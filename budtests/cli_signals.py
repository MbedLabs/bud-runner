"""SIGINT during run-tests, and the daemon: where it listens, which station it runs as, its socket
port and its log lines."""

import json
import signal
import socket
import time

import support
from budtestlibrary import BudTestCase

SLOW_SUITE = '''"""Two classes of three seconds each."""

import time
from pathlib import Path

from budtestlibrary import BudTestCase


class FirstTest(BudTestCase):
    """Marks its start, then takes three seconds."""

    def bud_first(self):
        """Mark and wait."""
        Path("first.started").write_text("1")
        time.sleep(3)
        self.assertTrue(True, msg="first done")


class SecondTest(BudTestCase):
    """Takes three seconds."""

    def bud_second(self):
        """Wait."""
        time.sleep(3)
        self.assertTrue(True, msg="second done")


SLOW = ["demo_slow.FirstTest", "demo_slow.SecondTest"]
'''


def lan_address() -> str:
    """Return this machine's address on its default route (no packet is sent)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect(("192.0.2.1", 9))
        return sock.getsockname()[0]


def ask(host: str, port: int, command: str = "ping") -> str | None:
    """Send a command to a daemon socket and return its answer, or None when the connection is
    refused."""
    try:
        with socket.create_connection((host, port), timeout=5) as sock:
            sock.sendall(command.encode())
            return sock.recv(1024).decode()
    except OSError:
        return None


class CliSignals(BudTestCase):
    """run-tests under SIGINT; the daemon of a registered station against Bud."""

    def setUpClass(self):
        self.bud = support.Bud()
        self.station = self.bud.station("daemon")

    def _daemon(self, case, *args, station=None):
        """Start the daemon for the station in the case and wait until its socket answers."""
        station = station or self.station
        case.give_station(station)
        running = case.start(
            support.PYTHON,
            "-m",
            "bud_runner",
            "daemon",
            "-u",
            station.name,
            "--interval",
            "60",
            *args,
        )
        return running

    def _online(self, name: str) -> bool:
        """Return whether Bud shows the station online."""
        return any(s["account"] == name and s["is_online"] for s in self.bud.stations())

    def bud_run_tests_sigint_finishes_the_current_test_then_force_exits(self):
        """One SIGINT: the running class finishes, the next is not run and the report says so; a
        second SIGINT exits 130."""
        case = support.Case("sigint-once")
        case.write("demo_slow.py", SLOW_SUITE)
        command = "bud-runner run-tests --no-upload after one SIGINT during FirstTest"
        running = case.start(
            support.PYTHON, "-m", "bud_runner", "run-tests", "-t", "demo_slow.SLOW", "--no-upload"
        )
        support.wait_for(lambda: (case.cwd / "first.started").exists(), timeout=30, interval=0.1)
        running.signal(signal.SIGINT)
        code = running.wait(60)
        support.check(
            self,
            code,
            1,
            f"{command} collects the results and exits 1",
            f"{command} exits {code}, not 1: {running.err[-600:]}",
        )
        support.says(self, "Interrupted", running.err, command)
        report = case.junit()
        first = report.find("./testsuite[@name='FirstTest']")
        failures = first.get("failures") if first is not None else "no FirstTest suite"
        support.check(
            self,
            failures,
            "0",
            "FirstTest, running when SIGINT arrived, finishes and passes with 0 failures",
            f"FirstTest, running when SIGINT arrived, shows failures={failures!r} in the report",
        )
        second = [s.get("name") for s in report.findall("./testsuite[@name='SecondTest']")]
        support.check(
            self,
            second,
            [],
            "SecondTest, next after the SIGINT, does not run and is not in the report",
            "SecondTest ran after the SIGINT and is in the report",
        )
        interrupted = [
            (e.get("message") or "").lower()
            for e in report.findall("./testsuite[@name='__suite_interrupted__']/testcase/error")
        ]
        support.says(
            self,
            "interrupted",
            " | ".join(interrupted),
            "the __suite_interrupted__ entry of the JUnit report",
        )

        case = support.Case("sigint-twice")
        case.write("demo_slow.py", SLOW_SUITE)
        command = "bud-runner run-tests --no-upload after two SIGINTs"
        running = case.start(
            support.PYTHON, "-m", "bud_runner", "run-tests", "-t", "demo_slow.SLOW", "--no-upload"
        )
        support.wait_for(lambda: (case.cwd / "first.started").exists(), timeout=30, interval=0.1)
        running.signal(signal.SIGINT)
        time.sleep(0.5)
        running.signal(signal.SIGINT)
        code = running.wait(30)
        running.stop()
        support.check(
            self,
            code,
            130,
            f"{command} force-exits with 130",
            f"{command} exits {code}, not 130",
        )
        support.says(self, "Force exiting", running.err, command)

    def bud_run_daemon_binds_localhost_by_default(self):
        """daemon --port P: P answers on 127.0.0.1 and is refused on the machine's network
        address."""
        port = support.closed_port()
        case = support.Case("daemon-default")
        running = self._daemon(case, "--port", port)
        try:
            answer = support.wait_for(lambda: ask("127.0.0.1", port), timeout=30)
            support.check(
                self,
                answer,
                "PONG",
                f"the daemon started with --port {port} answers PONG on 127.0.0.1",
                f"the daemon started with --port {port} answers {answer!r} on 127.0.0.1",
            )
            remote = ask(lan_address(), port)
            support.check(
                self,
                remote,
                None,
                f"port {port} refuses connections on the machine's network address by default",
                f"port {port} answers {remote!r} on the machine's network address",
            )
            support.says(self, "Bind Host: 127.0.0.1", running.out, "the daemon banner")
        finally:
            running.stop()

    def bud_daemon_cli_accepts_bind_host_option(self):
        """daemon --bind-host <network address>: the socket answers PONG there and not on
        127.0.0.1."""
        port = support.closed_port()
        address = lan_address()
        case = support.Case("daemon-bind-host")
        running = self._daemon(case, "--port", port, "--bind-host", address)
        try:
            answer = support.wait_for(lambda: ask(address, port), timeout=30)
            support.check(
                self,
                answer,
                "PONG",
                "the daemon started with --bind-host <network address> answers PONG there",
                f"the daemon started with --bind-host <network address> answers {answer!r} there",
            )
            local = ask("127.0.0.1", port)
            support.check(
                self,
                local,
                None,
                "with --bind-host <network address> the daemon does not answer on 127.0.0.1",
                f"with --bind-host <network address> the daemon answers {local!r} on 127.0.0.1",
            )
        finally:
            running.stop()

    def bud_daemon_cli_passes_username_into_auth_manager_for_service_contexts(self):
        """With two stations in the vault, daemon -u <second> runs as the second, and Bud shows it
        online."""
        second = self.bud.station("daemon-second")
        case = support.Case("daemon-second")
        case.give_station(self.station)
        running = self._daemon(case, "--port", support.closed_port(), station=second)
        try:
            online = support.wait_for(lambda: self._online(second.name), timeout=30)
            support.says(
                self,
                f"Starting Bud Runner Daemon for: {second.name}",
                running.out,
                f"the daemon started with -u {second.name}",
            )
            support.check(
                self,
                online,
                True,
                f"Bud shows {second.name}, the station given with -u, online",
                f"Bud does not show {second.name} online 30 s after its daemon started",
            )
        finally:
            running.stop()

    def bud_daemon_cli_uses_registered_socket_port_when_port_not_provided(self):
        """A station registered with --socket-port: the daemon listens on that port without
        --port."""
        port = support.closed_port()
        name = self.bud.free_station_name()
        case = support.Case("daemon-registered-port")
        support.pace_registration()
        done = case.bud_runner(
            "register",
            "-u",
            name,
            "-p",
            "station-password-1",
            "-b",
            self.bud.url,
            "--api-key",
            self.bud.mint_key(name),
            "--socket-port",
            port,
            "--no-start",
        )
        support.exits(
            self, done, 0, f"bud-runner register -u {name} --socket-port {port}", stop=True
        )
        running = case.start(
            support.PYTHON, "-m", "bud_runner", "daemon", "-u", name, "--interval", "60"
        )
        try:
            answer = support.wait_for(lambda: ask("127.0.0.1", port), timeout=30)
            support.says(self, f"Socket Port: {port}", running.out, "the daemon banner")
            support.check(
                self,
                answer,
                "PONG",
                f"the daemon without --port answers PONG on the registered socket port {port}",
                f"the daemon without --port answers {answer!r} on the registered port {port}",
            )
        finally:
            running.stop()

    def bud_daemon_cli_configures_structured_logging(self):
        """After the banner, every daemon log line on stdout is JSON with timestamp, level, logger
        and message."""
        port = support.closed_port()
        case = support.Case("daemon-logging")
        running = self._daemon(case, "--port", port)
        try:
            support.wait_for(lambda: ask("127.0.0.1", port), timeout=30)
            ask("127.0.0.1", port, "status")
            time.sleep(1)
        finally:
            running.stop()
        lines = [line for line in running.out.splitlines() if line.strip()]
        banner = [line for line in lines if not line.startswith("{")]
        logged = [json.loads(line) for line in lines if line.startswith("{")]
        plain = [
            line
            for line in banner
            if not line.startswith(("Starting Bud Runner Daemon", "  ", "Stopping daemon"))
        ]
        support.check(
            self,
            plain,
            [],
            "the only plain-text lines on the daemon's stdout are the banner and the stop line",
            f"the daemon's stdout holds plain-text lines outside the banner: {plain}",
        )
        support.need(
            self,
            len(logged) >= 2,
            True,
            f"the daemon logged {len(logged)} JSON lines",
            f"the daemon logged {len(logged)} JSON lines, fewer than the heartbeat start and the "
            "socket command",
        )
        for entry in logged:
            support.check(
                self,
                sorted(entry),
                ["level", "logger", "message", "timestamp"],
                f"the log line {entry['message'][:60]!r} carries timestamp, level, logger and "
                "message",
                f"the log line {entry.get('message', '')[:60]!r} carries the fields "
                f"{sorted(entry)}",
            )
        messages = [entry["message"] for entry in logged]
        support.check_in(
            self,
            "Heartbeat task started (interval=60s)",
            messages,
            "the daemon logs: Heartbeat task started (interval=60s)",
            f"the daemon does not log the heartbeat start; it logs {messages}",
        )
        commands = [
            m for m in messages if m.startswith("Received command from") and m.endswith(": status")
        ]
        support.check(
            self,
            len(commands),
            1,
            "the daemon logs the one status command it received on its socket",
            f"the daemon logs {len(commands)} status commands received on its socket, not one: "
            f"{messages}",
        )
