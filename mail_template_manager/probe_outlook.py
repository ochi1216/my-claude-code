# -*- coding: utf-8 -*-
"""
probe_outlook.py
Mail Template Manager — M0 実機プローブ
Version: 1.0.0

このスクリプトは「設計を決めるために、越智さんの会社PCでしか確かめられないこと」を
1回だけ測るための診断ツールである。機能ツールではないため、リポジトリの
`ツール名_yyyymmdd_NN.py` 形式のバージョン管理対象外とする
（`outlook_total_organizer/diagnose_archive.py` と同じ扱い）。

■ 絶対に守る制約
  - メールを一切送信しない（`.Send()` を呼ぶコードは存在しない）
  - 作成したメールアイテムはすべて削除してから終了する
  - 1つの項目が失敗しても、残りの項目を最後まで実行する
  - 依存は標準ライブラリ ＋ win32com のみ。msal が無ければ Graph 項目だけスキップする
    （社内プロキシ・証明書の問題で pip install が詰まると、プローブ自体が動かなくなるため）

■ 出力
  - probe_result_YYYYMMDD_HHMM.txt … 診断結果（UTF-8 BOM付き。メモ帳で文字化けしないため）
  - probe_signature.html            … Outlookが自動挿入する署名HTMLの実物

■ 設計上の注意
  win32com はモジュールのトップレベルでは import しない。レポート生成やHTML組み立ての
  ロジックを Windows 以外（開発環境の Linux）でも単体テストできるようにするためである。
"""

import base64
import json
import os
import sys
import traceback
from datetime import datetime

VERSION = "1.0.0"

# 判定ステータス
ST_OK = "OK"
ST_WARN = "注意"
ST_NG = "NG"
ST_SKIP = "SKIP"

# この3項目が NG だと「Outlookの下書きを直接作る方式(M1-α)」が成立しない
CRITICAL_ITEM_NOS = (1, 2, 3)

# 本文の差し込みが効いているかを確認するための目印
BODY_MARKER = "MTM_PROBE_BODY_MARKER"

# 項目6で使う、日本語フォルダ名を含む長いSharePoint URL（例1の「２０２６年」を模したもの）
SAMPLE_LONG_URL = (
    "https://nexperia.sharepoint.com/sites/JapanSite/Shared%20Documents/"
    "Export%20Report/2026%E5%B9%B4/09%E6%9C%88/"
    "?csf=1&web=1&e=AbCdEf&xsdata=MDV8MDJ8fDBhMWIyYzNkNGU1ZjZhN2I4YzlkMGUxZjJhM2I0YzVk"
)


# ============================================================
# 純粋関数（Windows非依存。tests/ で単体テストする）
# ============================================================

def escape_html_attr(value):
    """HTML属性値として安全な文字列に変換する。"""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def escape_html_text(value):
    """HTMLのテキストノードとして安全な文字列に変換する。"""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def build_link_html(url, text):
    """`<a href="...">text</a>` を組み立てる。

    URLを生のまま本文に書く方式は使わない。Outlookのエディタが長いURLを
    途中で分断することがあるためで、これは項目6で実測する。
    """
    return '<a href="{0}">{1}</a>'.format(escape_html_attr(url), escape_html_text(text))


def prepend_body_html(signature_html, body_html):
    """Outlookが挿入した署名HTMLの本文領域の先頭に、本文を差し込む。

    `HTMLBody` に単純代入すると署名が消えるため、署名HTMLの `<body>` 直後に
    本文を挿入して「署名を下に残す」。`<body>` が見つからない場合は、
    本文を前に単純連結する（署名が失われないことを優先する）。
    """
    if not signature_html:
        return body_html
    lowered = signature_html.lower()
    start = lowered.find("<body")
    if start == -1:
        return body_html + signature_html
    end = signature_html.find(">", start)
    if end == -1:
        return body_html + signature_html
    return signature_html[: end + 1] + body_html + signature_html[end + 1:]


def encode_share_url(url):
    """SharePointの共有URLを Microsoft Graph の `/shares/{id}` 形式に変換する。

    Graph の仕様どおり、URLをbase64url化して `u!` を前置し、末尾の `=` を取り除く。
    """
    encoded = base64.urlsafe_b64encode(url.encode("utf-8")).decode("ascii")
    return "u!" + encoded.rstrip("=")


