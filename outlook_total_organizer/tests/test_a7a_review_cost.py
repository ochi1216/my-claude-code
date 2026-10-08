# -*- coding: utf-8 -*-
"""A7a「振り返りタブ: AI費用の事前見積り・100円以上は確認・実績ログ・失敗/中止の表示の修正」テスト (仕様書 A7A_SPEC.md)。

仕様書だけを根拠に、実装 (_20261004_05.py の estimate_review_cost / 変更後の _run_review) を見ずに書いている。
  - 仕様に明記された挙動            -> 通常の TestCase
  - 仕様が曖昧/未記載で「最も自然な解釈」で書いたもの
                                    -> クラス名に SpecGap を含む (コメントに解釈を明記)
    SpecGap の失敗は「バグ」ではなく「仕様の確認が必要」の合図として扱う。

構成
  1. 定数 (REVIEW_ESTIMATE_* 12個)・シグネチャ
  2. estimate_review_cost (純関数): 呼び出し回数 / 形の変な入力 / 入力文字数 (通常・議事録・会議) / 実績ログの校正 /
     実績の下限 (追記: max(実績×1.5, 8000×0.5)) / 戻り値 / needs_confirm の境界 / 副作用なし・日付非依存 /
     定数が使われること / 独立した参照実装との一致
     count_failed_review_calls (純関数, 追記): 月別キャッシュの _error を数える (月×対象者・読めない/dictでない/空は数えない)
  3. _run_review の流れ (偽Outlook・偽AI・ダイアログのスタブ):
     見積りの位置と引数 / 0件 / 100円未満 / 100円以上の確認 (parent・default="no") / 中止 / 成功 /
     AI失敗がある実行 (追記: 実績ログは成功した呼び出しだけ・出力0は記録しない・「⚠ 振り返り生成は完了(…N件…)」) /
     失敗 (追記: エラーの文字列は「型名: 例外文」) / 変えていないこと / 本物の MailSummarizer (偽AI) と
     本物のレポート生成を通す統合
  4. 範囲ガード (_20261004_04.py と _20261004_05.py の AST 比較。変更してよい既存メソッドは _run_review だけ。
     追加してよい名前は REVIEW_ESTIMATE_* 12個・estimate_review_cost・count_failed_review_calls)

A3 の「（⚠ 未取得/AI失敗…）」通知の件数の数え方 (進行中の当月は未取得に数えない、など) は A3 の規則なので、ここでは
再定義せず、既存の review_cache_gaps を基準にして「通知が末尾に付くこと」だけを確かめる。

GUI テストは tkinter とディスプレイが無ければ自動 skip (Linux は xvfb-run -a /usr/bin/python3.12 tests/run_tests.py)。
ハーネスは A3 の ReviewGuiCase (本物の振り返りタブを組み立てる) と A1 の pump/settle (mainloop を回して待つ)、
A1.1 の方式 (テスト中は GC を止める・ダイアログがメインスレッドで出たか記録・呼び出し順の記録) を組み合わせている。
Outlook(COM)・AI・ネットワークには一切触れず、ブラウザ (webbrowser.open) も差し替えて実際には開かない。
費用の期待値は、既定モデル (gemini-2.5-flash: 入力0.30/出力2.50 USD/100万トークン, 1USD=160円。A2 で確定済み) から、
このファイル内の独立した計算 (yen_flash) で出す。日付・時刻に依存する期待値は作らない (固定日付だけを使う)。
実績ログ (json/ai_usage_log.jsonl) や設定は、必ず空の一時cwd の中で動かす (利用者の実データを拾わない)。

変異テスト (このテストが本当に誤りを見つけられるかの確認): 実装のコピーに誤りを1つ入れ、OTO_TARGET でその版を指して
このファイルだけを走らせる。
    OTO_TARGET=/path/to/壊した版.py xvfb-run -a /usr/bin/python3.12 tests/run_tests.py a7a_review_cost
(範囲ガードの章は常に tool フォルダの _04 / _05 を比べるので、変異版では変わらない)
"""
import ast
import contextlib
import copy
import functools
import gc
import inspect
import io
import json
import os
import random
import re
import threading
import time
import types
import unittest
import webbrowser                                  # noqa: F401  (mock.patch("webbrowser.open") の対象を先に読み込む)
from datetime import datetime
from unittest import mock

import _loader
import test_a1_gui_smoke as a1gui                  # pump / settle などの待機ヘルパを借りる
import test_a3_review_months as a3m                # 本物の振り返りタブを作る土台 (ReviewGuiCase) と固定日付を借りる
import test_a3_review_run as a3run                 # 偽Outlook / 偽AI (本物の MailSummarizer の AI 呼び出しだけ差し替え) を借りる
from _loader import read_bytes, read_json, snapshot_files, tempdir_cwd, write_bytes, write_json, write_text

tk, ttk, tkmessagebox = a1gui.tk, a1gui.ttk, a1gui.tkmessagebox


def oto():
    return _loader.load()


# ============================================================
# 共通の定数・ヘルパ
# ============================================================
FLASH = "gemini-2.5-flash"
PRO = "gemini-2.5-pro"
LOG_PATH = os.path.join("json", "ai_usage_log.jsonl")
LOG_KEYS = ["at", "feature", "n_calls", "input_tokens", "output_tokens", "yen", "model"]
AT_RE = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$"

SPEC_CONSTANTS = {
    "REVIEW_ESTIMATE_PROMPT_CHARS": 2100, "REVIEW_ESTIMATE_OUTPUT_TOKENS": 8000, "REVIEW_ESTIMATE_BODY_LIMIT": 800,
    "REVIEW_ESTIMATE_MAIL_OVERHEAD": 40, "REVIEW_ESTIMATE_THREAD_OVERHEAD": 200,
    "REVIEW_ESTIMATE_THREAD_CHARS_MAX": 8000, "REVIEW_ESTIMATE_TOTAL_CHARS_MAX": 60000,
    "REVIEW_ESTIMATE_MINUTES_BODY_LIMIT": 50000, "REVIEW_ESTIMATE_MEETING_LINES_MAX": 60,
    "REVIEW_ESTIMATE_MEETING_LINE_CHARS": 100, "REVIEW_ESTIMATE_SAFETY": 1.5,   # 追記2: 会議1行 40 → 100字
    "REVIEW_ESTIMATE_OUTPUT_FLOOR_RATIO": 0.5,                 # 追記: 実績から見積もるときの下限 = 既定の出力 8000 × 0.5
}
# 仕様の数値 (テストの式の中で使う。定数名ではなく値を直接書いて、実装の定数を信用しない)
PROMPT, OUT_DEFAULT = 2100, 8000
MEET = 100                                                   # 追記2: 会議1行あたりの字数 (旧40)

RUN_TEXT = "📈 振り返りを生成"
RUN_BUSY_TEXT = "⏳ 取得・分析中..."
REFORMAT_TEXT = "🎨 フォーマットのみ再生成"
START_STATUS = "📈 振り返りを生成中..."
DONE_TEXT = "✅ 振り返り生成完了"
NO_NEW_TEXT = "（新しい分析は不要でした）"
CANCELLED_STATUS = "⏹ 費用の確認で中止しました（AI分析は行っていません）"
FAIL_HEAD = "❌ 失敗しました: "
CONFIRM_TITLE = "AI費用の確認"
ESTIMATE_PRINT_HEAD = "💰 振り返りのAI費用の見込み"
REVIEW_LABEL = "振り返り"
WARN_HEAD = "⚠ 振り返り生成完了（AI失敗"                          # (追記2) AI分析に失敗した月×対象者があるときの完了表示の先頭
FINAL_PREFIXES = (DONE_TEXT, WARN_HEAD, "⏹ 費用の確認で中止しました", FAIL_HEAD.strip())


def yen_flash(input_tokens, output_tokens):
    """既定モデル (gemini-2.5-flash, 入力0.30/出力2.50 USD/100万トークン, 1USD=160円) の費用 (小数2桁)。"""
    return round((input_tokens / 1_000_000 * 0.30 + output_tokens / 1_000_000 * 2.50) * 160, 2)


def yen_pro(input_tokens, output_tokens):
    """gemini-2.5-pro (入力1.25/出力10.00 USD/100万トークン) の費用 (小数2桁)。"""
    return round((input_tokens / 1_000_000 * 1.25 + output_tokens / 1_000_000 * 10.00) * 160, 2)


def cost_text(yen, n):
    return f"（今回のAI費用 約{yen:.1f}円・{n}件）"


def gap_note(missing=0, failed=0):
    parts = []
    if missing:
        parts.append(f"未取得{missing}か月")
    if failed:
        parts.append(f"AI失敗{failed}か月")
    return ("（⚠ " + "・".join(parts) + "あり。レポートの期間表示を確認してください）") if parts else ""


class InTempCwd(unittest.TestCase):
    """各テストを空の一時cwd で動かす (実際の config / 実績ログを拾わない・json/ を汚さない)。"""

    def setUp(self):
        cm = tempdir_cwd()
        self.tmp = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)


# ---- 実績ログ (json/ai_usage_log.jsonl) の読み書き -------------------------------------
def rec(feature="review", n_calls=1, output_tokens=1000, input_tokens=50000, yen=1.0, model=FLASH,
        at="2026-10-04T09:00:00", **extra):
    d = {"at": at, "feature": feature, "n_calls": n_calls, "input_tokens": input_tokens,
         "output_tokens": output_tokens, "yen": yen, "model": model}
    d.update(extra)
    return d


def write_log(*lines):
    parts = [ln if isinstance(ln, str) else json.dumps(ln, ensure_ascii=False) for ln in lines]
    write_text(LOG_PATH, "\n".join(parts) + ("\n" if parts else ""))


def read_log_records():
    if not os.path.exists(LOG_PATH):
        return []
    return [json.loads(line) for line in read_bytes(LOG_PATH).decode("utf-8").split("\n") if line.strip()]


# ---- 見積りの入力データの合成 (monthly_threads の形: {"YYYYMM": {対象者: {conv_id: スレッド}}}) ----------
def mail(body="", **kw):
    d = {"body": body, "subject": "件名", "conversation_topic": "件名", "sender_email": "ochi@example.com",
         "sender_name": "Ochi"}
    d.update(kw)
    return d


def thr(*bodies, **kw):
    """通常スレッド: {"mails": [{"body": ...}, ...], "topic": ...}。"""
    d = {"topic": "件名", "mails": [mail(b) for b in bodies]}
    d.update(kw)
    return d


def minutes_mail(body="", **kw):
    subject = f"{oto().REVIEW_MINUTES_SUBJECT_KEYWORD} 12"
    return mail(body, subject=subject, conversation_topic=subject, **kw)


def minutes_thr(*bodies, **kw):
    """Japan Site Weekly議事録 (件名に REVIEW_MINUTES_SUBJECT_KEYWORD を含む) のスレッド。"""
    d = {"topic": "議事録", "mails": [minutes_mail(b) for b in bodies]}
    d.update(kw)
    return d


def one(threads, person="Ochi", yyyymm="202609"):
    """1か月・1対象者の monthly_threads。threads は {conv_id: スレッド}。"""
    return {yyyymm: {person: threads}}


def single(thread, person="Ochi", yyyymm="202609"):
    return one({"conv-1": thread}, person, yyyymm)


def empty_threads(n):
    """メール0通のスレッド n 個 (1スレッド = 見出しの 200 字だけ)。"""
    return {f"conv-{i}": {"mails": []} for i in range(n)}


def calls_grid(n):
    """ちょうど n 個の (月, 対象者) の組を持つ monthly_threads (どの組も「メール0通のスレッド1つ」= AI 1回)。"""
    monthly = {}
    for i in range(n):
        monthly.setdefault(f"2026{i % 12 + 1:02d}", {})[f"P{i // 12}"] = {"conv": {"mails": []}}
    return monthly


def est(monthly_threads, monthly_meetings=None, model=None):
    return oto().estimate_review_cost(monthly_threads, {} if monthly_meetings is None else monthly_meetings, model)


# ---- 独立した参照実装 (仕様書の式をそのまま書いたもの) ---------------------------------------
def ref_thread_chars(thread):
    """1スレッドの文字数: 各通 min(len(str(body or "")), 上限)+40 の合計 (上限は通常800・議事録5万)。
    通常スレッドはさらに min(…, 8000) (議事録は上限なし)。そのスレッドに +200 (見出し)。
    議事録の判定は review_thread_is_minutes (例外が出たら通常扱い)。"""
    mails = thread.get("mails") if isinstance(thread, dict) else None
    try:
        minutes = bool(oto().review_thread_is_minutes(thread))
    except Exception:                                           # noqa: BLE001
        minutes = False
    limit = 50000 if minutes else 800
    total = sum(min(len(str(m.get("body") or "")), limit) + 40 for m in (mails or []) if isinstance(m, dict))
    if not minutes:
        total = min(total, 8000)
    return total + 200


def ref_estimate(monthly_threads, monthly_meetings):
    """(呼び出し回数, 入力文字数の合計)。月×対象者でスレッド辞書が空でないものだけ1回。
    1回 = min(Σスレッドの文字数, 60000) + 2100 + (Ochi で、その月の会議が list なら min(件数,60)×100 (追記2))。"""
    n_calls = chars = 0
    if not isinstance(monthly_threads, dict):
        return 0, 0
    for yyyymm, per_person in monthly_threads.items():
        if not isinstance(per_person, dict):
            continue
        for person, threads in per_person.items():
            if not isinstance(threads, dict) or not threads:
                continue
            n_calls += 1
            chars += min(sum(ref_thread_chars(t) for t in threads.values()), 60000) + 2100
            meetings = monthly_meetings.get(yyyymm) if isinstance(monthly_meetings, dict) else None
            if person == "Ochi" and isinstance(meetings, list):
                chars += min(len(meetings), 60) * MEET
    return n_calls, chars


# ============================================================
# 1. 定数・シグネチャ
# ============================================================
class TestConstantsAndSignature(InTempCwd):
    """新しい定数の値と、新しい関数の引数 (シグネチャ) が仕様どおりであること。
    (見積りは設定を読む際に json/ を作るので、必ず一時cwd の中で呼ぶ。実行フォルダに json/ を作らない)"""

    def test_new_constants_have_the_specified_values(self):
        """仕様の REVIEW_ESTIMATE_* 12個 (追記の REVIEW_ESTIMATE_OUTPUT_FLOOR_RATIO を含む) が、仕様どおりの値で定義されている。"""
        for name, value in SPEC_CONSTANTS.items():
            with self.subTest(name=name):
                self.assertTrue(hasattr(oto(), name), f"{name} が無い")
                self.assertEqual(getattr(oto(), name), value)

    def test_there_are_exactly_twelve_spec_constants(self):
        """(比較元の健全性) 仕様の定数は12個 (追記で REVIEW_ESTIMATE_OUTPUT_FLOOR_RATIO が加わった)。"""
        self.assertEqual(len(SPEC_CONSTANTS), 12)

    def test_estimate_review_cost_signature(self):
        """estimate_review_cost(monthly_threads, monthly_meetings, model=None) の引数が仕様どおり。"""
        sig = inspect.signature(oto().estimate_review_cost)
        self.assertEqual(list(sig.parameters), ["monthly_threads", "monthly_meetings", "model"])
        self.assertIsNone(sig.parameters["model"].default)

    def test_count_failed_review_calls_signature(self):
        """(追記) count_failed_review_calls(monthly_threads) の引数が仕様どおり。"""
        sig = inspect.signature(oto().count_failed_review_calls)
        self.assertEqual(list(sig.parameters), ["monthly_threads"])

    def test_count_failed_review_calls_is_a_module_level_function(self):
        """(追記) モジュール直下の関数 (メソッドではない)。"""
        self.assertTrue(inspect.isfunction(oto().count_failed_review_calls))
        self.assertFalse(hasattr(oto().MailManagerGUI, "count_failed_review_calls"))

    def test_estimate_review_cost_is_a_module_level_function(self):
        """モジュール直下の関数 (メソッドではない)。"""
        self.assertTrue(inspect.isfunction(oto().estimate_review_cost))
        self.assertFalse(hasattr(oto().MailManagerGUI, "estimate_review_cost"))

    def test_the_things_the_spec_relies_on_still_exist(self):
        """仕様が前提にする既存の名前 (議事録判定・キーワード・閾値・A1.1 の関数) が残っている。"""
        self.assertEqual(oto().REVIEW_MINUTES_SUBJECT_KEYWORD, "ICS R04 Japan R&D meeting - week")
        self.assertEqual(oto().COST_CONFIRM_THRESHOLD_YEN, 100)
        for name in ("review_thread_is_minutes", "estimate_ai_cost_yen", "observed_output_tokens_per_call",
                     "record_ai_usage", "calc_api_cost_yen", "estimate_action_analysis_cost", "review_cache_gaps",
                     "_review_person_cache_suffix"):
            with self.subTest(name=name):
                self.assertTrue(callable(getattr(oto(), name, None)))
        self.assertTrue(callable(getattr(oto().MailManagerGUI, "_confirm_ai_cost", None)))

    def test_keyword_and_positional_calls_both_work(self):
        """引数名 (monthly_threads, monthly_meetings, model) のキーワード指定でも、model を省略しても呼べる。"""
        data = single(thr("a"))
        a = oto().estimate_review_cost(monthly_threads=data, monthly_meetings={}, model=PRO)
        b = oto().estimate_review_cost(data, {})
        self.assertEqual((a["n_calls"], b["n_calls"]), (1, 1))


# ============================================================
# 2. estimate_review_cost (純関数)
# ============================================================
class TestEstimateCalls(InTempCwd):
    """AI呼び出しの回数 = (月, 対象者) の組のうち、スレッド辞書が空でないものの数。"""

    def test_one_month_one_person_is_one_call(self):
        """1か月・Ochi 1人で、スレッドがあれば1回。"""
        self.assertEqual(est(single(thr("a")))["n_calls"], 1)

    def test_many_threads_in_one_pair_are_still_one_call(self):
        """同じ (月, 対象者) の中にスレッドが何個あっても1回 (束ねて1回で呼ぶ)。"""
        self.assertEqual(est(one({f"c{i}": thr("a") for i in range(30)}))["n_calls"], 1)

    def test_months_times_persons(self):
        """3か月 × 3人 (全部スレッドあり) で9回。"""
        data = {f"2026{m:02d}": {p: {"c": thr("a")} for p in ("Ochi", "Saji", "Yuto Oi")} for m in (7, 8, 9)}
        self.assertEqual(est(data)["n_calls"], 9)

    def test_a_person_with_no_threads_in_a_month_is_not_counted(self):
        """その月・その対象者のスレッド辞書が空なら呼ばない (数えない)。"""
        data = {"202608": {"Ochi": {"c": thr("a")}, "Saji": {}}, "202609": {"Ochi": {}, "Saji": {"c": thr("a")}}}
        self.assertEqual(est(data)["n_calls"], 2)

    def test_empty_threads_everywhere_means_zero_calls(self):
        """どの組もスレッドが空なら0回・入力0文字・費用0円・確認不要。"""
        e = est({"202608": {"Ochi": {}, "Saji": {}}, "202609": {"Ochi": {}}})
        self.assertEqual((e["n_calls"], e["input_chars"], e["input_tokens"], e["output_tokens"]), (0, 0, 0, 0))
        self.assertEqual(e["yen"], 0)
        self.assertIs(e["needs_confirm"], False)

    def test_a_month_with_an_empty_person_dict_is_zero_calls(self):
        """月はあるが対象者の辞書が空 ({"202609": {}}) なら0回。"""
        self.assertEqual(est({"202609": {}})["n_calls"], 0)

    def test_empty_monthly_threads_is_zero_calls(self):
        """monthly_threads が空 ({}: チェックした月が無い = キャッシュだけで作る) なら0回。"""
        e = est({})
        self.assertEqual((e["n_calls"], e["input_chars"], e["yen"]), (0, 0, 0))
        self.assertIs(e["needs_confirm"], False)

    def test_the_number_of_threads_does_not_change_the_calls_only_the_chars(self):
        """スレッドを増やしても回数は同じで、入力文字数だけが増える。"""
        a, b = est(one(empty_threads(1))), est(one(empty_threads(5)))
        self.assertEqual((a["n_calls"], b["n_calls"]), (1, 1))
        self.assertEqual(b["input_chars"] - a["input_chars"], 4 * 200)

    def test_months_without_a_cache_are_counted_like_cached_ones(self):
        """見積りはキャッシュの有無を見ない (チェックした月は常に再分析): 実績ファイルや月別キャッシュがあっても回数は同じ。"""
        os.makedirs(oto().REVIEW_CACHE_DIR, exist_ok=True)
        write_json(os.path.join(oto().REVIEW_CACHE_DIR, "202609.json"), {"item_count": 1, "achievements": []})
        self.assertEqual(est(single(thr("a")))["n_calls"], 1)

    def test_calls_and_chars_are_ints(self):
        """n_calls と input_chars は int。"""
        e = est(calls_grid(3))
        self.assertIs(type(e["n_calls"]), int)
        self.assertIs(type(e["input_chars"]), int)


class TestEstimateMalformedInput(InTempCwd):
    """形の変な入力でも例外を出さず、仕様どおり数える。"""

    ZERO = {"n_calls": 0, "input_chars": 0, "input_tokens": 0, "output_tokens": 0, "yen": 0, "needs_confirm": False}

    def test_monthly_threads_that_is_not_a_dict_gives_zeros_without_an_error(self):
        """monthly_threads が None・list・文字列・数値などなら、全て0 (例外を出さない)。"""
        for label, bad in (("None", None), ("list", []), ("非空list", [1, 2]), ("str", "x"), ("int", 5), ("bool", True)):
            with self.subTest(monthly_threads=label):
                e = est(bad)
                for key, value in self.ZERO.items():
                    self.assertEqual(e[key], value, key)

    def test_a_month_whose_person_dict_is_not_a_dict_is_skipped(self):
        """対象者の辞書 (per_person) が dict でない月は飛ばし、他の月は数える。"""
        for label, bad in (("None", None), ("list", []), ("非空list", [{"c": thr("a")}]), ("str", "x"), ("int", 5)):
            with self.subTest(per_person=label):
                data = {"202608": bad, "202609": {"Ochi": {"c": thr("a")}}}
                self.assertEqual(est(data)["n_calls"], 1)

    def test_threads_that_are_empty_or_not_a_dict_are_zero_calls(self):
        """その対象者のスレッドが 空 dict / None / list / 文字列 / 数値 なら0回。"""
        for label, bad in (("空dict", {}), ("None", None), ("空list", []), ("非空list", [thr("a")]), ("str", "x"), ("int", 5)):
            with self.subTest(threads=label):
                self.assertEqual(est({"202609": {"Ochi": bad}})["n_calls"], 0)

    def test_mails_missing_or_none_count_as_zero_mails(self):
        """mails が無い・None のスレッドは0通扱い (入力は 見出し200 + 定型2100 のまま、1回と数える)。"""
        for label, t in (("mailsキー無し", {}), ("mails=None", {"mails": None}), ("mails=[]", {"mails": []})):
            with self.subTest(thread=label):
                e = est(single(t))
                self.assertEqual((e["n_calls"], e["input_chars"]), (1, 2300))

    def test_mails_that_are_not_dicts_are_ignored(self):
        """dict でないメール要素は無視する (dict のものだけ数える)。"""
        e = est(single({"mails": [None, "文字列", 5, ["x"], mail("a" * 10)]}))
        self.assertEqual(e["input_chars"], PROMPT + 200 + (10 + 40))
        self.assertEqual(est(single({"mails": [None, "文字列", 5]}))["input_chars"], 2300)

    def test_body_missing_or_none_counts_as_empty(self):
        """body が無い/None/空文字/0 なら空 (0字 + 40字)。"""
        for label, m in (("キー無し", {"sender_name": "x"}), ("None", {"body": None}), ("空", {"body": ""}), ("0", {"body": 0})):
            with self.subTest(body=label):
                self.assertEqual(est(single({"mails": [m]}))["input_chars"], 2300 + 40)

    def test_non_string_body_is_converted_with_str(self):
        """body が文字列でなければ str() の長さで数える (12345 → 5字)。"""
        self.assertEqual(est(single({"mails": [{"body": 12345}]}))["input_chars"], 2300 + 5 + 40)

    def test_characters_not_bytes_are_counted(self):
        """バイト数ではなく文字数で数える (日本語・絵文字)。"""
        self.assertEqual(est(single(thr("あ" * 100)))["input_chars"], 2300 + 100 + 40)
        self.assertEqual(est(single(thr("😀" * 10)))["input_chars"], 2300 + 10 + 40)

    def test_whitespace_is_not_stripped(self):
        """空白・改行も文字として数える (strip しない)。"""
        self.assertEqual(est(single(thr("   ")))["input_chars"], 2300 + 3 + 40)
        self.assertEqual(est(single(thr("\n\n\n")))["input_chars"], 2300 + 3 + 40)

    def test_non_dict_monthly_meetings_entries_do_not_crash(self):
        """会議の月別辞書に、その月が無い・None・文字列があっても落ちない (会議の分は足さない)。"""
        for label, meetings in (("空dict", {}), ("月が無い", {"202501": [{}]}), ("None", {"202609": None}),
                                ("str", {"202609": "会議"}), ("int", {"202609": 3})):
            with self.subTest(meetings=label):
                self.assertEqual(est(single({"mails": []}), meetings)["input_chars"], 2300)


