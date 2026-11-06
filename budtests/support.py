"""Shared steps of the bud-runner suites.

The suites drive bud-runner the way its users do: ``python -m bud_runner`` as a child
process, the framework command lines that load its plugins, and its public modules
imported in the suite. Each case gets its own HOME, working directory and temporary
directory, and a child sees no BUD_* variable unless the case sets it. Commands that talk
to Bud reach a throwaway Bud instance; a recording proxy stands in front of it where a case
needs Bud to drop out, and an HTTP double answers only where a case needs an answer a real
Bud never gives.

Settings come from the environment: BUD_URL (base URL of the throwaway Bud), ADMIN_EMAIL
and ADMIN_PASSWORD (its seeded administrator), BUD_MAX_UPLOAD_BYTES (the upload size limit
the instance runs with) and optionally BUDTEST_WORK_DIR (where the cases' files go). Only
local addresses are accepted for BUD_URL.
"""

import http.client
import http.server
import json
import logging
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

import budtestlibrary
import requests

SUITES = Path(__file__).resolve().parent
REPO = SUITES.parent
FIXTURES = SUITES / "fixtures"
LIBRARY_PATH = str(Path(budtestlibrary.__file__).resolve().parent.parent)
PYTHON = sys.executable
_REGISTRATIONS: list[float] = []
_STATIONS: dict[str, "Station"] = {}


def _same(actual, expected) -> bool:
    """Whether actual equals expected; None and booleans must be the same object."""
    if expected is None or isinstance(expected, bool):
        return actual is expected
    return not isinstance(actual, bool) and actual == expected


def check(case, actual, expected, passed: str, failed: str = "", stop: bool = False) -> bool:
    """Compare actual with expected first, then record one entry whose message says what happened.

    passed is the message when the values match and failed the message when they differ.
    The entry carries repr() of both values: Bud shows the real values whatever their
    type. With stop, a mismatch also ends the step (an AssertRequire entry).
    """
    same = _same(actual, expected)
    return case.assertTrue(
        same,
        msg=passed if same else failed or passed,
        expected=repr(expected),
        actual=repr(actual),
        abort_on_fail=stop,
        assertion_type="AssertRequire" if stop else "AssertEqual",
    )


def need(case, actual, expected, passed: str, failed: str = "") -> bool:
    """check() whose mismatch ends the step: for what the rest of the step depends on."""
    return check(case, actual, expected, passed, failed, stop=True)


def check_in(case, member, container, passed: str, failed: str = "") -> bool:
    """Look for member in container first, then record one entry saying what happened."""
    found = member in container
    return case.assertTrue(
        found,
        msg=passed if found else failed or passed,
        expected=f"contains {member!r}",
        actual=repr(container),
        assertion_type="AssertIn",
    )


def check_not_in(case, member, container, passed: str, failed: str = "") -> bool:
    """Look for member in container first, then record one entry saying what happened."""
    found = member in container
    return case.assertTrue(
        not found,
        msg=failed or passed if found else passed,
        expected=f"does not contain {member!r}",
        actual=repr(container),
        assertion_type="AssertNotIn",
    )


def check_match(case, pattern: str, text: str, passed: str, failed: str = "") -> bool:
    """Match text against a regular expression first, then record one entry saying what happened.

    Only for values whose form is known and whose exact text is chosen at run time (a
    generated password, a timestamp, a port).
    """
    matched = re.search(pattern, text) is not None
    return case.assertTrue(
        matched,
        msg=passed if matched else failed or passed,
        expected=f"matches {pattern!r}",
        actual=repr(text),
        assertion_type="AssertRegex",
    )


def check_less(case, actual, limit, passed: str, failed: str = "") -> bool:
    """Compare actual with an upper limit first, then record one entry saying what happened."""
    below = actual < limit
    return case.assertTrue(
        below,
        msg=passed if below else failed or passed,
        expected=f"less than {limit!r}",
        actual=repr(actual),
        assertion_type="AssertLess",
    )


