"""Shared fixtures: build a throwaway project tree from inline pieces."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

DEMO = Path(__file__).resolve().parents[1] / "examples" / "demo"


@pytest.fixture
def project(tmp_path):
    """Return a builder that writes a ledger, documents, and artifacts.

    Usage::

        ledger_path = project(
            documents={"paper.tex": "..."},
            artifacts={"results/summary.json": {"x": 1}},
            ledger={"sources": {"summary": "results/summary.json"},
                    "claims": [...]},
        )
    """

    def build(documents: dict[str, str], artifacts: dict, ledger: dict) -> Path:
        for name, text in documents.items():
            target = tmp_path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        for name, payload in artifacts.items():
            target = tmp_path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(payload, str):  # raw text (CSV and friends)
                target.write_text(payload, encoding="utf-8")
            else:
                target.write_text(json.dumps(payload), encoding="utf-8")
        full = {"version": 1, "documents": list(documents), **ledger}
        path = tmp_path / "claims.yaml"
        path.write_text(yaml.safe_dump(full, sort_keys=False), encoding="utf-8")
        return path

    return build


@pytest.fixture
def demo_ledger():
    """Path to the committed demo ledger (used as a golden end-to-end case)."""
    return DEMO / "claims.yaml"


_COLLECTED = {}


def pytest_collection_modifyitems(items):
    """Record the real suite size so the README's own number can be audited."""
    _COLLECTED["count"] = len(items)


@pytest.fixture
def collected_test_count():
    return _COLLECTED.get("count")
