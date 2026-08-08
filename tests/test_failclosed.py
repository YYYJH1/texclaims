"""Regressions for the fail-open holes an adversarial review found.

Each test here describes a way the checker once reported success while a
number was wrong, missing, or unaccounted for.
"""

from __future__ import annotations

import json
import math

import pytest
import yaml

from texclaims.artifact import load_artifact, select
from texclaims.audit import run_check
from texclaims.cli import main
from texclaims.coverage import run_scan
from texclaims.document import NUMBER_RE, parse_number
from texclaims.errors import LedgerError
from texclaims.ledger import load_ledger

TEX = r"""\documentclass{article}
\begin{document}
\section{Evaluation}
%s
\end{document}
"""


def _ledger(project, body, claims, artifacts=None, scan=True, **extra):
    ledger = {"sources": {"summary": "results/summary.json"}, "claims": claims, **extra}
    if scan:
        ledger["scan"] = {"regions": [{"file": "paper.tex",
                                       "start": r"\section{Evaluation}"}]}
    return project(
        documents={"paper.tex": TEX % body},
        artifacts=artifacts or {"results/summary.json": {"value": 94.2}},
        ledger=ledger,
    )


def _claim(**kw):
    base = {"name": "c", "file": "paper.tex", "expect": 1, "value": "summary:.value"}
    return {**base, **kw}


def _unmapped(state):
    return [r.claimed for r in state.report.records if r.status == "UNMAPPED"]


# --- the number grammar must see numbers that carry units -------------------

@pytest.mark.parametrize(
    "text,expected",
    [
        ("latency of 120ms", ["120"]),
        ("a 2.4x speedup", ["2.4"]),
        ("a 7B model", ["7"]),
        ("64GB of memory", ["64"]),
        ("3GHz clock", ["3"]),
        ("1.2M tokens", ["1.2"]),
        (r"$4.87 \pm 0.51$", ["4.87", "0.51"]),
        ("a p-value of .05", [".05"]),
    ],
)
def test_numbers_glued_to_letters_still_tokenize(text, expected):
    """A trailing-\\w guard once erased this whole category from the scan."""
    assert [m.group(0) for m in NUMBER_RE.finditer(text)] == expected


@pytest.mark.parametrize("text", ["upgrade to v2", "run seed42", "version 1.2.3",
                                  "open file2.txt", "plot x1.png"])
def test_identifiers_are_still_not_numbers(text):
    assert [m.group(0) for m in NUMBER_RE.finditer(text)] == []


def test_leading_dot_decimal_carries_its_precision():
    parsed = parse_number(".05")
    assert (parsed.value, parsed.decimals) == (0.05, 2)


def test_unit_bearing_number_is_reported_unmapped(project):
    path = _ledger(project, "Accuracy is 94.2\\% at 999ms latency.",
                   [_claim(anchor={"template": r"is {num}\%"})])
    assert _unmapped(run_scan(load_ledger(path))) == ["999"]


def test_control_word_does_not_hide_the_number_after_it(project):
    path = _ledger(project, r"Accuracy is 94.2\% ($\pm0.99$ across seeds).",
                   [_claim(anchor={"template": r"is {num}\%"})])
    assert _unmapped(run_scan(load_ledger(path))) == ["0.99"]


def test_spaced_measurement_is_not_mistaken_for_a_dimension(project):
    path = _ledger(project, "Accuracy is 94.2\\% with 9.9 cm antennas.",
                   [_claim(anchor={"template": r"is {num}\%"})])
    assert _unmapped(run_scan(load_ledger(path))) == ["9.9"]


# --- a capture must be the whole number, not a convenient part of it --------

def test_capture_that_truncates_the_number_is_rejected(project):
    """Capturing "88" out of "88.9" once passed, and widened the tolerance."""
    path = _ledger(project, "Accuracy is 88.9 units.",
                   [_claim(anchor={"pattern": r"is (\d+)"})],
                   artifacts={"results/summary.json": {"value": 88.0}})
    with pytest.raises(LedgerError, match="stops inside it"):
        run_check(load_ledger(path))


