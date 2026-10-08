# -*- coding: utf-8 -*-
"""A1.1「🔄 解析のみ更新」ボタン・AI費用の事前確認・実績ログ・エラー表示の修正 テスト (仕様書 A11_SPEC.md)。

仕様書だけを根拠に、実装 (_20261004_04.py の record_ai_usage / observed_output_tokens_per_call /
estimate_action_analysis_cost / _confirm_ai_cost / _run_action_dashboard) を見ずに書いている。
  - 仕様に明記された挙動            -> 通常の TestCase
  - 仕様が曖昧/未記載で「最も自然な解釈」で書いたもの
                                    -> クラス名に SpecGap を含む (コメントに解釈を明記)
    SpecGap の失敗は「バグ」ではなく「仕様の確認が必要」の合図として扱う。

構成
  1. 定数・シグネチャ
  2. record_ai_usage (実績ログの追記。例外を外へ出さない)
  3. observed_output_tokens_per_call (実績ログからの校正値)
  4. estimate_action_analysis_cost (解析対象の判定 / 入力文字数 / 校正 / 返り値 / 境界)
  5. 案内文 (build_action_decision_snapshot) の文言
  6. 画面: 「🔄 解析のみ更新」ボタンの配置・文言・command (_ui_action_tab)
  7. _confirm_ai_cost (費用確認ダイアログ)
  8. _run_action_dashboard (成功 / 中止 / 失敗 / 費用確認 / 実績ログ / A2のトークンリセット / 呼び出し順)
  9. 範囲ガード (_20261004_03.py と _20261004_04.py の AST 比較。変更してよいのは許可リストだけ)

GUI テストは tkinter とディスプレイが無ければ自動 skip (Linux は xvfb-run -a /usr/bin/python3.12 tests/run_tests.py)。
ハーネスは A1 の GuiCase / スタブ (test_a1_gui_smoke) を拡張して使う。Outlook(COM)・AI・ネットワークには一切触れず、
ブラウザ (webbrowser.open) も差し替えて実際には開かない。

費用の期待値は、既定モデル (gemini-2.5-flash: 入力0.30/出力2.50 USD/100万トークン, 1USD=160円。A2 で確定済み) から、
このファイル内の独立した計算 (yen_flash) で出す。日付・時刻に依存する期待値は作らない
(現在時刻との比較は「前後の幅」で行い、固定日付の NOW だけを使う)。
実績ログ (json/ai_usage_log.jsonl) や設定は、必ず空の一時cwd の中で動かす (利用者の実データを拾わない)。
"""
import ast
import contextlib
import copy
import difflib
import functools
import gc
import inspect
import io
import json
import os
import random
import re
import signal
import threading
import time
import types
import unittest
import webbrowser                                  # noqa: F401  (mock.patch("webbrowser.open") の対象を先に読み込む)
from datetime import datetime, timedelta
from unittest import mock

import _loader
import test_a1_gui_smoke as a1gui                  # GUI ハーネス (GuiCase / スタブ) を再利用する
import test_a1_snapshot as a1snap                  # 案内文の確認で snapshot の環境作成を再利用する
from _loader import (
    CACHE_PATH, LAST_RUN_PATH, make_last_run, make_thread, read_bytes, read_json, snapshot_files,
    tempdir_cwd, write_bytes, write_json, write_text,
)

tk, ttk, tkmessagebox = a1gui.tk, a1gui.ttk, a1gui.tkmessagebox


def oto():
    return _loader.load()


# ============================================================
# 共通の定数・ヘルパ
# ============================================================
FLASH = "gemini-2.5-flash"
PRO = "gemini-2.5-pro"
LOG_PATH = os.path.join("json", "ai_usage_log.jsonl")
LAST_RESULT_PATH = os.path.join("json", "action_dashboard_last_result.json")
LOG_KEYS = ["at", "feature", "n_calls", "input_tokens", "output_tokens", "yen", "model"]
LOG_FAIL_MSG = "ai_usage_log.jsonl 追記失敗（本処理は継続）"          # 仕様: ⚠️ <これ>: <例外> を print する
AT_RE = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$"

RUN_TEXT = "📋 アクション一覧を生成"
UPDATE_TEXT = "🔄 解析のみ更新"
RUN_BUSY_TEXT = "⏳ 取得・解析中..."
UPDATE_BUSY_TEXT = "⏳ 更新中..."
REFORMAT_TEXT = "🎨 フォーマットのみ再生成"
CANCELLED_STATUS = "⏹ 費用の確認で中止しました（AI解析は行っていません）"
CONFIRM_TITLE = "AI費用の確認"
ESTIMATE_PRINT_HEAD = "💰 アクション解析のAI費用の見込み"
ACTION_LABEL = "アクション解析"
WARN_UPDATE = "⚠ 解析のみ更新は完了（解析に失敗したスレッドが{n}件。もう一度実行すると再試行します）"
WARN_RUN = "⚠ アクションダッシュボード生成は完了（解析に失敗したスレッドが{n}件。もう一度実行すると再試行します）"
UNKNOWN_UPDATE = "⚠ 解析のみ更新は完了（解析後の結果を読めず、成否を確認できませんでした。もう一度実行すると確かめられます）"
UNKNOWN_RUN = "⚠ アクションダッシュボード生成は完了（解析後の結果を読めず、成否を確認できませんでした。もう一度実行すると確かめられます）"
WAITING_STATUS = "⏸ AI費用の確認待ち（約{yen:.0f}円）…"          # 仕様(M2): 確認ダイアログを待つ間のステータス


def yen_flash(input_tokens, output_tokens):
    """既定モデル (gemini-2.5-flash, 入力0.30/出力2.50 USD/100万トークン, 1USD=160円) の費用。
    A2 の仕様 (calc_api_cost_yen) から、このファイル内で独立に計算する (小数2桁)。"""
    return round((input_tokens / 1_000_000 * 0.30 + output_tokens / 1_000_000 * 2.50) * 160, 2)


def yen_pro(input_tokens, output_tokens):
    """gemini-2.5-pro (入力1.25/出力10.00 USD/100万トークン) の費用。"""
    return round((input_tokens / 1_000_000 * 1.25 + output_tokens / 1_000_000 * 10.00) * 160, 2)


class InTempCwd(unittest.TestCase):
    """各テストを空の一時cwd で動かす (実際の config / 実績ログを拾わない・json/ を汚さない)。"""

    def setUp(self):
        cm = tempdir_cwd()
        self.tmp = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)


def call_capturing(fn, *args, **kwargs):
    """fn を呼び、(戻り値, print された文字列, 外へ出た例外) を返す。"""
    buf = io.StringIO()
    result, error = None, None
    with contextlib.redirect_stdout(buf):
        try:
            result = fn(*args, **kwargs)
        except Exception as e:                                  # noqa: BLE001
            error = e
    return result, buf.getvalue(), error


# ---- 実績ログ (json/ai_usage_log.jsonl) の読み書き -------------------------------------
def rec(feature="action", n_calls=1, output_tokens=1000, input_tokens=50000, yen=1.0, model=FLASH,
        at="2026-10-04T09:00:00", **extra):
    """実績ログの1件分 (仕様のキー構成)。"""
    d = {"at": at, "feature": feature, "n_calls": n_calls, "input_tokens": input_tokens,
         "output_tokens": output_tokens, "yen": yen, "model": model}
    d.update(extra)
    return d


def write_log(*lines, final_newline=True, newline="\n"):
    """実績ログを書く。lines は dict (JSON にする) か str (そのまま1行)。"""
    parts = [ln if isinstance(ln, str) else json.dumps(ln, ensure_ascii=False) for ln in lines]
    text = newline.join(parts) + (newline if parts and final_newline else "")
    write_text(LOG_PATH, text)


def read_log_text():
    return read_bytes(LOG_PATH).decode("utf-8")


def read_log_text_or_empty():
    return read_log_text() if os.path.exists(LOG_PATH) else ""


def read_log_records():
    return [json.loads(line) for line in read_log_text().split("\n") if line.strip()]


# ---- 解析対象スレッド / キャッシュの合成 ---------------------------------------------------
def mail(body="", **kw):
    d = {"body": body, "sender_name": "太郎"}
    d.update(kw)
    return d


def thr(*bodies, **kw):
    """group_by_thread の1スレッド分: {"mails": [{"body": ...}, ...], ...}。"""
    d = {"topic": "件名", "mails": [mail(b) for b in bodies]}
    d.update(kw)
    return d


def empty_threads(n):
    """メール0通のスレッド n 個 (どれも入力 1800 文字・1回と見積もられる)。"""
    return {f"CONV{i:03d}": {"topic": f"件名{i}", "mails": []} for i in range(n)}


def body_threads(n, body="本文です"):
    """メール1通 (本文 body) のスレッド n 個。"""
    return {f"CONV{i:03d}": thr(body, topic=f"件名{i}") for i in range(n)}


_UNSET = object()


def cache_entry(mail_count, error=False, data=_UNSET):
    """action_dashboard.json の threads[cid] 1件分。data=None / dict でない値も指定できる。"""
    if data is _UNSET:
        data = {"thread_id": "x", "topic": "t", "summary": "s", "category": "その他", "actions": []}
        if error:
            data["_error"] = True
    return {"mail_count": mail_count, "latest_entry_id": "E", "data": data}


def cache_of(**entries):
    return {"threads": dict(entries)}


def estimate(threads, cache_data=None, model=None):
    return oto().estimate_action_analysis_cost(threads, cache_data, model)


def thread_chars_reference(bodies):
    """仕様: 入力文字数 = min(Σ(min(len(str(body or "")), 800)+40), 30000) + 1800 (メールが dict のものだけ)。"""
    total = sum(min(len(str(b or "")), 800) + 40 for b in bodies)
    return min(total, 30000) + 1800


# ============================================================
# 1. 定数・シグネチャ
# ============================================================
class TestConstantsAndSignatures(unittest.TestCase):
    """新しい定数の値と、新しい関数・メソッドの引数 (シグネチャ) が仕様どおりであること。"""

    def test_new_constants_have_the_specified_values(self):
        """仕様の新しい定数 (ACTION_ESTIMATE_* と AI_USAGE_LOG_FILE) が仕様どおりの値であること。"""
        expected = {
            "ACTION_ESTIMATE_PROMPT_CHARS": 1800, "ACTION_ESTIMATE_OUTPUT_TOKENS": 2500,
            "ACTION_ESTIMATE_BODY_LIMIT": 800, "ACTION_ESTIMATE_THREAD_CHARS_MAX": 30000,
            "ACTION_ESTIMATE_SAFETY": 1.5, "ACTION_ESTIMATE_OUTPUT_FLOOR_RATIO": 0.5,
            "AI_USAGE_LOG_FILE": "json/ai_usage_log.jsonl",
        }
        for name, value in expected.items():
            with self.subTest(name=name):
                self.assertEqual(getattr(oto(), name), value)

    def test_record_ai_usage_signature(self):
        """record_ai_usage の引数名・順序・既定値 (yen と model は None) が仕様どおりであること。"""
        sig = inspect.signature(oto().record_ai_usage)
        self.assertEqual(list(sig.parameters), ["feature", "n_calls", "input_tokens", "output_tokens", "yen", "model"])
        self.assertIsNone(sig.parameters["yen"].default)
        self.assertIsNone(sig.parameters["model"].default)

    def test_observed_output_tokens_per_call_signature(self):
        """observed_output_tokens_per_call(feature, last_n=5) の引数が仕様どおりであること。"""
        sig = inspect.signature(oto().observed_output_tokens_per_call)
        self.assertEqual(list(sig.parameters), ["feature", "last_n"])
        self.assertEqual(sig.parameters["last_n"].default, 5)

    def test_estimate_action_analysis_cost_signature(self):
        """estimate_action_analysis_cost(threads, cache_data, model=None) の引数が仕様どおりであること。"""
        sig = inspect.signature(oto().estimate_action_analysis_cost)
        self.assertEqual(list(sig.parameters), ["threads", "cache_data", "model"])
        self.assertIsNone(sig.parameters["model"].default)

    def test_count_failed_action_threads_signature(self):
        """count_failed_action_threads(threads, cache_data) の引数が仕様どおりであること。"""
        sig = inspect.signature(oto().count_failed_action_threads)
        self.assertEqual(list(sig.parameters), ["threads", "cache_data"])

    def test_run_action_dashboard_takes_open_browser_defaulting_to_true(self):
        """_run_action_dashboard が open_browser 引数を持ち、既定は True (従来どおりHTMLを開く) であること。"""
        sig = inspect.signature(oto().MailManagerGUI._run_action_dashboard)
        self.assertEqual(list(sig.parameters), ["self", "open_browser"])
        self.assertIs(sig.parameters["open_browser"].default, True)

    def test_confirm_ai_cost_is_a_method_taking_estimate_and_label(self):
        """_confirm_ai_cost(self, estimate, label) がGUIのメソッドとして存在すること。"""
        sig = inspect.signature(oto().MailManagerGUI._confirm_ai_cost)
        self.assertEqual(list(sig.parameters), ["self", "estimate", "label"])


# ============================================================
# 2. record_ai_usage
# ============================================================
class TestRecordAiUsage(InTempCwd):
    """record_ai_usage: 1行のJSONを実績ログに追記する (キー・型・None・UTF-8・追記)。"""

    def rec(self, *args, **kwargs):
        return oto().record_ai_usage(*args, **kwargs)

    def test_returns_none(self):
        """戻り値は None であること。"""
        self.assertIsNone(self.rec("action", 3, 1000, 200))

    def test_creates_the_json_dir_and_the_log_file(self):
        """json/ が無ければ作り、実績ログ json/ai_usage_log.jsonl を作ること。"""
        self.assertFalse(os.path.exists("json"))
        self.rec("action", 3, 1000, 200)
        self.assertTrue(os.path.isfile(LOG_PATH))

    def test_existing_json_dir_is_reused_and_other_files_are_untouched(self):
        """json/ が既にあれば再利用し、同じフォルダの他のファイルには触れないこと。"""
        write_text(os.path.join("json", "other.json"), '{"keep": 1}')
        self.rec("action", 3, 1000, 200)
        self.assertEqual(sorted(os.listdir("json")), ["ai_usage_log.jsonl", "other.json"])
        self.assertEqual(read_bytes(os.path.join("json", "other.json")), b'{"keep": 1}')

    def test_one_call_writes_exactly_one_line_ending_with_one_newline(self):
        """1回の呼び出しで、末尾が改行1つの「1行のJSON」を追記すること。"""
        self.rec("action", 3, 1000, 200)
        text = read_log_text()
        self.assertTrue(text.endswith("\n"), "末尾が改行でない")
        self.assertFalse(text.endswith("\n\n"), "末尾の改行が2つ以上ある")
        self.assertEqual(text.count("\n"), 1, "1行になっていない")
        self.assertIsInstance(json.loads(text), dict)

    def test_line_has_exactly_the_seven_documented_keys(self):
        """1行のキーが仕様の7つ (at / feature / n_calls / input_tokens / output_tokens / yen / model) だけであること。"""
        self.rec("action", 3, 1000, 200, 1.5, "gemini-2.5-flash")
        self.assertEqual(sorted(read_log_records()[0]), sorted(LOG_KEYS))

    def test_given_values_are_recorded(self):
        """渡した値 (feature・回数・トークン・円・モデル) がそのまま記録されること。"""
        self.rec("action", 3, 12345, 678, 4.56, PRO)
        d = read_log_records()[0]
        self.assertEqual((d["feature"], d["n_calls"], d["input_tokens"], d["output_tokens"], d["yen"], d["model"]),
                         ("action", 3, 12345, 678, 4.56, PRO))

    def test_keyword_arguments_are_accepted(self):
        """仕様の引数名でキーワード指定しても記録できること。"""
        self.rec(feature="review", n_calls=2, input_tokens=10, output_tokens=20, yen=0.5, model=FLASH)
        d = read_log_records()[0]
        self.assertEqual((d["feature"], d["n_calls"], d["input_tokens"], d["output_tokens"], d["yen"], d["model"]),
                         ("review", 2, 10, 20, 0.5, FLASH))

    def test_value_types(self):
        """型が仕様どおり (featureとmodelはstr、回数とトークンはint、yenはfloat) であること。"""
        self.rec("action", 3, 12345, 678, 4.56, PRO)
        d = read_log_records()[0]
        self.assertIsInstance(d["feature"], str)
        for k in ("n_calls", "input_tokens", "output_tokens"):
            with self.subTest(key=k):
                self.assertIsInstance(d[k], int)
                self.assertNotIsInstance(d[k], bool)
        self.assertIsInstance(d["yen"], float)
        self.assertIsInstance(d["model"], str)
        self.assertIsInstance(d["at"], str)

    def test_yen_defaults_to_null(self):
        """yen を省略したら null (None) で記録すること。"""
        self.rec("action", 3, 1000, 200)
        self.assertIsNone(read_log_records()[0]["yen"])

    def test_yen_none_is_recorded_as_null(self):
        """yen=None は null で記録すること。"""
        self.rec("action", 3, 1000, 200, None)
        self.assertIsNone(read_log_records()[0]["yen"])

    def test_model_none_becomes_empty_string(self):
        """model=None は空文字で記録すること。"""
        self.rec("action", 3, 1000, 200, 1.0, None)
        self.assertEqual(read_log_records()[0]["model"], "")

    def test_model_defaults_to_empty_string(self):
        """model を省略したら空文字で記録すること。"""
        self.rec("action", 3, 1000, 200)
        self.assertEqual(read_log_records()[0]["model"], "")

    def test_none_call_count_and_tokens_become_zero(self):
        """回数・トークンが None なら 0 で記録すること。"""
        self.rec("action", None, None, None)
        d = read_log_records()[0]
        self.assertEqual((d["n_calls"], d["input_tokens"], d["output_tokens"]), (0, 0, 0))

    def test_each_none_is_replaced_independently(self):
        """None の項目だけが 0 になり、他の項目の値は保たれること。"""
        self.rec("action", 2, None, 30)
        self.rec("action", None, 40, None)
        a, b = read_log_records()
        self.assertEqual((a["n_calls"], a["input_tokens"], a["output_tokens"]), (2, 0, 30))
        self.assertEqual((b["n_calls"], b["input_tokens"], b["output_tokens"]), (0, 40, 0))

    def test_at_has_the_iso_format_without_fraction_or_timezone(self):
        """at が YYYY-MM-DDTHH:MM:SS (小数秒・タイムゾーンなし) で、実在する日時として読めること。"""
        self.rec("action", 1, 1, 1)
        at = read_log_records()[0]["at"]
        self.assertRegex(at, AT_RE)
        datetime.strptime(at, "%Y-%m-%dT%H:%M:%S")                # 実在する日時として読める

    def test_at_is_the_current_time(self):
        """at が呼び出した時刻 (前後1秒の幅) であること。"""
        # 現在時刻との比較は「前後の幅」で行う (日付に依存しない)。タイムゾーンは SpecGap 側で確認
        before = datetime.now().replace(microsecond=0)
        self.rec("action", 1, 1, 1)
        after = datetime.now()
        at = datetime.strptime(read_log_records()[0]["at"], "%Y-%m-%dT%H:%M:%S")
        self.assertLessEqual(before - timedelta(seconds=1), at)
        self.assertLessEqual(at, after + timedelta(seconds=1))

    def test_calls_are_appended_in_order_without_overwriting(self):
        """複数回呼ぶと行が増え (上書きしない)、呼んだ順に並ぶこと。"""
        for i in (1, 2, 3):
            self.rec("action", i, i * 100, i * 10)
        self.assertEqual(read_log_text().count("\n"), 3)
        self.assertEqual([r["n_calls"] for r in read_log_records()], [1, 2, 3])

    def test_existing_log_content_is_kept_as_a_prefix(self):
        """既存の実績ログの内容を書き換えず、その後ろに追記すること。"""
        write_log(rec(n_calls=7, output_tokens=777), rec("review", 8, 888))
        before = read_bytes(LOG_PATH)
        self.rec("action", 1, 1, 1)
        after = read_bytes(LOG_PATH)
        self.assertTrue(after.startswith(before), "既存の実績が書き換わった")
        self.assertEqual(after[len(before):].count(b"\n"), 1)
        self.assertEqual([r["n_calls"] for r in read_log_records()], [7, 8, 1])

    def test_japanese_is_written_as_utf8_without_unicode_escapes(self):
        """日本語はUTF-8のまま (\\uXXXX に化けず) 書かれ、読み戻せること。"""
        self.rec("アクション解析", 1, 1, 1, None, "モデル名")
        raw = read_bytes(LOG_PATH)
        self.assertIn("アクション解析".encode("utf-8"), raw)
        self.assertIn("モデル名".encode("utf-8"), raw)
        self.assertNotIn(b"\\u", raw, "ensure_ascii=False の想定が、日本語が \\uXXXX に化けている")
        d = json.loads(raw.decode("utf-8"))
        self.assertEqual((d["feature"], d["model"]), ("アクション解析", "モデル名"))

    def test_newlines_inside_values_do_not_break_the_one_line_rule(self):
        """値に改行が含まれていても1行のままで、読み戻すと元の値になること。"""
        self.rec("a\nb\r\nc", 1, 1, 1, None, "m\nx")
        text = read_log_text()
        self.assertEqual(text.count("\n"), 1)
        d = json.loads(text)
        self.assertEqual((d["feature"], d["model"]), ("a\nb\r\nc", "m\nx"))

    def test_success_prints_no_failure_message(self):
        """成功したときは「追記失敗」の警告を print しないこと。"""
        _, printed, exc = call_capturing(oto().record_ai_usage, "action", 3, 1000, 200)
        self.assertIsNone(exc)
        self.assertNotIn("追記失敗", printed)


class _Unconvertible:
    """int() / float() に変換しようとすると、理由付きの ValueError を出す値。"""

    def __int__(self):
        raise ValueError("理由XYZ")

    def __float__(self):
        raise ValueError("理由XYZ")

    def __index__(self):
        raise ValueError("理由XYZ")


# 数値に変換できない値 (n_calls / input_tokens / output_tokens 用)。inf は int() が OverflowError を出す値
BAD_COUNTS = [("文字列", "abc"), ("object", object()), ("list", [1, 2]), ("dict", {"a": 1}),
              ("inf", float("inf")), ("nan", float("nan")), ("数字+文字", "1.5x"), ("変換で例外", _Unconvertible())]
BAD_YEN = [("文字列", "abc"), ("object", object()), ("list", [1, 2]), ("dict", {"a": 1}),
           ("数字+文字", "1.5x"), ("変換で例外", _Unconvertible())]


def bad_argument_sets():
    """record_ai_usage("action", 1, 100, 10, 0.5) の1か所だけを、数値にできない値に差し替えた引数一式。"""
    base = ["action", 1, 100, 10, 0.5]
    for pos, name, values in ((1, "n_calls", BAD_COUNTS), (2, "input_tokens", BAD_COUNTS),
                              (3, "output_tokens", BAD_COUNTS), (4, "yen", BAD_YEN)):
        for label, value in values:
            args = list(base)
            args[pos] = value
            yield f"{name}={label}", args


class TestRecordAiUsageNeverRaises(InTempCwd):
    """例外は絶対に外へ出さない。失敗は「⚠️ ai_usage_log.jsonl 追記失敗（本処理は継続）: …」を print して戻る。"""

    def test_unconvertible_values_do_not_raise(self):
        """数値に変換できない値 (文字列・オブジェクト・inf/nanなど) を渡しても、例外を外へ出さないこと。"""
        for label, args in bad_argument_sets():
            with self.subTest(case=label):
                _, _, exc = call_capturing(oto().record_ai_usage, *args)
                self.assertIsNone(exc, f"例外が外へ出た: {exc!r}")

    def test_unconvertible_values_print_the_failure_message(self):
        """数値に変換できない値のときは「追記失敗（本処理は継続）」の警告を print すること。"""
        for label, args in bad_argument_sets():
            with self.subTest(case=label):
                _, printed, _ = call_capturing(oto().record_ai_usage, *args)
                self.assertIn(LOG_FAIL_MSG, printed)

    def test_unconvertible_values_append_nothing(self):
        """数値に変換できない値のときは、行を書かないこと。"""
        for label, args in bad_argument_sets():
            with self.subTest(case=label):
                call_capturing(oto().record_ai_usage, *args)
                self.assertEqual(read_log_text_or_empty(), "", "変換できない値なのに行が書かれた")

    def test_a_failed_call_does_not_damage_the_log_for_later_calls(self):
        """失敗した呼び出しが既存の実績を壊さず、次の呼び出しは通常どおり追記できること。"""
        oto().record_ai_usage("action", 1, 100, 10, 0.5)
        good = read_bytes(LOG_PATH)
        call_capturing(oto().record_ai_usage, "action", "abc", 100, 10)
        self.assertEqual(read_bytes(LOG_PATH), good, "失敗した呼び出しが既存の実績を壊した")
        oto().record_ai_usage("action", 2, 200, 20, 1.0)
        self.assertEqual([r["n_calls"] for r in read_log_records()], [1, 2])

    def test_json_path_being_a_file_does_not_raise_and_prints_the_failure_message(self):
        """json がフォルダではなくファイルで作れないときも、例外を出さず警告を print すること。"""
        write_text("json", "これはファイル")
        _, printed, exc = call_capturing(oto().record_ai_usage, "action", 1, 100, 10)
        self.assertIsNone(exc, f"例外が外へ出た: {exc!r}")
        self.assertIn(LOG_FAIL_MSG, printed)

    def test_json_path_being_a_file_is_left_untouched(self):
        """json がファイルのときは、そのファイルを壊さないこと。"""
        write_text("json", "これはファイル")
        call_capturing(oto().record_ai_usage, "action", 1, 100, 10)
        self.assertTrue(os.path.isfile("json"))
        self.assertEqual(read_bytes("json"), "これはファイル".encode("utf-8"))

    def test_log_path_being_a_directory_does_not_raise_and_prints_the_failure_message(self):
        """ログのパスがフォルダで書き込めないときも、例外を出さず警告を print すること。"""
        os.makedirs(LOG_PATH)                                    # 書き込めない (root でも開けない) 状況の再現
        _, printed, exc = call_capturing(oto().record_ai_usage, "action", 1, 100, 10)
        self.assertIsNone(exc, f"例外が外へ出た: {exc!r}")
        self.assertIn(LOG_FAIL_MSG, printed)
        self.assertTrue(os.path.isdir(LOG_PATH))


