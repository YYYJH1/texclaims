"""The README quotes real output, and this is what keeps that true.

A tool whose argument is "stop hand-copying numbers" should not hand-copy its
own terminal output into its landing page.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "demo"

_QUICKSTART_RE = re.compile(
    r"\$ texclaims check --ledger claims\.yaml\n(?P<body>.*?)\n(?P<summary>== .*? ==)\n",
    re.S,
)


def _run(*args: str, cwd: Path = DEMO) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "texclaims.cli", *args],
        cwd=cwd, capture_output=True, text=True,
        env={"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin"},
    )


@pytest.fixture
def demo_runs(tmp_path):
    results = {"clean": _run("check", "--ledger", "claims.yaml")}
    edits = {
        "headline": ("FastCache improves end-to-end throughput by 12.7",
                     "FastCache improves end-to-end throughput by 13.7"),
        "scan": ("All intervals use", "Throughput reached 8123 QPS. All intervals use"),
    }
    for name, (old, new) in edits.items():
        work = tmp_path / name
        shutil.copytree(DEMO, work)
        paper = work / "paper.tex"
        text = paper.read_text(encoding="utf-8")
        assert text.count(old) == 1
        paper.write_text(text.replace(old, new), encoding="utf-8")
        args = ["scan", "--strict"] if name == "scan" else ["check"]
        results[name] = _run(*args, "--ledger", "claims.yaml", cwd=work)
    assert {name: r.returncode for name, r in results.items()} == {
        "clean": 0, "headline": 1, "scan": 1}
    return results


def test_readme_scan_strict_matches_real_output(demo_runs):
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "insert `Throughput reached 8123 QPS. ` immediately" in text
    assert "before `All intervals use`" in text
    block = re.search(
        r"```console\n\$ texclaims scan --ledger claims\.yaml --strict\n(.*?)\n```",
        text, re.S,
    )
    assert block, "the README no longer quotes the strict scan example"
    result = demo_runs["scan"]
    assert result.returncode == 1
    # The README explicitly omits the preceding PASS lines. Everything it
    # does quote must match the edited manuscript, including line and snippet.
    produced = [line for line in result.stdout.splitlines()
                if not line.startswith("PASS ")] + result.stderr.splitlines()
    assert block.group(1).splitlines() == produced


@pytest.mark.parametrize("page", ["README.md", "README.zh-CN.md"])
def test_readme_headline_failure_matches_real_output(page, demo_runs):
    """The opening example claims a specific failure. Reproduce it exactly."""
    result = demo_runs["headline"]
    assert result.returncode == 1

    readme = (ROOT / page).read_text(encoding="utf-8")
    hero = readme.split("\n## ", 2)[1]  # the opening example section
    quoted = [l for l in hero.splitlines()
              if l.startswith(("PASS ", "FAIL ", "MISS ", "UNMAPPED ", "WARN ", "== "))]
    assert quoted, "the opening example no longer quotes any output"
    produced = result.stdout.splitlines() + result.stderr.splitlines()
    for line in quoted:
        assert line in produced, f"{page} quotes a line the tool does not print: {line}"
    exit_code = re.search(r"\$ echo \$\?\n(\d+)", hero)
    if exit_code:
        assert int(exit_code.group(1)) == result.returncode


def test_readme_quickstart_matches_real_output():
    quoted = _QUICKSTART_RE.search((ROOT / "README.md").read_text(encoding="utf-8"))
    assert quoted, "the README no longer contains a quickstart block to check"
    result = _run("check", "--ledger", "claims.yaml")
    assert result.returncode == 0
    assert quoted.group("body").strip().split("\n") == result.stdout.strip().split("\n")
    assert quoted.group("summary").strip() == result.stderr.strip()


def test_readme_json_summary_matches_real_output():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    block = re.search(
        r"```console\n\$ texclaims check --json \| jq -c '\.summary'\n(.*?)\n```",
        text, re.S,
    )
    assert block, "the README no longer quotes the compact JSON summary"
    # jq is an optional way to view the output, not a test dependency. Parsing
    # the documented JSON also catches a missing or invented summary field.
    expected = json.loads(block.group(1))
    result = _run("check", "--ledger", "claims.yaml", "--json")
    assert result.returncode == 0
    assert expected == json.loads(result.stdout)["summary"]


_COUNT_RE = re.compile(r"pytest\s+#\s*(\d+) tests")


@pytest.mark.parametrize("page", ["README.md", "README.zh-CN.md"])
def test_readme_quotes_only_output_the_tool_produces(page, demo_runs):
    """Both pages, not just the English one: quoting output the tool does not
    print is exactly the failure this project exists to catch."""
    text = (ROOT / page).read_text(encoding="utf-8")
    quoted = []
    for block in re.findall(r"```console\n(.*?)\n```", text, re.S):
        if block.startswith("$ texclaims check --json | jq -c '.summary'\n"):
            result = _run("check", "--ledger", "claims.yaml", "--json")
            assert result.returncode == 0
            assert json.loads(block.split("\n", 1)[1]) == json.loads(result.stdout)["summary"]
        else:
            quoted.extend(line for line in block.splitlines()
                          if line and not line.startswith("$ "))
    assert quoted, f"{page} quotes no output at all"
    produced = {line for result in demo_runs.values()
                for line in (result.stdout + result.stderr).splitlines()}
    produced.update(str(result.returncode) for result in demo_runs.values())
    # Failures need their documented edits, not an exemption from this check.
    # A fabricated FAIL, MISS or UNMAPPED line must fail just like a stale PASS.
    for line in quoted:
        assert line in produced, f"{page} quotes a line the tool does not print: {line}"


def test_readme_test_count_matches_the_suite(collected_test_count):
    """The tool's whole thesis is that a hand-copied number goes stale. Its own
    README quoted 475 while the suite had grown to 499."""
    match = _COUNT_RE.search((ROOT / "README.md").read_text(encoding="utf-8"))
    assert match, "the README no longer states a test count"
    assert int(match.group(1)) == collected_test_count


@pytest.mark.parametrize("page", ["README.md", "README.zh-CN.md"])
def test_scicoqa_claim_links_to_the_cited_survey(page):
    text = (ROOT / page).read_text(encoding="utf-8")
    target = ("https://github.com/YYYJH1/texclaims/blob/main/docs/prior-art.md"
              "#2-post-hoc-checking--read-the-paper-judge-the-numbers")
    assert f"[SciCoQA]({target})" in text
    survey = (ROOT / "docs" / "prior-art.md").read_text(encoding="utf-8")
    section = survey.split("## 2. Post-hoc checking — read the paper, judge the numbers\n")[1]
    section = section.split("\n## ", 1)[0]
    # The README's quantitative comparison must lead to a public, versioned
    # citation; an unlinked benchmark name cannot substantiate it.
    assert "[SciCoQA](https://arxiv.org/abs/2601.12910v3)" in section


@pytest.mark.parametrize("page", ["README.md", "README.zh-CN.md"])
def test_readme_skill_install_preserves_the_named_directory(page, tmp_path):
    text = (ROOT / page).read_text(encoding="utf-8")
    assert "`skills/texclaims/`" in text
    assert "`.claude/skills/`" in text
    target = "https://github.com/YYYJH1/texclaims/blob/main/skills/texclaims/SKILL.md"
    assert f"({target})" in text
    # Copying SKILL.md alone loses the named directory that skill discovery
    # needs. Execute the documented directory copy to keep that layout intact.
    installed = tmp_path / ".claude" / "skills" / "texclaims"
    shutil.copytree(ROOT / "skills" / "texclaims", installed)
    assert (installed / "SKILL.md").is_file()


def test_full_schema_is_a_visible_linkable_heading():
    text = (ROOT / "docs" / "ledger.md").read_text(encoding="utf-8")
    assert "\n## Full schema (version 1)\n\n```yaml\nversion: 1" in text
    assert "<summary>" not in text
    assert "<details>" not in text


def test_python_classifiers_match_the_ci_matrix_in_both_directions():
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        # Python 3.10 lacks tomllib; pytest already requires tomli there.
        # Reuse it so the metadata guard runs on the oldest supported Python.
        import tomli as tomllib

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    classifiers = {
        match.group(1) for entry in project["classifiers"]
        if (match := re.fullmatch(r"Programming Language :: Python :: (\d+\.\d+)", entry))
    }
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    tested = set(workflow["jobs"]["test"]["strategy"]["matrix"]["python-version"])
    assert classifiers == tested
    # PyPI wheel tags for Python 3.10+, checked in September 2026. Keep them
    # local: testing an install floor must not depend on PyPI being reachable.
    # A new floor needs its own verified entry, not an assumed future wheel.
    wheel_pythons = {
        "6.0": {f"3.{minor}" for minor in range(10, 12)},
        "6.0.1": {f"3.{minor}" for minor in range(10, 13)},
        "6.0.2": {f"3.{minor}" for minor in range(10, 14)},
        "6.0.3": {f"3.{minor}" for minor in range(10, 15)},
    }
    assert len(project["dependencies"]) == 1
    requirement = re.fullmatch(r"PyYAML>=(\d+(?:\.\d+)+)", project["dependencies"][0])
    assert requirement, "keep PyYAML as the only runtime dependency, with a floor and no ceiling"
    floor = requirement.group(1)
    assert floor in wheel_pythons, f"verify and record the wheel tags for PyYAML {floor}"
    missing = classifiers - wheel_pythons[floor]
    assert not missing, f"PyYAML {floor} lacks wheels for {missing}"


def test_version_is_stated_once():
    """The version lived in three hand-kept copies; pyproject now derives it
    from __init__, and this keeps CITATION.cff honest too."""
    from texclaims import __version__
    cff = yaml.safe_load((ROOT / "CITATION.cff").read_text(encoding="utf-8"))
    assert cff["version"] == __version__


@pytest.mark.parametrize("name", ["ci.yml", "publish.yml"])
def test_workflow_actions_use_full_commit_pins_with_version_comments(name):
    text = (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    refs = [step["uses"] for job in workflow["jobs"].values()
            for step in job.get("steps", []) if "uses" in step]
    assert refs
    for ref in refs:
        # Mutable tags can change the code that receives the publishing job's
        # OIDC permission. Keep full pins, with a readable version for updates.
        assert re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", ref), ref
        assert re.search(re.escape(ref) + r"\s+# v\d+\.\d+\.\d+\s*$", text, re.M), ref


def test_changelog_has_the_current_version_heading_and_link():
    from texclaims import __version__
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## [{__version__}]" in text
    assert f"\n[{__version__}]:" in text
