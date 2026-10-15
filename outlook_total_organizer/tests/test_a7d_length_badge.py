# -*- coding: utf-8 -*-
"""A7d「文字数超過の検出バッジ」テスト (仕様書 A7D_SPEC.md。レビュー第1回の変更: バッジの文字は「字数超過」)。

仕様書だけを根拠に、A7d の実装 (_20261004_11.py の変更部分) を見ずに書いている
(レポートへの入力の形は、変更前の _10 と既存テストに合わせた)。
  - 仕様に明記された挙動            -> 通常の TestCase
  - 仕様が曖昧/未記載で「最も自然な解釈」で書いたもの -> クラス名に SpecGap を含む

構成
  1. 定数・シグネチャ
  2. display_char_count (NFC・改行を数えない・前後の空白を数えない・None/数値/str()の失敗)
  3. over_length_badge_html (上限ちょうどは "" / 超えたらバッジ・ログ1行 / print が失敗しても例外を出さない)
  4. 各レポート (偽の入力で本物の HTMLReportGenerator に HTML を書かせる):
     プロジェクト俯瞰・スタッフ俯瞰 (Stage2 の text・100字)・統括コックピット v1 (text・100字・auto_filled は除外・
     エスケープ前で数える)・振り返り (summary・320字・手動追加は除外・.rv-chips の先頭・.rv-summary には入れない)。
     reformat_mode=True でも同じ。アクション一覧・統括コックピット v2 にはバッジが付かない。
  5. 範囲ガード (_10 と _11 をファイル名で指定して AST 比較。後のリビジョンが増えても変わらない)

変異テスト: 実装のコピーに誤りを1つ入れ、OTO_TARGET でその版を指してこのファイルだけを走らせる。
    OTO_TARGET=/path/to/壊した版.py xvfb-run -a /usr/bin/python3.12 tests/run_tests.py a7d_length_badge
(範囲ガードの章は常に tool フォルダの _10 / _11 を比べるので、変異版では変わらない)
(A10 = _12 で俯瞰2画面の text は HTML エスケープされるようになった。「A7d は text の埋め込み方を変えていない」ことは、
 _10 / _11 をファイル名で指定して確かめる。対象のリビジョンでは、エスケープ前の文で数えることだけを確かめる)
"""
import ast
import contextlib
import copy
import difflib
import functools
import html as html_mod
import inspect
import io
import os
import random
import re
import sys
import unicodedata
import unittest
from datetime import datetime
from html.parser import HTMLParser
from unittest import mock

import _loader
from _loader import tempdir_cwd


def oto():
    return _loader.load()


ONE_LINE = 100
EXEC = 320
BADGE_STYLE = ("display:inline-block;margin-left:4px;padding:0 6px;border-radius:8px;font-size:0.75em;line-height:1.5;"
               "background:#fef3c7;color:#92400e;border:1px solid #f59e0b;vertical-align:middle;")
BADGE_OPEN = '<span class="len-over-badge"'
BADGE_LABEL = "字数超過"
WARN = "⚠️"                     # ⚠️ (U+26A0 U+FE0F)


def ref_badge(n, limit):
    """仕様の文字列そのもの。"""
    return (f' <span class="len-over-badge" title="AIの文が{n}字です（目安は{limit}字以内）" style="{BADGE_STYLE}">'
            f'{BADGE_LABEL}</span>')


def ref_count(text):
    """仕様の定義そのまま (参照実装): NFC → 改行 (\\r \\n) を除く → strip() → len()。"""
    s = "" if text is None else str(text)
    s = unicodedata.normalize("NFC", s).replace("\r", "").replace("\n", "")
    return len(s.strip())


FILLER = "あいうえおかきくけこさしすせそたちつてとなにぬねの"


def text_of(n, tag):
    """先頭に識別用の tag を付けた、ちょうど n 字 (NFC・改行なし・前後の空白なし) の文。"""
    s = tag
    while len(s) < n:
        s += FILLER
    s = s[:n]
    assert ref_count(s) == n and s.startswith(tag)
    return s


class BadStr:
    def __str__(self):
        raise ValueError("str() に失敗するオブジェクト")


class NotStr:
    def __str__(self):
        return 12345                       # str() が TypeError になる


# ============================================================
# HTML の読み取り (標準ライブラリの HTMLParser で小さな木を作る)
# ============================================================
class Node:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.children = tag, dict(attrs), parent, []

    @property
    def classes(self):
        return (self.attrs.get("class") or "").split()

    def text(self):
        return "".join(c if isinstance(c, str) else c.text() for c in self.children)

    def elements(self):
        return [c for c in self.children if isinstance(c, Node)]

    def iter(self):
        yield self
        for c in self.children:
            if isinstance(c, Node):
                yield from c.iter()

    def ancestors(self):
        p = self.parent
        while p is not None:
            yield p
            p = p.parent


_VOID = frozenset("area base br col embed hr img input link meta param source track wbr".split())


class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", (), None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.cur)
        self.cur.children.append(node)
        if tag not in _VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(Node(tag, attrs, self.cur))

    def handle_endtag(self, tag):
        n = self.cur
        while n is not None and n.tag != tag:
            n = n.parent
        if n is not None and n.parent is not None:
            self.cur = n.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def parse_html(text):
    b = _TreeBuilder()
    b.feed(text)
    b.close()
    return b.root


def is_badge(node):
    return isinstance(node, Node) and node.tag == "span" and "len-over-badge" in node.classes


# ============================================================
# 1. 定数・シグネチャ
# ============================================================
class TestConstantsAndSignatures(unittest.TestCase):
    def test_constants(self):
        """ONE_LINE_SUMMARY_MAX_CHARS = 100、EXECUTIVE_SUMMARY_DETECT_CHARS = 320 (モジュール直下)。"""
        self.assertEqual(oto().ONE_LINE_SUMMARY_MAX_CHARS, 100)
        self.assertEqual(oto().EXECUTIVE_SUMMARY_DETECT_CHARS, 320)

    def test_signatures(self):
        """display_char_count(text) / over_length_badge_html(text, limit)。"""
        self.assertEqual(list(inspect.signature(oto().display_char_count).parameters), ["text"])
        self.assertEqual(list(inspect.signature(oto().over_length_badge_html).parameters), ["text", "limit"])


