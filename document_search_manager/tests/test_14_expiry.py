# -*- coding: utf-8 -*-
"""有効期限の表示と期限状態の判定 — v20260903_16

Nexusの標準書は有効期限を持つ。期限切れかどうかは業務上の重要情報なので、
最終更新日の右に列として出す。判定は**日付から自分で行う**（下記 E1 の理由）。
ネットワークには一切アクセスしない。

実行: python tests/test_14_expiry.py
"""
import sys
import threading
from datetime import datetime, timedelta
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
TODAY = datetime.now(dsm.JST).date()


def day(offset):
    return (TODAY + timedelta(days=offset)).strftime("%Y-%m-%d")


# ── E1 期限状態の判定 ────────────────────────────────────────
print("\n[E1] 有効期限からの状態判定")
check("昨日までは期限切れ", dsm._expiry_state(day(-1), CFG) == "expired", day(-1))
check("ずっと前も期限切れ", dsm._expiry_state(day(-400), CFG) == "expired")
check("今日は期限切れにしない（当日はまだ有効）",
      dsm._expiry_state(day(0), CFG) != "expired", dsm._expiry_state(day(0), CFG))
check("既定(60日)以内はまもなく期限",
      dsm._expiry_state(day(30), CFG) == "soon", dsm._expiry_state(day(30), CFG))
check("60日ちょうどはまもなく期限", dsm._expiry_state(day(60), CFG) == "soon")
check("61日先は有効", dsm._expiry_state(day(61), CFG) == "valid")
check("警告日数は設定で変えられる",
      dsm._expiry_state(day(30), dict(CFG, expiry_warn_days=10)) == "valid",
      dsm._expiry_state(day(30), dict(CFG, expiry_warn_days=10)))
check("警告を0日にすると、まもなく期限は出さない",
      dsm._expiry_state(day(1), dict(CFG, expiry_warn_days=0)) == "valid")
check("期限が無ければ判定しない", dsm._expiry_state("", CFG) == "")
check("不正な日付でも落ちない", dsm._expiry_state("not-a-date", CFG) == "")
check("空白だけでも落ちない", dsm._expiry_state("   ", CFG) == "")

# ── E2 実機のデータで期限が読める ────────────────────────────
print("\n[E2] Nexusの列からの取り込み")
REAL = {
    "qmDocumentNo": "NDS-00072",
    "qmDocumentTitle": "FMEA",
    "qmEditor": "Maik Jörn Teschner",
    "qmConfirmer": "Ansgar Thorns",
    "qmValidFrom": "2023-07-27T12:00:00Z",
    "qmValidUntil": "2026-07-27T12:00:00Z",
    "qmStatus": "Expired",
    "qmStatusEn": "Valid",
}
picked, sources = dsm._pick_nexus_fields(REAL, CFG)
check("有効期限を qmValidUntil から取る",
      picked.get("valid_until") == "2026-07-27T12:00:00Z", str(picked.get("valid_until")))
check("出所を記録する", sources.get("valid_until") == "qmValidUntil", str(sources))
check("qmStatus も取る（参考情報）", picked.get("doc_status") == "Expired")
check("qmStatusEn も取る（参考情報）", picked.get("doc_status_en") == "Valid")
check("有効期限に qmValidFrom を使わない",
      sources.get("valid_until") != "qmValidFrom", str(sources))


class FakeResp:
    def __init__(self, code, payload=None):
        self.status_code = code
        self._payload = payload or {}
        self.text = ""

    def json(self):
        return self._payload


def search_stub(token, query_string, frm, size):
    return 200, {"value": [{"hitsContainers": [{
        "total": 1, "hits": [{"resource": {"webUrl": SCOPE + "/FMEA.docx"}}],
        "moreResultsAvailable": False}]}]}, ""


def make_shares(fields):
    def fake_get(url, headers=None, params=None, timeout=None):
        if "/shares/" in url:
            return FakeResp(200, {"listItem": {"fields": dict(fields)}})
        return FakeResp(404)
    return fake_get


orig_get = dsm.http_req.get


def run_search(fields):
    nx = dsm.NexusProvider(CFG, DummyAuth())
    nx._people_cache = {}
    nx._people_lock = threading.Lock()
    nx._people_disabled = False
    nx._people_note = ""
    nx._mode = "search-api"
    nx._call_search_api = search_stub
    dsm.http_req.get = make_shares(fields)
    try:
        return nx.search("FMEA", 5)["results"][0]
    finally:
        dsm.http_req.get = orig_get


