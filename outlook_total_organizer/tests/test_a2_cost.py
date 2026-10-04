# -*- coding: utf-8 -*-
"""A2「費用表示の正確化と事前見積りの土台」テスト (仕様書 A2_SPEC.md)。

仕様書だけを根拠に、実装 (_20261004_02.py の新規・変更部分) を見ずに書いている。
  - 仕様に明記された挙動            -> 通常の TestCase
  - 仕様が曖昧/未記載で「最も自然な解釈」で書いたもの
                                    -> クラス名に SpecGap を含む (コメントに解釈を明記)
    SpecGap の失敗は「バグ」ではなく「仕様の確認が必要」の合図として扱う。

仕様変更 (A2_SPEC_DELTA_fix1.md: 敵対的レビュー第1回の指摘の反映) に追随済み:
単価表3件化 / モデル名の正規化 / 未登録モデルは表の最大単価 (known=False) + 注記 / シムの出力トークン規則 /
_as_token_count の int(float()) / 設定の独立検証 / estimate_ai_cost_yen_multi / 累計トークンのリセット (B1)。

構成
  1. _as_token_count / _CommonUsageMetadata / _CommonGeminiResponse (思考トークンの加算)
  2. 定数 / _cost_settings / _normalize_model_name / get_gemini_price / api_cost_note / calc_api_cost_yen
  3. estimate_ai_cost_yen / estimate_ai_cost_yen_multi
  4. HTMLReportGenerator の6か所の置換 (ソース確認 + 実際にHTMLを出力して確認)
  5. 範囲ガード (_20261004_01.py と _20261004_02.py の AST 比較。変更してよいのは許可リストだけ)
  6. 旧単価 (0.075/0.3) との回帰
  7. B1: 費用表示を「今回の実行分」にする累計トークンのリセット (ソース確認 + _run_action_dashboard の機能テスト)

設定ファイル (json/mail_manager_config.json) を読む処理は、利用者の実設定を拾わないよう、
必ず空の一時cwd の中で動かす (InTempCwd)。
"""
import ast
import copy
import difflib
import functools
import inspect
import os
import random
import unittest
from unittest import mock

import _loader
import test_a1_gui_smoke as a1gui          # B1 の機能テストで A1 の GUI ハーネス (GuiCase / スタブ) を再利用する
from _loader import tempdir_cwd, write_bytes, write_json, write_text


def oto():
    return _loader.load()


FLASH = "gemini-2.5-flash"
LITE = "gemini-2.5-flash-lite"
PRO = "gemini-2.5-pro"
DEFAULT_PRICES = {FLASH: (0.30, 2.50), LITE: (0.10, 0.40), PRO: (1.25, 10.00)}
MAX_PRICE = (1.25, 10.00)        # 既定の表の「入力単価の最大・出力単価の最大」= 未登録モデルに使う単価
NOTE = "　※単価未登録のモデルのため、表の最大単価で計算した概算（実際の単価と異なる場合があります）"    # 先頭は全角空白

SIX_REPORTS = (
    "generate_project_report", "generate_staff_report", "generate_cockpit_report",
    "generate_cockpit_v2_report", "generate_review_report", "generate_action_dashboard_report",
)

COST_LINE = "💰 APIコスト概算: 約 {total_yen} 円 (In:{total_input} / Out:{total_output})"
REFORMAT_LINE = "🎨 フォーマット再生成のみ（APIコスト無し）"


def write_config(obj):
    """一時cwd に設定ファイルを書く (パスは実装の CONFIG_FILE)。
    bytes / str はそのまま (壊れた設定の再現用)、それ以外は JSON として書く。"""
    path = oto().CONFIG_FILE
    if isinstance(obj, bytes):
        write_bytes(path, obj)
    elif isinstance(obj, str):
        write_text(path, obj)
    else:
        write_json(path, obj)


def as_tuples(prices):
    return {k: tuple(v) for k, v in prices.items()}


class InTempCwd(unittest.TestCase):
    """各テストを空の一時cwd で動かす (実際の config を拾わない / json/ を汚さない)。"""

    def setUp(self):
        cm = tempdir_cwd()
        self.tmp = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)


# ============================================================
# 1-a. _as_token_count
# ============================================================
class TestAsTokenCount(unittest.TestCase):
    def f(self, v):
        return oto()._as_token_count(v)

    def test_non_negative_integers_are_kept(self):
        for v in (0, 1, 42, 1_000_000, 2 ** 40):
            with self.subTest(v=v):
                self.assertEqual(self.f(v), v)

    def test_none_and_empty_string_become_zero(self):
        for v in (None, ""):
            with self.subTest(v=v):
                self.assertEqual(self.f(v), 0)

    def test_non_numeric_strings_become_zero(self):
        for v in ("abc", "12abc", "1,000", "  ", "tokens", "-"):
            with self.subTest(v=v):
                self.assertEqual(self.f(v), 0)

    def test_negative_numbers_become_zero(self):
        for v in (-1, -100, -0.5, -1e9, "-5"):
            with self.subTest(v=v):
                self.assertEqual(self.f(v), 0)

    def test_decimals_are_truncated_not_rounded(self):
        for v, exp in ((0.0, 0), (0.99, 0), (1.0, 1), (1.5, 1), (2.999, 2), (3.9, 3), (12.7, 12), (1000000.5, 1000000)):
            with self.subTest(v=v):
                self.assertEqual(self.f(v), exp)

    def test_numeric_strings_are_converted_via_int_of_float(self):
        # 仕様(変更後): int(float(value)) で変換する。"12.7" -> 12
        for v, exp in (("123", 123), ("0", 0), ("12.7", 12), ("0.99", 0), ("-5", 0), ("-0.5", 0)):
            with self.subTest(v=v):
                self.assertEqual(self.f(v), exp)

    def test_bool_is_converted_like_int(self):
        # 仕様(変更後): True -> 1
        self.assertEqual(self.f(True), 1)
        self.assertEqual(self.f(False), 0)

    def test_nan_and_infinity_become_zero_without_raising(self):
        # 仕様(変更後): NaN / ±inf -> 0 (例外を出さない)
        for v in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(v=v):
                self.assertEqual(self.f(v), 0)

    def test_always_returns_plain_int(self):
        for v in (0, 5, 5.7, "7", "12.7", None, -3, "abc", True, float("nan"), float("inf")):
            with self.subTest(v=v):
                self.assertIs(type(self.f(v)), int)


class TestSpecGapAsTokenCount(unittest.TestCase):
    def f(self, v):
        return oto()._as_token_count(v)

    def test_containers_become_zero(self):
        # 解釈: 数値として読めないものは全部 0 (仕様が例示するのは "abc"/None/-5/NaN/±inf)
        for v in ([], [5], {}, {"a": 1}, (3,)):
            with self.subTest(v=v):
                self.assertEqual(self.f(v), 0)

    def test_nan_and_infinity_strings_become_zero(self):
        # 解釈: 文字列 "nan"/"inf" も float() を通る点は同じなので、float の NaN/±inf と同じく 0 で例外なし
        for v in ("nan", "NaN", "inf", "-inf", "Infinity"):
            with self.subTest(v=v):
                self.assertEqual(self.f(v), 0)


# ============================================================
# 1-b. _CommonUsageMetadata
# ============================================================
def U(prompt=None, cand=None, thoughts=None, total=None):
    """usageMetadata の dict (None の項目はキーごと省略)。"""
    d = {}
    if prompt is not None:
        d["promptTokenCount"] = prompt
    if cand is not None:
        d["candidatesTokenCount"] = cand
    if thoughts is not None:
        d["thoughtsTokenCount"] = thoughts
    if total is not None:
        d["totalTokenCount"] = total
    return d


def md(usage):
    return oto()._CommonUsageMetadata(usage)


def attrs(m):
    return {"prompt": m.prompt_token_count, "visible": m.visible_candidates_token_count,
            "thoughts": m.thoughts_token_count, "cand": m.candidates_token_count}


ZEROS = {"prompt": 0, "visible": 0, "thoughts": 0, "cand": 0}


