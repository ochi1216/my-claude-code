# -*- coding: utf-8 -*-
"""A2 / B1 回帰テスト: 5つの入口の「💰 APIコスト概算」が、毎回「今回の実行分」になること。

B1 の不具合: レポート末尾の「💰 APIコスト概算」が、アプリを起動してからの累計になり、実行のたびに増えていた
(MailSummarizer のトークン合計が、入口の開始時に0へ戻っていなかった)。
対象の入口 (MailManagerGUI): _refresh_cockpit / _sync_and_refresh_cockpit / _run_cockpit_v2 /
_run_action_dashboard / _run_review。

作り
  - MailSummarizer / HTMLReportGenerator は実クラス、入口(MailManagerGUI)は実メソッドをそのまま動かす。
    偽物にするのは「Outlook からのメール取得」と「AI の応答」だけ(解析メソッドは「AI呼び出しをn回行って
    最小のデータを返す」ものに差し替えるが、トークンを数える経路 _run_genai_call_with_schema は実物)。
  - 1回のAI呼び出し = 入力6000 / 回答800 / 思考2500 / total9300 (仮定)。出力課金は 回答+思考 = 3300。
    期待する費用は、呼び出し回数から calc_api_cost_yen で計算する(金額は直書きしない)。
  - レポートに書かれた費用表示 (円, 入力, 出力) を、実際に出力された HTML から読む。

テスト
  1. TestPremise            : 前提の確認 (偽AI応答1回で累計がいくつ増えるか)。GUIなし。
  2. TestEntrypointCost     : 5つの入口それぞれ。開始前に「前回までの累計」を入れ、同じ処理を続けて実行しても、
                              毎回の費用表示が「1回分」で変わらない。
  3. TestSequentialFlows    : 対照。アクション生成とコックピットv2を、1つずつ続けて実行すれば、各画面は自分の分だけを表示する。
  4. TestOverlappingFlows   : 既知の制限の記録 (expectedFailure)。アクション生成の途中でv2を始めると表示がずれる。
                              3. と同じ手順・同じ判定で、違いは「重ねるかどうか」だけ。直ったら「想定外の成功」になる。

決定的・高速にするための方針
  - 固定時間の sleep は使わない。ワーカースレッドの終了は pump (mainloop) で待つ。重ねる場合は Event で止める位置を決める。
  - 日付・時刻に依存しない(振り返りの月などは固定値。レポートのファイル名の時刻は使わない)。
  - 各テストは空の一時cwd・新しいGUIで動き、他のテストの結果や実行順に依存しない。
  - ネットワーク・実Outlook・実ブラウザには触れない (webbrowser.open は記録だけ)。

実行 (outlook_total_organizer フォルダで):  xvfb-run -a python tests/run_tests.py a2_entrypoints
  (tkinter / ディスプレイが無い環境では GUI を使うテストは自動でスキップされる。OTO_TARGET でリビジョンを選べる)
"""
import copy
import os
import re
import threading
import unittest
from unittest import mock

import _loader
import test_a1_gui_smoke as a1gui          # GUI ハーネス (GuiCase / StubOutlook) を再利用する


def oto():
    return _loader.load()


# ============================================================
# 仮定と期待値
# ============================================================
# 偽のAI応答が返す、1回のAI呼び出しの使用量 (Gemini の usageMetadata 形式)
USAGE = {"promptTokenCount": 6000, "candidatesTokenCount": 800, "thoughtsTokenCount": 2500, "totalTokenCount": 9300}
CALL_IN = USAGE["promptTokenCount"]                                       # 1回あたりの入力 = 6000
CALL_OUT = USAGE["candidatesTokenCount"] + USAGE["thoughtsTokenCount"]    # 出力課金は 回答+思考 = 3300

N_CALLS = 6          # 入口が行う「メインのAI解析」の呼び出し回数
PJ_CALLS = 2         # _sync_and_refresh_cockpit のプロジェクト分析: 1プロジェクトあたりの呼び出し回数
RUNS = 3             # 同じ入口を連続で実行する回数
PREVIOUS_IN = 777_000     # 「前回までの累計」を模した、開始前のトークン合計
PREVIOUS_OUT = 555_000
FLOW_TIMEOUT = 20    # 1つの入口が終わるのを待つ上限(秒)。正常時は待たずに終わる

