"""Ledger schema validation: every failure path must raise LedgerError."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from texclaims.errors import LedgerError
from texclaims.ledger import (
    SCHEMA_VERSION,
    Anchor,
    EmitMacro,
    ScanRegion,
    Transform,
    ValueRef,
    load_ledger,
)

PAPER = "Throughput improves by 12.7\\% across 5 seeds.\n"
SUMMARY = {"improvement": {"throughput_pct": 12.734}, "n_seeds": 5}
DROP = object()


def claim(**over):
    """A minimal valid claim; pass ``key=DROP`` to remove a field."""
    node = {
        "name": "improvement",
        "file": "paper.tex",
        "anchor": {"template": "improves by {num}\\%"},
        "expect": 1,
        "value": "summary:.improvement.throughput_pct",
    }
    node.update(over)
    return {k: v for k, v in node.items() if v is not DROP}


def build(project, *, files=None, artifacts=None, claims=None, **top):
    """Write a valid-by-default ledger tree; ``top`` overrides ledger keys."""
    ledger = {
        "sources": {"summary": "results/summary.json"},
        "claims": [claim()] if claims is None else claims,
    }
    ledger.update({k: v for k, v in top.items() if v is not DROP})
    return project(
        documents={"paper.tex": PAPER} if files is None else files,
        artifacts={"results/summary.json": SUMMARY} if artifacts is None else artifacts,
        ledger=ledger,
    )


def raw_ledger(tmp_path, mapping):
    """Write a ledger verbatim, bypassing the fixture's required-key defaults."""
    path = tmp_path / "claims.yaml"
    path.write_text(yaml.safe_dump(mapping, sort_keys=False), encoding="utf-8")
    return path


def load_error(path) -> LedgerError:
    with pytest.raises(LedgerError) as excinfo:
        load_ledger(path)
    return excinfo.value


# --- closed schema ----------------------------------------------------------

def test_unknown_top_level_key_fails(project):
    err = load_error(build(project, claim={"name": "typo-of-claims"}))
    assert "unknown field(s) ['claim']" in str(err)
    assert err.path == "ledger"


def test_unknown_claim_field_fails(project):
    err = load_error(build(project, claims=[claim(tolerance=0.1)]))
    assert "unknown field(s) ['tolerance']" in str(err)
    assert err.path == "ledger.claims[0]"


def test_misspelled_transform_scale_fails(project):
    """The footgun the closed schema exists for: 'scal' must not pass silently."""
    err = load_error(build(project, claims=[claim(transform={"scal": 100})]))
    assert "unknown field(s) ['scal']" in str(err)
    assert "'scale'" in str(err)
    assert err.path == "ledger.claims[0](improvement).transform"


def test_unknown_anchor_field_fails(project):
    anchor = {"template": "improves by {num}\\%", "occurrence": 2}
    err = load_error(build(project, claims=[claim(anchor=anchor)]))
    assert "unknown field(s) ['occurrence']" in str(err)
    assert err.path == "ledger.claims[0](improvement).anchor"


def test_unknown_near_field_fails(project):
    anchor = {"near": {"context": "improves by", "occurence": 2}}
    err = load_error(build(project, claims=[claim(anchor=anchor)]))
    assert "unknown field(s) ['occurence']" in str(err)
    assert err.path == "ledger.claims[0](improvement).anchor.near"


def test_unknown_defaults_field_fails(project):
    err = load_error(build(project, defaults={"name": "not-defaultable"}))
    assert "unknown field(s) ['name']" in str(err)
    assert err.path == "ledger.defaults"


def test_unknown_exemption_field_fails(project):
    exemption = {
        "name": "waiver", "file": "paper.tex", "expect": 1,
        "anchor": {"template": "improves by {num}\\%"},
        "reason": "a written reason", "optional": True,
    }
    err = load_error(build(project, exemptions=[exemption]))
    assert "unknown field(s) ['optional']" in str(err)


# --- required fields --------------------------------------------------------

