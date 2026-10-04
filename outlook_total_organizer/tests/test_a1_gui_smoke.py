# -*- coding: utf-8 -*-
"""A1 判断待ち: GUI スモークテスト (MailManagerGUI の「⚖️ 判断待ち」パネル)。

tkinter が無い / ディスプレイが無い場合は自動でスキップ (SkipTest)。
Linux では  xvfb-run -a /usr/bin/python3.12 tests/run_tests.py  で実行できる。

MailManagerGUI.__init__ は呼ばず __new__ で作り、必要最小の属性だけを手で設定して
_ui_action_decision_panel(parent) を呼ぶ。Outlook(COM)・AI・ネットワークには一切触れない
(outlook は記録用スタブ。触れたら AttributeError で落ちる)。

【仕様書に無いため推測した点】 ボタン/Treeview/ラベルのウィジェット名・ハンドラ名は仕様に無いので、
ウィジェットツリーを走査して「ボタンの文言」「Treeview」「ラベルの文言」で探す。
ダブルクリックは Tk が <Double-1> の event_generate を許さないため、ButtonPress/Release を2回送る。

【重要】 別スレッドから root.after() を呼ぶには、メインスレッドが mainloop() の中に居る必要がある
(root.update() のループだと "main thread is not in main loop" になる)。
そのため待機は「after で条件を監視し、満たしたら root.quit() する mainloop」で行う (pump)。

クラス名に SpecGap を含むものは、仕様が曖昧/未記載のため自然な解釈で書いたもの。
"""
import os
import threading
import time
import unittest
from datetime import datetime, timedelta
from unittest import mock

import _loader
from _loader import (
    CACHE_PATH, LAST_RUN_PATH, STATUS_PATH, make_action, make_cache, make_last_run, make_status,
    make_thread, read_bytes, read_json, tempdir_cwd, write_json, write_text,
)

try:
    import tkinter as tk
    from tkinter import ttk
    import tkinter.messagebox as tkmessagebox
    _TK_IMPORT_ERROR = None
except Exception as _e:                                    # pragma: no cover
    tk = ttk = tkmessagebox = None
    _TK_IMPORT_ERROR = _e

BASE = "📋 アクション"
NOTICE_HEAD = "※解析済みの受信トレイ直下のメールだけを数えています。"      # 常設の注意文 (仕様変更第2回) の冒頭
OLDER_LINE_7_1 = "📅 7日より前に届いた未対応が1件あります（「🕰 古い案件も表示」で確認できます）。"
_SKIP_REASON = "unset"


def oto():
    return _loader.load()


def _gui_skip_reason():
    """tkinter が使えない/ディスプレイが無いときの理由 (使えれば None)。1回だけ判定する。"""
    global _SKIP_REASON
    if _SKIP_REASON != "unset":
        return _SKIP_REASON
    if tk is None:
        _SKIP_REASON = f"tkinter が import できない ({_TK_IMPORT_ERROR})"
    elif getattr(tk, "__a1_stub__", False) or getattr(tkmessagebox, "__a1_stub__", False):
        _SKIP_REASON = "tkinter が実環境に無い (_loader のスタブで代替しているため GUI テストは実行できない)"
    else:
        try:
            r = tk.Tk()
            r.destroy()
            _SKIP_REASON = None
        except Exception as e:                              # TclError (no display) など
            _SKIP_REASON = f"ディスプレイが使えない ({e})。Linux は xvfb-run -a を付けて実行してください"
    return _SKIP_REASON


# ============================================================
# スタブ
# ============================================================
class StubOutlook:
    """Outlook(COM) の代わり。user_name/user_smtp_address と show_thread_in_explorer だけを持つ。
    それ以外の属性に触れたら AttributeError (= GUI が COM に触れた疑い)。"""

    def __init__(self, user_name="Ochi, Yuichi", user_smtp_address="yuichi.ochi@example.com"):
        self.user_name = user_name
        self.user_smtp_address = user_smtp_address
        self.explorer_calls = []
        self.explorer_event = threading.Event()
        self.period_calls = []

    def show_thread_in_explorer(self, topic, entry_id):
        cur = threading.current_thread()
        self.explorer_calls.append({"topic": topic, "entry_id": entry_id,
                                    "in_main_thread": cur is threading.main_thread(),
                                    "daemon": cur.daemon})
        self.explorer_event.set()

    # --- _run_action_dashboard 用 (既存コードが呼ぶ) -------------------
    def get_relevant_mails_for_period(self, days, progress_callback=None):
        self.period_calls.append(days)
        return []

    def group_by_thread(self, mails):
        return {}

    def __getattr__(self, name):
        raise AttributeError(f"StubOutlook に {name} は無い (GUIがOutlook/COMに触れた疑い)")


class StubSummarizer:
    total_input_tokens = 0
    total_output_tokens = 0

    def __init__(self, fail=None):
        self.fail = fail
        self.calls = []

    def summarize_action_dashboard(self, threads, progress_callback=None, reset_conversation_ids=None,
                                   expand_from_cache=False):
        self.calls.append({"threads": threads, "reset": reset_conversation_ids, "expand": expand_from_cache})
        if self.fail:
            raise self.fail
        return {"threads": [], "action_cards": []}


class StubReporter:
    def __init__(self, fail=None):
        self.fail = fail
        self.calls = []

    def generate_action_dashboard_report(self, action_cards, date_range, total_input, total_output,
                                         reformat_mode=False, search_days=7):
        self.calls.append({"date_range": date_range, "search_days": search_days})
        if self.fail:
            raise self.fail
        return None                                      # None → webbrowser.open しない


class _Boom:
    def __init__(self, label):
        self._label = label

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        raise AssertionError(f"GUI(A1)が {self._label}.{name} に触れた (COM/AI/ネットワーク禁止)")

    def __call__(self, *a, **k):
        raise AssertionError(f"GUI(A1)が {self._label} を呼んだ (COM/AI/ネットワーク禁止)")


# ============================================================
# 合成データ
# ============================================================
def make_row(cid="C1", idx=0, **kw):
    row = {
        "key": oto().make_action_key_by_index(cid, idx), "cid": cid, "topic": f"AI件名{cid}",
        "real_topic": f"実件名{cid}", "entry_id": f"ENTRY-{cid}", "latest_ts": 1_790_000_000,
        "date_mmdd": "10/04 10:00", "importance": "高", "owner": f"依頼者{cid}", "target": "あなた",
        "action": f"{cid} の予算を承認してください", "deadline": "10/10", "ai_status": "返信待ち",
        "progress": "not_started", "priority": "", "comment": "",
        "resurfaced": False, "is_decision": True,          # 仕様変更(第2回)
    }
    row.update(kw)
    return row


def make_snapshot(rows, heading=None, status_text=None, older_rows="auto", heading_compact=None, **kw):
    n = None if rows is None else len(rows)
    if older_rows == "auto":
        older_rows = [] if rows is not None else None
    snap = {
        "rows": rows, "pending_count": n, "error_count": 0,
        "last_run": {"finished_at": "2026-10-04T10:00:00", "days": 7, "period_label": "1週間"},
        "stale": False, "freshness_unknown": False,
        "heading": heading if heading is not None else f"{BASE} (判断待ち{n if n is not None else '?'}・解析1時間前)",
        "status_text": status_text if status_text is not None else
        f"最終解析: 10/04 10:00（範囲: 1週間）／ 判断待ち: {n}件 {NOTICE_HEAD}",
        "since_ts": 1_789_000_000.0,
        # 仕様変更(第2回) の追加キー
        "older_rows": older_rows, "others_count": 0, "partial": False, "horizon_days": 7,
        "heading_compact": heading_compact if heading_compact is not None else f"{BASE} ⚖{n if n is not None else '!'}",
    }
    snap.update(kw)
    return snap


def walk(widget):
    yield widget
    for c in widget.winfo_children():
        yield from walk(c)


