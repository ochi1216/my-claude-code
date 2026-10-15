# -*- coding: utf-8 -*-
"""A6「タブ統合 (毎週の俯瞰3タブを入れ子Notebookにまとめる: 6→4)」テスト (仕様書 A6_SPEC.md)。

仕様書だけを根拠に、実装 (新メソッド MailManagerGUI._build_main_tabs の中身) を見ずに書いている。
  - 仕様に明記された挙動            -> 通常の TestCase
  - 仕様が曖昧/未記載で「最も自然な解釈」で書いたもの
                                    -> クラス名に SpecGap を含む (コメントに解釈を明記)
    SpecGap の失敗は「バグ」ではなく「仕様の確認が必要」の合図として扱う。

やり方
  - 本番の MailManagerGUI.__init__ は Outlook(COM) に接続するので Linux では呼べない。そこで
    MailManagerGUI.__new__ で作った空のオブジェクトに root (tk.Tk) だけ持たせ、**_build_main_tabs() を直接呼ぶ**
    (A6 の組み立てそのものを検査する。Notebook の手組みはしない)。
  - A1 の GUI フロー (見出しの更新・短縮見出し・タブ切替での再読込) は、その上で A1 の既存ハーネス
    (test_a1_gui_smoke.GuiCase: mainloop+quit の pump / settle / 後始末、StubOutlook、snapshot のビルダ) を使って動かす。
  - Tk の都合: <<NotebookTabChanged>> は select() の直後に queue されるので、settle() で流してから確認する。
    入れ子Notebook のイベントは入れ子Notebook 自身にだけ届き、上位Notebook のバインドには届かない。
  - Outlook(COM)・AI・ネットワークには一切触れない (A1 のスタブは触ったら失敗する)。
    Linux では  xvfb-run -a /usr/bin/python3.12 tests/run_tests.py a6  で実行できる (tkinter/ディスプレイが無ければ GUI は skip)。

構成
  1. 構造 (上位Notebook 4タブ / 入れ子Notebook 3タブ / 親子関係 / pack / 起動時の選択 / select() 不使用)
  2. 表示 (タブを選ぶと各ページが見える) / 必要な大きさ (旧の平らな6タブ構成との比較)
  3. A1 との整合 (本番の構成の上で A1 の見出し・短縮見出し・タブ切替の再読込・実ファイルでの一覧。
     さらに A1 の既存テスト (パネル構築/見出し/再読込/タブ切替/短縮見出し) を、手組みの Notebook の代わりに
     _build_main_tabs() の構成で丸ごと再実行する = クラス名 Production_<A1のクラス名>)
  4. 各 _ui_*_tab が入れ子の親フレームでも作れること
  5. 範囲ガード (旧版と新版の AST 比較。変えてよい既存メソッドは __init__ だけ、追加は _build_main_tabs だけ)
"""
import ast
import difflib
import functools
import os
import unittest
from collections import Counter
from unittest import mock

import _loader
import test_a1_gui_smoke as a1gui          # A1 の GUI ハーネス (GuiCase / スタブ / snapshot ビルダ) を再利用する

tk, ttk = a1gui.tk, a1gui.ttk
try:
    import tkinter.font as tkfont
except Exception:                                           # pragma: no cover
    tkfont = None

walk = a1gui.walk
BASE = a1gui.BASE
make_row = a1gui.make_row
make_snapshot = a1gui.make_snapshot

# 統合時にこの2つを書き換える (A6 の直前のリビジョン / A6 を入れたリビジョン)
OLD_REV = "outlook_total_organizer_20261004_05.py"
NEW_REV = "outlook_total_organizer_20261004_06.py"

# ---- 仕様書にあるタブの文言 (上位Notebook / 入れ子Notebook) ---------------------------------
T_SEARCH = "🔍 検索 / 整理"
T_ACTION = "📋 アクション"
T_WEEKLY = "📅 毎週(俯瞰)"
T_REVIEW = "📈 振り返り"
T_PROJECT = "📊 プロジェクト俯瞰"
T_STAFF = "👤 スタッフ俯瞰"
T_COCKPIT = "🚀 統括コックピット"
TOP_TEXTS = [T_SEARCH, T_ACTION, T_WEEKLY, T_REVIEW]
WEEKLY_TEXTS = [T_PROJECT, T_STAFF, T_COCKPIT]

# _build_main_tabs が self に作る8個 (仕様)
STRUCTURE_ATTRS = ("notebook", "nb_weekly", "tab_search", "tab_action", "tab_review",
                   "tab_project", "tab_staff", "tab_cockpit")

# 本番の __init__ が _build_main_tabs() のあとに呼ぶ順 (仕様: 呼び出し順は変更なし)
UI_ORDER = ("search", "project", "staff", "cockpit", "action", "review")
UI_METHODS = {"search": "_ui_search_tab", "project": "_ui_project_tab", "staff": "_ui_staff_tab",
              "cockpit": "_ui_cockpit_tab", "action": "_ui_action_tab", "review": "_ui_review_tab"}


def oto():
    return _loader.load()


def tab_paths(nb):
    return [str(t) for t in nb.tabs()]


def tab_texts(nb):
    return [nb.tab(t, "text") for t in nb.tabs()]


def is_inside(widget, frame):
    """widget が frame の子孫か (Tk のパス名で判定)。"""
    return str(widget).startswith(str(frame) + ".")


def find_text(frame, fragment, classes=None):
    """frame の子孫から、文言に fragment を含むラベル/ボタン/ラベルフレームを集める。"""
    classes = classes or (ttk.Button, tk.Button, ttk.Label, tk.Label, ttk.LabelFrame, tk.LabelFrame)
    out = []
    for w in walk(frame):
        if isinstance(w, classes):
            try:
                text = str(w.cget("text"))
            except tk.TclError:
                continue
            if fragment in text:
                out.append(w)
    return out


# ============================================================
# 共通の土台: 本番の _build_main_tabs() を直接呼んで構成を作る
# ============================================================
class TabsCase(a1gui.GuiCase):
    def setUp(self):
        super().setUp()
        self.refreshes = []                 # 「再読込」の呼び出し記録 (record_refresh=True のとき)

    def new_gui(self, geometry="1100x800+0+0"):
        """root (tk.Tk) だけを持つ空の MailManagerGUI (まだ _build_main_tabs() を呼んでいない)。"""
        mod = oto()
        root = tk.Tk()
        root.geometry(geometry)
        root.report_callback_exception = lambda exc, val, tb: self.callback_errors.append(f"{exc.__name__}: {val}")
        gui = mod.MailManagerGUI.__new__(mod.MailManagerGUI)
        gui.root = root
        self.gui = gui                      # 後始末 (GuiCase._teardown_gui) が root を破棄する
        return gui

    def attach_app_state(self, gui):
        """_ui_*_tab と A1 のフローが使う最小の属性 (本番では __init__ が _build_main_tabs の外で用意するもの)。"""
        gui.project_knowledge = {"staffs": {"Nakai": {}, "Saji": {}}, "projects": {}}
        gui.outlook = self.stub_outlook = a1gui.StubOutlook()
        gui.summarizer = a1gui.StubSummarizer()
        gui.reporter = a1gui.StubReporter()
        gui.threads = {}
        gui.selected = set()
        gui.lbl_stat = ttk.Label(gui.root, text="Ready", relief="sunken", padding=2)      # __init__ と同じ
        gui.lbl_stat.pack(side=tk.BOTTOM, fill=tk.X)

    def make_main(self, ui=(), app_like=False, geometry="1100x800+0+0", map_window=True, record_refresh=False):
        """_build_main_tabs() を適用した MailManagerGUI を返す。
        ui: そのあとに本番の __init__ と同じ書き方で呼ぶ _ui_*_tab ("search" "project" ... の名前)
        app_like: Outlook スタブ・ステータス行などの付属の属性を足す (ui があれば自動で足す)
        record_refresh: アクションの再読込 (_refresh_action_decision_view) を「回数を数えるだけ」に差し替える"""
        gui = self.new_gui(geometry)
        gui._build_main_tabs()                          # ← 検査対象。この時点の gui は root しか持たない
        if ui or app_like:
            self.attach_app_state(gui)
        if record_refresh:
            gui._refresh_action_decision_view = lambda: self.refreshes.append(1)
        for name in ui:
            getattr(gui, UI_METHODS[name])()
        if map_window:
            gui.root.update()
        return gui

    def drain(self):
        """保留中の <<NotebookTabChanged>> などを流す (A1 のテストの settle と同じ)。"""
        self.settle(0.2)


