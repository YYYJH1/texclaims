"""CLI surface: exit-code policy, output formats, generate/init, end-to-end."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from texclaims import __version__
from texclaims.cli import main

PAPER = r"""\documentclass{article}
\begin{document}
\section{Evaluation}
FastCache improves throughput by 12.7\% over the tuned baseline.
Mean request latency drops to 3.21 ms on the same hardware.
\end{document}
"""

SUMMARY = {
    "improvement_pct": 12.73421,
    "latency_ms": 3.2114,
    "hit_rate": 0.94218,
    "raw_seeds": 4.6,
}

SCAN = {"regions": [{"file": "paper.tex", "start": r"\section{Evaluation}"}]}

EMIT = {
    "output": "numbers.tex",
    "macros": [
        {"name": "Improvement", "value": "summary:.improvement_pct", "format": ".1f"},
        {"name": "Seeds", "value": "summary:.raw_seeds", "format": "d"},
        {"name": "HitRate", "value": "summary:.hit_rate", "scale": 100, "format": ".1f"},
    ],
}


def throughput_claim(**overrides):
    claim = {
        "name": "throughput",
        "file": "paper.tex",
        "anchor": {"template": r"throughput by {num}\%"},
        "expect": 1,
        "value": "summary:.improvement_pct",
    }
    claim.update(overrides)
    return claim


def latency_claim(**overrides):
    claim = {
        "name": "latency",
        "file": "paper.tex",
        "anchor": {"template": "drops to {num} ms"},
        "expect": 1,
        "value": "summary:.latency_ms",
    }
    claim.update(overrides)
    return claim


def make(project, *, paper=PAPER, summary=None, claims=None, **extra):
    """Write a one-document project and return the path to its ledger."""
    return project(
        documents={"paper.tex": paper},
        artifacts={"results/summary.json": dict(SUMMARY, **(summary or {}))},
        ledger={
            "sources": {"summary": "results/summary.json"},
            "claims": [throughput_claim()] if claims is None else claims,
            **extra,
        },
    )


@pytest.fixture
def run(capsys):
    """Invoke the CLI in-process; return (exit_code, stdout, stderr)."""

    def _run(*argv):
        code = main(list(argv))
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return _run


# --- exit-code taxonomy: 0 clean / 1 reconciliation / 2 configuration -------

def test_reconciled_number_exits_zero(project, run):
    ledger = make(project)
    code, out, err = run("check", "--ledger", str(ledger))
    assert code == 0
    assert out.splitlines() == [
        "PASS     throughput paper.tex:4 claimed=12.7 expected=12.73421 tol=0.05"
    ]
    assert "== 1 PASS, 0 FAIL, 0 MISS, 0 UNMAPPED, 0 WAIVED — OK ==" in err


def test_fabricated_number_exits_one(project, run):
    ledger = make(project, paper=PAPER.replace("12.7", "18.4"))
    code, out, err = run("check", "--ledger", str(ledger))
    assert code == 1
    assert out.startswith("FAIL     throughput paper.tex:4 claimed=18.4 expected=12.73421")
    assert "exceeds display-precision tolerance" in out
    assert "== 0 PASS, 1 FAIL, 0 MISS, 0 UNMAPPED, 0 WAIVED — FAIL ==" in err


def test_rewritten_sentence_exits_one_as_miss(project, run):
    ledger = make(project, paper=PAPER.replace("throughput by 12.7", "goodput of 12.7"))
    code, out, err = run("check", "--ledger", str(ledger))
    assert code == 1
    assert out.startswith("MISS     throughput paper.tex :: anchor not found")
    assert "0 PASS, 0 FAIL, 1 MISS" in err


def test_unknown_ledger_field_is_config_error(project, run):
    ledger = make(project, claims=[throughput_claim(scal=100)])
    code, out, err = run("check", "--ledger", str(ledger))
    assert code == 2
    assert err.startswith("CONFIG ERROR: ")
    assert "unknown field(s) ['scal']" in err
    assert out == ""


def test_unreadable_ledger_is_config_error(tmp_path, run):
    code, out, err = run("check", "--ledger", str(tmp_path / "absent.yaml"))
    assert code == 2
    assert "CONFIG ERROR: cannot read ledger" in err


def test_bad_selector_is_config_error_not_a_failed_claim(project, run):
    ledger = make(project, claims=[throughput_claim(value="summary:.no_such_key")])
    code, out, err = run("check", "--ledger", str(ledger))
    assert code == 2
    assert "CONFIG ERROR: claim 'throughput': [summary:.no_such_key] key 'no_such_key' not found" in err


def test_bad_group_selector_names_the_claim_and_group(project, run):
    claim = {"name": "latency-row", "file": "paper.tex", "expect": 1,
             "anchor": {"template": "from {num} to {num}"},
             "groups": {1: "summary:.baseline_ms", 2: "summary:.missing"}}
    ledger = make(project, paper="Latency from 4.87 to 3.21.\n", claims=[claim],
                  summary={"baseline_ms": 4.87})
    code, out, err = run("check", "--ledger", str(ledger))
    assert code == 2
    assert "claim 'latency-row' group 2: [summary:.missing] key 'missing' not found" in err


def test_bad_macro_selector_names_the_macro(project, run):
    emit = {"output": "numbers.tex", "macros": [
        {"name": "MissingMetric", "value": "summary:.missing"}]}
    ledger = make(project, emit=emit)
    code, out, err = run("generate", "--ledger", str(ledger))
    assert code == 2
    assert "macro 'MissingMetric': [summary:.missing] key 'missing' not found" in err
    assert not (ledger.parent / "numbers.tex").exists()


def test_missing_subcommand_is_a_usage_error():
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


def test_version_flag_prints_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"texclaims {__version__}"


# --- --json: the agent-facing contract -------------------------------------

def test_json_output_is_parsable_and_reports_ok(project, run):
    ledger = make(project)
    code, out, err = run("check", "--ledger", str(ledger), "--json")
    assert code == 0
    payload = json.loads(out)
    assert set(payload) == {"records", "warnings", "waived", "summary"}
    assert payload["waived"] == {}
    assert payload["summary"] == {
        "PASS": 1, "FAIL": 0, "MISS": 0, "UNMAPPED": 0, "WAIVED": 0, "verdict": "OK"
    }
    assert payload["records"] == [{
        "status": "PASS", "name": "throughput", "file": "paper.tex", "line": 4,
        "claimed": "12.7", "expected": 12.73421,
        "tolerance": pytest.approx(0.05, rel=1e-6), "note": "",
    }]


def test_json_verdict_is_fail_when_a_number_disagrees(project, run):
    ledger = make(project, paper=PAPER.replace("12.7", "18.4"))
    code, out, err = run("check", "--ledger", str(ledger), "--json")
    assert code == 1
    payload = json.loads(out)
    assert payload["summary"]["verdict"] == "FAIL"
    assert payload["summary"]["FAIL"] == 1
    assert payload["records"][0]["status"] == "FAIL"
    assert "exceeds display-precision tolerance" in payload["records"][0]["note"]


def test_json_carries_warnings(project, run):
    ledger = make(project)
    code, out, err = run("scan", "--ledger", str(ledger), "--json")
    assert code == 0
    payload = json.loads(out)
    assert payload["warnings"] == [
        "no scan regions declared; coverage scan had nothing to do"
    ]


@pytest.mark.parametrize("command", ["check", "scan"])
@pytest.mark.parametrize("problem", ["missing-ledger", "schema", "selector", "artifact"])
def test_json_configuration_errors_keep_the_diagnostic_and_exit_two(project, run, command, problem):
    claims = [throughput_claim()]
    if problem == "schema":
        claims = [throughput_claim(scal=100)]
    if problem == "selector":
        claims = [throughput_claim(value="summary:.missing")]
    ledger = make(project, claims=claims)
    if problem == "missing-ledger":
        ledger = ledger.parent / "absent.yaml"
    if problem == "artifact":
        (ledger.parent / "results/summary.json").write_text("{broken", encoding="utf-8")
    code, out, err = run(command, "--ledger", str(ledger), "--json")
    assert code == 2
    assert err.startswith("CONFIG ERROR: ")
    message = err.removeprefix("CONFIG ERROR: ").strip()
    assert json.loads(out) == {
        "records": [], "warnings": [], "summary": {"verdict": "CONFIG_ERROR"},
        "error": {"message": message},
    }


# --- scan: coverage gate is opt-in via --strict ----------------------------

def test_scan_reports_unmapped_without_failing_the_run(project, run):
    ledger = make(project, scan=SCAN)
    code, out, err = run("scan", "--ledger", str(ledger))
    assert code == 0
    unmapped = [line for line in out.splitlines() if line.startswith("UNMAPPED")]
    assert len(unmapped) == 1
    assert unmapped[0].startswith("UNMAPPED - paper.tex:5 claimed=3.21 ::")
    assert "Mean request latency drops to 3.21 ms" in unmapped[0]


def test_scan_strict_turns_unmapped_into_a_failure(project, run):
    ledger = make(project, scan=SCAN)
    code, out, err = run("scan", "--ledger", str(ledger), "--strict")
    assert code == 1
    assert "1 PASS, 0 FAIL, 0 MISS, 1 UNMAPPED, 0 WAIVED — FAIL" in err


def test_scan_strict_passes_when_every_number_is_claimed(project, run):
    ledger = make(project, claims=[throughput_claim(), latency_claim()], scan=SCAN)
    code, out, err = run("scan", "--ledger", str(ledger), "--strict")
    assert code == 0
    assert "2 PASS, 0 FAIL, 0 MISS, 0 UNMAPPED, 0 WAIVED — OK" in err
    assert "UNMAPPED" not in out


def test_scan_without_strict_still_fails_on_a_wrong_number(project, run):
    ledger = make(project, paper=PAPER.replace("12.7", "18.4"), scan=SCAN)
    code, out, err = run("scan", "--ledger", str(ledger))
    assert code == 1
    assert "FAIL     throughput" in out


def test_non_strict_scan_verdict_agrees_with_exit_code(project, run):
    ledger = make(project, scan=SCAN)
    code, out, err = run("scan", "--ledger", str(ledger), "--json")
    assert code == 0
    assert json.loads(out)["summary"]["verdict"] == "OK"


# --- generate --------------------------------------------------------------

def test_generate_writes_provenance_comments_and_newcommands(project, run, tmp_path):
    ledger = make(project, emit=EMIT)
    code, out, err = run("generate", "--ledger", str(ledger))
    assert code == 0
    assert "3 macro(s)" in err
    emitted = tmp_path / "numbers.tex"
    assert emitted.read_text(encoding="utf-8").splitlines() == [
        "% Generated by texclaims — do not edit by hand.",
        "% Macros: 3",
        "% Improvement <- summary:.improvement_pct = 12.73421",
        r"\newcommand{\Improvement}{12.7}",
        "% Seeds <- summary:.raw_seeds = 4.6",
        r"\newcommand{\Seeds}{5}",
        "% HitRate <- summary:.hit_rate = 0.94218",
        r"\newcommand{\HitRate}{94.2}",
    ]


def test_generate_integer_format_rounds_rather_than_truncates(project, run, tmp_path):
    emit = {"output": "numbers.tex",
            "macros": [{"name": "Seeds", "value": "summary:.raw_seeds", "format": "d"}]}
    ledger = make(project, summary={"raw_seeds": 41.6}, emit=emit)
    code, out, err = run("generate", "--ledger", str(ledger))
    assert code == 0
    assert r"\newcommand{\Seeds}{42}" in (tmp_path / "numbers.tex").read_text(encoding="utf-8")


def test_generate_formatless_macros_use_six_significant_figures(project, run, tmp_path):
    # %g / six significant figures is the default, including its rounding
    # and scientific notation. Changing it changes existing generated files.
    emit = {"output": "numbers.tex", "macros": [
        {"name": "Count", "value": "summary:.count"},
        {"name": "Fraction", "value": "summary:.fraction"},
    ]}
    ledger = make(project, summary={"count": 1234567, "fraction": 0.123456789}, emit=emit)
    code, out, err = run("generate", "--ledger", str(ledger))
    assert code == 0
    macros = [line for line in (tmp_path / "numbers.tex").read_text().splitlines()
              if line.startswith(r"\newcommand")]
    assert macros == [r"\newcommand{\Count}{1.23457e+06}",
                      r"\newcommand{\Fraction}{0.123457}"]


def test_generate_bad_format_is_a_configuration_error(project, run, tmp_path):
    emit = {"output": "numbers.tex", "macros": [
        {"name": "BadFormat", "value": "summary:.improvement_pct", "format": ".2q"}]}
    ledger = make(project, emit=emit)
    code, out, err = run("generate", "--ledger", str(ledger))
    assert code == 2
    assert "bad format spec '.2q' for macro 'BadFormat'" in err
    assert not (tmp_path / "numbers.tex").exists()


def test_generate_honours_out_override(project, run, tmp_path):
    ledger = make(project, emit=EMIT)
    target = tmp_path / "macros" / "generated.tex"
    target.parent.mkdir()
    code, out, err = run("generate", "--ledger", str(ledger), "--out", str(target))
    assert code == 0
    assert r"\newcommand{\Improvement}{12.7}" in target.read_text(encoding="utf-8")
    assert not (tmp_path / "numbers.tex").exists()


def test_relative_out_resolves_against_the_ledger_directory(project, run, tmp_path,
                                                            monkeypatch):
    ledger = make(project, emit=EMIT)
    workdir = tmp_path / "elsewhere"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    code, out, err = run("generate", "--ledger", str(ledger), "--out", "macros.tex")
    assert code == 0
    assert (tmp_path / "macros.tex").exists()
    assert not (workdir / "macros.tex").exists()


def test_generate_replaces_output_from_a_temporary_file_in_the_same_directory(
    project, run, tmp_path, monkeypatch,
):
    from texclaims import cli
    ledger = make(project, emit=EMIT)
    output = tmp_path / "numbers.tex"
    output.write_text("old macros\n", encoding="utf-8")
    replace = cli.os.replace
    replacements = []

    def observe_replace(source, target):
        source, target = Path(source), Path(target)
        # Until the complete replacement is ready, the old macro file must
        # remain intact. A temporary in another directory may cross filesystems.
        assert target == output
        assert source.parent == target.parent
        assert source != target
        assert target.read_text(encoding="utf-8") == "old macros\n"
        assert r"\newcommand{\Improvement}{12.7}" in source.read_text(encoding="utf-8")
        replacements.append(source)
        replace(source, target)

    monkeypatch.setattr(cli.os, "replace", observe_replace)
    assert run("generate", "--ledger", str(ledger))[0] == 0
    assert len(replacements) == 1
    assert not replacements[0].exists()


def test_generate_check_passes_when_emitted_file_is_current(project, run, tmp_path):
    ledger = make(project, emit=EMIT)
    assert run("generate", "--ledger", str(ledger))[0] == 0
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns)
              for p in tmp_path.rglob("*") if p.is_file()}
    code, out, err = run("generate", "--ledger", str(ledger), "--check")
    assert code == 0
    assert out == ""
    assert "numbers.tex is in sync" in err
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns)
            for p in tmp_path.rglob("*") if p.is_file()} == before


def test_generate_check_prints_a_diff_for_a_hand_edited_file(project, run, tmp_path):
    ledger = make(project, emit=EMIT)
    run("generate", "--ledger", str(ledger))
    emitted = tmp_path / "numbers.tex"
    emitted.write_text(
        emitted.read_text(encoding="utf-8").replace("{12.7}", "{99.9}"), encoding="utf-8"
    )
    code, out, err = run("generate", "--ledger", str(ledger), "--check")
    assert code == 1
    assert "+++ regenerated" in out
    assert r"-\newcommand{\Improvement}{99.9}" in out
    assert r"+\newcommand{\Improvement}{12.7}" in out
    assert "is stale; re-run generate" in err
    assert "{99.9}" in emitted.read_text(encoding="utf-8")


def test_generate_refuses_to_write_when_a_claim_fails(project, run, tmp_path):
    ledger = make(project, paper=PAPER.replace("12.7", "18.4"), emit=EMIT)
    code, out, err = run("generate", "--ledger", str(ledger))
    assert code == 1
    assert out.startswith("FAIL     throughput")
    assert "generate refused: fix the failing claims first" in err
    assert not (tmp_path / "numbers.tex").exists()


def test_generate_check_refuses_when_a_claim_fails(project, run, tmp_path):
    ledger = make(project, emit=EMIT)
    run("generate", "--ledger", str(ledger))
    broken = make(project, paper=PAPER.replace("12.7", "18.4"), emit=EMIT)
    code, out, err = run("generate", "--ledger", str(broken), "--check")
    assert code == 1
    assert "generate refused: fix the failing claims first" in err
    assert "+++ regenerated" not in out


def test_generate_without_an_emit_section_is_a_config_error(project, run, tmp_path):
    ledger = make(project)
    code, out, err = run("generate", "--ledger", str(ledger))
    assert code == 2
    assert "CONFIG ERROR: ledger has no 'emit' section" in err
    assert not (tmp_path / "numbers.tex").exists()


def test_generate_check_without_an_emitted_file_is_a_config_error(project, run):
    ledger = make(project, emit=EMIT)
    code, out, err = run("generate", "--ledger", str(ledger), "--check")
    assert code == 2
    assert "CONFIG ERROR: cannot read emitted file" in err


# --- init ------------------------------------------------------------------

def test_init_writes_a_loadable_skeleton(run, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code, out, err = run("init", "--doc", "main.tex")
    assert code == 0
    assert "edit the sources and claims" in err
    skeleton = yaml.safe_load((tmp_path / "claims.yaml").read_text(encoding="utf-8"))
    assert skeleton["version"] == 1
    assert skeleton["documents"] == ["main.tex"]
    assert skeleton["sources"] == {"summary": "results/summary.json"}
    assert skeleton["claims"] == []
    assert "#   - name: example-claim" in (tmp_path / "claims.yaml").read_text(encoding="utf-8")


def test_init_then_scan_reports_the_first_worklist(run, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "main.tex").write_text("We served 8123 requests.\n", encoding="utf-8")
    (tmp_path / "out").mkdir()
    (tmp_path / "out/metrics.json").write_text('{"requests": 8123}', encoding="utf-8")
    assert run("init", "--doc", "main.tex")[0] == 0
    path = tmp_path / "claims.yaml"
    # The source remains a live placeholder: fix only the path the onboarding
    # instructions name, without having to delete a claim from the demo paper.
    path.write_text(path.read_text(encoding="utf-8").replace(
        "results/summary.json", "out/metrics.json"), encoding="utf-8")
    code, out, err = run("scan")
    assert code == 0
    assert out.startswith("UNMAPPED - main.tex:1 claimed=8123")
    assert "0 PASS, 0 FAIL, 0 MISS, 1 UNMAPPED, 0 WAIVED — OK" in err
    assert run("scan", "--strict")[0] == 2


def test_init_refuses_to_overwrite_an_existing_ledger(run, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "claims.yaml").write_text("# hand-written\n", encoding="utf-8")
    code, out, err = run("init")
    assert code == 2
    assert "claims.yaml already exists; refusing to overwrite" in err
    assert (tmp_path / "claims.yaml").read_text(encoding="utf-8") == "# hand-written\n"


# --- end-to-end golden: the committed demo project -------------------------

def test_demo_check_is_clean_with_nine_passing_records(demo_ledger, run):
    code, out, err = run("check", "--ledger", str(demo_ledger))
    assert code == 0
    assert len([line for line in out.splitlines() if line.startswith("PASS")]) == 9
    assert "== 9 PASS, 0 FAIL, 0 MISS, 0 UNMAPPED, 1 WAIVED — OK ==" in err


def test_demo_scan_strict_is_clean(demo_ledger, run):
    code, out, err = run("scan", "--ledger", str(demo_ledger), "--strict")
    assert code == 0
    assert "UNMAPPED" not in out
    assert "== 9 PASS, 0 FAIL, 0 MISS, 0 UNMAPPED, 1 WAIVED — OK ==" in err


def test_demo_json_summary_matches_the_documented_shape(demo_ledger, run):
    code, out, err = run("check", "--ledger", str(demo_ledger), "--json")
    assert code == 0
    payload = json.loads(out)
    assert payload["summary"] == {
        "PASS": 9, "FAIL": 0, "MISS": 0, "UNMAPPED": 0, "WAIVED": 1, "verdict": "OK"
    }
    assert payload["warnings"] == []
    assert payload["waived"] == {"confidence-level": 1}
    assert {r["name"] for r in payload["records"]} == {
        "headline-improvement", "latency-row#g1", "latency-row#g2",
        "latency-row#g3", "latency-row#g4", "hit-rate", "seed-count",
    }


def test_demo_emitted_numbers_tex_is_in_sync(demo_ledger, run):
    code, out, err = run("generate", "--ledger", str(demo_ledger), "--check")
    assert code == 0
    assert "numbers.tex is in sync" in err


def test_demo_check_catches_a_drifted_number(demo_ledger, tmp_path, run):
    import shutil

    copy = tmp_path / "demo"
    shutil.copytree(demo_ledger.parent, copy)
    paper = copy / "paper.tex"
    paper.write_text(
        paper.read_text(encoding="utf-8").replace("hit rate of 94.2", "hit rate of 96.1"),
        encoding="utf-8",
    )
    code, out, err = run("check", "--ledger", str(copy / "claims.yaml"))
    assert code == 1
    assert "FAIL     hit-rate paper.tex:12 claimed=96.1 expected=94.218" in out
    assert "== 8 PASS, 1 FAIL, 0 MISS, 0 UNMAPPED, 1 WAIVED — FAIL ==" in err