# ============================================================
# 共通フィクスチャ
# ============================================================
class GuiCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reason = _gui_skip_reason()
        if reason:
            raise unittest.SkipTest(reason)

    def setUp(self):
        cm = tempdir_cwd()
        cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        self.dialogs = []                 # messagebox 呼び出しの記録 (関数名, 引数, キーワード)
        self.callback_errors = []         # Tk コールバックの未処理例外
        self.thread_errors = []           # ワーカースレッドの未処理例外
        # (A1.1) 旧版にあった「_run_action_dashboard の except 節の lambda が except 変数 e を参照して
        # after(0) 実行時に NameError になる」既知バグは修正済みのため、Tk コールバックの未処理例外は
        # (NameError も含め) すべて失敗として扱う。許容用のフラグ (tolerate_known_closure_bug) は廃止した。
        self._patch_messagebox()
        self._patch_thread_excepthook()
        self.baseline_threads = set(threading.enumerate())
        self.gui = None
        self.stub_outlook = None
        self.addCleanup(self._teardown_gui)

    # ---- パッチ -------------------------------------------------------
    def _patch_messagebox(self):
        ask_defaults = {"askquestion": "yes", "askokcancel": True, "askyesno": True,
                        "askyesnocancel": True, "askretrycancel": False}
        names = ("showinfo", "showwarning", "showerror") + tuple(ask_defaults)
        for name in names:
            def rec(*args, _name=name, **kwargs):
                self.dialogs.append((_name, args, kwargs))
                return ask_defaults.get(_name, "ok")
            p = mock.patch.object(tkmessagebox, name, rec)
            p.start()
            self.addCleanup(p.stop)

    def _patch_thread_excepthook(self):
        orig = threading.excepthook

        def hook(args):
            self.thread_errors.append(f"{args.exc_type.__name__}: {args.exc_value}")
        threading.excepthook = hook
        self.addCleanup(lambda: setattr(threading, "excepthook", orig))

    def dialog_text(self, kinds=None):
        out = []
        for name, args, kwargs in self.dialogs:
            if kinds and name not in kinds:
                continue
            out.append(" ".join(str(a) for a in list(args) + list(kwargs.values())))
        return "\n".join(out)

    # ---- GUI 構築 -----------------------------------------------------
    def make_gui(self, select_action=False, existing_widget=False, user_name="Ochi, Yuichi",
                 smtp="yuichi.ochi@example.com", build_panel=True, map_window=True):
        mod = oto()
        gui = mod.MailManagerGUI.__new__(mod.MailManagerGUI)
        root = tk.Tk()
        root.geometry("1100x800+0+0")
        root.report_callback_exception = lambda exc, val, tb: self.callback_errors.append(
            f"{exc.__name__}: {val}")
        gui.root = root
        gui.notebook = ttk.Notebook(root)
        gui.notebook.pack(fill=tk.BOTH, expand=True)
        gui.tab_search = ttk.Frame(gui.notebook)
        gui.tab_action = ttk.Frame(gui.notebook)
        gui.notebook.add(gui.tab_search, text="🔍 検索 / 整理")
        gui.notebook.add(gui.tab_action, text="📋 アクション")
        gui.outlook = self.stub_outlook = StubOutlook(user_name, smtp)
        gui.summarizer = StubSummarizer()
        gui.reporter = StubReporter()
        gui.v_action_prd = tk.StringVar(master=root, value="1週間")
        gui.v_action_sync_vba = tk.BooleanVar(master=root, value=False)
        gui.lbl_stat = ttk.Label(root, text="Ready")
        gui.lbl_stat.pack(side=tk.BOTTOM, fill=tk.X)
        gui.btn_run_action = ttk.Button(root, text="📋 アクション一覧を生成")
        gui.btn_update_action = ttk.Button(root, text="🔄 解析のみ更新")          # A1.1: 解析のみ更新ボタン
        gui.btn_reformat_action = ttk.Button(root, text="🎨 フォーマットのみ再生成")
        # 実機の MailManagerGUI.__init__ は self.config = load_config() を持つ。A1.1 の _run_action_dashboard が
        # config の gemini_model を読む (費用の事前見積り・実績ログ用) ので、__new__ で作るスタブにも用意する。
        # (load_config() は json/ を作ってしまうため使わず、既定値のコピーを置く。モデルを変えたいテストは書き換える)
        gui.config = dict(oto().DEFAULT_CONFIG)
        gui.threads = {}
        gui.selected = set()
        self.gui = gui
        if select_action:
            gui.notebook.select(gui.tab_action)
        if map_window:
            root.update()
        self.existing = None
        if existing_widget:
            self.existing = ttk.Label(gui.tab_action, text="既存ウィジェット(アクション生成ボタン等)")
            self.existing.pack(fill=tk.X)
            if map_window:
                root.update()
        if build_panel:
            gui._ui_action_decision_panel(gui.tab_action)
            if map_window:
                root.update()
        return gui

    def _teardown_gui(self):
        problems = []
        gui = self.gui
        if gui is not None:
            try:
                # 保留中のイベント (例: <<NotebookTabChanged>> → 再読込のワーカー起動) を先に流してから、
                # ワーカーの終了を待つ (流さないと、待機判定の直後にワーカーが起動して取りこぼす)
                self.settle(0.2)
                self.pump(lambda: not self.worker_threads(), timeout=5)
                self.settle(0.1)
                self.pump(lambda: not self.worker_threads(), timeout=5)
            except Exception as e:                          # noqa: BLE001
                problems.append(f"終了待ちで例外: {e!r}")
            if self.worker_threads():
                problems.append(f"ワーカースレッドが終わらない: {self.worker_threads()}")
            try:
                for aid in gui.root.tk.splitlist(gui.root.tk.call("after", "info")):
                    gui.root.after_cancel(aid)                # 破棄後に発火して "invalid command name" を出さない
            except Exception:                               # noqa: BLE001
                pass
            try:
                gui.root.destroy()
            except Exception:                               # noqa: BLE001
                pass
        if self.callback_errors:
            problems.append(f"Tkコールバックの未処理例外: {self.callback_errors}")
        if self.thread_errors:
            problems.append(f"ワーカースレッドの未処理例外: {self.thread_errors}")
        if problems:
            self.fail("\n".join(problems))

    def worker_threads(self):
        me = threading.current_thread()
        return [t for t in threading.enumerate()
                if t.is_alive() and t is not me and t not in self.baseline_threads]

    # ---- 待機 (mainloop + quit) --------------------------------------
    def pump(self, cond, timeout=5.0, interval=10):
        """cond() が真になるか timeout 秒まで mainloop を回す。真になれば True。"""
        root = self.gui.root
        deadline = time.monotonic() + timeout
        state = {"ok": False}

        def tick():
            try:
                ok = cond()
            except Exception as e:                          # noqa: BLE001
                state["err"] = e
                root.quit()
                return
            if ok:
                state["ok"] = True
                root.quit()
            elif time.monotonic() >= deadline:
                root.quit()
            else:
                root.after(interval, tick)

        root.after(0, tick)
        root.mainloop()
        if "err" in state:
            raise state["err"]
        return state["ok"]

    def settle(self, seconds=0.15):
        end = time.monotonic() + seconds
        self.pump(lambda: time.monotonic() >= end, timeout=seconds + 3)

    # ---- ウィジェット探索 ---------------------------------------------
    def panel(self):
        found = [w for w in walk(self.gui.tab_action)
                 if isinstance(w, (ttk.LabelFrame, tk.LabelFrame)) and "判断待ち" in str(w.cget("text"))]
        self.assertEqual(len(found), 1, f"LabelFrame「判断待ち」が {len(found)} 個ある")
        return found[0]

    def tree(self):
        found = [w for w in walk(self.panel()) if isinstance(w, ttk.Treeview)]
        self.assertEqual(len(found), 1, f"Treeview が {len(found)} 個ある")
        return found[0]

    def button(self, fragment):
        found = [w for w in walk(self.panel()) if isinstance(w, (ttk.Button, tk.Button))
                 and fragment in str(w.cget("text"))]
        self.assertEqual(len(found), 1, f"ボタン「{fragment}」が {len(found)} 個ある")
        return found[0]

    def old_checkbox(self):
        found = [w for w in walk(self.panel()) if isinstance(w, (ttk.Checkbutton, tk.Checkbutton))
                 and "古い案件" in str(w.cget("text"))]
        self.assertEqual(len(found), 1, f"チェックボタン「古い案件も表示」が {len(found)} 個ある")
        return found[0]

    def progress_cell(self, iid):
        """行の「進捗」列の表示文字列。"""
        tree = self.tree()
        cols = list(tree["columns"])
        idx = [i for i, c in enumerate(cols) if "進捗" in str(tree.heading(c, "text"))]
        self.assertEqual(len(idx), 1, f"「進捗」列が {len(idx)} 個ある: {cols}")
        return str(tree.item(iid, "values")[idx[0]])

    def label_texts(self, root_widget=None):
        base = root_widget or self.panel()
        return [str(w.cget("text")) for w in walk(base) if isinstance(w, (ttk.Label, tk.Label, tk.Message))]

    def tab_text(self):
        return self.gui.notebook.tab(self.gui.tab_action, "text")

    def row_ids(self):
        return list(self.tree().get_children())

    def row_text(self, iid):
        return " | ".join(str(v) for v in self.tree().item(iid, "values"))

    def select(self, *iids):
        self.tree().selection_set(iids)
        self.settle(0.1)

    def double_click_row(self, iid):
        tree = self.tree()
        tree.see(iid)
        self.gui.root.update()
        bbox = tree.bbox(iid)
        self.assertTrue(bbox, "行がビューに表示されていない (タブが非表示?)")
        x, y, w, h = bbox
        cx, cy = x + min(max(w - 1, 1), 12), y + h // 2
        for _ in range(2):                                   # <Double-1> は event_generate 不可 → 2回クリック
            tree.event_generate("<ButtonPress-1>", x=cx, y=cy)
            tree.event_generate("<ButtonRelease-1>", x=cx, y=cy)
        self.gui.root.update()

    def apply(self, snapshot):
        self.gui._apply_action_decision_view(snapshot)
        self.gui.root.update()

    # ---- 実ファイルを使うシナリオ --------------------------------------
    def key(self, cid, idx=0):
        return oto().make_action_key_by_index(cid, idx)

    def seed_files(self, statuses=None, cids=("A", "B", "C"), last_run=True):
        """A,B,C の3スレッド (判断待ち)。B は in_progress 済み。並びは 新しい順 A,B,C。"""
        now_ts = int(time.time())
        threads = {}
        for i, cid in enumerate(cids):
            threads[cid] = make_thread(
                [make_action(owner=f"依頼者{cid}", action=f"{cid}の予算を承認してください")],
                topic=f"AI件名{cid}", real_topic=f"実件名{cid}", latest_ts=now_ts - 3600 * (i + 1),
                entry_id=f"ENTRY-{cid}")
        write_json(CACHE_PATH, make_cache(threads))
        if statuses is None:
            statuses = {self.key("B"): make_status("in_progress", "", "bメモ")}
        write_json(STATUS_PATH, statuses)
        if last_run:
            write_json(LAST_RUN_PATH, make_last_run(datetime.now() - timedelta(minutes=90)))
        return threads

    def load_real(self, expect_rows=3):
        """実の snapshot を使って一覧を読み込む (_refresh_action_decision_view)。"""
        self.gui._refresh_action_decision_view()
        ok = self.pump(lambda: len(self.row_ids()) == expect_rows, timeout=8)
        self.assertTrue(ok, f"一覧が {expect_rows} 行にならない: {self.row_ids()}")

    def setup_loaded(self):
        """A,B,C の3行を実ファイル・実snapshotで読み込んだ状態にする。"""
        self.seed_files()
        self.make_gui(select_action=True)
        self.load_real(3)
        self.assertEqual(self.row_ids(), [self.key("A"), self.key("B"), self.key("C")])

    def last_op_previous(self):
        """_action_decision_last_op から「更新前progressの {key: previous}」を取り出す。
        仕様は「戻り値を保存」。戻り値そのもの / {"previous": 戻り値, ...} のラッパのどちらでも読めるようにする。"""
        op = getattr(self.gui, "_action_decision_last_op", None)
        if isinstance(op, dict) and isinstance(op.get("previous"), dict):
            return op["previous"]
        return op


