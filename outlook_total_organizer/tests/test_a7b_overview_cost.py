# -*- coding: utf-8 -*-
"""A7b「プロジェクト俯瞰・スタッフ俯瞰: AI費用の事前見積り・100円以上は確認・実績ログ・失敗/中止の表示」テスト (仕様書 A7B_SPEC.md)。

仕様書だけを根拠に、実装 (_20261004_07.py の estimate_overview_cost ほかの新関数・変更後の _run_project_overview /
_run_staff_overview・_finish_overview_status) を見ずに書いている。
  - 仕様に明記された挙動            -> 通常の TestCase
  - 仕様が曖昧/未記載で「最も自然な解釈」で書いたもの -> クラス名に SpecGap を含む

構成
  1. 定数 (11個)・補助関数・estimate_overview_cost (純関数)・count_failed_overview_threads
  2. 見積り＝実際: 本物の summarize_project_threads / summarize_staff_threads を、AI 呼び出し
     (_run_genai_call_with_schema) だけ偽物にして動かし、Stage1 の回数・Stage2 の回数・プロンプトの字数と見積りを比べる
  3. 画面の流れ (偽Outlook・偽AI・ダイアログのスタブ): 取得→見積り→確認→AI の順・中止・成功・AI失敗・HTML失敗・例外
  4. 範囲ガード (_06 と _07 の AST 比較)

費用の期待値は、既存の estimate_ai_cost_yen_multi / calc_api_cost_yen (A2 で確定済み) に、このファイルの独立した
字数・回数の計算 (ref_estimate) を渡して作る。実績ログ・解析キャッシュ・ナレッジは必ず空の一時cwd の中で扱う。
GUI テストは tkinter とディスプレイが無ければ自動 skip (Linux は xvfb-run -a /usr/bin/python3.12 tests/run_tests.py)。
"""
import ast
import contextlib
import copy
import functools
import gc
import hashlib
import inspect
import io
import json
import os
import re
import threading
import types
import unittest
import webbrowser                                  # noqa: F401  (mock.patch("webbrowser.open") の対象を先に読み込む)
from datetime import datetime, timedelta
from unittest import mock

import _loader
import test_a1_gui_smoke as a1gui
from _loader import read_bytes, snapshot_files, tempdir_cwd, write_json, write_text

tk, ttk, tkmessagebox = a1gui.tk, a1gui.ttk, a1gui.tkmessagebox


def oto():
    return _loader.load()


FLASH = "gemini-2.5-flash"
LITE = "gemini-2.5-flash-lite"
PRO = "gemini-2.5-pro"
LOG_PATH = os.path.join("json", "ai_usage_log.jsonl")
KNOWLEDGE_PATH = os.path.join("json", "project_knowledge.json")

SPEC_CONSTANTS = {
    "OVERVIEW_ESTIMATE_S1_PROMPT_CHARS": 1500, "OVERVIEW_ESTIMATE_S2_PROMPT_CHARS": 1500,
    "OVERVIEW_ESTIMATE_S2_CONTENT_CHARS": 30000, "OVERVIEW_ESTIMATE_BODY_LIMIT": 800,
    "OVERVIEW_ESTIMATE_MAIL_OVERHEAD": 40, "OVERVIEW_ESTIMATE_THREAD_CHARS_MAX": 30000,
    "OVERVIEW_ESTIMATE_S1_OUTPUT_TOKENS": 2500, "OVERVIEW_ESTIMATE_S2_OUTPUT_TOKENS": 6000,
    "OVERVIEW_ESTIMATE_SAFETY": 1.5, "OVERVIEW_ESTIMATE_OUTPUT_FLOOR_RATIO": 0.5,
}                                                   # (変更点1) STAFF_STAGE1_MODEL は削除
NEW_HELPERS = ("_overview_target_know", "_overview_cache_path", "_overview_cached_threads", "_overview_rules_text")
NEW_FUNCTIONS = NEW_HELPERS + ("estimate_overview_cost", "count_failed_overview_threads", "count_overview_stage2_calls")
RETURN_KEYS = {"input_tokens", "output_tokens", "yen", "needs_confirm", "price_known", "n_calls",
               "n_calls_s1", "n_calls_s2", "input_chars", "calibrated"}


class InTempCwd(unittest.TestCase):
    """各テストを空の一時cwd で動かす (実際の実績ログ・解析キャッシュを拾わない・SB を汚さない)。"""

    def setUp(self):
        cm = tempdir_cwd()
        self.tmp = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)


# ============================================================
# 入力データの合成
# ============================================================
_SEQ = [0]


def mail(body="本文", sender="Ochi", cid="c", received=None, unread=False, **kw):
    """Outlook から取得したメール1通 (group_by_thread / summarize_* が読む項目を持つ)。"""
    _SEQ[0] += 1
    d = {"conversation_id": cid, "entry_id": f"E-{cid}-{_SEQ[0]}", "subject": f"件名{cid}",
         "conversation_topic": f"件名{cid}", "received": received or datetime(2026, 9, 20, 10, 0) + timedelta(minutes=_SEQ[0]),
         "sender_name": sender, "sender_email": "x@example.com", "importance": 1, "unread": unread,
         "routing": "to_me", "to_emails": [], "cc_emails": [], "body": body, "html_body": "", "categories": "",
         "flag_status": 0, "folder": "受信トレイ", "attachment_names": []}
    d.update(kw)
    return d


def thread(*bodies, sender="Ochi", cid="c", topic=None):
    """スレッド (group_by_thread の形の最小限: topic / mails / latest_entry_id / latest_date)。"""
    mails = [mail(b, sender=sender, cid=cid) for b in bodies]
    return {"topic": topic or f"件名{cid}", "mails": mails, "latest_entry_id": mails[-1]["entry_id"] if mails else "",
            "latest_date": mails[-1]["received"] if mails else None, "has_unread": False}


def threads_of(n, *bodies, prefix="c", sender="Ochi"):
    bodies = bodies or ("本文",)
    return {f"{prefix}{i}": thread(*bodies, sender=sender, cid=f"{prefix}{i}") for i in range(n)}


def rules_text(rules):
    return "\n".join(f"- {r}" for r in rules) or "特になし"


def rules_hash(rules=()):
    return hashlib.md5(rules_text(list(rules)).encode("utf-8")).hexdigest()


def safe_name(name):
    return "".join(c for c in name if c.isalnum() or c in " ._-")


def cache_path(kind, name):
    return os.path.join("analysis_cache", f"{kind}_{safe_name(name)}.json")


def put_cache(kind, name, entries, rules=(), raw=None):
    """解析キャッシュを置く。entries = {cid: (mail_count, _error)}。raw を渡すと、その文字列/オブジェクトをそのまま書く。"""
    path = cache_path(kind, name)
    if raw is not None:
        if isinstance(raw, (bytes, str)):
            write_text(path, raw if isinstance(raw, str) else raw.decode("utf-8", "replace"))
        else:
            write_json(path, raw)
        return path
    th = {}
    for cid, (count, err) in entries.items():
        data = {"thread_id": cid, "topic": "t", "is_target": True, "summary": "s"}
        if err:
            data.update(is_target=False, category="エラー", _error=True)
        th[cid] = {"mail_count": count, "latest_entry_id": "", "data": data}
    write_json(path, {"rules_hash": rules_hash(rules), "threads": th})
    return path


def rec(feature, n_calls=1, output_tokens=1000, input_tokens=50000, yen=1.0, model=FLASH):
    return {"at": "2026-10-04T09:00:00", "feature": feature, "n_calls": n_calls, "input_tokens": input_tokens,
            "output_tokens": output_tokens, "yen": yen, "model": model}


def write_log(*records):
    write_text(LOG_PATH, "".join((r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)) + "\n" for r in records))


def read_log_records():
    if not os.path.exists(LOG_PATH):
        return []
    return [json.loads(x) for x in read_bytes(LOG_PATH).decode("utf-8").splitlines() if x.strip()]


def section(kind):
    return "projects" if kind == "project" else "staffs"


def know_of(kind, name, rules=None, master_history="", role=None, background=None, projects=None):
    """knowledge を作る (staff は projects 一覧も持つ)。"""
    t = {}
    if rules is not None:
        t["ai_correction_rules"] = list(rules)
    if master_history:
        t["master_history"] = master_history
    if role is not None:
        t["role"] = role
    if background is not None:
        t["background"] = background
    k = {section(kind): {name: t}}
    if kind == "staff":
        k["projects"] = {p: {} for p in (projects if projects is not None else ["00_Caracal", "01_Wheeling"])}
    return k


# ============================================================
# 独立した参照計算 (仕様書の式そのまま)
# ============================================================
def _ref_know(kind, name, knowledge):
    sec = knowledge.get(section(kind)) if isinstance(knowledge, dict) else None
    t = sec.get(name) if isinstance(sec, dict) else None
    return t if isinstance(t, dict) else {}


