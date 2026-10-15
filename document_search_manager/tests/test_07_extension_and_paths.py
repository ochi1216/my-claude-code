# -*- coding: utf-8 -*-
"""拡張子判定・URLデコード・フォルダ表示の短縮

ネットワークには一切アクセスせず、最新バージョンの本体を読み込んで検証する。
実行: python tests/test_07_extension_and_paths.py   （まとめて実行する場合は python tests/run_tests.py）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import dsm, DummyAuth  # noqa: E402

import tempfile

ok, ng = 0, 0
def check(label, cond, detail=""):
    global ok, ng
    if cond: ok += 1; print(f"  OK   {label}")
    else:    ng += 1; print(f"  NG   {label}  {detail}")

CFG = dict(dsm.DEFAULT_CFG)
p = dsm.SharePointProvider(CFG, auth=None)

print("\n[Z1] 拡張子判定の厳格化（越智さんの環境の実データ）")
cases = [
    ("R19 Validation Report.pptx", "pptx", "通常のファイル"),
    ("PCP gate Checklist V2.xlsm", "xlsm", "通常のファイル"),
    ("12. Validation", "", "番号付きフォルダ（従来は「 validation」を拡張子と誤認）"),
    ("12.%20Validation", "", "URLエンコードが残った番号付きフォルダ"),
    ("40. Bench Validation", "", "番号付きフォルダ"),
    ("MRA2.0", "", "バージョン付きフォルダ（従来は「0」を拡張子と誤認）"),
    ("01. Validation_Plan", "", "番号付きフォルダ"),
    ("archive.7z", "7z", "数字始まりだが実在する拡張子"),
    ("README", "", "拡張子なし"),
    ("a.verylongextension", "", "10文字を超えるものは拡張子とみなさない"),
]
for name, want, note in cases:
    got = dsm._extension_of(name)
    check(f"{note}: {name} → {want or '(なし)'}", got == want, f"実際={got}")

print("\n[Z2] %20 のデコード")
check("%20 を空白に戻す", dsm._decode_name("12.%20Validation") == "12. Validation")
check("%が無ければそのまま", dsm._decode_name("12. Validation") == "12. Validation")
check("日本語のエンコードも復号", dsm._decode_name("%E6%A4%9C%E8%A8%BC.docx") == "検証.docx")

print("\n[Z3] フォルダ判定（拡張子判定と連動）")
BASE = "https://nexperia.sharepoint.com/sites/NEX402xxA/Shared%20Documents/"
check("「12. Validation」はフォルダと判定",
      dsm._looks_like_folder(BASE + "12.%20Validation", {}) is True)
check("「MRA2.0」はフォルダと判定",
      dsm._looks_like_folder(BASE + "40.%20Bench%20Validation/MRA2.0", {}) is True)
check("「a.pptx」はファイルと判定", dsm._looks_like_folder(BASE + "a.pptx", {}) is False)

print("\n[Z4] フォルダ表示の短縮（ルートを / で表す）")
cases2 = [
    ("Shared Documents", "/", "ライブラリ直下"),
    ("Shared Documents/40. Bench Validation", "/40. Bench Validation", "1階層下"),
    ("Shared Documents/40. Bench Validation/43. Validation Results/MRA2p3",
     "/40. Bench Validation/43. Validation Results/MRA2p3", "深い階層"),
    ("Documents", "/", "既定ライブラリ(Documents)"),
    ("共有ドキュメント/検証", "/検証", "日本語の既定ライブラリ"),
    ("PO/2026/Vendor", "PO/2026/Vendor", "固有ライブラリ名は残す"),
    ("Templates", "Templates", "固有ライブラリ名は残す"),
    ("", "", "空"),
]
for full, want, note in cases2:
    got = dsm._shorten_folder(full)
    check(f"{note}: {full or '(空)'} → {want or '(空)'}", got == want, f"実際={got}")

print("\n[Z5] 検索結果への反映")
hit = {"resource": {"webUrl": BASE + "40.%20Bench%20Validation/01.%20Validation_Plan/a.pptx",
                    "lastModifiedDateTime": "2026-08-21T00:00:00Z"}}
r = p._hit_to_result(hit, 1)
check("表示は短縮パス", r.folder == "/40. Bench Validation/01. Validation_Plan", r.folder)
check("フルパスも保持",
      r.folder_full == "Shared Documents/40. Bench Validation/01. Validation_Plan",
      r.folder_full)
check("リンクはフルパスで組み立てる",
      "%2FShared%20Documents%2F40.%20Bench%20Validation" in r.folder_url, r.folder_url)
check("種別は pptx", r.doc_type == "pptx", r.doc_type)

hit_f = {"resource": {"webUrl": BASE + "12.%20Validation",
                      "lastModifiedDateTime": "2026-07-31T00:00:00Z"}}
rf = p._hit_to_result(hit_f, 2)
check("「12. Validation」の種別が「フォルダ」", rf.doc_type == "フォルダ", rf.doc_type)
check("「12. Validation」のタイトルが復号される", rf.title == "12. Validation", rf.title)
check("「12. Validation」のフォルダ列は / （ライブラリ直下）", rf.folder == "/", rf.folder)

print("\n[Z6] OneDrive（/personal/）への対応")
od = ("https://nexperia-my.sharepoint.com/personal/yuto_oi_nexperia_com/"
      "Documents/Validation_plan_v0p1.pptx")
ro = p._hit_to_result({"resource": {"webUrl": od}}, 3)
check("サイトURLが個人サイトになる",
      ro.site_url == "https://nexperia-my.sharepoint.com/personal/yuto_oi_nexperia_com",
      ro.site_url)
check("フォルダ列が空でなくなる（/ になる）", ro.folder == "/", f"[{ro.folder}]")
check("フォルダリンクが生成される", ro.folder_url.startswith("https://nexperia-my"), ro.folder_url)

print("\n[Z7] 画面と出力")
SD = Path(tempfile.mkdtemp())
dsm.STATE_PATH = SD / "s.json"; dsm.EXPORT_DIR = SD / "e"; dsm.DOWNLOAD_DIR = SD / "d"
dsm._cfg = CFG; dsm._auth = DummyAuth()
mgr = dsm.SearchManager(CFG, DummyAuth())
mgr.providers[dsm.TARGET_SHAREPOINT].search = lambda kw, mx: {
    "results": [r, rf, ro], "total": 3, "note": ""}
dsm._manager = mgr
client = dsm.flask_app.test_client()
html = client.get("/").get_data(as_text=True)
check("ツールチップにフルパスを出す", "r.folder_full || r.folder" in html)

data = client.post("/api/search", json={"keyword": "v", "target": "sharepoint"}).get_json()
check("APIが folder_full を返す", "folder_full" in data["results"][0])

csv_body = client.get("/api/export?format=csv").get_data(as_text=True)
check("CSVにはフルパスを出力（データの正確性を優先）",
      "Shared Documents/40. Bench Validation/01. Validation_Plan" in csv_body)

print(f"\n{'=' * 46}\n  成功 {ok} 件 / 失敗 {ng} 件\n{'=' * 46}")
sys.exit(1 if ng else 0)