# レポート末尾の費用表示 (6つのレポート共通の書式)。注記(単価未登録モデル)が付く場合があるので ) で止める
COST_LINE = re.compile(r"💰 APIコスト概算: 約 (?P<yen>[0-9.]+) 円 \(In:(?P<inp>\d+) / Out:(?P<out>\d+)\)")


def one_run_cost(calls):
    """AI呼び出しが calls 回の処理を「1回分」として表示したときの費用表示 (円, 入力, 出力)。
    金額は calc_api_cost_yen から式で求める (一時cwd = 設定ファイル無し の中で呼ぶこと)。"""
    total_in, total_out = calls * CALL_IN, calls * CALL_OUT
    return (oto().calc_api_cost_yen(total_in, total_out), total_in, total_out)


# ============================================================
# 偽物 (Outlook の取得と AI の応答だけ)
# ============================================================
class Outlook(a1gui.StubOutlook):
    """入口が呼ぶ Outlook のメソッドだけを足したスタブ (メールは0件)。COM・ネットワークには触れない。
    これ以外の属性に触れると StubOutlook が AttributeError にする。"""

    def get_project_mails(self, proj, days, include_sent=False):
        return []

    def search_mails_fast(self, *args, **kwargs):
        return []

    def get_review_mails_for_month(self, year, month, progress_callback=None):
        return []

    def get_review_calendar_events(self, year, month, progress_callback=None):
        return []


def make_summarizer():
    """実クラスの MailSummarizer を作り、AI(client.models.generate_content)だけを、毎回 USAGE を返す偽物にする。
    戻り値 (summarizer, burn)。burn(n) は、実際のトークン計測の経路 (_run_genai_call_with_schema) を通して
    AI呼び出しを n 回行う。"""
    mod = oto()
    summarizer = mod.MailSummarizer("dummy", "gemini-2.5-flash")

    def fake_generate_content(model=None, contents=None, config=None):
        raw = {"candidates": [{"content": {"parts": [{"text": '{"ok": 1}'}]}}], "usageMetadata": dict(USAGE)}
        return mod._CommonGeminiResponse(raw)

    summarizer.client.models.generate_content = fake_generate_content

    def burn(n):
        for _ in range(n):
            summarizer._run_genai_call_with_schema("prompt", {"type": "OBJECT"})

    return summarizer, burn


# ============================================================
# 1. 前提の確認
# ============================================================
class TestPremise(unittest.TestCase):
    def test_one_fake_ai_call_adds_the_assumed_tokens_to_the_totals(self):
        """前提の確認 (GUIなし): 偽のAI応答1回で MailSummarizer の累計は 入力6000 / 出力3300 だけ増え、n回なら n 倍になる。

        他のテストの期待値(円)は、この前提から calc_api_cost_yen で計算している。前提が崩れたとき
        (出力の数え方が変わった等)に、入口の不具合と取り違えないよう、ここで原因が分かるようにする。
        """
        self.assertEqual(USAGE["totalTokenCount"], CALL_IN + CALL_OUT, "仮定の使用量が自己矛盾している")
        summarizer, burn = make_summarizer()
        self.assertEqual((summarizer.total_input_tokens, summarizer.total_output_tokens), (0, 0))
        burn(1)
        self.assertEqual((summarizer.total_input_tokens, summarizer.total_output_tokens), (CALL_IN, CALL_OUT))
        burn(2)
        self.assertEqual((summarizer.total_input_tokens, summarizer.total_output_tokens),
                         (3 * CALL_IN, 3 * CALL_OUT))