@pytest.mark.parametrize("missing", ["version", "documents", "sources", "claims"])
def test_missing_top_level_field_fails(tmp_path, missing):
    top = {
        "version": 1,
        "documents": ["paper.tex"],
        "sources": {"summary": "results/summary.json"},
        "claims": [claim()],
    }
    del top[missing]
    err = load_error(raw_ledger(tmp_path, top))
    assert f"missing required field(s) ['{missing}']" in str(err)
    assert err.path == "ledger"


@pytest.mark.parametrize("missing", ["name", "file", "anchor", "expect"])
def test_missing_claim_field_fails(project, missing):
    err = load_error(build(project, claims=[claim(**{missing: DROP})]))
    assert f"missing required field(s) ['{missing}']" in str(err)
    assert err.path == "ledger.claims[0]"


def test_empty_claim_list_loads(project):
    """It used to be rejected, which made the documented first step — an empty
    ledger that scan fills in — impossible to write."""
    path = build(project, claims=[])
    assert load_ledger(path).claims == []

def test_non_mapping_ledger_fails(tmp_path):
    path = tmp_path / "claims.yaml"
    path.write_text("- version: 1\n", encoding="utf-8")
    err = load_error(path)
    assert "expected a mapping, got list" in str(err)
    assert err.path == "ledger"


def test_unparsable_yaml_fails(tmp_path):
    path = tmp_path / "claims.yaml"
    path.write_text("version: 1\n  bad indent: [\n", encoding="utf-8")
    assert "ledger is not valid YAML" in str(load_error(path))


def test_unreadable_ledger_fails(tmp_path):
    err = load_error(tmp_path / "nope.yaml")
    assert "cannot read ledger" in str(err)
    assert err.path == ""


# --- version ----------------------------------------------------------------

def test_future_schema_version_asks_for_an_upgrade(project):
    err = load_error(build(project, version=SCHEMA_VERSION + 1))
    assert f"version {SCHEMA_VERSION + 1} is newer" in str(err)
    assert f"supports up to {SCHEMA_VERSION}" in str(err)
    assert "upgrade" in str(err)


@pytest.mark.parametrize("version", [0, -1])
def test_version_below_one_fails(project, version):
    assert "field 'version' must be >= 1" in str(load_error(build(project, version=version)))


@pytest.mark.parametrize("version", ["1", 1.0, True, None, [1]])
def test_non_integer_version_fails(project, version):
    err = load_error(build(project, version=version))
    assert "field 'version' must be an integer" in str(err)
    assert err.path == "ledger"


# --- documents and sources --------------------------------------------------

def test_missing_document_file_fails(project):
    err = load_error(build(project, documents=["paper.tex", "ghost.tex"]))
    assert "document not found: ghost.tex" in str(err)
    assert err.path == "ledger.documents"


@pytest.mark.parametrize("documents", [[], "paper.tex", ["paper.tex", ""], [1]])
def test_bad_documents_list_fails(project, documents):
    err = load_error(build(project, documents=documents))
    assert "'documents' must be a non-empty list of file paths" in str(err)


def test_empty_sources_mapping_fails(project):
    err = load_error(build(project, sources={}))
    assert "'sources' must be a non-empty mapping" in str(err)


def test_non_mapping_sources_fails(project):
    err = load_error(build(project, sources=["results/summary.json"]))
    assert "expected a mapping, got list" in str(err)
    assert err.path == "ledger.sources"


def test_missing_artifact_file_fails(project):
    err = load_error(build(project, sources={"summary": "results/ghost.json"}))
    assert "artifact not found: results/ghost.json" in str(err)
    assert err.path == "ledger.sources.summary"


@pytest.mark.parametrize("name", ["2runs", "run summary", "", "runs.json"])
def test_non_identifier_source_name_fails(project, name):
    err = load_error(build(project, sources={name: "results/summary.json"}))
    assert f"source name {name!r} must be an identifier" in str(err)
    assert err.path == "ledger.sources"


