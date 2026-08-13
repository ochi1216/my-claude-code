# VERSION: 20260729_01
import os
import json
import re
import time
import threading
import traceback
import webbrowser
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from bs4 import BeautifulSoup
import msal
import requests as http_requests
from google import genai
from google.genai import types

# ==========================================
# 設定読み込み
# ==========================================
def load_config(path="config.json"):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

CONFIG = load_config()

# ==========================================
# OneNoteGraphExtractor
# 変更点: 4メソッドのsite_idをconfig固定値から引数に変更
# 変更点(20260727_01): Graph APIの401をTokenExpiredErrorとして区別できるように変更
# ==========================================
class TokenExpiredError(Exception):
    """Graph APIがHTTP 401を返した場合に送出する（アクセストークン期限切れ検知用）。"""
    pass


class OneNoteGraphExtractor:
    SCOPES     = ["Notes.Read", "Sites.Read.All", "Group.Read.All"]
    GRAPH_BASE = "https://graph.microsoft.com/v1.0"

    def __init__(self):
        self.token_cache_path = "token_cache.bin"
        self.cache = msal.SerializableTokenCache()
        if os.path.exists(self.token_cache_path):
            with open(self.token_cache_path, "r") as f:
                self.cache.deserialize(f.read())
        self.msal_app = msal.PublicClientApplication(
            CONFIG["CLIENT_ID"],
            authority=f"https://login.microsoftonline.com/{CONFIG['TENANT_ID']}",
            token_cache=self.cache
        )

    def _save_cache(self):
        if self.cache.has_state_changed:
            with open(self.token_cache_path, "w") as f:
                f.write(self.cache.serialize())

    def get_token_from_cache(self):
        accounts = self.msal_app.get_accounts()
        if accounts:
            result = self.msal_app.acquire_token_silent(self.SCOPES, account=accounts[0])
            if result and "access_token" in result:
                self._save_cache()
                return result["access_token"]
        return None

    def initiate_device_flow(self):
        flow = self.msal_app.initiate_device_flow(scopes=self.SCOPES)
        if "user_code" not in flow:
            raise Exception("Device Code Flowの開始に失敗しました")
        return flow

    def acquire_token_by_flow(self, flow):
        result = self.msal_app.acquire_token_by_device_flow(flow)
        if "access_token" in result:
            self._save_cache()
            return result["access_token"]
        raise Exception(f"認証失敗: {result.get('error_description', '不明なエラー')}")

    def _headers(self, token):
        return {"Authorization": f"Bearer {token}"}

    def _get(self, token, url):
        resp = http_requests.get(url, headers=self._headers(token), timeout=60)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 401:
            raise TokenExpiredError(f"Graph API Error 401: {resp.text[:300]}")
        raise Exception(f"Graph API Error {resp.status_code}: {resp.text[:300]}")

    def get_notebooks(self, token, site_id):
        if site_id:
            url = f"{self.GRAPH_BASE}/sites/{site_id}/onenote/notebooks?$select=id,displayName"
        else:
            url = f"{self.GRAPH_BASE}/me/onenote/notebooks?$select=id,displayName"
        return self._get(token, url).get("value", [])

    def get_sections(self, token, notebook_id, site_id):
        if site_id:
            url = f"{self.GRAPH_BASE}/sites/{site_id}/onenote/notebooks/{notebook_id}/sections?$select=id,displayName"
        else:
            url = f"{self.GRAPH_BASE}/me/onenote/notebooks/{notebook_id}/sections?$select=id,displayName"
        return self._get(token, url).get("value", [])


    def get_pages(self, token, section_id, site_id):
        """ページ一覧を取得。
        createdDateTimeが全て同一（移行済み）→ API順（OneNote表示順）を維持
        createdDateTimeが異なる → 昇順ソート（古い→新しい）
        """
        if site_id:
            url = f"{self.GRAPH_BASE}/sites/{site_id}/onenote/sections/{section_id}/pages?$select=id,title,createdDateTime,links&$top=100"
        else:
            url = f"{self.GRAPH_BASE}/me/onenote/sections/{section_id}/pages?$select=id,title,createdDateTime,links&$top=100"
        pages = []
        while url:
            data = self._get(token, url)
            pages.extend(data.get("value", []))
            url  = data.get("@odata.nextLink")

        # createdDateTimeの日付部分（YYYY-MM-DD）が全て同一か確認
        dates = set(p.get("createdDateTime", "")[:10] for p in pages)
        if len(dates) <= 1:
            # 全て同一日付（移行済みセクション）→ API返却順を維持
            return pages
        else:
            # 日付が異なる → createdDateTime昇順ソート（古い→新しい）
            return sorted(pages, key=lambda p: p.get("createdDateTime", ""))

    def get_page_html(self, token, page_id, site_id):
        """ページのHTML本文を取得（リダイレクト対応）"""
        if site_id:
            url = f"{self.GRAPH_BASE}/sites/{site_id}/onenote/pages/{page_id}/content"
        else:
            url = f"{self.GRAPH_BASE}/me/onenote/pages/{page_id}/content"
        headers = self._headers(token)
        resp = http_requests.get(url, headers=headers, timeout=60, allow_redirects=False)
        if resp.status_code in (301, 302, 303, 307, 308):
            redirect_url = resp.headers.get("Location")
            resp = http_requests.get(redirect_url, headers=headers, timeout=60)
        if resp.status_code == 200:
            return resp.text
        raise Exception(f"ページHTML取得失敗 {resp.status_code}: {resp.text[:300]}")

    def is_blue(self, style: str) -> bool:
        if not style:
            return False
        bd = CONFIG.get("blue_detection", {"max_r": 100, "min_b": 100, "min_b_minus_r": 50})
        match = re.search(r'color:\s*rgb\((\d+),\s*(\d+),\s*(\d+)\)', style)
        if not match:
            return False
        r, g, b = int(match.group(1)), int(match.group(2)), int(match.group(3))
        return r < bd["max_r"] and b > bd["min_b"] and b > r + bd["min_b_minus_r"]


    def extract_with_color(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        result_lines = []
        seen = set()

        # --- 条件①②: テーブル専用処理（find_all より先に実行） ---
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            for row in rows:
                # <th> ヘッダ行（条件②: ヘッダも専用処理に含める）
                headers = row.find_all("th")
                if headers:
                    cells = [h.get_text(strip=True) for h in headers]
                    line  = "| " + " | ".join(cells) + " |"
                    if line not in seen:
                        seen.add(line)
                        result_lines.append(line)
                    continue
                # <td> データ行
                tds = row.find_all("td")
                if not tds:
                    continue
                cells = [td.get_text(strip=True) for td in tds]
                # 全セルが空の行はスキップ
                if not any(cells):
                    continue
                line = "| " + " | ".join(cells) + " |"
                if line not in seen:
                    seen.add(line)
                    result_lines.append(line)
            # 条件①: テーブルをsoupから物理除去し、以降のfind_allとの二重出力を遮断
            table.decompose()

        # --- 既存処理: "td" を除外済みタグリストで非テーブル要素を抽出 ---
        for element in soup.find_all(["p", "span", "li", "h1", "h2", "h3"]):
            text = element.get_text(strip=True)
            if not text or text in seen:
                continue
            seen.add(text)
            style = element.get("style", "")
            is_blue_text = self.is_blue(style)
            if not is_blue_text:
                parent = element.find_parent(style=True)
                if parent:
                    is_blue_text = self.is_blue(parent.get("style", ""))
            if is_blue_text:
                result_lines.append(f"【更新ポイント】{text}")
            else:
                result_lines.append(text)
        return "\n".join(result_lines)


# ==========================================
# GeminiProcessor（完全無修正）
# ==========================================
class GeminiProcessor:
    def __init__(self):
        api_key = CONFIG.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEYが設定されていません。")
        self.client = genai.Client(api_key=api_key)
        self.model  = CONFIG.get("GEMINI_MODEL", "gemini-2.5-flash")

    def analyze_html(self, html_content: str, prev_data=None):
        prev_info_str = json.dumps(prev_data, ensure_ascii=False) if prev_data else "なし"
        prompt = f"""<system_directive>
あなたは世界最高峰のITプロジェクトマネージャー兼データアナリストです。
入力されるOneNoteページのテキスト（英語または日本語）を解析し、提供された「前回データ」と比較した上で、日本のビジネスシーンに最適な「自然な日本語」でJSONを出力してください。
</system_directive>

<critical_rules>
1. 【出力形式の絶対固定】: markdownタグや説明テキストは一切出力せず、純粋なJSONのみを返却すること。
2. 【完全日本語化】: 入力ソースが英語であっても全項目を日本語に翻訳・執筆すること。
3. 【差分抽出】: 【更新ポイント】と記載された行を先週からの変更・更新事項として優先的に抽出すること。黒文字は背景情報としてdetailsに格納すること。
4. 【情報の厳選】: updatesは各カテゴリ「絶対最大3項目」まで。
5. 【空データの処理】: 該当情報がない場合は必ず空文字("")、空リスト([])、空オブジェクト({{}})を返すこと。
</critical_rules>

<json_schema>
{{
  "_thinking": "string (思考プロセス。英語入力時は翻訳方針をここで整理すること)",
  "summary": "string (全体の進捗を300文字以内の自然な日本語で総括。箇条書き不可)",
  "updates": {{
    "[日本語カテゴリ名]": ["string (更新内容1)", "string (更新内容2)"]
  }},
  "details": {{
    "[日本語カテゴリ名]": {{
      "[日本語項目名]": "string (詳細内容)"
    }}
  }},
  "pending_actions": [
    {{
      "task_name": "string (日本語のタスク名)",
      "assignee": "string (担当者)",
      "deadline": "string (期限)",
      "status": "string (ステータス)"
    }}
  ]
}}
</json_schema>

<context_data>
【前回データ（差分比較用）】
{prev_info_str}
</context_data>

<page_content>
{html_content}
</page_content>

<execution>
ルールとスキーマ、および「完全翻訳」の指示を理解しました。解析を開始します。
</execution>"""

        response = self.client.models.generate_content(
            model=self.model,
            contents=[prompt],
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        try:
            result = json.loads(response.text)
            usage  = response.usage_metadata
            result["_token_usage"] = {
                "input_tokens":  getattr(usage, "prompt_token_count",     0) if usage else 0,
                "output_tokens": getattr(usage, "candidates_token_count", 0) if usage else 0
            }
            return result
        except Exception as e:
            print(f"[ERROR] JSON Parse Failed: {e}")
            return {"summary": "解析エラー", "updates": {}, "details": response.text,
                    "pending_actions": [], "_token_usage": {"input_tokens": 0, "output_tokens": 0}}


# ==========================================
# ReportGenerator
# 変更点(20260727_01): 詳細情報(details)が3階層以上ネストした場合に
# 生のPython辞書表記(例: {'宮崎': {...}})がそのまま出力される不具合を修正
# ==========================================
class ReportGenerator:
    @staticmethod
    def _render_detail_value(key, val, level):
        """detailsの値を再帰的にレンダリングする。
        valが辞書の場合は見出し(h5, h6, ...)を掘り下げ、文字列の場合は箇条書きにする。
        """
        if isinstance(val, dict):
            heading_level = min(level, 6)
            html = f"<h{heading_level}>■ {key}</h{heading_level}>"
            for sub_key, sub_val in val.items():
                html += ReportGenerator._render_detail_value(sub_key, sub_val, level + 1)
            return html
        else:
            return f"・<strong>{key}</strong>: {val}<br>"

    @staticmethod
    def generate_html(results, out_path, section_name="General", cost_info=None):
        html_content = f"""<!DOCTYPE html>
        <html lang="ja">
        <head>
            <meta charset="UTF-8">
            <title>Weekly Report - {section_name}</title>
            <style>
                body {{ font-family: 'Segoe UI', Meiryo, sans-serif; margin: 20px; color: #333; }}
                h1 {{ border-bottom: 2px solid #2c3e50; padding-bottom: 5px; color: #2c3e50; }}
                h2 {{ background-color: #ecf0f1; padding: 10px; border-left: 5px solid #3498db; margin-top: 30px; }}
                h3 {{ color: #2980b9; margin-bottom: 10px; border-bottom: 1px solid #bdc3c7; padding-bottom: 3px; }}
                h4 {{ color: #2c3e50; margin-bottom: 5px; margin-top: 15px; }}
                h5 {{ color: #34495e; margin: 10px 0 4px 12px; font-size: 0.95em; }}
                h6 {{ color: #7f8c8d; margin: 6px 0 3px 24px; font-size: 0.9em; font-weight: 600; }}
                .summary-box {{ background-color: #e8f8f5; padding: 15px; border-radius: 5px; border-left: 5px solid #1abc9c; margin-bottom: 20px; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
                th, td {{ border: 1px solid #bdc3c7; padding: 8px; text-align: left; }}
                th {{ background-color: #34495e; color: white; }}
                .action-item {{ background-color: #fff3e0; border-left-color: #e67e22; }}
                .link-btn {{ display: inline-block; margin-top: 15px; padding: 8px 15px; background-color: #8e44ad; color: white; text-decoration: none; border-radius: 3px; font-size: 0.9em; }}
                details {{ margin-bottom: 15px; background-color: #fdfdfd; }}
                summary {{ cursor: pointer; font-weight: bold; background-color: #f7f9f9; padding: 10px; border-left: 4px solid #3498db; list-style-type: none; }}
                summary::-webkit-details-marker {{ display: none; }}
                details[open] summary {{ border-bottom: 1px solid #ecf0f1; }}
                .details-content {{ padding: 10px 15px; border: 1px solid #ecf0f1; border-top: none; line-height: 1.6; }}
                .cost-footer {{ margin-top: 40px; padding: 15px; background: #f8f9fa; border-top: 2px solid #dee2e6; font-size: 12px; color: #666; }}
            </style>
        </head>
        <body>
            <h1>Weekly Report [{section_name}]</h1>
            <p>Generated: {time.strftime("%Y/%m/%d %H:%M")}</p>
        """
        for data in results:
            week_title   = data.get('week_title', 'Unknown Week')
            onenote_link = data.get('onenote_link', '#')
            summary      = data.get('summary', '要約なし')
            updates      = data.get('updates', {})
            details      = data.get('details', {})
            html_content += f"""
            <h2>{week_title}</h2>
            <div class="summary-box"><strong>【エグゼクティブ・サマリー】</strong><br>{summary}</div>
            """
            if updates:
                html_content += "<h3>主な更新内容 (差分)</h3>"
                if isinstance(updates, dict):
                    for category, items in updates.items():
                        html_content += f"<h4>■ {category}</h4><ul>"
                        if isinstance(items, list):
                            for item in items[:3]:
                                html_content += f"<li>{item}</li>"
                        else:
                            html_content += f"<li>{items}</li>"
                        html_content += "</ul>"
                elif isinstance(updates, list):
                    html_content += "<ul>"
                    for u in updates[:3]:
                        html_content += f"<li>{u}</li>"
                    html_content += "</ul>"
            if details:
                html_content += '<details><summary>■ 詳細情報 (クリックして展開)</summary><div class="details-content">'
                if isinstance(details, dict):
                    for category, content in details.items():
                        html_content += f"<h4>■ {category}</h4>"
                        if isinstance(content, dict):
                            for key, val in content.items():
                                html_content += ReportGenerator._render_detail_value(key, val, 5)
                            html_content += "<br>"
                        else:
                            formatted = re.sub(r'(?<!^)\s+(?=\d+\.\s)', '<br><br>', str(content).strip())
                            html_content += f"<p>{formatted}</p>"
                else:
                    html_content += f"<p>{details}</p>"
                html_content += '</div></details>'
            actions_html = ""
            for a in data.get('pending_actions', []):
                if isinstance(a, dict):
                    actions_html += f"<tr><td>{a.get('task_name','')}</td><td>{a.get('assignee','')}</td><td>{a.get('deadline','')}</td><td>{a.get('status','')}</td></tr>"
                else:
                    actions_html += f"<tr><td colspan='4'>{str(a)}</td></tr>"
            if actions_html:
                html_content += f"""<details><summary class="action-item">■ 残アクション (クリックして展開)</summary>
                <div class="details-content"><table>
                <tr><th>タスク名</th><th>担当者</th><th>期限</th><th>ステータス</th></tr>
                {actions_html}</table></div></details>"""
            if onenote_link != '#':
                html_content += f'<a href="{onenote_link}" class="link-btn">📌 OneNoteで元のページを開く</a>'
            html_content += "<hr style='margin-top: 40px; border: 1px dashed #ccc;'>"

        if cost_info:
            html_content += f"""
        <div class="cost-footer">
            <strong>【Gemini API 概算使用料金】</strong><br>
            モデル: {cost_info.get('model', 'gemini-2.5-flash')} &nbsp;|&nbsp;
            入力トークン: {cost_info.get('input_tokens', 0):,} &nbsp;|&nbsp;
            出力トークン: {cost_info.get('output_tokens', 0):,}<br>
            概算費用: 約 {cost_info.get('cost_usd', 0):.4f} USD
            （約 {cost_info.get('cost_jpy', 0):.1f} 円）<br>
            ※ Gemini 2.5 Flash料金基準（$0.30/$2.50 per 1Mトークン）・
            1USD={cost_info.get('usd_to_jpy', 157)}円換算（2026年5月時点）
        </div>"""

        html_content += "</body></html>"
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(html_content)


# ==========================================
# グローバル状態管理（無修正）
# ==========================================
_token       = None
_auth_flow   = None
_auth_state  = {"ready": False, "error": None}
_status      = {"state": "idle", "message": "待機中", "progress": 0, "total": 0, "report_path": ""}
_status_lock = threading.Lock()
_extractor   = OneNoteGraphExtractor()
# --- ブックマーク機能: 新規追加 ---
_bookmark_lock = threading.Lock()
BOOKMARKS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bookmarks.json")

def update_status(state, message, progress=0, total=0, report_path=""):
    with _status_lock:
        _status.update({"state": state, "message": message,
                        "progress": progress, "total": total, "report_path": report_path})

def _load_bookmarks() -> dict:
    """bookmarks.jsonを読み込む。破損時は.bakにリネームして空データで再生成。"""
    if not os.path.exists(BOOKMARKS_PATH):
        return {"bookmarks": []}
    try:
        with open(BOOKMARKS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        bak = BOOKMARKS_PATH + ".bak"
        try:
            os.rename(BOOKMARKS_PATH, bak)
            print(f"[WARN] bookmarks.json が破損していたため {bak} にリネームしました。空データで再起動します。")
        except OSError:
            pass
        return {"bookmarks": []}


def _save_bookmarks(data: dict) -> None:
    """bookmarks.jsonにアトミック書き込み（tmp→rename）。プロセスKillによる破損を防止。"""
    tmp = BOOKMARKS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, BOOKMARKS_PATH)

# ==========================================
# Flask アプリケーション
# ==========================================
app = Flask(__name__)

# ==========================================
# ブックマーク エンドポイント（新規追加）
# ==========================================
@app.route("/api/bookmarks", methods=["GET"])
def api_bookmarks_get():
    """全ブックマーク一覧を返す。"""
    with _bookmark_lock:
        data = _load_bookmarks()
    return jsonify(data.get("bookmarks", []))


@app.route("/api/bookmarks", methods=["POST"])
def api_bookmarks_post():
    """現在の選択状態をブックマークとして保存する。"""
    body = request.json or {}
    label         = body.get("label", "").strip()
    site_id       = body.get("site_id", "")
    site_name     = body.get("site_name", "")
    notebook_id   = body.get("notebook_id", "")
    notebook_name = body.get("notebook_name", "")
    section_id    = body.get("section_id", "")
    section_name  = body.get("section_name", "")
    page_ids      = body.get("page_ids", [])
    range_type    = body.get("range_type", "latest1")
    page_count    = body.get("page_count", 4)

    # ラベル自動補完
    if not label:
        latest_title = page_ids[-1].get("title", "") if page_ids else ""
        label = f"{section_name} / {latest_title}" if latest_title else section_name

    with _bookmark_lock:
        data = _load_bookmarks()
        bookmarks = data.get("bookmarks", [])

        # 重複ラベルにサフィックス付与
        existing_labels = {bm["label"] for bm in bookmarks}
        original_label  = label
        suffix = 2
        while label in existing_labels:
            label = f"{original_label} ({suffix})"
            suffix += 1

        bm_id = f"bm_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        bookmarks.append({
            "id":            bm_id,
            "label":         label,
            "site_id":       site_id,
            "site_name":     site_name,
            "notebook_id":   notebook_id,
            "notebook_name": notebook_name,
            "section_id":    section_id,
            "section_name":  section_name,
            "page_ids":      page_ids,
            "range_type":    range_type,
            "page_count":    page_count,
            "created_at":    datetime.now().isoformat()
        })
        data["bookmarks"] = bookmarks
        _save_bookmarks(data)
    return jsonify({"status": "saved", "id": bm_id, "label": label}), 201


