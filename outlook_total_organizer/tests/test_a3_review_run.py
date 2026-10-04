# -*- coding: utf-8 -*-
"""A3「振り返りタブの月範囲」追加テスト (仕様書 A3_SPEC.md + 敵対的レビュー後の変更点 A3_SPEC_DELTA_fix1.md / A3_SPEC_DELTA_fix2.md)。

第2回の変更点 (fix2) への追随: review_cache_gaps は進行中の当月 (now の年月) を未取得に数えない (当月の AI失敗は数える。
dict でない JSON は「キャッシュ無し」)、期間表示の「未取得/AI失敗」は対象者ごと (各人のレポートはその人だけ、保存する結果と
完了ステータスは合算)、「前月のみ」は前月が一覧に無いとき案内ダイアログ、窓幅は12月 (1年12か月が1行) も630pxで切れない。

A7a (振り返りの費用の事前見積り・確認 = _20261004_05 以降) への追随 (A3 の観点は弱めていない。_03 / _04 でもそのまま通る):
  - _run_review は self.config['gemini_model'] を読む (実機の __init__ は self.config = load_config() を持つ) ので、
    偽GUIにも config (DEFAULT_CONFIG のコピー) を持たせる。無いと AttributeError → 「❌ 失敗しました」になり、
    完了を待つテストが毎回タイムアウト (15秒) していた。
  - 完了ステータスの形が変わった: 「✅ 振り返り生成完了」+ 費用の文言 +（あれば）A3 の「（⚠ 未取得…）」通知。
    今回の実行でAI分析に失敗した「月×対象者」があれば、先頭は「⚠ 振り返り生成完了（AI失敗N件。その月を再実行で再試行）」(費用の文言は「成功{N件−失敗}/{件数}件」)。
    失敗は「❌ 失敗しました: …」(+エラーダイアログ)、費用の確認で中止は「⏹ …」。split_done_status が形を厳密に分け、
    A3 の観点 (通知がステータスの末尾に出る/出ない・未取得/AI失敗の件数) は、分けた「通知」の部分に対してこれまでどおり確かめる。
  - 失敗・中止のステータスが出たら、15秒待たずにその場で原因つきで失敗にする。

【なぜ必要か】 レビューで「_run_review を実行するテストが無く、all_months に選択月を渡す誤り
(= 常に「全月更新」になる / 12か月ぶんの表示にならない) が全73件をすり抜ける」と指摘された。
このファイルは、偽のOutlook・偽のAIを載せた画面で、本物の _run_review / generate_review_data /
_reformat_review を最後まで通し、次を確かめる。
  - 画面の12か月がそのまま generate_review_data の all_months に渡る (選択月だけではない)
  - 期間表示が「更新した月」「／未取得」「／AI失敗」を正しく表す (全月更新・キャッシュのみ・再構成を含む)
  - 年またぎ・月またぎ (10/31 に作った画面を 11/1 に操作) でも月が一覧の外に出ない
  - 「全て」チェックの連動、「前月のみ」は押した時点の前月、四半期ボタンの行の構成
  - 窓幅 630px 相当で、上段・四半期の行・年ごとの行・説明文の要求幅が収まる

仕様書だけを根拠に、実装 (_20261004_03.py の review_cache_gaps / _review_month_list_text / _ui_review_tab /
_run_review / _reformat_review) の中身を見ずに書いている。
  - 仕様に明記された挙動            -> 通常の TestCase
  - 仕様が曖昧/未記載で「最も自然な解釈」で書いたもの
                                    -> クラス名に SpecGap を含む (コメントに解釈を明記)
    SpecGap の失敗は「バグ」ではなく「仕様の確認が必要」の合図として扱う。

構成
  1. review_quarter_choices: 部分四半期の名前
  2. review_cache_gaps
  3. format_review_period_label: 「／未取得」「／AI失敗」の足し方
  4. _get_review_all_months: 画面の一覧から取る
  5. _ui_review_tab の画面構成 (行の構成・説明文) と docstring
  6. 「全て」の連動 / 「前月のみ」は押した時点の前月 / 月またぎ
  7. 窓幅 630px 相当の要求幅 (フォント固定。上限は実測 + 約10%)
  8. 機能テスト: 偽Outlook・偽AIで _run_review / generate_review_data / _reformat_review を通す

方針
  - 「今日」は固定日付で与える (実際の日付には依存しない)。Outlook(COM)・AI・ネットワークには一切触れない
    (偽AIは MailSummarizer の _run_genai_call_with_schema だけを置き換える。Gemini クライアントは作らない)。
  - ワーカースレッドの root.after は mainloop が回っているときだけ動く。待機は test_a1_gui_smoke の
    pump/settle (after で条件を監視して quit する mainloop) を使う。長い sleep はしない。
  - 実行: cd outlook_total_organizer && xvfb-run -a /usr/bin/python3.12 tests/run_tests.py a3_review_run
  - 「このテストは本当に誤りを見つけられるか」の確認 (変異テスト): 実装のコピーに誤りを1つ入れ、OTO_TARGET でその版を指して
    このファイルだけを走らせる (例: _run_review が all_months に選択月を渡す版 -> 8章の多くが失敗するはず)。
        OTO_TARGET=/path/to/壊した版.py xvfb-run -a /usr/bin/python3.12 tests/run_tests.py a3_review_run
"""
import inspect
import json
import os
import re
import threading
import types
import unittest
import webbrowser
from datetime import datetime
from unittest import mock

import _loader
from _loader import tempdir_cwd
import test_a1_gui_smoke as a1gui            # pump / settle (mainloop + quit 方式) などの待機ヘルパを借りる
import test_a3_review_months as a3m          # 画面の部品探索 (ReviewGuiCase) と共通の固定日付・参照実装を借りる
from test_a3_review_months import (
    ALL_1004, BASE_1004, BUTTON_CLASSES, CHECK_CLASSES, COMMA, LABEL_CLASSES, LPAR, NOW_0115, NOW_1004, NOW_1231,
    RPAR, SWEEP_COUNTS, SWEEP_NOWS, WAVE, find, ref_quarters, ref_range, split_ym, timeline_headings, wtext, ym,
)

tk = a3m.tk
ttk = a3m.ttk
try:
    import tkinter.font as tkfont
except Exception:                                              # pragma: no cover
    tkfont = None


def oto():
    return _loader.load()


# ============================================================
# 共通: 固定日付 / 参照実装 / キャッシュの置き場
# ============================================================
NOW_1031 = datetime(2026, 10, 31, 23, 0, 0)      # 月末 (この日に画面を作る)
NOW_1101 = datetime(2026, 11, 1, 9, 0, 0)        # 月が替わった翌朝 (同じ画面を操作する)
NOW_1215 = datetime(2026, 12, 15, 9, 0, 0)       # 2か月進んだ日 (前月 202611 は 10/31 に作った一覧に無い)
NOW_2027_0315 = datetime(2027, 3, 15, 9, 0, 0)   # ずっと先の日 (一覧が日付に引きずられないことの確認)

ALL_0115 = [ym(y, m) for y, m in ref_range(NOW_0115)]        # 202502 .. 202601 (年またぎの12か月)

# 振り返りキャッシュのファイル名の対象者サフィックス (_review_person_cache_suffix: Ochi は空、他は "__" + 英数字化した名前)
PERSON_SUFFIX = {"Ochi": "", "Saji": "__Saji", "Yuto Oi": "__Yuto_Oi"}


def freeze_module_clock(test, fixed):
    """対象モジュールの datetime.now()/today() を固定日付にする (そのテストが終わるまで)。GUI を使わないテスト用。"""
    class FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed if tz is None else fixed.replace(tzinfo=tz)

        @classmethod
        def today(cls):
            return fixed

        @classmethod
        def utcnow(cls):
            return fixed

    p = mock.patch.object(oto(), "datetime", FakeDatetime)
    p.start()
    test.addCleanup(p.stop)


def cache_file(yyyymm, person="Ochi"):
    return os.path.join(oto().REVIEW_CACHE_DIR, f"{yyyymm}{PERSON_SUFFIX[person]}.json")


def cached_achievement(yyyymm, person="Ochi"):
    """summarize_review_month がキャッシュへ保存する、annotate 済みの実績1件と同じ形 (年月ラベルは「{年}年{月}月」)。"""
    y, m = split_ym(yyyymm)
    return {
        "title": f"{y}年{m}月の実績({person})", "summary": "要約", "source_thread_ids": [f"conv-{yyyymm}-{person.lower()}"],
        "is_confirmed": True, "activity_type": "decision", "goal_keys": ["G1_project"], "project_key": "Japan_Site",
        "has_quantitative_effect": False, "quantitative_note": "", "site_wide": False,
        "completed_date": f"{y}-{m:02d}-15", "year_month": yyyymm, "person": person,
        "tier1": [], "tier2": [], "staff_involved": [], "staff_involved_labels": [],
        "g2_subcategory": None, "g2_subcategory_label": "", "rank": "A", "rank_label": "A", "type_label": "判断・決裁",
        "project_label": "Japan Site", "matched_meetings": [], "year_month_label": f"{y}年{m}月", "is_manual": False,
        "thread_entry_id": None, "thread_topic": "",
    }


def put_cache(yyyymm, person="Ochi", *, error=False, achievements=None, raw=None):
    """analysis_cache/review_monthly/ に、summarize_review_month が書くのと同じ形式のキャッシュを置く。
    raw (bytes/str) を渡すと、その中身をそのまま書く (壊れたファイルの再現用)。"""
    path = cache_file(yyyymm, person)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if raw is not None:
        _loader.write_bytes(path, raw if isinstance(raw, bytes) else raw.encode("utf-8"))
        return path
    if achievements is None:
        achievements = [cached_achievement(yyyymm, person)]
    _loader.write_json(path, {"item_count": len(achievements), "achievements": achievements, "_error": bool(error)})
    return path


def month_text(yyyymm):
    """参照実装: "202608" -> "2026年8月" (月は先頭の0なし)。"""
    y, m = split_ym(yyyymm)
    return f"{y}年{m}月"


def gap_list_text(months):
    """参照実装 (仕様 3.): 最大6か月までは「YYYY年M月」を「、」でつなぎ、7か月以上は「N か月分」(例 "11か月分")。"""
    if len(months) <= 6:
        return COMMA.join(month_text(mm) for mm in months)
    return f"{len(months)}か月分"


def gap_suffix(missing=None, failed=None):
    """参照実装 (仕様 3.): 本体の後ろに「／未取得: ...」「／AI失敗: ...」をこの順で足す。空/None は足さない。"""
    out = ""
    if missing:
        out += "／未取得: " + gap_list_text(missing)
    if failed:
        out += "／AI失敗: " + gap_list_text(failed)
    return out


# ============================================================
# 1. review_quarter_choices: 部分四半期の名前 (A3_SPEC_DELTA_fix1.md 1.)
# ============================================================
class TestQuarterNamesForPartialQuarters(unittest.TestCase):
    """範囲の端で3か月に満たない四半期は、含まれる月を括弧で付ける。1か月だけ "(10月)"、複数 "(11-12月)"。
    3か月そろう四半期は括弧なし。仕様の例以外にも、同じ規則から導ける具体例で固定する。"""

    def names(self, now, count=12):
        return [n for n, _months in oto().review_quarter_choices(now, count)]

    def test_one_month_quarter_has_that_month_in_parentheses(self):
        """1か月だけの四半期は「2026年Q4(10月)」のように、月を1つだけ括弧で付ける (月の先頭の0なし)。"""
        cases = ((datetime(2026, 10, 4), "2026年Q4(10月)"), (datetime(2026, 1, 15), "2026年Q1(1月)"),
                 (datetime(2026, 3, 31), "2026年Q1(3月)"), (datetime(2026, 4, 1), "2026年Q2(4月)"),
                 (datetime(2026, 9, 9), "2026年Q3(9月)"), (datetime(2026, 12, 31), "2026年Q4(12月)"))
        for now, expected in cases:
            with self.subTest(now=now.date().isoformat()):
                self.assertEqual(self.names(now, 1), [expected])

    def test_two_month_quarter_is_first_dash_last(self):
        """2か月の四半期は「2025年Q4(11-12月)」のように first-last月 (月の先頭の0なし)。"""
        cases = ((datetime(2026, 2, 10), "2026年Q1(1-2月)"), (datetime(2026, 3, 31), "2026年Q1(2-3月)"),
                 (datetime(2026, 5, 20), "2026年Q2(4-5月)"), (datetime(2026, 9, 1), "2026年Q3(8-9月)"),
                 (datetime(2026, 12, 31), "2026年Q4(11-12月)"))
        for now, expected in cases:
            with self.subTest(now=now.date().isoformat()):
                self.assertEqual(self.names(now, 2), [expected])

    def test_both_ends_are_marked_when_the_range_starts_and_ends_mid_quarter(self):
        """範囲の両端がどちらも部分四半期なら、両方に括弧が付く。"""
        self.assertEqual(self.names(datetime(2026, 4, 1), 2), ["2026年Q1(3月)", "2026年Q2(4月)"])
        self.assertEqual(self.names(datetime(2026, 5, 15), 3), ["2026年Q1(3月)", "2026年Q2(4-5月)"])
        self.assertEqual(self.names(datetime(2026, 8, 31), 3), ["2026年Q2(6月)", "2026年Q3(7-8月)"])
        self.assertEqual(self.names(datetime(2026, 11, 30), 5), ["2026年Q3", "2026年Q4(10-11月)"])      # 7〜9月はそろう

    def test_full_quarters_have_no_parentheses_even_at_the_ends(self):
        """3か月そろう四半期は、範囲の端であっても括弧が付かない (「2026年Q1」)。"""
        self.assertEqual(self.names(datetime(2026, 3, 31), 3), ["2026年Q1"])
        self.assertEqual(self.names(datetime(2026, 6, 30), 6), ["2026年Q1", "2026年Q2"])
        self.assertEqual(self.names(datetime(2026, 12, 31), 12), ["2026年Q1", "2026年Q2", "2026年Q3", "2026年Q4"])
        self.assertEqual(self.names(datetime(2026, 4, 1), 4), ["2026年Q1", "2026年Q2(4月)"])
        self.assertEqual(self.names(datetime(2026, 5, 31), 5), ["2026年Q1", "2026年Q2(4-5月)"])

    def test_punctuation_is_ascii_and_months_are_not_zero_padded(self):
        """括弧は半角 ( )、区切りは半角 -、月は0埋めなし (「(4-5月)」であって「(04-05月)」「（4～5月）」ではない)。"""
        name = self.names(datetime(2026, 5, 20), 2)[0]
        self.assertEqual(name, "2026年Q2(4-5月)")
        self.assertEqual(name.encode("ascii", "ignore").decode(), "2026Q2(4-5)")    # 非ASCIIは「年」「月」だけ
        one = self.names(datetime(2026, 4, 1), 1)[0]
        self.assertEqual(one, "2026年Q2(4月)")

    def test_names_follow_the_rule_for_every_date_and_count(self):
        """全月の1日・末日 × count 1〜24: 括弧が付くのは3か月に満たない四半期だけ、括弧の中身は含まれる月と一致、
        範囲の端以外の四半期は必ず3か月そろう (参照実装を使わない不変条件の確認)。"""
        pat = re.compile(r"^(\d{4})年Q([1-4])(?:\((\d{1,2})(?:-(\d{1,2}))?月\))?$")
        for now in SWEEP_NOWS:
            for count in SWEEP_COUNTS:
                got = oto().review_quarter_choices(now, count)
                label = f"{now:%Y-%m-%d} count={count}"
                for i, (name, months) in enumerate(got):
                    m = pat.match(name)
                    self.assertIsNotNone(m, f"{label}: 想定外の名前 {name!r}")
                    first, last = split_ym(months[0])[1], split_ym(months[-1])[1]
                    if len(months) == 3:
                        self.assertEqual(name, f"{m.group(1)}年Q{m.group(2)}", f"{label}: 3か月そろうのに括弧が付いている")
                    elif len(months) == 1:
                        self.assertEqual(m.group(3), str(first), f"{label}: {name!r} {months}")
                        self.assertIsNone(m.group(4), f"{label}: 1か月なのに範囲表記: {name!r}")
                    else:
                        self.assertEqual((m.group(3), m.group(4)), (str(first), str(last)), f"{label}: {name!r} {months}")
                    if 0 < i < len(got) - 1:
                        self.assertEqual(len(months), 3, f"{label}: 端以外の四半期は3か月そろうはず: {name!r}")


# ============================================================
# 2. review_cache_gaps (A3_SPEC_DELTA_fix1.md 2.)
# ============================================================
class ReviewCacheGapsCase(unittest.TestCase):
    """空の一時cwd (analysis_cache/review_monthly の置き場) の中で review_cache_gaps を呼ぶ。
    第3引数 now (進行中の当月の判定に使う日付) は、検査する月 (2025〜2026年) より先の固定日付 GAPS_NOW を既定で渡す
    = どの月も「進行中の当月」にならない (実際の日付には依存しない)。当月の扱いは TestReviewCacheGapsCurrentMonth で確かめる。"""

    GAPS_NOW = datetime(2030, 6, 15, 9, 0, 0)

    def setUp(self):
        cm = tempdir_cwd()
        self.tmp = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)

    def gaps(self, all_months, persons=None, now=None):
        return oto().review_cache_gaps(all_months, persons, now=self.GAPS_NOW if now is None else now)


