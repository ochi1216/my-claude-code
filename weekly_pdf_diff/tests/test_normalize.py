from normalize import normalize_text


def test_collapses_whitespace_and_newlines():
    assert normalize_text("Received  socket.\nEndorsed to Rel Lab.") == (
        "Received socket. Endorsed to Rel Lab."
    )


def test_strips_bullet_and_numbered_markers():
    assert normalize_text("  • Wheeling  ") == "Wheeling"
    assert normalize_text("- Wheeling") == "Wheeling"
    assert normalize_text("1. Wheeling") == "Wheeling"
    assert normalize_text("2) Wheeling") == "Wheeling"


def test_unifies_dash_and_prolonged_sound_mark_variants():
    assert normalize_text("ETD – test") == normalize_text("ETD — test") == normalize_text("ETD - test")


def test_marker_only_difference_is_not_a_diff():
    assert normalize_text("• Foo") == normalize_text("- Foo") == normalize_text("* Foo")
