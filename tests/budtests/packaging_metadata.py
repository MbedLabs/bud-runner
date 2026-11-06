"""Release metadata in pyproject.toml, the changelog entry of the declared version, README content,
and the organisation and maintainer named by PACKAGE_ORG and ORG_MAINTAINER."""

import os
import re
import tomllib

from budtestlibrary import BudTestCase

from tests.budtests.config import PackagingMetadata as c
from tests.budtests.parameters import PackagingMetadata as p


class PackagingMetadata(BudTestCase):
    """The package's published metadata and README."""

    def project(self) -> dict:
        """The [project] table of pyproject.toml."""
        return tomllib.loads((c.ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    def text(self, name: str) -> str:
        """A file of the checkout as text."""
        return (c.ROOT / name).read_text(encoding="utf-8")

    def bud_the_declared_version_is_a_release_number(self):
        """The version is major.minor.patch."""
        version = self.project()["version"]
        self.assertTrue(re.fullmatch(p.RELEASE_NUMBER, version) is not None, f"{version!r} is a release number")

    def bud_release_metadata_names_the_org_urls_license_and_classifier(self):
        """Authors, maintainers, URLs, license and the stable classifier."""
        project = self.project()
        self.assertEqual(project["authors"][0], p.ORG, "EmbedLabs is the first author")
        self.assertEqual(len(project["authors"]), p.AUTHORS, f"there are {p.AUTHORS} authors")
        self.assertEqual(project["maintainers"], [p.ORG], "EmbedLabs is the only maintainer")
        self.assertEqual(project["urls"], p.URLS, "the URLs are EmbedLabs'")
        self.assertEqual(project["license"], p.LICENSE, "the license is AGPL-3.0-only")
        self.assertIn(member=p.STABLE, container=project["classifiers"], msg="the package is marked stable")

    def bud_the_changelog_has_an_entry_for_the_declared_version(self):
        """CHANGELOG.md has a heading for the declared version."""
        entry = p.CHANGELOG_ENTRY.format(version=self.project()["version"])
        self.assertIn(member=entry, container=self.text("CHANGELOG.md"), msg=f"the changelog has {entry!r}")

    def bud_readme_calls_out_self_hosted_ci_usage(self):
        """The README mentions self-hosted CI."""
        self.assertIn(member=p.SELF_HOSTED, container=self.text("README.md"), msg=f"the README says {p.SELF_HOSTED!r}")

    def bud_readme_has_no_relative_markdown_links_that_break_on_pypi(self):
        """Every README link is absolute, mailto or an anchor."""
        links = re.findall(p.RELATIVE_LINK, self.text("README.md"))
        self.assertEqual(links, [], "the README holds no relative link")

    def bud_the_package_names_its_org(self):
        """The organisation in PACKAGE_ORG is the first author and the only maintainer."""
        org = os.environ.get(c.ORG_SETTING, "")
        if not org:
            self.skipAssert(f"{c.ORG_SETTING} is not set")
            return
        project = self.project()
        self.assertEqual(project["authors"][0]["name"], org, f"{org} is the first author")
        self.assertEqual([m["name"] for m in project["maintainers"]], [org], f"{org} is the only maintainer")

    def bud_the_package_names_its_maintainer(self):
        """The person in ORG_MAINTAINER is the author after the organisation."""
        maintainer = os.environ.get(c.MAINTAINER_SETTING, "")
        if not maintainer:
            self.skipAssert(f"{c.MAINTAINER_SETTING} is not set")
            return
        self.assertEqual(self.project()["authors"][1:], [{"name": maintainer}], f"{maintainer} follows the organisation")

    def bud_readme_credits_its_maintainer(self):
        """The README credits the person in ORG_MAINTAINER."""
        maintainer = os.environ.get(c.MAINTAINER_SETTING, "")
        if not maintainer:
            self.skipAssert(f"{c.MAINTAINER_SETTING} is not set")
            return
        credit = p.CREATOR.format(maintainer=maintainer)
        self.assertIn(member=credit, container=self.text("README.md"), msg=f"the README holds {credit!r}")