def raised_name(exc: BaseException | None) -> str:
    """The class name of exc, or 'nothing raised' when exc is None, for readable reports."""
    return "nothing raised" if exc is None else type(exc).__name__


def exits(case, done: "Done", expected: int, command: str, stop: bool = False) -> bool:
    """Record the exit code of a finished command against the one expected; the failure shows
    the ends of its output."""
    return check(
        case,
        done.code,
        expected,
        f"{command} exits {expected}",
        f"{command} exits {done.code}, not {expected}: {done!r}",
        stop=stop,
    )


def says(case, message: str, text: str, what: str) -> bool:
    """Record that an output holds a message; the failure shows what it holds instead."""
    return check_in(
        case,
        message,
        text,
        f"{what} says: {message}",
        f"{what} does not say {message!r}; it says: {text.strip()[-600:]}",
    )


def setting(name: str) -> str:
    """Return a required environment setting."""
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"{name} is not set")
    return value


def local_only(url: str) -> str:
    """Return url without a trailing slash when its host is localhost or 127.0.0.1; refuse it
    otherwise."""
    host = urllib.parse.urlsplit(url).hostname or ""
    if host not in ("localhost", "127.0.0.1"):
        raise RuntimeError(
            f"{url} is not a local address; the suites only reach throwaway instances"
        )
    return url.rstrip("/")


def bud_url() -> str:
    """Return the base URL of the throwaway Bud."""
    return local_only(setting("BUD_URL"))


def max_upload_bytes() -> int:
    """Return the upload size limit the throwaway Bud runs with."""
    return int(setting("BUD_MAX_UPLOAD_BYTES"))


def work_dir(name: str) -> Path:
    """Return a new empty directory for one case."""
    base = Path(os.environ.get("BUDTEST_WORK_DIR", tempfile.gettempdir()))
    base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f"{name}-", dir=base))


