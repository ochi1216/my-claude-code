# -*- coding: utf-8 -*-
"""A10b「他のレポートの、メール・AI 由来の文字列のエスケープ漏れと iframe の制限」テスト
(仕様書 A10B_SPEC.md。前提は A10_SPEC.md の report_text_html / report_js_str_html)。

仕様書だけを根拠に書いている (レポートへの入力の形は、変更前の _14 と既存テストに合わせた)。
  - 仕様に明記された挙動            -> 通常の TestCase
  - 仕様が曖昧/未記載で「最も自然な解釈」で書いたもの -> クラス名に SpecGap を含む

構成
  1. 検索レポート (generate_report → _build_html → _card。通常のカードと RSS のカードを1つのレポートに入れる):
     悪意のある値 (件名・差出人名・受信日時・本文・添付ファイル名・AI 要約・アクション・RSS のタイトル/要旨/
     キーワード/結論/ポイント・記事の URL) を入れて html.parser で解析し、特殊文字の無い値のときとタグ・属性の
     並びが同じ・文字はそのまま表示・javascript: などのリンクが出ない・iframe に sandbox (allow-scripts 無し)
  2. 検索レポートの独自スクリプト: escHtml の追加・autoLink が displayUrl を escHtml (node があれば実際に実行)
  3. 振り返り: achievement_id (' や \\ を含む) の JS の引数が元の値に戻る・抜け出せない (Python で JS の文字列を
     読む。node の acorn があれば本物の JS パーサでも)。手動追加・上書きのランクに "><script> を入れてもタグが増えない
  4. エラー時の文 (俯瞰2画面・統括コックピット v1)・アクション一覧の data-* 属性 (action_status.json 経由)
  5. 共通JS の regenerateQuestions が escHtml を通す・俯瞰2画面に marked の外部スクリプトが無い
  6. ブラウザ (Chromium を node の playwright で動かす。無ければ skip): 開いただけ・翻訳 (セーフリンクの URL に
     <img onerror> を入れた結果)・ボタン操作で、注入したコードが動かない・送る ID が元の値・iframe の中の
     スクリプトは動かないが翻訳はできる (allow-same-origin)・俯瞰2画面が外部へ読みに行かず JS エラーも無い
  7. 範囲ガード (_14 と _15 をファイル名で指定): AST で、変わった既存の関数は仕様の一覧だけ・それぞれ仕様の
     変更を元に戻すと _14 と同じ・追加の名前は無し。特殊文字の無い入力では _14 と同じ出力
     (外した script タグと、仕様で変えた JS の行・iframe の sandbox 属性を除く)

変異テスト: 実装のコピーに誤りを1つ入れ、OTO_TARGET でその版を指してこのファイルだけを走らせる。
    OTO_TARGET=/path/to/壊した版.py xvfb-run -a /usr/bin/python3.12 tests/run_tests.py a10b_reports_escape
(7 の範囲ガードは常に tool フォルダの _14 / _15 を比べるので、変異版では変わらない)

ブラウザ・node の場所は既定で自動検出 (PATH の node・/opt/node-tools/node_modules・/opt/pw-browsers/chromium)。
環境変数 OTO_NODE_MODULES (node_modules のフォルダ。複数は os.pathsep 区切り)・OTO_CHROMIUM (実行ファイル) で指定できる。
"""
import ast
import collections
import contextlib
import difflib
import functools
import html as html_mod
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from html.parser import HTMLParser
from unittest import mock

import _loader
from _loader import tempdir_cwd


def oto():
    return _loader.load()


PORT = 8765
SANDBOX_TOKENS = frozenset({"allow-same-origin", "allow-popups", "allow-popups-to-escape-sandbox", "allow-downloads"})
SANDBOX_ATTR = ' sandbox="allow-same-origin allow-popups allow-popups-to-escape-sandbox allow-downloads"'
MARKED_SRC = "https://cdn.jsdelivr.net/npm/marked/marked.min.js"
RSS_FOLDER = "RSS フィード"
ARTICLE_LINK_TEXT = "🌐 記事の表示"


# ============================================================
# HTML の読み取り (標準ライブラリの HTMLParser で小さな木を作る)
# ============================================================
class Node:
    def __init__(self, tag, attrs, parent):
        self.tag, self.parent, self.children = tag, parent, []
        self.attr_list = list(attrs)                 # 重複した属性も数えられるように、並びのまま持つ
        self.attrs = dict(attrs)

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


def skeleton(root):
    """要素の並び (タグ名と属性名の並び)。値は含めない。悪意のある値でこれが変わったら、タグか属性が増えている。"""
    return [(n.tag, tuple(k for k, _ in n.attr_list)) for n in root.iter() if n is not root]


def skeleton_diff(a, b, limit=12):
    lines = list(difflib.unified_diff([repr(x) for x in a], [repr(x) for x in b], "特殊文字なし", "悪意のある値",
                                      lineterm="", n=1))
    return "\n".join(lines[:limit])


def visible_text(node):
    """表示される文字 (script・style の中身を除いた文字の連結。実体参照は解釈済み)。"""
    out = []

    def rec(n):
        for c in n.children:
            if isinstance(c, str):
                out.append(c)
            elif c.tag not in ("script", "style"):
                rec(c)
    rec(node)
    return "".join(out)


def find(root, tag=None, cls=None, pred=None):
    return [n for n in root.iter() if n is not root and (tag is None or n.tag == tag)
            and (cls is None or cls in n.classes) and (pred is None or pred(n))]


def scripts_of(root):
    return [n for n in root.iter() if n.tag == "script"]


_URL_ATTRS = ("href", "src", "action", "formaction", "xlink:href", "srcdoc_url", "data")
_BAD_SCHEMES = ("javascript:", "vbscript:", "data:")


def url_scheme_of(value):
    """ブラウザと同じく、前後の空白・制御文字と中のタブ・改行を除いて小文字にした値。"""
    v = "".join(ch for ch in (value or "") if ch not in "\t\n\r")
    return v.strip(" \x00\x01\x02\x03\x04\x05\x06\x07\x08\x0b\x0c\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17"
                   "\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f").lower()


def bad_urls(root):
    out = []
    for n in root.iter():
        for k, v in n.attr_list:
            if k in _URL_ATTRS and url_scheme_of(v).startswith(_BAD_SCHEMES):
                out.append((n.tag, k, v))
    return out


def js_function_source(script, name):
    """script の中の function name(...) { ... } を取り出す (括弧の対応で終わりを探す)。"""
    m = re.search(r"(?:async\s+)?function\s+" + re.escape(name) + r"\s*\(", script)
    if not m:
        return None
    i = script.index("{", m.end())
    depth = 0
    for j in range(i, len(script)):
        if script[j] == "{":
            depth += 1
        elif script[j] == "}":
            depth -= 1
            if depth == 0:
                return script[m.start():j + 1]
    return None


# ============================================================
# JS の '…' 文字列を読む (onclick などの属性の中身を、ブラウザが属性を読んだ後の形で調べる)
# ============================================================
_JS_STR = r"'((?:[^'\\\r\n]|\\[\s\S])*)'"
_JS_SIMPLE_ESC = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}


def js_unescape(s):
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
        n = s[i + 1]
        if n in _JS_SIMPLE_ESC:
            out.append(_JS_SIMPLE_ESC[n])
            i += 2
        elif n == "x":
            out.append(chr(int(s[i + 2:i + 4], 16)))
            i += 4
        elif n == "u" and s[i + 2:i + 3] == "{":
            j = s.index("}", i)
            out.append(chr(int(s[i + 3:j], 16)))
            i = j + 1
        elif n == "u":
            out.append(chr(int(s[i + 2:i + 6], 16)))
            i += 6
        elif n in "\r\n\u2028\u2029":              # 行継続
            i += 2
        else:
            out.append(n)
            i += 2
    return "".join(out)


def parse_js_call(src, fn):
    """src が「fn(this, '…', 数字)」だけのとき (文字列の値, 数字) を返す。それ以外 (抜け出した等) は None。"""
    m = re.fullmatch(re.escape(fn) + r"\(this, " + _JS_STR + r", (\d+)\)", src)
    if not m:
        return None
    return js_unescape(m.group(1)), int(m.group(2))


# ============================================================
# node・ブラウザ (無ければ skip)
# ============================================================
def node_exe():
    return shutil.which("node")


def node_module_dirs():
    dirs = []
    env = os.environ.get("OTO_NODE_MODULES", "").strip()
    if env:
        dirs += env.split(os.pathsep)
    dirs.append("/opt/node-tools/node_modules")
    n = node_exe()
    if n:
        dirs.append(os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(n))), "lib", "node_modules"))
    return [d for d in dirs if d and os.path.isdir(d)]


def chromium_path():
    env = os.environ.get("OTO_CHROMIUM", "").strip()
    for cand in (env, "/opt/pw-browsers/chromium"):
        if cand and os.path.exists(cand):
            return cand
    return None


def run_node(js_code, stdin_obj=None, timeout=240):
    exe = node_exe()
    if not exe:
        raise unittest.SkipTest("node が無い環境: JS を実行する確認は対象外")
    with tempfile.TemporaryDirectory(prefix="oto_a10b_js_") as d:
        p = os.path.join(d, "t.js")
        with open(p, "w", encoding="utf-8") as f:
            f.write(js_code)
        env = dict(os.environ, NODE_PATH=os.pathsep.join(node_module_dirs()))
        r = subprocess.run([exe, p], input=json.dumps(stdin_obj if stdin_obj is not None else {}),
                           capture_output=True, text=True, encoding="utf-8", timeout=timeout, env=env)
    if r.returncode != 0:
        raise AssertionError(f"node が失敗した (終了コード {r.returncode}): {r.stderr[-1500:]}")
    lines = [ln for ln in r.stdout.split("\n") if ln.strip()]      # splitlines は U+2028 でも分けるので使わない
    if not lines:
        raise AssertionError(f"node の出力が無い: {r.stderr[-1500:]}")
    out = json.loads(lines[-1])
    if isinstance(out, dict) and out.get("__missing__"):
        raise unittest.SkipTest(f"{out['__missing__']} が無い環境: この確認は対象外")
    return out


SEARCH_SCRIPT_HARNESS = r"""
const vm = require('vm');
const fs = require('fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const noop = () => {};
const sb = {console, URL, URLSearchParams, setTimeout, clearTimeout, JSON, alert: noop, addEventListener: noop,
  document: {addEventListener: noop, getElementById: () => null, querySelectorAll: () => [], querySelector: () => null}};
sb.window = sb;
vm.createContext(sb);
vm.runInContext(input.script, sb);
const out = {hasEsc: typeof sb.escHtml === 'function', hasAutoLink: typeof sb.autoLink === 'function'};
out.esc = out.hasEsc ? input.esc.map(s => sb.escHtml(s === '__undefined__' ? undefined : s)) : null;
// 翻訳結果の表示 (translateText と同じく、& < > " を実体参照にしてから autoLink に渡す)
out.link = out.hasAutoLink ? input.link.map(t => sb.autoLink(
  t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'))) : null;
console.log(JSON.stringify(out));
"""

COMMON_JS_HARNESS = r"""
const vm = require('vm');
const fs = require('fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const noop = () => {};
const qlist = {children: [], appendChild(c) { this.children.push(c); }, querySelectorAll: () => []};
const sb = {console, URL, URLSearchParams, setTimeout, clearTimeout, JSON, alert: noop, addEventListener: noop,
  document: {
    addEventListener: noop, querySelectorAll: () => [], querySelector: () => null,
    getElementById: id => id === 'qlist-TQ' ? qlist : (id === 'ctx-TQ' ? {textContent: 'ctx'} : null),
    createElement: tag => ({tagName: String(tag).toUpperCase(), style: {}, innerHTML: '', textContent: ''}),
  },
  fetch: async () => ({ok: true, status: 200, json: async () => ({new_questions: input.questions})}),
};
sb.window = sb;
vm.createContext(sb);
vm.runInContext(input.script, sb);
(async () => {
  if (typeof sb.regenerateQuestions !== 'function') { console.log(JSON.stringify({error: 'regenerateQuestions が無い'})); return; }
  await sb.regenerateQuestions('TQ', 'Caracal', 8765, {disabled: false, textContent: 'btn'});
  console.log(JSON.stringify({items: qlist.children.map(li => li.innerHTML)}));
})().catch(e => console.log(JSON.stringify({error: String(e && e.stack || e)})));
"""