def summarize_status(items):
    """全項目の判定から、総合判定の3行を組み立てる。

    戻り値は (見出し, 方針の行, 補足の行) のタプル。
    """
    ng_nos = [it.no for it in items if it.status == ST_NG]
    warn_nos = [it.no for it in items if it.status == ST_WARN]
    critical_ng = [no for no in ng_nos if no in CRITICAL_ITEM_NOS]
    rerun_nos = [it.no for it in items if getattr(it, "rerun_needed", False)]

    # 環境を直せば解決する失敗は、設計の分岐ではない。
    # 「M1-βへ切り替えます」と誤って結論づけないよう、最優先で判定する。
    if rerun_nos:
        headline = "再実行が必要です（PCの準備が足りていません）"
        policy = "→ 下の [{0}] に書いてある準備をしてから、もう一度実行してください。".format(
            rerun_nos[0]
        )
        note = "→ 設計の判断は、その結果を見てから行います。今回の結果は送っていただかなくて結構です。"
        return headline, policy, note

    if critical_ng:
        headline = "要再検討（Outlookの下書きを直接作る方式が使えません）"
        policy = (
            "→ 設計方針「M1-β（本文と宛先を .eml ファイルで受け渡す）」へ切り替えます。"
        )
    elif ng_nos:
        headline = "条件付きOK（{0}件の要検討あり）".format(len(ng_nos))
        policy = "→ 設計方針「M1-α（Outlookの下書きを直接作る）」で進められます。"
    elif warn_nos:
        headline = "OK（{0}件の注意あり）".format(len(warn_nos))
        policy = "→ 設計方針「M1-α（Outlookの下書きを直接作る）」で進められます。"
    else:
        headline = "OK"
        policy = "→ 設計方針「M1-α（Outlookの下書きを直接作る）」で進められます。"

    if ng_nos:
        note = "→ 項目 {0} が NG のため、その部分の作り方を変更します。越智さんの追加作業はありません。".format(
            " / ".join("[{0}]".format(no) for no in ng_nos)
        )
    elif warn_nos:
        note = "→ 項目 {0} に注意があります。設計側で吸収します。越智さんの追加作業はありません。".format(
            " / ".join("[{0}]".format(no) for no in warn_nos)
        )
    else:
        note = "→ すべて想定どおりでした。越智さんの追加作業はありません。"

    return headline, policy, note


class ProbeItem(object):
    """診断1項目分の結果。"""

    def __init__(self, no, title, checked):
        self.no = no
        self.title = title
        self.checked = checked          # 「確かめたこと」
        self.status = ST_SKIP
        self.results = []               # 「結果」の行
        self.decides = []               # 「これで決まること」の行
        self.asks = []                  # 越智さんにしか答えられない [お願い]
        self.rerun_needed = False       # 環境を直して再実行すれば解決する失敗か

    def ok(self, *lines):
        self.status = ST_OK
        self.results.extend(lines)

    def warn(self, *lines):
        self.status = ST_WARN
        self.results.extend(lines)

    def ng(self, *lines):
        self.status = ST_NG
        self.results.extend(lines)

    def skip(self, *lines):
        self.status = ST_SKIP
        self.results.extend(lines)

    def decide(self, *lines):
        self.decides.extend(lines)

    def ask(self, *lines):
        self.asks.extend(lines)


