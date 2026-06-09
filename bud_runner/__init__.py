"""
bud_runner - CLI tool for test execution and CI/CD integration.

A command-line interface for:
- running test suites
- registering runners with the Bud backend
- creating test runs
- generating JUnit XML reports

Usage:
    python -m bud_runner add-test-run --test-case-list MyTests.TEST_LIST
    python -m bud_runner run-tests --test-case-list MyTests.TEST_LIST
    python -m bud_runner register --username runner1

Copyright (c) 2026 EmbedLabs
"""

from importlib.metadata import version

from bud_runner.cli import app

def _get_version():
    """Resolve package version from installed metadata."""
    try:
        return version("bud-runner")
    except Exception:
        return "unknown"


__version__ = _get_version()
__author__ = "EmbedLabs"
__email__ = "dev@embedlabs.net"

__all__ = ["app"]
