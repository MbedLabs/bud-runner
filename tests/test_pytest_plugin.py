"""The pytest plugin: real pytest runs mapped to Bud results and uploaded."""

import sys
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from bud_runner import api_client, auth, cli
from bud_runner.pytest_plugin import PLUGIN_NAME, comparison


PLUGIN = ("-p", "bud_runner.pytest_plugin", "-o", "enable_assertion_pass_hook=true")

SUITE = '''
import pytest


@pytest.mark.bloom("PRJ-TC-001")
def test_measures(bud_assert):
    measured = 3
    assert measured == 3
    assert "b" in "abc", "contains b"
    assert measured
    assert measured != 4
    assert measured < 5
    assert measured > 1
    assert "z" not in "abc"
    bud_assert.assertEqual(measured, 3)
    bud_assert.assertIn("b", "abc")
    bud_assert.assertInRange(measured, 1, 5)


def test_fails_a_check():
    values = [1, 2]
    assert values == [1, 3]


def test_soft_failure_goes_on(bud_assert):
    bud_assert.assertEqual(1, 2, "first")
    bud_assert.assertTrue(True, "after")


def test_abort_on_fail_stops(bud_assert):
    bud_assert.assertEqual(1, 2, "stop", abort_on_fail=True)
    bud_assert.assertTrue(True, "never")


def test_raises():
    raise ValueError("bad value")


def test_skipped(bud_assert):
    bud_assert.skipAssert("not measured here")
    pytest.skip("not on this bench")


@pytest.mark.xfail(reason="known issue")
def test_expected_failure():
    assert False


class TestGroup:
    @pytest.mark.bloom("PRJ-002")
    def test_method(self):
        assert 2 > 1


@pytest.fixture
def broken():
    raise RuntimeError("fixture broke")


def test_setup_error(broken):
    pass


def test_values(bud_assert):
    name = "abc"
    count = 0
    items = [1, 2]
    assert name
    bud_assert.assertTrue(name)
    assert items
    bud_assert.assertTrue(items)
    assert not count
    bud_assert.assertTrue(not count)
    assert count <= 1
    bud_assert.assertTrue(count <= 1)


def test_value_fails():
    empty = ""
    assert empty


@pytest.fixture
def checked_after(bud_assert):
    yield
    bud_assert.assertEqual(1, 2, "after")


def test_teardown_check(checked_after):
    pass


@pytest.mark.xfail(reason="soft check expected to fail")
def test_expected_soft_failure(bud_assert):
    bud_assert.assertEqual(1, 2, "soft")


@pytest.mark.xfail(reason="strict soft check", strict=True)
def test_expected_strict_soft_failure(bud_assert):
    bud_assert.assertEqual(1, 2, "strict soft")


@pytest.mark.xfail(reason="aborted check expected to fail", strict=True)
def test_expected_abort(bud_assert):
    bud_assert.assertEqual(1, 2, "abort", abort_on_fail=True)
'''


class _Grab:
    """Keeps the inner run's config, from which the reporter is read after the run."""

    config = None

    def pytest_configure(self, config):
        self.config = config


def _run(pytester, *args):
    pytester.makepyfile(test_bench=SUITE)
    grab = _Grab()
    rec = pytester.inline_run(*PLUGIN, *args, plugins=[grab])
    return rec, grab.config.pluginmanager.get_plugin(PLUGIN_NAME)


def _by_method(reporter):
    return {r["test_method"]: r for r in reporter.results}


def _core(entry):
    keys = ("passed", "skipped", "assertion_type", "expected", "actual", "result")
    return {k: entry[k] for k in keys}


def test_a_pytest_run_maps_to_bud_results(pytester):
    rec, reporter = _run(pytester, "--bud-no-upload")
    results = _by_method(reporter)
    assert len(reporter.results) == 15
    measured = results["test_measures"]
    assert measured["test_class"] == "test_bench.py::test_measures"
    assert measured['passed'] is True
    assert measured['error_message'] is None
    assert measured["metadata"]["tc_id"] == "PRJ-TC-001"
    assert measured["metadata"]["pytest_outcome"] == "passed"
    assert "bloom" in measured["metadata"]["pytest_markers"]
    assert 'test_case_file' not in measured['metadata']
    assert 'test_case_class' not in measured['metadata']
    types = [a["assertion_type"] for a in measured["assertions"]]
    assert types == [
        "AssertEqual",
        "AssertIn",
        "AssertTrue",
        "AssertNotEqual",
        "AssertLess",
        "AssertGreater",
        "AssertNotIn",
        "AssertEqual",
        "AssertIn",
        "AssertInRange",
    ]
    assert all(a["passed"] for a in measured["assertions"])
    grouped = results["test_method"]
    assert grouped["test_class"] == "test_bench.py::TestGroup::test_method"
    assert grouped["metadata"]["tc_id"] == "PRJ-TC-002"
    assert len({r["test_class"] for r in reporter.results}) == 15