# ============================================================
# 2. display_char_count
# ============================================================
class TestDisplayCharCount(unittest.TestCase):
    def f(self, x):
        return oto().display_char_count(x)

    def check(self, cases):
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(self.f(value), expected)

    def test_plain_text(self):
        """ふつうの文は len() どおり。"""
        self.check((("abc", 3), ("あいう", 3), ("", 0), ("日本語の文です。", 8), ("Q&A <b>", 7)))

    def test_nfc_normalization(self):
        """NFC 正規化後の字数: 結合文字の「か」+「゛」→1字、e+◌́→1字、NFD の「がぎぐげご」→5字、ハングル字母→1字。
        NFKC ではない: 半角の「ｶﾞ」は2字のまま・合字「ﬁ」・「㍿」は1字。"""
        self.check((("が", 1), ("é", 1), (unicodedata.normalize("NFD", "がぎぐげご"), 5),
                    ("가", 1), ("ｶﾞ", 2), ("ﬁ", 1), ("㍿", 1)))

    def test_newlines_are_not_counted(self):
        """改行 (\\r\\n・\\n・\\r) は、どこにあっても数えない。"""
        self.check((("あ\r\nい", 2), ("あ\nい", 2), ("あ\rい", 2), ("\r\n\nあい\r\r\n", 2), ("\n\n", 0),
                    ("あ\r\n" * 5, 5), ("\r", 0)))

    def test_leading_and_trailing_whitespace_is_not_counted(self):
        """前後の空白 (半角・タブ・全角・NBSP) は数えない。"""
        self.check((("  あい  ", 2), ("\tあい\t", 2), ("　あい　", 2), ("\xa0あい\xa0", 2),
                    (" \r\n あい \n ", 2), ("   ", 0), ("　", 0)))

    def test_inner_whitespace_is_counted(self):
        """中の空白は数える (改行の両側の空白も、改行を除いた後は「中の空白」)。"""
        self.check((("あ い", 3), ("あ\tい", 3), ("あ　い", 3), ("あ  い", 4), ("あ \n い", 4), ("a b c", 5)))

    def test_none_is_zero(self):
        """None → 0。"""
        self.assertEqual(self.f(None), 0)

    def test_numbers_and_other_objects_use_str(self):
        """数値などは str() した字数 (0 も "0" で1字)。"""
        self.check(((12345, 5), (0, 1), (3.5, 3), (-7, 2), (["あ"], 5)))

    def test_str_failure_gives_zero_without_raising(self):
        """str() が失敗するオブジェクト (__str__ が例外 / 文字列以外を返す) は 0。例外を出さない。"""
        for obj in (BadStr(), NotStr()):
            with self.subTest(obj=type(obj).__name__):
                self.assertEqual(self.f(obj), 0)

    def test_always_returns_int(self):
        for v in ("あ", "", None, 5, BadStr(), "が\r\n"):
            with self.subTest(value=v):
                self.assertIs(type(self.f(v)), int)

    def test_matches_the_reference_on_random_texts(self):
        """ランダムな文 (結合文字・改行・各種空白・記号の混在) で、仕様どおりの参照実装と一致する。"""
        units = ["あ", "が", "é", "A", "&", "<", " ", "　", "\t", "\r", "\n", "\r\n", "ｶ", "ﾞ", "ﬁ",
                 "\xa0", "。"]
        rng = random.Random(20261004)
        for _ in range(400):
            s = "".join(rng.choice(units) for _ in range(rng.randint(0, 30)))
            self.assertEqual(self.f(s), ref_count(s), repr(s))