def closed_port() -> int:
    """Return a loopback port nothing listens on."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def pace_registration(limit: int = 8) -> None:
    """Wait until fewer than limit station registrations were sent in the last minute (Bud allows
    10)."""
    while True:
        recent = [t for t in _REGISTRATIONS if time.monotonic() - t < 60]
        _REGISTRATIONS[:] = recent
        if len(recent) < limit:
            _REGISTRATIONS.append(time.monotonic())
            return
        time.sleep(60 - (time.monotonic() - recent[0]) + 0.5)


class Done:
    """A finished child process: its exit code, stdout and stderr."""

    def __init__(self, code: int, out: str, err: str):
        self.code, self.out, self.err = code, out, err

    def __repr__(self) -> str:
        """Return the exit code and the ends of both outputs."""
        return f"exit {self.code}\n--- stdout\n{self.out[-3000:]}\n--- stderr\n{self.err[-3000:]}"


class Case:
    """One case's HOME, working directory and temporary directory, and the commands it runs
    there."""

    def __init__(self, name: str):
        self.root = work_dir(name)
        self.home = self.root / "home"
        self.cwd = self.root / "cwd"
        self.tmp = self.root / "tmp"
        for path in (self.home, self.cwd, self.tmp):
            path.mkdir()

    def env(self, extra: dict | None = None) -> dict:
        """Return the child environment: no BUD_* settings, the case's HOME and TMPDIR,
        budtestlibrary importable, and BUDTEST_CODE_PATH first on the path when it is set."""
        dropped = (
            "RUNNER_API_KEY",
            "REQUESTS_CA_BUNDLE",
            "CURL_CA_BUNDLE",
            "PYTHONPATH",
            "PACKAGE_ORG",
            "ORG_MAINTAINER",
        )
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("BUD_") and k not in dropped and k != "ADMIN_PASSWORD"
        }
        env.update(
            {
                "HOME": str(self.home),
                "TMPDIR": str(self.tmp),
                "PYTHONPATH": os.pathsep.join(
                    p for p in (os.environ.get("BUDTEST_CODE_PATH", ""), LIBRARY_PATH) if p
                ),
                "PYTHONDONTWRITEBYTECODE": "1",
                "NO_COLOR": "1",
                "COLUMNS": "200",
            }
        )
        for key, value in (extra or {}).items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = str(value)
        return env

    def command(
        self,
        *args,
        env: dict | None = None,
        timeout: float = 300,
        cwd: Path | None = None,
        input: str | None = None,
    ) -> Done:
        """Run a command line in the case directory and return its outcome."""
        done = subprocess.run(
            list(args),
            cwd=cwd or self.cwd,
            env=self.env(env),
            capture_output=True,
            text=True,
            timeout=timeout,
            input=input,
        )
        return Done(done.returncode, done.stdout, done.stderr)

    def bud_runner(self, *args, **kwargs) -> Done:
        """Run ``python -m bud_runner`` with the arguments."""
        return self.command(PYTHON, "-m", "bud_runner", *[str(a) for a in args], **kwargs)

    def run_tests(
        self,
        test_case_list: str,
        *args,
        station: "Station | None" = None,
        env: dict | None = None,
        timeout: float = 300,
        backend: str | None = None,
    ) -> Done:
        """Run ``run-tests`` on a test case list, as the station against its Bud (or the backend
        given) when a station is given."""
        extra = []
        if station is not None:
            self.give_station(station)
            extra = ["-b", backend or station.backend, "-u", station.name]
        return self.bud_runner(
            "run-tests", "-t", test_case_list, *extra, *args, env=env, timeout=timeout
        )

    def start(self, *args, env: dict | None = None, cwd: Path | None = None) -> "Running":
        """Start a command line in the case directory without waiting for it."""
        return Running(self, [str(a) for a in args], env, cwd)

    def write(self, relative: str, text: str | bytes) -> Path:
        """Write a file under the working directory and return its path."""
        path = self.cwd / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(text, bytes):
            path.write_bytes(text)
        else:
            path.write_text(text, encoding="utf-8")
        return path

    def spooled(self) -> list[Path]:
        """Return the result payloads spooled under the case's HOME."""
        spool = self.home / ".bud" / "spool" / "results"
        return sorted(spool.glob("*.json")) if spool.is_dir() else []

    def vault(self) -> dict:
        """Return the identity vault under the case's HOME."""
        path = self.home / ".bud" / "config.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}

    def save_vault(self, data: dict) -> None:
        """Write the identity vault under the case's HOME."""
        path = self.home / ".bud" / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def give_station(self, station: "Station") -> None:
        """Put a registered station's identity into the case's vault, as registering on this
        machine would."""
        data = self.vault()
        data[station.name] = {
            "token": station.token,
            "port": station.port,
            "backend": station.backend,
        }
        self.save_vault(data)

    def junit(self, name: str = "report_junit.xml") -> ET.Element:
        """Return the root of a JUnit report written in the working directory."""
        return ET.parse(self.cwd / name).getroot()


class Running:
    """A started child process whose output goes to files under the case."""

    def __init__(self, case: Case, args: list, env: dict | None, cwd: Path | None):
        stamp = f"{time.monotonic_ns()}"
        self.out_path = case.root / f"out-{stamp}.txt"
        self.err_path = case.root / f"err-{stamp}.txt"
        self._out = open(self.out_path, "w")
        self._err = open(self.err_path, "w")
        self.process = subprocess.Popen(
            args,
            cwd=cwd or case.cwd,
            env=case.env(env),
            stdout=self._out,
            stderr=self._err,
            text=True,
            start_new_session=True,
        )

    @property
    def out(self) -> str:
        """Return what the process wrote on stdout so far."""
        return self.out_path.read_text(encoding="utf-8", errors="replace")

    @property
    def err(self) -> str:
        """Return what the process wrote on stderr so far."""
        return self.err_path.read_text(encoding="utf-8", errors="replace")

    def alive(self) -> bool:
        """Return whether the process is still running."""
        return self.process.poll() is None

    def signal(self, number: int) -> None:
        """Send a signal to the process."""
        self.process.send_signal(number)

    def wait(self, timeout: float = 60) -> int:
        """Wait for the process to end and return its exit code."""
        try:
            return self.process.wait(timeout=timeout)
        finally:
            self._out.close()
            self._err.close()

    def stop(self) -> None:
        """End the process and its children."""
        if self.alive():
            try:
                os.killpg(self.process.pid, 15)
                self.process.wait(timeout=10)
            except Exception:
                os.killpg(self.process.pid, 9)
                self.process.wait(timeout=10)
        self._out.close()
        self._err.close()


