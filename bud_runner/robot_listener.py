"""Robot Framework listener: a Robot run becomes a Bud run.

Attach it with ``robot --listener "bud_runner.robot_listener.BudListener;backend=https://bud"``
(the semicolon separator keeps the colons of a URL intact) or run
``bud-runner run-robot``. Each Robot test becomes one Bud test case and result (its
full name as the test class, its name as the method). Inside a test, each library
keyword call becomes one entry: a check (a library keyword whose name contains the
word "Should") is an assertion named ``Assert`` plus what it checks (AssertEqual,
AssertIn, AssertTrue, AssertEmpty, ...), never "Should"; a keyword that checks
nothing, or a failure that a TRY or a keyword such as Run Keyword And Ignore Error
handled, is an information entry; a keyword that fails is a failed entry; ``Skip``
is a skipped entry. Each entry carries its .robot
file, line and call, and a failure the Robot call chain as its traceback, which the
failed result carries too. A ``bloom:<TC id>`` tag becomes the Bloom identity, and
output.xml, log.html and report.html are uploaded as run artifacts. Nothing here
changes Robot's exit code: an upload failure spools the payload for the next
bud-runner invocation and prints a warning.
"""

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

BLOOM_TAG = "bloom:"
MAX_KEYWORD_DEPTH = 10
MAX_ASSERTIONS_PER_TEST = 500
ARG_LIMIT = 500
CHECK_WORD = "should"
SKIP_KEYWORDS = {"Skip", "Skip If"}
ASSERT_NAMES = {
    "Should Be Equal": "AssertEqual",
    "Should Be Equal As Integers": "AssertEqual",
    "Should Be Equal As Numbers": "AssertEqual",
    "Should Be Equal As Strings": "AssertEqual",
    "Should Not Be Equal": "AssertNotEqual",
    "Should Not Be Equal As Integers": "AssertNotEqual",
    "Should Not Be Equal As Numbers": "AssertNotEqual",
    "Should Not Be Equal As Strings": "AssertNotEqual",
    "Should Contain": "AssertIn",
    "Should Not Contain": "AssertNotIn",
    "Should Contain Any": "AssertInAny",
    "Should Not Contain Any": "AssertNotInAny",
    "Should Contain X Times": "AssertCount",
    "Should Match Regexp": "AssertRegex",
    "Should Not Match Regexp": "AssertNotRegex",
    "Should Match": "AssertMatch",
    "Should Not Match": "AssertNotMatch",
    "Should Start With": "AssertStartsWith",
    "Should Not Start With": "AssertNotStartsWith",
    "Should End With": "AssertEndsWith",
    "Should Not End With": "AssertNotEndsWith",
    "Should Be Empty": "AssertEmpty",
    "Should Not Be Empty": "AssertNotEmpty",
    "Should Be True": "AssertTrue",
    "Should Not Be True": "AssertFalse",
    "Length Should Be": "AssertLength",
}
TOLERANT_KEYWORDS = {
    "Run Keyword And Expect Error",
    "Run Keyword And Ignore Error",
    "Run Keyword And Return Status",
    "Run Keyword And Warn On Failure",
    "Wait Until Keyword Succeeds",
}
EXPECTED_SECOND = {
    "Should Be Equal",
    "Should Be Equal As Integers",
    "Should Be Equal As Numbers",
    "Should Be Equal As Strings",
    "Should Not Be Equal",
    "Should Not Be Equal As Integers",
    "Should Not Be Equal As Numbers",
    "Should Not Be Equal As Strings",
    "Should Contain",
    "Should Not Contain",
    "Should Start With",
    "Should Not Start With",
    "Should End With",
    "Should Not End With",
    "Should Match",
    "Should Not Match",
    "Should Match Regexp",
    "Should Not Match Regexp",
    "Length Should Be",
}
TRUTH_KEYWORDS = {"Should Be True": True, "Should Not Be True": False}


def _flag(value: Any) -> bool:
    return str(value).strip().lower() not in ("false", "0", "no", "off", "")


def _short(value: Any) -> str:
    text = str(value)
    return text if len(text) <= ARG_LIMIT else text[: ARG_LIMIT - 3] + "..."


def _resolve(args: List[str]) -> List[str]:
    """The keyword's arguments with variables replaced, where Robot can still do it."""
    try:
        from robot.libraries.BuiltIn import BuiltIn

        builtin = BuiltIn()
    except Exception:
        return [_short(a) for a in args]
    resolved = []
    for arg in args:
        try:
            resolved.append(_short(builtin.replace_variables(arg)))
        except Exception:
            resolved.append(_short(arg))
    return resolved


