"""Anchor compilation and matching: template, pattern, and near."""

from __future__ import annotations

import pytest

from texclaims.anchor import compile_template, find_anchor_matches
from texclaims.audit import run_check
from texclaims.cli import main
from texclaims.coverage import run_scan
from texclaims.document import Document
from texclaims.errors import LedgerError
from texclaims.ledger import Anchor, load_ledger


def _doc(tmp_path, text, name="paper.tex"):
    (tmp_path / name).write_text(text, encoding="utf-8")
    return Document(tmp_path, name)


def _ledger(project, doc_text, claims, *, summary=None, patterns=None, scan=None):
    ledger = {"sources": {"summary": "results/summary.json"}, "claims": claims}
    if patterns is not None:
        ledger["patterns"] = patterns
    if scan is not None:
        ledger["scan"] = scan
    return project(
        documents={"paper.tex": doc_text},
        artifacts={"results/summary.json": summary or {}},
        ledger=ledger,
    )


def _records(ledger_path):
    return run_check(load_ledger(ledger_path)).report.records


# --- template ---------------------------------------------------------------

def test_template_num_compiles_to_a_capture_group():
    compiled = compile_template(r"throughput by {num}\%", "t")
    assert compiled.groups == 1
    assert compiled.search(r"throughput by 12.7\%").group(1) == "12.7"


def test_template_num_captures_signed_and_grouped_tokens():
    compiled = compile_template("delta of {num} units", "t")
    for token in ("-3", "1,234", "4.5e-3", "\u22120.7"):
        assert compiled.search(f"delta of {token} units").group(1) == token


def test_template_literal_space_matches_any_whitespace_run():
    compiled = compile_template("across {num} seeds", "t")
    assert compiled.search("across\n  5\tseeds").group(1) == "5"


def test_template_matches_across_a_line_break(project):
    path = _ledger(
        project,
        "FastCache improves end-to-end throughput\nby 12.7\\% over the baseline.\n",
        [{"name": "headline", "file": "paper.tex",
          "anchor": {"template": r"improves end-to-end throughput by {num}\%"},
          "expect": 1, "value": "summary:.pct"}],
        summary={"pct": 12.7},
    )
    (record,) = _records(path)
    assert (record.status, record.claimed, record.line) == ("PASS", "12.7", 2)


def test_template_escapes_regex_metacharacters():
    compiled = compile_template(r"v1.2 (tuned) reports {num}\%", "t")
    assert compiled.groups == 1, "parentheses must be literal, not a capture group"
    assert compiled.search(r"v1.2 (tuned) reports 9\%") is not None
    assert compiled.search(r"v1x2 (tuned) reports 9\%") is None
    assert compiled.search(r"v1.2 (tuned) reports 9%") is None


def test_template_percent_escape_survives_tex_comment_masking(project):
    path = _ledger(
        project,
        "Gain (net) is 12.7\\% here. % stale note: 99.9\n",
        [{"name": "gain", "file": "paper.tex",
          "anchor": {"template": r"Gain (net) is {num}\%"},
          "expect": 1, "value": "summary:.pct"}],
        summary={"pct": 12.7},
    )
    (record,) = _records(path)
    assert (record.status, record.claimed) == ("PASS", "12.7")


def test_template_with_two_num_placeholders_yields_two_groups(project):
    assert compile_template("from {num} to {num} ms", "t").groups == 2
    path = _ledger(
        project,
        "Latency drops from 4.87 to 3.21 ms.\n",
        [{"name": "latency", "file": "paper.tex",
          "anchor": {"template": "from {num} to {num} ms"}, "expect": 1,
          "groups": {1: "summary:.before", 2: "summary:.after"}}],
        summary={"before": 4.87, "after": 3.21},
    )
    records = _records(path)
    assert [(r.status, r.name, r.claimed) for r in records] == [
        ("PASS", "latency#g1", "4.87"),
        ("PASS", "latency#g2", "3.21"),
    ]


def test_template_group_mismatch_fails_only_that_group(project):
    path = _ledger(
        project,
        "Latency drops from 4.87 to 3.21 ms.\n",
        [{"name": "latency", "file": "paper.tex",
          "anchor": {"template": "from {num} to {num} ms"}, "expect": 1,
          "groups": {1: "summary:.before", 2: "summary:.after"}}],
        summary={"before": 4.87, "after": 9.99},
    )
    ok, bad = _records(path)
    assert (ok.status, ok.name) == ("PASS", "latency#g1")
    assert (bad.status, bad.name, bad.claimed) == ("FAIL", "latency#g2", "3.21")
    assert "display-precision tolerance" in bad.note


