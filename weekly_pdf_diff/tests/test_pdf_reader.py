from pdf_reader import _dominant_span_font_size, extract_lines, extract_words


def test_dominant_span_font_size_ignores_short_differently_fonted_prefix():
    """実PDF検証で発見した不具合の再現テスト。

    自動採番の"1."がYuGothic-Regular・12ptで描画され、本文がArial・11.04ptで
    描画されているケースを再現する。行の代表フォントサイズは、文字数の多い
    本文側(11.04)を採用すべきで、先頭span("1.", 12.0)を採用してはいけない。
    """
    spans = [
        {"text": "1.", "size": 12.0, "font": "YuGothic-Regular"},
        {"text": " ", "size": 11.04, "font": "Arial"},
        {"text": "Align and prepare shipment Wheeling HTOL board.", "size": 11.04, "font": "Arial"},
    ]

    assert _dominant_span_font_size(spans) == 11.04


def test_extract_lines_uses_dominant_span_size_end_to_end(build_pdf):
    pdf_path, doc = build_pdf([[("Work Plan", True), ("1. Just one span here.", False)]])
    lines = extract_lines(doc)

    body_line = next(l for l in lines if "Just one span" in l.text)
    assert body_line.font_size == 11.0


def test_extract_words_sorted_by_page_then_position(build_pdf):
    pdf_path, doc = build_pdf([[("second line", False)], [("first of next page", False)]])
    words = extract_words(doc)

    pages = [w.page for w in words]
    assert pages == sorted(pages)
