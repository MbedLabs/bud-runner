"""The Behave formatter: real Behave runs mapped to Bud results and uploaded."""

import os
import sys
from types import SimpleNamespace

import pytest
from behave.__main__ import main as behave_main
from typer.testing import CliRunner

from bud_runner import api_client, auth, cli
from bud_runner.behave_formatter import BudFormatter

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

STEPS = '''
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
'''

ENVIRONMENT = '''
def before_scenario(context, scenario):
    if "skipme" in scenario.tags:
        scenario.skip("not on this bench")
    if "hookfail" in scenario.tags:
        raise RuntimeError("hook broke")
'''

SECOND_FEATURE = """@bloom:PRJ-003
Feature: Bench clock
  Scenario: Clock runs
    Given a bench
"""

CAPTURED = []


class Capture(BudFormatter):
    """BudFormatter that keeps itself for the test to read after the run."""

    def close(self):
        super().close()
        CAPTURED.append(self)


@pytest.fixture
def project(tmp_path, monkeypatch):
    features = tmp_path / "features"
    (features / "steps").mkdir(parents=True)
    (features / "bench.feature").write_text(FEATURE, encoding="utf-8")
    (features / "steps" / "bench_steps.py").write_text(STEPS, encoding="utf-8")
    (features / "environment.py").write_text(ENVIRONMENT, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    CAPTURED.clear()
    return tmp_path


def _run(*args):
    rc = behave_main(
        [
            "-f",
            "tests.test_behave_formatter:Capture",
            "-o",
            os.devnull,
            "--no-summary",
            "--tags=-@excluded",
            *args,
            "features",
        ]
    )
    return rc, CAPTURED[-1]


def _by_method(formatter):
    return {r["test_method"]: r for r in formatter.results}


def _steps(result):
    return [(a["assertion_type"], a["passed"], bool(a.get("info")), bool(a["skipped"])) for a in result["assertions"]]


def test_a_behave_run_maps_to_bud_results(project):
    rc, formatter = _run("-D", "bud_upload=false")
    assert rc == 1
    results = _by_method(formatter)
    assert list(results) == [
        "Voltage within limit",
        "Wrong value",
        "Step raises",
        "Missing step",
        "Skipped by hook",
        "Hook fails",
        "Outline 1 -- @1.1",
        "Outline 2 -- @1.2",
    ]
    assert {r["test_class"] for r in formatter.results} == {"Bench supply"}
    measured = results["Voltage within limit"]
    assert measured['passed'] is True
    assert measured['error_message'] is None
    assert measured["metadata"]["tc_id"] == "PRJ-TC-001"
    assert measured["metadata"]["behave_tags"] == ["bloom:PRJ-TC-001", "smoke"]
    assert measured["metadata"]["location"] == "features/bench.feature:6"
    assert 'test_case_file' not in measured['metadata']
    assert 'test_case_class' not in measured['metadata']
    assert _steps(measured) == [
        ("a bench", True, True, False),
        ("I measure 3", True, True, False),
        ("the value is 3", True, False, False),
        ("the value is below 5", True, False, False),
    ]
    check = measured["assertions"][3]
    assert check["code_context"] == "And the value is below 5"
    assert (check["source_file"], check["source_line"]) == ("features/bench.feature", 9)
    assert check["source_function"] == "Voltage within limit"
    outline = results["Outline 2 -- @1.2"]
    assert outline["passed"] is True
    assert [s[0] for s in _steps(outline)] == ["a bench", "I measure 2", "the value is 2"]


def test_failures_carry_message_and_traceback(project):
    rc, formatter = _run("-D", "bud_upload=false")
    results = _by_method(formatter)
    wrong = results["Wrong value"]
    assert wrong["passed"] is False
    assert _steps(wrong) == [
        ("a bench", True, True, False),
        ("I measure 2", True, True, False),
        ("the value is 3", False, False, False),
    ]
    failed = wrong["assertions"][2]
    assert failed['message'] == 'expected 3'
    assert wrong['error_message'] == 'expected 3'
    assert 'AssertionError' in failed['traceback']
    assert 'bench_steps.py' in failed['traceback']
    assert wrong["traceback"] == failed["traceback"]
    raised = results["Step raises"]
    assert raised['passed'] is False
    assert raised['error_message'] == 'ValueError: bad value'
    assert _steps(raised)[1] == ("I break", False, True, False)
    assert "ValueError: bad value" in raised["assertions"][1]["traceback"]
    assert "ValueError: bad value" in raised["traceback"]
    missing = results["Missing step"]
    assert missing["passed"] is False
    assert missing["error_message"] == "Undefined step: When nobody wrote this"
    assert _steps(missing)[1] == ("nobody wrote this", False, True, False)


def test_skips_hook_errors_and_tag_selection(project):
    rc, formatter = _run("-D", "bud_upload=false")
    results = _by_method(formatter)
    assert "Excluded by tags" not in results
    skipped = results["Skipped by hook"]
    assert skipped['passed'] is True
    assert skipped['metadata']['skipped'] is True
    assert skipped["error_message"] == "not on this bench"
    assert _steps(skipped) == [("Skip", True, False, True)]
    assert formatter.skipped == 1
    hook = results["Hook fails"]
    assert hook["passed"] is False
    assert [(a["assertion_type"], a["passed"]) for a in hook["assertions"]] == [("HookError", False)]
    assert "RuntimeError: hook broke" in hook["error_message"]
    assert "Traceback (most recent call last)" in hook["traceback"]
    assert 'environment.py' in hook['traceback']
    assert 'hook broke' in hook['traceback']
    assert hook["assertions"][0]["traceback"] == hook["traceback"]


def test_the_payload_names_the_suite_product_and_run(project):
    rc, formatter = _run(
        "-D",
        "bud_upload=false",
        "-D",
        "bud_test_run_id=7",
        "-D",
        "bud_product_id=4",
        "-D",
        "bud_ref_sw_under_test=v2.4.1",
    )
    body = formatter.payload("bench-1", 12)
    assert body['test_run_id'] == 7
    assert body['product_id'] == 4
    assert body['runner_account'] == 'bench-1'
    assert body['ref_software_under_test'] == 'v2.4.1'
    assert body["test_suite_name"] == "Bench supply"
    assert len(body["results"]) == 8
    (project / "features" / "clock.feature").write_text(SECOND_FEATURE, encoding="utf-8")
    rc, formatter = _run("-D", "bud_upload=false")
    assert formatter.payload(None, 12)["test_suite_name"] == "features"
    assert formatter.payload(None, 12)["product_id"] == 12
    assert _by_method(formatter)["Clock runs"]["metadata"]["tc_id"] == "PRJ-TC-003"
    assert _by_method(formatter)["Clock runs"]["metadata"]["behave_tags"] == ["bloom:PRJ-003"]
    behave_main(["-f", "tests.test_behave_formatter:Capture", "-o", os.devnull, "--no-summary", "-D", "bud_upload=false"])
    assert CAPTURED[-1].payload(None, None)["test_suite_name"] == "features"
    rc, formatter = _run("-D", "bud_upload=false", "-D", "bud_suite_name=Bench")
    assert formatter.payload(None, None)["test_suite_name"] == "Bench"


class FakeClient:
    def __init__(self, auth_manager, fail=False):
        self.calls = []
        self.fail = fail

    def upload_results_payload(self, payload):
        self.calls.append(("results", payload))
        if self.fail:
            raise RuntimeError("backend down")
        return {"test_run_id": 42}

    def update_test_run(self, run_id, skipped_tests=None):
        self.calls.append(("update", run_id, {"skipped_tests": skipped_tests}))


@pytest.fixture
def fake_backend(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    made = []

    def client_factory(auth_manager):
        client = FakeClient(auth_manager, fail=getattr(client_factory, "fail", False))
        made.append(client)
        return client

    monkeypatch.setattr(api_client, "BudAPIClient", client_factory)
    monkeypatch.setattr(
        auth, "AuthManager", lambda backend_url=None: SimpleNamespace(runner_account="bench-1", product_id=12)
    )
    spooled = []
    monkeypatch.setattr(cli, "_spool_results_payload", lambda payload: spooled.append(payload) or "spool.json")
    return SimpleNamespace(made=made, spooled=spooled, factory=client_factory)


def test_the_run_is_uploaded_without_a_skipped_count_when_no_feature_is_all_skipped(project, fake_backend, capsys):
    rc, formatter = _run("-D", "bud_backend_url=https://bud.example")
    assert rc == 1
    calls = fake_backend.made[0].calls
    assert calls[0][0] == 'results'
    assert len(calls[0][1]['results']) == 8
    assert calls[0][1]['product_id'] == 12
    assert calls[0][1]['runner_account'] == 'bench-1'
    assert [c[0] for c in calls] == ["results"]
    assert "Behave results uploaded to Bud run 42" in capsys.readouterr().err


def test_a_failed_upload_is_spooled(project, fake_backend):
    fake_backend.factory.fail = True
    _run("-D", "bud_test_run_id=7")
    assert len(fake_backend.spooled) == 1
    assert fake_backend.spooled[0]['test_run_id'] == 7
    assert [c[0] for c in fake_backend.made[0].calls] == ["results"]


def test_an_upload_error_never_changes_the_exit_code(project, monkeypatch, capsys):
    def boom(backend_url=None):
        raise RuntimeError("no credentials")

    monkeypatch.setattr(auth, "AuthManager", boom)
    (project / "features" / "bench.feature").write_text(SECOND_FEATURE, encoding="utf-8")
    rc, formatter = _run()
    assert rc == 0
    assert "Could not report the Behave run to Bud: no credentials" in capsys.readouterr().err


def test_run_behave_command_passes_behave_arguments_and_exit_code(monkeypatch):
    import behave.__main__ as behave_entry

    seen = {}

    def fake_main(args):
        seen["args"] = args
        return 1

    monkeypatch.setattr(behave_entry, "main", fake_main)
    result = CliRunner().invoke(
        cli.app,
        ["run-behave", "--no-upload", "--test-run-id", "5", "--suite-name", "Bench", "features/", "--tags=@smoke"],
    )
    assert result.exit_code == 1
    args = seen["args"]
    assert args[:4] == ["-f", "bud_runner.behave_formatter:BudFormatter", "-o", os.devnull]
    assert args[4:6] == ["-f", "pretty"]
    assert 'bud_test_run_id=5' in args
    assert 'bud_suite_name=Bench' in args
    assert 'bud_upload=false' in args
    assert args[-2:] == ["features/", "--tags=@smoke"]
    CliRunner().invoke(cli.app, ["run-behave", "--no-upload", "-f", "progress", "features/"])
    assert 'pretty' not in seen['args']
    assert seen['args'][-3:] == ['-f', 'progress', 'features/']


def test_run_behave_names_the_extra_when_behave_is_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "behave.__main__", None)
    result = CliRunner().invoke(cli.app, ["run-behave", "--no-upload", "features/"])
    assert result.exit_code == 2
    assert "pip install 'bud-runner[behave]'" in result.output


def test_run_behave_replays_the_spool_first_and_needs_a_backend(monkeypatch):
    import behave.__main__ as behave_entry

    flushed = []
    monkeypatch.setattr(behave_entry, "main", lambda args: 0)
    monkeypatch.setattr(cli, "AuthManager", lambda backend_url=None: SimpleNamespace(backend_url=backend_url))
    monkeypatch.setattr(cli, "BudAPIClient", lambda a: "client")
    monkeypatch.setattr(cli, "_flush_spooled_results", lambda *a: flushed.append(a[0]))
    result = CliRunner().invoke(cli.app, ["run-behave", "--backend-url", "https://bud.example", "features/"])
    assert result.exit_code == 0
    assert flushed == ['client']
    monkeypatch.setattr(cli, "AuthManager", lambda backend_url=None: SimpleNamespace(backend_url=None))
    result = CliRunner().invoke(cli.app, ["run-behave", "features/"])
    assert result.exit_code == 2


def test_run_behave_runs_behave_with_the_console_output_kept(project):
    result = CliRunner().invoke(cli.app, ["run-behave", "--no-upload", "--tags=-@excluded", "features"])
    assert result.exit_code == 1
    assert "Scenario: Voltage within limit" in result.output
