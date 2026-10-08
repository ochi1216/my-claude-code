# -*- coding: utf-8 -*-
"""A10「プロジェクト俯瞰・スタッフ俯瞰の HTML レポートで、メール・AI 由来の文字列をエスケープする」テスト
(仕様書 A10_SPEC.md。fix1 = 敵対的レビュー第1回の追補 B1・B2・M1 を含む)。

仕様書だけを根拠に書いている (レポートへの入力の形は、既存テスト test_a7d_length_badge.py と変更前の _11 に合わせた)。

構成
  1. report_text_html / report_js_str_html の表 (<script>・&・"・'・\\・改行・None・数値) と性質。
     JS の方は「HTML の属性値として読んだ後 (html.unescape)、JS の '…' 文字列として解釈すると元の値 (\\r を除く) に戻る」
     ことと、引用符で抜け出せないことを、小さな JS の字句解析器 (js_scan。ECMAScript の文字列リテラルの規則) で確かめる。
  2. 本物の generate_project_report / generate_staff_report で HTML を作り、html.parser で解析して比べる:
     悪意のある値 (要約の行・状態アイコン・件名・重要度・要約・アクションの担当/内容/状態・差出人名・受信日時・本文・根拠ID)
     で作った HTML は、通常の値で作った HTML と「タグ・属性の並びが同じ」(script 要素・onmouseover などが増えない)、
     表示の文字は元の値のまま、onclick などの JS は骨格が同じで、件名・根拠IDの引数は元の値 (\\r を除く) に戻る。
     reformat_mode=True でも同じ。通常の文 (特殊文字なし) は表示の文字が変わらない (_11 と _12 をファイル名で指定して、
     共通JS・iframe の sandbox 以外は HTML がバイト単位で同じ)。
  3. 字数超過バッジは、エスケープ前の文で数える (& などを含む100字には付かず、101字には文の直後に付く)。
  4. fix1: HTML 本文の iframe の sandbox (allow-scripts なし)。共通JS: escHtml・「📄 詳細」「✨ 要約」の結果・
     絞り込みボタン (data-v と this.dataset.v)。escHtml は node で、全体は Chromium (Playwright) で動かして確かめる
     (node・Playwright・Chromium が無い環境ではスキップ)。
  5. 範囲ガード (_11 と _12 をファイル名で指定して AST 比較。共通JS は行単位の差分。後のリビジョンが増えても変わらない)。

変異テスト: 実装のコピーに誤りを1つ入れ、OTO_TARGET でその版を指してこのファイルだけを走らせる。
    OTO_TARGET=/path/to/壊した版.py xvfb-run -a /usr/bin/python3.12 tests/run_tests.py a10_report_escape
(5. の範囲ガードと 2. の「_11 と _12 で同じ」は、常に tool フォルダの _11 / _12 を比べるので、変異版では変わらない)
"""
import ast
import contextlib
import copy
import difflib
import functools
import html as html_mod
import importlib.util
import inspect
import io
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from datetime import datetime
from html.parser import HTMLParser

import _loader
from _loader import tempdir_cwd

OLD_REV = "outlook_total_organizer_20261004_11.py"
NEW_REV = "outlook_total_organizer_20261004_12.py"
PORT = 8765
NAME = "Caracal"
KINDS = ("project", "staff")
ONE_LINE = 100
BADGE_LABEL = "字数超過"
SANDBOX_TOKENS = {"allow-same-origin", "allow-popups", "allow-popups-to-escape-sandbox", "allow-downloads"}
SANDBOX_ATTR = ' sandbox="allow-same-origin allow-popups allow-popups-to-escape-sandbox allow-downloads"'


def oto():
    return _loader.load()


@functools.lru_cache(maxsize=None)
def load_revision(filename):
    """tool フォルダのリビジョンをファイル名で指定して、別名のモジュールとして読み込む (無ければ None)。
    (OTO_TARGET で変異版を指しても、こちらは常に tool フォルダのファイル)"""
    path = _loader.rev_path(filename)
    if not os.path.isfile(path):
        return None
    oto()                                                  # 先に最小スタブを入れておく
    name = "oto_rev_" + os.path.splitext(filename)[0].replace("outlook_total_organizer_", "")
    if name in sys.modules:
        return sys.modules[name]
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


def common_js(mod=None):
    """共通の CSS/JS (HTMLReportGenerator._get_common_js_and_css の戻り値)。"""
    return (mod or oto()).HTMLReportGenerator(tempfile.gettempdir(), PORT)._get_common_js_and_css()


# ============================================================
# JavaScript の文字列リテラルの字句解析 (テスト用の道具)
# ============================================================
class JSSyntaxError(AssertionError):
    """JS の構文エラー (テストでは「失敗」として数える)。"""