class TestSpecGapRecordAiUsage(InTempCwd):
    """仕様が曖昧/未記載の点。自然な解釈で確認する (失敗は「仕様の確認が必要」の合図)。"""

    def test_failure_message_starts_with_the_warning_mark_and_ends_with_the_reason(self):
        """警告は「⚠️ ai_usage_log.jsonl 追記失敗（本処理は継続）: <理由>」の形で、理由 (例外の内容) が付くこと。"""
        # 仕様: "⚠️ ai_usage_log.jsonl 追記失敗（本処理は継続）: …" を print。… は例外の内容と解釈する
        reason_args = ["action", _Unconvertible(), 100, 10]
        _, printed, _ = call_capturing(oto().record_ai_usage, *reason_args)
        self.assertIn("⚠️ " + LOG_FAIL_MSG + ": ", printed)
        self.assertIn("理由XYZ", printed, "失敗の理由 (例外の内容) が表示されていない")

    def test_none_feature_does_not_raise(self):
        """feature=None (仕様外) でも例外を出さないこと。"""
        # feature は str と書かれている。None を渡したときの記録内容は未記載 → 例外にしないことだけ確認
        _, _, exc = call_capturing(oto().record_ai_usage, None, 1, 100, 10)
        self.assertIsNone(exc)

    def test_integral_float_and_digit_string_counts_are_converted_to_int(self):
        """変換できる値 (3.0 や "1234") はintにして記録すること。"""
        # 仕様: 「数値に変換できない値」だけが失敗。変換できる値 (3.0 / "1234") は int にして記録すると解釈する
        oto().record_ai_usage("action", 3.0, "1234", 56.0)
        d = read_log_records()[0]
        self.assertEqual((d["n_calls"], d["input_tokens"], d["output_tokens"]), (3, 1234, 56))
        for k in ("n_calls", "input_tokens", "output_tokens"):
            self.assertIsInstance(d[k], int, k)

    def test_integer_yen_is_recorded_as_a_float(self):
        """yen に int を渡したら float (3.0) として記録すること。"""
        # 仕様: yen は None または float。int を渡されたら float にすると解釈する (JSON 上は 3.0)
        oto().record_ai_usage("action", 1, 1, 1, 3)
        yen = read_log_records()[0]["yen"]
        self.assertEqual(yen, 3)
        self.assertIsInstance(yen, float)


class TestSpecGapRecordAiUsageAtIsLocalTime(InTempCwd):
    """`at` はローカル時刻 (A1 の finished_at / updated_at と同じく datetime.now() 基準) と解釈する。
    タイムゾーンを JST(+9) / EST(-5) に切り替えた派生クラス (下の make_tz_variants) でも同じテストを実行する。"""

    def test_at_follows_the_local_clock(self):
        """at がローカル時刻 (UTCではない) であること。JST/ESTに切り替えた派生クラスでも確認する。"""
        before = datetime.now().replace(microsecond=0)
        oto().record_ai_usage("action", 1, 1, 1)
        after = datetime.now()
        at = datetime.strptime(read_log_records()[0]["at"], "%Y-%m-%dT%H:%M:%S")
        self.assertLessEqual(before - timedelta(seconds=1), at)
        self.assertLessEqual(at, after + timedelta(seconds=1))


# ============================================================
# 3. observed_output_tokens_per_call
# ============================================================
class TestObservedOutputTokensPerCall(InTempCwd):
    """observed_output_tokens_per_call: 実績ログの直近N件から、1回あたりの出力トークンを求める。"""

    def obs(self, *args, **kwargs):
        return oto().observed_output_tokens_per_call(*args, **kwargs)

    # ---- 値が無いとき ------------------------------------------------
    def test_no_log_file_is_none(self):
        """実績ログが無ければ None。"""
        self.assertIsNone(self.obs("action"))

    def test_json_dir_without_the_log_is_none(self):
        """json/ はあるがログが無ければ None。"""
        os.makedirs("json")
        self.assertIsNone(self.obs("action"))

    def test_empty_log_is_none(self):
        """空のログなら None。"""
        write_text(LOG_PATH, "")
        self.assertIsNone(self.obs("action"))

    def test_unreadable_log_is_none_not_an_exception(self):
        """ログが読めない (パスがフォルダ) ときは、例外ではなく None。"""
        os.makedirs(LOG_PATH)                                    # ログの場所がディレクトリ (読めない)
        self.assertIsNone(self.obs("action"))

    def test_only_other_features_is_none(self):
        """他のfeatureの記録しか無ければ None。"""
        write_log(rec("review", 2, 4000), rec("cockpit", 1, 100))
        self.assertIsNone(self.obs("action"))

    def test_only_non_positive_call_counts_is_none(self):
        """n_calls が 0 以下の記録しか無ければ None。"""
        write_log(rec(n_calls=0, output_tokens=5000), rec(n_calls=-2, output_tokens=5000))
        self.assertIsNone(self.obs("action"))

    def test_only_broken_lines_is_none(self):
        """壊れた行しか無ければ None。"""
        write_log("これはJSONではない", "[1, 2]", '{"feature": "action"', "")
        self.assertIsNone(self.obs("action"))

    # ---- 計算 ----------------------------------------------------------
    def test_single_record_is_output_tokens_divided_by_calls(self):
        """1件だけなら 出力トークン ÷ 呼び出し回数。"""
        write_log(rec(n_calls=2, output_tokens=5000))
        self.assertEqual(self.obs("action"), 2500.0)

    def test_result_is_a_float(self):
        """戻り値は float。"""
        write_log(rec(n_calls=2, output_tokens=5000))
        self.assertIsInstance(self.obs("action"), float)

    def test_is_total_output_divided_by_total_calls_not_the_mean_of_ratios(self):
        """合計出力 ÷ 合計回数 (回数の違う記録を、比の平均にしない)。"""
        # (1000 + 6000) / (1 + 3) = 1750.0   (比の平均なら (1000 + 2000) / 2 = 1500.0 になってしまう)
        write_log(rec(n_calls=1, output_tokens=1000), rec(n_calls=3, output_tokens=6000))
        self.assertAlmostEqual(self.obs("action"), 1750.0)

    def test_input_tokens_and_yen_do_not_affect_the_result(self):
        """入力トークン・円は結果に影響しない。"""
        write_log(rec(n_calls=2, output_tokens=5000, input_tokens=9_999_999, yen=12345.0))
        self.assertEqual(self.obs("action"), 2500.0)

    def test_extra_keys_in_a_line_are_ignored(self):
        """行に余分なキーがあっても無視する。"""
        write_log(rec(n_calls=2, output_tokens=5000, memo="手書き", extra=[1, 2]))
        self.assertEqual(self.obs("action"), 2500.0)

    # ---- 直近 N 件 ---------------------------------------------------------
    def seven(self):
        """出力 1000..7000・各1回の7件 (古い順)。"""
        write_log(*[rec(n_calls=1, output_tokens=1000 * i) for i in range(1, 8)])

    def test_default_window_is_the_latest_five_records(self):
        """既定では直近5件 (末尾から5件) だけを使う。"""
        self.seven()
        self.assertEqual(self.obs("action"), 5000.0)               # (3+4+5+6+7)*1000/5。全7件なら 4000.0

    def test_explicit_window_sizes(self):
        """last_n を指定した件数だけ末尾から使う (記録数より大きければ全件)。"""
        self.seven()
        expected = {1: 7000.0, 2: 6500.0, 3: 6000.0, 4: 5500.0, 5: 5000.0, 6: 4500.0, 7: 4000.0, 100: 4000.0}
        for n, value in expected.items():
            with self.subTest(last_n=n):
                self.assertEqual(self.obs("action", last_n=n), value)

    def test_window_below_one_is_treated_as_one(self):
        """last_n が1未満なら1件として扱う。"""
        self.seven()
        for n in (0, -1, -100):
            with self.subTest(last_n=n):
                self.assertEqual(self.obs("action", last_n=n), 7000.0)

    def test_keyword_arguments_are_accepted(self):
        """引数名 (feature, last_n) のキーワード指定で呼べる。"""
        self.seven()
        self.assertEqual(self.obs(feature="action", last_n=2), 6500.0)

    def test_window_is_counted_from_the_end_of_the_file(self):
        """新旧は行の位置 (末尾が新しい) で決め、at の値では決めない。"""
        # 日時 at の新旧ではなく、行の位置 (末尾が新しい) で見る。at が古い行を末尾に置いても末尾が「新しい」
        write_log(rec(n_calls=1, output_tokens=1000, at="2026-10-04T09:00:00"),
                  rec(n_calls=1, output_tokens=9000, at="2020-01-01T00:00:00"))
        self.assertEqual(self.obs("action", last_n=1), 9000.0)

    # ---- 除外 -------------------------------------------------------------
    def test_other_features_are_ignored(self):
        """他のfeatureの行は無視し、featureごとに別々に求める。"""
        write_log(rec("action", 2, 4000), rec("review", 1, 99999), rec("action", 2, 6000))
        self.assertEqual(self.obs("action"), 2500.0)
        self.assertEqual(self.obs("review"), 99999.0)

    def test_other_features_do_not_use_up_the_window(self):
        """他のfeatureの行は直近N件に数えない。"""
        write_log(rec("action", 2, 4000), rec("review", 1, 111), rec("review", 1, 222), rec("review", 1, 333),
                  rec("action", 2, 6000))
        self.assertEqual(self.obs("action", last_n=2), 2500.0)

    def test_feature_match_is_exact(self):
        """featureは完全一致 (大文字小文字・前方一致・空白付きは別物)。"""
        write_log(rec("Action", 1, 999999), rec("action ", 1, 999999), rec("actions", 1, 999999),
                  rec("act", 1, 999999), rec("action", 2, 3000))
        self.assertEqual(self.obs("action"), 1500.0)

    def test_records_with_non_positive_call_counts_are_skipped_and_not_counted(self):
        """n_calls が 0 以下の記録は飛ばし、直近N件にも数えない。"""
        write_log(rec("action", 2, 4000), rec("action", 0, 999999), rec("action", -3, 999999), rec("action", 2, 6000))
        self.assertEqual(self.obs("action", last_n=2), 2500.0)

    def test_broken_lines_are_skipped_and_not_counted(self):
        """壊れた行 (JSONでない・n_callsの型違い) は飛ばし、直近N件にも数えない。"""
        good_a, good_b = rec("action", 2, 4000), rec("action", 2, 6000)
        broken = {
            "JSONでない": "これはJSONではない",
            "途中で切れたJSON": '{"at": "2026-10-04T09:00:00", "feature": "action", "n_calls": 2, "out',
            "空行": "",
            "空白だけの行": "   ",
            "配列": "[1, 2, 3]",
            "文字列": '"action"',
            "数値": "123",
            "n_callsが文字列": {"feature": "action", "n_calls": "abc", "output_tokens": 999999},
            "n_callsがリスト": {"feature": "action", "n_calls": [2], "output_tokens": 999999},
        }
        for label, line in broken.items():
            with self.subTest(broken=label):
                write_log(good_a, line, good_b)
                self.assertEqual(self.obs("action", last_n=2), 2500.0)

    def test_lines_whose_output_tokens_has_the_wrong_type_are_skipped_and_not_counted(self):
        """output_tokens の型が違う行も壊れた行として飛ばし、直近N件にも数えない。"""
        # 仕様: 壊れた行 (JSONでない/型が違う) は飛ばす (件数に数えない)。出力トークンの型違いも「型が違う」行。
        # 数えてしまうと (6000+0)/(2+1) = 2000.0 になり、実績が実際より小さく見える
        good_a, good_b = rec("action", 2, 4000), rec("action", 2, 6000)
        broken = {
            "output_tokensが文字列": {"feature": "action", "n_calls": 1, "output_tokens": "abc"},
            "output_tokensがリスト": {"feature": "action", "n_calls": 1, "output_tokens": [5]},
            "output_tokensがオブジェクト": {"feature": "action", "n_calls": 1, "output_tokens": {}},
        }
        for label, line in broken.items():
            with self.subTest(broken=label):
                write_log(good_a, line, good_b)
                self.assertEqual(self.obs("action", last_n=2), 2500.0)

    def test_log_that_cannot_be_decoded_is_none_not_an_exception(self):
        """UTF-8として読めないログ (cp932など) は、例外ではなく None。"""
        # 仕様: 「ファイルが…読めない → None」。Windows のメモ帳で ANSI (cp932) 保存された等で UTF-8 として読めないログ
        write_bytes(LOG_PATH, "アクションの実績です\n".encode("cp932"))
        result, _, exc = call_capturing(oto().observed_output_tokens_per_call, "action")
        self.assertIsNone(exc, f"例外が外へ出た: {exc!r}")
        self.assertIsNone(result)

    def test_negative_output_is_treated_as_zero_but_its_calls_still_count(self):
        """出力トークンが負なら 0 として扱う (回数は数える)。"""
        # (0 + 1000) / (2 + 2) = 250.0
        write_log(rec(n_calls=2, output_tokens=-500), rec(n_calls=2, output_tokens=1000))
        self.assertEqual(self.obs("action"), 250.0)

    def test_only_negative_output_gives_zero_not_none(self):
        """負の出力しか無い場合は None ではなく 0.0。"""
        write_log(rec(n_calls=2, output_tokens=-500))
        result = self.obs("action")
        self.assertIsNotNone(result)
        self.assertEqual(result, 0.0)

    def test_all_zero_outputs_give_zero_not_none(self):
        """出力がすべて 0 でも None ではなく 0.0。"""
        write_log(rec(n_calls=2, output_tokens=0))
        result = self.obs("action")
        self.assertIsNotNone(result)
        self.assertEqual(result, 0.0)

    # ---- ファイルの形 -------------------------------------------------------
    def test_crlf_line_endings_are_read(self):
        """改行が CRLF のログも読める。"""
        write_log(rec(n_calls=2, output_tokens=4000), rec(n_calls=2, output_tokens=6000), newline="\r\n")
        self.assertEqual(self.obs("action"), 2500.0)

    def test_last_line_without_a_final_newline_is_read(self):
        """最後の行に改行が無くても読める。"""
        write_log(rec(n_calls=2, output_tokens=4000), rec(n_calls=2, output_tokens=6000), final_newline=False)
        self.assertEqual(self.obs("action"), 2500.0)

    def test_blank_lines_between_records_are_ignored(self):
        """記録の間の空行は無視する。"""
        write_log(rec(n_calls=2, output_tokens=4000), "", rec(n_calls=2, output_tokens=6000))
        self.assertEqual(self.obs("action"), 2500.0)

    def test_records_before_thousands_of_other_feature_lines_are_still_found(self):
        """他featureの行が大量に後ろにあっても、前にある該当記録を見つける。"""
        write_log(rec("action", 2, 4000), *[rec("review", 1, 10) for _ in range(3000)])
        self.assertEqual(self.obs("action"), 2000.0)

    def test_reading_does_not_modify_the_log(self):
        """読むだけで、ログのバイト列も更新時刻も変えない。"""
        write_log(rec(n_calls=2, output_tokens=4000), "壊れた行")
        before, mtime = read_bytes(LOG_PATH), os.stat(LOG_PATH).st_mtime_ns
        self.obs("action")
        self.assertEqual(read_bytes(LOG_PATH), before)
        self.assertEqual(os.stat(LOG_PATH).st_mtime_ns, mtime)

    def test_round_trip_with_record_ai_usage(self):
        """record_ai_usage で書いた実績を読み戻して計算できる。"""
        oto().record_ai_usage("action", 2, 10000, 5000, 1.0, FLASH)
        oto().record_ai_usage("review", 5, 1, 999999, 9.0, FLASH)
        oto().record_ai_usage("action", 1, 4000, 1000, 0.5, FLASH)
        self.assertAlmostEqual(self.obs("action"), 6000 / 3)
        self.assertAlmostEqual(self.obs("review"), 999999 / 5)


class TestSpecGapObservedOutputTokensPerCall(InTempCwd):
    """仕様が曖昧/未記載の点 (null・UTF-8の一部破損・読むだけでファイルを作らない) を自然な解釈で確認する。"""

    def obs(self, *args, **kwargs):
        return oto().observed_output_tokens_per_call(*args, **kwargs)

    def test_null_numbers_are_treated_as_broken_lines(self):
        """null や欠落した数値の行も、壊れた行として飛ばす。"""
        # 仕様: 型が違う行は飛ばす。null も「型が違う」と解釈する (record_ai_usage は None を 0 にして書くので、
        # 実際のログには null は出てこない)
        good_a, good_b = rec("action", 2, 4000), rec("action", 2, 6000)
        for label, line in {"n_callsがnull": {"feature": "action", "n_calls": None, "output_tokens": 999999},
                            "output_tokensがnull": {"feature": "action", "n_calls": 1, "output_tokens": None},
                            "n_callsが無い": {"feature": "action", "output_tokens": 999999},
                            "output_tokensが無い": {"feature": "action", "n_calls": 1}}.items():
            with self.subTest(broken=label):
                write_log(good_a, line, good_b)
                self.assertEqual(self.obs("action", last_n=2), 2500.0)

    def test_a_few_invalid_utf8_bytes_among_good_lines_do_not_raise(self):
        """正常な行の中に壊れたバイトが混ざっても、例外を出さない (None か値)。"""
        # 全体が読めない場合 (上の test_log_that_cannot_be_decoded...) は None。一部の行だけが壊れているときは、
        # 「読めない」として None にするか、読める行だけ使うかが未記載 → どちらでも可 (例外にしないことだけ確認)
        write_bytes(LOG_PATH, json.dumps(rec(n_calls=2, output_tokens=5000)).encode("utf-8") + b"\n\xff\xfe\n")
        result, _, exc = call_capturing(oto().observed_output_tokens_per_call, "action")
        self.assertIsNone(exc, f"例外が外へ出た: {exc!r}")
        self.assertTrue(result is None or isinstance(result, float), result)

    def test_reading_creates_no_files_or_directories(self):
        """読むだけでは json/ やファイルを作らない。"""
        self.obs("action")
        self.assertFalse(os.path.exists("json"), "読むだけなのに json/ を作った")


# ============================================================
# 4. estimate_action_analysis_cost
# ============================================================
class TestEstimateWhichThreadsNeedAnalysis(InTempCwd):
    """AI解析が必要なスレッド = キャッシュに無い(または dict でない) / mail_count が現在のメール件数と違う / data._error が真。"""

    def calls(self, threads, cache_data):
        return estimate(threads, cache_data)["n_calls"]

    def test_thread_missing_from_the_cache_is_analyzed(self):
        """キャッシュに無いスレッドは解析対象 (1回)。"""
        self.assertEqual(self.calls({"A": thr("a", "b")}, cache_of()), 1)

    def test_cached_thread_with_the_same_mail_count_is_skipped(self):
        """キャッシュ済みで mail_count が同じなら解析しない。"""
        est = estimate({"A": thr("a", "b")}, cache_of(A=cache_entry(2)))
        self.assertEqual((est["n_calls"], est["input_chars"]), (0, 0))

    def test_changed_mail_count_is_analyzed(self):
        """mail_count が現在のメール件数と違えば解析対象。"""
        for cached_count in (1, 3, 0, 20):
            with self.subTest(cached_mail_count=cached_count):
                self.assertEqual(self.calls({"A": thr("a", "b")}, cache_of(A=cache_entry(cached_count))), 1)

    def test_error_thread_is_analyzed_even_when_the_mail_count_matches(self):
        """data._error が真なら mail_count が同じでも解析対象 (失敗の再試行)。"""
        self.assertEqual(self.calls({"A": thr("a", "b")}, cache_of(A=cache_entry(2, error=True))), 1)

    def test_truthy_error_flags_are_analyzed(self):
        """_error が真と評価される値なら解析対象。"""
        for flag in (True, 1, "x", [1], {"a": 1}):
            with self.subTest(flag=flag):
                data = {"thread_id": "A", "actions": [], "_error": flag}
                self.assertEqual(self.calls({"A": thr("a")}, cache_of(A=cache_entry(1, data=data))), 1)

    def test_falsy_error_flags_are_skipped(self):
        """_error が偽と評価される値なら解析しない。"""
        for flag in (False, 0, "", None, []):
            with self.subTest(flag=flag):
                data = {"thread_id": "A", "actions": [], "_error": flag}
                self.assertEqual(self.calls({"A": thr("a")}, cache_of(A=cache_entry(1, data=data))), 0)

    def test_cache_entry_that_is_not_a_dict_is_analyzed(self):
        """キャッシュのエントリが dict でなければ解析対象。"""
        for entry in (None, "x", 5, [], [1], True):
            with self.subTest(entry=entry):
                self.assertEqual(self.calls({"A": thr("a")}, cache_of(A=entry)), 1)

    def test_mixed_threads_count_only_the_ones_that_need_analysis(self):
        """複数スレッドで、解析が必要なものだけを数え、入力文字数もそれだけで足す。"""
        threads = {"OK": thr("a"), "NEW": thr("b"), "GREW": thr("c", "d"), "ERR": thr("e")}
        cache = cache_of(OK=cache_entry(1), GREW=cache_entry(1), ERR=cache_entry(1, error=True))
        est = estimate(threads, cache)
        self.assertEqual(est["n_calls"], 3)                         # NEW / GREW / ERR
        expected = thread_chars_reference(["b"]) + thread_chars_reference(["c", "d"]) + thread_chars_reference(["e"])
        self.assertEqual(est["input_chars"], expected)

    def test_cache_entries_for_threads_that_are_not_fetched_are_ignored(self):
        """今回取得していないスレッドのキャッシュは見積りに影響しない。"""
        cache = cache_of(OLD1=cache_entry(5), OLD2=cache_entry(1, error=True), A=cache_entry(1))
        self.assertEqual(self.calls({"A": thr("a")}, cache), 0)

    def test_each_thread_is_one_call(self):
        """解析対象のスレッド1つにつき呼び出し1回。"""
        self.assertEqual(self.calls(body_threads(7), cache_of()), 7)

    def test_unusable_cache_means_every_thread_is_analyzed(self):
        """cache_data が None・dictでない・threads が dict でないなら、全スレッドが解析対象。"""
        threads = {"A": thr("a"), "B": thr("b", "c")}
        unusable = {"None": None, "list": [], "str": "x", "int": 5, "bool": True,
                    "threadsが無い": {}, "threadsがNone": {"threads": None}, "threadsがlist": {"threads": []},
                    "threadsがstr": {"threads": "x"}, "別のキーだけ": {"foo": 1}}
        for label, cache in unusable.items():
            with self.subTest(cache=label):
                self.assertEqual(self.calls(threads, cache), 2)

    def test_empty_cache_threads_means_every_thread_is_analyzed(self):
        """キャッシュの threads が空なら全スレッドが解析対象。"""
        self.assertEqual(self.calls({"A": thr("a"), "B": thr("b")}, {"threads": {}}), 2)

    def test_no_threads_means_zero_calls(self):
        """threads が None または空なら呼び出し0回・入力0文字。"""
        for threads in ({}, None):
            for cache in (None, cache_of(A=cache_entry(1)), {"threads": {}}):
                with self.subTest(threads=threads, cache=cache):
                    est = estimate(threads, cache)
                    self.assertEqual(est["n_calls"], 0)
                    self.assertEqual(est["input_chars"], 0)


class TestSpecGapEstimateWhichThreadsNeedAnalysis(InTempCwd):
    """仕様が曖昧/未記載の点 (dataがNone・dictでない・入力を書き換えない・ファイルを書かない) を確認する。"""

    def test_data_none_does_not_crash(self):
        """data が None のキャッシュでも落ちない。"""
        # 仕様: 「data が None でも落ちない」。None のときに解析対象とするかは未記載 → 落ちないこと、
        # 他のスレッド (キャッシュに無い) が解析対象として正しく数えられること、だけを確認する
        threads = {"NODATA": thr("a"), "NEW": thr("b")}
        cache = cache_of(NODATA=cache_entry(1, data=None))
        est = estimate(threads, cache)
        self.assertIn(est["n_calls"], (1, 2))
        self.assertGreaterEqual(est["input_chars"], thread_chars_reference(["b"]))

    def test_entry_without_a_data_key_does_not_crash(self):
        """data キーが無いエントリでも落ちない。"""
        entry = {"mail_count": 1, "latest_entry_id": "E"}
        est = estimate({"NODATA": thr("a"), "NEW": thr("b")}, cache_of(NODATA=entry))
        self.assertIn(est["n_calls"], (1, 2))

    def test_data_that_is_not_a_dict_does_not_crash(self):
        """data が文字列・リスト・数値でも落ちない (壊れたキャッシュ)。"""
        # 仕様は「data が None でも落ちない」だけ。手編集・破損で data が文字列/リスト/数値のときも落ちない方が望ましいと
        # 解釈する (落ちても、続く summarize_action_dashboard が同じ規則で落ちるので実害は同じ)
        for data in ("エラー文字列", [1, 2], 5):
            with self.subTest(data=data):
                est = estimate({"A": thr("a")}, cache_of(A=cache_entry(1, data=data)))
                self.assertIn(est["n_calls"], (0, 1))

    def test_inputs_are_not_modified(self):
        """見積りは threads と cache_data を書き換えない。"""
        threads = {"A": thr("a" * 900, None, "x"), "B": {"mails": None}, "C": {}}
        cache = cache_of(A=cache_entry(3, error=True), Z=cache_entry(1))
        before_threads, before_cache = copy.deepcopy(threads), copy.deepcopy(cache)
        estimate(threads, cache)
        self.assertEqual(threads, before_threads, "threads を書き換えた")
        self.assertEqual(cache, before_cache, "cache_data を書き換えた")

    def test_estimating_writes_no_files(self):
        """見積りはファイルを書かない (実績ログへの追記もしない)。"""
        before = snapshot_files(".")
        estimate(body_threads(5), None)
        self.assertEqual(snapshot_files("."), before, "見積りがファイルを書いた (実績ログへの追記など)")


