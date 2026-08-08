"""Ledger loading and strict (closed-schema) validation.

Every mapping in the ledger has an explicit set of allowed keys; an unknown
key is a configuration error, never silently ignored.  All relative paths
resolve against the directory containing the ledger file.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .artifact import validate_selector
from .document import mask_comments
from .errors import LedgerError

SCHEMA_VERSION = 1

_MACRO_NAME_RE = re.compile(r"^[A-Za-z]+$")
_IDENT_RE = re.compile(r"^[A-Za-z_][\w\-]*$")


class _StrictLoader(yaml.SafeLoader):
    """A loader that refuses duplicate mapping keys.

    PyYAML's default is last-one-wins, which would let a second ``claims:``
    block delete every claim in the first one and still report a clean run.
    """


def _no_duplicate_keys(loader: _StrictLoader, node: yaml.MappingNode) -> dict:
    mapping: dict = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in mapping:
            raise LedgerError(
                f"duplicate key {key!r} at line {key_node.start_mark.line + 1}", "ledger")
        mapping[key] = loader.construct_object(value_node, deep=True)
    return mapping


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicate_keys)


_INPUT_RE = re.compile(
    r"(?<!\\)\\(?:input|include)(?![a-zA-Z])\s*(?:\{([^{}\n]+)\}|([^\s{}\\]+))")


def _included_files(path: Path) -> set[str]:
    """Names a manuscript pulls in with \\input or \\include.

    Read from the comment-masked text: a commented-out ``% \\input{old}`` and
    an ``\\input`` quoted inside a verbatim block are both ordinary, and
    rejecting a ledger over either would just make the tool unusable.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return set()
    return {(m.group(1) or m.group(2)).strip()
            for m in _INPUT_RE.finditer(mask_comments(text))}


def _resolve_inside(root: Path, rel: str, path: str) -> Path:
    """Resolve a ledger-relative path, refusing to leave the ledger's tree.

    The ledger is the project root; a claim that reads from outside it (or an
    emit target that writes outside it) is a mistake worth catching rather
    than a feature.
    """
    if Path(rel).is_absolute():
        raise LedgerError(f"path must be relative to the ledger: {rel}", path)
    target = (root / rel).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        raise LedgerError(f"path escapes the ledger directory: {rel}", path) from None
    return target


def resolve_output(ledger: "Ledger", target: str) -> Path:
    """Resolve a generate target, refusing to leave the tree or clobber a document.

    Unlike ledger fields, a CLI target may be absolute — it just has to land
    inside the ledger's directory.
    """
    root = ledger.root.resolve()
    resolved = (root / target).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise LedgerError(
            f"emit output escapes the ledger directory: {target}", "emit output") from None
    # Nothing the audit depends on may be the thing the audit overwrites.
    protected: list[tuple[Path, str]] = [
        *((ledger.root / d, f"the manuscript {d!r}") for d in ledger.documents),
        *((p, f"the artifact {n!r}") for n, p in ledger.sources.items()),
        (ledger.path, "the ledger itself"),
    ]
    for path_obj, what in protected:
        if resolved == path_obj.resolve():
            raise LedgerError(
                f"emit output {target!r} resolves to {what}; generating would "
                "overwrite it", "emit output")
    return resolved


@dataclass(frozen=True)
class ValueRef:
    source: str
    selector: str
    raw: str

    @staticmethod
    def parse(raw: Any, sources: dict[str, Path], path: str) -> "ValueRef":
        if not isinstance(raw, str) or ":" not in raw:
            raise LedgerError(
                f"value reference must be a 'source:selector' string, got {raw!r}", path
            )
        source, selector = raw.split(":", 1)
        source, selector = source.strip(), selector.strip()
        if source not in sources:
            known = ", ".join(sorted(sources))
            raise LedgerError(f"unknown source {source!r} (registered: {known})", path)
        validate_selector(selector)
        return ValueRef(source=source, selector=selector, raw=raw)


