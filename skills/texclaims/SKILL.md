---
name: texclaims
description: Build and maintain a texclaims ledger so the numbers in a LaTeX or Markdown manuscript stay tied to the experiment artifacts that produced them. Use when asked to audit, verify, or account for reported numbers in a paper, to set up a submission gate, or when a texclaims run reports FAIL, MISS, or UNMAPPED.
---

# texclaims

`texclaims` reconciles the numbers written in a manuscript against fields in
experiment artifacts (JSON/CSV), through a YAML ledger. It is deterministic:
it decides, you do not.

**The division of labour matters.** You are good at reading prose and
guessing which artifact field a sentence refers to. You are bad at being a
gate — your judgement is not reproducible and cannot be re-run in CI. So:
propose ledger entries, then let `texclaims` rule on them. Never report that
numbers "look consistent" without a clean run behind it.

## Commands

```bash
texclaims check                      # every claimed number matches its artifact
texclaims scan --strict              # every number in the region is claimed
texclaims generate --check           # the emitted macro file is in sync
texclaims init --doc main.tex        # write a ledger skeleton
texclaims check --json               # machine-readable records
```

Exit codes: `0` clean, `1` a number or the prose is wrong, `2` the ledger is
wrong. Treat `2` as your bug, not the author's.

## Bootstrapping a ledger for an existing paper

Work in small batches and keep the run green as you go.

1. `texclaims init --doc <main.tex>`, then set `sources:` to the real result
   files. Prefer one artifact per experiment over one giant blob.
2. Run `texclaims scan` (no `--strict`). Every number in the region comes back
   `UNMAPPED`. That list is your worklist.
3. For each number, read the surrounding sentence, find the artifact field
   that produced it, and add a claim. Anchor with a `template` — a literal
   snippet of the sentence with `{num}` where the number is:

   ```yaml
   - name: headline-improvement
     file: main.tex
     anchor: { template: 'improves throughput by {num}\%' }
     expect: 1
     value: 'summary:.improvement.throughput_pct'
   ```

4. Re-run after every few claims. Stop when `scan --strict` exits 0.
5. Add the three commands to CI.

Do not try to write the whole ledger in one pass. A ledger that fails to load
teaches you nothing; a ledger that goes green ten numbers at a time tells you
exactly which sentence broke.

## Reading the output

| Status | Meaning | What to do |
|---|---|---|
| `PASS` | The number matches its artifact. | Nothing. |
| `FAIL` | It does not match, or the anchor count is off. | Report it. Do **not** adjust the tolerance to make it pass. |
| `MISS` | The anchor no longer matches anything. | The prose was edited. Re-anchor the claim. Do **not** delete it. |
| `UNMAPPED` | A number in the region is unaccounted for. | Add a claim, or an exemption with a real reason. |

A `FAIL` is a finding, not an obstacle. When a claim fails, the answer is
either that the manuscript is wrong or that the ledger points at the wrong
field — never that the tolerance was too tight. The default tolerance is half
a unit in the last printed digit, which is exactly what a printed number
claims; loosening it means asserting something the paper does not.

## Anchoring

Three kinds, in the order you should reach for them:

```yaml
anchor: { template: 'improves throughput by {num}\%' }        # start here
anchor: { pattern: latency_row }                               # tables
anchor: { near: { context: 'Mean utility of', occurrence: 1 } }  # last resort
```

A `near` context is searched forwards to the end of its paragraph, so it must
sit *before* the number it anchors. `template` handles almost everything. Whitespace in it matches any whitespace
run, so line wrapping will not break the anchor, and `{num}` already knows
about signs, thousands separators, scientific notation and `\%`.

Use a named `pattern` when one regex serves several cells of a table row, and
map the capture groups:

```yaml
patterns:
  latency_row: '\$([\d.]+) \\pm ([\d.]+)\$'

claims:
  - name: latency-row
    file: main.tex
    anchor: { pattern: latency_row }
    expect: 1
    groups:
      1: 'summary:.mean_ms'
      2: 'summary:.std_ms'
```

**Never anchor on a nearby number.** `'18.44 & {num}'` looks convenient and
breaks the moment the experiment is rerun, taking every claim in that table
down with it. Anchor on words.

## Multiplicity

`expect` is exact. When a number appears in both the abstract and a results
table, write one claim with `expect: 2`. The two copies are then interlocked:
editing one fails the run. Getting `anchor matched 3 times, expect 2` usually
means the anchor is too short, not that the count is wrong.

## Exemptions

A number that is not a result — a confidence level, a protocol constant, a
year — is waived explicitly, with a reason someone else can read:

```yaml
exemptions:
  - name: confidence-level
    file: main.tex
    anchor: { template: 'the {num}\% confidence level' }
    expect: 1
    reason: "Statistical protocol constant chosen a priori, not a result."
```

An exemption waives **every** number inside its anchor match, not only the
`{num}` capture. Keep the anchor tight; to waive exactly one number in a
sentence that holds several, anchor it with `near`.

Do not use exemptions to clear the worklist. Every exemption you write is a
number nobody will ever check again; if you cannot state why it is not a
result, it probably is one.

## Selectors

```yaml
value: 'summary:.methods["ca-mappo"].utility'
value: 'runs:[] | .hit_rate | mean'          # mean over every CSV row
transform: { scale: 100 }                     # ratio in the artifact, percent in the paper
```

Available after a `|`: `mean`, `median`, `max`, `min`, `sum`, `len`, `abs`,
`first`, `last`. Anything more elaborate belongs in the script that writes the
artifact — a second implementation of the statistics is a second thing to keep
in sync.

## Moving numbers out of the prose

Once the backlog is clear, stop the problem recurring: emit the numbers as
macros and reference those in new text.

```yaml
emit:
  output: numbers.tex
  macros:
    - { name: HeadlineImprovement, value: 'summary:.improvement.throughput_pct', format: '.1f' }
```

`\input{numbers}` once, then write `\HeadlineImprovement\%`. `check` still
guards everything already hand-written; `generate --check` in CI catches a
stale macro file.

## Things that will bite you

- Editing the manuscript and the ledger in the same breath, then not
  re-running. Re-run.
- Treating a `MISS` as an obsolete claim. It means the sentence moved.
- Widening `abs_tol` to clear a `FAIL`.
- Exempting numbers in bulk to reach a green run.
- Reporting success from reading the output of `check` alone: it only proves
  the mapped numbers are right. Coverage needs `scan --strict`.
