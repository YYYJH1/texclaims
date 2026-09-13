"""Reconciliation semantics of the check pass: adversarial fixtures.

Every scenario builds a throwaway manuscript + artifact pair, runs the audit,
and asserts the exact record stream it must produce.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from texclaims.audit import run_check
from texclaims.ledger import load_ledger
from texclaims.report import FAIL, MISS, PASS

HEADLINE_ANCHOR = {"template": "throughput by {num}\\%"}
SUMMARY = {"throughput_pct": 12.73421}


def run(ledger_path):
    return run_check(load_ledger(ledger_path))


def statuses(state):
    return [r.status for r in state.report.records]


def json_digest(payload) -> str:
    """sha256 of the bytes the `project` fixture writes for a JSON artifact."""
    return hashlib.sha256(json.dumps(payload).encode("utf-8")).hexdigest()


def headline_ledger(**claim_overrides) -> dict:
    claim = {
        "name": "headline",
        "file": "paper.tex",
        "anchor": HEADLINE_ANCHOR,
        "expect": 1,
        "value": "summary:.throughput_pct",
    }
    claim.update(claim_overrides)
    return {"sources": {"summary": "results/summary.json"}, "claims": [claim]}


def test_fabricated_number_fails(project):
    path = project(
        documents={"paper.tex": "We improve throughput by 15.0\\% overall.\n"},
        artifacts={"results/summary.json": SUMMARY},
        ledger=headline_ledger(),
    )
    state = run(path)

    [record] = state.report.records
    assert record.status == FAIL
    assert record.name == "headline"
    assert record.file == "paper.tex"
    assert record.line == 1
    assert record.claimed == "15.0"
    assert record.expected == pytest.approx(12.73421)
    assert "exceeds" in record.note and "display-precision" in record.note
    assert state.report.exit_code() == 1


def test_correctly_rounded_number_passes(project):
    path = project(
        documents={"paper.tex": "We improve throughput by 12.7\\% overall.\n"},
        artifacts={"results/summary.json": SUMMARY},
        ledger=headline_ledger(),
    )
    state = run(path)

    [record] = state.report.records
    assert record.status == PASS
    assert record.claimed == "12.7"
    assert record.tolerance == pytest.approx(0.05, abs=1e-9)
    assert record.note == ""
    assert state.report.exit_code() == 0


def test_anchor_never_found_is_miss(project):
    path = project(
        documents={"paper.tex": "This paragraph makes no quantitative claim.\n"},
        artifacts={"results/summary.json": SUMMARY},
        ledger=headline_ledger(),
    )
    state = run(path)

    [record] = state.report.records
    assert record.status == MISS
    assert record.name == "headline"
    assert record.file == "paper.tex"
    assert "anchor not found" in record.note
    assert "do not delete it" in record.note
    assert state.report.exit_code() == 1


def test_optional_claim_with_missing_anchor_is_silent(project):
    path = project(
        documents={"paper.tex": "This paragraph makes no quantitative claim.\n"},
        artifacts={"results/summary.json": SUMMARY},
        ledger=headline_ledger(optional=True),
    )
    state = run(path)

    assert state.report.records == []
    assert state.report.exit_code() == 0


def test_anchor_count_mismatch_fails_with_actual_count(project):
    path = project(
        documents={
            "paper.tex": (
                "Intro: we improve throughput by 12.7\\% overall.\n"
                "Eval: we improve throughput by 12.7\\% over the baseline.\n"
            )
        },
        artifacts={"results/summary.json": SUMMARY},
        ledger=headline_ledger(expect=1),
    )
    state = run(path)

    [record] = state.report.records
    assert record.status == FAIL
    assert record.name == "headline"
    assert "matched 2 time(s)" in record.note
    assert "expect 1" in record.note
    assert record.line == 1
    assert state.report.exit_code() == 1


def test_optional_claim_still_fails_on_count_mismatch(project):
    path = project(
        documents={
            "paper.tex": (
                "Intro: we improve throughput by 12.7\\% overall.\n"
                "Eval: we improve throughput by 12.7\\% over the baseline.\n"
            )
        },
        artifacts={"results/summary.json": SUMMARY},
        ledger=headline_ledger(expect=1, optional=True),
    )
    state = run(path)

    [record] = state.report.records
    assert record.status == FAIL
    assert "matched 2 time(s)" in record.note


def test_deleting_one_of_two_copies_fails_rather_than_passing(project):
    path = project(
        documents={"paper.tex": "Intro: we improve throughput by 12.7\\% overall.\n"},
        artifacts={"results/summary.json": SUMMARY},
        ledger=headline_ledger(expect=2),
    )
    state = run(path)

    [record] = state.report.records
    assert record.status == FAIL
    assert "matched 1 time(s)" in record.note
    assert "expect 2" in record.note
    assert state.report.exit_code() == 1


def test_duplicated_claim_both_copies_agree(project):
    path = project(
        documents={
            "paper.tex": (
                "Intro: we improve throughput by 12.7\\% overall.\n"
                "Eval: we improve throughput by 12.7\\% over the baseline.\n"
            )
        },
        artifacts={"results/summary.json": SUMMARY},
        ledger=headline_ledger(expect=2),
    )
    state = run(path)

    assert statuses(state) == [PASS, PASS]
    assert [r.line for r in state.report.records] == [1, 2]
    assert {r.claimed for r in state.report.records} == {"12.7"}
    assert state.report.exit_code() == 0


def test_duplicated_claim_detects_the_edited_copy(project):
    path = project(
        documents={
            "paper.tex": (
                "Intro: we improve throughput by 12.7\\% overall.\n"
                "Eval: we improve throughput by 13.7\\% over the baseline.\n"
            )
        },
        artifacts={"results/summary.json": SUMMARY},
        ledger=headline_ledger(expect=2),
    )
    state = run(path)

    good, bad = state.report.records
    assert (good.status, good.line, good.claimed) == (PASS, 1, "12.7")
    assert (bad.status, bad.line, bad.claimed) == (FAIL, 2, "13.7")
    assert "exceeds" in bad.note
    assert state.report.exit_code() == 1


def test_second_claim_on_the_same_span_fails_as_already_claimed(project):
    path = project(
        documents={"paper.tex": "We improve throughput by 12.7\\% overall.\n"},
        artifacts={"results/summary.json": SUMMARY},
        ledger={
            "sources": {"summary": "results/summary.json"},
            "claims": [
                {
                    "name": "headline",
                    "file": "paper.tex",
                    "anchor": HEADLINE_ANCHOR,
                    "expect": 1,
                    "value": "summary:.throughput_pct",
                },
                {
                    "name": "headline-again",
                    "file": "paper.tex",
                    "anchor": {"template": "by {num}\\%"},
                    "expect": 1,
                    "value": "summary:.throughput_pct",
                },
            ],
        },
    )
    state = run(path)

    first, second = state.report.records
    assert (first.status, first.name) == (PASS, "headline")
    assert (second.status, second.name) == (FAIL, "headline-again")
    assert second.claimed == "12.7"
    assert "already claimed" in second.note
    assert state.report.exit_code() == 1
    assert len(state.claimed_spans["paper.tex"]) == 1


def test_group_captures_produce_one_record_per_group(project):
    path = project(
        documents={"paper.tex": "Latency drops from $4.87$\\,ms to $3.21$\\,ms.\n"},
        artifacts={"results/summary.json": {"baseline_ms": 4.87, "fast_ms": 3.209}},
        ledger={
            "sources": {"summary": "results/summary.json"},
            "patterns": {"latency_sentence": r"from \$([\d.]+)\$.* to \$([\d.]+)\$"},
            "claims": [
                {
                    "name": "latency-row",
                    "file": "paper.tex",
                    "anchor": {"pattern": "latency_sentence"},
                    "expect": 1,
                    "groups": {1: "summary:.baseline_ms", 2: "summary:.fast_ms"},
                }
            ],
        },
    )
    state = run(path)

    assert statuses(state) == [PASS, PASS]
    g1, g2 = state.report.records
    assert g1.name == "latency-row#g1"
    assert g2.name == "latency-row#g2"
    assert (g1.claimed, g2.claimed) == ("4.87", "3.21")
    assert g1.expected == pytest.approx(4.87)
    assert g2.expected == pytest.approx(3.209)
    assert state.report.exit_code() == 0


def test_repeated_groups_bind_the_same_fields_rather_than_indexing_rows(project):
    rows = [("Alpha", 4.87, 3.21), ("Beta", 6.5, 5.1), ("Gamma", 8.4, 7.3)]
    paper = "\n".join(f"{name} & {old} & {new}" for name, old, new in rows)
    artifact = {name: {"old": old, "new": new} for name, old, new in rows}
    claim = {"name": "all-rows", "file": "paper.tex", "expect": 3,
             "anchor": {"template": "& {num} & {num}"},
             "groups": {1: "summary:.Alpha.old", 2: "summary:.Alpha.new"}}
    path = project(documents={"paper.tex": paper},
                   artifacts={"results/summary.json": artifact},
                   ledger={"sources": {"summary": "results/summary.json"}, "claims": [claim]})
    state = run(path)
    assert statuses(state) == [PASS, PASS, FAIL, FAIL, FAIL, FAIL]
    assert state.report.exit_code() == 1
    # Each row needs its own label and artifact fields. Repeating an anchor
    # never turns expect into an index into the source artifact.
    claims = [{"name": name, "file": "paper.tex", "expect": 1,
               "anchor": {"template": name + " & {num} & {num}"},
               "groups": {1: f"summary:.{name}.old", 2: f"summary:.{name}.new"}}
              for name, _, _ in rows]
    path = project(documents={"paper.tex": paper},
                   artifacts={"results/summary.json": artifact},
                   ledger={"sources": {"summary": "results/summary.json"}, "claims": claims})
    state = run(path)
    assert statuses(state) == [PASS] * 6
    assert state.report.exit_code() == 0


def test_group_records_are_independent(project):
    path = project(
        documents={"paper.tex": "Latency drops from $4.87$\\,ms to $9.99$\\,ms.\n"},
        artifacts={"results/summary.json": {"baseline_ms": 4.87, "fast_ms": 3.21}},
        ledger={
            "sources": {"summary": "results/summary.json"},
            "patterns": {"latency_sentence": r"from \$([\d.]+)\$.* to \$([\d.]+)\$"},
            "claims": [
                {
                    "name": "latency-row",
                    "file": "paper.tex",
                    "anchor": {"pattern": "latency_sentence"},
                    "expect": 1,
                    "groups": {1: "summary:.baseline_ms", 2: "summary:.fast_ms"},
                }
            ],
        },
    )
    state = run(path)

    g1, g2 = state.report.records
    assert (g1.name, g1.status) == ("latency-row#g1", PASS)
    assert (g2.name, g2.status) == ("latency-row#g2", FAIL)
    assert g2.claimed == "9.99"
    assert state.report.exit_code() == 1


def test_already_claimed_record_keeps_the_group_suffix(project):
    path = project(
        documents={"paper.tex": "Latency drops from $4.87$\\,ms to $3.21$\\,ms.\n"},
        artifacts={"results/summary.json": {"baseline_ms": 4.87, "fast_ms": 3.21}},
        ledger={
            "sources": {"summary": "results/summary.json"},
            "patterns": {"latency_sentence": r"from \$([\d.]+)\$.* to \$([\d.]+)\$"},
            "claims": [
                {
                    "name": "fast-only",
                    "file": "paper.tex",
                    "anchor": {"template": "to ${num}$"},
                    "expect": 1,
                    "value": "summary:.fast_ms",
                },
                {
                    "name": "latency-row",
                    "file": "paper.tex",
                    "anchor": {"pattern": "latency_sentence"},
                    "expect": 1,
                    "groups": {1: "summary:.baseline_ms", 2: "summary:.fast_ms"},
                },
            ],
        },
    )
    state = run(path)

    _, g1, collision = state.report.records
    assert g1.name == "latency-row#g1"
    assert collision.status == FAIL
    assert "already claimed" in collision.note
    assert collision.name == "latency-row#g2"


def test_transform_chain_applies_scale_negate_absolute_offset_in_order(project):
    # -2 * 3 = -6 -> negate 6 -> abs 6 -> +0.5 = 6.5.  Any other ordering of
    # the same four operations yields -5.5 or 5.5, so 6.5 pins the order.
    path = project(
        documents={"paper.tex": "The corrected estimate is 6.5 units.\n"},
        artifacts={"results/summary.json": {"raw": -2.0}},
        ledger={
            "sources": {"summary": "results/summary.json"},
            "claims": [
                {
                    "name": "transformed",
                    "file": "paper.tex",
                    "anchor": {"template": "estimate is {num} units"},
                    "expect": 1,
                    "value": "summary:.raw",
                    "transform": {
                        "scale": 3,
                        "negate": True,
                        "absolute": True,
                        "offset": 0.5,
                    },
                }
            ],
        },
    )
    state = run(path)

    [record] = state.report.records
    assert record.status == PASS
    assert record.claimed == "6.5"
    assert record.expected == pytest.approx(6.5)
    assert state.report.exit_code() == 0


def test_transform_result_is_compared_not_the_raw_value(project):
    path = project(
        documents={"paper.tex": "The corrected estimate is -2.0 units.\n"},
        artifacts={"results/summary.json": {"raw": -2.0}},
        ledger={
            "sources": {"summary": "results/summary.json"},
            "claims": [
                {
                    "name": "transformed",
                    "file": "paper.tex",
                    "anchor": {"template": "estimate is {num} units"},
                    "expect": 1,
                    "value": "summary:.raw",
                    "transform": {
                        "scale": 3,
                        "negate": True,
                        "absolute": True,
                        "offset": 0.5,
                    },
                }
            ],
        },
    )
    state = run(path)

    [record] = state.report.records
    assert record.status == FAIL
    assert record.expected == pytest.approx(6.5)
    assert state.report.exit_code() == 1


def test_correct_sha256_pin_passes(project):
    payload = dict(SUMMARY)
    ledger = headline_ledger()
    ledger["pinning"] = {"sha256": {"results/summary.json": json_digest(payload)}}
    path = project(
        documents={"paper.tex": "We improve throughput by 12.7\\% overall.\n"},
        artifacts={"results/summary.json": payload},
        ledger=ledger,
    )
    state = run(path)

    assert statuses(state) == [PASS]
    assert state.report.exit_code() == 0


def test_wrong_sha256_pin_fails_before_the_claim_is_believed(project):
    ledger = headline_ledger()
    ledger["pinning"] = {"sha256": {"results/summary.json": "0" * 64}}
    path = project(
        documents={"paper.tex": "We improve throughput by 12.7\\% overall.\n"},
        artifacts={"results/summary.json": SUMMARY},
        ledger=ledger,
    )
    state = run(path)

    pin, claim = state.report.records
    assert pin.status == FAIL
    assert pin.name == "sha256-pin"
    assert pin.file == "results/summary.json"
    assert "!= pinned" in pin.note
    assert claim.status == PASS
    assert state.report.exit_code() == 1


def test_unused_named_pattern_warns(project):
    path = project(
        documents={"paper.tex": "We improve throughput by 12.7\\% overall.\n"},
        artifacts={"results/summary.json": SUMMARY},
        ledger={
            "sources": {"summary": "results/summary.json"},
            "patterns": {
                "used_one": r"throughput by ([\d.]+)\\%",
                "never_used": r"latency of ([\d.]+)\\,ms",
            },
            "claims": [
                {
                    "name": "headline",
                    "file": "paper.tex",
                    "anchor": {"pattern": "used_one"},
                    "expect": 1,
                    "value": "summary:.throughput_pct",
                }
            ],
        },
    )
    state = run(path)

    assert statuses(state) == [PASS]
    assert state.report.warnings == [
        "pattern 'never_used' is defined but never used"
    ]
    assert state.report.exit_code() == 0


def test_claim_matches_only_inside_its_own_file(project):
    body = "We improve throughput by 12.7\\% overall.\n"
    path = project(
        documents={"paper.tex": body, "appendix.tex": body},
        artifacts={"results/summary.json": SUMMARY},
        ledger={
            "sources": {"summary": "results/summary.json"},
            "claims": [
                {
                    "name": "headline",
                    "file": "paper.tex",
                    "anchor": HEADLINE_ANCHOR,
                    "expect": 1,
                    "value": "summary:.throughput_pct",
                }
            ],
        },
    )
    state = run(path)

    [record] = state.report.records
    assert record.status == PASS
    assert record.file == "paper.tex"
    assert set(state.claimed_spans) == {"paper.tex"}
    assert state.report.exit_code() == 0


def test_identical_spans_in_different_files_do_not_collide(project):
    body = "We improve throughput by 12.7\\% overall.\n"
    path = project(
        documents={"paper.tex": body, "appendix.tex": body},
        artifacts={"results/summary.json": SUMMARY},
        ledger={
            "sources": {"summary": "results/summary.json"},
            "claims": [
                {
                    "name": "headline-paper",
                    "file": "paper.tex",
                    "anchor": HEADLINE_ANCHOR,
                    "expect": 1,
                    "value": "summary:.throughput_pct",
                },
                {
                    "name": "headline-appendix",
                    "file": "appendix.tex",
                    "anchor": HEADLINE_ANCHOR,
                    "expect": 1,
                    "value": "summary:.throughput_pct",
                },
            ],
        },
    )
    state = run(path)

    assert statuses(state) == [PASS, PASS]
    assert [r.file for r in state.report.records] == ["paper.tex", "appendix.tex"]
    assert state.claimed_spans["paper.tex"] == state.claimed_spans["appendix.tex"]
    assert state.report.exit_code() == 0


def test_a_wrong_number_in_another_file_does_not_taint_the_claim(project):
    path = project(
        documents={
            "paper.tex": "We improve throughput by 12.7\\% overall.\n",
            "appendix.tex": "We improve throughput by 99.9\\% overall.\n",
        },
        artifacts={"results/summary.json": SUMMARY},
        ledger={
            "sources": {"summary": "results/summary.json"},
            "claims": [
                {
                    "name": "headline",
                    "file": "paper.tex",
                    "anchor": HEADLINE_ANCHOR,
                    "expect": 1,
                    "value": "summary:.throughput_pct",
                }
            ],
        },
    )
    state = run(path)

    assert statuses(state) == [PASS]
    assert state.report.exit_code() == 0
