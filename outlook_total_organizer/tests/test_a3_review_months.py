# -*- coding: utf-8 -*-
"""A3「振り返りタブの月範囲」テスト (仕様書 A3_SPEC.md + 敵対的レビュー第1回後の変更点 A3_SPEC_DELTA_fix1.md)。

仕様書だけを根拠に、実装 (_20261004_03.py の新規・変更部分) を見ずに書いている。
  - 仕様に明記された挙動            -> 通常の TestCase
  - 仕様が曖昧/未記載で「最も自然な解釈」で書いたもの
                                    -> クラス名に SpecGap を含む (コメントに解釈を明記)
    SpecGap の失敗は「バグ」ではなく「仕様の確認が必要」の合図として扱う。

仕様変更 (A3_SPEC_DELTA_fix1.md / fix2) への追随 (fix2 では、_run_review/_reformat_review の期間表示が合算+対象者ごとになり、
format_review_period_label の呼び出しが複数になった): 四半期ボタン名 (範囲の端で3か月に満たない四半期は
"2025年Q4(11-12月)" / "2026年Q4(10月)" のように含まれる月を括弧で付ける) と、範囲ガードの
「追加してよい名前」(review_cache_gaps / _review_month_list_text)。
review_cache_gaps・期間表示の「未取得/AI失敗」・_run_review/_reformat_review の機能テスト・窓幅630pxの
要求幅などの新規分は tests/test_a3_review_run.py にある。

構成
  1. review_month_range / REVIEW_WINDOW_MONTHS
  2. review_yyyymm / review_default_selected
  3. review_quarter_choices
  4. review_ym_sort_key
  5. format_review_period_label
  6. 月別タイムラインの並び (HTMLReportGenerator.generate_review_report。旧版 _02 では崩れることも確認)
  7. GUI (MailManagerGUI._ui_review_tab ほか)。tkinter とディスプレイが無ければ自動 skip
     Linux では  xvfb-run -a /usr/bin/python3.12 tests/run_tests.py  で実行できる
  8. 範囲ガード (_20261004_02.py と _20261004_03.py の AST 比較。変更してよいのは許可リストだけ)

「今日」に依存する期待値は、(a) 固定日付を引数 / モンキーパッチで与える、(b) このファイル内の独立した
参照実装 (ref_range など) で実際の現在日付から計算する、のどちらかで作る (日付が変わってもテストが壊れない)。
Outlook(COM)・AI・ネットワークには一切触れない (GUI テストでは outlook 等に「触ったら失敗」するスタブを置く)。
"""
import ast
import calendar
import copy
import functools
import gc
import importlib.util
import itertools
import os
import random
import re
import sys
import unittest
from datetime import date, datetime
from unittest import mock

import _loader
from _loader import tempdir_cwd

try:
    import tkinter as tk
    from tkinter import ttk
    import tkinter.messagebox as tkmessagebox
    _TK_IMPORT_ERROR = None
except Exception as _e:                                    # pragma: no cover
    tk = ttk = tkmessagebox = None
    _TK_IMPORT_ERROR = _e


def oto():
    return _loader.load()


# ============================================================
# 共通: 固定日付 / 独立した参照実装 / 記号
# ============================================================
NOW_1004 = datetime(2026, 10, 4, 12, 0, 0)       # 実行日 (2026-10-04): 範囲は 2025-11〜2026-10
NOW_0115 = datetime(2026, 1, 15, 9, 30, 0)       # 1月: 前月は前年12月 / 範囲は 2025-02〜2026-01
NOW_1231 = datetime(2026, 12, 31, 23, 59, 59)    # 年末: 範囲は 2026-01〜2026-12 (年またぎ無し)
NOW_0301 = datetime(2027, 3, 1, 0, 0, 0)         # 月初の3月: 前月は2月 / 範囲は 2026-04〜2027-03

WAVE = "〜"      # 〜 (波ダッシュ)
LPAR = "（"      # （
RPAR = "）"      # ）
COMMA = "、"     # 、


def ym(year, month):
    """参照実装: "YYYYMM" (実装の review_yyyymm を使わずに期待値を作る)。"""
    return f"{year:04d}{month:02d}"


def split_ym(yyyymm):
    return int(yyyymm[:4]), int(yyyymm[4:])


def ref_range(now, count=12):
    """参照実装: now の月を含む直近 count か月 [(年, 月), ...] (古い順)。count<1 は 1。"""
    count = max(1, count)
    end = now.year * 12 + (now.month - 1)
    out = []
    for i in range(end - count + 1, end + 1):
        y, m0 = divmod(i, 12)
        out.append((y, m0 + 1))
    return out


def ref_previous(now):
    """参照実装: 前月の "YYYYMM"。"""
    y, m = ref_range(now, 2)[0]
    return ym(y, m)


def ref_quarter_name(year, quarter, months):
    """参照実装: 四半期ボタン名。範囲内の月が3か月そろえば "2026年Q1"。満たなければ含まれる月を括弧で付ける
    (1か月だけ "2026年Q4(10月)"、複数は "2025年Q4(11-12月)" = first-last月。月は先頭の0なし)。"""
    base = f"{year}年Q{quarter}"
    if len(months) >= 3:
        return base
    if len(months) == 1:
        return f"{base}({months[0]}月)"
    return f"{base}({months[0]}-{months[-1]}月)"


def ref_quarters(now, count=12):
    """参照実装: [(表示名, ["YYYYMM", ...])] (暦年の四半期ごと・古い順・月は範囲内のものだけ)。"""
    groups = []                                    # [(年, 四半期, [月, ...])]
    for y, m in ref_range(now, count):
        q = (m - 1) // 3 + 1
        if not groups or groups[-1][:2] != (y, q):
            groups.append((y, q, []))
        groups[-1][2].append(m)
    return [(ref_quarter_name(y, q, ms), [ym(y, m) for m in ms]) for y, q, ms in groups]


def norm(choices):
    """review_quarter_choices の戻り値を [(名前, [月...])] に正規化 (要素が tuple/list どちらでも比較できるように)。"""
    return [(name, list(months)) for name, months in choices]


def _sweep_nows():
    out = []
    for y in range(2024, 2029):
        for m in range(1, 13):
            out.append(datetime(y, m, 1, 0, 0, 0))
            out.append(datetime(y, m, calendar.monthrange(y, m)[1], 23, 59, 59))
    return out


SWEEP_NOWS = _sweep_nows()                       # 2024〜2028 の全月の1日と末日 (120件)
SWEEP_COUNTS = (1, 2, 3, 4, 5, 6, 12, 13, 18, 24)


