# -*- coding: utf-8 -*-
"""ブラウザ操作テスト：サイト名のみ検索・除外診断（Playwright）— v20261007_01 で追加

ダミーデータで画面を起動し、「サイト名のみを検索する」の切り替え・無効化の戻し
忘れ・サイト一覧の表・🔍でサイト内検索へ進む動き・除外診断のログを、
実際のブラウザで操作して確認する。Graph API には一切アクセスしない。

    python tests/ui_check_site_only.py [--headed] [--shot 出力先.png]
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
    print("  成功 0 件 / 失敗 0 件")
    sys.exit(0)

PORT = 5098
WORK = Path(tempfile.mkdtemp())
PO = "https://nexperia.sharepoint.com/sites/PO"
LORRY = "https://nexperia.sharepoint.com/sites/P010024_Lorry"

ok, ng = 0, 0


def check(label, condition, detail=""):
    global ok, ng
    if condition:
        ok += 1
        print(f"  OK   {label}")
    else:
        ng += 1
        print(f"  NG   {label}  {detail}")


class FakeResp:
    def __init__(self, status, body=None, text=""):
        self.status_code, self._body, self.text = status, body, text

    def json(self):
        return self._body


def start_server():
    cfg = dict(dsm.DEFAULT_CFG, auto_open_browser=False, default_max_results=10)
    dsm.STATE_PATH = WORK / "session_state.json"
    dsm.EXPORT_DIR = WORK / "exports"
    dsm.FAVORITE_SITES_PATH = WORK / "favorite_sites.json"
    dsm._cfg = cfg
    dsm._auth = DummyAuth()

    manager = dsm.SearchManager(cfg, DummyAuth())
    sp = manager.providers[dsm.TARGET_SHAREPOINT]
    sp._token = lambda: "t"

    def fake_search(keyword, max_results):
        hit = {"resource": {"webUrl": f"{LORRY}/Shared%20Documents/a.docx",
                            "lastModifiedDateTime": "2026-04-14T04:00:00Z",
                            "createdBy": {"user": {"displayName": "Taro"}}}}
        return {"results": [sp._hit_to_result(hit, 1)], "total": 1,
                "note": f"サイト内検索: /sites/P010024_Lorry" if sp.site_scope_url else ""}
    sp.search = fake_search

    def fake_call(token, query, frm=0, size=25):
        hits = [{"resource": {"webUrl": f"{PO}/Shared%20Documents/x.docx"}}]
        body = {"value": [{"hitsContainers": [{"total": 9, "hits": hits}]}]}
        return 200, body, ""
    sp._call_search_api = fake_call
    for k in (dsm.TARGET_NEXUS, dsm.TARGET_ENOVIA):
        manager.providers[k].search = lambda kw, mx: {"results": [], "total": 0, "note": ""}
    dsm._manager = manager

    def fake_post(url, **kw):
        body = {"value": [{"hitsContainers": [{"total": 2, "hits": [
            {"resource": {"displayName": "PO", "webUrl": PO, "description": "purchase orders"}},
            {"resource": {"displayName": "P010024_Lorry", "webUrl": LORRY, "description": ""}},
        ]}]}]}
        return FakeResp(200, body)
    dsm.http_req.post = fake_post

    threading.Thread(
        target=lambda: dsm.flask_app.run(host="127.0.0.1", port=PORT,
                                         debug=False, use_reloader=False),
        daemon=True).start()
    time.sleep(2)


def main():
    print(f"🧪 ブラウザ操作テスト：サイト名のみ・除外診断（対象: {DSM_FILENAME}）")
    start_server()
    launch_args = {"headless": "--headed" not in sys.argv}
    if os.environ.get("CHROMIUM_PATH"):
        launch_args["executable_path"] = os.environ["CHROMIUM_PATH"]

    with sync_playwright() as pw:
        browser = pw.chromium.launch(**launch_args)
        page = browser.new_page(viewport={"width": 1500, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{PORT}/")

        def visible(sel):
            return page.is_visible(sel)

        def disabled(sel):
            return page.is_disabled(sel)

        def headers():
            return page.eval_on_selector_all("#resultHead th", "e => e.map(x => x.innerText.trim())")

        # ── 表示・非表示（[hidden] の対） ──
        check("Allタブでは「サイト名のみ」も除外診断の行も見えない",
              not visible("#siteOnly") and not visible("#exclusionDiagRow"))
        page.click("#tabs button[data-target='sharepoint']")
        page.wait_for_timeout(300)
        check("SharePointタブでは「サイト名のみ」と除外診断の行が見える",
              visible("#siteOnly") and visible("#exclusionDiagRow") and visible("#btnExclusionDiag"))
        check("注記は既定で見えない", not visible("#siteOnlyNote"))
        check("既定では文書検索用の指定は有効",
              not disabled("#titleOnly") and not disabled("#prefixSearch")
              and not disabled("#folderOnly") and not disabled("#siteSearchInput"))

        # ── オンにすると文書検索用の指定が無効になる ──
        page.check("#siteOnly")
        page.wait_for_timeout(200)
        check("オンにすると、タイトル限定・前方一致・フォルダのみ・サイト指定が無効になる",
              all(disabled(s) for s in ("#titleOnly", "#prefixSearch", "#folderOnly",
                                        "#siteSearchInput", "#btnSiteSearch", "#favoriteSites")))
        check("注記が見える", visible("#siteOnlyNote"))

        # ── 他のタブへ移ると無効が戻る（Nexusではタイトル限定が使える） ──
        page.click("#tabs button[data-target='nexus']")
        page.wait_for_timeout(300)
        check("Nexusタブでは、タイトル限定・前方一致が有効に戻る（無効のまま残らない）",
              not disabled("#titleOnly") and not disabled("#prefixSearch"))
        check("Nexusタブでは「サイト名のみ」の行は見えない", not visible("#siteOnly"))
        page.click("#tabs button[data-target='sharepoint']")
        page.wait_for_timeout(300)
        check("SharePointタブに戻ると、チェックが残っていて無効も再び効く",
              page.is_checked("#siteOnly") and disabled("#titleOnly"))

        # ── キーワードが空なら送らない ──
        page.fill("#keyword", "")
        page.click("#btnSearch")
        page.wait_for_timeout(300)
        check("キーワードが空なら、ログで案内して検索しない",
              "サイト名（の一部）を入力してください" in (page.text_content("#log") or ""))

        # ── サイト一覧の表 ──
        page.fill("#keyword", "PO")
        page.click("#btnSearch")
        page.wait_for_timeout(900)
        hs = headers()
        check("サイト用の列（サイト名・場所・説明・サイト内検索）に切り替わる",
              [h.split("\n")[0].replace("🔽", "").strip()[:4] for h in hs][:1] == ["サイト名"]
              and len(hs) == 4, hs)
        check("選択・探索・要約の列は出ない",
              not any(h.startswith(x) for h in hs for x in ("選択", "探索", "要約")), hs)
        rows = page.eval_on_selector_all("#resultBody tr", "e => e.map(x => x.innerText)")
        check("サイトが2行並ぶ（PO と P010024_Lorry）",
              len(rows) == 2 and "PO" in rows[0] and "/sites/PO" in rows[0]
              and "purchase orders" in rows[0], rows)
        check("件数表示", "2 件" in (page.text_content("#resultCount") or ""),
              page.text_content("#resultCount"))
        check("サイト名のリンク先はサイトのトップ",
              page.eval_on_selector("#resultBody tr td.title a", "e => e.href") == PO)
        check("選択用のチェックボックスは1つも無い（ZIPの対象にならない）",
              len(page.query_selector_all("#resultBody input[type=checkbox]")) == 0)
        check("探索ボタンは出ない", not visible("#btnExplore"))
        check("Excel/CSVは出せる", not disabled("#btnXlsx") and not disabled("#btnCsv"))
        check("ZIPボタンは無効", disabled("#btnDownload"))

        if "--shot" in sys.argv:
            page.screenshot(path=sys.argv[sys.argv.index("--shot") + 1], full_page=True)

        # ── 指定を変えたら再検索の案内 ──
        page.uncheck("#siteOnly")
        page.wait_for_timeout(200)
        check("チェックを外しただけでは表は変わらず、再検索の案内が出る",
              "もう一度「検索」を押す" in (page.text_content("#tabHint") or "")
              and len(headers()) == 4, page.text_content("#tabHint"))
        check("外すと、文書検索用の指定が有効に戻る",
              not disabled("#titleOnly") and not disabled("#siteSearchInput"))
        page.check("#siteOnly")
        page.wait_for_timeout(200)
        check("元に戻すと案内は消える", (page.text_content("#tabHint") or "").strip() == "")

        # ── 🔍でサイト内検索へ進む ──
        page.click("#resultBody tr:nth-child(2) button:has-text('このサイト内を検索')")
        page.wait_for_timeout(900)
        check("🔍を押すと、サイト名のみはオフに戻る", not page.is_checked("#siteOnly"))
        check("対象サイトのチップが出る", visible("#siteChip")
              and "P010024_Lorry" in (page.text_content("#siteChipName") or ""))
        hs2 = headers()
        check("文書検索の列（タイトル・探索・選択…）に戻る",
              any(h.startswith("フォルダ") for h in hs2) and any(h.startswith("探索") for h in hs2)
              and page.query_selector("#resultHead th.selcol input") is not None, hs2)
        check("サイト内検索の結果が出る",
              len(page.query_selector_all("#resultBody tr td.title")) == 1)
        check("文書検索用の指定は有効", not disabled("#titleOnly") and not disabled("#siteSearchInput"))
        check("探索ボタンが文書の結果では見える", visible("#btnExplore"))

        # ── 除外診断 ──
        page.fill("#keyword", "validation")
        page.click("#btnExclusionDiag")
        page.wait_for_timeout(300)
        check("除外サイト・除外キーワードが空なら、案内して送らない",
              "除外サイト（例: PO）か除外キーワード" in (page.text_content("#log") or ""))
        page.fill("#exclSites", "PO")
        page.fill("#exclWords", "old draft")
        page.click("#btnExclusionDiag")
        page.wait_for_timeout(900)
        log = page.text_content("#log") or ""
        check("条件ごとの件数と、組み立てたKQLがログに並ぶ",
              "A. NOT path:" in log and "B. NOT SPSiteURL:" in log and "C. -path:" in log
              and "D. 除外キーワード" in log and "E. A と D の併用" in log
              and f'NOT path:"{PO}"' in log, log[-1500:])
        check("「除外サイトの行」の件数を出す", "除外サイトの行" in log)
        check("診断は結果の表を書き換えない（サイト内検索の結果のまま）",
              len(page.query_selector_all("#resultBody tr td.title")) == 1)
        check("診断が終わったらボタンは有効に戻る", not disabled("#btnExclusionDiag"))

        check("画面のJSエラーが無い", not errors, str(errors))
        browser.close()

    print(f"\n{'=' * 46}")
    print(f"  成功 {ok} 件 / 失敗 {ng} 件")
    print(f"{'=' * 46}")
    return 1 if ng else 0


if __name__ == "__main__":
    sys.exit(main())