class TestCommonUsageMetadata(unittest.TestCase):
    def test_fields_are_mapped_and_thoughts_are_added(self):
        self.assertEqual(attrs(md(U(100, 50, 30))), {"prompt": 100, "visible": 50, "thoughts": 30, "cand": 80})

    def test_without_thoughts_candidates_equal_visible(self):
        self.assertEqual(attrs(md(U(100, 50))), {"prompt": 100, "visible": 50, "thoughts": 0, "cand": 50})

    def test_total_minus_prompt_is_used_when_both_are_present(self):
        # 仕様(変更後): total と prompt が両方あり (>0) かつ total >= prompt のときは total - prompt
        self.assertEqual(attrs(md(U(1000, 200, 300, 1500))), {"prompt": 1000, "visible": 200, "thoughts": 300, "cand": 500})
        self.assertEqual(attrs(md(U(100, 50, 30, 250))), {"prompt": 100, "visible": 50, "thoughts": 30, "cand": 150})
        self.assertEqual(attrs(md(U(100, 50, None, 400))), {"prompt": 100, "visible": 50, "thoughts": 0, "cand": 300})

    def test_old_max_rule_is_gone(self):
        # 旧規則 max(visible+thoughts, total-prompt) だと 1800 になるケース。新規則は total - prompt = 1000
        self.assertEqual(attrs(md(U(1000, 1000, 800, 2000))),
                         {"prompt": 1000, "visible": 1000, "thoughts": 800, "cand": 1000})

    def test_total_minus_prompt_rule_boundaries(self):
        # prompt=100, visible+thoughts=80。total が prompt を下回る(矛盾)/等しい(矛盾: 出力0は不自然)/上回る境界と、80 前後。
        # 第1回レビュー後の仕様: total > prompt のときだけ差を採り、それ以外は visible + thoughts
        for total, exp in ((99, 80), (100, 80), (101, 1), (170, 70), (179, 79), (180, 80), (181, 81), (250, 150)):
            with self.subTest(total=total):
                self.assertEqual(md(U(100, 50, 30, total)).candidates_token_count, exp)

    def test_prompt_greater_than_total_falls_back_to_visible_plus_thoughts(self):
        # 矛盾 (prompt > total): total - prompt が負になるので使わず、visible + thoughts
        self.assertEqual(attrs(md(U(1000, 200, 300, 800))), {"prompt": 1000, "visible": 200, "thoughts": 300, "cand": 500})

    def test_total_zero_or_missing_means_visible_plus_thoughts(self):
        self.assertEqual(md(U(100, 50, 30, 0)).candidates_token_count, 80)
        self.assertEqual(md(U(100, 50, 30)).candidates_token_count, 80)

    def test_total_without_prompt_falls_back_to_visible_plus_thoughts(self):
        # 仕様(変更後): total だけ (prompt 無し/0) のときは visible + thoughts (旧: total をそのまま採用していた)
        self.assertEqual(attrs(md(U(None, 50, None, 500))), {"prompt": 0, "visible": 50, "thoughts": 0, "cand": 50})
        self.assertEqual(attrs(md(U(None, 50, 30, 500))), {"prompt": 0, "visible": 50, "thoughts": 30, "cand": 80})
        self.assertEqual(attrs(md(U(0, 50, 30, 500))), {"prompt": 0, "visible": 50, "thoughts": 30, "cand": 80})

    def test_numeric_strings_none_and_garbage_in_total_and_prompt(self):
        # すべて _as_token_count を通す: 数値文字列は数値、None/非数値は 0 (= 「あり」とみなさない)
        k = ("promptTokenCount", "candidatesTokenCount", "thoughtsTokenCount", "totalTokenCount")
        cases = (
            (dict(zip(k, ("1000", "200", "300", "1500"))), {"prompt": 1000, "visible": 200, "thoughts": 300, "cand": 500}),
            (dict(zip(k, ("1000", "200", "300", "1700"))), {"prompt": 1000, "visible": 200, "thoughts": 300, "cand": 700}),
            (dict(zip(k, (1000, 200, 300, "abc"))), {"prompt": 1000, "visible": 200, "thoughts": 300, "cand": 500}),
            (dict(zip(k, (1000, 200, 300, None))), {"prompt": 1000, "visible": 200, "thoughts": 300, "cand": 500}),
            (dict(zip(k, (None, 200, 300, 9999))), {"prompt": 0, "visible": 200, "thoughts": 300, "cand": 500}),
            (dict(zip(k, ("x", "200", "300", "9999"))), {"prompt": 0, "visible": 200, "thoughts": 300, "cand": 500}),
            (dict(zip(k, ("100.9", "50.9", "10.9", "250.9"))), {"prompt": 100, "visible": 50, "thoughts": 10, "cand": 150}),
        )
        for usage, exp in cases:
            with self.subTest(usage=usage):
                self.assertEqual(attrs(md(usage)), exp)

    def test_realistic_gemini_responses(self):
        # 回答 200 + 思考 500、total = prompt + 回答 + 思考
        self.assertEqual(attrs(md(U(1234, 200, 500, 1934))),
                         {"prompt": 1234, "visible": 200, "thoughts": 500, "cand": 700})
        # 思考だけで回答が空 (candidatesTokenCount 欠落) でも出力課金分は数える
        self.assertEqual(attrs(md(U(100, None, 900, 1000))),
                         {"prompt": 100, "visible": 0, "thoughts": 900, "cand": 900})

    def test_empty_none_and_non_numeric_values_give_zeros(self):
        keys = ("promptTokenCount", "candidatesTokenCount", "thoughtsTokenCount", "totalTokenCount")
        cases = {
            "empty dict": {},
            "None": {k: None for k in keys},
            "empty str": {k: "" for k in keys},
            "non-numeric str": {k: "abc" for k in keys},
        }
        for label, usage in cases.items():
            with self.subTest(case=label):
                self.assertEqual(attrs(md(usage)), ZEROS)

    def test_negative_values_are_clamped_to_zero(self):
        self.assertEqual(attrs(md(U(-10, -20, -30))), ZEROS)
        self.assertEqual(attrs(md(U(100, -20, 10))), {"prompt": 100, "visible": 0, "thoughts": 10, "cand": 10})
        # 負の total は total 規則を勝たせない
        self.assertEqual(md(U(100, 50, None, -999)).candidates_token_count, 50)

    def test_decimals_are_truncated(self):
        self.assertEqual(attrs(md(U(100.9, 50.9, 10.9))), {"prompt": 100, "visible": 50, "thoughts": 10, "cand": 60})

    def test_non_dict_usage_gives_zeros(self):
        for usage in (None, [], [1, 2], "abc", 5, 3.5, (1, 2), set()):
            with self.subTest(usage=usage):
                self.assertEqual(attrs(md(usage)), ZEROS)

    def test_all_attributes_are_int(self):
        for usage in (U(100, 50, 30, 250), U(100.5, 50.5, 3.5), {}, None):
            with self.subTest(usage=usage):
                for name, v in attrs(md(usage)).items():
                    self.assertIs(type(v), int, name)

    def test_extra_keys_are_ignored_and_input_is_not_modified(self):
        usage = U(10, 5, None, None)
        usage["cachedContentTokenCount"] = 7
        usage["promptTokensDetails"] = [{"modality": "TEXT", "tokenCount": 10}]
        before = copy.deepcopy(usage)
        self.assertEqual(attrs(md(usage)), {"prompt": 10, "visible": 5, "thoughts": 0, "cand": 5})
        self.assertEqual(usage, before)