# ============================================================
# 共通フィクスチャ (入口を動かして、レポートの費用表示を読む)
# ============================================================
class EntrypointCase(a1gui.GuiCase):
    """入口 (MailManagerGUI の実メソッド) を動かし、開いたレポートの費用表示を読むための共通フィクスチャ。"""

    def setUp(self):
        self.opened = []                       # webbrowser.open を呼んだ (スレッド, レポートのパス)
        patcher = mock.patch("webbrowser.open", self._record_open)
        patcher.start()
        self.addCleanup(patcher.stop)          # GuiCase の後始末 (ワーカーの終了待ち) より後に外れるよう、先に登録する
        super().setUp()
        os.makedirs("json", exist_ok=True)     # 入口は json/ へ結果を保存する (空の一時cwdには無い)

    def _record_open(self, url, *args, **kwargs):
        self.opened.append((threading.current_thread(), url))
        return True

    # ---- GUI の組み立て -----------------------------------------------
    def build(self):
        """実クラスの MailSummarizer / HTMLReportGenerator と MailManagerGUI の実メソッドを使う GUI を作る。
        偽物は Outlook のメール取得と AI の応答だけ。解析メソッドは「AI呼び出しをn回行って最小のデータを返す」
        ものに差し替える (レポートを出力するために必要な最小のデータ)。"""
        mod = oto()
        gui = self.make_gui(select_action=True, build_panel=False)
        gui.outlook = Outlook()
        gui.summarizer, self.burn = make_summarizer()

        def analysis(n, result):
            def run(*args, **kwargs):
                self.burn(n)
                return copy.deepcopy(result)
            return run

        s = gui.summarizer
        s.summarize_action_dashboard = analysis(N_CALLS, {"action_cards": [], "threads": []})
        s.generate_cockpit_summary = analysis(N_CALLS, {})
        s.generate_cockpit_v2_data = analysis(N_CALLS, {})
        s.summarize_project_threads = analysis(PJ_CALLS, {})
        s.summarize_staff_threads = analysis(PJ_CALLS, {})
        s.generate_review_data = analysis(N_CALLS, {"generated_at": "x", "months": ["202609"], "persons": ["Ochi"],
                                                    "achievements": [], "raw_achievements": []})
        gui.reporter = mod.HTMLReportGenerator(os.path.join(os.getcwd(), "out"), 0)
        gui.project_knowledge = {"projects": {"P1": {}}, "staffs": {}}
        gui.cockpit_widgets = {}
        for name in ("btn_sync_cockpit", "btn_refresh_cockpit", "btn_reformat_cockpit", "btn_run_cockpit_v2",
                     "btn_reformat_cockpit_v2", "btn_run_review", "btn_reformat_review"):
            setattr(gui, name, a1gui.ttk.Button(gui.root, text=name))
        gui._refresh_action_decision_view = lambda: None
        # 振り返りの月・対象者は固定値 (今日の日付に依存させない)
        gui._get_review_selected_months = lambda: [(2026, 9)]
        gui._get_review_all_months = lambda: [f"2026{m:02d}" for m in range(1, 10)]
        gui._get_review_selected_persons = lambda: ["Ochi"]
        return gui

    # ---- 入口の実行と待機 ---------------------------------------------
    def start_flow(self, start):
        """入口のメソッドを呼び、その呼び出しで起動したワーカースレッド(1つ)を返す。"""
        before = set(self.worker_threads())
        start()
        started = [t for t in self.worker_threads() if t not in before]
        self.assertEqual(len(started), 1,
                         f"入口がワーカースレッドをちょうど1つ起動していない: {started} (確認で中断した、実行中として拒否した等)")
        return started[0]

    def wait_for(self, worker):
        """ワーカーが終わるまで待つ (mainloop を回す。固定時間の sleep はしない)。"""
        finished = self.pump(lambda: not worker.is_alive(), timeout=FLOW_TIMEOUT)
        self.assertTrue(finished, f"入口の処理が {FLOW_TIMEOUT} 秒以内に終わらない")
        self.gui.root.update()                 # ワーカーが最後に予約した after(0) (ボタンを元に戻す等) を流す

    def cost_shown_by(self, worker):
        """そのワーカーが開いたレポート(ちょうど1つ)の末尾の費用表示を (円, 入力, 出力) で返す。"""
        errors = self.dialog_text({"showerror"})
        self.assertEqual(errors, "", f"入口がエラーで終わった: {errors}")
        paths = [path for thread, path in self.opened if thread is worker]
        self.assertEqual(len(paths), 1, f"レポートがちょうど1つ開かれていない: {paths}")
        with open(paths[0], encoding="utf-8") as f:
            found = COST_LINE.search(f.read())
        self.assertIsNotNone(found, f"レポートに費用表示が見つからない: {os.path.basename(paths[0])}")
        return float(found["yen"]), int(found["inp"]), int(found["out"])

    def run_flow(self, start):
        """入口を1回実行し、終わるまで待って、レポートの費用表示 (円, 入力, 出力) を返す。"""
        worker = self.start_flow(start)
        self.wait_for(worker)
        return self.cost_shown_by(worker)


