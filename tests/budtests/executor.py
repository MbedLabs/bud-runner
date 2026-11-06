"""TestExecutor: selections, timeouts, queue ordering, interrupts and results, with the fixture suites
of tests/fixtures/mock_tests.py and a mocked multiprocessing context."""

import sys
import time
from types import ModuleType
from unittest.mock import MagicMock, patch

from budtestlibrary import BudTestCase, parameterized

from bud_runner.test_executor import TestExecutor as BudTestExecutor
from bud_runner.test_executor import TestRunResult as BudTestRunResult
from tests.budtests.config import Executor as c
from tests.budtests.parameters import Executor as p
from tests.fixtures import mock_tests


class Executor(BudTestCase):
    """What TestExecutor runs, stops and reports."""

    def executor(self) -> BudTestExecutor:
        """An executor with the default per-test and suite timeouts of the suite."""
        return BudTestExecutor(test_timeout=c.TEST_TIMEOUT, suite_timeout=c.SUITE_TIMEOUT)

    @parameterized(p.WITH_VALID_CASE)
    def bud_an_unavailable_selected_case_refuses_the_selection(self, has_valid_case):
        """A selection naming a missing case raises ImportError naming it and runs nothing."""
        module = ModuleType(c.SELECTION_MODULE)
        module.CASES = ([c.VALID_CASE] if has_valid_case else []) + [c.MISSING_CASE]
        executor = self.executor()
        raised = ""
        with patch.dict(sys.modules, {c.SELECTION_MODULE: module}):
            with patch.object(executor, "run_test_class") as execute:
                try:
                    executor.run_test_list(c.SELECTION)
                except ImportError as error:
                    raised = str(error)
        self.assertIn(member=c.MISSING_CASE, container=raised, msg="the ImportError names the missing case")
        self.assertEqual(execute.call_count, p.NONE, "no case runs")

    def bud_the_per_test_timeout_ends_a_slow_worker(self):
        """A test running past its timeout fails with a timeout error."""
        result = BudTestExecutor(test_timeout=c.SHORT_TEST_TIMEOUT, suite_timeout=c.SUITE_TIMEOUT).run_test_class(
            mock_tests.SlowTest
        )
        self.assertEqual(result.passed, False, "the slow test fails")
        error = (result.error_message or "").lower()
        self.assertTrue(any(text in error for text in p.TIMED_OUT), f"the error names the timeout: {error!r}")

    def bud_the_suite_timeout_skips_the_remaining_tests(self):
        """A suite out of time ends with a truncation marker naming the suite timeout."""
        results = BudTestExecutor(test_timeout=c.LONG_TEST_TIMEOUT, suite_timeout=c.NO_SUITE_TIME).run_test_list(
            c.FIXTURE_LIST, continue_on_error=True
        )
        truncated = [r for r in results if r.test_class == p.TRUNCATED]
        self.assertTrue(truncated, "a truncation marker is reported", abort_on_fail=True)
        self.assertIn(
            member=p.SUITE_TIMEOUT_TEXT,
            container=(truncated[0].error_message or "").lower(),
            msg="the marker names the suite timeout",
        )

    def bud_a_large_payload_completes_without_deadlock(self):
        """A result too large for the queue buffer arrives within the test timeout."""
        executor = self.executor()
        start = time.monotonic()
        result = executor.run_test_class(mock_tests.LargeResultTest)
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, c.TEST_TIMEOUT, "the large payload arrives within the timeout")
        self.assertEqual(result.passed, True, "the test passes")
        self.assertEqual(result.test_class, p.LARGE, "the result names the test")

    def bud_the_queue_is_read_before_the_worker_is_joined(self):
        """run_test_class reads the result queue before it joins the worker process."""
        joins: list[float] = []
        gets: list[float] = []

        class RecordingQueue:
            """A queue double that records when it is read."""

            def get(self, timeout=None):
                """Record the read and answer the stub result."""
                gets.append(time.monotonic())
                return p.STUB_RESULT

        class RecordingProcess:
            """A process double that records when it is joined."""

            exitcode = 0

            def __init__(self, *args, **kwargs):
                pass

            def start(self):
                """Start nothing."""

            def join(self, timeout=None):
                """Record the join."""
                joins.append(time.monotonic())

            def is_alive(self):
                """Never alive."""
                return False

        context = MagicMock()
        context.Queue.return_value = RecordingQueue()
        context.Process.return_value = RecordingProcess()
        with patch(c.CONTEXT_TARGET, return_value=context):
            result = BudTestExecutor(test_timeout=c.STUB_TEST_TIMEOUT).run_test_class(mock_tests.FastPassTest)
        self.assertEqual(result.passed, True, "the stub result passes")
        self.assertTrue(gets and joins, "the queue is read and the worker joined", abort_on_fail=True)
        self.assertLess(gets[0], joins[0], "the queue is read before the join")

    def bud_should_stop_interrupts_the_suite_before_the_next_test(self):
        """A stop request after the first test ends the suite with an interruption marker."""
        calls = {"n": 0}

        def stop_after_first():
            """Ask to stop from the second check on."""
            calls["n"] += 1
            return calls["n"] > 1

        results = self.executor().run_test_list(c.FIXTURE_LIST, continue_on_error=True, should_stop=stop_after_first)
        interrupted = [r for r in results if r.test_class == p.INTERRUPTED]
        self.assertTrue(interrupted, "an interruption marker is reported", abort_on_fail=True)
        self.assertIn(
            member=p.INTERRUPTED_TEXT,
            container=(interrupted[0].error_message or "").lower(),
            msg="the marker says interrupted",
        )
        self.assertLess(len(results), p.MARKERS + len(mock_tests.MOCK_TEST_LIST), "the remaining tests are not run")

    def bud_a_fast_test_passes(self):
        """A passing fixture test passes under its own name."""
        result = self.executor().run_test_class(mock_tests.FastPassTest)
        self.assertEqual(result.passed, True, "the test passes")
        self.assertEqual(result.test_class, p.FAST, "the result names the test")

    def bud_a_failing_test_returns_a_failure(self):
        """A failing fixture test fails with an error message."""
        result = self.executor().run_test_class(mock_tests.FailingTest)
        self.assertEqual(result.passed, False, "the test fails")
        self.assertTrue(result.error_message is not None, "the failure carries an error message")

    def bud_a_run_result_survives_its_dict_round_trip(self):
        """TestRunResult.from_dict(to_dict()) keeps the class and the outcome."""
        original = BudTestRunResult(test_class=p.ROUNDTRIP_CLASS, passed=True, duration_seconds=p.ROUNDTRIP_SECONDS)
        restored = BudTestRunResult.from_dict(original.to_dict())
        self.assertEqual(restored.test_class, p.ROUNDTRIP_CLASS, "the class survives")
        self.assertEqual(restored.passed, True, "the outcome survives")