ACORN_HARNESS = r"""
const fs = require('fs');
let acorn = null;
try { acorn = require('acorn'); } catch (e) {}
if (!acorn) { console.log(JSON.stringify({__missing__: 'acorn (node の JS パーサ)'})); process.exit(0); }
const srcs = JSON.parse(fs.readFileSync(0, 'utf8'));
const lit = a => a.type === 'Literal' ? {type: 'Literal', value: a.value} : {type: a.type};
console.log(JSON.stringify(srcs.map(src => {
  try {
    const prog = acorn.parse(src, {ecmaVersion: 'latest', sourceType: 'script'});
    return {ok: true, body: prog.body.map(st => (st.type === 'ExpressionStatement' && st.expression.type === 'CallExpression')
      ? {type: 'Call', callee: st.expression.callee.type === 'Identifier' ? st.expression.callee.name : st.expression.callee.type,
         args: st.expression.arguments.map(lit)}
      : {type: st.type})};
  } catch (e) { return {ok: false, error: String(e && e.message || e)}; }
})));
"""

BROWSER_RUNNER = r"""
const fs = require('fs');
const { pathToFileURL } = require('url');
const plan = JSON.parse(fs.readFileSync(0, 'utf8'));
function load(name) { try { return require(name); } catch (e) { return null; } }
(async () => {
  const pw = load('playwright') || load('playwright-core');
  if (!pw) { console.log(JSON.stringify({__missing__: 'playwright (node)'})); return; }
  const opts = {};
  if (plan.executable) opts.executablePath = plan.executable;
  let browser;
  try { browser = await pw.chromium.launch(opts); }
  catch (e) { console.log(JSON.stringify({__missing__: 'Chromium (' + String(e && e.message || e).slice(0, 200) + ')'})); return; }
  const results = {};
  try {
    for (const sc of plan.scenarios) {
      const context = await browser.newContext();
      await context.route(/^https?:\/\//, r => r.abort());
      const page = await context.newPage();
      const rec = {dialogs: [], errors: [], requests: []};
      page.on('dialog', d => { rec.dialogs.push(d.message()); d.dismiss().catch(() => {}); });
      page.on('pageerror', e => rec.errors.push(String(e && e.message || e)));
      page.on('request', r => rec.requests.push(r.url()));
      await page.addInitScript(fake => {
        window.__pwn = [];
        window.P = k => { window.__pwn.push(String(k)); };
        window.__fetches = [];
        window.fetch = async (url, init) => {
          window.__fetches.push({url: String(url), body: init && init.body != null ? String(init.body) : null});
          let payload = {};
          for (const [k, v] of fake) { if (String(url).includes(k)) { payload = v; break; } }
          return new Response(JSON.stringify(payload), {status: 200, headers: {'Content-Type': 'application/json'}});
        };
      }, sc.fake || []);
      try {
        await page.goto(pathToFileURL(sc.file).href, {waitUntil: 'load'});
        await page.waitForTimeout(sc.settle || 500);
        rec.out = sc.script ? await page.evaluate('(async () => {\n' + sc.script + '\n})()') : null;
        await page.waitForTimeout(sc.after || 400);
        rec.pwn = await page.evaluate(() => window.__pwn);
        rec.fetches = await page.evaluate(() => window.__fetches);
      } catch (e) { rec.fatal = String(e && e.stack || e).slice(0, 1500); }
      results[sc.name] = rec;
      await context.close();
    }
  } finally { await browser.close(); }
  console.log(JSON.stringify(results));
})().catch(e => console.log(JSON.stringify({__fatal__: String(e && e.stack || e)})));
"""


def run_browser(scenarios):
    plan = {"executable": chromium_path(), "scenarios": scenarios}
    res = run_node(BROWSER_RUNNER, plan, timeout=420)
    if "__fatal__" in res:
        raise AssertionError("ブラウザの実行に失敗: " + res["__fatal__"][:1500])
    return res


# ============================================================
# 悪意のある値・特殊文字の無い値
# ============================================================
def evil(tag):
    """タグ・属性・スクリプトの注入と、引用符・実体参照の文字そのもの (&lt;b&gt;) を含む値。先頭は識別用の 〔tag〕。"""
    return (f"〔{tag}〕<img src=x onerror=\"P('{tag}')\"><script>P('{tag}-s')</script>"
            f"\"><svg onload=P('{tag}-v')>' onmouseover='P(1)' &lt;b&gt;&amp; & é")


def plain(tag):
    """HTML の特殊文字を含まない値 (同じ識別用の 〔tag〕)。"""
    return f"〔{tag}〕通常の文です {tag}"


HTML_BODY_PLAIN = "<html><body><p>Hello world</p><p>Second line</p><a href=\"https://example.com/\">link</a></body></html>"
HTML_BODY_EVIL = ("<html><body><p>Hello world</p><p>Second line</p><a href=\"https://example.com/\">link</a>"
                  "<script>parent.P('ifr-script')</script><img src=x onerror=\"parent.P('ifr-img')\"></body></html>")
URL_PLAIN = "https://example.com/news/〔url〕"
URL_EVIL = "https://evil.example/〔url〕\"><img src=x onerror=\"P('url')\">' onmouseover='P(2)"
SAFELINK_PAYLOAD = "https://x.safelinks.protection.outlook.com/?url=%3Cimg%20src%3Dx%20onerror%3Dalert(1)%3E"


def search_inputs(v, url, html_body, body2_head="〔body2〕1行目\n"):
    """検索レポートへの入力 (threads, summaries)。通常のスレッド1件 (メール3通。HTML本文の iframe あり) と
    RSS のスレッド2件 (1件は題名・記事のリンクあり、1件は題名なし→件名を表示・HTML本文の iframe あり)。"""
    threads = {
        "CID-N": {"topic": v("topic"), "mail_count": 3, "latest_entry_id": "EN3", "mails": [
            {"entry_id": "EN1", "sender_name": v("sender1"), "received": v("recv1"), "body": v("body1"),
             "html_body": "", "attachment_names": [v("att1"), v("att2")], "folder": "受信トレイ"},
            {"entry_id": "EN2", "sender_name": v("sender2"), "received": datetime(2026, 10, 1, 9, 30),
             "body": body2_head + v("body2"), "html_body": "", "attachment_names": [], "folder": "受信トレイ"},
            {"entry_id": "EN3", "sender_name": v("sender3"), "received": "2026-10-02 10:00", "body": "plain body",
             "html_body": html_body, "inline_images": {}, "attachment_names": [v("att3")], "folder": "受信トレイ"},
        ]},
        "CID-R": {"topic": v("rsstopic"), "mail_count": 1, "latest_entry_id": "ER1", "mails": [
            {"entry_id": "ER1", "sender_name": v("feed"), "received": v("recvR"), "body": v("rssbody"),
             "html_body": "", "folder": RSS_FOLDER}]},
        "CID-R2": {"topic": v("rsstopic2"), "mail_count": 1, "latest_entry_id": "ER2", "mails": [
            {"entry_id": "ER2", "sender_name": "feed2", "received": "2026-10-03 08:00", "body": "rss body 2",
             "html_body": html_body, "inline_images": {}, "folder": RSS_FOLDER}]},
    }
    summaries = {
        "CID-N": {"summary": v("summary"), "mail_summaries": [v("msum1"), "", "(生成失敗)"],
                  "action_items": [{"priority": v("prio"), "action": v("act"), "owner": v("owner"), "deadline": v("dl")},
                                   {"priority": "高", "action": v("act2")}]},
        "CID-R": {"is_rss": True, "title": v("rsstitle"), "summary": v("rsssum"), "keywords": v("kw"),
                  "conclusion": v("concl"), "article_url": url,
                  "main_points": [{"point_title": v("pt1"), "description": v("pd1")},
                                  {"point_title": v("pt2"), "description": v("pd2")}]},
        "CID-R2": {"is_rss": True, "summary": v("rsssum2"), "keywords": v("kw2"), "conclusion": v("concl2"),
                   "main_points": []},
    }
    return threads, summaries


def render_search(mod, threads, summaries, out_dir):
    """generate_report で書かせて読む (out_dir は1回ごとに新しいフォルダ: 同じ秒のファイル名の衝突を避ける)。"""
    os.makedirs(out_dir, exist_ok=True)
    gen = mod.HTMLReportGenerator(out_dir, PORT)
    with contextlib.redirect_stdout(io.StringIO()), mock.patch("tkinter.messagebox.showwarning", create=True):
        path = gen.generate_report(threads, summaries, {})
    assert path and os.path.isfile(path), f"検索レポートが出力されなかった: {path!r}"
    assert os.path.dirname(os.path.abspath(path)) == os.path.abspath(out_dir), path
    with open(path, "r", encoding="utf-8", newline="") as f:
        return f.read()


