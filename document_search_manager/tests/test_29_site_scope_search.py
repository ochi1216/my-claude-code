# -*- coding: utf-8 -*-
"""サイト内検索（S05本実装）— v20260925_03 で追加

document_search_manager: 「1. SharePoint」タブでサイトを選び、そのサイトの
中だけを検索する機能を検証する。
  - サイトURLの検査と、トップURLへの揃え方（_normalize_site_scope_url）
  - KQLへの path:"..." の付け方（キーワードが空ならサイト内の一覧）
  - SearchManager が SharePointタブのときだけサイトを渡し、終わったら戻すこと
  - サイト名検索（①→②への切替、0件なら先頭の語で探し直し）
  - /api/search・/api/site_search・/api/favorite_sites・/api/state
  - 画面（チップ・候補の [hidden] 対策、キャッシュの条件、🔍ボタン）
Graph API には一切アクセスせず、スタブで検証する。
実行: python tests/test_29_site_scope_search.py
（まとめて実行する場合は python tests/run_tests.py）
"""
import json
import sys
import tempfile
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


CFG = dict(dsm.DEFAULT_CFG, mcas_host="nexperia.sharepoint.com.mcas.ms")
LORRY = "https://nexperia.sharepoint.com/sites/P010024_Lorry"
JEEP = "https://nexperia.sharepoint.com/sites/P010008-Jeeppkg-spin"

_ORIG = {"post": dsm.http_req.post, "get": dsm.http_req.get,
         "fav": dsm.FAVORITE_SITES_PATH, "fav_max": dsm.FAVORITE_SITES_MAX,
         "state": dsm.STATE_PATH, "cfg": dsm._cfg, "mgr": dsm._manager}
WORK = Path(tempfile.mkdtemp())


class FakeResp:
    def __init__(self, status, body=None, text=""):
        self.status_code, self._body, self.text = status, body, text

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


def site_hits(*sites):
    return {"value": [{"hitsContainers": [{
        "total": len(sites),
        "hits": [{"resource": {"displayName": n, "name": n, "webUrl": u}} for n, u in sites],
    }]}]}


def raises(fn, *args):
    try:
        fn(*args)
    except ValueError as e:
        return str(e)
    return None