class TestSpecGapEstimateMalformedInput(InTempCwd):
    """仕様が曖昧/未記載の点 (thread が dict でないときの見出し・monthly_meetings 自体が None のとき)。"""

    def test_a_thread_that_is_not_a_dict_does_not_crash(self):
        """thread が dict でなくても (None・文字列・数値・list) 落ちず、(月,対象者) は1回と数える。"""
        # 仕様: 「thread の mails が無い → 0通」。dict でない thread は「mails が無い」と同じ扱いと解釈する。
        # 見出しの +200 を足すか (2300) 足さないか (2100) は仕様に明記が無いので、どちらも許容する
        for label, bad in (("None", None), ("str", "x"), ("int", 5), ("list", [1])):
            with self.subTest(thread=label):
                e = est(one({"conv-1": bad}))
                self.assertEqual(e["n_calls"], 1)
                self.assertIn(e["input_chars"], (PROMPT, PROMPT + 200))

    def test_monthly_meetings_none_does_not_crash(self):
        """monthly_meetings が None でも落ちない (その月の会議が list でない → 会議の分は足さない)。"""
        # 仕様は「その月の会議が list なら」。monthly_meetings 自体が None/dict でない場合の記述は無いが、
        # 「list でない」の延長として、落ちずに会議の分を足さないと解釈する
        for bad in (None, [], "x", 5):
            with self.subTest(monthly_meetings=bad):
                e = oto().estimate_review_cost(single({"mails": []}), bad, None)
                self.assertEqual((e["n_calls"], e["input_chars"]), (1, 2300))


class TestEstimateInputChars(InTempCwd):
    """通常スレッドの入力文字数 = min(Σ(min(min(len(body),800)+40 の合計,8000)+200), 60000) + 2100。"""

    def chars(self, threads, person="Ochi", meetings=None):
        data = one(threads, person)
        e = est(data, {} if meetings is None else {"202609": meetings})
        self.assertEqual(e["n_calls"], 1)
        return e["input_chars"]

    def one_thread(self, *bodies):
        return self.chars({"conv-1": thr(*bodies)})

    def test_formula_examples(self):
        """入力文字数の式 (本文は1通800字まで・1通+40字・スレッド8000字まで・+200字(見出し)・+2100字(定型)) の具体例。"""
        cases = [
            ("メール0通", [], 2300),
            ("本文なし1通", [""], 2340),
            ("本文100字1通", ["a" * 100], 2440),
            ("本文799字", ["a" * 799], 3139),
            ("本文800字 (上限ちょうど)", ["a" * 800], 3140),
            ("本文801字 (上限超過)", ["a" * 801], 3140),
            ("本文5000字", ["a" * 5000], 3140),
            ("3通 10/20/30字", ["a" * 10, "b" * 20, "c" * 30], 2480),
            ("9通×800字 (合計7560は上限未満)", ["a" * 800] * 9, 2100 + 7560 + 200),
            ("10通×800字 (合計8400は上限8000へ)", ["a" * 800] * 10, 2100 + 8000 + 200),
            ("100通×800字", ["a" * 800] * 100, 2100 + 8000 + 200),
        ]
        for label, bodies, expected in cases:
            with self.subTest(case=label):
                self.assertEqual(self.one_thread(*bodies), expected)

    def test_body_limit_boundary_is_800(self):
        """1通の本文の上限 800字の境界 (799 / 800 / 801)。"""
        self.assertEqual(self.one_thread("a" * 799) - self.one_thread(""), 799)
        self.assertEqual(self.one_thread("a" * 800) - self.one_thread(""), 800)
        self.assertEqual(self.one_thread("a" * 801) - self.one_thread(""), 800)

    def test_thread_cap_boundary_is_8000(self):
        """スレッドの上限 8000字の境界 (7999 / 8000 / 8001)。9通×800字 (7560) の後ろの1通の長さで合計を決める。"""
        for last, expected_thread in ((399, 7999), (400, 8000), (401, 8000)):
            with self.subTest(total=7560 + last + 40):
                self.assertEqual(self.one_thread(*(["a" * 800] * 9 + ["b" * last])), PROMPT + expected_thread + 200)

    def test_heading_overhead_is_added_after_the_thread_cap(self):
        """見出しの +200 は、スレッドの上限 (8000) の後に足す (上限の対象外)。"""
        self.assertEqual(self.one_thread(*(["a" * 800] * 50)), PROMPT + 8000 + 200)

    def test_each_mail_counts_forty_extra_characters(self):
        """メール1通ごとに40字を足す。"""
        self.assertEqual(self.one_thread("", "") - self.one_thread(""), 40)

    def test_each_thread_counts_two_hundred_extra_characters(self):
        """スレッド1つごとに見出し200字を足す (メール0通のスレッドでも)。"""
        self.assertEqual(self.chars(empty_threads(2)) - self.chars(empty_threads(1)), 200)
        self.assertEqual(self.chars(empty_threads(100)), PROMPT + 100 * 200)

    def test_threads_in_one_call_are_summed(self):
        """同じ呼び出しの複数スレッドの文字数を合計する。"""
        self.assertEqual(self.chars({"a": thr("a" * 100), "b": thr(), "c": thr("c" * 10, "d" * 20)}),
                         PROMPT + (140 + 200) + 200 + (50 + 60 + 200))

    def test_each_thread_is_capped_on_its_own_not_as_a_whole(self):
        """8000字の上限はスレッドごと (2スレッドともそれぞれ8000字で頭打ち)。"""
        big = thr(*(["a" * 800] * 20))
        self.assertEqual(self.chars({"a": big, "b": copy.deepcopy(big)}), PROMPT + 2 * (8000 + 200))

    def test_total_cap_is_60000_for_the_sum_of_the_threads(self):
        """全スレッドの合計の上限は 60000字。上限の後に定型の 2100字を足す。"""
        full = lambda: thr(*(["a" * 800] * 10))                                   # 1つ 8000+200 = 8200  # noqa: E731
        self.assertEqual(self.chars({f"c{i}": full() for i in range(7)}), PROMPT + 7 * 8200)        # 57400: 上限未満
        self.assertEqual(self.chars({f"c{i}": full() for i in range(8)}), PROMPT + 60000)           # 65600 → 60000
        self.assertEqual(self.chars({f"c{i}": full() for i in range(30)}), PROMPT + 60000)

    def test_total_cap_boundary(self):
        """全体の上限 60000字の境界 (59999 / 60000 / 60001)。7スレッド(57400) + [800,800,x]字のスレッド (1920+x)。"""
        full = lambda: thr(*(["a" * 800] * 10))                                   # noqa: E731
        for x, expected_sum in ((679, 59999), (680, 60000), (681, 60000)):
            with self.subTest(total=57400 + 1920 + x):
                threads = {f"c{i}": full() for i in range(7)}
                threads["tail"] = thr("a" * 800, "b" * 800, "c" * x)
                self.assertEqual(self.chars(threads), PROMPT + expected_sum)

    def test_prompt_overhead_is_added_after_the_total_cap(self):
        """定型の 2100字は、全体の上限の後に足す (上限の対象外)。"""
        self.assertEqual(self.chars({f"c{i}": thr(*(["a" * 800] * 10)) for i in range(20)}), 60000 + 2100)

    def test_thread_order_does_not_matter(self):
        """スレッドの並び順で結果が変わらない。"""
        items = [(f"c{i}", thr("あ" * (i * 50))) for i in range(12)]
        a = est(one(dict(items)))["input_chars"]
        random.Random(7).shuffle(items)
        self.assertEqual(est(one(dict(items)))["input_chars"], a)

    def test_staff_and_ochi_get_the_same_thread_chars(self):
        """通常スレッドの文字数の数え方は、Ochi も スタッフも同じ (会議の分だけが違う)。"""
        data = {"202609": {"Ochi": {"c": thr("a" * 100)}, "Saji": {"c": thr("a" * 100)}}}
        e = est(data)
        self.assertEqual((e["n_calls"], e["input_chars"]), (2, 2 * (PROMPT + 140 + 200)))

    def test_calls_are_summed_over_months_and_persons(self):
        """複数の (月, 対象者) の入力文字数を合計する。"""
        data = {"202608": {"Ochi": {"c": thr("a" * 10)}}, "202609": {"Ochi": {"c": thr("a" * 20)}, "Saji": {"c": thr()}}}
        e = est(data)
        self.assertEqual(e["n_calls"], 3)
        self.assertEqual(e["input_chars"], (PROMPT + 50 + 200) + (PROMPT + 60 + 200) + (PROMPT + 200))

    def test_many_threads_are_estimated_quickly(self):
        """3000スレッド × 12か月でも5秒未満で見積もれる。"""
        data = {f"2026{m:02d}": {"Ochi": {f"c{i}": thr("本文" * 200, "返信" * 100) for i in range(250)}} for m in range(1, 13)}
        t0 = time.time()
        e = est(data)
        self.assertLess(time.time() - t0, 5.0)
        self.assertEqual(e["n_calls"], 12)


class TestEstimateMinutes(InTempCwd):
    """議事録 (件名に REVIEW_MINUTES_SUBJECT_KEYWORD を含むスレッド): 1通5万字まで・スレッドの上限なし・全体の6万字で頭打ち。"""

    def chars(self, *threads):
        e = est(one({f"c{i}": t for i, t in enumerate(threads)}))
        self.assertEqual(e["n_calls"], 1)
        return e["input_chars"]

    def test_minutes_body_is_not_cut_at_800(self):
        """議事録の本文は 800字で切らない (3000字なら 3000+40+200+2100)。"""
        self.assertEqual(self.chars(minutes_thr("a" * 3000)), PROMPT + 3040 + 200)

    def test_minutes_body_limit_is_50000(self):
        """議事録の1通の上限は5万字 (49999 / 50000 / 50001 / 10万)。"""
        for length, counted in ((49999, 49999), (50000, 50000), (50001, 50000), (100000, 50000)):
            with self.subTest(length=length):
                self.assertEqual(self.chars(minutes_thr("a" * length)), PROMPT + counted + 40 + 200)

    def test_minutes_thread_has_no_8000_cap(self):
        """議事録スレッドには 8000字のスレッド上限が無い (5000字×3通 = 15120 のまま)。"""
        self.assertEqual(self.chars(minutes_thr("a" * 5000, "b" * 5000, "c" * 5000)), PROMPT + 15120 + 200)

    def test_minutes_is_still_capped_by_the_total_60000(self):
        """議事録でも、全体の合計は 60000字で頭打ち (5万字×2通 → 60000 + 2100)。"""
        self.assertEqual(self.chars(minutes_thr("a" * 50000, "b" * 50000)), 60000 + PROMPT)

    def test_minutes_and_normal_threads_are_each_counted_by_their_own_rule(self):
        """議事録と通常スレッドが同じ呼び出しにあれば、それぞれの規則で数えて合計する。"""
        self.assertEqual(self.chars(minutes_thr("a" * 3000), thr("b" * 5000)), PROMPT + (3040 + 200) + (840 + 200))

    def test_minutes_detected_by_the_conversation_topic_too(self):
        """件名ではなく conversation_topic にキーワードがあっても議事録 (review_thread_is_minutes と同じ判定)。"""
        m = mail("a" * 3000, subject="RE: 件名", conversation_topic=f"{oto().REVIEW_MINUTES_SUBJECT_KEYWORD} 7")
        self.assertEqual(self.chars({"mails": [m]}), PROMPT + 3040 + 200)

    def test_keyword_match_is_case_insensitive_like_review_thread_is_minutes(self):
        """大文字小文字を区別しない判定 (既存の review_thread_is_minutes に従う)。"""
        subject = oto().REVIEW_MINUTES_SUBJECT_KEYWORD.upper()
        m = mail("a" * 3000, subject=subject, conversation_topic=subject)
        self.assertTrue(oto().review_thread_is_minutes({"mails": [m]}))                       # 前提
        self.assertEqual(self.chars({"mails": [m]}), PROMPT + 3040 + 200)

    def test_a_similar_but_different_subject_is_a_normal_thread(self):
        """キーワードを含まない似た件名は通常スレッド (800字で切る)。"""
        m = mail("a" * 3000, subject="ICS R04 Japan R&D meeting", conversation_topic="ICS R04 Japan R&D meeting")
        self.assertEqual(self.chars({"mails": [m]}), PROMPT + 840 + 200)

    def test_minutes_judgement_uses_review_thread_is_minutes(self):
        """議事録の判定は review_thread_is_minutes(thread) を使う (差し替えると結果が変わる)。"""
        seen = []

        def fake(thread, *a, **k):
            seen.append(thread)
            return True
        t = thr("a" * 3000)
        with mock.patch.object(oto(), "review_thread_is_minutes", fake):
            e = est(single(t))
        self.assertEqual(e["input_chars"], PROMPT + 3040 + 200, "判定が True なら議事録扱い (5万字上限)")
        self.assertTrue(any(s is t for s in seen), "review_thread_is_minutes にスレッドを渡していない")

    def test_an_exception_in_the_judgement_means_a_normal_thread(self):
        """判定で例外が出たら、通常スレッド扱い (800字で切る)。見積り全体は落ちない。"""
        def boom(thread, *a, **k):
            raise RuntimeError("判定で失敗")
        with mock.patch.object(oto(), "review_thread_is_minutes", boom):
            e = est(single(minutes_thr("a" * 3000)))
        self.assertEqual((e["n_calls"], e["input_chars"]), (1, PROMPT + 840 + 200))

    def test_a_real_judgement_error_means_a_normal_thread(self):
        """本物の review_thread_is_minutes が例外を出す形 (先頭に dict でない要素) の議事録は、通常扱い。"""
        # [None, 議事録のメール] は、review_thread_is_minutes の中で None.get が AttributeError になる
        t = {"mails": [None, minutes_mail("a" * 3000)]}
        with self.assertRaises(Exception):
            oto().review_thread_is_minutes(t)                                                  # 前提
        self.assertEqual(self.chars(t), PROMPT + 840 + 200)


class TestEstimateStaffMinutes(InTempCwd):
    """(レビュー指摘 a) スタッフ (Ochi 以外) の議事録も、議事録の規則 (1通5万字まで・スレッドの上限なし) で数える。会議は足さない。"""

    def test_staff_minutes_body_is_not_cut_at_800(self):
        """スタッフの議事録 3000字は 3000+40+200+2100 (会議があっても足さない)。"""
        for person in ("Saji", "Yuto Oi"):
            with self.subTest(person=person):
                e = est({"202609": {person: {"m": minutes_thr("a" * 3000)}}}, {"202609": [{}] * 10})
                self.assertEqual((e["n_calls"], e["input_chars"]), (1, PROMPT + 3040 + 200))

    def test_staff_minutes_have_no_8000_thread_cap(self):
        """スタッフの議事録 5000字×3通 = 15120 (8000で切らない)。"""
        e = est({"202609": {"Saji": {"m": minutes_thr("a" * 5000, "b" * 5000, "c" * 5000)}}})
        self.assertEqual(e["input_chars"], PROMPT + 15120 + 200)

    def test_staff_minutes_body_limit_is_50000(self):
        """スタッフの議事録も1通5万字まで (7万字 → 50000)。"""
        e = est({"202609": {"Saji": {"m": minutes_thr("a" * 70000)}}})
        self.assertEqual(e["input_chars"], PROMPT + 50040 + 200)

    def test_staff_minutes_are_capped_by_the_total_60000(self):
        """スタッフの議事録でも、全体の合計は 60000字で頭打ち。"""
        e = est({"202609": {"Saji": {"m": minutes_thr("a" * 50000, "b" * 50000)}}})
        self.assertEqual(e["input_chars"], 60000 + PROMPT)

    def test_the_same_minutes_thread_for_ochi_and_staff_is_counted_in_each_call(self):
        """同じ議事録スレッドが Ochi とスタッフの両方に入っていれば、それぞれの呼び出しで議事録として数える。"""
        t = minutes_thr("a" * 3000)
        e = est({"202609": {"Ochi": {"m": t}, "Saji": {"m": t}}})
        self.assertEqual((e["n_calls"], e["input_chars"]), (2, 2 * (PROMPT + 3040 + 200)))

    def test_staff_normal_and_minutes_threads_each_follow_their_rule(self):
        """スタッフの通常スレッド (800字で切る) と議事録 (切らない) が同じ呼び出しにあれば、それぞれの規則で合計する。"""
        e = est({"202609": {"Saji": {"n": thr("b" * 5000), "m": minutes_thr("a" * 3000)}}})
        self.assertEqual(e["input_chars"], PROMPT + (840 + 200) + (3040 + 200))


class TestEstimateMeetings(InTempCwd):
    """会議: Ochi だけ、その月の会議が list なら min(件数,60)×100 を足す (追記2: 1行100字。スタッフには足さない)。"""

    BASE = PROMPT + 200                                          # メール0通のスレッド1つ

    def chars(self, person="Ochi", meetings=None, yyyymm="202609"):
        e = est(single({"mails": []}, person, yyyymm), {yyyymm: meetings})
        self.assertEqual(e["n_calls"], 1)
        return e["input_chars"]

    def test_each_meeting_adds_forty_characters(self):
        """会議1件ごとに100字 (追記2。旧40字)。"""
        for n, extra in ((0, 0), (1, 100), (2, 200), (10, 1000), (59, 5900)):
            with self.subTest(meetings=n):
                self.assertEqual(self.chars(meetings=[{}] * n), self.BASE + extra)

    def test_meeting_lines_are_capped_at_60(self):
        """会議は最大60行 (60 / 61 / 100件)。"""
        for n in (60, 61, 100, 1000):
            with self.subTest(meetings=n):
                self.assertEqual(self.chars(meetings=[{}] * n), self.BASE + 6000)

    def test_staff_do_not_get_the_meetings(self):
        """スタッフ (Ochi 以外) には会議を足さない。"""
        for person in ("Saji", "Yuto Oi", "ochi", "OCHI"):
            with self.subTest(person=person):
                self.assertEqual(self.chars(person, [{}] * 10), self.BASE)

    def test_meetings_that_are_not_a_list_are_not_added(self):
        """その月の会議が list でなければ (None・文字列・数値・dict) 足さない。"""
        for label, bad in (("None", None), ("str", "会議"), ("int", 5), ("dict", {"a": 1})):
            with self.subTest(meetings=label):
                self.assertEqual(self.chars(meetings=bad), self.BASE)

    def test_meeting_items_are_only_counted_not_read(self):
        """会議の要素は数えるだけ (None や文字列でも1件)。"""
        self.assertEqual(self.chars(meetings=[None, "x", 3, {"subject": "a"}]), self.BASE + 4 * MEET)

    def test_the_meetings_of_the_same_month_are_used(self):
        """その月 (yyyymm) の会議だけを使う (他の月の会議は足さない)。"""
        e = est(single({"mails": []}, "Ochi", "202609"), {"202608": [{}] * 10, "202609": [{}] * 3})
        self.assertEqual(e["input_chars"], self.BASE + 3 * MEET)

    def test_a_month_without_ochi_threads_adds_no_meeting_cost(self):
        """Ochi のスレッドが空の月は呼び出しが無いので、会議の分も足さない (会議があっても)。"""
        data = {"202608": {"Ochi": {}, "Saji": {"c": {"mails": []}}}, "202609": {"Ochi": {"c": {"mails": []}}}}
        e = est(data, {"202608": [{}] * 50, "202609": [{}] * 2})
        self.assertEqual(e["n_calls"], 2)
        self.assertEqual(e["input_chars"], 2 * self.BASE + 2 * MEET)

    def test_meetings_are_added_per_month(self):
        """会議は月ごとの呼び出しに足す (2か月ともOchiなら、それぞれの月の会議を足す)。"""
        data = {"202608": {"Ochi": {"c": {"mails": []}}}, "202609": {"Ochi": {"c": {"mails": []}}}}
        e = est(data, {"202608": [{}] * 5, "202609": [{}] * 100})
        self.assertEqual(e["input_chars"], 2 * self.BASE + 5 * MEET + 60 * MEET)

    def test_meetings_are_added_to_the_pair_after_the_total_cap(self):
        """会議の分は、全体の上限 (60000) の後に足す (上限を超えて 60000 + 2100 + 会議)。"""
        data = one({f"c{i}": thr(*(["a" * 800] * 10)) for i in range(10)})
        e = est(data, {"202609": [{}] * 10})
        self.assertEqual(e["input_chars"], 60000 + PROMPT + 10 * MEET)


def meeting(subject, day=3):
    return {"subject": subject, "start": datetime(2026, 9, day, 10, 0)}


SUBJECT_55 = "ICS R04 Japan R&D meeting - week 37 / Caracal sync 1on1"
SUBJECT_LONG = "Nexperia Japan Site - Quarterly Business Review preparation (Finance/Procurement)"


class RealPromptCase(InTempCwd):
    """本物の summarize_review_month (AI の呼び出しだけ偽物) で、実際にAIへ渡るプロンプトを捕まえて見積りと比べる土台 (テストは持たない)。"""

    def real_prompt_length(self, person, threads, meetings):
        mod = oto()
        summarizer = mod.MailSummarizer.__new__(mod.MailSummarizer)
        summarizer.total_input_tokens = summarizer.total_output_tokens = 0
        prompts = []

        def fake(prompt, schema, override_model=None):
            prompts.append(prompt)
            return {"achievements": []}
        summarizer._run_genai_call_with_schema = fake
        summarizer.summarize_review_month(2026, 9, threads, meetings, staff_names=[], person=person, force_refresh=True)
        self.assertEqual(len(prompts), 1, "前提: AI がちょうど1回呼ばれる")
        return len(prompts[0])

    def assert_covers(self, person, threads, meetings):
        estimated = est({"202609": {person: threads}}, {"202609": meetings})["input_chars"]
        actual = self.real_prompt_length(person, copy.deepcopy(threads), meetings)
        self.assertGreaterEqual(estimated, actual, f"見積り {estimated}字 < 実際 {actual}字 (見積りが過小)")
        return estimated, actual



class TestEstimateCoversTheRealPrompt(RealPromptCase):
    """(追記2・レビュー指摘 c) 会議が60件・件名が長いときも「見積りの入力文字数 ≧ 実際にAIへ渡る入力 (プロンプトの長さ)」。"""

    def test_sixty_meetings_with_55_character_subjects(self):
        """Ochi・短いスレッド1つ + 会議60件 (件名55字): 見積り ≧ 実際。"""
        self.assert_covers("Ochi", {"c1": thr("short")}, [meeting(SUBJECT_55) for _ in range(60)])

    def test_sixty_meetings_with_long_subjects(self):
        """Ochi・短いスレッド1つ + 会議60件 (件名81字): 見積り ≧ 実際 (旧40字/行では過小だった)。"""
        self.assertEqual(len(SUBJECT_LONG), 81)
        self.assert_covers("Ochi", {"c1": thr("short")}, [meeting(SUBJECT_LONG) for _ in range(60)])

    def test_more_than_sixty_long_meetings(self):
        """会議100件 (件名81字。プロンプトも見積りも60件まで): 見積り ≧ 実際。"""
        self.assert_covers("Ochi", {"c1": thr("short")}, [meeting(SUBJECT_LONG, 1 + i % 28) for i in range(100)])

    def test_big_threads_and_sixty_long_meetings(self):
        """Ochi・大きなスレッド12個 (全体の上限まで) + 会議60件 (件名81字): 見積り ≧ 実際。"""
        threads = {f"c{i}": thr(*(["x" * 900] * 12)) for i in range(12)}
        self.assert_covers("Ochi", threads, [meeting(SUBJECT_LONG) for _ in range(60)])


class TestSpecGapEstimateCoversTheRealPrompt(RealPromptCase):
    """仕様が明記していない組み合わせ (スタッフの議事録) でも、見積り ≧ 実際 であること (見積りは「多めに」が目的)。"""

    def test_staff_minutes_thread(self):
        """スタッフ (Saji) の議事録スレッド 3000字: 見積り ≧ 実際 (議事録の抽出指示が付いても)。"""
        self.assert_covers("Saji", {"m": minutes_thr("x" * 3000)}, [])


