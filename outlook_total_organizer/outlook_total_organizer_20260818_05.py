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
import ctypes
import ctypes.wintypes
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys
# google.genai の types は types.GenerateContentConfig(...) の構築に引き続き使用する。
# 一方 genai.Client はネットワーク呼び出しを行うため使用をやめ、下記の互換シム
# (_CommonGeminiClient) に置き換えた(会社PCからGemini APIへの直接アクセスが
# 遮断されたため、共通モジュール gemini_client.py の自宅PCプロキシ自動
# フォールバック機構を経由するようにした)。
from google.genai import types
import requests
from bs4 import BeautifulSoup


# ============================================================
# Gemini 共通クライアント(gemini_client.py)への互換シム
# ============================================================
# 会社PCからGemini APIへの直接アクセスが遮断される事象(2026-08-10頃)を受け、
# rtocs_organizer / analog_ic_se_strategy_organizer と同様に、共通モジュール
# gemini_client.py の generate_advanced() 経由(直接呼び出しが失敗したら自宅PC
# プロキシへ自動フォールバック)へ移行した。
#
# 本ツールは google.genai SDK の呼び出しがファイル内の6箇所に分散していたため、
# 6箇所すべてを個別に書き換えるのではなく、genai.Client と同じインターフェース
# だけを持つ薄い互換シムを1つ用意し、genai.Client(api_key=...) の生成箇所のみを
# 差し替える方式にした。これにより、レスポンスを読む側のコード
# (response.text / response.usage_metadata.prompt_token_count 等)や
# types.GenerateContentConfig(...) による config 構築は一切変更していない。
#
# 必要な環境変数(会社PC):
#   GEMINI_API_KEY   … 直接呼び出し用(gemini_client.py 側が読む)
#   GEMINI_PROXY_URL … 自宅PCプロキシのURL(直接呼び出し失敗時のフォールバック先)
#   GEMINI_COMMON_DIR… gemini_client.py の置き場所を明示したい場合のみ(任意)
# GUI設定画面のAPIキー入力欄(json/mail_manager_config.json の gemini_api_key)は
# 使用されなくなった(他2ツールと同様、環境変数へ統一)。