_JS_ESC = {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v"}


def js_scan(code):
    """JavaScript のコードを、文字列リテラル ('…' / "…") とそれ以外に分ける (ECMAScript の文字列リテラルの規則)。
    戻り値: (骨格 = 文字列リテラルを S に置き換えたコード, [文字列リテラルの値 (エスケープを解いたもの)])。
    閉じていない文字列・文字列の中の生の改行 (\\r \\n) は JSSyntaxError (ブラウザでも構文エラー)。"""
    skel, strings, i, n = [], [], 0, len(code)
    while i < n:
        c = code[i]
        if c not in "'\"":
            skel.append(c)
            i += 1
            continue
        q, i, buf = c, i + 1, []
        while True:
            if i >= n:
                raise JSSyntaxError(f"文字列が閉じていない: {code!r}")
            c = code[i]
            if c == q:
                i += 1
                break
            if c in "\r\n":
                raise JSSyntaxError(f"文字列の中に生の改行がある: {code!r}")
            if c != "\\":
                buf.append(c)
                i += 1
                continue
            if i + 1 >= n:
                raise JSSyntaxError(f"文字列が \\ で終わっている: {code!r}")
            e = code[i + 1]
            i += 2
            if e in "\r\n\u2028\u2029":                    # 行継続 (何も足さない)
                if e == "\r" and code[i:i + 1] == "\n":
                    i += 1
            elif e == "x":
                buf.append(chr(int(code[i:i + 2], 16)))
                i += 2
            elif e == "u":
                if code[i:i + 1] == "{":
                    j = code.index("}", i)
                    buf.append(chr(int(code[i + 1:j], 16)))
                    i = j + 1
                else:
                    buf.append(chr(int(code[i:i + 4], 16)))
                    i += 4
            elif e == "0" and not code[i:i + 1].isdigit():
                buf.append("\0")
            elif e.isdigit():
                raise JSSyntaxError(f"8進数のエスケープ (想定外): {code!r}")
            else:
                buf.append(_JS_ESC.get(e, e))              # \' \" \\ と、意味の無いエスケープ (\q → q)
        strings.append("".join(buf))
        skel.append("S")
    return "".join(skel), strings


# ============================================================
# HTML の読み取り (標準ライブラリの html.parser)
# ============================================================
class _Events(HTMLParser):
    """解析の出来事を順に記録する (start / startend / end / data / comment / decl …)。続く data は1つにまとめる。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.events = []

    def handle_starttag(self, tag, attrs):
        self.events.append(("start", tag, tuple(attrs)))

    def handle_startendtag(self, tag, attrs):
        self.events.append(("startend", tag, tuple(attrs)))

    def handle_endtag(self, tag):
        self.events.append(("end", tag))

    def handle_data(self, data):
        if self.events and self.events[-1][0] == "data":
            self.events[-1] = ("data", self.events[-1][1] + data)
        else:
            self.events.append(("data", data))

    def handle_comment(self, data):
        self.events.append(("comment", data))

    def handle_decl(self, decl):
        self.events.append(("decl", decl))

    def handle_pi(self, data):
        self.events.append(("pi", data))

    def unknown_decl(self, data):
        self.events.append(("unknown_decl", data))


def html_events(text):
    p = _Events()
    p.feed(text)
    p.close()
    return p.events


def shape(events):
    """タグ・属性名の並び (属性の値と文字は除く)。"""
    out = []
    for e in events:
        if e[0] in ("start", "startend"):
            out.append((e[0], e[1], tuple(n for n, _v in e[2])))
        elif e[0] == "data":
            out.append(("data",))
        else:
            out.append(e)
    return out


def start_tags(events, tag):
    return [e for e in events if e[0] in ("start", "startend") and e[1] == tag]


def all_attr_names(events):
    return Counter(n for e in events if e[0] in ("start", "startend") for n, _v in e[2])


class Node:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.children = tag, dict(attrs), parent, []

    @property
    def classes(self):
        return (self.attrs.get("class") or "").split()

    def text(self):
        return "".join(c if isinstance(c, str) else c.text() for c in self.children)

    def iter(self):
        yield self
        for c in self.children:
            if isinstance(c, Node):
                yield from c.iter()


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
        if self.cur.children and isinstance(self.cur.children[-1], str):
            self.cur.children[-1] += data
        else:
            self.cur.children.append(data)


def parse_html(text):
    b = _TreeBuilder()
    b.feed(text)
    b.close()
    return b.root


def is_badge(node):
    return isinstance(node, Node) and node.tag == "span" and "len-over-badge" in node.classes


# ============================================================
# レポートへの入力 (俯瞰の要約データ・元スレッド)
# ============================================================
FILLER = "あいうえおかきくけこさしすせそたちつてとなにぬねの"


def text_of(n, tag):
    """先頭に識別用の tag を付けた、ちょうど n 字 (改行なし・前後の空白なし・NFC で変わらない文字だけ) の文。"""
    s = tag
    while len(s) < n:
        s += FILLER
    s = s[:n]
    assert len(s) == n and s.startswith(tag) and s == s.strip() and "\n" not in s
    return s


def s2_item(text, sids=("T1",), **kw):
    """俯瞰の Stage2 の1項目 (ensure_struct 後の形)。"""
    d = {"category": "プロジェクト管理", "project_scope": "横断業務", "action_type": "通知・共有", "text": text,
         "status_icon": "🔵", "source_thread_ids": list(sids)}
    d.update(kw)
    return d


def overview_summary(manager=(), status=(), stalled=(), threads=()):
    return {"manager_actions": list(manager), "staff_status": list(status), "stalled_monitor": list(stalled),
            "updated_history": "", "ai_questions": [], "threads": list(threads)}


FIELDS = ("text", "icon", "topic", "imp", "summary", "owner", "action", "status", "sender", "received", "body", "tid")
LABELS = {"text": "〔要約の行〕", "icon": "〔アイコン〕", "topic": "〔件名〕", "imp": "〔重要度〕", "summary": "〔要約〕",
          "owner": "〔担当〕", "action": "〔内容〕", "status": "〔状態〕", "sender": "〔差出人〕", "received": "〔受信〕",
          "body": "〔本文〕", "tid": "〔根拠ID〕"}
# 表示の文字に1回だけ出る項目 (根拠ID は表示されず、JS の引数 "Caracal_<根拠ID>" にだけ出る)
SHOWN_FIELDS = tuple(f for f in FIELDS if f != "tid")

# 通常の値 (特殊文字なし)。重要度・状態は「高/中/低」「未設定/漏れ/未定/完了/遅延」を含まない
# (= 悪意のある値と同じ色・並び順になり、HTML の形がそろう)
BENIGN = {"text": "〔要約の行〕現場の工程会議で、来週の搬入日程を確認した。",
          "icon": "〔アイコン〕🔵",
          "topic": "〔件名〕10月の搬入日程の確認",
          "imp": "〔重要度〕通常",
          "summary": "〔要約〕搬入日程を10/12に確定。クレーンの手配は佐治さん。",
          "owner": "〔担当〕佐治",
          "action": "〔内容〕クレーンを手配する",
          "status": "〔状態〕対応中",
          "sender": "〔差出人〕Saji Taro",
          "received": "〔受信〕2026-10-01 09:00",
          "body": "〔本文〕お疲れさまです。\n搬入日程の件、10/12で確定しました。\nよろしくお願いします。",
          "tid": "〔根拠ID〕T9"}

P_SCRIPT = '"><script>alert(1)</script>'
P_ATTR = '" onmouseover="x'
P_JS = "\\'); alert(1);//"
PAYLOADS = (
    ("script", P_SCRIPT),
    ("attr", P_ATTR),
    ("js", P_JS),
    ("img", "</span></div></td><img src=x onerror=alert(1)><span>"),
    ("entity", "&lt;b&gt;R&amp;D&quot;&#39; &copy; &copy &amp"),
    ("mixed", "It's \"Q&A\" <i>x</i> a<b c>d 5 > 3 & 2 < 4 </textarea><!-- -->"),
    ("newline", "1行目\n2行目\r\n3行目 C:\\new\\temp \\' \\\\ end\u2028x"),
    ("all", P_SCRIPT + P_ATTR + P_JS),
)


def malicious(payload):
    return {f: LABELS[f] + payload for f in FIELDS}


def build_inputs(kind, v, extra_items=()):
    sec = "projects" if kind == "project" else "staffs"
    mail = {"body": v["body"], "html_body": "", "entry_id": "E1", "subject": "件名", "conversation_topic": "件名",
            "sender_name": v["sender"], "received": v["received"]}
    orig = {NAME: {"T1": {"latest_date": datetime(2026, 10, 1, 9, 0), "latest_entry_id": "E1", "topic": "件名",
                          "mails": [mail]}}}
    thread = {"thread_id": "T1", "topic": v["topic"], "summary": v["summary"], "is_target": True, "importance": v["imp"],
              "category": "その他", "project_scope": "横断業務", "action_type": "通知・共有",
              "actions": [{"owner": v["owner"], "action": v["action"], "status": v["status"]}]}
    item = s2_item(v["text"], ["T1", v["tid"]], status_icon=v["icon"])
    data = overview_summary(manager=[item], status=list(extra_items), threads=[thread])
    return data, orig, {sec: {NAME: {}}}


class ReportCase(unittest.TestCase):
    def setUp(self):
        cm = tempdir_cwd()
        self.tmp = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        out = io.StringIO()                                   # レポート生成の [DEBUG] 表示・字数超過のログを黙らせる
        cm2 = contextlib.redirect_stdout(out)
        cm2.__enter__()
        self.addCleanup(cm2.__exit__, None, None, None)

    def render_data(self, kind, data, orig, knowledge, reformat=False, mod=None):
        gen = (mod or oto()).HTMLReportGenerator(os.path.join(self.tmp, "out"), PORT)
        fn = gen.generate_project_report if kind == "project" else gen.generate_staff_report
        path = fn(NAME, {NAME: data}, orig, knowledge, "2026/09/27 - 2026/10/04", "重要度順", 1000, 500, "adopted",
                  reformat)
        self.assertTrue(path, f"{kind}: HTML が出力されなかった (空のパスが返った = レポート生成が例外で失敗した)")
        with open(path, "r", encoding="utf-8", newline="") as f:          # 改行コードを変えずに読む
            return f.read()

    def render(self, kind, values, reformat=False, mod=None, extra_items=()):
        data, orig, knowledge = build_inputs(kind, copy.deepcopy(values), extra_items)
        return self.render_data(kind, data, orig, knowledge, reformat, mod)


# ============================================================
# 1. report_text_html / report_js_str_html
# ============================================================
class TestJsScannerSelfCheck(unittest.TestCase):
    """テスト用の道具 js_scan 自体の確認 (ECMAScript の文字列リテラルの規則どおりに読めること)。"""

    def test_scan(self):
        self.assertEqual(js_scan("f('a\\'b', \"c\\\"d\", 8765)"), ("f(S, S, 8765)", ["a'b", 'c"d']))
        self.assertEqual(js_scan("'a\\\\'"), ("S", ["a\\"]))
        self.assertEqual(js_scan("'\\n\\r\\t\\x41\\u3042\\u{1F600}\\q\\0'"), ("S", ["\n\r\tAあ\U0001F600q\0"]))
        self.assertEqual(js_scan("'a\\\nb'"), ("S", ["ab"]))                 # 行継続
        self.assertEqual(js_scan("'a\u2028b'"), ("S", ["a\u2028b"]))         # ES2019 から文字列に書ける

    def test_breakouts_are_visible(self):
        self.assertEqual(js_scan("f('\\\\'); alert(1); g('')"), ("f(S); alert(1); g(S)", ["\\", ""]))
        for bad in ("f('abc", "f('a\nb')", "f('a\rb')", "f('a\\", "f('\\\\'); alert(1);//')"):
            with self.subTest(code=bad):
                with self.assertRaises(JSSyntaxError):
                    js_scan(bad)


class TestReportTextHtml(unittest.TestCase):
    def f(self, v):
        return oto().report_text_html(v)

    def test_signature(self):
        self.assertEqual(list(inspect.signature(oto().report_text_html).parameters), ["value"])

    def test_table(self):
        """< > & " ' を無害化。\\ と改行はそのまま。None・数値などは str() した文字列。"""
        cases = (
            ("<script>", "&lt;script&gt;"),
            ("&", "&amp;"),
            ('"', "&quot;"),
            ("'", "&#x27;"),
            ("\\", "\\"),
            ("a\nb\r\nc", "a\nb\r\nc"),
            (None, "None"),
            (0, "0"), (12, "12"), (-3.5, "-3.5"), (True, "True"),
            ("", ""),
            ("通常の文です。（10/12）", "通常の文です。（10/12）"),
            (P_SCRIPT, "&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt;"),
            (P_ATTR, "&quot; onmouseover=&quot;x"),
            ("&lt;b&gt;", "&amp;lt;b&amp;gt;"),
            (["<a>"], "[&#x27;&lt;a&gt;&#x27;]"),
            (datetime(2026, 10, 1, 9, 0), "2026-10-01 09:00:00"),
        )
        for value, expected in cases:
            with self.subTest(value=value):
                r = self.f(value)
                self.assertIs(type(r), str)
                self.assertEqual(r, expected)

    def test_is_html_escape_of_str_on_random_texts(self):
        """仕様の定義 html.escape(str(value)) と一致し、HTML として読むと元の文字に戻る (特殊文字は残らない)。"""
        units = ["<", ">", "&", '"', "'", "\\", "\n", "\r", " ", "a", "あ", "😀", ";", "#", "x27", "amp", "lt"]
        rng = random.Random(20261005)
        for _ in range(500):
            s = "".join(rng.choice(units) for _ in range(rng.randint(0, 25)))
            r = self.f(s)
            self.assertEqual(r, html_mod.escape(s), repr(s))
            self.assertEqual(html_mod.unescape(r), s, repr(s))
            self.assertFalse(set(r) & set("<>\"'"), repr(r))


class TestReportJsStrHtml(unittest.TestCase):
    def f(self, v):
        return oto().report_js_str_html(v)

    def roundtrip(self, out):
        """HTML の属性値として読んだ後 (html.unescape)、JS の '…' 文字列として解釈した値。抜け出したら失敗。"""
        attr = html_mod.unescape(out)
        skel, strings = js_scan("'" + attr + "'")
        self.assertEqual(skel, "S", f"JS の文字列から抜け出している: {attr!r}")
        return strings[0]

    def test_signature(self):
        self.assertEqual(list(inspect.signature(oto().report_js_str_html).parameters), ["value"])

    def test_table(self):
        """None は ""。JS の \\→\\\\、'→\\'、\\r は削除、\\n→\\\\n にしてから html.escape(…, quote=True)。"""
        cases = (
            (None, ""),
            ("", ""),
            ("'", "\\&#x27;"),
            ('"', "&quot;"),
            ("\\", "\\\\"),
            ("a\nb", "a\\nb"),
            ("a\r\nb", "a\\nb"),
            ("a\rb", "ab"),
            ("<script>", "&lt;script&gt;"),
            ("&", "&amp;"),
            (5, "5"), (-2.5, "-2.5"),
            ("通常の文です。", "通常の文です。"),
            (P_JS, "\\\\\\&#x27;); alert(1);//"),
            ("C:\\new", "C:\\\\new"),
            ("\\'", "\\\\\\&#x27;"),
            (P_ATTR, "&quot; onmouseover=&quot;x"),
        )
        for value, expected in cases:
            with self.subTest(value=value):
                r = self.f(value)
                self.assertIs(type(r), str)
                self.assertEqual(r, expected)

    def test_roundtrip_table(self):
        """属性値として読んで JS の '…' として解釈すると元の値 (\\r を除く)。None は ""。数値は str()。"""
        for value in ("'", '"', "\\", "\\'", "'\\", "a\nb", "a\r\nb", "\r", "<script>alert(1)</script>", "&amp;",
                      P_SCRIPT, P_ATTR, P_JS, "');alert(1);('", "\\\\'", "x\u2028y", "😀あ", 0, 7, None):
            with self.subTest(value=value):
                expected = "" if value is None else str(value).replace("\r", "")
                self.assertEqual(self.roundtrip(self.f(value)), expected)

    def test_output_cannot_break_out_of_the_attribute(self):
        """出力に " ' < > は無く、& はすべて文字参照の始まり (属性の値から抜け出せない・別の文字参照に化けない)。"""
        for value in ("'\"<>&", P_SCRIPT, P_ATTR, P_JS, "&quot;&#39;&lt;"):
            with self.subTest(value=value):
                r = self.f(value)
                self.assertFalse(set(r) & set("\"'<>"), repr(r))
                stripped = r
                for ent in ("&amp;", "&lt;", "&gt;", "&quot;", "&#x27;"):
                    stripped = stripped.replace(ent, "")
                self.assertNotIn("&", stripped, repr(r))

    def test_roundtrip_on_random_texts_in_a_real_onclick_attribute(self):
        """ランダムな文を onclick="f('…', 1)" に入れて html.parser で読み、JS として解釈すると元の値 (\\r を除く)。"""
        units = ["'", '"', "\\", "\n", "\r", "\r\n", "<", ">", "&", ";", "(", ")", "/", " ", "a", "あ", "\t",
                 "\u2028", "😀", "x27", "#", "amp"]
        rng = random.Random(1005)
        for _ in range(500):
            s = "".join(rng.choice(units) for _ in range(rng.randint(0, 20)))
            doc = f'<button onclick="f(\'{self.f(s)}\', 1)">x</button><i>after</i>'
            ev = html_events(doc)
            self.assertEqual(shape(ev), [("start", "button", ("onclick",)), ("data",), ("end", "button"),
                                         ("start", "i", ()), ("data",), ("end", "i")], repr(s))
            skel, strings = js_scan(ev[0][2][0][1])
            self.assertEqual(skel, "f(S, 1)", repr(s))
            self.assertEqual(strings, [s.replace("\r", "")], repr(s))


# ============================================================
# 2. 本物の 2 つのレポート
# ============================================================
class OverviewEscapeCase(ReportCase):
    def sub(self, s, bvals, mvals):
        if s is None:
            return None
        for f in SHOWN_FIELDS:
            s = s.replace(bvals[f], mvals[f])
        return s

    @staticmethod
    def js_map(bvals, mvals):
        """JS の引数: 通常の値 → 悪意のある値が戻るべき値 (\\r を除く)。"""
        return {bvals["topic"]: mvals["topic"].replace("\r", ""),
                f"{NAME}_{bvals['tid']}": f"{NAME}_{mvals['tid']}".replace("\r", "")}

    def check_premise(self, events, vals, label):
        """前提: 通常の値の HTML に、各値が想定どおりの所に1回ずつ出ている (比べる意味がある)。"""
        datas = [e[1] for e in events if e[0] == "data"]
        for f in FIELDS:
            n = sum(d.count(vals[f]) for d in datas)
            self.assertEqual(n, 0 if f == "tid" else 1, f"{label}: 前提: {f} の値が表示の文字に {n} 回出ている")
        attrs = [(n, v) for e in events if e[0] in ("start", "startend") for n, v in e[2]]
        self.assertEqual([n for n, v in attrs if v and vals["body"] in v], ["data-original"],
                         f"{label}: 前提: 本文は data-original 属性に1回")
        js_args = Counter()
        for n, v in attrs:
            if n.startswith("on") and v:
                js_args.update(s for s in js_scan(v)[1] if s in (vals["topic"], f"{NAME}_{vals['tid']}"))
        self.assertEqual(js_args[vals["topic"]], 2, f"{label}: 前提: 件名は「📄 詳細」「✨ 要約」の JS の引数に1回ずつ")
        self.assertEqual(js_args[f"{NAME}_{vals['tid']}"], 1, f"{label}: 前提: 根拠IDは jumpToThread の引数に1回")
        for f in FIELDS:
            if f != "body":
                self.assertFalse([n for n, v in attrs if v and vals[f] in v and not n.startswith("on")],
                                 f"{label}: 前提: {f} が (on… 以外の) 属性に出ている")

    def compare(self, b_html, m_html, bvals, mvals, label):
        """悪意のある値の HTML が、通常の値の HTML と「タグ・属性の並びが同じ」で、値だけが元の文字どおりに入れ替わっている。"""
        be, me = html_events(b_html), html_events(m_html)
        self.check_premise(be, bvals, label)
        # タグ・属性の並び (script 要素・onmouseover などの属性が増えていない)
        self.assertEqual(len(start_tags(me, "script")), len(start_tags(be, "script")), f"{label}: script 要素の数が変わった")
        for evil in ("onmouseover", "onerror"):
            self.assertEqual(all_attr_names(me)[evil], all_attr_names(be)[evil], f"{label}: {evil} 属性が増えた")
        bs, ms = shape(be), shape(me)
        if bs != ms:
            i = next((k for k, (x, y) in enumerate(zip(bs, ms)) if x != y), min(len(bs), len(ms)))
            self.fail(f"{label}: タグ・属性の並びが通常の値の HTML と違う (#{i}): 通常 {bs[i:i + 3]} / 悪意 {ms[i:i + 3]}")
        # 値: 表示の文字と属性の値は、通常の値を悪意のある値に置き換えたものと同じ。JS は骨格が同じで、件名・根拠IDの引数だけが元の値
        jsmap = self.js_map(bvals, mvals)
        mapped = Counter()
        for k, (b, m) in enumerate(zip(be, me)):
            if b[0] == "data":
                self.assertEqual(m[1], self.sub(b[1], bvals, mvals), f"{label}: 表示の文字が元の値どおりでない (#{k})")
            elif b[0] in ("start", "startend"):
                for (bn, bv), (_mn, mv) in zip(b[2], m[2]):
                    if bn.startswith("on") and bv:
                        bsk, bstr = js_scan(bv)
                        try:
                            msk, mstr = js_scan(mv)
                        except JSSyntaxError as e:
                            self.fail(f"{label}: <{b[1]} {bn}> の JS が壊れた: {e}")
                        self.assertEqual(msk, bsk, f"{label}: <{b[1]} {bn}> の JS の骨格が変わった (文字列から抜け出した)")
                        for x, y in zip(bstr, mstr):
                            if x in jsmap:
                                mapped[x] += 1
                                self.assertEqual(y, jsmap[x], f"{label}: <{b[1]} {bn}> の引数が元の値に戻らない")
                            else:
                                self.assertEqual(y, x, f"{label}: <{b[1]} {bn}> の、件名・根拠ID以外の引数が変わった")
                    else:
                        self.assertEqual(mv, self.sub(bv, bvals, mvals), f"{label}: <{b[1]} {bn}> の値が元の値どおりでない")
            else:
                self.assertEqual(m, b, f"{label}: #{k} が変わった")
        self.assertEqual(sorted(mapped.values()), [1, 2], f"{label}: 件名 (2つ)・根拠ID (1つ) の JS の引数の数が違う")


class TestMaliciousValuesAreNotInterpreted(OverviewEscapeCase):
    """悪意のある値 ("><script>… / " onmouseover="x / \\'); alert(1);// など) を全項目に入れても、HTML のタグ・属性にならず、
    表示は元の文字のまま。onclick の件名・根拠IDの引数は元の値に戻る。プロジェクト・スタッフ、reformat_mode の両方で。"""

    def test_each_payload_in_every_field(self):
        for pname, payload in PAYLOADS:
            for kind in KINDS:
                for reformat in (False, True):
                    with self.subTest(payload=pname, kind=kind, reformat=reformat):
                        label = f"{pname}/{kind}/reformat={reformat}"
                        mvals = malicious(payload)
                        self.compare(self.render(kind, BENIGN, reformat), self.render(kind, mvals, reformat),
                                     BENIGN, mvals, label)

    def test_each_field_alone(self):
        """1項目だけに悪意のある値を入れても (他は通常の値)、同じ。"""
        for f in FIELDS:
            for kind in KINDS:
                with self.subTest(field=f, kind=kind):
                    mvals = dict(BENIGN)
                    mvals[f] = LABELS[f] + PAYLOADS[-1][1] + "<img src=x onerror=alert(2)>"
                    self.compare(self.render(kind, BENIGN), self.render(kind, mvals), BENIGN, mvals, f"{f}/{kind}")

    def test_visible_texts_and_attributes(self):
        """各項目の表示 (要素の文字) と data-original・onclick の件名・根拠IDが、元の値そのもの (直接の確認)。"""
        mvals = malicious(PAYLOADS[-1][1])
        for kind in KINDS:
            with self.subTest(kind=kind):
                root = parse_html(self.render(kind, mvals))
                lis = [n for n in root.iter() if n.tag == "li" and "js-summary-item" in n.classes]
                self.assertEqual(len([li for li in lis if mvals["text"] in li.text()]), 1, "要約の行")
                self.assertEqual([n for li in lis for n in li.iter() if n.tag in ("script", "img", "i", "b")], [],
                                 "要約の行の中に要素ができた")
                self.assertIn(mvals["icon"], [n.text() for n in root.iter() if "status-icon" in n.classes], "状態アイコン")
                self.assertIn(mvals["topic"], [n.text() for n in root.iter() if n.tag == "span"], "カードの件名")
                self.assertIn("重要度:" + mvals["imp"], [n.text() for n in root.iter() if "badge-imp" in n.classes],
                              "重要度")
                self.assertIn(mvals["summary"], [n.text() for n in root.iter() if n.tag == "div"], "カードの要約")
                tds = [n.text() for n in root.iter() if n.tag == "td"]
                self.assertIn(mvals["owner"], tds, "担当")
                self.assertIn(mvals["action"], tds, "内容")
                self.assertIn(mvals["status"], tds, "状態")
                self.assertIn("👤 " + mvals["sender"], [n.text() for n in root.iter() if n.tag == "b"], "差出人名")
                self.assertIn(mvals["received"], [n.text() for n in root.iter() if n.tag == "span"], "受信日時")
                bodies = [n for n in root.iter() if "mail-item-body" in n.classes]
                self.assertEqual(len(bodies), 1)
                self.assertEqual(bodies[0].attrs.get("data-original"), mvals["body"], "本文の data-original")
                self.assertEqual(bodies[0].text(), mvals["body"], "本文の表示")
                calls = [js_scan(n.attrs["onclick"]) for n in root.iter() if "summarize" in (n.attrs.get("onclick") or "")]
                self.assertEqual(len(calls), 2)
                for skel, strings in calls:
                    self.assertIn(mvals["topic"].replace("\r", ""), strings, skel)
                jumps = [js_scan(n.attrs["onclick"]) for n in root.iter() if "jumpToThread" in (n.attrs.get("onclick") or "")]
                self.assertEqual([s for _sk, s in jumps], [[f"{NAME}_T1"], [f"{NAME}_{mvals['tid']}".replace("\r", "")]],
                                 "根拠IDの jumpToThread の引数")
                self.assertNotIn("onmouseover", [k for n in root.iter() for k in n.attrs])


class TestNoneAndNumbers(OverviewEscapeCase):
    """None・数値は str() した文字列で表示 (件名の JS の引数は None なら "")。レポートは失敗しない。"""

    def test_none_and_numbers(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                data, orig, knowledge = build_inputs(kind, dict(BENIGN))
                th = data["threads"][0]
                th["summary"] = 12345
                th["actions"] = [{"owner": None, "action": 3.5, "status": "未定"}, {"action": "<x>"}]
                mail = orig[NAME]["T1"]["mails"][0]
                mail["sender_name"], mail["received"] = None, datetime(2026, 10, 1, 9, 0)
                root = parse_html(self.render_data(kind, data, orig, knowledge))
                tds = [n.text() for n in root.iter() if n.tag == "td"]
                self.assertEqual(tds, ["None", "3.5", "未定", "None", "<x>", ""])
                self.assertIn("12345", [n.text() for n in root.iter() if n.tag == "div"])
                self.assertIn("👤 None", [n.text() for n in root.iter() if n.tag == "b"])
                self.assertIn("2026-10-01 09:00:00", [n.text() for n in root.iter() if n.tag == "span"])
                for topic, expected_js in ((None, ""), (2026, "2026")):
                    data, orig, knowledge = build_inputs(kind, dict(BENIGN))
                    data["threads"][0]["topic"] = topic
                    root = parse_html(self.render_data(kind, data, orig, knowledge))
                    self.assertIn(str(topic), [n.text() for n in root.iter() if n.tag == "span"])
                    calls = [js_scan(n.attrs["onclick"])[1] for n in root.iter()
                             if "summarize" in (n.attrs.get("onclick") or "")]
                    self.assertEqual(len(calls), 2)
                    for strings in calls:
                        self.assertIn(expected_js, strings)


NORMAL = {"text": "現場の工程会議で、来週の搬入日程（10/12）を確認した。担当: 佐治 / 進捗 80% #12",
          "icon": "🟡",
          "topic": "【Caracal】10月の搬入日程の確認 #12 (再送) 100% / A-1",
          "imp": "高",
          "summary": "搬入日程を10/12に確定。\nクレーンの手配は佐治さん。費用 ¥1,200,000 (税別)",
          "owner": "佐治 (Saji)",
          "action": "クレーンを手配する; 予備日 10/13",
          "status": "未定",
          "sender": "Saji Taro (佐治 太郎)",
          "received": datetime(2026, 10, 1, 9, 0),
          "body": ("お疲れさまです。\n資料: https://example.com/docs/plan?id=12#top\n"
                   "C:\\share\\plan の図面を参照。\nよろしくお願いします。"),
          "tid": "T1"}


def add_html_mail_thread(kind, data, orig, html_body, topic="HTML本文のスレッド", importance="中"):
    """HTML 本文 (html_body) の最新メールを持つスレッド T2 を足す (根拠IDにも T2 を足す)。"""
    mail = {"body": "", "html_body": html_body, "entry_id": "E2", "subject": "件名2", "conversation_topic": "件名2",
            "sender_name": "Hata", "received": datetime(2026, 10, 2, 9, 0)}
    orig[NAME]["T2"] = {"latest_date": datetime(2026, 10, 2, 9, 0), "latest_entry_id": "E2", "topic": "件名2",
                        "mails": [mail]}
    data["threads"].append({"thread_id": "T2", "topic": topic, "summary": "HTMLメールの要約", "is_target": True,
                            "importance": importance, "category": "その他", "project_scope": "横断業務",
                            "action_type": "通知・共有", "actions": []})
    data["manager_actions"][0]["source_thread_ids"].append("T2")


class TestNormalTextIsUnchanged(OverviewEscapeCase):
    """通常の文 (HTML の特殊文字を含まない) は、表示の文字が変わらない。"""

    def test_displayed_as_is_on_target(self):
        """対象のリビジョン: 通常の文は、そのままの文字で表示される (件名に \\ や改行があっても表示は同じ・JS は元の値)。"""
        vals = dict(BENIGN)
        vals["topic"] = "〔件名〕C:\\work\\new 1行目\n2行目"
        vals["body"] = BENIGN["body"] + "\n資料: https://example.com/a?b=1#c"
        for kind in KINDS:
            for reformat in (False, True):
                with self.subTest(kind=kind, reformat=reformat):
                    root = parse_html(self.render(kind, vals, reformat))
                    self.assertIn(vals["topic"], [n.text() for n in root.iter() if n.tag == "span"])
                    self.assertIn(vals["summary"], [n.text() for n in root.iter() if n.tag == "div"])
                    self.assertIn("👤 " + vals["sender"], [n.text() for n in root.iter() if n.tag == "b"])
                    tds = [n.text() for n in root.iter() if n.tag == "td"]
                    self.assertEqual(tds, [vals["owner"], vals["action"], vals["status"]])
                    body = [n for n in root.iter() if "mail-item-body" in n.classes][0]
                    self.assertEqual(body.text(), vals["body"])
                    self.assertEqual(body.attrs.get("data-original"), vals["body"])
                    links = [n for n in body.iter() if n.tag == "a"]
                    self.assertEqual([a.attrs.get("href") for a in links], ["https://example.com/a?b=1#c"],
                                     "前提: 本文の URL が自動リンクにならない")
                    for n in root.iter():
                        if "summarize" in (n.attrs.get("onclick") or ""):
                            self.assertIn(vals["topic"], js_scan(n.attrs["onclick"])[1])

    def test_html_is_byte_identical_between_11_and_12(self):
        """_11 と _12 (ファイル名で指定) で、通常の文のレポートの HTML がバイト単位で同じ (reformat_mode も)。
        違ってよいのは、共通の CSS/JS (fix1 の変更。範囲ガードで別に確かめる) と、HTML 本文の iframe の sandbox 属性だけ。"""
        old, new = load_revision(OLD_REV), load_revision(NEW_REV)
        if old is None or new is None:
            self.skipTest(f"A10 のリビジョン対 ({OLD_REV} / {NEW_REV}) が無い")
        extra = [s2_item("進捗は順調。\\ 区切り / 予定どおり", ["T1"]), s2_item("停滞なし", [])]
        for kind in KINDS:
            for reformat in (False, True):
                for with_html in (False, True):
                    with self.subTest(kind=kind, reformat=reformat, html_mail=with_html):
                        out = []
                        for mod in (old, new):
                            data, orig, knowledge = build_inputs(kind, copy.deepcopy(NORMAL), extra)
                            data["manager_actions"][0]["source_thread_ids"] = ["T1"]
                            if with_html:
                                add_html_mail_thread(kind, data, orig, '<p style="color:red">HTML の本文</p>')
                            h = self.render_data(kind, data, orig, knowledge, reformat, mod)
                            self.assertEqual(h.count(common_js(mod)), 1, "前提: 共通の CSS/JS がそのまま1回入っている")
                            out.append(h.replace(common_js(mod), "<!--COMMON-->"))
                        a, b = out
                        self.assertIn("搬入日程", b)
                        self.assertEqual(b.count(SANDBOX_ATTR), 1 if with_html else 0, "iframe の sandbox 属性の数")
                        self.assertEqual(a, b.replace(SANDBOX_ATTR, ""))


# ============================================================
# 3. 字数超過バッジは、エスケープ前の文で数える
# ============================================================
class TestBadgeCountedBeforeEscaping(ReportCase):
    CASES = (                                       # (文, バッジの字数 / None = 付かない)
        (text_of(100, "〔R&D〕"), None),
        (text_of(100, "〔<>&\"'〕"), None),
        (text_of(95, "〔" + "&" * 20 + "〕"), None),
        (text_of(100, "〔<script>alert(1)</script>〕"), None),
        (text_of(101, "〔Q&A〕"), 101),
        (text_of(101, "〔\"><script>x</script>〕"), 101),
        (text_of(130, "〔&lt;&amp;〕"), 130),
    )

    def test_badge_is_decided_by_the_raw_text(self):
        """& < > " ' を含む100字 (エスケープ後は100字を超える) には付かない。101字・130字には文の直後に付く (title は元の字数)。
        表示の文字は元の文のまま。reformat_mode でも同じ。"""
        items = [s2_item(t, ["T1"]) for t, _n in self.CASES]
        for kind in KINDS:
            for reformat in (False, True):
                with self.subTest(kind=kind, reformat=reformat):
                    data = overview_summary(manager=items[:3], status=items[3:5], stalled=items[5:])
                    knowledge = {("projects" if kind == "project" else "staffs"): {NAME: {}}}
                    html = self.render_data(kind, copy.deepcopy(data), {}, knowledge, reformat)
                    root = parse_html(html)
                    lis = [n for n in root.iter() if n.tag == "li" and "js-summary-item" in n.classes]
                    self.assertEqual(len(lis), len(self.CASES))
                    self.assertEqual(start_tags(html_events(html), "script"),
                                     start_tags(html_events(self.render_data(
                                         kind, overview_summary(manager=[s2_item("通常の文", ["T1"])]), {}, knowledge,
                                         reformat)), "script"),
                                     "script 要素が増えた")
                    total = 0
                    for t, n in self.CASES:
                        found = [li for li in lis if t in li.text()]
                        self.assertEqual(len(found), 1, f"文がそのままの文字で表示されていない: {t[:20]!r}")
                        li = found[0]
                        kids = li.children
                        k = next((i for i, c in enumerate(kids) if isinstance(c, str) and t in c), None)
                        self.assertIsNotNone(k, f"文が li の直下の文字として1つにまとまっていない: {t[:20]!r}")
                        self.assertTrue(kids[k].endswith(t + " "), repr(kids[k][-30:]))
                        badges = [c for c in li.iter() if is_badge(c)]
                        if n is None:
                            self.assertEqual(badges, [], f"エスケープ後の字数で数えている? {t[:20]!r}")
                            self.assertNotIn(BADGE_LABEL, li.text())
                        else:
                            self.assertEqual(len(badges), 1, f"バッジが1つでない: {t[:20]!r}")
                            self.assertIs(kids[k + 1], badges[0], "バッジが文の直後に無い")
                            self.assertEqual(badges[0].attrs.get("title"), f"AIの文が{n}字です（目安は{ONE_LINE}字以内）")
                            self.assertEqual(badges[0].text(), BADGE_LABEL)
                            total += 1
                    self.assertEqual(html.count('class="len-over-badge"'), total)


# ============================================================
# 4. fix1: iframe の sandbox・共通JS (escHtml・AI の結果・絞り込みボタン)
# ============================================================
EVIL_HTML_BODY = ('<p>HTML本文です "引用" &amp; R&D</p><script>parent.__pwned_iframe=1;top.__pwned_iframe2=1;</script>'
                  '<img src=x onerror="parent.__pwned_iframe3=1"><a href="https://example.com/" target="_blank">リンク</a>')


class TestIframeSandbox(ReportCase):
    """俯瞰2画面の最新メールの HTML 本文の iframe に sandbox="allow-same-origin allow-popups allow-popups-to-escape-sandbox
    allow-downloads" (allow-scripts は無い)。srcdoc (本文) の扱いは変わらない。"""

    def test_sandbox_attribute(self):
        for kind in KINDS:
            for reformat in (False, True):
                for body in ("<p>通常のHTML本文</p>", EVIL_HTML_BODY):
                    with self.subTest(kind=kind, reformat=reformat, body=body[:12]):
                        data, orig, knowledge = build_inputs(kind, copy.deepcopy(BENIGN))
                        add_html_mail_thread(kind, data, orig, body)
                        html = self.render_data(kind, data, orig, knowledge, reformat)
                        frames = start_tags(html_events(html), "iframe")
                        self.assertEqual(len(frames), 1, "HTML 本文の iframe が1つでない")
                        attrs = dict(frames[0][2])
                        self.assertEqual([n for n, _v in frames[0][2]].count("sandbox"), 1, "sandbox 属性が1つでない")
                        tokens = (attrs.get("sandbox") or "").split()
                        self.assertNotIn("allow-scripts", tokens)
                        self.assertEqual(set(tokens), SANDBOX_TOKENS)
                        self.assertEqual(len(tokens), len(set(tokens)))
                        self.assertEqual(attrs.get("srcdoc"), body, "srcdoc の本文が変わった")
                        self.assertEqual(attrs.get("id"), f"iframe-{NAME}_T2_m0")

    def test_evil_html_body_does_not_change_the_outer_document(self):
        """HTML 本文のスクリプトや " は、外側の HTML のタグ・属性にならない (srcdoc の中に閉じている)。"""
        for kind in KINDS:
            with self.subTest(kind=kind):
                docs = []
                for body in ("<p>通常のHTML本文</p>", EVIL_HTML_BODY):
                    data, orig, knowledge = build_inputs(kind, copy.deepcopy(BENIGN))
                    add_html_mail_thread(kind, data, orig, body)
                    docs.append(html_events(self.render_data(kind, data, orig, knowledge)))
                self.assertEqual(shape(docs[0]), shape(docs[1]))


def _js_function(js, name):
    """共通JS から関数の定義 (function name(…) { … }) を1つ取り出す (行頭の字下げがそろっている前提)。"""
    m = re.search(r"^([ \t]*)(?:async )?function " + re.escape(name) + r"\(.*?^\1\}", js, re.S | re.M)
    return m.group(0) if m else None


class TestCommonJsStrings(unittest.TestCase):
    """共通JS (_get_common_js_and_css の文字列) の確認: escHtml があり、「📄 詳細」「✨ 要約」の AI の結果は escHtml を
    通してから innerHTML に入れる。絞り込みボタンの値は data-v="${escHtml(v)}" と this.dataset.v で渡す。"""

    @classmethod
    def setUpClass(cls):
        cls.js = common_js()

    def interpolations(self, src):
        return re.findall(r"\$\{(.*?)\}", src)

    def test_esc_html_is_defined_once(self):
        self.assertEqual(len(re.findall(r"function escHtml\(", self.js)), 1)
        self.assertIsNotNone(_js_function(self.js, "escHtml"))

    def test_summarize_detail_escapes_ai_results(self):
        fn = _js_function(self.js, "summarizeDetail")
        self.assertIsNotNone(fn)
        sinks = [l for l in fn.splitlines() if "innerHTML" in l]
        self.assertEqual(len(sinks), 1, sinks)
        ips = self.interpolations(sinks[0])
        self.assertEqual(sorted(ips), ["escHtml(a)", "escHtml(p)"], sinks[0])

    def test_summarize_single_mail_escapes_ai_result(self):
        fn = _js_function(self.js, "summarizeSingleMail")
        self.assertIsNotNone(fn)
        sinks = [l for l in fn.splitlines() if "innerHTML" in l]
        self.assertEqual(len(sinks), 1, sinks)
        self.assertEqual(self.interpolations(sinks[0]), ["escHtml(data.summary)"], sinks[0])

    def test_dashboard_filter_buttons_use_data_v(self):
        fn = _js_function(self.js, "renderDashboards")
        self.assertIsNotNone(fn)
        builder = [l for l in fn.splitlines() if re.search(r"const b = \(l, v, c, t\)", l)]
        self.assertEqual(len(builder), 1)
        line = builder[0]
        self.assertIn('data-v="${escHtml(v)}"', line)
        self.assertRegex(line, r"""onclick="applyFilter\('\$\{idPrefix\}', '\$\{t\}', this\.dataset\.v\)""")
        self.assertIn("${l}: ${escHtml(v)}</span>", line)
        self.assertNotIn("${v}", line, "値 v を escHtml を通さずに埋め込んでいる")
        self.assertEqual(sorted(set(self.interpolations(line))), ["c", "escHtml(v)", "idPrefix", "l", "t"])


def _node():
    node = shutil.which("node") or ("/opt/node22/bin/node" if os.path.isfile("/opt/node22/bin/node") else None)
    return node


@functools.lru_cache(maxsize=None)
def _node_env():
    """(node のパス, 環境変数, Playwright が使えるか) を返す。node が無ければ None。"""
    node = _node()
    if not node:
        return None
    paths = [p for p in os.environ.get("NODE_PATH", "").split(os.pathsep) if p]
    paths += [os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(node))), "lib", "node_modules"),
              "/opt/node22/lib/node_modules", "/usr/local/lib/node_modules", "/usr/lib/node_modules"]
    env = dict(os.environ, NODE_PATH=os.pathsep.join(p for p in paths if os.path.isdir(p)))
    if not env.get("PLAYWRIGHT_BROWSERS_PATH") and os.path.isdir("/opt/pw-browsers"):
        env["PLAYWRIGHT_BROWSERS_PATH"] = "/opt/pw-browsers"
    try:
        r = subprocess.run([node, "-e", "require.resolve('playwright')"], env=env, capture_output=True, timeout=60)
        has_pw = r.returncode == 0
    except Exception:                                      # noqa: BLE001
        has_pw = False
    return node, env, has_pw


