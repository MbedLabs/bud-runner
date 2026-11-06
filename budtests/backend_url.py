"""The client's default HTTPS policy and the explicit HTTP opt-in for an isolated network.

0.0.0.0 stands in for another host: bud-runner treats it as not this machine, and it still
reaches the throwaway Bud on loopback: nothing is exposed beyond this machine.
"""

import os
import time

import support
from budtestlibrary import BudTestCase, parameterized

from bud_runner import cli
from bud_runner.api_client import BudAPIClient, check_backend_url
from bud_runner.auth import AuthManager

REFUSED = "http://bud.example.com"
WARNING = "Unencrypted HTTP is enabled for the Bud backend"
ACCEPTED = [
    "http://localhost:8001",
    "http://127.0.0.1:8001",
    "http://[::1]:8001",
    "https://bud.example.com",
    "http://localhost:8000",
    "http://LocalHost:8001",
    "HTTP://127.0.0.1:8001",
    "http://127.255.255.254",
    "https://192.168.1.10:8001",
]
REFUSED_URLS = [
    "http://bud.example.com",
    "http://192.168.1.10:8001",
    "http://10.0.0.5",
    "http://BUD.EXAMPLE.COM",
    "HTTP://bud.example.com",
    " http://bud.example.com",
    "http://[fe80::1]:8001",
    "http://[::ffff:127.0.0.1]:8001",
    "http://0.0.0.0:8001",
    "http://localhost.example.com",
    "http://127.0.0.1.example.com",
    "http://[::1",
    "http://",
]
FRAMEWORK_TEST = {
    "run-robot": (
        "bench.robot",
        "*** Test Cases ***\nMarker\n    Create File    ran.marker    ran\n\n"
        "*** Settings ***\nLibrary    OperatingSystem\n",
    ),
    "run-pytest": (
        "test_marker.py",
        "from pathlib import Path\n\n\n"
        "def test_marker():\n    Path('ran.marker').write_text('ran')\n",
    ),
    "run-behave": (
        "features/marker.feature",
        "Feature: Marker\n  Scenario: Mark\n    Given a marker\n",
    ),
}
BEHAVE_STEPS = (
    "from pathlib import Path\n\nfrom behave import given\n\n\n@given('a marker')\n"
    "def step_marker(context):\n    Path('ran.marker').write_text('ran')\n"
)


def _auth(url: str) -> AuthManager:
    """Return station credentials for url, read in an empty HOME."""
    case = support.Case("auth")
    with support.Isolated(case):
        return AuthManager(
            backend_url=url, runner_token="station-session", runner_account="station-01"
        )


def _checked(url: str) -> BaseException | None:
    """Run check_backend_url on url and return what it raised, or None."""
    try:
        check_backend_url(url)
    except Exception as exc:
        return exc
    return None