# ============================================================
# 3. over_length_badge_html
# ============================================================
class TestOverLengthBadge(unittest.TestCase):
    def b(self, text, limit):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            r = oto().over_length_badge_html(text, limit)
        return r, out.getvalue()

    def test_exactly_at_the_limit_gives_nothing(self):
        """上限ちょうど (100字 / 320字) は "" でログも無し。"""
        for limit in (ONE_LINE, EXEC):
            with self.subTest(limit=limit):
                self.assertEqual(self.b(text_of(limit, "〔L〕"), limit), ("", ""))

    def test_one_over_the_limit_gives_the_exact_badge(self):
        """上限+1字 (101字 / 321字) は、仕様どおりのバッジの文字列 (先頭に半角スペース1つ・本文「字数超過」)。"""
        for limit in (ONE_LINE, EXEC):
            with self.subTest(limit=limit):
                r, _ = self.b(text_of(limit + 1, "〔L〕"), limit)
                self.assertEqual(r, ref_badge(limit + 1, limit))

    def test_badge_structure(self):
        """バッジの形: 先頭は半角スペース1つ、span.len-over-badge、title に字数と目安、本文は「字数超過」。"""
        r, _ = self.b(text_of(150, "〔S〕"), ONE_LINE)
        self.assertTrue(r.startswith(" <span ") and not r.startswith("  "), repr(r[:20]))
        root = parse_html(r)
        self.assertEqual(root.children[0], " ")
        spans = root.elements()
        self.assertEqual(len(spans), 1)
        self.assertTrue(is_badge(spans[0]))
        self.assertEqual(spans[0].attrs.get("title"), "AIの文が150字です（目安は100字以内）")
        self.assertEqual(spans[0].text(), BADGE_LABEL)

    def test_newlines_and_outer_whitespace_do_not_push_over(self):
        """100字＋改行・改行入りの100字・前後に空白のある100字は ""。"""
        t = text_of(100, "〔N〕")
        for v in (t + "\n", t + "\r\n", "\r\n" + t, t[:50] + "\r\n" + t[50:], t[:50] + "\n" + t[50:] + "\n\n",
                  t[:30] + "\r" + t[30:], "  " + t + "  ", "　" + t + "\t\n"):
            with self.subTest(value=v[-6:]):
                self.assertEqual(self.b(v, ONE_LINE), ("", ""))
        e = text_of(320, "〔E〕")
        self.assertEqual(self.b(e[:100] + "\r\n" + e[100:200] + "\n" + e[200:] + "\n", EXEC), ("", ""))

    def test_nfd_text_is_counted_after_nfc(self):
        """NFD の「が」×100 (200コードポイント) は100字なので ""。×101 は101字のバッジ。"""
        self.assertEqual(self.b(unicodedata.normalize("NFD", "が" * 100), ONE_LINE), ("", ""))
        r, _ = self.b(unicodedata.normalize("NFD", "が" * 101), ONE_LINE)
        self.assertEqual(r, ref_badge(101, ONE_LINE))

    def test_inner_spaces_count(self):
        """中の空白は数える: 99字の中に空白1つ → 100字 ("")、2つ → 101字 (バッジ)。"""
        t = text_of(99, "〔I〕")
        self.assertEqual(self.b(t[:40] + " " + t[40:], ONE_LINE), ("", ""))
        r, _ = self.b(t[:40] + " 　" + t[40:], ONE_LINE)
        self.assertEqual(r, ref_badge(101, ONE_LINE))

    def test_none_empty_and_unprintable_objects_give_nothing(self):
        """None・空・str() が失敗するオブジェクトは "" (例外を出さない)。"""
        for v in (None, "", "   \r\n", BadStr(), NotStr()):
            with self.subTest(value=type(v).__name__):
                self.assertEqual(self.b(v, ONE_LINE), ("", ""))

    def test_log_line(self):
        """超えたらログを1行: 「⚠️ 文字数超過: {n}字（目安{limit}字以内）: {先頭30字}…」。"""
        _, log = self.b("あ" * 101, ONE_LINE)
        self.assertEqual(log, f"{WARN} 文字数超過: 101字（目安100字以内）: {'あ' * 30}…\n")
        _, log = self.b("い" * 321, EXEC)
        self.assertEqual(log, f"{WARN} 文字数超過: 321字（目安320字以内）: {'い' * 30}…\n")

    def test_log_head_is_taken_after_normalization_and_newline_removal(self):
        """ログの先頭30字は、NFC 正規化・改行除去後の文字列から取る (改行の多い文でもログは1行)。"""
        t = unicodedata.normalize("NFD", "が\r\n" * 101)
        _, log = self.b(t, ONE_LINE)
        self.assertEqual(log, f"{WARN} 文字数超過: 101字（目安100字以内）: {'が' * 30}…\n")
        self.assertEqual(log.count("\n"), 1)

    def test_log_has_no_ellipsis_for_30_chars_or_less(self):
        """正規化・改行除去後が30字以下ならそのまま (「…」なし)。31字なら先頭30字＋「…」。"""
        cases = (("う" * 12, f"{WARN} 文字数超過: 12字（目安10字以内）: {'う' * 12}\n"),
                 ("え" * 30, f"{WARN} 文字数超過: 30字（目安10字以内）: {'え' * 30}\n"),
                 ("え" * 30 + "\n", f"{WARN} 文字数超過: 30字（目安10字以内）: {'え' * 30}\n"),
                 ("お" * 31, f"{WARN} 文字数超過: 31字（目安10字以内）: {'お' * 30}…\n"))
        for text, expected in cases:
            with self.subTest(text=text):
                r, log = self.b(text, 10)
                self.assertEqual(log, expected)
                self.assertEqual(r, ref_badge(ref_count(text), 10))

    def test_print_failure_does_not_raise(self):
        """print が例外を出しても (Windows の cp932 コンソールで ⚠️ が書けない等) 例外を出さず、バッジは返す。"""
        mod = oto()

        def boom(*a, **k):
            raise UnicodeEncodeError("cp932", "⚠", 0, 1, "illegal multibyte sequence")
        with mock.patch.object(mod, "print", boom, create=True):
            self.assertEqual(mod.over_length_badge_html(text_of(101, "〔P〕"), ONE_LINE), ref_badge(101, ONE_LINE))

    def test_broken_stdout_does_not_raise(self):
        """標準出力への書き込みが失敗しても例外を出さず、バッジは返す。"""
        class BrokenStream:
            encoding = "cp932"

            def write(self, s):
                raise OSError("書き込めない")

            def flush(self):
                raise OSError("書き込めない")

        with mock.patch.object(sys, "stdout", BrokenStream()):
            r = oto().over_length_badge_html(text_of(101, "〔Q〕"), ONE_LINE)
        self.assertEqual(r, ref_badge(101, ONE_LINE))


# ============================================================
# 4. 各レポート (偽の入力で本物の HTMLReportGenerator に HTML を書かせる)
# ============================================================
class ReportCase(unittest.TestCase):
    def setUp(self):
        cm = tempdir_cwd()
        self.tmp = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        self.gen = oto().HTMLReportGenerator(os.path.join(self.tmp, "out"), 8765)
        out = io.StringIO()                                   # レポート生成の [DEBUG] 表示・超過ログを黙らせる
        cm2 = contextlib.redirect_stdout(out)
        cm2.__enter__()
        self.addCleanup(cm2.__exit__, None, None, None)

    def read(self, path, label):
        self.assertTrue(path, f"{label}: HTML が出力されなかった (空のパスが返った)")
        with open(path, "r", encoding="utf-8", newline="") as f:     # 改行コードを変えずに読む (\r\n を保つ)
            return f.read()

    def assert_badge_follows(self, segment, text, n, limit, cite):
        """segment (li などの中身) で、text の直後に (半角スペース1つで) バッジがあり、その後ろが根拠リンク (cite=True) か終わり。"""
        i = segment.find(text)
        self.assertGreaterEqual(i, 0, f"文がそのままの形で見つからない: {text[:24]!r}")
        rest = segment[i + len(text):]
        self.assertTrue(rest.startswith(" " + BADGE_OPEN), f"文の直後 (半角スペース1つ) にバッジが無い: {rest[:100]!r}")
        self.assertEqual(segment.count(BADGE_OPEN), 1, "バッジが1つでない")
        end = rest.find("</span>") + len("</span>")
        badge, after = rest[:end], rest[end:]
        self.assertIn(f'title="AIの文が{n}字です（目安は{limit}字以内）"', badge)
        self.assertTrue(badge.endswith(f">{BADGE_LABEL}</span>"), badge)
        if cite:
            self.assertTrue(after.startswith(" <a ") and 'class="cite-badge"' in after.split("</a>")[0],
                            f"バッジの直後が根拠リンク (cite-badge) でない: {after[:100]!r}")
        else:
            self.assertEqual(after.strip(), "", f"バッジの後ろに想定外の内容: {after[:100]!r}")

    def assert_no_badge_after(self, segment, text):
        """segment にバッジが無く、text の直後は根拠リンクか終わり (空の要素なども足されていない)。"""
        self.assertNotIn(BADGE_OPEN, segment)
        self.assertNotIn(BADGE_LABEL, segment)
        i = segment.find(text)
        self.assertGreaterEqual(i, 0, f"文がそのままの形で見つからない: {text[:24]!r}")
        rest = segment[i + len(text):]
        self.assertTrue(rest.startswith(" <a ") or rest.strip() == "", f"文の直後に想定外の内容: {rest[:100]!r}")


