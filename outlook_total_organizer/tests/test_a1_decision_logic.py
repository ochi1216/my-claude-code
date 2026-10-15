# -*- coding: utf-8 -*-
"""A1「判断待ち」純関数テスト (仕様 1〜7, 10, 11) と「既存コード不変」ガード。

仕様書 (A1_SPEC.md) だけを根拠に、実装を見ずに書いている。
  - 仕様に明記された挙動          -> 通常の TestCase
  - 仕様が曖昧/未記載で「最も自然な解釈」で書いたもの
                                  -> クラス名に SpecGap を含む (コメントに解釈を明記)
    SpecGap の失敗は「バグ」ではなく「仕様の確認が必要」の合図として扱ってください。
"""
import ast
import copy
import os
import random
import time
import unittest
from datetime import datetime, timedelta

import _loader
from _loader import (
    CACHE_PATH, HOUR, NOW, ROW_KEYS, STATUS_PATH, iso_epoch, make_action, make_cache, make_last_run,
    make_status, make_thread, read_json, tempdir_cwd, ts_ago, write_bytes, write_json, write_text,
)


def oto():
    return _loader.load()


def const(name):
    """モジュール定数、無ければ MailManagerGUI のクラス定数 (仕様は置き場所を明記していない)。"""
    mod = oto()
    if hasattr(mod, name):
        return getattr(mod, name)
    return getattr(mod.MailManagerGUI, name)


BASE = "📋 アクション"


# ============================================================
# 定数
# ============================================================
class TestConstants(unittest.TestCase):
    def test_file_paths(self):
        self.assertEqual(oto().ACTION_DASHBOARD_CACHE_FILE, "analysis_cache/action_dashboard.json")
        self.assertEqual(oto().ACTION_LAST_RUN_FILE, "json/action_last_run.json")

    def test_existing_status_file_path_unchanged(self):
        self.assertEqual(oto().ACTION_STATUS_FILE, "json/action_status.json")

    def test_decision_types_and_keywords(self):
        self.assertEqual(tuple(oto().ACTION_DECISION_TYPES), ("承認・決裁", "相談・質問"))
        self.assertEqual(tuple(oto().ACTION_DECISION_KEYWORDS), ("承認", "決裁", "判断"))

    def test_thresholds(self):
        self.assertEqual(oto().ACTION_DECISION_STALE_HOURS, 24)
        self.assertEqual(oto().ACTION_DECISION_DEFAULT_HORIZON_DAYS, 7)

    def test_self_aliases(self):
        self.assertEqual(
            tuple(oto().ACTION_SELF_TARGET_ALIASES),
            ("あなた", "あなた自身", "あなたご自身", "自分", "本人", "you", "me", "ochi", "越智"))

    def test_progress_values(self):
        self.assertEqual(tuple(oto().ACTION_PROGRESS_VALUES),
                         ("not_started", "in_progress", "done", "ignored"))

    def test_clock_skew_and_tab_padding_constants(self):
        # 仕様変更(第2回): 定数 ACTION_DECISION_CLOCK_SKEW_SECONDS = 300 / ACTION_TAB_PADDING_PX = 28
        self.assertEqual(const("ACTION_DECISION_CLOCK_SKEW_SECONDS"), 300)
        self.assertEqual(const("ACTION_TAB_PADDING_PX"), 28)


# ============================================================
# 1. normalize_action_target_token
# ============================================================
class TestNormalizeToken(unittest.TestCase):
    def n(self, s):
        return oto().normalize_action_target_token(s)

    def test_spec_examples(self):
        for src, want in (("Ochi-san", "ochi"), ("越智さん", "越智"), ("ＯＣＨＩ", "ochi"),
                          ("あなた", "あなた"), ("さん", "さん")):
            with self.subTest(src=src):
                self.assertEqual(self.n(src), want)

    def test_each_honorific_is_removed(self):
        for suffix in ("さん", "様", "氏", "殿", "君", "くん"):
            with self.subTest(suffix=suffix):
                self.assertEqual(self.n("越智" + suffix), "越智")
        for src in ("ochi-san", "Ochi-San", "OCHI-SAN", "ochisan", "Ochisan"):
            with self.subTest(src=src):
                self.assertEqual(self.n(src), "ochi")

    def test_honorific_alone_is_kept_because_result_would_be_empty(self):
        for tok in ("さん", "様", "氏", "殿", "君", "くん", "san"):
            with self.subTest(tok=tok):
                self.assertEqual(self.n(tok), tok)

    def test_up_to_two_suffixes_are_removed_and_no_more(self):
        # 仕様変更(第3回): 敬称/宛名の言い回し/役職を「最大2回」まで除去する (旧: 1回だけ)
        self.assertEqual(self.n("越智さんさん"), "越智")
        self.assertEqual(self.n("越智様さん"), "越智")
        self.assertEqual(self.n("ochi-san-san"), "ochi")          # "-san" が "san" より優先されること
        # 3つ目は外さない (最大2回)
        self.assertEqual(self.n("越智さんさんさん"), "越智さん")
        self.assertEqual(self.n("ochi-san-san-san"), "ochi-san")

    def test_only_trailing_honorific_is_removed(self):
        self.assertEqual(self.n("さんま"), "さんま")
        self.assertEqual(self.n("様子"), "様子")
        self.assertEqual(self.n("君島"), "君島")
        self.assertEqual(self.n("san-ochi"), "san-ochi")

    def test_nfkc_lower_strip(self):
        for src, want in (("OCHI", "ochi"), ("  Ochi  ", "ochi"), ("　越智さん　", "越智"),
                          ("ＹＯＵ", "you"), ("Ｏｃｈｉ－ｓａｎ", "ochi"), ("Ochi ", "ochi"),
                          ("ｙｏｕ", "you"), ("", ""), ("   ", ""), ("　", "")):
            with self.subTest(src=src):
                self.assertEqual(self.n(src), want)

    def test_returns_str(self):
        for src in ("", "x", "越智さん", "  "):
            self.assertIsInstance(self.n(src), str)

    # ---- 仕様変更(第2回): 除去対象に さん宛て 様宛て さんへ 様へ さん宛 様宛 宛て 宛 マネージャー 部長 所長 課長 を追加 ----
    def test_new_suffixes_are_removed(self):
        for suffix in ("さん宛て", "様宛て", "さんへ", "様へ", "さん宛", "様宛", "宛て", "宛",
                       "マネージャー", "部長", "所長", "課長"):
            with self.subTest(suffix=suffix):
                self.assertEqual(self.n("越智" + suffix), "越智")

    def test_new_suffixes_on_you(self):
        for src, want in (("あなた宛て", "あなた"), ("あなた様宛て", "あなた"), ("あなたさん宛て", "あなた"),
                          ("Ochiさん宛て", "ochi"), ("OCHI様へ", "ochi"), ("ochi課長", "ochi")):
            with self.subTest(src=src):
                self.assertEqual(self.n(src), want)

    def test_longest_suffix_goes_first(self):
        # 長いものから除去: "越智さんさん宛て" は「さん宛て」→「さん」の2回で "越智"
        # (短い「宛て」から外すと「宛て」→「さん」で "越智さん" が残ってしまう。仕様変更(第3回)の例)
        self.assertEqual(self.n("越智さんさん宛て"), "越智")
        self.assertEqual(self.n("越智さん宛て"), "越智")
        self.assertEqual(self.n("越智様へ"), "越智")
        self.assertEqual(self.n("越智様宛て"), "越智")

    def test_title_plus_honorific_takes_two_removals(self):
        # 仕様変更(第3回): 「越智部長様」→「越智」 (肩書 + 敬称)
        for src in ("越智部長様", "越智課長様", "越智所長様", "越智部長さん", "越智マネージャー様",
                    "越智部長様宛て", "越智部長さん宛て", "越智部長宛て", "越智課長殿", "越智部長氏",
                    # 「さんへ」「様へ」「さん宛」「様宛」は1回で外せる (長い付属語を優先)。「へ」「宛」→「さん」の2回では
                    # 上限の2回を使い切って役職が残ってしまう
                    "越智部長さんへ", "越智部長様へ", "越智課長様へ", "越智部長さん宛", "越智部長様宛"):
            with self.subTest(src=src):
                self.assertEqual(self.n(src), "越智")

    def test_third_removal_is_not_done(self):
        # 3回分の付属語は「最大2回」の上限で外しきれない
        self.assertEqual(self.n("越智課長部長様"), "越智課長")

    def test_bare_he_particle_is_removed(self):
        # 仕様変更(第3回): 除去対象に素の「へ」を追加 (「あなたへ」→「あなた」)
        for src, want in (("あなたへ", "あなた"), ("越智へ", "越智"), ("ochiへ", "ochi"), ("Ochi-sanへ", "ochi")):
            with self.subTest(src=src):
                self.assertEqual(self.n(src), want)
        self.assertEqual(self.n("へ"), "へ")                       # 単独は除去すると空になるので残す

    def test_new_suffix_alone_is_kept_because_result_would_be_empty(self):
        for tok in ("宛て", "宛", "部長", "所長", "課長", "マネージャー", "へ"):
            with self.subTest(tok=tok):
                self.assertEqual(self.n(tok), tok)

    def test_san_he_and_sama_he_alone_become_the_bare_honorific(self):
        # 「さんへ」「様へ」単独: 長い方を外すと空になるので、短い「へ」だけ外して「さん」「様」になる (仕様変更(第3回))
        self.assertEqual(self.n("さんへ"), "さん")
        self.assertEqual(self.n("様へ"), "様")

    def test_new_suffix_only_when_trailing(self):
        for src in ("部長会議", "宛先", "課長代理", "マネージャー会", "所長室"):
            with self.subTest(src=src):
                self.assertEqual(self.n(src), src)


class TestSpecGapNormalize(unittest.TestCase):
    """仕様が曖昧: 敬称除去『後』に再度 strip するか / None の扱い / 長い付属語が空になるときの扱い。"""

    def test_long_suffix_that_would_empty_the_token_falls_back_to_the_shorter_one(self):
        # 「さんへ」→「さん」の仕様 (第3回) から素直に導かれる: 他の「長い付属語が全体になる」場合も同様
        n = oto().normalize_action_target_token
        for src, want in (("さん宛て", "さん"), ("様宛て", "様"), ("さん宛", "さん"), ("様宛", "様")):
            with self.subTest(src=src):
                self.assertEqual(n(src), want)

    def test_whitespace_between_title_and_honorific_is_ignored(self):
        n = oto().normalize_action_target_token
        for src in ("越智 部長", "越智　部長様", "越智部長 様", "越智 部長 様"):
            with self.subTest(src=src):
                self.assertEqual(n(src), "越智")

    def test_whitespace_before_honorific_leaves_no_trailing_space(self):
        # 仕様の順序は「NFKC→lower→strip→敬称除去」。除去後の再stripは明記なし。
        # 自然な解釈: 比較に使う正規化トークンに空白が残らない ("越智 さん" -> "越智")。
        n = oto().normalize_action_target_token
        self.assertEqual(n("越智 さん"), "越智")
        self.assertEqual(n("Ochi san"), "ochi")

    def test_none_is_treated_as_empty(self):
        # 仕様はstr前提。None は例外にせず空文字にするのが自然。
        self.assertEqual(oto().normalize_action_target_token(None), "")


