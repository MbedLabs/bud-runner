"""run-tests artifacts: named, globbed and discovered files, the report, the files steps attached
and their display names, with the executor, the reporter, the identity and Bud's client
mocked."""

import contextlib
import io
import os
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from budtestlibrary import BudTestCase
from typer.testing import CliRunner

from bud_runner.cli import (
    _discover_artifacts,
    _display_name,
    _step_artifacts,
    _upload_artifacts,
    app,
)
from tests.config import ArtifactUpload as config
from tests.doubles import Assertion, MethodResult, RunResult
from tests.messages import ArtifactUpload as messages
from tests.parameters import ArtifactUpload as parameters


class ArtifactUpload(BudTestCase):
    """The artifacts run-tests sends to Bud."""

    def setUp(self):
        """A new folder for the step's files and report."""
        self.folder = Path(os.environ[config.WORK_DIR_SETTING]) / config.FOLDER / uuid.uuid4().hex
        self.folder.mkdir(parents=True)

    @contextlib.contextmanager
    def inside(self):
        """Run the block with the step's folder as the working directory."""
        before = os.getcwd()
        os.chdir(self.folder)
        try:
            yield
        finally:
            os.chdir(before)

    def write(self, *parts: str) -> Path:
        """A file in the step's folder, its parent folders created."""
        path = self.folder.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x")
        return path

    def run_results(self) -> list:
        """One passing test class run."""
        rows = [MethodResult(config.RUN_METHOD, True, [Assertion(True, parameters.CHECK_TEXT)])]
        return [RunResult(test_class=config.RUN_CLASS, method_results=rows)]

    def step_results(self, *steps) -> list:
        """Results whose steps attached files, as budtestlibrary's attach_artifact leaves them."""
        return [
            SimpleNamespace(
                test_class=config.STEP_CLASS,
                passed=True,
                method_results=[
                    {
                        "method_name": name,
                        "passed": True,
                        "assertions": [],
                        "metadata": {"artifacts": entries},
                    }
                    for name, entries in steps
                ],
            )
        ]

    def run_tests(self, *options, results=None, answer=True, upload_effect=None, created=None):
        """Invoke run-tests in the step's folder with the executor, the reporter, the identity,
        the spool flush and Bud's client mocked; return the result and the client."""
        executor = MagicMock()
        executor.run_test_list.return_value = results if results is not None else self.run_results()
        reporter = MagicMock()
        reporter.generate.return_value = parameters.REPORT
        station = SimpleNamespace(backend_url=config.BACKEND, product_id=None, token=None)
        with contextlib.ExitStack() as stack:
            stack.enter_context(self.inside())
            stack.enter_context(patch("bud_runner.cli.TestExecutor", return_value=executor))
            stack.enter_context(patch("bud_runner.cli.JUnitReporter", return_value=reporter))
            stack.enter_context(patch("bud_runner.cli.AuthManager", return_value=station))
            stack.enter_context(patch("bud_runner.cli._flush_spooled_results"))
            client = stack.enter_context(patch("bud_runner.cli.BudAPIClient")).return_value
            client.build_results_payload.return_value = dict(parameters.PAYLOAD)
            client.create_test_run.return_value = (
                {"id": parameters.CREATED_RUN_ID} if created is None else created
            )
            client.upload_results_payload.return_value = answer
            client.get_test_run.return_value = {"product_id": None}
            client.update_test_run.return_value = {}
            if upload_effect is not None:
                client.upload_artifact.side_effect = upload_effect
            args = ["run-tests", "-t", config.SUITE, "--backend-url", config.BACKEND]
            args += ["--format", "junit", "-o", str(self.folder / config.REPORT_NAME), *options]
            result = CliRunner().invoke(app, args)
        return result, client

    def uploaded_names(self, client) -> list:
        """The file names sent, in order."""
        return [Path(sent.args[0]).name for sent in client.upload_artifact.call_args_list]

    def step_uploads(self, client) -> list:
        """The (file name, run, test case, display name) of each upload made for a step."""
        return [
            (
                Path(sent.args[0]).name,
                sent.kwargs.get("run_id"),
                sent.kwargs.get("test_case"),
                sent.kwargs.get("filename"),
            )
            for sent in client.upload_artifact.call_args_list
            if sent.kwargs.get("test_case")
        ]

    def refuse_step_uploads(self, path, run_id=None, test_case=None, filename=None):
        """Bud's answer when it refuses every upload made for a step."""
        if test_case:
            raise RuntimeError(messages.STORAGE_FULL)
        return {}

    def bud_a_named_file_is_uploaded_to_the_run(self):
        """A named file is sent once to the given run."""
        client = MagicMock()
        shot = self.write(parameters.SHOT)
        _upload_artifacts(client, [str(shot)], parameters.RUN_ID)
        self.assertEqual(
            client.upload_artifact.call_args_list,
            [call(str(shot), run_id=parameters.RUN_ID)],
            "the file is sent once to run 42",
        )

    def bud_a_glob_is_expanded(self):
        """A glob sends the files it matches and nothing else."""
        client = MagicMock()
        for name in [*parameters.GLOBBED, parameters.NOT_GLOBBED]:
            self.write(name)
        with self.inside():
            _upload_artifacts(client, [parameters.GLOB], parameters.RUN_ID)
        uploaded = sorted(sent.args[0] for sent in client.upload_artifact.call_args_list)
        self.assertEqual(uploaded, parameters.GLOBBED, "the two PNG files are sent")

    def bud_a_pattern_that_matches_nothing_is_warned(self):
        """A pattern matching no file sends nothing and says so on stderr."""
        client = MagicMock()
        errors = io.StringIO()
        with self.inside(), contextlib.redirect_stderr(errors):
            _upload_artifacts(client, [parameters.GLOB], parameters.RUN_ID)
        self.assertEqual(client.upload_artifact.call_count, 0, "nothing is sent")
        self.assertIn(
            member=messages.NO_MATCH,
            container=errors.getvalue(),
            msg=f"stderr says {messages.NO_MATCH!r}",
        )

    def bud_one_failed_upload_does_not_stop_the_rest(self):
        """A refused first file still lets the second one be sent."""
        client = MagicMock()
        client.upload_artifact.side_effect = [
            RuntimeError(parameters.TOO_LARGE),
            parameters.SECOND_ANSWER,
        ]
        files = [str(self.write(name)) for name in parameters.GLOBBED]
        _upload_artifacts(client, files, parameters.RUN_ID)
        self.assertEqual(client.upload_artifact.call_count, parameters.BOTH, "both files are tried")

    def bud_run_tests_uploads_artifacts_after_the_results(self):
        """An artifact named with -A is sent with the run."""
        shot = self.write(parameters.SHOT)
        result, client = self.run_tests("--test-run-id", str(parameters.RUN_ID), "-A", str(shot))
        self.assertEqual(result.exit_code, parameters.OK, f"run-tests exits 0: {result.output}")
        self.assertIn(
            member=str(shot),
            container=[sent.args[0] for sent in client.upload_artifact.call_args_list],
            msg="the named file is sent",
        )

    def bud_the_report_is_uploaded_without_being_asked_for(self):
        """The run's report is sent though no artifact is named."""
        result, client = self.run_tests("--test-run-id", str(parameters.RUN_ID))
        self.assertEqual(result.exit_code, parameters.OK, f"run-tests exits 0: {result.output}")
        self.assertEqual(
            self.uploaded_names(client), parameters.REPORT_ONLY, "only the report is sent"
        )

    def bud_named_artifacts_use_the_run_bud_runner_created(self):
        """Without a supplied run id, a named artifact uses Bud Runner's created run."""
        shot = self.write(parameters.SHOT)
        result, client = self.run_tests("-A", str(shot))
        self.assertEqual(result.exit_code, parameters.OK, f"run-tests exits 0: {result.output}")
        self.assertEqual(
            self.uploaded_names(client),
            [config.REPORT_NAME, parameters.SHOT],
            "the generated report and named artifact are sent to the created run",
        )
        self.assertEqual(
            {sent.kwargs["run_id"] for sent in client.upload_artifact.call_args_list},
            {parameters.CREATED_RUN_ID},
            "every artifact uses the created run id",
        )

    def bud_a_failed_artifact_does_not_fail_the_run(self):
        """A refused artifact leaves the run passing and is reported."""
        shot = self.write(parameters.SHOT)
        result, _ = self.run_tests(
            "--test-run-id",
            str(parameters.RUN_ID),
            "-A",
            str(shot),
            upload_effect=RuntimeError(messages.PAYLOAD_TOO_LARGE),
        )
        self.assertEqual(result.exit_code, parameters.OK, "run-tests exits 0")
        self.assertIn(
            member=messages.COULD_NOT_UPLOAD,
            container=result.output,
            msg=f"it says {messages.COULD_NOT_UPLOAD!r}",
        )

    def bud_logs_beside_the_run_are_discovered(self):
        """Log and error files beside the run are found; other files are not."""
        for name in [*parameters.LOGS, parameters.NOT_A_LOG]:
            self.write(name)
        with self.inside():
            found = [path.name for path in _discover_artifacts(self.folder / config.ARTIFACT_DIR)]
        self.assertEqual(sorted(found), parameters.LOGS, "the log and the error file are found")

    def bud_packet_captures_are_discovered(self):
        """Capture and trace files beside the run are found."""
        for name in parameters.CAPTURES:
            self.write(name)
        with self.inside():
            found = [path.name for path in _discover_artifacts(self.folder / config.ARTIFACT_DIR)]
        self.assertEqual(sorted(found), parameters.CAPTURES, "the capture and trace are found")

    def bud_everything_in_the_artifact_directory_is_taken(self):
        """Every file in the artifact directory is found, nested ones included."""
        self.write(config.ARTIFACT_DIR, parameters.DIRECTORY_FILES[0])
        self.write(config.ARTIFACT_DIR, parameters.PLOTS, parameters.DIRECTORY_FILES[1])
        with self.inside():
            found = [path.name for path in _discover_artifacts(self.folder / config.ARTIFACT_DIR)]
        self.assertEqual(
            sorted(found), parameters.DIRECTORY_FILES, "both files of the directory are found"
        )

    def bud_nothing_is_found_when_the_run_left_nothing(self):
        """An empty run folder yields no artifact."""
        with self.inside():
            found = _discover_artifacts(self.folder / config.ARTIFACT_DIR)
        self.assertEqual(found, [], "no artifact is found")

    def bud_the_workspace_is_never_walked(self):
        """Logs in nested folders and source files of the workspace are not found."""
        self.write(*parameters.WORKSPACE_LOG)
        self.write(*parameters.VENDOR_TRACE)
        self.write(parameters.SOURCE)
        with self.inside():
            found = _discover_artifacts(self.folder / config.ARTIFACT_DIR)
        self.assertEqual(found, [], "nothing in the workspace is found")

    def bud_a_run_sends_its_report_and_what_it_left(self):
        """The report, the artifact directory's file and the log beside the run are sent."""
        self.write(config.ARTIFACT_DIR, parameters.SHOT)
        self.write(parameters.BENCH_LOG)
        result, client = self.run_tests("--test-run-id", str(parameters.RUN_ID))
        self.assertEqual(result.exit_code, parameters.OK, f"run-tests exits 0: {result.output}")
        self.assertEqual(
            sorted(self.uploaded_names(client)),
            parameters.LEFT_AND_REPORT,
            "the log, the screenshot and the report are sent",
        )

    def bud_the_report_is_not_sent_twice_when_named(self):
        """The report named with -A is still sent once."""
        report = self.folder / config.REPORT_NAME
        result, client = self.run_tests("--test-run-id", str(parameters.RUN_ID), "-A", str(report))
        self.assertEqual(result.exit_code, parameters.OK, f"run-tests exits 0: {result.output}")
        self.assertEqual(
            self.uploaded_names(client), parameters.REPORT_ONLY, "the report is sent once"
        )

    def bud_a_discovered_file_that_will_not_upload_does_not_fail_the_run(self):
        """A refused discovered file leaves the run passing and is reported."""
        self.write(parameters.HUGE)
        result, _ = self.run_tests(
            "--test-run-id",
            str(parameters.RUN_ID),
            upload_effect=RuntimeError(messages.PAYLOAD_TOO_LARGE),
        )
        self.assertEqual(result.exit_code, parameters.OK, "run-tests exits 0")
        self.assertIn(
            member=messages.COULD_NOT_UPLOAD,
            container=result.stdout + result.stderr,
            msg=f"it says {messages.COULD_NOT_UPLOAD!r}",
        )

    def bud_files_a_step_attached_are_uploaded_with_their_step(self):
        """Each attached file goes to its step under its display name, before the report."""
        capture = self.write(parameters.CAPTURE)
        boot = self.write(parameters.BOOT)
        results = self.step_results(
            ("bud_capture", [{"path": str(capture), "name": parameters.CAPTURE_NAME}]),
            ("bud_boot", [{"path": str(boot), "name": parameters.BOOT}]),
        )
        result, client = self.run_tests("--test-run-id", str(parameters.RUN_ID), results=results)
        self.assertEqual(result.exit_code, parameters.OK, f"run-tests exits 0: {result.output}")
        self.assertEqual(
            self.step_uploads(client), parameters.ATTACHED, "each file goes to its step"
        )
        names = self.uploaded_names(client)
        self.assertLess(
            names.index(parameters.CAPTURE),
            names.index(config.REPORT_NAME),
            "the step's capture is sent before the report",
        )
        self.assertIn(
            member=messages.STEP_UPLOADED,
            container=result.output,
            msg=f"it says {messages.STEP_UPLOADED!r}",
        )

    def bud_all_artifacts_go_to_the_run_bud_runner_created(self):
        """Without a supplied run id, the step file and report go to Bud Runner's created run."""
        capture = self.write(parameters.CAPTURE)
        results = self.step_results(
            ("bud_capture", [{"path": str(capture), "name": parameters.CAPTURE}])
        )
        result, client = self.run_tests(
            "--artifact",
            parameters.CAPTURE,
            results=results,
            answer={"test_run_id": parameters.CREATED_RUN_ID},
        )
        self.assertEqual(result.exit_code, parameters.OK, f"run-tests exits 0: {result.output}")
        self.assertEqual(
            self.step_uploads(client),
            parameters.ATTACHED_TO_CREATED,
            "the step's file goes to run 77",
        )
        self.assertNotIn(
            member=messages.NEED_RUN, container=result.output, msg="no artifact waits for a run id"
        )
        self.assertEqual(
            self.uploaded_names(client),
            parameters.CREATED_ARTIFACTS,
            "the attached file and generated report are sent once",
        )

    def bud_a_run_creation_without_an_id_stops_before_artifact_upload(self):
        """A create response without an id fails the command and sends no artifact."""
        capture = self.write(parameters.CAPTURE)
        results = self.step_results(
            ("bud_capture", [{"path": str(capture), "name": parameters.CAPTURE}])
        )
        result, client = self.run_tests(results=results, created={})
        self.assertEqual(result.exit_code, parameters.FAILED, "run-tests exits 1")
        self.assertIn(
            member=messages.RUN_CREATION_FAILED,
            container=result.output,
            msg=f"it says {messages.RUN_CREATION_FAILED!r}",
        )
        self.assertEqual(client.upload_artifact.call_count, 0, "nothing is sent")

    def bud_a_missing_step_artifact_is_warned_and_skipped(self):
        """A step file that is gone is reported and the others are still sent."""
        kept = self.write(parameters.KEPT)
        gone = self.folder / parameters.GONE
        results = self.step_results(
            ("bud_gone", [{"path": str(gone), "name": parameters.GONE}]),
            ("bud_kept", [{"path": str(kept), "name": parameters.KEPT}]),
        )
        result, client = self.run_tests("--test-run-id", str(parameters.RUN_ID), results=results)
        self.assertEqual(result.exit_code, parameters.OK, f"run-tests exits 0: {result.output}")
        warning = messages.STEP_NOT_FOUND.format(path=gone)
        self.assertIn(member=warning, container=result.output, msg=f"it says {warning!r}")
        self.assertEqual(
            self.step_uploads(client), parameters.ATTACHED_KEPT, "the kept file is sent"
        )

    def bud_a_step_artifact_that_fails_to_upload_does_not_fail_the_run(self):
        """A refused step file leaves the run passing and is reported."""
        capture = self.write(parameters.CAPTURE)
        results = self.step_results(
            ("bud_capture", [{"path": str(capture), "name": parameters.CAPTURE}])
        )
        result, client = self.run_tests(
            "--test-run-id",
            str(parameters.RUN_ID),
            results=results,
            upload_effect=self.refuse_step_uploads,
        )
        self.assertEqual(result.exit_code, parameters.OK, f"run-tests exits 0: {result.output}")
        warning = messages.STEP_COULD_NOT.format(path=capture)
        self.assertIn(member=warning, container=result.output, msg=f"it says {warning!r}")
        self.assertEqual(
            self.step_uploads(client), parameters.ATTACHED_CAPTURE, "the step upload was tried"
        )

    def bud_a_found_file_whose_step_upload_failed_still_goes_up_once(self):
        """A discovered file whose step upload was refused is sent once as a plain artifact."""
        log = self.write(parameters.BENCH_LOG)
        results = self.step_results(
            ("bud_bench", [{"path": str(log), "name": parameters.BENCH_LOG}])
        )
        result, client = self.run_tests(
            "--test-run-id",
            str(parameters.RUN_ID),
            results=results,
            upload_effect=self.refuse_step_uploads,
        )
        self.assertEqual(result.exit_code, parameters.OK, f"run-tests exits 0: {result.output}")
        plain = [
            Path(sent.args[0]).name
            for sent in client.upload_artifact.call_args_list
            if not sent.kwargs.get("test_case")
        ]
        self.assertEqual(
            plain.count(parameters.BENCH_LOG), parameters.ONCE, "the log is sent plainly once"
        )

    def bud_a_file_both_found_and_attached_goes_up_once_with_its_step(self):
        """A file both discovered and attached is sent once, with its step."""
        log = self.write(parameters.BENCH_LOG)
        results = self.step_results(
            ("bud_bench", [{"path": str(log), "name": parameters.BENCH_LOG}])
        )
        result, client = self.run_tests("--test-run-id", str(parameters.RUN_ID), results=results)
        self.assertEqual(result.exit_code, parameters.OK, f"run-tests exits 0: {result.output}")
        self.assertEqual(
            self.uploaded_names(client).count(parameters.BENCH_LOG),
            parameters.ONCE,
            "the log is sent once",
        )
        self.assertEqual(
            self.step_uploads(client), parameters.ATTACHED_BENCH, "it is sent with its step"
        )

    def bud_nothing_is_sent_without_upload(self):
        """--no-upload sends no artifact."""
        capture = self.write(parameters.CAPTURE)
        results = self.step_results(
            ("bud_capture", [{"path": str(capture), "name": parameters.CAPTURE}])
        )
        result, client = self.run_tests(
            "--no-upload", "--test-run-id", str(parameters.RUN_ID), results=results
        )
        self.assertEqual(result.exit_code, parameters.OK, f"run-tests exits 0: {result.output}")
        self.assertEqual(client.upload_artifact.call_count, 0, "nothing is sent")

    def bud_display_names_and_the_step_list(self):
        """Display names keep or add the file's suffix, drop control characters and stop at 255
        characters; the step list skips entries without a path and files seen before."""
        pcap = Path(parameters.PCAP)
        for given, expected in parameters.DISPLAY_NAMES:
            self.assertEqual(
                _display_name(given, pcap), expected, f"{given!r} shows as {expected!r}"
            )
        self.assertEqual(
            _display_name("", Path(parameters.NO_SUFFIX)),
            parameters.NO_SUFFIX_NAME,
            "an empty name shows the file name",
        )
        long = _display_name(parameters.LONG_NAME, pcap)
        self.assertEqual(len(long), parameters.NAME_LIMIT, "a long name stops at 255 characters")
        self.assertTrue(long.endswith(parameters.PCAP_SUFFIX), "a long name keeps its suffix")
        steps = _step_artifacts(self.step_results(*parameters.STEP_LIST_INPUT))
        self.assertEqual(
            [(path.name, name, case) for path, name, case in steps],
            parameters.STEP_LIST,
            "each file is listed once with its step",
        )
        tabbed = _step_artifacts(
            self.step_results((parameters.TABBED_STEP, [{"path": parameters.TABBED_PATH}]))
        )
        self.assertEqual(tabbed[0][2], parameters.TABBED_CASE, "a tab in the step name is dropped")
