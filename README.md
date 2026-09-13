<div align="center">

# texclaims

**Deterministic audit of the numbers in your LaTeX manuscript
against the experiment artifacts that produced them.**

[![CI](https://github.com/YYYJH1/texclaims/actions/workflows/ci.yml/badge.svg)](https://github.com/YYYJH1/texclaims/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](https://github.com/YYYJH1/texclaims/blob/main/LICENSE)

English · [简体中文](https://github.com/YYYJH1/texclaims/blob/main/README.zh-CN.md)

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/YYYJH1/texclaims/main/assets/hero-dark.png">
  <img alt="Each highlighted number in a manuscript is tethered to a field in an experiment artifact; one tether is broken and red." src="https://raw.githubusercontent.com/YYYJH1/texclaims/main/assets/hero.png">
</picture>

</div>

- **Reads the `.tex` you already have.** No rewriting, no new build system.
- **Deterministic.** No model in the loop; the same input always gives the same verdict.
- **Fails closed.** A number nobody accounted for is an error, not silence.
- **Made for CI.** Stable exit codes, machine-readable output, one runtime dependency.

**Contents** · [Quickstart](#quickstart) · [How it works](#how-it-works) ·
[Adopting it](#adopting-it-on-a-paper-you-already-wrote) · [The three commands](#the-three-commands) ·
[Tolerance](#tolerance) · [Fail-closed](#fail-closed-by-design) · [CI](#continuous-integration) ·
[Agents](#a-deterministic-gate-for-an-agent-written-manuscript) · [Comparison](#how-it-compares) · [Reference](https://github.com/YYYJH1/texclaims/blob/main/docs/ledger.md)

---

## Why

Someone reruns the experiment and updates Section V:

```diff
  \section{Evaluation}
- FastCache improves end-to-end throughput by 12.7\% over the tuned baseline.
+ FastCache improves end-to-end throughput by 13.7\% over the tuned baseline.
```

The abstract still says 12.7. Nothing else in a LaTeX toolchain will tell you:

```console
$ texclaims check
PASS     headline-improvement paper.tex:6 claimed=12.7 expected=12.73421 tol=0.05
FAIL     headline-improvement paper.tex:10 claimed=13.7 expected=12.73421 tol=0.05 :: |claimed - expected| = 0.96579 exceeds display-precision tolerance
== 8 PASS, 1 FAIL, 0 MISS, 0 UNMAPPED, 1 WAIVED — FAIL ==
$ echo $?
1
```

One claim, two places, one of them now wrong. It knows the number should be
`12.73421` because the ledger says where it comes from:

```yaml
sources:
  summary: results/summary.json                    # an experiment artifact

claims:
  - name: headline-improvement
    file: paper.tex
    anchor: { template: 'throughput by {num}\%' }  # the sentence in the manuscript
    expect: 2                                      # it appears twice; both must agree
    value: 'summary:.improvement.throughput_pct'   # -> 12.73421
```

Everything above is [`examples/demo`](https://github.com/YYYJH1/texclaims/tree/main/examples/demo). The alternatives all ask
for something you may not want to give:

| Existing answer | What it asks of you |
|---|---|
| Literate programming (knitr, Quarto, showyourwork) | Rewrite the paper in its format, adopt its build system |
| LLM auditors | Trust a probabilistic reviewer as a gate — [SciCoQA](https://github.com/YYYJH1/texclaims/blob/main/docs/prior-art.md#2-post-hoc-checking--read-the-paper-judge-the-numbers) puts the best evaluated models under half on real-world discrepancies in the neighbouring paper-vs-code task |
| Artifact evaluation (ACM/IEEE, CODECHECK) | Only that the code runs; guidelines tolerate numeric drift |

## Quickstart

```console
$ git clone https://github.com/YYYJH1/texclaims && cd texclaims
$ pip install -e .          # not on PyPI yet; CI should pin a tag, see below
$ cd examples/demo
$ texclaims check --ledger claims.yaml
PASS     headline-improvement paper.tex:6 claimed=12.7 expected=12.73421 tol=0.05
PASS     headline-improvement paper.tex:10 claimed=12.7 expected=12.73421 tol=0.05
PASS     latency-row#g1 paper.tex:11 claimed=4.87 expected=4.8659 tol=0.005
PASS     latency-row#g2 paper.tex:11 claimed=0.51 expected=0.5121 tol=0.005
PASS     latency-row#g3 paper.tex:11 claimed=3.21 expected=3.2114 tol=0.005
PASS     latency-row#g4 paper.tex:11 claimed=0.44 expected=0.4432 tol=0.005
PASS     hit-rate paper.tex:12 claimed=94.2 expected=94.218 tol=0.05
PASS     seed-count paper.tex:6 claimed=5 expected=5 tol=0.5
PASS     seed-count paper.tex:12 claimed=5 expected=5 tol=0.5
== 9 PASS, 0 FAIL, 0 MISS, 0 UNMAPPED, 1 WAIVED — OK ==
```

Python 3.10+, one runtime dependency (PyYAML). Start your own ledger with
`texclaims init --doc main.tex`.

## How it works

![Sources on the left feed a ledger of bindings in the middle, which drives three commands and their exit codes.](https://raw.githubusercontent.com/YYYJH1/texclaims/main/assets/flow-pipeline.png)

Your manuscript and your result files meet in one place: a YAML ledger that
binds each reported number to the exact artifact field it came from. Three
commands read that ledger, and each answers a different question.

| Command | What it establishes |
|---|---|
| `texclaims check` | Every number the ledger claims **agrees with its artifact**. |
| `texclaims scan --strict` | Every number in the declared regions **is claimed by the ledger**. |
| `texclaims generate` | New prose **never hand-copies a number** in the first place. |

`check` proves the mapped numbers are right. `scan` proves you did not forget
to map one. Either alone leaves a gap; together they close the loop.

Exit codes are the interface: **0** clean, **1** a number or the prose is
wrong, **2** the ledger is wrong. CI can tell those apart.

Records use `PASS`, `FAIL`, `MISS`, or `UNMAPPED` and go to stdout; warnings
and the summary go to stderr. The summary's `WAIVED` counter counts number
occurrences covered by exemptions. It adds no per-number records and does not
affect the exit code. For completed audits, JSON includes the same total under
`summary.WAIVED` and counts by exemption name under `waived`, so a broad waiver
is visible.

With `--json`, `summary.verdict` is `OK` for exit 0 and `FAIL` for exit 1.
Ledger or artifact errors return `CONFIG_ERROR` with exit 2, empty `records`
and `warnings`, and an `error.message` diagnostic; the human-readable error
still goes to stderr. That error object has no audit counts because no audit
completed.

## Adopting it on a paper you already wrote

![A document with unaccounted numbers, a magnifier over the worklist, entries being added, and a passing gate, with an arrow looping back.](https://raw.githubusercontent.com/YYYJH1/texclaims/main/assets/flow-loop.png)

You do not write the ledger up front. You let the scan tell you what is
missing, and work the list down in batches:

1. `texclaims init --doc main.tex`, then point `sources:` at your result files.
2. Run `texclaims scan` **without** `--strict`. Every number in the region
   comes back `UNMAPPED` — that list is the worklist.
3. Add claims a few at a time, re-running as you go.
4. When `scan --strict` exits 0, add it to CI.

A paper split across files needs each one listed, with its own region —
claims are file-local, and `texclaims` does not follow includes such as
`\input`, `\include`, `\subfile`, or `\import`:

```yaml
documents: [main.tex, sections/results.tex, sections/discussion.tex]
scan:
  regions:
    - { file: main.tex, start: '\section{Introduction}' }
    - { file: sections/results.tex }
```

`scan` warns about an included name missing from `documents:`. Under `--strict`,
an unlisted name resolving to a real `.tex` section inside the project is a
configuration error; an unresolved package name or macro-built path only warns.
`check` alone reports nothing about coverage, so run non-strict `scan` alongside
it while adopting the ledger.

> [!IMPORTANT]
> Two things worth knowing before you start. An evaluation section in a
> two-column paper typically hands you a few hundred `UNMAPPED` entries on the
> first run, most of which collapse into one claim per table row (each covering
> that row's cells) and one exemption for protocol constants. And a claim binds
> a number to a **field that already exists** in your artifact: a derived figure
> like "improves by 12.7%" has to be a field your analysis script writes, because the selector
> deliberately cannot compute — a gate that evaluates expressions is a gate
> that can be wrong in a second, independent way.

## A deterministic gate for an agent-written manuscript

```console
$ texclaims check --json | jq -c '.summary'
{"FAIL":0,"MISS":0,"PASS":9,"UNMAPPED":0,"WAIVED":1,"verdict":"OK"}
```

[`skills/texclaims/SKILL.md`](https://github.com/YYYJH1/texclaims/blob/main/skills/texclaims/SKILL.md) is a ready-made agent
skill — copy the `skills/texclaims/` directory into `.claude/skills/` and the
agent knows how to bootstrap a ledger, read the four record statuses and the
`WAIVED` counter, and re-anchor a claim after an edit.

The division of labour: the agent proposes ledger entries, `texclaims` rules on
them. Good at reading sentences, bad at being a gate — this keeps the judgement
deterministic and re-runnable.

## The three commands

### check

Each claim anchors a number and binds it to one artifact field. `expect` is
exact, not a minimum: a number quoted in both the abstract and a results table
is declared once with `expect: 2`, interlocking the copies.

### scan

![Most numbers on a page are tethered to a source; three are circled because nothing accounts for them.](https://raw.githubusercontent.com/YYYJH1/texclaims/main/assets/scan.png)

`check` only vouches for numbers you remembered to write down. The scan
inverts the question — in each declared region, every number must be claimed,
or waived by an exemption that states a reason:

```yaml
exemptions:
  - name: confidence-level
    file: paper.tex
    anchor: { template: 'the {num}\% confidence level' }
    expect: 1
    reason: "Statistical protocol constant chosen a priori, not a result."

scan:
  regions:
    - file: paper.tex
      start: '\section{Evaluation}'
```

Anything else in that region is reported with its line and surrounding text.
In `examples/demo/paper.tex`, insert `Throughput reached 8123 QPS. ` immediately
before `All intervals use` in the Evaluation section. The scan then reports
the following, after the nine passing claims, and exits 1:

```console
$ texclaims scan --ledger claims.yaml --strict
UNMAPPED - paper.tex:13 claimed=8123 :: .2\% across 5 seeds. Throughput reached 8123 QPS. All intervals use the 95\% confide
== 9 PASS, 0 FAIL, 0 MISS, 1 UNMAPPED, 1 WAIVED — FAIL ==
```

Citation keys, labels, filenames and typesetting dimensions (`\hspace{12pt}`,
`[width=0.5]`) are masked out first; a bare `9.9mm` in prose stays visible. The
scan would rather ask about a measurement than go quiet about a result. It
always runs the full check first — coverage a stale ledger could vouch for
would be worthless.

### generate

```yaml
emit:
  output: numbers.tex
  macros:
    - name: HeadlineImprovement
      value: 'summary:.improvement.throughput_pct'
      format: '.1f'
```

```latex
% HeadlineImprovement <- summary:.improvement.throughput_pct = 12.73421
\newcommand{\HeadlineImprovement}{12.7}
```

`\input{numbers}` once, then write `\HeadlineImprovement\%`. Each macro carries
its provenance comment. In CI, `generate --check` verifies the committed file
still matches the ledger instead of rewriting it.

## Tolerance

The default tolerance is **half a unit in the last displayed decimal place** —
the only claim a printed number actually makes.

| In the paper | Accepts | Rejects |
|---|---|---|
| `12.7` | `12.73421`, `12.65` | `12.8`, `13.7` |
| `12.73` | `12.7342` | `12.74` |
| `5` | `5.4` | `5.6` |

Precision is read from the token, so a claim tightens automatically when you
print more digits. `abs_tol` and `rel_tol` are there for the rest, and
satisfying either passes. Floating-point slack is proportional to the
tolerance, never a fixed addend — a fixed addend would dominate at the
magnitudes where p-values and learning rates live.

## Fail-closed by design

Every rule here exists because the alternative fails silently.

| Rule | Without it |
|---|---|
| Unknown ledger field is an error | `scal:` instead of `scale:` passes with the wrong value |
| Duplicate YAML keys are an error | A second `claims:` block deletes the first, run stays green |
| Anchor not found is `MISS`, never a skip | Editing the sentence quietly removes the check |
| `expect` is exact | A copy-pasted paragraph doubles a number unnoticed |
| Each number occurrence is claimed once | One loose regex vouches for several numbers |
| A capture must be the whole number | `88` out of `88.9` audits a number nobody printed |
| Integers keep their exactness | Above 2^53 two different counts become one float |
| Exemptions require a written reason | The waiver list becomes a place to hide things |
| Claims are file-local | An identical number elsewhere satisfies the check |
| `scan --strict` needs a region | An empty gate that reports success is worse than no gate |
| `scan` re-runs `check` first | A stale ledger certifies coverage it no longer has |
| Any unexpected error exits 2 | A traceback exiting 1 reads as "a number is wrong" |

## Continuous integration

```yaml
- run: pip install "texclaims @ git+https://github.com/YYYJH1/texclaims@v0.1.0"
- run: texclaims check    --ledger paper/claims.yaml
- run: texclaims scan     --ledger paper/claims.yaml --strict
- run: texclaims generate --ledger paper/claims.yaml --check
```

> [!NOTE]
> Turn it on before you have full coverage: run `check` as the gate and `scan`
> without `--strict` while you work through the backlog, then flip `--strict`
> on once the region is clean.

## How it compares

| Tool | Position |
|---|---|
| **texclaims** | Audits hand-written numbers · no rewrite · deterministic |
| statcheck | Recomputes p-values · no rewrite · deterministic |
| showyourwork, Quarto, PythonTeX | Numbers become build products · changes authoring · deterministic |
| LLM audit skills | Model reads the manuscript · no rewrite · nondeterministic |
| CODECHECK, artifact evaluation | Human reruns the code · manual |

statcheck is the closest relative and they do not overlap: it asks whether the
reported statistics are internally consistent, `texclaims` whether the reported
numbers match the files that produced them. The literate-programming tools
solve the problem more thoroughly — if you will author in their format, use
them. This is for the manuscript that already exists.

The survey behind this table — 40+ tools across five categories, with
maintenance status and citations — is in [`docs/prior-art.md`](https://github.com/YYYJH1/texclaims/blob/main/docs/prior-art.md).

Prior art: [`jtoman/claims`](https://github.com/jtoman/claims) (2016) paired
LaTeX claim markers with a YAML verifier — the earliest version of this shape I
know of. K-Veritas (arXiv:2605.08586) argues the cryptographic form of the same
requirement.

## Ledger reference

A claim binds one number in one document to one artifact field:

```yaml
- name: headline-improvement
  file: paper.tex
  anchor: { template: 'throughput by {num}\%' }
  expect: 2
  value: 'summary:.improvement.throughput_pct'
```

[`docs/ledger.md`](https://github.com/YYYJH1/texclaims/blob/main/docs/ledger.md) has the rest: the three anchor kinds, the
selector grammar, transforms and tolerances, and every field of the schema.

## Limitations

- Inequality claims ("more than 40%") are out of scope; a ledger entry binds a
  number to a value, not to a predicate.
- Numbers inside figures are not audited. Generate the figure and its caption
  numbers from the same artifact instead.
- Markdown is never masked, since it has no TeX grammar: a `%` in a `.md` file
  is literal and dimensions are not recognised.
- Lengths are masked in recognised commands such as `\hspace{12pt}` and
  `\setlength{\parskip}{12pt}`, as well as options such as `[width=0.5]`.
  Bare or text-formatted measurements (`12pt`, `\textbf{9.9mm}`) stay visible;
  unfamiliar length commands may need an exemption.
- `\iffalse` masking preserves its live `\else` branch and tracks nested
  primitive conditionals. Unclosed blocks or unknown nested conditional commands
  are configuration errors because their coverage cannot be established safely.
- A sign detached from its number (`$- 5$`) is read as positive. Write `$-5$`.
- Include commands (`\input`, `\include`, `\subfile`, `\import` and their
  supported variants) are detected but not followed. List each manuscript file
  in `documents:`. `scan` reports an unlisted included name as `WARN`;
  `scan --strict` refuses to run when it resolves to a real `.tex` section
  inside the project. Unresolved package names and macro-built paths only warn.
  `check` alone does not report these coverage gaps.
- A percent is treated as literal inside `\verb`, `\url`, `\path`, `\href`,
  `\lstinline` and verbatim-like environments. A custom verbatim macro of your
  own is not known to it.
- The scan finds unclaimed numbers, not wrong ones. It tells you where you have
  not looked.

## Development

```console
$ pip install -e ".[dev]"
$ pytest                 # 661 tests
```

Mostly adversarial: each test in `tests/test_failclosed.py` describes a way an
earlier version reported success while a number was wrong, missing, or
unaccounted for. CI runs `texclaims` against its own example. Tests reproduce
the documented edits and compare console output in both READMEs, including
failures and the JSON summary, against what the tool actually prints.

---

<div align="center">

[Demo](https://github.com/YYYJH1/texclaims/tree/main/examples/demo) · [Agent skill](https://github.com/YYYJH1/texclaims/blob/main/skills/texclaims/SKILL.md) ·
[Cite](https://github.com/YYYJH1/texclaims/blob/main/CITATION.cff) · [MIT License](https://github.com/YYYJH1/texclaims/blob/main/LICENSE)

</div>
