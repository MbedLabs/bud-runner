"""
bud_runner - CLI tool for test execution and CI/CD integration.

A command-line interface for:
- Running test suites
- Registering runners with the Bud backend
- Creating test runs
- Generating JUnit XML reports


Usage:
    python -m bud_runner add_test_run --test-case-list MyTests.TEST_LIST
    python -m bud_runner run_tests --test-suite-name "XYZ Tests"
    python -m bud_runner register --username runner1 --token xxx

Copyright (c) 2026 EmbedLabs
"""

from pathlib import Path

from bud_runner.cli import app


def _get_version():
    """Reads version from pyproject.toml."""
    try:
        pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
        if pyproject_path.exists():
            for line in pyproject_path.read_text().splitlines():
                if line.startswith("version = "):
                    return line.split("=")[1].strip().strip('"')
    except Exception:
        pass
    return "0.4.6"


__version__ = _get_version()
__author__ = "EmbedLabs"
__email__ = "dev@embedlabs.net"

__all__ = ["app"]
