"""The pytest plugin: real pytest runs mapped to Bud results, assert statements recorded as
bud_assert records them, failures, skips, xfails and fixture errors, the payload, the upload and
the spool, and the run-pytest command, with Bud's client, the station identity and the spool
mocked."""

import contextlib
import io
import os
import sys
import textwrap
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from budtestlibrary import BudTestCase
from typer.testing import CliRunner

from bud_runner import api_client, auth, cli
from bud_runner.pytest_plugin import PLUGIN_NAME, comparison
from tests.config import PytestPlugin as config
from tests.messages import PytestPlugin as messages
from tests.parameters import PytestPlugin as parameters


class _Record:
    """Keeps the inner run's config and every collect and test report it made."""

    def __init__(self):
        self.config = None
        self.reports: list = []

    def pytest_configure(self, config):
        """Keep the run's config."""
        self.config = config

    def pytest_collectreport(self, report):
        """Keep a collect report."""
        self.reports.append(report)

    def pytest_runtest_logreport(self, report):
        """Keep a test phase report."""
        self.reports.append(report)


class _Bud:
    """A double of Bud's client that records the results and run updates sent."""

    def __init__(self, fail: bool = False):
        self.calls: list = []
        self.fail = fail

    def upload_results_payload(self, payload):
        """Record the results; raise when Bud is down."""
        self.calls.append(("results", payload))
        if self.fail:
            raise RuntimeError(messages.BACKEND_DOWN)
        return {"test_run_id": config.UPLOADED_RUN}

    def update_test_run(self, run_id, skipped_tests=None):
        """Record the run update."""
        self.calls.append(("update", run_id, {"skipped_tests": skipped_tests}))