# ============================================================
# 2. 5つの入口: 毎回「1回分」
# ============================================================
class TestEntrypointCost(EntrypointCase):
    def check_every_run_shows_one_run(self, gui, start, calls):
        """開始前に「前回までの累計」を入れてから、同じ入口を RUNS 回続けて実行し、毎回の表示が calls 回分であることを確認する。"""
        gui.summarizer.total_input_tokens = PREVIOUS_IN
        gui.summarizer.total_output_tokens = PREVIOUS_OUT
        shown = [self.run_flow(start) for _ in range(RUNS)]
        expected = one_run_cost(calls)
        self.assertEqual(
            shown, [expected] * RUNS,
            "費用表示 (円, 入力, 出力) が「今回の1回分」になっていない。1回目に前回までの累計が混ざる、"
            "または2回目以降が前回の累計を引きずって増えていく (B1)")

    def test_refresh_cockpit(self):
        """_refresh_cockpit (統括コックピットの更新): 開始前に累計が残っていても、続けて実行しても、毎回の費用表示は1回分。"""
        gui = self.build()
        self.check_every_run_shows_one_run(gui, gui._refresh_cockpit, N_CALLS)

    def test_sync_and_refresh_cockpit(self):
        """_sync_and_refresh_cockpit (全自動同期): 前回までの累計が残らず、PJ分析を含む全体で1回分を表示する。

        プロジェクト分析 (1PJあたり PJ_CALLS 回) → コックピット統合 (N_CALLS 回) の全部が、同じ1回分の費用に入る。
        (リセットの位置が遅いと、先に行ったプロジェクト分析の費用が表示から抜ける)
        """
        gui = self.build()
        gui.outlook.get_project_mails = lambda proj, days, include_sent=False: [{"entry_id": "x"}]   # PJ分析を実行させる
        n_projects = len(oto().load_project_knowledge().get("projects", {}))    # 入口は既定の知識ファイルを読み直す
        self.check_every_run_shows_one_run(gui, gui._sync_and_refresh_cockpit, N_CALLS + n_projects * PJ_CALLS)

    def test_run_cockpit_v2(self):
        """_run_cockpit_v2 (統括コックピットv2): 開始前に累計が残っていても、続けて実行しても、毎回の費用表示は1回分。"""
        gui = self.build()
        self.check_every_run_shows_one_run(gui, gui._run_cockpit_v2, N_CALLS)

    def test_run_action_dashboard(self):
        """_run_action_dashboard (アクション一覧): 開始前に累計が残っていても、続けて実行しても、毎回の費用表示は1回分。"""
        gui = self.build()
        self.check_every_run_shows_one_run(gui, gui._run_action_dashboard, N_CALLS)

    def test_run_review(self):
        """_run_review (振り返り): 開始前に累計が残っていても、続けて実行しても、毎回の費用表示は1回分。"""
        gui = self.build()
        self.check_every_run_shows_one_run(gui, gui._run_review, N_CALLS)