def test_assert_statements_and_bud_assert_give_the_same_records(pytester):
    rec, reporter = _run(pytester, "--bud-no-upload")
    entries = _by_method(reporter)["test_measures"]["assertions"]
    plain_equal, plain_in, plain_true = entries[0], entries[1], entries[2]
    fixture_equal, fixture_in = entries[7], entries[8]
    assert _core(plain_equal) == _core(fixture_equal)
    assert _core(plain_equal) == {
        "passed": True,
        "skipped": False,
        "assertion_type": "AssertEqual",
        "expected": "3",
        "actual": "3",
        "result": "3",
    }
    assert _core(plain_in) == _core(fixture_in)
    assert plain_in['expected'] == "'b' in container"
    assert plain_in['actual'] == 'abc'
    assert plain_in["message"] == "contains b"
    assert (plain_true["expected"], plain_true["actual"]) == ("True", "3")
    assert set(plain_equal) == set(fixture_equal)
    assert plain_equal['source_file'] == 'test_bench.py'
    assert plain_equal['source_line'] == 7
    assert plain_equal["source_function"] == "test_measures"
    assert plain_equal["code_context"] == "assert measured == 3"
    assert fixture_equal["code_context"] == "bud_assert.assertEqual(measured, 3)"
    lt, gt, not_in = entries[4], entries[5], entries[6]
    assert (lt["expected"], lt["actual"]) == ("< 5", "3")
    assert (gt["expected"], gt["actual"]) == ("> 1", "3")
    assert not_in["expected"] == "'z' NOT in container"


def test_an_asserted_value_is_recorded_as_bud_assert_records_it(pytester):
    rec, reporter = _run(pytester, "--bud-no-upload")
    entries = _by_method(reporter)["test_values"]["assertions"]
    pairs = [(entries[i], entries[i + 1]) for i in range(0, len(entries), 2)]
    assert len(pairs) == 4
    for plain, fixture in pairs:
        assert _core(plain) == _core(fixture)
    assert [plain["actual"] for plain, _ in pairs] == ["abc", "[1, 2]", "True", "True"]
    assert all(plain["assertion_type"] == "AssertTrue" for plain, _ in pairs)
    (failed,) = _by_method(reporter)["test_value_fails"]["assertions"]
    assert (failed["assertion_type"], failed["passed"], failed["expected"], failed["actual"]) == (
        "AssertTrue",
        False,
        "True",
        "",
    )


def test_a_failed_assert_carries_expected_actual_message_and_traceback(pytester):
    rec, reporter = _run(pytester, "--bud-no-upload")
    failed = _by_method(reporter)["test_fails_a_check"]
    assert failed["passed"] is False
    assert failed["metadata"]["pytest_outcome"] == "failed"
    (entry,) = failed["assertions"]
    assert entry['passed'] is False
    assert entry['assertion_type'] == 'AssertEqual'
    assert (entry["expected"], entry["actual"]) == ("[1, 3]", "[1, 2]")
    assert entry["message"].startswith("assert [1, 2] == [1, 3]")
    assert entry["code_context"] == "assert values == [1, 3]"
    assert 'test_bench.py' in entry['traceback']
    assert 'AssertionError' in entry['traceback']
    assert failed["error_message"] == entry["message"]
    assert failed["traceback"] == entry["traceback"]


