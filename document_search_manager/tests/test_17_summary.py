# -*- coding: utf-8 -*-
"""文書の要約機能（AI・Gemini経由）── 要約機能 Phase A

依頼:「検索結果の内容を、①300字のExecutive Summary ②章立てと概要
③Japan Site Managerへの示唆、の3段階でAI要約したい」への対応。

対象は SharePoint / Nexus の .docx のみ（Phase Aのスコープ）。フォルダ・
Enovia・他形式（.pptx/.pdf/.xlsx）は対象外（設計議論で合意済み、
DESIGN_NOTES参照）。AI呼び出しは既存の翻訳ツール群と同じ共通モジュール
gemini_client.py を流用するが、本テストはネットワークには一切アクセスせず、
_generate_advanced 等をスタブに差し替えて検証する。

実行: python tests/test_17_summary.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import dsm, DummyAuth  # noqa: E402

import io
import json

try:
    from docx import Document
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

ok, ng = 0, 0


def check(label, cond, detail=""):
    global ok, ng
    if cond:
        ok += 1
        print(f"  OK   {label}")
    else:
        ng += 1
        print(f"  NG   {label}  {detail}")


def make_docx_bytes(paragraphs):
    """[(text, style_or_None), ...] からdocxのバイト列を作る。"""
    doc = Document()
    for text, style in paragraphs:
        if style:
            doc.add_paragraph(text, style=style)
        else:
            doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def fake_gemini_response(executive_summary="要約です。",
                         chapters=None, insights=None):
    chapters = chapters if chapters is not None else [
        {"title": "第1章 概要", "overview": "概要の説明。"},
    ]
    insights = insights if insights is not None else {
        "use": "活用点", "caution": "注意点", "questions": "問い",
    }
    data = {"executive_summary": executive_summary, "chapters": chapters,
            "insights": insights}
    return {"candidates": [{"content": {"parts": [
        {"text": json.dumps(data, ensure_ascii=False)}
    ]}}]}


CFG = dict(dsm.DEFAULT_CFG)


# ── G1 _summarizable_reason（Phase Aの対象を絞るガード） ────────
print("\n[G1] 要約可能かどうかの判定（_summarizable_reason）")


def mk(**kwargs):
    base = dict(source="SharePoint", title="Sample", doc_type="docx",
                url="https://x/sites/S/Docs/Sample.docx", last_modified="2026-09-01")
    base.update(kwargs)
    return dsm.SearchResult(**base)


ok_row = mk()
check("SharePointのdocxは要約可能", dsm._summarizable_reason(ok_row) == (True, ""))

folder_row = mk(is_folder=True, doc_type=dsm.FOLDER_TYPE_LABEL)
reason = dsm._summarizable_reason(folder_row)
check("フォルダは要約不可", reason[0] is False and "フォルダ" in reason[1], reason)

enovia_row = mk(source="Enovia", doc_type="docx")
reason = dsm._summarizable_reason(enovia_row)
check("Enoviaは要約不可（Phase A対象外）", reason[0] is False and "Enovia" in reason[1], reason)

no_url_row = mk(url="")
reason = dsm._summarizable_reason(no_url_row)
check("リンクが無い行は要約不可", reason[0] is False and "リンク" in reason[1], reason)

pptx_row = mk(doc_type="pptx")
reason = dsm._summarizable_reason(pptx_row)
check("docx以外（pptx）は現状要約不可", reason[0] is False and "pptx" in reason[1], reason)

nexus_row = mk(source="Nexus")
check("Nexusのdocxも要約可能（SharePointProvider系統を継承）",
      dsm._summarizable_reason(nexus_row) == (True, ""))


# ── G2 _extract_docx_text（本文抽出・見出し・切り詰め） ─────────
if HAS_DOCX:
    print("\n[G2] docx本文抽出（_extract_docx_text）")

    content = make_docx_bytes([
        ("第1章 はじめに", "Heading 1"),
        ("これは本文の1段落目です。", None),
        ("第2章 詳細", "Heading 1"),
        ("これは本文の2段落目です。", None),
        ("", None),   # 空段落は無視される
    ])
    text, truncated = dsm._extract_docx_text(content, max_chars=10000)
    check("見出し段落に # が付く", "# 第1章 はじめに" in text, text)
    check("本文段落はそのまま", "これは本文の1段落目です。" in text, text)
    check("空段落は含まれない（連続する空行にならない）",
          "\n\n\n" not in text, repr(text))
    check("十分に短ければ切り詰められない", truncated is False)

    long_content = make_docx_bytes([("あ" * 100, None)])
    long_text, long_truncated = dsm._extract_docx_text(long_content, max_chars=50)
    check("上限を超えると切り詰められる", long_truncated is True)
    check("切り詰め後の長さが上限以下", len(long_text) <= 50, len(long_text))

    empty_content = make_docx_bytes([("", None)])
    empty_text, _ = dsm._extract_docx_text(empty_content, max_chars=10000)
    check("本文が無ければ空文字", empty_text == "", repr(empty_text))
else:
    print("\n[G2] python-docx未インストールのためスキップ（他機能には影響しない設計）")


# ── G3 _generate_summary（Geminiレスポンスの解析） ──────────────
print("\n[G3] Geminiレスポンスの解析（_generate_summary）")

captured = {}


def stub_ok(payload, model=None):
    captured["payload"] = payload
    captured["model"] = model
    return fake_gemini_response()


orig_generate_advanced = dsm._generate_advanced
dsm._generate_advanced = stub_ok
try:
    result = dsm._generate_summary("Sample", "本文テキスト")
    check("executive_summaryを取得できる", result["executive_summary"] == "要約です。", result)
    check("chaptersを取得できる", result["chapters"][0]["title"] == "第1章 概要", result)
    check("insightsを取得できる", result["insights"]["use"] == "活用点", result)
    check("モデル名が渡される", captured["model"] == dsm.GEMINI_MODEL_NAME, captured.get("model"))
    check("responseMimeTypeがJSON指定", captured["payload"]["generationConfig"]["responseMimeType"]
          == "application/json")
    check("responseSchemaが渡される",
          "responseSchema" in captured["payload"]["generationConfig"])

    dsm._generate_advanced = lambda payload, model=None: {"candidates": []}
    try:
        dsm._generate_summary("Sample", "本文")
        check("candidatesが空なら例外", False, "例外が発生しなかった")
    except RuntimeError as e:
        check("candidatesが空なら例外", "応答" in str(e), str(e))

    dsm._generate_advanced = lambda payload, model=None: {
        "candidates": [{"content": {"parts": [{"text": "not-json"}]}}]}
    try:
        dsm._generate_summary("Sample", "本文")
        check("JSONでない応答は例外", False, "例外が発生しなかった")
    except RuntimeError as e:
        check("JSONでない応答は例外", "JSON" in str(e), str(e))

    dsm._generate_advanced = lambda payload, model=None: {"candidates": [{"content": {"parts": [
        {"text": json.dumps({"executive_summary": "x"})}
    ]}}]}
    try:
        dsm._generate_summary("Sample", "本文")
        check("必須キー欠落は例外", False, "例外が発生しなかった")
    except RuntimeError as e:
        check("必須キー欠落は例外", "chapters" in str(e), str(e))
finally:
    dsm._generate_advanced = orig_generate_advanced


# ── G4 /api/summarize エンドポイント ────────────────────────────
print("\n[G4] /api/summarize エンドポイント")


def idx_of(resp_json, title):
    """/api/search の応答から、タイトルで行の_idx相当（配列位置）を探す。

    SearchManager.search() は結果を (source, rank) でソートするため、
    渡した順序どおりに並ぶとは限らない（実際にEnovia行が先頭に来ることを
    本テスト作成時に確認済み）。そのためタイトルで引き直す。
    """
    for i, r in enumerate(resp_json["results"]):
        if r["title"] == title:
            return str(i)
    raise AssertionError(f"title={title} が見つかりません: {resp_json}")


dsm._cfg = CFG
dsm._auth = DummyAuth()
mgr = dsm.SearchManager(CFG, DummyAuth())
rows = [
    mk(title="DocA", url="https://x/sites/S/Docs/A.docx",
       last_modified="2026-09-01"),                                             # 要約可
    mk(title="FolderX", is_folder=True, doc_type=dsm.FOLDER_TYPE_LABEL,
       url="https://x/sites/S/Docs/Folder"),                                    # フォルダ
    mk(title="EnoviaDoc", source="Enovia", url="https://x/sites/S/Docs/B.docx"),  # Enovia
    mk(title="PptxOne", doc_type="pptx", url="https://x/sites/S/Docs/C.pptx"),  # pptx
]
mgr.providers[dsm.TARGET_SHAREPOINT].search = lambda kw, mx: {
    "results": list(rows), "total": len(rows), "note": ""}
dsm._manager = mgr
client = dsm.flask_app.test_client()
search_resp = client.post("/api/search", json={"keyword": "sample", "target": "sharepoint"}).get_json()
idx_doc_a = idx_of(search_resp, "DocA")

r = client.post("/api/summarize", json={})
check("idx未指定は400", r.status_code == 400, r.status_code)

r = client.post("/api/summarize", json={"idx": idx_of(search_resp, "FolderX")})
check("フォルダ行は400（理由付き）",
      r.status_code == 400 and "フォルダ" in r.get_json()["error"], r.get_json())

r = client.post("/api/summarize", json={"idx": idx_of(search_resp, "EnoviaDoc")})
check("Enovia行は400（理由付き）",
      r.status_code == 400 and "Enovia" in r.get_json()["error"], r.get_json())

r = client.post("/api/summarize", json={"idx": idx_of(search_resp, "PptxOne")})
check("pptx行は400（理由付き）",
      r.status_code == 400 and "pptx" in r.get_json()["error"], r.get_json())

r = client.post("/api/summarize", json={"idx": "999"})
check("範囲外の索引は400", r.status_code == 400, r.status_code)

# Gemini未導入・未設定の状態からの検証（このサンドボックスの既定状態）
orig_has_gemini = dsm.HAS_GEMINI
orig_cred_check = dsm.gemini_credentials_available
if not HAS_DOCX:
    print("  (python-docx未インストールのため、以降のG4検証はスキップ)")
else:
    dsm.HAS_GEMINI = False
    r = client.post("/api/summarize", json={"idx": idx_doc_a})
    check("Gemini共通モジュール未導入なら500", r.status_code == 500, r.status_code)

    dsm.HAS_GEMINI = True
    dsm.gemini_credentials_available = lambda: False
    r = client.post("/api/summarize", json={"idx": idx_doc_a})
    check("認証情報未設定なら500", r.status_code == 500
          and "GEMINI_API_KEY" in r.get_json()["error"], r.get_json())
    dsm.gemini_credentials_available = lambda: True

    # ダウンロード・Gemini呼び出しをスタブ化した正常系
    docx_bytes = make_docx_bytes([
        ("概要", "Heading 1"),
        ("これはテスト用の十分に長い本文です。" * 5, None),
    ])

    class FakeResp:
        def __init__(self, code, content=b""):
            self.status_code = code
            self.content = content

    download_calls = []

    def fake_get(url, headers=None, timeout=None, allow_redirects=None):
        download_calls.append(url)
        return FakeResp(200, docx_bytes)

    orig_http_get = dsm.http_req.get
    dsm.http_req.get = fake_get

    gemini_calls = []

    def counting_gemini(payload, model=None):
        gemini_calls.append(payload)
        return fake_gemini_response(executive_summary="これはExecutive Summaryです。")

    dsm._generate_advanced = counting_gemini

    try:
        r = client.post("/api/summarize", json={"idx": idx_doc_a})
        check("正常系は200", r.status_code == 200, r.status_code)
        data = r.get_json()
        check("executive_summaryが返る",
              data.get("executive_summary") == "これはExecutive Summaryです。", data)
        check("chaptersが返る", len(data.get("chapters", [])) == 1, data)
        check("insightsが返る", "use" in data.get("insights", {}), data)
        check("titleが返る", data.get("title") == "DocA", data)
        check("truncatedはFalse（十分短いため）", data.get("truncated") is False, data)
        check("ダウンロードは1回呼ばれる", len(download_calls) == 1, len(download_calls))
        check("Geminiは1回呼ばれる", len(gemini_calls) == 1, len(gemini_calls))

        # ── キャッシュ: 同じ条件なら再取得・再要約しない ──
        r2 = client.post("/api/summarize", json={"idx": idx_doc_a})
        check("2回目もキャッシュにより200", r2.status_code == 200, r2.status_code)
        check("キャッシュにより再ダウンロードしない",
              len(download_calls) == 1, len(download_calls))
        check("キャッシュにより再度Geminiを呼ばない",
              len(gemini_calls) == 1, len(gemini_calls))

        # ── 文書が更新されたら（last_modifiedが変われば）キャッシュを使わない ──
        rows[0].last_modified = "2026-09-02"
        mgr.providers[dsm.TARGET_SHAREPOINT].search = lambda kw, mx: {
            "results": list(rows), "total": len(rows), "note": ""}
        client.post("/api/search", json={"keyword": "sample", "target": "sharepoint"})
        r3 = client.post("/api/summarize", json={"idx": idx_doc_a})
        check("最終更新日が変わればキャッシュを使わず再取得する",
              len(download_calls) == 2, len(download_calls))
        check("最終更新日が変わればキャッシュを使わず再度要約する",
              len(gemini_calls) == 2, len(gemini_calls))

        # ── 本文がほとんど無い場合は要約しない（誤った要約を避けるガード） ──
        dsm.http_req.get = lambda *a, **k: FakeResp(200, make_docx_bytes([("短", None)]))
        rows[0].last_modified = "2026-09-03"
        mgr.providers[dsm.TARGET_SHAREPOINT].search = lambda kw, mx: {
            "results": list(rows), "total": len(rows), "note": ""}
        client.post("/api/search", json={"keyword": "sample", "target": "sharepoint"})
        r4 = client.post("/api/summarize", json={"idx": idx_doc_a})
        check("本文が短すぎる場合は422（要約を行わない）",
              r4.status_code == 422, (r4.status_code, r4.get_json()))
        check("422のときGeminiは呼ばれない（無駄打ちしない）",
              len(gemini_calls) == 2, len(gemini_calls))

        # ── 切り詰め（summary_max_charsで上限を絞る） ──
        dsm.http_req.get = fake_get
        dsm._cfg = dict(CFG, summary_max_chars=20, summary_min_chars=5)
        rows[0].last_modified = "2026-09-04"
        mgr.providers[dsm.TARGET_SHAREPOINT].search = lambda kw, mx: {
            "results": list(rows), "total": len(rows), "note": ""}
        client.post("/api/search", json={"keyword": "sample", "target": "sharepoint"})
        r5 = client.post("/api/summarize", json={"idx": idx_doc_a})
        check("上限文字数を絞るとtruncated=True", r5.get_json().get("truncated") is True,
              r5.get_json())
        dsm._cfg = CFG

        # ── ダウンロード失敗時のエラー ──
        rows[0].last_modified = "2026-09-05"
        mgr.providers[dsm.TARGET_SHAREPOINT].search = lambda kw, mx: {
            "results": list(rows), "total": len(rows), "note": ""}
        client.post("/api/search", json={"keyword": "sample", "target": "sharepoint"})
        dsm.http_req.get = lambda *a, **k: FakeResp(403)
        r6 = client.post("/api/summarize", json={"idx": idx_doc_a})
        check("ファイル取得失敗は500", r6.status_code == 500, r6.status_code)

        # ── Gemini呼び出し失敗時のエラー ──
        rows[0].last_modified = "2026-09-06"
        mgr.providers[dsm.TARGET_SHAREPOINT].search = lambda kw, mx: {
            "results": list(rows), "total": len(rows), "note": ""}
        client.post("/api/search", json={"keyword": "sample", "target": "sharepoint"})
        dsm.http_req.get = fake_get

        def failing_gemini(payload, model=None):
            raise RuntimeError("プロキシに到達できません")

        dsm._generate_advanced = failing_gemini
        r7 = client.post("/api/summarize", json={"idx": idx_doc_a})
        check("Gemini呼び出し失敗は502", r7.status_code == 502
              and "要約の生成に失敗" in r7.get_json()["error"], r7.get_json())
    finally:
        dsm.http_req.get = orig_http_get
        dsm._generate_advanced = orig_generate_advanced
        dsm.HAS_GEMINI = orig_has_gemini
        dsm.gemini_credentials_available = orig_cred_check
        dsm._cfg = CFG


# ── G5 画面表示（ボタン・ポップアップの存在確認） ────────────────
print("\n[G5] 画面表示")
html = dsm.flask_app.test_client().get("/").get_data(as_text=True)
check("要約列がAllタブに定義されている", '"__summary"' in html)
check("要約ボタンの生成ロジックがある", "openSummaryPopup" in html)
check("要約可否の判定ロジックがある（Phase Aの対象を絞る）", "summaryUnavailableReason" in html)
check("ポップアップのDOM構造がある", "summaryOverlay" in html and "summary-modal" in html)
check("/api/summarize を呼び出すfetchがある", '"/api/summarize"' in html)
check("Escキーで閉じるハンドラがある", "summaryPopupKeyHandler" in html)


print(f"\n{'=' * 46}\n  成功 {ok} 件 / 失敗 {ng} 件\n{'=' * 46}")
sys.exit(1 if ng else 0)
