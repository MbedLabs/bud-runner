"""What run-tests sends to Bud after a run: the run update without method totals, the software
metadata, the spool on a recoverable failure and its replay, with the executor, the reporter, the
identity and Bud's client mocked."""

import contextlib
import os
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests
from budtestlibrary import BudTestCase
from typer.testing import CliRunner

from bud_runner.api_client import _flatten_results
from bud_runner.cli import app
from tests.config import RunTestsUpload as config
from tests.doubles import Assertion, MethodResult, RunResult
from tests.messages import RunTestsUpload as messages
from tests.parameters import RunTestsUpload as parameters


class RunTestsUpload(BudTestCase):
    """The upload and run update of run-tests."""

    def setUp(self):
        """A new folder for the report and the station's home."""
        self.folder = Path(os.environ[config.WORK_DIR_SETTING]) / config.FOLDER / uuid.uuid4().hex
        self.folder.mkdir(parents=True)
        self.home = self.folder / "home"
        self.spool = self.home / config.SPOOL

    def run_of(self, test_class: str, methods: list) -> list:
        """One test class run with the given (method, passed) rows."""
        rows = [
            MethodResult(name, passed, [Assertion(passed, parameters.CHECK_TEXT)])
            for name, passed in methods
        ]
        return [RunResult(test_class=test_class, method_results=rows)]

    @contextlib.contextmanager
    def station(self, results: list, payload: dict, flush: bool = False, **identity):
        """Mock the executor, the reporter, the identity, the spool flush and Bud's client; yield the
        client."""
        executor = MagicMock()
        executor.run_test_list.return_value = results
        reporter = MagicMock()
        reporter.generate.return_value = parameters.REPORT
        station = SimpleNamespace(
            backend_url=config.BACKEND, product_id=None, token=None, **identity
        )
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch("bud_runner.cli.TestExecutor", return_value=executor))
            stack.enter_context(patch("bud_runner.cli.JUnitReporter", return_value=reporter))
            stack.enter_context(patch("bud_runner.cli.AuthManager", return_value=station))
            if not flush:
                stack.enter_context(patch("bud_runner.cli._flush_spooled_results"))
            client = stack.enter_context(patch("bud_runner.cli.BudAPIClient")).return_value
            client.build_results_payload.return_value = payload
            client.upload_results_payload.return_value = True
            client.get_test_run.return_value = {"product_id": None}
            client.update_test_run.return_value = {}
            yield client

    def run_tests(self, *options, home: bool = False):
        """Invoke run-tests on the dummy suite with a JUnit report."""
        args = [
            "run-tests",
            "-t",
            config.SUITE,
            "--backend-url",
            config.BACKEND,
            *options,
            "--format",
            "junit",
        ]
        args += ["-o", str(self.folder / config.REPORT_NAME)]
        return CliRunner().invoke(app, args, env={"HOME": str(self.home)} if home else None)

    def http_error(self, text: str, status: int) -> requests.HTTPError:
        """An HTTP error with the given status."""
        error = requests.HTTPError(text)
        error.response = SimpleNamespace(status_code=status)
        return error

    def bud_the_run_update_omits_method_totals(self):
        """Three passing methods flatten to three rows, and the run update sends no totals."""
        results = self.run_of(parameters.PASSING_CLASS, parameters.PASSING)
        self.assertEqual(
            len(_flatten_results(results)), parameters.ROWS, "three methods flatten to three rows"
        )
        with self.station(results, dict(parameters.PAYLOAD)) as client:
            result = self.run_tests("--test-run-id", str(parameters.RUN_ID))
        self.assertEqual(result.exit_code, parameters.OK, f"run-tests exits 0: {result.output}")
        self.assertEqual(
            client.update_test_run.call_count,
            parameters.ONE,
            "the run is updated once",
            abort_on_fail=True,
        )
        kwargs = client.update_test_run.call_args.kwargs
        self.assertEqual(kwargs["run_id"], parameters.RUN_ID, "run 42 is updated")
        self.assertEqual(kwargs["status"], parameters.COMPLETED, "the run is Completed")
        self.assertIn(member="duration_seconds", container=kwargs, msg="the duration is sent")
        for counter in parameters.COUNTERS:
            self.assertNotIn(member=counter, container=kwargs, msg=f"{counter} is not sent")

    def bud_a_failed_run_still_omits_method_totals(self):
        """A failing method exits 1 and still sends no totals."""
        with self.station(
            self.run_of(parameters.MIXED_CLASS, parameters.MIXED), dict(parameters.PAYLOAD)
        ) as client:
            result = self.run_tests("--test-run-id", str(parameters.FAILED_RUN_ID))
        self.assertEqual(result.exit_code, parameters.FAILED, "run-tests exits 1")
        kwargs = client.update_test_run.call_args.kwargs
        for counter in parameters.COUNTERS:
            self.assertNotIn(member=counter, container=kwargs, msg=f"{counter} is not sent")

    def bud_the_software_under_test_is_kept_apart_from_the_test_software(self):
        """The four software references reach the upload unchanged."""
        with self.station(
            self.run_of(parameters.PASSING_CLASS, parameters.PASSING),
            {**parameters.PAYLOAD, **parameters.SOFTWARE},
        ) as client:
            result = self.run_tests(*parameters.SOFTWARE_OPTIONS)
        self.assertEqual(result.exit_code, parameters.OK, f"run-tests exits 0: {result.output}")
        self.assertEqual(
            client.upload_results_payload.call_count,
            parameters.ONE,
            "one upload",
            abort_on_fail=True,
        )
        sent = client.upload_results_payload.call_args.args[0]
        for key, value in parameters.SOFTWARE.items():
            self.assertEqual(sent.get(key), value, f"{key} is {value!r}")

    def bud_a_recoverable_upload_failure_is_spooled(self):
        """A 503 on upload exits 1 and leaves one spooled payload."""
        results = self.run_of(parameters.PASSING_CLASS, parameters.PASSING)
        with self.station(
            results, dict(parameters.PAYLOAD), flush=True, save_user_token=MagicMock()
        ) as client:
            client.upload_results_payload.side_effect = self.http_error(
                messages.UNAVAILABLE, parameters.UNAVAILABLE
            )
            result = self.run_tests(home=True)
        self.assertEqual(result.exit_code, parameters.FAILED, "run-tests exits 1")
        self.assertEqual(
            len(list(self.spool.glob("*.json"))), parameters.ONE, "one payload is spooled"
        )
        self.assertIn(
            member=messages.SPOOLED, container=result.output, msg=f"it says {messages.SPOOLED!r}"
        )

    def bud_a_spooled_payload_is_replayed_before_the_new_upload(self):
        """A pending spooled payload is uploaded first, then the run's, and the spool is emptied."""
        self.spool.mkdir(parents=True)
        (self.spool / "pending.json").write_text(parameters.PENDING)
        results = self.run_of(parameters.PASSING_CLASS, parameters.PASSING)
        with self.station(
            results, dict(parameters.PAYLOAD), flush=True, save_user_token=MagicMock()
        ) as client:
            result = self.run_tests(home=True)
        self.assertEqual(result.exit_code, parameters.OK, f"run-tests exits 0: {result.output}")
        self.assertEqual(
            client.upload_results_payload.call_count,
            parameters.TWO,
            "two uploads",
            abort_on_fail=True,
        )
        first, second = (call.args[0] for call in client.upload_results_payload.call_args_list)
        self.assertEqual(
            first["results"][0]["test_class"],
            parameters.PENDING_CLASS,
            "the spooled payload goes first",
        )
        self.assertEqual(
            second["results"][0]["test_class"],
            parameters.PASSING_CLASS,
            "the run's payload goes second",
        )
        self.assertEqual(
            len(list(self.spool.glob("*.json"))), parameters.NONE, "the spool is empty"
        )

    def bud_an_unrecoverable_upload_failure_fails_loudly(self):
        """A 500 on upload exits 1 and says the upload failed."""
        results = self.run_of(parameters.PASSING_CLASS, parameters.PASSING)
        with self.station(
            results, dict(parameters.PAYLOAD), runner_account=config.STATION
        ) as client:
            client.upload_results_payload.side_effect = self.http_error(
                messages.SERVER_ERROR, parameters.SERVER_ERROR
            )
            result = self.run_tests()
        self.assertEqual(result.exit_code, parameters.FAILED, "run-tests exits 1")
        self.assertIn(
            member=messages.UPLOAD_FAILED,
            container=result.output,
            msg=f"it says {messages.UPLOAD_FAILED!r}",
        )

    def bud_the_test_software_metadata_is_forwarded(self):
        """The test software's URL and reference reach the upload."""
        payload = {**parameters.PAYLOAD, **parameters.TEST_SOFTWARE}
        with self.station(
            self.run_of(parameters.PASSING_CLASS, parameters.PASSING),
            payload,
            runner_account=config.STATION,
        ) as client:
            result = self.run_tests(*parameters.TEST_SOFTWARE_OPTIONS)
        self.assertEqual(result.exit_code, parameters.OK, f"run-tests exits 0: {result.output}")
        self.assertEqual(
            client.upload_results_payload.call_count,
            parameters.ONE,
            "one upload",
            abort_on_fail=True,
        )
        sent = client.upload_results_payload.call_args.args[0]
        for key, value in parameters.TEST_SOFTWARE.items():
            self.assertEqual(sent.get(key), value, f"{key} is {value!r}")
