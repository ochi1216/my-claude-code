# -*- coding: utf-8 -*-
"""並列実行の部分成功・実機で判明した内部列名・Index取得の対象 — v20260903_11

ネットワークには一切アクセスしない。
実行: python tests/test_11_timeout_and_fields.py
"""
import sys
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

# ── T1 片方が時間内に終わらなくても、全体を失敗にしない ──────
# v20260904_01でEnoviaが実装済みになり TARGET_ALL の対象が3系統になったため、
# 全体の待ち時間枠（provider_timeout_sec × 系統数）も3倍になった。
# sleepの長さは系統数から動的に計算し、版が上がって系統が増えても
# このテストが陳腐化しないようにする（仕様変更ではなく実装数の変化のため）。
print("\n[T1] 並列実行の部分成功（v10で HTTP 500 になっていた不具合）")
cfg_fast = dict(CFG, provider_timeout_sec=1)
mgr = dsm.SearchManager(cfg_fast, DummyAuth())
sleep_sec = cfg_fast["provider_timeout_sec"] * len(mgr.providers) + 1.5


def slow_search(keyword, max_results):
    time.sleep(sleep_sec)      # 全体の待ち時間枠を確実に超える
    return {"results": [], "total": 0, "note": ""}


mgr.providers[dsm.TARGET_SHAREPOINT].search = (
    lambda kw, mx: {"results": [dsm.SearchResult(source="SharePoint", title="hit")],
                    "total": 1, "note": ""})
mgr.providers[dsm.TARGET_NEXUS].search = slow_search
# Enoviaは未ログインで例外を投げても検証に支障はないが、この検証の主眼は
# Nexusのタイムアウトなので、即時0件を返すスタブにして明確にしておく。
mgr.providers[dsm.TARGET_ENOVIA].search = (
    lambda kw, mx: {"results": [], "total": 0, "note": ""})

out = mgr.search("validation", dsm.TARGET_ALL, 10)
check("例外を投げず結果を返す（部分成功）", isinstance(out, dict), str(type(out)))
check("間に合った系統の結果は失わない", len(out["results"]) == 1,
      str(len(out["results"])))
nx = [s for s in out["statuses"] if s["key"] == "nexus"][0]
check("間に合わなかった系統は state=error", nx["state"] == "error", nx["state"])
check("理由を「制限時間内に応答がありません」と示す",
      "制限時間" in nx["message"], nx["message"])
check("対処方法（件数を減らす／設定を延ばす）を示す",
      "provider_timeout_sec" in nx["message"], nx["message"])
sp = [s for s in out["statuses"] if s["key"] == "sharepoint"][0]
check("間に合った系統は state=ok", sp["state"] == "ok", sp["state"])

# APIも500にならないこと
dsm._cfg = cfg_fast
dsm._manager = mgr
client = dsm.flask_app.test_client()
resp = client.post("/api/search",
                   json={"keyword": "validation", "target": "all", "max_results": 10})
check("APIが500にならない", resp.status_code == 200, str(resp.status_code))
check("APIも結果を返す", len(resp.get_json()["results"]) == 1)

check("provider_timeout_sec の既定を延ばした（Index取得ぶん）",
      CFG["provider_timeout_sec"] >= 120, str(CFG["provider_timeout_sec"]))

# ── T2 実機で判明した内部列名 ────────────────────────────────
print("\n[T2] 実機（Nexperiaテナント）で判明したShareflexの内部列名")
REAL = {
    "qmDocumentNo": "NDS-00688",
    "nxOldDocumentNo": "XPR-0367",
    "qmDocumentTitle": "Customer Programs Testing",
    "qmDocumentType": "Process Description",
    "nxApplicable": "Global Supply Chain",
    "nxFunctionalOrg": "Global Supply Chain",
    "qmProcess1": "Plan",
    "Title": "a",
    "FileLeafRef": "a.docx",
}
picked, sources = dsm._pick_nexus_fields(REAL, CFG)
check("qmDocumentNo → Document Number", picked.get("document_number") == "NDS-00688",
      json.dumps(picked, ensure_ascii=False))
check("nxOldDocumentNo → OldSystemIdentifier", picked.get("old_system_id") == "XPR-0367")
check("qmDocumentTitle → Document Title（Title より優先）",
      picked.get("title") == "Customer Programs Testing", picked.get("title"))
check("nxApplicable → Applicable To", picked.get("applicable_to") == "Global Supply Chain")
check("nxFunctionalOrg → Department", picked.get("department") == "Global Supply Chain")
check("qmProcess1 → Top Level Process", picked.get("top_level_process") == "Plan")
check("qmDocumentType → Document Type", picked.get("document_type") == "Process Description")