# ============================================================
# 1-c. _CommonGeminiResponse
# ============================================================
def raw_response(text="こんにちは", usage=None):
    r = {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    if usage is not None:
        r["usageMetadata"] = usage
    return r


class TestCommonGeminiResponse(InTempCwd):
    def test_thinking_tokens_flow_into_usage_metadata(self):
        resp = oto()._CommonGeminiResponse(raw_response(usage=U(1000, 100, 900, 2000)))
        self.assertEqual(resp.text, "こんにちは")
        self.assertEqual(attrs(resp.usage_metadata), {"prompt": 1000, "visible": 100, "thoughts": 900, "cand": 1000})

    def test_thinking_makes_the_displayed_cost_higher(self):
        # 呼び出し側は candidates_token_count をそのまま出力トークンとして足す (仕様「変えないもの」)
        um = oto()._CommonGeminiResponse(raw_response(usage=U(1000, 100, 900, 2000))).usage_metadata
        with_thinking = oto().calc_api_cost_yen(um.prompt_token_count, um.candidates_token_count)
        visible_only = oto().calc_api_cost_yen(um.prompt_token_count, um.visible_candidates_token_count)
        self.assertEqual(with_thinking, 0.45)    # (1000*0.30 + 1000*2.50)/1e6*160 = 0.448
        self.assertEqual(visible_only, 0.09)     # (1000*0.30 +  100*2.50)/1e6*160 = 0.088
        self.assertGreater(with_thinking, visible_only)

    def test_missing_or_non_dict_usage_metadata_gives_zeros(self):
        for label, raw in (("missing", raw_response()), ("None", dict(raw_response(), usageMetadata=None)),
                           ("str", dict(raw_response(), usageMetadata="x")), ("list", dict(raw_response(), usageMetadata=[]))):
            with self.subTest(case=label):
                resp = oto()._CommonGeminiResponse(raw)
                self.assertEqual(resp.text, "こんにちは")
                self.assertEqual(attrs(resp.usage_metadata), ZEROS)

    def test_non_dict_raw_gives_empty_text_and_zeros(self):
        for raw in (None, [], "abc", 5):
            with self.subTest(raw=raw):
                resp = oto()._CommonGeminiResponse(raw)
                self.assertEqual(resp.text, "")
                self.assertEqual(attrs(resp.usage_metadata), ZEROS)


# ============================================================
# 2-a. 定数
# ============================================================
class TestConstants(unittest.TestCase):
    def test_new_constants(self):
        m = oto()
        self.assertEqual(as_tuples(m.GEMINI_PRICES_USD_PER_1M), DEFAULT_PRICES)
        self.assertEqual(m.GEMINI_PRICE_FALLBACK_MODEL, FLASH)
        self.assertEqual(m.COST_CONFIRM_THRESHOLD_YEN, 100)
        self.assertEqual(m.ESTIMATE_TOKENS_PER_CHAR, 1.0)

    def test_fallback_model_is_in_the_price_table(self):
        self.assertIn(oto().GEMINI_PRICE_FALLBACK_MODEL, oto().GEMINI_PRICES_USD_PER_1M)

    def test_legacy_constants_are_kept_unchanged(self):
        m = oto()
        self.assertEqual(m.EXCHANGE_RATE_YEN, 160.0)
        self.assertEqual(m.PRICE_INPUT_1M_USD, 0.075)
        self.assertEqual(m.PRICE_OUTPUT_1M_USD, 0.30)


# ============================================================
# 2-b. _cost_settings
# ============================================================
class TestCostSettings(InTempCwd):
    def settings(self):
        return oto()._cost_settings()

    def test_defaults_without_config_file(self):
        usd_jpy, prices, model = self.settings()
        self.assertEqual(usd_jpy, 160.0)
        self.assertEqual(as_tuples(prices), DEFAULT_PRICES)
        self.assertEqual(model, FLASH)

    def test_default_fx_comes_from_exchange_rate_constant(self):
        with mock.patch.object(oto(), "EXCHANGE_RATE_YEN", 150.0):
            self.assertEqual(self.settings()[0], 150.0)
            self.assertEqual(oto().calc_api_cost_yen(1_000_000, 1_000_000), 420.0)
        self.assertEqual(self.settings()[0], 160.0)

    def test_prices_is_a_copy_of_the_constant(self):
        _, prices, _ = self.settings()
        prices["zzz-model"] = (9.0, 9.0)
        prices[FLASH] = (9.0, 9.0)
        self.assertNotIn("zzz-model", oto().GEMINI_PRICES_USD_PER_1M)
        self.assertEqual(as_tuples(oto().GEMINI_PRICES_USD_PER_1M), DEFAULT_PRICES)
        self.assertEqual(as_tuples(self.settings()[1]), DEFAULT_PRICES)

    def test_default_model_comes_from_config(self):
        for label, cfg, exp in (("key missing", {"output_folder": "./x"}, FLASH),
                                ("flash-lite", {"gemini_model": LITE}, LITE),
                                ("unlisted model", {"gemini_model": "my-future-model"}, "my-future-model")):
            with self.subTest(case=label):
                write_config(cfg)
                usd_jpy, prices, model = self.settings()
                self.assertEqual(model, exp)
                self.assertEqual(usd_jpy, 160.0)
                self.assertEqual(as_tuples(prices), DEFAULT_PRICES)

    def test_usd_jpy_override(self):
        for v in (150, 142.5, 0.0001):
            with self.subTest(usd_jpy=v):
                write_config({"usd_jpy": v})
                self.assertEqual(self.settings()[0], v)

    def test_usd_jpy_not_adopted_unless_a_positive_finite_number(self):
        # 仕様(変更後): 非数値・0以下・NaN/inf・bool は不正 -> 既定の 160 (例外なし)
        for v in (0, 0.0, -1, -160, "abc", None, [], {}, float("nan"), float("inf"), float("-inf"), True, False):
            with self.subTest(usd_jpy=v):
                write_config({"usd_jpy": v})
                usd_jpy, prices, model = self.settings()
                self.assertEqual(usd_jpy, 160.0)
                self.assertEqual(as_tuples(prices), DEFAULT_PRICES)
                self.assertEqual(model, FLASH)

    def test_gemini_prices_add_and_override(self):
        write_config({"gemini_prices": {"gemini-3-flash": [0.4, 3.0], FLASH: [0.5, 3.0]}})
        _, prices, _ = self.settings()
        p = as_tuples(prices)
        self.assertEqual(p["gemini-3-flash"], (0.4, 3.0))       # 追加
        self.assertEqual(p[FLASH], (0.5, 3.0))                  # 上書き
        self.assertEqual(p[LITE], DEFAULT_PRICES[LITE])         # 触れていないモデルは既定のまま
        self.assertEqual(p[PRO], DEFAULT_PRICES[PRO])
        self.assertEqual(len(p), 4)

    def test_gemini_prices_keys_are_normalized(self):
        # 仕様(変更後): config の gemini_prices のキーにもモデル名の正規化 (前後空白・小文字・先頭の models/) を適用する
        write_config({"gemini_prices": {"Models/My-Model": [1.0, 4.0], " GEMINI-2.5-FLASH ": [0.5, 3.0]}})
        p = as_tuples(self.settings()[1])
        self.assertEqual(p["my-model"], (1.0, 4.0))
        self.assertEqual(p[FLASH], (0.5, 3.0))                  # 大文字・空白付きのキーが flash を上書きする
        self.assertEqual(set(p), {FLASH, LITE, PRO, "my-model"})    # 正規化前のキーは残らない

    def test_gemini_prices_zero_and_int_values_are_accepted(self):
        write_config({"gemini_prices": {"free": [0, 0], "in-only": [0, 1.5], "out-only": [1.5, 0], "ints": [1, 4]}})
        p = as_tuples(self.settings()[1])
        self.assertEqual((p["free"], p["in-only"], p["out-only"], p["ints"]),
                         ((0, 0), (0, 1.5), (1.5, 0), (1, 4)))

    def test_gemini_prices_invalid_entries_are_not_adopted(self):
        bad_values = {
            "one element": [1], "three elements": [1, 2, 3], "empty": [], "str in": ["a", 2], "str out": [1, "b"],
            "negative in": [-0.01, 1], "negative out": [1, -0.01], "None": [None, 1], "plain str": "x",
            "plain number": 5, "null": None, "dict": {"in": 1, "out": 2},
            "inf in": [float("inf"), 1], "inf out": [1, float("inf")],          # 有限な数値のみ採用
            "nan in": [float("nan"), 1], "nan out": [1, float("nan")],
        }
        for label, v in bad_values.items():
            with self.subTest(case=label):
                write_config({"gemini_prices": {"bad-model": v}})
                _, prices, _ = self.settings()          # 例外を出さない
                self.assertNotIn("bad-model", prices)
                self.assertEqual(as_tuples(prices), DEFAULT_PRICES)

    def test_gemini_prices_that_is_not_a_dict_is_ignored(self):
        for v in ([], "x", 5, None, [["a", 1, 2]]):
            with self.subTest(gemini_prices=v):
                write_config({"gemini_prices": v})
                usd_jpy, prices, model = self.settings()
                self.assertEqual(usd_jpy, 160.0)
                self.assertEqual(as_tuples(prices), DEFAULT_PRICES)
                self.assertEqual(model, FLASH)

    def test_config_override_does_not_modify_the_module_constant(self):
        write_config({"usd_jpy": 100, "gemini_prices": {FLASH: [9.0, 9.0], "new-model": [1.0, 1.0]}})
        self.settings()
        self.assertEqual(as_tuples(oto().GEMINI_PRICES_USD_PER_1M), DEFAULT_PRICES)
        self.assertEqual(oto().EXCHANGE_RATE_YEN, 160.0)

    def test_broken_config_falls_back_to_defaults_without_raising(self):
        broken = {
            "invalid json": "{not json", "empty file": "", "blank": "   ", "truncated": "{", "json null": "null",
            "json list": "[]", "json number": "5", "json string": '"abc"', "binary garbage": b"\xff\xfe\x00garbage\x80",
        }
        for label, content in broken.items():
            with self.subTest(case=label):
                write_config(content)
                usd_jpy, prices, model = self.settings()
                self.assertEqual(usd_jpy, 160.0)
                self.assertEqual(as_tuples(prices), DEFAULT_PRICES)
                self.assertEqual(model, FLASH)

    def test_invalid_usd_jpy_does_not_block_gemini_prices(self):
        # 仕様(変更後): 各設定を独立に検証する。usd_jpy が不正でも gemini_prices は読む
        for bad in ("abc", 0, -5, None, float("nan"), float("inf"), True):
            with self.subTest(usd_jpy=bad):
                write_config({"usd_jpy": bad, "gemini_prices": {"m": [1, 2]}})
                usd_jpy, prices, model = self.settings()
                self.assertEqual(usd_jpy, 160.0)
                self.assertEqual(as_tuples(prices)["m"], (1, 2))
                self.assertEqual(model, FLASH)

    def test_valid_usd_jpy_is_kept_even_if_price_entries_are_invalid(self):
        write_config({"usd_jpy": 150, "gemini_prices": {"bad": "x", "bad2": [1]}})
        usd_jpy, prices, _ = self.settings()
        self.assertEqual(usd_jpy, 150)
        self.assertEqual(as_tuples(prices), DEFAULT_PRICES)

    def test_an_invalid_entry_is_skipped_but_later_entries_are_adopted(self):
        # 仕様(変更後): 不正なエントリは「そのエントリだけ」飛ばし、後続のエントリは採用する
        write_config({"gemini_prices": {"ok-1": [1, 2], "bad-1": "x", "bad-2": [1], "ok-2": [3, 4],
                                         "bad-3": [-1, 2], "ok-3": [0, 0]}})
        p = as_tuples(self.settings()[1])
        self.assertEqual((p["ok-1"], p["ok-2"], p["ok-3"]), ((1, 2), (3, 4), (0, 0)))
        self.assertEqual({k for k in p if k.startswith("bad")}, set())
        self.assertEqual(len(p), 3 + 3)

    def test_valid_usd_jpy_and_prices_are_both_adopted(self):
        write_config({"usd_jpy": 150, "gemini_model": LITE, "gemini_prices": {"m": [1, 2]}})
        usd_jpy, prices, model = self.settings()
        self.assertEqual((usd_jpy, model), (150, LITE))
        self.assertEqual(as_tuples(prices)["m"], (1, 2))

    def test_load_config_failure_or_non_dict_config_gives_defaults(self):
        # 仕様(変更後): load_config() が例外を出す / config が dict でない -> 既定 (例外を出さない)
        for label, kwargs in (("raises", {"side_effect": RuntimeError("boom")}),
                              ("returns list", {"return_value": [1, 2]}), ("returns None", {"return_value": None}),
                              ("returns str", {"return_value": "abc"})):
            with self.subTest(case=label):
                with mock.patch.object(oto(), "load_config", **kwargs):
                    usd_jpy, prices, model = self.settings()
                self.assertEqual(usd_jpy, 160.0)
                self.assertEqual(as_tuples(prices), DEFAULT_PRICES)
                self.assertEqual(model, FLASH)


class TestSpecGapCostSettings(InTempCwd):
    def test_bool_price_entries_are_not_adopted(self):
        # 解釈: usd_jpy と同様に bool は「数値」とみなさない (仕様はエントリを「両方が有限な0以上の数値」と書く)
        for v in ([True, 1], [1, False], [True, True]):
            with self.subTest(entry=v):
                write_config({"gemini_prices": {"bool-model": v}})
                self.assertNotIn("bool-model", oto()._cost_settings()[1])

    def test_config_changes_are_picked_up_on_the_next_call(self):
        # 解釈: 設定はキャッシュせず、呼ぶたびに load_config() で読む (仕様に「キャッシュする」の記載が無い)
        write_config({"usd_jpy": 150})
        self.assertEqual(oto()._cost_settings()[0], 150)
        write_config({"usd_jpy": 120})
        self.assertEqual(oto()._cost_settings()[0], 120)
        write_config("{broken")
        self.assertEqual(oto()._cost_settings()[0], 160.0)

    def test_null_or_empty_gemini_model_still_prices_like_flash(self):
        # 解釈: gemini_model が null / 空文字でも例外を出さず、単価は gemini-2.5-flash 相当で計算される
        #       (default_model 自体を None で返すか "gemini-2.5-flash" に戻すかは問わない)
        for v in (None, ""):
            with self.subTest(gemini_model=v):
                write_config({"gemini_model": v})
                oto()._cost_settings()
                self.assertEqual(oto().calc_api_cost_yen(1_000_000, 1_000_000), 448.0)


# ============================================================
# 2-c. _normalize_model_name (新規)
# ============================================================
class TestNormalizeModelName(unittest.TestCase):
    def n(self, v):
        return oto()._normalize_model_name(v)

    def test_none_and_empty_become_empty_string(self):
        for v in (None, "", "   "):
            with self.subTest(v=v):
                self.assertEqual(self.n(v), "")

    def test_strips_lowercases_and_removes_leading_models_prefix(self):
        cases = (
            ("gemini-2.5-flash", "gemini-2.5-flash"),
            ("  Gemini-2.5-Flash  ", "gemini-2.5-flash"),
            ("GEMINI-2.5-FLASH-LITE", "gemini-2.5-flash-lite"),
            ("models/gemini-2.5-pro", "gemini-2.5-pro"),
            ("Models/Gemini-2.5-Flash", "gemini-2.5-flash"),           # 仕様の例
            ("  MODELS/Gemini-2.5-Pro \n", "gemini-2.5-pro"),
        )
        for v, exp in cases:
            with self.subTest(v=v):
                self.assertEqual(self.n(v), exp)

    def test_only_a_leading_models_prefix_is_removed(self):
        for v in ("foo/models/bar", "my-models/x", "gemini-models"):
            with self.subTest(v=v):
                self.assertEqual(self.n(v), v)

    def test_returns_str_and_is_idempotent(self):
        for v in (None, "", "Models/Gemini-2.5-Flash", " x ", "gemini-9"):
            with self.subTest(v=v):
                r = self.n(v)
                self.assertIsInstance(r, str)
                self.assertEqual(self.n(r), r)


# ============================================================
# 2-d. get_gemini_price
# ============================================================
class TestGetGeminiPrice(InTempCwd):
    def price(self, *args, **kwargs):
        return oto().get_gemini_price(*args, **kwargs)

    def test_known_models(self):
        for model, exp in ((FLASH, (0.30, 2.50)), (LITE, (0.10, 0.40)), (PRO, (1.25, 10.00))):
            with self.subTest(model=model):
                r = self.price(model)
                self.assertEqual(tuple(r), exp + (True,))
                self.assertIs(r[2], True)

    def test_model_names_are_normalized_before_lookup(self):
        # 仕様(変更後): 前後空白除去・小文字化・先頭の models/ 除去 -> 単価表にあれば known=True
        cases = (("Models/Gemini-2.5-Flash", (0.30, 2.50, True)), (" gemini-2.5-flash-lite ", (0.10, 0.40, True)),
                 ("MODELS/GEMINI-2.5-PRO", (1.25, 10.00, True)), ("GEMINI-2.5-FLASH", (0.30, 2.50, True)))
        for model, exp in cases:
            with self.subTest(model=model):
                self.assertEqual(tuple(self.price(model)), exp)

    def test_unknown_model_gets_the_highest_prices_with_known_false(self):
        # 仕様(変更後): 単価表に無いモデルは「表の入力単価の最大・出力単価の最大」(既定の表なら 1.25 / 10.00)、known=False
        for model in ("gemini-9", "gemini-9.9-ultra", "totally-unknown", "gpt-4o", "gemini-2.5-flash-8b"):
            with self.subTest(model=model):
                r = self.price(model)
                self.assertEqual(tuple(r), MAX_PRICE + (False,))
                self.assertIs(r[2], False)

    def test_model_none_uses_the_default_model_from_config(self):
        self.assertEqual(tuple(self.price()), (0.30, 2.50, True))
        self.assertEqual(tuple(self.price(None)), (0.30, 2.50, True))
        self.assertEqual(tuple(self.price(model=None)), (0.30, 2.50, True))
        for cfg_model, exp in ((LITE, (0.10, 0.40, True)), (PRO, (1.25, 10.00, True)),
                               ("unknown-x", MAX_PRICE + (False,))):
            with self.subTest(gemini_model=cfg_model):
                write_config({"gemini_model": cfg_model})
                self.assertEqual(tuple(self.price()), exp)
                self.assertEqual(tuple(self.price(None)), exp)

    def test_explicit_model_wins_over_config_model(self):
        write_config({"gemini_model": LITE})
        self.assertEqual(tuple(self.price(FLASH)), (0.30, 2.50, True))

    def test_config_prices_override_and_extend_the_table(self):
        write_config({"gemini_prices": {FLASH: [1.0, 2.0], "my-model": [1.5, 4.0]}})
        self.assertEqual(tuple(self.price(FLASH)), (1.0, 2.0, True))
        self.assertEqual(tuple(self.price()), (1.0, 2.0, True))          # 既定モデル=flash も上書き後の単価
        self.assertEqual(tuple(self.price("my-model")), (1.5, 4.0, True))
        self.assertEqual(tuple(self.price(LITE)), (0.10, 0.40, True))

    def test_return_shape(self):
        r = self.price(FLASH)
        self.assertEqual(len(r), 3)
        self.assertIsInstance(r[0], (int, float))
        self.assertIsInstance(r[1], (int, float))
        self.assertIsInstance(r[2], bool)


    def test_unknown_model_price_follows_the_effective_table_independently_for_input_and_output(self):
        # 仕様(変更後): 入力単価の最大と出力単価の最大は別々に取る。config で高い単価を足せばそれも含む
        cases = (
            ("adds expensive model", {"gemini_prices": {"pricey": [3.0, 20.0]}}, (3.0, 20.0)),
            ("adds input-heavy model", {"gemini_prices": {"in-heavy": [5.0, 1.0]}}, (5.0, 10.0)),
            ("adds output-heavy model", {"gemini_prices": {"out-heavy": [0.5, 40.0]}}, (1.25, 40.0)),
            ("adds both", {"gemini_prices": {"in-heavy": [5.0, 1.0], "out-heavy": [0.5, 40.0]}}, (5.0, 40.0)),
            ("lowers the most expensive model", {"gemini_prices": {PRO: [0.5, 1.0]}}, (0.5, 2.5)),
            ("raises flash", {"gemini_prices": {FLASH: [2.0, 20.0]}}, (2.0, 20.0)),
            ("adds cheaper model", {"gemini_prices": {"cheap": [0.0, 0.0]}}, MAX_PRICE),
            ("invalid entry ignored", {"gemini_prices": {"bad": [99.0]}}, MAX_PRICE),
        )
        for label, cfg, exp in cases:
            with self.subTest(case=label):
                write_config(cfg)
                self.assertEqual(tuple(self.price("gemini-9")), exp + (False,))
                self.assertEqual(tuple(self.price("another-unknown")), exp + (False,))

    def test_config_price_keys_are_looked_up_by_normalized_name(self):
        write_config({"gemini_prices": {"Models/My-Model": [1.5, 4.0]}})
        for model in ("my-model", "MY-MODEL", "models/my-model", " My-Model "):
            with self.subTest(model=model):
                self.assertEqual(tuple(self.price(model)), (1.5, 4.0, True))


class TestSpecGapGetGeminiPrice(InTempCwd):
    def test_default_model_from_config_is_normalized_too(self):
        # 解釈: model=None のときの default_model (config の gemini_model) も、明示した model と同様に正規化して引く
        write_config({"gemini_model": " Models/Gemini-2.5-Flash-Lite "})
        self.assertEqual(tuple(oto().get_gemini_price()), (0.10, 0.40, True))


# ============================================================
# 2-e. api_cost_note (新規)
# ============================================================
class TestApiCostNote(InTempCwd):
    def note(self, *args, **kwargs):
        return oto().api_cost_note(*args, **kwargs)

    def test_known_models_have_no_note(self):
        for model in (None, FLASH, LITE, PRO):
            with self.subTest(model=model):
                self.assertEqual(self.note(model), "")
        self.assertEqual(self.note(), "")

    def test_unknown_models_get_the_note(self):
        for model in ("gemini-9", "totally-unknown", "gpt-4o"):
            with self.subTest(model=model):
                self.assertEqual(self.note(model), NOTE)
        self.assertTrue(self.note("gemini-9").startswith("　"))        # 先頭は全角空白

    def test_model_none_follows_the_config_default_model(self):
        for cfg_model, exp in ((LITE, ""), (PRO, ""), ("unknown-x", NOTE)):
            with self.subTest(gemini_model=cfg_model):
                write_config({"gemini_model": cfg_model})
                self.assertEqual(self.note(), exp)
                self.assertEqual(self.note(None), exp)

    def test_config_registered_model_has_no_note(self):
        write_config({"gemini_prices": {"my-model": [1.0, 4.0]}})
        self.assertEqual(self.note("my-model"), "")
        self.assertEqual(self.note("other-model"), NOTE)

    def test_note_is_consistent_with_price_known_flag(self):
        for model in (None, FLASH, LITE, PRO, "gemini-9", "x"):
            with self.subTest(model=model):
                known = oto().get_gemini_price(model)[2]
                self.assertEqual(self.note(model) == "", known)

    def test_returns_str(self):
        for model in (None, FLASH, "gemini-9"):
            self.assertIsInstance(self.note(model), str)


class TestSpecGapApiCostNote(InTempCwd):
    def test_normalized_model_names_are_known(self):
        # 解釈: 注記の「単価表にあるモデル」の判定も get_gemini_price と同じ正規化後の名前で行う
        for model in ("Models/Gemini-2.5-Flash", " GEMINI-2.5-PRO "):
            with self.subTest(model=model):
                self.assertEqual(oto().api_cost_note(model), "")


# ============================================================
# 2-d. calc_api_cost_yen
# ============================================================
class TestCalcApiCostYen(InTempCwd):
    def calc(self, *args, **kwargs):
        return oto().calc_api_cost_yen(*args, **kwargs)

    def test_flash_examples(self):
        cases = (
            (1_000_000, 1_000_000, 448.0),       # 仕様の例: (0.30+2.50)*160
            (1_000_000, 0, 48.0),
            (0, 1_000_000, 400.0),
            (0, 0, 0.0),
            (500_000, 500_000, 224.0),
            (2_000_000, 500_000, 296.0),         # 入力と出力を取り違えると 824.0 になる
            (10 ** 9, 10 ** 9, 448000.0),
        )
        for i, o, exp in cases:
            with self.subTest(input=i, output=o):
                self.assertEqual(self.calc(i, o), exp)

    def test_flash_lite_examples(self):
        for i, o, exp in ((1_000_000, 1_000_000, 80.0), (1_000_000, 0, 16.0), (0, 1_000_000, 64.0)):
            with self.subTest(input=i, output=o):
                self.assertEqual(self.calc(i, o, LITE), exp)
                self.assertEqual(self.calc(i, o, model=LITE), exp)

    def test_none_and_negative_counts_are_treated_as_zero(self):
        cases = ((None, None, 0.0), (None, 1_000_000, 400.0), (1_000_000, None, 48.0), (-5, -5, 0.0),
                 (-1_000_000, 1_000_000, 400.0), (1_000_000, -1, 48.0), (-1, -1, 0.0))
        for i, o, exp in cases:
            with self.subTest(input=i, output=o):
                self.assertEqual(self.calc(i, o), exp)

    def test_rounds_to_two_decimals(self):
        cases = (
            (123_456, 78_901, 37.49),    # 37.486288
            (1_041, 0, 0.05),            # 0.049968
            (1, 1, 0.0),                 # 0.000448
            (1_000_100, 0, 48.0),        # 48.0048 (切り捨て側)
            (1_000_200, 0, 48.01),       # 48.0096 (切り上げ側)
        )
        for i, o, exp in cases:
            with self.subTest(input=i, output=o):
                self.assertEqual(self.calc(i, o), exp)
        rng = random.Random(20261004)
        for _ in range(30):
            i, o = rng.randint(0, 5_000_000), rng.randint(0, 5_000_000)
            r = self.calc(i, o)
            self.assertEqual(r, round(r, 2))
            self.assertEqual(r, round((i / 1e6 * 0.30 + o / 1e6 * 2.50) * 160.0, 2))

    def test_returns_float(self):
        for i, o in ((1_000_000, 1_000_000), (0, 0), (None, None), (123, 456)):
            with self.subTest(input=i, output=o):
                self.assertIsInstance(self.calc(i, o), float)

    def test_float_token_counts_are_accepted(self):
        self.assertEqual(self.calc(1_000_000.0, 1_000_000.0), 448.0)

    def test_pro_examples(self):
        # gemini-2.5-pro は入力 $1.25 / 出力 $10.00 (仕様変更後の単価表)
        for i, o, exp in ((1_000_000, 1_000_000, 1800.0), (1_000_000, 0, 200.0), (0, 1_000_000, 1600.0)):
            with self.subTest(input=i, output=o):
                self.assertEqual(self.calc(i, o, PRO), exp)

    def test_unknown_model_is_priced_with_the_highest_prices(self):
        # 仕様(変更後): 未登録モデルは表の最大単価 (1.25 / 10.00)。例: gemini-9 の 1M/1M = (1.25+10.00)*160 = 1800.0
        for model in ("gemini-9", "unknown-model"):
            with self.subTest(model=model):
                self.assertEqual(self.calc(1_000_000, 1_000_000, model), 1800.0)
                self.assertEqual(self.calc(1_000_000, 0, model), 200.0)
                self.assertEqual(self.calc(0, 1_000_000, model), 1600.0)

    def test_normalized_model_names_are_priced_as_the_registered_model(self):
        self.assertEqual(self.calc(1_000_000, 1_000_000, "Models/Gemini-2.5-Flash"), 448.0)
        self.assertEqual(self.calc(1_000_000, 1_000_000, " GEMINI-2.5-FLASH-LITE "), 80.0)

    def test_unknown_model_follows_config_added_prices(self):
        write_config({"gemini_prices": {"pricey": [5.0, 40.0]}})
        self.assertEqual(self.calc(1_000_000, 1_000_000, "gemini-9"), 7200.0)       # (5+40)*160
        self.assertEqual(self.calc(1_000_000, 1_000_000, "pricey"), 7200.0)         # 登録済みとして同じ単価
        self.assertEqual(self.calc(1_000_000, 1_000_000), 448.0)                    # 既定モデル(flash)は変わらない

    def test_model_none_follows_config_and_explicit_model_wins(self):
        write_config({"gemini_model": LITE})
        self.assertEqual(self.calc(1_000_000, 1_000_000), 80.0)
        self.assertEqual(self.calc(1_000_000, 1_000_000, None), 80.0)
        self.assertEqual(self.calc(1_000_000, 1_000_000, FLASH), 448.0)

    def test_config_usd_jpy_and_prices_apply(self):
        for cfg, exp in (({"usd_jpy": 150}, 420.0), ({"usd_jpy": 100}, 280.0),
                         ({"gemini_prices": {FLASH: [1.0, 2.0]}}, 480.0),
                         ({"usd_jpy": 150, "gemini_model": LITE}, 75.0)):
            with self.subTest(config=cfg):
                write_config(cfg)
                self.assertEqual(self.calc(1_000_000, 1_000_000), exp)
        write_config({"gemini_prices": {"free-model": [0, 0]}})
        self.assertEqual(self.calc(1_000_000, 1_000_000, "free-model"), 0.0)

    def test_broken_or_invalid_config_still_gives_the_default_price(self):
        for label, cfg in (("invalid json", "{broken"), ("negative fx", {"usd_jpy": -5}), ("zero fx", {"usd_jpy": 0}),
                           ("bad prices", {"gemini_prices": {FLASH: ["a", "b"]}}), ("not a dict", [])):
            with self.subTest(case=label):
                write_config(cfg)
                self.assertEqual(self.calc(1_000_000, 1_000_000), 448.0)


# ============================================================
# 3. estimate_ai_cost_yen
# ============================================================
KEYS = {"input_tokens", "output_tokens", "yen", "needs_confirm", "price_known"}


class TestEstimateAiCostYen(InTempCwd):
    def est(self, *args, **kwargs):
        return oto().estimate_ai_cost_yen(*args, **kwargs)

    def test_spec_example(self):
        r = self.est(100000, 10, 2000)
        self.assertEqual((r["input_tokens"], r["output_tokens"], r["yen"]), (100000, 20000, 12.8))
        self.assertIs(r["needs_confirm"], False)
        self.assertIs(r["price_known"], True)
        # キーワード引数でも同じ (仕様の引数名)
        self.assertEqual(self.est(input_chars=100000, n_calls=10, output_tokens_per_call=2000), r)

    def test_result_keys_and_types(self):
        r = self.est(100000, 10, 2000)
        self.assertEqual(set(r), KEYS)
        self.assertIs(type(r["input_tokens"]), int)
        self.assertIs(type(r["output_tokens"]), int)
        self.assertIsInstance(r["yen"], float)
        self.assertIs(type(r["needs_confirm"]), bool)
        self.assertIs(type(r["price_known"]), bool)

    def test_yen_equals_calc_api_cost_yen_of_the_estimated_tokens(self):
        rng = random.Random(20261004)
        for _ in range(25):
            chars, n, per = rng.randint(0, 3_000_000), rng.randint(0, 200), rng.randint(0, 8_000)
            for model in (None, LITE, "unknown-model"):
                r = self.est(chars, n, per, model)
                self.assertEqual(r["input_tokens"], chars)
                self.assertEqual(r["output_tokens"], n * per)
                self.assertEqual(r["yen"], oto().calc_api_cost_yen(chars, n * per, model))

    def test_needs_confirm_at_the_threshold(self):
        # flash の出力単価 2.50USD/100万tok × 160円 = 0.0004円/tok → 250,000 tok でちょうど 100 円
        self.assertEqual(oto().COST_CONFIRM_THRESHOLD_YEN, 100)
        at = self.est(0, 1, 250_000)
        self.assertEqual((at["yen"], at["needs_confirm"]), (100.0, True))                 # ちょうど = True
        below = self.est(0, 1, 249_975)
        self.assertEqual((below["yen"], below["needs_confirm"]), (99.99, False))          # 直前 = False
        above = self.est(0, 1, 250_025)
        self.assertEqual((above["yen"], above["needs_confirm"]), (100.01, True))
        # 回数×1回あたりの積で 250,000 になる組み合わせでも同じ
        for n, per in ((100, 2_500), (250, 1_000), (1_000, 250), (2, 125_000)):
            with self.subTest(n_calls=n, per_call=per):
                r = self.est(0, n, per)
                self.assertEqual((r["output_tokens"], r["yen"], r["needs_confirm"]), (250_000, 100.0, True))

    def test_needs_confirm_at_the_threshold_via_input_chars(self):
        # flash の入力単価 0.30USD/100万tok × 160円 = 0.000048円/tok (入力だけで 100 円は約 2,083,333 tok)
        low, high = self.est(2_083_000, 0, 0), self.est(2_084_000, 0, 0)
        self.assertEqual((low["yen"], low["needs_confirm"]), (99.98, False))
        self.assertEqual((high["yen"], high["needs_confirm"]), (100.03, True))

    def test_needs_confirm_is_judged_on_the_returned_yen(self):
        # 閾値付近の連続した値で「needs_confirm == (返した yen >= 閾値)」が常に成り立つこと (丸めの境目を含む)
        thr = oto().COST_CONFIRM_THRESHOLD_YEN
        for tokens in range(249_980, 250_021):
            r = self.est(0, 1, tokens)
            self.assertEqual(r["needs_confirm"], r["yen"] >= thr, f"output_tokens={tokens} yen={r['yen']}")
        for chars in range(2_083_200, 2_083_260):          # 入力だけの場合の丸めの境目 (約 2,083,230) をまたぐ
            r = self.est(chars, 0, 0)
            self.assertEqual(r["needs_confirm"], r["yen"] >= thr, f"input_chars={chars} yen={r['yen']}")

    def test_threshold_constant_is_read_and_comparison_is_inclusive(self):
        # スペックの例は 12.8 円。閾値を 12.8 にするとちょうど = True、12.81 なら False
        for thr, exp in ((10, True), (12.8, True), (12.81, False), (1000, False)):
            with self.subTest(threshold=thr):
                with mock.patch.object(oto(), "COST_CONFIRM_THRESHOLD_YEN", thr):
                    self.assertIs(self.est(100000, 10, 2000)["needs_confirm"], exp)

    def test_n_calls_zero_means_no_output(self):
        r = self.est(100000, 0, 2000)
        self.assertEqual((r["input_tokens"], r["output_tokens"], r["yen"], r["needs_confirm"]), (100000, 0, 4.8, False))
        r = self.est(0, 0, 10 ** 9)
        self.assertEqual((r["input_tokens"], r["output_tokens"], r["yen"], r["needs_confirm"]), (0, 0, 0.0, False))
        r = self.est(0, 0, 0)
        self.assertEqual((r["input_tokens"], r["output_tokens"], r["yen"], r["needs_confirm"]), (0, 0, 0.0, False))

    def test_negative_values_are_clamped_to_zero(self):
        cases = (
            ((-1000, 3, 2000), (0, 6000, 2.4)),
            ((1000, -3, 2000), (1000, 0, 0.05)),
            ((1000, 3, -2000), (1000, 0, 0.05)),
            ((-1, -1, -1), (0, 0, 0.0)),
        )
        for args, (it, ot, yen) in cases:
            with self.subTest(args=args):
                r = self.est(*args)
                self.assertEqual((r["input_tokens"], r["output_tokens"], r["yen"]), (it, ot, yen))
                self.assertIs(r["needs_confirm"], False)

    def test_decimals_are_truncated(self):
        r = self.est(1234.9, 2.9, 2000)             # int(1234.9)=1234 / int(2.9)=2 回 × 2000
        self.assertEqual((r["input_tokens"], r["output_tokens"], r["yen"]), (1234, 4000, 1.66))
        self.assertEqual(self.est(0, 3, 1.5)["output_tokens"], 4)    # int(1.5 * 3) = 4

    def test_tokens_per_char_constant_is_applied(self):
        self.assertEqual(self.est(777, 0, 0)["input_tokens"], 777)          # 既定 1.0
        with mock.patch.object(oto(), "ESTIMATE_TOKENS_PER_CHAR", 0.5):
            self.assertEqual(self.est(1001, 0, 0)["input_tokens"], 500)     # int(500.5)
        with mock.patch.object(oto(), "ESTIMATE_TOKENS_PER_CHAR", 2.0):
            self.assertEqual(self.est(1000, 0, 0)["input_tokens"], 2000)

    def test_model_argument_and_price_known(self):
        cases = (
            (None, 448.0, True), (FLASH, 448.0, True), (LITE, 80.0, True), (PRO, 1800.0, True),
            ("unknown-model", 1800.0, False),        # 仕様(変更後): 未登録モデルは表の最大単価 (1.25 / 10.00)
        )
        for model, yen, known in cases:
            with self.subTest(model=model):
                r = self.est(1_000_000, 1, 1_000_000, model)
                self.assertEqual(r["yen"], yen)
                self.assertIs(r["price_known"], known)
        write_config({"gemini_model": "unknown-x"})
        self.assertIs(self.est(1000, 1, 1000)["price_known"], False)       # model=None → config のモデル
        write_config({"gemini_model": LITE})
        self.assertEqual(self.est(1_000_000, 1, 1_000_000)["yen"], 80.0)

    def test_config_and_broken_config(self):
        write_config({"usd_jpy": 150})
        self.assertEqual(self.est(100000, 10, 2000)["yen"], 12.0)
        write_config("{broken")
        r = self.est(100000, 10, 2000)
        self.assertEqual((r["yen"], r["needs_confirm"]), (12.8, False))

    def test_a_large_job_needs_confirmation(self):
        r = self.est(3_000_000, 50, 4000)           # 入力 3M tok + 出力 200k tok = 0.9+0.5 USD
        self.assertEqual((r["input_tokens"], r["output_tokens"], r["yen"]), (3_000_000, 200_000, 224.0))
        self.assertIs(r["needs_confirm"], True)


# ============================================================
# 3-b. estimate_ai_cost_yen_multi (新規: 複数段の見積り)
# ============================================================
MULTI_KEYS = KEYS | {"n_calls"}


def stage(chars=0, n=1, per=0, model=None):
    return {"input_chars": chars, "n_calls": n, "output_tokens_per_call": per, "model": model}


class TestEstimateAiCostYenMulti(InTempCwd):
    def multi(self, stages):
        return oto().estimate_ai_cost_yen_multi(stages)

    def test_two_stages_of_99_yen_need_confirmation_in_total(self):
        # 1段 = 99 円 (flash の出力 247,500 tok)。1段だけなら確認不要だが、2段の合計 198 円は要確認
        one = oto().estimate_ai_cost_yen(0, 1, 247_500)
        self.assertEqual((one["yen"], one["needs_confirm"]), (99.0, False))
        r = self.multi([stage(0, 1, 247_500), stage(0, 1, 247_500)])
        self.assertEqual((r["yen"], r["needs_confirm"]), (198.0, True))
        self.assertEqual((r["input_tokens"], r["output_tokens"], r["n_calls"]), (0, 495_000, 2))
        self.assertIs(r["price_known"], True)

    def test_total_is_judged_against_the_threshold_even_if_every_stage_is_below(self):
        r = self.multi([stage(0, 1, 150_000)] * 2)                  # 60 + 60 (各段は False)
        self.assertEqual((r["yen"], r["needs_confirm"]), (120.0, True))
        # 境界: 50 + 50 = 100 (ちょうど = True) / 50 + 49.99 = 99.99 (False)
        r = self.multi([stage(0, 1, 125_000), stage(0, 1, 125_000)])
        self.assertEqual((r["yen"], r["needs_confirm"]), (100.0, True))
        r = self.multi([stage(0, 1, 125_000), stage(0, 1, 124_975)])
        self.assertEqual((r["yen"], r["needs_confirm"]), (99.99, False))

    def test_empty_or_none_stages_give_zeros(self):
        for stages in (None, [], ()):
            with self.subTest(stages=stages):
                r = self.multi(stages)
                self.assertEqual(set(r), MULTI_KEYS)
                self.assertEqual((r["input_tokens"], r["output_tokens"], r["yen"], r["n_calls"]), (0, 0, 0.0, 0))
                self.assertIs(r["needs_confirm"], False)
                self.assertIs(r["price_known"], True)

    def test_result_keys_and_types(self):
        r = self.multi([stage(100000, 10, 2000)])
        self.assertEqual(set(r), MULTI_KEYS)
        self.assertIs(type(r["input_tokens"]), int)
        self.assertIs(type(r["output_tokens"]), int)
        self.assertIsInstance(r["yen"], float)
        self.assertIs(type(r["needs_confirm"]), bool)
        self.assertIs(type(r["price_known"]), bool)
        self.assertIs(type(r["n_calls"]), int)

    def test_a_single_stage_equals_estimate_ai_cost_yen(self):
        for args in ((100000, 10, 2000, None), (1_000_000, 1, 1_000_000, LITE), (500, 3, 100, "unknown-model")):
            with self.subTest(args=args):
                single, multi = oto().estimate_ai_cost_yen(*args), self.multi([stage(*args)])
                for k in ("input_tokens", "output_tokens", "yen", "needs_confirm", "price_known"):
                    self.assertEqual(multi[k], single[k], k)
                self.assertEqual(multi["n_calls"], args[1])

    def test_each_stage_is_priced_with_its_own_model_and_summed(self):
        r = self.multi([stage(1_000_000, 1, 1_000_000, LITE), stage(1_000_000, 1, 1_000_000, FLASH)])
        self.assertEqual(r["yen"], 528.0)                                            # 80 + 448
        self.assertEqual((r["input_tokens"], r["output_tokens"], r["n_calls"]), (2_000_000, 2_000_000, 2))
        r = self.multi([stage(100000, 10, 2000), stage(50000, 4, 1000), stage(0, 25, 100)])
        self.assertEqual(r["n_calls"], 39)
        self.assertEqual((r["input_tokens"], r["output_tokens"]), (150000, 20000 + 4000 + 2500))

    def test_total_is_the_sum_of_the_stage_yens_rounded_to_two_decimals(self):
        # 仕様: 段ごとに estimate_ai_cost_yen で見積もった yen を合算 (小数2桁に丸め)。
        # 入力 1010 tok の段は 0.04848 -> 0.05 円 (丸め後)。10段で 0.5 円 (全トークンをまとめて見積もると 0.48 円になる)
        r = self.multi([stage(1010, 0, 0)] * 10)
        self.assertEqual(r["yen"], 0.5)
        self.assertEqual(oto().calc_api_cost_yen(10100, 0), 0.48)

    def test_price_known_is_the_logical_and_over_the_stages(self):
        cases = (([FLASH, LITE], True), ([FLASH, "unknown-model"], False), (["unknown-model"], False),
                 (["unknown-model", FLASH, LITE], False), ([None, PRO], True), ([None], True))
        for models, exp in cases:
            with self.subTest(models=models):
                r = self.multi([stage(1000, 1, 100, m) for m in models])
                self.assertIs(r["price_known"], exp)

    def test_unknown_model_stage_uses_the_highest_prices(self):
        r = self.multi([stage(1_000_000, 1, 1_000_000, "gemini-9")])
        self.assertEqual((r["yen"], r["needs_confirm"], r["price_known"]), (1800.0, True, False))

    def test_negative_values_in_a_stage_are_clamped_like_estimate_ai_cost_yen(self):
        r = self.multi([stage(-1000, 3, 2000), stage(1000, -3, 2000)])
        self.assertEqual((r["input_tokens"], r["output_tokens"], r["yen"]), (1000, 6000, 2.45))   # 2.4 + 0.05

    def test_threshold_constant_is_read_and_comparison_is_inclusive(self):
        stages = [stage(100000, 10, 2000)] * 2                     # 12.8 + 12.8 = 25.6
        for thr, exp in ((10, True), (25.6, True), (25.61, False), (1000, False)):
            with self.subTest(threshold=thr):
                with mock.patch.object(oto(), "COST_CONFIRM_THRESHOLD_YEN", thr):
                    self.assertIs(self.multi(stages)["needs_confirm"], exp)

    def test_config_applies_to_every_stage(self):
        write_config({"usd_jpy": 150})
        self.assertEqual(self.multi([stage(100000, 10, 2000)] * 2)["yen"], 24.0)         # 12.0 + 12.0
        write_config("{broken")
        self.assertEqual(self.multi([stage(100000, 10, 2000)] * 2)["yen"], 25.6)


class TestSpecGapEstimateAiCostYenMulti(InTempCwd):
    def test_stage_without_a_model_key_uses_the_default_model(self):
        # 解釈: stage の "model" は省略可 (省略/None なら config の既定モデル)。仕様はキーを4つ列挙するだけで必須かは不明
        r = oto().estimate_ai_cost_yen_multi([{"input_chars": 100000, "n_calls": 10, "output_tokens_per_call": 2000}])
        self.assertEqual((r["yen"], r["price_known"], r["n_calls"]), (12.8, True, 10))


# ============================================================
# 4. 6か所の置換 (HTMLReportGenerator)
# ============================================================
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


COST_VARS = ("in_cost", "out_cost", "total_yen")
OLD_NUMBERS = {0.075, 0.3, 160, 1000000}


def cost_assigns(fn):
    return [n for n in ast.walk(fn)
            if isinstance(n, ast.Assign) and len(n.targets) == 1
            and isinstance(n.targets[0], ast.Name) and n.targets[0].id in COST_VARS]


def numeric_constants(fn):
    return {n.value for n in ast.walk(fn)
            if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool)}


