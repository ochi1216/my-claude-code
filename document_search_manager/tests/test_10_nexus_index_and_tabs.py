# -*- coding: utf-8 -*-
"""Nexusの標準Index・タブ構成・ディープリンク・検索診断 — v20260903_10 で追加

ネットワークには一切アクセスせず、Graphを呼ぶ経路はすべてスタブ化する。
実行: python tests/test_10_nexus_index_and_tabs.py
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

# ── I1 列名の正規化と値の平坦化 ──────────────────────────────
print("\n[I1] リスト項目の列名の正規化と、値の平坦化")
check("空白と大小文字の違いを吸収",
      dsm._normalize_field_key("Document Number")
      == dsm._normalize_field_key("documentnumber"))
check("SharePointの _x0020_ 表記を吸収",
      dsm._normalize_field_key("Document_x0020_Number")
      == dsm._normalize_field_key("Document Number"))
check("記号の違いを吸収",
      dsm._normalize_field_key("Doc-Author") == dsm._normalize_field_key("Doc Author"))

check("文字列はそのまま", dsm._field_text(" NDS-00688 ") == "NDS-00688")
check("人物列(LookupValue)を読む",
      dsm._field_text({"LookupValue": "David Chen"}) == "David Chen")
check("人物列(DisplayName)も読む",
      dsm._field_text({"DisplayName": "Rob Geljon"}) == "Rob Geljon")
check("複数選択列(配列)は ; で連結",
      dsm._field_text(["Global Supply Chain", "Back End"])
      == "Global Supply Chain; Back End")
check("Noneは空文字", dsm._field_text(None) == "")
check("空の辞書は空文字", dsm._field_text({}) == "")
check("数値も文字列化", dsm._field_text(123) == "123")

# ── I2 標準Indexの取り出し ───────────────────────────────────
print("\n[I2] リスト項目 fields からの標準Indexの取り出し")
FIELDS = {
    "Document_x0020_Number": "NDS-00688",
    "OldSystemIdentifier": "XPR-0367",
    "Document Title": "Customer Programs Testing",
    "DocAuthor": {"LookupValue": "David Chen"},
    "Doc Owner": {"LookupValue": "Rob Geljon"},
    "ApplicableTo": ["Global Supply Chain"],
    "Department": "Global Supply Chain",
    "TopLevelProcess": "Plan",
    "FileLeafRef": "a.docx",
}
picked = dsm._pick_nexus_fields(FIELDS, CFG)
check("Document Number（_x0020_表記）", picked.get("document_number") == "NDS-00688",
      json.dumps(picked, ensure_ascii=False))
check("OldSystemIdentifier", picked.get("old_system_id") == "XPR-0367")
check("Document Title（空白入り表記）",
      picked.get("title") == "Customer Programs Testing")
check("Doc Author（人物列）", picked.get("doc_author") == "David Chen")
check("Doc Owner（空白入り＋人物列）", picked.get("doc_owner") == "Rob Geljon")
check("Applicable To（配列）", picked.get("applicable_to") == "Global Supply Chain")
check("Department", picked.get("department") == "Global Supply Chain")
check("Top Level Process", picked.get("top_level_process") == "Plan")
check("該当しない列は拾わない", "nonsense" not in picked)
check("fieldsが辞書でなくても落ちない", dsm._pick_nexus_fields(None, CFG) == {})

cfg_map = dict(CFG, nexus_field_map={"department": "Owning Dept"})
picked2 = dsm._pick_nexus_fields({"Owning Dept": "JP Site", "Department": "X"}, cfg_map)
check("nexus_field_map の指定を最優先する", picked2.get("department") == "JP Site",
      json.dumps(picked2, ensure_ascii=False))

# ── I3 Nexusディープリンク ───────────────────────────────────
print("\n[I3] Shareflex画面を検索済み状態で開くディープリンク")
link = dsm._nexus_deep_link(CFG, "NDS-00688")
check("設定のView.aspxを土台にする", link.startswith(CFG["nexus_view_url"]), link)
check("&q= でキーワードを渡す", "&q=NDS-00688" in link, link)
check("記号はURLエンコードする",
      "%20" in dsm._nexus_deep_link(CFG, "a b"),
      dsm._nexus_deep_link(CFG, "a b"))
check("キーワードが空ならリンクを作らない", dsm._nexus_deep_link(CFG, "") == "")
check("View.aspxが未設定ならリンクを作らない",
      dsm._nexus_deep_link(dict(CFG, nexus_view_url=""), "x") == "")
check("? しか無いURLでも壊れない",
      dsm._nexus_deep_link(dict(CFG, nexus_view_url="https://x/v.aspx"), "k")
      == "https://x/v.aspx?q=k")

# ── I4 絞り込み方式の切り替え ────────────────────────────────
print("\n[I4] KQLの絞り込み方式（nexus_scope_mode）")
nx_path = dsm.NexusProvider(CFG, DummyAuth())
check("既定はフォルダで限定（path:）",
      nx_path._query_string("validation") == f'validation path:"{SCOPE}"',
      nx_path._query_string("validation"))
nx_site = dsm.NexusProvider(dict(CFG, nexus_scope_mode="site"), DummyAuth())
check("site 指定なら SPSiteURL: で限定",
      'SPSiteURL:"https://nexperia.sharepoint.com/sites/SF_QualityDocumentsProd"'
      in nx_site._query_string("validation"), nx_site._query_string("validation"))
nx_none = dsm.NexusProvider(dict(CFG, nexus_scope_mode="none"), DummyAuth())
check("none 指定なら絞り込まない",
      nx_none._query_string("validation") == "validation")

# ── I5 検索診断 ──────────────────────────────────────────────
print("\n[I5] Nexus検索診断（件数の実測比較）")
asked = []


def diag_stub(token, query_string, frm, size):
    asked.append(query_string)
    return 200, {"value": [{"hitsContainers": [{
        "total": 116, "hits": [{"resource": {"webUrl": SCOPE + "/a.docx"}}],
        "moreResultsAvailable": True}]}]}, ""


nx_diag = dsm.NexusProvider(CFG, DummyAuth())
nx_diag._call_search_api = diag_stub
rows = nx_diag.diagnose("validation plan")
check("4方式ぶんを返す", len(rows) == 4, str(len(rows)))
check("① はフォルダ限定", 'path:"' in rows[0]["query"], rows[0]["query"])
check("② はサイト限定", "SPSiteURL:" in rows[1]["query"], rows[1]["query"])
check("③ は限定なし", rows[2]["query"] == "validation plan", rows[2]["query"])
check("④ は完全一致（引用符あり）", '"validation plan"' in rows[3]["query"],
      rows[3]["query"])
check("該当件数(total)を持ち帰る", all(r.get("total") == 116 for r in rows),
      json.dumps(rows, ensure_ascii=False)[:200])
check("実際に投げたKQLが4本", len(asked) == 4, str(len(asked)))

rows_q = dsm.NexusProvider(CFG, DummyAuth())
rows_q._call_search_api = diag_stub
out_q = rows_q.diagnose('"validation plan"')
check("引用符付きで入力された場合は「引用符を外す」案を比較する",
      "引用符を外す" in out_q[3]["label"], out_q[3]["label"])

check("キーワードが空なら診断しない", dsm.NexusProvider(CFG, DummyAuth()).diagnose("") == [])

# ── I6 標準Indexの付与（/shares のスタブ） ───────────────────
print("\n[I6] 検索結果への標準Indexの付与")


class FakeResp:
    def __init__(self, code, payload=None):
        self.status_code = code
        self._payload = payload or {}
        self.text = ""

    def json(self):
        return self._payload


calls = []


def fake_get(url, headers=None, params=None, timeout=None):
    calls.append((url, (params or {}).get("$expand")))
    return FakeResp(200, {"listItem": {"fields": FIELDS}})


def search_stub(token, query_string, frm, size):
    return 200, {"value": [{"hitsContainers": [{
        "total": 1,
        "hits": [{"resource": {"webUrl": SCOPE + "/a.docx"}}],
        "moreResultsAvailable": False}]}]}, ""


nx = dsm.NexusProvider(CFG, DummyAuth())
nx._mode = "search-api"
nx._call_search_api = search_stub
orig_get = dsm.http_req.get
dsm.http_req.get = fake_get
try:
    out = nx.search("validation", 10)
finally:
    dsm.http_req.get = orig_get

row = out["results"][0]
check("/shares 経由でリスト項目を引く", calls and "/shares/" in calls[0][0], str(calls[:1]))
check("入れ子の $expand を要求する",
      calls and calls[0][1] == "listItem($expand=fields)", str(calls[:1]))
check("Document Number が入る", row.document_number == "NDS-00688", row.document_number)
check("OldSystemIdentifier が入る", row.old_system_id == "XPR-0367")
check("Doc Author が入る", row.doc_author == "David Chen")
check("Doc Owner が入る", row.doc_owner == "Rob Geljon")
check("Applicable To が入る", row.applicable_to == "Global Supply Chain")
check("Department が入る", row.department == "Global Supply Chain")
check("Document Title をタイトルに使う", row.title == "Customer Programs Testing",
      row.title)
check("Nexusで開くリンクが文書番号で作られる", "&q=NDS-00688" in row.nexus_url,
      row.nexus_url)
check("取得できた件数を note に出す", "Index列を 1/1 件" in out["note"], out["note"])


def fail_get(url, headers=None, params=None, timeout=None):
    return FakeResp(404)


nx2 = dsm.NexusProvider(CFG, DummyAuth())
nx2._mode = "search-api"
nx2._call_search_api = search_stub
dsm.http_req.get = fail_get
try:
    out2 = nx2.search("validation", 10)
finally:
    dsm.http_req.get = orig_get
check("Index列が取れなくても検索結果は残す（黙って消さない）",
      len(out2["results"]) == 1, str(len(out2["results"])))
check("取れなかったことを note に明示する",
      "取得できませんでした" in out2["note"], out2["note"])
check("それでもディープリンクはタイトルで作る",
      "&q=" in out2["results"][0].nexus_url, out2["results"][0].nexus_url)

nx3 = dsm.NexusProvider(dict(CFG, nexus_enrich_metadata=False), DummyAuth())
nx3._mode = "search-api"
nx3._call_search_api = search_stub
called = []
dsm.http_req.get = lambda *a, **k: called.append(1) or FakeResp(200, {})
try:
    nx3.search("validation", 10)
finally:
    dsm.http_req.get = orig_get
check("nexus_enrich_metadata=false ならリスト項目を引かない", not called, str(called))

# ── I7 画面（タブと列構成） ──────────────────────────────────
print("\n[I7] 画面のタブと列構成")
mgr = dsm.SearchManager(CFG, DummyAuth())
mgr.providers[dsm.TARGET_SHAREPOINT].search = (
    lambda kw, mx: {"results": [], "total": 0, "note": ""})
mgr.providers[dsm.TARGET_NEXUS].search = (
    lambda kw, mx: {"results": [], "total": 0, "note": ""})
dsm._cfg = CFG
dsm._manager = mgr
client = dsm.flask_app.test_client()
html = client.get("/").get_data(as_text=True)

check("版数表示が v20260903_10", "v20260903_10 (Phase 2.5" in html)
for target in ("all", "sharepoint", "nexus", "enovia"):
    check(f"{target} タブがある", f'data-target="{target}"' in html)
check("既定は All タブ", 'class="on" data-target="all"' in html)

nexus_set = html.split("nexus: [")[1].split("],")[0]
for key in ("document_number", "old_system_id", "doc_author", "doc_owner",
            "applicable_to", "department", "nexus_url"):
    check(f"Nexusタブの列に {key} がある", f'key: "{key}"' in nexus_set, nexus_set[:120])
check("Nexusタブにフォルダ列を出さない", 'key: "folder"' not in nexus_set)
check("Nexusタブにサイト列を出さない", 'key: "site"' not in nexus_set)
check("Allタブにもフォルダ列を出さない（Nexusでは無意味なため）",
      'key: "folder"' not in html.split("all: [")[1].split("],")[0])
check("SharePointタブにはフォルダ列を残す",
      'key: "folder"' in html.split("sharepoint: [")[1].split("],")[0])
check("列構成の切り替えで不要な絞り込みを落とす実装がある",
      "applyColumnSet" in html)
check("Nexus検索診断のボタンがある", 'id="btnNexusDiag"' in html)
check("該当件数の併記がある", "（該当 " in html)

# ── I8 API ───────────────────────────────────────────────────
print("\n[I8] API")
resp = client.post("/api/search",
                   json={"keyword": "validation", "target": "nexus", "max_results": 10})
check("検索APIが200", resp.status_code == 200, str(resp.status_code))
check("検索APIが target を返す（画面の列切替に使う）",
      resp.get_json().get("target") == "nexus", json.dumps(resp.get_json())[:200])

diag_provider = dsm.NexusProvider(CFG, DummyAuth())
diag_provider._call_search_api = diag_stub
mgr.providers[dsm.TARGET_NEXUS] = diag_provider
resp = client.post("/api/nexus_diag", json={"keyword": "validation plan"})
check("診断APIが200", resp.status_code == 200, str(resp.status_code))
check("診断APIが4方式を返す", len(resp.get_json()["rows"]) == 4)
check("診断APIは空キーワードを400", 
      client.post("/api/nexus_diag", json={"keyword": ""}).status_code == 400)

# ── I9 Nexusだけの結果はIndex列で出力する ────────────────────
print("\n[I9] Excel / CSV 出力の列構成")
nexus_row = dsm.SearchResult(
    source="Nexus", document_number="NDS-00688", old_system_id="XPR-0367",
    title="Customer Programs Testing", doc_author="David Chen",
    doc_owner="Rob Geljon", applicable_to="Global Supply Chain",
    department="Global Supply Chain", last_modified="2026-03-19", doc_type="docx",
    url="https://x/a.docx", nexus_url="https://x/v.aspx?q=NDS-00688", rank=1)
mgr.providers[dsm.TARGET_NEXUS].search = (
    lambda kw, mx: {"results": [nexus_row], "total": 1, "note": ""})
client.post("/api/search", json={"keyword": "validation", "target": "nexus"})

head = client.get("/api/export?format=csv").get_data(as_text=True).splitlines()[0]
for label in ("Document Number", "OldSystemIdentifier", "Document Title",
              "Doc Author", "Doc Owner", "Applicable To", "Department"):
    check(f"CSVヘッダーに {label} がある", label in head, head)
check("CSVヘッダーに Nexusリンクがある", "Nexusリンク" in head, head)
check("Nexusの出力にサイト／フォルダ列を出さない",
      "フォルダリンク" not in head and "サイトリンク" not in head, head)
check("Excel出力も200", client.get("/api/export?format=xlsx").status_code == 200)

mixed = dsm.SearchResult(source="SharePoint", title="a", url="https://x/a.docx")
mgr.providers[dsm.TARGET_SHAREPOINT].search = (
    lambda kw, mx: {"results": [mixed], "total": 1, "note": ""})
mgr.providers[dsm.TARGET_NEXUS].search = (
    lambda kw, mx: {"results": [], "total": 0, "note": ""})
client.post("/api/search", json={"keyword": "validation", "target": "sharepoint"})
head2 = client.get("/api/export?format=csv").get_data(as_text=True).splitlines()[0]
check("SharePointの結果は従来どおりの列構成",
      "フォルダ" in head2 and "サイトリンク" in head2, head2)
check("SharePointの出力にIndex列を出さない", "Document Number" not in head2, head2)

print(f"\n{'=' * 46}\n  成功 {ok} 件 / 失敗 {ng} 件\n{'=' * 46}")
sys.exit(1 if ng else 0)
