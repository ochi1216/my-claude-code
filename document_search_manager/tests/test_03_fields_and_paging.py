# -*- coding: utf-8 -*-
"""fieldsの明示要求とURL由来のフォールバック

ネットワークには一切アクセスせず、最新バージョンの本体を読み込んで検証する。
実行: python tests/test_03_fields_and_paging.py   （まとめて実行する場合は python tests/run_tests.py）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import dsm, DummyAuth  # noqa: E402

import json

ok, ng = 0, 0
def check(label, cond, detail=""):
    global ok, ng
    if cond: ok += 1; print(f"  OK   {label}")
    else:    ng += 1; print(f"  NG   {label}  {detail}")

CFG = dict(dsm.DEFAULT_CFG)

print("\n[V1] 越智さんの画面で起きた状態の再現と修正確認")
# 実機で返っていたとみられる形: fields が無く、webUrl と createdBy だけ
hit_real = {
    "resource": {
        "webUrl": "https://nexperia.sharepoint.com/sites/JapanTE/Shared%20Documents/"
                  "R19%20Validation%20Report%20v3.pptx",
        "lastModifiedDateTime": "2026-09-02T01:00:00Z",
        "createdBy": {"user": {"displayName": "Takahiro Miyazaki"}},
    }
}
p = dsm.SharePointProvider(CFG, auth=None)
r = p._hit_to_result(hit_real, 1)
check("タイトルをURLから復元（(タイトルなし)にならない）",
      r.title == "R19 Validation Report v3.pptx", r.title)
check("URLエンコード(%20)をスペースに戻す", " " in r.title, r.title)
check("種別をURLから復元", r.doc_type == "pptx", r.doc_type)
check("作成者は従来どおり取得", r.author == "Takahiro Miyazaki", r.author)
check("最終更新日は従来どおり取得", r.last_modified == "2026-09-02", r.last_modified)

print("\n[V2] fields が返ってきた場合は fields を優先")
hit_fields = {
    "resource": {
        "webUrl": "https://nexperia.sharepoint.com/sites/A/Docs/file01.docx",
        "fields": {"title": "検証手順書 2026年版", "fileExtension": "docx",
                   "author": "Yuto Oi", "lastModifiedTime": "2026-08-21T00:00:00Z"},
    }
}
r = p._hit_to_result(hit_fields, 1)
check("fields.title を優先", r.title == "検証手順書 2026年版", r.title)
check("fields.fileExtension を優先", r.doc_type == "docx", r.doc_type)

print("\n[V3] URLからのファイル名復元ユーティリティ")
cases = [
    ("https://x/sites/A/Docs/a%20b.pdf", "a b.pdf"),
    ("https://x/sites/A/Docs/", "Docs"),
    ("https://x/sites/A/Docs/%E6%97%A5%E6%9C%AC%E8%AA%9E.xlsx", "日本語.xlsx"),
    ("", ""),
    ("https://x", ""),
]
for url, want in cases:
    got = dsm._name_from_url(url)
    check(f"URL復元: {url[:40] or '(空)'} → {want or '(空)'}", got == want, got)

print("\n[V4] fields指定がHTTP 400で拒否された場合の自動再試行")
calls = []
class FakeResp:
    def __init__(self, code, payload=None):
        self.status_code = code
        self._payload = payload or {}
        self.text = "Bad Request: invalid field"
    def json(self): return self._payload

def fake_post(url, headers=None, json=None, timeout=None):
    body = json["requests"][0]
    calls.append("fields" in body)
    if "fields" in body:
        return FakeResp(400)
    return FakeResp(200, {"value": [{"hitsContainers": [
        {"total": 1, "hits": [{"resource": {"webUrl": "https://x/a.docx"}}],
         "moreResultsAvailable": False}]}]})

p2 = dsm.SharePointProvider(CFG, auth=None)
p2._fields_disabled = False
orig_post = dsm.http_req.post
dsm.http_req.post = fake_post
try:
    status, body, err = p2._call_search_api("tok", "validation", 0, 10)
    check("400を受けてfields無しで再試行し成功する", status == 200, f"{status} {err}")
    check("1回目はfieldsあり、2回目はfieldsなし", calls == [True, False], str(calls))
    check("以後はfieldsを要求しない", p2._fields_disabled is True)
    calls.clear()
    p2._call_search_api("tok", "x", 0, 10)
    check("2回目以降は最初からfields無し", calls == [False], str(calls))
finally:
    dsm.http_req.post = orig_post

print("\n[V5] 画面の件数プルダウンと /api/config")
dsm._cfg = dict(CFG, default_max_results=10)
dsm._manager = dsm.SearchManager(dsm._cfg, DummyAuth())
client = dsm.flask_app.test_client()

html = client.get("/").get_data(as_text=True)
# v08 で「何の上位か」を明確にするため「関連度上位 N 件」に表記を変更した
for v, label in [("10", "関連度上位 10 件"), ("25", "関連度上位 25 件"),
                 ("50", "関連度上位 50 件"), ("100", "関連度上位 100 件"),
                 ("200", "関連度上位 200 件"), ("500", "関連度上位 500 件")]:
    check(f"プルダウンに {label} がある", f'>{label}</option>' in html)
# v06 で初期値を「上位10件（前回の状態があればそれを優先）」に変更した
check("初期選択が上位10件", '<option value="10" selected>' in html)
check("100件が初期選択にならない", '<option value="100" selected>' not in html)

cfg_resp = client.get("/api/config")
check("GET /api/config が200", cfg_resp.status_code == 200)
data = cfg_resp.get_json()
check("既定件数10を返す", data["default_max_results"] == 10, json.dumps(data))
check("機密情報を返さない",
      "tenant_id" not in data and "client_id" not in data, json.dumps(data))

print(f"\n{'=' * 46}\n  成功 {ok} 件 / 失敗 {ng} 件\n{'=' * 46}")
sys.exit(1 if ng else 0)
