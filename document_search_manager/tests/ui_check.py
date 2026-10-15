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
import io
import json
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
        # 要約機能Phase A(20260904_02)で末尾に「要約」列を追加したため8列になった
        # （仕様変更に伴う陳腐化。列自体は次のcheckで別途確認する）。
        check("Allタブの列構成（ソース/タイトル/選択/作成者/最終更新日/種別/サイト/要約）",
              len(headers) == 8 and headers[1].startswith("タイトル")
              and headers[6].startswith("サイト") and headers[7].startswith("要約"),
              str(headers))
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

        # ── Enoviaタブ（Phase 3）── 既存のソート・絞り込み・状態復元の検証
        # （SharePoint/Nexusの2系統・SAMPLE+2件を前提にしている）を巻き込まないよう、
        # ここで最後にスタブを差し込んで単独で確認する。
        enovia_rows = [
            dsm.SearchResult(
                source="Enovia", document_number="DOC-594838", title="NEH8100 V&V Plan",
                description="NEH8100 Verification and Validation Plan", revision="3",
                enovia_state="Document Release.IN_WORK", author="Sheribeth Bolanos",
                doc_owner="Sheribeth Bolanos", last_modified="2026-09-04",
                created_date="2026-09-03", folder="Release and Production",
                doc_type="xlsm",
                url="https://dspace.plm.nexperia.com/3dspace/common/emxNavigator.jsp?objectId=A",
                enovia_url="https://dspace.plm.nexperia.com/3dspace/common/emxNavigator.jsp?objectId=A",
                rank=1),
            dsm.SearchResult(
                source="Enovia", document_number="DOC-594838", title="NEH8100 V&V Plan",
                description="NEH8100 Verification and Validation Plan", revision="2",
                enovia_state="Document Release.RELEASED", author="Sheribeth Bolanos",
                doc_owner="Sheribeth Bolanos", last_modified_by="Sheribeth Bolanos",
                last_modified="2026-09-03", created_date="2026-01-14",
                folder="Release and Production", doc_type="xlsm",
                url="https://dspace.plm.nexperia.com/3dspace/common/emxNavigator.jsp?objectId=B",
                enovia_url="https://dspace.plm.nexperia.com/3dspace/common/emxNavigator.jsp?objectId=B",
                rank=2),
        ]
        dsm._manager.providers[dsm.TARGET_ENOVIA].search = (
            lambda keyword, max_results: {"results": list(enovia_rows),
                                          "total": len(enovia_rows), "note": ""})

        page.click("#tabs button[data-target='enovia']")
        page.wait_for_timeout(900)
        en_headers = page.eval_on_selector_all("#resultHead th",
                                               "e => e.map(x => x.innerText.trim())")
        for label in ("Document Number", "Title", "Revision", "State", "Description",
                      "Doc Owner", "Enoviaで開く"):
            check(f"Enoviaタブに {label} 列がある",
                  any(h.startswith(label) for h in en_headers), str(en_headers))
        check("Enoviaタブにフォルダリンク列（SharePoint固有）を出さない",
              not any(h.startswith("サイト") for h in en_headers), str(en_headers))

        numbers_en = page.eval_on_selector_all("#resultBody tr td:nth-child(2)",
                                               "e => e.map(x => x.innerText)")
        check("Document Numberの値が並ぶ（Enovia）",
              numbers_en == ["DOC-594838", "DOC-594838"], str(numbers_en))

        rev_index = [i for i, h in enumerate(en_headers)
                    if h.startswith("Revision")][0] + 1
        revisions = page.eval_on_selector_all(
            f"#resultBody tr td:nth-child({rev_index})", "e => e.map(x => x.innerText)")
        check("同一Document Numberでもrevisionが別行のまま並ぶ（D1）",
              revisions == ["3", "2"], str(revisions))

        enovia_links = page.eval_on_selector_all(
            "#resultBody tr td a[href*='emxNavigator.jsp']", "e => e.map(x => x.href)")
        # タイトル列（クリックで開く）と「Enoviaで開く」列の両方にリンクが張られる
        # ため、2行×2リンク=4本になる。
        check("Enoviaで開くリンクが張られる（タイトル列＋専用列）",
              len(enovia_links) == 4, str(enovia_links))

        select_disabled = page.eval_on_selector_all(
            "#resultBody tr td.selcol input", "e => e.map(x => x.disabled)")
        check("Enoviaタブの選択チェックボックスは一括ダウンロード対象外で無効化される",
              all(select_disabled), str(select_disabled))
        if shot_path:
            page.screenshot(path=shot_path.replace(".png", "_enovia.png"))

        # 0.Allタブでは、同じDocument Numberでもリビジョンをタイトルに併記する（B5）。
        # 0.Allタブは、このテストの冒頭で同じキーワードを一度検索済みのため、
        # タブのキャッシュ（②）によりEnoviaを差し込む前の結果が再表示される。
        # 実際の利用でも起こり得る状況なので、「🔄 最新の情報に更新」で
        # 取得し直せることも合わせて確認する。
        page.click("#tabs button[data-target='all']")
        page.wait_for_timeout(900)
        page.click("#btnRefresh")
        page.wait_for_timeout(900)
        all_titles_with_enovia = page.eval_on_selector_all(
            "#resultBody tr td.title", "e => e.map(x => x.innerText)")
        check("0.AllタブでEnovia行のタイトルに(Rev.3)/(Rev.2)が付く",
              any("(Rev.3)" in t for t in all_titles_with_enovia)
              and any("(Rev.2)" in t for t in all_titles_with_enovia),
              str(all_titles_with_enovia))
        all_select_disabled = page.eval_on_selector_all(
            "#resultBody tr:has-text('NEH8100') td.selcol input",
            "e => e.map(x => x.disabled)")
        check("0.AllタブでもEnovia行の選択チェックボックスは無効化される",
              len(all_select_disabled) > 0 and all(all_select_disabled),
              str(all_select_disabled))

        # ── タブ切り替え直後、応答が届く前の表示 ──────────────
        # 越智さんからのフィードバック：タブを切り替えても応答が届くまでの
        # 数秒間、前のタブの結果が残って見え、切り替わっていないように
        # 誤解される、という指摘への対応。応答をわざと遅らせるスタブに
        # 差し替え、クリック直後（応答が届く前）に「検索しています」の
        # 表示へ切り替わることを確認する。
        def slow_sharepoint_search(keyword, max_results):
            time.sleep(1.2)
            return {"results": [dsm.SearchResult(source="SharePoint", title="slow-hit",
                                                  url="https://x/slow.docx", rank=1)],
                    "total": 1, "note": ""}

        dsm._manager.providers[dsm.TARGET_SHAREPOINT].search = slow_sharepoint_search
        page.click("#tabs button[data-target='sharepoint']")
        page.wait_for_timeout(150)   # 応答（1.2秒後）より十分前に確認する
        loading_text = page.text_content("#resultBody")
        check("タブ切り替え直後、応答が届く前は「検索しています」表示になる"
              "（前のタブの結果が残ったままにならない）",
              "検索しています" in (loading_text or ""), loading_text)
        page.wait_for_timeout(1500)  # 応答が届くのを待つ
        settled_titles = titles()
        check("応答が届いたら通常どおり結果に置き換わる",
              settled_titles == ["slow-hit"], str(settled_titles))

        # ── タブのキャッシュ（②）と「さらに取得」（③-C） ─────
        # 越智さんからの要望：条件を変えていないのにタブを行き来するたびに
        # 毎回待たされるのを無くしたい／最初は少なめでも早く表示し、
        # 必要なときだけ多く取得したい、という2点への対応を確認する。
        call_count = {"n": 0}
        TOTAL_MATCHES = 15   # 上限件数(10)より多く、かつ上限の選択肢(500)より少ない

        def counting_search(keyword, max_results):
            call_count["n"] += 1
            n = min(max_results, TOTAL_MATCHES)
            rows = [dsm.SearchResult(source="SharePoint", title="cache-hit-%d" % i,
                                     url="https://x/cache-%d.docx" % i, rank=i + 1)
                    for i in range(n)]
            return {"results": rows, "total": TOTAL_MATCHES, "note": ""}

        dsm._manager.providers[dsm.TARGET_SHAREPOINT].search = counting_search
        page.click("#tabs button[data-target='sharepoint']")
        page.fill("#keyword", "cachetest")
        page.click("#btnSearch")
        page.wait_for_timeout(600)
        check("初回検索でSharePointが1回呼ばれる", call_count["n"] == 1, call_count["n"])
        check("上限(10件)より該当件数(15件)が多いので「さらに取得」が有効になる",
              not page.is_disabled("#btnLoadMore"), "")

        # 条件を変えずにタブを行き来しても、キャッシュにより再取得しない
        page.click("#tabs button[data-target='nexus']")
        page.wait_for_timeout(400)
        page.click("#tabs button[data-target='sharepoint']")
        page.wait_for_timeout(400)
        check("同じ条件でタブへ戻ってもSharePointは再度呼ばれない（キャッシュ）",
              call_count["n"] == 1, call_count["n"])
        check("キャッシュ表示でも結果はすぐに反映される",
              titles() == ["cache-hit-%d" % i for i in range(10)], str(titles()))

        # 「🔄 最新の情報に更新」はキャッシュを無視して取得し直す
        page.click("#btnRefresh")
        page.wait_for_timeout(600)
        check("「最新の情報に更新」はキャッシュを無視して再取得する",
              call_count["n"] == 2, call_count["n"])

        # 「さらに取得」は上限を選択肢の最大値まで引き上げて再取得する
        page.click("#btnLoadMore")
        page.wait_for_timeout(600)
        check("「さらに取得」で取得件数の選択が最大値になる",
              page.input_value("#maxResults") == "500", page.input_value("#maxResults"))
        check("「さらに取得」で該当件数(15件)がすべて取得される",
              len(titles()) == TOTAL_MATCHES, str(len(titles())))
        check("該当件数をすべて取得したら「さらに取得」は無効化される",
              page.is_disabled("#btnLoadMore"), "")

        # ── 依頼1：SharePointの「フォルダのみを検索する」（案A） ─────
        # 直前の区間でSharePointタブのまま終わっているため、まず0.Allタブへ
        # 戻ってから「隠れている」ことを確認する。
        page.click("#tabs button[data-target='all']")
        page.wait_for_timeout(200)
        check("0.Allタブではフォルダのみを検索する行は隠れている",
              not page.is_visible("#folderOnlyRow"))
        page.click("#tabs button[data-target='sharepoint']")
        page.wait_for_timeout(200)
        check("SharePointタブに切り替えるとフォルダのみを検索する行が出る",
              page.is_visible("#folderOnlyRow"))

        # ファイル2件・フォルダ1件が混ざったスタブで、絞り込みが実際に
        # 効くこと（0件になるだけの弱い確認ではなく）を確認する。
        mixed_rows = [
            dsm.SearchResult(source="SharePoint", title="normal-file-1",
                             url="https://x/f1.docx", doc_type="docx", rank=1),
            dsm.SearchResult(source="SharePoint", title="normal-file-2",
                             url="https://x/f2.docx", doc_type="docx", rank=2),
            dsm.SearchResult(source="SharePoint", title="a-folder",
                             url="https://x/folder", doc_type=dsm.FOLDER_TYPE_LABEL,
                             is_folder=True, rank=3),
        ]
        dsm._manager.providers[dsm.TARGET_SHAREPOINT].search = (
            lambda kw, mx: {"results": list(mixed_rows), "total": len(mixed_rows), "note": ""})
        page.fill("#keyword", "folderonlytest")
        page.click("#btnSearch")
        page.wait_for_timeout(400)
        check("フォルダのみを検索するオフの状態では、ファイルもフォルダも見える",
              sorted(titles()) == ["a-folder", "normal-file-1", "normal-file-2"],
              str(titles()))

        page.check("#folderOnly")
        page.wait_for_timeout(200)
        check("フォルダのみを検索するをオンにすると、その場でフォルダだけに絞られる"
              "（再検索せずクライアント側で反映される）",
              titles() == ["a-folder"], str(titles()))

        page.uncheck("#folderOnly")
        page.wait_for_timeout(200)
        check("オフに戻すと絞り込みが解除される",
              sorted(titles()) == ["a-folder", "normal-file-1", "normal-file-2"],
              str(titles()))

        page.click("#tabs button[data-target='all']")
        page.wait_for_timeout(200)
        check("0.Allタブに戻るとフォルダのみを検索する行はまた隠れる",
              not page.is_visible("#folderOnlyRow"))

        # ── 文書の要約（AI・Gemini経由）── 要約機能 Phase A/B ────────
        page.click("#tabs button[data-target='sharepoint']")
        page.wait_for_timeout(200)
        summary_rows = [
            dsm.SearchResult(source="SharePoint", title="summarizable-doc",
                             url="https://x/sd.docx", doc_type="docx", rank=1),
            dsm.SearchResult(source="SharePoint", title="a-folder-2",
                             url="https://x/folder2", doc_type=dsm.FOLDER_TYPE_LABEL,
                             is_folder=True, rank=2),
            dsm.SearchResult(source="SharePoint", title="a-slide",
                             url="https://x/s.pptx", doc_type="pptx", rank=3),
            dsm.SearchResult(source="SharePoint", title="a-sheet",
                             url="https://x/e.xlsx", doc_type="xlsx", rank=4),
            dsm.SearchResult(source="SharePoint", title="a-macro-sheet",
                             url="https://x/e2.xlsm", doc_type="xlsm", rank=5),
            dsm.SearchResult(source="SharePoint", title="a-pdf",
                             url="https://x/p.pdf", doc_type="pdf", rank=6),
            dsm.SearchResult(source="SharePoint", title="a-mail",
                             url="https://x/m.msg", doc_type="msg", rank=7),
        ]
        dsm._manager.providers[dsm.TARGET_SHAREPOINT].search = (
            lambda kw, mx: {"results": list(summary_rows), "total": len(summary_rows), "note": ""})
        page.fill("#keyword", "summarytest")
        page.click("#btnSearch")
        page.wait_for_timeout(400)

        summary_buttons = page.query_selector_all("#resultBody button.mini")
        check("要約ボタンが行数ぶん出る", len(summary_buttons) == 7, len(summary_buttons))
        disabled_states = [b.is_disabled() for b in summary_buttons]
        check("docx行の要約ボタンは有効", disabled_states[0] is False, disabled_states)
        check("フォルダ行の要約ボタンは無効", disabled_states[1] is True, disabled_states)
        check("pptx行の要約ボタンは有効（Phase Bで追加）", disabled_states[2] is False, disabled_states)
        check("xlsx行の要約ボタンは有効（Phase Cで追加）", disabled_states[3] is False, disabled_states)
        check("xlsm行の要約ボタンは有効（マクロ有効ブックもxlsxと同様に対応）",
              disabled_states[4] is False, disabled_states)
        check("pdf行の要約ボタンは有効（v20260910_02で追加）",
              disabled_states[5] is False, disabled_states)
        check("対応外の形式(msg)の要約ボタンは無効",
              disabled_states[6] is True, disabled_states)

        summary_buttons[0].click()
        check("クリックするとポップアップが開く", page.is_visible("#summaryOverlay"))

        page.wait_for_timeout(800)
        # このサンドボックスにはGemini共通モジュールが無いため、実際に
        # エンドツーエンドでエラー表示まで辿り着くことを確認する
        # （検索とは独立した経路で、要約機能だけがエラーになることを示す）。
        # 応答が非常に速い（HAS_GEMINIチェックで即エラーになる）ため、
        # 「生成中」表示は一瞬しか出ずタイミング依存になる。ここでは
        # 最終的にエラー表示まで到達することだけを確認する。
        error_text = page.text_content(".summary-body")
        check("Gemini未設定の環境ではエラーメッセージが表示される（黙って固まらない）",
              "summary-error" in page.eval_on_selector(".summary-body", "e => e.innerHTML"),
              error_text)

        page.click(".summary-header button")
        page.wait_for_timeout(100)
        check("閉じるボタンでポップアップが消える", not page.is_visible("#summaryOverlay"))

        # ── 切り詰め時の確認ダイアログ（Phase C） ─────────────────
        # Gemini呼び出し等をスタブ化し、実ブラウザで
        # 「確認→続ける→要約表示」の一連の流れを検証する。
        from docx import Document as _ConfirmDocxDocument

        class _FakeDownloadResp:
            def __init__(self, code, content=b""):
                self.status_code = code
                self.content = content

        _confirm_docx_paragraphs_doc = _ConfirmDocxDocument()
        _confirm_docx_paragraphs_doc.add_paragraph("これは切り詰め確認テスト用の本文です。" * 5)
        _confirm_docx_buf = io.BytesIO()
        _confirm_docx_paragraphs_doc.save(_confirm_docx_buf)
        confirm_docx_bytes = _confirm_docx_buf.getvalue()

        def fake_gemini_for_confirm(payload, model=None):
            data = {
                "executive_summary": "確認後の要約です。",
                "chapters": [{"title": "章1", "overview": "概要"}],
                "insights": {"use": ["活用1", "活用2", "活用3"],
                             "caution": ["注意1", "注意2", "注意3"],
                             "questions": ["問い1", "問い2", "問い3"]},
            }
            return {"candidates": [{"content": {"parts": [
                {"text": json.dumps(data, ensure_ascii=False)}
            ]}}]}

        orig_has_gemini_ui = dsm.HAS_GEMINI
        orig_cred_ui = dsm.gemini_credentials_available
        orig_http_get_ui = dsm.http_req.get
        orig_generate_advanced_ui = dsm._generate_advanced
        orig_cfg_ui = dsm._cfg
        try:
            dsm.HAS_GEMINI = True
            dsm.gemini_credentials_available = lambda: True
            dsm.http_req.get = lambda *a, **k: _FakeDownloadResp(200, confirm_docx_bytes)
            dsm._generate_advanced = fake_gemini_for_confirm
            dsm._cfg = dict(dsm._cfg, summary_max_chars=20, summary_min_chars=1)

            summary_buttons2 = page.query_selector_all("#resultBody button.mini")
            summary_buttons2[0].click()   # docx行（summarizable-doc）
            page.wait_for_timeout(600)
            check("上限超過時は確認メッセージが表示される（Geminiを黙って呼ばない）",
                  "上限" in (page.text_content(".summary-body") or ""),
                  page.text_content(".summary-body"))
            check("「続ける」ボタンが表示される",
                  page.is_visible("text=続ける（先頭部分だけで要約）"))

            page.click("text=続ける（先頭部分だけで要約）")
            page.wait_for_timeout(600)
            check("続けるを押すと実際に要約結果が表示される",
                  "確認後の要約です" in (page.text_content(".summary-body") or ""),
                  page.text_content(".summary-body"))

            page.click(".summary-header button")
            page.wait_for_timeout(100)
        finally:
            dsm.HAS_GEMINI = orig_has_gemini_ui
            dsm.gemini_credentials_available = orig_cred_ui
            dsm.http_req.get = orig_http_get_ui
            dsm._generate_advanced = orig_generate_advanced_ui
            dsm._cfg = orig_cfg_ui


        # ── 図面が主体のPDF（v20260910_03）─────────────────────
        # 回路図PDFを要約しようとしたときに、Geminiを呼ばずに理由を伝え、
        # そのままファイルを開ける状態になるかを本物のブラウザで確認する。
        drawing_rows = [
            dsm.SearchResult(source="SharePoint", title="Schematic_RevB",
                             url="https://x/sites/S/Docs/sch.pdf",
                             doc_type="pdf", last_modified="2026-09-01", rank=1),
        ]
        dsm._manager.providers[dsm.TARGET_SHAREPOINT].search = (
            lambda kw, mx: {"results": list(drawing_rows), "total": 1, "note": ""})

        drawing_labels = ["R23", "C104", "U5", "VDD_3V3", "SDA", "10k", "GND"]
        drawing_text = "# Page 1\n" + "\n".join(
            drawing_labels[i % len(drawing_labels)] for i in range(3000))

        gemini_called = []

        orig_dl_drawing = dsm._download_one
        orig_ex_drawing = dsm._extract_text_for_summary
        orig_gen_drawing = dsm._generate_summary
        orig_has_drawing = dsm.HAS_GEMINI
        orig_cred_drawing = dsm.gemini_credentials_available
        try:
            dsm.HAS_GEMINI = True
            dsm.gemini_credentials_available = lambda: True
            dsm._download_one = lambda t, r, to: ("sch.pdf", b"%PDF-dummy")
            dsm._extract_text_for_summary = (
                lambda dt, c, mx: (drawing_text, False, len(drawing_text)))

            def _gen_drawing(title, text):
                gemini_called.append(title)
                return {"executive_summary": "羅列からの要約", "chapters": [],
                        "insights": {"use": [], "caution": [], "questions": []}}

            dsm._generate_summary = _gen_drawing
            dsm._summary_cache.clear()

            page.click("#tabs button[data-target='sharepoint']")
            page.wait_for_timeout(300)
            page.fill("#keyword", "schematic")
            page.click("#btnSearch")
            page.wait_for_timeout(700)

            page.query_selector_all("#resultBody button.mini")[0].click()
            page.wait_for_timeout(800)
            notice = page.text_content(".summary-body") or ""
            check("図面PDFでは要約の代わりに理由が表示される",
                  "図面が主体" in notice, notice[:120])
            check("判定の根拠（数字）も表示される",
                  "1行あたり平均" in notice, notice[:200])
            check("Geminiを呼んでいない（待たされない）",
                  gemini_called == [], gemini_called)
            check("「ファイルを開く」ボタンが出る",
                  page.is_visible("text=ファイルを開く"))
            check("「それでも要約する」ボタンが出る",
                  page.is_visible("text=それでも要約する"))

            page.click("text=それでも要約する")
            page.wait_for_timeout(800)
            check("「それでも要約する」を押せば実際に要約が実行される",
                  gemini_called == ["Schematic_RevB"]
                  and "羅列からの要約" in (page.text_content(".summary-body") or ""),
                  (gemini_called, page.text_content(".summary-body")))
            page.click(".summary-header button")
            page.wait_for_timeout(100)
        finally:
            dsm._download_one = orig_dl_drawing
            dsm._extract_text_for_summary = orig_ex_drawing
            dsm._generate_summary = orig_gen_drawing
            dsm.HAS_GEMINI = orig_has_drawing
            dsm.gemini_credentials_available = orig_cred_drawing
            dsm._summary_cache.clear()

        # ── フォルダ探索（v20260910_02）───────────────────────
        # 実際にチェックを付けて探索を実行し、ツリー表示・一覧表示・開閉・
        # ファイル名のリンクまでを本物のブラウザで確認する。
        # 単体テストでは見つからない不具合（CSSで [hidden] が効かない等、
        # 過去に実際に起きた）を捕まえるのがこの節の役割。
        explore_root = dsm.SearchResult(
            source="SharePoint", title="03. Hardware", is_folder=True,
            doc_type=dsm.FOLDER_TYPE_LABEL, site="Japan Design Center",
            url="https://x/sites/S/Docs/03Hardware", last_modified="2026-08-21",
            rank=1)
        dsm._manager.providers[dsm.TARGET_SHAREPOINT].search = (
            lambda kw, mx: {"results": [explore_root], "total": 1, "note": ""})

        def _graph_item(item_id, name, folder=False, size=126976):
            body = {"id": item_id, "name": name,
                    "webUrl": "https://x/sites/S/Docs/" + name,
                    "lastModifiedDateTime": "2026-08-21T05:00:00Z",
                    "createdBy": {"user": {"displayName": "Ochi"}},
                    "parentReference": {"driveId": "DRIVE01"}}
            if folder:
                body["folder"] = {"childCount": 2}
            else:
                body["file"] = {"mimeType": "application/octet-stream"}
                body["size"] = size
            return body

        EXPLORE_TREE = {
            "ROOT01": [_graph_item("SUB01", "01. Validation_Plan", folder=True),
                       _graph_item("FILE01", "Overview.docx")],
            "SUB01": [_graph_item("FILE02", "Plan_Rev3.pdf"),
                      _graph_item("FILE03", "Data.xlsx", size=2516582)],
        }

        class _FakeGraphResp:
            def __init__(self, payload):
                self.status_code = 200
                self._payload = payload
                self.text = ""

            def json(self):
                return self._payload

        def fake_graph_get(url, headers=None, timeout=None, **kwargs):
            if "/driveItem" in url and "/children" not in url:
                return _FakeGraphResp(_graph_item("ROOT01", "03. Hardware",
                                                  folder=True))
            if "/items/" in url and "/children" in url:
                item_id = url.split("/items/", 1)[1].split("/children", 1)[0]
                return _FakeGraphResp({"value": EXPLORE_TREE.get(item_id, [])})
            return _FakeGraphResp({"value": []})

        orig_http_get_explore = dsm.http_req.get
        dsm.http_req.get = fake_graph_get
        try:
            page.click("#tabs button[data-target='sharepoint']")
            page.wait_for_timeout(300)
            page.fill("#keyword", "explore-test")
            page.click("#btnSearch")
            page.wait_for_timeout(700)

            explore_boxes = page.query_selector_all(
                "#resultBody input[title*='再帰的に探索']")
            check("フォルダ行に「探索」のチェックが出る",
                  len(explore_boxes) == 1, len(explore_boxes))
            check("探索ボタンは、チェックを付ける前は押せない",
                  page.is_visible("#btnExplore")
                  and page.is_disabled("#btnExplore"))

            check("ツリー／一覧の切替は、検索結果のタブには出さない",
                  not page.is_visible("#viewToggle"))

            explore_boxes[0].check()
            page.wait_for_timeout(200)
            check("チェックを付けると探索ボタンが押せるようになる",
                  not page.is_disabled("#btnExplore"))
            check("探索ボタンに選択件数が出る",
                  "(1)" in (page.text_content("#btnExplore") or ""),
                  page.text_content("#btnExplore"))

            page.click("#btnExplore")
            page.wait_for_timeout(3500)

            check("探索が終わるとフォルダ探索タブが現れる",
                  page.is_visible("#tabExplore"))
            check("フォルダ探索タブが選択された状態になる",
                  "on" in (page.get_attribute("#tabExplore", "class") or ""),
                  page.get_attribute("#tabExplore", "class"))
            check("件数の見出しが「探索結果」になる",
                  "探索結果" in (page.text_content("#resultCount") or ""),
                  page.text_content("#resultCount"))

            tree_rows = page.eval_on_selector_all(
                "#resultBody tr td.title", "e => e.map(x => x.innerText.trim())")
            check("起点＋配下のすべてが行になる（4件＋起点）",
                  len(tree_rows) == 5, tree_rows)
            check("ツリー表示ではフォルダが先に並ぶ",
                  tree_rows[1].endswith("01. Validation_Plan"), tree_rows)

            indents = page.eval_on_selector_all(
                "#resultBody tr td.title .tindent",
                "e => e.map(x => x.style.width)")
            check("階層の深さだけ字下げされる（0/18/36px…）",
                  indents[0] == "0px" and indents[1] == "18px"
                  and indents[2] == "36px", indents)

            links = page.eval_on_selector_all(
                "#resultBody tr td.title a", "e => e.map(x => x.getAttribute('href'))")
            check("ツリー表示でもファイル名がリンクになっている（クリックで開ける）",
                  len(links) == 5 and all(h and h.startswith("https://") for h in links),
                  links)

            toggles = page.query_selector_all("#resultBody .ttoggle:not(.empty)")
            check("中身のあるフォルダには開閉の記号が出る",
                  len(toggles) == 2, len(toggles))
            toggles[1].click()   # 01. Validation_Plan を閉じる
            page.wait_for_timeout(300)
            check("フォルダを閉じるとその配下が隠れる",
                  len(page.query_selector_all("#resultBody tr td.title")) == 3,
                  len(page.query_selector_all("#resultBody tr td.title")))
            page.query_selector_all("#resultBody .ttoggle:not(.empty)")[1].click()
            page.wait_for_timeout(300)
            check("もう一度押すと元に戻る",
                  len(page.query_selector_all("#resultBody tr td.title")) == 5)

            # 承認済み設計どおり、ツリー表示でも「種別」だけは絞り込める。
            # 他の列は階層が壊れるため出さない。
            check("ツリー表示の絞り込みは「種別」だけ",
                  len(page.query_selector_all("#resultHead .filt")) == 1
                  and page.eval_on_selector_all(
                      "#resultHead th",
                      "e => e.filter(x => x.querySelector('.filt'))"
                      "      .every(x => x.innerText.indexOf('種別') >= 0)"),
                  page.eval_on_selector_all(
                      "#resultHead th",
                      "e => e.filter(x => x.querySelector('.filt'))"
                      "      .map(x => x.innerText.trim())"))

            page.click("#resultHead .filt")
            page.wait_for_timeout(200)
            page.click(".fpanel button:has-text('すべて解除')")
            page.wait_for_timeout(150)
            page.check(".fpanel input[type=checkbox][value='pdf']")
            page.wait_for_timeout(300)
            filtered = page.eval_on_selector_all(
                "#resultBody tr td.title", "e => e.map(x => x.innerText.trim())")
            check("ツリー表示で種別を絞り込むと、該当ファイルとその親だけが残る",
                  any("Plan_Rev3.pdf" in t for t in filtered)
                  and not any("Overview.docx" in t for t in filtered)
                  and any("01. Validation_Plan" in t for t in filtered),
                  filtered)
            page.click("#btnClearFilter")
            page.wait_for_timeout(300)
            check("絞り込みを解除すると全件に戻る",
                  len(page.query_selector_all("#resultBody tr td.title")) == 5,
                  len(page.query_selector_all("#resultBody tr td.title")))
            check("検索専用のボタンは探索タブでは出さない（押すと結果が消えるため）",
                  not page.is_visible("#btnRefresh")
                  and not page.is_visible("#btnLoadMore"))

            check("フォルダ探索タブではツリー／一覧の切替が出る",
                  page.is_visible("#viewToggle"))

            page.click("#btnFlatView")
            page.wait_for_timeout(300)
            check("一覧表示に切り替えると絞り込みの記号が出る",
                  len(page.query_selector_all("#resultHead .filt")) > 0)
            check("一覧表示では字下げしない",
                  len(page.query_selector_all("#resultBody .tindent")) == 0)
            flat_rows = page.eval_on_selector_all(
                "#resultBody tr td.title", "e => e.map(x => x.innerText.trim())")
            check("一覧表示でも全件見える", len(flat_rows) == 5, flat_rows)
            flat_links = page.eval_on_selector_all(
                "#resultBody tr td.title a", "e => e.map(x => x.getAttribute('href'))")
            check("一覧表示でもファイル名がリンクになっている",
                  len(flat_links) == 5, flat_links)

            sizes = page.eval_on_selector_all(
                "#resultBody tr td:nth-child(5)", "e => e.map(x => x.innerText.trim())")
            check("サイズが読みやすい単位で出る（フォルダは空欄）",
                  "" in sizes and any(v.endswith("KB") for v in sizes)
                  and any(v.endswith("MB") for v in sizes), sizes)

            headers_ex = page.eval_on_selector_all(
                "#resultHead th", "e => e.map(x => x.innerText.trim())")
            check("サイズ列には絞り込みを付けない（連続値のため並べ替えのみ）",
                  page.eval_on_selector_all(
                      "#resultHead th",
                      "e => e.filter(x => x.innerText.indexOf('サイズ') >= 0)"
                      "      .every(x => !x.querySelector('.filt'))"),
                  headers_ex)

            page.click("#tabs button[data-target='sharepoint']")
            page.wait_for_timeout(800)
            check("SharePointタブに戻ると検索結果の表示に戻る",
                  "検索結果" in (page.text_content("#resultCount") or ""),
                  page.text_content("#resultCount"))
            page.click("#tabExplore")
            page.wait_for_timeout(500)
            check("フォルダ探索タブに戻すと、再探索せずに結果が出る",
                  "探索結果" in (page.text_content("#resultCount") or "")
                  and len(page.query_selector_all("#resultBody tr td.title")) == 5,
                  page.text_content("#resultCount"))
        finally:
            dsm.http_req.get = orig_http_get_explore

        browser.close()

    print(f"\n{'=' * 46}")
    print(f"  成功 {ok} 件 / 失敗 {ng} 件")
    print(f"{'=' * 46}")
    return 1 if ng else 0


if __name__ == "__main__":
    sys.exit(main())