def code_text(src):
    """コメントだけの行を除いたソース (コメントに旧単価の説明が残っていても誤検知しない)。"""
    return "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))


def report_source(name):
    return inspect.getsource(getattr(oto().HTMLReportGenerator, name))


class TestSixReplacementsInSource(unittest.TestCase):
    def test_no_hardcoded_old_pricing_in_source_text(self):
        for name in SIX_REPORTS:
            with self.subTest(method=name):
                code = code_text(report_source(name))
                self.assertNotRegex(code, r"0\.075")
                self.assertNotRegex(code, r"\*\s*160\b")
                self.assertNotIn("in_cost", code)
                self.assertNotIn("out_cost", code)

    def test_no_old_numeric_constants_in_the_method_ast(self):
        # 旧版では 0.075 / 0.3 / 160 / 1000000 はこの3行にしか出てこない (_01 で確認済み)
        for name in SIX_REPORTS:
            with self.subTest(method=name):
                fn = method_node(_loader.target_path(), "HTMLReportGenerator", name)
                self.assertEqual(numeric_constants(fn) & OLD_NUMBERS, set())

    def test_total_yen_is_one_call_to_calc_api_cost_yen(self):
        expected = ast.dump(ast.parse("total_yen = calc_api_cost_yen(total_input, total_output)").body[0])
        for name in SIX_REPORTS:
            with self.subTest(method=name):
                code = code_text(report_source(name))
                self.assertEqual(code.count("calc_api_cost_yen("), 1)
                fn = method_node(_loader.target_path(), "HTMLReportGenerator", name)
                assigns = cost_assigns(fn)
                self.assertEqual([ast.dump(a) for a in assigns], [expected],
                                 "in_cost/out_cost/total_yen への代入は total_yen = calc_api_cost_yen(...) の1行だけのはず")

    def test_display_strings_are_unchanged(self):
        for name in SIX_REPORTS:
            with self.subTest(method=name):
                src = report_source(name)
                self.assertIn(COST_LINE, src)
                self.assertIn(REFORMAT_LINE, src)

    def test_cost_display_appends_api_cost_note(self):
        # 仕様(変更後): …円 (In:{total_input} / Out:{total_output}){api_cost_note()}
        for name in SIX_REPORTS:
            with self.subTest(method=name):
                self.assertIn(COST_LINE + "{api_cost_note()}", report_source(name))

    def test_cost_text_is_not_hardcoded_a_second_time(self):
        # 仕様(変更後): generate_staff_report の末尾の費用表示も cost_display を使う (旧はコスト文言を直書きしていた)
        for name in SIX_REPORTS:
            with self.subTest(method=name):
                self.assertEqual(code_text(report_source(name)).count("💰 APIコスト概算"), 1)


