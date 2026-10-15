# -*- coding: utf-8 -*-
"""フォルダ探索の深さ指定と、▶で次の階層を読み込むツリー — v20260925_04 で追加

document_search_manager: 越智さんのご要望（2026-09-25）
  - 「選択フォルダを探索」で深さを Lv1〜Lv4 から選べる（標準Lv2）。
    チェックしたフォルダがLv0、そのすぐ下がLv1、もう一つ下がLv2。
  - 指定した深さまでを一括で表示し、その先のフォルダは▶で開いたときに
    次の1階層を読み込む。
  - ツリーの開閉記号を大きく見やすくする。
最重要の確認点は、▶で足した行の番号が画面とサーバーでずれないこと
（ずれると、ZIP・Excel・要約で別のファイルが選ばれる）。
ネットワークには一切アクセスせず、http_req.get をスタブに差し替えて検証する。
実行: python tests/test_30_explore_level.py
（まとめて実行する場合は python tests/run_tests.py）
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import dsm, DummyAuth  # noqa: E402

ok, ng = 0, 0


def check(label, cond, detail=""):
    global ok, ng
    if cond:
        ok += 1
        print(f"  OK   {label}")
    else:
        ng += 1
        print(f"  NG   {label}  {detail}")


CFG = dict(dsm.DEFAULT_CFG)
_ORIG = {"get": dsm.http_req.get, "run": dsm._explore_run, "state": dsm.STATE_PATH,
         "cfg": dsm._cfg, "auth": dsm._auth, "last": dsm._last_results,
         "explore": dsm._explore_results}


class FakeResp:
    def __init__(self, status, body=None, text=""):
        self.status_code, self._body, self.text = status, body, text

    def json(self):
        return self._body


def folder_item(item_id, name, child_count=1):
    return {"id": item_id, "name": name, "folder": {"childCount": child_count},
            "webUrl": f"https://x/sites/S/Docs/{name}",
            "lastModifiedDateTime": "2026-09-25T01:00:00Z",
            "createdBy": {"user": {"displayName": "Ochi"}}}


def file_item(item_id, name):
    return {"id": item_id, "name": name, "file": {}, "size": 1024,
            "webUrl": f"https://x/sites/S/Docs/{name}",
            "lastModifiedDateTime": "2026-09-25T01:00:00Z",
            "createdBy": {"user": {"displayName": "Saji"}}}


def router(tree, calls):
    """/items/{id}/children と起点の /driveItem に、tree の中身で答える。"""
    def fake_get(url, **kw):
        calls.append(url)
        if "/driveItem" in url and "/children" not in url:
            return FakeResp(200, {"id": "ROOT", "parentReference": {"driveId": "D1"},
                                  "folder": {"childCount": 1}, "name": "P010024_Lorry"})
        if "/items/" in url and "/children" in url:
            item_id = url.split("/items/", 1)[1].split("/children", 1)[0]
            if item_id == "BROKEN":
                return FakeResp(403, None, "Access denied")
            return FakeResp(200, {"value": tree.get(item_id, [])})
        return FakeResp(404, None, "unexpected: " + url)
    return fake_get


def mk_root():
    return dsm.SearchResult(source="SharePoint", title="P010024_Lorry",
                            doc_type=dsm.FOLDER_TYPE_LABEL, is_folder=True,
                            site="P010024_Lorry", site_url="https://x/sites/S",
                            url="https://x/sites/S/Docs/P010024_Lorry")


# 起点 → DBH → PO#1 → Mask → deep.docx という一本道＋各階層にファイル1つ
TREE = {
    "ROOT": [folder_item("DBH", "DBH", 2), file_item("F0", "plan.xlsx")],
    "DBH": [folder_item("PO1", "PO#1", 2), file_item("F1", "po.pdf")],
    "PO1": [folder_item("MASK", "Mask", 1), file_item("F2", "mask.xlsx")],
    "MASK": [folder_item("EMPTY", "Empty", 0), file_item("F3", "deep.docx")],
    "EMPTY": [],
}


def run(level):
    calls = []
    dsm.http_req.get = router(TREE, calls)
    dsm._explore_jobs["t"] = {"done": False}
    dsm._explore_run("t", [mk_root()], "tok", 30, level)
    return dsm._explore_jobs.pop("t"), calls


try:
    # ── T1: 深さの検査 ──────────────────────────────────────
    print("\n[T1] _explore_level（深さの検査）")
    L = dsm._explore_level
    check("Lv1〜4はそのまま", [L(1), L(2), L(3), L(4)] == [1, 2, 3, 4])
    check("文字の '3' も受け付ける", L("3") == 3)
    check("範囲外・空・文字列はすべて標準のLv2", [L(0), L(5), L(None), L("abc"), L(-1)] == [2] * 5)
    check("標準はLv2", dsm.EXPLORE_DEFAULT_LEVEL == 2 and dsm.EXPLORE_LEVELS == (1, 2, 3, 4))

    # ── T2: 指定Lvまで一括で取る ─────────────────────────────
    print("\n[T2] _explore_run（指定したLvまで取り、その先は取らない）")
    for level, expect_titles, expect_unloaded in (
            (1, {"DBH", "plan.xlsx"}, 1),
            (2, {"DBH", "plan.xlsx", "PO#1", "po.pdf"}, 1),
            (3, {"DBH", "plan.xlsx", "PO#1", "po.pdf", "Mask", "mask.xlsx"}, 1),
            (4, {"DBH", "plan.xlsx", "PO#1", "po.pdf", "Mask", "mask.xlsx",
                 "Empty", "deep.docx"}, 0)):
        job, calls = run(level)
        rows = job["results"]
        titles = {r["title"] for r in rows if r["depth"] > 0}
        check(f"Lv{level}: Lv{level}までの項目だけが並ぶ", titles == expect_titles, titles)
        check(f"Lv{level}: 最も深い行の深さは{level}",
              max(r["depth"] for r in rows) == level, [r["depth"] for r in rows])
        listed = [c for c in calls if "/children" in c]
        check(f"Lv{level}: 中身を取りに行くのはLv{level - 1}までのフォルダだけ（{level}回）",
              len(listed) == level, listed)
        check(f"Lv{level}: 未読込のフォルダ数を返す（中身0件のフォルダは数えない）",
              job.get("unloaded") == expect_unloaded and job.get("level") == level,
              (job.get("unloaded"), job.get("level")))
        check(f"Lv{level}: 深さに達しても打ち切り扱いにしない", job.get("stopped") == "")

    # ── T3: /api/explore が深さを受け取る ────────────────────
    print("\n[T3] /api/explore（深さを受け取ってジョブに渡す）")
    dsm._cfg = CFG
    dsm._auth = DummyAuth()
    client = dsm.flask_app.test_client()
    dsm._last_results = [mk_root()]
    got = []
    dsm._explore_run = lambda job_id, roots, token, timeout, level=None: got.append(level)
    body = client.post("/api/explore", json={"idx": "0", "level": 3}).get_json()
    check("指定したLvでジョブを始める", body.get("level") == 3, body)
    body = client.post("/api/explore", json={"idx": "0", "level": 9}).get_json()
    check("範囲外のLvは標準のLv2にする", body.get("level") == 2, body)
    body = client.post("/api/explore", json={"idx": "0"}).get_json()
    check("Lvの指定が無ければ標準のLv2", body.get("level") == 2, body)
    import time as _t
    _t.sleep(0.2)   # 探索スレッド（スタブ）が値を記録するのを待つ
    check("ジョブにも同じLvが渡っている", got[:3] == [3, 2, 2], got)
    dsm._explore_run = _ORIG["run"]

    # ── T4: ▶で次の階層を読み込む ───────────────────────────
    print("\n[T4] /api/explore_children（▶で次の1階層を読み込む）")
    job, _ = run(2)
    dsm._explore_results = [dsm.SearchResult(**{k: v for k, v in r.items()})
                            for r in job["results"]]
    before = len(dsm._explore_results)
    po1 = next(r for r in dsm._explore_results if r.title == "PO#1")
    calls = []
    dsm.http_req.get = router(TREE, calls)
    body = client.post("/api/explore_children",
                       json={"item_id": po1.item_id, "drive_id": po1.drive_id}).get_json()
    check("未読込のフォルダを開くと、中身を足す", body.get("added") is True, body)
    check("足し始めた位置は、足す前のサーバー側の行数（画面はこれと照合する）",
          body.get("start") == before, (body.get("start"), before))
    check("サーバー側の探索結果の末尾に、同じ順で足している",
          [r.title for r in dsm._explore_results[before:]] == ["Mask", "mask.xlsx"]
          and [r["title"] for r in body["rows"]] == ["Mask", "mask.xlsx"],
          [r.title for r in dsm._explore_results[before:]])
    new = body["rows"]
    check("足した行の深さは親＋1（Lv3）", all(r["depth"] == po1.depth + 1 == 3 for r in new),
          [r["depth"] for r in new])
    check("足した行の親は、開いたフォルダ", all(r["parent_item_id"] == po1.item_id for r in new))
    check("場所の表記は、親の場所＋親フォルダ名",
          new[0]["path_text"] == f"{po1.path_text}/{po1.title}", new[0]["path_text"])
    check("足したフォルダも、その先を▶で読めるよう中の件数を持つ",
          new[0]["is_folder"] and new[0]["child_count"] == 1, new[0])
    check("Graphへの呼び出しは、そのフォルダの中身1回だけ",
          len([c for c in calls if "/children" in c]) == 1 and "/items/PO1/children" in calls[-1],
          calls)

    idx_new = str(before)
    picked = dsm._pick_results(idx_new, "explore")
    check("足した行の番号で、ZIP・Excelの対象として正しい行が選ばれる",
          len(picked) == 1 and picked[0].title == "Mask", [p.title for p in picked])

    calls.clear()
    body = client.post("/api/explore_children",
                       json={"item_id": po1.item_id, "drive_id": po1.drive_id}).get_json()
    check("同じフォルダを2回開いても足さない（既存の行の番号を返す）",
          body.get("added") is False and body.get("indices") == [before, before + 1]
          and len(dsm._explore_results) == before + 2, body)
    check("2回目はGraphを呼ばない", not calls, calls)

    mask = next(r for r in dsm._explore_results if r.title == "Mask")
    client.post("/api/explore_children", json={"item_id": mask.item_id, "drive_id": mask.drive_id})
    empty = next(r for r in dsm._explore_results if r.title == "Empty")
    body = client.post("/api/explore_children",
                       json={"item_id": empty.item_id, "drive_id": empty.drive_id}).get_json()
    check("何階層でも続けて開ける（Lv4→Lv5）",
          empty.depth == 4 and body.get("added") is True and body.get("rows") == [], body)

    resp = client.post("/api/explore_children", json={"item_id": "NOPE", "drive_id": "D1"})
    check("今の探索結果に無いフォルダは読み込まない（古い画面から押された場合）",
          resp.status_code == 409 and "やり直して" in resp.get_json().get("error", ""),
          resp.get_json())
    resp = client.post("/api/explore_children",
                       json={"item_id": po1.item_id, "drive_id": "OTHER"})
    check("ドライブが違えば別物として扱う（409）", resp.status_code == 409)
    f1 = next(r for r in dsm._explore_results if r.title == "po.pdf")
    resp = client.post("/api/explore_children", json={"item_id": f1.item_id, "drive_id": f1.drive_id})
    check("ファイルは開けない（409）", resp.status_code == 409)
    check("指定が空なら400",
          client.post("/api/explore_children", json={}).status_code == 400)

    broken = dsm.SearchResult(title="Broken", is_folder=True, item_id="BROKEN",
                              drive_id="D1", depth=2, child_count=3, source="SharePoint")
    dsm._explore_results.append(broken)
    n_before = len(dsm._explore_results)
    resp = client.post("/api/explore_children", json={"item_id": "BROKEN", "drive_id": "D1"})
    check("中身を取れなければ502と理由を返し、何も足さない",
          resp.status_code == 502 and "Broken" in resp.get_json().get("error", "")
          and len(dsm._explore_results) == n_before, resp.get_json())

    # ── T5: 深さの保存（次回起動時も使う） ────────────────────
    print("\n[T5] /api/state（深さを保存する）")
    dsm.STATE_PATH = Path(tempfile.mkdtemp()) / "session_state.json"
    client.post("/api/state", json={"keyword": "x", "explore_level": 3})
    st = json.loads(dsm.STATE_PATH.read_text(encoding="utf-8"))
    check("選んだLvを保存する", st.get("explore_level") == 3, st)
    client.post("/api/state", json={"keyword": "x", "explore_level": 7})
    st = json.loads(dsm.STATE_PATH.read_text(encoding="utf-8"))
    check("範囲外のLvは標準のLv2として保存する", st.get("explore_level") == 2, st)

    # ── T6: 画面 ────────────────────────────────────────────
    print("\n[T6] 画面（HTML/JS）")
    html = dsm.INDEX_HTML
    check("深さのプルダウンがあり、Lv1〜4で標準はLv2",
          'id="exploreLevel"' in html and html.count('<option value="') >= 4
          and '<option value="2" selected>深さ Lv2（標準）</option>' in html)
    check("プルダウンの表示は「選択フォルダを探索」ボタンと同じ条件",
          'document.getElementById("exploreLevel").hidden = btn.hidden;' in html)
    check("探索の開始時に、選んだLvを送る", "JSON.stringify({ idx: idx.join(\",\"), level: level })" in html)
    check("開閉の記号を大きくした（15px・押せる範囲24px）",
          "width: 24px; height: 24px;" in html and "font-size: 15px;" in html
          and "font-size: 10px;" not in html.split(".ttoggle {")[1].split("}")[0])
    check("▶は文字として描く指定（FE0E）を付ける（Windowsで絵文字にならないように）",
          'var TRI_CLOSED   = "\\u{25B6}\\u{FE0E}";' in html)
    check("未読込のフォルダは▶で読み込む（中の件数があり、まだ読んでいないもの）",
          'r.is_folder && !r._loaded && Number(r.child_count || 0) > 0' in html
          and "loadExploreChildren(r)" in html)
    check("足し始めた位置が画面の行数と一致しなければ足さない（番号ずれ防止）",
          "if (data.start !== exploreData.length) {" in html)
    check("同時に読み込むのは1つだけ（順番の入れ替わりによるずれを防ぐ）",
          "if (exploreLoadingId) {" in html)
    check("未読込・空のフォルダに注記を出す",
          '"件・未読込）"' in html and 'tnote = "（空）";' in html)
    check("深さは、キーワードが無くても復元する（キーワードの判定より前）",
          html.index('document.getElementById("exploreLevel").value = String(s.explore_level);')
          < html.index('if (!s || !s.keyword) { return; }'))
    check("深さを変えたら保存する",
          'getElementById("exploreLevel").addEventListener("change"' in html)

finally:
    dsm.http_req.get, dsm._explore_run = _ORIG["get"], _ORIG["run"]
    dsm.STATE_PATH, dsm._cfg, dsm._auth = _ORIG["state"], _ORIG["cfg"], _ORIG["auth"]
    dsm._last_results, dsm._explore_results = _ORIG["last"], _ORIG["explore"]


print(f"\n{'=' * 46}")
print(f"  成功 {ok} 件 / 失敗 {ng} 件")
print(f"{'=' * 46}")
sys.exit(1 if ng else 0)
