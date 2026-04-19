"""
CLI entry point for bud_runner.

Provides commands for test execution, runner registration, and test case synchronization.
"""

import json
import typer
from typing import Optional, List
from pathlib import Path
from enum import Enum

from bud_runner.api_client import BudAPIClient
from bud_runner.bloom_client import BloomClient
from bud_runner.runner_manager import RunnerManager
from bud_runner.test_executor import TestExecutor
from bud_runner.junit_reporter import JUnitReporter
from bud_runner.auth import AuthManager

app = typer.Typer(
    name="bud_runner",
    help="CLI tool for test execution and CI/CD integration with bud.embedlabs.de",
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
        help="Test case list module path (e.g., Bud_Test_Suite.HIL_TEST_CASES)",
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
    Create a new test run on bud.embedlabs.de.
    
    This command registers a new test run with the backend, which can then
    be executed by a runner.
    """
    auth = AuthManager(username=username, token=bud_token, backend_url=backend_url)
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
            typer.echo(f"✓ Test run created: ID={result.get('id')} ProductID={result.get('product_id')}")
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
        help="Test case list module path (e.g., Bud_Test_Suite.HIL_TEST_CASES)",
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
):
    """
    Execute tests from a test case list.
    
    Runs all tests in the specified test case list and generates a JUnit XML
    report for CI/CD integration.
    """
    executor = TestExecutor()
    reporter = JUnitReporter()
    
    typer.echo(f"Running tests from: {test_case_list}")
    
    try:
        # Import and run tests
        results = executor.run_test_list(
            test_case_list=test_case_list,
            continue_on_error=continue_on_error,
        )
        
        # Generate report
        if format == OutputFormat.junit:
            xml_content = reporter.generate(results)
            output.write_text(xml_content)
            typer.echo(f"✓ JUnit report written to: {output}")
        
        # Upload results if requested. Requires a backend URL AND an auth token;
        # fail loudly rather than silently skipping the upload.
        if upload_results:
            auth = AuthManager(backend_url=backend_url, token=bud_token)
            if not auth.token:
                typer.echo(
                    "⚠ Skipping result upload: no BUD_TOKEN (env) or --bud-token provided.",
                    err=True,
                )
            else:
                client = BudAPIClient(auth)
                
                # If we don't have a product_id yet, try to get it from the run if we have a run_id
                final_product_id = None
                if test_run_id:
                    try:
                        run_info = client.get_test_run(test_run_id)
                        final_product_id = run_info.get("product_id")
                    except Exception:
                        pass

                ok = client.upload_results(results, test_run_id=test_run_id, product_id=final_product_id)
                if ok:
                    suffix = f" (test_run_id={test_run_id})" if test_run_id else ""
                    typer.echo(f"✓ Results uploaded to backend{suffix}")
                    
                    # FINAL STATUS UPDATE: Use flattened results for accurate method counts
                    if test_run_id:
                        from bud_runner.api_client import _flatten_results
                        flat_results = _flatten_results(results)
                        
                        passed_count = sum(1 for r in flat_results if r.get("passed"))
                        total_count = len(flat_results)
                        
                        final_status = "Completed" if passed_count == total_count else "Failed"
                        client.update_test_run(
                            run_id=test_run_id,
                            status=final_status,
                            total_tests=total_count,
                            passed_tests=passed_count,
                            failed_tests=total_count - passed_count,
                            product_id=final_product_id
                        )
                        typer.echo(f"✓ Test run {test_run_id} marked as {final_status} ({passed_count}/{total_count} passed)")
                else:
                    typer.echo("✗ Result upload failed", err=True)
                    raise typer.Exit(code=1)
        
        # Print summary
        passed = sum(1 for r in results if r.passed)
        failed = len(results) - passed
        
        typer.echo(f"\nSummary: {passed} passed, {failed} failed")
        
        if failed > 0:
            raise typer.Exit(code=1)
            
    except Exception as e:
        typer.echo(f"✗ Error running tests: {e}", err=True)
        raise typer.Exit(code=1)


import subprocess
import sys
import os

def _start_daemon_background(backend_url: Optional[str], interval: int, port: int):
    """Helper to spawn the daemon in the background as a detached process."""
    cmd = [sys.executable, "-m", "bud_runner", "daemon", "--interval", str(interval), "--port", str(port)]
    if backend_url:
        cmd.extend(["--backend-url", backend_url])
    
    # Ensure logs are persistent
    log_file = open("runner_daemon.log", "a")
    
    # Capture current environment and ensure PYTHONPATH includes current directories
    env = os.environ.copy()
    current_pythonpath = env.get("PYTHONPATH", "")
    # Add bud-runner and bud-test-library to path if not already there
    workspace_root = os.getcwd()
    paths_to_add = [
        os.path.join(workspace_root, "bud-runner"),
        os.path.join(workspace_root, "bud-test-library")
    ]
    for p in paths_to_add:
        if p not in current_pythonpath:
            current_pythonpath = f"{p}:{current_pythonpath}" if current_pythonpath else p
    env["PYTHONPATH"] = current_pythonpath

    try:
        # Spawn background process detached from the current terminal session
        process = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
            env=env
        )
        # Record PID for management
        with open("runner_daemon.pid", "w") as f:
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
             "Falls back to RUNNER_API_KEY env var or app.properties 'runnerApiKey'.",
    ),
    no_start: bool = typer.Option(
        False,
        "--no-start",
        help="Do NOT start the heartbeat daemon automatically after registration",
    ),
):
    """
    Register this machine as a test runner with bud.embedlabs.de.

    Creates a runner account, stores credentials in app.properties,
    and automatically starts the heartbeat daemon in the background.
    """
    if password is None:
        password = typer.prompt("Password", hide_input=True)

    auth = AuthManager(backend_url=backend_url, runner_api_key=api_key)
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
        
        typer.echo(f"✓ Runner registered successfully")
        typer.echo(f"  Account: {result.get('account')}")
        typer.echo(f"  Token saved to: app.properties")

        if not no_start:
            typer.echo("✓ Spawning heartbeat daemon in background...")
            pid = _start_daemon_background(backend_url=backend_url, interval=60, port=socket_port)
            if pid:
                typer.echo(f"  Daemon started (PID: {pid}). Monitoring: runner_daemon.log")
        
    except Exception as e:
        typer.echo(f"✗ Registration failed: {e}", err=True)
        raise typer.Exit(code=1)


@app.command()
def daemon(
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
):
    """
    Start the runner daemon (heartbeat + socket listener).
    
    This process must remain running for the runner to appear 'Online' 
    and receive remote commands.
    """
    import signal
    import sys

    auth = AuthManager(backend_url=backend_url)
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

    def signal_handler(sig, frame):
        typer.echo("\nStopping daemon...")
        manager.stop_heartbeat()
        manager.stop_listener()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start heartbeat in background thread
    manager.start_heartbeat(interval=interval)
    
    # Start socket listener in foreground (blocks)
    try:
        manager.start_listener(port=port)
    except KeyboardInterrupt:
        signal_handler(None, None)
    except Exception as e:
        typer.echo(f"✗ Daemon error: {e}", err=True)
        manager.stop_heartbeat()
        raise typer.Exit(code=1)


@app.command()
def sync_test_cases(
    project: str = typer.Option(
        ...,
        "--project",
        "-p",
        help="Bloom project prefix or numeric ID",
    ),
    test_case_list: str = typer.Option(
        ...,
        "--test-case-list",
        "-t",
        help="Test case list module path",
    ),
    suite_name: str = typer.Option(
        ...,
        "--suite-name",
        "-s",
        help="Suite/scope name in Bloom (groups test cases for traceability)",
    ),
    bloom_url: Optional[str] = typer.Option(
        None,
        "--bloom-url",
        help="Bloom ALM URL (default: from config)",
    ),
    bloom_token: Optional[str] = typer.Option(
        None,
        "--bloom-token",
        help="Bloom ALM JWT token",
    ),
    bloom_email: Optional[str] = typer.Option(
        None,
        "--bloom-email",
        help="Bloom ALM login email (alternative to --bloom-token)",
    ),
    bloom_password: Optional[str] = typer.Option(
        None,
        "--bloom-password",
        help="Bloom ALM login password (used with --bloom-email)",
        hide_input=True,
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be synced without making changes",
    ),
):
    """
    Sync test cases to Bloom ALM traceability model.

    Creates/updates test cases, keeps them in a Bloom suite,
    and ensures a campaign scope exists for Bud linkage.
    """
    client = BloomClient(
        bloom_url=bloom_url,
        bloom_token=bloom_token,
        bloom_email=bloom_email,
        bloom_password=bloom_password,
    )
    
    typer.echo(f"Syncing test cases to Bloom ALM")
    typer.echo(f"  Project: {project}")
    typer.echo(f"  Campaign: {suite_name}")
    typer.echo(f"  Test list: {test_case_list}")
    
    if dry_run:
        typer.echo("\n[DRY RUN] Would sync the following:")
    
    try:
        from bud_runner.test_executor import TestExecutor
        executor = TestExecutor()
        test_classes = executor.load_test_list(test_case_list)
        
        for test_class in test_classes:
            if dry_run:
                typer.echo(f"  - {test_class.__name__}")
            else:
                tc = client.sync_test_case(
                    project_identifier=project,
                    campaign_name=suite_name,
                    test_class=test_class,
                )
                if tc:
                    typer.echo(f"✓ Synced: {test_class.__name__} -> {tc.tc_id}")
                else:
                    typer.echo(f"✗ Failed: {test_class.__name__}")
        
        if not dry_run:
            typer.echo(f"\n✓ Synced {len(test_classes)} test cases")
            
    except Exception as e:
        typer.echo(f"✗ Sync failed: {e}", err=True)
        raise typer.Exit(code=1)


@app.command()
def version():
    """Show bud_runner version."""
    from bud_runner import __version__
    typer.echo(f"bud_runner version {__version__}")


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
    typer.echo(f"  Backend URL: {auth.backend_url}")
    typer.echo(f"  Runner Account: {auth.runner_account or 'Not configured'}")
    typer.echo(f"  Token: {'Configured' if auth.token else 'Not configured'}")
    
    # Check connectivity
    client = BudAPIClient(auth)
    try:
        if client.health_check():
            typer.echo(f"  Backend Status: ✓ Connected")
        else:
            typer.echo(f"  Backend Status: ✗ Unreachable")
    except Exception as e:
        typer.echo(f"  Backend Status: ✗ Error: {e}")


def main():
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
