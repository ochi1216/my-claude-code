# -*- coding: utf-8 -*-
"""A7c テスト: 統括コックピットの「全自動同期」と「v2」の AI費用の事前見積り・100円以上は確認・実績ログ・失敗/中止の表示。

根拠は仕様書 A7C_SPEC.md (前提: A7B_SPEC.md / A11_SPEC.md) だけ。期待値は _08 の新規・変更部分の実装を読まずに決めた
(変異テストを作るときに、変える箇所だけを参照した)。

構成
  1. 純関数: estimate_cockpit_v2_cost / estimate_cockpit_sync_cost / 定数。
  2. 見積り＝実際: 本物の generate_cockpit_v2_data / summarize_project_threads / summarize_staff_threads /
     generate_cockpit_summary を、AI呼び出し (_run_genai_call_with_schema) だけ偽物にして動かし、見積りと比べる。
  3. GUI の流れ: 偽Outlook・偽AI (A2 と同じく、トークン計測の経路は本物)・ダイアログのスタブで、本物の
     _sync_and_refresh_cockpit / _run_cockpit_v2 を動かす。
  4. 範囲ガード (AST): _07 → _08。
  (fix1: A7C_SPEC_DELTA_fix1.md) 同期の実績ログは段ごと (project / staff / cockpit_summary)、決勝戦の見積りは実績
  "cockpit_summary" で校正、集計の0リセットは確認の後 (同期・v2・アクション解析・振り返り)、決勝戦の回数 (0回/出力0で失敗)、
  v2 の成否未確認、同期の HTML 失敗。
  (A7e: A7E_SPEC.md で更新) 同期はプロジェクト・スタッフの Stage1 だけを行う (summarize_* に stage1_only=True)。見積りは
  include_stage2=False、完了表示の件数は Stage1 + 決勝戦、実績ログの feature は "project_s1" / "staff_s1" / "cockpit_summary"。

方針: 一時cwd の中だけで動かす (json/ analysis_cache/ を SB に作らない)。固定時間の sleep は使わない (mainloop で待つ)。
日付は「今からの相対時刻」だけを使い、特定の日付に依存しない。ネットワーク・実Outlook・実ブラウザには触れない。
"""
import ast
import copy
import gc
import hashlib
import json
import os
import re
import threading
import unittest
from datetime import datetime, timedelta
from unittest import mock

import _loader
import test_a1_gui_smoke as a1gui                  # GuiCase (一時cwd・messagebox の記録・待機・後始末)
import test_a2_entrypoints as a2e                  # 本物の MailSummarizer + 偽の AI 応答 (トークン計測は本物の経路)
import test_a7a_review_cost as a7a                 # AST の索引ヘルパ
from _loader import tempdir_cwd, write_json

tkmessagebox = a1gui.tkmessagebox


def oto():
    return _loader.load()


OLD_REV = "outlook_total_organizer_20261004_07.py"
NEW_REV = "outlook_total_organizer_20261004_08.py"

SYNC_START_TEXT = ("全プロジェクトおよび全スタッフの過去1週間分のメールを再取得・分析します。\n"
                   "時間とAI費用がかかります（取得の後に費用の見込みを計算し、100円以上なら、もう一度確認します）。\n"
                   "実行しますか？")
CANCEL_TEXT = "⏹ 費用の確認で中止しました（AI分析は行っていません）"
SYNC_BUSY_TEXT = "全データの最新化と分析を行っています"
SYNC_BTN_TEXT = "🔄 最新状況に更新 (全自動同期 / 時間・コスト大)"
V2_BTN_TEXT = "🎯 統括コックピット v2（新コンセプト・試験運用）を生成"
FLOW_TIMEOUT = 30
MODEL = "gemini-2.5-flash"


# ============================================================
# 合成データ
# ============================================================
def make_mail(cid, i, body_len=100, sender="A", email="other@example.com", hours_ago=1.0):
    now = datetime.now()
    return {"cid": cid, "entry_id": f"{cid}-E{i}", "subject": f"件名 {cid}", "body": "本" * body_len,
            "sender_name": sender, "sender_email": email, "received": now - timedelta(hours=hours_ago + i)}


def make_thread(cid, n_mails, body_len=100):
    mails = [make_mail(cid, i, body_len) for i in range(n_mails)]
    return {"mails": mails, "topic": f"件名 {cid}", "latest_entry_id": mails[-1]["entry_id"] if mails else "",
            "latest_date": max(m["received"] for m in mails) if mails else None,
            "all_categories": set(), "has_unread": False, "is_flagged": False}


def threads_of(spec, body_len=100):
    """{cid: メール件数} -> group_by_thread 形式の threads。"""
    return {cid: make_thread(cid, n, body_len) for cid, n in spec.items()}


def action_chars(thread):
    """A1.1 の規則: 1スレッドの入力字数 = min(Σ(min(len(body),800)+40), 30000) + 1800。"""
    body = sum(min(len(str(m.get("body") or "")), 800) + 40 for m in thread.get("mails") or [] if isinstance(m, dict))
    return min(body, 30000) + 1800


# ============================================================
# 1. 純関数
# ============================================================
class InTempCwd(unittest.TestCase):
    def setUp(self):
        cm = tempdir_cwd()
        cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)


class TestConstants(unittest.TestCase):
    def test_constants(self):
        """定数: 決勝戦の回数4・1回あたり入力30000字・1回あたり出力4000トークン。"""
        m = oto()
        self.assertEqual(m.COCKPIT_SUMMARY_ESTIMATE_CALLS, 4)
        self.assertEqual(m.COCKPIT_SUMMARY_ESTIMATE_INPUT_CHARS, 30000)
        self.assertEqual(m.COCKPIT_SUMMARY_ESTIMATE_OUTPUT_TOKENS, 4000)


