"""Behave formatter: a Behave run becomes a Bud run.

Run ``bud-runner run-behave <behave arguments>``, or attach it yourself with
``behave -f bud_runner.behave_formatter:BudFormatter -o /dev/null -f pretty``. Each
feature becomes one Bud test case (its name as the test class) and each scenario one
result of it (its name as the method). Inside a scenario, each step becomes one entry
named after its text, with its .feature file, line and the step as written: a Then
step is a check and a Given or When step an information entry; a step that fails or
raises is failed with the error and its traceback, which the scenario's result carries
too, and a step without a step definition is failed with an "Undefined step" message. A hook error fails the scenario. A scenario skipped
with a reason becomes a skipped result; a scenario left out by tag selection is not
reported. A ``@bloom:PRJ-001`` tag becomes the Bloom test case ``PRJ-TC-001``. Options come from
Behave's userdata (``-D bud_backend_url=...``, ``bud_test_run_id``, ``bud_product_id``,
``bud_suite_name``, ``bud_ref_sw_under_test``, ``bud_upload``). When Behave closes the
formatter the run is uploaded; Behave's exit code is not changed, and an upload
failure spools the payload for the next bud-runner invocation and prints a warning.
"""

import os
import sys
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from behave.formatter.base import Formatter

from bud_runner.reporting import bloom_tc_id
from bud_runner.robot_listener import BLOOM_TAG, _entry, _flag, _relative, info_entry, skip_assertion

NOT_RECORDED = {"skipped", "untested", "executing"}


def _status(value: Any) -> str:
    """A Behave status as its name: passed, failed, error, undefined, skipped, ..."""
    return str(getattr(value, "name", value) or "untested")


def _number(value: Any) -> Optional[int]:
    return int(value) if value not in (None, "") else None


def _where(location: Any, function: Optional[str], code: Optional[str]) -> Dict[str, Any]:
    """File, line, scenario and step text of an entry."""
    return {
        "source_file": _relative(getattr(location, "filename", None)),
        "source_line": getattr(location, "line", None),
        "source_function": function,
        "code_context": code,
        "timestamp": datetime.now().isoformat(),
    }


def step_message(step: Any) -> str:
    """The error of a step that did not pass: its exception, else Behave's message."""
    if _status(step.status) == "undefined":
        return f"Undefined step: {step.keyword} {step.name}"
    exc = getattr(step, "exception", None)
    if exc is not None:
        text = str(exc)
        if isinstance(exc, AssertionError):
            return text or "AssertionError"
        return f"{type(exc).__name__}: {text}" if text else type(exc).__name__
    return (getattr(step, "error_message", None) or _status(step.status)).strip()


def step_traceback(step: Any) -> Optional[str]:
    """The Python traceback of a step that raised, else Behave's error message."""
    exc = getattr(step, "exception", None)
    tb = getattr(step, "exc_traceback", None)
    if exc is not None and tb is not None:
        return "".join(traceback.format_exception(type(exc), exc, tb)).strip()
    return getattr(step, "error_message", None) or None