class TestEstimateCalibration(InTempCwd):
    """1回あたりの出力トークン = observed_output_tokens_per_call("review") が真ならその×1.5、無ければ 8000。"""

    def est1(self, n=1):
        return est(calls_grid(n))

    def test_without_a_log_the_default_8000_is_used_and_not_calibrated(self):
        """実績が無ければ1回あたり8000トークンで、calibrated は False。"""
        e = self.est1()
        self.assertEqual(e["output_tokens_per_call"], 8000)
        self.assertIs(e["calibrated"], False)

    def test_with_a_log_the_observed_value_times_1_5_is_used(self):
        """feature="review" の実績があれば「実績 × 1.5」を1回あたりの出力にし、calibrated は True。"""
        write_log(rec("review", 2, 6000))                           # 実績 3000/回 → ×1.5 = 4500
        e = self.est1()
        self.assertAlmostEqual(e["output_tokens_per_call"], 4500.0)
        self.assertIs(e["calibrated"], True)

    def test_output_tokens_follow_the_calibrated_value_and_the_calls(self):
        """出力トークン合計は「1回あたり × 呼び出し回数」。"""
        write_log(rec("review", 2, 6000))
        self.assertEqual(self.est1(3)["output_tokens"], 13500)

    def test_default_output_tokens_are_8000_per_call(self):
        """実績なしの出力トークン合計は 8000 × 回数。"""
        self.assertEqual(self.est1(3)["output_tokens"], 24000)

    def test_other_features_in_the_log_do_not_calibrate(self):
        """他の feature (action など) の実績では校正しない。"""
        write_log(rec("action", 2, 6000), rec("cockpit", 1, 9000))
        e = self.est1()
        self.assertEqual(e["output_tokens_per_call"], 8000)
        self.assertIs(e["calibrated"], False)

    def test_only_the_review_records_are_used_among_mixed_features(self):
        """review と他の feature が混ざったログでは、review の実績だけを使う。"""
        write_log(rec("action", 1, 900000), rec("review", 2, 6000), rec("action", 1, 1))
        self.assertAlmostEqual(self.est1()["output_tokens_per_call"], 4500.0)

    def test_zero_observed_output_falls_back_to_the_default(self):
        """実績が 0 なら (真ではないので) 既定の 8000 を使う。"""
        write_log(rec("review", 2, 0))
        e = self.est1()
        self.assertEqual(e["output_tokens_per_call"], 8000)
        self.assertIs(e["calibrated"], False)

    def test_uses_the_latest_five_records_of_the_log(self):
        """実績は直近5件から求める (observed_output_tokens_per_call の既定 last_n=5)。"""
        write_log(*[rec("review", 1, 1000 * i) for i in range(1, 8)])   # 直近5件 = 3000..7000 → 平均 5000/回 → ×1.5
        self.assertAlmostEqual(self.est1()["output_tokens_per_call"], 7500.0)

    def test_uses_observed_output_tokens_per_call_with_feature_review(self):
        """実績の取得に observed_output_tokens_per_call("review") を使う (feature は "review")。"""
        seen = []

        def fake(feature, last_n=5):
            seen.append(feature)
            return 4000.0
        with mock.patch.object(oto(), "observed_output_tokens_per_call", fake):
            e = self.est1()
        self.assertEqual(seen, ["review"])
        self.assertAlmostEqual(e["output_tokens_per_call"], 6000.0)
        self.assertIs(e["calibrated"], True)

    def test_observed_none_or_zero_uses_the_default(self):
        """実績が None / 0 なら既定値 (calibrated は False)。"""
        for value in (None, 0, 0.0):
            with self.subTest(observed=value):
                with mock.patch.object(oto(), "observed_output_tokens_per_call", lambda feature, last_n=5: value):
                    e = self.est1()
                self.assertEqual(e["output_tokens_per_call"], 8000)
                self.assertIs(e["calibrated"], False)

    def test_calibrated_is_a_bool(self):
        """calibrated は bool。"""
        self.assertIs(type(self.est1()["calibrated"]), bool)
        write_log(rec("review", 1, 100))
        self.assertIs(type(self.est1()["calibrated"]), bool)

    def test_a_corrupt_log_falls_back_to_the_default(self):
        """実績ログが壊れていても (UTF-8 で読めない) 例外を出さず、既定値で見積もる。"""
        write_bytes(LOG_PATH, "壊れたログ\n".encode("cp932"))
        e = self.est1()
        self.assertEqual(e["output_tokens_per_call"], 8000)
        self.assertIs(e["calibrated"], False)

    def test_zero_calls_still_report_the_per_call_value(self):
        """0回のときも、1回あたりの出力 (既定/実績×1.5) と calibrated を返す。"""
        self.assertEqual(est({})["output_tokens_per_call"], 8000)
        write_log(rec("review", 1, 4000))
        e = est({})
        self.assertAlmostEqual(e["output_tokens_per_call"], 6000.0)
        self.assertIs(e["calibrated"], True)


class TestEstimateOutputFloor(InTempCwd):
    """(追記) 実績があるときの1回あたり出力 = max(実績×1.5, 8000×0.5)。実績が極端に小さくても下限 4000 を下回らない
    (全件失敗の実行などで実績が薄まり、見積りが過小になるのを防ぐ)。実績が無ければ 8000 のまま (下限は適用しない)。"""

    def per_call(self, observed, calls=1):
        """実績ログに「1回あたり出力 observed」の記録 (calls 回ぶん) を置いて、1回の見積りの per_call を返す。"""
        write_log(rec("review", calls, observed * calls))
        return est(calls_grid(1))

    def test_a_tiny_observed_value_is_raised_to_the_floor_4000(self):
        """実績 ×1.5 が 4000 に届かないなら、1回あたりの出力は 4000 (calibrated は True のまま)。"""
        for observed in (1, 100, 1000, 2000, 2600):
            with self.subTest(observed=observed):
                e = self.per_call(observed)
                self.assertAlmostEqual(e["output_tokens_per_call"], 4000.0)
                self.assertIs(e["calibrated"], True)

    def test_the_floor_boundary_is_observed_times_1_5_equal_to_4000(self):
        """境界: 実績 ×1.5 = 4000 ちょうど (実績 2666.67/回) は 4000。下側は 4000 に引き上げ、上側はそのまま。"""
        write_log(rec("review", 3, 8000))                           # 2666.67/回 ×1.5 = 4000
        self.assertAlmostEqual(est(calls_grid(1))["output_tokens_per_call"], 4000.0)
        write_log(rec("review", 3, 7500))                           # 2500/回 ×1.5 = 3750 → 4000
        self.assertAlmostEqual(est(calls_grid(1))["output_tokens_per_call"], 4000.0)
        write_log(rec("review", 3, 8100))                           # 2700/回 ×1.5 = 4050 → そのまま
        self.assertAlmostEqual(est(calls_grid(1))["output_tokens_per_call"], 4050.0)

    def test_values_above_the_floor_are_unchanged(self):
        """下限を超える実績は、従来どおり 実績×1.5。"""
        for observed, expected in ((3000, 4500.0), (6000, 9000.0), (10000, 15000.0), (166000, 249000.0)):
            with self.subTest(observed=observed):
                self.assertAlmostEqual(self.per_call(observed)["output_tokens_per_call"], expected)

    def test_without_a_log_the_default_is_used_as_it_is_not_the_floor(self):
        """実績が無ければ 8000 (下限 4000 ではない)。"""
        e = est(calls_grid(1))
        self.assertEqual(e["output_tokens_per_call"], 8000)
        self.assertIs(e["calibrated"], False)

    def test_the_floor_is_used_for_the_cost_and_the_output_tokens(self):
        """下限に引き上げた値で、出力トークンと費用を計算する (件数ぶん)。"""
        write_log(rec("review", 1, 1000))
        e = est(calls_grid(5))
        self.assertAlmostEqual(e["output_tokens_per_call"], 4000.0)
        self.assertEqual(e["output_tokens"], 20000)
        self.assertAlmostEqual(e["yen"], yen_flash(5 * 2300, 20000), places=2)

    def test_a_poisoned_log_cannot_make_a_big_run_look_cheap(self):
        """実績が極端に小さい (例: 出力 50 トークン/回) でも、「全て × 3人」(48件) の見込みは下限ぶんの費用になり、確認が出る水準を保つ。"""
        write_log(rec("review", 1, 50))
        data = {f"2026{m:02d}": {p: {"c": thr("本文")} for p in ("Ochi", "A", "B", "C")} for m in range(1, 13)}
        e = est(data)
        self.assertEqual(e["n_calls"], 48)
        self.assertGreaterEqual(e["output_tokens"], 48 * 4000)
        self.assertGreaterEqual(e["yen"], 48 * 4000 * 2.50 / 1_000_000 * 160)

    def test_a_small_but_real_observation_is_flagged_as_calibrated(self):
        """差し替えた実績 (observed_output_tokens_per_call) が小さな正の値でも、calibrated は True・出力は下限 4000。"""
        with mock.patch.object(oto(), "observed_output_tokens_per_call", lambda feature, last_n=5: 0.5):
            e = est(calls_grid(1))
        self.assertAlmostEqual(e["output_tokens_per_call"], 4000.0)
        self.assertIs(e["calibrated"], True)


class TestEstimateReturnValue(InTempCwd):
    """戻り値のキー・estimate_ai_cost_yen との一致・円・モデル。"""

    def test_has_exactly_the_documented_keys(self):
        """キーは estimate_ai_cost_yen のキー + n_calls / input_chars / output_tokens_per_call / calibrated だけ。"""
        base_keys = set(oto().estimate_ai_cost_yen(1, 1, 1))
        self.assertEqual(set(est(calls_grid(2))), base_keys | {"n_calls", "input_chars", "output_tokens_per_call", "calibrated"})
        self.assertEqual(set(est({})), set(est(calls_grid(2))))

    def test_it_returns_a_dict(self):
        """戻り値は dict。"""
        self.assertIsInstance(est(calls_grid(1)), dict)

    def test_base_fields_are_those_of_estimate_ai_cost_yen_for_the_same_inputs(self):
        """基本の項目 (input_tokens/output_tokens/yen/needs_confirm/price_known) は、同じ入力で estimate_ai_cost_yen を呼んだ結果と同じ。"""
        e = est(single(thr("あ" * 500), "Ochi"))
        expected = oto().estimate_ai_cost_yen(e["input_chars"], e["n_calls"], e["output_tokens_per_call"])
        for key in expected:
            with self.subTest(key=key):
                self.assertEqual(e[key], expected[key])

    def test_input_tokens_follow_the_characters_and_output_tokens_the_calls(self):
        """入力トークンは文字数 (1文字=1トークン)、出力トークンは 8000 × 回数。"""
        e = est(calls_grid(4))
        self.assertEqual(e["input_chars"], 4 * 2300)
        self.assertEqual(e["input_tokens"], 4 * 2300)
        self.assertEqual(e["output_tokens"], 4 * 8000)

    def test_yen_for_the_default_model(self):
        """既定モデル (flash) の円が、単価から独立に計算した値と一致する。"""
        e = est(calls_grid(10))
        self.assertAlmostEqual(e["yen"], yen_flash(10 * 2300, 10 * 8000), places=2)
        self.assertIs(e["price_known"], True)

    def test_model_is_used_for_the_price(self):
        """model に応じた単価で円を計算する。"""
        flash, pro = est(calls_grid(10), None, FLASH), est(calls_grid(10), None, PRO)
        self.assertAlmostEqual(flash["yen"], yen_flash(23000, 80000), places=2)
        self.assertAlmostEqual(pro["yen"], yen_pro(23000, 80000), places=2)
        self.assertGreater(pro["yen"], flash["yen"])

    def test_unknown_model_uses_the_highest_price_and_is_flagged(self):
        """単価表に無いモデルは最大単価で計算し、price_known が False。"""
        e = est(calls_grid(10), None, "gemini-9")
        self.assertIs(e["price_known"], False)
        self.assertAlmostEqual(e["yen"], yen_pro(23000, 80000), places=2)

    def test_model_none_uses_the_configured_default_model(self):
        """model=None は設定の既定モデル (json/mail_manager_config.json の gemini_model) で計算する。"""
        write_json(oto().CONFIG_FILE, {"gemini_model": PRO})
        self.assertEqual(est(calls_grid(10))["yen"], est(calls_grid(10), None, PRO)["yen"])

    def test_zero_calls_cost_nothing(self):
        """0回なら入力0・出力0・0円・確認不要。"""
        e = est({"202609": {"Ochi": {}}})
        self.assertEqual((e["input_tokens"], e["output_tokens"], e["yen"]), (0, 0, 0))
        self.assertIs(e["needs_confirm"], False)


class TestEstimateNeedsConfirm(InTempCwd):
    """needs_confirm は見込み円が COST_CONFIRM_THRESHOLD_YEN (100円) 以上で真 (estimate_ai_cost_yen と整合)。"""

    def test_30_calls_stay_under_100_yen(self):
        """メール0通のスレッドの組30個 (99.31円) は確認不要。"""
        e = est(calls_grid(30))
        self.assertAlmostEqual(e["yen"], yen_flash(30 * 2300, 30 * 8000), places=2)
        self.assertLess(e["yen"], 100)
        self.assertIs(e["needs_confirm"], False)

    def test_31_calls_reach_100_yen(self):
        """同31個 (102.62円) は確認が必要 (100円以上)。"""
        e = est(calls_grid(31))
        self.assertAlmostEqual(e["yen"], yen_flash(31 * 2300, 31 * 8000), places=2)
        self.assertGreaterEqual(e["yen"], 100)
        self.assertIs(e["needs_confirm"], True)

    def test_a_small_run_does_not_need_confirmation(self):
        """既定の前月のみ × Ochi 1人 (1回・数円) は確認不要。"""
        e = est(single(thr("a" * 500)))
        self.assertLess(e["yen"], 10)
        self.assertIs(e["needs_confirm"], False)

    def test_needs_confirm_agrees_with_yen_for_many_sizes(self):
        """needs_confirm は常に「円が100円以上か」と一致する。"""
        for n in (1, 10, 29, 30, 31, 32, 60, 120):
            with self.subTest(n=n):
                e = est(calls_grid(n))
                self.assertEqual(e["needs_confirm"], e["yen"] >= 100)

    def test_exactly_at_the_threshold_needs_confirmation(self):
        """ちょうど閾値の金額なら確認が必要 (以上)。1銭上なら不要。"""
        yen = est(calls_grid(1))["yen"]
        with mock.patch.object(oto(), "COST_CONFIRM_THRESHOLD_YEN", yen):
            self.assertIs(est(calls_grid(1))["needs_confirm"], True)
        with mock.patch.object(oto(), "COST_CONFIRM_THRESHOLD_YEN", yen + 0.01):
            self.assertIs(est(calls_grid(1))["needs_confirm"], False)

    def test_calibrated_output_moves_one_call_across_the_threshold(self):
        """実績で校正した出力量により、1回の見積りが100円をまたぐ (99.7円前後 → 100.3円前後)。"""
        # 1回・入力2300字。実績 166000/回 (×1.5 = 249000) → 99.71円 / 実績 167000/回 → 100.31円
        write_log(rec("review", 1, 166000))
        under = est(calls_grid(1))
        write_log(rec("review", 1, 167000))
        over = est(calls_grid(1))
        self.assertAlmostEqual(under["yen"], yen_flash(2300, 249000), places=2)
        self.assertLess(under["yen"], 100)
        self.assertIs(under["needs_confirm"], False)
        self.assertAlmostEqual(over["yen"], yen_flash(2300, 250500), places=2)
        self.assertGreaterEqual(over["yen"], 100)
        self.assertIs(over["needs_confirm"], True)

    def test_two_calibrated_calls_need_confirmation_where_one_does_not(self):
        """1回は100円未満でも、2回なら100円以上で確認が必要になる。"""
        write_log(rec("review", 1, 100000))                         # ×1.5 = 150000 トークン/回
        one_call, two_calls = est(calls_grid(1)), est(calls_grid(2))
        self.assertIs(one_call["needs_confirm"], False)
        self.assertIs(two_calls["needs_confirm"], True)
        self.assertAlmostEqual(two_calls["yen"], yen_flash(2 * 2300, 2 * 150000), places=2)

    def test_unknown_model_is_priced_high_and_can_cross_the_threshold(self):
        """単価未登録のモデルは高めの単価なので、同じ件数でも確認が必要になりうる (flash 20件は不要・未登録は必要)。"""
        flash, unknown = est(calls_grid(20), None, FLASH), est(calls_grid(20), None, "gemini-9")
        self.assertIs(flash["needs_confirm"], False)
        self.assertIs(unknown["needs_confirm"], True)

    def test_all_months_with_staff_is_over_the_threshold_without_a_track_record(self):
        """実績がまだ無いとき、「全て」(12か月) × Ochi + スタッフ3人 (48回) は確認が必要。既定 (1回) は不要。"""
        data = {f"2026{m:02d}": {p: {"c": thr("本文")} for p in ("Ochi", "A", "B", "C")} for m in range(1, 13)}
        e = est(data)
        self.assertEqual(e["n_calls"], 48)
        self.assertIs(e["needs_confirm"], True)
        self.assertIs(est(single(thr("本文")))["needs_confirm"], False)


class TestEstimatePurity(InTempCwd):
    """見積りは入力を書き換えず・ファイルを作らず・現在日付に依存しない。"""

    def messy(self):
        return ({"202608": {"Ochi": {"a": thr("x" * 900, None, 12345), "b": minutes_thr("m" * 60000), "c": {"mails": None}},
                            "Saji": {"d": {}}, "Bad": None},
                 "202609": None, "202610": {"Ochi": {"e": None}}},
                {"202608": [{"subject": "会議"}] * 70, "202609": None})

    def test_inputs_are_not_modified(self):
        """見積りは monthly_threads と monthly_meetings を書き換えない。"""
        mt, mm = self.messy()
        before_mt, before_mm = copy.deepcopy(mt), copy.deepcopy(mm)
        oto().estimate_review_cost(mt, mm, None)
        self.assertEqual(mt, before_mt, "monthly_threads を書き換えた")
        self.assertEqual(mm, before_mm, "monthly_meetings を書き換えた")

    def test_estimating_writes_no_files(self):
        """見積りはファイルを作らず・書き換えない (実績ログへの追記・月別キャッシュ・結果ファイルも)。"""
        write_log(rec("review", 1, 100))
        os.makedirs(oto().REVIEW_CACHE_DIR, exist_ok=True)
        write_json(os.path.join(oto().REVIEW_CACHE_DIR, "202609.json"), {"item_count": 1, "achievements": []})
        before = snapshot_files(".")
        mt, mm = self.messy()
        oto().estimate_review_cost(mt, mm, None)
        est(calls_grid(40))
        self.assertEqual(snapshot_files("."), before, "見積りがファイルを作った/書き換えた")

    def test_estimating_creates_no_usage_log(self):
        """実績ログが無いとき、見積りで実績ログ (ai_usage_log.jsonl) を作らない。"""
        est(calls_grid(40))
        self.assertFalse(os.path.exists(LOG_PATH))
        self.assertFalse(os.path.exists(oto().REVIEW_CACHE_DIR))
        self.assertFalse(os.path.exists(oto().REVIEW_LAST_RESULT_FILE))

    def test_the_result_does_not_depend_on_today(self):
        """現在日付に依存しない (日付を 2026-01-15 / 2027-12-31 / 2030-06-01 に固定しても、実際の今日でも同じ結果)。"""
        mt, mm = self.messy()
        real = oto().estimate_review_cost(mt, mm, None)
        for fixed in (datetime(2026, 1, 15, 9, 0, 0), datetime(2027, 12, 31, 23, 59, 59), datetime(2030, 6, 1, 0, 0, 0)):
            class FakeDatetime(datetime):
                @classmethod
                def now(cls, tz=None):
                    return fixed

                @classmethod
                def today(cls):
                    return fixed
            with self.subTest(today=fixed.isoformat()):
                with mock.patch.object(oto(), "datetime", FakeDatetime):
                    self.assertEqual(oto().estimate_review_cost(mt, mm, None), real)

    def test_same_input_same_output(self):
        """同じ入力なら何度呼んでも同じ結果。"""
        mt, mm = self.messy()
        self.assertEqual(oto().estimate_review_cost(mt, mm, None), oto().estimate_review_cost(mt, mm, None))

    def test_does_not_touch_com_ai_or_network(self):
        """見積りは Outlook(COM)・AI・ネットワークに触れない (触れると _loader のスタブが RuntimeError で落とす)。"""
        mt, mm = self.messy()
        oto().estimate_review_cost(mt, mm, None)                    # 例外が出なければ OK


class TestSpecGapEstimateUsesTheConstants(InTempCwd):
    """仕様は REVIEW_ESTIMATE_* を定義し、見積りがその値を使うと書いている。値を直書きして定数が使われない実装
    (= 定数を変えても効かない) を検知するため、定数を差し替えて見積りが追随することを確認する。"""

    def patched(self, name, value):
        return mock.patch.object(oto(), name, value)

    def test_prompt_chars_constant_is_used(self):
        """REVIEW_ESTIMATE_PROMPT_CHARS を差し替えると反映される。"""
        with self.patched("REVIEW_ESTIMATE_PROMPT_CHARS", 100):
            self.assertEqual(est(single({"mails": []}))["input_chars"], 100 + 200)

    def test_output_tokens_constant_is_used_as_the_default_per_call(self):
        """REVIEW_ESTIMATE_OUTPUT_TOKENS を既定の1回あたり出力として使う。"""
        with self.patched("REVIEW_ESTIMATE_OUTPUT_TOKENS", 1000):
            e = est(single({"mails": []}))
        self.assertEqual((e["output_tokens_per_call"], e["output_tokens"]), (1000, 1000))

    def test_body_limit_constant_is_used(self):
        """REVIEW_ESTIMATE_BODY_LIMIT を通常の本文の上限として使う。"""
        with self.patched("REVIEW_ESTIMATE_BODY_LIMIT", 10):
            self.assertEqual(est(single(thr("a" * 50)))["input_chars"], PROMPT + 10 + 40 + 200)

    def test_mail_overhead_constant_is_used(self):
        """REVIEW_ESTIMATE_MAIL_OVERHEAD を1通あたりの加算として使う。"""
        with self.patched("REVIEW_ESTIMATE_MAIL_OVERHEAD", 7):
            self.assertEqual(est(single(thr("", "")))["input_chars"], PROMPT + 200 + 2 * 7)

    def test_thread_overhead_constant_is_used(self):
        """REVIEW_ESTIMATE_THREAD_OVERHEAD をスレッドあたりの見出しの加算として使う。"""
        with self.patched("REVIEW_ESTIMATE_THREAD_OVERHEAD", 5):
            self.assertEqual(est(one(empty_threads(3)))["input_chars"], PROMPT + 15)

    def test_thread_chars_max_constant_is_used_for_normal_threads_only(self):
        """REVIEW_ESTIMATE_THREAD_CHARS_MAX を通常スレッドの上限として使う (議事録には効かない)。"""
        with self.patched("REVIEW_ESTIMATE_THREAD_CHARS_MAX", 100):
            self.assertEqual(est(single(thr("a" * 500, "b" * 500)))["input_chars"], PROMPT + 100 + 200)
            self.assertEqual(est(single(minutes_thr("a" * 500, "b" * 500)))["input_chars"], PROMPT + 1080 + 200)

    def test_total_chars_max_constant_is_used(self):
        """REVIEW_ESTIMATE_TOTAL_CHARS_MAX を全体の上限として使う。"""
        with self.patched("REVIEW_ESTIMATE_TOTAL_CHARS_MAX", 500):
            self.assertEqual(est(one(empty_threads(5)))["input_chars"], 500 + PROMPT)

    def test_minutes_body_limit_constant_is_used(self):
        """REVIEW_ESTIMATE_MINUTES_BODY_LIMIT を議事録の本文の上限として使う。"""
        with self.patched("REVIEW_ESTIMATE_MINUTES_BODY_LIMIT", 1000):
            self.assertEqual(est(single(minutes_thr("a" * 5000)))["input_chars"], PROMPT + 1000 + 40 + 200)

    def test_meeting_constants_are_used(self):
        """REVIEW_ESTIMATE_MEETING_LINES_MAX / REVIEW_ESTIMATE_MEETING_LINE_CHARS を会議の行数・1行の文字数として使う。"""
        meetings = {"202609": [{}] * 10}
        with self.patched("REVIEW_ESTIMATE_MEETING_LINES_MAX", 5):
            self.assertEqual(est(single({"mails": []}), meetings)["input_chars"], 2300 + 5 * MEET)
        with self.patched("REVIEW_ESTIMATE_MEETING_LINE_CHARS", 7):
            self.assertEqual(est(single({"mails": []}), meetings)["input_chars"], 2300 + 10 * 7)

    def test_floor_ratio_constant_is_used(self):
        """REVIEW_ESTIMATE_OUTPUT_FLOOR_RATIO を下限の割合として使う (0.25 なら 8000×0.25 = 2000)。"""
        write_log(rec("review", 1, 1000))                           # 実績 ×1.5 = 1500 → 下限へ
        with self.patched("REVIEW_ESTIMATE_OUTPUT_FLOOR_RATIO", 0.25):
            self.assertAlmostEqual(est(single({"mails": []}))["output_tokens_per_call"], 2000.0)

    def test_floor_follows_the_default_output_constant(self):
        """下限は「既定の出力 (REVIEW_ESTIMATE_OUTPUT_TOKENS) × 割合」 (既定を 10000 にすれば下限は 5000)。"""
        # 仕様は「max(実績×1.5, 8000×0.5)」。この 8000 は既定の出力 (REVIEW_ESTIMATE_OUTPUT_TOKENS) と解釈する
        write_log(rec("review", 1, 1000))
        with self.patched("REVIEW_ESTIMATE_OUTPUT_TOKENS", 10000):
            self.assertAlmostEqual(est(single({"mails": []}))["output_tokens_per_call"], 5000.0)

    def test_safety_constant_is_used(self):
        """REVIEW_ESTIMATE_SAFETY を実績に掛ける係数として使う。"""
        write_log(rec("review", 2, 6000))                           # 実績 3000/回
        with self.patched("REVIEW_ESTIMATE_SAFETY", 2.0):
            self.assertAlmostEqual(est(single({"mails": []}))["output_tokens_per_call"], 6000.0)


