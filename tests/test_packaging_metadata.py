from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_release_metadata_is_ready_for_1_0_0() -> None:
    project = _pyproject()["project"]

    assert project["version"] == "1.0.0"
    assert project["license"] == {"text": "AGPL-3.0-only"}
    assert "Development Status :: 5 - Production/Stable" in project["classifiers"]


def test_changelog_has_1_0_0_entry() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "## [1.0.0]" in changelog
