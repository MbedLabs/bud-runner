"""The client's default HTTPS policy and the explicit isolated-network HTTP opt-in, with the HTTP
transport of requests replaced by a recorder that answers 200 and no BUD_ setting set."""

import contextlib
import io
import logging
import os
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests
from budtestlibrary import BudTestCase, parameterized
from typer.testing import CliRunner

from bud_runner import api_client, cli
from bud_runner.api_client import BudAPIClient, InsecureBackendURLError, check_backend_url
from tests.config import BackendUrl as config
from tests.messages import BackendUrl as messages
from tests.parameters import BackendUrl as parameters


class _Warnings(logging.Handler):
    """Keeps the warnings logged while it is attached to the root logger."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record):
        """Keep the message."""
        self.messages.append(record.getMessage())


def _answer(request, **kwargs):
    """A 200 response to request with a version body."""
    response = requests.Response()
    response.status_code = 200
    response._content = b'{"version": "1.2.0"}'
    response.url = request.url
    response.request = request
    return response


class BackendUrl(BudTestCase):
    """Which backend URLs the client and every command accept, refuse or allow with a warning."""

    def folder(self) -> Path:
        """A new folder of this suite."""
        path = Path(os.environ[config.WORK_DIR_SETTING]) / config.FOLDER / uuid.uuid4().hex
        path.mkdir(parents=True)
        return path

    @contextlib.contextmanager
    def transport(self, extra: dict | None = None):
        """A home and working folder of the step's own, no BUD_ setting but the extra ones, the
        transport recorded, and the warnings kept; yield both."""
        home = self.folder()
        env = {k: v for k, v in os.environ.items() if k not in config.BUD_SETTINGS}
        env["HOME"] = str(home)
        env.update(extra or {})
        warnings = _Warnings()
        root = logging.getLogger()
        before = os.getcwd()
        send = Mock(side_effect=_answer)
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(requests.adapters.HTTPAdapter, "send", send),
        ):
            os.chdir(home)
            root.addHandler(warnings)
            try:
                yield send, warnings
            finally:
                root.removeHandler(warnings)
                os.chdir(before)

    def auth(self, url):
        """Station credentials for url."""
        return SimpleNamespace(
            backend_url=url,
            token=config.TOKEN,
            runner_token=config.TOKEN,
            runner_api_key=None,
            runner_account=config.ACCOUNT,
        )

    def unencrypted(self, warnings) -> int:
        """How many unencrypted-HTTP warnings were logged."""
        return sum(messages.UNENCRYPTED in message for message in warnings.messages)

    @parameterized(parameters.ACCEPTED)
    def bud_loopback_http_and_https_urls_are_accepted(self, url):
        """Loopback HTTP and any HTTPS reach /api/health."""
        with self.transport() as (send, _):
            healthy = BudAPIClient(self.auth(url)).health_check()
        self.assertEqual(healthy, True, f"{url} is healthy")
        self.assertEqual(
            send.call_args.args[0].url.lower(),
            f"{url}/api/health".lower(),
            "the health route is called",
        )

    @parameterized(parameters.REFUSED_URLS)
    def bud_plain_http_to_another_host_is_refused_before_any_request(self, url):
        """Plain HTTP to another host is refused, naming the URL and https://, before a session exists."""
        session = Mock()
        message = ""
        with self.transport() as (send, _), patch.object(api_client.requests, "Session", session):
            try:
                BudAPIClient(self.auth(url))
            except InsecureBackendURLError as error:
                message = str(error)
        self.assertIn(member=url, container=message, msg=f"the refusal names {url!r}")
        self.assertIn(
            member=messages.HTTPS_HINT, container=message, msg="the refusal points to https://"
        )
        self.assertEqual(session.call_count, parameters.NONE, "no session is created")
        self.assertEqual(send.call_count, parameters.NONE, "nothing is sent")

    def bud_the_refusal_is_a_value_error(self):
        """check_backend_url refuses with a ValueError."""
        raised = None
        try:
            check_backend_url(config.REFUSED)
        except ValueError as error:
            raised = error
        self.assertTrue(isinstance(raised, ValueError), "the refusal is a ValueError")

    def bud_the_default_backend_url_passes_the_check(self):
        """The default backend URL passes and a client is built for it."""
        from bud_runner.auth import AuthManager

        with self.transport():
            check_backend_url(AuthManager.DEFAULT_BACKEND_URL)
            auth = AuthManager()
            BudAPIClient(AuthManager())
        self.assertEqual(auth.backend_url, config.DEFAULT, "the default is http://localhost:8000")

    @parameterized([(command,) for command in parameters.COMMANDS])
    def bud_every_command_refuses_plain_http_to_another_host(self, command):
        """Every command exits 2 on plain HTTP to another host, before any request or framework start."""
        import behave.__main__
        import pytest
        import robot

        from bud_runner import reporting

        args = [a.format(report=config.CUCUMBER_REPORT) for a in command]
        started = Mock(return_value=0)
        executor = Mock()
        executor.run_test_list.return_value = []
        with (
            self.transport(
                {"BUD_RUNNER_TOKEN": config.TOKEN, "BUD_RUNNER_ACCOUNT": config.ACCOUNT}
            ) as (send, _),
            patch.object(robot, "run_cli", started),
            patch.object(pytest, "main", started),
            patch.object(behave.__main__, "main", started),
            patch.object(reporting, "send_run", started),
            patch.object(cli, "TestExecutor", Mock(return_value=executor)),
        ):
            result = CliRunner().invoke(cli.app, [*args, "--backend-url", config.REFUSED])
        self.assertEqual(
            result.exit_code, parameters.REFUSED_EXIT, f"{args[0]} exits 2: {result.output}"
        )
        refusing = messages.REFUSING.format(url=config.REFUSED)
        self.assertIn(member=refusing, container=result.output, msg=f"{args[0]} says {refusing!r}")
        self.assertIn(
            member=messages.HTTPS_HINT, container=result.output, msg=f"{args[0]} points to https://"
        )
        self.assertEqual(send.call_count, parameters.NONE, f"{args[0]} sends nothing")
        self.assertEqual(started.call_count, parameters.NONE, f"{args[0]} starts no framework")
        if args[0] == "run-tests":
            self.assertEqual(
                executor.run_test_list.call_count,
                parameters.NONE,
                "run-tests refuses the backend before it starts its suite",
            )

    def bud_status_shows_the_refusal_as_the_backend_health(self):
        """status names the URL and shows the refusal as the backend health, sending nothing."""
        with self.transport() as (send, _):
            result = CliRunner().invoke(cli.app, ["status", "--backend-url", config.REFUSED])
        self.assertEqual(result.exit_code, parameters.OK, f"status exits 0: {result.output}")
        for line in (
            messages.BACKEND_LINE.format(url=config.REFUSED),
            messages.HEALTH_REFUSED.format(url=config.REFUSED),
        ):
            self.assertIn(member=line, container=result.output, msg=f"status prints {line!r}")
        self.assertEqual(send.call_count, parameters.NONE, "nothing is sent")

    def bud_status_reaches_a_loopback_backend_over_http(self):
        """status reaches a loopback backend over plain HTTP."""
        with self.transport() as (send, _):
            result = CliRunner().invoke(cli.app, ["status", "--backend-url", config.LOOPBACK])
        self.assertEqual(result.exit_code, parameters.OK, f"status exits 0: {result.output}")
        self.assertIn(
            member=messages.HEALTH_OK, container=result.output, msg="the backend is healthy"
        )
        self.assertEqual(
            send.call_args_list[0].args[0].url,
            f"{config.LOOPBACK}/api/health",
            "the health route is called",
        )

    def bud_the_pytest_plugin_reports_the_refusal_and_keeps_the_exit_code(self):
        """A pytest run with the plugin keeps its exit code and reports the refusal on stderr."""
        folder = self.folder()
        (folder / parameters.PYTEST_FILE).write_text(parameters.PYTEST_BODY, encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k not in config.BUD_SETTINGS}
        env["HOME"] = str(folder)
        done = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "bud_runner.pytest_plugin",
                f"--bud-backend-url={config.REFUSED}",
                parameters.PYTEST_FILE,
            ],
            cwd=folder,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            done.returncode, parameters.OK, f"pytest keeps exit 0: {done.stdout[-300:]}"
        )
        refusal = messages.PYTEST_REFUSAL.format(url=config.REFUSED)
        self.assertIn(member=refusal, container=done.stderr, msg=f"stderr says {refusal!r}")

    def bud_the_robot_listener_reports_the_refusal(self):
        """The Robot listener reports the refusal on stderr and sends nothing."""
        from bud_runner.robot_listener import BudListener

        err = io.StringIO()
        with self.transport() as (send, _), contextlib.redirect_stderr(err):
            BudListener(backend=config.REFUSED).close()
        refusal = messages.ROBOT_REFUSAL.format(url=config.REFUSED)
        self.assertIn(member=refusal, container=err.getvalue(), msg=f"stderr says {refusal!r}")
        self.assertEqual(send.call_count, parameters.NONE, "nothing is sent")

    @parameterized(parameters.OPT_IN_URLS)
    def bud_explicit_environment_opt_in_allows_remote_http_with_a_warning(self, url):
        """BUD_ALLOW_HTTP=1 allows remote HTTP and warns about unencrypted credentials."""
        with self.transport({config.ALLOW: parameters.ON}) as (send, warnings):
            healthy = BudAPIClient(self.auth(url)).health_check()
        self.assertEqual(healthy, True, f"{url} is healthy")
        self.assertEqual(
            send.call_args.args[0].url, f"{url}/api/health", "the health route is called"
        )
        self.assertTrue(self.unencrypted(warnings) > 0, "an unencrypted-HTTP warning is logged")
        self.assertTrue(
            any(messages.CREDENTIALS in message.lower() for message in warnings.messages),
            "the warning mentions credentials",
        )

    @parameterized(parameters.OTHER_VALUES)
    def bud_other_environment_values_do_not_enable_remote_http(self, value):
        """Only BUD_ALLOW_HTTP=1 opts in."""
        refused = False
        with self.transport({config.ALLOW: value}) as (send, _):
            try:
                BudAPIClient(self.auth(config.REFUSED))
            except InsecureBackendURLError:
                refused = True
        self.assertTrue(refused, f"BUD_ALLOW_HTTP={value!r} still refuses")
        self.assertEqual(send.call_count, parameters.NONE, "nothing is sent")

    @parameterized(parameters.UNREADABLE)
    def bud_the_http_override_does_not_accept_an_unreadable_host(self, url):
        """The opt-in still refuses a URL without a readable host."""
        refused = False
        with self.transport({config.ALLOW: parameters.ON}) as (send, _):
            try:
                BudAPIClient(self.auth(url))
            except InsecureBackendURLError:
                refused = True
        self.assertTrue(refused, f"{url!r} is refused")
        self.assertEqual(send.call_count, parameters.NONE, "nothing is sent")

    @parameterized(parameters.NOT_WEAKENED)
    def bud_the_override_does_not_warn_when_http_is_not_weakened(self, url):
        """HTTPS and loopback HTTP under the opt-in log no unencrypted-HTTP warning."""
        with self.transport({config.ALLOW: parameters.ON}) as (_, warnings):
            healthy = BudAPIClient(self.auth(url)).health_check()
        self.assertEqual(healthy, True, f"{url} is healthy")
        self.assertEqual(self.unencrypted(warnings), parameters.NONE, "no unencrypted-HTTP warning")

    def bud_each_remote_http_client_warns_without_disclosing_url_credentials(self):
        """Each client warns once, without the URL's password or token."""
        with self.transport({config.ALLOW: parameters.ON}) as (_, warnings):
            for _ in range(parameters.TWO):
                BudAPIClient(self.auth(parameters.SECRET_URL))
        found = [message for message in warnings.messages if messages.UNENCRYPTED in message]
        self.assertEqual(len(found), parameters.TWO, "two clients warn twice")
        for secret in parameters.SECRETS:
            self.assertTrue(
                all(secret not in message for message in found), f"{secret!r} is not disclosed"
            )

    def bud_https_certificate_failures_do_not_downgrade_with_the_override(self):
        """A certificate failure stays a failure: one verified HTTPS try and no warning."""
        with self.transport({config.ALLOW: parameters.ON}) as (send, warnings):
            send.side_effect = requests.exceptions.SSLError(messages.CERTIFICATE)
            healthy = BudAPIClient(self.auth(config.HTTPS)).health_check()
        self.assertEqual(healthy, False, "the backend is unhealthy")
        self.assertEqual(send.call_count, parameters.ONE, "one try is made")
        self.assertEqual(
            send.call_args.args[0].url, f"{config.HTTPS}/api/health", "the try is HTTPS"
        )
        self.assertEqual(send.call_args.kwargs.get("verify"), True, "the certificate is verified")
        self.assertEqual(self.unencrypted(warnings), parameters.NONE, "no unencrypted-HTTP warning")

    def bud_the_private_ca_bundle_is_preserved_with_the_override(self):
        """A private CA bundle stays the verification under the opt-in."""
        bundle = str(self.folder() / parameters.BUNDLE)
        with self.transport({config.ALLOW: parameters.ON, config.CA_BUNDLE: bundle}) as (send, _):
            healthy = BudAPIClient(self.auth(config.HTTPS)).health_check()
        self.assertEqual(healthy, True, "the backend is healthy")
        self.assertEqual(send.call_args.kwargs.get("verify"), bundle, "the private bundle verifies")

    @parameterized(parameters.PREVIOUS)
    def bud_the_global_flag_allows_http_only_for_its_invocation(self, previous):
        """--allow-http allows remote HTTP for its command and leaves BUD_ALLOW_HTTP as it was."""
        extra = {} if previous is None else {config.ALLOW: previous}
        with self.transport(extra) as (_, warnings):
            result = CliRunner().invoke(
                cli.app, ["--allow-http", "status", "--backend-url", config.REFUSED]
            )
            after = os.environ.get(config.ALLOW)
        self.assertEqual(result.exit_code, parameters.OK, f"status exits 0: {result.output}")
        self.assertIn(
            member=messages.HEALTH_OK, container=result.output, msg="the backend is healthy"
        )
        self.assertTrue(self.unencrypted(warnings) > 0, "an unencrypted-HTTP warning is logged")
        self.assertEqual(after, previous, f"BUD_ALLOW_HTTP is back to {previous!r}")

    def bud_the_global_flag_restores_the_environment_after_a_command_failure(self):
        """A failing command under --allow-http still leaves BUD_ALLOW_HTTP unset."""

        def fail(*args):
            """Fail the status lookup."""
            raise RuntimeError(messages.COMMAND_FAILED)

        with self.transport(), patch.object(cli, "_load_backend_status", fail):
            result = CliRunner().invoke(
                cli.app, ["--allow-http", "status", "--backend-url", config.REFUSED]
            )
            after = os.environ.get(config.ALLOW)
        self.assertTrue(isinstance(result.exception, RuntimeError), "the command fails")
        self.assertEqual(after, None, "BUD_ALLOW_HTTP is unset again")

    def bud_environment_opt_in_warns_on_each_command_start(self):
        """With BUD_ALLOW_HTTP=1 every command start warns."""
        results = []
        with self.transport({config.ALLOW: parameters.ON}) as (_, warnings):
            for _ in range(parameters.TWO):
                results.append(
                    CliRunner().invoke(cli.app, ["status", "--backend-url", config.REFUSED])
                )
        for result in results:
            self.assertEqual(result.exit_code, parameters.OK, f"status exits 0: {result.output}")
            self.assertIn(
                member=messages.HEALTH_OK, container=result.output, msg="the backend is healthy"
            )
        self.assertEqual(self.unencrypted(warnings), parameters.TWO, "each start warns")

    def bud_registration_passes_the_explicit_override_to_its_background_daemon(self):
        """register --allow-http starts the daemon with BUD_ALLOW_HTTP=1 and leaves the environment unset."""
        spawn = Mock(return_value=SimpleNamespace(pid=parameters.PID))
        with self.transport(), patch.object(cli.subprocess, "Popen", spawn):
            result = CliRunner().invoke(cli.app, parameters.REGISTER)
            after = os.environ.get(config.ALLOW)
        self.assertEqual(result.exit_code, parameters.OK, f"register exits 0: {result.output}")
        self.assertEqual(
            spawn.call_count, parameters.ONE, "one daemon is started", abort_on_fail=True
        )
        self.assertIn(
            member="daemon", container=spawn.call_args.args[0], msg="the child is the daemon"
        )
        self.assertEqual(
            spawn.call_args.kwargs["env"].get(config.ALLOW),
            parameters.ON,
            "the daemon gets BUD_ALLOW_HTTP=1",
        )
        self.assertEqual(after, None, "BUD_ALLOW_HTTP is unset again")

    def bud_direct_framework_reporting_uses_the_environment_opt_in(self):
        """send_run honours BUD_ALLOW_HTTP=1, uploads once and warns."""
        from bud_runner.reporting import send_run

        extra = {
            config.ALLOW: parameters.ON,
            "BUD_RUNNER_ACCOUNT": config.ACCOUNT,
            "BUD_RUNNER_TOKEN": config.TOKEN,
        }
        with self.transport(extra) as (send, warnings):
            uploaded = send_run(
                lambda account, product: {"results": []}, framework="Robot", backend=config.REFUSED
            )
        self.assertEqual(uploaded, True, "the run is uploaded")
        self.assertEqual(send.call_count, parameters.ONE, "one request is sent")
        self.assertTrue(self.unencrypted(warnings) > 0, "an unencrypted-HTTP warning is logged")
