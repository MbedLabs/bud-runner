"""
CLI entry point for bud_runner.

Provides commands for test execution, runner registration, and test case synchronization.
"""

import json
import logging
import os
import secrets
import subprocess
import sys
import tempfile
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, List, Optional, Tuple

import requests
import typer

from bud_runner.api_client import BudAPIClient, _flatten_results
from bud_runner.auth import AuthManager
from bud_runner.junit_reporter import JUnitReporter
from bud_runner.runner_manager import RunnerManager
from bud_runner.test_executor import TestExecutor
from bud_runner.versioning import read_package_version


UPLOAD_NO_UPLOAD = '--upload/--no-upload'
BACKEND_URL_FOR_RESULT_UPLOAD = 'Backend URL for result upload'
EXISTING_TESTRUN_ID_TO_ATTACH_THE_RESULTS_TO = 'Existing TestRun id to attach the results to.'
GIT_REF_OF_THE_SOFTWARE_UNDER_TEST = 'Git ref of the software under test.'
PRODUCT_ID_FOR_A_RUN_BUD_CREATES_FROM_THE_UPLOAD = 'Product id for a run Bud creates from the upload.'
UPLOAD_RESULTS_TO_BUD = 'Upload results to Bud'

app = typer.Typer(
    name="bud_runner",
    help="CLI tool for test execution and CI/CD integration with the Bud backend",
    add_completion=True,
)


class OutputFormat(str, Enum):
    """Output format options."""

    json = "json"
    text = "text"
    junit = "junit"


class StatusOutputFormat(str, Enum):
    """Output format options for status-style commands."""

    json = "json"
    text = "text"


class DaemonLogFormatter(logging.Formatter):
    """Structured formatter for daemon log files."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        return json.dumps(payload, ensure_ascii=True)


def _configure_daemon_logging() -> None:
    """Route daemon logs through a structured stdout handler."""
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(DaemonLogFormatter())
    root_logger.addHandler(handler)


def _spool_dir() -> Path:
    """Directory for persisted result-upload payloads."""
    candidates = [
        Path.home() / ".bud" / "spool" / "results",
        Path(tempfile.gettempdir()) / "bud" / "spool" / "results",
    ]
    for spool_dir in candidates:
        try:
            spool_dir.mkdir(parents=True, exist_ok=True)
            return spool_dir
        except OSError:
            continue
    raise RuntimeError("Could not create a writable result spool directory")


def _spool_results_payload(payload: dict) -> Path:
    """Persist a failed upload payload for later replay."""
    spool_file = _spool_dir() / f"{int(time.time())}-{uuid.uuid4().hex}.json"
    spool_file.write_text(json.dumps(payload), encoding="utf-8")
    return spool_file


def _upload_payload_with_retry(
    client: BudAPIClient,
    auth: AuthManager,
    payload: dict,
    username: Optional[str],
    password: Optional[str],
) -> Any:
    """Upload a result payload with the same 401 refresh flow as live uploads; the server's answer."""
    try:
        return client.upload_results_payload(payload)
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        if status_code == 401 and username and password:
            typer.echo("401 during upload, refreshing token with provided credentials...")
            fresh_token = client.login_user(username, password)
            auth.save_user_token(username, fresh_token)
            return client.upload_results_payload(payload)
        raise


def _upload_artifacts(
    client: BudAPIClient, patterns: List[str], test_run_id: int, exclude: Iterable[Path] = ()
) -> None:
    """Upload files matching the given paths or globs against a test run, except ``exclude``."""
    files: List[Path] = []
    for pattern in patterns:
        literal = Path(pattern)
        if literal.is_file():
            files.append(literal)
            continue
        matches = sorted(m for m in Path().glob(pattern) if m.is_file())
        if not matches:
            typer.echo(f"⚠ No artifact matched: {pattern}", err=True)
        files.extend(matches)

    seen = set(exclude)
    for path in files:
        key = path.resolve()
        if key in seen:
            continue
        seen.add(key)
        try:
            client.upload_artifact(str(path), run_id=test_run_id)
            typer.echo(f"✓ Uploaded artifact: {path.name}")
        except Exception as exc:
            typer.echo(f"⚠ Could not upload {path}: {exc}", err=True)


# Logs, screenshots, plots, traces and packet captures a suite may leave behind.
LOG_PATTERNS = ("*.log", "*.out", "*.err")
CAPTURE_PATTERNS = ("*.pcap", "*.pcapng", "*.cap", "*.trace")


def _display_name(name: Any, path: Path) -> str:
    """The name a step artifact is shown under in Bud: the name given to ``attach_artifact``
    without control characters, ending with the file's extension, at most 255 characters."""
    text = "".join(ch for ch in str(name or "") if ord(ch) >= 32).strip() or path.name
    suffix = path.suffix
    if suffix and not text.lower().endswith(suffix.lower()):
        text += suffix
    if len(text) > 255:
        text = text[: 255 - len(suffix)] + suffix if suffix else text[:255]
    return text


def _step_artifacts(results: List[Any]) -> List[Tuple[Path, str, str]]:
    """The files steps attached with budtestlibrary's ``attach_artifact``, from each result's
    ``metadata["artifacts"]``, as (path, display name, test case ``<class>.<step>``); a file
    attached more than once is listed once, with the first step that attached it."""
    found: List[Tuple[Path, str, str]] = []
    seen = set()
    for row in _flatten_results(results):
        entries = (row.get("metadata") or {}).get("artifacts") or []
        if not isinstance(entries, list):
            continue
        step = f"{row.get('test_class')}.{row.get('test_method')}"
        test_case = "".join(ch for ch in step if ord(ch) >= 32)[:255]
        for entry in entries:
            if not isinstance(entry, dict) or not entry.get("path"):
                continue
            path = Path(str(entry["path"]))
            key = path.resolve()
            if key in seen:
                continue
            seen.add(key)
            found.append((path, _display_name(entry.get("name"), path), test_case))
    return found


