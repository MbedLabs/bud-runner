"""The Behave formatter: real Behave runs of a generated bench project mapped to Bud results, with
Bud's client, the station identity, the spool and the flush mocked."""

import contextlib
import io
import os
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from behave.__main__ import main as behave_main
from budtestlibrary import BudTestCase
from typer.testing import CliRunner

from bud_runner import api_client, auth, cli
from bud_runner.behave_formatter import BudFormatter
from tests.config import BehaveFormatter as config
from tests.doubles import RecordingClient
from tests.messages import BehaveFormatter as messages
from tests.parameters import BehaveFormatter as parameters

CAPTURED: list = []


class Capture(BudFormatter):
    """BudFormatter that keeps itself for the suite to read after the run."""

    def close(self):
        """Close and keep the formatter."""
        super().close()
        CAPTURED.append(self)


class BehaveFormatter(BudTestCase):
    """What a Behave run becomes in Bud and what run-behave passes on."""

    def setUp(self):
        """Write the bench project in a new folder and work in it."""
        self.project = Path(os.environ[config.WORK_DIR_SETTING]) / config.FOLDER / uuid.uuid4().hex
        features = self.project / "features"
        (features / "steps").mkdir(parents=True)
        (features / "bench.feature").write_text(parameters.FEATURE, encoding="utf-8")
        (features / "steps" / "bench_steps.py").write_text(parameters.STEPS, encoding="utf-8")
        (features / "environment.py").write_text(parameters.ENVIRONMENT, encoding="utf-8")
        self.before = os.getcwd()
        os.chdir(self.project)
        CAPTURED.clear()

    def tearDown(self):
        """Leave the project folder."""
        os.chdir(self.before)

    def run_behave(self, *args):
        """Run Behave on the project with the capturing formatter; return the exit code, the formatter
        and stderr."""
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = behave_main(
                [
                    "-f",
                    config.CAPTURE,
                    "-o",
                    os.devnull,
                    "--no-summary",
                    "--tags=-@excluded",
                    *args,
                    "features",
                ]
            )
        return rc, CAPTURED[-1], err.getvalue()

    def by_method(self, formatter) -> dict:
        """The formatter's results by scenario."""
        return {r["test_method"]: r for r in formatter.results}

    def steps(self, result) -> list:
        """What every step of a result says."""
        return [
            (a["assertion_type"], a["passed"], bool(a.get("info")), bool(a["skipped"]))
            for a in result["assertions"]
        ]

    @contextlib.contextmanager
    def backend(self, fail: bool = False):
        """Mock Bud's client, the station identity and the spool; yield what they record."""
        made, spooled = [], []

        def factory(auth_manager):
            """A recording client."""
            client = RecordingClient(
                config.UPLOADED_RUN, RuntimeError(messages.BACKEND_DOWN) if fail else None
            )
            made.append(client)
            return client

        with (
            patch.dict(os.environ, {"HOME": str(self.project / "home")}),
            patch.object(api_client, "BudAPIClient", factory),
            patch.object(
                auth,
                "AuthManager",
                lambda backend_url=None: SimpleNamespace(
                    runner_account=config.STATION, product_id=config.PRODUCT_ID
                ),
            ),
            patch.object(
                cli,
                "_spool_results_payload",
                lambda payload: spooled.append(payload) or "spool.json",
            ),
        ):
            yield SimpleNamespace(made=made, spooled=spooled)

    def bud_a_behave_run_maps_to_bud_results(self):
        """Each scenario becomes a result with its tags, location, steps and checks; the outline expands."""
        rc, formatter, _ = self.run_behave(*parameters.NO_UPLOAD)
        results = self.by_method(formatter)
        self.assertEqual(rc, parameters.FAILED, "Behave exits 1")
        self.assertEqual(list(results), parameters.SCENARIOS, "the scenarios are in run order")
        self.assertEqual(
            {r["test_class"] for r in formatter.results},
            {parameters.FEATURE_NAME},
            "every result names the feature",
        )
        measured = results[parameters.MEASURED]
        self.assertEqual(measured["passed"], True, "the scenario passes")
        self.assertEqual(measured["error_message"], None, "it carries no error")
        self.assertEqual(
            measured["metadata"]["tc_id"], parameters.TC_ID, "the Bloom tag gives the test case id"
        )
        self.assertEqual(measured["metadata"]["behave_tags"], parameters.TAGS, "the tags are kept")
        self.assertEqual(
            measured["metadata"]["location"],
            parameters.LOCATION,
            "the location is the scenario line",
        )
        for key in ("test_case_file", "test_case_class"):
            self.assertNotIn(member=key, container=measured["metadata"], msg=f"no {key} is set")
        self.assertEqual(
            self.steps(measured),
            parameters.MEASURED_STEPS,
            "Given/When are information, Then/And are checks",
        )
        check = measured["assertions"][3]
        self.assertEqual(
            check["code_context"], parameters.CHECK_CONTEXT, "the check keeps its step text"
        )
        self.assertEqual(
            (check["source_file"], check["source_line"]),
            parameters.CHECK_SOURCE,
            "the check keeps file and line",
        )
        self.assertEqual(
            check["source_function"], parameters.MEASURED, "the check names the scenario"
        )
        outline = results[parameters.OUTLINE]
        self.assertEqual(outline["passed"], True, "the second outline row passes")
        self.assertEqual(
            [s[0] for s in self.steps(outline)],
            parameters.OUTLINE_STEPS,
            "the row has its own steps",
        )

    def bud_failures_carry_the_message_and_traceback(self):
        """Failed, raising and undefined steps keep their message and trace."""
        _, formatter, _ = self.run_behave(*parameters.NO_UPLOAD)
        results = self.by_method(formatter)
        wrong = results[parameters.WRONG]
        self.assertEqual(wrong["passed"], False, "the wrong value fails")
        self.assertEqual(
            self.steps(wrong), parameters.WRONG_STEPS, "the run stops at the failing check"
        )
        failed = wrong["assertions"][2]
        self.assertEqual(
            failed["message"], messages.EXPECTED_3, "the step keeps the assert message"
        )
        self.assertEqual(
            wrong["error_message"], messages.EXPECTED_3, "the scenario keeps the assert message"
        )
        for text in (messages.ASSERTION_ERROR, messages.STEPS_FILE):
            self.assertIn(
                member=text, container=failed["traceback"], msg=f"the trace names {text!r}"
            )
        self.assertEqual(
            wrong["traceback"], failed["traceback"], "the scenario keeps the step's trace"
        )
        raised = results[parameters.RAISES]
        self.assertEqual(raised["passed"], False, "the raising step fails the scenario")
        self.assertEqual(
            raised["error_message"], messages.BAD_VALUE, "the error names the exception"
        )
        self.assertEqual(
            self.steps(raised)[1], parameters.BREAK_STEP, "the raising step fails as information"
        )
        self.assertIn(
            member=messages.BAD_VALUE,
            container=raised["assertions"][1]["traceback"],
            msg="the step's trace names it",
        )
        self.assertIn(
            member=messages.BAD_VALUE,
            container=raised["traceback"],
            msg="the scenario's trace names it",
        )
        missing = results[parameters.MISSING]
        self.assertEqual(missing["passed"], False, "an undefined step fails")
        self.assertEqual(
            missing["error_message"], messages.UNDEFINED, "it names the undefined step"
        )
        self.assertEqual(
            self.steps(missing)[1],
            parameters.MISSING_STEP,
            "the undefined step fails as information",
        )

    def bud_skips_hook_errors_and_tag_selection(self):
        """Excluded scenarios are absent, a skipped one is a Skip, and a failing hook is a HookError."""
        _, formatter, _ = self.run_behave(*parameters.NO_UPLOAD)
        results = self.by_method(formatter)
        self.assertNotIn(
            member=parameters.EXCLUDED, container=results, msg="the excluded scenario is absent"
        )
        skipped = results[parameters.SKIPPED]
        self.assertEqual(skipped["passed"], True, "the skipped scenario passes")
        self.assertEqual(skipped["metadata"].get("skipped"), True, "it is marked skipped")
        self.assertEqual(
            skipped["error_message"], messages.NOT_ON_BENCH, "it keeps the skip reason"
        )
        self.assertEqual(self.steps(skipped), parameters.SKIP_STEPS, "it is one Skip")
        self.assertEqual(formatter.skipped, parameters.ONE, "one scenario is counted skipped")
        hook = results[parameters.HOOK]
        self.assertEqual(hook["passed"], False, "the hook failure fails the scenario")
        self.assertEqual(
            [(a["assertion_type"], a["passed"]) for a in hook["assertions"]],
            parameters.HOOK_STEPS,
            "it is one HookError",
        )
        self.assertIn(
            member=messages.HOOK_BROKE,
            container=hook["error_message"],
            msg="the hook's error is kept",
        )
        for text in (messages.TRACEBACK, messages.ENVIRONMENT_FILE, messages.HOOK_TEXT):
            self.assertIn(
                member=text, container=hook["traceback"], msg=f"the hook's trace holds {text!r}"
            )
        self.assertEqual(
            hook["assertions"][0]["traceback"], hook["traceback"], "the HookError keeps the trace"
        )

    def bud_the_payload_names_the_suite_product_and_run(self):
        """The upload body names the run, product, station, software reference and suite."""
        _, formatter, _ = self.run_behave(*parameters.NO_UPLOAD, *parameters.PAYLOAD_OPTIONS)
        body = formatter.payload(parameters.ACCOUNT, parameters.DEFAULT_PRODUCT)
        for key, value in parameters.PAYLOAD_EXPECTED.items():
            self.assertEqual(body.get(key), value, f"{key} is {value!r}")
        self.assertEqual(len(body["results"]), parameters.RESULTS, "the body carries 8 results")
        (self.project / "features" / "clock.feature").write_text(
            parameters.SECOND_FEATURE, encoding="utf-8"
        )
        _, formatter, _ = self.run_behave(*parameters.NO_UPLOAD)
        self.assertEqual(
            formatter.payload(None, parameters.DEFAULT_PRODUCT)["test_suite_name"],
            parameters.MANY_FEATURES,
            "two features are suite 'features'",
        )
        self.assertEqual(
            formatter.payload(None, parameters.DEFAULT_PRODUCT)["product_id"],
            parameters.DEFAULT_PRODUCT,
            "the default product is used",
        )
        clock = self.by_method(formatter)[parameters.CLOCK]
        self.assertEqual(
            clock["metadata"]["tc_id"],
            parameters.CLOCK_TC,
            "the feature tag gives the test case id",
        )
        self.assertEqual(
            clock["metadata"]["behave_tags"], parameters.CLOCK_TAGS, "the feature's tag is kept"
        )
        with contextlib.redirect_stderr(io.StringIO()):
            behave_main(
                ["-f", config.CAPTURE, "-o", os.devnull, "--no-summary", *parameters.NO_UPLOAD]
            )
        self.assertEqual(
            CAPTURED[-1].payload(None, None)["test_suite_name"],
            parameters.MANY_FEATURES,
            "the default folder is suite 'features'",
        )
        _, formatter, _ = self.run_behave(*parameters.NO_UPLOAD, *parameters.SUITE_OPTION)
        self.assertEqual(
            formatter.payload(None, None)["test_suite_name"],
            parameters.SUITE_NAME,
            "a given suite name wins",
        )

    def bud_the_run_is_uploaded_without_a_skipped_count_when_no_feature_is_all_skipped(self):
        """The run uploads its 8 results for the station and product, without a run update."""
        with self.backend() as backend:
            rc, _, err = self.run_behave(*parameters.BACKEND_OPTION)
        self.assertEqual(rc, parameters.FAILED, "Behave exits 1")
        self.assertEqual(
            len(backend.made), parameters.ONE, "one client is made", abort_on_fail=True
        )
        calls = backend.made[0].calls
        self.assertEqual(calls[0][0], "results", "the results are sent")
        self.assertEqual(len(calls[0][1]["results"]), parameters.RESULTS, "8 results are sent")
        self.assertEqual(
            calls[0][1]["product_id"], config.PRODUCT_ID, "the station's product is sent"
        )
        self.assertEqual(calls[0][1]["runner_account"], config.STATION, "the station is named")
        self.assertEqual([call[0] for call in calls], ["results"], "no skipped count is updated")
        self.assertIn(
            member=messages.UPLOADED, container=err, msg=f"stderr says {messages.UPLOADED!r}"
        )

    def bud_a_failed_upload_is_spooled(self):
        """A failed upload is spooled with its run id."""
        with self.backend(fail=True) as backend:
            self.run_behave(*parameters.RUN_ID_OPTION)
        self.assertEqual(
            len(backend.spooled), parameters.ONE, "the payload is spooled once", abort_on_fail=True
        )
        self.assertEqual(
            backend.spooled[0]["test_run_id"],
            parameters.RUN_ID,
            "the spooled payload keeps its run",
        )
        self.assertEqual(
            [call[0] for call in backend.made[0].calls], ["results"], "only the results were tried"
        )

    def bud_an_upload_error_never_changes_the_exit_code(self):
        """A reporting error is printed and the passing run still exits 0."""

        def boom(backend_url=None):
            """Fail to load the station identity."""
            raise RuntimeError(messages.NO_CREDENTIALS)

        (self.project / "features" / "bench.feature").write_text(
            parameters.SECOND_FEATURE, encoding="utf-8"
        )
        with patch.object(auth, "AuthManager", boom):
            rc, _, err = self.run_behave()
        self.assertEqual(rc, parameters.OK, "Behave exits 0")
        self.assertIn(
            member=messages.COULD_NOT_REPORT,
            container=err,
            msg=f"stderr says {messages.COULD_NOT_REPORT!r}",
        )

    def bud_run_behave_passes_behave_arguments_and_exit_code(self):
        """run-behave adds the formatter and options, keeps the user's arguments and Behave's exit code."""
        import behave.__main__ as behave_entry

        seen: dict = {}

        def fake_main(args):
            """Record the arguments and fail."""
            seen["args"] = args
            return parameters.FAILED

        with patch.object(behave_entry, "main", fake_main):
            result = CliRunner().invoke(cli.app, parameters.RUN_BEHAVE)
            args = seen["args"]
            CliRunner().invoke(cli.app, parameters.PROGRESS)
            progress = seen["args"]
        self.assertEqual(result.exit_code, parameters.FAILED, "run-behave keeps exit 1")
        self.assertEqual(
            args[:4],
            ["-f", config.BUD_FORMATTER, "-o", os.devnull],
            "the Bud formatter comes first",
        )
        self.assertEqual(args[4:6], ["-f", "pretty"], "pretty output is added")
        for option in parameters.PASSED_ON:
            self.assertIn(member=option, container=args, msg=f"{option!r} is passed on")
        self.assertEqual(args[-2:], parameters.BEHAVE_TAIL, "the user's arguments come last")
        self.assertNotIn(
            member="pretty", container=progress, msg="a given formatter replaces pretty"
        )
        self.assertEqual(
            progress[-3:], parameters.PROGRESS_TAIL, "the given formatter and path come last"
        )

    def bud_run_behave_names_the_extra_when_behave_is_missing(self):
        """Without Behave, run-behave exits 2 and names the extra to install."""
        with patch.dict(sys.modules, {"behave.__main__": None}):
            result = CliRunner().invoke(cli.app, ["run-behave", "--no-upload", "features/"])
        self.assertEqual(result.exit_code, parameters.REFUSED, "run-behave exits 2")
        self.assertIn(
            member=messages.INSTALL_EXTRA,
            container=result.output,
            msg=f"it says {messages.INSTALL_EXTRA!r}",
        )

    def bud_run_behave_replays_the_spool_first_and_needs_a_backend(self):
        """run-behave flushes the spool before running and exits 2 without a backend."""
        import behave.__main__ as behave_entry

        flushed: list = []
        with (
            patch.object(behave_entry, "main", lambda args: parameters.OK),
            patch.object(
                cli,
                "AuthManager",
                lambda backend_url=None: SimpleNamespace(backend_url=backend_url),
            ),
            patch.object(cli, "BudAPIClient", lambda a: "client"),
            patch.object(cli, "_flush_spooled_results", lambda *a: flushed.append(a[0])),
        ):
            result = CliRunner().invoke(
                cli.app, ["run-behave", "--backend-url", config.BACKEND, "features/"]
            )
        self.assertEqual(result.exit_code, parameters.OK, f"run-behave exits 0: {result.output}")
        self.assertEqual(flushed, ["client"], "the spool is flushed")
        with (
            patch.object(behave_entry, "main", lambda args: parameters.OK),
            patch.object(
                cli, "AuthManager", lambda backend_url=None: SimpleNamespace(backend_url=None)
            ),
        ):
            result = CliRunner().invoke(cli.app, ["run-behave", "features/"])
        self.assertEqual(
            result.exit_code, parameters.REFUSED, "without a backend run-behave exits 2"
        )

    def bud_run_behave_runs_behave_with_the_console_output_kept(self):
        """run-behave runs the project and keeps Behave's console output."""
        result = CliRunner().invoke(
            cli.app, ["run-behave", "--no-upload", "--tags=-@excluded", "features"]
        )
        self.assertEqual(result.exit_code, parameters.FAILED, "run-behave exits 1")
        self.assertIn(
            member=messages.VOLTAGE_SCENARIO,
            container=result.output,
            msg="Behave's output is shown",
        )
