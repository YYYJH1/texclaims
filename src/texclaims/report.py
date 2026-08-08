"""Record model, output rendering, and exit-code policy.

Line protocol (stable, grep-friendly):

    PASS     <name> <file>:<line> claimed=<v> expected=<v> tol=<t>
    FAIL     <name> <file>:<line> ... :: <note>
    MISS     <name> <file> :: anchor not found
    UNMAPPED - <file>:<line> claimed=<t> :: <snippet>
    WARN     <message>

Ledger lines go to stdout; the summary/verdict line goes to stderr.
Exit codes: 0 clean, 1 reconciliation failure, 2 configuration error.
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass, field

def _jsonable(value: float | None) -> float | str | None:
    """Non-finite numbers become text; bare NaN is not valid JSON."""
    if value is None or math.isfinite(value):
        return value
    return str(value)


PASS = "PASS"
FAIL = "FAIL"
MISS = "MISS"
UNMAPPED = "UNMAPPED"

_FAILING = (FAIL, MISS, UNMAPPED)


@dataclass(frozen=True)
class Record:
    status: str
    name: str
    file: str
    line: int | None = None
    claimed: str | None = None
    expected: float | None = None
    tolerance: float | None = None
    note: str = ""

    def render(self) -> str:
        loc = self.file if self.line is None else f"{self.file}:{self.line}"
        parts = [f"{self.status:<8} {self.name} {loc}"]
        if self.claimed is not None:
            parts.append(f"claimed={self.claimed}")
        if self.expected is not None:
            parts.append(f"expected={self.expected:.10g}")
        if self.tolerance is not None:
            parts.append(f"tol={self.tolerance:.3g}")
        line = " ".join(parts)
        if self.note:
            line += f" :: {self.note}"
        return line


@dataclass
class Report:
    records: list[Record] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # A non-strict scan reports uncovered numbers without failing the run, so
    # the rendered verdict has to agree with the exit code.
    unmapped_is_failure: bool = True

    def add(self, record: Record) -> None:
        self.records.append(record)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def counts(self) -> dict[str, int]:
        counts = {PASS: 0, FAIL: 0, MISS: 0, UNMAPPED: 0}
        for record in self.records:
            counts[record.status] = counts.get(record.status, 0) + 1
        return counts

    @property
    def failed(self) -> bool:
        statuses = _FAILING if self.unmapped_is_failure else (FAIL, MISS)
        return any(r.status in statuses for r in self.records)

    def exit_code(self) -> int:
        return 1 if self.failed else 0

    def emit_text(self) -> None:
        for record in self.records:
            print(record.render())
        sys.stdout.flush()  # or the summary on stderr overtakes the records
        for warning in self.warnings:
            print(f"WARN     {warning}", file=sys.stderr)
        c = self.counts()
        verdict = "FAIL" if self.failed else "OK"
        print(
            f"== {c[PASS]} PASS, {c[FAIL]} FAIL, {c[MISS]} MISS, "
            f"{c[UNMAPPED]} UNMAPPED — {verdict} ==",
            file=sys.stderr,
        )

    def emit_json(self) -> None:
        payload = {
            "records": [
                {
                    "status": r.status,
                    "name": r.name,
                    "file": r.file,
                    "line": r.line,
                    "claimed": r.claimed,
                    "expected": _jsonable(r.expected),
                    "tolerance": _jsonable(r.tolerance),
                    "note": r.note,
                }
                for r in self.records
            ],
            "warnings": list(self.warnings),
            "summary": {**self.counts(), "verdict": "FAIL" if self.failed else "OK"},
        }
        # allow_nan would emit bare NaN/Infinity, which no strict JSON parser
        # accepts; a non-finite expectation is rendered as its text instead.
        json.dump(payload, sys.stdout, indent=2, sort_keys=True, allow_nan=False,
                  default=str)
        print()
