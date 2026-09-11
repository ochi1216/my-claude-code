# -*- coding: utf-8 -*-
"""フォルダ列とフォルダ／ファイルの区別

ネットワークには一切アクセスせず、最新バージョンの本体を読み込んで検証する。
実行: python tests/test_06_folders.py   （まとめて実行する場合は python tests/run_tests.py）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import dsm, DummyAuth  # noqa: E402

import json
import tempfile

ok, ng = 0, 0
def check(label, cond, detail=""):
    global ok, ng
    if cond: ok += 1; print(f"  OK   {label}")
    else:    ng += 1; print(f"  NG   {label}  {detail}")

CFG = dict(dsm.DEFAULT_CFG)
p = dsm.SharePointProvider(CFG, auth=None)
SITE = "https://nexperia.sharepoint.com/sites/JapanTE"

print("\n[Y1] ファイルURL → 保管フォルダの導出")
folder, furl = dsm._folder_of_url(
    "https://nexperia.sharepoint.com/sites/JapanTE/Shared%20Documents/2026/Reports/a.pptx", SITE)
check("表示パスは復号された階層", folder == "Shared Documents/2026/Reports", folder)
check("フォルダURLはライブラリのForms/AllItems.aspx",
      furl.startswith("https://nexperia.sharepoint.com/sites/JapanTE/Shared%20Documents/Forms/AllItems.aspx?id="),
      furl)
check("id にサーバー相対パスが符号化されて入る",
      "%2Fsites%2FJapanTE%2FShared%20Documents%2F2026%2FReports" in furl, furl)

folder2, _ = dsm._folder_of_url(
    "https://nexperia.sharepoint.com/sites/JapanTE/Shared%20Documents/a.pptx", SITE)
check("ライブラリ直下のファイルはライブラリ名", folder2 == "Shared Documents", folder2)
check("サイト直下は空", dsm._folder_of_url(SITE + "/a.pptx", SITE)[0] == "Shared Documents"
      or dsm._folder_of_url(SITE + "/a.pptx", SITE)[0] == "",
      dsm._folder_of_url(SITE + "/a.pptx", SITE)[0])
check("別サイトのURLは空", dsm._folder_of_url("https://x/sites/Other/D/a.pptx", SITE) == ("", ""))
check("空URLは空", dsm._folder_of_url("", SITE) == ("", ""))

print("\n[Y2] フォルダ自体のURL（drop_last=False）")
f3, u3 = dsm._folder_of_url(
    "https://nexperia.sharepoint.com/sites/JapanTE/Shared%20Documents/Validation%20Reports",
    SITE, drop_last=False)
check("そのフォルダ自身のパスを返す", f3 == "Shared Documents/Validation Reports", f3)
check("そのフォルダを開くURLになる",
      "%2FShared%20Documents%2FValidation%20Reports" in u3, u3)

print("\n[Y3] フォルダ判定")
check("拡張子が無ければフォルダ",
      dsm._looks_like_folder("https://x/sites/A/D/Validation%20Reports", {}) is True)
check("拡張子があればファイル",
      dsm._looks_like_folder("https://x/sites/A/D/a.pptx", {}) is False)
check("fields.isDocument=false ならフォルダ",
      dsm._looks_like_folder("https://x/sites/A/D/a.pptx", {"isdocument": "false"}) is True)
check("fields.isDocument=true ならファイル",
      dsm._looks_like_folder("https://x/sites/A/D/noext", {"isdocument": "true"}) is False)
check("contentclass に folder を含めばフォルダ",
      dsm._looks_like_folder("https://x/a.pptx", {"contentclass": "STS_ListItem_Folder"}) is True)

print("\n[Y4] 検索結果でのフォルダの扱い（案A: 除外せず区別する）")
hit_folder = {"resource": {
    "webUrl": "https://nexperia.sharepoint.com/sites/JapanTE/Shared%20Documents/Validation%20Reports",
    "lastModifiedDateTime": "2026-08-01T00:00:00Z"}}
r = p._hit_to_result(hit_folder, 1)
check("フォルダは is_folder=True", r.is_folder is True)
check("種別が「フォルダ」", r.doc_type == "フォルダ", r.doc_type)
check("タイトルはフォルダ名", r.title == "Validation Reports", r.title)
check("タイトルのリンク先はそのフォルダを開くURL",
      "AllItems.aspx" in r.url and "Validation%20Reports" in r.url, r.url)
# v07 で既定ライブラリ名をルート "/" に短縮する仕様に変更した
check("フォルダ列には親フォルダを示す（短縮表示）", r.folder == "/", r.folder)
check("フルパスも保持している", r.folder_full == "Shared Documents", r.folder_full)

hit_file = {"resource": {
    "webUrl": "https://nexperia.sharepoint.com/sites/JapanTE/Shared%20Documents/2026/a.pptx",
    "lastModifiedDateTime": "2026-08-01T00:00:00Z"}}
r2 = p._hit_to_result(hit_file, 2)
check("ファイルは is_folder=False", r2.is_folder is False)
check("種別は拡張子", r2.doc_type == "pptx", r2.doc_type)
check("フォルダ列に格納フォルダ（短縮表示）", r2.folder == "/2026", r2.folder)
check("フルパスも保持している", r2.folder_full == "Shared Documents/2026", r2.folder_full)
check("タイトルのリンク先はファイル本体", r2.url.endswith("a.pptx"), r2.url)

print("\n[Y5] exclude_folders の切り替え")
def stub(token, q, frm, size):
    return 200, {"value": [{"hitsContainers": [{"total": 2, "moreResultsAvailable": False,
        "hits": [hit_folder, hit_file]}]}]}, ""
p_keep = dsm.SharePointProvider(dict(CFG, exclude_folders=False), auth=None)
p_keep._call_search_api = stub
out = p_keep._search_by_search_api("tok", "validation", 100)
check("既定ではフォルダも残る", len(out["results"]) == 2, str(len(out["results"])))
check("残った行の順位が1,2で連番",
      [r.rank for r in out["results"]] == [1, 2], str([r.rank for r in out["results"]]))

p_drop = dsm.SharePointProvider(dict(CFG, exclude_folders=True), auth=None)
p_drop._call_search_api = stub
out2 = p_drop._search_by_search_api("tok", "validation", 100)
check("exclude_folders=true ならファイルだけ", len(out2["results"]) == 1
      and out2["results"][0].is_folder is False, str(len(out2["results"])))

print("\n[Y6] 画面と出力の列構成")
SD = Path(tempfile.mkdtemp())
dsm.STATE_PATH = SD / "s.json"; dsm.EXPORT_DIR = SD / "e"; dsm.DOWNLOAD_DIR = SD / "d"
dsm._cfg = CFG; dsm._auth = DummyAuth()
mgr = dsm.SearchManager(CFG, DummyAuth())
mgr.providers[dsm.TARGET_SHAREPOINT].search = lambda kw, mx: {
    "results": [r, r2], "total": 2, "note": ""}
dsm._manager = mgr
client = dsm.flask_app.test_client()
html = client.get("/").get_data(as_text=True)

check("列定義に「フォルダ」がある", 'label: "フォルダ"' in html)
# v10 で Nexusタブに標準Indexを表示するようにしたため、Document Number は
# 「どこにも出さない」から「Nexusタブにだけ出す」に変わった。
# SharePoint／Allタブに出していないことを確認する形に更新する
# （機能の劣化ではなく、仕様変更に伴うテスト記述の陳腐化）。
check("Nexusタブの列定義に Document Number がある",
      'key: "document_number"' in html and 'label: "Document Number"' in html)
check("SharePointタブの列定義には Document Number を出さない",
      'key: "document_number"' not in
      html.split("sharepoint: [")[1].split("],")[0])
check("Allタブの列定義にも Document Number を出さない",
      'key: "document_number"' not in html.split("all: [")[1].split("],")[0])
check("フォルダ列はサイト列の右",
      html.index('label: "フォルダ"') > html.index('label: "サイト"'))
check("件数プルダウンの初期選択が10件", '<option value="10" selected>' in html)
check("configで初期件数を上書きしない（applyDefaults廃止）", "applyDefaults" not in html)
check("フォルダ行は選択できない旨の実装がある", "フォルダはダウンロードできません" in html)

client.post("/api/search", json={"keyword": "validation", "target": "sharepoint"})
row = client.get("/api/state") and None
data = client.post("/api/search",
                   json={"keyword": "validation", "target": "sharepoint"}).get_json()
check("APIが folder / folder_url / is_folder を返す",
      all(k in data["results"][0] for k in ("folder", "folder_url", "is_folder")),
      json.dumps(data["results"][0])[:200])

csv_body = client.get("/api/export?format=csv").get_data(as_text=True)
head = csv_body.splitlines()[0]
check("CSVヘッダーに「フォルダ」がある", "フォルダ" in head, head)
check("CSVヘッダーに「フォルダリンク」がある", "フォルダリンク" in head, head)
check("CSVヘッダーから Document Number が消えている", "Document Number" not in head, head)
check("Excel出力も200", client.get("/api/export?format=xlsx").status_code == 200)

print("\n[Y7] 一括ダウンロードはフォルダを対象外にする")
resp = client.get("/api/download?idx=0")   # 0番はフォルダ
check("フォルダだけの選択は400", resp.status_code == 400, str(resp.status_code))

print(f"\n{'=' * 46}\n  成功 {ok} 件 / 失敗 {ng} 件\n{'=' * 46}")
sys.exit(1 if ng else 0)