@app.route("/api/bookmarks/<bm_id>", methods=["DELETE"])
def api_bookmarks_delete(bm_id):
    """指定IDのブックマークを削除する。"""
    with _bookmark_lock:
        data = _load_bookmarks()
        bookmarks = data.get("bookmarks", [])
        new_list  = [bm for bm in bookmarks if bm["id"] != bm_id]
        if len(new_list) == len(bookmarks):
            return jsonify({"error": "指定されたブックマークが見つかりません"}), 404
        data["bookmarks"] = new_list
        _save_bookmarks(data)
    return jsonify({"status": "deleted"})

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/auth/status")
def auth_status():
    global _token, _auth_flow, _auth_state
    if _token:
        return jsonify({"authenticated": True})
    cached = _extractor.get_token_from_cache()
    if cached:
        _token = cached
        return jsonify({"authenticated": True})
    flow = _extractor.initiate_device_flow()
    _auth_flow  = flow
    _auth_state = {"ready": False, "error": None}
    def _auth_worker():
        global _token
        try:
            token  = _extractor.acquire_token_by_flow(flow)
            _token = token
            _auth_state["error"] = None
        except Exception as e:
            _auth_state["error"] = str(e)
        finally:
            _auth_state["ready"] = True
    threading.Thread(target=_auth_worker, daemon=True).start()
    return jsonify({"authenticated": False, "message": flow.get("message", "")})

