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

from bud_runner.cli import app
from bud_runner.versioning import read_package_version

__version__ = read_package_version()
__author__ = "Amine El Omari"
__email__ = "dev@embedlabs.net"

__all__ = ["app"]
