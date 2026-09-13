"""The coverage scan: negative-space auditing.

Inside every declared scan region, each number token must be covered by a
claim or an exemption — an unclaimed number is exactly where a fabricated
or stale figure hides.  The scan always runs the full check pass first, so
coverage can never be faked by a stale ledger.
"""

from __future__ import annotations

import re

from .anchor import _flex_escape
from .audit import CheckState, run_check
from .document import NUMBER_RE, Document, percent_suffix
from .errors import LedgerError
from .ledger import Ledger, ScanRegion
from .report import UNMAPPED, Record, Report


def _locate(doc: Document, literal: str, which: str, region: ScanRegion,
            search_from: int = 0) -> tuple[int, int]:
    # Region bounds are literal source text, so they are located in the raw
    # document: a \label{...} makes a natural boundary and masking would hide
    # it.  Offsets are shared, since masking preserves length.
    pattern = re.compile(_flex_escape(literal), re.MULTILINE)
    hits = [m for m in pattern.finditer(doc.raw, search_from)]
    if len(hits) != 1:
        raise LedgerError(
            f"scan region {which} anchor {literal!r} in {region.file} matched "
            f"{len(hits)} time(s); it must match exactly once")
    return hits[0].span()


def _region_bounds(doc: Document, region: ScanRegion) -> tuple[int, int]:
    start = 0
    if region.start is not None:
        start = _locate(doc, region.start, "start", region)[1]
    end = len(doc.raw)
    if region.end is not None:
        end_span = _locate(doc, region.end, "end", region, search_from=start)
        end = end_span[0]
    if start >= end:
        raise LedgerError(f"scan region in {region.file} is empty or inverted")
    return start, end


def _covered(doc: Document, token_span: tuple[int, int],
             claimed: set[tuple[int, int]]) -> bool:
    if token_span in claimed:
        return True
    # A claim may capture "94.2" while the scan token is "94.2\%".  Only that
    # exact remainder counts: a claim capturing "88" must not vouch for the
    # token "88.9", whose decimals would then never be audited.
    for start, end in claimed:
        if start == token_span[0] and end <= token_span[1]:
            if percent_suffix(doc.raw[end:token_span[1]]):
                return True
    return False


def run_scan(ledger: Ledger, report: Report | None = None) -> CheckState:
    state = run_check(ledger, report)
    for region in ledger.scan_regions:
        doc = state.document(region.file)
        start, end = _region_bounds(doc, region)
        claimed = state.claimed_spans.get(region.file, set())
        for tok in NUMBER_RE.finditer(doc.scan_masked, start, end):
            if _covered(doc, tok.span(0), claimed):
                continue
            state.report.add(Record(
                status=UNMAPPED, name="-", file=region.file,
                line=doc.line_of(tok.start()), claimed=tok.group(0),
                note=doc.snippet(tok.start(), tok.end()),
            ))
    for name in ledger.unlisted_includes:
        state.report.warn(
            f"the manuscript pulls in {name!r}, which is not in 'documents'; "
            "nothing in it is audited")
    if not ledger.scan_regions:
        state.report.warn("no scan regions declared; coverage scan had nothing to do")
    else:
        # A multi-file paper is the normal case, and a document nobody scans is
        # a silent hole: the run goes green while a whole section is unaudited.
        scanned = {r.file for r in ledger.scan_regions}
        for doc in ledger.documents:
            if doc not in scanned:
                state.report.warn(
                    f"{doc} has no scan region; nothing in it is checked for coverage")
    return state