# ============================================================
# 2. is_target_self
# ============================================================
class TestIsTargetSelf(unittest.TestCase):
    def f(self, *a, **k):
        return oto().is_target_self(*a, **k)

    def test_empty_target_is_self(self):
        for t in (None, "", " ", "   ", "　", "\t", " \n ", "　 　", " "):
            with self.subTest(target=t):
                self.assertTrue(self.f(t))

    def test_builtin_aliases(self):
        for a in ("あなた", "あなた自身", "あなたご自身", "自分", "本人", "you", "me", "ochi", "越智"):
            with self.subTest(alias=a):
                self.assertTrue(self.f(a))

    def test_case_width_honorific_variants(self):
        for t in ("You", "YOU", "ＹＯＵ", "Me", "Ochi", "OCHI", "ＯＣＨＩ", "越智さん", "越智様", "越智氏",
                  "越智殿", "越智君", "越智くん", "Ochi-san", "Ochi san", "ochisan", "Ochi様",
                  "あなた様", "本人様", " あなた ", "　あなた　", "「越智さん」", "(Ochi-san)"):
            with self.subTest(target=t):
                self.assertTrue(self.f(t))

    def test_others_are_not_self(self):
        for t in ("Nakai", "Nakai-san", "中井さん", "各位", "全員", "チーム", "Team", "All",
                  "関係者各位", "Tanaka、Suzuki", "N/A", "不明", "-"):
            with self.subTest(target=t):
                self.assertFalse(self.f(t))

    def test_no_partial_match(self):
        # 仕様: 部分一致はしない。"Ochi" が含まれるだけでは True にならない
        for t in ("ochiai", "Ochiai", "Ochiai-san", "Kochi", "Tochigi", "Mochizuki", "Mochizuki-san",
                  "越智田", "小越智", "あなたの上司", "自分たち", "本人確認", "youtube", "yours",
                  "meeting", "memo", "Mei"):
            with self.subTest(target=t):
                self.assertFalse(self.f(t))

    def test_multiple_recipients_with_each_separator(self):
        seps = ["、", ",", "，", "/", "／", "・", "&", "＆", "+", "＋", ";", "；", "　", " "]
        for sep in seps:
            with self.subTest(sep=repr(sep)):
                self.assertTrue(self.f(f"Nakai{sep}Ochi"))
                self.assertTrue(self.f(f"Ochi{sep}Nakai"))
                self.assertTrue(self.f(f"Nakai{sep}あなた{sep}Tanaka"))
                self.assertFalse(self.f(f"Nakai{sep}Tanaka"))
                self.assertFalse(self.f(f"Nakai{sep}Ochiai"))

    def test_brackets_split_tokens(self):
        for o, c in (("(", ")"), ("（", "）"), ("[", "]"), ("「", "」")):
            with self.subTest(open=o):
                self.assertTrue(self.f(f"{o}Ochi{c}"))
                self.assertTrue(self.f(f"Nakai{o}Ochi{c}"))
                self.assertTrue(self.f(f"{o}越智{c}Nakai"))
                self.assertFalse(self.f(f"Nakai{o}Tanaka{c}"))
                self.assertFalse(self.f(f"{o}Ochiai{c}"))

    def test_consecutive_and_dangling_separators(self):
        for t in ("Nakai、、あなた", "、あなた、", "あなた、", ",,Ochi,,", "Ochi, Yuichi"):
            with self.subTest(target=t):
                self.assertTrue(self.f(t))

    def test_honorific_in_each_token(self):
        self.assertTrue(self.f("Nakai-san、Ochi-san"))
        self.assertTrue(self.f("中井さん／越智さん"))
        self.assertFalse(self.f("Nakai-san、Tanaka-san"))

    # ---- 仕様変更(第2回) ---------------------------------------------------
    def test_new_phrasings_are_self(self):
        for t in ("あなた宛て", "あなた宛", "あなた様宛て", "越智さんへ", "越智様へ", "越智さん宛て", "越智様宛て",
                  "越智宛て", "越智部長", "越智課長", "越智所長", "越智マネージャー", "『あなた』", "Ochi。",
                  "Mr. Ochi", "Ochi.", "Ochi-san。", "「あなた」宛て", "あなたへ"):
            with self.subTest(target=t):
                self.assertTrue(self.f(t))

    def test_title_plus_honorific_is_self(self):
        # 仕様変更(第3回): 「越智部長様」→「越智」 (最大2回の除去)。日本語の宛名で多い言い回し
        for t in ("越智部長様", "越智課長様", "越智所長様", "越智部長さん", "越智マネージャー様", "越智部長様宛て",
                  "越智部長さん宛て", "あなたへ", "越智様へ", "「越智部長様」", "Nakai、越智部長様"):
            with self.subTest(target=t):
                self.assertTrue(self.f(t))

    def test_title_plus_honorific_of_someone_else_is_not_self(self):
        for t in ("中井部長様", "中井課長さん", "越智田部長様", "越智部長様の件", "Nakai部長様"):
            with self.subTest(target=t):
                self.assertFalse(self.f(t))

    def test_target_written_as_own_email_address_is_self(self):
        # 仕様変更(第3回): build_self_aliases が SMTP アドレス全体も別名に含める
        al = oto().build_self_aliases("Ochi, Yuichi", "yuichi.ochi@example.com")
        self.assertTrue(self.f("yuichi.ochi@example.com", al))
        self.assertTrue(self.f("Yuichi.Ochi@Example.com", al))
        self.assertTrue(self.f("Yuichi Ochi <yuichi.ochi@example.com>", al))
        self.assertFalse(self.f("nakai@example.com", al))
        self.assertFalse(self.f("yuichi.ochi@other.example.org", al))

    def test_you_and_someone_else_is_not_self(self):
        # 「と」では分割しない → 「あなたと中井さん」は1つのトークン扱いで False のまま
        for t in ("あなたと中井さん", "あなたとNakai", "あなたの上司", "越智部長の件", "Dr. Ochiai", "Mr. Nakai"):
            with self.subTest(target=t):
                self.assertFalse(self.f(t))

    def test_new_separators_split_tokens(self):
        # 追加された区切り: 。 . ． 『 』 " ' “ ” ‘ ’
        seps = ["。", ".", "．", '"', "'", "“", "”", "‘", "’"]
        for sep in seps:
            with self.subTest(sep=repr(sep)):
                self.assertTrue(self.f(f"Nakai{sep}Ochi"))
                self.assertTrue(self.f(f"Ochi{sep}Nakai"))
                self.assertFalse(self.f(f"Nakai{sep}Tanaka"))
                self.assertFalse(self.f(f"Nakai{sep}Ochiai"))

    def test_new_bracket_like_pairs(self):
        for o, c in (("『", "』"), ('"', '"'), ("'", "'"), ("“", "”"), ("‘", "’")):
            with self.subTest(open=o):
                self.assertTrue(self.f(f"{o}Ochi{c}"))
                self.assertTrue(self.f(f"{o}あなた{c}"))
                self.assertTrue(self.f(f"Nakai{o}越智{c}"))
                self.assertFalse(self.f(f"Nakai{o}Tanaka{c}"))
                self.assertFalse(self.f(f"{o}Ochiai{c}"))

    # ---- extra_aliases -------------------------------------------------
    def test_extra_alias_single_token(self):
        self.assertFalse(self.f("Yamada"))
        self.assertTrue(self.f("Yamada", extra_aliases=("yamada",)))
        self.assertTrue(self.f("Yamada-san", extra_aliases=["yamada"]))
        self.assertTrue(self.f("山田さん", extra_aliases=("山田",)))
        self.assertTrue(self.f("Nakai、Yamada", extra_aliases=("yamada",)))
        self.assertFalse(self.f("Yamadaa", extra_aliases=("yamada",)))
        self.assertFalse(self.f("Yama", extra_aliases=("yamada",)))

    def test_extra_alias_is_normalized_too(self):
        self.assertTrue(self.f("yamada", extra_aliases=("Yamada-San",)))
        self.assertTrue(self.f("ＹＡＭＡＤＡ", extra_aliases=("yamada",)))
        self.assertTrue(self.f("yamada", extra_aliases=("ＹＡＭＡＤＡ",)))

    def test_extra_alias_multiword_full_match(self):
        al = ("taro yamada",)
        for t in ("Taro Yamada", "TARO YAMADA", "Taro　Yamada", "Taro Yamada-san"):
            with self.subTest(target=t):
                self.assertTrue(self.f(t, extra_aliases=al))

    def test_extra_alias_multiword_contiguous_subsequence(self):
        al = ("taro yamada",)
        for t in ("Nakai、Taro Yamada", "Taro Yamada、Nakai", "Nakai Taro Yamada Suzuki",
                  "Nakai/Taro Yamada/Suzuki"):
            with self.subTest(target=t):
                self.assertTrue(self.f(t, extra_aliases=al))

    def test_extra_alias_multiword_non_matches(self):
        al = ("taro yamada",)
        for t in ("Yamada Taro", "Taro Nakai Yamada", "Taro", "Yamada", "Taro Yamadaa", "Nakai"):
            with self.subTest(target=t):
                self.assertFalse(self.f(t, extra_aliases=al))

    def test_extra_alias_multiword_reverse_order_needs_its_own_alias(self):
        al = ("taro yamada", "yamada taro")
        self.assertTrue(self.f("Yamada Taro", extra_aliases=al))
        self.assertTrue(self.f("Taro Yamada", extra_aliases=al))

    def test_blank_extra_aliases_never_match(self):
        for aliases in (("",), ("  ",), ("　",), ("", "  ")):
            with self.subTest(aliases=aliases):
                self.assertFalse(self.f("Nakai", extra_aliases=aliases))
                self.assertFalse(self.f("Nakai、", extra_aliases=aliases))
                self.assertFalse(self.f("Nakai、、Tanaka", extra_aliases=aliases))

    def test_extra_aliases_do_not_remove_builtin_ones(self):
        self.assertTrue(self.f("あなた", extra_aliases=("taro yamada",)))
        self.assertTrue(self.f("", extra_aliases=("taro yamada",)))

    def test_list_and_tuple_extra_aliases_equivalent(self):
        self.assertTrue(self.f("Yamada", extra_aliases=["yamada"]))
        self.assertTrue(self.f("Yamada", extra_aliases=("yamada",)))


class TestSpecGapIsTargetSelf(unittest.TestCase):
    """仕様が曖昧/未記載の入力。自然な解釈で書いている。"""

    def f(self, *a, **k):
        return oto().is_target_self(*a, **k)

    def test_separator_only_target_is_not_self(self):
        # 仕様: 「None/空文字/空白のみ → True」。区切り文字だけ ("、", "()") は列挙に無い。
        # 既存HTMLが「あなた」と表示するのは空targetのみ → False が自然。
        # (実装が「トークン0個ならTrue」としていると True になる → 要確認)
        for t in ("、", "()", "/", "（）", "「」", ";;", ", ,", "。", ".", "『』", '""', "“”"):
            with self.subTest(target=t):
                self.assertFalse(self.f(t))

    def test_own_email_address_inside_a_multi_recipient_target_is_self(self):
        # メールアドレス全体の別名は「対象全体との完全一致」でしか拾えない恐れがある。区切りに "." が
        # 入っているため "yuichi.ochi@example.com" は複数宛先の中だと "yuichi" "ochi@example" "com" に割れる。
        # 自然な期待: 複数宛先の1つが自分のアドレスなら自分宛て (AIが宛先をアドレス表記で並べた場合)
        al = oto().build_self_aliases("Ochi, Yuichi", "yuichi.ochi@example.com")
        self.assertTrue(self.f("Nakai, yuichi.ochi@example.com", al))
        self.assertTrue(self.f("nakai@example.com; yuichi.ochi@example.com", al))
        self.assertTrue(self.f("yuichi.ochi@example.com、nakai@example.com", al))

    def test_own_email_address_in_angle_brackets_is_self(self):
        al = oto().build_self_aliases("", "yuichi.ochi@example.com")
        self.assertTrue(self.f("<yuichi.ochi@example.com>", al))
        self.assertTrue(self.f("Ochi Yuichi (yuichi.ochi@example.com)", al))
        self.assertFalse(self.f("<nakai@example.com>", al))

    def test_dotted_alias_given_alone_matches_the_same_dotted_target(self):
        # "." が区切りになっても、別名と対象全体が完全一致するなら True が自然 (build_self_aliases は
        # "yamada.taro" と "yamada taro" の両方を返すが、extra_aliases を直接渡す呼び出しもあり得る)
        self.assertTrue(self.f("yamada.taro", extra_aliases=("yamada.taro",)))
        self.assertFalse(self.f("nakai.hanako", extra_aliases=("yamada.taro",)))

    def test_extra_aliases_none_is_like_empty(self):
        self.assertFalse(self.f("Nakai", extra_aliases=None))
        self.assertTrue(self.f("Ochi", extra_aliases=None))

    def test_bare_string_extra_alias_is_one_alias_not_characters(self):
        # extra_aliases="yamada" (タプルにし忘れ) を1文字ずつ別名と解釈してはいけない
        self.assertFalse(self.f("a", extra_aliases="yamada"))
        self.assertTrue(self.f("Yamada", extra_aliases="yamada"))

    def test_newline_and_tab_split_tokens(self):
        # 区切りに列挙されているのは半角/全角空白のみ。改行/タブは未記載 → 空白の仲間として分割が自然
        self.assertTrue(self.f("Nakai\nOchi"))
        self.assertTrue(self.f("Nakai\tOchi"))

    def test_non_string_target_does_not_raise(self):
        for t in (123, 4.5, ["あなた"], {"a": 1}, True):
            with self.subTest(target=t):
                self.assertIn(self.f(t), (True, False))


