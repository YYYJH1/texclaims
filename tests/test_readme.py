"""The README quotes real output, and this is what keeps that true.

A tool whose argument is "stop hand-copying numbers" should not hand-copy its
own terminal output into its landing page.
"""

from __future__ import annotations

import re
import shutil

import pytest
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "demo"

_QUICKSTART_RE = re.compile(
    r"\$ texclaims check --ledger claims\.yaml\n(?P<body>.*?)\n(?P<summary>== .*? ==)\n",
    re.S,
)


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "texclaims.cli", *args],
        cwd=DEMO, capture_output=True, text=True,
        env={"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin"},
    )


def test_readme_headline_failure_matches_real_output(tmp_path):
    """The opening example claims a specific failure. Reproduce it exactly."""
    work = tmp_path / "demo"
    shutil.copytree(DEMO, work)
    paper = work / "paper.tex"
    # Only the Section V copy, exactly as the README's diff shows it.
    paper.write_text(paper.read_text(encoding="utf-8").replace(
        "FastCache improves end-to-end throughput by 12.7",
        "FastCache improves end-to-end throughput by 13.7"), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "texclaims.cli", "check", "--ledger", "claims.yaml"],
        cwd=work, capture_output=True, text=True,
        env={"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 1

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    hero = readme.split("\n## ", 2)[1]  # the opening example section
    quoted = [l for l in hero.splitlines()
              if l.startswith(("PASS ", "FAIL ", "== "))]
    assert quoted, "the opening example no longer quotes any output"
    produced = result.stdout.splitlines() + result.stderr.splitlines()
    for line in quoted:
        assert line in produced, f"README quotes a line the tool does not print: {line}"


def test_readme_quickstart_matches_real_output():
    quoted = _QUICKSTART_RE.search((ROOT / "README.md").read_text(encoding="utf-8"))
    assert quoted, "the README no longer contains a quickstart block to check"
    result = _run("check", "--ledger", "claims.yaml")
    assert result.returncode == 0
    assert quoted.group("body").strip().split("\n") == result.stdout.strip().split("\n")
    assert quoted.group("summary").strip() == result.stderr.strip()


_COUNT_RE = re.compile(r"pytest\s+#\s*(\d+) tests")


@pytest.mark.parametrize("page", ["README.md", "README.zh-CN.md"])
def test_readme_quotes_only_output_the_tool_produces(page):
    """Both pages, not just the English one: quoting output the tool does not
    print is exactly the failure this project exists to catch."""
    text = (ROOT / page).read_text(encoding="utf-8")
    quoted = [l for l in text.splitlines()
              if l.startswith(("PASS ", "FAIL ", "UNMAPPED ", "== "))]
    assert quoted, f"{page} quotes no output at all"
    result = _run("check", "--ledger", "claims.yaml")
    produced = set(result.stdout.splitlines()) | set(result.stderr.splitlines())
    # Only the lines a clean run produces; the pages also quote a tampered run
    # and a scan that finds an unmapped number, which this fixture is not in.
    for line in quoted:
        if line.startswith("PASS ") or line == "== 9 PASS, 0 FAIL, 0 MISS, 0 UNMAPPED — OK ==":
            assert line in produced, f"{page} quotes a line the tool does not print: {line}"


def test_readme_test_count_matches_the_suite(collected_test_count):
    """The tool's whole thesis is that a hand-copied number goes stale. Its own
    README quoted 475 while the suite had grown to 499."""
    match = _COUNT_RE.search((ROOT / "README.md").read_text(encoding="utf-8"))
    assert match, "the README no longer states a test count"
    assert int(match.group(1)) == collected_test_count


def test_version_is_stated_once():
    """The version lived in three hand-kept copies; pyproject now derives it
    from __init__, and this keeps CITATION.cff honest too."""
    import yaml as _yaml
    from texclaims import __version__
    cff = _yaml.safe_load((ROOT / "CITATION.cff").read_text(encoding="utf-8"))
    assert cff["version"] == __version__
