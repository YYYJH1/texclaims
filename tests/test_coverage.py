"""Coverage scan: every number inside a declared region must be accounted for."""

from __future__ import annotations

import pytest

from texclaims.cli import main
from texclaims.coverage import run_scan
from texclaims.errors import LedgerError
from texclaims.ledger import load_ledger
from texclaims.report import MISS, PASS, UNMAPPED

SUMMARY = {
    "results/summary.json": {
        "throughput_pct": 12.7,
        "hit_rate": 94.2,
        "overhead_pct": 3.3,
        "gap": 7.7,
        "rps": 88.0,
    }
}


def _claim(name, template, selector, expect=1):
    return {
        "name": name,
        "file": "paper.tex",
        "anchor": {"template": template},
        "expect": expect,
        "value": f"summary:{selector}",
    }


def _regions(**bounds):
    return {"scan": {"regions": [{"file": "paper.tex", **bounds}]}}


def _build(project, tex, claims, **extra):
    return project(
        documents={"paper.tex": tex},
        artifacts=SUMMARY,
        ledger={"sources": {"summary": "results/summary.json"}, "claims": claims, **extra},
    )


def _scan(path):
    return run_scan(load_ledger(path))


def _unmapped(state):
    return [r for r in state.report.records if r.status == UNMAPPED]


def _tokens(state):
    return [r.claimed for r in _unmapped(state)]


def _named(state, name):
    return [r for r in state.report.records if r.name == name]


INTRO_AND_EVAL = r"""\documentclass{article}
\begin{document}

\section{Introduction}
Throughput improved by 12.7\% overall.

\section{Evaluation}
The tuned baseline reached 88.0 requests per second.

\end{document}
"""


def test_unclaimed_number_in_region_is_unmapped(project):
    path = _build(
        project,
        INTRO_AND_EVAL,
        [_claim("throughput", r"improved by {num}\%", ".throughput_pct")],
        **_regions(start=r"\section{Evaluation}"),
    )
    state = _scan(path)

    assert [r.status for r in _named(state, "throughput")] == [PASS]
    records = _unmapped(state)
    assert len(records) == 1
    record = records[0]
    assert record.file == "paper.tex"
    assert record.line == 8
    assert record.claimed == "88.0"
    assert "tuned baseline reached 88.0" in record.note
    assert state.report.exit_code() == 1


def test_claimed_number_in_region_is_not_unmapped(project):
    tex = r"""\documentclass{article}
\begin{document}

\section{Evaluation}
The tuned baseline reached 88.0 requests per second.

\end{document}
"""
    path = _build(
        project,
        tex,
        [_claim("rps", "reached {num} requests", ".rps")],
        **_regions(start=r"\section{Evaluation}"),
    )
    state = _scan(path)

    assert [r.status for r in _named(state, "rps")] == [PASS]
    assert _unmapped(state) == []
    assert state.report.exit_code() == 0


def test_exemption_covers_every_number_token_inside_its_anchor(project):
    tex = r"""\documentclass{article}
\begin{document}

\section{Introduction}
Throughput improved by 12.7\% overall.

\section{Evaluation}
Hardware: 8 cores and 64 GB of RAM.

\end{document}
"""
    path = _build(
        project,
        tex,
        [_claim("throughput", r"improved by {num}\%", ".throughput_pct")],
        exemptions=[
            {
                "name": "test-rig",
                "file": "paper.tex",
                "anchor": {"template": "Hardware: {num} cores and 64 GB of RAM"},
                "expect": 1,
                "reason": "Fixed lab machine spec, not an experimental result.",
            }
        ],
        **_regions(start=r"\section{Evaluation}"),
    )
    state = _scan(path)

    assert _named(state, "test-rig") == []  # a satisfied exemption is silent
    assert _unmapped(state) == []
    assert state.report.exit_code() == 0