def test_template_match_span_covers_anchor_and_group(tmp_path):
    doc = _doc(tmp_path, "Throughput improves by 12.7\\% overall.\n")
    anchor = Anchor(kind="template", template=r"improves by {num}\%")
    (match,) = find_anchor_matches(anchor, doc, [], "t")
    assert doc.raw[slice(*match.span)] == "improves by 12.7\\%"
    (hit,) = match.numbers
    assert hit.group == 1
    assert hit.text == "12.7"
    assert doc.raw[slice(*hit.span)] == "12.7"


# --- pattern ----------------------------------------------------------------

_LATENCY_RE = r"\$([\d.]+) \\pm ([\d.]+)\$"
_LATENCY_TEX = "Mean latency is $4.87 \\pm 0.51$\\,ms.\n"


def test_pattern_inline_regex_maps_groups_to_values(project):
    path = _ledger(
        project, _LATENCY_TEX,
        [{"name": "latency", "file": "paper.tex",
          "anchor": {"pattern": _LATENCY_RE}, "expect": 1,
          "groups": {1: "summary:.mean", 2: "summary:.std"}}],
        summary={"mean": 4.87, "std": 0.51},
    )
    records = _records(path)
    assert [(r.status, r.name, r.claimed) for r in records] == [
        ("PASS", "latency#g1", "4.87"),
        ("PASS", "latency#g2", "0.51"),
    ]


def test_pattern_named_reference_resolves_to_the_patterns_table(project):
    path = _ledger(
        project, _LATENCY_TEX,
        [{"name": "latency", "file": "paper.tex",
          "anchor": {"pattern": "latency_row"}, "expect": 1,
          "groups": {1: "summary:.mean", 2: "summary:.std"}}],
        summary={"mean": 4.87, "std": 0.51},
        patterns={"latency_row": _LATENCY_RE},
    )
    ledger = load_ledger(path)
    assert ledger.claims[0].anchor.pattern == _LATENCY_RE
    assert ledger.used_patterns == {"latency_row"}
    state = run_check(ledger)
    assert [r.status for r in state.report.records] == ["PASS", "PASS"]
    assert state.report.warnings == []


def test_pattern_with_value_reads_only_group_one(project):
    path = _ledger(
        project, _LATENCY_TEX,
        [{"name": "latency", "file": "paper.tex",
          "anchor": {"pattern": _LATENCY_RE}, "expect": 1,
          "value": "summary:.mean"}],
        summary={"mean": 4.87},
    )
    (record,) = _records(path)
    assert (record.status, record.name, record.claimed) == ("PASS", "latency", "4.87")


def test_loose_capture_group_is_rejected_with_a_tighten_hint(project):
    path = _ledger(
        project, _LATENCY_TEX,
        [{"name": "loose-group", "file": "paper.tex",
          "anchor": {"pattern": r"latency is (\$[\d.]+ \\pm)"}, "expect": 1,
          "value": "summary:.mean"}],
        summary={"mean": 4.87},
    )
    with pytest.raises(LedgerError) as excinfo:
        _records(path)
    message = str(excinfo.value)
    assert message.startswith("claim 'loose-group': ")
    assert "capture group 1 matched '$4.87 \\\\pm'" in message
    assert "is not a number token" in message
    assert "tighten the group so it captures only the number" in message


def test_loose_capture_group_exits_two_as_a_config_error(project, capsys):
    path = _ledger(
        project, _LATENCY_TEX,
        [{"name": "loose-group", "file": "paper.tex",
          "anchor": {"pattern": r"latency is (\$[\d.]+ \\pm)"}, "expect": 1,
          "value": "summary:.mean"}],
        summary={"mean": 4.87},
    )
    assert main(["check", "--ledger", str(path)]) == 2
    err = capsys.readouterr().err
    assert "CONFIG ERROR: claim 'loose-group':" in err
    assert "tighten the group" in err


def test_requested_group_beyond_capture_count_fails(project):
    path = _ledger(
        project,
        "Throughput improves by 12.7 percent.\n",
        [{"name": "too-many-groups", "file": "paper.tex",
          "anchor": {"pattern": r"improves by ([\d.]+)"}, "expect": 1,
          "groups": {1: "summary:.pct", 2: "summary:.pct"}}],
        summary={"pct": 12.7},
    )
    with pytest.raises(LedgerError) as excinfo:
        _records(path)
    assert str(excinfo.value) == (
        "claim 'too-many-groups': anchor has 1 capture group(s), group 2 requested"
    )


