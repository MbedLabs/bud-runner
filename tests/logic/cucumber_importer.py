"""The Cucumber JSON import from real cucumber-js, Cucumber-JVM and Cucumber-Ruby reports, with Bud's
client, the station identity, the spool and the flush mocked."""

import contextlib
import json
import os
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from budtestlibrary import BudTestCase, parameterized
from typer.testing import CliRunner

from bud_runner import api_client, auth, cli, reporting
from bud_runner.cucumber_importer import (
    CucumberReport,
    CucumberReportError,
    error_text,
    feature_path,
    read_report,
)
from tests.config import CucumberImporter as config
from tests.messages import CucumberImporter as messages
from tests.parameters import CucumberImporter as parameters


class _Client:
    """A double of Bud's client that records what the import sends."""

    def __init__(self, fail: bool):
        self.calls: list = []
        self.fail = fail

    def upload_results_payload(self, payload):
        """Record the results; fail when asked to."""
        self.calls.append(("results", payload))
        if self.fail:
            raise RuntimeError(messages.BACKEND_DOWN)
        return {"test_run_id": config.UPLOADED_RUN}

    def update_test_run(self, run_id, skipped_tests=None):
        """Record the run update."""
        self.calls.append(("update", run_id, {"skipped_tests": skipped_tests}))

    def upload_artifact(self, path, run_id=None):
        """Record the artifact's file name and run."""
        self.calls.append(("artifact", Path(path).name, run_id))