# ============================================================
# 3. build_self_aliases
# ============================================================
class TestBuildSelfAliases(unittest.TestCase):
    def b(self, name, smtp):
        return oto().build_self_aliases(name, smtp)

    def assert_well_formed(self, aliases):
        self.assertIsInstance(aliases, list)
        self.assertEqual(len(aliases), len(set(aliases)), f"重複あり: {aliases}")
        norm = oto().normalize_action_target_token
        for a in aliases:
            self.assertIsInstance(a, str)
            self.assertTrue(a, f"空文字が混入: {aliases}")
            self.assertEqual(a, norm(a), f"normalize済みでない: {a!r}")

    def test_last_comma_first(self):
        al = self.b("Ochi, Yuichi", "")
        for want in ("ochi yuichi", "yuichi ochi", "ochiyuichi", "yuichiochi"):
            self.assertIn(want, al)
        self.assert_well_formed(al)

    def test_two_words_separated_by_space(self):
        al = self.b("Yuichi Ochi", "")
        for want in ("yuichi ochi", "ochi yuichi", "yuichiochi", "ochiyuichi"):
            self.assertIn(want, al)
        self.assert_well_formed(al)

    def test_japanese_name_with_fullwidth_space(self):
        al = self.b("越智　勇一", "")
        for want in ("越智 勇一", "勇一 越智", "越智勇一", "勇一越智"):
            self.assertIn(want, al)
        self.assert_well_formed(al)

    def test_smtp_local_part(self):
        al = self.b("", "yuichi.ochi@example.com")
        for want in ("yuichi.ochi", "yuichi ochi", "ochi yuichi"):
            self.assertIn(want, al)
        self.assert_well_formed(al)

    def test_smtp_full_address_is_an_alias_but_the_domain_alone_is_not(self):
        # 仕様変更(第3回): SMTPアドレス全体 ("yuichi.ochi@example.com") も別名に含める
        al = self.b("", "yuichi.ochi@example.com")
        self.assertIn("yuichi.ochi@example.com", al)
        for a in al:
            if "@" in a or "example" in a:
                self.assertEqual(a, "yuichi.ochi@example.com", f"ドメイン由来の余計な別名: {a!r}")
        self.assertNotIn("example.com", al)
        self.assertNotIn("example", al)
        self.assert_well_formed(al)

    def test_full_address_alias_is_normalized_and_lowercased(self):
        al = self.b("", "Yuichi.OCHI@Example.COM")
        self.assertIn("yuichi.ochi@example.com", al)
        self.assert_well_formed(al)

    def test_full_address_is_included_together_with_name_forms(self):
        al = self.b("Ochi, Yuichi", "yuichi.ochi@example.com")
        for want in ("ochi yuichi", "yuichi ochi", "ochiyuichi", "yuichiochi", "yuichi.ochi",
                     "yuichi.ochi@example.com"):
            self.assertIn(want, al)
        self.assert_well_formed(al)

    def test_smtp_local_part_with_underscore_or_hyphen(self):
        for local in ("yuichi_ochi", "yuichi-ochi"):
            with self.subTest(local=local):
                al = self.b("", f"{local}@example.com")
                self.assertIn(local, al)
                self.assertIn("yuichi ochi", al)
                self.assertIn("ochi yuichi", al)
                self.assert_well_formed(al)

    def test_smtp_is_lowercased(self):
        al = self.b("", "Yuichi.OCHI@Example.COM")
        self.assertIn("yuichi.ochi", al)
        self.assertIn("yuichi ochi", al)

    def test_name_and_smtp_are_deduplicated(self):
        al = self.b("Yuichi Ochi", "yuichi.ochi@example.com")
        self.assertEqual(al.count("yuichi ochi"), 1)
        self.assertEqual(al.count("ochi yuichi"), 1)
        self.assert_well_formed(al)

    def test_empty_or_none_gives_empty_list(self):
        for args in (("", ""), (None, None), ("", None), (None, "")):
            with self.subTest(args=args):
                self.assertEqual(self.b(*args), [])

    def test_name_only_and_smtp_only_are_independent(self):
        self.assertTrue(self.b("Ochi, Yuichi", None))
        self.assertTrue(self.b(None, "yuichi.ochi@example.com"))

    def test_three_part_local_part_is_well_formed(self):
        al = self.b("", "a.b.c@example.com")
        self.assertIn("a.b.c", al)
        self.assertIn("a b c", al)
        self.assert_well_formed(al)

    def test_result_works_with_is_target_self(self):
        al = self.b("Ochi, Yuichi", "yuichi.ochi@example.com")
        f = oto().is_target_self
        self.assertTrue(f("Yuichi Ochi", al))
        self.assertTrue(f("Yuichi Ochi-san", al))
        self.assertTrue(f("Nakai、Ochi Yuichi", al))
        self.assertTrue(f("yuichi.ochi", al))
        self.assertFalse(f("Nakai", al))
        self.assertFalse(f("Yuichi Ochiai", al))


class TestSpecGapBuildSelfAliases(unittest.TestCase):
    def b(self, name, smtp):
        return oto().build_self_aliases(name, smtp)

    def test_whitespace_only_inputs_give_empty_list(self):
        # 仕様は「空・None なら空リスト」。空白のみも空とみなすのが自然
        for args in (("   ", ""), ("", "  "), ("　", "　")):
            with self.subTest(args=args):
                self.assertEqual(self.b(*args), [])

    def test_single_word_name_is_included(self):
        # 1語の表示名: 仕様は2語の順序入替のみ記載。正規化した名前そのものを別名に含めるのが自然
        self.assertIn("ochi", self.b("Ochi", ""))
        self.assertIn("越智", self.b("越智", ""))

    def test_smtp_without_at_sign_does_not_raise(self):
        # Exchange内部アドレス等で "@" が無い場合。例外を出さずリストを返すこと
        for smtp in ("yuichi.ochi", "/o=exchangelabs/ou=x/cn=recipients/cn=abc", "@", "a@"):
            with self.subTest(smtp=smtp):
                self.assertIsInstance(self.b("", smtp), list)

    def test_name_with_parenthesized_suffix_does_not_raise(self):
        # 実在しがちな表示名 "Ochi, Yuichi (Nexperia)" 。仕様に記載なし → 例外にしないことだけ確認
        al = self.b("Ochi, Yuichi (Nexperia)", "")
        self.assertIsInstance(al, list)

    def test_non_string_inputs_do_not_raise(self):
        for args in ((123, 456), (["a"], {"b": 1})):
            with self.subTest(args=args):
                self.assertIsInstance(self.b(*args), list)


# ============================================================
# 4. is_decision_action
# ============================================================
class TestIsDecisionAction(unittest.TestCase):
    def f(self, *a):
        return oto().is_decision_action(*a)

    def test_thread_type_decides(self):
        for t in ("承認・決裁", "相談・質問"):
            with self.subTest(type=t):
                self.assertTrue(self.f("資料を送ってください", t))

    def test_thread_type_is_nfkc_and_stripped(self):
        for t in (" 承認・決裁 ", "　相談・質問　", "承認･決裁", "\t承認・決裁\n"):
            with self.subTest(type=t):
                self.assertTrue(self.f("資料を送ってください", t))

    def test_keywords_in_action_text(self):
        for kw in ("承認", "決裁", "判断"):
            for t in ("作業・依頼", "通知・共有", "その他", "", None):
                with self.subTest(kw=kw, type=t):
                    self.assertTrue(self.f(f"{kw}をお願いします", t))

    def test_keyword_substring_anywhere(self):
        for text in ("ご承認ください", "未承認の件", "判断材料を共有", "最終決裁待ち", "Please 承認 this"):
            with self.subTest(text=text):
                self.assertTrue(self.f(text, "作業・依頼"))

    def test_not_a_decision(self):
        for text, t in (("資料を送ってください", "作業・依頼"), ("", ""), ("", "通知・共有"),
                        ("確認ください", "その他"), ("裁決をお願いします", "作業・依頼")):
            with self.subTest(text=text, type=t):
                self.assertFalse(self.f(text, t))

    def test_type_requires_exact_match(self):
        # 種別は完全一致 (部分一致でTrueにしない)。キーワードも無い文面で確認
        for t in ("承認", "決裁", "相談", "質問", "承認・決裁等", "承認・決裁・相談・質問の件"):
            with self.subTest(type=t):
                self.assertFalse(self.f("資料を送ってください", t))

    def test_none_safe(self):
        self.assertTrue(self.f(None, "承認・決裁"))
        self.assertTrue(self.f("承認してください", None))
        self.assertFalse(self.f(None, None))
        self.assertFalse(self.f(None, "作業・依頼"))
        self.assertFalse(self.f("", None))

    def test_returns_bool(self):
        self.assertIs(self.f("承認", None), True)
        self.assertIs(self.f("確認", None), False)

    # ---- 仕様変更(第2回): 判断語の直後が「済」なら判断語として数えない ------------------
    def test_keyword_followed_by_sumi_is_not_a_decision(self):
        for text in ("承認済みです", "承認済", "決裁済みです", "決裁済", "判断済みです", "判断済", "ご承認済みの件",
                     "すでに承認済みです。"):
            with self.subTest(text=text):
                self.assertFalse(self.f(text, "作業・依頼"))
                self.assertFalse(self.f(text, None))

    def test_sumi_followed_by_other_characters_is_still_sumi(self):
        # 直後が「済」であれば、その次が「み」でなくても判断語として数えない
        for text in ("承認済の件です", "承認済です", "決裁済と聞いた", "判断済で", "承認済。", "承認済\n",
                     "承認済 ですが"):
            with self.subTest(text=text):
                self.assertFalse(self.f(text, "作業・依頼"))

    def test_another_keyword_later_still_makes_it_a_decision(self):
        for text in ("承認済みの上で判断をお願いします", "承認済み、決裁をお願いします",
                     "決裁済みですが承認が必要です", "判断済みの件。ただし承認待ち", "承認済み承認"):
            with self.subTest(text=text):
                self.assertTrue(self.f(text, "作業・依頼"))

    def test_not_approved_and_plain_keywords_are_decisions(self):
        for text in ("未承認です", "未承認", "承認をお願いします", "承認", "決裁願います", "判断を仰ぎたい",
                     "承認 済み", "承認が必要"):
            with self.subTest(text=text):
                self.assertTrue(self.f(text, "作業・依頼"))

    def test_decision_thread_type_wins_over_sumi_rule(self):
        # スレッドの action_type が「承認・決裁/相談・質問」なら語に関係なく True (不変)
        for t in ("承認・決裁", "相談・質問"):
            with self.subTest(type=t):
                self.assertTrue(self.f("承認済みです", t))
                self.assertTrue(self.f("資料を送ってください", t))


class TestSpecGapIsDecisionAction(unittest.TestCase):
    def test_non_string_inputs_do_not_raise(self):
        for args in ((123, 456), (["承認"], None), (None, ["承認・決裁"])):
            with self.subTest(args=args):
                self.assertIn(oto().is_decision_action(*args), (True, False))


# ============================================================
# 5. load_action_dashboard_cache
# ============================================================
class TestLoadActionDashboardCache(unittest.TestCase):
    def load(self):
        return oto().load_action_dashboard_cache()

    def test_missing_file_returns_empty_threads(self):
        with tempdir_cwd():
            self.assertEqual(self.load(), {"threads": {}})

    def test_missing_dir_and_file_creates_nothing(self):
        # 読み取り専用の関数: ファイル無しでキャッシュのファイルもディレクトリも作らない
        with tempdir_cwd():
            self.load()
            self.assertFalse(os.path.exists(CACHE_PATH))
            self.assertEqual(os.listdir("."), [])

    def test_valid_file_returns_cache_dict(self):
        cache = make_cache({"C1": make_thread(), "C2": make_thread(error=True)})
        with tempdir_cwd():
            write_json(CACHE_PATH, cache)
            res = self.load()
            self.assertIsInstance(res, dict)
            self.assertEqual(res, cache)
            self.assertEqual(sorted(res["threads"]), ["C1", "C2"])

    def test_empty_threads_is_valid_zero_not_unknown(self):
        with tempdir_cwd():
            write_json(CACHE_PATH, {"threads": {}})
            self.assertEqual(self.load(), {"threads": {}})

    def test_invalid_json_returns_none(self):
        for raw in ("{not json", "{", '{"threads": {', "\x00\x01garbage", "threads"):
            with self.subTest(raw=raw):
                with tempdir_cwd():
                    write_text(CACHE_PATH, raw)
                    self.assertIsNone(self.load())

    def test_zero_byte_file_returns_none(self):
        with tempdir_cwd():
            write_bytes(CACHE_PATH, b"")
            self.assertIsNone(self.load())

    def test_whitespace_only_file_returns_none(self):
        with tempdir_cwd():
            write_text(CACHE_PATH, " \n\t ")
            self.assertIsNone(self.load())

    def test_wrong_types_return_none(self):
        bad = ('[]', '"threads"', '123', 'null', 'true', '{}', '{"threads": null}', '{"threads": []}',
               '{"threads": "x"}', '{"threads": 5}', '{"other": {}}')
        for raw in bad:
            with self.subTest(raw=raw):
                with tempdir_cwd():
                    write_text(CACHE_PATH, raw)
                    self.assertIsNone(self.load())

    def test_non_utf8_bytes_return_none_not_exception(self):
        # UnicodeDecodeError は OSError でも JSONDecodeError でもない → 取りこぼしやすい
        with tempdir_cwd():
            write_bytes(CACHE_PATH, b'{"threads": {"a": "\xff\xfe\x80"}}')
            self.assertIsNone(self.load())

    def test_path_is_a_directory_returns_none(self):
        with tempdir_cwd():
            os.makedirs(CACHE_PATH)          # ファイルのはずの場所がディレクトリ (OSError系)
            self.assertIsNone(self.load())

    def test_does_not_modify_file(self):
        cache = make_cache({"C1": make_thread()})
        with tempdir_cwd():
            write_json(CACHE_PATH, cache)
            before = _loader.snapshot_files(".")
            self.load()
            self.assertEqual(_loader.snapshot_files("."), before)


# ============================================================
# 6. compute_pending_decisions
# ============================================================
class ComputeBase(unittest.TestCase):
    def compute(self, threads, statuses=None, **kw):
        return oto().compute_pending_decisions(
            make_cache(threads), {} if statuses is None else statuses, **kw)

    def key(self, cid, idx=0):
        return oto().make_action_key_by_index(cid, idx)


