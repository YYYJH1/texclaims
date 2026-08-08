"""Tolerance semantics.

Default tolerance encodes "the manuscript number is the source value
correctly rounded to its displayed precision": half a unit in the last
displayed decimal place, exponent-aware for scientific notation.  Explicit
``abs_tol``/``rel_tol`` replace the default; when both are given, satisfying
either one passes (OR semantics).

Slack for floating-point noise is *proportional* to the tolerance rather
than a fixed addend.  A fixed addend would dominate the real tolerance at
small magnitudes — with a 1e-12 addend, a fabricated ``1.5e-12`` audits
clean against a source of ``2.5e-12`` — which would make the check
fail-open exactly where p-values and learning rates live.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .document import ParsedNumber

_REL_SLACK = 1e-9
# Beyond this the half-unit tolerance itself overflows; such a number cannot
# be audited, and saying so is safer than computing an infinite tolerance.
_MAX_DECIMALS = 300


_EXACT_INT_LIMIT = 2 ** 53  # beyond this, float cannot tell neighbours apart


def _exact_mismatch(claimed: ParsedNumber, expected: int | float) -> "Verdict | None":
    """Compare huge integers exactly, where float equality is a lie.

    9007199254740992 and 9007199254740993 are the same float, so a
    float-only comparison certifies a number the artifact does not hold.
    """
    if claimed.decimals != 0 or abs(expected) < _EXACT_INT_LIMIT:
        return None
    if not isinstance(expected, int):
        return None  # a float this large has already lost the exact value
    text = claimed.token.replace("\u2212", "-").replace(",", "").rstrip("\\%")
    try:
        claimed_int = int(text)
    except ValueError:
        return None
    expected_int = int(expected)
    if claimed_int == expected_int:
        return Verdict(True, 0.0, 0.0, "exact-integer")
    return Verdict(False, float(abs(claimed_int - expected_int)), 0.0,
                   "integers beyond float precision differ exactly")


@dataclass(frozen=True)
class Verdict:
    ok: bool
    diff: float
    tolerance: float
    note: str


def display_tolerance(number: ParsedNumber) -> float:
    """Half a unit in the last displayed decimal place, plus relative slack."""
    if abs(number.decimals) > _MAX_DECIMALS:
        raise OverflowError(f"exponent out of auditable range: {number.token!r}")
    return 0.5 * 10.0 ** (-number.decimals) * (1.0 + _REL_SLACK)


def check_value(
    claimed: ParsedNumber,
    expected: int | float,
    abs_tol: float | None = None,
    rel_tol: float | None = None,
) -> Verdict:
    try:
        if not math.isfinite(claimed.value) or not math.isfinite(expected):
            return Verdict(False, math.inf, 0.0, "value is not finite")
    except OverflowError:  # an int too large to convert to float
        return Verdict(False, math.inf, 0.0, "value is out of the auditable range")
    if abs_tol is None and rel_tol is None:
        # Only the default path needs exact integer handling; an explicit
        # tolerance is the author saying how close is close enough.
        exact = _exact_mismatch(claimed, expected)
        if exact is not None:
            return exact
    diff = abs(claimed.value - expected)
    if not math.isfinite(diff):
        # Subtracting two finite values can still overflow; a difference the
        # arithmetic cannot represent must not be compared against anything.
        return Verdict(False, math.inf, 0.0, "difference overflows")
    if abs_tol is None and rel_tol is None:
        try:
            tol = display_tolerance(claimed)
        except OverflowError:
            return Verdict(False, diff, 0.0, "exponent out of auditable range")
        return Verdict(math.isfinite(tol) and diff <= tol, diff, tol,
                       "display-precision")
    tolerances: list[tuple[float, str]] = []
    if abs_tol is not None:
        tolerances.append((abs_tol * (1.0 + _REL_SLACK), "abs_tol"))
    if rel_tol is not None:
        tolerances.append((rel_tol * abs(expected) * (1.0 + _REL_SLACK), "rel_tol"))
    for tol, note in tolerances:
        if math.isfinite(tol) and diff <= tol:
            return Verdict(True, diff, tol, note)
    tol, note = max(tolerances)
    return Verdict(False, diff, tol, note)
