"""_weekly_line_range() の回帰テスト。

実PDF検証で発見した不具合の再現テスト: PDFは新しいWeeklyから順に綴じられて
いる（ページ番号が大きいほど古い週になる）。日付昇順(古い→新しい)にソートした
リストで「次の要素(index+1)」を終端に使うと、ページ番号の大小関係が逆転し、
スライス範囲が常に空になっていた。正しくは「1つ古い要素(index-1、ページ番号は
より大きい)」を終端に使う必要がある。
"""
import importlib.util
from datetime import date
from pathlib import Path

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


def _boundaries_oldest_first():
    """実PDFと同じ関係を再現: 日付が新しいほどページ番号は小さい。"""
    WB = cli.WeeklyBoundary  # noqa: N806
    return [
        WB(report_date=date(2026, 4, 10), start_page=83, start_y=181.3),  # 最古
        WB(report_date=date(2026, 4, 17), start_page=77, start_y=681.6),
        WB(report_date=date(2026, 4, 24), start_page=72, start_y=115.6),
        WB(report_date=date(2026, 5, 1), start_page=66, start_y=321.3),  # 最新
    ]


def test_range_end_uses_older_neighbor_not_newer():
    boundaries = _boundaries_oldest_first()

    # index=1 (2026-04-17) の終端は、1つ古い(index=0, 2026-04-10, page83)であるべき
    # であり、1つ新しい(index=2, 2026-04-24, page72)ではない。
    start_page, start_y, end_page, end_y = cli._weekly_line_range(boundaries, 1)
    assert start_page == 77
    assert end_page == 83, "終端がより新しい週(ページ番号が小さい)になっている(逆転バグ)"
    assert end_page > start_page, "終端ページは開始ページより大きくなければならない"


def test_oldest_entry_has_no_upper_bound():
    boundaries = _boundaries_oldest_first()

    start_page, start_y, end_page, end_y = cli._weekly_line_range(boundaries, 0)
    assert end_page is None, "最古のWeeklyは文書末尾まで(終端なし)であるべき"


def test_newest_entry_has_finite_range():
    boundaries = _boundaries_oldest_first()

    start_page, start_y, end_page, end_y = cli._weekly_line_range(boundaries, 3)
    assert end_page == 72, "最新のWeeklyも1つ古い週(index=2)までの範囲を持つべき"


def test_range_start_and_end_never_inverted_for_all_indices():
    boundaries = _boundaries_oldest_first()

    for i in range(len(boundaries)):
        start_page, start_y, end_page, end_y = cli._weekly_line_range(boundaries, i)
        if end_page is not None:
            assert end_page >= start_page, f"index={i}で範囲が逆転している"