class TestEstimateInputChars(InTempCwd):
    """入力文字数 = min(Σ(min(len(str(body or "")), 800) + 40), 30000) + 1800。呼び出しはスレッドごとに1回。"""

    def chars(self, thread, cache_data=None):
        est = estimate({"A": thread}, cache_data)
        self.assertEqual(est["n_calls"], 1)
        return est["input_chars"]

    def test_formula_examples(self):
        """入力文字数の式 (本文は1通800字まで・1通+40字・スレッド合計30000字まで・+1800字) の具体例。"""
        cases = [
            ("メール0通", [], 1800),
            ("本文なし1通", [""], 1840),
            ("本文100字1通", ["a" * 100], 1940),
            ("本文799字", ["a" * 799], 2639),
            ("本文800字 (上限ちょうど)", ["a" * 800], 2640),
            ("本文801字 (上限超過)", ["a" * 801], 2640),
            ("本文5000字", ["a" * 5000], 2640),
            ("3通 10/20/30字", ["a" * 10, "b" * 20, "c" * 30], 1980),
            ("35通×800字 (合計29400は上限未満)", ["a" * 800] * 35, 31200),
            ("36通×800字 (合計30240は上限30000へ)", ["a" * 800] * 36, 31800),
            ("100通×800字", ["a" * 800] * 100, 31800),
        ]
        for label, bodies, expected in cases:
            with self.subTest(case=label):
                self.assertEqual(self.chars(thr(*bodies)), expected)

    def test_thread_total_cap_boundary(self):
        """スレッド合計の上限30000字の境界 (29999 / 30000 / 30001)。"""
        # 35通×800字 = 29400。最後の1通の長さで合計 29999 / 30000 / 30001 にする
        for last_body_len, expected in ((559, 31799), (560, 31800), (561, 31800)):
            with self.subTest(total=29400 + last_body_len + 40):
                self.assertEqual(self.chars(thr(*(["a" * 800] * 35 + ["b" * last_body_len]))), expected)

    def test_prompt_overhead_is_added_after_the_cap_so_it_is_not_capped(self):
        """プロンプト分の1800字は上限の後に足す (上限の対象外)。"""
        self.assertEqual(self.chars(thr(*(["a" * 800] * 100))), 30000 + 1800)

    def test_each_mail_counts_forty_extra_characters(self):
        """メール1通ごとに40字を足す。"""
        one, two = self.chars(thr("")), self.chars(thr("", ""))
        self.assertEqual(two - one, 40)

    def test_body_longer_than_the_limit_counts_only_the_limit(self):
        """本文が上限 (800字) を超えても800字として数える。"""
        self.assertEqual(self.chars(thr("a" * 801)), self.chars(thr("a" * 800)))

    def test_thread_without_mails_still_costs_the_prompt_overhead(self):
        """メールが0通・mails が無い/None でも、プロンプト分の1800字で1回と見積もる。"""
        for label, t in (("mails=[]", {"mails": []}), ("mailsキー無し", {}), ("mails=None", {"mails": None})):
            with self.subTest(case=label):
                self.assertEqual(self.chars(t), 1800)

    def test_mails_that_are_not_dicts_are_ignored(self):
        """dict でないメール要素は無視する。"""
        self.assertEqual(self.chars({"mails": [None, "文字列", 5, ["x"], mail("a" * 10)]}), 50 + 1800)
        self.assertEqual(self.chars({"mails": [None, "文字列", 5]}), 1800)

    def test_missing_or_none_body_counts_as_empty(self):
        """body が無い/None なら空 (0字 + 40字)。"""
        self.assertEqual(self.chars({"mails": [{"sender_name": "x"}]}), 40 + 1800)
        self.assertEqual(self.chars({"mails": [{"body": None}]}), 40 + 1800)

    def test_non_string_body_is_converted_with_str(self):
        """body が文字列でなければ str() の長さで数える。"""
        self.assertEqual(self.chars({"mails": [{"body": 12345}]}), 5 + 40 + 1800)

    def test_characters_not_bytes_are_counted(self):
        """バイト数ではなく文字数で数える。"""
        self.assertEqual(self.chars(thr("あ" * 100)), 100 + 40 + 1800)
        self.assertEqual(self.chars(thr("😀" * 10)), 10 + 40 + 1800)

    def test_whitespace_is_not_stripped(self):
        """空白・改行も文字として数える (stripしない)。"""
        self.assertEqual(self.chars(thr("   ")), 3 + 40 + 1800)
        self.assertEqual(self.chars(thr("\n\n\n")), 3 + 40 + 1800)

    def test_threads_that_need_analysis_are_summed(self):
        """解析が必要な複数スレッドの入力文字数を合計する。"""
        est = estimate({"A": thr("a" * 100), "B": thr(), "C": thr("c" * 10, "d" * 20)}, None)
        self.assertEqual(est["n_calls"], 3)
        self.assertEqual(est["input_chars"], 1940 + 1800 + (50 + 60 + 1800))

    def test_cached_threads_do_not_add_to_the_characters(self):
        """キャッシュ済みのスレッドは入力文字数に足さない。"""
        threads = {"A": thr("a" * 100), "B": thr("b" * 500)}
        est = estimate(threads, cache_of(B=cache_entry(1)))
        self.assertEqual((est["n_calls"], est["input_chars"]), (1, 1940))

    def test_input_chars_and_n_calls_are_ints(self):
        """n_calls と input_chars は int。"""
        est = estimate(body_threads(3), None)
        self.assertIs(type(est["n_calls"]), int)
        self.assertIs(type(est["input_chars"]), int)

    def test_thread_order_does_not_matter(self):
        """スレッドの並び順で結果が変わらない。"""
        items = list(body_threads(12, "あ" * 300).items()) + list({"X": thr("x" * 900, "y")}.items())
        a = estimate(dict(items), None)
        random.Random(7).shuffle(items)
        b = estimate(dict(items), None)
        self.assertEqual((a["n_calls"], a["input_chars"]), (b["n_calls"], b["input_chars"]))

    def test_matches_an_independent_calculation_on_random_threads(self):
        """乱数で作ったスレッドで、独立に書いた式の結果と一致する (固定シード)。"""
        rnd = random.Random(20261004)
        for trial in range(60):
            threads, expected_chars = {}, 0
            for i in range(rnd.randint(1, 8)):
                bodies = [rnd.choice(["", "x" * rnd.randint(1, 1500), None, 12345, "あ" * rnd.randint(1, 900)])
                          for _ in range(rnd.randint(0, 50))]
                threads[f"T{i}"] = {"mails": [mail(b) for b in bodies]}
                expected_chars += thread_chars_reference(bodies)
            with self.subTest(trial=trial):
                est = estimate(threads, None)
                self.assertEqual(est["n_calls"], len(threads))
                self.assertEqual(est["input_chars"], expected_chars)

    def test_many_threads_are_estimated_quickly(self):
        """3000スレッドでも5秒未満で見積もれる。"""
        threads = {f"T{i}": thr("本文" * 200, "返信" * 100) for i in range(3000)}
        t0 = time.time()
        est = estimate(threads, None)
        self.assertLess(time.time() - t0, 5.0)
        self.assertEqual(est["n_calls"], 3000)


class TestEstimateCalibration(InTempCwd):
    """1回あたりの出力トークン = 実績 (observed_output_tokens_per_call("action")) が真なら ×1.5、無ければ 2500。"""

    def est(self, n=1):
        return estimate(empty_threads(n), None)

    def test_without_a_log_the_default_2500_is_used_and_not_calibrated(self):
        """実績が無ければ1回あたり2500トークンで、calibrated は False。"""
        est = self.est()
        self.assertEqual(est["output_tokens_per_call"], 2500)
        self.assertIs(est["calibrated"], False)

    def test_with_a_log_the_observed_value_times_1_5_is_used(self):
        """実績があれば「実績 × 1.5」を1回あたりの出力にし、calibrated は True。"""
        write_log(rec("action", 2, 6000))                           # 実績 3000/回 → ×1.5 = 4500
        est = self.est()
        self.assertAlmostEqual(est["output_tokens_per_call"], 4500.0)
        self.assertIs(est["calibrated"], True)

    def test_output_tokens_follow_the_calibrated_value(self):
        """出力トークン合計は「1回あたり × 呼び出し回数」。"""
        write_log(rec("action", 2, 6000))
        est = self.est(3)
        self.assertEqual(est["output_tokens"], 13500)               # 4500 × 3回

    def test_default_output_tokens_are_2500_per_call(self):
        """実績なしの出力トークン合計は 2500 × 回数。"""
        self.assertEqual(self.est(3)["output_tokens"], 7500)

    def test_other_features_in_the_log_do_not_calibrate(self):
        """他のfeatureの実績では校正しない。"""
        write_log(rec("review", 2, 6000))
        est = self.est()
        self.assertEqual(est["output_tokens_per_call"], 2500)
        self.assertIs(est["calibrated"], False)

    def test_zero_observed_output_falls_back_to_the_default(self):
        """実績が 0 なら (真ではないので) 既定の2500を使う。"""
        # 実績が 0 (または0以下) のときは「真」ではないので既定値を使う
        write_log(rec("action", 2, 0))
        est = self.est()
        self.assertEqual(est["output_tokens_per_call"], 2500)
        self.assertIs(est["calibrated"], False)

    def test_negative_only_output_falls_back_to_the_default(self):
        """負の出力しか無い実績 (= 0) なら既定の2500を使う。"""
        write_log(rec("action", 2, -4000))
        est = self.est()
        self.assertEqual(est["output_tokens_per_call"], 2500)
        self.assertIs(est["calibrated"], False)

    def test_uses_the_latest_five_records_of_the_log(self):
        """実績は直近5件から求める。"""
        write_log(*[rec("action", 1, 1000 * i) for i in range(1, 8)])   # 直近5件の実績 = 5000/回 → ×1.5
        self.assertAlmostEqual(self.est()["output_tokens_per_call"], 7500.0)

    def test_uses_observed_output_tokens_per_call_with_feature_action(self):
        """実績の取得に observed_output_tokens_per_call(feature="action") を使う。"""
        seen = []

        def fake(feature, last_n=5):
            seen.append(feature)
            return 1000.0
        with mock.patch.object(oto(), "observed_output_tokens_per_call", fake):
            est = self.est()
        self.assertEqual(seen, ["action"])
        self.assertAlmostEqual(est["output_tokens_per_call"], 1500.0)
        self.assertIs(est["calibrated"], True)

    def test_observed_none_or_zero_uses_the_default(self):
        """実績が None / 0 なら既定値。"""
        for value in (None, 0, 0.0):
            with self.subTest(observed=value):
                with mock.patch.object(oto(), "observed_output_tokens_per_call", lambda feature, last_n=5: value):
                    est = self.est()
                self.assertEqual(est["output_tokens_per_call"], 2500)
                self.assertIs(est["calibrated"], False)

    def test_calibrated_is_a_bool(self):
        """calibrated は bool。"""
        self.assertIs(type(self.est()["calibrated"]), bool)
        write_log(rec("action", 1, 100))
        self.assertIs(type(self.est()["calibrated"]), bool)


def failed_count(threads, cache_data):
    return oto().count_failed_action_threads(threads, cache_data)


def errored_entry(cid="x", error=True, mail_count=1):
    """解析に失敗したスレッドのキャッシュ (data._error が真)。"""
    return cache_entry(mail_count, data={"thread_id": cid, "topic": "t", "summary": "(解析失敗: 接続エラー)",
                                         "category": "エラー", "actions": [], "_error": error})


class TestCountFailedActionThreads(InTempCwd):
    """count_failed_action_threads(threads, cache_data): 今回取得したスレッドのうち、キャッシュの data._error が真のものの数。"""

    def test_counts_the_fetched_threads_whose_cached_analysis_failed(self):
        """今回のスレッドのうち、キャッシュの data._error が真のものだけを数える。"""
        threads = {"A": thr("a"), "B": thr("b"), "C": thr("c"), "D": thr("d")}
        cache = cache_of(A=errored_entry(), B=cache_entry(1), C=errored_entry(), D=cache_entry(1))
        self.assertEqual(failed_count(threads, cache), 2)

    def test_all_failed_threads_are_counted(self):
        """全スレッドが失敗していれば、スレッド数と同じ。"""
        threads = {f"T{i}": thr("x") for i in range(6)}
        cache = cache_of(**{cid: errored_entry(cid) for cid in threads})
        self.assertEqual(failed_count(threads, cache), 6)

    def test_no_failures_is_zero(self):
        """失敗が無ければ 0。"""
        self.assertEqual(failed_count({"A": thr("a")}, cache_of(A=cache_entry(1))), 0)

    def test_failures_of_threads_that_were_not_fetched_are_not_counted(self):
        """今回取得していないスレッド (threads に無いキー) の失敗は数えない。"""
        cache = cache_of(OLD1=errored_entry(), OLD2=errored_entry(), A=errored_entry())
        self.assertEqual(failed_count({"A": thr("a")}, cache), 1)

    def test_threads_without_a_cache_entry_are_not_counted(self):
        """キャッシュに無いスレッドは数えない。"""
        self.assertEqual(failed_count({"A": thr("a"), "B": thr("b")}, cache_of(A=errored_entry())), 1)

    def test_data_that_is_not_a_dict_is_not_counted(self):
        """data が dict でない (None・文字列・リスト・数値・キー無し) ものは数えない。"""
        for data in (None, "エラー", [1, 2], 5):
            with self.subTest(data=data):
                self.assertEqual(failed_count({"A": thr("a")}, cache_of(A=cache_entry(1, data=data))), 0)
        self.assertEqual(failed_count({"A": thr("a")}, cache_of(A={"mail_count": 1})), 0)

    def test_cache_entries_that_are_not_dicts_are_not_counted(self):
        """キャッシュのエントリが dict でなければ数えない。"""
        for entry in (None, "x", 5, [], [1], True):
            with self.subTest(entry=entry):
                self.assertEqual(failed_count({"A": thr("a")}, cache_of(A=entry)), 0)

    def test_truthy_error_flags_are_counted(self):
        """_error が真と評価される値なら数える。"""
        for flag in (True, 1, "x", [1], {"a": 1}):
            with self.subTest(flag=flag):
                self.assertEqual(failed_count({"A": thr("a")}, cache_of(A=errored_entry(error=flag))), 1)

    def test_falsy_error_flags_are_not_counted(self):
        """_error が偽と評価される値なら数えない。"""
        for flag in (False, 0, "", None, []):
            with self.subTest(flag=flag):
                self.assertEqual(failed_count({"A": thr("a")}, cache_of(A=errored_entry(error=flag))), 0)

    def test_mail_count_is_not_compared(self):
        """mail_count は見ない (失敗の数だけを数える。見積りの対象判定とは別)。"""
        self.assertEqual(failed_count({"A": thr("a", "b", "c")}, cache_of(A=errored_entry(mail_count=1))), 1)

    def test_unusable_cache_data_gives_zero(self):
        """cache_data が dict でない・threads が dict でない (None など) なら 0。"""
        threads = {"A": thr("a"), "B": thr("b")}
        unusable = {"None": None, "list": [], "str": "x", "int": 5, "空dict": {}, "threadsがNone": {"threads": None},
                    "threadsがlist": {"threads": []}, "threadsがstr": {"threads": "x"}, "別のキーだけ": {"foo": 1}}
        for label, cache in unusable.items():
            with self.subTest(cache=label):
                self.assertEqual(failed_count(threads, cache), 0)

    def test_no_threads_gives_zero(self):
        """threads が None または空なら 0 (キャッシュに失敗が残っていても)。"""
        cache = cache_of(A=errored_entry(), B=errored_entry())
        for threads in (None, {}):
            with self.subTest(threads=threads):
                self.assertEqual(failed_count(threads, cache), 0)

    def test_result_is_an_int(self):
        """戻り値は int (bool ではない)。"""
        for cache in (None, cache_of(A=errored_entry())):
            result = failed_count({"A": thr("a")}, cache)
            self.assertIs(type(result), int)

    def test_garbage_inputs_never_raise(self):
        """壊れた入力 (threads がリスト・文字列・数値 など) でも例外を出さない。"""
        for threads in ([], ["A"], "A", 5, True, [None], (1, 2)):
            for cache in (None, cache_of(A=errored_entry()), {"threads": {"A": None}}, "x"):
                with self.subTest(threads=threads, cache=cache):
                    _, _, exc = call_capturing(oto().count_failed_action_threads, threads, cache)
                    self.assertIsNone(exc, f"例外が外へ出た: {exc!r}")

    def test_inputs_are_not_modified(self):
        """threads と cache_data を書き換えない。"""
        threads = {"A": thr("a"), "B": {"mails": None}}
        cache = cache_of(A=errored_entry(), Z=cache_entry(1, data=None))
        before_threads, before_cache = copy.deepcopy(threads), copy.deepcopy(cache)
        failed_count(threads, cache)
        self.assertEqual(threads, before_threads)
        self.assertEqual(cache, before_cache)

    def test_counting_writes_no_files(self):
        """数えるだけで、ファイルを書かない。"""
        before = snapshot_files(".")
        failed_count({"A": thr("a")}, cache_of(A=errored_entry()))
        self.assertEqual(snapshot_files("."), before)

    def test_many_threads_are_counted_quickly(self):
        """3000 スレッドでも 5 秒未満。"""
        threads = {f"T{i}": thr("x") for i in range(3000)}
        cache = cache_of(**{cid: (errored_entry() if i % 2 else cache_entry(1)) for i, cid in enumerate(threads)})
        t0 = time.time()
        result = failed_count(threads, cache)
        self.assertLess(time.time() - t0, 5.0)
        self.assertEqual(result, 1500)

    def test_agrees_with_the_estimate_on_which_threads_get_retried(self):
        """失敗したスレッドは、次回の見積りで再試行 (解析対象) として数えられる。"""
        threads = {"A": thr("a"), "B": thr("b"), "C": thr("c")}
        cache = cache_of(A=errored_entry(), B=cache_entry(1), C=errored_entry())
        self.assertEqual(failed_count(threads, cache), 2)
        self.assertEqual(estimate(threads, cache)["n_calls"], 2)


class TestSpecGapCountFailedActionThreads(InTempCwd):
    """仕様が曖昧な点 (threads が dict でないときの結果) を自然な解釈で確認する。"""

    def test_threads_that_is_not_a_dict_gives_zero(self):
        """仕様は「threads が dict でない → 0」(threads は今回取得したスレッドの dict)。リスト・文字列・数値でも 0 (例外なし)。"""
        cache = cache_of(A=errored_entry())
        for threads in (["A"], "A", 5, True, [None], (1, 2)):
            with self.subTest(threads=threads):
                result, _, exc = call_capturing(oto().count_failed_action_threads, threads, cache)
                self.assertIsNone(exc, f"例外が外へ出た: {exc!r}")
                self.assertEqual(result, 0)


class TestEstimateOutputFloor(InTempCwd):
    """実績があるときの1回あたり出力は max(実績×1.5, 2500×0.5=1250)。実績が極端に小さくても見積りが薄まらない。"""

    def est_with_observed(self, observed_per_call, n=1):
        write_log(rec("action", 1, observed_per_call))
        return estimate(empty_threads(n), None)

    def test_tiny_observed_output_is_raised_to_the_floor(self):
        """実績が極端に小さい (1回 100 トークン → ×1.5 = 150) と、下限の 1250 トークンになる。"""
        self.assertEqual(self.est_with_observed(100)["output_tokens_per_call"], 1250)

    def test_floor_boundary_just_below(self):
        """実績×1.5 が下限をわずかに下回る (833×1.5 = 1249.5) と、1250 になる。"""
        self.assertAlmostEqual(self.est_with_observed(833)["output_tokens_per_call"], 1250.0)

    def test_floor_boundary_just_above(self):
        """実績×1.5 が下限をわずかに上回る (834×1.5 = 1251) と、そのまま 1251。"""
        self.assertAlmostEqual(self.est_with_observed(834)["output_tokens_per_call"], 1251.0)

    def test_floor_boundary_exactly(self):
        """実績×1.5 がちょうど 1250 (2500/3 回 × 1.5) でも 1250。"""
        write_log(rec("action", 3, 2500))
        self.assertAlmostEqual(estimate(empty_threads(1), None)["output_tokens_per_call"], 1250.0)

    def test_observed_above_the_floor_is_unchanged(self):
        """下限より大きければ、従来どおり 実績×1.5 (1000×1.5 = 1500)。"""
        self.assertAlmostEqual(self.est_with_observed(1000)["output_tokens_per_call"], 1500.0)

    def test_large_observed_output_is_unchanged(self):
        """実績が大きい場合も 実績×1.5 のまま (下限は上限にならない)。"""
        self.assertAlmostEqual(self.est_with_observed(100000)["output_tokens_per_call"], 150000.0)

    def test_floor_applies_to_the_total_output_tokens(self):
        """出力トークン合計は 下限 × 呼び出し回数 (4回なら 5000)。"""
        self.assertEqual(self.est_with_observed(1, n=4)["output_tokens"], 5000)

    def test_without_a_log_the_default_is_still_2500_not_the_floor(self):
        """実績が無いときは従来どおり 2500 (下限は実績があるときだけの規則)。"""
        est = estimate(empty_threads(1), None)
        self.assertEqual(est["output_tokens_per_call"], 2500)
        self.assertIs(est["calibrated"], False)

    def test_floor_keeps_a_large_run_above_the_confirmation_threshold(self):
        """下限があるので、実績がほぼ 0 でも、大きな実行 (190件) は 100円以上と見積もられ確認になる。"""
        est = self.est_with_observed(1, n=190)
        self.assertAlmostEqual(est["yen"], yen_flash(190 * 1800, 190 * 1250), places=2)
        self.assertIs(est["needs_confirm"], True)

    def test_floor_does_not_turn_a_small_run_into_a_confirmation(self):
        """下限があっても、小さな実行 (100件) は 100円未満のまま (58.64円)。"""
        est = self.est_with_observed(1, n=100)
        self.assertAlmostEqual(est["yen"], yen_flash(100 * 1800, 100 * 1250), places=2)
        self.assertIs(est["needs_confirm"], False)


class TestSpecGapEstimateOutputFloor(InTempCwd):
    """仕様が曖昧な点 (下限の適用で calibrated がどうなるか・下限が定数に従うか) を自然な解釈で確認する。"""

    def test_calibrated_stays_true_when_the_floor_applies(self):
        """実績を使った (校正した) ことに変わりはないので、下限が効いても calibrated は True。"""
        write_log(rec("action", 1, 100))
        est = estimate(empty_threads(1), None)
        self.assertEqual(est["output_tokens_per_call"], 1250)
        self.assertIs(est["calibrated"], True)

    def test_floor_follows_the_ratio_constant(self):
        """下限は「ACTION_ESTIMATE_OUTPUT_FLOOR_RATIO × 既定の出力 (2500)」。定数を差し替えると追随する (0.2 → 500)。"""
        write_log(rec("action", 1, 100))
        with mock.patch.object(oto(), "ACTION_ESTIMATE_OUTPUT_FLOOR_RATIO", 0.2):
            self.assertAlmostEqual(estimate(empty_threads(1), None)["output_tokens_per_call"], 500.0)

    def test_floor_follows_the_default_output_constant(self):
        """下限の基準は ACTION_ESTIMATE_OUTPUT_TOKENS。差し替える (4000) と下限も追随する (4000×0.5 = 2000)。"""
        write_log(rec("action", 1, 100))
        with mock.patch.object(oto(), "ACTION_ESTIMATE_OUTPUT_TOKENS", 4000):
            self.assertAlmostEqual(estimate(empty_threads(1), None)["output_tokens_per_call"], 2000.0)


class HugeLine:
    """実績ログの行の作り手 (巨大整数・深いネスト)。"""
    BIG400 = "9" * 400                                           # float に直せない巨大整数 (400桁)
    BIG5000 = "9" * 5000                                         # json が整数の桁数の上限 (4300桁) で拒否する長さ

    @classmethod
    def big_calls(cls, digits):
        return '{"feature": "action", "n_calls": %s, "output_tokens": 100}' % digits

    @classmethod
    def big_output(cls, digits):
        return '{"feature": "action", "n_calls": 1, "output_tokens": %s}' % digits

    DEEP_ARRAY = "[" * 100000 + "]" * 100000                    # json.loads が RecursionError を出す深さ
    DEEP_OBJECT = '{"a": ' * 100000 + "1" + "}" * 100000