class Station:
    """A Test Station registered with the throwaway Bud: its name, token, socket port, backend,
    password and enrolment key."""

    def __init__(self, name: str, token: str, port: int, backend: str, password: str, api_key: str):
        self.name, self.token, self.port, self.backend, self.password, self.api_key = (
            name,
            token,
            port,
            backend,
            password,
            api_key,
        )


class Bud:
    """The throwaway Bud over its HTTP API, signed in once as the seeded administrator."""

    _token: str | None = None

    def __init__(self):
        self.url = bud_url()

    def token(self) -> str:
        """Return the administrator's access token, signing in on first use."""
        if Bud._token is None:
            answer = requests.post(
                f"{self.url}/api/auth/login",
                json={"email": setting("ADMIN_EMAIL"), "password": setting("ADMIN_PASSWORD")},
                timeout=30,
            )
            answer.raise_for_status()
            Bud._token = answer.json()["access_token"]
        return Bud._token

    def request(
        self, method: str, path: str, token: str | None = None, **kwargs
    ) -> requests.Response:
        """Send a request to the Bud API as the administrator, signing in again once when the
        administrator's token has expired, or with the token given."""
        headers = {"Authorization": f"Bearer {token or self.token()}"}
        answer = requests.request(
            method, f"{self.url}/api{path}", headers=headers, timeout=60, **kwargs
        )
        if answer.status_code == 401 and token is None:
            Bud._token = None
            headers = {"Authorization": f"Bearer {self.token()}"}
            answer = requests.request(
                method, f"{self.url}/api{path}", headers=headers, timeout=60, **kwargs
            )
        return answer

    def get(self, path: str, **kwargs):
        """Return the JSON answer of a GET, raising on an error status."""
        answer = self.request("GET", path, **kwargs)
        answer.raise_for_status()
        return answer.json()

    def post(self, path: str, body: dict | None = None, **kwargs):
        """Return the JSON answer of a POST, raising on an error status."""
        answer = self.request("POST", path, json=body, **kwargs)
        answer.raise_for_status()
        return answer.json() if answer.content else None

    def mint_key(self, station_name: str | None = None) -> str:
        """Mint an enrolment key, optionally reserving a station name, and return it."""
        body = {"label": f"budtest-{time.monotonic_ns()}"}
        if station_name:
            body["station_name"] = station_name
        return self.post("/runners/api-keys", body)["api_key"]

    def free_station_name(self) -> str:
        """Return the first station-NN name no station and no enrolment key holds yet."""
        taken = {s["account"] for s in self.stations()} | {
            k.get("station_name") for k in self.get("/runners/api-keys")
        }
        number = 1
        while f"station-{number:02d}" in taken:
            number += 1
        return f"station-{number:02d}"

    def station(self, alias: str) -> Station:
        """Return the station this process registered under the alias, registering a new station-NN
        on first use."""
        if alias not in _STATIONS:
            name = self.free_station_name()
            case = Case(f"register-{name}")
            password = f"{name}-password-1"
            pace_registration()
            api_key = self.mint_key(name)
            done = case.bud_runner(
                "register",
                "-u",
                name,
                "-p",
                password,
                "--no-start",
                "-b",
                self.url,
                "--api-key",
                api_key,
            )
            if done.code != 0:
                raise RuntimeError(f"registering {name} failed: {done}")
            entry = case.vault()[name]
            _STATIONS[alias] = Station(
                name, entry["token"], entry["port"], entry["backend"], password, api_key
            )
        return _STATIONS[alias]

    def product(self, name: str) -> int:
        """Return the id of a product of that name, creating it when Bud has none."""
        for product in self.get("/products"):
            if product.get("name") == name:
                return product["id"]
        return self.post("/products", {"name": name})["id"]

    def run(self, run_id: int) -> dict:
        """Return a test run."""
        return self.get(f"/test-runs/{run_id}")

    def runs(self) -> list[dict]:
        """Return the test runs Bud lists, newest first."""
        answer = self.get("/test-runs", params={"limit": 100})
        return answer.get("runs", answer.get("items", [])) if isinstance(answer, dict) else answer

    def results(self, run_id: int) -> list[dict]:
        """Return the results of a run in the order Bud stored them (by id), each with its
        traceback."""
        return [
            self.get(f"/results/detail/{row['id']}")
            for row in sorted(self.get(f"/results/{run_id}"), key=lambda row: row["id"])
        ]

    def artifacts(self, run_id: int) -> list[dict]:
        """Return the artifacts of a run in upload order."""
        return self.get(f"/test-runs/{run_id}/artifacts")

    def uploaded(self, run_id: int) -> list[str]:
        """Return the names of the files uploaded to a run, without the PDF reports Bud stores
        itself when a run completes."""
        return [
            a["original_filename"]
            for a in self.artifacts(run_id)
            if not a["original_filename"].startswith(("bud-run-", "bud-suite-"))
        ]

    def stations(self) -> list[dict]:
        """Return the Test Stations with their online state."""
        return self.get("/runners/status")["runners"]

    def queue(self, test_paths: list[str], station: str, name: str | None = None) -> dict:
        """Queue a custom run of test paths for a station."""
        body = {"test_paths": test_paths, "runner_account": station}
        if name:
            body["name"] = name
        return self.post("/test-runs/custom", body)

    def create_run(
        self, station: Station, name: str, test_case_list: str = "demo_list.TESTS"
    ) -> int:
        """Create a test run as the station and return its id."""
        answer = requests.post(
            f"{self.url}/api/test-runs",
            headers={"Authorization": f"Bearer {station.token}"},
            json={
                "test_case_list": test_case_list,
                "test_suite_name": name,
                "runner_account": station.name,
                "status": "Running",
                "product_composition_id": self.product("Demo"),
            },
            timeout=30,
        )
        answer.raise_for_status()
        return answer.json()["id"]

    def new_run_ids(self, before: set[int]) -> list[int]:
        """Return the ids of runs created since the set of ids was taken, oldest first."""
        return sorted(r["id"] for r in self.runs() if r["id"] not in before)

    def run_ids(self) -> set[int]:
        """Return the ids of every run Bud lists now."""
        return {r["id"] for r in self.runs()}


