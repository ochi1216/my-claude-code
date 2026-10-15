# -*- coding: utf-8 -*-
"""人物列の氏名解決が並行実行で取りこぼさないこと — v20260903_14

【この検証が生まれた経緯】
v13までは、検索結果を6並列で処理する際、同じ人物を同時に引いた2本目以降の
スレッドが「まだ空の途中結果」を読んでしまい、氏名が取れているのに空欄に
なる行が混ざっていた（実機で「Doc Author が入る行と入らない行がある」と
報告された不具合）。並行実行で再現させ、二度と戻らないようにする。

ネットワークには一切アクセスしない。
実行: python tests/test_13_people_concurrency.py
"""
import sys
import threading
import time
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
USERS = {"27": "Maik Jorn Teschner", "31": "Ansgar Thorns"}


class FakeResp:
    def __init__(self, code, payload=None):
        self.status_code = code
        self._payload = payload or {}
        self.text = ""

    def json(self):
        return self._payload


orig_get = dsm.http_req.get

# ── C1 同じ人物を同時に引いても取りこぼさない ────────────────
print("\n[C1] 同じ人物を複数スレッドが同時に引く")


def slow_get(url, headers=None, params=None, timeout=None):
    if "/lists/User Information List/items/" in url:
        time.sleep(0.15)          # 引き当てに時間がかかる状況を作る
        user_id = url.rsplit("/", 1)[-1]
        return FakeResp(200, {"fields": {"Title": USERS.get(user_id, "")}})
    if "/sites/" in url:
        return FakeResp(200, {"id": "site-abc"})
    return FakeResp(404)


nx = dsm.NexusProvider(CFG, DummyAuth())
nx._people_cache = {}
nx._people_lock = threading.Lock()
nx._people_disabled = False
nx._people_note = ""

names = []
dsm.http_req.get = slow_get
try:
    threads = []
    for _ in range(6):
        def work():
            names.append(nx._user_name("tok", "27"))
        t = threading.Thread(target=work)
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
finally:
    dsm.http_req.get = orig_get

check("6スレッドすべてが氏名を取得できる",
      names == ["Maik Jorn Teschner"] * 6, str(names))
check("空文字を返したスレッドが無い", "" not in names, str(names))

# ── C2 検索全体（並列処理）で全行が埋まる ────────────────────
print("\n[C2] 検索を通して、全行の Doc Author / Doc Owner が埋まる")
DOCS = 12


def search_stub(token, query_string, frm, size):
    hits = [{"resource": {"webUrl": f"{SCOPE}/doc{i}.docx"}} for i in range(DOCS)]
    return 200, {"value": [{"hitsContainers": [{
        "total": DOCS, "hits": hits, "moreResultsAvailable": False}]}]}, ""


def shares_get(url, headers=None, params=None, timeout=None):
    if "/shares/" in url:
        # 全文書が同じ担当者。並列で同時に同じIDを引く状況になる。
        return FakeResp(200, {"listItem": {"fields": {
            "qmDocumentNo": "NDS-00072",
            "qmDocumentTitle": "FMEA",
            "qmEditorLookupId": 27,
            "qmOwnerLookupId": 31,
        }}})
    return slow_get(url, headers, params, timeout)


nx2 = dsm.NexusProvider(dict(CFG, nexus_enrich_workers=6), DummyAuth())
nx2._people_cache = {}
nx2._people_lock = threading.Lock()
nx2._people_disabled = False
nx2._people_note = ""
nx2._mode = "search-api"
nx2._call_search_api = search_stub

dsm.http_req.get = shares_get
try:
    out = nx2.search("FMEA", DOCS)
finally:
    dsm.http_req.get = orig_get

rows = out["results"]
check(f"{DOCS}件すべて返る", len(rows) == DOCS, str(len(rows)))
blank_author = [i for i, r in enumerate(rows) if not r.doc_author]
blank_owner = [i for i, r in enumerate(rows) if not r.doc_owner]
check("Doc Author が空欄の行が1つも無い", not blank_author, str(blank_author))
check("Doc Owner が空欄の行が1つも無い", not blank_owner, str(blank_owner))
check("氏名が正しい", rows[0].doc_author == "Maik Jorn Teschner"
      and rows[0].doc_owner == "Ansgar Thorns",
      f"{rows[0].doc_author} / {rows[0].doc_owner}")