@dataclass(frozen=True)
class Anchor:
    kind: str  # "template" | "pattern" | "near"
    template: str | None = None
    pattern: str | None = None  # resolved regex text (named patterns inlined)
    context: str | None = None
    occurrence: int = 1


@dataclass(frozen=True)
class Transform:
    scale: float = 1.0
    negate: bool = False
    absolute: bool = False
    offset: float = 0.0

    def apply(self, value: int | float) -> int | float:
        if (self.scale == 1 and not self.negate and not self.absolute
                and self.offset == 0):
            return value  # identity: keep an int an int
        if isinstance(value, int) and float(self.scale).is_integer() \
                and float(self.offset).is_integer():
            # Stay in exact integer arithmetic where the transform allows it.
            out = value * int(self.scale)
            if self.negate:
                out = -out
            if self.absolute:
                out = abs(out)
            return out + int(self.offset)
        value = value * self.scale
        if self.negate:
            value = -value
        if self.absolute:
            value = abs(value)
        return value + self.offset


@dataclass(frozen=True)
class Claim:
    name: str
    file: str
    anchor: Anchor
    expect: int
    value: ValueRef | None
    groups: dict[int, ValueRef]
    transform: Transform
    abs_tol: float | None
    rel_tol: float | None
    optional: bool


@dataclass(frozen=True)
class Exemption:
    name: str
    file: str
    anchor: Anchor
    expect: int
    reason: str


@dataclass(frozen=True)
class ScanRegion:
    file: str
    start: str | None
    end: str | None


@dataclass(frozen=True)
class EmitMacro:
    name: str
    value: ValueRef
    format: str
    scale: float


@dataclass(frozen=True)
class Emit:
    output: str
    macros: tuple[EmitMacro, ...]


@dataclass
class Ledger:
    root: Path
    path: Path
    documents: list[str]
    sources: dict[str, Path]
    patterns: dict[str, str]
    claims: list[Claim]
    exemptions: list[Exemption]
    scan_regions: list[ScanRegion]
    emit: Emit | None
    sha256_pins: dict[str, str] = field(default_factory=dict)
    used_patterns: set[str] = field(default_factory=set)
    unlisted_includes: list[str] = field(default_factory=list)
    missing_sections: list[str] = field(default_factory=list)


# --- validation helpers -----------------------------------------------------

def _need_mapping(node: Any, path: str) -> dict:
    if not isinstance(node, dict):
        raise LedgerError(f"expected a mapping, got {type(node).__name__}", path)
    return node


def _check_keys(node: dict, allowed: set[str], required: set[str], path: str) -> None:
    unknown = set(node) - allowed
    if unknown:
        raise LedgerError(
            f"unknown field(s) {sorted(map(str, unknown))} (allowed: {sorted(allowed)})", path
        )
    missing = required - set(node)
    if missing:
        raise LedgerError(f"missing required field(s) {sorted(missing)}", path)


def _need_str(node: dict, key: str, path: str) -> str:
    val = node.get(key)
    if not isinstance(val, str) or not val.strip():
        raise LedgerError(f"field {key!r} must be a non-empty string", path)
    return val


def _opt_number(node: dict, key: str, path: str) -> float | None:
    if key not in node:
        return None
    val = node[key]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise LedgerError(f"field {key!r} must be a number", path)
    if not math.isfinite(float(val)):
        raise LedgerError(f"field {key!r} must be a finite number, got {val}", path)
    return float(val)


def _need_expect(node: dict, path: str) -> int:
    val = node.get("expect")
    if isinstance(val, bool) or not isinstance(val, int) or val < 1:
        raise LedgerError("field 'expect' must be an integer >= 1", path)
    return val