# ---- 実際にHTMLを出力して確認する -----------------------------------------------------------
REPORT_CALLS = {
    "generate_project_report": lambda g, ti, to, rf: g.generate_project_report(
        "P", {}, {}, {}, "d", "date_desc", ti, to, "adopted", rf),
    "generate_staff_report": lambda g, ti, to, rf: g.generate_staff_report(
        "S", {}, {}, {}, "d", "date_desc", ti, to, "adopted", rf),
    "generate_cockpit_report": lambda g, ti, to, rf: g.generate_cockpit_report({}, {}, ti, to, rf),
    "generate_cockpit_v2_report": lambda g, ti, to, rf: g.generate_cockpit_v2_report({}, ti, to, rf),
    "generate_review_report": lambda g, ti, to, rf: g.generate_review_report({}, "p", ti, to, rf),
    "generate_action_dashboard_report": lambda g, ti, to, rf: g.generate_action_dashboard_report([], "d", ti, to, rf),
}


class TestSixReportsRenderTheNewCost(InTempCwd):
    def render(self, name, total_input, total_output, reformat=False):
        gen = oto().HTMLReportGenerator(os.path.join(self.tmp, "out"), 8765)
        path = REPORT_CALLS[name](gen, total_input, total_output, reformat)
        self.assertTrue(path, f"{name}: HTML が出力されなかった (空のパスが返った)")
        self.assertTrue(os.path.isfile(path), f"{name}: 返ったパスにファイルが無い: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def test_one_million_each_shows_448_yen_not_the_old_60(self):
        for name in SIX_REPORTS:
            with self.subTest(method=name):
                html = self.render(name, 1_000_000, 1_000_000)
                self.assertIn("💰 APIコスト概算: 約 448.0 円 (In:1000000 / Out:1000000)", html)
                self.assertNotIn("約 60.0 円", html)
                self.assertNotIn("※単価未登録", html)            # 既定モデル(flash)は単価表にあるので注記は出ない

    def test_input_and_output_are_not_swapped(self):
        for name in SIX_REPORTS:
            with self.subTest(method=name):
                html = self.render(name, 2_000_000, 500_000)
                self.assertIn("💰 APIコスト概算: 約 296.0 円 (In:2000000 / Out:500000)", html)

    def test_zero_tokens_show_zero_yen(self):
        for name in SIX_REPORTS:
            with self.subTest(method=name):
                self.assertIn("💰 APIコスト概算: 約 0.0 円 (In:0 / Out:0)", self.render(name, 0, 0))

    def test_reformat_mode_shows_no_cost(self):
        # 仕様(変更後): generate_staff_report の末尾も cost_display を使うので、staff も reformat_mode では
        # 「🎨 フォーマット再生成のみ（APIコスト無し）」になる (旧は reformat でも費用を直書きしていた)
        for name in SIX_REPORTS:
            with self.subTest(method=name):
                html = self.render(name, 1_000_000, 1_000_000, reformat=True)
                self.assertIn(REFORMAT_LINE, html)
                self.assertNotIn("APIコスト概算: 約", html)

    def test_unknown_default_model_shows_the_high_price_and_the_note(self):
        # 仕様(変更後): 既定モデルが単価表に無い -> 最大単価 (1800.0) で計算し、注記を末尾に付ける
        write_config({"gemini_model": "gemini-9"})
        for name in SIX_REPORTS:
            with self.subTest(method=name):
                html = self.render(name, 1_000_000, 1_000_000)
                self.assertIn("💰 APIコスト概算: 約 1800.0 円 (In:1000000 / Out:1000000)" + NOTE, html)

    def test_reformat_mode_has_no_note_even_for_an_unknown_model(self):
        write_config({"gemini_model": "gemini-9"})
        for name in SIX_REPORTS:
            with self.subTest(method=name):
                html = self.render(name, 1_000_000, 1_000_000, reformat=True)
                self.assertIn(REFORMAT_LINE, html)
                self.assertNotIn("※単価未登録", html)
                self.assertNotIn("APIコスト概算: 約", html)

    def test_report_follows_config_model_and_fx(self):
        cases = (({"gemini_model": LITE}, "80.0"), ({"gemini_model": PRO}, "1800.0"), ({"usd_jpy": 150}, "420.0"),
                 ({"gemini_model": LITE, "usd_jpy": 150}, "75.0"), ("{broken", "448.0"))
        for cfg, yen in cases:
            for name in SIX_REPORTS:
                with self.subTest(config=cfg, method=name):
                    write_config(cfg)
                    html = self.render(name, 1_000_000, 1_000_000)
                    self.assertIn(f"💰 APIコスト概算: 約 {yen} 円 (In:1000000 / Out:1000000)", html)
                    self.assertNotIn("※単価未登録", html)


# ============================================================
# 5. 範囲ガード (_01 → _02 で変えてよいのは許可リストだけ)
# ============================================================
OLD_REV = "outlook_total_organizer_20261004_01.py"
NEW_REV = "outlook_total_organizer_20261004_02.py"
# B1 (仕様変更後): 費用表示を「今回の実行分」にするため、この5つの入口メソッドに累計リセットの2行を足す
ENTRY_METHODS = ("_refresh_cockpit", "_sync_and_refresh_cockpit", "_run_cockpit_v2", "_run_action_dashboard", "_run_review")
RESET_LINES = ("self.summarizer.total_input_tokens = 0", "self.summarizer.total_output_tokens = 0")
# A7c fix1: 費用の確認がある入口と、その最初のAI呼び出し (リセットは確認の後・この呼び出しの前)
RESET_AFTER_CONFIRM = {"_sync_and_refresh_cockpit": "summarize_project_threads",
                       "_run_cockpit_v2": "generate_cockpit_v2_data",
                       "_run_action_dashboard": "summarize_action_dashboard",
                       "_run_review": "generate_review_data"}
ALLOWED_TO_CHANGE = ({"_CommonUsageMetadata.__init__"} | {f"HTMLReportGenerator.{n}" for n in SIX_REPORTS}
                     | {f"MailManagerGUI.{n}" for n in ENTRY_METHODS})
NEW_CONSTANTS = ("GEMINI_PRICES_USD_PER_1M", "GEMINI_PRICE_FALLBACK_MODEL", "COST_CONFIRM_THRESHOLD_YEN",
                 "ESTIMATE_TOKENS_PER_CHAR")
NEW_FUNCTIONS = ("_as_token_count", "_cost_settings", "get_gemini_price", "calc_api_cost_yen", "estimate_ai_cost_yen",
                 "_normalize_model_name", "api_cost_note", "estimate_ai_cost_yen_multi")


def _is_docstring(node):
    return (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str))


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