class CucumberImporter(BudTestCase):
    """What a Cucumber report becomes in Bud and what import-cucumber sends."""

    def report(self, name: str, **options) -> CucumberReport:
        """A fixture report."""
        return CucumberReport(
            read_report(config.FIXTURES / name), config.FIXTURES / name, **options
        )

    def by_method(self, report: CucumberReport) -> dict:
        """The report's results by scenario."""
        return {r["test_method"]: r for r in report.results}

    def shape(self, report: CucumberReport) -> list:
        """What every result says, without timings or texts."""
        return [
            (
                r["test_class"],
                r["test_method"],
                r["passed"],
                r["metadata"]["cucumber_status"],
                r["metadata"].get("tc_id"),
                [
                    (a["assertion_type"], a["passed"], bool(a.get("info")), bool(a["skipped"]))
                    for a in r["assertions"] or []
                ],
            )
            for r in report.results
        ]

    def written(self, name: str, content) -> Path:
        """A file in a new folder of this suite."""
        folder = Path(os.environ[config.WORK_DIR_SETTING]) / config.FOLDER / uuid.uuid4().hex
        folder.mkdir(parents=True)
        path = folder / name
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        return path

    def scenario(self, steps, after=()) -> dict:
        """The result of a one-scenario report."""
        return CucumberReport(
            [
                {
                    "name": "F",
                    "uri": "features/f.feature",
                    "elements": [
                        {
                            "type": "scenario",
                            "name": "S",
                            "line": 2,
                            "steps": steps,
                            "after": list(after),
                        }
                    ],
                }
            ]
        ).results[0]

    @contextlib.contextmanager
    def backend(self, fail: bool = False):
        """Mock Bud's client, the identities, the flush and the spool; yield what they record."""
        made, flushed, spooled = [], [], []

        def factory(auth_manager):
            """A recording client."""
            client = _Client(fail)
            made.append(client)
            return client

        home = self.written("home", "").parent / "home-dir"
        with (
            patch.dict(os.environ, {"HOME": str(home)}),
            patch.object(api_client, "BudAPIClient", factory),
            patch.object(
                auth,
                "AuthManager",
                return_value=SimpleNamespace(
                    runner_account=config.STATION, product_id=config.PRODUCT_ID
                ),
            ),
            patch.object(
                cli,
                "AuthManager",
                lambda backend_url=None: SimpleNamespace(
                    backend_url=backend_url or config.BACKEND_URL
                ),
            ),
            patch.object(cli, "BudAPIClient", return_value="client"),
            patch.object(cli, "_flush_spooled_results", lambda *a: flushed.append(a[0])),
            patch.object(
                cli,
                "_spool_results_payload",
                lambda payload: spooled.append(payload) or "spool.json",
            ),
        ):
            yield SimpleNamespace(made=made, flushed=flushed, spooled=spooled)

    def run_import(self, *args):
        """Invoke import-cucumber."""
        return CliRunner().invoke(cli.app, ["import-cucumber", *args])

    def bud_the_three_runners_give_the_same_bud_results(self):
        """cucumber-js, Cucumber-JVM and Cucumber-Ruby give the same results, scenario by scenario."""
        js, jvm, ruby = (self.shape(self.report(name)) for name in config.RUNNERS)
        self.assertEqual(jvm, js, "Cucumber-JVM matches cucumber-js")
        self.assertEqual(ruby, js, "Cucumber-Ruby matches cucumber-js")
        self.assertEqual(
            [row[1] for row in js], parameters.SCENARIOS, "the scenarios are in report order"
        )

    @parameterized(list(config.RUNNERS))
    def bud_a_cucumber_run_maps_to_bud_results(self, name):
        """A passing scenario becomes a passed result with its tags, location, steps and checks."""
        report = self.report(name)
        measured = self.by_method(report)[parameters.MEASURED]
        self.assertEqual(
            {r["test_class"] for r in report.results},
            {parameters.FEATURE},
            "every result names the feature",
        )
        self.assertEqual(measured["passed"], True, "the scenario passes")
        self.assertEqual(measured["error_message"], None, "it carries no error")
        self.assertEqual(
            measured["metadata"]["tc_id"], parameters.TC_ID, "the Bloom tag gives the test case id"
        )
        self.assertEqual(
            measured["metadata"]["cucumber_tags"], parameters.TAGS, "the tags are kept"
        )
        self.assertTrue(
            measured["metadata"]["location"].endswith(parameters.LOCATION_END),
            "the location is the feature line",
        )
        self.assertNotIn(
            member="test_case_file", container=measured["metadata"], msg="no test case file is set"
        )
        self.assertNotIn(
            member="skipped", container=measured["metadata"], msg="it is not marked skipped"
        )
        steps = [
            (a["assertion_type"], a["passed"], bool(a.get("info"))) for a in measured["assertions"]
        ]
        self.assertEqual(
            steps, parameters.MEASURED_STEPS, "Given/When are information, Then/And are checks"
        )
        check = measured["assertions"][3]
        self.assertEqual(
            check["code_context"], parameters.CHECK_CONTEXT, "the check keeps its step text"
        )
        self.assertEqual(check["source_line"], parameters.CHECK_LINE, "the check keeps its line")
        self.assertEqual(
            check["source_function"], parameters.MEASURED, "the check names the scenario"
        )
        self.assertTrue(measured["duration_seconds"] >= 0, "the duration is not negative")
        self.assertEqual(
            report.counts(),
            parameters.JS_COUNTS,
            "the counts are 1 feature, 8 scenarios, 3 passed, 5 failed",
        )

    @parameterized(messages.RUNNER_MESSAGES)
    def bud_failures_carry_the_runner_message_and_stack_trace(self, name, message):
        """Failed, raising, undefined, pending and hook failures keep the runner's message and trace."""
        results = self.by_method(self.report(name))
        wrong = results[parameters.WRONG]
        failed = wrong["assertions"][2]
        self.assertEqual(
            (failed["assertion_type"], failed["passed"]),
            parameters.FAILED_STEP,
            "the third step fails",
        )
        self.assertEqual(failed["message"], message, "the step keeps the runner's message")
        self.assertEqual(wrong["error_message"], message, "the scenario keeps the runner's message")
        self.assertTrue(
            failed["traceback"].startswith(message.split("\n")[0]),
            "the trace starts with the message",
        )
        self.assertTrue(
            len(failed["traceback"]) > len(message), "the trace is longer than the message"
        )
        self.assertEqual(
            wrong["traceback"], failed["traceback"], "the scenario keeps the step's trace"
        )
        raised = results[parameters.RAISES]
        self.assertEqual(raised["assertions"][1]["passed"], False, "the raising step fails")
        self.assertEqual(
            raised["assertions"][1]["info"], True, "the raising step is an information step"
        )
        self.assertIn(
            member=messages.BAD_VALUE,
            container=raised["error_message"],
            msg="the raised error is kept",
        )
        missing = results[parameters.MISSING]
        self.assertEqual(
            missing["error_message"], messages.UNDEFINED, "an undefined step names itself"
        )
        self.assertEqual(
            missing["metadata"]["cucumber_status"], "undefined", "its status is undefined"
        )
        pending = results[parameters.PENDING]
        self.assertEqual(pending["passed"], False, "a pending step fails the scenario")
        self.assertEqual(pending["metadata"]["cucumber_status"], "pending", "its status is pending")
        hook = results[parameters.HOOK]
        self.assertEqual(
            [(a["assertion_type"], a["passed"]) for a in hook["assertions"]],
            parameters.HOOK_STEPS,
            "a failing hook is one HookError",
        )
        self.assertIn(
            member=messages.HOOK_BROKE,
            container=hook["error_message"],
            msg="the hook's error is kept",
        )
        self.assertTrue(bool(hook["traceback"]), "the hook's trace is kept")

    def bud_edge_cases_from_a_real_cucumber_js_report(self):
        """Tags, ambiguous steps, after hooks, skipped scenarios, repeated names and non-English features."""
        report = self.report(config.EDGES)
        results = self.by_method(report)
        self.assertEqual(
            results[parameters.OWN_TAG]["metadata"]["tc_id"],
            parameters.OWN_TC,
            "the scenario's own tag wins",
        )
        self.assertEqual(
            results[parameters.OWN_TAG]["metadata"]["cucumber_tags"],
            parameters.OWN_TAGS,
            "both tags are kept",
        )
        self.assertEqual(
            results[parameters.FEATURE_TAG_ONLY]["metadata"]["tc_id"],
            parameters.FEATURE_TC,
            "the feature tag applies",
        )
        ambiguous = results[parameters.AMBIGUOUS]
        self.assertEqual(ambiguous["passed"], False, "an ambiguous step fails")
        self.assertEqual(
            ambiguous["error_message"], messages.AMBIGUOUS, "it names the ambiguous step"
        )
        after = results[parameters.AFTER]
        self.assertEqual(after["passed"], False, "a failing after hook fails the scenario")
        self.assertEqual(
            [(a["assertion_type"], a["passed"]) for a in after["assertions"]],
            parameters.AFTER_STEPS,
            "the hook follows the steps",
        )
        self.assertEqual(after["error_message"], messages.AFTER_BROKE, "the hook's error is kept")
        for name, reason in parameters.SKIPPED_SCENARIOS:
            skipped = results[name]
            self.assertEqual(skipped["passed"], True, f"{name!r} passes")
            self.assertEqual(
                skipped["metadata"].get("skipped"), True, f"{name!r} is marked skipped"
            )
            self.assertEqual(
                skipped["metadata"]["cucumber_status"], "skipped", f"{name!r} has status skipped"
            )
            self.assertEqual(skipped["error_message"], reason, f"{name!r} says {reason!r}")
            self.assertEqual(
                skipped["assertions"][-1]["assertion_type"], "Skip", f"{name!r} ends with a Skip"
            )
            self.assertEqual(
                skipped["assertions"][-1]["skipped"], True, f"{name!r}'s Skip is skipped"
            )
        for name in parameters.SAME_NAMES:
            self.assertIn(member=name, container=results, msg=f"{name!r} is told apart by its line")
        german = results[parameters.GERMAN]
        self.assertEqual(
            german["test_class"], parameters.GERMAN_FEATURE, "the German feature keeps its name"
        )
        self.assertEqual(german["passed"], True, "the German scenario passes")
        self.assertTrue(
            all(a.get("info") for a in german["assertions"]), "its steps are information steps"
        )
        self.assertEqual(
            report.counts(),
            parameters.EDGES_COUNTS,
            "the counts are 2 features, 9 scenarios, 5/2/2",
        )
        self.assertEqual(
            reporting.skipped_test_cases(report.results), 0, "no test case is fully skipped"
        )

    def bud_hooks_alone_make_no_steps_and_the_worst_status_wins(self):
        """A scenario of hooks only is skipped; a failing after hook outranks an undefined step."""
        hook_only = self.scenario(parameters.HOOK_ONLY)
        self.assertEqual(hook_only["passed"], True, "a hooks-only scenario passes")
        self.assertEqual(hook_only["metadata"].get("skipped"), True, "it is marked skipped")
        self.assertEqual(hook_only["error_message"], messages.NO_STEPS, "it says it has no steps")
        mixed = self.scenario(parameters.UNDEFINED_STEPS, after=parameters.FAILED_AFTER)
        self.assertEqual(
            mixed["metadata"]["cucumber_status"], "failed", "the failed hook's status wins"
        )
        self.assertEqual(
            mixed["error_message"], messages.UNDEFINED_A, "the first problem's message is kept"
        )

    def bud_the_payload_names_the_suite_product_and_run(self):
        """The upload body names the run, product, station, software reference and suite."""
        body = self.report(config.JVM, **parameters.PAYLOAD_OPTIONS).payload(
            parameters.ACCOUNT, parameters.DEFAULT_PRODUCT
        )
        for key, value in parameters.PAYLOAD_EXPECTED.items():
            self.assertEqual(body.get(key), value, f"{key} is {value!r}")
        self.assertEqual(len(body["results"]), parameters.RESULTS, "the body carries 8 results")
        edges = self.report(config.EDGES).payload(None, parameters.DEFAULT_PRODUCT)
        self.assertEqual(
            edges["test_suite_name"],
            parameters.EDGES_SUITE,
            "several features are suite 'features'",
        )
        self.assertEqual(
            edges["product_id"], parameters.DEFAULT_PRODUCT, "the default product is used"
        )
        named = self.report(config.JS, suite_name=parameters.SUITE_NAME).payload(None, None)
        self.assertEqual(named["test_suite_name"], parameters.SUITE_NAME, "a given suite name wins")
        no_uri = self.written(parameters.NO_URI_FILE, json.dumps(parameters.NO_URI))
        self.assertEqual(
            CucumberReport(read_report(no_uri), no_uri).payload(),
            None,
            "empty features give no body",
        )
        self.assertEqual(
            CucumberReport(read_report(no_uri), no_uri)._default_suite(),
            parameters.NO_URI_SUITE,
            "the file name is the suite",
        )

    def bud_paths_and_messages(self):
        """feature_path() strips runner prefixes; error_text() keeps the first line of a trace."""
        for raw, path in parameters.FEATURE_PATHS:
            self.assertEqual(feature_path(raw), path, f"{raw!r} gives {path!r}")
        for trace, text in parameters.ERROR_TEXTS:
            self.assertEqual(error_text(trace), text, f"the message is {text!r}")
        jvm = self.by_method(self.report(config.JVM))[parameters.MEASURED]
        self.assertEqual(
            jvm["metadata"]["location"],
            parameters.JVM_LOCATION,
            "the JVM location drops the classpath",
        )

    @parameterized(messages.MALFORMED)
    def bud_a_malformed_report_is_refused(self, content, problem):
        """read_report() names what is wrong with a malformed report."""
        path = self.written(parameters.REPORT_FILE, content)
        raised = ""
        try:
            read_report(path)
        except CucumberReportError as error:
            raised = str(error)
        self.assertIn(member=problem, container=raised, msg=f"the refusal says {problem!r}")

    def bud_a_report_that_is_not_utf8_is_refused(self):
        """A UTF-16 report is refused by read_report() and by import-cucumber with exit 2, sending nothing."""
        path = self.written(parameters.REPORT_FILE, parameters.UTF16_REPORT.encode("utf-16"))
        raised = ""
        try:
            read_report(path)
        except CucumberReportError as error:
            raised = str(error)
        self.assertIn(member=messages.NOT_UTF8, container=raised, msg="read_report says not UTF-8")
        with self.backend() as backend:
            result = self.run_import("--report", str(path))
        self.assertEqual(result.exit_code, parameters.REFUSED, "import-cucumber exits 2")
        self.assertIn(
            member=messages.NOT_UTF8, container=result.output, msg="import-cucumber says not UTF-8"
        )
        self.assertEqual(backend.made, [], "nothing is sent")

    def bud_a_missing_report_is_refused(self):
        """A missing file is refused as unreadable."""
        missing = self.written(parameters.REPORT_FILE, "").parent / "absent.json"
        raised = ""
        try:
            read_report(missing)
        except CucumberReportError as error:
            raised = str(error)
        self.assertIn(
            member=messages.CANNOT_READ,
            container=raised,
            msg="the refusal says the file is unreadable",
        )

    def bud_import_uploads_the_report_and_attaches_it(self):
        """import-cucumber flushes the spool, uploads 9 results for the station and product, and attaches the report."""
        with self.backend() as backend:
            result = self.run_import(
                "--report", str(config.FIXTURES / config.EDGES), "--backend-url", config.BACKEND_URL
            )
        self.assertEqual(
            result.exit_code, parameters.OK, f"import-cucumber exits 0: {result.output}"
        )
        self.assertIn(
            member=messages.EDGES_SUMMARY, container=result.output, msg="the summary is printed"
        )
        self.assertEqual(backend.flushed, ["client"], "the spool is flushed first")
        calls = backend.made[0].calls
        self.assertEqual(calls[0][0], "results", "the results go first")
        self.assertEqual(
            len(calls[0][1]["results"]), parameters.EDGES_RESULTS, "9 results are sent"
        )
        self.assertEqual(
            calls[0][1]["product_id"], config.PRODUCT_ID, "the station's product is sent"
        )
        self.assertEqual(calls[0][1]["runner_account"], config.STATION, "the station is named")
        self.assertEqual(
            calls[1:],
            [("artifact", config.EDGES, config.UPLOADED_RUN)],
            "the report is attached to the new run",
        )

    def bud_import_without_artifacts_and_with_a_run_id(self):
        """--no-artifacts sends only the results, for the given run and suite."""
        with self.backend() as backend:
            result = self.run_import(
                "--report",
                str(config.FIXTURES / config.RUBY),
                "--no-artifacts",
                "--test-run-id",
                parameters.RUN_ID,
                "--suite-name",
                parameters.SUITE_NAME,
            )
        self.assertEqual(
            result.exit_code, parameters.OK, f"import-cucumber exits 0: {result.output}"
        )
        body = backend.made[0].calls[0][1]
        self.assertEqual(body["test_run_id"], parameters.RUN_ID_VALUE, "the given run is used")
        self.assertEqual(
            body["test_suite_name"], parameters.SUITE_NAME, "the given suite name is used"
        )
        self.assertEqual(
            [call[0] for call in backend.made[0].calls], ["results"], "only the results are sent"
        )

    def bud_an_upload_that_does_not_reach_bud_exits_1_and_is_spooled(self):
        """A failed upload exits 1 and spools the 8 results."""
        with self.backend(fail=True) as backend:
            result = self.run_import("--report", str(config.FIXTURES / config.JS))
        self.assertEqual(result.exit_code, parameters.FAILED, "import-cucumber exits 1")
        self.assertEqual(
            len(backend.spooled), parameters.ONE, "the payload is spooled once", abort_on_fail=True
        )
        self.assertEqual(
            len(backend.spooled[0]["results"]), parameters.RESULTS, "the 8 results are spooled"
        )

    def bud_a_malformed_report_exits_2_before_anything_is_sent(self):
        """Invalid JSON exits 2 naming the file, before the spool is flushed or anything is sent."""
        bad = self.written(parameters.REPORT_FILE, "{not json")
        with self.backend() as backend:
            result = self.run_import("--report", str(bad))
        self.assertEqual(result.exit_code, parameters.REFUSED, "import-cucumber exits 2")
        self.assertIn(
            member=messages.NOT_JSON.format(path=bad),
            container=result.output,
            msg="the file is named as invalid JSON",
        )
        self.assertEqual(backend.flushed, [], "the spool is not flushed")
        self.assertEqual(backend.made, [], "nothing is sent")

    def bud_a_report_with_the_wrong_shape_inside_exits_2(self):
        """A step whose result is not an object exits 2 before anything is sent."""
        bad = self.written(parameters.REPORT_FILE, parameters.WRONG_SHAPE)
        with self.backend() as backend:
            result = self.run_import("--report", str(bad))
        self.assertEqual(result.exit_code, parameters.REFUSED, "import-cucumber exits 2")
        self.assertIn(
            member=messages.RESULT_NOT_OBJECT,
            container=result.output,
            msg="the bad result is named",
        )
        self.assertEqual(backend.flushed, [], "the spool is not flushed")
        self.assertEqual(backend.made, [], "nothing is sent")

    def bud_no_upload_and_empty_reports_send_nothing(self):
        """--no-upload and an empty report print their summary and send nothing."""
        empty = self.written(parameters.REPORT_FILE, "[]")
        with self.backend() as backend:
            local = self.run_import("--report", str(config.FIXTURES / config.JVM), "--no-upload")
            nothing = self.run_import("--report", str(empty))
        self.assertEqual(local.exit_code, parameters.OK, "--no-upload exits 0")
        self.assertIn(
            member=messages.JVM_SUMMARY, container=local.output, msg="the JVM summary is printed"
        )
        self.assertEqual(nothing.exit_code, parameters.OK, "an empty report exits 0")
        self.assertIn(
            member=messages.EMPTY_SUMMARY,
            container=nothing.output,
            msg="the empty summary is printed",
        )
        self.assertEqual(backend.made, [], "nothing is sent")
        self.assertEqual(backend.flushed, [], "the spool is not flushed")

    def bud_import_needs_a_backend_to_upload(self):
        """Without a backend URL import-cucumber exits 2 and says so."""
        with patch.object(cli, "AuthManager", return_value=SimpleNamespace(backend_url=None)):
            result = self.run_import("--report", str(config.FIXTURES / config.JS))
        self.assertEqual(result.exit_code, parameters.REFUSED, "import-cucumber exits 2")
        self.assertIn(
            member=messages.NO_BACKEND,
            container=result.output,
            msg="it says no backend is configured",
        )
