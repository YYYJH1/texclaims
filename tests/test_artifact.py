"""Artifact loading and the jq-subset selector (texclaims.artifact)."""

from __future__ import annotations

import re

import pytest

from texclaims.artifact import load_artifact, select, validate_selector
from texclaims.cli import main
from texclaims.errors import LedgerError

SUMMARY = {
    "improvement": {"throughput_pct": 12.73421},
    "n_seeds": 5,
    "drift": -0.75,
    "converged": True,
    "label": "fastcache",
    "empty": [],
    "xs": [1.0, 2.0, 6.0, 3.0],
    "runs": [
        {"x": 1.0, "delta": -1.0, "tag": "a"},
        {"x": 2.0, "delta": 3.0, "tag": "b"},
        {"x": 6.0, "delta": -5.0, "tag": "c"},
        {"x": 3.0, "delta": 2.0, "tag": "d"},
    ],
    "by_name": {"p": {"x": 4.0}, "q": {"x": 6.0}},
    "grid": [[1.0, 2.0], [3.0, 4.0]],
    "quoted key": 7,
    "single": 8,
    "hit-rate": 0.9419,
    "nested": {"b c": {"d": 2.5}},
}

RUNS_CSV = "seed,latency_ms,label\n42,3.18,fast\n43,3.25,slow\n"


@pytest.fixture
def artifact(project):
    """Write one artifact into a throwaway project tree; return its path."""

    def build(name, payload):
        ledger = project(
            documents={"paper.tex": "Value 1.\n"},
            artifacts={name: payload},
            ledger={"sources": {"data": name}, "claims": []},
        )
        return ledger.parent / name

    return build


@pytest.fixture
def load(artifact):
    def build(name, payload):
        return load_artifact(artifact(name, payload), "sources.data")

    return build


@pytest.fixture
def summary(load):
    return load("results/summary.json", SUMMARY)


@pytest.fixture
def runs(load):
    return load("results/runs.csv", RUNS_CSV)


# --- JSON paths -------------------------------------------------------------


def test_dot_path_walks_nested_objects(summary):
    assert select(summary, ".improvement.throughput_pct") == 12.73421


def test_double_quoted_step_selects_a_key_with_a_space(summary):
    assert select(summary, '["quoted key"]') == 7.0


def test_single_quoted_step_selects_the_same_way(summary):
    assert select(summary, "['single']") == 8.0


def test_quoted_step_may_follow_a_dot_path(summary):
    assert select(summary, '.nested["b c"].d') == 2.5


def test_quoted_step_tolerates_inner_whitespace(summary):
    assert select(summary, "[  'single'  ]") == 8.0


def test_bracket_index_selects_a_list_element(summary):
    assert select(summary, ".xs[2]") == 6.0


def test_indexes_chain_into_nested_lists(summary):
    assert select(summary, ".grid[1][0]") == 3.0


def test_hyphenated_key_is_a_plain_identifier_step(summary):
    assert select(summary, ".hit-rate") == 0.9419


def test_integer_json_value_keeps_its_exactness(summary):
    """Converting to float here would merge neighbours above 2**53."""
    result = select(summary, ".n_seeds")
    assert result == 5
    assert isinstance(result, int)


# --- CSV loading ------------------------------------------------------------


def test_csv_header_row_becomes_dict_keys(runs):
    assert runs == [
        {"seed": 42, "latency_ms": 3.18, "label": "fast"},
        {"seed": 43, "latency_ms": 3.25, "label": "slow"},
    ]


def test_csv_integer_cell_is_coerced_to_int(runs):
    assert isinstance(runs[0]["seed"], int)


def test_csv_decimal_cell_is_coerced_to_float(runs):
    assert isinstance(runs[0]["latency_ms"], float)


def test_csv_string_column_stays_a_string(runs):
    assert runs[0]["label"] == "fast"
    assert isinstance(runs[0]["label"], str)