# ============================================================
# 1. 構造
# ============================================================
class TestStructure(TabsCase):
    """_build_main_tabs() が作る構造 (仕様「新メソッド _build_main_tabs」)。"""

    def setUp(self):
        super().setUp()
        self.g = self.make_main()

    # ---- 上位 Notebook --------------------------------------------------
    def test_top_notebook_is_a_ttk_notebook(self):
        """self.notebook は ttk.Notebook。"""
        self.assertIsInstance(self.g.notebook, ttk.Notebook)

    def test_top_notebook_is_a_direct_child_of_root(self):
        """self.notebook の親は self.root (ttk.Notebook(self.root))。"""
        self.assertEqual(self.g.notebook.winfo_parent(), str(self.g.root))

    def test_top_notebook_is_laid_out_with_pack(self):
        """self.notebook は pack で配置される。"""
        self.assertEqual(self.g.notebook.winfo_manager(), "pack")

    def test_top_notebook_pack_fill_is_both(self):
        """pack(fill=BOTH): 縦横いっぱいに広がる。"""
        self.assertEqual(str(self.g.notebook.pack_info()["fill"]), "both")

    def test_top_notebook_pack_expand_is_on(self):
        """pack(expand=True)。"""
        self.assertEqual(int(self.g.notebook.pack_info()["expand"]), 1)

    def test_top_notebook_pack_padx_is_5(self):
        """pack(padx=5)。"""
        self.assertEqual(str(self.g.notebook.pack_info()["padx"]), "5")

    def test_top_notebook_pack_pady_is_5(self):
        """pack(pady=5)。"""
        self.assertEqual(str(self.g.notebook.pack_info()["pady"]), "5")

    def test_top_notebook_pack_parent_is_root(self):
        """pack の配置先 (in) は self.root。"""
        self.assertEqual(str(self.g.notebook.pack_info()["in"]), str(self.g.root))

    def test_top_notebook_has_exactly_four_tabs(self):
        """上位Notebook のタブは4つ (6→4)。"""
        self.assertEqual(len(self.g.notebook.tabs()), 4, f"タブ: {tab_texts(self.g.notebook)}")

    def test_top_notebook_tab_order(self):
        """上位Notebook のタブの並びは tab_search, tab_action, nb_weekly, tab_review。"""
        g = self.g
        self.assertEqual(tab_paths(g.notebook), [str(g.tab_search), str(g.tab_action), str(g.nb_weekly), str(g.tab_review)])

    def test_top_notebook_tab_texts(self):
        """上位Notebook のタブの文言は「🔍 検索 / 整理」「📋 アクション」「📅 毎週(俯瞰)」「📈 振り返り」(この順)。"""
        self.assertEqual(tab_texts(self.g.notebook), TOP_TEXTS)

    def test_weekly_notebook_is_the_third_top_tab(self):
        """入れ子Notebook (nb_weekly) 自体が上位Notebook の3番目のタブ。"""
        self.assertEqual(self.g.notebook.index(self.g.nb_weekly), 2)

    def test_action_tab_is_the_second_top_tab(self):
        """tab_action は上位Notebook の2番目のタブ。"""
        self.assertEqual(self.g.notebook.index(self.g.tab_action), 1)

    # ---- 入れ子 Notebook ------------------------------------------------
    def test_weekly_notebook_is_a_ttk_notebook(self):
        """self.nb_weekly は ttk.Notebook。"""
        self.assertIsInstance(self.g.nb_weekly, ttk.Notebook)

    def test_weekly_notebook_is_a_child_of_the_top_notebook(self):
        """nb_weekly の親は上位Notebook (ttk.Notebook(self.notebook))。"""
        g = self.g
        self.assertEqual(g.nb_weekly.winfo_parent(), str(g.notebook))
        self.assertIs(g.root.nametowidget(g.nb_weekly.winfo_parent()), g.notebook)

    def test_weekly_notebook_has_exactly_three_tabs(self):
        """入れ子Notebook のタブは3つ。"""
        self.assertEqual(len(self.g.nb_weekly.tabs()), 3, f"タブ: {tab_texts(self.g.nb_weekly)}")

    def test_weekly_notebook_tab_order(self):
        """入れ子Notebook のタブの並びは tab_project, tab_staff, tab_cockpit。"""
        g = self.g
        self.assertEqual(tab_paths(g.nb_weekly), [str(g.tab_project), str(g.tab_staff), str(g.tab_cockpit)])

    def test_weekly_notebook_tab_texts(self):
        """入れ子Notebook のタブの文言は「📊 プロジェクト俯瞰」「👤 スタッフ俯瞰」「🚀 統括コックピット」(この順)。"""
        self.assertEqual(tab_texts(self.g.nb_weekly), WEEKLY_TEXTS)

    # ---- 子フレームの種類と親 -------------------------------------------
    def test_search_action_review_are_ttk_frames(self):
        """tab_search / tab_action / tab_review は ttk.Frame。"""
        for name in ("tab_search", "tab_action", "tab_review"):
            with self.subTest(frame=name):
                self.assertIsInstance(getattr(self.g, name), ttk.Frame)

    def test_search_action_review_frames_are_children_of_the_top_notebook(self):
        """tab_search / tab_action / tab_review の親は上位Notebook。"""
        g = self.g
        for name in ("tab_search", "tab_action", "tab_review"):
            with self.subTest(frame=name):
                frame = getattr(g, name)
                self.assertEqual(frame.winfo_parent(), str(g.notebook))
                self.assertIs(g.root.nametowidget(frame.winfo_parent()), g.notebook)

    def test_project_staff_cockpit_are_ttk_frames(self):
        """tab_project / tab_staff / tab_cockpit は ttk.Frame。"""
        for name in ("tab_project", "tab_staff", "tab_cockpit"):
            with self.subTest(frame=name):
                self.assertIsInstance(getattr(self.g, name), ttk.Frame)

    def test_project_staff_cockpit_frames_are_children_of_the_nested_notebook(self):
        """tab_project / tab_staff / tab_cockpit の親は入れ子Notebook (上位Notebook ではない)。"""
        g = self.g
        for name in ("tab_project", "tab_staff", "tab_cockpit"):
            with self.subTest(frame=name):
                frame = getattr(g, name)
                self.assertEqual(frame.winfo_parent(), str(g.nb_weekly))
                self.assertIs(g.root.nametowidget(frame.winfo_parent()), g.nb_weekly)

    # ---- どのタブがどこに属するか ---------------------------------------
    def test_action_tab_is_directly_under_the_top_notebook(self):
        """tab_action は上位Notebook 直下のタブ (A1 の見出し更新・タブ切替の前提)。"""
        self.assertIn(str(self.g.tab_action), tab_paths(self.g.notebook))

    def test_action_tab_is_not_in_the_nested_notebook(self):
        """tab_action は入れ子Notebook のタブではない。"""
        self.assertNotIn(str(self.g.tab_action), tab_paths(self.g.nb_weekly))

    def test_project_staff_cockpit_are_not_tabs_of_the_top_notebook(self):
        """tab_project / tab_staff / tab_cockpit は上位Notebook の直下には無い (入れ子の中だけ)。"""
        g = self.g
        for name in ("tab_project", "tab_staff", "tab_cockpit"):
            with self.subTest(frame=name):
                self.assertNotIn(str(getattr(g, name)), tab_paths(g.notebook))

    def test_search_and_review_are_not_tabs_of_the_nested_notebook(self):
        """tab_search / tab_review は入れ子Notebook のタブではない。"""
        g = self.g
        for name in ("tab_search", "tab_review"):
            with self.subTest(frame=name):
                self.assertNotIn(str(getattr(g, name)), tab_paths(g.nb_weekly))

    # ---- 起動時に選ばれるタブ -------------------------------------------
    def test_start_tab_is_search(self):
        """起動時 (組み立て直後) に選ばれているのは最初のタブ「🔍 検索 / 整理」。"""
        g = self.g
        self.assertEqual(g.notebook.select(), str(g.tab_search))

    def test_start_tab_index_is_zero(self):
        """起動時の上位Notebook のカレントタブの番号は 0。"""
        self.assertEqual(self.g.notebook.index("current"), 0)

    def test_start_tab_text_is_search(self):
        """起動時のカレントタブの文言は「🔍 検索 / 整理」。"""
        self.assertEqual(self.g.notebook.tab("current", "text"), T_SEARCH)

    def test_start_page_is_visible(self):
        """起動時は検索ページが表示され、他のページは見えない。"""
        g = self.g
        g.root.update()
        self.assertTrue(g.tab_search.winfo_viewable())
        for name in ("tab_action", "nb_weekly", "tab_review", "tab_project", "tab_staff", "tab_cockpit"):
            with self.subTest(page=name):
                self.assertFalse(getattr(g, name).winfo_viewable())

    def test_action_tab_starts_with_the_base_text(self):
        """組み立て直後の tab_action の文言は基底の見出し ACTION_TAB_BASE_TEXT (「📋 アクション」)。"""
        self.assertEqual(self.g.notebook.tab(self.g.tab_action, "text"), oto().ACTION_TAB_BASE_TEXT)
        self.assertEqual(oto().ACTION_TAB_BASE_TEXT, T_ACTION)

    def test_action_tab_base_text_class_constant_is_unchanged(self):
        """MailManagerGUI.ACTION_TAB_BASE_TEXT は変わらず「📋 アクション」。"""
        self.assertEqual(oto().MailManagerGUI.ACTION_TAB_BASE_TEXT, T_ACTION)

    # ---- 中身は作らない ------------------------------------------------------
    def test_the_six_tab_frames_are_empty_after_build(self):
        """_ui_*_tab はここでは呼ばない: 6つのフレームのどれにも子ウィジェットは無い。"""
        for name in ("tab_search", "tab_action", "tab_review", "tab_project", "tab_staff", "tab_cockpit"):
            with self.subTest(frame=name):
                self.assertEqual(getattr(self.g, name).winfo_children(), [])


