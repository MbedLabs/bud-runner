"""
bud_runner

A command-line interface for:
- Running test suites
- Registering runners with your Bud instance
- Creating test runs
- Generating JUnit XML reports

Backend: https://<your-bud-instance-url>/

Usage:
    python -m bud_runner add-test-run --test-case-list MyTests.TEST_LIST
    python -m bud_runner run_tests --test-suite-name "Standard Test Suite"
    python -m bud_runner register --username runner1 --password secret

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
    return "0.3.4"

__version__ = _get_version()
__author__ = "EmbedLabs"
__email__ = "dev@embedlabs.de"

__all__ = ["app"]
