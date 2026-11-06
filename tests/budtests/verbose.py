"""Verbose logging across the CLI and the isolated execution worker, with the executor and Bud
mocked."""

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from budtestlibrary import BudTestCase, parameterized
from typer.testing import CliRunner

from bud_runner.cli import app
from bud_runner.test_executor import TestExecutor as Executor
from tests.budtests.config import Verbose as c
from tests.budtests.parameters import Verbose as p


class LoggingSuite:
    """A suite stand-in that reports the logging level it received inside the worker."""

    def set_loglevel(self, level):
        """Keep the level the worker sets."""
        self.level = level

    def run(self):
        """Pass."""
        return True

    def get_results(self):
        """The level received, as the suite's only result."""
        return [{"loglevel": self.level}]


class Verbose(BudTestCase):
    """--verbose reaches the spawned suite through run-tests and claim-run."""

    @parameterized(p.LEVELS)
    def bud_the_spawned_suite_receives_the_selected_logging_level(self, verbose, level):
        """The worker sets DEBUG on the suite with verbose, INFO without."""
        result = Executor(test_timeout=c.TEST_TIMEOUT, verbose=verbose).run_test_class(LoggingSuite)
        self.assertTrue(result.passed, "the suite passes")
        self.assertEqual(result.method_results, [{"loglevel": level}], f"verbose={verbose} gives level {level}")

    @parameterized(p.FLAGS)
    def bud_run_tests_passes_verbosity_to_the_executor(self, flag, verbose):
        """run-tests builds its executor with verbose set by --verbose or -v."""
        report = Path(os.environ[c.WORK_DIR_SETTING]) / c.REPORT_NAME
        report.parent.mkdir(parents=True, exist_ok=True)
        executor = MagicMock()
        executor.run_test_list.return_value = []
        with patch("bud_runner.cli.TestExecutor", return_value=executor) as factory:
            result = CliRunner().invoke(
                app, ["run-tests", "-t", p.TEST_LIST, "--no-upload", "-o", str(report), *flag]
            )
        self.assertEqual(result.exit_code, p.PASSED_EXIT, f"run-tests {flag} exits 0: {result.output}")
        self.assertEqual(factory.call_args.kwargs.get("verbose"), verbose, f"{flag} gives verbose={verbose}")

    @parameterized(p.FLAGS)
    def bud_claim_run_forwards_verbosity_to_its_execution(self, flag, verbose):
        """claim-run passes --verbose on to the run it starts only when given --verbose or -v."""
        auth = SimpleNamespace(backend_url=c.BACKEND_URL, runner_token=c.STATION_TOKEN, runner_account=c.ACCOUNT)
        client = MagicMock()
        client.claim_next_run.return_value = p.CLAIM
        with (
            patch("bud_runner.cli.AuthManager", return_value=auth),
            patch("bud_runner.cli.BudAPIClient", return_value=client),
            patch("bud_runner.cli._run_claimed", return_value=p.PASSED_EXIT) as execute,
        ):
            result = CliRunner().invoke(app, ["claim-run", *flag])
        self.assertEqual(result.exit_code, p.PASSED_EXIT, f"claim-run {flag} exits 0: {result.output}")
        self.assertEqual(
            p.VERBOSE_FLAG in execute.call_args.args[1], verbose, f"{flag} forwards --verbose: {verbose}"
        )
