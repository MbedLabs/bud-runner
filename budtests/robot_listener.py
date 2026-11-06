"""The Robot Framework listener and run-robot: real Robot runs mapped to Bud results, uploaded with
their files, spooled and replayed."""

import contextlib
import io
import json
import re
from pathlib import Path
from types import SimpleNamespace

import support
from budtestlibrary import BudTestCase

from bud_runner import robot_listener as listener_module
from bud_runner.robot_listener import BudListener, assert_name, assertion_for, is_check

UPLOADED = re.compile(r"Robot results uploaded to Bud run (\d+)")

SUITE = """*** Settings ***
Metadata    Software Under Test    fw-2.4.1

*** Test Cases ***
Measures within limit
    [Tags]    bloom:PRJ-TC-001    bench
    ${measured}=    Set Variable    3
    Should Be Equal As Numbers    ${measured}    3
    Should Be True    ${measured} < 5
    Check Twice    abc    b

Fails a check
    Should Be Equal    1    2

Is skipped
    Skip    not on this bench

*** Keywords ***
Check Twice
    [Arguments]    ${text}    ${part}
    Should Contain    ${text}    ${part}
"""

DEEP = """*** Settings ***
Resource    checks.resource

*** Test Cases ***
Goes deep
    Check Twice    abc    z

Fails hard
    Fail    broken wiring
"""

CHECKS = """*** Keywords ***
Check Twice
    [Arguments]    ${text}    ${part}
    Log    checking
    Should Contain    ${text}    ${part}
"""

TOLERATED = """*** Test Cases ***
Recovers then fails
    Run Keyword And Ignore Error    Fail    first problem
    Fail    real problem
"""

HANDLED = """*** Test Cases ***
Expects an error
    Run Keyword And Expect Error    *    Should Be Equal    1    2

Handles with try
    TRY
        Should Be Equal    3    4
    EXCEPT    *    type=glob
        Log    handled
    END

Calls a missing keyword
    This Keyword Does Not Exist

Has an empty body
    [Documentation]    nothing to run

Propagates through a wrapper
    Run Keyword    Should Be Equal    1    2

Retries then fails
    Wait Until Keyword Succeeds    3x    10ms    Should Be Equal    5    6

Fails in the body and the teardown
    Fail    body broke
    [Teardown]    Fail    teardown broke
"""

SKIP_IF = """*** Test Cases ***
Skips inside
    Skip If    True    no bench
"""

EXCLUDE = """*** Test Cases ***
First fails
    Fail    one

Second fails
    Fail    two

Slow one
    [Tags]    slow
    Fail    slow
"""


def _fields(entry: dict, *keys) -> dict:
    """Return the named fields of a stored entry, a missing one as '<absent>'."""
    return {key: entry.get(key, "<absent>") for key in keys}


def _file(path) -> str:
    """Return the file name of a stored source path."""
    return Path(path).name if path else ""


def _frame(line: str) -> str:
    """Return a traceback frame line from its file name on, without the File prefix and the
    directories of its file."""
    return re.sub(r'^\s*File "(?:[^"]*/)?', "", line)


