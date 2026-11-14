"""The Robot Framework listener: real Robot runs mapped to Bud results, the upload of the results,
skips and reports, the spool, the assertion names, the call chain of a failure, the caps and the
run-robot command, with Bud's client, the station identity and the spool mocked."""

import contextlib
import io
import os
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import robot
from budtestlibrary import BudTestCase
from typer.testing import CliRunner

from bud_runner import api_client, auth, cli
from bud_runner import robot_listener as listener_module
from bud_runner.robot_listener import BudListener, assert_name, assertion_for, is_check
from tests.config import RobotListener as config
from tests.messages import RobotListener as messages
from tests.parameters import RobotListener as parameters


class _Bud:
    """A double of Bud's client that records the results, run updates and artifacts sent."""

    def __init__(self, fail: bool = False):
        self.calls: list = []
        self.fail = fail

    def upload_results_payload(self, payload):
        """Record the results; raise when Bud is down."""
        self.calls.append(("results", payload))
        if self.fail:
            raise RuntimeError(messages.BACKEND_DOWN)
        return {"test_run_id": config.UPLOADED_RUN}

    def update_test_run(self, run_id, **fields):
        """Record the run update."""
        self.calls.append(("update", run_id, fields))

    def upload_artifact(self, path, run_id=None):
        """Record the artifact's file name and run."""
        self.calls.append(("artifact", Path(path).name, run_id))


