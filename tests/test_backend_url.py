"""The client refuses plain HTTP to a Bud backend that is not on this machine."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
from typer.testing import CliRunner

from bud_runner import api_client, cli
from bud_runner.api_client import BudAPIClient, InsecureBackendURLError, check_backend_url

REFUSED = "http://bud.example.com"
CUCUMBER_REPORT = Path(__file__).parent / "fixtures" / "cucumber" / "cucumber-js.json"
BUD_SETTINGS = (
    "BUD_BACKEND_URL",
    "BUD_TOKEN",
    "BUD_USERNAME",
    "BUD_RUNNER_ACCOUNT",
    "BUD_RUNNER_TOKEN",
    "BUD_RUNNER_API_KEY",
    "RUNNER_API_KEY",
)


def _auth(url):
    """Credentials for ``url`` in the shape BudAPIClient reads."""
    return SimpleNamespace(
        backend_url=url,
        token="station-session",
        runner_token="station-session",
        runner_api_key=None,
        runner_account="station-01",
    )


def _answer(request, **kwargs):
    """A 200 response to ``request`` with a version body."""
    response = requests.Response()
    response.status_code = 200
    response._content = b'{"version": "1.2.0"}'
    response.url = request.url
    response.request = request
    return response


@pytest.fixture
def transport(monkeypatch, tmp_path):
    """A home and working directory of the test's own without BUD_* settings, and the HTTP
    transport of requests replaced by a recorder that answers 200."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    for name in BUD_SETTINGS:
        monkeypatch.delenv(name, raising=False)
    send = Mock(side_effect=_answer)
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)
    return send


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8001",
        "http://127.0.0.1:8001",
        "http://[::1]:8001",
        "https://bud.example.com",
        "http://localhost:8000",
        "http://LocalHost:8001",
        "HTTP://127.0.0.1:8001",
        "http://127.255.255.254",
        "https://192.168.1.10:8001",
    ],
)
def test_loopback_http_and_https_urls_are_accepted(url, transport):
    client = BudAPIClient(_auth(url))
    assert client.health_check() is True
    request = transport.call_args.args[0]
    assert request.url.lower() == f"{url}/api/health".lower()


@pytest.mark.parametrize(
    "url",
    [
        "http://bud.example.com",
        "http://192.168.1.10:8001",
        "http://10.0.0.5",
        "http://BUD.EXAMPLE.COM",
        "HTTP://bud.example.com",
        " http://bud.example.com",
        "http://[fe80::1]:8001",
        "http://[::ffff:127.0.0.1]:8001",
        "http://0.0.0.0:8001",
        "http://localhost.example.com",
        "http://127.0.0.1.example.com",
        "http://[::1",
        "http://",
    ],
)
def test_plain_http_to_another_host_is_refused_before_any_request(url, transport, monkeypatch):
    session = Mock()
    monkeypatch.setattr(api_client.requests, "Session", session)
    with pytest.raises(InsecureBackendURLError) as refused:
        BudAPIClient(_auth(url))
    message = str(refused.value)
    assert url in message
    assert "https://" in message
    session.assert_not_called()
    transport.assert_not_called()


def test_the_refusal_is_a_value_error():
    with pytest.raises(ValueError):
        check_backend_url(REFUSED)


def test_the_default_backend_url_passes_the_check(transport):
    from bud_runner.auth import AuthManager

    check_backend_url(AuthManager.DEFAULT_BACKEND_URL)
    assert AuthManager().backend_url == "http://localhost:8000"
    BudAPIClient(AuthManager())


def _patched_frameworks(monkeypatch):
    """Robot, pytest, Behave and the Cucumber upload replaced by recorders."""
    import behave.__main__
    import robot

    from bud_runner import reporting

    started = Mock(return_value=0)
    monkeypatch.setattr(robot, "run_cli", started)
    monkeypatch.setattr(pytest, "main", started)
    monkeypatch.setattr(behave.__main__, "main", started)
    monkeypatch.setattr(reporting, "send_run", started)
    executor = Mock()
    executor.run_test_list.return_value = []
    monkeypatch.setattr(cli, "TestExecutor", Mock(return_value=executor))
    return started, executor


@pytest.mark.parametrize(
    "args",
    [
        ["add-test-run", "-t", "Suite.CASES", "-n", "Nightly", "--bud-token", "user-token"],
        ["run-tests", "-t", "Suite.CASES", "--format", "text"],
        ["claim-run"],
        ["register", "--username", "station-01", "--api-key", "enrolment-key", "--no-start"],
        ["daemon", "--username", "station-01"],
        ["run-robot", "tests/"],
        ["run-pytest", "tests/"],
        ["run-behave", "features/"],
        ["import-cucumber", "--report", str(CUCUMBER_REPORT)],
    ],
    ids=lambda args: args[0],
)
def test_every_command_refuses_plain_http_to_another_host(args, transport, monkeypatch):
    monkeypatch.setenv("BUD_RUNNER_TOKEN", "station-session")
    monkeypatch.setenv("BUD_RUNNER_ACCOUNT", "station-01")
    started, executor = _patched_frameworks(monkeypatch)
    result = CliRunner().invoke(cli.app, [*args, "--backend-url", REFUSED])
    assert result.exit_code == 2, result.output
    assert f"Refusing plain HTTP to {REFUSED}" in result.output
    assert "https://" in result.output
    transport.assert_not_called()
    started.assert_not_called()
    if args[0] == "run-tests":
        executor.run_test_list.assert_called_once()


def test_status_shows_the_refusal_as_the_backend_health(transport):
    result = CliRunner().invoke(cli.app, ["status", "--backend-url", REFUSED])
    assert result.exit_code == 0, result.output
    assert f"Backend URL: {REFUSED}" in result.output
    assert f"Backend Health: ✗ error: Refusing plain HTTP to {REFUSED}" in result.output
    transport.assert_not_called()


def test_status_reaches_a_loopback_backend_over_http(transport):
    result = CliRunner().invoke(cli.app, ["status", "--backend-url", "http://127.0.0.1:8001"])
    assert result.exit_code == 0, result.output
    assert "Backend Health: ✓ OK" in result.output
    assert transport.call_args_list[0].args[0].url == "http://127.0.0.1:8001/api/health"


def test_the_pytest_plugin_reports_the_refusal_and_keeps_the_exit_code(
    pytester, transport, capsys, monkeypatch
):
    monkeypatch.chdir(pytester.path)
    pytester.makepyfile(test_one="def test_one():\n    assert 1 == 1\n")
    rec = pytester.inline_run("-p", "bud_runner.pytest_plugin", f"--bud-backend-url={REFUSED}")
    assert rec.ret == 0
    err = capsys.readouterr().err
    assert f"Could not report the pytest run to Bud: Refusing plain HTTP to {REFUSED}" in err
    transport.assert_not_called()


def test_the_robot_listener_reports_the_refusal(transport, capsys):
    from bud_runner.robot_listener import BudListener

    BudListener(backend=REFUSED).close()
    err = capsys.readouterr().err
    assert f"Could not report the Robot run to Bud: Refusing plain HTTP to {REFUSED}" in err
    transport.assert_not_called()