class TestObservedOutputTokensPerCallIsFullyProtected(InTempCwd):
    """(m2) 関数全体が例外から守られ、どんなログでも例外を出さない。読めない/実績無しなら None。"""

    def obs_safely(self, *args, **kwargs):
        result, _printed, exc = call_capturing(oto().observed_output_tokens_per_call, *args, **kwargs)
        self.assertIsNone(exc, f"例外が外へ出た: {exc!r}")
        return result

    def good_pair(self, middle):
        return [rec("action", 2, 4000), middle, rec("action", 2, 6000)]

    def test_huge_integers_do_not_raise(self):
        """400桁・5000桁の巨大整数 (n_calls / output_tokens) の行があっても、例外を出さない。"""
        for label, line in {"n_callsが400桁": HugeLine.big_calls(HugeLine.BIG400),
                            "output_tokensが400桁": HugeLine.big_output(HugeLine.BIG400),
                            "n_callsが5000桁": HugeLine.big_calls(HugeLine.BIG5000),
                            "output_tokensが5000桁": HugeLine.big_output(HugeLine.BIG5000)}.items():
            with self.subTest(line=label):
                write_log(*self.good_pair(line))
                self.obs_safely("action", last_n=5)

    def test_huge_integer_lines_are_skipped_or_give_none(self):
        """巨大整数の行は飛ばす (他の正常な行の結果 2500.0 になる) か、None。壊れた値を混ぜた値にはしない。"""
        for label, line in {"n_callsが400桁": HugeLine.big_calls(HugeLine.BIG400),
                            "output_tokensが400桁": HugeLine.big_output(HugeLine.BIG400),
                            "output_tokensが5000桁": HugeLine.big_output(HugeLine.BIG5000)}.items():
            with self.subTest(line=label):
                write_log(*self.good_pair(line))
                result = self.obs_safely("action", last_n=5)
                self.assertTrue(result is None or result == 2500.0, f"巨大整数の行が結果に混ざった: {result!r}")

    def test_output_tokens_over_one_trillion_are_skipped_as_broken(self):
        """(a) output_tokens が 1兆 (10**12) を超える行は壊れた行として飛ばす (他の行の結果 2500.0)。ちょうど1兆は数える。"""
        write_log(*self.good_pair(HugeLine.big_output(str(10 ** 12 + 1))))
        self.assertEqual(self.obs_safely("action", last_n=5), 2500.0)
        write_log(rec("action", 1, 10 ** 12))
        self.assertEqual(self.obs_safely("action"), float(10 ** 12))

    def test_call_counts_over_one_million_are_skipped_as_broken(self):
        """(a) n_calls が 100万を超える行は壊れた行として飛ばす (他の行の結果 2500.0)。ちょうど100万は数える。"""
        write_log(*self.good_pair(HugeLine.big_calls(str(10 ** 6 + 1))))
        self.assertEqual(self.obs_safely("action", last_n=5), 2500.0)
        write_log(rec("action", 10 ** 6, 2 * 10 ** 6))
        self.assertEqual(self.obs_safely("action"), 2.0)

    def test_estimate_with_a_10_pow_306_line_uses_the_other_records(self):
        """(a) 10**306 の出力の行があっても、見積りは例外を出さず、他の行の実績 (3000×1.5=4500) で見積もる。"""
        write_log(rec("action", 2, 6000), HugeLine.big_output(str(10 ** 306)))
        result, _, exc = call_capturing(oto().estimate_action_analysis_cost, empty_threads(3), None)
        self.assertIsNone(exc, f"例外が外へ出た: {exc!r}")
        self.assertAlmostEqual(result["output_tokens_per_call"], 4500.0)
        self.assertIs(result["calibrated"], True)

    def test_estimate_with_only_a_10_pow_306_line_uses_the_default(self):
        """(a) 10**306 の行しか無ければ、見積りは既定値 (2500・calibrated=False) になり、例外を出さない。"""
        write_log(HugeLine.big_output(str(10 ** 306)))
        result, _, exc = call_capturing(oto().estimate_action_analysis_cost, empty_threads(3), None)
        self.assertIsNone(exc, f"例外が外へ出た: {exc!r}")
        self.assertEqual(result["output_tokens_per_call"], 2500)
        self.assertIs(result["calibrated"], False)

    def test_only_a_huge_integer_line_gives_none_or_nothing_useful(self):
        """巨大整数の行しか無いときも、例外にしない (None か、飛ばして None)。"""
        write_log(HugeLine.big_output(HugeLine.BIG400))
        self.assertIsNone(self.obs_safely("action"))

    def test_deeply_nested_json_lines_do_not_raise(self):
        """深くネストした JSON の行 (RecursionError になる) があっても、例外を出さない。"""
        for label, line in {"深い配列": HugeLine.DEEP_ARRAY, "深いオブジェクト": HugeLine.DEEP_OBJECT}.items():
            with self.subTest(line=label):
                write_log(*self.good_pair(line))
                self.obs_safely("action", last_n=5)

    def test_deeply_nested_json_lines_are_skipped_or_give_none(self):
        """深いネストの行は飛ばす (結果 2500.0) か None。"""
        for label, line in {"深い配列": HugeLine.DEEP_ARRAY, "深いオブジェクト": HugeLine.DEEP_OBJECT}.items():
            with self.subTest(line=label):
                write_log(*self.good_pair(line))
                result = self.obs_safely("action", last_n=5)
                self.assertTrue(result is None or result == 2500.0, f"深いネストの行が結果に混ざった: {result!r}")

    def test_only_a_deeply_nested_line_gives_none(self):
        """深いネストの行しか無ければ None。"""
        write_log(HugeLine.DEEP_ARRAY)
        self.assertIsNone(self.obs_safely("action"))

    def test_a_nul_character_in_the_log_path_gives_none(self):
        """ログのパスが不正 (NUL文字を含み、open が ValueError) でも、例外ではなく None。"""
        with mock.patch.object(oto(), "AI_USAGE_LOG_FILE", "json/ai\0usage.jsonl"):
            self.assertIsNone(self.obs_safely("action"))

    def test_any_exception_while_parsing_gives_none(self):
        """行の解析中に想定外の例外 (RuntimeError など) が出ても、例外を外へ出さず None。"""
        write_log(rec("action", 2, 4000))
        with mock.patch("json.loads", side_effect=RuntimeError("テスト用の想定外")):
            self.assertIsNone(self.obs_safely("action"))

    def test_memory_error_while_parsing_gives_none(self):
        """行の解析中に MemoryError が出ても (Exception なので)、例外を外へ出さず None。"""
        write_log(rec("action", 2, 4000))
        with mock.patch("json.loads", side_effect=MemoryError("テスト用")):
            self.assertIsNone(self.obs_safely("action"))

    def test_ordinary_log_still_works_after_the_protection(self):
        """保護を入れても、普通のログの計算は変わらない (直近N件・合計÷合計)。"""
        write_log(rec("action", 1, 1000), rec("action", 3, 6000))
        self.assertAlmostEqual(self.obs_safely("action"), 1750.0)

    def test_estimate_survives_a_poisoned_log(self):
        """壊れたログ (巨大整数・深いネスト・UTF-8でない) があっても、見積り (estimate_action_analysis_cost) は既定値で成功する。"""
        write_bytes(LOG_PATH, (HugeLine.big_output(HugeLine.BIG400) + "\n" + HugeLine.DEEP_ARRAY + "\n").encode("utf-8")
                    + "壊れた".encode("cp932") + b"\n")
        est = estimate(empty_threads(3), None)
        self.assertEqual(est["n_calls"], 3)
        self.assertEqual(est["output_tokens_per_call"], 2500)
        self.assertIs(est["calibrated"], False)


class TestSpecGapEstimateAndLogUseTheConstants(InTempCwd):
    """仕様は定数 (ACTION_ESTIMATE_* / AI_USAGE_LOG_FILE) を定義し、見積り・ログがその値を使うと書いている。
    値を直書きして定数が使われない実装 (= 定数を変えても効かない) を検知するため、定数を差し替えて追随することを確認する。"""

    def patched(self, name, value):
        return mock.patch.object(oto(), name, value)

    def test_prompt_chars_constant_is_used(self):
        """ACTION_ESTIMATE_PROMPT_CHARS を差し替えると見積りに反映される (直書きではない)。"""
        with self.patched("ACTION_ESTIMATE_PROMPT_CHARS", 100):
            self.assertEqual(estimate({"A": thr()}, None)["input_chars"], 100)

    def test_output_tokens_constant_is_used_as_the_default_per_call(self):
        """ACTION_ESTIMATE_OUTPUT_TOKENS を既定の1回あたり出力として使う。"""
        with self.patched("ACTION_ESTIMATE_OUTPUT_TOKENS", 1000):
            est = estimate({"A": thr()}, None)
        self.assertEqual(est["output_tokens_per_call"], 1000)
        self.assertEqual(est["output_tokens"], 1000)

    def test_body_limit_constant_is_used(self):
        """ACTION_ESTIMATE_BODY_LIMIT を本文の上限として使う。"""
        with self.patched("ACTION_ESTIMATE_BODY_LIMIT", 10):
            self.assertEqual(estimate({"A": thr("a" * 50)}, None)["input_chars"], 10 + 40 + 1800)

    def test_thread_chars_max_constant_is_used(self):
        """ACTION_ESTIMATE_THREAD_CHARS_MAX をスレッド合計の上限として使う。"""
        with self.patched("ACTION_ESTIMATE_THREAD_CHARS_MAX", 100):
            self.assertEqual(estimate({"A": thr("a" * 500, "b" * 500)}, None)["input_chars"], 100 + 1800)

    def test_safety_constant_is_used(self):
        """ACTION_ESTIMATE_SAFETY を実績に掛ける係数として使う。"""
        write_log(rec("action", 2, 6000))                           # 実績 3000/回
        with self.patched("ACTION_ESTIMATE_SAFETY", 2.0):
            self.assertAlmostEqual(estimate({"A": thr()}, None)["output_tokens_per_call"], 6000.0)

    def test_log_file_constant_is_used_for_writing_and_reading(self):
        """AI_USAGE_LOG_FILE を書き込みにも読み込みにも使う。"""
        other = os.path.join("json", "other_usage.jsonl")
        with self.patched("AI_USAGE_LOG_FILE", other):
            oto().record_ai_usage("action", 2, 10, 6000, 1.0, FLASH)
            self.assertAlmostEqual(oto().observed_output_tokens_per_call("action"), 3000.0)
        self.assertTrue(os.path.isfile(other))
        self.assertFalse(os.path.exists(LOG_PATH), "定数を差し替えても既定のパスに書いた")


class TestEstimateReturnValue(InTempCwd):
    """estimate_action_analysis_cost の返り値 (キー・estimate_ai_cost_yenとの一致・円・モデル) を確認する。"""

    def test_has_exactly_the_documented_keys(self):
        """返り値のキーが estimate_ai_cost_yen のキー + n_calls / input_chars / output_tokens_per_call / calibrated だけ。"""
        base_keys = set(oto().estimate_ai_cost_yen(1, 1, 1))
        self.assertEqual(set(estimate(body_threads(2), None)),
                         base_keys | {"n_calls", "input_chars", "output_tokens_per_call", "calibrated"})

    def test_base_fields_are_those_of_estimate_ai_cost_yen_for_the_same_inputs(self):
        """基本の項目は、同じ入力で estimate_ai_cost_yen を呼んだ結果と同じ。"""
        est = estimate(body_threads(3, "あ" * 500), None)
        expected = oto().estimate_ai_cost_yen(est["input_chars"], est["n_calls"], est["output_tokens_per_call"])
        for key in expected:
            with self.subTest(key=key):
                self.assertEqual(est[key], expected[key])

    def test_input_tokens_follow_the_characters_and_output_tokens_the_calls(self):
        """入力トークンは文字数 (1文字=1トークン)、出力トークンは 2500 × 回数。"""
        est = estimate(empty_threads(4), None)
        self.assertEqual(est["input_chars"], 4 * 1800)
        self.assertEqual(est["input_tokens"], 4 * 1800)             # 1文字 = 1トークン (ESTIMATE_TOKENS_PER_CHAR)
        self.assertEqual(est["output_tokens"], 4 * 2500)

    def test_yen_for_the_default_model(self):
        """既定モデル (flash) の円が、単価から独立に計算した値と一致する。"""
        est = estimate(empty_threads(10), None)
        self.assertAlmostEqual(est["yen"], yen_flash(10 * 1800, 10 * 2500), places=2)
        self.assertIs(est["price_known"], True)

    def test_zero_calls_cost_nothing_and_need_no_confirmation(self):
        """解析0件なら費用0円・確認不要。"""
        est = estimate({}, None)
        self.assertEqual((est["n_calls"], est["input_chars"], est["input_tokens"], est["output_tokens"]), (0, 0, 0, 0))
        self.assertEqual(est["yen"], 0)
        self.assertIs(est["needs_confirm"], False)

    def test_keyword_arguments_are_accepted(self):
        """引数名 (threads, cache_data, model) のキーワード指定で呼べる。"""
        est = oto().estimate_action_analysis_cost(threads=empty_threads(1), cache_data=None, model=PRO)
        self.assertEqual(est["n_calls"], 1)

    def test_model_is_used_for_the_price(self):
        """modelに応じた単価で円を計算する。"""
        flash, pro = estimate(empty_threads(10), None, FLASH), estimate(empty_threads(10), None, PRO)
        self.assertAlmostEqual(flash["yen"], yen_flash(18000, 25000), places=2)
        self.assertAlmostEqual(pro["yen"], yen_pro(18000, 25000), places=2)
        self.assertGreater(pro["yen"], flash["yen"])

    def test_unknown_model_uses_the_highest_price_and_is_flagged(self):
        """単価表に無いモデルは最大単価で計算し、price_known が False。"""
        est = estimate(empty_threads(10), None, "gemini-9")
        self.assertIs(est["price_known"], False)
        self.assertAlmostEqual(est["yen"], yen_pro(18000, 25000), places=2)

    def test_model_none_uses_the_configured_default_model(self):
        """model=None は設定の既定モデルで計算する。"""
        write_json(oto().CONFIG_FILE, {"gemini_model": PRO})
        self.assertEqual(estimate(empty_threads(10), None)["yen"], estimate(empty_threads(10), None, PRO)["yen"])


class TestEstimateNeedsConfirmBoundary(InTempCwd):
    """needs_confirm は見込み円が COST_CONFIRM_THRESHOLD_YEN (100円) 以上で真。"""

    def test_92_empty_threads_stay_under_100_yen(self):
        """メール0通のスレッド92個 (99.95円) は確認不要。"""
        est = estimate(empty_threads(92), None)
        self.assertAlmostEqual(est["yen"], 99.95, places=2)         # 入力165600 + 出力230000 トークン
        self.assertIs(est["needs_confirm"], False)

    def test_93_empty_threads_reach_100_yen(self):
        """同93個 (101.04円) は確認が必要 (100円以上)。"""
        est = estimate(empty_threads(93), None)
        self.assertAlmostEqual(est["yen"], 101.04, places=2)        # 入力167400 + 出力232500 トークン
        self.assertIs(est["needs_confirm"], True)

    def test_a_small_run_does_not_need_confirmation(self):
        """少数のスレッドでは確認不要。"""
        self.assertIs(estimate(body_threads(3), None)["needs_confirm"], False)

    def test_needs_confirm_agrees_with_yen_for_many_sizes(self):
        """needs_confirm は常に「円が100円以上か」と一致する。"""
        for n in (1, 10, 50, 91, 92, 93, 94, 200):
            with self.subTest(n=n):
                est = estimate(empty_threads(n), None)
                self.assertEqual(est["needs_confirm"], est["yen"] >= 100)

    def test_exactly_at_the_threshold_needs_confirmation(self):
        """ちょうど閾値の金額なら確認が必要 (以上)。"""
        yen = estimate(empty_threads(1), None)["yen"]
        with mock.patch.object(oto(), "COST_CONFIRM_THRESHOLD_YEN", yen):
            self.assertIs(estimate(empty_threads(1), None)["needs_confirm"], True)
        with mock.patch.object(oto(), "COST_CONFIRM_THRESHOLD_YEN", yen + 0.01):
            self.assertIs(estimate(empty_threads(1), None)["needs_confirm"], False)

    def test_calibrated_output_moves_one_call_across_the_threshold(self):
        """実績で校正した出力量により、1回の見積りが100円をまたぐ (99.69円 → 100.29円)。"""
        # 1スレッド・1回。実績 166000/回 (×1.5 = 249000 トークン) → 99.69円 / 実績 167000/回 → 100.29円
        write_log(rec("action", 1, 166000))
        under = estimate(empty_threads(1), None)
        write_log(rec("action", 1, 167000))
        over = estimate(empty_threads(1), None)
        self.assertAlmostEqual(under["yen"], 99.69, places=2)
        self.assertIs(under["needs_confirm"], False)
        self.assertAlmostEqual(over["yen"], 100.29, places=2)
        self.assertIs(over["needs_confirm"], True)

    def test_two_calibrated_calls_need_confirmation_where_one_does_not(self):
        """1回は100円未満でも、2回なら100円以上で確認が必要になる。"""
        write_log(rec("action", 1, 100000))                         # ×1.5 = 150000 トークン/回 → 1回 60.09円
        one, two = estimate(empty_threads(1), None), estimate(empty_threads(2), None)
        self.assertAlmostEqual(one["yen"], 60.09, places=2)
        self.assertIs(one["needs_confirm"], False)
        self.assertAlmostEqual(two["yen"], 120.17, places=2)
        self.assertIs(two["needs_confirm"], True)

    def test_unknown_model_is_priced_high_and_can_cross_the_threshold(self):
        """単価未登録のモデルは高めの単価なので、同じ件数でも確認が必要になりうる。"""
        flash, unknown = estimate(empty_threads(40), None, FLASH), estimate(empty_threads(40), None, "gemini-9")
        self.assertIs(flash["needs_confirm"], False)
        self.assertIs(unknown["needs_confirm"], True)


# ============================================================
# 5. 案内文 (build_action_decision_snapshot) の文言
# ============================================================
class TestGuidanceWording(a1snap.SnapBase):
    """「判断待ち」パネルの注意書きが、新しいボタン「🔄 解析のみ更新」を案内する。"""

    def status(self, **env_kw):
        self.env(**env_kw)
        return self.snap()["status_text"]

    def test_notice_line_points_to_the_update_button(self):
        """注意書きの「最新にするには…」が「🔄 解析のみ更新」を案内する。"""
        t = self.status(threads={"P": make_thread()}, statuses={}, finished=self.ago(hours=2))
        self.assertIn("（最新にするには「🔄 解析のみ更新」）。", t)

    def test_error_line_points_to_the_update_button(self):
        """解析失敗の案内が「その期間を含めて「🔄 解析のみ更新」すると再試行されます。」になる。"""
        t = self.status(threads={"P": make_thread(), "E": make_thread(error=True)}, statuses={},
                        finished=self.ago(hours=2))
        self.assertIn("その期間を含めて「🔄 解析のみ更新」すると再試行されます。", t)

    def test_old_button_name_is_not_mentioned_in_any_situation(self):
        """どの状況でも、旧ボタン名 (アクション一覧を生成) は案内文に残らない。"""
        envs = {
            "新しい解析": dict(threads={"P": make_thread()}, statuses={}, finished=self.ago(hours=2)),
            "古い解析": dict(threads={"P": make_thread()}, statuses={}, finished=self.ago(hours=30)),
            "解析失敗あり": dict(threads={"P": make_thread(), "E": make_thread(error=True)}, statuses={},
                             finished=self.ago(hours=2)),
            "解析の記録なし": dict(threads={"P": make_thread()}, statuses={}, finished=None),
        }
        for label, kw in envs.items():
            with self.subTest(situation=label):
                with tempdir_cwd():
                    self.assertNotIn("アクション一覧を生成", self.status(**kw))


# ============================================================
# GUI 共通ハーネス (A1 の GuiCase を拡張)
# ============================================================
def load_cache_file():
    """analysis_cache/action_dashboard.json (無ければ空) を読む。"""
    return read_json(CACHE_PATH) if os.path.exists(CACHE_PATH) else {"threads": {}}


class ScriptedModels:
    """生成AI (client.models) の差し替え。プロンプトに含まれるスレッドIDで、成功か接続失敗かを決める
    (実際の MailSummarizer.summarize_action_dashboard がこれを呼ぶ)。成功は固定のトークン使用量を返す。"""

    def __init__(self, fail_cids=(), fail_all=False, in_tokens=2000, out_tokens=500):
        self.fail_cids, self.fail_all = set(fail_cids), fail_all
        self.in_tokens, self.out_tokens = in_tokens, out_tokens
        self.calls = []

    def generate_content(self, **kw):
        prompt = str(kw.get("contents", ""))
        self.calls.append(prompt)
        if self.fail_all or any(f'"{cid}"' in prompt for cid in self.fail_cids):
            raise ConnectionError("proxy unreachable")
        cid = re.search(r'thread_id は理由を問わず "([^"]+)"', prompt).group(1)
        text = json.dumps({"thread_id": cid, "topic": f"件名{cid}", "summary": "要約", "category": "その他",
                           "action_type": "通知・共有", "importance": "低", "reasoning": "", "actions": []},
                          ensure_ascii=False)
        usage = types.SimpleNamespace(prompt_token_count=self.in_tokens, candidates_token_count=self.out_tokens)
        return types.SimpleNamespace(text=text, usage_metadata=usage)


def real_threads(n):
    """group_by_thread の実際の形 (実 MailSummarizer が読むキーを持つ) のスレッド n 個。各1通。"""
    return {f"CONV{i:03d}": {"topic": f"件名{i}", "mails": [{"body": "本文" * 50, "sender_name": "太郎"}],
                             "latest_entry_id": "E", "latest_date": datetime(2026, 10, 4, 9, 0, 0),
                             "all_categories": set()} for i in range(n)}


def make_real_summarizer(models):
    """実際の MailSummarizer (cache の書き込み・_error の付与・トークン集計はそのまま) + 差し替えのクライアント。"""
    cls = oto().MailSummarizer
    ms = cls.__new__(cls)
    ms.client = types.SimpleNamespace(models=models)
    ms.model_id = FLASH
    ms._configured = True
    ms.total_input_tokens = 0
    ms.total_output_tokens = 0
    return ms


class FlowSummarizer(a1gui.StubSummarizer):
    """解析のスタブ。呼び出しの記録・トークンの加算・失敗・解析中に止める (gate) ができる。"""

    model_id = FLASH

    def __init__(self, events, add_in=0, add_out=0, fail=None, cards=None, gate=None, started=None, fail_cids=(),
                 break_cache=False):
        super().__init__(fail=fail)
        self.events = events
        self.add_in, self.add_out = add_in, add_out
        self.cards = list(cards) if cards else []
        self.gate, self.started = gate, started
        self.fail_cids = set(fail_cids)           # 解析に失敗したことにするスレッド (キャッシュへ data._error を書く)
        self.break_cache = break_cache            # 解析の最後にキャッシュを壊す (解析後に読めない状況)

    def summarize_action_dashboard(self, threads, progress_callback=None, reset_conversation_ids=None,
                                   expand_from_cache=False):
        self.events.append("summarize")
        self.calls.append({"threads": threads, "reset": reset_conversation_ids, "expand": expand_from_cache})
        if self.started is not None:
            self.started.set()
        if self.gate is not None:
            self.gate.wait(10)
        if self.fail:
            raise self.fail
        self.total_input_tokens += self.add_in
        self.total_output_tokens += self.add_out
        if self.fail_cids:
            cache = load_cache_file()
            for cid in self.fail_cids:
                n_mails = len((threads.get(cid) or {}).get("mails") or [])
                cache["threads"][cid] = {"mail_count": n_mails, "latest_entry_id": "E", "data": {
                    "thread_id": cid, "topic": "t", "summary": "(解析失敗: 接続エラー)", "category": "エラー",
                    "actions": [], "_error": True}}
            write_json(CACHE_PATH, cache)
        if self.break_cache:
            write_text(CACHE_PATH, "{broken")
        return {"threads": [], "action_cards": list(self.cards)}


class FlowReporter(a1gui.StubReporter):
    """HTML 生成のスタブ。呼び出しの記録と、返すパス (None ならブラウザを開かない)。"""

    def __init__(self, events, path=None, fail=None):
        super().__init__(fail=fail)
        self.events = events
        self.path = path

    def generate_action_dashboard_report(self, action_cards, date_range, total_input, total_output,
                                         reformat_mode=False, search_days=7):
        self.events.append("report")
        self.calls.append({"action_cards": action_cards, "date_range": date_range, "total_input": total_input,
                           "total_output": total_output, "reformat_mode": reformat_mode, "search_days": search_days})
        if self.fail:
            raise self.fail
        return self.path


