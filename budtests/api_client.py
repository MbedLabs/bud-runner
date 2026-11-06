"""Run submissions are made with the station's credentials even when a user session is also
configured; Bud stores no result or artifact a user sends."""

import json

import support
from budtestlibrary import BudTestCase, parameterized

from bud_runner.api_client import BudAPIClient
from bud_runner.auth import AuthManager

STATION_REQUIRED = "Station authentication is required"


class ApiClient(BudTestCase):
    """Which credentials create, update and fill a run, and upload its artifacts, as Bud sees
    them."""

    def setUpClass(self):
        self.bud = support.Bud()
        self.station = self.bud.station("main")
        self.human = self.bud.token()

    def _env(self, human: bool) -> dict:
        """Return the station token, with the administrator's token as BUD_TOKEN when human is
        set."""
        env = {"BUD_RUNNER_TOKEN": self.station.token, "BUD_RUNNER_ACCOUNT": self.station.name}
        if human:
            env["BUD_TOKEN"] = self.human
        return env

    @staticmethod
    def _with(human: bool) -> str:
        """Name the credentials a parameterized case runs with."""
        return "the station token and a user BUD_TOKEN" if human else "the station token only"

    @parameterized([False, True])
    def bud_run_creation_uses_station_token(self, human):
        """add-test-run with the station token, a user session or not: Bud records the run under
        the station."""
        case = support.Case("create-as-station")
        done = case.bud_runner(
            "add-test-run",
            "-t",
            "demo_voltage.VOLTAGE_LIST",
            "-n",
            "Station run",
            "-b",
            self.bud.url,
            "--product-composition-id",
            self.bud.product("Demo"),
            "--output-format",
            "json",
            env=self._env(human),
        )
        support.exits(self, done, 0, f"bud-runner add-test-run with {self._with(human)}", stop=True)
        run = self.bud.run(int(json.loads(done.out)["id"]))
        support.check(
            self,
            run["runner_account"],
            self.station.name,
            f"Bud records the run created with {self._with(human)} under the station "
            f"{self.station.name}",
            f"Bud records the run created with {self._with(human)} under "
            f"{run['runner_account']!r}, not the station {self.station.name}",
        )

    @parameterized([False, True])
    def bud_run_update_and_results_use_station_token(self, human):
        """run-tests --test-run-id with the station token, a user session or not: results and
        completion are recorded for the station's run."""
        case = support.Case("results-as-station")
        run_id = self.bud.create_run(self.station, "Station results")
        command = f"bud-runner run-tests --test-run-id {run_id} with {self._with(human)}"
        done = case.bud_runner(
            "run-tests",
            "-t",
            support.voltage_suite(case),
            "--test-run-id",
            run_id,
            "-b",
            self.bud.url,
            env=self._env(human),
        )
        support.says(self, "✓ Results uploaded to backend", done.out, command)
        support.says(self, f"✓ Test run {run_id} marked as Completed", done.out, command)
        run = self.bud.run(run_id)
        stored = {k: run[k] for k in ("status", "runner_account", "total_tests")}
        support.check(
            self,
            stored,
            {"status": "Completed", "runner_account": self.station.name, "total_tests": 1},
            f"Bud holds run {run_id} as the station's Completed run with its one test class",
            f"Bud holds run {run_id} as {stored}",
        )
        count = len(self.bud.results(run_id))
        support.check(
            self,
            count,
            2,
            f"Bud stores both step results of the voltage suite on run {run_id}",
            f"Bud stores {count} results on run {run_id}, not the 2 step results",
        )

    def bud_human_session_cannot_create_a_run_without_station_token(self):
        """add-test-run with only a user token: exit 1, station authentication is required, no run
        in Bud."""
        before = self.bud.run_ids()
        command = "bud-runner add-test-run --bud-token <user> without a station token"
        done = support.Case("create-as-human").bud_runner(
            "add-test-run",
            "-t",
            "demo_voltage.VOLTAGE_LIST",
            "-n",
            "Human run",
            "-b",
            self.bud.url,
            "--bud-token",
            self.human,
        )
        support.exits(self, done, 1, command)
        support.says(self, STATION_REQUIRED, done.err, command)
        created = self.bud.new_run_ids(before)
        support.check(
            self,
            created,
            [],
            f"{command} creates no run in Bud",
            f"{command} created the runs {created} in Bud",
        )

    def bud_human_session_cannot_submit_results_without_station_token(self):
        """run-tests --test-run-id with only a user token: the upload is refused before sending,
        exit 1, nothing stored."""
        case = support.Case("results-as-human")
        run_id = self.bud.create_run(self.station, "Human results")
        command = f"bud-runner run-tests --test-run-id {run_id} with only a user BUD_TOKEN"
        done = case.bud_runner(
            "run-tests",
            "-t",
            support.voltage_suite(case),
            "--test-run-id",
            run_id,
            "-b",
            self.bud.url,
            env={"BUD_TOKEN": self.human},
        )
        support.exits(self, done, 1, command)
        support.says(self, f"{STATION_REQUIRED} to submit test results", done.err, command)
        stored = self.bud.results(run_id)
        support.check(
            self,
            stored,
            [],
            f"Bud stores no result on run {run_id} from a user: only stations submit results",
            f"Bud stores {len(stored)} results on run {run_id} sent with only a user token",
        )

    def bud_result_submission_with_station_key_removes_human_session(self):
        """upload_results_payload with only the station's enrolment key and a user token: Bud takes
        the results as the station's."""
        case = support.Case("key-results")
        with support.Isolated(
            case, {"BUD_RUNNER_API_KEY": self.station.api_key, "BUD_TOKEN": self.human}
        ):
            answer = BudAPIClient(AuthManager(backend_url=self.bud.url)).upload_results_payload(
                {
                    "results": [
                        {
                            "test_class": "KeySuite",
                            "test_method": "bud_one",
                            "passed": True,
                            "duration_seconds": 0.1,
                        }
                    ],
                    "test_suite_name": "Key upload",
                }
            )
        run = self.bud.run(answer["test_run_id"])
        support.check(
            self,
            run["runner_account"],
            self.station.name,
            "results sent with the station's enrolment key beside a user token create a run of "
            f"the station {self.station.name}, not of the user",
            f"results sent with the station's enrolment key beside a user token create a run of "
            f"{run['runner_account']!r}",
        )
        classes = [r["test_class"] for r in self.bud.results(run["id"])]
        support.check(
            self,
            classes,
            ["KeySuite"],
            f"Bud stores the one KeySuite result on run {run['id']}",
            f"Bud stores the results {classes} on run {run['id']}, not ['KeySuite']",
        )

    @parameterized([False, True])
    def bud_execution_artifact_uses_station_token(self, human):
        """run-tests --test-run-id with the station token, a user session or not: the JUnit report
        is stored on the run."""
        case = support.Case("artifact-as-station")
        run_id = self.bud.create_run(self.station, "Station artifact")
        command = f"bud-runner run-tests --test-run-id {run_id} with {self._with(human)}"
        done = case.bud_runner(
            "run-tests",
            "-t",
            support.voltage_suite(case),
            "--test-run-id",
            run_id,
            "-b",
            self.bud.url,
            env=self._env(human),
        )
        support.says(self, "✓ Uploaded artifact: report_junit.xml", done.out, command)
        uploaded = self.bud.uploaded(run_id)
        support.check(
            self,
            uploaded,
            ["report_junit.xml"],
            f"Bud stores report_junit.xml on run {run_id}, uploaded with {self._with(human)}",
            f"Bud stores {uploaded} on run {run_id}, not ['report_junit.xml']",
        )

    def bud_an_artifact_upload_with_only_a_user_token_is_not_stored(self):
        """upload_artifact with only a user token: Bud stores nothing on the run: only Test
        Stations upload artifacts."""
        case = support.Case("artifact-as-human")
        run_id = self.bud.create_run(self.station, "Human artifact")
        report = case.write("report_junit.xml", "<testsuite/>\n")
        raised = None
        with support.Isolated(case, {"BUD_TOKEN": self.human}):
            try:
                BudAPIClient(AuthManager(backend_url=self.bud.url)).upload_artifact(
                    str(report), run_id=run_id
                )
            except Exception as exc:
                raised = exc
        outcome = f"upload_artifact ended with {support.raised_name(raised)}: {raised}"
        uploaded = self.bud.uploaded(run_id)
        support.check(
            self,
            uploaded,
            [],
            f"Bud stores no artifact on run {run_id} from an upload with only a user token: "
            f"Bud users do not upload artifacts ({outcome})",
            f"Bud stores {uploaded} on run {run_id} from an upload with only a user token, but "
            f"only Test Stations upload artifacts ({outcome})",
        )

    def _last_heartbeat(self):
        """Return the last heartbeat Bud records for the station, or None."""
        found = [s for s in self.bud.stations() if s.get("account") == self.station.name]
        return found[0].get("last_heartbeat") if found else None

    @parameterized([False, True])
    def bud_heartbeat_uses_station_token(self, human):
        """A heartbeat with the station token, a user token or not: Bud answers for the station
        and records the station's heartbeat."""
        before = self._last_heartbeat()
        auth = AuthManager(
            token=self.human if human else None,
            backend_url=self.bud.url,
            runner_account=self.station.name,
            runner_token=self.station.token,
        )
        answer = BudAPIClient(auth).heartbeat()
        support.check(
            self,
            (answer.get("status"), answer.get("account")),
            ("ok", self.station.name),
            f"Bud accepts the heartbeat with {self._with(human)} as station {self.station.name}",
            f"Bud answers the heartbeat with {self._with(human)} with {answer}",
        )
        after = self._last_heartbeat()
        support.check(
            self,
            after is not None and after != before,
            True,
            f"Bud records a new heartbeat for {self.station.name}: {after}",
            f"Bud's last heartbeat for {self.station.name} stays {after!r} after the heartbeat",
        )


if __name__ == "__main__":
    raise SystemExit(0 if ApiClient().run() else 1)