class TestComputePendingBasics(ComputeBase):
    def test_empty_cache_gives_empty_list(self):
        rows = self.compute({})
        self.assertIsInstance(rows, list)
        self.assertEqual(rows, [])

    def test_row_fields(self):
        t = make_thread(
            [make_action(owner="Nakai", target="あなた", action="予算を承認してください",
                         deadline="10/10", status="返信待ち")],
            topic="AI要約タイトルX", real_topic="実件名X", importance="高", latest_ts=ts_ago(3),
            entry_id="E-META", cached_entry_id="E-CACHED")
        rows = self.compute({"C1": t})
        self.assertEqual(len(rows), 1)
        r = rows[0]
        for k in ROW_KEYS:
            self.assertIn(k, r, f"行に {k} が無い")
        self.assertEqual(r["key"], self.key("C1", 0))
        self.assertEqual(r["cid"], "C1")
        self.assertEqual(r["topic"], "AI要約タイトルX")
        self.assertEqual(r["real_topic"], "実件名X")
        self.assertEqual(r["entry_id"], "E-META")
        self.assertEqual(r["latest_ts"], ts_ago(3))
        self.assertEqual(r["date_mmdd"], t["meta"]["latest_date_mmdd"])
        self.assertEqual(r["importance"], "高")
        self.assertEqual(r["owner"], "Nakai")
        self.assertEqual(r["target"], "あなた")
        self.assertEqual(r["action"], "予算を承認してください")
        self.assertEqual(r["deadline"], "10/10")
        self.assertEqual(r["ai_status"], "返信待ち")
        self.assertEqual(r["progress"], "not_started")
        self.assertEqual(r["priority"], "")
        self.assertEqual(r["comment"], "")
        self.assertIs(r["resurfaced"], False)          # 仕様変更(第2回): 各行に resurfaced / is_decision
        self.assertIs(r["is_decision"], True)

    def test_resurfaced_and_is_decision_are_bools_on_every_row(self):
        rows = self.compute({"A": make_thread(), "B": make_thread([make_action(action="承認を"),
                                                                      make_action(action="決裁を")])})
        self.assertEqual(len(rows), 3)
        for r in rows:
            self.assertIs(r["resurfaced"], False)
            self.assertIs(r["is_decision"], True)

    def test_status_values_flow_into_row(self):
        k = self.key("C1", 0)
        rows = self.compute({"C1": make_thread()},
                            {k: make_status("in_progress", "high", "確認中のメモ")})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["progress"], "in_progress")
        self.assertEqual(rows[0]["priority"], "high")
        self.assertEqual(rows[0]["comment"], "確認中のメモ")

    def test_cid_is_the_cache_key(self):
        t = make_thread()
        cache = make_cache({"REAL-CID": t})
        cache["threads"]["REAL-CID"]["data"]["thread_id"] = "SOMETHING-ELSE"
        rows = oto().compute_pending_decisions(cache, {})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["cid"], "REAL-CID")
        self.assertEqual(rows[0]["key"], self.key("REAL-CID", 0))

    def test_entry_id_prefers_meta(self):
        rows = self.compute({"C1": make_thread(entry_id="E-META", cached_entry_id="E-CACHED")})
        self.assertEqual(rows[0]["entry_id"], "E-META")

    def test_entry_id_falls_back_to_cached_when_meta_lacks_it(self):
        t = make_thread(entry_id="E-META", cached_entry_id="E-CACHED")
        del t["meta"]["latest_entry_id"]
        rows = self.compute({"C1": t})
        self.assertEqual(rows[0]["entry_id"], "E-CACHED")

    def test_entry_id_empty_when_nowhere(self):
        t = make_thread()
        del t["meta"]["latest_entry_id"]
        del t["latest_entry_id"]
        rows = self.compute({"C1": t})
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["entry_id"])      # "" か None (GUIは空なら何もしない)


class TestComputePendingFilters(ComputeBase):
    def test_thread_without_meta_is_skipped(self):
        self.assertEqual(self.compute({"C1": make_thread(meta=False)}), [])

    def test_meta_none_is_skipped(self):
        t = make_thread()
        t["meta"] = None
        self.assertEqual(self.compute({"C1": t}), [])

    def test_error_thread_is_skipped(self):
        self.assertEqual(self.compute({"C1": make_thread(error=True)}), [])

    def test_thread_without_data_is_skipped(self):
        t = make_thread()
        del t["data"]
        self.assertEqual(self.compute({"C1": t}), [])

    def test_empty_action_text_is_skipped_but_still_counts_in_index(self):
        # idx は actions 配列の添字。action文が空のアクションも添字には数える (仕様)
        acts = [make_action(action=""), make_action(action="   "), make_action(action="　"),
                make_action(action="承認をお願いします")]
        rows = self.compute({"C1": make_thread(acts)})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["key"], self.key("C1", 3))
        self.assertNotEqual(rows[0]["key"], self.key("C1", 0))

    def test_status_of_other_index_does_not_leak(self):
        acts = [make_action(action=""), make_action(action="承認をお願いします")]
        st = {self.key("C1", 0): make_status("done")}      # 空文字アクション側のキー
        rows = self.compute({"C1": make_thread(acts)}, st)
        self.assertEqual([r["key"] for r in rows], [self.key("C1", 1)])
        st = {self.key("C1", 1): make_status("done")}
        self.assertEqual(self.compute({"C1": make_thread(acts)}, st), [])

    def test_done_and_ignored_are_not_counted(self):
        threads = {c: make_thread() for c in ("D", "I", "N", "P")}
        st = {self.key("D"): make_status("done"), self.key("I"): make_status("ignored"),
              self.key("P"): make_status("in_progress")}
        rows = self.compute(threads, st)
        self.assertEqual(sorted(r["cid"] for r in rows), ["N", "P"])
        prog = {r["cid"]: r["progress"] for r in rows}
        self.assertEqual(prog, {"N": "not_started", "P": "in_progress"})

    def test_target_must_be_self(self):
        cases = {
            "A": ("Nakai", False), "B": ("各位", False), "C": ("", True), "D": (None, True),
            "E": ("あなた、Nakai", True), "F": ("Ochiai", False), "G": ("越智さん", True),
            "H": ("Nakai/Tanaka", False),
        }
        threads = {cid: make_thread([make_action(target=t)]) for cid, (t, _) in cases.items()}
        rows = self.compute(threads)
        self.assertEqual(sorted(r["cid"] for r in rows),
                         sorted(cid for cid, (_, ok) in cases.items() if ok))

    def test_extra_aliases_are_passed_through(self):
        threads = {"C1": make_thread([make_action(target="Taro Yamada")])}
        self.assertEqual(self.compute(threads), [])
        rows = self.compute(threads, extra_aliases=("taro yamada",))
        self.assertEqual([r["cid"] for r in rows], ["C1"])
        rows = self.compute(threads, extra_aliases=["taro yamada"])
        self.assertEqual(len(rows), 1)

    def test_decision_condition_by_thread_type_or_keyword(self):
        threads = {
            "T1": make_thread([make_action(action="資料を送ってください")], action_type="承認・決裁"),
            "T2": make_thread([make_action(action="資料を送ってください")], action_type="相談・質問"),
            "T3": make_thread([make_action(action="資料を送ってください")], action_type="作業・依頼"),
            "T4": make_thread([make_action(action="資料を送ってください")], action_type="通知・共有"),
            "K1": make_thread([make_action(action="承認をお願いします")], action_type="作業・依頼"),
            "K2": make_thread([make_action(action="決裁願います")], action_type="通知・共有"),
            "K3": make_thread([make_action(action="ご判断ください")], action_type="その他"),
            "X1": make_thread([make_action(action="確認してください")], action_type="その他"),
        }
        rows = self.compute(threads)
        self.assertEqual(sorted(r["cid"] for r in rows), ["K1", "K2", "K3", "T1", "T2"])

    def test_thread_type_applies_to_every_action_in_thread(self):
        acts = [make_action(action="A を送って"), make_action(action="B を作って")]
        rows = self.compute({"C1": make_thread(acts, action_type="相談・質問")})
        self.assertEqual(sorted(r["key"] for r in rows),
                         sorted([self.key("C1", 0), self.key("C1", 1)]))

    def test_multiple_actions_judged_independently(self):
        acts = [make_action(action="承認してください", target="あなた"),
                make_action(action="承認してください", target="Nakai"),
                make_action(action="承認してください", target="あなた"),
                make_action(action="承認してください", target="あなた", deadline="10/9")]
        st = {self.key("C1", 2): make_status("done")}
        rows = self.compute({"C1": make_thread(acts)}, st)
        self.assertEqual(sorted(r["key"] for r in rows),
                         sorted([self.key("C1", 0), self.key("C1", 3)]))

    # ---- 旧キー引継ぎ (読み取りのみ) ----------------------------------
    def test_legacy_key_status_is_inherited_done(self):
        a = make_action(owner="Nakai", action="承認をお願いします")
        legacy = oto().make_action_key("C1", "Nakai", "承認をお願いします")
        self.assertEqual(self.compute({"C1": make_thread([a])}, {legacy: make_status("done")}), [])

    def test_legacy_key_status_is_inherited_fields(self):
        a = make_action(owner="Nakai", action="承認をお願いします")
        legacy = oto().make_action_key("C1", "Nakai", "承認をお願いします")
        rows = self.compute({"C1": make_thread([a])},
                            {legacy: make_status("in_progress", "top", "旧コメント")})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["progress"], "in_progress")
        self.assertEqual(rows[0]["priority"], "top")
        self.assertEqual(rows[0]["comment"], "旧コメント")

    def test_new_key_takes_precedence_over_legacy(self):
        a = make_action(owner="Nakai", action="承認をお願いします")
        legacy = oto().make_action_key("C1", "Nakai", "承認をお願いします")
        st = {legacy: make_status("done"), self.key("C1", 0): make_status("in_progress", "high")}
        rows = self.compute({"C1": make_thread([a])}, st)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["progress"], "in_progress")
        self.assertEqual(rows[0]["priority"], "high")

    def test_legacy_key_uses_first_40_chars_of_action(self):
        long_action = "承認をお願いします。" + "あ" * 80
        a = make_action(owner="Nakai", action=long_action)
        legacy = oto().make_action_key("C1", "Nakai", long_action)
        self.assertEqual(self.compute({"C1": make_thread([a])}, {legacy: make_status("ignored")}), [])

    def test_legacy_key_of_other_owner_or_action_is_not_inherited(self):
        a = make_action(owner="Nakai", action="承認をお願いします")
        other_owner = oto().make_action_key("C1", "Tanaka", "承認をお願いします")
        other_action = oto().make_action_key("C1", "Nakai", "別の依頼")
        other_cid = oto().make_action_key("C2", "Nakai", "承認をお願いします")
        st = {other_owner: make_status("done"), other_action: make_status("done"),
              other_cid: make_status("done")}
        self.assertEqual(len(self.compute({"C1": make_thread([a])}, st)), 1)

    def test_legacy_inheritance_does_not_write_back_to_input(self):
        # 「読み取りのみ。書き戻しはしない」: 呼び出し側の dict に移行キーを足さない
        a = make_action(owner="Nakai", action="承認をお願いします")
        legacy = oto().make_action_key("C1", "Nakai", "承認をお願いします")
        st = {legacy: make_status("in_progress")}
        before = copy.deepcopy(st)
        self.compute({"C1": make_thread([a])}, st)
        self.assertEqual(st, before)

    # ---- since_ts -----------------------------------------------------
    def test_since_ts_boundary_is_inclusive(self):
        since = ts_ago(48)
        threads = {"AT": make_thread(latest_ts=since), "AFTER": make_thread(latest_ts=since + 1),
                   "BEFORE": make_thread(latest_ts=since - 1)}
        rows = self.compute(threads, since_ts=since)
        self.assertEqual(sorted(r["cid"] for r in rows), ["AFTER", "AT"])

    def test_since_ts_none_means_no_filtering(self):
        threads = {"OLD": make_thread(latest_ts=ts_ago(24 * 365)), "NEW": make_thread(latest_ts=ts_ago(1)),
                   "ZERO": make_thread(latest_ts=0)}
        rows = self.compute(threads, since_ts=None)
        self.assertEqual(sorted(r["cid"] for r in rows), ["NEW", "OLD", "ZERO"])
        rows = self.compute(threads)
        self.assertEqual(len(rows), 3)

    def test_since_ts_zero_includes_epoch_zero(self):
        rows = self.compute({"ZERO": make_thread(latest_ts=0)}, since_ts=0)
        self.assertEqual([r["cid"] for r in rows], ["ZERO"])

    def test_since_ts_float(self):
        base = ts_ago(10)
        threads = {"A": make_thread(latest_ts=base), "B": make_thread(latest_ts=base + 1)}
        rows = self.compute(threads, since_ts=base + 0.5)
        self.assertEqual([r["cid"] for r in rows], ["B"])

    def test_since_ts_applies_before_other_conditions_only_to_included_threads(self):
        # since_ts 外のスレッドは「判断待ち」にも数えない (error_count 側は別関数)
        since = ts_ago(48)
        rows = self.compute({"OLD": make_thread(latest_ts=since - 10 * HOUR)}, since_ts=since)
        self.assertEqual(rows, [])


