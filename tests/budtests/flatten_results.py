"""_flatten_results(): budtestlibrary's nested results as the backend's flat TestResultCreate rows,
fed with doubles of the result objects."""

from budtestlibrary import BudTestCase

from bud_runner.api_client import _flatten_results
from tests.budtests.doubles import Assertion as _Assertion
from tests.budtests.doubles import MethodResult as _MethodResult
from tests.budtests.doubles import RunResult as _RunResult
from tests.budtests.parameters import FlattenResults as p


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