class TestBuildBehaviour(TabsCase):
    """_build_main_tabs() の呼び出し中の振る舞い (select() を呼ばない・_ui_*_tab を呼ばない・root だけで動く)。"""

    def test_build_works_on_an_object_that_has_only_root(self):
        """仕様「self.root に対して作る」: root だけを持つオブジェクトで動き、8個の属性を作る。"""
        gui = self.new_gui()
        self.assertEqual(set(vars(gui)), {"root"})
        gui._build_main_tabs()
        self.assertLessEqual(set(STRUCTURE_ATTRS), set(vars(gui)))

    def test_build_does_not_call_select_with_a_tab(self):
        """仕様「select() は呼ばない」: _build_main_tabs() の間、Notebook.select にタブを渡す呼び出しは1回も無い。"""
        gui = self.new_gui()
        calls = []
        orig = ttk.Notebook.select

        def spy(nb, *args, **kwargs):
            calls.append((str(nb), args, kwargs))
            return orig(nb, *args, **kwargs)

        with mock.patch.object(ttk.Notebook, "select", spy):
            gui._build_main_tabs()
        selecting = [c for c in calls if c[1] or c[2]]
        self.assertEqual(selecting, [], f"select(タブ指定) が呼ばれた: {selecting}")

    def test_search_tab_is_current_right_after_the_build(self):
        """イベントを1つも処理しない組み立て直後の時点でも、上位Notebook のカレントは tab_search。"""
        gui = self.new_gui()
        gui._build_main_tabs()
        self.assertEqual(gui.notebook.select(), str(gui.tab_search))

    def test_build_does_not_call_the_ui_tab_builders(self):
        """仕様「_ui_*_tab はここでは呼ばない」: 6つの _ui_*_tab のどれも呼ばれない。"""
        gui = self.new_gui()
        called = []
        for key, meth in UI_METHODS.items():
            setattr(gui, meth, lambda key=key: called.append(key))
        gui._build_main_tabs()
        self.assertEqual(called, [], f"_build_main_tabs が _ui_*_tab を呼んだ: {called}")


class TestSpecGapStructure(TabsCase):
    """仕様に明記されていない点を「最も自然な解釈」で書いたもの。"""

    def test_weekly_notebook_starts_on_its_first_tab(self):
        # 仕様は入れ子Notebook の起動時の選択を書いていない。「select() は呼ばない」の自然な帰結として、
        # 最初に add した tab_project (プロジェクト俯瞰) が入れ子の側のカレントになる、と解釈する
        g = self.make_main()
        self.assertEqual(g.nb_weekly.select(), str(g.tab_project))
        self.assertEqual(g.nb_weekly.index("current"), 0)

    def test_root_has_only_the_top_notebook_as_its_child(self):
        # 仕様「self.root に対して次を作る」は上位Notebook (self.notebook) だけを root 直下に置く。
        # root 直下に余計なウィジェットが作られていないこと (ステータス行は __init__ が後から作る)
        g = self.make_main()
        self.assertEqual([str(w) for w in g.root.winfo_children()], [str(g.notebook)])

    def test_the_widget_tree_has_exactly_the_eight_widgets_of_the_spec(self):
        # 仕様に書かれたウィジェット 8個 (2 Notebook + 6 Frame) 以外は作られない、と解釈する
        g = self.make_main()
        expected = {str(getattr(g, n)) for n in STRUCTURE_ATTRS}
        self.assertEqual({str(w) for w in walk(g.root)} - {str(g.root)}, expected)

    def test_build_sets_exactly_the_eight_attributes_of_the_spec(self):
        # 仕様が列挙する self の属性は 8個。それ以外の状態を self に足さない、と解釈する
        gui = self.new_gui()
        gui._build_main_tabs()
        self.assertEqual(set(vars(gui)) - {"root"}, set(STRUCTURE_ATTRS))

    def test_all_tabs_are_selectable(self):
        # 仕様はタブの state を書いていない。旧構成と同じく全タブが通常状態 (隠し/無効のタブは無い) と解釈する
        g = self.make_main()
        for nb in (g.notebook, g.nb_weekly):
            for t in nb.tabs():
                with self.subTest(tab=nb.tab(t, "text")):
                    self.assertEqual(str(nb.tab(t, "state")), "normal")

    def test_weekly_notebook_fills_the_page_of_the_top_notebook(self):
        # 仕様は大きさを書いていない。「タブに入れる」ので、毎週タブを開くと入れ子Notebook と最初のページが
        # 外側の内容領域いっぱいに広がる (小さく潰れない) と解釈する
        g = self.make_main()
        g.notebook.select(g.nb_weekly)
        self.settle(0.1)
        top_w, top_h = g.notebook.winfo_width(), g.notebook.winfo_height()
        self.assertGreater(g.nb_weekly.winfo_width(), top_w - 30)
        self.assertGreater(g.nb_weekly.winfo_height(), top_h * 0.8)
        self.assertGreater(g.tab_project.winfo_width(), top_w - 60)
        self.assertGreater(g.tab_project.winfo_height(), top_h * 0.6)


class TestSpecGapRequiredSize(TabsCase):
    """仕様は大きさを書いていない。「各タブの中身は変えない・親フレームの作成場所を変えるだけ」の帰結として、
    6つの _ui_*_tab を作ったあとの上位Notebook の「必要な大きさ (reqwidth/reqheight)」は、旧構成 (6タブを平らに並べたもの)
    と比べて、幅は増えず、高さは入れ子の見出し1段分 (+数px) までしか増えない、と解釈する。
    (仕様の「実機でしか確認できないこと」= 半画面・表示倍率が大きい環境での見切れ (スタッフ俯瞰の最下段・画面下のステータス行)
     の、Linux で確認できる代用。実機での見え方そのものは確認できない。)"""

    SLACK = 8

    def build_old_flat(self):
        """旧 __init__ と同じ書き方 (Notebook を1つ作り、6つのフレームを作って add) の平らな構成。_build_main_tabs は使わない。"""
        gui = self.new_gui()
        gui.notebook = ttk.Notebook(gui.root)
        gui.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        order = (("tab_search", T_SEARCH), ("tab_project", T_PROJECT), ("tab_staff", T_STAFF),
                 ("tab_cockpit", T_COCKPIT), ("tab_action", T_ACTION), ("tab_review", T_REVIEW))
        for name, _ in order:
            setattr(gui, name, ttk.Frame(gui.notebook))
        for name, text in order:
            gui.notebook.add(getattr(gui, name), text=text)
        self.attach_app_state(gui)
        for key in UI_ORDER:
            getattr(gui, UI_METHODS[key])()
        gui.root.update_idletasks()
        return gui

    def required_sizes(self):
        """(旧の (幅, 高さ), 新の (幅, 高さ), 入れ子の見出し1段の高さ)。Tk を2つ同時に生かさないよう、旧を測って壊してから新を作る。"""
        old = self.build_old_flat()
        old_size = (old.notebook.winfo_reqwidth(), old.notebook.winfo_reqheight())
        old.root.destroy()
        new = self.make_main(ui=UI_ORDER)
        new.root.update_idletasks()
        new_size = (new.notebook.winfo_reqwidth(), new.notebook.winfo_reqheight())
        pages = (new.tab_project, new.tab_staff, new.tab_cockpit)
        inner_header = new.nb_weekly.winfo_reqheight() - max(p.winfo_reqheight() for p in pages)
        return old_size, new_size, inner_header

    def test_required_width_does_not_grow(self):
        """6つの _ui_*_tab を作ったあとの上位Notebook の必要幅は、旧の平らな6タブ構成より増えない (+数pxまで)。"""
        old_size, new_size, _ = self.required_sizes()
        self.assertLessEqual(new_size[0], old_size[0] + self.SLACK, f"旧 {old_size} → 新 {new_size}")

    def test_required_height_grows_by_at_most_one_nested_header_row(self):
        """同じく必要な高さは、旧の平らな6タブ構成より「入れ子の見出し1段分 (+数px)」までしか増えない。"""
        old_size, new_size, inner_header = self.required_sizes()
        self.assertGreater(inner_header, 0, "前提: 入れ子の見出し行の高さが測れる")
        self.assertLessEqual(new_size[1], old_size[1] + inner_header + self.SLACK,
                             f"旧 {old_size} → 新 {new_size} (入れ子の見出し1段={inner_header})")