try:
    # ── T1: サイトURLの検査とトップURLへの揃え方 ─────────────────
    print("\n[T1] _normalize_site_scope_url（検査・トップURLへ揃える）")
    n = dsm._normalize_site_scope_url
    check("サイトのトップURLはそのまま", n(LORRY, CFG) == LORRY, n(LORRY, CFG))
    check("ライブラリ・フォルダまでのURLはトップに揃える",
          n(LORRY + "/Shared_Documents/50.Test", CFG) == LORRY)
    check("サイト名より後ろの空白・%・?は捨てるので拒否しない（コピーしたURLも使える）",
          n(LORRY + "/Shared Documents/Forms/AllItems.aspx?id=%2Fsites%2Fx", CFG) == LORRY)
    check("末尾のスラッシュは取る", n(LORRY + "/", CFG) == LORRY)
    check("/teams/ のサイトも使える",
          n("https://nexperia.sharepoint.com/teams/ABC", CFG)
          == "https://nexperia.sharepoint.com/teams/ABC")
    check("ハイフン入りのサイト名（P010008-Jeeppkg-spin）も通る", n(JEEP, CFG) == JEEP)
    check(".mcas.ms 経由の表示用URLは、検索用に本来のホストへ戻す",
          n("https://nexperia.sharepoint.com.mcas.ms/sites/P010024_Lorry", CFG) == LORRY)
    check("空なら空（指定なし）", n("", CFG) == "")
    check("社内以外のホストは拒否",
          "以外" in (raises(n, "https://evil.example.com/sites/X", CFG) or ""))
    check("http:// は拒否", raises(n, "http://nexperia.sharepoint.com/sites/X", CFG) is not None)
    check("/personal/（個人のOneDrive）は対象外",
          raises(n, "https://nexperia.sharepoint.com/personal/taro", CFG) is not None)
    check("サイト名が無いURLは拒否",
          raises(n, "https://nexperia.sharepoint.com/sites", CFG) is not None)
    msg = raises(n, LORRY + '" OR path:"https://evil', CFG) or ""
    check("KQLを壊す \" は拒否し、だめな文字を表示する", "「\"」" in msg, msg)
    msg = raises(n, LORRY + "​", CFG) or ""
    check("目に見えない文字は名前（U+200B）で示す（9/25の実機で原因が分からなかった反省）",
          "U+200B" in msg, msg)
    msg = raises(dsm._validate_site_scope_input, "a%20b c") or ""
    check("サイト絞り込み診断の入力チェックも、だめな文字を示すようになった",
          "「%」" in msg and "空白" in msg, msg)
    check("表示用: URLから /sites/名前 を取り出す",
          dsm._site_path_of(LORRY + "/Shared Documents") == "/sites/P010024_Lorry")

    # ── T2: KQLの組み立て ────────────────────────────────────
    print("\n[T2] _query_string（path: の付け方）")
    sp = dsm.SharePointProvider(CFG, DummyAuth())
    sp.title_only = True
    check("サイト未指定なら従来どおり", sp._query_string("TEST_Product") == "title:TEST_Product",
          sp._query_string("TEST_Product"))
    sp.site_scope_url = LORRY
    check("サイト指定ありなら、実機で確認したとおりの形になる",
          sp._query_string("TEST_Product") == f'title:TEST_Product path:"{LORRY}"',
          sp._query_string("TEST_Product"))
    check("キーワードが空ならサイト内の一覧（path:のみ）",
          sp._query_string("") == f'path:"{LORRY}"', sp._query_string(""))
    nx = dsm.NexusProvider(CFG, DummyAuth())
    check("Nexusは対象サイトの影響を受けない（属性は常に空）",
          nx.site_scope_url == "" and LORRY not in nx._query_string("validation"))

    # ── T3: 検索本体（注記・予備モードでの扱い） ─────────────────
    print("\n[T3] SharePointProvider.search（注記・予備モード）")
    sp3 = dsm.SharePointProvider(CFG, DummyAuth())
    sp3._mode = "search-api"
    sp3._search_by_search_api = lambda token, kw, mx: {"results": [], "total": 0, "note": ""}
    sp3.site_scope_url = LORRY
    out = sp3.search("x", 10)
    check("サイト内検索のときは、どのサイトかを注記に出す",
          "サイト内検索: /sites/P010024_Lorry" in out.get("note", ""), out.get("note"))
    sp3._mode = "site-drive"
    try:
        sp3.search("x", 10)
        check("予備のサイト単位検索モードでは、黙って全社検索にせず例外で伝える", False)
    except RuntimeError as e:
        check("予備のサイト単位検索モードでは、黙って全社検索にせず例外で伝える",
              "サイト内検索" in str(e), str(e))

    # ── T4: SearchManager（SharePointタブのときだけ渡し、必ず戻す） ──
    print("\n[T4] SearchManager.search（対象サイトの受け渡し）")
    mgr = dsm.SearchManager(CFG, DummyAuth())
    seen = {}

    def stub(key):
        def _s(keyword, max_results):
            seen[key] = mgr.providers[dsm.TARGET_SHAREPOINT].site_scope_url
            return {"results": [], "total": 0, "note": ""}
        return _s

    for k in (dsm.TARGET_SHAREPOINT, dsm.TARGET_NEXUS, dsm.TARGET_ENOVIA):
        mgr.providers[k].search = stub(k)
    mgr.search("x", dsm.TARGET_SHAREPOINT, 10, site_scope=LORRY)
    check("SharePointタブでは検索中だけサイトが渡る", seen.get(dsm.TARGET_SHAREPOINT) == LORRY, seen)
    check("検索が終わったら必ず空に戻す（疎通診断や別タブに漏らさない）",
          mgr.providers[dsm.TARGET_SHAREPOINT].site_scope_url == "")
    seen.clear()
    mgr.search("x", dsm.TARGET_ALL, 10, site_scope=LORRY)
    check("Allタブではサイトを渡さない（今までどおり全社検索）",
          seen.get(dsm.TARGET_SHAREPOINT) == "", seen)

    def boom(keyword, max_results):
        raise RuntimeError("fail")
    mgr.providers[dsm.TARGET_SHAREPOINT].search = boom
    mgr.search("x", dsm.TARGET_SHAREPOINT, 10, site_scope=LORRY)
    check("検索が失敗しても空に戻す",
          mgr.providers[dsm.TARGET_SHAREPOINT].site_scope_url == "")

    # ── T5: サイト名検索（①→②、0件なら先頭の語で探し直し） ─────────
    print("\n[T5] search_sites（サイト名検索）")
    posted, got = [], []

    def post_jeep(url, **kw):
        term = kw["json"]["requests"][0]["query"]["queryString"]
        posted.append(term)
        if term == "P010008":
            return FakeResp(200, site_hits(("P010008_Jeep", "https://nexperia.sharepoint.com/sites/P010008_Jeep"),
                                           ("P010008 - Jeep pkg-spin", JEEP)))
        return FakeResp(200, site_hits())
    dsm.http_req.post = post_jeep
    dsm.http_req.get = lambda url, **kw: got.append(url) or FakeResp(200, {"value": []})
    sp5 = dsm.SharePointProvider(CFG, DummyAuth())
    r = sp5.search_sites("P010008 - Jeep pkg-spin")
    check("表示名まるごとで0件なら、先頭の語で探し直す（9/25の実機の事例）",
          posted == ["P010008 - Jeep pkg-spin", "P010008"], posted)
    check("探し直したことを返す（画面のログで知らせるため）",
          r.get("retried_with") == "P010008", r)
    check("探し直しで目的のサイトが候補に出る",
          any(c["url"] == JEEP for c in r.get("candidates") or []), r.get("candidates"))
    check("①が使えている間は②を呼ばない", got == [], got)

    posted.clear()
    dsm.http_req.post = lambda url, **kw: posted.append(1) or FakeResp(200, site_hits())
    r = sp5.search_sites("Lorry")
    check("1語で0件なら探し直さない（無駄な呼び出しをしない）",
          len(posted) == 1 and r.get("ok") and r.get("candidates") == [] and not r.get("retried_with"), r)

    got.clear()
    dsm.http_req.post = lambda url, **kw: FakeResp(403, None, "Access denied")
    dsm.http_req.get = lambda url, **kw: got.append(url) or FakeResp(
        200, {"value": [{"displayName": "P010024_Lorry", "webUrl": LORRY}]})
    r = sp5.search_sites("Lorry")
    check("①が拒否されたら②に自動で切り替える",
          r.get("ok") and got and r["candidates"][0]["url"] == LORRY and "②" in r.get("method", ""), r)

    dsm.http_req.get = lambda url, **kw: FakeResp(500, None, "error")
    r = sp5.search_sites("Lorry")
    check("両方だめなら ok=False と理由（例外を投げない）",
          r.get("ok") is False and "HTTP 500" in r.get("message", ""), r)

    dsm.http_req.post = lambda url, **kw: FakeResp(200, site_hits(("URLなし", ""), ("P010024_Lorry", LORRY)))
    r = sp5.search_sites("Lorry")
    check("URLの無い候補は出さない（選んでも検索できないため）",
          [c["url"] for c in r["candidates"]] == [LORRY], r["candidates"])
    check("空の検索語は ok=False", sp5.search_sites('  "" ').get("ok") is False)

    # ── T6: /api/search ─────────────────────────────────────
    print("\n[T6] /api/search（対象サイトの受け取り）")
    dsm._cfg = CFG
    mgr6 = dsm.SearchManager(CFG, DummyAuth())
    calls = []

    def sp_search(keyword, max_results):
        calls.append((keyword, mgr6.providers[dsm.TARGET_SHAREPOINT].site_scope_url))
        return {"results": [], "total": 0, "note": "サイト内検索: /sites/P010024_Lorry"}
    mgr6.providers[dsm.TARGET_SHAREPOINT].search = sp_search
    for k in (dsm.TARGET_NEXUS, dsm.TARGET_ENOVIA):
        mgr6.providers[k].search = lambda kw, mx: {"results": [], "total": 0, "note": ""}
    dsm._manager = mgr6
    client = dsm.flask_app.test_client()

    resp = client.post("/api/search", json={"keyword": "", "target": "sharepoint"})
    check("キーワードもサイトも空なら 400", resp.status_code == 400)
    resp = client.post("/api/search", json={"keyword": "", "target": "sharepoint",
                                            "site_scope": LORRY})
    check("サイトを選んでいれば、キーワードが空でも検索する（サイト内の一覧）",
          resp.status_code == 200 and calls[-1] == ("", LORRY), (resp.status_code, calls))
    check("応答に、検査済みのトップURLを返す", resp.get_json().get("site_scope") == LORRY)
    resp = client.post("/api/search", json={"keyword": "x", "target": "sharepoint",
                                            "site_scope": LORRY + "/Forms"})
    check("深いURLが届いても、トップURLに揃えて使う", calls[-1] == ("x", LORRY), calls[-1])
    calls.clear()
    resp = client.post("/api/search", json={"keyword": "x", "target": "all", "site_scope": LORRY})
    check("Allタブではサイトを使わない", resp.status_code == 200 and calls[-1] == ("x", ""), calls)
    resp = client.post("/api/search", json={"keyword": "", "target": "all", "site_scope": LORRY})
    check("Allタブでキーワードが空なら、サイトがあっても 400", resp.status_code == 400)
    resp = client.post("/api/search", json={"keyword": "x", "target": "sharepoint",
                                            "site_scope": LORRY + '" OR x'})
    body = resp.get_json() or {}
    check("不正なサイトは 400 で、だめな文字を示す（Graphへは送らない）",
          resp.status_code == 400 and "「\"」" in body.get("error", ""), body)
    check("Excel等の出力名は、キーワードが空ならサイト名を使う",
          (client.post("/api/search", json={"keyword": "", "target": "sharepoint",
                                            "site_scope": LORRY}).status_code == 200
           and dsm._last_keyword == "P010024_Lorry"), dsm._last_keyword)

    # ── T7: /api/site_search ─────────────────────────────────
    print("\n[T7] /api/site_search")
    dsm.http_req.post = lambda url, **kw: FakeResp(200, site_hits(("P010024_Lorry", LORRY)))
    mgr6.providers[dsm.TARGET_SHAREPOINT] = dsm.SharePointProvider(CFG, DummyAuth())
    body = client.post("/api/site_search", json={"term": "Lorry"}).get_json()
    check("候補（名前とURL）を返す",
          body.get("ok") and body["candidates"][0] == {"name": "P010024_Lorry", "url": LORRY,
                                                       "description": ""}, body)

    # ── T8: /api/favorite_sites ──────────────────────────────
    print("\n[T8] /api/favorite_sites（よく使うサイト）")
    dsm.FAVORITE_SITES_PATH = WORK / "favorite_sites.json"
    check("未登録なら空", client.get("/api/favorite_sites").get_json() == {"sites": []})
    body = client.post("/api/favorite_sites", json={"action": "add", "name": " P010024_Lorry ",
                                                    "url": LORRY + "/Shared Documents"}).get_json()
    check("登録すると、トップURLに揃えて保存する",
          body.get("sites") == [{"name": "P010024_Lorry", "url": LORRY}], body)
    saved = json.loads(dsm.FAVORITE_SITES_PATH.read_text(encoding="utf-8"))
    check("ファイルにも保存されている", saved.get("sites") == body.get("sites"), saved)
    body = client.post("/api/favorite_sites", json={"action": "add", "name": "Lorry",
                                                    "url": LORRY}).get_json()
    check("同じサイトは二重に登録しない", len(body.get("sites")) == 1, body)
    body = client.post("/api/favorite_sites", json={"action": "add", "name": "",
                                                    "url": JEEP}).get_json()
    check("名前が空なら /sites/名前 で登録", body["sites"][-1]["name"] == "/sites/P010008-Jeeppkg-spin",
          body)
    body = client.post("/api/favorite_sites", json={"action": "remove", "url": LORRY}).get_json()
    check("解除できる", [s["url"] for s in body["sites"]] == [JEEP], body)
    resp = client.post("/api/favorite_sites", json={"action": "add", "url": "https://evil.example.com/sites/x"})
    check("社内以外のURLは登録できない（400）", resp.status_code == 400)
    resp = client.post("/api/favorite_sites", json={"action": "rename", "url": LORRY})
    check("add/remove 以外は 400", resp.status_code == 400)
    dsm.FAVORITE_SITES_MAX = 1
    resp = client.post("/api/favorite_sites", json={"action": "add", "url": LORRY})
    check("上限を超える登録は 400 で理由を返す",
          resp.status_code == 400 and "まで" in resp.get_json().get("error", ""), resp.get_json())
    dsm.FAVORITE_SITES_MAX = _ORIG["fav_max"]
    dsm.FAVORITE_SITES_PATH.write_text("{壊れたJSON", encoding="utf-8")
    check("ファイルが壊れていても落ちず、空として扱う",
          client.get("/api/favorite_sites").get_json() == {"sites": []})

    # ── T9: /api/state（サイトの指定は引き継がない） ─────────────
    print("\n[T9] /api/state（対象サイトは名前だけ残し、引き継がない）")
    dsm.STATE_PATH = WORK / "session_state.json"
    client.post("/api/state", json={"keyword": "x", "target": "sharepoint",
                                    "site_scope_name": "P010024_Lorry", "site_scope": LORRY})
    st = json.loads(dsm.STATE_PATH.read_text(encoding="utf-8"))
    check("名前は残す（次回起動時に「前回はサイト内検索だった」と知らせるため）",
          st.get("site_scope_name") == "P010024_Lorry", st)
    check("サイトのURL自体は保存しない（Q1=A案：次回起動時に引き継がない）",
          "site_scope" not in st and LORRY not in json.dumps(st), st)

    # ── T10: 画面 ───────────────────────────────────────────
    print("\n[T10] 画面（HTML/JS）")
    html = dsm.INDEX_HTML
    check("「対象サイト」の枠は既定で隠れている（SharePointタブでだけ出す）",
          '<div id="siteScopeBox" hidden>' in html)
    check("チップは display を指定するため [hidden] を対で書いている（DESIGN_NOTES 5-8）",
          ".sitechip { display: inline-flex;" in html and ".sitechip[hidden] { display: none; }" in html)
    check("候補の一覧も [hidden] を対で書いている",
          ".sitecands { display: flex;" in html and ".sitecands[hidden] { display: none; }" in html)
    check("キャッシュの条件に対象サイトを含める（論点B2）",
          "function cacheKey(keyword, target, maxResults, titleOnly, prefixSearch, typeScope, siteScope)"
          in html and html.count("p.typeScope, p.siteScope") == 2)
    check("サイトを選んでいれば、キーワードが空でも検索できる",
          "if (!p.keyword && !p.siteScope)" in html)
    check("対象サイトは SharePointタブのときだけ送る",
          'siteScope: (currentTarget() === "sharepoint" && selectedSite) ? selectedSite.url : ""' in html)
    check("チップには名前と一緒にURL上の場所を出す（同じ番号のサイトの取り違え防止）",
          'getElementById("siteChipPath").textContent = "（" + sitePathOf(selectedSite.url) + "）"' in html)
    check("検索結果のサイト列の🔍は SharePointの行だけに付ける",
          'if (r.source === "SharePoint") {' in html and 'go.className = "mini sitego"' in html)
    check("起動時によく使うサイトを読み込む", "loadFavoriteSites();" in html)
    check("前回サイト内検索だった場合は、引き継がない旨をログで知らせる",
          "サイトの指定は引き継がないため、全社検索で表示します" in html)

finally:
    dsm.http_req.post, dsm.http_req.get = _ORIG["post"], _ORIG["get"]
    dsm.FAVORITE_SITES_PATH, dsm.FAVORITE_SITES_MAX = _ORIG["fav"], _ORIG["fav_max"]
    dsm.STATE_PATH, dsm._cfg, dsm._manager = _ORIG["state"], _ORIG["cfg"], _ORIG["mgr"]


print(f"\n{'=' * 46}")
print(f"  成功 {ok} 件 / 失敗 {ng} 件")
print(f"{'=' * 46}")
sys.exit(1 if ng else 0)