def test_non_string_source_path_fails(project):
    err = load_error(build(project, sources={"summary": 42}))
    assert "source path must be a non-empty string" in str(err)


# --- claims -----------------------------------------------------------------

def test_claim_with_both_value_and_groups_fails(project):
    entry = claim(groups={1: "summary:.n_seeds"})
    err = load_error(build(project, claims=[entry]))
    assert "claim needs exactly one of: value, groups" in str(err)
    assert err.path == "ledger.claims[0](improvement)"


def test_claim_with_neither_value_nor_groups_fails(project):
    err = load_error(build(project, claims=[claim(value=DROP)]))
    assert "claim needs exactly one of: value, groups" in str(err)


def test_claim_file_outside_documents_fails(project):
    err = load_error(build(project, claims=[claim(file="appendix.tex")]))
    assert "file 'appendix.tex' is not in 'documents'" in str(err)
    assert err.path == "ledger.claims[0](improvement)"


def test_duplicate_claim_name_fails(project):
    err = load_error(build(project, claims=[claim(), claim(expect=2)]))
    assert "duplicate name 'improvement'" in str(err)
    assert err.path == "ledger.claims[1](improvement)"


def test_claim_and_exemption_share_one_namespace(project):
    exemption = {
        "name": "improvement", "file": "paper.tex", "expect": 1,
        "anchor": {"template": "across {num} seeds"},
        "reason": "a sufficiently long reason",
    }
    err = load_error(build(project, exemptions=[exemption]))
    assert "duplicate name 'improvement'" in str(err)
    assert err.path == "ledger.exemptions[0](improvement)"


@pytest.mark.parametrize("expect", [0, -1, 1.5, "1", True, None])
def test_non_positive_integer_expect_fails(project, expect):
    err = load_error(build(project, claims=[claim(expect=expect)]))
    assert "field 'expect' must be an integer >= 1" in str(err)


@pytest.mark.parametrize("name", ["", "   ", 7])
def test_non_string_claim_name_fails(project, name):
    err = load_error(build(project, claims=[claim(name=name)]))
    assert "field 'name' must be a non-empty string" in str(err)


def test_empty_groups_mapping_fails(project):
    err = load_error(build(project, claims=[claim(value=DROP, groups={})]))
    assert "'groups' must be a non-empty mapping" in str(err)


@pytest.mark.parametrize("key", [0, -1, "1"])
def test_non_positive_group_key_fails(project, key):
    entry = claim(value=DROP, groups={key: "summary:.n_seeds"})
    err = load_error(build(project, claims=[entry]))
    assert f"group key {key!r} must be an integer >= 1" in str(err)
    assert err.path == "ledger.claims[0](improvement).groups"


def test_non_boolean_optional_fails(project):
    err = load_error(build(project, claims=[claim(optional="yes")]))
    assert "field 'optional' must be a boolean" in str(err)


@pytest.mark.parametrize("field", ["abs_tol", "rel_tol"])
def test_non_numeric_tolerance_fails(project, field):
    err = load_error(build(project, claims=[claim(**{field: "0.01"})]))
    assert f"field {field!r} must be a number" in str(err)


def test_boolean_scale_fails(project):
    err = load_error(build(project, claims=[claim(transform={"scale": True})]))
    assert "field 'scale' must be a number" in str(err)


def test_non_boolean_negate_fails(project):
    err = load_error(build(project, claims=[claim(transform={"negate": 1})]))
    assert "field 'negate' must be a boolean" in str(err)


# --- value references -------------------------------------------------------

def test_unknown_source_reference_fails(project):
    err = load_error(build(project, claims=[claim(value="runs:.hit_rate")]))
    assert "unknown source 'runs' (registered: summary)" in str(err)
    assert err.path == "ledger.claims[0](improvement).value"


@pytest.mark.parametrize("ref", ["summary.n_seeds", 5, None])
def test_value_without_source_prefix_fails(project, ref):
    err = load_error(build(project, claims=[claim(value=ref)]))
    assert "value reference must be a 'source:selector' string" in str(err)


