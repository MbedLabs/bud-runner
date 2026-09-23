"""The Robot Framework listener: a real Robot run mapped to Bud results and uploaded."""

from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
import robot
from typer.testing import CliRunner

from bud_runner import api_client, auth, cli
from bud_runner import robot_listener as listener_module
from bud_runner.robot_listener import BudListener, assertion_for

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
    names = [a["name"] for a in measured["assertions"]]
    assert names == ["Set Variable", "Should Be Equal As Numbers", "Should Be True", "Should Contain"]
    numbers = measured["assertions"][1]
    assert (numbers["actual"], numbers["expected"], numbers["args"]) == ("3", "3", ["3", "3"])
    truth = measured["assertions"][2]
    assert (truth["actual"], truth["expected"]) == ("3 < 5", True)
    assert measured["assertions"][3]["args"] == ["abc", "b"]

    assert failed["passed"] is False and failed["error_message"] == "1 != 2"
    assert failed["assertions"][0]["passed"] is False
    assert "tc_id" not in failed["metadata"]
    assert skipped["passed"] is True and skipped["metadata"]["skipped"] is True
    assert skipped["error_message"] == "not on this bench"
    assert listener.skipped == 1
    assert {p.name for p in listener.files} == {"output.xml", "log.html", "report.html"}

    body = listener.payload("bench-1")
    assert body["test_suite_name"] == "Bench"
    assert body["ref_software_under_test"] == "fw-2.4.1"
    assert body["product_id"] == 4 and body["runner_account"] == "bench-1"
    assert body["test_run_id"] is None


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
    monkeypatch.setattr(auth, "AuthManager", lambda backend_url=None: SimpleNamespace(runner_account="bench-1"))
    spooled = []
    monkeypatch.setattr(cli, "_spool_results_payload", lambda payload: spooled.append(payload) or "spool.json")
    return SimpleNamespace(made=made, spooled=spooled, factory=client_factory)


def test_close_uploads_results_skips_and_reports(tmp_path, fake_backend):
    _run(tmp_path, BudListener(backend="https://bud.example"))
    calls = fake_backend.made[0].calls
    assert calls[0][0] == "results" and len(calls[0][1]["results"]) == 3
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
    monkeypatch.setattr(auth, "AuthManager", lambda backend_url=None: SimpleNamespace(runner_account=None))
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
    assert "expected" not in other and other["metadata"] == {"library": "Browser"}
    assert other["message"] is None
    negative = assertion_for("Should Not Be True", "BuiltIn", ["${x}"], False, "boom")
    assert (negative["expected"], negative["message"]) == (False, "boom")
    short = assertion_for("Should Be Equal", "BuiltIn", ["only-one"], True, "")
    assert "expected" not in short


def test_depth_and_count_caps(monkeypatch):
    listener = BudListener(upload="false")
    listener.start_test(None, None)
    kw = SimpleNamespace(name="Log", owner="BuiltIn", args=("x",), status="PASS", message="")
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
    not_run = SimpleNamespace(name="Log", owner="BuiltIn", args=(), status="NOT RUN", message="")
    listener._assertions = []
    listener.start_library_keyword(None, None, not_run)
    listener.end_library_keyword(None, None, not_run)
    assert listener._assertions == []
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