class TestEstimateMatchesReference(InTempCwd):
    """乱数で作った入力で、このファイル内の独立した参照実装 (仕様の式) と一致する (固定シード)。"""

    @staticmethod
    def random_input(rnd):
        persons = ["Ochi", "Saji", "Yuto Oi", "Kaji"]
        monthly, meetings = {}, {}
        for m in rnd.sample(range(1, 13), rnd.randint(1, 5)):
            yyyymm = f"2026{m:02d}"
            per = {}
            for p in rnd.sample(persons, rnd.randint(0, 4)):
                threads = {}
                for i in range(rnd.choice([0, 1, 1, 2, 5, 12])):
                    mails = [mail(rnd.choice(["", "x" * rnd.randint(1, 1500), None, 12345, "あ" * rnd.randint(1, 900)]))
                             for _ in range(rnd.randint(0, 14))]
                    if rnd.random() < 0.15:
                        mails = [minutes_mail(rnd.choice(["m" * rnd.randint(1, 30000), "m" * 70000])) for _ in range(rnd.randint(1, 3))]
                    if rnd.random() < 0.08:
                        mails.insert(rnd.randint(0, len(mails)), rnd.choice([None, "x", 5]))
                    threads[f"{p}-{i}"] = {"mails": mails}
                per[p] = threads
            monthly[yyyymm] = per
            meetings[yyyymm] = rnd.choice([None, [], [{}] * rnd.randint(1, 90), "x"])
        return monthly, meetings

    def test_matches_the_reference_on_random_inputs(self):
        """呼び出し回数と入力文字数の合計が、仕様の式を独立に書いた参照実装と一致する。"""
        rnd = random.Random(20261004)
        for trial in range(80):
            monthly, meetings = self.random_input(rnd)
            expected_calls, expected_chars = ref_estimate(monthly, meetings)
            with self.subTest(trial=trial):
                e = est(monthly, meetings)
                self.assertEqual(e["n_calls"], expected_calls)
                self.assertEqual(e["input_chars"], expected_chars)
                self.assertEqual(e["input_tokens"], expected_chars)
                self.assertAlmostEqual(e["yen"], yen_flash(expected_chars, expected_calls * 8000), places=2)


def cache_path(yyyymm, person="Ochi"):
    """月別キャッシュのパス: REVIEW_CACHE_DIR/{YYYYMM}{対象者のサフィックス}.json (Ochi は接尾辞なし)。"""
    return os.path.join(oto().REVIEW_CACHE_DIR, f"{yyyymm}{oto()._review_person_cache_suffix(person)}.json")


def put_cache_file(yyyymm, person="Ochi", error=True):
    """summarize_review_month が書くのと同じ形のキャッシュ (_error を指定できる)。"""
    write_json(cache_path(yyyymm, person), {"item_count": 1, "achievements": [], "_error": error})


def pairs(*items):
    """(月, 対象者) の組ごとに「スレッドが1つ」の monthly_threads を作る。"""
    monthly = {}
    for yyyymm, person in items:
        monthly.setdefault(yyyymm, {})[person] = {"conv": thr("a")}
    return monthly


def count_failed(monthly_threads):
    return oto().count_failed_review_calls(monthly_threads)


class TestCountFailedReviewCalls(InTempCwd):
    """(追記) count_failed_review_calls(monthly_threads): スレッド辞書が空でない「月×対象者」のうち、月別キャッシュが
    JSON の dict で _error が真のものの数。ファイルが無い・読めない・壊れている・dict でない・_error が偽は数えない。例外は出さない。"""

    def test_an_error_cache_of_a_pair_with_threads_is_counted(self):
        """スレッドのある (月, 対象者) の月別キャッシュが _error=true なら1件。"""
        put_cache_file("202609", "Ochi", error=True)
        self.assertEqual(count_failed(pairs(("202609", "Ochi"))), 1)

    def test_each_pair_is_counted_separately(self):
        """3か月 × 2人 (6組) のうち _error のある組だけを数える。"""
        monthly = pairs(*[(f"2026{m:02d}", p) for m in (7, 8, 9) for p in ("Ochi", "Saji")])
        for yyyymm, person in (("202607", "Ochi"), ("202608", "Saji"), ("202609", "Saji")):
            put_cache_file(yyyymm, person, error=True)
        put_cache_file("202607", "Saji", error=False)
        put_cache_file("202609", "Ochi", error=False)
        self.assertEqual(count_failed(monthly), 3)

    def test_the_count_is_per_pair_not_per_thread(self):
        """同じ (月, 対象者) にスレッドが何個あっても、失敗は1件。"""
        put_cache_file("202609", "Ochi", error=True)
        self.assertEqual(count_failed(one({f"c{i}": thr("a") for i in range(20)})), 1)

    def test_a_normal_cache_is_not_counted(self):
        """_error が偽・キーが無いキャッシュは数えない。"""
        put_cache_file("202609", "Ochi", error=False)
        write_json(cache_path("202608", "Ochi"), {"item_count": 1, "achievements": []})
        self.assertEqual(count_failed(pairs(("202609", "Ochi"), ("202608", "Ochi"))), 0)

    def test_truthy_error_values_are_counted(self):
        """_error が真と評価される値 (True・1・文字列・非空のlist/dict) なら数える。"""
        for value in (True, 1, "x", [1], {"a": 1}):
            with self.subTest(error=value):
                put_cache_file("202609", "Ochi", error=value)
                self.assertEqual(count_failed(pairs(("202609", "Ochi"))), 1)

    def test_falsy_error_values_are_not_counted(self):
        """_error が偽と評価される値 (False・0・空文字・None・空list) なら数えない。"""
        for value in (False, 0, "", None, []):
            with self.subTest(error=value):
                put_cache_file("202609", "Ochi", error=value)
                self.assertEqual(count_failed(pairs(("202609", "Ochi"))), 0)

    def test_missing_cache_file_or_folder_is_not_counted(self):
        """キャッシュのファイルが無い・フォルダ自体が無い場合は数えない。"""
        self.assertEqual(count_failed(pairs(("202609", "Ochi"))), 0)                  # フォルダが無い
        os.makedirs(oto().REVIEW_CACHE_DIR)
        self.assertEqual(count_failed(pairs(("202609", "Ochi"))), 0)                  # フォルダはあるがファイルが無い

    def test_unreadable_or_broken_files_are_not_counted(self):
        """JSON として読めない・壊れているファイルは数えない (例外も出さない)。"""
        os.makedirs(oto().REVIEW_CACHE_DIR)
        broken = {"空ファイル": b"", "壊れたJSON": b'{"_error": tru', "UTF-8でない": "壊れた".encode("cp932") + b'{"_error": true}',
                  "バイナリ": bytes(range(256)), "改行だけ": b"\n\n"}
        for label, raw in broken.items():
            with self.subTest(file=label):
                write_bytes(cache_path("202609", "Ochi"), raw)
                self.assertEqual(count_failed(pairs(("202609", "Ochi"))), 0)

    def test_a_json_that_is_not_a_dict_is_not_counted(self):
        """JSON としては読めても dict でなければ (list・文字列・数値・null・真偽値) 数えない。"""
        os.makedirs(oto().REVIEW_CACHE_DIR)
        for label, raw in (("list", '[{"_error": true}]'), ("str", '"_error"'), ("int", "5"), ("null", "null"), ("true", "true")):
            with self.subTest(json=label):
                write_text(cache_path("202609", "Ochi"), raw)
                self.assertEqual(count_failed(pairs(("202609", "Ochi"))), 0)

    def test_a_pair_with_empty_threads_is_not_counted_even_with_an_error_cache(self):
        """スレッド辞書が空の組は、_error のキャッシュがあっても数えない (その月は AI を呼んでいない)。"""
        put_cache_file("202609", "Ochi", error=True)
        put_cache_file("202609", "Saji", error=True)
        monthly = {"202609": {"Ochi": {}, "Saji": {"c": thr("a")}}}
        self.assertEqual(count_failed(monthly), 1)

    def test_a_month_that_is_not_in_monthly_threads_is_not_counted(self):
        """monthly_threads に無い月 (今回取得していない月) は、_error のキャッシュがあっても数えない。"""
        put_cache_file("202608", "Ochi", error=True)
        put_cache_file("202609", "Ochi", error=True)
        self.assertEqual(count_failed(pairs(("202609", "Ochi"))), 1)
        self.assertEqual(count_failed({}), 0)

    def test_another_persons_error_cache_does_not_count(self):
        """別の対象者のキャッシュは数えない (Ochi の組には 202609.json、Saji の組には 202609__Saji.json を見る)。"""
        put_cache_file("202609", "Saji", error=True)
        self.assertEqual(count_failed(pairs(("202609", "Ochi"))), 0)
        self.assertEqual(count_failed(pairs(("202609", "Saji"))), 1)
        put_cache_file("202609", "Ochi", error=True)
        self.assertEqual(count_failed(pairs(("202609", "Ochi"), ("202609", "Saji"))), 2)

    def test_the_file_names_follow_the_person_suffix(self):
        """ファイル名は Ochi が「YYYYMM.json」、スタッフが「YYYYMM__{英数字化した名前}.json」。"""
        self.assertEqual(os.path.basename(cache_path("202609", "Ochi")), "202609.json")
        self.assertEqual(os.path.basename(cache_path("202609", "Saji")), "202609__Saji.json")
        self.assertEqual(os.path.basename(cache_path("202609", "Yuto Oi")), "202609__Yuto_Oi.json")
        for person in ("Ochi", "Saji", "Yuto Oi"):
            with self.subTest(person=person):
                os.makedirs(oto().REVIEW_CACHE_DIR, exist_ok=True)
                put_cache_file("202609", person, error=True)
                self.assertEqual(count_failed(pairs(("202609", person))), 1)

    def test_monthly_threads_that_is_not_a_dict_gives_zero_without_an_error(self):
        """monthly_threads が dict でなければ (None・list・文字列・数値) 0 (例外を出さない)。"""
        put_cache_file("202609", "Ochi", error=True)
        for label, bad in (("None", None), ("list", []), ("非空list", [1, 2]), ("str", "x"), ("int", 5), ("bool", True)):
            with self.subTest(monthly_threads=label):
                self.assertEqual(count_failed(bad), 0)

    def test_a_per_person_that_is_not_a_dict_is_skipped(self):
        """対象者の辞書が dict でない月は飛ばし、他の月は数える。"""
        put_cache_file("202609", "Ochi", error=True)
        for label, bad in (("None", None), ("list", []), ("str", "x"), ("int", 5)):
            with self.subTest(per_person=label):
                self.assertEqual(count_failed({"202608": bad, "202609": {"Ochi": {"c": thr("a")}}}), 1)

    def test_threads_that_are_not_a_dict_or_are_empty_are_skipped(self):
        """スレッドが 空 dict / None / list / 文字列 / 数値 の組は飛ばす (例外を出さない)。"""
        put_cache_file("202609", "Ochi", error=True)
        for label, bad in (("空dict", {}), ("None", None), ("空list", []), ("非空list", [thr("a")]), ("str", "x"), ("int", 5)):
            with self.subTest(threads=label):
                self.assertEqual(count_failed({"202609": {"Ochi": bad}}), 0)

    def test_the_result_is_an_int(self):
        """戻り値は int。"""
        put_cache_file("202609", "Ochi", error=True)
        self.assertIs(type(count_failed(pairs(("202609", "Ochi")))), int)
        self.assertIs(type(count_failed(None)), int)

    def test_it_only_reads_and_does_not_modify_the_input(self):
        """読むだけ: ファイルを作らず・書き換えず (キャッシュのフォルダも作らない)、入力も書き換えない。"""
        monthly = {"202608": {"Ochi": {"c": thr("x" * 900, None)}, "Saji": {}}, "202609": None, "202610": {"Ochi": {"e": None}}}
        before_monthly = copy.deepcopy(monthly)
        count_failed(monthly)
        self.assertFalse(os.path.exists(oto().REVIEW_CACHE_DIR), "キャッシュのフォルダを作った")
        put_cache_file("202608", "Ochi", error=True)
        before_files = snapshot_files(".")
        self.assertEqual(count_failed(monthly), 1)
        self.assertEqual(snapshot_files("."), before_files, "ファイルを書き換えた")
        self.assertEqual(monthly, before_monthly, "入力を書き換えた")

    def test_the_result_does_not_depend_on_today(self):
        """現在日付に依存しない (日付を固定しても同じ結果)。"""
        put_cache_file("202609", "Ochi", error=True)
        monthly = pairs(("202609", "Ochi"), ("202608", "Ochi"))
        fixed = datetime(2030, 6, 1, 0, 0, 0)

        class FakeDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed
        with mock.patch.object(oto(), "datetime", FakeDatetime):
            self.assertEqual(count_failed(monthly), 1)

    def test_it_does_not_count_what_the_estimate_counts_it_only_looks_at_the_cache(self):
        """AI を呼ぶ件数 (見積り) とは別に、キャッシュの _error だけを見る (キャッシュが無ければ、スレッドがあっても0)。"""
        data = pairs(("202608", "Ochi"), ("202609", "Ochi"))
        self.assertEqual(est(data)["n_calls"], 2)
        self.assertEqual(count_failed(data), 0)


# ============================================================
# 3. _run_review の流れ (偽Outlook・偽AI・ダイアログのスタブ)
# ============================================================
class FlowOutlook:
    """Outlook(COM) の代わり。_run_review が使う3メソッドだけを持ち、呼ばれた順 (月・メール取得・スレッド化・会議取得) を
    events に記録する (COM には触れない)。スレッドの束ね方 (group_by_thread) は COM を使わない整形処理なので実物を使う。
      threads        : 月ごとの Ochi のスレッド数 (1スレッド = 本文 body のメール1通)
      staff_threads  : {スタッフ名: 月ごとのスレッド数}
      meetings       : 月ごとの会議の数
      fetch_error    : 指定すると get_review_mails_for_month がこの例外を出す
    """

    user_smtp_address = "ochi@example.com"

    def __init__(self, events, *, threads=1, body="本文", staff_threads=None, meetings=0, fetch_error=None):
        self.events = events
        self.threads, self.body, self.meetings = threads, body, meetings
        self.staff_threads = dict(staff_threads or {})
        self.fetch_error = fetch_error
        self.fetched = []
        self._group = types.MethodType(oto().OutlookMailManager.group_by_thread, self)

    def _make(self, year, month, tag, index, sender_name, sender_email):
        m = a3run.FakeOutlook._mail(year, month, tag, sender_name, sender_email, ["partner@example.com"])
        cid = f"conv-{year}{month:02d}-{tag}-{index}"
        m.update(conversation_id=cid, entry_id=f"E-{year}{month:02d}-{tag}-{index}", subject=f"件名{cid}",
                 conversation_topic=f"件名{cid}", body=self.body)
        return m

    def get_review_mails_for_month(self, year, month, progress_callback=None):
        self.events.append(f"mails:{year:04d}{month:02d}")
        self.fetched.append((year, month))
        if self.fetch_error is not None:
            raise self.fetch_error
        mails = [self._make(year, month, "ochi", i, "Ochi", self.user_smtp_address) for i in range(self.threads)]
        for person, n in self.staff_threads.items():
            tag = person.lower().replace(" ", "")
            mails += [self._make(year, month, tag, i, person, f"{tag}@example.com") for i in range(n)]
        return mails

    def group_by_thread(self, mails):
        self.events.append("group")
        return self._group(mails)

    def get_review_calendar_events(self, year, month, progress_callback=None):
        self.events.append(f"cal:{year:04d}{month:02d}")
        return [{"subject": f"会議{i}", "start": datetime(year, month, 10, 10, 0)} for i in range(self.meetings)]


class FlowSummarizer:
    """MailSummarizer の代わり (generate_review_data だけ)。呼び出しの記録・今回のトークンの加算・失敗・途中で止める (gate) ができる。"""

    model_id = FLASH

    def __init__(self, events, add_in=0, add_out=0, fail=None, gate=None, started=None, cache_effects=None,
                 spend_before_fail=False):
        self.events = events
        self.add_in, self.add_out, self.fail = add_in, add_out, fail
        self.spend_before_fail = spend_before_fail          # True なら、今回のトークンを加算してから fail を出す (AI を使った後の途中の例外)
        self.gate, self.started = gate, started
        self.cache_effects = dict(cache_effects or {})      # {(YYYYMM, 対象者): _error の真偽}: generate の最中にその月別キャッシュを書く
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.calls = []

    def generate_review_data(self, monthly_threads, monthly_meetings, all_target_months, staff_names=None,
                             persons=None, progress_callback=None):
        self.events.append("generate")
        self.calls.append({"monthly_threads": monthly_threads, "monthly_meetings": monthly_meetings,
                           "all_months": list(all_target_months), "staff_names": staff_names, "persons": persons})
        if self.started is not None:
            self.started.set()
        if self.gate is not None:
            self.gate.wait(10)
        if self.fail and self.spend_before_fail:
            self.total_input_tokens += self.add_in
            self.total_output_tokens += self.add_out
        if self.fail:
            raise self.fail
        self.total_input_tokens += self.add_in
        self.total_output_tokens += self.add_out
        for (yyyymm, person), is_error in self.cache_effects.items():
            put_cache_file(yyyymm, person, error=is_error)
        return {"generated_at": "2026-10-04 12:00", "months": sorted(all_target_months), "persons": persons or ["Ochi"],
                "achievements": [], "raw_achievements": []}


class FlowReporter:
    """HTMLReportGenerator の代わり (generate_review_report だけ)。呼び出しの記録と、返すパス。"""

    def __init__(self, events, fail=None):
        self.events = events
        self.fail = fail
        self.calls = []

    def generate_review_report(self, review_data, period_label, total_input, total_output, reformat_mode=False,
                               filter_person=None):
        self.events.append(f"report:{filter_person}")
        self.calls.append({"review_data": review_data, "period_label": period_label, "total_input": total_input,
                           "total_output": total_output, "reformat_mode": reformat_mode, "filter_person": filter_person})
        if self.fail:
            raise self.fail
        return f"/tmp/review-{filter_person}.html"


class ReviewCostCase(a3m.ReviewGuiCase):
    """偽Outlook・偽AI・ダイアログのスタブを載せた画面 (本物の振り返りタブ) で、本物の _run_review を動かす土台。

    - A3 の ReviewGuiCase で本物の _ui_review_tab を組み立てる (本物のボタン・月/対象者のチェック)。
    - ワーカースレッドの root.after は mainloop が回っているときだけ動くので、待機は A1 の pump/settle (after で条件を
      監視して quit する mainloop) を使う。
    - A1.1 と同じく、テストの実行中は GC を止める (ワーカー上で Tk オブジェクトが解放されて Tcl_AsyncDelete で
      プロセスごと落ちるのを避ける)。後始末の最後にメインスレッドで回収する。
    - messagebox の showerror / askyesno は、呼ばれたスレッドがメインスレッドかを記録し、askyesno の答えを
      self.ask_answer で指定できる (例外オブジェクトを入れると、それを raise する)。
    - 費用/実績ログの関数 (estimate_review_cost / record_ai_usage) と GUI の _confirm_ai_cost / _save_review_result は、
      呼び出し順 (self.events) と引数・戻り値を記録するラッパを付ける (中身は本物をそのまま呼ぶ)。
    """

    pump = a1gui.GuiCase.pump
    settle = a1gui.GuiCase.settle
    worker_threads = a1gui.GuiCase.worker_threads
    _patch_thread_excepthook = a1gui.GuiCase._patch_thread_excepthook

    def setUp(self):
        gc.disable()
        self.addCleanup(gc.enable)                              # 最初に登録 = 最後に実行
        super().setUp()                                         # 一時cwd / messagebox の差し替え / 後始末 (GUI の破棄)
        self.thread_errors = []
        self._patch_thread_excepthook()
        self.baseline_threads = set(threading.enumerate())
        self.events = []                  # 呼び出し順 (mails:YYYYMM/group/cal:YYYYMM/estimate/confirm/generate/record/save_result/report:<person>/browser)
        self.method_calls = {}            # tag -> [(args, kwargs), ...]
        self.module_reals = {}            # tag -> 差し替え前の本物の関数
        self.results = {}                 # tag -> [戻り値, ...]
        self.statuses = []                # _set_status に渡った (文言, start_timer) (呼ばれた順)
        self.printed = io.StringIO()      # 実行中に print された文字列 (ワーカーのものを含む)
        self.browser_calls = []
        self.start_state = self.mid_state = self.final_state = None
        self.mid_totals = None
        self.start_running = None
        p = mock.patch("webbrowser.open", lambda url, *a, **k: (self.events.append("browser"),
                                                                self.browser_calls.append(url), True)[2])
        p.start()
        self.addCleanup(p.stop)
        for name, tag in (("estimate_review_cost", "estimate"), ("record_ai_usage", "record"),
                          ("count_failed_review_calls", "count_failed")):
            self._spy_module(name, tag)
        self.addCleanup(self._finish_workers)                   # 後始末は後入れ先出し: GUI の破棄より先に走る

    def _finish_workers(self):
        if self.gui is not None and self.worker_threads():
            self.pump(lambda: not self.worker_threads(), timeout=5)
            self.settle(0.05)
        if self.worker_threads():
            self.fail(f"ワーカースレッドが終わらない: {self.worker_threads()}")
        if self.thread_errors:
            self.fail(f"ワーカースレッドの未処理例外: {self.thread_errors}")

    # ---- messagebox ---------------------------------------------------
    def _patch_messagebox(self):
        super()._patch_messagebox()
        self.dialog_threads = []          # [(関数名, メインスレッドで呼ばれたか)]
        self.ask_answer = True            # askyesno の答え。BaseException のインスタンスなら、それを raise する
        for name in ("showerror", "askyesno"):
            inner = getattr(tkmessagebox, name)                  # 基底が入れた記録用の差し替え

            def wrapper(*args, _inner=inner, _name=name, **kwargs):
                self.dialog_threads.append((_name, threading.current_thread() is threading.main_thread()))
                result = _inner(*args, **kwargs)
                if _name == "askyesno":
                    if isinstance(self.ask_answer, BaseException):
                        raise self.ask_answer
                    return self.ask_answer
                return result
            p = mock.patch.object(tkmessagebox, name, wrapper)
            p.start()
            self.addCleanup(p.stop)

    def _destroy(self, gui):
        root = gui.root
        try:
            for aid in root.tk.splitlist(root.tk.call("after", "info")):
                root.after_cancel(aid)
        except Exception:                                       # noqa: BLE001
            pass
        try:
            gui.__dict__.clear()
            gc.collect(0)              # GC を止めていたので、このテストで作ったものは全て最も若い世代にある (全世代の回収は重い)
        except Exception:                                       # noqa: BLE001
            pass
        try:
            root.destroy()
        except Exception:                                       # noqa: BLE001
            pass

    def _teardown_guis(self):
        try:
            super()._teardown_guis()
        finally:
            gc.collect(0)

    def dialog_entries(self, name):
        return [d for d in self.dialogs if d[0] == name]

    @staticmethod
    def title_and_message(entry):
        _name, args, kwargs = entry
        return (args[0] if args else kwargs.get("title")), (args[1] if len(args) > 1 else kwargs.get("message"))

    # ---- 呼び出し記録のラッパ -------------------------------------------------
    def _spy_module(self, name, tag):
        real = getattr(oto(), name, None)
        self.module_reals[tag] = real
        self.method_calls[tag] = []
        self.results[tag] = []
        if real is None:                                        # 未実装の版でも、他のテストが読み込みで落ちないようにする
            return

        def wrapper(*args, **kwargs):
            self.events.append(tag)
            self.method_calls[tag].append((args, kwargs))
            result = real(*args, **kwargs)
            self.results[tag].append(result)
            return result
        p = mock.patch.object(oto(), name, wrapper)
        p.start()
        self.addCleanup(p.stop)

    def _spy_method(self, gui, name, tag):
        real = getattr(gui, name)
        self.method_calls[tag] = []
        self.results[tag] = []

        def wrapper(*args, **kwargs):
            self.events.append(tag)
            self.method_calls[tag].append((args, kwargs))
            result = real(*args, **kwargs)
            self.results[tag].append(result)
            return result
        setattr(gui, name, wrapper)

    # ---- GUI 構築 -----------------------------------------------------
    def make_gui(self, today=None, staffs=None):
        gui = super().make_gui(today, staffs=staffs)
        # 本物の _set_status が使うステータスバーと、費用の見積り・実績ログが読む設定 (MailManagerGUI.__init__ が持つもの)
        gui.lbl_stat = ttk.Label(gui.root, text="Ready")
        gui.lbl_stat.pack(side=tk.BOTTOM, fill=tk.X)
        gui.config = dict(oto().DEFAULT_CONFIG)
        real_status = gui._set_status

        def status_spy(text, start_timer=False, current=0, total=0):
            self.statuses.append((text, start_timer))
            return real_status(text, start_timer, current, total)
        gui._set_status = status_spy
        self._spy_method(gui, "_confirm_ai_cost", "confirm")
        self._spy_method(gui, "_save_review_result", "save_result")
        return gui

    def ui_state(self, gui):
        return {
            "run_state": str(gui.btn_run_review.cget("state")), "run_text": str(gui.btn_run_review.cget("text")),
            "reformat_state": str(gui.btn_reformat_review.cget("state")),
            "reformat_text": str(gui.btn_reformat_review.cget("text")),
            "status": str(gui.lbl_stat.cget("text")),
        }

    def finished(self, gui):
        """最終ステータス (成功/中止/失敗) が出て、ボタンが元に戻った。"""
        return (any(t.startswith(FINAL_PREFIXES) for t, _ in self.statuses)
                and str(gui.btn_run_review.cget("state")) == "normal")

    def execute(self, gui, during=None, timeout=10):
        """gui._run_review() をメインループの中から呼び、最終ステータスとボタンの復帰まで待つ。"""
        started_call = {}

        def press_button():
            try:
                gui._run_review()
                self.start_state = self.ui_state(gui)            # 呼び出し直後 (メインスレッドの同期的な部分)
                self.start_running = getattr(gui, "is_running", None)
            except Exception as e:                              # noqa: BLE001
                started_call["error"] = e

        def press_failed():
            return "error" in started_call

        with contextlib.redirect_stdout(self.printed):
            gui.root.after(0, press_button)
            if during is not None:
                ok = self.pump(lambda: self.started.is_set() or press_failed(), timeout=timeout)
                if press_failed():
                    raise started_call["error"]
                self.assertTrue(ok, f"generate_review_data まで進まない: events={self.events}")
                self.settle(0.02)
                self.mid_state = self.ui_state(gui)
                self.mid_totals = (gui.summarizer.total_input_tokens, gui.summarizer.total_output_tokens)
                during(gui)
                self.gate.set()
            ok = self.pump(lambda: self.finished(gui) or press_failed(), timeout=timeout)
            if press_failed():
                raise started_call["error"]
            self.assertTrue(ok, f"最終ステータスとボタンの復帰まで到達しない: events={self.events}, "
                                f"statuses={self.statuses[-4:]}, ui={self.ui_state(gui)}")
            self.settle(0.05)                                    # 最終ステータスのあとに続く処理が無いことの確認を兼ねる
        self.final_state = self.ui_state(gui)
        return gui

    # ---- 1回分の実行 (スタブ版) ------------------------------------------------
    def flow(self, *, months=("202609",), persons=None, ask=True, log=None, seed_months=None, error_months=(),
             add_in=0, add_out=0, fail=None, report_fail=None, model=None, initial_totals=None, during=None,
             prior_result=None, timeout=10, today=a3m.NOW_1004, cache_effects=None, spend_before_fail=False,
             **outlook_kw):
        """偽Outlook・偽AI・偽レポートを載せて、_run_review を最後まで実行する。

        months      : チェックする月 ("YYYYMM" のタプル。() は「キャッシュのみ」)。既定は前月 (2026-10-04 なら 202609)
        persons     : 対象者 (既定は Ochi だけ。スタッフは Saji / Yuto Oi)。Ochi が先頭
        ask         : 費用確認ダイアログ (askyesno) の答え
        log         : 実績ログ json/ai_usage_log.jsonl に書く行 (dict / str のリスト。画面を作る前に置く)
        seed_months : 月別キャッシュ (analysis_cache/review_monthly/) を置く月 (既定は12か月ぜんぶ = 「未取得」の注記が付かない)
        error_months: その月は「AI失敗」のキャッシュを置く (対象者全員。generate の前から有る状態)
        cache_effects: {(月, 対象者): _error の真偽}。generate_review_data の最中に、その月別キャッシュを書く (AI失敗の再現)
        add_in/out  : generate_review_data が今回加算するトークン
        fail        : generate_review_data が出す例外 / report_fail : レポート生成が出す例外
        prior_result: review_last_result.json の前回の内容 (画面を作る前に置く)
        during      : 指定すると、generate_review_data の最中で止め、その間に during(gui) を実行してから再開する
        outlook_kw  : FlowOutlook への引数 (threads / body / staff_threads / meetings / fetch_error)
        """
        sel_persons = list(persons) if persons else ["Ochi"]
        if log is not None:
            write_log(*log)
        if prior_result is not None:
            write_json(oto().REVIEW_LAST_RESULT_FILE, prior_result)
        seeds = a3m.ALL_1004 if seed_months is None else list(seed_months)
        for mm in seeds:
            for p in sel_persons:
                a3run.put_cache(mm, p, error=(mm in error_months))
        staffs = {p: {} for p in sel_persons if p != "Ochi"}
        gui = self.make_gui(today, staffs=staffs)
        self.set_all_months(False)
        for mm in months:
            gui.v_review_month_vars[mm].set(True)
        for name, var in gui.v_review_person_vars.items():
            var.set(name in sel_persons)
        if model is not None:
            gui.config["gemini_model"] = model
        kw = dict(outlook_kw)
        kw.setdefault("staff_threads", {p: 1 for p in sel_persons if p != "Ochi"})
        self.outlook = gui.outlook = FlowOutlook(self.events, **kw)
        self.gate, self.started = threading.Event(), threading.Event()
        self.addCleanup(self.gate.set)                           # 失敗してもワーカーを止めたままにしない
        self.summarizer = gui.summarizer = FlowSummarizer(self.events, add_in, add_out, fail,
                                                          gate=self.gate if during is not None else None,
                                                          started=self.started, cache_effects=cache_effects,
                                                          spend_before_fail=spend_before_fail)
        if initial_totals is not None:
            gui.summarizer.total_input_tokens, gui.summarizer.total_output_tokens = initial_totals
        self.reporter = gui.reporter = FlowReporter(self.events, fail=report_fail)
        self.ask_answer = ask
        self.sel_persons, self.sel_months = sel_persons, list(months)
        self.execute(gui, during=during, timeout=timeout)
        return gui

    # ---- よく使う読み出し -------------------------------------------------
    def log_records(self):
        return read_log_records()

    def estimate_arguments(self):
        """estimate_review_cost への最初の呼び出しの引数を {名前: 値} で返す。"""
        calls = self.method_calls["estimate"]
        self.assertTrue(calls, "estimate_review_cost が呼ばれていない")
        args, kwargs = calls[0]
        return dict(inspect.signature(self.module_reals["estimate"]).bind(*args, **kwargs).arguments)

    def expected(self, observed=None, model=FLASH, months=None, persons=None):
        """直前の flow の設定 (月・対象者・偽Outlook) から、独立した参照実装で見積りの期待値を作る。
        observed: 実績ログの「1回あたり出力」(あれば ×1.5)。"""
        months = self.sel_months if months is None else months
        persons = self.sel_persons if persons is None else persons
        fo = self.outlook
        monthly, meetings = {}, {}
        for yyyymm in months:
            per = {}
            for p in persons:
                n = fo.threads if p == "Ochi" else fo.staff_threads.get(p, 0)
                per[p] = {f"{p}-{i}": {"mails": [{"body": fo.body}]} for i in range(n)}
            monthly[yyyymm] = per
            meetings[yyyymm] = [{} for _ in range(fo.meetings)]
        n_calls, chars = ref_estimate(monthly, meetings)
        per_call = observed * 1.5 if observed else OUT_DEFAULT
        price = yen_pro if model == PRO else yen_flash
        return {"n_calls": n_calls, "input_chars": chars, "per_call": per_call, "calibrated": bool(observed),
                "yen": price(chars, per_call * n_calls)}

    @staticmethod
    def dialog_text(label, yen, n_calls, calibrated):
        basis = "直近の実績から" if calibrated else "実績がまだ無いため多めに"
        return f"{label}のAI費用の見込み: 約{yen:.0f}円（{n_calls}件。{basis}見積もった概算です）\n\n実行しますか？"

    def final_statuses(self):
        return [(t, st) for t, st in self.statuses if t.startswith(FINAL_PREFIXES)]

    def expected_gap_note(self, persons=None):
        """A3 の「（⚠ 未取得…・AI失敗…あり。…）」通知の期待値。件数の数え方 (進行中の当月は「未取得」に数えない、など) は
        A3 の規則なので、ここでは既存の review_cache_gaps (実行後のキャッシュの状態・固定した「今日」) から作る。
        A7a の仕様は「その通知を (従来どおり) 末尾に付ける」ことだけ。"""
        missing, failed = oto().review_cache_gaps(a3m.ALL_1004, persons or self.sel_persons, now=a3m.NOW_1004)
        return gap_note(len(missing), len(failed))


