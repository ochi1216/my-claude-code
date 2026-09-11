# -*- coding: utf-8 -*-
"""旧版整理・状態保持・絞り込み出力・一括ダウンロード

ネットワークには一切アクセスせず、最新バージョンの本体を読み込んで検証する。
実行: python tests/test_05_state_and_download.py   （まとめて実行する場合は python tests/run_tests.py）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import dsm, DummyAuth  # noqa: E402

import io
import base64
import zipfile
import tempfile
import shutil

ok, ng = 0, 0
def check(label, cond, detail=""):
    global ok, ng
    if cond: ok += 1; print(f"  OK   {label}")
    else:    ng += 1; print(f"  NG   {label}  {detail}")

tmp = Path(tempfile.mkdtemp())

# ── X1 旧バージョンの自動アーカイブ ──────────────────────
print("\n[X1] 旧バージョンの old フォルダへの自動移動")
work = tmp / "tool"; work.mkdir()
for name in ["document_search_manager_20260903_01.py",
             "document_search_manager_20260903_02.py",
             "document_search_manager_20260903_03.py",
             "document_search_manager_20260903_04.py",
             "document_search_manager_20260903_08.py",
             "document_search_manager_20260904_01.py",
             "README.md", "config.json"]:
    (work / name).write_text("x", encoding="utf-8")

orig_base, orig_file = dsm.BASE_DIR, dsm.__file__
dsm.BASE_DIR = work
dsm.__file__ = str(work / "document_search_manager_20260903_08.py")
try:
    dsm._archive_old_versions()
finally:
    pass

remaining = sorted(f.name for f in work.glob("*.py"))
archived = sorted(f.name for f in (work / "old").glob("*.py"))
check("_01〜_03 と _04 が old へ移動",
      archived == ["document_search_manager_20260903_01.py",
                   "document_search_manager_20260903_02.py",
                   "document_search_manager_20260903_03.py",
                   "document_search_manager_20260903_04.py"], str(archived))
check("自分自身は残る", "document_search_manager_20260903_08.py" in remaining, str(remaining))
check("自分より新しい版(翌日分)は動かさない",
      "document_search_manager_20260904_01.py" in remaining, str(remaining))
check("py以外は動かさない", (work / "README.md").exists() and (work / "config.json").exists())

# 同名が old に既にある場合は上書きしない
(work / "document_search_manager_20260903_02.py").write_text("new", encoding="utf-8")
dsm._archive_old_versions()
check("old に同名があれば上書きせず手元も消さない",
      (work / "document_search_manager_20260903_02.py").read_text(encoding="utf-8") == "new"
      and (work / "old" / "document_search_manager_20260903_02.py").read_text(encoding="utf-8") == "x")

dsm.BASE_DIR, dsm.__file__ = orig_base, orig_file

# ── X2 既定件数 ──────────────────────────────────────────
print("\n[X2] 既定の取得件数")
check("DEFAULT_CFG の既定が10件", dsm.DEFAULT_CFG["default_max_results"] == 10,
      str(dsm.DEFAULT_CFG["default_max_results"]))

# ── 共通のセットアップ ───────────────────────────────────
CFG = dict(dsm.DEFAULT_CFG)
state_dir = tmp / "state"; state_dir.mkdir()
dsm.STATE_PATH = state_dir / "session_state.json"
dsm.EXPORT_DIR = state_dir / "exports"
dsm.DOWNLOAD_DIR = state_dir / "downloads"
dsm._cfg = CFG
dsm._auth = DummyAuth()
mgr = dsm.SearchManager(CFG, DummyAuth())

def mk(i, title, author, date, ext, site):
    return dsm.SearchResult(source="SharePoint", title=title, author=author,
                            last_modified=date, doc_type=ext, site=site,
                            site_url="https://x/sites/" + site,
                            url="https://nexperia.sharepoint.com/sites/" + site
                                + "/Docs/" + title + "." + ext, rank=i + 1)
ROWS = [
    mk(0, "Alpha",   "Ochi",  "2026-01-15", "pptx", "JapanTE"),
    mk(1, "Bravo",   "Suzuki","2026-05-20", "xlsm", "JapanTE"),
    mk(2, "Charlie", "Ochi",  "2026-09-02", "pptx", "JapanPE"),
    mk(3, "Delta",   "Tanaka","2026-07-31", "docx", "JapanPE"),
]
mgr.providers[dsm.TARGET_SHAREPOINT].search = lambda kw, mx: {
    "results": list(ROWS), "total": len(ROWS), "note": ""}
dsm._manager = mgr
client = dsm.flask_app.test_client()
client.post("/api/search", json={"keyword": "validation", "target": "sharepoint"})

# ── X3 状態の保存と復元 ──────────────────────────────────
print("\n[X3] 検索状態・ソート・フィルタの保存と復元")
r = client.get("/api/state")
check("保存前は空を返す", r.status_code == 200 and r.get_json() == {}, str(r.get_json()))

state = {"keyword": "validation", "target": "sharepoint", "max_results": 25,
         "sort": {"key": "last_modified", "dir": -1},
         "filters": {"doc_type": {"values": ["pptx", "xlsm"]},
                     "last_modified": {"from": "2026-05-01", "to": ""}}}
r = client.post("/api/state", json=state)
check("保存できる", r.get_json().get("saved") is True, str(r.get_json()))
check("session_state.json が作られる", dsm.STATE_PATH.exists())

got = client.get("/api/state").get_json()
check("キーワードを復元", got["keyword"] == "validation", got.get("keyword"))
check("検索対象を復元", got["target"] == "sharepoint", got.get("target"))
check("件数を復元", got["max_results"] == 25, str(got.get("max_results")))
check("降順ソートを復元", got["sort"] == {"key": "last_modified", "dir": -1}, str(got.get("sort")))
check("種別の複数選択フィルタを復元",
      got["filters"]["doc_type"]["values"] == ["pptx", "xlsm"], str(got.get("filters")))
check("日付範囲フィルタを復元",
      got["filters"]["last_modified"]["from"] == "2026-05-01", str(got.get("filters")))
check("保存日時が記録される", "saved_at" in got)

dsm._cfg = dict(CFG, restore_last_search=False)
check("restore_last_search=false なら復元しない", client.get("/api/state").get_json() == {})
dsm._cfg = CFG

# ── X4 絞り込み後の行だけを出力 ──────────────────────────
print("\n[X4] 画面の絞り込み・並び順を反映した出力")
csv_all = client.get("/api/export?format=csv").get_data(as_text=True)
check("idx無しなら全件出力", all(n in csv_all for n in ["Alpha", "Bravo", "Charlie", "Delta"]))

csv_sel = client.get("/api/export?format=csv&idx=2,0").get_data(as_text=True)
check("選択した行だけ出力", "Charlie" in csv_sel and "Alpha" in csv_sel
      and "Bravo" not in csv_sel and "Delta" not in csv_sel)
lines = [l for l in csv_sel.splitlines() if l.strip()]
check("画面の並び順を保つ（Charlieが先）",
      lines[1].find("Charlie") >= 0 and lines[2].find("Alpha") >= 0, str(lines[1:3]))
check("範囲外・不正な索引は無視する",
      "Alpha" in client.get("/api/export?format=csv&idx=0,999,abc,-1").get_data(as_text=True))

# ── X5 一括ダウンロード（ZIP） ───────────────────────────
print("\n[X5] 選択ファイルの一括ZIPダウンロード")
check("共有トークンがu!形式", dsm._share_token("https://x/a.docx").startswith("u!"))
check("共有トークンにパディングが残らない", "=" not in dsm._share_token("https://x/a.docx"))
decoded = base64.urlsafe_b64decode(
    dsm._share_token("https://x/a.docx")[2:] + "==").decode()
check("共有トークンを復号すると元のURL", decoded == "https://x/a.docx", decoded)

class FakeResp:
    def __init__(self, code, content=b""):
        self.status_code = code; self.content = content
calls = []
def fake_get(url, headers=None, timeout=None, allow_redirects=None):
    calls.append(url)
    if "Bravo" in base64.urlsafe_b64decode(
            url.split("/shares/")[1].split("/")[0][2:] + "==").decode():
        return FakeResp(403)
    return FakeResp(200, b"dummy-content")

orig_get = dsm.http_req.get
dsm.http_req.get = fake_get
try:
    resp = client.get("/api/download?idx=0,1,2")
    check("ZIPが返る", resp.status_code == 200, str(resp.status_code))
    zf = zipfile.ZipFile(io.BytesIO(resp.get_data()))
    names = sorted(zf.namelist())
    check("成功した2件が入る", "Alpha.pptx" in names and "Charlie.pptx" in names, str(names))
    check("失敗した1件は入らない", "Bravo.xlsm" not in names, str(names))
    check("失敗一覧が同梱される", "_ダウンロード失敗一覧.txt" in names, str(names))
    note = zf.read("_ダウンロード失敗一覧.txt").decode("utf-8")
    check("失敗一覧に理由が書かれる", "Bravo" in note and "403" in note, note[:120])

    resp = client.get("/api/download")
    check("選択なしは400", resp.status_code == 400, str(resp.status_code))

    dsm._cfg = dict(CFG, max_download_files=2)
    resp = client.get("/api/download?idx=0,2,3")
    zf = zipfile.ZipFile(io.BytesIO(resp.get_data()))
    note = zf.read("_ダウンロード失敗一覧.txt").decode("utf-8")
    check("上限を超えた分は対象外として記録", "上限" in note and "Delta" in note, note[:200])
    dsm._cfg = CFG

    dsm.http_req.get = lambda *a, **k: FakeResp(403)
    resp = client.get("/api/download?idx=0,2")
    check("全件失敗なら502とエラー説明", resp.status_code == 502
          and "権限" in resp.get_json()["error"], str(resp.status_code))
finally:
    dsm.http_req.get = orig_get

# ── X6 画面の要素 ────────────────────────────────────────
print("\n[X6] 画面の要素")
html = client.get("/").get_data(as_text=True)
for token, label in [
    ('key: "__select"', "選択列の定義"),
    ('type: "date"', "最終更新日の日付範囲フィルタ"),
    ('buildSetPanel', "複数選択フィルタ"),
    ('toggleSort', "昇順・降順ソート"),
    ('btnDownload', "一括ダウンロードボタン"),
    ('btnClearFilter', "フィルタ・ソート解除ボタン"),
    ('saveState', "状態の保存"),
    ('restoreState', "状態の復元"),
    ('"以降"', "日付フィルタの「以降」"),
    ('"以前"', "日付フィルタの「以前」"),
]:
    check(label + " がある", token in html)

print(f"\n{'=' * 46}\n  成功 {ok} 件 / 失敗 {ng} 件\n{'=' * 46}")
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(1 if ng else 0)
