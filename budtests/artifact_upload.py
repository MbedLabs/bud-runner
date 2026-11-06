"""Files run-tests uploads with a run: named with --artifact, found beside the run, and attached by
steps; what Bud stores."""

from pathlib import Path

import support
from budtestlibrary import BudTestCase

from bud_runner.cli import _display_name, _step_artifacts

SUITE = '''"""Suites whose steps leave and attach files."""

import os
from pathlib import Path

from budtestlibrary import BudTestCase


class PassTest(BudTestCase):
    """Attaches nothing."""

    def bud_passes(self):
        """Pass."""
        self.assertTrue(True, msg="ok")


class CaptureTest(BudTestCase):
    """Two steps, each attaching a file."""

    def bud_capture(self):
        """Attach a capture under a display name without its extension."""
        Path("traffic.pcap").write_bytes(b"pcap")
        self.attach_artifact("traffic.pcap", name="traffic capture")
        self.assertTrue(True, msg="captured")

    def bud_boot(self):
        """Attach a text file under its own name."""
        Path("boot.txt").write_text("boot")
        self.attach_artifact("boot.txt")
        self.assertTrue(True, msg="booted")


class OneCaptureTest(BudTestCase):
    """One step attaching traffic.pcap."""

    def bud_capture(self):
        """Attach the capture."""
        Path("traffic.pcap").write_bytes(b"pcap")
        self.attach_artifact("traffic.pcap")
        self.assertTrue(True, msg="captured")


class GoneTest(BudTestCase):
    """One step attaches a file it then deletes; another attaches a kept file."""

    def bud_gone(self):
        """Attach and delete."""
        Path("gone.log").write_text("gone")
        self.attach_artifact("gone.log")
        os.remove("gone.log")
        self.assertTrue(True, msg="gone")

    def bud_kept(self):
        """Attach a kept file."""
        Path("kept.log").write_text("kept")
        self.attach_artifact("kept.log")
        self.assertTrue(True, msg="kept")


class BigStepTest(BudTestCase):
    """Attaches a capture larger than Bud takes."""

    def bud_big(self):
        """Attach 300 kB."""
        Path("big.pcap").write_bytes(b"x" * 300_000)
        self.attach_artifact("big.pcap")
        self.assertTrue(True, msg="big")


class BenchTest(BudTestCase):
    """Attaches bench.log, which also lies beside the run."""

    def bud_bench(self):
        """Attach the bench log."""
        Path("bench.log").write_text("bench")
        self.attach_artifact("bench.log")
        self.assertTrue(True, msg="bench")


class NamesTest(BudTestCase):
    """Attaches files under a name with control characters and a 300-character name."""

    def bud_names(self):
        """Attach two captures."""
        Path("first.pcap").write_bytes(b"1")
        Path("second.pcap").write_bytes(b"2")
        self.attach_artifact("first.pcap", name="bad\\nname\\t")
        self.attach_artifact("second.pcap", name="x" * 300)
        self.assertTrue(True, msg="named")


PASS = ["demo_capture.PassTest"]
CAPTURE = ["demo_capture.CaptureTest"]
ONE_CAPTURE = ["demo_capture.OneCaptureTest"]
GONE = ["demo_capture.GoneTest"]
BIG_STEP = ["demo_capture.BigStepTest"]
BENCH = ["demo_capture.BenchTest"]
NAMES = ["demo_capture.NamesTest"]
'''

TOO_BIG = support.max_upload_bytes() + 1


def _has_test_case_field(request) -> bool:
    """Return whether a request is an upload that names a test case (a step artifact)."""
    return (
        request["method"] == "POST"
        and request["path"] == "/api/uploads"
        and b'name="test_case"' in request["body"]
    )


