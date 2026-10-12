"""pytest plugin: a pytest run becomes a Bud run.

Run ``bud-runner run-pytest <pytest arguments>``, or attach it yourself with
``pytest -p bud_runner.pytest_plugin -o enable_assertion_pass_hook=true``. Each pytest
test becomes one Bud test case and result (its node id as the test class, its name as
the method). Inside a test, every ``assert`` statement in a test module or conftest.py
becomes one assertion entry in the shape budtestlibrary sends: a single comparison is
named after what it checks (``==`` AssertEqual, ``!=`` AssertNotEqual, ``in`` AssertIn,
``not in`` AssertNotIn, ``<`` AssertLess, ``>`` AssertGreater) with its expected and
actual values, anything else is AssertTrue. The ``bud_assert`` fixture offers
budtestlibrary's assertion methods (``assertEqual``, ``assertIn``, ``assertInRange``,
...) with the same arguments and records; a failed one does not stop the test but fails
it, unless ``abort_on_fail=True`` stops it there; in a test marked xfail it is the
expected failure. An exception is a failed entry named
after its class, with pytest's traceback; ``pytest.skip`` and xfail make a skipped
result. A ``@pytest.mark.bloom("PRJ-001")`` marker becomes the Bloom test case ``PRJ-TC-001``. At the
end of the session the run is uploaded; pytest's exit code is not changed, and an
upload failure spools the payload for the next bud-runner invocation and prints a
warning.
"""

import ast
import linecache
import os
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import _pytest
import pluggy
import pytest

from bud_runner.reporting import bloom_tc_id
from bud_runner.robot_listener import _relative

PLUGIN_NAME = "bud-reporter"
BLOOM_MARKER = "bloom"
VALUE_LIMIT = 5000
RECORDED = "_bud_recorded"
STRICT_XPASS = "[XPASS(strict)]"
OPERATORS = {
    ast.Eq: "==",
    ast.NotEq: "!=",
    ast.In: "in",
    ast.NotIn: "not in",
    ast.Lt: "<",
    ast.Gt: ">",
}
ASSERT_TYPES = {
    "==": "AssertEqual",
    "!=": "AssertNotEqual",
    "in": "AssertIn",
    "not in": "AssertNotIn",
    "<": "AssertLess",
    ">": "AssertGreater",
}
_INTERNAL_DIRS = tuple(str(Path(m.__file__).resolve().parent) + os.sep for m in (_pytest, pluggy))
_THIS_FILE = str(Path(__file__).resolve())


class BudAssertionError(AssertionError):
    """Raised by a failed ``bud_assert`` call with ``abort_on_fail=True``."""


def _value(value: Any) -> Optional[str]:
    """A value as budtestlibrary stores it: its text, cut at 5000 characters."""
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= VALUE_LIMIT else text[:VALUE_LIMIT] + "... <truncated>"