def _upload_step_artifacts(
    client: BudAPIClient, steps: List[Tuple[Path, str, str]], test_run_id: int
) -> set:
    """Upload the files steps attached, each marked with its step; a missing file is skipped.
    The resolved paths of the files that were uploaded."""
    sent = set()
    for path, name, test_case in steps:
        if not path.is_file():
            typer.echo(f"⚠ Step artifact not found: {path} ({test_case})", err=True)
            continue
        try:
            client.upload_artifact(
                str(path), run_id=test_run_id, test_case=test_case, filename=name
            )
            typer.echo(f"✓ Uploaded step artifact: {name} ({test_case})")
            sent.add(path.resolve())
        except Exception as exc:
            typer.echo(f"⚠ Could not upload {path}: {exc}", err=True)
    return sent


def _discover_artifacts(artifact_dir: Path) -> List[Path]:
    """Whatever the run left behind, if anything did.

    Everything under the artifact directory, plus logs and captures written
    beside the run. Scanning the whole workspace would sweep up the repository
    itself, so only these two places are looked at.
    """
    found: List[Path] = []
    if artifact_dir.is_dir():
        found.extend(p for p in sorted(artifact_dir.rglob("*")) if p.is_file())
    for pattern in LOG_PATTERNS + CAPTURE_PATTERNS:
        found.extend(p for p in sorted(Path().glob(pattern)) if p.is_file())
    return found


def _custom_dir() -> Path:
    """Directory for generated test case lists."""
    custom_dir = Path(tempfile.gettempdir()) / "bud" / "custom"
    custom_dir.mkdir(parents=True, exist_ok=True)
    return custom_dir


def _write_custom_test_list(test_paths: List[str], test_run_id: int) -> str:
    """Write a claimed selection as a test case list module.

    A custom run arrives as a list of module.Class paths, which is what a test
    case list already holds. Writing one means the selection is executed by the
    loader every other run goes through. The run id keeps the module name
    unique, so a second run is not served the first one's import cache.
    """
    module = f"bud_custom_{test_run_id}"
    body = "CUSTOM_TEST_LIST = [\n" + "".join(f"    {path!r},\n" for path in test_paths) + "]\n"
    (_custom_dir() / f"{module}.py").write_text(body, encoding="utf-8")
    return f"{module}.CUSTOM_TEST_LIST"


def _run_claimed(
    claimed: dict,
    passthrough: List[str],
    workspace: Optional[Path],
) -> int:
    """Execute a claimed run through the existing run-tests command."""
    run = claimed["run"]
    selected = claimed.get("selected_tests")
    test_case_list = (
        _write_custom_test_list(selected, run["id"]) if selected else run["test_case_list"]
    )

    cmd = [
        sys.executable,
        "-m",
        "bud_runner",
        "run-tests",
        "--test-case-list",
        test_case_list,
        "--test-run-id",
        str(run["id"]),
        *passthrough,
    ]

    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(_custom_dir()), *sys.path])

    return subprocess.run(cmd, cwd=workspace, env=env).returncode


def _flush_spooled_results(
    client: BudAPIClient,
    auth: AuthManager,
    username: Optional[str],
    password: Optional[str],
) -> None:
    """Replay any spooled result payloads from earlier failed runs."""
    for spool_file in sorted(_spool_dir().glob("*.json")):
        payload = json.loads(spool_file.read_text(encoding="utf-8"))
        try:
            _upload_payload_with_retry(client, auth, payload, username, password)
        except Exception as exc:
            typer.echo(
                f"⚠ Could not replay spooled results from {spool_file.name}: {exc}", err=True
            )
            return
        spool_file.unlink(missing_ok=True)
        typer.echo(f"✓ Replayed spooled results from {spool_file.name}")


@app.command()
def add_test_run(
    test_case_list: str = typer.Option(
        ...,
        "--test-case-list",
        "-t",
        help="Test case list module path (e.g., Bud_Test_Suite.CORE_TEST_CASES)",
    ),
    test_suite_name: str = typer.Option(
        ...,
        "--test-suite-name",
        "-n",
        help="Name for the test suite run",
    ),
    url_test_software: Optional[str] = typer.Option(
        None,
        "--url-test-software",
        "--url-test-sw",
        help="URL to the test software repository",
    ),
    ref_test_software: str = typer.Option(
        "main",
        "--ref-test-software",
        "--ref-test-sw",
        help="Git ref (branch/tag/commit) of the test software",
    ),
    url_software_under_test: Optional[str] = typer.Option(
        None,
        "--sw-under-test",
        help="URL to the software-under-test repository",
    ),
    ref_software_under_test: Optional[str] = typer.Option(
        None,
        "--ref-sw-under-test",
        help="Git ref (branch/tag/commit) of the software under test",
    ),
    product_composition_id: int = typer.Option(
        1,
        "--product-composition-id",
        help="Product composition ID",
    ),
    status: str = typer.Option(
        "Running",
        "--status",
        help="Initial status of the test run",
    ),
    pipeline_software_under_test: bool = typer.Option(
        False,
        "--pipeline-software-under-test",
        help="Use software version from CI pipeline",
    ),
    backend_url: Optional[str] = typer.Option(
        None,
        "--backend-url",
        "-b",
        help="Backend URL (default: from config)",
    ),
    username: Optional[str] = typer.Option(
        None,
        "--username",
        "-u",
        help="Username for authentication",
    ),
    bud_token: Optional[str] = typer.Option(
        None,
        "--bud-token",
        help="API token for authentication",
    ),
    output_format: OutputFormat = typer.Option(
        OutputFormat.text,
        "--output-format",
        help="Output format for this command's response (text or json). Use json in CI to parse the returned run id.",
    ),
):
    """
    Create a new test run on the Bud platform.

    This command registers a new test run with the backend, which can then
    be executed by a runner.
    """
    auth = AuthManager(username=username, token=bud_token, backend_url=backend_url)
    if not auth.backend_url:
        typer.echo(
            "✗ No backend URL configured. Pass --backend-url or set BUD_BACKEND_URL.", err=True
        )
        raise typer.Exit(code=2)
    if not auth.token:
        typer.echo(
            "✗ Missing BUD_TOKEN. Export BUD_TOKEN or pass --bud-token before creating a test run.",
            err=True,
        )
        raise typer.Exit(code=2)

    client = BudAPIClient(auth)

    if output_format != OutputFormat.json:
        typer.echo(f"Creating test run: {test_suite_name}")
        typer.echo(f"Test case list: {test_case_list}")

    try:
        result = client.create_test_run(
            test_case_list=test_case_list,
            test_suite_name=test_suite_name,
            url_test_software=url_test_software,
            ref_test_software=ref_test_software,
            url_software_under_test=url_software_under_test,
            ref_software_under_test=ref_software_under_test,
            product_composition_id=product_composition_id,
            status=status,
            pipeline_software_under_test=pipeline_software_under_test,
        )

        if output_format == OutputFormat.json:
            # Emit ONLY JSON on stdout so CI can pipe it into `jq` safely.
            typer.echo(json.dumps(result))
        else:
            typer.echo(
                f"✓ Test run created: ID={result.get('id')} ProductID={result.get('product_id')}"
            )
            typer.echo(f"  URL: {result.get('url')}")

    except Exception as e:
        typer.echo(f"✗ Error creating test run: {e}", err=True)
        raise typer.Exit(code=1)