# 100円をまたぐ設定 (Ochi・前月だけ・1スレッド1通100字 = 入力 2440 字。実績ログの「1回あたり出力」を変えて振り分ける)
BODY100 = "x" * 100
LOW = dict(body=BODY100, log=[rec("review", 1, 166000)])         # 見込み 99.72円 (1件)
HIGH = dict(body=BODY100, log=[rec("review", 1, 167000)])        # 見込み 100.32円 (1件)
TWO = dict(months=("202608", "202609"), body=BODY100, log=[rec("review", 1, 100000)])   # 見込み 120.2円 (2件)


class TestReviewFlowEstimatePosition(ReviewCostCase):
    """見積りは、取得ループの後・generate_review_data の前に、取得したデータそのものに対して行う。"""

    def test_estimate_comes_after_the_whole_fetch_loop_and_before_generate(self):
        """呼び出し順: 全ての月の取得 → 見積り → (確認) → generate_review_data。"""
        self.flow(months=("202607", "202608", "202609"), **LOW)
        order = [e for e in self.events if e.startswith(("mails:", "cal:")) or e in ("estimate", "confirm", "generate")]
        self.assertEqual(order, ["mails:202607", "cal:202607", "mails:202608", "cal:202608", "mails:202609", "cal:202609",
                                 "estimate", "confirm", "generate"])

    def test_estimate_is_after_the_last_fetch_not_inside_the_loop(self):
        """見積りは取得ループの途中ではなく、最後の月の取得が終わった後に1回だけ。"""
        self.flow(months=("202608", "202609"), **LOW)
        self.assertEqual(self.events.count("estimate"), 1)
        self.assertGreater(self.events.index("estimate"), self.events.index("cal:202609"))
        self.assertLess(self.events.index("estimate"), self.events.index("generate"))

    def test_fetch_order_is_unchanged_mails_then_group_then_calendar_oldest_month_first(self):
        """取得の順序は従来どおり: 古い月から、月ごとに メール取得 → スレッド化 → 会議取得。"""
        self.flow(months=("202609", "202607", "202608"), **LOW)             # チェックの順序に関わらず古い月から
        fetch = [e for e in self.events if e.startswith(("mails:", "cal:")) or e == "group"]
        self.assertEqual(fetch, ["mails:202607", "group", "cal:202607", "mails:202608", "group", "cal:202608",
                                 "mails:202609", "group", "cal:202609"])

    def test_estimate_is_called_once_with_the_fetched_threads_and_meetings(self):
        """見積りに渡すのは、取得して対象者ごとに絞ったスレッド (月×対象者) と会議の月別辞書で、generate に渡すものと同じ内容。"""
        gui = self.flow(months=("202608", "202609"), persons=["Ochi", "Saji"], **LOW, meetings=3)
        args = self.estimate_arguments()
        self.assertEqual(len(self.method_calls["estimate"]), 1)
        self.assertEqual(sorted(args["monthly_threads"]), ["202608", "202609"])
        for yyyymm in ("202608", "202609"):
            self.assertEqual(sorted(args["monthly_threads"][yyyymm]), ["Ochi", "Saji"])
            for person in ("Ochi", "Saji"):
                self.assertEqual(len(args["monthly_threads"][yyyymm][person]), 1)
            self.assertEqual(len(args["monthly_meetings"][yyyymm]), 3)
        call = gui.summarizer.calls[0]
        self.assertEqual(args["monthly_threads"], call["monthly_threads"])
        self.assertEqual(args["monthly_meetings"], call["monthly_meetings"])

    def test_estimate_gets_the_configured_model(self):
        """見積りは設定 (config) の gemini_model で行う。"""
        self.flow(**LOW, model=PRO)
        self.assertEqual(self.estimate_arguments()["model"], PRO)

    def test_estimate_gets_the_default_model_when_the_config_has_the_default(self):
        """設定が既定なら、既定のモデル (gemini-2.5-flash) で見積もる。"""
        self.flow(**LOW)
        self.assertEqual(self.estimate_arguments()["model"], FLASH)

    def test_the_result_of_the_estimate_matches_the_reference(self):
        """見積りの件数・入力文字数は、取得した内容から独立に計算した値 (Ochi・スタッフ・会議つき) と一致する。"""
        self.flow(months=("202608", "202609"), persons=["Ochi", "Saji"], threads=2, body="あ" * 300, meetings=4,
                  staff_threads={"Saji": 3})
        exp = self.expected()
        got = self.results["estimate"][0]
        self.assertEqual(got["n_calls"], exp["n_calls"])
        self.assertEqual(exp["n_calls"], 4)
        self.assertEqual(got["input_chars"], exp["input_chars"])

    def test_staff_threads_that_do_not_qualify_are_not_counted(self):
        """見積りは機械フィルタ後の (対象者ごとの) スレッドで行う: スタッフのスレッドが無ければ、その組は数えない。"""
        self.flow(persons=["Ochi", "Saji"], staff_threads={"Saji": 0}, **LOW)
        self.assertEqual(self.results["estimate"][0]["n_calls"], 1)

    def test_estimate_is_not_made_when_the_fetch_fails(self):
        """取得で失敗したら、見積りも確認も generate も行わない。"""
        self.flow(fetch_error=RuntimeError("Outlookから取得できません"), **LOW)
        self.assertEqual(self.method_calls["estimate"], [])
        self.assertNotIn("generate", self.events)
        self.assertNotIn("confirm", self.events)

    def test_estimate_is_printed_when_something_needs_analysis(self):
        """AI分析が必要なら、費用の見込みを print する (「💰 振り返りのAI費用の見込み: …」)。"""
        self.flow(**LOW)
        self.assertIn(ESTIMATE_PRINT_HEAD, self.printed.getvalue())

    def test_estimate_is_not_printed_when_nothing_needs_analysis(self):
        """AI分析が0件なら、見込みは print しない。"""
        self.flow(threads=0)
        self.assertNotIn(ESTIMATE_PRINT_HEAD, self.printed.getvalue())

    def test_confirm_is_called_with_the_estimate_and_the_label(self):
        """確認 (_confirm_ai_cost) を、見積りとラベル「振り返り」で呼ぶ。"""
        self.flow(**LOW)
        calls = self.method_calls["confirm"]
        self.assertEqual(len(calls), 1)
        args, kwargs = calls[0]
        bound = inspect.signature(oto().MailManagerGUI._confirm_ai_cost).bind(None, *args, **kwargs).arguments
        self.assertEqual(bound["label"], REVIEW_LABEL)
        self.assertEqual(bound["estimate"], self.results["estimate"][0])
        self.assertEqual(bound["estimate"]["n_calls"], 1)


class TestReviewFlowNothingToAnalyze(ReviewCostCase):
    """n_calls==0 (キャッシュ読み込みだけ): 確認ダイアログも実績ログも無く、完了表示は「（新しい分析は不要でした）」。"""

    def test_no_threads_shows_no_confirmation_dialog(self):
        """対象のスレッドが無ければ、確認ダイアログを出さない。"""
        self.flow(threads=0)
        self.assertEqual(self.dialog_entries("askyesno"), [])

    def test_no_threads_writes_no_usage_log(self):
        """record_ai_usage を呼ばず、実績ログも作らない。"""
        self.flow(threads=0)
        self.assertEqual(self.method_calls["record"], [], "分析が0件なのに record_ai_usage を呼んだ")
        self.assertFalse(os.path.exists(LOG_PATH))

    def test_no_threads_still_generates_the_report_from_the_cache(self):
        """分析0件でも、generate_review_data を1回呼んでキャッシュからレポートを作る (従来どおり)。"""
        gui = self.flow(threads=0)
        self.assertEqual(len(gui.summarizer.calls), 1)
        self.assertEqual(len(self.reporter.calls), 1)
        self.assertEqual(len(self.browser_calls), 1)
        self.assertTrue(os.path.exists(oto().REVIEW_LAST_RESULT_FILE))

    def test_no_threads_status_says_no_new_analysis_was_needed(self):
        """完了表示は「✅ 振り返り生成完了（新しい分析は不要でした）」。"""
        self.flow(threads=0)
        self.assertEqual(self.final_state["status"], DONE_TEXT + NO_NEW_TEXT)
        self.assertNotIn("今回のAI費用", self.final_state["status"])

    def test_a_cache_only_run_has_zero_calls_and_fetches_nothing(self):
        """月を1つもチェックしない (キャッシュのみ) 実行は、取得もせず、0件・確認なし・実績ログなし。"""
        gui = self.flow(months=())
        self.assertEqual(self.outlook.fetched, [])
        self.assertEqual(self.results["estimate"][0]["n_calls"], 0)
        self.assertEqual(self.dialog_entries("askyesno"), [])
        self.assertFalse(os.path.exists(LOG_PATH))
        self.assertEqual(len(gui.summarizer.calls), 1)
        self.assertEqual(self.final_state["status"], DONE_TEXT + NO_NEW_TEXT)

    def test_the_gap_note_still_follows_at_the_end(self):
        """A3 の「（⚠ 未取得…）」通知は、従来どおり末尾に続く (「新しい分析は不要でした」の後ろ)。"""
        self.flow(threads=0, seed_months=a3m.ALL_1004[:10])                     # 後ろの2か月 (うち1つは進行中の当月) のキャッシュが無い
        note = self.expected_gap_note()
        self.assertIn("未取得", note, "前提: 未取得の月がある")
        self.assertEqual(self.final_state["status"], DONE_TEXT + NO_NEW_TEXT + note)

    def test_no_dialog_even_with_a_huge_track_record(self):
        """実績ログの1回あたり出力が巨大でも、0件なら費用は0円で確認しない。"""
        self.flow(threads=0, log=[rec("review", 1, 5_000_000)])
        self.assertEqual(self.dialog_entries("askyesno"), [])
        self.assertEqual(len(self.summarizer.calls), 1)

    def test_empty_person_threads_are_zero_calls_even_if_the_month_is_checked(self):
        """チェックした月でも、対象者のスレッドが0なら (空キャッシュを書くだけで AI は呼ばないので) 0件。"""
        self.flow(months=("202608", "202609"), threads=0)
        self.assertEqual(self.results["estimate"][0]["n_calls"], 0)
        self.assertEqual(self.method_calls["confirm"], [])


class TestReviewFlowUnderTheThreshold(ReviewCostCase):
    """100円未満の見込みは、確認なしで実行する。"""

    def test_just_under_100_yen_shows_no_dialog_and_continues(self):
        """見込み 99.7円 (1件) は、確認ダイアログを出さず、そのまま実行する。"""
        gui = self.flow(**LOW)
        self.assertLess(self.expected(observed=166000)["yen"], 100)                  # 前提
        self.assertEqual(self.results["estimate"][0]["n_calls"], 1)
        self.assertIs(self.results["estimate"][0]["needs_confirm"], False)
        self.assertEqual(self.dialog_entries("askyesno"), [])
        self.assertEqual(len(gui.summarizer.calls), 1)

    def test_default_run_is_far_under_the_threshold(self):
        """既定 (前月のみ × Ochi・実績なし) は数円で、確認なしに実行する。"""
        gui = self.flow()
        self.assertEqual(self.dialog_entries("askyesno"), [])
        self.assertEqual(len(gui.summarizer.calls), 1)
        self.assertLess(self.results["estimate"][0]["yen"], 10)

    def test_the_run_finishes_normally_with_the_cost_text(self):
        """完了表示は「✅ 振り返り生成完了（今回のAI費用 約N円・1件）」。"""
        self.flow(add_in=1_000_000, add_out=100_000)
        self.assertEqual(self.final_state["status"], DONE_TEXT + cost_text(88.0, 1))

    def test_under_100_yen_prints_the_estimate_but_shows_no_dialog(self):
        """確認ダイアログは出ないが、見込みは print される。"""
        self.flow(**LOW)
        self.assertEqual(self.dialogs, [])
        self.assertIn(ESTIMATE_PRINT_HEAD, self.printed.getvalue())


class TestReviewFlowAtTheThreshold(ReviewCostCase):
    """100円以上の見込みは、実行前に確認ダイアログを出す。"""

    def test_at_100_yen_a_confirmation_dialog_is_shown_once(self):
        """見込み 100.3円 (1件) は、確認ダイアログ (askyesno) を1回出す。"""
        self.flow(**HIGH)
        self.assertGreaterEqual(self.expected(observed=167000)["yen"], 100)          # 前提
        self.assertEqual(len(self.dialog_entries("askyesno")), 1)
        self.assertEqual([d[0] for d in self.dialogs], ["askyesno"])

    def test_dialog_has_the_title_and_the_exact_text_with_a_track_record(self):
        """実績ありの確認ダイアログのタイトルと本文 (「振り返りのAI費用の見込み: 約N円」「N件」「直近の実績から」)。"""
        self.flow(**HIGH)
        exp = self.expected(observed=167000)
        title, message = self.title_and_message(self.dialog_entries("askyesno")[0])
        self.assertEqual(title, CONFIRM_TITLE)
        self.assertEqual(message, self.dialog_text(REVIEW_LABEL, exp["yen"], 1, calibrated=True))
        self.assertIn("振り返りのAI費用の見込み: 約100円", message)
        self.assertIn("（1件。直近の実績から見積もった概算です）", message)

    def test_dialog_text_for_two_calls_with_a_track_record(self):
        """2か月ぶん (2件・約120円) の確認ダイアログの本文。"""
        self.flow(**TWO)
        exp = self.expected(observed=100000)
        self.assertEqual(exp["n_calls"], 2)
        _, message = self.title_and_message(self.dialog_entries("askyesno")[0])
        self.assertEqual(message, self.dialog_text(REVIEW_LABEL, exp["yen"], 2, calibrated=True))
        self.assertIn("約120円（2件。", message)

    def test_dialog_text_without_a_track_record(self):
        """実績が無いとき (「全て」× Ochi + スタッフ2人 = 36件・約119円) の本文は「実績がまだ無いため多めに」。"""
        months = a3m.ALL_1004
        self.flow(months=months, persons=["Ochi", "Saji", "Yuto Oi"], threads=1, staff_threads={"Saji": 1, "Yuto Oi": 1})
        exp = self.expected()
        self.assertEqual(exp["n_calls"], 36)
        self.assertGreaterEqual(exp["yen"], 100)
        _, message = self.title_and_message(self.dialog_entries("askyesno")[0])
        self.assertEqual(message, self.dialog_text(REVIEW_LABEL, exp["yen"], 36, calibrated=False))
        self.assertIn("36件。実績がまだ無いため多めに見積もった概算です", message)

    def test_the_dialog_is_decided_by_the_estimate_needs_confirm_flag(self):
        """確認ダイアログが出るのは、見積りの needs_confirm が真のときだけ (件数ではなく金額で決まる)。"""
        self.flow(**HIGH)
        self.assertIs(self.results["estimate"][0]["needs_confirm"], True)
        self.assertEqual(self.results["estimate"][0]["n_calls"], 1)                 # 1件でも100円以上なら出る
        self.assertEqual(len(self.dialog_entries("askyesno")), 1)

    def test_the_dialog_has_the_main_window_as_parent_and_defaults_to_no(self):
        """(追記) 確認ダイアログは、メインウィンドウを親にし、既定のボタンは「いいえ」 (誤って Enter で費用を使わない)。"""
        gui = self.flow(**HIGH)
        _name, _args, kwargs = self.dialog_entries("askyesno")[0]
        self.assertIs(kwargs.get("parent"), gui.root)
        self.assertEqual(kwargs.get("default"), "no")

    def test_dialog_is_shown_from_the_main_thread(self):
        """確認ダイアログはメインスレッドで出す (ワーカーから直接出さない)。"""
        self.flow(**HIGH)
        self.assertEqual([t for t in self.dialog_threads if t[0] == "askyesno"], [("askyesno", True)])

    def test_the_dialog_comes_after_the_estimate_and_before_generate(self):
        """確認ダイアログは、見積りの後・generate_review_data の前。"""
        self.flow(**HIGH)
        self.assertLess(self.events.index("estimate"), self.events.index("confirm"))
        self.assertLess(self.events.index("confirm"), self.events.index("generate"))

    def test_dialog_follows_the_configured_model_price(self):
        """確認ダイアログの金額は、設定のモデルの単価 (pro は flash より高い) で計算される。"""
        self.flow(**HIGH, model=PRO)
        exp = self.expected(observed=167000, model=PRO)
        _, message = self.title_and_message(self.dialog_entries("askyesno")[0])
        self.assertIn(f"約{exp['yen']:.0f}円（", message)

    def test_answering_yes_runs_the_analysis_and_finishes_normally(self):
        """「はい」なら従来どおり生成する (generate・実績ログ・結果の保存・レポート・ブラウザ)。"""
        gui = self.flow(**HIGH, ask=True, add_in=1000, add_out=100)
        self.assertEqual(len(gui.summarizer.calls), 1)
        recs = self.log_records()
        self.assertEqual(len(recs), 2, "既存の1行 (HIGH の実績) + 今回の1行になるはず")
        self.assertEqual((recs[-1]["feature"], recs[-1]["n_calls"]), ("review", 1))
        self.assertTrue(os.path.exists(oto().REVIEW_LAST_RESULT_FILE))
        self.assertEqual(len(self.reporter.calls), 1)
        self.assertEqual(self.browser_calls, ["/tmp/review-Ochi.html"])
        self.assertTrue(self.final_state["status"].startswith(DONE_TEXT))
        self.assertEqual(self.dialog_entries("showerror"), [])


