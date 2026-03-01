"""
Ensure ``run_tests`` does not PATCH method-level totals after upload.

Backend ``POST /api/results`` rolls up ``total_tests`` / ``passed_tests`` /
``failed_tests`` by ``test_class``. Sending flattened method-row counts would
overwrite that TC-class contract (e.g. 3 methods → dashboard shows 3 instead of 1).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests
from typer.testing import CliRunner

from bud_runner.api_client import _flatten_results
from bud_runner.cli import app
from tests.test_flatten_results import _FakeAssertion, _FakeMethodResult, _FakeRunResult


def _one_tc_three_methods_all_pass():
    return [
        _FakeRunResult(
            test_class="VoltageTest",
            method_results=[
                _FakeMethodResult("bud_a", True, [_FakeAssertion(True, "ok")]),
                _FakeMethodResult("bud_b", True, [_FakeAssertion(True, "ok")]),
                _FakeMethodResult("bud_c", True, [_FakeAssertion(True, "ok")]),
            ],
        )
    ]


def _default_upload_payload():
    return {"results": [{"test_class": "VoltageTest", "test_method": "bud_a"}]}


def test_run_tests_post_upload_patch_omits_counter_fields(tmp_path):
    """Flatten yields 3 rows; PATCH must not send method totals."""
    results = _one_tc_three_methods_all_pass()
    assert len(_flatten_results(results)) == 3

    out = tmp_path / "report.xml"
    mock_exec = MagicMock()
    mock_exec.run_test_list.return_value = results
    mock_rep = MagicMock()
    mock_rep.generate.return_value = "<testsuites/>"

    auth_ns = SimpleNamespace(
        backend_url="http://localhost:8000",
        product_id=None,
        token=None,
    )

    with patch("bud_runner.cli.TestExecutor", return_value=mock_exec):
        with patch("bud_runner.cli.JUnitReporter", return_value=mock_rep):
            with patch("bud_runner.cli.AuthManager", return_value=auth_ns):
                with patch("bud_runner.cli._flush_spooled_results"):
                    with patch("bud_runner.cli.BudAPIClient") as MockClient:
                        client_inst = MockClient.return_value
                        client_inst.build_results_payload.return_value = _default_upload_payload()
                        client_inst.upload_results_payload.return_value = True
                        client_inst.get_test_run.return_value = {"product_id": None}
                        client_inst.update_test_run.return_value = {}

                        runner = CliRunner()
                        result = runner.invoke(
                            app,
                            [
                                "run-tests",
                                "-t",
                                "dummy.suite",
                                "--backend-url",
                                "http://localhost:8000",
                                "--test-run-id",
                                "42",
                                "--format",
                                "junit",
                                "-o",
                                str(out),
                            ],
                        )

    assert result.exit_code == 0, result.stdout + "\n" + result.stderr
    client_inst.update_test_run.assert_called_once()
    kwargs = client_inst.update_test_run.call_args.kwargs
    assert kwargs["run_id"] == 42
    assert kwargs["status"] == "Completed"
    assert "duration_seconds" in kwargs
    assert "total_tests" not in kwargs
    assert "passed_tests" not in kwargs
    assert "failed_tests" not in kwargs


def test_run_tests_post_upload_still_omits_counters_when_suite_failed(tmp_path):
    """Exit non-zero for failed TC, but never overwrite DB totals with method grain."""
    results = [
        _FakeRunResult(
            test_class="BetaTest",
            method_results=[
                _FakeMethodResult("bud_one", True, [_FakeAssertion(True, "ok")]),
                _FakeMethodResult("bud_two", False, [_FakeAssertion(False, "nope")]),
            ],
        )
    ]

    out = tmp_path / "report.xml"
    mock_exec = MagicMock()
    mock_exec.run_test_list.return_value = results
    mock_rep = MagicMock()
    mock_rep.generate.return_value = "<testsuites/>"

    auth_ns = SimpleNamespace(
        backend_url="http://localhost:8000",
        product_id=None,
        token=None,
    )

    with patch("bud_runner.cli.TestExecutor", return_value=mock_exec):
        with patch("bud_runner.cli.JUnitReporter", return_value=mock_rep):
            with patch("bud_runner.cli.AuthManager", return_value=auth_ns):
                with patch("bud_runner.cli._flush_spooled_results"):
                    with patch("bud_runner.cli.BudAPIClient") as MockClient:
                        client_inst = MockClient.return_value
                        client_inst.build_results_payload.return_value = _default_upload_payload()
                        client_inst.upload_results_payload.return_value = True
                        client_inst.get_test_run.return_value = {"product_id": None}
                        client_inst.update_test_run.return_value = {}

                        runner = CliRunner()
                        result = runner.invoke(
                            app,
                            [
                                "run-tests",
                                "-t",
                                "dummy.suite",
                                "--backend-url",
                                "http://localhost:8000",
                                "--test-run-id",
                                "7",
                                "--format",
                                "junit",
                                "-o",
                                str(out),
                            ],
                        )

    assert result.exit_code == 1
    kwargs = client_inst.update_test_run.call_args.kwargs
    assert "total_tests" not in kwargs
    assert "passed_tests" not in kwargs
    assert "failed_tests" not in kwargs


def test_run_tests_reauths_on_upload_401_and_retries(tmp_path):
    results = _one_tc_three_methods_all_pass()
    out = tmp_path / "report.xml"
    mock_exec = MagicMock()
    mock_exec.run_test_list.return_value = results
    mock_rep = MagicMock()
    mock_rep.generate.return_value = "<testsuites/>"

    auth_ns = SimpleNamespace(
        backend_url="http://localhost:8000",
        product_id=None,
        token=None,
        save_user_token=MagicMock(),
        runner_account="ci@example.com",
        runner_api_key=None,
    )

    unauthorized = requests.HTTPError("401 Unauthorized")
    unauthorized.response = SimpleNamespace(status_code=401)

    with patch("bud_runner.cli.TestExecutor", return_value=mock_exec):
        with patch("bud_runner.cli.JUnitReporter", return_value=mock_rep):
            with patch("bud_runner.cli.AuthManager", return_value=auth_ns):
                with patch("bud_runner.cli._flush_spooled_results"):
                    with patch("bud_runner.cli.BudAPIClient") as MockClient:
                        client_inst = MockClient.return_value
                        client_inst.build_results_payload.return_value = _default_upload_payload()
                        client_inst.upload_results_payload.side_effect = [unauthorized, True]
                        client_inst.login_user.return_value = "fresh-token"
                        client_inst.get_test_run.return_value = {"product_id": None}
                        client_inst.update_test_run.return_value = {}

                        runner = CliRunner()
                        result = runner.invoke(
                            app,
                            [
                                "run-tests",
                                "-t",
                                "dummy.suite",
                                "--backend-url",
                                "http://localhost:8000",
                                "--username",
                                "ci@example.com",
                                "--password",
                                "secret-pass",
                                "--test-run-id",
                                "42",
                                "--format",
                                "junit",
                                "-o",
                                str(out),
                            ],
                        )

    assert result.exit_code == 0, result.output
    client_inst.login_user.assert_called_once_with("ci@example.com", "secret-pass")
    auth_ns.save_user_token.assert_called_once_with("ci@example.com", "fresh-token")
    assert client_inst.upload_results_payload.call_count == 2


def test_run_tests_reauth_retry_preserves_test_software_metadata(tmp_path):
    results = _one_tc_three_methods_all_pass()
    out = tmp_path / "report.xml"
    mock_exec = MagicMock()
    mock_exec.run_test_list.return_value = results
    mock_rep = MagicMock()
    mock_rep.generate.return_value = "<testsuites/>"

    auth_ns = SimpleNamespace(
        backend_url="http://localhost:8000",
        product_id=None,
        token=None,
        save_user_token=MagicMock(),
        runner_account="ci@example.com",
        runner_api_key=None,
    )

    unauthorized = requests.HTTPError("401 Unauthorized")
    unauthorized.response = SimpleNamespace(status_code=401)

    with patch("bud_runner.cli.TestExecutor", return_value=mock_exec):
        with patch("bud_runner.cli.JUnitReporter", return_value=mock_rep):
            with patch("bud_runner.cli.AuthManager", return_value=auth_ns):
                with patch("bud_runner.cli._flush_spooled_results"):
                    with patch("bud_runner.cli.BudAPIClient") as MockClient:
                        client_inst = MockClient.return_value
                        payload = _default_upload_payload()
                        payload["url_test_software"] = "https://github.com/example/fw-under-test"
                        payload["ref_test_software"] = "abc123def"
                        client_inst.build_results_payload.return_value = payload
                        client_inst.upload_results_payload.side_effect = [unauthorized, True]
                        client_inst.login_user.return_value = "fresh-token"
                        client_inst.get_test_run.return_value = {"product_id": None}
                        client_inst.update_test_run.return_value = {}

                        runner = CliRunner()
                        result = runner.invoke(
                            app,
                            [
                                "run-tests",
                                "-t",
                                "dummy.suite",
                                "--backend-url",
                                "http://localhost:8000",
                                "--username",
                                "ci@example.com",
                                "--password",
                                "secret-pass",
                                "--url-test-software",
                                "https://github.com/example/fw-under-test",
                                "--ref-test-software",
                                "abc123def",
                                "--format",
                                "junit",
                                "-o",
                                str(out),
                            ],
                        )

    assert result.exit_code == 0, result.output
    assert client_inst.upload_results_payload.call_count == 2
    first_call = client_inst.upload_results_payload.call_args_list[0].args[0]
    retry_call = client_inst.upload_results_payload.call_args_list[1].args[0]
    assert first_call["url_test_software"] == "https://github.com/example/fw-under-test"
    assert first_call["ref_test_software"] == "abc123def"
    assert retry_call["url_test_software"] == "https://github.com/example/fw-under-test"
    assert retry_call["ref_test_software"] == "abc123def"


def test_run_tests_preserves_separate_software_under_test_metadata(tmp_path):
    results = _one_tc_three_methods_all_pass()
    out = tmp_path / "report.xml"
    mock_exec = MagicMock()
    mock_exec.run_test_list.return_value = results
    mock_rep = MagicMock()
    mock_rep.generate.return_value = "<testsuites/>"

    auth_ns = SimpleNamespace(
        backend_url="http://localhost:8000",
        product_id=None,
        token=None,
    )

    with patch("bud_runner.cli.TestExecutor", return_value=mock_exec):
        with patch("bud_runner.cli.JUnitReporter", return_value=mock_rep):
            with patch("bud_runner.cli.AuthManager", return_value=auth_ns):
                with patch("bud_runner.cli._flush_spooled_results"):
                    with patch("bud_runner.cli.BudAPIClient") as MockClient:
                        client_inst = MockClient.return_value
                        payload = _default_upload_payload()
                        payload["url_test_software"] = "https://github.com/example/test-suite"
                        payload["ref_test_software"] = "tests-abc123"
                        payload["url_software_under_test"] = "https://github.com/example/firmware"
                        payload["ref_software_under_test"] = "fw-abc123"
                        client_inst.build_results_payload.return_value = payload
                        client_inst.upload_results_payload.return_value = True

                        runner = CliRunner()
                        result = runner.invoke(
                            app,
                            [
                                "run-tests",
                                "-t",
                                "dummy.suite",
                                "--backend-url",
                                "http://localhost:8000",
                                "--format",
                                "junit",
                                "--url-test-software",
                                "https://github.com/example/test-suite",
                                "--ref-test-software",
                                "tests-abc123",
                                "--sw-under-test",
                                "https://github.com/example/firmware",
                                "--ref-sw-under-test",
                                "fw-abc123",
                                "-o",
                                str(out),
                            ],
                        )

    assert result.exit_code == 0, result.output
    client_inst.upload_results_payload.assert_called_once()
    payload = client_inst.upload_results_payload.call_args.args[0]
    assert payload["url_test_software"] == "https://github.com/example/test-suite"
    assert payload["ref_test_software"] == "tests-abc123"
    assert payload["url_software_under_test"] == "https://github.com/example/firmware"
    assert payload["ref_software_under_test"] == "fw-abc123"


def test_run_tests_spools_payload_when_upload_fails(tmp_path):
    results = _one_tc_three_methods_all_pass()
    out = tmp_path / "report.xml"
    spool_dir = tmp_path / "home" / ".bud" / "spool" / "results"
    mock_exec = MagicMock()
    mock_exec.run_test_list.return_value = results
    mock_rep = MagicMock()
    mock_rep.generate.return_value = "<testsuites/>"

    auth_ns = SimpleNamespace(
        backend_url="http://localhost:8000",
        product_id=None,
        token=None,
        save_user_token=MagicMock(),
    )

    upload_error = requests.HTTPError("503 Service Unavailable")
    upload_error.response = SimpleNamespace(status_code=503)

    with patch("bud_runner.cli.TestExecutor", return_value=mock_exec):
        with patch("bud_runner.cli.JUnitReporter", return_value=mock_rep):
            with patch("bud_runner.cli.AuthManager", return_value=auth_ns):
                with patch("bud_runner.cli.BudAPIClient") as MockClient:
                    client_inst = MockClient.return_value
                    client_inst.build_results_payload.return_value = {
                        "results": [{"test_class": "VoltageTest", "test_method": "bud_a"}]
                    }
                    client_inst.upload_results_payload.side_effect = upload_error

                    runner = CliRunner()
                    result = runner.invoke(
                        app,
                        [
                            "run-tests",
                            "-t",
                            "dummy.suite",
                            "--backend-url",
                            "http://localhost:8000",
                            "--format",
                            "junit",
                            "-o",
                            str(out),
                        ],
                        env={"HOME": str(tmp_path / "home")},
                    )

    assert result.exit_code == 1
    spooled = list(spool_dir.glob("*.json"))
    assert len(spooled) == 1
    assert "Payload spooled to" in result.output


def test_run_tests_replays_spooled_payload_before_current_upload(tmp_path):
    results = _one_tc_three_methods_all_pass()
    out = tmp_path / "report.xml"
    spool_dir = tmp_path / "home" / ".bud" / "spool" / "results"
    spool_dir.mkdir(parents=True)
    (spool_dir / "pending.json").write_text(
        '{"results":[{"test_class":"PendingTest","test_method":"bud_pending"}]}'
    )
    mock_exec = MagicMock()
    mock_exec.run_test_list.return_value = results
    mock_rep = MagicMock()
    mock_rep.generate.return_value = "<testsuites/>"

    auth_ns = SimpleNamespace(
        backend_url="http://localhost:8000",
        product_id=None,
        token=None,
        save_user_token=MagicMock(),
    )

    with patch("bud_runner.cli.TestExecutor", return_value=mock_exec):
        with patch("bud_runner.cli.JUnitReporter", return_value=mock_rep):
            with patch("bud_runner.cli.AuthManager", return_value=auth_ns):
                with patch("bud_runner.cli.BudAPIClient") as MockClient:
                    client_inst = MockClient.return_value
                    client_inst.build_results_payload.return_value = {
                        "results": [{"test_class": "VoltageTest", "test_method": "bud_a"}]
                    }
                    client_inst.upload_results_payload.return_value = True

                    runner = CliRunner()
                    result = runner.invoke(
                        app,
                        [
                            "run-tests",
                            "-t",
                            "dummy.suite",
                            "--backend-url",
                            "http://localhost:8000",
                            "--format",
                            "junit",
                            "-o",
                            str(out),
                        ],
                        env={"HOME": str(tmp_path / "home")},
                    )

    assert result.exit_code == 0, result.output
    assert client_inst.upload_results_payload.call_count == 2
    first_payload = client_inst.upload_results_payload.call_args_list[0].args[0]
    second_payload = client_inst.upload_results_payload.call_args_list[1].args[0]
    assert first_payload["results"][0]["test_class"] == "PendingTest"
    assert second_payload["results"][0]["test_class"] == "VoltageTest"
    assert not list(spool_dir.glob("*.json"))


def test_run_tests_fails_loudly_when_upload_error_is_not_recoverable(tmp_path):
    results = _one_tc_three_methods_all_pass()
    out = tmp_path / "report.xml"
    mock_exec = MagicMock()
    mock_exec.run_test_list.return_value = results
    mock_rep = MagicMock()
    mock_rep.generate.return_value = "<testsuites/>"

    auth_ns = SimpleNamespace(
        backend_url="http://localhost:8000",
        product_id=None,
        token=None,
        runner_account="ci@example.com",
    )

    upload_error = requests.HTTPError("500 Server Error")
    upload_error.response = SimpleNamespace(status_code=500)

    with patch("bud_runner.cli.TestExecutor", return_value=mock_exec):
        with patch("bud_runner.cli.JUnitReporter", return_value=mock_rep):
            with patch("bud_runner.cli.AuthManager", return_value=auth_ns):
                with patch("bud_runner.cli._flush_spooled_results"):
                    with patch("bud_runner.cli.BudAPIClient") as MockClient:
                        client_inst = MockClient.return_value
                        client_inst.build_results_payload.return_value = _default_upload_payload()
                        client_inst.upload_results_payload.side_effect = upload_error
                        client_inst.get_test_run.return_value = {"product_id": None}

                        runner = CliRunner()
                        result = runner.invoke(
                            app,
                            [
                                "run-tests",
                                "-t",
                                "dummy.suite",
                                "--backend-url",
                                "http://localhost:8000",
                                "--format",
                                "junit",
                                "-o",
                                str(out),
                            ],
                        )

    assert result.exit_code == 1
    assert "Result upload failed" in result.output


def test_run_tests_forwards_test_software_metadata(tmp_path):
    results = _one_tc_three_methods_all_pass()
    out = tmp_path / "report.xml"
    mock_exec = MagicMock()
    mock_exec.run_test_list.return_value = results
    mock_rep = MagicMock()
    mock_rep.generate.return_value = "<testsuites/>"

    auth_ns = SimpleNamespace(
        backend_url="http://localhost:8000",
        product_id=None,
        token=None,
        runner_account="ci@example.com",
    )

    with patch("bud_runner.cli.TestExecutor", return_value=mock_exec):
        with patch("bud_runner.cli.JUnitReporter", return_value=mock_rep):
            with patch("bud_runner.cli.AuthManager", return_value=auth_ns):
                with patch("bud_runner.cli._flush_spooled_results"):
                    with patch("bud_runner.cli.BudAPIClient") as MockClient:
                        client_inst = MockClient.return_value
                        payload = _default_upload_payload()
                        payload["url_test_software"] = "https://github.com/example/repo"
                        payload["ref_test_software"] = "abc123"
                        client_inst.build_results_payload.return_value = payload
                        client_inst.upload_results_payload.return_value = True

                        runner = CliRunner()
                        result = runner.invoke(
                            app,
                            [
                                "run-tests",
                                "-t",
                                "dummy.suite",
                                "--backend-url",
                                "http://localhost:8000",
                                "--format",
                                "junit",
                                "--url-test-software",
                                "https://github.com/example/repo",
                                "--ref-test-software",
                                "abc123",
                                "-o",
                                str(out),
                            ],
                        )

    assert result.exit_code == 0, result.output
    client_inst.upload_results_payload.assert_called_once()
    payload = client_inst.upload_results_payload.call_args.args[0]
    assert payload["url_test_software"] == "https://github.com/example/repo"
    assert payload["ref_test_software"] == "abc123"
