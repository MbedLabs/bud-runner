"""The default backend, the status command, registration of a station, list-tests and artifact
uploads with test cases."""

import importlib.metadata
import json

import support
from budtestlibrary import BudTestCase

from bud_runner.api_client import BudAPIClient
from bud_runner.auth import AuthManager


class AuthAndStatus(BudTestCase):
    """status against Bud and an unreachable URL, register and re-register in Bud, list-tests,
    version and artifact uploads."""

    def setUpClass(self):
        self.bud = support.Bud()
        self.station = self.bud.station("main")
        self.version = importlib.metadata.version("bud-runner")
        self.bud_version = self.bud.get("/version")["version"]

    def _register(self, case, name, *args):
        """Run register for a station name with a key minted for it."""
        support.pace_registration()
        return case.bud_runner(
            "register",
            "-u",
            name,
            "-b",
            self.bud.url,
            "--api-key",
            self.bud.mint_key(name),
            "--no-start",
            *args,
        )

    def _json_field(self, payload: dict, key: str, expected, meaning: str) -> None:
        """Record one field of status --output-format json against the value expected."""
        support.check(
            self,
            payload.get(key),
            expected,
            f"status --output-format json reports {key}={expected!r}, {meaning}",
            f"status --output-format json reports {key}={payload.get(key)!r}, not {expected!r} "
            f"({meaning})",
        )

    def bud_default_backend_url_is_localhost(self):
        """Without arguments, environment, app.properties or vault, the backend is
        http://localhost:8000."""
        with support.Isolated(support.Case("default")):
            backend = AuthManager().backend_url
        support.check(
            self,
            backend,
            "http://localhost:8000",
            "without arguments, environment, app.properties or vault the backend is "
            "http://localhost:8000",
            f"without any setting the backend is {backend!r}, not http://localhost:8000",
        )

    def bud_status_reports_url_token_health_and_version(self):
        """status for a registered station: URL, token configured, health OK, Bud's version and the
        package version."""
        case = support.Case("status")
        case.give_station(self.station)
        case.write("app.properties", f"budRunnerAccount={self.station.name}\n")
        command = f"bud-runner status --backend-url <Bud> for {self.station.name}"
        done = case.bud_runner("status", "--backend-url", self.bud.url)
        support.exits(self, done, 0, command)
        for line in (
            f"Backend URL: {self.bud.url}",
            f"Runner Account: {self.station.name}",
            "Token: Configured",
            f"Runner package: {self.version}",
            "Backend Health: ✓ OK",
            f"Backend Version: {self.bud_version}",
        ):
            support.says(self, line, done.out, command)

    def bud_status_shows_unreachable_when_health_fails(self):
        """status against a closed port: unreachable and no version line."""
        command = "bud-runner status --backend-url <closed port>"
        done = support.Case("status-closed").bud_runner(
            "status", "--backend-url", f"http://127.0.0.1:{support.closed_port()}", timeout=180
        )
        support.exits(self, done, 0, command)
        support.says(self, "Backend Health: ✗ Unreachable", done.out, command)
        support.check_not_in(
            self,
            "Backend Version",
            done.out,
            f"{command} prints no Backend Version line",
            f"{command} prints a Backend Version line for an unreachable backend",
        )

    def bud_status_json_reports_backend_and_daemon_fields(self):
        """status --output-format json for a registered station: every field, Bud's health and
        version, and the daemon's last heartbeat."""
        case = support.Case("status-json")
        case.give_station(self.station)
        case.write("app.properties", f"budRunnerAccount={self.station.name}\n")
        done = case.bud_runner("status", "--backend-url", self.bud.url, "--output-format", "json")
        support.exits(self, done, 0, "bud-runner status --output-format json", stop=True)
        payload = json.loads(done.out)
        self._json_field(payload, "backend_url", self.bud.url, "the backend given")
        self._json_field(
            payload, "runner_account", self.station.name, "the account in app.properties"
        )
        self._json_field(payload, "token_configured", True, "the station token in the vault")
        self._json_field(payload, "runner_package_version", self.version, "the installed version")
        self._json_field(payload, "socket_port", self.station.port, "the port in the vault")
        self._json_field(payload, "backend_health", "ok", "Bud answers its health check")
        self._json_field(payload, "backend_version", self.bud_version, "the version Bud reports")
        configured = payload["daemon"].get("configured")
        support.check(
            self,
            configured,
            True,
            "status --output-format json reports the daemon configured for the station",
            f"status --output-format json reports daemon.configured={configured!r}",
        )
        last = payload["daemon"].get("last_heartbeat", "missing")
        support.check(
            self,
            last,
            None,
            "status --output-format json reports no heartbeat while the daemon has sent none",
            f"status --output-format json reports last_heartbeat={last!r} while the daemon has "
            "sent none",
        )
        record = {
            "sent_at": "2026-11-04T01:00:00+00:00",
            "ok": True,
            "answer": {
                "status": "ok",
                "timestamp": "2026-11-04T01:00:00",
                "account": self.station.name,
            },
        }
        daemons = case.home / ".bud" / "daemons"
        daemons.mkdir(parents=True, exist_ok=True)
        (daemons / f"bud_{self.station.name}.heartbeat.json").write_text(
            json.dumps(record), encoding="utf-8"
        )
        done = case.bud_runner("status", "--backend-url", self.bud.url, "--output-format", "json")
        support.exits(self, done, 0, "bud-runner status --output-format json", stop=True)
        last = json.loads(done.out)["daemon"].get("last_heartbeat")
        support.check(
            self,
            last,
            record,
            "status --output-format json reports the daemon's last heartbeat: sent at "
            "2026-11-04T01:00:00+00:00 and accepted by Bud",
            f"status --output-format json reports last_heartbeat={last!r}, not the daemon's "
            "recorded heartbeat",
        )

    def bud_version_reports_the_installed_distribution_version(self):
        """version prints the version importlib.metadata gives for bud-runner."""
        done = support.Case("version").bud_runner("version")
        printed = done.out.strip()
        support.check(
            self,
            printed,
            f"bud_runner version {self.version}",
            f"bud-runner version prints the installed version: bud_runner version {self.version}",
            f"bud-runner version prints {printed!r}, not bud_runner version {self.version}",
        )

    def bud_register_project_link_omits_runner_socket_port(self):
        """register --no-start: the project link names account and backend, and no socket port."""
        case = support.Case("register-link")
        name = self.bud.free_station_name()
        command = f"bud-runner register -u {name} --no-start"
        done = self._register(case, name, "--password", "station-password-1")
        support.exits(self, done, 0, command, stop=True)
        support.says(self, f"budRunnerAccount={name}", done.out, command)
        support.says(self, f"budBackend={self.bud.url}", done.out, command)
        support.check_not_in(
            self,
            "runnerSocketPort=",
            done.out,
            f"{command} prints no runnerSocketPort line in the project link",
            f"{command} prints a runnerSocketPort line in the project link",
        )
        support.check_not_in(
            self,
            "runnerSocketPort",
            (case.cwd / "app.properties").read_text(),
            "the app.properties register writes holds no runnerSocketPort",
            "the app.properties register writes holds runnerSocketPort",
        )

    def bud_register_without_password_generates_one_and_prints_once(self):
        """register without --password prints one generated password; Bud takes it on
        --re-register and refuses another."""
        case = support.Case("register-generated")
        name = self.bud.free_station_name()
        key = self.bud.mint_key(name)
        support.pace_registration()
        command = f"bud-runner register -u {name} without --password"
        done = case.bud_runner(
            "register", "-u", name, "-b", self.bud.url, "--api-key", key, "--no-start"
        )
        support.exits(self, done, 0, command, stop=True)
        lines = done.out.splitlines()
        heading = "Generated password for this runner account. Save it somewhere secure:"
        support.need(
            self,
            heading in lines,
            True,
            f"{command} announces the generated password",
            f"{command} does not announce a generated password: {done.out[-600:]}",
        )
        password = lines[lines.index(heading) + 1].strip()
        support.check(
            self,
            done.out.count(password),
            1,
            f"{command} prints the generated password exactly once",
            f"{command} prints the generated password {done.out.count(password)} times",
        )
        support.check_less(
            self,
            16,
            len(password),
            f"the generated password has {len(password)} characters, more than 16",
            f"the generated password has only {len(password)} characters",
        )
        support.pace_registration()
        wrong = case.bud_runner(
            "register",
            "-u",
            name,
            "-b",
            self.bud.url,
            "--api-key",
            key,
            "--no-start",
            "--re-register",
            "--password",
            "another-password-1",
        )
        refused = f"bud-runner register -u {name} --re-register with another password"
        support.exits(self, wrong, 1, refused)
        support.says(self, "Registration failed: 400 Client Error", wrong.err, refused)
        support.pace_registration()
        again = case.bud_runner(
            "register",
            "-u",
            name,
            "-b",
            self.bud.url,
            "--api-key",
            key,
            "--no-start",
            "--re-register",
            "--password",
            password,
        )
        support.exits(
            self,
            again,
            0,
            f"bud-runner register -u {name} --re-register with the generated password",
        )

    def bud_register_refuses_existing_local_runner_without_re_register(self):
        """A station in the local vault is registered again only with --re-register (exit
        2)."""
        case = support.Case("register-existing")
        case.save_vault(
            {
                "station-01": {
                    "token": "station-token",
                    "port": 53035,
                    "backend": "https://bud.example.com",
                }
            }
        )
        command = "bud-runner register -u station-01 with station-01 already in the vault"
        done = case.bud_runner(
            "register",
            "-u",
            "station-01",
            "-b",
            "https://bud.example.com",
            "--api-key",
            "enrolment-key",
            "--no-start",
        )
        support.exits(self, done, 2, command)
        support.says(self, "already registered locally", done.err, command)

    def bud_re_register_requires_existing_password(self):
        """--re-register without --password exits 2 with an explanation."""
        case = support.Case("re-register-no-password")
        case.save_vault(
            {
                "station-01": {
                    "token": "station-token",
                    "port": 53035,
                    "backend": "https://bud.example.com",
                }
            }
        )
        command = "bud-runner register -u station-01 --re-register without --password"
        done = case.bud_runner(
            "register",
            "-u",
            "station-01",
            "-b",
            "https://bud.example.com",
            "--api-key",
            "enrolment-key",
            "--re-register",
            "--no-start",
        )
        support.exits(self, done, 2, command)
        support.says(
            self, "Re-registration requires the existing runner password", done.err, command
        )

    def bud_re_register_uses_provided_password_and_refreshes_registration(self):
        """register, then --re-register with the same password and key: exit 0 and a new token in
        the vault."""
        case = support.Case("re-register")
        name = self.bud.free_station_name()
        key = self.bud.mint_key(name)
        support.pace_registration()
        first = case.bud_runner(
            "register",
            "-u",
            name,
            "-p",
            "station-password-1",
            "-b",
            self.bud.url,
            "--api-key",
            key,
            "--no-start",
        )
        support.exits(self, first, 0, f"bud-runner register -u {name}", stop=True)
        token = case.vault()[name]["token"]
        support.pace_registration()
        command = f"bud-runner register -u {name} --re-register with the same password"
        again = case.bud_runner(
            "register",
            "-u",
            name,
            "-p",
            "station-password-1",
            "-b",
            self.bud.url,
            "--api-key",
            key,
            "--no-start",
            "--re-register",
        )
        support.exits(self, again, 0, command)
        support.says(self, f"Re-registering runner: {name}", again.out, command)
        support.check(
            self,
            case.vault()[name]["token"] == token,
            False,
            f"after {command} the identity vault holds a new token for {name}",
            f"after {command} the identity vault still holds the old token for {name}",
        )

    def bud_auth_manager_exposes_socket_port_from_registered_identity(self):
        """status --output-format json shows the socket port the vault holds for the station."""
        case = support.Case("socket-port")
        case.save_vault(
            {
                "service-runner": {
                    "token": "vault-token",
                    "port": 54001,
                    "backend": f"http://127.0.0.1:{support.closed_port()}",
                }
            }
        )
        case.write("app.properties", "budRunnerAccount=service-runner\n")
        done = case.bud_runner("status", "--output-format", "json", timeout=180)
        port = json.loads(done.out)["socket_port"]
        support.check(
            self,
            port,
            54001,
            "status --output-format json shows socket_port 54001, the port the vault holds for "
            "service-runner",
            f"status --output-format json shows socket_port {port!r}, not the vault's 54001",
        )

    def bud_list_tests_resolves_suite_without_running_it(self):
        """list-tests names the classes of the list and runs none."""
        case = support.Case("list-tests")
        test_list = support.marker_suite(case)
        command = f"bud-runner list-tests --test-case-list {test_list}"
        done = case.bud_runner("list-tests", "--test-case-list", test_list)
        support.exits(self, done, 0, command)
        support.says(self, f"Resolved 1 test class(es) from {test_list}:", done.out, command)
        support.says(self, "  - demo_marker.MarkerTest", done.out, command)
        support.check(
            self,
            (case.cwd / "ran.marker").exists(),
            False,
            f"{command} runs none of the classes: no ran.marker",
            f"{command} ran the marker suite",
        )

    def bud_list_tests_supports_json_output(self):
        """list-tests --output-format json gives the list, the count and each class's name, module
        and path."""
        case = support.Case("list-tests-json")
        test_list = support.marker_suite(case)
        done = case.bud_runner(
            "list-tests", "--test-case-list", test_list, "--output-format", "json"
        )
        listed = json.loads(done.out)
        support.check(
            self,
            listed,
            {
                "test_case_list": test_list,
                "count": 1,
                "tests": [
                    {
                        "name": "MarkerTest",
                        "module": "demo_marker",
                        "path": "demo_marker.MarkerTest",
                    }
                ],
            },
            "list-tests --output-format json gives the list, count 1 and MarkerTest's name, module "
            "and path",
            f"list-tests --output-format json gives {listed}",
        )

    def bud_upload_artifact_stores_the_file_with_its_run_and_test_case(self):
        """upload_artifact(run_id, test_case) as the station: Bud stores the file on the run under
        the test case."""
        case = support.Case("artifact-test-case")
        run_id = self.bud.create_run(self.station, "Artifact test case")
        trace = case.write("trace.log", "trace-data")
        with support.Isolated(
            case, {"BUD_RUNNER_TOKEN": self.station.token, "BUD_RUNNER_ACCOUNT": self.station.name}
        ):
            answer = BudAPIClient(AuthManager(backend_url=self.bud.url)).upload_artifact(
                str(trace), run_id=run_id, test_case="VoltageTest"
            )
        stored = self.bud.artifacts(run_id)
        support.need(
            self,
            len(stored),
            1,
            f"Bud stores one artifact on run {run_id}",
            f"Bud stores {len(stored)} artifacts on run {run_id}, not one",
        )
        fields = {k: stored[0][k] for k in ("original_filename", "test_case", "size_bytes")}
        support.check(
            self,
            fields,
            {"original_filename": "trace.log", "test_case": "VoltageTest", "size_bytes": 10},
            f"Bud stores trace.log on run {run_id} under test case VoltageTest with its 10 bytes",
            f"Bud stores the artifact on run {run_id} as {fields}",
        )
        support.check(
            self,
            answer["id"],
            stored[0]["id"],
            f"upload_artifact answers with the id {stored[0]['id']} of the stored artifact",
            f"upload_artifact answers with id {answer['id']!r}, the stored artifact has "
            f"{stored[0]['id']}",
        )