class TestComputePendingResurfacing(ComputeBase):
    """仕様変更(第2回) B1「完了後の新着で再浮上」。
      - progress=="ignored" は常に除外 (新着があっても)
      - progress=="done" は、状態の updated_at (ISO '%Y-%m-%dT%H:%M:%S'・ローカル時刻) がパースでき、かつ
        meta.latest_ts > epoch(updated_at) のときだけ再浮上して一覧に含める (行に resurfaced: True)
      - updated_at が無い/不正、または latest_ts <= updated_at なら従来どおり除外
      - 旧キー(legacy)経由の done も同じ規則
    """

    U = "2026-10-01T09:00:00"

    @property
    def u(self):
        return iso_epoch(self.U)

    _UNSET = object()

    def done(self, updated_at=_UNSET, **kw):
        return make_status("done", updated_at=self.U if updated_at is self._UNSET else updated_at, **kw)

    def one(self, latest_ts, status, cid="C1", **kw):
        threads = {cid: make_thread(latest_ts=latest_ts)}
        return self.compute(threads, {self.key(cid): status} if status is not None else {}, **kw)

    def test_done_with_newer_mail_resurfaces(self):
        rows = self.one(self.u + 1, self.done())
        self.assertEqual(len(rows), 1)
        self.assertIs(rows[0]["resurfaced"], True)
        self.assertIs(rows[0]["is_decision"], True)
        self.assertEqual(rows[0]["key"], self.key("C1"))
        self.assertEqual(rows[0]["latest_ts"], self.u + 1)

    def test_done_with_much_newer_mail_resurfaces(self):
        for delta in (1, 60, 3600, 86400 * 30):
            with self.subTest(delta=delta):
                rows = self.one(self.u + delta, self.done())
                self.assertEqual([r["resurfaced"] for r in rows], [True])

    def test_done_boundary_equal_or_older_is_excluded(self):
        # latest_ts <= updated_at → 従来どおり除外 (ちょうど同時刻も除外)
        for delta in (0, -1, -3600, -86400 * 30):
            with self.subTest(delta=delta):
                self.assertEqual(self.one(self.u + delta, self.done()), [])

    def test_done_without_updated_at_is_excluded(self):
        st = {"progress": "done", "priority": "", "comment": ""}
        self.assertEqual(self.one(self.u + 10 ** 6, st), [])
        self.assertEqual(self.one(2_000_000_000, st), [])

    def test_done_with_invalid_updated_at_is_excluded(self):
        for bad in ("", None, "garbage", 12345, "2026-13-45T25:61:61", "2026/10/01 09:00:00", [], {}, True,
                    "2026-10-01"):
            with self.subTest(updated_at=bad):
                st = self.done(bad)
                self.assertEqual(self.one(2_000_000_000, st), [])

    def test_ignored_never_resurfaces(self):
        st = make_status("ignored", updated_at=self.U)
        self.assertEqual(self.one(self.u + 10 ** 6, st), [])
        self.assertEqual(self.one(2_000_000_000, make_status("ignored", updated_at="")), [])

    def test_non_done_rows_are_never_marked_resurfaced(self):
        # 再浮上は done 専用。updated_at より新しい latest_ts でも in_progress / not_started は通常の行
        for progress in ("not_started", "in_progress"):
            with self.subTest(progress=progress):
                rows = self.one(self.u + 100, make_status(progress, updated_at=self.U))
                self.assertEqual([r["resurfaced"] for r in rows], [False])
                self.assertEqual(rows[0]["progress"], progress)

    def test_no_status_entry_is_a_normal_row(self):
        rows = self.one(self.u + 100, None)
        self.assertEqual([r["resurfaced"] for r in rows], [False])

    def test_legacy_key_done_resurfaces_by_the_same_rule(self):
        a = make_action(owner="Nakai", action="承認をお願いします")
        legacy = oto().make_action_key("C1", "Nakai", "承認をお願いします")
        newer = {"C1": make_thread([a], latest_ts=self.u + 1)}
        older = {"C1": make_thread([a], latest_ts=self.u - 1)}
        same = {"C1": make_thread([a], latest_ts=self.u)}
        rows = self.compute(newer, {legacy: self.done()})
        self.assertEqual([r["resurfaced"] for r in rows], [True])
        self.assertEqual(self.compute(older, {legacy: self.done()}), [])
        self.assertEqual(self.compute(same, {legacy: self.done()}), [])
        self.assertEqual(self.compute(newer, {legacy: make_status("ignored", updated_at=self.U)}), [])
        no_ts = {legacy: {"progress": "done", "priority": "", "comment": ""}}
        self.assertEqual(self.compute(newer, no_ts), [])

    def test_new_key_takes_precedence_over_legacy_done(self):
        a = make_action(owner="Nakai", action="承認をお願いします")
        legacy = oto().make_action_key("C1", "Nakai", "承認をお願いします")
        st = {legacy: self.done(), self.key("C1"): make_status("not_started", updated_at=self.U)}
        rows = self.compute({"C1": make_thread([a], latest_ts=self.u + 1)}, st)
        self.assertEqual([r["resurfaced"] for r in rows], [False])
        self.assertEqual(rows[0]["progress"], "not_started")

    def test_each_action_uses_its_own_status(self):
        acts = [make_action(action="承認A"), make_action(action="承認B"), make_action(action="承認C"),
                make_action(action="承認D")]
        st = {
            self.key("C1", 0): self.done(),                                    # 新着あり → 再浮上
            self.key("C1", 1): self.done(updated_at="2026-10-02T09:00:00"),     # updated_at が latest_ts より後 → 除外
            self.key("C1", 2): make_status("ignored", updated_at=self.U),       # 除外
            # idx 3: 状態なし → 通常の行
        }
        rows = self.compute({"C1": make_thread(acts, latest_ts=iso_epoch("2026-10-01T10:00:00"))}, st)
        got = {r["key"]: r["resurfaced"] for r in rows}
        self.assertEqual(got, {self.key("C1", 0): True, self.key("C1", 3): False})

    def test_resurfaced_row_keeps_priority_and_comment(self):
        rows = self.one(self.u + 5, self.done(priority="top", comment="前回のメモ"))
        self.assertEqual(rows[0]["priority"], "top")
        self.assertEqual(rows[0]["comment"], "前回のメモ")

    def test_resurfaced_rows_still_obey_since_ts_target_and_decision_filters(self):
        t_old = make_thread(latest_ts=self.u + 5)
        t_other = make_thread([make_action(target="Nakai")], latest_ts=self.u + 5)
        t_plain = make_thread([make_action(action="資料送付")], action_type="作業・依頼", latest_ts=self.u + 5)
        t_err = make_thread(error=True, latest_ts=self.u + 5)
        t_nometa = make_thread(meta=False)
        threads = {"OLD": t_old, "OTHER": t_other, "PLAIN": t_plain, "ERR": t_err, "NOMETA": t_nometa}
        st = {self.key(c): self.done() for c in threads}
        rows = self.compute(threads, st, since_ts=self.u + 6)
        self.assertEqual(rows, [], "since_ts より古い再浮上行が含まれた")
        rows = self.compute(threads, st, since_ts=self.u)
        self.assertEqual([r["cid"] for r in rows], ["OLD"])

    def test_marking_done_again_hides_it_again(self):
        # 完了(set_action_progress)した直後は除外に戻る: updated_at が「今」に更新され latest_ts 以上になるため
        with tempdir_cwd():
            latest = int(time.time()) - 3600
            threads = {"C1": make_thread(latest_ts=latest)}
            key = self.key("C1")
            old_iso = datetime.fromtimestamp(latest - 7200).strftime("%Y-%m-%dT%H:%M:%S")
            write_json(STATUS_PATH, {key: make_status("done", updated_at=old_iso)})
            rows = self.compute(threads, read_json(STATUS_PATH))
            self.assertEqual([r["resurfaced"] for r in rows], [True])
            oto().set_action_progress({key: "done"})
            self.assertEqual(self.compute(threads, read_json(STATUS_PATH)), [])
            # 無視にしても同様に除外
            oto().set_action_progress({key: "ignored"})
            self.assertEqual(self.compute(threads, read_json(STATUS_PATH)), [])

    def test_a_fresh_mail_after_completion_resurfaces_again(self):
        # 完了 → さらに新着 (latest_ts > 完了時刻) で再び浮上する
        with tempdir_cwd():
            key = self.key("C1")
            done_epoch = int(time.time())
            write_json(STATUS_PATH, {key: make_status("done", updated_at=datetime.fromtimestamp(done_epoch)
                                                      .strftime("%Y-%m-%dT%H:%M:%S"))})
            st = read_json(STATUS_PATH)
            self.assertEqual(self.compute({"C1": make_thread(latest_ts=done_epoch - 5)}, st), [])
            rows = self.compute({"C1": make_thread(latest_ts=done_epoch + 5)}, st)
            self.assertEqual([r["resurfaced"] for r in rows], [True])

    def test_inputs_are_not_mutated_by_resurfacing(self):
        st = {self.key("C1"): self.done()}
        before = copy.deepcopy(st)
        cache = make_cache({"C1": make_thread(latest_ts=self.u + 1)})
        cache_before = copy.deepcopy(cache)
        oto().compute_pending_decisions(cache, st)
        self.assertEqual(st, before)
        self.assertEqual(cache, cache_before)


class TestSpecGapComputeResurfacing(ComputeBase):
    U = "2026-10-01T09:00:00"

    def test_resurfaced_row_keeps_the_stored_progress_done(self):
        # 仕様は「再浮上して一覧に含める (行に resurfaced: True)」。progress 欄の値は未記載 → 保存値のまま "done" が自然
        u = iso_epoch(self.U)
        rows = self.compute({"C1": make_thread(latest_ts=u + 1)},
                            {self.key("C1"): make_status("done", updated_at=self.U)})
        self.assertEqual(rows[0]["progress"], "done")

    def test_resurfaced_rows_sort_like_other_rows(self):
        # 並び順は (優先度, 期限あり, 新しい順, key) のまま。再浮上だからといって別扱いにしない
        u = iso_epoch(self.U)
        threads = {"NEW": make_thread(latest_ts=u + 100), "OLD": make_thread(latest_ts=u + 50)}
        st = {self.key("NEW"): make_status("done", updated_at=self.U)}          # NEW だけ再浮上
        rows = self.compute(threads, st)
        self.assertEqual([r["cid"] for r in rows], ["NEW", "OLD"])
        st = {self.key("OLD"): make_status("done", updated_at=self.U)}          # OLD だけ再浮上
        rows = self.compute(threads, st)
        self.assertEqual([r["cid"] for r in rows], ["NEW", "OLD"])

    def test_updated_at_with_space_separator_is_handled_without_exception(self):
        u = iso_epoch(self.U)
        st = {self.key("C1"): make_status("done", updated_at="2026-10-01 09:00:00")}
        rows = self.compute({"C1": make_thread(latest_ts=u + 1)}, st)
        self.assertIsInstance(rows, list)



class TestKnownLimitationResurfacingUpdatedAt(ComputeBase):
    """既知の制限の記録 (expectedFailure)。直ったら「想定外の成功」になるので、デコレータを外す。"""

    @unittest.expectedFailure
    def test_editing_comment_or_priority_does_not_hide_a_resurfaced_row(self):
        """既知の制限: updated_at は進捗以外の編集でも更新される。完了日時と編集日時を分けるには
        状態ファイルへ新フィールドが必要 (別段階)。

        再浮上の判定は「状態の updated_at (= 完了時刻のつもり) < latest_ts」。しかし既存の HTTPハンドラ
        /update_action_status は、progress 以外 (優先度・コメント) の変更でも updated_at を「今」に更新する。
        そのため、完了済み・再浮上中の案件に HTMLダッシュボードでコメント/優先度を付けただけで
        updated_at > latest_ts になり、まだ再度「完了」にしていないのに一覧から再び隠れる。
        「progress を変えていない限り再浮上は続くこと」をassertする。現状は隠れるので expectedFailure。
        (実HTTPハンドラで再現。実装は変えない)
        """
        import json as _json
        import threading as _threading
        import urllib.request
        from http.server import ThreadingHTTPServer
        mod = oto()
        try:
            server = ThreadingHTTPServer(("127.0.0.1", 0), mod.OutlookRequestHandler)
        except OSError as e:
            self.skipTest(f"localhost にバインドできない: {e}")
        port = server.server_address[1]
        _threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close()))
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def post(key, **fields):
            body = _json.dumps({"action_key": key, **fields}).encode("utf-8")
            req = urllib.request.Request(f"http://127.0.0.1:{port}/update_action_status", data=body,
                                         headers={"Content-Type": "application/json"}, method="POST")
            with opener.open(req, timeout=20) as resp:
                resp.read()

        with tempdir_cwd():
            latest = int(time.time()) - 3600
            key = self.key("C1")
            done_iso = datetime.fromtimestamp(latest - 7200).strftime("%Y-%m-%dT%H:%M:%S")
            write_json(STATUS_PATH, {key: make_status("done", updated_at=done_iso)})
            threads = {"C1": make_thread(latest_ts=latest)}
            rows = self.compute(threads, read_json(STATUS_PATH))
            self.assertEqual([r["resurfaced"] for r in rows], [True], "前提: 新着ありで再浮上している")
            post(key, comment="返信待ち")                               # progress は変えない
            rows = self.compute(threads, read_json(STATUS_PATH))
            self.assertEqual([r["resurfaced"] for r in rows], [True],
                             "コメントを付けただけで再浮上した案件が一覧から消えた (updated_at が更新されるため)")
            post(key, priority="top")
            rows = self.compute(threads, read_json(STATUS_PATH))
            self.assertEqual([r["resurfaced"] for r in rows], [True],
                             "優先度を変えただけで再浮上した案件が一覧から消えた (updated_at が更新されるため)")