def test_csv_suffix_match_is_case_insensitive(load):
    assert load("results/RUNS.CSV", "a,b\n1,x\n") == [{"a": 1, "b": "x"}]


def test_csv_cells_beyond_the_header_are_rejected(load):
    with pytest.raises(LedgerError, match="CSV row 2 has 1 extra field"):
        load("results/wide.csv", "a,b\n1,2,3\n")


def test_csv_rows_feed_the_wildcard_pipeline(runs):
    assert select(runs, "[] | .latency_ms | mean") == pytest.approx(3.215)
    assert select(runs, "[0] | .seed") == 42.0
    assert select(runs, "[] | .label | len") == 2.0


def test_demo_csv_loads_five_seeds(demo_ledger):
    rows = load_artifact(demo_ledger.parent / "results" / "runs.csv", "sources.runs")
    assert [row["seed"] for row in rows] == [42, 43, 44, 45, 46]
    assert select(rows, "[] | .hit_rate | mean") == pytest.approx(0.94218)


def test_demo_json_selector_matches_the_ledger(demo_ledger):
    data = load_artifact(demo_ledger.parent / "results" / "summary.json", "sources.summary")
    assert select(data, ".improvement.throughput_pct") == 12.73421


def test_invalid_json_reports_the_source_path(artifact):
    path = artifact("results/summary.json", "{not json")
    with pytest.raises(LedgerError) as exc:
        load_artifact(path, "sources.data")
    assert exc.value.path == "sources.data"
    assert str(exc.value).startswith("sources.data: artifact is not valid JSON")


def test_unreadable_artifact_reports_the_source_path(artifact):
    path = artifact("results/summary.json", SUMMARY)
    with pytest.raises(LedgerError) as exc:
        load_artifact(path.parent / "gone.json", "sources.data")
    assert exc.value.path == "sources.data"
    assert "cannot read artifact" in str(exc.value)


# --- wildcard ---------------------------------------------------------------


def test_wildcard_expands_a_list(summary):
    assert select(summary, ".xs[] | sum") == 12.0


def test_wildcard_expands_dict_values(summary):
    assert select(summary, ".by_name[] | .x | sum") == 10.0


def test_path_step_after_wildcard_maps_over_the_stream(summary):
    assert select(summary, ".runs[] | .x | max") == 6.0


def test_index_step_after_wildcard_maps_over_the_stream(summary):
    assert select(summary, ".grid[] | [0] | sum") == 4.0


def test_repeated_wildcard_flattens_the_stream(summary):
    assert select(summary, ".grid[][] | sum") == 10.0


def test_wildcard_over_the_whole_csv_root(runs):
    assert select(runs, "[] | .seed | max") == 43.0


# --- pipeline aggregation ---------------------------------------------------


@pytest.mark.parametrize(
    "func,expected",
    [
        ("mean", 3.0),
        ("median", 2.5),
        ("max", 6.0),
        ("min", 1.0),
        ("sum", 12.0),
        ("len", 4.0),
        ("first", 1.0),
        ("last", 3.0),
    ],
)
def test_aggregate_over_a_plain_list(summary, func, expected):
    assert select(summary, f".xs | {func}") == expected


@pytest.mark.parametrize(
    "func,expected",
    [
        ("mean", 3.0),
        ("median", 2.5),
        ("max", 6.0),
        ("min", 1.0),
        ("sum", 12.0),
        ("len", 4.0),
        ("first", 1.0),
        ("last", 3.0),
    ],
)
def test_aggregate_over_a_wildcard_stream(summary, func, expected):
    assert select(summary, f".runs[] | .x | {func}") == expected


def test_abs_on_a_scalar(summary):
    assert select(summary, ".drift | abs") == 0.75


def test_abs_maps_over_a_stream_before_reducing(summary):
    assert select(summary, ".runs[] | .delta | abs | max") == 5.0