class TestReviewCacheGaps(ReviewCacheGapsCase):
    """各 "YYYYMM" と各対象者について {YYYYMM}{サフィックス}.json を読み、無い/読めない/壊れている月は missing、
    JSON が dict で "_error" が真の月は failed。空の実績 (achievements: []、_error 偽) は正常。"""

    def test_all_months_present_and_normal_means_no_gaps(self):
        """全部のキャッシュが正常 (実績あり) なら ([], [])。"""
        for mm in ALL_1004:
            put_cache(mm)
        self.assertEqual(self.gaps(ALL_1004), ([], []))

    def test_empty_achievements_are_normal(self):
        """実績が0件のキャッシュ (_error 偽。_error キーが無い形も含む) は正常で、missing にも failed にも入らない。"""
        put_cache("202601", achievements=[])                                                    # "_error": false
        put_cache("202602", raw=json.dumps({"item_count": 0, "achievements": []}))              # _error キー無し (threads が空のとき)
        put_cache("202603", raw=json.dumps({"item_count": 0, "achievements": [], "_error": False}))
        self.assertEqual(self.gaps(["202601", "202602", "202603"]), ([], []))

    def test_missing_file_is_missing_and_not_failed(self):
        """キャッシュの無い月は missing (failed ではない)。古い順。"""
        put_cache("202601")
        put_cache("202603")
        self.assertEqual(self.gaps(["202601", "202602", "202603", "202604"]), (["202602", "202604"], []))

    def test_without_the_cache_folder_every_month_is_missing(self):
        """analysis_cache/ 自体が無くても例外を出さず、全部の月が missing。"""
        self.assertFalse(os.path.exists("analysis_cache"))
        self.assertEqual(self.gaps(["202512", "202601"]), (["202512", "202601"], []))

    def test_unreadable_or_broken_files_are_missing(self):
        """壊れている (空ファイル・JSON の途中切れ・文字化け・UTF-8 でないバイト列) /読めない (同名のフォルダ) ファイルは
        missing。例外は出さない。"""
        os.makedirs(os.path.dirname(cache_file("202601")), exist_ok=True)
        put_cache("202601", raw="")
        put_cache("202602", raw='{"item_count": 2, "achievements": [')
        put_cache("202603", raw="これはJSONではありません")
        put_cache("202604", raw=b"\xff\xfe\x00\x81\x82 not utf-8")
        os.makedirs(cache_file("202605"))                          # ファイルの代わりにフォルダがある = 読めない
        put_cache("202606")                                        # 正常
        got = self.gaps(["202601", "202602", "202603", "202604", "202605", "202606"])
        self.assertEqual(got, (["202601", "202602", "202603", "202604", "202605"], []))

    def test_error_true_is_failed_and_not_missing(self):
        """JSON が dict で "_error" が真の月は failed (missing ではない)。実績が残っていても failed。"""
        put_cache("202607", error=True, achievements=[])
        put_cache("202608", error=True)                            # 実績が1件あるが _error 真
        put_cache("202609")
        self.assertEqual(self.gaps(["202607", "202608", "202609"]), ([], ["202607", "202608"]))

    def test_missing_and_failed_are_both_reported_oldest_first(self):
        """missing と failed が混在しても、それぞれ古い順の "YYYYMM" のリスト (タプルの1つ目が missing、2つ目が failed)。"""
        put_cache("202511")
        put_cache("202512", error=True)
        put_cache("202601", error=True)
        put_cache("202603")
        got = self.gaps(["202511", "202512", "202601", "202602", "202603", "202604"])
        self.assertEqual(got, (["202602", "202604"], ["202512", "202601"]))
        missing, failed = got
        self.assertIsInstance(missing, list)
        self.assertIsInstance(failed, list)
        self.assertTrue(all(isinstance(mm, str) and re.fullmatch(r"\d{6}", mm) for mm in missing + failed))

    def test_twelve_month_window_across_years(self):
        """直近12か月 (年またぎ 2025-11〜2026-10) をそのまま渡せる: 年をまたいだファイル名も正しく引く。
        今日が 2026-10-04 なら進行中の当月 (202610) は未取得に数えないので、未取得は 202603・202608・202609 の3か月。"""
        for mm in ALL_1004[:3] + ALL_1004[5:9]:
            put_cache(mm)
        put_cache(ALL_1004[3], error=True)
        self.assertEqual(self.gaps(ALL_1004, now=NOW_1004), (ALL_1004[4:5] + ALL_1004[9:11], ALL_1004[3:4]))

    def test_default_person_is_ochi_and_other_persons_files_are_ignored(self):
        """既定の対象者は Ochi (サフィックス無しの {YYYYMM}.json)。他の対象者のファイルは数えない。"""
        put_cache("202601", person="Saji")
        put_cache("202602", person="Ochi")
        self.assertEqual(self.gaps(["202601", "202602"]), (["202601"], []))
        self.assertEqual(oto().review_cache_gaps(["202601", "202602"], now=self.GAPS_NOW), (["202601"], []),
                         "persons を省略しても同じ")

    def test_none_or_empty_persons_means_ochi(self):
        """persons が None / 空リストなら ["Ochi"] 扱い。"""
        put_cache("202602", person="Ochi")
        put_cache("202601", person="Saji")
        for persons in (None, []):
            with self.subTest(persons=persons):
                self.assertEqual(self.gaps(["202601", "202602"], persons), (["202601"], []))

    def test_a_month_is_missing_if_any_person_lacks_its_file(self):
        """対象者が複数のとき、1人でもキャッシュが無ければその月は missing。"""
        put_cache("202601", person="Ochi")
        put_cache("202601", person="Saji")
        put_cache("202602", person="Ochi")                         # Saji の 202602 が無い
        put_cache("202603", person="Saji")                         # Ochi の 202603 が無い
        self.assertEqual(self.gaps(["202601", "202602", "202603"], ["Ochi", "Saji"]), (["202602", "202603"], []))

    def test_a_month_is_failed_if_any_person_has_error(self):
        """対象者が複数のとき、1人でも "_error" が真ならその月は failed。"""
        put_cache("202601", person="Ochi")
        put_cache("202601", person="Saji", error=True)
        put_cache("202602", person="Ochi", error=True)
        put_cache("202602", person="Saji")
        put_cache("202603", person="Ochi")
        put_cache("202603", person="Saji")
        self.assertEqual(self.gaps(["202601", "202602", "202603"], ["Ochi", "Saji"]), ([], ["202601", "202602"]))

    def test_the_same_month_can_be_in_both_lists(self):
        """人物ごとに状態が違うとき、同じ月が missing と failed の両方に入りうる。"""
        put_cache("202601", person="Ochi")                         # Ochi は正常
        put_cache("202602", person="Ochi", error=True)             # Ochi は失敗 (Saji は無し)
        put_cache("202603", person="Saji", error=True)             # Saji は失敗 (Ochi は無し)
        got = self.gaps(["202601", "202602", "202603"], ["Ochi", "Saji"])
        self.assertEqual(got, (["202601", "202602", "202603"], ["202602", "202603"]))
        # 202601: Ochi 有 / Saji 無 -> missing のみ。202602, 202603: 片方が失敗で片方が無し -> 両方に入る

    def test_persons_are_checked_as_given_ochi_is_not_added(self):
        """persons を渡したときは、その人たちだけを見る (Ochi を勝手に足さない)。"""
        put_cache("202601", person="Saji")
        put_cache("202602", person="Saji")
        self.assertEqual(self.gaps(["202601", "202602"], ["Saji"]), ([], []))

    def test_person_name_is_turned_into_the_cache_file_suffix(self):
        """スペースを含む名前は _review_person_cache_suffix のとおり英数字以外を _ にしたサフィックスで引く
        ("Yuto Oi" -> 202601__Yuto_Oi.json)。"""
        self.assertEqual(oto()._review_person_cache_suffix("Yuto Oi"), "__Yuto_Oi")          # 前提 (既存関数)
        put_cache("202601", person="Yuto Oi")
        put_cache("202602", person="Yuto Oi", error=True)
        self.assertTrue(os.path.isfile(os.path.join(oto().REVIEW_CACHE_DIR, "202601__Yuto_Oi.json")))
        self.assertEqual(self.gaps(["202601", "202602", "202603"], ["Yuto Oi"]), (["202603"], ["202602"]))

    def test_valid_json_that_is_not_a_dict_is_missing(self):
        """JSON として読めても dict でない (リスト・文字列・数値・null) ファイルは「キャッシュ無し」(missing) 扱い
        (読み込み側 load_review_month_cache が空扱いにするため)。failed ではない。"""
        for i, text in enumerate(("[]", "[1, 2]", '"x"', "5", "null")):
            mm = f"2026{i + 1:02d}"
            put_cache(mm, raw=text)
            with self.subTest(json=text):
                self.assertEqual(self.gaps([mm]), ([mm], []))

    def test_none_or_empty_all_months_returns_two_empty_lists(self):
        """all_months が None / 空なら ([], []) (例外は出さない)。"""
        put_cache("202601")
        for months in (None, [], ()):
            for persons in (None, ["Ochi"], ["Ochi", "Saji"]):
                with self.subTest(all_months=months, persons=persons):
                    self.assertEqual(self.gaps(months, persons), ([], []))

    def test_return_value_is_a_pair_of_new_lists(self):
        """戻り値は (missing, failed) の2要素で、どちらも list。呼ぶたびに新しい list (呼び出し側が書き換えても影響しない)。"""
        a = self.gaps(["202601"])
        self.assertEqual(len(a), 2)
        self.assertIsInstance(a[0], list)
        self.assertIsInstance(a[1], list)
        a[0].append("999999")
        self.assertEqual(self.gaps(["202601"]), (["202601"], []))


class TestReviewCacheGapsCurrentMonth(ReviewCacheGapsCase):
    """review_cache_gaps(all_months, persons=None, now=None): 進行中の当月 (now の年月) は「キャッシュが無い月」(missing) に
    数えない (既定は前月のみで当月を取得しないため)。当月でもキャッシュが _error 真なら failed には数える。
    当月でもキャッシュがあれば従来どおり。now の既定は現在日付。"""

    def test_current_month_without_cache_is_not_missing(self):
        """今日が 2026-10-04 なら、キャッシュの無い 202610 (当月) は未取得に数えない。"""
        put_cache("202609")
        self.assertEqual(self.gaps(["202609", "202610"], now=NOW_1004), ([], []))

    def test_past_month_without_cache_is_still_missing_next_to_the_current_month(self):
        """当月を数えないだけで、キャッシュの無い過去の月 (202608) は従来どおり未取得。当月 (202610) は載らない。"""
        put_cache("202609")
        self.assertEqual(self.gaps(["202608", "202609", "202610"], now=NOW_1004), (["202608"], []))

    def test_current_month_with_error_is_failed(self):
        """当月でもキャッシュが _error 真なら failed には数える (missing には数えない)。"""
        put_cache("202610", error=True)
        self.assertEqual(self.gaps(["202610"], now=NOW_1004), ([], ["202610"]))

    def test_current_month_with_a_normal_cache_is_neither(self):
        """当月でもキャッシュが正常 (実績あり・実績0件) なら、missing にも failed にも入らない。"""
        put_cache("202610")
        put_cache("202609", achievements=[])
        self.assertEqual(self.gaps(["202609", "202610"], now=NOW_1004), ([], []))

    def test_non_dict_json_in_the_current_month_is_not_missing_either(self):
        """dict でない JSON は過去の月なら missing だが、当月なら missing に数えない。"""
        put_cache("202610", raw="[]")
        put_cache("202609", raw="[]")
        self.assertEqual(self.gaps(["202609", "202610"], now=NOW_1004), (["202609"], []))

    def test_the_current_month_follows_now_not_the_real_clock(self):
        """当月は引数 now の年月で決まる: 同じキャッシュでも、now が 11月なら 202610 は過去の月なので未取得に数える。"""
        put_cache("202609")
        self.assertEqual(self.gaps(["202609", "202610"], now=NOW_1004), ([], []))
        self.assertEqual(self.gaps(["202609", "202610"], now=NOW_1101), (["202610"], []))

    def test_the_current_month_at_the_year_start(self):
        """年初 (2026-01-15) の当月は 202601。前年12月 (202512) は過去の月なので数える。"""
        self.assertEqual(self.gaps(["202512", "202601"], now=NOW_0115), (["202512"], []))

    def test_default_now_is_today(self):
        """now を省略すると現在日付 (ここでは固定した 2026-10-04) を使う: 202610 は当月なので数えない。"""
        freeze_module_clock(self, NOW_1004)
        put_cache("202609")
        self.assertEqual(oto().review_cache_gaps(["202609", "202610"]), ([], []))
        self.assertEqual(oto().review_cache_gaps(["202608", "202609", "202610"], ["Ochi"]), (["202608"], []))

    def test_current_month_with_several_persons(self):
        """対象者が複数でも当月は missing に数えない。1人でも _error なら failed に数える。"""
        put_cache("202609", "Ochi")
        put_cache("202609", "Saji")
        put_cache("202610", "Ochi", error=True)              # Saji の 202610 は無い (当月なので未取得ではない)
        self.assertEqual(self.gaps(["202609", "202610"], ["Ochi", "Saji"], now=NOW_1004), ([], ["202610"]))

    def test_a_time_of_day_does_not_matter(self):
        """now の時刻は無関係 (月末の深夜でも、月初の0時でも同じ月が当月)。"""
        self.assertEqual(self.gaps(["202610"], now=datetime(2026, 10, 1, 0, 0, 0)), ([], []))
        self.assertEqual(self.gaps(["202610"], now=datetime(2026, 10, 31, 23, 59, 59)), ([], []))
        self.assertEqual(self.gaps(["202609"], now=datetime(2026, 10, 1, 0, 0, 0)), (["202609"], []))


class TestSpecGapReviewCacheGaps(ReviewCacheGapsCase):
    """仕様が曖昧/未記載の入力。自然な解釈で書いた。"""

    def test_error_is_judged_by_truthiness(self):
        """【仕様確認】「"_error" が真」を Python の真偽で読む (True / 1 / 空でない文字列は failed、False / 0 / "" / None / キー無しは正常)。"""
        for i, value in enumerate((True, 1, "429 rate limit")):
            with self.subTest(error=value):
                mm = f"2026{i + 1:02d}"
                put_cache(mm, raw=json.dumps({"item_count": 1, "achievements": [], "_error": value}))
                self.assertEqual(self.gaps([mm]), ([], [mm]))
        for i, value in enumerate((False, 0, "", None)):
            with self.subTest(error=value):
                mm = f"2025{i + 1:02d}"
                put_cache(mm, raw=json.dumps({"item_count": 1, "achievements": [], "_error": value}))
                self.assertEqual(self.gaps([mm]), ([], []))

    def test_it_only_reads(self):
        """【仕様確認】「読む」だけの関数と読む (診断用)。ファイルもフォルダも作らず、既存のファイルの中身も更新時刻も変えない。"""
        self.assertEqual(self.gaps(["202601", "202602"]), (["202601", "202602"], []))
        self.assertFalse(os.path.exists("analysis_cache"), "キャッシュが無いときにフォルダを作ってはいけない")
        put_cache("202601")
        put_cache("202602", error=True)
        before = _loader.snapshot_files(".")
        self.gaps(["202601", "202602", "202603"], ["Ochi", "Saji"])
        self.assertEqual(_loader.snapshot_files("."), before)


# ============================================================
# 3. format_review_period_label: 「／未取得」「／AI失敗」の足し方 (A3_SPEC_DELTA_fix1.md 3.)
# ============================================================
def label(all_months, selected=None, mode="run", missing=None, failed=None):
    return oto().format_review_period_label(all_months, selected, mode=mode, missing_months=missing, failed_months=failed)


def sel(*yyyymms):
    return [split_ym(mm) for mm in yyyymms]