def test_bad_selector_syntax_fails_at_load_time(project):
    err = load_error(build(project, claims=[claim(value="summary:n_seeds")]))
    assert "neither a path nor a known function" in str(err)


def test_group_reference_path_is_reported(project):
    entry = claim(value=DROP, groups={1: "summary:.n_seeds", 2: "ghost:.n_seeds"})
    err = load_error(build(project, claims=[entry]))
    assert err.path == "ledger.claims[0](improvement).groups[2]"


def test_value_reference_is_whitespace_tolerant(project):
    entry = claim(value=" summary : .n_seeds ")
    ledger = load_ledger(build(project, claims=[entry]))
    ref = ledger.claims[0].value
    assert ref == ValueRef(source="summary", selector=".n_seeds", raw=" summary : .n_seeds ")


# --- anchors ----------------------------------------------------------------

@pytest.mark.parametrize("anchor", [
    {},
    {"template": "improves by {num}\\%", "pattern": "row"},
    {"near": {"context": "improves"}, "template": "improves by {num}\\%"},
])
def test_anchor_needs_exactly_one_kind(project, anchor):
    err = load_error(build(project, claims=[claim(anchor=anchor)]))
    assert "anchor needs exactly one of: template, pattern, near" in str(err)
    assert err.path == "ledger.claims[0](improvement).anchor"


def test_template_without_num_placeholder_fails(project):
    err = load_error(build(project, claims=[claim(anchor={"template": "improves by"})]))
    assert "template must contain at least one {num} placeholder" in str(err)


def test_unknown_named_pattern_fails(project):
    ledger = build(
        project,
        claims=[claim(anchor={"pattern": "latency_row"})],
        patterns={"headline_row": "improves by ([\\d.]+)"},
    )
    err = load_error(ledger)
    assert "unknown named pattern 'latency_row' (defined: headline_row)" in str(err)


def test_named_pattern_reference_without_pattern_table_fails(project):
    err = load_error(build(project, claims=[claim(anchor={"pattern": "latency_row"})]))
    assert "unknown named pattern 'latency_row' (defined: none defined)" in str(err)


def test_pattern_without_capture_group_fails(project):
    err = load_error(build(project, patterns={"plain": "improves by [\\d.]+"}))
    assert "pattern must contain at least one capture group" in str(err)
    assert err.path == "ledger.patterns.plain"


def test_uncompilable_pattern_fails(project):
    err = load_error(build(project, patterns={"broken": "improves by ([\\d.]+"}))
    assert "invalid regex" in str(err)
    assert err.path == "ledger.patterns.broken"


def test_non_identifier_pattern_name_fails(project):
    err = load_error(build(project, patterns={"latency row": "([\\d.]+)"}))
    assert "pattern name 'latency row' must be an identifier" in str(err)
    assert err.path == "ledger.patterns"


@pytest.mark.parametrize("occurrence", [0, -1, 2.0, "2", True])
def test_near_occurrence_below_one_fails(project, occurrence):
    anchor = {"near": {"context": "improves by", "occurrence": occurrence}}
    err = load_error(build(project, claims=[claim(anchor=anchor)]))
    assert "field 'occurrence' must be an integer >= 1" in str(err)
    assert err.path == "ledger.claims[0](improvement).anchor.near"


def test_near_without_context_fails(project):
    err = load_error(build(project, claims=[claim(anchor={"near": {"occurrence": 2}})]))
    assert "missing required field(s) ['context']" in str(err)
    assert err.path == "ledger.claims[0](improvement).anchor.near"


def test_inline_pattern_is_kept_verbatim(project):
    inline = "improves by ([\\d.]+)\\\\%"
    ledger = load_ledger(build(project, claims=[claim(anchor={"pattern": inline})]))
    assert ledger.claims[0].anchor == Anchor(kind="pattern", pattern=inline)
    assert ledger.used_patterns == set()


