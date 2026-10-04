# -*- coding: utf-8 -*-
"""A1「判断待ち」テスト共通ローダ兼ユーティリティ。

役割
  1. 最新リビジョン (outlook_total_organizer_*.py を名前順で最後のもの。
     環境変数 OTO_TARGET があればそれ) を importlib で ``oto_under_test`` として読み込む。
  2. win32com / pythoncom / google.genai / requests / bs4 が import できない環境
     (Linux 等) でだけ、sys.modules に最小スタブを入れる。実環境にあればスタブしない。
     スタブの「Outlook/COM/ネットワークを呼ぶ関数」は呼ばれたら RuntimeError で大声で失敗する
     (A1 は COM・AI に触れない仕様のため、触れたらテストで検知できるようにする)。
  3. tempdir_cwd(): 一時ディレクトリへ chdir するコンテキストマネージャ。
     json/ や analysis_cache/ は相対パスで使われるため、テストは必ずこの中で動かす。
  4. 合成データの作成ヘルパ (cache / action_status / last_run)。

このファイルは仕様書 (A1_SPEC.md) だけを根拠に作られている。実装の中身は見ていない。
"""
import contextlib
import glob
import importlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time
import types
from datetime import datetime

# テスト実行で対象フォルダ配下に __pycache__ を増やさない
sys.dont_write_bytecode = True

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
TOOL_DIR = os.path.dirname(TESTS_DIR)
MODULE_NAME = "oto_under_test"
TARGET_GLOB = "outlook_total_organizer_*.py"

# 実際にスタブへ差し替えたモジュール名 (run_tests.py が表示する)
STUBBED_MODULES = []

# ---- 仕様書で「新規」とされている名前 (未実装検知用) ------------------------------
A1_CONSTANTS = (
    "ACTION_DASHBOARD_CACHE_FILE", "ACTION_LAST_RUN_FILE", "ACTION_DECISION_TYPES",
    "ACTION_DECISION_KEYWORDS", "ACTION_DECISION_STALE_HOURS",
    "ACTION_DECISION_DEFAULT_HORIZON_DAYS", "ACTION_SELF_TARGET_ALIASES",
    "ACTION_PROGRESS_VALUES",
    # 仕様変更(第2回)で追加。モジュール定数かクラス定数かは仕様に明記が無いので両方を探す
    "ACTION_DECISION_CLOCK_SKEW_SECONDS", "ACTION_TAB_PADDING_PX",
)
A1_FUNCTIONS = (
    "normalize_action_target_token", "is_target_self", "build_self_aliases",
    "is_decision_action", "load_action_dashboard_cache", "compute_pending_decisions",
    "count_recent_error_threads", "save_action_last_run", "load_action_last_run",
    "format_decision_age", "build_decision_heading", "build_action_decision_snapshot",
    "set_action_progress",
    "build_decision_heading_compact",       # 仕様変更(第2回)で追加
)
A1_GUI_ATTRS = (
    "ACTION_TAB_BASE_TEXT", "_ui_action_decision_panel", "_refresh_action_decision_view",
    "_apply_action_decision_view", "_action_decision_tick",
    "_render_action_decision_rows", "_choose_action_tab_heading",      # 仕様変更(第2回)で追加
)
A1_ALL_NAMES = A1_CONSTANTS + A1_FUNCTIONS + A1_GUI_ATTRS


# ============================================================
# 対象ファイルの特定
# ============================================================
def list_revisions():
    """tool フォルダ内の outlook_total_organizer_*.py を名前順で返す"""
    return sorted(glob.glob(os.path.join(TOOL_DIR, TARGET_GLOB)))


def find_target_path():
    """環境変数 OTO_TARGET (絶対パス / カレント相対 / ツールフォルダ相対 / ファイル名) があればそれ。
    無ければ名前順で最後のリビジョン。"""
    env = os.environ.get("OTO_TARGET", "").strip()
    if env:
        for cand in (env, os.path.join(TOOL_DIR, env)):
            if os.path.isfile(cand):
                return os.path.abspath(cand)
        raise FileNotFoundError(f"OTO_TARGET が見つかりません: {env}")
    revs = list_revisions()
    if not revs:
        raise FileNotFoundError(f"{TOOL_DIR} に {TARGET_GLOB} がありません")
    return revs[-1]


