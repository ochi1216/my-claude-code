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
    manager.providers[dsm.TARGET_NEXUS].search = (
        lambda keyword, max_results: {"results": [], "total": 0, "note": ""})
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

        check("検索結果が表示される", len(titles()) == len(SAMPLE), str(len(titles())))

        headers = page.eval_on_selector_all("#resultHead th",
                                            "e => e.map(x => x.innerText.trim())")
        check("列構成（ソース/タイトル/選択/作成者/最終更新日/種別/サイト/フォルダ）",
              len(headers) == 8 and headers[1].startswith("タイトル")
              and headers[7].startswith("フォルダ"), str(headers))

        types = page.eval_on_selector_all("#resultBody tr td:nth-child(6)",
                                          "e => e.map(x => x.innerText)")
        check("種別に %20 等の壊れた値が無い",
              all("%" not in t for t in types), str(types))
        check("フォルダ行が「フォルダ」と表示される", "フォルダ" in types, str(types))

        folders = page.eval_on_selector_all("#resultBody tr td:nth-child(8)",
                                            "e => e.map(x => x.innerText)")
        check("フォルダ列が / 始まりに短縮される",
              all(f.startswith("/") for f in folders if f), str(folders))

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
