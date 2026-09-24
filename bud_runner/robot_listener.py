"""Robot Framework listener: a Robot run becomes a Bud run.

Attach it with ``robot --listener "bud_runner.robot_listener.BudListener;backend=https://bud"``
(the semicolon separator keeps the colons of a URL intact) or run
``bud-runner run-robot``. Each Robot test becomes one Bud result (the suite's full
name as the test class, the test name as the method), each library keyword call
inside a test becomes one assertion, a ``bloom:<TC id>`` tag becomes the Bloom
identity, and output.xml, log.html and report.html are uploaded as run artifacts.
Nothing here changes Robot's exit code: an upload failure spools the payload for the
next bud-runner invocation and prints a warning.
"""

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

BLOOM_TAG = "bloom:"
MAX_KEYWORD_DEPTH = 10
MAX_ASSERTIONS_PER_TEST = 500
ARG_LIMIT = 500
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


def assertion_for(name: str, owner: Optional[str], args: List[str], passed: bool, message: str) -> Dict[str, Any]:
    """One Bud assertion for a library keyword call.

    For BuiltIn's Should family the argument order is known, so the expected and
    actual values are filled in; any other keyword keeps its arguments and outcome
    without guessing which argument is which.
    """
    assertion: Dict[str, Any] = {
        "name": name,
        "assertion_type": name,
        "args": args,
        "passed": passed,
        "message": message or None,
        "metadata": {"library": owner} if owner else None,
    }
    if owner == "BuiltIn":
        if name in EXPECTED_SECOND and len(args) >= 2:
            assertion["actual"] = args[0]
            assertion["expected"] = args[1]
        elif name in TRUTH_KEYWORDS and args:
            assertion["actual"] = args[0]
            assertion["expected"] = TRUTH_KEYWORDS[name]
    return assertion


def _elapsed(item: Any) -> float:
    elapsed = getattr(item, "elapsed_time", None)
    if elapsed is not None:
        return round(elapsed.total_seconds(), 3)
    return round((getattr(item, "elapsedtime", 0) or 0) / 1000.0, 3)


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

    def start_suite(self, data, result) -> None:
        if self.root_suite is None:
            self.root_suite = result.name
            self.metadata = {str(k): str(v) for k, v in (result.metadata or {}).items()}

    def start_test(self, data, result) -> None:
        self._assertions = []
        self._depth = 0

    def start_user_keyword(self, data, implementation, result) -> None:
        self._depth += 1

    def end_user_keyword(self, data, implementation, result) -> None:
        self._depth -= 1

    def start_library_keyword(self, data, implementation, result) -> None:
        self._depth += 1

    def end_library_keyword(self, data, implementation, result) -> None:
        self._depth -= 1
        if self._assertions is None or self._depth >= MAX_KEYWORD_DEPTH:
            return
        if len(self._assertions) >= MAX_ASSERTIONS_PER_TEST:
            return
        if result.status == "NOT RUN":
            return
        self._assertions.append(
            assertion_for(
                result.name,
                getattr(result, "owner", None),
                _resolve(list(result.args)),
                result.status == "PASS",
                result.message,
            )
        )

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
        self.results.append(
            {
                "test_class": result.parent.full_name if result.parent else (self.root_suite or "Robot"),
                "test_method": result.name,
                "passed": result.status in ("PASS", "SKIP"),
                "duration_seconds": _elapsed(result),
                "error_message": (result.message or None) if result.status != "PASS" else None,
                "assertions": self._assertions or None,
                "metadata": metadata,
            }
        )
        self._assertions = None

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
        from bud_runner.api_client import BudAPIClient
        from bud_runner.auth import AuthManager
        from bud_runner.cli import _spool_results_payload

        auth = AuthManager(backend_url=self.backend)
        client = BudAPIClient(auth)
        body = self.payload(auth.runner_account, auth.product_id)
        if body is None:
            print("[bud] The Robot run produced no test results; nothing uploaded.", file=sys.stderr)
            return
        try:
            response = client.upload_results_payload(body)
        except Exception as exc:
            spool = _spool_results_payload(body)
            print(f"[bud] Upload failed ({exc}); results spooled to {spool}", file=sys.stderr)
            return
        run_id = self.test_run_id
        if isinstance(response, dict) and response.get("test_run_id"):
            run_id = response["test_run_id"]
        print(f"[bud] Robot results uploaded to Bud run {run_id}", file=sys.stderr)
        if run_id and self.skipped:
            try:
                client.update_test_run(run_id=run_id, skipped_tests=self.skipped)
            except Exception as exc:
                print(f"[bud] Could not record skipped tests: {exc}", file=sys.stderr)
        if run_id and self.upload_artifacts:
            for path in self.files:
                if not path.is_file():
                    continue
                try:
                    client.upload_artifact(str(path), run_id=run_id)
                except Exception as exc:
                    print(f"[bud] Could not upload {path.name}: {exc}", file=sys.stderr)