class UpdateCase(a1gui.GuiCase):
    """_run_action_dashboard / _confirm_ai_cost / _ui_action_tab の機能テスト用ハーネス。

    - messagebox の showerror / askyesno は、呼ばれたスレッドがメインスレッドかを記録し、askyesno の答えを
      self.ask_answer で指定できる (例外オブジェクトを入れると、それを raise する)。
    - webbrowser.open は実際には開かず self.browser_calls に記録する。
    - 費用/実績ログ/last_run の関数と、GUI の _confirm_ai_cost / _save_action_dashboard_result は、呼び出し順を
      self.events に記録するラッパを付ける (中身は本物をそのまま呼ぶ)。
    """

    def setUp(self):
        # 循環参照のゴミ (前のテストの Tk オブジェクトなど) を、ワーカースレッドの上で GC が走って解放してしまうと、
        # 「Tcl_AsyncDelete: async handler deleted by the wrong thread」でプロセスごと異常終了することがある。
        # テストの実行中は GC を止め、後始末 (_teardown_gui) の最後にメインスレッドで回収する
        gc.disable()
        self.addCleanup(gc.enable)                              # 最初に登録 = 最後に実行 (setUp が途中で失敗しても戻す)
        super().setUp()
        self.events = []                  # 呼び出し順 (fetch/group/estimate/confirm/summarize/record/last_run/report/save_result/refresh)
        self.method_calls = {}            # tag -> [(args, kwargs), ...]  (ラッパで記録した呼び出し)
        self.module_reals = {}            # tag -> 差し替え前の本物の関数
        self.refreshes = []               # 再読込が呼ばれた時点の画面の状態
        self.printed = io.StringIO()      # 実行中に print された文字列 (ワーカーのものを含む)
        self.browser_calls = []
        self.group_args = []
        self.threads_returned = {}
        self.start_state = self.mid_state = self.final_state = None
        self.mid_totals = None
        p = mock.patch("webbrowser.open", lambda url, *a, **k: self.browser_calls.append(url) or True)
        p.start()
        self.addCleanup(p.stop)
        for name, tag in (("estimate_action_analysis_cost", "estimate"), ("record_ai_usage", "record"),
                          ("save_action_last_run", "last_run")):
            self._spy_module(name, tag)

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

    def _teardown_gui(self):
        # 基底の後始末は、A1 パネルの <<NotebookTabChanged>> などの保留イベントを流すため 0.3 秒固定で待つ。
        # このハーネスはパネルを作らないので、その待ちは不要 (ワーカーの終了待ち・コールバック例外の検査は基底のまま行う)
        orig_settle = self.settle
        self.settle = lambda seconds=0.15: orig_settle(0.01)
        try:
            super()._teardown_gui()
        finally:
            self.settle = orig_settle
            self.gui = None
            gc.collect(0)                                        # メインスレッドで、このテストの Tk オブジェクトを回収する
            #   (GC を止めていたので、このテストで作ったものは全て最も若い世代にある。全世代の回収は、他のテストが
            #    キャッシュした巨大な AST 等のせいで重く、1回 0.3 秒かかる)

    def dialog_entries(self, name):
        return [d for d in self.dialogs if d[0] == name]

    @staticmethod
    def title_and_message(entry):
        _name, args, kwargs = entry
        title = args[0] if args else kwargs.get("title")
        message = args[1] if len(args) > 1 else kwargs.get("message")
        return title, message

    # ---- 呼び出し記録のラッパ -------------------------------------------------
    def _spy_module(self, name, tag):
        real = getattr(oto(), name)
        self.module_reals[tag] = real
        self.method_calls[tag] = []

        def wrapper(*args, **kwargs):
            self.events.append(tag)
            self.method_calls[tag].append((args, kwargs))
            return real(*args, **kwargs)
        p = mock.patch.object(oto(), name, wrapper)
        p.start()
        self.addCleanup(p.stop)

    def _spy_method(self, gui, name, tag):
        real = getattr(gui, name)
        self.method_calls[tag] = []

        def wrapper(*args, **kwargs):
            self.events.append(tag)
            self.method_calls[tag].append((args, kwargs))
            return real(*args, **kwargs)
        setattr(gui, name, wrapper)

    # ---- GUI 構築 -----------------------------------------------------
    def make_gui(self, **kw):
        # _run_action_dashboard / _confirm_ai_cost は「判断待ち」パネルを使わない (再読込は差し替える)。パネルを作らない
        # ことで、タブ切替などの保留イベントやワーカーが無くなり、テストが速くなる (_ui_action_tab のテストは自分で作る)
        kw.setdefault("select_action", True)
        kw.setdefault("build_panel", False)
        gui = super().make_gui(**kw)
        # 「保存された (= _save_action_dashboard_result が呼ばれた)」ことを検知できるよう、最初は無効にしておく
        gui.btn_reformat_action.config(state="disabled")
        self._spy_method(gui, "_confirm_ai_cost", "confirm")
        self._spy_method(gui, "_save_action_dashboard_result", "save_result")
        return gui

    def install_outlook(self, gui, fetch_error=None, group_error=None):
        outlook = gui.outlook
        self.fetched = [object()]                                # 取得したメール (group_by_thread へ渡るはず)

        def fetch(days, progress_callback=None):
            self.events.append("fetch")
            outlook.period_calls.append(days)
            if fetch_error is not None:
                raise fetch_error
            return self.fetched

        def group(mails):
            self.events.append("group")
            self.group_args.append(mails)
            if group_error is not None:
                raise group_error
            return self.threads_returned
        outlook.get_relevant_mails_for_period = fetch
        outlook.group_by_thread = group

    def ui_state(self, gui):
        return {
            "run_state": str(gui.btn_run_action.cget("state")), "run_text": str(gui.btn_run_action.cget("text")),
            "update_state": str(gui.btn_update_action.cget("state")),
            "update_text": str(gui.btn_update_action.cget("text")),
            "reformat_state": str(gui.btn_reformat_action.cget("state")),
            "status": str(gui.lbl_stat.cget("text")),
        }

    # ---- 1回分の実行 ----------------------------------------------------
    def flow(self, open_browser, *, threads=None, cache=None, log=None, add_in=0, add_out=0, fail=None,
             report_fail=None, report_path=None, ask=True, fetch_error=None, group_error=None, cards=None,
             model=None, initial_totals=None, period=None, during=None, last_run=None, timeout=8,
             build_tab=False, press=None, log_bytes=None, real_models=None, fail_cids=(), break_cache=False):
        """GUI を組み立て、_run_action_dashboard(open_browser) を実行して、終了処理 (再読込の呼び出し) まで待つ。

        threads    : group_by_thread が返すスレッド (既定: 空 = 解析するものが無い)
        cache      : analysis_cache/action_dashboard.json に書く内容 (None は書かない)
        log        : 実績ログ json/ai_usage_log.jsonl に書く行 (dict / str のリスト)
        log_bytes  : 実績ログへそのまま書くバイト列 (UTF-8 として読めない壊れたログの再現用)
        ask        : 費用確認ダイアログ (askyesno) の答え
        during     : 指定すると、解析の最中 (summarize 内) で止め、その間に during(gui) を実行してから再開する
        build_tab  : True なら実際の _ui_action_tab でタブ (本物のボタン) を組み立てる
        press      : 指定すると、_run_action_dashboard を直接呼ぶ代わりに press(gui) を呼ぶ (例: ボタンの invoke)
        real_models: 指定すると、スタブの代わりに実際の MailSummarizer (差し替えの生成AIクライアント=ScriptedModels) を使う
        fail_cids  : スタブの解析が「失敗した」ことにするスレッドID (キャッシュに data._error を書く)
        open_browser=None のときは引数なしで呼ぶ (既定値の確認用)。
        """
        gui = self.make_gui()
        if build_tab:
            gui._ui_action_tab()
            gui.root.update()
        if model is not None:
            gui.config["gemini_model"] = model
        if period is not None:
            gui.v_action_prd.set(period)
        if cache is not None:
            write_json(CACHE_PATH, cache)
        if log is not None:
            write_log(*log)
        if log_bytes is not None:
            write_bytes(LOG_PATH, log_bytes)
        if last_run is not None:
            write_json(LAST_RUN_PATH, last_run)
        self.ask_answer = ask
        self.threads_returned = threads if threads is not None else {}
        self.install_outlook(gui, fetch_error, group_error)
        self.gate, self.started = threading.Event(), threading.Event()
        self.addCleanup(self.gate.set)                           # 失敗してもワーカーを止めたままにしない
        if real_models is not None:
            gui.summarizer = make_real_summarizer(real_models)
        else:
            gui.summarizer = FlowSummarizer(self.events, add_in, add_out, fail, cards,
                                            gate=self.gate if during is not None else None, started=self.started,
                                            fail_cids=fail_cids, break_cache=break_cache)
        if initial_totals is not None:
            gui.summarizer.total_input_tokens, gui.summarizer.total_output_tokens = initial_totals
        gui.reporter = FlowReporter(self.events, path=report_path, fail=report_fail)

        def fake_refresh():
            self.events.append("refresh")
            self.refreshes.append(self.ui_state(gui))
        gui._refresh_action_decision_view = fake_refresh

        # 実機ではメインループが回っている最中にボタンが押される。テストでもメインループの中から呼ぶ
        # (ループの外で呼ぶと、ワーカーの最初の Tk 呼び出しが「メインループ未突入」で 0.1 秒ずつ待たされて遅くなる)
        started_call = {}

        def press_button():
            try:
                if press is not None:
                    press(gui)
                elif open_browser is None:
                    gui._run_action_dashboard()
                else:
                    gui._run_action_dashboard(open_browser=open_browser)
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
                self.assertTrue(ok, f"解析 (summarize_action_dashboard) まで進まない: events={self.events}")
                self.settle(0.02)
                self.mid_state = self.ui_state(gui)
                self.mid_totals = (gui.summarizer.total_input_tokens, gui.summarizer.total_output_tokens)
                during(gui)
                self.gate.set()
            ok = self.pump(lambda: bool(self.refreshes) or press_failed(), timeout=timeout)
            if press_failed():
                raise started_call["error"]
            self.assertTrue(ok, f"終了処理 (判断待ちの再読込) まで到達しない: events={self.events}, ui={self.ui_state(gui)}")
            self.settle(0.02)                                    # 再読込のあとに続く処理が無いことの確認を兼ねる
        self.final_state = self.ui_state(gui)
        return gui

    # ---- よく使う読み出し -------------------------------------------------
    def log_records(self):
        return read_log_records() if os.path.exists(LOG_PATH) else []

    def estimate_arguments(self):
        """estimate_action_analysis_cost への最初の呼び出しの引数を {名前: 値} で返す。"""
        calls = self.method_calls["estimate"]
        self.assertTrue(calls, "estimate_action_analysis_cost が呼ばれていない")
        args, kwargs = calls[0]
        return dict(inspect.signature(self.module_reals["estimate"]).bind(*args, **kwargs).arguments)

    def expected_dialog_text(self, label, yen, n_calls, calibrated):
        basis = "直近の実績から" if calibrated else "実績がまだ無いため多めに"
        return f"{label}のAI費用の見込み: 約{yen:.0f}円（{n_calls}件。{basis}見積もった概算です）\n\n実行しますか？"

    # ---- _confirm_ai_cost の直接呼び出し -----------------------------------------
    @staticmethod
    def estimate_dict(**kw):
        """estimate_action_analysis_cost の返り値と同じキー構成の見積り (既定: 93件・101.04円・実績なし)。"""
        base = {"input_tokens": 167400, "output_tokens": 232500, "yen": 101.04, "needs_confirm": True,
                "price_known": True, "n_calls": 93, "input_chars": 167400, "output_tokens_per_call": 2500,
                "calibrated": False}
        base.update(kw)
        return base

    def confirm(self, estimate, label=ACTION_LABEL, timeout=6, prepare=None):
        """ワーカースレッドから _confirm_ai_cost を呼び (実際の呼び出し元と同じ)、メインスレッドで mainloop を回して
        結果を待つ。self.gui (make_gui 済み) を使う。戻らなければ失敗 (呼び出し側が固まった)。"""
        gui = self.gui
        res = {}

        def work():
            try:
                if prepare is not None:
                    prepare()                                    # ワーカーが _confirm_ai_cost を呼ぶ直前の準備
                res["value"] = gui._confirm_ai_cost(estimate, label)
            except Exception as e:                              # noqa: BLE001
                res["error"] = e
            finally:
                self.events.append("returned")
                res["done"] = True
        # ワーカーはメインループが回っている最中に起動する (ループの外だと、最初の Tk 呼び出しが 0.1 秒ずつ待たされる)
        gui.root.after(0, lambda: threading.Thread(target=work, daemon=True).start())
        ok = self.pump(lambda: res.get("done", False), timeout=timeout)
        self.assertTrue(ok, "_confirm_ai_cost が戻らない (呼び出し側が固まった)")
        if "error" in res:
            raise res["error"]
        return res["value"]


# ============================================================
# 6. 画面: 「🔄 解析のみ更新」ボタン (_ui_action_tab)
# ============================================================
class TestUpdateButtonUi(UpdateCase):
    """実際の _ui_action_tab を組み立て、ボタンの文言・配置・command を確認する。"""

    def build(self, saved_result=False):
        gui = self.make_gui(build_panel=False)
        self.run_calls = []

        def fake_run(open_browser=True):
            self.run_calls.append(open_browser)
        gui._run_action_dashboard = fake_run                     # command がどちらの形で束縛されても、これを呼ぶ
        if saved_result:
            write_text(LAST_RESULT_PATH, "{}")
        gui._ui_action_tab()
        gui.root.update()
        return gui

    def test_update_button_is_a_ttk_button_with_the_specified_label(self):
        """btn_update_action が ttk.Button で、表示は「🔄 解析のみ更新」。"""
        gui = self.build()
        self.assertIsInstance(gui.btn_update_action, ttk.Button)
        self.assertEqual(str(gui.btn_update_action.cget("text")), UPDATE_TEXT)

    def test_update_button_is_enabled_at_startup(self):
        """起動時は押せる状態。"""
        gui = self.build()
        self.assertEqual(str(gui.btn_update_action.cget("state")), "normal")

    def test_update_button_shares_the_parent_with_the_run_button(self):
        """「📋 アクション一覧を生成」と同じ枠に置く。"""
        gui = self.build()
        self.assertIs(gui.btn_update_action.master, gui.btn_run_action.master)

    def test_pack_order_is_run_then_update_then_reformat(self):
        """並びは run → update → reformat (runの直後・reformatの前)。"""
        gui = self.build()
        slaves = gui.btn_run_action.master.pack_slaves()
        i_run, i_update, i_reformat = (slaves.index(gui.btn_run_action), slaves.index(gui.btn_update_action),
                                       slaves.index(gui.btn_reformat_action))
        self.assertEqual((i_update, i_reformat), (i_run + 1, i_run + 2),
                         "「🔄 解析のみ更新」は run の直後・reformat の前のはず")

    def test_buttons_are_in_one_row_from_left_to_right(self):
        """3つのボタンが同じ行に、左から run・update・reformat の順に並ぶ。"""
        gui = self.build()
        run, update, reformat = gui.btn_run_action, gui.btn_update_action, gui.btn_reformat_action
        self.assertLess(run.winfo_rootx(), update.winfo_rootx())
        self.assertLess(update.winfo_rootx(), reformat.winfo_rootx())
        self.assertLessEqual(abs(run.winfo_rooty() - update.winfo_rooty()), 3, "run と update が同じ行にない")
        self.assertLessEqual(abs(update.winfo_rooty() - reformat.winfo_rooty()), 3)

    def test_update_button_does_not_overlap_its_neighbours(self):
        """ボタン同士が重ならない。"""
        gui = self.build()
        run, update, reformat = gui.btn_run_action, gui.btn_update_action, gui.btn_reformat_action
        self.assertLessEqual(run.winfo_rootx() + run.winfo_width(), update.winfo_rootx())
        self.assertLessEqual(update.winfo_rootx() + update.winfo_width(), reformat.winfo_rootx())

    def test_run_button_label_is_unchanged(self):
        """既存の「📋 アクション一覧を生成」の文言は変わらない。"""
        gui = self.build()
        self.assertEqual(str(gui.btn_run_action.cget("text")), RUN_TEXT)

    def test_run_button_still_runs_with_the_browser(self):
        """「📋 アクション一覧を生成」は従来どおりブラウザを開く実行 (open_browser=True)。"""
        gui = self.build()
        gui.btn_run_action.invoke()
        self.assertEqual(self.run_calls, [True])

    def test_update_button_runs_without_opening_the_browser(self):
        """「🔄 解析のみ更新」は open_browser=False で実行する。"""
        gui = self.build()
        gui.btn_update_action.invoke()
        self.assertEqual(self.run_calls, [False])

    def test_reformat_button_label_and_initial_state_are_unchanged(self):
        """「🎨 フォーマットのみ再生成」の文言と初期状態 (保存済みの結果なし → 無効) は変わらない。"""
        gui = self.build()
        self.assertEqual(str(gui.btn_reformat_action.cget("text")), REFORMAT_TEXT)
        self.assertEqual(str(gui.btn_reformat_action.cget("state")), "disabled")      # 保存済みの結果が無い

    def test_reformat_button_is_enabled_when_a_saved_result_exists(self):
        """保存済みの結果があれば「🎨 フォーマットのみ再生成」は最初から有効。"""
        gui = self.build(saved_result=True)
        self.assertEqual(str(gui.btn_reformat_action.cget("state")), "normal")

    def test_there_is_exactly_one_update_button_in_the_tab(self):
        """タブ内に「解析のみ更新」ボタンはちょうど1つ。"""
        gui = self.build()
        found = [w for w in a1gui.walk(gui.tab_action)
                 if isinstance(w, (ttk.Button, tk.Button)) and "解析のみ更新" in str(w.cget("text"))]
        self.assertEqual(len(found), 1)


class TestUpdateButtonEndToEnd(UpdateCase):
    """実際の _ui_action_tab の本物のボタンを押して、押したボタンどおりの動きになること (配線の確認)。"""

    def press_update(self, **kw):
        return self.flow(None, build_tab=True, press=lambda gui: gui.btn_update_action.invoke(), **kw)

    def press_run(self, **kw):
        return self.flow(None, build_tab=True, press=lambda gui: gui.btn_run_action.invoke(), **kw)

    def test_pressing_update_makes_no_html_and_opens_no_browser(self):
        """本物の「🔄 解析のみ更新」を押すと、HTMLを作らずブラウザも開かない。"""
        gui = self.press_update(report_path="/tmp/should-not-open.html")
        self.assertEqual(gui.reporter.calls, [])
        self.assertEqual(self.browser_calls, [])

    def test_pressing_update_saves_the_result_and_the_last_run_and_enables_reformat(self):
        """押すと、結果 (last_result) と最終解析の記録を保存し、「🎨 フォーマットのみ再生成」が有効になる。"""
        self.press_update(cards=[{"thread_id": "T1", "actions": []}])
        self.assertTrue(os.path.exists(LAST_RESULT_PATH))
        self.assertTrue(os.path.exists(LAST_RUN_PATH))
        self.assertEqual(self.final_state["reformat_state"], "normal")

    def test_pressing_update_ends_with_the_update_status_and_both_buttons_restored(self):
        """終了時のステータスは「✅ 解析のみ更新 完了」で、2つのボタンが元に戻る。"""
        self.press_update()
        s = self.final_state
        self.assertIn("✅ 解析のみ更新 完了", s["status"])
        self.assertEqual((s["run_state"], s["run_text"], s["update_state"], s["update_text"]),
                         ("normal", RUN_TEXT, "normal", UPDATE_TEXT))

    def test_pressing_update_disables_both_buttons(self):
        """押した直後、2つのボタンとも無効になり、実行中の文言になる。"""
        self.press_update()
        s = self.start_state
        self.assertEqual((s["run_state"], s["run_text"], s["update_state"], s["update_text"]),
                         ("disabled", RUN_BUSY_TEXT, "disabled", UPDATE_BUSY_TEXT))

    def test_pressing_run_generates_the_html_and_opens_the_browser(self):
        """本物の「📋 アクション一覧を生成」を押すと、従来どおりHTMLを作りブラウザで開く。"""
        gui = self.press_run(report_path="/tmp/report-XYZ.html")
        self.assertEqual(len(gui.reporter.calls), 1)
        self.assertEqual(self.browser_calls, ["/tmp/report-XYZ.html"])

    def test_pressing_run_ends_with_the_run_status_and_both_buttons_restored(self):
        """終了時のステータスは「✅ アクションダッシュボード生成完了」で、2つのボタンが元に戻る。"""
        self.press_run()
        s = self.final_state
        self.assertIn("✅ アクションダッシュボード生成完了", s["status"])
        self.assertEqual((s["run_state"], s["run_text"], s["update_state"], s["update_text"]),
                         ("normal", RUN_TEXT, "normal", UPDATE_TEXT))

    def test_pressing_run_disables_both_buttons(self):
        """押した直後、2つのボタンとも無効になる。"""
        self.press_run()
        s = self.start_state
        self.assertEqual((s["run_state"], s["run_text"], s["update_state"], s["update_text"]),
                         ("disabled", RUN_BUSY_TEXT, "disabled", UPDATE_BUSY_TEXT))

    def test_a_disabled_update_button_cannot_start_a_second_run_while_one_is_running(self):
        """実行中に「🔄 解析のみ更新」を押しても、2回目の解析は走らない。"""
        gui = self.press_update(threads=body_threads(1), during=lambda g: g.btn_update_action.invoke())
        self.assertEqual(len(gui.summarizer.calls), 1, "実行中に押された「解析のみ更新」で2回目の解析が走った")

    def test_a_disabled_run_button_cannot_start_a_second_run_while_one_is_running(self):
        """「🔄 解析のみ更新」の実行中に「📋 アクション一覧を生成」を押しても、走らない。"""
        gui = self.press_update(threads=body_threads(1), during=lambda g: g.btn_run_action.invoke())
        self.assertEqual(len(gui.summarizer.calls), 1, "「解析のみ更新」の実行中に押された「アクション一覧を生成」が走った")