class TestFormatReviewPeriodLabelWithGaps(unittest.TestCase):
    """従来の本体の「後ろ」に、missing_months があれば "／未取得: ..."、failed_months があれば "／AI失敗: ..." をこの順で足す。
    各リストは最大6か月まで「YYYY年M月」を「、」でつなぎ、7か月以上は「N か月分」。None/空は足さない。"""

    def test_missing_months_are_appended_with_the_spec_example(self):
        """未取得の月は「／未取得: 2025年11月、2025年12月」の形で後ろに足す。"""
        self.assertEqual(label(ALL_1004, sel("202609"), missing=["202511", "202512"]),
                         BASE_1004 + f"{LPAR}2026年9月を更新{RPAR}／未取得: 2025年11月、2025年12月")

    def test_failed_months_are_appended_with_the_spec_example(self):
        """AI失敗の月は「／AI失敗: 2026年8月」の形で後ろに足す。"""
        self.assertEqual(label(ALL_1004, sel("202609"), failed=["202608"]),
                         BASE_1004 + f"{LPAR}2026年9月を更新{RPAR}／AI失敗: 2026年8月")

    def test_missing_comes_before_failed(self):
        """両方あるときは「／未取得: ...／AI失敗: ...」の順。"""
        self.assertEqual(label(ALL_1004, sel("202609"), missing=["202511", "202512"], failed=["202608"]),
                         BASE_1004 + f"{LPAR}2026年9月を更新{RPAR}／未取得: 2025年11月、2025年12月／AI失敗: 2026年8月")

    def test_none_and_empty_lists_add_nothing(self):
        """None / 空リストは何も足さない (従来の出力と完全に同じ)。"""
        plain = label(ALL_1004, sel("202609"))
        for missing in (None, [], ()):
            for failed in (None, [], ()):
                with self.subTest(missing=missing, failed=failed):
                    self.assertEqual(label(ALL_1004, sel("202609"), missing=missing, failed=failed), plain)
        self.assertEqual(plain, BASE_1004 + f"{LPAR}2026年9月を更新{RPAR}")

    def test_up_to_six_months_are_listed_and_seven_or_more_are_counted(self):
        """各リストは最大6か月まで列挙し、7か月以上は「N か月分」(例 "／未取得: 11か月分")。未取得・AI失敗それぞれに適用。"""
        for n in range(1, 13):
            months = ALL_1004[:n]
            with self.subTest(n=n):
                got = label(ALL_1004, sel("202609"), missing=months, failed=months)
                tail = (COMMA.join(month_text(mm) for mm in months) if n <= 6 else f"{n}か月分")
                self.assertEqual(got, BASE_1004 + f"{LPAR}2026年9月を更新{RPAR}／未取得: {tail}／AI失敗: {tail}")
        self.assertTrue(label(ALL_1004, sel("202609"), missing=ALL_1004[:11]).endswith("／未取得: 11か月分"))

    def test_boundary_six_is_listed_seven_is_counted(self):
        """境界: 6か月は列挙、7か月は件数。"""
        six = label(ALL_1004, None, missing=ALL_1004[:6])
        self.assertTrue(six.endswith("／未取得: 2025年11月、2025年12月、2026年1月、2026年2月、2026年3月、2026年4月"), six)
        seven = label(ALL_1004, None, missing=ALL_1004[:7])
        self.assertTrue(seven.endswith("／未取得: 7か月分"), seven)

    def test_months_are_written_without_zero_padding_and_across_years(self):
        """月は先頭の0なし、年をまたいでも「YYYY年M月」。"""
        got = label(ALL_1004, None, failed=["202512", "202601", "202609"])
        self.assertTrue(got.endswith("／AI失敗: 2025年12月、2026年1月、2026年9月"), got)

    def test_every_body_variant_keeps_its_body_and_gets_the_gaps_after_it(self):
        """本体 (全月更新 / …を更新 / キャッシュのみ / (Nか月を更新) / 保存済みキャッシュから再構成) はそのまま、
        その後ろに足す。"""
        gaps = "／未取得: 2026年7月／AI失敗: 2026年8月"
        cases = (
            ("全月更新", dict(selected=sel(*ALL_1004)), f"{LPAR}全月更新{RPAR}"),
            ("1か月を更新", dict(selected=sel("202609")), f"{LPAR}2026年9月を更新{RPAR}"),
            ("2か月を更新", dict(selected=sel("202512", "202601")), f"{LPAR}2025年12月{COMMA}2026年1月を更新{RPAR}"),
            ("7か月を更新", dict(selected=sel(*ALL_1004[:7])), f"{LPAR}7か月を更新{RPAR}"),
            ("キャッシュのみ", dict(selected=None), f"{LPAR}キャッシュのみ{COMMA}更新なし{RPAR}"),
            ("キャッシュのみ(空リスト)", dict(selected=[]), f"{LPAR}キャッシュのみ{COMMA}更新なし{RPAR}"),
            ("再構成", dict(selected=None, mode="reformat"), f"{LPAR}保存済みキャッシュから再構成{RPAR}"),
            ("再構成(選択あり)", dict(selected=sel("202609"), mode="reformat"), f"{LPAR}保存済みキャッシュから再構成{RPAR}"),
        )
        for title, kwargs, body in cases:
            with self.subTest(body=title):
                got = label(ALL_1004, missing=["202607"], failed=["202608"], **kwargs)
                self.assertEqual(got, BASE_1004 + body + gaps)

    def test_positional_arguments_in_the_spec_order(self):
        """引数の順は (all_months, selected_months, mode, missing_months, failed_months)。位置引数でも同じ結果。"""
        got = oto().format_review_period_label(ALL_1004, sel("202609"), "run", ["202607"], ["202608"])
        self.assertEqual(got, BASE_1004 + f"{LPAR}2026年9月を更新{RPAR}／未取得: 2026年7月／AI失敗: 2026年8月")
        got = oto().format_review_period_label(ALL_1004, None, "reformat", ["202607"])
        self.assertEqual(got, BASE_1004 + f"{LPAR}保存済みキャッシュから再構成{RPAR}／未取得: 2026年7月")

    def test_the_old_two_argument_form_is_unchanged(self):
        """missing/failed を渡さない従来の呼び方は、これまでどおりの出力 (後方互換)。"""
        f = oto().format_review_period_label
        self.assertEqual(f(ALL_1004, sel(*ALL_1004)), BASE_1004 + f"{LPAR}全月更新{RPAR}")
        self.assertEqual(f(ALL_1004, None), BASE_1004 + f"{LPAR}キャッシュのみ{COMMA}更新なし{RPAR}")
        self.assertEqual(f(ALL_1004, None, mode="reformat"), BASE_1004 + f"{LPAR}保存済みキャッシュから再構成{RPAR}")

    def test_reference_suffix_matches_for_every_combination_of_list_sizes(self):
        """未取得 n 件 × AI失敗 k 件 (0〜12) の全組み合わせで、参照実装の足し方と一致する (6/7 の境界を含む)。"""
        for n in range(0, 13):
            for k in range(0, 13):
                with self.subTest(missing=n, failed=k):
                    missing, failed = ALL_1004[:n], ALL_1004[12 - k:]
                    self.assertEqual(label(ALL_1004, sel("202609"), missing=missing, failed=failed),
                                     BASE_1004 + f"{LPAR}2026年9月を更新{RPAR}" + gap_suffix(missing, failed))


# ============================================================
# 4. _get_review_all_months: 画面の一覧から取る (A3_SPEC_DELTA_fix1.md 4.)
# ============================================================
class TestGetReviewAllMonthsWithoutScreen(unittest.TestCase):
    """画面の月チェックボックス一覧 (v_review_month_vars) のキーを sorted して返す。一覧がまだ無い (属性が無い/空) ときだけ、
    従来どおり review_month_range(datetime.now()) から計算する。画面 (tkinter) 無しで確かめられる部分。"""

    def bare_gui(self):
        mod = oto()
        return mod.MailManagerGUI.__new__(mod.MailManagerGUI)

    def test_without_the_list_it_is_computed_from_today(self):
        """一覧の属性が無いときは、今日 (固定日付) から直近12か月を古い順に計算する。"""
        freeze_module_clock(self, NOW_1004)
        gui = self.bare_gui()
        self.assertFalse(hasattr(gui, "v_review_month_vars"))
        self.assertEqual(gui._get_review_all_months(), ALL_1004)
        freeze_module_clock(self, NOW_0115)
        self.assertEqual(gui._get_review_all_months(), ALL_0115)

    def test_with_an_empty_list_it_is_computed_from_today(self):
        """一覧が空のときも、今日から計算する。"""
        freeze_module_clock(self, NOW_1004)
        gui = self.bare_gui()
        gui.v_review_month_vars = {}
        self.assertEqual(gui._get_review_all_months(), ALL_1004)

    def test_with_a_list_it_is_the_sorted_keys_whatever_today_is(self):
        """一覧があるときは、そのキーを古い順に並べて返す。今日の日付 (固定: 2027-03-15) は使わない。"""
        freeze_module_clock(self, NOW_2027_0315)
        gui = self.bare_gui()
        gui.v_review_month_vars = {"202603": None, "202511": None, "202601": None, "202512": None}
        self.assertEqual(gui._get_review_all_months(), ["202511", "202512", "202601", "202603"])
        gui.v_review_month_vars = {mm: None for mm in reversed(ALL_1004)}
        self.assertEqual(gui._get_review_all_months(), ALL_1004)
        self.assertNotEqual(ALL_1004, [ym(y, m) for y, m in ref_range(NOW_2027_0315)], "前提: 今日から計算すると別の12か月になる")


class TestGetReviewAllMonthsOnScreen(a3m.ReviewGuiCase):
    """画面の一覧を使うこと: アプリを起動したまま月をまたいでも、画面に出ている月と選べる月が食い違わない。"""

    def test_the_list_on_screen_wins_after_the_date_moves_on(self):
        """画面を 2026-10-04 に作り、日付を 2027-03-15 まで進めても、_get_review_all_months は画面の12か月 (2025-11〜2026-10) のまま。"""
        gui = self.make_gui(NOW_1004)
        self.assertEqual(gui._get_review_all_months(), ALL_1004)
        self.freeze_today(NOW_2027_0315)
        got = gui._get_review_all_months()
        self.assertEqual(got, ALL_1004)
        self.assertEqual(got, sorted(gui.v_review_month_vars))
        self.assertNotEqual(got, [ym(y, m) for y, m in ref_range(NOW_2027_0315)], "今日から計算した値になっている")

    def test_the_result_is_oldest_first_across_years(self):
        """古い順 (年またぎでも 202511, 202512, 202601 ... の順)。"""
        for today in (NOW_1004, NOW_0115, NOW_1231):
            with self.subTest(today=today.date().isoformat()):
                gui = self.make_gui(today)
                got = gui._get_review_all_months()
                self.assertEqual(got, [ym(y, m) for y, m in ref_range(today)])
                self.assertEqual(got, sorted(got))
                self.close_gui(gui)


# ============================================================
# 5. _ui_review_tab の画面構成 (A3_SPEC_DELTA_fix1.md 5.)
# ============================================================
class ReviewRowsCase(a3m.ReviewGuiCase):
    """画面の「行」を、見た目どおり (縦の中心が近い部品を同じ行とみなす) に調べる補助。"""

    LINE_TOLERANCE = 3                       # 同じ行とみなす縦の中心のずれ (px)

    def named_label(self, text):
        found = [w for w in find(self.gui.tab_review, LABEL_CLASSES) if wtext(w) == text]
        self.assertEqual(len(found), 1, f"ラベル {text!r} が{len(found)}個。部品: {self.dump()}")
        return found[0]

    @staticmethod
    def center_y(w):
        return w.winfo_rooty() + w.winfo_height() / 2

    def line_of(self, ref):
        """ref と同じ行に見えている部品 (ラベル・ボタン・チェックボタン) を、左から順に返す。"""
        y0 = self.center_y(ref)
        same = [w for w in find(self.gui.tab_review, LABEL_CLASSES + BUTTON_CLASSES + CHECK_CLASSES)
                if w.winfo_ismapped() and abs(self.center_y(w) - y0) <= self.LINE_TOLERANCE]
        return sorted(same, key=lambda w: w.winfo_rootx())

    def line_texts(self, ref):
        return [wtext(w) for w in self.line_of(ref)]

    def description_label(self):
        found = [w for w in find(self.gui.tab_review, LABEL_CLASSES) if "既定は前月のみ" in (wtext(w) or "")]
        self.assertEqual(len(found), 1, f"説明文のラベルが{len(found)}個。部品: {self.dump()}")
        return found[0]


class TestReviewTabRows(ReviewRowsCase):
    """1行目 = 対象月 (全て・前月のみ)、2行目 = 四半期 (四半期ボタン)、その下に年ごとの月チェックボックス行。"""

    def test_first_row_has_only_the_label_the_all_check_and_the_prev_month_button(self):
        """1行目 (「対象月:」の行) は「全て」チェックと「前月のみ」ボタンだけ。四半期ボタンも月チェックボックスも置かない。"""
        for today in (NOW_1004, NOW_0115):
            with self.subTest(today=today.date().isoformat()):
                self.make_gui(today)
                texts = self.line_texts(self.named_label("対象月:"))
                self.assertEqual(len(texts), 3, f"1行目の部品: {texts}")
                self.assertEqual(texts[0], "対象月:")
                self.assertIn("全て", texts[1])
                self.assertEqual(texts[2], "前月のみ")
                self.close_gui(self.gui)

    def test_second_row_is_the_quarter_label_and_the_quarter_buttons_in_order(self):
        """2行目 (新設) はラベル「四半期:」と四半期ボタン (review_quarter_choices の名前) を古い四半期から順に左から並べる。"""
        for today in (NOW_1004, NOW_0115):
            with self.subTest(today=today.date().isoformat()):
                self.make_gui(today)
                texts = self.line_texts(self.named_label("四半期:"))
                self.assertEqual(texts, ["四半期:"] + [name for name, _ms in ref_quarters(today)])
                self.close_gui(self.gui)

    def test_quarter_buttons_are_not_in_the_first_row(self):
        """四半期ボタンは1行目に置かない (1行目と2行目は別の高さ)。"""
        self.make_gui(NOW_1004)
        top = self.named_label("対象月:")
        quarter = self.named_label("四半期:")
        self.assertGreater(self.center_y(quarter) - self.center_y(top), 8, "四半期の行が1行目の下に来ていない")
        top_line = set(self.line_texts(top))
        for name, _ms in ref_quarters(NOW_1004):
            self.assertNotIn(name, top_line)

    def test_rows_are_stacked_top_to_bottom_first_quarter_then_years(self):
        """上から 1行目(対象月) → 2行目(四半期) → 年ごとの月チェックボックス行 (古い年が上) の順。"""
        for today in (NOW_1004, NOW_0115, NOW_1231):
            with self.subTest(today=today.date().isoformat()):
                self.make_gui(today)
                ys = [self.center_y(self.named_label("対象月:")), self.center_y(self.named_label("四半期:"))]
                years = self.year_labels()
                ys += [self.center_y(years[y]) for y in sorted(years)]
                self.assertEqual(ys, sorted(ys), f"行の縦の並び: {ys}")
                self.assertEqual(len(set(round(v) for v in ys)), len(ys), "別々の行になっていない")
                self.close_gui(self.gui)

    def test_year_rows_keep_the_months_and_are_not_mixed_with_the_buttons(self):
        """年ごとの行には、その年の月チェックボックスだけが並ぶ (四半期ボタン・「全て」は混ざらない)。"""
        self.make_gui(NOW_1004)
        years = self.year_labels()
        self.assertEqual(sorted(years), [2025, 2026])
        self.assertEqual(self.line_texts(years[2025]), ["2025年:", "11月", "12月"])
        self.assertEqual(self.line_texts(years[2026]), ["2026年:"] + [f"{m}月" for m in range(1, 11)])

    def test_description_starts_with_the_two_notice_lines_from_the_spec(self):
        """説明文は、最長だった1行目を2行に分けた「※ 既定は前月のみにチェックが入っています(直近12か月・年またぎ)。」/
        「四半期ボタンで、その四半期の月をまとめて選べます。」で始まる。"""
        self.make_gui(NOW_1004)
        lines = wtext(self.description_label()).split("\n")
        self.assertEqual(lines[0], "※ 既定は前月のみにチェックが入っています(直近12か月・年またぎ)。")
        self.assertEqual(lines[1], "四半期ボタンで、その四半期の月をまとめて選べます。")

    def test_description_keeps_the_existing_explanation_after_the_notice(self):
        """追加した2行のあとに、従来の説明 (チェックした月だけ再取得・チェックを外した月はキャッシュ利用 ...) が残っている。"""
        self.make_gui(NOW_1004)
        text = wtext(self.description_label())
        for needle in ("チェックの付いた月だけ", "チェックを外した月は", "analysis_cache/review_monthly/", "2か月より前はオンラインアーカイブ"):
            self.assertIn(needle, text)


class TestDocstringsMentionThe12MonthWindow(unittest.TestCase):
    """docstring の「当年1月〜当月」は「直近12か月・年またぎ」に更新 (A3_SPEC_DELTA_fix1.md 6.)。"""

    METHODS = ("_ui_review_tab", "_get_review_all_months", "_run_review")

    def test_old_wording_is_gone_and_new_wording_is_in(self):
        """_ui_review_tab / _get_review_all_months / _run_review の docstring から「当年1月〜当月」が消え、「直近12か月・年またぎ」になっている。"""
        for name in self.METHODS:
            with self.subTest(method=name):
                doc = inspect.getdoc(getattr(oto().MailManagerGUI, name)) or ""
                self.assertNotIn("当年1月", doc, f"{name} の docstring に古い「当年1月〜当月」が残っている")
                self.assertIn("直近12か月・年またぎ", doc, f"{name} の docstring が「直近12か月・年またぎ」になっていない")


# ============================================================
# 6. 「全て」の連動 / 「前月のみ」は押した時点の前月 / 月またぎ (A3_SPEC_DELTA_fix1.md 5.)
# ============================================================
class TestAllCheckboxFollowsTheMonthChecks(a3m.ReviewGuiCase):
    """「全て」: 月チェックボックスを手で付け外ししたときも連動する (全部ONなら ON、1つでもOFFなら OFF)。
    四半期ボタン・前月のみボタンの後も連動する。操作は実際の部品の invoke (人がクリックするのと同じ経路) で行う。"""

    def test_turning_on_the_remaining_months_by_hand_turns_all_on(self):
        """既定 (前月のみON) から、残りの11か月を1つずつ手でONにすると、最後の1つで「全て」がONになる (それまではOFF)。"""
        gui = self.make_gui(NOW_1004)
        checks = self.month_checks()
        self.assertFalse(gui.v_review_all.get())
        rest = [mm for mm in sorted(checks) if mm != "202609"]
        for i, mm in enumerate(rest):
            self.click(checks[mm])
            if i < len(rest) - 1:
                self.assertFalse(gui.v_review_all.get(), f"{i + 1}個目 ({mm}) をONにした時点で「全て」がONになっている")
        self.assertTrue(gui.v_review_all.get(), "全部ONにしたのに「全て」がOFFのまま")
        self.assertEqual(self.on_months(), set(ALL_1004))

    def test_turning_off_any_one_month_by_hand_turns_all_off(self):
        """「全て」ONの状態から月を1つ手でOFFにすると「全て」がOFFになり、戻すとまたONになる。他の月はそのまま。"""
        gui = self.make_gui(NOW_1004)
        self.click(self.all_check())
        self.assertTrue(gui.v_review_all.get())
        checks = self.month_checks()
        for mm in ("202511", "202604", "202610"):                      # 最古・途中・最新のどれを外しても同じ
            with self.subTest(month=mm):
                self.click(checks[mm])
                self.assertFalse(gui.v_review_all.get(), f"{mm} を外したのに「全て」がONのまま")
                self.assertEqual(self.on_months(), set(ALL_1004) - {mm})
                self.click(checks[mm])
                self.assertTrue(gui.v_review_all.get(), f"{mm} を戻したのに「全て」がOFFのまま")
                self.assertEqual(self.on_months(), set(ALL_1004))

    def test_all_check_after_a_manual_uncheck_selects_everything_again(self):
        """手で1つ外したあとに「全て」を押すと、全選択に戻る (全解除にならない)。以前は「全て」がONのまま残り、押すと全解除になった。"""
        gui = self.make_gui(NOW_1004)
        self.click(self.all_check())                                    # 全ON
        self.click(self.month_checks()["202610"])                        # 10月だけ手で外す -> 全てOFF
        self.assertFalse(gui.v_review_all.get())
        self.click(self.all_check())
        self.assertTrue(gui.v_review_all.get())
        self.assertEqual(self.on_months(), set(ALL_1004), "「全て」を押したのに全部ONになっていない")

    def test_all_check_stays_off_after_prev_month_and_quarter_buttons(self):
        """四半期ボタン・前月のみボタンのあとも、全部ONでなければ「全て」はOFF (従来どおり)。"""
        gui = self.make_gui(NOW_1004)
        self.click(self.all_check())
        self.assertTrue(gui.v_review_all.get())
        self.click(self.button("2026年Q1"))
        self.assertFalse(gui.v_review_all.get())
        self.assertEqual(self.on_months(), {"202601", "202602", "202603"})
        self.click(self.all_check())
        self.click(self.button("前月のみ"))
        self.assertFalse(gui.v_review_all.get())
        self.assertEqual(self.on_months(), {"202609"})

    def test_checking_every_month_by_hand_after_a_quarter_button_turns_all_on(self):
        """四半期ボタンのあとに、残りの月を手でONにしていって全部ONになったら「全て」もON。"""
        gui = self.make_gui(NOW_1004)
        self.click(self.button("2026年Q2"))
        checks = self.month_checks()
        for mm in sorted(checks):
            if mm not in self.on_months():
                self.click(checks[mm])
        self.assertEqual(self.on_months(), set(ALL_1004))
        self.assertTrue(gui.v_review_all.get())