class _Server:
    """A threaded HTTP server on 127.0.0.1 with a free port, answering through handle(request)."""

    def __init__(self, handle, port: int = 0):
        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                """Keep the server quiet."""

            def answer(self):
                """Read the request, let the owner answer it and write the answer."""
                length = int(self.headers.get("content-length") or 0)
                body = self.rfile.read(length) if length else b""
                parts = urllib.parse.urlsplit(self.path)
                request = {
                    "method": self.command,
                    "path": parts.path,
                    "raw_path": self.path,
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                    "raw_headers": list(self.headers.items()),
                    "body": body,
                }
                status, headers, data = handle(request)
                self.send_response(status)
                for key, value in headers:
                    if key.lower() not in (
                        "transfer-encoding",
                        "connection",
                        "content-length",
                        "keep-alive",
                    ):
                        self.send_header(key, value)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = answer

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        """Stop the server and free its port."""
        self.server.shutdown()
        self.server.server_close()


class Proxy(_Server):
    """A recording proxy on 127.0.0.1 in front of the throwaway Bud; every request is kept in
    requests.

    refuse(request), when set, returns (status, text) to answer a request without passing it
    on, or None to pass it on; rewrite(request, status, data), when set, returns the body
    the client gets in place of Bud's, or None to keep it.
    """

    def __init__(self, port: int = 0, refuse=None, rewrite=None):
        self.upstream = urllib.parse.urlsplit(bud_url())
        self.requests: list[dict] = []
        self.refuse, self.rewrite = refuse, rewrite
        super().__init__(self._forward, port)

    def _forward(self, request: dict):
        """Send the request on to Bud and return its answer, or the refusal or rewrite the case
        set."""
        self.requests.append(request)
        refusal = self.refuse(request) if self.refuse else None
        if refusal is not None:
            return (
                refusal[0],
                [("Content-Type", "application/json")],
                json.dumps({"detail": refusal[1]}).encode(),
            )
        connection = http.client.HTTPConnection(
            self.upstream.hostname, self.upstream.port or 80, timeout=120
        )
        connection.putrequest(
            request["method"], request["raw_path"], skip_host=True, skip_accept_encoding=True
        )
        for key, value in request["raw_headers"]:
            if key.lower() not in (
                "connection",
                "keep-alive",
                "transfer-encoding",
                "accept-encoding",
            ):
                connection.putheader(key, value)
        connection.endheaders(request["body"] or None)
        response = connection.getresponse()
        data = response.read()
        connection.close()
        replaced = self.rewrite(request, response.status, data) if self.rewrite else None
        if replaced is not None:
            return response.status, [("Content-Type", "text/plain")], replaced
        return response.status, response.getheaders(), data

    def seen(self, method: str | None = None, prefix: str = "/api/") -> list[dict]:
        """Return the recorded API requests, optionally of one method."""
        return [
            r
            for r in self.requests
            if r["path"].startswith(prefix) and (method is None or r["method"] == method)
        ]