# ============================================================
# 7. _confirm_ai_cost
# ============================================================
class TestConfirmAiCost(UpdateCase):
    """(ワーカースレッドから呼ぶ) needs_confirm が真ならメインスレッドで askyesno を出し、押された結果を返す。"""

    def test_no_dialog_and_true_when_confirmation_is_not_needed(self):
        """needs_confirm が偽なら、ダイアログを出さず True。"""
        self.make_gui()
        result = self.confirm(self.estimate_dict(needs_confirm=False, yen=5.0, n_calls=3))
        self.assertIs(result, True)
        self.assertEqual(self.dialog_entries("askyesno"), [])

    def test_the_needs_confirm_flag_decides_not_the_yen(self):
        """確認の要否は needs_confirm で決める (円の大小ではない)。"""
        self.make_gui()
        self.assertIs(self.confirm(self.estimate_dict(needs_confirm=False, yen=500.0)), True)
        self.assertEqual(self.dialog_entries("askyesno"), [], "yen が大きくても needs_confirm が偽ならダイアログは出さない")
        self.ask_answer = True
        self.confirm(self.estimate_dict(needs_confirm=True, yen=1.0))
        self.assertEqual(len(self.dialog_entries("askyesno")), 1, "needs_confirm が真ならダイアログを出す")

    def test_yes_returns_true(self):
        """「はい」なら True。"""
        self.make_gui()
        self.ask_answer = True
        self.assertIs(self.confirm(self.estimate_dict()), True)

    def test_no_returns_false(self):
        """「いいえ」なら False。"""
        self.make_gui()
        self.ask_answer = False
        self.assertIs(self.confirm(self.estimate_dict()), False)

    def test_one_askyesno_dialog_is_shown(self):
        """askyesno のダイアログを1回だけ出す。"""
        self.make_gui()
        self.confirm(self.estimate_dict())
        self.assertEqual([d[0] for d in self.dialogs], ["askyesno"])

    def test_dialog_title(self):
        """ダイアログのタイトルは「AI費用の確認」。"""
        self.make_gui()
        self.confirm(self.estimate_dict())
        title, _ = self.title_and_message(self.dialog_entries("askyesno")[0])
        self.assertEqual(title, CONFIRM_TITLE)

    def test_dialog_text_without_a_track_record(self):
        """実績が無いときの本文 (「実績がまだ無いため多めに」) が仕様どおり。"""
        self.make_gui()
        self.confirm(self.estimate_dict(yen=101.04, n_calls=93, calibrated=False))
        _, message = self.title_and_message(self.dialog_entries("askyesno")[0])
        self.assertEqual(message, "アクション解析のAI費用の見込み: 約101円（93件。実績がまだ無いため多めに見積もった概算です）"
                                  "\n\n実行しますか？")

    def test_dialog_text_with_a_track_record(self):
        """実績があるときの本文 (「直近の実績から」) が仕様どおり。"""
        self.make_gui()
        self.confirm(self.estimate_dict(yen=120.17, n_calls=2, calibrated=True))
        _, message = self.title_and_message(self.dialog_entries("askyesno")[0])
        self.assertEqual(message, "アクション解析のAI費用の見込み: 約120円（2件。直近の実績から見積もった概算です）"
                                  "\n\n実行しますか？")

    def test_dialog_text_uses_the_given_label(self):
        """本文の先頭に、渡した label を使う。"""
        self.make_gui()
        self.confirm(self.estimate_dict(yen=150.0, n_calls=4, calibrated=True), label="テスト処理")
        _, message = self.title_and_message(self.dialog_entries("askyesno")[0])
        self.assertTrue(message.startswith("テスト処理のAI費用の見込み: 約150円（4件。"), message)
        self.assertNotIn(ACTION_LABEL, message)

    def test_yen_is_shown_with_no_decimals(self):
        """円は小数なし (四捨五入) で「約N円」と表示する。"""
        self.make_gui()
        for yen, shown in ((123.456, "123"), (123.6, "124"), (100.4, "100"), (1234.0, "1234")):
            with self.subTest(yen=yen):
                self.dialogs.clear()
                self.confirm(self.estimate_dict(yen=yen))
                _, message = self.title_and_message(self.dialog_entries("askyesno")[0])
                self.assertIn(f"約{shown}円（", message)

    def test_call_count_is_shown(self):
        """件数を「N件」と表示する。"""
        self.make_gui()
        self.confirm(self.estimate_dict(n_calls=1234))
        _, message = self.title_and_message(self.dialog_entries("askyesno")[0])
        self.assertIn("（1234件。", message)

    def test_dialog_is_shown_from_the_main_thread(self):
        """ダイアログはメインスレッドで出す (ワーカーから直接出さない)。"""
        self.make_gui()
        self.confirm(self.estimate_dict())
        self.assertEqual(self.dialog_threads, [("askyesno", True)], "ワーカースレッドから直接ダイアログを出している")

    def test_the_caller_waits_until_the_dialog_is_answered(self):
        """呼び出し側 (ワーカー) は、ダイアログに答えるまで待つ。"""
        self.make_gui()

        def answered(*a, **k):
            self.events.append("dialog")
            return False
        with mock.patch.object(tkmessagebox, "askyesno", answered):
            self.confirm(self.estimate_dict())
        self.assertEqual([e for e in self.events if e in ("dialog", "returned")], ["dialog", "returned"])

    def test_two_confirmations_in_a_row_both_work(self):
        """続けて2回確認しても、どちらも動く。"""
        self.make_gui()
        self.ask_answer = False
        self.assertIs(self.confirm(self.estimate_dict()), False)
        self.ask_answer = True
        self.assertIs(self.confirm(self.estimate_dict()), True)
        self.assertEqual(len(self.dialog_entries("askyesno")), 2)

    def test_an_exception_in_the_dialog_does_not_leave_the_caller_hanging(self):
        """ダイアログ内で例外が出ても、呼び出し側が固まらない。"""
        self.make_gui()
        self.ask_answer = RuntimeError("テスト用のダイアログ例外")
        self.confirm(self.estimate_dict())                       # 戻ること自体が確認 (固まれば timeout で失敗)
        # 例外を Tk のコールバック例外として出すか、内部で握りつぶすかは仕様に無い → どちらでも可
        self.callback_errors[:] = [e for e in self.callback_errors if "テスト用のダイアログ例外" not in e]

    def test_an_exception_in_the_dialog_means_false(self):
        """(M2) ダイアログ内で例外が出たら done をセットし、False (実行しない) として戻る。"""
        self.make_gui()
        self.ask_answer = RuntimeError("テスト用のダイアログ例外")
        result = self.confirm(self.estimate_dict())
        self.callback_errors[:] = [e for e in self.callback_errors if "テスト用のダイアログ例外" not in e]
        self.assertIs(result, False)

    def test_dialog_is_called_with_the_main_window_as_parent(self):
        """(M2) askyesno は parent=メインウィンドウ (self.root) つきで呼ぶ (他のウィンドウの後ろに隠れない)。"""
        gui = self.make_gui()
        self.confirm(self.estimate_dict())
        _name, _args, kwargs = self.dialog_entries("askyesno")[0]
        self.assertIs(kwargs.get("parent"), gui.root)

    def test_dialog_default_button_is_no(self):
        """(M2) askyesno は default="no" つき (既定のボタンは「いいえ」。Enterの連打で費用を使わない)。"""
        self.make_gui()
        self.confirm(self.estimate_dict())
        _name, _args, kwargs = self.dialog_entries("askyesno")[0]
        self.assertEqual(kwargs.get("default"), "no")

    def test_dialog_title_and_text_are_still_the_first_two_arguments(self):
        """(M2) タイトルと本文は askyesno の第1・第2引数 (parent/default はキーワードで足す)。"""
        self.make_gui()
        self.confirm(self.estimate_dict(yen=101.04, n_calls=93, calibrated=False))
        _name, args, _kwargs = self.dialog_entries("askyesno")[0]
        self.assertEqual(args[0], CONFIRM_TITLE)
        self.assertEqual(args[1], self.expected_dialog_text(ACTION_LABEL, 101.04, 93, calibrated=False))

    def test_waiting_status_is_shown_while_the_dialog_is_open(self):
        """(M2) ワーカーから呼んだとき、ダイアログを待つ間のステータスは「⏸ AI費用の確認待ち（約N円）…」(タイマーなし)。"""
        self.make_gui()
        seen = {}

        def asked(*a, **k):
            seen["status"] = str(self.gui.lbl_stat.cget("text"))
            seen["running"] = getattr(self.gui, "is_running", None)
            return True
        with mock.patch.object(tkmessagebox, "askyesno", asked):
            self.confirm(self.estimate_dict(yen=101.04))
        self.assertEqual(seen["status"], WAITING_STATUS.format(yen=101.04))
        self.assertIs(seen["running"], False, "待機中のステータスで経過時間のタイマーを動かしている (start_timer=False のはず)")

    def test_a_failing_status_update_does_not_stop_the_dialog(self):
        """(M2) 待機中ステータスの更新が失敗しても (握りつぶして)、ダイアログを出して答えを返す。"""
        gui = self.make_gui()

        def broken(*a, **k):
            raise RuntimeError("ステータス更新の失敗(テスト用)")
        gui._set_status = broken
        self.ask_answer = True
        self.assertIs(self.confirm(self.estimate_dict()), True)
        self.assertEqual(len(self.dialog_entries("askyesno")), 1)

    def front_recorder(self, gui, state):
        """root の state() を差し替え (state = "iconic" なら最小化中)、deiconify / lift / attributes の呼び出し順を記録する。"""
        order = []
        real_attr, real_lift, real_deiconify = gui.root.attributes, gui.root.lift, gui.root.deiconify

        def attributes(*a, **k):
            order.append(("attributes",) + a)
            return real_attr(*a, **k)

        def lift(*a, **k):
            order.append(("lift",))
            return real_lift(*a, **k)

        def deiconify(*a, **k):
            order.append(("deiconify",))
            return real_deiconify(*a, **k)
        gui.root.attributes, gui.root.lift, gui.root.deiconify = attributes, lift, deiconify
        gui.root.state = lambda newstate=None: state
        return order

    def confirm_recording_the_dialog(self, order):
        def asked(*a, **k):
            order.append(("dialog",))
            return True
        with mock.patch.object(tkmessagebox, "askyesno", asked):
            self.confirm(self.estimate_dict())
        return order[:order.index(("dialog",))]

    def test_the_window_is_brought_to_the_front_before_the_dialog(self):
        """(M2) ダイアログの前に lift と -topmost (True) を試し、300ms後に -topmost を False へ戻す (最小化かどうかに関係なく)。"""
        gui = self.make_gui()
        order = self.front_recorder(gui, "normal")
        before = self.confirm_recording_the_dialog(order)
        self.assertIn("lift", [o[0] for o in before])
        self.assertTrue([o for o in before if o[0] == "attributes" and len(o) >= 3 and o[1] == "-topmost" and o[2]],
                        f"ダイアログの前に -topmost を True にしていない: {before}")
        ok = self.pump(lambda: any(o[0] == "attributes" and len(o) >= 3 and o[1] == "-topmost" and not o[2]
                                   for o in order), timeout=3)
        self.assertTrue(ok, "300ms後に -topmost を False へ戻していない")

    def test_a_minimized_window_is_restored_before_the_dialog(self):
        """(M2) 最小化中 (state()=="iconic") のときだけ、ダイアログの前に deiconify で元に戻す。"""
        gui = self.make_gui()
        before = self.confirm_recording_the_dialog(self.front_recorder(gui, "iconic"))
        self.assertIn("deiconify", [o[0] for o in before])

    def test_a_window_that_is_not_minimized_is_not_deiconified(self):
        """(M2) 最小化されていない (通常・最大化) ときは deiconify を呼ばない (最大化の窓を通常サイズに戻さない)。"""
        for state in ("normal", "zoomed"):
            with self.subTest(state=state):
                gui = self.gui or self.make_gui()
                order = self.front_recorder(gui, state)
                before = self.confirm_recording_the_dialog(order)
                self.assertNotIn("deiconify", [o[0] for o in order], f"state={state} なのに deiconify した")
                self.assertIn("lift", [o[0] for o in before])

    def test_failing_attempts_to_raise_the_window_do_not_stop_the_dialog(self):
        """(M2) 前面化の試み (deiconify / lift / -topmost) が全部失敗しても (握りつぶして)、ダイアログを出して答えを返す。"""
        gui = self.make_gui()

        def broken(*a, **k):
            raise tk.TclError("前面化の失敗(テスト用)")
        gui.root.attributes, gui.root.lift, gui.root.deiconify = broken, broken, broken
        gui.root.state = broken                                 # 最小化かどうかの確認も失敗する
        self.ask_answer = True
        self.assertIs(self.confirm(self.estimate_dict()), True)
        self.assertEqual(len(self.dialog_entries("askyesno")), 1)

    # ---- メインスレッドから呼んだとき: 待たずに直接ダイアログを出す (デッドロックしない) ------------------
    def call_from_main_thread(self, estimate, label=ACTION_LABEL):
        """テスト (= GUI) のメインスレッドから _confirm_ai_cost を直接呼ぶ。固まる実装でテスト全体が止まらないよう、
        Unix では 5 秒の SIGALRM で打ち切る (Windows には無いので、そのまま呼ぶ)。"""
        gui = self.gui
        use_alarm = hasattr(signal, "SIGALRM")
        old = None
        if use_alarm:
            def on_alarm(signum, frame):
                raise AssertionError("メインスレッドから呼んだ _confirm_ai_cost が5秒たっても戻らない (固まった)")
            old = signal.signal(signal.SIGALRM, on_alarm)
            signal.alarm(5)
        try:
            return gui._confirm_ai_cost(estimate, label)
        finally:
            if use_alarm:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old)

    def test_called_from_the_main_thread_it_returns_the_answer_without_hanging(self):
        """(M2) メインスレッドから呼んでも固まらず、「はい」なら True を返す (直接 askyesno を出す)。"""
        self.make_gui()
        self.ask_answer = True
        self.assertIs(self.call_from_main_thread(self.estimate_dict()), True)

    def test_called_from_the_main_thread_no_returns_false(self):
        """(M2) メインスレッドから呼んで「いいえ」なら False。"""
        self.make_gui()
        self.ask_answer = False
        self.assertIs(self.call_from_main_thread(self.estimate_dict()), False)

    def test_called_from_the_main_thread_the_dialog_is_shown_directly_in_that_thread(self):
        """(M2) メインスレッドから呼んだときは、そのスレッドで直接ダイアログを1回だけ出す。"""
        self.make_gui()
        self.call_from_main_thread(self.estimate_dict())
        self.assertEqual(self.dialog_threads, [("askyesno", True)])

    def test_called_from_the_main_thread_the_dialog_has_the_same_title_text_parent_and_default(self):
        """(M2) メインスレッドから呼んだときも、タイトル・本文・parent・default="no" はワーカーから呼んだときと同じ。"""
        gui = self.make_gui()
        self.call_from_main_thread(self.estimate_dict(yen=101.04, n_calls=93, calibrated=False))
        _name, args, kwargs = self.dialog_entries("askyesno")[0]
        self.assertEqual(args[0], CONFIRM_TITLE)
        self.assertEqual(args[1], self.expected_dialog_text(ACTION_LABEL, 101.04, 93, calibrated=False))
        self.assertIs(kwargs.get("parent"), gui.root)
        self.assertEqual(kwargs.get("default"), "no")

    def test_called_from_the_main_thread_without_need_returns_true_without_a_dialog(self):
        """(M2) メインスレッドから呼んでも、needs_confirm が偽ならダイアログを出さず True。"""
        self.make_gui()
        self.assertIs(self.call_from_main_thread(self.estimate_dict(needs_confirm=False, yen=5.0)), True)
        self.assertEqual(self.dialog_entries("askyesno"), [])

    def test_called_from_inside_an_event_callback_it_does_not_hang_either(self):
        """(M2) ボタンの処理 (Tk のコールバック) の中、つまり実機で押されたときと同じ状況でも固まらない。"""
        gui = self.make_gui()
        box = {}
        gui.root.after(0, lambda: box.update(value=self.call_from_main_thread(self.estimate_dict())))
        self.assertTrue(self.pump(lambda: "value" in box, timeout=6), "コールバック内から呼んだ確認が戻らない")
        self.assertIs(box["value"], True)

    # ---- root が消えたら、待っている側は False で戻る (永久に固まらない) --------------------------------
    def vanished_root_confirm(self, make_exists):
        """ワーカーから見て (1) ダイアログが出ない (after で予約した ask が実行されない) まま、(2) root が消えた状況を作る。
        待つ側の done.wait(1.0) の繰り返しの中で root の存在を確かめるはずなので、ワーカースレッドからの
        winfo_exists() だけを差し替える (メインスレッドの Tk の操作 = テストの待機は本物のまま)。"""
        gui = self.make_gui()
        real_after, real_exists = gui.root.after, gui.root.winfo_exists

        def fake_after(ms, func=None, *args):
            if threading.current_thread() is not threading.main_thread():
                return "after#swallowed"                         # メインスレッドで ask を動かさない = ダイアログが終わらない
            return real_after(ms, func, *args)

        def fake_exists():
            if threading.current_thread() is not threading.main_thread():
                return make_exists()
            return real_exists()
        gui.root.after, gui.root.winfo_exists = fake_after, fake_exists
        t0 = time.monotonic()
        try:
            result = self.confirm(self.estimate_dict(), timeout=8)
        finally:
            del gui.root.after, gui.root.winfo_exists
        return result, time.monotonic() - t0

    def test_a_vanished_root_makes_the_waiting_caller_return_false(self):
        """(M2) 待っている間に root が消えた (winfo_exists() が偽) ら、固まらずに False で戻る。"""
        result, elapsed = self.vanished_root_confirm(lambda: 0)
        self.assertIs(result, False)
        self.assertLess(elapsed, 5.0, "root が消えたのに待ち続けた")
        self.assertEqual(self.dialog_entries("askyesno"), [], "ダイアログは出ていないはず")

    def test_a_root_whose_existence_check_raises_makes_the_waiting_caller_return_false(self):
        """(M2) 待っている間に winfo_exists() が例外 (TclError など) を出しても、固まらずに False で戻る。"""
        def raising():
            raise tk.TclError("application has been destroyed")
        result, elapsed = self.vanished_root_confirm(raising)
        self.assertIs(result, False)
        self.assertLess(elapsed, 5.0, "root の確認が例外でも待ち続けた")