class ProbeReport(object):
    """診断結果全体を、越智さんが1人で読める形に整形する。"""

    LINE = "-" * 64
    DLINE = "=" * 64

    def __init__(self, meta):
        self.meta = meta
        self.items = []

    def add(self, item):
        self.items.append(item)

    def render(self):
        out = []
        out.append(self.DLINE)
        out.append(" Mail Template Manager  実機プローブ 結果")
        label_width = max(self._width(key) for key, _ in self.meta) if self.meta else 0
        for key, value in self.meta:
            padding = " " * (label_width - self._width(key))
            out.append(" {0}{1} : {2}".format(key, padding, value))
        out.append(self.DLINE)
        out.append("")
        out.append(" このファイルは「設計を決めるために、越智さんのPCでしか確かめられない")
        out.append(" ことを1回だけ測った結果」です。何も送信していません。作成したメールは")
        out.append(" すべて削除済みです。")
        out.append("")

        headline, policy, note = summarize_status(self.items)
        out.append(" ▼ 総合判定 : {0}".format(headline))
        out.append("    {0}".format(policy))
        out.append("    {0}".format(note))
        out.append("")
        out.append("")

        for item in self.items:
            out.append(self.LINE)
            out.append("[{0}] {1}{2}[{3}]".format(
                item.no,
                item.title,
                " " * max(1, 52 - self._width(item.title) - len(str(item.no))),
                item.status,
            ))
            out.append(self.LINE)
            out.append(" 確かめたこと : {0}".format(item.checked))
            if item.results:
                out.append(" 結果         : {0}".format(item.results[0]))
                for line in item.results[1:]:
                    out.append("                {0}".format(line))
            if item.decides:
                out.append(" これで決まること :")
                for line in item.decides:
                    out.append("   {0}".format(line))
            if item.asks:
                out.append("")
                for line in item.asks:
                    out.append(" [お願い] {0}".format(line))
            out.append("")

        out.append("")
        out.append(self.DLINE)
        out.append(" ▼ 次にお願いしたいこと")
        out.append(self.DLINE)

        if any(getattr(it, "rerun_needed", False) for it in self.items):
            # 環境が整っていない状態の結果を送っていただいても、設計の判断材料にならない。
            # ここで「ファイルを送ってください」と書くと、往復が1回無駄になる。
            for item in self.items:
                if getattr(item, "rerun_needed", False):
                    out.append(" 1. 上の [{0}] に書いてある準備をしてください。".format(item.no))
            out.append(" 2. もう一度 run_probe.bat を実行してください。")
            out.append("")
            out.append(" 準備ができない場合や、やり方が分からない場合はお知らせください。")
            out.append("")
            out.append(" このウィンドウは Enter キーで閉じます。")
            out.append(self.DLINE)
            return "\n".join(out)

        out.append(" 1. このフォルダにある次の2つのファイルを送ってください。")
        out.append("      {0}".format(self.meta_value("結果ファイル")))
        out.append("      probe_signature.html             (署名の実物)")

        asks = [(it.no, line) for it in self.items for line in it.asks]
        if asks:
            out.append(" 2. 次の {0} 点にお答えください（本文中の [お願い] の再掲です）。".format(len(asks)))
            for no, line in asks:
                out.append("      [{0}] {1}".format(no, line))
        out.append("")
        out.append(" 何か1つでも [NG] があっても問題ありません。")
        out.append(" 設計をそれに合わせるための調査です。")
        out.append("")
        out.append(" このウィンドウは Enter キーで閉じます。")
        out.append(self.DLINE)
        return "\n".join(out)

    def meta_value(self, key):
        for k, v in self.meta:
            if k == key:
                return v
        return ""

    @staticmethod
    def _width(text):
        """全角文字を2文字幅として数え、判定欄の位置をおおよそ揃える。"""
        width = 0
        for ch in text:
            width += 2 if ord(ch) > 0x2E80 else 1
        return width


# ============================================================
# 実行基盤
# ============================================================

class ProbeContext(object):
    """診断中に持ち回る状態（Outlook接続、後始末が必要なアイテム等）。"""

    def __init__(self, out_dir, config):
        self.out_dir = out_dir
        self.config = config
        self.outlook = None
        self.namespace = None
        self.signature_html = ""
        self.cleanup_entry_ids = []     # 後始末する下書きの EntryID
        self.cleanup_items = []         # まだ保存していないメールアイテム


def run_check(report, no, title, checked, func, ctx):
    """1項目を実行する。例外が出ても握りつぶし、次の項目へ進む。

    1項目目で落ちて情報がゼロになるのが最悪のシナリオなので、
    すべての項目を互いに独立させている。
    """
    item = ProbeItem(no, title, checked)
    try:
        func(item, ctx)
    except Exception as exc:                                  # noqa: BLE001
        item.status = ST_NG
        item.results.append("例外が発生しました: {0}: {1}".format(type(exc).__name__, exc))
        detail = traceback.format_exc().strip().splitlines()
        for line in detail[-4:]:
            item.results.append(line.strip())
    report.add(item)
    return item


def safe_print(text):
    """コンソールの文字コードが日本語を扱えない場合でも落ちないようにする。"""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", "replace").decode("ascii"))


# ============================================================
# 各診断項目
# ============================================================