class TestComputePendingOrdering(ComputeBase):
    @staticmethod
    def oracle(spec):
        """spec: {cid: (priority, deadline, latest_ts)} -> 期待キー順"""
        prio_rank = {"top": 2, "high": 1}

        def sort_key(item):
            cid, (prio, deadline, ts) = item
            key = oto().make_action_key_by_index(cid, 0)
            return (-prio_rank.get(prio, 0), 0 if deadline else 1, -ts, key)
        return [oto().make_action_key_by_index(cid, 0) for cid, _ in sorted(spec.items(), key=sort_key)]

    def build(self, spec):
        threads, st = {}, {}
        for cid, (prio, deadline, ts) in spec.items():
            threads[cid] = make_thread([make_action(deadline=deadline)], latest_ts=ts)
            if prio is not None:
                st[self.key(cid, 0)] = make_status("not_started", prio)
        return threads, st

    def test_order_priority_then_deadline_then_newest_then_key(self):
        spec = {
            "T1": ("", "5/10", ts_ago(10)),
            "T2": ("high", "", ts_ago(1)),
            "T3": ("top", "", ts_ago(50)),
            "T4": ("", "", ts_ago(2)),
            "T5": ("", "5/12", ts_ago(100)),
            "T6": ("high", "5/1", ts_ago(30)),
            "T7": ("", "", ts_ago(2)),            # T4 と同じ ts → key 昇順で決まる
            "T8": ("bogus", "", ts_ago(3)),       # 未知の優先度は 0 扱い
            "T9": ("top", "5/3", ts_ago(500)),
            "T10": ("high", "", ts_ago(1)),       # T2 と同条件 → key 昇順
        }
        threads, st = self.build(spec)
        rows = self.compute(threads, st)
        self.assertEqual([r["key"] for r in rows], self.oracle(spec))

    def test_priority_rank_top_high_other(self):
        spec = {"A": ("", "", ts_ago(1)), "B": ("high", "", ts_ago(100)), "C": ("top", "", ts_ago(1000))}
        threads, st = self.build(spec)
        rows = self.compute(threads, st)
        self.assertEqual([r["cid"] for r in rows], ["C", "B", "A"])

    def test_deadline_present_comes_before_absent_within_same_priority(self):
        spec = {"NOD": ("", "", ts_ago(1)), "DL": ("", "来週", ts_ago(900))}
        threads, st = self.build(spec)
        self.assertEqual([r["cid"] for r in self.compute(threads, st)], ["DL", "NOD"])

    def test_newest_first_within_same_priority_and_deadline_presence(self):
        spec = {"OLD": ("", "", ts_ago(30)), "NEW": ("", "", ts_ago(1)), "MID": ("", "", ts_ago(10))}
        threads, st = self.build(spec)
        self.assertEqual([r["cid"] for r in self.compute(threads, st)], ["NEW", "MID", "OLD"])

    def test_ties_are_broken_by_key_ascending(self):
        acts = [make_action(deadline=""), make_action(deadline=""), make_action(deadline=""),
                make_action(deadline="")]
        rows = self.compute({"C1": make_thread(acts)})
        keys = [r["key"] for r in rows]
        self.assertEqual(len(keys), 4)
        self.assertEqual(keys, sorted(keys))

    def test_order_does_not_depend_on_cache_insertion_order(self):
        spec = {f"T{i}": (random.Random(i).choice(["", "high", "top"]),
                          random.Random(i + 100).choice(["", "5/1"]),
                          ts_ago(random.Random(i + 200).randint(1, 200))) for i in range(30)}
        threads, st = self.build(spec)
        expected = self.oracle(spec)
        for seed in (1, 2, 3):
            items = list(threads.items())
            random.Random(seed).shuffle(items)
            rows = self.compute(dict(items), st)
            self.assertEqual([r["key"] for r in rows], expected)


class TestComputePendingRobustness(ComputeBase):
    """壊れた入力でも例外を出さない (その要素を飛ばす)。"""

    def good_thread(self):
        return make_thread([make_action(action="承認をお願いします")])

    def test_broken_cache_data_gives_empty_list(self):
        for cache in (None, [], "x", 5, 1.5, True, {}, {"threads": None}, {"threads": []},
                      {"threads": "x"}, {"threads": 5}, {"other": 1}):
            with self.subTest(cache=cache):
                self.assertEqual(oto().compute_pending_decisions(cache, {}), [])

    def test_broken_action_statuses_are_treated_as_empty(self):
        cache = make_cache({"C1": self.good_thread()})
        for st in (None, [], "x", 5, True):
            with self.subTest(statuses=st):
                rows = oto().compute_pending_decisions(cache, st)
                self.assertEqual([r["cid"] for r in rows], ["C1"])

    def test_non_dict_status_entries_do_not_raise(self):
        cache = make_cache({"C1": self.good_thread()})
        k = self.key("C1", 0)
        for entry in (None, "done", [], 5, True, {}, {"progress": None}, {"progress": 5},
                      {"progress": ""}, {"priority": None}, {"comment": None}):
            with self.subTest(entry=entry):
                rows = oto().compute_pending_decisions(cache, {k: entry})
                self.assertIsInstance(rows, list)

    def test_status_entry_without_progress_counts_as_not_started(self):
        cache = make_cache({"C1": self.good_thread()})
        rows = oto().compute_pending_decisions(cache, {self.key("C1", 0): {"comment": "x"}})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["progress"], "not_started")

    def test_broken_thread_entries_are_skipped_good_one_survives(self):
        good = self.good_thread()
        meta_ok = make_thread()["meta"]
        threads = {
            "b1": "string", "b2": None, "b3": 123, "b4": [], "b5": True,
            "b6": {"data": None, "meta": meta_ok},
            "b7": {"data": "x", "meta": meta_ok},
            "b8": {"data": ["x"], "meta": meta_ok},
            "b9": {"data": {"actions": "notalist", "action_type": "承認・決裁"}, "meta": meta_ok},
            "b10": {"data": {"actions": {"a": 1}, "action_type": "承認・決裁"}, "meta": meta_ok},
            "b11": {"data": {"actions": None, "action_type": "承認・決裁"}, "meta": meta_ok},
            "b12": {"data": {"actions": [make_action()], "action_type": "承認・決裁"}, "meta": "notadict"},
            "b13": {"data": {"actions": [make_action()], "action_type": "承認・決裁"}, "meta": []},
            "b14": {"data": {"actions": [make_action()], "action_type": "承認・決裁"}},
            "good": good,
        }
        rows = oto().compute_pending_decisions({"threads": threads}, {})
        self.assertEqual([r["cid"] for r in rows], ["good"])

    def test_broken_action_elements_are_skipped_but_index_is_array_position(self):
        # 要素が dict でない → その要素を飛ばす。添字は配列上の位置 (enumerate) のまま
        acts = [None, "oops", 5, [], True, make_action(action="承認をお願いします")]
        rows = self.compute({"C1": make_thread(acts)})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["key"], self.key("C1", 5))

    def test_missing_action_keys_do_not_raise(self):
        # AIの出力はキー欠落があり得る (スキーマ上 actions の各キーは必須ではない)
        for a in ({}, {"action": "承認をお願いします"}, {"target": "あなた"}, {"owner": "x", "action": "承認"}):
            with self.subTest(action=a):
                rows = self.compute({"C1": make_thread([a])})
                self.assertIsInstance(rows, list)


class TestComputePendingPurity(ComputeBase):
    def test_inputs_are_not_mutated(self):
        threads = {"C1": make_thread([make_action(), make_action(action="")]),
                   "C2": make_thread(error=True), "C3": make_thread(meta=False)}
        cache = make_cache(threads)
        st = {self.key("C1", 0): make_status("in_progress", "high", "memo")}
        c0, s0 = copy.deepcopy(cache), copy.deepcopy(st)
        oto().compute_pending_decisions(cache, st, extra_aliases=("x y",), since_ts=ts_ago(48))
        self.assertEqual(cache, c0)
        self.assertEqual(st, s0)

    def test_result_is_deterministic(self):
        threads = {f"C{i}": make_thread(latest_ts=ts_ago(i)) for i in range(20)}
        a = self.compute(threads)
        b = self.compute(copy.deepcopy(threads))
        self.assertEqual(a, b)

    def test_rows_are_independent_copies(self):
        st = {self.key("C1", 0): make_status("in_progress", "high", "memo")}
        rows = self.compute({"C1": make_thread()}, st)
        rows[0]["comment"] = "CHANGED"
        rows[0]["progress"] = "done"
        self.assertEqual(st[self.key("C1", 0)]["comment"], "memo")
        self.assertEqual(st[self.key("C1", 0)]["progress"], "in_progress")


class TestSpecGapComputePending(ComputeBase):
    """仕様に明記が無く、既存の summarize_action_dashboard の流儀に合わせた自然な解釈。"""

    def test_empty_meta_dict_is_treated_as_no_meta(self):
        # 既存コードは `if not meta: continue` (空dictもスキップ)
        t = make_thread(meta={})
        self.assertEqual(self.compute({"C1": t}), [])

    def test_entry_id_empty_string_in_meta_falls_back_to_cached(self):
        t = make_thread(entry_id="", cached_entry_id="E-CACHED")
        rows = self.compute({"C1": t})
        self.assertEqual(rows[0]["entry_id"], "E-CACHED")

    def test_topic_falls_back_to_real_topic_when_ai_title_missing(self):
        t = make_thread(topic="", real_topic="実件名だけ")
        rows = self.compute({"C1": t})
        self.assertEqual(rows[0]["topic"], "実件名だけ")

    def test_importance_defaults_to_chu_when_missing(self):
        t = make_thread()
        del t["data"]["importance"]
        rows = self.compute({"C1": t})
        self.assertEqual(rows[0]["importance"], "中")

    def test_missing_target_and_deadline_become_empty_strings(self):
        a = {"owner": "Nakai", "action": "承認してください"}
        rows = self.compute({"C1": make_thread([a])})
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["target"])
        self.assertFalse(rows[0]["deadline"])

    def test_whitespace_only_deadline_counts_as_no_deadline(self):
        spec_threads = {
            "WS": make_thread([make_action(deadline="   ")], latest_ts=ts_ago(1)),
            "DL": make_thread([make_action(deadline="5/10")], latest_ts=ts_ago(100)),
        }
        rows = self.compute(spec_threads)
        self.assertEqual([r["cid"] for r in rows], ["DL", "WS"])

    def test_extra_aliases_none_is_accepted(self):
        rows = self.compute({"C1": make_thread()}, extra_aliases=None)
        self.assertEqual(len(rows), 1)

    def test_action_text_is_returned_unstripped_or_stripped_but_same_content(self):
        rows = self.compute({"C1": make_thread([make_action(action="  承認してください  ")])})
        self.assertEqual(rows[0]["action"].strip(), "承認してください")

    # ---- フィールド単位の型崩れ (仕様の「壊れた入力」の列挙外。例外を出さないことだけ確認) ----
    def test_action_fields_with_wrong_types_do_not_raise(self):
        base = make_action()
        variants = [
            {"action": None}, {"action": 123}, {"action": ["承認"]}, {"action": {"a": 1}},
            {"target": 123}, {"target": ["あなた"]}, {"target": {"a": 1}}, {"target": True},
            {"owner": None}, {"owner": 5}, {"owner": ["a"]}, {"deadline": None}, {"deadline": 5},
            {"deadline": ["x"]}, {"status": None}, {"status": 5},
        ]
        for patch in variants:
            a = dict(base)
            a.update(patch)
            with self.subTest(patch=patch):
                rows = self.compute({"C1": make_thread([a])})
                self.assertIsInstance(rows, list)

    def test_meta_field_with_wrong_types_does_not_raise(self):
        for bad in (None, "abc", "1700000000", [], {}, float("nan"), -1):
            t = make_thread()
            t["meta"]["latest_ts"] = bad
            for since in (None, ts_ago(48)):
                with self.subTest(latest_ts=bad, since=since):
                    rows = oto().compute_pending_decisions(make_cache({"C1": t}), {}, since_ts=since)
                    self.assertIsInstance(rows, list)

    def test_data_field_with_wrong_types_does_not_raise(self):
        for field in ("topic", "importance", "action_type"):
            for bad in (None, 5, ["x"], {"a": 1}):
                t = make_thread()
                t["data"][field] = bad
                with self.subTest(field=field, bad=bad):
                    rows = oto().compute_pending_decisions(make_cache({"C1": t}), {})
                    self.assertIsInstance(rows, list)

    def test_since_ts_with_meta_lacking_latest_ts_does_not_raise(self):
        t = make_thread()
        del t["meta"]["latest_ts"]
        rows = oto().compute_pending_decisions(make_cache({"C1": t}), {}, since_ts=ts_ago(24))
        self.assertIsInstance(rows, list)


class TestKeyCompatibilityWithExistingCards(ComputeBase):
    """GUIが書く action_key は、既存のHTMLダッシュボード(summarize_action_dashboard)が読む
    action_key と一致していなければ、完了/無視が反映されない。既存関数の出力と突き合わせる。"""

    def test_row_keys_and_status_match_existing_cards(self):
        mod = oto()
        threads = {
            "CA": make_thread([make_action(action=""), make_action(action="承認を", target="あなた")],
                              latest_ts=ts_ago(3)),
            "CB": make_thread([make_action(action="決裁を", owner="Suzuki")], latest_ts=ts_ago(5)),
            "CC": make_thread([make_action(action="判断を", owner="Tanaka")], latest_ts=ts_ago(7)),
        }
        legacy = mod.make_action_key("CC", "Tanaka", "判断を")
        st = {
            mod.make_action_key_by_index("CA", 1): make_status("in_progress", "high", "c1"),
            legacy: make_status("ignored", "top", "legacy"),
        }
        cache = make_cache(threads)
        with tempdir_cwd():
            write_json(CACHE_PATH, cache)
            write_json(os.path.join("json", "action_status.json"), st)
            summ = mod.MailSummarizer.__new__(mod.MailSummarizer)
            res = summ.summarize_action_dashboard({}, expand_from_cache=True)
        card_actions = {}
        for card in res["action_cards"]:
            for a in card["actions"]:
                card_actions[a["action_key"]] = a
        rows = oto().compute_pending_decisions(cache, st)
        # 旧キーのCCは ignored として引き継がれるため判断待ちに出ない
        self.assertEqual(sorted(r["cid"] for r in rows), ["CA", "CB"])
        for r in rows:
            self.assertIn(r["key"], card_actions, "既存カードの action_key と一致しない")
            card = card_actions[r["key"]]
            self.assertEqual(r["progress"], card["progress"])
            self.assertEqual(r["priority"], card["priority"])
            self.assertEqual(r["comment"], card["comment"])
            self.assertEqual(r["action"], card["action"])
        # 既存カード側でも CC は ignored として扱われている (引継ぎの前提確認)
        cc = [a for a in card_actions.values() if a["action"] == "判断を"][0]
        self.assertEqual(cc["progress"], "ignored")