# ============================================================
# パネルの構築
# ============================================================
class TestPanelBuild(GuiCase):
    def test_labelframe_tree_buttons_exist(self):
        self.make_gui()
        panel = self.panel()
        self.assertIn("判断待ち", str(panel.cget("text")))
        self.assertIsNotNone(self.tree())
        for frag in ("再読込", "完了にする", "無視する", "元に戻す"):
            self.button(frag)

    def test_tree_columns_headings_selectmode(self):
        self.make_gui()
        tree = self.tree()
        labels = ["進捗", "優先", "件名", "依頼者", "依頼内容", "期限", "受信"]
        cols = list(tree["columns"])
        self.assertEqual(len(cols), 7, f"列数が7でない: {cols}")
        for label, col in zip(labels, cols):
            self.assertIn(label, str(tree.heading(col, "text")), f"列 {col} の見出しに {label} が無い")
        self.assertEqual(str(tree.cget("selectmode")), "extended")

    def test_vertical_scrollbar_is_connected(self):
        self.make_gui()
        bars = [w for w in walk(self.panel()) if isinstance(w, ttk.Scrollbar)
                and str(w.cget("orient")) == "vertical"]
        self.assertTrue(bars, "縦スクロールバーが無い")
        self.assertTrue(str(self.tree().cget("yscrollcommand")).strip(), "Treeview にスクロールバーが連動していない")

    def test_panel_is_placed_below_existing_widgets(self):
        self.make_gui(select_action=True, existing_widget=True)
        self.gui.root.update()
        existing_bottom = self.existing.winfo_rooty() + self.existing.winfo_height()
        self.assertGreaterEqual(self.panel().winfo_rooty(), existing_bottom - 1,
                                "判断待ちパネルが既存ウィジェットの下にない")

    def test_building_the_panel_does_not_change_the_selected_tab(self):
        gui = self.make_gui(build_panel=False)
        calls = []
        orig_select = gui.notebook.select

        def spy(*a, **k):
            if a or k:
                calls.append((a, k))
            return orig_select(*a, **k)
        gui.notebook.select = spy
        self.assertEqual(gui.notebook.index("current"), 0)
        gui._ui_action_decision_panel(gui.tab_action)           # 構築中も select(タブ指定) を呼ばない
        gui.root.update()
        self.assertEqual(gui.notebook.index("current"), 0)
        self.apply(make_snapshot([make_row("A")]))
        self.seed_files()
        gui._refresh_action_decision_view()
        self.pump(lambda: len(self.row_ids()) == 3, timeout=8)
        self.assertEqual(calls, [], "notebook.select(タブ指定) が呼ばれた (起動タブは変えない仕様)")
        self.assertEqual(gui.notebook.index("current"), 0)

    def test_action_tab_base_text_constant(self):
        self.assertEqual(oto().MailManagerGUI.ACTION_TAB_BASE_TEXT, "📋 アクション")


# ============================================================
# _apply_action_decision_view
# ============================================================
class TestApplyView(GuiCase):
    def test_heading_status_rows_and_iids(self):
        self.make_gui(select_action=True)
        rows = [make_row("A", deadline="10/10"), make_row("B", deadline=""), make_row("C", owner="Suzuki")]
        snap = make_snapshot(rows, heading=f"{BASE} (判断待ち3・2時間前)", status_text="状態ラベルのテキストXYZ")
        self.apply(snap)
        self.assertEqual(self.tab_text(), f"{BASE} (判断待ち3・2時間前)")
        self.assertIn("状態ラベルのテキストXYZ", self.label_texts())
        self.assertEqual(self.row_ids(), [r["key"] for r in rows], "行数・順序・iid(=action_key) が一致しない")
        for r in rows:
            text = self.row_text(r["key"])
            for field in ("owner", "action", "deadline", "date_mmdd"):
                self.assertIn(r[field], text, f"{r['key']} の行に {field}={r[field]!r} が表示されていない")
            self.assertTrue(r["topic"] in text or r["real_topic"] in text, "件名が表示されていない")

    def test_apply_empty_rows(self):
        self.make_gui()
        self.apply(make_snapshot([make_row("A")]))
        self.apply(make_snapshot([], heading=f"{BASE} (判断待ち0・1時間前)"))
        self.assertEqual(self.row_ids(), [])
        self.assertEqual(self.tab_text(), f"{BASE} (判断待ち0・1時間前)")

    def test_apply_replaces_old_rows(self):
        self.make_gui()
        self.apply(make_snapshot([make_row("A"), make_row("B"), make_row("C")]))
        self.apply(make_snapshot([make_row("D"), make_row("B")]))
        self.assertEqual(self.row_ids(), [self.key("D"), self.key("B")])

    def test_apply_is_repeatable_and_does_not_grow(self):
        self.make_gui()
        snap = make_snapshot([make_row("A"), make_row("B")])
        for _ in range(20):
            self.apply(snap)
        self.assertEqual(self.row_ids(), [self.key("A"), self.key("B")])

    def test_unknown_rows_none_updates_heading_and_does_not_crash(self):
        self.make_gui()
        self.apply(make_snapshot([make_row("A"), make_row("B")]))
        snap = make_snapshot(None, heading=f"{BASE} (判断待ち?・読込失敗)", status_text="読込に失敗しました")
        self.apply(snap)
        self.assertEqual(self.tab_text(), f"{BASE} (判断待ち?・読込失敗)")
        self.assertIn("読込に失敗しました", self.label_texts())
        # 一覧を空にするか前回表示を残すかは仕様に無い (どちらでも可)。例外にならないこと
        self.assertIn(self.row_ids(), ([], [self.key("A"), self.key("B")]))

    def test_special_characters_in_cells_are_safe(self):
        self.make_gui()
        nasty = 'a {b} \\ "c" $d [e] ; \n 改行 {unbalanced'
        row = make_row("A", owner="O'Brien {x}", action=nasty, deadline="{10/10", topic="件名 } 閉じ括弧")
        self.apply(make_snapshot([row]))
        self.assertEqual(self.row_ids(), [row["key"]])
        self.assertIn("O'Brien {x}", self.row_text(row["key"]))

    def test_long_text_does_not_break(self):
        self.make_gui()
        row = make_row("A", action="長い依頼 " * 2000, comment="c" * 5000)
        self.apply(make_snapshot([row]))
        self.assertEqual(self.row_ids(), [row["key"]])

    def test_many_rows_are_applied_quickly(self):
        self.make_gui()
        rows = [make_row(f"C{i:03d}") for i in range(500)]
        t0 = time.time()
        self.apply(make_snapshot(rows))
        self.assertLess(time.time() - t0, 5.0)
        self.assertEqual(len(self.row_ids()), 500)

    def test_apply_does_not_change_selected_tab(self):
        gui = self.make_gui()
        self.apply(make_snapshot([make_row("A")]))
        self.assertEqual(gui.notebook.index("current"), 0)


class TestSelectionIsKept(GuiCase):
    def test_selection_of_surviving_rows_is_kept(self):
        self.make_gui(select_action=True)
        self.apply(make_snapshot([make_row("A"), make_row("B"), make_row("C")]))
        self.select(self.key("B"), self.key("C"))
        self.assertEqual(set(self.tree().selection()), {self.key("B"), self.key("C")})
        # 並べ替え + 新規行 + A 消滅
        self.apply(make_snapshot([make_row("C"), make_row("B"), make_row("D")]))
        self.assertEqual(set(self.tree().selection()), {self.key("B"), self.key("C")})

    def test_selection_of_vanished_rows_is_dropped_without_error(self):
        self.make_gui(select_action=True)
        self.apply(make_snapshot([make_row("A"), make_row("B")]))
        self.select(self.key("A"), self.key("B"))
        self.apply(make_snapshot([make_row("B"), make_row("C")]))
        self.assertEqual(set(self.tree().selection()), {self.key("B")})

    def test_selection_is_kept_across_repeated_identical_applies(self):
        self.make_gui(select_action=True)
        snap = make_snapshot([make_row("A"), make_row("B"), make_row("C")])
        self.apply(snap)
        self.select(self.key("A"))
        for _ in range(5):
            self.apply(snap)
        self.assertEqual(self.tree().selection(), (self.key("A"),))

    def test_no_selection_stays_empty(self):
        self.make_gui(select_action=True)
        self.apply(make_snapshot([make_row("A")]))
        self.apply(make_snapshot([make_row("A"), make_row("B")]))
        self.assertEqual(self.tree().selection(), ())

    def test_all_rows_vanish_clears_selection(self):
        self.make_gui(select_action=True)
        self.apply(make_snapshot([make_row("A")]))
        self.select(self.key("A"))
        self.apply(make_snapshot([]))
        self.assertEqual(self.tree().selection(), ())


class TestDetailLabel(GuiCase):
    def test_full_action_text_is_shown_for_selected_row(self):
        self.make_gui(select_action=True)
        long_action = "【長文】" + "予算の承認をお願いします。" * 30
        self.apply(make_snapshot([make_row("A", action=long_action), make_row("B")]))
        self.select(self.key("A"))
        self.assertTrue(any(long_action in t for t in self.label_texts()),
                        "選択行の詳細ラベルに依頼内容の全文が出ていない")


class TestSpecGapDetailLabel(GuiCase):
    def test_ai_remarks_are_shown_in_the_detail_label(self):
        # 仕様: 「依頼内容全文とAI所見」。行データで AI 由来の文は ai_status (action.status = 現状の一言) のみ
        self.make_gui(select_action=True)
        self.apply(make_snapshot([make_row("A", ai_status="先方の返信待ちで保留中ZZ")]))
        self.select(self.key("A"))
        self.assertTrue(any("先方の返信待ちで保留中ZZ" in t for t in self.label_texts()))