class TestPrevMonthButtonUsesTheTimeOfThePress(a3m.ReviewGuiCase):
    """「前月のみ」は、画面を作った時点の値を使い回さず、押した時点の review_default_selected(datetime.now()) を選ぶ。
    選ぶのは画面の一覧にある月だけ (一覧に無い月は無視)。アプリを起動したまま月をまたぐ場面 (10/31 → 11/1)。"""

    def test_pressed_after_the_month_changed_it_selects_the_new_previous_month(self):
        """10/31 に作った画面 (既定は9月) を 11/1 に操作して「前月のみ」を押すと、10月だけがONになる (9月ではない)。"""
        gui = self.make_gui(NOW_1031)
        self.assertEqual(self.on_months(), {"202609"}, "前提: 10/31 に作ったときの既定は前月 (9月)")
        self.freeze_today(NOW_1101)
        self.click(self.button("前月のみ"))
        self.assertEqual(self.on_months(), {"202610"})
        self.assertEqual(gui._get_review_selected_months(), [(2026, 10)])
        self.assertFalse(gui.v_review_all.get())

    def test_the_month_list_does_not_move_when_the_date_moves(self):
        """日付が月をまたいでも、画面の月の一覧は 2025-11〜2026-10 のまま (11月は増えず、2025年11月も消えない)。"""
        gui = self.make_gui(NOW_1031)
        self.freeze_today(NOW_1101)
        self.assertEqual(gui._get_review_all_months(), ALL_1004)
        self.click(self.button("前月のみ"))
        self.assertEqual(sorted(gui.v_review_month_vars), ALL_1004)
        self.assertEqual(gui._get_review_all_months(), ALL_1004)
        self.assertNotIn("202611", gui.v_review_month_vars)

    def test_selected_months_never_leave_the_screen_list(self):
        """「前月のみ」・四半期ボタン・「全て」のどれを押しても、選択月 (_get_review_selected_months) は一覧の中の月だけ。"""
        gui = self.make_gui(NOW_1031)
        self.freeze_today(NOW_1101)
        allowed = {split_ym(mm) for mm in ALL_1004}
        for action in (lambda: self.click(self.button("前月のみ")), lambda: self.click(self.all_check()),
                       lambda: self.click(self.button("2025年Q4(11-12月)")), lambda: self.click(self.button("前月のみ"))):
            action()
            self.assertTrue(set(gui._get_review_selected_months()) <= allowed, gui._get_review_selected_months())
            self.assertTrue(set(gui._get_review_selected_months()) <= {split_ym(mm) for mm in gui._get_review_all_months()})

    def test_pressed_the_same_day_it_still_selects_the_previous_month(self):
        """(回帰) 月をまたがない通常の場合は、これまでどおり前月だけがON。"""
        gui = self.make_gui(NOW_1004)
        self.click(self.all_check())
        self.click(self.button("前月のみ"))
        self.assertEqual(self.on_months(), {"202609"})


class TestPrevMonthButtonWhenTheListIsStale(a3m.ReviewGuiCase):
    """「前月のみ」: 押した時点の前月が画面の月一覧に1つも無い (起動したまま2か月以上またいだ) ときは、チェックを変えず、
    showinfo(「月の一覧が古くなっています」, 「月が変わったため、前月がこの一覧にありません。\nアプリを開き直すと、最新の月の一覧に
    なります。」) を出す。一覧にあれば従来どおり (選んで「全て」を連動)。"""

    TITLE = "月の一覧が古くなっています"
    MESSAGE = "月が変わったため、前月がこの一覧にありません。\nアプリを開き直すと、最新の月の一覧になります。"

    def infos(self):
        """messagebox.showinfo に渡った (タイトル, 本文) の一覧。"""
        out = []
        for name, args, kwargs in self.dialogs:
            if name == "showinfo":
                out.append((args[0] if args else kwargs.get("title"), args[1] if len(args) > 1 else kwargs.get("message")))
        return out

    def stale_gui(self):
        """10/31 に作った画面 (一覧は 2025-11〜2026-10) を、2か月進んだ 12/15 (前月 202611 は一覧に無い) に操作する。"""
        gui = self.make_gui(NOW_1031)
        self.freeze_today(NOW_1215)
        return gui

    def test_guide_dialog_is_shown_with_the_spec_title_and_message(self):
        """前月が一覧に無いとき、案内ダイアログ (showinfo) が1回だけ、仕様どおりのタイトルと本文で出る。"""
        self.stale_gui()
        self.click(self.button("前月のみ"))
        self.assertEqual(self.infos(), [(self.TITLE, self.MESSAGE)])

    def test_only_an_info_dialog_is_used(self):
        """案内は情報ダイアログ (showinfo) だけ。警告・エラー・確認のダイアログは出さない。"""
        self.stale_gui()
        self.click(self.button("前月のみ"))
        self.assertEqual([name for name, _a, _k in self.dialogs], ["showinfo"])

    def test_checks_are_left_as_they_were_from_the_default(self):
        """案内を出すとき、チェックは変えない: 既定 (9月だけON) のまま。"""
        gui = self.stale_gui()
        self.assertEqual(self.on_months(), {"202609"})
        self.click(self.button("前月のみ"))
        self.assertEqual(self.on_months(), {"202609"})
        self.assertFalse(gui.v_review_all.get())

    def test_checks_are_left_as_they_were_when_everything_is_on(self):
        """全ONのときに押しても、チェックも「全て」も変わらない (全解除にならない)。"""
        gui = self.stale_gui()
        self.click(self.all_check())
        self.click(self.button("前月のみ"))
        self.assertEqual(self.on_months(), set(ALL_1004))
        self.assertTrue(gui.v_review_all.get())

    def test_checks_are_left_as_they_were_for_a_partial_selection(self):
        """一部の月だけONのときに押しても、そのまま (四半期ボタンで選んだ2026年Q1が残る)。"""
        self.stale_gui()
        self.click(self.button("2026年Q1"))
        self.click(self.button("前月のみ"))
        self.assertEqual(self.on_months(), {"202601", "202602", "202603"})

    def test_selected_months_do_not_change_either(self):
        """案内を出したあとも、選択月 (生成時に取得する月) は変わらず、一覧の外の月 (202611) は含まれない。"""
        gui = self.stale_gui()
        self.click(self.button("前月のみ"))
        self.assertEqual(gui._get_review_selected_months(), [(2026, 9)])
        self.assertNotIn("202611", gui.v_review_month_vars)

    def test_no_dialog_when_the_previous_month_is_on_the_list(self):
        """月が1つ替わっただけ (11/1。前月 202610 は一覧にある) なら、案内は出ず、従来どおり前月だけを選ぶ。"""
        gui = self.make_gui(NOW_1031)
        self.freeze_today(NOW_1101)
        self.click(self.button("前月のみ"))
        self.assertEqual(self.infos(), [])
        self.assertEqual(self.on_months(), {"202610"})
        self.assertFalse(gui.v_review_all.get())

    def test_no_dialog_on_the_same_day(self):
        """月をまたいでいない通常の場合 (10/4 に作って 10/4 に押す) も、案内は出ない。"""
        self.make_gui(NOW_1004)
        self.click(self.button("前月のみ"))
        self.assertEqual(self.infos(), [])
        self.assertEqual(self.on_months(), {"202609"})

    def test_no_dialog_at_the_year_start(self):
        """年初 (1/15 に作って 1/15 に押す。前月は前年12月で一覧にある) も、案内は出ない。"""
        self.make_gui(NOW_0115)
        self.click(self.button("前月のみ"))
        self.assertEqual(self.infos(), [])
        self.assertEqual(self.on_months(), {"202512"})

    def test_no_dialog_from_the_other_buttons(self):
        """四半期ボタン・「全て」では、一覧が古くなっていても案内は出ない (「前月のみ」だけの案内)。"""
        self.stale_gui()
        self.click(self.button("2026年Q1"))
        self.click(self.all_check())
        self.assertEqual(self.infos(), [])


# ============================================================
# 7. 窓幅 630px 相当の要求幅 (A3_SPEC_DELTA_fix1.md 5.)
# ============================================================
# 窓が狭い (半画面・表示倍率150% で約630px) と、1行目・四半期の行・年ごとの行・説明文が切れる、という指摘への対応。
# 幅はフォントとテーマに依存するので、フォントを固定する (IPAPGothic 9pt・96dpi。Windows の日本語UIの近似) +
# Windows の vista テーマ相当のボタン最小幅 (-width -11) を再現し、上限は「実測 + 約10%」にしてある。
# 固定フォントが無い環境では skip する。
PINNED_FONT = "IPAPGothic"
PINNED_FONT_SIZE = 9
NAMED_FONTS = ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont", "TkSmallCaptionFont",
               "TkIconFont", "TkTooltipFont", "TkFixedFont")
NARROW_WINDOW_WIDTH = 630

# 実測値 (固定フォントでの要求幅 px) と、約10%の余裕を持たせた上限 (年ごとの行だけは窓の内側の幅に合わせて締める)
#   ROW_TOP_MAX      : 1行目 (対象月: 全て 前月のみ)                       実測 200 (どの日付でも同じ) -> 220
#   ROW_QUARTER_MAX  : 2行目 (四半期: + 四半期ボタン最大5つ)                 実測 最大 582 (10月・11月。1月は558、12月は443) -> 641
#   ROW_YEAR_MAX     : 年ごとの行 (月チェックボックスの行)                  実測 最大 591 (12月=1年12か月が1行。次は11月の541、
#                      1月の549) -> 600 (窓の内側の幅 598px にそろえた。padx を (0,4) に戻すと 615、年ラベル幅を広げると 631)
#   DESC_LINE1_MAX   : 説明文の追加した1行目 (※ 既定は前月のみ…)             実測 351 -> 387
#   DESC_LINE2_MAX   : 説明文の追加した2行目 (四半期ボタンで…)               実測 269 -> 296
# 窓幅630pxの内側の幅は 598px (Notebook の padx と枠、タブの余白を除く)。上限 (要求幅) の検査に加えて、10月・11月・1月・12月の
# どれでも、1行目・四半期の行・年ごとの行の部品が、この内側に切れずに収まっていること (実際の幅 >= 要求幅) も別に確かめる。
ROW_TOP_MAX = 220
ROW_QUARTER_MAX = 641
ROW_YEAR_MAX = 600
DESC_LINE1_MAX = 387
DESC_LINE2_MAX = 296


class NarrowWindowCase(ReviewRowsCase):
    """フォント・テーマ・拡大率を固定した、幅 630px の窓に振り返りタブを組み立てる。実機と同じく Notebook は padx=5, pady=5。"""

    WINDOW_GEOMETRY = f"{NARROW_WINDOW_WIDTH}x700+0+0"
    NOTEBOOK_PACK = ({"fill": tk.BOTH, "expand": True, "padx": 5, "pady": 5} if tk is not None else {})

    def _prepare_root(self, root):
        root.tk.call("tk", "scaling", 96 / 72)
        probe = tkfont.Font(root=root, family=PINNED_FONT, size=PINNED_FONT_SIZE)
        if probe.actual("family") != PINNED_FONT:
            root.destroy()
            self.skipTest(f"固定フォント {PINNED_FONT} が無い環境 (幅の上限は {PINNED_FONT} での実測値が前提)")
        for name in NAMED_FONTS:
            tkfont.Font(root=root, name=name, exists=True).configure(family=PINNED_FONT, size=PINNED_FONT_SIZE)
        style = ttk.Style(root)
        style.configure("TButton", anchor="center", padding=(1, 1), width=-11)       # Windows vista テーマの既定
        style.configure("TCheckbutton", padding=2)

    def req_width(self, text_label):
        """text_label を含む行 (そのラベルの親フレーム) の要求幅。"""
        return text_label.master.winfo_reqwidth()

    def rows_of_interest(self):
        """[(行の名前, 行フレーム)]: 1行目 / 四半期 / 年ごとの行。ラベルと同じ親フレームに、その行の部品が全部入っている前提。"""
        rows = [("1行目(対象月)", self.named_label("対象月:").master), ("2行目(四半期)", self.named_label("四半期:").master)]
        for year, lbl in sorted(self.year_labels().items()):
            rows.append((f"{year}年の行", lbl.master))
        return rows


class TestReviewTabFitsANarrowWindow(NarrowWindowCase):
    """窓幅 630px 相当 (半画面・表示倍率150%) で、1行目・四半期行・年ごとの行・説明文が切れない。"""

    # 四半期ごとの振り返りをする時期 (10月上旬・1月中旬)、四半期の行が最長になる11月、年ごとの行が最長になる12月 (1年12か月が1行)
    STRICT_DATES = (NOW_1004, NOW_1101, NOW_0115, NOW_1231)

    def test_rows_and_widgets_are_not_clipped_in_a_630px_window(self):
        """630px の窓で、1行目・四半期の行・年ごとの行のどの部品も、説明文も、切れず (要求幅どおりの幅で)・窓の内側に表示される。
        10月・11月・1月に加えて、1年12か月が1行になる12月でも。"""
        for today in self.STRICT_DATES:
            with self.subTest(today=today.date().isoformat()):
                self.make_gui(today)
                root = self.gui.root
                self.assertEqual(root.winfo_width(), NARROW_WINDOW_WIDTH, "窓幅が630pxになっていない")
                right_edge = root.winfo_rootx() + root.winfo_width()
                parts = [(f"{row_name} の {wtext(w)!r}", w) for row_name, row in self.rows_of_interest()
                         for w in row.winfo_children()]
                parts.append(("説明文", self.description_label()))
                for where, w in parts:
                    self.assertTrue(w.winfo_ismapped(), f"{where} が表示されていない")
                    self.assertGreaterEqual(w.winfo_width(), w.winfo_reqwidth(), f"{where} の幅が足りず切れている")
                    self.assertLessEqual(w.winfo_rootx() + w.winfo_width(), right_edge, f"{where} が窓の右端からはみ出ている")
                self.close_gui(self.gui)

    def test_december_year_row_fits_in_a_630px_window(self):
        """12月 (一覧が1年分12か月の1行。2026-12-31) でも、年ごとの行は 630px 窓の内側 (約598px) に収まり、最後の「12月」まで
        切れずに見える。以前は 615px で「12月」が切れた。"""
        self.make_gui(NOW_1231)
        years = self.year_labels()
        self.assertEqual(sorted(years), [2026], "前提: 1年分12か月の1行")
        row = years[2026].master
        self.assertLessEqual(row.winfo_reqwidth(), row.winfo_width(), "年の行の要求幅が窓の内側を超えている")
        last = self.month_checks()["202612"]
        self.assertTrue(last.winfo_ismapped())
        self.assertGreaterEqual(last.winfo_width(), last.winfo_reqwidth(), "「12月」のチェックボックスが切れている")
        root = self.gui.root
        self.assertLessEqual(last.winfo_rootx() + last.winfo_width(), root.winfo_rootx() + root.winfo_width(),
                             "「12月」が窓の右端からはみ出ている")

    def test_first_row_width_stays_small(self):
        """1行目 (対象月: 全て 前月のみ) の要求幅は上限以内 (四半期ボタンを戻すと大きく超える)。3つの日付のどれでも。"""
        for today in (NOW_1004, NOW_0115, NOW_1231):
            with self.subTest(today=today.date().isoformat()):
                self.make_gui(today)
                width = self.req_width(self.named_label("対象月:"))
                self.assertLessEqual(width, ROW_TOP_MAX, f"1行目の要求幅 {width}px が上限 {ROW_TOP_MAX}px を超えた")
                self.close_gui(self.gui)

    def test_quarter_row_width_stays_within_the_limit(self):
        """四半期の行 (四半期: + 四半期ボタン) の要求幅は、4つの日付 (四半期ボタンが5つになる日を含む) で上限以内。"""
        for today in (NOW_1004, NOW_1101, NOW_0115, NOW_1231):
            with self.subTest(today=today.date().isoformat()):
                self.make_gui(today)
                width = self.req_width(self.named_label("四半期:"))
                self.assertLessEqual(width, ROW_QUARTER_MAX, f"四半期の行の要求幅 {width}px が上限 {ROW_QUARTER_MAX}px を超えた")
                self.close_gui(self.gui)

    def test_year_rows_width_stays_within_the_limit(self):
        """年ごとの行 (年ラベル + その年の月) の要求幅は、4つの日付 (12月は1年12か月が1行) で上限 (窓の内側の幅に合わせた約600px) 以内。"""
        for today in (NOW_1004, NOW_1101, NOW_0115, NOW_1231):
            with self.subTest(today=today.date().isoformat()):
                self.make_gui(today)
                for year, lbl in sorted(self.year_labels().items()):
                    width = self.req_width(lbl)
                    self.assertLessEqual(width, ROW_YEAR_MAX, f"{year}年の行の要求幅 {width}px が上限 {ROW_YEAR_MAX}px を超えた")
                self.close_gui(self.gui)

    def test_description_notice_lines_are_short_enough(self):
        """説明文の追加した2行 (既定は前月のみ… / 四半期ボタンで…) は、1行ずつの文字幅が上限以内。
        (最長だった1行目を2行に分けた。1行に戻すと両方の合計 = 上限を大きく超える)"""
        self.make_gui(NOW_1004)
        label_w = self.description_label()
        font = tkfont.Font(root=self.gui.root, name="TkDefaultFont", exists=True)
        lines = wtext(label_w).split("\n")
        w1, w2 = font.measure(lines[0]), font.measure(lines[1])
        self.assertLessEqual(w1, DESC_LINE1_MAX, f"説明文の1行目 {w1}px が上限 {DESC_LINE1_MAX}px を超えた: {lines[0]!r}")
        self.assertLessEqual(w2, DESC_LINE2_MAX, f"説明文の2行目 {w2}px が上限 {DESC_LINE2_MAX}px を超えた: {lines[1]!r}")


