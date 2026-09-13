"""Command-line interface.

Exit codes: 0 clean, 1 reconciliation failure, 2 configuration error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

import yaml
from pathlib import Path

from . import __version__
from .audit import run_check
from .coverage import run_scan
from .emit import check_emitted, render_numbers
from .errors import LedgerError
from .ledger import load_ledger, resolve_output
from .report import Report

_SKELETON = """\
# texclaims ledger — see https://github.com/YYYJH1/texclaims
version: 1

documents:
  - {doc}

sources:
  summary: results/summary.json

claims: []
# Replace [] with claims as you work through the scan's UNMAPPED list:
#   - name: example-claim
#     file: {doc}
#     anchor: {{ template: 'improves throughput by {{num}}\\%' }}
#     expect: 1
#     value: 'summary:.improvement_pct'

# exemptions:
#   - name: confidence-level
#     file: {doc}
#     anchor: {{ template: 'the {{num}}\\% confidence level' }}
#     expect: 1
#     reason: "Protocol constant, not an experimental result."

scan:
  regions:
    - file: {doc}
"""


def _silence_stdout() -> None:
    # Avoid another broken pipe during interpreter shutdown, which can replace
    # the audit's exit code. Close the spare descriptor after redirecting stdout.
    fd = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(fd, sys.stdout.fileno())
    finally:
        os.close(fd)


def _emit_report(report: Report, as_json: bool = False) -> int:
    code = report.exit_code()
    try:
        report.emit_json() if as_json else report.emit_text()
    except BrokenPipeError:
        # The audit already ran. A consumer such as head must not turn its
        # failing verdict into success merely by closing the output early.
        _silence_stdout()
    return code


def _cmd_check(args: argparse.Namespace) -> int:
    state = run_check(load_ledger(args.ledger))
    return _emit_report(state.report, args.json)


def _cmd_scan(args: argparse.Namespace) -> int:
    ledger = load_ledger(args.ledger)
    if args.strict and not ledger.claims:
        raise LedgerError(
            "--strict but the ledger claims nothing; run 'scan' without "
            "--strict first and work through what it reports")
    if args.strict and not ledger.scan_regions:
        # An empty gate that reports success is worse than no gate.
        raise LedgerError("--strict needs at least one region under 'scan:'")
    if args.strict and ledger.missing_sections:
        # Passing over a section file that is right there would make --strict a
        # gate with a hole in it.
        raise LedgerError(
            f"--strict but the manuscript pulls in {ledger.missing_sections[0]!r}, "
            "which exists in this project and is not in 'documents'; nothing in "
            "it is audited")
    if args.strict:
        unscanned = [d for d in ledger.documents
                     if d not in {r.file for r in ledger.scan_regions}]
        if unscanned:
            raise LedgerError(
                f"--strict but {unscanned[0]!r} has no scan region; either give "
                "every document a region or drop it from 'documents'")
    report = Report(unmapped_is_failure=args.strict)
    state = run_scan(ledger, report)
    return _emit_report(state.report, args.json)


def _cmd_generate(args: argparse.Namespace) -> int:
    ledger = load_ledger(args.ledger)
    state = run_check(ledger)
    if state.report.failed:
        _emit_report(state.report)
        print("generate refused: fix the failing claims first", file=sys.stderr)
        return 1
    # Every path in play resolves against the ledger's directory, including a
    # CLI override: the ledger is the project root, not the shell's cwd. The
    # override gets the same containment and overwrite checks as the ledger's
    # own target — writing macros over the manuscript is unrecoverable.
    target = str(args.out) if args.out is not None else (
        ledger.emit.output if ledger.emit else "numbers.tex")
    output = resolve_output(ledger, target)
    if args.check:
        diff = check_emitted(ledger, state, output)
        if diff:
            try:
                print("\n".join(diff))
            except BrokenPipeError:
                _silence_stdout()
            print(f"emitted file {output} is stale; re-run generate", file=sys.stderr)
            return 1
        print(f"{output} is in sync", file=sys.stderr)
        return 0
    rendered = render_numbers(ledger, state)
    if output.is_dir():
        raise LedgerError(f"emit output {output} is a directory")
    if not output.parent.is_dir():
        raise LedgerError(f"emit output directory does not exist: {output.parent}")
    # Write via a temporary file in the same directory and rename: a failure
    # part-way through must not leave a truncated macro file behind, which
    # would then be \input by the next LaTeX build.
    try:
        with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=output.parent,
                prefix=f".{output.name}.", suffix=".tmp", delete=False) as fh:
            tmp = Path(fh.name)
            fh.write(rendered)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, output)
    except OSError as exc:
        raise LedgerError(f"cannot write {output}: {exc}") from exc
    n = len(ledger.emit.macros) if ledger.emit else 0
    print(f"wrote {output}: {n} macro(s)", file=sys.stderr)
    return 0


def _cmd_init(args: argparse.Namespace) -> int:
    target = Path("claims.yaml")
    if target.exists():
        print("claims.yaml already exists; refusing to overwrite", file=sys.stderr)
        return 2
    doc = yaml.safe_dump(args.doc, default_flow_style=True).strip().rstrip("\n")
    if doc.endswith("..."):
        doc = doc[:-3].strip()
    try:
        target.write_text(_SKELETON.format(doc=doc), encoding="utf-8")
    except OSError as exc:
        raise LedgerError(f"cannot write claims.yaml: {exc}") from exc
    print("wrote claims.yaml — edit the sources and claims to match your paper",
          file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="texclaims",
        description="Deterministic audit of manuscript numbers against experiment artifacts.",
    )
    parser.add_argument("--version", action="version", version=f"texclaims {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="reconcile every claim against its artifact")
    p_scan = sub.add_parser("scan", help="check + coverage scan of declared regions")
    for p in (p_check, p_scan):
        p.add_argument("--ledger", type=Path, default=Path("claims.yaml"))
        p.add_argument("--json", action="store_true", help="machine-readable output")
    p_scan.add_argument("--strict", action="store_true",
                        help="uncovered numbers fail the run (CI gate)")
    p_check.set_defaults(fn=_cmd_check)
    p_scan.set_defaults(fn=_cmd_scan)

    p_gen = sub.add_parser("generate", help="emit numbers.tex macros from the ledger")
    p_gen.add_argument("--ledger", type=Path, default=Path("claims.yaml"))
    p_gen.add_argument("--out", type=Path, default=None)
    p_gen.add_argument("--check", action="store_true",
                       help="verify the emitted file is in sync instead of writing")
    p_gen.set_defaults(fn=_cmd_generate)

    p_init = sub.add_parser("init", help="write a commented ledger skeleton")
    p_init.add_argument("--doc", default="main.tex")
    p_init.set_defaults(fn=_cmd_init)

    args = parser.parse_args(argv)
    try:
        code = args.fn(args)
        # Flush explicitly: a closed downstream pipe must surface here, where
        # it is a normal end of output, rather than during interpreter
        # shutdown where it would corrupt the exit status.
        try:
            sys.stdout.flush()
        except BrokenPipeError:
            _silence_stdout()
        return code
    except BrokenPipeError:
        # No verdict was returned. Treat an unexpected output failure as an
        # environment error; it cannot establish that the manuscript is clean.
        _silence_stdout()
        return 2
    except LedgerError as exc:
        print(f"CONFIG ERROR: {exc}", file=sys.stderr)
        if getattr(args, "json", False):
            # A bad ledger must still give JSON consumers a verdict. There is
            # no completed audit to summarize, so do not invent record counts.
            try:
                json.dump({"records": [], "warnings": [],
                           "summary": {"verdict": "CONFIG_ERROR"},
                           "error": {"message": str(exc)}}, sys.stdout,
                          indent=2, sort_keys=True)
                print()
                sys.stdout.flush()
            except BrokenPipeError:
                # Closing the error output early cannot clear exit 2.
                _silence_stdout()
        return 2
    except Exception as exc:  # noqa: BLE001 - a traceback would collide with
        # exit 1, which means "a number is wrong". Anything unexpected is
        # reported as a configuration error rather than mistaken for a verdict.
        print(f"INTERNAL ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("Please report this at https://github.com/YYYJH1/texclaims/issues",
              file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