_COMMON_DIR = os.environ.get("GEMINI_COMMON_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "common")
if _COMMON_DIR not in sys.path:
    sys.path.insert(0, _COMMON_DIR)

# gemini_client のインポートはここで試みるが、失敗してもツール自体は起動できる
# ようにする(メール検索・仕分けなどAIを使わない機能まで巻き添えで落とさないため)。
# 実際にAI呼び出しが行われた時点で、原因が分かるエラーメッセージを出す。
try:
    from gemini_client import generate_advanced as _generate_advanced
    _GEMINI_CLIENT_IMPORT_ERROR = None
except Exception as _e:
    _generate_advanced = None
    _GEMINI_CLIENT_IMPORT_ERROR = _e


def _schema_to_jsonable(schema):
    """types.GenerateContentConfig(response_schema=...) に渡されたスキーマを、
    REST APIのpayloadへそのまま載せられる素のdict/listへ変換する。
    本ツールは元々スキーマを素のdictで渡しているため通常は変換不要だが、
    google-genai SDKのバージョンによってはpydanticモデル(types.Schema)へ
    自動変換される場合があるため、その場合もJSON化できるようにしておく。"""
    if schema is None or isinstance(schema, (dict, list, str, int, float, bool)):
        return schema
    # pydantic v2 (model_dump) / v1 (dict) の両方に対応。REST APIのフィールド名は
    # camelCase(例: propertyOrdering)なので by_alias=True で別名を使う。
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


class _CommonUsageMetadata:
    """response.usage_metadata 互換(トークン計測用)。"""
    def __init__(self, usage: dict):
        usage = usage if isinstance(usage, dict) else {}
        self.prompt_token_count = usage.get("promptTokenCount", 0)
        self.candidates_token_count = usage.get("candidatesTokenCount", 0)


class _CommonGeminiResponse:
    """client.models.generate_content(...) の戻り値互換。
    呼び出し側は response.text と response.usage_metadata しか参照しないため、
    その2つだけを提供する。"""
    def __init__(self, raw: dict):
        try:
            self.text = raw["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError):
            self.text = ""
        self.usage_metadata = _CommonUsageMetadata(
            raw.get("usageMetadata", {}) if isinstance(raw, dict) else {}
        )


class _CommonGeminiModels:
    """client.models 互換。"""
    def generate_content(self, model=None, contents=None, config=None):
        if _generate_advanced is None:
            raise RuntimeError(
                "Gemini共通モジュール(gemini_client.py)を読み込めませんでした。"
                f"探索したパス: {_COMMON_DIR} / 元のエラー: {_GEMINI_CLIENT_IMPORT_ERROR}\n"
                "gemini-common-tools を配置し、必要なら環境変数 GEMINI_COMMON_DIR で"
                "gemini_client.py のあるフォルダを指定してください。"
            )
        payload = {"contents": [{"parts": [{"text": contents}]}]}
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
        # model は明示的に渡す(共通モジュール側の既定モデルに勝手にフォールバック
        # されると、UI上の表示と実際に使われるモデルが食い違うため)。
        raw = _generate_advanced(payload, model=model)
        # 直接呼び出しが遮断状態から復活したかどうかを観測する(復活時のみ通知)。
        # ここでの失敗が本来のAI呼び出しを巻き添えにしないよう、例外は握りつぶす。
        try:
            _observe_gemini_direct_state()
        except Exception:
            pass
        return _CommonGeminiResponse(raw)


class _CommonGeminiClient:
    """genai.Client(api_key=...) の代替。
    api_key は gemini_client.py 側が環境変数 GEMINI_API_KEY から読むため、
    ここでは互換性のために受け取るだけで使用しない。"""
    def __init__(self, api_key=None):
        self.models = _CommonGeminiModels()


# ------------------------------------------------------------
# Gemini API 直接呼び出しの「復活」検知とお知らせ
# ------------------------------------------------------------
# gemini_client.py は、直接呼び出しが失敗すると一定時間(既定30分。環境変数
# GEMINI_RETRY_DIRECT_AFTER_SECONDS で変更可)は直接呼び出しをスキップして
# プロキシ経由に固定し、猶予期間が過ぎるとまた直接呼び出しから試す、という
# 動作をする。会社側の遮断が解除された際に、それに気づけるようにするための仕組み。
#
# 本ツール側では「遮断されていた状態から直接呼び出しが成功する状態へ変わった」
# ことを検知し、その日の初回に限りポップアップでお知らせする。
# 判定方法: generate_advanced() が成功した直後に gemini_client 側の
# 「直接呼び出し無効化中」フラグを見る。gemini_client の実装上、
#   直接成功 -> フラグは False のまま / 直接失敗 -> _disable_direct() で True になり
#   プロキシへフォールバック / 既に無効化中 -> True のままプロキシへ
# となるため、呼び出し成功後にフラグが False なら「直接呼び出しが使われた」と判定できる。
#
# 注意: 単に「直接呼び出しが成功した」だけでは通知しない(遮断が起きていない
# 通常運用では毎日ポップアップが出てしまうため)。一度でも遮断を観測した後に
# 成功した場合のみ「復活」として通知する。
GEMINI_DIRECT_NOTICE_FILE = "json/gemini_direct_notice.json"
_gemini_notice_lock = threading.Lock()
_gemini_direct_restored_callback = None


def set_gemini_direct_restored_callback(fn):
    """直接呼び出しが復活した際に呼ぶコールバックを登録する(GUI側から登録する)。
    AI呼び出しはワーカースレッドから行われるため、コールバック側で
    root.after()を使ってメインスレッドへ処理を戻すこと。"""
    global _gemini_direct_restored_callback
    _gemini_direct_restored_callback = fn


def _gemini_direct_is_disabled():
    """gemini_client側の「直接呼び出し無効化中」状態を返す。
    共通モジュールが読めない・実装が変わった等で判定できない場合はNoneを返す
    (その場合は何も通知しない = 誤検知しない側に倒す)。"""
    try:
        import gemini_client as _gc
        fn = getattr(_gc, "_is_direct_disabled", None)
        if callable(fn):
            return bool(fn())
    except Exception:
        pass
    return None


def _load_gemini_notice() -> dict:
    try:
        with open(GEMINI_DIRECT_NOTICE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_gemini_notice(data: dict):
    try:
        os.makedirs("json", exist_ok=True)
        with open(GEMINI_DIRECT_NOTICE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        print(f"Gemini直接接続の通知状態の保存に失敗: {e}")


def _observe_gemini_direct_state():
    """AI呼び出しが成功するたびに、直接呼び出しが使えたかどうかを観測する。
    「遮断されていた状態から復活した」ことを検知したら、その日の初回に限り
    登録済みコールバック(GUIのポップアップ)を呼ぶ。
    AI呼び出しは複数のワーカースレッドから並行して行われるため、
    状態ファイルの読み書きはロックで保護する。"""
    disabled = _gemini_direct_is_disabled()
    if disabled is None:
        return

    cb = None
    with _gemini_notice_lock:
        state = _load_gemini_notice()
        if disabled:
            # 現在は遮断中(プロキシ経由)。あとで「復活」を検知できるよう、
            # 遮断を観測したことを記録しておく。
            if not state.get("direct_was_blocked"):
                state["direct_was_blocked"] = True
                _save_gemini_notice(state)
            return
        # ここに来た = 直接呼び出しが成功している
        if not state.get("direct_was_blocked"):
            # 一度も遮断を観測していない(＝通常運用)。毎日通知しないよう何もしない。
            return
        today = datetime.now().strftime("%Y-%m-%d")
        if state.get("last_notified_date") == today:
            return  # その日は通知済み
        state["last_notified_date"] = today
        state["direct_was_blocked"] = False
        _save_gemini_notice(state)
        cb = _gemini_direct_restored_callback

    # コールバックはロックの外で呼ぶ(GUIスケジューリング中にロックを保持しない)
    if cb:
        try:
            cb()
        except Exception as e:
            print(f"Gemini直接接続復活の通知に失敗: {e}")


def gemini_credentials_available() -> bool:
    """AI呼び出しが行える見込みがあるかどうかの事前チェック。
    移行後の認証情報は環境変数(GEMINI_API_KEY / GEMINI_PROXY_URL)が主で、
    直接呼び出しが遮断されていてもプロキシ経由で成功しうるため、
    どちらか一方でも設定されていれば「呼び出し可能」と判断する。
    旧来のGUI設定(json/mail_manager_config.json の gemini_api_key)しか
    設定していない環境でも止めないよう、そちらも見る。"""
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMINI_PROXY_URL"):
        return True
    try:
        return bool(load_config().get("gemini_api_key", ""))
    except Exception:
        return False


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
COCKPIT_V2_LAST_RESULT_FILE = "json/cockpit_v2_last_result.json"
PROJECT_LAST_RESULT_FILE = "json/project_last_result_latest.json"
STAFF_LAST_RESULT_FILE   = "json/staff_last_result_latest.json"

ACTION_STATUS_FILE            = "json/action_status.json"
ACTION_DASHBOARD_LAST_RESULT_FILE = "json/action_dashboard_last_result.json"
OUTLOOK_RESTART_STATE_FILE    = "json/outlook_restart_state.json"
COCKPIT_V2_PROJECT_OVERRIDE_FILE = "json/cockpit_v2_project_overrides.json"
COCKPIT_V2_ACKNOWLEDGED_FILE = "json/cockpit_v2_acknowledged.json"
REVIEW_MANUAL_FILE = "json/review_manual_items.json"
REVIEW_LAST_RESULT_FILE = "json/review_last_result.json"
REVIEW_CACHE_DIR = "analysis_cache/review_monthly"
# 振り返りタブ(スタッフ拡張): 対象者ごとのゴール(KPI)定義。Nexperiaのゴールシートは全ページ
# "confidential"のため、.pyへ直書きせずこのファイルに外出しする(.gitignoreで除外必須)。
REVIEW_PERSON_GOALS_FILE = "json/review_person_goals.json"

SEARCH_FOLDER_TOME = "未(ToMe)"
SEARCH_FOLDER_WITHME = "未(WithMe)"
SEARCH_FOLDER_CCME = "未(CcMe)"

# 振り返りタブ用: ユーザーがOutlookリボンの「アーカイブ」ボタン等で手動退避させたメールが
# 入っている可能性のあるフォルダの名前候補。組織・ユーザーによって名称が異なる
# (実機調査で「アーカイブ」「Archive」「Go2Archive」の3通りを確認済み)。
# このフォルダは受信・送信メールが混在しているため、受信トレイ/送信済みアイテムとは別に
# 横断的に探して丸ごとスキャン対象へ加える(送信/受信の判定はsender_emailベースの
# 既存ロジックに委ねる)。
MANUAL_ARCHIVE_FOLDER_NAMES = ["アーカイブ", "Archive", "Go2Archive"]


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

def load_cockpit_v2_project_overrides():
    """統括コックピットv2で、カード上のプロジェクト再分類UIから手動で変更された
    プロジェクト割り当てを読み込む({conversation_id: プロジェクト名})。
    未指定のスレッドは、従来通りメール取得元のプロジェクトのまま扱われる。"""
    os.makedirs("json", exist_ok=True)
    if os.path.exists(COCKPIT_V2_PROJECT_OVERRIDE_FILE):
        try:
            with open(COCKPIT_V2_PROJECT_OVERRIDE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: return {}
    return {}

def save_cockpit_v2_project_overrides(data):
    os.makedirs("json", exist_ok=True)
    with open(COCKPIT_V2_PROJECT_OVERRIDE_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_cockpit_v2_acknowledged():
    """統括コックピットv2で「✅ 確認済み」した案件を読み込む
    ({conversation_id: {"mail_count": スレッドのメール件数, "acknowledged_at": ISO時刻}})。
    action_status.json(進捗/優先度)とは別の、コックピットv2専用の状態。アクションタブの
    進捗とは連動させない(すみわけのため)。次回生成時、スレッドのメール件数が保存時と
    変わっていなければ「状況に変化なし」として引き続き非表示にし、件数が変わっていれば
    (新着メールがあった=状況が変わった)キューに再表示する。"""
    os.makedirs("json", exist_ok=True)
    if os.path.exists(COCKPIT_V2_ACKNOWLEDGED_FILE):
        try:
            with open(COCKPIT_V2_ACKNOWLEDGED_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: return {}
    return {}

def save_cockpit_v2_acknowledged(data):
    os.makedirs("json", exist_ok=True)
    with open(COCKPIT_V2_ACKNOWLEDGED_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def load_review_manual_items():
    """振り返りタブの手動編集(非表示・ランク上書き・手動追加・文言修正)を読み込む。
    キーはachievement_id(スレッドID群の連結、または手動追加分はmanual_XXXのID)。"""
    os.makedirs("json", exist_ok=True)
    default = {"hidden": [], "rank_overrides": {}, "added": {}, "text_overrides": {}}
    if os.path.exists(REVIEW_MANUAL_FILE):
        try:
            with open(REVIEW_MANUAL_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for k, v in default.items():
                data.setdefault(k, v)
            return data
        except: return default
    return default

def save_review_manual_items(data):
    os.makedirs("json", exist_ok=True)
    with open(REVIEW_MANUAL_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def _default_review_person_goals() -> dict:
    """json/review_person_goals.jsonが存在しない場合の雛形。ご提供いただいた各スタッフの
    2026年ゴールシート(Nexperia Goals PDF、全ページ"confidential"のためリポジトリには含めない)
    から抽出したKPIタイトルを初期値として入れる。Ochi以外はkeywords(実績との紐づけに使う
    キーワード)を空にしてあるため、紐づけ精度を上げるには実機でこのファイルへ追記が必要。
    Taizoさんはゴールシート未提供のため空枠(実績は集計されるが常にBランク判定になる)。
    キーは、project_knowledge["staffs"]の実際の登録名表記(例:"Yuto"。苗字"Oi"だけだと
    無関係な語への誤爆が多いため、宛先・送信者名のマッチングでは名前を優先している)に
    合わせてある。完全一致しない場合はget_review_person_goal_defsの部分一致で吸収する。"""
    return {
        "Ochi": {
            "G1_project": {
                "label": "G1 NPI遂行・CN危機対応",
                "keywords": ["Caracal", "Wheeling", "Grand Teton", "NEX40101A", "NEX402",
                             "R19", "IO Close", "12NC", "PCA", "PES", "disposal", "wafer",
                             "mask", "lead frame", "ATE", "characterization", "HTOL",
                             "reliability", "qualification", "MRA"],
            },
            "G2_site": {
                "label": "G2 サイト運営安定・事業継続",
                "keywords": ["Finance", "Procurement", "Legal", "Export", "Import", "PO",
                             "NDA", "2Agree", "安否確認", "safety confirmation", "SharePoint",
                             "Power Automate", "labor", "36協定", "下請", "支払い", "調達"],
            },
            "G3_r04": {
                "label": "G3 R04ガバナンス・プロセス統合",
                "keywords": ["IATF", "audit", "監査", "FMEA", "Enovia", "Sign-off",
                             "Document Control", "external audit"],
            },
        },
        "Saji": {
            "K1": {"label": "Caracal AL-Temp Cycle準備", "keywords": []},
            "K2": {"label": "Caracal validation", "keywords": []},
            "K3": {"label": "Wheeling HTOL・故障解析", "keywords": []},
            "K4": {"label": "Caracal テスト開発", "keywords": []},
            "K5": {"label": "Wheeling テスト開発", "keywords": []},
            "K6": {"label": "業務環境改善(SharePoint・PowerAutomate)", "keywords": []},
        },
        "Nakai": {
            "K1": {"label": "Enovia運用教育", "keywords": []},
            "K2": {"label": "Thick Copper Design Rules支援", "keywords": []},
            "K3": {"label": "旧R19案件クローズ(Caracal・Sterna)", "keywords": []},
            "K4": {"label": "旧R19 Studyクローズ", "keywords": []},
            "K5": {"label": "Caracal StudyのNPI移行", "keywords": []},
            "K6": {"label": "NEX4020xA推進", "keywords": []},
            "K7": {"label": "NEX40401A推進", "keywords": []},
            "K8": {"label": "Grand Teton・Wheeling支援", "keywords": []},
        },
        "Kajikawa": {
            "K1": {"label": "申請承認プロセス自動化(大阪・大分)", "keywords": []},
            "K2": {"label": "R04 Japan・Japan West Officeサイト活性化", "keywords": []},
            "K3": {"label": "R19関連PO・IOクローズ支援", "keywords": []},
            "K4": {"label": "業務プロセス再構築とSOP整備", "keywords": []},
        },
        "Yuto": {
            "K1": {"label": "製品エンジニアリング(Caracal・Wheeling・Grand Teton)", "keywords": []},
            "K2": {"label": "Wheeling validation", "keywords": []},
            "K3": {"label": "テスト開発(3製品)", "keywords": []},
        },
        "Najib": {
            "K1": {"label": "Grand Teton execution", "keywords": []},
            "K2": {"label": "Caracal study execution", "keywords": []},
            "K3": {"label": "ATEサンプル・qualサンプル納期", "keywords": []},
            "K4": {"label": "Wheeling qualification MRA3P0", "keywords": []},
        },
        "Taizo": {},
    }

def load_review_person_goals() -> dict:
    """振り返りタブ用: 対象者ごとのゴール(KPI)定義を読み込む。ファイルが無ければ
    雛形(_default_review_person_goals)を生成して保存してから返す。"""
    os.makedirs("json", exist_ok=True)
    if os.path.exists(REVIEW_PERSON_GOALS_FILE):
        try:
            with open(REVIEW_PERSON_GOALS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict) and data:
                return data
        except Exception:
            pass
    default = _default_review_person_goals()
    save_review_person_goals(default)
    return default

def save_review_person_goals(data: dict):
    os.makedirs("json", exist_ok=True)
    with open(REVIEW_PERSON_GOALS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def get_review_person_goal_defs(person: str, goals_data: dict = None) -> dict:
    """指定した対象者(person)のゴール定義を返す({goal_key: {"label":..., "keywords":[...]}}}。
    project_knowledge["staffs"]の登録キー表記が雛形のキー表記(例:"Yuto"⇄"Oi")と完全一致しない
    場合に備え、完全一致が無ければ大文字小文字を無視した部分一致でフォールバックする
    (classify_review_staff_involvementの名前照合と同じ考え方)。一致が無ければ空辞書を返す
    (そのスタッフの実績は全てゴール外=Bランクとして扱われる)。"""
    if goals_data is None:
        goals_data = load_review_person_goals()
    if person in goals_data:
        return goals_data[person]
    person_l = (person or "").strip().lower()
    if not person_l:
        return {}
    for key, val in goals_data.items():
        key_l = key.lower()
        if person_l == key_l or person_l in key_l or key_l in person_l:
            return val
    return {}

def build_review_goal_prompt_block(goal_defs: dict) -> str:
    """summarize_review_monthのAIプロンプトへ差し込む、ゴール分類の指示文をゴール定義
    (json/review_person_goals.jsonの当該personの値)から動的に組み立てる。以前はG1/G2/G3が
    プロンプトへ直接ハードコードされていたが、対象者ごとにゴールの内容(Ochiさんの3ゴール、
    各スタッフのKPI)が異なるため動的化した。goal_defsが空(ゴール未登録の対象者)の場合は、
    常に空配列を返すよう指示する。"""
    if not goal_defs:
        return 'goal_keys: この対象者にはゴールが未登録のため、常に空配列 [] を返すこと。'
    parts = []
    for key, d in goal_defs.items():
        label = d.get("label", key) if isinstance(d, dict) else str(d)
        kws = (d.get("keywords") or []) if isinstance(d, dict) else []
        hint = f"(関連キーワード例: {', '.join(kws)})" if kws else ""
        parts.append(f'"{key}"({label}){hint}')
    keys_desc = " / ".join(parts)
    return (
        f'goal_keys: この実績が紐づくゴールを0〜複数個、配列で指定。以下のいずれかのキーを使うこと: '
        f'{keys_desc} 。1つの実績が複数ゴールに同時に該当する場合は複数入れてよい'
        '(1実績=1ゴールに限定しない)。いずれのゴールにも該当しない場合は空配列でよい。'
    )

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

# 意思決定キューの分類(数値スコアではなく「異常の種類」で1件=1カテゴリに分類する)。
# 優先順位はこのリストの順番(先頭が最優先)。カテゴリ内は経過日数の降順のみで並べる。
COCKPIT_V2_CATEGORY_ORDER = ["reminded", "them_stalled", "silent", "spiking", "waiting"]
COCKPIT_V2_CATEGORY_LABELS = {
    "reminded":     "🔥 催促されている",
    "them_stalled": "🧊 相手が止まっている",
    "silent":       "🕰 長期沈黙",
    "spiking":      "📈 急に燃えている",
    "waiting":      "📥 自分待ち",
}

def should_include_in_cockpit_queue(is_waiting_on_me: bool, is_stalled: bool) -> bool:
    """自分待ち(ボールが自分のコートにある)は常にキュー対象。
    相手待ち(自分が最後に送信した)は、そのスレッド自身の平常ペースに対して
    相対的に沈黙している場合のみ対象にする(送った直後のスレッドまで急かす必要はないため)。"""
    return is_waiting_on_me or is_stalled

def classify_cockpit_item(is_waiting_on_me: bool, reminder_count: int,
                           is_stalled: bool, velocity_trend: str) -> tuple:
    """呼び出し前提: should_include_in_cockpit_queue()がTrueであること。
    優先順位: 催促されている > 相手が止まっている > 長期沈黙 > 急に燃えている > 自分待ち(特筆事項なし)。
    (category_key, category_label) のタプルを返す。"""
    if is_waiting_on_me and reminder_count >= 1:
        return ("reminded", COCKPIT_V2_CATEGORY_LABELS["reminded"])
    if not is_waiting_on_me:
        return ("them_stalled", COCKPIT_V2_CATEGORY_LABELS["them_stalled"])
    if is_stalled:
        return ("silent", COCKPIT_V2_CATEGORY_LABELS["silent"])
    if velocity_trend == "↑":
        return ("spiking", COCKPIT_V2_CATEGORY_LABELS["spiking"])
    return ("waiting", COCKPIT_V2_CATEGORY_LABELS["waiting"])

def cockpit_item_reasons(waiting_people_count: int, days_elapsed: float, reminder_count: int,
                          is_flagged: bool, has_deadline: bool) -> list:
    """UI表示用の根拠チップ文字列のリストを返す(数値スコアの内訳ではなく、
    カテゴリ分類を補足する事実の列挙)。"""
    reasons = []
    if waiting_people_count >= 1:
        reasons.append(f"👥 {waiting_people_count}人が待機中")
    if days_elapsed >= 1:
        reasons.append(f"⏰ {int(days_elapsed)}日間 動きなし")
    if reminder_count >= 1:
        reasons.append(f"📣 催促表現 {reminder_count}回")
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
# 振り返りタブ (四半期パフォーマンスレビュー用): ゴール分類・Tier判定・報告ランク
# ここに置く関数はすべてOutlook(win32com)に依存しない純粋関数とし、
# Outlookが動かない環境でも単体でロジック検証できるようにする。
# ============================================================

# 報告価値ブーストのTier1(経営層=報告先そのもの)。メールアドレスは小文字で管理する。
REVIEW_TIER1 = {
    "javed.ahmad@nexperia.com": "Javed (MAG Leader)",
    "thomas.lewis@nexperia.com": "Thomas (BG Leader)",
}
# Tier2(機能部門長=横のカウンターパート)。2名以上の関与で「部門横断」ブーストとする。
REVIEW_TIER2 = {
    "alber.teunissen@nexperia.com": "Alber (PM Mgr)",
    "john.perry@nexperia.com": "John (SE Mgr)",
    "a.timmer@nexperia.com": "Alex (TE Mgr)",
    "ulysis.suaverdez@nexperia.com": "Ulysis (PE Mgr)",
}

REVIEW_GOAL_ORDER = ["G1_project", "G2_site", "G3_r04"]
REVIEW_GOAL_LABELS = {
    "G1_project": "G1 プロジェクト遂行",
    "G2_site": "G2 サイト基盤整備",
    "G3_r04": "G3 R04フロー適合",
}

# G2(サイト基盤整備)実績を、報告時に見やすいよう機能別へ小分類するためのキーワード。
# ユーザー指定語(Finance/Procurement/Legal/IT/Export/Import/HR/人事/調達/PO/支払い/設備/安全)
# に、関連語(監査/audit/自動化/automation/ISO等)を加えたもの。小文字化して部分一致で判定する。
REVIEW_G2_KEYWORDS = {
    "finance_procurement": ["finance", "procurement", "調達", " po ", "purchase order", "支払い", "invoice", "予算", "budget"],
    "legal_trade": ["legal", "export", "import", "輸出", "輸入", "通関", "契約", "法務", "compliance"],
    "it_automation": [" it ", "automation", "自動化", "system", "デジタル", "dx", "ロボ", "rpa"],
    "hr": ["hr", "人事", "採用", "recruit", "教育", "training", "評価", "labor"],
    "facility_safety": ["設備", "安全", "safety", "facility", "5s", "audit", "監査", "isms", "iso", "改善"],
}
REVIEW_G2_SUBCAT_LABELS = {
    "finance_procurement": "💰 財務・調達",
    "legal_trade": "⚖️ 法務・輸出入",
    "it_automation": "💻 IT・自動化",
    "hr": "👥 人事・労務",
    "facility_safety": "🏭 設備・安全",
}

REVIEW_RANK_ORDER = ["S", "A", "B", "P"]
REVIEW_RANK_LABELS = {
    "S": "🅢 MAG Leader報告必須",
    "A": "🅐 報告推奨",
    "B": "🅑 実績リスト",
    "P": "🔵 進行中",
}

# 振り返りタブ用: 部下(スタッフ)の成果を機械判定するための、名前→ファンクションの対応表。
# スタッフ名簿自体はproject_knowledge["staffs"](スタッフ俯瞰タブの登録)をそのまま使い、
# 二重管理を避ける。ここではファンクション表示ラベルのみを保持する(project_knowledge側に
# ファンクション情報が無いため)。1名が複数ファンクションを兼任する場合はリストで複数指定する
# (例: Oi YutoはPE/VE兼任)。キーは小文字で管理する。
REVIEW_STAFF_FUNCTIONS = {
    "nakai": ["PM"],
    "saji": ["TE"],
    # 実際のproject_knowledge["staffs"]の登録名は"Yuto"(苗字の"Oi"だけだと無関係な語への
    # 誤爆が多く、宛先・送信者名のマッチングでは名前"Yuto"を優先しているため)。
    # ただし議事録本文中では本人は"Oi"/"Oi-san"として登場する(REVIEW_MINUTES_DOC_ALIASES参照)。
    "yuto": ["PE", "VE"],
    "najib": ["PE"],
    "kajikawa": ["Admin"],
}

def get_review_staff_functions(person: str) -> list:
    """REVIEW_STAFF_FUNCTIONSから対象者のファンクション(PM/PE/TE等)を取得する。
    project_knowledge["staffs"]の登録名表記がREVIEW_STAFF_FUNCTIONSのキー表記と
    完全一致しない場合に備え(例: "Yuto Oi"のようなフルネーム表記で登録されている場合)、
    完全一致が無ければget_review_person_goal_defsと同じ大文字小文字無視の部分一致で
    フォールバックする。一致が無ければ空リスト。"""
    person_l = (person or "").strip().lower()
    if not person_l:
        return []
    if person_l in REVIEW_STAFF_FUNCTIONS:
        return REVIEW_STAFF_FUNCTIONS[person_l]
    for key, funcs in REVIEW_STAFF_FUNCTIONS.items():
        if person_l in key or key in person_l:
            return funcs
    return []

# 振り返りタブ・議事録抽出用: 宛先・送信者名のマッチングに使う「安全な」名前
# (project_knowledge["staffs"]の登録名。例:"Yuto")と、実際に議事録本文の中でその人物を
# 指す表記(例:"Oi"/"Oi-san")が異なる場合の対応表。短い苗字("Oi"等)だけを宛先マッチングに
# 使うと無関係な語への誤爆が多いため、メール送信者・宛先の判定には常にproject_knowledge
# 登録名を使う一方、議事録本文からの人物別抽出をAIへ指示する際の表記はここで別名に置き換える。
# キーは小文字のproject_knowledge登録名。
REVIEW_MINUTES_DOC_ALIASES = {
    "yuto": ["Oi", "Oi-san"],
}

def get_review_minutes_doc_name(person: str) -> str:
    """振り返りタブ・議事録抽出用: person(project_knowledge登録名。宛先マッチング優先で
    短縮/安全な名前になっていることがある)を、実際に議事録本文中でその人物を指す表記
    (例:"Oi/Oi-san")に変換する。REVIEW_MINUTES_DOC_ALIASESに登録が無ければperson自身を
    そのまま返す(登録名と本文表記が一致している場合はこれで問題ない)。"""
    person_l = (person or "").strip().lower()
    aliases = REVIEW_MINUTES_DOC_ALIASES.get(person_l)
    if aliases:
        return "/".join(aliases)
    return person

REVIEW_TYPE_LABELS = {
    "decision": "⚖️判断・決裁",
    "execution": "🔨実行・完遂",
    "systemize": "🏗仕組み化",
    "coordination": "🤝調整・折衝",
    "communication": "📢発信・育成",
}

REVIEW_PROJECT_LABELS = {
    "00_Caracal": "Caracal",
    "01_Wheeling": "Wheeling",
    "02_GrandTeton": "GrandTeton",
    "03_R19Projects": "R19Proj",
    "Japan_Site": "Japan Site運営",
    "Other": "その他",
}

def classify_review_tier(recipient_emails: list, sender_email: str = "") -> dict:
    """To/Ccの宛先(+送信者)メールアドレス一覧から、Tier1/Tier2の関与者名を機械判定する。
    大文字小文字を問わず、REVIEW_TIER1/REVIEW_TIER2のキー(メールアドレス)と一致するかを見る。
    戻り値: {"tier1": [表示名,...], "tier2": [表示名,...]}(重複なし、定義順)"""
    emails_lower = {(e or "").strip().lower() for e in recipient_emails if e}
    if sender_email:
        emails_lower.add(sender_email.strip().lower())
    tier1 = [label for email, label in REVIEW_TIER1.items() if email in emails_lower]
    tier2 = [label for email, label in REVIEW_TIER2.items() if email in emails_lower]
    return {"tier1": tier1, "tier2": tier2}

def classify_review_g2_subcategory(text: str):
    """G2(サイト基盤整備)実績のタイトル・要約テキストから、機能別の小分類キーを1つ推定する。
    複数のキーワードグループに一致する場合はREVIEW_G2_KEYWORDSの定義順で最初に一致したものを採用する。
    一致が無ければNoneを返す(AIが付けたgoal_keysの精度をこの関数で否定はしない)。"""
    lower = f" {(text or '').lower()} "
    for key, kws in REVIEW_G2_KEYWORDS.items():
        if any(kw in lower for kw in kws):
            return key
    return None

def rank_review_achievement(is_confirmed: bool, goal_keys: list, tier1_present: bool,
                             tier2_count: int, site_wide: bool, has_quantitative: bool,
                             staff_involved: bool = False) -> str:
    """MAG Leaderへの報告優先順位を決定木で判定する(前回の統括コックピットv2で失敗した
    加重和スコア方式は採用しない)。
    Step1: 成果が確定(完了/判断を下した)していなければP(進行中。まだ「実績」ではなく
           「動き」として扱う。以前はここもBに含めていたが、"完了しているがゴール外"と
           "まだ結論が出ていない"が同じ扱いで区別できない、というご指摘を受けて分離した)。
    Step2: 3ゴール(G1/G2/G3)のいずれにも紐付かなければB(完了はしているがゴール外の実績)。
    Step3: Tier1関与・Tier2 2名以上・サイト全体影響・定量効果・スタッフの成果を牽引した、
           のいずれか1つでもあればS、無ければA。
           (staff_involvedは、登録スタッフ(部下)が主導したスレッドが実績の根拠に
           含まれる場合にtrue。マネージャーとして「上」「横」だけでなく「下(部下の成果)」も
           見えるようにするための追加条件。ゴール2「Japan Siteが効果的なチームとして
           活動できる環境整備」に直結するマネジメント成果とみなす)。"""
    if not is_confirmed:
        return "P"
    if not goal_keys:
        return "B"
    if tier1_present or tier2_count >= 2 or site_wide or has_quantitative or staff_involved:
        return "S"
    return "A"

def review_achievement_sort_key(achievement: dict) -> tuple:
    """ランク内の並び順: 定量効果の有無 → Tier1関与 → 関与組織数(Tier1+Tier2人数) →
    完了日の新しい順、の単純多段比較(合成スコアは使わない)。
    sorted()の昇順比較でそのまま「望ましい順」が先頭に来るよう、各項目を符号反転する。"""
    has_quant = 1 if achievement.get("has_quantitative_effect") else 0
    tier1 = 1 if achievement.get("tier1") else 0
    org_count = len(achievement.get("tier1", [])) + len(achievement.get("tier2", []))
    completed_date = achievement.get("completed_date") or ""
    try:
        ts = datetime.strptime(completed_date[:10], "%Y-%m-%d").timestamp()
    except Exception:
        ts = 0.0
    rank_idx = REVIEW_RANK_ORDER.index(achievement.get("rank", "B")) if achievement.get("rank") in REVIEW_RANK_ORDER else len(REVIEW_RANK_ORDER)
    return (rank_idx, -has_quant, -tier1, -org_count, -ts)

def meeting_matches_activity(meeting_subject: str, meeting_date, activity_topic: str,
                              activity_dates: list, window_days: int = 3) -> bool:
    """会議とメール実績を、件名の部分一致(相互包含)と時期の近さ(前後window_days以内)で
    ひも付けられるか判定する(会議で決めてメールで展開、という典型パターンの検知)。"""
    if not meeting_subject or not activity_topic or not meeting_date or not activity_dates:
        return False
    ms = meeting_subject.strip().lower()
    at = activity_topic.strip().lower()
    if not ms or not at:
        return False
    subject_match = (ms in at) or (at in ms)
    if not subject_match:
        return False
    return any(abs((meeting_date - d).days) <= window_days for d in activity_dates)

def bundle_recurring_meetings(meetings: list) -> list:
    """自分主催の会議のうち、同じ件名で3回以上開催されているものは「運営実績」として
    1件に束ね(定例会議)、それ未満(単発)はそのまま個別に返す。他者主催の会議は対象外
    (関与の補強材料としては別途使うが、実績としては束ねない)。"""
    from collections import defaultdict
    by_subject = defaultdict(list)
    for m in meetings:
        if m.get("is_organizer"):
            by_subject[(m.get("subject") or "").strip()].append(m)
    bundled = []
    for subject, occs in by_subject.items():
        if not subject:
            continue
        if len(occs) >= 3:
            bundled.append({
                "subject": subject,
                "kind": "recurring_summary",
                "occurrence_count": len(occs),
                "dates": sorted(o["start"] for o in occs if o.get("start")),
                "attendees": sorted({a for o in occs for a in (o.get("attendees") or [])}),
            })
        else:
            for o in occs:
                bundled.append({
                    "subject": subject, "kind": "single",
                    "occurrence_count": 1,
                    "dates": [o["start"]] if o.get("start") else [],
                    "attendees": o.get("attendees") or [],
                })
    return bundled

# 振り返りタブ: OchiさんがJapan Staff All等(配布リスト)へ週次で送信する、Japan Site
# Weekly議事録の件名キーワード。この議事録1通の中に全プロジェクトの進捗
# (PM=プロジェクト全体、PE=Oi-san、TE=Saji-san等)が混在している。配布リスト宛のため、
# 通常の宛先ベースのスタッフ判定(review_person_activity_qualifies)では、個人名にも
# 個人アドレスにも一致せず捕捉できない。そのため件名で特別に検知し、登録スタッフ全員の
# 対象スレッドへ無条件で含める(review_thread_is_minutesを参照)。
REVIEW_MINUTES_SUBJECT_KEYWORD = "ICS R04 Japan R&D meeting - week"

def review_thread_is_minutes(t: dict, user_smtp_address: str = None) -> bool:
    """振り返りタブ: あるスレッド(group_by_threadの1エントリ)がJapan Site Weekly議事録
    (REVIEW_MINUTES_SUBJECT_KEYWORDを件名に含む)かどうかを判定する。
    user_smtp_addressを指定した場合、そのメールがOchiさん自身の送信であることも必須にする
    (他者が似た件名で送った無関係なメールを誤って拾わないため)。summarize_review_month内で
    は(既にqualify済みのスレッドしか渡ってこないため)件名のみで十分と判断し省略する。"""
    my = (user_smtp_address or "").strip().lower() if user_smtp_address else None
    kw = REVIEW_MINUTES_SUBJECT_KEYWORD.lower()
    for m in t.get('mails', []):
        subj = f"{m.get('subject','')} {m.get('conversation_topic','')}".lower()
        if kw not in subj:
            continue
        if my is None or (m.get('sender_email') or '').strip().lower() == my:
            return True
    return False

# 振り返りタブ・議事録の進捗表(OneNote由来、Outlookの.HTMLBodyに<table>として残る)の
# ヘッダーセル文字列(小文字・空白除去後)を、内部の正規化した列名へ変換するための対応表。
# "Function"列は見出しの意味と異なり、実際には担当者の姓が入っている(REVIEW_MINUTES_DOC_ALIASES
# 参照)。表記ゆれ(週によって微妙に文言が変わる可能性)に備え、部分一致で判定する。
_REVIEW_MINUTES_TABLE_HEADER_ALIASES = [
    ("project", ["project"]),
    ("person", ["function"]),
    ("last_week", ["last week", "lastweek"]),
    ("this_week", ["this week", "thisweek"]),
    ("key_tasks", ["key tasks", "keytasks"]),
    ("baseline", ["baseline"]),
    ("lv", ["lv"]),
    ("risk_item", ["risk"]),
    ("countermeasures", ["countermeasure"]),
    ("comment", ["comment"]),
]

def parse_review_minutes_table(html_body: str) -> list:
    """Japan Site Weekly議事録のHTML本文(MailItem.HTMLBody)から、OneNote由来の進捗表を
    構造化して抽出する。表はProject/Function(実際は担当者名)/Last Week/This Week/
    Key Tasks in next 4w/Baseline/LV/Risk Item/Countermeasures Action/Commentの列を持ち、
    同一人物・同一プロジェクトの複数タスクにまたがってProject・Function列がrowspanで
    結合されている(例: "Caracal"がrowspan=10、その中の"Saji"がrowspan=6)。
    rowspan/colspanを考慮した一般的なグリッド展開で列を正しく復元する(特定の週の
    セル結合パターンに依存する実装にはしていない)。
    印刷用に表中に繰り返される見出し行(Project/Functionという値がそのまま入っている行)は
    データ行として扱わず除外する。
    戻り値は [{"project":str, "person":str, "last_week":str, "this_week":str,
    "key_tasks":str, "baseline":str, "lv":str, "risk_item":str,
    "countermeasures":str, "comment":str}, ...]。
    対象の表が見つからない・HTML本文が空の場合は空リストを返す(呼び出し元は
    既存の自由文からの人物別抽出にフォールバックする)。"""
    if not html_body:
        return []
    try:
        soup = BeautifulSoup(html_body, "html.parser")
    except Exception:
        return []

    all_rows = []
    for table in soup.find_all("table"):
        trs = table.find_all("tr")
        if len(trs) < 2:
            continue
        header_cells = trs[0].find_all(["td", "th"])
        header_texts = [c.get_text(" ", strip=True).lower() for c in header_cells]
        if not (any("project" in h for h in header_texts) and any("function" in h for h in header_texts)):
            continue  # Weekly議事録の進捗表ではない別種の表

        col_names = []
        for h in header_texts:
            canonical = None
            for name, aliases in _REVIEW_MINUTES_TABLE_HEADER_ALIASES:
                if any(a in h for a in aliases):
                    canonical = name
                    break
            col_names.append(canonical or f"col_{len(col_names)}")
        n_cols = len(col_names)

        pending = {}  # col_index -> [text, remaining_rowspan]
        for tr in trs[1:]:
            cells = tr.find_all(["td", "th"])
            row_values = [None] * n_cols
            col = 0
            cell_iter = iter(cells)
            cell = next(cell_iter, None)
            while col < n_cols:
                if col in pending and pending[col][1] > 0:
                    row_values[col] = pending[col][0]
                    pending[col][1] -= 1
                    if pending[col][1] == 0:
                        del pending[col]
                    col += 1
                    continue
                if cell is None:
                    col += 1
                    continue
                text = cell.get_text(" ", strip=True)
                try:
                    rowspan = int(cell.get("rowspan", 1) or 1)
                except ValueError:
                    rowspan = 1
                try:
                    colspan = int(cell.get("colspan", 1) or 1)
                except ValueError:
                    colspan = 1
                for c_off in range(colspan):
                    if col + c_off < n_cols:
                        row_values[col + c_off] = text
                        if rowspan > 1:
                            pending[col + c_off] = [text, rowspan - 1]
                col += colspan
                cell = next(cell_iter, None)
            row_dict = {name: (row_values[i] or "").strip() for i, name in enumerate(col_names)}
            if row_dict.get("project", "").strip().lower() == "project":
                continue  # 印刷用に繰り返された見出し行
            if any(row_dict.values()):
                all_rows.append(row_dict)
    return all_rows

def format_review_minutes_rows_for_person(rows: list) -> str:
    """parse_review_minutes_tableの結果のうち、特定の対象者に絞り込んだ行のリストを、
    AIへ渡すための整形済みテキストに変換する(1行1タスク)。"""
    lines = []
    for r in rows:
        parts = []
        head = f"[{r.get('project', '')}] {r.get('key_tasks', '')}".strip()
        if head.strip("[] "):
            parts.append(head)
        if r.get("last_week"): parts.append(f"開始/前回期限: {r['last_week']}")
        if r.get("this_week"): parts.append(f"今回期限: {r['this_week']}")
        if r.get("baseline"): parts.append(f"ベースライン: {r['baseline']}")
        if r.get("lv"): parts.append(f"LV: {r['lv']}")
        if r.get("risk_item"): parts.append(f"リスク: {r['risk_item']}")
        if r.get("countermeasures"): parts.append(f"対策: {r['countermeasures']}")
        if r.get("comment"): parts.append(f"コメント: {r['comment']}")
        if parts:
            lines.append(" / ".join(parts))
    return "\n".join(lines)

def review_activity_qualifies(mails: list, user_smtp_address: str, staff_names: list = None) -> bool:
    """振り返りタブの機械フィルタ(L2): AIに渡す前にスレッドを8〜9割落とすための必須条件。
    「自分の送信メールが1通も無い」スレッドは無条件で対象外(振り返りは受動的な受信ではなく
    自分が実際に行動した証跡を対象にするため)。
    自分の送信が1通以上ある場合でも、以下のいずれかを満たさないスレッド(単なる一往復の
    事務連絡等)はさらに除外する: 自分が起点(最初のメールの送信者が自分)／自分の送信が
    2通以上／自分の送信に添付ファイルがある／5人以上(To+Cc重複除く)に宛てている。
    staff_namesを指定した場合、上記に加えて「登録スタッフ(部下)が送信し、かつ自分が
    To/Ccのいずれかに含まれている」スレッドも対象に含める(マネージャー自身は送信して
    いなくても、部下が実行し自分に報告・共有している活動を「実行した実績」として
    拾うため。この条件が無いと、上と横への報告ばかりが対象になり、部下の成果が
    一切拾えないという構造的な欠落があった)。"""
    my = (user_smtp_address or "").strip().lower()
    if not my or not mails:
        return False
    my_mails = [m for m in mails if (m.get("sender_email") or "").strip().lower() == my]
    if my_mails:
        if len(my_mails) >= 2:
            return True
        if (mails[0].get("sender_email") or "").strip().lower() == my:
            return True
        if any(m.get("attachment_names") for m in my_mails):
            return True
        recipients = set()
        for m in my_mails:
            recipients.update((e or "").strip().lower() for e in (m.get("to_emails") or []))
            recipients.update((e or "").strip().lower() for e in (m.get("cc_emails") or []))
        recipients.discard(my)
        if len(recipients) >= 5:
            return True
    if staff_names:
        names_lower = [n.lower() for n in staff_names if n]
        for m in mails:
            sender = (m.get("sender_name") or "").lower()
            if not any(name in sender for name in names_lower):
                continue
            to_cc = {(e or "").strip().lower() for e in (m.get("to_emails") or []) + (m.get("cc_emails") or [])}
            if my in to_cc:
                return True
    return False

def classify_review_staff_involvement(mails: list, staff_names: list) -> list:
    """スレッド内メールの送信者名(sender_name)が登録スタッフ名のいずれかを含む場合、
    そのスタッフ名のリストを返す(大文字小文字を区別しない部分一致、出現順・重複なし)。
    staff_namesが空、または一致が無ければ空リスト。"""
    if not staff_names:
        return []
    involved = []
    seen = set()
    for m in mails:
        sender = (m.get("sender_name") or "").lower()
        for name in staff_names:
            if name and name.lower() in sender and name not in seen:
                seen.add(name)
                involved.append(name)
    return involved

def review_staff_function_labels(staff_names_involved: list) -> list:
    """classify_review_staff_involvementの結果(スタッフ名のリスト)を、
    REVIEW_STAFF_FUNCTIONSのファンクション表示付きラベル(例: "Nakai(PM)")に変換する。
    ファンクションが未登録のスタッフ名は、名前のみをそのまま返す。"""
    labels = []
    for name in staff_names_involved:
        funcs = get_review_staff_functions(name)
        labels.append(f"{name}({'/'.join(funcs)})" if funcs else name)
    return labels

def review_person_activity_qualifies(mails: list, person_name: str, person_emails,
                                      user_smtp_address: str) -> bool:
    """振り返りタブ・スタッフ拡張用の機械フィルタ(review_activity_qualifiesのOchi版に相当)。
    Ochiさんのメールボックス(委任アクセス・共有メールボックスは参照できない)の中で、
    あるスレッド(mails)を指定スタッフ(person_name)の活動として扱えるかを判定する。
    (a) スレッド内いずれかのメールのsender_nameにperson_nameが含まれる(大小文字無視の
        部分一致。classify_review_staff_involvementと同じ照合方式)、または
    (b) Ochiさんが送信したメール(sender_email==user_smtp_address)のTo/Ccに、当該スタッフの
        メールアドレス(person_emails。harvest_person_email_aliasesで動的収集したもの)が
        含まれる、のいずれかを満たせば対象とする。
    person_emailsが空(そのスタッフのメールアドレスが一度も観測されていない)場合は(b)は
    常にFalseになるため、実質(a)のみで判定される。"""
    name_l = (person_name or "").strip().lower()
    my = (user_smtp_address or "").strip().lower()
    if not name_l or not mails:
        return False
    for m in mails:
        sender = (m.get("sender_name") or "").lower()
        if name_l in sender:
            return True
    if my and person_emails:
        emails_l = {(e or "").strip().lower() for e in person_emails if e}
        if emails_l:
            for m in mails:
                if (m.get("sender_email") or "").strip().lower() != my:
                    continue
                to_cc = {(e or "").strip().lower() for e in (m.get("to_emails") or []) + (m.get("cc_emails") or [])}
                if to_cc & emails_l:
                    return True
    return False

def harvest_person_email_aliases(mails: list, person_names: list) -> dict:
    """取得済みメール群(mails。月をまたいだ全件でよい)から、各スタッフ名(person_names)ごとに
    「sender_nameに当該名前を含むメールのsender_email」を収集し、{person_name: {email,...}}を
    返す。project_knowledge["staffs"]にメールアドレス欄が無く、_item_to_dictのto_emails/
    cc_emailsは解決済みSMTPアドレスのみで送信者の表示名を保持していないため、実際に
    観測されたメールから動的にエイリアスを構築する(新たな永続スキーマを増やさない)。"""
    aliases = {name: set() for name in person_names if name}
    for m in mails:
        sender_name = (m.get("sender_name") or "").lower()
        sender_email = (m.get("sender_email") or "").strip().lower()
        if not sender_email:
            continue
        for name in person_names:
            if name and name.lower() in sender_name:
                aliases[name].add(sender_email)
    return aliases

def rank_review_staff_achievement(is_confirmed: bool, goal_keys: list,
                                   has_quantitative: bool, site_wide: bool) -> str:
    """スタッフ(部下)実績用のランク決定木。Ochiさん用のrank_review_achievement()とは
    判定基準が異なるため独立させている(Tier1/Tier2関与・スタッフ関与ブーストは、
    スタッフ自身の実績には意味を持たないため対象外。ここでも加重和スコアは使わない)。
    Step1: 成果が確定していなければP(進行中)。
    Step2: 本人のどのKPIゴールにも紐づかなければB(完了はしているがゴール外の実績)。
    Step3: ゴールに紐づき、かつ(定量効果あり または Japan Site全体規模)であればS。
    Step4: ゴールに紐づくのみであればA。"""
    if not is_confirmed:
        return "P"
    if not goal_keys:
        return "B"
    if has_quantitative or site_wide:
        return "S"
    return "A"

def _review_person_cache_suffix(person: str) -> str:
    """振り返りタブのキャッシュファイル名(analysis_cache/review_monthly/配下)に使う
    対象者サフィックスを作る。Ochiさんは既存キャッシュ("{yyyymm}.json"のみ)と
    バイト単位で完全互換にするため空文字を返す(既存キャッシュを失効させないため)。
    スタッフ名は日本語・スペースを含みうるため、英数字以外を_に置換する。"""
    if person == "Ochi":
        return ""
    safe = re.sub(r'[^A-Za-z0-9]+', '_', person).strip('_')
    return f"__{safe or 'person'}"

# ============================================================
# ローカルサーバー (HTMLリンク連携用)
# ============================================================

# Outlook操作リクエストをメインスレッドに渡すキュー
outlook_request_queue = queue.Queue()

# json/action_status.json への同時書き込み競合を防ぐロック(ThreadingHTTPServer化に伴い追加)
action_status_lock = threading.Lock()
# json/cockpit_v2_project_overrides.json への同時書き込み競合を防ぐロック
cockpit_v2_project_override_lock = threading.Lock()
# json/cockpit_v2_acknowledged.json への同時書き込み競合を防ぐロック
cockpit_v2_acknowledged_lock = threading.Lock()
# json/review_manual_items.json への同時書き込み競合を防ぐロック
review_manual_lock = threading.Lock()



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
                if not gemini_credentials_available(): raise Exception("Gemini APIの認証情報が設定されていません。環境変数 GEMINI_API_KEY および GEMINI_PROXY_URL を設定してください")
                client = _CommonGeminiClient(api_key=api_key)
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
                if not gemini_credentials_available(): raise Exception("Gemini APIの認証情報が設定されていません。環境変数 GEMINI_API_KEY および GEMINI_PROXY_URL を設定してください")
                chunk_size = 100
                chunks = [texts[i:i + chunk_size] for i in range(0, len(texts), chunk_size)]
                def translate_chunk(chunk_idx, chunk_data):
                    chunk_dict = {str(idx): text for idx, text in enumerate(chunk_data)}
                    prompt = "以下のJSONオブジェクトの「値(Value)」部分のみを自然な日本語に翻訳し、同じ「キー(Key)」を持つJSONオブジェクトとして出力してください。\n" + json.dumps(chunk_dict, ensure_ascii=False)
                    try:
                        client = _CommonGeminiClient(api_key=api_key)
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
                if not gemini_credentials_available(): raise Exception("Gemini APIの認証情報が設定されていません。環境変数 GEMINI_API_KEY および GEMINI_PROXY_URL を設定してください")
                prompt = f"以下の対象の活動要約を踏まえ、新しい質問を2つだけ生成してください。JSONの配列で出力してください。\n\n【対象】{target}\n【活動要約】\n{context}\n\n【既存】\n{json.dumps(existing_qs, ensure_ascii=False)}"
                client = _CommonGeminiClient(api_key=api_key)
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
                if not gemini_credentials_available(): raise Exception("Gemini APIの認証情報が設定されていません。環境変数 GEMINI_API_KEY および GEMINI_PROXY_URL を設定してください")
                prompt = f"以下のメール本文を1行（50文字以内）で簡潔に要約してください。※必ず自然な日本語に翻訳して出力してください。\n\n【件名】{topic}\n【本文】{body}"
                client = _CommonGeminiClient(api_key=api_key)
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
                if not gemini_credentials_available(): raise Exception("Gemini APIの認証情報が設定されていません。環境変数 GEMINI_API_KEY および GEMINI_PROXY_URL を設定してください")
                prompt = f"メールスレッド履歴を分析し、詳細要約をJSON形式で出力。※必ず日本語で出力。\n1.points:3つ以上の要点 2.risks:リスク 3.recommended_actions:推奨活動\n\n【件名】{topic}\n【本文】{body}"
                client = _CommonGeminiClient(api_key=api_key)
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
        elif parsed.path == '/update_cockpit_v2_project':
            try:
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
                conversation_id = (data.get('conversation_id') or '').strip()
                project = (data.get('project') or '').strip()
                if not conversation_id or not project:
                    raise Exception("conversation_idまたはprojectが指定されていません")
                with cockpit_v2_project_override_lock:
                    overrides = load_cockpit_v2_project_overrides()
                    overrides[conversation_id] = project
                    save_cockpit_v2_project_overrides(overrides)
                self.send_response(200); self._send_cors_headers(); self.send_header('Content-type', 'application/json; charset=utf-8'); self.end_headers()
                self.wfile.write(json.dumps({'status': 'success'}).encode('utf-8'))
            except Exception as e:
                self.send_response(500); self._send_cors_headers(); self.send_header('Content-type', 'application/json; charset=utf-8'); self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        elif parsed.path == '/acknowledge_cockpit_v2_item':
            try:
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
                conversation_id = (data.get('conversation_id') or '').strip()
                mail_count = data.get('mail_count')
                if not conversation_id or mail_count is None:
                    raise Exception("conversation_idまたはmail_countが指定されていません")
                with cockpit_v2_acknowledged_lock:
                    acknowledged = load_cockpit_v2_acknowledged()
                    acknowledged[conversation_id] = {
                        "mail_count": mail_count,
                        "acknowledged_at": datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
                    }
                    save_cockpit_v2_acknowledged(acknowledged)
                self.send_response(200); self._send_cors_headers(); self.send_header('Content-type', 'application/json; charset=utf-8'); self.end_headers()
                self.wfile.write(json.dumps({'status': 'success'}).encode('utf-8'))
            except Exception as e:
                self.send_response(500); self._send_cors_headers(); self.send_header('Content-type', 'application/json; charset=utf-8'); self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
        elif parsed.path == '/update_review_manual':
            try:
                content_length = int(self.headers['Content-Length'])
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
                action = (data.get('action') or '').strip()
                if action not in ('hide', 'unhide', 'set_rank', 'add', 'edit_text'):
                    raise Exception(f"不明なaction: {action}")
                with review_manual_lock:
                    manual = load_review_manual_items()
                    if action == 'hide':
                        aid = (data.get('achievement_id') or '').strip()
                        if not aid: raise Exception("achievement_idが指定されていません")
                        if aid not in manual['hidden']: manual['hidden'].append(aid)
                    elif action == 'unhide':
                        aid = (data.get('achievement_id') or '').strip()
                        manual['hidden'] = [h for h in manual['hidden'] if h != aid]
                    elif action == 'set_rank':
                        aid = (data.get('achievement_id') or '').strip()
                        rank = (data.get('rank') or '').strip()
                        if not aid or rank not in REVIEW_RANK_ORDER:
                            raise Exception("achievement_idまたはrankが不正です")
                        manual['rank_overrides'][aid] = rank
                    elif action == 'edit_text':
                        aid = (data.get('achievement_id') or '').strip()
                        if not aid: raise Exception("achievement_idが指定されていません")
                        entry = manual['text_overrides'].setdefault(aid, {})
                        if 'title' in data: entry['title'] = data['title']
                        if 'summary' in data: entry['summary'] = data['summary']
                    elif action == 'add':
                        import uuid
                        manual_id = f"manual_{uuid.uuid4().hex[:12]}"
                        manual['added'][manual_id] = {
                            "manual_id": manual_id,
                            "person": data.get('person', 'Ochi') or 'Ochi',
                            "title": data.get('title', '(無題)'),
                            "summary": data.get('summary', ''),
                            "goal_keys": data.get('goal_keys', []),
                            "project_key": data.get('project_key', 'Other'),
                            "activity_type": data.get('activity_type', 'execution'),
                            "is_confirmed": True,
                            "has_quantitative_effect": bool(data.get('has_quantitative_effect')),
                            "quantitative_note": data.get('quantitative_note', ''),
                            "site_wide": bool(data.get('site_wide')),
                            "completed_date": data.get('completed_date', ''),
                            "source_thread_ids": [],
                            "rank": data.get('rank', 'A'),
                        }
                    save_review_manual_items(manual)
                self.send_response(200); self._send_cors_headers(); self.send_header('Content-type', 'application/json; charset=utf-8'); self.end_headers()
                self.wfile.write(json.dumps({'status': 'success'}).encode('utf-8'))
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
        elif parsed.path == '/review_hidden_list':
            # 振り返りタブ: 現在非表示にしている実績の一覧(タイトル付き)を返す。
            # ページ再読み込み時に該当行を再度非表示にする処理と、「元に戻す」パネルの
            # 両方がこのエンドポイントを使う。タイトルはreview_last_result.json(直近の
            # 生成結果のraw_achievementsスナップショット)から、achievement_idと同じ
            # 算出式(MailSummarizer.apply_review_manual_overrides内の_aid_base+人物接頭辞と
            # 同じロジック。この関数を変更する場合は必ず両方を同時に更新すること)で
            # 突き合わせて引く。既存(接頭辞なし)の非表示指定はOchiさんの実績として
            # フォールバック照合する(後方互換)。
            try:
                manual = load_review_manual_items()
                hidden_ids = manual.get('hidden', [])
                items = []
                if hidden_ids and os.path.exists(REVIEW_LAST_RESULT_FILE):
                    hidden_set = set(hidden_ids)
                    with open(REVIEW_LAST_RESULT_FILE, 'r', encoding='utf-8') as f:
                        saved = json.load(f)
                    for a in saved.get('raw_achievements', []):
                        if a.get('manual_id'):
                            base = a['manual_id']
                        else:
                            ids = a.get('source_thread_ids', [])
                            base = "|".join(ids) if ids else a.get('title', '')
                        person = a.get('person') or 'Ochi'
                        aid = f"{person}::{base}"
                        matched_aid = None
                        if aid in hidden_set:
                            matched_aid = aid
                        elif person == 'Ochi' and base in hidden_set:
                            matched_aid = base
                        if matched_aid is not None:
                            items.append({
                                'achievement_id': matched_aid,
                                'title': a.get('title', '(無題)'),
                                'rank': a.get('rank', 'B'),
                            })
                self.send_response(200)
                self._send_cors_headers()
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({'hidden_ids': hidden_ids, 'items': items}).encode('utf-8'))
            except Exception as e:
                self.send_response(500); self._send_cors_headers(); self.send_header('Content-type', 'application/json; charset=utf-8'); self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
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
    

def get_primary_work_area():
    """タスクバー等を除いた、プライマリモニターの作業領域を(left, top, right, bottom)
    のタプルで返す。取得できない場合はNoneを返す(呼び出し元は画面全体へフォール
    バックする)。ウィンドウの高さをこの作業領域の高さに合わせないと、タスクバーの
    分だけウィンドウ下部が隠れてしまう。"""
    try:
        SPI_GETWORKAREA = 0x0030
        rect = ctypes.wintypes.RECT()
        if ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
            return (rect.left, rect.top, rect.right, rect.bottom)
        print("作業領域(work area)の取得に失敗しました(SystemParametersInfoWがFalseを返却)。画面全体を使用します。")
    except Exception as e:
        print(f"作業領域(work area)の取得でエラーが発生しました: {e}。画面全体を使用します。")
    return None


def fit_window_to_work_area(root, width: int, height: int, x: int, y: int):
    """tkinterのgeometry()に指定するWxHは、タイトルバー・枠を含まない
    クライアント領域のサイズである。そのため作業領域(タスクバーを除いた
    領域)の高さをそのままgeometry()の高さに使うと、タイトルバーの分だけ
    ウィンドウ全体(外枠)の下端が作業領域の下端(=タスクバー上端)を超えて
    はみ出し、下部がタスクバーに隠れてしまう(実機で繰り返し報告された不具合)。
    一度指定どおりのジオメトリでウィンドウを実体化させたうえで、OSレベルの
    外枠サイズ(GetWindowRect)と要求したクライアントサイズとの差分から
    タイトルバー・枠の実際のサイズを測定し、その分を差し引いて再設定する
    ことで、ウィンドウの外枠が作業領域内に収まるようにする。"""
    root.geometry(f"{width}x{height}+{x}+{y}")
    root.update_idletasks()
    try:
        hwnd = root.winfo_id()
        GA_ROOT = 2
        top_hwnd = ctypes.windll.user32.GetAncestor(hwnd, GA_ROOT) or hwnd
        rect = ctypes.wintypes.RECT()
        if not ctypes.windll.user32.GetWindowRect(top_hwnd, ctypes.byref(rect)):
            print("ウィンドウ外枠サイズの取得に失敗しました(GetWindowRectがFalseを返却)。タスクバーに一部重なる可能性があります。")
            return
        chrome_w = (rect.right - rect.left) - width
        chrome_h = (rect.bottom - rect.top) - height
        if chrome_w > 0 or chrome_h > 0:
            adj_w = max(width - max(chrome_w, 0), 200)
            adj_h = max(height - max(chrome_h, 0), 200)
            root.geometry(f"{adj_w}x{adj_h}+{x}+{y}")
            print(f"🖥 ウィンドウ外枠補正: chrome_w={chrome_w} chrome_h={chrome_h} → {adj_w}x{adj_h}+{x}+{y}")
    except Exception as e:
        print(f"ウィンドウ外枠サイズの補正でエラーが発生しました: {e}。タスクバーに一部重なる可能性があります。")


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

    def _restore_if_actually_maximized(self, explorer) -> bool:
        """ExplorerのCOM上のWindowStateが0(通常)であっても、実際のOS側ウィンドウ
        (HWND)は本当に最大化されていることがある。実機ログで、WindowState読み取りが
        0を返し続けているにもかかわらず、Left/Top/Width/Heightの設定が
        「最大化または最小化されているため...変更できません」という例外で
        一貫して(34回リトライしても)失敗し続ける事象を確認した。これは
        Windowsのスナップ機能等、Outlook自身のUI操作を経ない経路でウィンドウが
        最大化されると、COM側のWindowStateプロパティが実際のOSの状態に
        追従しないために起きると考えられる。そのため、Win32 APIで実ウィンドウを
        直接特定し、本当に最大化されている場合はShowWindow(SW_RESTORE)で
        直接復元する。取得・復元に失敗しても例外は投げない(Falseを返す)。"""
        try:
            user32 = ctypes.windll.user32
            user32.FindWindowW.restype = ctypes.wintypes.HWND
            user32.GetForegroundWindow.restype = ctypes.wintypes.HWND
        except Exception as e:
            print(f"🔧[Outlook配置] ctypes.windllへのアクセスに失敗しました: {e}")
            return False
        hwnd = 0
        try:
            caption = explorer.Caption
        except Exception:
            caption = None
        try:
            if caption:
                hwnd = user32.FindWindowW("rctrl_renwnd32", caption)
        except Exception:
            hwnd = 0
        if not hwnd:
            try:
                explorer.Activate()
                time.sleep(0.2)
                hwnd = user32.GetForegroundWindow()
            except Exception:
                hwnd = 0
        if not hwnd:
            print("🔧[Outlook配置] 実OS側のウィンドウハンドル(HWND)を特定できませんでした")
            return False
        try:
            if user32.IsZoomed(hwnd):
                print(f"🔧[Outlook配置] 実OS側で最大化を検出(hwnd={hwnd}, COM上のWindowStateとは不一致)。"
                      f"ShowWindow(SW_RESTORE)で復元します")
                SW_RESTORE = 9
                user32.ShowWindow(hwnd, SW_RESTORE)
                time.sleep(0.3)
                return True
            print(f"🔧[Outlook配置] 実OS側の状態確認: 最大化されていません(hwnd={hwnd})")
        except Exception as e:
            print(f"🔧[Outlook配置] 実OS側の最大化チェック/復元でエラー: {e}")
        return False

    def _apply_explorer_geometry(self, explorer, left: int, top: int, width: int, height: int,
                                  timeout_seconds: float = 10.0):
        """ExplorerへWindowState=0(通常ウィンドウ)→Left/Top/Width/Heightの順で適用する。
        実機で確認された不具合: 直前まで最大化されていたExplorerに対し、WindowState=0を
        設定した直後にLeft等を設定すると、
        「最大化または最小化されているため、エクスプローラー...のサイズまたは位置を
        変更できません」というCOM例外(-2147352567)が発生することがある。これは
        WindowStateの変更がOutlook内部で実際のウィンドウへ反映されるまでに
        わずかな遅延があり、その間はまだ最大化状態として扱われるため。
        そのため、(1)各プロパティの設定は個別に例外を捕捉して短い間隔でリトライし、
        1つのプロパティの失敗が他のプロパティの設定を巻き添えで止めないようにする、
        (2)WindowStateについては設定後、読み取り値が実際に0になる(=反映された)のを
        確認してからLeft/Top/Width/Heightを設定する、という2点で対応する。"""
        t0 = time.time()
        deadline = t0 + timeout_seconds

        def _set_retry(name, value):
            attempts = 0
            last_error = None
            while time.time() < deadline:
                attempts += 1
                try:
                    setattr(explorer, name, value)
                    print(f"🔧[Outlook配置] {name}={value} 設定成功(試行{attempts}回目, "
                          f"経過{time.time()-t0:.1f}秒)")
                    return True
                except Exception as e:
                    # Pythonは except...as e ブロックを抜けると変数eを自動的に破棄するため、
                    # ブロックの外(このループを抜けた後)でeを参照すると
                    # UnboundLocalErrorになる。文字列としてlast_errorに退避しておく。
                    last_error = str(e)
                    time.sleep(0.3)
            print(f"🔧[Outlook配置] {name}={value} 設定失敗(タイムアウト, 試行{attempts}回, "
                  f"経過{time.time()-t0:.1f}秒): 最後の例外={last_error if attempts else 'なし'}")
            return False

        _set_retry("WindowState", 0)
        wait_attempts = 0
        while time.time() < deadline:
            wait_attempts += 1
            try:
                current = explorer.WindowState
                if current == 0:
                    print(f"🔧[Outlook配置] WindowState読み取り確認: 0(通常)になった "
                          f"(確認{wait_attempts}回目, 経過{time.time()-t0:.1f}秒)")
                    break
            except Exception as e:
                print(f"🔧[Outlook配置] WindowState読み取り例外(確認{wait_attempts}回目): {e}")
            time.sleep(0.3)
        else:
            try:
                print(f"🔧[Outlook配置] WindowState読み取りタイムアウト: 最後に読めた値={explorer.WindowState}")
            except Exception as e:
                print(f"🔧[Outlook配置] WindowState読み取りタイムアウト、かつ読み取り自体も例外: {e}")

        # COM上のWindowStateが0でも、実OS側は本当に最大化されている場合がある
        # (実機ログで確認済み)。Left等を試みる前に、実OS側の状態を直接確認・復元する。
        self._restore_if_actually_maximized(explorer)

        _set_retry("Left", left)
        _set_retry("Top", top)
        _set_retry("Width", width)
        _set_retry("Height", height)
        try:
            explorer.Activate()
        except Exception as e:
            print(f"🔧[Outlook配置] Activate()失敗: {e}")

        try:
            print(f"🔧[Outlook配置] _apply_explorer_geometry完了時点の実測値: "
                  f"WindowState={explorer.WindowState} Left={explorer.Left} Top={explorer.Top} "
                  f"Width={explorer.Width} Height={explorer.Height} (所要{time.time()-t0:.1f}秒)")
        except Exception as e:
            print(f"🔧[Outlook配置] 完了時点の実測値読み取りに失敗: {e}")

    def arrange_outlook_window(self, left: int, top: int, width: int, height: int,
                                wait_seconds: float = 20.0) -> bool:
        """Outlookを起動時のウィンドウ配置用に前面へ出し、指定した位置・サイズへ配置する。
        win32com.client.Dispatch は対象アプリが未起動なら起動する挙動を持つため、
        「起動していれば/していなければ」の分岐はDispatch自身に任せ、本メソッドは
        起動済み・起動直後のどちらでも同じコードパスで扱う。
        起動直後はCOMサーバーへの応答やActiveExplorer()の取得が一時的に失敗する
        ことがあるため、取得できるまで短い間隔でポーリングする(タイムアウトはwait_seconds)。"""
        # === 診断用ビルド ===
        # これまで複数回の修正(WindowStateタイミング対応・Display前設定・
        # 再チェック短縮)を実機投入したが、いずれも「Outlookが最大化される」
        # 問題を解消できなかった。憶測での再修正を重ねる前に、実際に何が
        # 起きているかを正確に把握するため、各段階の状態を詳細にログ出力する。
        t_start = time.time()
        print(f"🔧[Outlook配置] 開始 (target left={left} top={top} width={width} height={height})")
        deadline = t_start + wait_seconds
        explorer = None
        created_new = False
        try:
            pythoncom.CoInitialize()
            outlook = win32com.client.Dispatch("Outlook.Application")

            while not explorer and time.time() < deadline:
                try:
                    namespace = outlook.GetNamespace("MAPI")
                    explorer = outlook.ActiveExplorer()
                    if explorer:
                        try:
                            print(f"🔧[Outlook配置] 既存のActiveExplorerを検出: "
                                  f"WindowState={explorer.WindowState} Left={explorer.Left} "
                                  f"Top={explorer.Top} Width={explorer.Width} Height={explorer.Height}")
                        except Exception as e:
                            print(f"🔧[Outlook配置] 既存のActiveExplorer検出、状態読み取り失敗: {e}")
                    if not explorer:
                        inbox = namespace.GetDefaultFolder(6)
                        explorer = inbox.GetExplorer()
                        created_new = True
                        try:
                            print(f"🔧[Outlook配置] GetExplorer()直後(Display前)の状態: "
                                  f"WindowState={explorer.WindowState}")
                        except Exception as e:
                            print(f"🔧[Outlook配置] GetExplorer()直後の状態読み取り失敗: {e}")
                        # GetExplorer()で新規作成したExplorerは、Outlook自身の既定挙動として
                        # 最大化状態でDisplay()されることがある(このツールが最大化を要求した
                        # ことは一度も無い)。Display()より前に通常ウィンドウ・位置・サイズを
                        # 設定しておくことで、最大化状態が画面に一度も現れないようにする狙い
                        # だったが、実機ではこれでも最大化が再発している。設定自体が成功して
                        # いるかをログで確認する。
                        try:
                            explorer.WindowState = 0
                            explorer.Left = left
                            explorer.Top = top
                            explorer.Width = width
                            explorer.Height = height
                            print("🔧[Outlook配置] Display前のWindowState/位置設定: 成功")
                        except Exception as e:
                            print(f"🔧[Outlook配置] Display前のWindowState/位置設定: 例外発生 - {e}")
                        explorer.Display()
                        try:
                            print(f"🔧[Outlook配置] Display()直後の状態: "
                                  f"WindowState={explorer.WindowState} Left={explorer.Left} "
                                  f"Top={explorer.Top} Width={explorer.Width} Height={explorer.Height}")
                        except Exception as e:
                            print(f"🔧[Outlook配置] Display()直後の状態読み取り失敗: {e}")
                except Exception as e:
                    print(f"🔧[Outlook配置] Explorer取得ループで例外: {e}")
                    explorer = None
                if not explorer:
                    time.sleep(0.5)

            if not explorer:
                print("🔧[Outlook配置] タイムアウト: Explorerを取得できませんでした")
                return False

            print(f"🔧[Outlook配置] 新規作成={created_new} / _apply_explorer_geometryを実行します "
                  f"(経過{time.time()-t_start:.1f}秒)")
            self._apply_explorer_geometry(explorer, left, top, width, height)

            # Outlookは起動直後、COM経由で位置を設定した「後」に前回終了時の
            # ウィンドウ状態(最大化等)を自分で復元することがある。この再チェックで
            # 実際に何回・どのタイミングでドリフトが起きるかを記録するため、
            # 診断のあいだは監視時間を15秒に延ばし、毎回の状態を全てログに残す
            # (これまでの3秒間の監視では、その後に再発する事象を捉えられていな
            # かった可能性があるため)。
            recheck_deadline = time.time() + 15.0
            check_no = 0
            while time.time() < recheck_deadline:
                time.sleep(1.0)
                check_no += 1
                try:
                    cur_state = explorer.WindowState
                    cur_left = explorer.Left
                    cur_top = explorer.Top
                    cur_width = explorer.Width
                    cur_height = explorer.Height
                    drifted = (
                        cur_state != 0
                        or cur_left != left
                        or cur_top != top
                        or cur_width != width
                        or cur_height != height
                    )
                    print(f"🔧[Outlook配置] 再チェック#{check_no}(経過{time.time()-t_start:.1f}秒): "
                          f"WindowState={cur_state} Left={cur_left} Top={cur_top} "
                          f"Width={cur_width} Height={cur_height} drifted={drifted}")
                except Exception as e:
                    print(f"🔧[Outlook配置] 再チェック#{check_no}で状態読み取り例外: {e}")
                    break
                if not drifted:
                    continue
                self._restore_if_actually_maximized(explorer)
                try:
                    explorer.WindowState = 0
                    explorer.Left = left
                    explorer.Top = top
                    explorer.Width = width
                    explorer.Height = height
                    print(f"🔧[Outlook配置] 再チェック#{check_no}: ドリフトを検知したため再設定しました")
                except Exception as e:
                    print(f"🔧[Outlook配置] 再チェック#{check_no}: 再設定で例外 - {e}")
            print(f"🔧[Outlook配置] 完了 (総経過{time.time()-t_start:.1f}秒)")
            return True
        except Exception as e:
            print(f"Outlookウィンドウ配置エラー: {e}")
            return False
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
                    # 「未読のみ」が指定されている場合は、[UnRead] = True もRestrictに含めて
                    # Outlook自身の索引で絞り込む(厳密検索のON/OFFに関わらず適用する)。
                    # 従来は非厳密検索時にunread_only判定が一切行われず(strictブロック内のみ)、
                    # 期間内の全メール(既読含む)を取得してから事後フィルタしていたため、
                    # Outlookの検索フォルダ上の「未読」ボタンに比べて大幅に遅くなっていた。
                    # get_unread_rss_feeds等で既に実績のある書き方(items.Restrict("[UnRead] = True"))
                    # と同じ構文を、日付条件と AND で組み合わせて使う。
                    unread_clause = " AND [UnRead] = True" if conditions.get('unread_only') else ""
                    days = conditions.get('days', 7)
                    if days == 0:
                        date_str = (datetime.now() - timedelta(hours=24)).strftime("%m/%d/%Y %H:%M")
                        try: items = items.Restrict(f"[ReceivedTime] >= '{date_str}'{unread_clause}")
                        except: pass
                    elif days < 0:
                        date_str = (datetime.now() - timedelta(hours=abs(days))).strftime("%m/%d/%Y %H:%M")
                        try: items = items.Restrict(f"[ReceivedTime] >= '{date_str}'{unread_clause}")
                        except: pass
                    elif days > 0:
                        date_str = (datetime.now() - timedelta(days=days)).strftime("%m/%d/%Y")
                        try: items = items.Restrict(f"[ReceivedTime] >= '{date_str}'{unread_clause}")
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
        スキップし、本文取得のみ行うことで高速化する。
        ※ strict_mode=True のため、search_mails_fastは選択期間内で個別にヒットしたメールしか
        取得せず、スレッド全体(期間より前の古いメール)は辿らない。そのため、期間より前に
        付与されたR19Projカテゴリタグが取得漏れになり、group_by_threadのis_r19判定が
        正しく働かないケースがあった。_enrich_r19_tag_from_full_history()で、本文・添付は
        取得せずカテゴリタグの有無だけを軽量に補完する。"""
        conditions = {
            'all_me': True,
            'strict_mode': True, 'days': days,
            'force_full_body': True,
            'skip_attachments': True
        }
        all_mails = self.search_mails_fast(conditions, logic="AND", include_sent=False, progress_callback=progress_callback)
        self._enrich_r19_tag_from_full_history(all_mails)
        return all_mails

    def enrich_bodies_for_threads(self, threads: dict, progress_callback=None) -> int:
        """指定されたスレッド群のうち、本文(body)が空のメールについてだけ、
        OutlookからEntryID経由で本文を取得して補完する。補完した件数を返す。

        背景: search_mails_fastは「本文キーワードでの絞り込みが不要なら本文を読まない」
        という高速化(light_mode)を行っており、本文KWを空にして検索した場合、
        取得済みメールのbodyは空文字のままになる。この状態のままAI要約を行うと
        「提供されたメールには本文がありませんでした」という結果になってしまう。
        検索自体は高速なまま維持したいので、実際に要約する直前に、選択された
        スレッドの本文だけをここで補完する(検索時に一律force_full_body=Trueに
        するのではなく、必要になった時点で必要な分だけ取りに行く方式)。

        既に本文があるメールには一切触れないため、本文KW付きで検索した場合や、
        force_full_body=Trueで取得済みの場合はOutlookへのアクセスが発生しない。"""
        targets = []
        for t in threads.values():
            for m in t.get('mails', []):
                if not (m.get('body') or '').strip() and m.get('entry_id'):
                    targets.append(m)
        if not targets:
            return 0

        filled = 0
        try:
            pythoncom.CoInitialize()
            outlook = win32com.client.Dispatch("Outlook.Application")
            namespace = outlook.GetNamespace("MAPI")
            for i, m in enumerate(targets, 1):
                if progress_callback:
                    progress_callback(i, len(targets), f"📄 本文を取得中... ({i}/{len(targets)})")
                try:
                    item = namespace.GetItemFromID(m['entry_id'])
                    body = self._clean_body_text(getattr(item, 'Body', '') or '')[:300000]
                    if body:
                        m['body'] = body
                        filled += 1
                except Exception:
                    # 個別メールの取得失敗(削除済み・アクセス不可等)は無視して続行する。
                    # そのメールの本文は空のままだが、他のメールの要約は成立させる。
                    continue
        except Exception as e:
            print(f"本文補完エラー: {e}")
        finally:
            try: pythoncom.CoUninitialize()
            except: pass
        return filled

    def _enrich_r19_tag_from_full_history(self, all_mails: list):
        """get_relevant_mails_for_period専用の補完処理。
        期間内フェッチでは、選択期間より前にR19Projカテゴリタグが付与されたスレッドの
        古いメールが取得対象から漏れるため、「スレッド内のどれかのメールにR19Projタグが
        あればスレッド全体にタグを付与する」という本来の仕様(group_by_threadのis_r19判定)が
        正しく働かない。ここでは、期間内フェッチの時点でまだR19Projタグが見つかっていない
        ConversationについてのみOutlookの会話(Conversation)全体をたどり、カテゴリタグの
        有無だけを軽量にチェックする(本文・添付は取得しない)。見つかった場合は、そのスレッドの
        期間内メール側のcategoriesに'R19Proj'を補完し、既存のgroup_by_thread/is_r19判定
        ロジックはそのまま流用する(is_r19の計算式自体は変更しない)。"""
        conv_ids_to_check = []
        seen = set()
        for mail in all_mails:
            conv_id = mail.get('conversation_id')
            if not conv_id or conv_id in seen:
                continue
            seen.add(conv_id)
            has_tag = any(
                'R19Proj' in (m.get('categories') or '')
                for m in all_mails if m.get('conversation_id') == conv_id
            )
            if not has_tag:
                conv_ids_to_check.append(mail)

        if not conv_ids_to_check:
            return

        try:
            pythoncom.CoInitialize()
            outlook = win32com.client.Dispatch("Outlook.Application")
            namespace = outlook.GetNamespace("MAPI")
            for sample_mail in conv_ids_to_check:
                try:
                    entry_id = sample_mail.get('entry_id')
                    if not entry_id:
                        continue
                    item = namespace.GetItemFromID(entry_id)
                    if self._conversation_categories_contain_r19(item):
                        current = (sample_mail.get('categories') or '').strip().strip(',').strip()
                        sample_mail['categories'] = f"{current}, R19Proj".strip(', ') if current else 'R19Proj'
                except:
                    continue
        except Exception as e:
            print(f"R19 Tag Enrich Error: {e}")
        finally:
            try: pythoncom.CoUninitialize()
            except: pass

    def _conversation_categories_contain_r19(self, item) -> bool:
        """指定アイテムの会話(Conversation)全体を再帰的にたどり、いずれかのメールの
        Categoriesプロパティ(本文・添付には触れない軽量なプロパティアクセスのみ)に
        'R19Proj'が含まれるかどうかを調べる。"""
        try:
            conv = item.GetConversation()
            if not conv:
                return False

            def _walk(node):
                cats = getattr(node, 'Categories', '') or ''
                if 'R19Proj' in cats:
                    return True
                for child in conv.GetChildren(node):
                    if _walk(child):
                        return True
                return False

            for root in conv.GetRootItems():
                if _walk(root):
                    return True
            return False
        except:
            return False

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
            
            # 件名末尾の括弧書き補足(例: "...Again（PO 8210238665）")は全角/半角どちらの
            # 括弧でも除去する。全角のみを対象外にすると、括弧書きがクエリに残ったまま
            # Outlook純正Instant Search(explorer.Search)へ渡され、フレーズ一致に失敗して
            # 検索結果0件になる不具合があったため対応(2026-08-17)。
            safe_topic = re.sub(r'\s*[\(（][^\)）]*[\)）]\s*$', '', topic or '')
            safe_topic = re.sub(r'[":\(\)（）\-\[\]\{\}<>\']', ' ', safe_topic)
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
        to_emails = []
        cc_emails = []
        try:
            my_smtp = self.user_smtp_address
            recipients = item.Recipients
            to_list = []
            for r in recipients:
                ra = self._resolve_object_to_smtp(r)
                if not ra:
                    continue
                if r.Type == 1:  # To
                    to_list.append(ra)
                    to_emails.append(ra)
                elif r.Type == 2:  # Cc
                    cc_emails.append(ra)

            if my_smtp:
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
            'routing': routing,
            # 振り返りタブ(四半期レビュー)のTier1/Tier2関与判定用。他の既存機能はrouting(to_me/with_me)
            # のみ参照しており、to_emails/cc_emailsを新たに使うのは振り返りタブのみ。
            'to_emails': to_emails,
            'cc_emails': cc_emails,
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

    # ============================================================
    # 振り返りタブ(四半期レビュー)専用: オンラインアーカイブ対応のメール/予定表取得
    # ------------------------------------------------------------
    # ご利用のOutlookは2か月より前のメールがすべて「オンライン アーカイブ」
    # (Exchange/M365のインプレースアーカイブ、既定ストアとは別の最上位メールボックス)に
    # 移動済みのため、既存のget_project_mails等が使うnamespace.GetDefaultFolder(6/5)
    # だけでは6か月分の振り返りに必要な過去分がまったく取得できない。
    # ここでは namespace.Stores を横断し、オンラインアーカイブのストアを検出したうえで、
    # そのルート配下の受信トレイ・送信済みアイテム・予定表も追加で走査する。
    # ============================================================

    def _find_online_archive_root(self, namespace):
        """オンラインアーカイブ(インプレースアーカイブ)のストアのルートフォルダを探す。
        Store.ExchangeStoreType == 3 (olExchangeArchiveMailbox)を第一判定に使い、
        取得できない/該当しない場合のフォールバックとして表示名の先頭一致
        (日本語「オンライン アーカイブ」/英語"Online Archive"等)も見る。
        見つからない場合はNone(アーカイブ未設定、または既定ストアのみの環境)。"""
        try:
            default_store_id = namespace.GetDefaultFolder(6).Store.StoreID
        except Exception:
            default_store_id = None
        archive_name_patterns = ["オンライン アーカイブ", "online archive", "in-place archive", "archive -"]
        try:
            stores = namespace.Stores
            for i in range(1, stores.Count + 1):
                try:
                    store = stores.Item(i)
                except Exception:
                    continue
                try:
                    if default_store_id and store.StoreID == default_store_id:
                        continue
                    is_archive = False
                    try:
                        if int(getattr(store, "ExchangeStoreType", -1)) == 3:  # olExchangeArchiveMailbox
                            is_archive = True
                    except Exception:
                        pass
                    if not is_archive:
                        name = (getattr(store, "DisplayName", "") or "").lower()
                        if any(p in name for p in archive_name_patterns):
                            is_archive = True
                    if is_archive:
                        return store.GetRootFolder()
                except Exception:
                    continue
        except Exception as e:
            print(f"Online Archive Detection Error: {e}")
        return None

    def _find_subfolder_by_names(self, root_folder, name_candidates):
        """root_folder直下の子フォルダから、名前候補リスト(日英両対応)に一致するものを探す。"""
        if not root_folder:
            return None
        try:
            for f in root_folder.Folders:
                if f.Name in name_candidates:
                    return f
        except Exception:
            pass
        return None

    def _find_manual_archive_folders(self, root_folder):
        """root_folder直下から、MANUAL_ARCHIVE_FOLDER_NAMESに一致するフォルダを
        すべて(該当が複数あっても)探して返す。実機調査で、現行メールボックス直下に
        ユーザーがOutlookの「アーカイブ」ボタンで手動退避したメールを溜めている
        「アーカイブ」フォルダ(受信・送信混在、既定フォルダのショートカットが無い)が
        別途存在し、既存のget_review_mails_for_monthが受信トレイ・送信済みアイテム
        (現行+オンラインアーカイブ)しか見ていなかったため、該当期間の活動を
        まるごと取得漏れしていたことが判明した。そのための専用ヘルパー。"""
        if not root_folder:
            return []
        found = []
        try:
            for f in root_folder.Folders:
                if f.Name in MANUAL_ARCHIVE_FOLDER_NAMES:
                    found.append(f)
        except Exception:
            pass
        return found

    def get_review_mails_for_month(self, year: int, month: int, progress_callback=None) -> list:
        """振り返りタブ用: 指定した暦月(1日0時〜翌月1日0時)の受信・送信メールを、
        現行メールボックスとオンラインアーカイブの両方から横断的に取得する。
        既存のget_project_mails等が使う「直近N日を1000件上限で取得」方式ではなく、
        暦月単位でループして毎回Restrictする方式にしているのは、6か月分を一括取得すると
        新しい方から1000件で打ち切られ古い月が丸ごと欠落するのを避けるため。"""
        all_mails = []
        processed_entry_ids = set()
        month_start = datetime(year, month, 1)
        month_end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
        start_str = month_start.strftime("%m/%d/%Y")
        end_str = month_end.strftime("%m/%d/%Y")

        try:
            pythoncom.CoInitialize()
            outlook = win32com.client.Dispatch("Outlook.Application")
            namespace = outlook.GetNamespace("MAPI")

            folders_to_scan = []
            try: folders_to_scan.append(("受信トレイ", namespace.GetDefaultFolder(6)))
            except Exception: pass
            try: folders_to_scan.append(("送信済み", namespace.GetDefaultFolder(5)))
            except Exception: pass

            # 現行メールボックス直下に、ユーザーがOutlookの「アーカイブ」ボタン等で
            # 手動退避させたメールをまとめて溜めているフォルダ(受信・送信混在)がある場合、
            # それも横断的にスキャン対象へ加える(実機調査で発見。既定フォルダの
            # ショートカットが無く、フォルダ名も組織・ユーザーごとに異なるため、
            # MANUAL_ARCHIVE_FOLDER_NAMESの候補名で都度探す)。
            try:
                default_root = namespace.GetDefaultFolder(6).Parent
                for af in self._find_manual_archive_folders(default_root):
                    folders_to_scan.append((f"{af.Name}(手動アーカイブ)", af))
            except Exception: pass

            archive_root = self._find_online_archive_root(namespace)
            archive_inbox = self._find_subfolder_by_names(archive_root, ["受信トレイ", "Inbox"]) if archive_root else None
            archive_sent = self._find_subfolder_by_names(archive_root, ["送信済みアイテム", "Sent Items"]) if archive_root else None
            if archive_inbox: folders_to_scan.append(("受信トレイ(アーカイブ)", archive_inbox))
            if archive_sent: folders_to_scan.append(("送信済み(アーカイブ)", archive_sent))
            if archive_root:
                for af in self._find_manual_archive_folders(archive_root):
                    folders_to_scan.append((f"{af.Name}(手動アーカイブ/オンラインアーカイブ)", af))

            for folder_name, folder in folders_to_scan:
                if progress_callback:
                    progress_callback(0, 0, f"📁 {year}年{month}月 {folder_name} を取得中...")
                try:
                    items = folder.Items
                    items.Sort("[ReceivedTime]", True)
                    try:
                        items = items.Restrict(f"[ReceivedTime] >= '{start_str}' AND [ReceivedTime] < '{end_str}'")
                    except Exception: pass
                    scan_count = 0
                    for item in items:
                        if scan_count >= 2000: break
                        try:
                            self._add_single_item(item, all_mails, processed_entry_ids, folder_name, skip_attachments=True)
                            scan_count += 1
                        except Exception: continue
                except Exception as e:
                    print(f"Review Month Fetch Error [{folder_name} {year}-{month}]: {e}")
        except Exception as e:
            print(f"Review Month Fetch Error [{year}-{month}]: {e}")
        finally:
            try: pythoncom.CoUninitialize()
            except Exception: pass
        return all_mails

    def _get_date_from_appointment_start(self, item):
        r = getattr(item, 'Start', None)
        if r is None: return datetime.now()
        if hasattr(r, 'replace'): return r.replace(tzinfo=None)
        return datetime(r.year, r.month, r.day, r.hour, r.minute, r.second)

    def _meeting_to_dict(self, item, folder_name):
        """AppointmentItemから振り返りタブ用に必要な最小限の情報だけを抽出する。
        is_organizer判定はMeetingStatus(0=単独の予定, 1=自分が主催する会議)を主に用いる。
        (受信した会議の招待はMeetingStatus 3/5/7になり、is_organizer=Falseになる想定。
        この判定の妥当性は実機Outlookでのご確認が必要。)"""
        is_organizer = False
        try:
            is_organizer = int(getattr(item, 'MeetingStatus', 0)) in (0, 1)
        except Exception:
            pass
        attendees = []
        try:
            recipients = item.Recipients
            for r in recipients:
                a = self._resolve_object_to_smtp(r)
                if a: attendees.append(a)
        except Exception:
            pass
        return {
            "subject": getattr(item, 'Subject', '(件名なし)') or '(件名なし)',
            "start": self._get_date_from_appointment_start(item),
            "is_organizer": is_organizer,
            "is_recurring": bool(getattr(item, 'IsRecurring', False)),
            "attendees": attendees,
            "folder": folder_name,
        }

    def get_review_calendar_events(self, year: int, month: int, progress_callback=None) -> list:
        """振り返りタブ用: 指定した暦月の予定表(現行+オンラインアーカイブ)から会議情報を取得する。
        定例会議(繰り返し予定)をIncludeRecurrences=Trueで正しく展開するには、
        Restrictの前に開始日時の昇順ソート(Sort("[Start]"))が必須(降順のままだと
        繰り返しが展開されない、既知のOutlook COM挙動)。他の取得処理の降順ソートとは
        あえて逆にしている点に注意。"""
        events = []
        month_start = datetime(year, month, 1)
        month_end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
        start_str = month_start.strftime("%m/%d/%Y")
        end_str = month_end.strftime("%m/%d/%Y")

        try:
            pythoncom.CoInitialize()
            outlook = win32com.client.Dispatch("Outlook.Application")
            namespace = outlook.GetNamespace("MAPI")

            calendars = []
            try: calendars.append(("予定表", namespace.GetDefaultFolder(9)))
            except Exception: pass
            archive_root = self._find_online_archive_root(namespace)
            archive_cal = self._find_subfolder_by_names(archive_root, ["予定表", "Calendar"]) if archive_root else None
            if archive_cal: calendars.append(("予定表(アーカイブ)", archive_cal))

            for cal_name, cal_folder in calendars:
                if progress_callback:
                    progress_callback(0, 0, f"📅 {year}年{month}月 {cal_name} を取得中...")
                try:
                    items = cal_folder.Items
                    items.Sort("[Start]")  # IncludeRecurrences展開には昇順ソートが必須
                    items.IncludeRecurrences = True
                    try:
                        items = items.Restrict(f"[Start] >= '{start_str}' AND [Start] < '{end_str}'")
                    except Exception: pass
                    scan_count = 0
                    for item in items:
                        if scan_count >= 1000: break
                        try:
                            events.append(self._meeting_to_dict(item, cal_name))
                            scan_count += 1
                        except Exception: continue
                except Exception as e:
                    print(f"Review Calendar Fetch Error [{cal_name} {year}-{month}]: {e}")
        except Exception as e:
            print(f"Review Calendar Fetch Error [{year}-{month}]: {e}")
        finally:
            try: pythoncom.CoUninitialize()
            except Exception: pass
        return events

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
        Gemini共通クライアント(gemini_client.py)への互換シムで初期化する。
        api_key引数は互換性のため残しているが、認証情報は共通モジュール側が
        環境変数(GEMINI_API_KEY / GEMINI_PROXY_URL)から読むため使用されない。
        """
        # クライアントの初期化
        self.client = _CommonGeminiClient(api_key=api_key)
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


    def summarize_action_dashboard(self, threads: dict, progress_callback=None, reset_conversation_ids: set = None, expand_from_cache: bool = False) -> dict:
        """
        アクションダッシュボード用: 期間×自分宛て全体のスレッドを横断解析し、
        フラットな「誰が・何を・いつまでに」のアクション項目一覧を生成する。
        summarize_project_threads の Stage1（スレッド単位抽出）相当のみを、
        特定プロジェクトの知識に依存しない軽量版として実行する。

        expand_from_cache=Trueの場合、今回の取得範囲(threads)に限らず、キャッシュ全体
        (過去のどこかの回で分析された全スレッド)からカードを作る。呼び出し元
        (_run_action_dashboard/_reformat_action_dashboard)が明示的に指定する。
        generate_cockpit_v2_dataのようにプロジェクト単位で呼ぶ既存の呼び出し元は、
        既定のFalse(今回の取得範囲のみ)のままにして挙動・性能を変えない。

        expand_from_cache=Trueのときは、表示するカードを今回の取得範囲(threads)だけに
        限定せず、キャッシュ全体(analysis_cache/action_dashboard.json。過去のどこかの回で
        一度でも分析された全スレッド)から作る。これにより、生成されたHTML側の「表示期間」
        プルダウンで今回の取得期間より広い範囲を選ぶと、過去に放置されている進行中アクションも
        (新たなOutlook取得・AI再解析を行わずに)表示できるようになる。
        受信日時・未読・R19Proj・フラグ等の表示用メタデータ(cache_data["threads"][cid]["meta"])
        は、AI解析結果(data)とは独立して、今回取得できた全スレッドについて毎回更新する
        (mail_countが変わらずAI再解析が不要な場合でも、Outlook側の未読状態等は変わりうる
        ため)。meta が無いキャッシュエントリ(本機能追加前の旧形式で、まだ一度も
        再取得されていないもの)は、正しい表示情報が無いためカード化をスキップする
        (そのスレッドを含む期間で改めて取得すれば、meta付きで表示されるようになる)。
        """
        import os, json as _json
        from concurrent.futures import ThreadPoolExecutor, as_completed

        threads = threads or {}

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

        cache_dirty = bool(needs_update)

        # 表示用メタデータ(受信日時・未読・R19Proj・フラグ・実件名・Outlookで開くためのID)を、
        # 今回取得できた全スレッドについて毎回最新化する(AI再解析の要否とは無関係。
        # mail_countが変わらない=AI再解析不要なスレッドでも、Outlook側の未読状態等は
        # 変わりうるため)。これにより、対象期間を広げて再取得するたびに、その範囲の
        # スレッドの表示情報が実際のOutlookの状態に追従する。
        for cid, t in threads.items():
            if cid not in cache_data["threads"]:
                continue  # AI解析結果がまだ無い(通常は直前のneeds_updateブロックで追加済みのはず)
            latest_date = t.get('latest_date')
            is_r19 = any("R19Proj" in c for c in t.get("all_categories", set()))
            is_flagged = bool(t.get("is_flagged", False))
            meta = {
                "real_topic": t.get("topic", ""),
                "latest_entry_id": t.get("latest_entry_id", ""),
                "latest_date_str": latest_date.strftime("%Y-%m-%d %H:%M") if latest_date else "",
                "latest_date_mmdd": latest_date.strftime("%m/%d %H:%M") if latest_date else "",
                "latest_ts": int(latest_date.timestamp()) if latest_date else 0,
                "has_unread": bool(t.get("has_unread", False)),
                "is_r19": is_r19,
                "is_flagged": is_flagged,
            }
            if cache_data["threads"][cid].get("meta") != meta:
                cache_data["threads"][cid]["meta"] = meta
                cache_dirty = True

        if cache_dirty:
            with open(cache_file, 'w', encoding='utf-8') as f:
                _json.dump(cache_data, f, ensure_ascii=False, indent=2)

        # キャッシュ済みデータ全体(過去のどこかの回で一度でも分析された全スレッド)を
        # 集約し、スレッド単位のカード一覧を作る(1スレッドに複数アクションがあれば
        # 1カードにまとめる)。今回の取得範囲(threads)だけに絞らないのは、生成された
        # HTML側の「表示期間」プルダウンで今回より広い範囲を選んだときに、過去に
        # 放置されている進行中アクションも(新たな取得・AI再解析なしに)表示できるように
        # するため。
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

        if expand_from_cache:
            card_source = list(cache_data["threads"].items())
        else:
            card_source = [(cid, cache_data["threads"].get(cid)) for cid in threads.keys()]
        for cid, cached in card_source:
            if not cached or not cached.get("data"): continue
            data = cached["data"]
            if data.get("_error"): continue
            meta = cached.get("meta")
            if not meta:
                # 本機能追加前の旧形式キャッシュで、まだ一度も再取得されておらず
                # 表示用メタデータが無いエントリ。正しい日時・未読状態・Outlookで
                # 開くためのIDが無いため、このスレッドを含む期間で改めて取得されるまで
                # カード化をスキップする。
                continue
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

            action_cards.append({
                "conversation_id": cid,
                "topic": data.get("topic") or meta.get("real_topic", ""),
                "real_topic": meta.get("real_topic", ""),
                "importance": data.get("importance", "中"),
                "category": data.get("category", "その他"),
                "latest_entry_id": meta.get("latest_entry_id", ""),
                "latest_date_str": meta.get("latest_date_str", ""),
                "latest_date_mmdd": meta.get("latest_date_mmdd", ""),
                "latest_ts": meta.get("latest_ts", 0),
                "has_unread": bool(meta.get("has_unread", False)),
                "is_r19": bool(meta.get("is_r19", False)),
                "is_flagged": bool(meta.get("is_flagged", False)),
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
        「相手が止まっている」(自分が最後に送信し、相手からの返信が無い)も、既に取得済みの
        送信済みメール(include_sent=True)を使って同様に判定する(新規のメール取得は不要)。
        アクション抽出自体は既存の summarize_action_dashboard をそのまま再利用する
        (AIキャッシュはmail_count単位のキーのため、期間ベースでもプロジェクトベースでも
        同じキャッシュの仕組みが機能する)。
        数値の解放スコアは廃止し、「異常の種類」(COCKPIT_V2_CATEGORY_ORDER)で分類する。
        複数プロジェクトの検索結果に同じスレッドが重複して出てくる場合は、conversation_id単位で
        1件に統合し、最初に見つかったプロジェクトを主プロジェクトとする(他は"other_projects"に保持)。
        """
        now = datetime.now()
        projects_out = {}
        # カード上のプロジェクト再分類UI(cockpitReassignProject)で手動変更された
        # プロジェクト割り当てを、キュー項目の表示上のプロジェクトタグにのみ反映する
        # (メール取得元・生体信号(velocity/silence/waiting_on_me_count)は変更しない。
        # あくまで意思決定キューでの分類・グルーピング表示を上書きするだけの機能)。
        project_overrides = load_cockpit_v2_project_overrides()
        # 「✅ 確認済み」にした案件(スレッドのメール件数が変わっていなければ再表示しない)
        acknowledged = load_cockpit_v2_acknowledged()

        project_list = list(project_threads.keys())
        # cid -> {"projects": [proj,...], "card": card, "thread": t, "open_actions": [...]}
        # 複数プロジェクトの検索結果に同じスレッドが重複して現れた場合、ここで1件に統合する。
        candidates = {}

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

            projects_out[proj] = {
                "priority": proj_priority,
                "velocity": velocity,
                "silence": silence,
                "waiting_on_me_count": 0,
                "waiting_on_them_count": 0,
                "thread_count": len(threads),
                # 生体信号カードを「異常があるときだけ」表示するためのフラグ。
                "is_anomaly": bool(silence.get("is_stalled")) or velocity.get("trend") != "→",
            }

            res = self.summarize_action_dashboard(threads, progress_callback=None)
            for card in res.get("action_cards", []):
                cid = card["conversation_id"]
                t = threads.get(cid)
                if not t or not t.get('mails'):
                    continue
                open_actions = [a for a in card.get("actions", []) if a.get("progress") not in ("done", "ignored")]
                if not open_actions:
                    continue

                if cid not in candidates:
                    candidates[cid] = {"projects": [], "card": card, "thread": t, "open_actions": open_actions}
                candidates[cid]["projects"].append(proj)

        queue_items = []
        for cid, c in candidates.items():
            t = c["thread"]
            card = c["card"]
            open_actions = c["open_actions"]
            projects_for_thread = c["projects"]
            primary_project = project_overrides.get(cid, projects_for_thread[0])
            other_projects = [p for p in projects_for_thread if p != primary_project]

            last_sender = (t['mails'][-1].get('sender_email') or '').lower()
            is_waiting_on_me = last_sender != (user_smtp_address or '').lower()

            latest_date = t.get('latest_date') or now
            days_elapsed = max((now - latest_date).total_seconds() / 86400, 0)

            # そのスレッド自身の過去のやり取りペースを基準にした相対沈黙・勢いを求める
            # (compute_relative_silence/compute_mail_velocityはプロジェクト単位でも
            # スレッド単位でも使える純粋関数のため、そのまま流用する)。
            thread_dates = sorted(m['received'] for m in t.get('mails', []) if m.get('received'))
            thread_silence = compute_relative_silence(thread_dates, now)
            thread_velocity = compute_mail_velocity(thread_dates, now)

            if not should_include_in_cockpit_queue(is_waiting_on_me, thread_silence.get("is_stalled", False)):
                continue

            waiting_people = set()
            reminder_count = 0
            has_deadline = False
            for a in open_actions:
                for p in (a.get("waiting_people") or []):
                    if p: waiting_people.add(p)
                reminder_count = max(reminder_count, int(a.get("reminder_count") or 0))
                if (a.get("deadline") or "").strip():
                    has_deadline = True

            mail_count = len(t.get('mails', []))
            ack = acknowledged.get(cid)
            if ack and ack.get("mail_count") == mail_count:
                continue  # 確認済み・スレッドに動きなし → 表示しない

            category_key, category_label = classify_cockpit_item(
                is_waiting_on_me=is_waiting_on_me,
                reminder_count=reminder_count,
                is_stalled=thread_silence.get("is_stalled", False),
                velocity_trend=thread_velocity.get("trend", "→"),
            )

            if primary_project in projects_out:
                if is_waiting_on_me:
                    projects_out[primary_project]["waiting_on_me_count"] += 1
                else:
                    projects_out[primary_project]["waiting_on_them_count"] += 1

            queue_items.append({
                "project": primary_project,
                # 同じスレッドが複数プロジェクトの検索結果にも現れていた場合の、主プロジェクト以外の一覧。
                "other_projects": other_projects,
                "conversation_id": cid,
                "topic": card.get("topic", ""),
                # Outlook側の件名検索(show_thread_in_explorer/開くリンク)に使うため、
                # AI要約タイトルではなく実際のメール件名(real_topic)を別途保持する。
                # AI要約タイトルで検索するとOutlookの件名と一致せずヒットしないため
                # (generate_action_dashboard_reportの既存対応と同じ理由)。
                "real_topic": card.get("real_topic") or card.get("topic", ""),
                "latest_entry_id": card.get("latest_entry_id", ""),
                # スレッドの最終更新(最新メール)の受信日時。件名の横に表示する。
                "latest_date_display": latest_date.strftime("%m/%d %H:%M") if latest_date else "",
                "category_key": category_key,
                "category_label": category_label,
                "days_elapsed": round(days_elapsed, 1),
                "reasons": cockpit_item_reasons(
                    len(waiting_people), days_elapsed, reminder_count,
                    bool(card.get("is_flagged")), has_deadline
                ),
                "is_flagged": bool(card.get("is_flagged")),
                # 確認済み(スヌーズ)状態の判定用。次回生成時、この件数から変化していなければ
                # 「状況に変化なし」として引き続き非表示にする。
                "mail_count": mail_count,
                # このカードに含まれる未完了アクションのキー一覧。「✅ 確認済み」ボタンは
                # action_status.jsonは変更せず(アクションタブとは意図的に非連動)、
                # 別途 /acknowledge_cockpit_v2_item でコックピットv2専用の確認済み状態を保存する。
                "action_keys": [a["action_key"] for a in open_actions],
            })

        queue_items.sort(key=lambda x: (
            COCKPIT_V2_CATEGORY_ORDER.index(x["category_key"]), -x["days_elapsed"]
        ))
        return {
            "generated_at": now.strftime("%Y-%m-%d %H:%M"),
            "projects": projects_out,
            "queue": queue_items,
        }

    def summarize_review_month(self, year: int, month: int, threads: dict, meetings: list,
                                staff_names: list = None, person: str = "Ochi",
                                force_refresh: bool = False,
                                progress_callback=None) -> list:
        """振り返りタブ用: 暦月1か月分の対象スレッド(review_activity_qualifies/
        review_person_activity_qualifiesで機械フィルタ済み)を、AIで複数スレッドの束=「実績」
        単位に統合する(L2活動→L3実績のAI要約)。
        Tier1/Tier2関与・G2小分類・報告ランク・会議紐付け・スタッフ(部下)の成果関与まで、
        この関数の中で annotate してからキャッシュする(以前はgenerate_review_data側で
        毎回annotateしていたが、「対象月チェックボックスで選ばれた月だけ再取得・再分析し、
        それ以外の月はキャッシュからそのまま読み込む」機能に対応するため、annotate済みの
        状態を月単位でキャッシュへ保存し、threads/meetingsが無くてもそのまま使えるようにした)。
        staff_namesはproject_knowledge["staffs"]の登録名一覧(スタッフ俯瞰タブと共通)。
        person: 対象者("Ochi"またはproject_knowledge["staffs"]のキー)。Ochi以外の場合、
        Tier1/Tier2判定・G2小分類・会議紐付けは行わず(Ochiさん自身の対外関与や自分の
        会議は他者の実績評価には無関係のため)、ランクもスタッフ用の決定木
        (rank_review_staff_achievement)で判定する。ゴール分類はjson/review_person_goals.json
        から動的にpersonの定義を読み込みプロンプトへ差し込む(以前はG1/G2/G3がプロンプトへ
        直接ハードコードされていた)。
        過去(先月以前)の月はメール内容が二度と変わらないため、キャッシュが存在すれば
        無条件に再利用し、再取得・再AI呼び出しを一切行わない(振り返りタブ生成のたびに
        毎回全期間を読み込みなおす負荷を避けるための本質的な対策)。当月のみ、対象スレッド
        件数の変化でキャッシュを無効化する。
        force_refresh=Trueの場合、既存キャッシュの状態(過去月か・item_count一致か・
        _errorか)を問わず、このキャッシュ判定を丸ごとスキップして必ずAIを再呼び出しする。
        「対象月チェックボックスをONにした月は、既存キャッシュの有無に関わらず必ず更新する」
        というご要望に対応するためのもの(呼び出し元のgenerate_review_dataでは、
        チェックされて今回メールを再取得した月について常にforce_refresh=Trueを渡す)。"""
        import os, json as _json
        os.makedirs(REVIEW_CACHE_DIR, exist_ok=True)
        yyyymm = f"{year:04d}{month:02d}"
        # Ochiさんは既存キャッシュファイル名("{yyyymm}.json")と完全互換にし、既存の
        # analysis_cache/review_monthly/配下のキャッシュを失効させない。スタッフは
        # "{yyyymm}__{person}.json"に分離する。
        cache_file = os.path.join(REVIEW_CACHE_DIR, f"{yyyymm}{_review_person_cache_suffix(person)}.json")

        now = datetime.now()
        is_closed_month = (year, month) < (now.year, now.month)
        item_count = len(threads)

        if not force_refresh and os.path.exists(cache_file):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cached = _json.load(f)
                # cached["_error"]がTrueの場合(前回このキャッシュがAI呼び出し失敗の結果として
                # 書き込まれた場合)は、過去の月であっても再利用せず必ず再試行する。
                # そうしないと、レート制限や一時的な通信エラーで失敗した月が「実績0件」として
                # 恒久的に固定されてしまう(過去に実際に発生した不具合)。
                if not cached.get("_error") and (is_closed_month or cached.get("item_count") == item_count):
                    if progress_callback: progress_callback(1, 1, f"📦 {year}年{month}月: キャッシュを利用")
                    return cached.get("achievements", [])
            except: pass

        if not threads:
            with open(cache_file, 'w', encoding='utf-8') as f:
                _json.dump({"item_count": 0, "achievements": []}, f, ensure_ascii=False, indent=2)
            return []

        if progress_callback: progress_callback(0, 1, f"⚙️ {year}年{month}月を分析中...")

        # Japan Site Weekly議事録(REVIEW_MINUTES_SUBJECT_KEYWORD)は、全プロジェクトの
        # 進捗が1通に混在した長文になりやすく、通常のスレッドと同じ8000文字切り詰めだと
        # 対象者のパートが途中で欠落する恐れがあるため全文を渡す。また、全体の60000文字上限
        # による切り詰めで議事録が後回しに削られないよう、議事録スレッドを先頭に並べる。
        thread_items = sorted(
            threads.items(),
            key=lambda kv: 0 if review_thread_is_minutes(kv[1]) else 1
        )
        thread_blocks = []
        has_minutes_for_person = False
        for cid, t in thread_items:
            is_minutes = review_thread_is_minutes(t)

            # 議事録は実は自由文ではなく、OneNote由来の進捗表(HTMLBodyに<table>として
            # 残っている)を含んでいることが多い。表からこの対象者の担当行を直接抽出
            # できれば、AIに渡すテキストは最初からこの対象者だけに絞られた状態になり、
            # 自由文からの人物別抽出(他人のパートを誤って拾う・見失うリスク)を避けられる。
            # ただし表の"Function"列は役割名ではなく担当者の姓が入っており(例:"Saji"は
            # そのまま、"Yuto"の場合は本文中で"Oi"表記のためREVIEW_MINUTES_DOC_ALIASESで
            # 変換する必要がある)、PM(Nakai)のように表に行を持たない対象者は
            # 従来通り「Executive Summary」等の自由文からの抽出に頼るしかない。
            structured_text = None
            if is_minutes and person != "Ochi":
                person_aliases = {person.strip().lower()} | {
                    a.strip().lower() for a in REVIEW_MINUTES_DOC_ALIASES.get(person.lower(), [])
                }
                matched_rows = []
                for m in t['mails']:
                    for row in parse_review_minutes_table(m.get('html_body', '')):
                        if (row.get('person') or '').strip().lower() in person_aliases:
                            matched_rows.append(row)
                if matched_rows:
                    structured_text = format_review_minutes_rows_for_person(matched_rows)

            if structured_text:
                content = structured_text
                marker = "【議事録: 進捗表からこの対象者の担当行のみ自動抽出済み】"
            else:
                # _clean_body_for_ai既定のlimit=800では、議事録のような長文本文は先頭800文字で
                # 切られてしまい対象者のパートに到達できない。議事録スレッドに限り、
                # 本文そのものを大きく緩めたlimitで渡す(全文を渡す、が既存の署名・引用カットの
                # 仕組み自体は活かす)。
                body_limit = 50000 if is_minutes else 800
                mail_texts = []
                for m in t['mails']:
                    body = self._clean(self._clean_body_for_ai(m['body'], limit=body_limit))
                    mail_texts.append(f"【送信者:{m['sender_name']}】\n本文:{body}\n")
                raw_content = "".join(mail_texts)
                if is_minutes:
                    content = raw_content
                    marker = "【議事録: 複数人の進捗が混在。下記の抽出指示を参照】" if person != "Ochi" else ""
                    if person != "Ochi":
                        has_minutes_for_person = True
                else:
                    content = raw_content[:8000]
                    marker = ""
            thread_blocks.append(f"=== スレッドID: {cid} / 件名: {t.get('topic','')} {marker} ===\n{content}\n")
        full_content = "\n".join(thread_blocks)[:60000]

        # 会議は常にOchiさん自身が主催したもの(get_review_calendar_events)なので、
        # Ochiさん以外の対象者の実績評価には無関係。personがOchi以外の場合はプロンプトへ
        # 含めない(混同・誤誘導を避けるため)。
        meeting_block = ""
        if meetings and person == "Ochi":
            lines = [f"- {m['subject']} ({m['start'].strftime('%Y-%m-%d') if hasattr(m.get('start'), 'strftime') else m.get('start','')})" for m in meetings[:60]]
            meeting_block = "\n【この月に自分が主催した会議(参考情報。実績の裏付けとして使ってよい)】\n" + "\n".join(lines)

        goal_defs = get_review_person_goal_defs(person)
        goal_prompt_block = build_review_goal_prompt_block(goal_defs)
        subject_desc = (
            "あなた(メール送信者本人)が四半期パフォーマンスレビューでMAG Leader(上司)に報告するための"
            if person == "Ochi"
            else f"部下である{person}さんが四半期パフォーマンスレビューで報告するための"
        )

        # 議事録(【議事録: ...】マーカー付きスレッド)から、この対象者の担当パートだけを
        # 抽出させるための指示。PM(プロジェクト全体)とPE/TE等の個別ファンクションとで
        # 抽出対象の説明を変える(get_review_staff_functionsのファンクション表示に準拠)。
        # project_knowledge登録名(宛先マッチング優先。例:"Yuto")と、議事録本文中の実際の
        # 表記(例:"Oi"/"Oi-san")が異なることがあるため、get_review_minutes_doc_nameで
        # 本文表記へ変換したうえでAIへ伝える(そうしないと、AIが「Yutoさん」という表記で
        # 本文を探しても見つからず、抽出漏れになる)。
        minutes_instruction = ""
        if has_minutes_for_person:
            func_labels = get_review_staff_functions(person)
            doc_name = get_review_minutes_doc_name(person)
            alias_note = f"(社内の登録名は「{person}」だが、この議事録本文では主に「{doc_name}」という表記で登場する)" if doc_name != person else ""
            if "PM" in func_labels:
                focus_desc = "プロジェクト全体の進捗(PM観点のサマリ部分)"
            elif func_labels:
                focus_desc = f"{doc_name}さん{alias_note}自身の{'/'.join(func_labels)}としての進捗パート"
            else:
                focus_desc = f"{doc_name}さん{alias_note}の担当領域に関する進捗パート"
            minutes_instruction = f"""

        【重要: 議事録メールの扱い】上記のスレッドのうち「【議事録: 複数人の進捗が混在。
        下記の抽出指示を参照】」と付記されているものは、Ochiさんが週次で送信するJapan Site
        全体の議事録であり、1通の中にプロジェクト全体(PM)・PE・TEなど複数人の進捗が混在
        している。この議事録からは、{focus_desc}のみを抽出して実績化すること。他の人物の
        パート(担当が異なる箇所)は無視し、実績に含めないこと。該当パートが見当たらない
        場合、そのスレッドからは実績を作らなくてよい。"""

        schema = {
            "type": "OBJECT", "properties": {
                "achievements": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
                    "title": {"type": "STRING"},
                    "summary": {"type": "STRING"},
                    "source_thread_ids": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "is_confirmed": {"type": "BOOLEAN"},
                    "activity_type": {"type": "STRING"},
                    "goal_keys": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "project_key": {"type": "STRING"},
                    "has_quantitative_effect": {"type": "BOOLEAN"},
                    "quantitative_note": {"type": "STRING"},
                    "site_wide": {"type": "BOOLEAN"},
                    "completed_date": {"type": "STRING"},
                }, "required": ["title", "summary", "source_thread_ids", "is_confirmed", "activity_type", "goal_keys", "project_key"]}}
            }, "required": ["achievements"]
        }

        prompt = f"""
        以下は、ある月にOchiさんのメールボックス内で実際にやり取りされた複数のスレッドである。
        {subject_desc}「実績」単位に統合・要約せよ。

        【最重要】単純な1スレッド=1実績の羅列にしないこと。同じ話題・同じ取り組みに関する
        複数のスレッド(例: 同じ施策について8スレッドに分かれてやり取りしている場合)は、
        1件の実績(例:「R04対応:全社DFMEAテンプレートを策定し3製品へ適用」)に統合し、
        source_thread_idsにその全スレッドIDを列挙すること。逆に、無関係な話題を1つの実績に
        まとめてはならない。

        各フィールドの指示:
        - title: 実績のタイトル(30文字程度、成果が分かる体言止め)
        - summary: 実績の要約(2〜3文。何を・なぜ・結果どうなったか)
        - source_thread_ids: この実績の根拠となったスレッドIDの配列(必須、1件以上)
        - is_confirmed: 成果が確定した(完了した、または明確な判断を下した)ならtrue。
          まだ進行中・結論が出ていないものはfalse。
        - activity_type: 必ず次のいずれか1つ: "decision"(判断・決裁) / "execution"(実行・完遂) /
          "systemize"(仕組み化・標準化) / "coordination"(調整・折衝) / "communication"(発信・育成)
        - {goal_prompt_block}
        - project_key: 関連プロジェクトを1つ、次のいずれかで指定:
          "00_Caracal" / "01_Wheeling" / "02_GrandTeton" / "03_R19Projects" /
          "Japan_Site"(特定プロジェクトに紐づかないサイト運営活動) / "Other"
        - has_quantitative_effect: 工数削減時間・件数・パーセンテージなど、定量的な効果を
          summaryまたはメール本文から明示できる場合のみtrue。
        - quantitative_note: has_quantitative_effect=trueの場合、その定量効果を一言で
          (例:「月4時間の確認工数を削減」)。falseなら空文字。
        - site_wide: Japan Site全体(単一プロジェクト・単一部門を超える範囲)に影響する場合true。
        - completed_date: is_confirmed=trueの場合、成果が確定した日付を"YYYY-MM-DD"形式で
          (スレッド内の最新メールの日付を目安にしてよい)。不明ならば空文字。
        {minutes_instruction}

        【対象月のスレッド】
        {full_content}
        {meeting_block}
        """

        res = self._run_genai_call_with_schema(prompt, schema)
        call_failed = not res or res.get("_error")
        achievements = res.get("achievements", []) if not call_failed else []

        # Tier1/Tier2関与・G2小分類・報告ランク・会議紐付けをここでannotateしてからキャッシュする
        # (以前はgenerate_review_data側でthreads/meetingsを使って毎回annotateしていたが、
        # 対象月チェックボックスで選ばれなかった月はthreads/meetingsを取得しないため、
        # annotate済みの状態そのものをキャッシュに保存しておく必要がある)。
        # personがOchi以外の場合、Tier1/Tier2関与・G2小分類・会議紐付けはOchiさん専用の
        # 軸(Ochiさんの対外関与・Ochiさんの主催会議)であり、スタッフ本人の実績には
        # 意味を持たないため付与せず、ランクもスタッフ用の決定木で判定する。
        is_ochi = (person == "Ochi")
        bundled_meetings = bundle_recurring_meetings(meetings) if is_ochi else []
        for a in achievements:
            a["year_month"] = yyyymm
            a["person"] = person
            source_ids = a.get("source_thread_ids", [])
            recipients = []
            activity_dates = []
            source_mails = []
            thread_entry_id = None
            thread_topic = ""
            for cid in source_ids:
                t = threads.get(cid)
                if not t: continue
                if thread_entry_id is None and t.get('latest_entry_id'):
                    thread_entry_id = t['latest_entry_id']
                    thread_topic = t.get('topic', '')
                for m in t['mails']:
                    recipients.extend(m.get('to_emails') or [])
                    recipients.extend(m.get('cc_emails') or [])
                    if m.get('received'): activity_dates.append(m['received'])
                    source_mails.append(m)

            if is_ochi:
                tier_info = classify_review_tier(recipients)
                staff_involved_names = classify_review_staff_involvement(source_mails, staff_names or [])
                matched_meetings = []
                if activity_dates:
                    for bm in bundled_meetings:
                        dates = bm.get('dates') or []
                        if not dates: continue
                        if meeting_matches_activity(bm.get('subject', ''), dates[0], a.get('title', ''), activity_dates):
                            matched_meetings.append(bm)
                g2_subcat = None
                if "G2_site" in (a.get("goal_keys") or []):
                    g2_subcat = classify_review_g2_subcategory(f"{a.get('title','')} {a.get('summary','')}")
                rank = rank_review_achievement(
                    is_confirmed=bool(a.get("is_confirmed")),
                    goal_keys=a.get("goal_keys") or [],
                    tier1_present=bool(tier_info["tier1"]),
                    tier2_count=len(tier_info["tier2"]),
                    site_wide=bool(a.get("site_wide")),
                    has_quantitative=bool(a.get("has_quantitative_effect")),
                    staff_involved=bool(staff_involved_names),
                )
            else:
                tier_info = {"tier1": [], "tier2": []}
                staff_involved_names = []
                matched_meetings = []
                g2_subcat = None
                rank = rank_review_staff_achievement(
                    is_confirmed=bool(a.get("is_confirmed")),
                    goal_keys=a.get("goal_keys") or [],
                    has_quantitative=bool(a.get("has_quantitative_effect")),
                    site_wide=bool(a.get("site_wide")),
                )

            a["tier1"] = tier_info["tier1"]
            a["tier2"] = tier_info["tier2"]
            a["staff_involved"] = staff_involved_names
            a["staff_involved_labels"] = review_staff_function_labels(staff_involved_names)
            a["g2_subcategory"] = g2_subcat
            a["g2_subcategory_label"] = REVIEW_G2_SUBCAT_LABELS.get(g2_subcat, "") if g2_subcat else ""
            a["rank"] = rank
            a["rank_label"] = REVIEW_RANK_LABELS.get(rank, rank)
            a["type_label"] = REVIEW_TYPE_LABELS.get(a.get("activity_type", ""), a.get("activity_type", ""))
            a["project_label"] = REVIEW_PROJECT_LABELS.get(a.get("project_key", ""), a.get("project_key", "その他"))
            a["matched_meetings"] = [
                {"subject": mm.get("subject", ""), "occurrence_count": mm.get("occurrence_count", 1)}
                for mm in matched_meetings
            ]
            a["year_month_label"] = f"{year}年{month}月"
            a["is_manual"] = False
            a["thread_entry_id"] = thread_entry_id
            a["thread_topic"] = thread_topic

        # call_failed=Trueの場合、"achievements": [] を「実績が本当に無かった」結果と
        # 区別できるよう "_error": True を付けて保存する。過去の月であっても次回生成時に
        # 必ず再試行されるようにするため(上のロード側の判定と対になっている)。
        with open(cache_file, 'w', encoding='utf-8') as f:
            _json.dump({
                "item_count": item_count, "achievements": achievements, "_error": bool(call_failed)
            }, f, ensure_ascii=False, indent=2)

        if call_failed:
            err_msg = (res or {}).get("summary", "不明なエラー")
            print(f"⚠️ 振り返り{year}年{month}月: AI分析に失敗したためこの月はスキップしました({err_msg})。次回生成時に自動的に再試行されます。")
            if progress_callback: progress_callback(1, 1, f"⚠️ {year}年{month}月: AI分析失敗(次回再試行)")
        else:
            if progress_callback: progress_callback(1, 1, f"✅ {year}年{month}月: 完了")
        return achievements

    def load_review_month_cache(self, yyyymm: str, person: str = "Ochi") -> list:
        """振り返りタブ用: 対象月チェックボックスで選ばれなかった月について、
        メール再取得・AI再分析を行わず、annotate済みキャッシュをそのまま読み込む。
        キャッシュが無い、またはエラーで保存されたキャッシュだった場合は空リストを返す
        (その月は今回選択されていないため、この場では再試行しない。再試行したい場合は
        チェックボックスをONにして再生成する)。person="Ochi"以外の場合、その対象者が
        過去に一度もこの月で選択・生成されていなければキャッシュが存在せず、空リストになる
        (スタッフを新たに対象へ追加した場合、過去月も含めて生成するには該当月のチェックを
        入れて再生成する必要がある)。"""
        import os, json as _json
        cache_file = os.path.join(REVIEW_CACHE_DIR, f"{yyyymm}{_review_person_cache_suffix(person)}.json")
        if not os.path.exists(cache_file):
            return []
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                cached = _json.load(f)
            if cached.get("_error"):
                return []
            return cached.get("achievements", [])
        except Exception:
            return []

    def generate_review_data(self, monthly_threads: dict, monthly_meetings: dict,
                              all_target_months: list, staff_names: list = None,
                              persons: list = None, progress_callback=None) -> dict:
        """振り返りタブ(四半期パフォーマンスレビュー)用のデータを生成する。
        monthly_threads: {"YYYYMM": {person: {conv_id: thread, ...}, ...}, ...} 形式。
        対象月チェックボックスがONだった月(=今回メールを再取得・再分析する月)についてのみ、
        呼び出し元(_run_review)で対象者ごとにreview_activity_qualifies/
        review_person_activity_qualifiesにより機械フィルタ済みのスレッド辞書を渡す。
        この月・この対象者の組は、既存キャッシュの有無・状態に関わらず必ずforce_refresh=True
        で再分析する(「チェックした月は必ず更新されるはず」という直感に反して、過去月の
        キャッシュ無条件再利用ロジックにより実際には更新されないケースがあったため、
        チェック=強制更新に統一した)。
        all_target_months: チェックボックス一覧に表示されている全ての月("YYYYMM"のリスト、
        ON/OFF問わず)。monthly_threads[yyyymm]に対象者が含まれない月は、
        load_review_month_cacheでキャッシュ済みのannotate結果をそのまま読み込む
        (メール再取得・AI再分析はしない)。これにより「更新したい月だけチェックして
        再生成」が可能になる。
        persons: 対象者のリスト("Ochi"、およびproject_knowledge["staffs"]のキー)。
        Noneまたは空の場合は["Ochi"]として扱う(既存呼び出し元との後方互換)。
        staff_namesはproject_knowledge["staffs"]の登録名一覧(Ochiさんの実績における
        「部下の成果関与」機械判定専用。持ち回りで各対象者の実績生成にもそのまま渡すが、
        person!="Ochi"のsummarize_review_month側では未使用)。
        最後に、手動編集(非表示・ランク上書き・手動追加・文言修正)をreview_manual_items.json
        からマージする。"""
        now = datetime.now()
        persons = persons or ["Ochi"]
        all_achievements = []
        months = sorted(all_target_months)
        total_steps = max(len(months) * len(persons), 1)
        step = 0
        for yyyymm in months:
            year, month = int(yyyymm[:4]), int(yyyymm[4:])
            for person in persons:
                step += 1
                if progress_callback:
                    progress_callback(step, total_steps, f"🎯 {year}年{month}月({person})を統合中...")
                month_threads_by_person = monthly_threads.get(yyyymm) or {}
                if person in month_threads_by_person:
                    achievements = self.summarize_review_month(
                        year, month, month_threads_by_person[person], monthly_meetings.get(yyyymm, []),
                        staff_names=staff_names, person=person, force_refresh=True, progress_callback=None
                    )
                else:
                    achievements = self.load_review_month_cache(yyyymm, person=person)
                all_achievements.extend(achievements)

        # raw_achievements: 手動編集(review_manual_items.json)を反映する"前"の状態。
        # 「フォーマットのみ再生成」はこちらを保存・再利用し、そのつど最新の手動編集を
        # 重複なく反映し直せるようにする(マージ後の状態を保存すると、再生成のたびに
        # 手動追加分が二重に足されてしまうため)。
        raw_achievements = [dict(a) for a in all_achievements]
        merged_achievements = self.apply_review_manual_overrides(all_achievements)

        return {
            "generated_at": now.strftime("%Y-%m-%d %H:%M"),
            "months": months,
            "persons": persons,
            "achievements": merged_achievements,
            "raw_achievements": raw_achievements,
        }

    def apply_review_manual_overrides(self, all_achievements: list) -> list:
        """review_manual_items.jsonの最新値(非表示・ランク上書き・手動追加・文言修正)を、
        AI生成済みの実績リストにマージし、achievement_idを付与・並べ替えまで行う。
        generate_review_data(初回生成時)と、GUI側の「フォーマットのみ再生成」
        (メール再取得・AI再解析なしで保存済み実績に最新の手動編集だけを反映)の両方から
        共通で呼び出す。"""
        manual = load_review_manual_items()

        for manual_id, item in manual.get("added", {}).items():
            item = dict(item)
            item["is_manual"] = True
            item.setdefault("person", "Ochi")
            item.setdefault("source_thread_ids", [])
            item.setdefault("tier1", [])
            item.setdefault("tier2", [])
            item.setdefault("staff_involved", [])
            item.setdefault("staff_involved_labels", [])
            item.setdefault("matched_meetings", [])
            item.setdefault("thread_entry_id", None)
            item.setdefault("thread_topic", "")
            item["rank_label"] = REVIEW_RANK_LABELS.get(item.get("rank", "A"), item.get("rank", "A"))
            item["type_label"] = REVIEW_TYPE_LABELS.get(item.get("activity_type", ""), item.get("activity_type", ""))
            item["project_label"] = REVIEW_PROJECT_LABELS.get(item.get("project_key", ""), item.get("project_key", "その他"))
            completed_date = item.get("completed_date") or ""
            try:
                _completed_dt = datetime.strptime(completed_date[:10], "%Y-%m-%d")
                item["year_month_label"] = f"{_completed_dt.year}年{_completed_dt.month}月"
            except Exception:
                item["year_month_label"] = "手動追加"
            all_achievements.append(item)

        # achievement_idはスタッフ拡張により対象者ごとにスコープ化する
        # ("{person}::{従来の算出結果}")。既存のreview_manual_items.json(hidden/
        # rank_overrides/text_overrides)は接頭辞なしで保存されているため、Ochiさんの実績に
        # ついては接頭辞なしIDでも一致するようフォールバックする(後方互換。新規の書き込みは
        # 今後すべて接頭辞付きで行う)。/review_hidden_listエンドポイント(do_GET)がこの算出式を
        # 独立に再実装しているため、この関数を変更する場合は必ず同時に更新すること。
        def _aid_base(a):
            if a.get("manual_id"):
                return a["manual_id"]
            ids = a.get("source_thread_ids", [])
            return "|".join(ids) if ids else a.get("title", "")

        for a in all_achievements:
            person = a.get("person") or "Ochi"
            base = _aid_base(a)
            a["achievement_id"] = f"{person}::{base}"
            a["_achievement_id_legacy"] = base if person == "Ochi" else None

        def _manual_get(mapping, a, default=None):
            aid = a["achievement_id"]
            if aid in mapping:
                return mapping[aid], True
            legacy = a.get("_achievement_id_legacy")
            if legacy is not None and legacy in mapping:
                return mapping[legacy], True
            return default, False

        hidden_ids = set(manual.get("hidden", []))
        def _is_hidden(a):
            if a["achievement_id"] in hidden_ids:
                return True
            legacy = a.get("_achievement_id_legacy")
            return legacy is not None and legacy in hidden_ids
        all_achievements = [a for a in all_achievements if not _is_hidden(a)]

        rank_overrides = manual.get("rank_overrides", {})
        for a in all_achievements:
            new_rank, found = _manual_get(rank_overrides, a)
            if found:
                a["rank"] = new_rank
                a["rank_label"] = REVIEW_RANK_LABELS.get(new_rank, new_rank)
                a["rank_is_manual"] = True

        text_overrides = manual.get("text_overrides", {})
        for a in all_achievements:
            ov, found = _manual_get(text_overrides, a)
            if found and ov:
                if ov.get("title"): a["title"] = ov["title"]
                if ov.get("summary"): a["summary"] = ov["summary"]

        for a in all_achievements:
            a.pop("_achievement_id_legacy", None)

        all_achievements.sort(key=review_achievement_sort_key)
        return all_achievements

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
        """統括コックピットv2(新コンセプト): アクションダッシュボードとの住み分けを、
        「私は何をやるか(アクションタブ)」vs「何かおかしくなっていないか(ここ)」で分ける。
        数値スコアでの並べ替えは廃止し、異常の種類(COCKPIT_V2_CATEGORY_ORDER)で分類する。
        平常時は空(生体信号は畳み、キューも空)になるのが健全な状態、という設計。
        操作は「✅ 確認済み」1つのみで、action_status.json(アクションタブの進捗)とは
        意図的に非連動にする(cockpit_v2_acknowledged.jsonで別管理)。
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
            project_names = list(projects.keys())

            # --- 生体信号カード: 異常があるプロジェクトだけを大きく出す。全て平常なら1行に畳む ---
            anomaly_projects = {p: v for p, v in projects.items() if v.get("is_anomaly")}
            if anomaly_projects:
                vital_html = []
                for proj, v in anomaly_projects.items():
                    proj_safe = html_mod.escape(proj)
                    prio = v.get("priority", "中")
                    prio_col = {"高": "#d03b3b", "中": "#898781", "低": "#2a78d6"}.get(prio, "#898781")
                    velocity = v.get("velocity", {})
                    silence = v.get("silence", {})
                    trend = velocity.get("trend", "→")
                    stalled = silence.get("is_stalled", False)
                    stall_badge = (
                        f'<span class="recon-badge rc-stall">🔴 沈黙 {silence.get("silence_days", 0)}日</span>'
                        if stalled else f'<span class="recon-badge rc-trend">📈 勢い{trend}</span>'
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
                            <span class="vmetric"><b>{v.get("waiting_on_them_count", 0)}</b>相手待ち</span>
                        </div>
                    </div>''')
                vitals_section = f'<div class="vitals">{"".join(vital_html)}</div>'
            elif project_names:
                vitals_section = f'<div class="q-empty q-empty-zen">✅ {len(project_names)}プロジェクトすべて平常ペースです。</div>'
            else:
                vitals_section = '<div class="q-empty">対象プロジェクトのデータがありません。</div>'

            # --- 意思決定キュー ---
            def _render_queue_row(item):
                cid_safe = html_mod.escape(item.get("conversation_id", ""), quote=True)
                topic_safe = html_mod.escape(item.get("topic", ""))
                proj = item.get("project", "")
                proj_safe = html_mod.escape(proj, quote=True)
                cat_safe = html_mod.escape(item.get("category_key", ""), quote=True)
                date_safe = html_mod.escape(item.get("latest_date_display", ""))
                mail_count = item.get("mail_count", 0)
                # Outlook側の件名検索には、AI要約タイトルではなく実際のメール件名(real_topic)を使う。
                # AI要約タイトルで検索するとOutlookの件名と一致せずスレッドに到達できないため
                # (generate_action_dashboard_reportの既存対応と同じ理由)。
                topic_encoded = quote(item.get("real_topic") or item.get("topic", ""))
                open_url = f'http://localhost:{self.server_port}/open?id={item.get("latest_entry_id","")}&topic={topic_encoded}'
                # Actionタブと同様、件名テキスト自体をクリックするとOutlookのスレッド検索に飛べるようにする
                # (旧「🚀 Outlookで開く」ボタンはこのリンクと機能が重複していたため廃止した)。
                if item.get("latest_entry_id"):
                    ask_html = f'<a class="q-ask" href="{open_url}" target="_blank" title="Outlookでこのスレッドを検索">{topic_safe}</a>'
                else:
                    ask_html = f'<span class="q-ask">{topic_safe}</span>'
                reasons_html = "".join(
                    f'<span class="reason">{html_mod.escape(r)}</span>' for r in item.get("reasons", [])
                )

                # 同じスレッドが複数プロジェクトの検索結果にも重複して現れていた場合の「+N」バッジ。
                other_projects = item.get("other_projects", [])
                other_badge = (
                    f'<span class="q-other-proj" title="{html_mod.escape("、".join(other_projects))}">+{len(other_projects)}</span>'
                    if other_projects else ''
                )

                # カード上でプロジェクトを再分類できるセレクタ。既知のプロジェクトのみ選択肢にする。
                project_options = "".join(
                    f'<option value="{html_mod.escape(p, quote=True)}"{" selected" if p == proj else ""}>{html_mod.escape(p)}</option>'
                    for p in project_names
                )
                project_select = (
                    f'<select class="q-project-select" title="プロジェクトを再分類" '
                    f'onchange="cockpitReassignProject(this, \'{cid_safe}\', {self.server_port})">{project_options}</select>'
                )

                return f'''
                <div class="q-row" data-cid="{cid_safe}" data-project="{proj_safe}" data-category="{cat_safe}">
                    <div class="q-body">
                        {ask_html}<span class="q-date">{date_safe}</span>
                        {project_select}{other_badge}
                        <div class="q-reasons">{reasons_html}</div>
                    </div>
                    <div class="q-right">
                        <button class="q-ack-btn" onclick="cockpitAcknowledge(this, '{cid_safe}', {mail_count}, {self.server_port})">✅ 確認済み</button>
                    </div>
                </div>'''

            # 表示1: 異常の種類別(既定表示)。カテゴリ内は経過日数の降順(データ側で整列済み)。
            by_category = {}
            for item in queue:
                by_category.setdefault(item.get("category_key", ""), []).append(item)
            queue_category_html = []
            for cat_key in COCKPIT_V2_CATEGORY_ORDER:
                items_in_cat = by_category.get(cat_key, [])
                if not items_in_cat:
                    continue
                cat_label = html_mod.escape(COCKPIT_V2_CATEGORY_LABELS.get(cat_key, cat_key))
                rows = "".join(_render_queue_row(item) for item in items_in_cat)
                queue_category_html.append(f'''
                <div class="q-cat-group">
                    <div class="q-cat-head">{cat_label}<span class="q-project-count">{len(items_in_cat)}件</span></div>
                    <div class="q-cat-rows">{rows}</div>
                </div>''')
            if not queue_category_html:
                queue_category_html.append('<div class="q-empty q-empty-zen">🎉 現在、対応が必要な異常はありません。</div>')

            # 表示2: プロジェクト別。各プロジェクトの下階層を、さらに異常の種類別にサブグループ化する
            # (種類別ビューと同じCOCKPIT_V2_CATEGORY_ORDERを使い、件数0の種類は表示しない)。
            # プロジェクト再分類UI(cockpitReassignProject)の移動先として使うため、
            # 0件のプロジェクトも空のグループとして描画しておく
            # (.q-project-rowsが空の場合はCSSの:empty::afterで「該当なし」を表示する)。
            by_project = {}
            for item in queue:
                by_project.setdefault(item.get("project", ""), []).append(item)
            queue_project_html = []
            for proj in project_names:
                items_in_proj = by_project.get(proj, [])
                proj_safe = html_mod.escape(proj, quote=True)
                proj_label = html_mod.escape(proj)

                by_category_in_proj = {}
                for item in items_in_proj:
                    by_category_in_proj.setdefault(item.get("category_key", ""), []).append(item)
                subgroups_html = []
                for cat_key in COCKPIT_V2_CATEGORY_ORDER:
                    items_in_cat = by_category_in_proj.get(cat_key, [])
                    if not items_in_cat:
                        continue
                    cat_safe = html_mod.escape(cat_key, quote=True)
                    cat_label = html_mod.escape(COCKPIT_V2_CATEGORY_LABELS.get(cat_key, cat_key))
                    subrows = "".join(_render_queue_row(item) for item in items_in_cat)
                    subgroups_html.append(f'''
                    <div class="q-subcat-group" data-category="{cat_safe}">
                        <div class="q-subcat-head">{cat_label}<span class="q-project-count">{len(items_in_cat)}件</span></div>
                        <div class="q-subcat-rows">{subrows}</div>
                    </div>''')

                queue_project_html.append(f'''
                <div class="q-project-group" data-project="{proj_safe}">
                    <div class="q-project-head">{proj_label}<span class="q-project-count">{len(items_in_proj)}件</span></div>
                    <div class="q-project-rows">{"".join(subgroups_html)}</div>
                </div>''')
            if not queue_project_html:
                queue_project_html.append('<div class="q-empty q-empty-zen">🎉 現在、対応が必要な異常はありません。</div>')

            import json as _json_mod
            category_labels_js = _json_mod.dumps(COCKPIT_V2_CATEGORY_LABELS, ensure_ascii=False)

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
.rc-trend{{color:var(--blue);background:color-mix(in srgb,var(--blue) 14%,transparent);}}
.vcard-metrics{{display:flex;justify-content:space-between;font-size:.76rem;color:var(--ink2);margin-top:6px;gap:8px;}}
.vmetric{{white-space:nowrap;}}
.vmetric b{{font-size:1.05rem;color:var(--ink);}}
.hero{{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:6px 4px;overflow:hidden;}}
.q-row{{display:grid;grid-template-columns:1fr auto;gap:12px;align-items:center;
  padding:13px 16px;border-top:1px solid var(--grid);}}
.q-row:first-child{{border-top:none;}}
.q-ask{{font-weight:650;color:var(--ink);text-decoration:none;}}
a.q-ask:hover{{text-decoration:underline;color:var(--blue);cursor:pointer;}}
.q-date{{font-size:.7rem;color:var(--muted);margin-left:8px;white-space:nowrap;}}
.q-project-select{{font-size:.7rem;color:var(--ink2);background:var(--chip);border:1px solid var(--border);
  border-radius:5px;padding:1px 4px;margin-left:8px;cursor:pointer;}}
.q-other-proj{{font-size:.66rem;color:var(--ink2);background:var(--chip);border:1px solid var(--border);
  border-radius:10px;padding:1px 6px;margin-left:4px;}}
.q-reasons{{margin-top:6px;display:flex;flex-wrap:wrap;gap:6px;}}
.reason{{font-size:.72rem;color:var(--ink2);background:var(--chip);border:1px solid var(--border);
  border-radius:20px;padding:2px 9px;white-space:nowrap;}}
.q-right{{text-align:right;}}
.q-empty{{padding:20px;text-align:center;color:var(--muted);}}
.q-empty-zen{{padding:28px;font-size:.95rem;color:var(--good-ink);font-weight:600;}}
.q-ack-btn{{font-size:.72rem;border:1px solid var(--border);border-radius:12px;padding:4px 11px;
  background:var(--chip);color:var(--ink2);cursor:pointer;white-space:nowrap;}}
.q-ack-btn:hover{{background:color-mix(in srgb,var(--good) 18%,transparent);color:var(--good-ink);border-color:var(--good);}}
.view-toggle{{display:flex;gap:8px;margin-bottom:10px;}}
.view-toggle-btn{{font-size:.78rem;font-weight:600;border:1px solid var(--border);border-radius:20px;
  padding:5px 14px;background:var(--surface);color:var(--ink2);cursor:pointer;}}
.view-toggle-btn.active{{background:var(--blue);color:#fff;border-color:var(--blue);}}
.q-cat-group, .q-project-group{{border-top:1px solid var(--grid);}}
.q-cat-group:first-child, .q-project-group:first-child{{border-top:none;}}
.q-cat-head, .q-project-head{{display:flex;align-items:center;gap:8px;font-weight:700;font-size:.85rem;
  padding:9px 16px;color:var(--ink);background:var(--chip);border-left:4px solid var(--blue);
  position:sticky;top:0;z-index:5;}}
.q-project-count{{font-size:.68rem;font-weight:400;color:var(--muted);background:var(--surface);
  border-radius:10px;padding:1px 8px;}}
.q-project-rows:empty::after{{content:"該当なし";display:block;padding:10px 16px;
  color:var(--muted);font-size:.78rem;}}
/* プロジェクト別ビューの下階層(種類別サブグループ)。上位のプロジェクト見出しより控えめに、
   インデントして表示する(sticky化はせず、常に見えているプロジェクト見出しと区別する)。 */
.q-subcat-group{{border-top:1px dashed var(--grid);}}
.q-subcat-group:first-child{{border-top:none;}}
.q-subcat-head{{display:flex;align-items:center;gap:8px;font-weight:600;font-size:.76rem;
  padding:7px 16px 7px 28px;color:var(--ink2);border-left:3px solid var(--muted);
  background:color-mix(in srgb, var(--chip) 55%, transparent);}}
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

  <div class="section-label">プロジェクトの生体信号（異常があるプロジェクトのみ表示）</div>
  {vitals_section}

  <div class="section-label">対応が必要な異常（種類別・理由つき）</div>
  <div class="view-toggle">
    <button id="viewBtnCategory" class="view-toggle-btn active" onclick="cockpitSetView('category')">⚠️ 種類別</button>
    <button id="viewBtnProject" class="view-toggle-btn" onclick="cockpitSetView('project')">🗂️ プロジェクト別</button>
  </div>
  <div id="queue-category" class="hero">
    {"".join(queue_category_html)}
  </div>
  <div id="queue-project" class="hero" style="display:none;">
    {"".join(queue_project_html)}
  </div>

  <div class="footer-note">
    ここは「私は何をやるか」を管理するアクションダッシュボードとは別に、「何かおかしくなっていないか」だけを見る画面です。
    🔥催促されている・🧊相手が止まっている(自分が最後に送信し返信が無い)・🕰長期沈黙(そのスレッド自身の平常ペースの2倍以上動きがない)・
    📈急に燃えている(直近でやり取りが急増)・📥自分待ち、のいずれかに該当するスレッドだけを表示しています。
    「✅ 確認済み」を押すと、スレッドに新しい動きがあるまで再表示されません。空欄＝現在は健全な状態です。
  </div>
</div>
<script>
// プロジェクト再分類時、移動先プロジェクトにまだ同じ種類のサブグループが無い場合に、
// その場でサブグループの見出しを作成するためのラベル定義(Python側COCKPIT_V2_CATEGORY_LABELSと対応)。
const COCKPIT_V2_CATEGORY_LABELS_JS = {category_labels_js};
async function cockpitAcknowledge(btn, cid, mailCount, port) {{
    btn.disabled = true;
    try {{
        await fetch(`http://localhost:${{port}}/acknowledge_cockpit_v2_item`, {{
            method: 'POST', headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{conversation_id: cid, mail_count: mailCount}})
        }});
    }} catch (e) {{ console.error(e); }}
    document.querySelectorAll(`.q-row[data-cid="${{cid}}"]`).forEach(row => {{ row.style.display = 'none'; }});
    cockpitRecomputeCounts();
}}
function cockpitRecomputeCounts() {{
    document.querySelectorAll('.q-project-group, .q-cat-group, .q-subcat-group').forEach(group => {{
        const rows = group.querySelectorAll('.q-row');
        const visibleCount = Array.from(rows).filter(r => r.style.display !== 'none').length;
        const countEl = group.querySelector('.q-project-count');
        if (countEl) countEl.textContent = visibleCount + '件';
    }});
}}
async function cockpitReassignProject(select, cid, port) {{
    const newProject = select.value;
    try {{
        await fetch(`http://localhost:${{port}}/update_cockpit_v2_project`, {{
            method: 'POST', headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{conversation_id: cid, project: newProject}})
        }});
    }} catch (e) {{ console.error(e); }}

    // 種類別ビュー・プロジェクト別ビュー、両方の同じcidの行のタグ・セレクタを揃える。
    document.querySelectorAll(`.q-row[data-cid="${{cid}}"]`).forEach(row => {{
        row.dataset.project = newProject;
        const sel = row.querySelector('.q-project-select');
        if (sel && sel !== select) sel.value = newProject;
    }});

    // プロジェクト別ビューの行は、実際に新しいプロジェクト×同じ種類のサブグループへ移動させる。
    // 移動先プロジェクトにまだそのカテゴリのサブグループが無ければ、その場で新規作成する。
    document.querySelectorAll(`#queue-project .q-row[data-cid="${{cid}}"]`).forEach(row => {{
        const category = row.dataset.category;
        const projectGroup = document.querySelector(
            `#queue-project .q-project-group[data-project="${{CSS.escape(newProject)}}"]`
        );
        if (!projectGroup) return;
        let subcatGroup = projectGroup.querySelector(`.q-subcat-group[data-category="${{CSS.escape(category)}}"]`);
        if (!subcatGroup) {{
            subcatGroup = document.createElement('div');
            subcatGroup.className = 'q-subcat-group';
            subcatGroup.dataset.category = category;
            const head = document.createElement('div');
            head.className = 'q-subcat-head';
            head.textContent = COCKPIT_V2_CATEGORY_LABELS_JS[category] || category;
            const countSpan = document.createElement('span');
            countSpan.className = 'q-project-count';
            countSpan.textContent = '0件';
            head.appendChild(countSpan);
            const rowsDiv = document.createElement('div');
            rowsDiv.className = 'q-subcat-rows';
            subcatGroup.appendChild(head);
            subcatGroup.appendChild(rowsDiv);
            projectGroup.querySelector('.q-project-rows').appendChild(subcatGroup);
        }}
        const targetRows = subcatGroup.querySelector('.q-subcat-rows');
        if (targetRows && row.parentElement !== targetRows) {{
            targetRows.appendChild(row);
        }}
    }});
    cockpitRecomputeCounts();
}}
function cockpitSetView(mode) {{
    document.getElementById('queue-category').style.display = (mode === 'category') ? '' : 'none';
    document.getElementById('queue-project').style.display = (mode === 'project') ? '' : 'none';
    document.getElementById('viewBtnCategory').classList.toggle('active', mode === 'category');
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

    def generate_review_report(self, review_data, period_label, total_input, total_output, reformat_mode=False, filter_person: str = None) -> str:
        """振り返りタブ(四半期パフォーマンスレビュー)用HTML。
        review_data は MailSummarizer.generate_review_data() の戻り値。
        3つの表示軸(ゴール別=既定・プロジェクト別・月別タイムライン)を切り替えられる。
        ゴール別ビューでは、goal_keysが複数(例: G1_project + G3_r04)の実績は該当する
        すべてのゴール見出しの下に(同じachievement_idで)重複表示する(二重帰属を許す設計)。
        ランクフィルタ(既定でB=実績リストは畳む)・非表示・ランク上書き・文言修正・手動追加は
        いずれも review_manual_items.json 経由(統括コックピットv2の確認済み/再分類UIと
        同じfetchパターン)。「📋 コピー用テキストを生成」で、現在表示中の実績をMarkdown化して
        コピーできる(レビューフォーム等への貼り付け用)。
        filter_person: 指定した場合、その対象者の実績だけに絞り込んだ「その人専用」の
        HTMLを生成する(ファイル名にも対象者名を含める)。四半期パフォーマンスレビューという
        用途上、複数人の実績を1つのHTMLに混在させると本人以外の評価内容が見えてしまうため、
        呼び出し元(_run_review/_reformat_review)は必ずこれを指定し、対象者ごとに
        本メソッドを繰り返し呼び出して別々のファイルを生成する。"""
        import html as html_mod
        import re as re_mod
        from urllib.parse import quote

        try:
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            if not self.folder.exists():
                self.folder.mkdir(parents=True)
            if filter_person:
                safe_person = re_mod.sub(r'[^0-9A-Za-z_\-]+', '_', filter_person).strip('_') or "person"
                path = self.folder / f"Review_{safe_person}_{ts}.html"
            else:
                path = self.folder / f"Review_{ts}.html"

            in_cost = (total_input / 1000000) * 0.075 * 160
            out_cost = (total_output / 1000000) * 0.3 * 160
            total_yen = round(in_cost + out_cost, 2)
            cost_display = (
                "🎨 フォーマット再生成のみ（APIコスト無し）"
                if reformat_mode
                else f"💰 APIコスト概算: 約 {total_yen} 円 (In:{total_input} / Out:{total_output})"
            )

            achievements = review_data.get("achievements", [])
            if filter_person:
                achievements = [a for a in achievements if (a.get("person") or "Ochi") == filter_person]
            generated_at = html_mod.escape(review_data.get("generated_at", ""))
            period_label_display = f"{period_label}　｜　対象者: {filter_person}" if filter_person else period_label
            period_label_safe = html_mod.escape(period_label_display)

            rank_counts = {"S": 0, "A": 0, "B": 0, "P": 0}
            for a in achievements:
                rank_counts[a.get("rank", "B")] = rank_counts.get(a.get("rank", "B"), 0) + 1

            def _chip(text, cls=""):
                return f'<span class="rv-chip {cls}">{html_mod.escape(text)}</span>'

            def _render_row(a):
                aid_safe = html_mod.escape(a.get("achievement_id", ""), quote=True)
                title_safe = html_mod.escape(a.get("title", "(無題)"))
                summary_safe = html_mod.escape(a.get("summary", ""))
                rank = a.get("rank", "B")
                rank_label_safe = html_mod.escape(a.get("rank_label", rank))
                type_label = a.get("type_label", "")
                project_label = a.get("project_label", "")
                ym_label = a.get("year_month_label", "")
                person = a.get("person", "Ochi")
                chips = []
                # スタッフ拡張: 対象者がOchiさん以外の実績には人物チップを付け、
                # 複数人物混在時でも誰の実績か一目でわかるようにする(4軸目は作らず、
                # 既存3軸+人物チップという最小限の変更に留める)。
                if person and person != "Ochi": chips.append(_chip(f"👤 {person}", "rv-c-person"))
                if type_label: chips.append(_chip(type_label, "rv-c-type"))
                if project_label: chips.append(_chip(f"🗂 {project_label}", "rv-c-proj"))
                if ym_label: chips.append(_chip(ym_label, "rv-c-ym"))
                if a.get("g2_subcategory_label"): chips.append(_chip(a["g2_subcategory_label"], "rv-c-g2"))
                for name in a.get("tier1", []):
                    chips.append(_chip(f"👔 {name}", "rv-c-tier1"))
                if len(a.get("tier2", [])) >= 2:
                    chips.append(_chip(f"🌐 部門横断({len(a['tier2'])})", "rv-c-tier2"))
                elif a.get("tier2"):
                    chips.append(_chip(f"🤝 {a['tier2'][0]}", "rv-c-tier2"))
                if a.get("site_wide"): chips.append(_chip("🏛 Japan Site全体", "rv-c-site"))
                if a.get("has_quantitative_effect") and a.get("quantitative_note"):
                    chips.append(_chip(f"📊 {a['quantitative_note']}", "rv-c-quant"))
                for label in a.get("staff_involved_labels", []):
                    chips.append(_chip(f"👥 {label}が主導", "rv-c-staff"))
                for mm in a.get("matched_meetings", []):
                    label = mm.get("subject", "")
                    if mm.get("occurrence_count", 1) > 1:
                        label += f"(全{mm['occurrence_count']}回)"
                    chips.append(_chip(f"📅 {label}", "rv-c-meet"))
                if a.get("is_manual"): chips.append(_chip("✍️ 手動追加", "rv-c-manual"))
                if not a.get("is_manual"):
                    chips.append(_chip(f"📎 {len(a.get('source_thread_ids', []))}スレッド根拠", "rv-c-src"))

                rank_opts = "".join(
                    f'<option value="{r}"{" selected" if r == rank else ""}>{html_mod.escape(REVIEW_RANK_LABELS[r])}</option>'
                    for r in REVIEW_RANK_ORDER
                )

                # アクションタブと同じ流儀: タイトル自体をリンクにし、検索にはAI要約タイトルではなく
                # 実際のメール件名(thread_topic)を渡す(AI要約タイトルではOutlookの件名と一致せず
                # ヒットしないため)。根拠スレッドが無い手動追加項目はリンク無しのまま表示する。
                if a.get("thread_entry_id"):
                    topic_encoded = quote(a.get("thread_topic") or "")
                    open_url = f'http://localhost:{self.server_port}/open?id={a["thread_entry_id"]}&topic={topic_encoded}'
                    title_html = f'<a class="rv-title" href="{open_url}" target="_blank" title="Outlookでこのメールを検索">{title_safe}</a>'
                else:
                    title_html = f'<span class="rv-title">{title_safe}</span>'

                person_safe = html_mod.escape(person or "Ochi", quote=True)
                return f'''
                <div class="rv-row" data-aid="{aid_safe}" data-rank="{rank}" data-person="{person_safe}">
                    <div class="rv-body">
                        <div class="rv-title-line">
                            <span class="rv-rank-badge rv-rank-{rank}">{rank_label_safe}</span>
                            {title_html}
                        </div>
                        <div class="rv-summary">{summary_safe}</div>
                        <div class="rv-chips">{"".join(chips)}</div>
                    </div>
                    <div class="rv-right">
                        <select class="rv-rank-select" title="ランクを手動変更" onchange="reviewSetRank(this, '{aid_safe}', {self.server_port})">{rank_opts}</select>
                        <button class="rv-hide-btn" onclick="reviewHide(this, '{aid_safe}', {self.server_port})" title="この実績を非表示にする">🙈 非表示</button>
                    </div>
                </div>'''

            # --- 表示1: ゴール別(既定)。goal_keysが複数あれば該当する全ゴールの下に重複表示する ---
            # スタッフ拡張: Ochiさん以外の対象者はKPIキー体系がOchiさんのG1/G2/G3と異なる
            # (対象者ごとにK1..K8等、キー名も意味も別)ため、REVIEW_GOAL_ORDER(Ochi専用の
            # 固定3ゴール)へは混ぜず、person=="Ochi"の実績だけをこのbuy_goalに集計する。
            # Ochiさん以外の実績はstaff_by_person_goalへ対象者ごとに集計し、Ochiさんの
            # 3ゴールに続けて対象者別のサブセクションとして追記する(既存3軸の構造・見た目は
            # Ochiさん単独時に限り一切変更しない)。
            by_goal = {g: [] for g in REVIEW_GOAL_ORDER}
            no_goal = []
            staff_by_person_goal = {}  # person -> {goal_key: [achievements]}
            staff_persons_present = []  # 出現順
            for a in achievements:
                gks = a.get("goal_keys") or []
                person = a.get("person", "Ochi")
                if not gks:
                    no_goal.append(a)
                    continue
                if person == "Ochi":
                    for g in gks:
                        if g in by_goal:
                            by_goal[g].append(a)
                else:
                    if person not in staff_by_person_goal:
                        staff_by_person_goal[person] = {}
                        staff_persons_present.append(person)
                    for g in gks:
                        staff_by_person_goal[person].setdefault(g, []).append(a)

            goal_sections = []
            # Ochiさん専用のG1/G2/G3見出しは、Ochiさん以外の対象者専用レポート
            # (filter_person指定時)には無関係(そのスタッフのKPIキー体系はK1..等で別物)
            # なので出さない。filter_person未指定(全員混在。現在は呼び出し元が使わない
            # 後方互換パスのみ)またはfilter_person=="Ochi"のときだけ表示する。
            if filter_person is None or filter_person == "Ochi":
                for g in REVIEW_GOAL_ORDER:
                    items = by_goal.get(g, [])
                    label = html_mod.escape(REVIEW_GOAL_LABELS.get(g, g))
                    if g == "G2_site" and items:
                        by_subcat = {}
                        no_subcat = []
                        for a in items:
                            sc = a.get("g2_subcategory")
                            if sc: by_subcat.setdefault(sc, []).append(a)
                            else: no_subcat.append(a)
                        sub_html = []
                        for sc_key, sc_label in REVIEW_G2_SUBCAT_LABELS.items():
                            sc_items = by_subcat.get(sc_key, [])
                            if not sc_items: continue
                            rows = "".join(_render_row(a) for a in sc_items)
                            sub_html.append(f'''
                            <div class="rv-subcat-group">
                                <div class="rv-subcat-head">{html_mod.escape(sc_label)}<span class="rv-count">{len(sc_items)}件</span></div>
                                <div class="rv-subcat-rows">{rows}</div>
                            </div>''')
                        if no_subcat:
                            # 小分類が付かないG2実績は、.rv-subcat-groupで包まずに.rv-goal-rowsの直下に
                            # 平置きする(包んでしまうと、コピー用テキスト生成・件数再計算のJSが
                            # ".rv-goal-group > .rv-goal-rows > .rv-row" / ".rv-subcat-group > .rv-subcat-rows
                            # > .rv-row" という直接の親子関係だけを見ているため、中途半端なラッパーに
                            # 入れると行が拾われず取りこぼす)。
                            sub_html.append("".join(_render_row(a) for a in no_subcat))
                        body = "".join(sub_html)
                    else:
                        body = "".join(_render_row(a) for a in items) if items else ''
                    goal_sections.append(f'''
                    <div class="rv-goal-group" data-goal="{html_mod.escape(g, quote=True)}">
                        <div class="rv-goal-head">{label}<span class="rv-count">{len(items)}件</span></div>
                        <div class="rv-goal-rows">{body}</div>
                    </div>''')

            # スタッフのゴール別サブセクション(対象者ごと、その人自身のKPI順に表示)。
            # json/review_person_goals.jsonのキー順(≒登録順)をそのまま見出し順に使う。
            if staff_persons_present:
                goals_data_for_report = load_review_person_goals()
                for person in staff_persons_present:
                    goal_defs = get_review_person_goal_defs(person, goals_data_for_report)
                    person_goal_items = staff_by_person_goal.get(person, {})
                    ordered_keys = list(goal_defs.keys()) if goal_defs else sorted(person_goal_items.keys())
                    for k in person_goal_items.keys():
                        if k not in ordered_keys:
                            ordered_keys.append(k)
                    for gk in ordered_keys:
                        items = person_goal_items.get(gk, [])
                        if not items:
                            continue
                        label_text = goal_defs.get(gk, {}).get("label", gk) if goal_defs else gk
                        label = html_mod.escape(f"👤 {person} - {label_text}")
                        rows = "".join(_render_row(a) for a in items)
                        goal_sections.append(f'''
                        <div class="rv-goal-group" data-goal="{html_mod.escape(f"{person}::{gk}", quote=True)}">
                            <div class="rv-goal-head">{label}<span class="rv-count">{len(items)}件</span></div>
                            <div class="rv-goal-rows">{rows}</div>
                        </div>''')

            if no_goal:
                rows = "".join(_render_row(a) for a in no_goal)
                goal_sections.append(f'''
                <div class="rv-goal-group" data-goal="none">
                    <div class="rv-goal-head">ゴール外<span class="rv-count">{len(no_goal)}件</span></div>
                    <div class="rv-goal-rows">{rows}</div>
                </div>''')
            view_goal_html = "".join(goal_sections)

            # --- 表示2: プロジェクト別 ---
            by_project = {}
            for a in achievements:
                by_project.setdefault(a.get("project_key", "Other"), []).append(a)
            project_sections = []
            for pk in list(REVIEW_PROJECT_LABELS.keys()):
                items = by_project.get(pk, [])
                if not items: continue
                label = html_mod.escape(REVIEW_PROJECT_LABELS[pk])
                rows = "".join(_render_row(a) for a in items)
                project_sections.append(f'''
                <div class="rv-goal-group">
                    <div class="rv-goal-head">{label}<span class="rv-count">{len(items)}件</span></div>
                    <div class="rv-goal-rows">{rows}</div>
                </div>''')
            view_project_html = "".join(project_sections) or '<div class="rv-empty">実績がありません。</div>'

            # --- 表示3: 月別タイムライン(新しい月が先頭) ---
            by_month = {}
            for a in achievements:
                by_month.setdefault(a.get("year_month_label", "手動追加"), []).append(a)
            timeline_sections = []
            for ym in sorted(by_month.keys(), reverse=True):
                items = by_month[ym]
                rows = "".join(_render_row(a) for a in items)
                timeline_sections.append(f'''
                <div class="rv-goal-group">
                    <div class="rv-goal-head">{html_mod.escape(ym)}<span class="rv-count">{len(items)}件</span></div>
                    <div class="rv-goal-rows">{rows}</div>
                </div>''')
            view_timeline_html = "".join(timeline_sections) or '<div class="rv-empty">実績がありません。</div>'

            project_options_html = "".join(
                f'<option value="{html_mod.escape(k, quote=True)}">{html_mod.escape(v)}</option>'
                for k, v in REVIEW_PROJECT_LABELS.items()
            )

            # 手動追加フォームの「対象者」プルダウンとゴールチェックボックス。
            # 対象者ごとにゴール(KPI)キー体系が異なる(Ochi=G1/G2/G3固定、スタッフ=K1..等)
            # ため、json/review_person_goals.jsonの定義をJSへ埋め込み、対象者選択時に
            # チェックボックスをJS側で動的に再構築する(reviewRenderAddGoals)。
            if filter_person:
                # 1ファイル=1対象者のレポートなので、手動追加フォームの対象者プルダウンも
                # その対象者のみに固定する(他人の実績を混在させないため)。
                report_persons = [filter_person]
            else:
                report_persons = []
                _seen_rp = set()
                for a in achievements:
                    p = a.get("person", "Ochi")
                    if p not in _seen_rp:
                        _seen_rp.add(p)
                        report_persons.append(p)
                if "Ochi" in report_persons:
                    report_persons.remove("Ochi")
                report_persons.insert(0, "Ochi")

            goals_data_all = load_review_person_goals()
            person_goals_js = {}
            for p in report_persons:
                defs = get_review_person_goal_defs(p, goals_data_all)
                person_goals_js[p] = [[k, (d.get("label", k) if isinstance(d, dict) else str(d))] for k, d in defs.items()]
            person_goals_json = json.dumps(person_goals_js, ensure_ascii=False)
            person_options_html = "".join(
                f'<option value="{html_mod.escape(p, quote=True)}">{html_mod.escape(p)}</option>'
                for p in report_persons
            )

            page_title = html_mod.escape(f"四半期振り返り - {filter_person}" if filter_person else "四半期振り返り")
            html_content = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>{page_title}</title>
<style>
:root{{ color-scheme: light;
  --page:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --border:rgba(11,11,11,0.10); --blue:#2a78d6;
  --good:#0ca30c; --good-ink:#006300; --chip:#f0efec; --gold:#b7860b; }}
@media (prefers-color-scheme: dark){{ :root:where(:not([data-theme="light"])){{ color-scheme: dark;
  --page:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --border:rgba(255,255,255,0.10); --blue:#3987e5;
  --good-ink:#0ca30c; --chip:#2c2c2a; --gold:#e0ac2b; }} }}
:root[data-theme="dark"]{{ color-scheme: dark; --page:#0d0d0d; --surface:#1a1a19; --ink:#ffffff;
  --ink2:#c3c2b7; --muted:#898781; --grid:#2c2c2a; --border:rgba(255,255,255,0.10);
  --blue:#3987e5; --good-ink:#0ca30c; --chip:#2c2c2a; --gold:#e0ac2b; }}
*{{box-sizing:border-box;}}
body{{margin:0;background:var(--page);color:var(--ink);
  font-family:system-ui,-apple-system,"Segoe UI",sans-serif;line-height:1.5;}}
.wrap{{max-width:1180px;margin:0 auto;padding:20px 20px 60px;}}
.topbar{{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-bottom:6px;}}
h1{{font-size:1.5rem;margin:0;}}
.subtitle{{color:var(--ink2);font-size:.85rem;}}
.cost{{margin-left:auto;font-size:.78rem;color:var(--ink2);}}
.rv-toolbar{{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:14px 0;}}
.rv-toggle-btn{{font-size:.78rem;font-weight:600;border:1px solid var(--border);border-radius:20px;
  padding:5px 14px;background:var(--surface);color:var(--ink2);cursor:pointer;}}
.rv-toggle-btn.active{{background:var(--blue);color:#fff;border-color:var(--blue);}}
.rv-rank-filter{{font-size:.75rem;font-weight:600;border:1px solid var(--border);border-radius:20px;
  padding:4px 12px;background:var(--chip);color:var(--ink2);cursor:pointer;}}
.rv-rank-filter.active{{border-color:var(--gold);color:var(--gold);}}
.rv-copy-btn{{margin-left:auto;font-size:.78rem;font-weight:600;border:1px solid var(--border);
  border-radius:20px;padding:6px 14px;background:var(--surface);color:var(--ink2);cursor:pointer;}}
.hero{{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:6px 4px;overflow:hidden;}}
.rv-goal-group{{border-top:1px solid var(--grid);}}
.rv-goal-group:first-child{{border-top:none;}}
.rv-goal-head{{display:flex;align-items:center;gap:8px;font-weight:700;font-size:.9rem;
  padding:10px 16px;color:var(--ink);background:var(--chip);border-left:4px solid var(--blue);
  position:sticky;top:0;z-index:5;}}
.rv-count{{font-size:.68rem;font-weight:400;color:var(--muted);background:var(--surface);
  border-radius:10px;padding:1px 8px;}}
.rv-goal-rows:empty::after{{content:"該当なし";display:block;padding:10px 16px;color:var(--muted);font-size:.78rem;}}
.rv-subcat-group{{border-top:1px dashed var(--grid);}}
.rv-subcat-group:first-child{{border-top:none;}}
.rv-subcat-head{{display:flex;align-items:center;gap:8px;font-weight:600;font-size:.76rem;
  padding:7px 16px 7px 28px;color:var(--ink2);border-left:3px solid var(--muted);
  background:color-mix(in srgb, var(--chip) 55%, transparent);}}
.rv-row{{display:grid;grid-template-columns:1fr auto;gap:12px;align-items:start;
  padding:13px 16px;border-top:1px solid var(--grid);}}
.rv-row:first-child{{border-top:none;}}
.rv-title-line{{display:flex;align-items:center;gap:8px;flex-wrap:wrap;}}
.rv-rank-badge{{font-size:.68rem;font-weight:700;border-radius:10px;padding:2px 8px;white-space:nowrap;}}
.rv-rank-S{{background:color-mix(in srgb,var(--gold) 22%,transparent);color:var(--gold);}}
.rv-rank-A{{background:color-mix(in srgb,var(--blue) 16%,transparent);color:var(--blue);}}
.rv-rank-B{{background:var(--chip);color:var(--muted);}}
.rv-rank-P{{background:color-mix(in srgb,var(--blue) 10%,transparent);color:var(--ink2);}}
.rv-title{{font-weight:650;}}
a.rv-title{{color:inherit;text-decoration:none;cursor:pointer;}}
a.rv-title:hover{{text-decoration:underline;color:var(--blue);}}
.rv-summary{{font-size:.82rem;color:var(--ink2);margin-top:4px;}}
.rv-chips{{margin-top:8px;display:flex;flex-wrap:wrap;gap:6px;}}
.rv-chip{{font-size:.7rem;color:var(--ink2);background:var(--chip);border:1px solid var(--border);
  border-radius:20px;padding:2px 9px;white-space:nowrap;}}
.rv-c-tier1{{color:var(--gold);border-color:var(--gold);}}
.rv-c-quant{{color:var(--good-ink);border-color:var(--good);}}
.rv-c-manual{{color:var(--blue);border-color:var(--blue);}}
.rv-c-staff{{color:#8a5cd6;border-color:#8a5cd6;}}
.rv-c-person{{color:#2a9d8f;border-color:#2a9d8f;font-weight:600;}}
.rv-right{{display:flex;flex-direction:column;gap:6px;align-items:flex-end;}}
.rv-rank-select{{font-size:.7rem;color:var(--ink2);background:var(--chip);border:1px solid var(--border);
  border-radius:5px;padding:2px 4px;cursor:pointer;}}
.rv-hide-btn{{font-size:.7rem;border:1px solid var(--border);border-radius:12px;padding:3px 9px;
  background:var(--chip);color:var(--ink2);cursor:pointer;white-space:nowrap;}}
.rv-hide-btn:hover{{background:color-mix(in srgb,var(--critical,#d03b3b) 14%,transparent);}}
.rv-empty{{padding:24px;text-align:center;color:var(--muted);}}
.rv-add-box{{margin-top:24px;background:var(--surface);border:1px dashed var(--border);border-radius:12px;padding:14px 16px;}}
.rv-add-box summary{{cursor:pointer;font-weight:600;font-size:.85rem;color:var(--ink2);}}
.rv-add-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;margin-top:12px;}}
.rv-add-grid input, .rv-add-grid select, .rv-add-grid textarea{{width:100%;padding:6px 8px;
  border:1px solid var(--border);border-radius:6px;background:var(--page);color:var(--ink);font-size:.8rem;}}
.rv-add-grid textarea{{grid-column:1 / -1;min-height:60px;}}
.rv-add-goals{{grid-column:1 / -1;display:flex;gap:14px;font-size:.78rem;color:var(--ink2);}}
.rv-add-submit{{margin-top:10px;font-size:.8rem;font-weight:600;border:1px solid var(--blue);
  border-radius:20px;padding:6px 16px;background:var(--blue);color:#fff;cursor:pointer;}}
#reviewCopyArea{{width:100%;min-height:160px;margin-top:10px;font-size:.75rem;
  background:var(--surface);color:var(--ink);border:1px solid var(--border);border-radius:8px;padding:10px;display:none;}}
.footer-note{{font-size:.72rem;color:var(--muted);margin-top:18px;padding:12px 14px;
  background:var(--surface);border:1px dashed var(--border);border-radius:10px;}}
</style>
</head>
<body>
<div class="wrap">
  <div class="topbar">
    <h1>📈 四半期振り返り</h1>
    <span class="subtitle">{period_label_safe} ／ {generated_at} 生成</span>
    <span class="cost">{cost_display}</span>
  </div>

  <div class="rv-toolbar">
    <button id="viewBtnGoal" class="rv-toggle-btn active" onclick="reviewSetView('goal')">🎯 ゴール別</button>
    <button id="viewBtnProject" class="rv-toggle-btn" onclick="reviewSetView('project')">🗂️ プロジェクト別</button>
    <button id="viewBtnTimeline" class="rv-toggle-btn" onclick="reviewSetView('timeline')">🗓️ 月別タイムライン</button>
    <button id="rankFilterS" class="rv-rank-filter active" onclick="reviewToggleRank('S')">🅢 S ({rank_counts.get('S',0)})</button>
    <button id="rankFilterA" class="rv-rank-filter active" onclick="reviewToggleRank('A')">🅐 A ({rank_counts.get('A',0)})</button>
    <button id="rankFilterB" class="rv-rank-filter" onclick="reviewToggleRank('B')">🅑 B ({rank_counts.get('B',0)})</button>
    <button id="rankFilterP" class="rv-rank-filter" onclick="reviewToggleRank('P')">🔵 進行中 ({rank_counts.get('P',0)})</button>
    <button class="rv-copy-btn" onclick="reviewCopyText()">📋 コピー用テキストを生成</button>
  </div>

  <div id="view-goal" class="hero">{view_goal_html}</div>
  <div id="view-project" class="hero" style="display:none;">{view_project_html}</div>
  <div id="view-timeline" class="hero" style="display:none;">{view_timeline_html}</div>

  <textarea id="reviewCopyArea" readonly></textarea>

  <details class="rv-add-box">
    <summary>✍️ 実績を手動で追加(会議・口頭判断など、メールに残らないもの)</summary>
    <div class="rv-add-grid">
      <select id="raPerson" onchange="reviewRenderAddGoals()">{person_options_html}</select>
      <input id="raTitle" placeholder="タイトル(例: R19量産判定の最終承認)">
      <select id="raProject">{project_options_html}</select>
      <select id="raType">
        <option value="decision">⚖️判断・決裁</option>
        <option value="execution">🔨実行・完遂</option>
        <option value="systemize">🏗仕組み化</option>
        <option value="coordination">🤝調整・折衝</option>
        <option value="communication">📢発信・育成</option>
      </select>
      <select id="raRank">
        <option value="S">🅢 MAG Leader報告必須</option>
        <option value="A" selected>🅐 報告推奨</option>
        <option value="B">🅑 実績リスト</option>
        <option value="P">🔵 進行中</option>
      </select>
      <input id="raDate" type="date">
      <input id="raQuantNote" placeholder="定量効果(任意。例: 月4時間削減)">
      <div class="rv-add-goals" id="raGoalsBox"></div>
      <textarea id="raSummary" placeholder="要約(2〜3文)"></textarea>
    </div>
    <button class="rv-add-submit" onclick="reviewAddManual({self.server_port})">追加する</button>
    <div style="font-size:.72rem;color:var(--ink2);margin-top:8px;">
      ※ 追加後は画面に即時反映されません。「🎨 フォーマットのみ再生成」を実行すると表示されます。
    </div>
  </details>

  <details class="rv-add-box">
    <summary>🙈 非表示にした実績を確認・復元</summary>
    <div id="rv-hidden-list" style="margin-top:10px; font-size:.8rem; color:var(--ink2);">読み込み中...</div>
    <div style="font-size:.72rem;color:var(--ink2);margin-top:8px;">
      ※ 元に戻した実績が本体の一覧に再表示されるのは「🎨 フォーマットのみ再生成」実行後です。
    </div>
  </details>

  <div class="footer-note">
    メールで送信済みの活動、および登録スタッフ(部下)が送信し自分がTo/Ccで把握している活動が自動集計の対象です(それ以外の受信のみのスレッドは対象外)。
    Ochiさんのランクは「成果確定していなければ🔵進行中 → G1/G2/G3のいずれにも紐づかなければ🅑B → Tier1関与/部門横断2名以上/Japan Site全体/定量効果/スタッフの成果を牽引、のいずれかで🅢S、無ければ🅐A」の順で機械的に判定しています。
    合成スコアではないため、常にチップで根拠を確認できます。手動での判断とは異なる場合は🙈非表示・ランク変更で調整してください。<br>
    スタッフ(👤チップ付き)の実績は、委任アクセス・共有メールボックスが無いためOchiさんのメールボックス内で観測できた範囲(本人が送信、またはOchiさんが本人へ送信したスレッド)に限られます。
    ランクは「成果未確定なら🔵進行中 → 本人のゴール(KPI)に紐づかなければ🅑B → 紐づき、かつ定量効果またはJapan Site全体規模なら🅢S、それ以外は🅐A」の決定木で判定しています(Tier1/Tier2関与は対象外)。
    ゴール(KPI)の定義はjson/review_person_goals.jsonで管理しています。
  </div>
</div>
<script>
function reviewSetView(mode) {{
    document.getElementById('view-goal').style.display = (mode === 'goal') ? '' : 'none';
    document.getElementById('view-project').style.display = (mode === 'project') ? '' : 'none';
    document.getElementById('view-timeline').style.display = (mode === 'timeline') ? '' : 'none';
    document.getElementById('viewBtnGoal').classList.toggle('active', mode === 'goal');
    document.getElementById('viewBtnProject').classList.toggle('active', mode === 'project');
    document.getElementById('viewBtnTimeline').classList.toggle('active', mode === 'timeline');
}}
let reviewActiveRanks = new Set(['S', 'A']);
function reviewToggleRank(rank) {{
    if (reviewActiveRanks.has(rank)) reviewActiveRanks.delete(rank); else reviewActiveRanks.add(rank);
    document.getElementById('rankFilter' + rank).classList.toggle('active', reviewActiveRanks.has(rank));
    document.querySelectorAll('.rv-row').forEach(row => {{
        row.style.display = reviewActiveRanks.has(row.dataset.rank) ? '' : 'none';
    }});
    reviewRecomputeCounts();
}}
function reviewRecomputeCounts() {{
    document.querySelectorAll('.rv-goal-group, .rv-subcat-group').forEach(group => {{
        const visible = Array.from(group.querySelectorAll('.rv-row')).filter(r => r.style.display !== 'none').length;
        const countEl = group.querySelector(':scope > .rv-goal-head .rv-count, :scope > .rv-subcat-head .rv-count');
        if (countEl) countEl.textContent = visible + '件';
    }});
}}
document.querySelectorAll('.rv-row').forEach(row => {{
    row.style.display = reviewActiveRanks.has(row.dataset.rank) ? '' : 'none';
}});
reviewRecomputeCounts();

// 非表示は再読み込みしても保持されるべきなので、このページの生成時点より後に
// 非表示にされた実績が残っていれば、読み込み時にサーバーの最新状態(review_manual_items.json)
// へ問い合わせて改めて非表示を適用する。あわせて「元に戻す」パネルも同じ結果で描画する。
async function reviewLoadHiddenList(port) {{
    try {{
        const res = await fetch(`http://localhost:${{port}}/review_hidden_list`);
        const data = await res.json();
        const hiddenIds = new Set(data.hidden_ids || []);
        document.querySelectorAll('.rv-row').forEach(row => {{
            if (hiddenIds.has(row.dataset.aid)) row.style.display = 'none';
        }});
        reviewRecomputeCounts();
        renderReviewHiddenPanel(data.items || [], port);
    }} catch (e) {{ console.error(e); }}
}}
function renderReviewHiddenPanel(items, port) {{
    const box = document.getElementById('rv-hidden-list');
    if (!box) return;
    box.innerHTML = '';
    if (!items.length) {{
        const empty = document.createElement('span');
        empty.style.color = 'var(--muted)';
        empty.textContent = '非表示にした実績はありません。';
        box.appendChild(empty);
        return;
    }}
    items.forEach(it => {{
        const row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:center;gap:8px;padding:4px 0;';
        const badge = document.createElement('span');
        badge.className = 'rv-rank-badge rv-rank-' + it.rank;
        badge.textContent = it.rank;
        const title = document.createElement('span');
        title.style.flex = '1';
        title.textContent = it.title;
        const btn = document.createElement('button');
        btn.className = 'rv-hide-btn';
        btn.textContent = '↩️ 元に戻す';
        btn.onclick = () => reviewUnhide(it.achievement_id, port, row, btn);
        row.appendChild(badge); row.appendChild(title); row.appendChild(btn);
        box.appendChild(row);
    }});
}}
async function reviewUnhide(aid, port, rowEl, btn) {{
    btn.disabled = true;
    try {{
        await fetch(`http://localhost:${{port}}/update_review_manual`, {{
            method: 'POST', headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{action: 'unhide', achievement_id: aid}})
        }});
    }} catch (e) {{ console.error(e); }}
    if (rowEl) rowEl.remove();
    alert('元に戻しました。本体の一覧に反映するには「🎨 フォーマットのみ再生成」を実行してください。');
}}
reviewLoadHiddenList({self.server_port});

async function reviewHide(btn, aid, port) {{
    btn.disabled = true;
    try {{
        await fetch(`http://localhost:${{port}}/update_review_manual`, {{
            method: 'POST', headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{action: 'hide', achievement_id: aid}})
        }});
    }} catch (e) {{ console.error(e); }}
    document.querySelectorAll(`.rv-row[data-aid="${{CSS.escape(aid)}}"]`).forEach(row => {{ row.style.display = 'none'; }});
    reviewRecomputeCounts();
}}
async function reviewSetRank(select, aid, port) {{
    const newRank = select.value;
    try {{
        await fetch(`http://localhost:${{port}}/update_review_manual`, {{
            method: 'POST', headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{action: 'set_rank', achievement_id: aid, rank: newRank}})
        }});
    }} catch (e) {{ console.error(e); }}
    document.querySelectorAll(`.rv-row[data-aid="${{CSS.escape(aid)}}"]`).forEach(row => {{
        row.dataset.rank = newRank;
        row.style.display = reviewActiveRanks.has(newRank) ? '' : 'none';
        const badge = row.querySelector('.rv-rank-badge');
        if (badge) {{
            badge.className = 'rv-rank-badge rv-rank-' + newRank;
            badge.textContent = select.options[select.selectedIndex].text;
        }}
        const sel = row.querySelector('.rv-rank-select');
        if (sel && sel !== select) sel.value = newRank;
    }});
    reviewRecomputeCounts();
}}
// 対象者ごとにゴール(KPI)キー体系が異なる(Ochi=G1/G2/G3固定、スタッフ=K1..等)ため、
// json/review_person_goals.jsonの定義(サーバー側で埋め込み済み)から、選択中の対象者の
// ゴールチェックボックスをJS側で動的に構築する。
const REVIEW_PERSON_GOALS = {person_goals_json};
function reviewRenderAddGoals() {{
    const person = document.getElementById('raPerson').value;
    const box = document.getElementById('raGoalsBox');
    const goals = REVIEW_PERSON_GOALS[person] || [];
    box.innerHTML = '';
    if (!goals.length) {{
        const note = document.createElement('span');
        note.style.color = 'var(--muted)';
        note.textContent = 'この対象者のゴールは未登録です(json/review_person_goals.jsonへ追記してください)。';
        box.appendChild(note);
        return;
    }}
    goals.forEach(([key, label]) => {{
        const lab = document.createElement('label');
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.className = 'ra-goal-cb';
        cb.value = key;
        lab.appendChild(cb);
        lab.appendChild(document.createTextNode(' ' + label));
        box.appendChild(lab);
    }});
}}
reviewRenderAddGoals();

async function reviewAddManual(port) {{
    const goalKeys = Array.from(document.querySelectorAll('#raGoalsBox .ra-goal-cb:checked')).map(cb => cb.value);
    const payload = {{
        action: 'add',
        person: document.getElementById('raPerson').value || 'Ochi',
        title: document.getElementById('raTitle').value || '(無題)',
        summary: document.getElementById('raSummary').value || '',
        project_key: document.getElementById('raProject').value,
        activity_type: document.getElementById('raType').value,
        rank: document.getElementById('raRank').value,
        completed_date: document.getElementById('raDate').value || '',
        goal_keys: goalKeys,
        has_quantitative_effect: !!document.getElementById('raQuantNote').value,
        quantitative_note: document.getElementById('raQuantNote').value || '',
    }};
    try {{
        await fetch(`http://localhost:${{port}}/update_review_manual`, {{
            method: 'POST', headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify(payload)
        }});
        alert('追加しました。「🎨 フォーマットのみ再生成」を実行すると画面に反映されます。');
    }} catch (e) {{ console.error(e); alert('追加に失敗しました: ' + e); }}
}}
function reviewCopyText() {{
    let activeViewId = document.getElementById('view-goal').style.display !== 'none' ? 'view-goal'
        : (document.getElementById('view-project').style.display !== 'none' ? 'view-project' : 'view-timeline');
    const container = document.getElementById(activeViewId);
    let lines = [];
    container.querySelectorAll('.rv-goal-group, .rv-subcat-group').forEach(group => {{
        const headEl = group.querySelector(':scope > .rv-goal-head, :scope > .rv-subcat-head');
        const rows = Array.from(group.querySelectorAll(':scope > .rv-goal-rows > .rv-row, :scope > .rv-subcat-rows > .rv-row'))
            .filter(r => r.style.display !== 'none');
        if (!rows.length) return;
        if (headEl) lines.push('## ' + headEl.childNodes[0].textContent.trim());
        rows.forEach(row => {{
            const title = row.querySelector('.rv-title').textContent.trim();
            const rankBadge = row.querySelector('.rv-rank-badge').textContent.trim();
            const summary = row.querySelector('.rv-summary').textContent.trim();
            const person = row.dataset.person || 'Ochi';
            // 複数人物が混在しうるため、Ochiさん以外の実績には誰の実績か行頭に前置する
            // (人物名が無いと、コピー先で誰の実績か分からないテキストになってしまうため)。
            const personPrefix = (person !== 'Ochi') ? `[${{person}}] ` : '';
            lines.push(`- ${{personPrefix}}[${{rankBadge}}] ${{title}}\\n  ${{summary}}`);
        }});
        lines.push('');
    }});
    const text = lines.join('\\n');
    const area = document.getElementById('reviewCopyArea');
    area.style.display = 'block';
    area.value = text;
    area.select();
    try {{ navigator.clipboard.writeText(text); }} catch (e) {{ /* クリップボードAPI不可の場合はテキストエリアから手動コピー */ }}
}}
</script>
</body>
</html>"""

            with open(path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            return str(path)
        except Exception as e:
            print(f"Review Report Error: {e}")
            return ""

    def generate_action_dashboard_report(self, action_cards, date_range, total_input, total_output, reformat_mode=False, search_days: int = 7) -> str:
        """
        アクションダッシュボード: 期間×自分宛て全体から抽出したアクション項目を、
        1スレッド=1カード(複数アクションがあれば束ねて表示)として一覧表示する。
        進捗(4択)・優先度(3択)・コメントはアクション単位でワンクリック/入力でその場保存され、
        完了/無視はデフォルトで非表示になる。R19Projタグ付きスレッドは専用フィルタで絞り込める。
        action_cardsには、今回実際にOutlookから取得した期間のスレッドだけでなく、過去の
        どこかの回で分析されキャッシュされている全スレッド(summarize_action_dashboardを
        expand_from_cache=Trueで呼んだ結果)が含まれる。ヘッダーの「表示期間」プルダウンは
        新たなOutlook取得・AI再解析を行わず、ブラウザ側のJS(applyActionFilters)だけで
        各カードのdata-ts(最終更新のタイムスタンプ)を基準に表示・非表示を切り替える。
        既定の選択値はsearch_days(今回実際にOutlookへ問い合わせた日数)以上をカバーする
        最小の選択肢にし、生成直後の見え方が従来と変わらないようにする(過去に放置されている
        アイテムを見るには、ユーザーが明示的にプルダウンを広げる必要がある)。
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
            # アクション行内の進捗/優先度ボタンは1行に収めるため短縮ラベルを使う
            # (フィルタバー・状態チップは上のフルラベルのまま使う)。
            PROGRESS_LABELS_SHORT = {"not_started": "未着", "in_progress": "進行", "done": "完了", "ignored": "無視"}
            PRIORITY_LABELS_SHORT = {"": "ー", "high": "★", "top": "★★"}
            priority_rank = {"top": 2, "high": 1, "": 0}

            def card_sort_key(card):
                prios = [priority_rank.get(a.get("priority", ""), 0) for a in card.get("actions", [])]
                max_prio = max(prios) if prios else 0
                has_deadline = any((a.get("deadline") or "").strip() for a in card.get("actions", []))
                return (-max_prio, 0 if has_deadline else 1, -card.get("latest_ts", 0))

            # 並び順(初期表示): カード内の最大優先度(★★→★→空欄) → 締切の有無 → スレッド最終更新の新しい順
            sorted_cards = sorted(action_cards, key=card_sort_key)

            # ヘッダーの「表示期間」プルダウン: 新たなOutlook取得・AI再解析を行わず、
            # ブラウザ側のJSだけでカードのdata-tsを基準に表示・非表示を切り替える
            # (action_cards自体は既にexpand_from_cache=Trueでキャッシュ全体から作られている)。
            # 既定の選択値は、今回実際にOutlookへ問い合わせた日数(search_days)以上を
            # カバーする最小の選択肢にし、生成直後の見え方が従来と変わらないようにする。
            AGE_FILTER_OPTIONS = [(7, "1週間"), (14, "2週間"), (21, "3週間"), (30, "1ヶ月"),
                                   (60, "2ヶ月"), (90, "3ヶ月"), (180, "6ヶ月"), (0, "全期間")]
            default_age_days = next((d for d, _ in AGE_FILTER_OPTIONS if d != 0 and d >= (search_days or 0)), 0)
            age_options_html = "".join(
                f'<option value="{d}"{" selected" if d == default_age_days else ""}>{html_mod.escape(label)}</option>'
                for d, label in AGE_FILTER_OPTIONS
            )

            cards_html = []
            for card in sorted_cards:
                cid = card.get("conversation_id", "")
                topic_safe = html_mod.escape(card.get("topic", ""))
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
                # タイトルクリックで「Outlookでこのスレッドを検索」を開く。旧「🚀 Outlook」ボタンは
                # このリンクと機能が完全に重複していたため削除し、タイトル自体のリンクに一本化した。
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
                first_action_progress = ""
                for idx, a in enumerate(card.get("actions", [])):
                    key = a["action_key"]
                    progress = a.get("progress", "not_started")
                    priority = a.get("priority", "")
                    comment = a.get("comment", "")
                    progresses_seen.add(progress)
                    priorities_seen.add(priority)
                    if idx == 0:
                        first_action_progress = progress

                    owner_safe = html_mod.escape(a.get("owner", "") or "(不明)")
                    target_safe = html_mod.escape(a.get("target", "") or "あなた")
                    action_safe = html_mod.escape(a.get("action", ""))
                    deadline_safe = html_mod.escape(a.get("deadline", ""))
                    comment_safe = html_mod.escape(comment, quote=True)
                    deadline_html = f'<span class="action-deadline">📅 {deadline_safe}</span>' if deadline_safe else ''

                    # 進捗4ボタン＋優先度3ボタンは短縮ラベルで1行(.status-btns)にまとめる。
                    # クラス名(prog-btn/prio-btn)・onclickは既存のsetActionProgress/setActionPriorityを
                    # そのまま流用するため変更しない。
                    prog_btns = "".join(
                        f'<button data-val="{val}" class="prog-btn{" active" if progress == val else ""}" '
                        f'onclick="setActionProgress(this, \'{key}\', \'{val}\', {self.server_port})">{label}</button>'
                        for val, label in PROGRESS_LABELS_SHORT.items()
                    )
                    prio_btns = "".join(
                        f'<button data-val="{val}" class="prio-btn{" active" if priority == val else ""}" '
                        f'onclick="setActionPriority(this, \'{key}\', \'{val}\', {self.server_port})">{label}</button>'
                        for val, label in PRIORITY_LABELS_SHORT.items()
                    )

                    # コメント欄はアコーディオンで開閉する。初期状態は常に閉じておき(display:none)、
                    # トグルボタンの記号と色だけで「開けばコメントが入っているかどうか」がわかるようにする:
                    # 塗り▼(閉/開く)▲(開/閉じる)=コメントあり(濃色)、白抜き▽(閉/開く)△(開/閉じる)=コメントなし(淡色)。
                    # コメント欄自体(input)の背景は常に白のまま変更しない。
                    has_comment = bool(comment.strip())
                    comment_toggle_symbol = "▼" if has_comment else "▽"
                    comment_toggle_cls = "comment-toggle-btn has-comment" if has_comment else "comment-toggle-btn"

                    # 1アクション=1行(コメント欄を閉じている間): トグル+誰から→誰へ(左、長ければ2行まで折返し)、
                    # 進捗/優先度の統合ボタン(右、.status-btnsはflex-shrink:0で折り返さない)。
                    items_html.append(f'''
                    <div class="action-item" data-key="{key}" data-progress="{progress}" data-priority="{priority}" data-has-comment="{"true" if has_comment else "false"}">
                        <div class="action-item-row">
                            <button type="button" class="{comment_toggle_cls}" onclick="toggleActionComment(this)" title="コメント欄の表示/非表示">{comment_toggle_symbol}</button>
                            <div class="action-item-detail"><b>{owner_safe}</b> → <b>{target_safe}</b>: {action_safe} {deadline_html}</div>
                            <div class="status-btns">
                                {prog_btns}
                                <div class="status-divider"></div>
                                {prio_btns}
                            </div>
                        </div>
                        <div class="action-comment-row" style="display:none;">
                            <input type="text" class="action-comment" value="{comment_safe}" placeholder="コメント（進行中の状況メモなど）"
                                   onblur="updateActionComment(this, '{key}', {self.server_port})">
                        </div>
                    </div>''')

                progresses_attr = ",".join(sorted(progresses_seen))
                priorities_attr = ",".join(sorted(priorities_seen))

                # 件名の横に表示する状態チップ(非インタラクティブ、表示専用)。初期値は1件目の進捗を
                # サーバー側でレンダリングしておき、ページ読み込み時にJS(applyActionFilters)が
                # 「現在のフィルタで残っている最上位のアクション」の進捗に基づいて即座に補正する。
                status_chip_label = html_mod.escape(PROGRESS_LABELS.get(first_action_progress, first_action_progress))

                # 外側(.action-card)=未読既読バー(8px、重要度の2倍太さ)＋絞り込み・並び替え用のカード集約データ属性。
                # 内側(.card-inner)=重要度バー(4px)。ヘッダー行(タイトル行)にカテゴリ/R19Projマーク/タイトル/
                # フラグ/受信日時/状態チップを1行にまとめる(flex-wrap:nowrap、タイトル文字列側が縮んで
                # 吸収するため折り返さない)。進捗の実際の変更は各アクション行の統合ボタンから行う。
                cards_html.append(f'''
                <div class="action-card js-action" data-key="{cid}" data-ts="{latest_ts}" data-unread="{unread_flag}" data-r19="{r19_flag}" data-progresses="{progresses_attr}" data-priorities="{priorities_attr}">
                    <div class="card-inner" style="border-left:4px solid {badge_col};">
                        <div class="card-header">
                            <span class="action-r19-wrap">{r19_badge}</span>
                            {topic_html}
                            <span class="action-flag-wrap">{flag_badge}</span>
                            <span class="action-date">{date_safe}</span>
                            <span class="status-chip" data-progress="{first_action_progress}">{status_chip_label}</span>
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
                .bg-r19 {{ background:#7c3aed; }}
                .bg-flag {{ background:#fef2f2; border:1px solid #fecaca; }}
                .action-card {{ border-left:8px solid #cbd5e1; border-radius:6px; margin-bottom:10px; box-shadow:0 1px 3px rgba(0,0,0,0.08); overflow:hidden; }}
                .action-card[data-unread="true"] {{ border-left-color:#2563eb; }}
                .card-inner {{ background:#fff; }}
                .card-header {{ display:flex; align-items:center; gap:8px; padding:14px 16px 10px; flex-wrap:nowrap; }}
                .action-r19-wrap {{ display:inline-block; width:88px; flex-shrink:0; }}
                .action-topic-text {{ flex:1 1 auto; min-width:40px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-weight:bold; font-size:1.02em; color:#1e293b; text-decoration:none; cursor:pointer; }}
                a.action-topic-text:hover {{ text-decoration:underline; color:#2563eb; }}
                .action-flag-wrap {{ display:inline-block; flex-shrink:0; }}
                .action-date {{ flex-shrink:0; font-size:0.8em; color:#94a3b8; white-space:nowrap; font-weight:normal; margin-right:4px; }}
                /* 件名横の状態チップ: フィルタで残っている最上位のアクションの進捗を表す表示専用ラベル(非インタラクティブ) */
                .status-chip {{ flex-shrink:0; font-size:0.76em; font-weight:bold; padding:3px 11px; border-radius:12px; white-space:nowrap; }}
                .status-chip[data-progress="not_started"] {{ background:#f1f5f9; color:#64748b; }}
                .status-chip[data-progress="in_progress"] {{ background:var(--primary); color:#fff; }}
                .status-chip[data-progress="done"] {{ background:#dcfce7; color:#15803d; }}
                .status-chip[data-progress="ignored"] {{ background:#f1f5f9; color:#94a3b8; text-decoration:line-through; }}
                /* 1アクション=1行(コメント欄を閉じている間)。誰から→誰へのテキストは長ければ2行まで折り返すが、
                   右側の統合ボタン(.status-btns)はflex-shrink:0のため折り返さず常に同じ行にとどまる。 */
                .action-item {{ padding:8px 16px 12px; border-top:1px dashed #e2e8f0; }}
                .action-item:first-of-type {{ border-top:1px solid #e2e8f0; }}
                .action-item-row {{ display:flex; align-items:flex-start; gap:8px; }}
                .comment-toggle-btn {{ flex-shrink:0; border:none; background:none; cursor:pointer; font-size:0.95em; line-height:1.6; color:#94a3b8; padding:0 2px; }}
                .comment-toggle-btn:hover {{ color:#2563eb; }}
                /* コメントが既にある場合(has-comment)は、記号を濃色にして一目で分かるようにする。
                   コメント欄自体(.action-comment)の背景は常に白のままで、ここでは変更しない。 */
                .comment-toggle-btn.has-comment {{ color:#0f172a; font-weight:bold; }}
                .comment-toggle-btn.has-comment:hover {{ color:#2563eb; }}
                .action-item-detail {{ flex:1 1 auto; min-width:0; font-size:0.95em; color:#334155; white-space:normal; overflow-wrap:break-word; line-height:1.6; }}
                .action-deadline {{ margin-left:8px; font-size:0.85em; color:#b45309; }}
                .action-comment-row {{ display:flex; margin-left:22px; margin-top:6px; }}
                .action-comment {{ width:100%; box-sizing:border-box; padding:6px 8px; border:1px solid #cbd5e1; border-radius:4px; font-size:0.9em; background:#fff; }}
                .status-btns {{ display:flex; align-items:center; gap:3px; flex-shrink:0; flex-wrap:nowrap; }}
                .status-divider {{ width:1px; height:16px; background:#e2e8f0; margin:0 3px; flex-shrink:0; }}
                .prog-btn, .prio-btn {{ padding:4px 8px; border:1px solid #cbd5e1; background:#fff; border-radius:10px; cursor:pointer; font-size:0.76em; color:#475569; min-width:30px; }}
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
                            <span class="filter-label">コメント欄:</span>
                            <button class="filter-btn" onclick="setAllComments(true)">▼ 全て表示</button>
                            <button class="filter-btn" onclick="setAllComments(false)">▲ 全て閉じる</button>
                        </div>
                        <div class="filter-group">
                            <label for="actionAgeFilter" class="filter-label">表示期間:</label>
                            <select id="actionAgeFilter" onchange="applyActionFilters()">
                                {age_options_html}
                            </select>
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
                const item = input.closest('.action-item');
                item.dataset.hasComment = input.value.trim().length > 0 ? 'true' : 'false';
                const btn = item.querySelector('.comment-toggle-btn');
                const row = item.querySelector('.action-comment-row');
                if (btn && row) {{
                    updateCommentToggleSymbol(item, btn, row.style.display !== 'none');
                }}
            }}
            function updateCommentToggleSymbol(item, btn, isOpen) {{
                const hasComment = item.dataset.hasComment === 'true';
                btn.classList.toggle('has-comment', hasComment);
                if (hasComment) {{
                    btn.textContent = isOpen ? '▲' : '▼';
                }} else {{
                    btn.textContent = isOpen ? '△' : '▽';
                }}
            }}
            function toggleActionComment(btn) {{
                const item = btn.closest('.action-item');
                const row = item.querySelector('.action-comment-row');
                const isHidden = (row.style.display === 'none' || row.style.display === '');
                row.style.display = isHidden ? 'flex' : 'none';
                updateCommentToggleSymbol(item, btn, isHidden);
            }}
            function setAllComments(open) {{
                document.querySelectorAll('.action-item').forEach(item => {{
                    const row = item.querySelector('.action-comment-row');
                    const btn = item.querySelector('.comment-toggle-btn');
                    if (!row || !btn) return;
                    row.style.display = open ? 'flex' : 'none';
                    updateCommentToggleSymbol(item, btn, open);
                }});
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
            const PROGRESS_LABELS_JS = {{not_started:'未着手', in_progress:'進行中', done:'完了', ignored:'無視'}};
            function applyActionFilters() {{
                const activeProgress = Array.from(document.querySelectorAll('.filter-progress.active')).map(b => b.dataset.val);
                const activePriority = Array.from(document.querySelectorAll('.filter-priority.active')).map(b => b.dataset.val);
                // 表示期間: 新たなOutlook取得・AI再解析は行わず、各カードが既に持つdata-ts
                // (最終更新のタイムスタンプ)をブラウザの現在時刻と比較するだけの表示切り替え。
                // "0"(全期間)を選ぶと、期間による絞り込みを行わない。
                const ageDaysEl = document.getElementById('actionAgeFilter');
                const ageDays = ageDaysEl ? parseInt(ageDaysEl.value, 10) : 0;
                const ageThresholdTs = ageDays > 0 ? Math.floor(Date.now() / 1000) - ageDays * 86400 : null;
                const allCards = document.querySelectorAll('.js-action');
                let visibleCardCount = 0;
                let visibleItemCount = 0;
                let totalItemCount = 0;
                allCards.forEach(card => {{
                    const r19Match = r19FilterMode === 'all' ? true
                        : r19FilterMode === 'only' ? (card.dataset.r19 === 'true')
                        : (card.dataset.r19 !== 'true');
                    const ageMatch = ageThresholdTs === null || parseInt(card.dataset.ts, 10) >= ageThresholdTs;
                    let anyItemVisible = false;
                    let topmostVisible = null;
                    card.querySelectorAll('.action-item').forEach(item => {{
                        totalItemCount++;
                        const itemMatch = r19Match
                            && ageMatch
                            && activeProgress.includes(item.dataset.progress)
                            && activePriority.includes(item.dataset.priority);
                        item.style.display = itemMatch ? '' : 'none';
                        if (itemMatch) {{
                            anyItemVisible = true; visibleItemCount++;
                            if (!topmostVisible) topmostVisible = item;
                        }}
                    }});
                    // 件名横の状態チップは、現在のフィルタで残っている最上位(一番上)のアクションの
                    // 進捗を表示する。該当アクションが1件も無ければ(カード自体が非表示になるため)隠す。
                    const chip = card.querySelector('.status-chip');
                    if (chip) {{
                        if (topmostVisible) {{
                            const p = topmostVisible.dataset.progress;
                            chip.dataset.progress = p;
                            chip.textContent = PROGRESS_LABELS_JS[p] || p;
                            chip.style.display = '';
                        }} else {{
                            chip.style.display = 'none';
                        }}
                    }}
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
    # 本ツールとOutlookの間に、デスクトップが少しだけ覗く隙間を残すための余白(px)。
    WINDOW_SPLIT_GAP = 12

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("📧 Outlook メールマネージャー v4.0")

        # 起動時にメイン画面を左右半分に分割し、左半分に本ツール・右半分にOutlookを
        # 配置する。タスクバーの分だけウィンドウ下部が隠れないよう、画面全体では
        # なくタスクバーを除いた作業領域(work area)を基準にする。Outlook側の
        # 起動・COM操作(起動していなければ起動を含む)は時間がかかりうるため、
        # 本ウィンドウの表示を妨げないようワーカースレッドで行う。
        work_area = get_primary_work_area()
        if work_area:
            wa_left, wa_top, wa_right, wa_bottom = work_area
        else:
            wa_left, wa_top = 0, 0
            wa_right, wa_bottom = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        wa_width = wa_right - wa_left
        wa_height = wa_bottom - wa_top

        half_w = wa_width // 2
        gap = self.WINDOW_SPLIT_GAP
        left_w = half_w - gap // 2
        outlook_left = wa_left + half_w + (gap - gap // 2)
        outlook_width = wa_right - outlook_left
        fit_window_to_work_area(self.root, left_w, wa_height, wa_left, wa_top)
        print(f"🖥 画面配置: work_area(取得={'成功' if work_area else '失敗→画面全体を使用'})="
              f"({wa_left},{wa_top})-({wa_right},{wa_bottom}) / "
              f"本ツール=x:{wa_left} w:{left_w} h:{wa_height} / "
              f"Outlook=x:{outlook_left} w:{outlook_width} h:{wa_height}")

        self.config = load_config()
        self.excluded_domains = load_excluded_domains()
        self.project_knowledge = load_project_knowledge()

        self.server_port = start_local_server()
        self.outlook = OutlookMailManager()
        self.summarizer = MailSummarizer(self.config['gemini_api_key'], self.config['gemini_model'])
        self.reporter = HTMLReportGenerator(self.config['output_folder'], self.server_port)

        threading.Thread(
            target=self.outlook.arrange_outlook_window,
            args=(outlook_left, wa_top, outlook_width, wa_height),
            daemon=True,
        ).start()

        # Gemini APIへの直接呼び出しが遮断状態から復活したら、その日の初回に限り
        # ポップアップでお知らせする。AI呼び出しはワーカースレッドから行われるため、
        # root.after()でメインスレッドへ処理を戻してからウィンドウを作る。
        set_gemini_direct_restored_callback(
            lambda: self.root.after(0, self._show_gemini_direct_restored_popup)
        )

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
        self.tab_review = ttk.Frame(self.notebook)

        self.notebook.add(self.tab_search, text="🔍 検索 / 整理")
        self.notebook.add(self.tab_project, text="📊 プロジェクト俯瞰")
        self.notebook.add(self.tab_staff, text="👤 スタッフ俯瞰")
        self.notebook.add(self.tab_cockpit, text="🚀 統括コックピット") # 追加
        self.notebook.add(self.tab_action, text="📋 アクション") # 追加(アクションダッシュボード)
        self.notebook.add(self.tab_review, text="📈 振り返り") # 追加(四半期パフォーマンスレビュー)

        self._ui_search_tab()
        self._ui_project_tab()
        self._ui_staff_tab()
        self._ui_cockpit_tab() # 追加
        self._ui_action_tab() # 追加(アクションダッシュボード)
        self._ui_review_tab() # 追加(振り返りタブ)
        
        self.lbl_stat = ttk.Label(self.root, text="Ready", relief="sunken", padding=2)
        self.lbl_stat.pack(side=tk.BOTTOM, fill=tk.X)

        if self.outlook.connect():
            self.lbl_stat.config(text=f"Ready (User: {self.outlook.user_name})")
        
        # 認証情報は環境変数(GEMINI_API_KEY / GEMINI_PROXY_URL)へ移行済み。
        # GUI設定のAPIキーが空でも、環境変数が設定されていれば警告しない。
        if not gemini_credentials_available():
            messagebox.showwarning(
                "!",
                "Gemini APIの認証情報が見つかりません。\n"
                "環境変数 GEMINI_API_KEY と GEMINI_PROXY_URL を設定してから、\n"
                "コマンドプロンプトを開き直して起動してください。"
            )
            
        self._load_cats()
        self._check_open_queue()

    def _set_status(self, text, start_timer=False, current=0, total=0):
        """current/totalを指定すると、「進行中どれぐらいか」が分かるよう
        "[現在/合計 (割合%)] メッセージ" の形でステータスバーに表示する
        (totalが0の場合は従来通りメッセージのみ表示、後方互換)。
        進捗表示の"(割合%)"自体に " (" が含まれるようになったため、_update_timer側の
        「経過秒数を付け足す前のベーステキスト」を文字列パース(旧: 表示中テキストを
        " (" で分割)ではなく、ここで確定した値をself._status_base_textに保存する
        方式に変更した(進捗表示の括弧と経過秒数表示の括弧が混同されるのを防ぐため)。"""
        if total and total > 0:
            pct = int(current / total * 100)
            text = f"[{current}/{total} ({pct}%)] {text}"
        self._status_base_text = text
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
        base_text = getattr(self, "_status_base_text", self.lbl_stat.cget("text"))
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

        _v2_reformat_init_state = tk.NORMAL if os.path.exists(COCKPIT_V2_LAST_RESULT_FILE) else tk.DISABLED
        self.btn_reformat_cockpit_v2 = ttk.Button(
            v2_f, text="🎨 フォーマットのみ再生成",
            command=self._reformat_cockpit_v2,
            state=_v2_reformat_init_state
        )
        self.btn_reformat_cockpit_v2.pack(side=tk.LEFT, padx=(5, 0))

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
                    progress_callback=lambda c, t, msg: self.root.after(0, lambda: self._set_status(msg, current=c, total=t))
                )
                total_input = self.summarizer.total_input_tokens
                total_output = self.summarizer.total_output_tokens
                path = self.reporter.generate_cockpit_v2_report(
                    cockpit_data, total_input, total_output
                )
                self._save_cockpit_v2_result(cockpit_data, total_input, total_output)
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

    def _save_cockpit_v2_result(self, cockpit_data, total_input, total_output):
        """統括コックピットv2の生成結果を保存し、次回以降「フォーマットのみ再生成」で
        メール再取得・AI再解析なしにHTMLだけを作り直せるようにする。"""
        try:
            with open(COCKPIT_V2_LAST_RESULT_FILE, 'w', encoding='utf-8') as jf:
                json.dump({
                    "cockpit_data": cockpit_data,
                    "total_input": total_input,
                    "total_output": total_output
                }, jf, ensure_ascii=False)
            self.root.after(0, lambda: self.btn_reformat_cockpit_v2.config(state=tk.NORMAL))
        except Exception as save_err:
            print(f"⚠️ cockpit_v2_last_result.json 保存失敗（HTML生成は継続）: {save_err}")

    def _reformat_cockpit_v2(self):
        """フォーマットのみ再生成: 保存済みデータからHTML再生成（メール再取得・AI再解析なし）。
        保存時点のqueueのうち、以下2つの最新値を反映してから描画する(いずれもメール再取得なしで
        キューに反映するため):
        1. cockpit_v2_acknowledged.json:「✅ 確認済み」にした案件(スレッドのメール件数が
           保存時から変わっていないもの)を除外する。コックピットv2の主な閉じ方。
        2. action_status.json: Actionタブ側で全アクションを完了/無視にした案件も除外する
           (action_status.jsonの更新自体はコックピットv2からは行わないが、Actionタブ側の
           変更をこちらにも反映するための補助的な判定として残す)。
        また、カード上のプロジェクト再分類UI(cockpit_v2_project_overrides.json)の
        変更も最新値で反映し直す。"""
        import tkinter.messagebox as messagebox

        if not os.path.exists(COCKPIT_V2_LAST_RESULT_FILE):
            messagebox.showerror("エラー", "保存済みデータがありません。\n先に「🎯 統括コックピット v2」を生成してください。")
            return

        self.btn_reformat_cockpit_v2.config(state=tk.DISABLED, text="⏳ フォーマット再生成中...")
        self._set_status("🎨 フォーマットのみ再生成中...", start_timer=True)

        def task():
            try:
                with open(COCKPIT_V2_LAST_RESULT_FILE, 'r', encoding='utf-8') as jf:
                    saved = json.load(jf)
                cockpit_data = saved.get("cockpit_data", {})
                total_input = saved.get("total_input", 0)
                total_output = saved.get("total_output", 0)

                action_statuses = load_action_status()
                project_overrides = load_cockpit_v2_project_overrides()
                acknowledged = load_cockpit_v2_acknowledged()

                def _still_open(item):
                    cid = item.get("conversation_id")
                    ack = acknowledged.get(cid)
                    if ack and ack.get("mail_count") == item.get("mail_count"):
                        return False
                    keys = item.get("action_keys", [])
                    if not keys:
                        return True
                    return any(
                        action_statuses.get(k, {}).get("progress") not in ("done", "ignored")
                        for k in keys
                    )

                queue = cockpit_data.get("queue", [])
                for item in queue:
                    cid = item.get("conversation_id")
                    if cid in project_overrides:
                        item["project"] = project_overrides[cid]
                cockpit_data["queue"] = [item for item in queue if _still_open(item)]

                path = self.reporter.generate_cockpit_v2_report(
                    cockpit_data, total_input, total_output, reformat_mode=True
                )
                if path:
                    import webbrowser
                    webbrowser.open(path)
            except Exception as e:
                _err = str(e)
                self.root.after(0, lambda: messagebox.showerror("エラー", f"フォーマット再生成に失敗しました:\n{_err}"))
            finally:
                self.root.after(0, lambda: self.btn_reformat_cockpit_v2.config(
                    state=tk.NORMAL, text="🎨 フォーマットのみ再生成"
                ))
                self.root.after(0, lambda: self._set_status("✅ フォーマット再生成完了", start_timer=False))

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

    def _save_action_dashboard_result(self, res, date_range, total_input, total_output, search_days: int = 7):
        try:
            with open(ACTION_DASHBOARD_LAST_RESULT_FILE, 'w', encoding='utf-8') as jf:
                json.dump({
                    "action_cards": res.get("action_cards", []),
                    "date_range": date_range,
                    "total_input": total_input,
                    "total_output": total_output,
                    "search_days": search_days
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
                    days, progress_callback=lambda c, t, msg: self.root.after(0, lambda: self._set_status(msg, current=c, total=t))
                )
                threads = self.outlook.group_by_thread(mails)
                res = self.summarizer.summarize_action_dashboard(
                    threads,
                    progress_callback=lambda c, t, msg: self.root.after(0, lambda: self._set_status(msg, current=c, total=t)),
                    reset_conversation_ids=reset_conv_ids,
                    expand_from_cache=True
                )
                date_range = f"対象期間: {self.v_action_prd.get()} / 自分宛て(To/With/Cc)全メール"
                path = self.reporter.generate_action_dashboard_report(
                    res.get("action_cards", []), date_range,
                    self.summarizer.total_input_tokens, self.summarizer.total_output_tokens,
                    search_days=days
                )
                self._save_action_dashboard_result(
                    res, date_range, self.summarizer.total_input_tokens, self.summarizer.total_output_tokens,
                    search_days=days
                )
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
                search_days  = saved.get("search_days", 7)

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
                    action_cards, date_range, total_input, total_output, reformat_mode=True,
                    search_days=search_days
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

    def _ui_review_tab(self):
        """第6のタブ: 振り返り(四半期パフォーマンスレビュー用エグゼクティブサマリー)。
        既存タブが「受信メールへの対応」を扱うのに対し、ここだけは自分が送信したメール
        (=実行した・判断したこと)を主データ源にする点が根本的に異なる。
        対象期間は「直近Nか月」ではなく、月ごとのチェックボックス(当年1月〜当月)で選ぶ。
        チェックが付いている月だけメール再取得・AI再分析を行い、外れている月は
        既存のanalysis_cache/review_monthly/配下のキャッシュをそのまま使う(一部の月だけ
        AI呼び出しが失敗した場合に、その月だけチェックして再試行できるようにするため)。"""
        main = ttk.Frame(self.tab_review, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        top_f = ttk.Frame(main)
        top_f.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(top_f, text="対象月:").pack(side=tk.LEFT, padx=(0, 5))

        self.v_review_month_vars = {}  # "YYYYMM" -> tk.BooleanVar
        now = datetime.now()
        review_months_ui = [(now.year, m) for m in range(1, now.month + 1)]

        self.v_review_all = tk.BooleanVar(value=True)

        def _on_all_toggle():
            checked = self.v_review_all.get()
            for var in self.v_review_month_vars.values():
                var.set(checked)

        ttk.Checkbutton(
            top_f, text="全て", variable=self.v_review_all, command=_on_all_toggle
        ).pack(side=tk.LEFT, padx=(0, 8))

        for (y, m) in review_months_ui:
            yyyymm = f"{y:04d}{m:02d}"
            var = tk.BooleanVar(value=True)
            self.v_review_month_vars[yyyymm] = var
            ttk.Checkbutton(top_f, text=f"{m}月", variable=var).pack(side=tk.LEFT, padx=(0, 4))

        # スタッフ拡張: 対象者チェックボックス行(project_knowledge["staffs"]のキー+"Ochi")。
        # 委任アクセス・共有メールボックスが無いため、スタッフの実績はOchiさんのメールボックス
        # 内で観測できる範囲(review_person_activity_qualifies)に限られる。既定はOchiさんのみ
        # (スタッフ俯瞰タブの「全員チェック」既定とは異なり、こちらは意図して絞ってある)。
        person_f = ttk.Frame(main)
        person_f.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(person_f, text="対象者:").pack(side=tk.LEFT, padx=(0, 5))

        self.v_review_person_vars = {}  # 表示名(project_knowledge["staffs"]のキー or "Ochi") -> tk.BooleanVar
        review_person_names = ["Ochi"] + list(self.project_knowledge.get("staffs", {}).keys())

        self.v_review_person_all = tk.BooleanVar(value=False)
        self._updating_review_person_checks = False

        def _on_review_person_all(*args):
            if self._updating_review_person_checks: return
            self._updating_review_person_checks = True
            v = self.v_review_person_all.get()
            for var in self.v_review_person_vars.values():
                var.set(v)
            self._updating_review_person_checks = False

        def _on_review_person_item(*args):
            if self._updating_review_person_checks: return
            self._updating_review_person_checks = True
            if self.v_review_person_vars and all(v.get() for v in self.v_review_person_vars.values()):
                self.v_review_person_all.set(True)
            else:
                self.v_review_person_all.set(False)
            self._updating_review_person_checks = False

        ttk.Button(
            person_f, text="全解除", command=lambda: self.v_review_person_all.set(False)
        ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Checkbutton(person_f, text="ALL", variable=self.v_review_person_all).pack(side=tk.LEFT, padx=(0, 8))
        self.v_review_person_all.trace_add("write", _on_review_person_all)

        for name in review_person_names:
            var = tk.BooleanVar(value=(name == "Ochi"))  # 既定はOchiさんのみ
            self.v_review_person_vars[name] = var
            var.trace_add("write", _on_review_person_item)
            ttk.Checkbutton(person_f, text=name, variable=var).pack(side=tk.LEFT, padx=(0, 4))

        btn_f = ttk.Frame(main)
        btn_f.pack(fill=tk.X, pady=(0, 10))

        self.btn_run_review = ttk.Button(btn_f, text="📈 振り返りを生成", command=self._run_review)
        self.btn_run_review.pack(side=tk.LEFT, padx=(0, 5))

        _reformat_init_state = tk.NORMAL if os.path.exists(REVIEW_LAST_RESULT_FILE) else tk.DISABLED
        self.btn_reformat_review = ttk.Button(
            btn_f, text="🎨 フォーマットのみ再生成",
            command=self._reformat_review,
            state=_reformat_init_state
        )
        self.btn_reformat_review.pack(side=tk.LEFT, padx=(5, 0))

        ttk.Label(
            main,
            text="※ チェックの付いた月だけ、現行メールボックスとオンラインアーカイブの両方から自分が送信したメール\n"
                 "(含・関連スレッド)と主催した会議を取得し、AIが「実績」単位に統合し直します。既存の結果があっても\n"
                 "チェックした月は必ず再取得・再分析します(古い結果はそのまま残らず上書きされます)。チェックを外した月は\n"
                 "取得・分析を行わず、前回までの結果(analysis_cache/review_monthly/配下のキャッシュ)をそのまま使います。\n"
                 "AI分析が一時的に失敗した月だけ後から再試行したい場合、その月だけチェックして再生成してください。\n"
                 "2か月より前はオンラインアーカイブから取得します。受信のみで自分から送信していないスレッドは対象外です\n"
                 "(振り返りは「実行したこと」を見るためです)。\n"
                 "対象者にスタッフ(部下)を追加した場合、委任アクセス・共有メールボックスは使用できないため、\n"
                 "Ochiさんのメールボックス内で観測できる範囲(本人が送信したスレッド、またはOchiさんが本人へ送信した\n"
                 "スレッド)だけが対象になります。ゴール(KPI)の定義はjson/review_person_goals.jsonで管理します。\n"
                 "スタッフを新規に対象へ追加した場合、過去月の実績を取得するにはその月のチェックも入れて再生成してください。",
            foreground="gray", justify=tk.LEFT
        ).pack(anchor=tk.W)

    def _get_review_all_months(self):
        """チェックボックス一覧に表示されている全ての月(当年1月〜当月)を、
        ON/OFF問わず古い順の"YYYYMM"文字列リストで返す(最終レポートに含める対象)。"""
        now = datetime.now()
        return [f"{now.year:04d}{m:02d}" for m in range(1, now.month + 1)]

    def _get_review_selected_months(self):
        """チェックボックスがONになっている月だけを、古い順の(年,月)タプルで返す
        (今回メールを再取得・AI再分析する対象)。"""
        selected = sorted(
            yyyymm for yyyymm, var in self.v_review_month_vars.items() if var.get()
        )
        return [(int(s[:4]), int(s[4:])) for s in selected]

    def _get_review_selected_persons(self) -> list:
        """対象者チェックボックスでONになっている対象者("Ochi"、および
        project_knowledge["staffs"]のキー)を、"Ochi"が常に先頭になるようにリストで返す。
        1つも選ばれていない場合は["Ochi"]にフォールバックする(必ず何かしら生成されるように)。"""
        selected = [name for name, var in self.v_review_person_vars.items() if var.get()]
        if not selected:
            return ["Ochi"]
        selected.sort(key=lambda n: (n != "Ochi", n))
        return selected

    def _save_review_result(self, review_data, period_label, total_input, total_output):
        """振り返りタブの生成結果(手動編集反映"前"のraw_achievements)を保存し、
        次回以降「フォーマットのみ再生成」でメール再取得・AI再解析なしにHTMLだけを
        作り直せるようにする。手動編集後の状態を保存しないのは、reformat実行のたびに
        review_manual_items.jsonの手動追加分が二重に足されるのを防ぐため。
        personsも保存する: 1ファイル=1対象者のHTMLに分割生成するため、reformat実行時に
        「今回の生成に含まれていた対象者は誰か」をこのファイルから復元する必要がある
        (raw_achievementsが0件の対象者がいても、その人のHTML(実績0件)を生成できるように)。"""
        try:
            with open(REVIEW_LAST_RESULT_FILE, 'w', encoding='utf-8') as jf:
                json.dump({
                    "raw_achievements": review_data.get("raw_achievements", []),
                    "months": review_data.get("months", []),
                    "persons": review_data.get("persons", []),
                    "period_label": period_label,
                    "total_input": total_input,
                    "total_output": total_output
                }, jf, ensure_ascii=False)
            self.root.after(0, lambda: self.btn_reformat_review.config(state=tk.NORMAL))
        except Exception as save_err:
            print(f"⚠️ review_last_result.json 保存失敗（HTML生成は継続）: {save_err}")

    def _run_review(self):
        """チェックの付いた月だけ、現行メールボックス+オンラインアーカイブから
        送信メール中心にスレッドを取得し(review_activity_qualifiesで機械フィルタ)、
        AIで実績単位に統合する。チェックの外れた月は既存キャッシュをそのまま使う
        (summarizer.generate_review_dataに丸投げ)。最終的にチェックボックス表示範囲
        (当年1月〜当月)の全月を統合したHTMLレポートを生成・表示する。
        スタッフ拡張: 対象者チェックボックスで選ばれた各スタッフについても、同じ月の
        メール取得結果(COM呼び出しは月ごとに1回のみ)をreview_person_activity_qualifies
        で再フィルタして同様にAI分析する(委任アクセス・共有メールボックスは無いため、
        Ochiさんのメールボックス内で観測できる範囲に限られる)。"""
        selected_months = self._get_review_selected_months()
        all_months = self._get_review_all_months()
        selected_persons = self._get_review_selected_persons()
        staff_persons = [p for p in selected_persons if p != "Ochi"]
        # スタッフ俯瞰タブと共通の登録名一覧(project_knowledge["staffs"])を、
        # 振り返りタブの「部下の成果」機械判定にもそのまま使う(二重管理を避けるため)。
        staff_names = list(self.project_knowledge.get("staffs", {}).keys())

        self.btn_run_review.config(state=tk.DISABLED, text="⏳ 取得・分析中...")
        self._set_status("📈 振り返りを生成中...", start_timer=True)

        def task():
            try:
                total_months = len(selected_months)
                monthly_threads = {}
                monthly_meetings = {}

                # get_review_mails_for_month/get_review_calendar_events自体は月をまたいだ
                # 全体件数を知らない(呼び出しのたびに(0, 0, メッセージ)しか渡してこない)ため、
                # ここで「今どの月を処理中か」をcurrent/totalとして被せ、ステータスバーに
                # "[2/6 (33%)] 📁 2026年6月 受信トレイ(アーカイブ) を取得中..." のように
                # 進捗が見えるようにする(チェック月数が多い・アーカイブ込みだと待ち時間が
                # 長くなるため)。チェックが1つも無い場合はこのループは空で、既存キャッシュの
                # 統合のみが行われる。
                for month_idx, (y, m) in enumerate(selected_months, start=1):
                    def progress_cb(c, t, msg, _idx=month_idx):
                        self.root.after(0, lambda: self._set_status(f"取得中: {msg}", current=_idx, total=total_months))

                    mails = self.outlook.get_review_mails_for_month(y, m, progress_callback=progress_cb)
                    threads = self.outlook.group_by_thread(mails)
                    meetings = self.outlook.get_review_calendar_events(y, m, progress_callback=progress_cb)
                    yyyymm = f"{y:04d}{m:02d}"

                    per_person_threads = {}
                    if "Ochi" in selected_persons:
                        per_person_threads["Ochi"] = {
                            cid: t for cid, t in threads.items()
                            if review_activity_qualifies(t['mails'], self.outlook.user_smtp_address, staff_names=staff_names)
                        }
                    if staff_persons:
                        aliases = harvest_person_email_aliases(mails, staff_persons)
                        for person in staff_persons:
                            per_person_threads[person] = {
                                cid: t for cid, t in threads.items()
                                if review_person_activity_qualifies(
                                    t['mails'], person, aliases.get(person, set()), self.outlook.user_smtp_address
                                )
                                # Japan Site Weekly議事録(ICS R04 Japan R&D meeting - week)は
                                # OchiさんからJapan Staff All等の配布リストへ送られるため、
                                # 個人名にも個人アドレスにも一致せず上のreview_person_activity_qualifies
                                # では拾えない。全プロジェクトの進捗が1通に混在した議事録として、
                                # 対象スタッフ全員へ無条件で含める(本文からの人物別抽出は
                                # summarize_review_month側のプロンプトで行う)。
                                or review_thread_is_minutes(t, self.outlook.user_smtp_address)
                            }

                    monthly_threads[yyyymm] = per_person_threads
                    monthly_meetings[yyyymm] = meetings

                review_data = self.summarizer.generate_review_data(
                    monthly_threads, monthly_meetings, all_months, staff_names=staff_names,
                    persons=selected_persons,
                    progress_callback=lambda c, t, msg: self.root.after(0, lambda: self._set_status(msg, current=c, total=t))
                )

                if len(selected_months) == len(all_months):
                    period_label = f"{all_months[0][:4]}年 1月〜{int(all_months[-1][4:])}月（全月更新）"
                elif selected_months:
                    updated_label = "、".join(f"{m}月" for (_, m) in selected_months)
                    period_label = f"{all_months[0][:4]}年 1月〜{int(all_months[-1][4:])}月（{updated_label}を更新）"
                else:
                    period_label = f"{all_months[0][:4]}年 1月〜{int(all_months[-1][4:])}月（キャッシュのみ、更新なし）"

                # 四半期パフォーマンスレビューという用途上、複数人の実績を1つのHTMLに
                # 混在させると本人以外の評価内容が見えてしまうため、対象者ごとに別々の
                # HTMLファイルを生成する(複数人まとめたHTMLは生成しない)。
                self._save_review_result(review_data, period_label, self.summarizer.total_input_tokens, self.summarizer.total_output_tokens)
                import webbrowser
                for person in selected_persons:
                    person_path = self.reporter.generate_review_report(
                        review_data, period_label,
                        self.summarizer.total_input_tokens, self.summarizer.total_output_tokens,
                        filter_person=person
                    )
                    if person_path:
                        webbrowser.open(person_path)
            except Exception as e:
                import tkinter.messagebox as messagebox
                self.root.after(0, lambda: messagebox.showerror("エラー", str(e)))
            finally:
                self.root.after(0, lambda: self.btn_run_review.config(state=tk.NORMAL, text="📈 振り返りを生成"))
                self.root.after(0, lambda: self._set_status("✅ 振り返り生成完了", start_timer=False))

        threading.Thread(target=task, daemon=True).start()

    def _reformat_review(self):
        """フォーマットのみ再生成: 現在チェックボックスで選ばれている対象者について、
        月別キャッシュ(analysis_cache/review_monthly/配下、メール再取得・AI再解析なし)
        から実績を読み込み直し、review_manual_items.jsonの最新値(非表示・ランク上書き・
        手動追加・文言修正)を適用してHTMLだけ再生成する。
        対象者は「前回『📈 振り返りを生成』を実行した時点で選ばれていた対象者」ではなく、
        今チェックボックスで選ばれている対象者を使う(例: 前回はOchi・Saji・Yutoで生成した後、
        チェックをKajikawaだけに変えてこのボタンを押せば、Kajikawaの月別キャッシュから
        Kajikawaだけのレポートを作り直せる)。以前は直近の生成結果(review_last_result.json)
        の対象者リストをそのまま使っていたため、チェックを変えても前回の対象者のHTMLが
        出てきてしまう不具合があった。
        ただし、その対象者がある月について一度も「📈 振り返りを生成」で分析されたことが
        無ければ、その月のキャッシュ自体が存在しないため実績0件になる(AI再解析はしないため、
        過去に一度も分析していない対象者・月の実績はこのボタンでは作れない。その場合は
        対象月のチェックを入れて「📈 振り返りを生成」を実行する必要がある)。"""
        import tkinter.messagebox as messagebox

        if not os.path.exists(REVIEW_CACHE_DIR):
            messagebox.showerror("エラー", "保存済みデータがありません。\n先に「📈 振り返りを生成」を実行してください。")
            return

        all_months = self._get_review_all_months()
        selected_persons = self._get_review_selected_persons()

        self.btn_reformat_review.config(state=tk.DISABLED, text="⏳ フォーマット再生成中...")
        self._set_status("🎨 フォーマットのみ再生成中...", start_timer=True)

        def task():
            try:
                all_achievements = []
                for yyyymm in all_months:
                    for person in selected_persons:
                        all_achievements.extend(self.summarizer.load_review_month_cache(yyyymm, person=person))

                raw_achievements = [dict(a) for a in all_achievements]
                merged = self.summarizer.apply_review_manual_overrides(all_achievements)
                period_label = f"{all_months[0][:4]}年 1月〜{int(all_months[-1][4:])}月（保存済みキャッシュから再構成）"
                review_data = {
                    "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "months": all_months,
                    "persons": selected_persons,
                    "achievements": merged,
                    "raw_achievements": raw_achievements,
                }
                # /review_hidden_list(非表示にした実績の確認・復元パネル)は
                # review_last_result.jsonのraw_achievementsからタイトルを引くため、
                # 今回チェックされていた対象者の分で上書き保存し直す。
                self._save_review_result(review_data, period_label, 0, 0)

                # 複数人まとめたHTMLは生成せず、対象者ごとに別々のHTMLファイルを生成する
                # (_run_reviewの初回生成と同じ方針)。
                import webbrowser
                for person in selected_persons:
                    person_path = self.reporter.generate_review_report(
                        review_data, period_label, 0, 0,
                        reformat_mode=True, filter_person=person
                    )
                    if person_path:
                        webbrowser.open(person_path)
            except Exception as e:
                _err = str(e)
                self.root.after(0, lambda: messagebox.showerror("エラー", f"フォーマット再生成に失敗しました:\n{_err}"))
            finally:
                self.root.after(0, lambda: self.btn_reformat_review.config(
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
            # 実際に生成されるレポートファイル名(Project_*/Staff_*/Executive_Cockpit_*/
            # CockpitV2_*/ActionDashboard_*.html)はいずれも"_report_"という文字列を含まないため、
            # 旧パターン"*_report_*.html"はどのファイルにも一致せず、常に0件扱いになっていた。
            # 出力フォルダ配下のhtmlファイルは全て本ツールが生成したレポートのため、*.htmlに変更する。
            for f in folder.glob("*.html"):
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

        # tk変数の読み取りはメインスレッドで行う(以降はワーカースレッドへ渡す)
        pl_str = self.v_past_limit.get()
        past_limit = 300000 if "無制限" in pl_str else int(re.search(r'\d+', pl_str).group()) if re.search(r'\d+', pl_str) else 800

        def summarize_and_report(choice):
            def task():
                res = self.summarizer.summarize_multiple_threads(sel, past_limit=past_limit, long_text_choice=choice)
                path = self.reporter.generate_report(sel, res, {})
                webbrowser.open(path)
                self._set_status("✅ 完了")
            threading.Thread(target=task, daemon=True).start()

        def prepare():
            # 本文KWを空にして検索した場合、高速化のため本文が読み込まれておらず
            # bodyが空のままになっている(search_mails_fastのlight_mode)。そのまま
            # 要約すると「本文がありませんでした」という結果になるため、実際に要約する
            # 直前に、選択されたスレッドの本文だけをここで補完する。
            # 既に本文があるメールには触れないので、本文KW付きで検索した場合や
            # 2回目以降の要約ではOutlookへのアクセスは発生しない。
            # COM呼び出しでGUIが固まらないよう、この処理はワーカースレッドで行う。
            try:
                self.outlook.enrich_bodies_for_threads(
                    sel,
                    progress_callback=lambda c, t, msg: self.root.after(
                        0, lambda: self._set_status(msg, current=c, total=t))
                )
            except Exception as e:
                # 本文補完に失敗しても、取得済みの範囲で要約は続行する
                print(f"本文補完に失敗しました(要約は継続します): {e}")

            # 長文判定は、本文を補完した"後"の実際の文字数で行う必要がある
            # (補完前は常に0文字となり、長文警告が出ないまま巨大なスレッドを
            # そのままAIへ送ってしまうため)。
            large_threads = []
            max_len = 0
            for cid, t in sel.items():
                if t['mails']:
                    t_len = sum(len(str(m['body'])) for m in t['mails'])
                    if t_len > 10000:
                        large_threads.append(t['topic'])
                        if t_len > max_len:
                            max_len = t_len

            def ask_and_go():
                # モーダルダイアログの表示はメインスレッドで行う
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
                self._set_status("📝 生成中...")
                summarize_and_report(choice)

            self.root.after(0, ask_and_go)

        threading.Thread(target=prepare, daemon=True).start()

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

    def _show_gemini_direct_restored_popup(self):
        """Gemini APIへの直接呼び出しが復活したことを知らせるポップアップ。
        grab_set()を呼ばない非モーダルウィンドウなので、OKを押さなくても
        他の操作(取得・要約など)をそのまま続けられる。
        表示は「復活した日の初回1回だけ」(_observe_gemini_direct_stateで制御)。"""
        try:
            d = tk.Toplevel(self.root)
            d.title("Gemini API 直接接続の復活")
            tk.Label(
                d, justify=tk.LEFT, padx=20, pady=15, font=("", 10),
                text=("✅ Gemini APIへの直接呼び出しに成功しました。\n\n"
                      "これまでは自宅PCのプロキシ経由で動作していましたが、\n"
                      "会社PCから直接APIを呼び出せる状態に復帰しています。\n\n"
                      "※このお知らせは復活した日の初回1回だけ表示されます。\n"
                      "※OKを押さなくても、そのまま作業を続けられます。")
            ).pack()
            ttk.Button(d, text="OK", command=d.destroy).pack(pady=(0, 15))
            # 他ウィンドウの背後に隠れて気づかれないよう最前面に出すが、
            # grab_set()はしない(モーダルにしない)。
            try:
                d.attributes('-topmost', True)
                d.lift()
            except Exception:
                pass
        except Exception as e:
            print(f"Gemini直接接続復活ポップアップの表示に失敗: {e}")

    def _set_api(self):
        # このAPIキー入力欄は、Gemini共通クライアント(gemini_client.py)への移行により
        # 実際の呼び出しには使われなくなった(認証情報は環境変数から読まれる)。
        # 値の保存自体は従来どおり行う(旧バージョンへ戻した場合に設定が残るように)が、
        # 使われないことが分かるよう画面に明記する。
        d = tk.Toplevel(self.root)
        d.title("Gemini APIキー（現在は未使用）")
        tk.Label(
            d, justify=tk.LEFT, fg="#b45309",
            text=("※この入力欄は現在使用されていません。\n"
                  "Gemini APIの認証情報は環境変数から読み込まれます:\n"
                  "  GEMINI_API_KEY   … 直接呼び出し用\n"
                  "  GEMINI_PROXY_URL … 自宅PCプロキシ(直接呼び出し失敗時のフォールバック先)\n"
                  "環境変数を設定した後は、コマンドプロンプトを開き直してから起動してください。")
        ).pack(padx=10, pady=(10, 6), anchor=tk.W)
        e = ttk.Entry(d, width=40)
        e.pack(padx=10)
        e.insert(0, self.config['gemini_api_key'])
        def save():
            self.config['gemini_api_key'] = e.get()
            save_config(self.config)
            self.summarizer.api_key = e.get()
            d.destroy()
        ttk.Button(d, text="Save", command=save).pack(pady=8)


if __name__ == "__main__":
    app = MailManagerGUI()
    app.root.mainloop()
