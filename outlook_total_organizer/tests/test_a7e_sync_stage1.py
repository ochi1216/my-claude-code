# -*- coding: utf-8 -*-
"""A7e テスト: 統括コックピットの全自動同期で、結果を使っていない統合 (Stage2) を省く (仕様書 A7E_SPEC.md。A7e は _14 で入った)。

根拠は仕様書だけ (期待値は実装を見ずに決めた。後で実装と照合した)。
  1. summarize_project_threads / summarize_staff_threads(stage1_only): 本物のメソッドを、AI の応答だけ偽物にして動かす
     (トークンの集計は本物の経路)。True なら Stage1 の解析キャッシュは従来 (既定・_13) と同じに更新され、Stage2 の
     AI 呼び出しは0回、戻り値は初期値のまま。既定 (False) は従来どおり Stage2 を呼ぶ。
  2. estimate_overview_cost(include_stage2): False なら n_calls_s2=0・Stage2 の字数0。1回あたりの出力は実績 "{kind}_s1" を
     優先・無ければ kind・どちらも無ければ Stage1 の既定値。True (既定) は _13 と完全に同じ ("{kind}_s1" の実績は読まない)。
  3. estimate_cockpit_sync_cost: プロジェクト・スタッフは Stage1 だけ (include_stage2=False) を数える。決勝戦は従来どおり。
  4. 全自動同期 (_sync_and_refresh_cockpit) を偽の Outlook・偽の AI で通す: summarize_* に stage1_only=True が渡る、
     Stage2 の AI 呼び出しが無い、完了表示の件数 = Stage1 + 決勝戦、実績ログは "project_s1" / "staff_s1" / "cockpit_summary"。
     同じ入力で _13 の同期も動かし、HTML・保存結果・解析キャッシュ・ナレッジが _13 と同じ (Stage2 を省いても出力が変わらない)。
  5. 俯瞰2画面 (_run_project_overview / _run_staff_overview) は従来どおり Stage2 を呼び、"project" / "staff" に記録する。
  6. 範囲ガード (AST・ファイル名で _13 と _14 を指定)。

方針: 一時cwd の中だけで動かす。固定時間の sleep は使わない (mainloop で待つ)。ネットワーク・実Outlook・実ブラウザには
触れない。GUI のテストは tkinter とディスプレイが無ければ自動 skip (Linux は xvfb-run -a /usr/bin/python3.12 tests/run_tests.py)。
"""
import ast
import collections
import contextlib
import copy
import functools
import gc
import hashlib
import importlib.util
import inspect
import json
import os
import random
import re
import sys
import threading
import unittest
import webbrowser                                  # noqa: F401  (mock.patch("webbrowser.open") の対象を先に読み込む)
from datetime import datetime, timedelta
from unittest import mock

import _loader
import test_a1_gui_smoke as a1gui                  # GuiCase (一時cwd・messagebox の記録・待機・後始末)
import test_a2_entrypoints as a2e                  # 偽の AI 応答1回の使用量 (入力6000 / 出力3300)
import test_a7a_review_cost as a7a                 # AST の索引ヘルパ
import test_a7b_overview_cost as a7b               # 見積りの参照計算・入力データ・俯瞰の画面ハーネス
from _loader import read_bytes, snapshot_files, tempdir_cwd, write_json


def oto():
    return _loader.load()


OLD_REV = "outlook_total_organizer_20261004_13.py"
NEW_REV = "outlook_total_organizer_20261004_14.py"
FLASH = "gemini-2.5-flash"
LITE = "gemini-2.5-flash-lite"
CALL_IN, CALL_OUT = a2e.CALL_IN, a2e.CALL_OUT     # 偽AI 1回あたりの (入力, 出力) = (6000, 3300)
LOG_PATH = os.path.join("json", "ai_usage_log.jsonl")
KNOWLEDGE_PATH = os.path.join("json", "project_knowledge.json")
LAST_RESULT_PATH = os.path.join("json", "cockpit_last_result.json")
INITIAL_RESULT = {"manager_actions": [], "staff_status": [], "stalled_monitor": [], "updated_history": "",
                  "ai_questions": [], "threads": []}
ROLE_KEYS = ("site_manager_view", "r19_pm_view", "pm_manager_view", "te_pe_view")
KINDS = ("project", "staff")
FLOW_TIMEOUT = 60


@functools.lru_cache(maxsize=None)
def load_rev(filename):
    """ツールフォルダの指定リビジョンを別名で読み込む (突き合わせ用)。無ければ None。"""
    path = os.path.join(_loader.TOOL_DIR, filename)
    if not os.path.isfile(path):
        return None
    oto()                                                  # 先に最小スタブを入れておく
    name = "oto_a7e_rev_" + re.sub(r"\W", "_", os.path.splitext(filename)[0])
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    with tempdir_cwd():
        spec.loader.exec_module(mod)
    return mod


def old_mod(test):
    mod = load_rev(OLD_REV)
    if mod is None:
        test.skipTest(f"{OLD_REV} が無い")
    return mod


def new_mod(test):
    """_14 を名前で読み込む。_13 との出力の突き合わせは、最新のリビジョンではなく _14 で行う
    (後のリビジョンが共通のJSなどを変えても、この比較が崩れないように)。"""
    mod = load_rev(NEW_REV)
    if mod is None:
        test.skipTest(f"{NEW_REV} が無い")
    return mod


@contextlib.contextmanager
def chdir(sub):
    """一時cwd の下の別のフォルダで動かす (_13 と _14 を同じ入力で別々に動かすため)。"""
    old = os.getcwd()
    os.makedirs(sub, exist_ok=True)
    os.chdir(sub)
    try:
        yield os.getcwd()
    finally:
        os.chdir(old)


def load_json_tree(folder):
    """folder の下の .json を {相対パス: 中身(dict)} で返す (キーの順番は比べない)。"""
    out = {}
    if not os.path.isdir(folder):
        return out
    for fn in sorted(os.listdir(folder)):
        if fn.endswith(".json"):
            with open(os.path.join(folder, fn), encoding="utf-8") as f:
                out[fn] = json.load(f)
    return out