# ============================================================
# 2. 表示: タブを選ぶと、そのページが見える
# ============================================================
class TestPagesAreShown(TabsCase):
    """タブを選ぶと、そのページだけが実際に表示される (上位Notebook・入れ子Notebook とも)。"""

    def show(self, nb, page):
        nb.select(page)
        self.settle(0.1)

    def test_each_top_level_tab_shows_only_its_own_page(self):
        """上位Notebook の各タブを選ぶと、そのページだけが見える。"""
        g = self.make_main()
        pages = [g.tab_search, g.tab_action, g.nb_weekly, g.tab_review]
        for page in pages:
            with self.subTest(tab=g.notebook.tab(page, "text")):
                self.show(g.notebook, page)
                self.assertEqual([bool(p.winfo_viewable()) for p in pages], [p is page for p in pages])

    def test_weekly_tab_shows_the_project_page_first(self):
        """「📅 毎週(俯瞰)」を開くと、入れ子の最初のページ (プロジェクト俯瞰) が見え、他の2つは見えない。"""
        g = self.make_main()
        self.show(g.notebook, g.nb_weekly)
        self.assertTrue(g.nb_weekly.winfo_viewable())
        self.assertEqual([bool(p.winfo_viewable()) for p in (g.tab_project, g.tab_staff, g.tab_cockpit)],
                         [True, False, False])

    def test_each_nested_tab_shows_only_its_own_page(self):
        """入れ子Notebook の各タブを選ぶと、そのページだけが見える (外側は毎週タブのまま)。"""
        g = self.make_main()
        self.show(g.notebook, g.nb_weekly)
        pages = [g.tab_project, g.tab_staff, g.tab_cockpit]
        for page in pages + [g.tab_project]:
            with self.subTest(tab=g.nb_weekly.tab(page, "text")):
                self.show(g.nb_weekly, page)
                self.assertEqual([bool(p.winfo_viewable()) for p in pages], [p is page for p in pages])
                self.assertEqual(g.notebook.select(), str(g.nb_weekly))

    def test_nested_pages_are_hidden_while_another_top_tab_is_selected(self):
        """毎週以外の上位タブを選んでいる間は、入れ子のページ (どれを選んでいても) は見えない。"""
        g = self.make_main()
        self.show(g.notebook, g.nb_weekly)
        self.show(g.nb_weekly, g.tab_cockpit)
        self.show(g.notebook, g.tab_review)
        for name in ("nb_weekly", "tab_project", "tab_staff", "tab_cockpit"):
            with self.subTest(page=name):
                self.assertFalse(getattr(g, name).winfo_viewable())
        self.assertEqual(g.nb_weekly.select(), str(g.tab_cockpit), "入れ子側の選択は覚えている")


