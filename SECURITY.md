# Security

## Reporting

Report a vulnerability through
[GitHub's private advisory form](https://github.com/YYYJH1/texclaims/security/advisories/new).
Please do not open a public issue for one. Expect a first reply within a week.

## What `texclaims` does with input

It reads three kinds of file, all of them yours: a YAML ledger, the manuscript
files the ledger lists, and the experiment artifacts it points at (JSON or
CSV). `init` creates a `claims.yaml` skeleton in the current directory and
refuses to overwrite an existing one. `generate` writes the macro file through
a temporary file in the same directory, then renames it into place;
`generate --check` writes nothing.

Two properties are load-bearing:

- **The ledger is parsed with a `SafeLoader` subclass.** No arbitrary Python
  object construction, and duplicate keys are an error rather than a silent
  overwrite. See [`src/texclaims/ledger.py`](src/texclaims/ledger.py).
- **The selector grammar cannot compute.** It addresses a field that already
  exists in an artifact; it evaluates no expressions and runs no code. A gate
  that evaluated expressions could be wrong in a second, independent way.

`texclaims` makes no network requests and loads no plugins.

## What counts as a vulnerability

The usual ones — code execution from a ledger or an artifact, a path that
escapes the project directory, a crash reachable from well-formed input.

And one that is specific to this tool: **a fail-open verdict is a security
bug here, not merely an incorrect result.** If a manuscript number disagrees
with its artifact and `texclaims` reports `PASS`, or an unclaimed number in a
declared region survives `scan --strict`, report it as a vulnerability. It is
used as a gate, and a gate that passes what it should stop has failed in the
only way that matters.

## Supported versions

The [latest release](https://github.com/YYYJH1/texclaims/releases/latest). This
is a young project with no long-term support branches; fixes go into a new one.