class TestEscHtmlInNode(unittest.TestCase):
    """escHtml を node で動かす: & < > " ' を無害化 (読み戻すと元の文字)。null/undefined は ""。"""

    def test_table(self):
        ne = _node_env()
        if ne is None:
            self.skipTest("node が無い環境")
        node, env, _ = ne
        src = _js_function(common_js(), "escHtml")
        self.assertIsNotNone(src, "escHtml が無い")
        inputs = ["", "a", "&", "<", ">", '"', "'", "<script>alert('x')</script>", 'a"b\'c&d<e>f', "&amp;&lt;",
                  "日本語", "\\n\n"]
        script = (src + "\nconst ins = " + json.dumps(inputs) + ";\n"
                  "process.stdout.write(JSON.stringify({str: ins.map(escHtml), nul: escHtml(null), und: escHtml(undefined),"
                  " zero: escHtml(0), num: escHtml(12), t: escHtml(true)}));")
        r = subprocess.run([node, "-e", script], env=env, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-500:])
        out = json.loads(r.stdout)
        self.assertEqual((out["nul"], out["und"]), ("", ""), "null/undefined は空文字")
        self.assertEqual((out["zero"], out["num"], out["t"]), ("0", "12", "true"))
        for s, e in zip(inputs, out["str"]):
            with self.subTest(value=s):
                self.assertFalse(set(e) & set("<>\"'"), repr(e))
                self.assertEqual(html_mod.unescape(e), s, repr(e))
                rest = re.sub(r"&(amp|lt|gt|quot|#39|#x27|apos);", "", e)
                self.assertNotIn("&", rest, repr(e))


