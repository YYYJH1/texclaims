# Changelog

Notable changes to `texclaims`. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[semantic versioning](https://semver.org/spec/v2.0.0.html) — where the public
interface is the ledger schema, the four verdicts, and the exit codes, not any
Python API.

## [Unreleased]

Verdicts change. Most of the fixes below close a way 0.1.0 could stay silent
about a number nobody accounted for, so a ledger that passed only through one
of them fails after the upgrade. One goes the other way: a `%` comment line no
longer breaks a paragraph, so `near` anchors stop failing on correct ledgers.

### Added

- A weekly scheduled CI run. A gate that only ran on push could not notice a
  new Python release breaking it.
- `CONTRIBUTING.md`, `SECURITY.md`, this changelog, a pull request template, a
  feature request template, and Dependabot for the CI actions.

### Changed

- CI now runs `actions/checkout@v7` and `actions/setup-python@v7`. The pinned
  v4 and v5 targeted Node 20, which GitHub had begun forcing onto Node 24 with
  a deprecation warning on every run.
- Every action the workflows use is pinned to a full commit SHA, with its
  version in a trailing comment. A tag is a movable ref, and `publish.yml`
  holds the project's only credential path to PyPI.
- The PyYAML floor is 6.0.3, the oldest release with a wheel for every Python
  the classifiers claim. `PyYAML>=6.0` admitted 6.0 and 6.0.1, which ship no
  wheel for 3.13 or 3.14 and whose source build fails against Cython 3.
- Both READMEs address images and files by absolute URL, so the project page
  rendered from `README.md` on PyPI is not a wall of broken links.
- The sdist carries `docs/`, `CHANGELOG.md`, `CONTRIBUTING.md`, `SECURITY.md`
  and both workflows; the README linked to a reference the tarball did not
  contain, and the shipped suite checks what the workflows declare.
- A release workflow that publishes to PyPI through Trusted Publishing, so no
  API token is stored in this repository.
- The summary counts waived occurrences, and `--json` breaks them down by
  exemption. One greedy anchor could waive three unrelated results behind
  `0 UNMAPPED -- OK`. Exit codes are unchanged.
- Selector errors name the claim, group or macro they came from.

### Fixed

- `abs_tol: 0` selected float subtraction, which cannot deliver exact equality
  above 2^53. An explicit tolerance now measures the same exact difference the
  default path does.
- A number written with `{,}` separators fell back to floats, so
  `9{,}007{,}199{,}254{,}740{,}992` passed against an artifact holding
  9007199254740993. A thin space split `50\,000` in two, so it could not be
  claimed at all. Both now go through the one normalisation the parser uses.
- A JSON `true` audited clean against a claimed 1.
- A quoted CSV cell spanning two lines was joined into one number, an unclosed
  quote was accepted, and fields past the header were dropped. Surplus fields
  now make the artifact malformed.
- `\iffalse ... \else ... \fi` was erased whole, live branch included.
  Conditionals are tracked with their nesting, and an unfamiliar `\if` inside
  a false branch is an error.
- A brace was taken as proof of a dimension, so `\textbf{9.9mm}` disappeared,
  and the "in" of "K=8 in every run" was read as inches. Only recognised
  length-taking commands may hide a measurement.
- `\subfile` and `\import` pulled a whole unaudited section in while
  `scan --strict` exited 0, where the identical `\input` exited 2. Both are
  followed now.
- A capture could take `1.2` out of `1.2.3`.
- A `%` comment line counted as a paragraph break, so `near` anchors failed on
  correct ledgers. Paragraphs come from the raw text, where TeX takes them.
- `texclaims check | head` exited 0 on a failing audit. The exit code is
  computed before anything is written.
- An integer past float range crashed the renderer, so two fail-closed
  verdicts ended in INTERNAL ERROR instead of being printed.
- `--json` printed nothing on the exit-2 path, where the pipeline the README
  recommends died with a parse error.
- `init` wrote a ledger that could not run: it hardcoded a source path and a
  claim anchored on the demo paper. It writes an empty claim list with the
  example commented out.
- The classifiers stopped at Python 3.13 while CI tested 3.14. A test keeps
  the two equal in both directions.
- The docs described behaviour the code does not have. Loading a ledger warns
  about an unlisted `\input` rather than refusing it, and `scan --strict` is
  what refuses; SECURITY.md offered a YAML artifact format that never existed;
  the skill install instruction named the file instead of the directory, so
  the skill never loaded; and a console block in the README had never been
  produced by anything.

## [0.1.0] — 2026-08-08

Initial release.

### Added

- `texclaims check` — every number the ledger claims is reconciled against the
  artifact field it is bound to, at display-precision tolerance.
- `texclaims scan --strict` — every number in a declared region must be claimed
  by the ledger or waived by an exemption that states a reason.
- `texclaims generate` — provenance-annotated LaTeX macros, so new prose need
  not transcribe a result by hand; `--check` gates them for staleness.
- `texclaims init` — a commented ledger skeleton for a manuscript.
- Ledger schema v1: three anchor kinds, a non-computing selector grammar, CSV
  as a first-class artifact, `expect` interlocking repeated numbers, and
  exemptions that require a written reason.
- Exit codes as the interface: 0 clean, 1 a number or the prose is wrong,
  2 the ledger is wrong.
- An agent skill in `skills/texclaims/`, and a Chinese introduction.

[Unreleased]: https://github.com/YYYJH1/texclaims/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/YYYJH1/texclaims/releases/tag/v0.1.0