def test_requested_group_beyond_capture_count_fails_even_without_a_match(tmp_path):
    doc = _doc(tmp_path, "no anchor text here\n")
    anchor = Anchor(kind="pattern", pattern=r"improves by ([\d.]+)")
    with pytest.raises(LedgerError, match="group 7 requested"):
        find_anchor_matches(anchor, doc, [1, 7], "claim 'x'")


def test_optional_group_that_did_not_participate_fails(tmp_path):
    doc = _doc(tmp_path, "value 7 alone\n")
    anchor = Anchor(kind="pattern", pattern=r"value (\d+)(?: pm (\d+))?")
    with pytest.raises(LedgerError) as excinfo:
        find_anchor_matches(anchor, doc, [1, 2], "claim 'x'")
    assert "capture group 2 did not participate in a match" in str(excinfo.value)


# --- near -------------------------------------------------------------------

_NEAR_TEX = "Hit rate of 94.2\\% across 5 seeds in total.\n"
_NEAR_CONTEXT = "Hit rate of 94.2\\% across 5 seeds"


def test_near_occurrence_selects_the_nth_number_in_the_context(project):
    path = _ledger(
        project, _NEAR_TEX,
        [{"name": "seeds", "file": "paper.tex",
          "anchor": {"near": {"context": _NEAR_CONTEXT, "occurrence": 2}},
          "expect": 1, "value": "summary:.n_seeds"}],
        summary={"n_seeds": 5},
    )
    (record,) = _records(path)
    assert (record.status, record.claimed, record.line) == ("PASS", "5", 1)


def test_near_occurrence_one_takes_the_percent_token(project):
    path = _ledger(
        project, _NEAR_TEX,
        [{"name": "hit-rate", "file": "paper.tex",
          "anchor": {"near": {"context": _NEAR_CONTEXT, "occurrence": 1}},
          "expect": 1, "value": "summary:.hit_rate"}],
        summary={"hit_rate": 94.2},
    )
    (record,) = _records(path)
    assert (record.status, record.claimed) == ("PASS", "94.2\\%")


def test_near_context_is_whitespace_flexible(project):
    path = _ledger(
        project, "Hit rate of 94.2\\% across\n5 seeds in total.\n",
        [{"name": "seeds", "file": "paper.tex",
          "anchor": {"near": {"context": _NEAR_CONTEXT, "occurrence": 2}},
          "expect": 1, "value": "summary:.n_seeds"}],
        summary={"n_seeds": 5},
    )
    (record,) = _records(path)
    assert (record.status, record.claimed, record.line) == ("PASS", "5", 2)


def test_near_occurrence_beyond_token_count_fails(project):
    path = _ledger(
        project, _NEAR_TEX,
        [{"name": "seeds", "file": "paper.tex",
          "anchor": {"near": {"context": _NEAR_CONTEXT, "occurrence": 3}},
          "expect": 1, "value": "summary:.n_seeds"}],
        summary={"n_seeds": 5},
    )
    with pytest.raises(LedgerError) as excinfo:
        _records(path)
    assert str(excinfo.value) == (
        "claim 'seeds': context matched at line 1 but its paragraph "
        "holds 2 number token(s), occurrence 3 requested"
    )


def test_near_match_span_reaches_the_selected_token(tmp_path):
    """The span must cover the anchored number, or an exemption using a
    `near` anchor would not mark that number as covered."""
    doc = _doc(tmp_path, _NEAR_TEX)
    anchor = Anchor(kind="near", context=_NEAR_CONTEXT, occurrence=2)
    (match,) = find_anchor_matches(anchor, doc, [], "t")
    # The span is the token alone: an exemption anchored with `near` must not
    # silently cover the other numbers between the context and its target.
    assert doc.raw[slice(*match.span)] == "5"
    (hit,) = match.numbers
    assert (hit.group, hit.text) == (1, "5")
    assert doc.raw[slice(*hit.span)] == "5"


def test_near_always_reports_group_one(tmp_path):
    doc = _doc(tmp_path, _NEAR_TEX)
    anchor = Anchor(kind="near", context=_NEAR_CONTEXT, occurrence=2)
    (match,) = find_anchor_matches(anchor, doc, [2], "t")
    assert [hit.group for hit in match.numbers] == [1]