def check_01_connect(item, ctx):
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        # 新しいPCで最初に起きる可能性が最も高い失敗。
        # 「ModuleNotFoundError」とだけ出しても越智さんは次の一手が分からないため、
        # 何をすれば直るかをその場で示し、再実行が必要であることを総合判定にも反映する。
        item.ng(
            "Outlook を操作するための部品（pywin32）が入っていません",
        )
        item.rerun_needed = True
        item.decide(
            "コマンドプロンプトで次を実行してから、もう一度 run_probe.bat を実行してください。",
            "    pip install pywin32",
            "※ 社内ネットワークの都合で pip が使えない場合はお知らせください。別の方法をご案内します。",
        )
        return

    pythoncom.CoInitialize()
    ctx.outlook = win32com.client.Dispatch("Outlook.Application")
    ctx.namespace = ctx.outlook.GetNamespace("MAPI")
    version = str(ctx.outlook.Version)

    item.ok(
        "接続成功",
        "Application.Version = {0}".format(version),
    )
    item.decide(
        "本ツールは Outlook の下書きを直接作る方式で作れます。",
        "※「新しい Outlook」に切り替わると、この方式は使えなくなります。",
    )
    item.ask(
        "Outlook の右上に「新しい Outlook」という切替スイッチが表示されているか、"
        "スクリーンショットを1枚いただけますか。",
    )


def check_02_create_item(item, ctx):
    if ctx.outlook is None:
        item.skip("項目[1]でOutlookに接続できなかったため、実行できませんでした。")
        return

    mail = ctx.outlook.CreateItem(0)        # 0 = olMailItem
    ctx.cleanup_items.append(mail)
    item.ok("成功（作成したメールは最後に削除します。送信はしません）")
    item.decide("カードから下書きを作る機能が実装できます。")


def check_03_signature(item, ctx):
    if ctx.outlook is None:
        item.skip("項目[1]でOutlookに接続できなかったため、実行できませんでした。")
        return

    mail = ctx.outlook.CreateItem(0)
    ctx.cleanup_items.append(mail)

    # GetInspector に触れるだけで Outlook は署名を挿入する。
    # 画面を開かずに済むため、Display より安全（M3の無人実行にも直結する）。
    method = "GetInspector（画面を開かない方法）"
    mail.GetInspector
    signature = mail.HTMLBody or ""

    if not signature.strip():
        # 署名が入らなかった場合のみ、実際にウィンドウを開いて再確認する。
        method = "Display（ウィンドウを開く方法）"
        mail.Display(False)
        signature = mail.HTMLBody or ""

    if not signature.strip():
        item.ng(
            "署名を取得できませんでした（本文が空でした）",
            "試した方法: GetInspector → Display の両方",
        )
        item.decide(
            "署名は本ツール側で用意する方式に変更します（設定画面で登録いただきます）。",
        )
        return

    ctx.signature_html = signature
    sig_path = os.path.join(ctx.out_dir, "probe_signature.html")
    with open(sig_path, "w", encoding="utf-8") as fh:
        fh.write(signature)

    # 署名の上に本文を差し込み、署名が下に残るかを確認する
    body = "<p>{0}</p>".format(BODY_MARKER)
    merged = prepend_body_html(signature, body)
    mail.HTMLBody = merged
    after = mail.HTMLBody or ""

    body_kept = BODY_MARKER in after
    # 署名の末尾付近の文字列が残っているかで、署名の保持を判定する
    tail = signature.strip()[-200:]
    sig_kept = _contains_loosely(after, tail)

    lines = [
        "署名を取得できました（HTML {0:,} 文字 / 取得方法: {1}）".format(len(signature), method),
        "署名の実物 → probe_signature.html に保存しました",
        "本文の差し込み : {0}".format("成功" if body_kept else "失敗"),
        "署名の保持     : {0}".format("成功" if sig_kept else "失敗"),
    ]
    if body_kept and sig_kept:
        item.ok(*lines)
        item.decide(
            "いつもの署名を消さずに、本文だけ差し替えられます。",
            "※ 署名HTMLの中身を見て、本文で使えるタグを決めます（こちらで判断します）。",
        )
    else:
        item.ng(*lines)
        item.decide(
            "署名の差し込み方を変更します（本文の末尾に署名を再結合する方式を検討します）。",
        )


