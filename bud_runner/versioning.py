"""Version resolution helpers for bud_runner."""

from __future__ import annotations

from importlib.metadata import version
from pathlib import Path


def read_package_version() -> str:
    """Resolve the package version from installed metadata or local pyproject."""
    try:
        return version("bud-runner")
    except Exception:
        pass

    try:
        pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
        for line in pyproject_path.read_text(encoding="utf-8").splitlines():
            if line.startswith('version = "'):
                return line.split('"', 2)[1]
    except Exception:
        pass

    return "unknown"
