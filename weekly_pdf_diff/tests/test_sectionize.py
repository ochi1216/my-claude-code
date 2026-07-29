from pdf_reader import extract_lines, extract_words
from sectionize import build_units


def _make_pdf(build_pdf, lines):
    """実データの箇条書き記号(•, Symbolフォント)はhelv/heboでは表現できないため、
    テストでは無印の見出し文言（ボールドフラグのみ）で代替する。
    """
    pdf_path, doc = build_pdf([lines])
    return extract_lines(doc), extract_words(doc)


def test_email_header_and_greeting_and_signature_excluded(build_pdf):
    lines_spec = [
        ("From: Sender <sender@example.com>", False),
        ("Sent: Friday, July 17, 2026 2:00 PM", False),
        ("To: Someone <someone@example.com>", False),
        ("Cc: ", False),
        ("Subject: Weekly Report Test ww29", False),
        ("Hello Ochi San.", False),
        ("Please refer to my weekly report as follows.", False),
        ("Work Plan", True),
        ("1. Something happened.", False),
        ("Thank you.", False),
        ("Regards", False),
        ("Test Sender", False),
        ("Product Engineer", False),
        ("test@example.com", False),
    ]
    lines, words = _make_pdf(build_pdf, lines_spec)
    units = build_units(lines, words)

    assert len(units) == 1
    assert units[0].section_path == ("Work Plan",)
    assert units[0].raw_text == "1. Something happened."


def test_continuation_line_merged_into_previous_item(build_pdf):
    lines_spec = [
        ("Work Plan", True),
        ("1. Received caracal ESD socket. Endorsed to Rel Lab and proceed test", False),
        ("program.", False),
        ("2. Next item.", False),
    ]
    lines, words = _make_pdf(build_pdf, lines_spec)
    units = build_units(lines, words)

    assert len(units) == 2
    assert units[0].raw_text == (
        "1. Received caracal ESD socket. Endorsed to Rel Lab and proceed test program."
    )
    assert units[1].raw_text == "2. Next item."


def test_weekly_update_project_heading_via_bold(build_pdf):
    lines_spec = [
        ("Weekly update", True),
        ("Wheeling", True),
        ("1. Wheeling item one.", False),
        ("Caracal", True),
        ("1. Caracal item one.", False),
    ]
    lines, words = _make_pdf(build_pdf, lines_spec)
    units = build_units(lines, words)

    assert [u.section_path for u in units] == [
        ("Weekly update", "Wheeling"),
        ("Weekly update", "Caracal"),
    ]


def test_summary_project_uses_project_name_field_not_bold(build_pdf):
    lines_spec = [
        ("Summary Project", True),
        ("Project Name:  Wheeling", False),
        ("Project Milestone: TBD", False),
        ("STR", False),
        ("1.STR item.", False),
        ("Reliability", False),
        ("1.Reliability item.", False),
        ("Project Name: Caracal", False),
        ("Others", False),
        ("1.Caracal others item.", False),
    ]
    lines, words = _make_pdf(build_pdf, lines_spec)
    units = build_units(lines, words)

    paths = [u.section_path for u in units]
    assert paths == [
        ("Summary Project", "Wheeling"),
        ("Summary Project", "Wheeling"),
        ("Summary Project", "Wheeling", "STR"),
        ("Summary Project", "Wheeling", "Reliability"),
        ("Summary Project", "Caracal"),
        ("Summary Project", "Caracal", "Others"),
    ]


def test_word_association_matches_line_word_count(build_pdf):
    lines_spec = [("Work Plan", True), ("1. Four simple words here.", False)]
    lines, words = _make_pdf(build_pdf, lines_spec)
    units = build_units(lines, words)

    assert len(units) == 1
    assert [w.text for w in units[0].words] == ["1.", "Four", "simple", "words", "here."]


def test_column_crossing_fragment_does_not_corrupt_adjacent_item(build_pdf):
    """実PDF調査で発見した不具合の再現テスト。

    OneNote由来PDFの一部では、罫線のない別列（狭い列に折り返された見出し）が
    STRリストと似たY座標に存在し、Y座標だけで行を結合すると別列の断片
    （例: "Reliability"が"Reliabi"/"lity"に分割されたもの）がSTR項目の
    テキストに混入してしまっていた。X座標が大きく離れた行は継続行とみなさない
    ことで、STR項目のテキストが汚染されないことを確認する。
    """
    lines_spec = [
        ("Summary Project", True, 50),
        ("Project Name:  Wheeling", False, 50),
        ("STR", False, 50),
        ("1.Execution schedule Wheeling Wheeling_2nd.xlsx", False, 113),
        ("Reliabi", False, 72),
        ("2.Wheeling Qualification readiness Summary", False, 113),
        ("lity", False, 72),
        ("3.Confirmed and proceed qual MRA2P1 as commercial only.", False, 113),
    ]
    lines, words = _make_pdf(build_pdf, lines_spec)
    units = build_units(lines, words)

    str_items = [u for u in units if u.section_path == ("Summary Project", "Wheeling", "STR")]
    numbered = [u for u in str_items if u.unit_type == "numbered_item"]

    assert len(numbered) == 3
    assert "Reliabi" not in numbered[0].raw_text
    assert "Reliabi" not in numbered[1].raw_text
    assert "lity" not in numbered[1].raw_text
    assert "lity" not in numbered[2].raw_text
    assert numbered[0].raw_text == "1.Execution schedule Wheeling Wheeling_2nd.xlsx"
    assert numbered[1].raw_text == "2.Wheeling Qualification readiness Summary"
