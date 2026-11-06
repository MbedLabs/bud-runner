"""_flatten_results(): budtestlibrary's nested results as the backend's flat TestResultCreate rows,
fed with doubles of the result objects."""

from budtestlibrary import BudTestCase

from bud_runner.api_client import _flatten_results
from tests.budtests.parameters import FlattenResults as p


class _Assertion:
    """A double of an assertion result."""

    def __init__(self, passed: bool, message: str):
        self.passed = passed
        self.message = message

    def to_dict(self):
        """The assertion as a dict."""
        return {"passed": self.passed, "message": self.message}


class _MethodResult:
    """A double of a step's result."""

    def __init__(self, method_name, passed, assertions, err=None, tb=None, summary_message=None):
        self.method_name = method_name
        self.passed = passed
        self.assertions = assertions
        self.duration_seconds = 0.5
        self.error_message = err
        self.traceback = tb
        self.summary_message = summary_message

    def to_dict(self):
        """The step result as a dict."""
        return {
            "method_name": self.method_name,
            "passed": self.passed,
            "assertions": [a.to_dict() for a in self.assertions],
            "duration_seconds": self.duration_seconds,
            "error_message": self.error_message,
            "traceback": self.traceback,
            "summary_message": self.summary_message,
        }


class _RunResult:
    """A double of a test class's result."""

    def __init__(self, test_class, method_results, passed=None, err=None):
        self.test_class = test_class
        self.method_results = method_results
        self.passed = passed if passed is not None else all(m.passed for m in method_results)
        self.duration_seconds = sum(m.duration_seconds for m in method_results)
        self.error_message = err


class FlattenResults(BudTestCase):
    """The rows _flatten_results() builds from run results, step results and flat dicts."""

    def bud_a_nested_run_result_becomes_one_row_per_step(self):
        """Each step is a row with the class and run id; the failing step keeps its traceback,
        assertions and summary."""
        run = _RunResult(
            p.VOLTAGE,
            [
                _MethodResult(
                    p.CELLS,
                    False,
                    [_Assertion(True, p.OK), _Assertion(False, p.TOO_LOW)],
                    err=p.CELL_ERROR,
                    tb=p.TRACE,
                    summary_message=p.SUMMARY,
                ),
                _MethodResult(p.PACK, True, [_Assertion(True, p.OK)]),
            ],
        )
        rows = _flatten_results([run], test_run_id=p.RUN_ID)
        self.assertEqual(len(rows), p.TWO_ROWS, "two steps give two rows", abort_on_fail=True)
        self.assertEqual(sorted(r["test_method"] for r in rows), sorted([p.CELLS, p.PACK]), "one row per step")
        self.assertEqual({r["test_class"] for r in rows}, {p.VOLTAGE}, "every row names the class")
        self.assertEqual({r["test_run_id"] for r in rows}, {p.RUN_ID}, "every row names the run")
        failing = next(r for r in rows if r["test_method"] == p.CELLS)
        self.assertEqual(failing["passed"], False, "the failing step's row is failed")
        self.assertEqual(failing["traceback"], p.TRACE, "the failing step's traceback is kept")
        self.assertEqual(failing["assertions"], p.CELL_ASSERTIONS, "the failing step's assertions are kept")
        self.assertEqual(failing["metadata"].get("summary_message"), p.SUMMARY, "the summary is in the metadata")

    def bud_a_class_failure_without_steps_gives_one_placeholder_row(self):
        """A class that failed before any step gives one failed __class__ row with its error."""
        run = _RunResult(p.BROKEN, [], passed=False, err=p.SETUP_ERROR)
        rows = _flatten_results([run], test_run_id=p.BROKEN_RUN_ID)
        self.assertEqual(len(rows), p.ONE_ROW, "one row", abort_on_fail=True)
        self.assertEqual(rows[0]["test_class"], p.BROKEN, "the row names the class")
        self.assertEqual(rows[0]["test_method"], p.PLACEHOLDER, "the row is the class placeholder")
        self.assertEqual(rows[0]["passed"], False, "the row is failed")
        self.assertEqual(rows[0]["error_message"], p.SETUP_ERROR, "the row carries the error")

    def bud_a_plain_step_result_is_accepted(self):
        """A step result without a class gives one row of an unknown class and no run id."""
        rows = _flatten_results([_MethodResult(p.SOLO, True, [_Assertion(True, p.OK)])], test_run_id=None)
        self.assertEqual(len(rows), p.ONE_ROW, "one row", abort_on_fail=True)
        self.assertEqual(rows[0]["test_method"], p.SOLO, "the row names the step")
        self.assertEqual(rows[0]["test_class"], p.UNKNOWN_CLASS, "the class is unknown")
        self.assertNotIn(member="test_run_id", container=rows[0], msg="the row carries no run id")

    def bud_an_already_flat_row_is_passed_through(self):
        """A flat dict keeps its step and gets the run id."""
        rows = _flatten_results([dict(p.SMOKE_ROW)], test_run_id=p.SMOKE_RUN_ID)
        self.assertEqual(rows[0]["test_method"], p.HELLO, "the step is kept")
        self.assertEqual(rows[0]["test_run_id"], p.SMOKE_RUN_ID, "the run id is added")