# ============================================================
# 3. A1 との整合 (本番の構成の上で A1 の GUI フローを動かす)
# ============================================================
class TestA1HeadingOnProductionTabs(TabsCase):
    """タブ見出し (件数・鮮度) は self.notebook.tab(self.tab_action, text=…) で更新される前提。"""

    LONG = a1gui.TestChooseTabHeading.LONG
    COMPACT = a1gui.TestChooseTabHeading.COMPACT

    def test_apply_updates_the_action_tab_heading_of_the_top_notebook(self):
        """_apply_action_decision_view の見出しが、上位Notebook の tab_action のタブ文言に反映される。"""
        gui = self.make_main(ui=("action",))
        heading = f"{BASE} (判断待ち3・2時間前)"
        self.apply(make_snapshot([make_row("A"), make_row("B"), make_row("C")], heading=heading))
        self.assertEqual(gui.notebook.tab(gui.tab_action, "text"), heading)

    def test_updated_heading_is_the_second_top_tab(self):
        """更新された見出しは上位Notebook の2番目のタブ (index 1) の文言として見える。"""
        gui = self.make_main(ui=("action",))
        heading = f"{BASE} (判断待ち1・5分前)"
        self.apply(make_snapshot([make_row("A")], heading=heading))
        self.assertEqual(gui.notebook.tab(1, "text"), heading)

    def test_failure_heading_also_reaches_the_top_notebook_tab(self):
        """集計失敗 (heading の無い snapshot) の「読込失敗」見出しも tab_action のタブ文言に出る。"""
        gui = self.make_main(ui=("action",))
        self.apply({"error": "テスト用の失敗"})
        self.assertEqual(self.tab_text(), f"{BASE} (判断待ち?・読込失敗)")

    def test_heading_update_leaves_the_other_tab_texts_alone(self):
        """見出しの更新で、他の上位タブ・入れ子のタブの文言は変わらない。"""
        gui = self.make_main(ui=("action",))
        self.apply(make_snapshot([make_row("A")], heading=f"{BASE} (判断待ち1・5分前)"))
        self.assertEqual([t for i, t in enumerate(tab_texts(gui.notebook)) if i != 1], [T_SEARCH, T_WEEKLY, T_REVIEW])
        self.assertEqual(tab_texts(gui.nb_weekly), WEEKLY_TEXTS)

    def test_heading_update_works_while_the_weekly_tab_is_selected(self):
        """毎週(俯瞰)タブを開いている間 (アクションが見えていない間) でも、見出しは更新される。"""
        gui = self.make_main(ui=("action",))
        gui.notebook.select(gui.nb_weekly)
        self.settle(0.1)
        heading = f"{BASE} (判断待ち1・WEEKLY)"
        self.apply(make_snapshot([make_row("A")], heading=heading))
        self.assertEqual(self.tab_text(), heading)

    def test_heading_update_does_not_change_the_selected_tabs(self):
        """見出しの更新は、上位Notebook・入れ子Notebook どちらの選択タブも変えない。"""
        gui = self.make_main(ui=("action",))
        gui.notebook.select(gui.nb_weekly)
        gui.nb_weekly.select(gui.tab_staff)
        self.settle(0.1)
        self.apply(make_snapshot([make_row("A")], heading=f"{BASE} (判断待ち1・KEEP)"))
        self.assertEqual(gui.notebook.select(), str(gui.nb_weekly))
        self.assertEqual(gui.nb_weekly.select(), str(gui.tab_staff))

    # ---- 短縮見出しの判定 (上位Notebook のタブ数が4) ----------------------
    def need_px(self, heading):
        """上位Notebook の全タブの文言幅 (TkDefaultFont.measure + ACTION_TAB_PADDING_PX/タブ)。アクションは heading で計算。"""
        font = tkfont.nametofont("TkDefaultFont")
        pad = a1gui._const("ACTION_TAB_PADDING_PX")
        total = 0
        for tab in self.gui.notebook.tabs():
            text = heading if str(tab) == str(self.gui.tab_action) else self.gui.notebook.tab(tab, "text")
            total += font.measure(text) + pad
        return total

    def need_px_old_six(self, heading):
        """旧構成 (6タブを平らに並べた) の場合の必要幅 (この構成との区別用)。"""
        font = tkfont.nametofont("TkDefaultFont")
        pad = a1gui._const("ACTION_TAB_PADDING_PX")
        texts = [T_SEARCH, T_PROJECT, T_STAFF, T_COCKPIT, heading, T_REVIEW]
        return sum(font.measure(t) + pad for t in texts)

    def resize(self, notebook_width):
        """上位Notebook の幅が notebook_width になるよう root の幅を決める (pack の padx=5 が左右にある分を足す)。"""
        gui = self.gui
        gui.root.geometry(f"{notebook_width + 10}x600+0+0")
        gui.root.update()
        gui.root.update_idletasks()
        got = gui.notebook.winfo_width()
        if abs(got - notebook_width) > 40:
            self.skipTest(f"上位Notebook の幅を {notebook_width}px にできない (実際 {got}px): ウィンドウマネージャ依存")

    def choose(self, heading=None, compact=None):
        return self.gui._choose_action_tab_heading(self.LONG if heading is None else heading,
                                                   self.COMPACT if compact is None else compact)

    def test_choose_heading_precondition_four_top_tabs(self):
        """前提: 判定が数える上位Notebook のタブは4つ (入れ子の中の3タブは数えない)。"""
        gui = self.make_main(ui=("action",))
        self.assertEqual(len(gui.notebook.tabs()), 4)

    def test_wide_window_keeps_the_normal_heading(self):
        """4タブの必要幅 + 150px の幅なら通常の見出し。"""
        self.make_main(ui=("action",))
        self.resize(self.need_px(self.LONG) + 150)
        self.assertEqual(self.choose(), self.LONG)

    def test_narrow_window_switches_to_the_compact_heading(self):
        """4タブの必要幅 - 150px の幅なら短い見出し。"""
        self.make_main(ui=("action",))
        self.resize(max(self.need_px(self.LONG) - 150, 120))
        self.assertEqual(self.choose(), self.COMPACT)

    def test_threshold_follows_the_four_tab_widths(self):
        """境界 (4タブの必要幅) の前後 ±150px で通常/短縮が切り替わる。"""
        self.make_main(ui=("action",))
        need = self.need_px(self.LONG)
        self.resize(need + 150)
        self.assertEqual(self.choose(), self.LONG)
        self.resize(need - 150)
        self.assertEqual(self.choose(), self.COMPACT)

    def test_threshold_counts_four_tabs_not_the_old_six(self):
        """旧6タブ構成なら短縮になる幅 (4タブの必要幅と6タブの必要幅の中間) で、4タブ構成は通常の見出しのまま。"""
        self.make_main(ui=("action",))
        need4, need6 = self.need_px(self.LONG), self.need_px_old_six(self.LONG)
        self.assertGreater(need6 - need4, 200, "前提: 6タブ構成との差が小さすぎて区別できない")
        self.resize((need4 + need6) // 2)
        self.assertEqual(self.choose(), self.LONG, "上位Notebook のタブ数が4ではない (入れ子にまとまっていない) 疑い")

    def test_a_heading_that_fits_is_kept_in_a_narrow_window(self):
        """短い見出しは、狭い窓でも通常の見出しのまま (収まるときは短縮しない)。"""
        self.make_main(ui=("action",))
        short = f"{BASE} (判断待ち3・解析2時間前)"
        self.resize(self.need_px(short) + 150)
        self.assertEqual(self.choose(short, f"{BASE} ⚖3"), short)

    def test_apply_view_follows_the_window_width_on_the_production_tabs(self):
        """_apply_action_decision_view は幅に応じて通常→短縮→通常と、tab_action のタブ文言を切り替える。"""
        self.make_main(ui=("action",))
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

    def test_compact_heading_keeps_the_weekly_tab_text(self):
        """短縮見出しにしても「📅 毎週(俯瞰)」などの他のタブの文言は変わらない。"""
        gui = self.make_main(ui=("action",))
        self.resize(max(self.need_px(self.LONG) - 150, 120))
        self.apply(make_snapshot([make_row("A")], heading=self.LONG, heading_compact=self.COMPACT))
        self.assertEqual(self.tab_text(), self.COMPACT)
        self.assertEqual([t for i, t in enumerate(tab_texts(gui.notebook)) if i != 1], [T_SEARCH, T_WEEKLY, T_REVIEW])


class TestA1TabChangeOnProductionTabs(TabsCase):
    """<<NotebookTabChanged>>: アクションを選んだときだけ再読込。毎週タブ・入れ子の内側のタブでは走らない。"""

    def start(self):
        """アクションまで組んだ本番構成。再読込は「数えるだけ」に差し替え、起動時のイベントを流してから返す。"""
        gui = self.make_main(ui=("action",), record_refresh=True)
        self.drain()
        return gui

    def select_and_drain(self, nb, page):
        nb.select(page)
        self.drain()

    def test_no_refresh_runs_at_startup(self):
        """起動直後 (検索タブが選ばれている間) は、アクションの再読込は走らない。"""
        gui = self.start()
        self.assertTrue(gui.notebook.bind("<<NotebookTabChanged>>"), "前提: タブ切替のバインドがある")
        self.assertEqual(self.refreshes, [])

    def test_selecting_the_action_tab_triggers_exactly_one_refresh(self):
        """アクションタブを選ぶと、再読込がちょうど1回走る。"""
        gui = self.start()
        n0 = len(self.refreshes)
        self.select_and_drain(gui.notebook, gui.tab_action)
        self.assertEqual(len(self.refreshes) - n0, 1)

    def test_selecting_the_weekly_tab_does_not_trigger_a_refresh(self):
        """毎週(俯瞰)タブを選んでも再読込は走らない (アクションを選んだときと区別できる)。"""
        gui = self.start()
        self.select_and_drain(gui.notebook, gui.tab_action)
        n0 = len(self.refreshes)
        self.assertGreaterEqual(n0, 1, "前提: アクションを選ぶと再読込が数えられる")
        self.select_and_drain(gui.notebook, gui.nb_weekly)
        self.assertEqual(len(self.refreshes), n0, "毎週タブを選んだだけで再読込された")

    def test_selecting_inner_tabs_of_the_weekly_tab_does_not_trigger_a_refresh(self):
        """毎週タブを開いて、入れ子の内側のタブ (プロジェクト/スタッフ/コックピット) を選んでも再読込は走らない。"""
        gui = self.start()
        self.select_and_drain(gui.notebook, gui.tab_action)
        self.select_and_drain(gui.notebook, gui.nb_weekly)
        n0 = len(self.refreshes)
        self.assertGreaterEqual(n0, 1, "前提: アクションを選ぶと再読込が数えられる")
        for page in (gui.tab_staff, gui.tab_cockpit, gui.tab_project):
            with self.subTest(inner=gui.nb_weekly.tab(page, "text")):
                self.select_and_drain(gui.nb_weekly, page)
                self.assertEqual(len(self.refreshes), n0, "入れ子の内側のタブを選んだだけで再読込された")

    def test_selecting_an_inner_tab_while_the_action_tab_is_current_does_not_trigger_a_refresh(self):
        """アクションを選んだまま、入れ子Notebook の内側のタブを (プログラムから) 切り替えても再読込は走らない。"""
        gui = self.start()
        self.select_and_drain(gui.notebook, gui.tab_action)
        n0 = len(self.refreshes)
        self.assertGreaterEqual(n0, 1, "前提: アクションを選ぶと再読込が数えられる")
        for page in (gui.tab_staff, gui.tab_cockpit, gui.tab_project):
            with self.subTest(inner=gui.nb_weekly.tab(page, "text")):
                self.select_and_drain(gui.nb_weekly, page)
                self.assertEqual(len(self.refreshes), n0, "入れ子のタブ切替が上位Notebook のハンドラに届いた")
        self.assertEqual(gui.notebook.select(), str(gui.tab_action))

    def test_selecting_search_or_review_does_not_trigger_a_refresh(self):
        """検索・振り返りタブを選んでも再読込は走らない。"""
        gui = self.start()
        self.select_and_drain(gui.notebook, gui.tab_action)
        n0 = len(self.refreshes)
        self.assertGreaterEqual(n0, 1, "前提: アクションを選ぶと再読込が数えられる")
        for page in (gui.tab_review, gui.tab_search):
            with self.subTest(tab=gui.notebook.tab(page, "text")):
                self.select_and_drain(gui.notebook, page)
                self.assertEqual(len(self.refreshes), n0)

    def test_coming_back_to_the_action_tab_from_the_weekly_tab_triggers_a_refresh(self):
        """毎週タブ (と入れ子の内側) を見たあとアクションに戻ると、再読込がちょうど1回走る。"""
        gui = self.start()
        self.select_and_drain(gui.notebook, gui.nb_weekly)
        self.select_and_drain(gui.nb_weekly, gui.tab_cockpit)
        n0 = len(self.refreshes)
        self.select_and_drain(gui.notebook, gui.tab_action)
        self.assertEqual(len(self.refreshes) - n0, 1)

    def test_the_whole_tab_tour_refreshes_only_for_the_action_tab(self):
        """全タブを巡回 (検索→アクション→毎週→内側3つ→振り返り→アクション) すると、再読込はアクションを選んだ2回だけ。"""
        gui = self.start()
        for nb, page in ((gui.notebook, gui.tab_action), (gui.notebook, gui.nb_weekly),
                         (gui.nb_weekly, gui.tab_staff), (gui.nb_weekly, gui.tab_cockpit),
                         (gui.nb_weekly, gui.tab_project), (gui.notebook, gui.tab_review),
                         (gui.notebook, gui.tab_search), (gui.notebook, gui.tab_action)):
            self.select_and_drain(nb, page)
        self.assertEqual(len(self.refreshes), 2)


class TestA1EndToEndOnProductionTabs(TabsCase):
    """実ファイル・実 snapshot (A1 の合成データ) で、本番の構成の上の一覧と見出しが動く。"""

    def setup_loaded(self):
        self.seed_files()
        gui = self.make_main(ui=("action",))
        gui.notebook.select(gui.tab_action)
        self.load_real(3)
        self.assertEqual(self.row_ids(), [self.key("A"), self.key("B"), self.key("C")])
        return gui

    def test_real_files_fill_the_list_and_the_top_notebook_heading(self):
        """実ファイルを読むと、一覧が3行になり、上位Notebook の tab_action の見出しに件数と鮮度が出る。"""
        gui = self.setup_loaded()
        self.assertTrue(self.tab_text().startswith(f"{BASE} (判断待ち3・解析1時間前"), self.tab_text())
        self.assertEqual(gui.notebook.tab(1, "text"), self.tab_text())

    def test_periodic_style_refresh_updates_the_heading_while_the_weekly_tab_is_shown(self):
        """毎週タブを開いたまま (定期再読込と同じ) 再読込しても、見出しが更新され、選択タブは変わらない。"""
        self.seed_files()
        gui = self.make_main(ui=("action",))
        gui.notebook.select(gui.nb_weekly)
        gui.nb_weekly.select(gui.tab_staff)
        self.settle(0.1)
        gui._refresh_action_decision_view()
        ok = self.pump(lambda: self.tab_text().startswith(f"{BASE} (判断待ち3・"), timeout=8)
        self.assertTrue(ok, f"毎週タブの表示中に見出しが更新されない: {self.tab_text()!r}")
        self.assertEqual(gui.notebook.select(), str(gui.nb_weekly))
        self.assertEqual(gui.nb_weekly.select(), str(gui.tab_staff))

    def test_complete_button_works_inside_the_action_tab(self):
        """アクションタブの「✅ 完了にする」: 一覧から消え、見出しの件数も更新される (A1 のフローが本番の構成で動く)。"""
        gui = self.setup_loaded()
        self.select(self.key("A"), self.key("B"))
        self.button("完了にする").invoke()
        ok = self.pump(lambda: self.row_ids() == [self.key("C")], timeout=8)
        self.assertTrue(ok, f"完了後に一覧が再読込されない: {self.row_ids()}")
        self.assertTrue(self.pump(lambda: self.tab_text().startswith(f"{BASE} (判断待ち1・"), timeout=5),
                        f"見出しの件数が更新されない: {self.tab_text()}")
        self.assertEqual(tab_texts(gui.nb_weekly), WEEKLY_TEXTS)

    def test_selecting_the_action_tab_again_rereads_the_files(self):
        """毎週タブへ移ってから、ファイルを書き換えてアクションに戻ると、実際の再読込で一覧に反映される。"""
        gui = self.setup_loaded()
        gui.notebook.select(gui.nb_weekly)
        self.settle(0.2)
        oto().set_action_progress({self.key("C"): "ignored"})           # 別経路 (ブラウザ側) で C を無視にした
        gui.notebook.select(gui.tab_action)
        ok = self.pump(lambda: self.row_ids() == [self.key("A"), self.key("B")], timeout=8)
        self.assertTrue(ok, f"アクションに戻っても再読込されない: {self.row_ids()}")


class _ProductionTabsMixin:
    """A1 の GuiCase.make_gui のうち「Notebook と2つのフレームの手組み」だけを、本番の _build_main_tabs() に置き換える。
    それ以外 (スタブ・ステータス行・パネルの構築・選択・map) は A1 の make_gui と同じ (期待値は A1 のテストそのまま)。"""

    def make_gui(self, select_action=False, existing_widget=False, user_name="Ochi, Yuichi",
                 smtp="yuichi.ochi@example.com", build_panel=True, map_window=True):
        mod = oto()
        gui = mod.MailManagerGUI.__new__(mod.MailManagerGUI)
        root = tk.Tk()
        root.geometry("1100x800+0+0")
        root.report_callback_exception = lambda exc, val, tb: self.callback_errors.append(
            f"{exc.__name__}: {val}")
        gui.root = root
        self.gui = gui
        gui._build_main_tabs()                                  # ← A1 の手組み (notebook / tab_search / tab_action) の代わり
        gui.outlook = self.stub_outlook = a1gui.StubOutlook(user_name, smtp)
        gui.summarizer = a1gui.StubSummarizer()
        gui.reporter = a1gui.StubReporter()
        gui.v_action_prd = tk.StringVar(master=root, value="1週間")
        gui.v_action_sync_vba = tk.BooleanVar(master=root, value=False)
        gui.lbl_stat = ttk.Label(root, text="Ready")
        gui.lbl_stat.pack(side=tk.BOTTOM, fill=tk.X)
        gui.btn_run_action = ttk.Button(root, text="📋 アクション一覧を生成")
        gui.btn_reformat_action = ttk.Button(root, text="🎨 フォーマットのみ再生成")
        gui.threads = {}
        gui.selected = set()
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


def make_production_variants(namespace, base_classes):
    """base_classes (A1 のテストクラス) の各々について、本番の構成で動かす派生クラス (Production_<名前>) を namespace に追加する。"""
    for base in base_classes:
        name = f"Production_{base.__name__}"
        namespace[name] = type(name, (_ProductionTabsMixin, base), {
            "__module__": namespace.get("__name__", __name__),
            "__doc__": f"A1 の {base.__name__} を、手組みの Notebook ではなく _build_main_tabs() の構成で実行"})


# タブ・見出し・タブ切替に関わる A1 のテスト (パネル構築 / 見出しの反映 / 再読込 / タブ切替 / 短縮見出し)
make_production_variants(globals(), (
    a1gui.TestPanelBuild, a1gui.TestApplyView, a1gui.TestRefresh, a1gui.TestSpecGapTickAndTabChange,
    a1gui.TestChooseTabHeading, a1gui.TestSpecGapChooseTabHeading))


# ============================================================
# 4. 各 _ui_*_tab が入れ子の親フレームでも作れること
# ============================================================
class TestNestedTabBuilders(TabsCase):
    """_ui_project_tab / _ui_staff_tab / _ui_cockpit_tab を、入れ子Notebook の子フレームを親にして実際に呼ぶ。
    必要な属性は project_knowledge (staffs のキー) だけ (+ A1 のスタブ)。Linux/Xvfb で全て動く。"""

    def build_one(self, key):
        """app_like の本番構成を作り、key の _ui_*_tab だけを呼ぶ。(gui, 呼ぶ前のウィジェットのパス集合) を返す。"""
        gui = self.make_main(app_like=True)
        before = {str(w) for w in walk(gui.root)}
        getattr(gui, UI_METHODS[key])()
        gui.root.update()
        return gui, before

    def leaks(self, gui, before, frame):
        """呼んだ結果できたウィジェットのうち、frame の外にあるもの。"""
        return [str(w) for w in walk(gui.root) if str(w) not in before and not is_inside(w, frame)]

    def show_inner(self, gui, page):
        gui.notebook.select(gui.nb_weekly)
        gui.nb_weekly.select(page)
        self.settle(0.1)

    # ---- プロジェクト俯瞰 -----------------------------------------------
    def test_project_builder_fills_its_nested_frame(self):
        """_ui_project_tab() が例外なく動き、tab_project (入れ子の子フレーム) に子ウィジェットが作られる。"""
        gui, _ = self.build_one("project")
        self.assertTrue(gui.tab_project.winfo_children())

    def test_project_builder_creates_widgets_only_inside_its_frame(self):
        """_ui_project_tab() が作るウィジェットは全て tab_project の中 (他のタブや root には漏れない)。"""
        gui, before = self.build_one("project")
        self.assertEqual(self.leaks(gui, before, gui.tab_project), [])

    def test_project_builder_keeps_its_main_widgets(self):
        """プロジェクト俯瞰の主な部品 (タイトル・対象プロジェクト枠・レポート生成ボタン) が tab_project の中にある。"""
        gui, _ = self.build_one("project")
        for fragment in ("プロジェクト分析・サマリ生成", "対象プロジェクト", "プロジェクト俯瞰レポートを生成"):
            with self.subTest(part=fragment):
                self.assertTrue(find_text(gui.tab_project, fragment), f"{fragment} が tab_project に無い")

    def test_project_page_is_shown_when_its_nested_tab_is_selected(self):
        """毎週タブ→プロジェクト俯瞰を選ぶと、レポート生成ボタンが実際に表示される。"""
        gui, _ = self.build_one("project")
        self.show_inner(gui, gui.tab_project)
        button = find_text(gui.tab_project, "プロジェクト俯瞰レポートを生成", (ttk.Button,))[0]
        self.assertTrue(button.winfo_viewable())

    # ---- スタッフ俯瞰 ---------------------------------------------------
    def test_staff_builder_fills_its_nested_frame(self):
        """_ui_staff_tab() が例外なく動き、tab_staff (入れ子の子フレーム) に子ウィジェットが作られる。"""
        gui, _ = self.build_one("staff")
        self.assertTrue(gui.tab_staff.winfo_children())

    def test_staff_builder_creates_widgets_only_inside_its_frame(self):
        """_ui_staff_tab() が作るウィジェットは全て tab_staff の中。"""
        gui, before = self.build_one("staff")
        self.assertEqual(self.leaks(gui, before, gui.tab_staff), [])

    def test_staff_builder_keeps_its_main_widgets(self):
        """スタッフ俯瞰の主な部品 (タイトル・対象スタッフ枠・レポート生成ボタン) が tab_staff の中にある。"""
        gui, _ = self.build_one("staff")
        for fragment in ("スタッフ活動分析・サマリ生成", "対象スタッフ", "スタッフの活動俯瞰レポートを生成"):
            with self.subTest(part=fragment):
                self.assertTrue(find_text(gui.tab_staff, fragment), f"{fragment} が tab_staff に無い")

    def test_staff_combobox_lists_the_staff_names_of_project_knowledge(self):
        """スタッフ名のプルダウンに project_knowledge の staffs のキーが入る (中身は変わっていない)。"""
        gui, _ = self.build_one("staff")
        self.assertTrue(is_inside(gui.cb_staff_name, gui.tab_staff))
        self.assertEqual(tuple(gui.cb_staff_name["values"]), ("Nakai", "Saji"))

    def test_staff_page_is_shown_when_its_nested_tab_is_selected(self):
        """毎週タブ→スタッフ俯瞰を選ぶと、レポート生成ボタンが実際に表示され、プロジェクト俯瞰の部品は隠れる。"""
        gui, _ = self.build_one("staff")
        self.show_inner(gui, gui.tab_staff)
        button = find_text(gui.tab_staff, "スタッフの活動俯瞰レポートを生成", (ttk.Button,))[0]
        self.assertTrue(button.winfo_viewable())
        self.assertFalse(gui.tab_project.winfo_viewable())

    # ---- 統括コックピット -----------------------------------------------
    def test_cockpit_builder_fills_its_nested_frame(self):
        """_ui_cockpit_tab() が例外なく動き、tab_cockpit (入れ子の子フレーム) に子ウィジェットが作られる。"""
        gui, _ = self.build_one("cockpit")
        self.assertTrue(gui.tab_cockpit.winfo_children())

    def test_cockpit_builder_creates_widgets_only_inside_its_frame(self):
        """_ui_cockpit_tab() が作るウィジェットは全て tab_cockpit の中。"""
        gui, before = self.build_one("cockpit")
        self.assertEqual(self.leaks(gui, before, gui.tab_cockpit), [])

    def test_cockpit_builder_keeps_its_main_widgets(self):
        """コックピットの主な部品 (サマリ/同期/v2 のボタン・4つのセクション枠) が tab_cockpit の中にある。"""
        gui, _ = self.build_one("cockpit")
        for fragment in ("既存状況をサマリ", "最新状況に更新", "統括コックピット v2",
                         "アラート", "アクション・キュー", "周知・ガバナンス", "停滞監視"):
            with self.subTest(part=fragment):
                self.assertTrue(find_text(gui.tab_cockpit, fragment), f"{fragment} が tab_cockpit に無い")

    def test_cockpit_page_is_shown_when_its_nested_tab_is_selected(self):
        """毎週タブ→統括コックピットを選ぶと、サマリのボタンが実際に表示される。"""
        gui, _ = self.build_one("cockpit")
        self.show_inner(gui, gui.tab_cockpit)
        button = find_text(gui.tab_cockpit, "既存状況をサマリ", (ttk.Button,))[0]
        self.assertTrue(button.winfo_viewable())

    # ---- まとめて ---------------------------------------------------------
    def test_each_builder_only_fills_its_own_frame(self):
        """3つの builder を順に呼ぶと、そのたびに自分のフレームだけが埋まり、他のフレームは空のまま。"""
        gui = self.make_main(app_like=True)
        frames = ("tab_search", "tab_action", "tab_review", "tab_project", "tab_staff", "tab_cockpit")
        built = []
        for key, frame in (("project", "tab_project"), ("staff", "tab_staff"), ("cockpit", "tab_cockpit")):
            getattr(gui, UI_METHODS[key])()
            built.append(frame)
            with self.subTest(after=key):
                for name in frames:
                    self.assertEqual(bool(getattr(gui, name).winfo_children()), name in built,
                                     f"{key} を呼んだ後の {name}")

    def test_all_six_builders_run_in_the_init_order_on_the_production_tabs(self):
        """__init__ と同じ順に6つの _ui_*_tab を呼んでも例外なく、6つのフレーム全てに部品ができる。"""
        gui = self.make_main(ui=UI_ORDER)
        for name in ("tab_search", "tab_action", "tab_review", "tab_project", "tab_staff", "tab_cockpit"):
            with self.subTest(frame=name):
                self.assertTrue(getattr(gui, name).winfo_children())

    def test_building_all_six_keeps_the_tab_layout_and_the_start_tab(self):
        """6つを作り終えても、タブの数・文言・並びは変わらず、起動時の選択は「🔍 検索 / 整理」のまま。"""
        gui = self.make_main(ui=UI_ORDER)
        self.drain()
        self.assertEqual(tab_texts(gui.notebook), TOP_TEXTS)
        self.assertEqual(tab_texts(gui.nb_weekly), WEEKLY_TEXTS)
        self.assertEqual(gui.notebook.select(), str(gui.tab_search))
        self.assertEqual(gui.nb_weekly.select(), str(gui.tab_project))

    def test_building_the_ui_tabs_does_not_call_select_with_a_tab(self):
        """6つの _ui_*_tab を作る間も、Notebook.select にタブを渡す呼び出しは無い (起動タブは変えない)。"""
        gui = self.make_main(app_like=True)
        calls = []
        orig = ttk.Notebook.select

        def spy(nb, *args, **kwargs):
            calls.append((str(nb), args, kwargs))
            return orig(nb, *args, **kwargs)

        with mock.patch.object(ttk.Notebook, "select", spy):
            for name in UI_ORDER:
                getattr(gui, UI_METHODS[name])()
        self.assertEqual([c for c in calls if c[1] or c[2]], [])


# ============================================================
# 5. 範囲ガード (_03 → _04 で変えてよい既存メソッドは __init__ だけ。追加は _build_main_tabs だけ)
# ============================================================
INIT = "MailManagerGUI.__init__"
BUILD = "MailManagerGUI._build_main_tabs"
ALLOWED_TO_CHANGE = {INIT}
NEW_METHODS = {BUILD}
UI_CALL_NAMES = ("_ui_search_tab", "_ui_project_tab", "_ui_staff_tab", "_ui_cockpit_tab", "_ui_action_tab",
                 "_ui_review_tab")
# 仕様が「変えない」とするもの: 各 _ui_*_tab (中身は変えない) と、A1 の見出し・タブ切替の処理 (そのまま動く)
UNCHANGED_BY_SPEC = tuple(f"MailManagerGUI.{n}" for n in UI_CALL_NAMES + (
    "_choose_action_tab_heading", "_apply_action_decision_view", "_on_action_decision_tab_changed",
    "_refresh_action_decision_view", "_ui_action_decision_panel", "_action_decision_tick",
    "_render_action_decision_rows"))
TAB_FRAME_NAMES = ("tab_search", "tab_project", "tab_staff", "tab_cockpit", "tab_action", "tab_review")


def _is_docstring(node):
    return (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str))