class TmpDirClassMixin:
    """クラス単位で一時 cwd を用意する (json/ などは相対パス)。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cm = tempdir_cwd()
        cls.tmp = cm.__enter__()
        cls.addClassCleanup(cm.__exit__, None, None, None)
        out = io.StringIO()
        cm2 = contextlib.redirect_stdout(out)
        cm2.__enter__()
        cls.addClassCleanup(cm2.__exit__, None, None, None)

    @classmethod
    def new_dir(cls):
        return tempfile.mkdtemp(dir=cls.tmp)


def read_path(path, label):
    assert path, f"{label}: HTML が出力されなかった (空のパスが返った)"
    with open(path, "r", encoding="utf-8", newline="") as f:
        return f.read()


# ============================================================
# 1. 検索レポート (_card)
# ============================================================
TEXT_FIELDS = ("topic", "sender1", "sender2", "sender3", "recv1", "att1", "att2", "att3", "msum1", "summary", "prio",
               "act", "owner", "dl", "act2", "rsstitle", "rsssum", "kw", "concl", "pt1", "pd1", "pt2", "pd2", "feed",
               "recvR", "rsstopic2", "rsssum2", "kw2", "concl2", "body1", "rssbody")


class TestSearchReport(TmpDirClassMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        mod = oto()
        cls.html_plain = render_search(mod, *search_inputs(plain, URL_PLAIN, HTML_BODY_PLAIN), cls.new_dir())
        cls.html_evil = render_search(mod, *search_inputs(evil, URL_EVIL, HTML_BODY_EVIL), cls.new_dir())
        cls.root_plain = parse_html(cls.html_plain)
        cls.root_evil = parse_html(cls.html_evil)

    def test_no_tags_or_attributes_are_added(self):
        """悪意のある値にしても、要素 (タグ) と属性の並びが特殊文字の無い値のときと同じ (通常・RSS のカードとも)。"""
        a, b = skeleton(self.root_plain), skeleton(self.root_evil)
        self.assertEqual(a, b, "タグか属性が増えた/変わった\n" + skeleton_diff(a, b))
        self.assertEqual(len(find(self.root_evil, cls="thread-card")), 3, "前提: カードが3枚 (通常1・RSS 2)")

    def test_no_injected_elements_or_handlers(self):
        """img・svg・script (レポート自身の script を除く) が無く、onerror・onload・onmouseover の属性も無い。"""
        tags = collections.Counter(n.tag for n in self.root_evil.iter())
        self.assertEqual((tags["img"], tags["svg"]), (0, 0))
        self.assertEqual(tags["script"], len(scripts_of(self.root_plain)))
        attrs = {k for n in self.root_evil.iter() for k, _ in n.attr_list}
        self.assertFalse(attrs & {"onerror", "onload", "onmouseover", "onfocus", "autofocus"}, attrs)

    def test_every_field_is_shown_as_the_literal_text(self):
        """各項目は、そのままの文字として表示される (エスケープは表示の文字を変えない。&lt; などの文字そのものも二重に解釈されない)。"""
        text = visible_text(self.root_evil)
        for f in TEXT_FIELDS:
            with self.subTest(field=f):
                self.assertIn(evil(f), text)

    def test_fields_are_in_their_places(self):
        """件名・差出人名・受信日時・添付・AI要約・要約・アクション・RSS の各欄が、それぞれの要素の文字として出る。"""
        r = self.root_evil
        titles = [n.text() for n in find(r, cls="t-title")]
        self.assertEqual(titles[0], evil("topic") + " 3件")
        self.assertEqual(titles[1], "📰 " + evil("rsstitle"))
        self.assertEqual(titles[2], "📰 " + evil("rsstopic2"), "RSS の題名が無いときは件名 (同じくエスケープ)")
        heads = find(r, cls="m-head")
        self.assertTrue(heads[0].text().startswith(evil("sender1") + " " + evil("recv1")), heads[0].text()[:80])
        self.assertTrue(heads[1].text().startswith(evil("sender2") + " 2026-10-01 09:30:00"), heads[1].text()[:80])
        sums = [n.text() for n in find(r, cls="m-sum")]
        self.assertEqual(sums[0], "💡 " + evil("msum1"))
        self.assertEqual(sums[1], ("〔body2〕1行目\n" + evil("body2"))[:80].replace("\n", " ") + "...")
        self.assertEqual(sums[2], "plain body...", "「(生成失敗)」のときは本文の先頭")
        atts = [n.text() for n in find(r, tag="div") if n.text().startswith("📎 添付ファイル: ")]
        self.assertIn("📎 添付ファイル: " + evil("att1") + ", " + evil("att2"), atts)
        self.assertIn("📎 添付ファイル: " + evil("att3"), atts)
        boxes = [n.text() for n in find(r, cls="sum-box")]
        for f in ("summary", "rsssum", "concl", "rsssum2", "concl2"):
            self.assertIn(evil(f), boxes, f)
        acts = find(r, cls="act-item")
        self.assertEqual(acts[0].text(), f"[{evil('prio')}]{evil('act')}担当:{evil('owner')} 期限:{evil('dl')}")
        self.assertEqual(acts[1].text(), f"[高]{evil('act2')}担当:None 期限:None", "無い項目は従来どおり None")
        self.assertIn("act-high", acts[1].classes)
        points = [n.text() for n in find(r, tag="b")]
        self.assertIn(evil("pt1"), points)
        self.assertIn(evil("pt2"), points)

    def test_body_head_is_cut_before_escaping(self):
        """本文の先頭80字は、エスケープの前に切る (実体参照の途中で切れない。表示は元の文の80字)。"""
        mod = oto()
        for body in ("a" * 79 + "<b>xyz", "a" * 78 + "&amp;rest", "b" * 77 + "\"'<>&", "改\n行" + "c" * 76 + "<<"):
            with self.subTest(body=body[-12:]):
                threads = {"C": {"topic": "t", "mail_count": 1, "latest_entry_id": "E", "mails": [
                    {"entry_id": "E", "sender_name": "s", "received": "r", "body": body, "html_body": ""}]}}
                root = parse_html(render_search(mod, threads, {"C": {}}, self.new_dir()))
                self.assertEqual([n.text() for n in find(root, cls="m-sum")], [body[:80].replace("\n", " ") + "..."])

    def test_iframe_has_the_sandbox_without_allow_scripts(self):
        """HTML 本文の iframe (通常・RSS のカードとも) に sandbox。値は A10 と同じ4つ (allow-scripts は無い)。"""
        iframes = find(self.root_evil, tag="iframe")
        self.assertEqual(len(iframes), 2, "前提: HTML 本文の iframe が2つ")
        for f in iframes:
            with self.subTest(iframe=f.attrs.get("id")):
                self.assertIn("sandbox", f.attrs)
                tokens = f.attrs["sandbox"].split()
                self.assertEqual(set(tokens), SANDBOX_TOKENS)
                self.assertEqual(len(tokens), len(set(tokens)))
                self.assertNotIn("allow-scripts", tokens)
                self.assertEqual([k for k, _ in f.attr_list].count("sandbox"), 1)

    def test_iframe_body_stays_inside_srcdoc(self):
        """iframe の srcdoc は従来どおりエスケープされ、本文の HTML (script など) は外側の文書の要素にならない。"""
        f = [n for n in find(self.root_evil, tag="iframe") if n.attrs.get("id") == "iframe-EN3"][0]
        self.assertEqual(f.attrs.get("srcdoc"), HTML_BODY_EVIL)
        self.assertEqual(f.elements(), [])

    def test_article_link_keeps_the_url_in_the_attribute(self):
        """記事のリンク (https で始まり " や ' を含む) は表示され、href はその URL そのもの (属性を抜けない)。"""
        links = [n for n in find(self.root_evil, tag="a") if n.text() == ARTICLE_LINK_TEXT]
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].attrs.get("href"), URL_EVIL)
        self.assertEqual([k for k, _ in links[0].attr_list], ["href", "target", "class"])

    def test_no_javascript_or_data_urls(self):
        """文書のどこにも javascript: / vbscript: / data: の URL の属性が無い。"""
        self.assertEqual(bad_urls(self.root_evil), [])

    def test_search_report_script_is_unchanged_by_the_values(self):
        """レポート自身の script の中身は、値によって変わらない (値は script に入らない)。"""
        a = [n.text() for n in scripts_of(self.root_plain)]
        b = [n.text() for n in scripts_of(self.root_evil)]
        self.assertEqual(a, b)


ARTICLE_SHOWN = (
    "http://example.com/a",
    "https://example.com/a?b=1&c=2",
    "https://evil.example/\"><img src=x onerror=P(1)>",
    "https://e.example/' onmouseover='P(1)",
    "https://e.example/\" autofocus onfocus=\"P(1)",
    "https://e.example/<script>P(1)</script>",
    "http://",
)
ARTICLE_HIDDEN = (
    None, "", "javascript:alert(1)", "JavaScript:alert(1)", "JAVASCRIPT:alert(1)", " javascript:alert(1)",
    "\tjavascript:alert(1)", "\njavascript:alert(1)", "java\tscript:alert(1)", "java\nscript:alert(1)",
    "javascript&colon;alert(1)", "&#106;avascript:alert(1)", "data:text/html,<script>alert(1)</script>",
    "vbscript:msgbox(1)", "//evil.example/x", "evil.example/x", "ftp://example.com/x", "file:///C:/x",
    "https:/\\evil.example", "https:javascript:alert(1)", "http:", " https://example.com/x",
    "\u200bhttps://example.com/x", "javascript:alert('http://x')", "javascript://%0Aalert(1)",
    "data:text/html,https://example.com", 12345, ["https://example.com/x"], {"u": "https://example.com/x"}, True,
)


def render_rss_urls(mod, urls, out_dir):
    """記事の URL だけを変えた RSS のカードを並べたレポート。{i: [記事のリンクの a 要素]} を返す。"""
    threads, summaries = {}, {}
    for i, u in enumerate(urls):
        cid = f"R{i}"
        threads[cid] = {"topic": f"t{i}", "mail_count": 1, "latest_entry_id": f"E{i}", "mails": [
            {"entry_id": f"E{i}", "sender_name": "feed", "received": "r", "body": "b", "html_body": "",
             "folder": RSS_FOLDER}]}
        summaries[cid] = {"is_rss": True, "title": f"title{i}", "summary": "s", "keywords": "k", "conclusion": "c",
                          "main_points": [], "article_url": u}
    threads["N"] = {"topic": "n", "mail_count": 1, "latest_entry_id": "EN", "mails": [
        {"entry_id": "EN", "sender_name": "s", "received": "r", "body": "b", "html_body": ""}]}   # RSS だけにしない
    root = parse_html(render_search(mod, threads, summaries, out_dir))
    out = {}
    for card in find(root, cls="thread-card"):
        idx = int(card.attrs["id"].split("-")[1]) - 1
        out[idx] = [n for n in find(card, tag="a") if n.text() == ARTICLE_LINK_TEXT]
    return root, out


class TestArticleUrl(TmpDirClassMixin, unittest.TestCase):
    def test_http_and_https_urls_are_linked_with_the_exact_href(self):
        """http:// か https:// で始まる URL はリンクにし、href は元の URL そのもの (属性を抜けない)。"""
        root, links = render_rss_urls(oto(), ARTICLE_SHOWN, self.new_dir())
        for i, u in enumerate(ARTICLE_SHOWN):
            with self.subTest(url=u):
                self.assertEqual(len(links[i]), 1, "リンクが無い")
                self.assertEqual(links[i][0].attrs.get("href"), u)
                self.assertEqual([k for k, _ in links[i][0].attr_list], ["href", "target", "class"])
        self.assertEqual(collections.Counter(n.tag for n in root.iter())["img"], 0)

    def test_other_urls_are_not_linked(self):
        """それ以外 (javascript:・大文字/空白/タブ入りの javascript:・data:・vbscript:・// 始まり・先頭に空白・
        None・空・文字列でない値) はリンクを出さない。"""
        root, links = render_rss_urls(oto(), ARTICLE_HIDDEN, self.new_dir())
        for i, u in enumerate(ARTICLE_HIDDEN):
            with self.subTest(url=u):
                self.assertEqual(links[i], [])
        self.assertEqual(bad_urls(root), [])
        self.assertEqual(len(find(root, cls="thread-card")), len(ARTICLE_HIDDEN) + 1)


class TestArticleUrlSpecGap(TmpDirClassMixin, unittest.TestCase):
    def test_scheme_is_case_insensitive(self):
        """(仕様に大文字の記載なし。URL のスキームは大文字小文字を区別しないので) HTTPS:// / Http:// もリンクにする。"""
        urls = ("HTTPS://EXAMPLE.COM/A", "Http://example.com/b")
        _root, links = render_rss_urls(oto(), urls, self.new_dir())
        for i, u in enumerate(urls):
            with self.subTest(url=u):
                self.assertEqual([n.attrs.get("href") for n in links[i]], [u])


# ============================================================
# 2. 検索レポートの独自スクリプト (escHtml・autoLink)
# ============================================================
def search_script(html_text):
    s = [n.text() for n in scripts_of(parse_html(html_text))]
    assert len(s) == 1, f"検索レポートの script が1つでない: {len(s)}"
    return s[0]


