"""import-cucumber: reports of cucumber-js, Cucumber-JVM and Cucumber-Ruby imported into Bud,
refusals, spooling."""

import json
import re

import support
from budtestlibrary import BudTestCase, parameterized

from bud_runner.cucumber_importer import CucumberReport, error_text, feature_path, read_report

RUNNERS = ("cucumber-js.json", "cucumber-jvm.json", "cucumber-ruby.json")
UPLOADED = re.compile(r"Cucumber results uploaded to Bud run (\d+)")


def _shape(results):
    """Return the comparable shape of stored results."""
    return [
        (
            r["test_class"],
            r["test_method"],
            r["passed"],
            r["test_metadata"]["cucumber_status"],
            r["test_metadata"].get("tc_id"),
            [
                (a["assertion_type"], a["passed"], bool(a.get("info")), bool(a["skipped"]))
                for a in r["assertions"] or []
            ],
        )
        for r in results
    ]


class CucumberImporter(BudTestCase):
    """What Bud stores for each runner's report and the edge cases, the run fields, the refusals
    and the spool."""

    def setUpClass(self):
        self.bud = support.Bud()
        self.station = self.bud.station("cucumber")
        self.product = self.bud.product("Demo")

    def _case(self, name, properties=""):
        """Return a case of the station, with its account (and more) in app.properties."""
        case = support.Case(name)
        case.give_station(self.station)
        case.write("app.properties", f"budRunnerAccount={self.station.name}\n{properties}")
        return case

    def _import(self, case, report, *args):
        """Run import-cucumber against Bud and return (outcome, run id or None)."""
        done = case.bud_runner("import-cucumber", "--report", report, "-b", self.bud.url, *args)
        found = UPLOADED.search(done.err)
        return done, int(found.group(1)) if found else None

    def _imported(self, name, fixture, *args):
        """Import a fixture report and return (outcome, run id, results by scenario)."""
        case = self._case(name)
        support.copy_fixture(case, fixture)
        done, run_id = self._import(case, fixture, *args)
        if run_id is None:
            raise RuntimeError(f"the import did not reach Bud: {done!r}")
        return done, run_id, {r["test_method"]: r for r in self.bud.results(run_id)}

    def same(self, actual, expected, passed: str, failed_what: str) -> bool:
        """Record actual against expected; the failure names what was stored instead."""
        return support.check(
            self, actual, expected, passed, f"{failed_what}: {actual!r}, not {expected!r}"
        )

    def bud_the_three_runners_give_the_same_bud_results(self):
        """Each runner's report imported into its own run: Bud holds the same results in the same
        order."""
        shapes = []
        for fixture in RUNNERS:
            _, run_id, _ = self._imported("three", fixture)
            shapes.append(_shape(self.bud.results(run_id)))
        for index, runner in ((1, "Cucumber-JVM"), (2, "Cucumber-Ruby")):
            support.check(
                self,
                shapes[index],
                shapes[0],
                f"Bud stores the {runner} report exactly as the cucumber-js report: same "
                "scenarios, "
                "outcomes, statuses, test cases and step entries",
                f"Bud stores the {runner} report differently from the cucumber-js report",
            )
        self.same(
            [row[1] for row in shapes[0]],
            [
                "Voltage within limit",
                "Wrong value",
                "Step raises",
                "Missing step",
                "Hook fails",
                "Pending step",
                "Outline 1",
                "Outline 2",
            ],
            "Bud stores the eight scenarios in the report's order",
            "Bud stores the scenarios in the order",
        )

    @parameterized(list(RUNNERS))
    def bud_a_cucumber_run_maps_to_bud_results(self, fixture):
        """The summary line and the stored "Voltage within limit" result of each runner."""
        command = f"bud-runner import-cucumber --report {fixture}"
        done, run_id, results = self._imported("map", fixture)
        support.exits(self, done, 0, command)
        support.says(
            self,
            f"Cucumber report {fixture}: 1 features, 8 scenarios (3 passed, 5 failed, 0 skipped)",
            done.out,
            command,
        )
        self.same(
            sorted({r["test_class"] for r in results.values()}),
            ["Bench supply"],
            "every stored scenario has the feature Bench supply as its test case",
            "the stored scenarios have the test cases",
        )
        measured = results["Voltage within limit"]
        self.same(
            {"passed": measured["passed"], "error_message": measured["error_message"]},
            {"passed": True, "error_message": None},
            f"Voltage within limit from {fixture} is stored as passed without error",
            f"Voltage within limit from {fixture} is stored with",
        )
        metadata = measured["test_metadata"]
        self.same(
            {"tc_id": metadata["tc_id"], "cucumber_tags": metadata["cucumber_tags"]},
            {"tc_id": "PRJ-TC-001", "cucumber_tags": ["bloom:PRJ-001", "smoke", "suite-tag"]},
            "Voltage within limit carries test case PRJ-TC-001 from its bloom:PRJ-001 tag, and its "
            "three tags",
            "Voltage within limit carries",
        )
        location = metadata["location"]
        self.same(
            location[-len("features/bench.feature:7") :],
            "features/bench.feature:7",
            f"Voltage within limit carries its location {location}, line 7 of "
            "features/bench.feature",
            "Voltage within limit carries a location ending in",
        )
        for key in ("test_case_file", "skipped"):
            support.check_not_in(
                self,
                key,
                metadata,
                f"the stored metadata of Voltage within limit has no {key}",
                f"the stored metadata of Voltage within limit has {key}={metadata.get(key)!r}",
            )
        steps = [
            (a["assertion_type"], a["passed"], bool(a.get("info"))) for a in measured["assertions"]
        ]
        self.same(
            steps,
            [
                ("a bench", True, True),
                ("I measure 3", True, True),
                ("the value is 3", True, False),
                ("the value is below 5", True, False),
            ],
            "Given and When steps are information entries, Then and And steps are checks",
            "Voltage within limit stores the step entries",
        )
        check = measured["assertions"][3]
        self.same(
            {k: check[k] for k in ("code_context", "source_line", "source_function")},
            {
                "code_context": "And the value is below 5",
                "source_line": 10,
                "source_function": "Voltage within limit",
            },
            "the last check carries its code, line 10 and its scenario",
            "the last check carries",
        )
        support.check_less(
            self,
            -1,
            measured["duration_seconds"],
            f"Voltage within limit is stored with a duration of {measured['duration_seconds']} s",
            f"Voltage within limit is stored with the duration {measured['duration_seconds']!r}",
        )

    @parameterized(
        [
            (
                "cucumber-js.json",
                "AssertionError [ERR_ASSERTION]\n    + expected - actual\n\n    -2\n    +3",
            ),
            ("cucumber-jvm.json", "java.lang.AssertionError: expected 3"),
            ("cucumber-ruby.json", "expected 3 (RuntimeError)"),
        ]
    )
    def bud_failures_carry_the_runner_message_and_stack_trace(self, fixture, message):
        """Bud stores each runner's failure message and stack trace, raised, undefined, pending and
        hook failures."""
        _, _, results = self._imported("failures", fixture)
        wrong = results["Wrong value"]
        failed = wrong["assertions"][2]
        self.same(
            {k: failed[k] for k in ("assertion_type", "passed", "message")},
            {"assertion_type": "the value is 3", "passed": False, "message": message},
            f"the failed Then step of Wrong value carries the {fixture} message",
            "the failed Then step of Wrong value is stored as",
        )
        self.same(
            wrong["error_message"],
            message,
            f"the error of Wrong value is the {fixture} message",
            "the error of Wrong value is",
        )
        first = message.split("\n")[0]
        self.same(
            failed["traceback"][: len(first)],
            first,
            f"the stack trace of the failed step starts with the message {first!r}",
            "the stack trace of the failed step starts with",
        )
        support.check_less(
            self,
            len(message),
            len(failed["traceback"]),
            f"the stack trace ({len(failed['traceback'])} characters) holds more than the message",
            f"the stack trace ({len(failed['traceback'])} characters) holds no more than the "
            "message",
        )
        support.check(
            self,
            wrong["traceback"],
            failed["traceback"],
            "the traceback of Wrong value is its failed step's stack trace",
            "the traceback of Wrong value differs from its failed step's stack trace",
        )
        raised = results["Step raises"]
        self.same(
            {k: raised["assertions"][1][k] for k in ("passed", "info")},
            {"passed": False, "info": True},
            "a raising When step is a failed information entry",
            "the raising When step is stored as",
        )
        support.says(self, "bad value", raised["error_message"], "the error of Step raises")
        missing = results["Missing step"]
        self.same(
            {
                "error_message": missing["error_message"],
                "status": missing["test_metadata"]["cucumber_status"],
            },
            {"error_message": "Undefined step: When nobody wrote this", "status": "undefined"},
            "Missing step is stored as undefined with Undefined step: When nobody wrote this",
            "Missing step is stored with",
        )
        pending = results["Pending step"]
        self.same(
            {"passed": pending["passed"], "status": pending["test_metadata"]["cucumber_status"]},
            {"passed": False, "status": "pending"},
            "Pending step is stored as failed with status pending",
            "Pending step is stored with",
        )
        hook = results["Hook fails"]
        self.same(
            [(a["assertion_type"], a["passed"]) for a in hook["assertions"]],
            [("HookError", False)],
            "Hook fails holds one failed HookError entry",
            "Hook fails holds the entries",
        )
        support.says(self, "hook broke", hook["error_message"], "the error of Hook fails")
        support.check_match(
            self,
            r"\S",
            hook["traceback"] or "",
            "Hook fails carries the hook's stack trace",
            "Hook fails carries no stack trace",
        )

    def bud_edge_cases_from_a_real_cucumber_js_report(self):
        """Tags, ambiguous steps, After hooks, skips, duplicate names and German keywords as Bud
        stores them."""
        command = "bud-runner import-cucumber --report cucumber-js-edges.json"
        done, run_id, results = self._imported("edges", "cucumber-js-edges.json")
        support.says(
            self,
            "Cucumber report cucumber-js-edges.json: 2 features, 9 scenarios (5 passed, 2 failed, "
            "2 skipped)",
            done.out,
            command,
        )
        own = results["Own tag wins"]["test_metadata"]
        self.same(
            {"tc_id": own["tc_id"], "cucumber_tags": own["cucumber_tags"]},
            {"tc_id": "PRJ-TC-002", "cucumber_tags": ["bloom:PRJ-002", "bloom:PRJ-009"]},
            "the scenario's own tag bloom:PRJ-002 wins over the feature tag, and both tags are "
            "kept",
            "Own tag wins carries",
        )
        self.same(
            results["Feature tag only"]["test_metadata"]["tc_id"],
            "PRJ-TC-009",
            "a scenario without its own tag takes PRJ-TC-009 from the feature tag",
            "Feature tag only carries the test case",
        )
        ambiguous = results["Ambiguous step"]
        self.same(
            {"passed": ambiguous["passed"], "error_message": ambiguous["error_message"]},
            {"passed": False, "error_message": "Ambiguous step: When I do twice"},
            "Ambiguous step is stored as failed with Ambiguous step: When I do twice",
            "Ambiguous step is stored with",
        )
        after = results["After hook fails"]
        self.same(
            {
                "passed": after["passed"],
                "error_message": after["error_message"],
                "entries": [(a["assertion_type"], a["passed"]) for a in after["assertions"]],
            },
            {
                "passed": False,
                "error_message": "Error: after broke",
                "entries": [("a bench", True), ("HookError", False)],
            },
            "After hook fails is failed with Error: after broke and a HookError entry after its "
            "step",
            "After hook fails is stored with",
        )
        for name, reason in (
            ("Skips itself", "Skipped by the runner"),
            ("Nothing in it", "Scenario has no steps"),
        ):
            skipped = results[name]
            self.same(
                {
                    "passed": skipped["passed"],
                    "skipped": skipped["test_metadata"]["skipped"],
                    "status": skipped["test_metadata"]["cucumber_status"],
                    "error_message": skipped["error_message"],
                    "last entry": (
                        skipped["assertions"][-1]["assertion_type"],
                        skipped["assertions"][-1]["skipped"],
                    ),
                },
                {
                    "passed": True,
                    "skipped": True,
                    "status": "skipped",
                    "error_message": reason,
                    "last entry": ("Skip", True),
                },
                f"{name} is stored as skipped with the reason {reason!r} and ends with a Skip "
                "entry",
                f"{name} is stored with",
            )
        for name in ("Same name (line 33)", "Same name (line 34)"):
            support.check_in(
                self,
                name,
                results,
                f"the duplicate scenario name is stored apart as {name}",
                f"no scenario is stored as {name}; the names are {sorted(results)}",
            )
        german = results["Wert prüfen"]
        self.same(
            {
                "test_class": german["test_class"],
                "passed": german["passed"],
                "entries not information": [
                    a["assertion_type"] for a in german["assertions"] if not a.get("info")
                ],
            },
            {"test_class": "Prüfstand", "passed": True, "entries not information": []},
            "the German feature Prüfstand passes and every step written with German keywords is "
            "an information entry",
            "Wert prüfen is stored with",
        )
        self.same(
            self.bud.run(run_id)["skipped_tests"],
            0,
            f"Bud counts 0 skipped test cases on run {run_id}: no feature is wholly skipped",
            f"Bud counts skipped test cases on run {run_id}",
        )

    def bud_hooks_alone_make_no_steps_and_the_worst_status_wins(self):
        """A hook-only scenario is stored skipped; an undefined step with a failed After hook is
        stored failed."""
        hook_only = [
            {
                "name": "F",
                "uri": "features/f.feature",
                "elements": [
                    {
                        "type": "scenario",
                        "name": "S",
                        "line": 2,
                        "steps": [
                            {
                                "keyword": "Before",
                                "hidden": True,
                                "result": {"status": "passed", "duration": 1},
                            }
                        ],
                    }
                ],
            }
        ]
        worst = [
            {
                "name": "G",
                "uri": "features/g.feature",
                "elements": [
                    {
                        "type": "scenario",
                        "name": "T",
                        "line": 2,
                        "steps": [
                            {
                                "keyword": "When ",
                                "name": "a",
                                "line": 3,
                                "result": {"status": "undefined"},
                            }
                        ],
                        "after": [
                            {"result": {"status": "failed", "error_message": "Error: after broke"}}
                        ],
                    }
                ],
            }
        ]
        case = self._case("hooks")
        case.write("hook-only.json", json.dumps(hook_only))
        case.write("worst.json", json.dumps(worst))
        _, first = self._import(case, "hook-only.json")
        _, second = self._import(case, "worst.json")
        support.need(
            self,
            [first is not None, second is not None],
            [True, True],
            "both inline reports reach Bud",
            f"the inline reports reached Bud as runs {first!r} and {second!r}",
        )
        only = self.bud.results(first)[0]
        self.same(
            {
                "passed": only["passed"],
                "skipped": only["test_metadata"]["skipped"],
                "error_message": only["error_message"],
            },
            {"passed": True, "skipped": True, "error_message": "Scenario has no steps"},
            "a scenario with only a hook is stored as skipped: Scenario has no steps",
            "the hook-only scenario is stored with",
        )
        worse = self.bud.results(second)[0]
        self.same(
            {
                "status": worse["test_metadata"]["cucumber_status"],
                "error_message": worse["error_message"],
            },
            {"status": "failed", "error_message": "Undefined step: When a"},
            "an undefined step with a failed After hook is stored as failed: the worst status wins",
            "the undefined step with a failed After hook is stored with",
        )

    def bud_the_payload_names_the_suite_product_and_run(self):
        """The run Bud creates carries product, ref and suite; app.properties gives the product;
        --suite-name and --test-run-id are used."""
        case = self._case("payload")
        support.copy_fixture(case, "cucumber-jvm.json")
        _, run_id = self._import(
            case, "cucumber-jvm.json", "--product-id", self.product, "--ref-sw-under-test", "v2.4.1"
        )
        run = self.bud.run(run_id)
        self.same(
            {
                k: run[k]
                for k in ("name", "product_id", "ref_software_under_test", "runner_account")
            },
            {
                "name": "Demo - Bench supply",
                "product_id": self.product,
                "ref_software_under_test": "v2.4.1",
                "runner_account": self.station.name,
            },
            "the run Bud creates is named after the product and the feature and carries v2.4.1 and "
            "the station",
            "the run Bud creates has",
        )
        self.same(
            len(self.bud.results(run_id)),
            8,
            f"Bud holds the eight results on run {run_id}",
            f"Bud holds this many results on run {run_id}",
        )
        existing = self.bud.create_run(self.station, "Existing run")
        _, used = self._import(case, "cucumber-jvm.json", "--test-run-id", existing)
        self.same(
            used,
            existing,
            f"import-cucumber --test-run-id {existing} uploads to run {existing}",
            "import-cucumber --test-run-id uploads to run",
        )
        self.same(
            len(self.bud.results(existing)),
            8,
            f"Bud holds the eight results on run {existing}",
            f"Bud holds this many results on run {existing}",
        )
        props = self._case("payload-properties", f"productId={self.product}\n")
        support.copy_fixture(props, "cucumber-js-edges.json")
        _, run_id = self._import(props, "cucumber-js-edges.json")
        run = self.bud.run(run_id)
        self.same(
            {"name": run["name"], "product_id": run["product_id"]},
            {"name": "Demo - features", "product_id": self.product},
            "a report of two features gives the run the features directory as suite and the "
            "app.properties product",
            "the run of the two-feature report has",
        )
        support.copy_fixture(props, "cucumber-js.json")
        _, run_id = self._import(props, "cucumber-js.json", "--suite-name", "Bench")
        self.same(
            self.bud.run(run_id)["name"],
            "Demo - Bench",
            "import-cucumber --suite-name Bench names the run Demo - Bench",
            "import-cucumber --suite-name Bench names the run",
        )
        nightly = props.write(
            "nightly.json",
            json.dumps([{"name": "A", "elements": []}, {"name": "B", "elements": []}]),
        )
        report = CucumberReport(read_report(nightly), nightly)
        self.same(
            {"payload": report.payload(), "default suite": report._default_suite()},
            {"payload": None, "default suite": "nightly"},
            "in-process: a report without scenarios gives no body, and its suite defaults to the "
            "file "
            "stem nightly",
            "in-process: the empty nightly.json report gives",
        )

    def bud_paths_and_messages(self):
        """feature_path strips the scheme; error_text keeps the first line of each runner's
        message."""
        for uri, expected in (
            (
                "file:src/test/resources/features/bench.feature",
                "src/test/resources/features/bench.feature",
            ),
            ("features/bench.feature", "features/bench.feature"),
            (None, None),
            ("classpath:com/acme/bench.feature", "com/acme/bench.feature"),
        ):
            got = feature_path(uri)
            support.check(
                self,
                got,
                expected,
                f"feature_path({uri!r}) gives {expected!r}",
                f"feature_path({uri!r}) gives {got!r}, not {expected!r}",
            )
        for runner, text, expected in (
            (
                "cucumber-js",
                "Error: bad\n    at World.<anonymous> (features/steps.js:5:37)",
                "Error: bad",
            ),
            (
                "Cucumber-JVM",
                "java.lang.AssertionError: x\n\tat probe.Steps.valueIs(Steps.java:12)",
                "java.lang.AssertionError: x",
            ),
            (
                "Cucumber-Ruby",
                "x (RuntimeError)\n./features/steps.rb:5:in `block'",
                "x (RuntimeError)",
            ),
        ):
            got = error_text(text)
            support.check(
                self,
                got,
                expected,
                f"error_text keeps the first line of a {runner} message: {expected!r}",
                f"error_text of a {runner} message gives {got!r}, not {expected!r}",
            )

    @parameterized(
        [
            ("{not json", "not valid JSON"),
            ('{"name": "x"}', "a Cucumber JSON report is a list of features"),
            ('[{"name": "x"}]', "feature 1 has no list of elements"),
            (
                '[{"name": "x", "elements": [{"steps": 3}]}]',
                "feature 1 has an element whose steps are not a list",
            ),
            ('[{"name": "x", "elements": [3]}]', "feature 1 has an element that is not an object"),
            (
                '[{"name": "x", "elements": [{"steps": [3]}]}]',
                "feature 1 has steps that are not objects",
            ),
            (
                '[{"name": "x", "elements": [{"steps": [{"name": "a", "result": "passed"}]}]}]',
                "a steps entry whose result",
            ),
            (
                '[{"name": "x", "elements": [{"before": {"result": {}}}]}]',
                "whose before are not a list",
            ),
            (
                '[{"name": "x", "tags": "@a", "elements": []}]',
                "feature 1 has tags that are not a list",
            ),
        ]
    )
    def bud_a_malformed_report_is_refused(self, content, problem):
        """import-cucumber of a malformed report: exit 2 and the problem named."""
        case = support.Case("malformed")
        case.write("report.json", content)
        command = f"bud-runner import-cucumber of the malformed report {content!r}"
        done = case.bud_runner("import-cucumber", "--report", "report.json", "-b", self.bud.url)
        support.exits(self, done, 2, command)
        support.says(self, problem, done.err, command)

    def bud_a_report_that_is_not_utf8_is_refused(self):
        """A UTF-16 report: exit 2 and "not UTF-8 text"."""
        case = support.Case("utf16")
        case.write("report.json", '[{"name": "x", "elements": []}]'.encode("utf-16"))
        command = "bud-runner import-cucumber of a UTF-16 report"
        done = case.bud_runner("import-cucumber", "--report", "report.json", "-b", self.bud.url)
        support.exits(self, done, 2, command)
        support.says(self, "not UTF-8 text", done.err, command)

    def bud_a_missing_report_is_refused(self):
        """An absent report: exit 2 and the unreadable-file message."""
        command = "bud-runner import-cucumber --report absent.json"
        done = support.Case("absent").bud_runner(
            "import-cucumber", "--report", "absent.json", "-b", self.bud.url
        )
        support.exits(self, done, 2, command)
        support.says(self, "cannot read the file", done.err, command)

    def bud_import_uploads_the_report_and_attaches_it(self):
        """The summary, 9 results, product from app.properties, the station, and the report
        attached to the run."""
        case = self._case("attach", f"productId={self.product}\n")
        support.copy_fixture(case, "cucumber-js-edges.json")
        command = "bud-runner import-cucumber --report cucumber-js-edges.json"
        done, run_id = self._import(case, "cucumber-js-edges.json")
        support.exits(self, done, 0, command)
        support.says(self, "Cucumber report cucumber-js-edges.json:", done.out, command)
        support.need(
            self,
            run_id is not None,
            True,
            f"{command} uploads to a Bud run",
            f"{command} reports no Bud run: {done!r}",
        )
        run = self.bud.run(run_id)
        self.same(
            {"product_id": run["product_id"], "runner_account": run["runner_account"]},
            {"product_id": self.product, "runner_account": self.station.name},
            "the run carries the app.properties product and the station",
            "the run carries",
        )
        self.same(
            len(self.bud.results(run_id)),
            9,
            f"Bud holds the nine results on run {run_id}",
            f"Bud holds this many results on run {run_id}",
        )
        self.same(
            self.bud.uploaded(run_id),
            ["cucumber-js-edges.json"],
            "the imported report is attached to the run",
            "the run holds the files",
        )

    def bud_import_without_artifacts_and_with_a_run_id(self):
        """--no-artifacts --test-run-id N --suite-name Bench: the results on run N and no file."""
        case = self._case("no-artifacts")
        support.copy_fixture(case, "cucumber-js.json")
        run_id = self.bud.create_run(self.station, "Bench")
        command = f"bud-runner import-cucumber --no-artifacts --test-run-id {run_id}"
        done, used = self._import(
            case,
            "cucumber-js.json",
            "--no-artifacts",
            "--test-run-id",
            run_id,
            "--suite-name",
            "Bench",
        )
        support.exits(self, done, 0, command)
        self.same(used, run_id, f"{command} uploads to run {run_id}", f"{command} uploads to run")
        self.same(
            len(self.bud.results(run_id)),
            8,
            f"Bud holds the eight results on run {run_id}",
            f"Bud holds this many results on run {run_id}",
        )
        self.same(
            self.bud.uploaded(run_id), [], f"{command} attaches no file", f"{command} attaches"
        )

    def bud_an_upload_that_does_not_reach_bud_exits_1_and_is_spooled(self):
        """Bud unreachable: exit 1 and a spooled payload with 8 results."""
        case = self._case("spool")
        support.copy_fixture(case, "cucumber-js.json")
        command = "bud-runner import-cucumber against a closed port"
        done = case.bud_runner(
            "import-cucumber",
            "--report",
            "cucumber-js.json",
            "-b",
            f"http://127.0.0.1:{support.closed_port()}",
            timeout=240,
        )
        support.exits(self, done, 1, command)
        spooled = case.spooled()
        support.need(
            self,
            len(spooled),
            1,
            f"{command} spools one result payload",
            f"{command} spooled {len(spooled)} payloads",
        )
        count = len(json.loads(spooled[0].read_text())["results"])
        self.same(
            count,
            8,
            "the spooled payload holds the eight results",
            "the spooled payload holds this many results",
        )

    def bud_no_upload_and_empty_reports_send_nothing(self):
        """--no-upload, and a report without scenarios: exit 0, the summary, no new run in Bud."""
        case = self._case("nothing")
        support.copy_fixture(case, "cucumber-js.json")
        case.write("empty.json", "[]")
        before = self.bud.run_ids()
        first_command = "bud-runner import-cucumber --no-upload of cucumber-js.json"
        second_command = "bud-runner import-cucumber of an empty report"
        first = case.bud_runner(
            "import-cucumber", "--report", "cucumber-js.json", "--no-upload", "-b", self.bud.url
        )
        second = case.bud_runner("import-cucumber", "--report", "empty.json", "-b", self.bud.url)
        support.exits(self, first, 0, first_command)
        support.exits(self, second, 0, second_command)
        support.says(
            self,
            "Cucumber report cucumber-js.json: 1 features, 8 scenarios",
            first.out,
            first_command,
        )
        support.says(
            self, "Cucumber report empty.json: 0 features, 0 scenarios", second.out, second_command
        )
        self.same(
            self.bud.new_run_ids(before),
            [],
            "neither --no-upload nor an empty report creates a run in Bud",
            "Bud holds the new runs",
        )