# ============================================================
# 8. 機能テスト: 偽Outlook・偽AI で、本物の _run_review / generate_review_data / _reformat_review を通す
# ============================================================
class FakeOutlook:
    """Outlook(COM) の代わり。_run_review が使う3メソッドだけを持ち、何を取得したかを記録する (COM には触れない)。
    スレッドの束ね方 (group_by_thread) は COM を使わない整形処理なので、実物をそのまま使う。"""

    user_smtp_address = "ochi@example.com"

    def __init__(self, with_staff=()):
        self.fetched = []                                 # get_review_mails_for_month に渡った (年, 月)
        self.with_staff = tuple(with_staff)
        self.group_by_thread = types.MethodType(oto().OutlookMailManager.group_by_thread, self)

    @staticmethod
    def _mail(year, month, tag, sender_name, sender_email, to):
        cid = f"conv-{year}{month:02d}-{tag}"
        return {
            "conversation_id": cid, "entry_id": f"E-{year}{month:02d}-{tag}", "subject": f"件名{year}{month:02d}-{tag}",
            "conversation_topic": f"件名{year}{month:02d}-{tag}", "received": datetime(year, month, 15, 10, 0),
            "sender_name": sender_name, "sender_email": sender_email, "importance": 1, "unread": False,
            "routing": "from_me", "to_emails": list(to), "cc_emails": [], "body": "本文", "html_body": "",
            "categories": "", "flag_status": 0, "folder": "送信済み", "attachment_names": [],
        }

    def get_review_mails_for_month(self, year, month, progress_callback=None):
        self.fetched.append((year, month))
        mails = [self._mail(year, month, "ochi", "Ochi", self.user_smtp_address, ["partner@example.com"])]
        for person in self.with_staff:
            mails.append(self._mail(year, month, person.lower(), person, f"{person.lower()}@example.com",
                                    ["partner@example.com"]))
        return mails

    def get_review_calendar_events(self, year, month, progress_callback=None):
        return []


def make_fake_summarizer(fail=()):
    """MailSummarizer の実物から、Gemini 呼び出し (_run_genai_call_with_schema) だけを偽物に差し替えたもの。
    __init__ (Gemini クライアントの生成) は呼ばない。ネットワークには触れない。
    fail: {("YYYYMM", "対象者のタグ(小文字)")} の組は、AI が失敗 (_error) を返す。
    ai_calls: AI が呼ばれた [("YYYYMM", タグ)] の記録。"""
    mod = oto()
    s = mod.MailSummarizer.__new__(mod.MailSummarizer)
    s.total_input_tokens = 0
    s.total_output_tokens = 0
    s.ai_calls = []
    s.fail_set = set(fail)                              # 失敗させる (YYYYMM, タグ) の組。完了ステータスの「AI失敗N件」の確認に使う

    def fake_call(prompt, schema, override_model=None):
        ids = re.findall(r"スレッドID: (conv-(\d{6})-([a-z]+))", prompt)
        assert ids, "プロンプトにスレッドIDが無い (偽AIの前提が崩れた)"
        yyyymm, tag = ids[0][1], ids[0][2]
        s.ai_calls.append((yyyymm, tag))
        if (yyyymm, tag) in fail:
            return {"_error": True, "summary": "429 rate limit (偽AI)"}
        y, m = split_ym(yyyymm)
        return {"achievements": [{
            "title": f"{y}年{m}月の実績({tag})", "summary": "要約", "source_thread_ids": [cid],
            "is_confirmed": True, "activity_type": "decision", "goal_keys": ["G1_project"], "project_key": "Japan_Site",
            "has_quantitative_effect": False, "quantitative_note": "", "site_wide": False,
            "completed_date": f"{y}-{m:02d}-15"} for cid, _mm, _tag in ids]}

    s._run_genai_call_with_schema = fake_call
    return s


# ---- 完了ステータスの形 (A7a = _20261004_05 以降で変わった。_03 / _04 は A3 のまま) ---------------------------------
#   _03 / _04 : 「✅ 振り返り生成完了」+ A3 の通知 (あれば)
#   _05 以降  : 「✅ 振り返り生成完了」+ 費用の文言 + A3 の通知 (あれば)
#               今回の実行でAI分析に失敗した「月×対象者」があるときは、先頭が「⚠ 振り返り生成完了（AI失敗N件。その月を再実行で再試行）」(費用の文言は「成功{N件−失敗}/{件数}件」) (A7a 追記2)
# A3 の通知 = 「（⚠ 未取得Nか月・AI失敗Mか月あり。レポートの期間表示を確認してください）」(欠けがあるときだけ・必ず末尾)。
DONE_HEAD = "✅ 振り返り生成完了"
AI_FAIL_HEAD_RE = r"⚠ 振り返り生成完了（AI失敗(?P<failed>\d+)件。その月を再実行で再試行）"
COST_TEXT_RE = r"（今回のAI費用 約\d+(?:\.\d+)?円・(?:成功(?P<ok>\d+)/)?(?P<calls>\d+)件）|（新しい分析は不要でした）"
GAP_NOTE_RE = r"（⚠ [^（）]*あり。レポートの期間表示を確認してください）"
ABORT_PREFIXES = ("❌ 失敗しました", "⏹ 費用の確認で中止しました")        # _05 以降の失敗・中止のステータス (待たずに失敗にする)
DONE_PREFIXES = (DONE_HEAD, "⚠ 振り返り生成完了（AI失敗")                         # 完了 (AI失敗ありの完了を含む)


def has_cost_report():
    """このリビジョンが A7a (振り返りの費用の事前見積り・確認。_20261004_05 以降) を含むか。完了ステータスの形が変わる。"""
    return hasattr(oto(), "estimate_review_cost")


def split_done_status(status):
    """完了ステータスを head (先頭) / cost (費用の文言) / note (A3の通知) に分けて SimpleNamespace で返す。
    _03 / _04 では cost は空。head がAI失敗ありの完了のときは failed にその件数 (それ以外は None)、
    cost が「N件」(AI失敗ありのときは「成功X/N件」) のときは calls に N (「新しい分析は不要」・_03/_04 は None)。
    AI失敗ありの先頭なら費用の文言は必ず「成功{N−失敗}/{N}件」、失敗が無いなら「成功X/N件」の形にならないことも確かめる。
    想定の形 (上の説明) でなければ AssertionError。先頭・費用・通知の他に余計な文言が混じっても失敗にする。"""
    if has_cost_report():
        pattern = rf"(?P<head>{DONE_HEAD}|{AI_FAIL_HEAD_RE})(?P<cost>{COST_TEXT_RE})(?P<note>{GAP_NOTE_RE})?"
    else:
        pattern = rf"(?P<head>{DONE_HEAD})(?P<cost>)(?P<note>{GAP_NOTE_RE})?"
    m = re.fullmatch(pattern, status)
    if m is None:
        raise AssertionError(f"完了ステータスが想定の形でない: {status!r}")
    groups = m.groupdict()
    failed = int(groups["failed"]) if groups.get("failed") else None
    ok = int(groups["ok"]) if groups.get("ok") else None
    calls = int(groups["calls"]) if groups.get("calls") else None
    if failed is not None and (ok is None or calls is None or ok != calls - failed):
        raise AssertionError(f"AI失敗ありの完了なのに、費用の文言が「成功{{N−失敗}}/{{N}}件」でない: {status!r}")
    if failed is None and ok is not None:
        raise AssertionError(f"AI失敗が無いのに、費用の文言が「成功X/N件」の形: {status!r}")
    return types.SimpleNamespace(
        head=groups["head"], cost=groups["cost"], note=groups["note"] or "",
        failed=int(groups["failed"]) if groups.get("failed") else None,
        calls=int(groups["calls"]) if groups.get("calls") else None)


class ReviewRunCase(a3m.ReviewGuiCase):
    """偽Outlook・偽AIを載せた画面で、本物の _run_review / generate_review_data / _reformat_review を動かす土台。
    ワーカースレッドの root.after は mainloop が回っているときだけ動くので、待機は test_a1_gui_smoke の pump/settle を借りる。"""

    pump = a1gui.GuiCase.pump
    settle = a1gui.GuiCase.settle
    worker_threads = a1gui.GuiCase.worker_threads
    _patch_thread_excepthook = a1gui.GuiCase._patch_thread_excepthook

    def setUp(self):
        super().setUp()                                   # 一時cwd / messagebox の記録 / 後始末 (GUI の破棄)
        self.thread_errors = []
        self._patch_thread_excepthook()
        self.baseline_threads = set(threading.enumerate())
        self.statuses = []                                # _set_status に渡った文言 (メインスレッドへ戻ってきた順)
        self.opened = []                                  # webbrowser.open に渡ったレポートのパス
        self.gen_calls = []                               # generate_review_data へ渡った引数の記録
        p = mock.patch.object(webbrowser, "open", lambda url, *a, **k: self.opened.append(url) or True)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self._finish_workers)             # 後始末は後入れ先出し: GUI の破棄 (_teardown_guis) より先に走る

    def _finish_workers(self):
        if self.gui is not None and self.worker_threads():
            self.pump(lambda: not self.worker_threads(), timeout=5)
            self.settle(0.05)
        if self.worker_threads():
            self.fail(f"ワーカースレッドが終わらない: {self.worker_threads()}")
        if self.thread_errors:
            self.fail(f"ワーカースレッドの未処理例外: {self.thread_errors}")

    # ---- 構築 ---------------------------------------------------------------
    def make_run_gui(self, today, staffs=None, fail=()):
        gui = self.make_gui(today, staffs=staffs)
        self.outlook = FakeOutlook(with_staff=tuple((staffs or {}).keys()))
        self.summarizer = make_fake_summarizer(fail=fail)
        real_generate = self.summarizer.generate_review_data

        def spy(monthly_threads, monthly_meetings, all_target_months, *args, **kwargs):
            persons = kwargs.get("persons", args[1] if len(args) > 1 else None)
            self.gen_calls.append({"all_months": list(all_target_months), "fetched_months": sorted(monthly_threads),
                                   "persons": list(persons) if persons else persons})
            return real_generate(monthly_threads, monthly_meetings, all_target_months, *args, **kwargs)

        self.summarizer.generate_review_data = spy
        gui.outlook = self.outlook
        gui.summarizer = self.summarizer
        gui.reporter = oto().HTMLReportGenerator(os.path.join(os.getcwd(), "out"), 8765)
        gui._set_status = lambda text, *a, **k: self.statuses.append(text)
        # 実機の MailManagerGUI.__init__ は self.config = load_config() を持つ。A7a (_05 以降) の _run_review は
        # config の gemini_model を読む (費用の事前見積り・実績ログ用) ので、__new__ で作る偽GUIにも用意する。
        # (load_config() は json/ を作ってしまうため使わず、既定値のコピーを置く。test_a1_gui_smoke.py と同じ)
        gui.config = dict(oto().DEFAULT_CONFIG)
        return gui

    # ---- 実行 (ワーカースレッドの完了まで mainloop を回して待つ) ----------------------
    def _run(self, gui, method, done_prefix, timeout=15, abort_prefixes=()):
        """method を実行し、done_prefix (文字列か、その組) で始まるステータスが出るまで待つ。abort_prefixes で始まるステータス
        (失敗・中止) が出たら、残りの時間を待たずに、そのステータスと出たダイアログを添えて失敗にする。"""
        done = (done_prefix,) if isinstance(done_prefix, str) else tuple(done_prefix)
        abort = tuple(abort_prefixes)
        n = len(self.statuses)
        getattr(gui, method)()
        ok = self.pump(lambda: any(s.startswith(done + abort) for s in self.statuses[n:]), timeout=timeout)
        self.assertTrue(ok, f"{method} が {timeout}秒で終わらない。ステータス: {self.statuses[n:][-5:]}")
        aborted = [s for s in self.statuses[n:] if s.startswith(abort)] if abort else []
        if aborted:
            self.fail(f"{method} が完了せずに終わった: {aborted[-1]!r}。ダイアログ: {self.dialogs}")
        self.pump(lambda: not self.worker_threads(), timeout=5)
        self.settle(0.05)
        self.assertEqual(self.thread_errors, [], "ワーカースレッドで例外")
        self.assertEqual(self.callback_errors, [], "Tkコールバックで例外 (生成処理の途中で落ちた疑い)")
        # A7a (_05 以降): 見込みが100円以上なら「AI費用の確認」(askyesno) が出る。これは正常な動き (偽の messagebox が「はい」を返して続行する。
        # 単価表や既定モデルが変わっても A3 のテストが巻き込まれないよう、このダイアログだけは許す)。それ以外のダイアログは従来どおり失敗。
        unexpected = [d for d in self.dialogs if not (d[0] == "askyesno" and d[1] and d[1][0] == "AI費用の確認")]
        self.assertEqual(unexpected, [], "エラー等のダイアログが出た")
        return [s for s in self.statuses[n:] if s.startswith(done)][-1]

    def run_review(self, gui):
        """「📈 振り返りを生成」を実行し、完了時のステータス文言を返す。
        完了 =「✅ 振り返り生成完了…」か (A7a: 今回AI分析に失敗した月×対象者があるとき)「⚠ 振り返り生成完了（AI失敗N件。…）」。
        「❌ 失敗しました」「⏹ 費用の確認で中止しました」(_05 以降) は完了とみなさず、その場で失敗にする。"""
        n_ai = len(self.summarizer.ai_calls)
        status = self._run(gui, "_run_review", DONE_PREFIXES, abort_prefixes=ABORT_PREFIXES)
        self.check_done_status(status, self.summarizer.ai_calls[n_ai:])
        return status

    def check_done_status(self, status, ai_calls):
        """完了ステータスの形が想定どおりで、(_05 以降は) 費用の文言の件数・AI失敗の件数が、今回の実行で偽AIが実際に呼ばれた回数・
        失敗させた回数と合うことを確かめる。A3 の通知 (未取得・AI失敗の月数) の確認は、各テストが note に対して行う。"""
        done = split_done_status(status)
        if not has_cost_report():
            return done
        failed = [c for c in ai_calls if c in self.summarizer.fail_set]
        if ai_calls:
            self.assertEqual(done.calls, len(ai_calls), f"費用の文言の件数が、偽AIの呼ばれた回数と違う: {status}")
        else:
            self.assertEqual(done.cost, "（新しい分析は不要でした）", f"AIを呼んでいないのに費用の文言が違う: {status}")
        if failed:
            self.assertEqual(done.failed, len(failed), f"AI失敗の件数が、偽AIが失敗させた回数と違う: {status}")
        else:
            self.assertEqual((done.head, done.failed), (DONE_HEAD, None), f"AI失敗が無いのに先頭が成功の形でない: {status}")
        return done

    def assert_plain_status(self, status):
        """欠けが無いときの完了ステータス: 先頭は「✅ 振り返り生成完了」で、A3 の通知は付かない。
        _03 / _04 は「✅ 振り返り生成完了」だけ。_05 以降はその後ろに費用の文言だけが付く。"""
        done = split_done_status(status)
        self.assertEqual(done.head, DONE_HEAD, status)
        self.assertEqual(done.note, "", f"欠けが無いのに通知が付いた: {status}")
        if not has_cost_report():
            self.assertEqual(status, DONE_HEAD)

    def reformat_review(self, gui):
        """「🎨 フォーマットのみ再生成」を実行し、完了時のステータス文言を返す。"""
        return self._run(gui, "_reformat_review", "✅ フォーマット再生成完了")

    # ---- 結果の読み取り -------------------------------------------------------
    def last_result(self):
        return _loader.read_json(oto().REVIEW_LAST_RESULT_FILE)

    def report_html(self, person="Ochi"):
        paths = [p for p in self.opened if os.path.basename(p).startswith(f"Review_{person}_")]
        self.assertTrue(paths, f"{person} のレポートが開かれていない: {self.opened}")
        with open(paths[-1], "r", encoding="utf-8") as f:
            return f.read()

    def report_subtitle(self, person="Ochi"):
        m = re.search(r'<span class="subtitle">(.*?)</span>', self.report_html(person), flags=re.S)
        self.assertIsNotNone(m, "レポートに subtitle が無い")
        return m.group(1)

    def report_label(self, person="Ochi"):
        """その人のレポートの subtitle のうち、期間表示の部分 (「　｜　対象者: …」の前まで)。"""
        subtitle = self.report_subtitle(person)
        self.assertIn(f"　｜　対象者: {person}", subtitle)
        return subtitle.split(f"　｜　対象者: {person}")[0]

    def report_timeline(self, person="Ochi"):
        return [h for h, _c in timeline_headings(self.report_html(person))]

    def assert_label_everywhere(self, expected, person="Ochi"):
        """期間表示 (label) が、review_last_result.json の period_label と、レポートの subtitle の両方で expected。"""
        self.assertEqual(self.last_result()["period_label"], expected)
        self.assertIn(expected, self.report_subtitle(person))

    def seed(self, months, person="Ochi", error=()):
        for mm in months:
            put_cache(mm, person, error=(mm in error))