# ============================================================
# 3. 2つの流れ: 続けて実行 (対照) / 重ねて実行 (既知の制限)
# ============================================================
class TwoFlowsCase(EntrypointCase):
    """アクション生成 (N_CALLS 回のAI呼び出し) とコックピットv2 (N_CALLS 回) を実行し、各レポートの費用表示を
    self.action_cost / self.v2_cost に入れる。OVERLAP は、サブクラスで指定する。
        False: アクション生成が終わってから v2 を始める (続けて実行)
        True : アクション生成が途中 (N_CALLS の半分) まで進んで止まっている間に v2 を始め、v2 が終わってから
               アクション生成を再開する (重ねて実行)

    実行は setUp で行う。シナリオ自体が崩れた場合 (終わらない・エラー・費用表示が無い) は、expectedFailure でも
    隠れずにエラーになる。判定 (各画面が自分の分だけを表示するか) だけがテスト本体にある。"""

    OVERLAP = None

    def setUp(self):
        super().setUp()
        self.action_cost, self.v2_cost = self.run_two_flows(self.OVERLAP)

    def run_two_flows(self, overlap):
        """アクション生成 → コックピットv2 を実行し、各レポートの費用表示 (アクション, v2) を返す。"""
        gui = self.build()
        reached, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)           # 失敗しても、止めてあるワーカーを必ず解放する (後始末で待ち続けない)
        pause_at = N_CALLS // 2

        def action_analysis(*args, **kwargs):
            self.burn(pause_at)
            reached.set()
            release.wait(FLOW_TIMEOUT)         # 重ねる場合、ここで v2 の実行が終わるのを待つ
            self.burn(N_CALLS - pause_at)
            return {"action_cards": [], "threads": []}

        gui.summarizer.summarize_action_dashboard = action_analysis
        if not overlap:
            release.set()
        action = self.start_flow(gui._run_action_dashboard)
        if overlap:
            self.pump(lambda: reached.is_set() or not action.is_alive(), timeout=FLOW_TIMEOUT)
            self.assertTrue(reached.is_set(), "アクション生成が、途中のAI呼び出しまで進まなかった")
            v2 = self.start_flow(gui._run_cockpit_v2)          # アクション生成の途中で、別の流れを始める
            self.wait_for(v2)
            release.set()
            self.wait_for(action)
        else:
            self.wait_for(action)
            v2 = self.start_flow(gui._run_cockpit_v2)
            self.wait_for(v2)
        return self.cost_shown_by(action), self.cost_shown_by(v2)

    def check_each_shows_only_its_own(self):
        expected = one_run_cost(N_CALLS)
        self.assertEqual(
            {"アクション": self.action_cost, "コックピットv2": self.v2_cost},
            {"アクション": expected, "コックピットv2": expected},
            f"費用表示 (円, 入力, 出力) が、各画面の自分の分 (どちらもAI呼び出し{N_CALLS}回分) になっていない")


class TestSequentialFlows(TwoFlowsCase):
    OVERLAP = False

    def test_each_screen_shows_only_its_own_cost(self):
        """対照: アクション生成のあとにコックピットv2を続けて実行すると、各画面の費用表示は自分の1回分だけ。

        同じ summarizer のトークン合計を2つの入口が共有していても、開始時のリセットで、v2 にアクション生成の分は混ざらない。
        下の TestOverlappingFlows と同じ手順・同じ判定で、違いは「重ねるかどうか」だけ。
        """
        self.check_each_shows_only_its_own()


class TestOverlappingFlows(TwoFlowsCase):
    OVERLAP = True

    @unittest.expectedFailure
    def test_known_limit_each_screen_shows_only_its_own_cost(self):
        """既知の制限(同時実行): アクション生成の途中でコックピットv2を始めると、アクション側の費用表示がずれる。

        トークン合計 (summarizer.total_input_tokens / total_output_tokens) は1つの共有カウンタで、入口の開始時に0へ
        戻す方式のため、2つの流れを重ねると、先に始めた流れ (アクション生成) は、途中までの自分の分がv2の開始時に消え、
        v2の分が加わった値を表示する (この手順では、自分の分の1.5倍を表示する。v2側は自分の分だけで正しい)。
        理想は、同時に実行しても、各画面が自分の分だけを表示すること。修正は越智さん承認後。
        「各画面が自分の分だけを表示すること」をassertする。現状は共有カウンタのためずれるので expectedFailure。
        直ったら「想定外の成功」になるので、デコレータを外す。
        """
        self.check_each_shows_only_its_own()


if __name__ == "__main__":
    unittest.main(verbosity=2)