@functools.lru_cache(maxsize=None)
def _parse(path):
    with open(path, "r", encoding="utf-8") as f:
        return ast.parse(f.read())


def method_node(path, cls_name, meth):
    for node in _parse(path).body:
        if isinstance(node, ast.ClassDef) and node.name == cls_name:
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub.name == meth:
                    return sub
    raise AssertionError(f"{cls_name}.{meth} が {os.path.basename(path)} に無い")


def _index_source(path):
    """関数/メソッド・定数・import・その他のトップレベル文・クラスの骨格を AST ダンプ (行番号・コメント・空白は無視) で索引化する。"""
    dump = ast.dump
    funcs, consts, imports, others, shells = {}, {}, set(), [], {}

    def add_consts(prefix, node):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for t in targets:
            if isinstance(t, ast.Name):
                consts[prefix + t.id] = dump(node)

    for node in _parse(path).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs[node.name] = dump(node)
        elif isinstance(node, ast.ClassDef):
            rest = []
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    funcs[f"{node.name}.{sub.name}"] = dump(sub)
                elif not _is_docstring(sub):
                    rest.append(dump(sub))
                    if isinstance(sub, (ast.Assign, ast.AnnAssign)):
                        add_consts(f"{node.name}.", sub)
            header = ([dump(x) for x in node.bases], [dump(x) for x in node.keywords],
                      [dump(x) for x in node.decorator_list])
            shells[node.name] = (header, rest)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            add_consts("", node)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.add(dump(node))
        elif not _is_docstring(node):
            others.append(dump(node))
    return funcs, consts, imports, others, shells


