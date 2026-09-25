# -*- coding: utf-8 -*-
"""サイト名検索診断（S05 Phase3-0b）— v20260925_02 で追加

document_search_manager: SharePointタブの「サイトを探す→選んだサイト内で
検索」の本実装に先立ち、サイト名の一部からサイトを探せるかを2方式
（① /search/query の entityTypes=site ② /sites?search=）で試す診断機能を
検証する。検索語の整形（ダブルクォート・目に見えない文字の除去）も確認する。
Graph API には一切アクセスせず、http_req.post / get をスタブ化して検証する。
実行: python tests/test_28_site_search_diag.py
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

_ORIG_POST = dsm.http_req.post
_ORIG_GET = dsm.http_req.get


class FakeResp:
    def __init__(self, status, body=None, text=""):
        self.status_code = status
        self._body = body
        self.text = text

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


# 2026-09-25の実機結果に合わせた名前（同名フォルダが別サイトにある実例も表現する）
SITE_LORRY = {
    "@odata.type": "#microsoft.graph.site",
    "id": "nexperia.sharepoint.com,aaa,bbb",
    "name": "P010024_Lorry",
    "displayName": "P010024_Lorry",
    "webUrl": "https://nexperia.sharepoint.com/sites/P010024_Lorry",
    "description": "Lorry project site",
}
SITE_OTHER = {
    "id": "nexperia.sharepoint.com,ccc,ddd",
    "name": "PO_Matrix",
    "displayName": "",  # 表示名が無いサイト → name を使う
    "webUrl": "https://nexperia.sharepoint.com/sites/PO_Matrix",
}

SEARCH_BODY = {"value": [{"hitsContainers": [{
    "total": 2,
    "hits": [{"resource": SITE_LORRY}, {"resource": SITE_OTHER}],
}]}]}


try:
    # ── T1: 検索語の整形 ─────────────────────────────────────
    print("\n[T1] _sanitize_site_search_term（検索語の整形）")
    s = dsm._sanitize_site_search_term
    check("普通の語はそのまま", s("Lorry") == "Lorry")
    check("前後の空白と全角空白を除き、連続空白を1つに",
          s("  Lorry　 project ") == "Lorry project", repr(s("  Lorry　 project ")))
    check("日本語のサイト名も通す（英数字に限定しない）", s("日本デザイン") == "日本デザイン")
    check("ダブルクォートを除く（KQLの句を壊さない）", s('Lo"rry') == "Lorry")
    check("全角の“”も除く", s("“Lorry”") == "Lorry")
    check("ゼロ幅スペースを除く（2026-09-25 実機の入力エラーの原因）",
          s("P010024_Lorry​") == "P010024_Lorry")
    check("制御文字を除く", s("Lor\x00ry\t") == "Lorry")
    check("長すぎる入力は切り詰める",
          len(s("a" * 500)) == dsm.SITE_SEARCH_TERM_MAX)
    check("空・空白だけなら空文字", s("   ") == "" and s(None) == "")

    # ── T2: 2方式とも成功 ────────────────────────────────────
    print("\n[T2] diagnose_site_search（2方式とも成功）")
    calls = {"post": [], "get": []}

    def fake_post(url, **kw):
        calls["post"].append((url, kw))
        return FakeResp(200, SEARCH_BODY)

    def fake_get(url, **kw):
        calls["get"].append((url, kw))
        return FakeResp(200, {"value": [SITE_LORRY]})

    dsm.http_req.post, dsm.http_req.get = fake_post, fake_get
    sp = dsm.SharePointProvider(CFG, DummyAuth())
    out = sp.diagnose_site_search('  "Lorry"  ')
    check("ok=True", out.get("ok") is True, out)
    check("整形後の検索語を返す", out.get("term") == "Lorry", out.get("term"))
    methods = out.get("methods") or []
    check("方式は2つ並ぶ", len(methods) == 2, len(methods))

    m1 = methods[0]
    body = calls["post"][0][1].get("json", {}) if calls["post"] else {}
    req = (body.get("requests") or [{}])[0]
    check("①は /search/query を呼ぶ", calls["post"] and calls["post"][0][0].endswith("/search/query"))
    check("①は entityTypes=site で要求する（listItemではない）",
          req.get("entityTypes") == ["site"], req.get("entityTypes"))
    check("①の検索語は整形済み（クォートを含まない）",
          req.get("query", {}).get("queryString") == "Lorry", req.get("query"))
    check("①に fields は付けない（siteでは不要・400の原因になり得る）", "fields" not in req)
    check("①の件数(total)をそのまま返す", m1.get("total") == 2, m1.get("total"))
    check("①の候補は名前とURLの組", m1.get("candidates", [{}])[0] == {
        "name": "P010024_Lorry",
        "url": "https://nexperia.sharepoint.com/sites/P010024_Lorry",
        "description": "Lorry project site"}, m1.get("candidates"))
    check("表示名が空のサイトは name を使う",
          m1.get("candidates", [{}, {}])[1].get("name") == "PO_Matrix",
          m1.get("candidates"))
    check("返ってきた項目名を並べる（何が取れるかを実機で見るため）",
          "webUrl" in (m1.get("fields") or []), m1.get("fields"))

    m2 = methods[1]
    check("②は /sites を GET する", calls["get"] and calls["get"][0][0].endswith("/sites"))
    check("②は search パラメータに検索語を渡す",
          calls["get"] and calls["get"][0][1].get("params") == {"search": "Lorry"},
          calls["get"][0][1].get("params") if calls["get"] else None)
    check("②の候補も取れる",
          m2.get("ok") is True and m2.get("candidates", [{}])[0].get("name") == "P010024_Lorry",
          m2)
    check("トークンを Authorization ヘッダーに付ける",
          calls["get"][0][1].get("headers", {}).get("Authorization") == "Bearer dummy-token")

    # ── T3: 片方だけ失敗しても、もう片方の結果は出す ─────────────
    print("\n[T3] 片方の方式だけが拒否される場合")
    dsm.http_req.post = lambda url, **kw: FakeResp(403, None, "Access denied")
    dsm.http_req.get = fake_get
    out3 = sp.diagnose_site_search("Lorry")
    m1, m2 = out3["methods"]
    check("①が403でも全体は ok=True（方式ごとに結果を並べる）", out3.get("ok") is True)
    check("①は ok=False・HTTPステータスと本文を残す",
          m1.get("ok") is False and m1.get("status") == 403 and "denied" in m1.get("message", ""),
          m1)
    check("②の結果は影響を受けない", m2.get("ok") is True, m2)

    def raise_post(url, **kw):
        raise ConnectionError("proxy down")
    dsm.http_req.post = raise_post
    out4 = sp.diagnose_site_search("Lorry")
    check("通信例外でも落ちず、status=0 と理由を残す",
          out4["methods"][0].get("ok") is False and out4["methods"][0].get("status") == 0
          and "proxy" in out4["methods"][0].get("message", ""), out4["methods"][0])

    dsm.http_req.post = lambda url, **kw: FakeResp(200, None)  # JSONでない応答
    out5 = sp.diagnose_site_search("Lorry")
    check("200でもJSONでなければ ok=False（落ちない）",
          out5["methods"][0].get("ok") is False, out5["methods"][0])

    dsm.http_req.post = lambda url, **kw: FakeResp(200, {"value": [{"hitsContainers": [
        {"total": 0, "hits": []}]}]})
    dsm.http_req.get = lambda url, **kw: FakeResp(200, {"value": []})
    out6 = sp.diagnose_site_search("NoSuchSite")
    check("0件でも ok=True・候補は空・項目名も空",
          out6["methods"][0].get("ok") is True and out6["methods"][0].get("candidates") == []
          and out6["methods"][0].get("fields") == [], out6["methods"][0])

    # ── T4: 入力・認証の異常 ─────────────────────────────────
    print("\n[T4] 入力・認証の異常")
    posted = []
    dsm.http_req.post = lambda url, **kw: posted.append(url) or FakeResp(200, SEARCH_BODY)
    out7 = sp.diagnose_site_search('  ""  ')
    check("整形後に空なら ok=False で、Graphを呼ばない",
          out7.get("ok") is False and posted == [], (out7, posted))

    class FailAuth:
        def get_token(self, scopes):
            raise RuntimeError("サインインが必要です")
    sp_fail = dsm.SharePointProvider(CFG, FailAuth())
    out8 = sp_fail.diagnose_site_search("Lorry")
    check("認証に失敗したら ok=False と理由（例外を投げない）",
          out8.get("ok") is False and "サインイン" in out8.get("message", ""), out8)

    # ── T5: 画面 ─────────────────────────────────────────────
    print("\n[T5] 画面（HTML）")
    html = dsm.INDEX_HTML if hasattr(dsm, "INDEX_HTML") else ""
    if not html:
        client = dsm.flask_app.test_client()
        html = client.get("/").get_data(as_text=True)
    check("「サイト名検索診断」ボタンがある", 'id="btnSiteSearchDiag"' in html)
    row_start = html.find('id="siteScopeDiagRow"')
    btn_pos = html.find('id="btnSiteSearchDiag"')
    row_end = html.find("</div>", row_start)
    check("ボタンはSharePointタブ専用の行の中にある（はみ出しているボタン列には足さない）",
          row_start != -1 and row_start < btn_pos < row_end, (row_start, btn_pos, row_end))
    check("処理中はボタンを押せないようにする（setBusyの対象）",
          'getElementById("btnSiteSearchDiag").disabled = busy' in html)
    check("/api/site_search_diag を呼ぶ", "/api/site_search_diag" in html)

finally:
    dsm.http_req.post = _ORIG_POST
    dsm.http_req.get = _ORIG_GET


print(f"\n{'=' * 46}")
print(f"  成功 {ok} 件 / 失敗 {ng} 件")
print(f"{'=' * 46}")
sys.exit(1 if ng else 0)
