"""The Robot Framework listener: a real Robot run mapped to Bud results and uploaded."""

from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
import robot
from typer.testing import CliRunner

from bud_runner import api_client, auth, cli
from bud_runner import robot_listener as listener_module
from bud_runner.robot_listener import BudListener, assert_name, assertion_for, is_check

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


def _run(tmp_path, listener):
    suite = tmp_path / "bench.robot"
    suite.write_text(SUITE, encoding="utf-8")
    rc = robot.run(
        str(suite), listener=listener, outputdir=str(tmp_path / "out"), stdout=StringIO(), stderr=StringIO()
    )
    return rc


def test_a_robot_run_maps_to_bud_results(tmp_path):
    listener = BudListener(upload="false", product_id="4")
    assert _run(tmp_path, listener) == 1

    measured, failed, skipped = listener.results
    assert (measured["test_class"], measured["test_method"]) == ("Bench", "Measures within limit")
    assert measured["passed"] is True and measured["error_message"] is None
    assert measured["metadata"]["tc_id"] == "PRJ-TC-001"
    assert measured["metadata"]["robot_tags"] == ["bench", "bloom:PRJ-TC-001"]
    types = [a["assertion_type"] for a in measured["assertions"]]
    assert types == ["Set Variable", "AssertEqual", "AssertTrue", "AssertIn"]
    assert all("name" not in a and "args" not in a and a["metadata"] == {} for a in measured["assertions"])
    info, numbers, truth, contains = measured["assertions"]
    assert info["info"] is True and info["passed"] is True
    assert "info" not in numbers and numbers["skipped"] is False
    assert (numbers["actual"], numbers["expected"]) == ("3", "3")
    assert numbers["source_file"].endswith("bench.robot") and numbers["source_line"] == 8
    assert numbers["source_function"] == "Measures within limit"
    assert numbers["code_context"] == "Should Be Equal As Numbers    ${measured}    3"
    assert numbers["traceback"] is None and numbers["timestamp"]
    assert (truth["actual"], truth["expected"]) == ("3 < 5", True)
    assert (contains["actual"], contains["expected"]) == ("abc", "b")
    assert (contains["source_function"], contains["source_line"]) == ("Check Twice", 21)
    assert measured["traceback"] is None

    assert failed["passed"] is False and failed["error_message"] == "1 != 2"
    (check,) = failed["assertions"]
    assert check["passed"] is False and check["assertion_type"] == "AssertEqual"
    assert check["traceback"].splitlines()[1:] == [
        f'  File "{check["source_file"]}", line 13, in Fails a check',
        "    Should Be Equal    1    2",
        "1 != 2",
    ]
    assert failed["traceback"] == check["traceback"]
    assert "tc_id" not in failed["metadata"]
    assert skipped["passed"] is True and skipped["metadata"]["skipped"] is True
    assert skipped["error_message"] == "not on this bench"
    (skip,) = skipped["assertions"]
    assert (skip["assertion_type"], skip["skipped"], skip["passed"]) == ("Skip", True, True)
    assert skip["message"] == "not on this bench" and skipped["traceback"] is None
    assert listener.skipped == 1
    assert {p.name for p in listener.files} == {"output.xml", "log.html", "report.html"}

    body = listener.payload("bench-1")
    assert body["test_suite_name"] == "Bench"
    assert body["ref_software_under_test"] == "fw-2.4.1"
    assert body["product_id"] == 4 and body["runner_account"] == "bench-1"
    assert body["test_run_id"] is None
    assert listener.payload("bench-1", 12)["product_id"] == 4
    unset = BudListener(upload="false")
    unset.results = listener.results
    assert unset.payload(None, 12)["product_id"] == 12
    assert "product_id" not in unset.payload(None, None)


class FakeClient:
    def __init__(self, auth_manager, fail=False):
        self.calls = []
        self.fail = fail

    def upload_results_payload(self, payload):
        self.calls.append(("results", payload))
        if self.fail:
            raise RuntimeError("backend down")
        return {"test_run_id": 42}

    def update_test_run(self, run_id, **fields):
        self.calls.append(("update", run_id, fields))

    def upload_artifact(self, path, run_id=None):
        self.calls.append(("artifact", Path(path).name, run_id))