class ArtifactUpload(BudTestCase):
    """What lands on the run in Bud for each way a file reaches run-tests."""

    def setUpClass(self):
        self.bud = support.Bud()
        self.station = self.bud.station("artifacts")

    def _case(self, name, files=()):
        """Return a case with the capture suites and the given files in its working directory."""
        case = support.Case(name)
        case.write("demo_capture.py", SUITE)
        for relative, content in files:
            case.write(relative, content)
        return case

    def _run(self, case, test_list="PASS", *args, run=True):
        """Run run-tests as the station on a new run (or none) and return (outcome, run id)."""
        run_id = self.bud.create_run(self.station, f"Artifacts {case.root.name}") if run else None
        extra = ("--test-run-id", run_id) if run else ()
        return (
            case.run_tests(f"demo_capture.{test_list}", *extra, *args, station=self.station),
            run_id,
        )

    def _stored(self, run_id):
        """Return (name, test case) of each file uploaded to the run, in upload order."""
        return [
            (a["original_filename"], a["test_case"])
            for a in self.bud.artifacts(run_id)
            if not a["original_filename"].startswith(("bud-run-", "bud-suite-"))
        ]

    def names(self, run_id, expected: list, what: str) -> None:
        """Record the sorted names of the files Bud stores on a run."""
        names = sorted(n for n, _ in self._stored(run_id))
        support.check(
            self,
            names,
            expected,
            f"Bud stores {', '.join(expected) or 'no file'} on run {run_id}: {what}",
            f"Bud stores {names} on run {run_id}, not {expected}",
        )

    def stored(self, run_id, expected: list, what: str) -> None:
        """Record the (name, test case) pairs Bud stores on a run, in upload order."""
        stored = self._stored(run_id)
        support.check(
            self,
            stored,
            expected,
            f"Bud stores {expected} on run {run_id}: {what}",
            f"Bud stores {stored} on run {run_id}, not {expected}",
        )

    def bud_expands_a_glob(self):
        """-A "*.png" uploads exactly the matching files, with the report."""
        case = self._case(
            "glob", [("a.png", b"\x89PNG a"), ("b.png", b"\x89PNG b"), ("notes.txt", "notes")]
        )
        done, run_id = self._run(case, "PASS", "-A", "*.png")
        support.exits(self, done, 0, 'bud-runner run-tests -A "*.png"')
        self.names(
            run_id,
            ["a.png", "b.png", "report_junit.xml"],
            '-A "*.png" uploads the two PNG files and the report, not notes.txt',
        )

    def bud_warns_when_a_pattern_matches_nothing(self):
        """-A "*.png" with no match: the warning, exit 0, only the report on the run."""
        case = self._case("no-match")
        command = 'bud-runner run-tests -A "*.png" with no PNG file'
        done, run_id = self._run(case, "PASS", "-A", "*.png")
        support.exits(self, done, 0, command)
        support.says(self, "⚠ No artifact matched: *.png", done.err, command)
        self.stored(run_id, [("report_junit.xml", None)], "only the report")

    def bud_one_failure_does_not_stop_the_rest(self):
        """Two -A files, the first over Bud's size limit: the second is stored and the run exits
        0."""
        case = self._case("one-refused", [("huge.bin", b"x" * TOO_BIG), ("small.txt", "small")])
        command = "bud-runner run-tests -A huge.bin -A small.txt, huge.bin over Bud's size limit"
        done, run_id = self._run(case, "PASS", "-A", "huge.bin", "-A", "small.txt")
        support.exits(self, done, 0, command)
        support.says(self, "⚠ Could not upload huge.bin", done.err, command)
        self.names(
            run_id,
            ["report_junit.xml", "small.txt"],
            "the refused huge.bin does not stop small.txt",
        )

    def bud_run_tests_uploads_artifacts_after_the_results(self):
        """-A failure.png: the results, then the file, are on the run."""
        case = self._case("after-results", [("failure.png", b"\x89PNG f")])
        proxy = support.Proxy()
        command = "bud-runner run-tests -A failure.png"
        try:
            run_id = self.bud.create_run(self.station, "After results")
            done = case.run_tests(
                "demo_capture.PASS",
                "--test-run-id",
                run_id,
                "-A",
                "failure.png",
                station=self.station,
                backend=proxy.url,
            )
        finally:
            proxy.close()
        support.exits(self, done, 0, command)
        posts = [r["path"] for r in proxy.seen("POST")]
        sent = sorted({path for path in posts if path in ("/api/results", "/api/uploads")})
        support.need(
            self,
            sent,
            ["/api/results", "/api/uploads"],
            f"{command} sends both the results and the uploads",
            f"{command} sent the POSTs {posts}",
        )
        order = [path for path in posts if path in ("/api/results", "/api/uploads")]
        support.check(
            self,
            order[0],
            "/api/results",
            f"{command} sends the results before any file",
            f"{command} sends a file before the results: {order}",
        )
        support.check_in(
            self,
            ("failure.png", None),
            self._stored(run_id),
            f"Bud stores failure.png on run {run_id}",
            f"Bud does not store failure.png on run {run_id}: {self._stored(run_id)}",
        )
        count = len(self.bud.results(run_id))
        support.check(
            self,
            count,
            1,
            f"Bud stores the one result on run {run_id}",
            f"Bud stores {count} results on run {run_id}, not 1",
        )

    def bud_the_report_is_uploaded_without_being_asked_for(self):
        """--format junit with a run: the JUnit report is an artifact of the run."""
        case = self._case("report")
        done, run_id = self._run(case, "PASS", "--format", "junit")
        self.stored(
            run_id,
            [("report_junit.xml", None)],
            "run-tests --format junit uploads its report unasked",
        )

    def bud_run_tests_needs_a_test_run_id(self):
        """-A without --test-run-id: the warning, and the run Bud created holds no file."""
        case = self._case("needs-run", [("notes.txt", "notes")])
        before = self.bud.run_ids()
        command = "bud-runner run-tests -A notes.txt without --test-run-id"
        done, _ = self._run(case, "PASS", "-A", "notes.txt", run=False)
        support.says(self, "⚠ Artifacts need a test run: pass --test-run-id.", done.err, command)
        new = self.bud.new_run_ids(before)
        support.need(
            self,
            len(new),
            1,
            f"{command} makes Bud create one run",
            f"{command} made Bud create the runs {new}, not one",
        )
        self.stored(new[0], [], "no file reaches the run Bud created")

    def bud_a_failed_artifact_does_not_fail_the_run(self):
        """-A a file Bud refuses for its size: exit 0 and the warning."""
        case = self._case("refused", [("huge.bin", b"x" * TOO_BIG)])
        command = "bud-runner run-tests -A huge.bin over Bud's size limit"
        done, run_id = self._run(case, "PASS", "-A", "huge.bin")
        support.exits(self, done, 0, command)
        support.says(self, "⚠ Could not upload huge.bin", done.err, command)
        support.check_not_in(
            self,
            "huge.bin",
            [n for n, _ in self._stored(run_id)],
            f"Bud does not store huge.bin on run {run_id}",
            f"Bud stores huge.bin on run {run_id} although it is over the size limit",
        )

    def bud_discovers_logs_beside_the_run(self):
        """bench.log and stderr.err beside the run are stored, notes.md is not."""
        case = self._case(
            "logs", [("bench.log", "bench"), ("stderr.err", "err"), ("notes.md", "notes")]
        )
        done, run_id = self._run(case)
        self.names(
            run_id,
            ["bench.log", "report_junit.xml", "stderr.err"],
            "the two logs beside the run and the report, not notes.md",
        )

    def bud_discovers_packet_captures(self):
        """can.pcapng and bus.trace beside the run are stored."""
        case = self._case("captures", [("can.pcapng", b"pcapng"), ("bus.trace", "trace")])
        done, run_id = self._run(case)
        self.names(
            run_id,
            ["bus.trace", "can.pcapng", "report_junit.xml"],
            "both captures beside the run and the report",
        )

    def bud_takes_everything_in_the_artifact_directory(self):
        """Every file under bud-artifacts/, nested ones included, is stored."""
        case = self._case(
            "artifact-dir",
            [("bud-artifacts/plot.png", b"\x89PNG p"), ("bud-artifacts/deep/raw.csv", "a,b")],
        )
        done, run_id = self._run(case)
        self.names(
            run_id,
            ["plot.png", "raw.csv", "report_junit.xml"],
            "every file under bud-artifacts/, nested ones included, and the report",
        )

    def bud_finds_nothing_when_the_run_left_nothing(self):
        """An empty working directory: only the report is stored."""
        case = self._case("nothing")
        done, run_id = self._run(case)
        self.stored(
            run_id, [("report_junit.xml", None)], "a run that left nothing uploads only its report"
        )

    def bud_never_walks_the_workspace(self):
        """Logs and traces in subdirectories other than bud-artifacts/ are not stored."""
        case = self._case(
            "no-walk",
            [("node_modules/pkg/install.log", "install"), ("vendor/debug.trace", "trace")],
        )
        done, run_id = self._run(case)
        self.stored(
            run_id,
            [("report_junit.xml", None)],
            "logs and traces in other subdirectories are not uploaded",
        )

    def bud_a_run_sends_its_report_and_what_it_left(self):
        """The report, bench.log and a bud-artifacts file are all stored."""
        case = self._case(
            "everything", [("bench.log", "bench"), ("bud-artifacts/plot.png", b"\x89PNG p")]
        )
        done, run_id = self._run(case)
        self.names(
            run_id,
            ["bench.log", "plot.png", "report_junit.xml"],
            "the report, the log beside the run and the bud-artifacts file",
        )

    def bud_the_report_is_not_sent_twice_when_named_explicitly(self):
        """-A report_junit.xml: the run holds one report."""
        case = self._case("report-once")
        done, run_id = self._run(case, "PASS", "-A", "report_junit.xml")
        count = [n for n, _ in self._stored(run_id)].count("report_junit.xml")
        support.check(
            self,
            count,
            1,
            f"with -A report_junit.xml Bud stores the report once on run {run_id}",
            f"with -A report_junit.xml Bud stores the report {count} times on run {run_id}",
        )

    def bud_a_discovered_file_that_will_not_upload_does_not_fail_the_run(self):
        """A capture beside the run over Bud's size limit: exit 0 and the warning."""
        case = self._case("big-capture", [("huge.pcap", b"x" * TOO_BIG)])
        command = "bud-runner run-tests with huge.pcap over Bud's size limit beside the run"
        done, run_id = self._run(case)
        support.exits(self, done, 0, command)
        support.says(self, "⚠ Could not upload huge.pcap", done.err, command)

    def bud_files_a_step_attached_are_uploaded_with_their_step(self):
        """Each attached file is stored under its step with its display name, before the report."""
        case = self._case("steps")
        command = "bud-runner run-tests of CaptureTest, whose steps attach files"
        done, run_id = self._run(case, "CAPTURE")
        support.exits(self, done, 0, command)
        self.stored(
            run_id,
            [
                ("traffic capture.pcap", "CaptureTest.bud_capture"),
                ("boot.txt", "CaptureTest.bud_boot"),
                ("report_junit.xml", None),
            ],
            "each step file under its step with its display name, then the report",
        )
        support.says(
            self,
            "✓ Uploaded step artifact: traffic capture.pcap (CaptureTest.bud_capture)",
            done.out,
            command,
        )

    def bud_step_artifacts_go_to_the_run_bud_created(self):
        """Without --test-run-id the step file goes to the run Bud created, and -A is warned
        about."""
        case = self._case("steps-new-run")
        before = self.bud.run_ids()
        command = "bud-runner run-tests -A traffic.pcap of OneCaptureTest without --test-run-id"
        done, _ = self._run(case, "ONE_CAPTURE", "-A", "traffic.pcap", run=False)
        support.exits(self, done, 0, command)
        support.says(self, "Artifacts need a test run", done.err, command)
        new = self.bud.new_run_ids(before)
        support.need(
            self,
            len(new),
            1,
            f"{command} makes Bud create one run",
            f"{command} made Bud create the runs {new}, not one",
        )
        self.stored(
            new[0],
            [("traffic.pcap", "OneCaptureTest.bud_capture")],
            "the step file goes once to the run Bud created",
        )

    def bud_step_artifacts_without_any_run_are_reported(self):
        """+proxy: when the results answer names no run, the step files are reported as not
        uploaded."""
        case = self._case("steps-no-run")
        proxy = support.Proxy(
            rewrite=lambda request, status, data: (
                b"OK" if request["path"] == "/api/results" else None
            )
        )
        command = "bud-runner run-tests of OneCaptureTest when the results answer names no run"
        try:
            case.give_station(self.station)
            done = case.bud_runner(
                "run-tests",
                "-t",
                "demo_capture.ONE_CAPTURE",
                "-b",
                proxy.url,
                "-u",
                self.station.name,
            )
        finally:
            proxy.close()
        support.exits(self, done, 0, command)
        support.says(self, "⚠ Step artifacts need a test run: 1 not uploaded.", done.err, command)
        uploads = len(proxy.seen("POST", "/api/uploads"))
        support.check(
            self,
            uploads,
            0,
            f"{command} sends no file",
            f"{command} sent {uploads} file uploads",
        )

    def bud_a_missing_step_artifact_is_warned_and_skipped(self):
        """A step file deleted after it was attached is warned about; only the kept file is
        stored."""
        case = self._case("steps-gone")
        command = "bud-runner run-tests of GoneTest, whose attached gone.log is deleted"
        done, run_id = self._run(case, "GONE")
        support.exits(self, done, 0, command)
        support.says(
            self,
            f"⚠ Step artifact not found: {case.cwd.resolve() / 'gone.log'} (GoneTest.bud_gone)",
            done.err,
            command,
        )
        self.stored(
            run_id,
            [("kept.log", "GoneTest.bud_kept"), ("report_junit.xml", None)],
            "only the kept file, once, under its step, then the report",
        )

    def bud_a_step_artifact_that_fails_to_upload_does_not_fail_the_run(self):
        """A step file over Bud's size limit: exit 0 and the warning."""
        case = self._case("steps-big")
        command = "bud-runner run-tests of BigStepTest, whose step attaches a file over the limit"
        done, run_id = self._run(case, "BIG_STEP")
        support.exits(self, done, 0, command)
        support.says(self, "⚠ Could not upload", done.err, command)
        support.check_not_in(
            self,
            "big.pcap",
            [n for n, _ in self._stored(run_id)],
            f"Bud does not store big.pcap on run {run_id}",
            f"Bud stores big.pcap on run {run_id} although it is over the size limit",
        )

    def bud_a_found_file_whose_step_upload_failed_still_goes_up_once(self):
        """+proxy refusing step uploads: bench.log, attached and found beside the run, is stored
        once as a plain artifact."""
        case = self._case("steps-refused")
        proxy = support.Proxy(
            refuse=lambda request: (507, "storage full") if _has_test_case_field(request) else None
        )
        command = "bud-runner run-tests of BenchTest with step uploads refused"
        try:
            run_id = self.bud.create_run(self.station, "Step refused")
            done = case.run_tests(
                "demo_capture.BENCH",
                "--test-run-id",
                run_id,
                station=self.station,
                backend=proxy.url,
            )
        finally:
            proxy.close()
        support.exits(self, done, 0, command)
        support.says(self, "⚠ Could not upload", done.err, command)
        bench = [s for s in self._stored(run_id) if s[0] == "bench.log"]
        support.check(
            self,
            bench,
            [("bench.log", None)],
            "bench.log, whose step upload was refused, is stored once as a plain artifact",
            f"bench.log is stored as {bench}",
        )

    def bud_a_file_both_found_and_attached_goes_up_once_with_its_step(self):
        """bench.log attached by a step and lying beside the run is stored once, under its step."""
        case = self._case("steps-once")
        done, run_id = self._run(case, "BENCH")
        bench = [s for s in self._stored(run_id) if s[0] == "bench.log"]
        support.check(
            self,
            bench,
            [("bench.log", "BenchTest.bud_bench")],
            "bench.log, attached by a step and lying beside the run, is stored once under its step",
            f"bench.log is stored as {bench}",
        )

    def bud_nothing_is_sent_without_upload(self):
        """--no-upload --test-run-id N: the run holds no result and no file."""
        case = self._case("no-upload", [("bench.log", "bench")])
        command = "bud-runner run-tests --no-upload --test-run-id N"
        done, run_id = self._run(case, "ONE_CAPTURE", "--no-upload")
        support.exits(self, done, 0, command)
        results = self.bud.results(run_id)
        support.check(
            self,
            len(results),
            0,
            f"{command} sends no result to run {run_id}",
            f"{command} sent {len(results)} results to run {run_id}",
        )
        artifacts = [a["original_filename"] for a in self.bud.artifacts(run_id)]
        support.check(
            self,
            artifacts,
            [],
            f"{command} sends no file to run {run_id}",
            f"{command} sent the files {artifacts} to run {run_id}",
        )

    def bud_display_names_and_the_step_list(self):
        """In-process name rules, and Bud's stored names for a step attaching "bad\\nname\\t" and a
        300-character name."""
        pcap = Path("/data/traffic.pcap")
        for name, path, expected, rule in [
            ("traffic capture", pcap, "traffic capture.pcap", "the file's extension is added"),
            ("capture v1.2", pcap, "capture v1.2.pcap", "a dotted name still gets the extension"),
            ("traffic.PCAP", pcap, "traffic.PCAP", "the extension in another case is kept"),
            ("bad\nname\t", pcap, "badname.pcap", "control characters are removed"),
            (None, pcap, "traffic.pcap", "no name gives the file name"),
            ("", Path("/data/notes"), "notes", "no name and no extension give the bare file name"),
        ]:
            got = _display_name(name, path)
            support.check(
                self,
                got,
                expected,
                f"_display_name({name!r}, {path.name}) gives {expected!r}: {rule}",
                f"_display_name({name!r}, {path.name}) gives {got!r}, not {expected!r}",
            )
        long = _display_name("x" * 300, pcap)
        shape = {"length": len(long), "ending": long[-5:]}
        support.check(
            self,
            shape,
            {"length": 255, "ending": ".pcap"},
            "a 300-character name is cut to 255 characters ending with .pcap",
            f"a 300-character name becomes {shape}",
        )
        rows = [
            {
                "test_class": "CaptureTest",
                "method_results": [
                    {
                        "method_name": "bud_a",
                        "passed": True,
                        "metadata": {
                            "artifacts": [
                                {"path": "/data/a.log", "name": "a.log"},
                                {"name": "no path"},
                                "not a dict",
                            ]
                        },
                    },
                    {
                        "method_name": "bud_b",
                        "passed": True,
                        "metadata": {
                            "artifacts": [
                                {"path": "/data/a.log", "name": "again"},
                                {"path": "/data/b.log"},
                            ]
                        },
                    },
                ],
            }
        ]
        listed = [(p.name, n, t) for p, n, t in _step_artifacts(rows)]
        support.check(
            self,
            listed,
            [("a.log", "a.log", "CaptureTest.bud_a"), ("b.log", "b.log", "CaptureTest.bud_b")],
            "_step_artifacts skips entries without a path and lists a.log once, under its first "
            "step",
            f"_step_artifacts lists {listed}",
        )
        tabbed = _step_artifacts(
            [
                {
                    "test_class": "CaptureTest",
                    "method_results": [
                        {
                            "method_name": "bud_value[a\tb]",
                            "passed": True,
                            "metadata": {"artifacts": [{"path": "/data/c.log"}]},
                        }
                    ],
                }
            ]
        )
        support.check(
            self,
            tabbed[0][2],
            "CaptureTest.bud_value[ab]",
            "control characters are removed from the test case CaptureTest.bud_value[a\\tb]",
            f"the test case of bud_value[a\\tb] becomes {tabbed[0][2]!r}",
        )
        case = self._case("names")
        done, run_id = self._run(case, "NAMES")
        stored = [n for n, t in self._stored(run_id) if t]
        support.check(
            self,
            stored,
            ["badname.pcap", "x" * 250 + ".pcap"],
            "Bud stores the cleaned name badname.pcap and the 255-character shortened name",
            f"Bud stores the step file names {stored}",
        )
