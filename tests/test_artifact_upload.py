"""Tests for ``run-tests --artifact``."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from bud_runner.cli import _discover_artifacts, _upload_artifacts, app
from tests.test_flatten_results import _FakeAssertion, _FakeMethodResult, _FakeRunResult


def _uploaded(client):
    return [call.args[0] for call in client.upload_artifact.call_args_list]


def _results():
    return [
        _FakeRunResult(
            test_class="VoltageTest",
            method_results=[_FakeMethodResult("test_idle", True, [_FakeAssertion(True, "ok")])],
        )
    ]


def _run_cli(tmp_path, extra_args, artifact_side_effect=None, monkeypatch=None):
    """Drive run-tests with the backend mocked, as the other CLI tests do."""
    if monkeypatch is not None:
        monkeypatch.chdir(tmp_path)
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


def test_run_tests_uploads_artifacts_after_the_results(tmp_path, monkeypatch):
    shot = tmp_path / "failure.png"
    shot.write_text("x")

    result, client = _run_cli(
        tmp_path, ["--test-run-id", "42", "-A", str(shot)], monkeypatch=monkeypatch
    )

    assert result.exit_code == 0, result.stdout
    assert str(shot) in _uploaded(client)


def test_the_report_is_uploaded_without_being_asked_for(tmp_path, monkeypatch):
    """Every run produces one; a run whose report is not in Bud is not evidence."""
    result, client = _run_cli(tmp_path, ["--test-run-id", "42"], monkeypatch=monkeypatch)

    assert result.exit_code == 0
    assert [Path(p).name for p in _uploaded(client)] == ["report.xml"]


def test_run_tests_needs_a_test_run_id(tmp_path):
    shot = tmp_path / "failure.png"
    shot.write_text("x")

    result, client = _run_cli(tmp_path, ["-A", str(shot)])

    client.upload_artifact.assert_not_called()
    assert "Artifacts need a test run" in result.output


def test_a_failed_artifact_does_not_fail_the_run(tmp_path):
    shot = tmp_path / "failure.png"
    shot.write_text("x")

    result, _ = _run_cli(
        tmp_path,
        ["--test-run-id", "42", "-A", str(shot)],
        artifact_side_effect=RuntimeError("413 Payload Too Large"),
    )

    assert result.exit_code == 0
    assert "Could not upload" in result.output


# ==================== what a run leaves behind ====================


def test_discovers_logs_beside_the_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "bench.log").write_text("x")
    (tmp_path / "stderr.err").write_text("x")
    (tmp_path / "notes.md").write_text("x")

    found = [p.name for p in _discover_artifacts(tmp_path / "bud-artifacts")]

    assert sorted(found) == ["bench.log", "stderr.err"]


def test_discovers_packet_captures(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "can.pcapng").write_text("x")
    (tmp_path / "bus.trace").write_text("x")

    found = [p.name for p in _discover_artifacts(tmp_path / "bud-artifacts")]

    assert sorted(found) == ["bus.trace", "can.pcapng"]


def test_takes_everything_in_the_artifact_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    artifacts = tmp_path / "bud-artifacts"
    (artifacts / "plots").mkdir(parents=True)
    (artifacts / "screenshot.png").write_text("x")
    (artifacts / "plots" / "voltage.svg").write_text("x")

    found = [p.name for p in _discover_artifacts(artifacts)]

    # The directory exists to be uploaded, so its shape is not second-guessed.
    assert sorted(found) == ["screenshot.png", "voltage.svg"]


def test_finds_nothing_when_the_run_left_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert _discover_artifacts(tmp_path / "bud-artifacts") == []


def test_never_walks_the_workspace(tmp_path, monkeypatch):
    """A bench workspace is a repository; sweeping it would upload the source."""
    monkeypatch.chdir(tmp_path)
    nested = tmp_path / "node_modules" / "pkg"
    nested.mkdir(parents=True)
    # Named to match a discovery pattern: only the depth keeps it out.
    (nested / "install.log").write_text("x")
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "debug.trace").write_text("x")
    (tmp_path / "voltage_suite.py").write_text("x")

    assert _discover_artifacts(tmp_path / "bud-artifacts") == []


def test_a_run_sends_its_report_and_what_it_left(tmp_path, monkeypatch):
    (tmp_path / "bud-artifacts").mkdir()
    (tmp_path / "bud-artifacts" / "failure.png").write_text("x")
    (tmp_path / "bench.log").write_text("x")

    result, client = _run_cli(tmp_path, ["--test-run-id", "42"], monkeypatch=monkeypatch)

    assert result.exit_code == 0, result.stdout
    assert sorted(Path(p).name for p in _uploaded(client)) == [
        "bench.log",
        "failure.png",
        "report.xml",
    ]


def test_the_report_is_not_sent_twice_when_named_explicitly(tmp_path, monkeypatch):
    out = tmp_path / "report.xml"

    result, client = _run_cli(
        tmp_path, ["--test-run-id", "42", "-A", str(out)], monkeypatch=monkeypatch
    )

    assert result.exit_code == 0
    assert [Path(p).name for p in _uploaded(client)] == ["report.xml"]


def test_a_discovered_file_that_will_not_upload_does_not_fail_the_run(tmp_path, monkeypatch):
    (tmp_path / "huge.pcap").write_text("x")

    result, _ = _run_cli(
        tmp_path,
        ["--test-run-id", "42"],
        artifact_side_effect=RuntimeError("413 Payload Too Large"),
        monkeypatch=monkeypatch,
    )

    assert result.exit_code == 0
    assert "Could not upload" in result.stdout + result.stderr
