"""How a run's results become the flat rows Bud stores: one per step, a class row when a class
produced none, flat rows as given."""

import support
from budtestlibrary import BudTestCase

from bud_runner.api_client import BudAPIClient, _flatten_results
from bud_runner.auth import AuthManager

BROKEN_SUITE = '''"""A suite whose class setup fails."""

from budtestlibrary import BudTestCase


class BrokenSuite(BudTestCase):
    """setUpClass raises."""

    def setUpClass(self):
        """Fail before any step."""
        raise RuntimeError("setUpClass raised")

    def bud_never_runs(self):
        """Not reached."""
        self.assertTrue(True, msg="never")


BROKEN_LIST = ["demo_broken.BrokenSuite"]
'''


class _MethodResult:
    """A method result as budtestlibrary's TestMethodResult exposes it."""

    def __init__(self, method_name, passed):
        self.method_name, self.passed = method_name, passed

    def to_dict(self):
        """Return the result as a dictionary."""
        return {
            "method_name": self.method_name,
            "passed": self.passed,
            "assertions": [{"passed": True, "message": "ok"}],
            "duration_seconds": 0.5,
        }


class FlattenResults(BudTestCase):
    """The rows Bud stores for a run with steps, a class that failed before its steps, a bare step
    result and a flat row."""

    def setUpClass(self):
        self.bud = support.Bud()
        self.station = self.bud.station("main")

    def bud_flattens_nested_run_result_into_per_method_rows(self):
        """run-tests --test-run-id: one stored row per step with class, run, outcome, traceback,
        assertions and summary."""
        case = support.Case("flatten")
        run_id = self.bud.create_run(self.station, "Flatten")
        command = f"bud-runner run-tests --test-run-id {run_id} of the voltage suite"
        done = case.run_tests(
            support.voltage_suite(case), "--test-run-id", run_id, station=self.station
        )
        support.exits(self, done, 1, f"{command}, one step of which fails,")
        rows = {r["test_method"]: r for r in self.bud.results(run_id)}
        support.need(
            self,
            sorted(rows),
            ["bud_check_cells", "bud_check_pack"],
            f"Bud stores one row per step on run {run_id}: bud_check_cells and bud_check_pack",
            f"Bud stores the rows {sorted(rows)} on run {run_id}",
        )
        for row in rows.values():
            support.check(
                self,
                row["test_class"],
                "VoltageTest",
                f"the stored row of {row['test_method']} names its class VoltageTest",
                f"the stored row of {row['test_method']} names the class {row['test_class']!r}",
            )
            support.check(
                self,
                row["test_run_id"],
                run_id,
                f"the stored row of {row['test_method']} is on run {run_id}",
                f"the stored row of {row['test_method']} is on run {row['test_run_id']!r}",
            )
        failing, passing = rows["bud_check_cells"], rows["bud_check_pack"]
        support.check(
            self,
            failing["passed"],
            False,
            "bud_check_cells, whose range check fails, is stored as failed",
            "bud_check_cells, whose range check fails, is stored as passed",
        )
        support.check(
            self,
            passing["passed"],
            True,
            "bud_check_pack, whose one check passes, is stored as passed",
            "bud_check_pack, whose one check passes, is stored as failed",
        )
        support.says(
            self, "too low", failing["error_message"] or "", "the stored error of bud_check_cells"
        )
        outcomes = [a["passed"] for a in failing["assertions"]]
        support.check(
            self,
            outcomes,
            [True, False],
            "both checks of bud_check_cells are stored in order: passed, then failed",
            f"the checks of bud_check_cells are stored with the outcomes {outcomes}",
        )
        messages = [a["message"] for a in failing["assertions"]]
        support.check(
            self,
            messages,
            ["ok", "too low"],
            "the checks of bud_check_cells keep their messages 'ok' and 'too low'",
            f"the checks of bud_check_cells are stored with the messages {messages}",
        )
        summary = failing["test_metadata"]["summary_message"]
        support.check(
            self,
            summary,
            failing["error_message"],
            "the summary message of bud_check_cells is its error message",
            f"the summary message of bud_check_cells is {summary!r}, not its error message "
            f"{failing['error_message']!r}",
        )
        summary = passing["test_metadata"]["summary_message"]
        support.check(
            self,
            summary,
            "Step Passed",
            "the summary message of the passing bud_check_pack is Step Passed",
            f"the summary message of the passing bud_check_pack is {summary!r}",
        )
        tc_id = failing["test_metadata"]["tc_id"]
        support.check(
            self,
            tc_id,
            "PRJ-TC-001",
            "the stored row carries PRJ-TC-001, the Bloom test case of VoltageTest",
            f"the stored row carries the Bloom test case {tc_id!r}, not PRJ-TC-001",
        )

    def bud_class_level_failure_with_no_methods_produces_placeholder_row(self):
        """A class whose setUpClass raises is stored as one failed __class__ row."""
        case = support.Case("class-failure")
        case.write("demo_broken.py", BROKEN_SUITE)
        run_id = self.bud.create_run(self.station, "Class failure")
        command = f"bud-runner run-tests --test-run-id {run_id} of a class whose setUpClass raises"
        done = case.run_tests(
            "demo_broken.BROKEN_LIST", "--test-run-id", run_id, station=self.station
        )
        support.exits(self, done, 1, command)
        rows = self.bud.results(run_id)
        support.need(
            self,
            [(r["test_class"], r["test_method"]) for r in rows],
            [("BrokenSuite", "__class__")],
            f"Bud stores one placeholder row BrokenSuite.__class__ on run {run_id}",
            f"Bud stores the rows {[(r['test_class'], r['test_method']) for r in rows]} on run "
            f"{run_id}",
        )
        support.check(
            self,
            rows[0]["passed"],
            False,
            "the BrokenSuite.__class__ row is stored as failed",
            "the BrokenSuite.__class__ row is stored as passed",
        )
        support.says(
            self,
            "setUpClass raised",
            rows[0]["error_message"] or "",
            "the stored error of the BrokenSuite.__class__ row",
        )

    def bud_plain_method_result_is_accepted(self):
        """In-process: a bare step result gets UnknownTestClass and no run id."""
        rows = _flatten_results([_MethodResult("bud_solo", True)], test_run_id=None)
        support.need(
            self,
            len(rows),
            1,
            "_flatten_results turns one bare step result into one row",
            f"_flatten_results turns one bare step result into {len(rows)} rows",
        )
        support.check(
            self,
            rows[0]["test_method"],
            "bud_solo",
            "the row keeps the step name bud_solo",
            f"the row names the step {rows[0]['test_method']!r}, not bud_solo",
        )
        support.check(
            self,
            rows[0]["test_class"],
            "UnknownTestClass",
            "a bare step result without a class gets the class UnknownTestClass",
            f"a bare step result without a class gets the class {rows[0]['test_class']!r}",
        )
        support.check_not_in(
            self,
            "test_run_id",
            rows[0],
            "a row flattened with test_run_id=None carries no test_run_id",
            "a row flattened with test_run_id=None carries "
            f"test_run_id={rows[0].get('test_run_id')!r}",
        )

    def bud_already_flat_dict_is_passed_through(self):
        """upload_results of a flat row: Bud stores it on the run as given."""
        run_id = self.bud.create_run(self.station, "Flat row")
        case = support.Case("flat-row")
        row = {
            "test_class": "SmokeTest",
            "test_method": "bud_hello",
            "passed": True,
            "duration_seconds": 0.1,
            "assertions": [{"passed": True, "message": "ok"}],
        }
        with support.Isolated(
            case, {"BUD_RUNNER_TOKEN": self.station.token, "BUD_RUNNER_ACCOUNT": self.station.name}
        ):
            client = BudAPIClient(AuthManager(backend_url=self.bud.url))
            client.upload_results([row], test_run_id=run_id)
        rows = self.bud.results(run_id)
        support.need(
            self,
            len(rows),
            1,
            f"upload_results of one flat row stores one row on run {run_id}",
            f"upload_results of one flat row stores {len(rows)} rows on run {run_id}",
        )
        stored = {k: rows[0][k] for k in ("test_class", "test_method", "passed", "assertions")}
        given = {k: row[k] for k in ("test_class", "test_method", "passed", "assertions")}
        support.check(
            self,
            stored,
            given,
            "Bud stores the flat row SmokeTest.bud_hello as given: class, step, outcome and checks",
            f"Bud stores the flat row as {stored}",
        )