class TestRunReviewPassesTheWholeWindow(ReviewRunCase):
    """_run_review: 画面の12か月ぜんぶを generate_review_data の all_months に渡す (選択月だけではない)。
    レビュー指摘: 「all_months に選択月を渡す誤りが全73件をすり抜ける」。"""

    def run_default(self):
        gui = self.make_run_gui(NOW_1004)
        self.assertEqual(self.on_months(), {"202609"}, "前提: 既定は前月だけがON")
        self.run_review(gui)
        return gui

    def test_default_run_passes_all_12_months_to_generate_review_data(self):
        """既定 (前月のみ) で実行 → generate_review_data の all_months は画面の12か月 (2025-11〜2026-10)。選択月だけではない。"""
        self.run_default()
        self.assertEqual(len(self.gen_calls), 1)
        self.assertEqual(sorted(self.gen_calls[0]["all_months"]), ALL_1004)

    def test_saved_result_lists_the_12_months(self):
        """既定の実行で保存される review_last_result.json の months も12か月 (選択月だけではない)。"""
        self.run_default()
        self.assertEqual(self.last_result()["months"], ALL_1004)

    def test_only_the_selected_month_is_fetched(self):
        """メールを取得するのは選択月 (前月 2026-09) だけ。残りの11か月は Outlook に問い合わせない。"""
        self.run_default()
        self.assertEqual(self.outlook.fetched, [(2026, 9)])

    def test_threads_are_collected_only_for_the_selected_month(self):
        """generate_review_data に渡るスレッドの月別辞書は、選択月 (202609) だけ。"""
        self.run_default()
        self.assertEqual(self.gen_calls[0]["fetched_months"], ["202609"])

    def test_only_the_selected_month_is_analysed_by_the_ai(self):
        """AI を呼ぶのは選択月だけ。キャッシュの無い他の11か月も、AI は呼ばない (実績0件のまま)。"""
        self.run_default()
        self.assertEqual(self.summarizer.ai_calls, [("202609", "ochi")])

    def test_only_the_selected_month_gets_a_cache_file(self):
        """キャッシュのファイルが増えるのは選択月だけ (analysis_cache/review_monthly/202609.json のみ)。"""
        self.run_default()
        self.assertEqual(sorted(os.listdir(oto().REVIEW_CACHE_DIR)), ["202609.json"])

    def test_all_check_fetches_every_month_in_the_window_oldest_first(self):
        """「全て」をチェック → 12か月ぜんぶを古い順に取得する。"""
        gui = self.make_run_gui(NOW_1004)
        self.click(self.all_check())
        self.run_review(gui)
        self.assertEqual(self.outlook.fetched, [split_ym(mm) for mm in ALL_1004])

    def test_all_check_analyses_every_month_in_the_window(self):
        """「全て」をチェック → 12か月ぜんぶを AI で分析する (all_months も同じ12か月)。"""
        gui = self.make_run_gui(NOW_1004)
        self.click(self.all_check())
        self.run_review(gui)
        self.assertEqual(self.summarizer.ai_calls, [(mm, "ochi") for mm in ALL_1004])
        self.assertEqual(sorted(self.gen_calls[0]["all_months"]), ALL_1004)

    def test_cache_only_run_fetches_nothing_and_calls_no_ai(self):
        """月を1つもチェックしない (キャッシュのみ) 実行は、メール取得もAI呼び出しもしない。"""
        self.seed(ALL_1004)
        gui = self.make_run_gui(NOW_1004)
        self.set_all_months(False)
        self.run_review(gui)
        self.assertEqual(self.outlook.fetched, [])
        self.assertEqual(self.summarizer.ai_calls, [])

    def test_cache_only_run_still_passes_the_12_months(self):
        """キャッシュのみの実行でも、generate_review_data の all_months は画面の12か月。"""
        self.seed(ALL_1004)
        gui = self.make_run_gui(NOW_1004)
        self.set_all_months(False)
        self.run_review(gui)
        self.assertEqual(sorted(self.gen_calls[0]["all_months"]), ALL_1004)

    def test_cache_only_run_shows_all_12_cached_months(self):
        """キャッシュのみの実行でも、レポートの月別タイムラインには12か月ぶんの実績が並ぶ。"""
        self.seed(ALL_1004)
        gui = self.make_run_gui(NOW_1004)
        self.set_all_months(False)
        self.run_review(gui)
        self.assertEqual(len(self.report_timeline()), 12)


class TestRunReviewPeriodLabel(ReviewRunCase):
    """_run_review の期間表示 (review_last_result.json の period_label と、レポートの subtitle)。"""

    def test_default_run_label_says_which_month_was_updated_and_that_others_are_missing(self):
        """既定 (前月のみ) の実行 → 「2025年11月〜2026年10月（2026年9月を更新）／未取得: 10か月分」。
        キャッシュ無しの過去の10か月 (2025-11〜2026-08) が未取得に載り、今回更新した9月は載らない (キャッシュを書いた後で
        数えている)。進行中の当月 (2026-10) は数えない。"""
        gui = self.make_run_gui(NOW_1004)
        self.run_review(gui)
        self.assert_label_everywhere(BASE_1004 + f"{LPAR}2026年9月を更新{RPAR}／未取得: 10か月分")

    def test_label_is_not_built_from_the_selection_only(self):
        """期間の頭 (〜の前後) は選択月ではなく表示している12か月の最初と最後。選択が前月だけでも「2026年9月〜2026年9月」や
        「全月更新」にならない (選択月を all_months として扱う誤りの検出)。"""
        gui = self.make_run_gui(NOW_1004)
        self.run_review(gui)
        label_text = self.last_result()["period_label"]
        self.assertTrue(label_text.startswith(BASE_1004), label_text)
        self.assertNotIn(f"2026年9月{WAVE}2026年9月", label_text)
        self.assertNotIn("全月更新", label_text)

    def test_missing_months_are_listed_when_there_are_six_or_fewer(self):
        """未取得が6か月以下なら月名を列挙する。キャッシュのある月 (2025年11月〜2026年4月) は載らず、進行中の当月 (2026年10月) も
        載らない。"""
        self.seed(ALL_1004[:6])                                         # 202511 .. 202604
        gui = self.make_run_gui(NOW_1004)
        self.run_review(gui)
        self.assert_label_everywhere(BASE_1004 + f"{LPAR}2026年9月を更新{RPAR}／未取得: 2026年5月、2026年6月、2026年7月、2026年8月")

    def test_nothing_is_appended_when_every_other_month_has_its_cache(self):
        """他の11か月ぜんぶにキャッシュがあれば、「／未取得」も「／AI失敗」も付かない。"""
        self.seed([mm for mm in ALL_1004 if mm != "202609"])
        gui = self.make_run_gui(NOW_1004)
        self.run_review(gui)
        self.assert_label_everywhere(BASE_1004 + f"{LPAR}2026年9月を更新{RPAR}")

    def test_current_month_is_not_reported_as_missing_after_the_default_run(self):
        """既定 (前月のみ) の実行では当月 (2026-10) を取得しないが、「／未取得: 2026年10月」は出ない。過去の月 (2025-11〜2026-08)
        にキャッシュが揃っていれば、期間表示には何も付かない。"""
        self.seed(ALL_1004[:-2])                                        # 202511 .. 202608 (202609 は今回更新、202610 は当月)
        gui = self.make_run_gui(NOW_1004)
        self.run_review(gui)
        self.assert_label_everywhere(BASE_1004 + f"{LPAR}2026年9月を更新{RPAR}")

    def test_a_missing_past_month_is_still_reported_when_the_current_month_is_skipped(self):
        """当月は数えないが、過去の月 (2026年7月) が欠けていれば「／未取得: 2026年7月」は出る (当月は載らない)。"""
        self.seed([mm for mm in ALL_1004[:-2] if mm != "202607"])
        gui = self.make_run_gui(NOW_1004)
        self.run_review(gui)
        self.assert_label_everywhere(BASE_1004 + f"{LPAR}2026年9月を更新{RPAR}／未取得: 2026年7月")

    def test_ai_failure_of_the_current_month_is_reported(self):
        """当月のキャッシュが _error 真 (前回AIが失敗) なら、当月でも「／AI失敗: 2026年10月」は出る。"""
        self.seed(ALL_1004[:-2])
        put_cache("202610", error=True)
        gui = self.make_run_gui(NOW_1004)
        self.run_review(gui)
        self.assert_label_everywhere(BASE_1004 + f"{LPAR}2026年9月を更新{RPAR}／AI失敗: 2026年10月")

    def test_all_twelve_months_checked_is_all_months_updated(self):
        """全12か月をチェックして実行 → 「（全月更新）」。全部更新したので「／未取得」は付かない。"""
        gui = self.make_run_gui(NOW_1004)
        self.click(self.all_check())
        self.run_review(gui)
        self.assert_label_everywhere(BASE_1004 + f"{LPAR}全月更新{RPAR}")

    def test_checking_every_month_one_by_one_is_also_all_months_updated(self):
        """「全て」を使わず、月を1つずつ全部チェックしても「（全月更新）」(選択月の数が表示月の数と一致)。"""
        gui = self.make_run_gui(NOW_1004)
        for mm, chk in sorted(self.month_checks().items()):
            if mm not in self.on_months():
                self.click(chk)
        self.run_review(gui)
        self.assert_label_everywhere(BASE_1004 + f"{LPAR}全月更新{RPAR}")

    def test_several_months_checked_are_listed_in_oldest_first_order(self):
        """複数月をチェック → 「（2025年12月、2026年1月を更新）」のように古い順に列挙 (年またぎの表記)。
        チェックした順 (1月→12月) と関係なく古い順。"""
        self.seed([mm for mm in ALL_1004 if mm not in ("202512", "202601")])
        gui = self.make_run_gui(NOW_1004)
        self.set_all_months(False)
        self.click(self.month_checks()["202601"])
        self.click(self.month_checks()["202512"])
        self.run_review(gui)
        self.assert_label_everywhere(BASE_1004 + f"{LPAR}2025年12月{COMMA}2026年1月を更新{RPAR}")

    def test_several_months_checked_are_fetched_oldest_first(self):
        """複数月をチェック → 取得は古い順 (2025-12 → 2026-01)。チェックした順に依存しない。"""
        self.seed([mm for mm in ALL_1004 if mm not in ("202512", "202601")])
        gui = self.make_run_gui(NOW_1004)
        self.set_all_months(False)
        self.click(self.month_checks()["202601"])
        self.click(self.month_checks()["202512"])
        self.run_review(gui)
        self.assertEqual(self.outlook.fetched, [(2025, 12), (2026, 1)])

    def test_seven_or_more_updated_months_are_counted(self):
        """更新が7か月以上なら「（7か月を更新）」のように件数にする。"""
        self.seed(ALL_1004)
        gui = self.make_run_gui(NOW_1004)
        self.set_all_months(False)
        for mm in ALL_1004[:7]:
            self.click(self.month_checks()[mm])
        self.run_review(gui)
        self.assert_label_everywhere(BASE_1004 + f"{LPAR}7か月を更新{RPAR}")

    def test_cache_only_run_says_no_update(self):
        """月をチェックしない実行 → 「（キャッシュのみ、更新なし）」。"""
        self.seed(ALL_1004)
        gui = self.make_run_gui(NOW_1004)
        self.set_all_months(False)
        self.run_review(gui)
        self.assert_label_everywhere(BASE_1004 + f"{LPAR}キャッシュのみ{COMMA}更新なし{RPAR}")


class TestRunReviewAiFailureLabel(ReviewRunCase):
    """AI が失敗した月 (キャッシュに _error: true) は「／AI失敗: ...」に載る。"""

    def test_ai_failure_on_the_selected_month_shows_up(self):
        """前月のAIが失敗 (_error) → 「…（2026年9月を更新）／未取得: 10か月分／AI失敗: 2026年9月」。
        失敗した月はキャッシュのファイルがあるので「未取得」ではなく「AI失敗」に載る。"""
        gui = self.make_run_gui(NOW_1004, fail={("202609", "ochi")})
        self.run_review(gui)
        self.assertTrue(_loader.read_json(cache_file("202609"))["_error"], "前提: 失敗した月のキャッシュに _error が付く")
        self.assert_label_everywhere(BASE_1004 + f"{LPAR}2026年9月を更新{RPAR}／未取得: 10か月分／AI失敗: 2026年9月")

    def test_failed_month_has_no_achievements_in_the_report(self):
        """AIが失敗した月の実績は、レポートに出ない (実績0件)。"""
        gui = self.make_run_gui(NOW_1004, fail={("202609", "ochi")})
        self.run_review(gui)
        self.assertEqual(self.report_timeline(), [])

    def test_existing_error_cache_of_an_unselected_month_shows_up(self):
        """チェックしていない月のキャッシュに _error: true があるとき (前回AIが失敗した月)、「／AI失敗: 2026年8月」。"""
        self.seed(ALL_1004, error=("202608",))
        gui = self.make_run_gui(NOW_1004)
        self.run_review(gui)
        self.assert_label_everywhere(BASE_1004 + f"{LPAR}2026年9月を更新{RPAR}／AI失敗: 2026年8月")

    def test_existing_error_cache_of_an_unselected_month_is_not_retried(self):
        """チェックしていない月は、キャッシュが _error でもAIを呼び直さない (チェックした月だけ更新する)。"""
        self.seed(ALL_1004, error=("202608",))
        gui = self.make_run_gui(NOW_1004)
        self.run_review(gui)
        self.assertEqual(self.summarizer.ai_calls, [("202609", "ochi")])

    def test_cache_only_run_with_an_error_cache(self):
        """月をチェックしない (キャッシュのみ) 実行でも、_error のキャッシュは「／AI失敗」に載る。"""
        self.seed(ALL_1004, error=("202608",))
        gui = self.make_run_gui(NOW_1004)
        self.set_all_months(False)
        self.run_review(gui)
        self.assert_label_everywhere(BASE_1004 + f"{LPAR}キャッシュのみ{COMMA}更新なし{RPAR}／AI失敗: 2026年8月")

    def test_several_failed_months_are_listed(self):
        """AI失敗が複数 (6か月以下) なら月名を列挙する。"""
        self.seed(ALL_1004, error=("202601", "202603"))
        gui = self.make_run_gui(NOW_1004)
        self.run_review(gui)
        self.assert_label_everywhere(BASE_1004 + f"{LPAR}2026年9月を更新{RPAR}／AI失敗: 2026年1月、2026年3月")

    def test_seven_failed_months_are_counted(self):
        """AI失敗が7か月以上なら件数 (「／AI失敗: 7か月分」)。"""
        self.seed(ALL_1004, error=tuple(ALL_1004[:7]))
        gui = self.make_run_gui(NOW_1004)
        self.set_all_months(False)
        self.run_review(gui)
        self.assert_label_everywhere(BASE_1004 + f"{LPAR}キャッシュのみ{COMMA}更新なし{RPAR}／AI失敗: 7か月分")

    def run_saji_fails(self):
        gui = self.make_run_gui(NOW_1004, staffs={"Saji": {}}, fail={("202609", "saji")})
        self.gui.v_review_person_vars["Saji"].set(True)
        self.run_review(gui)
        self.assertTrue(_loader.read_json(cache_file("202609", "Saji"))["_error"], "前提: Saji の分だけが失敗")
        self.assertFalse(_loader.read_json(cache_file("202609", "Ochi"))["_error"], "前提: Ochi の分は成功")

    def test_a_staff_members_failure_is_in_the_saved_label(self):
        """対象者が複数のとき、2人目 (Saji) のAIだけが失敗した月も、保存する結果 (全員の合算) の期間表示に「AI失敗」で載る。"""
        self.run_saji_fails()
        self.assertEqual(self.last_result()["period_label"],
                         BASE_1004 + f"{LPAR}2026年9月を更新{RPAR}／未取得: 10か月分／AI失敗: 2026年9月")

    def test_a_staff_members_failure_is_in_that_persons_report(self):
        """Saji のAI失敗は、Saji のレポートの期間表示に出る (その人の未取得10か月と、AI失敗の2026年9月)。"""
        self.run_saji_fails()
        self.assertEqual(self.report_label("Saji"),
                         BASE_1004 + f"{LPAR}2026年9月を更新{RPAR}／未取得: 10か月分／AI失敗: 2026年9月")

    def test_a_staff_members_failure_is_not_in_the_other_persons_report(self):
        """Saji のAI失敗は、Ochi のレポートには出ない (他の人の欠けを、この人のレポートに出さない)。Ochi 自身の欠けだけ。"""
        self.run_saji_fails()
        self.assertEqual(self.report_label("Ochi"), BASE_1004 + f"{LPAR}2026年9月を更新{RPAR}／未取得: 10か月分")


