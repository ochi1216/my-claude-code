# -*- coding: utf-8 -*-
"""SharePointサイト絞り込み診断（S05 Phase3-0）— v20260924_02 で追加

document_search_manager: 越智さんの要望「P010024_LorryというSharePoint Site
の中のTEST_Product_Engineeringという名前のフォルダを検索したい」を受け、
KQLの`path:`演算子による特定サイトへの絞り込みが、ユーザーが自由入力する
サイト名/URLに対しても実際に機能するかを事前確認するための診断機能を検証する。
敵対的プロダクトマネージャーレビューのB1（自由入力をKQLへそのまま埋め込む
危険性）を受けて追加したホワイトリスト検証も、この診断機能で最初に効かせる。
ネットワークには一切アクセスせず、最新バージョンの本体を読み込んで検証する。
実行: python tests/test_26_site_scope_diag.py
（まとめて実行する場合は python tests/run_tests.py）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import dsm, DummyAuth  # noqa: E402

ok, ng = 0, 0


def check(label, cond, detail=""):
    global ok, ng
    if cond:
        ok += 1
        print(f"  OK   {label}")
    else:
        ng += 1
        print(f"  NG   {label}  {detail}")


CFG = dict(dsm.DEFAULT_CFG)


# ── T1: _validate_site_scope_input（B1: ホワイトリスト検証） ──
print("\n[T1] サイト名/URL入力のホワイトリスト検証（敵対的レビューB1対応）")
check("空文字はそのまま許可（絞り込みなしとして扱う）",
      dsm._validate_site_scope_input("") == "")
check("空白のみも空文字扱い", dsm._validate_site_scope_input("   ") == "")
check("英数字・アンダースコアの短縮名を許可",
      dsm._validate_site_scope_input("P010024_Lorry") == "P010024_Lorry")
check("フルURL（スラッシュ・コロン含む）を許可",
      dsm._validate_site_scope_input(
          "https://nexperia.sharepoint.com/sites/P010024_Lorry")
      == "https://nexperia.sharepoint.com/sites/P010024_Lorry")
check("前後の空白は取り除く",
      dsm._validate_site_scope_input("  P010024_Lorry  ") == "P010024_Lorry")

for bad in ['P010024_Lorry" OR IsDocument:1 path:"', "P010024 Lorry",
            "P010024_Lorry;DROP", "サイト名", "<script>"]:
    try:
        dsm._validate_site_scope_input(bad)
        check(f"不正な文字を含む入力は例外を投げる: {bad!r}", False, "例外が発生しなかった")
    except ValueError as e:
        check(f"不正な文字を含む入力は例外を投げる: {bad!r}", True)
        check(f"  例外メッセージに使用可能文字の案内がある: {bad!r}",
              "英数字" in str(e), str(e))


# ── T2: _build_site_scope_url（短縮名⇄フルURL、M1対応） ──────
print("\n[T2] サイト名/URLから絶対URLを組み立てる（_build_site_scope_url）")
check("短縮名は sharepoint_host の /sites/ 配下に展開する",
      dsm._build_site_scope_url("P010024_Lorry", CFG)
      == "https://nexperia.sharepoint.com/sites/P010024_Lorry",
      dsm._build_site_scope_url("P010024_Lorry", CFG))
check("短縮名の前後のスラッシュは取り除く",
      dsm._build_site_scope_url("/P010024_Lorry/", CFG)
      == "https://nexperia.sharepoint.com/sites/P010024_Lorry")
check("httpsのフルURLはそのまま使う（/teams/・/personal/系にも対応）",
      dsm._build_site_scope_url(
          "https://nexperia.sharepoint.com/teams/SomeTeam", CFG)
      == "https://nexperia.sharepoint.com/teams/SomeTeam")
check("httpのフルURLもそのまま使う",
      dsm._build_site_scope_url("http://example.com/personal/someone", CFG)
      == "http://example.com/personal/someone")
check("フルURL末尾のスラッシュは落とす",
      dsm._build_site_scope_url(
          "https://nexperia.sharepoint.com/sites/P010024_Lorry/", CFG)
      == "https://nexperia.sharepoint.com/sites/P010024_Lorry")
check("空文字は空文字のまま（絞り込みなし）",
      dsm._build_site_scope_url("", CFG) == "")
check("sharepoint_hostが未設定なら短縮名を展開できず空文字",
      dsm._build_site_scope_url("P010024_Lorry", dict(CFG, sharepoint_host="")) == "")
try:
    dsm._build_site_scope_url('P010024_Lorry"', CFG)
    check("不正な文字を含む入力はValueErrorを伝播する", False, "例外が発生しなかった")
except ValueError:
    check("不正な文字を含む入力はValueErrorを伝播する", True)


# ── T3: diagnose_site_scope（クエリ組み立て・応答の解析） ─────
print("\n[T3] diagnose_site_scope: クエリ組み立てと応答の解析")


def make_page(total, hits, more=False):
    return {"value": [{"hitsContainers": [
        {"total": total, "hits": hits, "moreResultsAvailable": more}
    ]}]}


HIT_FOLDER = {"resource": {
    "webUrl": "https://nexperia.sharepoint.com/sites/P010024_Lorry/"
             "Shared%20Documents/TEST_Product_Engineering",
    # is_folderの判定はfields.isdocument→fields.contentclass→
    # URL末尾の拡張子有無、の順（_looks_like_folder参照）。ここでは
    # どちらの列も持たない実測に近い形にし、URL末尾（拡張子なし）から
    # フォルダと判定される経路を検証する。
    "fields": {"title": "TEST_Product_Engineering",
              "sitetitle": "P010024_Lorry"},
}}

sp = dsm.SharePointProvider(CFG, DummyAuth())
sp._token = lambda: "dummy-token"

captured = {}


def stub_call(token, query_string, frm, size):
    captured["query"] = query_string
    return 200, make_page(1, [HIT_FOLDER]), ""


sp._call_search_api = stub_call
out = sp.diagnose_site_scope("TEST_Product_Engineering", "P010024_Lorry")
check("成功時はok=True", out.get("ok") is True, out)
check("キーワード+サイトの両方をKQLに含める",
      "TEST_Product_Engineering" in out["query"] and 'path:"' in out["query"],
      out["query"])
check("組み立てたKQLに越智さんの実例のURLが入る",
      "https://nexperia.sharepoint.com/sites/P010024_Lorry" in out["query"],
      out["query"])
check("該当件数(total)を返す", out["total"] == 1, out["total"])
check("サンプル1件を解析して返す（フォルダと判定）",
      out["sample_count"] == 1 and out["samples"][0]["is_folder"] is True,
      out["samples"])
check("サンプルのtitleがTEST_Product_Engineering",
      out["samples"][0]["title"] == "TEST_Product_Engineering",
      out["samples"][0])

# サイトのみ（キーワード空、Q3=A: 許可する前提でサイト内一覧のクエリを確認）
out_site_only = sp.diagnose_site_scope("", "P010024_Lorry")
check("キーワード空・サイトのみでもpath:だけのクエリを組み立てる",
      out_site_only["query"].strip().startswith('path:"'), out_site_only["query"])

# キーワードのみ（サイト空）
out_kw_only = sp.diagnose_site_scope("validation", "")
check("サイト空・キーワードのみならpath:を付けない",
      "path:" not in out_kw_only["query"], out_kw_only["query"])

# 両方空
out_both_empty = sp.diagnose_site_scope("", "")
check("キーワード・サイトとも空ならエラーメッセージを返す（検索を実行しない）",
      out_both_empty.get("ok") is False
      and "空です" in out_both_empty.get("message", ""),
      out_both_empty)

# 不正なサイト名（B1）
out_bad = sp.diagnose_site_scope("validation", 'P010024_Lorry" OR 1=1')
check("不正な文字を含むサイト名はok=Falseでエラーメッセージを返す",
      out_bad.get("ok") is False and "使用できない文字" in out_bad.get("message", ""),
      out_bad)
check("不正な入力時はGraphへのリクエスト自体を送らない（安全側に倒す）",
      "query" not in out_bad, out_bad)

# HTTPエラー
sp_err = dsm.SharePointProvider(CFG, DummyAuth())
sp_err._token = lambda: "dummy-token"
sp_err._call_search_api = lambda token, q, frm, size: (401, None, "Unauthorized")
out_err = sp_err.diagnose_site_scope("validation", "P010024_Lorry")
check("HTTPエラー時はok=Falseでステータスコードを含む",
      out_err.get("ok") is False and "401" in out_err.get("message", ""),
      out_err)
check("HTTPエラー時も組み立てたKQLを返す（原因切り分けのため）",
      'path:"' in out_err.get("query", ""), out_err)


# ── T4: title_only/prefix_search を一時的に上書きし、必ず元に戻す ──
print("\n[T4] title_only/prefix_search の一時上書きと復元")
sp_flags = dsm.SharePointProvider(CFG, DummyAuth())
sp_flags._token = lambda: "dummy-token"
sp_flags.title_only = True
sp_flags.prefix_search = False


def stub_flags(token, query_string, frm, size):
    captured["flags_query"] = query_string
    return 200, make_page(0, []), ""


sp_flags._call_search_api = stub_flags
sp_flags.diagnose_site_scope("validation plan", "P010024_Lorry",
                             title_only=False, prefix_search=True)
check("診断中は指定したtitle_only/prefix_searchが使われる（本文検索になる）",
      "title:" not in captured["flags_query"], captured["flags_query"])
check("診断後、元のtitle_only/prefix_searchに復元される",
      sp_flags.title_only is True and sp_flags.prefix_search is False,
      (sp_flags.title_only, sp_flags.prefix_search))

# 例外時も必ず復元されることを確認（B1のバリデーション例外経路）
sp_flags2 = dsm.SharePointProvider(CFG, DummyAuth())
sp_flags2.title_only = True
sp_flags2.diagnose_site_scope("validation", 'bad"input')
check("バリデーション例外時もtitle_onlyは復元される（try/finally）",
      sp_flags2.title_only is True)


# ── T5: Flaskエンドポイント /api/site_scope_diag ────────────
print("\n[T5] Flaskエンドポイント /api/site_scope_diag")
mgr = dsm.SearchManager(CFG, DummyAuth())
mgr.providers[dsm.TARGET_SHAREPOINT]._token = lambda: "dummy-token"
mgr.providers[dsm.TARGET_SHAREPOINT]._call_search_api = (
    lambda token, q, frm, size: (200, make_page(2, [HIT_FOLDER]), ""))
dsm._cfg = CFG
dsm._manager = mgr

client = dsm.flask_app.test_client()
resp = client.post("/api/site_scope_diag",
                   json={"keyword": "TEST_Product_Engineering",
                        "site": "P010024_Lorry"})
check("POST /api/site_scope_diag が200", resp.status_code == 200, resp.status_code)
data = resp.get_json()
check("応答にok=Trueが入る", data.get("ok") is True, data)
check("応答に該当件数が入る", data.get("total") == 2, data)

resp_bad = client.post("/api/site_scope_diag",
                       json={"keyword": "x", "site": 'bad"input'})
check("不正なサイト名でも500にはならず200でok=Falseを返す（画面側で表示するため）",
      resp_bad.status_code == 200 and resp_bad.get_json().get("ok") is False,
      resp_bad.status_code)

html = dsm.flask_app.test_client().get("/").get_data(as_text=True)


# ── T6: 画面（HTML/JS）の構造確認 ───────────────────────────
print("\n[T6] 画面（HTML/JS）の構造確認")
check('サイト絞り込み診断ボタン（id="btnSiteScopeDiag"）がある',
      'id="btnSiteScopeDiag"' in html)
check('診断用のサイト入力欄（id="siteScopeInput"）がある',
      'id="siteScopeInput"' in html)
check('入力行（id="siteScopeDiagRow"）は既定で隠れている',
      '<div class="row" id="siteScopeDiagRow" hidden>' in html)
check("setTargetでSharePointタブ以外はsiteScopeDiagRowを隠す",
      'document.getElementById("siteScopeDiagRow").hidden = (target !== "sharepoint");'
      in html)
check("btnSiteScopeDiagはsetBusyで無効化される",
      'document.getElementById("btnSiteScopeDiag").disabled = busy;' in html)
check("クリック時に/api/site_scope_diagへPOSTする",
      'fetch("/api/site_scope_diag"' in html)
check("送信内容にtitle_only/prefix_searchの現在値を含める",
      'title_only: document.getElementById("titleOnly").checked' in html
      and 'prefix_search: document.getElementById("prefixSearch").checked' in html)


print(f"\n{'=' * 46}")
print(f"  成功 {ok} 件 / 失敗 {ng} 件")
print(f"{'=' * 46}")
sys.exit(0 if ng == 0 else 1)