check("出所を記録している", rows[0].index_sources.get("doc_author") == "qmEditor",
      json.dumps(rows[0].index_sources, ensure_ascii=False))

# ── C3 200なのに氏名が空だった場合は理由を残す ───────────────
print("\n[C3] 氏名が取得できなかった場合の扱い")


def empty_name_get(url, headers=None, params=None, timeout=None):
    if "/lists/User Information List/items/" in url:
        return FakeResp(200, {"fields": {"Title": ""}})
    if "/sites/" in url:
        return FakeResp(200, {"id": "site-abc"})
    return FakeResp(404)


nx3 = dsm.NexusProvider(CFG, DummyAuth())
nx3._people_cache = {}
nx3._people_lock = threading.Lock()
nx3._people_disabled = False
nx3._people_note = ""
dsm.http_req.get = empty_name_get
try:
    got = nx3._user_name("tok", "99")
finally:
    dsm.http_req.get = orig_get
check("氏名が空なら空文字を返す", got == "")
check("黙って空欄にせず理由を残す", "氏名が取得できませんでした" in nx3._people_note,
      nx3._people_note)

# ── C4 列診断 ────────────────────────────────────────────────
print("\n[C4] Nexus列診断（1件分の全列と対応づけ）")
nx4 = dsm.NexusProvider(CFG, DummyAuth())
nx4._people_cache = {}
nx4._people_lock = threading.Lock()
nx4._people_disabled = False
nx4._people_note = ""
nx4._mode = "search-api"
nx4._call_search_api = search_stub
dsm.http_req.get = shares_get
try:
    info = nx4.diagnose_fields("FMEA")
finally:
    dsm.http_req.get = orig_get

check("対象が見つかる", info.get("found") is True, json.dumps(info)[:200])
check("文書番号を返す", info.get("document_number") == "NDS-00072")
names_in = [c["name"] for c in info.get("columns", [])]
check("内部列の一覧を返す", "qmEditorLookupId" in names_in and "qmEditor" in names_in,
      str(names_in))
check("解決後の氏名も一覧に出る",
      any(c["name"] == "qmEditor" and c["value"] == "Maik Jorn Teschner"
          for c in info["columns"]), json.dumps(info["columns"], ensure_ascii=False))
check("対応づけを返す", info["mapping"].get("doc_owner") == "qmOwner",
      json.dumps(info["mapping"], ensure_ascii=False))
check("キーワードが空なら何もしない", nx4.diagnose_fields("") == {})

dsm._cfg = CFG
mgr = dsm.SearchManager(CFG, DummyAuth())
mgr.providers[dsm.TARGET_NEXUS] = nx4
dsm._manager = mgr
client = dsm.flask_app.test_client()
dsm.http_req.get = shares_get
try:
    resp = client.post("/api/nexus_field_diag", json={"keyword": "FMEA"})
finally:
    dsm.http_req.get = orig_get
check("列診断APIが200", resp.status_code == 200, str(resp.status_code))
check("列診断APIが対応づけを返す",
      resp.get_json()["mapping"].get("document_number") == "qmDocumentNo",
      json.dumps(resp.get_json())[:200])
check("列診断APIは空キーワードを400",
      client.post("/api/nexus_field_diag", json={"keyword": ""}).status_code == 400)

html = client.get("/").get_data(as_text=True)
check("画面に列診断ボタンがある", 'id="btnNexusFields"' in html)