def is_check(name: str) -> bool:
    """A check keyword: its name contains the word "Should", as Robot's checks are named."""
    return CHECK_WORD in (name or "").lower().split()


def assert_name(name: str) -> str:
    """The Bud assertion name of a check keyword: ``Assert`` plus what it checks, never "Should".

    Robot's own checks have fixed names (AssertEqual, AssertIn, AssertTrue, ...); any
    other check is named from its words, e.g. "Element Should Be Visible" becomes
    ``AssertElementVisible``.
    """
    if name in ASSERT_NAMES:
        return ASSERT_NAMES[name]
    words = [w for w in (name or "").replace("_", " ").split() if w]
    lowered = [w.lower() for w in words]
    at = lowered.index(CHECK_WORD) if CHECK_WORD in lowered else len(words)
    subject, rest = words[:at], words[at + 1 :]
    negated = bool(rest) and rest[0].lower() == "not"
    if negated:
        rest = rest[1:]
    if rest and rest[0].lower() == "be":
        rest = rest[1:]
    parts = ["".join(ch for ch in w if ch.isalnum()) for w in subject + rest]
    return "Assert" + ("Not" if negated else "") + "".join(p[:1].upper() + p[1:] for p in parts if p)


def _relative(source: Any) -> Optional[str]:
    """A source file as a path relative to the working directory when it is below it."""
    if not source:
        return None
    path = str(source)
    try:
        relative = os.path.relpath(path)
    except ValueError:
        return path
    return path if relative.startswith("..") else relative


def _call_text(name: str, args: Any) -> str:
    """The keyword call as written in the .robot file."""
    return "    ".join([name, *[str(a) for a in (args or ())]])


