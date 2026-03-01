"""Tests for CLI SIGINT/SIGTERM handling in run_tests."""

from __future__ import annotations

import json
import logging
import os
import signal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from bud_runner.cli import DaemonLogFormatter, _configure_daemon_logging, app
from bud_runner.runner_manager import RunnerManager


def test_run_tests_sigint_handler_sets_interrupt_then_force_exits():
    """First SIGINT sets flag; second forces os._exit (matches run_tests handler)."""
    runner = CliRunner()
    handlers: dict[int, object] = {}

    def record_signal(signum, handler):
        if signum in (signal.SIGINT, signal.SIGTERM):
            handlers[signum] = handler

    mock_results = [
        MagicMock(passed=True, test_class="T1"),
    ]

    with (
        patch("signal.signal", side_effect=record_signal),
        patch("bud_runner.cli.TestExecutor") as mock_executor_cls,
        patch("bud_runner.cli.JUnitReporter") as mock_reporter_cls,
        patch("os._exit") as mock_exit,
    ):
        mock_executor_cls.return_value.run_test_list.return_value = mock_results
        mock_reporter_cls.return_value.generate.return_value = "<testsuite/>"

        result = runner.invoke(
            app,
            [
                "run-tests",
                "--test-case-list",
                "tests.fixtures.mock_tests.MOCK_TEST_LIST",
                "--no-upload",
                "--format",
                "junit",
            ],
        )

        assert result.exit_code == 0
        assert signal.SIGINT in handlers
        on_interrupt = handlers[signal.SIGINT]
        on_interrupt(signal.SIGINT, None)
        on_interrupt(signal.SIGINT, None)
        mock_exit.assert_called_once_with(128 + signal.SIGINT)


def test_run_tests_passes_should_stop_when_executor_runs():
    """run_tests wires should_stop to the executor for cooperative shutdown."""
    runner = CliRunner()
    captured = {}

    def capture_run_test_list(*args, **kwargs):
        captured["should_stop"] = kwargs.get("should_stop")
        return [MagicMock(passed=True, test_class="T1")]

    with (
        patch("bud_runner.cli.TestExecutor") as mock_executor_cls,
        patch("bud_runner.cli.JUnitReporter") as mock_reporter_cls,
    ):
        mock_executor_cls.return_value.run_test_list.side_effect = capture_run_test_list
        mock_reporter_cls.return_value.generate.return_value = "<testsuite/>"

        result = runner.invoke(
            app,
            [
                "run-tests",
                "--test-case-list",
                "tests.fixtures.mock_tests.MOCK_TEST_LIST",
                "--no-upload",
            ],
        )

    assert result.exit_code == 0
    assert callable(captured.get("should_stop"))


@pytest.mark.asyncio
async def test_run_daemon_binds_localhost_by_default():
    manager = RunnerManager(MagicMock())
    manager._running = False
    captured = {}

    async def fake_start_server(handler, host, port):
        captured["host"] = host
        captured["port"] = port
        manager._running = False

        class DummyServer:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        return DummyServer()

    with patch("bud_runner.runner_manager.asyncio.start_server", side_effect=fake_start_server):
        await manager.run_daemon(port=53035, interval=60)

    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 53035


def test_daemon_cli_accepts_bind_host_option():
    runner = CliRunner()

    with (
        patch("bud_runner.cli.AuthManager") as mock_auth_cls,
        patch("bud_runner.cli.RunnerManager") as mock_manager_cls,
        patch("asyncio.run") as mock_asyncio_run,
    ):
        mock_auth = MagicMock()
        mock_auth.runner_account = "runner-01"
        mock_auth.backend_url = "https://bud.example.com"
        mock_auth.token = "runner-token"
        mock_auth.location = None
        mock_auth_cls.return_value = mock_auth

        mock_manager = MagicMock()
        mock_manager_cls.return_value = mock_manager

        result = runner.invoke(
            app,
            [
                "daemon",
                "--username",
                "runner-01",
                "--bind-host",
                "127.0.0.1",
            ],
        )

    assert result.exit_code == 0
    mock_manager.run_daemon.assert_called_once()
    assert mock_manager.run_daemon.call_args.kwargs["host"] == "127.0.0.1"
    mock_asyncio_run.assert_called_once()


def test_daemon_cli_passes_username_into_auth_manager_for_service_contexts():
    runner = CliRunner()

    with (
        patch("bud_runner.cli.AuthManager") as mock_auth_cls,
        patch("bud_runner.cli.RunnerManager") as mock_manager_cls,
        patch("asyncio.run"),
    ):
        mock_auth = MagicMock()
        mock_auth.runner_account = "service-runner"
        mock_auth.backend_url = "https://bud.example.com"
        mock_auth.token = "runner-token"
        mock_auth_cls.return_value = mock_auth
        mock_manager_cls.return_value = MagicMock()

        result = runner.invoke(
            app,
            [
                "daemon",
                "--username",
                "service-runner",
                "--backend-url",
                "https://bud.example.com",
            ],
        )

    assert result.exit_code == 0
    mock_auth_cls.assert_called_once_with(
        username="service-runner", backend_url="https://bud.example.com"
    )
    assert "Starting Bud Runner Daemon for: service-runner" in result.stdout


def test_daemon_cli_uses_registered_socket_port_when_port_not_provided():
    runner = CliRunner()

    with (
        patch("bud_runner.cli.AuthManager") as mock_auth_cls,
        patch("bud_runner.cli.RunnerManager") as mock_manager_cls,
        patch("asyncio.run"),
    ):
        mock_auth = MagicMock()
        mock_auth.runner_account = "service-runner"
        mock_auth.backend_url = "https://bud.example.com"
        mock_auth.token = "runner-token"
        mock_auth.socket_port = 54001
        mock_auth_cls.return_value = mock_auth

        mock_manager = MagicMock()
        mock_manager_cls.return_value = mock_manager

        result = runner.invoke(
            app,
            [
                "daemon",
                "--username",
                "service-runner",
            ],
        )

    assert result.exit_code == 0
    mock_manager.run_daemon.assert_called_once()
    assert mock_manager.run_daemon.call_args.kwargs["port"] == 54001
    assert "Socket Port: 54001" in result.stdout


def test_daemon_log_formatter_emits_json_lines():
    formatter = DaemonLogFormatter()
    record = logging.LogRecord(
        name="bud_runner.runner_manager",
        level=logging.INFO,
        pathname=__file__,
        lineno=123,
        msg="Heartbeat task started",
        args=(),
        exc_info=None,
    )

    payload = json.loads(formatter.format(record))
    assert payload["level"] == "INFO"
    assert payload["logger"] == "bud_runner.runner_manager"
    assert payload["message"] == "Heartbeat task started"
    assert "timestamp" in payload


def test_daemon_cli_configures_structured_logging():
    runner = CliRunner()

    with (
        patch("bud_runner.cli.AuthManager") as mock_auth_cls,
        patch("bud_runner.cli.RunnerManager") as mock_manager_cls,
        patch("bud_runner.cli._configure_daemon_logging") as mock_configure_logging,
        patch("asyncio.run"),
    ):
        mock_auth = MagicMock()
        mock_auth.runner_account = "runner-01"
        mock_auth.backend_url = "https://bud.example.com"
        mock_auth.token = "runner-token"
        mock_auth.socket_port = 53035
        mock_auth_cls.return_value = mock_auth
        mock_manager_cls.return_value = MagicMock()

        result = runner.invoke(
            app,
            [
                "daemon",
                "--username",
                "runner-01",
            ],
        )

    assert result.exit_code == 0
    mock_configure_logging.assert_called_once()