# ============================================================
# 1. review_month_range / REVIEW_WINDOW_MONTHS
# ============================================================
class TestReviewMonthRange(unittest.TestCase):
    def test_window_constant_is_12(self):
        self.assertEqual(oto().REVIEW_WINDOW_MONTHS, 12)

    def test_representative_dates_default_is_the_last_12_months(self):
        f = oto().review_month_range
        cases = (
            (NOW_1004, [(2025, 11), (2025, 12)] + [(2026, m) for m in range(1, 11)]),    # 年またぎ
            (NOW_0115, [(2025, m) for m in range(2, 13)] + [(2026, 1)]),                 # 1月: 前年2月から
            (NOW_1231, [(2026, m) for m in range(1, 13)]),                               # 12月: 暦年と一致
            (NOW_0301, [(2026, m) for m in range(4, 13)] + [(2027, m) for m in range(1, 4)]),
        )
        for now, expected in cases:
            with self.subTest(now=now.date().isoformat()):
                got = f(now)
                self.assertEqual(got, expected)
                self.assertEqual(len(got), 12)
                self.assertEqual(got[-1], (now.year, now.month), "末尾は当月のはず")
                self.assertEqual(f(now, 12), expected, "count=12 の明示指定は既定と同じはず")
                self.assertEqual(f(now=now), expected, "キーワード指定 now= でも同じはず")
                self.assertEqual(f(now, count=12), expected, "キーワード指定 count= でも同じはず")

    def test_count_1_2_3_13_24(self):
        f = oto().review_month_range
        with self.subTest(count=1):
            self.assertEqual(f(NOW_1004, 1), [(2026, 10)])
        with self.subTest(count=3):
            self.assertEqual(f(NOW_1004, 3), [(2026, 8), (2026, 9), (2026, 10)])
        with self.subTest(count=2, year_crossing=True):
            self.assertEqual(f(NOW_0115, 2), [(2025, 12), (2026, 1)])
        with self.subTest(count=13):
            got = f(NOW_1004, 13)
            self.assertEqual(len(got), 13)
            self.assertEqual((got[0], got[-1]), ((2025, 10), (2026, 10)))
        with self.subTest(count=24):
            got = f(NOW_1004, 24)
            self.assertEqual(len(got), 24)
            self.assertEqual((got[0], got[-1]), ((2024, 11), (2026, 10)))

    def test_count_zero_and_negative_are_treated_as_one(self):
        f = oto().review_month_range
        for count in (0, -1, -12, -100):
            with self.subTest(count=count):
                self.assertEqual(f(NOW_1004, count), [(2026, 10)])
                self.assertEqual(f(NOW_0115, count), [(2026, 1)])

    def test_sweep_matches_reference_and_is_ascending_contiguous_unique(self):
        f = oto().review_month_range
        for now in SWEEP_NOWS:
            for count in SWEEP_COUNTS:
                got = f(now, count)
                label = f"{now:%Y-%m-%d} count={count}"
                self.assertEqual(len(got), count, label)
                self.assertEqual(got[-1], (now.year, now.month), f"{label}: 末尾は当月のはず")
                idx = [y * 12 + (m - 1) for y, m in got]
                self.assertEqual(idx, list(range(idx[0], idx[0] + count)), f"{label}: 連続した昇順(古い順)のはず")
                self.assertEqual(got, ref_range(now, count), label)

    def test_day_of_month_and_time_of_day_do_not_matter(self):
        # 31日・閏日・30日までの月は、単純な「月を1つ戻す」実装が落ちやすい日付
        f = oto().review_month_range
        cases = (
            (datetime(2026, 3, 31, 23, 59, 59), (2025, 4), (2026, 3)),
            (datetime(2026, 8, 31, 0, 0, 0), (2025, 9), (2026, 8)),
            (datetime(2026, 10, 31, 12, 0, 0), (2025, 11), (2026, 10)),
            (datetime(2028, 2, 29, 12, 0, 0), (2027, 3), (2028, 2)),
            (datetime(2026, 1, 31, 12, 0, 0), (2025, 2), (2026, 1)),
        )
        for now, first, last in cases:
            with self.subTest(now=str(now)):
                got = f(now)
                self.assertEqual((got[0], got[-1], len(got)), (first, last, 12))
        self.assertEqual(f(datetime(2026, 10, 4, 0, 0, 0)), f(datetime(2026, 10, 4, 23, 59, 59)))

    def test_returns_list_of_int_pairs(self):
        got = oto().review_month_range(NOW_1004)
        self.assertIsInstance(got, list)
        for item in got:
            self.assertIsInstance(item, tuple)
            self.assertEqual(len(item), 2)
            y, m = item
            self.assertIs(type(y), int)
            self.assertIs(type(m), int)
            self.assertTrue(1 <= m <= 12)

    def test_now_none_means_today(self):
        f = oto().review_month_range
        before = datetime.now()
        got = f()
        after = datetime.now()
        self.assertIn(got, (ref_range(before), ref_range(after)))
        before = datetime.now()
        got3 = f(None, 3)
        after = datetime.now()
        self.assertIn(got3, (ref_range(before, 3), ref_range(after, 3)))


class TestSpecGapReviewMonthRange(unittest.TestCase):
    def test_a_date_object_is_accepted_like_a_datetime(self):
        # 仕様は now の型を明記していない。年と月しか要らないので date でも動く、と自然に解釈
        self.assertEqual(oto().review_month_range(date(2026, 10, 4)), ref_range(NOW_1004))


# ============================================================
# 2. review_yyyymm / review_default_selected
# ============================================================
class TestReviewYyyymm(unittest.TestCase):
    def test_month_is_zero_padded(self):
        f = oto().review_yyyymm
        for y, m, expected in ((2026, 9, "202609"), (2026, 1, "202601"), (2026, 10, "202610"),
                               (2026, 12, "202612"), (2025, 1, "202501"), (2027, 3, "202703")):
            with self.subTest(year=y, month=m):
                got = f(y, m)
                self.assertEqual(got, expected)
                self.assertIsInstance(got, str)
                self.assertEqual(len(got), 6)


class TestReviewDefaultSelected(unittest.TestCase):
    def test_representative_dates_previous_month_only(self):
        f = oto().review_default_selected
        cases = ((NOW_1004, "202609"),                       # 通常
                 (NOW_0115, "202512"),                       # 1月 → 前年12月
                 (NOW_0301, "202702"),                       # 3月 (2027-03-01) → 2月 (2027-02)
                 (NOW_1231, "202611"),
                 (datetime(2027, 1, 1), "202612"),
                 (datetime(2026, 2, 28), "202601"))
        for now, expected in cases:
            with self.subTest(now=now.date().isoformat()):
                got = f(now)
                self.assertEqual(got, [expected])
                self.assertIsInstance(got, list)
                self.assertEqual(f(now=now), [expected], "キーワード指定 now= でも同じはず")

    def test_end_of_month_days_use_the_previous_calendar_month(self):
        # 31日に「月を1つ戻す」と存在しない日付になる月 (2月・4月・9月 など) の境界
        f = oto().review_default_selected
        cases = ((datetime(2026, 3, 31), "202602"), (datetime(2026, 5, 31), "202604"),
                 (datetime(2026, 10, 31), "202609"), (datetime(2028, 3, 30), "202802"),
                 (datetime(2026, 1, 31), "202512"), (datetime(2026, 12, 31), "202611"))
        for now, expected in cases:
            with self.subTest(now=now.date().isoformat()):
                self.assertEqual(f(now), [expected])

    def test_sweep_is_exactly_one_str_and_matches_reference(self):
        f = oto().review_default_selected
        for now in SWEEP_NOWS:
            got = f(now)
            self.assertEqual(got, [ref_previous(now)], f"{now:%Y-%m-%d}")
            self.assertIsInstance(got[0], str)
            self.assertRegex(got[0], r"^\d{6}$")

    def test_now_none_means_today(self):
        before = datetime.now()
        got = oto().review_default_selected()
        after = datetime.now()
        self.assertIn(got, ([ref_previous(before)], [ref_previous(after)]))


