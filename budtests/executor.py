"""run-tests executing BudTestCase suites in worker processes: selection, per-test and suite
timeouts, large results, pass and fail."""

import os
import time

import support
from budtestlibrary import BudTestCase, parameterized

SUITE = '''"""Suites for the executor cases."""

import os
import time
from pathlib import Path

from budtestlibrary import BudTestCase


class PassTest(BudTestCase):
    """One passing step."""

    def bud_passes(self):
        """Pass."""
        self.assertTrue(True, msg="ok")


class MarkerTest(BudTestCase):
    """Writes ran.marker when it runs."""

    def bud_mark(self):
        """Write the marker."""
        Path("ran.marker").write_text("ran")
        self.assertTrue(True, msg="ran")


class SlowTest(BudTestCase):
    """Writes its process id, then sleeps 20 seconds."""

    def bud_sleep(self):
        """Sleep."""
        Path("slow.pid").write_text(str(os.getpid()))
        time.sleep(20)
        self.assertTrue(True, msg="woke")


class LargeTest(BudTestCase):
    """Records about 400 kB of check entries."""

    def bud_large(self):
        """Record 2000 checks with 200-character messages."""
        for number in range(2000):
            self.assertTrue(True, msg=f"{number:05d}" + "x" * 195)


class FailingSetupTest(BudTestCase):
    """setUpClass raises."""

    def setUpClass(self):
        """Fail before any step."""
        raise RuntimeError("boom")

    def bud_never(self):
        """Not reached."""
        self.assertTrue(True, msg="never")


ONE_MISSING = ["demo_exec.MarkerTest", "unavailable_station_suite.MissingCase"]
ONLY_MISSING = ["unavailable_station_suite.MissingCase"]
SLOW = ["demo_exec.SlowTest"]
TWO = ["demo_exec.PassTest", "demo_exec.PassTest"]
LARGE = ["demo_exec.LargeTest"]
PASS = ["demo_exec.PassTest"]
FAILING_SETUP = ["demo_exec.FailingSetupTest"]
'''


