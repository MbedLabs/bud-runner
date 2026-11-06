"""The Behave formatter and run-behave: a real Behave project mapped to Bud results, uploaded,
spooled and replayed."""

import json
import re

import support
from budtestlibrary import BudTestCase

UPLOADED = re.compile(r"Behave results uploaded to Bud run (\d+)")

FEATURE = """Feature: Bench supply
  Background:
    Given a bench

  @bloom:PRJ-TC-001 @smoke
  Scenario: Voltage within limit
    When I measure 3
    Then the value is 3
    And the value is below 5

  Scenario: Wrong value
    When I measure 2
    Then the value is 3
    Then the value is below 5

  Scenario: Step raises
    When I break

  Scenario: Missing step
    When nobody wrote this

  @skipme
  Scenario: Skipped by hook
    When I measure 1

  @excluded
  Scenario: Excluded by tags
    When I measure 1

  @hookfail
  Scenario: Hook fails
    When I measure 1

  Scenario Outline: Outline <v>
    When I measure <v>
    Then the value is <v>
    Examples:
      | v |
      | 1 |
      | 2 |
"""

STEPS = """
from behave import given, when, then


@given("a bench")
def a_bench(context):
    context.v = None


@when("I measure {v:d}")
def measure(context, v):
    context.v = v


@when("I break")
def broken(context):
    raise ValueError("bad value")


@then("the value is {v:d}")
def value_is(context, v):
    assert context.v == v, f"expected {v}"


@then("the value is below {v:d}")
def below(context, v):
    assert context.v < v
"""

ENVIRONMENT = """
def before_scenario(context, scenario):
    if "skipme" in scenario.tags:
        scenario.skip("not on this bench")
    if "hookfail" in scenario.tags:
        raise RuntimeError("hook broke")
"""

SECOND_FEATURE = """@bloom:PRJ-003
Feature: Bench clock
  Scenario: Clock runs
    Given a bench
"""

NO_BEHAVE = (
    '"""Stands in for a missing Behave: importing it fails as an absent package does."""\n\n'
    "raise ImportError(\"No module named 'behave'\")\n"
)


def _steps(result):
    """Return (type, passed, info, skipped) of each stored entry."""
    return [
        (a["assertion_type"], a["passed"], bool(a.get("info")), bool(a["skipped"]))
        for a in result["assertions"]
    ]


