from app.theme import _highlight


def test_highlight_marks_the_whole_value_not_a_digit_run_inside_a_date():
    marked = _highlight("MD4L07 01/2028 28 10/04/2025", "28")

    assert marked == "MD4L07 01/2028 <mark>28</mark> 10/04/2025"


def test_highlight_escapes_markup_and_skips_missing_values():
    assert _highlight("<b>28</b>", "28") == "&lt;b&gt;<mark>28</mark>&lt;/b&gt;"
    assert _highlight("no match here", "MD4L07") == "no match here"
    assert _highlight("anything", None) == "anything"
