# -*- coding: utf-8 -*-
"""サイトURLの導出とリンク配置

ネットワークには一切アクセスせず、最新バージョンの本体を読み込んで検証する。
実行: python tests/test_04_site_links.py   （まとめて実行する場合は python tests/run_tests.py）
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
p = dsm.SharePointProvider(CFG, auth=None)

print("\n[W1] 文書URL → サイトURLの導出")
cases = [
    ("https://nexperia.sharepoint.com/sites/JapanTE/Shared%20Documents/a.pptx",
     "https://nexperia.sharepoint.com/sites/JapanTE"),
    ("https://nexperia.sharepoint.com/sites/SF_QualityDocumentsProd/Documents/x/y/z.pdf",
     "https://nexperia.sharepoint.com/sites/SF_QualityDocumentsProd"),
    ("https://nexperia.sharepoint.com/teams/R19/Docs/a.docx",
     "https://nexperia.sharepoint.com/teams/R19"),
    # v07 で OneDrive の /personal/<user> も1つのサイトとして扱うようにした
    ("https://nexperia-my.sharepoint.com/personal/user/Documents/a.docx",
     "https://nexperia-my.sharepoint.com/personal/user"),
    ("", ""),
    ("not a url", ""),
]
for url, want in cases:
    got = dsm._site_url_from_url(url)
    check(f"{(url[:52] or '(空)')} → {want or '(空)'}", got == want, got)

print("\n[W2] サイト名の表示")
check("サイトURLから名前を取り出す",
      dsm._site_name_from_url("https://nexperia.sharepoint.com/sites/JapanTE") == "JapanTE")
check("ホストのみの場合はホスト名",
      dsm._site_name_from_url("https://nexperia-my.sharepoint.com") == "nexperia-my.sharepoint.com")

print("\n[W3] 検索結果へのサイト情報の反映")
hit = {"resource": {
    "webUrl": "https://nexperia.sharepoint.com/sites/JapanTE/Shared%20Documents/"
              "R19%20Validation%20Report.pptx",
    "lastModifiedDateTime": "2026-09-02T01:00:00Z",
    "createdBy": {"user": {"displayName": "Takahiro Miyazaki"}}}}
r = p._hit_to_result(hit, 1)
check("site_url を持つ", r.site_url == "https://nexperia.sharepoint.com/sites/JapanTE",
      r.site_url)
check("site 表示名は JapanTE", r.site == "JapanTE", r.site)
check("ファイルURLはそのまま保持", r.url.endswith("R19%20Validation%20Report.pptx"), r.url)

hit_f = {"resource": {"webUrl": "https://nexperia.sharepoint.com/sites/A/Docs/a.docx",
                      "fields": {"title": "検証手順書", "siteTitle": "Japan Design Center",
                                 "spSiteURL": "https://nexperia.sharepoint.com/sites/JapanDesign"}}}
r = p._hit_to_result(hit_f, 1)
check("fields.siteTitle を優先して表示", r.site == "Japan Design Center", r.site)
check("fields.spSiteURL を優先してリンク",
      r.site_url == "https://nexperia.sharepoint.com/sites/JapanDesign", r.site_url)

print("\n[W4] MCAS書き換えはサイトリンクにも適用される")
p2 = dsm.SharePointProvider(dict(CFG, rewrite_host_to_mcas=True), auth=None)
r = p2._hit_to_result(hit, 1)
check("ファイルURLを書き換える", ".mcas.ms" in r.url, r.url)
check("サイトURLも書き換える", ".mcas.ms" in r.site_url, r.site_url)

print("\n[W5] 画面のリンク配置")
dsm._cfg = dict(CFG, default_max_results=10)
mgr = dsm.SearchManager(dsm._cfg, DummyAuth())
mgr.providers[dsm.TARGET_SHAREPOINT].search = lambda kw, mx: {
    "results": [p._hit_to_result(hit, 1)], "total": 1, "note": ""}
dsm._manager = mgr
client = dsm.flask_app.test_client()

html = client.get("/").get_data(as_text=True)
# v05でテーブル描画を列駆動(COLUMNS + buildCell)に変更したため、検証点を合わせる
check("列定義に「サイト」がある", 'label: "サイト"' in html)
check("列定義に「リンク」列が無い", 'label: "リンク"' not in html)
check("タイトルセルにリンクを張る処理がある",
      'aFile.href = r.url' in html and 'td.appendChild(aFile)' in html)
check("サイトセルにリンクを張る処理がある",
      'aSite.href = r.site_url' in html and 'td.appendChild(aSite)' in html)
check("日付列の折り返し防止CSSがある", "td.nowrap { white-space: nowrap; }" in html)

data = client.post("/api/search",
                   json={"keyword": "validation", "target": "sharepoint"}).get_json()
row = data["results"][0]
check("APIレスポンスに site_url が含まれる", "site_url" in row, json.dumps(row)[:200])
check("site_url が正しい", row["site_url"] == "https://nexperia.sharepoint.com/sites/JapanTE",
      row["site_url"])

print("\n[W6] エクスポート列の追加")
csv_body = client.get("/api/export?format=csv").get_data(as_text=True)
check("CSVに「ファイルリンク」列がある", "ファイルリンク" in csv_body)
check("CSVに「サイトリンク」列がある", "サイトリンク" in csv_body)
check("CSVにサイトURLの値が入る", "https://nexperia.sharepoint.com/sites/JapanTE" in csv_body)
check("Excel出力も200", client.get("/api/export?format=xlsx").status_code == 200)

print(f"\n{'=' * 46}\n  成功 {ok} 件 / 失敗 {ng} 件\n{'=' * 46}")
sys.exit(1 if ng else 0)
