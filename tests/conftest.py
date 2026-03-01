"""Shared pytest fixtures for bud_runner tests."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure bud_runner package and tests.fixtures are importable in spawned workers.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