@app.route("/api/auth/poll")
def auth_poll():
    if _token:
        return jsonify({"authenticated": True})
    if _auth_state.get("ready"):
        if _auth_state.get("error"):
            return jsonify({"authenticated": False, "error": _auth_state["error"]})
        return jsonify({"authenticated": True})
    return jsonify({"authenticated": False, "pending": True})

@app.route("/api/sites")
def api_sites():
    sites = CONFIG.get("sites", [])
    return jsonify(sites)

@app.route("/api/notebooks")
def api_notebooks():
    global _token
    if not _token:
        return jsonify({"error": "未認証"}), 401
    site_id = request.args.get("site_id", "")
    try:
        return jsonify(_extractor.get_notebooks(_token, site_id))
    except TokenExpiredError:
        _token = None
        return jsonify({"error": "認証の有効期限が切れました。再認証してください。", "auth_expired": True}), 401
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/sections/<notebook_id>")
def api_sections(notebook_id):
    global _token
    if not _token:
        return jsonify({"error": "未認証"}), 401
    site_id = request.args.get("site_id", "")
    try:
        return jsonify(_extractor.get_sections(_token, notebook_id, site_id))
    except TokenExpiredError:
        _token = None
        return jsonify({"error": "認証の有効期限が切れました。再認証してください。", "auth_expired": True}), 401
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/pages/<section_id>")
def api_pages(section_id):
    global _token
    if not _token:
        return jsonify({"error": "未認証"}), 401
    site_id = request.args.get("site_id", "")
    try:
        return jsonify(_extractor.get_pages(_token, section_id, site_id))
    except TokenExpiredError:
        _token = None
        return jsonify({"error": "認証の有効期限が切れました。再認証してください。", "auth_expired": True}), 401
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/generate", methods=["POST"])
def generate():
    data          = request.json
    page_ids      = data.get("page_ids", [])
    section_name  = data.get("section_name", "General")
    notebook_name = data.get("notebook_name", "Notebook")
    site_id       = data.get("site_id", "")
    reverse_order = data.get("reverse_order", True)
    if not page_ids:
        return jsonify({"error": "ページが指定されていません"}), 400
    threading.Thread(
        target=_generate_worker, args=(page_ids, section_name, notebook_name, site_id, reverse_order), daemon=True
    ).start()
    return jsonify({"status": "started"})