class _DropCostAssigns(ast.NodeTransformer):
    """in_cost / out_cost / total_yen への代入文だけを取り除く (旧3行 → 新1行 の差を打ち消すため)。"""

    def visit_Assign(self, node):
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id in COST_VARS:
            return None
        return self.generic_visit(node)


class _DropApiCostNote(ast.NodeTransformer):
    """f-string の中の {api_cost_note(...)} を取り除く (cost_display への注記追加の差を打ち消すため)。"""

    @staticmethod
    def _is_note(v):
        return (isinstance(v, ast.FormattedValue) and isinstance(v.value, ast.Call)
                and isinstance(v.value.func, ast.Name) and v.value.func.id == "api_cost_note")

    def visit_JoinedStr(self, node):
        node.values = [v for v in node.values if not self._is_note(v)]
        return self.generic_visit(node)


STAFF_OLD_FOOTER = "💰 APIコスト概算: 約 {total_yen} 円 (In:{total_input} / Out:{total_output})"


def normalized_report_text(fn, old_staff=False):
    """6つのレポートの比較用テキスト: コスト3行(→1行)の代入と {api_cost_note()} を取り除いて unparse する。
    old_staff=True (旧版の generate_staff_report) は、末尾の費用表示の直書き (最後の出現) を {cost_display} に置き換える
    (仕様変更後は staff も cost_display を使う)。"""
    node = _DropApiCostNote().visit(_DropCostAssigns().visit(copy.deepcopy(fn)))
    text = ast.unparse(node)
    if old_staff:
        assert text.count(STAFF_OLD_FOOTER) >= 2, "比較元(旧)の staff に末尾の費用表示の直書きが見つからない"
        head, _, tail = text.rpartition(STAFF_OLD_FOOTER)
        text = head + "{cost_display}" + tail
    return text