class Executor(BudTestCase):
    """What run-tests --no-upload runs and what its JUnit report says."""

    def _case(self, name):
        """Return a case with the executor suites written into it."""
        case = support.Case(name)
        case.write("demo_exec.py", SUITE)
        return case

    @parameterized(["ONLY_MISSING", "ONE_MISSING"])
    def bud_an_unavailable_selected_case_refuses_the_selection(self, test_list):
        """A list naming a class that does not import: exit 1, the class in the error, nothing
        runs."""
        case = self._case("missing")
        command = f"bud-runner run-tests --no-upload -t demo_exec.{test_list}"
        done = case.run_tests(f"demo_exec.{test_list}", "--no-upload")
        support.exits(self, done, 1, command)
        support.says(self, "unavailable_station_suite.MissingCase", done.err, command)
        support.check(
            self,
            (case.cwd / "ran.marker").exists(),
            False,
            f"{command} runs no class of the list: no ran.marker",
            f"{command} ran a class of the list although one class does not import",
        )

    def bud_per_test_timeout_kills_slow_worker(self):
        """--test-timeout 2 on a 20-second step: the class fails with the timeout reason and its
        worker is gone."""
        case = self._case("test-timeout")
        command = "bud-runner run-tests --no-upload --test-timeout 2 on a 20 s step"
        started = time.monotonic()
        done = case.run_tests("demo_exec.SLOW", "--no-upload", "--test-timeout", "2")
        elapsed = round(time.monotonic() - started, 1)
        support.exits(self, done, 1, command)
        support.check_less(
            self,
            elapsed,
            18,
            f"{command} ends after {elapsed} s, without waiting for the step to finish",
            f"{command} ends after {elapsed} s, as if it waited for the 20 s step",
        )
        errors = case.junit().findall("./testsuite[@name='SlowTest']/testcase/error")
        support.need(
            self,
            len(errors),
            1,
            "the JUnit report marks SlowTest with one error",
            f"the JUnit report marks SlowTest with {len(errors)} errors, not one",
        )
        message = errors[0].get("message") or ""
        support.says(self, "Test timed out after 2s", message, "the JUnit error of SlowTest")
        pid = int((case.cwd / "slow.pid").read_text())
        try:
            os.kill(pid, 0)
            state = "still running"
        except ProcessLookupError:
            state = "gone"
        support.check(
            self,
            state,
            "gone",
            f"the worker process {pid} of the timed-out step is gone",
            f"the worker process {pid} of the timed-out step is still running",
        )

    def bud_suite_timeout_skips_remaining_tests(self):
        """--suite-timeout 0 on two classes: exit 1 and the truncation entry in the report."""
        case = self._case("suite-timeout")
        command = "bud-runner run-tests --no-upload --suite-timeout 0 on two classes"
        done = case.run_tests("demo_exec.TWO", "--no-upload", "--suite-timeout", "0")
        support.exits(self, done, 1, command)
        errors = case.junit().findall("./testsuite[@name='__suite_truncated__']/testcase/error")
        support.need(
            self,
            len(errors),
            1,
            "the JUnit report has one __suite_truncated__ error entry",
            f"the JUnit report has {len(errors)} __suite_truncated__ error entries, not one",
        )
        support.says(
            self, "suite timeout", (errors[0].get("message") or "").lower(), "the truncation entry"
        )

    def bud_large_queue_payload_completes_without_deadlock(self):
        """A class with about 400 kB of results passes well inside a 10-second test timeout."""
        case = self._case("large")
        command = "bud-runner run-tests --no-upload --test-timeout 10 on about 400 kB of results"
        started = time.monotonic()
        done = case.run_tests("demo_exec.LARGE", "--no-upload", "--test-timeout", "10")
        elapsed = round(time.monotonic() - started, 1)
        support.exits(self, done, 0, command)
        support.check_less(
            self,
            elapsed,
            9,
            f"{command} returns the results after {elapsed} s, well inside the 10 s timeout",
            f"{command} returns after {elapsed} s, not well inside the 10 s timeout",
        )
        suite = case.junit().find("./testsuite[@name='LargeTest']")
        failures = suite.get("failures") if suite is not None else "no LargeTest suite"
        support.check(
            self,
            failures,
            "0",
            "the JUnit report shows LargeTest with 0 failures",
            f"the JUnit report shows LargeTest with failures={failures!r}",
        )

    def bud_fast_test_passes(self):
        """A passing class: exit 0 and a passing test case in the report."""
        case = self._case("pass")
        done = case.run_tests("demo_exec.PASS", "--no-upload")
        support.exits(self, done, 0, "bud-runner run-tests --no-upload on a passing class")
        cases = case.junit().findall("./testsuite[@name='PassTest']/testcase[@name='bud_passes']")
        support.need(
            self,
            len(cases),
            1,
            "the JUnit report lists PassTest.bud_passes once",
            f"the JUnit report lists PassTest.bud_passes {len(cases)} times, not once",
        )
        children = [child.tag for child in cases[0]]
        support.check(
            self,
            children,
            [],
            "PassTest.bud_passes has no failure or error in the JUnit report",
            f"PassTest.bud_passes carries {children} in the JUnit report",
        )

    def bud_failing_test_returns_failure(self):
        """A class whose setUpClass raises: exit 1 and the error in the report."""
        case = self._case("failing")
        command = "bud-runner run-tests --no-upload on a class whose setUpClass raises"
        done = case.run_tests("demo_exec.FAILING_SETUP", "--no-upload")
        support.exits(self, done, 1, command)
        suites = case.junit().findall("./testsuite[@name='FailingSetupTest']")
        support.need(
            self,
            len(suites),
            1,
            "the JUnit report lists FailingSetupTest once",
            f"the JUnit report lists FailingSetupTest {len(suites)} times, not once",
        )
        suite = suites[0]
        errors = [e.get("message") or "" for e in suite.iter("error")]
        errors += [f.get("message") or "" for f in suite.iter("failure")]
        support.says(
            self,
            "boom",
            " | ".join(errors),
            "the JUnit errors and failures of FailingSetupTest, carrying the setUpClass error,",
        )