def s2_item(text, sids=("T1",), **kw):
    """俯瞰の Stage2 の1項目 (ensure_struct 後の形)。"""
    d = {"category": "プロジェクト管理", "project_scope": "横断業務", "action_type": "通知・共有", "text": text,
         "status_icon": "🔵", "source_thread_ids": list(sids)}
    d.update(kw)
    return d


def overview_summary(manager=(), status=(), stalled=(), threads=()):
    return {"manager_actions": list(manager), "staff_status": list(status), "stalled_monitor": list(stalled),
            "updated_history": "", "ai_questions": [], "threads": list(threads)}


def summary_lis(html):
    return re.findall(r'<li class="js-summary-item">(.*?)</li>', html, re.S)


def one_with(test, segments, tag):
    found = [s for s in segments if tag in s]
    test.assertEqual(len(found), 1, f"{tag} を含む項目が {len(found)} 個ある")
    return found[0]


@functools.lru_cache(maxsize=None)
def load_revision(filename):
    """tool フォルダのリビジョンをファイル名で指定して、別名のモジュールとして読み込む (無ければ None)。"""
    path = _loader.rev_path(filename)
    if not os.path.isfile(path):
        return None
    oto()                                                  # 先に最小スタブを入れておく
    name = "oto_rev_" + os.path.splitext(filename)[0].replace("outlook_total_organizer_", "")
    if name in sys.modules:
        return sys.modules[name]
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        with tempdir_cwd(), contextlib.redirect_stdout(io.StringIO()):
            spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return mod


BADGE_HTML_RE = re.compile(r' <span class="len-over-badge"[^>]*>' + BADGE_LABEL + '</span>')


class TestOverviewReports(ReportCase):
    """プロジェクト俯瞰・スタッフ俯瞰: Stage2 の text が101字以上ならその li にバッジ (根拠リンクの前)。100字までは無し。"""

    KINDS = ("project", "staff")

    def render(self, kind, data, name="Caracal", knowledge=None, orig=None, reformat=False, mod=None):
        sec = "projects" if kind == "project" else "staffs"
        knowledge = knowledge if knowledge is not None else {sec: {name: {}}}
        gen = self.gen if mod is None else mod.HTMLReportGenerator(os.path.join(self.tmp, "out"), 8765)
        fn = gen.generate_project_report if kind == "project" else gen.generate_staff_report
        path = fn(name, {name: data}, orig or {}, knowledge, "2026/09/27 - 2026/10/04", "重要度順", 1000, 500,
                  "adopted", reformat)
        return self.read(path, kind)

    def data(self):
        return overview_summary(
            manager=[s2_item(text_of(101, "〔M101〕"), ["T1"]), s2_item(text_of(100, "〔M100〕"), ["T1"])],
            status=[s2_item(text_of(101, "〔S101〕"), ["T1", "T2"]), s2_item(text_of(100, "〔S100〕") + "\n", ["T2"])],
            stalled=[s2_item(text_of(140, "〔K140〕"), []), s2_item(text_of(99, "〔K099〕"), ["T1"])])

    def test_badges_only_on_items_over_100_chars(self):
        """101字・140字の li にだけバッジ (101字/140字の title)。100字・100字+改行・99字は無し。reformat_mode でも同じ。"""
        for kind in self.KINDS:
            for reformat in (False, True):
                with self.subTest(kind=kind, reformat=reformat):
                    html = self.render(kind, self.data(), reformat=reformat)
                    lis = summary_lis(html)
                    for tag, n, cite in (("〔M101〕", 101, True), ("〔S101〕", 101, True), ("〔K140〕", 140, False)):
                        self.assert_badge_follows(one_with(self, lis, tag), text_of(n, tag), n, ONE_LINE, cite)
                    for tag, text in (("〔M100〕", text_of(100, "〔M100〕")), ("〔S100〕", text_of(100, "〔S100〕") + "\n"),
                                      ("〔K099〕", text_of(99, "〔K099〕"))):
                        self.assert_no_badge_after(one_with(self, lis, tag), text)
                    self.assertEqual(html.count(BADGE_OPEN), 3, "バッジの数が超過した項目の数 (3) と違う")

    def test_text_is_still_embedded_without_escaping_and_counted_raw(self):
        """A7d (_10 → _11) は Stage2 の text の埋め込み方を変えていない: _11 (ファイル名で指定) は HTML エスケープせずに埋め込み、
        その直後にバッジ。_10 の li は、_11 の li からバッジを除いたものと同じ。数えるのも元の文字列。
        (A10 = _12 から text は HTML エスケープして埋め込む。対象のリビジョンでは、埋め込まれた形 (そのまま/エスケープ後) を
        問わず、& や < を含む100字には付かず、101字には文の直後にバッジが付くことを確かめる)"""
        t100 = text_of(100, "〔R&D <b>x</b>〕")
        t101 = text_of(101, "〔Q&A <i>y</i>〕")
        data = overview_summary(manager=[s2_item(t100, ["T1"]), s2_item(t101, ["T1"])])
        for kind in self.KINDS:
            with self.subTest(kind=kind, rev="対象"):
                lis = summary_lis(self.render(kind, copy.deepcopy(data)))
                f100, f101 = [html_mod.escape(t) if any(html_mod.escape(t) in s for s in lis) else t for t in (t100, t101)]
                self.assert_no_badge_after(one_with(self, lis, f100), f100)
                self.assert_badge_follows(one_with(self, lis, f101), f101, 101, ONE_LINE, True)
        old_mod, new_mod = load_revision(OLD_REV), load_revision(NEW_REV)
        if old_mod is None or new_mod is None:
            self.skipTest(f"A7d のリビジョン対 ({OLD_REV} / {NEW_REV}) が無い (対象のリビジョンでの数え方は確認済み)")
        for kind in self.KINDS:
            with self.subTest(kind=kind, rev=NEW_REV):
                lis = summary_lis(self.render(kind, copy.deepcopy(data), mod=new_mod))
                seg100, seg101 = one_with(self, lis, "〔R&D <b>x</b>〕"), one_with(self, lis, "〔Q&A <i>y</i>〕")
                self.assert_no_badge_after(seg100, t100)
                self.assert_badge_follows(seg101, t101, 101, ONE_LINE, True)
            with self.subTest(kind=kind, rev=OLD_REV):
                old_lis = summary_lis(self.render(kind, copy.deepcopy(data), mod=old_mod))
                self.assertEqual(old_lis, [seg100, BADGE_HTML_RE.sub("", seg101)], "_10 と _11 で text の埋め込み方が違う")

    def test_other_long_texts_get_no_badge(self):
        """題名 (topic)・Stage1 の要約・アクション・経緯・回答メモ・AI質問は対象外 (長くてもバッジなし)。"""
        long = "長い文章です。" * 60
        for kind in self.KINDS:
            with self.subTest(kind=kind):
                name = "Caracal"
                sec = "projects" if kind == "project" else "staffs"
                mail = {"body": long, "html_body": "", "entry_id": "E1", "subject": "件名", "conversation_topic": "件名",
                        "sender_name": "Saji", "received": "2026-10-01 09:00"}
                orig = {name: {"T1": {"latest_date": datetime(2026, 10, 1, 9, 0), "latest_entry_id": "E1",
                                      "topic": "件名", "mails": [mail]}}}
                thread = {"thread_id": "T1", "topic": long, "summary": long, "is_target": True, "importance": "高",
                          "category": "その他", "project_scope": "横断業務", "action_type": "通知・共有",
                          "actions": [{"owner": "Saji", "action": long, "status": "未定"}]}
                data = overview_summary(manager=[s2_item(text_of(100, "〔OK〕"), ["T1"])], threads=[thread])
                data["ai_questions"] = [long]
                knowledge = {sec: {name: {"master_history": long, "history_summary": long, "human_answers": long,
                                          "role": long, "background": long}}}
                html = self.render(kind, data, name=name, knowledge=knowledge, orig=orig)
                self.assertIn(long, html, "前提: 長い文が HTML に出ていない")
                self.assertNotIn(BADGE_OPEN, html)
                self.assertNotIn(BADGE_LABEL, html)