@app.command()
def run_tests(
    test_case_list: str = typer.Option(
        ...,
        "--test-case-list",
        "-t",
        help="Test case list module path (e.g., Bud_Test_Suite.CORE_TEST_CASES)",
    ),
    output: Path = typer.Option(
        Path("report_junit.xml"),
        "--output",
        "--junit-report",
        "-o",
        help="Output file for JUnit XML report",
    ),
    format: OutputFormat = typer.Option(
        OutputFormat.junit,
        "--format",
        "-f",
        help="Output format",
    ),
    continue_on_error: bool = typer.Option(
        True,
        "--continue-on-error/--stop-on-error",
        help="Continue running tests after a failure",
    ),
    backend_url: Optional[str] = typer.Option(
        None,
        "--backend-url",
        "-b",
        help=BACKEND_URL_FOR_RESULT_UPLOAD,
    ),
    username: Optional[str] = typer.Option(
        None,
        "--username",
        "-u",
        help="Bud user email for token refresh during uploads",
    ),
    password: Optional[str] = typer.Option(
        None,
        "--password",
        help="Bud user password for token refresh during uploads",
        hide_input=True,
    ),
    test_run_id: Optional[int] = typer.Option(
        None,
        "--test-run-id",
        help="Existing TestRun id (from 'add-test-run --output-format json') to associate uploaded results with.",
    ),
    url_test_software: Optional[str] = typer.Option(
        None,
        "--url-test-software",
        "--url-test-sw",
        help="URL to the test software repository (for auto-created test runs)",
    ),
    ref_test_software: Optional[str] = typer.Option(
        None,
        "--ref-test-software",
        "--ref-test-sw",
        help="Git ref of the test software (for auto-created test runs)",
    ),
    url_software_under_test: Optional[str] = typer.Option(
        None,
        "--sw-under-test",
        help="URL to the software-under-test repository (for auto-created test runs)",
    ),
    ref_software_under_test: Optional[str] = typer.Option(
        None,
        "--ref-sw-under-test",
        help="Git ref of the software under test (for auto-created test runs)",
    ),
    bud_token: Optional[str] = typer.Option(
        None,
        "--bud-token",
        help="API token for authentication (otherwise read from BUD_TOKEN env).",
    ),
    upload_results: bool = typer.Option(
        True,
        UPLOAD_NO_UPLOAD,
        help="Upload results to backend",
    ),
    artifacts: List[str] = typer.Option(
        [],
        "--artifact",
        "-A",
        help="File or glob to upload with the results. Repeatable.",
    ),
    artifact_dir: Path = typer.Option(
        Path("bud-artifacts"),
        "--artifact-dir",
        help="Directory whose contents are uploaded if it exists.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show suite DEBUG output, including per-step lifecycle logs.",
    ),
    test_timeout: int = typer.Option(
        300,
        "--test-timeout",
        help="Max seconds per individual test (default: 300)",
    ),
    suite_timeout: int = typer.Option(
        1800,
        "--suite-timeout",
        help="Max seconds for the full suite (default: 1800)",
    ),
):
    """
    Execute tests from a test case list.

    Runs all tests in the specified test case list and generates a JUnit XML
    report for CI/CD integration.
    """
    import signal

    interrupted = False

    def _on_interrupt(signum, frame):
        nonlocal interrupted
        if interrupted:
            typer.echo("\nForce exiting...", err=True)
            os._exit(128 + signum)
        interrupted = True
        typer.echo(
            "\nInterrupted — finishing current test and collecting results...",
            err=True,
        )

    signal.signal(signal.SIGINT, _on_interrupt)
    signal.signal(signal.SIGTERM, _on_interrupt)

    executor = TestExecutor(test_timeout=test_timeout, suite_timeout=suite_timeout, verbose=verbose)
    reporter = JUnitReporter()

    typer.echo(f"Running tests from: {test_case_list}")

    start_time = time.time()
    try:
        # Import and run tests
        results = executor.run_test_list(
            test_case_list=test_case_list,
            continue_on_error=continue_on_error,
            should_stop=lambda: interrupted,
        )
        duration = time.time() - start_time

        # Generate report
        if format == OutputFormat.junit:
            xml_content = reporter.generate(results)
            output.write_text(xml_content)
            typer.echo(f"✓ JUnit report written to: {output}")

        # Upload results if requested. Requires a backend URL.
        if upload_results:
            auth = AuthManager(username=username, backend_url=backend_url, bud_token=bud_token)
            if not auth.backend_url:
                typer.echo(
                    "✗ No backend URL configured. Pass --backend-url or set BUD_BACKEND_URL.",
                    err=True,
                )
                raise typer.Exit(code=2)

            client = BudAPIClient(auth)
            _flush_spooled_results(client, auth, username, password)

            # If we don't have a product_id yet, try to get it from the run if we have a run_id
            final_product_id = None
            if test_run_id:
                try:
                    run_info = client.get_test_run(test_run_id)
                    final_product_id = run_info.get("product_id")
                except Exception:
                    pass

            payload = client.build_results_payload(
                results,
                test_run_id=test_run_id,
                product_id=final_product_id or auth.product_id,
                test_suite_name=test_case_list,
                url_test_software=url_test_software,
                ref_test_software=ref_test_software,
                url_software_under_test=url_software_under_test,
                ref_software_under_test=ref_software_under_test,
            )
            ok = True
            answer: Any = None
            if payload:
                try:
                    answer = _upload_payload_with_retry(client, auth, payload, username, password)
                except Exception as exc:
                    spool_file = _spool_results_payload(payload)
                    typer.echo(
                        f"✗ Result upload failed: {exc}. Payload spooled to {spool_file}",
                        err=True,
                    )
                    raise typer.Exit(code=1)

            if ok:
                suffix = f" (test_run_id={test_run_id})" if test_run_id else ""
                typer.echo(f"✓ Results uploaded to backend{suffix}")

                # Final status only: POST /api/results already rolls up total_tests /
                # passed_tests / failed_tests by test_class on the server. Do not PATCH
                # method-row totals here — they would overwrite the TC-class contract.
                if test_run_id:
                    final_status = "Completed"
                    client.update_test_run(
                        run_id=test_run_id,
                        status=final_status,
                        duration_seconds=duration,
                        product_id=final_product_id,
                    )
                    passed_tcs = sum(1 for r in results if r.passed)
                    total_tcs = len(results)
                    typer.echo(
                        f"✓ Test run {test_run_id} marked as {final_status} "
                        f"({passed_tcs} out of {total_tcs} TC passed)."
                    )

                steps = _step_artifacts(results)
                step_run_id = test_run_id
                if not step_run_id and isinstance(answer, dict):
                    step_run_id = answer.get("test_run_id")
                sent_steps: set = set()
                if steps and step_run_id:
                    sent_steps = _upload_step_artifacts(client, steps, int(step_run_id))
                elif steps:
                    typer.echo(
                        f"⚠ Step artifacts need a test run: {len(steps)} not uploaded.", err=True
                    )
                if test_run_id:
                    # The report is the one artifact every run produces, so it
                    # goes up without being asked for.
                    to_upload: List[str] = []
                    if format == OutputFormat.junit and output.is_file():
                        to_upload.append(str(output))
                    to_upload.extend(str(p) for p in _discover_artifacts(Path(artifact_dir)))
                    to_upload.extend(artifacts)
                    if to_upload:
                        _upload_artifacts(client, to_upload, test_run_id, exclude=sent_steps)
                elif artifacts:
                    typer.echo(
                        "⚠ Artifacts need a test run: pass --test-run-id.",
                        err=True,
                    )
            else:
                typer.echo("✗ Result upload failed", err=True)
                raise typer.Exit(code=1)

        # Print final Test Case level summary
        passed_tcs = sum(1 for r in results if r.passed)
        failed_tcs = len(results) - passed_tcs

        typer.echo(f"\nFinal Suite Result: {passed_tcs} TC(s) passed, {failed_tcs} TC(s) failed")

        # Exit with error if any test case failed
        if failed_tcs > 0:
            raise typer.Exit(code=1)

    except typer.Exit:
        # Re-raise Typer's clean exit exception
        raise
    except Exception as e:
        typer.echo(f"✗ Error running tests: {e}", err=True)
        raise typer.Exit(code=1)