def _contains_loosely(haystack, needle):
    """空白と改行の違いを無視して部分一致を判定する。

    Outlookは代入したHTMLを整形し直すことがあるため、完全一致では判定できない。
    """
    def normalize(text):
        return "".join(text.split())

    normalized_needle = normalize(needle)
    if not normalized_needle:
        return False
    return normalize(normalized_needle) in normalize(haystack)


def check_04_save_draft(item, ctx):
    if ctx.outlook is None:
        item.skip("項目[1]でOutlookに接続できなかったため、実行できませんでした。")
        return

    mail = ctx.outlook.CreateItem(0)
    mail.Subject = "[MTM PROBE] 下書き保存テスト（送信しません）"
    base = ctx.signature_html if ctx.signature_html else ""
    mail.HTMLBody = prepend_body_html(base, "<p>{0}</p>".format(BODY_MARKER))
    mail.Save()

    entry_id = str(mail.EntryID)
    ctx.cleanup_entry_ids.append(entry_id)

    reopened = ctx.namespace.GetItemFromID(entry_id)
    reopened_body = reopened.HTMLBody or ""
    body_kept = BODY_MARKER in reopened_body
    sig_kept = True
    if ctx.signature_html:
        tail = ctx.signature_html.strip()[-200:]
        sig_kept = _contains_loosely(reopened_body, tail)

    lines = [
        "成功。下書きフォルダに保存し、読み直せました",
        "本文の保持 : {0}".format("成功" if body_kept else "失敗"),
        "署名の保持 : {0}".format(
            "成功" if sig_kept else "失敗"
        ) if ctx.signature_html else "署名の保持 : 判定せず（項目[3]で署名を取得できなかったため）",
        "（確認後に削除します）",
    ]
    if body_kept and sig_kept:
        item.ok(*lines)
        item.decide(
            "将来「毎月1日に自動で下書きを用意しておく」機能(M3)を、",
            "画面を開かずに実現できます。これができないと M3 は別方式が必要でした。",
        )
    else:
        item.ng(*lines)
        item.decide(
            "無人での下書き作成(M3)は、画面を開く方式を検討します。",
        )


def check_05_accounts(item, ctx):
    if ctx.outlook is None:
        item.skip("項目[1]でOutlookに接続できなかったため、実行できませんでした。")
        return

    accounts = ctx.namespace.Session.Accounts
    count = int(accounts.Count)
    lines = ["アカウント {0} 件".format(count)]
    names = []
    for idx in range(1, count + 1):
        account = accounts.Item(idx)
        try:
            smtp = str(account.SmtpAddress)
        except Exception:                                     # noqa: BLE001
            smtp = "(アドレス不明)"
        display = str(account.DisplayName)
        names.append(smtp)
        lines.append("  {0}. {1}  ({2})".format(idx, smtp, display))

    # 送信元の切り替えが使えるかを確認する（送信はしない）
    mail = ctx.outlook.CreateItem(0)
    ctx.cleanup_items.append(mail)

    try:
        mail.SendUsingAccount = accounts.Item(1)
        using_account = "成功"
    except Exception as exc:                                  # noqa: BLE001
        using_account = "失敗（{0}）".format(type(exc).__name__)

    try:
        mail.SentOnBehalfOfName = names[0] if names else ""
        on_behalf = "成功"
    except Exception as exc:                                  # noqa: BLE001
        on_behalf = "失敗（{0}）".format(type(exc).__name__)

    lines.append("SendUsingAccount による切替   : {0}".format(using_account))
    lines.append("SentOnBehalfOfName による代理 : {0}".format(on_behalf))

    if using_account == "成功":
        item.ok(*lines)
    else:
        item.warn(*lines)
    item.decide("カードごとに「どのアドレスから送るか」を選べるようにします。")
    item.ask(
        "Export Report / Over Time Report は、上記のどのアドレスから送っていますか。",
    )