# ============================================================
# 3. review_quarter_choices
# ============================================================
class TestReviewQuarterChoices(unittest.TestCase):
    # 仕様 (A3_SPEC_DELTA_fix1.md 1.): 範囲の端で3か月に満たない四半期は、含まれる月を括弧で付ける。
    #   1か月だけ -> "(10月)"、複数 -> "(11-12月)" (月は数字に「月」、範囲は first-last月)。3か月そろう四半期は "2026年Q1"。
    def test_2026_10_04_2025q4_has_only_nov_and_dec(self):
        """2026-10-04: 2025年Q4 は範囲内の11・12月だけ、2026年Q4 は10月だけなので、どちらも月を括弧で付けた名前になる (仕様の例そのまま)。"""
        expected = [
            ("2025年Q4(11-12月)", ["202511", "202512"]),
            ("2026年Q1", ["202601", "202602", "202603"]),
            ("2026年Q2", ["202604", "202605", "202606"]),
            ("2026年Q3", ["202607", "202608", "202609"]),
            ("2026年Q4(10月)", ["202610"]),
        ]
        self.assertEqual(norm(oto().review_quarter_choices(NOW_1004)), expected)
        self.assertEqual(norm(oto().review_quarter_choices(NOW_1004, 12)), expected)

    def test_2026_01_15_2025_all_four_quarters_and_2026q1_is_january_only(self):
        """2026-01-15 (年またぎ): 2025年Q1 は2・3月だけ「(2-3月)」、2026年Q1 は1月だけ「(1月)」、間の3つは3か月そろうので括弧なし。"""
        # 範囲は 2025-02〜2026-01。2025年Q1 は範囲内の 2・3月だけ (1月は範囲外)、2026年Q1 は 1月だけ
        expected = [
            ("2025年Q1(2-3月)", ["202502", "202503"]),
            ("2025年Q2", ["202504", "202505", "202506"]),
            ("2025年Q3", ["202507", "202508", "202509"]),
            ("2025年Q4", ["202510", "202511", "202512"]),
            ("2026年Q1(1月)", ["202601"]),
        ]
        self.assertEqual(norm(oto().review_quarter_choices(NOW_0115)), expected)

    def test_2026_12_31_is_the_four_full_quarters_of_2026(self):
        """2026-12-31: 暦年と一致し、4つとも3か月そろうので括弧が付かない (端の四半期でも同じ)。"""
        # 3か月そろう四半期には括弧が付かない (端の四半期でも同じ)
        expected = [
            ("2026年Q1", ["202601", "202602", "202603"]),
            ("2026年Q2", ["202604", "202605", "202606"]),
            ("2026年Q3", ["202607", "202608", "202609"]),
            ("2026年Q4", ["202610", "202611", "202612"]),
        ]
        self.assertEqual(norm(oto().review_quarter_choices(NOW_1231)), expected)

    def test_count_1_3_13(self):
        """count=1・3・13: 端の四半期に月の括弧が付く (13か月なら先頭の2025年Q4 は10〜12月がそろうので括弧なし)。"""
        f = oto().review_quarter_choices
        with self.subTest(count=1):
            self.assertEqual(norm(f(NOW_1004, 1)), [("2026年Q4(10月)", ["202610"])])
        with self.subTest(count=3):
            self.assertEqual(norm(f(NOW_1004, 3)),
                             [("2026年Q3(8-9月)", ["202608", "202609"]), ("2026年Q4(10月)", ["202610"])])
        with self.subTest(count=13):
            self.assertEqual(norm(f(NOW_1004, 13)), [
                ("2025年Q4", ["202510", "202511", "202512"]),
                ("2026年Q1", ["202601", "202602", "202603"]),
                ("2026年Q2", ["202604", "202605", "202606"]),
                ("2026年Q3", ["202607", "202608", "202609"]),
                ("2026年Q4(10月)", ["202610"]),
            ])

    def test_count_zero_is_treated_as_one(self):
        """count=0 は最低1扱い: 「2026年Q4(10月)」だけ (仕様の例)。"""
        # 仕様 (A3_SPEC_DELTA_fix1.md 1.): count=0 は最低1扱いで 2026年Q4(10月)
        self.assertEqual(norm(oto().review_quarter_choices(NOW_1004, 0)), [("2026年Q4(10月)", ["202610"])])

    def test_sweep_months_are_in_range_unique_oldest_first_and_named_correctly(self):
        """全月の1日・末日 × count 1〜24: 月は範囲内で重複なし・古い四半期から順、名前は参照実装 (ref_quarters) の規則どおり。"""
        f = oto().review_quarter_choices
        for now in SWEEP_NOWS:
            for count in SWEEP_COUNTS:
                got = norm(f(now, count))
                label = f"{now:%Y-%m-%d} count={count}"
                for name, _ms in got:
                    self.assertRegex(name, r"^\d{4}年Q[1-4](\(\d{1,2}(-\d{1,2})?月\))?$", label)
                rng = [ym(y, m) for y, m in ref_range(now, count)]
                flat = [mm for _n, ms in got for mm in ms]
                self.assertEqual(len(flat), len(set(flat)), f"{label}: 月が複数の選択肢に重複している")
                self.assertEqual(flat, rng, f"{label}: 選択肢の月を順に並べると範囲(古い順)と一致するはず")
                keys = [(int(n[:4]), int(n[n.index("Q") + 1])) for n, _ in got]
                self.assertEqual(keys, sorted(set(keys)), f"{label}: 古い四半期から順・重複なしのはず")
                for name, ms in got:
                    for mm in ms:
                        y, m = split_ym(mm)
                        self.assertTrue(name.startswith(f"{y}年Q{(m - 1) // 3 + 1}"),
                                        f"{label}: {mm} は {name} の月ではない")
                self.assertEqual(got, ref_quarters(now, count), label)

    def test_return_shape(self):
        got = oto().review_quarter_choices(NOW_1004)
        self.assertIsInstance(got, list)
        for item in got:
            self.assertEqual(len(item), 2)
            name, months = item
            self.assertIsInstance(name, str)
            self.assertIsInstance(months, list)
            for mm in months:
                self.assertIsInstance(mm, str)
                self.assertRegex(mm, r"^\d{6}$")

    def test_now_none_means_today(self):
        f = oto().review_quarter_choices
        before = datetime.now()
        got = norm(f())
        after = datetime.now()
        self.assertIn(got, (ref_quarters(before), ref_quarters(after)))


# ============================================================
# 4. review_ym_sort_key
# ============================================================
LABELS_4 = ["2026年9月", "2026年10月", "2025年12月", "手動追加"]
LABELS_4_NEWEST_FIRST = ["2026年10月", "2026年9月", "2025年12月", "手動追加"]


class TestReviewYmSortKey(unittest.TestCase):
    def key(self, label):
        return oto().review_ym_sort_key(label)

    def test_parses_year_and_month(self):
        for label, expected in (("2026年10月", (2026, 10)), ("2026年9月", (2026, 9)),
                                ("2025年12月", (2025, 12)), ("2026年1月", (2026, 1))):
            with self.subTest(label=label):
                got = self.key(label)
                self.assertEqual(got, expected)
                self.assertIsInstance(got, tuple)
                self.assertEqual(len(got), 2)
                self.assertIs(type(got[0]), int)
                self.assertIs(type(got[1]), int)

    def test_orders_numerically_not_as_strings_and_across_years(self):
        self.assertGreater(self.key("2026年10月"), self.key("2026年9月"))     # 文字列順だと逆になる
        self.assertGreater(self.key("2026年12月"), self.key("2026年2月"))
        self.assertGreater(self.key("2026年1月"), self.key("2025年12月"))     # 年またぎ
        for y in range(2024, 2029):                                           # 全月で (年, 月) そのもの
            for m in range(1, 13):
                self.assertEqual(self.key(f"{y}年{m}月"), (y, m), f"{y}年{m}月")
        labels = [f"{y}年{m}月" for y in (2025, 2026) for m in range(1, 13)]
        shuffled = labels[:]
        random.Random(7).shuffle(shuffled)
        self.assertEqual(sorted(shuffled, key=self.key), labels)

    def test_surrounding_whitespace_is_tolerated(self):
        for label in (" 2026年10月", "2026年10月 ", "  2026年10月  "):
            with self.subTest(label=label):
                self.assertEqual(self.key(label), (2026, 10))

    def test_unreadable_labels_are_minus_one_pair(self):
        for label in ("手動追加", "", None, "abc", "年月", "2026年", "月", "10月", "2026-10", "202610", "2026/10",
                      "   "):
            with self.subTest(label=label):
                self.assertEqual(self.key(label), (-1, -1))

    def test_descending_sort_puts_new_months_first_and_manual_last(self):
        got = sorted(LABELS_4, key=self.key, reverse=True)
        self.assertEqual(got, LABELS_4_NEWEST_FIRST)
        # 入力順が違っても同じ
        for perm in itertools.permutations(LABELS_4):
            self.assertEqual(sorted(perm, key=self.key, reverse=True), LABELS_4_NEWEST_FIRST)
        # (確認) キー無しの文字列順の降順では、この並びにならない = このデータは旧不具合を再現できる
        self.assertNotEqual(sorted(LABELS_4, reverse=True), LABELS_4_NEWEST_FIRST)

    def test_manual_label_sorts_before_every_real_month(self):
        self.assertLess(self.key("手動追加"), self.key("2000年1月"))
        self.assertLess(self.key(None), self.key("2000年1月"))


