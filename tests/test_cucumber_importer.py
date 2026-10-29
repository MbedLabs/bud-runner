"""The Cucumber JSON import: real reports from cucumber-js, Cucumber-JVM and Cucumber-Ruby."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from bud_runner import api_client, auth, cli, reporting
from bud_runner.cucumber_importer import CucumberReport, CucumberReportError, error_text, feature_path, read_report

FIXTURES = Path(__file__).parent / "fixtures" / "cucumber"
RUNNERS = ("cucumber-js.json", "cucumber-jvm.json", "cucumber-ruby.json")


def _report(name, **options):
    return CucumberReport(read_report(FIXTURES / name), FIXTURES / name, **options)


def _by_method(report):
    return {r["test_method"]: r for r in report.results}


def _shape(report):
    return [
        (
            r["test_class"],
            r["test_method"],
            r["passed"],
            r["metadata"]["cucumber_status"],
            r["metadata"].get("tc_id"),
            [(a["assertion_type"], a["passed"], bool(a.get("info")), bool(a["skipped"])) for a in r["assertions"] or []],
        )
        for r in report.results
    ]


def test_the_three_runners_give_the_same_bud_results():
    js, jvm, ruby = (_shape(_report(name)) for name in RUNNERS)
    assert js == jvm == ruby
    assert [row[1] for row in js] == [
        "Voltage within limit",
        "Wrong value",
        "Step raises",
        "Missing step",
        "Hook fails",
        "Pending step",
        "Outline 1",
        "Outline 2",
    ]


@pytest.mark.parametrize("name", RUNNERS)
def test_a_cucumber_run_maps_to_bud_results(name):
    report = _report(name)
    results = _by_method(report)
    assert {r["test_class"] for r in report.results} == {"Bench supply"}
    measured = results["Voltage within limit"]
    assert measured['passed'] is True
    assert measured['error_message'] is None
    assert measured["metadata"]["tc_id"] == "PRJ-TC-001"
    assert measured["metadata"]["cucumber_tags"] == ["bloom:PRJ-001", "smoke", "suite-tag"]
    assert measured["metadata"]["location"].endswith("features/bench.feature:7")
    assert 'test_case_file' not in measured['metadata']
    assert 'skipped' not in measured['metadata']
    steps = [(a["assertion_type"], a["passed"], bool(a.get("info"))) for a in measured["assertions"]]
    assert steps == [
        ("a bench", True, True),
        ("I measure 3", True, True),
        ("the value is 3", True, False),
        ("the value is below 5", True, False),
    ]
    check = measured["assertions"][3]
    assert check['code_context'] == 'And the value is below 5'
    assert check['source_line'] == 10
    assert check["source_function"] == "Voltage within limit"
    assert measured["duration_seconds"] >= 0
    assert report.counts() == {"features": 1, "scenarios": 8, "passed": 3, "failed": 5, "skipped": 0}


@pytest.mark.parametrize(
    "name, message",
    [
        ("cucumber-js.json", "AssertionError [ERR_ASSERTION]\n    + expected - actual\n\n    -2\n    +3"),
        ("cucumber-jvm.json", "java.lang.AssertionError: expected 3"),
        ("cucumber-ruby.json", "expected 3 (RuntimeError)"),
    ],
)
def test_failures_carry_the_runner_message_and_stack_trace(name, message):
    results = _by_method(_report(name))
    wrong = results["Wrong value"]
    failed = wrong["assertions"][2]
    assert (failed["assertion_type"], failed["passed"]) == ("the value is 3", False)
    assert failed['message'] == message
    assert wrong['error_message'] == message
    assert failed['traceback'].startswith(message.split('\n')[0])
    assert len(failed['traceback']) > len(message)
    assert wrong["traceback"] == failed["traceback"]
    raised = results["Step raises"]
    assert raised['assertions'][1]['passed'] is False
    assert raised['assertions'][1]['info'] is True
    assert "bad value" in raised["error_message"]
    missing = results["Missing step"]
    assert missing["error_message"] == "Undefined step: When nobody wrote this"
    assert missing["metadata"]["cucumber_status"] == "undefined"
    pending = results["Pending step"]
    assert pending['passed'] is False
    assert pending['metadata']['cucumber_status'] == 'pending'
    hook = results["Hook fails"]
    assert [(a["assertion_type"], a["passed"]) for a in hook["assertions"]] == [("HookError", False)]
    assert 'hook broke' in hook['error_message']
    assert hook['traceback']


def test_edge_cases_from_a_real_cucumber_js_report():
    report = _report("cucumber-js-edges.json")
    results = _by_method(report)
    assert results["Own tag wins"]["metadata"]["tc_id"] == "PRJ-TC-002"
    assert results["Own tag wins"]["metadata"]["cucumber_tags"] == ["bloom:PRJ-002", "bloom:PRJ-009"]
    assert results["Feature tag only"]["metadata"]["tc_id"] == "PRJ-TC-009"
    ambiguous = results["Ambiguous step"]
    assert ambiguous['passed'] is False
    assert ambiguous['error_message'] == 'Ambiguous step: When I do twice'
    after = results["After hook fails"]
    assert after["passed"] is False
    assert [(a["assertion_type"], a["passed"]) for a in after["assertions"]] == [("a bench", True), ("HookError", False)]
    assert after["error_message"] == "Error: after broke"
    for name, reason in (("Skips itself", "Skipped by the runner"), ("Nothing in it", "Scenario has no steps")):
        skipped = results[name]
        assert skipped['passed'] is True
        assert skipped['metadata']['skipped'] is True
        assert skipped['metadata']['cucumber_status'] == 'skipped'
        assert skipped['error_message'] == reason
        assert skipped['assertions'][-1]['assertion_type'] == 'Skip'
        assert skipped['assertions'][-1]['skipped'] is True
    assert 'Same name (line 33)' in results
    assert 'Same name (line 34)' in results
    german = results["Wert prüfen"]
    assert german['test_class'] == 'Prüfstand'
    assert german['passed'] is True
    assert all(a.get("info") for a in german["assertions"])
    assert report.counts() == {"features": 2, "scenarios": 9, "passed": 5, "failed": 2, "skipped": 2}
    assert reporting.skipped_test_cases(report.results) == 0


def _scenario(steps, after=()):
    return CucumberReport(
        [
            {
                "name": "F",
                "uri": "features/f.feature",
                "elements": [{"type": "scenario", "name": "S", "line": 2, "steps": steps, "after": list(after)}],
            }
        ]
    ).results[0]


def test_hooks_alone_make_no_steps_and_the_worst_status_wins():
    hook_only = _scenario([{"keyword": "Before", "hidden": True, "result": {"status": "passed", "duration": 1}}])
    assert hook_only['passed'] is True
    assert hook_only['metadata']['skipped'] is True
    assert hook_only["error_message"] == "Scenario has no steps"
    undefined_then_failed_hook = _scenario(
        [{"keyword": "When ", "name": "a", "line": 3, "result": {"status": "undefined"}}],
        after=[{"result": {"status": "failed", "error_message": "Error: after broke"}}],
    )
    assert undefined_then_failed_hook["metadata"]["cucumber_status"] == "failed"
    assert undefined_then_failed_hook["error_message"] == "Undefined step: When a"


def test_the_payload_names_the_suite_product_and_run(tmp_path):
    report = _report("cucumber-jvm.json", test_run_id=7, product_id=4, ref_sw_under_test="v2.4.1")
    body = report.payload("station-1", 12)
    assert body['test_run_id'] == 7
    assert body['product_id'] == 4
    assert body['runner_account'] == 'station-1'
    assert body['ref_software_under_test'] == 'v2.4.1'
    assert body['test_suite_name'] == 'Bench supply'
    assert len(body['results']) == 8
    assert _report("cucumber-js-edges.json").payload(None, 12)["test_suite_name"] == "features"
    assert _report("cucumber-js-edges.json").payload(None, 12)["product_id"] == 12
    assert _report("cucumber-js.json", suite_name="Bench").payload(None, None)["test_suite_name"] == "Bench"
    no_uri = tmp_path / "nightly.json"
    no_uri.write_text(json.dumps([{"name": "A", "elements": []}, {"name": "B", "elements": []}]), encoding="utf-8")
    assert CucumberReport(read_report(no_uri), no_uri).payload() is None
    assert CucumberReport(read_report(no_uri), no_uri)._default_suite() == "nightly"


def test_paths_and_messages():
    assert feature_path("file:src/test/resources/features/bench.feature") == "src/test/resources/features/bench.feature"
    assert feature_path("features/bench.feature") == "features/bench.feature"
    assert feature_path(None) is None
    assert feature_path("classpath:com/acme/bench.feature") == "com/acme/bench.feature"
    assert error_text("Error: bad\n    at World.<anonymous> (features/steps.js:5:37)") == "Error: bad"
    assert error_text("java.lang.AssertionError: x\n\tat probe.Steps.valueIs(Steps.java:12)") == "java.lang.AssertionError: x"
    assert error_text("x (RuntimeError)\n./features/steps.rb:5:in `block'") == "x (RuntimeError)"
    jvm = _by_method(_report("cucumber-jvm.json"))["Voltage within limit"]
    assert jvm["metadata"]["location"] == "src/test/resources/features/bench.feature:7"


@pytest.mark.parametrize(
    "content, problem",
    [
        ("{not json", "not valid JSON"),
        ('{"name": "x"}', "a Cucumber JSON report is a list of features"),
        ('[{"name": "x"}]', "feature 1 has no list of elements"),
        ('[{"name": "x", "elements": [{"steps": 3}]}]', "feature 1 has an element whose steps are not a list"),
        ('[{"name": "x", "elements": [3]}]', "feature 1 has an element that is not an object"),
        ('[{"name": "x", "elements": [{"steps": [3]}]}]', "feature 1 has steps that are not objects"),
        ('[{"name": "x", "elements": [{"steps": [{"name": "a", "result": "passed"}]}]}]', "a steps entry whose result"),
        ('[{"name": "x", "elements": [{"before": {"result": {}}}]}]', "whose before are not a list"),
        ('[{"name": "x", "tags": "@a", "elements": []}]', "feature 1 has tags that are not a list"),
    ],
)
def test_a_malformed_report_is_refused(tmp_path, content, problem):
    path = tmp_path / "report.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(CucumberReportError, match=problem):
        read_report(path)


def test_a_report_that_is_not_utf8_is_refused(tmp_path, fake_backend):
    path = tmp_path / "report.json"
    path.write_bytes('[{"name": "x", "elements": []}]'.encode("utf-16"))
    with pytest.raises(CucumberReportError, match="not UTF-8 text"):
        read_report(path)
    result = _import("--report", str(path))
    assert result.exit_code == 2
    assert 'not UTF-8 text' in result.output
    assert fake_backend.made == []


def test_a_missing_report_is_refused(tmp_path):
    with pytest.raises(CucumberReportError, match="cannot read the file"):
        read_report(tmp_path / "absent.json")


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
    monkeypatch.setattr(
        auth, "AuthManager", lambda backend_url=None: SimpleNamespace(runner_account="station-1", product_id=12)
    )
    monkeypatch.setattr(
        cli, "AuthManager", lambda backend_url=None: SimpleNamespace(backend_url=backend_url or "https://bud.example")
    )
    flushed = []
    monkeypatch.setattr(cli, "BudAPIClient", lambda a: "client")
    monkeypatch.setattr(cli, "_flush_spooled_results", lambda *a: flushed.append(a[0]))
    spooled = []
    monkeypatch.setattr(cli, "_spool_results_payload", lambda payload: spooled.append(payload) or "spool.json")
    return SimpleNamespace(made=made, spooled=spooled, flushed=flushed, factory=client_factory)


def _import(*args):
    return CliRunner().invoke(cli.app, ["import-cucumber", *args])


def test_import_uploads_the_report_and_attaches_it(fake_backend):
    result = _import("--report", str(FIXTURES / "cucumber-js-edges.json"), "--backend-url", "https://bud.example")
    assert result.exit_code == 0, result.output
    assert "2 features, 9 scenarios (5 passed, 2 failed, 2 skipped)" in result.output
    assert fake_backend.flushed == ["client"]
    calls = fake_backend.made[0].calls
    assert calls[0][0] == 'results'
    assert len(calls[0][1]['results']) == 9
    assert calls[0][1]['product_id'] == 12
    assert calls[0][1]['runner_account'] == 'station-1'
    assert calls[1:] == [("artifact", "cucumber-js-edges.json", 42)]


def test_import_without_artifacts_and_with_a_run_id(fake_backend):
    result = _import(
        "--report", str(FIXTURES / "cucumber-ruby.json"), "--no-artifacts", "--test-run-id", "7", "--suite-name", "Bench"
    )
    assert result.exit_code == 0, result.output
    body = fake_backend.made[0].calls[0][1]
    assert body['test_run_id'] == 7
    assert body['test_suite_name'] == 'Bench'
    assert [c[0] for c in fake_backend.made[0].calls] == ["results"]


def test_an_upload_that_does_not_reach_bud_exits_1_and_is_spooled(fake_backend):
    fake_backend.factory.fail = True
    result = _import("--report", str(FIXTURES / "cucumber-js.json"))
    assert result.exit_code == 1
    assert len(fake_backend.spooled) == 1
    assert len(fake_backend.spooled[0]['results']) == 8


def test_a_malformed_report_exits_2_before_anything_is_sent(fake_backend, tmp_path):
    bad = tmp_path / "report.json"
    bad.write_text("{not json", encoding="utf-8")
    result = _import("--report", str(bad))
    assert result.exit_code == 2
    assert f"✗ {bad}: not valid JSON" in result.output
    assert fake_backend.flushed == []
    assert fake_backend.made == []


def test_a_report_with_the_wrong_shape_inside_exits_2(fake_backend, tmp_path):
    bad = tmp_path / "report.json"
    bad.write_text('[{"name": "x", "elements": [{"steps": [{"name": "a", "result": "passed"}]}]}]', encoding="utf-8")
    result = _import("--report", str(bad))
    assert result.exit_code == 2
    assert 'result is not an object' in result.output
    assert fake_backend.flushed == []
    assert fake_backend.made == []


def test_no_upload_and_empty_reports_send_nothing(fake_backend, tmp_path):
    result = _import("--report", str(FIXTURES / "cucumber-jvm.json"), "--no-upload")
    assert result.exit_code == 0
    assert '1 features, 8 scenarios (3 passed, 5 failed, 0 skipped)' in result.output
    empty = tmp_path / "empty.json"
    empty.write_text("[]", encoding="utf-8")
    result = _import("--report", str(empty))
    assert result.exit_code == 0
    assert '0 features, 0 scenarios' in result.output
    assert fake_backend.made == []
    assert fake_backend.flushed == []


def test_import_needs_a_backend_to_upload(monkeypatch):
    monkeypatch.setattr(cli, "AuthManager", lambda backend_url=None: SimpleNamespace(backend_url=None))
    result = _import("--report", str(FIXTURES / "cucumber-js.json"))
    assert result.exit_code == 2
    assert 'No backend URL configured' in result.output
