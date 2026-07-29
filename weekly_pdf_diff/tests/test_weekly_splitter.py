from datetime import date

from pdf_reader import extract_lines
from weekly_splitter import find_boundaries, resolve_missing_dates


def _weekly_email_lines(sender_meta: list[tuple[str, bool]], sent_text: str, subject_ww: int):
    return [
        *sender_meta,
        (f"From: Test Sender <sender@example.com>", False),
        (sent_text, False),
        ("To: Someone <someone@example.com>", False),
        ("Cc: ", False),
        (f"Subject: Weekly Report Test ww{subject_ww}", False),
        ("Hello Ochi San.", False),
        ("Please refer to my weekly report as follows.", False),
        ("Work Plan", True),
        ("1. Something happened this week.", False),
    ]


def test_boundary_mid_page_and_headerless_top(build_pdf):
    """引継ぎ資料5.1節・実PDF調査で確認した『Weekly境界がページ途中に来る』
    ケースと『PDF先頭はヘッダーなし』ケースを合成PDFで再現して検証する。
    """
    page1_top_weekly = [
        ("Hello Ochi San.", False),
        ("Please refer to my weekly report as follows.", False),
        ("Work Plan", True),
        ("1. Newest week item.", False),
        ("Thank you.", False),
        ("Regards", False),
        ("Test Sender", False),  # 署名の続きが2ページ目冒頭にはみ出す想定
    ]
    page2_signature_tail_then_next_weekly = [
        ("Test Sender (cont.)", False),  # ページ途中まで前Weeklyの署名
        ("test@example.com", False),
    ] + _weekly_email_lines([], "Sent: Friday, July 17, 2026 2:00 PM", 29)

    pdf_path, doc = build_pdf([page1_top_weekly, page2_signature_tail_then_next_weekly])
    lines = extract_lines(doc)
    boundaries = find_boundaries(lines)

    assert len(boundaries) == 2
    # 1件目: PDF先頭、日付未確定（ヘッダーなし）
    assert boundaries[0].start_page == 0
    assert boundaries[0].start_y == lines[0].y0
    assert boundaries[0].report_date is None
    # 2件目: 2ページ目の途中（Y座標が0ではない = ページ先頭ではない）から開始
    assert boundaries[1].start_page == 1
    assert boundaries[1].start_y > 0
    assert boundaries[1].report_date == date(2026, 7, 17)


def test_resolve_missing_dates_uses_onenote_timestamp(build_pdf):
    page1 = [
        ("Hello Ochi San.", False),
        ("Work Plan", True),
        ("1. Newest week item.", False),
        ("2026年7月29日", False),
        ("13:58", False),
    ]
    page2 = _weekly_email_lines([], "Sent: Friday, July 17, 2026 2:00 PM", 29)

    pdf_path, doc = build_pdf([page1, page2])
    lines = extract_lines(doc)
    boundaries = find_boundaries(lines)
    assert boundaries[0].report_date is None

    resolve_missing_dates(lines, boundaries)
    assert boundaries[0].report_date == date(2026, 7, 29)
    assert boundaries[1].report_date == date(2026, 7, 17)


def test_expected_count_mismatch_is_detectable(build_pdf):
    """検出件数を呼び出し側で期待値と突き合わせられることを確認する
    （不一致時は処理を停止しログ出力する、という仕様のための最小契約）。
    """
    page1 = [("Hello Ochi San.", False), ("Work Plan", True)]
    pdf_path, doc = build_pdf([page1])
    lines = extract_lines(doc)
    boundaries = find_boundaries(lines)

    expected_count = 16
    assert len(boundaries) != expected_count