def test_named_pattern_is_inlined_and_recorded_as_used(project):
    regex = "improves by ([\\d.]+)"
    ledger = load_ledger(build(
        project,
        claims=[claim(anchor={"pattern": "headline_row"})],
        patterns={"headline_row": regex, "unused_row": "([\\d.]+) seeds"},
    ))
    assert ledger.claims[0].anchor == Anchor(kind="pattern", pattern=regex)
    assert ledger.used_patterns == {"headline_row"}
    assert set(ledger.patterns) == {"headline_row", "unused_row"}


# --- exemptions -------------------------------------------------------------

def _exemption(**over):
    node = {
        "name": "confidence-level", "file": "paper.tex", "expect": 1,
        "anchor": {"template": "across {num} seeds"},
        "reason": "Protocol constant chosen a priori.",
    }
    node.update(over)
    return {k: v for k, v in node.items() if v is not DROP}


@pytest.mark.parametrize("reason", ["short", "  brief ", "1234567"])
def test_short_exemption_reason_fails(project, reason):
    err = load_error(build(project, exemptions=[_exemption(reason=reason)]))
    assert "'reason' must explain the exemption (>= 8 characters)" in str(err)
    assert err.path == "ledger.exemptions[0](confidence-level)"


@pytest.mark.parametrize("missing", ["name", "file", "anchor", "expect", "reason"])
def test_missing_exemption_field_fails(project, missing):
    err = load_error(build(project, exemptions=[_exemption(**{missing: DROP})]))
    assert f"missing required field(s) ['{missing}']" in str(err)


def test_defaults_do_not_apply_to_exemptions(project):
    ledger = build(
        project,
        claims=[claim(file=DROP)],
        exemptions=[_exemption(file=DROP)],
        defaults={"file": "paper.tex"},
    )
    err = load_error(ledger)
    assert "missing required field(s) ['file']" in str(err)
    assert err.path == "ledger.exemptions[0]"


def test_exemption_reason_is_stripped(project):
    exemption = _exemption(reason="  Protocol constant, not a result.  ")
    ledger = load_ledger(build(project, exemptions=[exemption]))
    assert ledger.exemptions[0].reason == "Protocol constant, not a result."
    assert ledger.exemptions[0].expect == 1


def test_non_list_exemptions_fails(project):
    err = load_error(build(project, exemptions=_exemption()))
    assert "expected a list, got dict" in str(err)
    assert err.path == "ledger.exemptions"


# --- scan regions -----------------------------------------------------------

def test_scan_region_file_outside_documents_fails(project):
    err = load_error(build(project, scan={"regions": [{"file": "appendix.tex"}]}))
    assert "file 'appendix.tex' is not in 'documents'" in str(err)
    assert err.path == "ledger.scan.regions[0]"


def test_unknown_scan_region_field_fails(project):
    region = {"file": "paper.tex", "from": "\\section{Evaluation}"}
    err = load_error(build(project, scan={"regions": [region]}))
    assert "unknown field(s) ['from']" in str(err)


def test_scan_without_regions_fails(project):
    err = load_error(build(project, scan={}))
    assert "missing required field(s) ['regions']" in str(err)
    assert err.path == "ledger.scan"


def test_scan_region_bounds_default_to_whole_file(project):
    ledger = load_ledger(build(project, scan={"regions": [{"file": "paper.tex"}]}))
    assert ledger.scan_regions == [ScanRegion(file="paper.tex", start=None, end=None)]


# --- emit -------------------------------------------------------------------

@pytest.mark.parametrize("name", ["Headline_Improvement", "Headline1", "headline-rate", "a b"])
def test_non_alphabetic_macro_name_fails(project, name):
    emit = {"output": "numbers.tex",
            "macros": [{"name": name, "value": "summary:.n_seeds"}]}
    err = load_error(build(project, emit=emit))
    assert f"macro name {name!r} must be letters only" in str(err)
    assert err.path == "ledger.emit.macros[0]"


