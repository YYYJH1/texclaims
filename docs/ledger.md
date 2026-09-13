# Ledger reference

Every field the ledger accepts, and how anchoring and selectors work. The
[README](../README.md) covers what the tool is for and how to adopt it.

## Anchoring

```yaml
anchor: { template: 'improves throughput by {num}\%' }            # start here
anchor: { pattern: latency_row }                                  # tables
anchor: { near: { context: 'Mean utility of', occurrence: 1 } }  # no regex at all
```

A `near` context is searched *forwards*: the anchored number is the N-th one
from the start of the context to the end of that paragraph, so put the context
before the number, not after it.

In a `template`, whitespace matches any whitespace run (line-wrapping cannot
break it) and `{num}` handles signs, Unicode minus, thousands separators
(`50,000`, `50{,}000`, `50\,000`),
scientific notation, leading-dot decimals like `.05`, and `\%`.

For a table row where one regex serves several cells, name it and map the
capture groups:

```yaml
patterns:
  latency_row: '\$([\d.]+) \\pm ([\d.]+)\$\\,ms to \$([\d.]+) \\pm ([\d.]+)\$'

claims:
  - name: latency-row
    file: paper.tex
    anchor: { pattern: latency_row }
    expect: 1
    groups:
      1: 'summary:.baseline.mean_ms'
      2: 'summary:.baseline.std_ms'
      3: 'summary:.fastcache.mean_ms'
      4: 'summary:.fastcache.std_ms'
```

A claim's `groups` bind the same artifact fields at every occurrence of its
anchor. `expect: 2` means the same numbers are printed twice and must agree;
it is not a row index. A multi-row table therefore needs one claim per row,
each anchored on that row's label and mapped to that row's artifact fields.
Named patterns reuse regex syntax, not a sequence of row bindings.

A capture group must take the whole number at that position. A group matching
`88` out of `88.9`, or one leaving the minus sign outside, is a configuration
error: it would audit a number the manuscript never printed.

> [!TIP]
> Never anchor on a nearby number (`'18.44 & {num}'`). It reads as convenient
> and breaks the moment you rerun the experiment, taking every claim in the
> table with it. Anchor on words.


## Artifacts and selectors

JSON and CSV are both first-class. A CSV becomes a list of row objects with
numeric cells coerced, so aggregation happens in the selector rather than in a
bespoke preprocessing script:

```yaml
value: 'runs:[] | .hit_rate | mean'      # mean over every row of runs.csv
value: 'summary:.methods["ca-mappo"].utility'
value: 'summary:.per_seed[0].reward'
```

A jq subset: `.key`, `["any key"]`, `[0]`, `[]`, and the functions `mean`,
`median`, `max`, `min`, `sum`, `len`, `abs`, `first`, `last`. Anything more
elaborate belongs in the script that writes the artifact — an auditor that
computes its own statistics is a second implementation to keep in sync.
`transform` applies `scale → negate → absolute → offset`.

## Full schema (version 1)

```yaml
version: 1                     # required

documents:                     # required; .tex and .md are supported
  - paper.tex

sources:                       # required; named artifacts (.json or .csv)
  summary: results/summary.json
  runs: results/runs.csv

defaults:                      # optional; merged into every claim
  file: paper.tex

patterns:                      # optional; named regexes for reuse
  latency_row: '...'

claims:                        # required
  - name: unique-id            # required; shares a namespace with exemptions
    file: paper.tex            # required; must appear in documents
    anchor: {...}              # required; template | pattern | near
    expect: 1                  # required; exact occurrence count
    value: 'source:selector'   # exactly one of value / groups
    groups: {1: 'source:selector'}
    transform: {scale: 100, negate: false, absolute: false, offset: 0}
    abs_tol: 0.01              # optional; overrides display tolerance
    rel_tol: 0.001             # optional; either one satisfying passes
    optional: false            # optional; see below

exemptions:                    # optional
  - name: unique-id
    file: paper.tex
    anchor: {...}
    expect: 1
    reason: "at least eight characters explaining why"

scan:                          # optional; required by --strict
  regions:
    - file: paper.tex
      start: '\section{Evaluation}'   # literal anchors, must match exactly once
      end: '\section{Conclusion}'

emit:                          # optional
  output: numbers.tex
  macros:
    - {name: MacroName, value: 'source:selector', format: '.1f', scale: 1}

pinning:                       # optional; artifact immutability
  sha256:
    results/summary.json: "<64 hex chars>"
```

All paths resolve against the ledger's own directory and may not leave it.

An emitted macro without `format` uses `%g` formatting (six significant figures),
which can round the value and switch to scientific notation.

An exemption waives **every** number inside its anchor match, not only the
`{num}` capture — so keep exemption anchors tight, and use a `near` anchor when
you mean to waive exactly one number in a crowded sentence.

For a completed audit, the text summary and JSON `summary.WAIVED` count waived number
occurrences; JSON `waived` breaks the count down by exemption name. These are
counters, not per-number records, and do not change the exit code.

JSON `summary.verdict` is `OK` (exit 0) or `FAIL` (exit 1) for a completed
audit. With `--json`, ledger or artifact errors produce `CONFIG_ERROR` (exit 2),
empty `records` and `warnings`, and `error.message`; no audit counts are
reported. The text error is also written to stderr.

`optional: true` is the one documented exception to fail-closed: a claim that
matches zero times is skipped instead of reported as `MISS`. It exists for
prose that legitimately comes and goes between drafts. Reach for it rarely —
it is the one setting that can hide a number from the audit.
