"""The pytest plugin and run-pytest: a real pytest session mapped to Bud results, uploaded, spooled
and replayed."""

import json
import re

import support
from budtestlibrary import BudTestCase

from bud_runner.pytest_plugin import comparison

UPLOADED = re.compile(r"pytest results uploaded to Bud run (\d+)")
CORE = ("passed", "skipped", "assertion_type", "expected", "actual", "result")
ONE_TEST = "def test_one():\n    assert 1 == 1\n"


def _core(entry):
    """Return the fields an assert statement and bud_assert must agree on."""
    return {k: entry[k] for k in CORE}


class PytestPlugin(BudTestCase):
    """One run-pytest session of the bench suite read back from Bud, plus the run fields, the
    refusals, the spool and the command."""

    def setUpClass(self):
        self.bud = support.Bud()
        self.station = self.bud.station("pytest")
        self.product = self.bud.product("Demo")
        self.run_id = self.bud.create_run(self.station, "Pytest bench")
        case = self._case("bench")
        self.bench = case.bud_runner(
            "run-pytest", "-b", self.bud.url, "--test-run-id", self.run_id, "test_bench.py"
        )
        self.results = {r["test_method"]: r for r in self.bud.results(self.run_id)}

    def _case(self, name, properties=""):
        """Return a case of the station with the bench suite as test_bench.py."""
        case = support.Case(name)
        case.give_station(self.station)
        case.write("app.properties", f"budRunnerAccount={self.station.name}\n{properties}")
        support.copy_fixture(case, "pytest_bench.py", "test_bench.py")
        return case

    def same(self, actual, expected, passed: str, failed_what: str) -> bool:
        """Record actual against expected; the failure names what was stored instead."""
        return support.check(
            self, actual, expected, passed, f"{failed_what}: {actual!r}, not {expected!r}"
        )

    def _new_run(self, before: set, command: str, done=None) -> dict:
        """Return the one run Bud created since before, stopping the step when there is not one."""
        new = self.bud.new_run_ids(before)
        detail = f" ({done!r})" if done is not None and len(new) != 1 else ""
        support.need(
            self,
            len(new),
            1,
            f"{command} makes Bud create one run",
            f"{command} made Bud create the runs {new}, not one{detail}",
        )
        return self.bud.run(new[0])

    def bud_a_pytest_run_maps_to_bud_results(self):
        """15 stored results, one class per node id, tc_id from the marker, outcome and assertion
        types."""
        command = f"bud-runner run-pytest --test-run-id {self.run_id} test_bench.py"
        support.exits(self, self.bench, 1, f"{command}, with pytest's code for failed tests,")
        self.same(
            len(self.results),
            15,
            f"Bud stores the 15 bench tests on run {self.run_id}",
            f"Bud stores this many results on run {self.run_id}",
        )
        measured = self.results["test_measures"]
        self.same(
            {k: measured[k] for k in ("test_class", "passed", "error_message")},
            {"test_class": "test_bench.py::test_measures", "passed": True, "error_message": None},
            "test_measures is stored under its node id test_bench.py::test_measures, passed",
            "test_measures is stored with",
        )
        metadata = measured["test_metadata"]
        self.same(
            {"tc_id": metadata["tc_id"], "pytest_outcome": metadata["pytest_outcome"]},
            {"tc_id": "PRJ-TC-001", "pytest_outcome": "passed"},
            "test_measures carries PRJ-TC-001 from its bloom marker and the outcome passed",
            "test_measures carries",
        )
        support.check_in(
            self,
            "bloom",
            metadata["pytest_markers"],
            "test_measures lists its bloom marker",
            f"test_measures lists the markers {metadata['pytest_markers']}",
        )
        for key in ("test_case_file", "test_case_class"):
            support.check_not_in(
                self,
                key,
                metadata,
                f"the stored metadata of test_measures has no {key}",
                f"the stored metadata of test_measures has {key}",
            )
        self.same(
            [a["assertion_type"] for a in measured["assertions"]],
            [
                "AssertEqual",
                "AssertIn",
                "AssertTrue",
                "AssertNotEqual",
                "AssertLess",
                "AssertGreater",
                "AssertNotIn",
                "AssertEqual",
                "AssertIn",
                "AssertInRange",
            ],
            "the ten checks of test_measures are stored with budtestlibrary's assertion types",
            "the checks of test_measures are stored as",
        )
        failed = [a["assertion_type"] for a in measured["assertions"] if not a["passed"]]
        self.same(
            failed,
            [],
            "every check of test_measures is stored as passed",
            "these checks of test_measures are stored as failed",
        )
        grouped = self.results["test_method"]
        self.same(
            {"test_class": grouped["test_class"], "tc_id": grouped["test_metadata"]["tc_id"]},
            {"test_class": "test_bench.py::TestGroup::test_method", "tc_id": "PRJ-TC-002"},
            "a class method is stored under its node id with PRJ-TC-002 from its short bloom "
            "marker",
            "TestGroup.test_method is stored with",
        )
        self.same(
            len({r["test_class"] for r in self.results.values()}),
            15,
            "each of the 15 tests is its own test class in Bud",
            "the 15 tests give this many classes",
        )

    def bud_assert_statements_and_bud_assert_give_the_same_records(self):
        """Stored entries of plain asserts equal those of bud_assert, with source file, line and
        code."""
        entries = self.results["test_measures"]["assertions"]
        plain_equal, plain_in, plain_true = entries[0], entries[1], entries[2]
        lt, gt, not_in, fixture_equal, fixture_in = (
            entries[4],
            entries[5],
            entries[6],
            entries[7],
            entries[8],
        )
        support.check(
            self,
            _core(plain_equal),
            _core(fixture_equal),
            "assert measured == 3 is stored like bud_assert.assertEqual(measured, 3)",
            f"assert == is stored as {_core(plain_equal)}, assertEqual as {_core(fixture_equal)}",
        )
        self.same(
            _core(plain_equal),
            {
                "passed": True,
                "skipped": False,
                "assertion_type": "AssertEqual",
                "expected": "3",
                "actual": "3",
                "result": "3",
            },
            "assert measured == 3 is a passed AssertEqual of 3 against 3",
            "assert measured == 3 is stored as",
        )
        support.check(
            self,
            _core(plain_in),
            _core(fixture_in),
            "assert 'b' in ... is stored like bud_assert.assertIn",
            f"assert in is stored as {_core(plain_in)}, assertIn as {_core(fixture_in)}",
        )
        self.same(
            {k: plain_in[k] for k in ("expected", "actual", "message")},
            {"expected": "'b' in container", "actual": "abc", "message": "contains b"},
            "assert 'b' in 'abc' keeps its expected value, actual value and message",
            "assert 'b' in 'abc' is stored with",
        )
        self.same(
            {k: plain_true[k] for k in ("expected", "actual")},
            {"expected": "True", "actual": "3"},
            "a truth assert stores True as expected and the value 3 as actual",
            "the truth assert is stored with",
        )
        self.same(
            sorted(plain_equal),
            sorted(fixture_equal),
            "an assert statement and bud_assert store the same fields",
            "the assert statement stores the fields",
        )
        self.same(
            {
                k: plain_equal[k]
                for k in ("source_file", "source_line", "source_function", "code_context")
            },
            {
                "source_file": "test_bench.py",
                "source_line": 7,
                "source_function": "test_measures",
                "code_context": "assert measured == 3",
            },
            "the assert statement points at test_bench.py line 7 in test_measures",
            "the assert statement points at",
        )
        self.same(
            fixture_equal["code_context"],
            "bud_assert.assertEqual(measured, 3)",
            "bud_assert.assertEqual stores its own line of code",
            "bud_assert.assertEqual stores the code",
        )
        self.same(
            [
                {"expected": lt["expected"], "actual": lt["actual"]},
                {"expected": gt["expected"], "actual": gt["actual"]},
                {"expected": not_in["expected"]},
            ],
            [
                {"expected": "< 5", "actual": "3"},
                {"expected": "> 1", "actual": "3"},
                {"expected": "'z' NOT in container"},
            ],
            "the less, greater and not-in asserts store budtestlibrary's expected texts",
            "the less, greater and not-in asserts are stored as",
        )

    def bud_an_asserted_value_is_recorded_as_bud_assert_records_it(self):
        """A truthiness assert is stored like assertTrue; a failing one too."""
        entries = self.results["test_values"]["assertions"]
        pairs = [(entries[i], entries[i + 1]) for i in range(0, len(entries), 2)]
        support.need(
            self,
            len(pairs),
            4,
            "test_values stores four pairs of assert and bud_assert entries",
            f"test_values stores {len(pairs)} pairs, not 4",
        )
        differing = [index for index, (p, f) in enumerate(pairs, 1) if _core(p) != _core(f)]
        self.same(
            differing,
            [],
            "each truthiness assert is stored like its bud_assert.assertTrue twin",
            "these pairs differ",
        )
        self.same(
            [p["actual"] for p, _ in pairs],
            ["abc", "[1, 2]", "True", "True"],
            "the truthiness asserts store the asserted values as actual",
            "the truthiness asserts store the actual values",
        )
        self.same(
            [p["assertion_type"] for p, _ in pairs],
            ["AssertTrue"] * 4,
            "each truthiness assert is stored as AssertTrue",
            "the truthiness asserts are stored as",
        )
        failed = self.results["test_value_fails"]["assertions"]
        self.same(
            [(a["assertion_type"], a["passed"], a["expected"], a["actual"]) for a in failed],
            [("AssertTrue", False, "True", "")],
            "a failing truthiness assert of an empty value is a failed AssertTrue with actual ''",
            "the failing truthiness assert is stored as",
        )

    def bud_a_failed_assert_carries_expected_actual_message_and_traceback(self):
        """A failed comparison is stored with expected, actual, message, code and traceback, and is
        the result's error."""
        failed = self.results["test_fails_a_check"]
        self.same(
            {"passed": failed["passed"], "outcome": failed["test_metadata"]["pytest_outcome"]},
            {"passed": False, "outcome": "failed"},
            "test_fails_a_check is stored as failed",
            "test_fails_a_check is stored with",
        )
        support.need(
            self,
            len(failed["assertions"]),
            1,
            "test_fails_a_check stores one entry",
            f"test_fails_a_check stores {len(failed['assertions'])} entries, not one",
        )
        entry = failed["assertions"][0]
        self.same(
            {
                k: entry[k]
                for k in ("passed", "assertion_type", "expected", "actual", "code_context")
            },
            {
                "passed": False,
                "assertion_type": "AssertEqual",
                "expected": "[1, 3]",
                "actual": "[1, 2]",
                "code_context": "assert values == [1, 3]",
            },
            "the failed assert values == [1, 3] is stored with [1, 3] expected and [1, 2] actual",
            "the failed assert is stored as",
        )
        start = "assert [1, 2] == [1, 3]"
        self.same(
            entry["message"][: len(start)],
            start,
            f"the failed assert's message starts with {start!r}",
            "the failed assert's message starts with",
        )
        for part in ("test_bench.py", "AssertionError"):
            support.says(self, part, entry["traceback"], "the failed assert's traceback")
        self.same(
            {
                "same error": failed["error_message"] == entry["message"],
                "same traceback": failed["traceback"] == entry["traceback"],
            },
            {"same error": True, "same traceback": True},
            "the test's error and traceback are the failed assert's message and traceback",
            "the test's error and traceback compared with the failed assert",
        )

    def bud_a_failed_bud_assert_goes_on_and_fails_the_test(self):
        """A soft failure goes on, abort_on_fail stops, a teardown check errors; as stored in
        Bud."""
        soft = self.results["test_soft_failure_goes_on"]
        self.same(
            {
                "passed": soft["passed"],
                "entries": [(a["assertion_type"], a["passed"]) for a in soft["assertions"]],
            },
            {"passed": False, "entries": [("AssertEqual", False), ("AssertTrue", True)]},
            "after a failed soft check the test goes on to its next check and fails",
            "test_soft_failure_goes_on is stored with",
        )
        self.same(
            soft["error_message"],
            "[AssertEqual] EXPECTED: 2 | ACTUAL: 1 | MESSAGE: first",
            "the soft failure is the test's error",
            "the error of test_soft_failure_goes_on is",
        )
        support.check_match(
            self,
            r"\S",
            soft["assertions"][0]["traceback"] or "",
            "the failed soft check carries a traceback",
            "the failed soft check carries no traceback",
        )
        abort = self.results["test_abort_on_fail_stops"]
        self.same(
            [(a["assertion_type"], a["passed"]) for a in abort["assertions"]],
            [("AssertEqual", False)],
            "abort_on_fail stops the test at its failed check",
            "test_abort_on_fail_stops stores the entries",
        )
        self.same(
            abort["error_message"],
            "[AssertEqual] EXPECTED: 2 | ACTUAL: 1 | MESSAGE: stop",
            "the aborting check is the test's error",
            "the error of test_abort_on_fail_stops is",
        )
        after = self.results["test_teardown_check"]
        self.same(
            {
                k: v
                for k, v in (
                    ("passed", after["passed"]),
                    ("outcome", after["test_metadata"]["pytest_outcome"]),
                    ("error_message", after["error_message"]),
                )
            },
            {
                "passed": False,
                "outcome": "error",
                "error_message": "[AssertEqual] EXPECTED: 2 | ACTUAL: 1 | MESSAGE: after",
            },
            "a failed check in a fixture teardown makes the test an error with that check as error",
            "test_teardown_check is stored with",
        )
        support.says(
            self, "ERROR at teardown of test_teardown_check", self.bench.out, "pytest's output"
        )

    def bud_a_failed_bud_assert_in_an_xfail_test_is_its_expected_failure(self):
        """pytest counts 4 passed, 1 skipped, 4 xfailed, 5 failed and 2 errors; the three xfailed
        soft checks are stored skipped."""
        summary = self.bench.out.strip().splitlines()[-1]
        counts = {word: int(number) for number, word in re.findall(r"(\d+) (\w+)", summary)}
        self.same(
            counts,
            {"passed": 4, "skipped": 1, "xfailed": 4, "failed": 5, "errors": 2},
            "pytest's summary of the bench counts 4 passed, 1 skipped, 4 xfailed, 5 failed and 2 "
            "errors (the fixture setup and the teardown check)",
            f"pytest's summary of the bench ({summary}) counts",
        )
        for name in (
            "test_expected_soft_failure",
            "test_expected_strict_soft_failure",
            "test_expected_abort",
        ):
            result = self.results[name]
            first = result["assertions"][0]
            self.same(
                {
                    "outcome": result["test_metadata"]["pytest_outcome"],
                    "skipped": result["test_metadata"]["skipped"],
                    "first entry": (first["assertion_type"], first["passed"]),
                },
                {"outcome": "xfailed", "skipped": True, "first entry": ("AssertEqual", False)},
                f"{name} is stored as an expected failure: xfailed and skipped, its failed check "
                "kept",
                f"{name} is stored with",
            )
        self.same(
            self.results["test_expected_strict_soft_failure"]["error_message"],
            "strict soft check",
            "the xfail reason strict soft check is the error of test_expected_strict_soft_failure",
            "the error of test_expected_strict_soft_failure is",
        )

    def bud_exceptions_skips_xfail_and_fixture_errors(self):
        """An exception, skips, an xfail and a fixture error as stored; the run's skipped count is
        5."""
        raised = self.results["test_raises"]
        self.same(
            [
                (a["assertion_type"], a["passed"], a["message"], a["source_function"])
                for a in raised["assertions"]
            ],
            [("ValueError", False, "bad value", "test_raises")],
            "a raised ValueError is stored as one failed ValueError entry with its message",
            "test_raises stores the entries",
        )
        support.says(
            self,
            "ValueError",
            raised["assertions"][0]["traceback"],
            "the traceback of the ValueError entry",
        )
        self.same(
            raised["error_message"],
            "bad value",
            "the error of test_raises is bad value",
            "the error of test_raises is",
        )
        skipped = self.results["test_skipped"]
        self.same(
            {
                "passed": skipped["passed"],
                "skipped": skipped["test_metadata"]["skipped"],
                "outcome": skipped["test_metadata"]["pytest_outcome"],
                "error_message": skipped["error_message"],
            },
            {
                "passed": True,
                "skipped": True,
                "outcome": "skipped",
                "error_message": "not on this bench",
            },
            "test_skipped is stored as skipped with the reason not on this bench",
            "test_skipped is stored with",
        )
        self.same(
            [(a["assertion_type"], a["skipped"], a["message"]) for a in skipped["assertions"]],
            [("Skip", True, "not measured here"), ("Skip", True, "not on this bench")],
            "test_skipped stores its soft skip and its pytest.skip as two Skip entries",
            "test_skipped stores the entries",
        )
        xfail = self.results["test_expected_failure"]
        self.same(
            {
                "outcome": xfail["test_metadata"]["pytest_outcome"],
                "skipped": xfail["test_metadata"]["skipped"],
                "entries": [a["assertion_type"] for a in xfail["assertions"]],
            },
            {"outcome": "xfailed", "skipped": True, "entries": ["Skip"]},
            "test_expected_failure is stored as xfailed and skipped with one Skip entry",
            "test_expected_failure is stored with",
        )
        setup = self.results["test_setup_error"]
        self.same(
            {
                "passed": setup["passed"],
                "outcome": setup["test_metadata"]["pytest_outcome"],
                "error_message": setup["error_message"],
                "entries": [(a["assertion_type"], a["metadata"]) for a in setup["assertions"]],
            },
            {
                "passed": False,
                "outcome": "error",
                "error_message": "fixture broke",
                "entries": [("RuntimeError", {"phase": "setup"})],
            },
            "a fixture that raises is stored as an error with one RuntimeError entry of the setup "
            "phase",
            "test_setup_error is stored with",
        )
        self.same(
            self.bud.run(self.run_id)["skipped_tests"],
            5,
            f"Bud counts 5 skipped test cases on run {self.run_id}: the skip and the four xfails",
            f"Bud counts skipped test cases on run {self.run_id}",
        )

    def bud_the_payload_names_the_suite_product_and_run(self):
        """--test-run-id puts the results on that run; a run Bud creates carries product, ref and
        the rootdir name; --suite-name and app.properties product are used."""
        self.same(
            len(self.results),
            15,
            f"run-pytest --test-run-id {self.run_id} puts the 15 results on that run",
            f"run {self.run_id} holds this many results",
        )
        case = self._case("payload")
        before = self.bud.run_ids()
        command = "bud-runner run-pytest --product-id <Demo> --ref-sw-under-test v2.4.1"
        done = case.bud_runner(
            "run-pytest",
            "-b",
            self.bud.url,
            "--product-id",
            self.product,
            "--ref-sw-under-test",
            "v2.4.1",
            "test_bench.py",
        )
        run = self._new_run(before, command, done)
        self.same(
            {
                k: run[k]
                for k in ("name", "product_id", "ref_software_under_test", "runner_account")
            },
            {
                "name": f"Demo - {case.cwd.name}",
                "product_id": self.product,
                "ref_software_under_test": "v2.4.1",
                "runner_account": self.station.name,
            },
            f"the run of {command} is named after the product and the rootdir, carries v2.4.1 and "
            "the station",
            f"the run of {command} has",
        )
        props = self._case("payload-props", f"productId={self.product}\n")
        before = self.bud.run_ids()
        command = "bud-runner run-pytest --suite-name Bench with productId in app.properties"
        props.bud_runner("run-pytest", "-b", self.bud.url, "--suite-name", "Bench", "test_bench.py")
        run = self._new_run(before, command)
        self.same(
            {"name": run["name"], "product_id": run["product_id"]},
            {"name": "Demo - Bench", "product_id": self.product},
            f"the run of {command} is named Demo - Bench and carries the app.properties product",
            f"the run of {command} has",
        )

    def bud_the_session_is_uploaded_with_the_skipped_count(self):
        """run-pytest with a station and app.properties product: 15 results, product, station, 5
        skipped, and the stderr line."""
        case = self._case("session", f"productId={self.product}\n")
        command = "bud-runner run-pytest test_bench.py with productId in app.properties"
        done = case.bud_runner("run-pytest", "-b", self.bud.url, "test_bench.py")
        found = UPLOADED.search(done.err)
        support.need(
            self,
            found is not None,
            True,
            f"{command} prints the Bud run it uploaded to",
            f"{command} prints no upload line: {done!r}",
        )
        run = self.bud.run(int(found.group(1)))
        self.same(
            {
                "product_id": run["product_id"],
                "runner_account": run["runner_account"],
                "skipped_tests": run["skipped_tests"],
                "results": len(self.bud.results(run["id"])),
            },
            {
                "product_id": self.product,
                "runner_account": self.station.name,
                "skipped_tests": 5,
                "results": 15,
            },
            f"the run of {command} carries the product, the station, 5 skipped and 15 results",
            f"the run of {command} has",
        )

    def bud_a_failed_upload_is_spooled(self):
        """Bud unreachable with --test-run-id 7: one spooled payload naming run 7, pytest's own exit
        code."""
        case = self._case("spool")
        command = "bud-runner run-pytest --test-run-id 7 against a closed port"
        done = case.bud_runner(
            "run-pytest",
            "-b",
            f"http://127.0.0.1:{support.closed_port()}",
            "--test-run-id",
            "7",
            "test_bench.py",
            timeout=240,
        )
        support.exits(self, done, 1, f"{command}, with pytest's code for failed tests,")
        spooled = case.spooled()
        support.need(
            self,
            len(spooled),
            1,
            f"{command} spools one result payload",
            f"{command} spooled {len(spooled)} payloads",
        )
        self.same(
            json.loads(spooled[0].read_text())["test_run_id"],
            7,
            "the spooled payload names run 7",
            "the spooled payload names run",
        )
        self.spool_case = case

    def bud_run_pytest_replays_the_spool_first(self):
        """The next run-pytest against Bud replays the spooled payload (onto a run of this station)
        and empties the spool."""
        case = getattr(self, "spool_case", None)
        support.need(
            self,
            case is not None,
            True,
            "the spool case ran first and left a spooled payload",
            "the spool case did not finish, so there is no spooled payload to replay",
        )
        spooled = case.spooled()[0]
        body = json.loads(spooled.read_text())
        target = self.bud.create_run(self.station, "Replayed")
        body["test_run_id"] = target
        spooled.write_text(json.dumps(body))
        case.write("test_bench.py", ONE_TEST)
        command = "the next bud-runner run-pytest against Bud"
        done = case.bud_runner("run-pytest", "-b", self.bud.url, "test_bench.py")
        support.says(self, "✓ Replayed spooled results from", done.out, command)
        self.same(
            len(self.bud.results(target)),
            15,
            f"the 15 spooled results reach Bud on run {target}",
            f"Bud holds this many results on run {target}",
        )
        self.same(
            [p.name for p in case.spooled()],
            [],
            "the spool is empty after the replay",
            "the spool still holds",
        )

    def bud_an_upload_error_never_changes_the_exit_code(self):
        """pytest with the plugin and a URL it refuses: exit 0 and the warning."""
        case = support.Case("upload-error")
        case.write("test_one.py", ONE_TEST)
        command = "pytest -p bud_runner.pytest_plugin --bud-backend-url=http://bud.example.com"
        done = case.command(
            support.PYTHON,
            "-m",
            "pytest",
            "-p",
            "bud_runner.pytest_plugin",
            "--bud-backend-url=http://bud.example.com",
            "test_one.py",
        )
        support.exits(self, done, 0, f"{command} on a passing test, keeping pytest's code,")
        support.says(self, "Could not report the pytest run to Bud", done.err, command)

    def bud_the_plugin_warns_when_the_pass_hook_is_off(self):
        """pytest with the plugin but without enable_assertion_pass_hook: the warning, exit 0."""
        case = support.Case("pass-hook")
        case.write("test_one.py", ONE_TEST)
        command = (
            "pytest -p bud_runner.pytest_plugin --bud-no-upload without enable_assertion_pass_hook"
        )
        done = case.command(
            support.PYTHON,
            "-m",
            "pytest",
            "-p",
            "bud_runner.pytest_plugin",
            "--bud-no-upload",
            "test_one.py",
        )
        support.exits(self, done, 0, command)
        support.says(self, "enable_assertion_pass_hook is off", done.out + done.err, command)

    def bud_comparison_follows_budtestlibrary(self):
        """comparison gives budtestlibrary's type, expected and actual for six operators."""
        for operator, left, right, expected in (
            ("==", 1, 2, ("AssertEqual", 2, 1)),
            ("!=", 1, 2, ("AssertNotEqual", "!= 2", 1)),
            ("in", "a", "abc", ("AssertIn", "'a' in container", "abc")),
            ("not in", "a", "abc", ("AssertNotIn", "'a' NOT in container", "abc")),
            ("<", 1, 2, ("AssertLess", "< 2", 1)),
            (">", 1, 2, ("AssertGreater", "> 2", 1)),
        ):
            got = comparison(operator, left, right)
            support.check(
                self,
                got,
                expected,
                f"comparison({operator!r}, {left!r}, {right!r}) gives budtestlibrary's {expected}",
                f"comparison({operator!r}, {left!r}, {right!r}) gives {got}, not {expected}",
            )

    def bud_run_pytest_command_passes_pytest_arguments_and_exit_code(self):
        """run-pytest --no-upload tests/ -k smoke: exit 1, only the smoke tests ran, bytecode under
        $HOME/.bud/pycache."""
        case = support.Case("run-pytest")
        case.write(
            "tests/test_bench.py",
            "def test_smoke_passes():\n    assert True\n\n\ndef test_smoke_fails():\n    assert 1 "
            "== 2\n"
            "\n\ndef test_slow():\n    assert True\n",
        )
        command = "bud-runner run-pytest --no-upload tests/ -k smoke -v"
        done = case.bud_runner(
            "run-pytest",
            "--no-upload",
            "tests/",
            "-k",
            "smoke",
            "-v",
            env={"PYTHONDONTWRITEBYTECODE": None},
        )
        support.exits(self, done, 1, f"{command}, with pytest's code for one failed test,")
        support.says(self, "test_smoke_passes PASSED", done.out, command)
        support.says(self, "test_smoke_fails FAILED", done.out, command)
        support.check_not_in(
            self,
            "test_slow",
            done.out.replace("deselected", ""),
            f"{command} does not run test_slow",
            f"{command} ran test_slow",
        )
        cached = [p.name for p in (case.home / ".bud" / "pycache").rglob("test_bench*.pyc")]
        self.same(
            len(cached),
            1,
            "the bytecode of tests/test_bench.py is under $HOME/.bud/pycache",
            "the bytecode files of test_bench under $HOME/.bud/pycache number",
        )
        beside = [str(p) for p in case.cwd.rglob("__pycache__")]
        self.same(
            beside,
            [],
            "no __pycache__ is written beside the tests",
            "__pycache__ folders beside the tests",
        )