def _parse_anchor(node: Any, patterns: dict[str, str], path: str, used: set[str]) -> Anchor:
    mapping = _need_mapping(node, path)
    kinds = [k for k in ("template", "pattern", "near") if k in mapping]
    if len(kinds) != 1:
        raise LedgerError("anchor needs exactly one of: template, pattern, near", path)
    kind = kinds[0]
    if kind == "template":
        _check_keys(mapping, {"template"}, {"template"}, path)
        template = _need_str(mapping, "template", path)
        if "{num}" not in template:
            raise LedgerError("template must contain at least one {num} placeholder", path)
        return Anchor(kind="template", template=template)
    if kind == "pattern":
        _check_keys(mapping, {"pattern"}, {"pattern"}, path)
        text = _need_str(mapping, "pattern", path)
        if _IDENT_RE.match(text):
            if text not in patterns:
                known = ", ".join(sorted(patterns)) or "none defined"
                raise LedgerError(f"unknown named pattern {text!r} (defined: {known})", path)
            used.add(text)
            text = patterns[text]
        return Anchor(kind="pattern", pattern=text)
    _check_keys(mapping, {"near"}, {"near"}, path)
    near = _need_mapping(mapping["near"], f"{path}.near")
    _check_keys(near, {"context", "occurrence"}, {"context"}, f"{path}.near")
    occurrence = near.get("occurrence", 1)
    if isinstance(occurrence, bool) or not isinstance(occurrence, int) or occurrence < 1:
        raise LedgerError("field 'occurrence' must be an integer >= 1", f"{path}.near")
    return Anchor(kind="near", context=_need_str(near, "context", f"{path}.near"),
                  occurrence=occurrence)


def _parse_transform(node: Any, path: str) -> Transform:
    if node is None:
        return Transform()
    mapping = _need_mapping(node, path)
    _check_keys(mapping, {"scale", "negate", "absolute", "offset"}, set(), path)
    scale = _opt_number(mapping, "scale", path)
    offset = _opt_number(mapping, "offset", path)
    for flag in ("negate", "absolute"):
        if flag in mapping and not isinstance(mapping[flag], bool):
            raise LedgerError(f"field {flag!r} must be a boolean", path)
    return Transform(
        scale=1.0 if scale is None else scale,
        negate=bool(mapping.get("negate", False)),
        absolute=bool(mapping.get("absolute", False)),
        offset=0.0 if offset is None else offset,
    )


_TOP_KEYS = {"version", "documents", "sources", "defaults", "patterns",
             "claims", "exemptions", "scan", "emit", "pinning"}
_CLAIM_KEYS = {"name", "file", "anchor", "expect", "value", "groups",
               "transform", "abs_tol", "rel_tol", "optional"}
_EXEMPTION_KEYS = {"name", "file", "anchor", "expect", "reason"}