def find_baseline_path(target=None):
    """対象の「直前のリビジョン」(名前順で1つ前)。無ければ None。
    環境変数 OTO_BASELINE があればそれを使う (既存コード不変ガードの比較元)。"""
    env = os.environ.get("OTO_BASELINE", "").strip()
    if env:
        for cand in (env, os.path.join(TOOL_DIR, env)):
            if os.path.isfile(cand):
                return os.path.abspath(cand)
        raise FileNotFoundError(f"OTO_BASELINE が見つかりません: {env}")
    target = os.path.abspath(target or find_target_path())
    revs = [os.path.abspath(p) for p in list_revisions()]
    if target in revs:
        i = revs.index(target)
        return revs[i - 1] if i > 0 else None
    # 対象がリストに無い (OTO_TARGET で別場所を指定) 場合は名前順で最後のものを基準にする
    return revs[-1] if revs else None


# ============================================================
# 最小スタブ (import できない場合のみ)
# ============================================================
class _Dummy:
    """どんな引数でも受け取りどんな属性も持つ汎用ダミー。import 時の定数参照・型注釈用。"""

    def __init__(self, *args, **kwargs):
        pass

    def __call__(self, *args, **kwargs):
        return _Dummy()

    def __getattr__(self, name):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return _Dummy()

    def __iter__(self):
        return iter(())


class _StubModule(types.ModuleType):
    """未知の属性は汎用ダミー(クラス)を返す最小スタブ。"""

    def __getattr__(self, name):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return _Dummy


def _boom(label):
    def _raise(*args, **kwargs):
        raise RuntimeError(
            f"[テスト用スタブ] {label} は使えません。"
            "A1 のコードが Outlook(COM)/ネットワークに触れた疑いがあります。")
    _raise.__name__ = "stub_" + label.replace(".", "_")
    return _raise


def _stub_win32com(name):
    m = _StubModule(name)
    m.__path__ = []          # サブモジュール (win32com.client) を持つ「パッケージ」扱い
    return m


def _stub_win32com_client(name):
    m = _StubModule(name)
    m.Dispatch = _boom("win32com.client.Dispatch")
    m.GetObject = _boom("win32com.client.GetObject")
    return m


def _stub_pythoncom(name):
    m = _StubModule(name)
    m.CoInitialize = _boom("pythoncom.CoInitialize")
    m.CoUninitialize = _boom("pythoncom.CoUninitialize")
    m.com_error = type("com_error", (Exception,), {})
    return m


def _stub_google(name):
    m = _StubModule(name)
    m.__path__ = []
    return m


def _stub_google_genai(name):
    m = _StubModule(name)
    m.__path__ = []
    m.Client = _boom("google.genai.Client")
    return m


def _stub_requests(name):
    m = _StubModule(name)
    for fn in ("get", "post", "put", "delete", "request"):
        setattr(m, fn, _boom("requests." + fn))
    return m


def _stub_bs4(name):
    m = _StubModule(name)
    m.BeautifulSoup = _boom("bs4.BeautifulSoup")
    return m


def _stub_tk_package(name):
    m = _StubModule(name)
    m.__path__ = []
    m.__a1_stub__ = True          # GUIテストが「実物のtkinterではない」ことを見分けるための目印
    return m


def _stub_tk_module(name):
    m = _StubModule(name)
    m.__a1_stub__ = True
    return m


_STUB_FACTORIES = (
    # tkinter は GUI テストの実行に必要 (実物が無い環境では GUI テストは skip)。ただし対象モジュールが
    # import 時に tkinter を読むため、実物が無い Python でも非GUIテストが動くよう最小スタブを用意しておく
    ("tkinter", _stub_tk_package),
    ("tkinter.font", _stub_tk_module),
    ("tkinter.ttk", _stub_tk_module),
    ("tkinter.messagebox", _stub_tk_module),
    ("win32com", _stub_win32com),
    ("win32com.client", _stub_win32com_client),
    ("pythoncom", _stub_pythoncom),
    ("google", _stub_google),
    ("google.genai", _stub_google_genai),
    ("google.genai.types", lambda n: _StubModule(n)),
    ("requests", _stub_requests),
    ("bs4", _stub_bs4),
)


def _install_stubs():
    """import できないモジュールにだけスタブを入れる (実環境にあればそのまま使う)。"""
    for name, factory in _STUB_FACTORIES:
        if name in STUBBED_MODULES:
            continue
        try:
            importlib.import_module(name)
            continue                      # 実物がある → スタブしない
        except Exception:                 # ImportError 以外 (壊れたパッケージ等) もスタブ対象
            sys.modules.pop(name, None)
        mod = factory(name)
        sys.modules[name] = mod
        parent, _, child = name.rpartition(".")
        if parent and parent in sys.modules:
            setattr(sys.modules[parent], child, mod)
        STUBBED_MODULES.append(name)


# ============================================================
# 読み込み
# ============================================================
_module = None


