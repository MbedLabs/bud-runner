"""
Unit tests for ``bud_runner.api_client._flatten_results``.

The helper is the contract between budtestlibrary's nested result objects
and the backend's flat ``TestResultCreate`` schema. A regression here
silently corrupts every uploaded test run, so keep it well-tested.
"""

from __future__ import annotations

from bud_runner.api_client import _flatten_results


class _FakeAssertion:
    def __init__(self, passed: bool, message: str):
        self.passed = passed
        self.message = message

    def to_dict(self):
        return {"passed": self.passed, "message": self.message}


class _FakeMethodResult:
    def __init__(self, method_name, passed, assertions, duration=0.5, err=None, tb=None, summary_message=None):
        self.method_name = method_name
        self.passed = passed
        self.assertions = assertions
        self.duration_seconds = duration
        self.error_message = err
        self.traceback = tb
        self.summary_message = summary_message

    def to_dict(self):
        return {
            "method_name": self.method_name,
            "passed": self.passed,
            "assertions": [a.to_dict() for a in self.assertions],
            "duration_seconds": self.duration_seconds,
            "error_message": self.error_message,
            "traceback": self.traceback,
            "summary_message": self.summary_message,
        }


class _FakeRunResult:
    def __init__(self, test_class, method_results, passed=None, err=None):
        self.test_class = test_class
        self.method_results = method_results
        self.passed = passed if passed is not None else all(m.passed for m in method_results)
        self.duration_seconds = sum(m.duration_seconds for m in method_results)
        self.error_message = err


def test_flattens_nested_run_result_into_per_method_rows():
    run = _FakeRunResult(
        test_class="VoltageTest",
        method_results=[
            _FakeMethodResult(
                "bud_check_cells",
                False,
                [_FakeAssertion(True, "ok"), _FakeAssertion(False, "too low")],
                err="cell 3 out of range",
                tb="Traceback...",
                summary_message="Failed: cell 3 out of range",
            ),
            _FakeMethodResult("bud_check_pack", True, [_FakeAssertion(True, "ok")]),
        ],
    )

    rows = _flatten_results([run], test_run_id=42)

    assert len(rows) == 2
    assert {r["test_method"] for r in rows} == {"bud_check_cells", "bud_check_pack"}
    for r in rows:
        assert r["test_class"] == "VoltageTest"
        assert r["test_run_id"] == 42

    failing = next(r for r in rows if r["test_method"] == "bud_check_cells")
    assert failing["passed"] is False
    assert failing["traceback"] == "Traceback..."
    assert failing["assertions"] == [
        {"passed": True, "message": "ok"},
        {"passed": False, "message": "too low"},
    ]
    assert failing["metadata"]["summary_message"] == "Failed: cell 3 out of range"


def test_class_level_failure_with_no_methods_produces_placeholder_row():
    run = _FakeRunResult(
        test_class="BrokenSuite",
        method_results=[],
        passed=False,
        err="setUpClass raised",
    )

    rows = _flatten_results([run], test_run_id=7)

    assert len(rows) == 1
    assert rows[0]["test_class"] == "BrokenSuite"
    assert rows[0]["test_method"] == "__class__"
    assert rows[0]["passed"] is False
    assert rows[0]["error_message"] == "setUpClass raised"


def test_plain_method_result_is_accepted():
    rows = _flatten_results(
        [_FakeMethodResult("bud_solo", True, [_FakeAssertion(True, "ok")])],
        test_run_id=None,
    )
    assert len(rows) == 1
    assert rows[0]["test_method"] == "bud_solo"
    assert rows[0]["test_class"] == "UnknownTestClass"
    assert "test_run_id" not in rows[0]


def test_already_flat_dict_is_passed_through():
    rows = _flatten_results(
        [
            {
                "test_class": "SmokeTest",
                "test_method": "bud_hello",
                "passed": True,
                "duration_seconds": 0.1,
                "assertions": [{"passed": True, "message": "ok"}],
            }
        ],
        test_run_id=9,
    )
    assert rows[0]["test_method"] == "bud_hello"
    assert rows[0]["test_run_id"] == 9