class TestEstimateCockpitV2Cost(InTempCwd):
    KEYS = {"input_tokens", "output_tokens", "yen", "needs_confirm", "price_known", "n_calls", "input_chars",
            "output_tokens_per_call", "calibrated"}

    def est(self, project_threads, cache=None, model=MODEL):
        return oto().estimate_cockpit_v2_cost(project_threads, cache, model)

    def expected(self, chars_list, model=MODEL, per_call=2500):
        e = oto().estimate_ai_cost_yen(sum(chars_list), len(chars_list), per_call, model)
        return e

    def test_same_thread_same_count_in_two_projects_is_counted_once(self):
        """同じ cid・同じ件数のスレッドが2つのPJに出ても、解析は1回 (v2 は PJごとにキャッシュを保存するため)。"""
        t = threads_of({"c1": 2})
        est = self.est({"P1": t, "P2": copy.deepcopy(t)})
        self.assertEqual(est["n_calls"], 1)
        self.assertEqual(est["input_chars"], action_chars(t["c1"]))

    def test_same_thread_different_count_is_counted_twice(self):
        """同じ cid でも件数が違えば、後のPJでもう一度解析される (2回)。"""
        p1, p2 = threads_of({"c1": 2}), threads_of({"c1": 3})
        est = self.est({"P1": p1, "P2": p2})
        self.assertEqual(est["n_calls"], 2)
        self.assertEqual(est["input_chars"], action_chars(p1["c1"]) + action_chars(p2["c1"]))

    def test_projects_are_counted_in_dict_order(self):
        """PJ は辞書の順に数える: 件数 2→3→3 なら2回、3→2→3 なら3回 (直前のPJの件数で上書きされるため)。"""
        a, b, c = threads_of({"c1": 2}), threads_of({"c1": 3}), threads_of({"c1": 3})
        self.assertEqual(self.est({"A": a, "B": b, "C": c})["n_calls"], 2)
        self.assertEqual(self.est({"B": b, "A": a, "C": c})["n_calls"], 3)

    def test_existing_cache_skips_threads(self):
        """既存キャッシュ: 件数一致かつ成功は省略、件数違い・_error・data None は解析対象。"""
        t = threads_of({"ok": 2, "diff": 2, "err": 1, "none": 1, "new": 1})
        cache = {"threads": {
            "ok": {"mail_count": 2, "data": {"thread_id": "ok"}},
            "diff": {"mail_count": 1, "data": {"thread_id": "diff"}},
            "err": {"mail_count": 1, "data": {"thread_id": "err", "_error": True}},
            "none": {"mail_count": 1, "data": None},
        }}
        est = self.est({"P1": t}, cache)
        # data None は「解析済み・成功」と同じ扱い (A1.1: data が None でも落ちない。_error が無い)
        expected_cids = ["diff", "err", "new"]
        self.assertEqual(est["n_calls"], len(expected_cids))
        self.assertEqual(est["input_chars"], sum(action_chars(t[c]) for c in expected_cids))

    def test_cache_none_or_broken_means_all_threads(self):
        """cache_data が None / dict でない / threads が dict でない → 全スレッドが解析対象。"""
        t = threads_of({"c1": 1, "c2": 2})
        for cache in (None, "x", [], {"threads": None}, {"threads": []}, {}):
            with self.subTest(cache=cache):
                est = self.est({"P1": t}, cache)
                self.assertEqual(est["n_calls"], 2)
                self.assertEqual(est["input_chars"], action_chars(t["c1"]) + action_chars(t["c2"]))

    def test_skips_non_dict_or_empty_projects_and_never_raises(self):
        """threads が dict でない/空の PJ は飛ばす。おかしな入力でも例外を出さない (0件)。"""
        t = threads_of({"c1": 1})
        est = self.est({"空": {}, "None": None, "文字": "x", "リスト": [1], "P1": t})
        self.assertEqual(est["n_calls"], 1)
        for bad in (None, {}, "x", [], {"P": {"c": None}}, {"P": {"c": {"mails": None}}}):
            with self.subTest(bad=bad):
                est = self.est(bad)
                self.assertIsInstance(est, dict)
                self.assertTrue(self.KEYS <= set(est), set(est))

    def test_return_value_and_yen(self):
        """戻り値: estimate_ai_cost_yen(入力字数合計, 回数合計, 1回あたり出力, model) + n_calls / input_chars /
        output_tokens_per_call / calibrated (実績なし → 2500・False)。"""
        p1, p2 = threads_of({"c1": 2, "c2": 1}), threads_of({"c3": 4})
        est = self.est({"P1": p1, "P2": p2})
        chars = [action_chars(p1["c1"]), action_chars(p1["c2"]), action_chars(p2["c3"])]
        exp = self.expected(chars)
        self.assertTrue(self.KEYS <= set(est), f"キーが足りない: {self.KEYS - set(est)}")
        for k in ("input_tokens", "output_tokens", "yen", "needs_confirm", "price_known"):
            self.assertEqual(est[k], exp[k], k)
        self.assertEqual((est["n_calls"], est["input_chars"], est["output_tokens_per_call"], est["calibrated"]),
                         (3, sum(chars), 2500, False))

    def test_unknown_model_price_not_known(self):
        """単価表に無いモデル → price_known 偽 (estimate_ai_cost_yen と同じ)。"""
        est = self.est({"P1": threads_of({"c1": 1})}, None, "no-such-model-xyz")
        self.assertFalse(est["price_known"])

    def test_calibrated_from_action_log(self):
        """実績ログ feature="action" があれば校正 (estimate_action_analysis_cost と同じ: max(実績×1.5, 1250))。
        feature="cockpit_sync" の行は使わない。"""
        m = oto()
        m.record_ai_usage("cockpit_sync", 1, 1000, 99999)
        est0 = self.est({"P1": threads_of({"c1": 1})})
        self.assertEqual((est0["output_tokens_per_call"], est0["calibrated"]), (2500, False))
        m.record_ai_usage("action", 2, 6000, 4000)         # 1回あたり 2000 → 3000
        est = self.est({"P1": threads_of({"c1": 1})})
        self.assertEqual((est["output_tokens_per_call"], est["calibrated"]), (3000, True))
        self.assertEqual(est["output_tokens"], 3000)

    def test_does_not_modify_inputs(self):
        """入力 (project_threads・cache_data) を書き換えない。"""
        pt = {"P1": threads_of({"c1": 2, "c2": 1}), "P2": threads_of({"c1": 2, "c3": 1})}
        cache = {"threads": {"c2": {"mail_count": 1, "data": {"thread_id": "c2"}}}}
        pt0, cache0 = copy.deepcopy(pt), copy.deepcopy(cache)
        self.est(pt, cache)
        self.assertEqual(pt, pt0)
        self.assertEqual(cache, cache0)

    def test_needs_confirm_boundary(self):
        """needs_confirm は yen ≥ COST_CONFIRM_THRESHOLD_YEN (境界: ちょうど同じ値で真、0.01円上なら偽)。"""
        m = oto()
        pt = {"P1": threads_of({"c1": 3, "c2": 1})}
        yen = self.est(pt)["yen"]
        self.assertGreater(yen, 0)
        with mock.patch.object(m, "COST_CONFIRM_THRESHOLD_YEN", yen):
            self.assertTrue(self.est(pt)["needs_confirm"])
        with mock.patch.object(m, "COST_CONFIRM_THRESHOLD_YEN", round(yen + 0.01, 2)):
            self.assertFalse(self.est(pt)["needs_confirm"])

    def test_writes_no_files(self):
        """見積りはファイルを書かない。"""
        self.est({"P1": threads_of({"c1": 1})})
        self.assertEqual(_loader.snapshot_files("."), {})


class TestEstimateCockpitSyncCost(InTempCwd):
    def stages(self, pt, st, know, model=MODEL):
        m = oto()
        p = m.estimate_overview_cost("project", pt, know, model, include_stage2=False)      # (A7e) 同期は Stage1 だけ
        s = m.estimate_overview_cost("staff", st, know, model, include_stage2=False)
        sm = m.estimate_ai_cost_yen(30000 * 4, 4, 4000, model)
        return p, s, sm

    def data(self):
        know = {"projects": {"P1": {"master_history": "経緯" * 10, "ai_correction_rules": ["ルールA"]}, "P2": {}},
                "staffs": {"S1": {"role": "役割", "background": "背景"}}}
        pt = {"P1": threads_of({"a1": 2, "a2": 1}), "P2": threads_of({"b1": 3})}
        st = {"S1": threads_of({"s1": 1})}
        return pt, st, know

    def test_sum_of_three_stages(self):
        """3段 (project + staff + 決勝戦4回) の合計: yen は小数2桁に丸めた合計、n_calls は決勝戦の4を含む合計、トークンも合計。"""
        pt, st, know = self.data()
        est = oto().estimate_cockpit_sync_cost(pt, st, know, MODEL)
        p, s, sm = self.stages(pt, st, know)
        self.assertEqual(est["yen"], round(p["yen"] + s["yen"] + sm["yen"], 2))
        self.assertEqual(est["n_calls"], p["n_calls"] + s["n_calls"] + 4)
        self.assertEqual(est["input_tokens"], p["input_tokens"] + s["input_tokens"] + sm["input_tokens"])
        self.assertEqual(est["output_tokens"], p["output_tokens"] + s["output_tokens"] + sm["output_tokens"])
        self.assertEqual(est["needs_confirm"], est["yen"] >= 100)
        self.assertTrue(est["price_known"])
        self.assertFalse(est["calibrated"])

    def test_stage_dicts(self):
        """段ごとの dict: project / staff は estimate_overview_cost(..., include_stage2=False) の結果 (A7e)、summary は決勝戦の見込み (n_calls=4)。"""
        pt, st, know = self.data()
        est = oto().estimate_cockpit_sync_cost(pt, st, know, MODEL)
        p, s, sm = self.stages(pt, st, know)
        self.assertEqual(est["project"], p)
        self.assertEqual(est["staff"], s)
        self.assertIsInstance(est["summary"], dict)
        self.assertEqual(est["summary"]["n_calls"], 4)
        for k in ("yen", "input_tokens", "output_tokens"):
            self.assertEqual(est["summary"][k], sm[k], k)
        self.assertEqual((est["summary"]["output_tokens_per_call"], est["summary"]["calibrated"]), (4000, False))

    def test_empty_inputs_are_only_the_final_four_calls(self):
        """対象が無くても決勝戦の4回は数える (None / 空でも例外なし)。"""
        sm = oto().estimate_ai_cost_yen(120000, 4, 4000, MODEL)
        for pt, st, know in (({}, {}, {}), (None, None, None), ({"P": None}, {"S": {}}, {})):
            with self.subTest(pt=pt, st=st):
                est = oto().estimate_cockpit_sync_cost(pt, st, know, MODEL)
                self.assertEqual(est["n_calls"], 4)
                self.assertEqual(est["yen"], round(sm["yen"], 2))

    def test_calibrated_needs_every_stage_with_calls(self):
        """(fix1) calibrated は n_calls>0 の段 (決勝戦は常に4回) が全部実績を使ったときだけ真。"""
        m = oto()
        pt, st, know = self.data()
        m.record_ai_usage("project", 2, 1000, 3000)
        m.record_ai_usage("staff", 2, 1000, 3000)
        self.assertFalse(m.estimate_cockpit_sync_cost(pt, st, know, MODEL)["calibrated"], "決勝戦の実績が無い")
        m.record_ai_usage("cockpit_summary", 4, 1000, 8000)
        self.assertTrue(m.estimate_cockpit_sync_cost(pt, st, know, MODEL)["calibrated"])

    def test_calibrated_ignores_stages_without_calls(self):
        """(fix1) 呼び出しが0回の段 (対象なし) は calibrated の判定に入れない。"""
        m = oto()
        pt, st, know = self.data()
        m.record_ai_usage("cockpit_summary", 4, 1000, 8000)
        self.assertTrue(m.estimate_cockpit_sync_cost({}, {}, know, MODEL)["calibrated"], "決勝戦だけ (実績あり)")
        self.assertFalse(m.estimate_cockpit_sync_cost(pt, {}, know, MODEL)["calibrated"], "project の実績が無い")
        m.record_ai_usage("project", 2, 1000, 3000)
        self.assertTrue(m.estimate_cockpit_sync_cost(pt, {}, know, MODEL)["calibrated"], "staff は0回なので見ない")
        self.assertFalse(m.estimate_cockpit_sync_cost(pt, st, know, MODEL)["calibrated"], "staff の実績が無い")

    def test_summary_stage_is_calibrated_from_cockpit_summary_log(self):
        """(fix1) 決勝戦の1回あたりの出力: 実績 "cockpit_summary" があれば max(実績×1.5, 2000)、無ければ 4000。
        "cockpit_sync" などほかの feature の行は使わない。"""
        m = oto()
        m.record_ai_usage("cockpit_sync", 4, 1000, 400000)
        m.record_ai_usage("project", 4, 1000, 400000)
        est = m.estimate_cockpit_sync_cost({}, {}, {}, MODEL)
        self.assertEqual((est["summary"]["output_tokens_per_call"], est["summary"]["calibrated"]), (4000, False))
        m.record_ai_usage("cockpit_summary", 4, 1000, 8000)          # 1回あたり 2000 → ×1.5 = 3000
        est = m.estimate_cockpit_sync_cost({}, {}, {}, MODEL)
        self.assertEqual((est["summary"]["output_tokens_per_call"], est["summary"]["calibrated"]), (3000, True))
        exp = m.estimate_ai_cost_yen(120000, 4, 3000, MODEL)
        self.assertEqual((est["summary"]["output_tokens"], est["yen"]), (12000, round(exp["yen"], 2)))

    def test_summary_stage_floor_is_2000(self):
        """(fix1) 実績が小さくても、決勝戦の1回あたりの出力は 2000 (4000×0.5) を下回らない。"""
        m = oto()
        m.record_ai_usage("cockpit_summary", 4, 1000, 400)            # 1回あたり 100 → ×1.5 = 150 → 下限 2000
        est = m.estimate_cockpit_sync_cost({}, {}, {}, MODEL)
        self.assertEqual((est["summary"]["output_tokens_per_call"], est["summary"]["output_tokens"]), (2000, 8000))

    def test_price_known_false_for_unknown_model(self):
        """単価表に無いモデル → price_known 偽。"""
        pt, st, know = self.data()
        self.assertFalse(oto().estimate_cockpit_sync_cost(pt, st, know, "no-such-model-xyz")["price_known"])

    def test_needs_confirm_boundary(self):
        """needs_confirm は合計 yen ≥ 100 (境界: しきい値を合計ちょうどにすると真、0.01円上で偽)。"""
        m = oto()
        pt, st, know = self.data()
        yen = m.estimate_cockpit_sync_cost(pt, st, know, MODEL)["yen"]
        with mock.patch.object(m, "COST_CONFIRM_THRESHOLD_YEN", yen):
            self.assertTrue(m.estimate_cockpit_sync_cost(pt, st, know, MODEL)["needs_confirm"])
        with mock.patch.object(m, "COST_CONFIRM_THRESHOLD_YEN", round(yen + 0.01, 2)):
            self.assertFalse(m.estimate_cockpit_sync_cost(pt, st, know, MODEL)["needs_confirm"])

    def test_does_not_modify_inputs_or_write_files(self):
        """入力を書き換えない・ファイルを書かない。"""
        pt, st, know = self.data()
        snap = copy.deepcopy((pt, st, know))
        oto().estimate_cockpit_sync_cost(pt, st, know, MODEL)
        self.assertEqual((pt, st, know), snap)
        self.assertEqual(_loader.snapshot_files("."), {})


