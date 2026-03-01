"""Tests for AuthManager defaults and CLI status command."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from bud_runner.api_client import BudAPIClient
from bud_runner.auth import AuthManager
from bud_runner.cli import _read_runner_package_version, app


def test_default_backend_url_is_localhost():
    auth = AuthManager()
    assert auth.backend_url == "http://localhost:8000"


def test_explicit_backend_url_overrides_default():
    auth = AuthManager(backend_url="https://bud.example.com")
    assert auth.backend_url == "https://bud.example.com"


def test_status_reports_url_token_health_and_version():
    runner = CliRunner()
    mock_client = MagicMock()
    mock_client.health_check.return_value = True
    mock_client.get_version.return_value = "1.2.3"

    with (
        patch("bud_runner.cli.AuthManager") as mock_auth_cls,
        patch("bud_runner.cli.BudAPIClient", return_value=mock_client),
        patch("bud_runner.cli._read_runner_package_version", return_value="0.4.6-test"),
    ):
        mock_auth = MagicMock()
        mock_auth.backend_url = "http://localhost:8000"
        mock_auth.runner_account = "runner-a"
        mock_auth.token = "secret-token"
        mock_auth_cls.return_value = mock_auth

        result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "http://localhost:8000" in result.stdout
    assert "Configured" in result.stdout
    assert "Connected" in result.stdout or "OK" in result.stdout
    assert "1.2.3" in result.stdout
    assert "0.4.6-test" in result.stdout
    mock_client.health_check.assert_called_once()
    mock_client.get_version.assert_called_once()


def test_status_shows_unreachable_when_health_fails():
    runner = CliRunner()
    mock_client = MagicMock()
    mock_client.health_check.return_value = False

    with (
        patch("bud_runner.cli.AuthManager") as mock_auth_cls,
        patch("bud_runner.cli.BudAPIClient", return_value=mock_client),
        patch("bud_runner.cli._read_runner_package_version", return_value="0.4.6"),
    ):
        mock_auth = MagicMock()
        mock_auth.backend_url = "http://localhost:8000"
        mock_auth.runner_account = None
        mock_auth.token = None
        mock_auth_cls.return_value = mock_auth

        result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "Unreachable" in result.stdout
    mock_client.get_version.assert_not_called()


def test_status_json_reports_backend_and_daemon_fields():
    runner = CliRunner()
    mock_client = MagicMock()
    mock_client.health_check.return_value = True
    mock_client.get_version.return_value = "1.2.3"
    mock_client.get_runner_status.return_value = {"runners": [{"account": "runner-a"}]}

    with (
        patch("bud_runner.cli.AuthManager") as mock_auth_cls,
        patch("bud_runner.cli.BudAPIClient", return_value=mock_client),
        patch("bud_runner.cli._read_runner_package_version", return_value="0.4.7"),
    ):
        mock_auth = MagicMock()
        mock_auth.backend_url = "http://localhost:8000"
        mock_auth.runner_account = "runner-a"
        mock_auth.token = "secret-token"
        mock_auth.socket_port = 54001
        mock_auth_cls.return_value = mock_auth

        result = runner.invoke(app, ["status", "--output-format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["backend_url"] == "http://localhost:8000"
    assert payload["runner_account"] == "runner-a"
    assert payload["token_configured"] is True
    assert payload["runner_package_version"] == "0.4.7"
    assert payload["socket_port"] == 54001
    assert payload["backend_health"] == "ok"
    assert payload["backend_version"] == "1.2.3"
    assert payload["daemon"]["backend_runner_status"] == {"runners": [{"account": "runner-a"}]}


def test_read_runner_package_version_uses_importlib_metadata_distribution_name():
    with patch("bud_runner.cli.read_package_version", return_value="9.9.9") as mock_version:
        assert _read_runner_package_version() == "9.9.9"

    mock_version.assert_called_once_with()


def test_register_project_link_omits_runner_socket_port():
    runner = CliRunner()

    with (
        patch("bud_runner.cli.AuthManager") as mock_auth_cls,
        patch("bud_runner.cli.RunnerManager") as mock_manager_cls,
    ):
        mock_auth = MagicMock()
        mock_auth.backend_url = "https://bud.example.com"
        mock_auth.runner_api_key = "shared-secret"
        mock_auth.vault.get_runner.return_value = None
        mock_auth_cls.return_value = mock_auth

        mock_manager = MagicMock()
        mock_manager.register.return_value = {"id": 1}
        mock_manager_cls.return_value = mock_manager

        result = runner.invoke(
            app,
            [
                "register",
                "--username",
                "runner-01",
                "--password",
                "super-secret",
                "--backend-url",
                "https://bud.example.com",
                "--api-key",
                "shared-secret",
                "--no-start",
            ],
        )

    assert result.exit_code == 0
    assert "budRunnerAccount=runner-01" in result.stdout
    assert "budBackend=https://bud.example.com" in result.stdout
    assert "runnerSocketPort=" not in result.stdout


def test_register_without_password_generates_one_and_prints_once():
    runner = CliRunner()

    with (
        patch("bud_runner.cli.AuthManager") as mock_auth_cls,
        patch("bud_runner.cli.RunnerManager") as mock_manager_cls,
        patch("bud_runner.cli.secrets.token_urlsafe", return_value="generated-pass-123"),
    ):
        mock_auth = MagicMock()
        mock_auth.backend_url = "https://bud.example.com"
        mock_auth.runner_api_key = "shared-secret"
        mock_auth.vault.get_runner.return_value = None
        mock_auth_cls.return_value = mock_auth

        mock_manager = MagicMock()
        mock_manager.register.return_value = {"id": 1}
        mock_manager_cls.return_value = mock_manager

        result = runner.invoke(
            app,
            [
                "register",
                "--username",
                "runner-01",
                "--backend-url",
                "https://bud.example.com",
                "--api-key",
                "shared-secret",
                "--no-start",
            ],
        )

    assert result.exit_code == 0
    mock_manager.register.assert_called_once_with(
        username="runner-01",
        password="generated-pass-123",
        socket_port=53035,
    )
    assert "Generated password for this runner account" in result.stdout
    assert "generated-pass-123" in result.stdout


def test_register_refuses_existing_local_runner_without_re_register():
    runner = CliRunner()

    with patch("bud_runner.cli.AuthManager") as mock_auth_cls:
        mock_auth = MagicMock()
        mock_auth.backend_url = "https://bud.example.com"
        mock_auth.runner_api_key = "shared-secret"
        mock_auth.vault.get_runner.return_value = {"token": "runner-token", "port": 53035}
        mock_auth_cls.return_value = mock_auth

        result = runner.invoke(
            app,
            [
                "register",
                "--username",
                "runner-01",
                "--backend-url",
                "https://bud.example.com",
                "--api-key",
                "shared-secret",
                "--no-start",
            ],
        )

    assert result.exit_code == 2
    assert "already registered locally" in result.output


def test_re_register_requires_existing_password():
    runner = CliRunner()

    with patch("bud_runner.cli.AuthManager") as mock_auth_cls:
        mock_auth = MagicMock()
        mock_auth.backend_url = "https://bud.example.com"
        mock_auth.runner_api_key = "shared-secret"
        mock_auth.vault.get_runner.return_value = {"token": "runner-token", "port": 53035}
        mock_auth_cls.return_value = mock_auth

        result = runner.invoke(
            app,
            [
                "register",
                "--username",
                "runner-01",
                "--backend-url",
                "https://bud.example.com",
                "--api-key",
                "shared-secret",
                "--re-register",
                "--no-start",
            ],
        )

    assert result.exit_code == 2
    assert "Re-registration requires the existing runner password" in result.output


def test_re_register_uses_provided_password_and_refreshes_registration():
    runner = CliRunner()

    with (
        patch("bud_runner.cli.AuthManager") as mock_auth_cls,
        patch("bud_runner.cli.RunnerManager") as mock_manager_cls,
    ):
        mock_auth = MagicMock()
        mock_auth.backend_url = "https://bud.example.com"
        mock_auth.runner_api_key = "shared-secret"
        mock_auth.vault.get_runner.return_value = {"token": "runner-token", "port": 53035}
        mock_auth_cls.return_value = mock_auth

        mock_manager = MagicMock()
        mock_manager.register.return_value = {"id": 1}
        mock_manager_cls.return_value = mock_manager

        result = runner.invoke(
            app,
            [
                "register",
                "--username",
                "runner-01",
                "--password",
                "known-password-123",
                "--backend-url",
                "https://bud.example.com",
                "--api-key",
                "shared-secret",
                "--re-register",
                "--no-start",
            ],
        )

    assert result.exit_code == 0
    mock_manager.register.assert_called_once_with(
        username="runner-01",
        password="known-password-123",
        socket_port=53035,
    )
    assert "Re-registering runner: runner-01" in result.stdout


def test_auth_manager_exposes_socket_port_from_registered_identity(tmp_path, monkeypatch):
    vault_home = tmp_path / "home"
    repo_dir = tmp_path / "repo"
    vault_dir = vault_home / ".bud"
    repo_dir.mkdir()
    vault_dir.mkdir(parents=True)

    (vault_dir / "config.json").write_text(
        '{"service-runner": {"token": "vault-token", "port": 54001, "backend": "https://vault-backend"}}'
    )

    monkeypatch.setenv("HOME", str(vault_home))
    monkeypatch.chdir(repo_dir)

    auth = AuthManager(username="service-runner")

    assert auth.socket_port == 54001


def test_list_tests_resolves_suite_without_running_it():
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "list-tests",
            "--test-case-list",
            "tests.fixtures.mock_tests.MOCK_TEST_LIST",
        ],
    )

    assert result.exit_code == 0
    assert "Resolved 2 test class(es)" in result.stdout
    assert "tests.fixtures.mock_tests.FastPassTest" in result.stdout


def test_list_tests_supports_json_output():
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "list-tests",
            "--test-case-list",
            "tests.fixtures.mock_tests.MOCK_TEST_LIST",
            "--output-format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["test_case_list"] == "tests.fixtures.mock_tests.MOCK_TEST_LIST"
    assert payload["count"] == 2
    assert payload["tests"][0]["path"] == "tests.fixtures.mock_tests.FastPassTest"


def test_upload_artifact_uses_api_client_session_for_retries(tmp_path):
    auth = MagicMock()
    auth.backend_url = "https://bud.example.com"
    auth.token = "user-token"
    auth.runner_api_key = None
    client = BudAPIClient(auth)

    artifact_path = tmp_path / "trace.log"
    artifact_path.write_text("trace-data", encoding="utf-8")

    with (
        patch.object(client._session, "post") as mock_post,
        patch("bud_runner.api_client.requests.post") as mock_requests_post,
    ):
        mock_response = MagicMock()
        mock_response.json.return_value = {"id": 7, "url": "https://bud.example.com/a/7"}
        mock_post.return_value = mock_response

        payload = client.upload_artifact(str(artifact_path), run_id=12, test_case="VoltageTest")

    assert payload == {"id": 7, "url": "https://bud.example.com/a/7"}
    mock_post.assert_called_once()
    mock_requests_post.assert_not_called()
    kwargs = mock_post.call_args.kwargs
    assert kwargs["data"] == {"run_id": 12, "test_case": "VoltageTest"}
    assert kwargs["timeout"] == 120
    assert "Authorization" in kwargs["headers"]