def check_06_long_link(item, ctx):
    if ctx.outlook is None:
        item.skip("項目[1]でOutlookに接続できなかったため、実行できませんでした。")
        return

    link_html = build_link_html(SAMPLE_LONG_URL, "09")
    mail = ctx.outlook.CreateItem(0)
    mail.Subject = "[MTM PROBE] リンクテスト（送信しません）"
    mail.HTMLBody = "<p>Export: {0}</p>".format(link_html)
    mail.Save()

    entry_id = str(mail.EntryID)
    ctx.cleanup_entry_ids.append(entry_id)

    reopened = ctx.namespace.GetItemFromID(entry_id)
    after = reopened.HTMLBody or ""

    kept = SAMPLE_LONG_URL in after or _contains_loosely(after, SAMPLE_LONG_URL)
    lines = [
        "入れたURL   : {0}".format(SAMPLE_LONG_URL[:60] + "..."),
        "URLの長さ   : {0} 文字".format(len(SAMPLE_LONG_URL)),
        "保存後の保持 : {0}".format("リンクは壊れていません" if kept else "リンクが変化しました"),
    ]
    if not kept:
        excerpt = _extract_href(after)
        lines.append("保存後のhref : {0}".format(excerpt[:120] if excerpt else "(取得できず)"))

    if kept:
        item.ok(*lines)
        item.decide("日本語フォルダ名を含む長いリンクを、そのまま本文に埋め込めます。")
    else:
        item.ng(*lines)
        item.decide(
            "URLの持ち方を変更します（短縮した共有リンク形式の採用を検討します）。",
            "→ 本ツール側で対応します。越智さんの作業は不要です。",
        )


def _extract_href(html):
    """HTMLから最初の href の値を取り出す（診断の報告用）。"""
    lowered = html.lower()
    idx = lowered.find("href=")
    if idx == -1:
        return ""
    rest = html[idx + 5:]
    if not rest:
        return ""
    quote = rest[0]
    if quote in ('"', "'"):
        end = rest.find(quote, 1)
        return rest[1:end] if end != -1 else rest[1:]
    end = rest.find(">")
    return rest[:end] if end != -1 else rest


def check_07_user_properties(item, ctx):
    if ctx.outlook is None:
        item.skip("項目[1]でOutlookに接続できなかったため、実行できませんでした。")
        return

    mail = ctx.outlook.CreateItem(0)
    mail.Subject = "[MTM PROBE] 目印テスト（送信しません）"
    mail.Body = "probe"

    # 1 = olText, True = このフォルダのフィールドとして追加
    prop_card = mail.UserProperties.Add("MTM_CardId", 1, True)
    prop_card.Value = "card_0001"
    prop_period = mail.UserProperties.Add("MTM_PeriodId", 1, True)
    prop_period.Value = "2026-08"
    mail.Save()

    entry_id = str(mail.EntryID)
    ctx.cleanup_entry_ids.append(entry_id)

    reopened = ctx.namespace.GetItemFromID(entry_id)
    read_card = reopened.UserProperties.Find("MTM_CardId")
    read_period = reopened.UserProperties.Find("MTM_PeriodId")

    card_value = str(read_card.Value) if read_card is not None else None
    period_value = str(read_period.Value) if read_period is not None else None

    lines = [
        "書き込み : 成功",
        "読み直し : MTM_CardId = {0}".format(card_value if card_value else "(読めませんでした)"),
        "           MTM_PeriodId = {0}".format(period_value if period_value else "(読めませんでした)"),
    ]

    if card_value == "card_0001" and period_value == "2026-08":
        item.ok(*lines)
        item.decide(
            "「このメールはもう送ったか」を、件名や本文を自由に書き換えても正しく追跡できます。",
            "→ 一覧の「未送信」バッジが嘘をつかなくなります。",
        )
    else:
        item.ng(*lines)
        item.decide(
            "自動での送信検出はあきらめ、一覧に「送信しました」チェックボックスを置く方式にします。",
            "→ 自動化は減りますが、バッジが嘘をつくことはありません。",
        )


def check_08_eml(item, ctx):
    eml_path = os.path.join(ctx.out_dir, "probe_sample.eml")
    body_html = "<html><body><p>MTM probe sample.</p></body></html>"
    lines = [
        "To: probe@example.com",
        "Subject: [MTM PROBE] eml test",
        "MIME-Version: 1.0",
        "Content-Type: text/html; charset=utf-8",
        "",
        body_html,
    ]
    with open(eml_path, "w", encoding="utf-8") as fh:
        fh.write("\r\n".join(lines))

    opened = False
    detail = ""
    if hasattr(os, "startfile"):
        try:
            os.startfile(eml_path)                            # noqa: S606
            opened = True
        except Exception as exc:                              # noqa: BLE001
            detail = "{0}: {1}".format(type(exc).__name__, exc)
    else:
        detail = "この環境には os.startfile がありません（Windows以外）"

    if opened:
        item.ok(
            "probe_sample.eml を作成し、開く操作を実行しました",
        )
    else:
        item.warn(
            "probe_sample.eml は作成しましたが、開けませんでした",
            detail,
        )
    item.decide(
        "将来 Outlook が「新しい Outlook」に切り替わった場合の代替手段になります。",
    )
    item.ask(
        "画面に開いたメールについて、(a) 何のアプリで開きましたか"
        "（Outlook / 新しいOutlook / その他） (b) 宛先と件名は入っていましたか。",
    )