def short_diff(a, b, limit=24):
    lines = list(difflib.unified_diff(a.splitlines(), b.splitlines(), "old", "new", lineterm="", n=0))
    return "\n".join(lines[:limit])


class TestScopeGuardA2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.target = os.path.join(_loader.TOOL_DIR, NEW_REV)
        cls.baseline = os.path.join(_loader.TOOL_DIR, OLD_REV)
        if not (os.path.isfile(cls.target) and os.path.isfile(cls.baseline)):
            raise unittest.SkipTest("A2のリビジョン対(20261004_01 / 20261004_02)が無い")
        cls.old = _index_source(cls.baseline)
        cls.new = _index_source(cls.target)

    def test_no_existing_function_or_method_is_removed(self):
        removed = sorted(n for n in self.old[0] if n not in self.new[0])
        self.assertEqual(removed, [], f"既存の関数/メソッドが消えている: {removed}")

    def test_only_allowed_functions_changed(self):
        old_f, new_f = self.old[0], self.new[0]
        changed = sorted(n for n, s in old_f.items() if n in new_f and new_f[n] != s and n not in ALLOWED_TO_CHANGE)
        self.assertEqual(changed, [], f"仕様で許可されていない既存関数/メソッドの変更: {changed}")

    def test_allowed_functions_were_actually_changed(self):
        old_f, new_f = self.old[0], self.new[0]
        unchanged = sorted(n for n in ALLOWED_TO_CHANGE if n in old_f and n in new_f and old_f[n] == new_f[n])
        self.assertEqual(unchanged, [], f"A2 で変更するはずの関数が変更されていない: {unchanged}")

    def test_existing_constants_are_unchanged(self):
        old_c, new_c = self.old[1], self.new[1]
        removed = sorted(n for n in old_c if n not in new_c)
        changed = sorted(n for n, s in old_c.items() if n in new_c and new_c[n] != s)
        self.assertEqual(removed, [], f"既存の定数が消えている: {removed}")
        self.assertEqual(changed, [], f"既存の定数が変更されている: {changed}")

    def test_existing_imports_are_kept(self):
        missing = self.old[2] - self.new[2]
        self.assertEqual(len(missing), 0, f"既存の import が {len(missing)} 件消えている")

    def test_other_top_level_statements_and_class_skeletons_are_unchanged(self):
        self.assertEqual(self.old[3], self.new[3], "関数/定数/import 以外のトップレベル文が変わっている")
        for cls_name, shell in self.old[4].items():
            with self.subTest(cls=cls_name):
                self.assertIn(cls_name, self.new[4])
                self.assertEqual(shell, self.new[4].get(cls_name), f"クラス {cls_name} の骨格(継承・デコレータ・クラス直下の文)が変わっている")

    def test_new_names_are_added_at_module_level(self):
        for n in NEW_FUNCTIONS:
            with self.subTest(function=n):
                self.assertIn(n, self.new[0])
                self.assertNotIn(n, self.old[0])
        for n in NEW_CONSTANTS:
            with self.subTest(constant=n):
                self.assertIn(n, self.new[1])
                self.assertNotIn(n, self.old[1])

    def test_each_of_the_six_reports_changed_only_in_the_cost_lines(self):
        # 許可される変更: 「3行→1行の置換」「cost_display への {api_cost_note()} 追加」「staff の末尾の費用表示を cost_display へ」
        for name in SIX_REPORTS:
            with self.subTest(method=name):
                old_fn = method_node(self.baseline, "HTMLReportGenerator", name)
                new_fn = method_node(self.target, "HTMLReportGenerator", name)
                # 比較元の健全性: 旧版には in_cost / out_cost / total_yen の3行があった
                self.assertEqual(sorted(a.targets[0].id for a in cost_assigns(old_fn)), ["in_cost", "out_cost", "total_yen"])
                old_text = normalized_report_text(old_fn, old_staff=(name == "generate_staff_report"))
                new_text = normalized_report_text(new_fn)
                self.assertEqual(old_text, new_text,
                                 f"{name}: 許可された変更以外の箇所が変更されている\n{short_diff(old_text, new_text)}")

    def test_each_entry_method_changed_only_by_the_two_reset_lines(self):
        # B1: 許可される変更は「累計リセット2行の追加のみ」(削除・置換は不可)
        for name in ENTRY_METHODS:
            with self.subTest(method=name):
                old = ast.unparse(method_node(self.baseline, "MailManagerGUI", name)).splitlines()
                new = ast.unparse(method_node(self.target, "MailManagerGUI", name)).splitlines()
                ops = difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes()
                changes = [(tag, old[i1:i2], new[j1:j2]) for tag, i1, i2, j1, j2 in ops if tag != "equal"]
                self.assertEqual([c for c in changes if c[0] != "insert"], [], "追加以外の変更 (削除・置換) がある")
                self.assertEqual(sorted(ln.strip() for _, _, added in changes for ln in added), sorted(RESET_LINES),
                                 "追加された行が累計リセットの2行だけになっていない")


