from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ORG = os.environ.get("PACKAGE_ORG", "")
MAINTAINER = os.environ.get("ORG_MAINTAINER", "")
needs_org = pytest.mark.skipif(not ORG, reason="PACKAGE_ORG is not set")
needs_maintainer = pytest.mark.skipif(not MAINTAINER, reason="ORG_MAINTAINER is not set")


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_the_declared_version_is_a_release_number() -> None:
    """Checks that the declared version is a release number (major.minor.patch)."""
    project = _pyproject()["project"]

    assert re.fullmatch(r"\d+\.\d+\.\d+", project["version"]), project["version"]


def test_release_metadata_is_ready_for_1_0_0() -> None:
    project = _pyproject()["project"]

    assert project["authors"][0] == {"name": "EmbedLabs", "email": "dev@embedlabs.net"}
    assert len(project["authors"]) == 2
    assert project["maintainers"] == [{"name": "EmbedLabs", "email": "dev@embedlabs.net"}]
    assert project["urls"] == {
        "Homepage": "https://embedlabs.net",
        "Documentation": "https://embedlabs.net/docs",
        "Support": "https://embedlabs.net",
    }
    assert project["license"] == {"text": "AGPL-3.0-only"}
    assert "Development Status :: 5 - Production/Stable" in project["classifiers"]


def test_the_changelog_has_an_entry_for_the_declared_version() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    version = _pyproject()["project"]["version"]

    assert f"## [{version}]" in changelog


def test_readme_calls_out_self_hosted_ci_usage() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "self-hosted CI" in readme


def test_readme_has_no_relative_markdown_links_that_break_on_pypi() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    relative_links = re.findall(r"\[[^]]+\]\((?!https?://|mailto:|#)[^)]+\)", readme)

    assert relative_links == []


@needs_org
def test_the_package_names_its_org() -> None:
    """Checks that the package metadata names the organisation in PACKAGE_ORG first and as
    its maintainer."""
    project = _pyproject()["project"]

    assert project["authors"][0]["name"] == ORG
    assert [m["name"] for m in project["maintainers"]] == [ORG]


@needs_maintainer
def test_the_package_names_its_maintainer() -> None:
    """Checks that the package metadata names the person in ORG_MAINTAINER after the
    organisation."""
    assert _pyproject()["project"]["authors"][1:] == [{"name": MAINTAINER}]


@needs_maintainer
def test_readme_credits_its_maintainer() -> None:
    """Checks that the README credits the person in ORG_MAINTAINER."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert f"Creator: {MAINTAINER}" in readme