def test_abs_after_a_reduction_applies_to_the_scalar(summary):
    assert select(summary, ".runs[] | .delta | min | abs") == 5.0


def test_len_of_an_empty_list_is_zero(summary):
    assert select(summary, ".empty | len") == 0.0


def test_len_counts_stream_elements_not_characters(summary):
    assert select(summary, ".runs[] | .tag | len") == 4.0


# --- error paths ------------------------------------------------------------


def test_missing_key_reports_consumed_path_and_candidates(summary):
    with pytest.raises(LedgerError) as exc:
        select(summary, ".improvement.latency_pct")
    message = str(exc.value)
    assert "key 'latency_pct' not found after '.improvement'" in message
    assert "'throughput_pct'" in message


@pytest.mark.parametrize("index", [4, 9])
def test_index_out_of_range_reports_length_and_consumed_path(summary, index):
    with pytest.raises(LedgerError) as exc:
        select(summary, f".xs[{index}]")
    assert f"index [{index}] out of range (len 4) after '.xs'" in str(exc.value)


def test_descending_into_a_scalar_reports_the_consumed_path(summary):
    with pytest.raises(LedgerError) as exc:
        select(summary, ".improvement.throughput_pct.mean")
    message = str(exc.value)
    assert "cannot select key 'mean' on float" in message
    assert "after '.improvement.throughput_pct'" in message


def test_indexing_a_non_list_reports_the_consumed_path(summary):
    with pytest.raises(LedgerError, match=r"cannot index \[0\] on dict after '\.improvement'"):
        select(summary, ".improvement[0]")


def test_wildcard_on_a_scalar_is_rejected(summary):
    with pytest.raises(LedgerError, match=r"cannot expand \[\] on int after '\.n_seeds'"):
        select(summary, ".n_seeds[]")


@pytest.mark.parametrize("selector", ["", ".xs | ", ".xs | | mean", "| .xs | mean"])
def test_empty_pipeline_stage_is_rejected(summary, selector):
    with pytest.raises(LedgerError, match="empty pipeline stage in selector"):
        select(summary, selector)


def test_unknown_function_name_is_rejected(summary):
    with pytest.raises(LedgerError) as exc:
        select(summary, ".xs | avg")
    assert "stage 'avg'" in str(exc.value)
    assert "neither a path nor a known function" in str(exc.value)


def test_function_applied_to_a_mapping_is_rejected(summary):
    with pytest.raises(LedgerError, match="function 'mean' needs a list/stream, got dict"):
        select(summary, ".improvement | mean")


def test_function_over_non_numeric_values_is_rejected(summary):
    with pytest.raises(LedgerError, match="function 'mean' failed"):
        select(summary, ".runs[] | .tag | mean")


def test_aggregate_on_an_empty_stream_is_rejected(summary):
    with pytest.raises(LedgerError, match="function 'mean' applied to an empty stream"):
        select(summary, ".empty[] | mean")


def test_aggregate_on_an_empty_list_is_rejected(summary):
    with pytest.raises(LedgerError, match="function 'sum' applied to an empty stream"):
        select(summary, ".empty | sum")


@pytest.mark.parametrize(
    "selector,kind",
    [(".improvement", "dict"), (".xs", "list"), (".label", "str")],
)
def test_non_scalar_result_is_rejected(summary, selector, kind):
    with pytest.raises(LedgerError) as exc:
        select(summary, selector)
    assert f"selector {selector!r} produced {kind}, expected a scalar number" in str(exc.value)


def test_boolean_result_is_rejected(summary):
    with pytest.raises(LedgerError, match="produced bool, expected a scalar number"):
        select(summary, ".converged")


def test_unfinished_stream_result_is_rejected(summary):
    with pytest.raises(LedgerError, match="expected a scalar number"):
        select(summary, ".xs[]")


def test_bad_syntax_inside_a_stage_is_rejected(summary):
    with pytest.raises(LedgerError, match=re.escape("bad selector syntax at '..xs'")):
        select(summary, "..xs")


