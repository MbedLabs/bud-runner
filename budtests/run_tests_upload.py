"""What run-tests leaves in Bud after the upload: run totals, the 401 refresh, the software
metadata, spooling and replay."""

import json

import support
from budtestlibrary import BudTestCase

SUITE = '''"""A class of three passing steps and a class with a failing step."""

from budtestlibrary import BudTestCase


class ThreeStepsTest(BudTestCase):
    """Three passing steps."""

    def bud_a(self):
        """Pass."""
        self.assertTrue(True, msg="a")

    def bud_b(self):
        """Pass."""
        self.assertTrue(True, msg="b")

    def bud_c(self):
        """Pass."""
        self.assertTrue(True, msg="c")


class MixedTest(BudTestCase):
    """A passing and a failing step."""

    def bud_ok(self):
        """Pass."""
        self.assertTrue(True, msg="ok")

    def bud_fails(self):
        """Fail."""
        self.assertEqual(1, 2, msg="fails")


THREE = ["demo_upload.ThreeStepsTest"]
MIXED = ["demo_upload.MixedTest"]
'''


class RunTestsUpload(BudTestCase):
    """Run totals Bud keeps, the refresh after a 401, the software fields of a run Bud creates,
    spool and replay."""

    def setUpClass(self):
        self.bud = support.Bud()
        self.station = self.bud.station("upload")
        self.spool_case = None

    def _case(self, name):
        """Return a case with the upload suites in its working directory."""
        case = support.Case(name)
        case.write("demo_upload.py", SUITE)
        return case

    def bud_run_tests_post_upload_patch_omits_counter_fields(self):
        """One class of three passing steps: Bud's run shows 1 test case, 1 passed, Completed."""
        case = self._case("totals")
        run_id = self.bud.create_run(self.station, "Totals")
        command = f"bud-runner run-tests --test-run-id {run_id} of one class of three passing steps"
        done = case.run_tests("demo_upload.THREE", "--test-run-id", run_id, station=self.station)
        support.exits(self, done, 0, command)
        run = self.bud.run(run_id)
        totals = {k: run[k] for k in ("total_tests", "passed_tests", "failed_tests", "status")}
        support.check(
            self,
            totals,
            {"total_tests": 1, "passed_tests": 1, "failed_tests": 0, "status": "Completed"},
            f"Bud shows run {run_id} Completed with 1 test case, 1 passed, 0 failed",
            f"Bud shows run {run_id} as {totals}",
        )
        count = len(self.bud.results(run_id))
        support.check(
            self,
            count,
            3,
            f"Bud stores the three step results on run {run_id}",
            f"Bud stores {count} step results on run {run_id}, not 3",
        )

    def bud_run_tests_post_upload_still_omits_counters_when_suite_failed(self):
        """One class with a failing step: exit 1, Bud's run shows 1 test case, 1 failed."""
        case = self._case("totals-failed")
        run_id = self.bud.create_run(self.station, "Totals failed")
        command = f"bud-runner run-tests --test-run-id {run_id} of one class with a failing step"
        done = case.run_tests("demo_upload.MIXED", "--test-run-id", run_id, station=self.station)
        support.exits(self, done, 1, command)
        run = self.bud.run(run_id)
        totals = {k: run[k] for k in ("total_tests", "passed_tests", "failed_tests")}
        support.check(
            self,
            totals,
            {"total_tests": 1, "passed_tests": 0, "failed_tests": 1},
            f"Bud shows run {run_id} with 1 test case, 0 passed, 1 failed",
            f"Bud shows run {run_id} with {totals}",
        )

    def bud_run_tests_exits_with_a_clear_error_when_bud_rejects_the_station_token(self):
        """A station token Bud rejects, with --username/--password of a Bud user: no user sign-in
        and no retry with user credentials; run-tests exits 1 saying the station token was
        rejected."""
        case = self._case("reauth")
        proxy = support.Proxy()
        command = "bud-runner run-tests --username/--password with a station token Bud rejects"
        try:
            done = case.bud_runner(
                "run-tests",
                "-t",
                "demo_upload.THREE",
                "-b",
                proxy.url,
                "--username",
                support.setting("ADMIN_EMAIL"),
                "--password",
                support.setting("ADMIN_PASSWORD"),
                env={
                    "BUD_RUNNER_TOKEN": "rejected-station-token",
                    "BUD_RUNNER_ACCOUNT": self.station.name,
                },
            )
        finally:
            proxy.close()
        logins = len(proxy.seen("POST", "/api/auth/login"))
        support.check(
            self,
            logins,
            0,
            f"{command} does not sign the user in after the 401: results are never sent as a user",
            f"{command} sent {logins} user sign-ins after the 401",
        )
        uploads = len(proxy.seen("POST", "/api/results"))
        support.check(
            self,
            uploads,
            1,
            f"{command} sends the result upload once and does not retry it with other credentials",
            f"{command} sent {uploads} result uploads, not the one Bud rejected",
        )
        support.exits(self, done, 1, f"{command}, whose station token Bud rejects,")
        support.says(
            self,
            "station token rejected",
            (done.out + done.err).lower(),
            f"{command}, in a clear error,",
        )

    def bud_run_tests_forwards_the_software_metadata(self):
        """run-tests without --test-run-id and the four software options: the run Bud creates
        carries them."""
        case = self._case("software")
        before = self.bud.run_ids()
        command = "bud-runner run-tests with the four software options and no --test-run-id"
        done = case.run_tests(
            "demo_upload.THREE",
            "--url-test-software",
            "https://example.com/test-suite",
            "--ref-test-software",
            "tests-abc123",
            "--sw-under-test",
            "https://example.com/firmware",
            "--ref-sw-under-test",
            "fw-abc123",
            station=self.station,
        )
        support.exits(self, done, 0, command)
        new = self.bud.new_run_ids(before)
        support.need(
            self,
            len(new),
            1,
            f"{command} makes Bud create one run",
            f"{command} made Bud create the runs {new}, not one",
        )
        run = self.bud.run(new[0])
        fields = (
            "url_test_software",
            "ref_test_software",
            "url_software_under_test",
            "ref_software_under_test",
        )
        stored = {k: run[k] for k in fields}
        support.check(
            self,
            stored,
            {
                "url_test_software": "https://example.com/test-suite",
                "ref_test_software": "tests-abc123",
                "url_software_under_test": "https://example.com/firmware",
                "ref_software_under_test": "fw-abc123",
            },
            f"the run Bud creates carries the four software values given to {command}",
            f"the run Bud creates carries the software values {stored}",
        )

    def bud_run_tests_spools_payload_when_upload_fails(self):
        """Bud unreachable: exit 1, one spooled payload in the HOME, and the message."""
        case = self._case("spool")
        case.give_station(self.station)
        command = "bud-runner run-tests against a closed port"
        done = case.bud_runner(
            "run-tests",
            "-t",
            "demo_upload.THREE",
            "-b",
            f"http://127.0.0.1:{support.closed_port()}",
            "-u",
            self.station.name,
            timeout=240,
        )
        support.exits(self, done, 1, command)
        support.says(self, "Payload spooled to", done.err, command)
        spooled = case.spooled()
        support.need(
            self,
            len(spooled),
            1,
            f"{command} spools one result payload under the case HOME",
            f"{command} spooled {len(spooled)} payloads: {[p.name for p in spooled]}",
        )
        classes = sorted({r["test_class"] for r in json.loads(spooled[0].read_text())["results"]})
        support.check(
            self,
            classes,
            ["ThreeStepsTest"],
            "the spooled payload holds the results of ThreeStepsTest, the class the run executed",
            f"the spooled payload holds the results of {classes}",
        )
        self.spool_case = case

    def bud_run_tests_replays_spooled_payload_before_current_upload(self):
        """The next run-tests against Bud replays the spooled run first, then uploads its own; the
        spool is empty."""
        case = self.spool_case
        support.need(
            self,
            case is not None,
            True,
            "the spool case ran first and left a spooled payload",
            "the spool case did not finish, so there is no spooled payload to replay",
        )
        case.write("demo_upload.py", SUITE)
        proxy = support.Proxy()
        before = self.bud.run_ids()
        command = "the next bud-runner run-tests against Bud"
        try:
            done = case.run_tests("demo_upload.MIXED", station=self.station, backend=proxy.url)
        finally:
            proxy.close()
        support.says(self, "✓ Replayed spooled results from", done.out, command)
        bodies = [json.loads(r["body"]) for r in proxy.seen("POST", "/api/results")]
        sent = [sorted({r["test_class"] for r in b["results"]}) for b in bodies]
        support.check(
            self,
            sent,
            [["ThreeStepsTest"], ["MixedTest"]],
            f"{command} uploads the spooled ThreeStepsTest run first, then its own MixedTest run",
            f"{command} uploads the result sets {sent} in that order",
        )
        new = self.bud.new_run_ids(before)
        stored = [sorted({r["test_class"] for r in self.bud.results(i)}) for i in new]
        support.check(
            self,
            stored,
            [["ThreeStepsTest"], ["MixedTest"]],
            "Bud holds both runs, the replayed ThreeStepsTest run first",
            f"Bud holds the new runs with the result classes {stored}",
        )
        left = [p.name for p in case.spooled()]
        support.check(
            self,
            left,
            [],
            "the spool is empty after the replay",
            f"the spool still holds {left} after the replay",
        )
