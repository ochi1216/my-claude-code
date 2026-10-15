import fitz

from models import DiffResult, TextUnit
from pdf_reader import extract_words
from render import render_diff


def _unit_from_words(words, text):
    return TextUnit(("A",), "paragraph", text, text, 11.0, words)


def test_original_text_is_removed_and_blue_bold_is_drawn():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 100), "will arrive", fontname="helv", fontsize=11)
    words = extract_words(doc)

    unit = _unit_from_words(words, "will arrive")
    result = DiffResult(unit, None, "modified", 90.0, words, False)
    render_diff(doc, [result])

    spans = [
        (s["text"], s["color"], s["flags"])
        for block in page.get_text("dict")["blocks"]
        for line in block.get("lines", [])
        for s in line["spans"]
    ]
    leftover_original = [s for s in spans if s[0].strip() and s[1] == 0 and s[2] == 0]
    assert not leftover_original, f"元の黒文字が残っている: {leftover_original}"
    assert any(flags & 16 for _, _color, flags in spans), "太字が描画されていない"


def test_existing_link_survives_redaction(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 100), "click here", fontname="helv", fontsize=11)
    link_rect = fitz.Rect(50, 88, 96, 104)
    page.insert_link({"kind": fitz.LINK_URI, "from": link_rect, "uri": "https://example.com"})

    src_path = tmp_path / "src.pdf"
    doc.save(src_path)
    doc2 = fitz.open(src_path)
    words = extract_words(doc2)
    unit = _unit_from_words(words, "click here")
    result = DiffResult(unit, None, "added", 0.0, [], True)

    render_diff(doc2, [result])

    out_path = tmp_path / "out.pdf"
    doc2.save(out_path)
    doc3 = fitz.open(out_path)
    links = doc3[0].get_links()
    assert len(links) == 1
    assert links[0]["uri"] == "https://example.com"


def test_erase_samples_background_fill_color_not_white():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    light_blue = (0.757, 0.894, 0.961)
    page.draw_rect(fitz.Rect(40, 85, 200, 110), color=light_blue, fill=light_blue, width=0)
    page.insert_text((50, 100), "status", fontname="helv", fontsize=11)
    words = extract_words(doc)

    unit = _unit_from_words(words, "status")
    result = DiffResult(unit, None, "added", 0.0, [], True)
    render_diff(doc, [result])

    fills = [d.get("fill") for d in page.get_drawings() if d.get("fill")]
    assert any(abs(f[0] - light_blue[0]) < 0.01 for f in fills), "背景が白で消去されている（薄い青が検出されていない）"


def test_bold_overflow_is_shrunk_to_fit_original_width():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    long_word = "Wheeling_Qualification_Readiness_Summary.pptx"
    page.insert_text((50, 100), long_word, fontname="helv", fontsize=11)
    words = extract_words(doc)
    original_width = words[0].x1 - words[0].x0

    unit = _unit_from_words(words, long_word)
    result = DiffResult(unit, None, "added", 0.0, words, True)
    render_diff(doc, [result])

    spans = [
        s
        for block in page.get_text("dict")["blocks"]
        for line in block.get("lines", [])
        for s in line["spans"]
        if s["text"].strip()
    ]
    assert len(spans) == 1
    rendered_width = spans[0]["bbox"][2] - spans[0]["bbox"][0]
    assert rendered_width <= original_width + 1.0, "太字化後の幅が元の単語幅をはみ出している"
    assert spans[0]["size"] >= 11.0 * 0.9, "フォントサイズの縮小が10%を超えている"


def test_deleted_and_unchanged_are_not_rendered():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 100), "untouched text", fontname="helv", fontsize=11)
    words = extract_words(doc)

    unit = _unit_from_words(words, "untouched text")
    results = [
        DiffResult(unit, unit, "unchanged", 100.0, [], False),
        DiffResult(None, unit, "deleted", 0.0, [], False),
    ]
    render_diff(doc, results)

    spans = [
        s
        for block in page.get_text("dict")["blocks"]
        for line in block.get("lines", [])
        for s in line["spans"]
    ]
    assert any(s["text"] == "untouched text" and s["flags"] == 0 for s in spans)


def test_adjacent_words_stay_visually_separated_after_bold_rendering():
    """実PDF検証で発見した不具合の再現テスト。

    実データのように単語間の隙間が非常に狭い(2〜3pt程度)場合、太字化で単語幅が
    広がり隙間を食いつぶして隣の単語と接触して見えてしまっていた。狭い間隔の
    単語列を合成し、太字描画後も get_text("words") で別々の単語として認識できる
    （＝視覚的な隙間が残っている）ことを確認する。
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    # 実データ相当の間隔(数pt)でXOffsetsを制御するため、単語ごとに個別配置する
    x = 72.0
    y = 500.0
    for word in ["Align", "and", "prepare"]:
        page.insert_text((x, y), word, fontname="helv", fontsize=12)
        width = fitz.get_text_length(word, fontname="helv", fontsize=12)
        x += width + 3.0  # 実データ相当の狭い間隔(3pt)

    words = extract_words(doc)
    assert len(words) == 3, f"事前条件: 3単語に分かれているはず: {[w.text for w in words]}"

    unit = _unit_from_words(words, "Align and prepare")
    result = DiffResult(unit, None, "added", 0.0, [], True)
    render_diff(doc, [result])

    rendered_words = extract_words(doc)
    assert len(rendered_words) == 3, (
        f"太字化後に単語が結合して1〜2語に減っている（隙間が消えている）: "
        f"{[w.text for w in rendered_words]}"
    )
    # 太字化後の最終フォントサイズは単語ごとに微妙に異なりうる(縮小率が違うため)ため、
    # Y座標のわずかな差でextract_wordsの既定ソート順が変わることがある。
    # ここではX座標で並べ替えた上で、語順と語間の隙間そのものを検証する。
    by_x = sorted(rendered_words, key=lambda w: w.x0)
    assert [w.text for w in by_x] == ["Align", "and", "prepare"]
    for prev_w, next_w in zip(by_x, by_x[1:]):
        gap = next_w.x0 - prev_w.x1
        assert gap > 0, f"{prev_w.text!r}と{next_w.text!r}の間に隙間がない(gap={gap:.2f})"