# --- validate_selector (syntax only) ----------------------------------------


@pytest.mark.parametrize(
    "selector",
    [
        ".a",
        ".a.b",
        ".a-b",
        ".a_b",
        '["any key"]',
        "['any key']",
        "[0]",
        "[]",
        ".a[0].b",
        "[] | .x | mean",
        ".a[] | .b[] | abs | median",
        "mean",
        "abs",
        "  .a  |  sum  ",
    ],
)
def test_validate_selector_accepts_valid_syntax(selector):
    assert validate_selector(selector) is None


@pytest.mark.parametrize(
    "selector,fragment",
    [
        ("", "empty pipeline stage"),
        (".a | ", "empty pipeline stage"),
        ("avg", "neither a path nor a known function"),
        ("x.y", "neither a path nor a known function"),
        (".a..b", "bad selector syntax"),
        (".a[", "bad selector syntax"),
        (".a[-1]", "bad selector syntax"),
        (".a b", "bad selector syntax"),
        (".9seeds", "bad selector syntax"),
        ('["unterminated]', "bad selector syntax"),
    ],
)
def test_validate_selector_rejects_bad_syntax(selector, fragment):
    with pytest.raises(LedgerError, match=re.escape(fragment)):
        validate_selector(selector)


def test_validate_selector_does_not_touch_data(summary):
    validate_selector(".no.such.path[3]")
    with pytest.raises(LedgerError, match="key 'no' not found"):
        select(summary, ".no.such.path[3]")


# --- exit codes through the CLI ---------------------------------------------


def _cli_project(project, selector):
    return project(
        documents={"paper.tex": "Throughput improved by 12.7 points.\n"},
        artifacts={"results/summary.json": {"improvement": {"throughput_pct": 12.7}}},
        ledger={
            "sources": {"summary": "results/summary.json"},
            "claims": [
                {
                    "name": "headline",
                    "file": "paper.tex",
                    "anchor": {"template": "improved by {num} points"},
                    "expect": 1,
                    "value": f"summary:{selector}",
                }
            ],
        },
    )


def test_resolvable_selector_checks_clean(project, capsys):
    ledger = _cli_project(project, ".improvement.throughput_pct")
    assert main(["check", "--ledger", str(ledger)]) == 0
    assert "PASS" in capsys.readouterr().out


def test_selector_failing_at_resolve_time_exits_config_error(project, capsys):
    ledger = _cli_project(project, ".improvement.latency_pct")
    assert main(["check", "--ledger", str(ledger)]) == 2
    err = capsys.readouterr().err
    assert "CONFIG ERROR" in err
    assert "[summary:.improvement.latency_pct]" in err
    assert "key 'latency_pct' not found" in err


def test_bad_selector_syntax_exits_config_error_before_any_check(project, capsys):
    ledger = _cli_project(project, ".improvement..throughput_pct")
    assert main(["check", "--ledger", str(ledger)]) == 2
    captured = capsys.readouterr()
    assert "bad selector syntax" in captured.err
    assert "PASS" not in captured.out


# --- known defects (see bugs_found) -----------------------------------------


def test_abs_on_a_non_number_is_a_ledger_error(summary):
    with pytest.raises(LedgerError, match="abs"):
        select(summary, ".label | abs")


def test_short_csv_row_is_a_ledger_error(load):
    with pytest.raises(LedgerError):
        load("results/ragged.csv", "a,b,c\n1,2\n")


def test_stream_result_message_avoids_the_private_class_name(summary):
    with pytest.raises(LedgerError) as exc:
        select(summary, ".xs[]")
    assert "_Stream" not in str(exc.value)


def test_quoted_key_containing_a_pipe_is_selectable(load):
    data = load("results/odd.json", {"a|b": 3})
    assert select(data, '["a|b"]') == 3.0
