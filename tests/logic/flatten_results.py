"""_flatten_results(): budtestlibrary's nested results as the backend's flat TestResultCreate rows,
fed with doubles of the result objects."""

from budtestlibrary import BudTestCase

from bud_runner.api_client import _flatten_results
from tests.doubles import Assertion as _Assertion
from tests.doubles import MethodResult as _MethodResult
from tests.doubles import RunResult as _RunResult
from tests.parameters import FlattenResults as parameters


class FlattenResults(BudTestCase):
    """The rows _flatten_results() builds from run results, step results and flat dicts."""

    def bud_a_nested_run_result_becomes_one_row_per_step(self):
        """Each step is a row with the class and run id; the failing step keeps its traceback,
        assertions and summary."""
        run = _RunResult(
            parameters.VOLTAGE,
            [
                _MethodResult(
                    parameters.CELLS,
                    False,
                    [_Assertion(True, parameters.OK), _Assertion(False, parameters.TOO_LOW)],
                    err=parameters.CELL_ERROR,
                    tb=parameters.TRACE,
                    summary_message=parameters.SUMMARY,
                ),
                _MethodResult(parameters.PACK, True, [_Assertion(True, parameters.OK)]),
            ],
        )
        rows = _flatten_results([run], test_run_id=parameters.RUN_ID)
        self.assertEqual(
            len(rows), parameters.TWO_ROWS, "two steps give two rows", abort_on_fail=True
        )
        self.assertEqual(
            sorted(r["test_method"] for r in rows),
            sorted([parameters.CELLS, parameters.PACK]),
            "one row per step",
        )
        self.assertEqual(
            {r["test_class"] for r in rows}, {parameters.VOLTAGE}, "every row names the class"
        )
        self.assertEqual(
            {r["test_run_id"] for r in rows}, {parameters.RUN_ID}, "every row names the run"
        )
        failing = next(r for r in rows if r["test_method"] == parameters.CELLS)
        self.assertEqual(failing["passed"], False, "the failing step's row is failed")
        self.assertEqual(
            failing["traceback"], parameters.TRACE, "the failing step's traceback is kept"
        )
        self.assertEqual(
            failing["assertions"],
            parameters.CELL_ASSERTIONS,
            "the failing step's assertions are kept",
        )
        self.assertEqual(
            failing["metadata"].get("summary_message"),
            parameters.SUMMARY,
            "the summary is in the metadata",
        )

    def bud_a_class_failure_without_steps_gives_one_placeholder_row(self):
        """A class that failed before any step gives one failed __class__ row with its error."""
        run = _RunResult(parameters.BROKEN, [], passed=False, err=parameters.SETUP_ERROR)
        rows = _flatten_results([run], test_run_id=parameters.BROKEN_RUN_ID)
        self.assertEqual(len(rows), parameters.ONE_ROW, "one row", abort_on_fail=True)
        self.assertEqual(rows[0]["test_class"], parameters.BROKEN, "the row names the class")
        self.assertEqual(
            rows[0]["test_method"], parameters.PLACEHOLDER, "the row is the class placeholder"
        )
        self.assertEqual(rows[0]["passed"], False, "the row is failed")
        self.assertEqual(
            rows[0]["error_message"], parameters.SETUP_ERROR, "the row carries the error"
        )

    def bud_a_plain_step_result_is_accepted(self):
        """A step result without a class gives one row of an unknown class and no run id."""
        rows = _flatten_results(
            [_MethodResult(parameters.SOLO, True, [_Assertion(True, parameters.OK)])],
            test_run_id=None,
        )
        self.assertEqual(len(rows), parameters.ONE_ROW, "one row", abort_on_fail=True)
        self.assertEqual(rows[0]["test_method"], parameters.SOLO, "the row names the step")
        self.assertEqual(rows[0]["test_class"], parameters.UNKNOWN_CLASS, "the class is unknown")
        self.assertNotIn(member="test_run_id", container=rows[0], msg="the row carries no run id")

    def bud_an_already_flat_row_is_passed_through(self):
        """A flat dict keeps its step and gets the run id."""
        rows = _flatten_results([dict(parameters.SMOKE_ROW)], test_run_id=parameters.SMOKE_RUN_ID)
        self.assertEqual(rows[0]["test_method"], parameters.HELLO, "the step is kept")
        self.assertEqual(rows[0]["test_run_id"], parameters.SMOKE_RUN_ID, "the run id is added")
