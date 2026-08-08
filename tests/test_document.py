"""Number-token grammar, parsing, and offset-preserving masking."""

from __future__ import annotations

import pytest

from texclaims.document import NUMBER_RE, Document, parse_number
from texclaims.errors import LedgerError


def tokens(text: str) -> list[str]:
    return [m.group(0) for m in NUMBER_RE.finditer(text)]


@pytest.fixture
def make_doc(project):
    """Write one document into a throwaway project tree and load it."""

    def build(name: str, text: str) -> Document:
        ledger_path = project(documents={name: text}, artifacts={}, ledger={"claims": []})
        return Document(ledger_path.parent, name)

    return build


# --- number-token grammar ---------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("we ran 42 trials", ["42"]),
        ("hit rate 94.2 overall", ["94.2"]),
        ("delta of -7 points", ["-7"]),
        ("delta of -0.51 points", ["-0.51"]),
        ("delta of \u22120.51 points", ["\u22120.51"]),
        ("gain of +3.5 points", ["+3.5"]),
        ("1,234 requests", ["1,234"]),
        ("12,345,678 requests", ["12,345,678"]),
        ("p is 1.5e-3 here", ["1.5e-3"]),
        ("p is 2E+8 here", ["2E+8"]),
        ("p is 1e4 here", ["1e4"]),
        ("94.2% hit rate", ["94.2%"]),
        (r"94.2\% hit rate", [r"94.2\%"]),
        (r"-1.5\% drift", [r"-1.5\%"]),
        ("from 4.87 to 3.21 ms", ["4.87", "3.21"]),
    ],
)
def test_number_re_matches_supported_token_forms(text, expected):
    assert tokens(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "upgrade to v2 today",
        "run seed42 again",
        "version 1.2.3 released",
        "open file2.txt now",
        "plot x1.png attached",
    ],
)
def test_digits_inside_identifiers_are_not_tokens(text):
    assert tokens(text) == []


def test_decimal_continuation_yields_no_partial_token():
    assert tokens("the 1.2.3 tag") == []


def test_sentence_final_period_is_allowed_after_a_number():
    assert tokens("We used 42. Then we stopped.") == ["42"]


def test_sentence_final_period_is_not_part_of_the_token():
    match = NUMBER_RE.search("throughput rose 12.7. Next")
    assert match.group(0) == "12.7"
    assert match.span() == (16, 20)


def test_percent_token_span_includes_the_escaped_percent():
    match = NUMBER_RE.search(r"rate of 94.2\% today")
    assert match.group(0) == r"94.2\%"
    assert match.span() == (8, 14)


# --- parse_number -----------------------------------------------------------


@pytest.mark.parametrize(
    "token, value, decimals",
    [
        ("42", 42.0, 0),
        ("3.14", 3.14, 2),
        ("-0.500", -0.5, 3),
        ("\u22120.5", -0.5, 1),
        ("+3.5", 3.5, 1),
        ("1,234", 1234.0, 0),
        ("\u22121,500.25", -1500.25, 2),
        ("94.2%", 94.2, 1),
        (r"12.7\%", 12.7, 1),
    ],
)
def test_parse_number_reads_value_and_display_precision(token, value, decimals):
    parsed = parse_number(token)
    assert parsed.value == pytest.approx(value)
    assert parsed.decimals == decimals


@pytest.mark.parametrize(
    "token, value, decimals",
    [
        ("1.5e-3", 0.0015, 4),
        ("1.5e3", 1500.0, -2),
        ("1e-4", 0.0001, 4),
        ("2E+8", 2e8, -8),
    ],
)
def test_parse_number_shifts_decimals_by_the_exponent(token, value, decimals):
    parsed = parse_number(token)
    assert parsed.value == pytest.approx(value)
    assert parsed.decimals == decimals


def test_parse_number_keeps_the_captured_token_verbatim():
    assert parse_number(r" 12.7\% ").token == r" 12.7\% "


def test_parse_number_rejects_non_numeric_text():
    with pytest.raises(LedgerError) as exc:
        parse_number("twelve")
    assert "not a number" in str(exc.value)


# --- masking ----------------------------------------------------------------


def test_tex_comment_and_its_numbers_are_masked(make_doc):
    doc = make_doc("paper.tex", "Throughput rose 12.7 points. % stale note: 99.9\n")
    assert tokens(doc.masked) == ["12.7"]
    assert "stale note" not in doc.masked
    assert "99.9" in doc.raw


def test_escaped_percent_does_not_start_a_comment(make_doc):
    doc = make_doc("paper.tex", "Hit rate is 94.2\\% across 5 seeds.\n")
    assert tokens(doc.masked) == ["94.2\\%", "5"]
    assert "across 5 seeds" in doc.masked


def test_escaped_backslash_before_percent_starts_a_comment(make_doc):
    doc = make_doc("paper.tex", "Value 42 \\\\% hidden 99\n")
    assert tokens(doc.masked) == ["42"]
    assert "hidden" not in doc.masked
    assert doc.masked.startswith("Value 42 \\\\ ")