class Double(_Server):
    """An HTTP double for answers a real Bud never gives; respond(request) returns (status, JSON
    body)."""

    def __init__(self, respond):
        self.requests: list[dict] = []

        def handle(request):
            self.requests.append(request)
            status, body = respond(request)
            return status, [("Content-Type", "application/json")], json.dumps(body).encode()

        super().__init__(handle)


class Isolated:
    """Inside the block this process has the case's HOME, working directory and TMPDIR, no BUD_*
    variable, and the variables given."""

    def __init__(self, case: Case, env: dict | None = None):
        self.case, self.extra = case, env or {}

    def __enter__(self) -> Case:
        self.saved_env = dict(os.environ)
        self.saved_cwd = os.getcwd()
        self.saved_tempdir = tempfile.tempdir
        for key in list(os.environ):
            if (
                key.startswith("BUD_")
                and key not in ("BUD_URL", "BUD_MAX_UPLOAD_BYTES")
                or key in ("RUNNER_API_KEY", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")
            ):
                del os.environ[key]
        os.environ.update({"HOME": str(self.case.home), "TMPDIR": str(self.case.tmp)})
        os.environ.update({k: str(v) for k, v in self.extra.items()})
        tempfile.tempdir = None
        os.chdir(self.case.cwd)
        return self.case

    def __exit__(self, *exc) -> None:
        os.chdir(self.saved_cwd)
        os.environ.clear()
        os.environ.update(self.saved_env)
        tempfile.tempdir = self.saved_tempdir


class Warnings(logging.Handler):
    """Inside the block, the warnings a bud_runner logger emits are kept in messages."""

    def __init__(self, logger: str = "bud_runner"):
        super().__init__(logging.WARNING)
        self.logger = logging.getLogger(logger)
        self.messages: list[str] = []

    def emit(self, record):
        """Keep the message."""
        self.messages.append(record.getMessage())

    def __enter__(self) -> "Warnings":
        self.logger.addHandler(self)
        return self

    def __exit__(self, *exc) -> None:
        self.logger.removeHandler(self)


class TlsServer:
    """An HTTPS server on 127.0.0.1 answering 200 to every GET, with a certificate signed by a test
    CA made for it.

    names are the subject alternative names of the server certificate, for example
    ``IP:127.0.0.1`` or ``DNS:bud.example.com``; ca is the CA certificate file.
    """

    def __init__(self, case: Case, names: str):
        folder = case.root / "tls"
        folder.mkdir(exist_ok=True)
        self.ca = folder / "ca.pem"
        key, csr, cert, ext = (
            folder / "server.key",
            folder / "server.csr",
            folder / "server.pem",
            folder / "ext.cnf",
        )

        def run(*args):
            """Run one openssl command in the TLS folder."""
            return subprocess.run(["openssl", *args], check=True, capture_output=True, cwd=folder)

        run(
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            "ca.key",
            "-out",
            str(self.ca),
            "-days",
            "2",
            "-subj",
            "/CN=Demo Test CA",
            "-addext",
            "basicConstraints=critical,CA:TRUE",
            "-addext",
            "keyUsage=critical,keyCertSign,cRLSign",
        )
        run(
            "req",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(csr),
            "-subj",
            "/CN=bud-test-server",
        )
        ext.write_text(
            f"subjectAltName={names}\nbasicConstraints=CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nauthorityKeyIdentifier=keyid,issuer\nsubjectKeyIdentifier=hash\n",
            encoding="utf-8",
        )
        run(
            "x509",
            "-req",
            "-in",
            str(csr),
            "-CA",
            str(self.ca),
            "-CAkey",
            "ca.key",
            "-CAcreateserial",
            "-out",
            str(cert),
            "-days",
            "2",
            "-extfile",
            str(ext),
        )
        self.requests: list[str] = []
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                """Keep the server quiet."""

            def do_GET(self):
                """Answer 200 with a small JSON body."""
                owner.requests.append(self.path)
                body = b'{"status": "healthy"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(cert), str(key))
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.server.daemon_threads = True
        self.url = f"https://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        """Stop the server."""
        self.server.shutdown()
        self.server.server_close()


def copy_fixture(case: Case, name: str, target: str | None = None) -> Path:
    """Copy a file from the fixtures folder into the case's working directory."""
    destination = case.cwd / (target or Path(name).name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURES / name, destination)
    return destination


def wait_for(condition, timeout: float = 30, interval: float = 0.5):
    """Return condition()'s first truthy value within timeout seconds, or its last value."""
    deadline = time.monotonic() + timeout
    value = condition()
    while not value and time.monotonic() < deadline:
        time.sleep(interval)
        value = condition()
    return value


def remote_url() -> str:
    """Return the throwaway Bud under the address 0.0.0.0: bud-runner treats it as another host,
    yet it reaches only this machine."""
    return f"http://0.0.0.0:{urllib.parse.urlsplit(bud_url()).port}"


MARKER_SUITE = '''"""A suite that leaves a marker file when it runs."""

from pathlib import Path

from budtestlibrary import BudTestCase


class MarkerTest(BudTestCase):
    """Writes ran.marker in the working directory."""

    def bud_mark(self):
        """Write the marker."""
        Path("ran.marker").write_text("ran")
        self.assertTrue(True, msg="ran")


MARKER_LIST = ["demo_marker.MarkerTest"]
'''


def marker_suite(case: Case) -> str:
    """Write the marker suite into the case and return its test case list."""
    case.write("demo_marker.py", MARKER_SUITE)
    return "demo_marker.MARKER_LIST"


VOLTAGE_SUITE = '''"""A suite with a failing and a passing step."""

from budtestlibrary import BloomMetaData, BudTestCase


class VoltageTest(BudTestCase):
    """Cell and pack voltage."""

    bloom_metadata = BloomMetaData("PRJ", "001")

    def bud_check_cells(self):
        """One check passes, one fails."""
        self.assertTrue(True, msg="ok")
        self.assertInRange(2.9, 3.0, 4.2, msg="too low")

    def bud_check_pack(self):
        """One check passes."""
        self.assertTrue(True, msg="ok")


VOLTAGE_LIST = ["demo_voltage.VoltageTest"]
'''


def voltage_suite(case: Case) -> str:
    """Write the voltage suite (a failing and a passing step) into the case and return its test
    case list."""
    case.write("demo_voltage.py", VOLTAGE_SUITE)
    return "demo_voltage.VOLTAGE_LIST"