class RobotListener(BudTestCase):
    """What Bud stores for Robot runs, the files and skipped count, the spool, and the listener's
    own rules."""

    def setUpClass(self):
        self.bud = support.Bud()
        self.station = self.bud.station("robot")
        self.product = self.bud.product("Demo")

    def _case(self, name, files, properties=""):
        """Return a case of the station with the given Robot files."""
        case = support.Case(name)
        case.give_station(self.station)
        case.write("app.properties", f"budRunnerAccount={self.station.name}\n{properties}")
        for relative, text in files.items():
            case.write(relative, text)
        return case

    def _robot(self, case, *args):
        """Run run-robot against Bud and return (outcome, run id or None, results in stored
        order)."""
        done = case.bud_runner("run-robot", "-b", self.bud.url, *args)
        found = UPLOADED.search(done.err)
        run_id = int(found.group(1)) if found else None
        return done, run_id, self.bud.results(run_id) if run_id else []

    def same(self, actual, expected, passed: str, failed_what: str) -> bool:
        """Record actual against expected; the failure names what was stored instead."""
        return support.check(
            self, actual, expected, passed, f"{failed_what}: {actual!r}, not {expected!r}"
        )

    def count(self, results: list, expected: int, command: str, done=None) -> None:
        """Stop the step unless Bud stored the expected number of results."""
        detail = f" ({done!r})" if done is not None and len(results) != expected else ""
        support.need(
            self,
            len(results),
            expected,
            f"{command} stores {expected} results in Bud",
            f"{command} stores {len(results)} results in Bud, not {expected}{detail}",
        )

    def bud_a_robot_run_maps_to_bud_results(self):
        """run-robot --product-id on bench.robot: the run Bud creates and every stored entry."""
        case = self._case("bench", {"bench.robot": SUITE})
        command = "bud-runner run-robot --product-id <Demo> bench.robot"
        done, run_id, results = self._robot(case, "--product-id", self.product, "bench.robot")
        support.exits(self, done, 1, f"{command}, with Robot's code for one failed test,")
        self.count(results, 3, command, done)
        run = self.bud.run(run_id)
        self.same(
            _fields(run, "name", "ref_software_under_test", "product_id"),
            {
                "name": "Demo - Bench",
                "ref_software_under_test": "fw-2.4.1",
                "product_id": self.product,
            },
            "the run Bud creates is named Demo - Bench, takes ref fw-2.4.1 from the suite Metadata "
            "and carries the product",
            "the run Bud creates has",
        )
        measured, failed, skipped = results
        self.same(
            _fields(measured, "test_class", "test_method", "passed", "error_message"),
            {
                "test_class": "Bench.Measures within limit",
                "test_method": "Measures within limit",
                "passed": True,
                "error_message": None,
            },
            "the passing test is stored as Bench.Measures within limit, passed, without error",
            "the passing test is stored with",
        )
        classes = len({r["test_class"] for r in results})
        self.same(
            classes,
            3,
            "each of the three Robot tests is its own test class in Bud",
            "the three tests give this many classes",
        )
        metadata = measured["test_metadata"]
        self.same(
            _fields(metadata, "tc_id", "robot_tags"),
            {"tc_id": "PRJ-TC-001", "robot_tags": ["bench", "bloom:PRJ-TC-001"]},
            "the passing test carries tc_id PRJ-TC-001 from its bloom tag, and its tags",
            "the passing test carries",
        )
        support.check_not_in(
            self,
            "test_case_file",
            metadata,
            "the stored metadata of a Robot test has no test_case_file",
            "the stored metadata of a Robot test has a test_case_file",
        )
        types = [a["assertion_type"] for a in measured["assertions"]]
        self.same(
            types,
            ["Set Variable", "AssertEqual", "AssertTrue", "AssertIn"],
            "the passing test stores Set Variable and its three checks as entries, in order",
            "the passing test stores the entries",
        )
        raw = [
            sorted(k for k in ("name", "args") if k in a)
            + ([] if a["metadata"] == {} else ["metadata"])
            for a in measured["assertions"]
        ]
        self.same(
            raw,
            [[], [], [], []],
            "no entry carries the raw keyword name, args or metadata",
            "the entries carry these raw keyword fields",
        )
        info, numbers, truth, contains = measured["assertions"]
        self.same(
            _fields(info, "info", "passed"),
            {"info": True, "passed": True},
            "Set Variable is stored as a passed information entry",
            "Set Variable is stored with",
        )
        self.same(
            _fields(numbers, "info", "skipped", "actual", "expected"),
            {"info": "<absent>", "skipped": False, "actual": "3", "expected": "3"},
            "Should Be Equal As Numbers is a check, not information, comparing 3 with 3",
            "Should Be Equal As Numbers is stored with",
        )
        self.same(
            {
                "file": _file(numbers["source_file"]),
                "line": numbers["source_line"],
                "function": numbers["source_function"],
                "code": numbers["code_context"],
                "traceback": numbers["traceback"],
            },
            {
                "file": "bench.robot",
                "line": 8,
                "function": "Measures within limit",
                "code": "Should Be Equal As Numbers    ${measured}    3",
                "traceback": None,
            },
            "the numbers check points at bench.robot line 8 in Measures within limit, without a "
            "traceback",
            "the numbers check points at",
        )
        support.check_match(
            self,
            r"\S",
            str(numbers.get("timestamp") or ""),
            f"the numbers check carries the timestamp {numbers.get('timestamp')!r}",
            "the numbers check carries no timestamp",
        )
        self.same(
            [_fields(truth, "actual", "expected"), _fields(contains, "actual", "expected")],
            [{"actual": "3 < 5", "expected": True}, {"actual": "abc", "expected": "b"}],
            "Should Be True stores '3 < 5' against True; Should Contain stores 'abc' against 'b'",
            "the truth and contains checks are stored as",
        )
        self.same(
            _fields(contains, "source_function", "source_line"),
            {"source_function": "Check Twice", "source_line": 21},
            "the check inside the user keyword points at Check Twice, line 21",
            "the check inside the user keyword points at",
        )
        self.same(
            measured["traceback"],
            None,
            "the passing test has no traceback",
            "the passing test has the traceback",
        )
        self.same(
            _fields(failed, "passed", "error_message"),
            {"passed": False, "error_message": "1 != 2"},
            "the failing test is stored as failed with the error 1 != 2",
            "the failing test is stored with",
        )
        check = failed["assertions"][0]
        chain = check["traceback"].splitlines()[1:]
        self.same(
            chain,
            [
                f'  File "{check["source_file"]}", line 13, in Fails a check',
                "    Should Be Equal    1    2",
                "1 != 2",
            ],
            "the failed check's traceback shows bench.robot line 13 in Fails a check, the keyword "
            "and 1 != 2",
            "the failed check's traceback is",
        )
        support.check(
            self,
            failed["traceback"],
            check["traceback"],
            "the failing test's traceback is its failed check's traceback",
            "the failing test's traceback differs from its failed check's traceback",
        )
        support.check_not_in(
            self,
            "tc_id",
            failed["test_metadata"],
            "the failing test, without a bloom tag, carries no tc_id",
            f"the failing test carries tc_id {failed['test_metadata'].get('tc_id')!r} without a "
            "bloom tag",
        )
        self.same(
            {
                "passed": skipped["passed"],
                "skipped": skipped["test_metadata"]["skipped"],
                "error_message": skipped["error_message"],
                "traceback": skipped["traceback"],
            },
            {
                "passed": True,
                "skipped": True,
                "error_message": "not on this bench",
                "traceback": None,
            },
            "the skipped test is stored as skipped with the reason not on this bench",
            "the skipped test is stored with",
        )
        self.same(
            [
                _fields(a, "assertion_type", "skipped", "passed", "message")
                for a in skipped["assertions"]
            ],
            [
                {
                    "assertion_type": "Skip",
                    "skipped": True,
                    "passed": True,
                    "message": "not on this bench",
                }
            ],
            "the skipped test holds one Skip entry with its reason",
            "the skipped test holds the entries",
        )

    def bud_close_uploads_results_skips_and_reports(self):
        """run-robot with the station and app.properties product: 3 results, product, 1 skipped,
        and Robot's three files attached."""
        case = self._case("files", {"bench.robot": SUITE}, f"productId={self.product}\n")
        command = "bud-runner run-robot bench.robot with productId in app.properties"
        done, run_id, results = self._robot(case, "bench.robot")
        support.need(
            self,
            run_id is not None,
            True,
            f"{command} uploads to a Bud run",
            f"{command} reports no Bud run: {done!r}",
        )
        run = self.bud.run(run_id)
        self.same(
            {
                "results": len(results),
                "product_id": run["product_id"],
                "skipped_tests": run["skipped_tests"],
                "runner_account": run["runner_account"],
            },
            {
                "results": 3,
                "product_id": self.product,
                "skipped_tests": 1,
                "runner_account": self.station.name,
            },
            f"the run of {command} holds 3 results, the product, 1 skipped test case and the "
            "station",
            f"the run of {command} has",
        )
        files = sorted(self.bud.uploaded(run_id))
        self.same(
            files,
            ["log.html", "output.xml", "report.html"],
            "Robot's output.xml, log.html and report.html are attached to the run",
            "the run holds the files",
        )

    def bud_failed_upload_is_spooled(self):
        """Bud unreachable with --test-run-id 7: one spooled payload naming run 7, Robot's own exit
        code."""
        case = self._case("spool", {"bench.robot": SUITE})
        command = "bud-runner run-robot --test-run-id 7 against a closed port"
        done = case.bud_runner(
            "run-robot",
            "-b",
            f"http://127.0.0.1:{support.closed_port()}",
            "--test-run-id",
            "7",
            "bench.robot",
            timeout=240,
        )
        support.exits(self, done, 1, f"{command}, with Robot's code for one failed test,")
        spooled = case.spooled()
        support.need(
            self,
            len(spooled),
            1,
            f"{command} spools one result payload",
            f"{command} spooled {len(spooled)} payloads",
        )
        named = json.loads(spooled[0].read_text())["test_run_id"]
        self.same(named, 7, "the spooled payload names run 7", "the spooled payload names run")
        self.spool_case = case

    def bud_run_robot_replays_the_spool_first(self):
        """The next run-robot against Bud replays the spooled payload (onto a run of this station)
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
        case.write("one.robot", "*** Test Cases ***\nPasses\n    Log    ok\n")
        command = "the next bud-runner run-robot against Bud"
        done, _, _ = self._robot(case, "one.robot")
        support.says(self, "✓ Replayed spooled results from", done.out, command)
        self.same(
            len(self.bud.results(target)),
            3,
            f"the three spooled results reach Bud on run {target}",
            f"Bud holds this many results on run {target}",
        )
        left = [p.name for p in case.spooled()]
        self.same(left, [], "the spool is empty after the replay", "the spool still holds")

    def bud_close_never_raises_and_skips_empty_runs(self):
        """close() without results says nothing was uploaded; with an unusable HOME it warns;
        neither raises."""
        case = support.Case("close")
        listener = BudListener(artifacts="no")
        first = io.StringIO()
        with support.Isolated(case), contextlib.redirect_stderr(first):
            listener.close()
        support.says(
            self, "nothing uploaded", first.getvalue(), "close() of a listener without results"
        )
        broken = support.Case("close-broken")
        (broken.home / ".bud").write_text("not a directory")
        second = io.StringIO()
        with support.Isolated(broken), contextlib.redirect_stderr(second):
            listener.close()
        support.says(
            self,
            "Could not report the Robot run",
            second.getvalue(),
            "close() in a HOME whose .bud is a file",
        )
        self.same(
            listener.upload_artifacts,
            False,
            'BudListener(artifacts="no") turns attachments off',
            'BudListener(artifacts="no") has upload_artifacts',
        )

    def bud_a_short_bloom_tag_names_the_test_case(self):
        """A bloom:PRJ-002 tag is stored as tc_id PRJ-TC-002."""
        case = self._case(
            "short-tag",
            {
                "short.robot": "*** Test Cases ***\nTagged\n    [Tags]    bloom:PRJ-002\n"
                "    Should Be Equal    1    1\n"
            },
        )
        command = "bud-runner run-robot short.robot"
        _, _, results = self._robot(case, "short.robot")
        self.count(results, 1, command)
        metadata = results[0]["test_metadata"]
        self.same(
            _fields(metadata, "tc_id", "robot_tags"),
            {"tc_id": "PRJ-TC-002", "robot_tags": ["bloom:PRJ-002"]},
            "the tag bloom:PRJ-002 is stored as tc_id PRJ-TC-002",
            "the test tagged bloom:PRJ-002 is stored with",
        )

    def bud_assertion_mapping(self):
        """assertion_for and is_check on several keywords."""
        other = assertion_for("Page Should Contain", "Browser", ["Welcome"], True, "")
        self.same(
            _fields(other, "assertion_type", "metadata", "expected", "message", "traceback"),
            {
                "assertion_type": "AssertPageContain",
                "metadata": {},
                "expected": "<absent>",
                "message": None,
                "traceback": None,
            },
            "assertion_for maps Browser's Page Should Contain to AssertPageContain without an "
            "expected value",
            "assertion_for maps Page Should Contain to",
        )
        negative = assertion_for(
            "Should Not Be True", "BuiltIn", ["${x}"], False, "boom", {"traceback": "tb"}
        )
        self.same(
            _fields(negative, "assertion_type", "expected", "actual", "message", "traceback"),
            {
                "assertion_type": "AssertFalse",
                "expected": False,
                "actual": "${x}",
                "message": "boom",
                "traceback": "tb",
            },
            "assertion_for maps a failed Should Not Be True to AssertFalse with its message and "
            "traceback",
            "assertion_for maps Should Not Be True to",
        )
        short = assertion_for("Should Be Equal", "BuiltIn", ["only-one"], True, "")
        self.same(
            _fields(short, "assertion_type", "expected"),
            {"assertion_type": "AssertEqual", "expected": "<absent>"},
            "Should Be Equal with one argument maps to AssertEqual without an expected value",
            "Should Be Equal with one argument maps to",
        )
        length = assertion_for("Length Should Be", "BuiltIn", ["[1, 2]", "2"], True, "")
        self.same(
            _fields(length, "assertion_type", "expected"),
            {"assertion_type": "AssertLength", "expected": "2"},
            "Length Should Be maps to AssertLength expecting 2",
            "Length Should Be maps to",
        )
        names = ("Page Should Contain", "Length Should Be", "Log", "Shouldered Task")
        checks = {name: is_check(name) for name in names}
        self.same(
            checks,
            {
                "Page Should Contain": True,
                "Length Should Be": True,
                "Log": False,
                "Shouldered Task": False,
            },
            "is_check takes the Should keywords as checks, and Log and Shouldered Task not",
            "is_check gives",
        )

    def bud_assert_names_never_say_should(self):
        """assert_name for eight keywords."""
        names = {
            "Should Be Empty": "AssertEmpty",
            "Should Not Be Empty": "AssertNotEmpty",
            "Should Start With": "AssertStartsWith",
            "Should Not Match Regexp": "AssertNotRegex",
            "Should Contain X Times": "AssertCount",
            "Element Should Not Be Visible": "AssertNotElementVisible",
            "Dictionary Should Contain Key": "AssertDictionaryContainKey",
            "Lists Should Be Equal": "AssertListsEqual",
        }
        self.same(
            {name: assert_name(name) for name in names},
            names,
            "assert_name turns each of the eight keywords into an Assert name without Should",
            "assert_name gives",
        )

    def bud_failures_carry_the_call_chain_and_keywords_that_check_nothing_are_information(self):
        """deep.robot with a resource: stored information entries and the call-chain traceback."""
        case = self._case("deep", {"deep.robot": DEEP, "checks.resource": CHECKS})
        command = "bud-runner run-robot deep.robot"
        _, _, results = self._robot(case, "deep.robot")
        self.count(results, 2, command)
        deep, hard = results
        log, check = deep["assertions"]
        self.same(
            {
                "type": log["assertion_type"],
                "info": log["info"],
                "code": log["code_context"],
                "file": _file(log["source_file"]),
                "line": log["source_line"],
            },
            {
                "type": "Log",
                "info": True,
                "code": "Log    checking",
                "file": "checks.resource",
                "line": 4,
            },
            "Log in checks.resource line 4 is stored as information",
            "Log is stored as",
        )
        self.same(
            {
                "type": check["assertion_type"],
                "passed": check["passed"],
                "file": _file(check["source_file"]),
                "line": check["source_line"],
            },
            {"type": "AssertIn", "passed": False, "file": "checks.resource", "line": 5},
            "the failed Should Contain is stored as AssertIn at checks.resource line 5",
            "the failed check is stored as",
        )
        frames = check["traceback"].splitlines()
        self.same(
            [_frame(frames[1]), frames[2], _frame(frames[3]), frames[4], frames[5]],
            [
                'deep.robot", line 6, in Goes deep',
                "    Check Twice    abc    z",
                'checks.resource", line 5, in Check Twice',
                "    Should Contain    ${text}    ${part}",
                deep["error_message"],
            ],
            "the failed check's traceback runs from deep.robot line 6 through Check Twice to the "
            "error",
            "the failed check's traceback frames are",
        )
        support.check(
            self,
            deep["traceback"],
            check["traceback"],
            "the test's traceback is its failed check's traceback",
            "the test's traceback differs from its failed check's traceback",
        )
        broken = hard["assertions"][0]
        self.same(
            {
                "entries": len(hard["assertions"]),
                "type": broken["assertion_type"],
                "passed": broken["passed"],
                "message": broken["message"],
                "info": broken.get("info", "<absent>"),
            },
            {
                "entries": 1,
                "type": "Fail",
                "passed": False,
                "message": "broken wiring",
                "info": "<absent>",
            },
            "Fail is stored as the one failed entry, not information, with its message",
            "Fail is stored as",
        )
        support.says(
            self,
            "broken wiring",
            broken["traceback"].splitlines()[-1],
            "the last line of Fail's traceback",
        )
        self.same(
            {"passed": hard["passed"], "same traceback": hard["traceback"] == broken["traceback"]},
            {"passed": False, "same traceback": True},
            "the test ending in Fail is failed and carries Fail's traceback",
            "the test ending in Fail is stored with",
        )

    def bud_the_result_traceback_is_the_failure_that_ended_the_test(self):
        """A tolerated failure is information; the failure that ended the test is the result's
        error."""
        case = self._case("tolerated", {"tolerated.robot": TOLERATED})
        command = "bud-runner run-robot tolerated.robot"
        _, _, results = self._robot(case, "tolerated.robot")
        self.count(results, 1, command)
        result = results[0]
        self.same(
            result["error_message"],
            "real problem",
            "the error of the test is the failure that ended it, real problem",
            "the error of the test is",
        )
        lines = result["traceback"].splitlines()
        self.same(
            {"last": lines[-1], "frame": _frame(lines[1]).split(", ", 1)[-1]},
            {"last": "real problem", "frame": "line 4, in Recovers then fails"},
            "the test's traceback ends in real problem from line 4 in Recovers then fails",
            "the test's traceback ends as",
        )
        handled, wrapper, real = result["assertions"]
        self.same(
            [
                _fields(wrapper, "assertion_type", "info"),
                _fields(handled, "assertion_type", "info", "passed", "message", "traceback"),
                _fields(real, "assertion_type", "passed"),
            ],
            [
                {"assertion_type": "Run Keyword And Ignore Error", "info": True},
                {
                    "assertion_type": "Fail",
                    "info": True,
                    "passed": True,
                    "message": "first problem",
                    "traceback": None,
                },
                {"assertion_type": "Fail", "passed": False},
            ],
            "the tolerated Fail and its wrapper are information; the last Fail is the failed entry",
            "the entries are stored as",
        )

    def bud_handled_failures_are_information_and_every_failed_test_has_a_failed_entry(self):
        """The seven handled, propagated, retried, missing, empty and teardown cases as stored."""
        case = self._case("handled", {"handled.robot": HANDLED})
        command = "bud-runner run-robot handled.robot"
        _, _, results = self._robot(case, "handled.robot")
        self.count(results, 7, command)
        expects, tries, missing, empty, propagated, retried, teardown = results
        inner = [e for e in expects["assertions"] if e["assertion_type"] == "AssertEqual"]
        self.same(
            {
                "passed": expects["passed"],
                "traceback": expects["traceback"],
                "failed entries": [
                    e["assertion_type"] for e in expects["assertions"] if not e["passed"]
                ],
                "checks not information": [e for e in inner if not e["info"]],
            },
            {
                "passed": True,
                "traceback": None,
                "failed entries": [],
                "checks not information": [],
            },
            "an expected error is information: the test passes and its inner checks are "
            "information",
            "the test with an expected error is stored as",
        )
        support.check_less(
            self,
            0,
            len(inner),
            f"the test with an expected error stores its {len(inner)} inner checks",
            "the test with an expected error stores no inner AssertEqual check",
        )
        self.same(
            {
                "passed": tries["passed"],
                "traceback": tries["traceback"],
                "entries": [(e["assertion_type"], e["info"]) for e in tries["assertions"]],
            },
            {"passed": True, "traceback": None, "entries": [("AssertEqual", True), ("Log", True)]},
            "a failure handled by TRY/EXCEPT is information and the test passes",
            "the TRY test is stored as",
        )
        unknown = missing["assertions"]
        self.same(
            {
                "passed": missing["passed"],
                "entries": [(e["assertion_type"], e["passed"]) for e in unknown],
                "traceback ends": unknown[0]["traceback"].splitlines()[-1] if unknown else None,
            },
            {
                "passed": False,
                "entries": [("This Keyword Does Not Exist", False)],
                "traceback ends": (
                    (missing["error_message"] or "").splitlines()[-1]
                    if missing["error_message"]
                    else None
                ),
            },
            "a missing keyword is the one failed entry, its traceback ending in the test's error",
            "the test calling a missing keyword is stored as",
        )
        fallback = empty["assertions"]
        self.same(
            {
                "passed": empty["passed"],
                "entries": [_fields(e, "assertion_type", "passed", "message") for e in fallback],
                "traceback": empty["traceback"],
            },
            {
                "passed": False,
                "entries": [
                    {"assertion_type": "Fail", "passed": False, "message": empty["error_message"]}
                ],
                "traceback": fallback[0]["traceback"] if fallback else None,
            },
            "a test with an empty body gets one failed Fail entry carrying its error",
            "the test with an empty body is stored as",
        )
        self.same(
            [(e["assertion_type"], e.get("info")) for e in propagated["assertions"]],
            [("AssertEqual", None), ("Run Keyword", True)],
            "a failure through Run Keyword is the failed check, and the wrapper is information",
            "the failure through a wrapper is stored as",
        )
        attempts = [
            e["passed"] for e in retried["assertions"] if e["assertion_type"] == "AssertEqual"
        ]
        failed_entries = [e["passed"] for e in retried["assertions"]].count(False)
        self.same(
            {"attempts": attempts, "failed entries": failed_entries},
            {"attempts": [True, True, False], "failed entries": 1},
            "a retried keyword stores each attempt, and only the last failure is a failed entry",
            "the retried keyword is stored as",
        )
        error = teardown["error_message"] or ""
        for part in ("body broke", "teardown broke"):
            support.says(self, part, error, "the error of the test whose body and teardown fail")
        self.same(
            teardown["traceback"].splitlines()[-1],
            "body broke",
            "the traceback of that test ends in body broke, the failure that ended it",
            "the traceback of the test whose body and teardown fail ends in",
        )

    def bud_a_keyword_ending_in_skip_is_a_skipped_entry(self):
        """Skip If inside a test is stored as a skipped Skip entry; synthetic hooks: a skipped check
        is kept and its wrapper dropped."""
        case = self._case("skip-if", {"skip.robot": SKIP_IF})
        command = "bud-runner run-robot skip.robot"
        _, _, results = self._robot(case, "skip.robot")
        self.count(results, 1, command)
        self.same(
            [(a["assertion_type"], a["skipped"], a["passed"]) for a in results[0]["assertions"]],
            [("Skip", True, True)],
            "Skip If inside a test is stored as one skipped Skip entry",
            "Skip If is stored as",
        )
        listener = BudListener(upload="false")
        listener.start_test(None, None)
        for item in (
            SimpleNamespace(
                name="Skip If", owner="BuiltIn", args=("True",), status="SKIP", message="no bench"
            ),
            SimpleNamespace(
                name="Should Be True", owner="BuiltIn", args=("x",), status="SKIP", message="later"
            ),
            SimpleNamespace(
                name="Run Keyword If", owner="BuiltIn", args=(), status="SKIP", message="no bench"
            ),
        ):
            listener.start_library_keyword(None, None, item)
            listener.end_library_keyword(None, None, item)
        self.same(
            [(a["assertion_type"], a["skipped"], a["passed"]) for a in listener._assertions],
            [("Skip", True, True), ("AssertTrue", True, True)],
            "the library hooks keep Skip If and the skipped check, and drop the Run Keyword If "
            "wrapper",
            "the library hooks record",
        )

    def bud_depth_and_count_caps(self):
        """In-process: the depth cap, the per-test cap (set to 1), NOT RUN, Log and the argument
        limit."""
        listener = BudListener(upload="false")
        listener.start_test(None, None)
        kw = SimpleNamespace(
            name="Should Be True", owner="BuiltIn", args=("x",), status="PASS", message=""
        )
        for _ in range(listener_module.MAX_KEYWORD_DEPTH):
            listener.start_user_keyword(None, None, None)
        listener.start_library_keyword(None, None, kw)
        listener.end_library_keyword(None, None, kw)
        self.same(
            listener._assertions,
            [],
            f"a check nested below MAX_KEYWORD_DEPTH ({listener_module.MAX_KEYWORD_DEPTH}) is not "
            "recorded",
            "below the depth cap the listener records",
        )
        listener._depth = 0
        saved = listener_module.MAX_ASSERTIONS_PER_TEST
        listener_module.MAX_ASSERTIONS_PER_TEST = 1
        try:
            for _ in range(3):
                listener.start_library_keyword(None, None, kw)
                listener.end_library_keyword(None, None, kw)
        finally:
            listener_module.MAX_ASSERTIONS_PER_TEST = saved
        self.same(
            len(listener._assertions),
            1,
            "with MAX_ASSERTIONS_PER_TEST at 1, three checks record one entry",
            "with MAX_ASSERTIONS_PER_TEST at 1, three checks record this many entries",
        )
        listener._assertions = []
        not_run = SimpleNamespace(
            name="Should Be True", owner="BuiltIn", args=(), status="NOT RUN", message=""
        )
        listener.start_library_keyword(None, None, not_run)
        listener.end_library_keyword(None, None, not_run)
        self.same(
            listener._assertions,
            [],
            "a NOT RUN keyword is not recorded",
            "a NOT RUN keyword records",
        )
        log = SimpleNamespace(name="Log", owner="BuiltIn", args=("x",), status="PASS", message="")
        listener.start_library_keyword(None, None, log)
        listener.end_library_keyword(None, None, log)
        self.same(
            [(a["assertion_type"], a["info"]) for a in listener._assertions],
            [("Log", True)],
            "Log is recorded as an information entry",
            "Log is recorded as",
        )
        long_arg = listener_module._short("x" * 600)
        self.same(
            {"length": len(long_arg), "ending": long_arg[-3:]},
            {"length": listener_module.ARG_LIMIT, "ending": "..."},
            f"a 600-character argument is cut to ARG_LIMIT ({listener_module.ARG_LIMIT}) ending "
            "in ...",
            "a 600-character argument becomes",
        )

    def bud_run_robot_command_passes_robot_arguments_and_exit_code(self):
        """run-robot --no-upload --exclude slow bench.robot (Robot takes its options before the data
        sources): Robot's exit code is the failure count and the slow test did not run."""
        case = support.Case("exclude")
        case.write("bench.robot", EXCLUDE)
        command = "bud-runner run-robot --no-upload --exclude slow bench.robot"
        done = case.bud_runner(
            "run-robot",
            "--no-upload",
            "--test-run-id",
            "9",
            "--suite-name",
            "Bench",
            "--exclude",
            "slow",
            "bench.robot",
        )
        support.exits(self, done, 2, f"{command}, with Robot's code for two failed tests,")
        support.says(self, "First fails", done.out, command)
        support.check_not_in(
            self,
            "Slow one",
            done.out,
            f"{command} does not run the slow test",
            f"{command} ran the slow test",
        )
        support.says(self, "2 tests, 0 passed, 2 failed", done.out, f"Robot's summary of {command}")