class TestReviewFlowCancel(ReviewCostCase):
    """確認ダイアログで「いいえ」(中止): AI分析も出力もしない。"""

    PREVIOUS = {"raw_achievements": [], "months": ["202601"], "persons": ["Ochi"], "period_label": "前回の結果",
                "total_input": 11, "total_output": 22}

    def cancelled(self, **kw):
        """見込み 100.3円 (1件) で確認が出て「いいえ」を押した実行 (前回の結果・実績ログ・月別キャッシュがある状態から)。"""
        kw.setdefault("prior_result", self.PREVIOUS)
        params = dict(HIGH)
        params.update(kw)
        return self.flow(ask=False, **params)

    def test_cancel_does_not_call_generate_review_data(self):
        """「いいえ」なら generate_review_data を呼ばない (AI分析をしない)。"""
        gui = self.cancelled()
        self.assertEqual(gui.summarizer.calls, [])
        self.assertNotIn("generate", self.events)

    def test_cancel_generates_no_html_and_opens_no_browser(self):
        """「いいえ」なら、HTMLもブラウザも出さない。"""
        gui = self.cancelled()
        self.assertEqual(gui.reporter.calls, [])
        self.assertEqual(self.browser_calls, [])
        self.assertFalse([e for e in self.events if e.startswith("report")])

    def test_cancel_does_not_write_review_last_result_json(self):
        """「いいえ」なら review_last_result.json を (保存関数の呼び出しも含め) 書かない。"""
        self.cancelled()
        self.assertEqual(self.method_calls["save_result"], [], "中止なのに _save_review_result を呼んだ")
        self.assertEqual(read_json(oto().REVIEW_LAST_RESULT_FILE), self.PREVIOUS, "前回の結果が上書きされた")

    def test_cancel_does_not_change_the_monthly_cache_folder(self):
        """「いいえ」なら、月別キャッシュ (analysis_cache/review_monthly/) のファイルを増減・書き換えしない。"""
        # 中止の実行でファイルが変わらないことを、画面を作る前の状態との比較で確かめる
        self.cancelled()
        before_names = sorted(f"{m}.json" for m in a3m.ALL_1004)
        self.assertEqual(sorted(os.listdir(oto().REVIEW_CACHE_DIR)), before_names)
        for mm in a3m.ALL_1004:
            with open(os.path.join(oto().REVIEW_CACHE_DIR, f"{mm}.json"), "rb") as f:
                body = json.loads(f.read().decode("utf-8"))
            self.assertEqual(body["achievements"][0]["year_month"], mm, "キャッシュの中身が変わった")

    def test_cancel_changes_no_file_at_all(self):
        """「いいえ」なら、どのファイルも作らず・書き換えない (中身と更新時刻を含めた全ファイルの比較)。"""
        self.flow_with_snapshot(ask=False)
        self.assertEqual(self.after, self.before, "中止なのに、ファイルが作られた/書き換えられた")

    def flow_with_snapshot(self, **kw):
        """画面を作った後・ボタンを押す直前のファイルの状態を取って、flow を実行する。"""
        before = {}
        real_execute = self.execute

        def execute(gui, during=None, timeout=10):
            before["files"] = snapshot_files(".")
            return real_execute(gui, during=during, timeout=timeout)
        self.execute = execute
        params = dict(HIGH, prior_result=self.PREVIOUS)
        params.update(kw)
        self.flow(**params)
        self.before, self.after = before["files"], snapshot_files(".")

    def test_cancel_writes_no_usage_log(self):
        """「いいえ」なら、実績ログを書かない (record_ai_usage を呼ばない・既存の実績ログは変わらない)。"""
        self.cancelled(log=[rec("review", 1, 167000)])
        self.assertEqual(self.method_calls["record"], [], "中止なのに record_ai_usage を呼んだ")
        self.assertEqual(self.log_records(), [rec("review", 1, 167000)])

    def test_cancel_with_no_usage_log_creates_none(self):
        """実績ログが無い状態で中止しても、実績ログは作られない (多めの見積りで確認が出る「全て」の場合)。"""
        self.flow(ask=False, months=a3m.ALL_1004, persons=["Ochi", "Saji", "Yuto Oi"], staff_threads={"Saji": 1, "Yuto Oi": 1})
        self.assertEqual(len(self.dialog_entries("askyesno")), 1)
        self.assertFalse(os.path.exists(LOG_PATH))
        self.assertEqual(self.method_calls["record"], [])

    def test_cancel_status_is_the_cancelled_message(self):
        """終了ステータスは「⏹ 費用の確認で中止しました（AI分析は行っていません）」。"""
        self.cancelled()
        self.assertEqual(self.final_state["status"], CANCELLED_STATUS)

    def test_cancel_status_does_not_claim_success(self):
        """中止のステータスに「✅」「完了」「失敗」を出さない。"""
        self.cancelled()
        for word in ("✅", "完了", "失敗", "❌"):
            self.assertNotIn(word, self.final_state["status"])

    def test_cancel_restores_the_button(self):
        """「いいえ」でもボタンを元の文言・有効に戻す。"""
        self.cancelled()
        self.assertEqual((self.final_state["run_state"], self.final_state["run_text"]), ("normal", RUN_TEXT))

    def test_cancel_stops_the_status_timer(self):
        """「いいえ」でもステータスのタイマーを止める (start_timer=False)。"""
        gui = self.cancelled()
        self.assertIs(gui.is_running, False)
        self.assertEqual(self.final_statuses()[-1], (CANCELLED_STATUS, False))

    def test_cancel_leaves_the_reformat_button_as_it_was(self):
        """中止では「🎨 フォーマットのみ再生成」の状態・文言を変えない (前回の結果が無ければ無効のまま)。"""
        self.flow(ask=False, **HIGH)                                          # 前回の結果なし
        self.assertEqual((self.final_state["reformat_state"], self.final_state["reformat_text"]), ("disabled", REFORMAT_TEXT))
        self.assertFalse(os.path.exists(oto().REVIEW_LAST_RESULT_FILE))

    def test_cancel_with_no_previous_result_writes_no_result(self):
        """前回の結果が無い状態で中止しても、review_last_result.json は作られない。"""
        self.flow(ask=False, **HIGH)
        self.assertFalse(os.path.exists(oto().REVIEW_LAST_RESULT_FILE))
        self.assertEqual(self.method_calls["save_result"], [])

    def test_cancel_shows_no_error_dialog(self):
        """中止はエラーではないので、エラーダイアログは出さない。"""
        self.cancelled()
        self.assertEqual(self.dialog_entries("showerror"), [])

    def test_cancel_after_the_estimate_was_printed(self):
        """中止する場合でも、見込みは print 済み。"""
        self.cancelled()
        self.assertIn(ESTIMATE_PRINT_HEAD, self.printed.getvalue())

    def test_cancel_leaves_the_token_totals_unchanged(self):
        """中止すると、トークン累計は実行前の値のまま (A7c fix1: 0へ戻すのは費用の確認の後・generate_review_data の直前。
        確認で中止しただけで、他の画面で実行中のAIの集計を0にしない)。"""
        gui = self.cancelled(initial_totals=(777_000, 555_000))
        self.assertEqual((gui.summarizer.total_input_tokens, gui.summarizer.total_output_tokens), (777_000, 555_000))

    def test_cancel_in_a_multi_person_run_also_does_nothing(self):
        """複数人・複数月の実行 (「全て」× 3人 = 36件) で中止しても、AI・出力は何も行わない。"""
        gui = self.flow(ask=False, months=a3m.ALL_1004, persons=["Ochi", "Saji", "Yuto Oi"],
                        staff_threads={"Saji": 1, "Yuto Oi": 1})
        self.assertEqual(gui.summarizer.calls, [])
        self.assertEqual(gui.reporter.calls, [])
        self.assertEqual(self.browser_calls, [])
        self.assertEqual(self.final_state["status"], CANCELLED_STATUS)


class TestSpecGapReviewFlowCancel(ReviewCostCase):
    """仕様が曖昧/未記載の点 (確認ダイアログが例外を出したとき)。"""

    def test_a_failing_confirmation_dialog_does_not_start_the_analysis(self):
        """確認ダイアログが例外を出しても、確認なしでAI分析を始めない (中止または失敗として終わり、ボタンは戻る)。"""
        # 仕様は「ダイアログ内で例外が出ても呼び出し側が固まらない」だけ (A1.1)。確認できなかったときに実行へ進む
        # (= 費用を使う) のは危険なので、実行しない側に倒れると解釈する
        gui = self.flow(ask=RuntimeError("テスト用のダイアログ例外"), **HIGH)
        self.callback_errors[:] = [e for e in self.callback_errors if "テスト用のダイアログ例外" not in e]
        self.assertEqual(gui.summarizer.calls, [])
        self.assertEqual(self.final_state["run_state"], "normal")
        self.assertEqual(self.browser_calls, [])


class TestReviewFlowSuccess(ReviewCostCase):
    """成功時: 実績ログへの追記・今回のAI費用の表示・A3の「未取得」通知・結果の保存とレポート。"""

    def test_success_appends_one_usage_line_for_the_run(self):
        """分析した実行は、実績ログに1行 (feature=review・見積りの件数・今回のトークン・モデル) 追記する。"""
        self.flow(months=("202607", "202608", "202609"), body=BODY100, add_in=1_000_000, add_out=100_000)
        recs = self.log_records()
        self.assertEqual(len(recs), 1)
        d = recs[0]
        self.assertEqual((d["feature"], d["n_calls"], d["input_tokens"], d["output_tokens"], d["model"]),
                         ("review", 3, 1_000_000, 100_000, FLASH))

    def test_usage_n_calls_is_the_estimated_count(self):
        """実績ログの n_calls は、見積りの件数 (月×対象者)。"""
        self.flow(months=("202608", "202609"), persons=["Ochi", "Saji"], add_in=10, add_out=5)
        self.assertEqual(self.log_records()[0]["n_calls"], self.results["estimate"][0]["n_calls"])
        self.assertEqual(self.log_records()[0]["n_calls"], 4)

    def test_record_ai_usage_is_called_with_the_specified_arguments(self):
        """record_ai_usage("review", n_calls, 今回の入力, 今回の出力, 今回費用, モデル) の形で呼ぶ。"""
        self.flow(add_in=123_456, add_out=7_890)
        calls = self.method_calls["record"]
        self.assertEqual(len(calls), 1)
        args, kwargs = calls[0]
        bound = inspect.signature(self.module_reals["record"]).bind(*args, **kwargs).arguments
        self.assertEqual(bound["feature"], "review")
        self.assertEqual(bound["n_calls"], 1)
        self.assertEqual((bound["input_tokens"], bound["output_tokens"]), (123_456, 7_890))
        self.assertAlmostEqual(bound["yen"], oto().calc_api_cost_yen(123_456, 7_890, FLASH), places=2)
        self.assertEqual(bound["model"], FLASH)

    def test_usage_line_has_this_runs_cost_not_the_estimate(self):
        """実績ログの円は、見込みではなく今回の実際のトークンから計算した値。"""
        self.flow(add_in=1_000_000, add_out=100_000)
        self.assertAlmostEqual(self.log_records()[0]["yen"], 88.0, places=2)

    def test_usage_line_is_a_complete_record(self):
        """実績ログの行は仕様の7つのキーを持ち、at の形式が正しい。"""
        self.flow(add_in=10, add_out=5)
        d = self.log_records()[0]
        self.assertEqual(sorted(d), sorted(LOG_KEYS))
        self.assertRegex(d["at"], AT_RE)

    def test_usage_tokens_are_this_runs_only_not_the_accumulated_totals(self):
        """実績ログのトークンは今回分だけ (前回までの累計を含まない)。"""
        self.flow(add_in=100, add_out=50, initial_totals=(777_000, 555_000))
        d = self.log_records()[0]
        self.assertEqual((d["input_tokens"], d["output_tokens"]), (100, 50))

    def test_usage_line_follows_the_configured_model(self):
        """実績ログのモデルと円は、設定のモデルに従う。"""
        self.flow(add_in=1_000_000, add_out=100_000, model=PRO)
        d = self.log_records()[0]
        self.assertEqual(d["model"], PRO)
        self.assertAlmostEqual(d["yen"], yen_pro(1_000_000, 100_000), places=2)

    def test_usage_is_appended_after_existing_lines(self):
        """実績ログは既存の行の後ろに追記する (上書きしない)。"""
        self.flow(add_in=10, add_out=5, log=[rec("action", 2, 4000), rec("review", 1, 9)])
        recs = self.log_records()
        self.assertEqual([r["feature"] for r in recs], ["action", "review", "review"])
        self.assertEqual(recs[0], rec("action", 2, 4000))
        self.assertEqual(recs[1], rec("review", 1, 9))

    def test_usage_is_written_once_per_run(self):
        """実績ログへの記録は1実行につき1回。"""
        self.flow(months=("202608", "202609"), add_in=1, add_out=1)
        self.assertEqual(len(self.method_calls["record"]), 1)

    def test_the_next_estimate_is_calibrated_by_this_runs_usage(self):
        """今回の実績が、次回の見積りの校正に使われる (feature=review)。"""
        self.flow(months=("202608", "202609"), add_in=100, add_out=6000)           # 2件・出力6000 → 実績 3000/回
        e = oto().estimate_review_cost(one({"c": {"mails": []}}), {}, None)
        self.assertAlmostEqual(e["output_tokens_per_call"], 4500.0)
        self.assertIs(e["calibrated"], True)

    def test_status_shows_this_runs_cost_and_calls(self):
        """完了表示は「✅ 振り返り生成完了（今回のAI費用 約88.0円・3件）」。"""
        self.flow(months=("202607", "202608", "202609"), add_in=1_000_000, add_out=100_000)
        self.assertEqual(self.final_state["status"], DONE_TEXT + cost_text(88.0, 3))

    def test_cost_in_the_status_uses_one_decimal_and_the_actual_tokens(self):
        """ステータスの費用は小数1桁で、実際のトークンから計算する。"""
        self.flow(months=("202608", "202609"), add_in=123_456, add_out=7_890)
        spent = oto().calc_api_cost_yen(123_456, 7_890)
        self.assertEqual(self.final_state["status"], DONE_TEXT + cost_text(spent, 2))

    def test_status_does_not_say_no_new_analysis_when_analyzed(self):
        """分析したときは「新しい分析は不要でした」を出さない。"""
        self.flow(add_in=10, add_out=10)
        self.assertNotIn("新しい分析は不要でした", self.final_state["status"])

    def test_gap_note_follows_the_cost_text_at_the_end(self):
        """A3 の「（⚠ 未取得…）」通知は、費用の表示の後ろ (末尾) に続く。"""
        self.flow(months=("202609",), add_in=1_000_000, add_out=100_000, seed_months=a3m.ALL_1004[:9])    # 後ろの3か月のキャッシュが無い
        note = self.expected_gap_note()
        self.assertIn("未取得", note, "前提: 未取得の月がある")
        self.assertEqual(self.final_state["status"], DONE_TEXT + cost_text(88.0, 1) + note)

    def test_gap_note_with_both_missing_and_failed_months(self):
        """未取得とAI失敗の両方があれば「（⚠ 未取得N か月・AI失敗M か月あり。…）」を、費用の文言の後ろに付ける。"""
        self.flow(add_in=1_000_000, add_out=100_000, seed_months=a3m.ALL_1004[:10], error_months=(a3m.ALL_1004[0],))
        note = self.expected_gap_note()
        self.assertIn("未取得", note)
        self.assertIn("AI失敗1か月", note)
        self.assertEqual(self.final_state["status"], DONE_TEXT + cost_text(88.0, 1) + note)

    def test_success_ends_without_the_timer(self):
        """成功時はタイマーを止める (start_timer=False)。"""
        gui = self.flow(add_in=1, add_out=1)
        self.assertIs(gui.is_running, False)
        self.assertIs(self.final_statuses()[-1][1], False)

    def test_success_restores_the_button(self):
        """成功したら、ボタンを有効・元の文言に戻す。"""
        self.flow(add_in=1, add_out=1)
        self.assertEqual((self.final_state["run_state"], self.final_state["run_text"]), ("normal", RUN_TEXT))

    def test_success_shows_no_error_dialog(self):
        """成功したら、エラーダイアログを出さない。"""
        self.flow(add_in=1, add_out=1)
        self.assertEqual(self.dialog_entries("showerror"), [])

    def test_the_final_status_is_the_last_status_set(self):
        """最終ステータスの後に、別のステータス (進捗など) で上書きされない。"""
        self.flow(add_in=1, add_out=1)
        self.assertTrue(self.statuses[-1][0].startswith(DONE_TEXT), self.statuses[-3:])

    def test_the_result_json_is_saved_with_this_runs_totals(self):
        """review_last_result.json に、月・対象者・今回のトークン (前回までの累計ではない) を保存する。"""
        self.flow(add_in=100, add_out=50, initial_totals=(777_000, 555_000))
        saved = read_json(oto().REVIEW_LAST_RESULT_FILE)
        self.assertEqual((saved["total_input"], saved["total_output"]), (100, 50))
        self.assertEqual(saved["months"], a3m.ALL_1004)
        self.assertEqual(saved["persons"], ["Ochi"])
        self.assertEqual(len(self.method_calls["save_result"]), 1)

    def test_the_reformat_button_becomes_enabled(self):
        """成功したら「🎨 フォーマットのみ再生成」が有効になる。"""
        self.flow(add_in=1, add_out=1)
        self.assertEqual(self.final_state["reformat_state"], "normal")

    def test_usage_is_recorded_after_generate_and_before_the_report(self):
        """実績ログは generate_review_data の後・レポート生成の前に書く (HTML生成が失敗しても費用は記録される順序)。"""
        # 仕様の並びは「generate_review_data の後: …record_ai_usage」。レポート生成との前後は明記が無いが、
        # 費用は generate で発生済みなので、レポートより前に記録すると解釈する
        self.flow(add_in=10, add_out=5)
        self.assertLess(self.events.index("generate"), self.events.index("record"))
        self.assertLess(self.events.index("record"), self.events.index("report:Ochi"))

    def test_call_order_of_a_whole_run(self):
        """呼び出し順: 取得 → 見積り → 確認 → generate → 実績ログ → (結果の保存) → レポート → ブラウザ。"""
        self.flow(add_in=10, add_out=5)
        order = [e for e in self.events if e in ("estimate", "confirm", "generate", "record", "save_result", "report:Ochi", "browser")]
        self.assertEqual(order[:3], ["estimate", "confirm", "generate"])
        self.assertLess(order.index("generate"), order.index("record"))
        self.assertLess(order.index("generate"), order.index("save_result"))
        self.assertLess(order.index("save_result"), order.index("report:Ochi"))
        self.assertEqual(order[-1], "browser")


def warn_text(n):
    """(追記2) AI分析に失敗した「月×対象者」が1件以上あるときの、成功表示に代わる先頭の文言。"""
    return f"⚠ 振り返り生成完了（AI失敗{n}件。その月を再実行で再試行）"


def partial_cost_text(yen, ok, n):
    """(追記2) 失敗があるときの費用の文言: 「（今回のAI費用 約X円・成功{n−失敗}/{n}件）」。"""
    return f"（今回のAI費用 約{yen:.1f}円・成功{ok}/{n}件）"


class TestReviewFlowAiFailures(ReviewCostCase):
    """(追記) AI分析に失敗した「月×対象者」があるとき: 実績ログには成功した呼び出しだけを記録し、
    完了表示は「⚠ 振り返り生成は完了（AI分析に失敗した月×対象者がN件。…）」+ 費用の文言 + A3の注記になる。
    失敗数は generate_review_data の後に count_failed_review_calls(monthly_threads) で数える (月別キャッシュの _error)。"""

    COST = dict(add_in=1_000_000, add_out=100_000)               # 今回の費用 88.0円

    # ---- 実績ログ: 成功した呼び出しだけ ----
    def test_when_every_call_failed_nothing_is_recorded(self):
        """全件失敗 (1件中1件) なら、出力トークンがあっても実績ログに記録しない。"""
        self.flow(error_months=("202609",), **self.COST)
        self.assertEqual(self.method_calls["record"], [], "全件失敗なのに record_ai_usage を呼んだ")
        self.assertFalse(os.path.exists(LOG_PATH))

    def test_when_every_call_failed_the_existing_log_is_not_changed(self):
        """全件失敗なら、既存の実績ログはそのまま (失敗の実績で見積りが薄まらない)。"""
        self.flow(error_months=("202609",), log=[rec("review", 1, 9000)], **self.COST)
        self.assertEqual(self.log_records(), [rec("review", 1, 9000)])

    def test_a_partial_failure_records_only_the_successful_calls(self):
        """2件のうち1件が失敗 → 記録する件数 (n_calls) は成功した1件。トークン・費用は今回の合計のまま。"""
        self.flow(months=("202608", "202609"), cache_effects={("202609", "Ochi"): True}, **self.COST)
        recs = self.log_records()
        self.assertEqual(len(recs), 1)
        self.assertEqual((recs[0]["feature"], recs[0]["n_calls"], recs[0]["input_tokens"], recs[0]["output_tokens"]),
                         ("review", 1, 1_000_000, 100_000))
        self.assertAlmostEqual(recs[0]["yen"], 88.0, places=2)

    def test_the_recorded_calls_are_the_estimated_calls_minus_the_failed_ones(self):
        """記録する件数 = 見積りの件数 − 失敗の件数 (3か月 × 2人 = 6件のうち、3組失敗 → 3件)。"""
        self.flow(months=("202607", "202608", "202609"), persons=["Ochi", "Saji"],
                  cache_effects={("202607", "Saji"): True, ("202608", "Ochi"): True, ("202609", "Saji"): True}, **self.COST)
        self.assertEqual(self.results["estimate"][0]["n_calls"], 6)
        self.assertEqual(self.log_records()[0]["n_calls"], 3)

    def test_a_failed_staff_pair_reduces_the_recorded_calls(self):
        """Ochi と Saji の2件のうち Saji だけ失敗 → 記録は1件。"""
        self.flow(persons=["Ochi", "Saji"], cache_effects={("202609", "Saji"): True}, **self.COST)
        self.assertEqual(self.log_records()[0]["n_calls"], 1)

    def test_without_failures_every_call_is_recorded(self):
        """失敗が無ければ、見積りの件数ぶん (2件) を記録する。"""
        self.flow(months=("202608", "202609"), **self.COST)
        self.assertEqual(self.log_records()[0]["n_calls"], 2)

    def test_zero_output_tokens_are_not_recorded(self):
        """今回の出力トークンが0なら (失敗が無くても) 実績ログに記録しない (出力0の実績が見積りを薄めるのを防ぐ)。"""
        self.flow(add_in=5000, add_out=0)
        self.assertEqual(self.method_calls["record"], [])
        self.assertFalse(os.path.exists(LOG_PATH))

    def test_no_tokens_at_all_are_not_recorded(self):
        """入力も出力も0なら記録しない。"""
        self.flow(add_in=0, add_out=0)
        self.assertEqual(self.method_calls["record"], [])

    def test_a_positive_output_is_enough_to_record(self):
        """出力トークンが正なら (入力が0でも) 記録する。"""
        self.flow(add_in=0, add_out=5)
        self.assertEqual(len(self.log_records()), 1)

    def test_zero_output_with_failures_is_not_recorded_either(self):
        """失敗があり出力も0なら、当然記録しない。"""
        self.flow(months=("202608", "202609"), cache_effects={("202609", "Ochi"): True}, add_in=10, add_out=0)
        self.assertEqual(self.method_calls["record"], [])

    def test_record_ai_usage_gets_the_successful_calls_and_this_runs_totals(self):
        """record_ai_usage("review", 成功した件数, 今回の入力, 今回の出力, 今回の費用, モデル) の形で呼ぶ。"""
        self.flow(months=("202608", "202609"), cache_effects={("202609", "Ochi"): True}, add_in=123_456, add_out=7_890,
                  model=PRO)
        args, kwargs = self.method_calls["record"][0]
        bound = inspect.signature(self.module_reals["record"]).bind(*args, **kwargs).arguments
        self.assertEqual((bound["feature"], bound["n_calls"], bound["input_tokens"], bound["output_tokens"], bound["model"]),
                         ("review", 1, 123_456, 7_890, PRO))
        self.assertAlmostEqual(bound["yen"], oto().calc_api_cost_yen(123_456, 7_890, PRO), places=2)

    # ---- 失敗数の数え方 ----
    def test_failures_are_counted_after_generate_from_the_caches_it_wrote(self):
        """失敗数は generate_review_data の後に数える: generate の最中に書かれた _error キャッシュが数えられる。"""
        self.flow(months=("202608", "202609"), cache_effects={("202609", "Ochi"): True}, **self.COST)
        self.assertLess(self.events.index("generate"), self.events.index("count_failed"))
        self.assertTrue(self.final_state["status"].startswith(warn_text(1)), self.final_state["status"])

    def test_an_old_error_cache_that_generate_fixed_is_not_a_failure(self):
        """前回の _error キャッシュがあっても、今回の generate が成功で上書きすれば、失敗ではない (数えるのは generate の後)。"""
        self.flow(error_months=("202609",), cache_effects={("202609", "Ochi"): False}, **self.COST)
        self.assertTrue(self.final_state["status"].startswith(DONE_TEXT), self.final_state["status"])
        self.assertEqual(self.log_records()[0]["n_calls"], 1)

    def test_count_failed_review_calls_gets_the_fetched_monthly_threads(self):
        """count_failed_review_calls には、取得した monthly_threads (見積りに渡したものと同じ内容) を渡す。"""
        self.flow(months=("202608", "202609"), persons=["Ochi", "Saji"], **self.COST)
        self.assertEqual(len(self.method_calls["count_failed"]), 1)
        args, kwargs = self.method_calls["count_failed"][0]
        bound = inspect.signature(self.module_reals["count_failed"]).bind(*args, **kwargs).arguments
        self.assertEqual(bound["monthly_threads"], self.estimate_arguments()["monthly_threads"])

    def test_failures_in_months_that_were_not_checked_are_not_counted(self):
        """チェックしていない月の _error キャッシュは、失敗に数えない (A3 の「AI失敗」の注記だけに出る)。"""
        self.flow(error_months=(a3m.ALL_1004[0],), **self.COST)
        self.assertTrue(self.final_state["status"].startswith(DONE_TEXT), self.final_state["status"])
        self.assertEqual(self.log_records()[0]["n_calls"], 1)

    def test_a_cancelled_run_does_not_count_failures(self):
        """中止した実行は generate の前なので、失敗数を数えない。"""
        self.flow(ask=False, **HIGH)
        self.assertEqual(self.method_calls["count_failed"], [])

    # ---- 完了表示 ----
    def test_failed_calls_change_the_completion_text_to_the_warning(self):
        """失敗が1件以上あれば、「✅ 振り返り生成完了」ではなく「⚠ 振り返り生成は完了（AI分析に失敗した月×対象者がN件。…）」。"""
        self.flow(months=("202608", "202609"), cache_effects={("202609", "Ochi"): True}, **self.COST)
        status = self.final_state["status"]
        self.assertTrue(status.startswith(warn_text(1)), status)
        self.assertNotIn("✅", status)
        self.assertNotIn(DONE_TEXT, status)

    def test_the_number_in_the_warning_is_the_number_of_failed_pairs(self):
        """警告の件数は、失敗した「月×対象者」の数 (Ochi と Saji が同じ月に失敗 → 2件)。"""
        self.flow(persons=["Ochi", "Saji"], cache_effects={("202609", "Ochi"): True, ("202609", "Saji"): True}, **self.COST)
        self.assertTrue(self.final_state["status"].startswith(warn_text(2)), self.final_state["status"])

    def test_when_every_call_failed_the_completion_is_the_warning_too(self):
        """全件失敗でも「⚠ 振り返り生成は完了（… 1件 …）」(成功表示にしない)。"""
        self.flow(error_months=("202609",), **self.COST)
        self.assertTrue(self.final_state["status"].startswith(warn_text(1)), self.final_state["status"])
        self.assertNotIn("✅", self.final_state["status"])

    def test_the_warning_is_followed_by_the_cost_text(self):
        """(追記2) 警告の後ろの費用の文言は「（今回のAI費用 約X円・成功{n−失敗}/{n}件）」(2件中1件失敗 → 成功1/2件)。"""
        self.flow(months=("202608", "202609"), cache_effects={("202609", "Ochi"): True}, **self.COST)
        status = self.final_state["status"]
        self.assertTrue(status.startswith(warn_text(1) + partial_cost_text(88.0, 1, 2)), status)
        self.assertNotIn("新しい分析は不要でした", status)

    def test_when_every_call_failed_the_cost_text_says_zero_succeeded(self):
        """(追記2) 全件失敗 (1件中1件) なら「成功0/1件」。"""
        self.flow(error_months=("202609",), **self.COST)
        self.assertTrue(self.final_state["status"].startswith(warn_text(1) + partial_cost_text(88.0, 0, 1)),
                        self.final_state["status"])

    def test_the_success_count_follows_several_failures(self):
        """(追記2) 3か月 × 2人 = 6件のうち3件失敗 → 「⚠ 振り返り生成完了（AI失敗3件。…）（今回のAI費用 約X円・成功3/6件）」。"""
        self.flow(months=("202607", "202608", "202609"), persons=["Ochi", "Saji"],
                  cache_effects={("202607", "Saji"): True, ("202608", "Ochi"): True, ("202609", "Saji"): True}, **self.COST)
        self.assertTrue(self.final_state["status"].startswith(warn_text(3) + partial_cost_text(88.0, 3, 6)),
                        self.final_state["status"])

    def test_the_whole_warning_status_is_head_cost_and_gap_note(self):
        """(追記2) 失敗ありの完了表示の全体 = 先頭 + 「成功X/N件」の費用の文言 + A3 の通知 (区切りなし)。"""
        self.flow(months=("202608", "202609"), cache_effects={("202609", "Ochi"): True}, **self.COST)
        note = self.expected_gap_note()
        self.assertIn("AI失敗1か月", note)
        self.assertEqual(self.final_state["status"], warn_text(1) + partial_cost_text(88.0, 1, 2) + note)

    def test_the_gap_note_still_comes_last(self):
        """A3 の「（⚠ 未取得/AI失敗…）」通知は、警告と費用の文言の後ろ (末尾) に続く。"""
        self.flow(months=("202608", "202609"), cache_effects={("202609", "Ochi"): True}, seed_months=a3m.ALL_1004[:8], **self.COST)
        status = self.final_state["status"]
        note = self.expected_gap_note()
        self.assertIn("未取得", note)
        self.assertIn("AI失敗1か月", note)
        self.assertTrue(status.endswith(note), status)
        self.assertLess(status.index(WARN_HEAD), status.index("（今回のAI費用"))
        self.assertLess(status.index("（今回のAI費用"), status.index("（⚠ 未取得"))

    def test_without_failures_the_normal_success_text_is_kept(self):
        """失敗が0件なら、従来どおり「✅ 振り返り生成完了」+ 費用の文言。"""
        self.flow(months=("202608", "202609"), **self.COST)
        self.assertEqual(self.final_state["status"], DONE_TEXT + cost_text(88.0, 2))
        self.assertNotIn("⚠ 振り返り生成は完了", self.final_state["status"])

    def test_the_run_still_generates_the_report_and_saves_the_result_when_calls_failed(self):
        """失敗があっても、レポートの生成・結果の保存・ブラウザ表示は従来どおり行う (完了までは同じ)。"""
        self.flow(months=("202608", "202609"), cache_effects={("202609", "Ochi"): True}, **self.COST)
        self.assertEqual(len(self.reporter.calls), 1)
        self.assertEqual(len(self.browser_calls), 1)
        self.assertEqual(len(self.method_calls["save_result"]), 1)
        self.assertEqual(self.dialog_entries("showerror"), [])

    def test_the_warning_restores_the_button_and_stops_the_timer(self):
        """警告で終わるときも、ボタンを戻し、タイマーを止め (start_timer=False)、それが最後のステータス。"""
        gui = self.flow(error_months=("202609",), **self.COST)
        self.assertEqual((self.final_state["run_state"], self.final_state["run_text"]), ("normal", RUN_TEXT))
        self.assertIs(gui.is_running, False)
        self.assertIs(self.final_statuses()[-1][1], False)
        self.assertTrue(self.statuses[-1][0].startswith(WARN_HEAD), self.statuses[-3:])

    def test_the_warning_is_not_an_error_dialog(self):
        """警告はエラーではないので、エラーダイアログは出さない。"""
        self.flow(error_months=("202609",), **self.COST)
        self.assertEqual(self.dialogs, [])