def test_capture_that_drops_the_sign_is_rejected(project):
    path = _ledger(project, "The delta is -5.2 units.",
                   [_claim(anchor={"pattern": r"is -([\d.]+)"})],
                   artifacts={"results/summary.json": {"value": 5.2}})
    with pytest.raises(LedgerError, match="starts inside it"):
        run_check(load_ledger(path))


def test_partial_claim_does_not_vouch_for_the_whole_token(project):
    """Coverage only forgives a percent suffix, not missing decimals."""
    path = _ledger(project, "Accuracy is 94.2 units.",
                   [_claim(anchor={"template": "is {num} units"})])
    state = run_scan(load_ledger(path))
    assert _unmapped(state) == []  # the full token is claimed


# --- the ledger itself must not be able to lie ------------------------------

def test_duplicate_yaml_key_is_refused(tmp_path):
    (tmp_path / "paper.tex").write_text(TEX % "Accuracy is 94.2 units.")
    (tmp_path / "results").mkdir()
    (tmp_path / "results/summary.json").write_text(json.dumps({"value": 94.2}))
    ledger = tmp_path / "claims.yaml"
    ledger.write_text(
        "version: 1\n"
        "documents: [paper.tex]\n"
        "sources: {summary: results/summary.json}\n"
        "claims:\n"
        "  - name: real\n"
        "    file: paper.tex\n"
        "    anchor: {template: 'is {num} units'}\n"
        "    expect: 1\n"
        "    value: 'summary:.value'\n"
        "claims:\n"  # a second block would silently delete the first
        "  - name: decoy\n"
        "    file: paper.tex\n"
        "    anchor: {template: 'is {num} units'}\n"
        "    expect: 1\n"
        "    value: 'summary:.value'\n"
    )
    with pytest.raises(LedgerError, match="duplicate key"):
        load_ledger(ledger)


def test_infinite_tolerance_is_refused(project):
    path = _ledger(project, "Accuracy is 94.2 units.",
                   [_claim(anchor={"template": "is {num} units"}, abs_tol=math.inf)])
    with pytest.raises(LedgerError, match="finite"):
        load_ledger(path)


def test_source_outside_the_ledger_tree_is_refused(project):
    path = _ledger(project, "Accuracy is 94.2 units.",
                   [_claim(anchor={"template": "is {num} units"})],
                   sources={"summary": "../outside.json"})
    with pytest.raises(LedgerError, match="escapes the ledger directory"):
        load_ledger(path)


def test_emit_target_cannot_overwrite_a_manuscript(project):
    path = _ledger(project, "Accuracy is 94.2 units.",
                   [_claim(anchor={"template": "is {num} units"})],
                   emit={"output": "paper.tex",
                         "macros": [{"name": "V", "value": "summary:.value"}]})
    with pytest.raises(LedgerError, match="would overwrite it"):
        load_ledger(path)


def test_strict_scan_without_regions_is_refused(project, capsys):
    path = _ledger(project, "Accuracy is 94.2 units.",
                   [_claim(anchor={"template": "is {num} units"})], scan=False)
    assert main(["scan", "--ledger", str(path), "--strict"]) == 2
    assert "at least one region" in capsys.readouterr().err


# --- malformed inputs are configuration errors, never tracebacks ------------

def test_non_utf8_document_is_a_configuration_error(project, capsys):
    path = _ledger(project, "Accuracy is 94.2 units.",
                   [_claim(anchor={"template": "is {num} units"})])
    (path.parent / "paper.tex").write_bytes(b"\xff\xfe not utf-8")
    assert main(["check", "--ledger", str(path)]) == 2
    assert "CONFIG ERROR" in capsys.readouterr().err


def test_duplicate_csv_header_is_a_configuration_error(tmp_path):
    csv_path = tmp_path / "runs.csv"
    csv_path.write_text("seed,acc,acc\n1,0.9,0.8\n")
    with pytest.raises(LedgerError, match="repeats column"):
        load_artifact(csv_path, "sources.runs")


