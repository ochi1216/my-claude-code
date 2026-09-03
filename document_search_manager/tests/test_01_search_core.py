# -*- coding: utf-8 -*-
"""検索の中核（パーサ・ページング・並列実行・重複排除・API）

ネットワークには一切アクセスせず、最新バージョンの本体を読み込んで検証する。
実行: python tests/test_01_search_core.py   （まとめて実行する場合は python tests/run_tests.py）
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

# ── T1 パーサ ────────────────────────────────────────────────
print("\n[T1] Graph Search hit のパース")
provider = dsm.SharePointProvider(CFG, auth=None)

# (a) 検索マネージドプロパティ(小文字)が入ってくる標準ケース
hit_a = {
    "rank": 1,
    "resource": {
        "webUrl": "https://nexperia.sharepoint.com/sites/JapanDesign/Docs/a.docx",
        "fields": {
            "title": "Validation Report 2026",
            "filename": "a.docx",
            "author": "Taro Ochi",
            "lastModifiedTime": "2026-07-14T09:12:33Z",
            "fileExtension": "docx",
            "siteTitle": "Japan Design",
        },
    },
}
r = provider._hit_to_result(hit_a, 1)
check("title を fields.title から取得", r.title == "Validation Report 2026", r.title)
check("author を fields.author から取得", r.author == "Taro Ochi", r.author)
check("日付をJSTで整形", r.last_modified == "2026-07-14", r.last_modified)
check("拡張子を取得", r.doc_type == "docx", r.doc_type)
check("URLを取得", r.url.endswith("a.docx"), r.url)
check("Nexus判定=False", r.is_nexus_path is False)

# (b) fields が空で、resource 直下しか無いケース（形が変わっても落ちないこと）
hit_b = {
    "resource": {
        "name": "spec.pdf",
        "webUrl": "https://nexperia.sharepoint.com/sites/SF_QualityDocumentsProd/Documents/spec.pdf",
        "lastModifiedDateTime": "2026-01-05T23:30:00Z",
        "createdBy": {"user": {"displayName": "Hanako Suzuki"}},
    }
}
r = provider._hit_to_result(hit_b, 2)
check("fields無しでも name からタイトル復元", r.title == "spec.pdf", r.title)
check("fields無しでも createdBy から作成者復元", r.author == "Hanako Suzuki", r.author)
check("拡張子をファイル名から復元", r.doc_type == "pdf", r.doc_type)
check("UTC→JSTで日付繰り上がり", r.last_modified == "2026-01-06", r.last_modified)
check("Nexusサイト配下を判定", r.is_nexus_path is True)

# (c) 完全に空の hit（クラッシュしないこと）
r = provider._hit_to_result({}, 3)
check("空hitでも例外を出さない", r.title == "(タイトルなし)", r.title)
check("空hitのURLは空文字", r.url == "")

# (d) Document Number 系のカスタム列
hit_d = {"resource": {"fields": {"title": "Q Doc", "documentNumber": "NDS-00688",
                                 "oldSystemIdentifier": "XPR-0367"}}}
r = provider._hit_to_result(hit_d, 4)
check("Document Number を取得", r.document_number == "NDS-00688", r.document_number)

# ── T2 ユーティリティ ────────────────────────────────────────
print("\n[T2] ユーティリティ")
check("不正日付は原文先頭10文字", dsm._format_datetime("not-a-date") == "not-a-date")
check("空日付は空文字", dsm._format_datetime("") == "")
check("拡張子なしファイル名", dsm._extension_of("README") == "")
check("_pick は最初の非空を返す", dsm._pick("", None, "x", "y") == "x")

cfg_mcas = dict(CFG, rewrite_host_to_mcas=True)
u = dsm._rewrite_url("https://nexperia.sharepoint.com/sites/A/x.docx", cfg_mcas)
check("MCAS書き換えON", u.startswith("https://nexperia.sharepoint.com.mcas.ms/"), u)
u2 = dsm._rewrite_url("https://nexperia.sharepoint.com/sites/A/x.docx", CFG)
check("MCAS書き換えOFF（既定）", ".mcas.ms" not in u2, u2)

host, path = dsm.SharePointProvider._split_site_url(
    "https://nexperia.sharepoint.com/sites/JapanDesign/")
check("サイトURL分解", (host, path) == ("nexperia.sharepoint.com", "/sites/JapanDesign"),
      f"{host} {path}")

# ── T3 ページング ────────────────────────────────────────────
print("\n[T3] ページング（Graph呼び出しはスタブ）")


def make_stub(total_hits):
    """total_hits 件を page_size ずつ返すスタブを作る。"""
    calls = []

    def stub(token, query_string, frm, size):
        calls.append((frm, size))
        hits = []
        for i in range(frm, min(frm + size, total_hits)):
            hits.append({"resource": {"name": f"doc{i}.docx",
                                      "webUrl": f"https://x/{i}.docx"}})
        return 200, {"value": [{"hitsContainers": [{
            "total": total_hits,
            "hits": hits,
            "moreResultsAvailable": (frm + size) < total_hits,
        }]}]}, ""
    return stub, calls


p = dsm.SharePointProvider(dict(CFG, page_size=25), auth=None)
stub, calls = make_stub(120)
p._call_search_api = stub
out = p._search_by_search_api("tok", "validation", 100)
check("上限100件で打ち切る", len(out["results"]) == 100, str(len(out["results"])))
check("total を保持", out["total"] == 120, str(out["total"]))
check("25件ずつ4回呼ぶ", len(calls) == 4, str(calls))
check("rank が1始まりの連番", out["results"][0].rank == 1 and out["results"][99].rank == 100)

# 総件数が上限未満のケース
stub2, calls2 = make_stub(7)
p._call_search_api = stub2
out2 = p._search_by_search_api("tok", "x", 100)
check("ヒットが少ない場合は1回で終了", len(out2["results"]) == 7 and len(calls2) == 1,
      f"{len(out2['results'])} / {calls2}")

# 途中でエラーになっても、取れた分は返す
state = {"n": 0}


def flaky(token, q, frm, size):
    state["n"] += 1
    if state["n"] == 1:
        return 200, {"value": [{"hitsContainers": [{
            "total": 100, "moreResultsAvailable": True,
            "hits": [{"resource": {"name": "a.docx"}}]}]}]}, ""
    return 503, None, "service unavailable"


p._call_search_api = flaky
out3 = p._search_by_search_api("tok", "x", 100)
check("途中エラーでも取得済み分を返す（部分成功）", len(out3["results"]) == 1,
      str(len(out3["results"])))

# 1回目からエラーなら例外
p._call_search_api = lambda *a, **k: (403, None, "Forbidden")
try:
    p._search_by_search_api("tok", "x", 10)
    check("初回エラーで例外", False, "例外が出なかった")
except RuntimeError as e:
    check("初回エラーで例外", "403" in str(e), str(e))

# ── T4 重複排除 ──────────────────────────────────────────────
print("\n[T4] Nexus重複排除")



rows = [
    dsm.SearchResult(source="SharePoint", title="a", is_nexus_path=False),
    dsm.SearchResult(source="SharePoint", title="b", is_nexus_path=True),
    dsm.SearchResult(source="Nexus", title="b", is_nexus_path=True),
]
m_off = dsm.SearchManager(dict(CFG, dedupe_nexus_from_sharepoint=False), DummyAuth())
kept, exc = m_off._dedupe(list(rows))
check("Phase1既定(false)では除外しない", len(kept) == 3 and exc == 0, f"{len(kept)}/{exc}")

m_on = dsm.SearchManager(dict(CFG, dedupe_nexus_from_sharepoint=True), DummyAuth())
kept, exc = m_on._dedupe(list(rows))
check("Phase2(true)ではSharePoint側のNexus文書を除外", len(kept) == 2 and exc == 1,
      f"{len(kept)}/{exc}")
check("除外後もNexus側の行は残る", any(r.source == "Nexus" for r in kept))

# ── T5 系統ごとの扱い ────────────────────────────────────────
# v09 で Nexus を実装したため、「Nexus＝未実装」を前提にしていた項目を
# 実装済みの前提に更新した（機能の劣化ではなく、仕様変更に伴うテストの陳腐化）。
# 未実装として残るのは Enovia のみ。
# 実装済みの系統は Graph を呼びに行くため、ネットワークに出ないよう
# search() をスタブに差し替えてから検証する。
print("\n[T5] 系統ごとの扱い（Nexus=実装済み / Enovia=未実装）")
mgr = dsm.SearchManager(CFG, DummyAuth())


def stub_hit(source, title):
    """1件だけ返すスタブを作る（ネットワークに出ないようにするため）。"""
    return lambda kw, mx: {"results": [dsm.SearchResult(source=source, title=title)],
                           "total": 1, "note": ""}


mgr.providers[dsm.TARGET_NEXUS].search = stub_hit("Nexus", "nexus-hit")
res = mgr.search("validation", dsm.TARGET_NEXUS, 100)
check("Nexus単独指定が結果を返す（実装済み）",
      len(res["results"]) == 1 and res["statuses"][0]["implemented"] is True,
      json.dumps(res["statuses"]))
check("Nexus単独指定ではSharePointを呼ばない",
      [s["key"] for s in res["statuses"]] == ["nexus"],
      str([s["key"] for s in res["statuses"]]))

res_e = mgr.search("validation", dsm.TARGET_ENOVIA, 100)
check("Enovia単独指定は未実装として返る",
      res_e["results"] == [] and res_e["statuses"][0]["implemented"] is False)
check("未実装メッセージにPhase 3と明示する",
      "Phase 3" in res_e["statuses"][0]["message"], res_e["statuses"][0]["message"])

# All 実行（SharePoint・Nexusともスタブ化）
mgr.providers[dsm.TARGET_SHAREPOINT].search = stub_hit("SharePoint", "hit1")
res_all = mgr.search("validation", dsm.TARGET_ALL, 100)
keys = sorted(s["key"] for s in res_all["statuses"])
check("Allで3系統すべてのステータスを返す",
      keys == ["enovia", "nexus", "sharepoint"], str(keys))
check("Allの結果はSharePointとNexusの2件", len(res_all["results"]) == 2,
      str(len(res_all["results"])))
sp = [s for s in res_all["statuses"] if s["key"] == "sharepoint"][0]
check("SharePointのstateがok", sp["state"] == "ok", sp["state"])
nx = [s for s in res_all["statuses"] if s["key"] == "nexus"][0]
check("Nexusのstateがok", nx["state"] == "ok", nx["state"])
en = [s for s in res_all["statuses"] if s["key"] == "enovia"][0]
check("Enoviaのstateがpending", en["state"] == "pending", en["state"])

# プロバイダが例外を投げても他系統は生き残る
mgr.providers[dsm.TARGET_SHAREPOINT].search = (
    lambda kw, mx: (_ for _ in ()).throw(RuntimeError("boom")))
res_err = mgr.search("validation", dsm.TARGET_ALL, 100)
sp_err = [s for s in res_err["statuses"] if s["key"] == "sharepoint"][0]
check("例外時はstate=errorで部分成功", sp_err["state"] == "error" and "boom" in sp_err["message"],
      json.dumps(sp_err))

# ── T6 Flaskエンドポイント ───────────────────────────────────
print("\n[T6] Flaskエンドポイント")
dsm._cfg = CFG
dsm._manager = mgr
# Nexusは0件を返すスタブにしておく（このブロックはSharePoint側の応答を検証する）
mgr.providers[dsm.TARGET_NEXUS].search = (
    lambda kw, mx: {"results": [], "total": 0, "note": ""})
mgr.providers[dsm.TARGET_SHAREPOINT].search = (
    lambda kw, mx: {"results": [
        dsm.SearchResult(source="SharePoint", document_number="NDS-1",
                         title="Validation Report", author="Ochi",
                         last_modified="2026-07-14", doc_type="docx",
                         site="Japan Design", url="https://x/a.docx", rank=1)],
        "total": 1, "note": ""})

client = dsm.flask_app.test_client()

resp = client.get("/")
check("GET / が200", resp.status_code == 200, str(resp.status_code))
html = resp.get_data(as_text=True)
check("ダークテーマ色 #1a1a2e を含む", "#1a1a2e" in html)
check("アクセント色 #e94560 を含む", "#e94560" in html)
check("0.All が既定選択", 'value="all" checked' in html)

resp = client.post("/api/search", json={"keyword": "", "target": "all"})
check("空キーワードは400", resp.status_code == 400, str(resp.status_code))

resp = client.post("/api/search",
                   json={"keyword": "validation", "target": "all", "max_results": 100})
check("POST /api/search が200", resp.status_code == 200, str(resp.status_code))
data = resp.get_json()
check("結果1件を返す", len(data["results"]) == 1, json.dumps(data)[:200])
check("結果にDocument Numberを含む", data["results"][0]["document_number"] == "NDS-1")
check("elapsed_sec を返す", "elapsed_sec" in data)

resp = client.post("/api/search",
                   json={"keyword": "x", "target": "all", "max_results": 99999})
check("max_results は hard_max_results で丸める", resp.status_code == 200)

resp = client.get("/api/export?format=csv")
check("CSV出力が200", resp.status_code == 200, str(resp.status_code))
body = resp.get_data(as_text=True)
# v06 で Document Number 列を廃止したため、別の列名で日本語ヘッダーを確認する
check("CSVヘッダーが日本語", "タイトル" in body and "最終更新日" in body, body[:120])
check("CSVに検索結果行が入る", "Validation Report" in body)

resp = client.get("/api/export?format=xlsx")
check("Excel出力が200", resp.status_code == 200, str(resp.status_code))
check("Excelのcontent-type", "spreadsheet" in resp.headers.get("Content-Type", ""),
      resp.headers.get("Content-Type", ""))

resp = client.post("/api/probe")
check("POST /api/probe が200", resp.status_code == 200, str(resp.status_code))
probes = resp.get_json()["probes"]
check("probeが3系統を返す", len(probes) == 3, str(len(probes)))

print(f"\n{'=' * 46}")
print(f"  成功 {ok} 件 / 失敗 {ng} 件")
print(f"{'=' * 46}")
sys.exit(1 if ng else 0)