# ---- Chromium (Playwright) でレポートを開いて確かめる -------------------------------------------
BROWSER_JS = r"""
const fs = require('fs');
const {chromium} = require('playwright');
(async () => {
  const cfg = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const browser = await chromium.launch();
  const results = [];
  try {
    for (const job of cfg.jobs) {
      const out = {label: job.label, dialogs: [], pageerrors: [], requests: []};
      const page = await browser.newPage();
      page.on('dialog', async d => { out.dialogs.push(d.message()); try { await d.dismiss(); } catch (e) {} });
      page.on('pageerror', e => out.pageerrors.push(String((e && e.message) || e)));
      const html = fs.readFileSync(job.html, 'utf8');
      await page.route('**/*', async route => {
        const req = route.request();
        const url = req.url();
        if (url === 'http://report.test/report.html') {
          return route.fulfill({status: 200, contentType: 'text/html; charset=utf-8', body: html});
        }
        if (url.startsWith(`http://localhost:${cfg.port}/`)) {
          const path = new URL(url).pathname;
          let body = null;
          try { body = JSON.parse(req.postData() || 'null'); } catch (e) { body = {_raw: req.postData()}; }
          out.requests.push({path, body});
          return route.fulfill({status: 200, contentType: 'application/json',
                                headers: {'Access-Control-Allow-Origin': '*'}, body: JSON.stringify(cfg.responses[path] || {})});
        }
        return route.fulfill({status: 204, body: ''});     // CDN など外のサイトへは出さない
      });
      const waitFor = async (fn, ms) => {
        const t0 = Date.now();
        while (Date.now() - t0 < ms) { if (await page.evaluate(fn)) return true; await page.waitForTimeout(50); }
        return false;
      };
      const settle = async () => {
        try { await page.waitForLoadState('networkidle', {timeout: 5000}); } catch (e) {}
        await waitFor(() => Array.from(document.images).every(i => i.complete), 3000);   // img の onerror まで待つ
        await page.waitForTimeout(150);
      };
      await page.goto('http://report.test/report.html', {waitUntil: 'load'});
      out.iframe_ready = await waitFor(() => Array.from(document.querySelectorAll('iframe')).every(f => f.contentDocument && f.contentDocument.readyState === 'complete'), 5000);
      out.dash_ready = await waitFor(() => document.querySelectorAll('[id^="dash-counts-"] span.badge').length > 0, 5000);
      await settle();
      out.after_load = await page.evaluate(() => {
        const r = {};
        r.pwned = Object.keys(window).filter(k => k.startsWith('__pwned'));
        r.iframes = Array.from(document.querySelectorAll('iframe')).map(f => {
          let text = null, err = null;
          try { text = f.contentDocument ? f.contentDocument.body.innerText : null; } catch (e) { err = String(e); }
          return {id: f.id, sandbox: f.getAttribute('sandbox'), text, err};
        });
        r.dash = Array.from(document.querySelectorAll('[id^="dash-counts-"]')).map(d => ({
          id: d.id,
          others: Array.from(d.querySelectorAll('*')).filter(e => !(e.tagName === 'SPAN' && e.classList.contains('badge'))).map(e => e.tagName),
          badges: Array.from(d.querySelectorAll('span.badge')).map(s => ({text: s.textContent, v: s.dataset.v === undefined ? null : s.dataset.v}))}));
        return r;
      });
      out.filters = await page.evaluate(async () => {
        const res = [];
        for (const s of Array.from(document.querySelectorAll('[id^="dash-counts-"] span.badge'))) {
          document.querySelectorAll('.js-thread').forEach(c => c.style.display = '');
          try { s.click(); } catch (e) {}
          await new Promise(r => setTimeout(r, 30));
          res.push({text: s.textContent, shown: Array.from(document.querySelectorAll('.js-thread')).filter(c => c.style.display !== 'none').map(c => c.id)});
        }
        document.querySelectorAll('.js-thread').forEach(c => c.style.display = '');
        return res;
      });
      out.jumps = await page.evaluate(async () => {
        window.__jt = [];
        const orig = window.jumpToThread;
        window.jumpToThread = function (x) { window.__jt.push(x); try { return orig.apply(this, arguments); } catch (e) { return null; } };
        for (const a of Array.from(document.querySelectorAll('a.cite-badge'))) { try { a.click(); } catch (e) {} }
        await new Promise(r => setTimeout(r, 50));
        return window.__jt;
      });
      await page.evaluate(() => {          // 「📄 詳細」「✨ 要約」を押す (AI の結果は cfg.responses の悪意のある文)
        for (const b of Array.from(document.querySelectorAll('button[onclick*="summarizeDetail"]'))) { try { b.click(); } catch (e) {} }
        for (const b of Array.from(document.querySelectorAll('button[onclick*="summarizeSingleMail"]'))) { try { b.click(); } catch (e) {} }
      });
      out.ai_ready = await waitFor(() => Array.from(document.querySelectorAll('[id^="detail-"]')).every(c => c.textContent.length > 0)
                                       && Array.from(document.querySelectorAll('[id^="sum-"]')).every(c => c.textContent.includes('💡')), 10000);
      await settle();
      out.ai = await page.evaluate(() => {
        const res = {detail: [], single: []};
        document.querySelectorAll('[id^="detail-"]').forEach(c => res.detail.push({id: c.id, text: c.textContent, tags: Array.from(c.querySelectorAll('*')).map(e => e.tagName)}));
        document.querySelectorAll('[id^="sum-"]').forEach(c => res.single.push({id: c.id, text: c.textContent, tags: Array.from(c.querySelectorAll('*')).map(e => e.tagName)}));
        return res;
      });
      await settle();
      out.pwned_end = await page.evaluate(() => Object.keys(window).filter(k => k.startsWith('__pwned')));
      await page.close();
      results.push(out);
    }
  } finally {
    await browser.close();
  }
  process.stdout.write(JSON.stringify(results));
})().catch(e => { console.error('A10_BROWSER_ERROR ' + ((e && e.stack) || String(e))); process.exit(3); });
"""