# ============================================================
# 7. count_recent_error_threads
# ============================================================
class TestCountRecentErrorThreads(unittest.TestCase):
    def count(self, threads, since):
        return oto().count_recent_error_threads(make_cache(threads), since)

    def test_counts_only_recent_error_threads_with_meta(self):
        since = ts_ago(48)
        threads = {
            "E1": make_thread(error=True, latest_ts=ts_ago(1)),
            "E2": make_thread(error=True, latest_ts=ts_ago(30)),
            "OLD": make_thread(error=True, latest_ts=ts_ago(500)),
            "OK": make_thread(error=False, latest_ts=ts_ago(1)),
            "NOMETA": make_thread(error=True, meta=False),
        }
        n = self.count(threads, since)
        self.assertEqual(n, 2)
        self.assertIsInstance(n, int)
        self.assertNotIsInstance(n, bool)

    def test_since_boundary_is_inclusive(self):
        since = ts_ago(48)
        threads = {"AT": make_thread(error=True, latest_ts=since),
                   "BEFORE": make_thread(error=True, latest_ts=since - 1)}
        self.assertEqual(self.count(threads, since), 1)

    def test_error_flag_truthiness(self):
        since = ts_ago(48)
        for flag, want in ((True, 1), (1, 1), ("yes", 1), (False, 0), (0, 0), (None, 0), ("", 0)):
            t = make_thread(latest_ts=ts_ago(1))
            t["data"]["_error"] = flag
            with self.subTest(flag=flag):
                self.assertEqual(self.count({"C1": t}, since), want)

    def test_missing_error_key_is_not_error(self):
        t = make_thread(latest_ts=ts_ago(1))
        self.assertNotIn("_error", t["data"])
        self.assertEqual(self.count({"C1": t}, ts_ago(48)), 0)

    def test_meta_missing_variants_are_not_counted(self):
        since = ts_ago(48)
        for meta in (False, {}, None):
            t = make_thread(error=True, meta=meta if meta is not None else False)
            if meta is None:
                t["meta"] = None
            with self.subTest(meta=meta):
                self.assertEqual(self.count({"C1": t}, since), 0)

    def test_empty_and_broken_inputs_give_zero(self):
        since = ts_ago(48)
        self.assertEqual(oto().count_recent_error_threads({"threads": {}}, since), 0)
        for cache in (None, [], "x", 5, {}, {"threads": None}, {"threads": []}, {"threads": "x"}):
            with self.subTest(cache=cache):
                self.assertEqual(oto().count_recent_error_threads(cache, since), 0)

    def test_broken_thread_entries_are_skipped(self):
        since = ts_ago(48)
        meta_ok = make_thread()["meta"]
        threads = {
            "b1": "s", "b2": None, "b3": 5, "b4": [],
            "b5": {"data": None, "meta": meta_ok}, "b6": {"data": "x", "meta": meta_ok},
            "b7": {"data": {"_error": True}, "meta": "x"}, "b8": {"data": {"_error": True}, "meta": []},
            "good": make_thread(error=True, latest_ts=ts_ago(1)),
        }
        self.assertEqual(oto().count_recent_error_threads({"threads": threads}, since), 1)

    def test_inputs_are_not_mutated(self):
        cache = make_cache({"E1": make_thread(error=True)})
        before = copy.deepcopy(cache)
        oto().count_recent_error_threads(cache, ts_ago(48))
        self.assertEqual(cache, before)

    def test_float_since_ts(self):
        base = ts_ago(10)
        threads = {"A": make_thread(error=True, latest_ts=base),
                   "B": make_thread(error=True, latest_ts=base + 1)}
        self.assertEqual(self.count(threads, base + 0.5), 1)


class TestSpecGapCountRecentErrorThreads(unittest.TestCase):
    def test_non_numeric_latest_ts_does_not_raise_and_is_not_counted(self):
        # フィールド単位の型崩れ (仕様の「壊れた入力」の列挙外)。数えない/例外を出さないのが自然
        threads = {
            "b9": {"data": {"_error": True}, "meta": {"latest_ts": None}},
            "b10": {"data": {"_error": True}, "meta": {"latest_ts": "abc"}},
            "good": make_thread(error=True, latest_ts=ts_ago(1)),
        }
        self.assertEqual(oto().count_recent_error_threads({"threads": threads}, ts_ago(48)), 1)

    def test_since_ts_none_counts_all_error_threads_with_meta(self):
        # compute_pending_decisions と同様に None は「期間で絞らない」が自然 (仕様は since_ts 必須の書き方)
        cache = make_cache({"A": make_thread(error=True, latest_ts=ts_ago(1)),
                            "B": make_thread(error=True, latest_ts=ts_ago(24 * 400)),
                            "C": make_thread(error=True, meta=False)})
        self.assertEqual(oto().count_recent_error_threads(cache, None), 2)


# ============================================================
# 10. format_decision_age
# ============================================================
class TestFormatDecisionAge(unittest.TestCase):
    def a(self, **kw):
        return oto().format_decision_age(timedelta(**kw))

    def test_negative_and_under_one_hour(self):
        for kw in (dict(), dict(seconds=-1), dict(days=-3), dict(hours=-100), dict(seconds=1),
                   dict(minutes=1), dict(minutes=59), dict(minutes=59, seconds=59),
                   dict(microseconds=3599999999), dict(milliseconds=3599999)):
            with self.subTest(kw=kw):
                self.assertEqual(self.a(**kw), "1時間以内")

    def test_hours_are_truncated(self):
        for kw, want in ((dict(hours=1), "1時間前"), (dict(hours=1, minutes=59, seconds=59), "1時間前"),
                         (dict(hours=2), "2時間前"), (dict(hours=2, minutes=30), "2時間前"),
                         (dict(hours=12), "12時間前"), (dict(hours=23), "23時間前"),
                         (dict(hours=23, minutes=59, seconds=59), "23時間前"),
                         (dict(hours=23, minutes=59, seconds=59, microseconds=999999), "23時間前")):
            with self.subTest(kw=kw):
                self.assertEqual(self.a(**kw), want)

    def test_days_are_truncated(self):
        for kw, want in ((dict(hours=24), "1日前"), (dict(days=1), "1日前"),
                         (dict(days=1, seconds=1), "1日前"), (dict(hours=47, minutes=59), "1日前"),
                         (dict(hours=48), "2日前"), (dict(days=3, hours=23), "3日前"),
                         (dict(days=7), "7日前"), (dict(days=365), "365日前")):
            with self.subTest(kw=kw):
                self.assertEqual(self.a(**kw), want)

    def test_returns_str(self):
        for kw in (dict(), dict(hours=5), dict(days=5), dict(days=-1)):
            self.assertIsInstance(self.a(**kw), str)


# ============================================================
# 11. build_decision_heading
# ============================================================
# 仕様変更(第2回):
#   fresh : {base} (判断待ち{n}{+}・解析{age}{・範囲のみ}{・解析失敗E件})
#   '+'   : 解析失敗が1件以上、または最終解析の範囲が7日未満 (last_run["days"] が 1〜6、または 0=24H→1日扱い)
#   範囲のみ: 範囲が7日未満のとき `・{period_label}のみ` (period_label が空なら `{日数}日のみ`)
#   順序  : 件数 → 解析経過 → 範囲のみ → 解析失敗
#   stale / unknown / 読込失敗 の文言は不変: (判断待ち?・要更新) / (判断待ち?・読込失敗)
#   時計ずれ: finished_at が now より 300秒(5分)を超えて未来 → unknown (要更新)。0〜300秒の未来は age=0
class TestBuildDecisionHeading(unittest.TestCase):
    def h(self, pending, last_run, errors=0, now=NOW, base=BASE):
        return oto().build_decision_heading(base, pending, last_run, errors, now)

    def lr(self, rng=7, label="1週間", **delta):
        """rng = 最終解析の範囲(last_run["days"])、delta = 最終解析から now までの経過 (timedelta の引数)"""
        return make_last_run(NOW - timedelta(**delta), days=rng, label=label)

    def test_fresh_heading_format(self):
        self.assertEqual(self.h(3, self.lr(hours=2)), f"{BASE} (判断待ち3・解析2時間前)")
        self.assertEqual(self.h(0, self.lr(hours=5, minutes=30)), f"{BASE} (判断待ち0・解析5時間前)")
        self.assertEqual(self.h(12, self.lr(minutes=30)), f"{BASE} (判断待ち12・解析1時間以内)")
        self.assertEqual(self.h(1, self.lr(seconds=0)), f"{BASE} (判断待ち1・解析1時間以内)")
        self.assertEqual(self.h(1, self.lr(hours=23, minutes=59, seconds=59)),
                         f"{BASE} (判断待ち1・解析23時間前)")

    def test_no_plus_when_range_is_7_days_or_more_and_no_errors(self):
        for days, label in ((7, "1週間"), (8, "8日"), (14, "2週間"), (21, "3週間"), (30, "1ヶ月"), (180, "6ヶ月")):
            with self.subTest(days=days):
                self.assertEqual(self.h(3, self.lr(rng=days, label=label, hours=2)),
                                 f"{BASE} (判断待ち3・解析2時間前)")

    def test_plus_and_range_only_when_range_under_7_days(self):
        for days, label in ((0, "24H"), (1, "今日"), (2, "2日"), (3, "3日間"), (6, "6日")):
            with self.subTest(days=days):
                self.assertEqual(self.h(3, self.lr(rng=days, label=label, hours=2)),
                                 f"{BASE} (判断待ち3+・解析2時間前・{label}のみ)")

    def test_spec_example_24h(self):
        # 仕様の例: (判断待ち0+・解析1時間以内・24Hのみ)
        self.assertEqual(self.h(0, self.lr(rng=0, label="24H", minutes=30)),
                         f"{BASE} (判断待ち0+・解析1時間以内・24Hのみ)")

    def test_range_only_label_falls_back_to_days_when_period_label_is_empty(self):
        # period_label が空なら `{日数}日のみ`
        self.assertEqual(self.h(3, self.lr(rng=3, label="", hours=2)), f"{BASE} (判断待ち3+・解析2時間前・3日のみ)")
        self.assertEqual(self.h(3, self.lr(rng=6, label="", hours=2)), f"{BASE} (判断待ち3+・解析2時間前・6日のみ)")
        self.assertEqual(self.h(3, self.lr(rng=1, label="", hours=2)), f"{BASE} (判断待ち3+・解析2時間前・1日のみ)")

    def test_pending_zero_is_not_confused_with_unknown(self):
        h = self.h(0, self.lr(hours=1))
        self.assertIn("判断待ち0", h)
        self.assertNotIn("?", h)

    def test_no_last_run_is_stale_unknown(self):
        self.assertEqual(self.h(3, None), f"{BASE} (判断待ち?・要更新)")

    def test_stale_boundary_exactly_24h_is_stale(self):
        stale = f"{BASE} (判断待ち?・要更新)"
        self.assertEqual(self.h(3, self.lr(hours=24)), stale)
        self.assertEqual(self.h(3, self.lr(hours=24, seconds=1)), stale)
        self.assertEqual(self.h(3, self.lr(hours=25)), stale)
        self.assertEqual(self.h(3, self.lr(days=7)), stale)
        self.assertNotEqual(self.h(3, self.lr(hours=23, minutes=59, seconds=59)), stale)

    def test_stale_and_unknown_ignore_pending_count_errors_and_range(self):
        stale = f"{BASE} (判断待ち?・要更新)"
        self.assertEqual(self.h(0, self.lr(hours=30), errors=5), stale)
        self.assertEqual(self.h(7, None, errors=5), stale)
        self.assertEqual(self.h(7, self.lr(rng=1, label="今日", hours=30), errors=5), stale)

    def test_cache_unreadable_when_fresh(self):
        self.assertEqual(self.h(None, self.lr(hours=2)), f"{BASE} (判断待ち?・読込失敗)")
        self.assertEqual(self.h(None, self.lr(hours=2), errors=3), f"{BASE} (判断待ち?・読込失敗)")
        self.assertEqual(self.h(None, self.lr(rng=1, label="今日", hours=2), errors=3),
                         f"{BASE} (判断待ち?・読込失敗)")

    def test_error_count_suffix_and_plus(self):
        h = self.h(3, self.lr(hours=2), errors=2)
        self.assertEqual(h, f"{BASE} (判断待ち3+・解析2時間前・解析失敗2件)")      # 仕様の例
        self.assertEqual(h.count("解析失敗"), 1)
        self.assertEqual(self.h(3, self.lr(hours=2), errors=0), f"{BASE} (判断待ち3・解析2時間前)")
        self.assertEqual(self.h(3, self.lr(hours=2), errors=1), f"{BASE} (判断待ち3+・解析2時間前・解析失敗1件)")
        self.assertEqual(self.h(0, self.lr(hours=2), errors=15), f"{BASE} (判断待ち0+・解析2時間前・解析失敗15件)")

    def test_order_count_age_range_errors_and_single_plus(self):
        h = self.h(3, self.lr(rng=3, label="3日間", hours=2), errors=2)
        self.assertEqual(h, f"{BASE} (判断待ち3+・解析2時間前・3日間のみ・解析失敗2件)")
        self.assertEqual(h.count("+"), 1)

    def test_future_finished_at_within_5_minutes_is_age_zero(self):
        for kw in (dict(seconds=-1), dict(minutes=-1), dict(minutes=-4, seconds=-59), dict(minutes=-5)):
            with self.subTest(delta=kw):
                self.assertEqual(self.h(2, self.lr(**kw)), f"{BASE} (判断待ち2・解析1時間以内)")

    def test_future_finished_at_over_5_minutes_is_unknown(self):
        unknown = f"{BASE} (判断待ち?・要更新)"
        for kw in (dict(minutes=-5, seconds=-1), dict(minutes=-6), dict(minutes=-10), dict(hours=-1),
                   dict(days=-3)):
            with self.subTest(delta=kw):
                self.assertEqual(self.h(2, self.lr(**kw)), unknown)

    def test_clock_skew_boundary_uses_the_constant(self):
        skew = const("ACTION_DECISION_CLOCK_SKEW_SECONDS")
        fresh = self.h(2, make_last_run(NOW + timedelta(seconds=skew)))
        unknown = self.h(2, make_last_run(NOW + timedelta(seconds=skew + 1)))
        self.assertEqual(fresh, f"{BASE} (判断待ち2・解析1時間以内)")
        self.assertEqual(unknown, f"{BASE} (判断待ち?・要更新)")

    def test_base_text_is_used_verbatim(self):
        self.assertEqual(self.h(3, self.lr(hours=2), base="X"), "X (判断待ち3・解析2時間前)")
        self.assertEqual(self.h(3, None, base="X"), "X (判断待ち?・要更新)")
        self.assertEqual(self.h(None, self.lr(hours=2), base="X"), "X (判断待ち?・読込失敗)")

    def test_returns_str(self):
        self.assertIsInstance(self.h(1, self.lr(hours=1)), str)

    def test_uses_given_now_not_wall_clock(self):
        last = make_last_run(datetime(2020, 1, 1, 0, 0, 0))
        far = datetime(2020, 1, 1, 3, 0, 0)
        self.assertEqual(oto().build_decision_heading(BASE, 4, last, 0, far), f"{BASE} (判断待ち4・解析3時間前)")


