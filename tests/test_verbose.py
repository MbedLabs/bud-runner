"""Verbose logging across the CLI and isolated execution worker."""

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from bud_runner.cli import app
from bud_runner.test_executor import TestExecutor as Executor


class LoggingSuite:
    """Report the logging level received inside the spawned worker."""

    def set_loglevel(self, level):
        self.level = level

    def run(self):
        return True

    def get_results(self):
        return [{"loglevel": self.level}]


@pytest.mark.parametrize("verbose,level", [(False, logging.INFO), (True, logging.DEBUG)])
def test_spawned_suite_receives_the_selected_logging_level(verbose, level):
    result = Executor(test_timeout=10, verbose=verbose).run_test_class(LoggingSuite)
    assert result.passed
    assert result.method_results == [{"loglevel": level}]


@pytest.mark.parametrize("flag,verbose", [([], False), (["--verbose"], True), (["-v"], True)])
def test_run_tests_passes_verbosity_to_executor(tmp_path, flag, verbose):
    executor = MagicMock()
    executor.run_test_list.return_value = []
    with patch("bud_runner.cli.TestExecutor", return_value=executor) as factory:
        result = CliRunner().invoke(
            app,
            [
                "run-tests",
                "-t",
                "Suite.CASES",
                "--no-upload",
                "-o",
                str(tmp_path / "result.xml"),
                *flag,
            ],
        )
    assert result.exit_code == 0, result.output
    assert factory.call_args.kwargs["verbose"] is verbose


@pytest.mark.parametrize("flag,verbose", [([], False), (["--verbose"], True), (["-v"], True)])
def test_claim_run_forwards_verbosity_to_its_execution(flag, verbose):
    auth = SimpleNamespace(
        backend_url="https://bud.example", runner_token="station-token", runner_account="station-01"
    )
    client = MagicMock()
    client.claim_next_run.return_value = {
        "run": {"id": 4, "name": "Run"},
        "claim_id": "claim",
        "selected_tests": None,
    }
    with (
        patch("bud_runner.cli.AuthManager", return_value=auth),
        patch("bud_runner.cli.BudAPIClient", return_value=client),
        patch("bud_runner.cli._run_claimed", return_value=0) as execute,
    ):
        result = CliRunner().invoke(app, ["claim-run", *flag])
    assert result.exit_code == 0, result.output
    assert ("--verbose" in execute.call_args.args[1]) is verbose