def err_text(exc):
    """(追記) 失敗時のエラーの文字列は f"{型名}: {例外の文字列}" (ダイアログ本文・ステータスの「❌ 失敗しました: …」)。"""
    return f"{type(exc).__name__}: {exc}"


class TestReviewFlowFailure(ReviewCostCase):
    """失敗 (取得や生成の例外): エラーダイアログが実際に出る・ステータスは「❌ 失敗しました: 型名: …」・ボタンが戻る。"""

    MSG = "AI分析で失敗しましたQQQ"

    def failed(self, exc=None, **kw):
        exc = RuntimeError(self.MSG) if exc is None else exc
        self.exc = exc
        return self.flow(fail=exc, **kw)

    def test_failure_shows_the_error_dialog_once(self):
        """失敗したら、エラーダイアログ (showerror) を1回だけ出す (従来はNameErrorで出なかった)。"""
        self.failed()
        self.assertEqual(len(self.dialog_entries("showerror")), 1)

    def test_failure_dialog_has_the_title_and_the_type_name_and_the_exception_text(self):
        """エラーダイアログのタイトルは「エラー」、本文は「型名: 例外の文字列」。"""
        self.failed()
        title, message = self.title_and_message(self.dialog_entries("showerror")[0])
        self.assertEqual((title, message), ("エラー", "RuntimeError: " + self.MSG))

    def test_failure_dialog_is_shown_from_the_main_thread(self):
        """エラーダイアログはメインスレッドで出す。"""
        self.failed()
        self.assertEqual([t for t in self.dialog_threads if t[0] == "showerror"], [("showerror", True)])

    def test_failure_status_shows_the_type_name_and_the_head_of_the_message(self):
        """失敗のステータスは「❌ 失敗しました: 型名: <例外文>」。"""
        self.failed()
        self.assertEqual(self.final_state["status"], FAIL_HEAD + "RuntimeError: " + self.MSG)

    def test_each_exception_type_gets_its_own_type_name(self):
        """型名は例外のクラス名 (ValueError・KeyError・OSError・自作の例外クラス)。ダイアログ本文もステータスも「型名: 例外文」。"""
        class MyOutlookError(Exception):
            pass
        for exc in (ValueError("値がおかしい"), KeyError("k"), OSError("書き込めない"), MyOutlookError("独自の失敗")):
            with self.subTest(exception=type(exc).__name__):
                self.dialogs.clear()
                self.statuses.clear()
                gui = self.failed(exc)
                self.assertEqual(self.title_and_message(self.dialog_entries("showerror")[0])[1], err_text(exc))
                self.assertEqual(self.final_state["status"], FAIL_HEAD + err_text(exc)[:80])
                self.assertTrue(err_text(exc).startswith(type(exc).__name__ + ": "))
                self.close_gui(gui)

    def test_failure_status_keeps_only_the_first_80_characters_of_the_whole_text(self):
        """失敗のステータスは、「型名: 例外文」の先頭80文字だけ (型名も80文字に数える)。"""
        exc = RuntimeError("あ" * 80 + "い" * 40)
        self.failed(exc)
        self.assertEqual(self.final_state["status"], FAIL_HEAD + err_text(exc)[:80])
        self.assertEqual(self.final_state["status"], FAIL_HEAD + "RuntimeError: " + "あ" * 66)
        self.assertNotIn("い", self.final_state["status"])

    def test_failure_status_with_exactly_80_characters_is_not_cut(self):
        """「型名: 例外文」がちょうど80文字なら切らない。"""
        exc = RuntimeError("う" * (80 - len("RuntimeError: ")))
        self.failed(exc)
        self.assertEqual(len(err_text(exc)), 80)
        self.assertEqual(self.final_state["status"], FAIL_HEAD + err_text(exc))

    def test_failure_status_with_81_characters_loses_only_the_last_one(self):
        """81文字なら、最後の1文字だけが切れる。"""
        exc = RuntimeError("え" * (81 - len("RuntimeError: ")))
        self.failed(exc)
        self.assertEqual(len(err_text(exc)), 81)
        self.assertEqual(self.final_state["status"], FAIL_HEAD + err_text(exc)[:80])

    def test_failure_dialog_shows_the_whole_text_even_when_long(self):
        """エラーダイアログには、長くても「型名: 例外文」の全文を出す (80文字で切らない)。"""
        exc = RuntimeError("あ" * 80 + "い" * 40)
        self.failed(exc)
        self.assertEqual(self.title_and_message(self.dialog_entries("showerror")[0])[1], err_text(exc))

    def test_failure_status_does_not_claim_success(self):
        """失敗のステータスに「完了」「✅」を出さない (従来は「✅ 振り返り生成完了」と出ていた)。"""
        self.failed()
        self.assertNotIn("✅", self.final_state["status"])
        self.assertNotIn("完了", self.final_state["status"])
        self.assertFalse([t for t, _ in self.statuses if t.startswith(DONE_TEXT)], "失敗なのに完了表示が一度でも出た")

    def test_failure_restores_the_button(self):
        """失敗してもボタンを元の文言・有効に戻す。"""
        self.failed()
        self.assertEqual((self.final_state["run_state"], self.final_state["run_text"]), ("normal", RUN_TEXT))

    def test_failure_stops_the_status_timer(self):
        """失敗してもステータスのタイマーを止める (start_timer=False)。"""
        gui = self.failed()
        self.assertIs(gui.is_running, False)
        self.assertEqual(self.final_statuses()[-1][1], False)

    def test_failure_status_is_the_last_status_set(self):
        """失敗のステータスの後に、成功の文言で上書きされない。"""
        self.failed()
        self.assertTrue(self.statuses[-1][0].startswith(FAIL_HEAD), self.statuses[-3:])

    def test_failure_does_not_generate_html_or_open_the_browser(self):
        """生成が失敗したら、HTMLもブラウザも出さない。"""
        gui = self.failed()
        self.assertEqual(gui.reporter.calls, [])
        self.assertEqual(self.browser_calls, [])

    def test_failure_does_not_save_the_result(self):
        """生成が失敗したら、review_last_result.json を書かず、「🎨 …」も有効にしない。"""
        self.failed()
        self.assertEqual(self.method_calls["save_result"], [])
        self.assertFalse(os.path.exists(oto().REVIEW_LAST_RESULT_FILE))
        self.assertEqual(self.final_state["reformat_state"], "disabled")

    def test_a_failed_analysis_writes_no_usage_line(self):
        """生成が失敗したときは、実績ログを書かない (「generate_review_data の後」に進まないため)。"""
        # 仕様の実績ログは「generate_review_data の後」。生成が例外なら、そこへ進まない。
        # (AI を途中まで呼んで費用が発生していても記録されない点は仕様に明記が無い → 仕様どおり書かない側で確認する)
        self.failed()
        self.assertEqual(self.method_calls["record"], [])
        self.assertFalse(os.path.exists(LOG_PATH))

    def test_failure_while_fetching_mails_is_reported_and_the_ui_recovers(self):
        """メール取得の失敗も、ダイアログ・ステータス・ボタン復帰が行われる (型名つき)。"""
        self.flow(fetch_error=RuntimeError("Outlookから取得できませんFFF"))
        self.assertEqual(self.title_and_message(self.dialog_entries("showerror")[0]),
                         ("エラー", "RuntimeError: Outlookから取得できませんFFF"))
        self.assertEqual(self.final_state["status"], FAIL_HEAD + "RuntimeError: Outlookから取得できませんFFF")
        self.assertEqual(self.final_state["run_state"], "normal")
        self.assertNotIn("generate", self.events)

    def test_failure_before_the_confirmation_shows_no_confirmation(self):
        """確認の前に失敗したら、確認ダイアログは出さない (多めの見積りになる条件でも)。"""
        self.flow(fetch_error=RuntimeError("取得失敗"), months=a3m.ALL_1004, persons=["Ochi", "Saji", "Yuto Oi"])
        self.assertEqual(self.dialog_entries("askyesno"), [])

    def test_failure_after_a_confirmed_run_still_reports_the_error(self):
        """確認で「はい」を押した後の生成の失敗も、エラーダイアログ・ステータスで知らせる。"""
        self.failed(**HIGH)
        self.assertEqual(len(self.dialog_entries("askyesno")), 1)
        self.assertEqual(len(self.dialog_entries("showerror")), 1)
        self.assertEqual(self.final_state["status"], FAIL_HEAD + err_text(self.exc))

    def test_report_failure_is_reported_and_the_ui_recovers(self):
        """レポート (HTML) 生成の失敗も、ダイアログ・ステータス・ボタン復帰が行われる (型名つき)。"""
        self.flow(report_fail=RuntimeError("HTML生成に失敗RRR"), add_in=1, add_out=1)
        self.assertEqual(self.title_and_message(self.dialog_entries("showerror")[0]),
                         ("エラー", "RuntimeError: HTML生成に失敗RRR"))
        self.assertEqual(self.final_state["status"], FAIL_HEAD + "RuntimeError: HTML生成に失敗RRR")
        self.assertEqual(self.final_state["run_state"], "normal")

    def test_report_failure_keeps_the_usage_line_because_the_analysis_succeeded(self):
        """HTML生成が失敗しても、分析は成功済みなので実績ログは残る (費用は使っている)。"""
        # 実績ログは generate_review_data の直後に書く (成功時の順序の SpecGap と同じ解釈)
        self.flow(report_fail=RuntimeError("HTML生成に失敗RRR"), add_in=100, add_out=50)
        self.assertEqual(len(self.log_records()), 1, "分析は成功したのに実績ログが無い (費用は使っている)")

    def test_failure_with_an_empty_message_still_reports(self):
        """例外の文字列が空でも、エラーダイアログとステータスで失敗を知らせる (成功扱いにしない)。"""
        self.failed(RuntimeError(""))
        self.assertEqual(len(self.dialog_entries("showerror")), 1)
        self.assertTrue(self.final_state["status"].startswith(FAIL_HEAD))
        self.assertEqual(self.title_and_message(self.dialog_entries("showerror")[0])[1], "RuntimeError: ")


SPENT_RE = r"（ここまでのAI費用 約(?P<yen>\d+(?:\.\d+)?)円）"


class TestReviewFlowFailureAfterSpending(ReviewCostCase):
    """(追記2) 途中で例外が出たとき、それまでに使ったAI費用 (calc_api_cost_yen(今回の入力, 今回の出力, モデル)) が0より大きければ、
    ステータスは「❌ 失敗しました: {型名: メッセージの先頭80字}（ここまでのAI費用 約X円）」。0なら末尾なし。実績ログには記録しない。
    ダイアログの本文は従来どおり「型名: メッセージ」。"""

    MSG = "AI分析の途中で失敗しましたZZZ"
    COST = dict(add_in=1_000_000, add_out=100_000)               # 使った費用 88.0円 (flash)

    def spent_failure(self, exc=None, **kw):
        self.exc = RuntimeError(self.MSG) if exc is None else exc
        params = dict(self.COST)
        params.update(kw)
        return self.flow(fail=self.exc, spend_before_fail=True, **params)

    def split(self, status):
        """ステータスを「❌ 失敗しました: 本文」と「（ここまでのAI費用 約X円）」に分ける (形が違えば失敗)。"""
        m = re.fullmatch(re.escape(FAIL_HEAD) + r"(?P<body>.*?)" + SPENT_RE, status, flags=re.S)
        self.assertIsNotNone(m, f"「❌ 失敗しました: …（ここまでのAI費用 約X円）」の形でない: {status!r}")
        return m.group("body"), float(m.group("yen"))

    def test_status_ends_with_the_cost_spent_so_far(self):
        """AIを使った後の例外: ステータスは「❌ 失敗しました: 型名: メッセージ（ここまでのAI費用 約88円前後）」。"""
        self.spent_failure()
        body, yen = self.split(self.final_state["status"])
        self.assertEqual(body, err_text(self.exc))
        self.assertAlmostEqual(yen, 88.0, delta=0.5)

    def test_the_cost_spent_follows_this_runs_tokens_and_the_configured_model(self):
        """ここまでの費用は、今回のトークン (前回までの累計を含まない) と設定のモデルで計算する。"""
        self.spent_failure(model=PRO, initial_totals=(777_000, 555_000))
        _body, yen = self.split(self.final_state["status"])
        self.assertAlmostEqual(yen, yen_pro(1_000_000, 100_000), delta=0.5)

    def test_the_80_character_cut_applies_to_the_error_text_before_the_cost(self):
        """先頭80字に切るのは「型名: メッセージ」の部分で、その後ろに費用を付ける (費用は切られない)。"""
        exc = RuntimeError("あ" * 80 + "い" * 40)
        self.spent_failure(exc)
        body, yen = self.split(self.final_state["status"])
        self.assertEqual(body, err_text(exc)[:80])
        self.assertAlmostEqual(yen, 88.0, delta=0.5)

    def test_the_dialog_text_has_no_cost(self):
        """ダイアログの本文は従来どおり「型名: メッセージ」(費用は付けない)。"""
        self.spent_failure()
        self.assertEqual(self.title_and_message(self.dialog_entries("showerror")[0]), ("エラー", err_text(self.exc)))

    def test_no_usage_line_is_written_for_the_failed_run(self):
        """途中の例外では、使った費用があっても実績ログに記録しない。"""
        self.spent_failure()
        self.assertEqual(self.method_calls["record"], [])
        self.assertFalse(os.path.exists(LOG_PATH))

    def test_the_ui_recovers_and_nothing_claims_success(self):
        """ボタンは戻り、タイマーは止まり、完了 (✅/⚠) の表示は一度も出ない。"""
        gui = self.spent_failure()
        self.assertEqual((self.final_state["run_state"], self.final_state["run_text"]), ("normal", RUN_TEXT))
        self.assertIs(gui.is_running, False)
        self.assertFalse([t for t, _ in self.statuses if t.startswith((DONE_TEXT, WARN_HEAD))])

    def test_no_cost_suffix_when_nothing_was_spent(self):
        """使った費用が0 (AIを使う前の例外) なら、末尾に費用を付けない (従来どおり)。"""
        self.flow(fail=RuntimeError(self.MSG), add_in=1_000_000, add_out=100_000)        # 加算する前に失敗
        self.assertEqual(self.final_state["status"], FAIL_HEAD + "RuntimeError: " + self.MSG)

    def test_no_cost_suffix_when_the_fetch_fails(self):
        """取得の失敗 (AIを使っていない) は、末尾に費用を付けない。"""
        self.flow(fetch_error=RuntimeError("取得できません"))
        self.assertEqual(self.final_state["status"], FAIL_HEAD + "RuntimeError: 取得できません")

    def test_a_tiny_cost_that_rounds_to_zero_adds_no_suffix(self):
        """費用が0円 (calc_api_cost_yen が 0.0 を返すほど少ない) なら、末尾に費用を付けない。"""
        self.spent_failure(add_in=1, add_out=1)                                              # 0.00045円 → 0.0
        self.assertEqual(oto().calc_api_cost_yen(1, 1, FLASH), 0.0)                          # 前提
        self.assertEqual(self.final_state["status"], FAIL_HEAD + err_text(self.exc))

    def test_a_failing_cost_calculation_means_no_suffix(self):
        """費用の計算に失敗したら0として扱い、末尾に費用を付けない (失敗の表示とダイアログは出る)。"""
        # 見積り (estimate_ai_cost_yen) も calc_api_cost_yen を使うので、今回のトークン (100万/10万) での計算だけを失敗させる
        real_calc = oto().calc_api_cost_yen

        def boom_for_this_run(input_tokens, output_tokens, model=None):
            if (input_tokens, output_tokens) == (1_000_000, 100_000):
                raise ValueError("単価が読めない")
            return real_calc(input_tokens, output_tokens, model)
        with mock.patch.object(oto(), "calc_api_cost_yen", boom_for_this_run):
            self.spent_failure()
        self.assertEqual(self.final_state["status"], FAIL_HEAD + err_text(self.exc))
        self.assertEqual(self.title_and_message(self.dialog_entries("showerror")[0])[1], err_text(self.exc))
        self.assertEqual(self.final_state["run_state"], "normal")

    def test_a_report_failure_after_a_successful_analysis_shows_the_cost_and_keeps_one_usage_line(self):
        """分析は成功しレポート生成で失敗: ステータスに「（ここまでのAI費用 約X円）」が付き、実績ログは分析後の1行だけ (例外で増やさない)。"""
        self.flow(report_fail=RuntimeError("HTML生成に失敗RRR"), **self.COST)
        body, yen = self.split(self.final_state["status"])
        self.assertEqual(body, "RuntimeError: HTML生成に失敗RRR")
        self.assertAlmostEqual(yen, 88.0, delta=0.5)
        self.assertEqual(len(self.log_records()), 1)


class TestSpecGapReviewFlowFailureAfterSpending(ReviewCostCase):
    """仕様が曖昧な点 (「約X円」の桁数)。"""

    def test_the_cost_so_far_uses_one_decimal_like_the_success_text(self):
        """「（ここまでのAI費用 約X円）」の X は、成功時の費用の文言と同じ小数1桁。"""
        # 追記2 は「約X円」とだけ書く。成功時の「（今回のAI費用 約{x:.1f}円・…）」と同じ書式と解釈する
        exc = RuntimeError("途中で失敗")
        self.flow(fail=exc, spend_before_fail=True, add_in=123_456, add_out=7_890)
        spent = oto().calc_api_cost_yen(123_456, 7_890, FLASH)
        self.assertEqual(self.final_state["status"], FAIL_HEAD + err_text(exc) + f"（ここまでのAI費用 約{spent:.1f}円）")


class TestReviewFlowUnchanged(ReviewCostCase):
    """変えていないこと: 対象者ごとのHTML生成・取得の順序・A2のトークンリセット・開始時の表示・generate への引数。"""

    def test_start_disables_the_button_with_the_busy_text_and_status(self):
        """開始時: ボタンが無効・「⏳ 取得・分析中...」、ステータスは「📈 振り返りを生成中...」 (タイマーあり)。"""
        self.flow(add_in=1, add_out=1)
        s = self.start_state
        self.assertEqual((s["run_state"], s["run_text"]), ("disabled", RUN_BUSY_TEXT))
        self.assertIn(START_STATUS, s["status"])
        self.assertIs(self.start_running, True)
        self.assertEqual(self.statuses[0], (START_STATUS, True))

    def test_the_button_stays_disabled_while_generating(self):
        """生成の最中も、ボタンは無効のまま。"""
        self.flow(add_in=1, add_out=1, during=lambda gui: None)
        self.assertEqual((self.mid_state["run_state"], self.mid_state["run_text"]), ("disabled", RUN_BUSY_TEXT))

    def test_token_totals_are_reset_to_zero_at_the_start(self):
        """(A2) 開始時にトークン累計を0に戻す (前回までの累計が残っていても、今回の実行分だけにする)。"""
        self.flow(initial_totals=(777_000, 555_000), during=lambda gui: None)
        self.assertEqual(self.mid_totals, (0, 0))

    def test_one_report_per_selected_person_in_order(self):
        """対象者ごとに別々のHTMLを生成する (Ochi が先頭・人数ぶん・filter_person を渡す)。"""
        self.flow(persons=["Saji", "Ochi", "Yuto Oi"], add_in=1, add_out=1)
        self.assertEqual([c["filter_person"] for c in self.reporter.calls], ["Ochi", "Saji", "Yuto Oi"])
        self.assertEqual([e for e in self.events if e.startswith("report:")], ["report:Ochi", "report:Saji", "report:Yuto Oi"])
        self.assertEqual(self.browser_calls, ["/tmp/review-Ochi.html", "/tmp/review-Saji.html", "/tmp/review-Yuto Oi.html"])

    def test_reports_get_this_runs_tokens_and_not_reformat_mode(self):
        """レポートには今回分のトークン (A2) を渡し、フォーマット再生成モードではない。"""
        self.flow(add_in=100, add_out=50, initial_totals=(777_000, 555_000))
        call = self.reporter.calls[0]
        self.assertEqual((call["total_input"], call["total_output"]), (100, 50))
        self.assertIs(call["reformat_mode"], False)

    def test_generate_receives_the_whole_window_the_persons_and_the_staff_names(self):
        """generate_review_data には、画面の12か月・選んだ対象者・登録スタッフ名を渡す (従来どおり)。"""
        gui = self.flow(persons=["Ochi", "Saji"], add_in=1, add_out=1)
        call = gui.summarizer.calls[0]
        self.assertEqual(sorted(call["all_months"]), a3m.ALL_1004)
        self.assertEqual(call["persons"], ["Ochi", "Saji"])
        self.assertEqual(call["staff_names"], ["Saji"])

    def test_only_the_checked_months_are_fetched(self):
        """メールを取得するのはチェックした月だけ (従来どおり)。"""
        self.flow(months=("202608", "202609"), add_in=1, add_out=1)
        self.assertEqual(self.outlook.fetched, [(2026, 8), (2026, 9)])

    def test_the_period_label_is_the_one_from_format_review_period_label(self):
        """レポートの期間表示は従来どおり format_review_period_label が作る (「更新した月」「未取得」)。"""
        self.flow(add_in=1, add_out=1)
        expected = oto().format_review_period_label(a3m.ALL_1004, [(2026, 9)], mode="run", missing_months=[], failed_months=[])
        self.assertEqual(self.reporter.calls[0]["period_label"], expected)
        self.assertEqual(read_json(oto().REVIEW_LAST_RESULT_FILE)["period_label"], expected)