# ── C5 実機の列データでの対応づけ（NDS-00072 / FMEA） ────────
# 越智さんの実機の「Nexus列診断」で得られた本物の列と値。
# Nexus画面と突き合わせて Doc Author = Maik Jörn Teschner /
# Doc Owner = Ansgar Thorns であることを確認済み。対応づけを固定する。
print("\n[C5] 実機の列データでの対応づけ")
REAL_FMEA = {
    "Author": "viktor dierenfeld",
    "AuthorLookupId": 17,
    "AppEditorLookupId": 3,
    "EditorLookupId": 1073741822,
    "Title": "FMEA",
    "FileLeafRef": "FMEA.docx",
    "nxApplicable": "Quality; BG ICS; BG MOS Discretes; BG WIM; BG Bipolar Discretes",
    "nxFunctionalOrg": "BG WIM",
    "nxOldDocumentNo": "XPR-0151",
    "qmConfirmer": "Ansgar Thorns",
    "qmConfirmerLookupId": 132,
    "qmDocumentNo": "NDS-00072",
    "qmDocumentTitle": "FMEA",
    "qmDocumentType": "Process Description",
    "qmEditor": "Maik Jörn Teschner",
    "qmEditorLookupId": 325,
    "qmProcess1": "Product Creation",
    "qmReviewer": "QM Doc Control",
    "qmStatusEn": "Valid",
    "qmValidUntil": "2026-07-27T12:00:00Z",
}
picked, sources = dsm._pick_nexus_fields(REAL_FMEA, CFG)
check("Doc Author は qmEditor", picked.get("doc_author") == "Maik Jörn Teschner",
      picked.get("doc_author"))
check("Doc Owner は qmConfirmer", picked.get("doc_owner") == "Ansgar Thorns",
      picked.get("doc_owner"))
check("Doc Author に作成者(Author)を使わない",
      sources.get("doc_author") == "qmEditor", str(sources))
check("Doc Owner に qmReviewer を使わない",
      sources.get("doc_owner") == "qmConfirmer", str(sources))
check("Document Number は qmDocumentNo", picked.get("document_number") == "NDS-00072")
check("OldSystemIdentifier は nxOldDocumentNo",
      picked.get("old_system_id") == "XPR-0151")
check("Document Title は qmDocumentTitle（Title より優先）",
      sources.get("title") == "qmDocumentTitle", str(sources))
check("Applicable To は nxApplicable",
      picked.get("applicable_to", "").startswith("Quality; BG ICS"),
      picked.get("applicable_to"))
check("Department は nxFunctionalOrg", picked.get("department") == "BG WIM")

# ── C6 氏名が既に入っている列は引き当てに行かない ────────────
print("\n[C6] 氏名が取れている列は引き当てを省く")
nx5 = dsm.NexusProvider(CFG, DummyAuth())
nx5._people_cache = {}
nx5._people_lock = threading.Lock()
nx5._people_disabled = False
nx5._people_note = ""

visited = []


def counting_get(url, headers=None, params=None, timeout=None):
    visited.append(url)
    return slow_get(url, headers, params, timeout)


dsm.http_req.get = counting_get
try:
    f = dict(REAL_FMEA)
    nx5._resolve_people("tok", f)
finally:
    dsm.http_req.get = orig_get

user_calls = [u for u in visited if "/items/" in u]
check("qmEditor / qmConfirmer は引き当てに行かない（氏名が既にある）",
      all("/items/325" not in u and "/items/132" not in u for u in user_calls),
      str(user_calls))
check("氏名が残る", f["qmEditor"] == "Maik Jörn Teschner"
      and f["qmConfirmer"] == "Ansgar Thorns")
check("氏名が既にある列ぶんの通信が減る",
      len(user_calls) < len([k for k in REAL_FMEA if str(k).endswith("LookupId")]),
      f"{len(user_calls)} 回")

# 氏名が無い列は従来どおり引き当てる
nx6 = dsm.NexusProvider(CFG, DummyAuth())
nx6._people_cache = {}
nx6._people_lock = threading.Lock()
nx6._people_disabled = False
nx6._people_note = ""
dsm.http_req.get = slow_get
try:
    f2 = {"qmEditorLookupId": 27}
    nx6._resolve_people("tok", f2)
finally:
    dsm.http_req.get = orig_get
check("氏名が無い列は従来どおり引き当てる",
      f2.get("qmEditor") == "Maik Jorn Teschner", str(f2))

print(f"\n{'=' * 46}\n  成功 {ok} 件 / 失敗 {ng} 件\n{'=' * 46}")
sys.exit(1 if ng else 0)