class RobotListener(BudTestCase):
    """The Robot Framework listener and the run-robot command."""

    def setUp(self):
        """A new folder for the step's Robot files and output."""
        self.folder = Path(os.environ[config.WORK_DIR_SETTING]) / config.FOLDER / uuid.uuid4().hex
        self.folder.mkdir(parents=True)

    def run_robot(self, listener, text: str, name: str = "bench.robot", **resources) -> int:
        """Write the suite and its resources to the step's folder and run Robot quietly."""
        for resource, content in resources.items():
            (self.folder / resource.replace("_", ".")).write_text(content, encoding="utf-8")
        suite = self.folder / name
        suite.write_text(text, encoding="utf-8")
        return robot.run(
            str(suite),
            listener=listener,
            outputdir=str(self.folder / "out"),
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )

    @contextlib.contextmanager
    def bud(self, fail: bool = False):
        """Mock Bud's client, the station identity, the spool and HOME; yield what was made and
        spooled."""
        made: list = []
        spooled: list = []

        def client(auth_manager):
            made.append(_Bud(fail))
            return made[-1]

        station = SimpleNamespace(runner_account=config.STATION, product_id=config.PRODUCT_ID)
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {"HOME": str(self.folder / "home")}))
            stack.enter_context(patch.object(api_client, "BudAPIClient", client))
            stack.enter_context(patch.object(auth, "AuthManager", return_value=station))
            stack.enter_context(
                patch.object(
                    cli,
                    "_spool_results_payload",
                    lambda payload: spooled.append(payload) or config.SPOOL_FILE,
                )
            )
            yield SimpleNamespace(made=made, spooled=spooled)

    def keyword(self, name: str, status: str, args=(), message: str = "", owner="BuiltIn"):
        """A library keyword as Robot hands it to the listener."""
        return SimpleNamespace(name=name, owner=owner, args=args, status=status, message=message)

    def bud_a_robot_run_maps_to_bud_results(self):
        """Each Robot test becomes one Bud result with its checks, tags, failure and skip, the
        run's files, and a payload carrying the suite, software and product."""
        listener = BudListener(upload="false", product_id=parameters.PRODUCT_ARGUMENT)
        code = self.run_robot(listener, parameters.SUITE)
        self.assertEqual(code, parameters.ROBOT_FAILED, "Robot exits 1 for one failed test")
        measured, failed, skipped = listener.results
        self.assertEqual(
            (measured["test_class"], measured["test_method"]),
            parameters.MEASURED_NAMES,
            "the test's class and method names",
        )
        self.assertNotIn(
            member="test_case_file", container=measured["metadata"], msg="no test case file"
        )
        self.assertNotIn(
            member="test_case_class", container=measured["metadata"], msg="no test case class"
        )
        self.assertEqual(
            len({result["test_class"] for result in listener.results}),
            parameters.CLASSES,
            "each test has its own class",
        )
        self.assertTrue(measured["passed"] is True, "the measuring test passed")
        self.assertTrue(measured["error_message"] is None, "it has no error")
        self.assertEqual(measured["metadata"]["tc_id"], parameters.TC_ID, "its Bloom test case")
        self.assertEqual(measured["metadata"]["robot_tags"], parameters.TAGS, "its Robot tags")
        self.assertEqual(
            [entry["assertion_type"] for entry in measured["assertions"]],
            parameters.MEASURED_TYPES,
            "its entries in order",
        )
        self.assertTrue(
            all(
                "name" not in entry and "args" not in entry and entry["metadata"] == {}
                for entry in measured["assertions"]
            ),
            "the entries carry no keyword name, arguments or metadata",
        )
        info, numbers, truth, contains = measured["assertions"]
        self.assertTrue(info["info"] is True, "Set Variable is information")
        self.assertTrue(info["passed"] is True, "Set Variable passed")
        self.assertNotIn(member="info", container=numbers, msg="a check is not information")
        self.assertTrue(numbers["skipped"] is False, "the check is not skipped")
        self.assertEqual(
            (numbers["actual"], numbers["expected"]), parameters.NUMBERS, "compared values"
        )
        self.assertTrue(numbers["source_file"].endswith("bench.robot"), "its file is the suite")
        self.assertEqual(numbers["source_line"], parameters.NUMBERS_LINE, "its line")
        self.assertEqual(
            numbers["source_function"], parameters.NUMBERS_FUNCTION, "its test as function"
        )
        self.assertEqual(numbers["code_context"], parameters.NUMBERS_CONTEXT, "its source line")
        self.assertTrue(numbers["traceback"] is None, "a passed check has no traceback")
        self.assertTrue(bool(numbers["timestamp"]), "the check has a timestamp")
        self.assertEqual(
            (truth["actual"], truth["expected"]), parameters.TRUTH, "Should Be True's values"
        )
        self.assertEqual(
            (contains["actual"], contains["expected"]),
            parameters.CONTAINS,
            "Should Contain's values",
        )
        self.assertEqual(
            (contains["source_function"], contains["source_line"]),
            parameters.CONTAINS_AT,
            "a keyword's check is placed in the keyword",
        )
        self.assertTrue(measured["traceback"] is None, "the passing test has no traceback")
        self.assertTrue(failed["passed"] is False, "the failing test failed")
        self.assertEqual(failed["error_message"], parameters.FAILED_ERROR, "its error")
        (check,) = failed["assertions"]
        self.assertTrue(check["passed"] is False, "its check failed")
        self.assertEqual(check["assertion_type"], "AssertEqual", "its check is AssertEqual")
        self.assertEqual(
            check["traceback"].splitlines()[1:],
            [
                f'  File "{check["source_file"]}", line {parameters.FAILED_LINE}, in Fails a check',
                *parameters.FAILED_FRAMES,
            ],
            "the traceback names the test, its line and the error",
        )
        self.assertEqual(failed["traceback"], check["traceback"], "the test carries it")
        self.assertNotIn(member="tc_id", container=failed["metadata"], msg="no test case id")
        self.assertTrue(skipped["passed"] is True, "a skipped test counts as passed")
        self.assertTrue(skipped["metadata"]["skipped"] is True, "it is marked skipped")
        self.assertEqual(skipped["error_message"], parameters.SKIP_MESSAGE, "its skip reason")
        (skip,) = skipped["assertions"]
        self.assertEqual(
            (skip["assertion_type"], skip["skipped"], skip["passed"]),
            parameters.SKIP_ENTRY,
            "the Skip entry",
        )
        self.assertEqual(skip["message"], parameters.SKIP_MESSAGE, "the Skip entry's message")
        self.assertTrue(skipped["traceback"] is None, "a skip has no traceback")
        self.assertEqual(listener.skipped, parameters.SKIPPED, "one test was skipped")
        self.assertEqual(
            {path.name for path in listener.files}, parameters.FILES, "Robot's three files"
        )
        body = listener.payload(config.STATION)
        self.assertEqual(body["test_suite_name"], parameters.SUITE_NAME, "the suite's name")
        self.assertEqual(
            body["ref_software_under_test"],
            parameters.SOFTWARE_UNDER_TEST,
            "the software under test from Metadata",
        )
        self.assertEqual(body["product_id"], parameters.PRODUCT_ID, "the listener's product")
        self.assertEqual(body["runner_account"], config.STATION, "the station")
        self.assertTrue(body["test_run_id"] is None, "no run is named")
        self.assertEqual(
            listener.payload(config.STATION, parameters.RUN_ID)["product_id"],
            parameters.PRODUCT_ID,
            "the listener's product wins over the station's",
        )
        unset = BudListener(upload="false")
        unset.results = listener.results
        self.assertEqual(
            unset.payload(None, parameters.RUN_ID)["product_id"],
            parameters.RUN_ID,
            "without a listener product the station's is used",
        )
        self.assertNotIn(
            member="product_id",
            container=unset.payload(None, None),
            msg="without any product none is sent",
        )

    def bud_close_uploads_results_skips_and_reports(self):
        """Closing sends the results, then the skip count, then Robot's files to the new run."""
        with self.bud() as sent:
            self.run_robot(BudListener(backend=config.BACKEND), parameters.SUITE)
        calls = sent.made[0].calls
        self.assertEqual(calls[0][0], "results", "the results go first")
        self.assertEqual(len(calls[0][1]["results"]), parameters.RESULTS, "three results")
        self.assertEqual(calls[0][1]["product_id"], config.PRODUCT_ID, "the station's product")
        self.assertEqual(calls[0][1]["test_suite_name"], parameters.SUITE_NAME, "the suite")
        self.assertEqual(
            calls[1],
            ("update", config.UPLOADED_RUN, {"skipped_tests": parameters.SKIPPED}),
            "the run is updated with one skip",
        )
        self.assertEqual(
            sorted(call[1] for call in calls[2:]),
            parameters.REPORT_FILES,
            "Robot's three files follow",
        )
        self.assertTrue(
            all(call[2] == config.UPLOADED_RUN for call in calls[2:]),
            "the files go to run 42",
        )

    def bud_a_failed_upload_is_spooled(self):
        """When Bud is down the results are spooled for the named run and nothing else is sent."""
        with self.bud(fail=True) as sent:
            self.run_robot(BudListener(test_run_id=parameters.SPOOL_RUN), parameters.SUITE)
        self.assertEqual(len(sent.spooled), 1, "one payload is spooled")
        self.assertEqual(sent.spooled[0]["test_run_id"], parameters.SPOOL_RUN_ID, "for run 7")
        self.assertEqual(
            [call[0] for call in sent.made[0].calls], ["results"], "only the results were tried"
        )

    def bud_close_never_raises_and_skips_empty_runs(self):
        """An empty run sends nothing, and a failing identity is reported without raising."""
        listener = BudListener(artifacts="no")
        nobody = SimpleNamespace(runner_account=None, product_id=None)
        errors = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stderr(errors))
            stack.enter_context(patch.object(auth, "AuthManager", return_value=nobody))
            stack.enter_context(patch.object(api_client, "BudAPIClient", return_value=_Bud()))
            listener.close()
        self.assertIn(
            member=messages.NOTHING_UPLOADED,
            container=errors.getvalue(),
            msg=f"stderr says {messages.NOTHING_UPLOADED!r}",
        )

        def no_vault(backend_url=None):
            raise RuntimeError(messages.NO_VAULT)

        errors = io.StringIO()
        with contextlib.redirect_stderr(errors), patch.object(auth, "AuthManager", no_vault):
            listener.close()
        self.assertIn(
            member=messages.COULD_NOT_REPORT,
            container=errors.getvalue(),
            msg=f"stderr says {messages.COULD_NOT_REPORT!r}",
        )
        self.assertTrue(listener.upload_artifacts is False, "artifacts=no turns the files off")

    def bud_a_short_bloom_tag_names_the_test_case(self):
        """A bloom:PRJ-002 tag names the test case PRJ-TC-002."""
        listener = BudListener(upload="false")
        self.run_robot(listener, parameters.SHORT_TAG_SUITE, name="short.robot")
        (result,) = listener.results
        self.assertEqual(result["metadata"]["tc_id"], parameters.SHORT_TC_ID, "the test case")
        self.assertEqual(result["metadata"]["robot_tags"], parameters.SHORT_TAGS, "the tags")

    def bud_assertions_are_mapped(self):
        """Library checks, negations, short calls and lengths map to Bud entries, and only
        checks count as checks."""
        other = assertion_for("Page Should Contain", "Browser", ["Welcome"], True, "")
        self.assertEqual(other["assertion_type"], parameters.OTHER_TYPE, "a library check")
        self.assertEqual(other["metadata"], {}, "no metadata")
        self.assertNotIn(member="expected", container=other, msg="no expected value")
        self.assertTrue(other["message"] is None, "no message")
        self.assertTrue(other["traceback"] is None, "no traceback")
        negative = assertion_for(
            "Should Not Be True", "BuiltIn", ["${x}"], False, "boom", {"traceback": "tb"}
        )
        self.assertEqual(
            (negative["assertion_type"], negative["expected"], negative["actual"]),
            parameters.NEGATIVE,
            "a negation",
        )
        self.assertEqual(
            (negative["message"], negative["traceback"]),
            parameters.NEGATIVE_FAILURE,
            "its failure",
        )
        short = assertion_for("Should Be Equal", "BuiltIn", ["only-one"], True, "")
        self.assertEqual(short["assertion_type"], "AssertEqual", "a one-argument equality")
        self.assertNotIn(member="expected", container=short, msg="has no expected value")
        length = assertion_for("Length Should Be", "BuiltIn", ["[1, 2]", "2"], True, "")
        self.assertEqual(
            (length["assertion_type"], length["expected"]), parameters.LENGTH, "a length check"
        )
        for name in parameters.CHECKS_KEYWORDS:
            self.assertTrue(is_check(name), f"{name!r} is a check")
        for name in parameters.NOT_CHECKS:
            self.assertFalse(is_check(name), f"{name!r} is not a check")

    def bud_assert_names_never_say_should(self):
        """Keyword names map to Assert names without Should."""
        self.assertEqual(
            {name: assert_name(name) for name in parameters.ASSERT_NAMES},
            parameters.ASSERT_NAMES,
            "each keyword's Assert name",
        )

    def bud_failures_carry_the_call_chain(self):
        """A failure in a resource keyword traces from the test to the keyword; keywords that
        check nothing are information."""
        listener = BudListener(upload="false")
        self.run_robot(
            listener, parameters.DEEP, name="deep.robot", checks_resource=parameters.CHECKS
        )
        deep, hard = listener.results
        log, check = deep["assertions"]
        self.assertEqual(
            (log["assertion_type"], log["info"], log["code_context"]),
            parameters.DEEP_LOG,
            "Log is information",
        )
        self.assertTrue(log["source_file"].endswith("checks.resource"), "Log is in the resource")
        self.assertEqual(log["source_line"], parameters.DEEP_LOG_LINE, "Log's line")
        self.assertEqual(check["assertion_type"], "AssertIn", "the check is AssertIn")
        self.assertTrue(check["passed"] is False, "the check failed")
        self.assertTrue(
            check["source_file"].endswith("checks.resource"), "the check is in the resource"
        )
        self.assertEqual(check["source_line"], parameters.DEEP_CHECK_LINE, "the check's line")
        frames = check["traceback"].splitlines()
        self.assertTrue(frames[1].endswith(parameters.DEEP_CALLER), "the test calls first")
        self.assertEqual(frames[2], parameters.DEEP_CALL, "with the keyword call")
        self.assertTrue(frames[3].endswith(parameters.DEEP_CALLEE), "then the keyword")
        self.assertEqual(frames[4], parameters.DEEP_CHECK, "with the failed check")
        self.assertEqual(frames[5], deep["error_message"], "then the error")
        self.assertEqual(deep["traceback"], check["traceback"], "the test carries it")
        (broken,) = hard["assertions"]
        self.assertEqual(
            (broken["assertion_type"], broken["passed"], broken["message"]),
            parameters.BROKEN,
            "Fail is a failed entry",
        )
        self.assertNotIn(member="info", container=broken, msg="Fail is not information")
        self.assertTrue(broken["traceback"].endswith(parameters.BROKEN[2]), "its traceback")
        self.assertTrue(hard["passed"] is False, "the test failed")
        self.assertEqual(hard["traceback"], broken["traceback"], "the test carries it")

    def bud_the_traceback_is_the_failure_that_ended_the_test(self):
        """An ignored failure is information; the failure that ended the test is its traceback."""
        listener = BudListener(upload="false")
        self.run_robot(listener, parameters.TOLERATED, name="tolerated.robot")
        (result,) = listener.results
        self.assertEqual(result["error_message"], parameters.REAL_PROBLEM, "the ending error")
        self.assertTrue(
            result["traceback"].endswith(parameters.REAL_PROBLEM), "the traceback ends with it"
        )
        self.assertIn(
            member=parameters.REAL_PROBLEM_AT,
            container=result["traceback"],
            msg="the traceback names its line",
        )
        handled, wrapper, real = result["assertions"]
        self.assertEqual(
            (wrapper["assertion_type"], wrapper["info"]), parameters.WRAPPER, "the wrapper"
        )
        self.assertEqual(
            (handled["assertion_type"], handled["info"], handled["passed"]),
            parameters.HANDLED_FAIL,
            "the ignored failure is information",
        )
        self.assertEqual(handled["message"], parameters.FIRST_PROBLEM, "its message")
        self.assertTrue(handled["traceback"] is None, "and no traceback")
        self.assertEqual(
            (real["assertion_type"], real["passed"]), parameters.REAL_FAIL, "the real failure"
        )

    def bud_handled_failures_are_information(self):
        """Expected and caught failures are information; every failed test has a failed entry."""
        listener = BudListener(upload="false")
        self.run_robot(listener, parameters.HANDLED, name="handled.robot")
        expects, tries, missing, empty, propagated, retried, teardown = listener.results
        self.assertTrue(expects["passed"] is True, "an expected error passes")
        self.assertTrue(expects["traceback"] is None, "with no traceback")
        self.assertTrue(
            all(entry["passed"] for entry in expects["assertions"]), "all its entries pass"
        )
        inner = [e for e in expects["assertions"] if e["assertion_type"] == "AssertEqual"]
        self.assertTrue(bool(inner), "the expected check is recorded")
        self.assertTrue(all(entry["info"] for entry in inner), "as information")
        self.assertTrue(tries["passed"] is True, "a caught failure passes")
        self.assertTrue(tries["traceback"] is None, "with no traceback")
        self.assertEqual(
            [(e["assertion_type"], e["info"]) for e in tries["assertions"]],
            parameters.TRY_ENTRIES,
            "its entries are information",
        )
        self.assertTrue(missing["passed"] is False, "a missing keyword fails")
        (unknown,) = missing["assertions"]
        self.assertEqual(
            unknown["assertion_type"], parameters.MISSING_KEYWORD, "the keyword is named"
        )
        self.assertTrue(unknown["passed"] is False, "as a failed entry")
        self.assertTrue(
            unknown["traceback"].endswith(missing["error_message"]), "its traceback ends in it"
        )
        self.assertTrue(empty["passed"] is False, "an empty test fails")
        (fallback,) = empty["assertions"]
        self.assertEqual(
            (fallback["assertion_type"], fallback["passed"], fallback["message"]),
            ("Fail", False, empty["error_message"]),
            "with a Fail entry",
        )
        self.assertEqual(empty["traceback"], fallback["traceback"], "carrying its traceback")
        failures = [e for e in propagated["assertions"] if e["passed"] is False]
        self.assertEqual(
            [e["assertion_type"] for e in failures],
            parameters.PROPAGATED_FAILURES,
            "only the inner check fails",
        )
        self.assertEqual(
            [(e["assertion_type"], e.get("info")) for e in propagated["assertions"]],
            parameters.PROPAGATED_ENTRIES,
            "the wrapper is information",
        )
        attempts = [e for e in retried["assertions"] if e["assertion_type"] == "AssertEqual"]
        self.assertEqual(
            [entry["passed"] for entry in attempts],
            parameters.ATTEMPTS,
            "two tolerated attempts, then the failing one",
        )
        self.assertEqual(
            [entry["passed"] for entry in retried["assertions"]].count(False),
            1,
            "one failed entry",
        )
        self.assertIn(
            member=parameters.BODY_BROKE,
            container=teardown["error_message"],
            msg="the body's error is kept",
        )
        self.assertIn(
            member=parameters.TEARDOWN_BROKE,
            container=teardown["error_message"],
            msg="the teardown's error is kept",
        )
        self.assertTrue(
            teardown["traceback"].endswith(parameters.BODY_BROKE), "the body's failure is traced"
        )

    def bud_a_keyword_ending_in_skip_is_a_skipped_entry(self):
        """Skipped keywords are skipped entries; a skipped wrapper adds nothing."""
        listener = BudListener(upload="false")
        listener.start_test(None, None)
        for item in (
            self.keyword("Skip If", "SKIP", ("True",), "no bench"),
            self.keyword("Should Be True", "SKIP", ("x",), "later"),
            self.keyword("Run Keyword If", "SKIP", (), "no bench"),
        ):
            listener.start_library_keyword(None, None, item)
            listener.end_library_keyword(None, None, item)
        self.assertEqual(
            [(a["assertion_type"], a["skipped"], a["passed"]) for a in listener._assertions],
            parameters.SKIP_ENTRIES,
            "the skip and the skipped check",
        )

    def bud_depth_and_count_caps(self):
        """Keywords below the depth cap and beyond the count cap are dropped, as are keywords
        that did not run; long arguments are shortened."""
        listener = BudListener(upload="false")
        listener.start_test(None, None)
        check = self.keyword("Should Be True", "PASS", ("x",))
        for _ in range(listener_module.MAX_KEYWORD_DEPTH):
            listener.start_user_keyword(None, None, None)
        listener.start_library_keyword(None, None, check)
        listener.end_library_keyword(None, None, check)
        self.assertEqual(listener._assertions, [], "a check below the depth cap is dropped")
        listener._depth = 0
        with patch.object(listener_module, "MAX_ASSERTIONS_PER_TEST", parameters.ASSERTION_CAP):
            for _ in range(parameters.TRIES):
                listener.start_library_keyword(None, None, check)
                listener.end_library_keyword(None, None, check)
        self.assertEqual(
            len(listener._assertions), parameters.ASSERTION_CAP, "checks stop at the count cap"
        )
        not_run = self.keyword("Should Be True", "NOT RUN")
        listener._assertions = []
        listener.start_library_keyword(None, None, not_run)
        listener.end_library_keyword(None, None, not_run)
        self.assertEqual(listener._assertions, [], "a keyword that did not run is dropped")
        log = self.keyword("Log", "PASS", ("x",))
        listener.start_library_keyword(None, None, log)
        listener.end_library_keyword(None, None, log)
        self.assertEqual(
            [(a["assertion_type"], a["info"]) for a in listener._assertions],
            parameters.INFO_ENTRIES,
            "Log is information",
        )
        long_argument = listener_module._short(parameters.LONG_ARGUMENT)
        self.assertEqual(
            len(long_argument), listener_module.ARG_LIMIT, "a long argument is shortened"
        )
        self.assertTrue(long_argument.endswith(parameters.ELLIPSIS), "and ends with ...")

    def bud_run_robot_passes_robot_arguments_and_exit_code(self):
        """run-robot hands Robot the listener with its settings, then Robot's own arguments, and
        exits with Robot's code."""
        suite = self.folder / "bench.robot"
        suite.write_text(parameters.SUITE, encoding="utf-8")
        seen: dict = {}

        def run_cli(args, exit=True):
            seen["args"] = args
            return parameters.COMMAND_EXIT

        with patch.object(robot, "run_cli", run_cli):
            result = CliRunner().invoke(
                cli.app,
                [
                    "run-robot",
                    "--no-upload",
                    "--test-run-id",
                    parameters.COMMAND_RUN,
                    "--suite-name",
                    parameters.SUITE_NAME,
                    str(suite),
                    *parameters.COMMAND_EXTRA,
                ],
            )
        self.assertEqual(result.exit_code, parameters.COMMAND_EXIT, "Robot's exit code")
        self.assertEqual(seen["args"][0], "--listener", "the listener comes first")
        listener_argument = seen["args"][1]
        self.assertTrue(listener_argument.startswith(config.LISTENER_CLASS), "it is Bud's listener")
        for setting in parameters.LISTENER_SETTINGS:
            self.assertIn(member=setting, container=listener_argument, msg=f"with {setting}")
        self.assertNotIn(
            member=parameters.NO_BACKEND_SETTING,
            container=listener_argument,
            msg="and no backend",
        )
        self.assertEqual(
            seen["args"][2:],
            [str(suite), *parameters.COMMAND_EXTRA],
            "Robot's own arguments follow",
        )

    def bud_run_robot_replays_the_spool_first(self):
        """run-robot replays the spool before running, and stops without a backend URL."""
        flushed: list = []
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(robot, "run_cli", return_value=parameters.OK))
            stack.enter_context(
                patch.object(
                    cli,
                    "AuthManager",
                    lambda backend_url=None: SimpleNamespace(backend_url=backend_url),
                )
            )
            stack.enter_context(
                patch.object(cli, "BudAPIClient", return_value=parameters.FLUSHED[0])
            )
            stack.enter_context(
                patch.object(cli, "_flush_spooled_results", lambda *args: flushed.append(args[0]))
            )
            result = CliRunner().invoke(
                cli.app,
                ["run-robot", "--backend-url", parameters.SPOOL_BACKEND, parameters.TESTS_FOLDER],
            )
            self.assertEqual(result.exit_code, parameters.OK, "run-robot exits 0")
            self.assertEqual(flushed, parameters.FLUSHED, "the spool is replayed first")
            stack.enter_context(
                patch.object(cli, "AuthManager", return_value=SimpleNamespace(backend_url=None))
            )
            result = CliRunner().invoke(cli.app, ["run-robot", parameters.TESTS_FOLDER])
        self.assertEqual(result.exit_code, parameters.USAGE_ERROR, "without a backend it exits 2")
        self.assertIn(
            member=messages.NO_BACKEND,
            container=result.output,
            msg=f"it says {messages.NO_BACKEND!r}",
        )