def load_ledger(ledger_path: Path) -> Ledger:
    try:
        raw_text = ledger_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise LedgerError(f"cannot read ledger: {exc}") from exc
    try:
        data = yaml.load(raw_text, Loader=_StrictLoader)
    except yaml.YAMLError as exc:
        raise LedgerError(f"ledger is not valid YAML: {exc}") from exc
    except RecursionError as exc:
        raise LedgerError("ledger nests too deeply to parse") from exc
    root = ledger_path.resolve().parent
    top = _need_mapping(data, "ledger")
    _check_keys(top, _TOP_KEYS, {"version", "documents", "sources", "claims"}, "ledger")

    version = top["version"]
    if isinstance(version, bool) or not isinstance(version, int):
        raise LedgerError("field 'version' must be an integer", "ledger")
    if version > SCHEMA_VERSION:
        raise LedgerError(
            f"ledger schema version {version} is newer than this texclaims "
            f"(supports up to {SCHEMA_VERSION}); please upgrade", "ledger")
    if version < 1:
        raise LedgerError("field 'version' must be >= 1", "ledger")

    documents = top["documents"]
    if not isinstance(documents, list) or not documents or \
            not all(isinstance(d, str) and d.strip() for d in documents):
        raise LedgerError("'documents' must be a non-empty list of file paths", "ledger")
    seen_docs: dict[Path, str] = {}
    included: set[str] = set()
    for doc in documents:
        resolved = _resolve_inside(root, doc, "ledger.documents")
        if not resolved.is_file():
            raise LedgerError(f"document not found: {doc}", "ledger.documents")
        if resolved in seen_docs:  # two spellings of one file would split state
            raise LedgerError(
                f"documents {seen_docs[resolved]!r} and {doc!r} are the same file",
                "ledger.documents")
        seen_docs[resolved] = doc
        included.update(_included_files(resolved))

    # \input/\include are not followed, so a file the manuscript pulls in but
    # the ledger never lists is audited by nobody.  This is a warning, not an
    # error: the name may be a package, a macro, a file outside the project, or
    # the emitted macro file itself, and refusing to run over any of those
    # would cost far more than the partial coverage it is meant to flag.
    listed = set(documents) | {d.rsplit(".tex", 1)[0] for d in documents}
    emit_name = ""
    if isinstance(top.get("emit"), dict):
        raw_out = top["emit"].get("output")
        if isinstance(raw_out, str):  # the file texclaims writes is its own
            emit_name = raw_out.rsplit(".tex", 1)[0]
            listed |= {raw_out, emit_name}
    listed |= {d.lstrip("./") for d in listed} | {f"./{d}" for d in listed}
    unlisted = sorted(n for n in included if n not in listed and n.lstrip("./") not in listed)
    # A name that resolves to a real .tex inside the project is a section you
    # forgot; anything else is a package, a macro-built path, or a file that is
    # simply not here, and refusing to run over those helps nobody.
    missing_sections = []
    for name in unlisted:
        for candidate in (name, f"{name}.tex"):
            try:
                target = _resolve_inside(root, candidate, "ledger.documents")
            except LedgerError:
                continue
            if target.is_file():
                missing_sections.append(name)
                break

    sources_node = _need_mapping(top["sources"], "ledger.sources")
    if not sources_node:
        raise LedgerError("'sources' must be a non-empty mapping", "ledger")
    sources: dict[str, Path] = {}
    for name, rel in sources_node.items():
        path = f"ledger.sources.{name}"
        if not isinstance(name, str) or not _IDENT_RE.match(name):
            raise LedgerError(f"source name {name!r} must be an identifier", "ledger.sources")
        if not isinstance(rel, str) or not rel.strip():
            raise LedgerError("source path must be a non-empty string", path)
        target = _resolve_inside(root, rel, path)
        if not target.is_file():
            raise LedgerError(f"artifact not found: {rel}", path)
        sources[name] = target

    # `or {}` would swallow a mis-typed block (a list, say) instead of
    # rejecting it, which is exactly the silent failure a closed schema exists
    # to prevent; only an absent key defaults.
    patterns_node = {} if top.get("patterns") is None else top["patterns"]
    patterns: dict[str, str] = {}
    for name, regex in _need_mapping(patterns_node, "ledger.patterns").items():
        path = f"ledger.patterns.{name}"
        if not isinstance(name, str) or not _IDENT_RE.match(name):
            raise LedgerError(f"pattern name {name!r} must be an identifier", "ledger.patterns")
        if not isinstance(regex, str) or not regex.strip():
            raise LedgerError("pattern must be a non-empty regex string", path)
        try:
            compiled = re.compile(regex, re.MULTILINE)
        except re.error as exc:
            raise LedgerError(f"invalid regex: {exc}", path) from exc
        if compiled.groups < 1:
            raise LedgerError("pattern must contain at least one capture group", path)
        patterns[name] = regex

    defaults = {} if top.get("defaults") is None else top["defaults"]
    _check_keys(_need_mapping(defaults, "ledger.defaults"),
                _CLAIM_KEYS - {"name"}, set(), "ledger.defaults")

    used_patterns: set[str] = set()
    names_seen: set[str] = set()

    def _register_name(name: str, path: str) -> None:
        if name in names_seen:
            raise LedgerError(f"duplicate name {name!r}", path)
        names_seen.add(name)

    claims_node = top["claims"]
    if not isinstance(claims_node, list):
        raise LedgerError("'claims' must be a list", "ledger")
    # An empty list is the ledger you start with: scan tells you what to put
    # in it.  --strict is where emptiness stops being acceptable.
    claims: list[Claim] = []
    for i, entry in enumerate(claims_node):
        path = f"ledger.claims[{i}]"
        merged = {**defaults, **_need_mapping(entry, path)}
        _check_keys(merged, _CLAIM_KEYS, {"name", "file", "anchor", "expect"}, path)
        name = _need_str(merged, "name", path)
        path = f"ledger.claims[{i}]({name})"
        _register_name(name, path)
        file = _need_str(merged, "file", path)
        if file not in documents:
            raise LedgerError(f"file {file!r} is not in 'documents'", path)
        has_value, has_groups = "value" in merged, "groups" in merged
        if has_value == has_groups:
            raise LedgerError("claim needs exactly one of: value, groups", path)
        value = None
        groups: dict[int, ValueRef] = {}
        if has_value:
            value = ValueRef.parse(merged["value"], sources, f"{path}.value")
        else:
            groups_node = _need_mapping(merged["groups"], f"{path}.groups")
            if not groups_node:
                raise LedgerError("'groups' must be a non-empty mapping", path)
            for key, ref in groups_node.items():
                if isinstance(key, bool) or not isinstance(key, int) or key < 1:
                    raise LedgerError(
                        f"group key {key!r} must be an integer >= 1", f"{path}.groups")
                groups[key] = ValueRef.parse(ref, sources, f"{path}.groups[{key}]")
        if "optional" in merged and not isinstance(merged["optional"], bool):
            raise LedgerError("field 'optional' must be a boolean", path)
        anchor = _parse_anchor(merged["anchor"], patterns, f"{path}.anchor", used_patterns)
        if anchor.kind == "near" and groups:
            raise LedgerError(
                "a 'near' anchor yields a single number, so it cannot be used with "
                "'groups'; use 'value' instead", path)
        claims.append(Claim(
            name=name, file=file, anchor=anchor,
            expect=_need_expect(merged, path),
            value=value, groups=groups,
            transform=_parse_transform(merged.get("transform"), f"{path}.transform"),
            abs_tol=_opt_number(merged, "abs_tol", path),
            rel_tol=_opt_number(merged, "rel_tol", path),
            optional=bool(merged.get("optional", False)),
        ))

    exemptions: list[Exemption] = []
    for i, entry in enumerate(_ensure_list(top.get("exemptions"), "ledger.exemptions")):
        path = f"ledger.exemptions[{i}]"
        node = _need_mapping(entry, path)
        _check_keys(node, _EXEMPTION_KEYS, _EXEMPTION_KEYS, path)
        name = _need_str(node, "name", path)
        path = f"ledger.exemptions[{i}]({name})"
        _register_name(name, path)
        file = _need_str(node, "file", path)
        if file not in documents:
            raise LedgerError(f"file {file!r} is not in 'documents'", path)
        reason = _need_str(node, "reason", path)
        if len(reason.strip()) < 8:
            raise LedgerError("'reason' must explain the exemption (>= 8 characters)", path)
        exemptions.append(Exemption(
            name=name, file=file,
            anchor=_parse_anchor(node["anchor"], patterns, f"{path}.anchor", used_patterns),
            expect=_need_expect(node, path),
            reason=reason.strip(),
        ))

    scan_regions: list[ScanRegion] = []
    if "scan" in top:
        scan_node = _need_mapping(top["scan"], "ledger.scan")
        _check_keys(scan_node, {"regions"}, {"regions"}, "ledger.scan")
        for i, entry in enumerate(_ensure_list(scan_node["regions"], "ledger.scan.regions")):
            path = f"ledger.scan.regions[{i}]"
            node = _need_mapping(entry, path)
            _check_keys(node, {"file", "start", "end"}, {"file"}, path)
            file = _need_str(node, "file", path)
            if file not in documents:
                raise LedgerError(f"file {file!r} is not in 'documents'", path)
            start = _need_str(node, "start", path) if "start" in node else None
            end = _need_str(node, "end", path) if "end" in node else None
            scan_regions.append(ScanRegion(file=file, start=start, end=end))

    emit: Emit | None = None
    if "emit" in top:
        emit_node = _need_mapping(top["emit"], "ledger.emit")
        _check_keys(emit_node, {"output", "macros"}, {"output", "macros"}, "ledger.emit")
        output = _need_str(emit_node, "output", "ledger.emit")
        emit_target = _resolve_inside(root, output, "ledger.emit.output")
        clashes = [f"the manuscript {d!r}" for d in documents
                   if emit_target == (root / d).resolve()]
        clashes += [f"the artifact {n!r}" for n, p in sources.items()
                    if emit_target == p.resolve()]
        if emit_target == ledger_path.resolve():
            clashes.append("the ledger itself")
        if clashes:
            raise LedgerError(
                f"emit output {output!r} resolves to {clashes[0]}; generating "
                "would overwrite it", "ledger.emit.output")
        macros: list[EmitMacro] = []
        macro_names: set[str] = set()
        for i, entry in enumerate(_ensure_list(emit_node["macros"], "ledger.emit.macros")):
            path = f"ledger.emit.macros[{i}]"
            node = _need_mapping(entry, path)
            _check_keys(node, {"name", "value", "format", "scale"}, {"name", "value"}, path)
            name = _need_str(node, "name", path)
            if not _MACRO_NAME_RE.match(name):
                raise LedgerError(
                    f"macro name {name!r} must be letters only (LaTeX command name)", path)
            if name in macro_names:
                raise LedgerError(f"duplicate macro name {name!r}", path)
            macro_names.add(name)
            fmt = node.get("format", "")
            if not isinstance(fmt, str):
                raise LedgerError("field 'format' must be a string", path)
            scale = _opt_number(node, "scale", path)
            macros.append(EmitMacro(
                name=name,
                value=ValueRef.parse(node["value"], sources, f"{path}.value"),
                format=fmt,
                scale=1.0 if scale is None else scale,
            ))
        emit = Emit(output=output, macros=tuple(macros))

    sha256_pins: dict[str, str] = {}
    if "pinning" in top:
        pin_node = _need_mapping(top["pinning"], "ledger.pinning")
        _check_keys(pin_node, {"sha256"}, {"sha256"}, "ledger.pinning")
        for rel, digest in _need_mapping(pin_node["sha256"], "ledger.pinning.sha256").items():
            path = f"ledger.pinning.sha256.{rel}"
            if not isinstance(rel, str) or not rel.strip():
                raise LedgerError(
                    f"pinned path {rel!r} must be a string (quote it in YAML)",
                    "ledger.pinning.sha256")
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise LedgerError("pin must be a 64-char lowercase hex sha256", path)
            if not _resolve_inside(root, rel, path).is_file():
                raise LedgerError(f"pinned artifact not found: {rel}", path)
            sha256_pins[rel] = digest

    return Ledger(
        root=root, path=ledger_path.resolve(), documents=list(documents),
        unlisted_includes=unlisted, missing_sections=missing_sections, sources=sources, patterns=patterns,
        claims=claims, exemptions=exemptions, scan_regions=scan_regions,
        emit=emit, sha256_pins=sha256_pins, used_patterns=used_patterns,
    )


def _ensure_list(node: Any, path: str) -> list:
    if node is None:
        return []
    if not isinstance(node, list):
        raise LedgerError(f"expected a list, got {type(node).__name__}", path)
    return node