def usage_log():
    if not os.path.exists(LOG_PATH):
        return []
    with open(LOG_PATH, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def write_log(*records):
    a7b.write_log(*records)


rec = a7b.rec


# ============================================================
# 偽の AI (応答だけ。トークンの集計は本物の経路)
# ============================================================
def stage_of(schema):
    props = (schema or {}).get("properties") or {}
    if "thread_id" in props:
        return "s1"
    if "manager_actions" in props:
        return "s2"
    if any(k in props for k in ROLE_KEYS):
        return "summary"
    return "other"


def s1_data(cid):
    """偽AI の Stage1 の解析結果 (解析キャッシュに書かれる data)。"""
    return {"thread_id": cid, "topic": f"トピック {cid}", "is_target": True,
            "summary": f"{cid} の要約。承認待ちの案件で、関係者の回答を待っています。", "category": "プロジェクト管理",
            "project_scope": "横断業務", "action_type": "承認・決裁", "importance": "高", "reasoning": "根拠",
            "actions": [{"owner": "Sato", "action": "承認する", "deadline": "", "status": "未着手"}]}


class FakeAI:
    """本物の MailSummarizer (mod のもの) を作り、client.models.generate_content だけを偽物にする。
    _run_genai_call_with_schema (本物) を1回ずつ直列にして呼び (並列の加算でトークンの集計が欠けないように)、
    段 ("s1" / "s2" / "summary") ・プロンプト・モデルを記録する。fail_cids の Stage1 は空の回答 (=失敗) を返す。"""

    def __init__(self, mod, model=FLASH, fail_cids=()):
        self.mod = mod
        self.s = mod.MailSummarizer("dummy", model)
        self.fail_cids = set(fail_cids)
        self.calls = []
        self.lock = threading.Lock()
        self._cur = None
        real = type(self.s)._run_genai_call_with_schema
        s = self.s

        def serialized(prompt, schema, override_model=None):
            with self.lock:
                self._cur = (prompt, schema)
                try:
                    return real(s, prompt, schema, override_model)
                finally:
                    self._cur = None
        s._run_genai_call_with_schema = serialized
        s.client.models.generate_content = self.generate

    def generate(self, model=None, contents=None, config=None):
        prompt, schema = self._cur
        stage = stage_of(schema)
        self.calls.append((stage, prompt, model))
        reply = self.reply(stage, prompt, schema)
        text = "" if reply is None else json.dumps(reply, ensure_ascii=False)
        raw = {"candidates": [{"content": {"parts": [{"text": text}]}}], "usageMetadata": dict(a2e.USAGE)}
        return self.mod._CommonGeminiResponse(raw)

    def reply(self, stage, prompt, schema):
        if stage == "s1":
            m = re.search(r'thread_id は理由を問わず "(.*?)"', prompt)
            cid = m.group(1) if m else "?"
            return None if cid in self.fail_cids else s1_data(cid)
        if stage == "s2":
            item = {"category": "プロジェクト管理", "project_scope": "横断業務", "action_type": "承認・決裁",
                    "text": "統合の結果", "status_icon": "🔴", "source_thread_ids": []}
            return {"manager_actions": [item], "staff_status": [dict(item)], "stalled_monitor": [dict(item)],
                    "updated_history": "統合の経緯", "ai_questions": ["質問"]}
        if stage == "summary":
            view = next(k for k in ROLE_KEYS if k in schema["properties"])
            ids = sorted(set(re.findall(r"\[ID: ([^\]]+)\]", prompt)))
            if not ids:
                return {view: {"red_alerts": [], "blue_highlights": [], "yellow_stalled": []}}

            def pick(i):
                return [{"source_thread_ids": [ids[i]], "category": "要対応", "text": f"{view} の {ids[i]}"}]
            return {view: {"red_alerts": pick(0), "blue_highlights": pick(-1), "yellow_stalled": pick(len(ids) // 2)}}
        return {"ok": 1}

    def n(self, stage=None):
        return sum(1 for c in self.calls if stage is None or c[0] == stage)

    def prompts(self, stage):
        return sorted((p, m) for st, p, m in self.calls if st == stage)


class InTempCwd(unittest.TestCase):
    def setUp(self):
        cm = tempdir_cwd()
        self.tmp = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)


# ============================================================
# 1. summarize_*(stage1_only)
# ============================================================
RULES = ["ルール1"]


def summarize_data(kind):
    """(per_target, knowledge)。Stage1 は A の c1・c2・c3 と B の b0・b1 の5回、Stage2 は A・B の2回 (既定のとき。
    put_summarize_cache の解析キャッシュがあるとき)。"""
    know = a7b.know_of(kind, "A", rules=RULES, master_history="経緯" * 5, role="役割", background="背景")
    per = {"A": a7b.threads_of(4, "本文" * 30), "B": a7b.threads_of(2, "別の本文", prefix="b")}
    return per, know


def put_summarize_cache(kind):
    """解析キャッシュ (A: c0 は解析済み・c1 は前回失敗・c2 は件数違い) を cwd に置く。"""
    a7b.put_cache(kind, "A", {"c0": (1, False), "c1": (1, True), "c2": (5, False)}, rules=RULES)


def summarize_input(kind):
    put_summarize_cache(kind)
    return summarize_data(kind)


def run_summarize(kind, per, know, mod=None, fail_cids=(), **kwargs):
    ai = FakeAI(mod or oto(), FLASH, fail_cids)
    fn = getattr(ai.s, f"summarize_{kind}_threads")
    progress, results = [], {}
    for name, threads in per.items():
        results[name] = fn(name, copy.deepcopy(threads), know, progress_callback=progress.append, **kwargs)
    return ai, results, progress


class TestSummarizeStage1Only(InTempCwd):
    def test_stage1_only_true_makes_no_stage2_call_and_returns_the_initial_result(self):
        """stage1_only=True: Stage1 は従来どおり5回 (キャッシュの判定も同じ)、Stage2 は0回、戻り値は初期値のまま。"""
        for kind in KINDS:
            with self.subTest(kind=kind), chdir(kind):
                per, know = summarize_input(kind)
                ai, results, _ = run_summarize(kind, per, know, stage1_only=True)
                self.assertEqual((ai.n("s1"), ai.n("s2"), ai.n()), (5, 0, 5))
                for name, res in results.items():
                    self.assertEqual(res, INITIAL_RESULT, name)

    def test_default_still_calls_stage2(self):
        """既定 (引数なし) と stage1_only=False: 従来どおり Stage2 を対象ごとに1回呼び、統合の結果を返す。"""
        for kind in KINDS:
            for label, kwargs in (("omitted", {}), ("false", {"stage1_only": False})):
                with self.subTest(kind=kind, label=label), chdir(f"{kind}_{label}"):
                    per, know = summarize_input(kind)
                    ai, results, _ = run_summarize(kind, per, know, **kwargs)
                    self.assertEqual((ai.n("s1"), ai.n("s2")), (5, 2))
                    for name, res in results.items():
                        self.assertEqual(len(res["manager_actions"]), 1, name)
                        self.assertIn("統合の経緯", res["updated_history"], name)
                        self.assertEqual(sorted(t["thread_id"] for t in res["threads"]), sorted(per[name]), name)

    def test_stage1_cache_is_the_same_as_default_and_13(self):
        """stage1_only=True でも、Stage1 の解析キャッシュは既定 (_14) と _13 と同じに更新される。Stage1 のプロンプト・モデルも同じ。
        (前回失敗・件数違い・新規・ルールあり・一部失敗を含む)"""
        old = old_mod(self)
        for kind in KINDS:
            for fail in ((), ("c3", "b0")):
                runs = {}
                per, know = summarize_data(kind)
                for label, mod, kwargs in (("s1only", oto(), {"stage1_only": True}), ("default", oto(), {}),
                                           ("rev13", old, {})):
                    with chdir(f"{kind}_{len(fail)}_{label}"):
                        put_summarize_cache(kind)
                        ai, _, _ = run_summarize(kind, per, know, mod, fail, **kwargs)
                        runs[label] = (load_json_tree("analysis_cache"), ai.prompts("s1"),
                                       mod.count_failed_overview_threads(kind, per))
                with self.subTest(kind=kind, fail=fail):
                    caches, prompts, failed = runs["s1only"]
                    self.assertEqual(sorted(caches), [f"{kind}_A.json", f"{kind}_B.json"])
                    self.assertEqual(failed, len(fail))
                    for other in ("default", "rev13"):
                        self.assertEqual(caches, runs[other][0], f"解析キャッシュが {other} と違う")
                        self.assertEqual(prompts, runs[other][1], f"Stage1 のプロンプト・モデルが {other} と違う")
                        self.assertEqual(failed, runs[other][2])
                    models = {m for _p, m in prompts}
                    self.assertEqual(models, {LITE} if kind == "staff" else {FLASH}, "Stage1 のモデル (従来どおり)")

    def test_stage1_only_with_everything_cached_makes_no_call_and_keeps_the_file(self):
        """全件解析済み: stage1_only=True は AI を呼ばず、解析キャッシュのファイルも書き換えない。戻り値は初期値のまま。"""
        for kind in KINDS:
            with self.subTest(kind=kind), chdir(kind):
                per = {"A": a7b.threads_of(2)}
                a7b.put_cache(kind, "A", {"c0": (1, False), "c1": (1, False)})
                path = a7b.cache_path(kind, "A")
                before = (read_bytes(path), os.stat(path).st_mtime_ns)
                ai, results, _ = run_summarize(kind, per, {}, stage1_only=True)
                self.assertEqual(ai.n(), 0)
                self.assertEqual(results["A"], INITIAL_RESULT)
                self.assertEqual((read_bytes(path), os.stat(path).st_mtime_ns), before)

    def test_tokens_are_only_the_stage1_calls(self):
        """stage1_only=True のトークンの集計は Stage1 の回数分だけ (Stage2 の分が無い)。"""
        for kind in KINDS:
            with self.subTest(kind=kind), chdir(kind):
                per, know = summarize_input(kind)
                ai, _, _ = run_summarize(kind, per, know, stage1_only=True)
                self.assertEqual((ai.s.total_input_tokens, ai.s.total_output_tokens), (5 * CALL_IN, 5 * CALL_OUT))

    def test_empty_threads_are_unchanged(self):
        """スレッドが空の対象は従来どおり (AI なし。戻り値は _13・既定と同じ)。"""
        old = old_mod(self)
        for kind in KINDS:
            with self.subTest(kind=kind):
                ai = FakeAI(oto())
                fn = getattr(ai.s, f"summarize_{kind}_threads")
                got = fn("X", {}, {}, stage1_only=True)
                self.assertEqual(got, fn("X", {}, {}))
                old_ai = FakeAI(old)
                self.assertEqual(got, getattr(old_ai.s, f"summarize_{kind}_threads")("X", {}, {}))
                self.assertEqual(ai.n(), 0)

    def test_signature(self):
        """引数は従来のものの後ろに stage1_only (既定 False) が増えただけ (名前・順番・既定値)。"""
        old = old_mod(self)
        for meth in ("summarize_project_threads", "summarize_staff_threads"):
            with self.subTest(meth=meth):
                new_p = list(inspect.signature(getattr(oto().MailSummarizer, meth)).parameters.values())
                old_p = list(inspect.signature(getattr(old.MailSummarizer, meth)).parameters.values())
                self.assertEqual([(p.name, p.default, p.kind) for p in new_p[:-1]],
                                 [(p.name, p.default, p.kind) for p in old_p])
                self.assertEqual((new_p[-1].name, new_p[-1].default), ("stage1_only", False))


class TestSpecGapStage1OnlyProgress(InTempCwd):
    """(SpecGap) stage1_only=True のときの進捗表示。仕様「Stage2 に入る前に返す」を、Stage2 の進捗表示 (「Stage 2」) も
    出さないと自然に解釈する (同期のステータスに、行わない統合の表示が出ないように)。"""

    def test_no_stage2_progress_message(self):
        """stage1_only=True の progress_callback に「Stage 2」の表示が無い (既定では出る)。"""
        for kind in KINDS:
            with self.subTest(kind=kind), chdir(kind):
                per, know = summarize_input(kind)
                _ai, _r, progress = run_summarize(kind, per, know, stage1_only=True)
                self.assertTrue(any("Stage 1" in str(m) for m in progress), progress)
                self.assertFalse([m for m in progress if "Stage 2" in str(m)])


# ============================================================
# 2. estimate_overview_cost(include_stage2)
# ============================================================
def est(kind, per, know=None, model=FLASH, mod=None, **kwargs):
    return (mod or oto()).estimate_overview_cost(kind, per, {} if know is None else know, model, **kwargs)


def ref_stage1_only(kind, per, know, model=FLASH, per_call=2500):
    """仕様の Stage1 だけの見積り (a7b の独立した参照計算の Stage1 部分)。"""
    s1_n, s1_c, _s2_n, _s2_c = a7b.ref_counts(kind, per, know or {})
    out = oto().estimate_ai_cost_yen_multi([{"input_chars": s1_c, "n_calls": s1_n, "output_tokens_per_call": per_call,
                                             "model": model}])
    out.update(n_calls_s1=s1_n, n_calls_s2=0, input_chars=s1_c)
    return out


def mixed_input(kind):
    """キャッシュ・ルール・経緯・役割が混在する入力 (A は1スレッド2通。c0 は解析済みで省略・c1 は件数違い・c2 は前回失敗)。"""
    a7b.put_cache(kind, "A", {"c0": (2, False), "c1": (3, False), "c2": (2, True)}, rules=["x"])
    k = {"projects": {"A": {"ai_correction_rules": ["x"], "master_history": "m" * 123}, "B": {}, "C": {}},
         "staffs": {"A": {"ai_correction_rules": ["x"], "master_history": "h" * 50, "role": "r" * 7, "background": "b" * 9}}}
    per = {"A": a7b.threads_of(4, "y" * 1000, "z"), "B": a7b.threads_of(2, "w" * 300, prefix="b"), "E": {}, "F": None}
    return per, k


KEYS_COMPARED = ("input_tokens", "output_tokens", "yen", "needs_confirm", "price_known", "n_calls", "n_calls_s1",
                 "n_calls_s2", "input_chars")


class TestEstimateIncludeStage2(InTempCwd):
    def test_signature(self):
        """estimate_overview_cost(kind, per_target_threads, knowledge, model=None, include_stage2=True)。"""
        p = list(inspect.signature(oto().estimate_overview_cost).parameters.values())
        self.assertEqual([x.name for x in p], ["kind", "per_target_threads", "knowledge", "model", "include_stage2"])
        self.assertIsNone(p[3].default)
        self.assertIs(p[4].default, True)

    def test_false_counts_only_stage1(self):
        """False: n_calls_s2=0・Stage2 の字数0。Stage1 の回数・字数・費用は仕様の式 (参照計算) どおり。実績なし → 2500/回。"""
        for kind in KINDS:
            with self.subTest(kind=kind), chdir(kind):
                per, k = mixed_input(kind)
                r = est(kind, per, k, include_stage2=False)
                ref = ref_stage1_only(kind, per, k)
                self.assertEqual(r["n_calls_s1"], 3 + 2, "前提: A は c1(件数違い)・c2(失敗)・c3、B は2件")
                for key in KEYS_COMPARED:
                    self.assertEqual(r[key], ref[key], key)
                self.assertEqual(r["n_calls"], r["n_calls_s1"])
                self.assertEqual(r["output_tokens"], 5 * 2500)
                self.assertTrue(a7b.RETURN_KEYS <= set(r), set(r))

    def test_false_stage1_part_is_the_same_as_true(self):
        """False と True で Stage1 の回数・字数は同じ (True の input_chars から Stage2 の字数を引いたもの)。"""
        for kind in KINDS:
            with self.subTest(kind=kind), chdir(kind):
                per, k = mixed_input(kind)
                t, f = est(kind, per, k, include_stage2=True), est(kind, per, k, include_stage2=False)
                s2_c = a7b.ref_counts(kind, per, k)[3]
                self.assertGreater(t["n_calls_s2"], 0)
                self.assertEqual(f["n_calls_s1"], t["n_calls_s1"])
                self.assertEqual(f["input_chars"], t["input_chars"] - s2_c)
                self.assertLess(f["yen"], t["yen"])

    def test_false_with_everything_cached_is_zero(self):
        """全件解析済みなら False は0回・0字・0円 (True は Stage2 を上限の1回数える)。"""
        for kind in KINDS:
            with self.subTest(kind=kind), chdir(kind):
                a7b.put_cache(kind, "A", {"c0": (1, False)})
                f = est(kind, {"A": a7b.threads_of(1)}, include_stage2=False)
                self.assertEqual((f["n_calls"], f["n_calls_s1"], f["n_calls_s2"], f["input_chars"], f["yen"]), (0, 0, 0, 0, 0))
                self.assertFalse(f["needs_confirm"])
                self.assertEqual(est(kind, {"A": a7b.threads_of(1)})["n_calls_s2"], 1)

    def per_call(self, kind, **kwargs):
        r = est(kind, {"P": a7b.threads_of(2)}, include_stage2=False, **kwargs)
        self.assertEqual(r["n_calls"], 2)
        return r["output_tokens"] / 2

    def test_output_prefers_the_s1_log(self):
        """出力: 実績 "{kind}_s1" があればそれを優先 (×1.5)。kind の実績があっても使わない。"""
        for kind in KINDS:
            with self.subTest(kind=kind), chdir(kind):
                write_log(rec(kind, 2, 20000), rec(f"{kind}_s1", 4, 8000))       # kind: 10000/回、_s1: 2000/回
                self.assertEqual(self.per_call(kind), 3000)

    def test_output_falls_back_to_the_kind_log(self):
        """"{kind}_s1" が無ければ、従来どおり kind の実績 (×1.5)。"""
        for kind in KINDS:
            with self.subTest(kind=kind), chdir(kind):
                write_log(rec(kind, 2, 20000))
                self.assertEqual(self.per_call(kind), 15000)

    def test_output_default_without_logs(self):
        """どちらも無ければ Stage1 の既定値 2500。"""
        for kind in KINDS:
            with self.subTest(kind=kind), chdir(kind):
                self.assertEqual(self.per_call(kind), 2500)

    def test_floor_is_half_the_stage1_default(self):
        """下限はどちらの実績でも Stage1 の既定値の半分 1250 (Stage2 の下限 3000 ではない)。"""
        for kind in KINDS:
            for feature in (f"{kind}_s1", kind):
                with self.subTest(kind=kind, feature=feature), chdir(f"{kind}_{feature}"):
                    write_log(rec(feature, 1, 100))                      # 100×1.5 = 150 → 1250
                    self.assertEqual(self.per_call(kind), 1250)
        with chdir("boundary"):
            write_log(rec("project_s1", 3, 2500))                       # 833.3×1.5 = 1250 ちょうど
            self.assertAlmostEqual(self.per_call("project"), 1250, places=6)

    def test_s1_log_uses_the_usual_recent_average(self):
        """"{kind}_s1" の実績は、ほかの実績と同じ直近の平均 (observed_output_tokens_per_call。直近5件) × 1.5。"""
        for kind in KINDS:
            with self.subTest(kind=kind), chdir(kind):
                write_log(*[rec(f"{kind}_s1", n, n * out) for n, out in ((1, 90000), (2, 1000), (3, 2000), (1, 4000),
                                                                           (2, 3000), (5, 2500))])
                obs = oto().observed_output_tokens_per_call(f"{kind}_s1")
                self.assertAlmostEqual(obs, 30500 / 13, places=6, msg="前提: 直近5件の平均 (最初の 90000 は入らない)")
                r = est(kind, {"P": a7b.threads_of(2)}, include_stage2=False)
                self.assertEqual(r["output_tokens"], int(max(obs * 1.5, 1250) * 2))

    def test_other_features_are_not_used(self):
        """別の対象の実績 (staff_s1 / project_s1 の逆・cockpit_summary・action など) は使わない。"""
        for kind in KINDS:
            other = "staff" if kind == "project" else "project"
            with self.subTest(kind=kind), chdir(kind):
                write_log(rec(f"{other}_s1", 1, 50000), rec(other, 1, 50000), rec("cockpit_summary", 1, 50000),
                          rec("action", 1, 50000), rec(f"{kind}_s2", 1, 50000), rec("s1", 1, 50000),
                          rec(f"{kind}_S1", 1, 50000), rec(f"{kind}_s1 ", 1, 50000))
                self.assertEqual(self.per_call(kind), 2500)

    def test_true_is_the_same_as_13_and_ignores_s1_logs(self):
        """True (既定・明示) は _13 と全キーが同じ。"{kind}_s1" の実績があっても読まない。"""
        old = old_mod(self)
        logs = ((), (rec("project_s1", 1, 90000), rec("staff_s1", 1, 90000)),
                (rec("project", 2, 9000), rec("staff", 3, 30000), rec("project_s1", 1, 100), rec("staff_s1", 1, 100)))
        for kind in KINDS:
            for i, log in enumerate(logs):
                with self.subTest(kind=kind, log=i), chdir(f"{kind}_{i}"):
                    if log:
                        write_log(*log)
                    per, k = mixed_input(kind)
                    want = est(kind, per, k, mod=old)
                    self.assertEqual(est(kind, per, k), want)
                    self.assertEqual(est(kind, per, k, include_stage2=True), want)

    def test_true_matches_13_on_random_inputs(self):
        """乱数 (固定シード) の入力 200 件で、True (既定) は _13 と全キーが同じ。False は Stage1 部分の参照計算どおりで n_calls_s2=0。"""
        old = old_mod(self)
        rng = random.Random(7)
        for case in range(200):
            with chdir(f"r{case}"):
                kind = rng.choice(KINDS)
                per, k = {}, {"projects": {f"P{i}": {} for i in range(rng.randint(0, 4))}, "staffs": {}}
                for t in range(rng.randint(0, 3)):
                    name = rng.choice(["A", "B", "Yuto Oi", "R&D (JP)"]) + str(t)
                    threads = {}
                    for c in range(rng.randint(0, 4)):
                        bodies = ["本" * rng.choice((0, 10, 799, 800, 801, 5000)) for _ in range(rng.randint(1, 4))]
                        threads[f"{name}-{c}"] = a7b.thread(*bodies, sender=rng.choice(("Ochi", "Yamamoto, Taro (NJ)", "")),
                                                            cid=f"{name}-{c}")
                    per[name] = threads
                    sec = "projects" if kind == "project" else "staffs"
                    rules = rng.choice(([], ["r1"], ["ルール" * 3, "x"]))
                    k[sec][name] = {"ai_correction_rules": rules, "master_history": "経緯" * rng.randint(0, 50),
                                    "role": "役" * rng.randint(0, 5), "background": "背" * rng.randint(0, 5)}
                    if threads and rng.random() < 0.5:
                        entries = {cid: (len(th["mails"]) if rng.random() < 0.7 else 99, rng.random() < 0.2)
                                   for cid, th in threads.items() if rng.random() < 0.7}
                        a7b.put_cache(kind, name, entries, rules=rules if rng.random() < 0.8 else ["別"])
                feats = [f for f in ("project", "staff", "project_s1", "staff_s1") if rng.random() < 0.4]
                if feats:
                    write_log(*[rec(f, rng.randint(1, 5), rng.randint(0, 40000)) for f in feats])
                model = rng.choice((FLASH, "gemini-2.5-pro", None))
                with self.subTest(case=case, kind=kind):
                    self.assertEqual(est(kind, per, k, model), est(kind, per, k, model, mod=old))
                    f = est(kind, per, k, model, include_stage2=False)
                    s1_n, s1_c, _s2n, _s2c = a7b.ref_counts(kind, per, k)
                    self.assertEqual((f["n_calls"], f["n_calls_s1"], f["n_calls_s2"], f["input_chars"]), (s1_n, s1_n, 0, s1_c))

    def test_false_malformed_inputs_do_not_raise(self):
        """False でも、形の違う入力で例外を出さない (n_calls_s2 は常に0)。"""
        for per in (None, [], "x", 1, {}, {"A": None}, {1: {"c": {}}}, {"A": {"c": None}}, {"A": {"c": {"mails": None}}},
                    {"A": {"c": {"mails": "abc"}}}, {"A": {"c": {"no_mails": 1}}}):
            for k in (None, [], {"projects": None, "staffs": None}, {"projects": {"A": None}}, {"staffs": {"A": []}}):
                for kind in KINDS:
                    with self.subTest(per=per, knowledge=k, kind=kind):
                        r = oto().estimate_overview_cost(kind, per, k, FLASH, include_stage2=False)
                        self.assertTrue(a7b.RETURN_KEYS <= set(r))
                        self.assertEqual(r["n_calls_s2"], 0)

    def test_false_does_not_write_files_or_modify_inputs(self):
        """False でも入力を書き換えず、ファイルも作らない。"""
        per, k = mixed_input("project")
        write_log(rec("project_s1", 1, 1000))
        before_files, before = snapshot_files("."), copy.deepcopy((per, k))
        est("project", per, k, include_stage2=False)
        est("staff", per, k, include_stage2=False)
        self.assertEqual((per, k), before)
        self.assertEqual(snapshot_files("."), before_files)


class TestSpecGapCalibratedWithoutStage2(InTempCwd):
    """(SpecGap) include_stage2=False の calibrated。仕様に明記は無いが、従来どおり「実績を使ったら真」と解釈する
    ("{kind}_s1" か kind のどちらかの実績を使えば真、どちらも無ければ偽)。"""

    def test_calibrated(self):
        for kind in KINDS:
            for label, log in (("none", ()), ("s1", (rec(f"{kind}_s1", 1, 1000),)), ("kind", (rec(kind, 1, 1000),))):
                with self.subTest(kind=kind, log=label), chdir(f"{kind}_{label}"):
                    if log:
                        write_log(*log)
                    r = est(kind, {"P": a7b.threads_of(1)}, include_stage2=False)
                    self.assertIs(r["calibrated"], label != "none")

    def test_sync_estimate_is_calibrated_by_s1_logs(self):
        """同期の見積りは "project_s1" / "staff_s1" / "cockpit_summary" の実績がそろえば calibrated (段ごとに実績を使う)。"""
        pt, st = {"P1": a7b.threads_of(2)}, {"S1": a7b.threads_of(1, prefix="s")}
        m = oto()
        write_log(rec("cockpit_summary", 4, 8000))
        self.assertFalse(m.estimate_cockpit_sync_cost(pt, st, {}, FLASH)["calibrated"])
        write_log(rec("cockpit_summary", 4, 8000), rec("project_s1", 2, 3000), rec("staff_s1", 1, 1000))
        self.assertTrue(m.estimate_cockpit_sync_cost(pt, st, {}, FLASH)["calibrated"])


# ============================================================
# 3. estimate_cockpit_sync_cost
# ============================================================
def sync_input():
    know = {"projects": {"P1": {"master_history": "経緯" * 10, "ai_correction_rules": ["ルールA"]}, "P2": {}},
            "staffs": {"S1": {"role": "役割", "background": "背景"}, "S2": {}}}
    pt = {"P1": a7b.threads_of(2, "本" * 500), "P2": a7b.threads_of(3, prefix="q")}
    st = {"S1": a7b.threads_of(1, prefix="s"), "S2": a7b.threads_of(2, prefix="t")}
    return pt, st, know


class TestCockpitSyncEstimate(InTempCwd):
    def test_project_and_staff_parts_are_stage1_only(self):
        """段の dict: project / staff は estimate_overview_cost(..., include_stage2=False) の結果 (n_calls_s2=0)。"""
        m = oto()
        pt, st, know = sync_input()
        e = m.estimate_cockpit_sync_cost(pt, st, know, FLASH)
        self.assertEqual(e["project"], est("project", pt, know, include_stage2=False))
        self.assertEqual(e["staff"], est("staff", st, know, include_stage2=False))
        self.assertEqual((e["project"]["n_calls_s2"], e["staff"]["n_calls_s2"]), (0, 0))

    def test_totals_are_stage1_plus_the_final_four(self):
        """合計: 回数 = Stage1 (project + staff) + 決勝戦4。円は段の合計 (小数2桁)。トークンも合計。"""
        m = oto()
        pt, st, know = sync_input()
        e = m.estimate_cockpit_sync_cost(pt, st, know, FLASH)
        p, s, sm = e["project"], e["staff"], e["summary"]
        self.assertEqual(e["n_calls"], 2 + 3 + 1 + 2 + 4)
        self.assertEqual(e["n_calls"], p["n_calls_s1"] + s["n_calls_s1"] + 4)
        self.assertEqual(e["yen"], round(p["yen"] + s["yen"] + sm["yen"], 2))
        self.assertEqual(e["input_tokens"], p["input_tokens"] + s["input_tokens"] + sm["input_tokens"])
        self.assertEqual(e["output_tokens"], p["output_tokens"] + s["output_tokens"] + sm["output_tokens"])
        self.assertEqual(e["needs_confirm"], e["yen"] >= 100)

    def test_relation_to_13(self):
        """_13 と比べて、回数は Stage2 の回数 (対象の数) だけ少なく、円も安い。決勝戦の段は同じ。"""
        old = old_mod(self)
        pt, st, know = sync_input()
        for log in ((), (rec("cockpit_summary", 4, 8000),)):
            with self.subTest(log=bool(log)):
                if log:
                    write_log(*log)
                new_e = oto().estimate_cockpit_sync_cost(pt, st, know, FLASH)
                old_e = old.estimate_cockpit_sync_cost(pt, st, know, FLASH)
                self.assertEqual(old_e["n_calls"] - new_e["n_calls"],
                                 old_e["project"]["n_calls_s2"] + old_e["staff"]["n_calls_s2"])
                self.assertEqual(old_e["project"]["n_calls_s2"] + old_e["staff"]["n_calls_s2"], 4)
                self.assertLess(new_e["yen"], old_e["yen"])
                self.assertEqual(new_e["summary"], old_e["summary"])

    def test_uses_the_s1_logs(self):
        """プロジェクトは "project_s1"、スタッフは "staff_s1" の実績を優先する (無ければ "project" / "staff")。"""
        pt, st, know = sync_input()
        write_log(rec("project", 1, 10000), rec("project_s1", 1, 1000), rec("staff", 1, 4000))
        e = oto().estimate_cockpit_sync_cost(pt, st, know, FLASH)
        self.assertEqual(e["project"]["output_tokens"], 5 * 1500)
        self.assertEqual(e["staff"]["output_tokens"], 3 * 6000)

    def test_actual_calls_of_a_stage1_only_run_match_the_estimate(self):
        """本物の summarize_*(stage1_only=True) と generate_cockpit_summary を偽AIで動かすと、実際の回数は見積りと同じ
        (Stage1 の回数・決勝戦4回・Stage2 0回)。Stage1 のプロンプトの字数の合計は Stage1 の見積り以下。"""
        m = oto()
        pt, st, know = sync_input()
        rules_h = hashlib.md5("- ルールA".encode("utf-8")).hexdigest()
        write_json(os.path.join("analysis_cache", "project_P1.json"), {"rules_hash": rules_h, "threads": {
            "c0": {"mail_count": 1, "latest_entry_id": "", "data": s1_data("c0")}}})
        e = m.estimate_cockpit_sync_cost(pt, st, know, FLASH)
        ai = FakeAI(m)
        for name, threads in pt.items():
            ai.s.summarize_project_threads(name, copy.deepcopy(threads), know, stage1_only=True)
        for name, threads in st.items():
            ai.s.summarize_staff_threads(name, copy.deepcopy(threads), know, stage1_only=True)
        ai.s.generate_cockpit_summary()
        self.assertEqual(e["project"]["n_calls_s1"], 4, "前提: P1 の c0 は解析済み")
        self.assertEqual(ai.n("s1"), e["project"]["n_calls_s1"] + e["staff"]["n_calls_s1"])
        self.assertEqual((ai.n("s2"), ai.n("summary")), (0, 4))
        self.assertEqual(ai.n(), e["n_calls"])
        s1_chars = sum(len(p) for st_, p, _m in ai.calls if st_ == "s1")
        self.assertLessEqual(s1_chars, e["project"]["input_chars"] + e["staff"]["input_chars"])


# ============================================================
# 4. 全自動同期 (_sync_and_refresh_cockpit)
# ============================================================
_MSEQ = [0]


def smail(cid, sender="Sato, Taro", body="本文です。" * 20):
    _MSEQ[0] += 1
    n = _MSEQ[0]
    return {"subject": f"件名 {cid}", "sender_name": sender, "sender_email": "x@example.com",
            "received": datetime(2026, 10, 1, 9, 0) + timedelta(minutes=n), "body": body, "html_body": "",
            "inline_images": {}, "attachment_names": [], "conversation_id": cid, "conversation_topic": f"件名 {cid}",
            "entry_id": f"E-{cid}-{n}", "importance": 1, "folder": "受信トレイ", "has_attachments": False,
            "unread": False, "categories": "", "flag_status": 0, "routing": "to_me", "to_emails": [], "cc_emails": []}


def sync_world():
    """同期の入力。P1: p1a(2通)・p1b(解析済み) / P2: p2a / Nakai: n1・n2(2通) / Saji: s1。
    Stage1 は p1a・p2a・n1・n2・s1 の5回。_13 の Stage2 は P1・P2・Nakai・Saji の4回。決勝戦は4回。"""
    proj = {"P1": [smail("p1a"), smail("p1a"), smail("p1b")], "P2": [smail("p2a")]}
    staff = {"Nakai": [smail("n1", "Nakai, Ken"), smail("n2", "Nakai, Ken"), smail("n2", "Sato, Taro")],
             "Saji": [smail("s1", "Saji, Jiro")]}
    know = {"projects": {"P1": {"ai_correction_rules": ["ルールA"], "master_history": "経緯P1"}, "P2": {}},
            "staffs": {"Nakai": {"role": "PM", "background": "背景"}, "Saji": {}}}
    return proj, staff, know


def put_world_files(know):
    write_json(KNOWLEDGE_PATH, know)
    rules_h = hashlib.md5("- ルールA".encode("utf-8")).hexdigest()
    write_json(os.path.join("analysis_cache", "project_P1.json"), {"rules_hash": rules_h, "threads": {
        "p1b": {"mail_count": 1, "latest_entry_id": "", "data": s1_data("p1b")}}})


class SyncOutlook(a1gui.StubOutlook):
    """Outlook の代わり (プロジェクト: get_project_mails / スタッフ: search_mails_fast)。group_by_thread は本物。"""

    def __init__(self, mod, proj_mails, staff_mails):
        super().__init__()
        self.mod = mod
        self.proj_mails, self.staff_mails = proj_mails, staff_mails

    def get_project_mails(self, proj, days, include_sent=False):
        return copy.deepcopy(self.proj_mails.get(proj, []))

    def search_mails_fast(self, conditions, logic="AND", *args, **kwargs):
        if conditions.get("sender"):
            return copy.deepcopy(self.staff_mails.get(conditions["sender"], []))
        return []

    def group_by_thread(self, mails):
        return self.mod.OutlookMailManager.group_by_thread(None, mails)


COST_LINE = re.compile(r"💰 APIコスト概算: 約 ([0-9.]+) 円 \(In:(\d+) / Out:(\d+)\)")


def normalize_html(text):
    text = COST_LINE.sub("💰COST", text)
    return re.sub(r"\d{4}/\d{2}/\d{2} \d{2}:\d{2}", "DATE", text)


class SyncCase(a1gui.GuiCase):
    """本物の _sync_and_refresh_cockpit (対象の版と _13) を、偽Outlook・本物の MailSummarizer (AI の応答だけ偽物)・
    本物の HTMLReportGenerator で動かす。GC は実行中止める (ワーカー上で Tk オブジェクトが解放されて落ちるのを避ける)。"""

    def setUp(self):
        gc.disable()
        self.addCleanup(gc.enable)
        self.addCleanup(gc.collect)
        self.opened = []
        p = mock.patch("webbrowser.open", lambda url, *a, **k: (self.opened.append(url), True)[1])
        p.start()
        self.addCleanup(p.stop)
        super().setUp()

    def sync_gui(self, mod, fail_cids=()):
        """mod の MailManagerGUI を作る (Tk の部品は共通)。戻り値 (gui, ai, summarize の呼び出し記録, ステータスの記録)。"""
        if self.gui is None:
            base = self.make_gui(select_action=False, build_panel=False)
            base.config = dict(oto().DEFAULT_CONFIG)
            base.config["gemini_model"] = FLASH
            base.cockpit_widgets = {}
            for key in ("pm", "site"):
                frame = a1gui.ttk.Frame(base.root)
                frame.pack()
                base.cockpit_widgets[key] = frame
            for name in ("btn_sync_cockpit", "btn_refresh_cockpit", "btn_reformat_cockpit"):
                setattr(base, name, a1gui.ttk.Button(base.root, text=name))
            base.root.update()
        base = self.gui
        gui = mod.MailManagerGUI.__new__(mod.MailManagerGUI)
        gui.__dict__.update({k: v for k, v in base.__dict__.items()})
        proj, staff, _know = self.world
        gui.outlook = SyncOutlook(mod, proj, staff)
        ai = FakeAI(mod, FLASH, fail_cids)
        gui.summarizer = ai.s
        gui.reporter = mod.HTMLReportGenerator(os.path.join(os.getcwd(), "out"), 0)
        calls, statuses = [], []
        for meth in ("summarize_project_threads", "summarize_staff_threads"):
            real = getattr(ai.s, meth)

            def spy(*args, _real=real, _meth=meth, **kwargs):
                calls.append((_meth, args[0], kwargs.get("stage1_only", "<無し>")))
                return _real(*args, **kwargs)
            setattr(ai.s, meth, spy)
        real_status = gui._set_status

        def status_spy(text, *a, **k):
            statuses.append(str(text))
            return real_status(text, *a, **k)
        gui._set_status = status_spy
        return gui, ai, calls, statuses

    def run_sync(self, gui):
        before = set(self.worker_threads())
        gui._sync_and_refresh_cockpit()
        started = [t for t in self.worker_threads() if t not in before]
        self.assertEqual(len(started), 1, "ワーカースレッドが1つ起動していない")
        self.assertTrue(self.pump(lambda: not started[0].is_alive(), timeout=FLOW_TIMEOUT), "同期が終わらない")
        self.settle(0.1)
        return str(gui.lbl_stat.cget("text"))

    def run_in(self, sub, mod, fail_cids=()):
        """sub フォルダで mod の同期を1回動かし、観察結果をまとめて返す。"""
        with chdir(sub) as here:
            put_world_files(self.world[2])
            n_opened = len(self.opened)
            gui, ai, calls, statuses = self.sync_gui(mod, fail_cids)
            status = self.run_sync(gui)
            html_paths = self.opened[n_opened:]
            html = None
            if html_paths:
                with open(html_paths[-1], encoding="utf-8") as f:
                    html = f.read()
            with open(LAST_RESULT_PATH, encoding="utf-8") as f:
                last = json.load(f)
            with open(KNOWLEDGE_PATH, encoding="utf-8") as f:
                knowledge = json.load(f)
            return {"dir": here, "gui": gui, "ai": ai, "calls": calls, "statuses": statuses, "status": status,
                    "log": usage_log(), "caches": load_json_tree("analysis_cache"), "last": last,
                    "knowledge": knowledge, "html": html, "errors": [d for d in self.dialogs if d[0] == "showerror"]}

    def assert_status(self, text, head, tail, n_calls):
        m = re.fullmatch(re.escape(head) + r"（今回のAI費用 約([0-9.]+)円・" + re.escape(tail) + r"）", text)
        self.assertIsNotNone(m, f"完了表示の形が違う: {text!r}")
        spent = oto().calc_api_cost_yen(n_calls * CALL_IN, n_calls * CALL_OUT, FLASH)
        self.assertIn(float(m.group(1)), {round(spent, 1), round(spent, 2), round(spent)}, text)


def summary_ids(ai):
    """決勝戦の呼び出しごとの (View, 候補の ID の並び替えた一覧)。(候補の並び順は解析の終わった順で変わり得るため、集合で比べる)"""
    out = []
    for stage, prompt, _model in ai.calls:
        if stage == "summary":
            view = re.search(r"【対象View】(\w+)", prompt)
            out.append((view.group(1) if view else "?", tuple(sorted(re.findall(r"\[ID: ([^\]]+)\]", prompt)))))
    return sorted(out)


def log_rows(log):
    return [(r["feature"], r["n_calls"], r["input_tokens"], r["output_tokens"]) for r in log]


def row(feature, ok, burned):
    return (feature, ok, burned * CALL_IN, burned * CALL_OUT)


class TestSyncStage1Only(SyncCase):
    def setUp(self):
        super().setUp()
        self.world = sync_world()

    def test_sync_passes_stage1_only_and_counts_stage1_plus_final(self):
        """同期: summarize_* に stage1_only=True が渡り、Stage2 の AI 呼び出しは0回。完了表示の件数は Stage1 (5) + 決勝戦 (4) = 9。
        実績ログは "project_s1" (2回) / "staff_s1" (3回) / "cockpit_summary" (4回)、トークンは段の増分。"""
        r = self.run_in("r14", oto())
        self.assertEqual(r["errors"], [])
        self.assertEqual(sorted(r["calls"]), sorted([("summarize_project_threads", "P1", True),
                                                     ("summarize_project_threads", "P2", True),
                                                     ("summarize_staff_threads", "Nakai", True),
                                                     ("summarize_staff_threads", "Saji", True)]))
        ai = r["ai"]
        self.assertEqual((ai.n("s1"), ai.n("s2"), ai.n("summary")), (5, 0, 4))
        self.assert_status(r["status"], "✅ 全解析同期完了", "9件", 9)
        self.assertEqual(log_rows(r["log"]), [row("project_s1", 2, 2), row("staff_s1", 3, 3), row("cockpit_summary", 4, 4)])
        self.assertEqual({x["model"] for x in r["log"]}, {FLASH})
        self.assertEqual((ai.s.total_input_tokens, ai.s.total_output_tokens), (9 * CALL_IN, 9 * CALL_OUT))

    def test_outputs_are_the_same_as_13(self):
        """同じ入力で _13 の同期と比べる: 解析キャッシュ・ナレッジ・保存結果 (res / cache_dict)・HTML (費用と日時を除く) が同じ。
        違うのは費用 (トークン) だけで、_14 は Stage2 の4回分 (4×6000 / 4×3300) 少ない。"""
        old = old_mod(self)
        r13 = self.run_in("r13", old)
        r14 = self.run_in("r14", new_mod(self))
        self.assertEqual((r13["ai"].n("s2"), r14["ai"].n("s2")), (4, 0), "前提: _13 は Stage2 を4回呼んでいた")
        self.assertEqual(r13["ai"].prompts("s1"), r14["ai"].prompts("s1"))
        self.assertEqual(summary_ids(r13["ai"]), summary_ids(r14["ai"]), "決勝戦への入力 (候補のスレッド) が違う")
        self.assertEqual(r14["caches"], r13["caches"])
        self.assertEqual(sorted(r14["caches"]), ["project_P1.json", "project_P2.json", "staff_Nakai.json", "staff_Saji.json"])
        self.assertEqual(r14["knowledge"], r13["knowledge"])
        self.assertEqual(r14["last"]["res"], r13["last"]["res"])
        self.assertEqual(r14["last"]["cache_dict"], r13["last"]["cache_dict"])
        self.assertEqual((r13["last"]["total_input"], r13["last"]["total_output"]), (13 * CALL_IN, 13 * CALL_OUT))
        self.assertEqual((r14["last"]["total_input"], r14["last"]["total_output"]), (9 * CALL_IN, 9 * CALL_OUT))
        self.assertIsNotNone(r13["html"])
        self.assertIsNotNone(r14["html"])
        self.assertEqual(normalize_html(r14["html"]), normalize_html(r13["html"]))
        cost = COST_LINE.search(r14["html"])
        self.assertIsNotNone(cost)
        self.assertEqual((int(cost.group(2)), int(cost.group(3))), (9 * CALL_IN, 9 * CALL_OUT))
        self.assertEqual(log_rows(r13["log"]), [row("project", 4, 4), row("staff", 5, 5), row("cockpit_summary", 4, 4)],
                         "前提: _13 の実績ログ")

    def test_failures_are_shown_and_outputs_still_match_13(self):
        """AI失敗あり (p1a・s1): 「⚠ 完了（AI失敗2件。…）（今回のAI費用 約X円・成功7/9件）」。実績ログは成功回数・段の増分。
        出力 (キャッシュ・ナレッジ・保存結果・HTML) は _13 と同じ。"""
        old = old_mod(self)
        fail = ("p1a", "s1")
        r13 = self.run_in("r13", old, fail)
        r14 = self.run_in("r14", new_mod(self), fail)
        self.assertEqual((r14["ai"].n("s1"), r14["ai"].n("s2"), r14["ai"].n("summary")), (5, 0, 4))
        self.assert_status(r14["status"], "⚠ 完了（AI失敗2件。もう一度実行すると再試行）", "成功7/9件", 9)
        self.assertEqual(log_rows(r14["log"]), [row("project_s1", 1, 2), row("staff_s1", 2, 3), row("cockpit_summary", 4, 4)])
        self.assertEqual(r14["caches"], r13["caches"])
        self.assertEqual(r14["knowledge"], r13["knowledge"])
        self.assertEqual(r14["last"]["res"], r13["last"]["res"])
        self.assertEqual(r14["last"]["cache_dict"], r13["last"]["cache_dict"])
        self.assertEqual(normalize_html(r14["html"]), normalize_html(r13["html"]))

    def test_second_sync_with_everything_analysed_is_only_the_final_four(self):
        """2回目 (全件解析済み): AI は決勝戦の4回だけ。完了表示は「4件」、実績ログに足されるのは "cockpit_summary" だけ。
        次回の見積りは "project_s1" / "staff_s1" の実績で校正される。"""
        with chdir("twice"):
            put_world_files(self.world[2])
            gui, ai, calls, _st = self.sync_gui(oto())
            self.run_sync(gui)
            first = len(ai.calls)
            status = self.run_sync(gui)
            self.assertEqual([c[0] for c in ai.calls[first:]], ["summary"] * 4)
            self.assert_status(status, "✅ 全解析同期完了", "4件", 4)
            self.assertEqual(log_rows(usage_log())[3:], [row("cockpit_summary", 4, 4)])
            self.assertTrue(all(c[2] is True for c in calls))
            m = oto()
            self.assertEqual(m.observed_output_tokens_per_call("project_s1"), CALL_OUT)
            self.assertEqual(m.observed_output_tokens_per_call("staff_s1"), CALL_OUT)
            self.assertIsNone(m.observed_output_tokens_per_call("project"))
            e = m.estimate_cockpit_sync_cost({"P9": a7b.threads_of(2, prefix="z")}, {"S9": a7b.threads_of(1, prefix="y")},
                                             {}, FLASH)
            self.assertTrue(e["calibrated"])
            self.assertEqual(e["project"]["output_tokens"], 2 * CALL_OUT * 1.5)
            self.assertEqual(e["staff"]["output_tokens"], 1 * CALL_OUT * 1.5)


class TestSpecGapSyncStatusHasNoStage2(SyncCase):
    """(SpecGap) 同期中のステータスに、行わない統合 (「Stage 2」) の表示が出ない (仕様「Stage2 に入る前に返す」の自然な解釈)。"""

    def setUp(self):
        super().setUp()
        self.world = sync_world()

    def test_no_stage2_status(self):
        r = self.run_in("r14", oto())
        self.assertTrue(any("Stage 1" in s for s in r["statuses"]), r["statuses"])
        self.assertEqual([s for s in r["statuses"] if "Stage 2" in s], [])


# ============================================================
# 5. 俯瞰2画面は従来どおり (Stage2 を呼び、"project" / "staff" に記録)
# ============================================================
class OverviewStillUsesStage2(a7b.OverviewCase):
    """a7b の俯瞰の画面ハーネスで、summarizer を本物の MailSummarizer (AI の応答だけ偽物) に差し替えて動かす。
    見積りの呼び出しは、同じ引数・同じ時点で _13 の estimate_overview_cost とも比べる。"""

    def run_real(self, kind, targets, mails, log=None):
        old = old_mod(self)
        gui = self.build(kind, targets, mails, log=log)
        self.ai = FakeAI(oto(), FLASH)
        gui.summarizer = self.ai.s
        self.summ_calls = []
        for meth in ("summarize_project_threads", "summarize_staff_threads"):
            real = getattr(self.ai.s, meth)

            def spy(*args, _real=real, _meth=meth, **kwargs):
                self.summ_calls.append((_meth, args[0], kwargs.get("stage1_only", "<無し>")))
                return _real(*args, **kwargs)
            setattr(self.ai.s, meth, spy)
        self.est_pairs = []
        current = oto().estimate_overview_cost

        def compare(*args, **kwargs):
            got = current(*args, **kwargs)
            self.est_pairs.append((got, old.estimate_overview_cost(*args, **kwargs), dict(kwargs)))
            return got
        p = mock.patch.object(oto(), "estimate_overview_cost", compare)
        p.start()
        self.addCleanup(p.stop)
        fn = gui._run_project_overview if kind == "project" else gui._run_staff_overview
        with contextlib.redirect_stdout(self.printed):
            gui.root.after(0, fn)
            ok = self.pump(lambda: any(t.startswith(a7b.FINAL_PREFIXES) for t, _ in self.statuses), timeout=FLOW_TIMEOUT)
            self.pump(lambda: not self.worker_threads(), timeout=10)
            self.settle(0.05)
        self.gui = gui
        self.assertTrue(ok, f"最終ステータスに到達しない: {self.statuses[-4:]}")
        return gui

    def check(self, kind, targets, meth):
        mails = {t: a7b.pmails(t, 2) for t in targets}
        log = [rec(f"{kind}_s1", 1, 90000)]                 # 同期の実績があっても、俯瞰の見積りは読まない
        self.run_real(kind, targets, mails, log=log)
        self.assertEqual([c for c in self.summ_calls if c[0] != meth], [])
        self.assertEqual(sorted(c[1] for c in self.summ_calls), sorted(targets))
        self.assertTrue(all(c[2] in ("<無し>", False) for c in self.summ_calls), self.summ_calls)
        self.assertEqual((self.ai.n("s1"), self.ai.n("s2")), (2 * len(targets), len(targets)), "Stage2 が呼ばれていない")
        self.assertEqual(len(self.est_pairs), 1)
        got, want, kwargs = self.est_pairs[0]
        self.assertNotIn("include_stage2", kwargs)
        self.assertEqual(got, want, "俯瞰の見積りが _13 と違う")
        n = 3 * len(targets)
        recs = [r for r in a7b.read_log_records() if r["feature"] != f"{kind}_s1"]
        self.assertEqual([(r["feature"], r["n_calls"], r["input_tokens"], r["output_tokens"]) for r in recs],
                         [(kind, n, n * CALL_IN, n * CALL_OUT)])
        final = self.final()
        self.assertTrue(final.startswith("✅ 完了（今回のAI費用 約"), final)
        self.assertTrue(final.endswith(f"円・{n}件）"), final)
        with open(a7b.KNOWLEDGE_PATH, encoding="utf-8") as f:
            know = json.load(f)
        section = "projects" if kind == "project" else "staffs"
        for t in targets:
            self.assertIn("統合の経緯", know[section][t].get("history_summary", ""), t)

    def test_project_overview(self):
        """プロジェクト俯瞰: stage1_only を渡さず Stage2 を対象ごとに呼ぶ。実績ログは "project" (Stage1+Stage2)。"""
        self.kind = "project"
        self.check("project", a7b.PROJECTS[:2], "summarize_project_threads")

    def test_staff_overview(self):
        """スタッフ俯瞰: stage1_only を渡さず Stage2 を対象ごとに呼ぶ。実績ログは "staff" (Stage1+Stage2)。"""
        self.kind = "staff"
        self.check("staff", ("Nakai", "Saji"), "summarize_staff_threads")


# ============================================================
# 6. 範囲ガード (AST・_13 → _14)
# ============================================================
ALLOWED_TO_CHANGE = {"estimate_overview_cost", "estimate_cockpit_sync_cost", "MailSummarizer.summarize_project_threads",
                     "MailSummarizer.summarize_staff_threads", "MailManagerGUI._sync_and_refresh_cockpit"}
MUST_STAY_UNCHANGED = ["MailManagerGUI._run_project_overview", "MailManagerGUI._run_staff_overview",
                       "MailSummarizer.generate_cockpit_summary", "HTMLReportGenerator.generate_cockpit_report",
                       "MailManagerGUI._refresh_cockpit", "MailManagerGUI._finish_cockpit_status",
                       "MailManagerGUI._confirm_ai_cost", "count_overview_stage2_calls", "count_failed_overview_threads",
                       "observed_output_tokens_per_call", "record_ai_usage", "save_project_knowledge",
                       "load_project_knowledge", "estimate_ai_cost_yen_multi", "MailSummarizer._run_genai_call_with_schema",
                       "MailManagerGUI._filter_threads_loose"]
SUMMARIZE = ("MailSummarizer.summarize_project_threads", "MailSummarizer.summarize_staff_threads")
SYNC = "MailManagerGUI._sync_and_refresh_cockpit"


def _is_name(node, name):
    return isinstance(node, ast.Name) and node.id == name


def _is_stage1_only_return(node):
    return (isinstance(node, ast.If) and _is_name(node.test, "stage1_only") and not node.orelse and len(node.body) == 1
            and isinstance(node.body[0], ast.Return) and _is_name(node.body[0].value, "merged_result"))


def _without_docstring(fn):
    fn = copy.deepcopy(fn)
    if fn.body and isinstance(fn.body[0], ast.Expr) and isinstance(getattr(fn.body[0], "value", None), ast.Constant) \
            and isinstance(fn.body[0].value.value, str):
        fn.body = fn.body[1:]
    return fn


class TestScopeGuardA7e(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.target = os.path.join(_loader.TOOL_DIR, NEW_REV)
        cls.baseline = os.path.join(_loader.TOOL_DIR, OLD_REV)
        if not (os.path.isfile(cls.target) and os.path.isfile(cls.baseline)):
            raise unittest.SkipTest(f"A7e のリビジョン対({OLD_REV} / {NEW_REV})が無い")
        cls.old = a7a._index_source(cls.baseline)
        cls.new = a7a._index_source(cls.target)

    def test_nothing_added_or_removed(self):
        """関数・メソッド・定数の追加/削除なし (追加の名前は無し)。定数・import・その他の文・クラスの骨格は不変。"""
        self.assertEqual(sorted(set(self.old[0]) ^ set(self.new[0])), [])
        self.assertEqual(sorted(set(self.old[1]) ^ set(self.new[1])), [])
        self.assertEqual(sorted(n for n, s in self.old[1].items() if self.new[1].get(n) != s), [])
        self.assertEqual(self.old[2], self.new[2])
        self.assertEqual(self.old[3], self.new[3])
        self.assertEqual(self.old[4], self.new[4])

    def test_only_allowed_functions_changed(self):
        """変わった既存の関数は estimate_overview_cost・estimate_cockpit_sync_cost・summarize_project_threads・
        summarize_staff_threads・_sync_and_refresh_cockpit だけ (どれも実際に変わっている)。"""
        changed = {n for n, s in self.old[0].items() if n in self.new[0] and self.new[0][n] != s}
        self.assertEqual(sorted(changed), sorted(ALLOWED_TO_CHANGE))

    def test_overviews_final_and_report_unchanged(self):
        """俯瞰2画面・決勝戦・HTML・キャッシュの数え方・実績ログ・ナレッジの保存などは不変。"""
        for q in MUST_STAY_UNCHANGED:
            with self.subTest(q=q):
                self.assertIn(q, self.old[0])
                self.assertEqual(self.new[0].get(q), self.old[0][q])

    def test_summarize_changes_only_the_parameter_and_the_early_return(self):
        """summarize_* の変更は「最後の引数 stage1_only: bool = False」と「if stage1_only: return merged_result」だけ
        (両方を取り除くと _13 と同じ AST)。stage1_only はほかで使わない。"""
        for q in SUMMARIZE:
            with self.subTest(q=q):
                old_fn, new_fn = a7a.func_node(self.baseline, q), copy.deepcopy(a7a.func_node(self.target, q))
                last = new_fn.args.args[-1]
                self.assertEqual(last.arg, "stage1_only")
                self.assertEqual(ast.dump(last.annotation), ast.dump(ast.Name("bool", ast.Load())))
                self.assertEqual(ast.dump(new_fn.args.defaults[-1]), ast.dump(ast.Constant(False)))
                new_fn.args.args.pop()
                new_fn.args.defaults.pop()
                removed = [n for n in ast.walk(new_fn) if _is_stage1_only_return(n)]
                self.assertEqual(len(removed), 1, "if stage1_only: return merged_result がちょうど1つ")
                self.assertIn(removed[0], new_fn.body, "早期 return は関数の直下 (入れ子の中ではない)")
                new_fn.body.remove(removed[0])
                self.assertEqual([n for n in ast.walk(new_fn) if _is_name(n, "stage1_only")], [])
                self.assertEqual(ast.dump(new_fn), ast.dump(old_fn))

    def test_early_return_is_right_after_the_stage1_cache_block(self):
        """早期 return は「if needs_update:」(Stage1 の解析と解析キャッシュの保存) の直後・Stage2 の前に置かれている。"""
        for q in SUMMARIZE:
            with self.subTest(q=q):
                body = a7a.func_node(self.target, q).body
                idx = [i for i, n in enumerate(body) if _is_stage1_only_return(n)]
                self.assertEqual(len(idx), 1)
                prev = body[idx[0] - 1]
                self.assertTrue(isinstance(prev, ast.If) and _is_name(prev.test, "needs_update"), ast.dump(prev)[:200])
                dumps = [n for n in ast.walk(prev) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                         and n.func.attr == "dump" and _is_name(n.func.value, "json")]
                self.assertTrue(dumps and any(_is_name(c.args[0], "cache_data") for c in dumps if c.args),
                                "直前のブロックで解析キャッシュ (cache_data) を保存していない")
                later = ast.dump(ast.Module(body=body[idx[0] + 1:], type_ignores=[]))
                self.assertIn("stage2_schema", later, "Stage2 は早期 return の後")
                self.assertNotIn("stage2_schema", ast.dump(ast.Module(body=body[:idx[0]], type_ignores=[])))

    def test_sync_changes_only_stage1_only_counts_and_features(self):
        """_sync_and_refresh_cockpit の変更は、summarize_* への stage1_only=True・回数から count_overview_stage2_calls を
        外す・実績ログの feature を "project_s1" / "staff_s1" にする、の3つだけ (逆に戻すと _13 と同じ AST)。"""
        old_fn, new_fn = a7a.func_node(self.baseline, SYNC), copy.deepcopy(a7a.func_node(self.target, SYNC))
        n_kw = 0
        for node in ast.walk(new_fn):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in (
                    "summarize_project_threads", "summarize_staff_threads"):
                kws = [k for k in node.keywords if k.arg == "stage1_only"]
                self.assertEqual(len(kws), 1, f"{node.func.attr} に stage1_only が無い")
                self.assertEqual(ast.dump(kws[0].value), ast.dump(ast.Constant(True)))
                node.keywords.remove(kws[0])
                n_kw += 1
        self.assertEqual(n_kw, 2)

        class Back(ast.NodeTransformer):
            """_14 の回数・feature を _13 の形に戻す。"""
            n_feat = 0

            def visit_Constant(self, node):
                if node.value in ("project_s1", "staff_s1"):
                    Back.n_feat += 1
                    return ast.copy_location(ast.Constant(node.value[:-3]), node)
                return node
        new_fn = Back().visit(new_fn)
        self.assertEqual(Back.n_feat, 2, "feature の \"project_s1\" / \"staff_s1\" が1回ずつ")

        class Drop(ast.NodeTransformer):
            """_13 の「estimate[...]["n_calls_s1"] + count_overview_stage2_calls(...)」から後ろを外す。"""
            n = 0

            def visit_BinOp(self, node):
                self.generic_visit(node)
                if isinstance(node.op, ast.Add) and isinstance(node.right, ast.Call) and _is_name(
                        node.right.func, "count_overview_stage2_calls"):
                    Drop.n += 1
                    return node.left
                return node
        old_fn = Drop().visit(copy.deepcopy(old_fn))
        self.assertEqual(Drop.n, 2, "前提: _13 は Stage2 の回数を2か所で足していた")
        self.assertEqual(ast.dump(new_fn), ast.dump(old_fn))

    def test_cockpit_sync_cost_changes_only_include_stage2(self):
        """estimate_cockpit_sync_cost の変更は、project / staff の estimate_overview_cost に include_stage2=False を渡すことと
        docstring (理由) だけ。"""
        old_fn, new_fn = a7a.func_node(self.baseline, "estimate_cockpit_sync_cost"), copy.deepcopy(
            a7a.func_node(self.target, "estimate_cockpit_sync_cost"))
        n = 0
        for node in ast.walk(new_fn):
            if isinstance(node, ast.Call) and _is_name(node.func, "estimate_overview_cost"):
                kws = [k for k in node.keywords if k.arg == "include_stage2"]
                self.assertEqual(len(kws), 1)
                self.assertEqual(ast.dump(kws[0].value), ast.dump(ast.Constant(False)))
                node.keywords.remove(kws[0])
                n += 1
        self.assertEqual(n, 2)
        self.assertEqual(ast.dump(_without_docstring(new_fn)), ast.dump(_without_docstring(old_fn)))
        doc_new, doc_old = ast.get_docstring(new_fn), ast.get_docstring(old_fn)
        self.assertNotEqual(doc_new, doc_old, "docstring に理由が書かれていない")
        self.assertIn("Stage2", doc_new)

    def test_estimate_overview_cost_signature_only_adds_include_stage2(self):
        """estimate_overview_cost の引数は、従来の後ろに include_stage2=True が増えただけ。"""
        old_fn, new_fn = a7a.func_node(self.baseline, "estimate_overview_cost"), a7a.func_node(self.target, "estimate_overview_cost")
        self.assertEqual([a.arg for a in new_fn.args.args], [a.arg for a in old_fn.args.args] + ["include_stage2"])
        self.assertEqual([ast.dump(d) for d in new_fn.args.defaults],
                         [ast.dump(d) for d in old_fn.args.defaults] + [ast.dump(ast.Constant(True))])


if __name__ == "__main__":
    unittest.main(verbosity=2)