@app.command(name="claim-run")
def claim_run(
    backend_url: Optional[str] = typer.Option(
        None,
        "--backend-url",
        "-b",
        help="Backend URL to claim runs from",
    ),
    username: Optional[str] = typer.Option(
        None,
        "--username",
        "-u",
        help="Runner account to claim as",
    ),
    workspace: Optional[Path] = typer.Option(
        None,
        "--workspace",
        "-w",
        help="Directory holding this station's test modules (default: current directory)",
    ),
    interval: int = typer.Option(
        0,
        "--interval",
        "-i",
        help="Seconds between polls. 0 claims once and exits.",
    ),
    artifacts: List[str] = typer.Option(
        [],
        "--artifact",
        "-A",
        help="File or glob to upload with each claimed run. Repeatable.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show suite DEBUG output, including per-step lifecycle logs.",
    ),
    test_timeout: int = typer.Option(
        300,
        "--test-timeout",
        help="Max seconds per individual test (default: 300)",
    ),
    suite_timeout: int = typer.Option(
        1800,
        "--suite-timeout",
        help="Max seconds for the full suite (default: 1800)",
    ),
):
    """
    Run whatever the backend has queued for this test station.

    The station asks for its next run and executes it with run-tests, so a
    custom selection takes the same path as any other run. Nothing connects
    inward to the bench.
    """
    auth = AuthManager(username=username, backend_url=backend_url)
    if not auth.backend_url:
        typer.echo(
            "✗ No backend URL configured. Pass --backend-url or set BUD_BACKEND_URL.",
            err=True,
        )
        raise typer.Exit(code=2)
    if not auth.runner_token:
        typer.echo(
            "✗ No runner token. Run 'bud_runner register' on this station first.",
            err=True,
        )
        raise typer.Exit(code=2)

    client = BudAPIClient(auth)

    passthrough = ["--test-timeout", str(test_timeout), "--suite-timeout", str(suite_timeout)]
    if verbose:
        passthrough.append("--verbose")
    passthrough.extend(["--backend-url", auth.backend_url])
    if auth.runner_account:
        passthrough.extend(["--username", auth.runner_account])
    for pattern in artifacts:
        passthrough.extend(["--artifact", pattern])

    claim_id = str(uuid.uuid4())
    while True:
        try:
            claimed = client.claim_next_run(claim_id)
        except Exception as exc:
            # A poller outlives the backend it talks to; a blip is not the end
            # of the shift. A one-shot claim has nobody to retry for it.
            typer.echo(f"⚠ Could not claim a run: {exc}", err=True)
            if interval <= 0:
                raise typer.Exit(code=1)
            time.sleep(interval)
            continue

        if claimed:
            run = claimed["run"]
            typer.echo(f"✓ Claimed run {run['id']}: {run['name']}")
            execution_error = None
            try:
                code = _run_claimed(claimed, passthrough, workspace)
            except Exception as exc:
                code = 1
                execution_error = f"{type(exc).__name__}: {exc}"
                typer.echo(
                    f"✗ Run {run['id']} could not execute: {execution_error}",
                    err=True,
                )

            while True:
                try:
                    client.complete_claimed_run(
                        run["id"],
                        claimed["claim_id"],
                        exit_code=code,
                        error=execution_error,
                    )
                    break
                except Exception as exc:
                    typer.echo(
                        f"⚠ Could not acknowledge run {run['id']}: {exc}",
                        err=True,
                    )
                    if interval <= 0:
                        raise typer.Exit(code=1)
                    # Do not claim or execute more work until Bud has the
                    # terminal answer for this run.
                    time.sleep(interval)

            typer.echo(f"Run {run['id']} finished with exit code {code}")
            claim_id = str(uuid.uuid4())
            # A poller keeps going; a one-shot claim carries the code to CI.
            if interval <= 0 and code != 0:
                raise typer.Exit(code=code)
        elif interval <= 0:
            typer.echo("Nothing queued.")
        else:
            # A successful empty response proves this key did not claim work.
            claim_id = str(uuid.uuid4())

        if interval <= 0:
            return
        time.sleep(interval)