# ============================================================
# ボタン操作 (実ファイル・実 snapshot を使う)
# ============================================================
class TestButtons(GuiCase):
    def test_complete_button_marks_done_and_reloads(self):
        self.setup_loaded()
        with mock.patch.object(oto(), "set_action_progress", wraps=oto().set_action_progress) as spy:
            self.select(self.key("A"), self.key("B"))
            self.button("完了にする").invoke()
            ok = self.pump(lambda: self.row_ids() == [self.key("C")], timeout=8)
        self.assertTrue(ok, f"完了後に一覧が再読込されない: {self.row_ids()}")
        statuses = read_json(STATUS_PATH)
        self.assertEqual(statuses[self.key("A")]["progress"], "done")
        self.assertEqual(statuses[self.key("B")]["progress"], "done")
        self.assertEqual(statuses[self.key("B")]["comment"], "bメモ")          # 他の項目は触らない
        self.assertNotIn(self.key("C"), statuses)
        self.assertEqual([c.args for c in spy.call_args_list],
                         [({self.key("A"): "done", self.key("B"): "done"},)],
                         "選択行のキーをまとめて set_action_progress に1回渡す想定")
        self.assertTrue(self.pump(lambda: self.tab_text().startswith(f"{BASE} (判断待ち1・"), timeout=5),
                        f"見出しの件数が更新されない: {self.tab_text()}")

    def test_ignore_button_marks_ignored_and_reloads(self):
        self.setup_loaded()
        self.select(self.key("C"))
        self.button("無視する").invoke()
        ok = self.pump(lambda: self.row_ids() == [self.key("A"), self.key("B")], timeout=8)
        self.assertTrue(ok, f"無視後に一覧が再読込されない: {self.row_ids()}")
        self.assertEqual(read_json(STATUS_PATH)[self.key("C")]["progress"], "ignored")

    def test_reload_reads_files_not_just_removes_selected_rows(self):
        # ブラウザ側 (HTTP) で C が完了にされていた場合、GUIの完了操作後の再読込で C も消える
        self.setup_loaded()
        oto().set_action_progress({self.key("C"): "done"})
        self.select(self.key("A"))
        self.button("完了にする").invoke()
        ok = self.pump(lambda: self.row_ids() == [self.key("B")], timeout=8)
        self.assertTrue(ok, f"再読込がファイルを反映していない: {self.row_ids()}")

    def test_undo_restores_previous_progress_including_missing_entries(self):
        self.setup_loaded()
        self.select(self.key("A"), self.key("B"))
        self.button("完了にする").invoke()
        self.assertTrue(self.pump(lambda: self.row_ids() == [self.key("C")], timeout=8))
        with mock.patch.object(oto(), "set_action_progress", wraps=oto().set_action_progress) as spy:
            self.button("元に戻す").invoke()
            ok = self.pump(lambda: self.row_ids() == [self.key("A"), self.key("B"), self.key("C")], timeout=8)
        self.assertTrue(ok, f"元に戻した後に一覧へ復帰しない: {self.row_ids()}")
        statuses = read_json(STATUS_PATH)
        self.assertEqual(statuses[self.key("A")]["progress"], "not_started")     # 前回エントリ無し(None) → not_started
        self.assertEqual(statuses[self.key("B")]["progress"], "in_progress")     # 元の値に復元
        self.assertEqual(statuses[self.key("B")]["comment"], "bメモ")
        self.assertEqual([c.args for c in spy.call_args_list],
                         [({self.key("A"): "not_started", self.key("B"): "in_progress"},)])

    def test_undo_only_reverts_the_last_operation(self):
        # 1段階のみ: done(A) → ignore(B) → 元に戻す は B だけ戻る
        self.setup_loaded()
        self.select(self.key("A"))
        self.button("完了にする").invoke()
        self.assertTrue(self.pump(lambda: self.key("A") not in self.row_ids(), timeout=8))
        self.select(self.key("B"))
        self.button("無視する").invoke()
        self.assertTrue(self.pump(lambda: self.key("B") not in self.row_ids(), timeout=8))
        self.button("元に戻す").invoke()
        self.assertTrue(self.pump(lambda: self.key("B") in self.row_ids(), timeout=8))
        statuses = read_json(STATUS_PATH)
        self.assertEqual(statuses[self.key("A")]["progress"], "done")
        self.assertEqual(statuses[self.key("B")]["progress"], "in_progress")
        self.assertNotIn(self.key("A"), self.row_ids())

    def test_undo_without_previous_operation_does_nothing(self):
        self.setup_loaded()
        before = read_bytes(STATUS_PATH)
        self.button("元に戻す").invoke()
        self.settle(0.3)
        self.assertEqual(read_bytes(STATUS_PATH), before)
        self.assertEqual(self.row_ids(), [self.key("A"), self.key("B"), self.key("C")])

    def test_complete_and_ignore_without_selection_do_nothing(self):
        self.setup_loaded()
        before = read_bytes(STATUS_PATH)
        self.assertEqual(self.tree().selection(), ())
        self.button("完了にする").invoke()
        self.button("無視する").invoke()
        self.settle(0.3)
        self.assertEqual(read_bytes(STATUS_PATH), before)
        self.assertEqual(self.row_ids(), [self.key("A"), self.key("B"), self.key("C")])

    def test_reload_button_rereads_files(self):
        self.setup_loaded()
        oto().set_action_progress({self.key("A"): "ignored"})
        self.button("再読込").invoke()
        ok = self.pump(lambda: self.row_ids() == [self.key("B"), self.key("C")], timeout=8)
        self.assertTrue(ok, f"再読込ボタンでファイルが反映されない: {self.row_ids()}")

    def test_write_failure_shows_error_and_keeps_the_list(self):
        # 書込に失敗 (action_status.json が壊れていて strict 読込が例外) → messagebox で通知、一覧は変更しない
        self.seed_files(statuses={self.key("C"): make_status("done")})
        self.make_gui(select_action=True)
        self.load_real(2)
        before_ids = self.row_ids()
        before_heading = self.tab_text()
        write_text(STATUS_PATH, "{broken")
        broken = read_bytes(STATUS_PATH)
        self.select(self.key("A"))
        self.button("完了にする").invoke()
        self.assertTrue(self.pump(lambda: any(d[0] == "showerror" for d in self.dialogs), timeout=5),
                        "書込失敗なのに messagebox.showerror が呼ばれない")
        self.settle(0.4)
        self.assertEqual(len([d for d in self.dialogs if d[0] == "showerror"]), 1)
        self.assertEqual(read_bytes(STATUS_PATH), broken, "壊れたファイルを上書きした")
        self.assertEqual(self.row_ids(), before_ids, "失敗時に一覧が変更された")
        self.assertEqual(self.tab_text(), before_heading, "失敗時に見出しが変更された")
        self.assertNotEqual(self.last_op_previous(), {self.key("A"): None}, "失敗した操作を「元に戻す」対象として保存した")

    def test_write_failure_message_contains_the_error_text(self):
        self.seed_files()
        self.make_gui(select_action=True)
        self.load_real(3)
        with mock.patch.object(oto(), "set_action_progress", side_effect=OSError("テスト用の書込エラーXYZ123")):
            self.select(self.key("A"))
            self.button("完了にする").invoke()
            self.assertTrue(self.pump(lambda: any(d[0] == "showerror" for d in self.dialogs), timeout=5))
        self.assertIn("XYZ123", self.dialog_text({"showerror"}), "エラー内容がメッセージに含まれていない")
        self.assertEqual(self.row_ids(), [self.key("A"), self.key("B"), self.key("C")])

    def test_buttons_work_for_a_single_selected_row_after_multiple_applies(self):
        self.setup_loaded()
        for _ in range(3):
            self.apply(make_snapshot([make_row("A"), make_row("B"), make_row("C")]))
        self.select(self.key("C"))
        self.button("完了にする").invoke()
        self.assertTrue(self.pump(lambda: self.key("C") not in self.row_ids(), timeout=8))
        self.assertEqual(read_json(STATUS_PATH)[self.key("C")]["progress"], "done")


class TestSpecGapButtons(GuiCase):
    def test_last_op_keeps_the_previous_progress_mapping(self):
        # 仕様: 「戻り値 (= {key: 更新前progress}) を self._action_decision_last_op に保存」。
        # 保存形式 (戻り値そのもの / {"previous": 戻り値, ...} のラッパ) は問わず、更新前の値が取れること
        self.setup_loaded()
        self.select(self.key("A"), self.key("B"))
        self.button("完了にする").invoke()
        self.assertTrue(self.pump(lambda: self.row_ids() == [self.key("C")], timeout=8))
        self.assertEqual(self.last_op_previous(), {self.key("A"): None, self.key("B"): "in_progress"})

    def test_second_undo_does_not_revert_again(self):
        # 「(元に戻すは) 1段階のみ」: 元に戻した後にもう一度押しても、その間に変えた状態を巻き戻さない
        self.setup_loaded()
        self.select(self.key("B"))
        self.button("完了にする").invoke()
        self.assertTrue(self.pump(lambda: self.key("B") not in self.row_ids(), timeout=8))
        self.button("元に戻す").invoke()
        self.assertTrue(self.pump(lambda: self.key("B") in self.row_ids(), timeout=8))
        oto().set_action_progress({self.key("B"): "ignored"})            # 元に戻した後に別経路で変更
        self.button("元に戻す").invoke()
        self.settle(0.4)
        self.assertEqual(read_json(STATUS_PATH)[self.key("B")]["progress"], "ignored",
                         "2回目の「元に戻す」が、その後の変更を巻き戻した")


# ============================================================
# ダブルクリック → Outlook で開く
# ============================================================
class TestOpenInOutlook(GuiCase):
    def test_double_click_opens_thread_via_worker_thread(self):
        self.make_gui(select_action=True)
        self.apply(make_snapshot([make_row("A", real_topic="実件名X", topic="AI件名X", entry_id="ENTRY-X")]))
        self.double_click_row(self.key("A"))
        self.assertTrue(self.pump(lambda: bool(self.stub_outlook.explorer_calls), timeout=5),
                        "ダブルクリックで show_thread_in_explorer が呼ばれない")
        calls = self.stub_outlook.explorer_calls
        self.assertEqual(len(calls), 1)
        self.assertEqual((calls[0]["topic"], calls[0]["entry_id"]), ("実件名X", "ENTRY-X"))
        self.assertFalse(calls[0]["in_main_thread"], "COMを触る関数をメインスレッドで呼んでいる (GUIが固まる)")
        self.assertTrue(calls[0]["daemon"], "daemon=True のスレッドで呼ぶ想定")

    def test_real_topic_empty_falls_back_to_ai_topic(self):
        self.make_gui(select_action=True)
        self.apply(make_snapshot([make_row("A", real_topic="", topic="AI件名だけ", entry_id="ENTRY-X")]))
        self.double_click_row(self.key("A"))
        self.assertTrue(self.pump(lambda: bool(self.stub_outlook.explorer_calls), timeout=5))
        self.assertEqual(self.stub_outlook.explorer_calls[0]["topic"], "AI件名だけ")

    def test_second_row_uses_its_own_ids(self):
        self.make_gui(select_action=True)
        self.apply(make_snapshot([make_row("A", entry_id="E-A"), make_row("B", entry_id="E-B")]))
        self.double_click_row(self.key("B"))
        self.assertTrue(self.pump(lambda: bool(self.stub_outlook.explorer_calls), timeout=5))
        self.assertEqual(self.stub_outlook.explorer_calls[0]["entry_id"], "E-B")
        self.assertEqual(self.stub_outlook.explorer_calls[0]["topic"], "実件名B")

    def test_empty_entry_id_does_not_call_outlook(self):
        self.make_gui(select_action=True)
        self.apply(make_snapshot([make_row("A", entry_id="")]))
        self.double_click_row(self.key("A"))
        self.settle(0.5)
        self.assertEqual(self.stub_outlook.explorer_calls, [], "entry_id が空なのに Outlook を呼んだ")

    def test_none_entry_id_does_not_call_outlook(self):
        self.make_gui(select_action=True)
        self.apply(make_snapshot([make_row("A", entry_id=None)]))
        self.double_click_row(self.key("A"))
        self.settle(0.5)
        self.assertEqual(self.stub_outlook.explorer_calls, [])

    def test_double_click_on_empty_area_does_nothing(self):
        self.make_gui(select_action=True)
        self.apply(make_snapshot([make_row("A")]))
        tree = self.tree()
        self.gui.root.update()
        x, y = 5, max(tree.winfo_height() - 3, 5)           # 行の下の空白
        for _ in range(2):
            tree.event_generate("<ButtonPress-1>", x=x, y=y)
            tree.event_generate("<ButtonRelease-1>", x=x, y=y)
        self.settle(0.4)
        self.assertEqual(self.stub_outlook.explorer_calls, [])


