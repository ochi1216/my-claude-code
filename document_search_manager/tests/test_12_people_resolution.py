# -*- coding: utf-8 -*-
"""人物列（LookupId）の氏名解決と、値の出所の表示 — v20260903_12

Graph は人物列を数値IDでしか返さないため、そのままでは Doc Author /
Doc Owner が空欄になる。サイトのユーザー情報リストを引いて氏名に直す経路と、
どの内部列から採った値かを画面に出す仕組みを検証する。
ネットワークには一切アクセスしない。

実行: python tests/test_12_people_resolution.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import dsm, DummyAuth  # noqa: E402

import json

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
SCOPE = "https://nexperia.sharepoint.com/sites/SF_QualityDocumentsProd/Documents"

# ── P1 LookupId の取り出し ───────────────────────────────────
print("\n[P1] 人物列からの参照ID抽出")
check("単一の数値", dsm._lookup_ids_of(27) == ["27"])
check("文字列の数値", dsm._lookup_ids_of("31") == ["31"])
check("複数人の配列", dsm._lookup_ids_of([27, "31"]) == ["27", "31"])
check("氏名が入っている場合はIDとみなさない", dsm._lookup_ids_of("David Chen") == [])
check("Noneは空", dsm._lookup_ids_of(None) == [])
check("空配列は空", dsm._lookup_ids_of([]) == [])


class FakeResp:
    def __init__(self, code, payload=None):
        self.status_code = code
        self._payload = payload or {}
        self.text = ""

    def json(self):
        return self._payload


USERS = {"27": "David Chen", "31": "Rob Geljon", "44": "Vince Reyes"}


def make_get(site_code=200, user_code=200, calls=None):
    def fake_get(url, headers=None, params=None, timeout=None):
        if calls is not None:
            calls.append(url)
        if "/lists/User Information List/items/" in url:
            if user_code != 200:
                return FakeResp(user_code)
            user_id = url.rsplit("/", 1)[-1]
            return FakeResp(200, {"fields": {"Title": USERS.get(user_id, "")}})
        if "/sites/" in url and "/lists/" not in url and "/shares/" not in url:
            if site_code != 200:
                return FakeResp(site_code)
            return FakeResp(200, {"id": "site-abc"})
        return FakeResp(404)
    return fake_get


orig_get = dsm.http_req.get

# ── P2 氏名への解決 ──────────────────────────────────────────
print("\n[P2] LookupId → 氏名の解決")
calls = []
nx = dsm.NexusProvider(CFG, DummyAuth())
nx._people_cache = {}
dsm.http_req.get = make_get(calls=calls)
try:
    fields = {"qmEditorLookupId": 27, "qmOwnerLookupId": [31, 44],
              "qmDocumentNo": "NDS-00688"}
    nx._resolve_people("tok", fields)
finally:
    dsm.http_req.get = orig_get

check("単一の人物列を氏名にする", fields.get("qmEditor") == "David Chen", str(fields))
check("複数人は ; で連結する", fields.get("qmOwner") == "Rob Geljon; Vince Reyes",
      str(fields))
check("元のLookupIdは消さない（診断で見られるように）",
      fields.get("qmEditorLookupId") == 27)
check("人物列でない列は触らない", fields.get("qmDocumentNo") == "NDS-00688")
check("サイトIDは1度だけ引く",
      len([c for c in calls if "/lists/" not in c]) == 1, str(calls))

# 同じ人は2度引かない
calls2 = []
dsm.http_req.get = make_get(calls=calls2)
try:
    nx._resolve_people("tok", {"aLookupId": 27, "bLookupId": 27})
finally:
    dsm.http_req.get = orig_get
check("同じIDは1度しか引かない（キャッシュ）",
      len([c for c in calls2 if "/items/" in c]) == 0, str(calls2))

# ── P3 参照できない環境でも壊れない ──────────────────────────
print("\n[P3] ユーザー情報リストを参照できない場合")
nx_ng = dsm.NexusProvider(CFG, DummyAuth())
nx_ng._people_cache = {}
calls3 = []
dsm.http_req.get = make_get(user_code=403, calls=calls3)
try:
    f2 = {"qmEditorLookupId": 27, "qmOwnerLookupId": 31}
    nx_ng._resolve_people("tok", f2)
finally:
    dsm.http_req.get = orig_get
check("解決できないときは列を作らない（数値を出さない）",
      "qmEditor" not in f2 and "qmOwner" not in f2, str(f2))
check("理由を控えて画面に出せるようにする",
      "HTTP 403" in nx_ng._people_note, nx_ng._people_note)
check("1度失敗したら引き続けない",
      len([c for c in calls3 if "/items/" in c]) == 1, str(calls3))

nx_nosite = dsm.NexusProvider(CFG, DummyAuth())
nx_nosite._people_cache = {}
dsm.http_req.get = make_get(site_code=404)
try:
    f3 = {"qmEditorLookupId": 27}
    nx_nosite._resolve_people("tok", f3)
finally:
    dsm.http_req.get = orig_get
check("サイトIDが引けなくても落ちない", "qmEditor" not in f3, str(f3))

nx_off = dsm.NexusProvider(dict(CFG, nexus_resolve_people=False), DummyAuth())
called = []
dsm.http_req.get = lambda *a, **k: called.append(1) or FakeResp(200, {})
try:
    f4 = {"qmEditorLookupId": 27}
    nx_off._resolve_people("tok", f4)
finally:
    dsm.http_req.get = orig_get
check("設定でオフにできる", not called and "qmEditor" not in f4, str(f4))

# ── P4 検索全体を通した動作 ──────────────────────────────────
print("\n[P4] 検索を通した動作（Index列に氏名が載る）")
REAL = {
    "qmDocumentNo": "NDS-00627",
    "nxOldDocumentNo": "XPR-0558",
    "qmDocumentTitle": "Package Development Workflow",
    "qmEditorLookupId": 27,
    "qmOwnerLookupId": 31,
    "nxApplicable": "Back End Operations",
    "nxFunctionalOrg": "Back End Operations",
}


def search_stub(token, query_string, frm, size):
    return 200, {"value": [{"hitsContainers": [{
        "total": 117, "hits": [{"resource": {"webUrl": SCOPE + "/a.docx"}}],
        "moreResultsAvailable": False}]}]}, ""


def shares_get(url, headers=None, params=None, timeout=None):
    if "/shares/" in url:
        return FakeResp(200, {"listItem": {"fields": dict(REAL)}})
    return make_get()(url, headers, params, timeout)


nx_full = dsm.NexusProvider(CFG, DummyAuth())
nx_full._people_cache = {}
nx_full._mode = "search-api"
nx_full._call_search_api = search_stub
dsm.http_req.get = shares_get
try:
    out = nx_full.search("validation plan", 10)
finally:
    dsm.http_req.get = orig_get

row = out["results"][0]
check("Doc Author に氏名が入る", row.doc_author == "David Chen", row.doc_author)
check("Doc Owner に氏名が入る", row.doc_owner == "Rob Geljon", row.doc_owner)
check("Document Number は従来どおり", row.document_number == "NDS-00627")
check("Doc Author の出所を記録する",
      row.index_sources.get("doc_author") == "qmEditor",
      json.dumps(row.index_sources, ensure_ascii=False))
check("Document Number の出所も記録する",
      row.index_sources.get("document_number") == "qmDocumentNo",
      json.dumps(row.index_sources, ensure_ascii=False))

# ── P5 画面とAPI ─────────────────────────────────────────────
print("\n[P5] 画面とAPI")
mgr = dsm.SearchManager(CFG, DummyAuth())
mgr.providers[dsm.TARGET_NEXUS].search = (
    lambda kw, mx: {"results": [row], "total": 117, "note": ""})
dsm._cfg = CFG
dsm._manager = mgr
client = dsm.flask_app.test_client()

resp = client.post("/api/search", json={"keyword": "validation plan",
                                        "target": "nexus", "max_results": 10})
data = resp.get_json()
check("APIが index_sources を返す", "index_sources" in data["results"][0],
      json.dumps(data["results"][0])[:200])
check("APIが Doc Author を返す", data["results"][0]["doc_author"] == "David Chen")

html = client.get("/").get_data(as_text=True)
check("画面が出所をツールチップに出す", "index_sources" in html)
check("ツールチップの文言がある", "内部列 " in html)

# ── P6 タイトルだけを検索する（標準ON） ─────────────────────
print("\n[P6] タイトルだけを検索する")
check("複数語はタイトル内のAND条件にする",
      dsm._title_only_query("validation plan") == "title:validation title:plan",
      dsm._title_only_query("validation plan"))
check("1語ならそのまま", dsm._title_only_query("validation") == "title:validation")
check("引用符付きは完全一致を尊重する",
      dsm._title_only_query('"validation plan"') == 'title:"validation plan"',
      dsm._title_only_query('"validation plan"'))
check("空なら空", dsm._title_only_query("") == "")
check("対象の列名は設定で変えられる",
      dsm._title_only_query("abc", "qmDocumentTitle") == "qmDocumentTitle:abc")
check("既定でオンにする設定がある", CFG["title_only_default"] is True)

nx_t = dsm.NexusProvider(CFG, DummyAuth())
nx_t.title_only = True
q = nx_t._query_string("validation plan")
check("タイトル限定でもNexusのフォルダ限定は残る", 'path:"' in q, q)
check("タイトル限定のKQLになる", "title:validation title:plan" in q, q)
nx_t.title_only = False
check("オフなら従来どおり全文",
      nx_t._query_string("validation plan").startswith("validation plan"),
      nx_t._query_string("validation plan"))

sp_t = dsm.SharePointProvider(CFG, DummyAuth())
sp_t.title_only = True
check("SharePoint側にも効く",
      sp_t._query_string("validation plan") == "title:validation title:plan",
      sp_t._query_string("validation plan"))

# 実行層から指定が伝わること
sent = {}
mgr_t = dsm.SearchManager(CFG, DummyAuth())


def capture(kw, mx):
    sent["title_only"] = mgr_t.providers[dsm.TARGET_NEXUS].title_only
    return {"results": [], "total": 0, "note": ""}


mgr_t.providers[dsm.TARGET_NEXUS].search = capture
mgr_t.search("validation", dsm.TARGET_NEXUS, 10, title_only=True)
check("実行層から各系統へ指定が伝わる", sent.get("title_only") is True, str(sent))
mgr_t.search("validation", dsm.TARGET_NEXUS, 10, title_only=False)
check("オフも伝わる", sent.get("title_only") is False, str(sent))

dsm._cfg = CFG
dsm._manager = mgr_t
client_t = dsm.flask_app.test_client()
resp_t = client_t.post("/api/search", json={"keyword": "validation",
                                            "target": "nexus", "title_only": True})
check("APIが title_only を返す", resp_t.get_json().get("title_only") is True,
      json.dumps(resp_t.get_json())[:200])
resp_f = client_t.post("/api/search", json={"keyword": "validation",
                                            "target": "nexus", "title_only": False})
check("オフも返す", resp_f.get_json().get("title_only") is False)
resp_d = client_t.post("/api/search", json={"keyword": "validation", "target": "nexus"})
check("未指定なら設定の既定（オン）を使う",
      resp_d.get_json().get("title_only") is True,
      json.dumps(resp_d.get_json())[:200])

html_t = client_t.get("/").get_data(as_text=True)
check("画面にチェックボックスがある", 'id="titleOnly"' in html_t)
check("既定でオンになっている", 'id="titleOnly" checked' in html_t)
check("状態として保存する", "title_only: document.getElementById" in html_t)

# ── P7 Nexusで開くリンク ─────────────────────────────────────
print("\n[P7] Nexusで開くリンク")
check("1件だけに絞り込んだ状態で開く旨を案内する",
      "だけに絞り込んだ状態で開きます" in html_t)
check("クリップボード方式はやめた（リンクだけで絞り込めるため）",
      "navigator.clipboard" not in html_t)

print(f"\n{'=' * 46}\n  成功 {ok} 件 / 失敗 {ng} 件\n{'=' * 46}")
sys.exit(1 if ng else 0)