def test_a_failed_bud_assert_goes_on_and_fails_the_test(pytester):
    rec, reporter = _run(pytester, "--bud-no-upload")
    reports = {r.nodeid.split("::")[-1]: r for r in rec.getreports("pytest_runtest_logreport") if r.when == "call"}
    assert reports["test_soft_failure_goes_on"].failed
    soft = _by_method(reporter)["test_soft_failure_goes_on"]
    assert soft["passed"] is False
    assert [(a["assertion_type"], a["passed"]) for a in soft["assertions"]] == [
        ("AssertEqual", False),
        ("AssertTrue", True),
    ]
    assert soft["error_message"] == "[AssertEqual] EXPECTED: 2 | ACTUAL: 1 | MESSAGE: first"
    assert soft["assertions"][0]["traceback"]
    abort = _by_method(reporter)["test_abort_on_fail_stops"]
    assert reports["test_abort_on_fail_stops"].failed
    assert [(a["assertion_type"], a["passed"]) for a in abort["assertions"]] == [("AssertEqual", False)]
    assert abort["error_message"] == "[AssertEqual] EXPECTED: 2 | ACTUAL: 1 | MESSAGE: stop"
    teardown = {r.nodeid.split("::")[-1]: r for r in rec.getreports("pytest_runtest_logreport") if r.when == "teardown"}
    assert teardown["test_teardown_check"].failed
    after = _by_method(reporter)["test_teardown_check"]
    assert after['passed'] is False
    assert after['metadata']['pytest_outcome'] == 'error'
    assert after["error_message"] == "[AssertEqual] EXPECTED: 2 | ACTUAL: 1 | MESSAGE: after"


def test_a_failed_bud_assert_in_an_xfail_test_is_its_expected_failure(pytester):
    rec, reporter = _run(pytester, "--bud-no-upload")
    by_phase = {}
    for r in rec.getreports("pytest_runtest_logreport"):
        by_phase[(r.nodeid.split("::")[-1], r.when)] = r
    results = _by_method(reporter)
    for name in ("test_expected_soft_failure", "test_expected_strict_soft_failure", "test_expected_abort"):
        call, teardown = by_phase[(name, "call")], by_phase[(name, "teardown")]
        assert call.skipped
        assert hasattr(call, 'wasxfail')
        assert teardown.passed
        result = results[name]
        assert result['metadata']['pytest_outcome'] == 'xfailed'
        assert result['metadata']['skipped'] is True
        assert [(a["assertion_type"], a["passed"]) for a in result["assertions"]][0] == ("AssertEqual", False)
    assert results["test_expected_strict_soft_failure"]["error_message"] == "strict soft check"
    rec.assertoutcome(passed=4, skipped=5, failed=7)


def test_exceptions_skips_xfail_and_fixture_errors(pytester):
    rec, reporter = _run(pytester, "--bud-no-upload")
    results = _by_method(reporter)
    raised = results["test_raises"]
    (entry,) = raised["assertions"]
    assert (entry["assertion_type"], entry["passed"], entry["message"]) == ("ValueError", False, "bad value")
    assert entry['source_function'] == 'test_raises'
    assert 'ValueError' in entry['traceback']
    assert raised["error_message"] == "bad value"
    skipped = results["test_skipped"]
    assert skipped['passed'] is True
    assert skipped['metadata']['skipped'] is True
    assert skipped["metadata"]["pytest_outcome"] == "skipped"
    assert skipped["error_message"] == "not on this bench"
    assert [(a["assertion_type"], a["skipped"], a["message"]) for a in skipped["assertions"]] == [
        ("Skip", True, "not measured here"),
        ("Skip", True, "not on this bench"),
    ]
    xfail = results["test_expected_failure"]
    assert xfail['metadata']['pytest_outcome'] == 'xfailed'
    assert xfail['metadata']['skipped'] is True
    assert [a["assertion_type"] for a in xfail["assertions"]] == ["Skip"]
    setup = results["test_setup_error"]
    assert setup['passed'] is False
    assert setup['metadata']['pytest_outcome'] == 'error'
    (entry,) = setup["assertions"]
    assert entry['assertion_type'] == 'RuntimeError'
    assert entry['metadata'] == {'phase': 'setup'}
    assert setup["error_message"] == "fixture broke"
    assert reporter.skipped == 5


def test_the_payload_names_the_suite_product_and_run(pytester):
    rec, reporter = _run(
        pytester, "--bud-no-upload", "--bud-test-run-id=7", "--bud-product-id=4", "--bud-ref-sw-under-test=v2.4.1"
    )
    body = reporter.payload("bench-1", 12)
    assert body['test_run_id'] == 7
    assert body['product_id'] == 4
    assert body["runner_account"] == "bench-1"
    assert body["ref_software_under_test"] == "v2.4.1"
    assert body["test_suite_name"] == pytester.path.name
    assert len(body["results"]) == 15
    rec, reporter = _run(pytester, "--bud-no-upload", "--bud-suite-name=Bench")
    assert reporter.payload(None, 12)["test_suite_name"] == "Bench"
    assert reporter.payload(None, 12)["product_id"] == 12


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