ROLE_KEYS = ("site_manager_view", "r19_pm_view", "pm_manager_view", "te_pe_view")


def role_item(text, sids=("T1",), **kw):
    d = {"category": "状況把握", "text": text, "source_thread_ids": list(sids)}
    d.update(kw)
    return d


def cockpit_data(**roles):
    data = {k: {"red_alerts": [], "blue_highlights": [], "yellow_stalled": []} for k in ROLE_KEYS}
    for k, v in roles.items():
        data[k].update(v)
    return data


def cockpit_lis(html):
    return re.findall(r'<li style="margin-bottom:8px; line-height:1.4;">(.*?)</li>', html, re.S)


class TestCockpitV1Report(ReportCase):
    """統括コックピット v1: text が101字以上ならバッジ (根拠リンクの前)。auto_filled が真なら付けない。エスケープ前で数える。"""

    def render(self, data, reformat=False, cache=None):
        return self.read(self.gen.generate_cockpit_report(data, cache or {}, 1000, 500, reformat), "cockpit")

    def test_badge_unless_auto_filled(self):
        """101字・150字はバッジ。auto_filled が真 (True・1) なら付かない。偽 (False・0) なら付く。reformat_mode でも同じ。"""
        data = cockpit_data(
            site_manager_view={
                "red_alerts": [role_item(text_of(101, "〔C101〕"), ["T1"]), role_item(text_of(100, "〔C100〕"), ["T2"])],
                "blue_highlights": [role_item(text_of(101, "〔A101〕"), ["T3"], auto_filled=True),
                                    role_item(text_of(150, "〔A150〕"), ["T4"], auto_filled=1)],
                "yellow_stalled": [role_item(text_of(101, "〔F101〕"), ["T5"], auto_filled=False),
                                   role_item(text_of(120, "〔Z120〕"), ["T6"], auto_filled=0),
                                   role_item(text_of(101, "〔N101〕"), [])]},
            te_pe_view={"red_alerts": [role_item(text_of(101, "〔E101〕"), ["T7"], duplicate_thread=True)]})
        for reformat in (False, True):
            with self.subTest(reformat=reformat):
                html = self.render(data, reformat)
                lis = cockpit_lis(html)
                for tag, n, cite in (("〔C101〕", 101, True), ("〔F101〕", 101, True), ("〔Z120〕", 120, True),
                                     ("〔N101〕", 101, False), ("〔E101〕", 101, True)):
                    self.assert_badge_follows(one_with(self, lis, tag), text_of(n, tag), n, ONE_LINE, cite)
                for tag, n in (("〔C100〕", 100), ("〔A101〕", 101), ("〔A150〕", 150)):
                    self.assert_no_badge_after(one_with(self, lis, tag), text_of(n, tag))
                self.assertIn("🧩", one_with(self, lis, "〔A101〕"), "前提: auto_filled の印 (🧩) が無い")
                self.assertEqual(html.count(BADGE_OPEN), 5, "バッジの数が対象の項目の数 (5) と違う")

    def test_counted_before_escaping(self):
        """エスケープ前の値で数える: & や < を含む100字は付かない (エスケープ後は100字を超える)。101字は付く。"""
        t100 = text_of(100, "〔R&D<1>〕")
        t098 = text_of(98, "〔\"<>&'〕")
        t101 = text_of(101, "〔Q&A〕")
        data = cockpit_data(site_manager_view={"red_alerts": [role_item(t100, ["T1"]), role_item(t098, ["T2"]),
                                                              role_item(t101, ["T3"])]})
        lis = cockpit_lis(self.render(data))
        self.assert_no_badge_after(one_with(self, lis, html_mod.escape("〔R&D<1>〕")), html_mod.escape(t100))
        self.assert_no_badge_after(one_with(self, lis, html_mod.escape("〔\"<>&'〕")), html_mod.escape(t098))
        self.assert_badge_follows(one_with(self, lis, "〔Q&amp;A〕"), html_mod.escape(t101), 101, ONE_LINE, True)

    def test_other_long_texts_get_no_badge(self):
        """根拠スレッド一覧の要約・題名は対象外 (長くてもバッジなし)。"""
        long = "長い要約の文章です。" * 50
        data = cockpit_data(site_manager_view={"red_alerts": [role_item(text_of(100, "〔OK〕"), ["T1"])]})
        data["thread_data_map"] = {"Saji_T1": {"data": {"topic": long, "summary": long}, "target_name": "Saji",
                                               "source_file": "staff_Saji.json", "latest_entry_id": "E1"}}
        html = self.render(data)
        self.assertIn(html_mod.escape(long), html, "前提: 長い文が HTML に出ていない")
        self.assertNotIn(BADGE_OPEN, html)
        self.assertNotIn(BADGE_LABEL, html)