def test_empty_macro_name_fails(project):
    emit = {"output": "numbers.tex", "macros": [{"name": "", "value": "summary:.n_seeds"}]}
    assert "field 'name' must be a non-empty string" in str(load_error(build(project, emit=emit)))


def test_duplicate_macro_name_fails(project):
    emit = {"output": "numbers.tex", "macros": [
        {"name": "Seeds", "value": "summary:.n_seeds"},
        {"name": "Seeds", "value": "summary:.improvement.throughput_pct"},
    ]}
    err = load_error(build(project, emit=emit))
    assert "duplicate macro name 'Seeds'" in str(err)
    assert err.path == "ledger.emit.macros[1]"


def test_emit_without_output_fails(project):
    emit = {"macros": [{"name": "Seeds", "value": "summary:.n_seeds"}]}
    err = load_error(build(project, emit=emit))
    assert "missing required field(s) ['output']" in str(err)
    assert err.path == "ledger.emit"


def test_macro_without_value_fails(project):
    emit = {"output": "numbers.tex", "macros": [{"name": "Seeds", "format": ".1f"}]}
    err = load_error(build(project, emit=emit))
    assert "missing required field(s) ['value']" in str(err)


def test_non_string_macro_format_fails(project):
    emit = {"output": "numbers.tex",
            "macros": [{"name": "Seeds", "value": "summary:.n_seeds", "format": 2}]}
    err = load_error(build(project, emit=emit))
    assert "field 'format' must be a string" in str(err)


def test_macro_defaults_are_identity(project):
    emit = {"output": "numbers.tex",
            "macros": [{"name": "Seeds", "value": "summary:.n_seeds"}]}
    ledger = load_ledger(build(project, emit=emit))
    assert ledger.emit.output == "numbers.tex"
    assert ledger.emit.macros == (
        EmitMacro(name="Seeds",
                  value=ValueRef("summary", ".n_seeds", "summary:.n_seeds"),
                  format="", scale=1.0),
    )


# --- pinning ----------------------------------------------------------------

DIGEST = "9f" * 32


@pytest.mark.parametrize("digest", ["abc123", DIGEST.upper(), "9f" * 31, 42])
def test_bad_sha256_pin_fails(project, digest):
    pinning = {"sha256": {"results/summary.json": digest}}
    err = load_error(build(project, pinning=pinning))
    assert "pin must be a 64-char lowercase hex sha256" in str(err)
    assert err.path == "ledger.pinning.sha256.results/summary.json"


def test_pinned_file_must_exist(project):
    pinning = {"sha256": {"results/ghost.json": DIGEST}}
    err = load_error(build(project, pinning=pinning))
    assert "pinned artifact not found: results/ghost.json" in str(err)


def test_unknown_pinning_field_fails(project):
    err = load_error(build(project, pinning={"md5": {"results/summary.json": DIGEST}}))
    assert "unknown field(s) ['md5']" in str(err)
    assert err.path == "ledger.pinning"


def test_valid_pin_is_recorded(project):
    pinning = {"sha256": {"results/summary.json": DIGEST}}
    ledger = load_ledger(build(project, pinning=pinning))
    assert ledger.sha256_pins == {"results/summary.json": DIGEST}


def test_non_string_pin_key_fails(project):
    err = load_error(build(project, pinning={"sha256": {2024: DIGEST}}))
    assert "ledger.pinning.sha256" in err.path


# --- strictness holes -------------------------------------------------------

@pytest.mark.parametrize("key", ["patterns", "defaults"])
def test_falsy_non_mapping_block_fails(project, key):
    err = load_error(build(project, **{key: []}))
    assert "expected a mapping, got list" in str(err)


# --- defaults merging -------------------------------------------------------

def test_defaults_supply_missing_claim_fields(project):
    ledger = load_ledger(build(
        project,
        claims=[claim(file=DROP, expect=DROP)],
        defaults={"file": "paper.tex", "expect": 3, "transform": {"scale": 100}},
    ))
    entry = ledger.claims[0]
    assert entry.file == "paper.tex"
    assert entry.expect == 3
    assert entry.transform == Transform(scale=100.0)


