"""AuthManager defaults, the status, register and list-tests commands, and artifact uploads, with the
identity, Bud's client, the runner manager and the HTTP session mocked."""

import contextlib
import json
import os
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests
from budtestlibrary import BudTestCase
from typer.testing import CliRunner

from bud_runner.api_client import BudAPIClient
from bud_runner.auth import AuthManager
from bud_runner.cli import _read_runner_package_version, app
from tests.config import AuthAndStatus as config
from tests.messages import AuthAndStatus as messages
from tests.parameters import AuthAndStatus as parameters


class AuthAndStatus(BudTestCase):
    """What a station reports, registers and lists, and how it uploads an artifact."""

    def folder(self) -> Path:
        """A new folder of this suite."""
        path = Path(os.environ[config.WORK_DIR_SETTING]) / config.FOLDER / uuid.uuid4().hex
        path.mkdir(parents=True)
        return path

    @contextlib.contextmanager
    def clean(self, vault: str | None = None):
        """Run the block in a new home and working folder, the vault holding the given text, and no
        BUD_ setting; yield the folder."""
        home = self.folder()
        if vault is not None:
            (home / config.VAULT).parent.mkdir(parents=True)
            (home / config.VAULT).write_text(vault)
        env = {k: v for k, v in os.environ.items() if not k.startswith(config.BUD_PREFIX)}
        env["HOME"] = str(home)
        before = os.getcwd()
        with patch.dict(os.environ, env, clear=True):
            os.chdir(home)
            try:
                yield home
            finally:
                os.chdir(before)

    def station(self, vault_entry=None) -> MagicMock:
        """A mocked AuthManager for registering runner-01 with the shared key."""
        auth = MagicMock()
        auth.backend_url = config.BACKEND
        auth.runner_api_key = parameters.API_KEY
        auth.vault.get_runner.return_value = vault_entry
        return auth

    def register(self, auth, *extra):
        """Invoke register for runner-01 with a mocked identity and runner manager."""
        with (
            patch("bud_runner.cli.AuthManager", return_value=auth),
            patch("bud_runner.cli.RunnerManager") as manager,
        ):
            manager.return_value.register.return_value = parameters.REGISTERED
            result = CliRunner().invoke(
                app,
                [
                    "register",
                    "--username",
                    parameters.STATION,
                    "--backend-url",
                    config.BACKEND,
                    "--api-key",
                    parameters.API_KEY,
                    *extra,
                    "--no-start",
                ],
            )
        return result, manager.return_value

    def client(self, token: str) -> BudAPIClient:
        """A client with a mocked identity."""
        auth = MagicMock()
        auth.backend_url = config.BACKEND
        auth.token = token
        auth.runner_api_key = None
        return BudAPIClient(auth)

    def artifact(self) -> Path:
        """A small log file to upload."""
        path = self.folder() / parameters.ARTIFACT_NAME
        path.write_text(parameters.ARTIFACT_TEXT, encoding="utf-8")
        return path

    def bud_the_default_backend_url_is_localhost(self):
        """Without settings the backend is http://localhost:8000."""
        with self.clean():
            backend = AuthManager().backend_url
        self.assertEqual(backend, config.DEFAULT, "the default backend is localhost")

    def bud_an_explicit_backend_url_overrides_the_default(self):
        """A given backend URL wins."""
        with self.clean():
            backend = AuthManager(backend_url=config.BACKEND).backend_url
        self.assertEqual(backend, config.BACKEND, "the given backend is used")

    def bud_status_reports_the_url_token_health_and_versions(self):
        """status prints the backend, the token state, the health and both versions."""
        client = MagicMock()
        client.health_check.return_value = True
        client.get_version.return_value = parameters.SERVER_VERSION
        auth = MagicMock(
            backend_url=config.DEFAULT,
            runner_account=parameters.RUNNER,
            token=parameters.SECRET_TOKEN,
        )
        with (
            patch("bud_runner.cli.AuthManager", return_value=auth),
            patch("bud_runner.cli.BudAPIClient", return_value=client),
            patch(
                "bud_runner.cli._read_runner_package_version",
                return_value=parameters.RUNNER_VERSION,
            ),
        ):
            result = CliRunner().invoke(app, ["status"])
        self.assertEqual(result.exit_code, parameters.OK, f"status exits 0: {result.output}")
        for text in (
            config.DEFAULT,
            messages.CONFIGURED,
            parameters.SERVER_VERSION,
            parameters.RUNNER_VERSION,
        ):
            self.assertIn(member=text, container=result.stdout, msg=f"status prints {text!r}")
        self.assertTrue(
            any(text in result.stdout for text in messages.HEALTHY),
            "status shows the backend healthy",
        )
        self.assertEqual(
            client.health_check.call_count, parameters.ONE, "the health is checked once"
        )
        self.assertEqual(client.get_version.call_count, parameters.ONE, "the version is read once")

    def bud_status_shows_unreachable_when_the_health_check_fails(self):
        """A failed health check shows Unreachable and reads no version."""
        client = MagicMock()
        client.health_check.return_value = False
        auth = MagicMock(backend_url=config.DEFAULT, runner_account=None, token=None)
        with (
            patch("bud_runner.cli.AuthManager", return_value=auth),
            patch("bud_runner.cli.BudAPIClient", return_value=client),
            patch(
                "bud_runner.cli._read_runner_package_version", return_value=parameters.PLAIN_VERSION
            ),
        ):
            result = CliRunner().invoke(app, ["status"])
        self.assertEqual(result.exit_code, parameters.OK, f"status exits 0: {result.output}")
        self.assertIn(
            member=messages.UNREACHABLE, container=result.stdout, msg="status says Unreachable"
        )
        self.assertEqual(client.get_version.call_count, parameters.NONE, "no version is read")

    def bud_the_runner_version_comes_from_the_package_metadata(self):
        """The runner's version is the installed package's version."""
        with patch(
            "bud_runner.cli.read_package_version", return_value=parameters.METADATA_VERSION
        ) as version:
            shown = _read_runner_package_version()
        self.assertEqual(shown, parameters.METADATA_VERSION, "the package version is shown")
        self.assertEqual(version.call_count, parameters.ONE, "it is read once")
        self.assertEqual(version.call_args.args, (), "it is read without arguments")

    def bud_the_registration_project_link_omits_the_socket_port(self):
        """register prints the project link without the socket port."""
        result, _ = self.register(self.station(), "--password", parameters.PASSWORD)
        self.assertEqual(result.exit_code, parameters.OK, f"register exits 0: {result.output}")
        for line in (messages.ACCOUNT_LINE, messages.BACKEND_LINE):
            self.assertIn(member=line, container=result.stdout, msg=f"the link holds {line!r}")
        self.assertNotIn(
            member=messages.SOCKET_LINE,
            container=result.stdout,
            msg="the link holds no socket port",
        )

    def bud_register_without_a_password_generates_one_and_prints_it_once(self):
        """register without --password generates one, registers with it and prints it."""
        with patch("bud_runner.cli.secrets.token_urlsafe", return_value=parameters.GENERATED):
            result, manager = self.register(self.station())
        self.assertEqual(result.exit_code, parameters.OK, f"register exits 0: {result.output}")
        self.assertEqual(
            manager.register.call_args.kwargs,
            {
                "username": parameters.STATION,
                "password": parameters.GENERATED,
                "socket_port": config.DEFAULT_PORT,
            },
            "the generated password registers the station",
        )
        for text in (messages.GENERATED, parameters.GENERATED):
            self.assertIn(member=text, container=result.stdout, msg=f"register prints {text!r}")

    def bud_register_refuses_an_existing_local_runner_without_re_register(self):
        """A station in the vault is refused with exit 2 without --re-register."""
        result, _ = self.register(self.station(parameters.VAULT_ENTRY))
        self.assertEqual(result.exit_code, parameters.REFUSED, "register exits 2")
        self.assertIn(
            member=messages.ALREADY_LOCAL,
            container=result.output,
            msg="register says already registered locally",
        )

    def bud_re_register_requires_the_existing_password(self):
        """--re-register without --password is refused with exit 2."""
        result, _ = self.register(self.station(parameters.VAULT_ENTRY), "--re-register")
        self.assertEqual(result.exit_code, parameters.REFUSED, "register exits 2")
        self.assertIn(
            member=messages.NEEDS_PASSWORD,
            container=result.output,
            msg="register asks for the existing password",
        )

    def bud_re_register_uses_the_given_password_and_refreshes_the_registration(self):
        """--re-register with --password registers again with that password."""
        result, manager = self.register(
            self.station(parameters.VAULT_ENTRY),
            "--password",
            parameters.KNOWN_PASSWORD,
            "--re-register",
        )
        self.assertEqual(result.exit_code, parameters.OK, f"register exits 0: {result.output}")
        self.assertEqual(
            manager.register.call_args.kwargs,
            {
                "username": parameters.STATION,
                "password": parameters.KNOWN_PASSWORD,
                "socket_port": config.DEFAULT_PORT,
            },
            "the given password registers the station again",
        )
        self.assertIn(
            member=messages.RE_REGISTERING,
            container=result.stdout,
            msg=f"register prints {messages.RE_REGISTERING!r}",
        )

    def bud_the_auth_manager_exposes_the_registered_socket_port(self):
        """A registered station's socket port comes from the vault."""
        with self.clean(parameters.SERVICE_VAULT):
            port = AuthManager(username=parameters.SERVICE_RUNNER).socket_port
        self.assertEqual(port, parameters.SERVICE_PORT, "the vault's port is used")

    def bud_list_tests_resolves_a_suite_without_running_it(self):
        """list-tests resolves the fixture list's two classes."""
        result = CliRunner().invoke(app, ["list-tests", "--test-case-list", config.FIXTURE_LIST])
        self.assertEqual(result.exit_code, parameters.OK, f"list-tests exits 0: {result.output}")
        for text in (messages.RESOLVED, config.FIRST_FIXTURE):
            self.assertIn(member=text, container=result.stdout, msg=f"list-tests prints {text!r}")

    def bud_list_tests_supports_json_output(self):
        """list-tests --output-format json names the list, the count and each test."""
        result = CliRunner().invoke(
            app, ["list-tests", "--test-case-list", config.FIXTURE_LIST, "--output-format", "json"]
        )
        self.assertEqual(result.exit_code, parameters.OK, f"list-tests exits 0: {result.output}")
        payload = json.loads(result.stdout)
        self.assertEqual(payload["test_case_list"], config.FIXTURE_LIST, "the list is named")
        self.assertEqual(payload["count"], parameters.FIXTURE_COUNT, "two tests are counted")
        self.assertEqual(
            payload["tests"][0]["path"], config.FIRST_FIXTURE, "the first test is named"
        )

    def bud_an_artifact_upload_uses_the_client_session(self):
        """upload_artifact posts through the client's session with the run, test case, timeout and auth."""
        client = self.client("user-token")
        path = self.artifact()
        with (
            patch.object(client._session, "post") as post,
            patch("bud_runner.api_client.requests.post") as bare_post,
        ):
            post.return_value = MagicMock(json=MagicMock(return_value=parameters.UPLOADED))
            answer = client.upload_artifact(
                str(path), run_id=parameters.RUN_ID, test_case=parameters.TEST_CASE
            )
        self.assertEqual(answer, parameters.UPLOADED, "the answer is returned")
        self.assertEqual(
            post.call_count, parameters.ONE, "the session posts once", abort_on_fail=True
        )
        self.assertEqual(bare_post.call_count, parameters.NONE, "requests.post is not used")
        kwargs = post.call_args.kwargs
        self.assertEqual(
            kwargs["data"],
            {"run_id": parameters.RUN_ID, "test_case": parameters.TEST_CASE},
            "the run and test case are sent",
        )
        self.assertEqual(kwargs["timeout"], config.UPLOAD_TIMEOUT, "the upload has a 120 s timeout")
        self.assertIn(
            member="Authorization", container=kwargs["headers"], msg="the upload is authenticated"
        )

    def bud_an_artifact_upload_is_real_multipart(self):
        """The prepared request is multipart/form-data with a boundary."""
        client = self.client("runner-token")
        path = self.artifact()
        response = requests.Response()
        response.status_code = parameters.CREATED
        response._content = parameters.CREATED_BODY
        response.headers["Content-Type"] = "application/json"
        with patch.object(client._session, "send", return_value=response) as send:
            client.upload_artifact(
                str(path), run_id=parameters.RUN_ID, test_case=parameters.TEST_CASE
            )
        content_type = send.call_args.args[0].headers["Content-Type"]
        self.assertTrue(
            content_type.startswith(messages.MULTIPART), f"the body is multipart: {content_type!r}"
        )
