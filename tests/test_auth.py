from unittest.mock import patch

from bud_runner.auth import AuthManager


def test_auth_manager_ignores_secret_tokens_in_project_properties(tmp_path, monkeypatch):
    vault_home = tmp_path / "home"
    repo_dir = tmp_path / "repo"
    vault_dir = vault_home / ".bud"
    repo_dir.mkdir()
    vault_dir.mkdir(parents=True)

    (vault_dir / "config.json").write_text(
        '{"ci-runner": {"token": "vault-token", "port": 53035, "backend": "https://vault-backend"}}'
    )
    (repo_dir / "app.properties").write_text(
        "\n".join(
            [
                "budRunnerAccount=ci-runner",
                "budBackend=https://project-backend",
                "budRunnerToken=project-token",
                "runnerApiKey=project-api-key",
                "budToken=project-user-token",
            ]
        )
    )

    monkeypatch.setenv("HOME", str(vault_home))
    monkeypatch.chdir(repo_dir)

    auth = AuthManager()

    assert auth.runner_account == "ci-runner"
    assert auth.backend_url == "https://vault-backend"
    assert auth.runner_token == "vault-token"
    assert auth.token == "vault-token"
    assert auth.runner_api_key is None


def test_environment_variables_override_project_properties(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "app.properties").write_text(
        "\n".join(
            [
                "budBackend=https://project-backend",
                "budRunnerAccount=project-runner",
            ]
        )
    )

    monkeypatch.chdir(repo_dir)
    monkeypatch.setenv("BUD_BACKEND_URL", "https://env-backend")
    monkeypatch.setenv("BUD_RUNNER_ACCOUNT", "env-runner")
    monkeypatch.setenv("BUD_RUNNER_TOKEN", "env-token")

    auth = AuthManager()

    assert auth.backend_url == "https://env-backend"
    assert auth.runner_account == "env-runner"
    assert auth.runner_token == "env-token"


def test_constructor_arguments_override_environment_and_project_properties(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "app.properties").write_text(
        "\n".join(
            [
                "budBackend=https://project-backend",
                "budRunnerAccount=project-runner",
            ]
        )
    )

    monkeypatch.chdir(repo_dir)
    monkeypatch.setenv("BUD_BACKEND_URL", "https://env-backend")
    monkeypatch.setenv("BUD_RUNNER_ACCOUNT", "env-runner")

    auth = AuthManager(
        backend_url="https://arg-backend",
        username="arg-runner",
        runner_account="arg-explicit-runner",
    )

    assert auth.backend_url == "https://arg-backend"
    assert auth.username == "arg-runner"
    assert auth.runner_account == "arg-explicit-runner"


def test_username_argument_sets_runner_account_and_loads_vault_identity(tmp_path, monkeypatch):
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

    assert auth.username == "service-runner"
    assert auth.runner_account == "service-runner"
    assert auth.runner_token == "vault-token"
    assert auth.token == "vault-token"
    assert auth.backend_url == "https://vault-backend"


def test_username_argument_loads_cached_user_token_from_vault(tmp_path, monkeypatch):
    vault_home = tmp_path / "home"
    repo_dir = tmp_path / "repo"
    vault_dir = vault_home / ".bud"
    repo_dir.mkdir()
    vault_dir.mkdir(parents=True)

    (vault_dir / "config.json").write_text(
        '{"_users": {"ci@example.com": {"token": "user-token", "backend": "https://vault-backend"}}}'
    )

    monkeypatch.setenv("HOME", str(vault_home))
    monkeypatch.chdir(repo_dir)

    auth = AuthManager(username="ci@example.com")

    assert auth.username == "ci@example.com"
    assert auth.token == "user-token"
    assert auth.backend_url == "https://vault-backend"


def test_save_to_properties_writes_only_allowed_project_keys(tmp_path, monkeypatch):
    properties_path = tmp_path / "app.properties"
    monkeypatch.delenv("HOME", raising=False)

    auth = AuthManager(
        username="last-user",
        backend_url="https://bud.example",
        runner_account="runner-01",
        runner_token="secret-token",
        runner_api_key="secret-api-key",
    )
    auth._location = "Lab A"
    auth._product_id = 42

    auth.save_to_properties(str(properties_path))

    content = properties_path.read_text()

    assert "budBackend=https://bud.example" in content
    assert "budRunnerAccount=runner-01" in content
    assert "location=Lab A" in content
    assert "productId=42" in content
    assert "lastUser=last-user" in content
    assert "runnerSocketPort" not in content
    assert "budRunnerToken" not in content
    assert "runnerApiKey" not in content
    assert "secret-token" not in content
    assert "secret-api-key" not in content


def test_invalid_properties_logs_warning_instead_of_printing(tmp_path, monkeypatch, caplog):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    bad_properties = repo_dir / "app.properties"
    bad_properties.write_text("budBackend=https://bud.example")

    monkeypatch.chdir(repo_dir)

    with (
        caplog.at_level("WARNING"),
        patch(
            "bud_runner.auth.configparser.ConfigParser.read_string",
            side_effect=ValueError("bad properties"),
        ),
    ):
        auth = AuthManager(properties_file=str(bad_properties))

    assert auth.backend_url == "http://localhost:8000"
    assert any("Error loading properties" in message for message in caplog.messages)
