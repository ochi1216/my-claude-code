"""パイプライン全体（Phase 1〜5）を通した統合テスト。

3件の合成Weekly（基準週＋2週）を持つPDFを作り、CLIエントリポイントの run() を
直接呼び出して、出力ファイル一式と主要な差分の反映結果を確認する。
CLIエントリポイントのファイル名は日付が変わると増えていくため、
run_weekly_pdf_diff.batと同じ規則（ファイル名で最新を選ぶ）で動的に読み込む。
"""
import importlib.util
import json
from datetime import date
from pathlib import Path

import fitz

PROJECT_DIR = Path(__file__).resolve().parent.parent


def _load_latest_cli_module():
    candidates = sorted(PROJECT_DIR.glob("weekly_pdf_diff_????????_??.py"))
    assert candidates, "weekly_pdf_diff_yyyymmdd_NN.py が見つかりません"
    latest = candidates[-1]
    spec = importlib.util.spec_from_file_location(latest.stem, latest)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cli = _load_latest_cli_module()

PAGE_WIDTH, PAGE_HEIGHT = 595, 842
LINE_HEIGHT = 16


def _build_three_weekly_pdf(path: Path) -> None:
    doc = fitz.open()

    # week3（最新, ヘッダーなし。日付はOneNote印字スタンプから解決させる）
    page0_lines = [
        ("Hello Ochi San.", False),
        ("Please refer to my weekly report as follows.", False),
        ("Work Plan", True),
        ("1. New task for week three.", False),
        ("Weekly update", True),
        ("Wheeling", True),
        ("1. ESD socket was received on 21st July.", False),
        ("Thank you.", False),
        ("Regards", False),
        ("Test Sender", False),
        ("2026年5月1日", False),
        ("11:00", False),
    ]
    # week2（2026-04-24）
    page1_lines = [
        ("From: Sender <sender@example.com>", False),
        ("Sent: Friday, April 24, 2026 11:00 AM", False),
        ("To: Someone <someone@example.com>", False),
        ("Cc: ", False),
        ("Subject: Weekly Report Test ww2", False),
        ("Hello Ochi San.", False),
        ("Please refer to my weekly report as follows.", False),
        ("Work Plan", True),
        ("1. Existing task.", False),
        ("Weekly update", True),
        ("Wheeling", True),
        ("1. ESD socket will arrive on 21st July.", False),
        ("Thank you.", False),
        ("Regards", False),
        ("Test Sender", False),
    ]
    # week1（2026-04-17, 基準週）
    page2_lines = [
        ("From: Sender <sender@example.com>", False),
        ("Sent: Friday, April 17, 2026 11:00 AM", False),
        ("To: Someone <someone@example.com>", False),
        ("Cc: ", False),
        ("Subject: Weekly Report Test ww1", False),
        ("Hello Ochi San.", False),
        ("Please refer to my weekly report as follows.", False),
        ("Work Plan", True),
        ("1. Existing task.", False),
        ("Weekly update", True),
        ("Wheeling", True),
        ("1. ESD socket will arrive on 21st July.", False),
        ("Thank you.", False),
        ("Regards", False),
        ("Test Sender", False),
    ]

    for page_lines in (page0_lines, page1_lines, page2_lines):
        page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        y = 50
        for text, bold in page_lines:
            if text.isascii():
                fontname = "hebo" if bold else "helv"
            else:
                fontname = "japan"
            page.insert_text((50, y), text, fontname=fontname, fontsize=11)
            y += LINE_HEIGHT

    doc.save(path)


def test_pipeline_produces_expected_outputs_and_word_level_diff(tmp_path):
    pdf_path = tmp_path / "synthetic_weekly.pdf"
    _build_three_weekly_pdf(pdf_path)
    output_dir = tmp_path / "output"

    exit_code = cli.run(
        pdf_path=pdf_path,
        output_dir=output_dir,
        expected_count=3,
        baseline=date(2026, 4, 17),
    )
    assert exit_code == 0

    index_path = output_dir / f"{pdf_path.stem}_weekly_index.json"
    pdf_out_path = output_dir / f"{pdf_path.stem}_diff_blue_bold.pdf"
    csv_path = output_dir / f"{pdf_path.stem}_diff_report.csv"
    html_path = output_dir / f"{pdf_path.stem}_diff_report.html"
    for path in (index_path, pdf_out_path, csv_path, html_path):
        assert path.exists(), f"{path} が作成されていない"

    index_data = json.loads(index_path.read_text(encoding="utf-8"))
    assert [entry["date"] for entry in index_data] == ["2026-04-17", "2026-04-24", "2026-05-01"]

    # week1(基準週)とweek2は内容が完全に同一 -> 差分レポートに行が出ないはず
    csv_text = csv_path.read_text(encoding="utf-8-sig")
    rows = [r for r in csv_text.splitlines()[1:] if r.strip()]
    week1_to_week2_rows = [r for r in rows if r.startswith("2026-04-24,2026-04-17,")]
    assert week1_to_week2_rows == [], f"変更がないはずのweek1->week2に差分が検出された: {week1_to_week2_rows}"

    week2_to_week3_rows = [r for r in rows if r.startswith("2026-05-01,2026-04-24,")]
    assert week2_to_week3_rows, "week2->week3の差分がレポートに出ていない"

    # 出力PDFは元の3ページ構成を維持している
    out_doc = fitz.open(pdf_out_path)
    assert out_doc.page_count == 3

    # week3(0ページ目)には "was"/"received" が青太字で描画されているはず
    page0 = out_doc[0]
    blue_bold_spans = [
        s["text"]
        for block in page0.get_text("dict")["blocks"]
        for line in block.get("lines", [])
        for s in line["spans"]
        if s["flags"] & 16 and s["color"] != 0
    ]
    assert any("was" in t or "received" in t for t in blue_bold_spans), (
        f"単語単位の青太字が見つからない: {blue_bold_spans}"
    )