# ============================================================
# 2. 見積り＝実際
# ============================================================
def fill_schema(schema):
    t = (schema or {}).get("type")
    if t == "OBJECT":
        return {k: fill_schema(v) for k, v in (schema.get("properties") or {}).items()}
    if t == "ARRAY":
        return [fill_schema(schema.get("items") or {})] if schema.get("minItems") else []
    if t == "BOOLEAN":
        return True
    if t in ("INTEGER", "NUMBER"):
        return 0
    return "テスト"


class RealAiCase(InTempCwd):
    """本物の MailSummarizer で、AI呼び出し (_run_genai_call_with_schema) だけ偽物にする。呼び出しを記録する。"""

    def setUp(self):
        super().setUp()
        self.summarizer, _burn = a2e.make_summarizer()
        self.calls = []
        lock = threading.Lock()

        def fake(prompt, schema, override_model=None):
            with lock:
                self.calls.append((prompt, schema, override_model))
            return fill_schema(schema)
        self.summarizer._run_genai_call_with_schema = fake


class TestV2EstimateMatchesActual(RealAiCase):
    def test_call_count_and_prompt_chars(self):
        """本物の generate_cockpit_v2_data (複数PJ・重複スレッド・既存キャッシュあり) の実際のAI呼び出し回数は、
        見積りの n_calls と一致し、実際のプロンプトの字数合計は input_chars 以下。"""
        m = oto()
        write_json(os.path.join("analysis_cache", "action_dashboard.json"), {"threads": {
            "c2": {"mail_count": 1, "data": {"thread_id": "c2", "topic": "t", "actions": []}},
            "c4": {"mail_count": 1, "data": {"thread_id": "c4", "topic": "t", "actions": [], "_error": True}},
        }})
        pt = {
            "PA": threads_of({"c1": 2, "c2": 1, "c3": 3}, body_len=900),
            "PB": threads_of({"c1": 2, "c4": 1}, body_len=900),       # c1 は PA と同じ件数 → 1回だけ
            "PC": threads_of({"c3": 4}, body_len=900),                # c3 は件数違い → もう1回
            "PD": {},
        }
        est = m.estimate_cockpit_v2_cost(pt, m.load_action_dashboard_cache(), MODEL)
        self.assertEqual(est["n_calls"], 4, "前提: c1, c3, c4, c3(件数違い) の4回")
        self.summarizer.generate_cockpit_v2_data(copy.deepcopy(pt), {"projects": {}}, "me@example.com")
        self.assertEqual(len(self.calls), est["n_calls"], "実際のAI呼び出し回数が見積りと違う")
        actual_chars = sum(len(p) for p, _s, _m in self.calls)
        self.assertLessEqual(actual_chars, est["input_chars"], "実際のプロンプトの字数が見積りを超えた")


class TestSyncEstimateCoversActual(RealAiCase):
    def test_call_counts(self):
        """本物の summarize_project_threads / summarize_staff_threads / generate_cockpit_summary を偽AIで動かすと、
        Stage1 の実回数は見積りと一致し、全体の実回数は見積り (n_calls) 以下。
        (A7e) 同期と同じく summarize_* は stage1_only=True で動かす: Stage2 は0回で、全体の実回数は見積りと一致する。"""
        m = oto()
        rules = ["ルールA"]
        know = {"projects": {"P1": {"master_history": "経緯", "ai_correction_rules": rules}, "P2": {}},
                "staffs": {"S1": {"role": "役割", "background": "背景"}}}
        p1 = threads_of({"a1": 2, "a2": 1})
        # P1 の a2 は解析済み (件数一致・成功・rules_hash 一致) → Stage1 を省略
        rules_hash = hashlib.md5("\n".join(f"- {r}" for r in rules).encode("utf-8")).hexdigest()
        write_json(os.path.join("analysis_cache", "project_P1.json"), {"rules_hash": rules_hash, "threads": {
            "a2": {"mail_count": 1, "data": {"thread_id": "a2", "topic": "t", "is_target": True, "summary": "s"}}}})
        pt = {"P1": p1, "P2": threads_of({"b1": 1})}
        st = {"S1": threads_of({"s1": 2, "s2": 1})}
        est = m.estimate_cockpit_sync_cost(pt, st, know, MODEL)
        s = self.summarizer
        for name, threads in pt.items():
            s.summarize_project_threads(name, copy.deepcopy(threads), know, stage1_only=True)
        for name, threads in st.items():
            s.summarize_staff_threads(name, copy.deepcopy(threads), know, stage1_only=True)
        s.generate_cockpit_summary()
        stage1 = [c for c in self.calls if "thread_id" in ((c[1] or {}).get("properties") or {})]
        self.assertEqual(len(stage1), est["project"]["n_calls_s1"] + est["staff"]["n_calls_s1"])
        self.assertEqual(len(stage1), 4, "前提: a1, b1, s1, s2 の4回")
        self.assertLessEqual(len(self.calls), est["n_calls"])
        stage2 = [c for c in self.calls if "manager_actions" in ((c[1] or {}).get("properties") or {})]
        self.assertEqual(stage2, [], "(A7e) stage1_only=True なのに Stage2 が呼ばれた")
        self.assertEqual(len(self.calls), len(stage1) + 4, "前提: 決勝戦 (4回) も実際に呼ばれている")
        self.assertEqual(len(self.calls), est["n_calls"])


