import win32com.client
import pythoncom
import time
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import ttk, messagebox
import tkinter.font as tkfont
import threading
import json
import re
import os
import webbrowser
import queue
import shutil
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from google import genai
from google.genai import types
import requests
from bs4 import BeautifulSoup


# ============================================================
# 設定・データ管理
# ============================================================

CONFIG_FILE            = "json/mail_manager_config.json"
EXCLUDED_DOMAINS_FILE  = "json/excluded_domains.json"
PROJECT_KNOWLEDGE_FILE = "json/project_knowledge.json"

EXCHANGE_RATE_YEN      = 160.0
PRICE_INPUT_1M_USD     = 0.075
PRICE_OUTPUT_1M_USD    = 0.30

COCKPIT_LAST_RESULT_FILE = "json/cockpit_last_result.json"
PROJECT_LAST_RESULT_FILE = "json/project_last_result_latest.json"
STAFF_LAST_RESULT_FILE   = "json/staff_last_result_latest.json"

ACTION_STATUS_FILE            = "json/action_status.json"
ACTION_DASHBOARD_LAST_RESULT_FILE = "json/action_dashboard_last_result.json"
OUTLOOK_RESTART_STATE_FILE    = "json/outlook_restart_state.json"

SEARCH_FOLDER_TOME = "未(ToMe)"
SEARCH_FOLDER_WITHME = "未(WithMe)"
SEARCH_FOLDER_CCME = "未(CcMe)"


DEFAULT_CONFIG = {
    "gemini_api_key": "",
    "output_folder": "./mail_reports",
    "default_period_days": 7,
    "gemini_model": "gemini-2.5-flash"
}


def load_config():
    os.makedirs("json", exist_ok=True)
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
            for key, value in DEFAULT_CONFIG.items():
                if key not in config:
                    config[key] = value
            return config
    return DEFAULT_CONFIG.copy()

def save_config(config):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

def load_excluded_domains():
    if os.path.exists(EXCLUDED_DOMAINS_FILE):
        try:
            with open(EXCLUDED_DOMAINS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return set(d.strip().lower() for d in data if d and d.strip() and '.' in d)
        except:
            return set()
    return set()

def save_excluded_domains(domains):
    with open(EXCLUDED_DOMAINS_FILE, 'w', encoding='utf-8') as f:
        json.dump(list(domains), f, indent=2, ensure_ascii=False)



def load_project_knowledge():
    default_knowledge = {
        "common_settings": {
            "my_role": "プロジェクトマネージャーとして全体の進行管理と課題解決を担当します。",
            "stakeholders": "Aさん: 営業窓口\nBさん: 開発担当"
        },
        "projects": {
            "00_Caracal": {"history_summary": "", "human_answers": "", "priority": "中"},
            "01_Wheeling": {"history_summary": "", "human_answers": "", "priority": "中"},
            "02_GrandTeton": {"history_summary": "", "human_answers": "", "priority": "中"},
            "03_R19Projects": {"history_summary": "", "human_answers": "", "priority": "中"}
        }
    }
    if os.path.exists(PROJECT_KNOWLEDGE_FILE):
        try:
            with open(PROJECT_KNOWLEDGE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # 欠損キーの補完
                for k, v in default_knowledge.items():
                    if k not in data: data[k] = v
                for pk, pv in default_knowledge["projects"].items():
                    if pk not in data["projects"]: data["projects"][pk] = pv
                # 既存ファイルに priority キーが無い場合の補完(統括コックピットv2用、既定"中")
                for pk in data["projects"]:
                    if "priority" not in data["projects"][pk]:
                        data["projects"][pk]["priority"] = "中"
                return data
        except:
            pass
    return default_knowledge

def save_project_knowledge(data):
    if os.path.exists(PROJECT_KNOWLEDGE_FILE):
        backup_dir = Path("knowledge_backups")
        backup_dir.mkdir(exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        shutil.copy2(PROJECT_KNOWLEDGE_FILE, backup_dir / f"project_knowledge_{ts}.json")
    with open(PROJECT_KNOWLEDGE_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_action_status():
    """アクションダッシュボードの手動ステータス（進捗・優先度・コメント）を読み込む"""
    os.makedirs("json", exist_ok=True)
    if os.path.exists(ACTION_STATUS_FILE):
        try:
            with open(ACTION_STATUS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: return {}
    return {}

def save_action_status(data):
    os.makedirs("json", exist_ok=True)
    with open(ACTION_STATUS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_outlook_restart_state():
    """Outlook再起動検知用に、前回確認したOutlookプロセスの起動時刻マーカーを読み込む"""
    os.makedirs("json", exist_ok=True)
    if os.path.exists(OUTLOOK_RESTART_STATE_FILE):
        try:
            with open(OUTLOOK_RESTART_STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: return {}
    return {}

def save_outlook_restart_state(data):
    os.makedirs("json", exist_ok=True)
    with open(OUTLOOK_RESTART_STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def make_action_key(conversation_id: str, owner: str, action: str) -> str:
    """[旧方式] スレッドID+依頼者+アクション文言の先頭部分から安定キーを作る。
    AIが再解析のたびに owner/action の言い回しを変えると別キーになりステータスが
    リセットされてしまう問題があったため、現在は make_action_key_by_index に置き換え済み。
    既存ユーザーが過去にこのキーで保存したステータスを引き継ぐための後方互換関数として残す。"""
    import hashlib
    raw = f"{conversation_id}::{owner}::{str(action)[:40]}"
    return hashlib.md5(raw.encode('utf-8')).hexdigest()

def make_action_key_by_index(conversation_id: str, index: int) -> str:
    """[新方式] スレッドID + そのスレッド内でのアクションの並び順(0始まり)から安定キーを作る。
    AIが再解析でowner/actionの文言を変えても、同じスレッド内のアクション数・順序が
    変わらない限り(1スレッド1アクションの最頻出ケースでは常に)キーが変わらない。"""
    import hashlib
    raw = f"{conversation_id}::idx{index}"
    return hashlib.md5(raw.encode('utf-8')).hexdigest()

def _mail_has_just_do_it_category(categories: str) -> bool:
    """カテゴリ文字列(';'または','区切り)に大文字小文字を問わず"Just Do It"が含まれるか判定する。
    OutlookのVBA(ThisOutlookSession.Flag_unread_setup)の判定条件をPython側で再現するための共通ヘルパー。"""
    tokens = [c.strip().upper() for c in re.split(r'[;,]\s*', categories or '') if c and c.strip()]
    return "JUST DO IT" in tokens

# ============================================================
# 統括コックピットv2 (新コンセプト): 解放スコア・生体信号・沈黙検知
# ここに置く関数はすべてOutlook(win32com)に依存しない純粋関数とし、
# Outlookが動かない環境でも単体でロジック検証できるようにする。
# ============================================================

# 統括コックピットv2のメール取得ウィンドウ(日数)。生体信号の「直近ウィンドウ vs 前ウィンドウ」
# 比較(compute_mail_velocity, デフォルトwindow_days=7)が2ウィンドウ分必要なため、
# その2倍以上を確保する値にしている。
COCKPIT_V2_WINDOW_DAYS = 30

# 解放スコアの重み(合計100になるよう設計。各成分は0〜1に正規化してから乗じる)
SCORE_WEIGHTS = {
    "waiting_people": 22,   # 待っている人数
    "days_elapsed": 22,     # 最後のあなた宛てメールからの経過日数(締切の代理指標)
    "reminder_count": 18,   # 催促・リマインドの表現回数
    "manual_priority": 15,  # あなたが手動で付けた優先度(★/★★)
    "project_priority": 12, # プロジェクト優先度(project_knowledge.jsonの設定)
    "flagged": 8,           # Outlookフラグ or Just Do Itタグ
    "deadline_bonus": 3,    # 明示的な締切の有無(補助的なボーナス)
}

def compute_release_score(waiting_people_count: int, days_elapsed: float, reminder_count: int,
                           manual_priority: str, project_priority: str, is_flagged: bool,
                           has_deadline: bool) -> float:
    """"自分待ち"の案件を並べ替えるための解放スコア(0〜100)を計算する。
    各成分は根拠チップとしてそのままUIに出せるよう、加重和のみで完結させ、
    ブラックボックスな重みづけにしない(SCORE_WEIGHTSが唯一のチューニング箇所)。"""
    norm_wp = min(max(waiting_people_count, 0), 5) / 5
    norm_days = min(max(days_elapsed, 0), 10) / 10
    norm_rem = min(max(reminder_count, 0), 3) / 3
    norm_manual = {"★★": 1.0, "★": 0.5}.get(manual_priority or "", 0.0)
    norm_proj = {"高": 1.0, "中": 0.5, "低": 0.0}.get(project_priority or "中", 0.5)
    norm_flag = 1.0 if is_flagged else 0.0
    norm_deadline = 1.0 if has_deadline else 0.0

    score = (
        SCORE_WEIGHTS["waiting_people"] * norm_wp
        + SCORE_WEIGHTS["days_elapsed"] * norm_days
        + SCORE_WEIGHTS["reminder_count"] * norm_rem
        + SCORE_WEIGHTS["manual_priority"] * norm_manual
        + SCORE_WEIGHTS["project_priority"] * norm_proj
        + SCORE_WEIGHTS["flagged"] * norm_flag
        + SCORE_WEIGHTS["deadline_bonus"] * norm_deadline
    )
    return round(score, 1)

def release_score_reasons(waiting_people_count: int, days_elapsed: float, reminder_count: int,
                           manual_priority: str, project_priority: str, is_flagged: bool,
                           has_deadline: bool) -> list:
    """解放スコアの内訳を、UI表示用の根拠チップ文字列のリストとして返す。
    「なぜ今これが上位か」を必ず説明できるようにするための、スコアと1対1の可視化。"""
    reasons = []
    if waiting_people_count >= 1:
        reasons.append(f"👥 {waiting_people_count}人が待機中")
    if days_elapsed >= 1:
        reasons.append(f"⏰ {int(days_elapsed)}日間 未返信")
    if reminder_count >= 1:
        reasons.append(f"📣 催促表現 {reminder_count}回")
    if manual_priority in ("★", "★★"):
        reasons.append(f"🔺 手動優先度 {manual_priority}")
    if project_priority == "高":
        reasons.append("🔺 高優先プロジェクト")
    if is_flagged:
        reasons.append("🚩 フラグ / Just Do It")
    if has_deadline:
        reasons.append("📅 締切の明記あり")
    return reasons

def compute_mail_velocity(sorted_dates: list, now: datetime, window_days: int = 7) -> dict:
    """直近ウィンドウ vs その前のウィンドウのメール件数を比較し、勢いの増減を出す。
    sorted_datesは昇順ソート済みのdatetimeリスト(送受信問わずスレッドの全メール日時)。"""
    if not sorted_dates:
        return {"recent_count": 0, "prior_count": 0, "trend": "→"}
    recent_cutoff = now - timedelta(days=window_days)
    prior_cutoff = now - timedelta(days=window_days * 2)
    recent_count = sum(1 for d in sorted_dates if d >= recent_cutoff)
    prior_count = sum(1 for d in sorted_dates if prior_cutoff <= d < recent_cutoff)
    if recent_count > prior_count * 1.2:
        trend = "↑"
    elif recent_count < prior_count * 0.8:
        trend = "↓"
    else:
        trend = "→"
    return {"recent_count": recent_count, "prior_count": prior_count, "trend": trend}

def compute_relative_silence(sorted_dates: list, now: datetime) -> dict:
    """固定日数ではなく「そのスレッド/プロジェクトの平常ペースより間が空いているか」で
    沈黙を判定する(相対閾値)。平常ペース(平均間隔)の2倍、最低でも2日を沈黙の目安とする。"""
    if len(sorted_dates) < 2:
        return {"silence_days": 0.0, "avg_gap_days": 0.0, "is_stalled": False}
    gaps = [
        (sorted_dates[i + 1] - sorted_dates[i]).total_seconds() / 86400
        for i in range(len(sorted_dates) - 1)
    ]
    avg_gap = sum(gaps) / len(gaps) if gaps else 0.0
    silence_days = (now - sorted_dates[-1]).total_seconds() / 86400
    threshold = max(avg_gap * 2.0, 2.0)
    return {
        "silence_days": round(silence_days, 1),
        "avg_gap_days": round(avg_gap, 1),
        "is_stalled": silence_days > threshold
    }

# ============================================================
# ローカルサーバー (HTMLリンク連携用)
# ============================================================

# Outlook操作リクエストをメインスレッドに渡すキュー
outlook_request_queue = queue.Queue()

# json/action_status.json への同時書き込み競合を防ぐロック(ThreadingHTTPServer化に伴い追加)
action_status_lock = threading.Lock()



class OutlookRequestHandler(BaseHTTPRequestHandler):
    """HTMLからのリクエスト（Outlook起動・翻訳・JSON更新）を処理"""

    def _send_cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()




    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == '/translate':
            try:
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
                text = data.get('text', '')
                config = load_config()
                api_key = config.get('gemini_api_key', '')
                if not api_key: raise Exception("APIキーが設定されていません")
                client = genai.Client(api_key=api_key)
                res = client.models.generate_content(
                    model=config.get('gemini_model', 'gemini-2.5-flash'),
                    contents=f"以下の英文メールを自然な日本語で翻訳してください。\n\n{text}"
                )
                self.send_response(200); self._send_cors_headers(); self.send_header('Content-type', 'application/json; charset=utf-8'); self.end_headers()
                self.wfile.write(json.dumps({'translated': res.text}).encode('utf-8'))
            except Exception as e:
                self.send_response(500); self._send_cors_headers(); self.send_header('Content-type', 'application/json; charset=utf-8'); self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        elif parsed.path == '/translate_array':
            try:
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
                texts = data.get('texts', [])
                config = load_config()
                api_key = config.get('gemini_api_key', '')
                if not api_key: raise Exception("APIキーが設定されていません")
                chunk_size = 100
                chunks = [texts[i:i + chunk_size] for i in range(0, len(texts), chunk_size)]
                def translate_chunk(chunk_idx, chunk_data):
                    chunk_dict = {str(idx): text for idx, text in enumerate(chunk_data)}
                    prompt = "以下のJSONオブジェクトの「値(Value)」部分のみを自然な日本語に翻訳し、同じ「キー(Key)」を持つJSONオブジェクトとして出力してください。\n" + json.dumps(chunk_dict, ensure_ascii=False)
                    try:
                        client = genai.Client(api_key=api_key)
                        res = client.models.generate_content(model=config.get('gemini_model', 'gemini-2.5-flash'), contents=prompt, config=types.GenerateContentConfig(response_mime_type="application/json"))
                        translated_dict = json.loads(res.text)
                        return [translated_dict.get(str(idx), chunk_data[idx]) for idx in range(len(chunk_data))]
                    except: return chunk_data
                from concurrent.futures import ThreadPoolExecutor, as_completed
                results = {}
                with ThreadPoolExecutor(max_workers=5) as executor:
                    future_to_idx = {executor.submit(translate_chunk, i, c): i for i, c in enumerate(chunks)}
                    for future in as_completed(future_to_idx):
                        idx = future_to_idx[future]; results[idx] = future.result()
                translated_array = []
                for i in range(len(chunks)): translated_array.extend(results[i])
                self.send_response(200); self._send_cors_headers(); self.send_header('Content-type', 'application/json; charset=utf-8'); self.end_headers()
                self.wfile.write(json.dumps({'translated': translated_array}).encode('utf-8'))
            except Exception as e:
                self.send_response(500); self._send_cors_headers(); self.send_header('Content-type', 'application/json; charset=utf-8'); self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        elif parsed.path == '/update_knowledge':
            try:
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
                proj = data.get('project')
                staff = data.get('staff')
                kn = load_project_knowledge()
                if proj:
                    target = kn.setdefault("projects", {}).setdefault(proj, {})
                    if 'human_answers' in data: target["human_answers"] = data['human_answers']
                    if 'master_history' in data: target["master_history"] = data['master_history']
                    if 'history_summary' in data: target["history_summary"] = data['history_summary']
                if staff:
                    target = kn.setdefault("staffs", {}).setdefault(staff, {})
                    if 'human_answers' in data: target["human_answers"] = data['human_answers']
                    if 'master_history' in data: target["master_history"] = data['master_history']
                    if 'history_summary' in data: target["history_summary"] = data['history_summary']
                    if 'role' in data: target["role"] = data['role']
                    if 'background' in data: target["background"] = data['background']
                save_project_knowledge(kn)
                self.send_response(200); self._send_cors_headers(); self.send_header('Content-type', 'application/json; charset=utf-8'); self.end_headers()
                self.wfile.write(json.dumps({'status': 'success'}).encode('utf-8'))
            except Exception as e:
                self.send_response(500); self._send_cors_headers(); self.send_header('Content-type', 'application/json; charset=utf-8'); self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        elif parsed.path == '/generate_questions':
            try:
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
                target = data.get('target', ''); context = data.get('context', ''); existing_qs = data.get('existing_questions', [])
                config = load_config(); api_key = config.get('gemini_api_key', '')
                if not api_key: raise Exception("APIキーが設定されていません")
                prompt = f"以下の対象の活動要約を踏まえ、新しい質問を2つだけ生成してください。JSONの配列で出力してください。\n\n【対象】{target}\n【活動要約】\n{context}\n\n【既存】\n{json.dumps(existing_qs, ensure_ascii=False)}"
                client = genai.Client(api_key=api_key)
                res = client.models.generate_content(model=config.get('gemini_model', 'gemini-2.5-flash'), contents=prompt, config=types.GenerateContentConfig(response_mime_type="application/json"))
                self.send_response(200); self._send_cors_headers(); self.send_header('Content-type', 'application/json; charset=utf-8'); self.end_headers()
                self.wfile.write(json.dumps({'new_questions': json.loads(res.text)}).encode('utf-8'))
            except Exception as e:
                self.send_response(500); self._send_cors_headers(); self.send_header('Content-type', 'application/json; charset=utf-8'); self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        elif parsed.path == '/summarize_single':
            try:
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
                topic = data.get('topic', ''); body = data.get('body', '')
                config = load_config(); api_key = config.get('gemini_api_key', '')
                if not api_key: raise Exception("APIキーが設定されていません")
                prompt = f"以下のメール本文を1行（50文字以内）で簡潔に要約してください。※必ず自然な日本語に翻訳して出力してください。\n\n【件名】{topic}\n【本文】{body}"
                client = genai.Client(api_key=api_key)
                res = client.models.generate_content(model=config.get('gemini_model', 'gemini-2.5-flash'), contents=prompt)
                self.send_response(200); self._send_cors_headers(); self.send_header('Content-type', 'application/json; charset=utf-8'); self.end_headers()
                self.wfile.write(json.dumps({'summary': res.text.strip()}).encode('utf-8'))
            except Exception as e:
                self.send_response(500); self._send_cors_headers(); self.send_header('Content-type', 'application/json; charset=utf-8'); self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        elif parsed.path == '/summarize_detail':
            try:
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
                topic = data.get('topic', ''); body = data.get('body', ''); t_type = data.get('target_type', 'project'); t_name = data.get('target_name', '')
                config = load_config(); api_key = config.get('gemini_api_key', '')
                if not api_key: raise Exception("APIキーが設定されていません")
                prompt = f"メールスレッド履歴を分析し、詳細要約をJSON形式で出力。※必ず日本語で出力。\n1.points:3つ以上の要点 2.risks:リスク 3.recommended_actions:推奨活動\n\n【件名】{topic}\n【本文】{body}"
                client = genai.Client(api_key=api_key)
                res = client.models.generate_content(model=config.get('gemini_model', 'gemini-2.5-flash'), contents=prompt, config=types.GenerateContentConfig(response_mime_type="application/json"))
                self.send_response(200); self._send_cors_headers(); self.send_header('Content-type', 'application/json; charset=utf-8'); self.end_headers()
                self.wfile.write(res.text.encode('utf-8'))
            except Exception as e:
                self.send_response(500); self._send_cors_headers(); self.send_header('Content-type', 'application/json; charset=utf-8'); self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        elif parsed.path == '/update_ai_rules':
            try:
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
                t_type = data.get('type'); t_name = data.get('target'); rule = data.get('rule', '').strip()
                if t_type and t_name and rule:
                    kn = load_project_knowledge(); key = "projects" if t_type == 'project' else "staffs"
                    target = kn.setdefault(key, {}).setdefault(t_name, {})
                    rules = target.setdefault("ai_correction_rules", [])
                    if rule not in rules: rules.append(rule); target["ai_correction_rules"] = rules[-20:]
                    save_project_knowledge(kn)
                self.send_response(200); self._send_cors_headers(); self.send_header('Content-type', 'application/json; charset=utf-8'); self.end_headers()
                self.wfile.write(json.dumps({'status': 'success'}).encode('utf-8'))
            except Exception as e:
                self.send_response(500); self._send_cors_headers(); self.send_header('Content-type', 'application/json; charset=utf-8'); self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        elif parsed.path == '/update_action_status':
            try:
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
                action_key = (data.get('action_key') or '').strip()
                if not action_key: raise Exception("action_keyが指定されていません")
                with action_status_lock:
                    statuses = load_action_status()
                    entry = statuses.setdefault(action_key, {"progress": "not_started", "priority": "", "comment": ""})
                    if 'progress' in data: entry['progress'] = data['progress']
                    if 'priority' in data: entry['priority'] = data['priority']
                    if 'comment' in data: entry['comment'] = data['comment']
                    entry['updated_at'] = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
                    statuses[action_key] = entry
                    save_action_status(statuses)
                self.send_response(200); self._send_cors_headers(); self.send_header('Content-type', 'application/json; charset=utf-8'); self.end_headers()
                self.wfile.write(json.dumps({'status': 'success', 'entry': entry}).encode('utf-8'))
            except Exception as e:
                self.send_response(500); self._send_cors_headers(); self.send_header('Content-type', 'application/json; charset=utf-8'); self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        else: self.send_error(404, "Not Found")

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/open':
            qs = parse_qs(parsed.query)
            eid = qs.get('id', [None])[0]
            topic = qs.get('topic', [None])[0]
            if eid:
                outlook_request_queue.put(('open_thread' if topic else 'open_item', eid, topic))
                
                self.send_response(200)
                self._send_cors_headers()
                self.send_header('Content-type', 'text/html; charset=utf-8')
                self.end_headers()
                html = """
                <html><head><script>window.close();</script></head>
                <body style="font-family:sans-serif;text-align:center;margin-top:50px;">
                <h3>Outlookで開いています...</h3>
                <p>このタブは閉じても構いません。</p>
                </body></html>
                """
                self.wfile.write(html.encode('utf-8'))
            else:
                self.send_error(400, "Entry ID not provided")
        else:
            self.send_error(404, "Not Found")
    
    def log_message(self, format, *args):
        pass



def start_local_server():
    """ポート8082で固定してサーバーを起動し、ポート番号を返す。
    ThreadingHTTPServerを使用し、複数のブラウザタブ/接続からのリクエストを
    同時並行で処理できるようにする（非スレッド版HTTPServerだと、1つの接続が
    keep-aliveで保持されている間、他の接続が受け付けられず「読み込み中のまま
    固まる」symptomが発生するため）。"""
    try:
        # ポート8082番で固定起動
        server = ThreadingHTTPServer(('localhost', 8082), OutlookRequestHandler)
        port = 8082
        print(f"✅ ローカルサーバーをポート {port} で起動しました")
    except OSError:
        # 万が一8082番が他のソフトに使われていた場合の予備ルート
        print("⚠️ ポート8082が使用中またはブロックされています。ランダムポートにフォールバックします。")
        server = ThreadingHTTPServer(('localhost', 0), OutlookRequestHandler)
        port = server.server_port

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return port
    

# ============================================================
# Outlook連携クラス
# ============================================================

class OutlookMailManager:
    """Outlookメール取得・操作"""
    


    def __init__(self):
        self.outlook = None
        self.namespace = None
        self.inbox = None
        self._connected = False
        self.user_name = ""
        self.user_smtp_address = ""
        self.session_marked_read_entry_ids = set()
    
    def connect(self):
        try:
            pythoncom.CoInitialize()
            self.outlook = win32com.client.Dispatch("Outlook.Application")
            self.namespace = self.outlook.GetNamespace("MAPI")
            self.inbox = self.namespace.GetDefaultFolder(6)
            
            try:
                cu = self.namespace.CurrentUser
                self.user_name = cu.Name
                self.user_smtp_address = self._resolve_object_to_smtp(cu)
            except Exception as e:
                print(f"User Resolution Error: {e}")
            
            self._connected = True
            return True
        except Exception as e:
            print(f"Outlook接続エラー: {e}")
            return False

    def _resolve_object_to_smtp(self, obj):
        try:
            try:
                pa = obj.PropertyAccessor
                smtp_addr = pa.GetProperty("http://schemas.microsoft.com/mapi/proptag/0x39FE001E")
                if smtp_addr and '@' in smtp_addr:
                    return smtp_addr.lower()
            except: pass

            addr_entry = None
            if hasattr(obj, "AddressEntry"): addr_entry = obj.AddressEntry
            elif hasattr(obj, "Type"): addr_entry = obj
            
            if addr_entry:
                if addr_entry.Type == "EX":
                    try:
                        eu = addr_entry.GetExchangeUser()
                        if eu:
                            smtp_addr = eu.PrimarySmtpAddress
                            if smtp_addr: return smtp_addr.lower()
                    except: pass
                if addr_entry.Address and '@' in addr_entry.Address:
                    return addr_entry.Address.lower()

            if hasattr(obj, "Address"):
                if obj.Address and '@' in obj.Address and "/o=" not in obj.Address:
                    return obj.Address.lower()
        except: pass
        return ""

    def get_categories(self) -> list:
        try:
            pythoncom.CoInitialize()
            outlook = win32com.client.Dispatch("Outlook.Application")
            namespace = outlook.GetNamespace("MAPI")
            categories = namespace.Categories
            result = [cat.Name for cat in categories]
            pythoncom.CoUninitialize()
            return result
        except: return []

    def _get_outlook_process_creation_marker(self) -> str:
        """WMI経由でOUTLOOK.EXEプロセスのCreationDateを取得する。
        複数プロセスがヒットした場合は最も古い(=最初に起動した)ものを採用する。
        取得失敗/プロセス未検出時は空文字を返す(呼び出し元は「今回は判定不能」として扱う)。"""
        try:
            pythoncom.CoInitialize()
            wmi_service = win32com.client.GetObject("winmgmts:")
            results = wmi_service.ExecQuery(
                "SELECT ProcessId, CreationDate FROM Win32_Process WHERE Name='OUTLOOK.EXE'"
            )
            creation_dates = [r.CreationDate for r in results if getattr(r, 'CreationDate', None)]
            if not creation_dates:
                return ""
            return min(creation_dates)
        except Exception as e:
            print(f"Outlookプロセス起動時刻取得エラー(WMI): {e}")
            return ""
        finally:
            try: pythoncom.CoUninitialize()
            except: pass

    def check_and_update_outlook_restart_state(self) -> bool:
        """Outlookが前回チェック時から再起動されたか(または初回実行か)を判定する。
        再起動を検知した場合は json/outlook_restart_state.json を新しいマーカーで更新しTrueを返す。
        WMI取得に失敗した場合は状態を更新せずFalseを返す(判定を次回に持ち越す。
        「再起動していない」と断定しているわけではない点に注意)。"""
        current_marker = self._get_outlook_process_creation_marker()
        if not current_marker:
            return False
        state = load_outlook_restart_state()
        if state.get("last_seen_creation_date") == current_marker:
            return False
        state["last_seen_creation_date"] = current_marker
        state["last_checked_at"] = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
        save_outlook_restart_state(state)
        return True




    def search_mails_fast(self, conditions: dict, logic: str = "AND",
                          include_sent: bool = True,
                          progress_callback=None) -> list:
        all_mails = []
        processed_entry_ids = set()
        processed_conversation_ids = set()
        previous_search_light_mode = getattr(self, "_active_search_light_mode", False)
        
        try:
            pythoncom.CoInitialize()
            outlook = win32com.client.Dispatch("Outlook.Application")
            namespace = outlook.GetNamespace("MAPI")
            inbox = namespace.GetDefaultFolder(6)
            
            check_to_me = conditions.get('to_me')
            check_with_me = conditions.get('with_me')
            check_cc_me = conditions.get('cc_me')
            check_all_me = conditions.get('all_me', False)
            
            target_search_folders = []
            if check_to_me: target_search_folders.append(SEARCH_FOLDER_TOME)
            if check_with_me: target_search_folders.append(SEARCH_FOLDER_WITHME)
            if check_cc_me: target_search_folders.append(SEARCH_FOLDER_CCME)
            
            folders = []
            if target_search_folders:
                found_folders = {}
                try:
                    store = inbox.Store
                    search_folders = store.GetSearchFolders()
                    for sf in search_folders:
                        if sf.Name in target_search_folders:
                            found_folders[sf.Name] = sf
                except: pass
                
                missing_folders = [name for name in target_search_folders if name not in found_folders]
                if missing_folders:
                    raise Exception(f"検索フォルダが見つかりませんでした: {', '.join(missing_folders)}")
                
                for name in target_search_folders:
                    folders.append((name, found_folders[name]))
            
            needs_inbox = not (check_to_me or check_with_me or check_cc_me) or check_all_me
            if needs_inbox:
                folders.append(("受信トレイ", inbox))
            
            if include_sent:
                try:
                    folders.append(("送信済み", namespace.GetDefaultFolder(5)))
                except: pass
            
            body_kw = conditions.get('body_keyword', '').strip().lower()
            body_kws = [k.strip() for k in body_kw.split() if k.strip()] if body_kw else []
            search_light_mode = (not bool(body_kws)) and not conditions.get('force_full_body', False)
            self._active_search_light_mode = search_light_mode
            skip_attachments_flag = conditions.get('skip_attachments', False)
            
            strict = conditions.get('strict_mode', False)
            
            scan_count = 0
            
            for folder_name, folder in folders:
                if progress_callback: progress_callback(0, 0, f"📁 {folder_name} を検索中...")
                try:
                    items = folder.Items
                    items.Sort("[ReceivedTime]", True)
                    
                    # === 期間フィルタリングのロジック分岐 ===
                    days = conditions.get('days', 7)
                    if days == 0:
                        date_str = (datetime.now() - timedelta(hours=24)).strftime("%m/%d/%Y %H:%M")
                        try: items = items.Restrict(f"[ReceivedTime] >= '{date_str}'")
                        except: pass
                    elif days < 0:
                        date_str = (datetime.now() - timedelta(hours=abs(days))).strftime("%m/%d/%Y %H:%M")
                        try: items = items.Restrict(f"[ReceivedTime] >= '{date_str}'")
                        except: pass
                    elif days > 0:
                        date_str = (datetime.now() - timedelta(days=days)).strftime("%m/%d/%Y")
                        try: items = items.Restrict(f"[ReceivedTime] >= '{date_str}'")
                        except: pass
                    
                    if s := conditions.get('subject', '').strip():
                        try: items = items.Restrict(f"@SQL=\"urn:schemas:httpmail:subject\" LIKE '%{s.split()[0]}%'")
                        except: pass
                    if s := conditions.get('sender', '').strip():
                        try: items = items.Restrict(f"@SQL=\"urn:schemas:httpmail:sendername\" LIKE '%{s}%'")
                        except: pass
                    
                    max_scan = 500
                    for item in items:
                        if scan_count >= max_scan: break
                        try:
                            is_match = True
                            
                            if s := conditions.get('subject'):
                                kws = [k.strip().lower() for k in s.split() if k.strip()]
                                sub = (getattr(item, 'Subject', '') or '').lower()
                                if logic == "AND":
                                    if not all(k in sub for k in kws): is_match = False
                                else:
                                    if not any(k in sub for k in kws): is_match = False
                            if not is_match: continue

                            if c := conditions.get('category'):
                                item_cat = (getattr(item, 'Categories', '') or '').strip()
                                if c == "(項目なし)":
                                    if item_cat != "": is_match = False
                                elif c != "(すべて)":
                                    if c.lower() not in item_cat.lower(): is_match = False
                            if not is_match: continue

                            if body_kws:
                                b = (getattr(item, 'Body', '') or '').lower()
                                if logic == "AND":
                                    if not all(k in b for k in body_kws): is_match = False
                                else:
                                    if not any(k in b for k in body_kws): is_match = False
                            if not is_match: continue
                            
                            if fd := conditions.get('filter_domains'):
                                try:
                                    se = self._get_sender_smtp_address_robust(item)
                                    if se and '@' in se:
                                        d = se.split('@')[-1].lower()
                                        if d in fd: is_match = False
                                except: pass
                            if not is_match: continue

                            if strict:
                                if conditions.get('unread_only') and not getattr(item, 'UnRead', False):
                                    is_match = False
                                
                                flag_status = conditions.get('flag_status')
                                if flag_status == 'active' and getattr(item, 'FlagStatus', 0) != 2:
                                    is_match = False
                                elif flag_status == 'none' and getattr(item, 'FlagStatus', 0) == 2:
                                    is_match = False
                                
                                if check_all_me:
                                    pass
                                elif check_to_me or check_with_me or check_cc_me:
                                    hit = False
                                    if folder_name in (SEARCH_FOLDER_TOME, SEARCH_FOLDER_WITHME, SEARCH_FOLDER_CCME):
                                        hit = True
                                    else:
                                        my_smtp = self.user_smtp_address
                                        if my_smtp:
                                            try:
                                                recipients = item.Recipients
                                                to_list = []
                                                cc_list = []
                                                for r in recipients:
                                                    ra = self._resolve_object_to_smtp(r)
                                                    if ra:
                                                        if r.Type == 1: to_list.append(ra)
                                                        elif r.Type == 2: cc_list.append(ra)
                                                is_to_me = (len(to_list) == 1 and to_list[0] == my_smtp)
                                                is_with_me = (my_smtp in to_list and len(to_list) > 1)
                                                is_cc_me = (my_smtp in cc_list)
                                                if check_to_me and is_to_me: hit = True
                                                if check_with_me and is_with_me: hit = True
                                                if check_cc_me and is_cc_me: hit = True
                                            except: pass
                                    if not hit: is_match = False
                            
                            if not is_match: continue
                            
                            if strict or check_to_me:
                                self._add_single_item(item, all_mails, processed_entry_ids, folder_name, light_mode=search_light_mode, skip_attachments=skip_attachments_flag)
                            else:
                                conv_id = getattr(item, 'ConversationID', None)
                                if conv_id and conv_id not in processed_conversation_ids:
                                    processed_conversation_ids.add(conv_id)
                                    try:
                                        conv = item.GetConversation()
                                        if conv:
                                            for root in conv.GetRootItems():
                                                self._traverse_conversation(root, conv, all_mails, processed_entry_ids)
                                        else:
                                            self._add_single_item(item, all_mails, processed_entry_ids, folder_name, light_mode=search_light_mode, skip_attachments=skip_attachments_flag)
                                    except:
                                        self._add_single_item(item, all_mails, processed_entry_ids, folder_name, light_mode=search_light_mode, skip_attachments=skip_attachments_flag)
                                elif not conv_id:
                                    self._add_single_item(item, all_mails, processed_entry_ids, folder_name, light_mode=search_light_mode, skip_attachments=skip_attachments_flag)
                            
                            scan_count += 1
                            if progress_callback and scan_count % 10 == 0:
                                progress_callback(scan_count, 0, f"🔍 検索ヒット数: {scan_count}件...")
                        except: continue
                except: pass
        except Exception as e:
            print(f"Search Error: {e}")
            raise
        finally:
            self._active_search_light_mode = previous_search_light_mode
            try: pythoncom.CoUninitialize()
            except: pass
        return all_mails

    def get_relevant_mails_for_period(self, days: int, progress_callback=None) -> list:
        """アクションダッシュボード用: 期間内の受信トレイ全体（既読・未読問わず）を、
        既知のプロジェクト/スタッフに限定せず横断的に取得する。
        ※ to_me/with_me/cc_me条件はOutlookの「未(ToMe)」等の未読専用検索フォルダに
        絞り込まれてしまうため使わず、all_me（受信トレイ全体・絞り込みなし）を使う。
        ※ force_full_body=True を指定しないと本文が空文字で返る（search_mails_fastの
        light_modeはbody_keyword未指定時デフォルトON）ため、AI解析に必須の本文取得を強制する。
        ※ skip_attachments=True で添付ファイル・インライン画像の処理（テキスト解析には不要）を
        スキップし、本文取得のみ行うことで高速化する。"""
        conditions = {
            'all_me': True,
            'strict_mode': True, 'days': days,
            'force_full_body': True,
            'skip_attachments': True
        }
        return self.search_mails_fast(conditions, logic="AND", include_sent=False, progress_callback=progress_callback)

    def search_ad_mails(self, days: int, excluded_domains: set, unread_only: bool = False, progress_callback=None) -> list:
        all_mails = []
        processed_entry_ids = set()
        try:
            pythoncom.CoInitialize()
            outlook = win32com.client.Dispatch("Outlook.Application")
            namespace = outlook.GetNamespace("MAPI")
            inbox = namespace.GetDefaultFolder(6)
            if progress_callback: progress_callback(0, 0, "📢 広告候補メールをスキャン中...")
            items = inbox.Items
            items.Sort("[ReceivedTime]", True)
            
            # === 期間フィルタリングのロジック分岐 (広告検索用) ===
            if days == -12:
                date_str = (datetime.now() - timedelta(hours=12)).strftime("%m/%d/%Y %H:%M")
                try: items = items.Restrict(f"[ReceivedTime] >= '{date_str}'")
                except: pass
            elif days == 0:
                date_str = (datetime.now() - timedelta(hours=24)).strftime("%m/%d/%Y %H:%M")
                try: items = items.Restrict(f"[ReceivedTime] >= '{date_str}'")
                except: pass
            elif days:
                date_str = (datetime.now() - timedelta(days=days)).strftime("%m/%d/%Y")
                try: items = items.Restrict(f"[ReceivedTime] >= '{date_str}'")
                except: pass
                
            max_scan = 1000
            scan_count = 0
            for item in items:
                if scan_count >= max_scan: break
                try:
                    if unread_only and not getattr(item, 'UnRead', False): continue
                    
                    sender_email = self._get_sender_smtp_address_robust(item)
                    if not sender_email or '@' not in sender_email: continue
                    domain = sender_email.split('@')[-1].lower()
                    if domain == 'nexperia.com' or domain in excluded_domains: continue
                    self._add_single_item(item, all_mails, processed_entry_ids, "受信トレイ")
                    scan_count += 1
                    if progress_callback and scan_count % 20 == 0:
                        progress_callback(scan_count, 0, f"📢 広告候補: {scan_count}件...")
                except: continue
        except Exception as e:
            print(f"Ad Search Error: {e}")
        finally:
            try: pythoncom.CoUninitialize()
            except: pass
        return all_mails


    def get_unread_rss_feeds(self, progress_callback=None) -> list:
        all_mails = []
        scan_count = [0] # 参照渡しでカウントを共有
        
        def _scan_folder(folder):
            if scan_count[0] >= 500: return
            try:
                items = folder.Items
                items.Sort("[ReceivedTime]", True)
                try: items = items.Restrict("[UnRead] = True")
                except: pass
                
                for item in items:
                    if scan_count[0] >= 500: break
                    try:
                        subject = getattr(item, 'Subject', '(タイトルなし)') or '(タイトルなし)'
                        sender_name = getattr(item, 'SenderName', '') or '(送信者なし)'
                        entry_id = getattr(item, 'EntryID', '')
                        
                        raw_body = getattr(item, 'Body', '') or ''
                        cleaned_body = self._clean_body_text(raw_body)
                        categories = getattr(item, 'Categories', '') or ''
                        folder_name = folder.Name
                        
                        # --- RSS送信者抽出とタグ分離ロジック（安全装置付き） ---
                        if 'note' in folder_name.lower() or sender_name.startswith('#'):
                            import re
                            m = re.search(r'https?://note\.com/([^/\s\?]+)', raw_body)
                            if m:
                                creator_id = m.group(1)
                                if categories: categories = f"{categories}, {sender_name}"
                                else: categories = sender_name
                                sender_name = creator_id
                        
                        all_mails.append({
                            'subject': subject,
                            'sender_name': sender_name,
                            'sender_email': '',
                            'received': self._get_date_from_item(item),
                            'body': cleaned_body[:10000],
                            'conversation_id': entry_id,
                            'conversation_topic': subject,
                            'entry_id': entry_id,
                            'importance': 1,
                            'folder': "RSS フィード",
                            'display_folder': folder_name,
                            'has_attachments': False,
                            'unread': bool(getattr(item, 'UnRead', False)),
                            'categories': categories,
                            'flag_status': getattr(item, 'FlagStatus', 0),
                            'routing': "other"
                        })
                        scan_count[0] += 1
                    except: continue
            except: pass
            
            try:
                for subfolder in folder.Folders:
                    if scan_count[0] >= 500: break
                    _scan_folder(subfolder)
            except: pass

        try:
            pythoncom.CoInitialize()
            outlook = win32com.client.Dispatch("Outlook.Application")
            namespace = outlook.GetNamespace("MAPI")
            try: rss_folder = namespace.GetDefaultFolder(25)
            except: return []
            
            if progress_callback: progress_callback(0, 0, "📰 RSS記事をスキャン中...")
            _scan_folder(rss_folder)
            
        except Exception as e: print(f"RSS Search Error: {e}")
        finally:
            try: pythoncom.CoUninitialize()
            except: pass
        return all_mails

    def get_junk_deleted_unread_mails(self, progress_callback=None) -> list:
        all_mails = []
        processed_entry_ids = set()
        try:
            pythoncom.CoInitialize()
            outlook = win32com.client.Dispatch("Outlook.Application")
            namespace = outlook.GetNamespace("MAPI")
            
            folders = []
            try: folders.append(("削除済み", namespace.GetDefaultFolder(3)))
            except: pass
            try: folders.append(("迷惑メール", namespace.GetDefaultFolder(23)))
            except: pass
            
            scan_count = 0
            for folder_name, folder in folders:
                try:
                    items = folder.Items
                    items.Sort("[ReceivedTime]", True)
                    try: items = items.Restrict("[UnRead] = True")
                    except: pass
                    
                    for item in items:
                        if scan_count >= 500: break
                        try:
                            self._add_single_item(item, all_mails, processed_entry_ids, folder_name)
                            scan_count += 1
                        except: continue
                except: pass
        except Exception as e:
            print(f"Junk Search Error: {e}")
        finally:
            try: pythoncom.CoUninitialize()
            except: pass
        return all_mails


    def mark_mails_read(self, entry_ids: list) -> int:
        success_count = 0
        try:
            pythoncom.CoInitialize()
            outlook = win32com.client.Dispatch("Outlook.Application")
            namespace = outlook.GetNamespace("MAPI")
            for eid in entry_ids:
                try:
                    item = namespace.GetItemFromID(eid)
                    if eid:
                        self.session_marked_read_entry_ids.add(str(eid))
                    if item.UnRead:
                        item.UnRead = False
                        item.Save()
                        success_count += 1
                except: pass
        except Exception as e: print(f"Mark Read Error: {e}")
        finally:
            try: pythoncom.CoUninitialize()
            except: pass
        return success_count

    def mark_mails_unread(self, entry_ids: list) -> int:
        success_count = 0
        try:
            pythoncom.CoInitialize()
            outlook = win32com.client.Dispatch("Outlook.Application")
            namespace = outlook.GetNamespace("MAPI")
            for eid in entry_ids:
                try:
                    item = namespace.GetItemFromID(eid)
                    if not item.UnRead:
                        item.UnRead = True
                        item.Save()
                        success_count += 1
                except: pass
        except Exception as e: print(f"Mark Unread Error: {e}")
        finally:
            try: pythoncom.CoUninitialize()
            except: pass
        return success_count
    
    def remove_flags(self, entry_ids: list) -> int:
        success_count = 0
        try:
            pythoncom.CoInitialize()
            outlook = win32com.client.Dispatch("Outlook.Application")
            namespace = outlook.GetNamespace("MAPI")
            for eid in entry_ids:
                try:
                    item = namespace.GetItemFromID(eid)
                    if getattr(item, 'FlagStatus', 0) != 0:
                        item.FlagStatus = 0
                        item.Save()
                        success_count += 1
                except: pass
        except Exception as e: print(f"Remove Flag Error: {e}")
        finally:
            try: pythoncom.CoUninitialize()
            except: pass
        return success_count

    def toggle_flag(self, entry_id: str) -> bool:
        new_status = False
        try:
            pythoncom.CoInitialize()
            outlook = win32com.client.Dispatch("Outlook.Application")
            namespace = outlook.GetNamespace("MAPI")
            try:
                item = namespace.GetItemFromID(entry_id)
                if item.FlagStatus == 2:
                    item.FlagStatus = 0
                    new_status = False
                else:
                    item.FlagStatus = 2
                    new_status = True
                item.Save()
            except: pass
        except Exception as e: print(f"Toggle Flag Error: {e}")
        finally:
            try: pythoncom.CoUninitialize()
            except: pass
        return new_status

    def mark_all_junk_deleted_read(self) -> int:
        success_count = 0
        try:
            pythoncom.CoInitialize()
            outlook = win32com.client.Dispatch("Outlook.Application")
            namespace = outlook.GetNamespace("MAPI")
            for folder_id in [3, 23]:
                try:
                    folder = namespace.GetDefaultFolder(folder_id)
                    items = folder.Items
                    try: items = items.Restrict("[UnRead] = True")
                    except: pass
                    for item in items:
                        try:
                            if item.UnRead:
                                item.UnRead = False
                                item.Save()
                                success_count += 1
                        except: pass
                except: pass
        except Exception as e:
            print(f"Junk/Deleted Mark Read Error: {e}")
        finally:
            try: pythoncom.CoUninitialize()
            except: pass
        return success_count

    def _find_captioo_folder(self, store, inbox):
        """"Captioo"という名前のフォルダを、get_project_mailsのステップ1-2と同じ手順
        (検索フォルダ優先→受信トレイ直下のサブフォルダ)で探す。見つからなければNone。"""
        try:
            for sf in store.GetSearchFolders():
                if sf.Name == "Captioo":
                    return sf
        except: pass
        try:
            for sub in inbox.Folders:
                if sub.Name == "Captioo":
                    return sub
        except: pass
        return None

    def sync_forced_unread_from_outlook_state(self) -> dict:
        """OutlookのVBA(ThisOutlookSession.Flag_unread_setup/ProcessFolder)と同じ条件で
        受信トレイ+"Captioo"フォルダを走査し、FlagStatus==2 または カテゴリに"Just Do It"を含み、
        かつ現在既読(UnRead==False)のメールを強制的に未読へ戻す(item.UnRead=True; item.Save())。
        呼び出し元が「Outlook再起動を検知した場合のみ1回」呼ぶことを想定した実処理本体。
        "Captioo"フォルダが見つからない場合は受信トレイのみで実行し、静かにスキップする。"""
        updated_count = 0
        affected_entry_ids = []
        affected_conversation_ids = set()
        SCAN_CAP = 20000  # VBA同様フォルダ全体を走査する想定だが暴走防止の安全弁
        try:
            pythoncom.CoInitialize()
            outlook = win32com.client.Dispatch("Outlook.Application")
            namespace = outlook.GetNamespace("MAPI")
            inbox = namespace.GetDefaultFolder(6)
            store = inbox.Store
            captioo = self._find_captioo_folder(store, inbox)
            target_folders = [inbox] + ([captioo] if captioo else [])

            for folder in target_folders:
                try:
                    items = folder.Items
                except: continue
                scan_count = 0
                for item in items:
                    if scan_count >= SCAN_CAP: break
                    scan_count += 1
                    try:
                        flag_status = getattr(item, 'FlagStatus', 0)
                        categories = getattr(item, 'Categories', '') or ''
                        is_target = flag_status == 2 or _mail_has_just_do_it_category(categories)
                        if is_target and not item.UnRead:
                            item.UnRead = True
                            item.Save()
                            updated_count += 1
                            eid = getattr(item, 'EntryID', '')
                            conv_id = getattr(item, 'ConversationID', '') or eid
                            if eid: affected_entry_ids.append(eid)
                            if conv_id: affected_conversation_ids.add(conv_id)
                    except: continue
        except Exception as e:
            print(f"Outlook再起動同期(強制未読化)エラー: {e}")
        finally:
            try: pythoncom.CoUninitialize()
            except: pass
        return {
            "updated_count": updated_count,
            "affected_entry_ids": affected_entry_ids,
            "affected_conversation_ids": affected_conversation_ids
        }

    def move_mails_to_promotion(self, entry_ids: list) -> int:
        success_count = 0
        try:
            pythoncom.CoInitialize()
            outlook = win32com.client.Dispatch("Outlook.Application")
            namespace = outlook.GetNamespace("MAPI")
            inbox = namespace.GetDefaultFolder(6)
            root_folder = inbox.Parent
            try: promo_folder = root_folder.Folders("Promotion")
            except:
                try: promo_folder = root_folder.Folders.Add("Promotion")
                except: return 0
            for eid in entry_ids:
                try:
                    item = namespace.GetItemFromID(eid)
                    item.Move(promo_folder)
                    success_count += 1
                except: pass
        except Exception as e: print(f"Move Error: {e}")
        finally:
            try: pythoncom.CoUninitialize()
            except: pass
        return success_count

    def open_mail_item(self, entry_id: str):
        """指定されたメールをOutlookで開く"""
        try:
            pythoncom.CoInitialize()
            outlook = win32com.client.Dispatch("Outlook.Application")
            namespace = outlook.GetNamespace("MAPI")
            item = namespace.GetItemFromID(entry_id)
            item.Display()
            
            try:
                insp = item.GetInspector
                if insp: insp.Activate()
            except: pass
            
            pythoncom.CoUninitialize()
            return True
        except Exception as e:
            print(f"Open Item Error: {e}")
            return False

    def show_thread_in_explorer(self, topic: str, entry_id: str):
        try:
            pythoncom.CoInitialize()
            outlook = win32com.client.Dispatch("Outlook.Application")
            namespace = outlook.GetNamespace("MAPI")
            explorer = outlook.ActiveExplorer()
            if not explorer:
                inbox = namespace.GetDefaultFolder(6)
                explorer = inbox.GetExplorer()
                explorer.Display()
            explorer.Activate()
            try:
                inbox = namespace.GetDefaultFolder(6)
                explorer.CurrentFolder = inbox
            except: pass
            
            safe_topic = re.sub(r'\s*\([^)]*\)\s*$', '', topic or '')
            safe_topic = re.sub(r'[":\(\)\-\[\]\{\}<>\']', ' ', safe_topic)
            safe_topic = re.sub(r'\s+', ' ', safe_topic).strip()
            
            query = f'subject:"{safe_topic}"'
            explorer.Search(query, 0)
            try:
                item = namespace.GetItemFromID(entry_id)
                if explorer.IsItemSelectableInView(item):
                    explorer.ClearSelection()
                    explorer.AddToSelection(item)
            except: pass
            pythoncom.CoUninitialize()
            return True
        except Exception as e:
            print(f"Explorer Error: {e}")
            return False

    def _traverse_conversation(self, item, conversation, all_mails, processed_entry_ids):
        try:
            self._add_single_item(item, all_mails, processed_entry_ids, "Conversation")
            for child in conversation.GetChildren(item):
                self._traverse_conversation(child, conversation, all_mails, processed_entry_ids)
        except: pass

    def _add_single_item(self, item, all_mails, processed_entry_ids, folder_name, light_mode=None, skip_attachments=False):
        try:
            eid = getattr(item, 'EntryID', '')
            if not eid or eid in processed_entry_ids: return
            received_dt = self._get_date_from_item(item)
            if folder_name == "Conversation":
                try: f_name = item.Parent.Name
                except: f_name = "関連メール"
            else: f_name = folder_name
            if light_mode is None:
                light_mode = getattr(self, "_active_search_light_mode", False)
            all_mails.append(self._item_to_dict(item, received_dt, f_name, light_mode=light_mode, skip_attachments=skip_attachments))
            processed_entry_ids.add(eid)
        except: pass

    def _get_date_from_item(self, item):
        r = getattr(item, 'ReceivedTime', None) or getattr(item, 'SentOn', None)
        if r is None: return datetime.now()
        if hasattr(r, 'replace'): return r.replace(tzinfo=None)
        return datetime(r.year, r.month, r.day, r.hour, r.minute, r.second)
    
    def _clean_body_text(self, text):
        if not text: return ""
        cleaned = re.sub(r'[\r\n]+', '\n', text)
        return cleaned.strip()

 
    def _item_to_dict(self, item, received_dt, folder_name, light_mode=False, skip_attachments=False):
        s_email = ""
        sender = getattr(item, 'Sender', None)
        if sender: s_email = self._resolve_object_to_smtp(sender)
        else: s_email = self._resolve_object_to_smtp(item)

        entry_id = getattr(item, 'EntryID', '')
        raw_unread = bool(getattr(item, 'UnRead', False))
        categories = getattr(item, 'Categories', '') or ''
        flag_status = getattr(item, 'FlagStatus', 0)
        has_just_do_it_category = _mail_has_just_do_it_category(categories)
        is_forced_unread_target = flag_status == 2 or has_just_do_it_category
        is_session_marked_read = str(entry_id) in getattr(self, "session_marked_read_entry_ids", set())
        if is_session_marked_read and is_forced_unread_target:
            effective_unread = False
        else:
            effective_unread = raw_unread or is_forced_unread_target

        routing = "other"
        try:
            my_smtp = self.user_smtp_address
            if my_smtp:
                recipients = item.Recipients
                to_list = []
                for r in recipients:
                    if r.Type == 1: # To
                        ra = self._resolve_object_to_smtp(r)
                        if ra: to_list.append(ra)
                
                if len(to_list) == 1 and to_list[0] == my_smtp:
                    routing = "to_me"
                elif my_smtp in to_list and len(to_list) > 1:
                    routing = "with_me"
        except: pass

        inline_images = {}
        attachment_names = []
        attachments = None
        try:
            attachments = getattr(item, 'Attachments', None)
            if attachments and not light_mode and not skip_attachments:
                import tempfile, base64, io, os
                try: 
                    from PIL import Image
                    has_pillow = True
                except ImportError: 
                    has_pillow = False
                
                for i in range(1, attachments.Count + 1):
                    attach = attachments.Item(i)
                    cid = ""
                    try: 
                        cid = attach.PropertyAccessor.GetProperty("http://schemas.microsoft.com/mapi/proptag/0x3712001F")
                    except:
                        try: 
                            cid = attach.PropertyAccessor.GetProperty("http://schemas.microsoft.com/mapi/proptag/0x3712001E")
                        except: pass
                    
                    if cid:
                        try:
                            safe_name = "".join([c for c in getattr(attach, 'FileName', f'img_{i}.png') if c.isalnum() or c in "._-"])
                            if not safe_name: safe_name = f"temp_img_{i}.png"
                            t_path = os.path.join(tempfile.gettempdir(), safe_name)
                            attach.SaveAsFile(t_path)
                            
                            if has_pillow:
                                with Image.open(t_path) as img:
                                    img.thumbnail((800, 800))
                                    fmt = img.format if img.format else 'PNG'
                                    if img.mode != 'RGB' and fmt in ['JPEG', 'JPG']: 
                                        img = img.convert('RGB')
                                    buf = io.BytesIO()
                                    img.save(buf, format=fmt)
                                    b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
                                    mime = f"image/{fmt.lower()}"
                            else:
                                with open(t_path, "rb") as f:
                                    b64 = base64.b64encode(f.read()).decode('utf-8')
                                    mime = "image/png"
                            
                            inline_images[cid] = f"data:{mime};base64,{b64}"
                            os.remove(t_path)
                        except: pass
                    else:
                        try:
                            fn = getattr(attach, 'FileName', '')
                            if fn: attachment_names.append(fn)
                        except: pass
        except: pass

        return {
            'subject': getattr(item, 'Subject', '(件名なし)') or '(件名なし)',
            'sender_name': getattr(item, 'SenderName', '') or '',
            'sender_email': s_email,
            'received': received_dt,
            'body': '' if light_mode else self._clean_body_text(getattr(item, 'Body', '') or '')[:300000],
            'html_body': '' if light_mode else getattr(item, 'HTMLBody', '') or '',
            'inline_images': inline_images,
            'attachment_names': attachment_names,
            'conversation_id': getattr(item, 'ConversationID', ''),
            'conversation_topic': getattr(item, 'ConversationTopic', ''),
            'entry_id': entry_id,
            'importance': getattr(item, 'Importance', 1),
            'folder': folder_name,
            'has_attachments': attachments and attachments.Count > 0,
            'unread': effective_unread,
            'categories': categories,
            'flag_status': flag_status,
            'routing': routing
        }
 
    def _get_sender_smtp_address_robust(self, item):
        try:
            s = getattr(item, 'Sender', None)
            if s: return self._resolve_object_to_smtp(s)
            return self._resolve_object_to_smtp(item)
        except: return ""


    def group_by_thread(self, mails: list) -> dict:
        threads = defaultdict(lambda: {
            'topic': '', 'mails': [], 'participants': set(),
            'latest_date': None, 'latest_entry_id': None,
            'latest_folder': '',
            'mail_count': 0, 'has_high_importance': False, 'has_unread': False,
            'display_tag': 'normal', 'all_categories': set(), 'is_flagged': False
        })
        for mail in mails:
            conv_id = mail['conversation_id'] or mail['entry_id']
            t = threads[conv_id]
            t['mails'].append(mail)
            if not t['topic'] or len(mail['conversation_topic']) > len(t['topic']):
                t['topic'] = mail['conversation_topic'] or mail['subject']
            t['participants'].add(mail['sender_name'])
            t['mail_count'] += 1
            if mail['importance'] == 2: t['has_high_importance'] = True
            if mail.get('unread'): t['has_unread'] = True
            
            if mail.get('categories'):
                cats = re.split(r'[;,]\s*', mail['categories'])
                for c in cats:
                    if c.strip(): t['all_categories'].add(c.strip())
            
            if mail.get('flag_status') == 2 or _mail_has_just_do_it_category(mail.get('categories', '')):
                t['is_flagged'] = True

            if t['latest_date'] is None or mail['received'] > t['latest_date']:
                t['latest_date'] = mail['received']
                t['latest_entry_id'] = mail['entry_id']
                t['latest_folder'] = mail.get('display_folder') or mail.get('folder', '')
        
        for cid, t in threads.items():
            t['mails'] = sorted(t['mails'], key=lambda x: x['received'])
            t['participants'] = list(t['participants'])
            t['categories_str'] = ", ".join(sorted(list(t['all_categories'])))
            
            has_unread_tome = any(m['unread'] and m['routing'] == 'to_me' for m in t['mails'])
            has_unread_withme = any(m['unread'] and m['routing'] == 'with_me' for m in t['mails'])
            has_tome = any(m['routing'] == 'to_me' for m in t['mails'])
            has_withme = any(m['routing'] == 'with_me' for m in t['mails'])
            
            if t['has_unread']:
                if has_unread_tome: t['display_tag'] = 'tome_unread'
                elif has_unread_withme: t['display_tag'] = 'withme_unread'
                else: t['display_tag'] = 'other_unread'
            else:
                if has_tome: t['display_tag'] = 'tome_read'
                elif has_withme: t['display_tag'] = 'withme_read'
                else: t['display_tag'] = 'other_read'

        return dict(sorted(threads.items(), key=lambda x: x[1]['latest_date'], reverse=True))



    def get_project_mails(self, folder_name: str, days: int, include_sent: bool = False) -> list:
        """
        プロジェクト用メール取得 (V39: 03_R19Projects向けカテゴリタグフォールバック対応)
        include_sent=True の場合、取得したスレッド(ConversationID)に該当する送信済み
        アイテムも追加で収集する(統括コックピットv2の「自分が返信済みか」判定用)。
        ※ 添付ファイル・インライン画像の処理は常にスキップする(skip_attachments=True)。
        AI要約(summarize_project_threads/summarize_action_dashboard)は本文テキストのみ
        参照し添付データは使わないため、取得のたびに毎回発生する一時ファイル書き出し・
        画像処理の負荷を避けて高速化する(get_relevant_mails_for_periodと同じ最適化)。
        """
        all_mails = []
        processed_entry_ids = set()
        try:
            pythoncom.CoInitialize()
            outlook = win32com.client.Dispatch("Outlook.Application")
            namespace = outlook.GetNamespace("MAPI")
            inbox = namespace.GetDefaultFolder(6)
            store = inbox.Store
            
            target_folder = None
            
            # 1. 検索フォルダー(Search Folders)を優先的に探す
            try:
                search_folders = store.GetSearchFolders()
                for sf in search_folders:
                    if sf.Name == folder_name:
                        target_folder = sf
                        break
            except: pass

            # 2. 見つからない場合、受信トレイ(Inbox)のサブフォルダーから探す
            if not target_folder:
                try:
                    for sub in inbox.Folders:
                        if sub.Name == folder_name:
                            target_folder = sub
                            break
                except: pass

            # 日付文字列の生成 (V33パッチ適用済の安全なロジックを継承)
            if days == -12:
                date_str = (datetime.now() - timedelta(hours=12)).strftime("%m/%d/%Y %H:%M")
            elif days == 0:
                date_str = (datetime.now() - timedelta(hours=24)).strftime("%m/%d/%Y %H:%M")
            else:
                date_str = (datetime.now() - timedelta(days=days)).strftime("%m/%d/%Y")

            # 3. 03_R19Projects専用フォールバック:
            #    検索フォルダが見つからない場合、受信トレイで「R19Proj」を含む
            #    分類タグが付与されているメールスレッドを検索する
            if not target_folder and folder_name == "03_R19Projects":
                print(f"[R19] 検索フォルダ未発見。受信トレイでR19Projカテゴリタグ検索にフォールバック...")
                try:
                    items = inbox.Items
                    items.Sort("[ReceivedTime]", True)
                    try:
                        items = items.Restrict(f"[ReceivedTime] >= '{date_str}'")
                    except: pass
                    
                    # スレッド単位で「R19Proj」を含む分類タグを持つメールを収集
                    r19_conv_ids = set()
                    scan_count = 0
                    for item in items:
                        if scan_count >= 3000: break
                        try:
                            cats = getattr(item, 'Categories', '') or ''
                            if 'R19Proj' in cats:
                                conv_id = getattr(item, 'ConversationID', '')
                                if conv_id:
                                    r19_conv_ids.add(conv_id)
                            scan_count += 1
                        except: continue
                    
                    if r19_conv_ids:
                        # 対象スレッドIDを持つ全メールを収集
                        items2 = inbox.Items
                        items2.Sort("[ReceivedTime]", True)
                        try:
                            items2 = items2.Restrict(f"[ReceivedTime] >= '{date_str}'")
                        except: pass
                        scan_count2 = 0
                        for item in items2:
                            if scan_count2 >= 3000: break
                            try:
                                conv_id = getattr(item, 'ConversationID', '')
                                if conv_id in r19_conv_ids:
                                    self._add_single_item(item, all_mails, processed_entry_ids, folder_name, skip_attachments=True)
                                scan_count2 += 1
                            except: continue
                        print(f"[R19] フォールバック完了: {len(all_mails)}件取得 ({len(r19_conv_ids)}スレッド)")
                except Exception as e:
                    print(f"[R19] フォールバック検索エラー: {e}")

            else:
                # いずれにも見つからない場合は空で返す
                if not target_folder:
                    return []

                items = target_folder.Items
                items.Sort("[ReceivedTime]", True)

                try:
                    items = items.Restrict(f"[ReceivedTime] >= '{date_str}'")
                except: pass

                scan_count = 0
                for item in items:
                    if scan_count >= 1000: break
                    try:
                        # 物理重複排除を伴う追加(skip_attachments=True: AI要約は本文テキストのみ
                        # 参照し添付/インライン画像は使わないため、高速化のためスキップする。
                        # get_relevant_mails_for_period(アクションダッシュボード用)と同じ最適化)
                        self._add_single_item(item, all_mails, processed_entry_ids, folder_name, skip_attachments=True)
                        scan_count += 1
                    except: continue

            # 4. include_sent=True の場合、対象スレッド(ConversationID)に該当する送信済み
            #    アイテムも追加で収集する。get_project_mailsのフォルダベース検索は送信済み
            #    フォルダには及ばないため、既存のR19フォールバック(3)と同じ「対象の
            #    ConversationIDを集めて別フォルダを再走査する」パターンを踏襲する。
            if include_sent and all_mails:
                try:
                    conv_ids = {m['conversation_id'] for m in all_mails if m.get('conversation_id')}
                    if conv_ids:
                        sent_folder = namespace.GetDefaultFolder(5)
                        sent_items = sent_folder.Items
                        sent_items.Sort("[ReceivedTime]", True)
                        try:
                            sent_items = sent_items.Restrict(f"[ReceivedTime] >= '{date_str}'")
                        except: pass
                        scan_count3 = 0
                        for item in sent_items:
                            if scan_count3 >= 1000: break
                            try:
                                conv_id = getattr(item, 'ConversationID', '')
                                if conv_id in conv_ids:
                                    self._add_single_item(item, all_mails, processed_entry_ids, "送信済み", skip_attachments=True)
                                scan_count3 += 1
                            except: continue
                except Exception as e:
                    print(f"Project Sent-Items Search Error [{folder_name}]: {e}")
        except Exception as e:
            print(f"Project Search Error [{folder_name}]: {e}")
        finally:
            try: pythoncom.CoUninitialize()
            except: pass
        return all_mails
        

    def get_staff_mails(self, staff_name: str, days: int, flags: dict) -> list:
        if not self.namespace: return []
        target_folders = [6, 5] 
        all_mails = []
        name_lower = staff_name.lower()
        
        for f_idx in target_folders:
            try:
                folder = self.namespace.GetDefaultFolder(f_idx)
                items = folder.Items
                items.Sort("[ReceivedTime]", True)
                
                if days == -12:
                    cutoff = (datetime.now() - timedelta(hours=12)).strftime('%m/%d/%Y %H:%M %p')
                    restricted = items.Restrict(f"\"[ReceivedTime]\" >= '{cutoff}'")
                elif days == 0:
                    cutoff = (datetime.now() - timedelta(hours=24)).strftime('%m/%d/%Y %H:%M %p')
                    restricted = items.Restrict(f"\"[ReceivedTime]\" >= '{cutoff}'")
                elif days > 0:
                    cutoff = (datetime.now() - timedelta(days=days)).strftime('%m/%d/%Y %H:%M %p')
                    restricted = items.Restrict(f"\"[ReceivedTime]\" >= '{cutoff}'")
                else:
                    restricted = items
                
                for item in restricted:
                    try:
                        if item.Class == 43: # MailItem
                            match = False
                            if flags.get('from'):
                                sn = (getattr(item, 'SenderName', '') or '').lower()
                                se = (getattr(item, 'SenderEmailAddress', '') or '').lower()
                                if name_lower in sn or name_lower in se: match = True
                            if not match and flags.get('to'):
                                to = (getattr(item, 'To', '') or '').lower()
                                if name_lower in to: match = True
                            if not match and flags.get('cc'):
                                cc = (getattr(item, 'CC', '') or '').lower()
                                if name_lower in cc: match = True
                                
                            if match:
                                dt = getattr(item, 'ReceivedTime', None)
                                if dt:
                                    try: dt = datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)
                                    except: pass
                                    all_mails.append(self._item_to_dict(item, dt, folder.Name))
                    except: pass
            except: pass
        return all_mails

# ============================================================
# AI要約クラス
# ============================================================



class MailSummarizer:
    def __init__(self, api_key: str, model_name: str):
        """
        最新の google.genai SDK を使用して初期化を行う (V2026.0421.24)
        """
        from google import genai
        # クライアントの初期化
        self.client = genai.Client(api_key=api_key)
        self.model_id = model_name
        self._configured = True
        
        # トークン計測用のカウンター
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def _call_ai(self, prompt: str) -> str:
        """
        AIへのリクエストを集中管理し、トークン計測と通信を安全に行う共通メソッド
        """
        response = self.client.models.generate_content(
            model=self.model_id,
            contents=prompt
        )
        
        # トークン使用量の計測 (2026年SDKの usage_metadata 形式)
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            self.total_input_tokens += getattr(response.usage_metadata, 'prompt_token_count', 0)
            self.total_output_tokens += getattr(response.usage_metadata, 'candidates_token_count', 0)
            
        return response.text if response.text else ""

    def _run_genai_call_with_schema(self, prompt: str, schema: dict, override_model: str = None) -> dict:
        """
        指定されたスキーマに従ってAIを呼び出し、構造化されたJSONを取得する共通ヘルパー (V25 Modern SDK版)
        override_model が指定された場合はそのモデルを優先使用する（Stage 1高速化用）
        """
        from google.genai import types
        try:
            # override_model が指定されていればそれを使用し、なければデフォルトの self.model_id を使用
            target_model = override_model if override_model else self.model_id
            # Modern SDK (2026規格) による構造化出力リクエスト
            response = self.client.models.generate_content(
                model=target_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema,
                    max_output_tokens=8192,
                    temperature=0.2
                )
            )

            # トークン使用量の集計 (最新の usage_metadata プロトコルに準拠)
            if response.usage_metadata:
                self.total_input_tokens += getattr(response.usage_metadata, 'prompt_token_count', 0)
                self.total_output_tokens += getattr(response.usage_metadata, 'candidates_token_count', 0)

            if not response.text:
                return self._error("AIからの空の回答")

            result = self._extract_json(response.text)
            if result:
                return result
            
            # V21デバッグ追加: パース失敗時に生のAI回答を出力して原因を特定する
            print(f"\n[DEBUG] ❌ JSONパース失敗。生の回答(先頭/末尾):\n{response.text[:200]} ... \n{response.text[-200:]}\n")

            return self._error("JSONパース失敗 (構造不備)")

        except Exception as e:
            print(f"⚠️ API通信エラー (Schema Call): {e}")
            return self._error(f"API通信エラー: {str(e)}")

    def summarize_multiple_threads(self, threads: dict, cb=None, past_limit: int = 800, latest_unlimited: bool = False, long_text_choice: int = 1) -> dict:
        results = {}
        total = len(threads)
        done = 0
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=8) as exc:
            futures = {exc.submit(self.summarize_thread, t, past_limit, latest_unlimited, long_text_choice): cid for cid, t in threads.items()}
            for f in as_completed(futures):
                cid = futures[f]
                done += 1
                try:
                    results[cid] = f.result()
                    if cb: cb(done, total, f"完了: {threads[cid]['topic'][:20]}")
                except Exception as e: results[cid] = self._error(str(e))
        return results

    def summarize_thread(self, thread_data: dict, past_limit: int = 800, latest_unlimited: bool = False, long_text_choice: int = 1) -> dict:
        import re
        mails = thread_data['mails']
        is_rss = any(m.get('folder') == "RSS フィード" for m in mails)
        if is_rss:
            m = mails[0]
            web_text = self._fetch_web_content(m['body'])
            result = self._generate_rss_summary(m['subject'], m['body'], web_text)
            urls = re.findall(r'(https?://[^\s<>"]+)', m['body'])
            if urls and isinstance(result, dict): result['article_url'] = urls[0]
            return result
            
        total_body_len = sum(len(m['body']) for m in mails)
        if total_body_len > 10000 and long_text_choice == 2:
            return {"summary": "※文字数超過のため、要約処理はスキップされました（軽量表示モード）。", "skipped": True}
            
        mail_texts = []
        total_len = 0
        limit = 3000000 
        
        for i, m in enumerate(mails, 1):
            is_latest = (i == len(mails))
            if is_latest:
                if total_body_len > 10000 and long_text_choice == 1:
                    raw_body = m['body']
                    if len(raw_body) > 10000:
                        body = self._clean(raw_body[:2000] + "\n\n...（中略）...\n\n" + raw_body[-8000:])
                    else: body = self._clean(raw_body)
                else:
                    max_chars = 300000 if long_text_choice == 3 or latest_unlimited else 10000
                    body = self._clean(m['body'][:max_chars])
            else:
                body_cleaned = self._clean_body_for_ai(m['body'], limit=past_limit)
                body = self._clean(body_cleaned)
                
            text = f"\n【メール{i}】日時:{m['received']} 送信者:{m['sender_name']}\n本文:{body}\n"
            if total_len + len(text) > limit: break
            mail_texts.append(text)
            total_len += len(text)
        
        BATCH_SIZE = 10
        all_individual_summaries = []
        if len(mail_texts) > BATCH_SIZE:
            for i in range(0, len(mail_texts), BATCH_SIZE):
                batch = mail_texts[i : i + BATCH_SIZE]
                batch_summaries = self._generate_batch_summaries(batch, i+1)
                all_individual_summaries.extend(batch_summaries)
            diff = len(mail_texts) - len(all_individual_summaries)
            if diff > 0: all_individual_summaries.extend(["(生成失敗)"] * diff)
            return self._generate_overall_analysis(thread_data['topic'], mail_texts, all_individual_summaries)
        else:
            return self._generate_single_shot(thread_data['topic'], mail_texts)

    def _generate_batch_summaries(self, mail_texts, start_idx):
        from google.genai import types
        content = "".join(mail_texts)
        prompt = f"以下のメール群の内容をそれぞれ100文字程度の日本語で要約し、JSONで出力してください。\n{content}"
        schema = {
            "type": "OBJECT", "properties": {"mail_summaries": {"type": "ARRAY", "items": {"type": "STRING"}}}, "required": ["mail_summaries"]
        }
        try:
            res = self.client.models.generate_content(model=self.model_id, contents=prompt, config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=schema))
            if res.usage_metadata:
                self.total_input_tokens += getattr(res.usage_metadata, 'prompt_token_count', 0)
                self.total_output_tokens += getattr(res.usage_metadata, 'candidates_token_count', 0)
            data = self._extract_json(res.text)
            if data and "mail_summaries" in data:
                summaries = data["mail_summaries"]
                if len(summaries) < len(mail_texts): summaries.extend(["(生成失敗)"] * (len(mail_texts) - len(summaries)))
                return summaries
        except: pass
        return ["(要約生成エラー)"] * len(mail_texts)

    def _generate_overall_analysis(self, topic, mail_texts, individual_summaries):
        from google.genai import types
        content = "".join(mail_texts)
        prompt = f"トピック: {topic}\n内容: {content}\n上記のスレッド全体を【日本語】で分析・要約し、JSONで出力してください。"
        schema = {
            "type": "OBJECT", "properties": {
                "summary": {"type": "STRING"},
                "action_items": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {"priority": {"type": "STRING"}, "action": {"type": "STRING"}, "owner": {"type": "STRING"}, "deadline": {"type": "STRING"}}}}
            }, "required": ["summary", "action_items"]
        }
        try:
            res = self.client.models.generate_content(model=self.model_id, contents=prompt, config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=schema))
            if res.usage_metadata:
                self.total_input_tokens += getattr(res.usage_metadata, 'prompt_token_count', 0)
                self.total_output_tokens += getattr(res.usage_metadata, 'candidates_token_count', 0)
            result = self._extract_json(res.text)
            if not result: result = self._error("解析失敗")
            result["mail_summaries"] = individual_summaries
            return result
        except Exception as e: return self._error(str(e))

    def _generate_single_shot(self, topic, mail_texts):
        from google.genai import types
        content = "".join(mail_texts)
        prompt = f"トピック: {topic}\n内容: {content}\n全ての内容を【日本語】で要約・抽出し、JSON形式で出力せよ。"
        schema = {
            "type": "OBJECT", "properties": {
                "summary": {"type": "STRING"},
                "mail_summaries": {"type": "ARRAY", "items": {"type": "STRING"}},
                "action_items": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {"priority": {"type": "STRING"}, "action": {"type": "STRING"}, "owner": {"type": "STRING"}, "deadline": {"type": "STRING"}}}}
            }, "required": ["summary", "mail_summaries", "action_items"]
        }
        try:
            res = self.client.models.generate_content(model=self.model_id, contents=prompt, config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=schema))
            if res.usage_metadata:
                self.total_input_tokens += getattr(res.usage_metadata, 'prompt_token_count', 0)
                self.total_output_tokens += getattr(res.usage_metadata, 'candidates_token_count', 0)
            return self._extract_json(res.text) if res and res.text else self._error("レスポンス空")
        except Exception as e: return self._error(str(e))

    def _fetch_web_content(self, text):
        import re, requests
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return "BeautifulSoup未インストール"
        urls = re.findall(r'(https?://[^\s<>"]+)', text)
        if not urls: return "URLなし"
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            res = requests.get(urls[0], headers=headers, timeout=10)
            res.raise_for_status()
            soup = BeautifulSoup(res.content, 'html.parser')
            for s in soup(["script", "style"]): s.decompose()
            return f"【本文】\n{soup.get_text()[:15000]}"
        except Exception as e: return f"取得失敗: {e}"

    def _generate_rss_summary(self, topic, rss_body, web_text):
        from google.genai import types
        content = f"RSS: {topic}\n{web_text}"
        prompt = f"以下の記事の内容を高校生にもわかる平易な【日本語】で要約し、JSONで出力してください。\n{content}"
        schema = {
            "type": "OBJECT", "properties": {
                "is_rss": {"type": "BOOLEAN"}, "title": {"type": "STRING"}, "summary": {"type": "STRING"},
                "keywords": {"type": "STRING"}, "conclusion": {"type": "STRING"},
                "main_points": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {"point_title": {"type": "STRING"}, "description": {"type": "STRING"}}}}
            }, "required": ["is_rss", "title", "summary", "keywords", "conclusion", "main_points"]
        }
        try:
            res = self.client.models.generate_content(model=self.model_id, contents=prompt, config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=schema))
            if res.usage_metadata:
                self.total_input_tokens += getattr(res.usage_metadata, 'prompt_token_count', 0)
                self.total_output_tokens += getattr(res.usage_metadata, 'candidates_token_count', 0)
            result = self._extract_json(res.text)
            if isinstance(result, dict):
                result['is_rss'] = True
            return result
        except: return self._error("RSS解析失敗")



    def summarize_project_threads(self, project_name: str, threads: dict, knowledge: dict, retry_callback=None, progress_callback=None) -> dict:
        """
        プロジェクト単位の解析を実行する (V25 Modern SDKベース + V32 3層構造化と入力制限)
        """
        import time, json, hashlib, os
        from datetime import datetime
        from concurrent.futures import ThreadPoolExecutor, as_completed

        print(f"\n{'='*20}\n🚀 AI PROJECT ANALYSIS START (2-Stage): {project_name}\nThread count: {len(threads)}")

        merged_result = {
            "manager_actions": [], "staff_status": [], "stalled_monitor": [],
            "updated_history": "", "ai_questions": [], "threads": []
        }
        
        def ensure_struct(items, default_cat="その他"):
            res = []
            if not items: return res
            for item in items:
                if isinstance(item, dict):
                    res.append({
                        "category": str(item.get("category") or default_cat),
                        "project_scope": str(item.get("project_scope") or project_name),
                        "action_type": str(item.get("action_type") or "通知・共有"),
                        "text": str(item.get("text") or ""),
                        "status_icon": str(item.get("status_icon") or "⚪"),
                        "source_thread_ids": item.get("source_thread_ids", [])
                    })
            return res

        if not threads: 
            return self._error("活動なし")

        proj_know = knowledge.get('projects', {}).get(project_name, {})
        master_hist = proj_know.get('master_history', '')
        recent_hist = proj_know.get('history_summary', '')
        ai_rules_text = "\n".join([f"- {r}" for r in proj_know.get('ai_correction_rules', [])]) or "特になし"
        
        current_rules_hash = hashlib.md5(ai_rules_text.encode('utf-8')).hexdigest()

        safe_project_name = "".join([c for c in project_name if c.isalnum() or c in " ._-"])
        cache_dir = "analysis_cache"
        os.makedirs(cache_dir, exist_ok=True)
        cache_file = os.path.join(cache_dir, f"project_{safe_project_name}.json")

        cache_data = {"rules_hash": "", "threads": {}}
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
            except: pass

        if cache_data.get("rules_hash") != current_rules_hash:
            print("  -> 🔄 ルール更新を検知。解析キャッシュをリフレッシュします。")
            cache_data["threads"] = {}
            cache_data["rules_hash"] = current_rules_hash

        needs_update = {}
        for cid, t in threads.items():
            mail_count = len(t['mails'])
            cached = cache_data["threads"].get(cid)
            if not cached or cached.get("mail_count") != mail_count or cached.get("data", {}).get("_error"):
                needs_update[cid] = t

        if needs_update:
            msg = f"⚙️ Stage 1: {len(needs_update)}件の新規/更新スレッドを抽出中..."
            print(f"  -> {msg}")
            if progress_callback: progress_callback(msg)

            thread_schema = {
                "type": "OBJECT", "properties": {
                    "thread_id": {"type": "STRING"}, "topic": {"type": "STRING"}, "is_target": {"type": "BOOLEAN"},
                    "summary": {"type": "STRING"}, "category": {"type": "STRING"}, "project_scope": {"type": "STRING"},
                    "action_type": {"type": "STRING"}, "importance": {"type": "STRING"}, "reasoning": {"type": "STRING"},
                    "actions": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
                        "owner": {"type": "STRING"}, "action": {"type": "STRING"}, "deadline": {"type": "STRING"}, "status": {"type": "STRING"}
                    }}}
                }, "required": ["thread_id", "topic", "is_target", "summary", "category", "project_scope", "action_type"]
            }

            done_count = 0
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = {}
                for cid, t in needs_update.items():
                    mail_texts = []
                    for m in t['mails']:
                        body = self._clean(self._clean_body_for_ai(m['body']))
                        mail_texts.append(f"【送信者:{m['sender_name']}】\n本文:{body}\n")
                    content = "".join(mail_texts)[:30000]
                    
                    prompt = f"""
                    プロジェクト「{project_name}」に関する以下のメールスレッドを日本語で分析し、指定されたJSON形式で出力せよ。
                    
                    【厳守事項】
                    - 引用タグ(source/cite)は絶対に出力しないこと。
                    - category は必ず [プロジェクト管理, 定常業務, 障害・トラブル, 技術サポート, 運用・保守, 組織・チーム, 購買・調達, 法務・監査, その他] のいずれかを指定。
                    - action_type は必ず [通知・共有, 承認・決裁, 作業・依頼, 相談・質問, その他] のいずれかを指定。
                    - project_scope は "{project_name}" を指定すること。
                    - thread_id は理由を問わず "{cid}" という文字列を必ず出力すること。

                    ルール: {ai_rules_text}
                    内容: {content}
                    """
                    futures[executor.submit(self._run_genai_call_with_schema, prompt, thread_schema)] = (cid, len(t['mails']), t['topic'])

                for future in as_completed(futures):
                    cid, m_count, t_topic = futures[future]
                    res = future.result()
                    done_count += 1
                    if progress_callback: progress_callback(f"⚙️ Stage 1: 解析中 ({done_count}/{len(needs_update)})...")

                    if res and not res.get('_error'):
                        res['thread_id'] = cid
                        cache_data["threads"][cid] = {"mail_count": m_count, "latest_entry_id": needs_update[cid].get('latest_entry_id', ''), "data": res}
                    else:
                        cache_data["threads"][cid] = {
                            "mail_count": m_count,
                            "latest_entry_id": needs_update[cid].get('latest_entry_id', ''),
                            "data": {"thread_id": cid, "topic": t_topic, "is_target": False, "summary": f"(解析失敗: {res.get('summary', '接続エラー')})", "category": "エラー", "_error": True}
                        }


            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)

        msg2 = "📊 Stage 2: プロジェクト全体サマリを統合中..."
        print(f"  -> {msg2}")
        if progress_callback: progress_callback(msg2)

        target_for_s2 = []
        for cid, t in threads.items():
            cached = cache_data["threads"].get(cid)
            if cached and cached.get("data"):
                merged_result["threads"].append(cached["data"])
                if cached["data"].get("is_target", True) and not cached["data"].get("_error"):
                    imp = cached['data'].get('importance', '中')
                    imp_val = 0 if imp == '高' else 2 if imp == '低' else 1
                    dt = t.get('latest_date')
                    ts = int(dt.timestamp()) if dt else 0
                    text = f"[ID: {cid}] 【トピック: {cached['data'].get('topic')}】 重要度: {imp}\n要約: {cached['data'].get('summary')}"
                    target_for_s2.append((imp_val, -ts, text))

        # V32追加: 情報過多によるAI暴走を防ぐため、重要度>新着順でソートし上位15件に絞る
        target_for_s2.sort(key=lambda x: (x[0], x[1]))
        active_summaries = [x[2] for x in target_for_s2[:15]]

        if not active_summaries:
            merged_result["staff_status"].append({"category": "その他", "project_scope": project_name, "action_type": "通知・共有", "text": "解析対象期間中に有効な活動記録が見つかりませんでした。", "status_icon": "⚪"})
            return merged_result

        shared_item_schema = {
            "type": "OBJECT", "properties": {
                "category": {"type": "STRING"}, "project_scope": {"type": "STRING"},
                "action_type": {"type": "STRING"}, "text": {"type": "STRING"}, "status_icon": {"type": "STRING"},
                "source_thread_ids": {"type": "ARRAY", "items": {"type": "STRING"}}
            }, "required": ["category", "project_scope", "action_type", "text"]
        }
        stage2_schema = {
            "type": "OBJECT", "properties": {
                "manager_actions": {"type": "ARRAY", "items": shared_item_schema, "minItems": 1, "maxItems": 3},
                "staff_status": {"type": "ARRAY", "items": shared_item_schema, "minItems": 1, "maxItems": 3},
                "stalled_monitor": {"type": "ARRAY", "items": shared_item_schema, "minItems": 1, "maxItems": 3},
                "updated_history": {"type": "STRING"}, "ai_questions": {"type": "ARRAY", "items": {"type": "STRING"}}
            }, "required": ["manager_actions", "staff_status", "stalled_monitor", "updated_history"]
        }

        # V32修正: AIパンク防止のため30000文字に制限
        s2_content = "\n\n".join(active_summaries)[:30000]
        
        s2_prompt = f"""
        プロジェクト「{project_name}」の以下の【個別活動要約群】を統合し、全体像をマネージャー視点で分析し、日本語のJSONで回答せよ。
        
        【出力JSONのルートキー（3層構造）】
        - manager_actions: あなた(上司)の介入・承認・決裁が必要な事項、または致命的なブロッカー
        - staff_status: プロジェクトの今週の主要な進捗、および次週予定しているアクション
        - stalled_monitor: 文脈から判断して、ボールを持ったまま返信が止まっている（停滞している）案件

        【厳守ルール】
        1. status_icon は「🔴、🔵、🟡、🟢」などの1文字の絵文字のみを出力すること。
        2. text は必ず【1文のみ】で簡潔にまとめ、100文字以内に収めること。
        3. text の先頭に独自の分類タグを絶対に付けないこと。
        4. category フィールドには「manager_actions」等のJSONキー名を入れるのではなく、必ず既存の分類リスト [プロジェクト管理, 定常業務, 障害・トラブル, 技術サポート, 運用・保守, 組織・チーム, 購買・調達, 法務・監査, その他] のいずれかを指定すること。
        5. project_scope は "{project_name}" を指定すること。
        6. 引用タグは絶対に出力しないこと。
        7. 【最重要】各セクション(manager_actions, staff_status, stalled_monitor)の項目数は、最も重要なものを【厳守して1〜3項目のみ】出力すること。絶対に長文をダラダラと出力せず、1文で簡潔にまとめること。
        8. 各文章の根拠となった情報の [ID: xxx] を、source_thread_ids フィールドに配列形式で必ず含めること。複数ある場合は複数、特定できない場合は空配列とせよ。

        経緯: {master_hist}
        内容: {s2_content}
        """
        
        s2_res = self._run_genai_call_with_schema(s2_prompt, stage2_schema)

        if s2_res and not s2_res.get('_error'):
            merged_result["manager_actions"] = ensure_struct(s2_res.get("manager_actions", []))
            merged_result["staff_status"] = ensure_struct(s2_res.get("staff_status", []))
            merged_result["stalled_monitor"] = ensure_struct(s2_res.get("stalled_monitor", []))
            merged_result["ai_questions"] = s2_res.get("ai_questions", [])
            
            ts = datetime.now().strftime("%Y/%m/%d %H:%M")
            new_hist = s2_res.get("updated_history", "").strip()
            merged_result["updated_history"] = f"**[{ts} プロジェクト分析]**\n{new_hist}\n\n{recent_hist[:3000]}" if new_hist else recent_hist
            print("  -> ✅ Stage 2 成功")
        else:
            print("  -> ❌ Stage 2 失敗")
            merged_result["manager_actions"].append({"category": "システム", "project_scope": "エラー", "action_type": "警告", "text": "全体サマリの統合に失敗しました。個別スレッド詳細は下部で確認可能です。", "status_icon": "⚠️"})

        return merged_result

  
    def summarize_staff_threads(self, staff_name: str, threads: dict, knowledge: dict, retry_callback=None, progress_callback=None) -> dict:
        """
        スタッフ単位の解析を実行する (V25 Modern SDKベース + V30 3層構造 + V31 Truncation Fix)
        """
        import time, json, hashlib, os
        from datetime import datetime
        from concurrent.futures import ThreadPoolExecutor, as_completed

        print(f"\n{'='*20}\n🚀 AI STAFF ANALYSIS START (2-Stage): {staff_name}\nThread count: {len(threads)}")

        merged_result = {
            "manager_actions": [], "staff_status": [], "stalled_monitor": [],
            "updated_history": "", "ai_questions": [], "threads": []
        }
        
        def ensure_struct(items, default_cat="その他"):
            res = []
            if not items: return res
            for item in items:
                if isinstance(item, dict):
                    res.append({
                        "category": str(item.get("category") or default_cat),
                        "project_scope": str(item.get("project_scope") or "横断業務"),
                        "action_type": str(item.get("action_type") or "通知・共有"),
                        "text": str(item.get("text") or ""),
                        "status_icon": str(item.get("status_icon") or "⚪"),
                        "source_thread_ids": item.get("source_thread_ids", [])
                    })
            return res

        if not threads: 
            return self._error("活動なし")

        staff_know = knowledge.get('staffs', {}).get(staff_name, {})
        role = staff_know.get('role', 'スタッフ')
        bg = staff_know.get('background', '')
        master_hist = staff_know.get('master_history', '')
        recent_hist = staff_know.get('history_summary', '')
        
        known_projects = list(knowledge.get('projects', {}).keys())
        allowed_scopes = known_projects + ["横断業務", "その他"]
        proj_list_str = ", ".join(known_projects) if known_projects else "横断業務"
        ai_rules_text = "\n".join([f"- {r}" for r in staff_know.get('ai_correction_rules', [])]) or "特になし"

        current_rules_hash = hashlib.md5(ai_rules_text.encode('utf-8')).hexdigest()

        safe_staff_name = "".join([c for c in staff_name if c.isalnum() or c in " ._-"])
        cache_dir = "analysis_cache"
        os.makedirs(cache_dir, exist_ok=True)
        cache_file = os.path.join(cache_dir, f"staff_{safe_staff_name}.json")

        cache_data = {"rules_hash": "", "threads": {}}
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
            except: pass

        if cache_data.get("rules_hash") != current_rules_hash:
            print("  -> 🔄 ルール更新を検知。解析キャッシュをリフレッシュします。")
            cache_data["threads"] = {}
            cache_data["rules_hash"] = current_rules_hash

        needs_update = {}
        for cid, t in threads.items():
            mail_count = len(t['mails'])
            cached = cache_data["threads"].get(cid)
            if not cached or cached.get("mail_count") != mail_count or cached.get("data", {}).get("_error"):
                needs_update[cid] = t

        if needs_update:
            msg = f"⚙️ Stage 1: {len(needs_update)}件の新規/更新スレッドを抽出中..."
            print(f"  -> {msg}")
            if progress_callback: progress_callback(msg)

            thread_schema = {
                "type": "OBJECT", "properties": {
                    "thread_id": {"type": "STRING"}, "topic": {"type": "STRING"}, "is_target": {"type": "BOOLEAN"},
                    "summary": {"type": "STRING"}, "category": {"type": "STRING"}, "project_scope": {"type": "STRING", "enum": allowed_scopes},
                    "action_type": {"type": "STRING"}, "importance": {"type": "STRING"}, "reasoning": {"type": "STRING"},
                    "actions": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
                        "owner": {"type": "STRING"}, "action": {"type": "STRING"}, "deadline": {"type": "STRING"}, "status": {"type": "STRING"}
                    }}}
                }, "required": ["thread_id", "topic", "is_target", "summary", "category", "project_scope", "action_type"]
            }

            done_count = 0
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = {}
                for cid, t in needs_update.items():
                    mail_texts = []
                    for m in t['mails']:
                        body = self._clean(self._clean_body_for_ai(m['body']))
                        mail_texts.append(f"【送信者:{m['sender_name']}】\n本文:{body}\n")
                    content = "".join(mail_texts)[:30000]
                    
                    prompt = f"""
                    スタッフ「{staff_name}」の以下のメールスレッドを日本語で分析し、指定されたJSON形式で出力せよ。
                    
                    【厳守事項】
                    - 引用タグ(source/cite)は絶対に出力しないこと。
                    - category は必ず [プロジェクト管理, 定常業務, 障害・トラブル, 技術サポート, 運用・保守, 組織・チーム, 購買・調達, 法務・監査, その他] のいずれかを指定。
                    - action_type は必ず [通知・共有, 承認・決裁, 作業・依頼, 相談・質問, その他] のいずれかを指定。
                    - project_scope は必ず [{proj_list_str}, 横断業務, その他] のいずれかを指定すること。リストにない独自の名称は絶対に出力しないこと。
                    - thread_id は理由を問わず "{cid}" という文字列を必ず出力すること。

                    ルール: {ai_rules_text}
                    内容: {content}
                    """
                    # Stage 1: gemini-2.5-flash-lite で高速分類・要約を実施し、Stage 2で標準モデルが統合する
                    futures[executor.submit(self._run_genai_call_with_schema, prompt, thread_schema, "gemini-2.5-flash-lite")] = (cid, len(t['mails']), t['topic'])

                for future in as_completed(futures):
                    cid, m_count, t_topic = futures[future]
                    res = future.result()
                    done_count += 1
                    if progress_callback: progress_callback(f"⚙️ Stage 1: 解析中 ({done_count}/{len(needs_update)})...")
                    
                    if res and not res.get('_error'):
                        res['thread_id'] = cid
                        cache_data["threads"][cid] = {"mail_count": m_count, "latest_entry_id": needs_update[cid].get('latest_entry_id', ''), "data": res}
                    else:
                        cache_data["threads"][cid] = {
                            "mail_count": m_count,
                            "latest_entry_id": needs_update[cid].get('latest_entry_id', ''),
                            "data": {"thread_id": cid, "topic": t_topic, "is_target": False, "summary": f"(解析失敗: {res.get('summary', '接続エラー')})", "category": "エラー", "_error": True}
                        }

            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2, ensure_ascii=False)

            if progress_callback: progress_callback(f"✅ Stage 1完了: {staff_name} ({len(needs_update)}件更新)")

        target_for_s2 = []
        for cid, t in threads.items():
            cached = cache_data["threads"].get(cid)
            if cached and cached.get("data"):
                merged_result["threads"].append(cached["data"])
                if cached["data"].get("is_target", True) and not cached["data"].get("_error"):
                    imp = cached['data'].get('importance', '中')
                    imp_val = 0 if imp == '高' else 2 if imp == '低' else 1
                    dt = t.get('latest_date')
                    ts = int(dt.timestamp()) if dt else 0
                    text = f"[ID: {cid}] 【トピック: {cached['data'].get('topic')}】 重要度: {imp}\n要約: {cached['data'].get('summary')}"
                    target_for_s2.append((imp_val, -ts, text))

        target_for_s2.sort(key=lambda x: (x[0], x[1]))
        active_summaries = [x[2] for x in target_for_s2[:15]]

        if not active_summaries:
            merged_result["staff_status"].append({"category": "その他", "project_scope": "横断業務", "action_type": "通知・共有", "text": "解析対象期間中に有効な活動記録が見つかりませんでした。", "status_icon": "⚪"})
            return merged_result

        shared_item_schema = {
            "type": "OBJECT", "properties": {
                "category": {"type": "STRING"}, "project_scope": {"type": "STRING", "enum": allowed_scopes},
                "action_type": {"type": "STRING"}, "text": {"type": "STRING"}, "status_icon": {"type": "STRING"},
                "source_thread_ids": {"type": "ARRAY", "items": {"type": "STRING"}}
            }, "required": ["category", "project_scope", "action_type", "text"]
        }
        stage2_schema = {
            "type": "OBJECT", "properties": {
                "manager_actions": {"type": "ARRAY", "items": shared_item_schema, "minItems": 1, "maxItems": 3},
                "staff_status": {"type": "ARRAY", "items": shared_item_schema, "minItems": 1, "maxItems": 3},
                "stalled_monitor": {"type": "ARRAY", "items": shared_item_schema, "minItems": 1, "maxItems": 3},
                "updated_history": {"type": "STRING"}, "ai_questions": {"type": "ARRAY", "items": {"type": "STRING"}}
            }, "required": ["manager_actions", "staff_status", "stalled_monitor", "updated_history"]
        }

        s2_content = "\n\n".join(active_summaries)[:30000]
        
        s2_prompt = f"""
        スタッフ「{staff_name}」の以下の【個別活動要約群】を統合し、全体像をマネージャー視点で分析し、日本語のJSONで回答せよ。
        
        【出力JSONのルートキー（3層構造）】
        - manager_actions: あなた(上司)の介入・承認・決裁が必要な事項、または致命的なブロッカー
        - staff_status: スタッフの今週の主要な実績、および次週予定しているアクション
        - stalled_monitor: 文脈から判断して、ボールを持ったまま返信が止まっている（停滞している）案件

        【厳守ルール】
        1. status_icon は「🔴、🔵、🟡、🟢」などの1文字の絵文字のみを出力すること。
        2. text は必ず【1文のみ】で簡潔にまとめ、100文字以内に収めること。
        3. text の先頭に独自の分類タグを絶対に付けないこと。
        4. category フィールドには「manager_actions」等のJSONキー名を入れるのではなく、必ず既存の分類リスト [プロジェクト管理, 定常業務, 障害・トラブル, 技術サポート, 運用・保守, 組織・チーム, 購買・調達, 法務・監査, その他] のいずれかを指定すること。
        5. project_scope は必ず [{proj_list_str}, 横断業務, その他] のいずれかとし、勝手に新しいプロジェクト範囲名を捏造しないこと。
        6. 引用タグは絶対に出力しないこと。
        7. 【最重要】各セクション(manager_actions, staff_status, stalled_monitor)の項目数は、最も重要なものを【厳守して1〜3項目のみ】出力すること。絶対に長文をダラダラと出力せず、1文で簡潔にまとめること。
        8. 各文章の根拠となった情報の [ID: xxx] を、source_thread_ids フィールドに配列形式で必ず含めること。複数ある場合は複数、特定できない場合は空配列とせよ。

        役割: {role} / 背景: {bg} / 経緯: {master_hist}
        内容: {s2_content}
        """
        
        s2_res = self._run_genai_call_with_schema(s2_prompt, stage2_schema)

        if s2_res and not s2_res.get('_error'):
            merged_result["manager_actions"] = ensure_struct(s2_res.get("manager_actions", []))
            merged_result["staff_status"] = ensure_struct(s2_res.get("staff_status", []))
            merged_result["stalled_monitor"] = ensure_struct(s2_res.get("stalled_monitor", []))
            merged_result["ai_questions"] = s2_res.get("ai_questions", [])
            
            ts = datetime.now().strftime("%Y/%m/%d %H:%M")
            new_hist = s2_res.get("updated_history", "").strip()
            merged_result["updated_history"] = f"**[{ts} スタッフ分析]**\n{new_hist}\n\n{recent_hist[:3000]}" if new_hist else recent_hist
            print("  -> ✅ Stage 2 成功")
        else:
            print("  -> ❌ Stage 2 失敗")
            merged_result["manager_actions"].append({"category": "システム", "project_scope": "エラー", "action_type": "警告", "text": "全体サマリの統合に失敗しました。個別スレッド詳細は下部で確認可能です。", "status_icon": "⚠️"})

        return merged_result


    def summarize_action_dashboard(self, threads: dict, progress_callback=None, reset_conversation_ids: set = None) -> dict:
        """
        アクションダッシュボード用: 期間×自分宛て全体のスレッドを横断解析し、
        フラットな「誰が・何を・いつまでに」のアクション項目一覧を生成する。
        summarize_project_threads の Stage1（スレッド単位抽出）相当のみを、
        特定プロジェクトの知識に依存しない軽量版として実行する。
        """
        import os, json as _json
        from concurrent.futures import ThreadPoolExecutor, as_completed

        if not threads:
            return {"threads": [], "action_cards": []}

        cache_dir = "analysis_cache"
        os.makedirs(cache_dir, exist_ok=True)
        cache_file = os.path.join(cache_dir, "action_dashboard.json")

        cache_data = {"threads": {}}
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cache_data = _json.load(f)
            except: pass

        needs_update = {}
        for cid, t in threads.items():
            mail_count = len(t['mails'])
            cached = cache_data["threads"].get(cid)
            if not cached or cached.get("mail_count") != mail_count or cached.get("data", {}).get("_error"):
                needs_update[cid] = t

        if needs_update:
            msg = f"⚙️ アクション抽出中: {len(needs_update)}件の新規/更新スレッド..."
            print(f"  -> {msg}")
            if progress_callback: progress_callback(0, len(needs_update), msg)

            thread_schema = {
                "type": "OBJECT", "properties": {
                    "thread_id": {"type": "STRING"}, "topic": {"type": "STRING"},
                    "summary": {"type": "STRING"}, "category": {"type": "STRING"},
                    "action_type": {"type": "STRING"}, "importance": {"type": "STRING"}, "reasoning": {"type": "STRING"},
                    "actions": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
                        "owner": {"type": "STRING"}, "target": {"type": "STRING"},
                        "action": {"type": "STRING"}, "deadline": {"type": "STRING"}, "status": {"type": "STRING"},
                        "waiting_people": {"type": "ARRAY", "items": {"type": "STRING"}},
                        "reminder_count": {"type": "INTEGER"}
                    }}}
                }, "required": ["thread_id", "topic", "summary", "category", "action_type"]
            }

            done_count = 0
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = {}
                for cid, t in needs_update.items():
                    mail_texts = []
                    for m in t['mails']:
                        body = self._clean(self._clean_body_for_ai(m['body']))
                        mail_texts.append(f"【送信者:{m['sender_name']}】\n本文:{body}\n")
                    content = "".join(mail_texts)[:30000]

                    prompt = f"""
                    以下のメールスレッドを日本語で分析し、指定されたJSON形式で出力せよ。
                    最重要目的は、あなた（メール受信者本人）が「誰から・何を・いつまでに」求められているかを
                    actions 配列に構造化して抽出することである。

                    【厳守事項】
                    - actions配列には、このスレッドの中で「誰かが誰かに対応を求めている」項目がある場合のみ、
                      owner(依頼者名)・target(依頼の宛先。メール受信者本人が宛先なら"あなた"、スレッド内の
                      別の人物が宛先ならその人物名)・action(依頼内容、簡潔に)・deadline(明記があれば、
                      なければ空文字)・status(現時点の状況を一言で)を入れること。対応不要な通知・共有のみの
                      スレッドはactionsを空配列にしてよい。
                    - waiting_people には、このactionの対応(target側の返信・作業)を実質的に待っている人物名を
                      配列で入れること(owner本人に加え、スレッド内でCc等により関係し待っている人物も含めてよい)。
                      判別できなければ owner のみを1件入れる。
                    - reminder_count には、このactionに関して「催促・リマインド・再送・至急・急ぎ」等の
                      催促表現がスレッド内に出現した回数の目安を整数で入れること(無ければ0)。
                    - category は必ず [プロジェクト管理, 定常業務, 障害・トラブル, 技術サポート, 運用・保守, 組織・チーム, 購買・調達, 法務・監査, その他] のいずれかを指定。
                    - action_type は必ず [通知・共有, 承認・決裁, 作業・依頼, 相談・質問, その他] のいずれかを指定。
                    - importance は必ず [高, 中, 低] のいずれかを指定。
                    - 引用タグ(source/cite)は絶対に出力しないこと。
                    - thread_id は理由を問わず "{cid}" という文字列を必ず出力すること。

                    内容: {content}
                    """
                    futures[executor.submit(self._run_genai_call_with_schema, prompt, thread_schema)] = (cid, len(t['mails']), t['topic'])

                for future in as_completed(futures):
                    cid, m_count, t_topic = futures[future]
                    res = future.result()
                    done_count += 1
                    if progress_callback: progress_callback(done_count, len(needs_update), f"⚙️ アクション抽出中 ({done_count}/{len(needs_update)})...")

                    if res and not res.get('_error'):
                        res['thread_id'] = cid
                        cache_data["threads"][cid] = {"mail_count": m_count, "latest_entry_id": needs_update[cid].get('latest_entry_id', ''), "data": res}
                    else:
                        cache_data["threads"][cid] = {
                            "mail_count": m_count,
                            "latest_entry_id": needs_update[cid].get('latest_entry_id', ''),
                            "data": {"thread_id": cid, "topic": t_topic, "summary": f"(解析失敗: {res.get('summary', '接続エラー')})", "category": "エラー", "actions": [], "_error": True}
                        }

            with open(cache_file, 'w', encoding='utf-8') as f:
                _json.dump(cache_data, f, ensure_ascii=False, indent=2)

        # 期間内スレッドのキャッシュ済みデータを集約し、スレッド単位のカード一覧を作る
        # (1スレッドに複数アクションがある場合は1カードにまとめる)
        result_threads = []
        action_cards = []
        action_statuses = load_action_status()
        statuses_migrated = False

        # Outlook再起動検知に伴い強制未読化されたスレッドについては、以前保存された
        # 進捗(完了/無視等)をリセットし、ダッシュボードの既定フィルタで再表示されるようにする。
        # 優先度・コメントは変更しない。チェックボックスOFF時はreset_conversation_idsが空集合のため、
        # 従来通り何も変更されない。
        reset_conversation_ids = reset_conversation_ids or set()
        if reset_conversation_ids:
            with action_status_lock:
                action_statuses = load_action_status()  # 直前のHTTPサーバ側更新を取り込むため再読込
                reset_changed = False
                for reset_cid in reset_conversation_ids:
                    cached_thread = cache_data["threads"].get(reset_cid)
                    if not cached_thread or not cached_thread.get("data"):
                        continue
                    n_actions = len(cached_thread["data"].get("actions", []))
                    for idx in range(n_actions):
                        akey = make_action_key_by_index(reset_cid, idx)
                        if akey in action_statuses:
                            action_statuses[akey]["progress"] = "not_started"
                            action_statuses[akey]["updated_at"] = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
                            reset_changed = True
                if reset_changed:
                    save_action_status(action_statuses)

        for cid, t in threads.items():
            cached = cache_data["threads"].get(cid)
            if not cached or not cached.get("data"): continue
            data = cached["data"]
            if data.get("_error"): continue
            result_threads.append(data)

            thread_actions = []
            for idx, a in enumerate(data.get("actions", [])):
                if not (a.get("action") or "").strip(): continue
                action_key = make_action_key_by_index(cid, idx)
                user_state = action_statuses.get(action_key)
                if user_state is None:
                    # 旧キー方式(文言ベース)で保存されていたステータスがあれば引き継ぐ。
                    # AIの再解析でowner/actionの言い回しが変わってもステータスが消えないようにするための救済。
                    legacy_key = make_action_key(cid, a.get("owner", ""), a.get("action", ""))
                    legacy_state = action_statuses.get(legacy_key)
                    if legacy_state is not None:
                        user_state = legacy_state
                        action_statuses[action_key] = legacy_state
                        statuses_migrated = True
                if user_state is None:
                    user_state = {}
                thread_actions.append({
                    "action_key": action_key,
                    "owner": a.get("owner", ""),
                    "target": a.get("target", ""),
                    "action": a.get("action", ""),
                    "deadline": a.get("deadline", ""),
                    "ai_status": a.get("status", ""),
                    "progress": user_state.get("progress", "not_started"),
                    "priority": user_state.get("priority", ""),
                    "comment": user_state.get("comment", ""),
                    "waiting_people": a.get("waiting_people") or ([a.get("owner")] if a.get("owner") else []),
                    "reminder_count": int(a.get("reminder_count") or 0)
                })

            if not thread_actions:
                continue

            latest_date = t.get('latest_date')
            # スレッド内のいずれかのメールに "R19Proj" カテゴリタグが付与されていれば、
            # そのスレッドをR19プロジェクト案件として扱う。
            is_r19 = any("R19Proj" in c for c in t.get("all_categories", set()))
            # スレッド内のいずれかのメールにOutlookのフラグがアクティブ設定(FlagStatus==2)されていれば
            # フラグ付きスレッドとして扱う。完了済みフラグ(FlagStatus==1)は対象外(group_by_threadのis_flaggedを踏襲)。
            is_flagged = bool(t.get("is_flagged", False))
            action_cards.append({
                "conversation_id": cid,
                "topic": data.get("topic") or t.get("topic", ""),
                "real_topic": t.get("topic", ""),
                "importance": data.get("importance", "中"),
                "category": data.get("category", "その他"),
                "latest_entry_id": t.get("latest_entry_id", ""),
                "latest_date_str": latest_date.strftime("%Y-%m-%d %H:%M") if latest_date else "",
                "latest_date_mmdd": latest_date.strftime("%m/%d %H:%M") if latest_date else "",
                "latest_ts": int(latest_date.timestamp()) if latest_date else 0,
                "has_unread": bool(t.get("has_unread", False)),
                "is_r19": is_r19,
                "is_flagged": is_flagged,
                "actions": thread_actions
            })

        if statuses_migrated:
            save_action_status(action_statuses)

        return {"threads": result_threads, "action_cards": action_cards}

    def generate_cockpit_v2_data(self, project_threads: dict, project_knowledge: dict,
                                  user_smtp_address: str, progress_callback=None) -> dict:
        """統括コックピットv2(新コンセプト)のデータを生成する。
        project_threads: {project_name: threads_dict} 形式。threads_dictはgroup_by_threadの戻り値
        (呼び出し元がOutlookMailManager.get_project_mails(..., include_sent=True)で取得した
        メールをgroup_by_threadでまとめたもの。送信済みメールを含めることで「自分が返信済みか」
        を判定できるようにしている)。
        「自分待ち(ボールが自分のコートにある)」の判定は、各スレッドの最新メールの送信者が
        user_smtp_address と一致しないことで行う(=最後に動いたのが自分でない=自分が未返信)。
        アクション抽出自体は既存の summarize_action_dashboard をそのまま再利用する
        (AIキャッシュはmail_count単位のキーのため、期間ベースでもプロジェクトベースでも
        同じキャッシュの仕組みが機能する)。
        """
        now = datetime.now()
        projects_out = {}
        queue_items = []
        priority_rank = {"★★": 2, "★": 1, "": 0}

        project_list = list(project_threads.keys())
        for i, proj in enumerate(project_list):
            threads = project_threads.get(proj) or {}
            if progress_callback:
                progress_callback(i, len(project_list), f"🎯 {proj} を集計中...")

            proj_priority = (project_knowledge.get("projects", {}).get(proj, {}) or {}).get("priority", "中")

            # 生体信号: プロジェクト全体のメール日時から勢い・相対沈黙を機械的に計算(AI不要)
            all_dates = sorted(
                m['received'] for t in threads.values() for m in t.get('mails', []) if m.get('received')
            )
            velocity = compute_mail_velocity(all_dates, now)
            silence = compute_relative_silence(all_dates, now)

            res = self.summarize_action_dashboard(threads, progress_callback=None)
            action_cards = res.get("action_cards", [])

            waiting_on_me_count = 0
            for card in action_cards:
                cid = card["conversation_id"]
                t = threads.get(cid)
                if not t or not t.get('mails'):
                    continue
                last_sender = (t['mails'][-1].get('sender_email') or '').lower()
                awaiting_my_reply = last_sender != (user_smtp_address or '').lower()
                if not awaiting_my_reply:
                    continue

                open_actions = [a for a in card.get("actions", []) if a.get("progress") not in ("done", "ignored")]
                if not open_actions:
                    continue
                waiting_on_me_count += 1

                latest_date = t.get('latest_date') or now
                days_elapsed = max((now - latest_date).total_seconds() / 86400, 0)

                waiting_people = set()
                reminder_count = 0
                best_priority = ""
                has_deadline = False
                for a in open_actions:
                    for p in (a.get("waiting_people") or []):
                        if p: waiting_people.add(p)
                    reminder_count = max(reminder_count, int(a.get("reminder_count") or 0))
                    p_val = a.get("priority") or ""
                    if priority_rank.get(p_val, 0) > priority_rank.get(best_priority, 0):
                        best_priority = p_val
                    if (a.get("deadline") or "").strip():
                        has_deadline = True

                score_kwargs = dict(
                    waiting_people_count=len(waiting_people) or 1,
                    days_elapsed=days_elapsed,
                    reminder_count=reminder_count,
                    manual_priority=best_priority,
                    project_priority=proj_priority,
                    is_flagged=bool(card.get("is_flagged")),
                    has_deadline=has_deadline
                )
                queue_items.append({
                    "project": proj,
                    "conversation_id": cid,
                    "topic": card.get("topic", ""),
                    # Outlook側の件名検索(show_thread_in_explorer/開くリンク)に使うため、
                    # AI要約タイトルではなく実際のメール件名(real_topic)を別途保持する。
                    # AI要約タイトルで検索するとOutlookの件名と一致せずヒットしないため
                    # (generate_action_dashboard_reportの既存対応と同じ理由)。
                    "real_topic": card.get("real_topic") or card.get("topic", ""),
                    "latest_entry_id": card.get("latest_entry_id", ""),
                    "score": compute_release_score(**score_kwargs),
                    "reasons": release_score_reasons(**score_kwargs),
                    "action_count": len(open_actions),
                    "is_flagged": bool(card.get("is_flagged")),
                    # このカードに含まれる未完了アクションのキー一覧。コックピットv2の
                    # 「✅完了」「🙈無視」ボタンから、Actionタブと同じ/update_action_statusを
                    # 一括で叩いてカードを閉じられるようにするために保持する。
                    "action_keys": [a["action_key"] for a in open_actions],
                })

            projects_out[proj] = {
                "priority": proj_priority,
                "velocity": velocity,
                "silence": silence,
                "waiting_on_me_count": waiting_on_me_count,
                "thread_count": len(threads),
            }

        queue_items.sort(key=lambda x: x["score"], reverse=True)
        return {
            "generated_at": now.strftime("%Y-%m-%d %H:%M"),
            "projects": projects_out,
            "queue": queue_items,
        }

    def generate_cockpit_summary(self, progress_callback=None) -> dict:
        """
        統括コックピット用データ生成 (V20260507.03: 補完文途中切れ防止・セクション単位補完パッチ)
        Stage1キャッシュを収集し、site_manager_view / pm_manager_view / te_pe_view の各Viewへ
        候補を割り当てたうえで、各View合計1件以上・最大9件（赤青黄各3件目安）を満たすように統合する。
        """
        import os, json, re
        from collections import defaultdict

        if progress_callback: progress_callback("🔍 キャッシュからStage 1データを収集中...")
        cache_dir = "analysis_cache"
        all_summaries = []

        role_keys = ["site_manager_view", "r19_pm_view", "pm_manager_view", "te_pe_view"]
        section_keys = ["red_alerts", "blue_highlights", "yellow_stalled"]
        max_items_per_section = 3
        max_items_per_view = 9

        def _safe_text(value, default=""):
            if value is None:
                return default
            return str(value).strip()

        def _is_project_file(fname):
            return fname.startswith("project_") and fname.endswith(".json")

        def _is_staff_file(fname):
            return fname.startswith("staff_") and fname.endswith(".json")

        def _target_name_from_file(fname):
            return fname.replace("project_", "").replace("staff_", "").replace(".json", "")

        def _has_any(text, keywords):
            text_l = _safe_text(text).lower()
            return any(k.lower() in text_l for k in keywords)

        def _first_action_status(data):
            actions = data.get("actions", [])
            if isinstance(actions, list):
                for action in actions:
                    if isinstance(action, dict):
                        status = _safe_text(action.get("status"))
                        if status:
                            return status
            return ""

        def _view_hints_for_candidate(fname, target_name, data):
            hints = []
            target_l = target_name.lower()
            combined = " ".join([
                _safe_text(data.get("topic")),
                _safe_text(data.get("summary")),
                _safe_text(data.get("category")),
                _safe_text(data.get("project_scope")),
                _safe_text(data.get("action_type")),
                _safe_text(data.get("reasoning"))
            ])
            if _is_staff_file(fname):
                if target_l in ["kajikawa", "taizo"]:
                    hints.append("site_manager_view")
                if target_l == "nakai":
                    hints.append("pm_manager_view")
                if target_l == "ochi":
                    hints.append("r19_pm_view")
                if target_l in ["saji", "yuto", "najib"]:
                    hints.append("te_pe_view")

            if _is_project_file(fname):
                if "r19" in target_name.lower() or "03_r19" in target_name.lower():
                    hints.append("r19_pm_view")
                else:
                    hints.append("pm_manager_view")

            site_keywords = [
                "承認", "決裁", "費用", "コストセンター", "輸出", "輸入", "tradewin",
                "dhl", "ein", "会社登録番号", "r19", "release", "リリース",
                "保留", "hold", "pir", "admin", "拠点", "サイト", "法務", "監査"
            ]
            tech_keywords = [
                "htol", "hast", "esd", "cdm", "psi", "wat", "wafer", "ウェハ",
                "バンプ", "bump", "jcap", "jcet", "test", "テスト", "socket", "ソケット",
                "board", "ボード", "evm", "pcb", "ccopp", "vout", "qualification", "認定"
            ]
            pm_keywords = [
                "project", "プロジェクト", "進捗", "スケジュール", "po", "見積",
                "月次", "週次", "gate", "ゲート", "出荷", "手配", "review", "レビュー"
            ]
            r19_keywords = [
                "r19", "sustaining", "サステイニング", "サスティニング", "r19proj"
            ]

            if _has_any(combined, site_keywords) and "site_manager_view" not in hints:
                hints.append("site_manager_view")
            if _has_any(combined, tech_keywords) and "te_pe_view" not in hints:
                hints.append("te_pe_view")
            if _has_any(combined, r19_keywords) and "r19_pm_view" not in hints:
                hints.append("r19_pm_view")
            if _has_any(combined, pm_keywords) and "pm_manager_view" not in hints:
                hints.append("pm_manager_view")

            if not hints:
                hints.append("site_manager_view")

            return hints

        def _candidate_score(candidate, view_key):
            data = candidate.get("data", {})
            target_l = candidate.get("target_name", "").lower()
            fname = candidate.get("source_file", "")
            importance = _safe_text(data.get("importance"))
            action_type = _safe_text(data.get("action_type"))
            category = _safe_text(data.get("category"))
            summary = _safe_text(data.get("summary"))
            status = _first_action_status(data)
            score = 0

            if importance in ["高", "High", "high"]:
                score += 50
            elif importance in ["中", "Medium", "medium"]:
                score += 25
            elif importance in ["低", "Low", "low"]:
                score += 5

            if action_type in ["承認・決裁", "相談・質問", "作業・依頼"]:
                score += 20
            if category in ["障害・トラブル", "法務・監査", "購買・調達", "プロジェクト管理", "技術サポート"]:
                score += 10
            if _has_any(status, ["未着手", "未完了", "pending", "open", "保留", "待ち", "進行中"]):
                score += 12
            if len(summary) > 30:
                score += 3

            if view_key == "pm_manager_view":
                if target_l == "nakai":
                    score += 80
                elif _is_project_file(fname):
                    score += 35
            elif view_key == "r19_pm_view":
                if target_l == "ochi":
                    score += 80
                elif _is_project_file(fname) and ("r19" in target_name.lower() or "03_r19" in target_name.lower()):
                    score += 60
                elif _is_project_file(fname):
                    score += 15
            elif view_key == "te_pe_view":
                if target_l in ["saji", "yuto", "najib"]:
                    score += 70
                elif _is_project_file(fname):
                    score += 20
            elif view_key == "site_manager_view":
                if target_l in ["kajikawa", "taizo"]:
                    score += 70
                elif _is_project_file(fname):
                    score += 10

            return score

        def _section_for_candidate(candidate):
            data = candidate.get("data", {})
            importance = _safe_text(data.get("importance"))
            action_type = _safe_text(data.get("action_type"))
            status = _first_action_status(data)
            combined = " ".join([
                _safe_text(data.get("topic")),
                _safe_text(data.get("summary")),
                _safe_text(data.get("reasoning")),
                status
            ])

            if importance in ["高", "High", "high"] or action_type in ["承認・決裁", "相談・質問"]:
                return "red_alerts"

            if _has_any(combined, ["未着手", "未完了", "pending", "open", "保留", "待ち", "進行中", "遅延", "停止"]):
                return "yellow_stalled"

            if action_type in ["通知・共有"] or _has_any(combined, ["完了", "承認済", "共有", "報告", "順調"]):
                return "blue_highlights"

            return "yellow_stalled"

        def _complete_sentence_text(value, soft_limit=220):
            text = re.sub(r"\s+", " ", _safe_text(value)).strip()
            if not text:
                return ""
            if len(text) <= soft_limit:
                return text

            sentence_end_marks = ["。", "．", ".", "！", "!", "？", "?"]
            cut_positions = [text.rfind(mark, 0, soft_limit + 1) for mark in sentence_end_marks]
            cut_pos = max(cut_positions)
            if cut_pos >= 60:
                return text[:cut_pos + 1].strip()

            return text

        def _candidate_to_role_item(candidate, auto_filled=False):
            data = candidate.get("data", {})
            category = _safe_text(data.get("category"), "状況把握") or "状況把握"
            topic = _safe_text(data.get("topic"), "件名なし")
            summary = _safe_text(data.get("summary"), "")
            text_source = summary if summary else topic
            text = _complete_sentence_text(text_source, soft_limit=220)
            if not text:
                text = _complete_sentence_text(topic, soft_limit=220)
            return {
                "category": category,
                "text": text,
                "source_thread_ids": [candidate["id"]],
                "duplicate_thread": False,
                "auto_filled": bool(auto_filled)
            }

        if os.path.exists(cache_dir):
            for fname in os.listdir(cache_dir):
                if fname.endswith(".json"):
                    try:
                        with open(os.path.join(cache_dir, fname), 'r', encoding='utf-8') as f:
                            cdata = json.load(f)
                            target_name = _target_name_from_file(fname)
                            for cid, tinfo in cdata.get("threads", {}).items():
                                data = tinfo.get("data", {})
                                if data and not data.get("_error") and data.get("is_target"):
                                    view_hints = _view_hints_for_candidate(fname, target_name, data)
                                    text = (
                                        f"[ID: {cid}] "
                                        f"[TARGET: {target_name}] "
                                        f"[SOURCE: {fname}] "
                                        f"[VIEW_HINT: {', '.join(view_hints)}] "
                                        f"【{data.get('category')} / {data.get('project_scope')} / {data.get('action_type')}】 "
                                        f"{data.get('topic')}\n"
                                        f"重要度: {data.get('importance', '未指定')}\n"
                                        f"要約: {data.get('summary')}"
                                    )
                                    all_summaries.append({
                                        "id": cid,
                                        "text": text,
                                        "source_file": fname,
                                        "target_name": target_name,
                                        "view_hints": view_hints,
                                        "data": data,
                                        "latest_entry_id": tinfo.get("latest_entry_id", "")
                                    })
                                    
                    except: pass

        if not all_summaries:
            return self._error("解析済みデータがありません。先にプロジェクトまたはスタッフの解析を実行してください。")

        if progress_callback: progress_callback(f"⚙️ View別候補を整理中: 全{len(all_summaries)}件...")

        candidates_by_view = {key: [] for key in role_keys}
        for candidate in all_summaries:
            for view_key in candidate.get("view_hints", []):
                if view_key in candidates_by_view:
                    candidates_by_view[view_key].append(candidate)

        for view_key in role_keys:
            candidates_by_view[view_key] = sorted(
                candidates_by_view[view_key],
                key=lambda c: _candidate_score(c, view_key),
                reverse=True
            )

        print("[DEBUG] all_summaries:", len(all_summaries))
        print("[DEBUG] site candidates:", len(candidates_by_view["site_manager_view"]))
        print("[DEBUG] r19 candidates:", len(candidates_by_view["r19_pm_view"]))
        print("[DEBUG] pm candidates:", len(candidates_by_view["pm_manager_view"]))
        print("[DEBUG] te candidates:", len(candidates_by_view["te_pe_view"]))
        print("[DEBUG] r19 top:", [(c.get("target_name"), c.get("source_file"), c.get("id")) for c in candidates_by_view["r19_pm_view"][:5]])
        print("[DEBUG] pm top:", [(c.get("target_name"), c.get("source_file"), c.get("id")) for c in candidates_by_view["pm_manager_view"][:5]])
        print("[DEBUG] te top:", [(c.get("target_name"), c.get("source_file"), c.get("id")) for c in candidates_by_view["te_pe_view"][:5]])

        r19_primary = [c for c in candidates_by_view["r19_pm_view"] if c.get("target_name", "").lower() == "ochi"]
        r19_project = [c for c in candidates_by_view["r19_pm_view"] if _is_project_file(c.get("source_file", "")) and ("r19" in c.get("target_name", "").lower() or "03_r19" in c.get("target_name", "").lower())]
        r19_other = [c for c in candidates_by_view["r19_pm_view"] if c not in r19_primary and c not in r19_project]
        candidates_by_view["r19_pm_view"] = r19_primary + r19_project + r19_other

        pm_primary = [c for c in candidates_by_view["pm_manager_view"] if c.get("target_name", "").lower() == "nakai"]
        pm_project = [c for c in candidates_by_view["pm_manager_view"] if _is_project_file(c.get("source_file", ""))]
        pm_other = [c for c in candidates_by_view["pm_manager_view"] if c not in pm_primary and c not in pm_project]
        candidates_by_view["pm_manager_view"] = pm_primary + pm_project + pm_other

        te_primary = [c for c in candidates_by_view["te_pe_view"] if c.get("target_name", "").lower() in ["saji", "yuto", "najib"]]
        te_project = [c for c in candidates_by_view["te_pe_view"] if _is_project_file(c.get("source_file", ""))]
        te_other = [c for c in candidates_by_view["te_pe_view"] if c not in te_primary and c not in te_project]
        candidates_by_view["te_pe_view"] = te_primary + te_project + te_other

        box_candidate_limit = 6
        boxed_candidates = {
            role_key: {section_key: [] for section_key in section_keys}
            for role_key in role_keys
        }

        for role_key in role_keys:
            used_in_role_section = {section_key: set() for section_key in section_keys}
            for candidate in candidates_by_view.get(role_key, []):
                section_key = _section_for_candidate(candidate)
                if section_key not in section_keys:
                    continue

                input_key = (candidate.get("id"), candidate.get("source_file"))
                if input_key in used_in_role_section[section_key]:
                    continue
                if len(boxed_candidates[role_key][section_key]) >= box_candidate_limit:
                    continue

                boxed_candidates[role_key][section_key].append(candidate)
                used_in_role_section[section_key].add(input_key)

        print("[DEBUG] boxed candidate counts:")
        for role_key in role_keys:
            for section_key in section_keys:
                print("[DEBUG BOX]", role_key, section_key, len(boxed_candidates[role_key][section_key]))

        def _build_boxed_final_content():
            blocks = []
            for role_key in role_keys:
                for section_key in section_keys:
                    candidates = boxed_candidates.get(role_key, {}).get(section_key, [])
                    header = f"【{role_key} / {section_key} 候補】候補数: {len(candidates)}件"
                    if not candidates:
                        blocks.append(header + "\n(候補なし)")
                        continue

                    lines = [header]
                    for idx, candidate in enumerate(candidates, start=1):
                        lines.append(
                            f"\n--- 候補 {idx} ---\n"
                            f"[BOX: {role_key} / {section_key}]\n"
                            f"{candidate.get('text', '')}"
                        )
                    blocks.append("\n".join(lines))
            return "\n\n".join(blocks)

        # ── 案A: BOOLEANフィールドを削除してスキーマ状態数を削減 ──────────────────
        # duplicate_thread / auto_filled はPython側で後処理するためスキーマ不要
        role_item_schema = {
            "type": "OBJECT",
            "properties": {
                "category": {"type": "STRING"},
                "text": {"type": "STRING"},
                "source_thread_ids": {"type": "ARRAY", "items": {"type": "STRING"}}
            },
            "required": ["category", "text", "source_thread_ids"]
        }

        # View単位スキーマ（案C: 1View分のみ包む）
        single_view_sections_schema = {
            "type": "OBJECT",
            "properties": {
                "red_alerts":      {"type": "ARRAY", "items": role_item_schema, "maxItems": 3},
                "blue_highlights": {"type": "ARRAY", "items": role_item_schema, "maxItems": 3},
                "yellow_stalled":  {"type": "ARRAY", "items": role_item_schema, "maxItems": 3}
            },
            "required": ["red_alerts", "blue_highlights", "yellow_stalled"]
        }

        # ── 案C: View単位コンテンツ・プロンプトビルダー ───────────────────────────
        def _build_single_view_content(view_key):
            blocks = []
            for section_key in section_keys:
                candidates = boxed_candidates.get(view_key, {}).get(section_key, [])
                header = f"【{view_key} / {section_key} 候補】候補数: {len(candidates)}件"
                if not candidates:
                    blocks.append(header + "\n(候補なし)")
                    continue
                lines_inner = [header]
                for idx, candidate in enumerate(candidates, start=1):
                    lines_inner.append(
                        f"\n--- 候補 {idx} ---\n"
                        f"[BOX: {view_key} / {section_key}]\n"
                        f"{candidate.get('text', '')}"
                    )
                blocks.append("\n".join(lines_inner))
            return "\n\n".join(blocks)

        _view_hints_map = {
            "site_manager_view": "TARGET: Kajikawa / Taizo、および承認・輸出入・費用・R19・拠点運営を優先してください。",
            "r19_pm_view":       "TARGET: Ochi を最優先し、不足する場合は project_03_r19*.json または R19/Sustaining関連の project_*.json も使ってください。",
            "pm_manager_view":   "TARGET: Nakai を最優先し、不足する場合は project_*.json も使ってください。",
            "te_pe_view":        "TARGET: Saji / Yuto / Najib を優先し、不足する場合は技術・試験・HTOL・PSI・ウェハー・CCOPP系の project_*.json も使ってください。",
        }

        def _build_single_view_prompt(view_key, view_content):
            hint = _view_hints_map.get(view_key, "")
            return (
                f"以下の候補を分析し、{view_key} 用のExecutive Cockpit JSONを生成してください。\n\n"
                f"【対象View】{view_key}\n"
                f"【優先方針】{hint}\n\n"
                "【共通方針】\n"
                "- 入力は red_alerts / blue_highlights / yellow_stalled の3箱に分かれています。\n"
                "- 各箱から、候補が存在する場合は最低1件、最大3件を選んでください。\n"
                "- 候補数が0件の箱だけ、空配列 [] を許可します。\n"
                f"- [BOX: {view_key} / section] を最優先で尊重してください。\n"
                "- source_thread_ids には [ID: XXXXX] の XXXXX 部分だけを入れてください。\n"
                "- category は20文字以内、text は100文字以内の日本語にしてください。\n"
                "- 出力は純粋なJSONのみ。Markdownバッククォートや説明文は不要です。\n\n"
                "【色別Sectionの意味】\n"
                "- red_alerts: 即時介入・重大アラート（承認待ち、決裁待ち、顧客影響、量産移行不可、出荷停止）\n"
                "- blue_highlights: 戦略成果・ハイライト（完了、承認済み、次工程へ進める状態、プロジェクト前進）\n"
                "- yellow_stalled: 停滞監視・ボトルネック（未完了、pending、保留、回答待ち、遅延リスク）\n\n"
                "【出力JSON例】\n"
                "{\n"
                "  \"red_alerts\": [{\"source_thread_ids\": [\"AAAAA\"], \"category\": \"承認待ち\", \"text\": \"承認が滞っており早急な判断が必要です。\"}],\n"
                "  \"blue_highlights\": [{\"source_thread_ids\": [\"BBBBB\"], \"category\": \"承認完了\", \"text\": \"承認が完了し次工程へ進める状態です。\"}],\n"
                "  \"yellow_stalled\": [{\"source_thread_ids\": [\"CCCCC\"], \"category\": \"回答待ち\", \"text\": \"関係者からの回答待ちで次アクションが保留されています。\"}]\n"
                "}\n\n"
                f"【候補】\n{view_content}"
            )

        # ── 案C: View単位4回に分割してAPI呼び出し ────────────────────────────────
        if progress_callback: progress_callback("📊 統括コックピット: View別に分割してAI解析中...")
        final_res = {}
        for view_idx, view_key in enumerate(role_keys, start=1):
            if progress_callback: progress_callback(f"📊 コックピット解析 ({view_idx}/{len(role_keys)}): {view_key}...")
            _vc = _build_single_view_content(view_key)
            _vp = _build_single_view_prompt(view_key, _vc)
            _single_schema = {
                "type": "OBJECT",
                "properties": {view_key: single_view_sections_schema},
                "required": [view_key]
            }
            _vr = self._run_genai_call_with_schema(_vp, _single_schema)
            if _vr and not _vr.get("_error") and view_key in _vr:
                final_res[view_key] = _vr[view_key]
                print(f"[DEBUG] ✅ {view_key}: Gemini解析成功")
            else:
                final_res[view_key] = {section_key: [] for section_key in section_keys}
                print(f"[DEBUG] ⚠️ {view_key}: Gemini失敗 -> Pythonフォールバック")
        # 欠損View保護
        for _rk in role_keys:
            if _rk not in final_res:
                final_res[_rk] = {section_key: [] for section_key in section_keys}


        if not final_res or final_res.get("_error"):
            final_res = {role_key: {section_key: [] for section_key in section_keys} for role_key in role_keys}

        if progress_callback: progress_callback("🧩 空View補完と件数制御を実行中...")

        candidate_lookup = defaultdict(list)
        for candidate in all_summaries:
            candidate_lookup[str(candidate["id"]).strip().upper()].append(candidate)

        for role_key in role_keys:
            role_data = final_res.get(role_key, {})
            if not isinstance(role_data, dict):
                role_data = {}
            final_res[role_key] = role_data

            for section_key in section_keys:
                items = role_data.get(section_key, [])
                if not isinstance(items, list):
                    items = []
                normalized_items = []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    raw_tids = item.get("source_thread_ids", [])
                    if not isinstance(raw_tids, list):
                        raw_tids = []
                    found_tids = []
                    for tid in raw_tids:
                        tid_str = str(tid).strip()
                        if tid_str and tid_str.upper() in candidate_lookup and tid_str not in found_tids:
                            found_tids.append(tid_str)
                    item["source_thread_ids"] = found_tids
                    item["category"] = _safe_text(item.get("category"), "状況把握") or "状況把握"
                    item["text"] = _safe_text(item.get("text"), "")
                    item["duplicate_thread"] = False
                    item["auto_filled"] = bool(item.get("auto_filled", False))
                    if item["text"]:
                        normalized_items.append(item)
                role_data[section_key] = normalized_items[:max_items_per_section]

            total_role_items = sum(len(role_data.get(section_key, [])) for section_key in section_keys)
            if total_role_items == 0:
                fallback = None
                for candidate in candidates_by_view.get(role_key, []):
                    if str(candidate["id"]).strip().upper() in candidate_lookup:
                        fallback = candidate
                        break
                if fallback:
                    section_key = _section_for_candidate(fallback)
                    role_data.setdefault(section_key, [])
                    if len(role_data[section_key]) < max_items_per_section:
                        role_data[section_key].append(_candidate_to_role_item(fallback, auto_filled=True))

            role_used_tids = set()
            for section_key in section_keys:
                for item in role_data.get(section_key, []):
                    for tid in item.get("source_thread_ids", []):
                        role_used_tids.add(str(tid).strip().upper())

            for section_key in section_keys:
                role_data.setdefault(section_key, [])
                if len(role_data[section_key]) > 0:
                    continue
                for candidate in candidates_by_view.get(role_key, []):
                    safe_candidate_id = str(candidate.get("id", "")).strip().upper()
                    if not safe_candidate_id or safe_candidate_id in role_used_tids:
                        continue
                    if safe_candidate_id not in candidate_lookup:
                        continue
                    if _section_for_candidate(candidate) != section_key:
                        continue
                    if len(role_data[section_key]) < max_items_per_section:
                        role_data[section_key].append(_candidate_to_role_item(candidate, auto_filled=True))
                        role_used_tids.add(safe_candidate_id)
                    break

            flat_count = 0
            for section_key in section_keys:
                kept = []
                for item in role_data.get(section_key, []):
                    if flat_count >= max_items_per_view:
                        break
                    kept.append(item)
                    flat_count += 1
                role_data[section_key] = kept

        print("[DEBUG] final counts before duplicate check:")
        for role_key in role_keys:
            print(
                "[DEBUG]", role_key,
                "red=", len(final_res.get(role_key, {}).get("red_alerts", [])),
                "blue=", len(final_res.get(role_key, {}).get("blue_highlights", [])),
                "yellow=", len(final_res.get(role_key, {}).get("yellow_stalled", []))
            )
            for section_key in section_keys:
                for item in final_res.get(role_key, {}).get(section_key, []):
                    print(
                        "[DEBUG ITEM]",
                        role_key,
                        section_key,
                        item.get("category"),
                        item.get("auto_filled"),
                        item.get("source_thread_ids"),
                        item.get("text", "")[:50]
                    )

        tid_to_roles = defaultdict(set)
        for role_key in role_keys:
            for section_key in section_keys:
                for item in final_res.get(role_key, {}).get(section_key, []):
                    for tid in item.get("source_thread_ids", []):
                        tid_to_roles[str(tid).strip().upper()].add(role_key)

        duplicate_tids = {tid for tid, roles in tid_to_roles.items() if len(roles) > 1}
        for role_key in role_keys:
            for section_key in section_keys:
                for item in final_res.get(role_key, {}).get(section_key, []):
                    item["duplicate_thread"] = any(str(tid).strip().upper() in duplicate_tids for tid in item.get("source_thread_ids", []))

        if progress_callback: progress_callback("🧬 物理リンクを継承中...")
        final_res["thread_data_map"] = {}
        stored_thread_keys = set()

        for role_key in role_keys:
            for section_key in section_keys:
                for item in final_res.get(role_key, {}).get(section_key, []):
                    found_tids = []
                    for tid in item.get("source_thread_ids", []):
                        tid_str = str(tid).strip()
                        safe_tid = tid_str.upper()
                        if not safe_tid or safe_tid not in candidate_lookup:
                            continue

                        found_tids.append(tid_str)
                        if safe_tid in stored_thread_keys:
                            continue

                        orig_info = candidate_lookup[safe_tid][0]
                        try:
                            fpath = os.path.join(cache_dir, orig_info["source_file"])
                            with open(fpath, 'r', encoding='utf-8') as f:
                                cdata = json.load(f)
                                raw_thread = next((v for k, v in cdata.get("threads", {}).items() if str(k).strip().upper() == safe_tid), None)
                                if raw_thread:
                                    t_key = f"cp_{orig_info['target_name']}_{tid_str}"
                                    final_res["thread_data_map"][t_key] = {
                                        "data": raw_thread.get("data"),
                                        "target_name": orig_info["target_name"],
                                        "latest_entry_id": raw_thread.get("latest_entry_id", "")
                                    }                                    
                                    stored_thread_keys.add(safe_tid)
                        except: pass

                    item["source_thread_ids"] = found_tids

        if progress_callback: progress_callback("✅ コックピット統合完了")
        return final_res

    def _render_cockpit_data(self, data):
        """
        AIから返ってきたJSONをUIに描画する (V37: スタッフ俯瞰機能の完全移植版)
        """
        if data.get("_error"):
            self._render_cockpit_error(data.get("summary", "不明なエラー"))
            return

        def dismiss_item(frame):
            frame.destroy()

        # 1. 統括ダッシュボードの集計と描画
        for child in self.cockpit_dash_row.winfo_children():
            child.destroy()
        
        t_map = data.get("thread_data_map", {})
        if t_map:
            stats = {'cat': {}, 'scp': {}, 'act': {}}
            for t_info in t_map.values():
                d = t_info.get("data", {})
                cat = d.get('category', 'その他'); stats['cat'][cat] = stats['cat'].get(cat, 0) + 1
                scp = d.get('project_scope', '全体'); stats['scp'][scp] = stats['scp'].get(scp, 0) + 1
                act = d.get('action_type', '通知'); stats['act'][act] = stats['act'].get(act, 0) + 1

            # 簡易タグの表示
            for c_name, count in stats['cat'].items():
                tk.Label(self.cockpit_dash_row, text=f"🏷️{c_name}:{count}", bg="#EEF2FF", fg="#4338CA", font=("", 8, "bold"), padx=5).pack(side=tk.LEFT, padx=2)
            for s_name, count in stats['scp'].items():
                tk.Label(self.cockpit_dash_row, text=f"📁{s_name}:{count}", bg="#F0F9FF", fg="#0369A1", font=("", 8, "bold"), padx=5).pack(side=tk.LEFT, padx=2)

        # 2. 各セクションのカード描画
        for key, widget in self.cockpit_widgets.items():
            for child in widget.winfo_children():
                child.destroy()
                
            items = data.get(key, [])
            if not items:
                ttk.Label(widget, text="該当するアラートやタスクはありません。順調です。", foreground="green").pack(pady=5)
                continue

            for item in items:
                # アイテムカードの外枠
                item_frame = tk.Frame(widget, bg="#ffffff", bd=1, relief=tk.SOLID)
                item_frame.pack(fill=tk.X, pady=5, padx=2)
                
                # ヘッダー (タイトル + 閉じる)
                header_f = tk.Frame(item_frame, bg=self.cockpit_sections[key]["color"])
                header_f.pack(fill=tk.X)
                tk.Label(header_f, text=f"■ {item.get('title', '無題')}", font=("", 10, "bold"), bg=self.cockpit_sections[key]["color"]).pack(side=tk.LEFT, padx=5, pady=3)
                tk.Button(header_f, text="✖ 閉じる", relief=tk.FLAT, bg=self.cockpit_sections[key]["color"], fg="gray", cursor="hand2", command=lambda f=item_frame: dismiss_item(f)).pack(side=tk.RIGHT, padx=5)
                
                # メインコンテンツ
                body_f = tk.Frame(item_frame, bg="#ffffff", padx=10, pady=8)
                body_f.pack(fill=tk.X)
                tk.Message(body_f, text=item.get("desc", ""), width=900, bg="#ffffff", fg="#1F2937", font=("", 10)).pack(anchor=tk.W)

                # 3. 物理リンク (スレッド詳細・アコーディオン) の埋め込み
                t_ids = item.get("thread_ids", [])
                for tid in t_ids:
                    # 接頭辞付きIDでマップから生データを検索
                    found_key = next((k for k in t_map if k.endswith(f"_{tid}")), None)
                    if not found_key: continue
                    
                    t_info = t_map[found_key]
                    th_data = t_info["data"]
                    
                    # スレッド拡張エリア (スタッフ俯瞰のデザインを移植)
                    ext_f = tk.Frame(body_f, bg="#F9FAFB", bd=1, relief=tk.GROOVE, padx=8, pady=8)
                    ext_f.pack(fill=tk.X, pady=8)
                    
                    # スレッドタイトルとOutlook直通リンク
                    title_f = tk.Frame(ext_f, bg="#F9FAFB")
                    title_f.pack(fill=tk.X)
                    tk.Label(title_f, text=f"🔗 根拠: {th_data.get('topic')}", font=("", 9, "bold"), bg="#F9FAFB", fg="#374151").pack(side=tk.LEFT)
                    
                    # 物理アドレス (EntryID) で直接開く
                    eid = th_data.get('_entry_id') or ""
                    tk.Button(title_f, text="🚀 Outlook", command=lambda e=eid: self.outlook.open_mail_item(e), bg="#EFF6FF", fg="#1D4ED8", font=("", 8), relief=tk.FLAT).pack(side=tk.RIGHT)
                    
                    # 要約文
                    tk.Label(ext_f, text=th_data.get("summary", ""), wraplength=850, justify=tk.LEFT, bg="#F9FAFB", font=("", 9), fg="#4B5563").pack(fill=tk.X, pady=5)
                    
                    # アクションリスト (存在する場合のみ)
                    actions = th_data.get("actions", [])
                    if actions:
                        act_f = tk.Frame(ext_f, bg="#FFFFFF", bd=1, relief=tk.FLAT)
                        act_f.pack(fill=tk.X, pady=5)
                        for a in actions[:3]: # 上位3件
                            tk.Label(act_f, text=f"✅ {a.get('owner', '担当者')}: {a.get('action', '')}", bg="#FFFFFF", font=("", 8), fg="#059669").pack(anchor=tk.W, padx=5)
            
            
    def _clean(self, text: str) -> str:
        """
        AIに送るテキストから制御文字を除去し、空白を正規化する
        """
        import re
        if not text: return ""
        cleaned = "".join(c for c in text if c.isprintable() or c in "\n\r")
        return re.sub(r'\s+', ' ', cleaned).strip()

    def _clean_body_for_ai(self, text: str, limit: int = 800) -> str:
        """
        メール本文から署名や古い引用をカットし、先頭の重要部分のみを抽出する
        """
        if not text: return ""
        lines = text.splitlines()
        keep_lines = []
        delimiters = ["-----original message-----", "from:", "___", "sent:", "送信日時:", "subject:"]
        
        for line in lines:
            l_lower = line.lower().strip()
            if any(d in l_lower for d in delimiters) or l_lower.startswith(">"):
                break
            keep_lines.append(line)
        
        return "\n".join(keep_lines).strip()[:limit]


    def _extract_json(self, text: str) -> dict:
        """
        AIの回答からJSON部分のみを抽出しパースする (V36: トークン切れ自動補完機能付き)
        """
        import re
        import json
        if not text: return None
        
        # 引用タグの除去
        text = re.sub(r"\[\s*(source|cite)\s*:\s*\d+\s*\]", "", text, flags=re.IGNORECASE)
        
        start_idx = text.find('{')
        end_idx = text.rfind('}')
        
        if start_idx == -1:
            return None
            
        # 終了括弧が見つからない（途中で切れた）場合、末尾までを対象にする
        if end_idx == -1 or end_idx < start_idx:
            json_fragment = text[start_idx:].strip()
        else:
            json_fragment = text[start_idx:end_idx+1].strip()
        
        try:
            # 基本パース (strict=Falseで生の改行を許容)
            return json.loads(json_fragment, strict=False)
        except:
            # 物理的な中断（トークン切れ）への救済ロジック
            try:
                temp_json = json_fragment
                # 配列の閉じ忘れ補完
                bracket_balance = temp_json.count('[') - temp_json.count(']')
                if bracket_balance > 0:
                    temp_json += ']' * bracket_balance
                
                # オブジェクトの閉じ忘れ補完
                brace_balance = temp_json.count('{') - temp_json.count('}')
                if brace_balance > 0:
                    temp_json += '}' * brace_balance
                
                return json.loads(temp_json, strict=False)
            except:
                return None

    def _error(self, msg: str) -> dict:
        """
        エラー発生時の標準レスポンス構造を生成する
        """
        return {
            "summary": f"エラー: {msg}",
            "_error": True,
            "project_status": [],
            "project_highlights": [{"text": f"解析エラー: {msg}"}],
            "threads": []
        }
 
# ============================================================
# HTMLレポート生成
# ============================================================



class HTMLReportGenerator:
    def __init__(self, output_folder: str, server_port: int):
        self.folder = Path(output_folder)
        self.server_port = server_port


    def _get_status_badge(self, st):
        """ステータス文字列に応じて適切なHTMLバッジを返す（V22整合版）"""
        import html
        s = html.escape(str(st)).lower()
        if any(k in s for k in ["未設定", "漏れ", "未定"]):
            return f'<span style="background:#fee2e2; color:#ef4444; font-weight:bold; font-size:0.85em; padding:2px 6px; border-radius:4px;">{st}</span>'
        elif "完了" in s:
            return f'<span style="background:#dcfce7; color:#16a34a; font-weight:bold; font-size:0.85em; padding:2px 6px; border-radius:4px;">{st}</span>'
        elif "遅延" in s:
            return f'<span style="background:#fef08a; color:#a16207; font-weight:bold; font-size:0.85em; padding:2px 6px; border-radius:4px;">{st}</span>'
        else:
            return f'<span style="background:#f1f5f9; color:#64748b; font-size:0.85em; padding:2px 6px; border-radius:4px;">{st}</span>'


    def generate_report(self, threads, summaries, conds):
        is_rss_only = True
        if not threads:
            is_rss_only = False
        else:
            for t in threads.values():
                if not any(m.get('folder') == 'RSS フィード' for m in t.get('mails', [])):
                    is_rss_only = False
                    break
        
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        target_dir = self.folder
        if is_rss_only:
            sp_dir = Path(r"C:\Users\nx023836\Nexperia\My Private - Documents\Summary")
            if sp_dir.exists(): target_dir = sp_dir
            else:
                import tkinter.messagebox as mb
                try: mb.showwarning("警告", "SharePointフォルダが見つからないため、ローカルフォルダに代替保存しました。")
                except: pass
        
        path = target_dir / f"mail_report_{ts}.html"
        html = self._build_html(threads, summaries, conds)
        with open(path, 'w', encoding='utf-8') as f: f.write(html)
        return str(path)

    def _build_html(self, threads, summaries, conds):
        total_m = sum(t['mail_count'] for t in threads.values())
        high_p = sum(len([a for a in s.get('action_items',[]) if a.get('priority')=='高']) for s in summaries.values())
        cards = [self._card(t, summaries.get(cid, {}), i) for i, (cid, t) in enumerate(threads.items(), 1)]
            
        return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
:root {{ --primary:#2563eb; --high:#f97316; --bg:#f3f4f6; }}
body {{ font-family:'Segoe UI',sans-serif; background:var(--bg); color:#333; margin:0; padding:20px; }}
.container {{ max-width:1200px; margin:0 auto; padding-bottom: 80px; }}
.header {{ background:linear-gradient(135deg,var(--primary),#1d4ed8); color:#fff; padding:20px; border-radius:10px; margin-bottom:20px; scroll-margin-top: 20px; }}
.stat-card {{ background:#fff; padding:15px; border-radius:8px; text-align:center; box-shadow:0 1px 3px rgba(0,0,0,0.1); display:inline-block; width:200px; margin-right:10px; }}
.stat-val {{ font-size:24px; font-weight:bold; color:var(--primary); }}
.thread-card {{ background:#fff; margin-bottom:20px; border-radius:10px; border-top:4px solid var(--primary); box-shadow:0 1px 3px rgba(0,0,0,0.1); overflow:hidden; scroll-margin-top: 20px; transition: border-color 0.3s, box-shadow 0.3s; }}
.active-card {{ border: 2px solid var(--primary); box-shadow: 0 0 10px rgba(37, 99, 235, 0.3); }}
.t-head {{ padding:15px; border-bottom:1px solid #eee; display:flex; justify-content:space-between; }}
.t-title {{ font-weight:bold; font-size:18px; }}
.t-body {{ padding:20px; }}
.section {{ margin-bottom:20px; }}
.sec-title {{ font-weight:bold; border-bottom:2px solid #eee; margin-bottom:10px; color:#555; }}
.sum-box {{ background:#f8fafc; padding:15px; border-radius:6px; }}
.act-item {{ display:flex; gap:10px; padding:10px; background:#f8fafc; border-left:4px solid #ccc; margin-bottom:5px; }}
.act-high {{ border-left-color:var(--high); background:#fff7ed; }}
.mail-item {{ border-left:3px solid #cbd5e1; padding:10px; background:#f8fafc; margin-bottom:10px; }}
.m-head {{ font-weight:bold; margin-bottom:5px; }}
.m-sum {{ background:#fff; padding:5px; border:1px solid #eee; margin-bottom:5px; color:#666; font-size:0.9em; }}
.m-body {{ white-space:pre-wrap; max-height:0; overflow:hidden; transition:0.3s; font-size:0.9em; }}
.m-body.open {{ max-height:none; padding-top:10px; border-top:1px dotted #ccc; }}
.toggle {{ cursor:pointer; color:var(--primary); font-size:0.8em; }}
.open-link {{ color:#2563eb; text-decoration:none; margin-left:10px; font-size:0.8em; cursor:pointer; }}
.open-link:hover {{ text-decoration:underline; }}
.nav-fab-container {{ position: fixed; top: 50%; right: 20px; transform: translateY(-50%); display: flex; flex-direction: column; gap: 15px; z-index: 1000; pointer-events: none; }}
.nav-fab-btn {{ pointer-events: auto; width: 56px; height: 56px; border-radius: 50%; background-color: rgba(0, 0, 0, 0.05); border: 1px solid rgba(0, 0, 0, 0.05); color: var(--primary); text-shadow: 1px 1px 0 #fff, -1px 1px 0 #fff, 1px -1px 0 #fff, -1px -1px 0 #fff, 0 2px 5px rgba(0,0,0,0.3); font-size: 32px; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: all 0.2s; }}
.nav-fab-btn:active {{ background-color: rgba(37, 99, 235, 0.2); transform: scale(0.95); }}
.nav-fab-btn.disabled {{ color: rgba(150, 150, 150, 0.5); cursor: default; text-shadow: none; pointer-events: none; }}
.nav-indicator {{ pointer-events: auto; background: rgba(0, 0, 0, 0.4); color: white; padding: 2px 8px; border-radius: 10px; text-align: center; font-size: 0.8rem; margin-bottom: 5px; font-weight: bold; }}
.header-actions {{ display:flex; justify-content:space-between; align-items:flex-end; }}
</style>
<script>
let translations = {{}};
function toggle(e) {{
    let b = e.nextElementSibling; b.classList.toggle('open');
    e.innerText = b.classList.contains('open') ? "▲ 閉じる" : "▼ 全文";
}}
function toggleHist(e) {{
    let c = e.nextElementSibling;
    const isOpen = (c.style.display === 'none' || c.style.display === '');
    c.style.display = isOpen ? 'block' : 'none';
    e.innerText = isOpen ? e.innerText.replace('▼', '▲') : e.innerText.replace('▲', '▼');
}}

async function translateText(btn, uid, serverPort) {{
    const wrapper = document.getElementById('m-body-wrapper-' + uid);
    const iframe = document.getElementById('iframe-' + uid);
    
    if (iframe) {{
        const doc = iframe.contentDocument;
        if (!doc) return;

        if (btn.getAttribute('data-state') === 'ja') {{
            const orig = JSON.parse(iframe.dataset.origTexts);
            applyTextsToIframe(doc, orig);
            btn.textContent = "🌐 翻訳";
            btn.setAttribute('data-state', 'en');
            return;
        }}

        if (iframe.dataset.transTexts) {{
            const trans = JSON.parse(iframe.dataset.transTexts);
            applyTextsToIframe(doc, trans);
            btn.textContent = "英 原文";
            btn.setAttribute('data-state', 'ja');
            return;
        }}

        btn.textContent = "⏳ 翻訳中...";
        btn.style.pointerEvents = 'none';
        btn.style.opacity = '0.5';

        const texts = extractTextsFromIframe(doc);
        iframe.dataset.origTexts = JSON.stringify(texts);

        const payloadTexts = [];
        const map = [];
        const isNoise = (s) => {{
            const trimmed = s.trim();
            if (trimmed === '') return true;
            if (/^https?:\\/\\//.test(trimmed)) return true;
            if (!/[a-zA-Z]/.test(trimmed)) return true;
            return false;
        }};
        
        for(let i = 0; i < texts.length; i++) {{
            if(isNoise(texts[i])) continue;
            payloadTexts.push(texts[i]);
            map.push(i);
        }}

        try {{
            let translatedPayload = payloadTexts;
            if (payloadTexts.length > 0) {{
                const response = await fetch(`http://localhost:${{serverPort}}/translate_array`, {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ texts: payloadTexts }})
                }});
                const data = await response.json();
                if (!response.ok) throw new Error(data.error || "通信エラー");
                translatedPayload = data.translated;
            }}
            
            const finalTranslated = [...texts];
            for(let i = 0; i < payloadTexts.length; i++) {{
                finalTranslated[map[i]] = translatedPayload[i];
            }}

            iframe.dataset.transTexts = JSON.stringify(finalTranslated);
            applyTextsToIframe(doc, finalTranslated);

            btn.textContent = "英 原文";
            btn.setAttribute('data-state', 'ja');
        }} catch (e) {{
            alert("翻訳に失敗しました: " + e.message);
            btn.textContent = "🌐 翻訳";
        }} finally {{
            btn.style.pointerEvents = 'auto';
            btn.style.opacity = '1';
            if (wrapper && wrapper.style.display === 'none') {{
                wrapper.style.display = 'block';
                btn.parentNode.parentNode.querySelector('.toggle').textContent = '▲ 閉じる';
            }}
        }}
        return;
    }}
    
    const bodyContainer = document.getElementById('m-body-' + uid) || document.getElementById('body-' + uid);
    if (!bodyContainer) return;
    
    if (!bodyContainer.dataset.originalHtml) {{
        bodyContainer.dataset.originalHtml = bodyContainer.innerHTML;
    }}
    const originalHtml = bodyContainer.dataset.originalHtml;
    
    if (btn.getAttribute('data-state') === 'ja') {{
        bodyContainer.innerHTML = originalHtml;
        btn.textContent = "🌐 翻訳";
        btn.setAttribute('data-state', 'en');
        return;
    }}
    if (translations[uid]) {{
        bodyContainer.innerHTML = translations[uid];
        btn.textContent = "英 原文";
        btn.setAttribute('data-state', 'ja');
        return;
    }}
    
    btn.textContent = "⏳ 翻訳中...";
    btn.style.pointerEvents = 'none';
    btn.style.opacity = '0.5';
    let originalText = bodyContainer.getAttribute('data-original');
    bodyContainer.innerHTML = '⏳ 翻訳中...';
    try {{
        const response = await fetch(`http://localhost:${{serverPort}}/translate`, {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({{ text: originalText }})
        }});
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "通信エラー");
        
        let safeTrans = data.translated.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        let linkedTrans = autoLink(safeTrans);
        
        translations[uid] = linkedTrans;
        bodyContainer.innerHTML = linkedTrans;
        btn.textContent = "英 原文";
        btn.setAttribute('data-state', 'ja');
    }} catch (e) {{
        alert("翻訳に失敗しました: " + e.message);
        bodyContainer.innerHTML = originalHtml;
        btn.textContent = "🌐 翻訳";
    }} finally {{
        btn.style.pointerEvents = 'auto';
        btn.style.opacity = '1';
        if (bodyContainer.style.display === 'none' || bodyContainer.style.display === '') {{
            bodyContainer.style.display = 'block';
            btn.parentNode.parentNode.querySelector('.toggle').textContent = '▲ 閉じる';
        }}
    }}
}}

function extractTextsFromIframe(doc) {{
    const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT, null, false);
    let node;
    const texts = [];
    while (node = walker.nextNode()) {{
        const p = node.parentNode.nodeName;
        if (p === 'SCRIPT' || p === 'STYLE' || p === 'NOSCRIPT') continue;
        if (node.nodeValue.trim() !== '') {{
            texts.push(node.nodeValue);
        }}
    }}
    return texts;
}}

function applyTextsToIframe(doc, textsArr) {{
    const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT, null, false);
    let node;
    let i = 0;
    while (node = walker.nextNode()) {{
        const p = node.parentNode.nodeName;
        if (p === 'SCRIPT' || p === 'STYLE' || p === 'NOSCRIPT') continue;
        if (node.nodeValue.trim() !== '') {{
            if (textsArr[i] !== undefined) {{
                node.nodeValue = textsArr[i];
            }}
            i++;
        }}
    }}
}}

function toggleSingleMailBody(btn, uid) {{
    const wrapper = document.getElementById('m-body-wrapper-' + uid);
    if (wrapper) {{
        if (wrapper.style.display === 'none') {{
            wrapper.style.display = 'block';
            btn.textContent = '▲ 閉じる';
        }} else {{
            wrapper.style.display = 'none';
            btn.textContent = '▼ 全文';
        }}
        return;
    }}
    const body = document.getElementById('body-' + uid) || document.getElementById('m-body-' + uid);
    if (body) {{
        if (body.style.display === 'none' || body.style.display === '') {{
            body.style.display = 'block';
            btn.textContent = '▲ 閉じる';
        }} else {{
            body.style.display = 'none';
            btn.textContent = '▼ 全文';
        }}
    }}
}}

function autoLink(text) {{
    const urlRegex = /(https?:\\/\\/[^\\s<>"]+)/g;
    return text.replace(urlRegex, function(url) {{
        let displayUrl = url;
        if (url.includes('safelinks.protection.outlook.com')) {{
            try {{
                let unescapedUrl = url.replace(/&amp;/g, '&');
                let urlObj = new URL(unescapedUrl);
                let params = new URLSearchParams(urlObj.search);
                if (params.has('url')) {{
                    displayUrl = params.get('url');
                }}
            }} catch(e) {{}}
        }}
        displayUrl = displayUrl.replace(/&amp;/g, '&');
        if (displayUrl.length > 50) {{
            displayUrl = displayUrl.substring(0, 47) + "...";
        }}
        return '<a href="' + url + '" target="_blank" style="color:#2563eb; text-decoration:underline; word-break:break-all;">' + displayUrl + '</a>';
    }});
}}

let currentIndex = 0; 
const totalCount = {len(threads)}; 
let isAutoScrolling = false;
function updateNavState() {{
    const btnPrev = document.getElementById('btnPrev'); 
    const btnNext = document.getElementById('btnNext');
    if(btnPrev) btnPrev.classList.toggle('disabled', currentIndex <= 0);
    if(btnNext) btnNext.classList.toggle('disabled', currentIndex >= totalCount);
    const indicator = document.getElementById('navIndicator');
    if(indicator) {{ indicator.textContent = currentIndex === 0 ? "Top" : currentIndex + " / " + totalCount; }}
    document.querySelectorAll('.thread-card').forEach(c => c.classList.remove('active-card'));
    if (currentIndex > 0) {{ 
        const activeCard = document.getElementById('card-' + currentIndex); 
        if (activeCard) activeCard.classList.add('active-card'); 
    }}
}}
function scrollToCard(index) {{
    if (index < 0 || index > totalCount || isAutoScrolling) return;
    isAutoScrolling = true;
    if (index === 0) {{ window.scrollTo({{ top: 0, behavior: 'smooth' }}); }} 
    else {{ 
        const target = document.getElementById('card-' + index); 
        if (target) {{ target.scrollIntoView({{ behavior: 'smooth', block: 'start' }}); }} 
    }}
    currentIndex = index; updateNavState(); setTimeout(() => {{ isAutoScrolling = false; }}, 200);
}}
function scrollToNext() {{ if (currentIndex < totalCount) scrollToCard(currentIndex + 1); }}
function scrollToPrev() {{ if (currentIndex > 0) scrollToCard(currentIndex - 1); }}
document.addEventListener('DOMContentLoaded', function() {{
    updateNavState();
}});
</script>
</head><body>
<div class="container">
    <div id="top-header" class="header" data-index="0"><h1>📧 レポート</h1><div>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div></div>
    <div class="header-actions">
        <div class="stats-container">
            <div class="stat-card"><div class="stat-val">{len(threads)}</div><div>Threads</div></div>
            <div class="stat-card"><div class="stat-val">{total_m}</div><div>Mails</div></div>
            <div class="stat-card"><div class="stat-val">{high_p}</div><div>High Priority</div></div>
        </div>
    </div>
    <br>
    {''.join(cards)}
</div>
<div class="nav-fab-container">
    <div id="navIndicator" class="nav-indicator">Top</div>
    <button onclick="scrollToPrev()" class="nav-fab-btn" id="btnPrev">▲</button>
    <button onclick="scrollToNext()" class="nav-fab-btn" id="btnNext">▼</button>
</div>
</body></html>"""

    def _card(self, t, s, index):
        mail_html = []
        ms = s.get('mail_summaries', [])
        for i, m in enumerate(t['mails']):
            if i < len(ms) and ms[i] and ms[i] != "(生成失敗)": summ = f"💡 {ms[i]}"
            else: summ = m['body'][:80].replace('\n', ' ') + "..."
            link = f'http://localhost:{self.server_port}/open?id={m["entry_id"]}'
            uid = m['entry_id']
            
            att_names = m.get('attachment_names', [])
            att_html = ""
            if att_names:
                att_html = f'<div style="font-size:0.85em; color:#475569; margin-top:3px; font-weight:bold;">📎 添付ファイル: {", ".join(att_names)}</div>'
                
            html_body_raw = m.get('html_body', '')
            if html_body_raw:
                import html
                import re
                for cid, b64_data in m.get('inline_images', {}).items():
                    html_body_raw = re.sub(rf'src=["\']cid:{re.escape(cid)}.*?["\']', f'src="{b64_data}"', html_body_raw, flags=re.IGNORECASE)
                safe_srcdoc = html.escape(html_body_raw, quote=True)
                body_render = f'''
                <div id="m-body-wrapper-{uid}" style="display:none; margin-top:10px; padding-top:10px; border-top:1px dotted #ccc; background:#fff;">
                    <iframe id="iframe-{uid}" srcdoc="{safe_srcdoc}" style="width:100%; border:none; min-height:500px; resize:vertical; overflow:auto;"></iframe>
                </div>
                '''
            else:
                raw_body_clean = m['body'].replace('&', '&amp;').replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
                linked_body = self._auto_link_text(raw_body_clean)
                body_render = f'<div class="m-body" id="m-body-{uid}" data-original="{raw_body_clean}" data-translated="false" style="display:none; padding-top:10px; border-top:1px dotted #ccc; font-size:0.9em; white-space:pre-wrap;">{linked_body}</div>'
            
            mail_html.append(f'''
            <div class="mail-item">
                <div class="m-head">{m['sender_name']} <span style="font-weight:normal;font-size:0.8em">{m['received']}</span>
                    <a href="{link}" target="_blank" class="open-link">🚀 Outlook</a>
                    <button onclick="translateText(this, '{uid}', {self.server_port})" class="open-link" style="background:none; border:none; padding:0; font:inherit;" data-state="en">🌐 翻訳</button>
                </div>
                {att_html}
                <div class="m-sum">{summ}</div>
                <button class="toggle" onclick="toggleSingleMailBody(this, '{uid}')" style="background:none; border:none; padding:0; font:inherit; color:var(--primary); cursor:pointer; font-size:0.85em;">▼ 全文</button>
                {body_render}
            </div>''')
        
        acts = []
        for a in s.get('action_items', []):
            cls = "act-high" if a.get('priority')=='高' else ""
            acts.append(f'<div class="act-item {cls}"><div>[{a.get("priority")}]</div><div style="flex:1"><b>{a.get("action")}</b><br><span style="font-size:0.8em">担当:{a.get("owner")} 期限:{a.get("deadline")}</span></div></div>')
            
        if s.get('is_rss'):
            pts_html = []
            for pt in s.get('main_points', []):
                pts_html.append(f'<div style="margin-bottom:10px; background:#f8fafc; padding:10px; border-left:4px solid var(--primary);"><b>{pt.get("point_title", "")}</b><br><span style="font-size:0.9em;">{pt.get("description", "")}</span></div>')
            s_content = f'''
            <div class="section"><div class="sec-title">📝 要旨</div><div class="sum-box">{s.get("summary","")}</div></div>
            <div class="section"><div class="sec-title">🔑 キーワード</div><div style="padding:5px 15px; font-weight:bold; color:#475569;">{s.get("keywords","")}</div></div>
            <div class="section"><div class="sec-title">🎯 結論</div><div class="sum-box" style="white-space:pre-wrap;">{s.get("conclusion","")}</div></div>
            <div class="section"><div class="sec-title">💡 主なポイント</div><div>{"".join(pts_html)}</div></div>
            '''
            return f'''
            <div class="thread-card" id="card-{index}" data-index="{index}">
                <div class="t-head">
                    <div class="t-title">📰 {s.get("title", t['topic'])}</div>
                    <div>
                        {f'<a href="{s.get("article_url")}" target="_blank" class="open-link">🌐 記事の表示</a>' if s.get('article_url') else ''}
                        {f'<a href="http://localhost:{self.server_port}/open?id={t["latest_entry_id"]}" target="_blank" class="open-link">🚀 Outlook</a>' if t.get('latest_entry_id') else ''}
                    </div>
                </div>
                <div class="t-body">
                    {s_content}
                    <div class="section" style="cursor:pointer;background:#eee;padding:5px" onclick="toggleHist(this)">📬 RSS元テキスト表示 ▼</div>
                    <div style="display:none">{"".join(mail_html)}</div>
                </div>
            </div>'''
            
        return f'''
        <div class="thread-card" id="card-{index}" data-index="{index}">
            <div class="t-head">
                <div class="t-title">{t['topic']} <span style="font-size:0.7em;background:#eee;padding:2px 6px;border-radius:10px">{t['mail_count']}件</span></div>
                {f'<a href="http://localhost:{self.server_port}/open?id={t["latest_entry_id"]}" target="_blank" class="open-link">🚀 Outlook</a>' if t.get('latest_entry_id') else ''}
            </div>
            <div class="t-body">
                {f'<div class="section"><div class="sec-title">📝 要約</div><div class="sum-box">{s.get("summary","")}</div></div>' if s.get('summary') else ''}
                {f'<div class="section"><div class="sec-title">✅ アクション</div>{"".join(acts)}</div>' if acts else ''}
                <div class="section" style="cursor:pointer;background:#eee;padding:5px" onclick="toggleHist(this)">📬 履歴 ({t['mail_count']}) ▼</div>
                <div style="display:none">{"".join(mail_html)}</div>
            </div>
        </div>'''


    def _render_structured_items(self, items: list, is_status: bool = False) -> str:
        """AIの構造化データを連動フィルタリング用のLIタグに変換（案C: 隠し接頭辞付き）"""
        import html
        res = []
        for item in items:
            # 型安全性の確保：辞書型でない場合はデフォルト値でラップ
            if not isinstance(item, dict):
                d = {
                    "category": "その他",
                    "project_scope": "横断業務",
                    "action_type": "通知・共有",
                    "text": str(item or ""),
                    "status_icon": "⚪"
                }
            else:
                d = item

            # 属性の取得とエスケープ（Null安全）
            cat = html.escape(str(d.get('category') or 'その他'))
            proj = html.escape(str(d.get('project_scope') or '横断業務'))
            act = html.escape(str(d.get('action_type') or '通知・共有'))
            txt = html.escape(str(d.get('text') or ''))
            
            # ステータス専用アイコンの処理
            icon_html = ""
            if is_status:
                icon = html.escape(str(d.get('status_icon') or '⚪'))
                icon_html = f'<span style="margin-right:5px; font-size:1.1em;">{icon}</span>'

            # 案C: 3軸の接頭辞を隠しタグとして埋め込む（JSの switchView で表示/非表示を切り替える）
            # 色指定は各バッジの bg-cat, bg-proj, bg-act と同期
            prefix_cat = f'<span class="px-cat" style="display:none; font-weight:bold; color:#6366f1; margin-right:4px;">[{cat}]</span>'
            prefix_proj = f'<span class="px-proj" style="display:none; font-weight:bold; color:#0ea5e9; margin-right:4px;">[{proj}]</span>'
            prefix_act = f'<span class="px-act" style="display:none; font-weight:bold; color:#f59e0b; margin-right:4px;">[{act}]</span>'
            
            # JS連動用の属性(data-*)をli要素に付与して返却
            res.append(f'<li class="js-summary-item" style="margin-bottom:6px;" data-category="{cat}" data-project="{proj}" data-action="{act}">{icon_html}{prefix_cat}{prefix_proj}{prefix_act}<span class="text">{txt}</span></li>')
            
        return "".join(res)

    def _format_recent_history(self, text: str) -> str:
        if not text: return ""
        import re
        import html
        safe_text = html.escape(text)
        
        # タイムスタンプ行を太字と区切り線で強調
        pattern = r'(\[\d{4}/\d{2}/\d{2} \d{2}:\d{2}.*?\])'
        safe_text = re.sub(pattern, r'<div style="margin-top:15px; padding-top:10px; border-top:1px dashed #cbd5e1; font-weight:bold; color:#0369a1;">\1</div>', safe_text)
        
        # 長文を「。」で改行してリスト化風に（先頭に箇条書きマーカーを入れる）
        safe_text = safe_text.replace('。', '。<br><span style="color:#94a3b8; margin-right:4px;">•</span>')
        
        # 重要キーワードのハイライト
        keywords = ["遅延", "リスク", "課題", "未定", "確認依頼", "重要", "アラート", "漏れ"]
        for kw in keywords:
            safe_text = safe_text.replace(kw, f'<span style="color:#ef4444; font-weight:bold; background:#fee2e2; padding:0 2px; border-radius:2px;">{kw}</span>')
            
        return safe_text

    def _clean_body_for_display(self, text: str, limit: int = 2000) -> str:
        if not text: return ""
        import re
        text = re.sub(r'[\r\n]+', '\n', str(text))
        if len(text) > limit:
            return text[:limit] + "\n... (以降省略) ..."
        return text

    def _auto_link_text(self, text: str) -> str:
        if not text: return ""
        import re
        url_regex = r'(https?://[\w/:%#\$&\?\(\)~\.=\+\-]+)'
        return re.sub(url_regex, r'<a href="\1" target="_blank" style="color:#60a5fa; text-decoration:underline;">\1</a>', text)

    def generate_project_report(self, report_name, summaries, orig_threads_map, knowledge, date_range, sort_order, total_input, total_output, report_mode="adopted", reformat_mode=False) -> str:
        try:
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            if not self.folder.exists():
                self.folder.mkdir(parents=True)
            
            safe_report_name = "".join([c for c in report_name if c.isalnum() or c in " ._-"])
            path = self.folder / f"Project_{safe_report_name}_{ts}.html"
            
            in_cost = (total_input / 1000000) * 0.075 * 160
            out_cost = (total_output / 1000000) * 0.3 * 160
            total_yen = round(in_cost + out_cost, 2)
            cost_display = (
                "🎨 フォーマット再生成のみ（APIコスト無し）"
                if reformat_mode
                else f"💰 APIコスト概算: 約 {total_yen} 円 (In:{total_input} / Out:{total_output})"
            )
            

            def get_status_badge(st):
                s = st.lower()
                if any(k in s for k in ["未設定", "漏れ", "未定"]):
                    return f'<span style="background:#fee2e2; color:#ef4444; font-weight:bold; font-size:0.85em; padding:2px 6px; border-radius:4px;">{st}</span>'
                elif "完了" in s:
                    return f'<span style="background:#dcfce7; color:#16a34a; font-weight:bold; font-size:0.85em; padding:2px 6px; border-radius:4px;">{st}</span>'
                elif "遅延" in s:
                    return f'<span style="background:#fef08a; color:#a16207; font-weight:bold; font-size:0.85em; padding:2px 6px; border-radius:4px;">{st}</span>'
                else:
                    return f'<span style="background:#f1f5f9; color:#64748b; font-size:0.85em; padding:2px 6px; border-radius:4px;">{st}</span>'

            def _render_structured_items(items, th_idx_map, proj_prefix, is_top3=False):
                import html
                if not items: return ""
                html_list = []
                for item in items:
                    icon = item.get('status_icon', '⚪')
                    cat = html.escape(str(item.get('category', 'その他')))
                    pj = html.escape(str(item.get('project_scope', '横断業務')))
                    act = html.escape(str(item.get('action_type', '通知・共有')))
                    text = item.get("text", "")
                    
                    source_ids = item.get("source_thread_ids", [])
                    badges = ""
                    if isinstance(source_ids, list):
                        for tid in source_ids:
                            idx = th_idx_map.get(tid, "?")
                            badges += f' <a href="javascript:void(0)" onclick="event.stopPropagation(); jumpToThread(\'{proj_prefix}_{tid}\')" class="cite-badge" title="根拠スレッドへジャンプ">[{idx}]</a>'
                    
                    prefix_html = f'<span class="px-cat">[{cat}]</span><span class="px-proj" style="display:none;">[{pj}]</span><span class="px-act" style="display:none;">[{act}]</span>'
                    html_list.append(f'<li class="js-summary-item"><span class="status-icon">{icon}</span> <strong>{prefix_html}</strong> {text}{badges}</li>')
                return "".join(html_list)

            import html
            from urllib.parse import quote
            html_blocks = []
            for proj, data in summaries.items():
                proj_id = proj.replace(" ", "_").replace(".", "")
                safe_proj_name_js = proj.replace("'", "\\'")
                
                if data.get('_error'):
                    html_blocks.append(f'<div class="thread-card"><div class="t-head t-title">{proj} - エラー</div><div class="t-body">{data.get("summary")}</div></div>')
                    continue

                proj_know = knowledge.get('projects', {}).get(proj, {})
                master_hist = proj_know.get('master_history', '')
                formatted_hist = self._format_recent_history(proj_know.get('history_summary', ''))
                human_ans = proj_know.get('human_answers', '')
                
                ai_threads = data.get('threads', [])
                if report_mode == "adopted":
                    adopted_ids = set()
                    for section_key in ("manager_actions", "staff_status", "stalled_monitor"):
                        for item in data.get(section_key, []):
                            for tid in item.get("source_thread_ids", []):
                                adopted_ids.add(str(tid).strip().upper())
                    if adopted_ids:
                        ai_threads = [th for th in ai_threads if str(th.get('thread_id', '')).strip().upper() in adopted_ids]
                        print(f"[DEBUG] 軽量モード: {proj} -> {len(ai_threads)}件に絞り込み (採用ID: {len(adopted_ids)}件)")
                    else:
                        print(f"[DEBUG] 軽量モード: {proj} -> 採用IDなし、全スレッドで生成")
                target_threads, noise_threads = [], []
                for th in ai_threads:
                    cid = th.get('thread_id', '')
                    orig_t = orig_threads_map.get(proj, {}).get(cid, {})
                    latest_dt = orig_t.get('latest_date', datetime.min)
                    th['_entry_id'] = orig_t.get('latest_entry_id', '')
                    th['_ts_val'] = int(latest_dt.timestamp())
                    imp = th.get('importance', '中')
                    th['_imp_val'] = {"高": 0, "中": 1, "低": 2}.get(imp, 1)
                    if th.get('is_target', True): target_threads.append(th)
                    else: noise_threads.append(th)

                standard_sorted = sorted(target_threads, key=lambda x: (x['_imp_val'], -x['_ts_val']))
                th_id_to_index = {th.get('thread_id', ''): i + 1 for i, th in enumerate(standard_sorted)}

                if sort_order == "重要度順": 
                    target_threads.sort(key=lambda x: (x['_imp_val'], -x['_ts_val']))
                elif sort_order == "最新スレッド順": 
                    target_threads.sort(key=lambda x: x['_ts_val'], reverse=True)

                th_html = []
                for th in target_threads:
                    imp = th.get('importance', '中')
                    badge_col = '#f97316' if imp == '高' else '#10b981' if imp == '低' else '#eab308'
                    
                    _e = lambda x: html.escape(str(x))
                    cat, pj, act = _e(th.get('category', 'その他')), _e(th.get('project_scope', '横断業務')), _e(th.get('action_type', '通知・共有'))
                    
                    orig_th_id = th.get('thread_id', f'rand_{int(datetime.now().timestamp())}')
                    th_id = f"{proj_id}_{orig_th_id}"
                    
                    global_idx = th_id_to_index.get(orig_th_id, "?")
                    orig_t_info = orig_threads_map.get(proj, {}).get(orig_th_id, {})
                    orig_mails = orig_t_info.get('mails', [])
                    uid_latest = f"{th_id}_m{len(orig_mails) - 1}" if orig_mails else f"{th_id}_m0"
                    
                    orig_topic_encoded = quote(str(orig_t_info.get("topic", "")))
                    safe_topic = th.get("topic", "").replace("'", "\\'").replace('"', '&quot;')
                    
                    link_btn = f'<a href="http://localhost:{self.server_port}/open?id={th.get("_entry_id")}&topic={orig_topic_encoded}" target="_blank" onclick="event.stopPropagation();" style="font-size:0.75em; text-decoration:none; background:#eff6ff; color:#2563eb; padding:2px 8px; border-radius:12px; border:1px solid #bfdbfe; margin-left:10px;">Outlook</a>' if th.get("_entry_id") else ''
                    detail_btn = f'<button onclick="event.stopPropagation(); forceOpenThread(\'{th_id}\'); summarizeDetail(this, \'{th_id}\', \'{uid_latest}\', \'{safe_topic}\', \'{safe_proj_name_js}\', \'project\', {self.server_port})" style="font-size:0.75em; background:#e0f2fe; color:#0369a1; border:1px solid #7dd3fc; border-radius:12px; padding:2px 8px; cursor:pointer; margin-left:10px;">📄 詳細</button>'
                    rule_btn = f'<button onclick="event.stopPropagation(); toggleRuleForm(\'{th_id}\')" style="font-size:0.75em; background:#fef3c7; color:#ea580c; border:1px solid #fdba74; border-radius:12px; padding:2px 8px; cursor:pointer; margin-left:10px;">🔄 学習</button>'
                    
                    acts_table = ""
                    if th.get('actions'):
                        rows = "".join([f'<tr style="border-bottom:1px solid #e2e8f0;"><td style="padding:8px; font-weight:bold;">{a.get("owner")}</td><td style="padding:8px;">{a.get("action")}</td><td style="padding:8px;">{get_status_badge(a.get("status", ""))}</td></tr>' for a in th.get('actions')])
                        acts_table = f'<div style="margin-bottom:15px;"><button onclick="event.stopPropagation(); toggleActions(this, \'acts-{th_id}\')" style="width:100%; text-align:left; font-weight:bold; cursor:pointer; background:#f8fafc; border:1px solid #cbd5e1; padding:6px 12px; border-radius:4px; font-size:0.85em;">▼ アクション ({len(th.get("actions"))}件)</button><div id="acts-{th_id}" style="display:none; background:#fff; border:1px solid #cbd5e1; border-top:none; padding:10px;"><table style="width:100%; border-collapse:collapse; font-size:0.95em;">{rows}</table></div></div>'

                    # ★変更★ 最新メール1件のみ生成（orig_mails[-1:]）
                    mail_items_html = []
                    for i, m in zip([len(orig_mails) - 1], orig_mails[-1:]):
                        uid = f"{th_id}_m{i}"
                        display_body = str(m.get('body', ''))  # ★変更★ 常に全文（最新メールのみのため条件不要）
                        mail_topic_encoded = quote(str(m.get("conversation_topic") or m.get("subject", "")))
                        item_link = f'<a href="http://localhost:{self.server_port}/open?id={m.get("entry_id")}&topic={mail_topic_encoded}" target="_blank" onclick="event.stopPropagation();" style="font-size:0.85em; text-decoration:none; color:#2563eb; margin-left:15px;">&#x1F680; Outlook</a>'
                        summary_btn = f'<div id="sum-{uid}" style="margin-bottom:8px;" onclick="event.stopPropagation();"><button onclick="summarizeSingleMail(this, \'{uid}\', \'{safe_topic}\', {self.server_port})" style="cursor:pointer; background:#fff; border:1px solid #cbd5e1; padding:4px 10px; border-radius:12px; font-size:0.85em;">✨ 要約</button></div>'
                        html_body_raw = m.get('html_body', '')
                        if html_body_raw:
                            import re
                            for img_cid, b64_data in m.get('inline_images', {}).items():
                                html_body_raw = re.sub(rf'src=["\'"]cid:{re.escape(img_cid)}.*?["\']', f'src="{b64_data}"', html_body_raw, flags=re.IGNORECASE)
                            body_render = f'<div id="m-body-wrapper-{uid}" style="display:none; margin-top:10px; padding-top:10px; border-top:1px dotted #cbd5e1;" onclick="event.stopPropagation();"><iframe id="iframe-{uid}" srcdoc="{html.escape(html_body_raw, quote=True)}" style="width:100%; min-height:450px; border:none;"></iframe></div>'
                        else:
                            clean_text = display_body.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
                            body_render = f'<div id="body-{uid}" class="mail-item-body" onclick="event.stopPropagation();" data-original="{clean_text}" style="display:none; margin-top:10px; padding-top:10px; border-top:1px dotted #cbd5e1; white-space:pre-wrap; font-size:0.9em;">{self._auto_link_text(clean_text)}</div>'
                        mail_items_html.append(f'<div style="border-left:3px solid #cbd5e1; padding:10px; background:#f8fafc; margin-top:10px; border-radius:4px;"><b>👤 {m.get("sender_name")}</b> <span style="font-weight:normal; margin-left:10px; color:#64748b;">{m.get("received")}</span> <button onclick="event.stopPropagation(); translateText(this, \'{uid}\', {self.server_port})" class="view-btn" style="font-size:0.8em; padding:2px 8px; margin-left:10px;">🌐 翻訳</button>{item_link}{summary_btn}<div><button onclick="event.stopPropagation(); toggleSingleMailBody(this, \'{uid}\')" style="cursor:pointer; background:none; border:none; text-decoration:underline; font-size:0.85em; color:#2563eb;">▼ 全文</button></div>{body_render}</div>')

                    th_html.append(f'''
                    <div class="thread-card js-thread" id="thread-body-{th_id}" onclick="toggleThreadCard('{th_id}')" data-imp="{th.get('_imp_val')}" data-date="{th.get('_ts_val')}" data-category="{cat}" data-project="{pj}" data-action="{act}" style="border-left:4px solid {badge_col}; padding:12px 15px; background:#fff; margin-bottom:12px; border-radius:6px; box-shadow:0 1px 3px rgba(0,0,0,0.1); cursor:pointer; transition:background 0.2s;">
                        <div style="display:flex; justify-content:space-between; align-items:center; gap:8px;">
                            <div style="display:flex; align-items:center; gap:6px; font-weight:bold; font-size:1.05em; min-width:0;">
                                <span class="cite-badge" style="vertical-align:baseline; flex-shrink:0;">[{global_idx}]</span>
                                <span style="overflow:hidden; text-overflow:ellipsis;">{th.get("topic")}</span>
                            </div>
                            <div style="display:flex; align-items:center; gap:5px; flex-shrink:0;">
                                <span class="badge-imp" style="background:{badge_col}; color:white; padding:2px 8px; border-radius:12px; font-size:0.7em; white-space:nowrap;">重要度:{imp}</span>
                                {link_btn}{rule_btn}{detail_btn}
                                <a href="#proj-top-{proj_id}" onclick="event.stopPropagation();" style="font-size:0.75em; color:#94a3b8; text-decoration:none; white-space:nowrap;" title="プロジェクト先頭に戻る">↑ 戻る</a>
                            </div>
                        </div>
                        <div class="tag-row">
                            <span class="badge bg-cat">🏷️ {cat}</span> <span class="badge bg-proj">📁 {pj}</span> <span class="badge bg-act">⚡ {act}</span>
                        </div>
                        <div id="inner-thread-body-{th_id}" class="thread-accordion-body" style="display:none; margin-top:15px; border-top:1px dashed #cbd5e1; padding-top:15px;">
                            <div id="rule-form-{th_id}" onclick="event.stopPropagation();" style="display:none; background:#fffbeb; padding:10px; margin-bottom:15px; border-radius:6px; border:1px solid #fde68a;">
                                <select id="rule-sel-{th_id}"><option value="重要">重視</option><option value="無視">無視</option></select>
                                <input type="text" id="rule-txt-{th_id}"><button onclick="submitAiRule('{proj_id}', '{safe_proj_name_js}', 'project', '{th_id}', {self.server_port}, this)">登録</button>
                            </div>
                            <div id="detail-{th_id}" style="display:none; margin-bottom:15px; padding:15px; border:2px solid #bae6fd; background:#f0f9ff; border-radius:6px; font-size:0.95em;" onclick="event.stopPropagation();"></div>
                            <div style="font-size:0.95em; margin-bottom:15px; line-height:1.6; color:#334155;">{th.get("summary")}</div>
                            {acts_table}
                            <div><button style="cursor:pointer; background:#fff; border:1px solid #cbd5e1; padding:6px 12px; border-radius:4px; font-size:0.85em; font-weight:bold;" onclick="event.stopPropagation(); toggleThreadMails(this, '{th_id}')">▲ 閉じる</button></div>
                            <div id="mails-{th_id}" style="display:block; margin-top:10px;" onclick="event.stopPropagation();">{"".join(mail_items_html)}</div>
                        </div>
                    </div>''')

                # V33修正: プロジェクト側の新スキーマのキー名で読み込み（A案: 個別改修）
                act_html = _render_structured_items(data.get("manager_actions", []), th_id_to_index, proj_id, True)
                stat_html = _render_structured_items(data.get("staff_status", []), th_id_to_index, proj_id, True)
                stall_html = _render_structured_items(data.get("stalled_monitor", []), th_id_to_index, proj_id, True)

                html_blocks.append(f'''
                <div class="project-container" style="background:#fff; margin-bottom:30px; border-radius:10px; overflow:hidden; box-shadow:0 4px 6px rgba(0,0,0,0.05);">
                    <div id="proj-top-{proj_id}" style="padding:15px 20px; background:#f8fafc; border-bottom:1px solid #e2e8f0; scroll-margin-top:10px;"><div style="font-weight:bold; font-size:20px; color:#1e293b;">📁 {proj}</div></div>
                    <div style="padding:20px; background:#f3f4f6;">

                        <div class="summary-section" style="display:flex; flex-direction:column; gap:10px; margin-bottom:20px;">
                            <div class="summary-card" style="background:#fff; border-left:5px solid #ef4444; padding:15px; border-radius:8px;"><b>🔴 上司(あなた)の介入・承認が必要な事項</b><ul style="margin:5px 0 0 0; padding-left:20px;">{act_html}</ul></div>
                            <div class="summary-card" style="background:#fff; border-left:5px solid #eab308; padding:15px; border-radius:8px;"><b>🟡 停滞監視 (ボールを持ったまま止まっている案件)</b><ul style="margin:5px 0 0 0; padding-left:20px;">{stall_html}</ul></div>
                            <div class="summary-card" style="background:#fff; border-left:5px solid #3b82f6; padding:15px; border-radius:8px;"><b>🔵 プロジェクト進捗</b><ul style="margin:5px 0 0 0; padding-left:20px;">{stat_html}</ul></div>
                        </div>                        
                        <button onclick="toggleAnalysis('analysis-wrapper-{proj_id}', this, '▼ 分析を表示')" style="width:100%; text-align:left; font-weight:bold; padding:10px; cursor:pointer; background:#e0e7ff; border:1px solid #c7d2fe; border-radius:6px; color:#3730a3; margin-bottom:15px;">▼ 分析を表示</button>
                        <div id="analysis-wrapper-{proj_id}" class="js-analysis-wrapper" style="display:none; flex-direction:column;">
                            <div class="dashboard-panel" style="background:#f8fafc; padding:15px; border-radius:8px; border:1px solid #e2e8f0; margin-bottom:20px;"><b>📊 3軸連動ダッシュボード</b><div id="dash-counts-{proj_id}" class="dash-row" style="display:flex; flex-wrap:wrap; gap:8px; margin-top:10px;"></div></div>
                            <button onclick="toggleSection('threads-{proj_id}', this, '▼ スレッド詳細を表示 ({len(target_threads)}件)')" style="width:100%; text-align:left; font-weight:bold; padding:10px; cursor:pointer; background:#f1f5f9; border:1px solid #cbd5e1; border-radius:6px;">▼ スレッド詳細を表示 ({len(target_threads)}件)</button>
                            <div id="threads-{proj_id}" style="display:none; flex-direction:column; margin-top:10px;">
                                <div style="text-align:right; margin-bottom:10px;">
                                    <button onclick="toggleAllFilteredThreads('{proj_id}', this)" style="cursor:pointer; font-size:0.85em; padding:4px 12px; margin-right:8px; background:#fff; border:1px solid #cbd5e1; border-radius:4px;">▼ スレッド情報を表示</button>
                                    <button onclick="applyFilter('{proj_id}', '', '')" style="cursor:pointer; font-size:0.85em; padding:4px 12px; background:#f1f5f9; border:1px solid #cbd5e1; border-radius:4px;">すべての絞り込みを解除</button>
                                </div>
                                <div id="thread-container-inner-{proj_id}">{"".join(th_html)}</div>
                            </div>
                            <button onclick="toggleSection('qa-{proj_id}', this, '▼ AI質問と回答メモ')" style="width:100%; text-align:left; padding:10px; margin-top:10px; cursor:pointer; background:#fff7ed; border:1px solid #fed7aa; border-radius:6px; color:#c2410c; font-weight:bold;">▼ AI質問と回答メモ</button>
                            <div id="qa-{proj_id}" style="display:none; background:#fff7ed; padding:15px; border:1px solid #fed7aa; border-top:none;">
                                <textarea id="ta-{proj_id}" style="width:100%; min-height:80px; padding:10px;">{html.escape(human_ans)}</textarea>
                                <button onclick="saveAnswers('{safe_proj_name_js}', 'ta-{proj_id}', 'toast-{proj_id}', {self.server_port})" style="margin-top:10px; cursor:pointer; background:#ea580c; color:white; border:none; padding:6px 15px; border-radius:4px;">保存</button><span id="toast-{proj_id}" style="opacity:0; margin-left:15px;">✅</span>
                            </div>
                            <button onclick="toggleSection('know-{proj_id}', this, '▼ 🧠 プロジェクト情報・過去知識')" style="width:100%; text-align:left; padding:10px; margin-top:10px; cursor:pointer; background:#f0fdfa; border:1px solid #bae6fd; border-radius:6px; color:#0369a1; font-weight:bold;">▼ 🧠 プロジェクト情報・過去知識</button>
                            <div id="know-{proj_id}" style="display:none; padding:15px; background:#f0fdfa; border:1px solid #bae6fd; border-top:none;">
                                <div style="font-weight:bold; font-size:0.9em; margin:10px 0 5px 0;">マスター経緯:</div><textarea id="master-{proj_id}" style="width:100%; min-height:100px;">{html.escape(master_hist)}</textarea>
                                <button onclick="saveProjectKnowledge('{safe_proj_name_js}', 'master-{proj_id}', 'toast-k-{proj_id}', {self.server_port}, this)" style="margin-top:10px; cursor:pointer; background:#0284c7; color:white; border:none; padding:6px 15px; border-radius:4px;">保存</button><span id="toast-k-{proj_id}" style="opacity:0; margin-left:15px;">✅</span>
                                <div style="margin-top:15px; font-size:0.9em; border-top:1px solid #cbd5e1; padding-top:10px;">{formatted_hist}</div>
                            </div>
                        </div>
                    </div>
                </div>''')

            js_css = self._get_common_js_and_css()

            sel_imp = 'selected' if sort_order == "重要度順" else ''
            sel_desc = 'selected' if sort_order == "最新スレッド順" else ''

            final_html = f"""<!DOCTYPE html>
            <html lang="ja">
            <head>
                <meta charset="UTF-8">
                {js_css}
                <style>
                    .cite-badge {{
                        font-size: 0.85em; color: #1a73e8; text-decoration: none; margin-left: 4px;
                        vertical-align: super; font-weight: bold; cursor: pointer;
                    }}
                    .cite-badge:hover {{ text-decoration: underline; }}
                </style>
                <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
            </head>
            <body>
            <div class="container">
            <div class="header"><div><h1 style="margin:0;">📁 {report_name} 活動俯瞰レポート</h1><p style="margin:5px 0 0 0; opacity:0.8;">{date_range}</p></div>
                <div style="background:rgba(255,255,255,0.2); padding:10px; border-radius:8px;">
                    <label for="sortOrder" style="font-weight:bold; font-size:0.9em; margin-right:5px;">並び順:</label>
                    <select id="sortOrder" onchange="sortThreads()" style="padding:6px; border-radius:4px; border:none; font-weight:bold; color:#333;">
                        <option value="importance" {sel_imp}>重要度順</option>
                        <option value="date_desc" {sel_desc}>日時順（新しい順）</option>
                    </select>
                </div>
            </div>
            <div class="controls"><div style="margin-bottom:10px; font-weight:bold; color:#475569;">📊 表示切り替え（グループ化 & 接頭辞連動）</div><div class="btn-group">
                <button class="view-btn active" onclick="switchView('default', this)">🌟 標準（重要度順）</button>
                <button class="view-btn" onclick="switchView('category', this)">🏷️ 業務カテゴリ別</button>
                <button class="view-btn" onclick="switchView('project', this)">📁 プロジェクト別</button>
                <button class="view-btn" onclick="switchView('action', this)">⚡ アクション別</button>
                <button class="view-btn" style="margin-left:auto; background:#f1f5f9; border-color:#cbd5e1; color:#334155;" onclick="toggleAllAnalysisWrappers(this)">📂 全分析を展開</button>
            </div></div>
            {''.join(html_blocks)}<div style="text-align:right; margin-top:20px; font-size:0.9em; color:#64748b;">{cost_display}</div></div>
            <script>
                document.addEventListener('DOMContentLoaded', () => {{
                    if (typeof marked !== 'undefined') {{
                        document.querySelectorAll('.markdown-body').forEach(el => {{
                            const rawText = el.textContent || el.innerText;
                            el.innerHTML = marked.parse(rawText);
                        }});
                    }}
                    if (typeof renderDashboards === 'function') renderDashboards();
                    window.originalOrders = {{}};
                    document.querySelectorAll('[id^="thread-container-inner-"]').forEach(container => {{
                        window.originalOrders[container.id] = Array.from(container.children);
                    }});
                }});
            </script>
            </body></html>"""
            
            html_len = len(final_html)
            chunk_size = 500000 
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    for i in range(0, html_len, chunk_size):
                        f.write(final_html[i:i+chunk_size])
                return str(path)
            except Exception as write_err:
                if path.exists(): 
                    try: path.unlink()
                    except: pass
                raise write_err
                
        except Exception as e: 
            print(f"❌ Project Report Error: {e}")
            return ""

    def generate_staff_report(self, staff_name, summaries, orig_threads_map, knowledge, date_range, sort_order, total_input, total_output, report_mode="adopted", reformat_mode=False) -> str:
        try:
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            if not self.folder.exists():
                self.folder.mkdir(parents=True)
            
            safe_staff_name = "".join([c for c in staff_name if c.isalnum() or c in " ._-"])
            path = self.folder / f"Staff_{safe_staff_name}_{ts}.html"
            
            in_cost = (total_input / 1000000) * 0.075 * 160
            out_cost = (total_output / 1000000) * 0.3 * 160
            total_yen = round(in_cost + out_cost, 2)
            cost_display = (
                "🎨 フォーマット再生成のみ（APIコスト無し）"
                if reformat_mode
                else f"💰 APIコスト概算: 約 {total_yen} 円 (In:{total_input} / Out:{total_output})"
            )
            

            def get_status_badge(st):
                s = st.lower()
                if any(k in s for k in ["未設定", "漏れ", "未定"]):
                    return f'<span style="background:#fee2e2; color:#ef4444; font-weight:bold; font-size:0.85em; padding:2px 6px; border-radius:4px;">{st}</span>'
                elif "完了" in s:
                    return f'<span style="background:#dcfce7; color:#16a34a; font-weight:bold; font-size:0.85em; padding:2px 6px; border-radius:4px;">{st}</span>'
                elif "遅延" in s:
                    return f'<span style="background:#fef08a; color:#a16207; font-weight:bold; font-size:0.85em; padding:2px 6px; border-radius:4px;">{st}</span>'
                else:
                    return f'<span style="background:#f1f5f9; color:#64748b; font-size:0.85em; padding:2px 6px; border-radius:4px;">{st}</span>'

            def _render_structured_items(items, th_idx_map, staff_prefix, is_top3=False):
                import html
                if not items: return ""
                html_list = []
                for item in items:
                    icon = item.get('status_icon', '⚪')
                    cat = html.escape(str(item.get('category', 'その他')))
                    pj = html.escape(str(item.get('project_scope', '横断業務')))
                    act = html.escape(str(item.get('action_type', '通知・共有')))
                    text = item.get("text", "")
                    
                    source_ids = item.get("source_thread_ids", [])
                    badges = ""
                    if isinstance(source_ids, list):
                        for tid in source_ids:
                            idx = th_idx_map.get(tid, "?")
                            badges += f' <a href="javascript:void(0)" onclick="event.stopPropagation(); jumpToThread(\'{staff_prefix}_{tid}\')" class="cite-badge" title="根拠スレッドへジャンプ">[{idx}]</a>'
                    
                    prefix_html = f'<span class="px-cat">[{cat}]</span><span class="px-proj" style="display:none;">[{pj}]</span><span class="px-act" style="display:none;">[{act}]</span>'
                    html_list.append(f'<li class="js-summary-item"><span class="status-icon">{icon}</span> <strong>{prefix_html}</strong> {text}{badges}</li>')
                return "".join(html_list)

            import html
            from urllib.parse import quote
            html_blocks = []
            for staff, data in summaries.items():
                staff_id = staff.replace(" ", "_").replace(".", "")
                safe_staff_name_js = staff.replace("'", "\\'")
                
                if data.get('_error'):
                    html_blocks.append(f'<div class="thread-card"><div class="t-head t-title">{staff} - エラー</div><div class="t-body">{data.get("summary")}</div></div>')
                    continue

                staff_know = knowledge.get('staffs', {}).get(staff, {})
                role = staff_know.get('role', '')
                bg = staff_know.get('background', '')
                master_hist = staff_know.get('master_history', '')
                formatted_hist = self._format_recent_history(staff_know.get('history_summary', ''))
                human_ans = staff_know.get('human_answers', '')
                
                ai_threads = data.get('threads', [])
                if report_mode == "adopted":
                    adopted_ids = set()
                    for section_key in ("manager_actions", "staff_status", "stalled_monitor"):
                        for item in data.get(section_key, []):
                            for tid in item.get("source_thread_ids", []):
                                adopted_ids.add(str(tid).strip().upper())
                    if adopted_ids:
                        ai_threads = [th for th in ai_threads if str(th.get('thread_id', '')).strip().upper() in adopted_ids]
                        print(f"[DEBUG] 軽量モード: {staff} -> {len(ai_threads)}件に絞り込み (採用ID: {len(adopted_ids)}件)")
                    else:
                        print(f"[DEBUG] 軽量モード: {staff} -> 採用IDなし、全スレッドで生成")
                target_threads, noise_threads = [], []
                for th in ai_threads:
                    cid = th.get('thread_id', '')
                    orig_t = orig_threads_map.get(staff, {}).get(cid, {})
                    latest_dt = orig_t.get('latest_date', datetime.min)
                    th['_entry_id'] = orig_t.get('latest_entry_id', '')
                    th['_ts_val'] = int(latest_dt.timestamp())
                    imp = th.get('importance', '中')
                    th['_imp_val'] = {"高": 0, "中": 1, "低": 2}.get(imp, 1)
                    if th.get('is_target', True): target_threads.append(th)
                    else: noise_threads.append(th)

                standard_sorted = sorted(target_threads, key=lambda x: (x['_imp_val'], -x['_ts_val']))
                th_id_to_index = {th.get('thread_id', ''): i + 1 for i, th in enumerate(standard_sorted)}

                if sort_order == "重要度順": 
                    target_threads.sort(key=lambda x: (x['_imp_val'], -x['_ts_val']))
                elif sort_order == "最新スレッド順": 
                    target_threads.sort(key=lambda x: x['_ts_val'], reverse=True)

                th_html = []
                for th in target_threads:
                    imp = th.get('importance', '中')
                    badge_col = '#f97316' if imp == '高' else '#10b981' if imp == '低' else '#eab308'
                    
                    _e = lambda x: html.escape(str(x))
                    cat, pj, act = _e(th.get('category', 'その他')), _e(th.get('project_scope', '横断業務')), _e(th.get('action_type', '通知・共有'))
                    
                    orig_th_id = th.get('thread_id', f'rand_{int(datetime.now().timestamp())}')
                    th_id = f"{staff_id}_{orig_th_id}"
                    
                    global_idx = th_id_to_index.get(orig_th_id, "?")
                    orig_t_info = orig_threads_map.get(staff, {}).get(orig_th_id, {})
                    orig_mails = orig_t_info.get('mails', [])
                    uid_latest = f"{th_id}_m{len(orig_mails) - 1}" if orig_mails else f"{th_id}_m0"
                    
                    orig_topic_encoded = quote(str(orig_t_info.get("topic", "")))
                    safe_topic = th.get("topic", "").replace("'", "\\'").replace('"', '&quot;')
                    
                    link_btn = f'<a href="http://localhost:{self.server_port}/open?id={th.get("_entry_id")}&topic={orig_topic_encoded}" target="_blank" onclick="event.stopPropagation();" style="font-size:0.75em; text-decoration:none; background:#eff6ff; color:#2563eb; padding:2px 8px; border-radius:12px; border:1px solid #bfdbfe; margin-left:10px;">Outlook</a>' if th.get("_entry_id") else ''
                    detail_btn = f'<button onclick="event.stopPropagation(); forceOpenThread(\'{th_id}\'); summarizeDetail(this, \'{th_id}\', \'{uid_latest}\', \'{safe_topic}\', \'{safe_staff_name_js}\', \'staff\', {self.server_port})" style="font-size:0.75em; background:#e0f2fe; color:#0369a1; border:1px solid #7dd3fc; border-radius:12px; padding:2px 8px; cursor:pointer; margin-left:10px;">📄 詳細</button>'
                    rule_btn = f'<button onclick="event.stopPropagation(); toggleRuleForm(\'{th_id}\')" style="font-size:0.75em; background:#fef3c7; color:#ea580c; border:1px solid #fdba74; border-radius:12px; padding:2px 8px; cursor:pointer; margin-left:10px;">🔄 学習</button>'
                    
                    acts_table = ""
                    if th.get('actions'):
                        rows = "".join([f'<tr style="border-bottom:1px solid #e2e8f0;"><td style="padding:8px; font-weight:bold;">{a.get("owner")}</td><td style="padding:8px;">{a.get("action")}</td><td style="padding:8px;">{get_status_badge(a.get("status", ""))}</td></tr>' for a in th.get('actions')])
                        acts_table = f'<div style="margin-bottom:15px;"><button onclick="event.stopPropagation(); toggleActions(this, \'acts-{th_id}\')" style="width:100%; text-align:left; font-weight:bold; cursor:pointer; background:#f8fafc; border:1px solid #cbd5e1; padding:6px 12px; border-radius:4px; font-size:0.85em;">▼ アクション ({len(th.get("actions"))}件)</button><div id="acts-{th_id}" style="display:none; background:#fff; border:1px solid #cbd5e1; border-top:none; padding:10px;"><table style="width:100%; border-collapse:collapse; font-size:0.95em;">{rows}</table></div></div>'

                    # ★変更★ 最新メール1件のみ生成（orig_mails[-1:]）
                    mail_items_html = []
                    for i, m in zip([len(orig_mails) - 1], orig_mails[-1:]):
                        uid = f"{th_id}_m{i}"
                        display_body = str(m.get('body', ''))  # ★変更★ 常に全文（最新メールのみのため条件不要）
                        mail_topic_encoded = quote(str(m.get("conversation_topic") or m.get("subject", "")))
                        item_link = f'<a href="http://localhost:{self.server_port}/open?id={m.get("entry_id")}&topic={mail_topic_encoded}" target="_blank" onclick="event.stopPropagation();" style="font-size:0.85em; text-decoration:none; color:#2563eb; margin-left:15px;">&#x1F680; Outlook</a>'
                        summary_btn = f'<div id="sum-{uid}" style="margin-bottom:8px;" onclick="event.stopPropagation();"><button onclick="summarizeSingleMail(this, \'{uid}\', \'{safe_topic}\', {self.server_port})" style="cursor:pointer; background:#fff; border:1px solid #cbd5e1; padding:4px 10px; border-radius:12px; font-size:0.85em;">✨ 要約</button></div>'
                        html_body_raw = m.get('html_body', '')
                        if html_body_raw:
                            import re
                            for img_cid, b64_data in m.get('inline_images', {}).items():
                                html_body_raw = re.sub(rf'src=["\'"]cid:{re.escape(img_cid)}.*?["\']', f'src="{b64_data}"', html_body_raw, flags=re.IGNORECASE)
                            body_render = f'<div id="m-body-wrapper-{uid}" style="display:none; margin-top:10px; padding-top:10px; border-top:1px dotted #cbd5e1;" onclick="event.stopPropagation();"><iframe id="iframe-{uid}" srcdoc="{html.escape(html_body_raw, quote=True)}" style="width:100%; min-height:450px; border:none;"></iframe></div>'
                        else:
                            clean_text = display_body.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
                            body_render = f'<div id="body-{uid}" class="mail-item-body" onclick="event.stopPropagation();" data-original="{clean_text}" style="display:none; margin-top:10px; padding-top:10px; border-top:1px dotted #cbd5e1; white-space:pre-wrap; font-size:0.9em;">{self._auto_link_text(clean_text)}</div>'
                        mail_items_html.append(f'<div style="border-left:3px solid #cbd5e1; padding:10px; background:#f8fafc; margin-top:10px; border-radius:4px;"><b>👤 {m.get("sender_name")}</b> <span style="font-weight:normal; margin-left:10px; color:#64748b;">{m.get("received")}</span> <button onclick="event.stopPropagation(); translateText(this, \'{uid}\', {self.server_port})" class="view-btn" style="font-size:0.8em; padding:2px 8px; margin-left:10px;">🌐 翻訳</button>{item_link}{summary_btn}<div><button onclick="event.stopPropagation(); toggleSingleMailBody(this, \'{uid}\')" style="cursor:pointer; background:none; border:none; text-decoration:underline; font-size:0.85em; color:#2563eb;">▼ 全文</button></div>{body_render}</div>')

                    th_html.append(f'''
                    <div class="thread-card js-thread" id="thread-body-{th_id}" onclick="toggleThreadCard('{th_id}')" data-imp="{th.get('_imp_val')}" data-date="{th.get('_ts_val')}" data-category="{cat}" data-project="{pj}" data-action="{act}" style="border-left:4px solid {badge_col}; padding:12px 15px; background:#fff; margin-bottom:12px; border-radius:6px; box-shadow:0 1px 3px rgba(0,0,0,0.1); cursor:pointer; transition:background 0.2s;">
                        <div style="display:flex; justify-content:space-between; align-items:center; gap:8px;">
                            <div style="display:flex; align-items:center; gap:6px; font-weight:bold; font-size:1.05em; min-width:0;">
                                <span class="cite-badge" style="vertical-align:baseline; flex-shrink:0;">[{global_idx}]</span>
                                <span style="overflow:hidden; text-overflow:ellipsis;">{th.get("topic")}</span>
                            </div>
                            <div style="display:flex; align-items:center; gap:5px; flex-shrink:0;">
                                <span class="badge-imp" style="background:{badge_col}; color:white; padding:2px 8px; border-radius:12px; font-size:0.7em; white-space:nowrap;">重要度:{imp}</span>
                                {link_btn}{rule_btn}{detail_btn}
                                <a href="#staff-top-{staff_id}" onclick="event.stopPropagation();" style="font-size:0.75em; color:#94a3b8; text-decoration:none; white-space:nowrap;" title="スタッフ先頭に戻る">↑ 戻る</a>
                            </div>
                        </div>
                        <div class="tag-row">
                            <span class="badge bg-cat">🏷️ {cat}</span> <span class="badge bg-proj">📁 {pj}</span> <span class="badge bg-act">⚡ {act}</span>
                        </div>
                        <div id="inner-thread-body-{th_id}" class="thread-accordion-body" style="display:none; margin-top:15px; border-top:1px dashed #cbd5e1; padding-top:15px;">
                            <div id="rule-form-{th_id}" onclick="event.stopPropagation();" style="display:none; background:#fffbeb; padding:10px; margin-bottom:15px; border-radius:6px; border:1px solid #fde68a;">
                                <select id="rule-sel-{th_id}"><option value="重要">重視</option><option value="無視">無視</option></select>
                                <input type="text" id="rule-txt-{th_id}"><button onclick="submitAiRule('{staff_id}', '{safe_staff_name_js}', 'staff', '{th_id}', {self.server_port}, this)">登録</button>
                            </div>
                            <div id="detail-{th_id}" style="display:none; margin-bottom:15px; padding:15px; border:2px solid #bae6fd; background:#f0f9ff; border-radius:6px; font-size:0.95em;" onclick="event.stopPropagation();"></div>
                            <div style="font-size:0.95em; margin-bottom:15px; line-height:1.6; color:#334155;">{th.get("summary")}</div>
                            {acts_table}
                            <div><button style="cursor:pointer; background:#fff; border:1px solid #cbd5e1; padding:6px 12px; border-radius:4px; font-size:0.85em; font-weight:bold;" onclick="event.stopPropagation(); toggleThreadMails(this, '{th_id}')">▲ 閉じる</button></div>
                            <div id="mails-{th_id}" style="display:block; margin-top:10px;" onclick="event.stopPropagation();">{"".join(mail_items_html)}</div>
                        </div>
                    </div>''')

                # V30修正: 新スキーマのキー名で読み込み
                act_html = _render_structured_items(data.get("manager_actions", []), th_id_to_index, staff_id, True)
                stat_html = _render_structured_items(data.get("staff_status", []), th_id_to_index, staff_id, True)
                stall_html = _render_structured_items(data.get("stalled_monitor", []), th_id_to_index, staff_id, True)

                html_blocks.append(f'''
                <div class="project-container" style="background:#fff; margin-bottom:30px; border-radius:10px; overflow:hidden; box-shadow:0 4px 6px rgba(0,0,0,0.05);">
                    <div id="staff-top-{staff_id}" style="padding:15px 20px; background:#f8fafc; border-bottom:1px solid #e2e8f0; scroll-margin-top:10px;"><div style="font-weight:bold; font-size:20px; color:#1e293b;">👤 {staff}</div></div>
                    <div style="padding:20px; background:#f3f4f6;">

                        <div class="summary-section" style="display:flex; flex-direction:column; gap:10px; margin-bottom:20px;">
                            <div class="summary-card" style="background:#fff; border-left:5px solid #ef4444; padding:15px; border-radius:8px;"><b>🔴 上司(あなた)の介入・承認が必要な事項</b><ul style="margin:5px 0 0 0; padding-left:20px;">{act_html}</ul></div>
                            <div class="summary-card" style="background:#fff; border-left:5px solid #eab308; padding:15px; border-radius:8px;"><b>🟡 停滞監視 (ボールを持ったまま止まっている案件)</b><ul style="margin:5px 0 0 0; padding-left:20px;">{stall_html}</ul></div>
                            <div class="summary-card" style="background:#fff; border-left:5px solid #3b82f6; padding:15px; border-radius:8px;"><b>🔵 スタッフの実績と次週予定</b><ul style="margin:5px 0 0 0; padding-left:20px;">{stat_html}</ul></div>
                        </div>      
      
                        <button onclick="toggleAnalysis('analysis-wrapper-{staff_id}', this, '▼ 分析を表示')" style="width:100%; text-align:left; font-weight:bold; padding:10px; cursor:pointer; background:#e0e7ff; border:1px solid #c7d2fe; border-radius:6px; color:#3730a3; margin-bottom:15px;">▼ 分析を表示</button>
                        <div id="analysis-wrapper-{staff_id}" class="js-analysis-wrapper" style="display:none; flex-direction:column;">
                            <div class="dashboard-panel" style="background:#f8fafc; padding:15px; border-radius:8px; border:1px solid #e2e8f0; margin-bottom:20px;"><b>📊 3軸連動ダッシュボード</b><div id="dash-counts-{staff_id}" class="dash-row" style="display:flex; flex-wrap:wrap; gap:8px; margin-top:10px;"></div></div>
                            <button onclick="toggleSection('threads-{staff_id}', this, '▼ スレッド詳細を表示 ({len(target_threads)}件)')" style="width:100%; text-align:left; font-weight:bold; padding:10px; cursor:pointer; background:#f1f5f9; border:1px solid #cbd5e1; border-radius:6px;">▼ スレッド詳細を表示 ({len(target_threads)}件)</button>
                            <div id="threads-{staff_id}" style="display:none; flex-direction:column; margin-top:10px;">
                                <div style="text-align:right; margin-bottom:10px;">
                                    <button onclick="toggleAllFilteredThreads('{staff_id}', this)" style="cursor:pointer; font-size:0.85em; padding:4px 12px; margin-right:8px; background:#fff; border:1px solid #cbd5e1; border-radius:4px;">▼ スレッド情報を表示</button>
                                    <button onclick="applyFilter('{staff_id}', '', '')" style="cursor:pointer; font-size:0.85em; padding:4px 12px; background:#f1f5f9; border:1px solid #cbd5e1; border-radius:4px;">すべての絞り込みを解除</button>
                                </div>
                                <div id="thread-container-inner-{staff_id}">{"".join(th_html)}</div>
                            </div>
                            <button onclick="toggleSection('qa-{staff_id}', this, '▼ AI質問と回答メモ')" style="width:100%; text-align:left; padding:10px; margin-top:10px; cursor:pointer; background:#fff7ed; border:1px solid #fed7aa; border-radius:6px; color:#c2410c; font-weight:bold;">▼ AI質問と回答メモ</button>
                            <div id="qa-{staff_id}" style="display:none; background:#fff7ed; padding:15px; border:1px solid #fed7aa; border-top:none;">
                                <textarea id="ta-{staff_id}" style="width:100%; min-height:80px; padding:10px;">{html.escape(human_ans)}</textarea>
                                <button onclick="saveAnswers('{safe_staff_name_js}', 'ta-{staff_id}', 'toast-{staff_id}', {self.server_port})" style="margin-top:10px; cursor:pointer; background:#ea580c; color:white; border:none; padding:6px 15px; border-radius:4px;">保存</button><span id="toast-{staff_id}" style="opacity:0; margin-left:15px;">✅</span>
                            </div>
                            <button onclick="toggleSection('know-{staff_id}', this, '▼ 🧠 スタッフ情報・過去知識')" style="width:100%; text-align:left; padding:10px; margin-top:10px; cursor:pointer; background:#f0fdfa; border:1px solid #bae6fd; border-radius:6px; color:#0369a1; font-weight:bold;">▼ 🧠 スタッフ情報・過去知識</button>
                            <div id="know-{staff_id}" style="display:none; padding:15px; background:#f0fdfa; border:1px solid #bae6fd; border-top:none;">
                                <div style="font-weight:bold; font-size:0.9em; margin-bottom:5px;">役割 (Role):</div><textarea id="role-{staff_id}" style="width:100%; min-height:50px;">{html.escape(role)}</textarea>
                                <div style="font-weight:bold; font-size:0.9em; margin:10px 0 5px 0;">背景 (Background):</div><textarea id="bg-{staff_id}" style="width:100%; min-height:50px;">{html.escape(bg)}</textarea>
                                <div style="font-weight:bold; font-size:0.9em; margin:10px 0 5px 0;">マスター経緯:</div><textarea id="master-{staff_id}" style="width:100%; min-height:100px;">{html.escape(master_hist)}</textarea>
                                <button onclick="saveStaffKnowledgeExt('{safe_staff_name_js}', 'role-{staff_id}', 'bg-{staff_id}', 'master-{staff_id}', 'toast-k-{staff_id}', {self.server_port}, this)" style="margin-top:10px; cursor:pointer; background:#0284c7; color:white; border:none; padding:6px 15px; border-radius:4px;">保存</button><span id="toast-k-{staff_id}" style="opacity:0; margin-left:15px;">✅</span>
                                <div style="margin-top:15px; font-size:0.9em; border-top:1px solid #cbd5e1; padding-top:10px;">{formatted_hist}</div>
                            </div>
                        </div>
                    </div>
                </div>''')

            js_css = self._get_common_js_and_css()

            sel_imp = 'selected' if sort_order == "重要度順" else ''
            sel_desc = 'selected' if sort_order == "最新スレッド順" else ''

            final_html = f"""<!DOCTYPE html>
            <html lang="ja">
            <head>
                <meta charset="UTF-8">
                {js_css}
                <style>
                    .cite-badge {{
                        font-size: 0.85em; color: #1a73e8; text-decoration: none; margin-left: 4px;
                        vertical-align: super; font-weight: bold; cursor: pointer;
                    }}
                    .cite-badge:hover {{ text-decoration: underline; }}
                </style>
                <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
            </head>
            <body>
            <div class="container">
            <div class="header"><div><h1 style="margin:0;">👤 {staff_name} 活動俯瞰レポート</h1><p style="margin:5px 0 0 0; opacity:0.8;">{date_range}</p></div>
                <div style="background:rgba(255,255,255,0.2); padding:10px; border-radius:8px;">
                    <label for="sortOrder" style="font-weight:bold; font-size:0.9em; margin-right:5px;">並び順:</label>
                    <select id="sortOrder" onchange="sortThreads()" style="padding:6px; border-radius:4px; border:none; font-weight:bold; color:#333;">
                        <option value="importance" {sel_imp}>重要度順</option>
                        <option value="date_desc" {sel_desc}>日時順（新しい順）</option>
                    </select>
                </div>
            </div>
            <div class="controls"><div style="margin-bottom:10px; font-weight:bold; color:#475569;">📊 表示切り替え（グループ化 & 接頭辞連動）</div><div class="btn-group">
                <button class="view-btn active" onclick="switchView('default', this)">🌟 標準（重要度順）</button>
                <button class="view-btn" onclick="switchView('category', this)">🏷️ 業務カテゴリ別</button>
                <button class="view-btn" onclick="switchView('project', this)">📁 プロジェクト別</button>
                <button class="view-btn" onclick="switchView('action', this)">⚡ アクション別</button>
                <button class="view-btn" style="margin-left:auto; background:#f1f5f9; border-color:#cbd5e1; color:#334155;" onclick="toggleAllAnalysisWrappers(this)">📂 全分析を展開</button>
            </div></div>
            {''.join(html_blocks)}<div style="text-align:right; margin-top:20px; font-size:0.9em; color:#64748b;">💰 APIコスト概算: 約 {total_yen} 円 (In:{total_input} / Out:{total_output})</div></div>
            <script>
                document.addEventListener('DOMContentLoaded', () => {{
                    if (typeof marked !== 'undefined') {{
                        document.querySelectorAll('.markdown-body').forEach(el => {{
                            const rawText = el.textContent || el.innerText;
                            el.innerHTML = marked.parse(rawText);
                        }});
                    }}
                    if (typeof renderDashboards === 'function') renderDashboards();
                    window.originalOrders = {{}};
                    document.querySelectorAll('[id^="thread-container-inner-"]').forEach(container => {{
                        window.originalOrders[container.id] = Array.from(container.children);
                    }});
                }});
            </script>
            </body></html>"""
            
            html_len = len(final_html)
            chunk_size = 500000 
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    for i in range(0, html_len, chunk_size):
                        f.write(final_html[i:i+chunk_size])
                return str(path)
            except Exception as write_err:
                if path.exists(): 
                    try: path.unlink()
                    except: pass
                raise write_err
                
        except Exception as e: 
            print(f"❌ Staff Report Error: {e}")
            return ""


    def generate_cockpit_report(self, data, cache_dict, total_input, total_output, reformat_mode=False) -> str:
        '''v20260528_02_03 Executive Cockpit HTML描画（Outlookボタン位置調整）'''
        try:
            from datetime import datetime
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            if not self.folder.exists():
                self.folder.mkdir(parents=True)

            path = self.folder / f"Executive_Cockpit_{ts}.html"

            in_cost = (total_input / 1000000) * 0.075 * 160
            out_cost = (total_output / 1000000) * 0.3 * 160
            total_yen = round(in_cost + out_cost, 2)
            cost_display = (
                "🎨 フォーマット再生成のみ（APIコスト無し）"
                if reformat_mode
                else f"💰 APIコスト概算: 約 {total_yen} 円 (In:{total_input} / Out:{total_output})"
            )

            cache_lookup = {}
            if isinstance(cache_dict, dict):
                for k, v in cache_dict.items():
                    cache_lookup[str(k).strip().upper()] = v

            def _normalize_tid(tid):
                return str(tid).strip().upper()

            def _safe_anchor_id(role_key, tid):
                raw = f"cockpit-thread-{role_key}-{tid}"
                return "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in raw)

            def _thread_lookup_from_map():
                lookup = {}
                thread_map = data.get("thread_data_map", {})
                if not isinstance(thread_map, dict):
                    return lookup
                for map_key, info in thread_map.items():
                    if not isinstance(info, dict):
                        continue
                    tid = _normalize_tid(str(map_key).split("_")[-1])
                    if tid and tid not in lookup:
                        lookup[tid] = info
                return lookup

            thread_lookup = _thread_lookup_from_map()

            def _get_thread_title(tid):
                tid_norm = _normalize_tid(tid)
                if tid_norm in cache_lookup:
                    return str(cache_lookup.get(tid_norm))
                info = thread_lookup.get(tid_norm, {})
                if isinstance(info, dict):
                    t_data = info.get("data", {})
                    if isinstance(t_data, dict):
                        for key_name in ["raw_topic", "conversation_topic", "subject", "topic"]:
                            val = t_data.get(key_name)
                            if val:
                                return str(val)
                return f"スレッド {tid_norm[:8]}"

            def _collect_role_thread_ids(role_data):
                ids = []
                if not isinstance(role_data, dict):
                    return ids
                for section_key in ["red_alerts", "blue_highlights", "yellow_stalled"]:
                    items = role_data.get(section_key, [])
                    if not isinstance(items, list):
                        continue
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        s_ids = item.get("source_thread_ids", [])
                        if not isinstance(s_ids, list):
                            continue
                        for tid in s_ids:
                            tid_norm = _normalize_tid(tid)
                            if tid_norm and tid_norm not in ids:
                                ids.append(tid_norm)
                return ids

            def _render_role_items(items, icon_str, role_key, citation_map):
                import html
                if not items:
                    return f'<li style="color:#94a3b8; font-size:0.9em; margin-bottom:8px;">(報告事項なし)</li>'
                res = []
                for d in items:
                    if not isinstance(d, dict):
                        continue

                    cat = html.escape(str(d.get('category', '状況把握')))
                    txt = html.escape(str(d.get('text', '')))
                    s_ids = d.get('source_thread_ids', [])
                    if not isinstance(s_ids, list):
                        s_ids = []

                    prefix_icons = ""
                    if d.get('duplicate_thread'):
                        prefix_icons += '<span title="他Viewにも同じ根拠スレッドあり" style="margin-right:3px;">🔁</span>'
                    if d.get('auto_filled'):
                        prefix_icons += '<span title="Python補完により追加" style="margin-right:3px;">🧩</span>'

                    badges = ""
                    for tid in s_ids:
                        tid_norm = _normalize_tid(tid)
                        if not tid_norm:
                            continue
                        cite_no = citation_map.get(tid_norm)
                        if not cite_no:
                            continue
                        topic = _get_thread_title(tid_norm)
                        anchor_id = _safe_anchor_id(role_key, tid_norm)
                        badges += f' <a href="javascript:void(0)" onclick="openEvidenceAndJump(\'{anchor_id}\', \'cockpit-evidence-{role_key}\')" class="cite-badge" title="{html.escape(str(topic))}">[{cite_no}]</a>'

                    res.append(
                        f'<li style="margin-bottom:8px; line-height:1.4;">'
                        f'<span style="margin-right:5px; font-size:1.1em;">{icon_str}</span> '
                        f'<strong style="color:#475569;">{prefix_icons}{cat}</strong> {txt}{badges}</li>'
                    )

                if not res:
                    return f'<li style="color:#94a3b8; font-size:0.9em; margin-bottom:8px;">(報告事項なし)</li>'
                return "".join(res)

            def _render_related_threads(role_key, role_data, citation_map, duplicate_tids):
                import html
                tids = _collect_role_thread_ids(role_data)
                if not tids:
                    return '<div style="color:#94a3b8; font-size:0.9em; padding:10px 0;">根拠スレッドなし</div>'
                cards = []
                for tid in tids:
                    cite_no = citation_map.get(tid)
                    if not cite_no:
                        continue
                    topic = _get_thread_title(tid)
                    info = thread_lookup.get(tid, {})
                    t_data = info.get("data", {}) if isinstance(info, dict) else {}
                    target_name = info.get("target_name", "") if isinstance(info, dict) else ""
                    source_file = info.get("source_file", "") if isinstance(info, dict) else ""
                    entry_id = info.get("latest_entry_id", "") if isinstance(info, dict) else ""
                    outlook_link = f'<a href="http://localhost:{self.server_port}/open?id={entry_id}" target="_blank" style="font-size:0.75em; text-decoration:none; background:#eff6ff; color:#2563eb; padding:2px 8px; border-radius:12px; border:1px solid #bfdbfe; margin-left:6px; white-space:nowrap;">🚀 Outlook</a>' if entry_id else ""
                    summary = ""
                    if isinstance(t_data, dict):
                        summary = str(t_data.get("summary") or t_data.get("text") or "")
                    if not summary:
                        summary = "この根拠スレッドの詳細表示は、今後のPhaseでStaff俯瞰テンプレートに合わせて拡張します。"
                    dup_icon = " 🔁" if tid in duplicate_tids else ""
                    anchor_id = _safe_anchor_id(role_key, tid)
                    cards.append(f'''
                            <div id="{anchor_id}" style="background:#fff; border:1px solid #cbd5e1; border-left:5px solid #64748b; border-radius:8px; padding:12px 14px; margin:10px 0; scroll-margin-top:20px;">
                                <div style="display:flex; align-items:flex-start; gap:8px;">
                                    <span class="cite-badge" style="vertical-align:baseline; margin-left:0;">[{cite_no}]</span>
                                    <div style="flex:1;">
                                        <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                                            <div style="font-weight:bold; color:#1e293b; line-height:1.4;">📩 {html.escape(str(topic))}{dup_icon}</div>
                                            <div style="display:flex; align-items:center; gap:4px;">
                                                {outlook_link}
                                                <a href="#view-summary-{role_key}" style="font-size:0.75em; color:#94a3b8; text-decoration:none; white-space:nowrap;" title="ダッシュボードに戻る">↑ 戻る</a>
                                            </div>
                                        </div>
                                        <div style="font-size:0.82em; color:#64748b; margin-top:4px;">
                                            ThreadID: {html.escape(str(tid))} / Target: {html.escape(str(target_name))} / Source: {html.escape(str(source_file))}
                                        </div>
                                        <div style="font-size:0.9em; color:#334155; margin-top:8px; line-height:1.5;">{html.escape(str(summary))}</div>
                                    </div>
                                </div>
                            </div>''')
                return "".join(cards) if cards else '<div style="color:#94a3b8; font-size:0.9em; padding:10px 0;">根拠スレッドなし</div>'

            roles = [
                ("site_manager_view", "🏢 Japan Site Manager View (Target: Kajikawa, 拠点全体)", "#f8fafc"),
                ("r19_pm_view", "🧭 R19 PM View", "#fff7ed"),
                ("pm_manager_view", "📊 PM (Project) Manager View (Target: Nakai, プロジェクト進捗)", "#f0f9ff"),
                ("te_pe_view", "🔧 TE / PE (Engineering) View (Target: Saji, Oi, Najib, 技術・歩留まり)", "#f0fdf4")
            ]

            role_citation_maps = {}
            tid_role_count = {}
            for key, title, bg_color in roles:
                role_data_for_map = data.get(key, {})
                if not isinstance(role_data_for_map, dict):
                    role_data_for_map = {}
                tids = _collect_role_thread_ids(role_data_for_map)
                role_citation_maps[key] = {tid: idx + 1 for idx, tid in enumerate(tids)}
                for tid in set(tids):
                    tid_role_count[tid] = tid_role_count.get(tid, 0) + 1
            duplicate_tids = {tid for tid, count in tid_role_count.items() if count > 1}

            html_blocks = []

            if data.get('_error'):
                html_blocks.append(f'<div style="color:red; font-weight:bold; padding:20px;">エラー: {data.get("summary")}</div>')
            else:
                for key, title, bg_color in roles:
                    role_data = data.get(key, {})
                    if not isinstance(role_data, dict):
                        role_data = {}

                    citation_map = role_citation_maps.get(key, {})
                    red_html    = _render_role_items(role_data.get("red_alerts", []),     "🔴", key, citation_map)
                    blue_html   = _render_role_items(role_data.get("blue_highlights", []),"🔵", key, citation_map)
                    yellow_html = _render_role_items(role_data.get("yellow_stalled", []), "🟡", key, citation_map)
                    related_threads_html = _render_related_threads(key, role_data, citation_map, duplicate_tids)

                    html_blocks.append(f'''
                    <div class="project-container" style="background:#fff; margin-bottom:30px; border-radius:10px; overflow:hidden; box-shadow:0 4px 6px rgba(0,0,0,0.05); border:1px solid #e2e8f0;">
                        <div style="padding:15px 20px; background:{bg_color}; border-bottom:1px solid #e2e8f0;">
                            <div style="font-weight:bold; font-size:18px; color:#1e293b;">{title}</div>
                        </div>
                        <div style="padding:20px; background:#fff;">
                            <div id="view-summary-{key}" class="summary-section" style="display:flex; flex-direction:column; gap:12px;">
                                <div class="summary-card" style="border-left:5px solid #ef4444; padding:15px; background:#fef2f2; border-radius:8px;">
                                    <b style="color:#b91c1c; font-size:1.05em;">🔴 即時介入・重大アラート</b>
                                    <ul style="margin:8px 0 0 0; padding-left:20px; list-style-type:none;">{red_html}</ul>
                                </div>
                                <div class="summary-card" style="border-left:5px solid #eab308; padding:15px; background:#fefce8; border-radius:8px;">
                                    <b style="color:#a16207; font-size:1.05em;">🟡 停滞監視・ボトルネック</b>
                                    <ul style="margin:8px 0 0 0; padding-left:20px; list-style-type:none;">{yellow_html}</ul>
                                </div>
                                <div class="summary-card" style="border-left:5px solid #3b82f6; padding:15px; background:#eff6ff; border-radius:8px;">
                                    <b style="color:#1d4ed8; font-size:1.05em;">🔵 戦略成果・ハイライト</b>
                                    <ul style="margin:8px 0 0 0; padding-left:20px; list-style-type:none;">{blue_html}</ul>
                                </div>
                            </div>
                            <button onclick="toggleSection('cockpit-evidence-{key}', this, '▼ 根拠スレッド一覧を表示')" style="margin-top:16px; cursor:pointer; background:#fff; border:1px solid #cbd5e1; padding:7px 12px; border-radius:6px; font-size:0.9em; font-weight:bold;">▼ 根拠スレッド一覧を表示</button>
                            <div id="cockpit-evidence-{key}" style="display:none; margin-top:12px; border-top:1px solid #e2e8f0; padding-top:12px;">
                                <div style="font-weight:bold; color:#334155; margin-bottom:8px;">📎 根拠スレッド一覧</div>
                                {related_threads_html}
                            </div>

                        </div>
                    </div>''')

            js_css = self._get_common_js_and_css()
            date_range = datetime.now().strftime('%Y/%m/%d %H:%M')

            final_html = f"""<!DOCTYPE html>
            <html lang="ja">
            <head>
                <meta charset="UTF-8">
                {js_css}
                <style>
                    .cite-badge {{ font-size: 0.85em; color: #1a73e8; text-decoration: none; margin-left: 4px; vertical-align: super; font-weight: bold; cursor: pointer; }}
                    .cite-badge:hover {{ text-decoration: underline; }}
                    body {{ background-color: #f1f5f9; }}
                </style>
            </head>
            <body>
            <div class="container" style="max-width:1000px;">
                <div class="header" style="background:linear-gradient(135deg, #0f172a, #334155); margin-bottom:30px; display:flex; justify-content:space-between; align-items:center;">
                    <div><h1 style="margin:0;">🚀 Executive Cockpit</h1><p style="margin:5px 0 0 0; opacity:0.8;">統括ダッシュボード (Generated: {date_range})</p></div>
                    <button onclick="closeAllEvidence()" style="background:rgba(255,255,255,0.15); color:#fff; border:1px solid rgba(255,255,255,0.4); padding:6px 12px; border-radius:6px; cursor:pointer; font-size:0.85em; white-space:nowrap;">📌 根拠スレッドをすべて閉じる</button>
                </div>
                {''.join(html_blocks)}
                <div style="text-align:right; margin-top:20px; margin-bottom:40px; font-size:0.9em; color:#64748b;">{cost_display}</div>
            </div>
            </body></html>"""

            with open(path, 'w', encoding='utf-8') as f:
                f.write(final_html)
            return str(path)
        except Exception as e:
            print(f"❌ Cockpit Report Error: {e}")
            return ""

    def _prepare_threads_data(self, data, orig_threads, sort_order):
        """スレッドのソート、重要度の正規化、および軽量モード判定を行う (V33: 2000年問題回避パッチ適用済)"""
        from datetime import datetime
        
        # AIの回答に含まれるスレッドリストを安全に取得（欠落時は空リスト）
        ai_threads_list = data.get('threads', [])
        
        # AIが稀にJSONの配列ではなく「辞書」で返してきた場合の救済措置
        if isinstance(ai_threads_list, dict):
            ai_threads_list = list(ai_threads_list.values())

        target_threads = []
        
        # 重要度の正規化マッピング（表記揺れを物理的に吸収）
        imp_map = {
            "高": 0, "high": 0, "High": 0,
            "中": 1, "medium": 1, "Medium": 1, "通常": 1, "normal": 1,
            "低": 2, "low": 2, "Low": 2
        }

        for th in ai_threads_list:
            # 防御的パース: 必須の thread_id がない場合はスキップして自爆を防ぐ
            th_id = th.get('thread_id', '')
            if not th_id:
                continue
            
            # 元データ（Outlook生データ）からタイムスタンプ等の付帯情報を取得
            orig_t = orig_threads.get(th_id, {})
            # 【V33 修正】Windowsの Errno 22 (マイナスタイムスタンプ) を防ぐため 2000/1/1 を最小値に設定
            latest_dt = orig_t.get('latest_date') or datetime(2000, 1, 1)
            
            # UI表示用の内部キー（_から始まるもの）をセット。欠落はデフォルト値でガード。
            th['_entry_id'] = orig_t.get('latest_entry_id', '')
            th['_ts_val'] = int(latest_dt.timestamp())
            
            # 重要度の正規化処理：AIが英語や異なる呼称を使っても内部数値(0-2)へ変換
            raw_imp = th.get('importance', '中')
            th['_imp_val'] = imp_map.get(raw_imp, 1) # 未知の文字列は「中(1)」扱い
            
            # UIのバッジ表示に不整合が起きないよう、正規化された日本語文字列を再セット
            normalized_imp_str = "高" if th['_imp_val'] == 0 else "中" if th['_imp_val'] == 1 else "低"
            th['importance'] = normalized_imp_str

            # ターゲット判定：明示的に is_target: false となっているノイズ以外を採用
            if th.get('is_target', True) is True: 
                target_threads.append(th)

        # 指定されたソート順に従って安定ソートを実行
        if sort_order == "重要度順":
            # 第1優先：重要度(0=高 -> 2=低)、第2優先：日付(新しい順)
            target_threads.sort(key=lambda x: (x.get('_imp_val', 1), -x.get('_ts_val', 0)))
        elif sort_order == "最新スレッド順":
            target_threads.sort(key=lambda x: x.get('_ts_val', 0), reverse=True)
        elif sort_order == "最古スレッド順":
            target_threads.sort(key=lambda x: x.get('_ts_val', 0))

        # 大量データ時の「軽量保護モード」判定（30件閾値）
        is_lightweight = len(target_threads) > 30
        
        return target_threads, is_lightweight

    def _build_thread_cards_html(self, target_threads, orig_threads, target_name, target_type, is_lightweight):
        """スレッドカードおよびメール履歴のHTML文字列を生成する"""
        import html
        import re
        from datetime import datetime
        from urllib.parse import quote
        
        th_html = []
        
        # UI全体で利用するJS用サニタイズ済みのターゲット名
        target_name_safe_js = str(target_name).replace("'", "\\'").replace('"', '&quot;')
        
        # 軽量モード時の警告表示
        if is_lightweight:
            th_html.append(
                f'<div style="margin-bottom:15px; padding:10px; background:#fff7ed; '
                f'border-left:4px solid #ea580c; color:#9a3412; font-size:0.9em; border-radius:4px;">'
                f'<b>⚠️ 軽量保護モード作動中</b><br>'
                f'スレッド数が閾値（30件）を超過したため、システムの安定性を優先し、メール本文と画像データの展開を制限しました。'
                f'詳細は「Outlook」リンクから確認してください。</div>'
            )

        for th in target_threads:
            imp = th.get('importance', '中')
            badge_col = '#f97316' if imp == '高' else '#10b981' if imp == '低' else '#eab308'
            th_id = th.get('thread_id', f'rand_{int(datetime.now().timestamp())}')
            
            # JS構文エラーを物理的に防ぐための完全サニタイズ
            raw_topic = str(th.get("topic", ""))
            safe_topic = html.escape(raw_topic).replace("'", "\\'").replace('"', '&quot;')
            topic_encoded = quote(raw_topic)
            
            # 1. アクションテーブルの構築
            acts_table = ""
            if th.get('actions'):
                rows = []
                for a in th.get('actions'):
                    owner = html.escape(a.get("owner", ""))
                    action = html.escape(a.get("action", ""))
                    status_badge = self._get_status_badge(a.get("status", ""))
                    deadline = html.escape(a.get("deadline", ""))
                    rows.append(
                        f'<tr style="border-bottom:1px solid #e2e8f0;">'
                        f'<td style="padding:8px; font-weight:bold;">{owner}</td>'
                        f'<td style="padding:8px;">{action}</td>'
                        f'<td style="padding:8px; white-space:nowrap;">{deadline}</td>'
                        f'<td style="padding:8px; white-space:nowrap;">{status_badge}</td>'
                        f'</tr>'
                    )
                
                acts_table = (
                    f'<div style="margin-bottom:15px;">'
                    f'<button onclick="event.stopPropagation(); toggleActions(this, \'acts-{th_id}\')" '
                    f'style="width:100%; text-align:left; font-weight:bold; cursor:pointer; background:#f8fafc; '
                    f'border:1px solid #cbd5e1; padding:6px 12px; border-radius:4px; font-size:0.85em; color:#334155;">'
                    f'▼ アクション ({len(th.get("actions"))}件)</button>'
                    f'<div id="acts-{th_id}" style="display:none; background:#fff; border:1px solid #cbd5e1; border-top:none; padding:10px;">'
                    f'<table style="width:100%; border-collapse:collapse; font-size:0.95em;">{"".join(rows)}</table>'
                    f'</div></div>'
                )

            # 2. メール履歴の構築
            mail_items_html = []
            orig_mails = orig_threads.get(th_id, {}).get('mails', [])
            
            for i, m in enumerate(orig_mails):
                uid = f"{th_id}_m{i}"
                item_link = f'<a href="http://localhost:{self.server_port}/open?id={m.get("entry_id")}" target="_blank" onclick="event.stopPropagation();" style="font-size:0.85em; text-decoration:none; color:#2563eb; margin-left:15px;">&#x1F680; Outlook</a>'
                
                # 個別メール用のUIボタン復元
                summary_btn = f'<div id="sum-{uid}" style="margin-bottom:8px;" onclick="event.stopPropagation();"><button onclick="summarizeSingleMail(this, \'{uid}\', \'{safe_topic}\', {self.server_port})" style="cursor:pointer; background:#fff; border:1px solid #cbd5e1; padding:4px 10px; border-radius:12px; font-size:0.85em;">✨ 要約</button></div>'
                translate_btn = f'<button onclick="event.stopPropagation(); translateText(this, \'{uid}\', {self.server_port})" class="view-btn" style="font-size:0.8em; padding:2px 8px; margin-left:10px;">🌐 翻訳</button>'
                
                content_render = ""
                # 軽量モード分岐：本文・画像の処理を完全スキップ
                if is_lightweight:
                    content_render = (
                        f'<div style="margin-top:5px; padding:8px; background:#f1f5f9; color:#64748b; '
                        f'font-size:0.85em; border-radius:4px; border:1px dashed #cbd5e1;">'
                        f'※ 本文省略モード：詳細はOutlookで確認してください。</div>'
                    )
                else:
                    html_body_raw = m.get('html_body', '')
                    if html_body_raw:
                        # インライン画像のBase64埋め込み
                        for img_cid, b64_data in m.get('inline_images', {}).items():
                            html_body_raw = re.sub(rf'src=["\']cid:{re.escape(img_cid)}.*?["\']', f'src="{b64_data}"', html_body_raw, flags=re.IGNORECASE)
                        content_render = (
                            f'<div id="m-body-wrapper-{uid}" style="display:none; margin-top:10px; padding-top:10px; border-top:1px dotted #cbd5e1;">'
                            f'<iframe id="iframe-{uid}" srcdoc="{html.escape(html_body_raw, quote=True)}" style="width:100%; min-height:450px; border:none; resize:vertical; overflow:auto;"></iframe>'
                            f'</div>'
                        )
                    else:
                        # プレーンテキストのオートリンク処理
                        clean_text = html.escape(str(m.get('body', '')))
                        content_render = (
                            f'<div id="body-{uid}" class="mail-item-body" onclick="event.stopPropagation();" '
                            f'data-original="{clean_text}" style="display:none; margin-top:10px; padding-top:10px; '
                            f'border-top:1px dotted #cbd5e1; white-space:pre-wrap; font-size:0.9em;">'
                            f'{self._auto_link_text(clean_text)}</div>'
                        )
                
                sender_safe = html.escape(m.get("sender_name", ""))
                mail_items_html.append(
                    f'<div style="border-left:3px solid #cbd5e1; padding:10px; background:#f8fafc; margin-top:10px; border-radius:4px;">'
                    f'<div style="display:flex; align-items:center; font-weight:bold; font-size:0.85em; color:#475569;">'
                    f'&#x1F464; {sender_safe} <span style="font-weight:normal; margin-left:10px; color:#64748b;">&#x1F4C5; {m.get("received")}</span>'
                    f'{translate_btn}'
                    f'<span style="margin-left:auto;">{item_link}</span></div>'
                    f'{summary_btn}'
                    f'<div style="margin-top:5px;"><button onclick="event.stopPropagation(); toggleSingleMailBody(this, \'{uid}\')" '
                    f'style="cursor:pointer; background:none; border:none; text-decoration:underline; font-size:0.85em; color:#2563eb; padding:0;">'
                    f'▼ 全文</button></div>{content_render}</div>'
                )

            # 3. スレッドカード全体の組み立て
            link_btn = f'<a href="http://localhost:{self.server_port}/open?id={th.get("_entry_id", "")}&topic={topic_encoded}" target="_blank" onclick="event.stopPropagation();" style="font-size:0.75em; text-decoration:none; background:#eff6ff; color:#2563eb; padding:2px 8px; border-radius:12px; border:1px solid #bfdbfe; margin-left:10px;">Outlook</a>' if th.get("_entry_id") else ''
            
            # スレッドごとのUIボタン復元
            uid_latest = f"{th_id}_m{len(orig_mails) - 1}" if orig_mails else f"{th_id}_m0"
            detail_btn = f'<button onclick="event.stopPropagation(); forceOpenThread(\'{th_id}\'); summarizeDetail(this, \'{th_id}\', \'{uid_latest}\', \'{safe_topic}\', \'{target_name_safe_js}\', \'{target_type}\', {self.server_port})" style="font-size:0.75em; background:#e0f2fe; color:#0369a1; border:1px solid #7dd3fc; border-radius:12px; padding:2px 8px; cursor:pointer; margin-left:10px;">📄 詳細</button>'
            rule_btn = f'<button onclick="event.stopPropagation(); toggleRuleForm(\'{th_id}\')" style="font-size:0.75em; background:#fef3c7; color:#ea580c; border:1px solid #fdba74; border-radius:12px; padding:2px 8px; cursor:pointer; margin-left:10px;">🔄 学習</button>'

            cat_safe = html.escape(th.get('category', 'その他'))
            proj_safe = html.escape(th.get('project_scope', '全体'))
            act_safe = html.escape(th.get('action_type', '通知'))
            sum_safe = html.escape(th.get("summary", ""))

            th_html.append(
                f'<div class="thread-card js-thread" onclick="toggleThreadCard(\'{th_id}\')" '
                f'data-imp="{th.get("_imp_val")}" data-date="{th.get("_ts_val")}" data-category="{cat_safe}" '
                f'data-project="{proj_safe}" data-action="{act_safe}" '
                f'style="border-left:4px solid {badge_col}; padding:12px 15px; background:#fff; margin-bottom:12px; '
                f'border-radius:6px; box-shadow:0 1px 3px rgba(0,0,0,0.1); cursor:pointer;">'
                
                f'<div style="font-weight:bold; font-size:1.05em; display:flex; align-items:center; flex-wrap:wrap; gap:5px;">'
                f'{html.escape(th.get("topic", ""))} <span class="badge-imp" style="background:{badge_col}; color:white; '
                f'padding:2px 8px; border-radius:12px; font-size:0.75em;">{imp}</span>{link_btn}{rule_btn}{detail_btn}</div>'
                
                f'<div class="tag-row">'
                f'<span class="badge bg-cat">🏷️ {cat_safe}</span> '
                f'<span class="badge bg-proj">📁 {proj_safe}</span> '
                f'<span class="badge bg-act">⚡ {act_safe}</span></div>'
                
                f'<div id="thread-body-{th_id}" class="thread-accordion-body" style="display:none; margin-top:15px; border-top:1px dashed #cbd5e1; padding-top:15px;">'
                
                f'<div id="rule-form-{th_id}" onclick="event.stopPropagation();" style="display:none; background:#fffbeb; padding:10px; margin-bottom:15px; border-radius:6px; border:1px solid #fde68a;">'
                f'<select id="rule-sel-{th_id}"><option value="重要">重視</option><option value="無視">無視</option></select>'
                f'<input type="text" id="rule-txt-{th_id}"><button onclick="submitAiRule(\'{target_name_safe_js}\', \'{target_name_safe_js}\', \'{target_type}\', \'{th_id}\', {self.server_port}, this)">登録</button>'
                f'</div>'
                
                f'<div id="detail-{th_id}" style="display:none; margin-bottom:15px; padding:15px; border:2px solid #bae6fd; background:#f0f9ff; border-radius:6px; font-size:0.95em;" onclick="event.stopPropagation();"></div>'
                
                f'<div style="font-size:0.95em; margin-bottom:15px; line-height:1.6; color:#334155;">{sum_safe}</div>'
                f'{acts_table}'
                f'<div><button style="cursor:pointer; background:#fff; border:1px solid #cbd5e1; padding:6px 12px; border-radius:4px; font-size:0.85em; font-weight:bold; color:#334155;" '
                f'onclick="event.stopPropagation(); toggleThreadMails(this, \'{th_id}\')">▼ 履歴 ({len(orig_mails)}件)</button></div>'
                f'<div id="mails-{th_id}" style="display:none; margin-top:10px;" onclick="event.stopPropagation();">{"".join(mail_items_html)}</div>'
                f'</div>'
                
                f'</div>'
            )
            
        return "".join(th_html)


    def generate_cockpit_v2_report(self, cockpit_data, total_input, total_output, reformat_mode=False) -> str:
        """統括コックピットv2(新コンセプト): 「メールを要約する」のではなく、プロジェクトの
        状態(勢い・沈黙)と、自分待ちの案件を解放スコア順に理由つきで見せるダッシュボード。
        cockpit_data は MailSummarizer.generate_cockpit_v2_data() の戻り値。
        既存の generate_cockpit_report / generate_action_dashboard_report とは独立した
        新規メソッドとして実装し、既存の統括コックピット出力には一切影響しない。"""
        import html as html_mod
        from urllib.parse import quote

        try:
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            if not self.folder.exists():
                self.folder.mkdir(parents=True)
            path = self.folder / f"CockpitV2_{ts}.html"

            in_cost = (total_input / 1000000) * 0.075 * 160
            out_cost = (total_output / 1000000) * 0.3 * 160
            total_yen = round(in_cost + out_cost, 2)
            cost_display = (
                "🎨 フォーマット再生成のみ（APIコスト無し）"
                if reformat_mode
                else f"💰 APIコスト概算: 約 {total_yen} 円 (In:{total_input} / Out:{total_output})"
            )

            projects = cockpit_data.get("projects", {})
            queue = cockpit_data.get("queue", [])
            generated_at = html_mod.escape(cockpit_data.get("generated_at", ""))

            # --- 生体信号カード ---
            vital_html = []
            for proj, v in projects.items():
                proj_safe = html_mod.escape(proj)
                prio = v.get("priority", "中")
                prio_col = {"高": "#d03b3b", "中": "#898781", "低": "#2a78d6"}.get(prio, "#898781")
                velocity = v.get("velocity", {})
                silence = v.get("silence", {})
                trend = velocity.get("trend", "→")
                stalled = silence.get("is_stalled", False)
                stall_badge = (
                    f'<span class="recon-badge rc-stall">🔴 沈黙 {silence.get("silence_days", 0)}日</span>'
                    if stalled else '<span class="recon-badge rc-ok">✅ 平常ペース</span>'
                )
                vital_html.append(f'''
                <div class="vcard">
                    <div class="vcard-top">
                        <span class="pname">{proj_safe}</span>
                        <span class="prio-chip" style="color:{prio_col};border-color:{prio_col};">優先度 {html_mod.escape(prio)}</span>
                        {stall_badge}
                    </div>
                    <div class="vcard-metrics">
                        <span class="vmetric"><b>{velocity.get("recent_count", 0)}</b>件/直近ウィンドウ {trend}</span>
                        <span class="vmetric"><b>{v.get("waiting_on_me_count", 0)}</b>自分待ち</span>
                    </div>
                </div>''')

            # --- 意思決定キュー ---
            import json as _json_mod

            def _render_queue_row(item, rank):
                cid_safe = html_mod.escape(item.get("conversation_id", ""), quote=True)
                topic_safe = html_mod.escape(item.get("topic", ""))
                proj_safe = html_mod.escape(item.get("project", ""))
                # Outlook側の件名検索には、AI要約タイトルではなく実際のメール件名(real_topic)を使う。
                # AI要約タイトルで検索するとOutlookの件名と一致せずスレッドに到達できないため
                # (generate_action_dashboard_reportの既存対応と同じ理由)。
                topic_encoded = quote(item.get("real_topic") or item.get("topic", ""))
                open_url = f'http://localhost:{self.server_port}/open?id={item.get("latest_entry_id","")}&topic={topic_encoded}'
                evi_link = (
                    f'<a class="q-evi" href="{open_url}" target="_blank">🚀 Outlookで開く</a>'
                    if item.get("latest_entry_id") else ''
                )
                # Actionタブと同様、件名テキスト自体もクリックするとOutlookのスレッド検索に飛べるようにする。
                if item.get("latest_entry_id"):
                    ask_html = f'<a class="q-ask" href="{open_url}" target="_blank" title="Outlookでこのスレッドを検索">{topic_safe}</a>'
                else:
                    ask_html = f'<span class="q-ask">{topic_safe}</span>'
                reasons_html = "".join(
                    f'<span class="reason">{html_mod.escape(r)}</span>' for r in item.get("reasons", [])
                )
                # action_keysをJSに渡し、「✅完了」「🙈無視」ボタンからActionタブと同じ
                # /update_action_status を(カード内の未完了アクション全件に対して)一括で叩けるようにする。
                keys_json = html_mod.escape(_json_mod.dumps(item.get("action_keys", [])), quote=True)
                rank_html = f'<div class="q-rank">{rank}</div>' if rank else '<div class="q-rank">・</div>'
                return f'''
                <div class="q-row" data-cid="{cid_safe}">
                    {rank_html}
                    <div class="q-body">
                        {ask_html}<span class="q-tag">{proj_safe}</span>
                        <div class="q-reasons">{reasons_html}</div>
                    </div>
                    <div class="q-right">
                        {evi_link}
                        <div class="q-score">解放スコア {item.get("score", 0)}</div>
                        <div class="q-done-btns">
                            <button class="q-done-btn q-done" onclick="cockpitCloseCard(this, '{cid_safe}', {keys_json}, 'done', {self.server_port})">✅完了</button>
                            <button class="q-done-btn q-ignore" onclick="cockpitCloseCard(this, '{cid_safe}', {keys_json}, 'ignored', {self.server_port})">🙈無視</button>
                        </div>
                    </div>
                </div>'''

            # 表示1: 解放スコア順(上位8件を展開表示、残りは畳んで件数のみ表示。取りこぼしゼロ)
            TOP_N = 8
            top_items = queue[:TOP_N]
            rest_count = max(len(queue) - TOP_N, 0)
            queue_score_html = [_render_queue_row(item, rank) for rank, item in enumerate(top_items, start=1)]
            if not queue_score_html:
                queue_score_html.append('<div class="q-empty">現在、自分待ちの案件はありません。</div>')
            more_html = (
                f'<div class="q-more">▸ 残り <b>{rest_count}件</b> を解放スコア順に保持中（畳んでいるだけ・取りこぼしゼロ）</div>'
                if rest_count > 0 else ''
            )

            # 表示2: プロジェクト別(各プロジェクト内は解放スコア順。全件表示、上位N件による打ち切りはしない)
            by_project = {}
            for item in queue:
                by_project.setdefault(item.get("project", ""), []).append(item)
            queue_project_html = []
            if by_project:
                for proj in projects.keys():
                    items_in_proj = by_project.get(proj, [])
                    if not items_in_proj:
                        continue
                    proj_safe = html_mod.escape(proj)
                    rows = "".join(_render_queue_row(item, None) for item in items_in_proj)
                    queue_project_html.append(f'''
                    <div class="q-project-group">
                        <div class="q-project-head">{proj_safe}<span class="q-project-count">{len(items_in_proj)}件</span></div>
                        {rows}
                    </div>''')
            if not queue_project_html:
                queue_project_html.append('<div class="q-empty">現在、自分待ちの案件はありません。</div>')

            html_content = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>統括コックピット v2</title>
<style>
:root{{ color-scheme: light;
  --page:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --border:rgba(11,11,11,0.10); --blue:#2a78d6;
  --good:#0ca30c; --serious:#ec835a; --critical:#d03b3b; --good-ink:#006300; --chip:#f0efec; }}
@media (prefers-color-scheme: dark){{ :root:where(:not([data-theme="light"])){{ color-scheme: dark;
  --page:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --border:rgba(255,255,255,0.10); --blue:#3987e5;
  --good-ink:#0ca30c; --chip:#2c2c2a; }} }}
:root[data-theme="dark"]{{ color-scheme: dark; --page:#0d0d0d; --surface:#1a1a19; --ink:#ffffff;
  --ink2:#c3c2b7; --muted:#898781; --grid:#2c2c2a; --border:rgba(255,255,255,0.10);
  --blue:#3987e5; --good-ink:#0ca30c; --chip:#2c2c2a; }}
*{{box-sizing:border-box;}}
body{{margin:0;background:var(--page);color:var(--ink);
  font-family:system-ui,-apple-system,"Segoe UI",sans-serif;line-height:1.5;}}
.wrap{{max-width:1180px;margin:0 auto;padding:20px 20px 60px;}}
.topbar{{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-bottom:6px;}}
h1{{font-size:1.5rem;margin:0;}}
.subtitle{{color:var(--ink2);font-size:.85rem;}}
.cost{{margin-left:auto;font-size:.78rem;color:var(--ink2);}}
.section-label{{font-size:.72rem;font-weight:700;letter-spacing:.08em;color:var(--muted);
  text-transform:uppercase;margin:26px 0 10px;}}
.vitals{{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px;}}
.vcard{{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:14px 15px;}}
.vcard-top{{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:6px;}}
.pname{{font-weight:700;font-size:.95rem;}}
.prio-chip{{font-size:.68rem;border:1px solid;border-radius:10px;padding:1px 7px;}}
.recon-badge{{font-size:.7rem;font-weight:700;padding:2px 7px;border-radius:6px;white-space:nowrap;margin-left:auto;}}
.rc-ok{{color:var(--good-ink);background:color-mix(in srgb,var(--good) 14%,transparent);}}
.rc-stall{{color:var(--critical);background:color-mix(in srgb,var(--critical) 14%,transparent);}}
.vcard-metrics{{display:flex;justify-content:space-between;font-size:.76rem;color:var(--ink2);margin-top:6px;}}
.vmetric b{{font-size:1.05rem;color:var(--ink);}}
.hero{{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:6px 4px;}}
.q-row{{display:grid;grid-template-columns:34px 1fr auto;gap:12px;align-items:center;
  padding:13px 16px;border-top:1px solid var(--grid);}}
.q-row:first-child{{border-top:none;}}
.q-rank{{font-size:1.3rem;font-weight:800;color:var(--blue);text-align:center;}}
.q-ask{{font-weight:650;color:var(--ink);text-decoration:none;}}
a.q-ask:hover{{text-decoration:underline;color:var(--blue);cursor:pointer;}}
.q-tag{{font-size:.7rem;color:var(--ink2);margin-left:8px;background:var(--chip);border-radius:5px;padding:1px 7px;}}
.q-reasons{{margin-top:6px;display:flex;flex-wrap:wrap;gap:6px;}}
.reason{{font-size:.72rem;color:var(--ink2);background:var(--chip);border:1px solid var(--border);
  border-radius:20px;padding:2px 9px;white-space:nowrap;}}
.q-right{{text-align:right;}}
.q-evi{{font-size:.74rem;color:var(--blue);text-decoration:none;white-space:nowrap;}}
.q-score{{font-size:.66rem;color:var(--muted);margin-top:4px;}}
.q-more{{padding:12px 16px;font-size:.8rem;color:var(--ink2);border-top:1px solid var(--grid);}}
.q-empty{{padding:20px;text-align:center;color:var(--muted);}}
.q-done-btns{{display:flex;justify-content:flex-end;gap:6px;margin-top:6px;}}
.q-done-btn{{font-size:.68rem;border:1px solid var(--border);border-radius:12px;padding:3px 9px;
  background:var(--chip);color:var(--ink2);cursor:pointer;white-space:nowrap;}}
.q-done-btn.q-done:hover{{background:color-mix(in srgb,var(--good) 18%,transparent);color:var(--good-ink);border-color:var(--good);}}
.q-done-btn.q-ignore:hover{{background:color-mix(in srgb,var(--muted) 22%,transparent);color:var(--ink);border-color:var(--muted);}}
.q-row.q-closed{{display:none;}}
.view-toggle{{display:flex;gap:8px;margin-bottom:10px;}}
.view-toggle-btn{{font-size:.78rem;font-weight:600;border:1px solid var(--border);border-radius:20px;
  padding:5px 14px;background:var(--surface);color:var(--ink2);cursor:pointer;}}
.view-toggle-btn.active{{background:var(--blue);color:#fff;border-color:var(--blue);}}
.q-project-group{{border-top:1px solid var(--grid);}}
.q-project-group:first-child{{border-top:none;}}
.q-project-head{{display:flex;align-items:center;gap:8px;font-weight:700;font-size:.85rem;
  padding:10px 16px 2px;color:var(--ink);}}
.q-project-count{{font-size:.68rem;font-weight:400;color:var(--muted);background:var(--chip);
  border-radius:10px;padding:1px 8px;}}
.footer-note{{font-size:.72rem;color:var(--muted);margin-top:18px;padding:12px 14px;
  background:var(--surface);border:1px dashed var(--border);border-radius:10px;}}
</style>
</head>
<body>
<div class="wrap">
  <div class="topbar">
    <h1>🎯 統括コックピット v2</h1>
    <span class="subtitle">{generated_at} 生成 ／ メールのみで判定（試験運用中）</span>
    <span class="cost">{cost_display}</span>
  </div>

  <div class="section-label">プロジェクトの生体信号（メール件数の増減・相対沈黙）</div>
  <div class="vitals">{"".join(vital_html) if vital_html else '<div class="q-empty">対象プロジェクトのデータがありません。</div>'}</div>

  <div class="section-label">今週あなたが動かす意思決定キュー（解放スコア順・理由つき）</div>
  <div class="view-toggle">
    <button id="viewBtnScore" class="view-toggle-btn active" onclick="cockpitSetView('score')">📊 解放スコア順</button>
    <button id="viewBtnProject" class="view-toggle-btn" onclick="cockpitSetView('project')">🗂️ プロジェクト別</button>
  </div>
  <div id="queue-score" class="hero">
    {"".join(queue_score_html)}
    {more_html}
  </div>
  <div id="queue-project" class="hero" style="display:none;">
    {"".join(queue_project_html)}
  </div>

  <div class="footer-note">
    解放スコア＝待っている人数・放置日数・催促回数・あなたの手動優先度・プロジェクト優先度・フラグ/Just Do Itの加重和（0〜100）。
    「自分待ち」は送信済みメールも参照し、スレッドの最後の発言者があなた自身でないことで判定しています。
    OneNote週次レポートとの照合は次フェーズで追加予定です。
  </div>
</div>
<script>
async function cockpitCloseCard(btn, cid, keys, progressValue, port) {{
    btn.disabled = true;
    try {{
        for (const key of keys) {{
            await fetch(`http://localhost:${{port}}/update_action_status`, {{
                method: 'POST', headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{action_key: key, progress: progressValue}})
            }});
        }}
    }} catch (e) {{ console.error(e); }}
    document.querySelectorAll(`.q-row[data-cid="${{cid}}"]`).forEach(row => row.classList.add('q-closed'));
}}
function cockpitSetView(mode) {{
    document.getElementById('queue-score').style.display = (mode === 'score') ? '' : 'none';
    document.getElementById('queue-project').style.display = (mode === 'project') ? '' : 'none';
    document.getElementById('viewBtnScore').classList.toggle('active', mode === 'score');
    document.getElementById('viewBtnProject').classList.toggle('active', mode === 'project');
}}
</script>
</body>
</html>"""

            with open(path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            return str(path)
        except Exception as e:
            print(f"Cockpit v2 Report Error: {e}")
            return ""

    def generate_action_dashboard_report(self, action_cards, date_range, total_input, total_output, reformat_mode=False) -> str:
        """
        アクションダッシュボード: 期間×自分宛て全体から抽出したアクション項目を、
        1スレッド=1カード(複数アクションがあれば束ねて表示)として一覧表示する。
        進捗(4択)・優先度(3択)・コメントはアクション単位でワンクリック/入力でその場保存され、
        完了/無視はデフォルトで非表示になる。R19Projタグ付きスレッドは専用フィルタで絞り込める。
        """
        import html as html_mod
        from urllib.parse import quote

        try:
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            if not self.folder.exists():
                self.folder.mkdir(parents=True)
            path = self.folder / f"ActionDashboard_{ts}.html"

            in_cost = (total_input / 1000000) * 0.075 * 160
            out_cost = (total_output / 1000000) * 0.3 * 160
            total_yen = round(in_cost + out_cost, 2)
            cost_display = (
                "🎨 フォーマット再生成のみ（APIコスト無し）"
                if reformat_mode
                else f"💰 APIコスト概算: 約 {total_yen} 円 (In:{total_input} / Out:{total_output})"
            )

            PROGRESS_LABELS = {"not_started": "未着手", "in_progress": "進行中", "done": "完了", "ignored": "無視"}
            PRIORITY_LABELS = {"": "—", "high": "★優先", "top": "★★最優先"}
            priority_rank = {"top": 2, "high": 1, "": 0}

            def card_sort_key(card):
                prios = [priority_rank.get(a.get("priority", ""), 0) for a in card.get("actions", [])]
                max_prio = max(prios) if prios else 0
                has_deadline = any((a.get("deadline") or "").strip() for a in card.get("actions", []))
                return (-max_prio, 0 if has_deadline else 1, -card.get("latest_ts", 0))

            # 並び順(初期表示): カード内の最大優先度(★★→★→空欄) → 締切の有無 → スレッド最終更新の新しい順
            sorted_cards = sorted(action_cards, key=card_sort_key)

            cards_html = []
            for card in sorted_cards:
                cid = card.get("conversation_id", "")
                topic_safe = html_mod.escape(card.get("topic", ""))
                cat_safe = html_mod.escape(card.get("category", "その他"))
                date_safe = html_mod.escape(card.get("latest_date_mmdd", ""))
                latest_ts = card.get("latest_ts", 0)
                unread_flag = "true" if card.get("has_unread") else "false"
                r19_flag = "true" if card.get("is_r19") else "false"
                imp = card.get("importance", "中")
                badge_col = '#f97316' if imp == '高' else '#10b981' if imp == '低' else '#eab308'
                # Outlook側の件名検索(show_thread_in_explorer)に使うため、AI要約タイトルではなく
                # 実際のメール件名(real_topic)をリンクに渡す。AI要約タイトルで検索すると
                # Outlookの件名と一致せずヒットしない。
                topic_encoded = quote(card.get("real_topic") or card.get("topic", ""))
                open_url = f'http://localhost:{self.server_port}/open?id={card.get("latest_entry_id","")}&topic={topic_encoded}'
                link_btn = (
                    f'<a class="card-outlook-btn" href="{open_url}" target="_blank">🚀 Outlook</a>'
                ) if card.get("latest_entry_id") else ''
                # タイトルクリック時も「🚀 Outlook」ボタンと全く同じURL(Outlookの件名検索)を開く。
                if card.get("latest_entry_id"):
                    topic_html = (
                        f'<a class="action-topic-text" href="{open_url}" target="_blank" '
                        f'title="Outlookでこのメールを検索">{topic_safe}</a>'
                    )
                else:
                    topic_html = f'<span class="action-topic-text">{topic_safe}</span>'
                r19_badge = '<span class="badge bg-r19">🧩 R19Proj</span>' if card.get("is_r19") else ''
                flag_badge = '<span class="badge bg-flag">🚩</span>' if card.get("is_flagged") else ''

                progresses_seen = set()
                priorities_seen = set()
                items_html = []
                for a in card.get("actions", []):
                    key = a["action_key"]
                    progress = a.get("progress", "not_started")
                    priority = a.get("priority", "")
                    comment = a.get("comment", "")
                    progresses_seen.add(progress)
                    priorities_seen.add(priority)

                    owner_safe = html_mod.escape(a.get("owner", "") or "(不明)")
                    target_safe = html_mod.escape(a.get("target", "") or "あなた")
                    action_safe = html_mod.escape(a.get("action", ""))
                    deadline_safe = html_mod.escape(a.get("deadline", ""))
                    comment_safe = html_mod.escape(comment, quote=True)
                    deadline_html = f'<span class="action-deadline">📅 {deadline_safe}</span>' if deadline_safe else ''

                    prog_btns = "".join(
                        f'<button data-val="{val}" class="prog-btn{" active" if progress == val else ""}" '
                        f'onclick="setActionProgress(this, \'{key}\', \'{val}\', {self.server_port})">{label}</button>'
                        for val, label in PROGRESS_LABELS.items()
                    )
                    prio_btns = "".join(
                        f'<button data-val="{val}" class="prio-btn{" active" if priority == val else ""}" '
                        f'onclick="setActionPriority(this, \'{key}\', \'{val}\', {self.server_port})">{label}</button>'
                        for val, label in PRIORITY_LABELS.items()
                    )

                    items_html.append(f'''
                    <div class="action-item" data-key="{key}" data-progress="{progress}" data-priority="{priority}">
                        <div class="action-item-detail"><b>{owner_safe}</b> → <b>{target_safe}</b>: {action_safe} {deadline_html}</div>
                        <div class="prog-btns">{prog_btns}</div>
                        <div class="action-comment-row">
                            <input type="text" class="action-comment" value="{comment_safe}" placeholder="コメント（進行中の状況メモなど）"
                                   onblur="updateActionComment(this, '{key}', {self.server_port})">
                        </div>
                        <div class="prio-btns">{prio_btns}</div>
                    </div>''')

                progresses_attr = ",".join(sorted(progresses_seen))
                priorities_attr = ",".join(sorted(priorities_seen))

                # 外側(.action-card)=未読既読バー(8px、重要度の2倍太さ)＋絞り込み・並び替え用のカード集約データ属性。
                # 内側(.card-inner)=重要度バー(4px)。ヘッダー行にカテゴリ/R19Projマーク/タイトル/日時/Outlookボタンをまとめ、
                # スレッド内の各アクションは.action-itemとして個別に進捗・優先度・コメントを持つ。
                cards_html.append(f'''
                <div class="action-card js-action" data-key="{cid}" data-ts="{latest_ts}" data-unread="{unread_flag}" data-r19="{r19_flag}" data-progresses="{progresses_attr}" data-priorities="{priorities_attr}">
                    <div class="card-inner" style="border-left:4px solid {badge_col};">
                        <div class="card-header">
                            <span class="action-cat-wrap"><span class="badge bg-cat">🏷️ {cat_safe}</span></span>
                            <span class="action-r19-wrap">{r19_badge}</span>
                            <span class="action-flag-wrap">{flag_badge}</span>
                            {topic_html}
                            <span class="action-date">{date_safe}</span>
                            {link_btn}
                        </div>
                        {"".join(items_html)}
                    </div>
                </div>''')

            final_html = f"""<!DOCTYPE html>
            <html lang="ja">
            <head>
                <meta charset="UTF-8">
                <style>
                :root {{ --primary:#2563eb; --bg:#e2e8f0; }}
                body {{ font-family:'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background:var(--bg); margin:0; padding:20px; color:#333; line-height:1.5; }}
                .container {{ max-width:1150px; margin:0 auto; }}
                .sticky-top {{ position:sticky; top:0; z-index:200; background:var(--bg); padding-top:4px; margin-top:-4px; }}
                .header {{ background:linear-gradient(135deg, var(--primary), #1d4ed8); color:#fff; padding:20px; border-radius:10px; margin-bottom:15px; box-shadow:0 4px 6px rgba(0,0,0,0.1); }}
                .controls {{ background:#f8fafc; padding:12px 15px; border-radius:8px; margin-bottom:20px; border:1px solid #e2e8f0; display:flex; align-items:center; gap:18px; flex-wrap:wrap; box-shadow:0 4px 6px rgba(0,0,0,0.08); }}
                .controls-break {{ flex-basis:100%; height:0; }}
                .filter-group {{ display:flex; align-items:center; gap:4px; }}
                .filter-label {{ font-weight:bold; font-size:0.85em; color:#475569; margin-right:2px; }}
                .filter-btn {{ padding:4px 10px; border:1px solid #cbd5e1; background:#fff; border-radius:12px; cursor:pointer; font-size:0.8em; color:#94a3b8; }}
                .filter-btn.active {{ background:#334155; color:#fff; border-color:#334155; }}
                #r19FilterBtn.active {{ background:#7c3aed; border-color:#7c3aed; }}
                #r19ExcludeFilterBtn.active {{ background:#dc2626; border-color:#dc2626; }}
                .badge {{ padding:2px 8px; border-radius:4px; font-size:11px; font-weight:bold; color:#fff; display:inline-block; }}
                .bg-cat {{ background:#6366f1; }}
                .bg-r19 {{ background:#7c3aed; }}
                .bg-flag {{ background:#fef2f2; border:1px solid #fecaca; }}
                .action-card {{ border-left:8px solid #cbd5e1; border-radius:6px; margin-bottom:10px; box-shadow:0 1px 3px rgba(0,0,0,0.08); overflow:hidden; }}
                .action-card[data-unread="true"] {{ border-left-color:#2563eb; }}
                .card-inner {{ background:#fff; }}
                .card-header {{ display:flex; align-items:center; gap:8px; padding:14px 16px 10px; }}
                .action-cat-wrap {{ display:inline-block; width:104px; flex-shrink:0; }}
                .action-r19-wrap {{ display:inline-block; width:88px; flex-shrink:0; }}
                .action-flag-wrap {{ display:inline-block; width:30px; flex-shrink:0; }}
                .action-topic-text {{ flex:1 1 auto; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-weight:bold; font-size:1.02em; color:#1e293b; text-decoration:none; cursor:pointer; }}
                a.action-topic-text:hover {{ text-decoration:underline; color:#2563eb; }}
                .action-date {{ flex-shrink:0; font-size:0.8em; color:#94a3b8; white-space:nowrap; font-weight:normal; }}
                .card-outlook-btn {{ flex-shrink:0; font-size:0.75em; text-decoration:none; background:#eff6ff; color:#2563eb; padding:3px 10px; border-radius:12px; border:1px solid #bfdbfe; white-space:nowrap; }}
                .action-item {{ display:grid; grid-template-columns: 1fr 235px; gap:6px 15px; align-items:center; padding:8px 16px 12px; border-top:1px dashed #e2e8f0; }}
                .action-item:first-of-type {{ border-top:1px solid #e2e8f0; }}
                .action-item-detail {{ font-size:0.95em; color:#334155; }}
                .action-deadline {{ margin-left:8px; font-size:0.85em; color:#b45309; }}
                .action-comment-row {{ display:flex; }}
                .action-comment {{ width:100%; box-sizing:border-box; padding:6px 8px; border:1px solid #cbd5e1; border-radius:4px; font-size:0.9em; }}
                .prog-btns, .prio-btns {{ display:flex; gap:4px; flex-wrap:wrap; }}
                .prog-btn, .prio-btn {{ padding:5px 10px; border:1px solid #cbd5e1; background:#fff; border-radius:12px; cursor:pointer; font-size:0.8em; color:#475569; }}
                .prog-btn.active {{ background:var(--primary); color:#fff; border-color:var(--primary); font-weight:bold; }}
                .prio-btn.active {{ background:#f59e0b; color:#fff; border-color:#f59e0b; font-weight:bold; }}
                </style>
            </head>
            <body>
            <div class="container">
                <div class="sticky-top">
                    <div class="header">
                        <h1 style="margin:0;">📋 アクションダッシュボード</h1>
                        <p style="margin:5px 0 0 0; opacity:0.8;">{date_range}</p>
                    </div>
                    <div class="controls">
                        <div class="filter-group">
                            <span class="filter-label">進捗:</span>
                            <button class="filter-btn filter-progress active" data-val="not_started" onclick="toggleFilterBtn(this)">未着手</button>
                            <button class="filter-btn filter-progress active" data-val="in_progress" onclick="toggleFilterBtn(this)">進行中</button>
                            <button class="filter-btn filter-progress" data-val="done" onclick="toggleFilterBtn(this)">完了</button>
                            <button class="filter-btn filter-progress" data-val="ignored" onclick="toggleFilterBtn(this)">無視</button>
                        </div>
                        <div class="controls-break"></div>
                        <div class="filter-group">
                            <span class="filter-label">プロジェクト:</span>
                            <button class="filter-btn" id="r19FilterBtn" onclick="toggleR19Filter('only')">🧩 R19Proj</button>
                            <button class="filter-btn" id="r19ExcludeFilterBtn" onclick="toggleR19Filter('exclude')">🚫 R19Proj以外</button>
                        </div>
                        <div class="filter-group">
                            <span class="filter-label">優先度:</span>
                            <button class="filter-btn filter-priority active" data-val="" onclick="toggleFilterBtn(this)">—</button>
                            <button class="filter-btn filter-priority active" data-val="high" onclick="toggleFilterBtn(this)">★優先</button>
                            <button class="filter-btn filter-priority active" data-val="top" onclick="toggleFilterBtn(this)">★★最優先</button>
                        </div>
                        <div class="filter-group">
                            <label for="actionSortOrder" class="filter-label">並び順:</label>
                            <select id="actionSortOrder" onchange="sortActionCards()">
                                <option value="priority" selected>優先度順（★★→★→空欄）</option>
                                <option value="progress">進捗順（未着手→進行中→完了→無視）</option>
                                <option value="date_desc">時系列順（新しい順）</option>
                                <option value="date_asc">時系列順（古い順）</option>
                            </select>
                        </div>
                        <span id="actionCountLabel" style="margin-left:auto; font-size:0.85em; color:#64748b;"></span>
                    </div>
                </div>
                <div id="actionList">{"".join(cards_html) if cards_html else '<div style="padding:20px; text-align:center; color:#64748b;">この期間、対応が必要なアクションは見つかりませんでした。</div>'}</div>
                <div style="text-align:right; margin-top:20px; font-size:0.9em; color:#64748b;">{cost_display}</div>
            </div>
            <script>
            async function updateActionStatusApi(key, payload, port) {{
                payload.action_key = key;
                try {{
                    await fetch(`http://localhost:${{port}}/update_action_status`, {{
                        method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify(payload)
                    }});
                }} catch (e) {{ console.error(e); }}
            }}
            function recomputeCardAggregates(card) {{
                const items = card.querySelectorAll('.action-item');
                const progresses = new Set();
                const priorities = new Set();
                items.forEach(it => {{ progresses.add(it.dataset.progress); priorities.add(it.dataset.priority); }});
                card.dataset.progresses = Array.from(progresses).join(',');
                card.dataset.priorities = Array.from(priorities).join(',');
            }}
            function setActionProgress(btn, key, val, port) {{
                const item = btn.closest('.action-item');
                item.dataset.progress = val;
                item.querySelectorAll('.prog-btn').forEach(b => b.classList.toggle('active', b.dataset.val === val));
                updateActionStatusApi(key, {{progress: val}}, port);
                recomputeCardAggregates(item.closest('.js-action'));
                applyActionFilters();
            }}
            function setActionPriority(btn, key, val, port) {{
                const item = btn.closest('.action-item');
                item.dataset.priority = val;
                item.querySelectorAll('.prio-btn').forEach(b => b.classList.toggle('active', b.dataset.val === val));
                updateActionStatusApi(key, {{priority: val}}, port);
                recomputeCardAggregates(item.closest('.js-action'));
                applyActionFilters();
            }}
            function updateActionComment(input, key, port) {{
                updateActionStatusApi(key, {{comment: input.value}}, port);
            }}
            function toggleFilterBtn(btn) {{
                btn.classList.toggle('active');
                applyActionFilters();
            }}
            let r19FilterMode = 'all';
            function toggleR19Filter(mode) {{
                r19FilterMode = (r19FilterMode === mode) ? 'all' : mode;
                document.getElementById('r19FilterBtn').classList.toggle('active', r19FilterMode === 'only');
                document.getElementById('r19ExcludeFilterBtn').classList.toggle('active', r19FilterMode === 'exclude');
                applyActionFilters();
            }}
            function applyActionFilters() {{
                const activeProgress = Array.from(document.querySelectorAll('.filter-progress.active')).map(b => b.dataset.val);
                const activePriority = Array.from(document.querySelectorAll('.filter-priority.active')).map(b => b.dataset.val);
                const allCards = document.querySelectorAll('.js-action');
                let visibleCardCount = 0;
                let visibleItemCount = 0;
                let totalItemCount = 0;
                allCards.forEach(card => {{
                    const r19Match = r19FilterMode === 'all' ? true
                        : r19FilterMode === 'only' ? (card.dataset.r19 === 'true')
                        : (card.dataset.r19 !== 'true');
                    let anyItemVisible = false;
                    card.querySelectorAll('.action-item').forEach(item => {{
                        totalItemCount++;
                        const itemMatch = r19Match
                            && activeProgress.includes(item.dataset.progress)
                            && activePriority.includes(item.dataset.priority);
                        item.style.display = itemMatch ? '' : 'none';
                        if (itemMatch) {{ anyItemVisible = true; visibleItemCount++; }}
                    }});
                    card.style.display = anyItemVisible ? '' : 'none';
                    if (anyItemVisible) visibleCardCount++;
                }});
                const label = document.getElementById('actionCountLabel');
                if (label) label.textContent = visibleItemCount + ' / ' + totalItemCount + ' 件を表示中（' + visibleCardCount + 'カード）';
            }}
            function sortActionCards() {{
                const order = document.getElementById('actionSortOrder').value;
                const container = document.getElementById('actionList');
                const cards = Array.from(container.querySelectorAll('.js-action'));
                const priorityRank = {{top: 2, high: 1, '': 0}};
                const progressRank = {{not_started: 0, in_progress: 1, done: 2, ignored: 3}};
                function maxPriority(card) {{
                    return Math.max(...(card.dataset.priorities || '').split(',').map(p => priorityRank[p] ?? 0));
                }}
                function minProgress(card) {{
                    return Math.min(...(card.dataset.progresses || '').split(',').map(p => progressRank[p] ?? 0));
                }}
                if (order === 'priority') {{
                    cards.sort((a, b) => maxPriority(b) - maxPriority(a));
                }} else if (order === 'progress') {{
                    cards.sort((a, b) => minProgress(a) - minProgress(b));
                }} else if (order === 'date_desc') {{
                    cards.sort((a, b) => parseInt(b.dataset.ts || '0') - parseInt(a.dataset.ts || '0'));
                }} else if (order === 'date_asc') {{
                    cards.sort((a, b) => parseInt(a.dataset.ts || '0') - parseInt(b.dataset.ts || '0'));
                }}
                cards.forEach(c => container.appendChild(c));
            }}
            document.addEventListener('DOMContentLoaded', applyActionFilters);
            </script>
            </body></html>"""

            with open(path, 'w', encoding='utf-8') as f:
                f.write(final_html)
            return str(path)
        except Exception as e:
            print(f"❌ Action Dashboard Report Error: {e}")
            return ""


    def _get_common_js_and_css(self):
        """共通のCSSスタイルとJavaScriptロジックを一元的に提供する"""
        return """
        <style>
        :root { --primary:#2563eb; --high:#f97316; --bg:#e2e8f0; }
        body { font-family:'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background:var(--bg); margin:0; padding:20px; color:#333; line-height:1.5; }
        .container { max-width:1200px; margin:0 auto; }
        .header { background:linear-gradient(135deg, var(--primary), #1d4ed8); color:#fff; padding:20px; border-radius:10px; margin-bottom:20px; display:flex; justify-content:space-between; align-items:center; box-shadow:0 4px 6px rgba(0,0,0,0.1); }
        .controls { background:#f8fafc; padding:15px; border-radius:8px; margin-bottom:20px; border:1px solid #e2e8f0; position:sticky; top:10px; z-index:100; box-shadow:0 4px 6px rgba(0,0,0,0.1); }
        .btn-group { display:flex; gap:10px; flex-wrap:wrap; }
        .view-btn { padding:8px 16px; border:1px solid #cbd5e1; background:#fff; border-radius:6px; cursor:pointer; font-size:14px; transition:all 0.2s; color: #475569; }
        .view-btn.active { background:var(--primary); color:#fff; border-color:var(--primary); font-weight:bold; }
        .tag-row { display:flex; gap:8px; margin:8px 0; flex-wrap:wrap; }
        .badge { padding:2px 8px; border-radius:4px; font-size:11px; font-weight:bold; color:#fff; display:inline-block; }
        .bg-cat { background:#6366f1; } 
        .bg-proj { background:#0ea5e9; } 
        .bg-act { background:#f59e0b; }
        .js-thread:hover { background:#fdfdfd !important; box-shadow:0 2px 5px rgba(0,0,0,0.15) !important; border-color:#bfdbfe !important; }
        .group-header { background:#e2e8f0; padding:8px 15px; border-radius:6px; margin:30px 0 15px 0; font-size:16px; font-weight:bold; color:#1e293b; border-left:4px solid #64748b; }
        .mail-item-body { font-family: 'Consolas', 'Monaco', monospace; }
        </style>
        
        <script>
        // アコーディオン制御
        function toggleThreadCard(id) { 
            const el = document.getElementById('inner-thread-body-' + id); 
            if (!el) return;
            el.style.display = (el.style.display === 'none' || el.style.display === '') ? 'block' : 'none'; 
        }

        function toggleActions(btn, id) { 
            const el = document.getElementById(id); 
            if (!el) return;
            const isHidden = (el.style.display === 'none' || el.style.display === ''); 
            el.style.display = isHidden ? 'block' : 'none'; 
            btn.textContent = (isHidden ? '▲ ' : '▼ ') + btn.textContent.replace(/^[▲▼] /, ''); 
        }

        function toggleThreadMails(btn, id) { 
            const el = document.getElementById('mails-' + id); 
            if (!el) return;
            const isHidden = (el.style.display === 'none' || el.style.display === '');
            el.style.display = isHidden ? 'block' : 'none'; 
            btn.textContent = isHidden ? '▲ 閉じる' : '▼ 履歴'; 
        }

        function toggleSingleMailBody(btn, id) { 
            const el = document.getElementById('body-' + id) || document.getElementById('m-body-wrapper-' + id); 
            if (!el) return;
            const isHidden = (el.style.display === 'none' || el.style.display === ''); 
            el.style.display = isHidden ? 'block' : 'none'; 
            btn.textContent = isHidden ? '▲ 閉じる' : '▼ 全文'; 
        }

        function toggleSection(id, btn, def) {
            const el = document.getElementById(id);
            if (!el) return;
            const isH = el.style.display === 'none';
            el.style.display = isH ? 'block' : 'none';
            btn.textContent = isH ? '▲ 閉じる' : def;
        }

        function closeAllEvidence() {
            const panels = document.querySelectorAll('[id^="cockpit-evidence-"]');
            panels.forEach(function(el) {
                if (el.style.display !== 'none') {
                    el.style.display = 'none';
                    const btn = el.previousElementSibling;
                    if (btn && btn.tagName === 'BUTTON') {
                        btn.textContent = '▼ 根拠スレッド一覧を表示';
                    }
                }
            });
        }

        function openEvidenceAndJump(anchorId, evidenceId) {
            const panel = document.getElementById(evidenceId);
            if (panel && panel.style.display === 'none') {
                panel.style.display = 'block';
                const btn = panel.previousElementSibling;
                if (btn && btn.tagName === 'BUTTON') {
                    btn.textContent = '▲ 閉じる';
                }
            }
            setTimeout(function() {
                const target = document.getElementById(anchorId);
                if (!target) return;
                target.scrollIntoView({ behavior: 'smooth', block: 'center' });
                target.style.transition = 'background 0.5s';
                const oldBg = target.style.background || '#fff';
                target.style.background = '#fef9c3';
                setTimeout(function() { target.style.background = oldBg; }, 1500);
            }, 100);
        }


        function toggleAnalysis(id, btn, def) {
            const el = document.getElementById(id);
            if (!el) return;
            const isH = el.style.display === 'none' || el.style.display === '';
            el.style.display = isH ? 'flex' : 'none';
            btn.textContent = isH ? '▲ 分析を閉じる' : def;
        }

        function jumpToThread(tid) {
            const target = document.getElementById('thread-body-' + tid);
            if (!target) return;

            // 親コンテナを探して必要なら開く
            const container = target.closest('.project-container');
            if (container) {
                const analysisWrapper = container.querySelector('.js-analysis-wrapper');
                const threadsSection = container.querySelector('[id^="threads-"]');
                
                // 分析ラッパーが閉じているなら開く
                if (analysisWrapper && (analysisWrapper.style.display === 'none' || analysisWrapper.style.display === '')) {
                    const btn = analysisWrapper.previousElementSibling;
                    toggleAnalysis(analysisWrapper.id, btn, '▼ 分析を表示');
                }
                // スレッド詳細セクションが閉じているなら開く
                if (threadsSection && (threadsSection.style.display === 'none' || threadsSection.style.display === '')) {
                    const btn = threadsSection.previousElementSibling;
                    toggleSection(threadsSection.id, btn, btn.textContent);
                }
            }

            // V07追加: スレッドの中身（アコーディオン）も確実に開く
            const inner = document.getElementById('inner-thread-body-' + tid);
            if (inner && (inner.style.display === 'none' || inner.style.display === '')) {
                inner.style.display = 'block';
            }

            // スムーズスクロール
            target.scrollIntoView({ behavior: 'smooth', block: 'center' });

            // 到達時のハイライト効果
            target.style.transition = 'background 0.5s';
            const oldBg = target.style.background;
            target.style.background = '#fff9c4';
            setTimeout(() => { target.style.background = oldBg; }, 1500);
        }

        function toggleAllAnalysisWrappers(btn) {
            const isOpening = btn.textContent.includes('展開');
            const wrappers = document.querySelectorAll('.js-analysis-wrapper');
            wrappers.forEach(w => {
                w.style.display = isOpening ? 'flex' : 'none';
                const prevBtn = w.previousElementSibling;
                if(prevBtn && prevBtn.tagName === 'BUTTON') {
                    prevBtn.textContent = isOpening ? '▲ 分析を閉じる' : '▼ 分析を表示';
                }
            });
            btn.textContent = isOpening ? '📂 全分析を折り畳む' : '📂 全分析を展開';
        }

        function forceOpenThread(thId) {
            const body = document.getElementById('inner-thread-body-' + thId);
            if(body) body.style.display = 'block';
        }

        function toggleAllFilteredThreads(idPrefix, btn) {
            const isOpening = btn.textContent.includes('▼');
            const cards = document.querySelectorAll('#thread-container-inner-' + idPrefix + ' .js-thread');
            cards.forEach(card => {
                if (card.style.display !== 'none') {
                    const body = card.querySelector('.thread-accordion-body');
                    if (body) body.style.display = isOpening ? 'block' : 'none';
                }
            });
            btn.textContent = isOpening ? '▲ スレッド情報を非表示' : '▼ スレッド情報を表示';
        }

        function toggleRuleForm(thId) { 
            const el = document.getElementById('rule-form-' + thId); 
            if(!el) return; 
            el.style.display = el.style.display === 'none' ? 'block' : 'none'; 
        }

        // 表示切り替え（グループ化）
        function switchView(type, btn) {
            document.querySelectorAll('.view-btn').forEach(b => b.classList.remove('active')); 
            btn.classList.add('active');
            
            // サマリ接頭辞の切り替え
            document.querySelectorAll('.js-summary-item').forEach(li => {
                li.querySelectorAll('.px-cat, .px-proj, .px-act').forEach(s => s.style.display = 'none');
                if (type === 'category') { const p = li.querySelector('.px-cat'); if(p) p.style.display = 'inline'; }
                else if (type === 'project') { const p = li.querySelector('.px-proj'); if(p) p.style.display = 'inline'; }
                else if (type === 'action') { const p = li.querySelector('.px-act'); if(p) p.style.display = 'inline'; }
            });
            
            document.querySelectorAll('.project-container').forEach(container => {
                const wrapper = container.querySelector('[id^="thread-container-inner-"]');
                if (!wrapper) return;
                
                if (!window.originalOrders) window.originalOrders = {};
                if (!window.originalOrders[wrapper.id]) {
                    window.originalOrders[wrapper.id] = Array.from(wrapper.children);
                }
                
                wrapper.innerHTML = '';
                if (type === 'default') { 
                    window.originalOrders[wrapper.id].forEach(c => wrapper.appendChild(c.cloneNode(true))); 
                } else {
                    const groups = {}; 
                    window.originalOrders[wrapper.id].forEach(c => { 
                        const val = c.getAttribute('data-' + type) || '未分類'; 
                        if (!groups[val]) groups[val] = []; 
                        groups[val].push(c.cloneNode(true)); 
                    });
                    
                    Object.keys(groups).sort().forEach(g => { 
                        const h = document.createElement('div'); 
                        h.className = 'group-header'; 
                        h.innerText = g + ' (' + groups[g].length + ')'; 
                        wrapper.appendChild(h); 
                        groups[g].forEach(c => wrapper.appendChild(c)); 
                    });
                }
            });
        }

        // 並び替え制御
        function sortThreads() {
            const val = document.getElementById('sortOrder').value;
            document.querySelectorAll('[id^="thread-container-inner-"]').forEach(wrapper => {
                const threads = Array.from(wrapper.querySelectorAll('.js-thread'));
                threads.sort((a, b) => {
                    if (val === 'importance') {
                        return parseInt(a.dataset.imp) - parseInt(b.dataset.imp) || parseInt(b.dataset.date) - parseInt(a.dataset.date);
                    }
                    return val === 'date_desc' ? parseInt(b.dataset.date) - parseInt(a.dataset.date) : parseInt(a.dataset.date) - parseInt(b.dataset.date);
                });
                threads.forEach(t => wrapper.appendChild(t));
            });
        }

        // ダッシュボードの集計と描画
        function renderDashboards() {
            const containers = document.querySelectorAll('[id^="thread-container-inner-"]');
            containers.forEach(container => {
                const idPrefix = container.id.replace('thread-container-inner-', '');
                const dashRow = document.getElementById('dash-counts-' + idPrefix);
                if (!dashRow) return;
                const threads = Array.from(container.children);
                const stats = { imp: {'高':0,'中':0,'低':0}, cat: {}, scope: {}, act: {} };
                threads.forEach(t => {
                    const impText = t.querySelector('.badge-imp')?.textContent.replace('重要度:','') || '中';
                    if(stats.imp[impText] !== undefined) stats.imp[impText]++;
                    const cat = t.dataset.category; if(cat) stats.cat[cat] = (stats.cat[cat] || 0) + 1;
                    const scp = t.dataset.project; if(scp) stats.scope[scp] = (stats.scope[scp] || 0) + 1;
                    const act = t.dataset.action; if(act) stats.act[act] = (stats.act[act] || 0) + 1;
                });
                let html = '';
                const b = (l, v, c, t) => `<span class="badge ${c}" style="cursor:pointer; margin-right:4px;" onclick="applyFilter('${idPrefix}', '${t}', '${v}')">${l}: ${v}</span>`;
                if (stats.imp['高'] > 0) html += `<span class="badge" style="background:#ef4444; cursor:pointer;" onclick="applyFilter('${idPrefix}', 'imp', '0')">重要: 高</span>`;
                Object.keys(stats.cat).forEach(k => html += b('分類', k, 'bg-cat', 'category'));
                Object.keys(stats.scope).forEach(k => html += b('範囲', k, 'bg-proj', 'project'));
                Object.keys(stats.act).forEach(k => html += b('行動', k, 'bg-act', 'action'));
                dashRow.innerHTML = html;
            });
        }

        function applyFilter(idPrefix, type, value) {
            const cards = document.querySelectorAll('#thread-container-inner-' + idPrefix + ' .js-thread');
            cards.forEach(card => {
                if (!type) card.style.display = '';
                else card.style.display = (card.getAttribute('data-' + type) === value) ? '' : 'none';
            });
            const section = document.getElementById('threads-' + idPrefix);
            if (section && section.style.display === 'none') {
                const btn = section.previousElementSibling; toggleSection('threads-' + idPrefix, btn, btn.textContent);
            }
            if(section) section.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }

        // AI非同期通信群
        async function summarizeDetail(btn, thId, uid, topic, targetName, type, port) {
            const container = document.getElementById('detail-'+thId);
            if (btn.dataset.loaded === 'true') { container.style.display = (container.style.display==='none'?'block':'none'); btn.textContent = (container.style.display==='none'?'📄 詳細':'📄 閉じる'); return; }
            btn.disabled = true; btn.textContent = "...";
            let body = document.getElementById('body-'+uid)?.dataset.original || document.getElementById('iframe-'+uid)?.contentDocument.body.innerText;
            try {
                const res = await fetch(`http://localhost:${port}/summarize_detail`, { method: 'POST', body: JSON.stringify({topic, body, target_type: type, target_name: targetName}) });
                const data = await res.json();
                if(data.points) {
                    container.innerHTML = '<b>■ 要点</b><ul>' + data.points.map(p=>`<li>${p}</li>`).join('') + '</ul><b>■ 推奨アクション</b><ul>' + (data.recommended_actions||[]).map(a=>`<li>${a}</li>`).join('') + '</ul>';
                    container.style.display = 'block'; btn.dataset.loaded = 'true'; btn.textContent = '📄 閉じる';
                }
            } catch (e) { console.error(e); }
            btn.disabled = false;
        }

        async function summarizeSingleMail(btn, uid, topic, port) { 
            const body = document.getElementById('body-'+uid)?.dataset.original || document.getElementById('iframe-'+uid)?.contentDocument.body.innerText; 
            try {
                const res = await fetch(`http://localhost:${port}/summarize_single`, { method: 'POST', body: JSON.stringify({topic, body}) }); 
                const data = await res.json(); 
                if(data.summary) document.getElementById('sum-'+uid).innerHTML = `💡 ${data.summary}`; 
            } catch (e) { console.error(e); }
        }

        function extractTextsFromIframe(doc) {
            const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT, null, false);
            let node, texts = []; while (node = walker.nextNode()) { if (node.nodeValue.trim()) texts.push(node.nodeValue); } return texts;
        }
        function applyTextsToIframe(doc, textsArr) {
            const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT, null, false);
            let node, i = 0; while (node = walker.nextNode()) { if (node.nodeValue.trim()) node.nodeValue = textsArr[i++]; }
        }

        async function translateText(btn, uid, port) {
            const iframe = document.getElementById('iframe-' + uid);
            if (iframe) {
                const doc = iframe.contentDocument;
                if (btn.getAttribute('data-state') === 'ja') { applyTextsToIframe(doc, JSON.parse(iframe.dataset.origTexts)); btn.textContent = "🌐 翻訳"; btn.setAttribute('data-state', 'en'); return; }
                if (iframe.dataset.transTexts) { applyTextsToIframe(doc, JSON.parse(iframe.dataset.transTexts)); btn.textContent = "英 原文"; btn.setAttribute('data-state', 'ja'); return; }
                const texts = extractTextsFromIframe(doc); iframe.dataset.origTexts = JSON.stringify(texts);
                try {
                    const res = await fetch(`http://localhost:${port}/translate_array`, { method: 'POST', body: JSON.stringify({ texts }) });
                    const data = await res.json();
                    if(data.translated) { iframe.dataset.transTexts = JSON.stringify(data.translated); applyTextsToIframe(doc, data.translated); btn.textContent = "英 原文"; btn.setAttribute('data-state', 'ja'); }
                } catch (e) { console.error(e); }
            } else {
                const el = document.getElementById('body-'+uid); 
                if (btn.getAttribute('data-state') === 'ja') { el.innerText = el.dataset.original; btn.textContent = "🌐 翻訳"; btn.setAttribute('data-state', 'en'); return; }
                try {
                    const res = await fetch(`http://localhost:${port}/translate`, { method: 'POST', body: JSON.stringify({text: el.dataset.original}) });
                    const data = await res.json(); 
                    if(data.translated) { el.innerText = data.translated; btn.textContent = "英 原文"; btn.setAttribute('data-state', 'ja'); }
                } catch (e) { console.error(e); }
            }
        }

        async function saveAnswers(name, taId, toastId, port) { 
            try {
                const idPrefix = taId.replace('ta-', '');
                const isStaff = document.getElementById('role-' + idPrefix) !== null;
                const payload = isStaff ? {staff: name, human_answers: document.getElementById(taId).value} : {project: name, human_answers: document.getElementById(taId).value};
                const res = await fetch(`http://localhost:${port}/update_knowledge`, { method: 'POST', body: JSON.stringify(payload) }); 
                if(res.ok) { const t = document.getElementById(toastId); if(t) { t.style.opacity = 1; setTimeout(()=>t.style.opacity=0, 2000); } }
            } catch (e) { console.error(e); }
        }

        async function regenerateQuestions(idPrefix, name, port, btn) {
            btn.disabled = true; const origText = btn.textContent; btn.textContent = '...';
            try {
                const ctx = document.getElementById('ctx-'+idPrefix)?.textContent || '';
                const qlist = document.getElementById('qlist-'+idPrefix);
                const ex = Array.from(qlist.querySelectorAll('li')).map(li => li.textContent.replace(/^Q\\d+\\.\\s*/, ''));
                const res = await fetch(`http://localhost:${port}/generate_questions`, { method: 'POST', body: JSON.stringify({target: name, context: ctx, existing_questions: ex}) });
                const data = await res.json();
                if(data.new_questions) {
                    data.new_questions.forEach(q => {
                        const li = document.createElement('li'); li.style.marginBottom = '6px';
                        li.innerHTML = `<b>Q.</b> ${q}`; qlist.appendChild(li);
                    });
                }
            } catch (e) { console.error(e); }
            btn.textContent = origText; btn.disabled = false;
        }

        async function submitAiRule(name, safeName, type, thId, port, btn) {
            const val = document.getElementById('rule-sel-'+thId).value + ': ' + document.getElementById('rule-txt-'+thId).value;
            if(!document.getElementById('rule-txt-'+thId).value) return;
            btn.disabled = true; btn.textContent = '...';
            try {
                await fetch(`http://localhost:${port}/update_ai_rules`, { method: 'POST', body: JSON.stringify({type: type, target: safeName, rule: val}) });
                btn.textContent = '完了'; setTimeout(()=> { btn.disabled = false; btn.textContent='登録'; document.getElementById('rule-txt-'+thId).value=''; }, 2000);
            } catch(e) { console.error(e); btn.disabled = false; btn.textContent='エラー'; }
        }

        async function saveStaffKnowledgeExt(staff, rId, bId, mId, tId, port, btn) { 
            if(btn) btn.disabled = true;
            try {
                const res = await fetch(`http://localhost:${port}/update_knowledge`, { method: 'POST', body: JSON.stringify({staff, role: document.getElementById(rId).value, background: document.getElementById(bId).value, master_history: document.getElementById(mId).value}) }); 
                if(res.ok) { const t = document.getElementById(tId); if(t) { t.style.opacity = 1; setTimeout(()=>t.style.opacity=0, 2000); } }
            } catch (e) { console.error(e); }
            if(btn) btn.disabled = false;
        }

        // 知識更新の非同期保存
        async function saveProjectKnowledge(proj, mId, tId, port, btn) {
            if(btn) btn.disabled = true; 
            try { 
                const res = await fetch(`http://localhost:${port}/update_knowledge`, { 
                    method: 'POST', 
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({project: proj, master_history: document.getElementById(mId).value}) 
                }); 
                if (res.ok) { 
                    const t = document.getElementById(tId); 
                    if(t) { t.style.opacity = 1; setTimeout(() => t.style.opacity = 0, 2000); }
                } 
            } catch (e) {
                console.error(e);
            } finally { 
                if(btn) btn.disabled = false; 
            }
        }
        </script>
        """
        
# ============================================================
# GUI
# ============================================================



class MailManagerGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("📧 Outlook メールマネージャー v4.0")
        self.root.geometry("1100x750")
        
        self.config = load_config()
        self.excluded_domains = load_excluded_domains()
        self.project_knowledge = load_project_knowledge()
        
        self.server_port = start_local_server()
        self.outlook = OutlookMailManager()
        self.summarizer = MailSummarizer(self.config['gemini_api_key'], self.config['gemini_model'])
        self.reporter = HTMLReportGenerator(self.config['output_folder'], self.server_port)
        
        self.threads = {}
        self.selected = set()
        
        # タイマー用の変数
        self.start_time = 0
        self.is_running = False
        
        menu = tk.Menu(self.root)
        self.root.config(menu=menu)
        sm = tk.Menu(menu, tearoff=0)
        menu.add_cascade(label="設定", menu=sm)
        sm.add_command(label="APIキー", command=self._set_api)

        fm = tk.Menu(menu, tearoff=0)
        menu.add_cascade(label="ファイル管理", menu=fm)
        fm.add_command(label="📁 レポート管理", command=self._open_file_manager)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.tab_search = ttk.Frame(self.notebook)
        self.tab_project = ttk.Frame(self.notebook)
        self.tab_staff = ttk.Frame(self.notebook)
        self.tab_cockpit = ttk.Frame(self.notebook)
        self.tab_action = ttk.Frame(self.notebook)

        self.notebook.add(self.tab_search, text="🔍 検索 / 整理")
        self.notebook.add(self.tab_project, text="📊 プロジェクト俯瞰")
        self.notebook.add(self.tab_staff, text="👤 スタッフ俯瞰")
        self.notebook.add(self.tab_cockpit, text="🚀 統括コックピット") # 追加
        self.notebook.add(self.tab_action, text="📋 アクション") # 追加(アクションダッシュボード)

        self._ui_search_tab()
        self._ui_project_tab()
        self._ui_staff_tab()
        self._ui_cockpit_tab() # 追加
        self._ui_action_tab() # 追加(アクションダッシュボード)
        
        self.lbl_stat = ttk.Label(self.root, text="Ready", relief="sunken", padding=2)
        self.lbl_stat.pack(side=tk.BOTTOM, fill=tk.X)

        if self.outlook.connect():
            self.lbl_stat.config(text=f"Ready (User: {self.outlook.user_name})")
        
        if not self.config['gemini_api_key']:
            messagebox.showwarning("!", "APIキー設定が必要です")
            
        self._load_cats()
        self._check_open_queue()

    def _set_status(self, text, start_timer=False):
        if start_timer:
            self.start_time = time.time()
            self.is_running = True
            self._update_timer()
        else:
            self.is_running = False
        self.lbl_stat.config(text=text)
        self.root.update_idletasks()

    def _update_timer(self):
        if not self.is_running:
            return
        elapsed = int(time.time() - self.start_time)
        base_text = self.lbl_stat.cget("text").split(" (")[0]
        self.lbl_stat.config(text=f"{base_text} ({elapsed}秒経過)")
        self.root.after(1000, self._update_timer)

    def _check_open_queue(self):
        try:
            while True:
                req = outlook_request_queue.get_nowait()
                if isinstance(req, tuple) and len(req) == 3:
                    req_type, eid, topic = req
                    if req_type == 'open_thread' and topic:
                        threading.Thread(target=self.outlook.show_thread_in_explorer, args=(topic, eid), daemon=True).start()
                    elif req_type == 'open_item' and eid:
                        self.outlook.open_mail_item(eid)
                elif req:
                    self.outlook.open_mail_item(req)
        except queue.Empty:
            pass
        self.root.after(100, self._check_open_queue)




    def _ui_search_tab(self):
        main = ttk.Frame(self.tab_search, padding=10)
        main.pack(fill=tk.BOTH, expand=True)
        
        sf = ttk.LabelFrame(main, text="🔍 検索 / 📢 広告抽出", padding=10)
        sf.pack(fill=tk.X, pady=5)
        
        f1 = ttk.Frame(sf)
        f1.pack(fill=tk.X)
        
        ttk.Label(f1, text="件名:").pack(side=tk.LEFT)
        self.e_sub = ttk.Entry(f1, width=25)
        self.e_sub.pack(side=tk.LEFT, padx=5)
        
        ttk.Label(f1, text="送信者:").pack(side=tk.LEFT)
        self.e_snd = ttk.Entry(f1, width=20)
        self.e_snd.pack(side=tk.LEFT, padx=5)
        
        ttk.Label(f1, text="期間:").pack(side=tk.LEFT)
        self.v_prd = tk.StringVar(value="24H")
        ttk.Combobox(f1, textvariable=self.v_prd, values=["任意時間(h)", "12H", "24H", "今日", "3日間", "1週間", "2週間", "1ヶ月", "2ヶ月", "3ヶ月"], width=12, state="readonly").pack(side=tk.LEFT)
        
        self.spin_search_h = tk.Spinbox(f1, from_=1, to=1000, width=5)
        self.spin_search_h.pack(side=tk.LEFT, padx=2)
        self.spin_search_h.delete(0, tk.END)
        self.spin_search_h.insert(0, "1")
        ttk.Label(f1, text="h").pack(side=tk.LEFT)
        
        self.v_unread = tk.BooleanVar(value=False)
        ttk.Checkbutton(f1, text="未読のみ", variable=self.v_unread).pack(side=tk.LEFT, padx=5)
        
        self.v_all_me = tk.BooleanVar(value=False)
        self.chk_all = ttk.Checkbutton(f1, text="ALL", variable=self.v_all_me, command=self._on_all_toggled)
        self.chk_all.pack(side=tk.LEFT, padx=3)
        
        self.v_to_me = tk.BooleanVar(value=False)
        self.chk_to = ttk.Checkbutton(f1, text="To:Me", variable=self.v_to_me)
        self.chk_to.pack(side=tk.LEFT, padx=3)
        
        self.v_with_me = tk.BooleanVar(value=False)
        self.chk_with = ttk.Checkbutton(f1, text="With:Me", variable=self.v_with_me)
        self.chk_with.pack(side=tk.LEFT, padx=3)
        
        self.v_cc_me = tk.BooleanVar(value=False)
        self.chk_cc = ttk.Checkbutton(f1, text="CC:Me", variable=self.v_cc_me)
        self.chk_cc.pack(side=tk.LEFT, padx=3)
        
        f2 = ttk.Frame(sf)
        f2.pack(fill=tk.X, pady=5)
        
        ttk.Label(f2, text="分類:").pack(side=tk.LEFT)
        self.v_cat = tk.StringVar(value="(すべて)")
        self.c_cat = ttk.Combobox(f2, textvariable=self.v_cat, width=15)
        self.c_cat.pack(side=tk.LEFT, padx=5)
        
        ttk.Label(f2, text="フォルダ:").pack(side=tk.LEFT)
        self.e_fld = ttk.Combobox(f2, width=15)
        self.e_fld.pack(side=tk.LEFT, padx=5)
        
        ttk.Label(f2, text="本文KW:").pack(side=tk.LEFT)
        self.e_kwd = ttk.Entry(f2, width=20)
        self.e_kwd.pack(side=tk.LEFT, padx=5)
        
        ttk.Label(f2, text="フラグ:").pack(side=tk.LEFT)
        self.v_flag = tk.StringVar(value="(指定なし)")
        self.c_flag = ttk.Combobox(f2, textvariable=self.v_flag, values=["(指定なし)", "フラグあり", "フラグなし"], width=10, state="readonly")
        self.c_flag.pack(side=tk.LEFT, padx=5)
        
        self.v_strict = tk.BooleanVar(value=False)
        ttk.Checkbutton(f2, text="厳密検索", variable=self.v_strict).pack(side=tk.LEFT, padx=5)
        
        # V20.1修正: pack(side=tk.RIGHT) は先に書いたものほど右に来るため順序を調整
        self.btn_search = ttk.Button(f2, text="🔍 通常検索", command=self._search)
        self.btn_search.pack(side=tk.RIGHT, padx=5)

        self.btn_refresh = ttk.Button(f2, text="🔄 表示更新", command=self._refresh_display)
        self.btn_refresh.pack(side=tk.RIGHT, padx=5)

        self.btn_external = ttk.Button(f2, text="外部メール", command=self._search_external)
        self.btn_external.pack(side=tk.RIGHT, padx=5)

        self.btn_ad = ttk.Button(f2, text="📢 広告抽出", command=self._search_ad)
        self.btn_ad.pack(side=tk.RIGHT, padx=5)

        self.btn_rss = ttk.Button(f2, text="📰 RSS抽出", command=self._search_rss)
        self.btn_rss.pack(side=tk.RIGHT, padx=5)
        
        lf = ttk.LabelFrame(main, text="📋 一覧", padding=5)
        lf.pack(fill=tk.BOTH, expand=True)
        
        cols = ("sel", "cat", "top", "cnt", "who", "date", "fld", "flg")
        self.tree = ttk.Treeview(lf, columns=cols, show="headings")
        
        try:
            base_font = tkfont.nametofont("TkDefaultFont")
            bold_font = tkfont.Font(**base_font.configure())
            bold_font.configure(weight="bold")
        except:
            bold_font = None

        self.tree.tag_configure("tome_unread", foreground="red", font=bold_font)
        self.tree.tag_configure("tome_read", foreground="red", background="#f0f0f0")
        self.tree.tag_configure("withme_unread", foreground="green", font=bold_font)
        self.tree.tag_configure("withme_read", foreground="green", background="#f0f0f0")
        self.tree.tag_configure("other_unread", font=bold_font)
        self.tree.tag_configure("other_read", background="#f0f0f0")
        self.tree.tag_configure("checked", background="#b3d9ff")
        
        self.tree.heading("sel", text="✓", command=lambda: self._sort_tree("sel", False))
        self.tree.column("sel", width=40, anchor="center")
        self.tree.heading("cat", text="分類", command=lambda: self._sort_tree("cat", False))
        self.tree.column("cat", width=100)
        self.tree.heading("top", text="トピック", command=lambda: self._sort_tree("top", False))
        self.tree.column("top", width=380)
        self.tree.heading("cnt", text="数", command=lambda: self._sort_tree("cnt", False))
        self.tree.column("cnt", width=40, anchor="center")
        self.tree.heading("who", text="送信者", command=lambda: self._sort_tree("who", False))
        self.tree.column("who", width=180)
        self.tree.heading("date", text="日時", command=lambda: self._sort_tree("date", False))
        self.tree.column("date", width=120, anchor="center")
        self.tree.heading("fld", text="フォルダ", command=lambda: self._sort_tree("fld", False))
        self.tree.column("fld", width=120)
        self.tree.heading("flg", text="🚩", command=lambda: self._sort_tree("flg", False))
        self.tree.column("flg", width=40, anchor="center")
        
        sc = ttk.Scrollbar(lf, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sc.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sc.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.tree.bind("<ButtonRelease-1>", self._click)
        self.tree.bind("<Double-1>", self._on_tree_double_click)
        self.tree.bind("<Control-q>", self._on_ctrl_q)
        
        bf = ttk.Frame(main)
        bf.pack(fill=tk.X, pady=5)
        
        self.btn_all_read = ttk.Button(bf, text="■全選択既読", command=self._all_and_mark_read, state="disabled")
        self.btn_all_read.pack(side=tk.LEFT, padx=(0, 5))
        
        ttk.Button(bf, text="☑ 全選択", command=self._all).pack(side=tk.LEFT)
        ttk.Button(bf, text="☐ 解除", command=self._none).pack(side=tk.LEFT, padx=5)
        
        f_right = ttk.Frame(bf)
        f_right.pack(side=tk.RIGHT)
        
        self.btn_gen = ttk.Button(f_right, text="📊 レポート", command=self._gen, state="disabled")
        self.btn_gen.pack(side=tk.TOP, fill=tk.X)
        
        f_limit = ttk.Frame(f_right)
        f_limit.pack(side=tk.TOP, pady=(2,0))
        ttk.Label(f_limit, text="過去ﾒｰﾙ上限:").pack(side=tk.LEFT)
        self.v_past_limit = tk.StringVar(value="800文字(推奨)")
        self.c_past_limit = ttk.Combobox(f_limit, textvariable=self.v_past_limit, values=["800文字(推奨)", "1000文字", "2000文字", "3000文字", "無制限"], state="readonly", width=14)
        self.c_past_limit.pack(side=tk.LEFT)
        
        self.btn_excl = ttk.Button(bf, text="🛡️ 除外登録", command=self._register_exclude, state="disabled")
        self.btn_excl.pack(side=tk.RIGHT, padx=10)
        self.btn_jd_read = ttk.Button(bf, text="🗑️ 迷削既読", command=self._mark_junk_deleted_read)
        self.btn_jd_read.pack(side=tk.RIGHT, padx=10)
        self.btn_read = ttk.Button(bf, text="📩 既読にする", command=self._mark_read, state="disabled")
        self.btn_read.pack(side=tk.RIGHT, padx=10)
        self.btn_remove_flag = ttk.Button(bf, text="🏳️ フラグ解除", command=self._remove_flags, state="disabled")
        self.btn_remove_flag.pack(side=tk.RIGHT, padx=10)
        self.btn_mark_unread = ttk.Button(bf, text="📨 未読にする", command=self._mark_unread, state="disabled")
        self.btn_mark_unread.pack(side=tk.RIGHT, padx=10)
        self.btn_promo = ttk.Button(bf, text="📦 Promotionへ移動", command=self._move_to_promo, state="disabled")
        self.btn_promo.pack(side=tk.RIGHT, padx=10)


    def _click(self, e):
        col_id = self.tree.identify_column(e.x)
        item_id = self.tree.identify_row(e.y)
        if not item_id: return
        
        if col_id == "#8":
            self._toggle_thread_flag(item_id)
            return

        # Idea 1: チェックボックス列(#1)をクリックした時のみトグルするように修正
        if col_id == "#1":
            if item_id in self.selected:
                self.selected.remove(item_id)
                self.tree.set(item_id, "sel", "☐")
                self.tree.item(item_id, tags=self._row_tags(item_id))
            else:
                self.selected.add(item_id)
                self.tree.set(item_id, "sel", "☑")
                self.tree.item(item_id, tags=self._row_tags(item_id))
            self._chk_btns()

    def _on_ctrl_q(self, event=None):
        """Ctrl+Q押下時に、ハイライトされている行をチェックし既読にする"""
        selection = self.tree.selection() # ハイライトされている行を取得
        if not selection: return
        
        # 1. 選択されている全アイテムを「チェック状態」にする
        for item_id in selection:
            if item_id not in self.selected:
                self.selected.add(item_id)
                self.tree.set(item_id, "sel", "☑")
                self.tree.item(item_id, tags=self._row_tags(item_id))
        
        # 2. ボタンの状態を更新
        self._chk_btns()
        
        # 3. 既読処理（既存の _mark_read）を呼び出す
        self._mark_read()

    def _on_all_toggled(self):
        import tkinter as tk
        if self.v_all_me.get():
            self.v_to_me.set(False)
            self.v_with_me.set(False)
            self.v_cc_me.set(False)
            self.chk_to.config(state=tk.DISABLED)
            self.chk_with.config(state=tk.DISABLED)
            self.chk_cc.config(state=tk.DISABLED)
        else:
            self.chk_to.config(state=tk.NORMAL)
            self.chk_with.config(state=tk.NORMAL)
            self.chk_cc.config(state=tk.NORMAL)

    def _ui_project_tab(self):
        main = ttk.Frame(self.tab_project, padding=20)
        main.pack(fill=tk.BOTH, expand=True)

        lbl_title = ttk.Label(main, text="【 プロジェクト分析・サマリ生成 】", font=("", 14, "bold"))
        lbl_title.pack(anchor=tk.W, pady=(0, 10))

        f_proj = ttk.LabelFrame(main, text="📂 対象プロジェクト", padding=10)
        f_proj.pack(fill=tk.X, pady=5)
        
        self._updating_checks = False
        self.var_proj_all = tk.BooleanVar(value=True)
        self.var_proj_caracal = tk.BooleanVar(value=True)
        self.var_proj_wheeling = tk.BooleanVar(value=True)
        self.var_proj_grandteton = tk.BooleanVar(value=True)
        self.var_proj_r19projects = tk.BooleanVar(value=True)

        def on_all(*args):
            if self._updating_checks: return
            self._updating_checks = True
            v = self.var_proj_all.get()
            self.var_proj_caracal.set(v)
            self.var_proj_wheeling.set(v)
            self.var_proj_grandteton.set(v)
            self.var_proj_r19projects.set(v)
            self._updating_checks = False

        def on_item(*args):
            if self._updating_checks: return
            self._updating_checks = True
            if (self.var_proj_caracal.get() and self.var_proj_wheeling.get()
                    and self.var_proj_grandteton.get() and self.var_proj_r19projects.get()):
                self.var_proj_all.set(True)
            else:
                self.var_proj_all.set(False)
            self._updating_checks = False

        self.var_proj_all.trace_add("write", on_all)
        self.var_proj_caracal.trace_add("write", on_item)
        self.var_proj_wheeling.trace_add("write", on_item)
        self.var_proj_grandteton.trace_add("write", on_item)
        self.var_proj_r19projects.trace_add("write", on_item)
        
        ttk.Checkbutton(f_proj, text="ALL", variable=self.var_proj_all).pack(side=tk.LEFT, padx=10)
        ttk.Checkbutton(f_proj, text="00_Caracal", variable=self.var_proj_caracal).pack(side=tk.LEFT, padx=10)
        ttk.Checkbutton(f_proj, text="01_Wheeling", variable=self.var_proj_wheeling).pack(side=tk.LEFT, padx=10)
        ttk.Checkbutton(f_proj, text="02_GrandTeton", variable=self.var_proj_grandteton).pack(side=tk.LEFT, padx=10)
        ttk.Checkbutton(f_proj, text="03_R19Projects", variable=self.var_proj_r19projects).pack(side=tk.LEFT, padx=10)

        f_period = ttk.Frame(main)
        f_period.pack(fill=tk.X, pady=10)
        
        ttk.Label(f_period, text="📅 抽出期間:").pack(side=tk.LEFT, padx=(0, 10))
        self.var_proj_period = tk.StringVar(value="過去1週間")
        ttk.Combobox(f_period, textvariable=self.var_proj_period, values=["任意時間(h)", "12H", "24H", "3日間", "過去1週間", "過去2週間", "過去1ヶ月", "過去3ヶ月"], state="readonly", width=12).pack(side=tk.LEFT)
        
        self.spin_proj_h = tk.Spinbox(f_period, from_=1, to=1000, width=5)
        self.spin_proj_h.pack(side=tk.LEFT, padx=2)
        self.spin_proj_h.delete(0, tk.END)
        self.spin_proj_h.insert(0, "1")
        ttk.Label(f_period, text="h").pack(side=tk.LEFT)
        
        self.var_proj_unread = tk.BooleanVar(value=False)
        ttk.Checkbutton(f_period, text="未読のみ", variable=self.var_proj_unread).pack(side=tk.LEFT, padx=(10, 0))
        
        ttk.Label(f_period, text="並び順:").pack(side=tk.LEFT, padx=(20, 10))
        self.var_proj_sort = tk.StringVar(value="重要度順")
        ttk.Combobox(f_period, textvariable=self.var_proj_sort, values=["重要度順", "最新スレッド順", "最古スレッド順"], state="readonly", width=15).pack(side=tk.LEFT)

        f_know = ttk.LabelFrame(main, text="🧠 過去知識 (Memory) と インタラクティブ更新", padding=10)
        f_know.pack(fill=tk.X, pady=10)
        
        btn_edit_know = ttk.Button(f_know, text="✎ 役割とマスター経緯を編集", command=self._open_knowledge_editor)
        btn_edit_know.pack(anchor=tk.W, pady=5)
        
        ttk.Label(f_know, text="※ レポート生成時にAIが各プロジェクトの最新履歴を自動更新します。\n※ HTMLレポート上でもマスター経緯の編集やAIへの回答を直接保存できます。").pack(anchor=tk.W)

        f_run = ttk.Frame(main)
        f_run.pack(fill=tk.X, pady=30)
        # ── レポートモード選択ラジオボタン ─────────────────────────────────────
        self.var_proj_report_mode = tk.StringVar(value="adopted")
        f_mode = ttk.Frame(f_run)
        f_mode.pack(anchor=tk.CENTER, pady=(0, 8))
        ttk.Radiobutton(f_mode, text="🎯 AI採用スレッドのみ（軽量）", variable=self.var_proj_report_mode, value="adopted").pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(f_mode, text="📋 全スレッド（詳細）", variable=self.var_proj_report_mode, value="all").pack(side=tk.LEFT, padx=10)
        btn_run = ttk.Button(f_run, text="🚀 プロジェクト俯瞰レポートを生成", command=self._run_project_overview)
        btn_run.pack(anchor=tk.CENTER, ipadx=20, ipady=10)

        _proj_reformat_init = tk.NORMAL if os.path.exists(PROJECT_LAST_RESULT_FILE) else tk.DISABLED
        self.btn_reformat_project = ttk.Button(
            f_run, text="🎨 フォーマットのみ再生成",
            command=self._reformat_project,
            state=_proj_reformat_init
        )
        self.btn_reformat_project.pack(anchor=tk.CENTER, pady=(6, 0))
        

    def _ui_staff_tab(self):
        main = ttk.Frame(self.tab_staff, padding=20)
        main.pack(fill=tk.BOTH, expand=True)

        lbl_title = ttk.Label(main, text="【 スタッフ活動分析・サマリ生成 】", font=("", 14, "bold"))
        lbl_title.pack(anchor=tk.W, pady=(0, 10))

        f_staff = ttk.LabelFrame(main, text="👤 対象スタッフ", padding=10)
        f_staff.pack(fill=tk.X, pady=5)
        
        ttk.Label(f_staff, text="スタッフ名:").pack(side=tk.LEFT)
        self.var_staff_name = tk.StringVar()
        staff_list = list(self.project_knowledge.get("staffs", {}).keys())
        self.cb_staff_name = ttk.Combobox(f_staff, textvariable=self.var_staff_name, values=staff_list, width=25)
        self.cb_staff_name.pack(side=tk.LEFT, padx=10)
        
        # V14追加: ハードコードされた複数選択用チェックボックスと排他制御
        f_staff_multi = ttk.Frame(f_staff)
        f_staff_multi.pack(side=tk.LEFT, padx=20)
        
        self.var_sm_all = tk.BooleanVar(value=True)
        self.var_sm_taizo = tk.BooleanVar(value=True)
        self.var_sm_nakai = tk.BooleanVar(value=True)
        self.var_sm_kajikawa = tk.BooleanVar(value=True)
        self.var_sm_saji = tk.BooleanVar(value=True)
        self.var_sm_oi = tk.BooleanVar(value=True)
        self.var_sm_najib = tk.BooleanVar(value=True)
        
        self._updating_sm_checks = False
        def on_sm_all(*args):
            if self._updating_sm_checks: return
            self._updating_sm_checks = True
            v = self.var_sm_all.get()
            for var in [self.var_sm_taizo, self.var_sm_nakai, self.var_sm_kajikawa, self.var_sm_saji, self.var_sm_oi, self.var_sm_najib]:
                var.set(v)
            self._updating_sm_checks = False
            self._toggle_staff_ui_states()

        def on_sm_item(*args):
            if self._updating_sm_checks: return
            self._updating_sm_checks = True
            if all(v.get() for v in [self.var_sm_taizo, self.var_sm_nakai, self.var_sm_kajikawa, self.var_sm_saji, self.var_sm_oi, self.var_sm_najib]):
                self.var_sm_all.set(True)
            else:
                self.var_sm_all.set(False)
            self._updating_sm_checks = False
            self._toggle_staff_ui_states()
            
        def on_dropdown_change(*args):
            self._toggle_staff_ui_states()
            
        self.var_sm_all.trace_add("write", on_sm_all)
        for v in [self.var_sm_taizo, self.var_sm_nakai, self.var_sm_kajikawa, self.var_sm_saji, self.var_sm_oi, self.var_sm_najib]:
            v.trace_add("write", on_sm_item)
        self.var_staff_name.trace_add("write", on_dropdown_change)

        ttk.Button(f_staff_multi, text="全解除", command=lambda: self.var_sm_all.set(False)).pack(side=tk.LEFT, padx=(0, 10))
        self.chk_sm_all = ttk.Checkbutton(f_staff_multi, text="ALL", variable=self.var_sm_all)
        self.chk_sm_taizo = ttk.Checkbutton(f_staff_multi, text="Taizo", variable=self.var_sm_taizo)
        self.chk_sm_nakai = ttk.Checkbutton(f_staff_multi, text="Nakai", variable=self.var_sm_nakai)
        self.chk_sm_kajikawa = ttk.Checkbutton(f_staff_multi, text="Kajikawa", variable=self.var_sm_kajikawa)
        self.chk_sm_saji = ttk.Checkbutton(f_staff_multi, text="Saji", variable=self.var_sm_saji)
        self.chk_sm_oi = ttk.Checkbutton(f_staff_multi, text="Oi", variable=self.var_sm_oi)
        self.chk_sm_najib = ttk.Checkbutton(f_staff_multi, text="Najib", variable=self.var_sm_najib)
        for chk in [self.chk_sm_all, self.chk_sm_taizo, self.chk_sm_nakai, self.chk_sm_kajikawa, self.chk_sm_saji, self.chk_sm_oi, self.chk_sm_najib]:
            chk.pack(side=tk.LEFT, padx=5)

        f_filter = ttk.LabelFrame(main, text="🔍 関与フィルター", padding=10)
        f_filter.pack(fill=tk.X, pady=5)
        
        self._updating_staff_checks = False
        self.var_staff_all = tk.BooleanVar(value=True)
        self.var_staff_from = tk.BooleanVar(value=True)
        self.var_staff_to = tk.BooleanVar(value=True)
        self.var_staff_cc = tk.BooleanVar(value=True)

        def on_staff_all(*args):
            if self._updating_staff_checks: return
            self._updating_staff_checks = True
            v = self.var_staff_all.get()
            self.var_staff_from.set(v)
            self.var_staff_to.set(v)
            self.var_staff_cc.set(v)
            self._updating_staff_checks = False

        def on_staff_item(*args):
            if self._updating_staff_checks: return
            self._updating_staff_checks = True
            if self.var_staff_from.get() and self.var_staff_to.get() and self.var_staff_cc.get():
                self.var_staff_all.set(True)
            else:
                self.var_staff_all.set(False)
            self._updating_staff_checks = False

        self.var_staff_all.trace_add("write", on_staff_all)
        self.var_staff_from.trace_add("write", on_staff_item)
        self.var_staff_to.trace_add("write", on_staff_item)
        self.var_staff_cc.trace_add("write", on_staff_item)
        
        ttk.Checkbutton(f_filter, text="ALL", variable=self.var_staff_all).pack(side=tk.LEFT, padx=10)
        ttk.Checkbutton(f_filter, text="From", variable=self.var_staff_from).pack(side=tk.LEFT, padx=10)
        ttk.Checkbutton(f_filter, text="To", variable=self.var_staff_to).pack(side=tk.LEFT, padx=10)
        ttk.Checkbutton(f_filter, text="CC", variable=self.var_staff_cc).pack(side=tk.LEFT, padx=10)

        f_period = ttk.Frame(main)
        f_period.pack(fill=tk.X, pady=10)
        
        ttk.Label(f_period, text="📅 抽出期間:").pack(side=tk.LEFT, padx=(0, 10))
        self.var_staff_period = tk.StringVar(value="過去1週間")
        ttk.Combobox(f_period, textvariable=self.var_staff_period, values=["任意時間(h)", "12H", "24H", "3日間", "過去1週間", "過去2週間", "過去1ヶ月", "過去3ヶ月"], state="readonly", width=12).pack(side=tk.LEFT)
        
        self.spin_staff_h = tk.Spinbox(f_period, from_=1, to=1000, width=5)
        self.spin_staff_h.pack(side=tk.LEFT, padx=2)
        self.spin_staff_h.delete(0, tk.END)
        self.spin_staff_h.insert(0, "1")
        ttk.Label(f_period, text="h").pack(side=tk.LEFT)
        
        self.var_staff_unread = tk.BooleanVar(value=False)
        ttk.Checkbutton(f_period, text="未読のみ", variable=self.var_staff_unread).pack(side=tk.LEFT, padx=(10, 0))
        
        ttk.Label(f_period, text="並び順:").pack(side=tk.LEFT, padx=(20, 10))
        self.var_staff_sort = tk.StringVar(value="重要度順")
        ttk.Combobox(f_period, textvariable=self.var_staff_sort, values=["重要度順", "最新スレッド順", "最古スレッド順"], state="readonly", width=15).pack(side=tk.LEFT)

        f_know = ttk.LabelFrame(main, text="🧠 スタッフ情報 (役割・背景)", padding=10)
        f_know.pack(fill=tk.X, pady=10)
        
        self.btn_edit_staff_know = ttk.Button(f_know, text="✎ スタッフ情報とマスター経緯を編集", command=self._open_staff_knowledge_editor)
        self.btn_edit_staff_know.pack(anchor=tk.W, pady=5)

        f_run = ttk.Frame(main)
        f_run.pack(fill=tk.X, pady=30)
        # ── レポートモード選択ラジオボタン ─────────────────────────────────────
        self.var_staff_report_mode = tk.StringVar(value="adopted")
        f_mode_s = ttk.Frame(f_run)
        f_mode_s.pack(anchor=tk.CENTER, pady=(0, 8))
        ttk.Radiobutton(f_mode_s, text="🎯 AI採用スレッドのみ（軽量）", variable=self.var_staff_report_mode, value="adopted").pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(f_mode_s, text="📋 全スレッド（詳細）", variable=self.var_staff_report_mode, value="all").pack(side=tk.LEFT, padx=10)
        btn_run = ttk.Button(f_run, text="🚀 スタッフの活動俯瞰レポートを生成", command=self._run_staff_overview)
        btn_run.pack(anchor=tk.CENTER, ipadx=20, ipady=10)

        _staff_reformat_init = tk.NORMAL if os.path.exists(STAFF_LAST_RESULT_FILE) else tk.DISABLED
        self.btn_reformat_staff = ttk.Button(
            f_run, text="🎨 フォーマットのみ再生成",
            command=self._reformat_staff,
            state=_staff_reformat_init
        )
        self.btn_reformat_staff.pack(anchor=tk.CENTER, pady=(6, 0))

        self._toggle_staff_ui_states()

    def _toggle_staff_ui_states(self):
        """Staff概観のドロップダウンと複数選択チェックボックスの排他制御を行う"""
        import tkinter as tk
        is_dropdown_used = bool(self.var_staff_name.get().strip())
        is_multi_used = any(v.get() for v in [self.var_sm_taizo, self.var_sm_nakai, self.var_sm_kajikawa, self.var_sm_saji, self.var_sm_oi, self.var_sm_najib])
        
        if is_dropdown_used and not is_multi_used:
            for chk in [self.chk_sm_all, self.chk_sm_taizo, self.chk_sm_nakai, self.chk_sm_kajikawa, self.chk_sm_saji, self.chk_sm_oi, self.chk_sm_najib]:
                chk.config(state=tk.DISABLED)
            self.btn_edit_staff_know.config(state=tk.NORMAL)
        elif is_multi_used:
            self.cb_staff_name.config(state=tk.DISABLED)
            self.btn_edit_staff_know.config(state=tk.DISABLED)
        else:
            self.cb_staff_name.config(state=tk.NORMAL)
            for chk in [self.chk_sm_all, self.chk_sm_taizo, self.chk_sm_nakai, self.chk_sm_kajikawa, self.chk_sm_saji, self.chk_sm_oi, self.chk_sm_najib]:
                chk.config(state=tk.NORMAL)
            self.btn_edit_staff_know.config(state=tk.DISABLED)


    def _ui_cockpit_tab(self):
        """第4のタブ: 統括コックピット (V25 トップダウン俯瞰 + V31 ボタン分割)"""
        main = ttk.Frame(self.tab_cockpit, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        # 上部コントロール
        top_f = ttk.Frame(main)
        top_f.pack(fill=tk.X, pady=(0, 10))
        
        self.btn_refresh_cockpit = ttk.Button(
            top_f, text="📊 既存状況をサマリ (高速)", 
            command=self._refresh_cockpit
        )
        self.btn_refresh_cockpit.pack(side=tk.LEFT, padx=(0, 5))

        self.btn_sync_cockpit = ttk.Button(
            top_f, text="🔄 最新状況に更新 (全自動同期 / 時間・コスト大)", 
            command=self._sync_and_refresh_cockpit
        )
        self.btn_sync_cockpit.pack(side=tk.LEFT)

        _reformat_init_state = tk.NORMAL if os.path.exists(COCKPIT_LAST_RESULT_FILE) else tk.DISABLED
        self.btn_reformat_cockpit = ttk.Button(
            top_f, text="🎨 フォーマットのみ再生成",
            command=self._reformat_cockpit,
            state=_reformat_init_state
        )
        self.btn_reformat_cockpit.pack(side=tk.LEFT, padx=(5, 0))

        ttk.Label(top_f, text="※過去1週間の全データをトーナメント方式で評価します", foreground="gray").pack(side=tk.LEFT, padx=10)

        v2_f = ttk.Frame(main)
        v2_f.pack(fill=tk.X, pady=(0, 10))
        self.btn_run_cockpit_v2 = ttk.Button(
            v2_f, text="🎯 統括コックピット v2（新コンセプト・試験運用）を生成",
            command=self._run_cockpit_v2
        )
        self.btn_run_cockpit_v2.pack(side=tk.LEFT)
        ttk.Label(
            v2_f,
            text="※ メールを要約するのではなく、自分待ちの案件を解放スコア順に理由つきで表示する新方式（送信済みメールも参照）",
            foreground="gray"
        ).pack(side=tk.LEFT, padx=10)

        # スクロールエリア
        canvas = tk.Canvas(main, highlightthickness=0)
        sc = ttk.Scrollbar(main, orient="vertical", command=canvas.yview)
        self.cockpit_scroll_frame = ttk.Frame(canvas)
        
        self.cockpit_scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=self.cockpit_scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=sc.set)
        
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sc.pack(side=tk.RIGHT, fill=tk.Y)

        # マウスホイール制御
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # セクション定義 (4大管理領域)
        self.cockpit_sections = {
            "alerts": {"title": "🚨 アラート (上司報告・重大リスク)", "color": "#FFEBEE"},
            "action_queue": {"title": "⚡ アクション・キュー (あなたの承認・指示待ち)", "color": "#E3F2FD"},
            "governance": {"title": "📢 周知・ガバナンス (スタッフへの徹底事項)", "color": "#F1F8E9"},
            "stalled": {"title": "🛑 停滞監視 (議論の詰まり・長期未解決)", "color": "#FFF3E0"}
        }
        
        self.cockpit_widgets = {}  # セクションごとのコンテナ保持
        
        for key, info in self.cockpit_sections.items():
            f = ttk.LabelFrame(self.cockpit_scroll_frame, text=info["title"], padding=10)
            f.pack(fill=tk.X, expand=True, pady=10, padx=5)
            
            inner = ttk.Frame(f)
            inner.pack(fill=tk.X)
            
            self.cockpit_widgets[key] = inner
            
            # 初期メッセージ
            ttk.Label(inner, text="データがありません。更新ボタンを押してください。", foreground="gray").pack(pady=5)


    def _refresh_cockpit(self):
        """統括コックピットの表示を更新する制御ロジック (HTML連携版)"""
        self.btn_sync_cockpit.config(state=tk.DISABLED, text="⏳ 解析・同期中 (しばらくお待ちください)...")
        self._set_status("🚀 統括コックピットを更新中...", start_timer=True)
        
        for widget in self.cockpit_widgets.values():
            for child in widget.winfo_children():
                child.destroy()
            import tkinter.ttk as ttk
            ttk.Label(widget, text="ブラウザでHTMLレポートを生成しています...", foreground="gray").pack(pady=10)

        def task():
            try:
                res = self.summarizer.generate_cockpit_summary(
                    progress_callback=lambda msg: self.root.after(0, lambda: self._set_status(msg))
                )
                
                # HTML生成用：キャッシュから ID -> Topic の辞書を構築
                import os, json
                cache_dict = {}
                cache_dir = "analysis_cache"
                if os.path.exists(cache_dir):
                    for fname in os.listdir(cache_dir):
                        if fname.endswith(".json"):
                            try:
                                with open(os.path.join(cache_dir, fname), 'r', encoding='utf-8') as f:
                                    cdata = json.load(f)
                                    for cid, tinfo in cdata.get("threads", {}).items():
                                        t_data = tinfo.get("data", {})
                                        if t_data and "topic" in t_data:
                                            cache_dict[cid] = t_data["topic"]
                            except: pass

                path = self.reporter.generate_cockpit_report(res, cache_dict, self.summarizer.total_input_tokens, self.summarizer.total_output_tokens)
                try:
                    with open(COCKPIT_LAST_RESULT_FILE, 'w', encoding='utf-8') as jf:
                        json.dump({
                            "res": res,
                            "cache_dict": cache_dict,
                            "total_input": self.summarizer.total_input_tokens,
                            "total_output": self.summarizer.total_output_tokens
                        }, jf, ensure_ascii=False)
                    print("💾 cockpit_last_result.json 保存完了")
                    self.root.after(0, lambda: self.btn_reformat_cockpit.config(state=tk.NORMAL))
                except Exception as save_err:
                    print(f"⚠️ cockpit_last_result.json 保存失敗（HTML生成は継続）: {save_err}")
                if path:
                    import webbrowser
                    webbrowser.open(path)
            except Exception as e:
                import tkinter.messagebox as messagebox
                self.root.after(0, lambda: messagebox.showerror("エラー", str(e)))
            finally:
                self.root.after(0, lambda: self.btn_sync_cockpit.config(state=tk.NORMAL, text="🔄 最新状況に更新 (全自動同期 / 時間・コスト大)"))
                self.root.after(0, lambda: self._set_status("✅ コックピット更新完了", start_timer=False))

        import threading
        threading.Thread(target=task, daemon=True).start()


    def _sync_and_refresh_cockpit(self):
        """全自動パイプライン: 全PJ・スタッフのキャッシュ最新化後、HTMLコックピットを描画"""
        import tkinter as tk
        import tkinter.ttk as ttk
        import tkinter.messagebox as messagebox
        import threading

        if not messagebox.askyesno("⚠️ 確認", "全プロジェクトおよび全スタッフの過去1週間分のメールを再取得・分析します。\nAPIコールの時間とコスト（数十円〜）がかかりますが実行しますか？"):
            return

        self.btn_sync_cockpit.config(state=tk.DISABLED, text="⏳ 全自動同期中 (数分かかります)...")
        self.btn_refresh_cockpit.config(state=tk.DISABLED)
        self._set_status("🚀 全解析同期パイプラインを開始...", start_timer=True)
        
        for widget in self.cockpit_widgets.values():
            for child in widget.winfo_children():
                child.destroy()
            ttk.Label(widget, text="全データの最新化と分析を行っています（完了後ブラウザが開きます）...", foreground="gray").pack(pady=10)

        def task():
            try:
                days = 7  # 過去1週間で固定
                self.project_knowledge = load_project_knowledge()
                
                # 1. 全プロジェクトのキャッシュ更新
                proj_targets = list(self.project_knowledge.get("projects", {}).keys())
                for proj in proj_targets:
                    self.root.after(0, lambda p=proj: self._set_status(f"⚙️ PJ抽出中: {p}"))
                    mails = self.outlook.get_project_mails(proj, days)
                    if mails:
                        threads = self.outlook.group_by_thread(mails)
                        self.summarizer.summarize_project_threads(
                            proj, threads, self.project_knowledge,
                            progress_callback=lambda msg, p=proj: self.root.after(0, lambda: self._set_status(f"🤖 PJ分析({p}): {msg}"))
                        )

                # 2. 全スタッフのキャッシュ更新
                staff_targets = list(self.project_knowledge.get("staffs", {}).keys())
                conds_base = {'days': days}
                for staff in staff_targets:
                    self.root.after(0, lambda s=staff: self._set_status(f"⚙️ スタッフ抽出中: {s}"))
                    mails = []
                    seen_ids = set()
                    search_term = {"Oi": "yuto.oi"}.get(staff, staff)  # 既存のエイリアス対応
                    
                    try:
                        c_from = conds_base.copy(); c_from['sender'] = search_term
                        res = self.outlook.search_mails_fast(c_from, "AND", True)
                        for m in res:
                            if m.get('entry_id') and m['entry_id'] not in seen_ids:
                                mails.append(m); seen_ids.add(m['entry_id'])
                                
                        c_other = conds_base.copy(); c_other['body_keyword'] = search_term
                        res = self.outlook.search_mails_fast(c_other, "AND", True)
                        for m in res:
                            if m.get('entry_id') and m['entry_id'] not in seen_ids:
                                mails.append(m); seen_ids.add(m['entry_id'])
                    except Exception as e:
                        print(f"Sync Search Error ({staff}): {e}")

                    if mails:
                        threads = self.outlook.group_by_thread(mails)
                        self.summarizer.summarize_staff_threads(
                            staff, threads, self.project_knowledge,
                            progress_callback=lambda msg, s=staff: self.root.after(0, lambda: self._set_status(f"🤖 スタッフ分析({s}): {msg}"))
                        )

                save_project_knowledge(self.project_knowledge)

                # 3. 決勝戦（コックピットの統合処理）
                self.root.after(0, lambda: self._set_status("📊 最新データでコックピットを構築中..."))
                res = self.summarizer.generate_cockpit_summary(
                    progress_callback=lambda msg: self.root.after(0, lambda: self._set_status(msg))
                )
                
                # HTML生成用：キャッシュ辞書構築
                import os, json
                cache_dict = {}
                cache_dir = "analysis_cache"
                if os.path.exists(cache_dir):
                    for fname in os.listdir(cache_dir):
                        if fname.endswith(".json"):
                            try:
                                with open(os.path.join(cache_dir, fname), 'r', encoding='utf-8') as f:
                                    cdata = json.load(f)
                                    for cid, tinfo in cdata.get("threads", {}).items():
                                        t_data = tinfo.get("data", {})
                                        if t_data and "topic" in t_data:
                                            cache_dict[cid] = t_data["topic"]
                            except: pass

                path = self.reporter.generate_cockpit_report(res, cache_dict, self.summarizer.total_input_tokens, self.summarizer.total_output_tokens)
                try:
                    with open(COCKPIT_LAST_RESULT_FILE, 'w', encoding='utf-8') as jf:
                        json.dump({
                            "res": res,
                            "cache_dict": cache_dict,
                            "total_input": self.summarizer.total_input_tokens,
                            "total_output": self.summarizer.total_output_tokens
                        }, jf, ensure_ascii=False)
                    print("💾 cockpit_last_result.json 保存完了")
                    self.root.after(0, lambda: self.btn_reformat_cockpit.config(state=tk.NORMAL))
                except Exception as save_err:
                    print(f"⚠️ cockpit_last_result.json 保存失敗（HTML生成は継続）: {save_err}")
                if path:
                    import webbrowser
                    webbrowser.open(path)

            except Exception as e:
                import tkinter.messagebox as messagebox
                self.root.after(0, lambda: messagebox.showerror("エラー", str(e)))
            finally:
                self.root.after(0, lambda: self.btn_sync_cockpit.config(state=tk.NORMAL, text="🔄 最新状況に更新 (全自動同期 / 時間・コスト大)"))
                self.root.after(0, lambda: self.btn_refresh_cockpit.config(state=tk.NORMAL))
                self.root.after(0, lambda: self._set_status("✅ 全解析同期完了", start_timer=False))

        threading.Thread(target=task, daemon=True).start()


    def _reformat_cockpit(self):
        """フォーマットのみ再生成: cockpit_last_result.json からデータ読込→HTML再生成（APIコール無し）"""
        import os, json, threading, webbrowser
        import tkinter.messagebox as messagebox

        if not os.path.exists(COCKPIT_LAST_RESULT_FILE):
            messagebox.showerror("エラー", "保存済みデータがありません。\n先に「📊 既存状況をサマリ」または「🔄 最新状況に更新」を実行してください。")
            return

        self.btn_reformat_cockpit.config(state=tk.DISABLED, text="⏳ フォーマット再生成中...")
        self._set_status("🎨 フォーマットのみ再生成中...", start_timer=True)

        def task():
            try:
                with open(COCKPIT_LAST_RESULT_FILE, 'r', encoding='utf-8') as jf:
                    saved = json.load(jf)
                res          = saved.get("res", {})
                cache_dict   = saved.get("cache_dict", {})
                total_input  = saved.get("total_input", 0)
                total_output = saved.get("total_output", 0)
                path = self.reporter.generate_cockpit_report(
                    res, cache_dict, total_input, total_output, reformat_mode=True
                )
                if path:
                    webbrowser.open(path)
            except Exception as e:
                _err = str(e)
                self.root.after(0, lambda: messagebox.showerror("エラー", f"フォーマット再生成に失敗しました:\n{_err}"))
            finally:
                self.root.after(0, lambda: self.btn_reformat_cockpit.config(
                    state=tk.NORMAL, text="🎨 フォーマットのみ再生成"
                ))
                self.root.after(0, lambda: self._set_status("✅ フォーマット再生成完了", start_timer=False))

        threading.Thread(target=task, daemon=True).start()

    def _run_cockpit_v2(self):
        """統括コックピットv2(新コンセプト・試験運用): プロジェクトごとに送信済みメールも
        含めて取得し、「自分待ち(ボールが自分のコートにある)」の案件を解放スコア順に
        理由つきで表示する。既存の統括コックピット(_refresh_cockpit等)には一切影響しない。"""
        import tkinter.messagebox as messagebox

        self.btn_run_cockpit_v2.config(state=tk.DISABLED, text="⏳ 集計中...")
        self._set_status("🎯 統括コックピット v2 を生成中...", start_timer=True)

        def task():
            try:
                project_names = list(self.project_knowledge.get("projects", {}).keys())
                project_threads = {}
                for i, proj in enumerate(project_names):
                    self.root.after(0, lambda p=proj, i=i: self._set_status(
                        f"📁 {p} を取得中... ({i+1}/{len(project_names)})"
                    ))
                    mails = self.outlook.get_project_mails(proj, COCKPIT_V2_WINDOW_DAYS, include_sent=True)
                    project_threads[proj] = self.outlook.group_by_thread(mails)

                cockpit_data = self.summarizer.generate_cockpit_v2_data(
                    project_threads, self.project_knowledge, self.outlook.user_smtp_address,
                    progress_callback=lambda c, t, msg: self.root.after(0, lambda: self._set_status(msg))
                )
                path = self.reporter.generate_cockpit_v2_report(
                    cockpit_data, self.summarizer.total_input_tokens, self.summarizer.total_output_tokens
                )
                if path:
                    import webbrowser
                    webbrowser.open(path)
                else:
                    self.root.after(0, lambda: messagebox.showerror("エラー", "統括コックピット v2 の生成に失敗しました。"))
            except Exception as e:
                _err = str(e)
                self.root.after(0, lambda: messagebox.showerror("エラー", f"統括コックピット v2 の生成中にエラーが発生しました:\n{_err}"))
            finally:
                self.root.after(0, lambda: self.btn_run_cockpit_v2.config(
                    state=tk.NORMAL, text="🎯 統括コックピット v2（新コンセプト・試験運用）を生成"
                ))
                self.root.after(0, lambda: self._set_status("✅ 統括コックピット v2 生成完了", start_timer=False))

        threading.Thread(target=task, daemon=True).start()

    def _render_cockpit_error(self, error_msg):
        for widget in self.cockpit_widgets.values():
            for child in widget.winfo_children():
                child.destroy()
        
        ttk.Label(self.cockpit_widgets["alerts"], text=f"❌ エラーが発生しました:\n{error_msg}", foreground="red").pack(pady=10)

    def _render_cockpit_data(self, data):
        """AIから返ってきたJSONをUIカードに流し込み、Dismiss機能を付与する"""
        if data.get("_error"):
            self._render_cockpit_error(data.get("summary", "不明なエラー"))
            return

        def dismiss_item(frame):
            frame.destroy()

        for key, widget in self.cockpit_widgets.items():
            for child in widget.winfo_children():
                child.destroy()
                
            items = data.get(key, [])
            if not items:
                ttk.Label(widget, text="該当するアラートやタスクはありません。順調です。", foreground="green").pack(pady=5)
                continue

            for idx, item in enumerate(items):
                # アイテム用コンテナ
                item_frame = tk.Frame(widget, bg="#ffffff", bd=1, relief=tk.SOLID)
                item_frame.pack(fill=tk.X, pady=4, padx=2)
                
                # ヘッダー領域 (タイトル + Dismissボタン)
                header_f = tk.Frame(item_frame, bg=self.cockpit_sections[key]["color"])
                header_f.pack(fill=tk.X)
                
                title = str(item.get("title", "無題"))
                desc = str(item.get("desc", ""))
                
                tk.Label(header_f, text=f"■ {title}", font=("", 10, "bold"), bg=self.cockpit_sections[key]["color"]).pack(side=tk.LEFT, padx=5, pady=3)
                
                # Q6: 手動Dismissフェイルセーフ
                btn_dismiss = tk.Button(header_f, text="✖ 閉じる", relief=tk.FLAT, bg=self.cockpit_sections[key]["color"], fg="gray", cursor="hand2", command=lambda f=item_frame: dismiss_item(f))
                btn_dismiss.pack(side=tk.RIGHT, padx=5)
                
                # 本文領域
                body_f = tk.Frame(item_frame, bg="#ffffff")
                body_f.pack(fill=tk.X, padx=10, pady=8)
                
                tk.Message(body_f, text=desc, width=900, bg="#ffffff", fg="#333333").pack(anchor=tk.W)


    def _ui_action_tab(self):
        """第5のタブ: アクションダッシュボード（期間×自分宛て全体の横断アクション一覧）"""
        main = ttk.Frame(self.tab_action, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        top_f = ttk.Frame(main)
        top_f.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(top_f, text="対象期間:").pack(side=tk.LEFT, padx=(0, 5))
        self.v_action_prd = tk.StringVar(value="1週間")
        cmb = ttk.Combobox(
            top_f, textvariable=self.v_action_prd, state="readonly", width=10,
            values=["24H", "今日", "3日間", "1週間", "2週間", "3週間", "1ヶ月", "2ヶ月", "3ヶ月", "6ヶ月"]
        )
        cmb.pack(side=tk.LEFT, padx=(0, 10))

        self.btn_run_action = ttk.Button(
            top_f, text="📋 アクション一覧を生成", command=self._run_action_dashboard
        )
        self.btn_run_action.pack(side=tk.LEFT, padx=(0, 5))

        _reformat_init_state = tk.NORMAL if os.path.exists(ACTION_DASHBOARD_LAST_RESULT_FILE) else tk.DISABLED
        self.btn_reformat_action = ttk.Button(
            top_f, text="🎨 フォーマットのみ再生成",
            command=self._reformat_action_dashboard,
            state=_reformat_init_state
        )
        self.btn_reformat_action.pack(side=tk.LEFT, padx=(5, 0))

        sync_f = ttk.Frame(main)
        sync_f.pack(fill=tk.X, pady=(0, 8))
        self.v_action_sync_vba = tk.BooleanVar(value=False)
        self.chk_action_sync_vba = ttk.Checkbutton(
            sync_f,
            text="🔄 Outlook再起動を検知したら、フラグ/Just Do It付き既読メールを未読に戻し、該当の進捗もリセットする",
            variable=self.v_action_sync_vba
        )
        self.chk_action_sync_vba.pack(side=tk.LEFT)

        ttk.Label(
            main,
            text="※ 指定期間内で自分宛て(To/With/Cc)の全メールを対象に、AIが「誰から・何を・いつまでに」求められているかを抽出します。\n"
                 "既知のプロジェクト/スタッフには限定しません。進捗・優先度・コメントはブラウザ上のボタン/入力欄でその場保存され、次回もフォーマット再生成で保持されます。",
            foreground="gray", justify=tk.LEFT
        ).pack(anchor=tk.W)

    def _get_action_days(self):
        return {"24H": 0, "今日": 1, "3日間": 3, "1週間": 7, "2週間": 14, "3週間": 21, "1ヶ月": 30, "2ヶ月": 60, "3ヶ月": 90, "6ヶ月": 180}.get(self.v_action_prd.get(), 7)

    def _save_action_dashboard_result(self, res, date_range, total_input, total_output):
        try:
            with open(ACTION_DASHBOARD_LAST_RESULT_FILE, 'w', encoding='utf-8') as jf:
                json.dump({
                    "action_cards": res.get("action_cards", []),
                    "date_range": date_range,
                    "total_input": total_input,
                    "total_output": total_output
                }, jf, ensure_ascii=False)
            self.root.after(0, lambda: self.btn_reformat_action.config(state=tk.NORMAL))
        except Exception as save_err:
            print(f"⚠️ action_dashboard_last_result.json 保存失敗（HTML生成は継続）: {save_err}")

    def _run_action_dashboard(self):
        """期間内で自分宛て全体のメールを取得し、AIでアクション抽出してHTMLダッシュボードを開く"""
        self.btn_run_action.config(state=tk.DISABLED, text="⏳ 取得・解析中...")
        self._set_status("🚀 アクションダッシュボードを生成中...", start_timer=True)

        def task():
            try:
                reset_conv_ids = set()
                if self.v_action_sync_vba.get():
                    if self.outlook.check_and_update_outlook_restart_state():
                        try:
                            sync_result = self.outlook.sync_forced_unread_from_outlook_state()
                            reset_conv_ids = sync_result.get("affected_conversation_ids", set())
                        except Exception as sync_err:
                            print(f"Outlook再起動同期エラー: {sync_err}")
                days = self._get_action_days()
                mails = self.outlook.get_relevant_mails_for_period(
                    days, progress_callback=lambda c, t, msg: self.root.after(0, lambda: self._set_status(msg))
                )
                threads = self.outlook.group_by_thread(mails)
                res = self.summarizer.summarize_action_dashboard(
                    threads,
                    progress_callback=lambda c, t, msg: self.root.after(0, lambda: self._set_status(msg)),
                    reset_conversation_ids=reset_conv_ids
                )
                date_range = f"対象期間: {self.v_action_prd.get()} / 自分宛て(To/With/Cc)全メール"
                path = self.reporter.generate_action_dashboard_report(
                    res.get("action_cards", []), date_range,
                    self.summarizer.total_input_tokens, self.summarizer.total_output_tokens
                )
                self._save_action_dashboard_result(res, date_range, self.summarizer.total_input_tokens, self.summarizer.total_output_tokens)
                if path:
                    import webbrowser
                    webbrowser.open(path)
            except Exception as e:
                import tkinter.messagebox as messagebox
                self.root.after(0, lambda: messagebox.showerror("エラー", str(e)))
            finally:
                self.root.after(0, lambda: self.btn_run_action.config(state=tk.NORMAL, text="📋 アクション一覧を生成"))
                self.root.after(0, lambda: self._set_status("✅ アクションダッシュボード生成完了", start_timer=False))

        threading.Thread(target=task, daemon=True).start()

    def _reformat_action_dashboard(self):
        """フォーマットのみ再生成: 保存済みデータからHTML再生成（APIコール無し）"""
        import tkinter.messagebox as messagebox

        if not os.path.exists(ACTION_DASHBOARD_LAST_RESULT_FILE):
            messagebox.showerror("エラー", "保存済みデータがありません。\n先に「📋 アクション一覧を生成」を実行してください。")
            return

        self.btn_reformat_action.config(state=tk.DISABLED, text="⏳ フォーマット再生成中...")
        self._set_status("🎨 フォーマットのみ再生成中...", start_timer=True)

        def task():
            try:
                with open(ACTION_DASHBOARD_LAST_RESULT_FILE, 'r', encoding='utf-8') as jf:
                    saved = json.load(jf)
                action_cards = saved.get("action_cards", [])
                date_range   = saved.get("date_range", "")
                total_input  = saved.get("total_input", 0)
                total_output = saved.get("total_output", 0)

                # 再生成時は、保存されたAI抽出結果はそのままに、ステータス（進捗・優先度・コメント）だけ
                # json/action_status.json の最新値で上書きしてから描画する(カード内の各アクションごとに)
                action_statuses = load_action_status()
                for card in action_cards:
                    for a in card.get("actions", []):
                        st = action_statuses.get(a.get("action_key", ""), {})
                        a["progress"] = st.get("progress", a.get("progress", "not_started"))
                        a["priority"] = st.get("priority", a.get("priority", ""))
                        a["comment"] = st.get("comment", a.get("comment", ""))

                path = self.reporter.generate_action_dashboard_report(
                    action_cards, date_range, total_input, total_output, reformat_mode=True
                )
                if path:
                    import webbrowser
                    webbrowser.open(path)
            except Exception as e:
                _err = str(e)
                self.root.after(0, lambda: messagebox.showerror("エラー", f"フォーマット再生成に失敗しました:\n{_err}"))
            finally:
                self.root.after(0, lambda: self.btn_reformat_action.config(
                    state=tk.NORMAL, text="🎨 フォーマットのみ再生成"
                ))
                self.root.after(0, lambda: self._set_status("✅ フォーマット再生成完了", start_timer=False))

        threading.Thread(target=task, daemon=True).start()

    def _open_knowledge_editor(self):
        self.project_knowledge = load_project_knowledge()
        
        d = tk.Toplevel(self.root)
        d.title("🧠 プロジェクトナレッジ編集")
        d.geometry("750x850")
        
        notebook = ttk.Notebook(d)
        notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        tab_common = ttk.Frame(notebook)
        notebook.add(tab_common, text="共通設定")
        
        ttk.Label(tab_common, text="私の役割:").pack(anchor=tk.W, padx=5, pady=2)
        txt_role = tk.Text(tab_common, height=5)
        txt_role.pack(fill=tk.X, padx=5, pady=2)
        txt_role.insert("1.0", self.project_knowledge.get("common_settings", {}).get("my_role", ""))
        
        ttk.Label(tab_common, text="ステークホルダー:").pack(anchor=tk.W, padx=5, pady=2)
        txt_sh = tk.Text(tab_common, height=5)
        txt_sh.pack(fill=tk.X, padx=5, pady=2)
        txt_sh.insert("1.0", self.project_knowledge.get("common_settings", {}).get("stakeholders", ""))
        
        ttk.Button(tab_common, text="共通設定を保存", command=lambda: self._save_common_kn(txt_role, txt_sh)).pack(pady=10)
        
        for proj in self.project_knowledge.get("projects", {}).keys():
            ptab = ttk.Frame(notebook)
            notebook.add(ptab, text=proj)

            data = self.project_knowledge.get("projects", {}).get(proj, {})

            prio_row = ttk.Frame(ptab)
            prio_row.pack(fill=tk.X, padx=5, pady=(8, 2))
            ttk.Label(prio_row, text="🎯 プロジェクト優先度（統括コックピットの解放スコアに反映）:").pack(side=tk.LEFT)
            v_prio = tk.StringVar(value=data.get("priority", "中"))
            ttk.Combobox(prio_row, textvariable=v_prio, state="readonly", width=6,
                         values=["高", "中", "低"]).pack(side=tk.LEFT, padx=(8, 0))

            ttk.Label(ptab, text="📌 マスター経緯（人間が管理・AIは書き換えません）:").pack(anchor=tk.W, padx=5, pady=2)
            t_m = tk.Text(ptab, height=15)
            t_m.pack(fill=tk.X, padx=5, pady=2)
            t_m.insert("1.0", data.get("master_history", ""))

            ttk.Label(ptab, text="📅 AI履歴（自動蓄積・閲覧用）:").pack(anchor=tk.W, padx=5, pady=(10, 2))
            t_a = tk.Text(ptab, height=15, bg="#f8f8f8")
            t_a.pack(fill=tk.X, padx=5, pady=2)
            t_a.insert("1.0", data.get("history_summary", ""))

            ttk.Button(ptab, text=f"このプロジェクト({proj})を保存", command=lambda p=proj, m=t_m, a=t_a, pr=v_prio: self._save_proj_kn(p, m.get("1.0", tk.END), a.get("1.0", tk.END), pr.get())).pack(pady=10)

    def _save_common_kn(self, txt_role, txt_sh):
        if "common_settings" not in self.project_knowledge:
            self.project_knowledge["common_settings"] = {}
        self.project_knowledge["common_settings"]["my_role"] = txt_role.get("1.0", tk.END).strip()
        self.project_knowledge["common_settings"]["stakeholders"] = txt_sh.get("1.0", tk.END).strip()
        save_project_knowledge(self.project_knowledge)
        messagebox.showinfo("保存", "共通設定を保存しました")

    def _save_proj_kn(self, proj, master, ai_hist, priority="中"):
        if "projects" not in self.project_knowledge:
            self.project_knowledge["projects"] = {}
        target = self.project_knowledge["projects"].setdefault(proj, {})
        target["master_history"] = master.strip()
        target["history_summary"] = ai_hist.strip()
        target["priority"] = priority
        save_project_knowledge(self.project_knowledge)
        messagebox.showinfo("保存", f"{proj} のナレッジを保存しました")

    def _open_staff_knowledge_editor(self):
        self.project_knowledge = load_project_knowledge()
        if "staffs" not in self.project_knowledge: 
            self.project_knowledge["staffs"] = {}
        
        staff_name = self.var_staff_name.get().strip()
        if not staff_name:
            messagebox.showwarning("警告", "対象スタッフ名を入力または選択してください。")
            return
            
        d = tk.Toplevel(self.root)
        d.title(f"🧠 スタッフ情報編集: {staff_name}")
        d.geometry("750x850")
        
        staff_data = self.project_knowledge["staffs"].get(staff_name, {})
        
        ttk.Label(d, text="役割 (Role):").pack(anchor=tk.W, padx=10, pady=5)
        txt_role = tk.Text(d, height=3)
        txt_role.pack(fill=tk.X, padx=10, pady=2)
        txt_role.insert("1.0", staff_data.get("role", ""))
        
        ttk.Label(d, text="その他バックグラウンド (Background):").pack(anchor=tk.W, padx=10, pady=5)
        txt_bg = tk.Text(d, height=3)
        txt_bg.pack(fill=tk.X, padx=10, pady=2)
        txt_bg.insert("1.0", staff_data.get("background", ""))
        
        ttk.Label(d, text="📌 マスター経緯（人間が管理・AIは書き換えません）:").pack(anchor=tk.W, padx=10, pady=5)
        txt_m = tk.Text(d, height=12)
        txt_m.pack(fill=tk.X, padx=10, pady=2)
        txt_m.insert("1.0", staff_data.get("master_history", ""))

        ttk.Label(d, text="📅 AI履歴（自動蓄積・閲覧用）:").pack(anchor=tk.W, padx=10, pady=(10, 5))
        txt_a = tk.Text(d, height=12, bg="#f8f8f8")
        txt_a.pack(fill=tk.X, padx=10, pady=2)
        txt_a.insert("1.0", staff_data.get("history_summary", ""))
        
        def save():
            s = self.project_knowledge["staffs"].setdefault(staff_name, {})
            s["role"] = txt_role.get("1.0", tk.END).strip()
            s["background"] = txt_bg.get("1.0", tk.END).strip()
            s["master_history"] = txt_m.get("1.0", tk.END).strip()
            s["history_summary"] = txt_a.get("1.0", tk.END).strip()
            
            save_project_knowledge(self.project_knowledge)
            staff_list = list(self.project_knowledge["staffs"].keys())
            self.cb_staff_name.config(values=staff_list)
            messagebox.showinfo("保存", "スタッフ情報を更新しました。")
            d.destroy()

        ttk.Button(d, text="保存して閉じる", command=save).pack(pady=15)

    def _open_file_manager(self):
        d = tk.Toplevel(self.root)
        d.title("📁 レポートファイル管理")
        d.geometry("380x280")
        d.resizable(False, False)
        
        ttk.Label(d, text="■ 保存先フォルダの確認", font=("", 10, "bold")).pack(anchor=tk.W, padx=15, pady=(15, 5))
        def open_folder():
            folder = self.config.get('output_folder', '')
            if os.path.exists(folder):
                os.startfile(os.path.abspath(folder))
            else:
                messagebox.showwarning("警告", "保存フォルダが見つかりません。")
        ttk.Button(d, text="📂 エクスプローラーで開く", command=open_folder).pack(fill=tk.X, padx=20, pady=5)
        
        ttk.Separator(d, orient="horizontal").pack(fill=tk.X, padx=10, pady=15)
        
        ttk.Label(d, text="■ 古いレポートの一括クリーンナップ", font=("", 10, "bold")).pack(anchor=tk.W, padx=15, pady=5)
        f_clean = ttk.Frame(d)
        f_clean.pack(fill=tk.X, padx=20, pady=5)
        v_days = tk.StringVar(value="7日以前")
        ttk.Combobox(f_clean, textvariable=v_days, values=["7日以前", "14日以前", "30日以前", "60日以前"], state="readonly", width=12).pack(side=tk.LEFT, padx=(0, 10))
        
        def run_clean():
            days = int(re.search(r'\d+', v_days.get()).group())
            folder = Path(self.config.get('output_folder', ''))
            if not folder.exists():
                messagebox.showinfo("情報", "対象のフォルダが存在しません。")
                return
                
            cutoff_time = datetime.now().timestamp() - (days * 86400)
            target_files = []
            total_size = 0
            for f in folder.glob("*_report_*.html"):
                if f.is_file():
                    stat = f.stat()
                    if stat.st_mtime < cutoff_time:
                        target_files.append(f)
                        total_size += stat.st_size
                        
            if not target_files:
                messagebox.showinfo("結果", f"{days}日以前の古いレポートは見つかりませんでした。")
                return
                
            mb_size = round(total_size / (1024 * 1024), 2)
            if messagebox.askyesno("確認", f"{days}日以前のレポートファイルが {len(target_files)}件（合計 {mb_size} MB）見つかりました。\n\nこれらをすべて削除してよろしいですか？"):
                del_count = 0
                for f in target_files:
                    try:
                        f.unlink()
                        del_count += 1
                    except Exception:
                        pass
                messagebox.showinfo("完了", f"{del_count}件のファイルを削除しました。")
                
        ttk.Button(f_clean, text="🗑️ 削除を実行", command=run_clean).pack(side=tk.LEFT)


    def _run_project_overview(self):
        self.project_knowledge = load_project_knowledge() 
        
        targets = []
        if self.var_proj_caracal.get(): targets.append("00_Caracal")
        if self.var_proj_wheeling.get(): targets.append("01_Wheeling")
        if self.var_proj_grandteton.get(): targets.append("02_GrandTeton")
        if self.var_proj_r19projects.get(): targets.append("03_R19Projects")
        
        if not targets:
            messagebox.showwarning("警告", "対象プロジェクトが選択されていません。")
            return
            
        period_str = self.var_proj_period.get()
        sort_order = self.var_proj_sort.get()
        days_map = {"任意時間(h)": -999, "12H": -12, "24H": 0, "3日間": 3, "過去1週間": 7, "過去2週間": 14, "過去1ヶ月": 30, "過去3ヶ月": 90}
        days = days_map.get(period_str, 14)
        if days == -999:
            try:
                days = -int(self.spin_proj_h.get())
            except:
                days = -1
                
        unread_only = self.var_proj_unread.get()
        
        end_date = datetime.now()
        if days < 0:
            start_date = end_date - timedelta(hours=abs(days))
        elif days == 0:
            start_date = end_date - timedelta(hours=24)
        else:
            start_date = end_date - timedelta(days=days)
        
        if days <= 0:
            date_range_str = f"{start_date.strftime('%Y/%m/%d %H:%M')} 〜 {end_date.strftime('%Y/%m/%d %H:%M')}"
        else:
            date_range_str = f"{start_date.strftime('%Y/%m/%d')} 〜 {end_date.strftime('%Y/%m/%d')}"
        
        self._set_status("🚀 解析開始...", start_timer=True)
        self.summarizer.total_input_tokens = 0
        self.summarizer.total_output_tokens = 0

        def task():
            summaries = {}
            all_orig_threads = {}
            
            for proj in targets:
                self.root.after(0, lambda p=proj: self._set_status(f"⚙️ 抽出中: {p}"))
                mails = self.outlook.get_project_mails(proj, days)
                
                if not mails:
                    # V34修正: 新3層スキーマに対応したダミーデータ
                    summaries[proj] = {
                        "manager_actions": [], 
                        "staff_status": [{"category": "その他", "project_scope": proj, "action_type": "通知・共有", "text": "指定期間のメールはありません。", "status_icon": "⚪"}], 
                        "stalled_monitor": [], "threads": []
                    }
                    continue
                    
                threads = self.outlook.group_by_thread(mails)
                if unread_only:
                    threads = {cid: t for cid, t in threads.items() if t['has_unread']}
                
                all_orig_threads[proj] = threads
                self.root.after(0, lambda p=proj: self._set_status(f"🤖 AI分析中: {p}"))
                
                res = self.summarizer.summarize_project_threads(
                    proj, threads, self.project_knowledge,
                    retry_callback=lambda p=proj: self.root.after(0, lambda: self._set_status(f"🤖 AI再試行中: {p}")),
                    progress_callback=lambda msg: self.root.after(0, lambda: self._set_status(msg))
                )
                summaries[proj] = res
                
                if "updated_history" in res:
                    if "projects" not in self.project_knowledge:
                        self.project_knowledge["projects"] = {}
                    if proj not in self.project_knowledge["projects"]:
                        self.project_knowledge["projects"][proj] = {}
                    self.project_knowledge["projects"][proj]["history_summary"] = res["updated_history"]

            save_project_knowledge(self.project_knowledge)
            
            self.root.after(0, lambda: self._set_status("📝 レポート生成中..."))
            
            _proj_report_mode = getattr(self, 'var_proj_report_mode', None)
            _proj_mode_val = _proj_report_mode.get() if _proj_report_mode else "adopted"
            path = self.reporter.generate_project_report(
                targets[0] if len(targets) == 1 else "Combined_Report",
                summaries, 
                all_orig_threads,
                self.project_knowledge, 
                date_range_str,
                sort_order,
                self.summarizer.total_input_tokens, 
                self.summarizer.total_output_tokens,
                report_mode=_proj_mode_val
            )
            
            if path and len(path) > 0:
                webbrowser.open(path)
                try:
                    orig_threads_slim = {}
                    for proj, threads in all_orig_threads.items():
                        orig_threads_slim[proj] = {
                            cid: {
                                "latest_entry_id": t.get("latest_entry_id", ""),
                                "latest_date_str": t["latest_date"].isoformat() if t.get("latest_date") else ""
                            }
                            for cid, t in threads.items()
                        }
                    with open(PROJECT_LAST_RESULT_FILE, 'w', encoding='utf-8') as jf:
                        json.dump({
                            "report_name": targets[0] if len(targets) == 1 else "Combined_Report",
                            "summaries": summaries,
                            "orig_threads_slim": orig_threads_slim,
                            "date_range_str": date_range_str,
                            "sort_order": sort_order,
                            "total_input": self.summarizer.total_input_tokens,
                            "total_output": self.summarizer.total_output_tokens,
                            "report_mode": _proj_mode_val
                        }, jf, ensure_ascii=False)
                    print("💾 project_last_result_latest.json 保存完了")
                    self.root.after(0, lambda: self.btn_reformat_project.config(state=tk.NORMAL))
                except Exception as save_err:
                    print(f"⚠️ project_last_result_latest.json 保存失敗（HTML生成は継続）: {save_err}")
                self.root.after(0, lambda: self._set_status("✅ 完了", start_timer=False))
            else:
                self.root.after(0, lambda: self._set_status("❌ 生成失敗", start_timer=False))
                self.root.after(0, lambda: messagebox.showerror("エラー", "HTMLファイルの書き出しに失敗しました。"))

        threading.Thread(target=task, daemon=True).start()


    def _reformat_project(self):
        """フォーマットのみ再生成（Project）: project_last_result_latest.json からHTML再生成"""
        import os, json, threading, webbrowser
        import tkinter.messagebox as messagebox
        from datetime import datetime

        if not os.path.exists(PROJECT_LAST_RESULT_FILE):
            messagebox.showerror("エラー", "保存済みデータがありません。\n先に「🚀 プロジェクト俯瞰レポートを生成」を実行してください。")
            return

        self.btn_reformat_project.config(state=tk.DISABLED, text="⏳ フォーマット再生成中...")
        self._set_status("🎨 フォーマットのみ再生成中...", start_timer=True)

        def task():
            try:
                with open(PROJECT_LAST_RESULT_FILE, 'r', encoding='utf-8') as jf:
                    saved = json.load(jf)
                orig_threads_map = {}
                for proj, threads_slim in saved.get("orig_threads_slim", {}).items():
                    orig_threads_map[proj] = {
                        cid: {
                            "latest_entry_id": v.get("latest_entry_id", ""),
                            "latest_date": datetime.fromisoformat(v["latest_date_str"]) if v.get("latest_date_str") else datetime(2000, 1, 1)
                        }
                        for cid, v in threads_slim.items()
                    }
                knowledge = load_project_knowledge()
                path = self.reporter.generate_project_report(
                    saved["report_name"], saved["summaries"], orig_threads_map,
                    knowledge, saved["date_range_str"], saved["sort_order"],
                    saved["total_input"], saved["total_output"],
                    report_mode=saved.get("report_mode", "adopted"), reformat_mode=True
                )
                if path:
                    webbrowser.open(path)
            except Exception as e:
                _err = str(e)
                self.root.after(0, lambda: messagebox.showerror("エラー", f"フォーマット再生成に失敗しました:\n{_err}"))

            finally:
                self.root.after(0, lambda: self.btn_reformat_project.config(
                    state=tk.NORMAL, text="🎨 フォーマットのみ再生成"
                ))
                self.root.after(0, lambda: self._set_status("✅ フォーマット再生成完了", start_timer=False))

        threading.Thread(target=task, daemon=True).start()

    def _run_staff_overview(self):
        """
        スタッフの活動俯瞰レポートを生成する (V30 最終型整合版)
        """
        # V14追加: 単一ドロップダウンか、複数チェックボックスかを判定してターゲットリストを作成
        targets = []
        is_multi = any(v.get() for v in [self.var_sm_taizo, self.var_sm_nakai, self.var_sm_kajikawa, self.var_sm_saji, self.var_sm_oi, self.var_sm_najib])
        
        if is_multi:
            if self.var_sm_taizo.get(): targets.append("Taizo")
            if self.var_sm_nakai.get(): targets.append("Nakai")
            if self.var_sm_kajikawa.get(): targets.append("Kajikawa")
            if self.var_sm_saji.get(): targets.append("Saji")
            if self.var_sm_oi.get(): targets.append("Oi")
            if self.var_sm_najib.get(): targets.append("Najib")
        else:
            sn = self.var_staff_name.get().strip()
            if sn: targets.append(sn.capitalize())
            
        if not targets:
            messagebox.showwarning("警告", "対象スタッフが選択されていません。")
            return
            
        flags = {
            'from': self.var_staff_from.get(),
            'to': self.var_staff_to.get(),
            'cc': self.var_staff_cc.get()
        }
        if not any(flags.values()):
            messagebox.showwarning("警告", "関与フィルターを少なくとも1つ選択してください。")
            return

        self.project_knowledge = load_project_knowledge()
        if "staffs" not in self.project_knowledge:
            self.project_knowledge["staffs"] = {}
        for t in targets:
            if t not in self.project_knowledge["staffs"]:
                self.project_knowledge["staffs"][t] = {}
        
        period_str = self.var_staff_period.get()
        sort_order = self.var_staff_sort.get()
        days_map = {"任意時間(h)": -999, "12H": -12, "24H": 0, "3日間": 3, "過去1週間": 7, "過去2週間": 14, "過去1ヶ月": 30, "過去3ヶ月": 90}
        days = days_map.get(period_str, 7)
        if days == -999:
            try: days = -int(self.spin_staff_h.get())
            except: days = -1
                
        unread_only = self.var_staff_unread.get()
        from datetime import datetime, timedelta
        end_date = datetime.now()
        start_date = end_date - (timedelta(hours=abs(days)) if days <= 0 else timedelta(days=days))
        date_range_str = f"{start_date.strftime('%Y/%m/%d')} 〜 {end_date.strftime('%Y/%m/%d')}"
        
        self._set_status("🚀 スタッフ分析開始...", start_timer=True)
        self.summarizer.total_input_tokens = 0
        self.summarizer.total_output_tokens = 0

        def task():
            summaries = {}
            all_orig_threads = {}
            
            # V14追加: Project版と同様に対象リストをループ処理
            for staff_name in targets:
                self.root.after(0, lambda s=staff_name: self._set_status(f"⚙️ 抽出中: {s}"))
                
                conds_base = {
                    'subject': '', 'sender': '', 'category': '(すべて)', 'body_keyword': '',
                    'days': days, 'flag_status': None, 'unread_only': False,
                    'to_me': False, 'with_me': False, 'cc_me': False,
                    'strict_mode': False, 'folder_kw': ''
                }
                mails = []
                seen_ids = set()
                
                # V17修正: 検索エラーを防ぐためダブルクォートを外し、一意なアドレスプレフィックスに置換
                SEARCH_ALIASES = {"Oi": "yuto.oi"}
                search_term = SEARCH_ALIASES.get(staff_name, staff_name)
                exact_search_term = search_term
                
                try:
                    if flags.get('from'):
                        c_from = conds_base.copy(); c_from['sender'] = exact_search_term
                        res = self.outlook.search_mails_fast(c_from, "AND", True)
                        for m in res:
                            if m.get('entry_id') and m['entry_id'] not in seen_ids:
                                mails.append(m); seen_ids.add(m['entry_id'])
                    if flags.get('to') or flags.get('cc'):
                        c_other = conds_base.copy(); c_other['body_keyword'] = exact_search_term
                        res = self.outlook.search_mails_fast(c_other, "AND", True)
                        for m in res:
                            if m.get('entry_id') and m['entry_id'] not in seen_ids:
                                mails.append(m); seen_ids.add(m['entry_id'])
                except Exception as e: print(f"Search Error: {e}")

                if not mails:
                    summaries[staff_name] = {"project_status": [], "project_highlights": [{"text": "メールなし"}], "threads": []}
                else:
                    threads = self.outlook.group_by_thread(mails)
                    if unread_only: threads = {cid: t for cid, t in threads.items() if t.get('has_unread')}
                    all_orig_threads[staff_name] = threads
                    
                    res = self.summarizer.summarize_staff_threads(
                        staff_name, threads, self.project_knowledge,
                        progress_callback=lambda msg: self.root.after(0, lambda: self._set_status(msg))
                    )
                    
                    print(f"\n[DEBUG] --- Stage 2 Analysis Completed ---")
                    print(f"[DEBUG] Result Thread Count: {len(res.get('threads', []))}")
                    missing_ids = [th.get('thread_id') for th in res.get('threads', []) if th.get('thread_id') not in threads]
                    if missing_ids: print(f"[DEBUG] ⚠️ ID Mismatch Detected: {missing_ids}")
                    else: print(f"[DEBUG] ✅ All Thread IDs matched Outlook data.")
                    
                    summaries[staff_name] = res
                    if res.get("updated_history"):
                        self.project_knowledge["staffs"][staff_name]["history_summary"] = res["updated_history"]

            save_project_knowledge(self.project_knowledge)
            self.root.after(0, lambda: self._set_status("📝 レポート生成中..."))
            
            from pathlib import Path
            self.reporter.folder = Path(str(self.reporter.folder).strip())

            # V14修正: レポートのタイトルとファイル名を複数選択か単体かで分岐
            target_title = "Multi" if len(targets) > 1 else targets[0]

            _staff_report_mode = getattr(self, 'var_staff_report_mode', None)
            _staff_mode_val = _staff_report_mode.get() if _staff_report_mode else "adopted"
            path = self.reporter.generate_staff_report(
                target_title, summaries, all_orig_threads,
                self.project_knowledge, date_range_str, sort_order,
                self.summarizer.total_input_tokens, self.summarizer.total_output_tokens,
                report_mode=_staff_mode_val
            )
            
            if path:
                import webbrowser
                webbrowser.open(path)
                try:
                    orig_threads_slim = {}
                    for staff, threads in all_orig_threads.items():
                        orig_threads_slim[staff] = {
                            cid: {
                                "latest_entry_id": t.get("latest_entry_id", ""),
                                "latest_date_str": t["latest_date"].isoformat() if t.get("latest_date") else ""
                            }
                            for cid, t in threads.items()
                        }
                    with open(STAFF_LAST_RESULT_FILE, 'w', encoding='utf-8') as jf:
                        json.dump({
                            "target_title": target_title,
                            "summaries": summaries,
                            "orig_threads_slim": orig_threads_slim,
                            "date_range_str": date_range_str,
                            "sort_order": sort_order,
                            "total_input": self.summarizer.total_input_tokens,
                            "total_output": self.summarizer.total_output_tokens,
                            "report_mode": _staff_mode_val
                        }, jf, ensure_ascii=False)
                    print("💾 staff_last_result_latest.json 保存完了")
                    self.root.after(0, lambda: self.btn_reformat_staff.config(state=tk.NORMAL))
                except Exception as save_err:
                    print(f"⚠️ staff_last_result_latest.json 保存失敗（HTML生成は継続）: {save_err}")
                self.root.after(0, lambda: self._set_status("✅ 完了", start_timer=False))
            else:
                self.root.after(0, lambda: self._set_status("❌ 生成失敗", start_timer=False))

            self.root.after(0, lambda: self.cb_staff_name.config(values=list(self.project_knowledge.get("staffs", {}).keys())))

        import threading
        threading.Thread(target=task, daemon=True).start()        
        

    def _reformat_staff(self):
        """フォーマットのみ再生成（Staff）: staff_last_result_latest.json からHTML再生成"""
        import os, json, threading, webbrowser
        import tkinter.messagebox as messagebox
        from datetime import datetime

        if not os.path.exists(STAFF_LAST_RESULT_FILE):
            messagebox.showerror("エラー", "保存済みデータがありません。\n先に「🚀 スタッフの活動俯瞰レポートを生成」を実行してください。")
            return

        self.btn_reformat_staff.config(state=tk.DISABLED, text="⏳ フォーマット再生成中...")
        self._set_status("🎨 フォーマットのみ再生成中...", start_timer=True)

        def task():
            try:
                with open(STAFF_LAST_RESULT_FILE, 'r', encoding='utf-8') as jf:
                    saved = json.load(jf)
                orig_threads_map = {}
                for staff, threads_slim in saved.get("orig_threads_slim", {}).items():
                    orig_threads_map[staff] = {
                        cid: {
                            "latest_entry_id": v.get("latest_entry_id", ""),
                            "latest_date": datetime.fromisoformat(v["latest_date_str"]) if v.get("latest_date_str") else datetime(2000, 1, 1)
                        }
                        for cid, v in threads_slim.items()
                    }
                knowledge = load_project_knowledge()
                path = self.reporter.generate_staff_report(
                    saved["target_title"], saved["summaries"], orig_threads_map,
                    knowledge, saved["date_range_str"], saved["sort_order"],
                    saved["total_input"], saved["total_output"],
                    report_mode=saved.get("report_mode", "adopted"), reformat_mode=True
                )
                if path:
                    webbrowser.open(path)
            except Exception as e:
                _err = str(e)
                self.root.after(0, lambda: messagebox.showerror("エラー", f"フォーマット再生成に失敗しました:\n{_err}"))
            finally:
                self.root.after(0, lambda: self.btn_reformat_staff.config(
                    state=tk.NORMAL, text="🎨 フォーマットのみ再生成"
                ))
                self.root.after(0, lambda: self._set_status("✅ フォーマット再生成完了", start_timer=False))

        threading.Thread(target=task, daemon=True).start()
        
    def _update_folder_combobox(self, folders):
        current_val = self.e_fld.get()
        sorted_folders = sorted([f for f in folders if f])
        self.e_fld.config(values=sorted_folders)
        self.e_fld.set(current_val)

    def _sort_tree(self, col, reverse):
        items = [(self.tree.set(k, col), k) for k in self.tree.get_children("")]
        items.sort(reverse=reverse)
        for index, (val, k) in enumerate(items):
            self.tree.move(k, "", index)
        self.tree.heading(col, command=lambda: self._sort_tree(col, not reverse))

    def _get_days(self):
        p = self.v_prd.get()
        if p == "任意時間(h)":
            return -int(self.spin_search_h.get())
        return {"12H":-12, "24H":0, "今日":1, "3日間":3, "1週間":7, "2週間":14, "1ヶ月":30, "2ヶ月":60, "3ヶ月":90}.get(p, 7)
        
    def _get_flag_status(self):
        v = self.v_flag.get()
        if v == "フラグあり": return "active"
        if v == "フラグなし": return "none"
        return None


    def _search(self):
        if getattr(self, 'v_all_me', None) and self.v_all_me.get():
            if not messagebox.askyesno("⚠️ 大量抽出の警告", "「ALL (宛先無視)」が選択されています。メーリングリスト等も含め全件抽出するため、APIの処理時間とコストが大幅に増加する可能性があります。\n\n処理を開始してもよろしいですか？"):
                return
                
        conds = {
            'subject': self.e_sub.get(), 'sender': self.e_snd.get(),
            'category': self.v_cat.get(), 'body_keyword': self.e_kwd.get(),
            'days': self._get_days(),
            'flag_status': self._get_flag_status(),
            'unread_only': self.v_unread.get(),
            'to_me': self.v_to_me.get(),
            'with_me': self.v_with_me.get(),
            'cc_me': self.v_cc_me.get(),
            'all_me': getattr(self, 'v_all_me', tk.BooleanVar(value=False)).get(),
            'strict_mode': self.v_strict.get(),
            'folder_kw': self.e_fld.get()
        }
        self._run_search(conds)


    def _search_external(self):
        if not self.excluded_domains:
            messagebox.showinfo("info", "除外ドメインが登録されていません。")
            return
        conds = {
            'subject': self.e_sub.get(), 'sender': self.e_snd.get(),
            'category': self.v_cat.get(), 'body_keyword': self.e_kwd.get(),
            'days': self._get_days(),
            'filter_domains': self.excluded_domains,
            'flag_status': self._get_flag_status(),
            'unread_only': self.v_unread.get(),
            'to_me': self.v_to_me.get(),
            'with_me': self.v_with_me.get(),
            'cc_me': self.v_cc_me.get(),
            'all_me': getattr(self, 'v_all_me', tk.BooleanVar(value=False)).get(),
            'strict_mode': self.v_strict.get(),
            'folder_kw': self.e_fld.get()
        }
        self._run_search(conds)

    def _search_ad(self):
        days = self._get_days()
        unread_only = self.v_unread.get()
        self._set_status("🔍 検索中...")
        def task():
            try:
                mails = self.outlook.search_ad_mails(days, self.excluded_domains, unread_only)
                self.threads = self.outlook.group_by_thread(mails)
                
                folders = {t.get('latest_folder', '') for t in self.threads.values()}
                self.root.after(0, lambda f=folders: self._update_folder_combobox(f))
                
                self._filter_threads_loose({'folder_kw': self.e_fld.get()})
                self.root.after(0, self._update)
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Error", str(e)))
        threading.Thread(target=task, daemon=True).start()

    def _search_rss(self):
        self._set_status("📰 RSS記事を取得中...")
        def task():
            try:
                mails = self.outlook.get_unread_rss_feeds()
                self.threads = self.outlook.group_by_thread(mails)
                
                folders = {t.get('latest_folder', '') for t in self.threads.values()}
                self.root.after(0, lambda f=folders: self._update_folder_combobox(f))
                
                self._filter_threads_loose({'folder_kw': self.e_fld.get()})
                self.root.after(0, self._update)
                if not mails:
                    self.root.after(0, lambda: messagebox.showinfo("info", "未読のRSS記事はありません。"))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Error", str(e)))
        threading.Thread(target=task, daemon=True).start()

    def _refresh_display(self):
        """Outlook通信を行わず、現在のUI条件でメモリ上のスレッドを高速リフレッシュする (V20)"""
        if not self.threads:
            return

        conds = {
            'category': self.v_cat.get(),
            'unread_only': self.v_unread.get(),
            'flag_status': self._get_flag_status(),
            'to_me': self.v_to_me.get(),
            'with_me': self.v_with_me.get(),
            'cc_me': self.v_cc_me.get(),
            'folder_kw': self.e_fld.get()
        }
        
        # 既存の絞り込みロジックを再利用してメモリ上の self.threads を「引き算」する
        self._filter_threads_loose(conds)
        
        # 削除されたスレッドのIDを selected からも除去（自爆防止）
        self.selected = {cid for cid in self.selected if cid in self.threads}
        
        # 画面描画の更新
        self._update()
        
        # チェック状態を復元（selected に残っているものを ✓ に戻す）
        for cid in self.selected:
            if self.tree.exists(cid):
                self.tree.set(cid, "sel", "☑")
                self.tree.item(cid, tags=self._row_tags(cid))
        
        self._chk_btns()
        self._set_status(f"リフレッシュ完了: {len(self.threads)}件")

    def _run_search(self, conds):
        self._set_status("🔍 検索中...")
        def task():
            try:
                if self.outlook.check_and_update_outlook_restart_state():
                    try:
                        self.outlook.sync_forced_unread_from_outlook_state()
                    except Exception as sync_err:
                        print(f"Outlook再起動同期エラー: {sync_err}")
                mails = self.outlook.search_mails_fast(conds, "AND", True)
                self.threads = self.outlook.group_by_thread(mails)
                
                folders = {t.get('latest_folder', '') for t in self.threads.values()}
                self.root.after(0, lambda f=folders: self._update_folder_combobox(f))
                
                if not conds.get('strict_mode'):
                    self._filter_threads_loose(conds)
                
                self.root.after(0, self._update)
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Error", str(e)))
        threading.Thread(target=task, daemon=True).start()

    def _filter_threads_loose(self, conds):
        removals = []
        for cid, t in self.threads.items():
            fld_kw = conds.get('folder_kw', '').strip().lower()
            if fld_kw:
                t_fld = (t.get('latest_folder') or '').lower()
                if fld_kw not in t_fld:
                    removals.append(cid)
                    continue
                    
            if conds.get('unread_only') and not t['has_unread']:
                removals.append(cid)
                continue
            
            fst = conds.get('flag_status')
            if fst == 'active' and not t['is_flagged']:
                removals.append(cid)
                continue
            elif fst == 'none' and t['is_flagged']:
                removals.append(cid)
                continue
                
            cat_cond = conds.get('category')
            if cat_cond:
                if cat_cond == "(項目なし)":
                    if t['all_categories']:
                        removals.append(cid)
                        continue
                elif cat_cond != "(すべて)":
                    found = False
                    for c in t['all_categories']:
                        if cat_cond.lower() in c.lower():
                            found = True
                            break
                    if not found:
                        removals.append(cid)
                        continue
            
            check_to = conds.get('to_me')
            check_with = conds.get('with_me')
            check_cc = conds.get('cc_me')
            if check_to or check_with or check_cc:
                hit = False
                for m in t['mails']:
                    r = m['routing']
                    if check_to and r == 'to_me':
                        hit = True
                        break
                    if check_with and r == 'with_me':
                        hit = True
                        break
                    if check_cc and self.outlook.user_smtp_address: 
                        pass
                if (check_to or check_with) and not hit:
                    removals.append(cid)
                    continue

        for cid in removals:
            del self.threads[cid]

    def _row_tags(self, cid: str):
        tags = []
        try:
            if cid in self.selected: tags.append("checked")
        except: pass
        try:
            d_tag = self.threads.get(cid, {}).get('display_tag', 'normal')
            if d_tag != 'normal': tags.append(d_tag)
        except: pass
        return tuple(tags)

    def _update(self):
        self.tree.delete(*self.tree.get_children())
        self.selected.clear()
        for cid, t in self.threads.items():
            self.tree.insert("", "end", iid=cid, tags=self._row_tags(cid), values=(
                "☐", 
                t['categories_str'], 
                t['topic'][:80], 
                t['mail_count'],
                ",".join(t['participants'][:2]),
                t['latest_date'].strftime('%m/%d %H:%M'),
                t.get('latest_folder', ''),
                "🚩" if t['is_flagged'] else "⚐"
            ))
        self._chk_btns()
        self._set_status(f"完了: {len(self.threads)}件")


    def _toggle_thread_flag(self, cid):
        thread = self.threads.get(cid)
        if not thread: return
        eid = thread['latest_entry_id']
        def task():
            new_state = self.outlook.toggle_flag(eid)
            thread['is_flagged'] = new_state
            self.root.after(0, lambda: self.tree.set(cid, "flg", "🚩" if new_state else "⚐"))
        threading.Thread(target=task, daemon=True).start()

    def _all(self):
        for i in self.tree.get_children():
            self.selected.add(i)
            self.tree.set(i, "sel", "☑")
            self.tree.item(i, tags=self._row_tags(i))
        self._chk_btns()
    
    def _none(self):
        self.selected.clear()
        for i in self.tree.get_children():
            self.tree.set(i, "sel", "☐")
            self.tree.item(i, tags=self._row_tags(i))
        self._chk_btns()

    def _chk_btns(self):
        s = "normal" if self.selected else "disabled"
        self.btn_gen.config(state=s)
        self.btn_excl.config(state=s)
        self.btn_read.config(state=s)
        self.btn_mark_unread.config(state=s)
        self.btn_promo.config(state=s)
        self.btn_remove_flag.config(state=s)
        
        s_all = "normal" if self.tree.get_children() else "disabled"
        if hasattr(self, 'btn_all_read'):
            self.btn_all_read.config(state=s_all)

    def _all_and_mark_read(self):
        if not self.tree.get_children(): return
        self._all()
        self._mark_read()

    def _on_tree_double_click(self, event):
        item = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if col == "#8": return 
        if item:
            topic = self.threads[item]['topic']
            eid = self.threads[item]['latest_entry_id']
            if eid:
                threading.Thread(target=self.outlook.show_thread_in_explorer, args=(topic, eid), daemon=True).start()

    def _register_exclude(self):
        if not messagebox.askyesno("確認", "選択したメールのドメインを除外リストに登録しますか？"): return
        new_domains = set()
        for cid in list(self.selected):
            for mail in self.threads[cid]['mails']:
                if '@' in mail['sender_email']:
                    d = mail['sender_email'].split('@')[-1].lower()
                    if d != 'nexperia.com': new_domains.add(d)
            self.tree.delete(cid)
            del self.threads[cid]
            self.selected.remove(cid)
        
        if new_domains:
            self.excluded_domains.update(new_domains)
            save_excluded_domains(self.excluded_domains)
            self._chk_btns()
            messagebox.showinfo("完了", "登録しました:\n" + "\n".join(new_domains))

    def _mark_read(self):
        target_cids = list(self.selected)
        ids = []
        for cid in target_cids:
            for mail in self.threads[cid]['mails']:
                ids.append(mail['entry_id'])
        if not ids: return
        self._set_status("既読処理中...")
        
        def task():
            c = self.outlook.mark_mails_read(ids)
            for cid in target_cids:
                if cid in self.threads:
                    for m in self.threads[cid]['mails']:
                        m['unread'] = False
            
            def update_and_restore():
                self._recalc_thread_status(target_cids)
                self._update()
                for cid in target_cids:
                    if self.tree.exists(cid):
                        self.selected.add(cid)
                        self.tree.set(cid, "sel", "☑")
                        self.tree.item(cid, tags=self._row_tags(cid))
                self._chk_btns()
                self._set_status(f"完了: {c}通を既読にしました")
                
            self.root.after(0, update_and_restore)
            
        threading.Thread(target=task, daemon=True).start()

    def _mark_unread(self):
        target_cids = list(self.selected)
        ids = []
        for cid in target_cids:
            for mail in self.threads[cid]['mails']:
                ids.append(mail['entry_id'])
        if not ids: return
        self._set_status("未読処理中...")
        
        def task():
            c = self.outlook.mark_mails_unread(ids)
            for cid in target_cids:
                if cid in self.threads:
                    for m in self.threads[cid]['mails']:
                        m['unread'] = True
            
            def update_and_restore():
                self._recalc_thread_status(target_cids)
                self._update()
                for cid in target_cids:
                    if self.tree.exists(cid):
                        self.selected.add(cid)
                        self.tree.set(cid, "sel", "☑")
                        self.tree.item(cid, tags=self._row_tags(cid))
                self._chk_btns()
                self._set_status(f"完了: {c}通を未読にしました")
                
            self.root.after(0, update_and_restore)
            
        threading.Thread(target=task, daemon=True).start()

    def _remove_flags(self):
        ids = []
        for cid in self.selected:
            for mail in self.threads[cid]['mails']:
                ids.append(mail['entry_id'])
        if not ids: return
        self._set_status("フラグ解除中...")
        def task():
            c = self.outlook.remove_flags(ids)
            self.root.after(0, lambda: self._set_status(f"完了: {c}通のフラグを解除しました"))
        threading.Thread(target=task, daemon=True).start()

    def _mark_junk_deleted_read(self):
        self._set_status("対象メール検索中...")
        def task():
            mails = self.outlook.get_junk_deleted_unread_mails()
            if not mails:
                self.root.after(0, lambda: messagebox.showinfo("info", "対象の未読メールはありません。"))
                self.root.after(0, lambda: self._set_status("対象なし"))
                return
            
            self.threads = self.outlook.group_by_thread(mails)
            folders = {t.get('latest_folder', '') for t in self.threads.values()}
            self.root.after(0, lambda f=folders: self._update_folder_combobox(f))
            self.root.after(0, self._update_and_select_all_for_junk)

        threading.Thread(target=task, daemon=True).start()

    def _update_and_select_all_for_junk(self):
        self._update()
        self._all() 
        if messagebox.askyesno("確認", f"迷惑メール/削除済みアイテムの未読 {len(self.threads)} 件を表示しました。\nこれらを全て「既読」にしますか？"):
            self._mark_read() 

    def _move_to_promo(self):
        if not messagebox.askyesno("確認", "選択スレッドをPromotionへ移動しますか？"): return
        target_cids = list(self.selected)
        ids = []
        for cid in target_cids:
            for mail in self.threads[cid]['mails']:
                ids.append(mail['entry_id'])
        def task():
            c = self.outlook.move_mails_to_promotion(ids)
            self.root.after(0, lambda: self._on_move_done(target_cids, c))
        threading.Thread(target=task, daemon=True).start()

    def _on_move_done(self, cids, count):
        for cid in cids:
            if cid in self.threads:
                self.threads[cid]['latest_folder'] = "Promotion"
                try:
                    self.tree.set(cid, "fld", "Promotion")
                except:
                    pass
        self._chk_btns()
        messagebox.showinfo("完了", f"{count}通を移動しました")

    def _ask_long_text_action(self, total_len: int) -> tuple[int, bool]:
        import tkinter as tk
        dialog = tk.Toplevel(self.root)
        dialog.title("⚠️ スレッドの文字数超過警告")
        dialog.geometry("550x350")
        dialog.attributes('-topmost', True)
        dialog.grab_set()
        
        dialog.geometry("+%d+%d" % (self.root.winfo_x() + 50, self.root.winfo_y() + 50))
        
        result_choice = [1] 
        apply_to_all = tk.BooleanVar(value=False)
        
        msg = f"スレッドの文字数が10,000文字を超過しています（約 {total_len:,} 文字）。\nそのまま要約を行うとAPIエラーやフリーズが発生する可能性があります。\n処理方法を選択してください。"
        tk.Label(dialog, text=msg, justify=tk.LEFT, padx=15, pady=15, font=("", 10)).pack(anchor="w")
        
        def set_choice(c):
            result_choice[0] = c
            dialog.destroy()
            
        tk.Button(dialog, text="[1] 先頭(2k)と末尾(8k)を残して短く切り詰める (推奨)", bg="#f0fdfa", font=("", 10, "bold"), command=lambda: set_choice(1)).pack(fill=tk.X, padx=15, pady=5)
        tk.Button(dialog, text="[2] 要約せず、テキストのみを出力する (最速・軽量)", bg="#f8fafc", command=lambda: set_choice(2)).pack(fill=tk.X, padx=15, pady=5)
        tk.Button(dialog, text="[3] 警告を無視してフルテキストで要約する (非推奨)", bg="#fee2e2", command=lambda: set_choice(3)).pack(fill=tk.X, padx=15, pady=5)
        
        tk.Checkbutton(dialog, text="以降、1万文字を超えるスレッドはすべて同じ処理にする", variable=apply_to_all, font=("", 10, "bold"), fg="#ea580c").pack(pady=15)
        
        dialog.protocol("WM_DELETE_WINDOW", lambda: set_choice(1))
        self.root.wait_window(dialog)
        
        return result_choice[0], apply_to_all.get()


    def _gen(self):
        selected_count = len(self.selected)
        if selected_count >= 2:
            if not messagebox.askyesno("確認", f"{selected_count}件のスレッドのレポートを作成しますが、よろしいですか？"):
                return
                
        self._set_status("📝 生成中...")
        sel = {c: self.threads[c] for c in self.selected}
        
        large_threads = []
        max_len = 0
        for cid, t in sel.items():
            if t['mails']:
                t_len = sum(len(str(m['body'])) for m in t['mails'])
                if t_len > 10000:
                    large_threads.append(t['topic'])
                    if t_len > max_len:
                        max_len = t_len
        
        self.long_text_session_choice = getattr(self, 'long_text_session_choice', None)
        choice = 1
        
        if large_threads:
            if self.long_text_session_choice is None:
                c, apply_all = self._ask_long_text_action(max_len)
                choice = c
                if apply_all:
                    self.long_text_session_choice = c
            else:
                choice = self.long_text_session_choice
                    
        pl_str = self.v_past_limit.get()
        past_limit = 300000 if "無制限" in pl_str else int(re.search(r'\d+', pl_str).group()) if re.search(r'\d+', pl_str) else 800

        def task():
            res = self.summarizer.summarize_multiple_threads(sel, past_limit=past_limit, long_text_choice=choice)
            path = self.reporter.generate_report(sel, res, {})
            webbrowser.open(path)
            self._set_status("✅ 完了")
        threading.Thread(target=task, daemon=True).start()

    def _recalc_thread_status(self, cids):
        for cid in cids:
            if cid not in self.threads:
                continue
            t = self.threads[cid]
            t['has_unread'] = any(m['unread'] for m in t['mails'])
            has_unread_tome = any(m['unread'] and m['routing'] == 'to_me' for m in t['mails'])
            has_unread_withme = any(m['unread'] and m['routing'] == 'with_me' for m in t['mails'])
            has_tome = any(m['routing'] == 'to_me' for m in t['mails'])
            has_withme = any(m['routing'] == 'with_me' for m in t['mails'])
            
            if t['has_unread']:
                if has_unread_tome: t['display_tag'] = 'tome_unread'
                elif has_unread_withme: t['display_tag'] = 'withme_unread'
                else: t['display_tag'] = 'other_unread'
            else:
                if has_tome: t['display_tag'] = 'tome_read'
                elif has_withme: t['display_tag'] = 'withme_read'
                else: t['display_tag'] = 'other_read'

    def _load_cats(self):
        def task():
            try:
                cats = self.outlook.get_categories()
                self.root.after(0, lambda: self.c_cat.config(values=["(すべて)", "(項目なし)"]+cats))
            except:
                pass
        threading.Thread(target=task, daemon=True).start()

    def _set_api(self):
        d = tk.Toplevel(self.root)
        e = ttk.Entry(d, width=40)
        e.pack()
        e.insert(0, self.config['gemini_api_key'])
        def save():
            self.config['gemini_api_key'] = e.get()
            save_config(self.config)
            self.summarizer.api_key = e.get()
            d.destroy()
        ttk.Button(d, text="Save", command=save).pack()


if __name__ == "__main__":
    app = MailManagerGUI()
    app.root.mainloop()