def test_structural_macro_arguments_are_masked(make_doc):
    doc = make_doc(
        "paper.tex",
        "See \\cite{smith2024} and \\ref{fig3} and \\includegraphics{x1.png};\n"
        "the gain is 12.7 points.\n",
    )
    assert tokens(doc.masked) == ["12.7"]
    for hidden in ("smith2024", "fig3", "x1.png"):
        assert hidden not in doc.masked
        assert hidden in doc.raw


def test_includegraphics_optional_argument_is_masked(make_doc):
    doc = make_doc(
        "paper.tex",
        "\\includegraphics[width=0.5\\textwidth]{plot1.png}\nAccuracy 94.2\\%.\n",
    )
    assert tokens(doc.masked) == ["94.2\\%"]


def test_href_masks_the_url_but_keeps_the_link_text(make_doc):
    doc = make_doc("paper.tex", "See \\href{http://x.test/v1/9}{run 5}.\n")
    assert tokens(doc.masked) == ["5"]
    assert "x.test" not in doc.masked
    assert "run 5" in doc.masked


def test_masking_preserves_length_and_only_blanks_characters(make_doc):
    doc = make_doc(
        "paper.tex",
        "Intro 12.7\\% gain. % note 99.9\n"
        "See \\cite{smith2024} for 4.87 ms.\n"
        "Rule of 12pt and width=0.5 here.\n",
    )
    for view in (doc.masked, doc.scan_masked):
        assert len(view) == len(doc.raw)
        assert all(m == r or m == " " for m, r in zip(view, doc.raw))


def test_line_of_reports_one_based_lines_for_masked_tokens(make_doc):
    doc = make_doc(
        "paper.tex",
        "Intro line with 12.7\\% gain.\n"
        "% masked comment holding 99.9\n"
        "Latency drops to 3.21 ms.\n",
    )
    located = [(m.group(0), doc.line_of(m.start())) for m in NUMBER_RE.finditer(doc.masked)]
    assert located == [("12.7\\%", 1), ("3.21", 3)]


def test_line_of_maps_offsets_around_newlines(make_doc):
    doc = make_doc("paper.tex", "alpha\nbeta\ngamma\n")
    first_newline = doc.raw.index("\n")
    assert doc.line_of(0) == 1
    assert doc.line_of(first_newline) == 1
    assert doc.line_of(first_newline + 1) == 2
    assert doc.line_of(doc.raw.index("gamma")) == 3


def test_scan_mask_hides_typesetting_dimensions(make_doc):
    doc = make_doc(
        "paper.tex",
        "A rule of 12pt with width=0.5 and 7 cm margins; accuracy 94.2\\%.\n",
    )
    # Only "width=0.5" sits where LaTeX takes a dimension. A bare "12pt" or
    # "7 cm" in prose could be a measurement, so the scan still surfaces them
    # and the author waives them once with an exemption.
    assert tokens(doc.masked) == ["12", "0.5", "7", "94.2\\%"]
    assert tokens(doc.scan_masked) == ["12", "7", "94.2\\%"]
    assert "width=0.5" in doc.masked and "width=0.5" not in doc.scan_masked


def test_markdown_keeps_percent_and_is_not_comment_masked(make_doc):
    doc = make_doc("paper.md", "Hit rate 94.2% here. % not a comment 88.8\n")
    assert doc.masked == doc.raw
    assert tokens(doc.masked) == ["94.2%", "88.8"]


def test_markdown_is_never_masked(make_doc):
    """Markdown has no TeX grammar, so nothing is masked away — as documented."""
    doc = make_doc("notes.md", "Figure at width=0.5 shows 94.2% hit rate.\n")
    assert doc.scan_masked == doc.raw
    assert tokens(doc.scan_masked) == ["0.5", "94.2%"]


def test_snippet_collapses_whitespace_around_the_span(make_doc):
    doc = make_doc("paper.tex", "Latency drops\n   from 4.87 ms\n   to 3.21 ms.\n")
    start = doc.raw.index("4.87")
    assert doc.snippet(start, start + 4, radius=12) == "ops from 4.87 ms to 3."


def test_unreadable_document_raises_ledger_error_with_path(make_doc, project):
    ledger_path = project(documents={"paper.tex": "x\n"}, artifacts={}, ledger={"claims": []})
    with pytest.raises(LedgerError) as exc:
        Document(ledger_path.parent, "missing.tex")
    assert exc.value.path == "missing.tex"
    assert "cannot read document" in str(exc.value)


def test_prose_number_before_the_word_in_is_still_scanned(make_doc):
    doc = make_doc("paper.tex", "The speedup is 5 in the tuned configuration.\n")
    assert tokens(doc.scan_masked) == ["5"]


def test_scan_mask_preserves_newlines(make_doc):
    doc = make_doc("paper.tex", "Margin is 0.5\ncm wide.\nAccuracy 94.2\\%.\n")
    assert doc.scan_masked.count("\n") == doc.raw.count("\n")