def _evil(k):
    return f'"><img src=x onerror="window.__pwned_{k}=1">'


B_TOPIC1 = "件名1\\'); alert('topic1');//" + _evil("topic") + "\n2行目"
B_TOPIC2 = "件名2 \"q\" 'a' \\ b &amp; </script>"
B_TID = "x');alert('tid');('" + _evil("tid")
B_CAT = "x'),alert('cat'),('" + _evil("cat")
B_SCOPE = "<img src=x onerror=\"window.__pwned_pj=1\">'"
B_ACT = "');alert('act');//"
B_BODY = "本文1 \" onmouseover=\"window.__pwned_body=1\" <script>window.__pwned_body2=1</script> &amp; x"
B_POINTS = ["<img src=x onerror=\"window.__pwned_m1=1;alert('m1')\">",
            "</li></ul><script>window.__pwned_m1s=1</script><img src=x onerror=\"window.__pwned_m1b=1\">"]
B_ACTIONS = ["<svg onload=\"window.__pwned_m1a=1\"></svg><img src=x onerror=\"window.__pwned_m1d=1\">"]
B_SUMMARY = "<img src=x onerror=\"window.__pwned_m1c=1;alert('m1c')\">"


def browser_inputs(kind):
    """ブラウザ確認用の入力: T1 (プレーンテキスト本文・悪意のある件名/分類/範囲/行動) と T2 (悪意のある HTML 本文・重要度)。"""
    sec = "projects" if kind == "project" else "staffs"
    m1 = {"body": B_BODY, "html_body": "", "entry_id": "E1", "subject": "s", "conversation_topic": "s",
          "sender_name": "差出人" + _evil("sender"), "received": datetime(2026, 10, 1, 9, 0)}
    m2 = {"body": "", "html_body": EVIL_HTML_BODY, "entry_id": "E2", "subject": "s2", "conversation_topic": "s2",
          "sender_name": "S2", "received": datetime(2026, 10, 2, 9, 0)}
    orig = {NAME: {"T1": {"latest_date": datetime(2026, 10, 1, 9, 0), "latest_entry_id": "E1", "topic": "t", "mails": [m1]},
                   "T2": {"latest_date": datetime(2026, 10, 2, 9, 0), "latest_entry_id": "E2", "topic": "t2", "mails": [m2]}}}
    t1 = {"thread_id": "T1", "topic": B_TOPIC1, "summary": "要約" + _evil("summary"), "is_target": True, "importance": "高",
          "category": B_CAT, "project_scope": B_SCOPE, "action_type": B_ACT,
          "actions": [{"owner": "o" + _evil("owner"), "action": "a" + _evil("action"), "status": "s" + _evil("status")}]}
    t2 = {"thread_id": "T2", "topic": B_TOPIC2, "summary": "要約2", "is_target": True,
          "importance": "<img src=x onerror=\"window.__pwned_imp=1\">", "category": "その他", "project_scope": "横断業務",
          "action_type": "通知・共有", "actions": []}
    item = s2_item("要約の行" + _evil("text"), ["T1", "T2", B_TID], status_icon="<img src=x onerror=\"window.__pwned_icon=1\">")
    return overview_summary(manager=[item], threads=[t1, t2]), orig, {sec: {NAME: {}}}