def _entry(assertion_type: str, passed: bool, message: str, where: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    where = where or {}
    return {
        "passed": passed,
        "skipped": False,
        "message": message or None,
        "assertion_type": assertion_type,
        "source_file": where.get("source_file"),
        "source_line": where.get("source_line"),
        "source_function": where.get("source_function"),
        "code_context": where.get("code_context"),
        "traceback": None if passed else where.get("traceback"),
        "timestamp": where.get("timestamp"),
        "metadata": {},
    }


def assertion_for(
    name: str,
    owner: Optional[str],
    args: List[str],
    passed: bool,
    message: str,
    where: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """One Bud assertion for a check keyword, named by ``assert_name``.

    For BuiltIn's checks, where the argument order is known, the expected and actual
    values are filled in.
    """
    builtin = owner == "BuiltIn"
    assertion = _entry(assert_name(name), passed, message, where)
    if builtin:
        if name in EXPECTED_SECOND and len(args) >= 2:
            assertion["actual"] = args[0]
            assertion["expected"] = args[1]
        elif name in TRUTH_KEYWORDS and args:
            assertion["actual"] = args[0]
            assertion["expected"] = TRUTH_KEYWORDS[name]
    return assertion


def info_entry(name: str, message: str, where: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """An information entry for a keyword that checks nothing and passed."""
    entry = _entry(name, True, message, where)
    entry["info"] = True
    return entry


def skip_assertion(message: str, where: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """A skipped assertion, as budtestlibrary's ``skipAssert`` sends it."""
    entry = _entry("Skip", True, message, where)
    entry["skipped"] = True
    return entry


def _elapsed(item: Any) -> float:
    elapsed = getattr(item, "elapsed_time", None)
    if elapsed is not None:
        return round(elapsed.total_seconds(), 3)
    return round((getattr(item, "elapsedtime", 0) or 0) / 1000.0, 3)


def _timestamp(result: Any) -> Optional[str]:
    end = getattr(result, "end_time", None)
    return end.isoformat() if end is not None and hasattr(end, "isoformat") else None


class BudListener:
    """Collects a Robot run and uploads it to Bud when Robot closes."""

    ROBOT_LISTENER_API_VERSION = 3

    def __init__(
        self,
        backend: Optional[str] = None,
        test_run_id: Optional[str] = None,
        product_id: Optional[str] = None,
        suite_name: Optional[str] = None,
        ref_sw_under_test: Optional[str] = None,
        upload: str = "true",
        artifacts: str = "true",
    ):
        self.backend = backend
        self.test_run_id = int(test_run_id) if test_run_id else None
        self.product_id = int(product_id) if product_id else None
        self.suite_name = suite_name
        self.ref_sw_under_test = ref_sw_under_test
        self.upload = _flag(upload)
        self.upload_artifacts = _flag(artifacts)
        self.results: List[Dict[str, Any]] = []
        self.files: List[Path] = []
        self.root_suite: Optional[str] = None
        self.metadata: Dict[str, str] = {}
        self.skipped = 0
        self._assertions: Optional[List[Dict[str, Any]]] = None
        self._depth = 0
        self._frames: List[Dict[str, Any]] = []
        self._scopes: List[Dict[str, Any]] = []
        self._failure: Optional[str] = None
        self._failure_message: Optional[str] = None
        self._tolerant: List[Dict[str, Any]] = []
        self._starts: List[int] = []

    def start_suite(self, data, result) -> None:
        if self.root_suite is None:
            self.root_suite = result.name
            self.metadata = {str(k): str(v) for k, v in (result.metadata or {}).items()}

    def start_test(self, data, result) -> None:
        self._assertions = []
        self._depth = 0
        self._frames = []
        self._failure = None
        self._failure_message = None
        self._tolerant = []
        self._starts = []
        self._scopes = [
            {
                "source": _relative(getattr(data, "source", None)),
                "name": getattr(result, "name", None) or getattr(data, "name", None),
            }
        ]

    def _enter(self, data) -> None:
        scope = self._scopes[-1] if self._scopes else {"source": None, "name": None}
        self._frames.append(
            {
                "source_file": scope["source"],
                "source_line": getattr(data, "lineno", None),
                "source_function": scope["name"],
                "code_context": _call_text(getattr(data, "name", ""), getattr(data, "args", ())),
            }
        )

    def _leave(self) -> None:
        if self._frames:
            self._frames.pop()

    def start_user_keyword(self, data, implementation, result) -> None:
        self._depth += 1
        self._enter(data)
        outer = self._scopes[-1]["source"] if self._scopes else None
        self._scopes.append(
            {
                "source": _relative(getattr(implementation, "source", None)) or outer,
                "name": getattr(implementation, "name", None) or getattr(data, "name", None),
            }
        )

    def end_user_keyword(self, data, implementation, result) -> None:
        self._depth -= 1
        self._leave()
        if len(self._scopes) > 1:
            self._scopes.pop()

    def start_library_keyword(self, data, implementation, result) -> None:
        self._depth += 1
        self._enter(data)
        self._starts.append(len(self._assertions or []))
        if getattr(result, "name", None) in TOLERANT_KEYWORDS:
            self._open_tolerant()

    def start_invalid_keyword(self, data, implementation, result) -> None:
        self.start_library_keyword(data, implementation, result)

    def end_invalid_keyword(self, data, implementation, result) -> None:
        self.end_library_keyword(data, implementation, result)

    def start_try(self, data, result) -> None:
        self._open_tolerant()

    def end_try(self, data, result) -> None:
        self._close_tolerant(getattr(result, "status", None) == "PASS")

    def _open_tolerant(self) -> None:
        """Mark where a keyword or TRY that may handle a failure starts."""
        self._tolerant.append(
            {
                "index": len(self._assertions or []),
                "failure": self._failure,
                "failure_message": self._failure_message,
            }
        )

    def _close_tolerant(self, handled: bool, retries: bool = False) -> None:
        """A handled failure inside becomes information and is not the test's failure;
        of retried attempts that all failed, only the last stays a failure."""
        if not self._tolerant:
            return
        mark = self._tolerant.pop()
        if self._assertions is None:
            return
        failed = [e for e in self._assertions[mark["index"] :] if e.get("passed") is False]
        if not handled:
            failed = failed[:-1] if retries else []
        for entry in failed:
            entry["passed"] = True
            entry["info"] = True
            entry["traceback"] = None
        if handled:
            self._failure = mark["failure"]
            self._failure_message = mark["failure_message"]

    def _traceback(self, message: str) -> str:
        lines = ["Traceback (most recent call last):"]
        for frame in self._frames:
            lines.append(
                f'  File "{frame["source_file"]}", line {frame["source_line"]}, in {frame["source_function"]}'
            )
            lines.append(f"    {frame['code_context']}")
        lines.append(message or "failed")
        return "\n".join(lines)

    def _note_failure(self, message: str, traceback: str) -> None:
        """Keep the first failure no TRY or keyword handled, with its deepest call chain."""
        if self._failure is not None:
            if self._failure_message != message or self._failure.count("\n") >= traceback.count("\n"):
                return
        self._failure = traceback
        self._failure_message = message

    def end_library_keyword(self, data, implementation, result) -> None:
        self._depth -= 1
        where = dict(self._frames[-1]) if self._frames else {}
        where["timestamp"] = _timestamp(result)
        start = self._starts.pop() if self._starts else len(self._assertions or [])
        try:
            name = getattr(result, "name", None)
            if name in TOLERANT_KEYWORDS:
                self._close_tolerant(result.status == "PASS", retries=name == "Wait Until Keyword Succeeds")
            self._record(result, where, start)
        finally:
            self._leave()

    def _record(self, result, where: Dict[str, Any], start: int = 0) -> None:
        if self._assertions is None:
            return
        name, status = result.name, result.status
        if status == "NOT RUN":
            return
        capped = self._depth >= MAX_KEYWORD_DEPTH or len(self._assertions) >= MAX_ASSERTIONS_PER_TEST
        if capped and (status != "FAIL" or len(self._assertions) >= 2 * MAX_ASSERTIONS_PER_TEST):
            if status == "FAIL":
                self._note_failure(result.message, self._traceback(result.message))
            return
        if status == "SKIP":
            if name in SKIP_KEYWORDS or is_check(name):
                entry = skip_assertion(result.message, where)
                if name not in SKIP_KEYWORDS:
                    entry["assertion_type"] = assert_name(name)
                self._assertions.append(entry)
            return
        failed = status == "FAIL"
        inner_failure = any(e.get("passed") is False for e in self._assertions[start:])
        if failed and not is_check(name) and inner_failure:
            self._assertions.append(info_entry(name, result.message, where))
            return
        if failed:
            where["traceback"] = self._traceback(result.message)
            self._note_failure(result.message, where["traceback"])
        if is_check(name):
            entry = assertion_for(
                name, getattr(result, "owner", None), _resolve(list(result.args)), not failed, result.message, where
            )
        elif failed:
            entry = _entry(name, False, result.message, where)
        else:
            entry = info_entry(name, result.message, where)
        self._assertions.append(entry)

    def end_test(self, data, result) -> None:
        tags = [str(t) for t in result.tags]
        tc_ids = [t[len(BLOOM_TAG):].strip() for t in tags if t.lower().startswith(BLOOM_TAG)]
        skipped = result.status == "SKIP"
        if skipped:
            self.skipped += 1
        metadata: Dict[str, Any] = {"robot_status": result.status, "robot_tags": tags}
        if tc_ids and tc_ids[0]:
            metadata["tc_id"] = tc_ids[0]
        if skipped:
            metadata["skipped"] = True
        full_name = getattr(result, "full_name", None) or (
            f"{result.parent.full_name}.{result.name}" if result.parent else result.name
        )
        if result.status == "FAIL" and self._assertions is not None:
            if not any(e.get("passed") is False for e in self._assertions):
                fallback = _entry("Fail", False, result.message, None)
                fallback["traceback"] = self._failure or f"Traceback (most recent call last):\n{result.message}"
                self._failure = fallback["traceback"]
                self._assertions.append(fallback)
        self.results.append(
            {
                "test_class": full_name,
                "test_method": result.name,
                "passed": result.status in ("PASS", "SKIP"),
                "duration_seconds": _elapsed(result),
                "error_message": (result.message or None) if result.status != "PASS" else None,
                "traceback": self._failure if result.status == "FAIL" else None,
                "assertions": self._assertions or None,
                "metadata": metadata,
            }
        )
        self._assertions = None
        self._frames = []
        self._scopes = []
        self._failure = None
        self._failure_message = None

    def output_file(self, path) -> None:
        self.files.append(Path(path))

    def log_file(self, path) -> None:
        self.files.append(Path(path))

    def report_file(self, path) -> None:
        self.files.append(Path(path))

    def payload(
        self, runner_account: Optional[str] = None, default_product_id: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """The ResultsUpload body for the collected run, or None when nothing ran.

        The product is the listener's ``product_id`` option, else the one bud-runner
        reads from app.properties (``productId``), as ``run-tests`` does.
        """
        if not self.results:
            return None
        body: Dict[str, Any] = {
            "results": self.results,
            "test_run_id": self.test_run_id,
            "runner_account": runner_account,
            "test_suite_name": self.suite_name or self.root_suite,
            "ref_software_under_test": self.ref_sw_under_test
            or self.metadata.get("Software Under Test")
            or self.metadata.get("ref_sw_under_test"),
        }
        product_id = self.product_id if self.product_id is not None else default_product_id
        if product_id is not None:
            body["product_id"] = product_id
        return body

    def close(self) -> None:
        if not self.upload:
            return
        try:
            self._send()
        except Exception as exc:
            print(f"[bud] Could not report the Robot run to Bud: {exc}", file=sys.stderr)

    def _send(self) -> None:
        from bud_runner.reporting import send_run

        send_run(
            self.payload,
            framework="Robot",
            backend=self.backend,
            test_run_id=self.test_run_id,
            skipped=self.skipped,
            files=self.files if self.upload_artifacts else (),
        )