def check_09_graph(item, ctx):
    target_url = (ctx.config or {}).get("probe_target_folder_url", "")
    if not target_url:
        item.skip(
            "スキップしました",
            "理由: config.json の probe_target_folder_url が未設定です",
            "      （例1の上位フォルダURLをいただいてから測ります）",
        )
        return

    try:
        import msal                                           # noqa: F401
    except ImportError:
        item.skip(
            "スキップしました",
            "理由: msal が未インストールです（この項目だけ飛ばしました）",
        )
        return

    import urllib.request

    tenant_id, client_id, source = _resolve_credentials(ctx.config)
    if not tenant_id or not client_id:
        item.skip(
            "スキップしました",
            "理由: tenant_id / client_id を取得できませんでした",
        )
        return

    import msal as _msal

    app = _msal.PublicClientApplication(
        client_id, authority="https://login.microsoftonline.com/{0}".format(tenant_id)
    )
    scopes = ["https://graph.microsoft.com/Sites.Read.All"]
    flow = app.initiate_device_flow(scopes=scopes)
    if "user_code" not in flow:
        item.ng("デバイスコードの取得に失敗しました", str(flow.get("error_description", "")))
        return

    safe_print("")
    safe_print("  [9] SharePoint の確認のため、1回だけサインインしてください。")
    safe_print("      " + flow["message"])
    safe_print("")

    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        item.ng("サインインに失敗しました", str(result.get("error_description", "")))
        return

    share_id = encode_share_url(target_url)
    api = "https://graph.microsoft.com/v1.0/shares/{0}/driveItem/children?$top=25".format(share_id)
    request = urllib.request.Request(
        api, headers={"Authorization": "Bearer " + result["access_token"]}
    )
    with urllib.request.urlopen(request, timeout=30) as response:   # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))

    children = payload.get("value", [])
    lines = [
        "認証成功（認証情報の取得元: {0}）".format(source),
        "子アイテム {0} 件を取得しました".format(len(children)),
    ]
    for child in children[:10]:
        kind = "フォルダ" if "folder" in child else "ファイル"
        lines.append("  - [{0}] {1}".format(kind, child.get("name", "")))
        lines.append("        webUrl: {0}".format((child.get("webUrl") or "")[:80]))

    has_web_url = any(child.get("webUrl") for child in children)
    if children and has_web_url:
        item.ok(*lines)
        item.decide(
            "対象フォルダの中身を一覧し、候補として画面に並べられます（M1の中核機能）。",
        )
    else:
        item.warn(*lines)
        item.decide("取得はできましたが、中身が空か webUrl が取れませんでした。URLを再確認します。")


def _resolve_credentials(config):
    """tenant_id / client_id を、自分の設定 → 既存ツールの設定 の順に探す。

    `document_search_manager` と同じ借用方式。新規のEntra ID権限申請は発生しない。
    """
    config = config or {}
    tenant_id = config.get("tenant_id", "")
    client_id = config.get("client_id", "")
    if tenant_id and client_id:
        return tenant_id, client_id, "本ツールの config.json"

    here = os.path.dirname(os.path.abspath(__file__))
    candidates = []
    explicit = config.get("credentials_from", "")
    if explicit:
        candidates.append(explicit)
    candidates.append(os.path.join(here, "..", "po_database_organizer", "config.json"))
    candidates.append(os.path.join(here, "..", "onenote_report_generator", "config.json"))

    for path in candidates:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:                                     # noqa: BLE001
            continue
        found_tenant = data.get("tenant_id") or data.get("TENANT_ID") or ""
        found_client = data.get("client_id") or data.get("CLIENT_ID") or ""
        if found_tenant and found_client:
            return found_tenant, found_client, os.path.normpath(path)

    return "", "", ""


