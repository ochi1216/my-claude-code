# VERSION: 20260928_01
import os
import json
import re
import sys
import time
import threading
import traceback
import webbrowser
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from bs4 import BeautifulSoup, NavigableString
import msal
import requests as http_requests
# 変更点(20260812_01): 会社PCからGemini APIへの直接アクセスが遮断されたため、
# `from google import genai` を廃止し、共通モジュール gemini_client.py 経由
# （直接呼び出し→失敗時は自宅PCプロキシへ自動フォールバック）に移行した。
# types は types.GenerateContentConfig(...) の構築に引き続き使うため残す。
from google.genai import types

# ==========================================
# 設定読み込み
# ==========================================
def load_config(path="config.json"):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

CONFIG = load_config()

# ==========================================
# Gemini 共通モジュール（gemini_client.py）互換シム
# VERSION 20260812_01 で新規追加
#
# genai.Client と同じインターフェースだけを持つ薄い互換シム。
# これにより以下の既存処理は一切変更不要:
#   - response.text を読む処理
#   - response.usage_metadata.prompt_token_count / candidates_token_count
#   - types.GenerateContentConfig(...) による config 構築
# ==========================================
# 変更点(20260812_02): 本ツールは他ツールより1階層深い
#   PythonScripts\Onenote\onenote_report_generator\
# にあるため、既定の "../common" では PythonScripts\Onenote\common\ を探してしまい、
# 実際の配置先 PythonScripts\common\ に届かなかった。
# 環境変数 GEMINI_COMMON_DIR が最優先。未設定なら "../common" → "../../common" の順に
# gemini_client.py が実在するフォルダを自動探索する。
def _resolve_common_dirs():
    """gemini_client.py の探索先候補を優先順に返す。"""
    env_dir = os.environ.get("GEMINI_COMMON_DIR")
    if env_dir:
        return [env_dir]
    here = os.path.dirname(os.path.abspath(__file__))
    return [
        os.path.normpath(os.path.join(here, "..", "common")),        # 他ツールと同じ階層の場合
        os.path.normpath(os.path.join(here, "..", "..", "common")),  # 本ツールのようにもう1階層深い場合
    ]


_COMMON_DIR_CANDIDATES = _resolve_common_dirs()

# 実際に gemini_client.py が存在する候補を優先して sys.path へ入れる。
# 見つからなければ全候補を入れておく（エラーメッセージで全候補を提示するため）。
_COMMON_DIR = next(
    (d for d in _COMMON_DIR_CANDIDATES if os.path.isfile(os.path.join(d, "gemini_client.py"))),
    _COMMON_DIR_CANDIDATES[0],
)
for _d in _COMMON_DIR_CANDIDATES:
    if _d not in sys.path:
        sys.path.insert(0, _d)

# import を try/except にする理由: 共通モジュールが未配置・パス誤りのときに
# ツール自体が起動できなくなると、AIを使わない機能（OneNote閲覧・ブックマーク・
# 過去レポート閲覧）まで巻き添えで停止するため。起動は継続させ、実際にAI呼び出しが
# 行われた時点で原因の分かる RuntimeError を出す。
try:
    from gemini_client import generate_advanced as _generate_advanced
    _GEMINI_CLIENT_IMPORT_ERROR = None
except Exception as _e:
    _generate_advanced = None
    _GEMINI_CLIENT_IMPORT_ERROR = _e


def gemini_credentials_available() -> bool:
    """Gemini の認証情報が利用可能かを判定する。

    直接呼び出しが遮断されていてもプロキシ経由なら成功しうるため、
    GEMINI_API_KEY / GEMINI_PROXY_URL の**どちらか一方でも**あれば通す
    （プロキシ専用構成を誤って弾かないため）。
    旧来の config.json の GEMINI_API_KEY しか無い環境も止めない。
    """
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMINI_PROXY_URL"):
        return True
    try:
        return bool(CONFIG.get("GEMINI_API_KEY", ""))
    except Exception:
        return False


def _schema_to_jsonable(schema):
    """response_schema が SDK バージョンによって pydantic モデルへ自動変換された
    場合でも REST payload へ載せられるよう dict 化する保険。素のdictならそのまま返す。
    現状このツールは response_schema を使っていないが、将来使った場合に備えて残す。"""
    if schema is None or isinstance(schema, (dict, list, str, int, float, bool)):
        return schema
    for attr, kwargs in (("model_dump", {"mode": "json", "exclude_none": True, "by_alias": True}),
                         ("dict", {"exclude_none": True, "by_alias": True})):
        fn = getattr(schema, attr, None)
        if callable(fn):
            try:
                return fn(**kwargs)
            except Exception:
                try:
                    return fn()
                except Exception:
                    pass
    return schema