def achievement(aid, summary, *, person="Ochi", is_manual=False, rank="A", **kw):
    """振り返りの実績1件 (summarize_review_month が作る形)。"""
    d = {"achievement_id": aid, "title": f"実績{aid}", "summary": summary, "source_thread_ids": [f"conv-{aid}"],
         "is_confirmed": True, "activity_type": "decision", "goal_keys": ["G1_project"], "project_key": "Japan_Site",
         "has_quantitative_effect": False, "quantitative_note": "", "site_wide": False, "completed_date": "2026-09-15",
         "year_month": "202609", "person": person, "tier1": [], "tier2": [], "staff_involved": [],
         "staff_involved_labels": [], "g2_subcategory": None, "g2_subcategory_label": "", "rank": rank,
         "rank_label": rank, "type_label": "判断・決裁", "project_label": "Japan Site", "matched_meetings": [],
         "year_month_label": "2026年9月", "is_manual": is_manual, "thread_entry_id": None, "thread_topic": ""}
    if is_manual:
        d["source_thread_ids"] = []
    d.update(kw)
    return d


class TestReviewReport(ReportCase):
    """振り返り: summary が321字以上ならバッジ (.rv-chips の先頭)。320字までは無し。手動追加は付けない。.rv-summary には入れない。"""

    def render(self, items, person="Ochi", reformat=False):
        data = {"achievements": items, "generated_at": "2026-10-04 12:00"}
        return self.read(self.gen.generate_review_report(data, "2026年Q3", 1000, 500, reformat, person), "review")

    def rows(self, html):
        root = parse_html(html)
        out = {}
        for n in root.iter():
            if n.tag == "div" and "rv-row" in n.classes:
                out.setdefault(n.attrs.get("data-aid"), []).append(n)
        return root, out

    def parts(self, row):
        summ = [n for n in row.iter() if "rv-summary" in n.classes]
        chips = [n for n in row.iter() if "rv-chips" in n.classes]
        self.assertEqual((len(summ), len(chips)), (1, 1), "行に .rv-summary / .rv-chips が1つずつ無い")
        return summ[0], chips[0]

    def check_rows(self, html, items, over):
        """over: {aid: 字数} (バッジが付くもの)。それ以外の行にはバッジが無い。.rv-summary の中身は元の summary のまま。"""
        root, rows = self.rows(html)
        total = 0
        for a in items:
            aid = a["achievement_id"]
            self.assertTrue(rows.get(aid), f"{aid} の行が無い")
            for row in rows[aid]:
                summ, chips = self.parts(row)
                self.assertEqual(summ.text(), a["summary"], f"{aid}: .rv-summary の文字が変わった (コピー用の文字列に影響)")
                self.assertEqual(summ.elements(), [], f"{aid}: .rv-summary の中に要素が入った")
                self.assertNotIn("超過", summ.text())
                badges = [n for n in row.iter() if is_badge(n)]
                if aid in over:
                    self.assertEqual(len(badges), 1, f"{aid}: バッジが1つでない")
                    self.assertIs(chips.elements()[0], badges[0], f"{aid}: バッジが .rv-chips の先頭に無い")
                    self.assertEqual(badges[0].text(), BADGE_LABEL)
                    self.assertEqual(badges[0].attrs.get("title"), f"AIの文が{over[aid]}字です（目安は320字以内）")
                    total += 1
                else:
                    self.assertEqual(badges, [], f"{aid}: バッジが付いている")
        all_badges = [n for n in root.iter() if is_badge(n)]
        self.assertEqual(len(all_badges), total, "行の .rv-chips 以外にもバッジがある")
        for bdg in all_badges:
            self.assertTrue(any("rv-chips" in p.classes for p in bdg.ancestors()))
        return rows

    def test_badge_on_ai_items_over_320_chars(self):
        """321字・500字 (AIの実績) はバッジ。320字・320字+改行・手動追加の321字は無し。reformat_mode でも同じ。"""
        items = [achievement("a321", text_of(321, "〔R321〕")), achievement("a320", text_of(320, "〔R320〕")),
                 achievement("m321", text_of(321, "〔M321〕"), is_manual=True),
                 achievement("n320", text_of(320, "〔N320〕") + "\r\n"),
                 achievement("e500", text_of(500, "〔E500〕"), rank="S")]
        for reformat in (False, True):
            with self.subTest(reformat=reformat):
                self.check_rows(self.render(items, reformat=reformat), items, {"a321": 321, "e500": 500})

    def test_badge_comes_before_the_person_chip(self):
        """スタッフの実績 (人物チップが付く) でも、バッジは .rv-chips の先頭 (人物チップより前)。"""
        items = [achievement("s321", text_of(321, "〔P321〕"), person="Saji", goal_keys=["K1"]),
                 achievement("s100", text_of(100, "〔P100〕"), person="Saji", goal_keys=["K1"])]
        rows = self.check_rows(self.render(items, person="Saji"), items, {"s321": 321})
        for row in rows["s321"]:
            _, chips = self.parts(row)
            self.assertIn("rv-c-person", chips.elements()[1].classes, "バッジの次が人物チップでない")

    def test_counted_before_escaping(self):
        """エスケープ前の summary で数える: & < > を含む320字は付かない。321字は付く。.rv-summary は元の文字のまま。"""
        items = [achievement("x320", text_of(320, "〔R&D <x>〕")), achievement("x321", text_of(321, "〔Q&A〕"))]
        self.check_rows(self.render(items), items, {"x321": 321})