# ── T3 人物列（LookupId）の数値は採用しない ──────────────────
print("\n[T3] 人物列が数値IDでしか返らない場合の扱い")
only_ids = {"qmEditorLookupId": 27, "AuthorLookupId": "31",
            "qmConfirmerLookupId": 44}
picked_ids, _s = dsm._pick_nexus_fields(only_ids, CFG)
check("LookupIdの数値は Doc Author に採用しない",
      "doc_author" not in picked_ids, json.dumps(picked_ids, ensure_ascii=False))
check("LookupIdの数値は Doc Owner に採用しない", "doc_owner" not in picked_ids)

named = {"qmEditorLookupId": 27, "qmEditor": {"LookupValue": "David Chen"},
         "qmApprover": "Rob Geljon"}
picked_named, _s2 = dsm._pick_nexus_fields(named, CFG)
check("名前が取れる列があればそちらを使う",
      picked_named.get("doc_author") == "David Chen",
      json.dumps(picked_named, ensure_ascii=False))
check("Doc Owner も名前が取れれば使う", picked_named.get("doc_owner") == "Rob Geljon")

# v12: 人物列は _resolve_people が <列名>LookupId → <列名> に直したうえで
# 対応づける。氏名が直接入っていた場合も同じ経路で拾えることを確認する。
nx_resolve = dsm.NexusProvider(CFG, DummyAuth())
direct = {"qmEditorLookupId": "David Chen", "qmOwnerLookupId": ["Rob Geljon"]}
nx_resolve._resolve_people("tok", direct)
check("数値でないLookupIdの値は、そのまま素直な列名へ引き継ぐ",
      direct.get("qmEditor") == "David Chen", str(direct))
check("配列でも引き継ぐ", direct.get("qmOwner") == "Rob Geljon", str(direct))
check("引き継いだ値がIndex列に載る",
      dsm._pick_nexus_fields(direct, CFG)[0].get("doc_author") == "David Chen")
check("qmDocumentNo から採ったことを記録する",
      sources.get("document_number") == "qmDocumentNo", str(sources))

# ── T4 Index取得は Nexusタブのときだけ ───────────────────────
print("\n[T4] Index取得は「2. Nexus」タブのときだけ行う")


class FakeResp:
    def __init__(self, code, payload=None):
        self.status_code = code
        self._payload = payload or {}
        self.text = ""

    def json(self):
        return self._payload


def search_stub(token, query_string, frm, size):
    return 200, {"value": [{"hitsContainers": [{
        "total": 1, "hits": [{"resource": {"webUrl": SCOPE + "/a.docx"}}],
        "moreResultsAvailable": False}]}]}, ""


shares_calls = []


def fake_get(url, headers=None, params=None, timeout=None):
    shares_calls.append(url)
    return FakeResp(200, {"listItem": {"fields": REAL}})


mgr2 = dsm.SearchManager(CFG, DummyAuth())
nx_provider = mgr2.providers[dsm.TARGET_NEXUS]
nx_provider._mode = "search-api"
nx_provider._call_search_api = search_stub
mgr2.providers[dsm.TARGET_SHAREPOINT].search = (
    lambda kw, mx: {"results": [], "total": 0, "note": ""})

orig_get = dsm.http_req.get
dsm.http_req.get = fake_get
try:
    out_all = mgr2.search("validation", dsm.TARGET_ALL, 10)
    calls_after_all = len(shares_calls)
    out_nx = mgr2.search("validation", dsm.TARGET_NEXUS, 10)
    calls_after_nexus = len(shares_calls)
finally:
    dsm.http_req.get = orig_get

check("0.All ではIndexを取りに行かない（待ち時間を増やさない）",
      calls_after_all == 0, str(calls_after_all))
check("2.Nexus ではIndexを取りに行く", calls_after_nexus == 1, str(calls_after_nexus))
check("0.All でも検索結果自体は返る", len(out_all["results"]) == 1,
      str(len(out_all["results"])))
check("2.Nexus ではIndexが埋まる",
      out_nx["results"][0].document_number == "NDS-00688",
      out_nx["results"][0].document_number)
check("0.All ではIndexは空のまま",
      out_all["results"][0].document_number == "",
      out_all["results"][0].document_number)

# ── T5 画面：引用符の注意喚起 ────────────────────────────────
print("\n[T5] 引用符付きキーワードの注意喚起")
dsm._cfg = CFG
dsm._manager = mgr2
html = dsm.flask_app.test_client().get("/").get_data(as_text=True)
check("引用符を検知する実装がある", 'keyword.indexOf("\\"")' in html)
check("完全一致になる旨を伝える", "完全一致" in html)
check("Nexus画面と比べるときは外すよう案内する",
      "引用符を外して" in html)

print(f"\n{'=' * 46}\n  成功 {ok} 件 / 失敗 {ng} 件\n{'=' * 46}")
sys.exit(1 if ng else 0)