def test_near_with_a_non_default_group_key_is_a_config_error(project):
    path = _ledger(
        project, _NEAR_TEX,
        [{"name": "seeds", "file": "paper.tex",
          "anchor": {"near": {"context": _NEAR_CONTEXT, "occurrence": 2}},
          "expect": 1, "groups": {2: "summary:.n_seeds"}}],
        summary={"n_seeds": 5},
    )
    with pytest.raises(LedgerError):
        _records(path)


def test_near_context_without_a_number_anchors_the_following_number(project):
    path = _ledger(
        project,
        "Compared with the strongest baseline we gain 12.7\\% throughput.\n",
        [{"name": "gain", "file": "paper.tex",
          "anchor": {"near": {"context": "Compared with the strongest baseline",
                              "occurrence": 1}},
          "expect": 1, "value": "summary:.pct"}],
        summary={"pct": 12.7},
    )
    (record,) = _records(path)
    assert (record.status, record.claimed) == ("PASS", "12.7\\%")


# --- spans feed coverage accounting -----------------------------------------

def test_template_span_covers_its_token_and_leaves_siblings_unmapped(project):
    path = _ledger(
        project,
        "\\section{Evaluation}\nThroughput improves by 12.7\\% and memory grows by 3.4\\%.\n",
        [{"name": "throughput", "file": "paper.tex",
          "anchor": {"template": r"Throughput improves by {num}\%"},
          "expect": 1, "value": "summary:.pct"}],
        summary={"pct": 12.7},
        scan={"regions": [{"file": "paper.tex", "start": "\\section{Evaluation}"}]},
    )
    records = run_scan(load_ledger(path)).report.records
    assert [(r.status, r.claimed, r.line) for r in records] == [
        ("PASS", "12.7", 2),
        ("UNMAPPED", "3.4\\%", 2),
    ]


def test_near_span_covers_only_the_selected_token(project):
    path = _ledger(
        project,
        "\\section{Evaluation}\nHit rate of 94.2\\% across 5 seeds in total.\n",
        [{"name": "seeds", "file": "paper.tex",
          "anchor": {"near": {"context": _NEAR_CONTEXT, "occurrence": 2}},
          "expect": 1, "value": "summary:.n_seeds"}],
        summary={"n_seeds": 5},
        scan={"regions": [{"file": "paper.tex", "start": "\\section{Evaluation}"}]},
    )
    records = run_scan(load_ledger(path)).report.records
    assert [(r.status, r.claimed) for r in records] == [
        ("PASS", "5"),
        ("UNMAPPED", "94.2\\%"),
    ]


def test_two_claims_cannot_share_one_number_occurrence(project):
    claim = {"file": "paper.tex", "expect": 1, "value": "summary:.pct",
             "anchor": {"template": r"improves by {num}\%"}}
    path = _ledger(
        project, "Throughput improves by 12.7\\% overall.\n",
        [{"name": "first", **claim},
         {"name": "second", **claim,
          "anchor": {"pattern": r"improves by ([\d.]+)\\%"}}],
        summary={"pct": 12.7},
    )
    first, second = _records(path)
    assert (first.status, first.name) == ("PASS", "first")
    assert (second.status, second.name, second.claimed) == ("FAIL", "second", "12.7")
    assert second.note == "this number occurrence is already claimed by 'first'"


def test_repeated_anchor_spans_are_distinct_per_occurrence(project):
    path = _ledger(
        project,
        "Intro: across 5 seeds.\nEvaluation: across 5 seeds.\n",
        [{"name": "seeds", "file": "paper.tex",
          "anchor": {"template": "across {num} seeds"}, "expect": 2,
          "value": "summary:.n_seeds"}],
        summary={"n_seeds": 5},
    )
    records = _records(path)
    assert [(r.status, r.line) for r in records] == [("PASS", 1), ("PASS", 2)]


def test_multiplicity_mismatch_is_a_fail_not_an_exception(project, capsys):
    path = _ledger(
        project,
        "Intro: across 5 seeds.\nEvaluation: across 5 seeds.\n",
        [{"name": "seeds", "file": "paper.tex",
          "anchor": {"template": "across {num} seeds"}, "expect": 1,
          "value": "summary:.n_seeds"}],
        summary={"n_seeds": 5},
    )
    (record,) = _records(path)
    assert (record.status, record.line) == ("FAIL", 1)
    assert record.note == "anchor matched 2 time(s), expect 1"
    assert main(["check", "--ledger", str(path)]) == 1
    capsys.readouterr()
