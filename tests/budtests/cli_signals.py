"""The CLI's interrupt handling in run-tests and the daemon's binding, account, port and logging, with
the executor, reporter, auth manager and runner manager mocked."""

import asyncio
import json
import logging
import signal
from unittest.mock import MagicMock, patch

from budtestlibrary import BudTestCase
from typer.testing import CliRunner

from bud_runner.cli import DaemonLogFormatter, app
from bud_runner.runner_manager import RunnerManager
from tests.budtests.config import CliSignals as c
from tests.budtests.messages import CliSignals as m
from tests.budtests.parameters import CliSignals as p


class CliSignals(BudTestCase):
    """run-tests on SIGINT and the daemon command with mocked collaborators."""

    def auth(self, account: str, **attributes) -> MagicMock:
        """A mocked AuthManager for a station."""
        auth = MagicMock()
        auth.runner_account = account
        auth.backend_url = c.BACKEND_URL
        auth.token = p.TOKEN
        for name, value in attributes.items():
            setattr(auth, name, value)
        return auth

    def bud_a_first_sigint_sets_the_interrupt_and_a_second_forces_the_exit(self):
        """run-tests installs a SIGINT handler; two interrupts end the process with 128 + SIGINT."""
        handlers: dict = {}

        def record(signum, handler):
            """Keep the handler installed for SIGINT or SIGTERM."""
            if signum in (signal.SIGINT, signal.SIGTERM):
                handlers[signum] = handler

        with (
            patch("signal.signal", side_effect=record),
            patch("bud_runner.cli.TestExecutor") as executor,
            patch("bud_runner.cli.JUnitReporter") as reporter,
            patch("os._exit") as exit_now,
        ):
            executor.return_value.run_test_list.return_value = [MagicMock(passed=True, test_class=p.PASSED_CLASS)]
            reporter.return_value.generate.return_value = p.JUNIT
            result = CliRunner().invoke(
                app, ["run-tests", "--test-case-list", c.FIXTURE_LIST, "--no-upload", "--format", "junit"]
            )
            self.assertEqual(result.exit_code, p.PASSED_EXIT, f"run-tests exits 0: {result.output}")
            self.assertIn(member=signal.SIGINT, container=handlers, msg="a SIGINT handler is installed", abort_on_fail=True)
            handlers[signal.SIGINT](signal.SIGINT, None)
            handlers[signal.SIGINT](signal.SIGINT, None)
            self.assertEqual(exit_now.call_count, p.ONE, "the second interrupt forces one exit")
            self.assertEqual(exit_now.call_args.args, (p.INTERRUPT_EXIT,), "the exit code is 128 + SIGINT")

    def bud_run_tests_hands_should_stop_to_the_executor(self):
        """run-tests gives the executor a callable should_stop."""
        captured: dict = {}

        def capture(*args, **kwargs):
            """Keep should_stop and pass."""
            captured["should_stop"] = kwargs.get("should_stop")
            return [MagicMock(passed=True, test_class=p.PASSED_CLASS)]

        with patch("bud_runner.cli.TestExecutor") as executor, patch("bud_runner.cli.JUnitReporter") as reporter:
            executor.return_value.run_test_list.side_effect = capture
            reporter.return_value.generate.return_value = p.JUNIT
            result = CliRunner().invoke(app, ["run-tests", "--test-case-list", c.FIXTURE_LIST, "--no-upload"])
        self.assertEqual(result.exit_code, p.PASSED_EXIT, f"run-tests exits 0: {result.output}")
        self.assertTrue(callable(captured.get("should_stop")), "should_stop is callable")

    def bud_the_daemon_binds_loopback_by_default(self):
        """run_daemon opens its socket on 127.0.0.1 and the given port."""
        manager = RunnerManager(MagicMock(backend_url=c.BACKEND_URL))
        manager._running = False
        captured: dict = {}

        async def start_server(handler, host, port):
            """Record the address and stop the daemon."""
            captured["host"], captured["port"] = host, port
            manager._running = False

            class Server:
                """A server double used as an async context."""

                async def __aenter__(self):
                    return self

                async def __aexit__(self, exc_type, exc, tb):
                    return False

            return Server()

        with patch("bud_runner.runner_manager.asyncio.start_server", side_effect=start_server):
            asyncio.run(manager.run_daemon(port=c.PORT, interval=c.INTERVAL))
        self.assertEqual(captured.get("host"), c.LOOPBACK, "the daemon binds 127.0.0.1")
        self.assertEqual(captured.get("port"), c.PORT, "the daemon binds the given port")

    def bud_the_daemon_command_accepts_a_bind_host(self):
        """daemon --bind-host passes the host to run_daemon."""
        with (
            patch("bud_runner.cli.AuthManager", return_value=self.auth(p.RUNNER, location=None)),
            patch("bud_runner.cli.RunnerManager") as manager_class,
            patch("asyncio.run") as run,
        ):
            result = CliRunner().invoke(app, ["daemon", "--username", p.RUNNER, "--bind-host", c.LOOPBACK])
        manager = manager_class.return_value
        self.assertEqual(result.exit_code, p.PASSED_EXIT, f"daemon exits 0: {result.output}")
        self.assertEqual(manager.run_daemon.call_count, p.ONE, "run_daemon is called once", abort_on_fail=True)
        self.assertEqual(manager.run_daemon.call_args.kwargs.get("host"), c.LOOPBACK, "the bind host is passed")
        self.assertEqual(run.call_count, p.ONE, "the daemon loop is started once")

    def bud_the_daemon_command_passes_the_username_to_the_auth_manager(self):
        """daemon --username builds the AuthManager for that station and names it."""
        with (
            patch("bud_runner.cli.AuthManager", return_value=self.auth(p.SERVICE_RUNNER)) as auth_class,
            patch("bud_runner.cli.RunnerManager"),
            patch("asyncio.run"),
        ):
            result = CliRunner().invoke(
                app, ["daemon", "--username", p.SERVICE_RUNNER, "--backend-url", c.BACKEND_URL]
            )
        self.assertEqual(result.exit_code, p.PASSED_EXIT, f"daemon exits 0: {result.output}")
        self.assertEqual(
            auth_class.call_args.kwargs,
            {"username": p.SERVICE_RUNNER, "backend_url": c.BACKEND_URL},
            "the AuthManager gets the username and backend",
        )
        starting = m.STARTING.format(account=p.SERVICE_RUNNER)
        self.assertIn(member=starting, container=result.stdout, msg=f"the daemon prints {starting!r}")

    def bud_the_daemon_command_uses_the_registered_port_without_a_port_option(self):
        """daemon without --port uses the station's registered socket port."""
        with (
            patch("bud_runner.cli.AuthManager", return_value=self.auth(p.SERVICE_RUNNER, socket_port=p.REGISTERED_PORT)),
            patch("bud_runner.cli.RunnerManager") as manager_class,
            patch("asyncio.run"),
        ):
            result = CliRunner().invoke(app, ["daemon", "--username", p.SERVICE_RUNNER])
        manager = manager_class.return_value
        self.assertEqual(result.exit_code, p.PASSED_EXIT, f"daemon exits 0: {result.output}")
        self.assertEqual(manager.run_daemon.call_args.kwargs.get("port"), p.REGISTERED_PORT, "the registered port is used")
        shown = m.SOCKET_PORT.format(port=p.REGISTERED_PORT)
        self.assertIn(member=shown, container=result.stdout, msg=f"the daemon prints {shown!r}")

    def bud_the_daemon_log_formatter_writes_json_lines(self):
        """DaemonLogFormatter turns a record into JSON with level, logger, message and timestamp."""
        record = logging.LogRecord(
            name=c.LOGGER,
            level=logging.INFO,
            pathname=__file__,
            lineno=p.LOG_LINE,
            msg=p.LOG_MESSAGE,
            args=(),
            exc_info=None,
        )
        payload = json.loads(DaemonLogFormatter().format(record))
        self.assertEqual(payload.get("level"), p.LEVEL, "the level is INFO")
        self.assertEqual(payload.get("logger"), c.LOGGER, "the logger is named")
        self.assertEqual(payload.get("message"), p.LOG_MESSAGE, "the message is kept")
        self.assertIn(member="timestamp", container=payload, msg="the line carries a timestamp")

    def bud_the_daemon_command_configures_structured_logging(self):
        """daemon sets up its JSON logging once."""
        with (
            patch("bud_runner.cli.AuthManager", return_value=self.auth(p.RUNNER, socket_port=c.PORT)),
            patch("bud_runner.cli.RunnerManager"),
            patch("bud_runner.cli._configure_daemon_logging") as configure,
            patch("asyncio.run"),
        ):
            result = CliRunner().invoke(app, ["daemon", "--username", p.RUNNER])
        self.assertEqual(result.exit_code, p.PASSED_EXIT, f"daemon exits 0: {result.output}")
        self.assertEqual(configure.call_count, p.ONE, "the logging is configured once")