def assertion(
    passed: bool,
    assertion_type: str,
    message: str = "",
    expected: Any = None,
    actual: Any = None,
    result: Any = None,
    where: Optional[Dict[str, Any]] = None,
    trace: Optional[str] = None,
    skipped: bool = False,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """One assertion entry with the fields of budtestlibrary's ``TestResult.to_dict``."""
    where = where or {}
    return {
        "passed": passed,
        "message": message,
        "skipped": skipped,
        "assertion_type": assertion_type,
        "expected": _value(expected),
        "actual": _value(actual),
        "result": _value(result),
        "source_file": where.get("source_file"),
        "source_line": where.get("source_line"),
        "source_function": where.get("source_function"),
        "code_context": where.get("code_context"),
        "traceback": None if passed else trace,
        "timestamp": datetime.now().isoformat(),
        "metadata": metadata or {},
    }


def comparison(op: str, left: Any, right: Any) -> Tuple[str, Any, Any]:
    """The assertion type, expected and actual of ``left <op> right``, as budtestlibrary's
    method for that check builds them; the left operand is the actual value."""
    if op == "==":
        return "AssertEqual", right, left
    if op == "!=":
        return "AssertNotEqual", f"!= {right}", left
    if op == "in":
        return "AssertIn", f"'{left}' in container", right
    if op == "not in":
        return "AssertNotIn", f"'{left}' NOT in container", right
    if op == "<":
        return "AssertLess", f"< {right}", left
    return "AssertGreater", f"> {right}", left


def operator_of(test: Optional[ast.expr]) -> Optional[str]:
    """The operator of an assert's expression when it is one comparison Bud names."""
    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        return OPERATORS.get(type(test.ops[0]))
    return None


def shown_value(text: Optional[str]) -> Any:
    """The value pytest shows for an asserted expression: the Python literal it reads as,
    else the text itself."""
    if text is None:
        return None
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return text


def check(
    passed: bool,
    test: Optional[ast.expr],
    compared: Optional[Tuple[str, Any, Any]],
    message: str,
    where: Dict[str, Any],
    trace: Optional[str] = None,
    shown: Optional[str] = None,
) -> Dict[str, Any]:
    """The entry of an ``assert`` statement.

    A comparison Bud names takes its expected and actual from the compared values. Any
    other expression is AssertTrue with expected True: a ``not``, ``and``, ``or`` or other
    comparison has the boolean as its actual, any other expression the value pytest
    shows for it (``shown``), as budtestlibrary's ``assertTrue(value)`` records it.
    """
    op = operator_of(test)
    if op and compared and compared[0] == op:
        assertion_type, expected, actual = comparison(op, compared[1], compared[2])
        return assertion(passed, assertion_type, message, expected, actual, actual, where, trace)
    if op:
        return assertion(passed, ASSERT_TYPES[op], message, where=where, trace=trace)
    actual: Any = passed
    boolean = isinstance(test, (ast.BoolOp, ast.Compare)) or (
        isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not)
    )
    if test is not None and not boolean and shown is not None:
        actual = shown_value(shown)
    return assertion(passed, "AssertTrue", message, True, actual, actual, where, trace)


def _failed_value(message: str) -> Optional[str]:
    """What pytest shows after ``assert`` in a failed assert's explanation."""
    for line in message.splitlines():
        if line.startswith("assert "):
            return line[len("assert ") :]
    return None


def _internal(filename: str) -> bool:
    try:
        path = str(Path(filename).resolve())
    except (OSError, ValueError):
        path = filename
    return path == _THIS_FILE or path.startswith(_INTERNAL_DIRS)


def _callsite() -> Dict[str, Any]:
    """File, line and function of the nearest caller outside pytest, pluggy and this plugin."""
    frame = sys._getframe(1)
    while frame is not None and _internal(frame.f_code.co_filename):
        frame = frame.f_back
    if frame is None:
        return {}
    filename = frame.f_code.co_filename
    return {
        "source_file": _relative(filename),
        "source_line": frame.f_lineno,
        "source_function": frame.f_code.co_name,
        "code_context": linecache.getline(filename, frame.f_lineno).strip() or None,
        "path": filename,
        "frame": frame,
    }


def _parse_expression(source: str) -> Optional[ast.expr]:
    try:
        return ast.parse(source.strip(), mode="eval").body
    except SyntaxError:
        return None


def _literal_message(node: Optional[ast.Assert]) -> str:
    """The message of ``assert x, "message"`` when it is a plain string."""
    if node is not None and isinstance(node.msg, ast.Constant) and isinstance(node.msg.value, str):
        return node.msg.value
    return ""


def _skip_reason(report: Any) -> str:
    if hasattr(report, "wasxfail"):
        return str(report.wasxfail or "xfail")
    longrepr = report.longrepr
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        reason = str(longrepr[2])
    else:
        reason = str(longrepr or "")
    return reason[len("Skipped: ") :] if reason.startswith("Skipped: ") else reason


def _skip_site(item: Any) -> Dict[str, Any]:
    path, lineno, name = item.location
    return {
        "source_file": path,
        "source_line": (lineno + 1) if lineno is not None else None,
        "source_function": name,
    }


class _TestState:
    """What one test collected while it ran."""

    def __init__(self) -> None:
        self.assertions: List[Dict[str, Any]] = []
        self.reports: List[Any] = []
        self.error: Optional[str] = None
        self.soft_failure: Optional[str] = None