class BehaveFormatter(BudTestCase):
    """One run-behave of the bench project read back from Bud, plus run fields, upload, spool,
    refusals and the command."""

    def setUpClass(self):
        self.bud = support.Bud()
        self.station = self.bud.station("behave")
        self.product = self.bud.product("Demo")
        self.run_id = self.bud.create_run(self.station, "Behave bench")
        case = self._case("bench")
        self.bench = case.bud_runner(
            "run-behave",
            "-b",
            self.bud.url,
            "--test-run-id",
            self.run_id,
            "--tags=-@excluded",
            "features",
        )
        self.ordered = self.bud.results(self.run_id)
        self.results = {r["test_method"]: r for r in self.ordered}

    def _case(self, name, properties=""):
        """Return a case of the station with the bench project."""
        case = support.Case(name)
        case.give_station(self.station)
        case.write("app.properties", f"budRunnerAccount={self.station.name}\n{properties}")
        case.write("features/bench.feature", FEATURE)
        case.write("features/steps/bench_steps.py", STEPS)
        case.write("features/environment.py", ENVIRONMENT)
        return case

    def stored(self, scenario: str, actual: dict, expected: dict, what: str) -> None:
        """Record fields of a stored scenario against the values expected."""
        support.check(
            self,
            actual,
            expected,
            f"Bud stores the scenario {scenario!r} with {what}",
            f"Bud stores the scenario {scenario!r} with {actual}, not {what}",
        )

    def bud_a_behave_run_maps_to_bud_results(self):
        """The stored scenarios, class, tc_id, tags, location, step entries and outline rows."""
        support.exits(
            self,
            self.bench,
            1,
            "bud-runner run-behave of the bench project, which has failing scenarios,",
        )
        order = [r["test_method"] for r in self.ordered]
        support.check(
            self,
            order,
            [
                "Voltage within limit",
                "Wrong value",
                "Step raises",
                "Missing step",
                "Skipped by hook",
                "Hook fails",
                "Outline 1 -- @1.1",
                "Outline 2 -- @1.2",
            ],
            f"Bud stores the eight scenarios of the bench feature on run {self.run_id} in order",
            f"Bud stores the scenarios {order} on run {self.run_id}",
        )
        classes = sorted({r["test_class"] for r in self.ordered})
        support.check(
            self,
            classes,
            ["Bench supply"],
            "every stored scenario has the feature Bench supply as its test case",
            f"the stored scenarios have the test cases {classes}",
        )
        measured = self.results["Voltage within limit"]
        metadata = measured["test_metadata"]
        self.stored(
            "Voltage within limit",
            {
                "passed": measured["passed"],
                "error_message": measured["error_message"],
                "tc_id": metadata["tc_id"],
                "behave_tags": metadata["behave_tags"],
                "location": metadata["location"],
            },
            {
                "passed": True,
                "error_message": None,
                "tc_id": "PRJ-TC-001",
                "behave_tags": ["bloom:PRJ-TC-001", "smoke"],
                "location": "features/bench.feature:6",
            },
            "passed, no error, tc_id PRJ-TC-001 from its tag, its tags and its location",
        )
        extra = sorted(k for k in ("test_case_file", "test_case_class") if k in metadata)
        support.check(
            self,
            extra,
            [],
            "the stored metadata of a Behave scenario has no test_case_file or test_case_class",
            f"the stored metadata of a Behave scenario has {extra}",
        )
        steps = _steps(measured)
        support.check(
            self,
            steps,
            [
                ("a bench", True, True, False),
                ("I measure 3", True, True, False),
                ("the value is 3", True, False, False),
                ("the value is below 5", True, False, False),
            ],
            "Voltage within limit stores one entry per step, Background step first",
            f"Voltage within limit stores the step entries {steps}",
        )
        check = measured["assertions"][3]
        source = {
            k: check[k] for k in ("code_context", "source_file", "source_line", "source_function")
        }
        support.check(
            self,
            source,
            {
                "code_context": "And the value is below 5",
                "source_file": "features/bench.feature",
                "source_line": 9,
                "source_function": "Voltage within limit",
            },
            "the last step entry points at its line 9 in features/bench.feature",
            f"the last step entry points at {source}",
        )
        outline = self.results["Outline 2 -- @1.2"]
        self.stored(
            "Outline 2 -- @1.2",
            {"passed": outline["passed"], "steps": [s[0] for s in _steps(outline)]},
            {"passed": True, "steps": ["a bench", "I measure 2", "the value is 2"]},
            "passed and the steps of its example row",
        )

    def bud_failures_carry_message_and_traceback(self):
        """Failed checks, raised errors and undefined steps with their messages and tracebacks as
        stored."""
        wrong = self.results["Wrong value"]
        self.stored(
            "Wrong value",
            {"passed": wrong["passed"], "steps": _steps(wrong)},
            {
                "passed": False,
                "steps": [
                    ("a bench", True, True, False),
                    ("I measure 2", True, True, False),
                    ("the value is 3", False, False, False),
                ],
            },
            "failed, stopping at the failed check",
        )
        failed = wrong["assertions"][2]
        self.stored(
            "Wrong value",
            {"check message": failed["message"], "error_message": wrong["error_message"]},
            {"check message": "expected 3", "error_message": "expected 3"},
            "the failed check's message 'expected 3' as its error",
        )
        support.says(
            self, "AssertionError", failed["traceback"], "the traceback of the failed check"
        )
        support.says(
            self, "bench_steps.py", failed["traceback"], "the traceback of the failed check"
        )
        support.check(
            self,
            wrong["traceback"],
            failed["traceback"],
            "the traceback of Wrong value is the traceback of its failed check",
            "the traceback of Wrong value differs from the traceback of its failed check",
        )
        raised = self.results["Step raises"]
        self.stored(
            "Step raises",
            {
                "passed": raised["passed"],
                "error_message": raised["error_message"],
                "raising step": _steps(raised)[1],
            },
            {
                "passed": False,
                "error_message": "ValueError: bad value",
                "raising step": ("I break", False, True, False),
            },
            "failed with the raised ValueError: bad value",
        )
        support.says(
            self,
            "ValueError: bad value",
            raised["assertions"][1]["traceback"],
            "the traceback of the raising step entry",
        )
        support.says(
            self, "ValueError: bad value", raised["traceback"], "the traceback of Step raises"
        )
        missing = self.results["Missing step"]
        self.stored(
            "Missing step",
            {
                "passed": missing["passed"],
                "error_message": missing["error_message"],
                "undefined step": _steps(missing)[1],
            },
            {
                "passed": False,
                "error_message": "Undefined step: When nobody wrote this",
                "undefined step": ("nobody wrote this", False, True, False),
            },
            "failed with Undefined step: When nobody wrote this",
        )

    def bud_skips_hook_errors_and_tag_selection(self):
        """The excluded scenario is absent; the hook skip and the hook error as stored."""
        support.check_not_in(
            self,
            "Excluded by tags",
            self.results,
            "Excluded by tags, left out with --tags=-@excluded, is not stored",
            "Excluded by tags is stored although --tags=-@excluded left it out",
        )
        skipped = self.results["Skipped by hook"]
        self.stored(
            "Skipped by hook",
            {
                "passed": skipped["passed"],
                "skipped": skipped["test_metadata"]["skipped"],
                "error_message": skipped["error_message"],
                "steps": _steps(skipped),
            },
            {
                "passed": True,
                "skipped": True,
                "error_message": "not on this bench",
                "steps": [("Skip", True, False, True)],
            },
            "skipped by its hook with the reason 'not on this bench' as one Skip entry",
        )
        hook = self.results["Hook fails"]
        self.stored(
            "Hook fails",
            {
                "passed": hook["passed"],
                "entries": [(a["assertion_type"], a["passed"]) for a in hook["assertions"]],
            },
            {"passed": False, "entries": [("HookError", False)]},
            "failed with one failed HookError entry",
        )
        support.says(
            self, "RuntimeError: hook broke", hook["error_message"], "the error of Hook fails"
        )
        for part in ("Traceback (most recent call last)", "environment.py", "hook broke"):
            support.says(self, part, hook["traceback"], "the traceback of Hook fails")
        support.check(
            self,
            hook["assertions"][0]["traceback"],
            hook["traceback"],
            "the HookError entry carries the traceback of Hook fails",
            "the HookError entry carries another traceback than Hook fails",
        )
        skipped_count = self.bud.run(self.run_id)["skipped_tests"]
        support.check(
            self,
            skipped_count,
            0,
            f"Bud counts 0 skipped test cases on run {self.run_id}: no feature is wholly skipped",
            f"Bud counts {skipped_count!r} skipped test cases on run {self.run_id}, not 0",
        )

    def _new_run(self, before: set, command: str) -> dict:
        """Return the one run Bud created since before, stopping the step when there is not one."""
        new = self.bud.new_run_ids(before)
        support.need(
            self,
            len(new),
            1,
            f"{command} makes Bud create one run",
            f"{command} made Bud create the runs {new}, not one",
        )
        return self.bud.run(new[0])

    def bud_the_payload_names_the_suite_product_and_run(self):
        """Run fields of runs Bud creates: product, ref, feature or directory name, app.properties
        product, --suite-name; a feature tag."""
        support.check(
            self,
            len(self.ordered),
            8,
            f"run-behave --test-run-id {self.run_id} puts the eight results on that run",
            f"run-behave --test-run-id {self.run_id} put {len(self.ordered)} results on that run",
        )
        case = self._case("payload")
        before = self.bud.run_ids()
        command = "bud-runner run-behave --product-id <Demo> --ref-sw-under-test v2.4.1"
        case.bud_runner(
            "run-behave",
            "-b",
            self.bud.url,
            "--product-id",
            self.product,
            "--ref-sw-under-test",
            "v2.4.1",
            "--tags=-@excluded",
            "features",
        )
        run = self._new_run(before, command)
        fields = {
            k: run[k] for k in ("name", "product_id", "ref_software_under_test", "runner_account")
        }
        support.check(
            self,
            fields,
            {
                "name": "Demo - Bench supply",
                "product_id": self.product,
                "ref_software_under_test": "v2.4.1",
                "runner_account": self.station.name,
            },
            f"the run of {command} is named after the product and the feature, carries v2.4.1 and "
            "the station",
            f"the run of {command} has {fields}",
        )
        props = self._case("payload-props", f"productId={self.product}\n")
        props.write("features/clock.feature", SECOND_FEATURE)
        before = self.bud.run_ids()
        command = "bud-runner run-behave of two features with productId in app.properties"
        props.bud_runner("run-behave", "-b", self.bud.url, "--tags=-@excluded", "features")
        run = self._new_run(before, command)
        fields = {k: run[k] for k in ("name", "product_id")}
        support.check(
            self,
            fields,
            {"name": "Demo - features", "product_id": self.product},
            f"the run of {command} is named after the directory and carries the app.properties "
            "product",
            f"the run of {command} has {fields}",
        )
        clock = {r["test_method"]: r for r in self.bud.results(run["id"])}["Clock runs"][
            "test_metadata"
        ]
        fields = {"tc_id": clock["tc_id"], "behave_tags": clock["behave_tags"]}
        support.check(
            self,
            fields,
            {"tc_id": "PRJ-TC-003", "behave_tags": ["bloom:PRJ-003"]},
            "the feature tag bloom:PRJ-003 names test case PRJ-TC-003 for the scenario Clock runs",
            f"the scenario Clock runs is stored with {fields}",
        )
        before = self.bud.run_ids()
        command = "bud-runner run-behave --suite-name Bench"
        props.bud_runner(
            "run-behave",
            "-b",
            self.bud.url,
            "--suite-name",
            "Bench",
            "--tags=-@excluded",
            "features",
        )
        run = self._new_run(before, command)
        support.check(
            self,
            run["name"],
            "Demo - Bench",
            f"the run of {command} is named Demo - Bench",
            f"the run of {command} is named {run['name']!r}",
        )

    def bud_the_run_is_uploaded_without_a_skipped_count_when_no_feature_is_all_skipped(self):
        """run-behave with the station and app.properties product: 8 results, product, station,
        skipped unset, the stderr line."""
        case = self._case("session", f"productId={self.product}\n")
        command = "bud-runner run-behave with productId in app.properties"
        done = case.bud_runner("run-behave", "-b", self.bud.url, "--tags=-@excluded", "features")
        support.exits(self, done, 1, f"{command}, keeping Behave's exit code,")
        found = UPLOADED.search(done.err)
        support.need(
            self,
            found is not None,
            True,
            f"{command} prints the Bud run it uploaded to",
            f"{command} prints no upload line: {done!r}",
        )
        run = self.bud.run(int(found.group(1)))
        fields = {
            "results": len(self.bud.results(run["id"])),
            "product_id": run["product_id"],
            "runner_account": run["runner_account"],
            "skipped_tests": run["skipped_tests"],
        }
        support.check(
            self,
            fields,
            {
                "results": 8,
                "product_id": self.product,
                "runner_account": self.station.name,
                "skipped_tests": 0,
            },
            f"the run of {command} holds 8 results, the product, the station and 0 skipped",
            f"the run of {command} has {fields}",
        )

    def bud_a_failed_upload_is_spooled(self):
        """Bud unreachable with --test-run-id 7: one spooled payload naming run 7."""
        case = self._case("spool")
        command = "bud-runner run-behave --test-run-id 7 against a closed port"
        done = case.bud_runner(
            "run-behave",
            "-b",
            f"http://127.0.0.1:{support.closed_port()}",
            "--test-run-id",
            "7",
            "--tags=-@excluded",
            "features",
            timeout=240,
        )
        support.exits(self, done, 1, f"{command}, keeping Behave's exit code,")
        spooled = case.spooled()
        support.need(
            self,
            len(spooled),
            1,
            f"{command} spools one result payload",
            f"{command} spooled {len(spooled)} payloads",
        )
        run_id = json.loads(spooled[0].read_text())["test_run_id"]
        support.check(
            self,
            run_id,
            7,
            "the spooled payload names run 7",
            f"the spooled payload names run {run_id!r}, not 7",
        )
        self.spool_case = case

    def bud_run_behave_replays_the_spool_first(self):
        """The next run-behave against Bud replays the spooled payload (onto a run of this station)
        and empties the spool."""
        case = getattr(self, "spool_case", None)
        support.need(
            self,
            case is not None,
            True,
            "the spool case ran first and left a spooled payload",
            "the spool case did not finish, so there is no spooled payload to replay",
        )
        spooled = case.spooled()[0]
        body = json.loads(spooled.read_text())
        target = self.bud.create_run(self.station, "Replayed")
        body["test_run_id"] = target
        spooled.write_text(json.dumps(body))
        case.write("features/bench.feature", SECOND_FEATURE)
        command = "the next bud-runner run-behave against Bud"
        done = case.bud_runner("run-behave", "-b", self.bud.url, "features")
        support.says(self, "✓ Replayed spooled results from", done.out, command)
        count = len(self.bud.results(target))
        support.check(
            self,
            count,
            8,
            f"the eight spooled results reach Bud on run {target}",
            f"Bud holds {count} results on run {target}, not the 8 spooled ones",
        )
        left = [p.name for p in case.spooled()]
        support.check(
            self,
            left,
            [],
            "the spool is empty after the replay",
            f"the spool still holds {left}",
        )

    def bud_an_upload_error_never_changes_the_exit_code(self):
        """behave with the formatter and a URL it refuses, on a passing feature: exit 0 and the
        warning."""
        case = support.Case("upload-error")
        case.write("features/clock.feature", SECOND_FEATURE)
        case.write("features/steps/bench_steps.py", STEPS)
        command = (
            "behave -f BudFormatter with bud_backend_url=http://bud.example.com on a passing "
            "feature"
        )
        done = case.command(
            support.PYTHON,
            "-m",
            "behave",
            "-f",
            "bud_runner.behave_formatter:BudFormatter",
            "-D",
            "bud_backend_url=http://bud.example.com",
            "features",
        )
        support.exits(self, done, 0, f"{command}, keeping Behave's exit code,")
        support.says(self, "Could not report the Behave run to Bud", done.err, command)

    def bud_run_behave_command_passes_behave_arguments_and_exit_code(self):
        """run-behave --no-upload --tags=@smoke: exit 1, only smoke scenarios, pretty output; with
        -f progress no pretty output."""
        case = support.Case("run-behave")
        case.write(
            "features/smoke.feature",
            "Feature: Smoke\n  @smoke\n  Scenario: Smoke passes\n    Given a bench\n\n  @smoke\n"
            "  Scenario: Smoke fails\n    Given a bench\n    When I measure 1\n    Then the value "
            "is 2\n"
            "\n  Scenario: Not smoke\n    Given a bench\n",
        )
        case.write("features/steps/bench_steps.py", STEPS)
        command = "bud-runner run-behave --no-upload features/ --tags=@smoke"
        done = case.bud_runner(
            "run-behave",
            "--no-upload",
            "--test-run-id",
            "5",
            "--suite-name",
            "Bench",
            "features/",
            "--tags=@smoke",
        )
        support.exits(self, done, 1, f"{command}, keeping Behave's exit code,")
        support.says(self, "Scenario: Smoke passes", done.out, f"the pretty output of {command}")
        support.says(
            self,
            "1 scenario passed, 1 failed, 1 skipped",
            done.out,
            f"Behave's summary of {command}",
        )
        command = "bud-runner run-behave --no-upload -f progress features/ --tags=@smoke"
        progress = case.bud_runner(
            "run-behave", "--no-upload", "-f", "progress", "features/", "--tags=@smoke"
        )
        support.exits(self, progress, 1, f"{command}, keeping Behave's exit code,")
        support.check_not_in(
            self,
            "Scenario: Smoke passes",
            progress.out,
            f"{command} prints no pretty output",
            f"{command} prints pretty output although -f progress was given",
        )

    def bud_run_behave_names_the_extra_when_behave_is_missing(self):
        """With Behave not importable (a stand-in package that fails to import shadows it): exit 2
        and the install hint."""
        case = support.Case("no-behave")
        case.write("shadow/behave/__init__.py", NO_BEHAVE)
        command = "bud-runner run-behave with Behave not importable"
        done = case.bud_runner(
            "run-behave",
            "--no-upload",
            "features/",
            env={"PYTHONPATH": f"{case.cwd / 'shadow'}:{support.LIBRARY_PATH}"},
        )
        support.exits(self, done, 2, command)
        support.says(self, "pip install 'bud-runner[behave]'", done.err, command)

    def bud_run_behave_runs_behave_with_the_console_output_kept(self):
        """run-behave --no-upload on the bench project: exit 1 and Behave's pretty output on
        stdout."""
        case = self._case("console")
        command = "bud-runner run-behave --no-upload of the bench project"
        done = case.bud_runner("run-behave", "--no-upload", "--tags=-@excluded", "features")
        support.exits(self, done, 1, f"{command}, keeping Behave's exit code,")
        support.says(
            self, "Scenario: Voltage within limit", done.out, f"the pretty output of {command}"
        )
