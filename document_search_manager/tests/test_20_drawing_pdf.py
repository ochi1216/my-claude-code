# -*- coding: utf-8 -*-
"""図面が主体のPDFの判定（v20260910_03）

越智さんのご指摘：回路図PDFを要約しようとすると数十万文字として扱われる。
調べた結果これは誤認識ではなく、回路図PDFがベクター図面で、部品番号・
ネット名・ピン名がすべて「文字」として埋め込まれているためだった。
文字数は正しいが、文章ではないため要約しても意味を成さない。

方針（越智さんの判断・案C）：**図面が主体と判定したら要約せず、
理由を伝えてファイルを開いていただく。**

このテストで確かめるのは3点。
  ① 「文章」と「羅列」を、実際に測って区別できているか
  ② 箇条書き中心の正当な文書を、図面と誤判定しないか
  ③ 判定したときにGeminiを呼んでいないか（呼べば無駄な120秒が発生する）

ネットワークにもGeminiにも一切アクセスしない。
実行: python tests/test_20_drawing_pdf.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _harness import dsm, Checker, DummyAuth  # noqa: E402

check = Checker()

CFG = dict(dsm.DEFAULT_CFG)


# ── 見本データ ────────────────────────────────────────────────
def schematic_text(sheets=6, labels_per_sheet=500):
    """回路図PDFから取り出される文字の見本（部品番号・ネット名・定数の羅列）。"""
    names = ["R23", "C104", "U5", "VDD_3V3", "SDA", "SCL", "10k", "100n",
             "GND", "Q7", "TP12", "NRST", "1u", "D3", "L2", "4.7k"]
    lines = []
    for sheet in range(1, sheets + 1):
        lines.append(f"# Page {sheet}")
        for i in range(labels_per_sheet):
            lines.append(names[i % len(names)])
    return "\n".join(lines)


def prose_text(paragraphs=200):
    """通常の日本語文書の見本。"""
    lines = ["# 1. 評価の目的"]
    for i in range(paragraphs):
        lines.append(f"本項では第{i + 1}節の評価条件について述べる。"
                     "対象は電源ICであり、温度範囲は-40度から125度とする。")
    return "\n".join(lines)


def bullet_text(items=600):
    """箇条書き中心の正当な文書。1行は短いが、文としては成立している。"""
    lines = ["# チェックリスト"]
    for i in range(items):
        lines.append(f"項目{i + 1}を確認する。")
    return "\n".join(lines)


def table_text(rows=300):
    """表を書き出したPDFの見本。句点は無いが、1行は長い。"""
    lines = ["# 部品表"]
    for i in range(rows):
        lines.append(f"{i + 1} | NX{1000 + i} | 電圧レギュレータ 3.3V 出力 | "
                     f"数量 {i % 7 + 1} | 備考なし 予備品として在庫あり")
    return "\n".join(lines)


# ── H1 測る（_pdf_text_metrics） ──────────────────────────────
print("\n[H1] 本文の性質を測る（_pdf_text_metrics）")
m_draw = dsm._pdf_text_metrics(schematic_text())
m_prose = dsm._pdf_text_metrics(prose_text())

check("見出し行（# ）は本文として数えない",
      dsm._pdf_text_metrics("# Page 1\nabc\n# Page 2\ndef")["lines"] == 2,
      dsm._pdf_text_metrics("# Page 1\nabc\n# Page 2\ndef"))
check("図面は文末記号がほぼ無い", m_draw["sentences"] == 0, m_draw)
check("文章は文末記号が多い（30〜60字に1つ程度）",
      0.015 <= m_prose["sentence_ratio"] <= 0.05, m_prose)
check("図面は1行が極端に短い", m_draw["avg_line_chars"] < 6, m_draw)
check("文章は1行が長い", m_prose["avg_line_chars"] > 30, m_prose)
check("小数点は文末として数えない（10.5 の . を句点と誤らない）",
      dsm._pdf_text_metrics("10.5 3.3 4.7")["sentences"] == 0,
      dsm._pdf_text_metrics("10.5 3.3 4.7"))
check("英文のピリオドは文末として数える",
      dsm._pdf_text_metrics("This is a test. And another one.")["sentences"] == 2,
      dsm._pdf_text_metrics("This is a test. And another one."))
check("空文字でも落ちない（ゼロ除算をしない）",
      dsm._pdf_text_metrics("")["sentence_ratio"] == 0.0)


# ── H2 判定する（_looks_like_drawing_pdf） ────────────────────
print("\n[H2] 図面かどうかの判定（_looks_like_drawing_pdf）")
is_draw, why = dsm._looks_like_drawing_pdf(m_draw, CFG, m_draw["chars"])
check("回路図は図面と判定する", is_draw is True, (is_draw, why))
check("判定の根拠を数字で示す（後から検証できるようにする）",
      "読み取った" in why and "1行あたり平均" in why, why)
check("文末記号が0個のときは「約N字に1つ」と書かない（誤解を招くため）",
      "1つもなく" in why and "字に1つ" not in why, why)

m_few = dsm._pdf_text_metrics(schematic_text() + "\nここに1つだけ文がある。")
_is, why_few = dsm._looks_like_drawing_pdf(m_few, CFG, m_few["chars"])
check("文末記号が少しあるときは、何字に1つかを示す",
      "字に1つ" in why_few, why_few)

is_draw, _why = dsm._looks_like_drawing_pdf(m_prose, CFG, m_prose["chars"])
check("通常の文書は図面と判定しない", is_draw is False)

m_bullet = dsm._pdf_text_metrics(bullet_text())
is_draw, _why = dsm._looks_like_drawing_pdf(m_bullet, CFG, m_bullet["chars"])
check("箇条書き中心の文書は図面と判定しない（1行は短いが文になっている）",
      is_draw is False, m_bullet)

m_table = dsm._pdf_text_metrics(table_text())
is_draw, _why = dsm._looks_like_drawing_pdf(m_table, CFG, m_table["chars"])
check("表の書き出しは図面と判定しない（句点は無いが1行が長い）",
      is_draw is False, m_table)

m_small = dsm._pdf_text_metrics(schematic_text(sheets=1, labels_per_sheet=50))
is_draw, _why = dsm._looks_like_drawing_pdf(m_small, CFG, m_small["chars"])
check("短いPDFは判定しない（誤判定の害の方が大きいため）",
      is_draw is False, m_small)

check("切り詰められていても、元が大きければ判定の対象にする",
      dsm._looks_like_drawing_pdf(m_small, CFG, 400000)[0] is True,
      m_small)

strict = dict(CFG, pdf_drawing_avg_line_chars=1)
check("閾値は config.json で調整できる（1行あたりの文字数）",
      dsm._looks_like_drawing_pdf(m_draw, strict, m_draw["chars"])[0] is False)
strict2 = dict(CFG, pdf_drawing_check_min_chars=10 ** 9)
check("判定を始める文字数も config.json で調整できる",
      dsm._looks_like_drawing_pdf(m_draw, strict2, m_draw["chars"])[0] is False)


# ── H3 API の振る舞い（/api/summarize） ───────────────────────
print("\n[H3] 要約APIの振る舞い（Geminiを呼ばずに止まるか）")
dsm._cfg = CFG
dsm._auth = DummyAuth()
client = dsm.flask_app.test_client()

gemini_calls = []


def mk(**kwargs):
    base = dict(source="SharePoint", title="Schematic_RevB",
                doc_type="pdf", url="https://x/sites/S/Docs/sch.pdf",
                last_modified="2026-09-01")
    base.update(kwargs)
    return dsm.SearchResult(**base)


extracted = {"text": schematic_text(), "truncated": False}

orig_download = dsm._download_one
orig_extract = dsm._extract_text_for_summary
orig_generate = dsm._generate_summary
orig_has_gemini = dsm.HAS_GEMINI
orig_cred = dsm.gemini_credentials_available
try:
    dsm.HAS_GEMINI = True
    dsm.gemini_credentials_available = lambda: True
    dsm._download_one = lambda token, result, timeout: ("sch.pdf", b"%PDF-dummy")
    dsm._extract_text_for_summary = (
        lambda doc_type, content, max_chars: (
            extracted["text"], extracted["truncated"], len(extracted["text"])))

    def fake_generate(title, text):
        gemini_calls.append(title)
        return {"executive_summary": "ダミー要約", "chapters": [],
                "insights": {"use": [], "caution": [], "questions": []}}

    dsm._generate_summary = fake_generate

    dsm._last_results = [mk(), mk(title="Report", doc_type="docx",
                               url="https://x/sites/S/Docs/r.docx")]
    dsm._summary_cache.clear()

    r = client.post("/api/summarize", json={"idx": "0"})
    data = r.get_json()
    check("図面PDFは要約せず、案内を返す",
          r.status_code == 200 and data.get("drawing_pdf") is True, data)
    check("Geminiを呼んでいない（無駄な待ち時間を発生させない）",
          gemini_calls == [], gemini_calls)
    check("案内に理由を含める", bool(data.get("reason")), data)
    check("案内に本文の総字数を含める",
          data.get("total_chars") == len(extracted["text"]), data)
    check("案内にファイルのリンクを含める（そのまま開けるようにする）",
          data.get("url") == "https://x/sites/S/Docs/sch.pdf", data)
    check("案内はキャッシュしない（次に押したときも同じ案内を出す）",
          not dsm._summary_cache, dsm._summary_cache)

    r = client.post("/api/summarize", json={"idx": "0", "confirm_drawing": True})
    check("「それでも要約する」を選べば要約を実行する",
          r.status_code == 200 and gemini_calls == ["Schematic_RevB"],
          (r.status_code, gemini_calls))

    # 切り詰めよりも先に図面の判定を行う（二度手間を避けるため）
    gemini_calls.clear()
    dsm._summary_cache.clear()
    extracted["truncated"] = True
    r = client.post("/api/summarize", json={"idx": "0"})
    data = r.get_json()
    check("切り詰めにも該当する図面PDFでは、図面の案内を先に出す",
          data.get("drawing_pdf") is True and not data.get("truncated"), data)
    extracted["truncated"] = False

    # 図面でない形式は、この判定を一切通らない
    gemini_calls.clear()
    dsm._summary_cache.clear()
    extracted["text"] = schematic_text()
    r = client.post("/api/summarize", json={"idx": "1"})
    check("同じ内容でも .docx なら判定しない（PDFだけの話のため）",
          r.get_json().get("drawing_pdf") is None
          and gemini_calls == ["Report"], (r.get_json(), gemini_calls))

    # 通常のPDFは、これまでどおり要約される
    gemini_calls.clear()
    dsm._summary_cache.clear()
    extracted["text"] = prose_text()
    r = client.post("/api/summarize", json={"idx": "0"})
    check("文章が主体のPDFは、これまでどおり要約する",
          r.get_json().get("drawing_pdf") is None
          and gemini_calls == ["Schematic_RevB"], (r.get_json(), gemini_calls))
finally:
    dsm._download_one = orig_download
    dsm._extract_text_for_summary = orig_extract
    dsm._generate_summary = orig_generate
    dsm.HAS_GEMINI = orig_has_gemini
    dsm.gemini_credentials_available = orig_cred
    dsm._summary_cache.clear()


# ── H4 画面側 ────────────────────────────────────────────────
print("\n[H4] 画面側の部品")
html = client.get("/").get_data(as_text=True)
for label, needle in [
    ("図面PDFの案内を描く処理がある", "function renderDrawingPdfNotice("),
    ("案内を切り詰め確認より先に出している", "if (result.data.drawing_pdf) {"),
    ("「ファイルを開く」ボタンがある", '"ファイルを開く"'),
    ("「それでも要約する」ボタンがある", '"それでも要約する"'),
    ("確認の意思をサーバーへ送っている", "confirm_drawing: confirmDrawing"),
]:
    check(label, needle in html, needle)

check("判定の閾値が既定値として入っている",
      dsm.DEFAULT_CFG.get("pdf_drawing_check_min_chars") == 5000
      and dsm.DEFAULT_CFG.get("pdf_drawing_sentence_ratio") == 0.005
      and dsm.DEFAULT_CFG.get("pdf_drawing_avg_line_chars") == 12,
      {k: v for k, v in dsm.DEFAULT_CFG.items() if k.startswith("pdf_drawing")})

check.finish()