def load():
    """対象リビジョンを ``oto_under_test`` として読み込んで返す (2回目以降はキャッシュ)。"""
    global _module
    if _module is not None:
        return _module
    path = find_target_path()
    _install_stubs()
    spec = importlib.util.spec_from_file_location(MODULE_NAME, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(MODULE_NAME, None)
        raise
    _module = mod
    return mod


def target_path():
    return find_target_path()


def missing_a1_names(mod=None):
    """仕様上「新規」の名前のうち、まだ対象モジュールに無いもの。"""
    mod = mod or load()
    gui = getattr(mod, "MailManagerGUI", None)
    missing = []
    for n in A1_CONSTANTS + A1_FUNCTIONS:
        if not hasattr(mod, n) and not (n in A1_CONSTANTS and gui is not None and hasattr(gui, n)):
            missing.append(n)
    for n in A1_GUI_ATTRS:
        if gui is None or not hasattr(gui, n):
            missing.append("MailManagerGUI." + n)
    return missing


# ============================================================
# 一時ディレクトリ
# ============================================================
@contextlib.contextmanager
def tempdir_cwd():
    """一時ディレクトリへ chdir し、終了時に元のcwdへ戻して一時ディレクトリを削除する。
    (json/ analysis_cache/ は相対パスで使われるため、テストはこの中で行う)"""
    try:
        old = os.getcwd()
    except OSError:
        old = TESTS_DIR
    tmp = tempfile.mkdtemp(prefix="oto_a1_")
    os.chdir(tmp)
    try:
        yield tmp
    finally:
        try:
            os.chdir(old)
        except OSError:
            os.chdir(TESTS_DIR)
        shutil.rmtree(tmp, ignore_errors=True)


# ============================================================
# タイムゾーン切替 (ローカル時刻の扱いの検証用)
# ============================================================
# 実装は updated_at / finished_at を「ローカル時刻のナイーブな ISO 文字列」で読み書きし、epoch との比較は
# datetime.timestamp() (ローカル解釈) で行う想定。UTC の環境 (CI/サンドボックス) では UTC 固定の誤実装と
# 区別できないので、JST(+9) / EST(-5) に切り替えた状態でも同じテストを走らせる (越智さんの環境は JST)。
class TimezoneMixin:
    """テストクラスに TimezoneMixin を先頭で混ぜると、そのクラスの全テストを TZ_SPEC のローカルTZで実行する。
    time.tzset が無い OS (Windows) では skip (そちらは実機のローカルTZそのものが検証対象になる)。"""

    TZ_SPEC = "JST-9"

    def setUp(self):
        if not hasattr(time, "tzset"):
            self.skipTest("time.tzset が無い OS: ローカルタイムゾーンの切替テストは対象外")
        old = os.environ.get("TZ")
        os.environ["TZ"] = self.TZ_SPEC
        time.tzset()

        def restore():
            if old is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old
            time.tzset()
        self.addCleanup(restore)
        super().setUp()


def make_tz_variants(namespace, base_classes, specs=(("JST", "JST-9"), ("EST", "EST5"))):
    """base_classes の各テストクラスについて、TZ ごとの派生クラス (<名前>_TZ_<tag>) を namespace に追加する。"""
    for base in base_classes:
        for tag, spec in specs:
            name = f"{base.__name__}_TZ_{tag}"
            namespace[name] = type(name, (TimezoneMixin, base),
                                   {"TZ_SPEC": spec, "__module__": namespace.get("__name__", __name__),
                                    "__doc__": f"{base.__name__} をローカルTZ {spec} で実行"})


# ============================================================
# ファイル操作ヘルパ
# ============================================================
def write_bytes(path, data):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def write_text(path, text):
    write_bytes(path, text.encode("utf-8"))


def write_json(path, obj):
    write_text(path, json.dumps(obj, ensure_ascii=False, indent=2))


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def snapshot_files(root="."):
    """root 配下の「ファイルだけ」を {相対パス: (中身, mtime_ns)} で返す (ディレクトリは含めない)。"""
    out = {}
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            st = os.stat(p)
            out[rel] = (read_bytes(p), st.st_mtime_ns)
    return out


# ============================================================
# 合成データのビルダ
# ============================================================
# テストの「現在時刻」。ローカルタイムのナイーブな datetime (実装が datetime.now() を使う前提と揃える)。
NOW = datetime(2026, 10, 4, 12, 0, 0)
NOW_TS = int(NOW.timestamp())
DAY = 86400
HOUR = 3600

CACHE_PATH = os.path.join("analysis_cache", "action_dashboard.json")
STATUS_PATH = os.path.join("json", "action_status.json")
LAST_RUN_PATH = os.path.join("json", "action_last_run.json")

ROW_KEYS = (
    "key", "cid", "topic", "real_topic", "entry_id", "latest_ts", "date_mmdd", "importance",
    "owner", "target", "action", "deadline", "ai_status", "progress", "priority", "comment",
    "resurfaced", "is_decision",          # 仕様変更(第2回)で追加
)
SNAPSHOT_KEYS = (
    "rows", "pending_count", "error_count", "last_run", "stale", "freshness_unknown",
    "heading", "status_text", "since_ts",
    "older_rows", "others_count", "partial", "horizon_days", "heading_compact",   # 仕様変更(第2回)で追加
)


def ts_ago(hours=0.0, now=NOW):
    """now から hours 時間前の epoch (int)。"""
    return int(now.timestamp() - hours * HOUR)


def fmt_dt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def make_action(owner="Nakai", target="あなた", action="承認をお願いします", deadline="",
                status="未対応", waiting_people=None, reminder_count=0):
    """cache の data.actions[] の1要素。"""
    return {
        "owner": owner, "target": target, "action": action, "deadline": deadline,
        "status": status,
        "waiting_people": [owner] if waiting_people is None else waiting_people,
        "reminder_count": reminder_count,
    }


def make_thread(actions=None, *, topic="AI要約タイトル", real_topic="実際の件名",
                action_type="承認・決裁", importance="高", latest_ts=None,
                entry_id="ENTRY-META", cached_entry_id="ENTRY-CACHED",
                meta=True, error=False, mail_count=2):
    """cache の threads[cid] 1件分。

    meta=True  : latest_ts 等から標準の meta を作る
    meta=False : meta キー自体を付けない (旧形式キャッシュ)
    meta=dict  : その dict を meta としてそのまま使う
    """
    if latest_ts is None:
        latest_ts = ts_ago(2)
    if actions is None:
        actions = [make_action()]
    data = {
        "thread_id": "?", "topic": topic, "summary": "要約", "category": "プロジェクト管理",
        "action_type": action_type, "importance": importance, "reasoning": "AIの所見",
        "actions": actions,
    }
    if error:
        data["_error"] = True
    entry = {"mail_count": mail_count, "latest_entry_id": cached_entry_id, "data": data}
    if meta is True:
        dt = datetime.fromtimestamp(latest_ts)
        entry["meta"] = {
            "real_topic": real_topic, "latest_entry_id": entry_id,
            "latest_date_str": dt.strftime("%Y-%m-%d %H:%M"),
            "latest_date_mmdd": dt.strftime("%m/%d %H:%M"),
            "latest_ts": latest_ts, "has_unread": False, "is_r19": False, "is_flagged": False,
        }
    elif isinstance(meta, dict):
        entry["meta"] = meta
    return entry


def make_cache(threads):
    """{cid: entry} から {"threads": {...}} を作る (data.thread_id を cid に揃える)。"""
    for cid, e in threads.items():
        if isinstance(e, dict) and isinstance(e.get("data"), dict):
            e["data"]["thread_id"] = cid
    return {"threads": threads}


# 仕様変更(第2回): done は「updated_at が meta.latest_ts 以上」のときだけ除外され、新着(latest_ts > updated_at)で
# 再浮上する。既定の updated_at は「どのテスト用 latest_ts よりも未来」にして、done=除外 になるようにしておく。
# (再浮上を試すテストは updated_at を明示する)
FUTURE_UPDATED_AT = "2030-01-01T00:00:00"


def make_status(progress="not_started", priority="", comment="", updated_at=FUTURE_UPDATED_AT):
    return {"progress": progress, "priority": priority, "comment": comment, "updated_at": updated_at}


def iso_epoch(iso):
    """'%Y-%m-%dT%H:%M:%S' (ローカル時刻) -> epoch(int)。実装の updated_at 解釈と同じ前提。"""
    return int(datetime.strptime(iso, "%Y-%m-%dT%H:%M:%S").timestamp())


def make_last_run(finished, days=7, label="1週間"):
    """finished は datetime。action_last_run.json の中身 (仕様8の形式)。"""
    return {"finished_at": fmt_dt(finished), "days": days, "period_label": label}


def write_env(cache=None, statuses=None, last_run=None):
    """カレントディレクトリ (一時cwd) に合成データを書く。None は「ファイルを作らない」。"""
    if cache is not None:
        write_json(CACHE_PATH, cache)
    if statuses is not None:
        write_json(STATUS_PATH, statuses)
    if last_run is not None:
        write_json(LAST_RUN_PATH, last_run)