class BudFormatter(Formatter):
    """Collects a Behave run and uploads it to Bud when Behave closes the formatter."""

    name = "bud"
    description = "Report the run to Bud (bud-runner)."

    def __init__(self, stream_opener: Any, config: Any) -> None:
        super().__init__(stream_opener, config)
        data = getattr(config, "userdata", None) or {}
        self.backend: Optional[str] = data.get("bud_backend_url") or None
        self.test_run_id = _number(data.get("bud_test_run_id"))
        self.product_id = _number(data.get("bud_product_id"))
        self.suite_name: Optional[str] = data.get("bud_suite_name") or None
        self.ref_sw_under_test: Optional[str] = data.get("bud_ref_sw_under_test") or None
        self.upload = _flag(data.get("bud_upload", "true"))
        self.results: List[Dict[str, Any]] = []
        self.skipped = 0
        self.feature_names: List[str] = []
        self._feature: Any = None
        self._scenario: Any = None
        self._entries: List[Dict[str, Any]] = []
        self._failure: Optional[Tuple[str, Optional[str]]] = None
        self._closed = False

    def feature(self, feature: Any) -> None:
        self._finish()
        self._feature = feature
        if feature.name not in self.feature_names:
            self.feature_names.append(feature.name)

    def scenario(self, scenario: Any) -> None:
        self._finish()
        self._scenario = scenario
        self._entries = []
        self._failure = None

    def result(self, step: Any) -> None:
        if self._scenario is None:
            return
        status = _status(step.status)
        if status in NOT_RECORDED:
            return
        where = _where(step.location, self._scenario.name.strip(), f"{step.keyword} {step.name}")
        if status == "passed":
            if step.step_type == "then":
                entry = _entry(step.name, True, "", where)
            else:
                entry = info_entry(step.name, "", where)
        else:
            message = step_message(step)
            where["traceback"] = step_traceback(step)
            entry = _entry(step.name, False, message, where)
            if step.step_type != "then":
                entry["info"] = True
            if self._failure is None:
                self._failure = (message, where["traceback"])
        self._entries.append(entry)

    def eof(self) -> None:
        self._finish()

    def _tags(self, scenario: Any) -> List[str]:
        """The scenario's tags, then the feature's, then any other inherited tag (a Rule's)."""
        tags = [str(t) for t in getattr(scenario, "tags", [])]
        feature_tags = getattr(self._feature, "tags", []) if self._feature is not None else []
        tags += [str(t) for t in feature_tags if str(t) not in tags]
        inherited = sorted(str(t) for t in (getattr(scenario, "effective_tags", None) or []))
        return tags + [t for t in inherited if t not in tags]

    def _finish(self) -> None:
        """Turn the scenario that ended into its Bud result."""
        scenario, self._scenario = self._scenario, None
        if scenario is None:
            return
        status = _status(scenario.status)
        skip_reason = getattr(scenario, "skip_reason", None)
        if status == "skipped" and not skip_reason:
            return
        tags = self._tags(scenario)
        location = getattr(scenario, "location", None)
        metadata: Dict[str, Any] = {
            "behave_status": status,
            "behave_tags": tags,
            "location": f"{_relative(getattr(location, 'filename', None))}:{getattr(location, 'line', '')}",
        }
        tc_ids = [t[len(BLOOM_TAG) :].strip() for t in tags if t.lower().startswith(BLOOM_TAG)]
        if tc_ids and tc_ids[0]:
            metadata["tc_id"] = bloom_tc_id(tc_ids[0])
        name = scenario.name.strip()
        entries = self._entries
        where = _where(location, name, f"{getattr(scenario, 'keyword', 'Scenario')}: {name}")
        error: Optional[str] = None
        trace: Optional[str] = None
        skipped = status == "skipped"
        if getattr(scenario, "hook_failed", False) or status == "hook_error":
            error = (getattr(scenario, "error_message", None) or "hook error").strip()
            trace = step_traceback(scenario) or error
            where["traceback"] = trace
            entries.append(_entry("HookError", False, error, where))
        elif self._failure is not None:
            error, trace = self._failure
        elif skipped:
            self.skipped += 1
            metadata["skipped"] = True
            error = str(skip_reason)
            entries.append(skip_assertion(error, where))
        elif status != "passed":
            error = (getattr(scenario, "error_message", None) or status).strip()
            trace = step_traceback(scenario) or error
            where["traceback"] = trace
            entries.append(_entry("Fail", False, error, where))
        passed = status == "passed" or skipped
        self.results.append(
            {
                "test_class": self._feature.name if self._feature is not None else name,
                "test_method": name,
                "passed": passed,
                "duration_seconds": round(float(getattr(scenario, "duration", 0.0) or 0.0), 3),
                "error_message": error,
                "traceback": None if passed else trace,
                "assertions": entries or None,
                "metadata": metadata,
            }
        )
        self._entries = []
        self._failure = None

    def _default_suite(self) -> Optional[str]:
        """The feature's name when the run has one feature, else the directory of the first
        path given to Behave, else ``features``, Behave's default directory."""
        if len(self.feature_names) == 1:
            return self.feature_names[0]
        paths = list(getattr(self.config, "paths", None) or [])
        if not paths:
            return "features"
        first = os.path.abspath(str(paths[0]).split(":")[0])
        folder = first if os.path.isdir(first) else os.path.dirname(first)
        return os.path.basename(folder) or None

    def payload(
        self, runner_account: Optional[str] = None, default_product_id: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """The ResultsUpload body for the collected run, or None when no scenario ran.

        The suite is ``bud_suite_name``, else the feature's name when one feature ran,
        else the name of the features directory; the product is ``bud_product_id``, else
        the one bud-runner reads from app.properties.
        """
        if not self.results:
            return None
        body: Dict[str, Any] = {
            "results": self.results,
            "test_run_id": self.test_run_id,
            "runner_account": runner_account,
            "test_suite_name": self.suite_name or self._default_suite(),
            "ref_software_under_test": self.ref_sw_under_test,
        }
        product_id = self.product_id if self.product_id is not None else default_product_id
        if product_id is not None:
            body["product_id"] = product_id
        return body

    def close(self) -> None:
        self._finish()
        if self.upload and not self._closed:
            self._closed = True
            try:
                from bud_runner.reporting import send_run

                send_run(
                    self.payload,
                    framework="Behave",
                    backend=self.backend,
                    test_run_id=self.test_run_id,
                )
            except Exception as exc:
                print(f"[bud] Could not report the Behave run to Bud: {exc}", file=sys.stderr)
        self.close_stream()
