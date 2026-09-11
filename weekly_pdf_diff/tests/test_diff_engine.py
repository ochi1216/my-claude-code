from diff_engine import _word_diff, pair_units
from models import TextUnit
from normalize import normalize_text
from pdf_reader import Word


def _unit(section_path: tuple, text: str) -> TextUnit:
    tokens = text.split()
    words = [
        Word(page=0, x0=i * 10.0, y0=0.0, x1=i * 10.0 + 8.0, y1=10.0, text=t)
        for i, t in enumerate(tokens)
    ]
    return TextUnit(
        section_path=section_path,
        unit_type="paragraph",
        raw_text=text,
        normalized_text=normalize_text(text),
        font_size=11.0,
        words=words,
    )


def test_exact_match_same_section_is_unchanged():
    prev = [_unit(("A",), "This line stays exactly the same.")]
    curr = [_unit(("A",), "This line stays exactly the same.")]

    result = pair_units(prev, curr)[0]

    assert result.change_type == "unchanged"
    assert result.similarity == 100.0
    assert result.changed_words == []


def test_exact_match_different_section_is_moved():
    prev = [_unit(("A",), "Identical unchanged text moved elsewhere.")]
    curr = [_unit(("B",), "Identical unchanged text moved elsewhere.")]

    result = pair_units(prev, curr)[0]

    assert result.change_type == "moved"


def test_similar_text_flags_only_changed_words():
    prev = [_unit(("A",), "ESD socket will arrive on 21st July.")]
    curr = [_unit(("A",), "ESD socket was received on 21st July.")]

    result = pair_units(prev, curr)[0]

    assert result.change_type == "modified"
    assert result.whole_unit is False
    assert [w.text for w in result.changed_words] == ["was", "received"]


def test_unrelated_current_unit_is_added():
    prev = [_unit(("A",), "This will be deleted next week.")]
    curr = [_unit(("A",), "Totally brand new content never seen before at all now.")]

    results = pair_units(prev, curr)
    change_types = {r.change_type for r in results}

    assert "added" in change_types
    assert "deleted" in change_types


def test_unmatched_prev_unit_is_deleted_not_rendered():
    prev = [_unit(("A",), "This line will disappear.")]
    curr: list[TextUnit] = []

    results = pair_units(prev, curr)

    assert len(results) == 1
    assert results[0].change_type == "deleted"
    assert results[0].curr_unit is None
    assert results[0].prev_unit is prev[0]


def test_word_diff_falls_back_to_whole_unit_when_mostly_rewritten():
    prev = _unit(("A",), "aaa bbb ccc ddd eee")
    curr = _unit(("A",), "xxx yyy zzz www eee")  # 4/5語が変更 (>60%)

    changed_words, whole_unit = _word_diff(prev, curr)

    assert whole_unit is True
    assert changed_words == []


def test_word_diff_keeps_word_level_precision_for_minor_edit():
    prev = _unit(("A",), "The quick brown fox jumps over the lazy dog")
    curr = _unit(("A",), "The quick brown fox leaps over the lazy dog")  # 1/9語

    changed_words, whole_unit = _word_diff(prev, curr)

    assert whole_unit is False
    assert [w.text for w in changed_words] == ["leaps"]