class TestReportsWithoutLengthRule(ReportCase):
    """アクション一覧・統括コックピット v2 は対象外 (長い文でもバッジなし)。"""

    LONG = "とても長いアクションの説明文です。" * 40

    def test_action_dashboard_has_no_badge(self):
        long = self.LONG
        card = {"conversation_id": "C1", "topic": long, "real_topic": "件名", "latest_date_mmdd": "10/04 09:00",
                "latest_ts": 1_790_000_000, "has_unread": False, "is_r19": False, "is_flagged": False,
                "importance": "高", "latest_entry_id": "E1", "summary": long,
                "actions": [{"action_key": "C1#0", "owner": "Saji", "target": "あなた", "action": long,
                             "deadline": "10/10", "progress": "not_started", "priority": "", "comment": long}]}
        for reformat in (False, True):
            with self.subTest(reformat=reformat):
                html = self.read(self.gen.generate_action_dashboard_report([card], "2026/09/27 - 2026/10/04", 1000, 500,
                                                                           reformat, 7), "action")
                self.assertIn(html_mod.escape(long), html, "前提: 長い文が HTML に出ていない")
                self.assertNotIn(BADGE_OPEN, html)
                self.assertNotIn(BADGE_LABEL, html)

    def test_cockpit_v2_has_no_badge(self):
        long = self.LONG
        data = {"projects": {"00_Caracal": {"is_anomaly": True, "priority": "高",
                                            "velocity": {"recent_count": 3, "trend": "↑"},
                                            "silence": {"is_stalled": False, "silence_days": 0},
                                            "waiting_on_me_count": 1, "waiting_on_them_count": 0}},
                "queue": [{"conversation_id": "C1", "topic": long, "real_topic": "件名", "project": "00_Caracal",
                           "category_key": "reminded", "latest_date_display": "10/04", "mail_count": 3,
                           "latest_entry_id": "E1", "reasons": [long, long], "other_projects": []}],
                "generated_at": "2026-10-04 12:00"}
        for reformat in (False, True):
            with self.subTest(reformat=reformat):
                html = self.read(self.gen.generate_cockpit_v2_report(data, 1000, 500, reformat), "cockpit_v2")
                self.assertIn(html_mod.escape(long), html, "前提: 長い文が HTML に出ていない")
                self.assertNotIn(BADGE_OPEN, html)
                self.assertNotIn(BADGE_LABEL, html)


# ============================================================
# 5. 範囲ガード (_10 → _11 で変えてよいのは4つのレポート生成メソッドの描画の1か所ずつと、定数2つ・関数2つの追加だけ)
# ============================================================
OLD_REV = "outlook_total_organizer_20261004_10.py"
NEW_REV = "outlook_total_organizer_20261004_11.py"
FOUR_REPORTS = {"generate_project_report": "ONE_LINE_SUMMARY_MAX_CHARS",
                "generate_staff_report": "ONE_LINE_SUMMARY_MAX_CHARS",
                "generate_cockpit_report": "ONE_LINE_SUMMARY_MAX_CHARS",
                "generate_review_report": "EXECUTIVE_SUMMARY_DETECT_CHARS"}
ALLOWED_TO_CHANGE = {f"HTMLReportGenerator.{n}" for n in FOUR_REPORTS}
NEW_CONSTANTS = {"ONE_LINE_SUMMARY_MAX_CHARS": 100, "EXECUTIVE_SUMMARY_DETECT_CHARS": 320}
NEW_FUNCTIONS = {"display_char_count", "over_length_badge_html"}
A7D_NAMES = frozenset(set(NEW_CONSTANTS) | NEW_FUNCTIONS)


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


def _is_docstring(node):
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)


def _index_source(path):
    """関数/メソッド・定数・import・その他のトップレベル文・クラスの骨格を AST ダンプで索引化する (行番号・コメントは無視)。"""
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


def _names(node):
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _badge_vars(fn):
    """A7d の名前を使った式を代入された変数 (len_badge など)。"""
    out = set()
    for n in ast.walk(fn):
        if isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None and _names(n.value) & A7D_NAMES:
            for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                out |= {x.id for x in ast.walk(t) if isinstance(x, ast.Name)}
    return out


def _drop_parts(values, names):
    """f-string の部品から、A7d の名前を使う {…} を取り除く (隣り合った固定文字列はつなぐ)。"""
    out = []
    for v in values:
        if isinstance(v, ast.FormattedValue) and _names(v) & names:
            continue
        if out and isinstance(v, ast.Constant) and isinstance(out[-1], ast.Constant):
            out[-1] = ast.Constant(out[-1].value + v.value)
            continue
        out.append(v)
    return out


_HEADERS = {ast.If: ("test",), ast.While: ("test",), ast.For: ("target", "iter"), ast.AsyncFor: ("target", "iter"),
            ast.With: ("items",), ast.AsyncWith: ("items",), ast.Try: (),
            ast.FunctionDef: ("args", "decorator_list", "returns"),
            ast.AsyncFunctionDef: ("args", "decorator_list", "returns"),
            ast.ClassDef: ("bases", "keywords", "decorator_list")}
