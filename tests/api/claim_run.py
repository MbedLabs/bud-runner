"""claim-run and the test case list it generates, with Bud's client, the child process, the clock and
the station identity mocked, and every step's generated modules in a folder of its own."""

import os
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests
from budtestlibrary import BudTestCase
from typer.testing import CliRunner

from bud_runner.api_client import BudAPIClient
from bud_runner.cli import _custom_dir, _run_claimed, _write_custom_test_list, app
from bud_runner.test_executor import TestExecutor
from tests.config import ClaimRun as config
from tests.messages import ClaimRun as messages
from tests.parameters import ClaimRun as parameters


class ClaimRun(BudTestCase):
    """Generated lists, the child run, the claim calls and the claim-run command."""

    def setUp(self):
        """Send this step's generated modules to a new folder."""
        folder = Path(os.environ[config.WORK_DIR_SETTING]) / config.FOLDER / uuid.uuid4().hex
        folder.mkdir(parents=True)
        self.temp = patch(config.TEMP_TARGET, return_value=str(folder))
        self.temp.start()

    def tearDown(self):
        """Stop sending modules to this step's folder."""
        self.temp.stop()

    def claimed(self, selected=None, test_case_list=parameters.DEFAULT_LIST) -> dict:
        """A claim answer for run 7."""
        return {
            "claim_id": parameters.CLAIM_ID,
            "run": {
                "id": parameters.RUN_ID,
                "name": parameters.RUN_NAME,
                "test_case_list": test_case_list,
            },
            "selected_tests": selected,
        }

    def auth(self, runner_token=config.RUNNER_TOKEN):
        """A station identity."""
        return SimpleNamespace(
            backend_url=config.BACKEND_URL,
            token=config.USER_TOKEN,
            runner_token=runner_token,
            runner_account=config.ACCOUNT,
            runner_api_key=None,
        )

    def child(self, claim, passthrough=None, cwd=None):
        """Run a claimed run with the child process mocked and return the mock."""
        with patch(
            config.SUBPROCESS_TARGET, return_value=SimpleNamespace(returncode=parameters.PASSED)
        ) as run:
            _run_claimed(claim, passthrough or [], cwd)
        return run

    def invoke(
        self,
        args,
        claim_return=None,
        claim_side_effect=None,
        run_return=parameters.PASSED,
        run_side_effect=None,
        complete_side_effect=None,
    ):
        """Invoke claim-run with the identity, Bud's client and the run of the claim mocked."""
        with patch("bud_runner.cli.AuthManager", return_value=self.auth()):
            with patch("bud_runner.cli.BudAPIClient") as client_class:
                client = client_class.return_value
                if claim_side_effect is not None:
                    client.claim_next_run.side_effect = claim_side_effect
                else:
                    client.claim_next_run.return_value = claim_return
                if complete_side_effect is not None:
                    client.complete_claimed_run.side_effect = complete_side_effect
                with patch(
                    "bud_runner.cli._run_claimed",
                    return_value=run_return,
                    side_effect=run_side_effect,
                ) as run:
                    result = CliRunner().invoke(app, ["claim-run", *args])
        return result, client, run

    def completion(self, client) -> tuple:
        """The arguments of the one completion sent."""
        return (
            client.complete_claimed_run.call_args.args,
            client.complete_claimed_run.call_args.kwargs,
        )

    def bud_the_written_list_loads_through_the_stock_executor(self):
        """The generated module is what TestExecutor.load_test_list reads."""
        test_case_list = _write_custom_test_list(parameters.SELECTION, parameters.SELECTION_RUN)
        sys.path.insert(0, str(_custom_dir()))
        try:
            with patch.object(TestExecutor, "_load_test_class", side_effect=lambda path: path):
                loaded = TestExecutor().load_test_list(test_case_list)
        finally:
            sys.path.remove(str(_custom_dir()))
        self.assertEqual(
            test_case_list.rsplit(".", 1)[1], parameters.LIST_NAME, "the list is CUSTOM_TEST_LIST"
        )
        self.assertEqual(loaded, parameters.SELECTION, "the executor loads the selection in order")

    def bud_each_run_gets_its_own_module(self):
        """Two runs write two modules."""
        first = _write_custom_test_list(parameters.FIRST_PATH, parameters.FIRST_RUN)
        second = _write_custom_test_list(parameters.SECOND_PATH, parameters.SECOND_RUN)
        self.assertNotEqual(first, second, "the two runs get different lists")
        for run in (parameters.FIRST_RUN, parameters.SECOND_RUN):
            name = parameters.MODULE.format(run=run)
            self.assertTrue((_custom_dir() / name).exists(), f"{name} is written")

    def bud_paths_are_written_as_literals(self):
        """A path with a quote is written as a literal and the module compiles."""
        _write_custom_test_list([parameters.QUOTED_PATH], parameters.QUOTED_RUN)
        name = parameters.MODULE.format(run=parameters.QUOTED_RUN)
        body = (_custom_dir() / name).read_text(encoding="utf-8")
        self.assertIn(
            member=parameters.QUOTED_PATH, container=body, msg="the path is in the module"
        )
        self.assertTrue(compile(body, name, "exec") is not None, "the module compiles")

    def bud_a_custom_run_executes_the_generated_list(self):
        """A selection runs run-tests on the generated list for its run."""
        command = self.child(self.claimed(selected=parameters.ALPHA)).call_args.args[0]
        self.assertEqual(
            command[:4],
            [sys.executable, *parameters.RUN_TESTS],
            "the child is bud_runner run-tests",
        )
        self.assertIn(
            member=parameters.CUSTOM_LIST, container=command, msg="the generated list is run"
        )
        self.assertEqual(
            command[command.index("--test-run-id") + 1],
            str(parameters.RUN_ID),
            "the run id is passed",
        )

    def bud_an_ordinary_run_keeps_its_own_test_case_list(self):
        """A run without a selection runs its own list and writes no module."""
        command = self.child(self.claimed(test_case_list=parameters.OWN_LIST)).call_args.args[0]
        self.assertIn(
            member=parameters.OWN_LIST, container=command, msg="the run's own list is run"
        )
        self.assertEqual(list(_custom_dir().glob("*.py")), [], "no module is written")

    def bud_the_generated_module_is_importable_by_the_child(self):
        """The child's PYTHONPATH starts with the generated modules' folder."""
        env = self.child(self.claimed(selected=parameters.ALPHA)).call_args.kwargs["env"]
        self.assertEqual(
            env["PYTHONPATH"].split(":")[0], str(_custom_dir()), "the folder comes first"
        )

    def bud_options_are_passed_through(self):
        """Extra options reach run-tests and the child runs in the given folder."""
        cwd = _custom_dir()
        run = self.child(self.claimed(selected=parameters.ALPHA), parameters.PASSTHROUGH, cwd)
        self.assertEqual(
            run.call_args.args[0][-2:], parameters.PASSTHROUGH, "the options are passed on"
        )
        self.assertEqual(run.call_args.kwargs.get("cwd"), cwd, "the child runs in the given folder")

    def bud_a_claim_uses_the_runner_token(self):
        """The claim sends the station token and the claim id as idempotency key."""
        client = BudAPIClient(self.auth())
        response = MagicMock(status_code=parameters.OK)
        response.json.return_value = self.claimed()
        with patch.object(client._session, "post", return_value=response) as post:
            client.claim_next_run(parameters.CLAIM_ID)
        headers = post.call_args.kwargs["headers"]
        self.assertEqual(
            headers.get("Authorization"),
            f"Bearer {config.RUNNER_TOKEN}",
            "the station token is sent",
        )
        self.assertEqual(
            headers.get("Idempotency-Key"),
            parameters.CLAIM_ID,
            "the claim id is the idempotency key",
        )

    def bud_an_empty_queue_is_not_an_error(self):
        """204 means nothing is queued."""
        client = BudAPIClient(self.auth())
        with patch.object(
            client._session, "post", return_value=MagicMock(status_code=parameters.EMPTY)
        ):
            self.assertEqual(client.claim_next_run(), None, "nothing is claimed")

    def bud_a_rejected_claim_raises(self):
        """A refused claim raises the HTTP error."""
        client = BudAPIClient(self.auth())
        response = MagicMock(status_code=parameters.FORBIDDEN)
        response.raise_for_status.side_effect = requests.HTTPError(str(parameters.FORBIDDEN))
        raised = None
        with patch.object(client._session, "post", return_value=response):
            try:
                client.claim_next_run()
            except requests.HTTPError as error:
                raised = error
        self.assertTrue(raised is not None, "the refusal raises HTTPError")

    def bud_completion_sends_the_claim_key_and_the_terminal_answer(self):
        """Completion posts to the run's complete route with the claim key, exit code and error."""
        client = BudAPIClient(self.auth())
        response = MagicMock(status_code=parameters.OK)
        response.json.return_value = parameters.COMPLETED
        with patch.object(client._session, "post", return_value=response) as post:
            completed = client.complete_claimed_run(
                parameters.RUN_ID,
                parameters.CLAIM_ID,
                exit_code=parameters.FAILED,
                error=parameters.EXECUTOR_ERROR,
            )
        self.assertEqual(completed, parameters.COMPLETED, "the answer is returned")
        self.assertTrue(
            post.call_args.args[0].endswith(f"/runners/runs/{parameters.RUN_ID}/complete"),
            "the run's route is used",
        )
        self.assertEqual(
            post.call_args.kwargs["headers"].get("Idempotency-Key"),
            parameters.CLAIM_ID,
            "the claim key is sent",
        )
        self.assertEqual(
            post.call_args.kwargs["json"],
            {"exit_code": parameters.FAILED, "error": parameters.EXECUTOR_ERROR},
            "the answer is sent",
        )

    def bud_claim_run_claims_once_and_exits(self):
        """One claim, one run, one completion with exit 0."""
        result, client, run = self.invoke([], claim_return=self.claimed(selected=parameters.ALPHA))
        self.assertEqual(result.exit_code, parameters.PASSED, f"claim-run exits 0: {result.output}")
        self.assertEqual(client.claim_next_run.call_count, parameters.ONE, "one claim")
        self.assertEqual(run.call_count, parameters.ONE, "one run")
        self.assertEqual(
            self.completion(client),
            (
                (parameters.RUN_ID, parameters.CLAIM_ID),
                {"exit_code": parameters.PASSED, "error": None},
            ),
            "one completion",
        )
        self.assertIn(
            member=messages.CLAIMED,
            container=result.stdout,
            msg=f"claim-run prints {messages.CLAIMED!r}",
        )

    def bud_the_child_keeps_the_resolved_station_and_backend(self):
        """The run gets the resolved backend and station name."""
        result, _, run = self.invoke([], claim_return=self.claimed(selected=parameters.ALPHA))
        passthrough = run.call_args.args[1]
        self.assertEqual(result.exit_code, parameters.PASSED, f"claim-run exits 0: {result.output}")
        self.assertEqual(
            passthrough[passthrough.index("--backend-url") + 1],
            config.BACKEND_URL,
            "the backend is passed",
        )
        self.assertEqual(
            passthrough[passthrough.index("--username") + 1],
            config.ACCOUNT,
            "the station is passed",
        )

    def bud_an_empty_queue_runs_nothing(self):
        """Nothing queued runs nothing and says so."""
        result, _, run = self.invoke([], claim_return=None)
        self.assertEqual(result.exit_code, parameters.PASSED, "claim-run exits 0")
        self.assertEqual(run.call_count, parameters.NONE, "nothing runs")
        self.assertIn(
            member=messages.NOTHING_QUEUED,
            container=result.stdout,
            msg=f"claim-run prints {messages.NOTHING_QUEUED!r}",
        )

    def bud_polling_survives_a_backend_blip(self):
        """A refused claim is retried with the same claim id and the run then starts."""
        calls = [requests.ConnectionError("refused"), self.claimed(selected=parameters.ALPHA)]
        with patch(config.SLEEP_TARGET, side_effect=[None, KeyboardInterrupt]):
            result, client, run = self.invoke(parameters.INTERVAL, claim_side_effect=calls)
        ids = [call.args[0] for call in client.claim_next_run.call_args_list]
        self.assertEqual(
            client.claim_next_run.call_count, parameters.TWO, "the claim is tried twice"
        )
        self.assertEqual(ids[0], ids[1], "both tries use the same claim id")
        self.assertEqual(run.call_count, parameters.ONE, "the run starts once")
        self.assertIn(
            member=messages.COULD_NOT_CLAIM,
            container=result.output,
            msg=f"claim-run prints {messages.COULD_NOT_CLAIM!r}",
        )

    def bud_a_nonzero_test_exit_is_acknowledged_as_finished(self):
        """A failing run is completed with exit 1 and claim-run exits 1."""
        result, client, _ = self.invoke(
            [], claim_return=self.claimed(), run_return=parameters.FAILED
        )
        self.assertEqual(result.exit_code, parameters.FAILED, "claim-run exits 1")
        self.assertEqual(
            self.completion(client),
            (
                (parameters.RUN_ID, parameters.CLAIM_ID),
                {"exit_code": parameters.FAILED, "error": None},
            ),
            "exit 1 is sent",
        )

    def bud_the_commands_code_is_the_runs_own(self):
        """A configuration error of the run (2) is claim-run's exit code."""
        result, _, _ = self.invoke(
            [], claim_return=self.claimed(), run_return=parameters.CONFIG_ERROR
        )
        self.assertEqual(result.exit_code, parameters.CONFIG_ERROR, "claim-run exits 2")

    def bud_a_poller_keeps_polling_when_a_run_fails(self):
        """With an interval, a failing run is completed and polling goes on until interrupted."""
        with patch(config.SLEEP_TARGET, side_effect=[KeyboardInterrupt]):
            result, client, run = self.invoke(
                parameters.INTERVAL, claim_return=self.claimed(), run_return=parameters.FAILED
            )
        self.assertEqual(
            result.exit_code, parameters.INTERRUPTED, "the poller ends only on the interrupt"
        )
        self.assertEqual(
            client.complete_claimed_run.call_count, parameters.ONE, "the run is completed"
        )
        self.assertEqual(run.call_count, parameters.ONE, "the run ran once")

    def bud_an_executor_error_is_acknowledged_before_the_command_fails(self):
        """An executor crash is completed with exit 1 and the error, then claim-run exits 1."""
        result, client, _ = self.invoke(
            [], claim_return=self.claimed(), run_side_effect=RuntimeError(parameters.EXECUTOR_ERROR)
        )
        self.assertEqual(result.exit_code, parameters.FAILED, "claim-run exits 1")
        self.assertEqual(
            self.completion(client),
            (
                (parameters.RUN_ID, parameters.CLAIM_ID),
                {"exit_code": parameters.FAILED, "error": parameters.WRAPPED_ERROR},
            ),
            "the crash is sent",
        )

    def bud_polling_retries_the_answer_without_running_or_claiming_again(self):
        """A completion that fails is retried without a new claim or run."""
        with patch(config.SLEEP_TARGET, side_effect=[None, KeyboardInterrupt]):
            result, client, run = self.invoke(
                parameters.INTERVAL,
                claim_return=self.claimed(),
                complete_side_effect=[requests.ConnectionError("refused"), {}],
            )
        self.assertEqual(
            result.exit_code, parameters.INTERRUPTED, "the poller ends on the interrupt"
        )
        self.assertEqual(client.claim_next_run.call_count, parameters.ONE, "one claim")
        self.assertEqual(
            client.complete_claimed_run.call_count, parameters.TWO, "the completion is retried"
        )
        self.assertEqual(run.call_count, parameters.ONE, "one run")

    def bud_a_one_shot_claim_reports_a_failure(self):
        """Without an interval a refused claim exits 1 and runs nothing."""
        result, _, run = self.invoke([], claim_side_effect=requests.ConnectionError("refused"))
        self.assertEqual(result.exit_code, parameters.FAILED, "claim-run exits 1")
        self.assertEqual(run.call_count, parameters.NONE, "nothing runs")

    def bud_registration_is_required(self):
        """Without a station token claim-run exits 2 and asks to register."""
        with patch("bud_runner.cli.AuthManager", return_value=self.auth(runner_token=None)):
            result = CliRunner().invoke(app, ["claim-run"])
        self.assertEqual(result.exit_code, parameters.CONFIG_ERROR, "claim-run exits 2")
        self.assertIn(
            member=messages.REGISTER, container=result.output, msg="claim-run asks to register"
        )
