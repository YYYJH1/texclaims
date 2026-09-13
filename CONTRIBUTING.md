# Contributing

`texclaims` is a gate. The bar for a change is not "does it work" but "what
does it now refuse to let through, and what test says so".

## Setup

```console
$ pip install -e ".[dev]"
$ pytest                 # the whole suite
```

Python 3.10+ and PyYAML. Nothing else is needed to develop it, and nothing
else may become a runtime dependency without a reason in the pull request.

## The tests are the argument

Most of the suite is adversarial. Each test in [`tests/test_failclosed.py`](tests/test_failclosed.py)
describes a way an earlier version reported success while a number was wrong,
missing, or unaccounted for. A change to gate behaviour belongs there, written
as the failure it prevents rather than as the feature it adds.

Three things are enforced by tests and will fail CI if you edit them by hand:

- **Console output quoted in either README.** [`tests/test_readme.py`](tests/test_readme.py)
  re-runs the clean demo and the documented edits, comparing all quoted record
  statuses and summaries in both languages. The JSON summary is parsed with
  Python's `json` module; the tests do not require `jq`. Change the tool, then
  paste what it actually prints — a tool arguing against hand-copied numbers
  may not hand-copy its own.
- **The test count in the README.** Same file, same reason.
- **The version.** It is stated once, in [`src/texclaims/__init__.py`](src/texclaims/__init__.py).
  `pyproject.toml` derives it and `CITATION.cff` must agree; a test checks that.

## What is out of scope

The [Limitations](README.md#limitations) section is a list of deliberate
refusals, not a backlog. In particular the selector grammar cannot compute: a
derived figure has to be a field your analysis script writes, because a gate
that evaluates expressions is a gate that can be wrong in a second, independent
way. Proposals to add arithmetic will be declined on those grounds.

## Pull requests

CI must be green on all of it: the matrix (3.10 through 3.14), the self-audit
that runs `texclaims` against its own example, and the packaging job that
installs the sdist and runs the suite out of it.

Write the commit subject as what changed, and say what it stops. Existing
history is the model:

```
Close the gate's last hole, and stop the README quoting a stale number
```

## Reporting instead

A ledger that produces the wrong verdict is a bug report, not a pull request,
and the [bug template](.github/ISSUE_TEMPLATE/bug_report.yml) asks for the
three things needed to reproduce it: version, the relevant ledger entry, and
the full output with its exit code.
