"""Mock test classes for TestExecutor integration tests."""

from __future__ import annotations

import time


class FastPassTest:
    def run(self):
        return True


class SlowTest:
    def run(self):
        time.sleep(8)
        return True


class FailingTest:
    def run(self):
        raise RuntimeError("boom")


class LargeResultTest:
    def run(self):
        return True

    def get_results(self):
        # Large payload to fill the multiprocessing queue buffer if read order is wrong.
        return [
            {
                "method_name": "bud_huge",
                "passed": True,
                "assertions": [],
                "duration_seconds": 0.01,
                "metadata": {"blob": "x" * 400_000},
            }
        ]


MOCK_TEST_LIST = [
    "tests.fixtures.mock_tests.FastPassTest",
    "tests.fixtures.mock_tests.FastPassTest",
]