def test_abs_on_a_non_number_is_a_configuration_error():
    with pytest.raises(LedgerError, match="'abs' failed"):
        select({"label": "x"}, ".label | abs")


def test_quoted_key_may_contain_a_pipe():
    assert select({"a|b": 3}, '["a|b"]') == 3.0


def test_non_finite_macro_is_refused(project, capsys):
    path = _ledger(project, "Accuracy is 94.2 units.",
                   [_claim(anchor={"template": "is {num} units"})],
                   artifacts={"results/summary.json": {"value": 94.2,
                                                       "bad": float("nan")}},
                   emit={"output": "numbers.tex",
                         "macros": [{"name": "Bad", "value": "summary:.bad"}]})
    assert main(["generate", "--ledger", str(path)]) == 2
    assert "not a finite number" in capsys.readouterr().err
    assert not (path.parent / "numbers.tex").exists()


# --- a second review pass, reading the fixed code, found these -------------

def test_dimension_keyword_needs_a_word_boundary(project):
    """'bandwidth=999' contains 'width=999' but is not a typesetting dimension."""
    path = _ledger(project, "Accuracy is 94.2\\% at bandwidth=999 Mb/s.",
                   [_claim(anchor={"template": r"is {num}\%"})])
    assert _unmapped(run_scan(load_ledger(path))) == ["999"]


def test_prose_measurement_with_a_glued_unit_is_scanned(project):
    path = _ledger(project, "Accuracy is 94.2\\% with a 9.9mm antenna.",
                   [_claim(anchor={"template": r"is {num}\%"})])
    assert _unmapped(run_scan(load_ledger(path))) == ["9.9"]


def test_percent_inside_verb_is_not_a_comment(project):
    path = _ledger(project,
                   "Accuracy is 94.2\\% here. Literal \\verb|%| then result 777.",
                   [_claim(anchor={"template": r"is {num}\%"})])
    assert _unmapped(run_scan(load_ledger(path))) == ["777"]


def test_two_option_citation_is_masked(project):
    path = _ledger(project,
                   "Accuracy is 94.2\\%. Prior work \\citep[see][p.~2]{2019-smith}.",
                   [_claim(anchor={"template": r"is {num}\%"})])
    assert _unmapped(run_scan(load_ledger(path))) == []


def test_integers_beyond_float_precision_compare_exactly(project):
    path = _ledger(project, "The count is 9007199254740992 items.",
                   [_claim(anchor={"template": "count is {num} items"})],
                   artifacts={"results/summary.json": {"value": 9007199254740993}})
    (record,) = [r for r in run_check(load_ledger(path)).report.records]
    assert record.status == "FAIL"


def test_overflowing_tolerance_cannot_pass(project):
    path = _ledger(project, "The value is -1e308 units.",
                   [_claim(anchor={"template": "value is {num} units"},
                           abs_tol=1.7976931348623157e308)],
                   artifacts={"results/summary.json": {"value": 1e308}})
    (record,) = run_check(load_ledger(path)).report.records
    assert record.status == "FAIL"


def test_booleans_cannot_be_averaged_into_a_number():
    with pytest.raises(LedgerError, match="boolean"):
        select({"flags": [True, True]}, ".flags | mean")


def test_headerless_csv_is_a_configuration_error(tmp_path):
    empty = tmp_path / "runs.csv"
    empty.write_text("")
    with pytest.raises(LedgerError, match="no header"):
        load_artifact(empty, "sources.runs")


def test_out_override_cannot_overwrite_the_manuscript(project, capsys):
    path = _ledger(project, "Accuracy is 94.2 units.",
                   [_claim(anchor={"template": "is {num} units"})],
                   emit={"output": "numbers.tex",
                         "macros": [{"name": "V", "value": "summary:.value"}]})
    before = (path.parent / "paper.tex").read_text(encoding="utf-8")
    assert main(["generate", "--ledger", str(path), "--out", "paper.tex"]) == 2
    assert "would overwrite it" in capsys.readouterr().err
    assert (path.parent / "paper.tex").read_text(encoding="utf-8") == before