# ============================================================
# 3. GUI の流れ
# ============================================================
class FakeOutlook(a1gui.StubOutlook):
    def __init__(self, case, proj_mails=None, staff_mails=None):
        super().__init__()
        self.case = case
        self.proj_mails = proj_mails or {}
        self.staff_mails = staff_mails or {}

    def get_project_mails(self, proj, days, include_sent=False):
        self.case.events.append(f"fetch:{proj}")
        return copy.deepcopy(self.proj_mails.get(proj, []))

    def search_mails_fast(self, conditions, logic="AND", *args, **kwargs):
        who = conditions.get("sender") or conditions.get("body_keyword")
        self.case.events.append(f"search:{who}")
        if conditions.get("sender"):
            return copy.deepcopy(self.staff_mails.get(who, []))
        return []

    def group_by_thread(self, mails):
        out = {}
        for mm in mails:
            t = out.setdefault(mm["cid"], {"mails": [], "topic": mm["subject"], "latest_entry_id": "",
                                           "latest_date": mm["received"], "all_categories": set(),
                                           "has_unread": False, "is_flagged": False})
            t["mails"].append(mm)
            t["latest_entry_id"] = mm["entry_id"]
        return out


class FakeReporter:
    def __init__(self, case):
        self.case = case
        self.path = "report.html"

    def generate_cockpit_report(self, res, cache_dict, total_input, total_output, *a, **k):
        self.case.events.append("report")
        return self.path

    def generate_cockpit_v2_report(self, data, total_input, total_output, *a, **k):
        self.case.events.append("report")
        return self.path


def mails_for(spec, body_len=800):
    """{cid: 件数} -> メールのリスト (偽Outlook の取得結果)。"""
    out = []
    for cid, n in spec.items():
        out.extend(make_mail(cid, i, body_len) for i in range(n))
    return out


def big_spec(prefix, n):
    return {f"{prefix}{i:03d}": 1 for i in range(n)}