def test_the_session_is_uploaded_with_the_skipped_count(pytester, fake_backend, capsys):
    _run(pytester, "--bud-backend-url=https://bud.example")
    calls = fake_backend.made[0].calls
    assert calls[0][0] == 'results'
    assert len(calls[0][1]['results']) == 15
    assert calls[0][1]['product_id'] == 12
    assert calls[0][1]['runner_account'] == 'bench-1'
    assert calls[1] == ("update", 42, {"skipped_tests": 5})
    assert "pytest results uploaded to Bud run 42" in capsys.readouterr().err


def test_a_failed_upload_is_spooled(pytester, fake_backend):
    fake_backend.factory.fail = True
    _run(pytester, "--bud-test-run-id=7")
    assert len(fake_backend.spooled) == 1
    assert fake_backend.spooled[0]['test_run_id'] == 7
    assert [c[0] for c in fake_backend.made[0].calls] == ["results"]


def test_an_upload_error_never_changes_the_exit_code(pytester, monkeypatch, capsys):
    def boom(backend_url=None):
        raise RuntimeError("no credentials")

    monkeypatch.setattr(auth, "AuthManager", boom)
    pytester.makepyfile(test_one="def test_one():\n    assert 1 == 1\n")
    rec = pytester.inline_run(*PLUGIN)
    assert rec.ret == 0
    assert "Could not report the pytest run to Bud: no credentials" in capsys.readouterr().err


def test_the_plugin_warns_when_the_pass_hook_is_off(pytester):
    pytester.makepyfile(test_one="def test_one():\n    assert 1 == 1\n")
    result = pytester.runpytest("-p", "bud_runner.pytest_plugin", "--bud-no-upload")
    result.stdout.fnmatch_lines(["*enable_assertion_pass_hook is off*"])
    assert result.ret == 0


def test_comparison_follows_budtestlibrary():
    assert comparison("==", 1, 2) == ("AssertEqual", 2, 1)
    assert comparison("!=", 1, 2) == ("AssertNotEqual", "!= 2", 1)
    assert comparison("in", "a", "abc") == ("AssertIn", "'a' in container", "abc")
    assert comparison("not in", "a", "abc") == ("AssertNotIn", "'a' NOT in container", "abc")
    assert comparison("<", 1, 2) == ("AssertLess", "< 2", 1)
    assert comparison(">", 1, 2) == ("AssertGreater", "> 2", 1)


def test_run_pytest_command_passes_pytest_arguments_and_exit_code(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    seen = {}

    def fake_main(args):
        seen["args"] = args
        seen["prefix"] = sys.pycache_prefix
        return 1

    monkeypatch.setattr(pytest, "main", fake_main)
    before = sys.pycache_prefix
    result = CliRunner().invoke(
        cli.app,
        ["run-pytest", "--no-upload", "--test-run-id", "5", "--suite-name", "Bench", "tests/", "-k", "smoke"],
    )
    assert result.exit_code == 1
    assert seen["args"][:4] == ["-p", "bud_runner.pytest_plugin", "-o", "enable_assertion_pass_hook=true"]
    assert '--bud-test-run-id=5' in seen['args']
    assert '--bud-suite-name=Bench' in seen['args']
    assert "--bud-no-upload" in seen["args"]
    assert seen["args"][-3:] == ["tests/", "-k", "smoke"]
    assert seen["prefix"] == str(tmp_path / ".bud" / "pycache")
    assert sys.pycache_prefix == before


def test_run_pytest_replays_the_spool_first_and_needs_a_backend(monkeypatch):
    flushed = []
    monkeypatch.setattr(pytest, "main", lambda args: 0)
    monkeypatch.setattr(cli, "AuthManager", lambda backend_url=None: SimpleNamespace(backend_url=backend_url))
    monkeypatch.setattr(cli, "BudAPIClient", lambda a: "client")
    monkeypatch.setattr(cli, "_flush_spooled_results", lambda *a: flushed.append(a[0]))
    result = CliRunner().invoke(cli.app, ["run-pytest", "--backend-url", "https://bud.example", "tests/"])
    assert result.exit_code == 0
    assert flushed == ['client']
    monkeypatch.setattr(cli, "AuthManager", lambda backend_url=None: SimpleNamespace(backend_url=None))
    result = CliRunner().invoke(cli.app, ["run-pytest", "tests/"])
    assert result.exit_code == 2