class TestSpecGapBuildDecisionHeading(unittest.TestCase):
    def h(self, pending, last_run, errors=0, now=NOW):
        return oto().build_decision_heading(BASE, pending, last_run, errors, now)

    def test_rule_order_no_record_wins_over_cache_failure(self):
        # 仕様の列挙順: ①last_run無し ②24h以上/時計ずれ ③pending=None ④fresh。
        # last_run無し かつ pending=None のとき「要更新」「読込失敗」どちらかは未記載 → 列挙順どおり「要更新」
        self.assertEqual(self.h(None, None), f"{BASE} (判断待ち?・要更新)")

    def test_rule_order_stale_wins_over_cache_failure(self):
        last = make_last_run(NOW - timedelta(hours=30))
        self.assertEqual(self.h(None, last), f"{BASE} (判断待ち?・要更新)")

    def test_rule_order_clock_skew_wins_over_cache_failure(self):
        last = make_last_run(NOW + timedelta(hours=1))
        self.assertEqual(self.h(None, last), f"{BASE} (判断待ち?・要更新)")

    def test_unparseable_finished_at_is_stale_and_does_not_raise(self):
        for bad in ({"finished_at": "garbage"}, {"finished_at": ""}, {"finished_at": None}, {}):
            with self.subTest(last_run=bad):
                self.assertEqual(self.h(3, bad), f"{BASE} (判断待ち?・要更新)")

    def test_timezone_aware_finished_at_does_not_raise(self):
        # 手編集で "+09:00" 付きになった場合: naive との引き算で TypeError にならないこと
        last = {"finished_at": "2026-10-04T10:00:00+09:00", "days": 7, "period_label": "1週間"}
        self.assertIsInstance(self.h(3, last), str)

    def test_error_count_none_is_zero(self):
        last = make_last_run(NOW - timedelta(hours=2))
        self.assertEqual(self.h(3, last, errors=None), f"{BASE} (判断待ち3・解析2時間前)")

    def test_range_only_label_for_zero_days_with_empty_label_says_one_day(self):
        # 「0=24H→1日扱い」: period_label が空のとき「{日数}日のみ」の日数も 1日扱いが自然 (「0日のみ」にしない)
        last = make_last_run(NOW - timedelta(hours=2), days=0, label="")
        self.assertEqual(self.h(3, last), f"{BASE} (判断待ち3+・解析2時間前・1日のみ)")

    def test_negative_days_is_treated_like_a_one_day_range(self):
        # snapshot の window_days は「days>0 ? days : 1」。0 や負は1日扱い → 7日未満 → '+' と「のみ」
        last = make_last_run(NOW - timedelta(hours=2), days=-1, label="謎")
        self.assertEqual(self.h(3, last), f"{BASE} (判断待ち3+・解析2時間前・謎のみ)")

    def test_missing_or_wrong_typed_days_and_label_do_not_raise(self):
        for patch in ({"days": None}, {"days": "abc"}, {"days": [3]}, {"period_label": None}, {"period_label": 5}):
            last = make_last_run(NOW - timedelta(hours=2))
            last.update(patch)
            with self.subTest(patch=patch):
                self.assertIsInstance(self.h(3, last), str)
        last = make_last_run(NOW - timedelta(hours=2))
        del last["days"]
        self.assertIsInstance(self.h(3, last), str)


# ============================================================
# build_decision_heading_compact (仕様変更(第2回) 8)
# ============================================================
# stale/unknown → `{base} ⚖?` / 読込失敗 → `{base} ⚖!` / fresh → `{base} ⚖{n}`
# (解析失敗あり、または範囲が7日未満なら末尾に `+`)
class TestBuildDecisionHeadingCompact(unittest.TestCase):
    def c(self, pending, last_run, errors=0, now=NOW, base=BASE):
        return oto().build_decision_heading_compact(base, pending, last_run, errors, now)

    def lr(self, rng=7, label="1週間", **delta):
        """rng = 最終解析の範囲(last_run["days"])、delta = 最終解析から now までの経過 (timedelta の引数)"""
        return make_last_run(NOW - timedelta(**delta), days=rng, label=label)

    def test_fresh(self):
        self.assertEqual(self.c(3, self.lr(hours=2)), f"{BASE} ⚖3")
        self.assertEqual(self.c(0, self.lr(hours=2)), f"{BASE} ⚖0")
        self.assertEqual(self.c(12, self.lr(minutes=10)), f"{BASE} ⚖12")
        self.assertEqual(self.c(1, self.lr(hours=23, minutes=59, seconds=59)), f"{BASE} ⚖1")

    def test_plus_for_errors(self):
        self.assertEqual(self.c(3, self.lr(hours=2), errors=2), f"{BASE} ⚖3+")
        self.assertEqual(self.c(0, self.lr(hours=2), errors=1), f"{BASE} ⚖0+")
        self.assertEqual(self.c(3, self.lr(hours=2), errors=0), f"{BASE} ⚖3")

    def test_plus_for_range_under_7_days(self):
        for days in (0, 1, 3, 6):
            with self.subTest(days=days):
                self.assertEqual(self.c(3, self.lr(rng=days, label="x", hours=2)), f"{BASE} ⚖3+")
        for days in (7, 14, 30):
            with self.subTest(days=days):
                self.assertEqual(self.c(3, self.lr(rng=days, label="x", hours=2)), f"{BASE} ⚖3")

    def test_single_plus_when_both_conditions(self):
        self.assertEqual(self.c(3, self.lr(rng=3, label="3日間", hours=2), errors=4), f"{BASE} ⚖3+")

    def test_stale_and_unknown(self):
        unknown = f"{BASE} ⚖?"
        self.assertEqual(self.c(3, None), unknown)
        self.assertEqual(self.c(3, self.lr(hours=24)), unknown)
        self.assertEqual(self.c(3, self.lr(hours=24, seconds=1)), unknown)
        self.assertEqual(self.c(3, self.lr(days=5)), unknown)
        self.assertEqual(self.c(3, self.lr(hours=30), errors=2), unknown)
        self.assertNotEqual(self.c(3, self.lr(hours=23, minutes=59, seconds=59)), unknown)

    def test_cache_read_failure(self):
        self.assertEqual(self.c(None, self.lr(hours=2)), f"{BASE} ⚖!")
        self.assertEqual(self.c(None, self.lr(hours=2), errors=3), f"{BASE} ⚖!")
        self.assertEqual(self.c(None, self.lr(rng=1, label="今日", hours=2)), f"{BASE} ⚖!")

    def test_rule_order_unknown_before_failure(self):
        # 通常の見出しと同じ判定順: 記録なし/stale/時計ずれ が 読込失敗 より先
        self.assertEqual(self.c(None, None), f"{BASE} ⚖?")
        self.assertEqual(self.c(None, self.lr(hours=30)), f"{BASE} ⚖?")
        self.assertEqual(self.c(None, make_last_run(NOW + timedelta(hours=1))), f"{BASE} ⚖?")

    def test_clock_skew(self):
        self.assertEqual(self.c(2, make_last_run(NOW + timedelta(seconds=300))), f"{BASE} ⚖2")
        self.assertEqual(self.c(2, make_last_run(NOW + timedelta(seconds=301))), f"{BASE} ⚖?")
        self.assertEqual(self.c(2, make_last_run(NOW + timedelta(minutes=4))), f"{BASE} ⚖2")
        self.assertEqual(self.c(2, make_last_run(NOW + timedelta(days=3))), f"{BASE} ⚖?")

    def test_base_text_is_used_verbatim(self):
        self.assertEqual(self.c(3, self.lr(hours=2), base="X"), "X ⚖3")
        self.assertEqual(self.c(3, None, base="X"), "X ⚖?")
        self.assertEqual(self.c(None, self.lr(hours=2), base="X"), "X ⚖!")

    def test_is_shorter_than_the_full_heading(self):
        mod = oto()
        for pending, last, errors in ((3, self.lr(hours=2), 2), (0, self.lr(rng=3, label="3日間", hours=2), 1),
                                      (None, self.lr(hours=2), 0), (3, None, 0)):
            full = mod.build_decision_heading(BASE, pending, last, errors, NOW)
            compact = mod.build_decision_heading_compact(BASE, pending, last, errors, NOW)
            self.assertLess(len(compact), len(full), (full, compact))
            self.assertTrue(compact.startswith(BASE))

    def test_returns_str_and_does_not_raise_on_broken_last_run(self):
        for bad in ({"finished_at": "garbage"}, {"finished_at": None}, {}, {"finished_at": 5}):
            with self.subTest(last_run=bad):
                self.assertIsInstance(self.c(3, bad), str)
        self.assertEqual(self.c(3, {"finished_at": "garbage"}), f"{BASE} ⚖?")
        self.assertEqual(self.c(3, make_last_run(NOW - timedelta(hours=2)), errors=None), f"{BASE} ⚖3")


# ============================================================
# 既存コード不変ガード (仕様「変えないもの」)
# ============================================================
# 仕様上 A1 で変更してよい既存の関数/メソッド:
#   - MailManagerGUI.__init__ (tick起動・タブ変更バインド等)
#   - MailManagerGUI._ui_action_tab (判断待ちパネルの追加)
#   - MailManagerGUI._run_action_dashboard (last_run保存・finallyで再読込)
# これら以外の既存の関数・メソッド・モジュール定数が変わっていたら「ついでに直した」疑い。
ALLOWED_TO_CHANGE = {
    "MailManagerGUI.__init__", "MailManagerGUI._ui_action_tab", "MailManagerGUI._run_action_dashboard",
}


def _index_source(path):
    """関数/メソッド・定数・import を AST ダンプ (行番号・コメント・空白は無視) で索引化する。"""
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src)
    funcs, consts, imports = {}, {}, set()
    dump = ast.dump
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs[node.name] = dump(node)
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    funcs[f"{node.name}.{sub.name}"] = dump(sub)
                elif isinstance(sub, (ast.Assign, ast.AnnAssign)):
                    targets = sub.targets if isinstance(sub, ast.Assign) else [sub.target]
                    for t in targets:
                        if isinstance(t, ast.Name):
                            consts[f"{node.name}.{t.id}"] = dump(sub)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name):
                    consts[t.id] = dump(node)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.add(dump(node))
    return funcs, consts, imports


class TestScopeGuardExistingCodeUnchanged(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # A1の「既存コードは変更しない」宣誓は、A1のリビジョン対(20260821_02 → 20261004_01)に対して検証する。
        # (後続のリビジョン[A2以降]は、それぞれのテストで自分の変更範囲を検証する)
        cls.target = _loader.rev_path("outlook_total_organizer_20261004_01.py")
        cls.baseline = _loader.rev_path("outlook_total_organizer_20260821_02.py")
        if not (os.path.isfile(cls.target) and os.path.isfile(cls.baseline)):
            raise unittest.SkipTest("A1のリビジョン対(20260821_02 / 20261004_01)が無い")
        cls.old = _index_source(cls.baseline)
        cls.new = _index_source(cls.target)

    def test_existing_functions_and_methods_are_unchanged(self):
        old_funcs, new_funcs = self.old[0], self.new[0]
        removed = sorted(n for n in old_funcs if n not in new_funcs)
        changed = sorted(n for n, s in old_funcs.items()
                         if n in new_funcs and new_funcs[n] != s and n not in ALLOWED_TO_CHANGE)
        self.assertEqual(removed, [], f"既存の関数/メソッドが消えている: {removed}")
        self.assertEqual(changed, [], f"仕様で許可されていない既存関数/メソッドの変更: {changed}")

    def test_existing_module_and_class_constants_are_unchanged(self):
        old_c, new_c = self.old[1], self.new[1]
        removed = sorted(n for n in old_c if n not in new_c)
        changed = sorted(n for n, s in old_c.items() if n in new_c and new_c[n] != s)
        self.assertEqual(removed, [], f"既存の定数が消えている: {removed}")
        self.assertEqual(changed, [], f"既存の定数が変更されている: {changed}")

    def test_existing_imports_are_kept(self):
        missing = self.old[2] - self.new[2]
        self.assertEqual(len(missing), 0, f"既存の import が {len(missing)} 件消えている")

    def test_allowed_to_change_functions_still_exist(self):
        for n in sorted(ALLOWED_TO_CHANGE):
            self.assertIn(n, self.new[0])


# ローカルタイムゾーンを JST(+9) / EST(-5) にして、再浮上の updated_at 判定を再実行する
_loader.make_tz_variants(globals(), [TestComputePendingResurfacing])


if __name__ == "__main__":
    unittest.main(verbosity=2)
