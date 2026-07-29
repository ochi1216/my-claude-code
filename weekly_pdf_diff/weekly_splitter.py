"""Weekly Reportの境界検出と日付抽出（IMPLEMENTATION_PLAN.md 2章・5.3節）。

境界は (ページ番号, ページ内Y座標) の組で管理する。実PDFではWeekly境界が
ページ途中で発生することを確認済みのため、ページ単位の固定範囲は使わない。
"""
import re
from dataclasses import dataclass
from datetime import date

from pdf_reader import Line

SENT_RE = re.compile(r"^Sent:\s*\w+,\s*(\w+)\s+(\d{1,2}),\s*(\d{4})")
SUBJECT_RE = re.compile(r"^Subject:\s*Weekly Report")
ONENOTE_DATE_RE = re.compile(r"^(\d{4})年(\d{1,2})月(\d{1,2})日$")

MONTHS = {
    "January": 1, "February": 2, "March": 3, "April": 4, "May": 5, "June": 6,
    "July": 7, "August": 8, "September": 9, "October": 10, "November": 11,
    "December": 12,
}


@dataclass
class WeeklyBoundary:
    report_date: date | None
    start_page: int
    start_y: float


def _parse_sent_date(text: str) -> date | None:
    m = SENT_RE.match(text.strip())
    if not m:
        return None
    month_name, day, year = m.groups()
    month = MONTHS.get(month_name)
    if month is None:
        return None
    return date(int(year), month, int(day))


def _parse_onenote_date(text: str) -> date | None:
    m = ONENOTE_DATE_RE.match(text.strip())
    if not m:
        return None
    year, month, day = (int(v) for v in m.groups())
    return date(year, month, day)


def find_boundaries(lines: list[Line]) -> list[WeeklyBoundary]:
    """Subject: Weekly Report で始まるブロックをWeekly開始位置として検出する。
    PDF先頭は無条件で最新Weeklyの開始位置として扱う（ヘッダーが無いケース）。
    """
    if not lines:
        return []

    boundaries = [
        WeeklyBoundary(report_date=None, start_page=lines[0].page, start_y=lines[0].y0)
    ]

    for i, line in enumerate(lines):
        if not SUBJECT_RE.match(line.text.strip()):
            continue
        sent_date = None
        for prev in reversed(lines[max(0, i - 3):i]):
            sent_date = _parse_sent_date(prev.text)
            if sent_date:
                break
        boundaries.append(
            WeeklyBoundary(report_date=sent_date, start_page=line.page, start_y=line.y0)
        )

    return boundaries


def resolve_missing_dates(lines: list[Line], boundaries: list[WeeklyBoundary]) -> None:
    """report_dateがNoneの境界（主にヘッダーなし先頭ブロック）を、その
    ブロック内に出現するOneNote印字日時から補完する（優先順位3位: 5.3節）。
    boundariesをin-placeで更新する。
    """
    for idx, boundary in enumerate(boundaries):
        if boundary.report_date is not None:
            continue
        end_page = boundaries[idx + 1].start_page if idx + 1 < len(boundaries) else None
        end_y = boundaries[idx + 1].start_y if idx + 1 < len(boundaries) else None
        for line in lines:
            if line.page < boundary.start_page:
                continue
            if line.page == boundary.start_page and line.y0 < boundary.start_y:
                continue
            if end_page is not None and (
                line.page > end_page or (line.page == end_page and line.y0 >= end_y)
            ):
                break
            found = _parse_onenote_date(line.text)
            if found:
                boundary.report_date = found
                break
