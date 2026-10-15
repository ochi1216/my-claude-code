# -*- coding: utf-8 -*-
"""フォルダ探索の事前診断（/api/explore_diag）

越智さんに承認いただいた「フォルダ探索ビュー」の実装に入る前に、
**現在の権限（Sites.Read.All のみ）でフォルダの子要素を取得できるか**を
実機で確かめるための診断機能のテスト。

/shares/{token}/driveItem は既存のNexus列取得で実績があるが、/children が
同じ権限で通るかは未確認のため、推測で本実装に入らずここで事実を確定させる、
という位置づけの機能（DESIGN_NOTES参照）。

ネットワークには一切アクセスせず、http_req.get をスタブに差し替えて検証する。
実行: python tests/test_18_explore_diag.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import dsm, DummyAuth  # noqa: E402

import json

ok, ng = 0, 0


def check(label, cond, detail=""):
    global ok, ng
    if cond:
        ok += 1
        print(f"  OK   {label}")
    else:
        ng += 1
        print(f"  NG   {label}  {detail}")


class FakeResp:
    def __init__(self, code, payload=None, text=""):
        self.status_code = code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


# ── 応答の見本（実際のGraphの形に合わせたダミー） ──────────────
ROOT_ITEM = {
    "id": "ROOT01",
    "name": "03. Hardware",
    "parentReference": {"driveId": "DRIVE01"},
}
CHILD_FOLDER = {
    "id": "SUB01", "name": "01. Validation_Plan",
    "folder": {"childCount": 3},
    "webUrl": "https://x/sites/S/Docs/01",
    "lastModifiedDateTime": "2026-08-21T05:00:00Z",
    "createdBy": {"user": {"displayName": "Ochi"}},
    "parentReference": {"driveId": "DRIVE01", "id": "ROOT01"},
}
CHILD_FILE = {
    "id": "FILE01", "name": "Validation_Plan_Rev3.docx",
    "file": {"mimeType": "application/vnd..."},
    "size": 126976,
    "webUrl": "https://x/sites/S/Docs/01/Validation_Plan_Rev3.docx",
    "lastModifiedDateTime": "2026-08-21T05:00:00Z",
    "createdBy": {"user": {"displayName": "Ochi"}},
    "parentReference": {"driveId": "DRIVE01", "id": "ROOT01"},
}
GRANDCHILD = {"id": "FILE02", "name": "MRA2.0_Notes.docx", "file": {}, "size": 4096}


def make_router(step2=None, step3=None, step1=None):
    """URLの形で応答を振り分けるスタブを作る。呼ばれたURLも記録する。"""
    calls = []

    def fake_get(url, headers=None, timeout=None, **kwargs):
        calls.append(url)
        if "/driveItem/children" in url:
            return step2 if step2 is not None else FakeResp(
                200, {"value": [CHILD_FOLDER, CHILD_FILE]})
        if "/items/" in url and "/children" in url:
            return step3 if step3 is not None else FakeResp(200, {"value": [GRANDCHILD]})
        if "/driveItem" in url:
            return step1 if step1 is not None else FakeResp(200, ROOT_ITEM)
        return FakeResp(404, None, "unexpected url")

    return fake_get, calls


CFG = dict(dsm.DEFAULT_CFG)


def mk(**kwargs):
    base = dict(source="SharePoint", title="03. Hardware",
                doc_type=dsm.FOLDER_TYPE_LABEL, is_folder=True,
                url="https://x/sites/S/Docs/03Hardware", last_modified="2026-08-21")
    base.update(kwargs)
    return dsm.SearchResult(**base)


# ── H1 _explore_child_label（見本の1行表示） ────────────────────
print("\n[H1] 子要素の見本表示（_explore_child_label）")
check("フォルダは📁と件数が出る",
      dsm._explore_child_label(CHILD_FOLDER) == "📁 01. Validation_Plan（中に 3 件）",
      dsm._explore_child_label(CHILD_FOLDER))
check("ファイルは📄とサイズが出る（KB）",
      dsm._explore_child_label(CHILD_FILE) == "📄 Validation_Plan_Rev3.docx（124 KB）",
      dsm._explore_child_label(CHILD_FILE))
check("MB単位でも表示できる",
      "MB" in dsm._explore_child_label({"name": "big.pptx", "file": {}, "size": 2516582}),
      dsm._explore_child_label({"name": "big.pptx", "file": {}, "size": 2516582}))
check("サイズが無くても落ちない",
      dsm._explore_child_label({"name": "x.docx", "file": {}}) == "📄 x.docx")
check("名前が無くても落ちない",
      "(名前なし)" in dsm._explore_child_label({"file": {}}))


# ── H2 _explore_diagnose（3段階の呼び出し） ────────────────────
print("\n[H2] 診断の本体（_explore_diagnose）")

orig_get = dsm.http_req.get
try:
    fake_get, calls = make_router()
    dsm.http_req.get = fake_get
    report = dsm._explore_diagnose("dummy-token", mk(), 30)

    check("3段階すべてを報告する", len(report["rows"]) == 3, len(report["rows"]))
    check("①起点フォルダの取得に成功", report["rows"][0]["ok"] is True, report["rows"][0])
    check("①でidとdriveIdを読み取る",
          "ROOT01" in report["rows"][0]["detail"]
          and "DRIVE01" in report["rows"][0]["detail"], report["rows"][0])
    check("②直下の子要素の取得に成功", report["rows"][1]["ok"] is True, report["rows"][1])
    check("②で取得件数を報告する", "2 件" in report["rows"][1]["detail"], report["rows"][1])
    check("③さらに1階層下の取得に成功（＝再帰できる）",
          report["rows"][2]["ok"] is True, report["rows"][2])
    check("③は子フォルダのidを使って /drives/{driveId}/items/{itemId}/children を呼ぶ",
          any("/drives/DRIVE01/items/SUB01/children" in u for u in calls), calls)
    check("すべて成功なら判定はOK", report["verdict"]["ok"] is True, report["verdict"])
    check("判定に「実装できます」と明示される",
          "実装できます" in report["verdict"]["message"], report["verdict"])

    present = {f["key"]: f["present"] for f in report["fields"]}
    check("必要な項目の有無を報告する（name/size等）",
          present.get("name") is True and present.get("webUrl") is True, present)
    check("見本の子要素が返る（最大5件）",
          len(report["samples"]) == 2 and "📁" in report["samples"][0], report["samples"])
    check("対象フォルダのタイトルを返す",
          report["target"]["title"] == "03. Hardware", report["target"])

    # ── ②が権限エラーになる場合（本実装できないケース） ──
    fake_get, calls = make_router(step2=FakeResp(403, None, "Access denied"))
    dsm.http_req.get = fake_get
    denied = dsm._explore_diagnose("dummy-token", mk(), 30)
    check("②が403なら判定はNG", denied["verdict"]["ok"] is False, denied["verdict"])
    check("②が403なら理由が分かる文言になる",
          "権限" in denied["verdict"]["message"], denied["verdict"])
    check("②が403でもHTTPステータスを報告する",
          denied["rows"][1]["status"] == 403, denied["rows"][1])
    check("②が失敗したら③は実行しない（無駄打ちしない）",
          denied["rows"][2].get("skipped") is True, denied["rows"][2])

    # ── ③だけ失敗する場合（1階層目は開けるが再帰できない） ──
    fake_get, calls = make_router(step3=FakeResp(403, None, "Access denied"))
    dsm.http_req.get = fake_get
    shallow = dsm._explore_diagnose("dummy-token", mk(), 30)
    check("③だけ失敗なら判定はNG", shallow["verdict"]["ok"] is False, shallow["verdict"])
    check("③だけ失敗なら「その先へ潜れませんでした」と伝える",
          "潜れません" in shallow["verdict"]["message"], shallow["verdict"])

    # ── 中にフォルダが無い場合（再帰は未確認のまま） ──
    fake_get, calls = make_router(step2=FakeResp(200, {"value": [CHILD_FILE]}))
    dsm.http_req.get = fake_get
    flat = dsm._explore_diagnose("dummy-token", mk(), 30)
    check("子フォルダが無ければ③はスキップされる",
          flat["rows"][2].get("skipped") is True, flat["rows"][2])
    check("その場合は「再帰は未確認」と正直に伝える（成功と断定しない）",
          flat["verdict"]["ok"] is True and "未確認" in flat["verdict"]["message"],
          flat["verdict"])
    check("③をスキップしたときは /items/ を呼んでいない",
          not any("/items/" in u for u in calls), calls)

    # ── ページングが必要な場合の注意喚起 ──
    fake_get, calls = make_router(step2=FakeResp(200, {
        "value": [CHILD_FOLDER, CHILD_FILE],
        "@odata.nextLink": "https://graph.microsoft.com/v1.0/next"}))
    dsm.http_req.get = fake_get
    paged = dsm._explore_diagnose("dummy-token", mk(), 30)
    check("続きがある場合はページングが必要だと報告する",
          "ページング" in paged["rows"][1]["detail"], paged["rows"][1])

    # ── 応答に項目が欠けている場合 ──
    fake_get, calls = make_router(step2=FakeResp(200, {"value": [{"name": "x.docx"}]}))
    dsm.http_req.get = fake_get
    thin = dsm._explore_diagnose("dummy-token", mk(), 30)
    thin_present = {f["key"]: f["present"] for f in thin["fields"]}
    check("欠けている項目はpresent=falseとして報告される",
          thin_present.get("name") is True and thin_present.get("size") is False,
          thin_present)

    # ── 通信そのものが失敗する場合 ──
    def boom(url, headers=None, timeout=None, **kwargs):
        raise RuntimeError("接続できません")

    dsm.http_req.get = boom
    broken = dsm._explore_diagnose("dummy-token", mk(), 30)
    check("通信失敗でも例外を投げず報告に変える",
          broken["rows"][0]["ok"] is False and "接続できません" in broken["rows"][0]["message"],
          broken["rows"][0])
finally:
    dsm.http_req.get = orig_get


# ── H3 /api/explore_diag エンドポイント ────────────────────────
print("\n[H3] /api/explore_diag エンドポイント")

dsm._cfg = CFG
dsm._auth = DummyAuth()
mgr = dsm.SearchManager(CFG, DummyAuth())
rows = [
    dsm.SearchResult(source="SharePoint", title="a-file.docx", doc_type="docx",
                     url="https://x/sites/S/Docs/a.docx", rank=1),
    dsm.SearchResult(source="SharePoint", title="03. Hardware",
                     doc_type=dsm.FOLDER_TYPE_LABEL, is_folder=True,
                     url="https://x/sites/S/Docs/03Hardware", rank=2),
]
mgr.providers[dsm.TARGET_SHAREPOINT].search = lambda kw, mx: {
    "results": list(rows), "total": len(rows), "note": ""}
dsm._manager = mgr
client = dsm.flask_app.test_client()

orig_get = dsm.http_req.get
try:
    fake_get, calls = make_router()
    dsm.http_req.get = fake_get

    # 検索前は _last_results が空（他テストの影響を受けないよう明示的に空にする）
    with dsm._lock:
        dsm._last_results = []
    r = client.post("/api/explore_diag", json={})
    check("検索結果が無ければ400（何をすべきか案内する）",
          r.status_code == 400 and "検索" in r.get_json()["error"], r.get_json())

    search_resp = client.post(
        "/api/search", json={"keyword": "sample", "target": "sharepoint"}).get_json()
    titles = [x["title"] for x in search_resp["results"]]
    folder_idx = str(titles.index("03. Hardware"))
    file_idx = str(titles.index("a-file.docx"))

    r = client.post("/api/explore_diag", json={})
    data = r.get_json()
    check("idx省略時は最初のフォルダ行を自動で選ぶ",
          r.status_code == 200 and data["target"]["title"] == "03. Hardware", data)
    check("判定が返る", data["verdict"]["ok"] is True, data.get("verdict"))

    r = client.post("/api/explore_diag", json={"idx": folder_idx})
    check("idx指定でも動く",
          r.status_code == 200 and r.get_json()["target"]["title"] == "03. Hardware",
          r.get_json())

    r = client.post("/api/explore_diag", json={"idx": file_idx})
    check("フォルダ以外の行を指定したら400（理由付き）",
          r.status_code == 400 and "フォルダではありません" in r.get_json()["error"],
          r.get_json())

    r = client.post("/api/explore_diag", json={"idx": "999"})
    check("範囲外の索引は400", r.status_code == 400, r.status_code)

    # Enoviaのフォルダ行は対象外
    enovia_rows = [dsm.SearchResult(source="Enovia", title="E-Folder",
                                    doc_type=dsm.FOLDER_TYPE_LABEL, is_folder=True,
                                    url="https://x/enovia/folder", rank=1)]
    with dsm._lock:
        dsm._last_results = list(enovia_rows)
    r = client.post("/api/explore_diag", json={})
    check("Enoviaのフォルダは400（対象外と明示する）",
          r.status_code == 400 and "Enovia" in r.get_json()["error"], r.get_json())
finally:
    dsm.http_req.get = orig_get


# ── H4 画面表示 ────────────────────────────────────────────────
print("\n[H4] 画面表示")
html = dsm.flask_app.test_client().get("/").get_data(as_text=True)
check("フォルダ探索診断ボタンがある", 'id="btnExploreDiag"' in html)
check("/api/explore_diag を呼び出すfetchがある", '"/api/explore_diag"' in html)
check("実行中はボタンが無効化される",
      'getElementById("btnExploreDiag").disabled = busy' in html)
check("ボタンに用途の説明（title）が付いている",
      'id="btnExploreDiag" class="ghost" title=' in html)


print(f"\n{'=' * 46}\n  成功 {ok} 件 / 失敗 {ng} 件\n{'=' * 46}")
sys.exit(1 if ng else 0)
