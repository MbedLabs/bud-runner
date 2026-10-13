"""Cucumber JSON import: a Cucumber run, from any Cucumber runner, becomes a Bud run.

Run ``bud-runner import-cucumber --report report.json``. The report is the standard
Cucumber JSON that cucumber-js (``--format json:report.json``), Cucumber-JVM
(``--plugin json:report.json``) and Cucumber-Ruby (``--format json``) write. Each
feature becomes one Bud test case (its name as the test class) and each scenario, every
Scenario Outline row included, one result of it (its name as the method; ``(line N)`` is
added when two scenarios of a feature share a name). Background steps count as the
scenario's own. Each step becomes one entry named after its text, with its .feature file,
line and the step as written: a Then step is a check and a Given or When step an
information entry; And, But and ``*`` take the type of the step before. A step that fails,
is ambiguous, undefined or pending is failed with the runner's message and stack trace,
which the scenario's result carries too; a failed hook is a failed ``HookError`` entry. A
scenario's status is its worst step's, as Cucumber computes it: a scenario with a skipped
step, or with no steps, is a skipped result. A ``@bloom:PRJ-001`` tag on the scenario or
its feature becomes the Bloom test case ``PRJ-TC-001``. Keywords are recognised in
English; steps with keywords of other Gherkin languages take the type of the step before.
"""

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from bud_runner.reporting import bloom_tc_id
from bud_runner.robot_listener import BLOOM_TAG, _entry, _relative, info_entry, skip_assertion

STEP_TYPES = {"given": "given", "when": "when", "then": "then"}
FAILED = ("failed", "ambiguous", "undefined", "pending")
LIST_KEYS = ("steps", "before", "after", "tags")
STACK_FRAME = re.compile(r"^\s+at \S|^\./\S+:\d+:in |^/\S+:\d+:in ")
NANOSECONDS = 1_000_000_000


class CucumberReportError(Exception):
    """A file that is not a Cucumber JSON report."""


def read_report(path: Path) -> List[Dict[str, Any]]:
    """The features of a Cucumber JSON report, or ``CucumberReportError`` naming the problem."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise CucumberReportError(f"cannot read the file ({exc.strerror or exc})") from exc
    except UnicodeDecodeError as exc:
        raise CucumberReportError(f"not UTF-8 text ({exc.reason} at byte {exc.start})") from exc
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise CucumberReportError(f"not valid JSON ({exc})") from exc
    if not isinstance(data, list):
        raise CucumberReportError("a Cucumber JSON report is a list of features")
    for index, feature in enumerate(data, start=1):
        if not isinstance(feature, dict) or not isinstance(feature.get("elements"), list):
            raise CucumberReportError(f"feature {index} has no list of elements")
        if not isinstance(feature.get("tags", []), list):
            raise CucumberReportError(f"feature {index} has tags that are not a list")
        for element in feature["elements"]:
            _check_element(element, index)
    return data


def _check_element(element: Any, feature: int) -> None:
    """Raise CucumberReportError for an element whose steps, hooks, tags or results differ
    from the report's shape."""
    if not isinstance(element, dict):
        raise CucumberReportError(f"feature {feature} has an element that is not an object")
    for key in LIST_KEYS:
        items = element.get(key, [])
        if not isinstance(items, list):
            raise CucumberReportError(f"feature {feature} has an element whose {key} are not a list")
        for item in items:
            if not isinstance(item, dict):
                raise CucumberReportError(f"feature {feature} has {key} that are not objects")
            if key != "tags" and not isinstance(item.get("result", {}), dict):
                raise CucumberReportError(f"feature {feature} has a {key} entry whose result is not an object")


def feature_path(uri: Any) -> Optional[str]:
    """A feature's ``uri`` as a path relative to the working directory, without a ``file:``
    or ``classpath:`` scheme."""
    if not uri:
        return None
    text = str(uri)
    for scheme in ("file://", "file:", "classpath:"):
        if text.startswith(scheme):
            text = text[len(scheme) :]
            break
    return _relative(text)


def error_text(message: str) -> str:
    """The error of a runner's message without its stack trace: the lines before the first
    stack frame (cucumber-js ``    at ...``, Cucumber-JVM ``\\tat ...``, Cucumber-Ruby
    ``./path:N:in ...``)."""
    kept: List[str] = []
    for line in message.splitlines():
        if STACK_FRAME.match(line):
            break
        kept.append(line.rstrip())
    return "\n".join(kept).strip() or message.strip()