class TestInChromium(unittest.TestCase):
    """本物のレポートを Chromium で開き、悪意のある値・AI の結果・HTML 本文のスクリプトが実行されないことを確かめる
    (Playwright で localhost のサーバーの応答を差し替える)。node・Playwright・Chromium が無い環境ではスキップ。"""

    @classmethod
    def setUpClass(cls):
        ne = _node_env()
        if ne is None or not ne[2]:
            raise unittest.SkipTest("node / Playwright が無い環境 (Chromium での確認は対象外)")
        node, env, _ = ne
        tmp = tempfile.mkdtemp(prefix="oto_a10_browser_")
        try:
            jobs = []
            for kind in KINDS:
                data, orig, knowledge = browser_inputs(kind)
                with contextlib.redirect_stdout(io.StringIO()):
                    gen = oto().HTMLReportGenerator(os.path.join(tmp, "out_" + kind), PORT)
                    fn = gen.generate_project_report if kind == "project" else gen.generate_staff_report
                    path = fn(NAME, {NAME: data}, orig, knowledge, "2026/09/27 - 2026/10/04", "重要度順", 1000, 500,
                              "adopted", False)
                if not path:
                    raise AssertionError(f"{kind}: HTML が出力されなかった")
                jobs.append({"label": kind, "html": path})
            cfg = {"port": PORT, "jobs": jobs, "responses": {
                "/summarize_detail": {"points": B_POINTS, "recommended_actions": B_ACTIONS},
                "/summarize_single": {"summary": B_SUMMARY}}}
            cfg_path = os.path.join(tmp, "cfg.json")
            js_path = os.path.join(tmp, "check.js")
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False)
            with open(js_path, "w", encoding="utf-8") as f:
                f.write(BROWSER_JS)
            r = subprocess.run([node, js_path, cfg_path], env=env, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=180)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if r.returncode != 0 and "browserType.launch" in r.stderr:
            raise unittest.SkipTest("Chromium を起動できない環境: " + r.stderr.strip().splitlines()[-1][:120])
        if r.returncode != 0:
            raise AssertionError("ブラウザ確認のスクリプトが失敗: " + r.stderr[-1500:])
        cls.results = {x["label"]: x for x in json.loads(r.stdout)}

    def each(self, check):
        """kind ごとに subTest を開いて check(kind, 結果) を呼ぶ (片方の失敗でもう片方を止めない)。"""
        for kind in KINDS:
            with self.subTest(kind=kind):
                check(kind, self.results[kind])

    def test_nothing_is_executed(self):
        """読み込み・絞り込み・根拠リンク・「📄 詳細」「✨ 要約」の後も、悪意のあるスクリプトは1つも動いていない
        (window.__pwned_* が無い・alert が出ない・JS の構文エラーが無い)。"""
        def check(_kind, r):
            self.assertTrue(r["dash_ready"], "絞り込みボタンが描画されなかった (renderDashboards が動いていない)")
            self.assertTrue(r["ai_ready"], "「📄 詳細」「✨ 要約」の結果が表示されなかった (ボタンの JS が動いていない?)")
            self.assertEqual(r["after_load"]["pwned"], [], "読み込み時に動いた")
            self.assertEqual(r["pwned_end"], [], "操作の後に動いた")
            self.assertEqual(r["dialogs"], [], "alert などが出た")
            self.assertEqual(r["pageerrors"], [], "ページの JS でエラー (onclick の構文エラーなど)")
        self.each(check)

    def test_iframe_is_sandboxed_but_readable(self):
        """B1: iframe は sandbox (allow-scripts なし) で、本文のスクリプトは動かない。同じオリジンなので本文は読める。"""
        def check(_kind, r):
            frames = r["after_load"]["iframes"]
            self.assertTrue(r["iframe_ready"], "iframe の本文が読めなかった (allow-same-origin が無い?)")
            self.assertEqual(len(frames), 1)
            self.assertEqual(set((frames[0]["sandbox"] or "").split()), SANDBOX_TOKENS)
            self.assertIsNone(frames[0]["err"])
            self.assertIn("HTML本文です", frames[0]["text"] or "", "contentDocument が読めない (allow-same-origin が無い?)")
        self.each(check)

    def test_dashboard_filter_buttons(self):
        """B2: 分類・範囲・行動の絞り込みボタン: 表示は元の文字、data-v は元の値、押すとその値のカードだけが残る。"""
        def check(_kind, r):
            dash = r["after_load"]["dash"]
            self.assertEqual(len(dash), 1)
            self.assertEqual(dash[0]["others"], [], "ボタンの中に要素ができた")
            badges = {b["text"]: b["v"] for b in dash[0]["badges"]}
            filters = {f["text"]: f["shown"] for f in r["filters"]}
            for label, value in (("分類", B_CAT), ("範囲", B_SCOPE), ("行動", B_ACT),
                                 ("分類", "その他"), ("範囲", "横断業務"), ("行動", "通知・共有")):
                text = f"{label}: {value}"
                self.assertIn(text, badges, f"ボタンが無い/表示が元の文字でない: {text!r}")
                self.assertEqual(badges[text], value, "data-v が元の値でない")
                expected = [f"thread-body-{NAME}_T1"] if value in (B_CAT, B_SCOPE, B_ACT) else [f"thread-body-{NAME}_T2"]
                self.assertEqual(filters[text], expected, f"絞り込みが元の値で働かない: {text!r}")
        self.each(check)

    def test_jump_to_thread_args(self):
        """B2: 根拠リンクの jumpToThread の引数は、元の "<接頭辞>_<根拠ID>" (AI の根拠IDでも抜け出せない)。"""
        def check(_kind, r):
            self.assertEqual(r["jumps"], [f"{NAME}_T1", f"{NAME}_T2", f"{NAME}_{B_TID}"])
        self.each(check)

    def test_buttons_send_the_exact_topic_and_body(self):
        """「📄 詳細」「✨ 要約」のボタンは、元の件名 (\\r を除く)・元の本文 (data-original / HTML 本文の文字) を送る。"""
        def check(kind, r):
            reqs = r["requests"]
            detail = sorted((q["body"]["topic"], q["body"]["body"], q["body"]["target_type"])
                            for q in reqs if q["path"] == "/summarize_detail")
            single = sorted((q["body"]["topic"], q["body"]["body"]) for q in reqs if q["path"] == "/summarize_single")
            self.assertEqual([d[0] for d in detail], sorted([B_TOPIC1, B_TOPIC2]))
            self.assertEqual([s[0] for s in single], sorted([B_TOPIC1, B_TOPIC2]))
            self.assertEqual({d[2] for d in detail}, {kind})
            bodies = {d[0]: d[1] for d in detail}
            self.assertEqual(bodies[B_TOPIC1], B_BODY, "プレーンテキスト本文 (data-original) が元の文字でない")
            self.assertIn("HTML本文です", bodies[B_TOPIC2], "HTML 本文 (iframe) が読めていない")
            self.assertEqual(dict(single), bodies)
        self.each(check)

    def test_ai_results_are_shown_as_text(self):
        """M1: 「📄 詳細」「✨ 要約」の AI の結果は、タグとして解釈されず文字として表示される。"""
        def check(_kind, r):
            detail = {d["id"]: d for d in r["ai"]["detail"]}
            single = {d["id"]: d for d in r["ai"]["single"]}
            for tid in ("T1", "T2"):
                d = detail[f"detail-{NAME}_{tid}"]
                self.assertEqual(d["text"], "■ 要点" + "".join(B_POINTS) + "■ 推奨アクション" + "".join(B_ACTIONS))
                self.assertEqual(d["tags"], ["B", "UL", "LI", "LI", "B", "UL", "LI"], "AI の結果が要素になった")
                s = single[f"sum-{NAME}_{tid}_m0"]
                self.assertEqual(s["text"], "💡 " + B_SUMMARY)
                self.assertEqual(s["tags"], [], "AI の要約が要素になった")
        self.each(check)


