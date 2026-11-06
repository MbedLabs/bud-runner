"""Release metadata of the installed bud-runner distribution, its long description and the
changelog entry of its version."""

import importlib.metadata
import os
import re

import support
from budtestlibrary import BudTestCase

ORG = os.environ.get("PACKAGE_ORG", "")
MAINTAINER = os.environ.get("ORG_MAINTAINER", "")
ORG_EMAIL = ["EmbedLabs <dev@embedlabs.net>"]


def _metadata():
    """Return the core metadata of the installed bud-runner distribution."""
    return importlib.metadata.metadata("bud-runner")


def _long_description() -> str:
    """Return the installed distribution's long description (the README)."""
    metadata = _metadata()
    return metadata.get_payload() or metadata.get("Description") or ""


class PackagingMetadata(BudTestCase):
    """Version, authors, maintainers, URLs, license, classifier, README content and the changelog
    entry."""

    def bud_the_declared_version_is_a_release_number(self):
        """The installed version is major.minor.patch, and the version command prints it."""
        version = importlib.metadata.version("bud-runner")
        support.check_match(
            self,
            r"^\d+\.\d+\.\d+$",
            version,
            f"the installed bud-runner version {version} is a major.minor.patch release number",
            f"the installed bud-runner version {version!r} is not major.minor.patch",
        )
        done = support.Case("version").bud_runner("version")
        support.exits(self, done, 0, "bud-runner version")
        printed = done.out.strip()
        support.check(
            self,
            printed,
            f"bud_runner version {version}",
            f"bud-runner version prints the installed version: bud_runner version {version}",
            f"bud-runner version prints {printed!r}, not bud_runner version {version}",
        )

    def bud_release_metadata_is_ready_for_1_0_0(self):
        """Author, maintainer, project URLs, license and the production classifier in the installed
        metadata."""
        metadata = _metadata()
        authors = metadata.get_all("Author-email")
        support.check(
            self,
            authors,
            ORG_EMAIL,
            "the installed metadata names EmbedLabs <dev@embedlabs.net> as the author with an "
            "email",
            f"the installed metadata names {authors} as the authors with an email",
        )
        named = len(metadata.get_all("Author") or [])
        support.check(
            self,
            named,
            1,
            "the installed metadata names one more author without an email",
            f"the installed metadata names {named} authors without an email, not 1",
        )
        maintainers = metadata.get_all("Maintainer-email")
        support.check(
            self,
            maintainers,
            ORG_EMAIL,
            "the installed metadata names EmbedLabs <dev@embedlabs.net> as the only maintainer",
            f"the installed metadata names {maintainers} as the maintainers with an email",
        )
        plain = metadata.get_all("Maintainer")
        support.check(
            self,
            plain,
            None,
            "the installed metadata names no maintainer without an email",
            f"the installed metadata names {plain} as maintainers without an email",
        )
        urls = metadata.get_all("Project-URL")
        support.check(
            self,
            urls,
            [
                "Homepage, https://embedlabs.net",
                "Documentation, https://embedlabs.net/docs",
                "Support, https://embedlabs.net",
            ],
            "the installed metadata lists the Homepage, Documentation and Support URLs",
            f"the installed metadata lists the project URLs {urls}",
        )
        license_name = metadata.get("License")
        support.check(
            self,
            license_name,
            "AGPL-3.0-only",
            "the installed metadata declares the license AGPL-3.0-only",
            f"the installed metadata declares the license {license_name!r}, not AGPL-3.0-only",
        )
        support.check_in(
            self,
            "Development Status :: 5 - Production/Stable",
            metadata.get_all("Classifier"),
            "the installed metadata carries the classifier Development Status :: 5 - "
            "Production/Stable",
            "the installed metadata does not carry the Production/Stable classifier",
        )

    def bud_the_changelog_has_an_entry_for_the_declared_version(self):
        """CHANGELOG.md of the code base has a section for the installed version."""
        changelog = (support.REPO / "CHANGELOG.md").read_text(encoding="utf-8")
        version = importlib.metadata.version("bud-runner")
        support.check_in(
            self,
            f"## [{version}]",
            changelog,
            f"CHANGELOG.md has a section ## [{version}] for the installed version",
            f"CHANGELOG.md has no section ## [{version}] for the installed version",
        )

    def bud_readme_calls_out_self_hosted_ci_usage(self):
        """The long description says self-hosted CI."""
        support.check_in(
            self,
            "self-hosted CI",
            _long_description(),
            "the README in the installed metadata mentions self-hosted CI",
            "the README in the installed metadata does not mention self-hosted CI",
        )

    def bud_readme_has_no_relative_markdown_links_that_break_on_pypi(self):
        """The long description holds no relative Markdown link."""
        relative = re.findall(r"\[[^]]+\]\((?!https?://|mailto:|#)[^)]+\)", _long_description())
        support.check(
            self,
            relative,
            [],
            "the README in the installed metadata holds no relative Markdown link, which would "
            "break on PyPI",
            f"the README in the installed metadata holds the relative links {relative}",
        )

    def bud_the_package_names_its_org(self):
        """The organisation in PACKAGE_ORG is the author with an email and the only maintainer."""
        if not ORG:
            self.skipAssert("PACKAGE_ORG is not set")
            return
        metadata = _metadata()
        for field, role in (("Author-email", "author"), ("Maintainer-email", "only maintainer")):
            names = [e.split(" <")[0] for e in metadata.get_all(field) or []]
            support.check(
                self,
                names,
                [ORG],
                f"the organisation in PACKAGE_ORG is the {role} with an email",
                f"the {field} entries name {names}, not only the organisation in PACKAGE_ORG",
            )

    def bud_the_package_names_its_maintainer(self):
        """The person in ORG_MAINTAINER is the author named after the organisation."""
        if not MAINTAINER:
            self.skipAssert("ORG_MAINTAINER is not set")
            return
        authors = _metadata().get_all("Author")
        support.check(
            self,
            authors,
            [MAINTAINER],
            "the person in ORG_MAINTAINER is the author named after the organisation",
            f"the Author entries name {authors}, not only the person in ORG_MAINTAINER",
        )

    def bud_readme_credits_its_maintainer(self):
        """The long description credits the person in ORG_MAINTAINER."""
        if not MAINTAINER:
            self.skipAssert("ORG_MAINTAINER is not set")
            return
        support.check_in(
            self,
            f"Creator: {MAINTAINER}",
            _long_description(),
            "the README credits the person in ORG_MAINTAINER as Creator",
            "the README has no Creator line for the person in ORG_MAINTAINER",
        )