def _generate_worker(page_ids, section_name, notebook_name, site_id, reverse_order=True):
    try:
        update_status("running", "処理を開始します...", 0, len(page_ids))
        gen                 = GeminiProcessor()
        results             = []
        prev_context        = None
        total_input_tokens  = 0
        total_output_tokens = 0

        for i, page in enumerate(page_ids):
            update_status("running", f"ページ取得中 ({i+1}/{len(page_ids)})", i, len(page_ids))
            html    = _extractor.get_page_html(_token, page["id"], site_id)
            content = _extractor.extract_with_color(html)
            print("[DEBUG extract]\n", content[:2000])
            update_status("running", f"Gemini解析中 ({i+1}/{len(page_ids)})", i, len(page_ids))
            analyzed = gen.analyze_html(content, prev_data=prev_context)
            if isinstance(analyzed, list):
                analyzed = analyzed[0] if analyzed else {}

            token_usage          = analyzed.pop("_token_usage", {"input_tokens": 0, "output_tokens": 0})
            total_input_tokens  += token_usage.get("input_tokens",  0)
            total_output_tokens += token_usage.get("output_tokens", 0)

            onenote_link = page.get("links", {}).get("oneNoteWebUrl", {}).get("href", "#")
            analyzed.update({
                "week_title":   page.get("title", f"Page {i+1}"),
                "onenote_link": onenote_link
            })
            results.append(analyzed)
            prev_context = analyzed

        pricing  = CONFIG.get("gemini_pricing", {
            "input_per_million":  0.30,
            "output_per_million": 2.50,
            "usd_to_jpy":         157
        })
        cost_usd  = (total_input_tokens  / 1_000_000 * pricing["input_per_million"] +
                     total_output_tokens / 1_000_000 * pricing["output_per_million"])
        cost_jpy  = cost_usd * pricing["usd_to_jpy"]
        cost_info = {
            "model":         CONFIG.get("GEMINI_MODEL", "gemini-2.5-flash"),
            "input_tokens":  total_input_tokens,
            "output_tokens": total_output_tokens,
            "cost_usd":      cost_usd,
            "cost_jpy":      cost_jpy,
            "usd_to_jpy":    pricing["usd_to_jpy"]
        }

        update_status("running", "HTMLレポート生成中...", len(page_ids), len(page_ids))
        rep_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
        os.makedirs(rep_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        def _safe(s):
            return re.sub(r'[\\/:*?"<>|\s]', '_', str(s))

        latest_title = page_ids[-1].get("title", "unknown") if page_ids else "unknown"
        fname    = f"ON_summary_{_safe(notebook_name)}_{_safe(section_name)}_{_safe(latest_title)}_{ts}.html"
        out_path = os.path.join(rep_dir, fname)

        # 変更点(20260729_01): Gemini解析の処理順（差分抽出の基準）には一切手を
        # 加えず、HTMLへ書き出す直前の表示順のみをチェックボックスの指定に従って
        # 反転する。reverse_order=True（既定）で新→古に並べ替える。
        html_results = list(reversed(results)) if reverse_order else results

        ReportGenerator.generate_html(html_results, out_path, section_name, cost_info=cost_info)
        update_status("done", "レポート生成完了！", len(page_ids), len(page_ids), out_path)
    except Exception as e:
        print(f"[ERROR] {traceback.format_exc()}")
        update_status("error", f"エラー: {str(e)}")

@app.route("/status")
def status():
    with _status_lock:
        return jsonify(dict(_status))

@app.route("/reports")
def reports_list():
    rep_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
    os.makedirs(rep_dir, exist_ok=True)
    files = sorted([f for f in os.listdir(rep_dir) if f.endswith(".html")], reverse=True)
    return jsonify(files)

@app.route("/reports/open/<filename>")
def open_report(filename):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports", filename)
    if os.path.exists(path):
        webbrowser.open(path)
        return jsonify({"status": "opened"})
    return jsonify({"error": "ファイルが見つかりません"}), 404

@app.route("/reports/cleanup", methods=["POST"])
def cleanup_reports():
    rep_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
    cutoff  = time.time() - (7 * 24 * 60 * 60)
    deleted = 0
    for f in os.listdir(rep_dir):
        path = os.path.join(rep_dir, f)
        if f.endswith(".html") and os.path.getmtime(path) < cutoff:
            os.remove(path)
            deleted += 1
    return jsonify({"deleted": deleted})

if __name__ == "__main__":
    print("OneNote Report Generator 20260729_01 を起動します...")
    print("ブラウザで http://localhost:5000 を開いてください")
    webbrowser.open("http://localhost:5000")
    app.run(debug=False, threaded=True, port=5000)
