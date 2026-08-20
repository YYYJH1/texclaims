# Changelog

Notable changes to `texclaims`. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[semantic versioning](https://semver.org/spec/v2.0.0.html) — where the public
interface is the ledger schema, the four verdicts, and the exit codes, not any
Python API.

## [Unreleased]

No change to the checker: the verdict any ledger got from 0.1.0 it still gets.

### Added

- A weekly scheduled CI run. A gate that only ran on push could not notice a
  new Python release breaking it.
- `CONTRIBUTING.md`, `SECURITY.md`, this changelog, a pull request template, a
  feature request template, and Dependabot for the CI actions.

### Changed

- CI now runs `actions/checkout@v7` and `actions/setup-python@v7`. The pinned
  v4 and v5 targeted Node 20, which GitHub had begun forcing onto Node 24 with
  a deprecation warning on every run.
- Both READMEs address images and files by absolute URL, so the project page
  rendered from `README.md` on PyPI is not a wall of broken links.
- The sdist carries `docs/`, `CHANGELOG.md`, `CONTRIBUTING.md` and
  `SECURITY.md`; the README linked to a reference the tarball did not contain.
- A release workflow that publishes to PyPI through Trusted Publishing, so no
  API token is stored in this repository.

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
