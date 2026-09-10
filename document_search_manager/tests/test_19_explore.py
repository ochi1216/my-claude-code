# -*- coding: utf-8 -*-
"""フォルダ探索（Phase A/B）— /api/explore・ツリー構築・既存機能への受け渡し

v20260910_01 の事前診断で、Sites.Read.All のまま
  /shares/{token}/driveItem → /children → /drives/{driveId}/items/{id}/children
の3段が通ることを実機確認済み。本テストは、その事実の上に載せた本実装の検証。

確認する軸は5つ。
  ① Graphの応答を、画面と同じ SearchResult に正しく写せているか
  ② ページ送り（@odata.nextLink）を最後まで追えているか
  ③ 上限（深さ5階層 / 2000件）で確実に止まり、理由を残せているか
  ④ 探索結果に対して、既存のZIP取得・Excel出力・要約がそのまま効くか
  ⑤ 版を上げたのに古い画面が出る事故（実機で発生）への対策が入っているか

ネットワークには一切アクセスせず、http_req.get をスタブに差し替えて検証する。
実行: python tests/test_19_explore.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import dsm, Checker, DummyAuth  # noqa: E402

check = Checker()


class FakeResp:
    def __init__(self, code, payload=None, text=""):
        self.status_code = code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def folder_item(item_id, name, child_count=1):
    return {
        "id": item_id, "name": name,
        "folder": {"childCount": child_count},
        "webUrl": f"https://x/sites/S/Docs/{name}",
        "lastModifiedDateTime": "2026-08-21T05:00:00Z",
        "createdBy": {"user": {"displayName": "Ochi"}},
        "parentReference": {"driveId": "DRIVE01"},
    }


def file_item(item_id, name, size=126976):
    return {
        "id": item_id, "name": name,
        "file": {"mimeType": "application/octet-stream"},
        "size": size,
        "webUrl": f"https://x/sites/S/Docs/{name}",
        "lastModifiedDateTime": "2026-08-21T05:00:00Z",
        "createdBy": {"user": {"displayName": "Saji"}},
        "parentReference": {"driveId": "DRIVE01"},
    }


CFG = dict(dsm.DEFAULT_CFG)


def mk_root(**kwargs):
    base = dict(source="SharePoint", title="03. Hardware",
                doc_type=dsm.FOLDER_TYPE_LABEL, is_folder=True,
                site="Japan Design Center", site_url="https://x/sites/S",
                url="https://x/sites/S/Docs/03Hardware", last_modified="2026-08-21")
    base.update(kwargs)
    return dsm.SearchResult(**base)


def make_router(tree, root_item=None, fail_on=None):
    """item_id → 子要素の一覧 という辞書から、Graphの代わりを作る。

    tree の値がリストのリストの場合は「ページ送りされる応答」を意味する。
    fail_on に item_id を渡すと、そのフォルダの取得だけ失敗させられる。
    """
    calls = []

    def children_of(item_id, page):
        pages = tree.get(item_id, [])
        if pages and not isinstance(pages[0], list):
            pages = [pages]
        if page >= len(pages):
            return {"value": []}
        body = {"value": pages[page]}
        if page + 1 < len(pages):
            body["@odata.nextLink"] = (f"https://graph/next?item={item_id}"
                                       f"&page={page + 1}")
        return body

    def fake_get(url, headers=None, timeout=None, **kwargs):
        calls.append(url)
        if url.startswith("https://graph/next?"):
            query = url.split("?", 1)[1]
            parts = dict(p.split("=", 1) for p in query.split("&"))
            return FakeResp(200, children_of(parts["item"], int(parts["page"])))
        if "/driveItem" in url and "/children" not in url:
            return FakeResp(200, root_item or folder_item("ROOT01", "03. Hardware"))
        if "/items/" in url and "/children" in url:
            item_id = url.split("/items/", 1)[1].split("/children", 1)[0]
            if fail_on and item_id == fail_on:
                return FakeResp(403, None, "Access denied")
            return FakeResp(200, children_of(item_id, 0))
        return FakeResp(404, None, "unexpected url: " + url)

    return fake_get, calls


def run_explore(tree, roots=None, root_item=None, fail_on=None):
    """探索本体を、その場で（スレッドを使わず）実行して進捗辞書を返す。"""
    fake_get, calls = make_router(tree, root_item=root_item, fail_on=fail_on)
    orig = dsm.http_req.get
    dsm.http_req.get = fake_get
    job_id = "testjob"
    dsm._explore_jobs[job_id] = {"done": False, "current": "", "scanned": 0,
                                 "found": 0, "errors": []}
    try:
        dsm._explore_run(job_id, roots or [mk_root()], "dummy-token", 30)
    finally:
        dsm.http_req.get = orig
    return dsm._explore_jobs.pop(job_id), calls


# ── H1 Graphの応答 → SearchResult への写し取り ─────────────────
print("\n[H1] driveItem を SearchResult に写す（_explore_child_to_result）")
root = mk_root()
row_folder = dsm._explore_child_to_result(
    folder_item("SUB01", "01. Validation_Plan", 3), root, "ROOT01", "DRIVE01",
    1, "03. Hardware")
check("フォルダはis_folder=True・種別はフォルダ",
      row_folder.is_folder is True and row_folder.doc_type == dsm.FOLDER_TYPE_LABEL,
      (row_folder.is_folder, row_folder.doc_type))
check("フォルダのサイズは0（Graphの合計値を出すと誤解を招くため）",
      row_folder.size == 0, row_folder.size)
check("Graphの申告する中の件数を持つ", row_folder.child_count == 3, row_folder.child_count)
check("親のitem_idを持つ（ツリーの組み立てに使う）",
      row_folder.parent_item_id == "ROOT01", row_folder.parent_item_id)
check("深さを持つ", row_folder.depth == 1, row_folder.depth)
check("起点フォルダからの場所を持つ",
      row_folder.path_text == "03. Hardware", row_folder.path_text)
check("サイト情報は起点フォルダから引き継ぐ",
      row_folder.site == "Japan Design Center", row_folder.site)

row_file = dsm._explore_child_to_result(
    file_item("FILE01", "Validation_Plan_Rev3.docx"), root, "SUB01", "DRIVE01",
    2, "03. Hardware/01. Validation_Plan")
check("ファイルは拡張子が種別になる", row_file.doc_type == "docx", row_file.doc_type)
check("ファイルのサイズを持つ", row_file.size == 126976, row_file.size)
check("作成者を持つ", row_file.author == "Saji", row_file.author)
check("最終更新日はJSTのYYYY-MM-DDに整形される",
      row_file.last_modified == "2026-08-21", row_file.last_modified)
check("webUrlがurlになる（ファイル名クリックで開けるようにするため）",
      row_file.url.endswith("Validation_Plan_Rev3.docx"), row_file.url)
check("名前が無くても落ちない",
      dsm._explore_child_to_result({"file": {}}, root, "P", "D", 1, "").title
      == "(名前なし)")


# ── H2 ページ送りを最後まで追う ────────────────────────────────
print("\n[H2] ページ送り（@odata.nextLink）")
tree = {
    "ROOT01": [[file_item(f"F{i}", f"a{i}.docx") for i in range(3)],
               [file_item(f"G{i}", f"b{i}.docx") for i in range(2)]],
}
job, calls = run_explore(tree)
check("2ページ目まで取り切る（3件+2件=5件）", job["found"] == 5, job["found"])
check("nextLinkのURLをそのまま使う（$top/$selectを付け直さない）",
      any(u.startswith("https://graph/next?") for u in calls), calls)
check("$select を明示している（file/folderの判定を欠かさないため）",
      any("$select=" in u for u in calls))


# ── H3 再帰・深さの上限・件数の上限 ────────────────────────────
print("\n[H3] 再帰と上限（深さ5階層 / 2000件）")
deep = {}
for level in range(1, 9):
    deep[f"L{level - 1}" if level > 1 else "ROOT01"] = [
        folder_item(f"L{level}", f"level{level}")]
job, calls = run_explore(deep)
depths = [r["depth"] for r in job["results"]]
check("深さの上限で止まる（起点0＋5階層＝最大深さ5）",
      max(depths) == dsm.EXPLORE_MAX_DEPTH, depths)
check("上限に当たったことを理由として残す",
      "深さの上限" in job["stopped"], job["stopped"])
check("上限より深いフォルダは開きに行かない",
      len([u for u in calls if "/items/" in u]) == dsm.EXPLORE_MAX_DEPTH,
      [u for u in calls if "/items/" in u])

wide = {"ROOT01": [file_item(f"F{i}", f"f{i}.docx") for i in range(20)]}
orig_max = dsm.EXPLORE_MAX_ITEMS
try:
    dsm.EXPLORE_MAX_ITEMS = 5
    job, _calls = run_explore(wide)
    check("件数の上限で打ち切る", job["found"] == 5, job["found"])
    check("打ち切った理由を残す", "上限の 5 件" in job["stopped"], job["stopped"])
finally:
    dsm.EXPLORE_MAX_ITEMS = orig_max

mixed = {
    "ROOT01": [folder_item("SUB01", "01. Validation_Plan"),
               file_item("FILE01", "Overview.docx")],
    "SUB01": [file_item("FILE02", "Plan_Rev3.pdf")],
}
job, _calls = run_explore(mixed)
check("起点フォルダ自身も1行として含む（ツリーの根になる）",
      any(r["depth"] == 0 and r["parent_item_id"] == "" for r in job["results"]),
      [(r["title"], r["depth"]) for r in job["results"]])
check("起点は検出件数に数えない（見つけたものだけを数える）",
      job["found"] == 3 and len(job["results"]) == 4,
      (job["found"], len(job["results"])))
check("フォルダ数とファイル数を分けて数える",
      job["folders"] == 2 and job["files"] == 2, (job["folders"], job["files"]))
check("走査したフォルダ数を数える（起点＋SUB01）", job["scanned"] == 2, job["scanned"])
check("孫の場所は親のパスを連ねたものになる",
      any(r["path_text"] == "03. Hardware/01. Validation_Plan"
          for r in job["results"]),
      [r["path_text"] for r in job["results"]])

job, _calls = run_explore(mixed, fail_on="SUB01")
check("途中のフォルダが取得できなくても、他は最後まで探索する",
      job["done"] is True and job["found"] == 2, (job["done"], job["found"]))
check("取得できなかったフォルダは理由付きで報告する",
      len(job["errors"]) == 1 and "01. Validation_Plan" in job["errors"][0],
      job["errors"])

job, _calls = run_explore({}, root_item={"id": "", "parentReference": {}})
check("起点フォルダを特定できないときは、その旨を報告して終わる",
      job["done"] is True and job["errors"] and "起点" in job["errors"][0],
      job["errors"])
check("起点の特定に失敗しても、検出件数が負にならない",
      job["found"] == 0 and job["folders"] == 0 and job["files"] == 0,
      (job["found"], job["folders"], job["files"]))


# ── H4 API（/api/explore・/api/explore_status） ────────────────
print("\n[H4] API の入口（/api/explore・/api/explore_status）")
dsm._cfg = CFG
dsm._auth = DummyAuth()
client = dsm.flask_app.test_client()

r = client.post("/api/explore", json={})
check("idx未指定は400", r.status_code == 400, r.status_code)

dsm._last_results = [
    dsm.SearchResult(source="SharePoint", title="notafolder", doc_type="docx",
                     url="https://x/sites/S/Docs/a.docx"),
    dsm.SearchResult(source="Enovia", title="EnoviaFolder", is_folder=True,
                     url="https://x/enovia/folder"),
    mk_root(),
]
r = client.post("/api/explore", json={"idx": "0"})
check("フォルダでない行を指定すると400",
      r.status_code == 400 and "フォルダ" in r.get_json()["error"], r.get_json())
r = client.post("/api/explore", json={"idx": "1"})
check("Enoviaのフォルダは対象外（SharePointのみ、というご指示どおり）",
      r.status_code == 400, r.get_json())
r = client.post("/api/explore", json={"idx": "999"})
check("範囲外の索引は400", r.status_code == 400, r.status_code)

r = client.get("/api/explore_status?job=nosuchjob")
check("知らないジョブIDは404", r.status_code == 404, r.status_code)

fake_get, _calls = make_router(mixed)
orig_get = dsm.http_req.get
dsm.http_req.get = fake_get
try:
    r = client.post("/api/explore", json={"idx": "2"})
    body = r.get_json()
    check("探索を開始するとジョブIDが返る", r.status_code == 200 and body.get("job"), body)
    check("起点フォルダ名を返す（何を探索しているか画面に出すため）",
          body.get("roots") == ["03. Hardware"], body.get("roots"))

    status = {}
    for _ in range(100):
        status = client.get("/api/explore_status?job=" + body["job"]).get_json()
        if status.get("done"):
            break
        time.sleep(0.05)
    check("進捗を問い合わせると、やがて完了になる", status.get("done") is True, status)
    check("完了時に結果そのものを返す（別途取りに行かせない）",
          len(status.get("results") or []) == 4, len(status.get("results") or []))
finally:
    dsm.http_req.get = orig_get


# ── H5 探索結果に対する既存機能（ZIP取得・出力・要約） ──────────
print("\n[H5] 探索結果への既存機能の受け渡し（scope=explore）")
search_rows = [dsm.SearchResult(source="SharePoint", title="検索側",
                                url="https://x/sites/S/Docs/search.docx",
                                doc_type="docx")]
explore_rows = [
    dsm.SearchResult(source="SharePoint", title="探索側", doc_type="docx",
                     url="https://x/sites/S/Docs/explored.docx",
                     item_id="FILE01", root_label="03. Hardware"),
    dsm.SearchResult(source="SharePoint", title="探索フォルダ", is_folder=True,
                     doc_type=dsm.FOLDER_TYPE_LABEL,
                     url="https://x/sites/S/Docs/sub", item_id="SUB01",
                     root_label="03. Hardware"),
]
dsm._last_results = list(search_rows)
dsm._explore_results = list(explore_rows)

check("scope未指定は検索結果から選ぶ（従来どおり）",
      dsm._pick_results("0")[0].title == "検索側")
check("scope=exploreは探索結果から選ぶ",
      dsm._pick_results("0", "explore")[0].title == "探索側")
check("探索結果と検索結果は別々に保たれる（索引も別系統）",
      dsm._pick_results("1", "explore")[0].title == "探索フォルダ")

r = client.get("/api/export?format=csv&scope=explore&idx=0")
check("Excel/CSV出力が探索結果でも動く", r.status_code == 200, r.status_code)

downloaded = {}


def fake_download(token, result, timeout):
    downloaded["title"] = result.title
    return "explored.docx", b"dummy"


orig_download = dsm._download_one
dsm._download_one = fake_download
try:
    r = client.get("/api/download?scope=explore&idx=0")
    check("ZIP取得が探索結果でも動く（探索側の行が取得される）",
          r.status_code == 200 and downloaded.get("title") == "探索側",
          (r.status_code, downloaded))
finally:
    dsm._download_one = orig_download

r = client.post("/api/summarize", json={"idx": "1", "scope": "explore"})
check("探索結果のフォルダ行は要約できない（理由付きで400）",
      r.status_code == 400 and "フォルダ" in r.get_json()["error"], r.get_json())


# ── H6 .pdf の要約対応 ────────────────────────────────────────
print("\n[H6] .pdf の要約対応（越智さん承認済みの⑤）")
check("対応形式に pdf が入っている", "pdf" in dsm.SUMMARIZABLE_EXTENSIONS,
      dsm.SUMMARIZABLE_EXTENSIONS)
check("pdfはPDF用の抽出関数へ振り分けられる",
      dsm._extract_text_for_summary.__code__.co_names.count("_extract_pdf_text") == 1
      or "_extract_pdf_text" in dsm._extract_text_for_summary.__code__.co_names)
check("PDF抽出関数が存在する", callable(dsm._extract_pdf_text))
check("PyMuPDFは遅延importにする（未導入でも他機能に影響させない）",
      "fitz" in dsm._extract_pdf_text.__code__.co_names)


# ── H7 版の入れ替わりを妨げないための対策 ──────────────────────
print("\n[H7] 古い版が出続ける事故への対策")
resp = client.get("/")
check("画面HTMLはキャッシュさせない（no-store）",
      "no-store" in (resp.headers.get("Cache-Control") or ""),
      resp.headers.get("Cache-Control"))
check("使用中でないポートは「使用中」と判定しない",
      dsm._port_in_use(59999) is False)

import socket as _socket  # noqa: E402
listener = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
listener.bind(("127.0.0.1", 0))
listener.listen(1)
try:
    check("使用中のポートは検出できる（二重起動の防止）",
          dsm._port_in_use(listener.getsockname()[1]) is True)
finally:
    listener.close()


# ── H8 画面（HTML/JS）に必要な部品があるか ────────────────────
print("\n[H8] 画面側の部品")
html = client.get("/").get_data(as_text=True)
for label, needle in [
    ("フォルダ探索タブがある", 'data-target="explore"'),
    ("探索タブは既定で隠れている（探索するまで出さない）",
     'id="tabExplore" data-target="explore" hidden'),
    ("探索ボタンがある", 'id="btnExplore"'),
    ("ツリー表示・一覧表示の切替がある", 'id="btnTreeView"'),
    ("一覧表示ボタンがある", 'id="btnFlatView"'),
    ("SharePointの列に「探索」列がある", '{ key: "__explore"'),
    ("探索結果用の列構成がある", "  explore: ["),
    ("サイズ列がある", '{ key: "size"'),
    ("場所（パス）列がある", '{ key: "path_text"'),
    ("ツリーの並び順を組み立てる関数がある", "function buildTreeOrder("),
    ("ツリー表示かどうかの判定がある", "function isTreeView("),
    ("探索の進捗を問い合わせる処理がある", "function pollExplore("),
    ("探索結果へ切り替える処理がある", "function enterExploreView("),
    ("ZIP取得にscopeを渡している", '"/api/download?scope="'),
    ("出力にscopeを渡している", '"&scope=" + (isExploreView()'),
    ("サイズは数値として並べ替える", 'if (key === "size")'),
    ("ツリー表示では並べ替えを掛けない", "if (isTreeView()) {"),
    ("ツリー表示でも種別だけは絞り込める（祖先フォルダを残す）",
     'if (isFiltered("doc_type")) {'),
    ("種別の絞り込みの見出しはツリー表示でも出す",
     'var treeFilterable = isTreeView() && col.key === "doc_type";'),
    ("要約の対応形式にpdfが入っている",
     '["docx", "pptx", "xlsx", "xlsm", "pdf"]'),
]:
    check(label, needle in html, needle)

check("探索の上限が画面の説明文と一致している（5階層・2000件）",
      dsm.EXPLORE_MAX_DEPTH == 5 and dsm.EXPLORE_MAX_ITEMS == 2000
      and "5階層" in html and "2000件" in html)

check.finish()
