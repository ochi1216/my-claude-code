# -*- coding: utf-8 -*-
"""M0 実機プローブの、Windows非依存部分の検証

probe_outlook.py は win32com をトップレベルで import しない構造にしてあるため、
開発環境（Linux）でもモジュールとして読み込める。ここではその純粋関数と
レポート整形・例外分離を検証する。

実行: python tests/test_01_probe_core.py
      （まとめて実行する場合は python tests/run_tests.py）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import probe_outlook as p  # noqa: E402

ok, ng = 0, 0


def _has_bare_newline(data):
    """b"\r\n" 以外の裸の \r や \n が含まれるかを調べる。

    "\r\r\n"（今回実機で見つかった不具合の症状）や "\n" 単独は、
    b"\r\n" を全て取り除いた残りに \r か \n が残るかで判定する。
    """
    stripped = data.replace(b"\r\n", b"")
    return b"\r" in stripped or b"\n" in stripped


def check(label, cond, detail=""):
    global ok, ng
    if cond:
        ok += 1
        print("  OK   {0}".format(label))
    else:
        ng += 1
        print("  NG   {0}  {1}".format(label, detail))


# ------------------------------------------------------------
print("\n■ HTMLの組み立て")
# ------------------------------------------------------------

link = p.build_link_html("https://example.com/a?x=1&y=2", "09月")
check("リンクのURLの & がエスケープされる", "&amp;" in link, link)
check("リンクの表示文字がそのまま入る", ">09月</a>" in link, link)

evil = p.build_link_html('https://e.com/"onmouseover="x', '<script>')
check("URL中の二重引用符がエスケープされ、属性を抜け出せない",
      '"onmouseover=' not in evil.replace("&quot;", ""), evil)
check("表示文字のタグがエスケープされる", "<script>" not in evil, evil)

# ------------------------------------------------------------
print("\n■ 署名の上への本文差し込み（項目[3]の中核）")
# ------------------------------------------------------------

SIG = '<html><head><style>.x{}</style></head><body lang="JA"><p>-- <br>Ochi</p></body></html>'
merged = p.prepend_body_html(SIG, "<p>HELLO</p>")
check("本文が差し込まれる", "<p>HELLO</p>" in merged, merged)
check("署名が残る", "Ochi" in merged, merged)
check("本文が署名より前に来る",
      merged.index("HELLO") < merged.index("Ochi"), merged)
check("bodyタグの外に本文を出していない",
      merged.index("<body") < merged.index("HELLO"), merged)
check("headのstyleを壊していない", "<style>.x{}</style>" in merged, merged)

no_body = p.prepend_body_html("<p>署名だけ</p>", "<p>HELLO</p>")
check("bodyタグが無い署名でも、署名を失わない",
      "HELLO" in no_body and "署名だけ" in no_body, no_body)
check("bodyタグが無い場合も本文が先頭に来る",
      no_body.index("HELLO") < no_body.index("署名だけ"), no_body)

check("署名が空なら本文だけを返す",
      p.prepend_body_html("", "<p>HELLO</p>") == "<p>HELLO</p>")
check("bodyの閉じ忘れHTMLでも例外にならず署名を失わない",
      "HELLO" in p.prepend_body_html("<body", "<p>HELLO</p>"))

# 大文字のBODYタグ（Outlookが返すHTMLは書式が一定しない）
upper = p.prepend_body_html("<HTML><BODY><p>SIG</p></BODY></HTML>", "<p>HELLO</p>")
check("BODYタグが大文字でも差し込める",
      upper.index("HELLO") < upper.index("SIG"), upper)

# ------------------------------------------------------------
print("\n■ Graph の共有URLエンコード（項目[9]）")
# ------------------------------------------------------------

share = p.encode_share_url("https://nexperia.sharepoint.com/sites/X/Shared Documents/2026年")
check("u! で始まる", share.startswith("u!"), share)
check("パディングの = を含まない", "=" not in share, share)
check("URL安全な文字だけで構成される",
      all(c.isalnum() or c in "-_!" for c in share), share)

import base64  # noqa: E402

restored = share[2:]
restored += "=" * (-len(restored) % 4)
check("復号すると元のURLに戻る",
      base64.urlsafe_b64decode(restored).decode("utf-8").endswith("2026年"))

# ------------------------------------------------------------
print("\n■ 総合判定（越智さんが最初に読む3行）")
# ------------------------------------------------------------

def make_items(spec):
    """spec: {項目番号: ステータス} から ProbeItem のリストを作る。"""
    items = []
    for no in range(1, 10):
        item = p.ProbeItem(no, "件名{0}".format(no), "確認")
        item.status = spec.get(no, p.ST_OK)
        items.append(item)
    return items


head, policy, note = p.summarize_status(make_items({}))
check("全部OKなら総合判定はOK", head == "OK", head)
check("全部OKならM1-αで進む", "M1-α" in policy, policy)
check("全部OKなら追加作業なしと伝える", "追加作業はありません" in note, note)

head, policy, note = p.summarize_status(make_items({6: p.ST_NG}))
check("重要3項目以外のNGは「条件付きOK」", "条件付きOK" in head, head)
check("条件付きOKでもM1-αで進む", "M1-α" in policy, policy)
check("NGの項目番号を明示する", "[6]" in note, note)
check("NGでも越智さんの作業は不要と伝える", "追加作業はありません" in note, note)

head, policy, note = p.summarize_status(make_items({3: p.ST_NG}))
check("署名(項目3)のNGは「要再検討」", "要再検討" in head, head)
check("重要項目NGならM1-βへ切り替える", "M1-β" in policy, policy)

head, _, note = p.summarize_status(make_items({5: p.ST_WARN}))
check("注意だけならOK扱い", head.startswith("OK"), head)
check("注意の件数を示す", "1件" in head, head)

head, _, _ = p.summarize_status(make_items({4: p.ST_NG, 6: p.ST_NG}))
check("NGが2件なら件数を数える", "2件" in head, head)

# 環境が整っていないだけの失敗を、設計の分岐と取り違えないこと
rerun_items = make_items({1: p.ST_NG})
rerun_items[0].rerun_needed = True
head, policy, note = p.summarize_status(rerun_items)
check("pywin32未導入は「再実行が必要」と判定する", "再実行" in head, head)
check("pywin32未導入をM1-βへの切り替えと誤判定しない",
      "M1-β" not in policy and "M1-α" not in policy, policy)
check("準備すべき項目番号を示す", "[1]" in policy, policy)
check("結果を送らなくてよいと伝える", "送っていただかなくて" in note, note)

# ------------------------------------------------------------
print("\n■ レポートの整形")
# ------------------------------------------------------------

report = p.ProbeReport([
    ("実行日時", "2026-09-16 09:42:11"),
    ("結果ファイル", "probe_result_20260916_0942.txt"),
])
item1 = p.ProbeItem(1, "Outlook への接続", "操作できるか")
item1.ok("接続成功")
item1.decide("下書きを直接作れます。")
item1.ask("スクリーンショットを1枚いただけますか。")
report.add(item1)

item6 = p.ProbeItem(6, "長いURLのリンク", "壊れないか")
item6.ng("リンクが変化しました")
item6.decide("URLの持ち方を変更します。")
report.add(item6)

text = report.render()
check("総合判定が本文より前に出る",
      text.index("総合判定") < text.index("[1]"), "")
check("結果ファイル名が「次にお願いしたいこと」に出る",
      text.count("probe_result_20260916_0942.txt") >= 2, "")
check("署名の実物の提出を依頼している", "probe_signature.html" in text)
check("[お願い]が末尾に再掲される",
      text.rindex("スクリーンショット") > text.index("[6]"), "")
check("NG項目にも「作業は不要」の趣旨が伝わる", "問題ありません" in text)
check("Enterで閉じると案内している", "Enter" in text)
check("判定ラベルが各項目に付く",
      "[OK]" in text and "[NG]" in text, "")

meta_lines = [ln for ln in text.splitlines() if " : " in ln][:2]
# 全角文字は2文字幅で表示されるため、文字数ではなく表示幅で揃っているかを見る
widths = set(p.ProbeReport._width(ln[:ln.index(" : ")]) for ln in meta_lines)
check("メタ情報のコロンの位置が表示幅で揃う", len(widths) == 1, (meta_lines, widths))

# 準備不足のときは、結果ファイルの送付ではなく「準備して再実行」を案内する
report3 = p.ProbeReport([("結果ファイル", "x.txt")])
blocked = p.ProbeItem(1, "Outlook への接続", "操作できるか")
blocked.ng("pywin32 が入っていません")
blocked.rerun_needed = True
blocked.decide("pip install pywin32")
report3.add(blocked)
text3 = report3.render()
check("準備不足のときはファイル送付を依頼しない",
      "送ってください" not in text3, "")
check("準備不足のときは再実行を案内する",
      "run_probe.bat を実行" in text3, "")
check("準備不足のときも閉じ方を案内する", "Enter" in text3)

# ------------------------------------------------------------
print("\n■ 例外が出ても最後まで走り切ること（最重要）")
# ------------------------------------------------------------

class FakeCtx(object):
    pass


report2 = p.ProbeReport([("結果ファイル", "x.txt")])
executed = []


def boom(item, ctx):
    executed.append("boom")
    raise RuntimeError("COM error 0x80004005")


def fine(item, ctx):
    executed.append("fine")
    item.ok("成功")


r1 = p.run_check(report2, 1, "落ちる項目", "確認", boom, FakeCtx())
r2 = p.run_check(report2, 2, "その次の項目", "確認", fine, FakeCtx())

check("例外が呼び出し元に伝播しない", True)
check("例外を出した項目はNGになる", r1.status == p.ST_NG, r1.status)
check("例外の内容が結果に残る",
      any("COM error 0x80004005" in line for line in r1.results), r1.results)
check("例外の型名が残る",
      any("RuntimeError" in line for line in r1.results), r1.results)
check("落ちた次の項目も実行される", executed == ["boom", "fine"], executed)
check("落ちた次の項目はOKになる", r2.status == p.ST_OK, r2.status)
check("両方の項目がレポートに載る", len(report2.items) == 2, len(report2.items))

# ------------------------------------------------------------
print("\n■ 認証情報の借用（新規のEntra ID権限申請を発生させない仕組み）")
# ------------------------------------------------------------

import json  # noqa: E402
import tempfile  # noqa: E402

tid, cid, src = p._resolve_credentials({"tenant_id": "T1", "client_id": "C1"})
check("自分のconfigに両方あればそれを使う",
      (tid, cid) == ("T1", "C1"), (tid, cid))
check("取得元を明示する", "config.json" in src, src)

tmp = Path(tempfile.mkdtemp())
borrowed = tmp / "borrowed.json"
borrowed.write_text(json.dumps({"TENANT_ID": "T2", "CLIENT_ID": "C2"}), encoding="utf-8")
tid, cid, src = p._resolve_credentials({"credentials_from": str(borrowed)})
check("credentials_from から借用できる", (tid, cid) == ("T2", "C2"), (tid, cid))
check("大文字キー(TENANT_ID)にも対応する", tid == "T2", tid)

tid, cid, src = p._resolve_credentials({"credentials_from": str(tmp / "nope.json")})
check("借用先が無くても例外にならない", tid == "" and cid == "", (tid, cid))

# ------------------------------------------------------------
print("\n■ 安全性（絶対に送信しない）")
# ------------------------------------------------------------

import ast  # noqa: E402

source = Path(p.__file__).read_text(encoding="utf-8")
tree = ast.parse(source)

# コメントやdocstringの中の「.Send() は呼ばない」という説明文に反応しないよう、
# 構文木から「実際のメソッド呼び出し」だけを取り出して判定する。
called_methods = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        called_methods.add(node.func.attr)

check("Send メソッドをどこからも呼んでいない", "Send" not in called_methods,
      sorted(m for m in called_methods if "Send" in m))
check("メール送信に使われる他のメソッドも呼んでいない",
      not (called_methods & {"Send", "SendAndSave", "Submit"}), "")
check("後始末で Close を呼んでいる", "Close" in called_methods)
check("保存した下書きに Delete を呼んでいる", "Delete" in called_methods)
check("結果ファイルをUTF-8 BOM付きで書く", "utf-8-sig" in source)

# ------------------------------------------------------------
print("\n■ .emlファイルの改行（2026-09-17 実機で判明した不具合の再発防止）")
# ------------------------------------------------------------
# 越智さんの会社PCで、.emlの中身がOutlookに正しく解釈されず、ヘッダー行が
# そのまま本文の文字として表示される不具合が実際に起きた。原因は、手組みの
# "\r\n" 入り文字列をテキストモードで書き込んでいたため、Windowsのテキストモードが
# 文字列中の "\n" をもう一度 os.linesep に変換し、実際の改行が "\r\r\n" に
# 壊れていたこと。Linux(この検証環境)ではこの二重変換が起きないため、
# 当時のテストでは検出できなかった。ここでは生成されたバイト列を直接検証し、
# プラットフォームに関わらずこのクラスの不具合を検出できるようにする。

eml_bytes = p.build_eml_bytes("probe@example.com", "件名テスト", "<p>本文</p>")

check("戻り値がbytes（呼び出し側でのテキストモード書き込みを誘発しない）",
      isinstance(eml_bytes, bytes), type(eml_bytes))
check("壊れた改行(\\r\\r\\n)を含まない", b"\r\r\n" not in eml_bytes,
      eml_bytes[:200])
check("裸の改行(\\r や \\n 単独)を含まない。全て \\r\\n 区切りである",
      b"\r\n" in eml_bytes and not _has_bare_newline(eml_bytes), "")
check("Toヘッダーが読める形で含まれる", b"To: probe@example.com" in eml_bytes,
      eml_bytes[:200])
check("Subjectヘッダーが含まれる（日本語件名はMIMEエンコードされる）",
      b"Subject:" in eml_bytes, eml_bytes[:200])
check("ヘッダーと本文の間に空行がある（ヘッダー終端の目印）",
      b"\r\n\r\n" in eml_bytes, "")
check("本文のHTMLが含まれる", b"<p>" in eml_bytes and b"</p>" in eml_bytes,
      "")

# email標準ライブラリで読み返して、実際にメールとして解釈できることも確認する
import email  # noqa: E402
import email.policy  # noqa: E402

parsed = email.message_from_bytes(eml_bytes, policy=email.policy.default)
check("読み返すとSubjectが正しくデコードされる",
      parsed["Subject"] == "件名テスト", parsed["Subject"])
check("読み返すとToが正しい", parsed["To"] == "probe@example.com", parsed["To"])
check("読み返すと本文がHTMLとして取得できる",
      "<p>本文</p>" in parsed.get_body(preferencelist=("html",)).get_content(), "")

print("\n{0}\n  成功 {1} 件 / 失敗 {2} 件\n{0}".format("=" * 46, ok, ng))
sys.exit(1 if ng else 0)
