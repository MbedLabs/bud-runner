"""AuthManager: where a station's identity, backend and tokens come from, and what it saves to
app.properties, with a throwaway home and project folder and every BUD_ setting cleared."""

import contextlib
import logging
import os
import uuid
from pathlib import Path
from unittest.mock import patch

from budtestlibrary import BudTestCase

from bud_runner.auth import AuthManager
from tests.config import Auth as config
from tests.parameters import Auth as parameters


class _Collector(logging.Handler):
    """Keeps the messages logged to it."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record):
        """Keep the message."""
        self.messages.append(record.getMessage())


class Auth(BudTestCase):
    """The precedence of arguments, environment, app.properties and the vault, and the saved keys."""

    def folders(self, vault: str | None = None, properties: str | None = None) -> tuple[Path, Path]:
        """A new home holding the vault text, and a new project folder holding the app.properties
        text."""
        root = Path(os.environ[config.WORK_DIR_SETTING]) / config.FOLDER / uuid.uuid4().hex
        home, repo = root / config.HOME, root / config.REPO
        repo.mkdir(parents=True)
        (home / config.VAULT).parent.mkdir(parents=True)
        if vault is not None:
            (home / config.VAULT).write_text(vault)
        if properties is not None:
            (repo / config.PROPERTIES).write_text(properties)
        return home, repo

    @contextlib.contextmanager
    def place(self, home: Path, repo: Path, extra: dict | None = None):
        """Run the block with HOME at home, repo as the working directory, no BUD_ setting but the
        extra ones, and restore all of it after."""
        env = {k: v for k, v in os.environ.items() if not k.startswith(config.BUD_PREFIX)}
        env["HOME"] = str(home)
        env.update(extra or {})
        before = os.getcwd()
        with patch.dict(os.environ, env, clear=True):
            os.chdir(repo)
            try:
                yield
            finally:
                os.chdir(before)

    def bud_secret_tokens_in_project_properties_are_ignored(self):
        """Tokens and keys in app.properties are ignored; the vault's identity is used."""
        home, repo = self.folders(parameters.RUNNER_VAULT, parameters.STRAY_PROPERTIES)
        with self.place(home, repo):
            auth = AuthManager()
        self.assertEqual(
            auth.runner_account, parameters.CI_RUNNER, "the account comes from app.properties"
        )
        self.assertEqual(
            auth.backend_url, parameters.VAULT_BACKEND, "the backend comes from the vault"
        )
        self.assertEqual(
            auth.runner_token, parameters.VAULT_TOKEN, "the station token comes from the vault"
        )
        self.assertEqual(auth.token, parameters.VAULT_TOKEN, "the token is the vault's")
        self.assertEqual(auth.runner_api_key, None, "no API key is taken from app.properties")

    def bud_environment_variables_override_project_properties(self):
        """BUD_ settings win over app.properties."""
        home, repo = self.folders(properties=parameters.PROJECT_PROPERTIES)
        with self.place(home, repo, parameters.ENV):
            auth = AuthManager()
        self.assertEqual(
            auth.backend_url, parameters.ENV_BACKEND, "the backend comes from the environment"
        )
        self.assertEqual(
            auth.runner_account, parameters.ENV_RUNNER, "the account comes from the environment"
        )
        self.assertEqual(
            auth.runner_token, parameters.ENV_TOKEN, "the token comes from the environment"
        )

    def bud_constructor_arguments_override_environment_and_project_properties(self):
        """Arguments win over BUD_ settings and app.properties."""
        home, repo = self.folders(properties=parameters.PROJECT_PROPERTIES)
        with self.place(home, repo, parameters.ENV):
            auth = AuthManager(
                backend_url=parameters.ARG_BACKEND,
                username=parameters.ARG_USERNAME,
                runner_account=parameters.ARG_RUNNER,
            )
        self.assertEqual(
            auth.backend_url, parameters.ARG_BACKEND, "the backend comes from the argument"
        )
        self.assertEqual(
            auth.username, parameters.ARG_USERNAME, "the username comes from the argument"
        )
        self.assertEqual(
            auth.runner_account, parameters.ARG_RUNNER, "the account comes from the argument"
        )

    def bud_a_username_argument_sets_the_account_and_loads_its_vault_identity(self):
        """A username names the station and loads its token and backend from the vault."""
        home, repo = self.folders(parameters.SERVICE_VAULT)
        with self.place(home, repo):
            auth = AuthManager(username=parameters.SERVICE_RUNNER)
        self.assertEqual(auth.username, parameters.SERVICE_RUNNER, "the username is kept")
        self.assertEqual(
            auth.runner_account, parameters.SERVICE_RUNNER, "the account is the username"
        )
        self.assertEqual(
            auth.runner_token, parameters.VAULT_TOKEN, "the station token comes from the vault"
        )
        self.assertEqual(auth.token, parameters.VAULT_TOKEN, "the token is the vault's")
        self.assertEqual(
            auth.backend_url, parameters.VAULT_BACKEND, "the backend comes from the vault"
        )

    def bud_a_username_argument_loads_the_cached_user_token(self):
        """A username of a cached user loads that user's token and backend from the vault."""
        home, repo = self.folders(parameters.USER_VAULT)
        with self.place(home, repo):
            auth = AuthManager(username=parameters.USER)
        self.assertEqual(auth.username, parameters.USER, "the username is kept")
        self.assertEqual(auth.token, parameters.USER_TOKEN, "the user's token is loaded")
        self.assertEqual(auth.backend_url, parameters.VAULT_BACKEND, "the user's backend is loaded")

    def bud_save_to_properties_writes_only_the_allowed_project_keys(self):
        """app.properties gets the project keys and never a token, key or socket port."""
        home, repo = self.folders()
        with self.place(home, repo):
            auth = AuthManager(**parameters.SAVE_ARGUMENTS)
            auth._location = parameters.LOCATION
            auth._product_id = parameters.PRODUCT_ID
            auth.save_to_properties(str(repo / config.PROPERTIES))
        content = (repo / config.PROPERTIES).read_text()
        for line in parameters.SAVED_LINES:
            self.assertIn(member=line, container=content, msg=f"{line!r} is saved")
        for text in parameters.UNSAVED:
            self.assertNotIn(member=text, container=content, msg=f"{text!r} is not saved")

    def bud_unreadable_properties_log_a_warning_and_keep_the_default_backend(self):
        """A properties file that fails to parse logs a warning and leaves the default backend."""
        home, repo = self.folders(properties=parameters.BAD_PROPERTIES)
        collector = _Collector()
        logger = logging.getLogger("bud_runner.auth")
        logger.addHandler(collector)
        try:
            with (
                self.place(home, repo),
                patch(config.READ_STRING, side_effect=ValueError(parameters.BAD_ERROR)),
            ):
                auth = AuthManager(properties_file=str(repo / config.PROPERTIES))
        finally:
            logger.removeHandler(collector)
        self.assertEqual(auth.backend_url, config.DEFAULT_BACKEND, "the default backend is kept")
        self.assertTrue(
            any(parameters.LOAD_WARNING in message for message in collector.messages),
            f"a warning says {parameters.LOAD_WARNING!r}: {collector.messages}",
        )