# ============================================================
# 5. 範囲ガード (_11 → _12 で変えてよいのは、2つのレポート生成メソッドの決まった箇所・共通JSの決まった箇所と、関数2つの追加だけ)
# ============================================================
TWO_REPORTS = {"generate_project_report": "proj_prefix", "generate_staff_report": "staff_prefix"}
COMMON = "_get_common_js_and_css"
ALLOWED_TO_CHANGE = {f"HTMLReportGenerator.{n}" for n in list(TWO_REPORTS) + [COMMON]}
NEW_FUNCTIONS = {"report_text_html", "report_js_str_html"}
# 各メソッドで report_text_html に包まれる式 (仕様の箇所そのまま。1回ずつ)
TEXT_WRAPPED = Counter(["text", "icon", "imp", "a.get('owner')", "a.get('action')", "a.get('status', '')",
                        "m.get('sender_name')", "m.get('received')", "th.get('topic')", "th.get('summary')"])


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


def short_diff(a, b, limit=30):
    lines = list(difflib.unified_diff(a.splitlines(), b.splitlines(), "old", "new", lineterm="", n=1))
    return "\n".join(lines[:limit])


def _is_const_call(node, attr, args):
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == attr
            and not node.keywords and len(node.args) == len(args)
            and all(isinstance(a, ast.Constant) and a.value == v for a, v in zip(node.args, args)))


class _Splice(ast.AST):
    """f-string の {report_js_str_html(f"…")} を、中の f-string の部品に戻すための目印。"""
    _fields = ("inner",)


