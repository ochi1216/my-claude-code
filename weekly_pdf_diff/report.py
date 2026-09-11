"""差分レポート出力（CSV/HTML）。IMPLEMENTATION_PLAN.md 14章。"""
import csv
import html
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from models import DiffResult

_COLUMNS = [
    "current_week",
    "previous_week",
    "project",
    "section",
    "change_type",
    "previous_text",
    "current_text",
    "changed_words",
    "page",
    "confidence",
]


@dataclass
class ReportRow:
    current_week: str
    previous_week: str
    project: str
    section: str
    change_type: str
    previous_text: str
    current_text: str
    changed_words: str
    page: str
    confidence: str

    def as_list(self) -> list[str]:
        return [getattr(self, col) for col in _COLUMNS]


def build_rows(
    curr_date: date | None, prev_date: date | None, diff_results: list[DiffResult]
) -> list[ReportRow]:
    rows: list[ReportRow] = []
    for result in diff_results:
        if result.change_type == "unchanged":
            continue  # 差分がないものはレポートに載せない

        unit = result.curr_unit or result.prev_unit
        section_path = unit.section_path if unit else ()
        project = section_path[1] if len(section_path) > 1 else ""
        section = section_path[-1] if section_path else ""

        page = ""
        for candidate in (result.curr_unit, result.prev_unit):
            if candidate and candidate.words:
                page = str(candidate.words[0].page + 1)  # 1始まり
                break

        rows.append(
            ReportRow(
                current_week=curr_date.isoformat() if curr_date else "",
                previous_week=prev_date.isoformat() if prev_date else "",
                project=project,
                section=section,
                change_type=result.change_type,
                previous_text=result.prev_unit.raw_text if result.prev_unit else "",
                current_text=result.curr_unit.raw_text if result.curr_unit else "",
                changed_words=" / ".join(w.text for w in result.changed_words),
                page=page,
                confidence=f"{result.similarity:.0f}",
            )
        )
    return rows


def write_csv(rows: list[ReportRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig: Excel(日本語Windows)でBOMなしUTF-8を開くと文字化けするための対策
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(_COLUMNS)
        for row in rows:
            writer.writerow(row.as_list())


def write_html(rows: list[ReportRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "".join(f"<th>{col}</th>" for col in _COLUMNS)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{html.escape(v)}</td>" for v in row.as_list())
        body_rows.append(f"<tr>{cells}</tr>")
    content = (
        "<!doctype html><meta charset='utf-8'><title>weekly_pdf_diff report</title>"
        "<table border='1' cellspacing='0' cellpadding='4'>"
        f"<tr>{header}</tr>{''.join(body_rows)}</table>"
    )
    path.write_text(content, encoding="utf-8")