class TestSpecGapReviewYmSortKey(unittest.TestCase):
    def key(self, label):
        return oto().review_ym_sort_key(label)

    def test_space_after_the_year_mark_fullwidth_space_and_tab_are_tolerated(self):
        # 仕様は「空白許容」とだけ書く。「年」の後ろの空白・全角空白・タブ/改行も空白として許容、と自然に解釈
        for label in ("2026年 10月", "　2026年10月　", "\t2026年10月\n"):
            with self.subTest(label=label):
                self.assertEqual(self.key(label), (2026, 10))

    def test_whitespace_between_the_digits_and_the_year_month_marks_is_tolerated(self):
        # 【仕様確認】「空白許容」が、数字と「年」「月」の間の空白 (2026 年 10 月) まで含むのかは仕様から読み取れない。
        # 「空白は許容する」を素直に読めば許容されるはず、と自然に解釈 (実装が許容しないなら仕様側で範囲を明記してほしい)
        for label in ("2026 年10月", "2026年10 月", "2026 年 10 月"):
            with self.subTest(label=label):
                self.assertEqual(self.key(label), (2026, 10))

    def test_fullwidth_digits_are_either_unreadable_or_parsed(self):
        # 全角数字は仕様に無い。(-1,-1) でも (2026,10) でも良い (どちらかでなければ NG)
        self.assertIn(self.key("２０２６年１０月"), ((-1, -1), (2026, 10)))

    def test_zero_padded_month_is_read_as_the_month(self):
        self.assertEqual(self.key("2026年09月"), (2026, 9))

    def test_non_string_and_out_of_range_inputs_do_not_raise(self):
        for bad in (123, 2026.10, [], {}, b"2026"):
            with self.subTest(bad=repr(bad)):
                self.assertEqual(self.key(bad), (-1, -1))
        for odd in ("2026年13月", "2026年0月"):        # 値は未定義。例外にならず (int, int) を返せばよい
            with self.subTest(odd=odd):
                got = self.key(odd)
                self.assertEqual(len(got), 2)
                self.assertIs(type(got[0]), int)
                self.assertIs(type(got[1]), int)


# ============================================================
# 5. format_review_period_label
# ============================================================
ALL_1004 = [ym(y, m) for y, m in ref_range(NOW_1004)]          # 202511 .. 202610 (12か月)
BASE_1004 = f"2025年11月{WAVE}2026年10月"


def fmt(all_months, selected=None, mode=None):
    f = oto().format_review_period_label
    if mode is None:
        return f(all_months, selected)
    return f(all_months, selected, mode=mode)


def suffix(text):
    return f"{LPAR}{text}{RPAR}"


def names(months):
    """[(年, 月), ...] -> "2025年12月、2026年1月" (月は先頭の0なし)。"""
    return COMMA.join(f"{y}年{m}月" for y, m in months)


class TestFormatReviewPeriodLabel(unittest.TestCase):
    def test_all_months_updated(self):
        self.assertEqual(fmt(ALL_1004, ref_range(NOW_1004)), BASE_1004 + suffix("全月更新"))

    def test_no_update_for_none_empty_and_omitted(self):
        expected = BASE_1004 + suffix(f"キャッシュのみ{COMMA}更新なし")
        self.assertEqual(fmt(ALL_1004, None), expected)
        self.assertEqual(fmt(ALL_1004, []), expected)
        self.assertEqual(oto().format_review_period_label(ALL_1004), expected)
        self.assertEqual(oto().format_review_period_label(all_months=ALL_1004, selected_months=None), expected)

    def test_one_and_two_months_are_listed_with_spec_example(self):
        self.assertEqual(fmt(ALL_1004, [(2026, 9)]), BASE_1004 + suffix("2026年9月を更新"))
        # 仕様書の例 (年またぎ表記)
        self.assertEqual(fmt(ALL_1004, [(2025, 12), (2026, 1)]),
                         BASE_1004 + suffix(f"2025年12月{COMMA}2026年1月を更新"))

    def test_up_to_six_months_are_listed_and_seven_or_more_are_counted(self):
        window = ref_range(NOW_1004)
        for label, pick in (("末尾n件", lambda n: window[-n:]), ("先頭n件", lambda n: window[:n])):
            for n in range(1, 12):                                # 12 は「全月更新」なのでここでは除く
                sel = pick(n)
                expected = BASE_1004 + (suffix(f"{names(sel)}を更新") if n <= 6 else suffix(f"{n}か月を更新"))
                with self.subTest(pick=label, n=n):
                    self.assertEqual(fmt(ALL_1004, sel), expected)
        # 境界の具体例
        six = COMMA.join(f"2026年{m}月" for m in (5, 6, 7, 8, 9)) + f"{COMMA}2026年10月"
        self.assertEqual(fmt(ALL_1004, [(2026, m) for m in range(5, 11)]), BASE_1004 + suffix(f"{six}を更新"))
        self.assertEqual(fmt(ALL_1004, [(2026, m) for m in range(4, 11)]), BASE_1004 + suffix("7か月を更新"))

    def test_reformat_mode_wins_over_the_selection(self):
        expected = BASE_1004 + suffix("保存済みキャッシュから再構成")
        for sel in (None, [], [(2026, 9)], ref_range(NOW_1004)):
            with self.subTest(selected=sel):
                self.assertEqual(fmt(ALL_1004, sel, mode="reformat"), expected)
        self.assertEqual(oto().format_review_period_label(ALL_1004, None, "reformat"), expected)

    def test_run_mode_is_the_default(self):
        for sel in (None, [], [(2026, 9)], ref_range(NOW_1004), [(2026, m) for m in range(4, 11)]):
            with self.subTest(selected=sel):
                self.assertEqual(fmt(ALL_1004, sel, mode="run"), fmt(ALL_1004, sel))

    def test_base_uses_first_and_last_month_without_leading_zero(self):
        cases = (
            (ALL_1004, f"2025年11月{WAVE}2026年10月"),                                       # 年またぎ
            ([ym(y, m) for y, m in ref_range(NOW_0115)], f"2025年2月{WAVE}2026年1月"),        # 月の0なし
            ([ym(2026, m) for m in range(1, 13)], f"2026年1月{WAVE}2026年12月"),              # 同一年でも年を2回書く
            ([ym(y, m) for y, m in ref_range(NOW_0301)], f"2026年4月{WAVE}2027年3月"),
        )
        for all_months, base in cases:
            with self.subTest(base=base):
                self.assertEqual(fmt(all_months, None), base + suffix(f"キャッシュのみ{COMMA}更新なし"))
                self.assertEqual(fmt(all_months, None, mode="reformat"), base + suffix("保存済みキャッシュから再構成"))

    def test_single_month_window(self):
        base = f"2026年9月{WAVE}2026年9月"
        self.assertEqual(fmt(["202609"], None), base + suffix(f"キャッシュのみ{COMMA}更新なし"))
        self.assertEqual(fmt(["202609"], [(2026, 9)]), base + suffix("全月更新"))           # 件数が一致 = 全月更新

    def test_full_update_wins_over_the_count_rule_and_other_window_sizes(self):
        # 12/12 は「12か月を更新」ではなく「全月更新」
        self.assertEqual(fmt(ALL_1004, ref_range(NOW_1004)), BASE_1004 + suffix("全月更新"))
        # 13か月の窓: 13/13 は全月更新、12/13 は「12か月を更新」、7/13 は「7か月を更新」
        all13 = [ym(y, m) for y, m in ref_range(NOW_1004, 13)]
        base13 = f"2025年10月{WAVE}2026年10月"
        self.assertEqual(fmt(all13, ref_range(NOW_1004, 13)), base13 + suffix("全月更新"))
        self.assertEqual(fmt(all13, ref_range(NOW_1004, 12)), base13 + suffix("12か月を更新"))
        self.assertEqual(fmt(all13, ref_range(NOW_1004, 7)), base13 + suffix("7か月を更新"))
        # 3か月の窓: 3/3 は全月更新、2/3 は列挙
        all3 = [ym(y, m) for y, m in ref_range(NOW_1004, 3)]
        base3 = f"2026年8月{WAVE}2026年10月"
        self.assertEqual(fmt(all3, ref_range(NOW_1004, 3)), base3 + suffix("全月更新"))
        self.assertEqual(fmt(all3, [(2026, 9), (2026, 10)]), base3 + suffix(f"2026年9月{COMMA}2026年10月を更新"))


