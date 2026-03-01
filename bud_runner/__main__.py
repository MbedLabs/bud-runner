"""
Entry point for running bud_runner as a module.

Usage:
    python -m bud_runner add_test_run --test-case-list MyTests.LIST
    python -m bud_runner run_tests --test-case-list MyTests.LIST
    python -m bud_runner register --username runner1
"""

from bud_runner.cli import main

if __name__ == "__main__":
    main()