# ============================================================
# 8. _run_action_dashboard
# ============================================================
class CommonFlowTests:
    """「📋 アクション一覧を生成」(open_browser=True) と「🔄 解析のみ更新」(open_browser=False) の、どちらから呼んでも
    同じはずの振る舞い。OPEN / START_TEXT / DONE_TEXT を持つ UpdateCase に混ぜて使う。"""
    OPEN = None
    START_TEXT = ""
    DONE_TEXT = ""

    def go(self, **kw):
        return self.flow(self.OPEN, **kw)

    # ---- 開始 ------------------------------------------------------------
    def test_start_disables_both_buttons_with_their_busy_texts(self):
        """開始時に2つのボタンとも無効になり、文言が「⏳ 取得・解析中...」「⏳ 更新中...」になる。"""
        self.go()
        s = self.start_state
        self.assertEqual((s["run_state"], s["run_text"]), ("disabled", RUN_BUSY_TEXT))
        self.assertEqual((s["update_state"], s["update_text"]), ("disabled", UPDATE_BUSY_TEXT))

    def test_start_status_text_and_timer(self):
        """開始時のステータス文言が押したボタンに合ったものになり、経過時間のタイマーが動く。"""
        self.go()
        self.assertIn(self.START_TEXT, self.start_state["status"])
        self.assertIs(self.start_running, True, "開始時は start_timer=True (経過秒数を表示する)")

    def test_both_buttons_stay_disabled_while_the_analysis_is_running(self):
        """解析の最中も、2つのボタンは無効のまま。"""
        self.go(during=lambda gui: None)
        s = self.mid_state
        self.assertEqual((s["run_state"], s["run_text"]), ("disabled", RUN_BUSY_TEXT))
        self.assertEqual((s["update_state"], s["update_text"]), ("disabled", UPDATE_BUSY_TEXT))
        self.assertIn(self.START_TEXT, s["status"])

    def test_token_totals_are_reset_to_zero_at_the_start(self):
        """(A2) 開始時にトークン累計を0に戻す。"""
        # A2: 開始時に累計を 0 に戻す (前回までの累計が残っていても、今回の実行分だけにするため)
        self.go(initial_totals=(777_000, 555_000), during=lambda gui: None)
        self.assertEqual(self.mid_totals, (0, 0))

    # ---- 成功 ------------------------------------------------------------
    def test_success_restores_both_buttons(self):
        """成功したら、2つのボタンを有効・元の文言に戻す。"""
        self.go()
        s = self.final_state
        self.assertEqual((s["run_state"], s["run_text"]), ("normal", RUN_TEXT))
        self.assertEqual((s["update_state"], s["update_text"]), ("normal", UPDATE_TEXT))

    def test_success_status_names_the_finished_action(self):
        """成功時のステータスが、押したボタンに合った完了文言になる。"""
        self.go()
        self.assertIn(self.DONE_TEXT, self.final_state["status"])

    def test_success_status_says_no_new_analysis_was_needed_when_nothing_was_analyzed(self):
        """解析0件なら「（新しい解析は不要でした）」を続ける。"""
        self.go()
        self.assertIn("（新しい解析は不要でした）", self.final_state["status"])
        self.assertNotIn("今回のAI費用", self.final_state["status"])

    def test_success_status_shows_this_runs_cost_and_calls_when_analyzed(self):
        """解析したら「（今回のAI費用 約N円・M件）」を続ける。"""
        # 3件解析・今回のトークン 入力100万/出力10万 → 88.0円
        self.go(threads=body_threads(3), add_in=1_000_000, add_out=100_000)
        self.assertIn("（今回のAI費用 約88.0円・3件）", self.final_state["status"])
        self.assertNotIn("新しい解析は不要でした", self.final_state["status"])

    def test_cost_in_the_status_uses_one_decimal_and_the_actual_tokens(self):
        """ステータスの費用は小数1桁で、実際のトークンから計算する。"""
        self.go(threads=body_threads(2), add_in=123_456, add_out=7_890)
        spent = oto().calc_api_cost_yen(123_456, 7_890)
        self.assertIn(f"（今回のAI費用 約{spent:.1f}円・2件）", self.final_state["status"])

    def test_success_stops_the_status_timer(self):
        """成功時にステータスのタイマーを止める。"""
        gui = self.go()
        self.assertIs(gui.is_running, False)

    def test_refresh_is_called_once_after_success(self):
        """成功時に判断待ちの再計算 (再読込) を1回呼ぶ。"""
        self.go()
        self.assertEqual(len(self.refreshes), 1)

    def test_refresh_comes_after_the_buttons_and_status_are_final(self):
        """再読込は、ボタンとステータスが最終状態になった後に呼ぶ。"""
        self.go()
        s = self.refreshes[0]
        self.assertEqual((s["run_state"], s["run_text"], s["update_state"], s["update_text"]),
                         ("normal", RUN_TEXT, "normal", UPDATE_TEXT))
        self.assertIn(self.DONE_TEXT, s["status"])

    def test_summarize_is_called_once_even_when_nothing_needs_analysis(self):
        """解析0件でも summarize_action_dashboard を1回呼ぶ (キャッシュから表示用データを作るため)。"""
        # n_calls==0 でも summarize_action_dashboard は呼ぶ (キャッシュから表示用データを作るため)
        gui = self.go()
        self.assertEqual(len(gui.summarizer.calls), 1)
        self.assertIs(gui.summarizer.calls[0]["expand"], True)
        self.assertEqual(gui.summarizer.calls[0]["reset"], set())

    def test_summarize_receives_the_grouped_threads(self):
        """summarize には group_by_thread の結果を渡す。"""
        threads = body_threads(2)
        gui = self.go(threads=threads)
        self.assertIs(gui.summarizer.calls[0]["threads"], threads)

    def test_group_by_thread_receives_the_fetched_mails(self):
        """group_by_thread には取得したメールを渡す。"""
        self.go()
        self.assertEqual(self.group_args, [self.fetched])

    def test_last_run_is_saved_with_the_range_and_the_label_at_the_start(self):
        """最終解析の記録 (範囲・開始時の期間ラベル) を保存する。実行中に期間を変えても開始時のもの。"""
        # 解析の最中に期間の選択を変えても、保存するのは開始時の期間 (A1 の既存動作)
        self.go(period="3日間", during=lambda gui: gui.v_action_prd.set("1ヶ月"))
        d = read_json(LAST_RUN_PATH)
        self.assertEqual(d["days"], 3)
        self.assertEqual(d["period_label"], "3日間")

    def test_last_run_is_saved_exactly_once_after_success(self):
        """最終解析の記録は成功時に1回だけ保存する。"""
        self.go()
        self.assertEqual(len(self.method_calls["last_run"]), 1)

    def test_a_failing_last_run_save_does_not_stop_the_run(self):
        """最終解析の記録の保存に失敗しても、本処理は続く (A1の既存動作)。"""
        # A1 の既存動作: save_action_last_run が失敗しても、本処理 (結果の保存など) は継続する
        with mock.patch.object(oto(), "save_action_last_run", side_effect=OSError("書き込み不可")):
            self.go(cards=[{"thread_id": "T1", "actions": []}], report_path="/tmp/r.html")
        self.assertEqual(self.dialog_entries("showerror"), [])
        self.assertIn(self.DONE_TEXT, self.final_state["status"])
        self.assertEqual(len(self.method_calls["save_result"]), 1)

    # ---- 費用の事前見積り ----------------------------------------------------
    def test_estimate_is_called_with_the_grouped_threads_the_cache_and_the_config_model(self):
        """見積りは、グループ化したスレッド・キャッシュの内容・設定のモデルで行う。"""
        cache = cache_of(CONV000=cache_entry(1))
        threads = body_threads(2)
        self.go(threads=threads, cache=cache)
        args = self.estimate_arguments()
        self.assertIs(args["threads"], threads)
        self.assertEqual(args["cache_data"], cache)
        self.assertEqual(args["model"], FLASH)

    def test_estimate_gets_the_default_empty_cache_when_there_is_no_cache_file(self):
        """キャッシュファイルが無ければ、空のキャッシュ (threads={}) で見積もる。"""
        self.go(threads=body_threads(1))
        self.assertEqual(self.estimate_arguments()["cache_data"], {"threads": {}})

    def test_estimate_follows_the_configured_model(self):
        """見積りは設定の gemini_model で行う。"""
        self.go(threads=body_threads(3), model=PRO)
        self.assertEqual(self.estimate_arguments()["model"], PRO)

    def test_estimate_is_printed_when_something_needs_analysis(self):
        """解析が必要なら、費用の見込みを print する。"""
        self.go(threads=body_threads(3))
        self.assertIn(ESTIMATE_PRINT_HEAD, self.printed.getvalue())

    def test_estimate_is_not_printed_when_nothing_needs_analysis(self):
        """解析0件なら、見込みは print しない。"""
        self.go()
        self.assertNotIn(ESTIMATE_PRINT_HEAD, self.printed.getvalue())

    def test_confirm_is_called_with_the_estimate_and_the_label(self):
        """確認 (_confirm_ai_cost) を、見積りとラベル「アクション解析」で呼ぶ。"""
        self.go(threads=body_threads(3))
        calls = self.method_calls["confirm"]
        self.assertEqual(len(calls), 1)
        args, kwargs = calls[0]
        bound = inspect.signature(oto().MailManagerGUI._confirm_ai_cost).bind(None, *args, **kwargs).arguments
        self.assertEqual(bound["label"], ACTION_LABEL)
        self.assertEqual(bound["estimate"]["n_calls"], 3)
        self.assertEqual(bound["estimate"]["input_chars"], 3 * (len("本文です") + 40 + 1800))

    def test_nothing_to_analyze_shows_no_dialog_and_still_continues(self):
        """全てキャッシュ済み (0件) なら確認ダイアログを出さず、そのまま続ける。"""
        gui = self.go(threads=body_threads(2), cache=cache_of(CONV000=cache_entry(1), CONV001=cache_entry(1)))
        self.assertEqual(self.dialog_entries("askyesno"), [])
        self.assertEqual(len(gui.summarizer.calls), 1)

    # ---- 確認ダイアログ (閾値付近) ------------------------------------------------
    def test_just_under_the_threshold_shows_no_dialog_and_continues(self):
        """100円未満 (99.95円) の見込みは、確認なしで実行する。"""
        gui = self.go(threads=empty_threads(92))                  # 99.95円
        self.assertEqual(self.dialog_entries("askyesno"), [])
        self.assertEqual(len(gui.summarizer.calls), 1)

    def test_at_the_threshold_a_confirmation_dialog_is_shown(self):
        """100円以上 (101.04円) の見込みは、確認ダイアログを出す。"""
        self.go(threads=empty_threads(93))                        # 101.04円
        self.assertEqual(len(self.dialog_entries("askyesno")), 1)

    def test_dialog_has_the_title_and_the_text_without_a_track_record(self):
        """実績なしの確認ダイアログのタイトルと本文 (約101円・93件・実績がまだ無いため多めに)。"""
        self.go(threads=empty_threads(93))
        title, message = self.title_and_message(self.dialog_entries("askyesno")[0])
        self.assertEqual(title, CONFIRM_TITLE)
        self.assertEqual(message, self.expected_dialog_text(ACTION_LABEL, 101.04, 93, calibrated=False))

    def test_dialog_text_with_a_track_record(self):
        """実績ありの確認ダイアログの本文 (約120円・2件・直近の実績から)。"""
        self.go(threads=empty_threads(2), log=[rec("action", 1, 100000)])      # 実績 → 見込み 120.17円・2件
        _, message = self.title_and_message(self.dialog_entries("askyesno")[0])
        self.assertEqual(message, self.expected_dialog_text(ACTION_LABEL, 120.17, 2, calibrated=True))

    def test_dialog_is_shown_from_the_main_thread(self):
        """確認ダイアログはメインスレッドで出す。"""
        self.go(threads=empty_threads(93))
        self.assertEqual([t for t in self.dialog_threads if t[0] == "askyesno"], [("askyesno", True)])

    def test_confirming_runs_the_analysis_and_finishes_normally(self):
        """「はい」なら解析し、実績ログ・最終解析の記録を残して正常終了する。"""
        gui = self.go(threads=empty_threads(93), ask=True, add_in=1000, add_out=100)
        self.assertEqual(len(gui.summarizer.calls), 1)
        self.assertEqual(len(self.log_records()), 1)
        self.assertTrue(os.path.exists(LAST_RUN_PATH))
        self.assertIn(self.DONE_TEXT, self.final_state["status"])

    # ---- 中止 (確認で「いいえ」) ---------------------------------------------------
    PREVIOUS_RUN = make_last_run(datetime(2026, 10, 3, 9, 0, 0), 14, "2週間")        # 中止の前から記録されている最終解析

    def cancelled(self, **kw):
        """93件 (101.04円) で確認ダイアログが出て、「いいえ」を押した実行 (前回の最終解析の記録がある状態から)。"""
        kw.setdefault("last_run", self.PREVIOUS_RUN)
        return self.go(threads=empty_threads(93), ask=False, **kw)

    def test_cancel_does_not_run_the_analysis(self):
        """「いいえ」なら、解析 (summarize_action_dashboard) を呼ばない。"""
        gui = self.cancelled()
        self.assertEqual(gui.summarizer.calls, [])
        self.assertNotIn("summarize", self.events)

    def test_cancel_does_not_save_the_last_run(self):
        """「いいえ」なら、最終解析の記録を保存しない (前回の記録のまま)。"""
        self.cancelled()
        self.assertEqual(self.method_calls["last_run"], [], "中止なのに save_action_last_run を呼んだ")
        self.assertEqual(read_json(LAST_RUN_PATH), self.PREVIOUS_RUN,
                         "中止なのに最終解析の記録が上書きされた (鮮度が偽になる)")

    def test_cancel_writes_no_usage_log(self):
        """「いいえ」なら、実績ログを書かない。"""
        self.cancelled()
        self.assertEqual(self.method_calls["record"], [], "中止なのに record_ai_usage を呼んだ")
        self.assertFalse(os.path.exists(LOG_PATH), "中止なのに実績ログを書いた")

    def test_cancel_keeps_the_existing_usage_log_as_it_was(self):
        """「いいえ」でも、既存の実績ログは変わらない。"""
        self.cancelled(log=[rec("action", 2, 4000)])
        self.assertEqual(self.log_records(), [rec("action", 2, 4000)])

    def test_cancel_generates_no_html_and_opens_no_browser(self):
        """「いいえ」なら、HTMLもブラウザも出さない。"""
        gui = self.cancelled(report_path="/tmp/should-not-open.html")
        self.assertEqual(gui.reporter.calls, [])
        self.assertEqual(self.browser_calls, [])

    def test_cancel_status_is_the_cancelled_message(self):
        """「いいえ」の終了ステータスは「⏹ 費用の確認で中止しました（AI解析は行っていません）」。"""
        self.cancelled()
        self.assertEqual(self.final_state["status"], CANCELLED_STATUS)

    def test_cancel_restores_both_buttons(self):
        """「いいえ」でも2つのボタンを元に戻す。"""
        self.cancelled()
        s = self.final_state
        self.assertEqual((s["run_state"], s["run_text"]), ("normal", RUN_TEXT))
        self.assertEqual((s["update_state"], s["update_text"]), ("normal", UPDATE_TEXT))

    def test_cancel_stops_the_status_timer(self):
        """「いいえ」でもステータスのタイマーを止める。"""
        gui = self.cancelled()
        self.assertIs(gui.is_running, False)

    def test_cancel_still_refreshes_the_decision_view(self):
        """「いいえ」でも判断待ちの再読込を呼ぶ。"""
        self.cancelled()
        self.assertEqual(len(self.refreshes), 1)

    def test_cancel_refresh_comes_after_the_buttons_and_status_are_final(self):
        """「いいえ」の再読込も、ボタンとステータスが最終状態になった後。"""
        self.cancelled()
        s = self.refreshes[0]
        self.assertEqual((s["run_state"], s["update_state"], s["status"]), ("normal", "normal", CANCELLED_STATUS))

    def test_cancel_after_the_estimate_was_printed(self):
        """中止する場合でも、見込みは print 済み。"""
        self.cancelled()
        self.assertIn(ESTIMATE_PRINT_HEAD, self.printed.getvalue())

    def test_cancel_leaves_the_token_totals_unchanged(self):
        """中止すると、トークン累計は実行前の値のまま (A7c fix1: 0へ戻すのは費用の確認の後・AIの直前。
        確認で中止しただけで、他の画面で実行中のAIの集計を0にしない)。"""
        gui = self.cancelled(initial_totals=(777_000, 555_000))
        self.assertEqual((gui.summarizer.total_input_tokens, gui.summarizer.total_output_tokens), (777_000, 555_000))

    # ---- 実績ログ ---------------------------------------------------------------
    def test_success_appends_one_usage_line_for_the_run(self):
        """解析した実行は、実績ログに1行 (feature=action・回数・トークン・モデル) 追記する。"""
        self.go(threads=body_threads(3), add_in=1_000_000, add_out=100_000)
        recs = self.log_records()
        self.assertEqual(len(recs), 1)
        d = recs[0]
        self.assertEqual((d["feature"], d["n_calls"], d["input_tokens"], d["output_tokens"], d["model"]),
                         ("action", 3, 1_000_000, 100_000, FLASH))

    def test_usage_line_has_this_runs_cost_not_the_estimate(self):
        """実績ログの円は、見込みではなく今回の実際のトークンから計算した値。"""
        self.go(threads=body_threads(3), add_in=1_000_000, add_out=100_000)
        self.assertAlmostEqual(self.log_records()[0]["yen"], 88.0, places=2)     # 見込み (約3円) ではなく実際の費用

    def test_usage_line_is_a_complete_record(self):
        """実績ログの行は仕様の7つのキーを持ち、at の形式が正しい。"""
        self.go(threads=body_threads(3), add_in=10, add_out=5)
        d = self.log_records()[0]
        self.assertEqual(sorted(d), sorted(LOG_KEYS))
        self.assertRegex(d["at"], AT_RE)

    def test_usage_tokens_are_this_runs_only_not_the_accumulated_totals(self):
        """実績ログのトークンは今回分だけ (前回までの累計を含まない)。"""
        self.go(threads=body_threads(2), add_in=100, add_out=50, initial_totals=(777_000, 555_000))
        d = self.log_records()[0]
        self.assertEqual((d["input_tokens"], d["output_tokens"]), (100, 50))

    def test_usage_line_follows_the_configured_model(self):
        """実績ログのモデルと円は、設定のモデルに従う。"""
        self.go(threads=body_threads(3), add_in=1_000_000, add_out=100_000, model=PRO)
        d = self.log_records()[0]
        self.assertEqual(d["model"], PRO)
        self.assertAlmostEqual(d["yen"], yen_pro(1_000_000, 100_000), places=2)

    def test_usage_is_appended_after_existing_lines(self):
        """実績ログは既存の行の後ろに追記する。"""
        self.go(threads=body_threads(1), add_in=10, add_out=5, log=[rec("action", 2, 4000), rec("review", 1, 9)])
        recs = self.log_records()
        self.assertEqual([r["feature"] for r in recs], ["action", "review", "action"])
        self.assertEqual(recs[0], rec("action", 2, 4000))

    def test_usage_is_written_once_per_run(self):
        """実績ログへの記録は1実行につき1回。"""
        self.go(threads=body_threads(3), add_in=1, add_out=1)
        self.assertEqual(len(self.method_calls["record"]), 1)

    def test_nothing_analyzed_writes_no_usage_log(self):
        """解析0件なら、record_ai_usage を呼ばず実績ログを作らない。"""
        self.go()
        self.assertEqual(self.method_calls["record"], [], "解析が0件なのに record_ai_usage を呼んだ")
        self.assertFalse(os.path.exists(LOG_PATH))

    def test_everything_cached_writes_no_usage_log(self):
        """全てキャッシュ済みなら、実績ログを作らない。"""
        self.go(threads=body_threads(2), cache=cache_of(CONV000=cache_entry(1), CONV001=cache_entry(1)))
        self.assertFalse(os.path.exists(LOG_PATH))

    def test_a_corrupt_usage_log_does_not_stop_the_run(self):
        """実績ログが壊れていても (UTF-8で読めない)、本処理は止まらない。"""
        # 実績ログは見積りの校正に使う補助情報。読めないとき (仕様: 読めない → None → 既定値で見積もる) でも、本処理は止まらない。
        # Windows のメモ帳で ANSI (cp932) 保存された等で UTF-8 として読めないログを置く
        gui = self.go(threads=body_threads(2), log_bytes="壊れたログ\n".encode("cp932"))
        self.assertEqual(self.dialog_entries("showerror"), [], "壊れた実績ログのせいで失敗した")
        self.assertEqual(len(gui.summarizer.calls), 1)
        self.assertIn(self.DONE_TEXT, self.final_state["status"])

    def test_the_next_estimate_is_calibrated_by_this_runs_usage(self):
        """今回の実績が、次回の見積りの校正に使われる。"""
        # 2件解析・出力 6000 トークン → 実績 3000/回 → 次の見積りは 4500/回 (校正あり)
        self.go(threads=body_threads(2), add_in=100, add_out=6000)
        est = estimate(empty_threads(1), None)
        self.assertAlmostEqual(est["output_tokens_per_call"], 4500.0)
        self.assertIs(est["calibrated"], True)

    # ---- 解析の一部/全部が失敗した実行 (B1: 実績ログに失敗した呼び出しを記録しない / M1: 完了表示) -----------------
    WARN_TEXT = ""                    # 解析に失敗したスレッドがあるときの完了表示 ({n} = 失敗数)。サブクラスで指定

    def all_failed(self, **kw):
        """実際の MailSummarizer + 接続失敗のクライアントで、6件すべての解析が失敗した実行。"""
        self.models = ScriptedModels(fail_all=True)
        return self.go(threads=real_threads(6), real_models=self.models, **kw)

    def partly_failed(self, **kw):
        """6件のうち CONV001 と CONV003 の2件が接続失敗、残り4件は成功 (各: 入力2000・出力500トークン) した実行。"""
        self.models = ScriptedModels(fail_cids=("CONV001", "CONV003"))
        return self.go(threads=real_threads(6), real_models=self.models, **kw)

    def test_all_failed_run_really_failed_in_the_cache(self):
        """(前提の確認) 差し替えのクライアントが全件失敗し、実際のキャッシュに6件とも data._error が付く。"""
        self.all_failed()
        self.assertEqual(oto().count_failed_action_threads(real_threads(6), oto().load_action_dashboard_cache()), 6)
        self.assertEqual(len(self.models.calls), 6)

    def test_all_failed_run_writes_no_usage_line(self):
        """(B1) 全件失敗の実行は、実績ログに書かない (失敗は出力0で、見積りの平均を薄めるため)。"""
        self.all_failed()
        self.assertEqual(self.method_calls["record"], [], "全件失敗なのに record_ai_usage を呼んだ")
        self.assertFalse(os.path.exists(LOG_PATH), "全件失敗なのに実績ログを書いた")

    def test_all_failed_run_shows_the_warning_instead_of_the_success_text(self):
        """(M1) 全件失敗の実行は、成功の表示 (✅) ではなく「⚠ …は完了（解析に失敗したスレッドが6件。…）」を出す。"""
        self.all_failed()
        status = self.final_state["status"]
        self.assertTrue(status.startswith(self.WARN_TEXT.format(n=6)), status)
        self.assertNotIn("✅", status)

    def test_all_failed_run_shows_a_cost_of_zero_yen(self):
        """(M1) 全件失敗の実行の費用表示は 0円台 (トークンを使っていない: 約0.0円)。"""
        self.all_failed()
        self.assertIn("（今回のAI費用 約0.0円・", self.final_state["status"])

    def test_all_failed_run_does_not_pretend_to_be_up_to_date_with_a_success_status(self):
        """(M1) 全件失敗の実行では、「解析のみ更新 完了」「アクションダッシュボード生成完了」の成功文言を出さない。"""
        self.all_failed()
        status = self.final_state["status"]
        self.assertNotIn(self.DONE_TEXT, status)

    def test_all_failed_run_shows_no_error_dialog_and_restores_the_ui(self):
        """全件失敗でも、処理自体は例外なく終わる: エラーダイアログは出さず、ボタンを戻し、再読込する。"""
        self.all_failed()
        self.assertEqual(self.dialog_entries("showerror"), [])
        s = self.final_state
        self.assertEqual((s["run_state"], s["run_text"], s["update_state"], s["update_text"]),
                         ("normal", RUN_TEXT, "normal", UPDATE_TEXT))
        self.assertEqual(len(self.refreshes), 1)

    def test_all_failed_run_keeps_the_usage_log_and_the_next_estimate_as_they_were(self):
        """(B1) 全件失敗の実行の前後で、実績ログも次の見積り (1回あたりの出力・円) も変わらない (薄まらない)。"""
        seeded = [rec("action", 2, 6000)]
        before_text = json.dumps(seeded[0], ensure_ascii=False) + "\n"
        write_log(*seeded)
        before = estimate(empty_threads(93), None)
        self.all_failed(log=seeded)
        self.assertEqual(read_log_text(), before_text, "全件失敗の実行が実績ログを書き換えた")
        after = estimate(empty_threads(93), None)
        self.assertEqual(after["output_tokens_per_call"], before["output_tokens_per_call"])
        self.assertGreaterEqual(after["yen"], before["yen"], "全件失敗の実行の後で、同じスレッド数の見積りが下がった")
        self.assertEqual(after["needs_confirm"], before["needs_confirm"])

    def test_after_an_all_failed_run_a_large_run_still_needs_confirmation(self):
        """(B1) 全件失敗の実行の後でも、大きな実行 (93件) は引き続き 100円以上と見積もられて確認になる (薄まらない)。"""
        self.all_failed(log=[rec("action", 2, 6000)])
        after = estimate(empty_threads(93), None)
        self.assertAlmostEqual(after["output_tokens_per_call"], 4500.0)
        self.assertIs(after["needs_confirm"], True)

    def test_partial_failure_logs_only_the_successful_calls(self):
        """(B1) 一部失敗の実行は、成功した件数 (6件中4件) だけを n_calls として記録する。トークンは今回の実績。"""
        self.partly_failed()
        recs = self.log_records()
        self.assertEqual(len(recs), 1)
        d = recs[0]
        self.assertEqual((d["feature"], d["n_calls"], d["input_tokens"], d["output_tokens"], d["model"]),
                         ("action", 4, 8000, 2000, FLASH))
        self.assertAlmostEqual(d["yen"], oto().calc_api_cost_yen(8000, 2000), places=2)

    def test_partial_failure_logs_the_successes_not_the_estimated_count(self):
        """(B1) 記録する n_calls は、見積り件数 (6) ではなく成功した件数 (4)。"""
        self.partly_failed()
        self.assertNotEqual(self.log_records()[0]["n_calls"], 6)

    def test_partial_failure_shows_the_warning_with_the_failed_count(self):
        """(M1) 一部失敗の実行は「⚠ …は完了（解析に失敗したスレッドが2件。…）」に、費用の文言が続く。"""
        self.partly_failed()
        status = self.final_state["status"]
        self.assertTrue(status.startswith(self.WARN_TEXT.format(n=2)), status)
        self.assertIn("（今回のAI費用 約", status)
        self.assertNotIn("✅", status)

    def test_partial_failure_cost_is_that_of_the_successful_calls(self):
        """(M1) 一部失敗の実行の費用は、実際に使ったトークン (入力8000・出力2000) から計算した値。"""
        self.partly_failed()
        spent = oto().calc_api_cost_yen(8000, 2000)
        self.assertIn(f"（今回のAI費用 約{spent:.1f}円・", self.final_state["status"])

    def test_partial_failure_keeps_the_observed_output_per_successful_call(self):
        """(B1) 一部失敗の後の実績は、成功した呼び出しだけで求まる: (6000+2000)/(2+4)。失敗を回数に入れた 1000 にならない。"""
        self.partly_failed(log=[rec("action", 2, 6000)])
        self.assertAlmostEqual(oto().observed_output_tokens_per_call("action"), (6000 + 2000) / (2 + 4))

    def test_partial_failure_failed_threads_are_retried_next_time(self):
        """一部失敗の後、次回の見積りでは、失敗した2件だけが解析対象 (再試行) になる。"""
        self.partly_failed()
        est = estimate(real_threads(6), oto().load_action_dashboard_cache())
        self.assertEqual(est["n_calls"], 2)

    def test_partial_failure_ends_cleanly(self):
        """一部失敗でも、エラーダイアログは出さず、ボタンを戻し、再読込する。"""
        self.partly_failed()
        self.assertEqual(self.dialog_entries("showerror"), [])
        s = self.final_state
        self.assertEqual((s["run_state"], s["update_state"]), ("normal", "normal"))
        self.assertEqual(len(self.refreshes), 1)

    def test_a_run_without_failures_still_shows_the_success_text(self):
        """失敗が0件の実行 (実際のサマライザで全件成功) は、従来どおりの成功文言になる。"""
        self.models = ScriptedModels()
        self.go(threads=real_threads(3), real_models=self.models)
        self.assertTrue(self.final_state["status"].startswith(self.DONE_TEXT), self.final_state["status"])
        self.assertNotIn("⚠", self.final_state["status"])

    def test_all_succeeded_run_logs_every_call(self):
        """全件成功の実行 (実際のサマライザ) は、見積り件数どおり (3件・入力6000・出力1500) 記録する。"""
        self.models = ScriptedModels()
        self.go(threads=real_threads(3), real_models=self.models)
        d = self.log_records()[0]
        self.assertEqual((d["n_calls"], d["input_tokens"], d["output_tokens"]), (3, 6000, 1500))

    def test_no_usage_line_when_no_output_tokens_were_used(self):
        """(B1) 解析件数があっても、出力トークンが0なら実績ログに書かない (出力0の平均で見積りを薄めない)。"""
        self.go(threads=body_threads(3), add_in=1000, add_out=0)
        self.assertEqual(self.method_calls["record"], [])
        self.assertFalse(os.path.exists(LOG_PATH))

    def test_no_usage_line_when_every_thread_failed_even_if_output_tokens_were_counted(self):
        """(B1) 全スレッドが失敗 (data._error) なら、出力トークンが数えられていても書かない (成功した件数が0)。"""
        threads = body_threads(3)
        self.go(threads=threads, add_in=1000, add_out=500, fail_cids=tuple(threads))
        self.assertEqual(self.method_calls["record"], [])
        self.assertFalse(os.path.exists(LOG_PATH))

    def test_usage_counts_only_the_threads_that_did_not_fail_with_the_stub(self):
        """(B1) スタブでも: 3件のうち1件が data._error なら、記録する n_calls は2。"""
        self.go(threads=body_threads(3), add_in=1000, add_out=500, fail_cids=("CONV001",))
        self.assertEqual(self.log_records()[0]["n_calls"], 2)

    def test_unreadable_cache_after_the_analysis_writes_no_usage_line(self):
        """(b) 解析後のキャッシュが読めない (None) ときは、成否が分からないので実績ログに記録しない。"""
        self.go(threads=body_threads(3), add_in=1000, add_out=500, break_cache=True)
        self.assertEqual(self.method_calls["record"], [])
        self.assertFalse(os.path.exists(LOG_PATH))

    def test_unreadable_cache_after_the_analysis_shows_the_cannot_confirm_warning(self):
        """(b) その完了表示は「⚠ …は完了（解析後の結果を読めず、成否を確認できませんでした。…）」+ 費用の文言 (✅ にしない)。"""
        self.go(threads=body_threads(3), add_in=1000, add_out=500, break_cache=True)
        status = self.final_state["status"]
        self.assertTrue(status.startswith(self.UNKNOWN_TEXT), status)
        self.assertIn("（今回のAI費用 約", status)
        self.assertNotIn("✅", status)

    def test_unreadable_cache_after_the_analysis_still_ends_cleanly(self):
        """(b) 解析後のキャッシュが読めなくても、エラーダイアログは出さず、ボタンを戻して再読込する。"""
        self.go(threads=body_threads(3), add_in=1000, add_out=500, break_cache=True)
        self.assertEqual(self.dialog_entries("showerror"), [])
        self.assertEqual((self.final_state["run_state"], self.final_state["update_state"]), ("normal", "normal"))
        self.assertEqual(len(self.refreshes), 1)

    def test_failures_still_in_the_cache_after_the_analysis_are_counted(self):
        """解析のあとのキャッシュに data._error が残るスレッド (今回も失敗した) は、失敗として数える: 警告1件・記録は成功分の1件。"""
        threads = body_threads(2)
        stale = cache_of(CONV000=errored_entry("CONV000", mail_count=1))          # 失敗のまま (スタブは結果を書き換えない)
        self.go(threads=threads, cache=stale, add_in=1000, add_out=500)
        self.assertTrue(self.final_state["status"].startswith(self.WARN_TEXT.format(n=1)), self.final_state["status"])
        self.assertEqual(self.log_records()[0]["n_calls"], 1)                     # 見積り2件 - 失敗1件

    # ---- 失敗 ------------------------------------------------------------
    FAIL_MSG = "AI解析で失敗しましたQQQ"
    FAIL_SHOWN = "RuntimeError: AI解析で失敗しましたQQQ"            # 仕様(m5): 失敗の表示は「型名: 例外の文字列」

    def failed(self, **kw):
        kw.setdefault("fail", RuntimeError(self.FAIL_MSG))
        return self.go(**kw)

    def test_failure_shows_the_error_dialog_once(self):
        """失敗したら、エラーダイアログ (showerror) を1回だけ出す。"""
        self.failed()
        self.assertEqual(len(self.dialog_entries("showerror")), 1)

    def test_failure_dialog_has_the_title_and_the_exception_text(self):
        """エラーダイアログのタイトルは「エラー」、本文は「型名: 例外の文字列」。"""
        self.failed()
        title, message = self.title_and_message(self.dialog_entries("showerror")[0])
        self.assertEqual(title, "エラー")
        self.assertEqual(message, self.FAIL_SHOWN)

    def test_failure_dialog_is_shown_from_the_main_thread(self):
        """エラーダイアログはメインスレッドで出す。"""
        self.failed()
        self.assertEqual([t for t in self.dialog_threads if t[0] == "showerror"], [("showerror", True)])

    def test_failure_status_shows_the_head_of_the_message(self):
        """失敗のステータスは「❌ 失敗しました: 型名: <例外文>」。"""
        self.failed()
        self.assertEqual(self.final_state["status"], "❌ 失敗しました: " + self.FAIL_SHOWN)

    def test_failure_status_keeps_only_the_first_80_characters(self):
        """失敗のステータスは、「型名: 例外文」の先頭80文字だけ (型名も80文字に含む)。"""
        msg = "あ" * 80 + "い" * 40
        self.failed(fail=RuntimeError(msg))
        shown = "RuntimeError: " + msg
        self.assertEqual(self.final_state["status"], "❌ 失敗しました: " + shown[:80])
        self.assertNotIn("い", self.final_state["status"])

    def test_failure_status_with_exactly_80_characters_is_not_cut(self):
        """「型名: 例外文」がちょうど80文字なら切らない (81文字なら最後の1文字を切る)。"""
        msg = "う" * (80 - len("RuntimeError: "))
        self.failed(fail=RuntimeError(msg))
        self.assertEqual(self.final_state["status"], "❌ 失敗しました: RuntimeError: " + msg)

    def test_failure_status_cuts_the_81st_character(self):
        """「型名: 例外文」が81文字なら、81文字目だけを切る。"""
        msg = "う" * (80 - len("RuntimeError: ")) + "え"
        self.failed(fail=RuntimeError(msg))
        self.assertEqual(self.final_state["status"], "❌ 失敗しました: RuntimeError: " + msg[:-1])

    def test_failure_dialog_shows_the_whole_message_even_when_long(self):
        """エラーダイアログには、長くても「型名: 例外文」の全文を出す (80文字で切らない)。"""
        msg = "あ" * 80 + "い" * 40
        self.failed(fail=RuntimeError(msg))
        self.assertEqual(self.title_and_message(self.dialog_entries("showerror")[0])[1], "RuntimeError: " + msg)

    def test_failure_message_names_the_actual_exception_type(self):
        """型名は実際の例外クラスの名前 (OSError など)。"""
        self.failed(fail=OSError("書き込めません"))
        self.assertEqual(self.title_and_message(self.dialog_entries("showerror")[0])[1], "OSError: 書き込めません")

    def test_failure_message_with_a_custom_exception_and_an_empty_message(self):
        """自作の例外クラスでも型名が付き、メッセージが空なら「型名: 」になる。"""
        class SummarizerBrokeError(Exception):
            pass
        self.failed(fail=SummarizerBrokeError())
        self.assertEqual(self.title_and_message(self.dialog_entries("showerror")[0])[1], "SummarizerBrokeError: ")
        self.assertEqual(self.final_state["status"], "❌ 失敗しました: SummarizerBrokeError: ")

    def test_failure_status_does_not_claim_success(self):
        """失敗のステータスに「完了」「✅」を出さない。"""
        self.failed()
        self.assertNotIn("✅", self.final_state["status"])
        self.assertNotIn("完了", self.final_state["status"])

    def test_failure_restores_both_buttons(self):
        """失敗しても2つのボタンを元に戻す。"""
        self.failed()
        s = self.final_state
        self.assertEqual((s["run_state"], s["run_text"]), ("normal", RUN_TEXT))
        self.assertEqual((s["update_state"], s["update_text"]), ("normal", UPDATE_TEXT))

    def test_failure_stops_the_status_timer(self):
        """失敗してもステータスのタイマーを止める。"""
        gui = self.failed()
        self.assertIs(gui.is_running, False)

    def test_failure_still_refreshes_the_decision_view(self):
        """失敗しても判断待ちの再読込を呼ぶ。"""
        self.failed()
        self.assertEqual(len(self.refreshes), 1)

    def test_failure_refresh_comes_after_the_buttons_and_status_are_final(self):
        """失敗の再読込も、ボタンとステータスが最終状態になった後。"""
        self.failed()
        s = self.refreshes[0]
        self.assertEqual((s["run_state"], s["update_state"]), ("normal", "normal"))
        self.assertEqual(s["status"], "❌ 失敗しました: " + self.FAIL_SHOWN)

    def test_failure_does_not_save_the_last_run(self):
        """解析が失敗したら、最終解析の記録を保存しない (鮮度が偽になる)。"""
        self.failed()
        self.assertEqual(self.method_calls["last_run"], [])
        self.assertFalse(os.path.exists(LAST_RUN_PATH), "解析失敗なのに last_run を保存した (鮮度が偽になる)")

    def test_failure_does_not_generate_html_or_open_the_browser(self):
        """解析が失敗したら、HTMLもブラウザも出さない。"""
        gui = self.failed(report_path="/tmp/should-not-open.html")
        self.assertEqual(gui.reporter.calls, [])
        self.assertEqual(self.browser_calls, [])

    def test_failure_while_fetching_mails_is_reported_and_the_ui_recovers(self):
        """メール取得の失敗も、ダイアログ・ステータス・ボタン復帰・再読込が行われる。"""
        self.go(fetch_error=RuntimeError("Outlookから取得できませんFFF"))
        title, message = self.title_and_message(self.dialog_entries("showerror")[0])
        self.assertEqual((title, message), ("エラー", "RuntimeError: Outlookから取得できませんFFF"))
        self.assertEqual(self.final_state["status"], "❌ 失敗しました: RuntimeError: Outlookから取得できませんFFF")
        self.assertEqual((self.final_state["run_state"], self.final_state["update_state"]), ("normal", "normal"))
        self.assertEqual(len(self.refreshes), 1)
        self.assertNotIn("summarize", self.events)

    def test_failure_while_grouping_threads_is_reported_and_the_ui_recovers(self):
        """スレッド化の失敗も、同様に通知して復帰する。"""
        self.go(group_error=ValueError("グループ化に失敗GGG"))
        self.assertEqual(self.title_and_message(self.dialog_entries("showerror")[0])[1], "ValueError: グループ化に失敗GGG")
        self.assertEqual(self.final_state["status"], "❌ 失敗しました: ValueError: グループ化に失敗GGG")
        self.assertEqual((self.final_state["run_state"], self.final_state["update_state"]), ("normal", "normal"))
        self.assertEqual(len(self.refreshes), 1)

    def test_failure_before_the_confirmation_shows_no_confirmation(self):
        """確認の前に失敗したら、確認ダイアログは出さない。"""
        self.go(fetch_error=RuntimeError("取得失敗"), threads=empty_threads(93))
        self.assertEqual(self.dialog_entries("askyesno"), [])

    def test_success_shows_no_error_dialog(self):
        """成功したら、エラーダイアログを出さない。"""
        self.go(threads=body_threads(2))
        self.assertEqual(self.dialog_entries("showerror"), [])


