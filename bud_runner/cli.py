"""
CLI entry point for bud_runner.

Provides commands for test execution, runner registration, and test case synchronization.
"""

import json
import os
import subprocess
import sys
import time
from enum import Enum
from pathlib import Path
from typing import List, Optional

import typer

from bud_runner.api_client import BudAPIClient
from bud_runner.auth import AuthManager
from bud_runner.junit_reporter import JUnitReporter
from bud_runner.runner_manager import RunnerManager
from bud_runner.test_executor import TestExecutor

app = typer.Typer(
    name="bud_runner",
    help="CLI tool for test execution and CI/CD integration with the Bud backend",
    add_completion=False,
)


class OutputFormat(str, Enum):
    """Output format options."""

    json = "json"
    text = "text"
    junit = "junit"


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
        help="URL to the test software repository",
    ),
    ref_test_software: str = typer.Option(
        "main",
        "--ref-test-software",
        help="Git ref (branch/tag/commit) of test software",
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
        help="Backend URL for result upload",
    ),
    test_run_id: Optional[int] = typer.Option(
        None,
        "--test-run-id",
        help="Existing TestRun id (from 'add_test_run --output-format json') to associate uploaded results with.",
    ),
    bud_token: Optional[str] = typer.Option(
        None,
        "--bud-token",
        help="API token for authentication (otherwise read from BUD_TOKEN env).",
    ),
    upload_results: bool = typer.Option(
        True,
        "--upload/--no-upload",
        help="Upload results to backend",
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

    executor = TestExecutor(test_timeout=test_timeout, suite_timeout=suite_timeout)
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
            auth = AuthManager(backend_url=backend_url, bud_token=bud_token)
            if not auth.backend_url:
                typer.echo(
                    "✗ No backend URL configured. Pass --backend-url or set BUD_BACKEND_URL.",
                    err=True,
                )
                raise typer.Exit(code=2)

            client = BudAPIClient(auth)

            # If we don't have a product_id yet, try to get it from the run if we have a run_id
            final_product_id = None
            if test_run_id:
                try:
                    run_info = client.get_test_run(test_run_id)
                    final_product_id = run_info.get("product_id")
                except Exception:
                    pass

            ok = client.upload_results(
                results,
                test_run_id=test_run_id,
                product_id=final_product_id or auth.product_id,
                test_suite_name=test_case_list,
            )
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
    log_file = open(f"bud_{username}.log", "a")

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
        with open(f"bud_{username}.pid", "w") as f:
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
        help="Password for registration (prompt if not provided)",
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
        help="Shared secret sent as X-API-Key for POST /api/runners/register (matches backend RUNNER_API_KEY). "
        "Falls back to RUNNER_API_KEY env var.",
    ),
    no_start: bool = typer.Option(
        False,
        "--no-start",
        help="Do NOT start the heartbeat daemon automatically after registration",
    ),
):
    """
    Register this machine as a test runner.

    Creates a runner account, stores credentials in your global machine vault,
    and automatically starts the heartbeat daemon in the background.
    """
    if password is None:
        password = typer.prompt("Password", hide_input=True)

    auth = AuthManager(backend_url=backend_url, runner_api_key=api_key)
    if not auth.backend_url:
        typer.echo(
            "✗ No backend URL configured. Pass --backend-url or set BUD_BACKEND_URL.", err=True
        )
        raise typer.Exit(code=2)
    if not auth.runner_api_key:
        typer.echo(
            "✗ RUNNER_API_KEY is not configured. Pass --api-key or export "
            "RUNNER_API_KEY (the shared secret from the Bud backend).",
            err=True,
        )
        raise typer.Exit(code=2)

    manager = RunnerManager(auth)

    typer.echo(f"Registering runner: {username}")

    try:
        result = manager.register(
            username=username,
            password=password,
            socket_port=socket_port,
        )

        typer.echo(f"✓ Registered successfully. Identity saved to ~/.bud/config.json")

        if not no_start:
            typer.echo(f"✓ Spawning heartbeat daemon in background for {username}...")
            pid = _start_daemon_background(
                username=username, backend_url=backend_url, interval=60, port=socket_port
            )
            if pid:
                typer.echo(f"  Daemon started (PID: {pid}). Monitoring: bud_{username}.log")

        typer.echo("\nProject Link (copy to your repo app.properties):")
        typer.echo("-" * 40)
        typer.echo(f"budRunnerAccount={username}")
        typer.echo(f"budBackend={auth.backend_url}")
        typer.echo(f"runnerSocketPort={socket_port}")
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
    port: int = typer.Option(
        53035,
        "--port",
        "-p",
        help="Socket listener port",
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

    manager = RunnerManager(auth)

    typer.echo(f"Starting Bud Runner Daemon for: {auth.runner_account}")
    typer.echo(f"  Backend: {auth.backend_url}")
    typer.echo(f"  Heartbeat Interval: {interval}s")
    typer.echo(f"  Socket Port: {port}")
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
        asyncio.run(manager.run_daemon(port=port, interval=interval, location=location))
    except KeyboardInterrupt:
        signal_handler(None, None)
    except Exception as e:
        typer.echo(f"✗ Daemon error: {e}", err=True)
        raise typer.Exit(code=1)


def _read_runner_package_version() -> str:
    """Resolve bud_runner package version from pyproject.toml or installed metadata."""
    try:
        cli_dir = Path(__file__).parent.parent
        toml_path = cli_dir / "pyproject.toml"
        if toml_path.exists():
            for line in toml_path.read_text().splitlines():
                if line.startswith("version = "):
                    return line.split("=")[1].strip().strip('"')
    except Exception:
        pass

    from importlib.metadata import version as _pkg_version

    try:
        return _pkg_version("bud_runner")
    except Exception:
        return "unknown"


@app.command()
def status(
    backend_url: Optional[str] = typer.Option(
        None,
        "--backend-url",
        "-b",
        help="Backend URL",
    ),
):
    """
    Show runner status and connectivity.
    """
    auth = AuthManager(backend_url=backend_url)

    typer.echo("Runner Status:")
    typer.echo(f"  Backend URL: {auth.backend_url or '(not set)'}")
    typer.echo(f"  Runner Account: {auth.runner_account or 'Not configured'}")
    typer.echo(f"  Token: {'Configured' if auth.token else 'Not configured'}")
    typer.echo(f"  Runner package: {_read_runner_package_version()}")

    if not auth.backend_url:
        typer.echo("  Backend Health: (skipped — no backend URL)")
        return

    client = BudAPIClient(auth)
    try:
        if client.health_check():
            typer.echo("  Backend Health: ✓ OK")
            try:
                backend_version = client.get_version()
                typer.echo(f"  Backend Version: {backend_version}")
            except Exception as e:
                typer.echo(f"  Backend Version: ✗ Error: {e}")
        else:
            typer.echo("  Backend Health: ✗ Unreachable")
    except Exception as e:
        typer.echo(f"  Backend Health: ✗ Error: {e}")


@app.command(name="version")
def version():
    """Show bud_runner version."""
    typer.echo(f"bud_runner version {_read_runner_package_version()}")


def main():
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