class BudReporter:
    """Collects a pytest session and uploads it to Bud when the session finishes."""

    def __init__(self, config: Any) -> None:
        option = config.option
        self.config = config
        self.backend: Optional[str] = option.bud_backend_url
        self.test_run_id: Optional[int] = option.bud_test_run_id
        self.product_id: Optional[int] = option.bud_product_id
        self.suite_name: Optional[str] = option.bud_suite_name
        self.ref_sw_under_test: Optional[str] = option.bud_ref_sw_under_test
        self.upload = not option.bud_no_upload
        self.results: List[Dict[str, Any]] = []
        self.skipped = 0
        self._tests: Dict[str, _TestState] = {}
        self._compared: Optional[Tuple[str, Any, Any]] = None
        self._sources: Dict[str, Tuple[str, List[ast.Assert]]] = {}

    def state(self, nodeid: str) -> _TestState:
        """The collection of the test with this node id."""
        if nodeid not in self._tests:
            self._tests[nodeid] = _TestState()
        return self._tests[nodeid]

    def record(self, nodeid: str, entry: Dict[str, Any], failure_line: Optional[str] = None) -> None:
        """Add an entry to a test; ``failure_line`` marks a failed ``bud_assert`` call."""
        state = self.state(nodeid)
        state.assertions.append(entry)
        if failure_line is not None and state.soft_failure is None:
            state.soft_failure = failure_line
            state.error = state.error or failure_line

    def _assert_at(self, filename: str, lineno: int) -> Tuple[Optional[ast.Assert], str]:
        """The assert statement covering a line of a file, and the file's source."""
        if filename not in self._sources:
            try:
                source = Path(filename).read_text(encoding="utf-8")
                nodes = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Assert)]
            except (OSError, SyntaxError, ValueError):
                source, nodes = "", []
            self._sources[filename] = (source, nodes)
        source, nodes = self._sources[filename]
        hits = [n for n in nodes if n.lineno <= lineno <= (getattr(n, "end_lineno", None) or n.lineno)]
        return (max(hits, key=lambda n: n.lineno) if hits else None), source

    def _statement(self, where: Dict[str, Any], lineno: int) -> Optional[ast.Assert]:
        """The assert at ``where``, its full source put into ``code_context``."""
        path = where.get("path")
        if not path:
            return None
        node, source = self._assert_at(path, lineno)
        if node is not None:
            where["code_context"] = ast.get_source_segment(source, node) or where.get("code_context")
        return node

    def pytest_runtest_logstart(self, nodeid: str, location: Any) -> None:
        self._tests[nodeid] = _TestState()
        self._compared = None

    @pytest.hookimpl(tryfirst=True)
    def pytest_assertrepr_compare(self, config: Any, op: str, left: Any, right: Any) -> None:
        self._compared = (op, left, right)
        return None

    def pytest_assertion_pass(self, item: Any, lineno: int, orig: str, expl: str) -> None:
        compared, self._compared = self._compared, None
        where = _callsite()
        node = self._statement(where, lineno)
        if node is None:
            where["code_context"] = f"assert {orig}"
        test = node.test if node is not None else _parse_expression(orig)
        where["source_line"] = lineno
        shown = expl.split("\n", 1)[0] if expl else None
        entry = check(True, test, compared, _literal_message(node), where, shown=shown)
        self.state(item.nodeid).assertions.append(entry)

    def _failure_site(self, excinfo: Any) -> Dict[str, Any]:
        """Where a failure was raised: the deepest frame below the rootdir, else the deepest
        frame outside pytest."""
        root = str(self.config.rootpath) + os.sep
        entries = [e for e in excinfo.traceback if not _internal(str(e.path))]
        own = [e for e in entries if str(e.path).startswith(root) and "site-packages" not in str(e.path)]
        chosen = (own or entries or [None])[-1]
        if chosen is None:
            return {}
        filename = str(chosen.path)
        return {
            "source_file": _relative(filename),
            "source_line": chosen.lineno + 1,
            "source_function": chosen.name,
            "code_context": linecache.getline(filename, chosen.lineno + 1).strip() or None,
            "path": filename,
        }

    def _failure_entry(self, when: str, excinfo: Any, report: Any) -> Dict[str, Any]:
        """The failed entry of an exception: an assert's check, else the exception's class."""
        exc = excinfo.value
        trace = report.longreprtext or None
        message = str(exc) or type(exc).__name__
        where = self._failure_site(excinfo)
        if isinstance(exc, AssertionError) and when == "call" and where:
            node = self._statement(where, where["source_line"])
            if node is not None:
                compared, self._compared = self._compared, None
                return check(False, node.test, compared, message, where, trace, _failed_value(message))
        entry = assertion(False, type(exc).__name__, message, where=where, trace=trace)
        if when != "call":
            entry["metadata"] = {"phase": when}
        return entry

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item: Any, call: Any):
        outcome = yield
        report = outcome.get_result()
        state = self.state(item.nodeid)
        xfail = hasattr(report, "wasxfail")
        strict_pass = report.failed and str(report.longrepr or "").startswith(STRICT_XPASS)
        if call.when == "call" and state.soft_failure and ((xfail and report.passed) or strict_pass):
            report.outcome = "skipped"
            if strict_pass:
                report.wasxfail = str(report.longrepr)[len(STRICT_XPASS) :].strip()
            xfail = True
        expected_failure = xfail or any(hasattr(r, "wasxfail") for r in state.reports)
        earlier_failure = any(r.failed for r in state.reports)
        surface = call.when == "call" or (call.when == "teardown" and not earlier_failure)
        if surface and report.passed and not expected_failure and state.soft_failure:
            report.outcome = "failed"
            report.longrepr = f"bud_assert failed: {state.soft_failure}"
        excinfo = call.excinfo
        if report.failed and excinfo is not None and not getattr(excinfo.value, RECORDED, False):
            entry = self._failure_entry(call.when, excinfo, report)
            state.assertions.append(entry)
            state.error = state.error or entry["message"]
        elif report.skipped:
            reason = _skip_reason(report)
            state.assertions.append(assertion(True, "Skip", reason, where=_skip_site(item), skipped=True))
        state.reports.append(report)
        if call.when == "teardown":
            self._finish(item, state)

    def _finish(self, item: Any, state: _TestState) -> None:
        """Turn a test's collection into its Bud result."""
        reports = state.reports
        failed = [r for r in reports if r.failed]
        skipped = not failed and any(r.skipped for r in reports)
        xfail = any(hasattr(r, "wasxfail") for r in reports)
        if failed:
            outcome = "failed" if any(r.when == "call" for r in failed) else "error"
        elif skipped:
            outcome = "xfailed" if xfail else "skipped"
        else:
            outcome = "xpassed" if xfail else "passed"
        metadata: Dict[str, Any] = {
            "pytest_outcome": outcome,
            "pytest_markers": sorted({m.name for m in item.iter_markers()}),
        }
        marker = item.get_closest_marker(BLOOM_MARKER)
        if marker is not None and marker.args and str(marker.args[0]).strip():
            metadata["tc_id"] = bloom_tc_id(str(marker.args[0]))
        error = None
        if failed:
            error = state.error or failed[0].longreprtext or outcome
        elif skipped:
            self.skipped += 1
            metadata["skipped"] = True
            error = next((_skip_reason(r) for r in reports if r.skipped), None) or None
        self.results.append(
            {
                "test_class": item.nodeid,
                "test_method": item.name,
                "passed": not failed,
                "duration_seconds": round(sum(getattr(r, "duration", 0.0) or 0.0 for r in reports), 3),
                "error_message": error,
                "traceback": (failed[0].longreprtext or None) if failed else None,
                "assertions": state.assertions or None,
                "metadata": metadata,
            }
        )
        self._tests.pop(item.nodeid, None)

    def payload(
        self, runner_account: Optional[str] = None, default_product_id: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """The ResultsUpload body for the collected session, or None when no test ran.

        The suite is ``--bud-suite-name``, else the name of pytest's rootdir; the product
        is ``--bud-product-id``, else the one bud-runner reads from app.properties.
        """
        if not self.results:
            return None
        body: Dict[str, Any] = {
            "results": self.results,
            "test_run_id": self.test_run_id,
            "runner_account": runner_account,
            "test_suite_name": self.suite_name or self.config.rootpath.name,
            "ref_software_under_test": self.ref_sw_under_test,
        }
        product_id = self.product_id if self.product_id is not None else default_product_id
        if product_id is not None:
            body["product_id"] = product_id
        return body

    def pytest_sessionfinish(self, session: Any, exitstatus: Any) -> None:
        if not self.upload:
            return
        try:
            from bud_runner.reporting import send_run

            send_run(
                self.payload,
                framework="pytest",
                backend=self.backend,
                test_run_id=self.test_run_id,
                skipped=self.skipped,
            )
        except Exception as exc:
            print(f"[bud] Could not report the pytest run to Bud: {exc}", file=sys.stderr)


class BudAssert:
    """budtestlibrary's assertion methods inside a pytest test, recorded for Bud.

    Every call adds one entry to the running test, with the arguments, names and values
    budtestlibrary's ``BudTestCase`` uses. A failed check does not raise: the test goes
    on and fails at its end, its first failed check as the error message. With
    ``abort_on_fail=True`` a failed check raises ``BudAssertionError`` at once.
    """

    def __init__(self, reporter: BudReporter, nodeid: str) -> None:
        self._reporter = reporter
        self._nodeid = nodeid

    def skipAssert(self, msg: str, **kwargs: Any) -> None:
        """Record an explicitly skipped check."""
        entry = assertion(True, "Skip", msg, where=_callsite(), skipped=True, metadata=kwargs)
        self._reporter.record(self._nodeid, entry)

    def assertTrue(
        self,
        condition: Any,
        msg: str = "",
        expected: Any = None,
        actual: Any = None,
        abort_on_fail: bool = False,
        assertion_type: str = "AssertTrue",
        **kwargs: Any,
    ) -> bool:
        """Check that ``condition`` is true; every other check is recorded through this one."""
        passed = bool(condition)
        expected = expected if expected is not None else True
        actual = actual if actual is not None else condition
        where = _callsite()
        trace = None
        if not passed and where.get("frame") is not None:
            trace = "".join(traceback.format_stack(where["frame"])).strip()
        entry = assertion(passed, assertion_type, msg, expected, actual, actual, where, trace, metadata=kwargs)
        line = None
        if not passed:
            line = f"[{assertion_type}] EXPECTED: {expected} | ACTUAL: {actual} | MESSAGE: {msg}"
        self._reporter.record(self._nodeid, entry, line)
        if line is not None and abort_on_fail:
            error = BudAssertionError(line)
            setattr(error, RECORDED, True)
            raise error
        return passed

    def assertEqual(
        self, actual: Any, expected: Any, msg: str = "", abort_on_fail: bool = False, **kwargs: Any
    ) -> bool:
        """Check ``actual == expected``."""
        return self.assertTrue(
            actual == expected, msg, expected, actual, abort_on_fail, "AssertEqual", **kwargs
        )

    def assertNotEqual(
        self, actual: Any, expected: Any, msg: str = "", abort_on_fail: bool = False, **kwargs: Any
    ) -> bool:
        """Check ``actual != expected``."""
        return self.assertTrue(
            actual != expected, msg, f"!= {expected}", actual, abort_on_fail, "AssertNotEqual", **kwargs
        )

    @staticmethod
    def _container(name: str, actual: Any, expected: Any, member: Any, container: Any) -> Tuple[Any, Any]:
        """The member and the container of an ``in`` check, as budtestlibrary takes them."""
        item = member if member is not None else actual
        holder = container if container is not None else expected
        if not hasattr(holder, "__contains__"):
            raise TypeError(
                f"{name} requires a container with __contains__ (list, dict, set, str, etc.), "
                f"got {type(holder).__name__}"
            )
        return item, holder

    def assertIn(
        self,
        actual: Any = None,
        expected: Any = None,
        member: Any = None,
        container: Any = None,
        msg: str = "",
        abort_on_fail: bool = False,
        **kwargs: Any,
    ) -> bool:
        """Check that ``member`` (or ``actual``) is in ``container`` (or ``expected``)."""
        item, holder = self._container("assertIn", actual, expected, member, container)
        return self.assertTrue(
            item in holder, msg, f"'{item}' in container", holder, abort_on_fail, "AssertIn", **kwargs
        )

    def assertNotIn(
        self,
        actual: Any = None,
        expected: Any = None,
        member: Any = None,
        container: Any = None,
        msg: str = "",
        abort_on_fail: bool = False,
        **kwargs: Any,
    ) -> bool:
        """Check that ``member`` (or ``actual``) is not in ``container`` (or ``expected``)."""
        item, holder = self._container("assertNotIn", actual, expected, member, container)
        return self.assertTrue(
            item not in holder,
            msg,
            f"'{item}' NOT in container",
            holder,
            abort_on_fail,
            "AssertNotIn",
            **kwargs,
        )

    def assertInTolerance(
        self,
        actual: float,
        expected: float,
        absolute_tolerance: Optional[float] = None,
        relative_tolerance: Optional[float] = None,
        msg: str = "",
        abort_on_fail: bool = False,
        **kwargs: Any,
    ) -> bool:
        """Check that ``actual`` is within a tolerance of ``expected``."""
        if absolute_tolerance is not None:
            tol = absolute_tolerance
        elif relative_tolerance is not None:
            tol = abs(expected * relative_tolerance)
        else:
            tol = 0.0
        return self.assertTrue(
            (expected - tol) <= actual <= (expected + tol),
            msg,
            f"{expected}±{tol}",
            actual,
            abort_on_fail,
            "AssertInTolerance",
            **kwargs,
        )

    def assertInRange(
        self,
        actual: float,
        lower_bound: float,
        upper_bound: Optional[float] = None,
        include_bounds: bool = True,
        msg: str = "",
        abort_on_fail: bool = False,
        **kwargs: Any,
    ) -> bool:
        """Check that ``actual`` lies between the bounds, or above ``lower_bound`` alone."""
        if upper_bound is not None:
            if include_bounds:
                cond = lower_bound <= actual <= upper_bound
            else:
                cond = lower_bound < actual < upper_bound
            expected = f"[{lower_bound}, {upper_bound}]"
        else:
            cond = (actual >= lower_bound) if include_bounds else (actual > lower_bound)
            expected = f">= {lower_bound}" if include_bounds else f"> {lower_bound}"
        return self.assertTrue(cond, msg, expected, actual, abort_on_fail, "AssertInRange", **kwargs)

    def assertFalse(self, condition: Any, msg: str = "", abort_on_fail: bool = False, **kwargs: Any) -> bool:
        """Check that ``condition`` is false."""
        return self.assertTrue(
            not condition, msg, False, bool(condition), abort_on_fail, "AssertFalse", **kwargs
        )

    def assertGreater(
        self, actual: Any, expected: Any, msg: str = "", abort_on_fail: bool = False, **kwargs: Any
    ) -> bool:
        """Check ``actual > expected``."""
        return self.assertTrue(
            actual > expected, msg, f"> {expected}", actual, abort_on_fail, "AssertGreater", **kwargs
        )

    def assertLess(
        self, actual: Any, expected: Any, msg: str = "", abort_on_fail: bool = False, **kwargs: Any
    ) -> bool:
        """Check ``actual < expected``."""
        return self.assertTrue(
            actual < expected, msg, f"< {expected}", actual, abort_on_fail, "AssertLess", **kwargs
        )

    def assertRegex(
        self, text: str, pattern: str, msg: str = "", abort_on_fail: bool = False, **kwargs: Any
    ) -> bool:
        """Check that ``pattern`` matches somewhere in ``text``."""
        return self.assertTrue(
            bool(re.search(pattern, text)),
            msg,
            f"matches '{pattern}'",
            text,
            abort_on_fail,
            "AssertRegex",
            **kwargs,
        )


def pytest_addoption(parser: Any) -> None:
    group = parser.getgroup("bud", "report the run to Bud (bud_runner.pytest_plugin)")
    group.addoption("--bud-backend-url", default=None, help="Bud backend URL for the upload.")
    group.addoption(
        "--bud-test-run-id", type=int, default=None, help="Existing Bud test run to attach the results to."
    )
    group.addoption(
        "--bud-product-id", type=int, default=None, help="Product id for a run Bud creates from the upload."
    )
    group.addoption("--bud-suite-name", default=None, help="Suite name in Bud (default: the rootdir name).")
    group.addoption("--bud-ref-sw-under-test", default=None, help="Git ref of the software under test.")
    group.addoption(
        "--bud-no-upload", action="store_true", default=False, help="Collect the run but do not upload it."
    )


def pytest_configure(config: Any) -> None:
    config.addinivalue_line("markers", f"{BLOOM_MARKER}(tc_id): the Bloom test case this test verifies.")
    if not config.getini("enable_assertion_pass_hook"):
        config.issue_config_time_warning(
            pytest.PytestConfigWarning(
                "bud_runner.pytest_plugin: enable_assertion_pass_hook is off, so passing assert "
                "statements are not reported to Bud; use bud-runner run-pytest or "
                "-o enable_assertion_pass_hook=true."
            ),
            stacklevel=2,
        )
    config.pluginmanager.register(BudReporter(config), PLUGIN_NAME)


@pytest.fixture
def bud_assert(request: Any) -> BudAssert:
    """budtestlibrary's assertion methods, recorded as Bud assertion entries of this test."""
    return BudAssert(request.config.pluginmanager.get_plugin(PLUGIN_NAME), request.node.nodeid)