class TestSpecGapOpenInOutlook(GuiCase):
    def test_empty_entry_id_shows_a_guidance_message(self):
        # 仕様: 「entry_id が空なら何もせず案内メッセージ」。表示手段 (messagebox / ラベル) は未記載
        self.make_gui(select_action=True)
        self.apply(make_snapshot([make_row("A", entry_id="")]))
        before = self.label_texts(self.gui.root) + [self.gui.lbl_stat.cget("text")]
        self.double_click_row(self.key("A"))
        self.settle(0.5)
        after = self.label_texts(self.gui.root) + [self.gui.lbl_stat.cget("text")]
        self.assertTrue(self.dialogs or before != after, "案内メッセージが出ていない (messagebox もラベル変化も無い)")


# ============================================================
# _refresh_action_decision_view / tick / タブ切替
# ============================================================
class TestRefresh(GuiCase):
    def test_snapshot_runs_in_worker_thread_and_apply_in_main_thread(self):
        gui = self.make_gui(select_action=True)
        seen = {}
        snap = make_snapshot([make_row("A")], heading=f"{BASE} (判断待ち1・WORKER)")

        def fake_builder(*a, **k):
            seen["worker_is_main"] = threading.current_thread() is threading.main_thread()
            return snap

        applied = []
        orig_apply = gui._apply_action_decision_view

        def spy_apply(s):
            applied.append((threading.current_thread() is threading.main_thread(), s))
            return orig_apply(s)
        gui._apply_action_decision_view = spy_apply
        with mock.patch.object(oto(), "build_action_decision_snapshot", fake_builder):
            gui._refresh_action_decision_view()
            ok = self.pump(lambda: self.tab_text() == f"{BASE} (判断待ち1・WORKER)", timeout=5)
        self.assertTrue(ok, "refresh 後に見出しが更新されない")
        self.assertIs(seen["worker_is_main"], False, "snapshot をメインスレッドで実行している (UIが固まる)")
        self.assertTrue(applied and applied[-1][0], "_apply_action_decision_view をメインスレッド以外で呼んでいる")
        self.assertEqual(applied[-1][1], snap)
        self.assertEqual(self.row_ids(), [self.key("A")])

    def test_no_second_worker_while_one_is_running(self):
        gui = self.make_gui(select_action=True)
        gate, started, calls = threading.Event(), threading.Event(), []
        snap = make_snapshot([make_row("A")], heading=f"{BASE} (判断待ち1・GATE)")

        def slow_builder(*a, **k):
            calls.append(1)
            started.set()
            gate.wait(10)
            return snap

        with mock.patch.object(oto(), "build_action_decision_snapshot", slow_builder):
            gui._refresh_action_decision_view()
            self.assertTrue(self.pump(started.is_set, timeout=5), "ワーカーが開始しない")
            gui._refresh_action_decision_view()
            gui._refresh_action_decision_view()
            self.settle(0.3)
            self.assertEqual(len(calls), 1, "実行中に refresh が多重起動した")
            gate.set()
            self.assertTrue(self.pump(lambda: self.tab_text() == f"{BASE} (判断待ち1・GATE)", timeout=5))

    def test_can_refresh_again_after_completion(self):
        gui = self.make_gui(select_action=True)
        calls = []

        def builder(*a, **k):
            calls.append(1)
            return make_snapshot([make_row("A")], heading=f"{BASE} (判断待ち1・N{len(calls)})")

        with mock.patch.object(oto(), "build_action_decision_snapshot", builder):
            gui._refresh_action_decision_view()
            self.assertTrue(self.pump(lambda: self.tab_text().endswith("N1)"), timeout=5))
            self.settle(0.1)
            gui._refresh_action_decision_view()
            self.assertTrue(self.pump(lambda: len(calls) >= 2 and self.tab_text().endswith(f"N{len(calls)})"),
                                      timeout=5), "完了後の2回目の refresh が動かない (多重起動ガードが解除されない)")

    def test_worker_exception_shows_load_failure_and_does_not_crash(self):
        gui = self.make_gui(select_action=True)

        def boom(*a, **k):
            raise RuntimeError("snapshot で想定外の例外")

        with mock.patch.object(oto(), "build_action_decision_snapshot", boom):
            gui._refresh_action_decision_view()
            ok = self.pump(lambda: self.tab_text().endswith("(判断待ち?・読込失敗)"), timeout=5)
        self.assertTrue(ok, f"ワーカー例外後に見出しが「読込失敗」にならない: {self.tab_text()!r}")
        self.assertTrue(self.tab_text().startswith(BASE), self.tab_text())
        # 例外後も次の refresh が動く (ガードが解除されている)
        good = make_snapshot([make_row("A")], heading=f"{BASE} (判断待ち1・RECOVERED)")
        with mock.patch.object(oto(), "build_action_decision_snapshot", lambda *a, **k: good):
            gui._refresh_action_decision_view()
            self.assertTrue(self.pump(lambda: self.tab_text().endswith("RECOVERED)"), timeout=5),
                            "例外後に refresh が再開できない")

    def test_end_to_end_with_real_files_and_real_snapshot(self):
        self.seed_files()
        mod = oto()
        patches = [mock.patch.object(mod, n, _Boom(n), create=True)
                   for n in ("win32com", "pythoncom", "requests", "_CommonGeminiClient")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        gui = self.make_gui(select_action=True)
        gui._refresh_action_decision_view()
        ok = self.pump(lambda: len(self.row_ids()) == 3, timeout=8)
        self.assertTrue(ok)
        self.assertEqual(self.row_ids(), [self.key("A"), self.key("B"), self.key("C")])
        self.assertTrue(self.tab_text().startswith(f"{BASE} (判断待ち3・解析1時間前"), self.tab_text())
        self.assertIn(NOTICE_HEAD, "\n".join(self.label_texts()))
        self.assertEqual(self.stub_outlook.explorer_calls, [])

    def test_missing_files_show_unknown_freshness_but_no_crash(self):
        gui = self.make_gui(select_action=True)
        gui._refresh_action_decision_view()
        self.assertTrue(self.pump(lambda: self.tab_text() == f"{BASE} (判断待ち?・要更新)", timeout=5),
                        f"ファイルが何も無いとき見出しが「要更新」にならない: {self.tab_text()!r}")
        self.assertEqual(self.row_ids(), [])

    def test_aliases_come_from_outlook_user(self):
        # Outlook の表示名/SMTP から作った別名で「自分宛て」を判定する (COMには触れず属性だけ読む)
        write_json(CACHE_PATH, make_cache({
            "Y": make_thread([make_action(target="Yamada Taro-san")], latest_ts=int(time.time()) - 3600)}))
        write_json(LAST_RUN_PATH, make_last_run(datetime.now() - timedelta(minutes=90)))
        gui = self.make_gui(select_action=True, user_name="Taro Yamada", smtp="taro.yamada@example.com")
        self.load_real(1)
        self.assertEqual(self.row_ids(), [self.key("Y")])

    def test_aliases_empty_when_outlook_user_unknown(self):
        write_json(CACHE_PATH, make_cache({
            "Y": make_thread([make_action(target="Yamada Taro-san")], latest_ts=int(time.time()) - 3600)}))
        write_json(LAST_RUN_PATH, make_last_run(datetime.now() - timedelta(minutes=90)))
        gui = self.make_gui(select_action=True, user_name="", smtp="")
        gui._refresh_action_decision_view()
        self.assertTrue(self.pump(lambda: self.tab_text().startswith(f"{BASE} (判断待ち0・"), timeout=8),
                        self.tab_text())
        self.assertEqual(self.row_ids(), [])


class TestTick(GuiCase):
    def record_after(self):
        calls = []
        real_after = self.gui.root.after

        def rec(ms, func=None, *args):
            calls.append((ms, func))
            if isinstance(ms, (int, float)) and ms >= 500:
                return "after#fake"                          # 長い待ちは実際には予約しない
            return real_after(ms, func, *args)
        self.gui.root.after = rec
        return calls

    def test_tick_refreshes_and_reschedules_in_120_seconds(self):
        gui = self.make_gui(select_action=True)
        refreshes = []
        gui._refresh_action_decision_view = lambda: refreshes.append(1)
        calls = self.record_after()
        gui._action_decision_tick()
        self.settle(0.1)
        self.assertEqual(len(refreshes), 1, "tick で再読込されない")
        self.assertTrue(any(ms == 120000 for ms, _ in calls),
                        f"次回を120秒後に予約していない: {[ms for ms, _ in calls]}")

    def test_tick_repeats(self):
        gui = self.make_gui(select_action=True)
        refreshes = []
        gui._refresh_action_decision_view = lambda: refreshes.append(1)
        calls = self.record_after()
        gui._action_decision_tick()
        nxt = [f for ms, f in calls if ms == 120000]
        self.assertTrue(nxt)
        nxt[0]()                                             # 予約された次回を実行
        self.assertEqual(len(refreshes), 2)

    def test_tick_does_not_touch_com_or_ai(self):
        self.seed_files()
        mod = oto()
        for n in ("win32com", "pythoncom", "requests", "_CommonGeminiClient"):
            p = mock.patch.object(mod, n, _Boom(n), create=True)
            p.start()
            self.addCleanup(p.stop)
        gui = self.make_gui(select_action=True)
        self.record_after()
        gui._action_decision_tick()
        self.assertTrue(self.pump(lambda: len(self.row_ids()) == 3, timeout=8))


class TestSpecGapTickAndTabChange(GuiCase):
    def test_tick_reschedules_even_if_refresh_raises(self):
        gui = self.make_gui(select_action=True)

        def boom():
            raise RuntimeError("refresh failed")
        gui._refresh_action_decision_view = boom
        calls = []
        real_after = gui.root.after

        def rec(ms, func=None, *args):
            calls.append(ms)
            if isinstance(ms, (int, float)) and ms >= 500:
                return "after#fake"
            return real_after(ms, func, *args)
        gui.root.after = rec
        try:
            gui._action_decision_tick()
        except RuntimeError:
            pass
        self.assertIn(120000, calls, "refresh が例外でも次回の tick を予約し続ける想定 (定期更新が止まらない)")

    def test_selecting_the_action_tab_triggers_a_refresh(self):
        # 仕様: <<NotebookTabChanged>> (add="+") に、アクションタブ選択時の再読込をバインド。
        # バインドを __init__ 側で行う実装だと、__new__ で作ったこのテストからは見えない (→要確認)
        gui = self.make_gui()
        refreshes = []
        gui._refresh_action_decision_view = lambda: refreshes.append(1)
        gui.notebook.select(gui.tab_search)
        self.settle(0.1)
        n0 = len(refreshes)
        gui.notebook.select(gui.tab_action)
        self.settle(0.2)
        self.assertGreater(len(refreshes), n0, "アクションタブ選択で再読込されない")

    def test_selecting_another_tab_does_not_trigger_a_refresh(self):
        gui = self.make_gui(select_action=True)
        refreshes = []
        gui._refresh_action_decision_view = lambda: refreshes.append(1)
        gui.notebook.select(gui.tab_search)
        self.settle(0.2)
        self.assertEqual(refreshes, [], "他のタブを選んだだけで再読込された")

    def test_tab_change_binding_keeps_existing_bindings(self):
        # add="+" : パネル構築前から付いていた <<NotebookTabChanged>> のバインドを上書きしない
        gui = self.make_gui(build_panel=False)
        fired = []
        gui.notebook.bind("<<NotebookTabChanged>>", lambda e: fired.append(1))
        gui._ui_action_decision_panel(gui.tab_action)
        gui.root.update()
        gui._refresh_action_decision_view = lambda: None
        gui.notebook.select(gui.tab_action)
        self.settle(0.2)
        self.assertTrue(fired, "既存の <<NotebookTabChanged>> ハンドラが上書きされた (add='+' になっていない)")


class TestSpecGapContextMenu(GuiCase):
    def test_context_menu_has_the_four_commands_if_prebuilt(self):
        # 仕様: 右クリックメニュー(完了/無視/Outlookで開く/元に戻す)。生成タイミング (事前/右クリック時) は未記載。
        # 事前生成されている場合だけ中身を確認する (右クリック時生成なら skip)
        self.make_gui()
        menus = [w for w in walk(self.gui.root) if isinstance(w, tk.Menu)]
        labels = []
        for m in menus:
            end = m.index("end")
            if end is None:
                continue
            for i in range(end + 1):
                try:
                    labels.append(str(m.entrycget(i, "label")))
                except tk.TclError:
                    pass
        if not labels:
            self.skipTest("右クリックメニューが事前生成されていない (右クリック時に生成する実装?)")
        text = " ".join(labels)
        for frag in ("完了", "無視", "Outlook", "元に戻す"):
            self.assertIn(frag, text, f"右クリックメニューに「{frag}」が無い: {labels}")


# ============================================================
# 仕様変更(第2回): 「🕰 古い案件も表示」(v_action_decision_old / chk_action_decision_old)
# ============================================================
class TestOlderCheckbox(GuiCase):
    """ONのとき一覧に older_rows を末尾へ足す。_render_action_decision_rows() が直近 snapshot
    (self._action_decision_last_snap) から描き直す (チェック変更で再計算はしない)。"""

    def older_snapshot(self, **kw):
        rows = [make_row("A"), make_row("B")]
        older = [make_row("O1", latest_ts=1_000_000_000), make_row("O2", latest_ts=1_000_000_000)]
        return make_snapshot(rows, older_rows=older, **kw)

    def toggle(self):
        self.old_checkbox().invoke()
        self.settle(0.1)

    def test_checkbox_exists_and_defaults_to_off(self):
        gui = self.make_gui(select_action=True)
        box = self.old_checkbox()
        self.assertIs(gui.chk_action_decision_old, box)
        self.assertIs(gui.v_action_decision_old.get(), False)
        self.assertIn("古い案件も表示", str(box.cget("text")))

    def test_off_shows_only_rows(self):
        self.make_gui(select_action=True)
        self.apply(self.older_snapshot())
        self.assertEqual(self.row_ids(), [self.key("A"), self.key("B")])

    def test_on_appends_older_rows_at_the_end_and_off_removes_them(self):
        gui = self.make_gui(select_action=True)
        self.apply(self.older_snapshot())
        self.toggle()
        self.assertIs(gui.v_action_decision_old.get(), True)
        self.assertEqual(self.row_ids(), [self.key("A"), self.key("B"), self.key("O1"), self.key("O2")])
        self.toggle()
        self.assertIs(gui.v_action_decision_old.get(), False)
        self.assertEqual(self.row_ids(), [self.key("A"), self.key("B")])

    def test_older_rows_show_their_cells(self):
        self.make_gui(select_action=True)
        self.apply(self.older_snapshot())
        self.toggle()
        text = self.row_text(self.key("O1"))
        self.assertIn("依頼者O1", text)
        self.assertIn("O1 の予算を承認してください", text)

    def test_toggle_keeps_selection_of_surviving_rows(self):
        self.make_gui(select_action=True)
        self.apply(self.older_snapshot())
        self.select(self.key("B"))
        self.toggle()                                              # ON: 選択は残る
        self.assertEqual(self.tree().selection(), (self.key("B"),))
        self.select(self.key("B"), self.key("O1"))
        self.toggle()                                              # OFF: O1 は消える → B だけ残る (例外なし)
        self.assertEqual(set(self.tree().selection()), {self.key("B")})
        self.toggle()                                              # ON に戻しても O1 を勝手に選択しない
        self.assertEqual(set(self.tree().selection()), {self.key("B")})

    def test_toggle_does_not_recompute_the_snapshot(self):
        self.make_gui(select_action=True)
        self.apply(self.older_snapshot())
        calls = []

        def builder(*a, **k):
            calls.append(1)
            return make_snapshot([])
        with mock.patch.object(oto(), "build_action_decision_snapshot", builder):
            for _ in range(4):
                self.toggle()
            self.settle(0.3)
        self.assertEqual(calls, [], "チェック切替で snapshot を再計算した")
        self.assertEqual(self.worker_threads(), [])

    def test_render_rows_redraws_from_the_last_snapshot(self):
        gui = self.make_gui(select_action=True)
        snap = self.older_snapshot()
        self.apply(snap)
        self.assertEqual(gui._action_decision_last_snap, snap)
        gui.v_action_decision_old.set(True)
        gui._render_action_decision_rows()
        gui.root.update()
        self.assertEqual(self.row_ids(), [self.key("A"), self.key("B"), self.key("O1"), self.key("O2")])
        gui.v_action_decision_old.set(False)
        gui._render_action_decision_rows()
        gui.root.update()
        self.assertEqual(self.row_ids(), [self.key("A"), self.key("B")])

    def test_new_snapshot_while_on_uses_its_own_older_rows(self):
        gui = self.make_gui(select_action=True)
        self.apply(self.older_snapshot())
        self.toggle()
        self.apply(make_snapshot([make_row("A")], older_rows=[make_row("O3", latest_ts=1_000_000_000)]))
        self.assertEqual(self.row_ids(), [self.key("A"), self.key("O3")])
        self.apply(make_snapshot([make_row("A")]))                   # older が無くなった
        self.assertEqual(self.row_ids(), [self.key("A")])
        self.assertIs(gui.v_action_decision_old.get(), True)          # チェックは保持される

    def test_new_snapshot_while_off_never_shows_older_rows(self):
        self.make_gui(select_action=True)
        self.apply(self.older_snapshot())
        self.apply(self.older_snapshot())
        self.assertEqual(self.row_ids(), [self.key("A"), self.key("B")])

    def test_tab_heading_and_status_do_not_change_on_toggle(self):
        self.make_gui(select_action=True)
        self.apply(self.older_snapshot(heading=f"{BASE} (判断待ち2・解析1時間前)", status_text="状態XYZ"))
        before = (self.tab_text(), sorted(self.label_texts()))
        self.toggle()
        self.assertEqual((self.tab_text(), sorted(self.label_texts())), before)

    def test_older_rows_none_or_missing_does_not_crash(self):
        gui = self.make_gui(select_action=True)
        self.toggle()                                                # ON のまま
        self.apply(make_snapshot([make_row("A")], older_rows=None))
        self.assertEqual(self.row_ids(), [self.key("A")])
        snap = make_snapshot([make_row("A"), make_row("B")])
        del snap["older_rows"]                                       # 古い形式の snapshot (キー無し)
        self.apply(snap)
        self.assertEqual(self.row_ids(), [self.key("A"), self.key("B")])
        self.apply(make_snapshot(None))                              # 読込失敗 (rows=None, older_rows=None)
        self.assertIs(gui.v_action_decision_old.get(), True)

    def test_complete_button_works_on_an_older_row(self):
        self.make_gui(select_action=True)
        self.apply(self.older_snapshot())
        self.toggle()
        calls = []
        with mock.patch.object(oto(), "set_action_progress", lambda d: calls.append(dict(d)) or {k: None for k in d}):
            self.select(self.key("O2"))
            self.button("完了にする").invoke()
            self.settle(0.3)
        self.assertEqual(calls, [{self.key("O2"): "done"}])

    def seed_with_old(self):
        now_ts = int(time.time())
        threads = {
            "A": make_thread([make_action(owner="依頼者A", action="Aの予算を承認してください")], topic="AI件名A",
                             real_topic="実件名A", latest_ts=now_ts - 3600, entry_id="ENTRY-A"),
            "OLD": make_thread([make_action(owner="依頼者OLD", action="OLDの予算を承認してください")],
                               topic="AI件名OLD", real_topic="実件名OLD", latest_ts=now_ts - 20 * 86400,
                               entry_id="ENTRY-OLD"),
        }
        write_json(CACHE_PATH, make_cache(threads))
        write_json(STATUS_PATH, {})
        write_json(LAST_RUN_PATH, make_last_run(datetime.now() - timedelta(minutes=90)))

    def test_e2e_old_pending_is_hidden_until_checked_and_can_be_completed(self):
        self.seed_with_old()
        gui = self.make_gui(select_action=True)
        self.load_real(1)
        self.assertEqual(self.row_ids(), [self.key("A")])
        self.assertIn(OLDER_LINE_7_1, "\n".join(self.label_texts()), "古い未対応の件数が状態ラベルに出ていない")
        self.toggle()
        self.assertEqual(self.row_ids(), [self.key("A"), self.key("OLD")])
        self.select(self.key("OLD"))
        self.button("完了にする").invoke()
        ok = self.pump(lambda: self.row_ids() == [self.key("A")], timeout=8)
        self.assertTrue(ok, f"古い案件を完了にしても一覧から消えない: {self.row_ids()}")
        self.assertEqual(read_json(STATUS_PATH)[self.key("OLD")]["progress"], "done")
        self.assertIs(gui.v_action_decision_old.get(), True)
        self.assertNotIn("古い案件も表示", "\n".join(self.label_texts()), "古い未対応が無くなったのに案内が残っている")


# ============================================================
# 仕様変更(第2回): 再浮上した行 (resurfaced) の「新着」表示と「元に戻す」
# ============================================================
class TestResurfacedGui(GuiCase):
    def seed_resurfaced(self):
        """A: done だが新着あり (再浮上) / B: in_progress / C: 通常。新しい順 A,B,C。"""
        now_ts = int(time.time())

        def iso(t):
            return datetime.fromtimestamp(t).strftime("%Y-%m-%dT%H:%M:%S")
        threads = {}
        for i, cid in enumerate(("A", "B", "C")):
            threads[cid] = make_thread(
                [make_action(owner=f"依頼者{cid}", action=f"{cid}の予算を承認してください")],
                topic=f"AI件名{cid}", real_topic=f"実件名{cid}", latest_ts=now_ts - 3600 * (i + 1),
                entry_id=f"ENTRY-{cid}")
        write_json(CACHE_PATH, make_cache(threads))
        write_json(STATUS_PATH, {
            self.key("A"): make_status("done", "high", "前回完了", updated_at=iso(now_ts - 3 * 86400)),
            self.key("B"): make_status("in_progress", "", "bメモ"),
        })
        write_json(LAST_RUN_PATH, make_last_run(datetime.now() - timedelta(minutes=90)))

    def test_resurfaced_row_shows_new_arrival_in_the_progress_column(self):
        self.make_gui(select_action=True)
        self.apply(make_snapshot([make_row("A", resurfaced=True, progress="done"), make_row("B"),
                                  make_row("C", progress="in_progress")]))
        self.assertIn("新着", self.progress_cell(self.key("A")))
        self.assertNotIn("新着", self.progress_cell(self.key("B")))
        self.assertNotIn("新着", self.progress_cell(self.key("C")))

    def test_non_resurfaced_done_like_values_never_show_new_arrival(self):
        self.make_gui(select_action=True)
        self.apply(make_snapshot([make_row("A", resurfaced=False, progress="not_started"),
                                  make_row("B", resurfaced=False, progress="in_progress")]))
        for cid in ("A", "B"):
            self.assertNotIn("新着", self.progress_cell(self.key(cid)))

    def test_older_resurfaced_row_shows_new_arrival_too(self):
        self.make_gui(select_action=True)
        self.apply(make_snapshot([make_row("A")], older_rows=[make_row("O1", resurfaced=True, progress="done")]))
        self.old_checkbox().invoke()
        self.settle(0.1)
        self.assertIn("新着", self.progress_cell(self.key("O1")))

    def test_e2e_resurfaced_done_is_listed_with_marker(self):
        self.seed_resurfaced()
        self.make_gui(select_action=True)
        self.load_real(3)
        self.assertEqual(self.row_ids(), [self.key("A"), self.key("B"), self.key("C")])
        self.assertIn("新着", self.progress_cell(self.key("A")))
        self.assertNotIn("新着", self.progress_cell(self.key("B")))
        self.assertNotIn("新着", self.progress_cell(self.key("C")))

    def test_complete_then_undo_restores_not_started_for_resurfaced_rows(self):
        # 完了/無視の前に resurfaced だった行は「未着手(not_started)」へ戻す
        # (done に戻すと updated_at が「今」になって再び隠れてしまうため)。通常の行は元の値へ
        self.seed_resurfaced()
        self.make_gui(select_action=True)
        self.load_real(3)
        self.select(self.key("A"), self.key("B"))
        self.button("完了にする").invoke()
        self.assertTrue(self.pump(lambda: self.row_ids() == [self.key("C")], timeout=8))
        self.assertEqual(read_json(STATUS_PATH)[self.key("A")]["progress"], "done")
        with mock.patch.object(oto(), "set_action_progress", wraps=oto().set_action_progress) as spy:
            self.button("元に戻す").invoke()
            ok = self.pump(lambda: self.row_ids() == [self.key("A"), self.key("B"), self.key("C")], timeout=8)
        self.assertTrue(ok, f"元に戻しても一覧へ復帰しない (done へ戻して再び隠れた?): {self.row_ids()}")
        self.assertEqual([c.args for c in spy.call_args_list],
                         [({self.key("A"): "not_started", self.key("B"): "in_progress"},)])
        st = read_json(STATUS_PATH)
        self.assertEqual(st[self.key("A")]["progress"], "not_started")
        self.assertEqual(st[self.key("A")]["comment"], "前回完了")             # 他の項目は触らない
        self.assertEqual(st[self.key("A")]["priority"], "high")
        self.assertEqual(st[self.key("B")]["progress"], "in_progress")
        self.assertNotIn("新着", self.progress_cell(self.key("A")))          # もう「新着」ではない

    def test_ignore_then_undo_restores_not_started_for_resurfaced_rows(self):
        self.seed_resurfaced()
        self.make_gui(select_action=True)
        self.load_real(3)
        self.select(self.key("A"))
        self.button("無視する").invoke()
        self.assertTrue(self.pump(lambda: self.key("A") not in self.row_ids(), timeout=8))
        self.assertEqual(read_json(STATUS_PATH)[self.key("A")]["progress"], "ignored")
        self.button("元に戻す").invoke()
        self.assertTrue(self.pump(lambda: self.key("A") in self.row_ids(), timeout=8))
        self.assertEqual(read_json(STATUS_PATH)[self.key("A")]["progress"], "not_started")

    def test_undo_of_a_normal_row_still_restores_its_previous_value(self):
        self.seed_resurfaced()
        self.make_gui(select_action=True)
        self.load_real(3)
        self.select(self.key("B"))
        self.button("完了にする").invoke()
        self.assertTrue(self.pump(lambda: self.key("B") not in self.row_ids(), timeout=8))
        self.button("元に戻す").invoke()
        self.assertTrue(self.pump(lambda: self.key("B") in self.row_ids(), timeout=8))
        self.assertEqual(read_json(STATUS_PATH)[self.key("B")]["progress"], "in_progress")

    def test_resurfaced_row_completed_stays_hidden_until_the_next_new_mail(self):
        self.seed_resurfaced()
        self.make_gui(select_action=True)
        self.load_real(3)
        self.select(self.key("A"))
        self.button("完了にする").invoke()
        self.assertTrue(self.pump(lambda: self.key("A") not in self.row_ids(), timeout=8))
        self.gui._refresh_action_decision_view()                      # 再読込しても隠れたまま
        self.settle(0.6)
        self.assertNotIn(self.key("A"), self.row_ids())


# ============================================================
# 仕様変更(第2回): 再読込の多重起動防止ウォッチドッグ (60秒超で解除)
# ============================================================
class TestRefreshWatchdog(GuiCase):
    def run_refresh(self, started_ago, expect_run):
        gui = self.make_gui(select_action=True)
        calls = []
        snap = make_snapshot([make_row("A")], heading=f"{BASE} (判断待ち1・WATCHDOG)")

        def builder(*a, **k):
            calls.append(1)
            return snap
        gui._action_decision_refreshing = True
        gui._action_decision_refresh_started = time.monotonic() - started_ago
        with mock.patch.object(oto(), "build_action_decision_snapshot", builder):
            gui._refresh_action_decision_view()
            if expect_run:
                ok = self.pump(lambda: self.tab_text().endswith("WATCHDOG)"), timeout=5)
                self.assertTrue(ok, "60秒超の「実行中」フラグが解除されず、再読込が走らない (永久停止)")
            else:
                self.settle(0.5)
        return gui, calls

    def test_stuck_flag_is_released_after_61_seconds(self):
        gui, calls = self.run_refresh(61, expect_run=True)
        self.assertEqual(calls, [1])

    def test_much_longer_than_60_seconds_also_runs(self):
        gui, calls = self.run_refresh(3600, expect_run=True)
        self.assertEqual(calls, [1])

    def test_within_60_seconds_still_blocks_a_second_worker(self):
        gui = self.make_gui(select_action=True)
        calls = []

        def builder(*a, **k):
            calls.append(1)
            return make_snapshot([make_row("A")])
        with mock.patch.object(oto(), "build_action_decision_snapshot", builder):
            for ago in (0, 1, 30, 59):
                with self.subTest(started_seconds_ago=ago):
                    gui._action_decision_refreshing = True
                    gui._action_decision_refresh_started = time.monotonic() - ago
                    gui._refresh_action_decision_view()
                    self.settle(0.3)
                    self.assertEqual(calls, [], f"{ago}秒経過で多重起動した")
                    self.assertTrue(gui._action_decision_refreshing, "実行中フラグが勝手に下りた")

    def test_after_a_watchdog_restart_the_guard_works_again(self):
        gui, calls = self.run_refresh(61, expect_run=True)
        self.assertTrue(self.pump(lambda: not gui._action_decision_refreshing, timeout=5),
                        "再起動した読込が終わってもフラグが下りない")
        with mock.patch.object(oto(), "build_action_decision_snapshot",
                               lambda *a, **k: make_snapshot([make_row("B")], heading=f"{BASE} (判断待ち1・AGAIN)")):
            gui._refresh_action_decision_view()
            self.assertTrue(self.pump(lambda: self.tab_text().endswith("AGAIN)"), timeout=5))

    def test_refresh_started_is_recorded_with_monotonic_time(self):
        gui = self.make_gui(select_action=True)
        gate, started = threading.Event(), threading.Event()

        def slow(*a, **k):
            started.set()
            gate.wait(10)
            return make_snapshot([make_row("A")])
        t0 = time.monotonic()
        with mock.patch.object(oto(), "build_action_decision_snapshot", slow):
            gui._refresh_action_decision_view()
            self.assertTrue(self.pump(started.is_set, timeout=5))
            t1 = time.monotonic()
            self.assertTrue(gui._action_decision_refreshing)
            self.assertGreaterEqual(gui._action_decision_refresh_started, t0 - 0.01)
            self.assertLessEqual(gui._action_decision_refresh_started, t1 + 0.01)
            gate.set()
            self.assertTrue(self.pump(lambda: not gui._action_decision_refreshing, timeout=5))


# ============================================================
# 仕様変更(第2回): _choose_action_tab_heading (タブ見出しの通常/短縮の選択)
# ============================================================
class TestChooseTabHeading(GuiCase):
    LONG = f"{BASE} (判断待ち12+・解析23時間前・3日間のみ・解析失敗15件)"
    COMPACT = f"{BASE} ⚖12+"

    def need_px(self, heading):
        """全タブの文言幅 (TkDefaultFont.measure + ACTION_TAB_PADDING_PX/タブ)。アクションタブは heading で計算。"""
        import tkinter.font as tkfont
        font = tkfont.nametofont("TkDefaultFont")
        pad = _const("ACTION_TAB_PADDING_PX")
        total = 0
        for tab in self.gui.notebook.tabs():
            text = heading if str(tab) == str(self.gui.tab_action) else self.gui.notebook.tab(tab, "text")
            total += font.measure(text) + pad
        return total

    def resize(self, width):
        self.gui.root.geometry(f"{width}x400+0+0")
        self.gui.root.update()
        self.gui.root.update_idletasks()
        got = self.gui.notebook.winfo_width()
        if abs(got - width) > 60:
            self.skipTest(f"ウィンドウ幅を {width}px にできない (実際 {got}px): ウィンドウマネージャ依存")

    def choose(self, heading=None, compact=None):
        return self.gui._choose_action_tab_heading(self.LONG if heading is None else heading,
                                                   self.COMPACT if compact is None else compact)

    def test_enough_width_returns_the_normal_heading(self):
        self.make_gui(select_action=True)
        self.resize(self.need_px(self.LONG) + 150)
        self.assertEqual(self.choose(), self.LONG)

    def test_not_enough_width_returns_the_compact_heading(self):
        self.make_gui(select_action=True)
        self.resize(max(self.need_px(self.LONG) - 150, 120))
        self.assertEqual(self.choose(), self.COMPACT)

    def test_width_unknown_before_display_returns_the_normal_heading(self):
        # 表示前 (winfo_width() <= 1): 幅が分からないので通常の見出し
        gui = self.make_gui(select_action=True, map_window=False)
        self.assertLessEqual(gui.notebook.winfo_width(), 1)
        self.assertEqual(self.choose(), self.LONG)

    def test_a_heading_that_fits_is_kept_even_in_a_narrow_window(self):
        self.make_gui(select_action=True)
        short = f"{BASE} (判断待ち3・解析2時間前)"
        self.resize(self.need_px(short) + 150)
        self.assertEqual(self.choose(short, f"{BASE} ⚖3"), short)

    def test_threshold_follows_the_text_widths(self):
        # 幅がちょうど境界の前後 (±150px) で切り替わる = 文言幅 + タブごとの余白(28px) で判定している
        self.make_gui(select_action=True)
        need = self.need_px(self.LONG)
        self.resize(need + 150)
        self.assertEqual(self.choose(), self.LONG)
        self.resize(need - 150)
        self.assertEqual(self.choose(), self.COMPACT)

    def test_returns_str(self):
        self.make_gui(select_action=True)
        self.assertIsInstance(self.choose(), str)

    def test_apply_view_uses_the_choice(self):
        self.make_gui(select_action=True)
        snap = make_snapshot([make_row("A")], heading=self.LONG, heading_compact=self.COMPACT)
        self.resize(self.need_px(self.LONG) + 150)
        self.apply(snap)
        self.assertEqual(self.tab_text(), self.LONG)
        self.resize(max(self.need_px(self.LONG) - 150, 120))
        self.apply(snap)
        self.assertEqual(self.tab_text(), self.COMPACT)
        self.resize(self.need_px(self.LONG) + 150)
        self.apply(snap)
        self.assertEqual(self.tab_text(), self.LONG)

    def test_apply_view_with_unknown_width_keeps_the_normal_heading(self):
        gui = self.make_gui(select_action=True, map_window=False)
        self.assertLessEqual(gui.notebook.winfo_width(), 1)
        gui._apply_action_decision_view(make_snapshot([make_row("A")], heading=self.LONG,
                                                      heading_compact=self.COMPACT))
        self.assertEqual(self.tab_text(), self.LONG)

    def test_apply_view_failure_heading_also_uses_the_choice(self):
        # 読込失敗/要更新の見出しも同じ仕組みで短縮される (narrow なら compact)
        self.make_gui(select_action=True)
        snap = make_snapshot(None, heading=f"{BASE} (判断待ち?・読込失敗)", heading_compact=f"{BASE} ⚖!")
        self.resize(max(self.need_px(self.LONG) - 150, 120))
        self.apply(snap)
        self.assertIn(self.tab_text(), (f"{BASE} (判断待ち?・読込失敗)", f"{BASE} ⚖!"))


class TestSpecGapChooseTabHeading(GuiCase):
    LONG = TestChooseTabHeading.LONG
    COMPACT = TestChooseTabHeading.COMPACT

    def test_snapshot_without_compact_heading_falls_back_to_the_normal_heading(self):
        # 古い形式の snapshot (heading_compact 無し) でも落ちない
        gui = self.make_gui(select_action=True)
        gui.root.geometry("200x400+0+0")
        gui.root.update()
        snap = make_snapshot([make_row("A")], heading=self.LONG)
        del snap["heading_compact"]
        self.apply(snap)
        self.assertEqual(self.tab_text(), self.LONG)

    def test_last_snapshot_is_remembered_for_rendering(self):
        gui = self.make_gui(select_action=True)
        snap = make_snapshot([make_row("A")])
        self.apply(snap)
        self.assertEqual(gui._action_decision_last_snap, snap)

    def test_tab_heading_is_not_changed_by_window_resize_until_next_apply(self):
        # 仕様は「_apply_action_decision_view がこれでタブ見出しを決める」のみ。リサイズ追従は未記載
        # → リサイズだけでは見出しが勝手に変わらない/例外にならないこと
        gui = self.make_gui(select_action=True)
        self.apply(make_snapshot([make_row("A")], heading=self.LONG, heading_compact=self.COMPACT))
        before = self.tab_text()
        gui.root.geometry("200x400+0+0")
        gui.root.update()
        self.assertIn(self.tab_text(), (before, self.COMPACT))


def _const(name):
    """モジュール定数、無ければ MailManagerGUI のクラス定数 (仕様は置き場所を明記していない)。"""
    mod = oto()
    if hasattr(mod, name):
        return getattr(mod, name)
    return getattr(mod.MailManagerGUI, name)


# ============================================================
# _run_action_dashboard の変更 (last_run 保存と finally での再読込)
# ============================================================
class TestRunActionDashboardHook(GuiCase):
    def run_dashboard(self, gui, expect_last_run=True, timeout=10):
        refreshes = []
        gui._refresh_action_decision_view = lambda: refreshes.append(1)
        gui._run_action_dashboard()
        ok = self.pump(lambda: str(gui.btn_run_action.cget("state")) == "normal" and bool(refreshes), timeout=timeout)
        self.assertTrue(ok, f"生成処理が完了しない (btn={gui.btn_run_action.cget('state')}, refresh={len(refreshes)})")
        self.settle(0.2)
        return refreshes

    def test_success_saves_last_run_and_triggers_refresh(self):
        gui = self.make_gui(select_action=True)
        before = datetime.now().replace(microsecond=0)
        refreshes = self.run_dashboard(gui)
        d = read_json(LAST_RUN_PATH)
        self.assertEqual(d["days"], 7)                               # 「1週間」
        self.assertIn("1週間", d["period_label"])
        ts = datetime.strptime(d["finished_at"], "%Y-%m-%dT%H:%M:%S")
        self.assertLessEqual(before - timedelta(seconds=2), ts)
        self.assertLessEqual(ts, datetime.now() + timedelta(seconds=2))
        self.assertEqual(len(refreshes), 1)
        # 既存挙動は変えない
        self.assertEqual(str(gui.btn_run_action.cget("state")), "normal")
        self.assertEqual(str(gui.btn_run_action.cget("text")), "📋 アクション一覧を生成")
        self.assertEqual(len(gui.summarizer.calls), 1)
        self.assertIs(gui.summarizer.calls[0]["expand"], True)
        self.assertEqual(gui.summarizer.calls[0]["reset"], set())
        self.assertEqual(len(gui.reporter.calls), 1)
        self.assertEqual(self.dialogs, [])

    def test_24h_period_is_saved_as_days_0(self):
        gui = self.make_gui(select_action=True)
        gui.v_action_prd.set("24H")
        self.run_dashboard(gui)
        d = read_json(LAST_RUN_PATH)
        self.assertEqual(d["days"], 0)
        self.assertIn("24H", d["period_label"])
        self.assertEqual(self.stub_outlook.period_calls, [0])

    def test_other_periods(self):
        gui = self.make_gui(select_action=True)
        for label, days in (("3日間", 3), ("1ヶ月", 30), ("6ヶ月", 180)):
            with self.subTest(period=label):
                gui.v_action_prd.set(label)
                self.run_dashboard(gui)
                d = read_json(LAST_RUN_PATH)               # 前回の記録が上書きされること (days/label が変わる)
                self.assertEqual(d["days"], days)
                self.assertIn(label, d["period_label"])

    def test_summarize_failure_does_not_save_last_run_but_still_refreshes(self):
        gui = self.make_gui(select_action=True)
        gui.summarizer = StubSummarizer(fail=RuntimeError("AI解析で失敗しましたQQQ"))
        refreshes = self.run_dashboard(gui)
        self.assertFalse(os.path.exists(LAST_RUN_PATH), "解析失敗なのに last_run を保存した (鮮度が偽になる)")
        self.assertEqual(len(refreshes), 1, "失敗時も finally で再読込する想定")
        self.assertEqual(str(gui.btn_run_action.cget("state")), "normal")
        self.assertEqual(str(gui.btn_run_action.cget("text")), "📋 アクション一覧を生成")

    def test_report_failure_keeps_last_run_because_analysis_succeeded(self):
        # 仕様: summarize_action_dashboard 「成功直後」に save_action_last_run (HTML生成より前)
        gui = self.make_gui(select_action=True)
        gui.reporter = StubReporter(fail=RuntimeError("HTML生成に失敗RRR"))
        refreshes = self.run_dashboard(gui)
        self.assertTrue(os.path.exists(LAST_RUN_PATH), "解析は成功したのに last_run が保存されていない")
        self.assertEqual(len(refreshes), 1)

    def test_failure_shows_the_error_dialog_with_the_exception_message(self):
        """失敗したら、エラーダイアログ (messagebox.showerror) が実際に1回表示され、本文に例外メッセージを含む。

        A1.1 で修正された旧版の既知バグの回帰テスト (旧: expectedFailure)。旧版は except 節の
        `lambda: messagebox.showerror("エラー", str(e))` が after(0) 実行時に except 変数 e を参照できず
        NameError になり、エラーダイアログが出なかった。再発すると、この表示の確認だけでなく
        teardown の「Tkコールバックの未処理例外」(NameError) でも検知される。
        """
        gui = self.make_gui(select_action=True)
        gui.summarizer = StubSummarizer(fail=RuntimeError("AI解析で失敗しましたQQQ"))
        self.run_dashboard(gui)
        shown = [d for d in self.dialogs if d[0] == "showerror"]
        self.assertEqual(len(shown), 1, f"showerror が1回だけ表示されるはず: {self.dialogs}")
        self.assertIn("QQQ", self.dialog_text({"showerror"}))

    def test_last_run_is_saved_before_report_generation(self):
        gui = self.make_gui(select_action=True)
        order = []
        orig_save = oto().save_action_last_run

        def spy_save(*a, **k):
            order.append("save_last_run")
            return orig_save(*a, **k)

        class OrderReporter(StubReporter):
            def generate_action_dashboard_report(self_inner, *a, **k):
                order.append("report")
                return StubReporter.generate_action_dashboard_report(self_inner, *a, **k)

        gui.reporter = OrderReporter()
        with mock.patch.object(oto(), "save_action_last_run", spy_save):
            self.run_dashboard(gui)
        self.assertEqual(order, ["save_last_run", "report"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
