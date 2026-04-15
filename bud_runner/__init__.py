"""
bud_runner - CLI tool for test execution and CI/CD integration.

A command-line interface for:
- Running test suites
- Registering runners with bud.embedlabs.de
- Creating test runs
- Syncing test cases to Bloom ALM
- Generating JUnit XML reports

Backend: https://bud.embedlabs.de/
ALM: https://bloom.embedlabs.de/ (Bloom)

Usage:
    python -m bud_runner add_test_run --test-case-list MyTests.TEST_LIST
    python -m bud_runner run_tests --test-suite-name "HIL Tests"
    python -m bud_runner register --username runner1 --token xxx
    python -m bud_runner sync_test_cases --project bms-project

Copyright (c) 2025 EmbedLabs
"""

from bud_runner.cli import app

__version__ = "0.1.0"
__author__ = "EmbedLabs"
__email__ = "dev@embedlabs.de"

__all__ = ["app"]