def short_diff(a, b, limit=30):
    lines = list(difflib.unified_diff(a, b, "old", "new", lineterm="", n=0))
    return "\n".join(lines[:limit])


def self_call_name(stmt):
    """`self.<名前>(...)` だけの式文ならその <名前>、そうでなければ None。"""
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        f = stmt.value.func
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "self":
            return f.attr
    return None


def self_assigned_attrs(fn):
    """fn の中で `self.<名前> = ...` (代入・複数代入・拡張代入) される <名前> の一覧。"""
    return [n.attr for n in ast.walk(fn)
            if isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Store)
            and isinstance(n.value, ast.Name) and n.value.id == "self"]


def _is_self_attr(node, attr):
    return (isinstance(node, ast.Attribute) and node.attr == attr
            and isinstance(node.value, ast.Name) and node.value.id == "self")


def _is_notebook_add(stmt):
    """`self.notebook.add(...)` の式文か。"""
    if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)):
        return False
    f = stmt.value.func
    return isinstance(f, ast.Attribute) and f.attr == "add" and _is_self_attr(f.value, "notebook")


def _is_notebook_pack(stmt):
    if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)):
        return False
    f = stmt.value.func
    return isinstance(f, ast.Attribute) and f.attr == "pack" and _is_self_attr(f.value, "notebook")


_NOTEBOOK_CREATE = ast.dump(ast.parse("self.notebook = ttk.Notebook(self.root)").body[0])
_FRAME_CREATES = {ast.dump(ast.parse(f"self.{n} = ttk.Frame(self.notebook)").body[0]) for n in TAB_FRAME_NAMES}
_BUILD_CALL = ast.dump(ast.parse("self._build_main_tabs()").body[0])


def old_notebook_block(old_body):
    """旧 __init__ の本文から「Notebook作成〜6つの add」の範囲 (開始, 終了) を返す。想定と違えば AssertionError。"""
    starts = [i for i, s in enumerate(old_body) if ast.dump(s) == _NOTEBOOK_CREATE]
    adds = [i for i, s in enumerate(old_body) if _is_notebook_add(s)]
    if len(starts) != 1:
        raise AssertionError(f"旧版に self.notebook = ttk.Notebook(self.root) が {len(starts)} 個ある")
    if len(adds) != 6:
        raise AssertionError(f"旧版の self.notebook.add(...) が {len(adds)} 個 (6個のはず)")
    i0, i1 = starts[0], adds[-1]
    block = old_body[i0:i1 + 1]
    kinds = Counter()
    for s in block:
        if ast.dump(s) == _NOTEBOOK_CREATE:
            kinds["create"] += 1
        elif _is_notebook_pack(s):
            kinds["pack"] += 1
        elif ast.dump(s) in _FRAME_CREATES:
            kinds["frame"] += 1
        elif _is_notebook_add(s):
            kinds["add"] += 1
        else:
            kinds["other"] += 1
    if kinds != Counter(create=1, pack=1, frame=6, add=6):
        raise AssertionError(f"旧版の Notebook ブロックが想定 (作成1・pack1・フレーム6・add6) と違う: {dict(kinds)}")
    return i0, i1