class PytestPlugin(BudTestCase):
    """The pytest plugin and the run-pytest command."""

    def setUp(self):
        """A new folder for the step's pytest project."""
        self.folder = Path(os.environ[config.WORK_DIR_SETTING]) / config.FOLDER / uuid.uuid4().hex
        self.folder.mkdir(parents=True)

    @contextlib.contextmanager
    def isolated(self):
        """Run the block in the step's folder with HOME there, no PYTEST_ADDOPTS, and the
        modules, import path and working directory restored after it."""
        modules, path, before = set(sys.modules), list(sys.path), os.getcwd()
        with patch.dict(os.environ, {"HOME": str(self.folder)}):
            os.environ.pop("PYTEST_ADDOPTS", None)
            os.chdir(self.folder)
            try:
                yield
            finally:
                os.chdir(before)
                sys.path[:] = path
                for name in set(sys.modules) - modules:
                    del sys.modules[name]

    def run_pytest(self, *options, text: str = parameters.SUITE, plugin: bool = True):
        """Write the bench file as pytester writes it, dedented and without surrounding blank
        lines, and an empty pytest.ini; run pytest on the folder and return the exit code, the
        record of the run and pytest's output."""
        bench = textwrap.dedent(text).strip("\n") + "\n"
        (self.folder / f"{config.BENCH}.py").write_text(bench, encoding="utf-8")
        (self.folder / "pytest.ini").write_text("", encoding="utf-8")
        record = _Record()
        output = io.StringIO()
        flags = list(config.PLUGIN) if plugin else list(config.PLUGIN[:2])
        with self.isolated(), contextlib.redirect_stdout(output):
            code = pytest.main([*flags, "-p", "no:cacheprovider", *options], plugins=[record])
        return code, record, output.getvalue()

    def reporter(self, record):
        """The plugin's reporter of the run."""
        return record.config.pluginmanager.get_plugin(PLUGIN_NAME)

    def by_method(self, record) -> dict:
        """The run's Bud results by test function."""
        return {result["test_method"]: result for result in self.reporter(record).results}

    def phases(self, record, when: str) -> dict:
        """The test reports of one phase by test function."""
        return {
            report.nodeid.split("::")[-1]: report
            for report in record.reports
            if getattr(report, "when", None) == when
        }

    def outcomes(self, record) -> dict:
        """Passed calls and skipped and failed reports, counted as pytest's own pytester counts
        them."""
        counts = {"passed": 0, "skipped": 0, "failed": 0}
        for report in record.reports:
            if report.passed:
                counts["passed"] += report.when == "call"
            elif report.skipped:
                counts["skipped"] += 1
            else:
                counts["failed"] += 1
        return counts

    def core(self, entry: dict) -> dict:
        """The fields an assert statement and bud_assert must record alike."""
        return {key: entry[key] for key in parameters.CORE_KEYS}

    @contextlib.contextmanager
    def bud(self, fail: bool = False):
        """Mock Bud's client, the station identity and the spool; yield what was made and
        spooled."""
        made: list = []
        spooled: list = []

        def client(auth_manager):
            made.append(_Bud(fail))
            return made[-1]

        station = SimpleNamespace(runner_account=config.STATION, product_id=config.PRODUCT_ID)
        with contextlib.ExitStack() as stack:
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

    def bud_a_pytest_run_maps_to_bud_results(self):
        """Each pytest test becomes one Bud result with its checks, outcome and Bloom marker."""
        _, record, _ = self.run_pytest(parameters.NO_UPLOAD)
        reporter = self.reporter(record)
        results = self.by_method(record)
        self.assertEqual(len(reporter.results), parameters.RESULTS, "fifteen results")
        measured = results["test_measures"]
        self.assertEqual(measured["test_class"], parameters.MEASURED_CLASS, "its node id")
        self.assertTrue(measured["passed"] is True, "it passed")
        self.assertTrue(measured["error_message"] is None, "with no error")
        self.assertEqual(measured["metadata"]["tc_id"], parameters.TC_ID, "its Bloom test case")
        self.assertEqual(
            measured["metadata"]["pytest_outcome"], parameters.PASSED, "pytest's outcome"
        )
        self.assertIn(
            member=parameters.BLOOM_MARKER,
            container=measured["metadata"]["pytest_markers"],
            msg="its markers include bloom",
        )
        self.assertNotIn(
            member="test_case_file", container=measured["metadata"], msg="no test case file"
        )
        self.assertNotIn(
            member="test_case_class", container=measured["metadata"], msg="no test case class"
        )
        self.assertEqual(
            [entry["assertion_type"] for entry in measured["assertions"]],
            parameters.MEASURED_TYPES,
            "its entries in order",
        )
        self.assertTrue(
            all(entry["passed"] for entry in measured["assertions"]), "all its entries pass"
        )
        grouped = results["test_method"]
        self.assertEqual(grouped["test_class"], parameters.GROUPED_CLASS, "a class test's node id")
        self.assertEqual(
            grouped["metadata"]["tc_id"], parameters.GROUPED_TC_ID, "a short bloom marker"
        )
        self.assertEqual(
            len({result["test_class"] for result in reporter.results}),
            parameters.RESULTS,
            "each test has its own class",
        )

    def bud_assert_statements_and_bud_assert_give_the_same_records(self):
        """An assert statement is recorded as the matching bud_assert call records it."""
        _, record, _ = self.run_pytest(parameters.NO_UPLOAD)
        entries = self.by_method(record)["test_measures"]["assertions"]
        plain_equal, plain_in, plain_true = entries[0], entries[1], entries[2]
        fixture_equal, fixture_in = entries[7], entries[8]
        self.assertEqual(self.core(plain_equal), self.core(fixture_equal), "== as assertEqual")
        self.assertEqual(self.core(plain_equal), parameters.PLAIN_EQUAL, "its recorded fields")
        self.assertEqual(self.core(plain_in), self.core(fixture_in), "in as assertIn")
        self.assertEqual(
            (plain_in["expected"], plain_in["actual"], plain_in["message"]),
            parameters.PLAIN_IN,
            "in's values and message",
        )
        self.assertEqual(
            (plain_true["expected"], plain_true["actual"]),
            parameters.PLAIN_TRUE,
            "a bare value as assertTrue",
        )
        self.assertEqual(set(plain_equal), set(fixture_equal), "the same fields")
        self.assertEqual(plain_equal["source_file"], parameters.SOURCE_FILE, "its file")
        self.assertEqual(plain_equal["source_line"], parameters.SOURCE_LINE, "its line")
        self.assertEqual(plain_equal["source_function"], parameters.SOURCE_FUNCTION, "its function")
        self.assertEqual(plain_equal["code_context"], parameters.PLAIN_CONTEXT, "its source")
        self.assertEqual(
            fixture_equal["code_context"], parameters.FIXTURE_CONTEXT, "bud_assert's source"
        )
        less, greater, not_in = entries[4], entries[5], entries[6]
        self.assertEqual((less["expected"], less["actual"]), parameters.LESS, "< as assertLess")
        self.assertEqual(
            (greater["expected"], greater["actual"]), parameters.GREATER, "> as assertGreater"
        )
        self.assertEqual(not_in["expected"], parameters.NOT_IN, "not in as assertNotIn")

    def bud_an_asserted_value_is_recorded_as_bud_assert_records_it(self):
        """A truth check on a value is recorded as assertTrue records it, failing on an empty
        value."""
        _, record, _ = self.run_pytest(parameters.NO_UPLOAD)
        results = self.by_method(record)
        entries = results["test_values"]["assertions"]
        pairs = [(entries[i], entries[i + 1]) for i in range(0, len(entries), 2)]
        self.assertEqual(len(pairs), parameters.VALUE_PAIRS, "four statement and call pairs")
        for plain, fixture in pairs:
            self.assertEqual(self.core(plain), self.core(fixture), "recorded alike")
        self.assertEqual(
            [plain["actual"] for plain, _ in pairs], parameters.VALUES, "the values checked"
        )
        self.assertTrue(
            all(plain["assertion_type"] == "AssertTrue" for plain, _ in pairs),
            "all as AssertTrue",
        )
        (failed,) = results["test_value_fails"]["assertions"]
        self.assertEqual(
            (failed["assertion_type"], failed["passed"], failed["expected"], failed["actual"]),
            parameters.VALUE_FAILS,
            "an empty value fails",
        )

    def bud_a_failed_assert_carries_expected_actual_message_and_traceback(self):
        """A failed assert statement carries its values, message, source and traceback, and
        the test carries them too."""
        _, record, _ = self.run_pytest(parameters.NO_UPLOAD)
        failed = self.by_method(record)["test_fails_a_check"]
        self.assertTrue(failed["passed"] is False, "the test failed")
        self.assertEqual(
            failed["metadata"]["pytest_outcome"], parameters.FAILED_OUTCOME, "pytest's outcome"
        )
        (entry,) = failed["assertions"]
        self.assertTrue(entry["passed"] is False, "its entry failed")
        self.assertEqual(entry["assertion_type"], "AssertEqual", "as AssertEqual")
        self.assertEqual(
            (entry["expected"], entry["actual"]), parameters.FAILED_VALUES, "the compared lists"
        )
        self.assertTrue(
            entry["message"].startswith(parameters.FAILED_MESSAGE_START), "pytest's message"
        )
        self.assertEqual(entry["code_context"], parameters.FAILED_CONTEXT, "its source")
        self.assertIn(
            member=parameters.SOURCE_FILE, container=entry["traceback"], msg="traced in the file"
        )
        self.assertIn(
            member="AssertionError", container=entry["traceback"], msg="as an AssertionError"
        )
        self.assertEqual(failed["error_message"], entry["message"], "the test carries the message")
        self.assertEqual(failed["traceback"], entry["traceback"], "and the traceback")

    def bud_a_failed_bud_assert_goes_on_and_fails_the_test(self):
        """A failed bud_assert lets the test go on and fails it; abort_on_fail stops it; a
        failure in teardown fails the test as an error."""
        _, record, _ = self.run_pytest(parameters.NO_UPLOAD)
        results = self.by_method(record)
        calls = self.phases(record, "call")
        self.assertTrue(calls["test_soft_failure_goes_on"].failed, "pytest fails the test")
        soft = results["test_soft_failure_goes_on"]
        self.assertTrue(soft["passed"] is False, "Bud fails it")
        self.assertEqual(
            [(entry["assertion_type"], entry["passed"]) for entry in soft["assertions"]],
            parameters.SOFT_ENTRIES,
            "the later check still runs",
        )
        self.assertEqual(soft["error_message"], parameters.SOFT_ERROR, "the first failure")
        self.assertTrue(bool(soft["assertions"][0]["traceback"]), "it is traced")
        abort = results["test_abort_on_fail_stops"]
        self.assertTrue(calls["test_abort_on_fail_stops"].failed, "pytest fails the abort")
        self.assertEqual(
            [(entry["assertion_type"], entry["passed"]) for entry in abort["assertions"]],
            parameters.ABORT_ENTRIES,
            "nothing runs after the abort",
        )
        self.assertEqual(abort["error_message"], parameters.ABORT_ERROR, "the aborting failure")
        teardowns = self.phases(record, "teardown")
        self.assertTrue(teardowns["test_teardown_check"].failed, "pytest fails the teardown")
        after = results["test_teardown_check"]
        self.assertTrue(after["passed"] is False, "Bud fails the test")
        self.assertEqual(
            after["metadata"]["pytest_outcome"], parameters.ERROR_OUTCOME, "as an error"
        )
        self.assertEqual(after["error_message"], parameters.AFTER_ERROR, "the teardown failure")

    def bud_a_failed_bud_assert_in_an_xfail_test_is_its_expected_failure(self):
        """A failed bud_assert in an xfail test is its expected failure, strict or not."""
        _, record, _ = self.run_pytest(parameters.NO_UPLOAD)
        results = self.by_method(record)
        calls, teardowns = self.phases(record, "call"), self.phases(record, "teardown")
        for name in parameters.XFAIL_TESTS:
            self.assertTrue(calls[name].skipped, f"{name} is skipped by pytest")
            self.assertTrue(hasattr(calls[name], "wasxfail"), f"{name} was an expected failure")
            self.assertTrue(teardowns[name].passed, f"{name}'s teardown passes")
            result = results[name]
            self.assertEqual(
                result["metadata"]["pytest_outcome"], parameters.XFAILED, f"{name} is xfailed"
            )
            self.assertTrue(result["metadata"]["skipped"] is True, f"{name} is marked skipped")
            self.assertEqual(
                [(entry["assertion_type"], entry["passed"]) for entry in result["assertions"]][0],
                parameters.FIRST_XFAIL_ENTRY,
                f"{name}'s failed check is kept",
            )
        self.assertEqual(
            results["test_expected_strict_soft_failure"]["error_message"],
            parameters.STRICT_REASON,
            "the strict xfail's reason",
        )
        self.assertEqual(self.outcomes(record), parameters.OUTCOMES, "pytest's outcome counts")

    def bud_exceptions_skips_xfail_and_fixture_errors(self):
        """Exceptions, skips, xfails and fixture errors each map to their own entry."""
        _, record, _ = self.run_pytest(parameters.NO_UPLOAD)
        results = self.by_method(record)
        raised = results["test_raises"]
        (entry,) = raised["assertions"]
        self.assertEqual(
            (entry["assertion_type"], entry["passed"], entry["message"]),
            parameters.RAISED,
            "the exception as an entry",
        )
        self.assertEqual(entry["source_function"], parameters.RAISED_FUNCTION, "in its test")
        self.assertIn(member="ValueError", container=entry["traceback"], msg="traced")
        self.assertEqual(raised["error_message"], parameters.BAD_VALUE, "the test's error")
        skipped = results["test_skipped"]
        self.assertTrue(skipped["passed"] is True, "a skip counts as passed")
        self.assertTrue(skipped["metadata"]["skipped"] is True, "it is marked skipped")
        self.assertEqual(
            skipped["metadata"]["pytest_outcome"], parameters.SKIPPED_OUTCOME, "pytest's outcome"
        )
        self.assertEqual(skipped["error_message"], parameters.SKIP_REASON, "its reason")
        self.assertEqual(
            [(e["assertion_type"], e["skipped"], e["message"]) for e in skipped["assertions"]],
            parameters.SKIP_ENTRIES,
            "the skipped check and the skip",
        )
        xfail = results["test_expected_failure"]
        self.assertEqual(
            xfail["metadata"]["pytest_outcome"], parameters.XFAILED, "an xfail is xfailed"
        )
        self.assertTrue(xfail["metadata"]["skipped"] is True, "and marked skipped")
        self.assertEqual(
            [entry["assertion_type"] for entry in xfail["assertions"]],
            parameters.XFAIL_ENTRIES,
            "with a Skip entry",
        )
        setup = results["test_setup_error"]
        self.assertTrue(setup["passed"] is False, "a fixture error fails the test")
        self.assertEqual(
            setup["metadata"]["pytest_outcome"], parameters.ERROR_OUTCOME, "as an error"
        )
        (entry,) = setup["assertions"]
        self.assertEqual(entry["assertion_type"], parameters.SETUP_TYPE, "the fixture's error")
        self.assertEqual(entry["metadata"], parameters.SETUP_METADATA, "in the setup phase")
        self.assertEqual(setup["error_message"], parameters.SETUP_ERROR, "its message")
        self.assertEqual(self.reporter(record).skipped, parameters.SKIPPED, "five skips")

    def bud_the_payload_names_the_suite_product_and_run(self):
        """The payload carries the run, product, station, software and suite name given, and
        falls back to the station's product."""
        _, record, _ = self.run_pytest(parameters.NO_UPLOAD, *parameters.PAYLOAD_OPTIONS)
        body = self.reporter(record).payload(config.STATION, parameters.STATION_RUN)
        self.assertEqual(body["test_run_id"], parameters.PAYLOAD_RUN, "the run given")
        self.assertEqual(body["product_id"], parameters.PAYLOAD_PRODUCT, "the product given")
        self.assertEqual(body["runner_account"], config.STATION, "the station")
        self.assertEqual(
            body["ref_software_under_test"], parameters.SOFTWARE_UNDER_TEST, "the software"
        )
        self.assertEqual(body["test_suite_name"], self.folder.name, "the project's folder name")
        self.assertEqual(len(body["results"]), parameters.RESULTS, "fifteen results")
        _, record, _ = self.run_pytest(parameters.NO_UPLOAD, parameters.SUITE_NAME_OPTION)
        named = self.reporter(record).payload(None, parameters.STATION_RUN)
        self.assertEqual(named["test_suite_name"], parameters.SUITE_NAME, "the suite name given")
        self.assertEqual(
            named["product_id"], parameters.STATION_RUN, "the station's product otherwise"
        )

    def bud_the_session_is_uploaded_with_the_skipped_count(self):
        """The session's results go to Bud, then the run is updated with the skip count."""
        errors = io.StringIO()
        with self.bud() as sent, contextlib.redirect_stderr(errors):
            self.run_pytest(parameters.BACKEND_OPTION)
        calls = sent.made[0].calls
        self.assertEqual(calls[0][0], "results", "the results go first")
        self.assertEqual(len(calls[0][1]["results"]), parameters.RESULTS, "fifteen results")
        self.assertEqual(calls[0][1]["product_id"], config.PRODUCT_ID, "the station's product")
        self.assertEqual(calls[0][1]["runner_account"], config.STATION, "the station")
        self.assertEqual(
            calls[1],
            ("update", config.UPLOADED_RUN, {"skipped_tests": parameters.SKIPPED}),
            "the run is updated with five skips",
        )
        self.assertIn(
            member=messages.UPLOADED,
            container=errors.getvalue(),
            msg=f"stderr says {messages.UPLOADED!r}",
        )

    def bud_a_failed_upload_is_spooled(self):
        """When Bud is down the results are spooled for the named run and nothing else is sent."""
        with self.bud(fail=True) as sent, contextlib.redirect_stderr(io.StringIO()):
            self.run_pytest(parameters.SPOOL_OPTION)
        self.assertEqual(len(sent.spooled), 1, "one payload is spooled")
        self.assertEqual(sent.spooled[0]["test_run_id"], parameters.PAYLOAD_RUN, "for run 7")
        self.assertEqual(
            [call[0] for call in sent.made[0].calls], ["results"], "only the results were tried"
        )

    def bud_an_upload_error_never_changes_the_exit_code(self):
        """A failing identity is reported and pytest still exits 0."""

        def no_credentials(backend_url=None):
            raise RuntimeError(messages.NO_CREDENTIALS)

        errors = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(auth, "AuthManager", no_credentials))
            stack.enter_context(contextlib.redirect_stderr(errors))
            code, _, _ = self.run_pytest(text=parameters.ONE_TEST)
        self.assertEqual(code, parameters.OK, "pytest exits 0")
        self.assertIn(
            member=messages.COULD_NOT_REPORT,
            container=errors.getvalue(),
            msg=f"stderr says {messages.COULD_NOT_REPORT!r}",
        )

    def bud_the_plugin_warns_when_the_pass_hook_is_off(self):
        """Without enable_assertion_pass_hook the plugin warns, and the run still passes."""
        code, _, output = self.run_pytest(
            parameters.NO_UPLOAD, text=parameters.ONE_TEST, plugin=False
        )
        self.assertIn(
            member=messages.HOOK_OFF,
            container=output,
            msg=f"pytest prints {messages.HOOK_OFF!r}",
        )
        self.assertEqual(code, parameters.OK, "pytest exits 0")

    def bud_comparison_follows_budtestlibrary(self):
        """Each comparison operator maps to budtestlibrary's assertion and values."""
        for (operator, left, right), expected in parameters.COMPARISONS:
            self.assertEqual(
                comparison(operator, left, right), expected, f"{operator!r} maps to {expected[0]}"
            )

    def bud_run_pytest_passes_pytest_arguments_and_exit_code(self):
        """run-pytest hands pytest the plugin, its settings and pytest's own arguments, keeps
        bytecode under the station's home and restores the prefix, and exits with pytest's
        code."""
        seen: dict = {}

        def main(args):
            seen["args"] = args
            seen["prefix"] = sys.pycache_prefix
            return parameters.COMMAND_EXIT

        before = sys.pycache_prefix
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {"HOME": str(self.folder)}))
            stack.enter_context(patch.object(pytest, "main", main))
            result = CliRunner().invoke(cli.app, parameters.COMMAND_ARGS)
        self.assertEqual(result.exit_code, parameters.COMMAND_EXIT, "pytest's exit code")
        self.assertEqual(seen["args"][:4], list(config.PLUGIN), "the plugin comes first")
        for setting in parameters.COMMAND_SETTINGS:
            self.assertIn(member=setting, container=seen["args"], msg=f"with {setting}")
        self.assertEqual(seen["args"][-3:], parameters.COMMAND_TAIL, "pytest's own arguments")
        self.assertEqual(
            seen["prefix"],
            str(self.folder.joinpath(*parameters.PYCACHE)),
            "bytecode goes under the station's home",
        )
        self.assertEqual(sys.pycache_prefix, before, "the prefix is restored")

    def bud_run_pytest_replays_the_spool_first_and_needs_a_backend(self):
        """run-pytest replays the spool before running, and stops without a backend URL."""
        flushed: list = []
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(pytest, "main", return_value=parameters.OK))
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
            result = CliRunner().invoke(cli.app, parameters.SPOOL_ARGS)
            self.assertEqual(result.exit_code, parameters.OK, "run-pytest exits 0")
            self.assertEqual(flushed, parameters.FLUSHED, "the spool is replayed first")
            stack.enter_context(
                patch.object(cli, "AuthManager", return_value=SimpleNamespace(backend_url=None))
            )
            result = CliRunner().invoke(cli.app, parameters.NO_BACKEND_ARGS)
        self.assertEqual(result.exit_code, parameters.USAGE_ERROR, "without a backend it exits 2")