row = run_search(REAL)
check("有効期限をJSTの日付に整形する", row.valid_until == "2026-07-27", row.valid_until)
check("Nexus上のステータスも保持する",
      row.doc_status == "Expired" and row.doc_status_en == "Valid",
      f"{row.doc_status} / {row.doc_status_en}")

expired_row = run_search(dict(REAL, qmValidUntil=day(-10) + "T12:00:00Z"))
check("過去の期限は expired", expired_row.expiry_state == "expired",
      expired_row.expiry_state)
soon_row = run_search(dict(REAL, qmValidUntil=day(20) + "T12:00:00Z"))
check("近い期限は soon", soon_row.expiry_state == "soon", soon_row.expiry_state)
valid_row = run_search(dict(REAL, qmValidUntil=day(200) + "T12:00:00Z"))
check("先の期限は valid", valid_row.expiry_state == "valid", valid_row.expiry_state)

no_date = dict(REAL)
del no_date["qmValidUntil"]
none_row = run_search(no_date)
check("期限が無い文書は空欄のまま",
      none_row.valid_until == "" and none_row.expiry_state == "",
      f"{none_row.valid_until} / {none_row.expiry_state}")

# ── E3 画面 ──────────────────────────────────────────────────
print("\n[E3] 画面の列とバッジ")
mgr = dsm.SearchManager(CFG, DummyAuth())
mgr.providers[dsm.TARGET_NEXUS].search = (
    lambda kw, mx: {"results": [expired_row], "total": 1, "note": ""})
mgr.providers[dsm.TARGET_SHAREPOINT].search = (
    lambda kw, mx: {"results": [], "total": 0, "note": ""})
dsm._cfg = CFG
dsm._manager = mgr
client = dsm.flask_app.test_client()
html = client.get("/").get_data(as_text=True)

nexus_set = html.split("nexus: [")[1].split("],")[0]
check("Nexusタブに有効期限の列がある", 'key: "valid_until"' in nexus_set, nexus_set[:150])
check("列名は「有効期限」", 'label: "有効期限"' in nexus_set)
check("最終更新日の右に置く",
      nexus_set.index('key: "valid_until"') > nexus_set.index('key: "last_modified"'))
check("種別の左に置く",
      nexus_set.index('key: "valid_until"') < nexus_set.index('key: "doc_type"'))
check("日付範囲で絞り込める型にする",
      'key: "valid_until",       label: "有効期限",             type: "date"' in nexus_set
      or ('key: "valid_until"' in nexus_set and 'type: "date"' in nexus_set))
check("期限切れのバッジがある", "期限切れ" in html)
check("まもなくのバッジがある", "まもなく" in html)
check("バッジの配色がある", ".badge.expired" in html and ".badge.soon" in html)
check("アクセント色を使う", "background: var(--accent)" in html)
check("Nexus上のステータスをツールチップに添える",
      "Nexus上のステータス" in html)
check("SharePointタブには有効期限を出さない",
      'key: "valid_until"' not in html.split("sharepoint: [")[1].split("],")[0])

resp = client.post("/api/search", json={"keyword": "FMEA", "target": "nexus"})
data = resp.get_json()["results"][0]
check("APIが有効期限を返す", data["valid_until"] == expired_row.valid_until)
check("APIが期限状態を返す", data["expiry_state"] == "expired", data["expiry_state"])
check("APIがNexus上のステータスも返す", data["doc_status"] == "Expired")

# ── E4 出力 ──────────────────────────────────────────────────
print("\n[E4] Excel / CSV 出力")
head = client.get("/api/export?format=csv").get_data(as_text=True).splitlines()[0]
check("CSVに有効期限の列がある", "有効期限" in head, head)
check("CSVに期限状態の列がある", "期限状態" in head, head)
check("CSVにNexus上のステータスの列がある", "Nexus上のステータス" in head, head)
body = client.get("/api/export?format=csv").get_data(as_text=True).splitlines()[1]
check("期限状態を日本語で出力する", "期限切れ" in body, body)
check("Excel出力も200", client.get("/api/export?format=xlsx").status_code == 200)
check("期限状態の表示名を持つ",
      dsm.EXPIRY_LABELS["expired"] == "期限切れ"
      and dsm.EXPIRY_LABELS["soon"] == "まもなく期限"
      and dsm.EXPIRY_LABELS["valid"] == "有効")

print(f"\n{'=' * 46}\n  成功 {ok} 件 / 失敗 {ng} 件\n{'=' * 46}")
sys.exit(1 if ng else 0)
