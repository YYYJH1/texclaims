"""Artifact loading and the jq-subset selector.

Supported sources: JSON (any shape) and CSV (header row -> list of dicts,
numeric-looking cells coerced to int/float).

Selector grammar — pipeline stages separated by ``|``:

* path stage:      ``.key``  ``.quoted-or-plain-ident``  ``["any key"]``
                   ``['any key']``  ``[0]``  ``[]`` (wildcard)
* function stage:  ``mean`` ``median`` ``max`` ``min`` ``sum`` ``len``
                   ``abs`` ``first`` ``last``

After a wildcard the stream semantics apply: later path steps map over the
elements, functions reduce the stream to a scalar.  The final result of a
value reference must be a scalar number.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
import statistics
from pathlib import Path
from typing import Any

from .errors import LedgerError


class _Stream(list):
    """Marker: a stream of values produced by a ``[]`` wildcard."""


_STEP_RE = re.compile(
    r"\.(?P<ident>[A-Za-z_][\w\-]*)"
    r"|\[\s*\"(?P<dq>[^\"]*)\"\s*\]"
    r"|\[\s*'(?P<sq>[^']*)'\s*\]"
    r"|\[\s*(?P<index>\d+)\s*\]"
    r"|\[\s*\]"
)

def _sum(values: list) -> int | float:
    """Exact for integers, error-compensated for floats."""
    if all(isinstance(v, int) for v in values):
        return sum(values)  # plain sum is exact on ints; fsum would truncate
    return math.fsum(values)


_FUNCS = {
    "mean": statistics.fmean,
    "median": statistics.median,
    "max": max,
    "min": min,
    "sum": _sum,
    "len": len,
    "first": lambda xs: xs[0],
    "last": lambda xs: xs[-1],
}


def _coerce(cell: str) -> Any:
    text = cell.strip()
    for cast in (int, float):
        try:
            return cast(text)
        except ValueError:
            continue
    return cell


def load_artifact(path: Path, ledger_path: str) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise LedgerError(f"cannot read artifact: {exc}", path=ledger_path) from exc
    if path.suffix.lower() == ".csv":
        text = text.lstrip("\ufeff")  # Excel and pandas write a BOM
        out = []
        # splitlines() would turn a quoted "12\n34" cell into numeric 1234.
        # Strict quoting also refuses a truncated final quoted field.
        reader = csv.DictReader(io.StringIO(text), strict=True)
        try:
            header = reader.fieldnames
        except csv.Error as exc:
            raise LedgerError(f"malformed CSV: {exc}", ledger_path) from exc
        if not header:  # an empty file is not a zero-row table
            raise LedgerError("CSV has no header row", ledger_path)
        duplicates = sorted({h for h in header if header.count(h) > 1})
        if duplicates:  # DictReader keeps only the last; a named column could vanish
            raise LedgerError(
                f"CSV header repeats column(s) {duplicates}", ledger_path)
        try:
            rows = list(reader)
        except csv.Error as exc:
            raise LedgerError(f"malformed CSV: {exc}", ledger_path) from exc
        for lineno, row in enumerate(rows, start=2):
            if None in row:  # DictReader stores surplus fields under its restkey
                raise LedgerError(
                    f"CSV row {lineno} has {len(row[None])} extra field(s) beyond "
                    "the header", ledger_path)
            missing = sorted(k for k, v in row.items() if k is not None and v is None)
            if missing:  # a truncated artifact must not audit as if it were whole
                raise LedgerError(
                    f"CSV row {lineno} is missing column(s) {missing}", ledger_path)
            out.append({k: _coerce(v) for k, v in row.items()})
        return out
    def _no_dupes(pairs):
        seen: dict = {}
        for k, v in pairs:
            if k in seen:
                raise LedgerError(
                    f"artifact repeats key {k!r}; which value is the result?",
                    path=ledger_path)
            seen[k] = v
        return seen

    try:
        return json.loads(text, object_pairs_hook=_no_dupes)
    except json.JSONDecodeError as exc:
        raise LedgerError(f"artifact is not valid JSON: {exc}", path=ledger_path) from exc
    except RecursionError as exc:
        raise LedgerError("artifact nests too deeply to parse", path=ledger_path) from exc


def _apply_key(node: Any, key: str, consumed: str) -> Any:
    if isinstance(node, _Stream):
        return _Stream(_apply_key(item, key, consumed) for item in node)
    if not isinstance(node, dict):
        raise LedgerError(f"cannot select key {key!r} on {type(node).__name__} after {consumed!r}")
    if key not in node:
        near = ", ".join(sorted(map(repr, node)) [:6])
        raise LedgerError(f"key {key!r} not found after {consumed!r} (has: {near})")
    return node[key]


def _apply_index(node: Any, index: int, consumed: str) -> Any:
    if isinstance(node, _Stream):
        return _Stream(_apply_index(item, index, consumed) for item in node)
    if not isinstance(node, list):
        raise LedgerError(f"cannot index [{index}] on {type(node).__name__} after {consumed!r}")
    if index >= len(node):
        raise LedgerError(f"index [{index}] out of range (len {len(node)}) after {consumed!r}")
    return node[index]


def _apply_wildcard(node: Any, consumed: str) -> _Stream:
    if isinstance(node, _Stream):
        flat: list[Any] = []
        for item in node:
            flat.extend(_apply_wildcard(item, consumed))
        return _Stream(flat)
    if isinstance(node, dict):
        return _Stream(node.values())
    if isinstance(node, list):
        return _Stream(node)
    raise LedgerError(f"cannot expand [] on {type(node).__name__} after {consumed!r}")


def _apply_path(node: Any, stage: str) -> Any:
    pos = 0
    while pos < len(stage):
        m = _STEP_RE.match(stage, pos)
        if m is None:
            raise LedgerError(f"bad selector syntax at {stage[pos:]!r} in {stage!r}")
        consumed = stage[: m.start()]
        if m.group("ident") is not None:
            node = _apply_key(node, m.group("ident"), consumed)
        elif m.group("dq") is not None:
            node = _apply_key(node, m.group("dq"), consumed)
        elif m.group("sq") is not None:
            node = _apply_key(node, m.group("sq"), consumed)
        elif m.group("index") is not None:
            node = _apply_index(node, int(m.group("index")), consumed)
        else:
            node = _apply_wildcard(node, consumed)
        pos = m.end()
    return node


def _type_name(node: Any) -> str:
    return "stream" if isinstance(node, _Stream) else type(node).__name__


def _apply_func(node: Any, name: str) -> Any:
    if name == "abs":
        # abs(True) is the integer 1; checking only after the function would
        # let a flag pass as a result, including through an abs | mean stream.
        values = node if isinstance(node, _Stream) else [node]
        if any(isinstance(v, bool) for v in values):
            raise LedgerError("function 'abs' received a boolean, not a number")
        try:
            if isinstance(node, _Stream):
                return _Stream(abs(x) for x in node)
            return abs(node)
        except TypeError as exc:
            raise LedgerError(f"function 'abs' failed: {exc}") from exc
    fn = _FUNCS[name]
    if not isinstance(node, (list, _Stream)):
        raise LedgerError(f"function {name!r} needs a list/stream, got {_type_name(node)}")
    values = list(node)
    if not values and name != "len":
        raise LedgerError(f"function {name!r} applied to an empty stream")
    if name != "len" and any(isinstance(v, bool) for v in values):
        # bool is an int in Python; letting it through would average flags.
        raise LedgerError(f"function {name!r} received a boolean, not a number")
    if name != "len" and any(isinstance(v, float) and not math.isfinite(v)
                             for v in values):
        # max/min/median would quietly step around a NaN and certify the rest.
        raise LedgerError(
            f"function {name!r} received a non-finite value; the artifact is corrupt")
    try:
        return fn(values)
    except (TypeError, statistics.StatisticsError) as exc:
        raise LedgerError(f"function {name!r} failed: {exc}") from exc


def _split_stages(selector: str) -> list[str]:
    """Split on ``|`` while respecting quoted key segments."""
    stages: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    for ch in selector:
        if quote is not None:
            buf.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch == "|":
            stages.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    stages.append("".join(buf))
    return stages


def select(root: Any, selector: str) -> int | float:
    """Run a full selector pipeline; the result must be a scalar number.

    An integer is returned as an ``int``: converting to float here would
    silently merge neighbouring values above 2**53.
    """
    node = root
    for raw_stage in _split_stages(selector):
        stage = raw_stage.strip()
        if not stage:
            raise LedgerError(f"empty pipeline stage in selector {selector!r}")
        if stage in _FUNCS or stage == "abs":
            node = _apply_func(node, stage)
        elif stage.startswith((".", "[")):
            node = _apply_path(node, stage)
        else:
            raise LedgerError(
                f"stage {stage!r} in selector {selector!r} is neither a path nor a known function"
            )
    if isinstance(node, bool) or not isinstance(node, (int, float)):
        raise LedgerError(
            f"selector {selector!r} produced {_type_name(node)}, expected a scalar number"
        )
    return node


def validate_selector(selector: str) -> None:
    """Syntax-only validation at ledger-load time (no data needed)."""
    for raw_stage in _split_stages(selector):
        stage = raw_stage.strip()
        if not stage:
            raise LedgerError(f"empty pipeline stage in selector {selector!r}")
        if stage in _FUNCS or stage == "abs":
            continue
        if not stage.startswith((".", "[")):
            raise LedgerError(
                f"stage {stage!r} in selector {selector!r} is neither a path nor a known function"
            )
        pos = 0
        while pos < len(stage):
            m = _STEP_RE.match(stage, pos)
            if m is None:
                raise LedgerError(f"bad selector syntax at {stage[pos:]!r} in {stage!r}")
            index = m.group("index")
            if index is not None and len(index) > 9:
                raise LedgerError(f"index [{index}] is impossibly large in {stage!r}")
            pos = m.end()