if hasattr(ast, "TryStar"):
    _HEADERS[ast.TryStar] = ()


def _strip_stmts(stmts, names):
    """A7d の名前を使う文を取り除く。複合文は、見出し (if の条件など) が使っていなければ中身だけ処理し、
    中身が全部取り除かれた if などは文ごと取り除く。"""
    out = []
    for st in stmts:
        if type(st) in _HEADERS:
            heads = []
            for f in _HEADERS[type(st)]:
                v = getattr(st, f, None)
                heads += v if isinstance(v, list) else [v]
            if any(isinstance(h, ast.AST) and _names(h) & names for h in heads):
                continue
            had_body = bool(st.body)
            for f in ("body", "orelse", "finalbody"):
                lst = getattr(st, f, None)
                if isinstance(lst, list):
                    setattr(st, f, _strip_stmts(lst, names))
            for h in getattr(st, "handlers", None) or []:
                h.body = _strip_stmts(h.body, names)
            if had_body and not st.body and not getattr(st, "orelse", None):
                continue
            out.append(st)
        elif _names(st) & names:
            continue
        else:
            out.append(st)
    return out


def strip_a7d(fn):
    """A7d で足した部分 (バッジの {…}・len_badge などの文) を取り除いた関数の AST (比較用のコピー)。"""
    fn = copy.deepcopy(fn)
    names = A7D_NAMES | _badge_vars(fn)
    for n in ast.walk(fn):
        if isinstance(n, ast.JoinedStr):
            n.values = _drop_parts(n.values, names)
    fn.body = _strip_stmts(fn.body, names)
    return fn


def short_diff(a, b, limit=30):
    lines = list(difflib.unified_diff(a.splitlines(), b.splitlines(), "old", "new", lineterm="", n=1))
    return "\n".join(lines[:limit])


class TestScopeGuardA7d(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = _loader.rev_path(OLD_REV)
        cls.target = _loader.rev_path(NEW_REV)
        if not (os.path.isfile(cls.baseline) and os.path.isfile(cls.target)):
            raise unittest.SkipTest("A7d のリビジョン対 (20261004_10 / 20261004_11) が無い")
        cls.old = _index_source(cls.baseline)
        cls.new = _index_source(cls.target)

    def test_no_existing_function_is_removed(self):
        self.assertEqual(sorted(n for n in self.old[0] if n not in self.new[0]), [])

    def test_only_the_four_report_methods_changed(self):
        """変わった既存の関数は4つのレポート生成メソッドだけ (4つとも実際に変わっている)。"""
        old_f, new_f = self.old[0], self.new[0]
        changed = {n for n, s in old_f.items() if n in new_f and new_f[n] != s}
        self.assertEqual(sorted(changed - ALLOWED_TO_CHANGE), [], "許可されていない既存関数/メソッドの変更")
        self.assertEqual(sorted(ALLOWED_TO_CHANGE - changed), [], "A7d で変わるはずのメソッドが変わっていない")

    def test_only_two_functions_and_two_constants_are_added_before_the_report_class(self):
        """追加は関数2つ (display_char_count・over_length_badge_html)・定数2つ (100・320) だけ。どれもモジュール直下で、
        HTMLReportGenerator の定義より前。"""
        self.assertEqual({n for n in self.new[0] if n not in self.old[0]}, NEW_FUNCTIONS)
        self.assertEqual({n for n in self.new[1] if n not in self.old[1]}, set(NEW_CONSTANTS))
        body = _parse(self.target).body
        cls_line = [n.lineno for n in body if isinstance(n, ast.ClassDef) and n.name == "HTMLReportGenerator"][0]
        for node in body:
            names = ({node.name} if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else
                     {t.id for t in node.targets if isinstance(t, ast.Name)} if isinstance(node, ast.Assign) else set())
            for n in names & A7D_NAMES:
                with self.subTest(name=n):
                    self.assertLess(node.lineno, cls_line, f"{n} が HTMLReportGenerator の定義より後にある")
                    if n in NEW_CONSTANTS:
                        self.assertEqual(ast.literal_eval(node.value), NEW_CONSTANTS[n])

    def test_existing_constants_imports_and_other_statements_are_unchanged(self):
        old_c, new_c = self.old[1], self.new[1]
        self.assertEqual(sorted(n for n in old_c if n not in new_c), [], "既存の定数が消えている")
        self.assertEqual(sorted(n for n, s in old_c.items() if n in new_c and new_c[n] != s), [], "既存の定数が変わっている")
        self.assertEqual(self.old[2], self.new[2], "import が変わっている")
        self.assertEqual(self.old[3], self.new[3], "関数/定数/import 以外のトップレベル文が変わっている")
        self.assertEqual(self.old[4], self.new[4], "クラスの骨格 (継承・クラス直下の文) が変わっている")

    def test_each_report_changed_only_by_the_badge(self):
        """4つのメソッドは、バッジの部分 (f-string の {…}・len_badge などの文) を取り除くと _10 と同じ。
        それぞれ over_length_badge_html を仕様の定数 (100字は ONE_LINE_SUMMARY_MAX_CHARS、320字は
        EXECUTIVE_SUMMARY_DETECT_CHARS) で呼んでいる。"""
        for name, const in FOUR_REPORTS.items():
            with self.subTest(method=name):
                old_fn = method_node(self.baseline, "HTMLReportGenerator", name)
                new_fn = method_node(self.target, "HTMLReportGenerator", name)
                self.assertEqual(ast.dump(strip_a7d(old_fn)), ast.dump(old_fn), "前提: 比較元 (_10) に A7d の名前がある")
                calls = [c for c in ast.walk(new_fn) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                         and c.func.id == "over_length_badge_html"]
                self.assertTrue(calls, "over_length_badge_html を呼んでいない")
                for c in calls:
                    self.assertIn(const, {a.id for a in c.args if isinstance(a, ast.Name)}, ast.unparse(c))
                stripped = strip_a7d(new_fn)
                self.assertEqual(ast.dump(stripped), ast.dump(old_fn),
                                 "バッジ以外の変更がある\n" + short_diff(ast.unparse(old_fn), ast.unparse(stripped)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