@app.command(
    name="run-robot",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def run_robot(
    ctx: typer.Context,
    backend_url: Optional[str] = typer.Option(
        None, "--backend-url", "-b", help=BACKEND_URL_FOR_RESULT_UPLOAD
    ),
    test_run_id: Optional[int] = typer.Option(
        None, "--test-run-id", help=EXISTING_TESTRUN_ID_TO_ATTACH_THE_RESULTS_TO
    ),
    product_id: Optional[int] = typer.Option(
        None, "--product-id", help=PRODUCT_ID_FOR_A_RUN_BUD_CREATES_FROM_THE_UPLOAD
    ),
    ref_software_under_test: Optional[str] = typer.Option(
        None, "--ref-sw-under-test", help=GIT_REF_OF_THE_SOFTWARE_UNDER_TEST
    ),
    suite_name: Optional[str] = typer.Option(
        None, "--suite-name", help="Suite name in Bud (default: the Robot root suite name)."
    ),
    upload_results: bool = typer.Option(True, UPLOAD_NO_UPLOAD, help=UPLOAD_RESULTS_TO_BUD),
    upload_artifacts: bool = typer.Option(
        True,
        "--artifacts/--no-artifacts",
        help="Upload output.xml, log.html and report.html with the results",
    ),
):
    """
    Run Robot Framework with the Bud listener attached.

    Every argument Bud does not know is passed to robot unchanged, for example
    ``bud-runner run-robot --backend-url https://bud tests/``. Robot's exit code is
    returned as is, so CI still fails on failed tests.
    """
    try:
        import robot
    except ImportError:
        typer.echo("✗ Robot Framework is not installed: pip install 'bud-runner[robot]'", err=True)
        raise typer.Exit(code=2)

    if upload_results:
        auth = AuthManager(backend_url=backend_url)
        if not auth.backend_url:
            typer.echo(
                "✗ No backend URL configured. Pass --backend-url or set BUD_BACKEND_URL.",
                err=True,
            )
            raise typer.Exit(code=2)
        try:
            _flush_spooled_results(BudAPIClient(auth), auth, None, None)
        except Exception as exc:
            typer.echo(f"⚠ Could not replay spooled results: {exc}", err=True)

    options = {
        "backend": backend_url,
        "test_run_id": test_run_id,
        "product_id": product_id,
        "ref_sw_under_test": ref_software_under_test,
        "suite_name": suite_name,
        "upload": "true" if upload_results else "false",
        "artifacts": "true" if upload_artifacts else "false",
    }
    listener = "bud_runner.robot_listener.BudListener" + "".join(
        f";{key}={value}" for key, value in options.items() if value is not None
    )
    rc = robot.run_cli(["--listener", listener, *ctx.args], exit=False)
    raise typer.Exit(code=rc)


def _pytest_pycache_dir() -> Path:
    """Directory for the bytecode of a ``run-pytest`` session."""
    candidates = [
        Path.home() / ".bud" / "pycache",
        Path(tempfile.gettempdir()) / "bud" / "pycache",
    ]
    for cache_dir in candidates:
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            return cache_dir
        except OSError:
            continue
    raise RuntimeError("Could not create a writable bytecode cache directory")


@app.command(
    name="run-pytest",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def run_pytest(
    ctx: typer.Context,
    backend_url: Optional[str] = typer.Option(
        None, "--backend-url", "-b", help=BACKEND_URL_FOR_RESULT_UPLOAD
    ),
    test_run_id: Optional[int] = typer.Option(
        None, "--test-run-id", help=EXISTING_TESTRUN_ID_TO_ATTACH_THE_RESULTS_TO
    ),
    product_id: Optional[int] = typer.Option(
        None, "--product-id", help=PRODUCT_ID_FOR_A_RUN_BUD_CREATES_FROM_THE_UPLOAD
    ),
    ref_software_under_test: Optional[str] = typer.Option(
        None, "--ref-sw-under-test", help=GIT_REF_OF_THE_SOFTWARE_UNDER_TEST
    ),
    suite_name: Optional[str] = typer.Option(
        None, "--suite-name", help="Suite name in Bud (default: the pytest rootdir name)."
    ),
    upload_results: bool = typer.Option(True, UPLOAD_NO_UPLOAD, help=UPLOAD_RESULTS_TO_BUD),
):
    """
    Run pytest with the Bud plugin attached.

    Every argument Bud does not know is passed to pytest unchanged, for example
    ``bud-runner run-pytest --backend-url https://bud tests/ -k smoke``. The session runs
    with pytest's assertion pass hook on and compiles its bytecode into
    ``~/.bud/pycache``, where every rewritten test module has the hook, and passing
    assert statements are reported too. pytest's exit code is returned as is.
    """
    try:
        import pytest
    except ImportError:
        typer.echo("✗ pytest is not installed: pip install 'bud-runner[pytest]'", err=True)
        raise typer.Exit(code=2)

    if upload_results:
        auth = AuthManager(backend_url=backend_url)
        if not auth.backend_url:
            typer.echo(
                "✗ No backend URL configured. Pass --backend-url or set BUD_BACKEND_URL.",
                err=True,
            )
            raise typer.Exit(code=2)
        try:
            _flush_spooled_results(BudAPIClient(auth), auth, None, None)
        except Exception as exc:
            typer.echo(f"⚠ Could not replay spooled results: {exc}", err=True)

    options = {
        "--bud-backend-url": backend_url,
        "--bud-test-run-id": test_run_id,
        "--bud-product-id": product_id,
        "--bud-ref-sw-under-test": ref_software_under_test,
        "--bud-suite-name": suite_name,
    }
    args = ["-p", "bud_runner.pytest_plugin", "-o", "enable_assertion_pass_hook=true"]
    args += [f"{key}={value}" for key, value in options.items() if value is not None]
    if not upload_results:
        args.append("--bud-no-upload")
    previous_prefix = sys.pycache_prefix
    sys.pycache_prefix = str(_pytest_pycache_dir())
    try:
        rc = pytest.main([*args, *ctx.args])
    finally:
        sys.pycache_prefix = previous_prefix
    raise typer.Exit(code=int(rc))


def _names_a_formatter(args: List[str]) -> bool:
    """Whether Behave arguments choose an output format (``-f``/``--format``)."""
    for arg in args:
        if arg in ("-f", "--format") or arg.startswith("--format="):
            return True
        if arg.startswith("-f") and not arg.startswith("--"):
            return True
    return False


@app.command(
    name="run-behave",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def run_behave(
    ctx: typer.Context,
    backend_url: Optional[str] = typer.Option(
        None, "--backend-url", "-b", help=BACKEND_URL_FOR_RESULT_UPLOAD
    ),
    test_run_id: Optional[int] = typer.Option(
        None, "--test-run-id", help=EXISTING_TESTRUN_ID_TO_ATTACH_THE_RESULTS_TO
    ),
    product_id: Optional[int] = typer.Option(
        None, "--product-id", help=PRODUCT_ID_FOR_A_RUN_BUD_CREATES_FROM_THE_UPLOAD
    ),
    ref_software_under_test: Optional[str] = typer.Option(
        None, "--ref-sw-under-test", help=GIT_REF_OF_THE_SOFTWARE_UNDER_TEST
    ),
    suite_name: Optional[str] = typer.Option(
        None,
        "--suite-name",
        help="Suite name in Bud (default: the feature name, or the features directory).",
    ),
    upload_results: bool = typer.Option(True, UPLOAD_NO_UPLOAD, help=UPLOAD_RESULTS_TO_BUD),
):
    """
    Run Behave with the Bud formatter attached.

    Every argument Bud does not know is passed to behave unchanged, for example
    ``bud-runner run-behave --backend-url https://bud features/ --tags=@smoke``. The Bud
    formatter writes nothing to the console; without ``-f`` in the arguments Behave's
    ``pretty`` output is shown as well. Behave's exit code is returned as is.
    """
    try:
        from behave.__main__ import main as behave_main
    except ImportError:
        typer.echo("✗ Behave is not installed: pip install 'bud-runner[behave]'", err=True)
        raise typer.Exit(code=2)

    if upload_results:
        auth = AuthManager(backend_url=backend_url)
        if not auth.backend_url:
            typer.echo(
                "✗ No backend URL configured. Pass --backend-url or set BUD_BACKEND_URL.",
                err=True,
            )
            raise typer.Exit(code=2)
        try:
            _flush_spooled_results(BudAPIClient(auth), auth, None, None)
        except Exception as exc:
            typer.echo(f"⚠ Could not replay spooled results: {exc}", err=True)

    userdata = {
        "bud_backend_url": backend_url,
        "bud_test_run_id": test_run_id,
        "bud_product_id": product_id,
        "bud_ref_sw_under_test": ref_software_under_test,
        "bud_suite_name": suite_name,
        "bud_upload": "true" if upload_results else "false",
    }
    args = ["-f", "bud_runner.behave_formatter:BudFormatter", "-o", os.devnull]
    if not _names_a_formatter(ctx.args):
        args += ["-f", "pretty"]
    for key, value in userdata.items():
        if value is not None:
            args += ["-D", f"{key}={value}"]
    rc = behave_main([*args, *ctx.args])
    raise typer.Exit(code=int(rc or 0))


@app.command(name="import-cucumber")
def import_cucumber(
    report: Path = typer.Option(..., "--report", help="Cucumber JSON report to import."),
    backend_url: Optional[str] = typer.Option(
        None, "--backend-url", "-b", help=BACKEND_URL_FOR_RESULT_UPLOAD
    ),
    test_run_id: Optional[int] = typer.Option(
        None, "--test-run-id", help=EXISTING_TESTRUN_ID_TO_ATTACH_THE_RESULTS_TO
    ),
    product_id: Optional[int] = typer.Option(
        None, "--product-id", help=PRODUCT_ID_FOR_A_RUN_BUD_CREATES_FROM_THE_UPLOAD
    ),
    ref_software_under_test: Optional[str] = typer.Option(
        None, "--ref-sw-under-test", help=GIT_REF_OF_THE_SOFTWARE_UNDER_TEST
    ),
    suite_name: Optional[str] = typer.Option(
        None,
        "--suite-name",
        help="Suite name in Bud (default: the feature name, or the features directory).",
    ),
    upload_results: bool = typer.Option(True, UPLOAD_NO_UPLOAD, help=UPLOAD_RESULTS_TO_BUD),
    upload_artifacts: bool = typer.Option(
        True, "--artifacts/--no-artifacts", help="Attach the report file to the Bud run"
    ),
):
    """
    Import a Cucumber JSON report into Bud.

    Reads the report written by cucumber-js, Cucumber-JVM or Cucumber-Ruby and uploads it
    as a Bud run, for example ``bud-runner import-cucumber --report report.json``. Exit
    code 0 when the report was read and, with ``--upload``, reached Bud; 1 when the upload
    did not reach Bud (the results are spooled); 2 when the report is unreadable or no
    backend is configured.
    """
    from bud_runner.cucumber_importer import CucumberReport, CucumberReportError, read_report
    from bud_runner.reporting import send_run

    try:
        features = read_report(report)
    except CucumberReportError as exc:
        typer.echo(f"✗ {report}: {exc}", err=True)
        raise typer.Exit(code=2)
    imported = CucumberReport(
        features,
        report_path=report,
        test_run_id=test_run_id,
        product_id=product_id,
        suite_name=suite_name,
        ref_sw_under_test=ref_software_under_test,
    )
    counts = imported.counts()
    typer.echo(
        f"Cucumber report {report.name}: {counts['features']} features, {counts['scenarios']} scenarios "
        f"({counts['passed']} passed, {counts['failed']} failed, {counts['skipped']} skipped)"
    )
    if not upload_results or not imported.results:
        raise typer.Exit(code=0)
    auth = AuthManager(backend_url=backend_url)
    if not auth.backend_url:
        typer.echo(
            "✗ No backend URL configured. Pass --backend-url or set BUD_BACKEND_URL.",
            err=True,
        )
        raise typer.Exit(code=2)
    try:
        _flush_spooled_results(BudAPIClient(auth), auth, None, None)
    except Exception as exc:
        typer.echo(f"⚠ Could not replay spooled results: {exc}", err=True)
    reached = send_run(
        imported.payload,
        framework="Cucumber",
        backend=backend_url,
        test_run_id=test_run_id,
        files=[report] if upload_artifacts else (),
    )
    raise typer.Exit(code=0 if reached else 1)


@app.command(name="list-tests")
def list_tests(
    test_case_list: str = typer.Option(
        ...,
        "--test-case-list",
        "-t",
        help="Test case list module path (e.g., Bud_Test_Suite.CORE_TEST_CASES)",
    ),
    output_format: StatusOutputFormat = typer.Option(
        StatusOutputFormat.text,
        "--output-format",
        help="Output format for this command (text or json).",
    ),
):
    """
    Resolve a test case list without executing the tests.
    """
    executor = TestExecutor()

    try:
        test_classes = executor.load_test_list(test_case_list)
    except Exception as e:
        typer.echo(f"✗ Error loading tests: {e}", err=True)
        raise typer.Exit(code=1)

    resolved = [
        {
            "name": test_class.__name__,
            "module": test_class.__module__,
            "path": f"{test_class.__module__}.{test_class.__name__}",
        }
        for test_class in test_classes
    ]

    if output_format == StatusOutputFormat.json:
        typer.echo(
            json.dumps(
                {
                    "test_case_list": test_case_list,
                    "count": len(resolved),
                    "tests": resolved,
                }
            )
        )
        return

    typer.echo(f"Resolved {len(resolved)} test class(es) from {test_case_list}:")
    for test_class in resolved:
        typer.echo(f"  - {test_class['path']}")


def _start_daemon_background(username: str, backend_url: Optional[str], interval: int, port: int):
    """Helper to spawn the daemon in the background as a detached process."""
    cmd = [
        sys.executable,
        "-m",
        "bud_runner",
        "daemon",
        "--username",
        username,
        "--interval",
        str(interval),
        "--port",
        str(port),
    ]
    if backend_url:
        cmd.extend(["--backend-url", backend_url])

    # Ensure logs are persistent and namespaced
    daemons_dir = Path.home() / ".bud" / "daemons"
    daemons_dir.mkdir(parents=True, exist_ok=True)
    log_file = open(daemons_dir / f"bud_{username}.log", "a")

    # Capture current environment and ensure PYTHONPATH includes sys.path
    env = os.environ.copy()
    # Pass the current python sys.path to the subprocess so it has access to the exact same libraries
    env["PYTHONPATH"] = os.pathsep.join(sys.path)

    try:
        # Spawn background process detached from the current terminal session
        process = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
            env=env,
        )
        # Record PID for management
        with open(daemons_dir / f"bud_{username}.pid", "w") as f:
            f.write(str(process.pid))
        return process.pid
    except Exception as e:
        typer.echo(f"⚠ Could not start background daemon automatically: {e}", err=True)
        return None


@app.command()
def register(
    username: str = typer.Option(
        ...,
        "--username",
        "-u",
        help="Runner username/account name",
    ),
    password: Optional[str] = typer.Option(
        None,
        "--password",
        "-p",
        help="Password for registration (auto-generated if omitted)",
        hide_input=True,
    ),
    backend_url: Optional[str] = typer.Option(
        None,
        "--backend-url",
        "-b",
        help="Backend URL",
    ),
    socket_port: int = typer.Option(
        53035,
        "--socket-port",
        help="Socket port for runner communication",
    ),
    api_key: Optional[str] = typer.Option(
        None,
        "--api-key",
        envvar="RUNNER_API_KEY",
        help="This station's enrolment key, minted by a Bud administrator under "
        "Test Stations, sent as X-API-Key for POST /api/runners/register. A key pins "
        "to the first station that registers with it. Falls back to the RUNNER_API_KEY "
        "env var.",
    ),
    no_start: bool = typer.Option(
        False,
        "--no-start",
        help="Do NOT start the heartbeat daemon automatically after registration",
    ),
    re_register: bool = typer.Option(
        False,
        "--re-register",
        help="Refresh an already-registered runner using its existing password",
    ),
):
    """
    Register this machine as a test runner.

    Creates a runner account, stores credentials in your global machine vault,
    and automatically starts the heartbeat daemon in the background.
    """
    auth = AuthManager(backend_url=backend_url, runner_api_key=api_key)
    if not auth.backend_url:
        typer.echo(
            "✗ No backend URL configured. Pass --backend-url or set BUD_BACKEND_URL.", err=True
        )
        raise typer.Exit(code=2)
    if not auth.runner_api_key:
        typer.echo(
            "✗ RUNNER_API_KEY is not configured. Pass --api-key or export "
            "RUNNER_API_KEY (this station's enrolment key, minted by a Bud "
            "administrator under Test Stations).",
            err=True,
        )
        raise typer.Exit(code=2)

    existing_identity = auth.vault.get_runner(username)
    if existing_identity and not re_register:
        typer.echo(
            "✗ Runner is already registered locally. Use --re-register with the "
            "existing password to refresh the token or update socket settings.",
            err=True,
        )
        raise typer.Exit(code=2)

    generated_password = False
    if password is None:
        if re_register:
            typer.echo(
                "✗ Re-registration requires the existing runner password. Pass "
                "--password together with --re-register.",
                err=True,
            )
            raise typer.Exit(code=2)
        generated_password = True
        password = secrets.token_urlsafe(18)

    manager = RunnerManager(auth)

    typer.echo(f"{'Re-registering' if re_register else 'Registering'} runner: {username}")

    try:
        result = manager.register(
            username=username,
            password=password,
            socket_port=socket_port,
        )
        username = result.get("account") or username

        typer.echo(f"✓ Registered as {username}. Identity saved to ~/.bud/config.json")
        if generated_password:
            typer.echo("Generated password for this runner account. Save it somewhere secure:")
            typer.echo(password)

        if not no_start:
            typer.echo(f"✓ Spawning heartbeat daemon in background for {username}...")
            pid = _start_daemon_background(
                username=username, backend_url=backend_url, interval=60, port=socket_port
            )
            if pid:
                typer.echo(
                    f"  Daemon started (PID: {pid}). Monitoring: ~/.bud/daemons/bud_{username}.log"
                )

        typer.echo("\nProject Link (copy to your repo app.properties):")
        typer.echo("-" * 40)
        typer.echo(f"budRunnerAccount={username}")
        typer.echo(f"budBackend={auth.backend_url}")
        typer.echo("-" * 40)

    except Exception as e:
        typer.echo(f"✗ Registration failed: {e}", err=True)
        raise typer.Exit(code=1)


@app.command()
def daemon(
    username: Optional[str] = typer.Option(
        None,
        "--username",
        "-u",
        help="Runner account to use (loads secret from vault)",
    ),
    backend_url: Optional[str] = typer.Option(
        None,
        "--backend-url",
        "-b",
        help="Backend URL",
    ),
    interval: int = typer.Option(
        60,
        "--interval",
        "-i",
        help="Heartbeat interval in seconds",
    ),
    port: Optional[int] = typer.Option(
        None,
        "--port",
        "-p",
        help="Socket listener port (falls back to registered port)",
    ),
    bind_host: str = typer.Option(
        "127.0.0.1",
        "--bind-host",
        help="Host interface for the daemon socket listener",
    ),
    location: Optional[str] = typer.Option(
        None,
        "--location",
        "-l",
        help="Human-readable location of the test station",
    ),
):
    """
    Start the runner daemon (heartbeat + socket listener).

    This process must remain running for the runner to appear 'Online'
    and receive remote commands.
    """
    import asyncio
    import signal
    import sys

    auth = AuthManager(username=username, backend_url=backend_url)
    if not auth.runner_account or not auth.token:
        typer.echo(
            "✗ Runner is not configured. Please run 'register' first or provide BUD_RUNNER_TOKEN.",
            err=True,
        )
        raise typer.Exit(code=2)

    resolved_port = port or auth.socket_port
    manager = RunnerManager(auth)

    _configure_daemon_logging()

    typer.echo(f"Starting Bud Runner Daemon for: {auth.runner_account}")
    typer.echo(f"  Backend: {auth.backend_url}")
    typer.echo(f"  Heartbeat Interval: {interval}s")
    typer.echo(f"  Socket Port: {resolved_port}")
    typer.echo(f"  Bind Host: {bind_host}")
    if location:
        typer.echo(f"  Location: {location}")

    def signal_handler(sig, frame):
        typer.echo("\nStopping daemon...")
        manager.stop_heartbeat()
        manager.stop_listener()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        asyncio.run(
            manager.run_daemon(
                port=resolved_port,
                interval=interval,
                location=location,
                host=bind_host,
            )
        )
    except KeyboardInterrupt:
        signal_handler(None, None)
    except Exception as e:
        typer.echo(f"✗ Daemon error: {e}", err=True)
        raise typer.Exit(code=1)


def _read_runner_package_version() -> str:
    """Resolve bud_runner package version from installed package metadata."""
    return read_package_version()


@app.command()
def status(
    backend_url: Optional[str] = typer.Option(
        None,
        "--backend-url",
        "-b",
        help="Backend URL",
    ),
    output_format: StatusOutputFormat = typer.Option(
        StatusOutputFormat.text,
        "--output-format",
        help="Output format for this command (text or json).",
    ),
):
    """
    Show runner status and connectivity.
    """
    auth = AuthManager(backend_url=backend_url)
    status_payload = {
        "backend_url": auth.backend_url or None,
        "runner_account": auth.runner_account,
        "token_configured": bool(auth.token),
        "runner_package_version": _read_runner_package_version(),
        "socket_port": auth.socket_port if auth.runner_account else None,
        "backend_health": "skipped",
        "backend_version": None,
        "daemon": {
            "configured": bool(auth.runner_account and auth.token),
        },
    }

    if auth.backend_url:
        client = BudAPIClient(auth)
        try:
            if client.health_check():
                status_payload["backend_health"] = "ok"
                try:
                    status_payload["backend_version"] = client.get_version()
                except Exception as e:
                    status_payload["backend_version"] = f"error: {e}"
                if auth.runner_account and auth.token:
                    try:
                        runner_status = client.get_runner_status()
                        status_payload["daemon"]["backend_runner_status"] = runner_status
                    except Exception as e:
                        status_payload["daemon"]["backend_runner_status_error"] = str(e)
            else:
                status_payload["backend_health"] = "unreachable"
        except Exception as e:
            status_payload["backend_health"] = f"error: {e}"

    if output_format == StatusOutputFormat.json:
        typer.echo(json.dumps(status_payload))
        return

    typer.echo("Runner Status:")
    typer.echo(f"  Backend URL: {status_payload['backend_url'] or '(not set)'}")
    typer.echo(f"  Runner Account: {auth.runner_account or 'Not configured'}")
    typer.echo(f"  Token: {'Configured' if auth.token else 'Not configured'}")
    typer.echo(f"  Runner package: {status_payload['runner_package_version']}")
    if status_payload["socket_port"] is not None:
        typer.echo(f"  Socket Port: {status_payload['socket_port']}")

    backend_health = status_payload["backend_health"]
    if backend_health == "skipped":
        typer.echo("  Backend Health: (skipped — no backend URL)")
        return
    if backend_health == "ok":
        typer.echo("  Backend Health: ✓ OK")
    elif backend_health == "unreachable":
        typer.echo("  Backend Health: ✗ Unreachable")
    else:
        typer.echo(f"  Backend Health: ✗ {backend_health}")

    if status_payload["backend_version"] is not None:
        typer.echo(f"  Backend Version: {status_payload['backend_version']}")

    runner_status = status_payload["daemon"].get("backend_runner_status")
    if runner_status is not None:
        typer.echo(f"  Daemon Status: {runner_status}")
    elif "backend_runner_status_error" in status_payload["daemon"]:
        typer.echo(f"  Daemon Status: ✗ {status_payload['daemon']['backend_runner_status_error']}")


@app.command(name="version")
def version():
    """Show bud_runner version."""
    typer.echo(f"bud_runner version {_read_runner_package_version()}")


def main():
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