def test_claim_overrides_defaults(project):
    ledger = load_ledger(build(
        project,
        claims=[claim(file=DROP, expect=2, transform={"scale": 2})],
        defaults={"file": "paper.tex", "expect": 9, "transform": {"scale": 100}},
    ))
    entry = ledger.claims[0]
    assert (entry.expect, entry.transform) == (2, Transform(scale=2.0))


def test_defaults_are_validated_against_each_claim(project):
    err = load_error(build(project, defaults={"file": "ghost.tex"},
                           claims=[claim(file=DROP)]))
    assert "file 'ghost.tex' is not in 'documents'" in str(err)


def test_claim_without_transform_is_identity(project):
    ledger = load_ledger(build(project))
    entry = ledger.claims[0]
    assert entry.transform == Transform(scale=1.0, negate=False, absolute=False, offset=0.0)
    assert (entry.abs_tol, entry.rel_tol, entry.optional) == (None, None, False)
    assert entry.groups == {}
    assert entry.anchor == Anchor(kind="template", template="improves by {num}\\%")


def test_transform_applies_scale_negate_absolute_offset_in_order(project):
    assert Transform(scale=2.0, negate=True, absolute=True, offset=1.0).apply(3.0) == 7.0
    assert Transform(scale=2.0, negate=True, offset=1.0).apply(3.0) == -5.0
    assert Transform().apply(-4.5) == -4.5


# --- golden demo ledger -----------------------------------------------------

def test_demo_ledger_loads_with_expected_fields(demo_ledger):
    ledger = load_ledger(demo_ledger)

    assert ledger.root == Path(demo_ledger).resolve().parent
    assert ledger.documents == ["paper.tex"]
    assert set(ledger.sources) == {"summary", "runs"}
    assert ledger.sources["runs"] == ledger.root / "results" / "runs.csv"
    assert all(path.is_file() for path in ledger.sources.values())
    assert ledger.sha256_pins == {}

    assert [c.name for c in ledger.claims] == [
        "headline-improvement", "latency-row", "hit-rate", "seed-count"]
    assert all(c.file == "paper.tex" for c in ledger.claims)  # from defaults

    headline = ledger.claims[0]
    assert headline.anchor == Anchor(kind="template", template="throughput by {num}\\%")
    assert headline.expect == 2
    assert headline.value == ValueRef(
        "summary", ".improvement.throughput_pct", "summary:.improvement.throughput_pct")

    latency = ledger.claims[1]
    assert latency.anchor.kind == "pattern"
    assert latency.anchor.pattern == ledger.patterns["latency_sentence"]
    assert ledger.used_patterns == {"latency_sentence"}
    assert sorted(latency.groups) == [1, 2, 3, 4]
    assert latency.groups[3].selector == ".fastcache.mean_ms"
    assert latency.value is None

    hit_rate = ledger.claims[2]
    assert hit_rate.transform == Transform(scale=100.0)
    assert hit_rate.value == ValueRef(
        "runs", "[] | .hit_rate | mean", "runs:[] | .hit_rate | mean")

    assert len(ledger.exemptions) == 1
    waiver = ledger.exemptions[0]
    assert waiver.name == "confidence-level"
    assert waiver.anchor == Anchor(kind="template", template="the {num}\\% confidence level")
    assert len(waiver.reason) >= 8

    assert ledger.scan_regions == [
        ScanRegion(file="paper.tex", start="\\section{Evaluation}", end=None)]

    assert ledger.emit.output == "numbers.tex"
    assert [m.name for m in ledger.emit.macros] == ["HeadlineImprovement", "MeanHitRate"]
    assert ledger.emit.macros[1] == EmitMacro(
        name="MeanHitRate",
        value=ValueRef("runs", "[] | .hit_rate | mean", "runs:[] | .hit_rate | mean"),
        format=".1f", scale=100.0)