ESC_INPUTS = [None, "__undefined__", 0, 12, "", "&<>\"'", "a&amp;b", "日本語", "<img src=x onerror=alert(1)>"]
SL = "https://x.safelinks.protection.outlook.com/?url="
# 注入を試みる翻訳結果: (入力, [(リンクの href, リンクの表示の文字)])。表示はセーフリンクの url= を戻した文字そのまま
LINK_INJECT = [
    ("訳: " + SAFELINK_PAYLOAD + " です", [(SAFELINK_PAYLOAD, "<img src=x onerror=alert(1)>")]),
    (SL + "%3Cscript%3EP(%27tr2%27)%3C%2Fscript%3E", [(SL + "%3Cscript%3EP(%27tr2%27)%3C%2Fscript%3E", "<script>P('tr2')</script>")]),
    (SL + "%22%20onmouseover%3D%22P(1)", [(SL + "%22%20onmouseover%3D%22P(1)", "\" onmouseover=\"P(1)")]),
    (SL + "%3Csvg%2Fonload%3DP(1)%3E%26lt%3Bb%26gt%3B", [(SL + "%3Csvg%2Fonload%3DP(1)%3E%26lt%3Bb%26gt%3B",
                                                       "<svg/onload=P(1)><b>")]),
    (SL + "%26lt%3Bimg%20src%3Dx%20onerror%3Dalert(1)%26gt%3B",
     [(SL + "%26lt%3Bimg%20src%3Dx%20onerror%3Dalert(1)%26gt%3B", "<img src=x onerror=alert(1)>")]),
    (SL + "javascript%3Aalert(1)", [(SL + "javascript%3Aalert(1)", "javascript:alert(1)")]),
    ("https://example.com/x&lt;img src=x onerror=alert(1)&gt;", [("https://example.com/x&lt;img", "https://example.com/x<img")]),
]
# 注入にならない翻訳結果 (A10b 前の _14 でも要素が増えない)。表示 (文字・リンクの文字・href) は _14 と同じ
LINK_SAME_AS_14 = [
    "見て <https://example.com/a> を",
    "\"https://example.com/q\" と 'https://example.com/r'",
    "see https://example.com/?a=1&b=2 now",
    "https://example.com/x&lt;y と https://example.com/x&gt;y と https://example.com/x&quot;y",
    "https://nam12.safelinks.protection.outlook.com/?url=https%3A%2F%2Fexample.com%2Fp%3Fa%3D1%26b%3D2&data=05%7C02&reserved=0",
    SL + "https%3A%2F%2Fexample.com%2F" + "a" * 25 + "%26%3Cb%3E" + "z" * 20 + "&data=1",
    "<" + SL + "https%3A%2F%2Fexample.com%2Fb&data=1>",
    "https://example.com/" + "b" * 60 + " と https://example.com/" + "c" * 26 + "&lt;d",
    "URL なし & <b>太字</b> 'q' \"dq\"",
]
ANGLE_URL_TEXT = "見て <https://example.com/a> を"