def test_out_override_cannot_escape_the_ledger_tree(project, capsys):
    path = _ledger(project, "Accuracy is 94.2 units.",
                   [_claim(anchor={"template": "is {num} units"})],
                   emit={"output": "numbers.tex",
                         "macros": [{"name": "V", "value": "summary:.value"}]})
    assert main(["generate", "--ledger", str(path), "--out", "../escaped.tex"]) == 2
    assert "escapes the ledger directory" in capsys.readouterr().err


def test_emit_output_with_a_dot_prefix_still_guards_the_manuscript(project):
    path = _ledger(project, "Accuracy is 94.2 units.",
                   [_claim(anchor={"template": "is {num} units"})],
                   emit={"output": "./paper.tex",
                         "macros": [{"name": "V", "value": "summary:.value"}]})
    with pytest.raises(LedgerError, match="would overwrite it"):
        load_ledger(path)


def test_init_quotes_an_awkward_filename(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "paper: draft.tex").write_text("Nothing here.\n")
    assert main(["init", "--doc", "paper: draft.tex"]) == 0
    loaded = yaml.safe_load((tmp_path / "claims.yaml").read_text(encoding="utf-8"))
    assert loaded["documents"] == ["paper: draft.tex"]


def test_claim_and_exemption_cannot_share_one_occurrence(project):
    """The claim captures "12.7"; the exemption tokenises "12.7\\%"."""
    path = _ledger(
        project, "Throughput improves by 12.7\\% overall.",
        [{"name": "pct", "file": "paper.tex", "expect": 1,
          "value": "summary:.value",
          "anchor": {"template": r"improves by {num}\%"}}],
        artifacts={"results/summary.json": {"value": 12.7}},
        exemptions=[{"name": "waiver", "file": "paper.tex", "expect": 1,
                     "anchor": {"template": r"by {num}\% overall"},
                     "reason": "Trying to own a number a claim already owns."}],
    )
    records = run_check(load_ledger(path)).report.records
    assert [r.status for r in records] == ["PASS", "FAIL"]
    assert "already claimed" in records[1].note


def test_two_spellings_of_one_document_are_refused(project):
    path = project(
        documents={"paper.tex": TEX % "Accuracy is 94.2 units."},
        artifacts={"results/summary.json": {"value": 94.2}},
        ledger={"sources": {"summary": "results/summary.json"},
                "claims": [_claim(anchor={"template": "is {num} units"})]},
    )
    text = path.read_text(encoding="utf-8").replace(
        "documents:\n- paper.tex\n", "documents:\n- paper.tex\n- ./paper.tex\n")
    path.write_text(text, encoding="utf-8")
    with pytest.raises(LedgerError, match="the same file"):
        load_ledger(path)


def test_sum_does_not_lose_the_result_to_accumulation_error():
    values = {"xs": [1e100, 1.0, -1e100]}
    assert select(values, ".xs | sum") == 1.0


# --- a third review, reading the twice-fixed code, found these --------------

@pytest.mark.parametrize("body,expected", [
    (r"Accuracy is 94.2\% here. Code at \url{https://x.com/a%20b}. Result 777.", ["777"]),
    (r"Accuracy is 94.2\% here. See \href{http://x.com/a%20b}{link} and 777.", ["777"]),
    (r"Accuracy is 94.2\% here. Use \lstinline|a%b| then 777.", ["777"]),
])
def test_literal_percent_does_not_eat_the_rest_of_the_line(project, body, expected):
    """One %20 in a URL once hid every number that followed it."""
    path = _ledger(project, body, [_claim(anchor={"template": r"is {num}\%"})])
    assert _unmapped(run_scan(load_ledger(path))) == expected


