# -*- coding: utf-8 -*-
"""ブラウザ操作テスト（Playwright）

ダミーデータで画面を起動し、ソート・絞り込み・選択・状態復元を実際に操作して
確認する。Graph API には一切アクセスしない。

    pip install playwright
    playwright install chromium
    python tests/ui_check.py [--headed] [--shot 出力先.png]

Playwright が入っていない環境ではスキップ扱いで終了する（合格扱い）。
ブラウザの実行ファイルを指定したい場合は環境変数 CHROMIUM_PATH を設定する。
"""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import dsm, DummyAuth, DSM_FILENAME  # noqa: E402

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:
    print("⚠️  Playwright が未インストールのため、ブラウザ操作テストをスキップします。")
    print("    実行する場合: pip install playwright && playwright install chromium")
    print("  成功 0 件 / 失敗 0 件")
    sys.exit(0)

PORT = 5099
WORK = Path(tempfile.mkdtemp())

# 越智さんの環境に近い階層構成のダミーデータ
# （サイト, サイト内パス, 作成者, 最終更新日時）
SAMPLE = [
    ("P020015_Caracal", "Shared%20Documents/40.%20Bench%20Validation/41.%20Hardware/"
     "Engineering%20and%20Validation%20Evaluation%20Board", "Bogdan Duduman",
     "2026-04-14T04:00:00Z"),
    ("P020009_Wheeling", "Shared%20Documents/40.%20Bench%20Validation/"
     "01.%20Validation_Plan/PCP%20gate%20Checklist%20V2.xlsm",
     "Bogdan Duduman;Yuto Oi", "2026-08-21T05:00:00Z"),
    ("P020015_Caracal", "Shared%20Documents/40.%20Bench%20Validation/"
     "01.%20Validation_Plan/MRA2.0/%5B40VB%5D%20LDO.pptx",
     "Jake Smith;Takahiro Miyazaki", "2026-09-02T01:00:00Z"),
    ("NEX402xxA", "Shared%20Documents/12.%20Validation", "Jennifer Mitchell",
     "2026-07-31T02:00:00Z"),
    ("P040029%20-%20Grand%20Teton", "Shared%20Documents/40.%20Bench%20Validation/"
     "43.%20Validation%20Results/Desgin_Initial_Validation_JPN", "Kenichi Hirooka",
     "2026-06-01T02:00:00Z"),
    ("P020009_Wheeling", "Shared%20Documents/40.%20Bench%20Validation/"
     "43.%20Validation%20Results/MRA2p3/Nexperia%20corporate%20template.pptx",
     "Petra Beekmans - van Zijll;Yuto Oi", "2026-08-21T06:00:00Z"),
]

ok, ng = 0, 0


def check(label, condition, detail=""):
    global ok, ng
    if condition:
        ok += 1
        print(f"  OK   {label}")
    else:
        ng += 1
        print(f"  NG   {label}  {detail}")


def start_server():
    cfg = dict(dsm.DEFAULT_CFG, auto_open_browser=False, default_max_results=10)
    dsm.STATE_PATH = WORK / "session_state.json"
    dsm.EXPORT_DIR = WORK / "exports"
    dsm.DOWNLOAD_DIR = WORK / "downloads"
    dsm._cfg = cfg
    dsm._auth = DummyAuth()

    provider = dsm.SharePointProvider(cfg, auth=None)

    def fake_search(keyword, max_results):
        results = []
        for index, (site, path, author, stamp) in enumerate(SAMPLE):
            hit = {"resource": {
                "webUrl": f"https://nexperia.sharepoint.com/sites/{site}/{path}",
                "lastModifiedDateTime": stamp,
                "createdBy": {"user": {"displayName": author}}}}
            results.append(provider._hit_to_result(hit, index + 1))
        return {"results": results, "total": len(results), "note": ""}

    manager = dsm.SearchManager(cfg, DummyAuth())
    manager.providers[dsm.TARGET_SHAREPOINT].search = fake_search
    # v09 で Nexus が実装済みになったため、こちらもスタブ化する。
    # そうしないと 0.All の検索で実際に Graph を呼びに行ってしまい、
    # 会社PCでは本物のNexusの結果がダミーデータに混ざって件数が合わなくなる。
    nexus_rows = [
        dsm.SearchResult(
            source="Nexus", document_number="NDS-00688", old_system_id="XPR-0367",
            title="Customer Programs Testing", doc_author="David Chen",
            doc_owner="Rob Geljon", applicable_to="Global Supply Chain",
            department="Global Supply Chain", last_modified="2026-03-19",
            doc_type="docx", url="https://nexperia.sharepoint.com/sites/"
            "SF_QualityDocumentsProd/Documents/3E08-CD5F/a.docx",
            nexus_url="https://nexperia.sharepoint.com/x/View.aspx?q=NDS-00688",
            valid_until="2020-01-31", expiry_state="expired",
            doc_status="Expired", doc_status_en="Valid",
            is_nexus_path=True, rank=1),
        dsm.SearchResult(
            source="Nexus", document_number="NDS-00213", old_system_id="XTE-0061",
            title="Basic and Product Type Request Form", doc_author="Vince Reyes",
            doc_owner="Marc Albers", applicable_to="Global Supply Chain",
            department="Global Supply Chain", last_modified="2025-09-15",
            doc_type="pdf", url="https://nexperia.sharepoint.com/sites/"
            "SF_QualityDocumentsProd/Documents/801F-6853/b.pdf",
            nexus_url="https://nexperia.sharepoint.com/x/View.aspx?q=NDS-00213",
            valid_until="2099-12-31", expiry_state="valid",
            is_nexus_path=True, rank=2),
    ]
    manager.providers[dsm.TARGET_NEXUS].search = (
        lambda keyword, max_results: {"results": list(nexus_rows),
                                      "total": len(nexus_rows), "note": ""})
    dsm._manager = manager

    threading.Thread(
        target=lambda: dsm.flask_app.run(host="127.0.0.1", port=PORT,
                                         debug=False, use_reloader=False),
        daemon=True).start()
    time.sleep(2)


