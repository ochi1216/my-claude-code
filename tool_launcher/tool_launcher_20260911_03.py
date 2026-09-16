#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tool_launcher_20260911_03.py  --  my-claude-code ツールランチャー v2

VERSION: 20260911_03

旧 tool_launcher_20260808_01.py（PythonScripts直下、Git管理外）の後継。
設計の経緯は同フォルダの README.md / CHANGELOG.md を参照。

主要な方針:
  * ツールの定義は tools.json に外部化する。本ファイルは編集せずにツールを増減できる。
  * my-claude-code 配下に移行済みのツールは .bat を起動し、最新ファイル探索・Python選択・
    依存関係の解決は .bat 側に任せる（本体はそれらのロジックを持たない）。
  * 旧 PythonScripts に残っているツールは、従来どおり最新の .py を直接起動する。
  * 追加ライブラリ（psutil / customtkinter 等）には一切依存しない。標準ライブラリのみ。

Windows専用の処理（コンソール非表示・多重起動防止）はすべて sys.platform で分岐しており、
他OSでも import / 起動自体は通る（GUIの見た目は保証しない）。
"""

import atexit
import ctypes
import datetime
import glob
import json
import os
import re
import subprocess
import sys
import threading
import traceback
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox

VERSION = "20260911_03"

IS_WINDOWS = sys.platform == "win32"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
TOOLS_JSON = os.path.join(SCRIPT_DIR, "tools.json")
LOG_FILE = os.path.join(SCRIPT_DIR, "launcher_log.txt")
RESTART_BAT = os.path.join(SCRIPT_DIR, "run_tool_launcher.bat")

# 多重起動防止に使う名前付きミューテックス名（セッションローカル）。
MUTEX_NAME = "my_claude_code_tool_launcher_v2"

CREATE_NEW_CONSOLE = 0x00000010
CREATE_NO_WINDOW = 0x08000000
ERROR_ALREADY_EXISTS = 183
SW_HIDE = 0
SW_SHOWNORMAL = 1

# ---------------------------------------------------------------------------
# 配色（CLAUDE.md のUI規約: bg #1a1a2e / accent #e94560 に準拠した単一ダークテーマ）
# ---------------------------------------------------------------------------
C_BG = "#1a1a2e"          # アプリ背景
C_BAR = "#16213e"         # ヘッダ／ステータスバー
C_TILE = "#212545"        # ツールタイル
C_TILE_HI = "#2b3060"     # ツールタイル（ホバー）
C_LINE = "#2c3160"        # 罫線（強）
C_LINE_SOFT = "#232850"   # 罫線（弱）
C_INK = "#eceef8"         # 本文
C_INK2 = "#a8aed0"        # 副次テキスト
C_INK3 = "#6f76a0"        # 補助テキスト
C_ACCENT = "#e94560"      # 差し色（更新ボタンとホバーにのみ使用）
C_ACCENT_DIM = "#8f2236"
C_OK = "#4ecca3"          # ■ プロキシ経由
C_WARN = "#f0a500"        # □ 直接呼び出し
C_MOVE = "#8b7cf6"        # 移管予定
C_BAT = "#7fd7ff"         # BATバッジ
C_LOG_BG = "#101527"      # ログ枠背景

GEMINI_STRIPE = {"proxy": C_OK, "direct": C_WARN}
GEMINI_BADGE = {"proxy": ("■ PROXY", C_OK, "#276a55"),
                "direct": ("□ DIRECT", C_WARN, "#6b4c10")}
KIND_BADGE = {"bat": ("BAT", C_BAT, "#2e5570"),
              "py": ("PY", C_INK3, C_LINE),
              "streamlit": ("STREAMLIT", C_BAT, "#2e5570")}

# GUIログ枠。GUI構築前のログはここに溜めて、構築後にまとめて流し込む。
_log_widget = None
_log_backlog = []

# ミューテックスのハンドル。プロセスが生きている間だけ保持する。
_mutex_handle = None


# ---------------------------------------------------------------------------
# ログ
# ---------------------------------------------------------------------------
def log_message(msg):
    """日本語＋絵文字ステータス形式でログを出力する（GUI枠とファイルの両方）。"""
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    line = "[{}] {}".format(timestamp, msg)

    if _log_widget is None:
        _log_backlog.append(line)
    else:
        _append_to_log_widget(line)

    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write("[{}] {}\n".format(
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg))
    except OSError as e:
        # ログファイルに書けなくても動作は継続する。ただし黙って捨てない。
        if _log_widget is not None:
            _append_to_log_widget("[{}] ⚠️ ログファイルに書き込めません: {}".format(
                timestamp, e))


def _append_to_log_widget(line):
    _log_widget.configure(state="normal")
    _log_widget.insert("end", line + "\n")
    _log_widget.see("end")
    _log_widget.configure(state="disabled")


# ---------------------------------------------------------------------------
# Windows固有処理
# ---------------------------------------------------------------------------
def _console_hwnd():
    if not IS_WINDOWS:
        return None
    try:
        return ctypes.windll.kernel32.GetConsoleWindow()
    except Exception:
        return None


def hide_console():
    """起動元バッチのコンソールウィンドウを隠す（ログはGUI内に表示するため）。

    隠したままプロセスが終わると、起動元バッチの `pause` が見えない位置で
    待ち続けてしまう。そうならないよう、終了時に必ず戻す処理を登録しておく。
    """
    hwnd = _console_hwnd()
    if hwnd:
        try:
            ctypes.windll.user32.ShowWindow(hwnd, SW_HIDE)
            atexit.register(show_console)
        except Exception:
            pass


def show_console():
    """致命的エラー時にコンソールを再表示し、traceback を読めるようにする。"""
    hwnd = _console_hwnd()
    if hwnd:
        try:
            ctypes.windll.user32.ShowWindow(hwnd, SW_SHOWNORMAL)
        except Exception:
            pass


def acquire_single_instance():
    """名前付きミューテックスで多重起動を防ぐ。

    ロックファイル方式と違い、プロセスが異常終了してもOSが自動的に解放するため、
    ロックが残って起動できなくなる事故が起きない。psutil も不要。

    Returns:
        True  : このプロセスが唯一のランチャー
        False : すでに別のランチャーが起動している
    """
    global _mutex_handle
    if not IS_WINDOWS:
        return True
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        handle = kernel32.CreateMutexW(None, 1, MUTEX_NAME)
        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            if handle:
                kernel32.CloseHandle(ctypes.c_void_p(handle))
            return False
        _mutex_handle = handle
        return True
    except Exception:
        # ミューテックスが使えない環境では多重起動防止を諦めて起動を優先する。
        return True


def release_single_instance():
    """再起動の直前にミューテックスを解放する（新プロセスが弾かれないように）。"""
    global _mutex_handle
    if _mutex_handle and IS_WINDOWS:
        try:
            ctypes.windll.kernel32.ReleaseMutex(ctypes.c_void_p(_mutex_handle))
            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(_mutex_handle))
        except Exception:
            pass
    _mutex_handle = None


# ---------------------------------------------------------------------------
# tools.json の読み込みとパス解決
# ---------------------------------------------------------------------------
def load_config():
    """tools.json を読み込む。失敗時は None を返す（呼び出し側でメッセージ表示）。"""
    if not os.path.isfile(TOOLS_JSON):
        messagebox.showerror(
            "設定ファイルがありません",
            "tools.json が見つかりません。\n\n"
            "想定の場所: {}\n\n"
            "git pull でファイルが取得できているか確認してください。".format(TOOLS_JSON))
        return None
    try:
        with open(TOOLS_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        messagebox.showerror(
            "設定ファイルを読めません",
            "tools.json の読み込みに失敗しました。\n\n"
            "場所: {}\n\nエラー: {}".format(TOOLS_JSON, e))
        return None


def resolve_root(root_kind, legacy_root):
    """root 指定（repo / legacy）を実際のフォルダパスに変換する。"""
    if root_kind == "repo":
        return REPO_ROOT
    if root_kind == "legacy":
        return os.path.normpath(os.path.expandvars(legacy_root))
    return None


def tool_target_path(tool, legacy_root):
    """tools.json の path を絶対パスに変換する（存在確認はしない）。"""
    base = resolve_root(tool.get("root"), legacy_root)
    if base is None:
        return None
    rel = os.path.normpath(tool.get("path", "").replace("/", os.sep))
    return os.path.join(base, rel)


# ---------------------------------------------------------------------------
# 最新バージョンファイルの探索（kind == py / streamlit 用）
# ---------------------------------------------------------------------------
_VER_RE_3 = re.compile(r"(\d{8})_(\d{2})_(\d{2})\.py$", re.IGNORECASE)
_VER_RE_2 = re.compile(r"(\d{8})_(\d{2})\.py$", re.IGNORECASE)


def version_key(path):
    """ファイル名から (日付, メジャー, マイナー) を取り出す。

    対応形式:
        ツール名_yyyymmdd_NN.py     -> (yyyymmdd, NN, "00")
        ツール名_yyyymmdd_NN_MM.py  -> (yyyymmdd, NN, MM)
    いずれにも一致しない場合は最小値を返し、必ず他のファイルに負けるようにする。
    桁数が固定なので、文字列のまま比較しても日付順・版数順になる。
    """
    base = os.path.basename(path)
    m = _VER_RE_3.search(base)
    if m:
        return (m.group(1), m.group(2), m.group(3))
    m = _VER_RE_2.search(base)
    if m:
        return (m.group(1), m.group(2), "00")
    return ("00000000", "00", "00")


def find_latest_py(prefix_path):
    """prefix_path + "*.py" のうち、最も新しいバージョンのファイルを返す。

    旧ランチャーは "<prefix>*" で検索していたため .bat やフォルダまで候補に含めて
    いたが、ここでは拡張子を .py に限定している。

    Args:
        prefix_path: "C:\\...\\excel\\excel_VVCM_checker_" のような接頭辞つき絶対パス
    Returns:
        (最新ファイルの絶対パス, 候補件数) / 見つからなければ (None, 0)
    """
    candidates = [p for p in glob.glob(prefix_path + "*.py") if os.path.isfile(p)]
    if not candidates:
        return None, 0
    return max(candidates, key=version_key), len(candidates)


# ---------------------------------------------------------------------------
# ツールの起動
# ---------------------------------------------------------------------------
def child_env(work_dir):
    env = os.environ.copy()
    env["PYTHONPATH"] = work_dir
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def spawn(args, work_dir):
    """新しいコンソールウィンドウで子プロセスを起動する。

    args はリスト（引数を個別に渡す場合）と文字列（Windowsでコマンドラインを
    そのまま渡す場合）のどちらでもよい。文字列を使うのは `cmd /s /c "... || pause"`
    の形を崩さずに渡したいときだけで、ユーザー入力は一切連結していない。
    """
    flags = CREATE_NEW_CONSOLE if IS_WINDOWS else 0
    return subprocess.Popen(args, cwd=work_dir, env=child_env(work_dir),
                            creationflags=flags)


def launch_tool(tool, legacy_root):
    """tools.json の 1エントリを起動する。失敗時はログとダイアログで理由を示す。"""
    label = tool.get("label", tool.get("id", "(名称未設定)"))
    kind = tool.get("kind")
    target = tool_target_path(tool, legacy_root)

    if target is None:
        _fail(label, "root の指定が不正です（repo / legacy のいずれかを指定してください）: {}"
              .format(tool.get("root")))
        return

    log_message("▶ {} を起動します".format(label))

    if kind == "bat":
        if not os.path.isfile(target):
            _fail(label, "バッチファイルが見つかりません:\n{}".format(target))
            return
        work_dir = os.path.dirname(target)
        # Windows の CreateProcess は .bat を直接実行できないため cmd /c を介する。
        # shell=True は使わない（パスに空白や特殊文字が含まれる場合に危険なため）。
        args = ["cmd", "/c", target] if IS_WINDOWS else [target]
        _spawn_and_report(label, args, work_dir, os.path.basename(target))
        return

    if kind in ("py", "streamlit"):
        latest, count = find_latest_py(target)
        if latest is None:
            _fail(label,
                  "対象の .py ファイルが1件も見つかりません。\n\n"
                  "検索パターン:\n{}*.py\n\n"
                  "フォルダが移動・改名されていないか確認してください。".format(target))
            return
        work_dir = os.path.dirname(latest)
        log_message("🔍 最新版を選択: {}（候補 {} 件）".format(os.path.basename(latest), count))
        if kind == "streamlit":
            # streamlit アプリは python で直接実行できない。ランチャー自身と同じ
            # インタプリタを使うため、streamlit コマンドではなく -m 経由で起動する。
            inner = '"{}" -m streamlit run "{}"'.format(sys.executable, latest)
            plain = [sys.executable, "-m", "streamlit", "run", latest]
        else:
            inner = '"{}" "{}"'.format(sys.executable, latest)
            plain = [sys.executable, latest]

        if IS_WINDOWS:
            # 20260911_02: ツールが起動直後に落ちると、専用コンソールが一瞬で閉じて
            # エラー内容を読めなかった（OneNote要約ツールで実際に発生）。
            # cmd の `||` は直前のコマンドが異常終了したときだけ後ろを実行する演算子。
            # これで「成功時は今までどおり閉じる／失敗時だけ pause で残る」を両立する。
            # `/s` は「文字列の最初と最後の引用符だけを取り除き、中身はそのまま使う」
            # 指定。パスに空白が含まれていても壊れない。
            # .bat 起動（kind: bat）は各バッチが自前で pause するため、ここは通らない。
            args = 'cmd /s /c "{} || pause"'.format(inner)
        else:
            args = plain

        _spawn_and_report(label, args, work_dir, os.path.basename(latest))
        return

    _fail(label, "kind の指定が不正です（bat / py / streamlit のいずれか）: {}".format(kind))


def _spawn_and_report(label, args, work_dir, shown_name):
    log_message("📂 {}".format(work_dir))
    try:
        proc = spawn(args, work_dir)
    except OSError as e:
        _fail(label, "起動に失敗しました。\n\n対象: {}\nエラー: {}".format(shown_name, e))
        return
    log_message("✅ 起動完了: {}（PID: {}）".format(shown_name, proc.pid))


def _fail(label, detail):
    log_message("❌ {} を起動できません: {}".format(label, detail.replace("\n", " ")))
    messagebox.showerror("{} を起動できません".format(label), detail)


# ---------------------------------------------------------------------------
# 自動検出（tools.json に載っていない run_*.bat を拾う）
# ---------------------------------------------------------------------------
def scan_unregistered_bats(known_folders):
    """repo 配下1階層の run_*.bat のうち、tools.json 未登録のものを返す。

    20260911_03: 判定の単位を「.batファイル」から「フォルダ」に変更した。
    tools.json に載っているフォルダには補助用の .bat が同居していることが多く
    （po_database_organizer の run_po_pdf_merge.bat など）、ファイル単位で判定すると
    それらが毎回「未登録」に並んでしまう。また status:hidden のツールのフォルダも
    除外されず、非表示にしたはずのものが自動検出で復活していた。
    """
    found = []
    try:
        names = sorted(os.listdir(REPO_ROOT))
    except OSError as e:
        log_message("⚠️ リポジトリ配下を走査できません: {}".format(e))
        return found

    for name in names:
        folder = os.path.join(REPO_ROOT, name)
        if not os.path.isdir(folder) or name.startswith(".") or name == "tool_launcher":
            continue
        if os.path.normcase(os.path.abspath(folder)) in known_folders:
            continue
        for bat in sorted(glob.glob(os.path.join(folder, "run_*.bat"))):
            found.append({
                "id": "auto_{}_{}".format(name, os.path.basename(bat)),
                "label": "{} / {}".format(name, os.path.basename(bat)),
                "category": "unregistered",
                "root": "repo",
                "kind": "bat",
                "path": os.path.relpath(bat, REPO_ROOT).replace(os.sep, "/"),
                "gemini": "none",
                "status": "active",
            })
    return found


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------
class LauncherApp(object):

    def __init__(self, root, config):
        self.root = root
        self.config = config
        self.legacy_root = config.get("legacy_root", "")
        self.window_cfg = config.get("window", {})
        self.columns = int(self.window_cfg.get("columns", 4) or 4)
        self.pull_button = None
        self._setup_fonts()
        self._build()

    # -- フォント -----------------------------------------------------------
    def _setup_fonts(self):
        available = set(tkfont.families(self.root))

        def pick(candidates, fallback):
            for name in candidates:
                if name in available:
                    return name
            return fallback

        jp = pick(["Yu Gothic UI", "Meiryo UI", "Meiryo", "MS UI Gothic",
                   "Noto Sans CJK JP", "DejaVu Sans"], "TkDefaultFont")
        mono = pick(["Consolas", "MS Gothic", "DejaVu Sans Mono", "Courier New"],
                    "TkFixedFont")

        # 20260911_02: 実機で見づらいとの指摘を受け、全フォントを一律 +2pt した。
        self.f_logo = (jp, 17, "bold")
        self.f_meta = (mono, 10)
        self.f_cat = (jp, 11, "bold")
        self.f_tile = (jp, 12)
        self.f_badge = (mono, 9, "bold")
        self.f_btn = (jp, 12, "bold")
        self.f_log = (mono, 11)
        self.f_status = (mono, 10)
        # 小さめのボタン（⚙ tools.json / 終了）用。上と同じく +2pt。
        self.f_btn_small = (jp, 11)

    # -- 画面全体 -----------------------------------------------------------
    def _build(self):
        root = self.root
        root.title("{} - {}".format(self.window_cfg.get("title", "TOOL LAUNCHER"),
                                    os.path.basename(__file__)))
        root.geometry("{}x{}".format(int(self.window_cfg.get("width", 940)),
                                     int(self.window_cfg.get("height", 800))))
        root.minsize(720, 520)
        root.configure(bg=C_BG)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._build_header()
        self._build_board()
        self._build_log()
        self._build_status()

    def _build_header(self):
        bar = tk.Frame(self.root, bg=C_BAR)
        bar.pack(side="top", fill="x")
        inner = tk.Frame(bar, bg=C_BAR)
        inner.pack(fill="x", padx=20, pady=14)

        brand = tk.Frame(inner, bg=C_BAR)
        brand.pack(side="left", anchor="w")
        logo = tk.Frame(brand, bg=C_BAR)
        logo.pack(anchor="w")
        tk.Label(logo, text="⚡ TOOL ", bg=C_BAR, fg=C_INK,
                 font=self.f_logo).pack(side="left")
        tk.Label(logo, text="LAUNCHER", bg=C_BAR, fg=C_ACCENT,
                 font=self.f_logo).pack(side="left")

        self.meta_label = tk.Label(brand, text="", bg=C_BAR, fg=C_INK3,
                                   font=self.f_meta, anchor="w")
        self.meta_label.pack(anchor="w", pady=(3, 0))

        right = tk.Frame(inner, bg=C_BAR)
        right.pack(side="right", anchor="e")

        tk.Button(right, text="⚙ tools.json", command=self.open_tools_json,
                  bg=C_BAR, fg=C_INK2, font=self.f_btn_small,
                  activebackground=C_TILE, activeforeground=C_INK,
                  relief="solid", bd=1, padx=12, pady=4,
                  highlightthickness=0, cursor="hand2").pack(side="left", padx=(0, 8))

        self.pull_button = tk.Button(right, text="🔄 更新", command=self.on_git_pull,
                                     bg=C_ACCENT, fg="#ffffff", font=self.f_btn,
                                     activebackground=C_ACCENT_DIM,
                                     activeforeground="#ffffff",
                                     relief="flat", bd=0, padx=18, pady=5,
                                     highlightthickness=0, cursor="hand2")
        self.pull_button.pack(side="left")

    def _build_board(self):
        wrap = tk.Frame(self.root, bg=C_BG)
        wrap.pack(side="top", fill="both", expand=True)

        canvas = tk.Canvas(wrap, bg=C_BG, highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(wrap, orient="vertical", command=canvas.yview,
                                 bg=C_BAR, troughcolor=C_BG, bd=0,
                                 highlightthickness=0, activebackground=C_ACCENT_DIM)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        board = tk.Frame(canvas, bg=C_BG)
        window_id = canvas.create_window((0, 0), window=board, anchor="nw")

        board.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfigure(window_id, width=e.width))

        def on_wheel(event):
            canvas.yview_scroll(-1 * int(event.delta / 120), "units")

        canvas.bind_all("<MouseWheel>", on_wheel)

        self._render_categories(board)

    def _render_categories(self, board):
        categories = self.config.get("categories", [])
        tools = [t for t in self.config.get("tools", [])
                 if t.get("status") != "hidden"]

        # 自動検出から除外するフォルダ。status:hidden も含めた「tools.json に
        # 載っている全ツール」を対象にする（hidden を除外し忘れると、非表示に
        # したツールが「未登録」として復活してしまうため）。
        known_folders = set()
        for tool in self.config.get("tools", []):
            if tool.get("root") != "repo":
                continue
            path = tool_target_path(tool, self.legacy_root)
            if path:
                known_folders.add(os.path.normcase(os.path.abspath(os.path.dirname(path))))

        auto = scan_unregistered_bats(known_folders)
        if auto:
            categories = list(categories) + [{"id": "unregistered", "label": "⚙ 未登録"}]
            tools = list(tools) + auto
            log_message("🔎 tools.json 未登録の run_*.bat を {} 件検出しました".format(len(auto)))

        shown = 0
        for category in categories:
            members = [t for t in tools if t.get("category") == category.get("id")]
            if not members:
                continue
            self._render_one_category(board, category, members)
            shown += len(members)

        orphans = [t for t in tools
                   if t.get("category") not in {c.get("id") for c in categories}]
        if orphans:
            self._render_one_category(board, {"id": "other", "label": "❓ 分類なし"}, orphans)
            shown += len(orphans)

        repo_count = sum(1 for t in tools if t.get("root") == "repo")
        legacy_count = sum(1 for t in tools if t.get("root") == "legacy")
        self.meta_label.configure(
            text="{} tools  ·  repo {} / legacy {}  ·  v{}".format(
                shown, repo_count, legacy_count, VERSION))
        log_message("🚀 ツールランチャーを起動しました（{} 件を読み込み）".format(shown))

    def _render_one_category(self, board, category, members):
        block = tk.Frame(board, bg=C_BG)
        block.pack(fill="x", padx=20, pady=(14, 0))

        head = tk.Frame(block, bg=C_BG)
        head.pack(fill="x", pady=(0, 8))
        tk.Label(head, text=category.get("label", ""), bg=C_BG, fg=C_INK2,
                 font=self.f_cat).pack(side="left")
        tk.Frame(head, bg=C_LINE_SOFT, height=1).pack(
            side="left", fill="x", expand=True, padx=10)
        tk.Label(head, text=str(len(members)), bg=C_BG, fg=C_INK3,
                 font=self.f_meta).pack(side="right")

        grid = tk.Frame(block, bg=C_BG)
        grid.pack(fill="x")
        for col in range(self.columns):
            grid.grid_columnconfigure(col, weight=1, uniform="tool")

        for index, tool in enumerate(members):
            tile = self._make_tile(grid, tool)
            tile.grid(row=index // self.columns, column=index % self.columns,
                      sticky="nsew", padx=(0, 9), pady=(0, 9))

    # -- タイル -------------------------------------------------------------
    def _make_tile(self, parent, tool):
        stripe_color = GEMINI_STRIPE.get(tool.get("gemini"), C_LINE)

        outer = tk.Frame(parent, bg=C_TILE, highlightthickness=1,
                         highlightbackground=C_LINE_SOFT, highlightcolor=C_LINE_SOFT,
                         cursor="hand2")
        stripe = tk.Frame(outer, bg=stripe_color, width=3)
        stripe.pack(side="left", fill="y")
        stripe.pack_propagate(False)

        body = tk.Frame(outer, bg=C_TILE)
        body.pack(side="left", fill="both", expand=True, padx=(9, 10), pady=(9, 8))

        name = tk.Label(body, text=tool.get("label", ""), bg=C_TILE, fg=C_INK,
                        font=self.f_tile, anchor="nw", justify="left",
                        wraplength=210, height=2)
        name.pack(fill="x")

        tags = tk.Frame(body, bg=C_TILE)
        tags.pack(fill="x", anchor="w", pady=(7, 0))

        painted = [outer, body, name, tags]

        kind_badge = KIND_BADGE.get(tool.get("kind"))
        if kind_badge:
            painted.append(self._add_badge(tags, *kind_badge))

        gemini_badge = GEMINI_BADGE.get(tool.get("gemini"))
        if gemini_badge:
            painted.append(self._add_badge(tags, *gemini_badge))

        if tool.get("status") == "planned_move":
            painted.append(self._add_badge(tags, "移管予定", C_MOVE, "#4a3f8a"))

        def on_enter(_event=None):
            for widget in painted:
                widget.configure(bg=C_TILE_HI)
            outer.configure(highlightbackground=C_ACCENT, highlightcolor=C_ACCENT)
            stripe.configure(bg=C_ACCENT)
            name.configure(fg="#ffffff")

        def on_leave(_event=None):
            for widget in painted:
                widget.configure(bg=C_TILE)
            outer.configure(highlightbackground=C_LINE_SOFT, highlightcolor=C_LINE_SOFT)
            stripe.configure(bg=stripe_color)
            name.configure(fg=C_INK)

        def on_click(_event=None):
            launch_tool(tool, self.legacy_root)

        for widget in painted + [stripe]:
            widget.bind("<Enter>", on_enter)
            widget.bind("<Leave>", on_leave)
            widget.bind("<Button-1>", on_click)

        return outer

    def _add_badge(self, parent, text, fg, border):
        badge = tk.Label(parent, text=text, bg=C_TILE, fg=fg, font=self.f_badge,
                         padx=4, pady=0, highlightthickness=1,
                         highlightbackground=border, highlightcolor=border)
        badge.pack(side="left", padx=(0, 4))
        return badge

    # -- ログ枠 -------------------------------------------------------------
    def _build_log(self):
        global _log_widget

        pane = tk.Frame(self.root, bg=C_LOG_BG, highlightthickness=1,
                        highlightbackground=C_LINE)
        pane.pack(side="top", fill="x")

        head = tk.Frame(pane, bg=C_LOG_BG)
        head.pack(fill="x", padx=20, pady=(8, 4))
        tk.Label(head, text="LOG", bg=C_LOG_BG, fg=C_INK3,
                 font=self.f_meta).pack(side="left")
        tk.Label(head, text="launcher_log.txt", bg=C_LOG_BG, fg=C_INK3,
                 font=self.f_meta).pack(side="right")

        box = tk.Frame(pane, bg=C_LOG_BG)
        box.pack(fill="x", padx=20, pady=(0, 10))

        scrollbar = tk.Scrollbar(box, orient="vertical", bg=C_BAR,
                                 troughcolor=C_LOG_BG, bd=0, highlightthickness=0)
        scrollbar.pack(side="right", fill="y")

        text = tk.Text(box, height=6, bg=C_LOG_BG, fg=C_INK2, font=self.f_log,
                       bd=0, highlightthickness=0, wrap="word", relief="flat",
                       insertbackground=C_INK, yscrollcommand=scrollbar.set)
        text.pack(side="left", fill="x", expand=True)
        scrollbar.configure(command=text.yview)
        text.configure(state="disabled")

        _log_widget = text
        for line in _log_backlog:
            _append_to_log_widget(line)
        del _log_backlog[:]

    # -- ステータスバー -----------------------------------------------------
    def _build_status(self):
        bar = tk.Frame(self.root, bg=C_BAR)
        bar.pack(side="top", fill="x")
        inner = tk.Frame(bar, bg=C_BAR)
        inner.pack(fill="x", padx=20, pady=6)

        tk.Label(inner, text="python {} · {}".format(
                     ".".join(str(n) for n in sys.version_info[:3]), sys.executable),
                 bg=C_BAR, fg=C_INK3, font=self.f_status, anchor="w").pack(side="left")

        tk.Button(inner, text="終了", command=self.on_close,
                  bg=C_BAR, fg=C_ACCENT, font=self.f_btn_small,
                  activebackground=C_ACCENT_DIM, activeforeground="#ffffff",
                  relief="solid", bd=1, padx=16, pady=2,
                  highlightthickness=0, cursor="hand2").pack(side="right")

    # -- 操作 ---------------------------------------------------------------
    def open_tools_json(self):
        """tools.json を既定のエディタで開く（ツールの増減・並べ替え用）。"""
        log_message("⚙ tools.json を開きます: {}".format(TOOLS_JSON))
        try:
            if IS_WINDOWS:
                os.startfile(TOOLS_JSON)  # noqa: S606 - ユーザー操作による明示的な起動
            else:
                subprocess.Popen(["xdg-open", TOOLS_JSON])
        except OSError as e:
            _fail("tools.json", "ファイルを開けませんでした。\n\n{}".format(e))

    def latest_launcher_name(self):
        latest, _ = find_latest_py(os.path.join(SCRIPT_DIR, "tool_launcher_"))
        return os.path.basename(latest) if latest else None

    def on_git_pull(self):
        """git pull --ff-only を実行する。失敗しても自動修復は一切行わない。"""
        self.pull_button.configure(state="disabled", text="🔄 更新中...")
        log_message("🔄 git pull --ff-only を実行します（{}）".format(REPO_ROOT))
        before = self.latest_launcher_name()

        def work():
            try:
                result = subprocess.run(
                    ["git", "pull", "--ff-only"],
                    cwd=REPO_ROOT, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=180,
                    creationflags=(CREATE_NO_WINDOW if IS_WINDOWS else 0))
            except Exception as e:  # FileNotFoundError / TimeoutExpired など
                self.root.after(0, lambda: self._pull_failed(e))
                return
            self.root.after(0, lambda: self._pull_finished(result, before))

        threading.Thread(target=work, daemon=True).start()

    def _pull_failed(self, error):
        self.pull_button.configure(state="normal", text="🔄 更新")
        if isinstance(error, FileNotFoundError):
            detail = ("git コマンドが見つかりません。\n"
                      "Git for Windows がインストールされ、PATHが通っているか確認してください。")
        elif isinstance(error, subprocess.TimeoutExpired):
            detail = "git pull が 180 秒以内に終わりませんでした。ネットワークを確認してください。"
        else:
            detail = str(error)
        log_message("❌ 更新に失敗しました: {}".format(detail.replace("\n", " ")))
        messagebox.showerror("更新に失敗しました", detail)

    def _pull_finished(self, result, before):
        self.pull_button.configure(state="normal", text="🔄 更新")

        for line in (result.stdout or "").splitlines():
            if line.strip():
                log_message("   {}".format(line.rstrip()))
        for line in (result.stderr or "").splitlines():
            if line.strip():
                log_message("   {}".format(line.rstrip()))

        if result.returncode != 0:
            # 競合・認証エラー等はそのまま表示し、stash や reset は行わない（設計判断: 案A）。
            log_message("❌ 更新に失敗しました（終了コード {}）。手動で対処してください。"
                        .format(result.returncode))
            messagebox.showerror(
                "更新に失敗しました",
                "git pull --ff-only が失敗しました（終了コード {}）。\n\n"
                "内容はログ枠に表示しています。競合や未コミットの変更がある場合は、\n"
                "コマンドプロンプトで手動で対処してください。\n\n"
                "自動での退避（stash）やリセットは行いません。".format(result.returncode))
            return

        log_message("✅ 更新が完了しました")

        after = self.latest_launcher_name()
        if after and before and after != before:
            log_message("♻️ ランチャー本体が更新されました: {} → {}".format(before, after))
            if messagebox.askyesno(
                    "ランチャーを再起動します",
                    "ランチャー本体が新しいバージョンに更新されました。\n\n"
                    "{} → {}\n\n"
                    "いま再起動しますか？".format(before, after)):
                self.restart()
        else:
            messagebox.showinfo("更新が完了しました",
                                "リポジトリを最新の状態にしました。\n"
                                "詳細はログ枠を確認してください。")

    def restart(self):
        """新しいランチャーを起動して自分は終了する。"""
        if not os.path.isfile(RESTART_BAT):
            _fail("再起動", "起動用バッチが見つかりません:\n{}".format(RESTART_BAT))
            return
        log_message("♻️ ランチャーを再起動します")
        # 新プロセスが多重起動チェックで弾かれないよう、先にミューテックスを解放する。
        release_single_instance()
        try:
            flags = CREATE_NEW_CONSOLE if IS_WINDOWS else 0
            args = ["cmd", "/c", RESTART_BAT] if IS_WINDOWS else [RESTART_BAT]
            subprocess.Popen(args, cwd=SCRIPT_DIR, creationflags=flags)
        except OSError as e:
            _fail("再起動", "再起動に失敗しました。\n\n{}".format(e))
            return
        self.root.destroy()

    def on_close(self):
        log_message("🔚 ツールランチャーを終了します")
        release_single_instance()
        self.root.destroy()


# ---------------------------------------------------------------------------
# エントリポイント
# ---------------------------------------------------------------------------
def main():
    root = tk.Tk()
    root.withdraw()

    if not acquire_single_instance():
        messagebox.showwarning(
            "すでに起動しています",
            "ツールランチャーはすでに起動しています。\n"
            "タスクバーで既存のウィンドウを確認してください。")
        root.destroy()
        return 0

    config = load_config()
    if config is None:
        release_single_instance()
        root.destroy()
        return 1

    app = LauncherApp(root, config)

    def report_callback_exception(exc_type, exc_value, exc_tb):
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        log_message("🚨 予期しないエラー: {}".format(exc_value))
        messagebox.showerror("予期しないエラー",
                             "処理中にエラーが発生しました。\n\n{}".format(text))

    root.report_callback_exception = report_callback_exception

    root.deiconify()
    # GUIが無事に組み上がってからコンソールを隠す。組み上がる前に落ちた場合は
    # コンソールが残るため、traceback をそのまま読める。
    hide_console()
    root.mainloop()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        show_console()
        traceback.print_exc()
        try:
            log_message("🚨 起動に失敗しました: {}".format(
                traceback.format_exc().splitlines()[-1]))
        except Exception:
            pass
        sys.exit(1)