# ============================================================
# 後始末
# ============================================================

def cleanup(ctx):
    """作成したメールをすべて削除する。失敗しても診断結果には影響させない。"""
    removed = 0
    failed = 0

    for mail in ctx.cleanup_items:
        try:
            mail.Close(1)           # 1 = olDiscard（保存せずに閉じる）
            removed += 1
        except Exception:                                     # noqa: BLE001
            failed += 1

    for entry_id in ctx.cleanup_entry_ids:
        try:
            saved = ctx.namespace.GetItemFromID(entry_id)
            saved.Delete()
            removed += 1
        except Exception:                                     # noqa: BLE001
            failed += 1

    return removed, failed


# ============================================================
# エントリポイント
# ============================================================

def load_config(here):
    path = os.path.join(here, "config.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:                                         # noqa: BLE001
        return {}


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    now = datetime.now()
    result_name = "probe_result_{0}.txt".format(now.strftime("%Y%m%d_%H%M"))
    result_path = os.path.join(here, result_name)

    safe_print("")
    safe_print("=" * 64)
    safe_print(" Mail Template Manager  実機プローブ")
    safe_print("=" * 64)
    safe_print(" これから Outlook と SharePoint の動作を確認します。")
    safe_print("")
    safe_print("   ・メールのウィンドウが1つ開く場合があります")
    safe_print("   ・何も送信しません")
    safe_print("   ・作成したメールは自動で削除します")
    safe_print("   ・所要 30秒ほどです")
    safe_print("")
    safe_print("=" * 64)
    safe_print("")

    config = load_config(here)
    ctx = ProbeContext(here, config)

    report = ProbeReport([
        ("実行日時", now.strftime("%Y-%m-%d %H:%M:%S")),
        ("PC名", os.environ.get("COMPUTERNAME", "(不明)")),
        ("Python", sys.version.split()[0]),
        ("プローブ", "v{0}".format(VERSION)),
        ("出力先", here),
        ("結果ファイル", result_name),
    ])

    checks = [
        (1, "Outlook への接続とバージョン", "Python から Outlook を操作できるか",
         check_01_connect),
        (2, "メールの新規作成 (CreateItem)", "プログラムから新しいメールを作れるか",
         check_02_create_item),
        (3, "署名の取得と本文の結合",
         "新規メールに Outlook が自動で入れる署名を取り出し、その上に本文を差し込めるか",
         check_03_signature),
        (4, "下書きフォルダへの保存 (.Save)",
         "メールの画面を開かずに、下書きフォルダへ保存できるか", check_04_save_draft),
        (5, "送信元アカウントの構成", "どのアドレスから送れるか（共有アドレスの有無）",
         check_05_accounts),
        (6, "日本語フォルダ名・長いURLのリンク",
         "「2026年」のような日本語名フォルダのSharePointリンクを本文に入れたとき、壊れないか",
         check_06_long_link),
        (7, "メールへの目印の埋め込み (UserProperties)",
         "下書きに見えない目印（カード名・対象月）を付けられるか。保存し直しても残るか",
         check_07_user_properties),
        (8, ".eml ファイルの動作",
         "将来「新しい Outlook」に切り替わった場合の代替手段が使えるか", check_08_eml),
        (9, "SharePoint フォルダの読み取り (Microsoft Graph)",
         "例1の上位フォルダの中身を一覧できるか", check_09_graph),
    ]

    for no, title, checked, func in checks:
        safe_print("  [{0}/{1}] {2} ...".format(no, len(checks), title))
        item = run_check(report, no, title, checked, func, ctx)
        safe_print("        → {0}".format(item.status))

    removed, failed = cleanup(ctx)
    safe_print("")
    safe_print("  後始末: 作成したメール {0} 件を削除しました（失敗 {1} 件）".format(removed, failed))

    text = report.render()
    # UTF-8 BOM付きで書き出す。BOM無しだとメモ帳で文字化けし、報告の往復が1回増えるため。
    with open(result_path, "w", encoding="utf-8-sig") as fh:
        fh.write(text)

    safe_print("")
    safe_print(text)
    safe_print("")
    safe_print("  結果ファイル: {0}".format(result_path))
    safe_print("")

    try:
        input("  Enter キーを押すと終了します...")
    except (EOFError, KeyboardInterrupt):
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
