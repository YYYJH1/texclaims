"""Anchor compilation and matching.

Three anchor kinds locate numbers in a masked document:

* ``template`` — a literal snippet with ``{num}`` placeholders.  Whitespace
  in the literal matches any whitespace run (LaTeX reflow safe); each
  ``{num}`` compiles to a capturing number-token group.
* ``pattern``  — a raw regex (inline or from the named ``patterns`` table),
  compiled verbatim with ``re.MULTILINE``; capture groups carry the numbers.
* ``near``     — a literal context; the anchored number is the N-th number
  token from the start of the context to the end of that paragraph, so the
  context may sit before the number rather than around it.

Multiplicity is exact: the anchor must occur ``expect`` times in its file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .document import NUMBER_GROUP, NUMBER_RE, Document, percent_suffix
from .errors import LedgerError
from .ledger import Anchor


@dataclass(frozen=True)
class NumberHit:
    """One anchored number occurrence: a capture with its byte span."""
    group: int
    text: str
    span: tuple[int, int]


@dataclass(frozen=True)
class AnchorMatch:
    span: tuple[int, int]  # span of the whole anchor occurrence
    numbers: tuple[NumberHit, ...]


def _flex_escape(literal: str) -> str:
    """Escape a literal for regex use; whitespace runs become ``\\s+``."""
    out: list[str] = []
    i = 0
    while i < len(literal):
        ch = literal[i]
        if ch.isspace():
            while i < len(literal) and literal[i].isspace():
                i += 1
            out.append(r"\s+")
            continue
        out.append(re.escape(ch))
        i += 1
    return "".join(out)


def compile_template(template: str, path: str) -> re.Pattern[str]:
    parts = template.split("{num}")
    body = NUMBER_GROUP.join(_flex_escape(part) for part in parts)
    try:
        return re.compile(body, re.MULTILINE)
    except re.error as exc:  # pragma: no cover - escape should prevent this
        raise LedgerError(f"template compiled to invalid regex: {exc}", path) from exc


def _compile_pattern(pattern: str, path: str) -> re.Pattern[str]:
    try:
        compiled = re.compile(pattern, re.MULTILINE)
    except re.error as exc:
        raise LedgerError(f"invalid regex: {exc}", path) from exc
    if compiled.groups < 1:
        raise LedgerError("pattern must contain at least one capture group", path)
    return compiled


def _reject_partial_capture(
    doc: Document, span: tuple[int, int], text: str, group: int, path: str
) -> None:
    """Refuse a capture that is only part of the number standing there.

    A group matching "88" out of "88.9", or one that leaves the minus sign
    outside, looks like a valid number in isolation.  Accepting it would
    audit a number the manuscript never printed — and, worse, widen the
    display tolerance to match the truncated precision.
    """
    view = doc.scan_masked
    stops_inside = re.match(r"\.\d", view[span[1]:span[1] + 2])
    starts_inside = re.search(r"\d\.$", view[max(0, span[0] - 2):span[0]])
    if stops_inside or starts_inside:
        # NUMBER_RE excludes version-like dotted runs. Its absence cannot
        # authorize a capture of "1.2" out of the manuscript's "1.2.3".
        lo, hi = span
        while lo > 0 and (view[lo - 1].isdigit() or view[lo - 1] == "."):
            lo -= 1
        while hi < len(view) and (view[hi].isdigit() or view[hi] == "."):
            hi += 1
        direction = "stops" if stops_inside else "starts"
        raise LedgerError(
            f"capture group {group} matched {text!r} but the manuscript prints "
            f"{view[lo:hi]!r} at that position; the group {direction} inside it "
            "(takes only part of a dotted run)", path)
    token = doc.token_at(span[0])
    if token is None:  # identifier-glued numbers remain explicitly anchorable
        return
    if token.start() < span[0]:
        raise LedgerError(
            f"capture group {group} matched {text!r} but the number at that position "
            f"is {token.group(0)!r}; the group starts inside it (include the sign or "
            "the leading digits)", path)
    trailing = doc.scan_masked[span[1]:token.end()]
    if token.end() < span[1] or not percent_suffix(trailing):
        raise LedgerError(
            f"capture group {group} matched {text!r} but the number at that position "
            f"is {token.group(0)!r}; the group stops inside it (widen it to the whole "
            "number)", path)


def _regex_matches(
    compiled: re.Pattern[str], doc: Document, wanted_groups: list[int], path: str
) -> list[AnchorMatch]:
    # Validate the requested groups against the pattern itself, not against a
    # match: an impossible group index must fail even when nothing matched.
    for g in wanted_groups:
        if g > compiled.groups:
            raise LedgerError(
                f"anchor has {compiled.groups} capture group(s), group {g} requested", path)
    matches: list[AnchorMatch] = []
    for m in compiled.finditer(doc.masked):
        hits: list[NumberHit] = []
        for g in wanted_groups:
            text = m.group(g)
            if text is None:
                raise LedgerError(f"capture group {g} did not participate in a match", path)
            if not re.fullmatch(NUMBER_GROUP, text):
                raise LedgerError(
                    f"capture group {g} matched {text!r}, which is not a number token "
                    "(tighten the group so it captures only the number)", path)
            _reject_partial_capture(doc, m.span(g), text, g, path)
            hits.append(NumberHit(group=g, text=text, span=m.span(g)))
        matches.append(AnchorMatch(span=m.span(0), numbers=tuple(hits)))
    return matches


_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n")


def _near_matches(anchor: Anchor, doc: Document, path: str) -> list[AnchorMatch]:
    context_re = re.compile(_flex_escape(anchor.context or ""), re.MULTILINE)
    matches: list[AnchorMatch] = []
    for m in context_re.finditer(doc.masked):
        # Search from the start of the context to the end of its paragraph, so
        # a context that merely precedes the number still anchors it.
        # Masked comments or labels are not blank lines in the manuscript.
        para = _PARAGRAPH_BREAK.search(doc.raw, m.end())
        limit = para.start() if para else len(doc.masked)
        tokens = list(NUMBER_RE.finditer(doc.scan_masked, m.start(), limit))
        if len(tokens) < anchor.occurrence:
            raise LedgerError(
                f"context matched at line {doc.line_of(m.start())} but its paragraph "
                f"holds {len(tokens)} number token(s), occurrence {anchor.occurrence} "
                "requested", path)
        tok = tokens[anchor.occurrence - 1]
        hits = (NumberHit(group=1, text=tok.group(0), span=tok.span(0)),)
        # The span is the token alone, not the whole context: an exemption
        # covers what it anchors, and a context that merely precedes the
        # number must not silently waive the other numbers along the way.
        matches.append(AnchorMatch(span=tok.span(0), numbers=hits))
    return matches


def find_anchor_matches(
    anchor: Anchor, doc: Document, wanted_groups: list[int], path: str
) -> list[AnchorMatch]:
    """All occurrences of the anchor in the document (multiplicity unchecked)."""
    if anchor.kind == "template":
        compiled = compile_template(anchor.template or "", path)
        n_groups = compiled.groups
        groups = wanted_groups or list(range(1, n_groups + 1))
        return _regex_matches(compiled, doc, groups, path)
    if anchor.kind == "pattern":
        compiled = _compile_pattern(anchor.pattern or "", path)
        groups = wanted_groups or [1]
        return _regex_matches(compiled, doc, groups, path)
    return _near_matches(anchor, doc, path)
