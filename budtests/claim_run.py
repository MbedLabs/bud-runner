"""claim-run against Bud's queue: the run it claims, what it executes, the answer it gives Bud,
and how it polls."""

import json
import time
import uuid

import requests
import support
from budtestlibrary import BudTestCase

from bud_runner.api_client import BudAPIClient
from bud_runner.auth import AuthManager
from bud_runner.cli import _write_custom_test_list

BENCH = '''"""Bench suites a station runs; each class writes a marker named after it."""

from pathlib import Path

from budtestlibrary import BudTestCase


class VoltageTest(BudTestCase):
    """Passes."""

    def bud_voltage(self):
        """Mark and pass."""
        Path("VoltageTest.ran").write_text("1")
        self.assertTrue(True, msg="voltage")


class CurrentTest(BudTestCase):
    """Passes."""

    def bud_current(self):
        """Mark and pass."""
        Path("CurrentTest.ran").write_text("1")
        self.assertTrue(True, msg="current")


class PlotTest(BudTestCase):
    """Leaves a PNG beside the run."""

    def bud_plot(self):
        """Write plot.png."""
        Path("plot.png").write_bytes(b"\\x89PNG plot")
        self.assertTrue(True, msg="plotted")


class FailingTest(BudTestCase):
    """Fails."""

    def bud_fails(self):
        """Fail."""
        self.assertEqual(1, 2, msg="fails")


ALL = [
    "demo_bench.VoltageTest",
    "demo_bench.CurrentTest",
    "demo_bench.PlotTest",
    "demo_bench.FailingTest",
]
VOLTAGE = ["demo_bench.VoltageTest"]
'''