class TestReviewFlowReformatIsUntouched(ReviewCostCase):
    """_reformat_review (フォーマットのみ再生成) は変更なし: AIを呼ばず、見積り・確認・実績ログも無い。"""

    def reformat(self):
        a3run_months = a3m.ALL_1004
        for mm in a3run_months:
            a3run.put_cache(mm, "Ochi")
        write_json(oto().REVIEW_LAST_RESULT_FILE, {"raw_achievements": [], "months": a3run_months, "persons": ["Ochi"],
                                                    "period_label": "x", "total_input": 0, "total_output": 0})
        gui = self.make_gui(a3m.NOW_1004)
        self.summarizer = gui.summarizer = a3run.make_fake_summarizer()
        self.reporter = gui.reporter = FlowReporter(self.events)
        self.events.clear()
        started = {}

        def press():
            try:
                gui._reformat_review()
            except Exception as e:                              # noqa: BLE001
                started["error"] = e
        with contextlib.redirect_stdout(self.printed):
            gui.root.after(0, press)
            ok = self.pump(lambda: any(t.startswith("✅ フォーマット再生成完了") for t, _ in self.statuses) or "error" in started,
                           timeout=10)
            if "error" in started:
                raise started["error"]
            self.assertTrue(ok, f"フォーマット再生成が終わらない: {self.statuses[-3:]}")
            self.settle(0.05)
        return gui

    def test_reformat_does_not_call_the_ai_nor_the_estimate(self):
        """フォーマットのみ再生成は、AI を呼ばず、見積り・確認・実績ログも行わない。"""
        self.reformat()
        self.assertEqual(self.summarizer.ai_calls, [])
        self.assertEqual(self.method_calls["estimate"], [])
        self.assertEqual(self.method_calls["record"], [])
        self.assertEqual(self.method_calls["confirm"], [])
        self.assertEqual(self.dialog_entries("askyesno"), [])
        self.assertFalse(os.path.exists(LOG_PATH))

    def test_reformat_finishes_with_its_own_status_and_restores_its_button(self):
        """終了ステータスは「✅ フォーマット再生成完了」で、ボタンが元に戻る。"""
        gui = self.reformat()
        self.assertEqual(self.statuses[-1][0], "✅ フォーマット再生成完了")
        self.assertEqual((str(gui.btn_reformat_review.cget("state")), str(gui.btn_reformat_review.cget("text"))),
                         ("normal", REFORMAT_TEXT))

    def test_reformat_generates_the_report_in_reformat_mode(self):
        """レポートは reformat_mode=True・トークン0/0 で、対象者ごとに生成する (従来どおり)。"""
        self.reformat()
        self.assertEqual(len(self.reporter.calls), 1)
        call = self.reporter.calls[0]
        self.assertEqual((call["reformat_mode"], call["filter_person"], call["total_input"], call["total_output"]),
                         (True, "Ochi", 0, 0))


# ---- 本物の MailSummarizer (偽AI) と本物のレポート生成を通す統合 ----------------------------------------
def make_counting_summarizer(fail=()):
    """a3run.make_fake_summarizer (AIの呼び出しだけ偽物) に、プロンプトの長さを記録し、今回のトークンを加算する機能を足したもの。"""
    s = a3run.make_fake_summarizer(fail=fail)
    inner = s._run_genai_call_with_schema
    s.prompt_lengths = []

    def counting(prompt, schema, override_model=None):
        s.prompt_lengths.append(len(prompt))
        s.total_input_tokens += len(prompt)
        s.total_output_tokens += 1000
        return inner(prompt, schema, override_model)
    s._run_genai_call_with_schema = counting
    return s


class EndToEndCase(ReviewCostCase):
    """本物の generate_review_data / summarize_review_month / HTMLReportGenerator (AIの呼び出しだけ偽物) を載せた画面の土台。"""

    def e2e(self, *, months=("202609",), persons=None, ask=True, log=None, seed_months=(), fail=(), today=a3m.NOW_1004):
        sel_persons = list(persons) if persons else ["Ochi"]
        if log is not None:
            write_log(*log)
        for mm in seed_months:
            for p in sel_persons:
                a3run.put_cache(mm, p)
        staffs = {p: {} for p in sel_persons if p != "Ochi"}
        gui = self.make_gui(today, staffs=staffs)
        self.set_all_months(False)
        for mm in months:
            gui.v_review_month_vars[mm].set(True)
        for name, var in gui.v_review_person_vars.items():
            var.set(name in sel_persons)
        self.outlook = gui.outlook = a3run.FakeOutlook(with_staff=tuple(p for p in sel_persons if p != "Ochi"))
        self.summarizer = gui.summarizer = make_counting_summarizer(fail=fail)
        real_generate = self.summarizer.generate_review_data

        def generate_spy(*args, **kwargs):
            self.events.append("generate")
            return real_generate(*args, **kwargs)
        self.summarizer.generate_review_data = generate_spy
        gui.reporter = oto().HTMLReportGenerator(os.path.join(os.getcwd(), "out"), 8765)
        self.ask_answer = ask
        self.sel_persons, self.sel_months = sel_persons, list(months)
        self.execute(gui)
        return gui


class TestReviewEndToEnd(EndToEndCase):
    """見積りの件数が実際の AI 呼び出し回数と一致すること、中止でキャッシュ・結果・レポートが何も作られないことを、
    本物の生成処理 (AIの呼び出しだけ偽物) で確かめる。"""

    def test_default_run_estimate_equals_the_real_ai_calls(self):
        """既定 (前月のみ × Ochi): 見積りの件数と、実際に AI が呼ばれた回数がどちらも1回。"""
        self.e2e()
        self.assertEqual(self.results["estimate"][0]["n_calls"], 1)
        self.assertEqual(len(self.summarizer.ai_calls), 1)

    def test_default_run_has_no_dialog_and_ends_with_the_cost_and_the_gap_note(self):
        """既定の実行は確認なしで、完了表示は「✅ 振り返り生成完了（今回のAI費用 約X円・1件）（⚠ 未取得11か月あり。…）」。"""
        self.e2e()
        self.assertEqual(self.dialogs, [])
        spent = yen_flash(sum(self.summarizer.prompt_lengths), 1000)
        note = self.expected_gap_note()
        self.assertIn("未取得", note, "前提: 前月のキャッシュしか無いので、他の月は未取得")
        self.assertEqual(self.final_state["status"], DONE_TEXT + cost_text(spent, 1) + note)

    def test_default_run_usage_line_has_the_actual_tokens(self):
        """既定の実行の実績ログは、実際に使ったトークン (偽AIが数えたもの) と呼び出し回数1。"""
        self.e2e()
        recs = read_log_records()
        self.assertEqual(len(recs), 1)
        d = recs[0]
        self.assertEqual((d["feature"], d["n_calls"], d["model"]), ("review", 1, FLASH))
        self.assertEqual((d["input_tokens"], d["output_tokens"]), (sum(self.summarizer.prompt_lengths), 1000))
        self.assertAlmostEqual(d["yen"], yen_flash(sum(self.summarizer.prompt_lengths), 1000), places=2)

    def test_default_run_generates_the_real_report_and_the_result_file(self):
        """既定の実行は、本物のレポート (Review_Ochi_*.html) と review_last_result.json を作る (従来どおり)。"""
        self.e2e()
        self.assertEqual(len(self.browser_calls), 1)
        self.assertTrue(os.path.basename(self.browser_calls[0]).startswith("Review_Ochi_"))
        self.assertTrue(os.path.isfile(self.browser_calls[0]))
        self.assertTrue(os.path.isfile(oto().REVIEW_LAST_RESULT_FILE))

    def test_all_months_with_staff_estimate_equals_the_real_ai_calls_and_asks_first(self):
        """「全て」(12か月) × Ochi + スタッフ2人: 見積りは36件 (約119円) で確認が出る。「はい」で実際の AI 呼び出しも36回。"""
        gui = self.e2e(months=a3m.ALL_1004, persons=["Ochi", "Saji", "Yuto Oi"], ask=True)
        self.assertEqual(self.results["estimate"][0]["n_calls"], 36)
        self.assertEqual(len(self.summarizer.ai_calls), 36)
        self.assertEqual(len(self.dialog_entries("askyesno")), 1)
        self.assertTrue(self.results["estimate"][0]["needs_confirm"])
        self.assertEqual(read_log_records()[0]["n_calls"], 36)
        self.assertEqual(len(os.listdir(oto().REVIEW_CACHE_DIR)), 36)
        self.assertEqual(len(self.browser_calls), 3)
        self.assertEqual(self.dialog_entries("showerror"), [])

    def test_all_months_with_staff_cancel_creates_nothing(self):
        """同じ条件で「いいえ」: AI は1回も呼ばれず、月別キャッシュのフォルダ・結果・レポート・実績ログが何も作られない。"""
        self.e2e(months=a3m.ALL_1004, persons=["Ochi", "Saji", "Yuto Oi"], ask=False)
        self.assertEqual(self.summarizer.ai_calls, [])
        self.assertFalse(os.path.exists(oto().REVIEW_CACHE_DIR), "中止なのに analysis_cache/review_monthly/ が作られた")
        self.assertFalse(os.path.exists(oto().REVIEW_LAST_RESULT_FILE))
        self.assertFalse(os.path.exists(LOG_PATH))
        self.assertEqual(self.browser_calls, [])
        self.assertFalse([f for f in os.listdir(".") if f == "out" and os.listdir("out")], "中止なのにレポートが作られた")
        self.assertNotIn("generate", self.events)
        self.assertEqual(self.final_state["status"], CANCELLED_STATUS)

    def test_cache_only_run_has_zero_calls_and_no_log(self):
        """キャッシュのみ (月のチェックなし) の実行: 見積り0件・AIなし・確認なし・実績ログなし・「（新しい分析は不要でした）」。"""
        self.e2e(months=(), seed_months=a3m.ALL_1004)
        self.assertEqual(self.results["estimate"][0]["n_calls"], 0)
        self.assertEqual(self.summarizer.ai_calls, [])
        self.assertEqual(self.dialogs, [])
        self.assertFalse(os.path.exists(LOG_PATH))
        self.assertEqual(self.final_state["status"], DONE_TEXT + NO_NEW_TEXT)
        self.assertEqual(len(self.browser_calls), 1)

    def test_when_every_call_failed_nothing_is_recorded_and_the_status_warns(self):
        """(追記) AIが全件失敗 (1件中1件): 呼び出しは行われた (見積りの件数 = 実際の呼び出し回数) が、実績ログには記録せず、
        完了表示は「⚠ 振り返り生成は完了（AI分析に失敗した月×対象者が1件。…）」。"""
        self.e2e(fail={("202609", "ochi")})
        self.assertEqual(self.results["estimate"][0]["n_calls"], len(self.summarizer.ai_calls))
        self.assertEqual(self.results["count_failed"], [1])
        self.assertFalse(os.path.exists(LOG_PATH), "全件失敗なのに実績ログを書いた")
        self.assertTrue(self.final_state["status"].startswith(warn_text(1)), self.final_state["status"])
        self.assertIn("AI失敗1か月", self.final_state["status"])

    def test_a_partial_failure_records_only_the_successful_calls(self):
        """(追記) 3か月のうち1か月が失敗: 実績ログには成功した2件を記録 (トークンは実際に使った全呼び出しの合計)。"""
        self.e2e(months=("202607", "202608", "202609"), fail={("202608", "ochi")})
        self.assertEqual(self.results["estimate"][0]["n_calls"], 3)
        self.assertEqual(len(self.summarizer.ai_calls), 3)
        self.assertEqual(self.results["count_failed"], [1])
        recs = read_log_records()
        self.assertEqual(len(recs), 1)
        self.assertEqual((recs[0]["n_calls"], recs[0]["output_tokens"]), (2, 3000))
        self.assertEqual(recs[0]["input_tokens"], sum(self.summarizer.prompt_lengths))
        self.assertTrue(self.final_state["status"].startswith(warn_text(1)), self.final_state["status"])


class TestSpecGapReviewEndToEnd(EndToEndCase):
    """仕様が曖昧/未記載の点 (見積りの入力文字数と、実際にAIへ渡るプロンプトの長さの関係)。"""

    def test_the_estimate_is_a_generous_estimate_of_the_real_prompt_length(self):
        """見積りの入力文字数は、実際にAIへ渡ったプロンプトの長さ以上 (多めの見積り) で、2倍以内。"""
        # 仕様は定型プロンプトを「約2,100字」とし、見積りは「多めに」と書く (実プロンプトの長さそのものは仕様の対象外)。
        # 小さなスレッド1つの既定の実行で、見積り >= 実際 かつ 見積り <= 実際の2倍 (実測: 見積り2342字・実プロンプト2147字)。
        # 定型プロンプトが長くなって見積りを超えたら、REVIEW_ESTIMATE_PROMPT_CHARS を見直す合図になる
        self.e2e()
        estimated = self.results["estimate"][0]["input_chars"]
        actual = self.summarizer.prompt_lengths[0]
        self.assertGreaterEqual(estimated, actual, "見積りが実際のプロンプトより少ない (見積りが少なすぎる)")
        self.assertLessEqual(estimated, actual * 2, "見積りが実際の2倍を超える (多すぎる)")


# ============================================================
# 4. 範囲ガード (_04 → _05 で変えてよい既存メソッドは _run_review だけ)
# ============================================================
OLD_REV = "outlook_total_organizer_20261004_04.py"
NEW_REV = "outlook_total_organizer_20261004_05.py"
RUN_REVIEW = "MailManagerGUI._run_review"
ALLOWED_TO_CHANGE = {RUN_REVIEW}
NEW_CONSTANTS = tuple(SPEC_CONSTANTS)
NEW_FUNCTIONS = ("estimate_review_cost", "count_failed_review_calls")
MUST_STAY_UNCHANGED = (
    "MailManagerGUI._reformat_review", "MailManagerGUI._save_review_result", "MailManagerGUI._confirm_ai_cost",
    "MailManagerGUI._get_review_all_months", "MailManagerGUI._get_review_selected_months",
    "MailManagerGUI._get_review_selected_persons", "MailManagerGUI._ui_review_tab", "MailManagerGUI._run_action_dashboard",
    "MailManagerGUI._set_status", "MailSummarizer.generate_review_data", "MailSummarizer.summarize_review_month",
    "MailSummarizer.load_review_month_cache", "review_cache_gaps", "format_review_period_label", "review_thread_is_minutes",
    "estimate_action_analysis_cost", "estimate_ai_cost_yen", "calc_api_cost_yen", "record_ai_usage",
    "observed_output_tokens_per_call", "review_activity_qualifies", "review_person_activity_qualifies",
)


def _is_docstring(node):
    return (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str))


@functools.lru_cache(maxsize=None)
def _parse(path):
    with open(path, "r", encoding="utf-8") as f:
        return ast.parse(f.read())


def func_node(path, qualified):
    """"name" (モジュール直下) または "Class.method" の FunctionDef。"""
    cls_name, _, meth = qualified.rpartition(".")
    for node in _parse(path).body:
        if not cls_name and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == meth:
            return node
        if cls_name and isinstance(node, ast.ClassDef) and node.name == cls_name:
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub.name == meth:
                    return sub
    raise AssertionError(f"{qualified} が {os.path.basename(path)} に無い")


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


def _top_level_names(path):
    """モジュール直下の (名前 -> body 内の位置)。関数・クラス・単純な代入が対象。"""
    out = {}
    for i, node in enumerate(_parse(path).body):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out[node.name] = i
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name):
                    out[t.id] = i
    return out


def _call_names_in_source_order(fn):
    """fn (入れ子の関数を含む) の中の呼び出しの名前 (属性なら最後の名前) を、ソースの位置順に返す。"""
    calls = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            f = n.func
            name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else None)
            if name:
                calls.append((n.lineno, n.col_offset, name))
    return [name for _, _, name in sorted(calls)]


class TestScopeGuardA7a(unittest.TestCase):
    """範囲ガード: _04 → _05 で変えてよい既存のメソッドは MailManagerGUI._run_review だけ。追加は仕様の定数 (12個) と
    estimate_review_cost・count_failed_review_calls だけ。削除なし。"""

    @classmethod
    def setUpClass(cls):
        cls.target = _loader.rev_path(NEW_REV)
        cls.baseline = _loader.rev_path(OLD_REV)
        if not (os.path.isfile(cls.target) and os.path.isfile(cls.baseline)):
            raise unittest.SkipTest(f"A7a のリビジョン対({OLD_REV} / {NEW_REV})が無い")
        cls.old = _index_source(cls.baseline)
        cls.new = _index_source(cls.target)

    def test_no_existing_function_or_method_is_removed(self):
        """既存の関数・メソッドが消えていない。"""
        removed = sorted(n for n in self.old[0] if n not in self.new[0])
        self.assertEqual(removed, [], f"既存の関数/メソッドが消えている: {removed}")

    def test_only_run_review_changed_among_the_existing_functions(self):
        """既存の関数・メソッドのうち、変更されているのは MailManagerGUI._run_review だけ。"""
        old_f, new_f = self.old[0], self.new[0]
        changed = sorted(n for n, s in old_f.items() if n in new_f and new_f[n] != s and n not in ALLOWED_TO_CHANGE)
        self.assertEqual(changed, [], f"仕様で許可されていない既存関数/メソッドの変更: {changed}")

    def test_run_review_was_actually_changed(self):
        """許可された _run_review が実際に変更されている (A7a の実装が入っている)。"""
        self.assertNotEqual(self.old[0][RUN_REVIEW], self.new[0][RUN_REVIEW])

    def test_run_review_signature_is_unchanged(self):
        """_run_review の引数 (self だけ) は変わらない。"""
        old_fn, new_fn = func_node(self.baseline, RUN_REVIEW), func_node(self.target, RUN_REVIEW)
        self.assertEqual(ast.dump(old_fn.args), ast.dump(new_fn.args))
        self.assertEqual([x.arg for x in new_fn.args.args], ["self"])

    def test_the_functions_the_spec_says_are_unchanged_are_identical(self):
        """仕様が「変えない」とするもの (_reformat_review・generate_review_data・_confirm_ai_cost・A1.1 の関数など) が無変更。"""
        for q in MUST_STAY_UNCHANGED:
            with self.subTest(function=q):
                self.assertIn(q, self.old[0], f"{q} が旧版に見つからない (比較の前提が崩れた)")
                self.assertEqual(self.new[0].get(q), self.old[0][q], f"{q} が変更されている")

    def test_existing_constants_are_unchanged(self):
        """既存の定数 (COST_CONFIRM_THRESHOLD_YEN など) が消えても変わってもいない。"""
        old_c, new_c = self.old[1], self.new[1]
        removed = sorted(n for n in old_c if n not in new_c)
        changed = sorted(n for n, s in old_c.items() if n in new_c and new_c[n] != s)
        self.assertEqual(removed, [], f"既存の定数が消えている: {removed}")
        self.assertEqual(changed, [], f"既存の定数が変更されている: {changed}")

    def test_existing_imports_are_kept(self):
        """既存の import が消えていない。"""
        missing = self.old[2] - self.new[2]
        self.assertEqual(len(missing), 0, f"既存の import が {len(missing)} 件消えている")

    def test_other_top_level_statements_and_class_skeletons_are_unchanged(self):
        """関数・定数・import 以外のトップレベル文と、クラスの骨格が変わっていない。"""
        self.assertEqual(self.old[3], self.new[3], "関数/定数/import 以外のトップレベル文が変わっている")
        for cls_name, shell in self.old[4].items():
            with self.subTest(cls=cls_name):
                self.assertIn(cls_name, self.new[4])
                self.assertEqual(shell, self.new[4].get(cls_name),
                                 f"クラス {cls_name} の骨格(継承・デコレータ・クラス直下の文)が変わっている")

    def test_new_names_are_added(self):
        """仕様の新しい定数 (12個) と estimate_review_cost・count_failed_review_calls が追加されている (旧版には無い)。"""
        for n in NEW_FUNCTIONS:
            with self.subTest(function=n):
                self.assertIn(n, self.new[0])
                self.assertNotIn(n, self.old[0])
        for n in NEW_CONSTANTS:
            with self.subTest(constant=n):
                self.assertIn(n, self.new[1])
                self.assertNotIn(n, self.old[1])

    def test_nothing_else_was_added_beyond_the_names_in_the_spec(self):
        """仕様に無い関数・メソッド・定数 (先頭が _ のものも) が追加されていない。"""
        added_f = sorted(set(self.new[0]) - set(self.old[0]))
        added_c = sorted(set(self.new[1]) - set(self.old[1]))
        self.assertEqual(added_f, sorted(NEW_FUNCTIONS), f"仕様に無い関数/メソッドが追加されている: {added_f}")
        self.assertEqual(added_c, sorted(NEW_CONSTANTS), f"仕様に無い定数が追加されている: {added_c}")

    def test_no_class_is_added_or_removed(self):
        """トップレベルのクラスの追加・削除は無い。"""
        self.assertEqual(sorted(self.new[4]), sorted(self.old[4]))

    def test_new_module_level_definitions_sit_after_estimate_action_analysis_cost_as_one_block(self):
        """追加した定数・関数が、仕様どおり estimate_action_analysis_cost の後 (次の既存の定義 load_project_knowledge の前) に、
        ひとまとまりで置かれている (間に別の定義が挟まらない)。"""
        names = _top_level_names(self.target)
        positions = sorted(names[n] for n in NEW_CONSTANTS + NEW_FUNCTIONS)
        self.assertGreater(min(positions), names["estimate_action_analysis_cost"])
        self.assertLess(max(positions), names["load_project_knowledge"])
        self.assertEqual(positions, list(range(positions[0], positions[0] + len(positions))),
                         "追加した定数・関数の間に、別の定義が挟まっている")

    def test_count_failed_review_calls_sits_right_after_estimate_review_cost(self):
        """(追記) count_failed_review_calls は、estimate_review_cost の直後にある。"""
        names = _top_level_names(self.target)
        self.assertEqual(names["count_failed_review_calls"], names["estimate_review_cost"] + 1)

    def test_run_review_keeps_its_calls_in_the_specified_order(self):
        """_run_review の呼び出し順 (ソース上): 取得 (メール → スレッド化 → 会議) → 見積り → 確認 → generate → 失敗数 → 実績ログ → 保存 → レポート生成。"""
        calls = _call_names_in_source_order(func_node(self.target, RUN_REVIEW))

        def first(name):
            self.assertIn(name, calls, f"_run_review の中に {name} の呼び出しが無い")
            return calls.index(name)
        order = ["get_review_mails_for_month", "group_by_thread", "get_review_calendar_events", "estimate_review_cost",
                 "_confirm_ai_cost", "generate_review_data", "count_failed_review_calls", "record_ai_usage"]
        positions = [first(n) for n in order]
        self.assertEqual(positions, sorted(positions), f"呼び出し順が仕様と違う: {[calls[p] for p in positions]}")
        self.assertLess(first("generate_review_data"), first("_save_review_result"))
        self.assertLess(first("_save_review_result"), first("generate_review_report"))

    def test_run_review_still_calls_the_things_the_spec_keeps(self):
        """_run_review は、従来の処理 (対象者ごとのレポート・結果の保存・A2のトークンリセット用の代入・A3の注記) を残している。"""
        fn = func_node(self.target, RUN_REVIEW)
        calls = set(_call_names_in_source_order(fn))
        for name in ("generate_review_report", "_save_review_result", "review_cache_gaps", "format_review_period_label",
                     "calc_api_cost_yen", "_set_status"):
            with self.subTest(call=name):
                self.assertIn(name, calls)
        src = ast.unparse(fn)
        self.assertIn("total_input_tokens = 0", src)
        self.assertIn("total_output_tokens = 0", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