class _UndoA10(ast.NodeTransformer):
    """A10 (fix1 を含む) の変更を元に戻した AST を作る (比較用):
    report_text_html(x) → x、report_js_str_html(th.get("topic", "")) → 旧の .replace 2つ、
    {report_js_str_html(f"{prefix}_{tid}")} → {prefix}_{tid}、clean_text の最後の .replace('"','&quot;') を外す、
    iframe の sandbox 属性の文字を外す。戻した箇所を記録する (仕様の箇所だけが変わったことを確かめる)。"""

    def __init__(self):
        self.text_args, self.js_args, self.quot, self.sandbox = Counter(), Counter(), 0, 0

    def visit_Call(self, node):
        self.generic_visit(node)
        f = node.func
        if isinstance(f, ast.Name) and f.id == "report_text_html" and len(node.args) == 1 and not node.keywords:
            self.text_args[ast.unparse(node.args[0])] += 1
            return node.args[0]
        if isinstance(f, ast.Name) and f.id == "report_js_str_html" and len(node.args) == 1 and not node.keywords:
            arg = node.args[0]
            self.js_args[ast.unparse(arg)] += 1
            if isinstance(arg, ast.JoinedStr):
                return _Splice(inner=arg)
            inner = ast.Call(func=ast.Attribute(value=arg, attr="replace", ctx=ast.Load()),
                             args=[ast.Constant("'"), ast.Constant("\\'")], keywords=[])
            return ast.Call(func=ast.Attribute(value=inner, attr="replace", ctx=ast.Load()),
                            args=[ast.Constant('"'), ast.Constant("&quot;")], keywords=[])
        if _is_const_call(node, "replace", ('"', "&quot;")) and _is_const_call(f.value, "replace", (">", "&gt;")):
            self.quot += 1
            return f.value
        return node

    def visit_JoinedStr(self, node):
        self.generic_visit(node)
        values = []
        for v in node.values:
            if isinstance(v, ast.FormattedValue) and isinstance(v.value, _Splice):
                values.extend(v.value.inner.values)
            elif isinstance(v, ast.Constant) and isinstance(v.value, str) and SANDBOX_ATTR in v.value:
                self.sandbox += v.value.count(SANDBOX_ATTR)
                values.append(ast.Constant(v.value.replace(SANDBOX_ATTR, "")))
            else:
                values.append(v)
        merged = []
        for v in values:
            if merged and isinstance(v, ast.Constant) and isinstance(merged[-1], ast.Constant):
                merged[-1] = ast.Constant(merged[-1].value + v.value)
            else:
                merged.append(v)
        node.values = merged
        return node


def _unwrap_js_line(line):
    """共通JS の変更行を、fix1 の前の形に戻す (escHtml(x) → x、data-v 属性を外し this.dataset.v → '${v}')。"""
    line = line.replace(' data-v="${escHtml(v)}"', "").replace("this.dataset.v", "'${v}'")
    return re.sub(r"\$\{escHtml\(([^{}()]*)\)\}", r"${\1}", line)


class TestScopeGuardA10(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = _loader.rev_path(OLD_REV)
        cls.target = _loader.rev_path(NEW_REV)
        if not (os.path.isfile(cls.baseline) and os.path.isfile(cls.target)):
            raise unittest.SkipTest(f"A10 のリビジョン対 ({OLD_REV} / {NEW_REV}) が無い")
        cls.old = _index_source(cls.baseline)
        cls.new = _index_source(cls.target)

    def test_no_existing_function_is_removed(self):
        self.assertEqual(sorted(n for n in self.old[0] if n not in self.new[0]), [])

    def test_only_the_allowed_methods_changed(self):
        """変わった既存の関数は generate_project_report・generate_staff_report・_get_common_js_and_css だけ (3つとも変わっている)。"""
        old_f, new_f = self.old[0], self.new[0]
        changed = {n for n, s in old_f.items() if n in new_f and new_f[n] != s}
        self.assertEqual(sorted(changed - ALLOWED_TO_CHANGE), [], "許可されていない既存関数/メソッドの変更")
        self.assertEqual(sorted(ALLOWED_TO_CHANGE - changed), [], "A10 で変わるはずのメソッドが変わっていない")

    def test_only_two_module_functions_are_added(self):
        """追加は関数2つ (report_text_html・report_js_str_html。モジュール直下・引数は value) だけ。"""
        self.assertEqual({n for n in self.new[0] if n not in self.old[0]}, NEW_FUNCTIONS)
        for name in NEW_FUNCTIONS:
            node = [n for n in _parse(self.target).body if isinstance(n, ast.FunctionDef) and n.name == name]
            self.assertEqual(len(node), 1, f"{name} がモジュール直下に1つでない")
            args = node[0].args
            self.assertEqual([a.arg for a in args.posonlyargs + args.args], ["value"], name)
            self.assertEqual((args.vararg, args.kwarg, args.kwonlyargs, args.defaults), (None, None, [], []), name)

    def test_existing_constants_imports_and_other_statements_are_unchanged(self):
        old_c, new_c = self.old[1], self.new[1]
        self.assertEqual(sorted(n for n in new_c if n not in old_c), [], "定数が増えている")
        self.assertEqual(sorted(n for n in old_c if n not in new_c), [], "既存の定数が消えている")
        self.assertEqual(sorted(n for n, s in old_c.items() if n in new_c and new_c[n] != s), [], "既存の定数が変わっている")
        self.assertEqual(self.old[2], self.new[2], "import が変わっている")
        self.assertEqual(self.old[3], self.new[3], "関数/定数/import 以外のトップレベル文が変わっている")
        self.assertEqual(self.old[4], self.new[4], "クラスの骨格 (クラスの増減・継承・クラス直下の文) が変わっている")

    def test_each_report_changed_only_at_the_specified_places(self):
        """2つのメソッドは、A10 の変更 (仕様の10か所の report_text_html・件名と根拠IDの report_js_str_html・clean_text の "
        の処理・iframe の sandbox) を元に戻すと _11 と同じ。包まれた式は仕様の箇所そのもの (1回ずつ)。
        字数超過の判定はエスケープ前の text のまま。"""
        for name, prefix in TWO_REPORTS.items():
            with self.subTest(method=name):
                old_fn = method_node(self.baseline, "HTMLReportGenerator", name)
                new_fn = method_node(self.target, "HTMLReportGenerator", name)
                names_old = {n.id for n in ast.walk(old_fn) if isinstance(n, ast.Name)}
                self.assertFalse(names_old & NEW_FUNCTIONS, "前提: 比較元 (_11) に A10 の名前がある")
                self.assertNotIn("sandbox", ast.unparse(old_fn), "前提: 比較元 (_11) に sandbox がある")
                undo = _UndoA10()
                stripped = undo.visit(copy.deepcopy(new_fn))
                self.assertEqual(undo.text_args, TEXT_WRAPPED, "report_text_html で包んだ式が仕様の箇所と違う")
                self.assertEqual(undo.js_args, Counter(["th.get('topic', '')", f"f'{{{prefix}}}_{{tid}}'"]),
                                 "report_js_str_html で包んだ式が仕様の箇所と違う")
                self.assertEqual(undo.quot, 1, "clean_text の .replace('\"','&quot;') が1回でない")
                self.assertEqual(undo.sandbox, 1, "iframe の sandbox 属性が1回でない")
                badge_calls = [c for c in ast.walk(new_fn) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                               and c.func.id == "over_length_badge_html"]
                self.assertEqual([ast.unparse(c.args[0]) for c in badge_calls], ["text"],
                                 "字数超過の判定がエスケープ前の text でない")
                self.assertEqual(ast.dump(stripped), ast.dump(old_fn),
                                 "仕様の箇所以外の変更がある\n" + short_diff(ast.unparse(old_fn), ast.unparse(stripped)))

    def test_common_js_changed_only_at_the_specified_places(self):
        """共通JS は、escHtml の追加 (コメント・空行を除くと関数の定義だけ) と、3行 (「📄 詳細」「✨ 要約」の innerHTML・
        絞り込みボタンの b) の置き換えだけ。置き換えた行は escHtml・data-v・this.dataset.v を戻すと _11 の行と同じ。
        メソッドの他の部分は同じ。"""
        old_fn = method_node(self.baseline, "HTMLReportGenerator", COMMON)
        new_fn = method_node(self.target, "HTMLReportGenerator", COMMON)
        rets = []
        for fn in (old_fn, new_fn):
            r = [n for n in fn.body if isinstance(n, ast.Return)]
            self.assertEqual(len(r), 1)
            self.assertIsInstance(r[0].value, ast.Constant)
            rets.append(r[0].value.value)
        old_js, new_js = rets
        same = copy.deepcopy(new_fn)
        [n for n in same.body if isinstance(n, ast.Return)][0].value.value = old_js
        self.assertEqual(ast.dump(same), ast.dump(old_fn), "共通JS の文字列以外が変わっている")
        a, b = old_js.split("\n"), new_js.split("\n")
        replaced, inserted, deleted = [], [], []
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
            if tag == "replace":
                self.assertEqual(i2 - i1, j2 - j1, f"行の置き換えが1対1でない: {a[i1:i2]} → {b[j1:j2]}")
                replaced += list(zip(a[i1:i2], b[j1:j2]))
            elif tag == "insert":
                inserted += b[j1:j2]
            elif tag == "delete":
                deleted += a[i1:i2]
        self.assertEqual(deleted, [], "消された行がある")
        code = [l.strip() for l in inserted if l.strip() and not l.strip().startswith("//")]
        self.assertEqual(len(code), 3, f"足された行が escHtml の定義だけでない: {code}")
        self.assertEqual(code[0], "function escHtml(s) {")
        self.assertTrue(code[1].startswith("return ") and code[1].endswith(";"), code[1])
        self.assertEqual(code[2], "}")
        self.assertEqual(len(replaced), 3, f"置き換えた行が3行でない: {replaced}")
        kinds = []
        for old_line, new_line in replaced:
            self.assertEqual(_unwrap_js_line(new_line), old_line, f"置き換えの中身が仕様と違う:\n{old_line}\n{new_line}")
            kinds.append("detail" if "data.points" in new_line else "single" if "data.summary" in new_line
                         else "b" if "const b =" in new_line else new_line)
        self.assertEqual(sorted(kinds), ["b", "detail", "single"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
