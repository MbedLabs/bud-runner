"""Tests for TestExecutor timeouts, queue ordering, and interrupt handling."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from bud_runner.test_executor import TestExecutor as BudTestExecutor
from bud_runner.test_executor import TestRunResult as BudTestRunResult
from tests.fixtures import mock_tests


@pytest.fixture
def executor():
    return BudTestExecutor(test_timeout=10, suite_timeout=60)


def test_per_test_timeout_kills_slow_worker():
    short_executor = BudTestExecutor(test_timeout=2, suite_timeout=60)
    result = short_executor.run_test_class(mock_tests.SlowTest)

    assert result.passed is False
    assert result.error_message is not None
    assert (
        "timed out" in result.error_message.lower() or "Failed to retrieve" in result.error_message
    )


def test_suite_timeout_skips_remaining_tests():
    executor = BudTestExecutor(test_timeout=30, suite_timeout=0)
    results = executor.run_test_list(
        "tests.fixtures.mock_tests.MOCK_TEST_LIST",
        continue_on_error=True,
    )

    assert len(results) >= 1
    truncated = [r for r in results if r.test_class == "__suite_truncated__"]
    assert truncated, "expected suite truncation marker"
    assert "suite timeout" in (truncated[0].error_message or "").lower()


def test_large_queue_payload_completes_without_deadlock(executor):
    """Parent reads queue before join; large payloads must not hang the suite."""
    start = time.monotonic()
    result = executor.run_test_class(mock_tests.LargeResultTest)
    elapsed = time.monotonic() - start

    assert elapsed < executor._test_timeout, "large payload run should not hang"
    assert result.passed is True
    assert result.test_class == "LargeResultTest"


def test_queue_get_called_before_process_join():
    """Regression guard for queue-before-join ordering in run_test_class."""
    join_calls: list[float] = []
    get_calls: list[float] = []

    class RecordingQueue:
        def get(self, timeout=None):
            get_calls.append(time.monotonic())
            return {
                "test_class": "StubTest",
                "passed": True,
                "method_results": [],
                "duration_seconds": 0.0,
                "error_message": None,
                "start_time": None,
                "end_time": None,
                "metadata": {},
            }

    class RecordingProcess:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

        def join(self, timeout=None):
            join_calls.append(time.monotonic())

        def is_alive(self):
            return False

        @property
        def exitcode(self):
            return 0

    mock_ctx = MagicMock()
    mock_ctx.Queue.return_value = RecordingQueue()
    mock_ctx.Process.return_value = RecordingProcess()

    with patch("bud_runner.test_executor.multiprocessing.get_context", return_value=mock_ctx):
        executor = BudTestExecutor(test_timeout=5)
        result = executor.run_test_class(mock_tests.FastPassTest)

    assert result.passed is True
    assert get_calls, "queue.get should run"
    assert join_calls, "process.join should run"
    assert get_calls[0] < join_calls[0], "queue.get must happen before process.join"


def test_should_stop_interrupts_suite_before_next_test(executor):
    call_count = {"n": 0}

    def stop_after_first():
        call_count["n"] += 1
        return call_count["n"] > 1

    results = executor.run_test_list(
        "tests.fixtures.mock_tests.MOCK_TEST_LIST",
        continue_on_error=True,
        should_stop=stop_after_first,
    )

    interrupted = [r for r in results if r.test_class == "__suite_interrupted__"]
    assert interrupted
    assert "interrupted" in (interrupted[0].error_message or "").lower()
    assert len(results) < 2 + len(mock_tests.MOCK_TEST_LIST)


def test_fast_test_passes(executor):
    result = executor.run_test_class(mock_tests.FastPassTest)
    assert result.passed is True
    assert result.test_class == "FastPassTest"


def test_failing_test_returns_failure(executor):
    result = executor.run_test_class(mock_tests.FailingTest)
    assert result.passed is False
    assert result.error_message is not None


def test_test_run_result_roundtrip():
    original = BudTestRunResult(
        test_class="X",
        passed=True,
        duration_seconds=1.5,
    )
    restored = BudTestRunResult.from_dict(original.to_dict())
    assert restored.test_class == "X"
    assert restored.passed is True
