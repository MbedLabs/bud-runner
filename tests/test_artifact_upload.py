"""Tests for ``run-tests --artifact``."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from bud_runner.cli import _upload_artifacts, app
from tests.test_flatten_results import _FakeAssertion, _FakeMethodResult, _FakeRunResult


def _results():
    return [
        _FakeRunResult(
            test_class="VoltageTest",
            method_results=[_FakeMethodResult("test_idle", True, [_FakeAssertion(True, "ok")])],
        )
    ]


def _run_cli(tmp_path, extra_args, artifact_side_effect=None):
    """Drive run-tests with the backend mocked, as the other CLI tests do."""
    out = tmp_path / "report.xml"
    mock_exec = MagicMock()
    mock_exec.run_test_list.return_value = _results()
    mock_rep = MagicMock()
    mock_rep.generate.return_value = "<testsuites/>"
    auth_ns = SimpleNamespace(backend_url="http://localhost:8000", product_id=None, token=None)

    with patch("bud_runner.cli.TestExecutor", return_value=mock_exec):
        with patch("bud_runner.cli.JUnitReporter", return_value=mock_rep):
            with patch("bud_runner.cli.AuthManager", return_value=auth_ns):
                with patch("bud_runner.cli._flush_spooled_results"):
                    with patch("bud_runner.cli.BudAPIClient") as MockClient:
                        client = MockClient.return_value
                        client.build_results_payload.return_value = {"results": [{"a": 1}]}
                        client.upload_results_payload.return_value = True
                        client.get_test_run.return_value = {"product_id": None}
                        client.update_test_run.return_value = {}
                        if artifact_side_effect is not None:
                            client.upload_artifact.side_effect = artifact_side_effect

                        result = CliRunner().invoke(
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
                                *extra_args,
                            ],
                        )
    return result, client


def test_uploads_a_named_file(tmp_path):
    client = MagicMock()
    shot = tmp_path / "failure.png"
    shot.write_text("x")

    _upload_artifacts(client, [str(shot)], 42)

    client.upload_artifact.assert_called_once_with(str(shot), run_id=42)


def test_expands_a_glob(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = MagicMock()
    (tmp_path / "a.png").write_text("x")
    (tmp_path / "b.png").write_text("x")
    (tmp_path / "notes.txt").write_text("x")

    _upload_artifacts(client, ["*.png"], 42)

    uploaded = sorted(call.args[0] for call in client.upload_artifact.call_args_list)
    assert uploaded == ["a.png", "b.png"]


def test_warns_when_a_pattern_matches_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    client = MagicMock()

    _upload_artifacts(client, ["*.png"], 42)

    client.upload_artifact.assert_not_called()
    assert "No artifact matched" in capsys.readouterr().err


def test_one_failure_does_not_stop_the_rest(tmp_path):
    client = MagicMock()
    client.upload_artifact.side_effect = [RuntimeError("413"), {"id": 2}]
    first = tmp_path / "a.png"
    first.write_text("x")
    second = tmp_path / "b.png"
    second.write_text("x")

    _upload_artifacts(client, [str(first), str(second)], 42)

    assert client.upload_artifact.call_count == 2


def test_run_tests_uploads_artifacts_after_the_results(tmp_path):
    shot = tmp_path / "failure.png"
    shot.write_text("x")

    result, client = _run_cli(tmp_path, ["--test-run-id", "42", "-A", str(shot)])

    assert result.exit_code == 0, result.stdout
    client.upload_artifact.assert_called_once_with(str(shot), run_id=42)


def test_run_tests_uploads_nothing_when_none_requested(tmp_path):
    result, client = _run_cli(tmp_path, ["--test-run-id", "42"])

    assert result.exit_code == 0
    client.upload_artifact.assert_not_called()


def test_run_tests_needs_a_test_run_id(tmp_path):
    shot = tmp_path / "failure.png"
    shot.write_text("x")

    result, client = _run_cli(tmp_path, ["-A", str(shot)])

    client.upload_artifact.assert_not_called()
    assert "Artifacts need a test run" in result.stdout + result.stderr


def test_a_failed_artifact_does_not_fail_the_run(tmp_path):
    shot = tmp_path / "failure.png"
    shot.write_text("x")

    result, _ = _run_cli(
        tmp_path,
        ["--test-run-id", "42", "-A", str(shot)],
        artifact_side_effect=RuntimeError("413 Payload Too Large"),
    )

    assert result.exit_code == 0
    assert "Could not upload" in result.stdout + result.stderr