def main():
    print(f"🧪 ブラウザ操作テスト（対象: {DSM_FILENAME}）")
    start_server()

    headed = "--headed" in sys.argv
    shot_path = None
    if "--shot" in sys.argv:
        shot_path = sys.argv[sys.argv.index("--shot") + 1]

    launch_args = {"headless": not headed}
    executable = os.environ.get("CHROMIUM_PATH")
    if executable:
        launch_args["executable_path"] = executable

    with sync_playwright() as pw:
        browser = pw.chromium.launch(**launch_args)
        page = browser.new_page(viewport={"width": 1500, "height": 900})
        page.goto(f"http://127.0.0.1:{PORT}/")

        def titles():
            return page.eval_on_selector_all("#resultBody tr td.title",
                                             "e => e.map(x => x.innerText)")

        page.fill("#keyword", "validation")
        page.click("#btnSearch")
        page.wait_for_timeout(900)

        # v10: 0.All は SharePoint と Nexus の両方を並べる
        check("検索結果が表示される", len(titles()) == len(SAMPLE) + 2, str(len(titles())))

        headers = page.eval_on_selector_all("#resultHead th",
                                            "e => e.map(x => x.innerText.trim())")
        # v10: Allタブからフォルダ列を外した。Nexusのフォルダ名は内部ハッシュで、
        # SharePointと同じ列に並べても意味を成さないため（仕様変更）。
        check("Allタブの列構成（ソース/タイトル/選択/作成者/最終更新日/種別/サイト）",
              len(headers) == 7 and headers[1].startswith("タイトル")
              and headers[6].startswith("サイト"), str(headers))
        check("Allタブにフォルダ列は出さない",
              not any(h.startswith("フォルダ") for h in headers), str(headers))

        types = page.eval_on_selector_all("#resultBody tr td:nth-child(6)",
                                          "e => e.map(x => x.innerText)")
        check("種別に %20 等の壊れた値が無い",
              all("%" not in t for t in types), str(types))
        check("フォルダ行が「フォルダ」と表示される", "フォルダ" in types, str(types))

        # ── SharePointタブへ切り替える（列構成が変わることの確認） ──
        page.click("#tabs button[data-target='sharepoint']")
        page.wait_for_timeout(900)
        sp_headers = page.eval_on_selector_all("#resultHead th",
                                               "e => e.map(x => x.innerText.trim())")
        check("SharePointタブに切り替えるとフォルダ列が出る",
              any(h.startswith("フォルダ") for h in sp_headers), str(sp_headers))
        check("SharePointタブにはソース列を出さない",
              not any(h.startswith("ソース") for h in sp_headers), str(sp_headers))
        folder_index = [i for i, h in enumerate(sp_headers)
                        if h.startswith("フォルダ")][0] + 1
        folders = page.eval_on_selector_all(
            f"#resultBody tr td:nth-child({folder_index})",
            "e => e.map(x => x.innerText)")
        check("フォルダ列に値がある", any(f for f in folders), str(folders))
        check("フォルダ列が / 始まりに短縮される",
              all(f.startswith("/") for f in folders if f), str(folders))

        # ── Nexusタブへ切り替える（標準Indexが出ることの確認） ──
        page.click("#tabs button[data-target='nexus']")
        page.wait_for_timeout(900)
        nx_headers = page.eval_on_selector_all("#resultHead th",
                                               "e => e.map(x => x.innerText.trim())")
        for label in ("Document Number", "OldSystemIdentifier", "Document Title",
                      "Doc Author", "Doc Owner", "Applicable To", "Department",
                      "有効期限", "Nexusで開く"):
            check(f"Nexusタブに {label} 列がある",
                  any(h.startswith(label) for h in nx_headers), str(nx_headers))
        check("Nexusタブにフォルダ列を出さない",
              not any(h.startswith("フォルダ") for h in nx_headers), str(nx_headers))
        # 1列目は選択欄。Document Number は2列目（Nexus画面と同じ並び）
        numbers = page.eval_on_selector_all("#resultBody tr td:nth-child(2)",
                                            "e => e.map(x => x.innerText)")
        check("Document Number の値が並ぶ", numbers == ["NDS-00688", "NDS-00213"],
              str(numbers))
        nexus_links = page.eval_on_selector_all(
            "#resultBody tr td a[href*='View.aspx']", "e => e.map(x => x.href)")
        check("Nexusで開くリンクが張られる", len(nexus_links) == 2, str(nexus_links))

        # 有効期限の列とバッジ
        expiry_index = [i for i, h in enumerate(nx_headers)
                        if h.startswith("有効期限")][0] + 1
        expiries = page.eval_on_selector_all(
            f"#resultBody tr td:nth-child({expiry_index})",
            "e => e.map(x => x.innerText)")
        check("有効期限の日付が並ぶ",
              expiries[0].startswith("2020-01-31")
              and expiries[1].startswith("2099-12-31"), str(expiries))
        check("期限切れの行にバッジが出る", "期限切れ" in expiries[0], str(expiries))
        check("期限内の行にはバッジを出さない",
              "期限切れ" not in expiries[1] and "まもなく" not in expiries[1],
              str(expiries))
        badges = page.eval_on_selector_all("#resultBody .badge.expired",
                                           "e => e.length")
        check("期限切れのバッジは1件だけ", badges == 1, str(badges))
        if shot_path:
            page.screenshot(path=shot_path.replace(".png", "_nexus.png"))

        # 以降のソート・絞り込みの検証は Allタブで行う
        page.click("#tabs button[data-target='all']")
        page.wait_for_timeout(900)

        # 最終更新日で昇順→降順
        page.click("#resultHead th:nth-child(5) .hdr")
        page.wait_for_timeout(300)
        asc = page.eval_on_selector_all("#resultBody tr td:nth-child(5)",
                                        "e => e.map(x => x.innerText)")
        check("最終更新日の昇順ソート", asc == sorted(asc), str(asc))
        page.click("#resultHead th:nth-child(5) .hdr")
        page.wait_for_timeout(300)
        desc = page.eval_on_selector_all("#resultBody tr td:nth-child(5)",
                                         "e => e.map(x => x.innerText)")
        check("最終更新日の降順ソート", desc == sorted(desc, reverse=True), str(desc))

        # 種別の複数選択フィルタ
        page.click("#resultHead th:nth-child(6) .filt")
        page.wait_for_timeout(300)
        if shot_path:
            page.screenshot(path=shot_path)      # full_page はパネルを閉じるため使わない
        page.click(".fpanel button:has-text('すべて解除')")
        page.wait_for_timeout(200)
        for value in ("pptx", "xlsm"):
            page.check(f".fpanel input[value='{value}']")
            page.wait_for_timeout(150)
        filtered = titles()
        check("種別を複数選択して絞り込める（pptx と xlsm）",
              len(filtered) == 3 and all(t.endswith((".pptx", ".xlsm")) for t in filtered),
              str(filtered))
        page.click("header")
        page.wait_for_timeout(200)

        # 最終更新日の範囲フィルタ
        page.click("#resultHead th:nth-child(5) .filt")
        page.wait_for_timeout(300)
        dates = page.query_selector_all(".fpanel input[type=date]")
        dates[0].fill("2026-08-01")
        dates[0].dispatch_event("change")
        page.wait_for_timeout(300)
        check("「この日以降」で絞り込める", len(titles()) == 3, str(titles()))
        dates[1].fill("2026-08-25")
        dates[1].dispatch_event("change")
        page.wait_for_timeout(300)
        check("「この日以前」を重ねて絞り込める", len(titles()) == 2, str(titles()))
        page.click("header")
        page.wait_for_timeout(200)

        # 一括ダウンロードの選択
        page.check("#resultBody tr:nth-child(1) td.selcol input")
        page.wait_for_timeout(200)
        check("選択件数がボタンに出る",
              "(1)" in page.text_content("#btnDownload"),
              page.text_content("#btnDownload"))

        # 再読み込みで状態が復元される
        page.reload()
        page.wait_for_timeout(1800)
        check("再起動後もキーワードが復元される",
              page.input_value("#keyword") == "validation", page.input_value("#keyword"))
        check("再起動後も絞り込みが復元される", len(titles()) == 2, str(titles()))
        arrows = page.eval_on_selector_all("#resultHead .arrow",
                                           "e => e.map(x => x.innerText)")
        check("再起動後もソート状態が復元される", arrows == ["▼"], str(arrows))

        browser.close()

    print(f"\n{'=' * 46}")
    print(f"  成功 {ok} 件 / 失敗 {ng} 件")
    print(f"{'=' * 46}")
    return 1 if ng else 0


if __name__ == "__main__":
    sys.exit(main())