class TestSearchReportScript(TmpDirClassMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.script = search_script(render_search(oto(), *search_inputs(plain, URL_PLAIN, HTML_BODY_PLAIN), cls.new_dir()))

    def test_escHtml_is_defined(self):
        """検索レポートの独自スクリプトに escHtml がある。"""
        self.assertIsNotNone(js_function_source(self.script, "escHtml"), "function escHtml が無い")

    def test_autoLink_escapes_the_display_url(self):
        """autoLink の戻り値の HTML で、表示の URL (displayUrl) は escHtml を通してから入れる (そのまま連結しない)。"""
        src = js_function_source(self.script, "autoLink")
        self.assertIsNotNone(src, "function autoLink が無い")
        rets = [ln for ln in src.splitlines() if "<a " in ln]
        self.assertEqual(len(rets), 1, rets)
        self.assertRegex(rets[0], r"\+\s*escHtml\(\s*displayUrl\b")
        self.assertIsNone(re.search(r"\+\s*displayUrl\b", rets[0]), "displayUrl をそのまま連結している: " + rets[0])

    def test_escHtml_in_node(self):
        """(node で実行) escHtml は & < > " ' を実体参照にし、null/undefined は ""、数値は文字列。戻すと元の文字。"""
        out = run_node(SEARCH_SCRIPT_HARNESS, {"script": self.script, "esc": ESC_INPUTS, "link": []})
        self.assertTrue(out["hasEsc"], "escHtml が関数として定義されていない")
        expected_plain = ["", "", "0", "12", "", "&<>\"'", "a&amp;b", "日本語", "<img src=x onerror=alert(1)>"]
        for inp, got, exp in zip(ESC_INPUTS, out["esc"], expected_plain):
            with self.subTest(input=inp):
                self.assertIsInstance(got, str)
                self.assertFalse(set(got) & set("<>\"'"), got)
                self.assertIsNone(re.search(r"&(?!(?:amp|lt|gt|quot|#39|#x27|apos);)", got), got)
                self.assertEqual(html_mod.unescape(got), exp)

    def test_autoLink_in_node(self):
        """(node で実行) 翻訳結果の URL のリンク: セーフリンクの url= に <img onerror>・<script>・" などがあっても、
        要素は a だけで、表示は url= を戻した文字のまま。href は元の URL (属性を抜けない)。"""
        out = run_node(SEARCH_SCRIPT_HARNESS, {"script": self.script, "esc": [], "link": [i for i, _ in LINK_INJECT]})
        for (inp, exp), got in zip(LINK_INJECT, out["link"]):
            with self.subTest(input=inp[:70]):
                root = parse_html(got)
                els = [n for n in root.iter() if n is not root]
                self.assertEqual([n.tag for n in els], ["a"] * len(exp), got)
                self.assertEqual([(n.attrs.get("href"), n.text()) for n in els], exp)
                for n in els:
                    self.assertEqual([k for k, _ in n.attr_list], ["href", "target", "style"])

    def test_angle_bracket_url_shows_no_entity_text(self):
        """(node で実行。レビュー指摘 m1) 「<https://example.com/a>」を含む翻訳結果: 表示は元の文のまま
        (&gt; などの実体参照の文字が出ない)。リンクの文字も https://example.com/a で始まり、&gt; を含まない。"""
        out = run_node(SEARCH_SCRIPT_HARNESS, {"script": self.script, "esc": [], "link": [ANGLE_URL_TEXT]})
        root = parse_html(out["link"][0])
        self.assertEqual(visible_text(root), ANGLE_URL_TEXT)
        links = find(root, tag="a")
        self.assertEqual(len(links), 1)
        self.assertTrue(links[0].text().startswith("https://example.com/a"), links[0].text())
        for ent in ("&gt;", "&lt;", "&quot;", "&amp;"):
            self.assertNotIn(ent, links[0].text())

    def test_display_is_the_same_as_rev14_for_non_injecting_text(self):
        """(node で実行) 注入にならない翻訳結果 (<URL>・"URL"・& や &lt; の文字・長い URL・ふつうのセーフリンク) の表示
        (文字・リンクの文字・href・要素) は、A10b 前の _14 と同じ (表示の文字は変えない)。"""
        old = _loader.rev_path(OLD_REV)
        if not os.path.isfile(old):
            self.skipTest(f"{OLD_REV} が無い")
        with tempdir_cwd() as tmp, contextlib.redirect_stdout(io.StringIO()):
            old_script = search_script(render_search(load_rev(OLD_REV), *search_inputs(plain, URL_PLAIN, HTML_BODY_PLAIN),
                                                     os.path.join(tmp, "o")))
        got = run_node(SEARCH_SCRIPT_HARNESS, {"script": self.script, "esc": [], "link": LINK_SAME_AS_14})["link"]
        exp = run_node(SEARCH_SCRIPT_HARNESS, {"script": old_script, "esc": [], "link": LINK_SAME_AS_14})["link"]

        def shape(h):
            root = parse_html(h)
            return (visible_text(root), [(n.tag, n.attrs.get("href"), n.text()) for n in root.iter() if n is not root])
        for inp, g, e in zip(LINK_SAME_AS_14, got, exp):
            with self.subTest(input=inp[:70]):
                self.assertEqual(shape(g), shape(e))


# ============================================================
# 3. 振り返り (achievement_id の JS の引数・ランク)
# ============================================================
TRICKY_IDS = (
    "Ochi::O'Brien's 件",                                   # AI のタイトル由来の '
    "Ochi::x'); P('aid1'); ('",                             # JS の文字列を抜ける試み
    "Ochi::back\\slash\\' end",                             # \ と \'
    "Ochi::trail\\",                                        # 末尾の \ (閉じの ' を無効にする試み)
    "Ochi::\"><img src=x onerror=P('aid2')>",               # 属性を抜ける試み
    "Ochi::</script><script>P('aid3')</script>",
    "Ochi::&#39;&quot;&amp;&lt;",                           # 実体参照の文字そのもの
    "Ochi::line1\nline2",
    "Ochi::cr\r\nlf",
    "Ochi::tab\tsep\u2028ls",
    "Ochi::conv-1|conv-2",                                  # ふつうの ID (根拠IDの連結)
)
LONE_CR_ID = "Ochi::lone\rcr"                               # Python の確認だけ (HTML は CR を LF に変えるため)
RANK_EVIL = "\"><script>P('rank')</script>"
RANK_EVIL2 = "S' onmouseover='P(3)\" x=\"<b>"


def achievement(aid, *, person="Ochi", rank="A", is_manual=False, **kw):
    """振り返りの実績1件 (apply_review_manual_overrides の後の形)。"""
    d = {"achievement_id": aid, "title": f"実績 {len(aid)}", "summary": "要約です。", "source_thread_ids": ["conv-x"],
         "is_confirmed": True, "activity_type": "decision", "goal_keys": ["G1_project"], "project_key": "Japan_Site",
         "has_quantitative_effect": False, "quantitative_note": "", "site_wide": False, "completed_date": "2026-09-15",
         "year_month": "202609", "person": person, "tier1": [], "tier2": [], "staff_involved": [],
         "staff_involved_labels": [], "g2_subcategory": None, "g2_subcategory_label": "", "rank": rank,
         "rank_label": rank, "type_label": "判断・決裁", "project_label": "Japan Site", "matched_meetings": [],
         "year_month_label": "2026年9月", "is_manual": is_manual, "thread_entry_id": None, "thread_topic": ""}
    d.update(kw)
    return d


def render_review(mod, achievements, out_dir, person="Ochi"):
    gen = mod.HTMLReportGenerator(out_dir, PORT)
    with contextlib.redirect_stdout(io.StringIO()):
        path = gen.generate_review_report({"achievements": achievements, "generated_at": "2026-10-04 12:00"},
                                          "2026年Q3", 1000, 500, False, person)
    return read_path(path, "review")


def review_rows(root):
    out = collections.OrderedDict()
    for n in find(root, tag="div", cls="rv-row"):
        out.setdefault(n.attrs.get("data-aid"), []).append(n)
    return out


def manual_items(rank_added, rank_override):
    """review_manual_items.json: 手動追加1件 (ランクは検証されない) と、AI の実績1件のランクの上書き。"""
    return {"hidden": [], "text_overrides": {}, "rank_overrides": {"Ochi::conv-m1": rank_override},
            "added": {"manual_aaa": {
                "manual_id": "manual_aaa", "person": "Ochi", "title": "手動の実績", "summary": "手動の要約",
                "goal_keys": ["G1_project"], "project_key": "Japan_Site", "activity_type": "decision",
                "is_confirmed": True, "has_quantitative_effect": False, "quantitative_note": "", "site_wide": False,
                "completed_date": "2026-09-01", "source_thread_ids": [], "rank": rank_added}}}


def review_with_manual(mod, rank_added, rank_override, out_dir):
    """review_manual_items.json を書き、apply_review_manual_overrides を通してから振り返りレポートを書かせる。"""
    _loader.write_json(mod.REVIEW_MANUAL_FILE, manual_items(rank_added, rank_override))
    base = achievement("", rank="A", source_thread_ids=["conv-m1"], title="AIの実績")
    base.pop("achievement_id")
    achs = mod.MailSummarizer.apply_review_manual_overrides(object.__new__(mod.MailSummarizer), [base])
    return render_review(mod, achs, out_dir)


class TestReviewReport(TmpDirClassMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ids = TRICKY_IDS + (LONE_CR_ID,)
        cls.html = render_review(oto(), [achievement(a) for a in cls.ids], cls.new_dir())
        cls.root = parse_html(cls.html)
        cls.rows = review_rows(cls.root)

    def test_each_id_has_its_rows_and_the_data_aid_is_the_original(self):
        """各実績の行があり、data-aid (属性を読んだ後の値) は元の ID のまま。"""
        self.assertEqual(sorted(self.rows), sorted(self.ids))

    def test_js_arguments_round_trip_to_the_original_id(self):
        """「ランク変更」(onchange)・「🙈 非表示」(onclick) は fn(this, '…', ポート) の形のまま (抜け出さない) で、
        '…' を JS の文字列として読むと元の ID (\\r を除く) に戻る。"""
        for aid, rows in self.rows.items():
            for row in rows:
                with self.subTest(aid=aid):
                    sel = find(row, tag="select", cls="rv-rank-select")
                    btn = find(row, tag="button", cls="rv-hide-btn")
                    self.assertEqual((len(sel), len(btn)), (1, 1))
                    for node, attr, fn in ((sel[0], "onchange", "reviewSetRank"), (btn[0], "onclick", "reviewHide")):
                        got = parse_js_call(node.attrs.get(attr, ""), fn)
                        self.assertIsNotNone(got, f"{attr} が {fn}(this, '…', {PORT}) の形でない: {node.attrs.get(attr)!r}")
                        self.assertEqual(got, (aid.replace("\r", ""), PORT))

    def test_js_arguments_with_a_real_js_parser(self):
        """(node の acorn で) 属性の JS は、呼び出し1つ・引数3つ (this・文字列・数) で、文字列は元の ID (\\r を除く)。"""
        srcs, expected = [], []
        for aid, rows in self.rows.items():
            row = rows[0]
            for node, attr, fn in ((find(row, tag="select", cls="rv-rank-select")[0], "onchange", "reviewSetRank"),
                                   (find(row, tag="button", cls="rv-hide-btn")[0], "onclick", "reviewHide")):
                srcs.append(node.attrs[attr])
                expected.append({"ok": True, "body": [{"type": "Call", "callee": fn, "args": [
                    {"type": "ThisExpression"}, {"type": "Literal", "value": aid.replace("\r", "")},
                    {"type": "Literal", "value": PORT}]}]})
        got = run_node(ACORN_HARNESS, srcs)
        for src, g, e in zip(srcs, got, expected):
            with self.subTest(src=src[:60]):
                self.assertEqual(g, e)

    def test_no_injected_elements(self):
        """ID の中の <img>・<script> は要素にならない (img・svg が無く、script はレポート自身のものだけ)。"""
        plain_html = render_review(oto(), [achievement(f"Ochi::plain-{i}") for i in range(len(self.ids))], self.new_dir())
        tags = collections.Counter(n.tag for n in self.root.iter())
        self.assertEqual(tags["img"], 0)
        self.assertEqual(tags["script"], len(scripts_of(parse_html(plain_html))))
        self.assertEqual(skeleton(parse_html(plain_html)), skeleton(self.root))


class TestReviewManualRank(TmpDirClassMixin, unittest.TestCase):
    """手動追加 (review_manual_items.json の added。ランクは検証されない)・ランクの上書きに "><script> を入れる。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        mod = oto()
        cls.html_plain = review_with_manual(mod, "Z", "Z", cls.new_dir())
        cls.html_evil = review_with_manual(mod, RANK_EVIL, RANK_EVIL2, cls.new_dir())
        cls.root_plain, cls.root_evil = parse_html(cls.html_plain), parse_html(cls.html_evil)

    def test_no_tags_or_attributes_are_added(self):
        a, b = skeleton(self.root_plain), skeleton(self.root_evil)
        self.assertEqual(a, b, "タグか属性が増えた\n" + skeleton_diff(a, b))
        self.assertEqual(collections.Counter(n.tag for n in self.root_evil.iter())["script"],
                         collections.Counter(n.tag for n in self.root_plain.iter())["script"])

    def test_rank_is_kept_as_the_attribute_value_and_class(self):
        """data-rank は元のランクの文字のまま、ランクのクラス名は rv-rank-<元の文字>、バッジの文字も元の文字。"""
        rows = review_rows(self.root_evil)
        self.assertEqual(set(rows), {"Ochi::manual_aaa", "Ochi::conv-m1"})
        for aid, rank in (("Ochi::manual_aaa", RANK_EVIL), ("Ochi::conv-m1", RANK_EVIL2)):
            for row in rows[aid]:
                with self.subTest(aid=aid):
                    self.assertEqual(row.attrs.get("data-rank"), rank)
                    badge = find(row, tag="span", cls="rv-rank-badge")
                    self.assertEqual(len(badge), 1)
                    self.assertEqual(badge[0].attrs.get("class"), f"rv-rank-badge rv-rank-{rank}")
                    self.assertEqual(badge[0].text(), rank)
                    self.assertEqual(badge[0].elements(), [])


# ============================================================
# 4. エラー時の文・アクション一覧の data-* 属性
# ============================================================
ERROR_EVIL = evil("err")


def overview_error_html(mod, kind, summary, out_dir, name="Caracal"):
    sec = "projects" if kind == "project" else "staffs"
    gen = mod.HTMLReportGenerator(out_dir, PORT)
    fn = gen.generate_project_report if kind == "project" else gen.generate_staff_report
    with contextlib.redirect_stdout(io.StringIO()):
        path = fn(name, {name: {"_error": True, "summary": summary}}, {}, {sec: {name: {}}},
                  "2026/09/27 - 2026/10/04", "重要度順", 1000, 500, "adopted", False)
    return read_path(path, kind)


def cockpit_error_html(mod, summary, out_dir):
    gen = mod.HTMLReportGenerator(out_dir, PORT)
    with contextlib.redirect_stdout(io.StringIO()):
        path = gen.generate_cockpit_report({"_error": True, "summary": summary}, {}, 1000, 500, False)
    return read_path(path, "cockpit")


def error_texts(root, kind):
    if kind == "cockpit":
        return [n.text() for n in find(root, tag="div") if n.text().startswith("エラー: ")
                and "color:red" in (n.attrs.get("style") or "").replace(" ", "")]
    return [find(card, cls="t-body")[0].text() for card in find(root, cls="thread-card")
            if find(card, cls="t-title") and find(card, cls="t-title")[0].text().endswith(" - エラー")]


class TestErrorTexts(TmpDirClassMixin, unittest.TestCase):
    KINDS = ("project", "staff", "cockpit")

    def render(self, kind, summary):
        if kind == "cockpit":
            return cockpit_error_html(oto(), summary, self.new_dir())
        return overview_error_html(oto(), kind, summary, self.new_dir())

    def test_error_text_is_escaped(self):
        """エラー時の文 (data["summary"]) に <img>・<script> があっても要素にならず、そのままの文字で表示される。"""
        for kind in self.KINDS:
            with self.subTest(kind=kind):
                rp, re_ = parse_html(self.render(kind, plain("err"))), parse_html(self.render(kind, ERROR_EVIL))
                self.assertEqual(skeleton(rp), skeleton(re_), skeleton_diff(skeleton(rp), skeleton(re_)))
                prefix = "エラー: " if kind == "cockpit" else ""
                self.assertEqual(error_texts(re_, kind), [prefix + ERROR_EVIL])

    def test_none_is_still_shown_as_None(self):
        """summary が無い (None) ときの表示は従来どおり "None"。"""
        for kind in self.KINDS:
            with self.subTest(kind=kind):
                prefix = "エラー: " if kind == "cockpit" else ""
                self.assertEqual(error_texts(parse_html(self.render(kind, None)), kind), [prefix + "None"])


PROG_EVIL1 = "in_progress\" onmouseover=\"P('prog1')"
PROG_EVIL2 = "x\"><img src=x onerror=\"P('prog2')\">"
PRIO_EVIL1 = "\"><svg onload=\"P('prio1')\">"
PRIO_EVIL2 = "top' autofocus onfocus='P(2)' x=\"<b>&amp;"


def action_cards():
    cards = []
    for i in range(2):
        cards.append({"conversation_id": f"C{i}", "topic": f"件名{i}", "real_topic": f"件名{i}",
                      "latest_date_mmdd": "10/04 09:00", "latest_ts": 1_790_000_000 + i, "has_unread": False,
                      "is_r19": False, "is_flagged": False, "importance": "高", "latest_entry_id": f"E{i}",
                      "summary": "s", "actions": [
                          {"action_key": f"C{i}#{j}", "owner": "Saji", "target": "あなた", "action": f"確認{j}",
                           "deadline": "10/10", "progress": "not_started", "priority": "", "comment": ""}
                          for j in range(2)]})
    return cards


def action_html(mod, statuses, out_dir):
    """json/action_status.json を書き、「フォーマットのみ再生成」と同じく読み込んだ値をカードに入れてから書かせる。"""
    _loader.write_json(_loader.STATUS_PATH, statuses)
    loaded = mod.load_action_status()
    cards = action_cards()
    for card in cards:
        for a in card["actions"]:
            st = loaded.get(a.get("action_key", ""), {})
            a["progress"] = st.get("progress", a.get("progress", "not_started"))
            a["priority"] = st.get("priority", a.get("priority", ""))
            a["comment"] = st.get("comment", a.get("comment", ""))
    gen = mod.HTMLReportGenerator(out_dir, PORT)
    with contextlib.redirect_stdout(io.StringIO()):
        path = gen.generate_action_dashboard_report(cards, "2026/09/27 - 2026/10/04", 1000, 500, True, 7)
    return read_path(path, "action")


def statuses(p1, p2, r1, r2):
    return {"C0#0": {"progress": p1, "priority": r1, "comment": "", "updated_at": "2026-10-01T00:00:00"},
            "C0#1": {"progress": p2, "priority": r2, "comment": "", "updated_at": "2026-10-01T00:00:00"},
            "C1#0": {"progress": "in_progress", "priority": "high", "comment": "", "updated_at": "2026-10-01T00:00:00"}}


class TestActionDashboardAttributes(TmpDirClassMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        mod = oto()
        cls.root_plain = parse_html(action_html(mod, statuses("zz_p1", "zz_p2", "zz_r1", "zz_r2"), cls.new_dir()))
        cls.root_evil = parse_html(action_html(mod, statuses(PROG_EVIL1, PROG_EVIL2, PRIO_EVIL1, PRIO_EVIL2),
                                               cls.new_dir()))

    def test_no_tags_or_attributes_are_added(self):
        a, b = skeleton(self.root_plain), skeleton(self.root_evil)
        self.assertEqual(a, b, "タグか属性が増えた\n" + skeleton_diff(a, b))
        self.assertEqual(collections.Counter(n.tag for n in self.root_evil.iter())["img"], 0)

    def test_data_attributes_keep_the_values(self):
        """アクションの data-progress / data-priority・カードの data-progresses / data-priorities・状態チップの
        data-progress は、action_status.json の値そのまま (属性を抜けない)。"""
        items = {n.attrs["data-key"]: n for n in find(self.root_evil, cls="action-item")}
        self.assertEqual((items["C0#0"].attrs["data-progress"], items["C0#0"].attrs["data-priority"]),
                         (PROG_EVIL1, PRIO_EVIL1))
        self.assertEqual((items["C0#1"].attrs["data-progress"], items["C0#1"].attrs["data-priority"]),
                         (PROG_EVIL2, PRIO_EVIL2))
        cards = {n.attrs["data-key"]: n for n in find(self.root_evil, cls="action-card")}
        self.assertEqual(cards["C0"].attrs["data-progresses"], ",".join(sorted({PROG_EVIL1, PROG_EVIL2})))
        self.assertEqual(cards["C0"].attrs["data-priorities"], ",".join(sorted({PRIO_EVIL1, PRIO_EVIL2})))
        chip = find(cards["C0"], cls="status-chip")
        self.assertEqual(len(chip), 1)
        self.assertEqual(chip[0].attrs["data-progress"], PROG_EVIL1)
        self.assertEqual(chip[0].text(), PROG_EVIL1, "未知の進捗はそのままの文字で表示 (従来どおり)")
        self.assertEqual([k for k, _ in chip[0].attr_list], ["class", "data-progress"])


# ============================================================
# 5. 共通JS の regenerateQuestions・俯瞰2画面の外部スクリプト
# ============================================================
def overview_data():
    def item(t):
        return {"category": "プロジェクト管理", "project_scope": "横断業務", "action_type": "通知・共有", "text": t,
                "status_icon": "🔵", "source_thread_ids": ["T1"]}
    thread = {"thread_id": "T1", "topic": "件名", "summary": "要約", "is_target": True, "importance": "高",
              "category": "その他", "project_scope": "横断業務", "action_type": "通知・共有",
              "actions": [{"owner": "Saji", "action": "確認", "status": "未定"}]}
    return {"manager_actions": [item("確認する")], "staff_status": [item("進めている")], "stalled_monitor": [],
            "updated_history": "", "ai_questions": ["質問1"], "threads": [thread]}


def overview_html(mod, kind, out_dir, name="Caracal"):
    sec = "projects" if kind == "project" else "staffs"
    mail = {"body": "本文です", "html_body": "", "entry_id": "E1", "subject": "件名", "conversation_topic": "件名",
            "sender_name": "Saji", "received": "2026-10-01 09:00"}
    orig = {name: {"T1": {"latest_date": datetime(2026, 10, 1, 9, 0), "latest_entry_id": "E1", "topic": "件名",
                          "mails": [mail]}}}
    gen = mod.HTMLReportGenerator(out_dir, PORT)
    fn = gen.generate_project_report if kind == "project" else gen.generate_staff_report
    with contextlib.redirect_stdout(io.StringIO()):
        path = fn(name, {name: overview_data()}, orig, {sec: {name: {}}}, "2026/09/27 - 2026/10/04", "重要度順",
                  1000, 500, "adopted", False)
    return read_path(path, kind)


def common_js(root):
    s = [n.text() for n in scripts_of(root) if "function regenerateQuestions" in n.text()]
    assert len(s) == 1, f"regenerateQuestions を含む script が1つでない: {len(s)}"
    return s[0]


QUESTIONS = ["<img src=x onerror=P('q1')>", "普通の質問ですか?", "\"><svg onload=P('q2')>", "&lt;b&gt; & 'x'"]


class TestCommonJsAndExternalScripts(TmpDirClassMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        mod = oto()
        cls.pages = {k: overview_html(mod, k, cls.new_dir()) for k in ("project", "staff")}
        cls.pages["project_error"] = overview_error_html(mod, "project", ERROR_EVIL, cls.new_dir())
        cls.pages["staff_error"] = overview_error_html(mod, "staff", ERROR_EVIL, cls.new_dir())

    def test_regenerateQuestions_passes_the_ai_output_through_escHtml(self):
        """共通JS の regenerateQuestions: innerHTML に入れる AI の出力 (q) は escHtml を通す。"""
        src = js_function_source(common_js(parse_html(self.pages["project"])), "regenerateQuestions")
        self.assertIsNotNone(src)
        assigns = re.findall(r"innerHTML\s*=\s*(`[^`]*`|[^;]*);", src)
        self.assertTrue(assigns, "innerHTML への代入が見つからない")
        for a in assigns:
            subs = re.findall(r"\$\{([^}]*)\}", a)
            self.assertTrue(subs, a)
            for s in subs:
                self.assertTrue(s.strip().startswith("escHtml("), f"escHtml を通していない: ${{{s}}}")

    def test_regenerateQuestions_in_node(self):
        """(node で実行) AI の新しい質問に <img onerror> などがあっても、li の中は <b>Q.</b> と文字だけ。"""
        out = run_node(COMMON_JS_HARNESS, {"script": common_js(parse_html(self.pages["project"])),
                                           "questions": QUESTIONS})
        self.assertNotIn("error", out, out.get("error"))
        self.assertEqual(len(out["items"]), len(QUESTIONS))
        for q, inner in zip(QUESTIONS, out["items"]):
            with self.subTest(q=q):
                root = parse_html(inner)
                self.assertEqual([n.tag for n in root.iter() if n is not root], ["b"], inner)
                self.assertEqual(visible_text(root), "Q. " + q)

    def test_overview_reports_have_no_external_script(self):
        """俯瞰2画面 (通常・エラー時) に、外部の script (src 付き) が無い。marked の読み込みも無い。"""
        for name, page in self.pages.items():
            with self.subTest(page=name):
                root = parse_html(page)
                self.assertEqual([n.attrs.get("src") for n in scripts_of(root) if "src" in n.attrs], [])
                self.assertNotIn("marked.min.js", page)
                self.assertNotIn("cdn.jsdelivr.net", page)


# ============================================================
# 6. ブラウザ (Chromium)
# ============================================================
JS_FIND_TRANSLATE_BTN = "const findBtn = uid => [...document.querySelectorAll('button')].find(b => (b.getAttribute('onclick') || '').includes(\"translateText(this, '\" + uid + \"'\"));\n"
TRANSLATED_PLAIN = ("訳: <https://example.com/a> と " + SAFELINK_PAYLOAD +
                    " と https://x.safelinks.protection.outlook.com/?url=%3Cimg%20src%3Dx%20onerror%3DP(%27tr%27)%3E"
                    " と https://x.safelinks.protection.outlook.com/?url=%3Cscript%3EP(%27tr2%27)%3C%2Fscript%3E")


class TestInBrowser(TmpDirClassMixin, unittest.TestCase):
    """実際に Chromium で開く (node の playwright。無ければ skip)。注入した P('…') や alert が動かないこと。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not node_exe():
            raise unittest.SkipTest("node が無い環境: ブラウザの確認は対象外")
        mod = oto()
        files = {}

        def save(name, text):
            p = os.path.join(cls.tmp, f"{name}.html")
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(text)
            files[name] = p
            return p

        save("search", render_search(mod, *search_inputs(evil, URL_EVIL, HTML_BODY_EVIL), cls.new_dir()))
        cls.review_ids = TRICKY_IDS
        save("review", render_review(mod, [achievement(a) for a in TRICKY_IDS], cls.new_dir()))
        save("review_manual", review_with_manual(mod, RANK_EVIL, RANK_EVIL2, cls.new_dir()))
        save("project", overview_html(mod, "project", cls.new_dir()))
        save("staff", overview_html(mod, "staff", cls.new_dir()))
        save("project_error", overview_error_html(mod, "project", ERROR_EVIL, cls.new_dir()))
        save("staff_error", overview_error_html(mod, "staff", ERROR_EVIL, cls.new_dir()))
        save("cockpit_error", cockpit_error_html(mod, ERROR_EVIL, cls.new_dir()))
        save("action", action_html(mod, statuses(PROG_EVIL1, PROG_EVIL2, PRIO_EVIL1, PRIO_EVIL2), cls.new_dir()))
        review_fake = [["/review_hidden_list", {"hidden_ids": [], "items": []}],
                       ["/update_review_manual", {"status": "success"}]]
        scenarios = [
            {"name": "search_load", "file": files["search"], "settle": 900, "script":
                "return {iframes: [...document.querySelectorAll('iframe')].map(f => ({id: f.id, sandbox: f.getAttribute('sandbox')})),"
                " titles: [...document.querySelectorAll('.t-title')].map(e => e.textContent),"
                " imgs: document.querySelectorAll('img').length, svgs: document.querySelectorAll('svg').length};"},
            {"name": "search_translate_plain", "file": files["search"],
             "fake": [["/translate_array", {"translated": []}], ["/translate", {"translated": TRANSLATED_PLAIN}]],
             "script": JS_FIND_TRANSLATE_BTN +
                "await translateText(findBtn('EN1'), 'EN1', 8765);\n"
                "await new Promise(r => setTimeout(r, 500));\n"
                "const box = document.getElementById('m-body-EN1');\n"
                "return {imgs: box.querySelectorAll('img').length, scripts: box.querySelectorAll('script').length,"
                " tags: [...box.querySelectorAll('*')].map(e => e.tagName),"
                " links: [...box.querySelectorAll('a')].map(a => [a.getAttribute('href'), a.textContent]), text: box.textContent};"},
            {"name": "search_translate_iframe", "file": files["search"], "settle": 900,
             "fake": [["/translate_array", {"translated": ["こんにちは世界", "二行目", "リンク"]}],
                      ["/translate", {"translated": "x"}]],
             "script": JS_FIND_TRANSLATE_BTN +
                "const ifr = document.getElementById('iframe-EN3');\n"
                "for (let i = 0; i < 60; i++) { const d = ifr.contentDocument; if (d && d.body && d.body.textContent.includes('Hello')) break; await new Promise(r => setTimeout(r, 50)); }\n"
                "const before = ifr.contentDocument && ifr.contentDocument.body ? ifr.contentDocument.body.textContent : null;\n"
                "await translateText(findBtn('EN3'), 'EN3', 8765);\n"
                "const after = ifr.contentDocument && ifr.contentDocument.body ? ifr.contentDocument.body.textContent : null;\n"
                "return {sandbox: ifr.getAttribute('sandbox'), before, after};"},
            {"name": "review", "file": files["review"], "fake": review_fake, "script":
                "const rows = [...document.querySelectorAll('.rv-row')]; const seen = new Set(); const res = [];\n"
                "for (const row of rows) {\n"
                "  const aid = row.dataset.aid; if (seen.has(aid)) continue; seen.add(aid);\n"
                "  let n = window.__fetches.length;\n"
                "  row.querySelector('.rv-hide-btn').click();\n"
                "  await new Promise(r => setTimeout(r, 60));\n"
                "  const hide = window.__fetches.slice(n).map(f => f.body);\n"
                "  const same = rows.filter(r => r.dataset.aid === aid);\n"
                "  const hiddenAll = same.every(r => r.style.display === 'none');\n"
                "  const sel = row.querySelector('.rv-rank-select'); sel.value = 'S';\n"
                "  n = window.__fetches.length; sel.dispatchEvent(new Event('change'));\n"
                "  await new Promise(r => setTimeout(r, 60));\n"
                "  const rank = window.__fetches.slice(n).map(f => f.body);\n"
                "  const rankedAll = same.every(r => r.dataset.rank === 'S');\n"
                "  res.push({aid, hide, rank, hiddenAll, rankedAll, count: same.length});\n"
                "}\n"
                "return res;"},
            {"name": "review_manual", "file": files["review_manual"], "fake": review_fake, "script":
                "return [...document.querySelectorAll('.rv-row')].map(r => ({aid: r.dataset.aid, rank: r.dataset.rank,"
                " badge: r.querySelector('.rv-rank-badge').className, text: r.querySelector('.rv-rank-badge').textContent}));"},
            {"name": "project", "file": files["project"],
             "fake": [["/generate_questions", {"new_questions": QUESTIONS}]], "script":
                "const ul = document.createElement('ul'); ul.id = 'qlist-TQ'; document.body.appendChild(ul);\n"
                "const c = document.createElement('div'); c.id = 'ctx-TQ'; c.textContent = 'ctx'; document.body.appendChild(c);\n"
                "const b = document.createElement('button'); b.textContent = 'gen'; document.body.appendChild(b);\n"
                "await regenerateQuestions('TQ', 'Caracal', 8765, b);\n"
                "await new Promise(r => setTimeout(r, 300));\n"
                "return [...ul.children].map(li => ({text: li.textContent, tags: [...li.querySelectorAll('*')].map(e => e.tagName)}));"},
            {"name": "staff", "file": files["staff"]},
            {"name": "project_error", "file": files["project_error"], "script":
                "return [...document.querySelectorAll('.thread-card .t-body')].map(e => e.textContent);"},
            {"name": "staff_error", "file": files["staff_error"], "script":
                "return [...document.querySelectorAll('.thread-card .t-body')].map(e => e.textContent);"},
            {"name": "cockpit_error", "file": files["cockpit_error"], "script":
                "return [...document.querySelectorAll('div')].filter(e => e.textContent.startsWith('エラー: ') && e.children.length === 0).map(e => e.textContent);"},
            {"name": "action", "file": files["action"], "script":
                "return {items: [...document.querySelectorAll('.action-item')].map(e => [e.dataset.key, e.dataset.progress, e.dataset.priority]),"
                " cards: [...document.querySelectorAll('.action-card')].map(e => [e.dataset.key, e.dataset.progresses, e.dataset.priorities]),"
                " chips: [...document.querySelectorAll('.status-chip')].map(e => e.dataset.progress)};"},
        ]
        cls.res = run_browser(scenarios)

    def r(self, name):
        rec = self.res.get(name)
        self.assertIsNotNone(rec, f"{name} の結果が無い")
        self.assertNotIn("fatal", rec, rec.get("fatal"))
        return rec

    def assert_quiet(self, rec, errors=True):
        self.assertEqual(rec["pwn"], [], "注入したコードが動いた")
        self.assertEqual(rec["dialogs"], [], "ダイアログ (alert など) が出た")
        if errors:
            self.assertEqual(rec["errors"], [], "ページで JS のエラー")

    def test_search_report_runs_nothing_on_load(self):
        """検索レポートを開いただけでは、件名・差出人名・添付・AI 要約・RSS の値・HTML 本文のスクリプトは動かない。
        iframe には sandbox があり、注入した img・svg は無い。"""
        rec = self.r("search_load")
        self.assert_quiet(rec)
        self.assertEqual([f["sandbox"] for f in rec["out"]["iframes"]], [SANDBOX_ATTR.split('"')[1]] * 2)
        self.assertEqual((rec["out"]["imgs"], rec["out"]["svgs"]), (0, 0))
        self.assertEqual(rec["out"]["titles"][0], evil("topic") + " 3件")

    def test_search_translation_with_a_safelinks_payload_runs_nothing(self):
        """翻訳結果のセーフリンク (url= に %3Cimg onerror…%3E) は、表示の文字になり、alert も P(…) も動かない。
        同じ翻訳結果の「<https://example.com/a>」は、元の文のとおり表示される (&gt; の文字が出ない。レビュー指摘 m1)。"""
        rec = self.r("search_translate_plain")
        self.assert_quiet(rec)
        out = rec["out"]
        self.assertEqual((out["imgs"], out["scripts"]), (0, 0))
        self.assertEqual(out["tags"], ["A", "A", "A", "A"])
        self.assertEqual([t for _h, t in out["links"]][1:],
                         ["<img src=x onerror=alert(1)>", "<img src=x onerror=P('tr')>", "<script>P('tr2')</script>"])
        self.assertEqual(out["links"][1][0], SAFELINK_PAYLOAD)
        first = out["links"][0][1]
        self.assertTrue(first.startswith("https://example.com/a"), first)
        self.assertNotIn("&gt;", first)
        self.assertIn("訳: <https://example.com/a> と ", out["text"])
        self.assertNotIn("&gt;", out["text"])
        self.assertEqual([f["url"] for f in rec["fetches"]], [f"http://localhost:{PORT}/translate"])

    def test_search_iframe_scripts_are_blocked_but_translation_still_works(self):
        """HTML 本文の iframe の中のスクリプト・onerror は動かない (sandbox)。翻訳は従来どおり iframe の文字を置き換える
        (allow-same-origin で中の文書を読める)。"""
        rec = self.r("search_translate_iframe")
        self.assert_quiet(rec)
        out = rec["out"]
        self.assertIsNotNone(out["before"], "iframe の文書を読めない")
        self.assertIn("Hello world", out["before"])
        self.assertIn("こんにちは世界", out["after"] or "")
        self.assertIn("二行目", out["after"] or "")
        self.assertEqual([f["url"] for f in rec["fetches"]], [f"http://localhost:{PORT}/translate_array"])

    def test_review_buttons_send_the_original_id(self):
        """振り返り: 「🙈 非表示」「ランク変更」は、元の ID (\\r を除く) をサーバーへ送り、同じ ID の行 (各ビュー) を
        非表示/ランク変更する。' や \\ を含む ID でも JS を抜け出さない (P(…) が動かない・JS エラーなし)。"""
        rec = self.r("review")
        self.assert_quiet(rec)
        got = {x["aid"]: x for x in rec["out"]}
        for aid in self.review_ids:
            exp = aid.replace("\r", "")
            with self.subTest(aid=aid):
                self.assertIn(exp, got, "行が無い (data-aid が元の ID でない)")
                x = got[exp]
                self.assertEqual([json.loads(b) for b in x["hide"]], [{"action": "hide", "achievement_id": exp}])
                self.assertEqual([json.loads(b) for b in x["rank"]],
                                 [{"action": "set_rank", "achievement_id": exp, "rank": "S"}])
                self.assertTrue(x["hiddenAll"], "同じ ID の行が非表示にならない")
                self.assertTrue(x["rankedAll"], "同じ ID の行のランクが変わらない")
                self.assertGreaterEqual(x["count"], 2)

    def test_review_manual_rank_runs_nothing(self):
        """手動追加・上書きのランクの "><script> は動かず、data-rank・クラス名・バッジの文字は元の文字のまま。"""
        rec = self.r("review_manual")
        self.assert_quiet(rec)
        rows = {}
        for x in rec["out"]:
            rows.setdefault(x["aid"], []).append(x)
        for aid, rank in (("Ochi::manual_aaa", RANK_EVIL), ("Ochi::conv-m1", RANK_EVIL2)):
            with self.subTest(aid=aid):
                self.assertTrue(rows.get(aid))
                for x in rows[aid]:
                    self.assertEqual((x["rank"], x["badge"], x["text"]), (rank, f"rv-rank-badge rv-rank-{rank}", rank))

    def test_overview_reports_load_nothing_external_and_have_no_js_errors(self):
        """俯瞰2画面は外部 (http/https) を読みに行かず、JS のエラーも無い (marked を外しても動く)。"""
        for name in ("project", "staff"):
            with self.subTest(page=name):
                rec = self.r(name)
                self.assert_quiet(rec)
                self.assertEqual([u for u in rec["requests"] if u.startswith(("http://", "https://"))], [])

    def test_regenerateQuestions_in_browser(self):
        """共通JS の regenerateQuestions: AI の質問の <img onerror> などは文字として表示され、動かない。"""
        rec = self.r("project")
        self.assertEqual(rec["out"], [{"text": "Q. " + q, "tags": ["B"]} for q in QUESTIONS])

    def test_error_texts_run_nothing(self):
        """エラー時の文 (俯瞰2画面・統括コックピット v1) の <img onerror>・<script> は動かず、文字として表示される。"""
        for name, exp in (("project_error", ERROR_EVIL), ("staff_error", ERROR_EVIL),
                          ("cockpit_error", "エラー: " + ERROR_EVIL)):
            with self.subTest(page=name):
                rec = self.r(name)
                self.assert_quiet(rec, errors=False)
                self.assertEqual(rec["out"], [exp])

    def test_action_dashboard_data_attributes_in_the_dom(self):
        """アクション一覧: action_status.json の値の " や > で属性を抜けず (P(…) が動かない)、dataset は元の値。"""
        rec = self.r("action")
        self.assert_quiet(rec, errors=False)
        items = {k: (p, r) for k, p, r in rec["out"]["items"]}
        self.assertEqual(items["C0#0"], (PROG_EVIL1, PRIO_EVIL1))
        self.assertEqual(items["C0#1"], (PROG_EVIL2, PRIO_EVIL2))
        cards = {k: (p, r) for k, p, r in rec["out"]["cards"]}
        self.assertEqual(cards["C0"], (",".join(sorted({PROG_EVIL1, PROG_EVIL2})), ",".join(sorted({PRIO_EVIL1, PRIO_EVIL2}))))


# ============================================================
# 7. 範囲ガード (_14 → _15)
# ============================================================
OLD_REV = "outlook_total_organizer_20261004_14.py"
NEW_REV = "outlook_total_organizer_20261004_15.py"
G = "HTMLReportGenerator."
ALLOWED_TO_CHANGE = {G + n for n in ("_card", "_build_html", "generate_review_report", "generate_project_report",
                                     "generate_staff_report", "generate_cockpit_report",
                                     "generate_action_dashboard_report", "_get_common_js_and_css")}


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


class _Undo(ast.NodeTransformer):
    """_15 のメソッドに入った仕様の変更を元に戻す (戻した回数を数える)。"""

    def __init__(self, unwrap=None, str_edits=(), rename=None, drop_assigns=None, expr_swaps=None, genexp=False):
        self.unwrap = unwrap                  # Call -> bool: 真なら最初の引数 (str(x) なら x) に置き換える
        self.str_edits = str_edits            # [(正規表現, 置換)] 文字列定数 (f-string の固定部分も)
        self.rename = rename or {}
        self.drop_assigns = drop_assigns or {}  # {変数名: 期待する右辺のソース}
        self.expr_swaps = expr_swaps or {}    # {式のソース: 置き換える式のソース} (IfExp の条件)
        self.genexp = genexp                  # (n for n in X) -> X
        self.n = collections.Counter()

    def visit_Call(self, node):
        self.generic_visit(node)
        if self.unwrap and self.unwrap(node):
            self.n["unwrap"] += 1
            return node.args[0]
        return node

    def visit_GeneratorExp(self, node):
        self.generic_visit(node)
        if self.genexp and isinstance(node.elt, ast.Name) and len(node.generators) == 1:
            g = node.generators[0]
            if isinstance(g.target, ast.Name) and g.target.id == node.elt.id and not g.ifs:
                self.n["genexp"] += 1
                return g.iter
        return node

    def visit_IfExp(self, node):
        self.generic_visit(node)
        src = ast.unparse(node.test)
        if src in self.expr_swaps:
            self.n["swap"] += 1
            node.test = ast.parse(self.expr_swaps[src], mode="eval").body
        return node

    def visit_Constant(self, node):
        if isinstance(node.value, str):
            v = node.value
            for pat, rep in self.str_edits:
                v, k = re.subn(pat, rep, v, flags=re.S)
                self.n["str:" + pat[:30]] += k
            if v != node.value:
                return ast.copy_location(ast.Constant(v), node)
        return node

    def visit_Name(self, node):
        if node.id in self.rename:
            self.n["rename:" + node.id] += 1
            return ast.copy_location(ast.Name(self.rename[node.id], node.ctx), node)
        return node

    def visit_Assign(self, node):
        if (len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in self.drop_assigns):
            self.n["drop:" + node.targets[0].id] += 1
            assert ast.unparse(node.value) == self.drop_assigns[node.targets[0].id], ast.unparse(node)
            return None
        self.generic_visit(node)
        return node


def _call_name(node):
    f = node.func
    return f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")


def _rth_of(arg_src):
    """report_text_html(<arg_src>) だけを外す。"""
    def pred(c):
        return (_call_name(c) == "report_text_html" and isinstance(c.func, ast.Name) and len(c.args) == 1
                and not c.keywords and (arg_src is None or ast.unparse(c.args[0]) == arg_src))
    return pred


_ACTION_ATTR_VARS = {"progress", "priority", "progresses_attr", "priorities_attr", "first_action_progress"}


def _action_escape(c):
    """html_mod.escape(X, quote=True) / html_mod.escape(str(X), quote=True) (X は進捗・優先度の変数) を X に戻す。"""
    if not (isinstance(c.func, ast.Attribute) and c.func.attr == "escape" and isinstance(c.func.value, ast.Name)
            and c.func.value.id == "html_mod" and len(c.args) == 1 and len(c.keywords) == 1
            and c.keywords[0].arg == "quote" and isinstance(c.keywords[0].value, ast.Constant)
            and c.keywords[0].value.value is True):
        return False
    a = c.args[0]
    if isinstance(a, ast.Call) and _call_name(a) == "str" and isinstance(a.func, ast.Name) and len(a.args) == 1:
        a = a.args[0]
        if isinstance(a, ast.Name) and a.id in _ACTION_ATTR_VARS:
            c.args[0] = a
            return True
        return False
    return isinstance(a, ast.Name) and a.id in _ACTION_ATTR_VARS


ESC_FN_RE = r"function escHtml\(s\) \{\n.*?\n\}\n\n"
# autoLink の表示 (レビュー指摘 m1 の追補: 渡る文はエスケープ済みなので &lt; &gt; &quot; を戻してから escHtml)
AUTOLINK_DISPLAY_RE = (r"escHtml\(displayUrl\.replace\(/&lt;/g, '<'\)\.replace\(/&gt;/g, '>'\)"
                       r"\.replace\(/&quot;/g, '\"'\)\)")
MARKED_LINE_RE = r"[ ]*<script src=\"https://cdn\.jsdelivr\.net/npm/marked/marked\.min\.js\"></script>\n"
# メソッド名 -> (_15 側の戻し方, 期待する回数, _14 側の戻し方 (marked の行を消す) の期待回数)
UNDO_SPECS = {
    "_card": (lambda: _Undo(unwrap=_rth_of(None), genexp=True,
                            str_edits=[(re.escape(SANDBOX_ATTR), "")],
                            expr_swaps={"str(s.get('article_url') or '').lower().startswith(('http://', 'https://'))":
                                        "s.get('article_url')"}),
              {"unwrap": 18, "genexp": 1, "swap": 1, "str:" + re.escape(SANDBOX_ATTR)[:30]: 1}, 0),
    "_build_html": (lambda: _Undo(str_edits=[(ESC_FN_RE, ""), (AUTOLINK_DISPLAY_RE, "displayUrl")]),
                    {"str:" + ESC_FN_RE[:30]: 1, "str:" + AUTOLINK_DISPLAY_RE[:30]: 1}, 0),
    "generate_review_report": (lambda: _Undo(
        drop_assigns={"aid_js": "report_js_str_html(a.get('achievement_id', ''))",
                      "rank_safe": "html_mod.escape(str(a.get('rank', 'B')), quote=True)"},
        rename={"aid_js": "aid_safe", "rank_safe": "rank"}),
        {"drop:aid_js": 1, "drop:rank_safe": 1, "rename:aid_js": 2, "rename:rank_safe": 2}, 0),
    "generate_project_report": (lambda: _Undo(unwrap=_rth_of("data.get('summary')")), {"unwrap": 1}, 1),
    "generate_staff_report": (lambda: _Undo(unwrap=_rth_of("data.get('summary')")), {"unwrap": 1}, 1),
    "generate_cockpit_report": (lambda: _Undo(unwrap=_rth_of("data.get('summary')")), {"unwrap": 1}, 0),
    "generate_action_dashboard_report": (lambda: _Undo(unwrap=_action_escape), {"unwrap": 5}, 0),
    "_get_common_js_and_css": (lambda: _Undo(str_edits=[(r"\$\{escHtml\(q\)\}", "${q}")]),
                               {"str:" + r"\$\{escHtml\(q\)\}"[:30]: 1}, 0),
}


def short_diff(a, b, limit=30):
    lines = list(difflib.unified_diff(a.splitlines(), b.splitlines(), "old", "new", lineterm="", n=1))
    return "\n".join(lines[:limit])


def rev_paths():
    old = _loader.rev_path(OLD_REV)
    new = _loader.rev_path(NEW_REV)
    if not (os.path.isfile(old) and os.path.isfile(new)):
        raise unittest.SkipTest(f"A10b のリビジョン対 ({OLD_REV} / {NEW_REV}) が無い")
    return old, new


class TestScopeGuardA10b(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline, cls.target = rev_paths()
        cls.old = _index_source(cls.baseline)
        cls.new = _index_source(cls.target)

    def test_no_existing_function_is_removed(self):
        self.assertEqual(sorted(n for n in self.old[0] if n not in self.new[0]), [])

    def test_only_the_listed_methods_changed(self):
        """変わった既存の関数/メソッドは仕様の一覧 (8つ) だけ。8つとも実際に変わっている。"""
        old_f, new_f = self.old[0], self.new[0]
        changed = {n for n, s in old_f.items() if n in new_f and new_f[n] != s}
        self.assertEqual(sorted(changed - ALLOWED_TO_CHANGE), [], "許可されていない既存関数/メソッドの変更")
        self.assertEqual(sorted(ALLOWED_TO_CHANGE - changed), [], "変わるはずのメソッドが変わっていない")

    def test_no_names_are_added(self):
        """追加の関数・メソッド・定数は無い。"""
        self.assertEqual(sorted(n for n in self.new[0] if n not in self.old[0]), [])
        self.assertEqual(sorted(n for n in self.new[1] if n not in self.old[1]), [])

    def test_existing_constants_imports_and_other_statements_are_unchanged(self):
        old_c, new_c = self.old[1], self.new[1]
        self.assertEqual(sorted(n for n in old_c if n not in new_c), [], "既存の定数が消えている")
        self.assertEqual(sorted(n for n, s in old_c.items() if n in new_c and new_c[n] != s), [], "既存の定数が変わっている")
        self.assertEqual(self.old[2], self.new[2], "import が変わっている")
        self.assertEqual(self.old[3], self.new[3], "関数/定数/import 以外のトップレベル文が変わっている")
        self.assertEqual(self.old[4], self.new[4], "クラスの骨格 (継承・クラス直下の文) が変わっている")

    def test_each_method_changed_only_as_specified(self):
        """各メソッドの変更は仕様の行だけ: 仕様の変更 (report_text_html などで包む・sandbox 属性・http/https の確認・
        escHtml・aid_js / rank_safe・marked の行) を元に戻すと、_14 のメソッドと AST が一致する。戻した回数も仕様どおり。"""
        for name, (make, expected, old_marked) in UNDO_SPECS.items():
            with self.subTest(method=name):
                old_fn = method_node(self.baseline, "HTMLReportGenerator", name)
                new_fn = method_node(self.target, "HTMLReportGenerator", name)
                undo = make()
                new_norm = undo.visit(ast.parse(ast.unparse(new_fn)).body[0])
                got = {k: v for k, v in undo.n.items() if v}
                self.assertEqual(got, expected, "仕様の変更の回数が違う")
                old_undo = _Undo(str_edits=[(MARKED_LINE_RE, "")])
                old_norm = old_undo.visit(ast.parse(ast.unparse(old_fn)).body[0])
                self.assertEqual(sum(old_undo.n.values()), old_marked, "_14 の marked の行の数が前提と違う")
                self.assertEqual(ast.dump(new_norm), ast.dump(old_norm),
                                 "仕様以外の変更がある\n" + short_diff(ast.unparse(old_norm), ast.unparse(new_norm)))


@functools.lru_cache(maxsize=None)
def load_rev(fname):
    """tool フォルダの指定リビジョンを別名で読み込む (出力の比較用)。"""
    path = _loader.rev_path(fname)
    oto()                                                  # 先に最小スタブを入れておく
    mod_name = "oto_a10b_" + re.sub(r"\W", "_", fname[:-3])
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    with tempdir_cwd(), contextlib.redirect_stdout(io.StringIO()):
        spec.loader.exec_module(mod)
    return mod


TS_RE = re.compile(r"\d{4}[-/]\d{2}[-/]\d{2}[ T]\d{2}:\d{2}(?::\d{2})?|\d{8}_\d{6}")


def norm_ts(s):
    return TS_RE.sub("<TS>", s)


class TestSameOutputAsRev14ForPlainInput(unittest.TestCase):
    """特殊文字の無い入力では、_15 の出力は _14 と同じ (外した marked の script タグと、仕様で変えた JS の行
    (検索レポートの escHtml・autoLink、共通JS の regenerateQuestions)・iframe の sandbox 属性を除く。生成日時も除く)。"""

    @classmethod
    def setUpClass(cls):
        rev_paths()
        cls.m14, cls.m15 = load_rev(OLD_REV), load_rev(NEW_REV)

    def both(self, render):
        out = []
        for mod in (self.m14, self.m15):
            with tempdir_cwd() as tmp, contextlib.redirect_stdout(io.StringIO()):
                out.append(norm_ts(render(mod, tmp)))
        return out

    def assert_same(self, a, b):
        self.assertEqual(a, b, "\n" + short_diff(a, b))

    def undo15(self, text, edits):
        for pat, rep, count in edits:
            text, k = re.subn(pat, rep, text, flags=re.S)
            self.assertEqual(k, count, f"_15 の出力の {pat[:40]} の数が違う")
        return text

    def test_search_report(self):
        def render(mod, tmp):
            return render_search(mod, *search_inputs(plain, URL_PLAIN, HTML_BODY_PLAIN), os.path.join(tmp, "o"))
        o14, o15 = self.both(render)
        o15 = self.undo15(o15, [(ESC_FN_RE, "", 1), (AUTOLINK_DISPLAY_RE, "displayUrl", 1),
                                (re.escape(SANDBOX_ATTR), "", 2)])
        self.assert_same(o14, o15)

    def test_review_report(self):
        achs = [achievement(f"Ochi::conv-{i}", rank=r) for i, r in enumerate(("S", "A", "B", "P"))]
        achs.append(achievement("Ochi::manual_x", rank="A", is_manual=True, source_thread_ids=[]))
        o14, o15 = self.both(lambda mod, tmp: render_review(mod, achs, tmp))
        self.assert_same(o14, o15)

    def test_overview_reports(self):
        for kind in ("project", "staff"):
            for label, render in (("normal", lambda mod, tmp: overview_html(mod, kind, tmp)),
                                  ("error", lambda mod, tmp: overview_error_html(mod, kind, plain("err"), tmp)),
                                  ("error_none", lambda mod, tmp: overview_error_html(mod, kind, None, tmp))):
                with self.subTest(kind=kind, data=label):
                    o14, o15 = self.both(render)
                    o14, k = re.subn(MARKED_LINE_RE, "", o14)
                    self.assertEqual(k, 1, "_14 の出力に marked の行が1つない")
                    o15 = self.undo15(o15, [(r"\$\{escHtml\(q\)\}", "${q}", 1)])
                    self.assert_same(o14, o15)

    def test_cockpit_report_error(self):
        for summary in (plain("err"), None):
            with self.subTest(summary=summary):
                o14, o15 = self.both(lambda mod, tmp: cockpit_error_html(mod, summary, tmp))
                o15 = self.undo15(o15, [(r"\$\{escHtml\(q\)\}", "${q}", 1)])
                self.assert_same(o14, o15)

    def test_action_dashboard(self):
        st = statuses("in_progress", "done", "high", "top")
        o14, o15 = self.both(lambda mod, tmp: action_html(mod, st, tmp))
        self.assert_same(o14, o15)

    def test_rev14_had_the_injection(self):
        """(テストの効き目の確認) _14 では、悪意のある件名などでタグが増えていた・iframe に sandbox が無かった・
        振り返りの ' で JS の引数を抜けられた。"""
        with tempdir_cwd() as tmp, contextlib.redirect_stdout(io.StringIO()):
            p = parse_html(render_search(self.m14, *search_inputs(plain, URL_PLAIN, HTML_BODY_PLAIN), os.path.join(tmp, "a")))
            e = parse_html(render_search(self.m14, *search_inputs(evil, URL_EVIL, HTML_BODY_EVIL), os.path.join(tmp, "b")))
            self.assertNotEqual(skeleton(p), skeleton(e))
            self.assertTrue(all("sandbox" not in f.attrs for f in find(e, tag="iframe")))
            rows = review_rows(parse_html(render_review(self.m14, [achievement("Ochi::x'); P('aid1'); ('")], tmp)))
            btn = find(rows["Ochi::x'); P('aid1'); ('"][0], tag="button", cls="rv-hide-btn")[0]
            self.assertIsNone(parse_js_call(btn.attrs["onclick"], "reviewHide"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