class TestRunReviewCompletionStatus(ReviewRunCase):
    """完了ステータス: 欠け (未取得・AI失敗) があれば、末尾に「（⚠ 未取得Nか月・AI失敗Mか月あり。レポートの期間表示を確認してください）」が付く。
    欠けが無ければその通知は付かない (_03 / _04 は「✅ 振り返り生成完了」だけ。A7a の _05 以降は「✅ 振り返り生成完了」+ 費用の文言だけ)。
    ゼロ件の側を書くか省くかは仕様に明記が無いので、件数のある側だけを確かめる。
    ステータスの形 (先頭・費用の文言・通知) は split_done_status が厳密に分け、余計な文言が混じれば失敗にする。"""

    WARNING_HEAD = "（⚠ "                       # A3 の通知の書き出し (_03 では完了の文言の直後、_05 以降では費用の文言の直後)
    WARNING_TAIL = "レポートの期間表示を確認してください）"

    def test_status_warns_with_the_count_when_months_are_missing(self):
        """未取得が10か月 (過去の月。当月は数えない) あるとき、完了ステータスの末尾に警告が付く (「未取得10か月」を含む)。"""
        gui = self.make_run_gui(NOW_1004)
        status = self.run_review(gui)
        done = split_done_status(status)
        self.assertEqual(done.head, DONE_HEAD, status)
        self.assertTrue(done.note.startswith(self.WARNING_HEAD), status)
        self.assertIn("未取得10か月", done.note)

    def test_status_warns_with_the_count_when_ai_failed(self):
        """AI失敗が1か月のとき、完了ステータスの末尾に警告が付く (「AI失敗1か月」を含む)。
        (キャッシュに残っていた失敗。今回の実行のAIは成功しているので、先頭は成功の「✅ 振り返り生成完了」)"""
        self.seed([mm for mm in ALL_1004 if mm != "202609"], error=("202608",))
        gui = self.make_run_gui(NOW_1004)
        status = self.run_review(gui)
        done = split_done_status(status)
        self.assertEqual(done.head, DONE_HEAD, status)
        self.assertTrue(done.note.startswith(self.WARNING_HEAD), status)
        self.assertIn("AI失敗1か月", done.note)

    def test_status_shows_both_counts(self):
        """未取得2か月 (2025年11・12月。当月 2026年10月 は数えない)・AI失敗2か月のとき、両方の件数が出る。"""
        self.seed([mm for mm in ALL_1004 if mm not in ("202609", "202610", "202511", "202512")], error=("202601", "202602"))
        gui = self.make_run_gui(NOW_1004)
        done = split_done_status(self.run_review(gui))
        self.assertIn("未取得2か月", done.note)
        self.assertIn("AI失敗2か月", done.note)

    def test_warning_status_asks_to_check_the_period_label(self):
        """警告付きのステータスは「レポートの期間表示を確認してください）」で終わる (_05 以降も、費用の文言の後ろ = 末尾)。"""
        gui = self.make_run_gui(NOW_1004)
        status = self.run_review(gui)
        self.assertTrue(status.endswith(self.WARNING_TAIL), status)
        self.assertTrue(split_done_status(status).note.endswith(self.WARNING_TAIL), status)

    def test_the_warning_appears_once_at_the_very_end(self):
        """A3 の通知「（⚠ …あり。…）」は1つだけで、ステータスの最後にある (費用の文言などの後ろ)。"""
        gui = self.make_run_gui(NOW_1004)
        status = self.run_review(gui)
        self.assertEqual(status.count("（⚠ "), 1, status)
        self.assertEqual(status.count("未取得"), 1, status)
        self.assertTrue(status.endswith(split_done_status(status).note), status)
        self.assertTrue(status.rindex("（⚠ ") > status.index(DONE_HEAD), status)

    def test_status_keeps_the_warning_when_this_runs_ai_failed(self):
        """今回の実行で前月 (2026年9月) のAIが失敗したとき: 完了ステータスの末尾には、これまでどおり A3 の通知
        (「未取得10か月・AI失敗1か月」) が付く。_05 以降は先頭がAI失敗ありの完了 (件数1) に変わり、
        _03 / _04 は先頭が「✅ 振り返り生成完了」のまま。(A7a 追記2 で先頭は「⚠ 振り返り生成完了（AI失敗1件。その月を再実行で再試行）」)"""
        gui = self.make_run_gui(NOW_1004, fail={("202609", "ochi")})
        status = self.run_review(gui)
        done = split_done_status(status)
        if has_cost_report():
            self.assertEqual(done.failed, 1, status)
        else:
            self.assertEqual(done.head, DONE_HEAD, status)
        self.assertTrue(done.note.startswith(self.WARNING_HEAD), status)
        self.assertIn("未取得10か月", done.note)
        self.assertIn("AI失敗1か月", done.note)
        self.assertTrue(status.endswith(self.WARNING_TAIL), status)

    def test_status_is_the_plain_message_after_updating_every_month(self):
        """全月更新で何も欠けていなければ、通知の無い完了 (従来は「✅ 振り返り生成完了」だけ。_05 以降はそれに費用の文言)。"""
        gui = self.make_run_gui(NOW_1004)
        self.click(self.all_check())
        self.assert_plain_status(self.run_review(gui))

    def test_status_has_no_warning_when_only_the_current_month_has_no_cache(self):
        """過去の月が全部そろっていて、キャッシュが無いのが進行中の当月だけなら、警告は出ない (毎回「未取得: 当月」と出さない)。"""
        self.seed(ALL_1004[:-2])
        gui = self.make_run_gui(NOW_1004)
        self.assert_plain_status(self.run_review(gui))

    def test_status_is_the_plain_message_when_every_other_month_has_its_cache(self):
        """他の11か月ぜんぶにキャッシュがあれば (欠けなし)、更新が前月だけでも通知の無い完了 (「✅ 振り返り生成完了」+ 費用の文言だけ)。"""
        self.seed([mm for mm in ALL_1004 if mm != "202609"])
        gui = self.make_run_gui(NOW_1004)
        self.assert_plain_status(self.run_review(gui))

    def test_status_is_the_plain_message_for_a_cache_only_run_without_gaps(self):
        """キャッシュのみの実行で欠けが無ければ、通知の無い完了 (_05 以降は費用の文言が「新しい分析は不要でした」)。"""
        self.seed(ALL_1004)
        gui = self.make_run_gui(NOW_1004)
        self.set_all_months(False)
        status = self.run_review(gui)
        self.assert_plain_status(status)
        if has_cost_report():
            self.assertEqual(split_done_status(status).cost, "（新しい分析は不要でした）", status)


class TestRunReviewUsesReviewCacheGaps(ReviewRunCase):
    """_run_review / _reformat_review は review_cache_gaps(all_months, selected_persons) の結果で期間表示を作る。
    review_cache_gaps が例外を出しても握りつぶして ([], []) で続行する。"""

    def spy_gaps(self):
        p = mock.patch.object(oto(), "review_cache_gaps", wraps=oto().review_cache_gaps)
        spy = p.start()
        self.addCleanup(p.stop)
        return spy

    def raise_in_gaps(self):
        p = mock.patch.object(oto(), "review_cache_gaps", side_effect=RuntimeError("boom"))
        p.start()
        self.addCleanup(p.stop)

    @staticmethod
    def args_of(call):
        all_months = call.args[0] if call.args else call.kwargs.get("all_months")
        persons = call.args[1] if len(call.args) > 1 else call.kwargs.get("persons")
        return list(all_months), (list(persons) if persons is not None else None)

    def persons_of_calls(self, spy):
        return [self.args_of(c)[1] for c in spy.call_args_list]

    def test_run_passes_the_12_months_in_every_call(self):
        """run: review_cache_gaps に渡る月は、どの呼び出しでも表示している12か月 (選択月だけではない)。"""
        spy = self.spy_gaps()
        gui = self.make_run_gui(NOW_1004)
        self.run_review(gui)
        self.assertGreaterEqual(spy.call_count, 1)
        for call in spy.call_args_list:
            self.assertEqual(sorted(self.args_of(call)[0]), ALL_1004)

    def test_run_passes_the_selected_person_in_every_call(self):
        """run: 対象者が1人なら、review_cache_gaps に渡る対象者はどの呼び出しでもその人 (既定は Ochi)。"""
        spy = self.spy_gaps()
        gui = self.make_run_gui(NOW_1004)
        self.run_review(gui)
        self.assertEqual(set(map(tuple, self.persons_of_calls(spy))), {("Ochi",)})

    def two_person_gui(self):
        gui = self.make_run_gui(NOW_1004, staffs={"Saji": {}})
        self.gui.v_review_person_vars["Saji"].set(True)
        return gui

    def test_run_passes_all_selected_persons_together_for_the_saved_label(self):
        """run: 対象者が複数なら、保存する結果・完了ステータス用に、選んだ全員 (Ochi が先頭) をまとめて渡す呼び出しがある。"""
        spy = self.spy_gaps()
        self.run_review(self.two_person_gui())
        self.assertIn(["Ochi", "Saji"], self.persons_of_calls(spy))

    def test_run_passes_each_person_alone_for_that_persons_report(self):
        """run: 対象者が2人以上なら、各人のレポート用に、その人だけを渡す呼び出しがある (Ochi だけ・Saji だけ)。"""
        spy = self.spy_gaps()
        self.run_review(self.two_person_gui())
        self.assertIn(["Ochi"], self.persons_of_calls(spy))
        self.assertIn(["Saji"], self.persons_of_calls(spy))

    def test_reformat_passes_the_12_months_in_every_call(self):
        """reformat: review_cache_gaps に渡る月は、どの呼び出しでも表示している12か月。"""
        self.seed(ALL_1004)
        spy = self.spy_gaps()
        gui = self.make_run_gui(NOW_1004)
        self.reformat_review(gui)
        self.assertGreaterEqual(spy.call_count, 1)
        for call in spy.call_args_list:
            self.assertEqual(sorted(self.args_of(call)[0]), ALL_1004)

    def test_reformat_passes_the_selected_person_in_every_call(self):
        """reformat: 対象者が1人なら、review_cache_gaps に渡る対象者はどの呼び出しでもその人 (既定は Ochi)。"""
        self.seed(ALL_1004)
        spy = self.spy_gaps()
        gui = self.make_run_gui(NOW_1004)
        self.reformat_review(gui)
        self.assertEqual(set(map(tuple, self.persons_of_calls(spy))), {("Ochi",)})

    def test_reformat_passes_all_persons_together_and_each_person_alone(self):
        """reformat: 対象者が2人以上なら、全員まとめて (保存する結果用) と、各人だけ (その人のレポート用) の両方を渡す。"""
        self.seed(ALL_1004)
        spy = self.spy_gaps()
        self.reformat_review(self.two_person_gui())
        persons = self.persons_of_calls(spy)
        for expected in (["Ochi", "Saji"], ["Ochi"], ["Saji"]):
            self.assertIn(expected, persons)

    def test_run_continues_without_gap_notes_when_review_cache_gaps_raises(self):
        """review_cache_gaps が例外を出しても握りつぶす: 生成は最後まで進み (エラーダイアログなし)、期間表示は欠けの注記なし。"""
        self.raise_in_gaps()
        gui = self.make_run_gui(NOW_1004)
        self.run_review(gui)
        self.assert_label_everywhere(BASE_1004 + f"{LPAR}2026年9月を更新{RPAR}")

    def test_run_status_is_the_plain_message_when_review_cache_gaps_raises(self):
        """review_cache_gaps が例外のとき ([], [] 扱い)、完了ステータスは警告 (A3 の通知) なしの「✅ 振り返り生成完了」
        (_05 以降はその後ろに費用の文言だけ)。"""
        self.raise_in_gaps()
        gui = self.make_run_gui(NOW_1004)
        self.assert_plain_status(self.run_review(gui))

    def test_run_with_two_persons_continues_without_gap_notes_when_review_cache_gaps_raises(self):
        """対象者が2人でも、review_cache_gaps の例外は握りつぶす: 保存する結果も各人のレポートも、期間表示は欠けの注記なし。"""
        self.raise_in_gaps()
        gui = self.make_run_gui(NOW_1004, staffs={"Saji": {}})
        self.gui.v_review_person_vars["Saji"].set(True)
        self.run_review(gui)
        expected = BASE_1004 + f"{LPAR}2026年9月を更新{RPAR}"
        self.assertEqual(self.last_result()["period_label"], expected)
        self.assertEqual(self.report_label("Ochi"), expected)
        self.assertEqual(self.report_label("Saji"), expected)

    def test_reformat_with_two_persons_continues_without_gap_notes_when_review_cache_gaps_raises(self):
        """reformat でも、対象者が2人のとき例外は握りつぶし、保存する結果も各人のレポートも欠けの注記なし。"""
        self.seed(ALL_1004)
        self.raise_in_gaps()
        gui = self.make_run_gui(NOW_1004, staffs={"Saji": {}})
        self.gui.v_review_person_vars["Saji"].set(True)
        self.reformat_review(gui)
        expected = BASE_1004 + f"{LPAR}保存済みキャッシュから再構成{RPAR}"
        self.assertEqual(self.last_result()["period_label"], expected)
        self.assertEqual(self.report_label("Ochi"), expected)
        self.assertEqual(self.report_label("Saji"), expected)

    def test_reformat_continues_without_gap_notes_when_review_cache_gaps_raises(self):
        """reformat でも、review_cache_gaps の例外は握りつぶして続行し、期間表示は欠けの注記なし。"""
        self.seed(ALL_1004)
        self.raise_in_gaps()
        gui = self.make_run_gui(NOW_1004)
        self.reformat_review(gui)
        self.assert_label_everywhere(BASE_1004 + f"{LPAR}保存済みキャッシュから再構成{RPAR}")


class TestReformatReviewLabel(ReviewRunCase):
    """_reformat_review: 保存済みキャッシュだけから作り直す (取得もAIも無し)。期間は画面の12か月、末尾に「／未取得」「／AI失敗」。"""

    def run_then_reformat(self):
        gui = self.make_run_gui(NOW_1004)
        self.run_review(gui)
        self.before = (list(self.outlook.fetched), list(self.summarizer.ai_calls), len(self.gen_calls))
        self.reformat_review(gui)
        return gui

    def test_label_is_rebuilt_from_cache_with_the_gaps(self):
        """既定の実行のあとに「フォーマットのみ再生成」→ 「…（保存済みキャッシュから再構成）／未取得: 10か月分」
        (過去の10か月 2025-11〜2026-08 が未取得。202609 はキャッシュあり、当月 202610 は数えない)。"""
        self.run_then_reformat()
        self.assert_label_everywhere(BASE_1004 + f"{LPAR}保存済みキャッシュから再構成{RPAR}／未取得: 10か月分")

    def test_reformat_does_not_fetch_mail(self):
        """再構成ではメールを取得しない (保存済みキャッシュだけを使う)。"""
        self.run_then_reformat()
        self.assertEqual(self.outlook.fetched, self.before[0])

    def test_reformat_does_not_call_the_ai(self):
        """再構成では AI を呼ばない。"""
        self.run_then_reformat()
        self.assertEqual(self.summarizer.ai_calls, self.before[1])

    def test_reformat_does_not_call_generate_review_data(self):
        """再構成では generate_review_data (取得・分析の本体) を呼ばない。"""
        self.run_then_reformat()
        self.assertEqual(len(self.gen_calls), self.before[2])

    def test_reformat_label_without_gaps_has_no_update_wording(self):
        """欠けが無ければ、再構成の期間表示は「…（保存済みキャッシュから再構成）」だけ (「更新」「全月」は入らない)。"""
        self.seed(ALL_1004)
        gui = self.make_run_gui(NOW_1004)
        self.reformat_review(gui)
        self.assert_label_everywhere(BASE_1004 + f"{LPAR}保存済みキャッシュから再構成{RPAR}")

    def test_reformat_saves_the_12_months(self):
        """再構成で保存される review_last_result.json の months は12か月 (画面の一覧)。"""
        self.seed(ALL_1004)
        gui = self.make_run_gui(NOW_1004)
        self.reformat_review(gui)
        self.assertEqual(self.last_result()["months"], ALL_1004)

    def test_reformat_saves_the_selected_persons(self):
        """再構成で保存される persons は、選んでいる対象者。"""
        self.seed(ALL_1004)
        gui = self.make_run_gui(NOW_1004)
        self.reformat_review(gui)
        self.assertEqual(self.last_result()["persons"], ["Ochi"])

    def test_reformat_report_has_every_cached_month(self):
        """再構成したレポートの月別タイムラインには、キャッシュのある12か月が全部並ぶ。"""
        self.seed(ALL_1004)
        gui = self.make_run_gui(NOW_1004)
        self.reformat_review(gui)
        self.assertEqual(len(self.report_timeline()), 12)

    def test_reformat_shows_ai_failures_from_the_cache(self):
        """キャッシュに _error の月があれば「／AI失敗: ...」(複数は古い順に列挙)。"""
        self.seed(ALL_1004, error=("202608", "202609"))
        gui = self.make_run_gui(NOW_1004)
        self.reformat_review(gui)
        self.assert_label_everywhere(BASE_1004 + f"{LPAR}保存済みキャッシュから再構成{RPAR}／AI失敗: 2026年8月、2026年9月")

    def test_reformat_report_leaves_out_the_failed_months(self):
        """_error の月 (2か月) の実績は出ない: 12か月のうち10か月ぶんだけがタイムラインに並ぶ。"""
        self.seed(ALL_1004, error=("202608", "202609"))
        gui = self.make_run_gui(NOW_1004)
        self.reformat_review(gui)
        self.assertEqual(len(self.report_timeline()), 10)

    def test_reformat_with_both_gaps(self):
        """未取得とAI失敗が両方あれば「／未取得: ...／AI失敗: ...」の順。"""
        self.seed(ALL_1004[2:], error=("202609",))                    # 202511, 202512 が無い
        gui = self.make_run_gui(NOW_1004)
        self.reformat_review(gui)
        self.assert_label_everywhere(
            BASE_1004 + f"{LPAR}保存済みキャッシュから再構成{RPAR}／未取得: 2025年11月、2025年12月／AI失敗: 2026年9月")

    def reformat_with_saji_missing(self):
        """Ochi は12か月ぜんぶのキャッシュあり、Saji は1つも無い状態で、2人を選んで再構成する。"""
        self.seed(ALL_1004, "Ochi")
        gui = self.make_run_gui(NOW_1004, staffs={"Saji": {}})
        self.gui.v_review_person_vars["Saji"].set(True)
        self.reformat_review(gui)

    def test_saved_label_counts_the_gaps_of_every_selected_person(self):
        """対象者に Saji を足して再構成 → 保存する結果の期間表示は全員の合算: Saji のキャッシュの欠け (過去の11か月。当月は数えない)
        を数える。Ochi だけ見ると「欠けなし」になる。"""
        self.reformat_with_saji_missing()
        self.assertEqual(self.last_result()["period_label"],
                         BASE_1004 + f"{LPAR}保存済みキャッシュから再構成{RPAR}／未取得: 11か月分")

    def test_the_report_of_a_person_with_complete_caches_has_no_gap_note(self):
        """Ochi は全月そろっているので、Ochi のレポートの期間表示には「未取得」が出ない (Saji の欠けを出さない)。"""
        self.reformat_with_saji_missing()
        self.assertEqual(self.report_label("Ochi"), BASE_1004 + f"{LPAR}保存済みキャッシュから再構成{RPAR}")

    def test_the_report_of_a_person_with_gaps_shows_them(self):
        """Saji のレポートの期間表示には、Saji の欠け (「／未取得: 11か月分」) が出る。"""
        self.reformat_with_saji_missing()
        self.assertEqual(self.report_label("Saji"),
                         BASE_1004 + f"{LPAR}保存済みキャッシュから再構成{RPAR}／未取得: 11か月分")

    def test_the_other_persons_ai_failure_is_not_in_this_persons_report(self):
        """Saji のキャッシュだけが _error の月は、Saji のレポートと保存する結果には「AI失敗」で出るが、Ochi のレポートには出ない。"""
        self.seed(ALL_1004, "Ochi")
        self.seed(ALL_1004, "Saji", error=("202608",))
        gui = self.make_run_gui(NOW_1004, staffs={"Saji": {}})
        self.gui.v_review_person_vars["Saji"].set(True)
        self.reformat_review(gui)
        body = BASE_1004 + f"{LPAR}保存済みキャッシュから再構成{RPAR}"
        self.assertEqual(self.report_label("Ochi"), body)
        self.assertEqual(self.report_label("Saji"), body + "／AI失敗: 2026年8月")
        self.assertEqual(self.last_result()["period_label"], body + "／AI失敗: 2026年8月")