# ============================================================
# 6. 旧単価 (0.075 / 0.3) との回帰
# ============================================================
def old_yen(total_input, total_output):
    """A2 以前の各レポートの計算 (直書きの 0.075 / 0.3 / 160)。"""
    in_cost = (total_input / 1000000) * 0.075 * 160
    out_cost = (total_output / 1000000) * 0.3 * 160
    return round(in_cost + out_cost, 2)


class TestRegressionAgainstOldPricing(InTempCwd):
    def test_one_million_each_was_60_and_is_now_448(self):
        self.assertEqual(old_yen(1_000_000, 1_000_000), 60.0)
        self.assertEqual(oto().calc_api_cost_yen(1_000_000, 1_000_000), 448.0)

    def test_new_cost_differs_from_and_exceeds_the_old_one_for_the_same_tokens(self):
        for i, o in ((1000, 1000), (10_000, 5_000), (100_000, 100_000), (1_000_000, 0), (0, 1_000_000),
                     (1_000_000, 1_000_000), (5_000_000, 2_000_000), (123_456, 78_901)):
            with self.subTest(input=i, output=o):
                new, old = oto().calc_api_cost_yen(i, o), old_yen(i, o)
                self.assertNotEqual(new, old)
                self.assertGreater(new, old)

    def test_per_direction_ratio(self):
        # 入力は 0.075 → 0.30 (4倍)、出力は 0.30 → 2.50 (約8.3倍)
        self.assertEqual((old_yen(1_000_000, 0), oto().calc_api_cost_yen(1_000_000, 0)), (12.0, 48.0))
        self.assertEqual((old_yen(0, 1_000_000), oto().calc_api_cost_yen(0, 1_000_000)), (48.0, 400.0))

    def test_flash_lite_is_also_above_the_old_cost(self):
        for i, o in ((1_000_000, 1_000_000), (1_000_000, 0), (0, 1_000_000)):
            with self.subTest(input=i, output=o):
                self.assertGreater(oto().calc_api_cost_yen(i, o, LITE), old_yen(i, o))

    def test_legacy_price_constants_are_not_used_by_the_new_calculation(self):
        with mock.patch.object(oto(), "PRICE_INPUT_1M_USD", 99.0), mock.patch.object(oto(), "PRICE_OUTPUT_1M_USD", 99.0):
            self.assertEqual(oto().calc_api_cost_yen(1_000_000, 1_000_000), 448.0)
            self.assertEqual(oto().estimate_ai_cost_yen(100000, 10, 2000)["yen"], 12.8)


# ============================================================
# 7. B1: 費用表示を「今回の実行分」にする (累計トークンのリセット)
# ============================================================
def start_timer_statements(fn):
    """fn の中の self._set_status(..., start_timer=True) の文を (所属する文リスト, 位置) で返す。"""
    found = []
    for node in ast.walk(fn):
        lists = [getattr(node, f) for f in ("body", "orelse", "finalbody") if isinstance(getattr(node, f, None), list)]
        lists += [h.body for h in (getattr(node, "handlers", None) or [])]
        for lst in lists:
            for i, s in enumerate(lst):
                call = s.value if isinstance(s, ast.Expr) and isinstance(s.value, ast.Call) else None
                if (call is not None and isinstance(call.func, ast.Attribute) and call.func.attr == "_set_status"
                        and isinstance(call.func.value, ast.Name) and call.func.value.id == "self"
                        and any(k.arg == "start_timer" and isinstance(k.value, ast.Constant) and k.value.value is True
                                for k in call.keywords)):
                    found.append((lst, i))
    return found


class TestTokenTotalsAreResetAtStart(unittest.TestCase):
    def test_reset_lines_are_in_the_source_of_the_five_entry_methods(self):
        for name in ENTRY_METHODS:
            with self.subTest(method=name):
                src = inspect.getsource(getattr(oto().MailManagerGUI, name))
                for line in RESET_LINES:
                    self.assertIn(line, src)

    def test_reset_lines_directly_follow_the_start_timer_status_call(self):
        # 仕様: 開始時の self._set_status(..., start_timer=True) の直後に、累計 (入力/出力) を 0 に戻す2行
        # (A7c fix1 で、費用の確認がある4つの入口はリセットを確認の後へ移した。確認の無い _refresh_cockpit だけが開始時のまま)
        for name in [n for n in ENTRY_METHODS if n not in RESET_AFTER_CONFIRM]:
            with self.subTest(method=name):
                fn = method_node(_loader.target_path(), "MailManagerGUI", name)
                found = start_timer_statements(fn)
                self.assertTrue(found, "self._set_status(..., start_timer=True) の文が見つからない")
                for lst, i in found:
                    following = [ast.unparse(s) for s in lst[i + 1:i + 3]]
                    self.assertEqual(sorted(following), sorted(RESET_LINES),
                                     f"start_timer=True の直後の2文が累計リセットになっていない: {following}")

    def test_reset_lines_sit_after_the_cost_confirmation_and_before_the_first_ai_call(self):
        # A7c fix1: 費用の確認がある4つの入口は、累計リセットの2行が「_confirm_ai_cost の呼び出しより後・最初のAI呼び出しより前」
        # にだけあり (2行は連続)、開始時 (start_timer=True の直後) には無い (確認で中止しても、他の画面の集計を0にしないため)
        for name, first_ai in RESET_AFTER_CONFIRM.items():
            with self.subTest(method=name):
                fn = method_node(_loader.target_path(), "MailManagerGUI", name)
                for lst, i in start_timer_statements(fn):
                    following = [ast.unparse(s) for s in lst[i + 1:i + 3]]
                    self.assertFalse(set(following) & set(RESET_LINES), f"開始時にリセットしている: {following}")
                pos = lambda n: (n.lineno, n.col_offset)                          # noqa: E731
                calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
                confirms = [pos(n) for n in calls if n.func.attr == "_confirm_ai_cost"]
                ai_calls = [pos(n) for n in calls if n.func.attr == first_ai]
                self.assertTrue(confirms, "_confirm_ai_cost の呼び出しが無い")
                self.assertTrue(ai_calls, f"{first_ai} の呼び出しが無い")
                resets = []
                for node in ast.walk(fn):
                    for f in ("body", "orelse", "finalbody"):
                        lst = getattr(node, f, None)
                        if isinstance(lst, list):
                            resets += [(lst, j) for j, st in enumerate(lst) if ast.unparse(st) in RESET_LINES]
                self.assertEqual(len(resets), 2, f"リセットの文が2つ (入力・出力) でない: {len(resets)}")
                (lst_a, ja), (lst_b, jb) = sorted(resets, key=lambda r: pos(r[0][r[1]]))
                self.assertTrue(lst_a is lst_b and jb == ja + 1, "リセットの2行が連続していない")
                self.assertEqual(sorted(ast.unparse(lst_a[j]) for j in (ja, jb)), sorted(RESET_LINES))
                self.assertGreater(pos(lst_a[ja]), max(confirms), "リセットが費用の確認より前にある")
                self.assertLess(pos(lst_b[jb]), min(ai_calls), f"リセットが最初のAI呼び出し ({first_ai}) より後にある")


class _TokenAddingSummarizer(a1gui.StubSummarizer):
    """解析の中でトークンを加算するスタブ (= 今回の実行分のトークン)。"""

    def summarize_action_dashboard(self, *args, **kwargs):
        self.total_input_tokens += 100
        self.total_output_tokens += 50
        return super().summarize_action_dashboard(*args, **kwargs)


class _TokenRecordingReporter(a1gui.StubReporter):
    def generate_action_dashboard_report(self, action_cards, date_range, total_input, total_output,
                                         reformat_mode=False, search_days=7):
        self.calls.append({"total_input": total_input, "total_output": total_output})
        return None


class TestRunActionDashboardResetsTotals(a1gui.GuiCase):
    """機能テスト: _run_action_dashboard を実際に動かし、レポートへ渡る累計が「今回の実行分」だけになること。"""

    def run_once(self, gui):
        refreshes = []
        gui._refresh_action_decision_view = lambda: refreshes.append(1)
        gui._run_action_dashboard()
        ok = self.pump(lambda: str(gui.btn_run_action.cget("state")) == "normal" and bool(refreshes), timeout=10)
        self.assertTrue(ok, "生成処理が完了しない")
        self.settle(0.2)

    def test_displayed_totals_cover_only_this_run(self):
        gui = self.make_gui(select_action=True)
        gui.summarizer = _TokenAddingSummarizer()
        gui.summarizer.total_input_tokens = 777_000          # 前回までの累計が残っている状態
        gui.summarizer.total_output_tokens = 555_000
        gui.reporter = _TokenRecordingReporter()
        self.run_once(gui)
        self.run_once(gui)                                   # 2回続けて実行しても累計にならない
        self.assertEqual([(c["total_input"], c["total_output"]) for c in gui.reporter.calls], [(100, 50), (100, 50)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