def _contents_to_payload_contents(contents):
    """SDK の contents 引数を Gemini REST の contents 形式へ変換する。

    本ツールは `contents=[prompt]`（文字列1個のリスト）で呼び出しているため、
    文字列・リストの両方に対応させている。
    （outlook_total_organizer は全て文字列だったが、本ツールはリスト形式）
    """
    if contents is None:
        parts = []
    elif isinstance(contents, str):
        parts = [{"text": contents}]
    elif isinstance(contents, (list, tuple)):
        parts = []
        for c in contents:
            if isinstance(c, str):
                parts.append({"text": c})
            elif isinstance(c, dict):
                parts.append(c)
            else:
                parts.append({"text": str(c)})
    else:
        parts = [{"text": str(contents)}]
    return [{"parts": parts}]


class _CommonUsageMetadata:
    def __init__(self, usage: dict):
        usage = usage if isinstance(usage, dict) else {}
        self.prompt_token_count     = usage.get("promptTokenCount", 0)
        self.candidates_token_count = usage.get("candidatesTokenCount", 0)


class _CommonGeminiResponse:
    def __init__(self, raw: dict):
        try:
            self.text = raw["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError):
            self.text = ""
        self.usage_metadata = _CommonUsageMetadata(
            raw.get("usageMetadata", {}) if isinstance(raw, dict) else {}
        )


class _CommonGeminiModels:
    def generate_content(self, model=None, contents=None, config=None):
        if _generate_advanced is None:
            raise RuntimeError(
                "Gemini共通モジュール(gemini_client.py)を読み込めませんでした。\n"
                f"探索したパス: {' / '.join(_COMMON_DIR_CANDIDATES)}\n"
                f"元のエラー: {_GEMINI_CLIENT_IMPORT_ERROR}\n"
                "gemini-common-tools を配置し、必要なら環境変数 GEMINI_COMMON_DIR で"
                "gemini_client.py のあるフォルダを指定してください。"
            )
        payload = {"contents": _contents_to_payload_contents(contents)}
        if config is not None:
            gen_cfg = {}
            mime = getattr(config, "response_mime_type", None)
            if mime:
                gen_cfg["responseMimeType"] = mime
            schema = getattr(config, "response_schema", None)
            if schema is not None:
                gen_cfg["responseSchema"] = _schema_to_jsonable(schema)
            temp = getattr(config, "temperature", None)
            if temp is not None:
                gen_cfg["temperature"] = temp
            if gen_cfg:
                payload["generationConfig"] = gen_cfg
        # model は必ず明示的に渡す。省略すると共通モジュール側の既定モデルに落ち、
        # 「UI上は別モデルを表示しているのに実際は flash が動く」silent failure になる。
        raw = _generate_advanced(payload, model=model)
        return _CommonGeminiResponse(raw)


class _CommonGeminiClient:
    """genai.Client(api_key=...) の代替。api_key は gemini_client.py 側が
    環境変数から読むため、互換性のために受け取るだけで使用しない。"""
    def __init__(self, api_key=None):
        self.models = _CommonGeminiModels()

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

    # 変更点(20260928_01): 青文字判定・HTML→テキスト抽出を刷新するための定数。
    # extract_with_color() 内の走査ロジックが参照する。
    _SKIP_TAGS      = {"head", "title", "style", "script", "meta", "link"}
    _LIST_TAGS      = {"ul", "ol"}
    _BLOCK_LINE_TAGS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6"}

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

    # ==========================================
    # 変更点(20260928_01): 青文字＝今週の更新の検出を全面刷新。
    #
    # 旧実装（20260812_02以前）の問題点（実測で確認済み）:
    #   ① 行まるごと青（<p><span style="color:rgb(...)">…</span></p>）が
    #      find_all の文書順走査で親<p>のテキストが先に黒として出力され、
    #      同一文言の子<span>が seen 重複除去で捨てられ、マーカーが付かない。
    #      これがOneNoteで最も一般的な書き方であり、最大の原因だった。
    #   ② is_blue() が color:rgb(...) 記法しか見ておらず、16進数
    #      （color:#0070c0）を検出できない。
    #   ③ 表のセル内の青は判定されず、table.decompose() で判定機会自体が
    #      失われる。
    #   ④ 行の一部だけ青の場合、同一テキストが複数回出力される。
    #
    # 新実装は soup.body を文書順に1回だけたどる「線形化」方式に置き換え、
    # テキストノード単位で色を解決してから行として組み立てる。
    # ==========================================

    def _parse_css_color(self, value: str):
        """CSSのcolor値（#rgb / #rrggbb / rgb() / rgba()）を(r,g,b)に変換する。
        解釈できない値（inherit, windowtext, 色名など）はNoneを返す。"""
        if not value:
            return None
        value = value.strip()
        m = re.match(r'^#([0-9a-fA-F]{3})$', value)
        if m:
            h = m.group(1)
            return tuple(int(c * 2, 16) for c in h)
        m = re.match(r'^#([0-9a-fA-F]{6})$', value)
        if m:
            h = m.group(1)
            return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
        m = re.match(r'^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*[\d.]+\s*)?\)$', value, re.I)
        if m:
            return tuple(int(m.group(i)) for i in (1, 2, 3))
        return None

    def _extract_color_rgb(self, style: str):
        """style属性文字列から color:（background-colorは除外）の値を取り出す。
        同一style内に複数回colorが指定されている場合はCSSの慣例どおり後勝ち。"""
        if not style:
            return None
        rgb = None
        for m in re.finditer(r'(?<![\w-])color\s*:\s*([^;]+)', style, re.I):
            parsed = self._parse_css_color(m.group(1))
            if parsed is not None:
                rgb = parsed
        return rgb

    def _rgb_is_blue(self, rgb) -> bool:
        bd = CONFIG.get("blue_detection", {"max_r": 100, "min_b": 100, "min_b_minus_r": 50})
        r, g, b = rgb
        return r < bd["max_r"] and b > bd["min_b"] and b > r + bd["min_b_minus_r"]

    def is_blue(self, style: str) -> bool:
        rgb = self._extract_color_rgb(style)
        if rgb is None:
            return False
        return self._rgb_is_blue(rgb)

    def _resolve_is_blue(self, el, inherited: bool) -> bool:
        """要素自身にcolor指定があればそれで判定し、無ければ親から継承した
        is_blueをそのまま使う（＝黒を明示したspanが青い親の中にあれば
        そのspanだけ黒になる）。"""
        style = el.get("style", "") if hasattr(el, "get") else ""
        rgb = self._extract_color_rgb(style)
        if rgb is None:
            return inherited
        return self._rgb_is_blue(rgb)

    def _is_negligible(self, text: str) -> bool:
        """空白・記号のみのテキストか（行全体が青かどうかの判定から除外する）。"""
        return re.sub(r'[\s\W]+', '', text, flags=re.UNICODE) == ""

    def _render_line(self, segments, prefix: str = "") -> str:
        """(text, is_blue) の列を1行の文字列に組み立てる。
        隣接する同色の断片は連結し、全体が青なら【更新ポイント】、
        一部だけ青なら該当部分を⟦⟧で囲む。"""
        merged = []
        for text, blue in segments:
            norm = re.sub(r'[ \t\r\n ]+', ' ', text)
            if norm == "":
                continue
            if merged and merged[-1][1] == blue:
                merged[-1] = (merged[-1][0] + norm, blue)
            else:
                merged.append((norm, blue))
        if not merged:
            return ""
        first_t, first_b = merged[0]
        merged[0] = (first_t.lstrip(), first_b)
        last_t, last_b = merged[-1]
        merged[-1] = (last_t.rstrip(), last_b)

        if not any(not self._is_negligible(t) for t, _ in merged):
            return ""

        has_any_blue     = any(b and not self._is_negligible(t) for t, b in merged)
        is_line_all_blue = all(self._is_negligible(t) or b for t, b in merged)

        if not has_any_blue:
            return prefix + "".join(t for t, _ in merged)
        if is_line_all_blue:
            return prefix + "【更新ポイント】" + "".join(t for t, _ in merged)
        parts = []
        for t, b in merged:
            if self._is_negligible(t):
                parts.append(t)
            elif b:
                parts.append(f"⟦{t}⟧")
            else:
                parts.append(t)
        return prefix + "【更新ポイント】" + "".join(parts)

    def _flush(self, buf, lines, prefix: str = ""):
        line = self._render_line(buf, prefix=prefix)
        if line:
            lines.append(line)
        buf.clear()

    def _has_block_descendant(self, el) -> bool:
        return el.find(["p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol"]) is not None

    def _block_prefix(self, name: str, list_depth: int) -> str:
        if name == "li":
            return "  " * max(list_depth - 1, 0) + "- "
        if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            return "# "
        return ""

    def _emit_block_line(self, el, inherited_blue, list_depth, lines, prefix: str = ""):
        own = []
        self._collect_into(el, inherited_blue, own, lines, list_depth, prefix=prefix)
        self._flush(own, lines, prefix=prefix)

    def _collect_into(self, el, inherited_blue, buf, lines, list_depth, prefix: str = ""):
        """1行分（p/li/h/leaf-div等）の内容を集める。span/a/b/strong/em/font等の
        インライン要素はここでbufへマージされ、同じ行として扱われる。
        prefixは呼び出し元（この行の所有者=p/li/h）の見出し・字下げ記号で、
        途中でbr/table/nested listにより行が分割された場合も同じprefixを
        引き継ぐ（例: <li>親<ul>...</ul>後続</li> の「親」と「後続」がどちらも
        「- 」付きの行になる）。"""
        for child in el.children:
            if isinstance(child, NavigableString):
                text = str(child)
                if text:
                    buf.append((text, inherited_blue))
                continue
            name = (child.name or "").lower()
            if name in self._SKIP_TAGS:
                continue
            if name == "br":
                self._flush(buf, lines, prefix=prefix)
                continue
            if name == "table":
                self._flush(buf, lines, prefix=prefix)
                self._extract_table(child, lines)
                continue
            child_blue = self._resolve_is_blue(child, inherited_blue)
            if name in self._LIST_TAGS:
                self._flush(buf, lines, prefix=prefix)
                self._process_children(child, child_blue, list_depth + 1, lines)
                continue
            if name in self._BLOCK_LINE_TAGS:
                self._flush(buf, lines, prefix=prefix)
                self._emit_block_line(child, child_blue, list_depth, lines, self._block_prefix(name, list_depth))
                continue
            if name == "div" and self._has_block_descendant(child):
                self._flush(buf, lines, prefix=prefix)
                self._process_children(child, child_blue, list_depth, lines)
                continue
            # span / a / b / strong / em / font / u / sup / sub / 葉div 等はマージ
            self._collect_into(child, child_blue, buf, lines, list_depth, prefix=prefix)

    def _process_children(self, container, inherited_blue, list_depth, lines):
        """body/div（グループ）/ul/ol/liの子を文書順に処理し、ブロック要素
        （p/li/h/table/leafなdiv）が現れるたびに1行を確定してlinesへ追加する。"""
        buf = []
        for child in container.children:
            if isinstance(child, NavigableString):
                text = str(child)
                if text:
                    buf.append((text, inherited_blue))
                continue
            name = (child.name or "").lower()
            if name in self._SKIP_TAGS:
                continue
            if name == "br":
                self._flush(buf, lines)
                continue
            if name == "table":
                self._flush(buf, lines)
                self._extract_table(child, lines)
                continue
            child_blue = self._resolve_is_blue(child, inherited_blue)
            if name in self._LIST_TAGS:
                self._flush(buf, lines)
                self._process_children(child, child_blue, list_depth + 1, lines)
                continue
            if name in self._BLOCK_LINE_TAGS:
                self._flush(buf, lines)
                self._emit_block_line(child, child_blue, list_depth, lines, self._block_prefix(name, list_depth))
                continue
            if self._has_block_descendant(child):
                self._flush(buf, lines)
                self._process_children(child, child_blue, list_depth, lines)
                continue
            # 葉div、または稀に直置きされたinline要素：単独の1行として確定
            self._flush(buf, lines)
            self._emit_block_line(child, child_blue, list_depth, lines, prefix="")
        self._flush(buf, lines)

    def _extract_table(self, table, lines):
        """表はtr直下のtd/thのみを対象にする。セル内に複数段落あれば" / "で
        連結し、入れ子の表はセル内の文字列として平坦化する（decomposeはしない
        ため、以前のように判定機会自体を失うことはない）。"""
        def _iter_rows(node):
            for child in node.find_all(["tbody", "thead", "tfoot", "tr"], recursive=False):
                if child.name == "tr":
                    yield child
                else:
                    yield from _iter_rows(child)
        rows = list(_iter_rows(table)) or table.find_all("tr")
        for row in rows:
            cells = row.find_all(["td", "th"], recursive=False) or row.find_all(["td", "th"])
            if not cells:
                continue
            cell_texts = []
            cell_has_blue = []
            for cell in cells:
                cell_blue = self._resolve_is_blue(cell, False)
                sub_lines = []
                self._process_children(cell, cell_blue, 0, sub_lines)
                any_blue = any(("【更新ポイント】" in l) or ("⟦" in l) for l in sub_lines)
                plain = [l.replace("【更新ポイント】", "").replace("⟦", "").replace("⟧", "") for l in sub_lines]
                cell_text = " / ".join(p for p in plain if p.strip())
                if not cell_text:
                    cell_text = cell.get_text(strip=True)
                cell_texts.append(cell_text)
                cell_has_blue.append(any_blue)
            if not any(c.strip() for c in cell_texts):
                continue
            line = "| " + " | ".join(cell_texts) + " |"
            if any(cell_has_blue):
                line = "【更新ポイント】" + line
            lines.append(line)

    def extract_with_color(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        root = soup.body if soup.body else soup
        lines = []
        self._process_children(root, False, 0, lines)
        return "\n".join(lines)


# ==========================================
# GeminiProcessor
# 変更点(20260729_02): 出力言語モード（日本語に翻訳 / 原文の言語を維持）を
# 選択できるように、プロンプト内の言語依存文字列を _LANG_VARIANTS に集約した。
# language_mode="translate_ja"（既定）の文言は変更前と完全一致させている。
#
# 変更点(20260928_01):
#   ① 青文字（【更新ポイント】/⟦⟧）を最優先として抽出するルールを全モード
#      共通のプロンプト固定部（analyze_html内）に追加した。従来ルール3は
#      「差分抽出を優先」としか書かれておらず、そもそも抽出処理側で
#      マーカーがほとんど付与されていなかった（extract_with_color刷新で対応）
#      ことに加え、サマリー欄の指示にも青文字優先の言及が無かったため
#      summary_hintにも追記した。
#   ② updates上限は3のまま維持（青文字の内容は統合して収め、削除しない）。
#   ③ 3つ目のモード "bilingual_ja_en"（日本語＋英語併記）を追加。
#      英語(en)を先に生成してから日本語(ja)を生成させる（表示は日本語が先）。
#      ja は英語からの再翻訳ではなく原文から直接執筆させる。
#      details / pending_actions は日本語のみ（越智さんの確認：英語の
#      読み手は自分と上司の確認用のため、summary/updatesのみ併記で足りる）。
# ==========================================
UPDATES_MAX = 3

_LANG_VARIANTS = {
    "translate_ja": {
        "directive_tail": "日本のビジネスシーンに最適な「自然な日本語」でJSONを出力してください。",
        "rule2": "2. 【完全日本語化】: 入力ソースが英語であっても全項目を日本語に翻訳・執筆すること。",
        "thinking_hint": "思考プロセス。英語入力時は翻訳方針をここで整理すること",
        "summary_hint": ("全体の進捗を300文字以内の自然な日本語で総括。冒頭で今週の進捗"
                         "（【更新ポイント】の内容）を述べ、黒文字は文脈の補足にのみ使うこと。"
                         "【更新ポイント】が無い場合はその旨が分かるように書くこと。箇条書き不可"),
        "category_label": "日本語カテゴリ名",
        "item_label": "日本語項目名",
        "task_hint": "日本語のタスク名",
        "exec_line": "ルールとスキーマ、および「完全翻訳」の指示を理解しました。解析を開始します。",
        "bilingual": False,
    },
    "keep_original": {
        "directive_tail": "入力ソースの言語（英語・日本語など）を翻訳せずそのまま維持してJSONを出力してください。",
        "rule2": ("2. 【原文言語の維持】: 入力ソースの言語を翻訳せずそのまま維持して執筆すること。"
                  "カテゴリ名・項目名（JSONのキーやラベル文字列）、タスク名も含め、"
                  "日本語ラベルへの置き換えは行わないこと。"),
        "thinking_hint": "思考プロセス。入力ソースの言語を判定し、その言語を維持する方針をここで整理すること",
        "summary_hint": ("全体の進捗を300文字以内で、原文の言語のまま自然に総括。冒頭で今週の進捗"
                         "（【更新ポイント】の内容）を述べ、黒文字は文脈の補足にのみ使うこと。"
                         "【更新ポイント】が無い場合はその旨が分かるように書くこと。箇条書き不可"),
        "category_label": "カテゴリ名（原文の言語のまま）",
        "item_label": "項目名（原文の言語のまま）",
        "task_hint": "タスク名（原文の言語のまま）",
        "exec_line": "ルールとスキーマ、および「原文言語維持」の指示を理解しました。解析を開始します。",
        "bilingual": False,
    },
    "bilingual_ja_en": {
        "directive_tail": ("日本語と英語（自分と上司が内容確認に使う英語）の両方でJSONを出力してください。"
                           "summary/updatesの各項目は英語(en)を先に執筆してから日本語(ja)を執筆すること。"),
        "rule2": ("2. 【日英併記】: en（英語）を先に書いてからja（日本語）を書くこと。ただしjaは"
                  "英語からの再翻訳にせず原文から直接執筆し、固有名詞・社内用語・型番・数値は"
                  "原文の表記を保つこと。en/jaは同じ事実を述べ、どちらか一方にだけ情報を足したり"
                  "削ったりしないこと。details・pending_actionsは日本語のみでよい。"),
        "thinking_hint": "思考プロセス。英語→日本語の順で執筆する方針をここで整理すること",
        "summary_hint_en": ("Summarize overall progress in English within 300 characters. Lead with "
                            "this week's progress (the 【更新ポイント】content); use black text only "
                            "as supporting context. If there is no 【更新ポイント】, make that clear."),
        "summary_hint": ("全体の進捗を300文字以内の自然な日本語で総括（英語からの再翻訳ではなく原文から"
                         "執筆すること）。冒頭で今週の進捗（【更新ポイント】の内容）を述べ、黒文字は"
                         "文脈の補足にのみ使うこと。【更新ポイント】が無い場合はその旨が分かるように書くこと。"
                         "箇条書き不可"),
        "category_label": "日本語カテゴリ名 / English category name",
        "item_label": "日本語項目名",
        "task_hint": "日本語のタスク名",
        "exec_line": "ルールとスキーマ、および「日英併記（英語を先に執筆）」の指示を理解しました。解析を開始します。",
        "bilingual": True,
    },
}

_INPUT_FORMAT_NOTE = """<input_format>
本文には抽出時に付与した以下の目印が含まれる場合がある（OneNote上の実際の文字ではない）。
- 【更新ポイント】: その行（または⟦⟧で囲まれた部分）が青文字＝今週の更新であることを示す
- ⟦...⟧: 青文字の部分（行の一部だけが青い場合）
- 行頭の「- 」「  - 」等: 箇条書きの階層（インデント2つ分で1階層深い）
- 行頭の「# 」: OneNote上の見出し
- 「| a | b |」: 表の1行
</input_format>"""

_COMMON_RULE3 = ("3. 【差分抽出（青文字優先）】: 【更新ポイント】と記載された行（⟦⟧内が青文字部分）が"
                 "今週の進捗である。updatesは原則としてこの内容から作成すること。黒文字は、青文字が"
                 "示す内容の対象・主語・前提を補うためにのみ使ってよく、黒文字単独の話題をupdatesに"
                 "含めてはならない。凡例や「青字＝更新」といった説明文自体は更新として扱わないこと。"
                 "ページ内に【更新ポイント】が1行も無い場合に限り、前回データとの比較で差分を抽出する"
                 "こと。マーカー（【更新ポイント】）や囲み記号（⟦⟧）はJSON出力にそのまま含めないこと。")


def _strip_markers(value):
    """抽出時に付与したマーカーをGeminiが出力へ写してしまった場合の保険。"""
    if isinstance(value, str):
        return value.replace("【更新ポイント】", "").replace("⟦", "").replace("⟧", "")
    return value


def _clean_updates_value(value):
    if isinstance(value, dict):
        return {k: _strip_markers(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean_updates_value(v) for v in value]
    return _strip_markers(value)


class GeminiProcessor:
    def __init__(self):
        # 変更点(20260812_01): 移行後は config.json の GEMINI_API_KEY が空でも
        # プロキシ経由で成功しうるため、APIキー必須のガードを廃止し、
        # GEMINI_API_KEY / GEMINI_PROXY_URL のどちらか一方でも通す判定に置き換えた。
        # （旧ガードのままだと移行後に全AI機能が例外で止まる）
        if not gemini_credentials_available():
            raise ValueError(
                "Geminiの認証情報が見つかりません。環境変数 GEMINI_API_KEY"
                "（直接呼び出し用）または GEMINI_PROXY_URL（自宅PCプロキシ用）の"
                "いずれかを設定してください。"
            )
        api_key = CONFIG.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
        self.client = _CommonGeminiClient(api_key=api_key)
        self.model  = CONFIG.get("GEMINI_MODEL", "gemini-2.5-flash")

    def analyze_html(self, html_content: str, prev_data=None, language_mode="translate_ja"):
        prev_info_str = json.dumps(prev_data, ensure_ascii=False) if prev_data else "なし"
        v = _LANG_VARIANTS.get(language_mode, _LANG_VARIANTS["translate_ja"])
        bilingual = v.get("bilingual", False)

        if bilingual:
            summary_schema = f'"summary_en": "string ({v["summary_hint_en"]})",\n  "summary": "string ({v["summary_hint"]})",'
            updates_item_schema = (
                '[{"en": "string (更新内容1・英語)", "ja": "string (更新内容1・日本語)"}, '
                '{"en": "string (更新内容2・英語)", "ja": "string (更新内容2・日本語)"}]'
            )
            # bilingual_ja_enではdetails/pending_actionsは日本語のみとする
            # （越智さんの確認：英語の読み手は自分と上司の確認用のため、
            # 併記が必要なのはsummary/updatesのみで足りる）。他の2モードは
            # 既存どおり「詳細内容」のまま（keep_originalで日本語化を強制
            # しないよう、この注記はbilingual限定にする）。
            detail_item_hint = "詳細内容・日本語"
        else:
            summary_schema = f'"summary": "string ({v["summary_hint"]})",'
            updates_item_schema = '["string (更新内容1)", "string (更新内容2)"]'
            detail_item_hint = "詳細内容"

        prompt = f"""<system_directive>
あなたは世界最高峰のITプロジェクトマネージャー兼データアナリストです。
入力されるOneNoteページのテキスト（英語または日本語）を解析し、提供された「前回データ」と比較した上で、{v["directive_tail"]}
</system_directive>

{_INPUT_FORMAT_NOTE}

<critical_rules>
1. 【出力形式の絶対固定】: markdownタグや説明テキストは一切出力せず、純粋なJSONのみを返却すること。
{v["rule2"]}
{_COMMON_RULE3}
4. 【情報の厳選】: updatesは各カテゴリ「絶対最大{UPDATES_MAX}項目」まで。青文字の内容が{UPDATES_MAX}項目を超える場合は、内容が近いものを統合して{UPDATES_MAX}項目以内に収めること。青文字の内容を理由なく削除・省略しないこと。
5. 【空データの処理】: 該当情報がない場合は必ず空文字("")、空リスト([])、空オブジェクト({{}})を返すこと。
</critical_rules>

<json_schema>
{{
  "_thinking": "string ({v["thinking_hint"]})",
  {summary_schema}
  "updates": {{
    "[{v["category_label"]}]": {updates_item_schema}
  }},
  "details": {{
    "[{v["category_label"]}]": {{
      "[{v["item_label"]}]": "string ({detail_item_hint})"
    }}
  }},
  "pending_actions": [
    {{
      "task_name": "string ({v["task_hint"]})",
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
{v["exec_line"]}
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
            # 変更点(20260928_01): マーカー（【更新ポイント】/⟦⟧）をGeminiが
            # 出力へ写してしまった場合の保険としてsummary/updatesから除去する。
            if isinstance(result.get("summary"), str):
                result["summary"] = _strip_markers(result["summary"])
            if isinstance(result.get("summary_en"), str):
                result["summary_en"] = _strip_markers(result["summary_en"])
            if isinstance(result.get("updates"), dict):
                result["updates"] = {k: _clean_updates_value(v2) for k, v2 in result["updates"].items()}
            elif isinstance(result.get("updates"), list):
                result["updates"] = _clean_updates_value(result["updates"])
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

    # 変更点(20260928_01): 日英併記モード(bilingual_ja_en)のupdates項目
    # {"en":..., "ja":...} を表示するためのレンダラ。文字列や、en/jaの
    # どちらかが欠けた場合、未知の形にも対応する（黙って消さない）。
    @staticmethod
    def _render_update_item(item):
        if isinstance(item, dict):
            ja = item.get("ja", "")
            en = item.get("en", "")
            if ja and en:
                return f"<li>{ja}<br><span class='en-sub' lang='en'>{en}</span></li>"
            if ja:
                return f"<li>{ja}</li>"
            if en:
                return f"<li lang='en'>{en}</li>"
            fallback = " / ".join(str(v) for v in item.values() if v)
            return f"<li>{fallback}</li>"
        return f"<li>{item}</li>"

    @staticmethod
    def generate_html(results, out_path, section_name="General", cost_info=None, language_mode="translate_ja"):
        bilingual_heading = (language_mode == "bilingual_ja_en")
        exec_summary_label = "【エグゼクティブ・サマリー】 / Executive Summary" if bilingual_heading else "【エグゼクティブ・サマリー】"
        updates_heading    = "主な更新内容 (差分) / Key Updates" if bilingual_heading else "主な更新内容 (差分)"
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
                .blue-stat {{ font-size: 12px; color: #7f8c8d; margin: -10px 0 10px 2px; }}
                .en-sub {{ font-size: 0.85em; color: #666; }}
                .more-note {{ color: #999; list-style-type: none; }}
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
            summary_en   = data.get('summary_en', '')
            updates      = data.get('updates', {})
            details      = data.get('details', {})

            # 変更点(20260928_01): 青文字の検出状況を各ページの見出し下に
            # 表示する（除外はせず警告のみ。運用ミス＝前週コピー残りの
            # 検出も含む）。
            blue_stats   = data.get('_blue_stats') or {}
            blue_lines   = blue_stats.get('blue_lines', 0)
            same_as_prev = blue_stats.get('same_as_prev', 0)
            stat_parts = []
            if blue_lines > 0:
                stat_parts.append(f"青文字 {blue_lines}行を検出")
            else:
                stat_parts.append("⚠ 青文字なし：前回データとの比較で推定")
            if same_as_prev > 0:
                stat_parts.append(f"⚠ 前週と同文の青 {same_as_prev}行（コピー残りの可能性）")
            blue_stat_html = f'<div class="blue-stat">{" ／ ".join(stat_parts)}</div>'

            summary_html = f"<strong>{exec_summary_label}</strong><br>{summary}"
            if summary_en:
                summary_html += f"<br><span class='en-sub' lang='en'>{summary_en}</span>"

            html_content += f"""
            <h2>{week_title}</h2>
            {blue_stat_html}
            <div class="summary-box">{summary_html}</div>
            """
            if updates:
                html_content += f"<h3>{updates_heading}</h3>"
                if isinstance(updates, dict):
                    for category, items in updates.items():
                        html_content += f"<h4>■ {category}</h4><ul>"
                        if isinstance(items, list):
                            for item in items[:UPDATES_MAX]:
                                html_content += ReportGenerator._render_update_item(item)
                            if len(items) > UPDATES_MAX:
                                html_content += f"<li class='more-note'>…他 {len(items) - UPDATES_MAX} 件</li>"
                        else:
                            html_content += ReportGenerator._render_update_item(items)
                        html_content += "</ul>"
                elif isinstance(updates, list):
                    html_content += "<ul>"
                    for u in updates[:UPDATES_MAX]:
                        html_content += ReportGenerator._render_update_item(u)
                    if len(updates) > UPDATES_MAX:
                        html_content += f"<li class='more-note'>…他 {len(updates) - UPDATES_MAX} 件</li>"
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
    language_mode = data.get("language_mode", "translate_ja")
    if not page_ids:
        return jsonify({"error": "ページが指定されていません"}), 400
    threading.Thread(
        target=_generate_worker,
        args=(page_ids, section_name, notebook_name, site_id, reverse_order, language_mode),
        daemon=True
    ).start()
    return jsonify({"status": "started"})

def _blue_lines_from_content(content: str):
    """extract_with_color()の出力から青文字行を抽出する。
    比較用に、マーカー・⟦⟧・前後空白を除いた文字列の集合も返す
    （前週コピー残りの検出に使う）。"""
    lines = [l for l in content.split("\n") if "【更新ポイント】" in l]
    normalized = {re.sub(r'[⟦⟧]', '', l.replace("【更新ポイント】", "")).strip() for l in lines}
    return lines, normalized


def _ja_only(value):
    """dict({"en","ja"}) / list / str のいずれでも日本語側だけを取り出す
    （bilingual_ja_enモードで次ページへ渡す前回データを日本語のみに絞る）。"""
    if isinstance(value, list):
        return [_ja_only(v) for v in value]
    if isinstance(value, dict):
        return value.get("ja") or value.get("en") or ""
    return value


def _build_prev_context(analyzed: dict, language_mode: str) -> dict:
    """次ページのGemini呼び出しに渡す「前回データ」を組み立てる。
    _blue_statsはGeminiへの入力を変えないよう常に除外する。
    bilingual_ja_enモードでは、前週の英文がそのまま次の出力に写り込むのを
    防ぎ、入力トークンも抑えるため、summary_enを除き、updatesは日本語側
    だけに絞る。"""
    ctx = {k: v for k, v in analyzed.items() if k != "_blue_stats"}
    if language_mode == "bilingual_ja_en":
        ctx.pop("summary_en", None)
        updates = ctx.get("updates")
        if isinstance(updates, dict):
            ctx["updates"] = {k: _ja_only(v) for k, v in updates.items()}
        elif isinstance(updates, list):
            ctx["updates"] = _ja_only(updates)
    return ctx


def _generate_worker(page_ids, section_name, notebook_name, site_id, reverse_order=True, language_mode="translate_ja"):
    try:
        update_status("running", "処理を開始します...", 0, len(page_ids))
        gen                  = GeminiProcessor()
        results              = []
        prev_context         = None
        prev_blue_normalized = set()
        total_input_tokens   = 0
        total_output_tokens  = 0

        for i, page in enumerate(page_ids):
            update_status("running", f"ページ取得中 ({i+1}/{len(page_ids)})", i, len(page_ids))
            html    = _extractor.get_page_html(_token, page["id"], site_id)
            content = _extractor.extract_with_color(html)
            print("[DEBUG extract]\n", content[:2000])
            # 変更点(20260928_01): 青文字（【更新ポイント】）の検出行数を
            # コンソールに出す。0件ならextract_with_color側の検出漏れの
            # 可能性が高く、レポート側の警告表示とあわせて実機診断に使う。
            blue_lines, blue_normalized = _blue_lines_from_content(content)
            same_as_prev = len(blue_normalized & prev_blue_normalized) if blue_normalized else 0
            print(f"[DEBUG blue] {len(blue_lines)}行検出" +
                  (f" / 先頭: {blue_lines[:3]}" if blue_lines else "") +
                  (f" / 前週と同文 {same_as_prev}行" if same_as_prev else ""))
            update_status("running", f"Gemini解析中 ({i+1}/{len(page_ids)})", i, len(page_ids))
            analyzed = gen.analyze_html(content, prev_data=prev_context, language_mode=language_mode)
            if isinstance(analyzed, list):
                analyzed = analyzed[0] if analyzed else {}

            token_usage          = analyzed.pop("_token_usage", {"input_tokens": 0, "output_tokens": 0})
            total_input_tokens  += token_usage.get("input_tokens",  0)
            total_output_tokens += token_usage.get("output_tokens", 0)

            onenote_link = page.get("links", {}).get("oneNoteWebUrl", {}).get("href", "#")
            analyzed.update({
                "week_title":   page.get("title", f"Page {i+1}"),
                "onenote_link": onenote_link,
                "_blue_stats":  {"blue_lines": len(blue_lines), "same_as_prev": same_as_prev},
            })
            results.append(analyzed)
            prev_context         = _build_prev_context(analyzed, language_mode)
            prev_blue_normalized = blue_normalized

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

        ReportGenerator.generate_html(html_results, out_path, section_name, cost_info=cost_info, language_mode=language_mode)
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
    print("OneNote Report Generator 20260928_01 を起動します...")
    print("ブラウザで http://localhost:5000 を開いてください")
    webbrowser.open("http://localhost:5000")
    app.run(debug=False, threaded=True, port=5000)