def test_number_glued_to_a_control_word_cannot_be_half_captured(project):
    """token_at once looked at a view where \\pm suppressed the number."""
    path = _ledger(project, r"Mean latency is $4.87\pm0.51$ ms.",
                   [_claim(anchor={"pattern": r"\\pm(\d+)"})],
                   artifacts={"results/summary.json": {"value": 0.4}})
    with pytest.raises(LedgerError, match="stops inside it"):
        run_check(load_ledger(path))


def test_exemption_can_waive_a_number_glued_to_a_control_word(project):
    path = _ledger(project, r"Accuracy is 94.2\% ($\pm0.99$ across seeds).",
                   [_claim(anchor={"template": r"is {num}\%"})],
                   exemptions=[{"name": "spread", "file": "paper.tex", "expect": 1,
                                "anchor": {"pattern": r"\\pm(0\.99)"},
                                "reason": "Dispersion, reported alongside the mean."}])
    assert _unmapped(run_scan(load_ledger(path))) == []


def test_number_touching_cjk_text_is_scanned(project):
    """A Unicode \\w guard blinded the scan on Chinese manuscripts."""
    path = _ledger(project, "Accuracy is 94.2\\% overall. 本方法提升了777个单位。",
                   [_claim(anchor={"template": r"is {num}\%"})])
    assert _unmapped(run_scan(load_ledger(path))) == ["777"]


def test_relative_length_is_treated_as_typesetting(project):
    path = _ledger(project,
                   "Accuracy is 94.2\\% overall.\n"
                   r"\begin{minipage}{0.45\textwidth}\end{minipage}",
                   [_claim(anchor={"template": r"is {num}\%"})])
    assert _unmapped(run_scan(load_ledger(path))) == []


def test_generate_cannot_overwrite_an_artifact(project, capsys):
    path = _ledger(project, "Accuracy is 94.2 units.",
                   [_claim(anchor={"template": "is {num} units"})],
                   emit={"output": "numbers.tex",
                         "macros": [{"name": "V", "value": "summary:.value"}]})
    before = (path.parent / "results/summary.json").read_text(encoding="utf-8")
    assert main(["generate", "--ledger", str(path),
                 "--out", "results/summary.json"]) == 2
    assert "the artifact" in capsys.readouterr().err
    assert (path.parent / "results/summary.json").read_text(encoding="utf-8") == before


def test_generate_cannot_overwrite_the_ledger(project, capsys):
    path = _ledger(project, "Accuracy is 94.2 units.",
                   [_claim(anchor={"template": "is {num} units"})],
                   emit={"output": "numbers.tex",
                         "macros": [{"name": "V", "value": "summary:.value"}]})
    assert main(["generate", "--ledger", str(path), "--out", "claims.yaml"]) == 2
    assert "the ledger itself" in capsys.readouterr().err


def test_explicit_tolerance_still_applies_to_huge_integers(project):
    path = _ledger(project, "The count is 9007199254740992 items.",
                   [_claim(anchor={"template": "count is {num} items"},
                           abs_tol=10)],
                   artifacts={"results/summary.json": {"value": 9007199254740995}})
    (record,) = run_check(load_ledger(path)).report.records
    assert record.status == "PASS"


def test_integer_survives_a_scaling_transform(project):
    path = _ledger(project, "The count is 18014398509481984 items.",
                   [_claim(anchor={"template": "count is {num} items"},
                           transform={"scale": 2})],
                   artifacts={"results/summary.json": {"value": 9007199254740992}})
    (record,) = run_check(load_ledger(path)).report.records
    assert record.status == "PASS"


def test_non_finite_csv_value_is_refused(tmp_path):
    csv_path = tmp_path / "runs.csv"
    csv_path.write_text("seed,acc\n1,0.9\n2,nan\n")
    rows = load_artifact(csv_path, "sources.runs")
    with pytest.raises(LedgerError, match="non-finite"):
        select({"rows": rows}, ".rows[] | .acc | max")


def test_csv_with_a_byte_order_mark_is_addressable(tmp_path):
    csv_path = tmp_path / "runs.csv"
    csv_path.write_text("\ufeffseed,acc\n1,0.9\n", encoding="utf-8")
    rows = load_artifact(csv_path, "sources.runs")
    assert rows[0]["seed"] == 1