def test_percent_suffixed_token_is_covered_by_the_prefix_rule(project):
    tex = r"""\documentclass{article}
\begin{document}

\section{Evaluation}
An average cache hit rate of 94.2\% was observed.

\end{document}
"""
    path = _build(
        project,
        tex,
        [_claim("hit-rate", r"hit rate of {num}\%", ".hit_rate")],
        **_regions(start=r"\section{Evaluation}"),
    )
    state = _scan(path)

    doc = state.document("paper.tex")
    (span,) = state.claimed_spans["paper.tex"]
    assert doc.raw[span[0]:span[1]] == "94.2"
    assert doc.raw[span[0]:span[1] + 2] == r"94.2\%"  # scan token is strictly longer

    assert [r.status for r in _named(state, "hit-rate")] == [PASS]
    assert _unmapped(state) == []
    assert state.report.exit_code() == 0


THREE_SECTIONS = r"""\documentclass{article}
\begin{document}

\section{Introduction}
Overhead was 3.3 percent in the pilot study.

\section{Evaluation}
The observed gap was 7.7 units.

\section{Related Work}
Prior work reported 5.5 units.

\end{document}
"""


def test_region_start_and_end_anchors_bound_the_scan(project):
    path = _build(
        project,
        THREE_SECTIONS,
        [_claim("overhead", "Overhead was {num} percent", ".overhead_pct")],
        **_regions(start=r"\section{Evaluation}", end=r"\section{Related Work}"),
    )
    state = _scan(path)

    records = _unmapped(state)
    assert len(records) == 1
    assert records[0].claimed == "7.7"
    assert records[0].line == 8


def test_unclaimed_numbers_outside_the_region_are_ignored(project):
    path = _build(
        project,
        THREE_SECTIONS,
        [_claim("gap", "observed gap was {num} units", ".gap")],
        **_regions(start=r"\section{Evaluation}", end=r"\section{Related Work}"),
    )
    state = _scan(path)

    assert [r.status for r in _named(state, "gap")] == [PASS]
    assert _unmapped(state) == []
    assert state.report.exit_code() == 0


def test_region_without_bounds_covers_the_whole_file(project):
    tex = r"""\documentclass{article}
\begin{document}
Overhead was 3.3 percent in the pilot study.

\section{Evaluation}
The tuned baseline reached 88.0 requests per second.

Total cost was 4.4 dollars.

\end{document}
"""
    path = _build(
        project,
        tex,
        [_claim("rps", "reached {num} requests", ".rps")],
        **_regions(),
    )
    state = _scan(path)

    assert _tokens(state) == ["3.3", "4.4"]
    assert [r.line for r in _unmapped(state)] == [3, 8]


def test_missing_start_anchor_is_a_config_error(project):
    path = _build(
        project,
        INTRO_AND_EVAL,
        [_claim("throughput", r"improved by {num}\%", ".throughput_pct")],
        **_regions(start=r"\section{Nonexistent}"),
    )
    with pytest.raises(LedgerError) as excinfo:
        _scan(path)
    message = str(excinfo.value)
    assert "start anchor" in message
    assert "matched 0 time(s)" in message
    assert "must match exactly once" in message


def test_ambiguous_start_anchor_is_a_config_error(project):
    tex = r"""\documentclass{article}
\begin{document}

\section{Introduction}
We compare against the baseline configuration.

\section{Evaluation}
Against the baseline the gap was 7.7 units.

\end{document}
"""
    path = _build(
        project,
        tex,
        [_claim("gap", "gap was {num} units", ".gap")],
        **_regions(start="the baseline"),
    )
    with pytest.raises(LedgerError) as excinfo:
        _scan(path)
    assert "matched 2 time(s)" in str(excinfo.value)


def test_empty_region_between_adjacent_anchors_is_a_config_error(project):
    tex = r"""\documentclass{article}
\begin{document}

\section{Evaluation}\subsection{Setup}
The observed gap was 7.7 units.

\end{document}
"""
    path = _build(
        project,
        tex,
        [_claim("gap", "gap was {num} units", ".gap")],
        **_regions(start=r"\section{Evaluation}", end=r"\subsection{Setup}"),
    )
    with pytest.raises(LedgerError) as excinfo:
        _scan(path)
    assert "paper.tex is empty or inverted" in str(excinfo.value)