class ClaimRun(BudTestCase):
    """What claim-run takes from Bud's queue and what Bud records afterwards."""

    def setUpClass(self):
        self.bud = support.Bud()
        self.number = 0

    def _bench(self, name):
        """Return a new station and a workspace whose bench suites Bud knows from a first run of
        that station."""
        self.number += 1
        station = self.bud.station(f"claim-{self.number}")
        case = support.Case(name)
        case.write("demo_bench.py", BENCH)
        seed = case.run_tests("demo_bench.ALL", station=station)
        if seed.code not in (0, 1):
            raise RuntimeError(f"seeding the catalog failed: {seed!r}")
        for marker in case.cwd.glob("*.ran"):
            marker.unlink()
        for leftover in ("plot.png", "report_junit.xml"):
            (case.cwd / leftover).unlink(missing_ok=True)
        return station, case

    def _claim(self, case, station, *args, backend=None, timeout=300):
        """Run claim-run as the station."""
        return case.bud_runner(
            "claim-run",
            "-u",
            station.name,
            "-b",
            backend or station.backend,
            *args,
            timeout=timeout,
        )

    def _claimed_runs(self, station, before):
        """Return the runs of the station created since the ids in before, oldest first."""
        return [
            self.bud.run(i)
            for i in self.bud.new_run_ids(before)
            if self.bud.run(i)["runner_account"] == station.name
        ]

    def _one_run(self, station, before, command: str) -> dict:
        """Return the one run claimed for the station since before, stopping the step otherwise."""
        runs = self._claimed_runs(station, before)
        support.need(
            self,
            len(runs),
            1,
            f"{command} claims one run of {station.name}",
            f"{command} leaves {len(runs)} runs of {station.name} in Bud, not one",
        )
        return runs[0]

    def _classes(self, run: dict, expected: list, what: str) -> None:
        """Record the classes whose results Bud holds on a run."""
        classes = sorted({r["test_class"] for r in self.bud.results(run["id"])})
        support.check(
            self,
            classes,
            expected,
            f"Bud holds results of {', '.join(expected)} on run {run['id']}: {what}",
            f"Bud holds results of {classes} on run {run['id']}, not {expected}",
        )

    def bud_written_list_loads_through_the_stock_executor(self):
        """A custom run of two classes is claimed and both classes' results reach the claimed
        run."""
        station, case = self._bench("two-classes")
        self.bud.queue(["demo_bench.VoltageTest", "demo_bench.CurrentTest"], station.name)
        before = self.bud.run_ids()
        command = "bud-runner claim-run of a custom run of VoltageTest and CurrentTest"
        done = self._claim(case, station, "--workspace", case.cwd)
        support.exits(self, done, 0, command)
        run = self._one_run(station, before, command)
        self._classes(run, ["CurrentTest", "VoltageTest"], "both selected classes ran")

    def bud_each_run_gets_its_own_module(self):
        """Two custom runs with different selections, claimed by one poller: each run holds only
        its own classes."""
        station, case = self._bench("two-runs")
        self.bud.queue(["demo_bench.VoltageTest"], station.name, name="First selection")
        self.bud.queue(["demo_bench.CurrentTest"], station.name, name="Second selection")
        before = self.bud.run_ids()
        running = case.start(
            support.PYTHON,
            "-m",
            "bud_runner",
            "claim-run",
            "-u",
            station.name,
            "-b",
            station.backend,
            "--interval",
            "1",
            "--workspace",
            case.cwd,
        )
        try:
            support.wait_for(
                lambda: len(
                    [r for r in self._claimed_runs(station, before) if r["claim_acknowledged_at"]]
                )
                == 2,
                timeout=120,
                interval=1,
            )
        finally:
            running.stop()
        answered = [r for r in self._claimed_runs(station, before) if r["claim_acknowledged_at"]]
        support.need(
            self,
            len(answered),
            2,
            "one claim-run --interval 1 poller claims and answers both queued runs",
            f"the poller answered {len(answered)} of the 2 queued runs within 120 s: "
            f"{running.err[-1500:]}",
        )
        runs = sorted(answered, key=lambda r: r["name"])
        held = [sorted({r["test_class"] for r in self.bud.results(run["id"])}) for run in runs]
        support.check(
            self,
            held,
            [["VoltageTest"], ["CurrentTest"]],
            "each claimed run holds only its own selection: VoltageTest, then CurrentTest",
            f"the two claimed runs hold the classes {held}",
        )
        modules = len(list(case.tmp.glob("bud/custom/bud_custom_*.py")))
        support.check(
            self,
            modules,
            2,
            "claim-run generates one test list module per claimed run",
            f"claim-run generated {modules} test list modules for 2 runs",
        )

    def bud_paths_are_written_as_literals(self):
        """In-process: a selected path with a quote is written as a literal and the module
        compiles."""
        case = support.Case("literal")
        with support.Isolated(case):
            reference = _write_custom_test_list(["demo_bench.Voltage'Test"], 7)
        module = case.tmp / "bud" / "custom" / f"{reference.split('.')[0]}.py"
        source = module.read_text()
        namespace = {}
        exec(compile(source, str(module), "exec"), namespace)
        support.check(
            self,
            namespace["CUSTOM_TEST_LIST"],
            ["demo_bench.Voltage'Test"],
            "the generated module compiles and keeps the path demo_bench.Voltage'Test as written",
            f"the generated module holds {namespace['CUSTOM_TEST_LIST']!r}",
        )

    def bud_an_ordinary_run_keeps_its_own_test_case_list(self):
        """+proxy: a claimed run without a selection runs its own test case list (Bud always sends a
        selection; the proxy removes it)."""
        station, case = self._bench("ordinary")
        self.bud.queue(["demo_bench.CurrentTest"], station.name)

        def rewrite(request, status, data):
            """Turn the claimed run into an ordinary run of demo_bench.VOLTAGE."""
            if request["path"] != "/api/runners/claim-run" or status != 200:
                return None
            claimed = json.loads(data)
            claimed["selected_tests"] = None
            claimed["run"]["test_case_list"] = "demo_bench.VOLTAGE"
            return json.dumps(claimed).encode()

        proxy = support.Proxy(rewrite=rewrite)
        before = self.bud.run_ids()
        command = "bud-runner claim-run of a run without a selection and list demo_bench.VOLTAGE"
        try:
            done = self._claim(case, station, "--workspace", case.cwd, backend=proxy.url)
        finally:
            proxy.close()
        support.exits(self, done, 0, command)
        run = self._one_run(station, before, command)
        self._classes(run, ["VoltageTest"], "the run's own test case list ran")
        modules = [p.name for p in case.tmp.glob("bud/custom/*.py")]
        support.check(
            self,
            modules,
            [],
            f"{command} generates no test list module",
            f"{command} generated the modules {modules}",
        )

    def bud_options_are_passed_through(self):
        """claim-run --workspace <dir> -A "*.png": the PNG the suite left is an artifact of the
        claimed run."""
        station, case = self._bench("passthrough")
        self.bud.queue(["demo_bench.PlotTest"], station.name)
        before = self.bud.run_ids()
        elsewhere = support.Case("elsewhere")
        command = 'bud-runner claim-run --workspace <dir> -A "*.png" from another directory'
        done = elsewhere.bud_runner(
            "claim-run",
            "-u",
            station.name,
            "-b",
            station.backend,
            "--workspace",
            case.cwd,
            "-A",
            "*.png",
            env={"HOME": case.home},
        )
        support.exits(self, done, 0, command)
        run = self._one_run(station, before, command)
        uploaded = self.bud.uploaded(run["id"])
        support.check_in(
            self,
            "plot.png",
            uploaded,
            f"plot.png, left by PlotTest in the workspace, is an artifact of run {run['id']}",
            f"run {run['id']} holds the artifacts {uploaded}, without plot.png",
        )

    def bud_claim_uses_the_runner_token(self):
        """claim_next_run with a user token is refused by Bud; with the station token Bud hands
        over the queued run."""
        station, case = self._bench("token")
        self.bud.queue(["demo_bench.VoltageTest"], station.name)
        refusal = None
        with support.Isolated(support.Case("claim-as-user"), {"BUD_TOKEN": self.bud.token()}):
            try:
                BudAPIClient(AuthManager(backend_url=self.bud.url)).claim_next_run()
            except requests.HTTPError as exc:
                refusal = exc.response
        status = getattr(refusal, "status_code", None)
        support.check(
            self,
            status,
            403,
            "Bud answers 403 to claim_next_run with only a user token: stations claim runs",
            f"Bud answers {status!r} to claim_next_run with only a user token, not 403",
        )
        with support.Isolated(
            support.Case("claim-as-station"),
            {
                "BUD_TOKEN": self.bud.token(),
                "BUD_RUNNER_TOKEN": station.token,
                "BUD_RUNNER_ACCOUNT": station.name,
            },
        ):
            client = BudAPIClient(AuthManager(backend_url=self.bud.url))
            claim_id = str(uuid.uuid4())
            claimed = client.claim_next_run(claim_id)
            client.complete_claimed_run(claimed["run"]["id"], claim_id, exit_code=0)
        support.check(
            self,
            claimed["selected_tests"],
            ["demo_bench.VoltageTest"],
            "with the station token beside the user token Bud hands over the queued VoltageTest "
            "run",
            f"with the station token Bud hands over the selection {claimed['selected_tests']!r}",
        )

    def bud_an_empty_queue_is_not_an_error(self):
        """claim-run with nothing queued: exit 0 and "Nothing queued."."""
        station, case = self._bench("empty")
        command = "bud-runner claim-run with nothing queued"
        done = self._claim(case, station)
        support.exits(self, done, 0, command)
        support.says(self, "Nothing queued.", done.out, command)

    def bud_a_rejected_claim_raises(self):
        """claim-run with a station token Bud rejects: exit 1 and the claim error."""
        command = "bud-runner claim-run with a station token Bud rejects"
        done = support.Case("rejected").bud_runner(
            "claim-run",
            "-b",
            self.bud.url,
            env={"BUD_RUNNER_TOKEN": "rejected-station-token", "BUD_RUNNER_ACCOUNT": "station-99"},
        )
        support.exits(self, done, 1, command)
        support.says(self, "⚠ Could not claim a run", done.err, command)

    def bud_completion_sends_the_claim_key_and_terminal_answer(self):
        """A claimed run whose suite fails: Bud shows it finished with exit code 1."""
        station, case = self._bench("failing")
        self.bud.queue(["demo_bench.FailingTest"], station.name)
        before = self.bud.run_ids()
        command = "bud-runner claim-run of a run whose suite fails"
        done = self._claim(case, station, "--workspace", case.cwd)
        support.exits(self, done, 1, f"{command}, with the run's own code,")
        run = self._one_run(station, before, command)
        state = {
            "status": run["status"],
            "runner_exit_code": run["runner_exit_code"],
            "answered": run["claim_acknowledged_at"] is not None,
        }
        support.check(
            self,
            state,
            {"status": "Completed", "runner_exit_code": 1, "answered": True},
            f"Bud shows run {run['id']} Completed, answered, with exit code 1",
            f"Bud shows run {run['id']} as {state}",
        )

    def bud_claims_once_and_exits(self):
        """One queued run: exit 0, "Claimed run N", completed in Bud, nothing more claimed."""
        station, case = self._bench("once")
        self.bud.queue(["demo_bench.VoltageTest"], station.name)
        self.bud.queue(["demo_bench.CurrentTest"], station.name)
        before = self.bud.run_ids()
        command = "bud-runner claim-run with two runs queued"
        done = self._claim(case, station, "--workspace", case.cwd)
        support.exits(self, done, 0, command)
        run = self._one_run(station, before, command)
        support.says(self, f"✓ Claimed run {run['id']}", done.out, command)
        state = {"status": run["status"], "runner_exit_code": run["runner_exit_code"]}
        support.check(
            self,
            state,
            {"status": "Completed", "runner_exit_code": 0},
            f"Bud shows the claimed run {run['id']} Completed with exit code 0",
            f"Bud shows the claimed run {run['id']} as {state}",
        )
        queued = [
            r
            for r in self.bud.get("/execution-requests")
            if r.get("runner_account") == station.name and r.get("state") == "queued"
        ]
        support.check(
            self,
            len(queued),
            1,
            f"{command} claims once and exits: the second request stays queued",
            f"{len(queued)} requests of {station.name} are still queued, not the second one only",
        )

    def bud_child_execution_keeps_the_resolved_station_and_backend(self):
        """Station only in the vault, account in app.properties and backend in BUD_BACKEND_URL: the
        results land on Bud under the station."""
        station, case = self._bench("resolved")
        case.write("app.properties", f"budRunnerAccount={station.name}\n")
        self.bud.queue(["demo_bench.VoltageTest"], station.name)
        before = self.bud.run_ids()
        command = "bud-runner claim-run with the account in app.properties and BUD_BACKEND_URL"
        done = case.bud_runner(
            "claim-run", "--workspace", case.cwd, env={"BUD_BACKEND_URL": self.bud.url}
        )
        support.exits(self, done, 0, command)
        run = self._one_run(station, before, command)
        self._classes(
            run, ["VoltageTest"], "the child execution kept the resolved station and backend"
        )

    def bud_polling_survives_a_backend_blip(self):
        """claim-run --interval 1 started while Bud is unreachable (its client retries for about
        30 s before a poll fails); once Bud can be reached, the queued run is claimed once and
        completed."""
        station, case = self._bench("blip")
        port = support.closed_port()
        before = self.bud.run_ids()
        running = case.start(
            support.PYTHON,
            "-m",
            "bud_runner",
            "claim-run",
            "-u",
            station.name,
            "-b",
            f"http://127.0.0.1:{port}",
            "--interval",
            "1",
            "--workspace",
            case.cwd,
        )
        proxy = None
        try:
            support.wait_for(lambda: "Could not claim a run" in running.err, timeout=90, interval=1)
            self.bud.queue(["demo_bench.VoltageTest"], station.name)
            proxy = support.Proxy(port=port)
            support.wait_for(
                lambda: any(
                    r["claim_acknowledged_at"] for r in self._claimed_runs(station, before)
                ),
                timeout=180,
                interval=1,
            )
        finally:
            running.stop()
            if proxy:
                proxy.close()
        support.says(
            self,
            "⚠ Could not claim a run",
            running.err,
            "claim-run --interval 1 while Bud cannot be reached",
        )
        runs = self._claimed_runs(station, before)
        answered = [r["id"] for r in runs if r["claim_acknowledged_at"]]
        support.check(
            self,
            len(answered),
            1,
            "once Bud can be reached the poller claims and completes the queued run",
            f"once Bud can be reached the poller completed {len(answered)} runs within 180 s",
        )
        support.check(
            self,
            len(runs),
            1,
            "the queued run is claimed once",
            f"the poller claimed {len(runs)} runs for one queued request",
        )

    def bud_a_nonzero_test_exit_is_acknowledged_as_finished(self):
        """A failing queued run: exit 1 and Bud shows it finished."""
        station, case = self._bench("nonzero")
        self.bud.queue(["demo_bench.FailingTest"], station.name)
        before = self.bud.run_ids()
        command = "bud-runner claim-run of a failing queued run"
        done = self._claim(case, station, "--workspace", case.cwd)
        runs = self._claimed_runs(station, before)
        support.exits(self, done, 1, command)
        statuses = [r["status"] for r in runs]
        support.check(
            self,
            statuses,
            ["Completed"],
            "Bud shows the failing claimed run finished: Completed",
            f"Bud shows the claimed runs with the statuses {statuses}",
        )

    def bud_the_commands_code_is_the_runs_own(self):
        """A queued run whose module is gone from the workspace: claim-run exits with run-tests'
        code, and Bud records it."""
        station, case = self._bench("gone-module")
        self.bud.queue(["demo_bench.VoltageTest"], station.name)
        (case.cwd / "demo_bench.py").unlink()
        before = self.bud.run_ids()
        command = "bud-runner claim-run of a run whose module is gone from the workspace"
        done = self._claim(case, station, "--workspace", case.cwd)
        run = self._one_run(station, before, command)
        support.check(
            self,
            done.code,
            run["runner_exit_code"],
            f"{command} exits {done.code}, the code Bud records for run {run['id']}",
            f"{command} exits {done.code}, Bud records {run['runner_exit_code']!r}",
        )
        support.says(
            self, f"Run {run['id']} finished with exit code {done.code}", done.out, command
        )
        support.exits(
            self,
            done,
            1,
            f"{command}, with run-tests' code for a selected class that cannot be imported,",
        )

    def bud_a_poller_does_not_exit_when_a_run_fails(self):
        """claim-run --interval 1 with a failing queued run: still running after Bud shows the run
        finished."""
        station, case = self._bench("poller")
        self.bud.queue(["demo_bench.FailingTest"], station.name)
        before = self.bud.run_ids()
        running = case.start(
            support.PYTHON,
            "-m",
            "bud_runner",
            "claim-run",
            "-u",
            station.name,
            "-b",
            station.backend,
            "--interval",
            "1",
            "--workspace",
            case.cwd,
        )
        try:
            finished = support.wait_for(
                lambda: any(
                    r["claim_acknowledged_at"] for r in self._claimed_runs(station, before)
                ),
                timeout=120,
                interval=1,
            )
            time.sleep(3)
            alive = running.alive()
        finally:
            running.stop()
        support.check(
            self,
            finished,
            True,
            "Bud shows the failing claimed run finished",
            "Bud does not show the failing claimed run finished within 120 s",
        )
        support.check(
            self,
            alive,
            True,
            "claim-run --interval 1 keeps polling 3 s after the failed run finished",
            "claim-run --interval 1 exited after the failed run",
        )

    def bud_an_executor_error_is_acknowledged_before_the_command_fails(self):
        """claim-run --workspace <missing dir>: exit 1, and Bud records the error with exit code
        1."""
        station, case = self._bench("missing-workspace")
        self.bud.queue(["demo_bench.VoltageTest"], station.name)
        before = self.bud.run_ids()
        command = "bud-runner claim-run --workspace <missing dir>"
        done = self._claim(case, station, "--workspace", case.cwd / "missing")
        support.exits(self, done, 1, command)
        run = self._one_run(station, before, command)
        support.check(
            self,
            run["runner_exit_code"],
            1,
            f"Bud records exit code 1 for run {run['id']}",
            f"Bud records exit code {run['runner_exit_code']!r} for run {run['id']}, not 1",
        )
        support.says(
            self,
            "FileNotFoundError",
            run["runner_error"] or "",
            f"the error Bud records for run {run['id']}",
        )

    def bud_polling_retries_the_answer_without_running_or_claiming_again(self):
        """+proxy refusing the first completion: the poller answers again, without a second claim or
        run."""
        station, case = self._bench("retry-answer")
        self.bud.queue(["demo_bench.VoltageTest"], station.name)
        refused = []

        def refuse_once(request):
            """Refuse the first completion with 400."""
            if request["path"].endswith("/complete") and not refused:
                refused.append(request)
                return 400, "try again"
            return None

        proxy = support.Proxy(refuse=refuse_once)
        before = self.bud.run_ids()
        running = case.start(
            support.PYTHON,
            "-m",
            "bud_runner",
            "claim-run",
            "-u",
            station.name,
            "-b",
            proxy.url,
            "--interval",
            "1",
            "--workspace",
            case.cwd,
        )
        try:
            done = support.wait_for(
                lambda: any(
                    r["claim_acknowledged_at"] for r in self._claimed_runs(station, before)
                ),
                timeout=120,
                interval=1,
            )
            time.sleep(2)
        finally:
            running.stop()
            proxy.close()
        support.check(
            self,
            done,
            True,
            "Bud records the second completion answer of the poller",
            "Bud records no completion answer within 120 s",
        )
        completions = len(proxy.seen("POST", "/api/runners/runs/"))
        support.check(
            self,
            completions,
            2,
            "the poller sends the completion twice: the refused one and the retry",
            f"the poller sent {completions} completion requests, not 2",
        )
        runs = len(self._claimed_runs(station, before))
        support.check(
            self,
            runs,
            1,
            "the retried answer claims no second run: Bud holds one run",
            f"Bud holds {runs} runs of {station.name} after the retried answer",
        )
        support.says(
            self,
            "⚠ Could not acknowledge run",
            running.err,
            "the poller after the refused completion",
        )
        claims = len(proxy.seen("POST", "/api/runners/claim-run"))
        support.check_less(
            self,
            0,
            claims,
            f"the poller sent {claims} claim requests through the proxy",
            "the poller sent no claim request through the proxy",
        )
        support.check(
            self,
            case.cwd.joinpath("VoltageTest.ran").exists(),
            True,
            "the claimed VoltageTest ran: VoltageTest.ran exists",
            "the claimed VoltageTest did not run: no VoltageTest.ran",
        )

    def bud_a_one_shot_claim_reports_a_failure(self):
        """claim-run against a closed port with a station token: exit 1."""
        command = "bud-runner claim-run against a closed port"
        done = support.Case("closed").bud_runner(
            "claim-run",
            "-b",
            f"http://127.0.0.1:{support.closed_port()}",
            env={"BUD_RUNNER_TOKEN": "station-token", "BUD_RUNNER_ACCOUNT": "station-99"},
            timeout=240,
        )
        support.exits(self, done, 1, command)
        support.says(self, "⚠ Could not claim a run", done.err, command)

    def bud_registration_is_required(self):
        """claim-run without a station token: exit 2 and the register hint."""
        command = "bud-runner claim-run without a station token"
        done = support.Case("unregistered").bud_runner("claim-run", "-b", self.bud.url)
        support.exits(self, done, 2, command)
        support.says(self, "Run 'bud_runner register'", done.err, command)