def test_json_artifact_with_a_repeated_key_is_refused(tmp_path):
    art = tmp_path / "summary.json"
    art.write_text('{"value": 1, "value": 2}')
    with pytest.raises(LedgerError, match="repeats key"):
        load_artifact(art, "sources.summary")


def test_unlisted_include_warns_rather_than_refusing(project):
    """A hard error here made generate unusable on any paper that does
    \\input{numbers}, and refused to run over package names entirely."""
    path = _ledger(project, r"Accuracy is 94.2 units. \input{appendix}",
                   [_claim(anchor={"template": "is {num} units"})])
    ledger = load_ledger(path)
    assert ledger.unlisted_includes == ["appendix"]
    warnings = run_scan(ledger).report.warnings
    assert any("appendix" in w and "not in 'documents'" in w for w in warnings)


def test_strict_scan_refuses_an_unscanned_document(project, capsys):
    path = project(
        documents={"paper.tex": TEX % "Accuracy is 94.2 units.",
                   "appendix.tex": "Nothing numeric here.\n"},
        artifacts={"results/summary.json": {"value": 94.2}},
        ledger={"sources": {"summary": "results/summary.json"},
                "claims": [_claim(anchor={"template": "is {num} units"})],
                "scan": {"regions": [{"file": "paper.tex"}]}},
    )
    assert main(["scan", "--ledger", str(path), "--strict"]) == 2
    assert "no scan region" in capsys.readouterr().err


@pytest.mark.parametrize("body", [
    "Accuracy is 94.2 units.\n% \\input{old-section}",
    "Accuracy is 94.2 units.\n\\begin{verbatim}\n\\input{example}\n\\end{verbatim}",
])
def test_input_in_a_comment_or_verbatim_is_not_a_real_include(project, body):
    """Rejecting a ledger over a commented-out \\input would make the tool
    unusable on any real paper."""
    path = _ledger(project, body, [_claim(anchor={"template": "is {num} units"})])
    assert load_ledger(path).documents == ["paper.tex"]


def test_thousands_separated_number_is_one_token(project):
    """It was once claimed and reported unaccounted at the same time."""
    path = _ledger(project, "We used 1,000 prompts.",
                   [_claim(anchor={"template": "used {num} prompts"})],
                   artifacts={"results/summary.json": {"value": 1000}})
    state = run_scan(load_ledger(path))
    assert [r.status for r in state.report.records] == ["PASS"]


def test_capture_inside_a_masked_region_is_still_guarded(project):
    """token_at reads scan_masked first; where that view is blank it must fall
    back rather than wave the capture through."""
    path = _ledger(project, "Held out 0.459 of the data.",
                   [_claim(anchor={"pattern": r"out (0\.45)"})],
                   artifacts={"results/summary.json": {"value": 0.45}})
    with pytest.raises(LedgerError, match="stops inside it"):
        run_check(load_ledger(path))


@pytest.mark.parametrize("body", [
    "Accuracy is 94.2 units.\n\\begin{comment}\n\\input{old}\n\\end{comment}",
    "Accuracy is 94.2 units.\n\\iffalse\n\\input{old}\n\\fi",
])
def test_input_in_excluded_blocks_is_not_a_real_include(project, body):
    path = _ledger(project, body, [_claim(anchor={"template": "is {num} units"})])
    assert load_ledger(path).unlisted_includes == []


def test_braceless_input_is_noticed(project):
    """\\input file is the TeX primitive form and loads file.tex just the same."""
    path = _ledger(project, "Accuracy is 94.2 units.\n\\input appendix",
                   [_claim(anchor={"template": "is {num} units"})])
    assert load_ledger(path).unlisted_includes == ["appendix"]


