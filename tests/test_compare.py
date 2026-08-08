"""Tolerance semantics: display precision, explicit tolerances, non-finite values."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from texclaims.audit import run_check
from texclaims.cli import main
from texclaims.compare import check_value, display_tolerance
from texclaims.document import parse_number
from texclaims.ledger import load_ledger
from texclaims.report import FAIL, PASS, Report

PAPER = (
    "\\section{Evaluation}\n"
    "FastCache improves throughput by <NUM>\\% over the tuned baseline.\n"
)
CLAIMED_LINE = 2


def tol(token: str) -> float:
    return display_tolerance(parse_number(token))


def verdict(token: str, expected: float, **tolerances):
    return check_value(parse_number(token), expected, **tolerances)


@pytest.fixture
def paper(project):
    """Build a one-claim project; the manuscript prints ``claimed`` verbatim."""

    def build(claimed: str, expected: float, **claim_fields) -> Path:
        return project(
            documents={"paper.tex": PAPER.replace("<NUM>", claimed)},
            artifacts={"results/summary.json": {"throughput_pct": expected}},
            ledger={
                "sources": {"summary": "results/summary.json"},
                "claims": [
                    {
                        "name": "headline",
                        "file": "paper.tex",
                        "anchor": {"template": "throughput by {num}\\%"},
                        "expect": 1,
                        "value": "summary:.throughput_pct",
                        **claim_fields,
                    }
                ],
            },
        )

    return build


def audit(ledger_path: Path) -> Report:
    return run_check(load_ledger(ledger_path)).report


def only(report: Report):
    assert len(report.records) == 1, report.records
    return report.records[0]


# --- default tolerance: half a unit in the last displayed decimal ------------


@pytest.mark.parametrize(
    "token, expected_tol",
    [
        ("12.7", 0.05),
        ("3.37", 0.005),
        ("5", 0.5),
        ("0.468", 0.0005),
        ("94.218", 0.0005),
        ("1,234", 0.5),
        ("12.7\\%", 0.05),
        ("-12.7", 0.05),
    ],
)
def test_display_tolerance_is_half_unit_in_last_decimal(token, expected_tol):
    assert tol(token) == pytest.approx(expected_tol)


@pytest.mark.parametrize(
    "token, decimals, expected_tol",
    [
        ("1.5e-3", 4, 5e-5),
        ("1.5E-3", 4, 5e-5),
        ("2e-3", 3, 5e-4),
        ("1.25e-2", 4, 5e-5),
        ("1.5e3", -2, 50.0),
        ("2e6", -6, 5e5),
    ],
)
def test_display_tolerance_combines_mantissa_decimals_and_exponent(
    token, decimals, expected_tol
):
    assert parse_number(token).decimals == decimals
    assert tol(token) == pytest.approx(expected_tol)


def test_scientific_notation_matches_the_plain_form_it_displays():
    assert tol("1.5e-3") == pytest.approx(tol("0.0015"))
    assert tol("2e-3") == pytest.approx(tol("0.002"))


def test_fewer_mantissa_digits_means_a_coarser_tolerance():
    """'1.5e3' shows precision to the hundreds; plain '1500' to the unit."""
    assert tol("1.5e3") == pytest.approx(50.0)
    assert tol("1500") == pytest.approx(0.5)
    assert verdict("1.5e3", 1520.0).ok
    assert not verdict("1500", 1520.0).ok


# --- correct rounding must pass ---------------------------------------------


def test_correctly_rounded_one_decimal_passes():
    v = verdict("12.7", 12.73421)
    assert v.ok
    assert v.note == "display-precision"
    assert v.diff == pytest.approx(0.03421)
    assert v.tolerance == pytest.approx(0.05)


def test_correctly_rounded_two_decimal_passes():
    v = verdict("4.87", 4.8659)
    assert v.ok
    assert v.diff == pytest.approx(0.0041)
    assert v.tolerance == pytest.approx(0.005)


def test_rounded_integer_passes():
    assert verdict("5", 5.4999).ok
    assert verdict("5", 4.5001).ok


def test_exact_half_unit_boundary_passes():
    v = verdict("12.7", 12.75)
    assert v.ok
    assert v.diff == pytest.approx(0.05)


def test_just_past_half_unit_fails():
    v = verdict("12.7", 12.76)
    assert not v.ok
    assert v.diff == pytest.approx(0.06)
    assert v.tolerance == pytest.approx(0.05)


def test_correctly_rounded_scientific_value_passes():
    assert verdict("1.5e-3", 1.5432e-3).ok


def test_scientific_tolerance_is_tight_enough_to_catch_a_wrong_last_digit():
    v = verdict("1.5e-3", 1.6e-3)
    assert not v.ok
    assert v.diff == pytest.approx(1e-4)
    assert v.tolerance == pytest.approx(5e-5)


# --- fabricated numbers must fail -------------------------------------------


def test_fabricated_number_fails():
    v = verdict("0.468", 0.488)
    assert not v.ok
    assert v.note == "display-precision"
    assert v.diff == pytest.approx(0.02)
    assert v.tolerance == pytest.approx(0.0005)


def test_wrong_leading_digit_fails():
    v = verdict("13.7", 12.7)
    assert not v.ok
    assert v.diff == pytest.approx(1.0)
    assert v.tolerance == pytest.approx(0.05)


def test_truncation_instead_of_rounding_fails():
    assert not verdict("4.86", 4.8659).ok


# --- explicit abs_tol / rel_tol replace the default --------------------------


def test_abs_tol_widens_beyond_the_display_default():
    assert not verdict("12.7", 12.9).ok
    v = verdict("12.7", 12.9, abs_tol=0.5)
    assert v.ok
    assert v.note == "abs_tol"
    assert v.tolerance == pytest.approx(0.5)


def test_abs_tol_replaces_rather_than_widens_the_display_default():
    assert verdict("12.7", 12.73421).ok
    v = verdict("12.7", 12.73421, abs_tol=0.001)
    assert not v.ok
    assert v.note == "abs_tol"
    assert v.tolerance == pytest.approx(0.001)


def test_rel_tol_scales_with_the_expected_value():
    passing = verdict("100", 110.0, rel_tol=0.1)
    assert passing.ok
    assert passing.note == "rel_tol"
    assert passing.tolerance == pytest.approx(11.0)

    failing = verdict("100", 112.0, rel_tol=0.1)
    assert not failing.ok
    assert failing.tolerance == pytest.approx(11.2)


def test_rel_tol_uses_the_magnitude_of_expected_not_claimed():
    assert verdict("1", 100.0, rel_tol=1.0).ok
    assert not verdict("100", 1.0, rel_tol=1.0).ok


def test_either_tolerance_alone_is_enough_to_pass():
    by_abs = verdict("1.0", 1.4, abs_tol=1.0, rel_tol=0.0001)
    assert by_abs.ok
    assert by_abs.note == "abs_tol"

    by_rel = verdict("1.0", 1.4, abs_tol=0.001, rel_tol=0.5)
    assert by_rel.ok
    assert by_rel.note == "rel_tol"


def test_both_tolerances_failing_reports_the_wider_one():
    v = verdict("1.0", 1.4, abs_tol=0.001, rel_tol=0.01)
    assert not v.ok
    assert v.note == "rel_tol"
    assert v.tolerance == pytest.approx(0.014)


# --- non-finite values are always a failure ---------------------------------


@pytest.mark.parametrize("expected", [math.inf, -math.inf, math.nan])
def test_non_finite_expected_fails(expected):
    v = verdict("12.7", expected)
    assert not v.ok
    assert v.note == "value is not finite"
    assert v.diff == math.inf
    assert v.tolerance == 0.0


def test_non_finite_claimed_fails():
    assert parse_number("1e400").value == math.inf
    v = verdict("1e400", 1.0)
    assert not v.ok
    assert v.note == "value is not finite"


@pytest.mark.parametrize("tolerances", [{"abs_tol": 1e300}, {"rel_tol": 1e300}])
def test_non_finite_never_passes_even_with_an_enormous_tolerance(tolerances):
    assert not verdict("12.7", math.nan, **tolerances).ok
    assert not verdict("12.7", math.inf, **tolerances).ok


# --- end to end through the check pass and the CLI ---------------------------


def test_check_records_a_pass_for_a_correctly_rounded_claim(paper):
    ledger_path = paper("12.7", 12.73421)
    report = audit(ledger_path)
    record = only(report)
    assert record.status == PASS
    assert record.name == "headline"
    assert record.file == "paper.tex"
    assert record.line == CLAIMED_LINE
    assert record.claimed == "12.7"
    assert record.expected == pytest.approx(12.73421)
    assert record.tolerance == pytest.approx(0.05)
    assert record.note == ""
    assert report.exit_code() == 0


def test_check_records_a_fail_with_the_diff_in_the_note(paper):
    report = audit(paper("13.7", 12.73421))
    record = only(report)
    assert record.status == FAIL
    assert record.claimed == "13.7"
    assert record.tolerance == pytest.approx(0.05)
    assert record.note == (
        "|claimed - expected| = 0.96579 exceeds display-precision tolerance"
    )
    assert report.exit_code() == 1


def test_check_honours_ledger_rel_tol(paper):
    assert audit(paper("12.7", 12.9)).exit_code() == 1
    report = audit(paper("12.7", 12.9, rel_tol=0.05))
    record = only(report)
    assert record.status == PASS
    assert record.tolerance == pytest.approx(0.645)
    assert report.exit_code() == 0


def test_check_fails_on_a_non_finite_artifact_value(paper):
    report = audit(paper("12.7", math.nan))
    record = only(report)
    assert record.status == FAIL
    assert record.tolerance == 0.0
    assert "value is not finite" in record.note


def test_cli_exits_zero_when_the_manuscript_number_is_correctly_rounded(paper, capsys):
    code = main(["check", "--ledger", str(paper("12.7", 12.73421))])
    out, err = capsys.readouterr()
    assert code == 0
    assert out.startswith("PASS")
    assert "claimed=12.7" in out
    assert "1 PASS, 0 FAIL" in err


def test_cli_exits_one_on_a_fabricated_number(paper, capsys):
    code = main(["check", "--ledger", str(paper("13.7", 12.73421))])
    out, err = capsys.readouterr()
    assert code == 1
    assert out.startswith("FAIL")
    assert "exceeds display-precision tolerance" in out
    assert "0 PASS, 1 FAIL" in err
    assert "FAIL ==" in err


# --- known defects (see bugs_found) -----------------------------------------


def test_epsilon_does_not_swallow_a_fabrication_at_tiny_scale():
    v = verdict("1.5e-12", 2.5e-12)
    assert v.tolerance == pytest.approx(5e-14)
    assert not v.ok


def test_extreme_exponent_reports_instead_of_crashing():
    assert not verdict("0.0e400", 1.0).ok
