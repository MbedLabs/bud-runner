"""
CLI entry point for bud_runner.

Provides commands for test execution, runner registration, and status monitoring.
"""

import json
import typer
from typing import Optional, List
from pathlib import Path
from bud_runner.auth import AuthManager
from bud_runner.api_client import BudAPIClient
from bud_runner.test_executor import TestExecutor
from bud_runner.runner_manager import RunnerManager

app = typer.Typer(help="Bud Test Automation Runner")

@app.command()
def register(
    username: str = typer.Option(..., "--username", "-u", help="Runner account username"),
    password: str = typer.Option(..., "--password", "-p", help="Runner account password", hide_input=True),
    backend_url: str = typer.Option("https://bud.embedlabs.de", "--backend-url", "-b", help="Bud backend URL"),
    socket_port: int = typer.Option(53035, "--socket-port", help="Local socket port for remote commands"),
):
    """Register this machine as a Bud test runner."""
    auth = AuthManager(backend_url=backend_url)
    client = BudAPIClient(auth)
    
    try:
        typer.echo(f"Registering runner '{username}' with {backend_url}...")
        token = client.register_runner(username, password, socket_port)
        auth.save_identity(username, token, socket_port)
        typer.echo("✓ Runner registered successfully.")
    except Exception as e:
        typer.echo(f"✗ Registration failed: {e}", err=True)
        raise typer.Exit(code=1)

@app.command()
def add_test_run(
    test_suite_name: str = typer.Option(..., "--test-suite-name", "-s", help="Display name for the test run"),
    test_case_list: str = typer.Option(..., "--test-case-list", "-t", help="Python module path to the test list"),
    product_composition_id: Optional[int] = typer.Option(None, "--product-composition-id", "-id", help="Product composition ID"),
    backend_url: Optional[str] = typer.Option(None, "--backend-url", "-b", help="Bud backend URL"),
    output_format: str = typer.Option("text", "--output-format", help="Output format (text or json)"),
):
    """Create a new test run record in Bud."""
    auth = AuthManager(backend_url=backend_url)
    client = BudAPIClient(auth)
    
    try:
        run_data = client.create_test_run(test_suite_name, test_case_list, product_composition_id)
        if output_format == "json":
            typer.echo(json.dumps(run_data))
        else:
            typer.echo(f"✓ Created test run ID: {run_data['id']}")
    except Exception as e:
        typer.echo(f"✗ Failed to create test run: {e}", err=True)
        raise typer.Exit(code=1)

@app.command()
def run_tests(
    test_case_list: str = typer.Option(..., "--test-case-list", "-t", help="Python module path to test list"),
    test_run_id: Optional[int] = typer.Option(None, "--test-run-id", help="Existing test run ID"),
    backend_url: Optional[str] = typer.Option(None, "--backend-url", "-b", help="Bud backend URL"),
    junit_report: Optional[str] = typer.Option(None, "--junit-report", help="Path to save JUnit XML report"),
    continue_on_error: bool = typer.Option(False, "--continue-on-error", help="Continue even if a test fails"),
    upload: bool = typer.Option(True, "--upload/--no-upload", help="Upload results to backend"),
):
    """Execute a list of tests and report results."""
    auth = AuthManager(backend_url=backend_url)
    executor = TestExecutor(auth if upload else None)
    
    try:
        results = executor.run_test_list(test_case_list, test_run_id=test_run_id, continue_on_error=continue_on_error)
        
        if junit_report:
            executor.save_junit_report(results, junit_report)
            typer.echo(f"✓ JUnit report saved to: {junit_report}")
            
        if not results.passed:
            raise typer.Exit(code=1)
    except Exception as e:
        typer.echo(f"✗ Execution error: {e}", err=True)
        raise typer.Exit(code=1)

@app.command()
def status():
    """Show runner status and connectivity."""
    auth = AuthManager()
    typer.echo(f"Runner Account: {auth.runner_account or 'Not configured'}")
    typer.echo(f"Backend URL:    {auth.backend_url}")
    
    client = BudAPIClient(auth)
    try:
        if client.health_check():
            typer.echo("Backend Status:  ✓ Connected")
        else:
            typer.echo("Backend Status:  ✗ Unreachable")
    except Exception as e:
        typer.echo(f"Backend Status:  ✗ Error: {e}")

@app.command()
def version():
    """Show bud_runner version."""
    from bud_runner import __version__
    typer.echo(f"bud_runner version {__version__}")

if __name__ == "__main__":
    app()
