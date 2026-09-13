# Prior art

Before writing `texclaims` I surveyed what already existed, across five
categories. This is that survey, trimmed to what a reader might want to check.
Everything here was verified in August 2026; adoption figures move, so treat
them as a snapshot rather than a claim.

The short version: several tools solve a neighbouring problem well, and one
dead project (2016) had the same shape. Nothing installable reconciles
hand-written manuscript numbers against artifact fields, which is the gap this
tool fills.

## 1. Build-time generation — the numbers become build products

These remove hand-copied numbers by making every number a computed value. They
solve the problem more thoroughly than `texclaims` does. The cost is that you
author the paper in their format and adopt their build system.

| Tool | Status (Aug 2026) | Relationship |
|---|---|---|
| [showyourwork](https://github.com/showyourwork/showyourwork) | 663★, last release v0.4.3 (Aug 2023) | The closest precedent: Snakemake-backed, figure- *and* number-level provenance via `\variable`, CI-gated. Requires restructuring the repo as a workflow. |
| [knitr](https://github.com/yihui/knitr) / Sweave | Active, CRAN | The R standard. Inline `\Sexpr{}` computes at compile time. Requires `.Rnw`/`.Rmd` and R. |
| [Quarto](https://quarto.org/docs/computations/inline-code.html) | Very active (Posit) | The current mainstream answer. Explicitly aims at "prose never drifts out of sync with analysis". Requires authoring in `.qmd`. |
| [PythonTeX](https://ctan.org/pkg/pythontex) | Stalled (v0.18, 2021) | Executes Python inside LaTeX. Closest to a plain-LaTeX author, but the numbers still become code calls. |
| [Rxiv-Maker](https://github.com/HenriquesLab/rxiv-maker) | Active, arXiv:2508.00836 | 2025 entrant, same lineage: enhanced Markdown, numbers generated at build. |
| [paper-pipeline](https://github.com/jbrusey/paper-pipeline) | New (Jul 2026), individual | An agent skill teaching Make-based pipelines that emit LaTeX macros. No reconciliation step. |

None of them audits an existing `.tex`. In this family a number is derived by
construction, so "does the printed number match the data" is not a question that
arises — and cannot be asked of a manuscript already written.

## 2. Post-hoc checking — read the paper, judge the numbers

| Tool | Status | Relationship |
|---|---|---|
| [statcheck](https://github.com/MicheleNuijten/statcheck) | ~192★, active, used in journal workflows | The closest relative in spirit: audits numbers already written, no workflow change, can gate. But it recomputes p-values from the statistics beside them — internal consistency, never external evidence. Its prevalence work is also the best evidence that this class of error is real. |
| GRIM / SPRITE ([rsprite2](https://lukaswallrich.github.io/rsprite2/)) | CRAN, stable | Tests whether a reported mean is arithmetically possible. No artifacts involved. |
| [SciScore](https://www.sciscore.com/) | Commercial, journal-integrated | Checks methods-section rigor criteria, not results. |
| [CODECHECK](https://codecheck.org.uk/) | Active, publisher partnerships | A human re-runs the code and certifies it. Whole-workflow granularity, not per-number. |
| The Black Spatula Project, YesNoError | Active 2024–2026 | LLM sweeps over manuscripts. Probabilistic; useful as reviewers, not as gates. |
| [PaperRepro](https://arxiv.org/abs/2603.00058) | 2026 paper, code released | LLM agents re-execute an artifact and compare findings. Grounded, but agent-driven and aimed at third-party review. |
| [SciCoQA](https://arxiv.org/abs/2601.12910v3) | 2026 benchmark, ACL | 635 paper–code discrepancies (92 real, 543 synthetic); the best evaluated models detect 46.7% of real-world discrepancies. A benchmark for paper–code alignment, not an artifact-field reconciliation tool. |

## 3. The same shape, tried before

[`jtoman/claims`](https://github.com/jtoman/claims) (2016, 24★, ~10 commits)
paired LaTeX claim markers with a YAML file mapping claim IDs to verification
commands. It is the earliest version of this idea I found. It required editing
the manuscript to insert markers, had no artifact-field selectors and no
tolerance model, and was abandoned.

Two current projects reach for the same goal from the agent side:
[`pedrohcgs/claude-code-my-workflow`](https://github.com/pedrohcgs/claude-code-my-workflow)
(~1.5k★) has a `passport.yaml` recording per-claim PASS/FAIL with tolerances,
and `CatNebulaaaa/ClaimCheck-Skill` freezes paper-vs-code claims for review.
Both are agent workflows: the audit is orchestrated by a model, so it is not
reproducible and cannot be a CI gate. They are good evidence the need is real.

## 4. Experiment tracking — generation only, never verification

MLflow, Weights & Biases, DVC, sacred, Guild AI and Aim were all checked. The
traffic is one-way: W&B Reports export LaTeX, DVC compares metric files between
revisions (`dvc metrics diff`, the closest mechanism in the ecosystem), Guild
renders reports. None parses a `.tex`, and none has a notion of "the number
printed on page 7 should equal this field".

## 5. Publication infrastructure

ACM and IEEE artifact badging, cTuning's CK/CM toolchain, AutoAppendix, Code
Ocean and ReproZip all stop at "does the artifact run". ACM's *Results
Reproduced* criteria explicitly accept agreement "within a tolerance deemed
acceptable", so numeric drift is tolerated by design. Several 2025–2026 papers
treat this as a known gap; K-Veritas (arXiv:2605.08586) argues for the
cryptographic form of the same requirement — signed, non-repudiable evidence
that a reported number came from a real computation.

## What this leaves

A tool that (a) leaves the manuscript as it is, (b) binds each printed number to
a named field in a named artifact, (c) decides deterministically, and (d) exits
non-zero, did not exist in an installable form. `texclaims` is that, and
nothing more: it does not re-run experiments (CODECHECK, PaperRepro do), does
not judge statistics (statcheck does), and does not generate your numbers
(Quarto, showyourwork do — and if you are willing to author in their format,
they are the better answer).