def _status(item: Dict[str, Any]) -> str:
    return str((item.get("result") or {}).get("status") or "unknown").lower()


def _duration(item: Dict[str, Any]) -> float:
    value = (item.get("result") or {}).get("duration") or 0
    try:
        return float(value) / NANOSECONDS
    except (TypeError, ValueError):
        return 0.0


def _tag_names(item: Dict[str, Any]) -> List[str]:
    return [str(t.get("name", "")).lstrip("@") for t in item.get("tags") or [] if isinstance(t, dict)]


class CucumberReport:
    """The Bud results of a Cucumber JSON report."""

    def __init__(
        self,
        features: List[Dict[str, Any]],
        report_path: Optional[Path] = None,
        test_run_id: Optional[int] = None,
        product_id: Optional[int] = None,
        suite_name: Optional[str] = None,
        ref_sw_under_test: Optional[str] = None,
    ) -> None:
        self.report_path = Path(report_path) if report_path is not None else None
        self.test_run_id = test_run_id
        self.product_id = product_id
        self.suite_name = suite_name
        self.ref_sw_under_test = ref_sw_under_test
        self.feature_names: List[str] = []
        self.feature_paths: List[str] = []
        self.results: List[Dict[str, Any]] = []
        for feature in features:
            self._feature(feature)

    def counts(self) -> Dict[str, int]:
        """Features, and scenarios passed, failed and skipped."""
        skipped = sum(1 for r in self.results if r["metadata"].get("skipped"))
        passed = sum(1 for r in self.results if r["passed"]) - skipped
        return {
            "features": len(self.feature_names),
            "scenarios": len(self.results),
            "passed": passed,
            "failed": len(self.results) - passed - skipped,
            "skipped": skipped,
        }

    def _feature(self, feature: Dict[str, Any]) -> None:
        name = str(feature.get("name") or feature.get("id") or "Feature")
        path = feature_path(feature.get("uri"))
        self.feature_names.append(name)
        if path:
            self.feature_paths.append(path)
        feature_tags = _tag_names(feature)
        scenarios: List[Tuple[Dict[str, Any], List[Dict[str, Any]]]] = []
        background: List[Dict[str, Any]] = []
        for element in feature.get("elements") or []:
            if str(element.get("type") or "scenario").lower() == "background":
                background.append(element)
                continue
            scenarios.append((element, background))
            background = []
        names = [str(e.get("name") or "").strip() or "Scenario" for e, _ in scenarios]
        for element, backgrounds in scenarios:
            self._scenario(name, path, feature_tags, element, backgrounds, names)

    def _scenario(
        self,
        feature_name: str,
        path: Optional[str],
        feature_tags: List[str],
        element: Dict[str, Any],
        backgrounds: List[Dict[str, Any]],
        names: List[str],
    ) -> None:
        """Turn one scenario element, with the background elements before it, into its result."""
        name = str(element.get("name") or "").strip() or "Scenario"
        line = element.get("line")
        if names.count(name) > 1 and line is not None:
            name = f"{name} (line {line})"
        own = [t for t in _tag_names(element) if t not in feature_tags]
        tags = own + [t for t in feature_tags if t not in own]
        parts = backgrounds + [element]
        steps = [s for part in parts for s in part.get("steps") or []]
        entries: List[Dict[str, Any]] = []
        statuses: List[str] = []
        failures: List[Tuple[str, str]] = []
        duration = 0.0
        step_type = "given"
        for hook in [h for part in parts for h in part.get("before") or []]:
            duration += _duration(hook)
            self._hook(hook, "Before", path, name, entries, statuses, failures)
        for step in steps:
            duration += _duration(step)
            if step.get("hidden") or not step.get("name"):
                self._hook(step, str(step.get("keyword") or "Hook").strip(), path, name, entries, statuses, failures)
                continue
            keyword = str(step.get("keyword") or "").strip()
            step_type = STEP_TYPES.get(keyword.lower(), step_type)
            status = _status(step)
            statuses.append(status)
            if status in ("skipped", "unknown"):
                continue
            text = str(step.get("name"))
            where: Dict[str, Any] = {
                "source_file": path,
                "source_line": step.get("line"),
                "source_function": name,
                "code_context": f"{keyword} {text}",
            }
            if status == "passed":
                entries.append(_entry(text, True, "", where) if step_type == "then" else info_entry(text, "", where))
                continue
            message, trace = self._failure_text(step, status, keyword, text)
            where["traceback"] = trace
            entry = _entry(text, False, message, where)
            if step_type != "then":
                entry["info"] = True
            entries.append(entry)
            failures.append((message, trace))
        for hook in [h for part in parts for h in part.get("after") or []]:
            duration += _duration(hook)
            self._hook(hook, "After", path, name, entries, statuses, failures)
        failed = [s for s in FAILED if s in statuses]
        real_steps = [s for s in steps if not s.get("hidden") and s.get("name")]
        if failed:
            status = failed[0]
        elif "skipped" in statuses or not real_steps:
            status = "skipped"
        else:
            status = "passed"
        metadata: Dict[str, Any] = {
            "cucumber_status": status,
            "cucumber_tags": tags,
            "location": f"{path}:{line}" if path else str(line),
        }
        tc_ids = [t[len(BLOOM_TAG) :].strip() for t in tags if t.lower().startswith(BLOOM_TAG)]
        if tc_ids and tc_ids[0]:
            metadata["tc_id"] = bloom_tc_id(tc_ids[0])
        error: Optional[str] = None
        if failures:
            error = failures[0][0]
        elif status == "skipped":
            metadata["skipped"] = True
            error = "Scenario has no steps" if not real_steps else "Skipped by the runner"
            where = {"source_file": path, "source_line": line, "source_function": name, "code_context": f"Scenario: {name}"}
            entries.append(skip_assertion(error, where))
        passed = not failures
        self.results.append(
            {
                "test_class": feature_name,
                "test_method": name,
                "passed": passed,
                "duration_seconds": round(duration, 3),
                "error_message": error,
                "traceback": None if passed else failures[0][1],
                "assertions": entries or None,
                "metadata": metadata,
            }
        )

    @staticmethod
    def _failure_text(step: Dict[str, Any], status: str, keyword: str, text: str) -> Tuple[str, str]:
        """Message and traceback of a step that did not pass."""
        raw = str((step.get("result") or {}).get("error_message") or "")
        if raw.strip():
            return error_text(raw), raw.strip()
        label = {"undefined": "Undefined step", "ambiguous": "Ambiguous step", "pending": "Pending step"}.get(
            status, "Failed step"
        )
        message = f"{label}: {keyword} {text}"
        return message, message

    @staticmethod
    def _hook(
        hook: Dict[str, Any],
        kind: str,
        path: Optional[str],
        scenario: str,
        entries: List[Dict[str, Any]],
        statuses: List[str],
        failures: List[Tuple[str, str]],
    ) -> None:
        """Record a hook that did not pass as a failed ``HookError`` entry."""
        status = _status(hook)
        if status in ("passed", "skipped", "unknown"):
            return
        statuses.append("failed")
        raw = str((hook.get("result") or {}).get("error_message") or "").strip()
        message = error_text(raw) if raw else f"{kind} hook {status}"
        where = {
            "source_file": path,
            "source_line": None,
            "source_function": scenario,
            "code_context": f"{kind} hook",
            "traceback": raw or message,
        }
        entries.append(_entry("HookError", False, message, where))
        failures.append((message, raw or message))

    def _default_suite(self) -> Optional[str]:
        """The feature's name when the report has one feature, else the first feature's
        directory, else the report file's name without extension."""
        if len(self.feature_names) == 1:
            return self.feature_names[0]
        if self.feature_paths:
            folder = os.path.basename(os.path.dirname(os.path.abspath(self.feature_paths[0])))
            if folder:
                return folder
        return self.report_path.stem if self.report_path is not None else None

    def payload(
        self, runner_account: Optional[str] = None, default_product_id: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """The ResultsUpload body of the report, or None when it has no scenario.

        The suite is ``suite_name``, else the feature's name when the report has one
        feature, else the first feature's directory, else the report file's name; the
        product is ``product_id``, else the one bud-runner reads from app.properties.
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
