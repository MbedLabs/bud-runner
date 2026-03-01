"""
CLI entry point for bud_runner.

Provides commands for test execution, runner registration, and test case synchronization.
"""

import typer
from typing import Optional, List
from pathlib import Path
from enum import Enum

from bud_runner.api_client import BudAPIClient
from bud_runner.openproject_client import OpenProjectClient
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
):
    """
    Create a new test run on bud.embedlabs.de.
    
    This command registers a new test run with the backend, which can then
    be executed by a runner.
    """
    auth = AuthManager(username=username, token=bud_token, backend_url=backend_url)
    client = BudAPIClient(auth)
    
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
        
        typer.echo(f"✓ Test run created: ID={result.get('id')}")
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
        
        # Upload results if requested
        if upload_results and backend_url:
            auth = AuthManager(backend_url=backend_url)
            client = BudAPIClient(auth)
            client.upload_results(results)
            typer.echo("✓ Results uploaded to backend")
        
        # Print summary
        passed = sum(1 for r in results if r.passed)
        failed = len(results) - passed
        
        typer.echo(f"\nSummary: {passed} passed, {failed} failed")
        
        if failed > 0:
            raise typer.Exit(code=1)
            
    except Exception as e:
        typer.echo(f"✗ Error running tests: {e}", err=True)
        raise typer.Exit(code=1)


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
):
    """
    Register this machine as a test runner with bud.embedlabs.de.
    
    Creates a runner account and stores credentials in app.properties.
    """
    if password is None:
        password = typer.prompt("Password", hide_input=True)
    
    auth = AuthManager(backend_url=backend_url)
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
        
    except Exception as e:
        typer.echo(f"✗ Registration failed: {e}", err=True)
        raise typer.Exit(code=1)


@app.command()
def sync_test_cases(
    project: str = typer.Option(
        ...,
        "--project",
        "-p",
        help="OpenProject project identifier",
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
        help="Test suite name (parent Work Package)",
    ),
    pm_url: Optional[str] = typer.Option(
        None,
        "--pm-url",
        help="OpenProject URL (default: from config)",
    ),
    pm_token: Optional[str] = typer.Option(
        None,
        "--pm-token",
        help="OpenProject API token",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be synced without making changes",
    ),
):
    """
    Sync test cases to OpenProject Work Packages.
    
    Creates Test Suite and Test Case Work Packages in OpenProject
    for requirement traceability.
    """
    client = OpenProjectClient(pm_url=pm_url, pm_token=pm_token)
    
    typer.echo(f"Syncing test cases to OpenProject")
    typer.echo(f"  Project: {project}")
    typer.echo(f"  Suite: {suite_name}")
    typer.echo(f"  Test list: {test_case_list}")
    
    if dry_run:
        typer.echo("\n[DRY RUN] Would sync the following:")
    
    try:
        # Import test list
        from bud_runner.test_executor import TestExecutor
        executor = TestExecutor()
        test_classes = executor.load_test_list(test_case_list)
        
        for test_class in test_classes:
            if dry_run:
                typer.echo(f"  - {test_class.__name__}")
            else:
                wp = client.sync_test_case(
                    project_id=project,
                    suite_name=suite_name,
                    test_class=test_class,
                )
                if wp:
                    typer.echo(f"✓ Synced: {test_class.__name__} -> WP-{wp.id}")
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