def test_stale_ledger_cannot_fake_coverage(project):
    tex = r"""\documentclass{article}
\begin{document}

\section{Evaluation}
FastCache improves latency by 12.7\% over the tuned baseline.

\end{document}
"""
    path = _build(
        project,
        tex,
        [_claim("throughput", r"improves throughput by {num}\%", ".throughput_pct")],
        **_regions(),
    )
    state = _scan(path)

    miss = _named(state, "throughput")
    assert [r.status for r in miss] == [MISS]
    assert "anchor not found" in miss[0].note
    assert _tokens(state) == [r"12.7\%"]
    assert state.report.counts()[UNMAPPED] == 1
    assert state.report.exit_code() == 1


def test_claim_with_wrong_multiplicity_covers_nothing(project):
    tex = r"""\documentclass{article}
\begin{document}

\section{Evaluation}
Throughput improved by 12.7\% over the tuned baseline.
Restated: throughput improved by 12.7\% end to end.

\end{document}
"""
    path = _build(
        project,
        tex,
        [_claim("throughput", r"improved by {num}\%", ".throughput_pct", expect=1)],
        **_regions(start=r"\section{Evaluation}"),
    )
    state = _scan(path)

    (failure,) = _named(state, "throughput")
    assert "anchor matched 2 time(s), expect 1" in failure.note
    assert _tokens(state) == [r"12.7\%", r"12.7\%"]
    assert state.report.exit_code() == 1


def test_region_can_be_bounded_by_a_masked_latex_command(project):
    tex = r"""\documentclass{article}
\begin{document}

\section{Introduction}
Overhead was 3.3 percent in the pilot study.

\section{Evaluation}
\label{sec:eval}
The observed gap was 7.7 units.

\end{document}
"""
    path = _build(
        project,
        tex,
        [_claim("overhead", "Overhead was {num} percent", ".overhead_pct")],
        **_regions(start=r"\label{sec:eval}"),
    )
    state = _scan(path)

    assert _tokens(state) == ["7.7"]


def test_ledger_without_scan_regions_warns(project):
    tex = r"""\documentclass{article}
\begin{document}
Throughput improved by 12.7\% overall.
\end{document}
"""
    path = _build(
        project, tex, [_claim("throughput", r"improved by {num}\%", ".throughput_pct")]
    )
    state = _scan(path)

    assert state.report.warnings == [
        "no scan regions declared; coverage scan had nothing to do"
    ]
    assert _unmapped(state) == []
    assert state.report.exit_code() == 0


def test_masked_citations_and_typesetting_dimensions_are_not_unmapped(project):
    tex = r"""\documentclass{article}
\begin{document}

\section{Introduction}
Throughput improved by 12.7\% overall.

\section{Evaluation}
Prior work \cite{smith2024, jones-2019} and \ref{fig:2} used a 12pt body font
set in 10 pt captions, with \pgfplotsset{scale=0.75} for every plot.
\includegraphics[width=0.8\textwidth]{fig1.pdf}
The residual error is 0.42 units.

\end{document}
"""
    path = _build(
        project,
        tex,
        [_claim("throughput", r"improved by {num}\%", ".throughput_pct")],
        **_regions(start=r"\section{Evaluation}"),
    )
    state = _scan(path)

    # Citation keys, refs and the graphics option are masked. The font sizes
    # are surfaced: outside a LaTeX dimension slot they are indistinguishable
    # from a measurement, and the scan errs toward asking rather than silence.
    assert _tokens(state) == ["12", "10", "0.42"]
    assert _unmapped(state)[-1].line == 11


def test_unmapped_gates_the_run_only_under_strict(project, capsys):
    path = _build(
        project,
        INTRO_AND_EVAL,
        [_claim("throughput", r"improved by {num}\%", ".throughput_pct")],
        **_regions(start=r"\section{Evaluation}"),
    )

    assert main(["scan", "--ledger", str(path)]) == 0
    out = capsys.readouterr().out
    assert "UNMAPPED" in out
    assert "claimed=88.0" in out

    assert main(["scan", "--ledger", str(path), "--strict"]) == 1