def test_the_emitted_macro_file_is_not_warned_about(project):
    """texclaims wrote numbers.tex itself; warning that it is unaudited is noise
    on every single run of the workflow the README recommends."""
    path = _ledger(project, "Accuracy is 94.2 units.\n\\input{numbers}",
                   [_claim(anchor={"template": "is {num} units"})],
                   emit={"output": "numbers.tex",
                         "macros": [{"name": "V", "value": "summary:.value"}]})
    assert load_ledger(path).unlisted_includes == []


@pytest.mark.parametrize("name", ["includegraphics{fig1}", "includeonly{a}",
                                  "inputencoding{utf8}"])
def test_lookalike_commands_are_not_includes(project, name):
    """Every paper has figures; a junk warning on each one teaches the reader
    to ignore warnings."""
    path = _ledger(project, f"Accuracy is 94.2 units. \\{name}",
                   [_claim(anchor={"template": "is {num} units"})])
    assert load_ledger(path).unlisted_includes == []


def test_strict_refuses_a_section_file_that_exists_but_is_unlisted(project, capsys):
    """Warning was not enough: --strict exited 0 while a whole file went
    unaudited, which is the hole the gate exists to close."""
    path = project(
        documents={"paper.tex": TEX % "Accuracy is 94.2 units.\n\\input{sections/more}",
                   "sections/more.tex": "Latency was 999 ms.\n"},
        artifacts={"results/summary.json": {"value": 94.2}},
        ledger={"sources": {"summary": "results/summary.json"},
                "claims": [_claim(anchor={"template": "is {num} units"})],
                "scan": {"regions": [{"file": "paper.tex"}]}},
    )
    # documents lists only paper.tex, so sections/more.tex is a real hole.
    text = path.read_text(encoding="utf-8").replace(
        "documents:\n- paper.tex\n- sections/more.tex\n", "documents:\n- paper.tex\n")
    path.write_text(text, encoding="utf-8")
    assert main(["scan", "--ledger", str(path), "--strict"]) == 2
    assert "exists in this project" in capsys.readouterr().err


def test_a_package_name_only_warns(project):
    """\\input{glyphtounicode} names a package, not a forgotten section."""
    path = _ledger(project, "Accuracy is 94.2 units.\n\\input{glyphtounicode}",
                   [_claim(anchor={"template": "is {num} units"})])
    ledger = load_ledger(path)
    assert ledger.unlisted_includes == ["glyphtounicode"]
    assert ledger.missing_sections == []


@pytest.mark.parametrize("text,expected", [
    ("(6,36,600)", ["6", "36", "600"]),          # a tuple, not one number
    ("We used 1,000 prompts", ["1,000"]),        # prose thousands still work
    ("1,234,567 rows", ["1,234,567"]),
    ("36{,}600 items", ["36{,}600"]),            # LaTeX's own thousands form
    ("range 3--5 units", ["3", "5"]),            # an en-dash, not a minus
    ("delta of -5.2", ["-5.2"]),
    ("(-5) and (+3)", ["-5", "+3"]),
])
def test_latex_numeric_conventions(text, expected):
    """Reading 36,600 out of the tuple (6,36,600) audits a number the
    manuscript never printed, and leaves the real 36 unclaimable."""
    assert [m.group(0) for m in NUMBER_RE.finditer(text)] == expected


def test_latex_thousands_parse_to_their_value():
    assert parse_number("36{,}600").value == 36600.0


def test_an_empty_ledger_loads_but_cannot_pass_strict(project, capsys):
    """The documented first step is an empty ledger that scan fills in; it has
    to load, and --strict has to refuse it."""
    path = project(
        documents={"paper.tex": TEX % "Accuracy is 94.2 units."},
        artifacts={"results/summary.json": {"value": 94.2}},
        ledger={"sources": {"summary": "results/summary.json"}, "claims": [],
                "scan": {"regions": [{"file": "paper.tex"}]}},
    )
    assert load_ledger(path).claims == []
    assert main(["scan", "--ledger", str(path)]) == 0        # exploratory run
    assert main(["scan", "--ledger", str(path), "--strict"]) == 2
    assert "claims nothing" in capsys.readouterr().err