class TestScopeGuardA6(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.target = _loader.rev_path(NEW_REV)
        cls.baseline = _loader.rev_path(OLD_REV)
        if not (os.path.isfile(cls.target) and os.path.isfile(cls.baseline)):
            raise unittest.SkipTest(f"A6のリビジョン対({OLD_REV} / {NEW_REV})が無い")
        cls.old = _index_source(cls.baseline)
        cls.new = _index_source(cls.target)
        cls.old_init = method_node(cls.baseline, "MailManagerGUI", "__init__")
        cls.new_init = method_node(cls.target, "MailManagerGUI", "__init__")

    # ---- 関数・メソッド -----------------------------------------------
    def test_no_existing_function_or_method_is_removed(self):
        """既存の関数/メソッドは1つも消えていない。"""
        removed = sorted(n for n in self.old[0] if n not in self.new[0])
        self.assertEqual(removed, [], f"既存の関数/メソッドが消えている: {removed}")

    def test_only_init_changed_among_the_existing_functions(self):
        """既存の関数/メソッドのうち、変更されているのは MailManagerGUI.__init__ だけ。"""
        old_f, new_f = self.old[0], self.new[0]
        changed = sorted(n for n, s in old_f.items() if n in new_f and new_f[n] != s)
        self.assertEqual(sorted(set(changed) - ALLOWED_TO_CHANGE), [], f"仕様で許可されていない既存関数/メソッドの変更: {changed}")

    def test_init_was_actually_changed(self):
        """MailManagerGUI.__init__ は実際に変更されている (A6 の変更が入っている)。"""
        self.assertNotEqual(self.old[0][INIT], self.new[0][INIT])

    def test_only_build_main_tabs_was_added(self):
        """追加された関数/メソッドは MailManagerGUI._build_main_tabs だけ。"""
        added = sorted(set(self.new[0]) - set(self.old[0]))
        self.assertEqual(added, sorted(NEW_METHODS), f"仕様に無い関数/メソッドが追加されている: {added}")

    def test_build_main_tabs_is_an_instance_method_taking_only_self(self):
        """_build_main_tabs は MailManagerGUI のインスタンスメソッドで、引数は self だけ。"""
        fn = method_node(self.target, "MailManagerGUI", "_build_main_tabs")
        a = fn.args
        self.assertEqual([x.arg for x in a.args], ["self"])
        self.assertEqual((a.posonlyargs, a.vararg, a.kwonlyargs, a.kwarg, a.defaults, a.kw_defaults), ([], None, [], None, [], []))
        self.assertEqual(fn.decorator_list, [])

    def test_functions_the_spec_says_are_unchanged_are_identical(self):
        """各 _ui_*_tab と A1 の見出し・タブ切替の処理は、旧版と AST が完全に同じ。"""
        for q in UNCHANGED_BY_SPEC:
            with self.subTest(name=q):
                self.assertIn(q, self.old[0], f"{q} が旧版に見つからない (比較の前提が崩れた)")
                self.assertIn(q, self.new[0])
                self.assertEqual(self.new[0][q], self.old[0][q], f"{q} が変更されている")

    # ---- 定数・import・骨格 ------------------------------------------
    def test_no_constant_is_added_removed_or_changed(self):
        """定数 (モジュール/クラス) の追加・削除・変更は無い (ACTION_TAB_BASE_TEXT も含む)。"""
        old_c, new_c = self.old[1], self.new[1]
        removed = sorted(n for n in old_c if n not in new_c)
        added = sorted(n for n in new_c if n not in old_c)
        changed = sorted(n for n, s in old_c.items() if n in new_c and new_c[n] != s)
        self.assertEqual((removed, added, changed), ([], [], []),
                         f"定数の変更: 削除={removed} 追加={added} 変更={changed}")

    def test_existing_imports_are_kept(self):
        """既存の import は1つも消えていない。"""
        missing = self.old[2] - self.new[2]
        self.assertEqual(len(missing), 0, f"既存の import が {len(missing)} 件消えている")

    def test_other_top_level_statements_and_class_skeletons_are_unchanged(self):
        """関数/定数/import 以外のトップレベル文と、クラスの骨格 (継承・デコレータ・クラス直下の文) は変わらない。"""
        self.assertEqual(self.old[3], self.new[3], "関数/定数/import 以外のトップレベル文が変わっている")
        for cls_name, shell in self.old[4].items():
            with self.subTest(cls=cls_name):
                self.assertIn(cls_name, self.new[4])
                self.assertEqual(shell, self.new[4].get(cls_name),
                                 f"クラス {cls_name} の骨格(継承・デコレータ・クラス直下の文)が変わっている")

    def test_no_class_is_added_or_removed(self):
        """トップレベルのクラスの追加・削除は無い (追加は _build_main_tabs だけ)。"""
        self.assertEqual(sorted(self.new[4]), sorted(self.old[4]))

    # ---- __init__ の中身 ---------------------------------------------
    def test_init_signature_is_unchanged(self):
        """__init__ の引数 (self だけ) とデコレータは変わらない。"""
        self.assertEqual(ast.dump(self.new_init.args), ast.dump(self.old_init.args))
        self.assertEqual([ast.dump(d) for d in self.new_init.decorator_list],
                         [ast.dump(d) for d in self.old_init.decorator_list])

    def test_old_init_has_the_notebook_block_this_guard_expects(self):
        """(比較元の健全性) 旧 __init__ には「Notebook作成・pack・6フレーム・6つの add」が連続して1か所ある。"""
        i0, i1 = old_notebook_block(self.old_init.body)
        self.assertEqual(i1 - i0 + 1, 14)

    def test_init_differs_from_the_old_one_only_by_the_replaced_notebook_block(self):
        """新 __init__ = 旧 __init__ の「Notebook作成〜6つの add」を self._build_main_tabs() 1行に置き換えただけ (他の行は不変)。"""
        old_body, new_body = self.old_init.body, self.new_init.body
        i0, i1 = old_notebook_block(old_body)
        expected = [ast.dump(s) for s in old_body[:i0]] + [_BUILD_CALL] + [ast.dump(s) for s in old_body[i1 + 1:]]
        actual = [ast.dump(s) for s in new_body]
        if actual != expected:
            exp_src = [ast.unparse(s) for s in old_body[:i0]] + ["self._build_main_tabs()"] + \
                      [ast.unparse(s) for s in old_body[i1 + 1:]]
            self.fail("__init__ が「ブロックの置換だけ」になっていない:\n" +
                      short_diff([x.splitlines()[0] for x in exp_src], [ast.unparse(s).splitlines()[0] for s in new_body]))

    def test_init_calls_build_main_tabs_exactly_once_as_a_plain_statement(self):
        """__init__ の直下に self._build_main_tabs() の式文がちょうど1つ (if/try の中ではない)。"""
        calls = [s for s in self.new_init.body if self_call_name(s) == "_build_main_tabs"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(ast.dump(calls[0]), _BUILD_CALL, "引数なしの self._build_main_tabs() ではない")

    def test_build_main_tabs_is_called_before_the_first_ui_tab_call(self):
        """self._build_main_tabs() は、最初の _ui_*_tab() の呼び出しより前に置かれている。"""
        names = [self_call_name(s) for s in self.new_init.body]
        self.assertIn("_build_main_tabs", names)
        first_ui = min(i for i, n in enumerate(names) if n in UI_CALL_NAMES)
        self.assertLess(names.index("_build_main_tabs"), first_ui)

    def test_the_six_ui_tab_calls_keep_their_order(self):
        """__init__ の _ui_search_tab → project → staff → cockpit → action → review の6つの呼び出しは、順序も回数もそのまま。"""
        new_order = [n for n in map(self_call_name, self.new_init.body) if n in UI_CALL_NAMES]
        old_order = [n for n in map(self_call_name, self.old_init.body) if n in UI_CALL_NAMES]
        self.assertEqual(old_order, list(UI_CALL_NAMES), "(比較元の前提) 旧版の呼び出し順が仕様と違う")
        self.assertEqual(new_order, list(UI_CALL_NAMES))

    def test_init_no_longer_creates_the_notebook_or_the_tab_frames(self):
        """__init__ には Notebook・各タブ用フレームを作る代入が残っていない (作成は _build_main_tabs へ移った)。"""
        names = {"notebook", "nb_weekly", *TAB_FRAME_NAMES}
        self.assertEqual(sorted(set(self_assigned_attrs(self.new_init)) & names), [])

    # ---- _build_main_tabs の中身 (機械的な検査。中身は読まない) ----------
    def test_build_main_tabs_does_not_call_the_ui_tab_builders(self):
        """_build_main_tabs の中に self._ui_*_tab() の呼び出しは無い。"""
        fn = method_node(self.target, "MailManagerGUI", "_build_main_tabs")
        calls = sorted({n.func.attr for n in ast.walk(fn)
                        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and isinstance(n.func.value, ast.Name) and n.func.value.id == "self"
                        and n.func.attr in UI_CALL_NAMES})
        self.assertEqual(calls, [])

    def test_build_main_tabs_has_no_select_call(self):
        """_build_main_tabs の中に .select(...) の呼び出しは無い (起動時に開くタブを変えない)。"""
        fn = method_node(self.target, "MailManagerGUI", "_build_main_tabs")
        selects = [ast.unparse(n) for n in ast.walk(fn)
                   if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "select"]
        self.assertEqual(selects, [])


class TestSpecGapScopeGuardA6(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        old_p = _loader.rev_path(OLD_REV)
        new_p = _loader.rev_path(NEW_REV)
        if not (os.path.isfile(old_p) and os.path.isfile(new_p)):
            raise unittest.SkipTest(f"A6のリビジョン対({OLD_REV} / {NEW_REV})が無い")
        cls.old = _index_source(old_p)
        cls.new = _index_source(new_p)

    def test_no_new_import_was_added(self):
        # 仕様の「追加は _build_main_tabs だけ (新しい定数・関数なし)」に import は明記されていない。
        # 入れ子Notebook は既存の ttk で作れるので、新しい import は不要 (追加は仕様外) と自然に解釈する
        added = self.new[2] - self.old[2]
        self.assertEqual(len(added), 0, f"仕様に無い import が {len(added)} 件追加されている")


if __name__ == "__main__":
    unittest.main(verbosity=2)
