from datetime import date

from models import DiffResult, TextUnit
from pdf_reader import Word
from report import build_rows, write_csv, write_html


def _unit(section_path, text, page=0):
    words = [
        Word(page=page, x0=i * 10.0, y0=0.0, x1=i * 10.0 + 8.0, y1=10.0, text=w)
        for i, w in enumerate(text.split())
    ]
    return TextUnit(section_path, "paragraph", text, text, 11.0, words)


def test_unchanged_rows_are_excluded_from_report():
    curr = _unit(("Work Plan",), "same text")
    results = [DiffResult(curr, curr, "unchanged", 100.0, [], False)]

    rows = build_rows(date(2026, 7, 17), date(2026, 7, 10), results)

    assert rows == []


def test_modified_row_captures_project_section_and_changed_words():
    curr = _unit(("Summary Project", "Wheeling", "STR"), "was received today", page=5)
    prev = _unit(("Summary Project", "Wheeling", "STR"), "will arrive today", page=4)
    results = [DiffResult(curr, prev, "modified", 88.0, curr.words[:1], False)]

    rows = build_rows(date(2026, 7, 17), date(2026, 7, 10), results)

    assert len(rows) == 1
    row = rows[0]
    assert row.project == "Wheeling"
    assert row.section == "STR"
    assert row.change_type == "modified"
    assert row.previous_text == "will arrive today"
    assert row.current_text == "was received today"
    assert row.changed_words == "was"
    assert row.page == "6"  # 0始まりpage=5 -> 1始まり表記
    assert row.confidence == "88"


def test_deleted_row_uses_prev_unit_for_project_and_page():
    prev = _unit(("Summary Project", "Caracal", "Others"), "removed line", page=2)
    results = [DiffResult(None, prev, "deleted", 0.0, [], False)]

    rows = build_rows(date(2026, 7, 17), date(2026, 7, 10), results)

    assert len(rows) == 1
    assert rows[0].project == "Caracal"
    assert rows[0].current_text == ""
    assert rows[0].previous_text == "removed line"
    assert rows[0].page == "3"


def test_write_csv_and_html_create_files(tmp_path):
    curr = _unit(("Work Plan",), "brand new item")
    results = [DiffResult(curr, None, "added", 0.0, [], True)]
    rows = build_rows(date(2026, 7, 17), date(2026, 7, 10), results)

    csv_path = tmp_path / "out.csv"
    html_path = tmp_path / "out.html"
    write_csv(rows, csv_path)
    write_html(rows, html_path)

    assert csv_path.exists()
    assert html_path.exists()
    csv_text = csv_path.read_text(encoding="utf-8-sig")
    assert "brand new item" in csv_text
    html_text = html_path.read_text(encoding="utf-8")
    assert "brand new item" in html_text
