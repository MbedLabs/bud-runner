"""Where AuthManager takes its credentials from: arguments, environment, app.properties and the
identity vault."""

import contextlib
import io
import json
import logging

import support
from budtestlibrary import BudTestCase

from bud_runner.auth import AuthManager


class _Records(logging.Handler):
    """A logging handler that keeps the messages it receives."""

    def __init__(self):
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record):
        """Keep the formatted message."""
        self.messages.append(record.getMessage())


class Auth(BudTestCase):
    """Precedence of arguments, environment, project properties and vault, and what
    save_to_properties writes."""

    def field(self, auth, name: str, expected, source: str) -> bool:
        """Record one AuthManager attribute against the value its source should give it."""
        actual = getattr(auth, name)
        return support.check(
            self,
            actual,
            expected,
            f"AuthManager.{name} is {expected!r}, taken from {source}",
            f"AuthManager.{name} is {actual!r}, not {expected!r} from {source}",
        )

    def bud_auth_manager_ignores_secret_tokens_in_project_properties(self):
        """Token keys in app.properties are ignored; the station token comes from the vault, no
        enrolment key is read."""
        case = support.Case("properties-secrets")
        case.save_vault(
            {
                "ci-runner": {
                    "token": "vault-token",
                    "port": 53035,
                    "backend": "https://vault-backend",
                }
            }
        )
        case.write(
            "app.properties",
            "budRunnerAccount=ci-runner\nbudBackend=https://project-backend\n"
            "budRunnerToken=project-token\nrunnerApiKey=project-api-key\n"
            "budToken=project-user-token\n",
        )
        with support.Isolated(case):
            auth = AuthManager()
        self.field(auth, "runner_account", "ci-runner", "budRunnerAccount in app.properties")
        self.field(
            auth,
            "backend_url",
            "https://vault-backend",
            "the vault identity of ci-runner, which wins over budBackend in app.properties",
        )
        self.field(
            auth,
            "runner_token",
            "vault-token",
            "the vault, not budRunnerToken in app.properties",
        )
        self.field(auth, "token", "vault-token", "the station token in the vault")
        self.field(
            auth,
            "runner_api_key",
            None,
            "nowhere: runnerApiKey in app.properties is not read",
        )

    def bud_environment_variables_override_project_properties(self):
        """BUD_BACKEND_URL, BUD_RUNNER_ACCOUNT and BUD_RUNNER_TOKEN win over app.properties."""
        case = support.Case("env-over-properties")
        case.write(
            "app.properties",
            "budBackend=https://project-backend\nbudRunnerAccount=project-runner\n",
        )
        with support.Isolated(
            case,
            {
                "BUD_BACKEND_URL": "https://env-backend",
                "BUD_RUNNER_ACCOUNT": "env-runner",
                "BUD_RUNNER_TOKEN": "env-token",
            },
        ):
            auth = AuthManager()
        self.field(
            auth, "backend_url", "https://env-backend", "BUD_BACKEND_URL over app.properties"
        )
        self.field(auth, "runner_account", "env-runner", "BUD_RUNNER_ACCOUNT over app.properties")
        self.field(auth, "runner_token", "env-token", "BUD_RUNNER_TOKEN")

    def bud_constructor_arguments_override_environment_and_project_properties(self):
        """Backend, username, account and token arguments win over the environment and
        app.properties."""
        case = support.Case("args-over-env")
        case.write(
            "app.properties",
            "budBackend=https://project-backend\nbudRunnerAccount=project-runner\n",
        )
        with support.Isolated(
            case,
            {
                "BUD_BACKEND_URL": "https://env-backend",
                "BUD_RUNNER_ACCOUNT": "env-runner",
                "BUD_TOKEN": "env-user-token",
            },
        ):
            auth = AuthManager(
                backend_url="https://arg-backend",
                username="arg-runner",
                runner_account="arg-explicit-runner",
                token="arg-token",
            )
        self.field(
            auth,
            "backend_url",
            "https://arg-backend",
            "the backend_url argument over BUD_BACKEND_URL",
        )
        self.field(auth, "username", "arg-runner", "the username argument")
        self.field(
            auth,
            "runner_account",
            "arg-explicit-runner",
            "the runner_account argument over BUD_RUNNER_ACCOUNT",
        )
        self.field(auth, "token", "arg-token", "the token argument over BUD_TOKEN")

    def bud_username_argument_sets_runner_account_and_loads_vault_identity(self):
        """username= names the account and loads its token, port and backend from the vault."""
        case = support.Case("username-vault")
        case.save_vault(
            {
                "service-runner": {
                    "token": "vault-token",
                    "port": 54001,
                    "backend": "https://vault-backend",
                }
            }
        )
        with support.Isolated(case):
            auth = AuthManager(username="service-runner")
        self.field(auth, "username", "service-runner", "the username argument")
        self.field(auth, "runner_account", "service-runner", "the username argument")
        self.field(auth, "runner_token", "vault-token", "the vault identity of service-runner")
        self.field(auth, "token", "vault-token", "the station token in the vault")
        self.field(
            auth, "backend_url", "https://vault-backend", "the vault identity of service-runner"
        )
        self.field(auth, "socket_port", 54001, "the vault identity of service-runner")

    def bud_username_argument_loads_cached_user_token_from_vault(self):
        """A user saved in the vault gives its token and backend."""
        case = support.Case("user-vault")
        case.save_vault(
            {
                "_users": {
                    "ci@example.com": {"token": "user-token", "backend": "https://vault-backend"}
                }
            }
        )
        with support.Isolated(case):
            auth = AuthManager(username="ci@example.com")
        self.field(auth, "username", "ci@example.com", "the username argument")
        self.field(auth, "token", "user-token", "the user ci@example.com cached in the vault")
        self.field(
            auth,
            "backend_url",
            "https://vault-backend",
            "the user ci@example.com cached in the vault",
        )

    def bud_save_to_properties_writes_only_allowed_project_keys(self):
        """save_to_properties writes backend, account, last user, location and product, and no
        secret."""
        case = support.Case("save-properties")
        case.write("app.properties", "location=Lab A\nproductId=42\n")
        with support.Isolated(case):
            auth = AuthManager(
                username="last-user",
                backend_url="https://bud.example.com",
                runner_account="station-01",
                runner_token="secret-token",
                runner_api_key="secret-api-key",
            )
            auth.save_to_properties(str(case.cwd / "saved.properties"))
        content = (case.cwd / "saved.properties").read_text(encoding="utf-8")
        for line in (
            "budBackend=https://bud.example.com",
            "budRunnerAccount=station-01",
            "location=Lab A",
            "productId=42",
            "lastUser=last-user",
        ):
            support.check_in(
                self,
                line,
                content,
                f"save_to_properties writes {line}",
                f"save_to_properties does not write {line}",
            )
        for absent in (
            "runnerSocketPort",
            "budRunnerToken",
            "runnerApiKey",
            "secret-token",
            "secret-api-key",
        ):
            support.check_not_in(
                self,
                absent,
                content,
                f"save_to_properties does not write {absent}",
                f"save_to_properties writes {absent} into the properties file",
            )
        count = json.dumps(case.vault()).count("secret-token")
        support.check(
            self,
            count,
            0,
            "save_to_properties writes the station token into the identity vault neither",
            f"the identity vault holds the station token {count} times after save_to_properties",
        )

    def bud_invalid_properties_logs_warning_instead_of_printing(self):
        """A malformed app.properties is logged as a warning, nothing is printed, and the default
        backend stays."""
        case = support.Case("bad-properties")
        bad = case.write(
            "app.properties", "budBackend=https://bud.example.com\nthis line is not a property\n"
        )
        records = _Records()
        logger = logging.getLogger("bud_runner.auth")
        logger.addHandler(records)
        printed = io.StringIO()
        try:
            with support.Isolated(case), contextlib.redirect_stdout(printed):
                auth = AuthManager(properties_file=str(bad))
        finally:
            logger.removeHandler(records)
        self.field(
            auth,
            "backend_url",
            "http://localhost:8000",
            "the default, since the malformed app.properties is not loaded",
        )
        support.says(
            self,
            "Error loading properties",
            " | ".join(records.messages),
            "the warnings bud_runner.auth logs for a malformed app.properties",
        )
        support.check(
            self,
            printed.getvalue(),
            "",
            "AuthManager prints nothing on stdout for a malformed app.properties",
            f"AuthManager prints {printed.getvalue()[:300]!r} for a malformed app.properties",
        )

    def bud_bud_token_argument_wins_over_the_environment(self):
        """bud_token= (what run-tests --bud-token passes) wins over BUD_TOKEN, as arguments come
        first."""
        case = support.Case("bud-token-precedence")
        with support.Isolated(case, {"BUD_TOKEN": "env-token"}):
            auth = AuthManager(bud_token="arg-token")
        self.field(
            auth,
            "token",
            "arg-token",
            "the bud_token argument (run-tests --bud-token), which wins over BUD_TOKEN as function "
            "arguments come first",
        )
