from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_release_metadata_is_ready_for_1_0_0() -> None:
    project = _pyproject()["project"]

    assert project["version"] == "1.0.1"
    assert project["authors"] == [
        {"name": "EmbedLabs", "email": "dev@embedlabs.net"},
        {"name": "Amine El Omari"},
    ]
    assert project["maintainers"] == [{"name": "EmbedLabs", "email": "dev@embedlabs.net"}]
    assert project["urls"] == {
        "Homepage": "https://embedlabs.net",
        "Documentation": "https://embedlabs.net/docs",
        "Support": "https://embedlabs.net",
    }
    assert project["license"] == {"text": "AGPL-3.0-only"}
    assert "Development Status :: 5 - Production/Stable" in project["classifiers"]


def test_changelog_has_1_0_0_entry() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "## [1.0.1]" in changelog


def test_readme_credits_creator() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "Creator: Amine El Omari" in readme


def test_readme_calls_out_self_hosted_ci_usage() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "self-hosted CI" in readme


def test_readme_has_no_relative_markdown_links_that_break_on_pypi() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    relative_links = re.findall(r"\[[^]]+\]\((?!https?://|mailto:)[^)]+\)", readme)

    assert relative_links == []
