"""
Ensure ``run_tests`` does not PATCH method-level totals after upload.

Backend ``POST /api/results`` rolls up ``total_tests`` / ``passed_tests`` /
``failed_tests`` by ``test_class``. Sending flattened method-row counts would
overwrite that TC-class contract (e.g. 3 methods → dashboard shows 3 instead of 1).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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
                with patch("bud_runner.cli.BudAPIClient") as MockClient:
                    client_inst = MockClient.return_value
                    client_inst.upload_results.return_value = True
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
                with patch("bud_runner.cli.BudAPIClient") as MockClient:
                    client_inst = MockClient.return_value
                    client_inst.upload_results.return_value = True
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