# ============================================================
# 6. 月別タイムラインの並び (generate_review_report)
# ============================================================
OLD_REV = "outlook_total_organizer_20261004_02.py"
NEW_REV = "outlook_total_organizer_20261004_03.py"


def make_ach(idx, label=None, **extra):
    """generate_review_report が必要とする最小限の実績 (他のキーは既存コード側の .get の既定値で足りる)。"""
    a = {"achievement_id": f"ach-{idx}", "title": f"実績{idx}", "summary": "要約", "rank": "A"}
    if label is not None:
        a["year_month_label"] = label
    a.update(extra)
    return a


ACHS_4 = [make_ach(1, "2026年9月"), make_ach(2, "2026年10月"), make_ach(3, "2025年12月"), make_ach(4, "手動追加")]


def timeline_headings(html):
    """月別タイムライン (id="view-timeline") 内の見出しを [(見出し, 件数表記), ...] で返す。"""
    start = html.find('id="view-timeline"')
    assert start >= 0, 'HTML に id="view-timeline" が無い'
    end = html.find('id="reviewCopyArea"', start)
    region = html[start:end if end >= 0 else len(html)]
    heads = re.findall(r'<div class="rv-goal-head">(.*?)<span class="rv-count">(.*?)</span>', region, flags=re.S)
    return [(h.strip(), c.strip()) for h, c in heads]


