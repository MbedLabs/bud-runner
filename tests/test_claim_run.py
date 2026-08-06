"""Tests for ``claim-run`` and the test case list it generates."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests
from typer.testing import CliRunner

from bud_runner.api_client import BudAPIClient
from bud_runner.cli import _custom_dir, _run_claimed, _write_custom_test_list, app


@pytest.fixture(autouse=True)
def _custom_modules_in_tmp(tmp_path, monkeypatch):
    """Keep generated modules out of the shared temp directory."""
    monkeypatch.setattr("bud_runner.cli.tempfile.gettempdir", lambda: str(tmp_path))


def _claimed(run_id=7, selected=None, test_case_list="Suite.CASES"):
    return {
        "run": {"id": run_id, "name": "Custom run", "test_case_list": test_case_list},
        "selected_tests": selected,
    }


def _auth(runner_token="runner-token"):
    return SimpleNamespace(
        backend_url="http://localhost:8000",
        token="user-token",
        runner_token=runner_token,
        runner_account="bench-01",
        runner_api_key=None,
    )


# ==================== the generated test case list ====================


def test_written_list_loads_through_the_stock_executor(monkeypatch):
    """The generated module is what TestExecutor.load_test_list already reads."""
    from bud_runner.test_executor import TestExecutor

    selection = ["voltage_suite.VoltageTest", "boot_suite.BootTest"]
    test_case_list = _write_custom_test_list(selection, 42)
    monkeypatch.syspath_prepend(str(_custom_dir()))

    module_name, list_name = test_case_list.rsplit(".", 1)
    assert list_name == "CUSTOM_TEST_LIST"

    executor = TestExecutor()
    with patch.object(TestExecutor, "_load_test_class", side_effect=lambda path: path):
        assert executor.load_test_list(test_case_list) == selection


def test_each_run_gets_its_own_module():
    """Two runs must not collide in the import cache."""
    first = _write_custom_test_list(["a.A"], 1)
    second = _write_custom_test_list(["b.B"], 2)

    assert first != second
    assert (_custom_dir() / "bud_custom_1.py").exists()
    assert (_custom_dir() / "bud_custom_2.py").exists()


def test_paths_are_written_as_literals():
    _write_custom_test_list(["suite.Test'X"], 3)

    body = (_custom_dir() / "bud_custom_3.py").read_text(encoding="utf-8")
    assert "suite.Test'X" in body
    assert compile(body, "bud_custom_3.py", "exec")


# ==================== handing the run to run-tests ====================


def test_a_custom_run_executes_the_generated_list():
    with patch("bud_runner.cli.subprocess.run", return_value=SimpleNamespace(returncode=0)) as run:
        _run_claimed(_claimed(selected=["suite.Alpha"]), [], None)

    cmd = run.call_args.args[0]
    assert cmd[:4] == [sys.executable, "-m", "bud_runner", "run-tests"]
    assert "bud_custom_7.CUSTOM_TEST_LIST" in cmd
    assert cmd[cmd.index("--test-run-id") + 1] == "7"


def test_an_ordinary_run_keeps_its_own_test_case_list():
    with patch("bud_runner.cli.subprocess.run", return_value=SimpleNamespace(returncode=0)) as run:
        _run_claimed(_claimed(selected=None, test_case_list="Bud_Suite.HIL"), [], None)

    cmd = run.call_args.args[0]
    assert "Bud_Suite.HIL" in cmd
    assert not list(_custom_dir().glob("*.py"))


def test_the_generated_module_is_importable_by_the_child():
    with patch("bud_runner.cli.subprocess.run", return_value=SimpleNamespace(returncode=0)) as run:
        _run_claimed(_claimed(selected=["suite.Alpha"]), [], None)

    env = run.call_args.kwargs["env"]
    assert env["PYTHONPATH"].split(":")[0] == str(_custom_dir())


def test_options_are_passed_through(tmp_path):
    with patch("bud_runner.cli.subprocess.run", return_value=SimpleNamespace(returncode=0)) as run:
        _run_claimed(_claimed(selected=["suite.Alpha"]), ["--artifact", "*.png"], tmp_path)

    cmd = run.call_args.args[0]
    assert cmd[-2:] == ["--artifact", "*.png"]
    assert run.call_args.kwargs["cwd"] == tmp_path


# ==================== the claim itself ====================


def test_claim_uses_the_runner_token():
    """A user token is not a test station, and the backend refuses it."""
    client = BudAPIClient(_auth())
    response = MagicMock(status_code=200)
    response.json.return_value = _claimed()

    with patch.object(client._session, "post", return_value=response) as post:
        client.claim_next_run()

    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer runner-token"


def test_an_empty_queue_is_not_an_error():
    client = BudAPIClient(_auth())

    with patch.object(client._session, "post", return_value=MagicMock(status_code=204)):
        assert client.claim_next_run() is None


def test_a_rejected_claim_raises():
    client = BudAPIClient(_auth())
    response = MagicMock(status_code=403)
    response.raise_for_status.side_effect = requests.HTTPError("403")

    with patch.object(client._session, "post", return_value=response):
        with pytest.raises(requests.HTTPError):
            client.claim_next_run()


# ==================== the command ====================


def _invoke(args, claim_side_effect=None, claim_return=None):
    with patch("bud_runner.cli.AuthManager", return_value=_auth()):
        with patch("bud_runner.cli.BudAPIClient") as MockClient:
            client = MockClient.return_value
            if claim_side_effect is not None:
                client.claim_next_run.side_effect = claim_side_effect
            else:
                client.claim_next_run.return_value = claim_return
            with patch("bud_runner.cli._run_claimed", return_value=0) as run_claimed:
                result = CliRunner().invoke(app, ["claim-run", *args])
    return result, client, run_claimed


def test_claims_once_and_exits():
    result, client, run_claimed = _invoke([], claim_return=_claimed(selected=["suite.Alpha"]))

    assert result.exit_code == 0, result.stdout
    assert client.claim_next_run.call_count == 1
    assert run_claimed.call_count == 1
    assert "Claimed run 7" in result.stdout


def test_an_empty_queue_runs_nothing():
    result, _, run_claimed = _invoke([], claim_return=None)

    assert result.exit_code == 0
    run_claimed.assert_not_called()
    assert "Nothing queued" in result.stdout


def test_polling_survives_a_backend_blip():
    """A station outlives the backend it talks to."""
    calls = [requests.ConnectionError("refused"), _claimed(selected=["suite.Alpha"])]

    with patch("bud_runner.cli.time.sleep", side_effect=[None, KeyboardInterrupt]):
        result, client, run_claimed = _invoke(["--interval", "5"], claim_side_effect=calls)

    assert client.claim_next_run.call_count == 2
    assert run_claimed.call_count == 1
    assert "Could not claim a run" in result.stdout + result.stderr


def test_a_one_shot_claim_reports_a_failure():
    result, _, run_claimed = _invoke([], claim_side_effect=requests.ConnectionError("refused"))

    assert result.exit_code == 1
    run_claimed.assert_not_called()


def test_registration_is_required():
    with patch("bud_runner.cli.AuthManager", return_value=_auth(runner_token=None)):
        result = CliRunner().invoke(app, ["claim-run"])

    assert result.exit_code == 2
    assert "register" in result.stdout + result.stderr