@pytest.fixture
def fake_backend(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    made = []

    def client_factory(auth_manager):
        client = FakeClient(auth_manager, fail=getattr(client_factory, "fail", False))
        made.append(client)
        return client

    monkeypatch.setattr(api_client, "BudAPIClient", client_factory)
    monkeypatch.setattr(auth, "AuthManager", lambda backend_url=None: SimpleNamespace(runner_account="bench-1", product_id=12))
    spooled = []
    monkeypatch.setattr(cli, "_spool_results_payload", lambda payload: spooled.append(payload) or "spool.json")
    return SimpleNamespace(made=made, spooled=spooled, factory=client_factory)


def test_close_uploads_results_skips_and_reports(tmp_path, fake_backend):
    _run(tmp_path, BudListener(backend="https://bud.example"))
    calls = fake_backend.made[0].calls
    assert calls[0][0] == "results" and len(calls[0][1]["results"]) == 3
    assert calls[0][1]["product_id"] == 12
    assert calls[0][1]["test_suite_name"] == "Bench"
    assert calls[1] == ("update", 42, {"skipped_tests": 1})
    assert sorted(c[1] for c in calls[2:]) == ["log.html", "output.xml", "report.html"]
    assert all(c[2] == 42 for c in calls[2:])


def test_failed_upload_is_spooled(tmp_path, fake_backend):
    fake_backend.factory.fail = True
    _run(tmp_path, BudListener(test_run_id="7"))
    assert len(fake_backend.spooled) == 1 and fake_backend.spooled[0]["test_run_id"] == 7
    assert [c[0] for c in fake_backend.made[0].calls] == ["results"]


def test_close_never_raises_and_skips_empty_runs(monkeypatch, capsys):
    listener = BudListener(artifacts="no")
    monkeypatch.setattr(auth, "AuthManager", lambda backend_url=None: SimpleNamespace(runner_account=None, product_id=None))
    monkeypatch.setattr(api_client, "BudAPIClient", lambda a: FakeClient(a))
    listener.close()
    assert "nothing uploaded" in capsys.readouterr().err

    def boom(backend_url=None):
        raise RuntimeError("no vault")

    monkeypatch.setattr(auth, "AuthManager", boom)
    listener.close()
    assert "Could not report the Robot run" in capsys.readouterr().err
    assert listener.upload_artifacts is False


def test_assertion_mapping():
    other = assertion_for("Page Should Contain", "Browser", ["Welcome"], True, "")
    assert other["assertion_type"] == "AssertPageContain" and other["metadata"] == {}
    assert "expected" not in other and other["message"] is None and other["traceback"] is None
    negative = assertion_for("Should Not Be True", "BuiltIn", ["${x}"], False, "boom", {"traceback": "tb"})
    assert (negative["assertion_type"], negative["expected"], negative["actual"]) == ("AssertFalse", False, "${x}")
    assert (negative["message"], negative["traceback"]) == ("boom", "tb")
    short = assertion_for("Should Be Equal", "BuiltIn", ["only-one"], True, "")
    assert short["assertion_type"] == "AssertEqual" and "expected" not in short
    length = assertion_for("Length Should Be", "BuiltIn", ["[1, 2]", "2"], True, "")
    assert (length["assertion_type"], length["expected"]) == ("AssertLength", "2")
    assert is_check("Page Should Contain") and is_check("Length Should Be")
    assert not is_check("Log") and not is_check("Shouldered Task")


def test_assert_names_never_say_should():
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
    assert {name: assert_name(name) for name in names} == names


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


def test_failures_carry_the_call_chain_and_keywords_that_check_nothing_are_information(tmp_path):
    (tmp_path / "checks.resource").write_text(CHECKS, encoding="utf-8")
    suite = tmp_path / "deep.robot"
    suite.write_text(DEEP, encoding="utf-8")
    listener = BudListener(upload="false")
    robot.run(str(suite), listener=listener, outputdir=str(tmp_path / "out"), stdout=StringIO(), stderr=StringIO())
    deep, hard = listener.results

    log, check = deep["assertions"]
    assert (log["assertion_type"], log["info"], log["code_context"]) == ("Log", True, "Log    checking")
    assert log["source_file"].endswith("checks.resource") and log["source_line"] == 4
    assert check["assertion_type"] == "AssertIn" and check["passed"] is False
    assert check["source_file"].endswith("checks.resource") and check["source_line"] == 5
    frames = check["traceback"].splitlines()
    assert frames[1].endswith("deep.robot\", line 6, in Goes deep") and frames[2] == "    Check Twice    abc    z"
    assert frames[3].endswith("checks.resource\", line 5, in Check Twice")
    assert frames[4] == "    Should Contain    ${text}    ${part}"
    assert frames[5] == deep["error_message"] and deep["traceback"] == check["traceback"]

    (broken,) = hard["assertions"]
    assert (broken["assertion_type"], broken["passed"], broken["message"]) == ("Fail", False, "broken wiring")
    assert "info" not in broken and broken["traceback"].endswith("broken wiring")
    assert hard["passed"] is False and hard["traceback"] == broken["traceback"]


TOLERATED = """*** Test Cases ***
Recovers then fails
    Run Keyword And Ignore Error    Fail    first problem
    Fail    real problem
"""


def test_the_result_traceback_is_the_failure_that_ended_the_test(tmp_path):
    suite = tmp_path / "tolerated.robot"
    suite.write_text(TOLERATED, encoding="utf-8")
    listener = BudListener(upload="false")
    robot.run(str(suite), listener=listener, outputdir=str(tmp_path / "out"), stdout=StringIO(), stderr=StringIO())
    (result,) = listener.results
    assert result["error_message"] == "real problem"
    assert result["traceback"].endswith("real problem") and "line 4, in Recovers then fails" in result["traceback"]
    handled, wrapper, real = result["assertions"]
    assert (wrapper["assertion_type"], wrapper["info"]) == ("Run Keyword And Ignore Error", True)
    assert (handled["assertion_type"], handled["info"], handled["passed"]) == ("Fail", True, True)
    assert handled["message"] == "first problem" and handled["traceback"] is None
    assert (real["assertion_type"], real["passed"]) == ("Fail", False)


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


def test_handled_failures_are_information_and_every_failed_test_has_a_failed_entry(tmp_path):
    suite = tmp_path / "handled.robot"
    suite.write_text(HANDLED, encoding="utf-8")
    listener = BudListener(upload="false")
    robot.run(str(suite), listener=listener, outputdir=str(tmp_path / "out"), stdout=StringIO(), stderr=StringIO())
    expects, tries, missing, empty, propagated, retried, teardown = listener.results

    assert expects["passed"] is True and expects["traceback"] is None
    assert all(e["passed"] for e in expects["assertions"])
    inner = [e for e in expects["assertions"] if e["assertion_type"] == "AssertEqual"]
    assert inner and all(e["info"] for e in inner)

    assert tries["passed"] is True and tries["traceback"] is None
    assert [(e["assertion_type"], e["info"]) for e in tries["assertions"]] == [("AssertEqual", True), ("Log", True)]

    assert missing["passed"] is False
    (unknown,) = missing["assertions"]
    assert unknown["assertion_type"] == "This Keyword Does Not Exist" and unknown["passed"] is False
    assert unknown["traceback"].endswith(missing["error_message"])

    assert empty["passed"] is False
    (fallback,) = empty["assertions"]
    assert (fallback["assertion_type"], fallback["passed"], fallback["message"]) == (
        "Fail",
        False,
        empty["error_message"],
    )
    assert empty["traceback"] == fallback["traceback"]

    failures = [e for e in propagated["assertions"] if e["passed"] is False]
    assert [e["assertion_type"] for e in failures] == ["AssertEqual"]
    assert [(e["assertion_type"], e.get("info")) for e in propagated["assertions"]] == [
        ("AssertEqual", None),
        ("Run Keyword", True),
    ]

    attempts = [e for e in retried["assertions"] if e["assertion_type"] == "AssertEqual"]
    assert len(attempts) == 3 and [e["passed"] for e in attempts] == [True, True, False]
    assert [e["passed"] for e in retried["assertions"]].count(False) == 1

    assert "body broke" in teardown["error_message"] and "teardown broke" in teardown["error_message"]
    assert teardown["traceback"].endswith("body broke")


def test_a_keyword_ending_in_skip_is_a_skipped_entry():
    listener = BudListener(upload="false")
    listener.start_test(None, None)
    kw = SimpleNamespace(name="Skip If", owner="BuiltIn", args=("True",), status="SKIP", message="no bench")
    check = SimpleNamespace(name="Should Be True", owner="BuiltIn", args=("x",), status="SKIP", message="later")
    wrapper = SimpleNamespace(name="Run Keyword If", owner="BuiltIn", args=(), status="SKIP", message="no bench")
    for item in (kw, check, wrapper):
        listener.start_library_keyword(None, None, item)
        listener.end_library_keyword(None, None, item)
    assert [(a["assertion_type"], a["skipped"], a["passed"]) for a in listener._assertions] == [
        ("Skip", True, True),
        ("AssertTrue", True, True),
    ]


def test_depth_and_count_caps(monkeypatch):
    listener = BudListener(upload="false")
    listener.start_test(None, None)
    kw = SimpleNamespace(name="Should Be True", owner="BuiltIn", args=("x",), status="PASS", message="")
    for _ in range(listener_module.MAX_KEYWORD_DEPTH):
        listener.start_user_keyword(None, None, None)
    listener.start_library_keyword(None, None, kw)
    listener.end_library_keyword(None, None, kw)
    assert listener._assertions == []
    listener._depth = 0
    monkeypatch.setattr(listener_module, "MAX_ASSERTIONS_PER_TEST", 1)
    for _ in range(3):
        listener.start_library_keyword(None, None, kw)
        listener.end_library_keyword(None, None, kw)
    assert len(listener._assertions) == 1
    not_run = SimpleNamespace(name="Should Be True", owner="BuiltIn", args=(), status="NOT RUN", message="")
    listener._assertions = []
    listener.start_library_keyword(None, None, not_run)
    listener.end_library_keyword(None, None, not_run)
    assert listener._assertions == []
    log = SimpleNamespace(name="Log", owner="BuiltIn", args=("x",), status="PASS", message="")
    listener.start_library_keyword(None, None, log)
    listener.end_library_keyword(None, None, log)
    assert [(a["assertion_type"], a["info"]) for a in listener._assertions] == [("Log", True)]
    long_arg = listener_module._short("x" * 600)
    assert len(long_arg) == listener_module.ARG_LIMIT and long_arg.endswith("...")


def test_run_robot_command_passes_robot_arguments_and_exit_code(tmp_path, monkeypatch):
    suite = tmp_path / "bench.robot"
    suite.write_text(SUITE, encoding="utf-8")
    seen = {}

    def fake_run_cli(args, exit=True):
        seen["args"] = args
        return 3

    monkeypatch.setattr(robot, "run_cli", fake_run_cli)
    result = CliRunner().invoke(
        cli.app,
        ["run-robot", "--no-upload", "--test-run-id", "9", "--suite-name", "Bench", str(suite), "--exclude", "slow"],
    )
    assert result.exit_code == 3
    listener_arg = seen["args"][1]
    assert seen["args"][0] == "--listener"
    assert listener_arg.startswith("bud_runner.robot_listener.BudListener;")
    assert "test_run_id=9" in listener_arg and "upload=false" in listener_arg
    assert "suite_name=Bench" in listener_arg and "backend=" not in listener_arg
    assert seen["args"][2:] == [str(suite), "--exclude", "slow"]


def test_run_robot_replays_the_spool_first(tmp_path, monkeypatch):
    flushed = []
    monkeypatch.setattr(robot, "run_cli", lambda args, exit=True: 0)
    monkeypatch.setattr(cli, "AuthManager", lambda backend_url=None: SimpleNamespace(backend_url=backend_url))
    monkeypatch.setattr(cli, "BudAPIClient", lambda a: "client")
    monkeypatch.setattr(cli, "_flush_spooled_results", lambda *a: flushed.append(a[0]))
    result = CliRunner().invoke(cli.app, ["run-robot", "--backend-url", "https://bud", "tests/"])
    assert result.exit_code == 0 and flushed == ["client"]

    monkeypatch.setattr(cli, "AuthManager", lambda backend_url=None: SimpleNamespace(backend_url=None))
    result = CliRunner().invoke(cli.app, ["run-robot", "tests/"])
    assert result.exit_code == 2 and "No backend URL" in result.output