class TestFlowUpdateOnly(CommonFlowTests, UpdateCase):
    """「🔄 解析のみ更新」= _run_action_dashboard(open_browser=False)。HTML もブラウザも使わず、判断待ちの鮮度だけ更新する。"""

    OPEN = False
    START_TEXT = "🔄 判断待ちの解析を更新中..."
    DONE_TEXT = "✅ 解析のみ更新 完了"
    WARN_TEXT = WARN_UPDATE
    UNKNOWN_TEXT = UNKNOWN_UPDATE

    def test_no_html_report_is_generated(self):
        """「🔄 解析のみ更新」では HTML (generate_action_dashboard_report) を作らない。"""
        gui = self.go(cards=[{"thread_id": "T1", "actions": []}])
        self.assertEqual(gui.reporter.calls, [])
        self.assertNotIn("report", self.events)

    def test_browser_is_not_opened_even_if_a_report_path_would_be_returned(self):
        """ブラウザ (webbrowser.open) を開かない。"""
        self.go(report_path="/tmp/should-not-open.html")
        self.assertEqual(self.browser_calls, [])

    def test_the_last_result_json_is_saved_so_the_html_can_be_made_later(self):
        """後で「🎨 フォーマットのみ再生成」できるよう、last_result の json を保存する。"""
        cards = [{"thread_id": "T1", "topic": "件名1", "actions": [{"action": "承認してください"}]}]
        self.go(cards=cards)
        self.assertEqual(len(self.method_calls["save_result"]), 1)
        saved = read_json(LAST_RESULT_PATH)
        self.assertEqual(saved["action_cards"], cards)
        self.assertEqual(saved["search_days"], 7)
        self.assertIn("1週間", saved["date_range"])

    def test_the_format_only_button_becomes_enabled(self):
        """「🎨 フォーマットのみ再生成」が有効になる。"""
        self.go()
        self.assertEqual(self.final_state["reformat_state"], "normal")

    def test_the_format_only_button_text_is_not_changed(self):
        """「🎨 フォーマットのみ再生成」の文言は変えない。"""
        gui = self.go()
        self.assertEqual(str(gui.btn_reformat_action.cget("text")), REFORMAT_TEXT)

    def test_call_order_without_html(self):
        """呼び出し順: 取得 → グループ化 → 見積り → 確認 → 解析 → 実績ログ → 最終解析の記録 → 結果の保存 → 再読込 (HTMLなし)。"""
        self.go(threads=empty_threads(93), add_in=1, add_out=1)
        order = [e for e in self.events if e in ("fetch", "group", "estimate", "confirm", "summarize", "record",
                                                 "last_run", "report", "save_result", "refresh")]
        self.assertEqual(order, ["fetch", "group", "estimate", "confirm", "summarize", "record", "last_run",
                                 "save_result", "refresh"])

    def test_the_run_button_text_is_not_used_for_the_status(self):
        """完了のステータスに「アクションダッシュボード生成完了」を使わない。"""
        self.go()
        self.assertNotIn("アクションダッシュボード生成完了", self.final_state["status"])


class TestFlowWithBrowser(CommonFlowTests, UpdateCase):
    """「📋 アクション一覧を生成」= _run_action_dashboard(open_browser=True)。従来どおり HTML を作ってブラウザで開く。"""

    OPEN = True
    START_TEXT = "🚀 アクションダッシュボードを生成中..."
    DONE_TEXT = "✅ アクションダッシュボード生成完了"
    WARN_TEXT = WARN_RUN
    UNKNOWN_TEXT = UNKNOWN_RUN

    def test_report_is_generated_once_with_the_period_days_and_this_runs_totals(self):
        """HTMLを1回作り、期間・日数・今回分のトークンを渡す (A2のリセットを含む)。"""
        cards = [{"thread_id": "T1", "actions": []}]
        gui = self.go(cards=cards, add_in=100, add_out=50, initial_totals=(777_000, 555_000), period="3日間")
        self.assertEqual(len(gui.reporter.calls), 1)
        call = gui.reporter.calls[0]
        self.assertEqual(call["action_cards"], cards)
        self.assertEqual(call["search_days"], 3)
        self.assertIn("3日間", call["date_range"])
        self.assertEqual((call["total_input"], call["total_output"]), (100, 50))
        self.assertIs(call["reformat_mode"], False)

    def test_browser_is_opened_with_the_report_path(self):
        """HTMLのパスをブラウザで開く。"""
        self.go(report_path="/tmp/report-ABC.html")
        self.assertEqual(self.browser_calls, ["/tmp/report-ABC.html"])

    def test_browser_is_not_opened_when_the_report_returns_no_path(self):
        """HTMLのパスが無ければブラウザを開かない。"""
        self.go(report_path=None)
        self.assertEqual(self.browser_calls, [])

    def test_the_last_result_json_is_saved(self):
        """last_result の json を保存する (カード・今回分のトークン)。"""
        cards = [{"thread_id": "T1", "actions": []}]
        self.go(cards=cards, add_in=100, add_out=50)
        saved = read_json(LAST_RESULT_PATH)
        self.assertEqual(saved["action_cards"], cards)
        self.assertEqual((saved["total_input"], saved["total_output"]), (100, 50))

    def test_the_format_only_button_becomes_enabled(self):
        """「🎨 フォーマットのみ再生成」が有効になる。"""
        self.go()
        self.assertEqual(self.final_state["reformat_state"], "normal")

    def test_calling_without_arguments_behaves_like_open_browser_true(self):
        """引数なしで呼ぶと open_browser=True と同じ (従来どおり)。"""
        gui = self.flow(None, report_path="/tmp/report-DEF.html")
        self.assertEqual(len(gui.reporter.calls), 1)
        self.assertEqual(self.browser_calls, ["/tmp/report-DEF.html"])
        self.assertIn("✅ アクションダッシュボード生成完了", self.final_state["status"])

    def test_call_order_with_html(self):
        """呼び出し順: … → 最終解析の記録 → HTML生成 → 結果の保存 → 再読込。"""
        self.go(threads=empty_threads(93), add_in=1, add_out=1, report_path="/tmp/r.html")
        order = [e for e in self.events if e in ("fetch", "group", "estimate", "confirm", "summarize", "record",
                                                 "last_run", "report", "save_result", "refresh")]
        self.assertEqual(order, ["fetch", "group", "estimate", "confirm", "summarize", "record", "last_run",
                                 "report", "save_result", "refresh"])

    def test_report_failure_still_keeps_last_run_and_usage_because_the_analysis_succeeded(self):
        """HTML生成が失敗しても、解析は成功済みなので最終解析の記録・実績ログは残る。"""
        self.go(threads=body_threads(2), add_in=100, add_out=50, report_fail=RuntimeError("HTML生成に失敗RRR"))
        self.assertTrue(os.path.exists(LAST_RUN_PATH), "解析は成功したのに last_run が保存されていない")
        self.assertEqual(len(self.log_records()), 1, "解析は成功したのに実績ログが無い (費用は使っている)")

    def test_report_failure_is_reported_and_the_ui_recovers(self):
        """HTML生成の失敗も、通知・ステータス・ボタン復帰・再読込が行われる。"""
        self.go(report_fail=RuntimeError("HTML生成に失敗RRR"))
        self.assertEqual(self.title_and_message(self.dialog_entries("showerror")[0]),
                         ("エラー", "RuntimeError: HTML生成に失敗RRR"))
        self.assertEqual(self.final_state["status"], "❌ 失敗しました: RuntimeError: HTML生成に失敗RRR")
        self.assertEqual((self.final_state["run_state"], self.final_state["update_state"]), ("normal", "normal"))
        self.assertEqual(len(self.refreshes), 1)


class TestSpecGapFlows(UpdateCase):
    """仕様が曖昧/未記載の点。自然な解釈で確認する。"""

    def test_update_only_status_is_exactly_the_done_text_followed_by_the_note(self):
        """「✅ 解析のみ更新 完了」に「（新しい解析は不要でした）」を区切りなしで続ける。"""
        # 仕様: 「✅ 解析のみ更新 完了」。続けて「（新しい解析は不要でした）」 → 区切りなしで連結すると解釈
        self.flow(False)
        self.assertEqual(self.final_state["status"], "✅ 解析のみ更新 完了（新しい解析は不要でした）")

    def test_update_only_status_with_cost_is_exactly_the_done_text_followed_by_the_cost(self):
        """「✅ 解析のみ更新 完了」に「（今回のAI費用 …）」を区切りなしで続ける。"""
        self.flow(False, threads=body_threads(3), add_in=1_000_000, add_out=100_000)
        self.assertEqual(self.final_state["status"], "✅ 解析のみ更新 完了（今回のAI費用 約88.0円・3件）")

    def test_run_status_is_exactly_the_done_text_followed_by_the_note(self):
        """「✅ アクションダッシュボード生成完了」に「（新しい解析は不要でした）」を続ける。"""
        self.flow(True)
        self.assertEqual(self.final_state["status"], "✅ アクションダッシュボード生成完了（新しい解析は不要でした）")

    def test_run_status_with_cost_is_exactly_the_done_text_followed_by_the_cost(self):
        """「✅ アクションダッシュボード生成完了」に「（今回のAI費用 …）」を続ける。"""
        self.flow(True, threads=body_threads(3), add_in=1_000_000, add_out=100_000)
        self.assertEqual(self.final_state["status"], "✅ アクションダッシュボード生成完了（今回のAI費用 約88.0円・3件）")

    def test_all_failed_status_ends_with_the_cost_text_using_the_estimated_call_count(self):
        """全件失敗の警告のあとに「（今回のAI費用 約0.0円・6件）」を続ける (件数は従来どおり見積りの解析件数と解釈する)。"""
        self.models = ScriptedModels(fail_all=True)
        self.flow(False, threads=real_threads(6), real_models=self.models)
        self.assertEqual(self.final_state["status"], WARN_UPDATE.format(n=6) + "（今回のAI費用 約0.0円・6件）")

    def test_a_failed_analysis_writes_no_usage_line(self):
        """解析が失敗したときは、実績ログを書かない (「解析後」に進まないため)。"""
        # 仕様の実績ログは「解析後」(summarize が成功してから)。解析が例外なら、そこへ進まない
        self.flow(False, threads=body_threads(3), fail=RuntimeError("AI解析で失敗しました"))
        self.assertEqual(self.method_calls["record"], [])
        self.assertFalse(os.path.exists(LOG_PATH))

    def test_cancel_does_not_save_the_last_result_for_reformatting(self):
        """中止では、フォーマット再生成用の結果も保存しない (「🎨 …」は無効のまま)。"""
        # 中止では解析結果が無いので、フォーマット再生成用の保存もしない (保存済みの前回結果を壊さない)
        self.flow(False, threads=empty_threads(93), ask=False)
        self.assertEqual(self.method_calls["save_result"], [])
        self.assertFalse(os.path.exists(LAST_RESULT_PATH))
        self.assertEqual(self.final_state["reformat_state"], "disabled")

    def test_failure_does_not_save_the_last_result_for_reformatting(self):
        """失敗でも、フォーマット再生成用の結果を保存しない。"""
        self.flow(False, fail=RuntimeError("AI解析で失敗しました"))
        self.assertEqual(self.method_calls["save_result"], [])
        self.assertEqual(self.final_state["reformat_state"], "disabled")

    def test_usage_is_recorded_before_the_last_run_is_saved(self):
        """実績ログは、最終解析の記録より前に書く (仕様の並び順)。"""
        # 仕様の並び: 解析後に実績ログ → save_action_last_run (→ 画面ごとの出力)
        self.flow(False, threads=body_threads(2), add_in=10, add_out=5)
        self.assertLess(self.events.index("record"), self.events.index("last_run"))

    def test_a_failing_confirmation_dialog_does_not_start_the_analysis(self):
        """確認ダイアログが失敗しても、確認なしで解析を始めない。"""
        # 確認の画面が出せなかったときに、確認なしで費用を使う方向へは進まない (中止または失敗として終わる)
        gui = self.flow(False, threads=empty_threads(93), ask=RuntimeError("テスト用のダイアログ例外"))
        self.callback_errors[:] = [e for e in self.callback_errors if "テスト用のダイアログ例外" not in e]
        self.assertEqual(gui.summarizer.calls, [])
        self.assertEqual(self.final_state["run_state"], "normal")
        self.assertEqual(self.final_state["update_state"], "normal")
        self.assertEqual(len(self.refreshes), 1)


# ============================================================
# 9. 範囲ガード (_03 → _04 で変えてよいのは許可リストだけ)
# ============================================================
OLD_REV = "outlook_total_organizer_20261004_03.py"
NEW_REV = "outlook_total_organizer_20261004_04.py"
ALLOWED_TO_CHANGE = {"MailManagerGUI._run_action_dashboard", "MailManagerGUI._ui_action_tab",
                     "build_action_decision_snapshot"}
NEW_CONSTANTS = ("ACTION_ESTIMATE_PROMPT_CHARS", "ACTION_ESTIMATE_OUTPUT_TOKENS", "ACTION_ESTIMATE_BODY_LIMIT",
                 "ACTION_ESTIMATE_THREAD_CHARS_MAX", "ACTION_ESTIMATE_SAFETY", "ACTION_ESTIMATE_OUTPUT_FLOOR_RATIO",
                 "AI_USAGE_LOG_FILE")
NEW_FUNCTIONS = ("record_ai_usage", "observed_output_tokens_per_call", "estimate_action_analysis_cost",
                 "count_failed_action_threads", "MailManagerGUI._confirm_ai_cost")
OLD_GUIDANCE_BUTTON = "「📋 アクション一覧を生成」"
NEW_GUIDANCE_BUTTON = "「🔄 解析のみ更新」"


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


class _ReplaceGuidanceButton(ast.NodeTransformer):
    """文字列定数の中の 「📋 アクション一覧を生成」 を 「🔄 解析のみ更新」 に置き換える (旧→新の差を打ち消すため)。"""

    def visit_Constant(self, node):
        if isinstance(node.value, str) and OLD_GUIDANCE_BUTTON in node.value:
            return ast.copy_location(ast.Constant(node.value.replace(OLD_GUIDANCE_BUTTON, NEW_GUIDANCE_BUTTON)), node)
        return node


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


class TestScopeGuardA11(unittest.TestCase):
    """範囲ガード: _03 → _04 で変えてよい既存の関数は _run_action_dashboard・_ui_action_tab・build_action_decision_snapshot だけ。追加は仕様の定数・関数・_confirm_ai_cost だけ。"""

    @classmethod
    def setUpClass(cls):
        cls.target = _loader.rev_path(NEW_REV)
        cls.baseline = _loader.rev_path(OLD_REV)
        if not (os.path.isfile(cls.target) and os.path.isfile(cls.baseline)):
            raise unittest.SkipTest("A1.1 のリビジョン対(20261004_03 / 20261004_04)が無い")
        cls.old = _index_source(cls.baseline)
        cls.new = _index_source(cls.target)

    def test_no_existing_function_or_method_is_removed(self):
        """既存の関数・メソッドが消えていない。"""
        removed = sorted(n for n in self.old[0] if n not in self.new[0])
        self.assertEqual(removed, [], f"既存の関数/メソッドが消えている: {removed}")

    def test_only_allowed_functions_changed(self):
        """許可された3つ以外の既存の関数・メソッドが変更されていない。"""
        old_f, new_f = self.old[0], self.new[0]
        changed = sorted(n for n, s in old_f.items() if n in new_f and new_f[n] != s and n not in ALLOWED_TO_CHANGE)
        self.assertEqual(changed, [], f"仕様で許可されていない既存関数/メソッドの変更: {changed}")

    def test_allowed_functions_were_actually_changed(self):
        """許可された3つが実際に変更されている (A1.1の実装がある)。"""
        old_f, new_f = self.old[0], self.new[0]
        for n in sorted(ALLOWED_TO_CHANGE):
            with self.subTest(function=n):
                self.assertIn(n, old_f)
                self.assertIn(n, new_f)
                self.assertNotEqual(old_f[n], new_f[n], f"A1.1 で変更するはずの {n} が変更されていない")

    def test_existing_constants_are_unchanged(self):
        """既存の定数 (A2の COST_CONFIRM_THRESHOLD_YEN などを含む) が変わっていない。"""
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

    def test_new_names_are_added_at_module_level_or_as_the_named_method(self):
        """仕様の新しい定数・関数 (と _confirm_ai_cost) が追加されている。"""
        for n in NEW_FUNCTIONS:
            with self.subTest(function=n):
                self.assertIn(n, self.new[0])
                self.assertNotIn(n, self.old[0])
        for n in NEW_CONSTANTS:
            with self.subTest(constant=n):
                self.assertIn(n, self.new[1])
                self.assertNotIn(n, self.old[1])

    def test_nothing_else_was_added_beyond_the_names_in_the_spec(self):
        """仕様に無い関数・メソッド・公開の定数が追加されていない。"""
        # 仕様: 「追加は上記の定数・関数・_confirm_ai_cost のみ」。先頭が _ の非公開の定数は実装の詳細として許容する
        added_f = sorted(set(self.new[0]) - set(self.old[0]))
        added_c = sorted(set(self.new[1]) - set(self.old[1]))
        self.assertEqual(added_f, sorted(NEW_FUNCTIONS), f"仕様に無い関数/メソッドが追加されている: {added_f}")
        public_c = [n for n in added_c if not n.split(".")[-1].startswith("_")]
        self.assertEqual(public_c, sorted(NEW_CONSTANTS), f"仕様に無い公開の定数が追加されている: {added_c}")

    def test_new_module_level_definitions_sit_right_before_load_project_knowledge(self):
        """追加した定数・関数が、仕様どおり load_project_knowledge の直前にまとまっている。"""
        names = _top_level_names(self.target)
        module_level = [n for n in NEW_CONSTANTS + NEW_FUNCTIONS if "." not in n]
        positions = sorted(names[n] for n in module_level)
        anchor = names["load_project_knowledge"]
        self.assertEqual(positions, list(range(anchor - len(positions), anchor)),
                         "追加した定数・関数が load_project_knowledge の直前にまとまっていない")
        self.assertGreater(min(positions), names["estimate_ai_cost_yen_multi"])

    def test_count_failed_action_threads_sits_right_after_estimate_action_analysis_cost(self):
        """count_failed_action_threads は、仕様どおり estimate_action_analysis_cost の直後に置かれている。"""
        names = _top_level_names(self.target)
        self.assertEqual(names["count_failed_action_threads"], names["estimate_action_analysis_cost"] + 1)

    def test_floor_ratio_constant_sits_right_after_the_safety_constant(self):
        """ACTION_ESTIMATE_OUTPUT_FLOOR_RATIO は、仕様どおり ACTION_ESTIMATE_SAFETY の次に置かれている。"""
        names = _top_level_names(self.target)
        self.assertEqual(names["ACTION_ESTIMATE_OUTPUT_FLOOR_RATIO"], names["ACTION_ESTIMATE_SAFETY"] + 1)

    def test_build_action_decision_snapshot_changed_only_in_the_two_guidance_strings(self):
        """build_action_decision_snapshot は案内文の文字列2か所だけが変わっている。"""
        old_fn = func_node(self.baseline, "build_action_decision_snapshot")
        new_fn = func_node(self.target, "build_action_decision_snapshot")
        replaced = _ReplaceGuidanceButton().visit(copy.deepcopy(old_fn))
        self.assertEqual(ast.dump(replaced), ast.dump(new_fn),
                         "案内文の文字列2か所以外が変更されている (関数の他の部分は不変のはず)")

    def test_the_two_guidance_strings_were_actually_replaced(self):
        """その2か所が、旧ボタン名から「🔄 解析のみ更新」に置き換わっている。"""
        old_src = ast.unparse(func_node(self.baseline, "build_action_decision_snapshot"))
        new_src = ast.unparse(func_node(self.target, "build_action_decision_snapshot"))
        self.assertEqual(old_src.count(OLD_GUIDANCE_BUTTON), 2)
        self.assertEqual(new_src.count(OLD_GUIDANCE_BUTTON), 0)
        self.assertEqual(new_src.count(NEW_GUIDANCE_BUTTON), 2)

    def test_ui_action_tab_changed_only_by_inserting_the_update_button(self):
        """_ui_action_tab は「🔄 解析のみ更新」ボタンの追加 (挿入) だけが変わっている。"""
        old = ast.unparse(func_node(self.baseline, "MailManagerGUI._ui_action_tab")).splitlines()
        new = ast.unparse(func_node(self.target, "MailManagerGUI._ui_action_tab")).splitlines()
        ops = difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes()
        changes = [(tag, i1, i2, new[j1:j2]) for tag, i1, i2, j1, j2 in ops if tag != "equal"]
        self.assertEqual([c for c in changes if c[0] != "insert"], [], "追加以外の変更 (削除・置換) がある")
        self.assertEqual(len(changes), 1, "追加が1か所にまとまっていない")
        inserted = "\n".join(changes[0][3])
        for needle in ("self.btn_update_action", "ttk.Button", "解析のみ更新", ".pack("):
            self.assertIn(needle, inserted)

    def test_update_button_code_is_inserted_right_after_the_run_button(self):
        """追加位置が「📋 …」ボタンの pack の直後・reformat ボタンの前。"""
        old = ast.unparse(func_node(self.baseline, "MailManagerGUI._ui_action_tab")).splitlines()
        new = ast.unparse(func_node(self.target, "MailManagerGUI._ui_action_tab")).splitlines()
        ops = [op for op in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes() if op[0] != "equal"]
        self.assertEqual(len(ops), 1, "追加が1か所にまとまっていない")
        i1 = ops[0][1]
        self.assertIn("self.btn_run_action.pack(", old[i1 - 1], "run ボタンの pack の直後に追加するはず")
        self.assertIn("_reformat_init_state", old[i1], "reformat ボタンの前に追加するはず")

    def test_reformat_and_result_saving_methods_are_untouched(self):
        """_reformat_action_dashboard・_save_action_dashboard_result など周辺のメソッドが無変更。"""
        for n in ("MailManagerGUI._reformat_action_dashboard", "MailManagerGUI._save_action_dashboard_result",
                  "MailManagerGUI._get_action_days", "MailManagerGUI._set_status",
                  "MailManagerGUI._refresh_action_decision_view", "save_action_last_run"):
            with self.subTest(function=n):
                self.assertEqual(self.new[0][n], self.old[0][n], f"{n} が変更されている")


# ローカルタイムゾーンを JST(+9) / EST(-5) にして、`at` が「ローカル時刻」であることを再確認する
_loader.make_tz_variants(globals(), [TestSpecGapRecordAiUsageAtIsLocalTime])


if __name__ == "__main__":
    unittest.main(verbosity=2)