class BackendUrl(BudTestCase):
    """Which backend URLs are accepted, refused or opted into, by the client, every command and the
    framework adapters."""

    def setUpClass(self):
        self.bud = support.Bud()
        self.station = self.bud.station("main")

    def accepted(self, url: str, condition: str) -> None:
        """Record that check_backend_url accepts url under a condition."""
        raised = _checked(url)
        support.check(
            self,
            support.raised_name(raised),
            "nothing raised",
            f"check_backend_url accepts {url!r} {condition}",
            f"check_backend_url refuses {url!r} {condition}: {raised}",
        )

    def refused(self, url: str, condition: str) -> None:
        """Record that check_backend_url refuses url under a condition."""
        raised = _checked(url)
        support.check(
            self,
            support.raised_name(raised),
            "InsecureBackendURLError",
            f"check_backend_url refuses {url!r} {condition} with InsecureBackendURLError",
            f"check_backend_url answers {url!r} {condition} with {support.raised_name(raised)}",
        )

    def reaches_bud(self, done, command: str) -> None:
        """Record that a status command reached Bud's health check."""
        support.says(self, "Backend Health: ✓ OK", done.out, command)

    @parameterized(ACCEPTED)
    def bud_loopback_http_and_https_urls_are_accepted(self, url):
        """HTTPS anywhere and HTTP to a loopback name or address pass the check."""
        self.accepted(url, "without any opt-in")

    def bud_status_reaches_a_loopback_backend_over_http(self):
        """status over plain HTTP to 127.0.0.1 reaches Bud."""
        command = "bud-runner status --backend-url http://127.0.0.1:<port>"
        done = support.Case("status-loopback").bud_runner("status", "--backend-url", self.bud.url)
        support.exits(self, done, 0, command)
        self.reaches_bud(done, command)
        support.check_not_in(
            self,
            WARNING,
            done.err,
            f"{command} gives no plain-HTTP warning for loopback",
            f"{command} warns about plain HTTP to loopback",
        )

    @parameterized(REFUSED_URLS)
    def bud_plain_http_to_another_host_is_refused_before_any_request(self, url):
        """HTTP to another host, or an HTTP URL with no readable host, is refused with the URL and
        an https hint."""
        raised = None
        with support.Isolated(support.Case("refused")):
            try:
                BudAPIClient(AuthManager(backend_url=url))
            except Exception as exc:
                raised = exc
        support.need(
            self,
            support.raised_name(raised),
            "InsecureBackendURLError",
            f"BudAPIClient for {url!r} is refused with InsecureBackendURLError",
            f"BudAPIClient for {url!r} ends with {support.raised_name(raised)}",
        )
        message = str(raised)
        support.says(self, url, message, f"the refusal of {url!r}")
        support.says(self, "https://", message, f"the refusal of {url!r}")

    def bud_the_refusal_is_a_value_error(self):
        """The refusal is a ValueError."""
        raised = _checked(REFUSED)
        kinds = [kind.__name__ for kind in type(raised).__mro__] if raised else []
        support.check_in(
            self,
            "ValueError",
            kinds,
            f"check_backend_url refuses {REFUSED} with {support.raised_name(raised)}, a ValueError",
            f"check_backend_url answers {REFUSED} with {support.raised_name(raised)}, not a "
            "ValueError",
        )

    def bud_the_default_backend_url_passes_the_check(self):
        """The default backend URL is http://localhost:8000 and a client is built for it."""
        raised = None
        with support.Isolated(support.Case("default")):
            auth = AuthManager()
            try:
                BudAPIClient(auth)
            except Exception as exc:
                raised = exc
        support.check(
            self,
            auth.backend_url,
            "http://localhost:8000",
            "the default backend URL is http://localhost:8000",
            f"the default backend URL is {auth.backend_url!r}, not http://localhost:8000",
        )
        support.check(
            self,
            support.raised_name(raised),
            "nothing raised",
            "BudAPIClient is built for the default backend URL",
            f"BudAPIClient for the default backend URL fails with {raised!r}",
        )

    @parameterized(
        [
            (
                "add-test-run",
                "-t",
                "demo_marker.MARKER_LIST",
                "-n",
                "Nightly",
                "--bud-token",
                "user-token",
            ),
            ("run-tests", "-t", "demo_marker.MARKER_LIST", "--format", "text"),
            ("claim-run",),
            ("register", "--username", "station-01", "--api-key", "enrolment-key", "--no-start"),
            ("daemon", "--username", "station-01"),
            ("run-robot", "bench.robot"),
            ("run-pytest", "test_marker.py"),
            ("run-behave", "features"),
            ("import-cucumber", "--report", "cucumber-js.json"),
        ]
    )
    def bud_every_command_refuses_plain_http_to_another_host(self, *args):
        """Each command exits 2 with the refusal; a framework does not run, run-tests runs its suite
        before the upload is refused."""
        case = support.Case(f"refuse-{args[0]}")
        support.marker_suite(case)
        support.copy_fixture(case, "cucumber-js.json")
        if args[0] in FRAMEWORK_TEST:
            case.write(*FRAMEWORK_TEST[args[0]])
            case.write("features/steps/marker_steps.py", BEHAVE_STEPS)
        command = f"bud-runner {args[0]} --backend-url {REFUSED}"
        done = case.bud_runner(
            *args,
            "--backend-url",
            REFUSED,
            env={"BUD_RUNNER_TOKEN": "station-session", "BUD_RUNNER_ACCOUNT": "station-01"},
        )
        support.exits(self, done, 2, command)
        output = done.out + done.err
        support.says(self, f"Refusing plain HTTP to {REFUSED}", output, command)
        support.says(self, "https://", output, command)
        ran = (case.cwd / "ran.marker").exists()
        if args[0] == "run-tests":
            support.check(
                self,
                ran,
                True,
                f"{command} runs its suite before the upload is refused: ran.marker exists",
                f"{command} did not run its suite before the upload was refused",
            )
        else:
            support.check(
                self,
                ran,
                False,
                f"{command} runs no test before the refusal: no ran.marker",
                f"{command} ran a test although the backend URL is refused",
            )

    def bud_status_shows_the_refusal_as_the_backend_health(self):
        """status prints the URL and the refusal as the backend health, and exits 0."""
        command = f"bud-runner status --backend-url {REFUSED}"
        done = support.Case("status-refused").bud_runner("status", "--backend-url", REFUSED)
        support.exits(self, done, 0, command)
        support.says(self, f"Backend URL: {REFUSED}", done.out, command)
        support.says(
            self, f"Backend Health: ✗ error: Refusing plain HTTP to {REFUSED}", done.out, command
        )

    def bud_the_pytest_plugin_reports_the_refusal_and_keeps_the_exit_code(self):
        """pytest with the plugin and a refused URL: exit 0 of the passing test and the refusal on
        stderr."""
        case = support.Case("pytest-refused")
        case.write("test_one.py", "def test_one():\n    assert 1 == 1\n")
        command = (
            f"pytest -p bud_runner.pytest_plugin --bud-backend-url={REFUSED} on a passing test"
        )
        done = case.command(
            support.PYTHON,
            "-m",
            "pytest",
            "-p",
            "bud_runner.pytest_plugin",
            f"--bud-backend-url={REFUSED}",
            "test_one.py",
        )
        support.exits(self, done, 0, f"{command}, keeping pytest's own exit code,")
        support.says(
            self,
            f"Could not report the pytest run to Bud: Refusing plain HTTP to {REFUSED}",
            done.err,
            command,
        )

    def bud_the_robot_listener_reports_the_refusal(self):
        """robot with the listener and a refused URL: the refusal on stderr, Robot's exit code
        kept."""
        case = support.Case("robot-refused")
        case.write("bench.robot", "*** Test Cases ***\nPasses\n    Log    ok\n")
        command = f"robot --listener BudListener;backend={REFUSED} on a passing test"
        done = case.command(
            support.PYTHON,
            "-m",
            "robot",
            "--listener",
            f"bud_runner.robot_listener.BudListener;backend={REFUSED}",
            "--output",
            "NONE",
            "--report",
            "NONE",
            "--log",
            "NONE",
            "bench.robot",
        )
        support.exits(self, done, 0, f"{command}, keeping Robot's own exit code,")
        support.says(
            self,
            f"Could not report the Robot run to Bud: Refusing plain HTTP to {REFUSED}",
            done.err,
            command,
        )

    def bud_explicit_environment_opt_in_allows_remote_http_with_a_warning(self):
        """BUD_ALLOW_HTTP=1: status reaches Bud at another address and warns on stderr that
        credentials go without TLS."""
        command = "bud-runner status --backend-url http://0.0.0.0:<port> with BUD_ALLOW_HTTP=1"
        done = support.Case("opt-in").bud_runner(
            "status", "--backend-url", support.remote_url(), env={"BUD_ALLOW_HTTP": "1"}
        )
        self.reaches_bud(done, command)
        support.says(self, WARNING, done.err, command)
        support.says(self, "credentials", done.err.lower(), f"the plain-HTTP warning of {command}")
        for url in (REFUSED, "http://192.168.1.10:8001", "http://bud:8000"):
            with support.Isolated(support.Case("opt-in-url"), {"BUD_ALLOW_HTTP": "1"}):
                self.accepted(url, "with BUD_ALLOW_HTTP=1")

    @parameterized(["0", "true", "yes", "false", "2", ""])
    def bud_other_environment_values_do_not_enable_remote_http(self, value):
        """Any BUD_ALLOW_HTTP value but 1 keeps the refusal."""
        with support.Isolated(support.Case("other-value"), {"BUD_ALLOW_HTTP": value}):
            self.refused(REFUSED, f"with BUD_ALLOW_HTTP={value!r}")

    @parameterized(["http://", "http://[::1"])
    def bud_the_http_override_does_not_accept_an_unreadable_host(self, url):
        """The opt-in does not accept an HTTP URL without a readable host."""
        with support.Isolated(support.Case("unreadable"), {"BUD_ALLOW_HTTP": "1"}):
            self.refused(url, "with BUD_ALLOW_HTTP=1, having no readable host,")

    def bud_the_override_does_not_warn_when_http_is_not_weakened(self):
        """With the opt-in, loopback HTTP to Bud and an HTTPS URL give no warning."""
        command = "bud-runner status --backend-url http://127.0.0.1:<port> with BUD_ALLOW_HTTP=1"
        done = support.Case("no-warning").bud_runner(
            "status", "--backend-url", self.bud.url, env={"BUD_ALLOW_HTTP": "1"}
        )
        self.reaches_bud(done, command)
        support.check_not_in(
            self,
            WARNING,
            done.err,
            f"{command} gives no plain-HTTP warning for loopback",
            f"{command} warns about plain HTTP to loopback",
        )
        with (
            support.Isolated(support.Case("https"), {"BUD_ALLOW_HTTP": "1"}),
            support.Warnings() as warnings,
        ):
            check_backend_url("https://bud.example.com")
        support.check(
            self,
            warnings.messages,
            [],
            "check_backend_url with BUD_ALLOW_HTTP=1 logs no warning for https://bud.example.com",
            f"check_backend_url logs {warnings.messages} for https://bud.example.com",
        )

    def bud_each_remote_http_client_warns_without_disclosing_url_credentials(self):
        """Two clients for an HTTP URL with userinfo and query give two warnings that name
        neither."""
        with (
            support.Isolated(support.Case("userinfo"), {"BUD_ALLOW_HTTP": "1"}),
            support.Warnings() as warnings,
        ):
            for _ in range(2):
                BudAPIClient(
                    AuthManager(backend_url="http://user:password@bud.example.com?token=private")
                )
        messages = [m for m in warnings.messages if WARNING in m]
        support.check(
            self,
            len(messages),
            2,
            "two clients for a plain-HTTP URL with BUD_ALLOW_HTTP=1 log one warning each",
            f"two clients for a plain-HTTP URL log {len(messages)} plain-HTTP warnings, not 2",
        )
        leaked = [m for m in messages if "password" in m or "private" in m]
        support.check(
            self,
            leaked,
            [],
            "no warning names the password or the token query of the URL",
            f"warnings name the URL's password or token: {leaked}",
        )

    def bud_https_certificate_failures_do_not_downgrade_with_the_override(self):
        """With the opt-in, a certificate for another name fails the health check over HTTPS,
        without a plain-HTTP warning."""
        case = support.Case("tls-mismatch")
        server = support.TlsServer(case, "DNS:bud.example.com")
        try:
            with (
                support.Isolated(
                    case, {"BUD_ALLOW_HTTP": "1", "REQUESTS_CA_BUNDLE": str(server.ca)}
                ),
                support.Warnings() as warnings,
            ):
                healthy = BudAPIClient(AuthManager(backend_url=server.url)).health_check()
        finally:
            server.close()
        support.check(
            self,
            healthy,
            False,
            "the health check fails against an HTTPS server whose certificate names another host",
            "the health check passes against an HTTPS server whose certificate names another host",
        )
        support.check(
            self,
            server.requests,
            [],
            "no request gets past the failed TLS handshake",
            f"requests got past the failed TLS handshake: {server.requests}",
        )
        plain = [m for m in warnings.messages if WARNING in m]
        support.check(
            self,
            plain,
            [],
            "the certificate failure gives no plain-HTTP warning: HTTPS is not downgraded",
            f"the certificate failure gives plain-HTTP warnings: {plain}",
        )

    def bud_the_private_ca_bundle_is_preserved_with_the_override(self):
        """With the opt-in, a server signed by the CA in REQUESTS_CA_BUNDLE passes the health
        check."""
        case = support.Case("tls-private-ca")
        server = support.TlsServer(case, "IP:127.0.0.1")
        try:
            with support.Isolated(
                case, {"BUD_ALLOW_HTTP": "1", "REQUESTS_CA_BUNDLE": str(server.ca)}
            ):
                healthy = BudAPIClient(AuthManager(backend_url=server.url)).health_check()
        finally:
            server.close()
        support.check(
            self,
            healthy,
            True,
            "the health check passes against a server signed by the CA in REQUESTS_CA_BUNDLE",
            "the health check fails against a server signed by the CA in REQUESTS_CA_BUNDLE",
        )
        support.check(
            self,
            server.requests,
            ["/api/health"],
            "the health check reaches /api/health on the private-CA server",
            f"the private-CA server received {server.requests}, not ['/api/health']",
        )

    @parameterized([None, "0", "1"])
    def bud_the_global_flag_allows_http_only_for_its_invocation(self, previous):
        """--allow-http lets status reach Bud at another address with the warning, whatever
        BUD_ALLOW_HTTP held."""
        command = (
            f"bud-runner --allow-http status --backend-url http://0.0.0.0:<port> with "
            f"BUD_ALLOW_HTTP={previous!r}"
        )
        done = support.Case("allow-http").bud_runner(
            "--allow-http",
            "status",
            "--backend-url",
            support.remote_url(),
            env={"BUD_ALLOW_HTTP": previous},
        )
        self.reaches_bud(done, command)
        support.says(self, WARNING, done.err, command)

    @parameterized([None, "0"])
    def bud_the_global_flag_restores_the_environment_after_a_command_failure(self, previous):
        """In one process, --allow-http is undone after the command fails (a HOME whose .bud is a
        file)."""
        case = support.Case("restore")
        (case.home / ".bud").write_text("not a directory")
        env = {} if previous is None else {"BUD_ALLOW_HTTP": previous}
        failure = None
        with support.Isolated(case, env):
            try:
                cli.app(["--allow-http", "status", "--backend-url", REFUSED], standalone_mode=False)
            except Exception as exc:
                failure = exc
            after = os.environ.get("BUD_ALLOW_HTTP")
        support.need(
            self,
            failure is None,
            False,
            "--allow-http status fails in a HOME whose .bud is a file "
            f"({support.raised_name(failure)})",
            "--allow-http status succeeds in a HOME whose .bud is a file, so no failure is tested",
        )
        support.check(
            self,
            after,
            previous,
            f"after the failed --allow-http command BUD_ALLOW_HTTP is back to {previous!r}",
            f"after the failed --allow-http command BUD_ALLOW_HTTP is {after!r}, not {previous!r}",
        )

    def bud_environment_opt_in_warns_on_each_command_start(self):
        """With BUD_ALLOW_HTTP=1 each status run warns."""
        for attempt in (1, 2):
            command = f"status run {attempt} with BUD_ALLOW_HTTP=1 to http://0.0.0.0:<port>"
            done = support.Case("each-start").bud_runner(
                "status", "--backend-url", support.remote_url(), env={"BUD_ALLOW_HTTP": "1"}
            )
            self.reaches_bud(done, command)
            count = done.err.count(WARNING)
            support.check(
                self,
                count,
                1,
                f"{command} prints the plain-HTTP warning once",
                f"{command} prints the plain-HTTP warning {count} times",
            )

    def bud_registration_passes_the_explicit_override_to_its_background_daemon(self):
        """--allow-http register starts the daemon, which heartbeats Bud at another address: the
        station is online."""
        case = support.Case("register-daemon")
        name = self.bud.free_station_name()
        support.pace_registration()
        command = f"bud-runner --allow-http register --username {name} at http://0.0.0.0:<port>"
        done = case.bud_runner(
            "--allow-http",
            "register",
            "--username",
            name,
            "--password",
            "station-password-1",
            "--api-key",
            self.bud.mint_key(name),
            "--backend-url",
            support.remote_url(),
        )
        pid_file = case.home / ".bud" / "daemons" / f"bud_{name}.pid"
        try:
            support.exits(self, done, 0, command)
            support.need(
                self,
                pid_file.is_file(),
                True,
                f"{command} starts the background daemon: its PID file exists",
                f"{command} started no background daemon: no PID file",
            )
            online = support.wait_for(
                lambda: any(s["account"] == name and s["is_online"] for s in self.bud.stations()),
                timeout=30,
            )
            support.check(
                self,
                online,
                True,
                f"Bud shows {name} online: the daemon heartbeats Bud over the opted-in plain HTTP",
                f"Bud does not show {name} online 30 s after registration",
            )
            log = (case.home / ".bud" / "daemons" / f"bud_{name}.log").read_text(encoding="utf-8")
            support.check_not_in(
                self,
                "Refusing plain HTTP",
                log,
                "the background daemon does not refuse the opted-in URL",
                "the background daemon refuses the plain-HTTP URL despite --allow-http",
            )
        finally:
            if pid_file.is_file():
                try:
                    os.kill(int(pid_file.read_text()), 15)
                except ProcessLookupError:
                    pass
                time.sleep(1)

    def bud_direct_framework_reporting_uses_the_environment_opt_in(self):
        """send_run with BUD_ALLOW_HTTP=1 reaches Bud at another address with the warning, and Bud
        holds the results."""
        from bud_runner.reporting import send_run

        row = {
            "test_class": "OptInTest",
            "test_method": "check",
            "passed": True,
            "duration_seconds": 0.1,
        }
        before = self.bud.run_ids()
        with (
            support.Isolated(
                support.Case("send-run"),
                {
                    "BUD_ALLOW_HTTP": "1",
                    "BUD_RUNNER_ACCOUNT": self.station.name,
                    "BUD_RUNNER_TOKEN": self.station.token,
                },
            ),
            support.Warnings() as warnings,
        ):
            uploaded = send_run(
                lambda account, product: {
                    "results": [row],
                    "runner_account": account,
                    "test_suite_name": "Opt-in",
                },
                framework="Robot",
                backend=support.remote_url(),
            )
        support.check(
            self,
            uploaded,
            True,
            "send_run with BUD_ALLOW_HTTP=1 reports the upload to http://0.0.0.0:<port>",
            "send_run with BUD_ALLOW_HTTP=1 reports no upload to http://0.0.0.0:<port>",
        )
        support.says(self, WARNING, " | ".join(warnings.messages), "the warnings send_run logs")
        new = self.bud.new_run_ids(before)
        support.need(
            self,
            len(new),
            1,
            "Bud holds one new run from send_run",
            f"Bud holds {len(new)} new runs after send_run, not one",
        )
        classes = [r["test_class"] for r in self.bud.results(new[0])]
        support.check(
            self,
            classes,
            ["OptInTest"],
            "Bud holds the OptInTest result send_run sent",
            f"Bud holds the results {classes}, not ['OptInTest']",
        )