class TestRunReviewPerPersonGaps(ReviewRunCase):
    """対象者が2人 (Ochi・Saji) のとき: Ochi は全部の過去月にキャッシュあり・Saji は欠け。各人のレポートにはその人だけの欠け、
    保存する結果と完了ステータスは合算 (A3_SPEC_DELTA_fix2.md 2.)。"""

    def run_ochi_complete_saji_missing(self):
        self.seed(ALL_1004[:-2], "Ochi")                          # Ochi: 202511 .. 202608 (202609 は今回の実行で生成、202610 は当月)
        gui = self.make_run_gui(NOW_1004, staffs={"Saji": {}})
        self.gui.v_review_person_vars["Saji"].set(True)
        return self.run_review(gui)

    def test_the_report_of_the_complete_person_has_no_missing_note(self):
        """Ochi は過去月が全部そろっている (当月は数えない) ので、Ochi のレポートの期間表示に「未取得」は出ない。"""
        self.run_ochi_complete_saji_missing()
        self.assertEqual(self.report_label("Ochi"), BASE_1004 + f"{LPAR}2026年9月を更新{RPAR}")

    def test_the_report_of_the_person_with_gaps_shows_the_missing_months(self):
        """Saji は 202609 しかキャッシュが無いので、Saji のレポートには「／未取得: 10か月分」が出る。"""
        self.run_ochi_complete_saji_missing()
        self.assertEqual(self.report_label("Saji"), BASE_1004 + f"{LPAR}2026年9月を更新{RPAR}／未取得: 10か月分")

    def test_the_saved_label_is_the_combined_gaps_of_both_persons(self):
        """保存する結果 (review_last_result.json の period_label) は2人の合算: Saji の欠けが載る。"""
        self.run_ochi_complete_saji_missing()
        self.assertEqual(self.last_result()["period_label"],
                         BASE_1004 + f"{LPAR}2026年9月を更新{RPAR}／未取得: 10か月分")

    def test_the_completion_status_is_the_combined_warning(self):
        """完了ステータスの警告も合算 (Saji の欠け 10か月を数える)。Ochi だけなら警告は出ない。"""
        status = self.run_ochi_complete_saji_missing()
        done = split_done_status(status)
        self.assertEqual(done.head, DONE_HEAD, status)
        self.assertTrue(done.note.startswith("（⚠ "), status)
        self.assertIn("未取得10か月", done.note)

    def test_each_persons_own_gaps_are_not_mixed_when_the_months_differ(self):
        """Ochi は 2026年7月だけ欠け、Saji は 2026年3月だけ欠け (どちらも前月 9月は今回生成): 各レポートはその人の欠けだけ。
        保存する結果は両方 (古い順に 2026年3月、2026年7月)。"""
        self.seed([mm for mm in ALL_1004[:-2] if mm != "202607"], "Ochi")
        self.seed([mm for mm in ALL_1004[:-2] if mm != "202603"], "Saji")
        gui = self.make_run_gui(NOW_1004, staffs={"Saji": {}})
        self.gui.v_review_person_vars["Saji"].set(True)
        self.run_review(gui)
        body = BASE_1004 + f"{LPAR}2026年9月を更新{RPAR}"
        self.assertEqual(self.report_label("Ochi"), body + "／未取得: 2026年7月")
        self.assertEqual(self.report_label("Saji"), body + "／未取得: 2026年3月")
        self.assertEqual(self.last_result()["period_label"], body + "／未取得: 2026年3月、2026年7月")


class TestRunAcrossTheYearEnd(ReviewRunCase):
    """年またぎ (2026-01-15: 2025-02〜2026-01、前月は前年12月) でも、キャッシュが正しい場所に書かれ、タイムラインは新しい順。"""

    SEEDED = ("202502", "202509", "202510", "202511", "202601")

    def run_default(self):
        self.seed(self.SEEDED)
        gui = self.make_run_gui(NOW_0115)
        self.assertEqual(self.on_months(), {"202512"}, "前提: 1月の既定は前年12月")
        self.run_review(gui)
        return gui

    def test_previous_december_is_the_month_fetched(self):
        """既定 (前月のみ=前年12月) → 取得するのは 2025-12 だけ (2026-12 や 2024-12 ではない)。"""
        self.run_default()
        self.assertEqual(self.outlook.fetched, [(2025, 12)])

    def test_previous_december_is_the_month_analysed(self):
        """既定 (前年12月) → AI で分析するのは 202512 だけ。"""
        self.run_default()
        self.assertEqual(self.summarizer.ai_calls, [("202512", "ochi")])

    def test_cache_is_written_to_202512_json(self):
        """前年12月のキャッシュは analysis_cache/review_monthly/202512.json に書かれる (既存のキャッシュはそのまま、他は増えない)。"""
        self.run_default()
        self.assertEqual(sorted(os.listdir(oto().REVIEW_CACHE_DIR)), sorted(f"{mm}.json" for mm in self.SEEDED + ("202512",)))

    def test_cache_content_is_labelled_december_2025(self):
        """書かれた 202512.json の実績の年月ラベルは「2025年12月」で、AI失敗の印 (_error) は付かない。"""
        self.run_default()
        written = _loader.read_json(cache_file("202512"))
        self.assertEqual([a["year_month_label"] for a in written["achievements"]], ["2025年12月"])
        self.assertFalse(written["_error"])

    def test_all_months_passed_cross_the_year_end(self):
        """all_months は年またぎの12か月 (2025-02〜2026-01)。"""
        self.run_default()
        self.assertEqual(sorted(self.gen_calls[0]["all_months"]), ALL_0115)

    def test_label_crosses_the_year_end_and_lists_the_missing_months(self):
        """期間表示は「2025年2月〜2026年1月（2025年12月を更新）／未取得: 2025年3月〜8月の6か月を列挙」。"""
        self.run_default()
        missing = [mm for mm in ALL_0115 if mm not in self.SEEDED + ("202512",)]
        self.assertEqual(missing, [f"2025{m:02d}" for m in range(3, 9)])
        self.assert_label_everywhere(f"2025年2月{WAVE}2026年1月{LPAR}2025年12月を更新{RPAR}" + gap_suffix(missing))

    def test_timeline_is_newest_first_across_the_year_end(self):
        """月別タイムラインは新しい月が先頭 (2026年1月 → 2025年12月 → … → 2025年9月 → 2025年2月)。
        文字列順だと 2025年9月 が 2025年12月 より上に来る (以前の不具合) が、そうならない。"""
        self.run_default()
        expected = ["2026年1月", "2025年12月", "2025年11月", "2025年10月", "2025年9月", "2025年2月"]
        self.assertNotEqual(sorted(expected, reverse=True), expected, "前提: このデータは文字列順だと並びが変わる")
        self.assertEqual(self.report_timeline(), expected)

    def test_timeline_of_a_full_12_month_run_is_newest_first(self):
        """全12か月を更新したレポートのタイムラインは、12か月ぶんが新しい順 (年またぎ)。"""
        gui = self.make_run_gui(NOW_0115)
        self.click(self.all_check())
        self.run_review(gui)
        window = [f"{y}年{m}月" for y, m in ref_range(NOW_0115)]
        self.assertEqual(self.report_timeline(), list(reversed(window)))

    def test_label_of_a_full_12_month_run_across_the_year_end(self):
        """全12か月を更新 → 「2025年2月〜2026年1月（全月更新）」。"""
        gui = self.make_run_gui(NOW_0115)
        self.click(self.all_check())
        self.run_review(gui)
        self.assert_label_everywhere(f"2025年2月{WAVE}2026年1月{LPAR}全月更新{RPAR}")


class TestReformatAcrossTheYearEnd(ReviewRunCase):
    """年またぎの再構成 (2026-01-15)。"""

    def test_reformat_label_crosses_the_year_end(self):
        """期間は 2025年2月〜2026年1月。"""
        self.seed(ALL_0115)
        gui = self.make_run_gui(NOW_0115)
        self.reformat_review(gui)
        self.assert_label_everywhere(f"2025年2月{WAVE}2026年1月{LPAR}保存済みキャッシュから再構成{RPAR}")

    def test_reformat_timeline_is_newest_first(self):
        """タイムラインは新しい順 (2026年1月 → 2025年12月 → … → 2025年2月)。"""
        self.seed(ALL_0115)
        gui = self.make_run_gui(NOW_0115)
        self.reformat_review(gui)
        self.assertEqual(self.report_timeline(), [f"{y}年{m}月" for y, m in reversed(ref_range(NOW_0115))])


class TestRunAcrossAMonthEnd(ReviewRunCase):
    """月またぎ: 2026-10-31 に作った画面を 2026-11-01 に操作しても、選べる月・取得する月・表示する月が画面の一覧 (2025-11〜2026-10) のまま。"""

    def run_after_midnight(self, press_prev=True, press_all=False):
        gui = self.make_run_gui(NOW_1031)
        self.freeze_today(NOW_1101)
        if press_prev:
            self.click(self.button("前月のみ"))
        if press_all:
            self.click(self.all_check())
        self.run_review(gui)
        return gui

    def test_prev_month_button_then_run_fetches_october(self):
        """11/1 に「前月のみ」→ 生成: 取得するのは10月 (画面を作った 10/31 の前月 9月でも、11月でもない)。"""
        self.run_after_midnight()
        self.assertEqual(self.outlook.fetched, [(2026, 10)])

    def test_prev_month_button_then_run_analyses_october(self):
        """11/1 に「前月のみ」→ 生成: AIで分析するのも10月だけ。"""
        self.run_after_midnight()
        self.assertEqual(self.summarizer.ai_calls, [("202610", "ochi")])

    def test_all_months_stay_the_screen_window_after_midnight(self):
        """11/1 に生成しても、all_months は 2025-11〜2026-10 のまま (202611 を含まない・2025年11月を落とさない)。"""
        self.run_after_midnight()
        self.assertEqual(sorted(self.gen_calls[0]["all_months"]), ALL_1004)

    def test_cache_is_written_for_october_only(self):
        """キャッシュが書かれるのは 202610.json だけ (202611.json は作られない)。"""
        self.run_after_midnight()
        self.assertEqual(sorted(os.listdir(oto().REVIEW_CACHE_DIR)), ["202610.json"])

    def test_label_after_midnight(self):
        """期間表示は「2025年11月〜2026年10月（2026年10月を更新）／未取得: 11か月分」。"""
        self.run_after_midnight()
        self.assert_label_everywhere(BASE_1004 + f"{LPAR}2026年10月を更新{RPAR}／未取得: 11か月分")

    def test_default_selection_made_before_midnight_is_still_fetched_after_it(self):
        """ボタンを押さず、10/31 に作った既定 (9月) のまま 11/1 に生成 → 取得するのは9月。"""
        self.run_after_midnight(press_prev=False)
        self.assertEqual(self.outlook.fetched, [(2026, 9)])

    def test_default_selection_made_before_midnight_keeps_the_window_in_the_label(self):
        """ボタンを押さずに 11/1 に生成しても、表示は 2025-11〜2026-10 のまま (ずれない)。"""
        self.run_after_midnight(press_prev=False)
        self.assert_label_everywhere(BASE_1004 + f"{LPAR}2026年9月を更新{RPAR}／未取得: 11か月分")

    def test_all_check_after_midnight_fetches_the_screen_window(self):
        """11/1 に「全て」→ 生成: 取得するのは画面の12か月 (2025-11〜2026-10)。一覧に無い11月は取得しない。"""
        self.run_after_midnight(press_prev=False, press_all=True)
        self.assertEqual(self.outlook.fetched, [split_ym(mm) for mm in ALL_1004])

    def test_all_check_after_midnight_is_all_months_updated(self):
        """11/1 に「全て」→ 生成: 期間表示は「（全月更新）」。"""
        self.run_after_midnight(press_prev=False, press_all=True)
        self.assert_label_everywhere(BASE_1004 + f"{LPAR}全月更新{RPAR}")

    def test_reformat_after_midnight_keeps_the_screen_window_in_the_label(self):
        """11/1 の再構成: 期間は 2025年11月〜2026年10月 (日付から計算した 2025-12〜2026-11 にならない)。"""
        self.seed(ALL_1004)
        gui = self.make_run_gui(NOW_1031)
        self.freeze_today(NOW_1101)
        self.reformat_review(gui)
        self.assert_label_everywhere(BASE_1004 + f"{LPAR}保存済みキャッシュから再構成{RPAR}")

    def test_reformat_after_midnight_saves_the_screen_window(self):
        """11/1 の再構成で保存される months も、画面の12か月 (2025-11〜2026-10)。"""
        self.seed(ALL_1004)
        gui = self.make_run_gui(NOW_1031)
        self.freeze_today(NOW_1101)
        self.reformat_review(gui)
        self.assertEqual(self.last_result()["months"], ALL_1004)


class TestRunReviewMultiplePersons(ReviewRunCase):
    """対象者が複数のとき、人ごとに別々のキャッシュとレポート。期間表示は全員で同じ。"""

    def run_two_persons(self):
        gui = self.make_run_gui(NOW_1004, staffs={"Saji": {}})
        self.gui.v_review_person_vars["Saji"].set(True)
        return gui, self.run_review(gui)

    def test_each_person_gets_a_cache_file(self):
        """Ochi と Saji を選んで既定 (前月のみ) → キャッシュは 202609.json (Ochi) と 202609__Saji.json (Saji)。"""
        self.run_two_persons()
        self.assertEqual(sorted(os.listdir(oto().REVIEW_CACHE_DIR)), ["202609.json", "202609__Saji.json"])

    def test_each_person_gets_a_separate_report(self):
        """レポートは人ごとに別ファイルで2つ (Ochi 用と Saji 用)。"""
        self.run_two_persons()
        self.assertEqual(sorted(os.path.basename(p).split("_")[1] for p in self.opened), ["Ochi", "Saji"])

    def test_both_reports_show_the_gaps_when_both_persons_lack_the_same_months(self):
        """どちらも前月 (202609) だけがキャッシュ済みなら、両方のレポートに「／未取得: 10か月分」(過去の月。当月は数えない)。
        保存する結果 (合算) も同じ。"""
        self.run_two_persons()
        expected = BASE_1004 + f"{LPAR}2026年9月を更新{RPAR}／未取得: 10か月分"
        self.assertEqual(self.report_label("Ochi"), expected)
        self.assertEqual(self.report_label("Saji"), expected)
        self.assertEqual(self.last_result()["period_label"], expected)

    def test_the_selected_persons_are_passed_to_generate_review_data(self):
        """generate_review_data に渡る対象者は、選んだ2人 (Ochi が先頭)。"""
        self.run_two_persons()
        self.assertEqual(self.gen_calls[0]["persons"], ["Ochi", "Saji"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