class CockpitCase(a1gui.GuiCase):
    """本物の _sync_and_refresh_cockpit / _run_cockpit_v2 を、偽Outlook・偽AI・ダイアログのスタブで動かす土台。
    GC は実行中止める (ワーカー上で Tk オブジェクトが解放されて落ちるのを避ける。A7a と同じ)。"""

    def setUp(self):
        gc.disable()
        self.addCleanup(gc.enable)
        self.addCleanup(gc.collect)
        self.events = []
        self.answers = {}
        self.dialog_main = []
        self.fail_cids = set()
        self.block_first_ai = False
        self.reached, self.release = threading.Event(), threading.Event()
        self.browser = []
        p = mock.patch("webbrowser.open", lambda url, *a, **k: (self.events.append("browser"),
                                                                self.browser.append(url), True)[2])
        p.start()
        self.addCleanup(p.stop)
        super().setUp()
        self.addCleanup(self.release.set)
        os.makedirs("json", exist_ok=True)
        self.spied = {}
        for name, tag in (("estimate_cockpit_sync_cost", "estimate"), ("estimate_cockpit_v2_cost", "estimate"),
                          ("save_project_knowledge", "save_knowledge"), ("record_ai_usage", "record")):
            self._spy(name, tag)

    def _spy(self, name, tag):
        real = getattr(oto(), name, None)
        self.spied[name] = []
        if real is None:                  # 未実装の版 (旧版) でも、他の確認ができるように読み込みでは落とさない
            return

        def wrapper(*args, **kwargs):
            self.events.append(tag)
            result = real(*args, **kwargs)
            self.spied[name].append((args, kwargs, result))
            return result
        p = mock.patch.object(oto(), name, wrapper)
        p.start()
        self.addCleanup(p.stop)

    def _patch_messagebox(self):
        super()._patch_messagebox()
        inner = tkmessagebox.askyesno

        def ask(*args, **kwargs):
            self.dialog_main.append(threading.current_thread() is threading.main_thread())
            inner(*args, **kwargs)
            title = args[0] if args else kwargs.get("title")
            self.events.append(f"ask:{title}")
            if title == COST_TITLE and getattr(self, "gui", None) is not None:
                self.totals_at_cost_ask.append(self.totals())
            return self.answers.get(title, True)
        self.totals_at_cost_ask = []
        p = mock.patch.object(tkmessagebox, "askyesno", ask)
        p.start()
        self.addCleanup(p.stop)

    def totals(self):
        s = self.gui.summarizer
        return (s.total_input_tokens, s.total_output_tokens)

    def preset_totals(self):
        """前回までの集計 (他の画面の実行中の分) を模した値を入れる。"""
        self.gui.summarizer.total_input_tokens, self.gui.summarizer.total_output_tokens = PREV_TOTALS

    def records(self):
        """実績ログを (feature, n_calls, 入力, 出力) で返し、yen が増分のトークンの費用であることも確かめる。"""
        out = []
        for r in self.usage_log():
            self.assertAlmostEqual(r["yen"], oto().calc_api_cost_yen(r["input_tokens"], r["output_tokens"], MODEL),
                                   places=2, msg=f"実績ログの yen が段の増分の費用でない: {r}")
            out.append((r["feature"], r["n_calls"], r["input_tokens"], r["output_tokens"]))
        return out

    # ---- 組み立て ----------------------------------------------------
    def build(self, projects, staffs=None, proj_mails=None, staff_mails=None):
        gui = self.make_gui(select_action=False, build_panel=False)
        gui.outlook = FakeOutlook(self, proj_mails, staff_mails)
        gui.summarizer, self.burn = a2e.make_summarizer()
        gui.reporter = self.reporter = FakeReporter(self)
        know = {"projects": {p: {} for p in projects}, "staffs": {s: {} for s in (staffs or [])}}
        write_json(oto().PROJECT_KNOWLEDGE_FILE, know)
        gui.project_knowledge = oto().load_project_knowledge()
        gui.config = dict(oto().DEFAULT_CONFIG)
        gui.config["gemini_model"] = MODEL
        gui.cockpit_widgets = {}
        for key in ("pm", "site"):
            frame = a1gui.ttk.Frame(gui.root)
            frame.pack()
            a1gui.ttk.Label(frame, text=f"前回の表示: {key}").pack()
            gui.cockpit_widgets[key] = frame
        for name, text in (("btn_sync_cockpit", SYNC_BTN_TEXT), ("btn_refresh_cockpit", "📊 既存状況をサマリ"),
                           ("btn_reformat_cockpit", "🎨"), ("btn_run_cockpit_v2", V2_BTN_TEXT),
                           ("btn_reformat_cockpit_v2", "🎨")):
            setattr(gui, name, a1gui.ttk.Button(gui.root, text=text))
        s = gui.summarizer
        s.summarize_project_threads = self._fake_overview("project")
        s.summarize_staff_threads = self._fake_overview("staff")
        s.generate_cockpit_summary = self._fake_summary
        s.generate_cockpit_v2_data = self._fake_v2
        gui.root.update()
        return gui

    def _first_ai(self):
        if self.block_first_ai and not self.reached.is_set():
            self.reached.set()
            self.release.wait(FLOW_TIMEOUT)

    def _fake_overview(self, kind):
        def run(name, threads, knowledge, retry_callback=None, progress_callback=None, stage1_only=False):
            self.events.append(f"ai:{kind}:{name}")
            self._first_ai()
            threads = threads or {}
            ok_any = any(cid not in self.fail_cids for cid in threads)
            # Stage1 はスレッドごと、Stage2 は成功した要約がある対象だけ。(A7e) stage1_only=True なら Stage2 は行わない
            self.burn(len(threads) + (1 if ok_any and not stage1_only else 0))
            safe = "".join(c for c in name if c.isalnum() or c in " ._-")
            cache = {"rules_hash": "", "threads": {
                cid: {"mail_count": len(t["mails"]),
                      "data": dict({"thread_id": cid, "topic": "t", "is_target": True, "summary": "s"},
                                   **({"_error": True} if cid in self.fail_cids else {}))}
                for cid, t in threads.items()}}
            write_json(os.path.join("analysis_cache", f"{kind}_{safe}.json"), cache)
            return {"threads": []}
        return run

    def _fake_summary(self, progress_callback=None):
        self.events.append("ai:summary")
        self._first_ai()
        if getattr(self, "summary_error", None):
            raise self.summary_error
        self.burn(getattr(self, "summary_burn", 4))
        return copy.deepcopy(getattr(self, "summary_result", {}))

    def _fake_v2(self, project_threads, project_knowledge, user_smtp_address, progress_callback=None):
        self.events.append("ai:v2")
        if getattr(self, "v2_error", None):
            raise self.v2_error
        cache = oto().load_action_dashboard_cache() or {"threads": {}}
        cache.setdefault("threads", {})
        n = 0
        for threads in project_threads.values():
            for cid, t in (threads or {}).items():
                if cid in cache["threads"]:
                    continue
                n += 1
                data = {"thread_id": cid, "topic": "t", "actions": []}
                if cid in self.fail_cids:
                    data["_error"] = True
                cache["threads"][cid] = {"mail_count": len(t["mails"]), "data": data}
        self.burn(n)
        write_json(os.path.join("analysis_cache", "action_dashboard.json"), cache)
        if getattr(self, "v2_corrupt_cache", False):           # 解析後のキャッシュが読めない
            with open(os.path.join("analysis_cache", "action_dashboard.json"), "w", encoding="utf-8") as f:
                f.write("{壊れたJSON")
        return {"generated_at": "x", "projects": {}, "queue": []}

    # ---- 実行と待機 --------------------------------------------------
    def start(self, method):
        before = set(self.worker_threads())
        method()
        started = [t for t in self.worker_threads() if t not in before]
        return started[0] if started else None

    def wait(self, worker):
        self.assertIsNotNone(worker, "ワーカースレッドが起動していない")
        self.assertTrue(self.pump(lambda: not worker.is_alive(), timeout=FLOW_TIMEOUT), "終わらない")
        self.settle(0.05)

    def run_flow(self, method):
        self.wait(self.start(method))

    # ---- 観察 --------------------------------------------------------
    def status(self):
        return str(self.gui.lbl_stat.cget("text"))

    def widget_texts(self):
        return {k: [str(c.cget("text")) for c in f.winfo_children()] for k, f in self.gui.cockpit_widgets.items()}

    def ask_messages(self, title):
        return [(a[1] if len(a) > 1 else k.get("message")) for n, a, k in self.dialogs
                if n == "askyesno" and (a[0] if a else k.get("title")) == title]

    def errors(self):
        return [" ".join(str(x) for x in list(a) + list(k.values())) for n, a, k in self.dialogs if n == "showerror"]

    def usage_log(self):
        path = os.path.join("json", "ai_usage_log.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def estimate(self):
        recs = self.spied["estimate_cockpit_sync_cost"] + self.spied["estimate_cockpit_v2_cost"]
        self.assertEqual(len(recs), 1, "見積りがちょうど1回呼ばれていない")
        return recs[0][2]

    def spent(self):
        s = self.gui.summarizer
        return oto().calc_api_cost_yen(s.total_input_tokens, s.total_output_tokens, MODEL)

    def assert_cost_in_status(self, prefix, tail_fmt):
        """ステータス = prefix + （今回のAI費用 約X円・{tail}）。X は今回の費用 (丸めは小数0〜2桁を許す)。"""
        text = self.status()
        self.assertTrue(text.startswith(prefix), f"ステータスの先頭が違う: {text!r}")
        m = re.fullmatch(re.escape(prefix) + r"（今回のAI費用 約([0-9.]+)円・" + re.escape(tail_fmt) + r"）", text)
        self.assertIsNotNone(m, f"ステータスの形が違う: {text!r}")
        shown, spent = float(m.group(1)), self.spent()
        self.assertGreater(spent, 0)
        self.assertIn(shown, {round(spent), round(spent, 1), round(spent, 2)}, f"費用 {shown} が今回の費用 {spent} と違う")


SYNC_TITLE = "⚠️ 確認"
COST_TITLE = "AI費用の確認"
PREV_TOTALS = (111, 222)          # 前回までの集計 (他の画面の分) を模した値
CALL_IN, CALL_OUT = a2e.CALL_IN, a2e.CALL_OUT      # 偽AI 1回あたりの (入力, 出力) = (6000, 3300)


def tok(calls):
    return (calls * CALL_IN, calls * CALL_OUT)


def rec(feature, ok_calls, burned_calls):
    """段ごとの実績ログの期待値 (feature, 成功回数, 段の入力の増分, 段の出力の増分)。"""
    return (feature, ok_calls) + tok(burned_calls)


class TestSyncStartDialog(CockpitCase):
    def test_new_start_text_and_no_does_nothing(self):
        """開始時の askyesno は新しい文言。いいえなら何もしない (ワーカーなし・取得なし・欄もボタンもそのまま)。"""
        gui = self.build(["P1"], [], {"P1": mails_for({"a": 1})})
        self.answers[SYNC_TITLE] = False
        before = self.widget_texts()
        worker = self.start(gui._sync_and_refresh_cockpit)
        self.settle(0.05)
        self.assertIsNone(worker)
        msgs = [a[1] if len(a) > 1 else k.get("message") for n, a, k in self.dialogs if n == "askyesno"]
        self.assertEqual(msgs, [SYNC_START_TEXT])
        self.assertEqual([e for e in self.events if not e.startswith("ask:")], [])
        self.assertEqual(self.widget_texts(), before)
        self.assertEqual(str(gui.btn_sync_cockpit.cget("state")), "normal")


class TestSyncSmallCost(CockpitCase):
    def test_fetch_all_before_ai_no_second_confirm_and_success(self):
        """100円未満: 取得 (PJ→スタッフ) が全部終わってから見積り→最初のAI。2回目の確認なし。成功の表示と実績ログ。"""
        gui = self.build(["P1", "P2"], ["S1"], {"P1": mails_for({"a1": 2, "a2": 1}), "P2": mails_for({"b1": 1})},
                         {"S1": mails_for({"s1": 1})})
        self.preset_totals()
        self.run_flow(gui._sync_and_refresh_cockpit)
        self.assertEqual(self.errors(), [])
        est = self.estimate()
        self.assertFalse(est["needs_confirm"], "前提: 100円未満")
        self.assertEqual(self.ask_messages(COST_TITLE), [])
        ev = self.events
        first_ai = min(i for i, e in enumerate(ev) if e.startswith("ai:"))
        last_fetch = max(i for i, e in enumerate(ev) if e.startswith(("fetch:", "search:")))
        self.assertLess(last_fetch, ev.index("estimate"))
        self.assertLess(ev.index("estimate"), first_ai)
        self.assertIn("search:S1", ev[:first_ai])
        self.assertLess(max(i for i, e in enumerate(ev) if e.startswith("fetch:")), ev.index("search:S1"))
        self.assertIn("save_knowledge", ev)
        self.assertIn("report", ev)
        self.assertEqual(self.browser, ["report.html"])
        self.assertTrue(os.path.exists(oto().COCKPIT_LAST_RESULT_FILE))
        # (fix1) 実績ログは段ごと (増分のトークン・成功回数)。"cockpit_sync" は記録しない
        # (A7e) 同期は Stage1 だけ: project_s1 3 (a1,a2,b1) / staff_s1 1 / 決勝戦 4
        self.assertEqual(self.records(), [rec("project_s1", 3, 3), rec("staff_s1", 1, 1), rec("cockpit_summary", 4, 4)])
        # 集計は確認の後 (AIの直前) に0へ戻すので、前回までの分 (111/222) は混ざらない
        self.assertEqual(self.totals(), tok(8))
        self.assert_cost_in_status("✅ 全解析同期完了", "8件")
        self.assertEqual(str(gui.btn_sync_cockpit.cget("state")), "normal")
        self.assertEqual(str(gui.btn_sync_cockpit.cget("text")), SYNC_BTN_TEXT)
        self.assertEqual(str(gui.btn_refresh_cockpit.cget("state")), "normal")

    def test_ai_failures_are_shown_and_not_logged(self):
        """AI失敗あり: 「⚠ 完了（AI失敗N件。…）（今回のAI費用 約X円・成功M/N件）」、実績ログは成功件数。"""
        gui = self.build(["P1"], ["S1"], {"P1": mails_for({"a1": 1, "a2": 1, "a3": 1})}, {"S1": mails_for({"s1": 1})})
        self.fail_cids = {"a1", "s1"}
        self.run_flow(gui._sync_and_refresh_cockpit)
        est = self.estimate()
        self.assertEqual(est["n_calls"], 8, "前提: 見積り = Stage1 4 + 決勝戦4 (A7e: 同期は Stage2 を省く)")
        # 実際: Stage1 4 (a1,a2,a3,s1) + 決勝戦4 = 8
        self.assert_cost_in_status("⚠ 完了（AI失敗2件。もう一度実行すると再試行）", "成功6/8件")
        # project_s1: 3回 (a1 失敗) → 成功2 / staff_s1: 1回 (s1 失敗) → 成功0 なので記録しない / 決勝戦 4
        self.assertEqual(self.records(), [rec("project_s1", 2, 3), rec("cockpit_summary", 4, 4)])

    def test_count_is_actual_calls_when_stage2_is_skipped(self):
        """(fix1) 完了表示・実績ログの件数は見積り(上限)ではなく実際の回数: Stage1 が全部失敗した対象は Stage2 を数えない。
        (A7e) 同期は Stage2 を行わないので、件数は Stage1 + 決勝戦。"""
        gui = self.build(["P1", "P2"], [], {"P1": mails_for({"a1": 1, "a2": 1}), "P2": mails_for({"b1": 1})})
        self.fail_cids = {"a1", "a2"}
        self.run_flow(gui._sync_and_refresh_cockpit)
        self.assertEqual(self.estimate()["n_calls"], 7, "前提: 見積り = Stage1 3 + 決勝戦4 (A7e: 同期は Stage2 を省く)")
        # 実際: Stage1 3 + 決勝戦4 = 7、成功 = 7 − 2 = 5
        self.assert_cost_in_status("⚠ 完了（AI失敗2件。もう一度実行すると再試行）", "成功5/7件")
        # project_s1: 3回 (a1,a2 失敗) → 成功1 / staff: 対象なし (記録なし) / 決勝戦 4
        self.assertEqual(self.records(), [rec("project_s1", 1, 3), rec("cockpit_summary", 4, 4)])

    def test_html_write_failure_shows_report_failed(self):
        """(fix1 Minor4) HTML の書き出し失敗 (path が空): ブラウザは開かず、ダイアログは出さず、保存結果は保存する。
        表示は「❌ 生成失敗（今回のAI費用 約X円）」。実績ログは決勝戦の後なので記録する。"""
        gui = self.build(["P1"], [], {"P1": mails_for({"a1": 1})})
        self.reporter.path = ""
        self.run_flow(gui._sync_and_refresh_cockpit)
        self.assertIn("report", self.events)
        self.assertEqual(self.browser, [])
        self.assertEqual(self.errors(), [])
        self.assertTrue(os.path.exists(oto().COCKPIT_LAST_RESULT_FILE))
        m = re.fullmatch(r"❌ 生成失敗（今回のAI費用 約([0-9.]+)円）", self.status())
        self.assertIsNotNone(m, self.status())
        spent = self.spent()
        self.assertIn(float(m.group(1)), {round(spent), round(spent, 1), round(spent, 2)})
        self.assertEqual(self.records(), [rec("project_s1", 1, 1), rec("cockpit_summary", 4, 4)])      # (A7e) Stage1 だけ

    def test_summary_without_analyzed_data_counts_zero_calls(self):
        """(fix1 Minor1) 決勝戦が _error (解析済みのデータが無くAIを呼ばなかった) なら、決勝戦は0回 (記録もしない)。"""
        gui = self.build(["P1"], [], {"P1": mails_for({"a1": 1})})
        self.summary_burn = 0
        self.summary_result = {"_error": True, "summary": "解析済みデータがありません。"}
        self.run_flow(gui._sync_and_refresh_cockpit)
        self.assert_cost_in_status("✅ 全解析同期完了", "1件")             # Stage1 1 (決勝戦0。A7e: Stage2 なし)
        self.assertEqual(self.records(), [rec("project_s1", 1, 1)])

    def test_summary_with_zero_output_counts_four_failures(self):
        """(fix1 Minor1) 決勝戦の段の出力の増分が0なら、決勝戦の4回とも失敗として数える (記録もしない)。"""
        gui = self.build(["P1"], [], {"P1": mails_for({"a1": 1})})
        self.summary_burn = 0
        self.summary_result = {}
        self.run_flow(gui._sync_and_refresh_cockpit)
        self.assert_cost_in_status("⚠ 完了（AI失敗4件。もう一度実行すると再試行）", "成功1/5件")     # (A7e) Stage1 1 + 決勝戦4
        self.assertEqual(self.records(), [rec("project_s1", 1, 1)])


class TestSyncBigCost(CockpitCase):
    def build_big(self):
        return self.build(["P1"], ["S1"], {"P1": mails_for(big_spec("a", 150))}, {"S1": mails_for({"s1": 1})})

    def test_confirm_no_cancels_without_touching_anything(self):
        """100円以上で「いいえ」: AIなし・ナレッジ保存なし・HTMLなし・保存結果なし・実績ログなし・欄はそのまま・ボタン復帰・中止の表示。"""
        gui = self.build_big()
        self.answers[COST_TITLE] = False
        before = self.widget_texts()
        self.preset_totals()
        self.run_flow(gui._sync_and_refresh_cockpit)
        self.assertEqual(self.totals(), PREV_TOTALS, "(fix1 M2) 確認で中止しただけで、集計 (他の画面の分) を0にした")
        est = self.estimate()
        self.assertTrue(est["needs_confirm"], f"前提: 100円以上 ({est['yen']})")
        msgs = self.ask_messages(COST_TITLE)
        self.assertEqual(len(msgs), 1)
        self.assertIn(f"統括コックピットの全自動同期のAI費用の見込み: 約{est['yen']:.0f}円", msgs[0])
        self.assertEqual([e for e in self.events if e.startswith("ai:")], [])
        for tag in ("save_knowledge", "report", "browser", "record"):
            self.assertNotIn(tag, self.events)
        self.assertFalse(os.path.exists(oto().COCKPIT_LAST_RESULT_FILE))
        self.assertEqual(self.usage_log(), [])
        self.assertEqual(self.widget_texts(), before, "中止したのにコックピットの欄が消された")
        self.assertEqual(str(gui.btn_sync_cockpit.cget("state")), "normal")
        self.assertEqual(str(gui.btn_sync_cockpit.cget("text")), SYNC_BTN_TEXT)
        self.assertEqual(str(gui.btn_refresh_cockpit.cget("state")), "normal")
        self.assertEqual(self.status(), CANCEL_TEXT)
        self.assertEqual(self.errors(), [])

    def test_confirm_yes_replaces_the_panels_before_ai(self):
        """100円以上で「はい」: 欄が「全データの最新化と分析を行っています…」に置き換わってから解析し、従来どおり生成する。"""
        gui = self.build_big()
        before = self.widget_texts()
        self.block_first_ai = True
        self.preset_totals()
        worker = self.start(gui._sync_and_refresh_cockpit)
        self.assertTrue(self.pump(self.reached.is_set, timeout=FLOW_TIMEOUT), "AI まで進まない")
        self.settle(0.1)
        during = self.widget_texts()
        self.release.set()
        self.wait(worker)
        self.assertEqual(len(self.ask_messages(COST_TITLE)), 1)
        self.assertNotEqual(during, before, "AI を始めた時点で欄が置き換わっていない")
        for key, texts in during.items():
            self.assertTrue(any(SYNC_BUSY_TEXT in t for t in texts), f"{key}: {texts}")
        self.assertEqual(self.dialog_main, [True, True], "ダイアログはメインスレッドで出す")
        for tag in ("save_knowledge", "report", "browser", "record", "ai:summary"):
            self.assertIn(tag, self.events)
        self.assertTrue(os.path.exists(oto().COCKPIT_LAST_RESULT_FILE))
        self.assertTrue(self.status().startswith("✅ 全解析同期完了（今回のAI費用 約"), self.status())
        self.assertEqual(self.totals_at_cost_ask, [PREV_TOTALS], "(fix1 M2) 確認の時点では、まだ集計を0にしない")
        self.assertEqual(self.totals(), tok(151 + 4), "AIの直前に0へ戻し、今回の分だけになる (A7e: Stage1 151 + 決勝戦4)")


class TestSyncException(CockpitCase):
    def test_error_dialog_is_actually_shown(self):
        """例外: エラーダイアログ (本文 `型名: メッセージ`) が実際に出る。ステータスは「❌ 失敗しました（ここまでのAI費用 約X円）: 型名: メッセージ」。ボタン復帰。"""
        gui = self.build(["P1"], [], {"P1": mails_for({"a1": 1})})
        self.summary_error = ValueError("決勝戦で失敗-xyz")
        self.run_flow(gui._sync_and_refresh_cockpit)
        errs = self.errors()
        self.assertEqual(len(errs), 1, f"エラーダイアログが出ていない: {self.callback_errors}")
        self.assertIn("ValueError: 決勝戦で失敗-xyz", errs[0])
        m = re.fullmatch(r"❌ 失敗しました（ここまでのAI費用 約([0-9.]+)円）: ValueError: 決勝戦で失敗-xyz", self.status())
        self.assertIsNotNone(m, f"失敗の表示の形が違う (PJ分析で費用が出ているので、費用を先頭寄りに出す): {self.status()!r}")
        spent = self.spent()
        self.assertGreater(spent, 0)
        self.assertIn(float(m.group(1)), {round(spent), round(spent, 1), round(spent, 2)})
        self.assertEqual(str(gui.btn_sync_cockpit.cget("state")), "normal")
        self.assertNotIn("record", self.events)

    def test_failure_before_confirm_shows_no_cost_and_keeps_totals(self):
        """(fix1 M2) 確認より前 (取得中) の失敗: 「❌ 失敗しました: 型名: メッセージ」(前回までの集計を費用として出さない)。集計も変えない。"""
        gui = self.build(["P1"], [], {"P1": mails_for({"a1": 1})})

        def broken(proj, days, include_sent=False):
            raise RuntimeError("取得で失敗-s")
        gui.outlook.get_project_mails = broken
        self.preset_totals()
        self.run_flow(gui._sync_and_refresh_cockpit)
        self.assertEqual(self.status(), "❌ 失敗しました: RuntimeError: 取得で失敗-s")
        self.assertEqual(len(self.errors()), 1)
        self.assertEqual(self.totals(), PREV_TOTALS)
        self.assertEqual(self.usage_log(), [])


class TestV2Flow(CockpitCase):
    def build_v2(self, n_per_project):
        projects = ["P1", "P2"]
        mails = {"P1": mails_for(big_spec("x", n_per_project)), "P2": mails_for(big_spec("y", n_per_project))}
        return self.build(projects, [], mails)

    def test_cancel(self):
        """100円以上で「いいえ」: 取得の後・generate の前に見積り。generate なし・HTMLなし・保存なし・実績ログなし・中止の表示。"""
        gui = self.build_v2(150)
        self.answers[COST_TITLE] = False
        self.preset_totals()
        self.run_flow(gui._run_cockpit_v2)
        self.assertEqual(self.totals(), PREV_TOTALS, "(fix1 M2) 確認で中止しただけで、集計 (他の画面の分) を0にした")
        est = self.estimate()
        self.assertTrue(est["needs_confirm"], f"前提: 100円以上 ({est['yen']})")
        msgs = self.ask_messages(COST_TITLE)
        self.assertEqual(len(msgs), 1)
        self.assertIn(f"統括コックピットv2のAI費用の見込み: 約{est['yen']:.0f}円", msgs[0])
        ev = self.events
        self.assertLess(max(i for i, e in enumerate(ev) if e.startswith("fetch:")), ev.index("estimate"))
        for tag in ("ai:v2", "report", "browser", "record"):
            self.assertNotIn(tag, ev)
        self.assertFalse(os.path.exists(oto().COCKPIT_V2_LAST_RESULT_FILE))
        self.assertEqual(self.usage_log(), [])
        self.assertEqual(self.status(), CANCEL_TEXT)
        self.assertEqual(str(gui.btn_run_cockpit_v2.cget("state")), "normal")
        self.assertEqual(str(gui.btn_run_cockpit_v2.cget("text")), V2_BTN_TEXT)

    def test_success_records_action_usage(self):
        """成功: 見積りは generate の前。実績ログ feature="action" (成功件数)。ステータス「✅ 統括コックピット v2 生成完了（今回のAI費用 …）」。"""
        gui = self.build_v2(3)
        self.preset_totals()
        self.run_flow(gui._run_cockpit_v2)
        self.assertEqual(self.totals(), tok(6), "(fix1 M2) AIの直前に0へ戻し、今回の分だけになる")
        est = self.estimate()
        self.assertEqual(est["n_calls"], 6)
        ev = self.events
        self.assertLess(ev.index("estimate"), ev.index("ai:v2"))
        self.assertEqual(self.ask_messages(COST_TITLE), [])
        log = self.usage_log()
        s = gui.summarizer
        self.assertEqual([(r["feature"], r["n_calls"], r["input_tokens"], r["output_tokens"]) for r in log],
                         [("action", 6, s.total_input_tokens, s.total_output_tokens)])
        self.assert_cost_in_status("✅ 統括コックピット v2 生成完了", "6件")
        self.assertTrue(os.path.exists(oto().COCKPIT_V2_LAST_RESULT_FILE))
        self.assertEqual(self.browser, ["report.html"])

    def test_nothing_to_analyze_still_generates_without_confirm(self):
        """解析が要らない (n_calls=0): 確認なしで generate を呼ぶ (キャッシュから作るため)。実績ログは書かない。
        表示は「✅ 統括コックピット v2 生成完了（新しい解析は不要でした）」。"""
        gui = self.build(["P1"], [], {})
        self.preset_totals()
        self.run_flow(gui._run_cockpit_v2)
        self.assertEqual(self.totals(), (0, 0), "(fix1 M2) 見積り0件 (確認なし) でも generate の直前で0へ戻す")
        self.assertEqual(self.estimate()["n_calls"], 0)
        self.assertEqual(self.ask_messages(COST_TITLE), [])
        self.assertIn("ai:v2", self.events)
        self.assertEqual(self.usage_log(), [])
        self.assertEqual(self.status(), "✅ 統括コックピット v2 生成完了（新しい解析は不要でした）")
        self.assertEqual(self.errors(), [])

    def test_failures(self):
        """AI失敗あり: 「⚠ 完了（AI失敗N件。…）（今回のAI費用 約X円・成功M/N件）」、実績ログは成功件数。"""
        gui = self.build_v2(3)
        self.fail_cids = {"x000", "y002"}
        self.run_flow(gui._run_cockpit_v2)
        self.assert_cost_in_status("⚠ 完了（AI失敗2件。もう一度実行すると再試行）", "成功4/6件")
        self.assertEqual([(r["feature"], r["n_calls"]) for r in self.usage_log()], [("action", 4)])

    def test_html_failure(self):
        """HTML生成に失敗 (path が空): ダイアログ「統括コックピット v2 の生成に失敗しました。」。
        (fix1 Minor4) ステータスは「❌ 生成失敗（今回のAI費用 約X円）」。"""
        gui = self.build_v2(1)
        self.reporter.path = ""
        self.run_flow(gui._run_cockpit_v2)
        self.assertEqual(len(self.errors()), 1)
        self.assertIn("統括コックピット v2 の生成に失敗しました。", self.errors()[0])
        m = re.fullmatch(r"❌ 生成失敗（今回のAI費用 約([0-9.]+)円）", self.status())
        self.assertIsNotNone(m, self.status())
        spent = self.spent()
        self.assertIn(float(m.group(1)), {round(spent), round(spent, 1), round(spent, 2)})
        self.assertEqual(self.browser, [])
        self.assertEqual(str(gui.btn_run_cockpit_v2.cget("state")), "normal")

    def test_exception(self):
        """例外: ダイアログ本文に「統括コックピット v2 の生成中にエラーが発生しました:」と `型名: メッセージ`、ステータス「❌ 失敗しました: …」。"""
        gui = self.build_v2(1)
        self.v2_error = RuntimeError("v2で失敗-abc")
        self.run_flow(gui._run_cockpit_v2)
        errs = self.errors()
        self.assertEqual(len(errs), 1)
        self.assertIn("統括コックピット v2 の生成中にエラーが発生しました:", errs[0])
        self.assertIn("RuntimeError: v2で失敗-abc", errs[0])
        self.assertEqual(self.status(), "❌ 失敗しました: RuntimeError: v2で失敗-abc", "費用0なら費用の括弧なし")
        self.assertEqual(self.usage_log(), [])
        self.assertEqual(str(gui.btn_run_cockpit_v2.cget("text")), V2_BTN_TEXT)

    def test_failure_before_confirm_shows_no_cost_and_keeps_totals(self):
        """(fix1 M2) 確認より前 (取得中) の失敗: 「❌ 失敗しました: 型名: メッセージ」(費用なし)。集計を変えない。"""
        gui = self.build_v2(1)

        def broken(proj, days, include_sent=False):
            raise RuntimeError("取得で失敗-v")
        gui.outlook.get_project_mails = broken
        self.preset_totals()
        self.run_flow(gui._run_cockpit_v2)
        self.assertEqual(self.status(), "❌ 失敗しました: RuntimeError: 取得で失敗-v")
        self.assertIn("RuntimeError: 取得で失敗-v", self.errors()[0])
        self.assertEqual(self.totals(), PREV_TOTALS)

    def test_unreadable_cache_after_generate_is_unverified(self):
        """(fix1 Minor3) 解析後のキャッシュが読めない: 「⚠ 完了（解析後の結果を読めず、成否は未確認）（今回のAI費用 約X円・N件）」、実績ログなし。"""
        gui = self.build_v2(3)
        self.v2_corrupt_cache = True
        self.run_flow(gui._run_cockpit_v2)
        self.assertIsNone(oto().load_action_dashboard_cache(), "前提: 解析後のキャッシュが読めない")
        self.assert_cost_in_status("⚠ 完了（解析後の結果を読めず、成否は未確認）", "6件")
        self.assertEqual(self.usage_log(), [])


# ============================================================
# 3b. (fix1 水平展開) アクション解析・振り返りも、集計の0リセットは確認の後
# ============================================================
class HorizontalResetCase(a2e.EntrypointCase):
    """A2 の入口ハーネス (本物の入口・本物の MailSummarizer・偽AI 1回=6000/3300) で、_run_action_dashboard (両ボタン) と
    _run_review を動かす。確認ダイアログを出すため、見積りの関数だけ「100円以上」の固定値を返すものに差し替える
    (ここで確かめるのはリセットの位置。見積りの中身は A1.1 / A7a のテストの範囲)。"""

    BIG = {"input_tokens": 500000, "output_tokens": 400000, "yen": 250.0, "needs_confirm": True, "price_known": True,
           "n_calls": 150, "input_chars": 500000, "output_tokens_per_call": 2500, "calibrated": False}

    def setUp(self):
        gc.disable()
        self.addCleanup(gc.enable)
        self.addCleanup(gc.collect)
        self.answers = {}
        self.totals_at_cost_ask = []
        super().setUp()

    def _patch_messagebox(self):
        super()._patch_messagebox()
        inner = tkmessagebox.askyesno

        def ask(*args, **kwargs):
            inner(*args, **kwargs)
            title = args[0] if args else kwargs.get("title")
            if title == COST_TITLE and getattr(self, "gui", None) is not None:
                s = self.gui.summarizer
                self.totals_at_cost_ask.append((s.total_input_tokens, s.total_output_tokens))
            return self.answers.get(title, True)
        p = mock.patch.object(tkmessagebox, "askyesno", ask)
        p.start()
        self.addCleanup(p.stop)

    def build_with(self, estimate_name, estimate=None):
        gui = self.build()
        fake = estimate or (lambda *a, **k: dict(self.BIG))
        p = mock.patch.object(oto(), estimate_name, fake)
        p.start()
        self.addCleanup(p.stop)
        return gui

    def go(self, start):
        """前回までの集計 (111/222) を入れてから入口を1回実行し、終わるまで待つ。"""
        s = self.gui.summarizer
        s.total_input_tokens, s.total_output_tokens = PREV_TOTALS
        self.wait_for(self.start_flow(start))

    def totals(self):
        s = self.gui.summarizer
        return (s.total_input_tokens, s.total_output_tokens)

    def status(self):
        return str(self.gui.lbl_stat.cget("text"))


class TestActionDashboardResetAfterConfirm(HorizontalResetCase):
    def test_no_keeps_the_totals_for_both_buttons(self):
        """「📋 アクション一覧を生成」「🔄 解析のみ更新」とも、確認で「いいえ」なら集計 (前回までの 111/222) を変えない。"""
        gui = self.build_with("estimate_action_analysis_cost")
        self.answers[COST_TITLE] = False
        for open_browser in (True, False):
            with self.subTest(open_browser=open_browser):
                self.go(lambda ob=open_browser: gui._run_action_dashboard(open_browser=ob))
                self.assertEqual(self.totals(), PREV_TOTALS)
                self.assertEqual(self.status(), "⏹ 費用の確認で中止しました（AI解析は行っていません）")
        self.assertEqual(len(self.totals_at_cost_ask), 2, "前提: 確認ダイアログが2回出た")

    def test_yes_resets_after_the_confirmation(self):
        """「はい」: 確認の時点ではまだ前回までの集計のまま、解析の直前に0へ戻り、終了時は今回の1回分だけ。"""
        gui = self.build_with("estimate_action_analysis_cost")
        for open_browser in (True, False):
            with self.subTest(open_browser=open_browser):
                self.totals_at_cost_ask.clear()
                self.go(lambda ob=open_browser: gui._run_action_dashboard(open_browser=ob))
                self.assertEqual(self.totals_at_cost_ask, [PREV_TOTALS])
                self.assertEqual(self.totals(), tok(a2e.N_CALLS))
                self.assertEqual(self.dialog_text({"showerror"}), "")


class TestReviewResetAfterConfirm(HorizontalResetCase):
    def test_no_keeps_the_totals(self):
        """振り返り: 確認で「いいえ」なら集計を変えない。"""
        gui = self.build_with("estimate_review_cost")
        self.answers[COST_TITLE] = False
        self.go(gui._run_review)
        self.assertEqual(len(self.totals_at_cost_ask), 1, "前提: 確認ダイアログが出た")
        self.assertEqual(self.totals(), PREV_TOTALS)
        self.assertEqual(self.status(), "⏹ 費用の確認で中止しました（AI分析は行っていません）")

    def test_yes_resets_after_the_confirmation(self):
        """振り返り「はい」: 確認の時点ではまだ前回までの集計のまま、生成の直前に0へ戻り、終了時は今回の1回分だけ。"""
        gui = self.build_with("estimate_review_cost")
        self.go(gui._run_review)
        self.assertEqual(self.totals_at_cost_ask, [PREV_TOTALS])
        self.assertEqual(self.totals(), tok(a2e.N_CALLS))
        self.assertEqual(self.dialog_text({"showerror"}), "")

    def test_failure_before_confirm_shows_no_cost(self):
        """振り返り: 確認より前の失敗では「ここまでのAI費用」を出さない (前回までの集計が残っているため)。集計も変えない。"""
        def broken(*args, **kwargs):
            raise RuntimeError("見積りの前で失敗-r")
        gui = self.build_with("estimate_review_cost", broken)
        self.go(gui._run_review)
        self.assertEqual(self.status(), "❌ 失敗しました: RuntimeError: 見積りの前で失敗-r")
        self.assertEqual(self.totals(), PREV_TOTALS)


# ============================================================
# 4. 範囲ガード (AST)
# ============================================================
SYNC = "MailManagerGUI._sync_and_refresh_cockpit"
V2 = "MailManagerGUI._run_cockpit_v2"
ACTION = "MailManagerGUI._run_action_dashboard"
REVIEW = "MailManagerGUI._run_review"
ALLOWED_TO_CHANGE = {SYNC, V2, ACTION, REVIEW}     # (fix1) 後の2つは、リセットの位置と ai_started だけ
NEW_FUNCTIONS = ["estimate_cockpit_v2_cost", "estimate_cockpit_sync_cost", "MailManagerGUI._finish_cockpit_status"]
NEW_CONSTANTS = ["COCKPIT_SUMMARY_ESTIMATE_CALLS", "COCKPIT_SUMMARY_ESTIMATE_INPUT_CHARS",
                 "COCKPIT_SUMMARY_ESTIMATE_OUTPUT_TOKENS"]
MUST_STAY_UNCHANGED = ["MailManagerGUI._refresh_cockpit", "MailSummarizer.generate_cockpit_summary",
                       "MailSummarizer.generate_cockpit_v2_data", "MailSummarizer.summarize_project_threads",
                       "MailSummarizer.summarize_staff_threads", "MailManagerGUI._confirm_ai_cost",
                       "estimate_overview_cost", "estimate_action_analysis_cost", "record_ai_usage"]


class TestScopeGuardA7c(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.target = _loader.rev_path(NEW_REV)
        cls.baseline = _loader.rev_path(OLD_REV)
        if not (os.path.isfile(cls.target) and os.path.isfile(cls.baseline)):
            raise unittest.SkipTest(f"A7c のリビジョン対({OLD_REV} / {NEW_REV})が無い")
        cls.old = a7a._index_source(cls.baseline)
        cls.new = a7a._index_source(cls.target)

    def test_nothing_removed(self):
        """既存の関数・メソッド・定数が消えていない。"""
        self.assertEqual(sorted(n for n in self.old[0] if n not in self.new[0]), [])
        self.assertEqual(sorted(n for n in self.old[1] if n not in self.new[1]), [])

    def test_only_allowed_methods_changed(self):
        """変更された既存メソッドは _sync_and_refresh_cockpit・_run_cockpit_v2 と、(fix1 水平展開) _run_action_dashboard・
        _run_review だけ (どれも実際に変更あり)。"""
        old_f, new_f = self.old[0], self.new[0]
        changed = sorted(n for n, s in old_f.items() if n in new_f and new_f[n] != s)
        self.assertEqual(changed, sorted(ALLOWED_TO_CHANGE))

    def test_action_and_review_change_only_the_reset_position(self):
        """(fix1) _run_action_dashboard・_run_review の変更は、リセットの位置と ai_started だけ: 呼び出しの種類と数は同じで、
        集計を0にする代入はどちらも1か所のまま。"""
        from collections import Counter
        for q in (ACTION, REVIEW):
            with self.subTest(q=q):
                old_fn, new_fn = a7a.func_node(self.baseline, q), a7a.func_node(self.target, q)
                self.assertEqual(Counter(a7a._call_names_in_source_order(new_fn)),
                                 Counter(a7a._call_names_in_source_order(old_fn)))
                for fn in (old_fn, new_fn):
                    resets = [n for n in ast.walk(fn) if isinstance(n, ast.Assign) and any(
                        isinstance(t, ast.Attribute) and t.attr in ("total_input_tokens", "total_output_tokens")
                        for t in n.targets)]
                    self.assertEqual(len(resets), 2, "集計を0にする代入 (入力・出力) は1か所ずつ")

    def test_refresh_and_ai_functions_unchanged(self):
        """「表示のみ更新」(_refresh_cockpit)・generate_cockpit_summary・generate_cockpit_v2_data・summarize_* などは不変。"""
        for q in MUST_STAY_UNCHANGED:
            with self.subTest(q=q):
                self.assertIn(q, self.old[0])
                self.assertEqual(self.new[0].get(q), self.old[0][q])

    def test_only_spec_names_added(self):
        """追加は定数3つ・関数2つ・メソッド _finish_cockpit_status だけ。既存定数・import・その他の文・クラスの骨格は不変。"""
        self.assertEqual(sorted(set(self.new[0]) - set(self.old[0])), sorted(NEW_FUNCTIONS))
        self.assertEqual(sorted(set(self.new[1]) - set(self.old[1])), sorted(NEW_CONSTANTS))
        self.assertEqual(sorted(n for n, s in self.old[1].items() if self.new[1].get(n) != s), [])
        self.assertEqual(self.old[2] - self.new[2], set())
        self.assertEqual(self.old[3], self.new[3])
        self.assertEqual(self.old[4], self.new[4])

    def test_new_definitions_placed_between(self):
        """追加の定数・関数は count_failed_overview_threads の後・load_project_knowledge の前にひとまとまりで置かれる。"""
        names = a7a._top_level_names(self.target)
        pos = sorted(names[n] for n in NEW_CONSTANTS + NEW_FUNCTIONS[:2])
        self.assertGreater(min(pos), names["count_failed_overview_threads"])
        self.assertLess(max(pos), names["load_project_knowledge"])
        self.assertEqual(pos, list(range(pos[0], pos[0] + len(pos))))


if __name__ == "__main__":
    unittest.main(verbosity=2)