@functools.lru_cache(maxsize=None)
def load_baseline():
    """直前版 (_02) を別名で読み込む (旧不具合の再現確認用)。ファイルが無ければ None。"""
    path = _loader.rev_path(OLD_REV)
    if not os.path.isfile(path):
        return None
    oto()                                                  # 先に最小スタブを入れておく
    spec = importlib.util.spec_from_file_location("oto_baseline_a2", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["oto_baseline_a2"] = mod
    with tempdir_cwd():
        spec.loader.exec_module(mod)
    return mod


class ReviewReportCase(unittest.TestCase):
    def setUp(self):
        cm = tempdir_cwd()
        self.tmp = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)

    def render(self, mod, achievements):
        gen = mod.HTMLReportGenerator(os.path.join(self.tmp, "out"), 8765)
        review_data = {"achievements": achievements, "generated_at": "2026-10-04 12:00"}
        path = gen.generate_review_report(review_data, f"2025年11月{WAVE}2026年10月", 0, 0)
        self.assertTrue(path, "HTML が出力されなかった (空のパスが返った)")
        self.assertTrue(os.path.isfile(path), f"返ったパスにファイルが無い: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def heads(self, mod, achievements):
        return [h for h, _c in timeline_headings(self.render(mod, achievements))]


class TestTimelineOrder(ReviewReportCase):
    def test_four_labels_newest_first_and_manual_last(self):
        self.assertEqual(self.heads(oto(), ACHS_4), ["2026年10月", "2026年9月", "2025年12月", "手動追加"])

    def test_input_order_does_not_matter(self):
        for perm in itertools.permutations(ACHS_4):
            with self.subTest(order=[a["year_month_label"] for a in perm]):
                self.assertEqual(self.heads(oto(), list(perm)),
                                 ["2026年10月", "2026年9月", "2025年12月", "手動追加"])

    def test_same_month_is_one_group_with_its_count(self):
        achs = [make_ach(1, "2026年9月"), make_ach(2, "2026年10月"), make_ach(3, "2026年10月"), make_ach(4, "手動追加")]
        got = timeline_headings(self.render(oto(), achs))
        self.assertEqual(got, [("2026年10月", "2件"), ("2026年9月", "1件"), ("手動追加", "1件")])

    def test_full_12_month_window_is_in_descending_chronological_order(self):
        window = [f"{y}年{m}月" for y, m in ref_range(NOW_1004)]               # 2025年11月 .. 2026年10月
        shuffled = window[:]
        random.Random(11).shuffle(shuffled)
        achs = [make_ach(i, label) for i, label in enumerate(shuffled)] + [make_ach(99, "手動追加")]
        self.assertEqual(self.heads(oto(), achs), list(reversed(window)) + ["手動追加"])

    def test_achievement_without_year_month_label_is_grouped_as_manual_and_last(self):
        achs = [make_ach(1), make_ach(2, "2026年9月"), make_ach(3, "2025年12月")]
        self.assertEqual(self.heads(oto(), achs), ["2026年9月", "2025年12月", "手動追加"])

    def test_old_revision_has_the_ordering_bug_that_a3_fixes(self):
        old = load_baseline()
        if old is None:
            self.skipTest(f"{OLD_REV} が無い")
        got = self.heads(old, ACHS_4)
        self.assertNotEqual(got, ["2026年10月", "2026年9月", "2025年12月", "手動追加"],
                            "旧版でも正しい並びになっている (このテストデータは旧不具合を再現できていない)")
        self.assertLess(got.index("2026年9月"), got.index("2026年10月"), f"旧版の並び: {got}")


# ============================================================
# 7. GUI (MailManagerGUI._ui_review_tab ほか)
# ============================================================
_SKIP_REASON = "unset"


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
        except Exception as e:                                  # TclError (no display) など
            _SKIP_REASON = f"ディスプレイが使えない ({e})。Linux は xvfb-run -a を付けて実行してください"
    return _SKIP_REASON


class _Boom:
    """触ったら失敗するスタブ (振り返りタブの構築・月選択の操作が Outlook/AI に触れていないことの確認)。"""

    def __init__(self, label):
        self._label = label

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        raise AssertionError(f"振り返りタブの構築/操作が {self._label}.{name} に触れた (COM/AI/ネットワーク禁止)")

    def __call__(self, *a, **k):
        raise AssertionError(f"振り返りタブの構築/操作が {self._label} を呼んだ (COM/AI/ネットワーク禁止)")


BUTTON_CLASSES = ("Button", "TButton")
CHECK_CLASSES = ("Checkbutton", "TCheckbutton")
LABEL_CLASSES = ("Label", "TLabel")


def walk(widget):
    yield widget
    for c in widget.winfo_children():
        yield from walk(c)


def wtext(widget):
    try:
        return str(widget.cget("text"))
    except Exception:                                           # text オプションを持たない部品
        return None


def find(root, classes):
    return [w for w in walk(root) if w.winfo_class() in classes]


class ReviewGuiCase(unittest.TestCase):
    DATES = (NOW_1004, NOW_0115, NOW_1231)

    @classmethod
    def setUpClass(cls):
        reason = _gui_skip_reason()
        if reason:
            raise unittest.SkipTest(reason)

    def setUp(self):
        cm = tempdir_cwd()
        cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        self.dialogs = []
        self.callback_errors = []
        self.guis = []
        self.gui = None
        self._fixed_today = None
        self._today_patch = None
        self._patch_messagebox()
        self.addCleanup(self._teardown_guis)

    # ---- パッチ ----------------------------------------------------------
    def _patch_messagebox(self):
        ask_defaults = {"askquestion": "yes", "askokcancel": True, "askyesno": True,
                        "askyesnocancel": True, "askretrycancel": False}
        for name in ("showinfo", "showwarning", "showerror") + tuple(ask_defaults):
            def rec(*args, _name=name, **kwargs):
                self.dialogs.append((_name, args, kwargs))
                return ask_defaults.get(_name, "ok")
            p = mock.patch.object(tkmessagebox, name, rec)
            p.start()
            self.addCleanup(p.stop)

    def freeze_today(self, fixed):
        """対象モジュールの datetime.now()/today() を固定日付にする (テストが終わるまで有効)。"""
        self._fixed_today = fixed
        if self._today_patch is None:
            case = self

            class FakeDatetime(datetime):
                @classmethod
                def now(cls, tz=None):
                    f = case._fixed_today
                    return f if tz is None else f.replace(tzinfo=tz)

                @classmethod
                def today(cls):
                    return case._fixed_today

                @classmethod
                def utcnow(cls):
                    return case._fixed_today

            self._today_patch = mock.patch.object(oto(), "datetime", FakeDatetime)
            self._today_patch.start()
            self.addCleanup(self._today_patch.stop)

    # ---- GUI 構築 / 破棄 ---------------------------------------------------
    # サブクラスが差し替えられる構築パラメータ (tests/test_a3_review_run.py の窓幅630pxテストが使う)
    WINDOW_GEOMETRY = "1100x800+0+0"
    NOTEBOOK_PACK = {"fill": tk.BOTH, "expand": True} if tk is not None else {}

    def _prepare_root(self, root):
        """タブを組み立てる「前」に root へ施す設定 (フォント・テーマの固定など)。既定は何もしない。"""

    def make_gui(self, today=None, staffs=None):
        """MailManagerGUI.__init__ は呼ばず __new__ で作り、必要最小の属性だけ手で設定して _ui_review_tab() を呼ぶ。
        today を渡すと、その日付を「今日」にする (None なら実際の今日)。
        staffs を渡すと project_knowledge["staffs"] にそのキーを登録する (対象者チェックボックスに出る)。"""
        mod = oto()
        if today is not None:
            self.freeze_today(today)
        gui = mod.MailManagerGUI.__new__(mod.MailManagerGUI)
        root = tk.Tk()
        self._prepare_root(root)
        root.geometry(self.WINDOW_GEOMETRY)
        root.report_callback_exception = lambda exc, val, tb: self.callback_errors.append(f"{exc.__name__}: {val}")
        gui.root = root
        gui.notebook = ttk.Notebook(root)
        gui.notebook.pack(**self.NOTEBOOK_PACK)
        gui.tab_review = ttk.Frame(gui.notebook)
        gui.notebook.add(gui.tab_review, text="📈 振り返り")
        gui.project_knowledge = {"staffs": dict(staffs or {}), "projects": {}}
        gui.outlook = _Boom("outlook")
        gui.summarizer = _Boom("summarizer")
        gui.reporter = _Boom("reporter")
        self.guis.append(gui)
        self.gui = gui
        gui._ui_review_tab()
        root.update()
        return gui

    def _destroy(self, gui):
        root = gui.root
        try:
            for aid in root.tk.splitlist(root.tk.call("after", "info")):
                root.after_cancel(aid)
        except Exception:                                       # noqa: BLE001
            pass
        try:
            gui.__dict__.clear()           # BooleanVar を root が生きているうちに解放する (破棄後の __del__ の雑音を避ける)
            gc.collect()
        except Exception:                                       # noqa: BLE001
            pass
        try:
            root.destroy()
        except Exception:                                       # noqa: BLE001
            pass

    def close_gui(self, gui):
        if gui in self.guis:
            self.guis.remove(gui)
        if self.gui is gui:
            self.gui = None
        self._destroy(gui)

    def _teardown_guis(self):
        for gui in list(self.guis):
            self._destroy(gui)
        self.guis = []
        self.gui = None
        if self.callback_errors:
            self.fail(f"Tkコールバックの未処理例外: {self.callback_errors}")

    # ---- 部品の探索 --------------------------------------------------------
    def dump(self):
        return [(w.winfo_class(), wtext(w)) for w in walk(self.gui.tab_review) if wtext(w)]

    def button(self, text):
        """ボタンの文言で探す (完全一致を優先し、無ければ部分一致で1個だけ見つかればそれ)。"""
        buttons = find(self.gui.tab_review, BUTTON_CLASSES)
        exact = [w for w in buttons if wtext(w) == text]
        if len(exact) == 1:
            return exact[0]
        loose = [w for w in buttons if text in (wtext(w) or "")]
        self.assertEqual(len(loose), 1, f"ボタン {text!r} が{len(loose)}個 (期待は1個)。部品: {self.dump()}")
        return loose[0]

    def all_check(self):
        """v_review_all に結び付いたチェックボタン (= 「全て」)。"""
        name = str(self.gui.v_review_all)
        found = [w for w in find(self.gui.tab_review, CHECK_CLASSES) if str(w.cget("variable")) == name]
        self.assertEqual(len(found), 1, f"v_review_all に結び付いたチェックボタンが{len(found)}個。部品: {self.dump()}")
        self.assertIn("全て", wtext(found[0]) or "", "「全て」チェックの文言")
        return found[0]

    def month_checks(self):
        """{"YYYYMM": チェックボタン} (v_review_month_vars の変数名で対応付ける)。"""
        by_var = {str(v): k for k, v in self.gui.v_review_month_vars.items()}
        out = {}
        for w in find(self.gui.tab_review, CHECK_CLASSES):
            name = str(w.cget("variable"))
            if name in by_var:
                out[by_var[name]] = w
        return out

    def year_labels(self):
        """{年: 年ラベル} (文言が「{年}年:」のラベル)。"""
        out = {}
        for w in find(self.gui.tab_review, LABEL_CLASSES):
            m = re.fullmatch(r"(\d{4})年:", wtext(w) or "")
            if m:
                out[int(m.group(1))] = w
        return out

    def on_months(self):
        return {k for k, v in self.gui.v_review_month_vars.items() if v.get()}

    def set_all_months(self, value):
        for v in self.gui.v_review_month_vars.values():
            v.set(value)
        self.gui.v_review_all.set(value)

    def click(self, widget):
        widget.invoke()
        self.gui.root.update()


class TestReviewTabGui(ReviewGuiCase):
    def test_month_vars_are_the_last_12_months_across_years(self):
        for today in self.DATES:
            with self.subTest(today=today.date().isoformat()):
                gui = self.make_gui(today)
                self.assertEqual(len(gui.v_review_month_vars), 12)
                self.assertEqual(sorted(gui.v_review_month_vars), [ym(y, m) for y, m in ref_range(today)])
                self.assertEqual(len(self.month_checks()), 12, f"12か月ぶんのチェックボックスがあるはず。部品: {self.dump()}")
                self.close_gui(gui)

    def test_default_is_previous_month_only_and_all_is_off(self):
        for today in self.DATES:
            with self.subTest(today=today.date().isoformat()):
                gui = self.make_gui(today)
                prev = ref_previous(today)
                self.assertEqual(self.on_months(), {prev}, "既定は前月だけON (1月なら前年12月)")
                self.assertFalse(gui.v_review_all.get(), "「全て」の既定は OFF")
                self.assertEqual(gui._get_review_selected_months(), [split_ym(prev)])
                self.close_gui(gui)

    def test_get_review_all_months_is_the_12_months_oldest_first(self):
        for today in self.DATES:
            with self.subTest(today=today.date().isoformat()):
                gui = self.make_gui(today)
                got = gui._get_review_all_months()
                self.assertEqual(got, [ym(y, m) for y, m in ref_range(today)])
                self.assertEqual(got, sorted(gui.v_review_month_vars))
                self.close_gui(gui)

    def test_get_review_selected_months_returns_year_month_pairs_oldest_first(self):
        gui = self.make_gui(NOW_1004)
        self.assertEqual(gui._get_review_selected_months(), [(2026, 9)])
        for key, v in gui.v_review_month_vars.items():
            v.set(key in ("202610", "202511", "202601"))          # 選んだ順や dict の並びと無関係に古い順で返る
        self.assertEqual(gui._get_review_selected_months(), [(2025, 11), (2026, 1), (2026, 10)])
        for v in gui.v_review_month_vars.values():
            v.set(False)
        self.assertEqual(gui._get_review_selected_months(), [])

    def test_prev_month_button_selects_only_the_previous_month(self):
        for today in (NOW_1004, NOW_0115):
            with self.subTest(today=today.date().isoformat()):
                gui = self.make_gui(today)
                prev = ref_previous(today)
                btn = self.button("前月のみ")
                self.set_all_months(True)                         # 全ON (「全て」もON) から
                self.click(btn)
                self.assertEqual(self.on_months(), {prev})
                self.assertFalse(gui.v_review_all.get())
                self.set_all_months(False)                        # 別の月だけON (最古の月) から
                gui.v_review_month_vars[ym(*ref_range(today)[0])].set(True)
                self.click(btn)
                self.assertEqual(self.on_months(), {prev})
                self.assertEqual(gui._get_review_selected_months(), [split_ym(prev)])
                self.close_gui(gui)

    def test_quarter_buttons_are_named_by_review_quarter_choices(self):
        """四半期ボタンの文言は review_quarter_choices の名前そのまま。2026-10-04 では「2025年Q4(11-12月)」「2026年Q4(10月)」(括弧付き) で、括弧なしのボタンは無い。"""
        mod = oto()
        for today in (NOW_1004, NOW_0115):
            with self.subTest(today=today.date().isoformat()):
                gui = self.make_gui(today)
                texts = [wtext(b) for b in find(gui.tab_review, BUTTON_CLASSES)]
                for name, _months in mod.review_quarter_choices(today):
                    self.assertEqual(texts.count(name), 1, f"四半期ボタン {name!r} が1個あるはず。ボタン: {texts}")
                self.close_gui(gui)
        # 実行日 2026-10-04 の具体名 (仕様の例: 2025年Q4 は11・12月だけ / 2026年Q4 は10月だけ。端の四半期は月を括弧で付ける)
        gui = self.make_gui(NOW_1004)
        texts = [wtext(b) for b in find(gui.tab_review, BUTTON_CLASSES)]
        for name in ("2025年Q4(11-12月)", "2026年Q1", "2026年Q2", "2026年Q3", "2026年Q4(10月)"):
            self.assertEqual(texts.count(name), 1, f"{name!r}。ボタン: {texts}")
        for plain in ("2025年Q4", "2026年Q4"):
            self.assertNotIn(plain, texts, f"{plain!r} (括弧無し) のボタンは無いはず: 3か月に満たない四半期は月を括弧で付ける")
        self.assertNotIn("2025年Q3", texts, "範囲外の四半期のボタンは出さない")

    def test_each_quarter_button_selects_only_that_quarters_months(self):
        for today in (NOW_1004, NOW_0115):
            with self.subTest(today=today.date().isoformat()):
                gui = self.make_gui(today)
                for name, months in ref_quarters(today):
                    self.set_all_months(True)                     # 全ON から押しても、その四半期以外はOFFになる
                    self.click(self.button(name))
                    with self.subTest(quarter=name):
                        self.assertEqual(self.on_months(), set(months))
                        self.assertFalse(gui.v_review_all.get(), "「全て」は全ON時のみ True")
                        self.assertEqual(gui._get_review_selected_months(), [split_ym(mm) for mm in months])
                self.close_gui(gui)

    def test_quarter_button_after_another_selection_replaces_it(self):
        """四半期ボタンを続けて押すと、前の選択は残らず押した四半期の月だけがON (名前は括弧付きの正式名で押す)。"""
        gui = self.make_gui(NOW_1004)
        self.click(self.button("2026年Q1"))
        self.assertEqual(self.on_months(), {"202601", "202602", "202603"})
        self.click(self.button("2025年Q4(11-12月)"))
        self.assertEqual(self.on_months(), {"202511", "202512"}, "前の四半期の選択は残らない")
        self.assertEqual(gui._get_review_selected_months(), [(2025, 11), (2025, 12)])
        self.click(self.button("前月のみ"))
        self.assertEqual(self.on_months(), {"202609"})

    def test_all_checkbox_turns_every_month_on_then_off(self):
        gui = self.make_gui(NOW_1004)
        chk = self.all_check()
        self.click(chk)
        self.assertTrue(gui.v_review_all.get())
        self.assertEqual(self.on_months(), set(gui._get_review_all_months()))
        self.assertEqual(gui._get_review_selected_months(), [split_ym(mm) for mm in gui._get_review_all_months()])
        self.click(chk)
        self.assertFalse(gui.v_review_all.get())
        self.assertEqual(self.on_months(), set())
        self.assertEqual(gui._get_review_selected_months(), [])

    def test_month_checkboxes_are_one_row_per_year_with_a_year_label(self):
        for today in self.DATES:
            with self.subTest(today=today.date().isoformat()):
                gui = self.make_gui(today)
                window = ref_range(today)
                years = sorted({y for y, _m in window})
                labels = self.year_labels()
                self.assertEqual(sorted(labels), years, f"年ラベルは {years} の「{{年}}年:」だけのはず。部品: {self.dump()}")
                checks = self.month_checks()
                prev_y = None
                for y in years:
                    lbl = labels[y]
                    row = lbl.master
                    kids = list(row.winfo_children())
                    self.assertIs(kids[0], lbl, f"{y}年: ラベルが行の先頭")
                    months = [m for yy, m in window if yy == y]
                    row_checks = [c for c in kids if c.winfo_class() in CHECK_CLASSES]
                    self.assertEqual([wtext(c) for c in row_checks], [f"{m}月" for m in months], f"{y}年の行")
                    for m in months:
                        self.assertIs(checks[ym(y, m)].master, row, f"{ym(y, m)} のチェックボックスは {y}年の行の中")
                    ys = [c.winfo_rooty() for c in row_checks]
                    self.assertLessEqual(max(ys) - min(ys), 3, f"{y}年の月は同じ高さ(1行)に並ぶはず: {ys}")
                    if prev_y is not None:
                        self.assertLess(labels[prev_y].winfo_rooty(), lbl.winfo_rooty(), "古い年の行が上")
                    self.assertTrue(all(lbl.winfo_rootx() <= c.winfo_rootx() for c in row_checks), "年ラベルは行の左端")
                    prev_y = y
                if today is NOW_1231:
                    self.assertNotIn(2025, labels, "年またぎが無い日は前年の行を出さない")
                self.close_gui(gui)

    def test_description_mentions_the_default_previous_month(self):
        gui = self.make_gui(NOW_1004)
        joined = "\n".join(t for t in (wtext(w) for w in walk(gui.tab_review)) if t)
        for needle in ("既定は前月のみにチェックが入っています", "直近12か月", "年またぎ"):
            self.assertIn(needle, joined)

    def test_real_today_defaults_match_the_reference(self):
        # 日付を固定しない (実際の今日)。参照実装で今日の値を作るので、いつ実行しても成り立つ
        before = datetime.now()
        gui = self.make_gui()
        after = datetime.now()
        cands = [before, after]
        keys = sorted(gui.v_review_month_vars)
        match = [d for d in cands if keys == [ym(y, m) for y, m in ref_range(d)]]
        self.assertTrue(match, f"月キーが今日(前後 {before:%Y-%m-%d}/{after:%Y-%m-%d})の直近12か月でない: {keys}")
        today = match[0]
        self.assertEqual(self.on_months(), {ref_previous(today)})
        self.assertFalse(gui.v_review_all.get())
        self.assertEqual(gui._get_review_all_months(), [ym(y, m) for y, m in ref_range(today)])
        self.assertEqual(gui._get_review_selected_months(), [split_ym(ref_previous(today))])


class TestSpecGapReviewTabGui(ReviewGuiCase):
    def test_description_text_starts_with_the_default_notice(self):
        # 仕様: 「説明文の先頭に『既定は前月のみにチェックが入っています(直近12か月・年またぎ…)』を追加」
        # 既存の説明文は先頭に注記マーク「※」が付く。「※」と空白を除いた先頭がこの文言なら「先頭」と自然に解釈
        gui = self.make_gui(NOW_1004)
        notice = "既定は前月のみにチェックが入っています"
        texts = [t for t in (wtext(w) for w in walk(gui.tab_review)) if t and notice in t]
        self.assertTrue(texts, f"説明文が見つからない。部品: {self.dump()}")
        heads = [t.lstrip("※ 　\n") for t in texts]
        self.assertTrue(any(h.startswith(notice) for h in heads), f"説明文の先頭ではない: {texts}")


# ============================================================
# 8. 範囲ガード (_02 → _03 で変えてよいのは許可リストだけ)
# ============================================================
ALLOWED_TO_CHANGE = {
    "HTMLReportGenerator.generate_review_report",
    "MailManagerGUI._ui_review_tab",
    "MailManagerGUI._get_review_all_months",
    "MailManagerGUI._run_review",
    "MailManagerGUI._reformat_review",
}
NEW_CONSTANTS = ("REVIEW_WINDOW_MONTHS",)
# 仕様で「新規に追加する」とされているモジュールレベルの関数 (必ず存在する)。
# review_cache_gaps は A3_SPEC_DELTA_fix1.md (敵対的レビュー第1回の反映) で加わった
NEW_FUNCTIONS = ("review_month_range", "review_yyyymm", "review_default_selected", "review_quarter_choices",
                 "review_ym_sort_key", "format_review_period_label", "review_cache_gaps")
# 仕様が「追加してよい」とする非公開のヘルパ (無くてもよい。期間表示の月リストの整形用)。
# このほかに追加された関数/メソッドは仕様外
OPTIONAL_NEW_PRIVATE_FUNCTIONS = ("_review_month_list_text",)
OPTIONAL_NEW_PRIVATE_CONSTANTS = ("_REVIEW_YM_RE",)
UNCHANGED_BY_SPEC = ("generate_review_data", "summarize_review_month", "get_review_mails_for_month",
                     "_get_review_selected_months")


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


class _DropReviewSortKey(ast.NodeTransformer):
    """sorted(..., key=review_ym_sort_key, ...) の key= だけを取り除く (旧→新の差を打ち消すため)。"""

    def visit_Call(self, node):
        self.generic_visit(node)
        if isinstance(node.func, ast.Name) and node.func.id == "sorted":
            node.keywords = [k for k in node.keywords
                             if not (k.arg == "key" and isinstance(k.value, ast.Name)
                                     and k.value.id == "review_ym_sort_key")]
        return node


def _sorted_by_month_calls(fn):
    out = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "sorted" and n.args:
            a0 = n.args[0]
            if (isinstance(a0, ast.Call) and isinstance(a0.func, ast.Attribute) and a0.func.attr == "keys"
                    and isinstance(a0.func.value, ast.Name) and a0.func.value.id == "by_month"):
                out.append(n)
    return out


def _format_calls(fn):
    return [n for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "format_review_period_label"]


def _const(node):
    return node.value if isinstance(node, ast.Constant) else object()


class TestScopeGuardA3(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.target = _loader.rev_path(NEW_REV)
        cls.baseline = _loader.rev_path(OLD_REV)
        if not (os.path.isfile(cls.target) and os.path.isfile(cls.baseline)):
            raise unittest.SkipTest("A3のリビジョン対(20261004_02 / 20261004_03)が無い")
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
        for n in sorted(ALLOWED_TO_CHANGE):
            with self.subTest(function=n):
                self.assertIn(n, old_f)
                self.assertIn(n, new_f)
                self.assertNotEqual(old_f[n], new_f[n], f"A3 で変更するはずの {n} が変更されていない")

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
                self.assertEqual(shell, self.new[4].get(cls_name),
                                 f"クラス {cls_name} の骨格(継承・デコレータ・クラス直下の文)が変わっている")

    def test_new_names_are_added_at_module_level(self):
        for n in NEW_FUNCTIONS:
            with self.subTest(function=n):
                self.assertIn(n, self.new[0])
                self.assertNotIn(n, self.old[0])
        for n in NEW_CONSTANTS:
            with self.subTest(constant=n):
                self.assertIn(n, self.new[1])
                self.assertNotIn(n, self.old[1])

    def test_nothing_else_was_added_beyond_the_names_in_the_spec(self):
        """追加された関数/定数は、仕様の許可リスト (必須の7関数+REVIEW_WINDOW_MONTHS、任意の _review_month_list_text / _REVIEW_YM_RE) だけ。"""
        # 仕様 (A3_SPEC_DELTA_fix1.md「範囲ガード」) の「新規追加してよい名前」は次のとおりで、これ以外の追加は仕様外:
        #   定数 REVIEW_WINDOW_MONTHS (必須) と 非公開の _REVIEW_YM_RE (無くてもよい)
        #   関数 review_month_range / review_yyyymm / review_default_selected / review_quarter_choices /
        #        review_ym_sort_key / format_review_period_label / review_cache_gaps (必須) と
        #        非公開ヘルパ _review_month_list_text (無くてもよい)
        added_f = sorted(set(self.new[0]) - set(self.old[0]))
        added_c = sorted(set(self.new[1]) - set(self.old[1]))
        beyond_f = sorted(set(added_f) - set(OPTIONAL_NEW_PRIVATE_FUNCTIONS))
        beyond_c = sorted(set(added_c) - set(OPTIONAL_NEW_PRIVATE_CONSTANTS))
        self.assertEqual(beyond_f, sorted(NEW_FUNCTIONS), f"仕様に無い関数/メソッドが追加されている: {added_f}")
        self.assertEqual(beyond_c, sorted(NEW_CONSTANTS), f"仕様に無い定数が追加されている: {added_c}")

    def test_functions_the_spec_says_are_unchanged_are_identical(self):
        for name in UNCHANGED_BY_SPEC:
            with self.subTest(name=name):
                hits = [q for q in self.old[0] if q == name or q.endswith("." + name)]
                self.assertTrue(hits, f"{name} が旧版に見つからない (比較の前提が崩れた)")
                for q in hits:
                    self.assertIn(q, self.new[0])
                    self.assertEqual(self.new[0][q], self.old[0][q], f"{q} が変更されている")

    def test_generate_review_report_changed_only_in_the_timeline_sort_call(self):
        old_fn = method_node(self.baseline, "HTMLReportGenerator", "generate_review_report")
        new_fn = method_node(self.target, "HTMLReportGenerator", "generate_review_report")
        self.assertEqual(ast.dump(_DropReviewSortKey().visit(copy.deepcopy(new_fn))), ast.dump(old_fn),
                         "月別タイムラインの sorted(..., key=review_ym_sort_key) 以外の箇所が変更されている")

    def test_timeline_sort_is_sorted_by_month_with_review_ym_sort_key_descending(self):
        new_fn = method_node(self.target, "HTMLReportGenerator", "generate_review_report")
        calls = _sorted_by_month_calls(new_fn)
        self.assertEqual(len(calls), 1, "sorted(by_month.keys(), ...) が1か所のはず")
        kws = {k.arg: k.value for k in calls[0].keywords}
        self.assertIsInstance(kws.get("key"), ast.Name)
        self.assertEqual(kws["key"].id, "review_ym_sort_key")
        self.assertIs(_const(kws.get("reverse")), True)

    def test_run_and_reformat_review_use_format_review_period_label_for_period_label(self):
        """_run_review / _reformat_review は format_review_period_label で期間表示を作る。呼び出しは、全員合算の期間表示 (保存する結果用:
        period_label) と、対象者が2人以上のときの各人の期間表示 (A3_SPEC_DELTA_fix2.md) があってよい。どの呼び出しも mode を明示し
        (run / reformat)、run は今回更新した月を渡し、reformat は None を渡す。欠けは review_cache_gaps の結果から作る。"""
        for meth, mode, second_is_none in (("_run_review", "run", False), ("_reformat_review", "reformat", True)):
            with self.subTest(method=meth):
                fn = method_node(self.target, "MailManagerGUI", meth)
                calls = _format_calls(fn)
                self.assertGreaterEqual(len(calls), 1, f"{meth}: format_review_period_label を呼ぶはず")
                for call in calls:
                    kws = {k.arg: k.value for k in call.keywords}
                    self.assertEqual(_const(kws.get("mode")), mode, f"{meth}: mode={mode!r} を明示する")
                    second = call.args[1] if len(call.args) >= 2 else kws.get("selected_months")
                    self.assertIsNotNone(second, f"{meth}: 第2引数 (selected_months) がある")
                    if second_is_none:
                        self.assertIsNone(_const(second), f"{meth}: reformat では selected_months=None")
                    else:
                        self.assertNotIsInstance(second, ast.Constant, f"{meth}: run では今回更新した月を渡す")
                gap_calls = [n for n in ast.walk(fn)
                             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "review_cache_gaps"]
                self.assertGreaterEqual(len(gap_calls), 1, f"{meth}: 期間表示の「未取得/AI失敗」は review_cache_gaps の結果から作るはず")


if __name__ == "__main__":
    unittest.main(verbosity=2)
