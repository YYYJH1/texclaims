"""The check pass: reconcile every claim and exemption against the manuscript.

Produces the record stream and the per-file registry of claimed spans that
the coverage scan consumes.  Fail-closed rules enforced here:

* an anchor must occur exactly ``expect`` times (0 occurrences of a
  non-optional claim is MISS; any other mismatch is FAIL);
* every number occurrence may be claimed by at most one claim/exemption;
* sha256-pinned artifacts must hash to their pinned digest.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from .anchor import find_anchor_matches
from .artifact import load_artifact, select
from .compare import check_value
from .document import NUMBER_RE, Document, parse_number
from .errors import LedgerError
from .ledger import Claim, Exemption, Ledger, ValueRef
from .report import FAIL, MISS, PASS, Record, Report

Span = tuple[int, int]


@dataclass
class CheckState:
    ledger: Ledger
    report: Report
    documents: dict[str, Document] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)
    claimed_spans: dict[str, set[Span]] = field(default_factory=dict)
    span_owner: dict[tuple[str, int], str] = field(default_factory=dict)

    def document(self, rel_name: str) -> Document:
        if rel_name not in self.documents:
            self.documents[rel_name] = Document(self.ledger.root, rel_name)
        return self.documents[rel_name]

    def artifact(self, source: str) -> Any:
        if source not in self.artifacts:
            path = self.ledger.sources[source]
            self.artifacts[source] = load_artifact(path, f"sources.{source}")
        return self.artifacts[source]

    def resolve(self, ref: ValueRef) -> float:
        try:
            return select(self.artifact(ref.source), ref.selector)
        except LedgerError as exc:
            raise LedgerError(f"[{ref.raw}] {exc}") from exc

    def owner_of(self, rel_name: str, span: Span) -> str:
        return self.span_owner.get((rel_name, span[0]), "another entry")

    def try_claim_span(self, rel_name: str, span: Span, owner: str = "") -> bool:
        """Register ownership of one number occurrence.

        Ownership is keyed on where the number *starts*: a claim capturing
        "12.7" and an exemption tokenising "12.7\\%" are the same occurrence,
        and only one entry may own it.
        """
        spans = self.claimed_spans.setdefault(rel_name, set())
        if any(existing[0] == span[0] for existing in spans):
            return False
        spans.add(span)
        if owner:
            self.span_owner[(rel_name, span[0])] = owner
        return True


def _verify_pins(state: CheckState) -> None:
    for rel, digest in state.ledger.sha256_pins.items():
        h = hashlib.sha256()
        with open(state.ledger.root / rel, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        actual = h.hexdigest()
        if actual != digest:
            state.report.add(Record(
                status=FAIL, name="sha256-pin", file=rel,
                note=f"artifact hash {actual[:12]}… != pinned {digest[:12]}…",
            ))


def _check_claim(state: CheckState, claim: Claim) -> None:
    doc = state.document(claim.file)
    wanted = sorted(claim.groups) if claim.groups else []
    path = f"claim '{claim.name}'"
    matches = find_anchor_matches(claim.anchor, doc, wanted, path)

    if not matches:
        if not claim.optional:
            state.report.add(Record(
                status=MISS, name=claim.name, file=claim.file,
                note="anchor not found (re-anchor the claim; do not delete it)",
            ))
        return
    if len(matches) != claim.expect:
        state.report.add(Record(
            status=FAIL, name=claim.name, file=claim.file,
            line=doc.line_of(matches[0].span[0]),
            note=f"anchor matched {len(matches)} time(s), expect {claim.expect}",
        ))
        return

    # Resolve expectations once per claim.
    expected: dict[int, float] = {}
    if claim.value is not None:
        expected[1] = claim.transform.apply(state.resolve(claim.value))
    else:
        for g, ref in claim.groups.items():
            expected[g] = claim.transform.apply(state.resolve(ref))

    for match in matches:
        for hit in match.numbers:
            line = doc.line_of(hit.span[0])
            label = f"{claim.name}#g{hit.group}" if claim.groups else claim.name
            if not state.try_claim_span(claim.file, hit.span, claim.name):
                state.report.add(Record(
                    status=FAIL, name=label, file=claim.file, line=line,
                    claimed=hit.text,
                    note="this number occurrence is already claimed by "
                         f"{state.owner_of(claim.file, hit.span)!r}",
                ))
                continue
            target = expected[hit.group if claim.groups else 1]
            claimed = parse_number(hit.text)
            verdict = check_value(claimed, target, claim.abs_tol, claim.rel_tol)
            state.report.add(Record(
                status=PASS if verdict.ok else FAIL, name=label,
                file=claim.file, line=line, claimed=hit.text,
                expected=target, tolerance=verdict.tolerance,
                note="" if verdict.ok else
                f"|claimed - expected| = {verdict.diff:.6g} exceeds {verdict.note} tolerance",
            ))


def _check_exemption(state: CheckState, exemption: Exemption) -> None:
    doc = state.document(exemption.file)
    path = f"exemption '{exemption.name}'"
    matches = find_anchor_matches(exemption.anchor, doc, [], path)
    if len(matches) != exemption.expect:
        state.report.add(Record(
            status=FAIL, name=exemption.name, file=exemption.file,
            note=f"exemption anchor matched {len(matches)} time(s), expect {exemption.expect}",
        ))
        return
    for match in matches:
        # An exemption covers every number token inside its anchor occurrence,
        # tokenised on the same view the coverage scan uses: on `masked` a
        # number glued to a control word could never be waived at all.
        for tok in NUMBER_RE.finditer(doc.scan_masked, match.span[0], match.span[1]):
            if not state.try_claim_span(exemption.file, tok.span(0), exemption.name):
                state.report.add(Record(
                    status=FAIL, name=exemption.name, file=exemption.file,
                    line=doc.line_of(tok.start()), claimed=tok.group(0),
                    note="this number occurrence is already claimed by "
                         f"{state.owner_of(exemption.file, tok.span(0))!r}",
                ))


def run_check(ledger: Ledger, report: Report | None = None) -> CheckState:
    state = CheckState(ledger=ledger, report=report or Report())
    _verify_pins(state)
    for claim in ledger.claims:
        _check_claim(state, claim)
    for exemption in ledger.exemptions:
        _check_exemption(state, exemption)
    unused = set(ledger.patterns) - ledger.used_patterns
    for name in sorted(unused):
        state.report.warn(f"pattern {name!r} is defined but never used")
    return state