def _ref_cached(kind, name, rt):
    try:
        with open(cache_path(kind, name), "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:                                           # noqa: BLE001
        return {}
    if not isinstance(data, dict) or data.get("rules_hash") != hashlib.md5(rt.encode("utf-8")).hexdigest():
        return {}
    th = data.get("threads")
    return th if isinstance(th, dict) else {}


def ref_counts(kind, per_target, knowledge):
    """(S1回数, S1字数, S2回数, S2字数) を仕様書の式で数える (cwd のキャッシュを読む)。"""
    s1_n = s1_c = s2_n = s2_c = 0
    projects = knowledge.get("projects") if isinstance(knowledge, dict) else None
    plist = ", ".join(projects.keys()) if isinstance(projects, dict) else ""
    for name, threads in (per_target.items() if isinstance(per_target, dict) else []):
        if not isinstance(threads, dict) or not threads:
            continue
        know = _ref_know(kind, name, knowledge)
        rules = know.get("ai_correction_rules")
        rt = rules_text(rules if isinstance(rules, list) else [])
        cached = _ref_cached(kind, name, rt)
        fixed = 1500 + len(rt) + len(name) * 2 + 100 + (len(plist) if kind == "staff" else 0)
        for cid, t in threads.items():
            mails = (t.get("mails") or []) if isinstance(t, dict) else []
            c = cached.get(cid)
            if (isinstance(c, dict) and c.get("mail_count") == len(mails) and isinstance(c.get("data"), dict)
                    and not c["data"].get("_error")):
                continue
            body = sum(min(len(str(m.get("body") or "")), 800) + 40 + len(str(m.get("sender_name") or ""))
                       for m in mails if isinstance(m, dict))                   # (変更点2) 送信者名の字数も足す
            s1_n += 1
            s1_c += min(body, 30000) + fixed
        s2_n += 1
        s2_c += 1500 + 30000 + len(str(know.get("master_history") or "")) + len(name) * 2      # (変更点3) 名前×2
        if kind == "staff":
            s2_c += len(str(know.get("role") or "")) + len(str(know.get("background") or "")) + len(plist)
    return s1_n, s1_c, s2_n, s2_c


def ref_estimate(kind, per_target, knowledge, model=FLASH, observed=None):
    s1_n, s1_c, s2_n, s2_c = ref_counts(kind, per_target, knowledge)
    o1 = max(observed * 1.5, 2500 * 0.5) if observed else 2500
    o2 = max(observed * 1.5, 6000 * 0.5) if observed else 6000
    out = oto().estimate_ai_cost_yen_multi([
        {"input_chars": s1_c, "n_calls": s1_n, "output_tokens_per_call": o1, "model": model},   # (変更点1) staff も設定モデル
        {"input_chars": s2_c, "n_calls": s2_n, "output_tokens_per_call": o2, "model": model}])
    out.update(n_calls_s1=s1_n, n_calls_s2=s2_n, input_chars=s1_c + s2_c, calibrated=bool(observed))
    return out


def est(kind, per_target, knowledge=None, model=FLASH):
    return oto().estimate_overview_cost(kind, per_target, {} if knowledge is None else knowledge, model)


# ============================================================
# 1. 定数・補助関数
# ============================================================
class TestConstantsAndHelpers(InTempCwd):
    """仕様の定数11個・補助関数・シグネチャ。"""

    def test_constants_have_the_specified_values(self):
        """定数11個が仕様の値。"""
        for n, v in SPEC_CONSTANTS.items():
            with self.subTest(constant=n):
                self.assertEqual(getattr(oto(), n), v)

    def test_staff_stage1_model_constant_is_removed(self):
        """(変更点1) 定数 STAFF_STAGE1_MODEL は削除されている (見積りで使わなくなったため)。"""
        self.assertFalse(hasattr(oto(), "STAFF_STAGE1_MODEL"))

    def test_signatures(self):
        """estimate_overview_cost(kind, per_target_threads, knowledge, model=None, include_stage2=True) (A7e で include_stage2 を追加) /
        count_failed_overview_threads(kind, per_target_threads)。"""
        p = list(inspect.signature(oto().estimate_overview_cost).parameters.values())
        self.assertEqual([x.name for x in p], ["kind", "per_target_threads", "knowledge", "model", "include_stage2"])
        self.assertIsNone(p[3].default)
        self.assertIs(p[4].default, True)
        p2 = list(inspect.signature(oto().count_failed_overview_threads).parameters)
        self.assertEqual(p2, ["kind", "per_target_threads"])
        p3 = list(inspect.signature(oto().count_overview_stage2_calls).parameters)
        self.assertEqual(p3, ["kind", "per_target_threads"])

    def test_cache_path_is_built_like_summarize(self):
        """_overview_cache_path は summarize_* と同じ名前 (analysis_cache/{kind}_{英数字と「 ._-」だけ}.json)。"""
        for kind in ("project", "staff"):
            for name in ("00_Caracal", "Yuto Oi", "a/b:c*?<>|", "名前.v2-x", "R&D (JP)"):
                with self.subTest(kind=kind, name=name):
                    self.assertEqual(os.path.normpath(oto()._overview_cache_path(kind, name)),
                                     os.path.normpath(cache_path(kind, name)))

    def test_cache_path_matches_the_file_summarize_actually_writes(self):
        """実際に summarize_project_threads / summarize_staff_threads が書いたファイルと同じパス。"""
        for kind, name in (("project", "P/x:1"), ("staff", "Yuto Oi!")):
            with self.subTest(kind=kind):
                runner = RealRun(kind)
                runner.run({name: threads_of(1)}, {})
                self.assertTrue(os.path.exists(oto()._overview_cache_path(kind, name)))

    def test_rules_text(self):
        """_overview_rules_text: ルールを「- 」付きで改行連結、空/リストでない→「特になし」。"""
        f = oto()._overview_rules_text
        self.assertEqual(f({"ai_correction_rules": ["A", "B"]}), "- A\n- B")
        self.assertEqual(f({"ai_correction_rules": []}), "特になし")
        self.assertEqual(f({}), "特になし")
        self.assertEqual(f({"ai_correction_rules": "AB"}), "特になし")
        self.assertEqual(f({"ai_correction_rules": None}), "特になし")

    def test_target_know(self):
        """_overview_target_know: knowledge["projects"/"staffs"][name]。形が違えば {}。"""
        f = oto()._overview_target_know
        self.assertEqual(f("project", "P", {"projects": {"P": {"a": 1}}}), {"a": 1})
        self.assertEqual(f("staff", "S", {"staffs": {"S": {"b": 2}}, "projects": {"S": {"x": 1}}}), {"b": 2})
        for bad in (None, [], {"projects": []}, {"projects": {"P": "x"}}, {"projects": {}}, {"staffs": {"P": {}}}):
            with self.subTest(knowledge=bad):
                self.assertEqual(f("project", "P", bad), {})

    def test_cached_threads(self):
        """_overview_cached_threads: rules_hash が一致し threads が dict のときだけ threads。他は {}。"""
        f = oto()._overview_cached_threads
        put_cache("project", "P", {"a": (1, False)}, rules=["R"])
        self.assertEqual(set(f("project", "P", rules_text(["R"]))), {"a"})
        self.assertEqual(f("project", "P", "特になし"), {})              # rules_hash 不一致
        self.assertEqual(f("project", "Q", "特になし"), {})              # 無い
        for raw in ("{壊れた", json.dumps([1, 2]), json.dumps({"rules_hash": rules_hash(), "threads": [1]}), ""):
            with self.subTest(raw=raw):
                put_cache("staff", "S", None, raw=raw)
                self.assertEqual(f("staff", "S", "特になし"), {})


# ============================================================
# 1. estimate_overview_cost (純関数)
# ============================================================
class TestEstimateCallsAndCache(InTempCwd):
    """Stage1 の回数 (キャッシュの省略判定) と Stage2 の回数。"""

    def test_no_cache_means_every_thread_plus_one_stage2_per_target(self):
        """キャッシュが無ければ全スレッドを Stage1 で1回ずつ＋対象ごとに Stage2 を1回。"""
        for kind in ("project", "staff"):
            with self.subTest(kind=kind):
                r = est(kind, {"A": threads_of(3), "B": threads_of(2, prefix="d")}, know_of(kind, "A"))
                self.assertEqual((r["n_calls_s1"], r["n_calls_s2"], r["n_calls"]), (5, 2, 7))

    def test_cached_threads_with_the_same_mail_count_are_skipped(self):
        """mail_count が一致し _error でないキャッシュ済みスレッドは Stage1 を省略する。"""
        for kind in ("project", "staff"):
            with self.subTest(kind=kind):
                put_cache(kind, "A", {"c0": (1, False), "c1": (1, False)})
                r = est(kind, {"A": threads_of(3)}, {})
                self.assertEqual((r["n_calls_s1"], r["n_calls_s2"]), (1, 1))

    def test_a_different_mail_count_or_error_is_analysed_again(self):
        """件数違い・_error のキャッシュは Stage1 をやり直す。"""
        for kind in ("project", "staff"):
            with self.subTest(kind=kind):
                put_cache(kind, "A", {"c0": (2, False), "c1": (1, True), "c2": (1, False)})
                r = est(kind, {"A": threads_of(3)}, {})
                self.assertEqual(r["n_calls_s1"], 2)

    def test_mail_count_compares_the_raw_mails_length_including_non_dicts(self):
        """件数の比較は mails の長さそのまま (dict でない要素も数える)。"""
        t = thread("x")
        t["mails"].append("not a dict")
        put_cache("project", "A", {"c": (2, False)})
        self.assertEqual(est("project", {"A": {"c": t}})["n_calls_s1"], 0)
        put_cache("project", "A", {"c": (1, False)})
        self.assertEqual(est("project", {"A": {"c": t}})["n_calls_s1"], 1)

    def test_rule_change_means_all_threads(self):
        """補正ルール文の md5 が rules_hash と違えば全件。"""
        for kind in ("project", "staff"):
            with self.subTest(kind=kind):
                put_cache(kind, "A", {"c0": (1, False), "c1": (1, False)}, rules=["古いルール"])
                k = know_of(kind, "A", rules=["新しいルール"])
                self.assertEqual(est(kind, {"A": threads_of(2)}, k)["n_calls_s1"], 2)
                k2 = know_of(kind, "A", rules=["古いルール"])
                self.assertEqual(est(kind, {"A": threads_of(2)}, k2)["n_calls_s1"], 0)

    def test_no_rules_matches_the_hash_of_tokubetsu_nashi(self):
        """補正ルールが無い (リストでない) ときは「特になし」の md5 で比べる。"""
        put_cache("project", "A", {"c0": (1, False)}, rules=[])
        self.assertEqual(est("project", {"A": threads_of(1)}, {"projects": {"A": {"ai_correction_rules": "x"}}})["n_calls_s1"], 0)

    def test_broken_cache_means_all_threads(self):
        """壊れたキャッシュ (JSONでない・dictでない・threadsがdictでない) は全件。"""
        for raw in ("{壊れた", json.dumps(["x"]), json.dumps({"rules_hash": rules_hash(), "threads": "x"})):
            with self.subTest(raw=raw):
                put_cache("project", "A", None, raw=raw)
                self.assertEqual(est("project", {"A": threads_of(2)})["n_calls_s1"], 2)

    def test_all_cached_still_counts_stage2_once(self):
        """全件キャッシュ済みでも Stage2 は対象ごとに1回数える (上限で数える)。"""
        put_cache("project", "A", {"c0": (1, False)})
        r = est("project", {"A": threads_of(1)})
        self.assertEqual((r["n_calls_s1"], r["n_calls_s2"], r["n_calls"]), (0, 1, 1))

    def test_empty_or_non_dict_threads_are_skipped(self):
        """threads が空・dictでない対象は飛ばす (Stage2 も数えない)。"""
        r = est("project", {"A": {}, "B": None, "C": [1], "D": "x", "E": threads_of(1)})
        self.assertEqual((r["n_calls_s1"], r["n_calls_s2"]), (1, 1))

    def test_the_other_kinds_cache_is_not_used(self):
        """project の見積りは staff_*.json を読まない (逆も同じ)。"""
        put_cache("staff", "A", {"c0": (1, False)})
        self.assertEqual(est("project", {"A": threads_of(1)})["n_calls_s1"], 1)


class TestEstimateInputChars(InTempCwd):
    """入力字数の式。"""

    def test_project_stage1_and_stage2_formula(self):
        """project の入力字数 = Stage1(本文800字上限+40・定型1500+ルール文+名前×2+100) + Stage2(1500+30000+経緯)。"""
        k = know_of("project", "PJ", rules=["R1", "ルール2"], master_history="経緯" * 10)
        r = est("project", {"PJ": {"c": thread("a" * 10, "b" * 900)}}, k)
        s1 = (10 + 40 + 4 + 800 + 40 + 4) + 1500 + len("- R1\n- ルール2") + 2 * 2 + 100   # 送信者「Ochi」4字/通
        s2 = 1500 + 30000 + 20 + 2 * 2
        self.assertEqual(r["input_chars"], s1 + s2)

    def test_staff_adds_the_project_list_and_role_background(self):
        """staff は Stage1 に PJ一覧の字数、Stage2 に役割・背景の字数を足す。"""
        k = know_of("staff", "Saji", rules=[], master_history="h" * 7, role="r" * 3, background="b" * 5,
                    projects=["AAA", "BB"])
        r = est("staff", {"Saji": {"c": thread("x" * 5)}}, k)
        s1 = (5 + 40 + 4) + 1500 + len("特になし") + 4 * 2 + 100 + len("AAA, BB")
        s2 = 1500 + 30000 + 7 + 3 + 5 + 4 * 2 + len("AAA, BB")
        self.assertEqual(r["input_chars"], s1 + s2)

    def test_body_limit_and_thread_cap(self):
        """本文は800字で頭打ち、1スレッドの合計は30000字で頭打ち。"""
        one = est("project", {"P": {"c": thread("x" * 800)}})["input_chars"]
        self.assertEqual(est("project", {"P": {"c": thread("x" * 801)}})["input_chars"], one)
        self.assertEqual(est("project", {"P": {"c": thread("x" * 799)}})["input_chars"], one - 1)
        big = est("project", {"P": {"c": thread(*["x" * 800] * 40)}})["input_chars"]     # 40×844 = 33760 → 30000
        self.assertEqual(big - one, 30000 - 844)

    def test_body_none_non_str_and_non_dict_mails(self):
        """本文 None は空・数値は str() の字数・dict でないメールは数えない。"""
        t = thread("ab")
        t["mails"] += [{"body": None}, {"body": 12345}, {}, "not a dict", None]
        r = est("project", {"P": {"c": t}})
        base = est("project", {"P": {"c": thread()}})["input_chars"]                   # メール0通のスレッド
        self.assertEqual(r["input_chars"], base + (2 + 40 + 4) + 40 + (5 + 40) + 40)     # "ab" / None / 12345 / {} (dict でない2つは数えない)

    def test_sender_name_is_added_per_mail(self):
        """(変更点2) 1通あたり len(str(sender_name or "")) を足す (None・無しは0、数値は str の字数)。本文の800字上限とは別に足す。"""
        def chars(sender, body="x" * 900):
            t = thread(body)
            t["mails"][0]["sender_name"] = sender
            return est("project", {"P": {"c": t}})["input_chars"]
        base = chars(None)
        self.assertEqual(chars("") - base, 0)
        self.assertEqual(chars("Yamamoto, Taro (Nexperia Japan)") - base, 31)
        self.assertEqual(chars(12345) - base, 5)
        t = thread("x")
        del t["mails"][0]["sender_name"]
        self.assertEqual(est("project", {"P": {"c": t}})["input_chars"], chars(None, "x"))

    def test_stage2_adds_the_name_twice_and_staff_adds_the_project_list(self):
        """(変更点3) Stage2 は 名前×2 を足し、staff はさらに PJ一覧 (", " 連結) の字数を足す。"""
        put_cache("project", "LongProjectName", {"c0": (1, False)})
        put_cache("staff", "LongProjectName", {"c0": (1, False)})
        per = {"LongProjectName": threads_of(1)}                       # Stage1 は省略 → Stage2 だけ
        self.assertEqual(est("project", per, {})["input_chars"], 1500 + 30000 + 15 * 2)
        k = {"projects": {"A1": {}, "B22": {}, "C333": {}}, "staffs": {"LongProjectName": {"role": "rr", "background": "b"}}}
        self.assertEqual(est("staff", per, k)["input_chars"], 1500 + 30000 + 15 * 2 + 2 + 1 + len("A1, B22, C333"))

    def test_matches_the_reference_on_a_mixed_case(self):
        """キャッシュ・ルール・経緯が混在するケースで、独立した参照計算と全キーが一致する。"""
        put_cache("project", "A", {"c0": (1, False), "c1": (3, False)}, rules=["x"])
        k = {"projects": {"A": {"ai_correction_rules": ["x"], "master_history": "m" * 123}, "B": {}}}
        per = {"A": threads_of(3, "y" * 1000, "z"), "B": threads_of(2, "w" * 300, prefix="b")}
        r, ref = est("project", per, k, FLASH), ref_estimate("project", per, k, FLASH)
        for key in ("n_calls_s1", "n_calls_s2", "input_chars", "n_calls", "input_tokens", "output_tokens", "yen"):
            with self.subTest(key=key):
                self.assertEqual(r[key], ref[key])


class TestEstimateOutputAndModel(InTempCwd):
    """出力の既定値・実績ログからの校正・下限・モデル。"""

    def test_default_outputs_without_a_log(self):
        """実績ログが無ければ Stage1=2500・Stage2=6000 トークン/回、calibrated=False。"""
        r = est("project", {"P": threads_of(2)})
        self.assertEqual(r["output_tokens"], 2 * 2500 + 6000)
        self.assertFalse(r["calibrated"])

    def test_calibrated_from_the_log_of_the_same_kind(self):
        """実績ログ (feature=kind) の1回あたり出力×1.5 を両段に使い、calibrated=True。"""
        for kind in ("project", "staff"):
            with self.subTest(kind=kind):
                write_log(rec(kind, 2, 20000))                   # 1回あたり 10000 → ×1.5 = 15000
                r = est(kind, {"P": threads_of(2)})
                self.assertTrue(r["calibrated"])
                self.assertEqual(r["output_tokens"], 3 * 15000)
                os.remove(LOG_PATH)

    def test_other_features_do_not_calibrate(self):
        """別の feature の実績は使わない。"""
        write_log(rec("staff", 1, 50000), rec("review", 1, 50000), rec("action", 1, 50000))
        r = est("project", {"P": threads_of(1)})
        self.assertFalse(r["calibrated"])
        self.assertEqual(r["output_tokens"], 2500 + 6000)

    def test_floor_is_half_the_default_per_stage(self):
        """実績×1.5 が小さすぎるときは段ごとに既定の半分 (1250 / 3000) を下限にする。"""
        write_log(rec("project", 1, 100))                         # 150 → 下限 1250 / 3000
        r = est("project", {"P": threads_of(2)})
        self.assertEqual(r["output_tokens"], 2 * 1250 + 3000)
        self.assertTrue(r["calibrated"])

    def test_floor_boundary(self):
        """下限の境界 (実績×1.5 = 3000 は Stage2 の下限と同じ)。"""
        write_log(rec("project", 1, 2000))                        # 3000 → S1 3000 (>1250), S2 3000 (=下限)
        self.assertEqual(est("project", {"P": threads_of(1)})["output_tokens"], 3000 + 3000)

    def test_staff_stage1_is_priced_with_the_configured_model(self):
        """(変更点1) 同じ入力なら staff と project の円は同じ (staff の Stage1 も設定モデルの単価)。金額は参照計算と一致。"""
        per = {"X": threads_of(5, "y" * 500)}
        kp = {"projects": {"X": {}}}
        ks = {"staffs": {"X": {}}}
        rp, rs = est("project", per, kp), est("staff", per, ks)
        self.assertEqual(rp["input_chars"], rs["input_chars"])
        self.assertEqual(rs["yen"], rp["yen"])
        self.assertEqual(rs["output_tokens"], rp["output_tokens"])
        self.assertEqual(rs["yen"], ref_estimate("staff", per, ks)["yen"])
        self.assertEqual(rp["yen"], ref_estimate("project", per, kp)["yen"])

    def test_stage2_uses_the_given_model_and_stage1_too_for_project(self):
        """指定モデル (pro) の単価で計算される (project は両段、staff は Stage2)。"""
        per = {"X": threads_of(2)}
        for kind in ("project", "staff"):
            with self.subTest(kind=kind):
                self.assertEqual(est(kind, per, {}, PRO)["yen"], ref_estimate(kind, per, {}, PRO)["yen"])

    def test_model_none_uses_the_default_model(self):
        """model=None は既定モデルの単価。"""
        per = {"X": threads_of(1)}
        self.assertEqual(oto().estimate_overview_cost("project", per, {})["yen"],
                         ref_estimate("project", per, {}, None)["yen"])


class TestEstimateReturnAndPurity(InTempCwd):
    """戻り値のキー・needs_confirm の境界・形の違う入力・副作用なし。"""

    def test_return_keys(self):
        """戻り値のキーは estimate_ai_cost_yen_multi の dict ＋ n_calls_s1 / n_calls_s2 / input_chars / calibrated。"""
        r = est("project", {"P": threads_of(1)})
        self.assertEqual(set(r), RETURN_KEYS)
        self.assertIsInstance(r["calibrated"], bool)
        self.assertEqual(r["n_calls"], r["n_calls_s1"] + r["n_calls_s2"])

    def test_needs_confirm_boundary(self):
        """yen が 100 以上で needs_confirm (実績ログで 1回あたりの出力を変えて境界をまたぐ)。"""
        lo = hi = None
        for out in range(81500, 83000, 5):                  # 1対象1スレッド: 1回あたり約8.2万で 100円をまたぐ
            write_log(rec("project", 1, out))
            r = est("project", {"P": threads_of(1)})
            self.assertEqual(r["needs_confirm"], r["yen"] >= 100)
            if r["yen"] < 100:
                lo = r
            elif hi is None:
                hi = r
        self.assertIsNotNone(lo)
        self.assertIsNotNone(hi)

    def test_malformed_inputs_do_not_raise(self):
        """形の違う入力 (None・リスト・文字列・mails が無い等) でも例外を出さない。"""
        for per in (None, [], "x", 1, {}, {"A": None}, {1: {"c": {}}}, {"A": {"c": None}}, {"A": {"c": {"mails": None}}},
                    {"A": {"c": {"mails": "abc"}}}, {"A": {"c": {"no_mails": 1}}}):
            for k in (None, [], {"projects": None, "staffs": None}, {"projects": {"A": None}}, {"staffs": {"A": []}}):
                for kind in ("project", "staff"):
                    with self.subTest(per=per, knowledge=k, kind=kind):
                        r = oto().estimate_overview_cost(kind, per, k, FLASH)
                        self.assertTrue(RETURN_KEYS <= set(r))

    def test_non_dict_per_target_is_zero_calls(self):
        """per_target_threads が dict でなければ0件・0円・確認不要。"""
        for per in (None, [], "x"):
            r = est("project", per)
            self.assertEqual((r["n_calls"], r["input_chars"], r["yen"]), (0, 0, 0))
            self.assertFalse(r["needs_confirm"])

    def test_does_not_mutate_input_or_write_files(self):
        """入力を書き換えず、ファイルも作らない。"""
        put_cache("project", "A", {"c0": (1, False)})
        per = {"A": threads_of(2), "B": threads_of(1)}
        k = know_of("project", "A", rules=["x"], master_history="m")
        before_per, before_k = copy.deepcopy(per), copy.deepcopy(k)
        before = snapshot_files(".")
        est("project", per, k)
        est("staff", per, k)
        self.assertEqual(per, before_per)
        self.assertEqual(k, before_k)
        self.assertEqual(snapshot_files("."), before)


class TestCountFailedOverviewThreads(InTempCwd):
    """count_failed_overview_threads: 解析後のキャッシュで、対象の cid のうち data._error が真の数。"""

    def test_counts_errors_only_for_the_given_cids(self):
        """各対象の threads のキーに当たる項目のうち data._error が真のものだけ数える。"""
        for kind in ("project", "staff"):
            with self.subTest(kind=kind):
                put_cache(kind, "A", {"c0": (1, True), "c1": (1, False), "zz": (1, True)})
                put_cache(kind, "B", {"d0": (1, True), "d1": (1, True)})
                per = {"A": threads_of(2), "B": threads_of(2, prefix="d"), "C": threads_of(1)}
                self.assertEqual(oto().count_failed_overview_threads(kind, per), 3)

    def test_rules_hash_is_not_required_and_other_kind_is_ignored(self):
        """解析後のキャッシュ (rules_hash を問わない) を読む。別の kind のファイルは見ない。"""
        put_cache("project", "A", {"c0": (1, True)}, rules=["何か"])
        self.assertEqual(oto().count_failed_overview_threads("project", {"A": threads_of(1)}), 1)
        self.assertEqual(oto().count_failed_overview_threads("staff", {"A": threads_of(1)}), 0)

    def test_broken_or_missing_is_zero_and_never_raises(self):
        """無い・壊れた・threads が dict でない・data が dict でない → 0。例外なし。"""
        put_cache("project", "A", None, raw="{壊れた")
        put_cache("project", "B", None, raw=json.dumps({"threads": [1]}))
        put_cache("project", "C", None, raw=json.dumps({"threads": {"c0": {"data": "x"}, "c1": "y"}}))
        per = {"A": threads_of(1), "B": threads_of(1), "C": threads_of(2), "D": threads_of(1)}
        self.assertEqual(oto().count_failed_overview_threads("project", per), 0)
        for bad in (None, [], "x", {"A": None}, {"A": "x"}):
            self.assertEqual(oto().count_failed_overview_threads("project", bad), 0)


def put_raw_threads(kind, name, threads):
    write_json(cache_path(kind, name), {"rules_hash": rules_hash(), "threads": threads})


class TestCountOverviewStage2Calls(InTempCwd):
    """(変更点4) count_overview_stage2_calls: 解析後のキャッシュで、対象のスレッドに「data が空でない dict・is_target が偽でない
    (既定True)・_error が偽」の要約が1件以上ある対象の数。読めない等は0扱い・例外なし。"""

    def test_counts_targets_with_at_least_one_valid_summary(self):
        """有効な要約が1件以上ある対象だけを1と数える (1対象に何件あっても1)。"""
        for kind in ("project", "staff"):
            with self.subTest(kind=kind):
                put_cache(kind, "A", {"c0": (1, False), "c1": (1, False)})
                put_cache(kind, "B", {"d0": (1, True)})                      # 全部失敗 → 数えない
                put_cache(kind, "C", {"e0": (1, True), "e1": (1, False)})   # 1件でも有効 → 数える
                per = {"A": threads_of(2), "B": threads_of(1, prefix="d"), "C": threads_of(2, prefix="e"),
                       "D": threads_of(1, prefix="f")}                          # キャッシュ無し → 数えない
                self.assertEqual(oto().count_overview_stage2_calls(kind, per), 2)

    def test_is_target_and_data_rules(self):
        """is_target が偽・data が空/dictでない・_error が真 → 数えない。is_target が無い → 既定 True で数える。"""
        cases = {
            "no_is_target": ({"summary": "s"}, 1), "is_target_true": ({"is_target": True}, 1),
            "is_target_false": ({"is_target": False, "summary": "s"}, 0), "empty": ({}, 0), "none": (None, 0),
            "string": ("x", 0), "error": ({"is_target": True, "_error": True}, 0), "error_false": ({"_error": False}, 1),
        }
        for label, (data, expected) in cases.items():
            with self.subTest(case=label):
                put_raw_threads("project", "A", {"c0": {"mail_count": 1, "data": data}})
                self.assertEqual(oto().count_overview_stage2_calls("project", {"A": threads_of(1)}), expected)

    def test_only_the_given_cids_are_looked_at(self):
        """対象のスレッド (per_target_threads のキー) に無い cid の要約は数えない。別の kind のファイルも見ない。"""
        put_cache("project", "A", {"other": (1, False)})
        self.assertEqual(oto().count_overview_stage2_calls("project", {"A": threads_of(1)}), 0)
        put_cache("staff", "B", {"c0": (1, False)})
        self.assertEqual(oto().count_overview_stage2_calls("project", {"B": threads_of(1)}), 0)
        self.assertEqual(oto().count_overview_stage2_calls("staff", {"B": threads_of(1)}), 1)

    def test_broken_inputs_are_zero_and_never_raise(self):
        """壊れた/無いファイル・threads が dict でない・入力が dict でない → 0。例外を出さない。"""
        put_cache("project", "A", None, raw="{壊れた")
        put_cache("project", "B", None, raw=json.dumps({"threads": [1]}))
        put_cache("project", "C", None, raw=json.dumps([1, 2]))
        per = {"A": threads_of(1), "B": threads_of(1), "C": threads_of(1), "E": {}, "F": None}
        self.assertEqual(oto().count_overview_stage2_calls("project", per), 0)
        for bad in (None, [], "x", 1, {"A": "x"}, {"A": [1]}):
            self.assertEqual(oto().count_overview_stage2_calls("project", bad), 0)

    def test_does_not_write_files(self):
        """ファイルを作らない・書き換えない。"""
        put_cache("project", "A", {"c0": (1, False)})
        before = snapshot_files(".")
        oto().count_overview_stage2_calls("project", {"A": threads_of(1), "Z": threads_of(1)})
        self.assertEqual(snapshot_files("."), before)


# ============================================================
# 2. 見積り＝実際 (本物の summarize_* を、AI 呼び出しだけ偽物にして動かす)
# ============================================================
class RealRun:
    """本物の MailSummarizer.summarize_project_threads / summarize_staff_threads を、_run_genai_call_with_schema だけ
    偽物にして実行する。呼び出し (stage, プロンプト, モデル指定) を記録する。fail_cids の Stage1 は失敗 (_error) を返す。"""

    def __init__(self, kind, fail_cids=()):
        self.kind = kind
        self.fail_cids = set(fail_cids)
        self.calls = []
        self.lock = threading.Lock()
        s = oto().MailSummarizer.__new__(oto().MailSummarizer)
        s.model_id = FLASH
        s.total_input_tokens = s.total_output_tokens = 0
        s._run_genai_call_with_schema = self.fake
        self.s = s

    def fake(self, prompt, schema, override_model=None):
        props = (schema or {}).get("properties", {})
        stage = 1 if "thread_id" in props else 2
        with self.lock:
            self.calls.append((stage, prompt, override_model))
        if stage == 1:
            m = re.search(r'thread_id は理由を問わず "(.*?)"', prompt)
            cid = m.group(1) if m else "?"
            if cid in self.fail_cids:
                return {"_error": True, "summary": "失敗"}
            return {"thread_id": cid, "topic": "t", "is_target": True, "summary": "要約" * 20, "category": "その他",
                    "project_scope": "x", "action_type": "通知・共有", "importance": "中"}
        return {"manager_actions": [], "staff_status": [], "stalled_monitor": [], "updated_history": "新しい経緯"}

    def run(self, per_target, knowledge):
        fn = self.s.summarize_project_threads if self.kind == "project" else self.s.summarize_staff_threads
        for name, threads in per_target.items():
            fn(name, threads, knowledge)
        return self

    def n(self, stage):
        return sum(1 for c in self.calls if c[0] == stage)

    def chars(self, stage=None):
        return sum(len(c[1]) for c in self.calls if stage is None or c[0] == stage)


class TestEstimateEqualsActual(InTempCwd):
    """見積りの Stage1 回数 = 実際、Stage2 回数 ≧ 実際、入力字数 ≧ 実際のプロンプトの合計。"""

    def check(self, kind, per, knowledge, fail_cids=()):
        e = est(kind, per, knowledge)
        r = RealRun(kind, fail_cids).run(per, knowledge)
        self.assertEqual(r.n(1), e["n_calls_s1"], "Stage1 の実回数と見積りが違う")
        self.assertLessEqual(r.n(2), e["n_calls_s2"])
        self.assertLessEqual(r.chars(), e["input_chars"], "実際のプロンプトの字数の合計が見積りを超えた")
        s2_part = ref_counts(kind, per, knowledge)[3]
        self.assertLessEqual(r.chars(1), e["input_chars"] - s2_part, "Stage1 のプロンプト合計が Stage1 の見積りを超えた")
        self.assertLessEqual(r.chars(2), s2_part, "Stage2 のプロンプト合計が Stage2 の見積りを超えた")
        self.assertEqual(oto().count_overview_stage2_calls(kind, per), r.n(2), "count_overview_stage2_calls が実際の Stage2 回数と違う")
        return e, r

    def test_without_cache(self):
        """キャッシュなし: 見積りの Stage1 回数 = 実際、Stage2 ≧ 実際、字数 ≧ 実際。"""
        for kind in ("project", "staff"):
            with self.subTest(kind=kind):
                self.check(kind, {"A": threads_of(3, "本文" * 300), "B": threads_of(1, prefix="b")}, know_of(kind, "A"))

    def test_second_run_uses_the_cache(self):
        """2回目 (全件キャッシュ済み): Stage1 は0回で見積りと一致。"""
        for kind in ("project", "staff"):
            with self.subTest(kind=kind):
                per = {"A": threads_of(3)}
                self.check(kind, per, {})
                e, r = self.check(kind, per, {})
                self.assertEqual(r.n(1), 0)

    def test_mail_count_change_and_errors(self):
        """件数違い・前回失敗 (_error) のスレッドだけが再解析され、見積りと一致。"""
        for kind in ("project", "staff"):
            with self.subTest(kind=kind):
                per = {"A": threads_of(4)}
                self.check(kind, per, {}, fail_cids={"c1"})
                per2 = copy.deepcopy(per)
                per2["A"]["c2"]["mails"].append(mail("追加", cid="c2"))
                e, r = self.check(kind, per2, {})
                self.assertEqual(r.n(1), 2)                       # c1 (_error) と c2 (件数違い)

    def test_rule_change_reanalyses_everything(self):
        """補正ルールが変わると全件再解析され、見積りと一致。"""
        for kind in ("project", "staff"):
            with self.subTest(kind=kind):
                per = {"A": threads_of(3)}
                self.check(kind, per, know_of(kind, "A", rules=["旧"]))
                e, r = self.check(kind, per, know_of(kind, "A", rules=["新しいルール"]))
                self.assertEqual(r.n(1), 3)

    def test_all_failed_means_no_stage2(self):
        """Stage1 が全部失敗すると Stage2 は呼ばれない (見積りは上限の1回)。"""
        e, r = self.check("project", {"A": threads_of(2)}, {}, fail_cids={"c0", "c1"})
        self.assertEqual(r.n(2), 0)
        self.assertEqual(e["n_calls_s2"], 1)

    def test_long_names_rules_history_and_bodies(self):
        """会議のような長い件名・長い送信者名・長い補正ルール・長い経緯・本文の上限超え。"""
        long_subject = "【定例】Nexperia Japan Site Weekly Meeting 議事録 - Quarterly Business Review (Finance/Procurement)"
        for kind in ("project", "staff"):
            with self.subTest(kind=kind):
                per = {"03_R19Projects": {}}
                for i in range(6):
                    t = thread(*(["長文" * 700] * (i + 1) + ["短"]), sender="Yamamoto, Taro (Nexperia Japan)",
                               cid=f"conv{i}", topic=long_subject * 2)
                    per["03_R19Projects"][f"conv{i}"] = t
                k = know_of(kind, "03_R19Projects", rules=["ルール" * 100, "rule " * 80, "x"],
                            master_history="経緯" * 3000, role="課長" * 50, background="背景" * 200,
                            projects=["00_Caracal", "01_Wheeling", "02_GrandTeton", "03_R19Projects"])
                self.check(kind, per, k)

    def test_thread_cap_with_many_mails(self):
        """メールが多くて30000字の上限に掛かるスレッドでも、見積りが実際を下回らない。"""
        for kind in ("project", "staff"):
            with self.subTest(kind=kind):
                self.check(kind, {"P": {"c": thread(*["本" * 800] * 50, cid="c")}}, {})


class TestSpecGapEstimateCacheEntryWithoutData(InTempCwd):
    """(SpecGap) キャッシュの項目に data が無い (mail_count だけ) 場合。仕様「data._error 偽なら省略」を、summarize_* と同じく
    「data が無い = _error 偽 → 省略」と解釈し、見積りの Stage1 回数が実際と一致することを確かめる。"""

    def test_entry_without_data_counts_like_summarize(self):
        """data の無いキャッシュ項目でも、見積りの Stage1 回数が実際と一致する。"""
        for kind in ("project", "staff"):
            with self.subTest(kind=kind):
                write_json(cache_path(kind, "A"), {"rules_hash": rules_hash(), "threads": {"c0": {"mail_count": 1}}})
                per = {"A": threads_of(2)}
                e = est(kind, per, {})
                r = RealRun(kind).run(per, {})
                self.assertEqual(e["n_calls_s1"], r.n(1))


class LongSummaryRun(RealRun):
    """Stage1 の要約が長い (Stage2 の内容が30000字の上限に掛かる) 偽AI。"""

    def fake(self, prompt, schema, override_model=None):
        r = super().fake(prompt, schema, override_model)
        if isinstance(r, dict) and "thread_id" in r:
            r["summary"] = "長" * 2500
        return r


class TestEstimateCoversLongSenderNamesAndProjectLists(InTempCwd):
    """(変更点2・3) 長い送信者名・多数のPJ一覧でも、段ごとに見積りが実際を下回らない (前回の SpecGap を通常テストにした)。"""

    def test_sixty_char_sender_names_on_many_short_mails(self):
        """60字の送信者名×60通の短いメールでも Stage1 の見積りが実際を下回らない。"""
        sender = "Very Long Display Name, Somebody (Nexperia Japan K.K. / R&D)"[:60]
        for kind in ("project", "staff"):
            with self.subTest(kind=kind):
                per = {"P": {"c": thread(*["短い"] * 60, sender=sender, cid="c")}}
                e = est(kind, per, {})
                r = RealRun(kind).run(per, {})
                s2_part = ref_counts(kind, per, {})[3]
                self.assertLessEqual(r.chars(1), e["input_chars"] - s2_part)
                self.assertLessEqual(r.chars(2), s2_part)

    def test_staff_stage2_with_thirty_projects_and_full_content(self):
        """PJ 30件・Stage2 の内容が30000字の上限まで来ても、Stage2 の見積りが実際を下回らない (名前・PJ一覧を数える)。"""
        for kind in ("project", "staff"):
            with self.subTest(kind=kind):
                k = know_of(kind, "Kajikawa", projects=[f"{i:02d}_ProjectName{i}" for i in range(30)],
                            role="課長代理", background="背景" * 30, master_history="経緯" * 50)
                per = {"Kajikawa": threads_of(16)}
                e = est(kind, per, k)
                s1n, s1c, s2n, s2c = ref_counts(kind, per, k)
                r = LongSummaryRun(kind).run(per, k)
                self.assertEqual(r.n(1), e["n_calls_s1"])
                self.assertLessEqual(r.chars(1), s1c)
                self.assertLessEqual(r.chars(2), s2c)
                self.assertEqual(e["input_chars"], s1c + s2c)


# ============================================================
# 3. 画面の流れ
# ============================================================
PROJECTS = ("00_Caracal", "01_Wheeling", "02_GrandTeton", "03_R19Projects")
PROJECT_VARS = ("var_proj_caracal", "var_proj_wheeling", "var_proj_grandteton", "var_proj_r19projects")
STAFFS = ("Taizo", "Nakai", "Kajikawa", "Saji", "Oi", "Najib")
STAFF_VARS = ("var_sm_taizo", "var_sm_nakai", "var_sm_kajikawa", "var_sm_saji", "var_sm_oi", "var_sm_najib")
SEARCH_ALIASES = {"Oi": "yuto.oi"}
CANCELLED = "⏹ 費用の確認で中止しました（AI分析は行っていません）"
FINAL_PREFIXES = ("✅ 完了", "⚠ 完了", "⏹ 費用の確認で中止しました", "❌ 失敗しました", "❌ 生成失敗")
LABEL = {"project": "プロジェクト俯瞰", "staff": "スタッフ俯瞰"}
FLAG = {"project": "_project_overview_running", "staff": "_staff_overview_running"}
BUSY_MSG = {"project": "プロジェクト俯瞰を実行中です。終わってからもう一度押してください。",
            "staff": "スタッフ俯瞰を実行中です。終わってからもう一度押してください。"}
LAST_RESULT = {"project": os.path.join("json", "project_last_result_latest.json"),
               "staff": os.path.join("json", "staff_last_result_latest.json")}


class FlowOutlook:
    """Outlook の代わり。プロジェクト: get_project_mails / スタッフ: search_mails_fast。group_by_thread は本物。"""

    def __init__(self, events, mails_by_target, fetch_error=None):
        self.events = events
        self.mails = mails_by_target
        self.fetch_error = fetch_error
        self.search_error = None
        self._group = types.MethodType(oto().OutlookMailManager.group_by_thread, self)

    def get_project_mails(self, folder_name, days, include_sent=False):
        self.events.append(f"fetch:{folder_name}")
        if self.fetch_error is not None:
            raise self.fetch_error
        return copy.deepcopy(self.mails.get(folder_name, []))

    def search_mails_fast(self, conditions, logic="AND", flag=True, *a, **k):
        term = conditions.get("sender") or conditions.get("body_keyword")
        self.events.append(f"fetch:{term}")
        if self.search_error is not None:
            raise self.search_error
        if not conditions.get("sender"):
            return []
        name = {v: k2 for k2, v in SEARCH_ALIASES.items()}.get(term, term)
        return copy.deepcopy(self.mails.get(name, []))

    def group_by_thread(self, mails):
        if self.fetch_error is not None and isinstance(self.fetch_error, LookupError):
            raise self.fetch_error
        return self._group(mails)


class FlowSummarizer:
    """MailSummarizer の代わり。summarize_* の呼び出しを記録し、トークンを加算する。
    fail_cids: その cid の解析キャッシュを _error で書く (AI失敗の再現)。raise_on: その対象で例外。"""

    model_id = FLASH

    def __init__(self, test, add_in=0, add_out=0, fail_cids=(), raise_on=None, error=None):
        self.t = test
        self._ti = self._to = 0
        self.add_in, self.add_out = add_in, add_out
        self.fail_cids = set(fail_cids)
        self.raise_on, self.error = raise_on, error
        self.calls = []
        self.entry_totals = []            # summarize_* に入った時点の集計 (in, out)
        self.gate = self.started = None

    # (fix2) 共有のトークン集計。外から 0 を代入された (リセットされた) ことを events に "reset:in" / "reset:out" で記録する
    @property
    def total_input_tokens(self):
        return self._ti

    @total_input_tokens.setter
    def total_input_tokens(self, value):
        if value == 0:
            self.t.events.append("reset:in")
        self._ti = value

    @property
    def total_output_tokens(self):
        return self._to

    @total_output_tokens.setter
    def total_output_tokens(self, value):
        if value == 0:
            self.t.events.append("reset:out")
        self._to = value

    def _run(self, kind, name, threads, knowledge, **kw):
        self.t.events.append(f"ai:{name}")
        self.entry_totals.append((self._ti, self._to))
        if self.gate is not None:
            self.started.set()
            self.gate.wait(10)
        self.calls.append((name, threads, knowledge))
        self._ti += self.add_in
        self._to += self.add_out
        if self.raise_on == name:
            raise self.error
        entries = {cid: (len(t["mails"]), cid in self.fail_cids) for cid, t in threads.items()}
        if entries:
            put_cache(kind, name, entries)
        return {"manager_actions": [], "staff_status": [{"text": f"S-{name}"}], "stalled_monitor": [],
                "updated_history": f"H-{name}", "ai_questions": [], "threads": []}

    def summarize_project_threads(self, project_name, threads, knowledge, retry_callback=None, progress_callback=None):
        return self._run("project", project_name, threads, knowledge)

    def summarize_staff_threads(self, staff_name, threads, knowledge, retry_callback=None, progress_callback=None):
        return self._run("staff", staff_name, threads, knowledge)


class FlowReporter:
    def __init__(self, events, path="/tmp/overview.html", fail=None):
        self.events = events
        self.path = path
        self.fail = fail
        self.calls = []
        self.folder = os.getcwd()

    def generate_project_report(self, name, summaries, all_orig, knowledge, date_range, sort_order, ti, to, **kw):
        self.events.append("report")
        if self.fail:
            raise self.fail
        self.calls.append({"name": name, "summaries": copy.deepcopy(summaries), "orig": all_orig, "ti": ti, "to": to})
        return self.path

    def generate_staff_report(self, name, summaries, all_orig, knowledge, date_range, sort_order, ti, to, **kw):
        self.events.append("report")
        if self.fail:
            raise self.fail
        self.calls.append({"name": name, "summaries": copy.deepcopy(summaries), "orig": all_orig, "ti": ti, "to": to})
        return self.path


class _Spin:
    def get(self):
        return "24"


class SpyVar:
    """Tk の変数の代わり。get() の呼び出しを記録して、元の変数の値を返す (入力を読んだかどうかの確認用)。"""

    def __init__(self, inner, log, name):
        self.inner, self.log, self.name = inner, log, name

    def get(self):
        self.log.append(self.name)
        return self.inner.get()

    def set(self, value):
        return self.inner.set(value)


INPUT_VARS = {
    "project": PROJECT_VARS + ("var_proj_period", "var_proj_sort", "var_proj_unread"),
    "staff": STAFF_VARS + ("var_staff_name", "var_staff_from", "var_staff_to", "var_staff_cc", "var_staff_period",
                           "var_staff_sort", "var_staff_unread"),
}


class OverviewCase(a1gui.GuiCase):
    """偽Outlook・偽AI・ダイアログのスタブで、本物の _run_project_overview / _run_staff_overview を動かす土台
    (A1.1 の UpdateCase と同じく、実行中は GC を止める・askyesno の答えを指定できる・呼び出し順を記録する)。"""

    def setUp(self):
        gc.disable()
        self.addCleanup(gc.enable)
        super().setUp()
        self.events = []
        self.statuses = []
        self.calls = {}
        self.reals = {}
        self.browser_calls = []
        self.printed = io.StringIO()
        p = mock.patch("webbrowser.open", lambda url, *a, **k: (self.events.append("browser"), self.browser_calls.append(url), True)[2])
        p.start()
        self.addCleanup(p.stop)
        for name, tag in (("estimate_overview_cost", "estimate"), ("record_ai_usage", "record"),
                          ("save_project_knowledge", "save_knowledge"), ("count_failed_overview_threads", "count_failed")):
            self._spy_module(name, tag)

    def _spy_module(self, name, tag):
        real = getattr(oto(), name, None)
        self.calls[tag] = []
        self.reals[tag] = real
        if real is None:
            return

        def wrapper(*args, **kwargs):
            self.events.append(tag)
            result = real(*args, **kwargs)
            self.calls[tag].append((args, kwargs, result))
            return result
        p = mock.patch.object(oto(), name, wrapper)
        p.start()
        self.addCleanup(p.stop)

    def _patch_messagebox(self):
        super()._patch_messagebox()
        self.ask_answer = True
        self.dialog_threads = []                                  # [(関数名, メインスレッドで呼ばれたか)]
        inner_err = tkmessagebox.showerror

        def err(*args, **kwargs):
            self.dialog_threads.append(("showerror", threading.current_thread() is threading.main_thread()))
            return inner_err(*args, **kwargs)
        p0 = mock.patch.object(tkmessagebox, "showerror", err)
        p0.start()
        self.addCleanup(p0.stop)
        inner = tkmessagebox.askyesno

        def ask(*args, **kwargs):
            self.events.append("confirm_dialog")
            inner(*args, **kwargs)
            return self.ask_answer
        p = mock.patch.object(tkmessagebox, "askyesno", ask)
        p.start()
        self.addCleanup(p.stop)

    def _teardown_gui(self):
        orig_settle = self.settle
        self.settle = lambda seconds=0.15: orig_settle(0.01)
        try:
            super()._teardown_gui()
        finally:
            self.settle = orig_settle
            self.gui = None
            gc.collect(0)

    def build(self, kind, targets, mails, *, ask=True, log=None, knowledge=None, add_in=1000, add_out=500,
              fail_cids=(), raise_on=None, error=None, fetch_error=None, report_path="/tmp/overview.html",
              initial_totals=(7777, 8888), unread_only=False, report_fail=None):
        if log:
            write_log(*log)
        if knowledge is not None:
            write_json(KNOWLEDGE_PATH, knowledge)
        gui = self.make_gui(build_panel=False)
        root = gui.root
        B = lambda v=False: tk.BooleanVar(master=root, value=v)           # noqa: E731
        S = lambda v="": tk.StringVar(master=root, value=v)               # noqa: E731
        for var, name in zip(PROJECT_VARS, PROJECTS):
            setattr(gui, var, B(kind == "project" and name in targets))
        for var, name in zip(STAFF_VARS, STAFFS):
            setattr(gui, var, B(kind == "staff" and name in targets))
        gui.var_proj_period, gui.var_proj_sort, gui.var_proj_unread = S("過去2週間"), S("新しい順"), B(unread_only)
        gui.var_proj_report_mode = S("adopted")
        gui.spin_proj_h = gui.spin_staff_h = _Spin()
        gui.var_staff_name = S("")
        gui.var_staff_from, gui.var_staff_to, gui.var_staff_cc = B(True), B(True), B(False)
        gui.var_staff_period, gui.var_staff_sort, gui.var_staff_unread = S("過去1週間"), S("新しい順"), B(unread_only)
        gui.var_staff_report_mode = S("adopted")
        gui.btn_reformat_project = ttk.Button(root, text="r", state=tk.DISABLED)
        gui.btn_reformat_staff = ttk.Button(root, text="r", state=tk.DISABLED)
        gui.cb_staff_name = ttk.Combobox(root, values=[])
        gui.project_knowledge = {}
        gui.outlook = FlowOutlook(self.events, mails, fetch_error)
        gui.summarizer = self.summ = FlowSummarizer(self, add_in, add_out, fail_cids, raise_on, error)
        gui.summarizer.total_input_tokens, gui.summarizer.total_output_tokens = initial_totals
        gui.reporter = self.reporter = FlowReporter(self.events, report_path, report_fail)
        real_status = gui._set_status

        def status_spy(text, start_timer=False, current=0, total=0):
            self.statuses.append((text, threading.current_thread() is threading.main_thread()))
            return real_status(text, start_timer, current, total)
        gui._set_status = status_spy
        self.confirm_totals, self.outcomes = [], []
        real_confirm, real_finish = gui._confirm_ai_cost, gui._finish_overview_status

        def confirm_spy(estimate, label):
            self.events.append("confirm")
            self.confirm_totals.append((gui.summarizer.total_input_tokens, gui.summarizer.total_output_tokens))
            return real_confirm(estimate, label)

        def finish_spy(outcome, *a, **k):
            self.events.append("finish")
            try:
                self.outcomes.append(copy.deepcopy(outcome))
            except Exception:                                   # noqa: BLE001
                self.outcomes.append(dict(outcome))
            return real_finish(outcome, *a, **k)
        gui._confirm_ai_cost = confirm_spy
        gui._finish_overview_status = finish_spy
        self.ask_answer = ask
        self.kind = kind
        return gui

    def totals(self):
        return (self.gui.summarizer.total_input_tokens, self.gui.summarizer.total_output_tokens)

    def run_flow(self, kind, targets, mails, **kw):
        gui = self.build(kind, targets, mails, **kw)
        fn = gui._run_project_overview if kind == "project" else gui._run_staff_overview
        with contextlib.redirect_stdout(self.printed):
            gui.root.after(0, fn)
            ok = self.pump(lambda: any(t.startswith(FINAL_PREFIXES) for t, _ in self.statuses), timeout=10)
            self.assertTrue(ok, f"最終ステータスに到達しない: events={self.events}, statuses={self.statuses[-4:]}")
            self.pump(lambda: not self.worker_threads(), timeout=5)
            self.settle(0.05)
        self.gui = gui
        return gui

    def entry(self, gui=None):
        gui = gui or self.gui
        return gui._run_project_overview if self.kind == "project" else gui._run_staff_overview

    def infos(self):
        return [d for d in self.dialogs if d[0] == "showinfo"]

    def run_again(self):
        """(変更点5) 前回の実行が終わった後にもう一度押すと、「実行中」で拒否されず最後まで動く (フラグが戻っている)。"""
        finals = lambda: sum(1 for t, _ in self.statuses if t.startswith(FINAL_PREFIXES))      # noqa: E731
        n_final, n_info = finals(), len(self.infos())
        n_fetch = sum(1 for e in self.events if e.startswith("fetch:"))
        with contextlib.redirect_stdout(self.printed):
            self.gui.root.after(0, self.entry())
            ok = self.pump(lambda: finals() > n_final, timeout=10)
            self.pump(lambda: not self.worker_threads(), timeout=5)
            self.settle(0.05)
        self.assertTrue(ok, "2回目の実行が最後まで動かない")
        self.assertEqual(len(self.infos()), n_info, "前回の実行が終わった後なのに「実行中」で拒否された")
        self.assertGreater(sum(1 for e in self.events if e.startswith("fetch:")), n_fetch)
        self.assertFalse(getattr(self.gui, FLAG[self.kind]))

    # ---- 読み出し ----
    def final(self):
        finals = [t for t, _ in self.statuses if t.startswith(FINAL_PREFIXES)]
        return finals[-1] if finals else None

    def estimate(self):
        self.assertTrue(self.calls["estimate"], "estimate_overview_cost が呼ばれていない")
        return self.calls["estimate"][0][2]

    def confirm_dialogs(self):
        return [d for d in self.dialogs if d[0] == "askyesno"]

    def errors(self):
        return [d for d in self.dialogs if d[0] == "showerror"]

    @staticmethod
    def message(entry):
        _n, args, kwargs = entry
        return args[1] if len(args) > 1 else kwargs.get("message", "")


def pmails(name, n_threads, body="本文", n_mails=1):
    return [mail(body, cid=f"{name}-t{i}") for i in range(n_threads) for _ in range(n_mails)]


def yen_re(text, head):
    m = re.search(re.escape(head) + r"約(\d+(?:\.\d+)?)円", text)
    return float(m.group(1)) if m else None


class OverviewFlowTests:
    """プロジェクト俯瞰・スタッフ俯瞰で共通の流れのテスト (KIND と TARGETS を派生クラスで決める)。"""

    KIND = None
    TARGETS = ()
    BIG_LOG = None      # 100円以上になる実績ログ (1対象・1スレッド)

    def mails(self, empty=()):
        return {t: ([] if t in empty else pmails(t, 2)) for t in self.TARGETS}

    def test_fetch_all_targets_first_then_estimate_then_ai_in_target_order(self):
        """取得は全対象を先に → 見積り → AI (targets の順)。メールなしの対象は AI なしのダミー。"""
        empty = (self.TARGETS[1],)
        self.run_flow(self.KIND, self.TARGETS, self.mails(empty))
        ev = [e for e in self.events if e.startswith(("fetch:", "ai:", "estimate"))]
        last_fetch = max(i for i, e in enumerate(ev) if e.startswith("fetch:"))
        first_ai = min(i for i, e in enumerate(ev) if e.startswith("ai:"))
        self.assertLess(last_fetch, ev.index("estimate"))
        self.assertLess(ev.index("estimate"), first_ai)
        ai = [e[3:] for e in ev if e.startswith("ai:")]
        self.assertEqual(ai, [t for t in self.TARGETS if t not in empty])
        summaries = self.reporter.calls[0]["summaries"]
        self.assertEqual(list(summaries), list(self.TARGETS))
        self.assertEqual(set(self.reporter.calls[0]["orig"]), set(self.TARGETS) - set(empty))
        dummy = summaries[self.TARGETS[1]]
        if self.KIND == "project":
            self.assertEqual(dummy["staff_status"][0]["text"], "指定期間のメールはありません。")
        else:
            self.assertEqual(dummy, {"project_status": [], "project_highlights": [{"text": "メールなし"}], "threads": []})

    def test_estimate_arguments(self):
        """estimate_overview_cost(kind, all_orig_threads, self.project_knowledge, config の gemini_model)。"""
        self.run_flow(self.KIND, self.TARGETS, self.mails(), )
        args, kwargs, _ = self.calls["estimate"][0]
        bound = inspect.signature(self.reals["estimate"]).bind(*args, **kwargs).arguments
        self.assertEqual(bound["kind"], self.KIND)
        self.assertEqual(set(bound["per_target_threads"]), set(self.TARGETS))
        self.assertEqual(bound.get("model"), self.gui.config.get("gemini_model"))
        self.assertIs(bound["knowledge"], self.gui.project_knowledge)

    def test_under_100_yen_runs_without_confirmation(self):
        """100円未満は確認なしで実行する。"""
        self.run_flow(self.KIND, self.TARGETS[:1], self.mails())
        self.assertLess(self.estimate()["yen"], 100)
        self.assertEqual(self.confirm_dialogs(), [])
        self.assertEqual([e for e in self.events if e.startswith("ai:")], [f"ai:{self.TARGETS[0]}"])

    def test_100_yen_or_more_asks_and_yes_runs(self):
        """100円以上は AI の前に確認ダイアログ (本文「…俯瞰のAI費用の見込み: 約N円」)。Yes なら従来どおり生成。"""
        self.run_flow(self.KIND, self.TARGETS[:1], self.mails(), log=self.BIG_LOG, ask=True)
        e = self.estimate()
        self.assertGreaterEqual(e["yen"], 100)
        dlg = self.confirm_dialogs()
        self.assertEqual(len(dlg), 1)
        self.assertTrue(self.message(dlg[0]).startswith(f"{LABEL[self.KIND]}のAI費用の見込み: 約{e['yen']:.0f}円"
                                                        f"（{e['n_calls']}件。"), self.message(dlg[0]))   # 件数は見積り(上限)
        self.assertLess(self.events.index("confirm_dialog"), self.events.index(f"ai:{self.TARGETS[0]}"))
        self.assertTrue(self.final().startswith("✅ 完了"))
        self.assertTrue(os.path.exists(LAST_RESULT[self.KIND]))

    def test_no_cancels_everything(self):
        """No: AIなし・ナレッジ保存なし・HTMLなし・ブラウザなし・last_result なし・キャッシュ不変・実績ログなし。"""
        put_cache(self.KIND, self.TARGETS[0], {"old": (1, False)})
        before_cache = read_bytes(cache_path(self.KIND, self.TARGETS[0]))
        self.run_flow(self.KIND, self.TARGETS[:1], self.mails(), log=self.BIG_LOG, ask=False)
        self.assertEqual(len(self.confirm_dialogs()), 1)
        self.assertEqual([e for e in self.events if e.startswith("ai:") or e in ("report", "browser", "record")], [])
        self.assertEqual(self.calls["save_knowledge"], [])
        self.assertEqual(self.browser_calls, [])
        self.assertFalse(os.path.exists(LAST_RESULT[self.KIND]))
        self.assertFalse(os.path.exists(KNOWLEDGE_PATH))
        self.assertEqual(read_bytes(cache_path(self.KIND, self.TARGETS[0])), before_cache)
        self.assertEqual(len(read_log_records()), 1)
        self.assertEqual(self.final(), CANCELLED)
        self.assertEqual(self.errors(), [])
        btn = self.gui.btn_reformat_project if self.KIND == "project" else self.gui.btn_reformat_staff
        self.assertEqual(str(btn.cget("state")), "disabled")              # 保存結果が無いので再生成ボタンは有効化しない
        self.run_again()                                                   # (変更点5) 中止の経路でもフラグが戻る

    def test_unread_only_keeps_emptied_targets_and_needs_no_new_analysis(self):
        """未読のみで空になった対象も all_orig_threads に入る (従来どおり)。見積りは0件 →「新しい解析は不要でした」。"""
        self.run_flow(self.KIND, self.TARGETS[:2], self.mails(), unread_only=True)
        self.assertEqual(self.estimate()["n_calls"], 0)
        self.assertEqual(self.reporter.calls[0]["orig"], {t: {} for t in self.TARGETS[:2]})
        self.assertEqual(self.final(), "✅ 完了（新しい解析は不要でした）")
        self.assertEqual(self.confirm_dialogs(), [])

    def test_success_records_usage_and_shows_cost(self):
        """成功: 実績ログ (feature=kind・n_calls=見積りの件数・今回のトークン) と「✅ 完了（今回のAI費用 約X円・N件）」。"""
        self.run_flow(self.KIND, self.TARGETS[:2], self.mails(), add_in=200000, add_out=30000)
        e = self.estimate()
        n = e["n_calls_s1"] + 2                          # (変更点4) 実回数 = Stage1 + Stage2 が走った対象の数 (2対象とも有効)
        recs = read_log_records()
        self.assertEqual(len(recs), 1)
        self.assertEqual((recs[0]["feature"], recs[0]["n_calls"]), (self.KIND, n))
        self.assertEqual((recs[0]["input_tokens"], recs[0]["output_tokens"]), (400000, 60000))
        yen = oto().calc_api_cost_yen(400000, 60000, FLASH)
        self.assertEqual(recs[0]["model"], FLASH)
        self.assertAlmostEqual(recs[0]["yen"], yen, places=2)
        final = self.final()
        self.assertTrue(final.startswith("✅ 完了（今回のAI費用 約"), final)
        self.assertTrue(final.endswith(f"円・{n}件）"), final)
        self.assertAlmostEqual(yen_re(final, "（今回のAI費用 "), yen, delta=0.051 if "." in final else 0.5)
        self.assertEqual(self.reporter.calls[0]["ti"], 400000)            # A2: 開始時に今回分へリセット
        self.run_again()                                                   # (変更点5) 成功の経路でもフラグが戻る

    def test_final_status_is_set_on_the_main_thread(self):
        """終了表示はメインスレッドで設定される。"""
        self.run_flow(self.KIND, self.TARGETS[:1], self.mails())
        finals = [(t, main) for t, main in self.statuses if t.startswith(FINAL_PREFIXES)]
        self.assertTrue(finals and all(main for _, main in finals), finals)

    def test_ai_failures_are_not_recorded_and_shown(self):
        """AI失敗あり: 実績ログは成功件数だけ、表示は「⚠ 完了（AI失敗N件。…）（今回のAI費用 約X円・成功M/N件）」。"""
        t0 = self.TARGETS[0]
        self.run_flow(self.KIND, self.TARGETS[:1], self.mails(), fail_cids={f"{t0}-t0"}, add_in=100, add_out=10)
        e = self.estimate()
        n = e["n_calls_s1"] + 1                          # 1件は有効なので Stage2 は走る
        recs = read_log_records()
        self.assertEqual([r["n_calls"] for r in recs], [n - 1])
        final = self.final()
        self.assertTrue(final.startswith("⚠ 完了（AI失敗1件。もう一度実行すると再試行）（今回のAI費用 約"), final)
        self.assertTrue(final.endswith(f"円・成功{n - 1}/{n}件）"), final)

    def test_all_stage1_failed_does_not_count_stage2(self):
        """(変更点4) Stage1 が全部失敗して Stage2 が走らない対象は、分母に Stage2 を含めない。成功0件なので実績ログも書かない。"""
        t0 = self.TARGETS[0]
        self.run_flow(self.KIND, self.TARGETS[:1], self.mails(), fail_cids={f"{t0}-t0", f"{t0}-t1"}, add_in=100, add_out=10)
        e = self.estimate()
        self.assertEqual((e["n_calls_s1"], e["n_calls_s2"]), (2, 1))
        self.assertEqual(read_log_records(), [])
        final = self.final()
        self.assertTrue(final.startswith("⚠ 完了（AI失敗2件。もう一度実行すると再試行）（今回のAI費用 約"), final)
        self.assertTrue(final.endswith("円・成功0/2件）"), final)

    def test_partly_failed_targets_count_only_the_stage2_that_ran(self):
        """(変更点4) 2対象のうち1対象だけ Stage1 が全部失敗: 実回数 = Stage1 4 + Stage2 1 = 5、成功 3。"""
        t0, t1 = self.TARGETS[0], self.TARGETS[1]
        self.run_flow(self.KIND, self.TARGETS[:2], self.mails(), fail_cids={f"{t0}-t0", f"{t0}-t1"}, add_in=100, add_out=10)
        self.assertEqual([r["n_calls"] for r in read_log_records()], [3])
        self.assertTrue(self.final().endswith("円・成功3/5件）"), self.final())

    def test_zero_output_is_not_recorded(self):
        """出力トークンが0なら実績ログを書かない。"""
        self.run_flow(self.KIND, self.TARGETS[:1], self.mails(), add_in=100, add_out=0)
        self.assertEqual(read_log_records(), [])

    def test_no_mail_at_all_means_no_new_analysis(self):
        """全対象メールなし: AI なし・確認なし・実績ログなし・「✅ 完了（新しい解析は不要でした）」。"""
        self.run_flow(self.KIND, self.TARGETS[:2], self.mails(empty=self.TARGETS[:2]))
        self.assertEqual([e for e in self.events if e.startswith("ai:")], [])
        self.assertEqual(self.final(), "✅ 完了（新しい解析は不要でした）")
        self.assertEqual(read_log_records(), [])
        self.assertEqual(self.confirm_dialogs(), [])

    def test_html_failure_keeps_generation_failed(self):
        """HTML書き出し失敗: 「❌ 生成失敗」のまま (プロジェクトは従来のエラーダイアログ)・ブラウザなし。"""
        self.run_flow(self.KIND, self.TARGETS[:1], self.mails(), report_path="")
        self.assertEqual(self.final(), "❌ 生成失敗")
        self.assertFalse(any(t.startswith(("✅", "⚠")) for t, _ in self.statuses))
        msgs = [self.message(d) for d in self.errors()]
        if self.KIND == "project":
            self.assertEqual(msgs, ["HTMLファイルの書き出しに失敗しました。"])
        else:
            self.assertEqual(msgs, [])
        self.assertEqual(self.browser_calls, [])
        self.run_again()                                                   # (変更点5) HTML失敗の経路でもフラグが戻る

    def test_ai_exception_shows_dialog_and_partial_cost(self):
        """AI の例外: エラーダイアログ「型名: メッセージ」・「❌ 失敗しました: …（ここまでのAI費用 約X円）」・保存/レポートなし。"""
        err = RuntimeError("AIが落ちました")
        self.run_flow(self.KIND, self.TARGETS[:2], self.mails(), raise_on=self.TARGETS[1], error=err,
                      add_in=300000, add_out=40000)
        msgs = [self.message(d) for d in self.errors()]
        self.assertEqual(len(msgs), 1)
        self.assertIn("RuntimeError: AIが落ちました", msgs[0])
        final = self.final()
        self.assertTrue(final.startswith("❌ 失敗しました（ここまでのAI費用 約"), final)            # (変更点6) 費用を先頭寄りに
        self.assertTrue(final.endswith("円）: RuntimeError: AIが落ちました"), final)
        yen = oto().calc_api_cost_yen(600000, 80000, FLASH)
        self.assertAlmostEqual(yen_re(final, "（ここまでのAI費用 "), yen, delta=0.051 if "." in final else 0.5)
        self.assertEqual(self.calls["save_knowledge"], [])
        self.assertEqual(self.reporter.calls, [])
        self.run_again()                                                   # (変更点5) 失敗の経路でもフラグが戻る

    def test_fetch_exception_shows_dialog_without_cost(self):
        """取得の例外: エラーダイアログ・「❌ 失敗しました: 型名: メッセージ」(費用0なので費用の注記なし)・AI なし。"""
        err = LookupError("取得できません")
        self.run_flow(self.KIND, self.TARGETS[:1], self.mails(), fetch_error=err)
        msgs = [self.message(d) for d in self.errors()]
        self.assertEqual(len(msgs), 1)
        self.assertIn("LookupError: 取得できません", msgs[0])
        self.assertEqual(self.final(), "❌ 失敗しました: LookupError: 取得できません")
        self.assertEqual([e for e in self.events if e.startswith("ai:")], [])
        self.run_again()

    def test_report_exception_shows_dialog_and_cost_so_far(self):
        """レポート生成の例外も task() 全体の try で捕まえる: エラーダイアログ・「❌ 失敗しました: …（ここまでのAI費用 約X円）」。"""
        self.run_flow(self.KIND, self.TARGETS[:1], self.mails(), report_fail=OSError("書けません"),
                      add_in=500000, add_out=50000)
        msgs = [self.message(d) for d in self.errors()]
        self.assertEqual(len(msgs), 1)
        self.assertIn("OSError: 書けません", msgs[0])
        final = self.final()
        self.assertTrue(final.startswith("❌ 失敗しました（ここまでのAI費用 約"), final)
        self.assertTrue(final.endswith("円）: OSError: 書けません"), final)
        self.assertAlmostEqual(yen_re(final, "（ここまでのAI費用 "), oto().calc_api_cost_yen(500000, 50000, FLASH),
                               delta=0.051 if "." in final else 0.5)
        self.assertEqual(self.browser_calls, [])

    def test_second_press_while_running_shows_info_and_does_nothing(self):
        """(変更点5) 実行中にもう一度押すと showinfo("実行中", …) を出して何もしない (取得・ワーカー・トークンのリセットなし)。"""
        gui = self.build(self.KIND, self.TARGETS[:1], self.mails())
        self.summ.gate, self.summ.started = threading.Event(), threading.Event()
        self.addCleanup(self.summ.gate.set)
        self.gui = gui
        with contextlib.redirect_stdout(self.printed):
            gui.root.after(0, self.entry(gui))
            self.assertTrue(self.pump(lambda: self.summ.started.is_set(), timeout=10), self.events)
            self.assertTrue(getattr(gui, FLAG[self.KIND]))
            workers = set(self.worker_threads())
            n_fetch = sum(1 for e in self.events if e.startswith("fetch:"))
            gui.summarizer.total_input_tokens, gui.summarizer.total_output_tokens = 111, 222
            # (第2回 M1) 2回目は、ナレッジの読み直し (load_project_knowledge)・self.project_knowledge の差し替え・
            # 対象の入力 (チェック・ドロップダウン・期間など) の読み取りをしない。入力は変えておく (スタッフ名の変更など)
            reads, loads = [], []
            originals = {n: getattr(gui, n) for n in INPUT_VARS[self.KIND]}
            for n, v in originals.items():
                setattr(gui, n, SpyVar(v, reads, n))
            if self.KIND == "staff":
                originals["var_staff_name"].set("Zed")
                originals["var_sm_najib"].set(True)
            else:
                originals["var_proj_r19projects"].set(True)
            knowledge_before = gui.project_knowledge
            real_load = oto().load_project_knowledge
            with mock.patch.object(oto(), "load_project_knowledge",
                                   lambda *a, **k: (loads.append(1), real_load(*a, **k))[1]):
                self.entry(gui)()                                          # 2回目 (メインスレッド)
            self.assertEqual(loads, [], "実行中の2回目で load_project_knowledge が呼ばれた")
            self.assertIs(gui.project_knowledge, knowledge_before, "実行中の2回目で self.project_knowledge が差し替えられた")
            self.assertEqual(reads, [], f"実行中の2回目で対象の入力を読んだ: {reads}")
            for n, v in originals.items():
                setattr(gui, n, v)
            self.settle(0.05)
            infos = self.infos()
            self.assertEqual(len(infos), 1)
            _n, args, kwargs = infos[0]
            title = args[0] if args else kwargs.get("title")
            msg = args[1] if len(args) > 1 else kwargs.get("message")
            self.assertEqual((title, msg), ("実行中", BUSY_MSG[self.KIND]))
            self.assertEqual(set(self.worker_threads()) - workers, set())
            self.assertEqual(sum(1 for e in self.events if e.startswith("fetch:")), n_fetch)
            self.assertEqual((gui.summarizer.total_input_tokens, gui.summarizer.total_output_tokens), (111, 222))
            self.summ.gate.set()
            self.assertTrue(self.pump(lambda: any(t.startswith(FINAL_PREFIXES) for t, _ in self.statuses), timeout=10))
            self.pump(lambda: not self.worker_threads(), timeout=5)
            self.settle(0.05)
        self.assertEqual(len([e for e in self.events if e.startswith("ai:")]), 1)
        self.assertFalse(getattr(gui, FLAG[self.KIND]))
        self.assertTrue(self.final().startswith("✅ 完了"), self.final())
        with open(KNOWLEDGE_PATH, encoding="utf-8") as f:                 # 実行中の処理の経緯が消えていない
            saved = json.load(f)
        self.assertEqual(saved[section(self.KIND)][self.TARGETS[0]]["history_summary"], f"H-{self.TARGETS[0]}")
        self.assertIs(gui.project_knowledge, knowledge_before)
        self.assertEqual(gui.project_knowledge[section(self.KIND)][self.TARGETS[0]]["history_summary"], f"H-{self.TARGETS[0]}")

    def test_no_target_warning_does_not_set_the_flag(self):
        """(変更点5) 対象なしの警告で戻るときはフラグを立てない。その後、対象を選べば普通に動く。"""
        gui = self.build(self.KIND, (), {})
        self.gui = gui
        self.entry(gui)()
        self.assertEqual(len([d for d in self.dialogs if d[0] == "showwarning"]), 1)
        self.assertFalse(getattr(gui, FLAG[self.KIND], False))
        self.assertEqual(self.worker_threads(), [])
        self.assertEqual((gui.summarizer.total_input_tokens, gui.summarizer.total_output_tokens), (7777, 8888))  # (fix2) 変えない
        getattr(gui, PROJECT_VARS[0] if self.KIND == "project" else STAFF_VARS[0]).set(True)
        gui.outlook.mails = {PROJECTS[0]: pmails(PROJECTS[0], 1), STAFFS[0]: pmails(STAFFS[0], 1)}
        self.run_again()

    # ---- (fix2) トークン集計のリセット位置 ----
    def test_fix2_cancel_keeps_the_previous_totals(self):
        """(fix2-1) 開始時にはリセットしない: 前回までの集計 111/222 は、費用の確認で「いいえ」でもそのまま。"""
        self.run_flow(self.KIND, self.TARGETS[:1], self.mails(), log=self.BIG_LOG, ask=False, initial_totals=(111, 222))
        self.assertEqual(self.final(), CANCELLED)
        self.assertEqual(self.totals(), (111, 222))
        self.assertEqual(self.confirm_totals, [(111, 222)])
        self.assertNotIn("reset:in", self.events)
        self.assertNotIn("reset:out", self.events)

    def test_fix2_failure_before_the_ai_keeps_totals_and_shows_no_cost(self):
        """(fix2-2) 確認より前の失敗 (取得中の例外): 集計はそのまま・「ここまでのAI費用」を添えない (前の実行の分を出さない)。"""
        self.run_flow(self.KIND, self.TARGETS[:1], self.mails(), fetch_error=LookupError("取得できません"),
                      initial_totals=(5_000_000, 1_000_000))
        self.assertEqual(self.final(), "❌ 失敗しました: LookupError: 取得できません")
        self.assertEqual(self.totals(), (5_000_000, 1_000_000))
        self.assertNotIn("reset:in", self.events)
        self.assertEqual([o.get("ai_started") for o in self.outcomes], [False])

    def test_fix2_failure_after_the_ai_started_shows_only_this_runs_cost(self):
        """(fix2-3) AI の後の失敗: 「❌ 失敗しました（ここまでのAI費用 約X円）: …」。X は今回の分だけ (前回までの集計を含まない)。"""
        self.run_flow(self.KIND, self.TARGETS[:2], self.mails(), raise_on=self.TARGETS[1], error=RuntimeError("AIが落ちました"),
                      add_in=300000, add_out=40000, initial_totals=(5_000_000, 1_000_000))
        final = self.final()
        self.assertTrue(final.startswith("❌ 失敗しました（ここまでのAI費用 約"), final)
        self.assertTrue(final.endswith("円）: RuntimeError: AIが落ちました"), final)
        yen = oto().calc_api_cost_yen(600000, 80000, FLASH)
        self.assertAlmostEqual(yen_re(final, "（ここまでのAI費用 "), yen, delta=0.051 if "." in final else 0.5)
        self.assertEqual([o.get("ai_started") for o in self.outcomes], [True])

    def test_fix2_success_shows_reports_saves_and_logs_only_this_run(self):
        """(fix2-4) 成功時の表示・レポート・保存結果・実績ログは今回の1回分 (前回までの集計 500万/100万 が混ざらない)。"""
        self.run_flow(self.KIND, self.TARGETS[:2], self.mails(), add_in=200000, add_out=30000,
                      initial_totals=(5_000_000, 1_000_000))
        self.assertEqual((self.reporter.calls[0]["ti"], self.reporter.calls[0]["to"]), (400000, 60000))
        recs = read_log_records()
        self.assertEqual([(r["input_tokens"], r["output_tokens"]) for r in recs], [(400000, 60000)])
        with open(LAST_RESULT[self.KIND], encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual((saved["total_input"], saved["total_output"]), (400000, 60000))
        final = self.final()
        self.assertAlmostEqual(yen_re(final, "（今回のAI費用 "), oto().calc_api_cost_yen(400000, 60000, FLASH),
                               delta=0.051 if "." in final else 0.5)
        self.assertEqual(self.totals(), (400000, 60000))

    def test_fix2_zero_estimate_still_resets_before_the_ai_stage(self):
        """(fix2-4) 見積り0件 (確認なし) でも AI の段の前でリセットする: レポート・保存結果は 0/0。"""
        self.run_flow(self.KIND, self.TARGETS[:2], self.mails(empty=self.TARGETS[:2]), initial_totals=(5_000_000, 1_000_000))
        self.assertEqual(self.final(), "✅ 完了（新しい解析は不要でした）")
        self.assertEqual(self.estimate()["n_calls"], 0)
        self.assertEqual(self.confirm_dialogs(), [])
        self.assertIn("reset:in", self.events)
        self.assertIn("reset:out", self.events)
        self.assertEqual(self.totals(), (0, 0))
        self.assertEqual((self.reporter.calls[0]["ti"], self.reporter.calls[0]["to"]), (0, 0))
        with open(LAST_RESULT[self.KIND], encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual((saved["total_input"], saved["total_output"]), (0, 0))

    def test_fix2_reset_is_after_confirm_and_before_the_first_summarize(self):
        """(fix2-5) リセットは _confirm_ai_cost (100円以上の確認ダイアログ) の後・最初の summarize_* の前に1回だけ。"""
        self.run_flow(self.KIND, self.TARGETS[:2], self.mails(), log=self.BIG_LOG, ask=True, initial_totals=(111, 222))
        ev = self.events
        self.assertEqual((ev.count("reset:in"), ev.count("reset:out")), (1, 1))
        first_ai = min(i for i, e in enumerate(ev) if e.startswith("ai:"))
        for tag in ("reset:in", "reset:out"):
            with self.subTest(tag=tag):
                self.assertLess(ev.index("confirm"), ev.index(tag))
                self.assertLess(ev.index("confirm_dialog"), ev.index(tag))
                self.assertLess(ev.index(tag), first_ai)
        self.assertEqual(self.confirm_totals, [(111, 222)])
        self.assertEqual(self.summ.entry_totals[0], (0, 0))

    def test_fix2_finish_status_depends_on_ai_started(self):
        """(fix2-5) 同じ失敗の outcome で ai_started だけを変えて _finish_overview_status を呼ぶと、偽なら費用を添えない・真なら添える。"""
        self.run_flow(self.KIND, self.TARGETS[:1], self.mails(), raise_on=self.TARGETS[0], error=RuntimeError("落ちた"),
                      add_in=300000, add_out=40000)
        outcome = self.outcomes[-1]
        self.assertTrue(outcome.get("ai_started"))
        for started, has_cost in ((False, False), (True, True)):
            with self.subTest(ai_started=started):
                n = len(self.statuses)
                self.gui._finish_overview_status(dict(outcome, ai_started=started))
                self.settle(0.05)
                texts = [t for t, _ in self.statuses[n:] if t.startswith("❌ 失敗しました")]
                self.assertEqual(len(texts), 1, self.statuses[n:])
                if has_cost:
                    self.assertTrue(texts[0].startswith("❌ 失敗しました（ここまでのAI費用 約"), texts[0])
                    self.assertTrue(texts[0].endswith("円）: RuntimeError: 落ちた"), texts[0])
                else:
                    self.assertEqual(texts[0], "❌ 失敗しました: RuntimeError: 落ちた")

    def test_knowledge_history_is_updated_and_saved(self):
        """ナレッジの history_summary が対象ごとに更新・保存される (従来どおり)。"""
        self.run_flow(self.KIND, self.TARGETS[:2], self.mails())
        with open(KNOWLEDGE_PATH, encoding="utf-8") as f:
            saved = json.load(f)
        for t in self.TARGETS[:2]:
            self.assertEqual(saved[section(self.KIND)][t]["history_summary"], f"H-{t}")


class TestProjectOverviewFlow(OverviewFlowTests, OverviewCase):
    KIND = "project"
    TARGETS = PROJECTS
    BIG_LOG = [rec("project", 1, 100000)]


class TestStaffOverviewFlow(OverviewFlowTests, OverviewCase):
    KIND = "staff"
    TARGETS = ("Taizo", "Nakai", "Oi", "Najib")
    BIG_LOG = [rec("staff", 1, 200000)]

    def test_no_involvement_filter_warning_does_not_set_the_flag(self):
        """(変更点5) 関与フィルターなしの警告で戻るときはフラグを立てない。"""
        gui = self.build("staff", ("Saji",), {"Saji": pmails("Saji", 1)})
        gui.var_staff_from.set(False)
        gui.var_staff_to.set(False)
        gui.var_staff_cc.set(False)
        self.gui = gui
        gui._run_staff_overview()
        self.assertEqual(len([d for d in self.dialogs if d[0] == "showwarning"]), 1)
        self.assertFalse(getattr(gui, FLAG["staff"], False))
        self.assertEqual(self.worker_threads(), [])

    def test_staff_name_candidates_are_updated(self):
        """スタッフ名の候補 (cb_staff_name) が更新される (従来どおり)。"""
        self.run_flow(self.KIND, self.TARGETS[:2], self.mails())
        self.assertEqual(set(self.gui.cb_staff_name.cget("values")) >= set(self.TARGETS[:2]), True)


class SpecGapErrorCut:
    """(SpecGap) 「{型名: メッセージの先頭80字}」は「型名: メッセージ」全体の先頭80字と解釈 (メッセージだけの80字とも読める)。"""

    def test_long_error_message_is_cut_at_80(self):
        """長い例外文は「型名: メッセージ」の先頭80字で表示する。"""
        err = RuntimeError("あ" * 200)
        self.run_flow(self.KIND, self.TARGETS[:1], self.mails(), raise_on=self.TARGETS[0], error=err, add_in=0, add_out=0)
        self.assertEqual(self.final(), "❌ 失敗しました: " + ("RuntimeError: " + "あ" * 200)[:80])


class TestSpecGapOverviewDialogs(OverviewCase):
    """(SpecGap) 仕様に明記の無い細部を自然な解釈で確かめる。
    - エラーダイアログは (Tk の制約上) メインスレッドで出す。
    - スタッフの検索 (search_mails_fast) の例外は従来どおり取得部分の中で握りつぶし (Search Error を print)、
      その対象は「メールなし」のダミーになる (全体の失敗にはしない)。"""

    KIND, TARGETS = "project", PROJECTS
    mails = OverviewFlowTests.mails

    def test_error_dialog_is_shown_on_the_main_thread(self):
        """取得の例外のエラーダイアログはメインスレッドで出る。"""
        self.run_flow("project", PROJECTS[:1], self.mails(), fetch_error=LookupError("x"))
        self.assertEqual(self.dialog_threads, [("showerror", True)])

    def test_staff_search_error_is_swallowed_like_before(self):
        """スタッフの検索の例外は従来どおり握りつぶし、その対象はメールなしのダミーで完了する。"""
        gui = self.build("staff", ("Saji",), {"Saji": pmails("Saji", 1)})
        gui.outlook.search_error = RuntimeError("検索失敗")
        with contextlib.redirect_stdout(self.printed):
            gui.root.after(0, gui._run_staff_overview)
            self.assertTrue(self.pump(lambda: any(t.startswith(FINAL_PREFIXES) for t, _ in self.statuses), timeout=10))
            self.pump(lambda: not self.worker_threads(), timeout=5)
            self.settle(0.05)
        self.gui = gui
        self.assertEqual(self.errors(), [])
        self.assertEqual(self.reporter.calls[0]["summaries"]["Saji"],
                         {"project_status": [], "project_highlights": [{"text": "メールなし"}], "threads": []})
        self.assertEqual(self.final(), "✅ 完了（新しい解析は不要でした）")


class TestSpecGapProjectErrorCut(SpecGapErrorCut, OverviewCase):
    KIND, TARGETS = "project", PROJECTS
    mails = OverviewFlowTests.mails


class TestSpecGapStaffErrorCut(SpecGapErrorCut, OverviewCase):
    KIND, TARGETS = "staff", ("Taizo", "Nakai")
    mails = OverviewFlowTests.mails


# ============================================================
# 4. 範囲ガード (_06 → _07)
# ============================================================
OLD_REV = "outlook_total_organizer_20261004_06.py"
NEW_REV = "outlook_total_organizer_20261004_07.py"
ALLOWED_TO_CHANGE = {"MailManagerGUI._run_project_overview", "MailManagerGUI._run_staff_overview"}
NEW_METHOD = "MailManagerGUI._finish_overview_status"


def _is_docstring(node):
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)


@functools.lru_cache(maxsize=None)
def _parse(path):
    with open(path, "r", encoding="utf-8") as f:
        return ast.parse(f.read())


def _index_source(path):
    funcs, consts, others, shells, order = {}, {}, [], {}, {}
    for i, node in enumerate(_parse(path).body):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs[node.name] = ast.dump(node)
            order[node.name] = i
        elif isinstance(node, ast.ClassDef):
            rest = []
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    funcs[f"{node.name}.{sub.name}"] = ast.dump(sub)
                elif not _is_docstring(sub):
                    rest.append(ast.dump(sub))
            shells[node.name] = rest
            order[node.name] = i
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            for t in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                if isinstance(t, ast.Name):
                    consts[t.id] = ast.dump(node)
                    order[t.id] = i
        elif not _is_docstring(node):
            others.append(ast.dump(node))
    return funcs, consts, others, shells, order


class TestScopeGuardA7b(unittest.TestCase):
    """変更してよい既存メソッドは2つだけ。追加は仕様の名前だけ。削除なし。"""

    @classmethod
    def setUpClass(cls):
        cls.baseline = _loader.rev_path(OLD_REV)
        cls.target = _loader.rev_path(NEW_REV)
        if not (os.path.isfile(cls.baseline) and os.path.isfile(cls.target)):
            raise unittest.SkipTest("A7b のリビジョン対が無い")
        cls.old = _index_source(cls.baseline)
        cls.new = _index_source(cls.target)

    def test_nothing_removed(self):
        """既存の関数・メソッド・定数が消えていない。"""
        self.assertEqual(sorted(set(self.old[0]) - set(self.new[0])), [])
        self.assertEqual(sorted(set(self.old[1]) - set(self.new[1])), [])

    def test_only_the_two_methods_changed(self):
        """既存のうち変わったのは _run_project_overview / _run_staff_overview だけ (定数・他の文・クラスの骨格も不変)。"""
        changed = sorted(n for n, s in self.old[0].items() if self.new[0].get(n, s) != s)
        self.assertEqual(changed, sorted(ALLOWED_TO_CHANGE))
        changed_c = sorted(n for n, s in self.old[1].items() if self.new[1].get(n, s) != s)
        self.assertEqual(changed_c, [])
        self.assertEqual(self.old[2], self.new[2])
        self.assertEqual(self.old[3], self.new[3])

    def test_only_the_spec_names_are_added(self):
        """追加は仕様の定数11個・補助4関数・estimate_overview_cost・count_failed_overview_threads・_finish_overview_status だけ。"""
        self.assertEqual(sorted(set(self.new[0]) - set(self.old[0])), sorted(NEW_FUNCTIONS + (NEW_METHOD,)))
        self.assertEqual(sorted(set(self.new[1]) - set(self.old[1])), sorted(SPEC_CONSTANTS))

    def test_new_block_sits_after_count_failed_review_calls_and_before_load_project_knowledge(self):
        """追加の定数・関数は count_failed_review_calls の後・load_project_knowledge の前にある。"""
        o = self.new[4]
        pos = sorted(o[n] for n in tuple(SPEC_CONSTANTS) + NEW_FUNCTIONS)
        self.assertGreater(pos[0], o["count_failed_review_calls"])
        self.assertLess(pos[-1], o["load_project_knowledge"])


if __name__ == "__main__":
    unittest.main()
