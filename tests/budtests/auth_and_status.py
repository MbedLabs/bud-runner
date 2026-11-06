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
from tests.budtests.config import AuthAndStatus as c
from tests.budtests.messages import AuthAndStatus as m
from tests.budtests.parameters import AuthAndStatus as p


class AuthAndStatus(BudTestCase):
    """What a station reports, registers and lists, and how it uploads an artifact."""

    def folder(self) -> Path:
        """A new folder of this suite."""
        path = Path(os.environ[c.WORK_DIR_SETTING]) / c.FOLDER / uuid.uuid4().hex
        path.mkdir(parents=True)
        return path

    @contextlib.contextmanager
    def clean(self, vault: str | None = None):
        """Run the block in a new home and working folder, the vault holding the given text, and no
        BUD_ setting; yield the folder."""
        home = self.folder()
        if vault is not None:
            (home / c.VAULT).parent.mkdir(parents=True)
            (home / c.VAULT).write_text(vault)
        env = {k: v for k, v in os.environ.items() if not k.startswith(c.BUD_PREFIX)}
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
        auth.backend_url = c.BACKEND
        auth.runner_api_key = p.API_KEY
        auth.vault.get_runner.return_value = vault_entry
        return auth

    def register(self, auth, *extra):
        """Invoke register for runner-01 with a mocked identity and runner manager."""
        with patch("bud_runner.cli.AuthManager", return_value=auth), patch("bud_runner.cli.RunnerManager") as manager:
            manager.return_value.register.return_value = p.REGISTERED
            result = CliRunner().invoke(
                app,
                ["register", "--username", p.STATION, "--backend-url", c.BACKEND, "--api-key", p.API_KEY, *extra, "--no-start"],
            )
        return result, manager.return_value

    def client(self, token: str) -> BudAPIClient:
        """A client with a mocked identity."""
        auth = MagicMock()
        auth.backend_url = c.BACKEND
        auth.token = token
        auth.runner_api_key = None
        return BudAPIClient(auth)

    def artifact(self) -> Path:
        """A small log file to upload."""
        path = self.folder() / p.ARTIFACT_NAME
        path.write_text(p.ARTIFACT_TEXT, encoding="utf-8")
        return path

    def bud_the_default_backend_url_is_localhost(self):
        """Without settings the backend is http://localhost:8000."""
        with self.clean():
            backend = AuthManager().backend_url
        self.assertEqual(backend, c.DEFAULT, "the default backend is localhost")

    def bud_an_explicit_backend_url_overrides_the_default(self):
        """A given backend URL wins."""
        with self.clean():
            backend = AuthManager(backend_url=c.BACKEND).backend_url
        self.assertEqual(backend, c.BACKEND, "the given backend is used")

    def bud_status_reports_the_url_token_health_and_versions(self):
        """status prints the backend, the token state, the health and both versions."""
        client = MagicMock()
        client.health_check.return_value = True
        client.get_version.return_value = p.SERVER_VERSION
        auth = MagicMock(backend_url=c.DEFAULT, runner_account=p.RUNNER, token=p.SECRET_TOKEN)
        with (
            patch("bud_runner.cli.AuthManager", return_value=auth),
            patch("bud_runner.cli.BudAPIClient", return_value=client),
            patch("bud_runner.cli._read_runner_package_version", return_value=p.RUNNER_VERSION),
        ):
            result = CliRunner().invoke(app, ["status"])
        self.assertEqual(result.exit_code, p.OK, f"status exits 0: {result.output}")
        for text in (c.DEFAULT, m.CONFIGURED, p.SERVER_VERSION, p.RUNNER_VERSION):
            self.assertIn(member=text, container=result.stdout, msg=f"status prints {text!r}")
        self.assertTrue(any(text in result.stdout for text in m.HEALTHY), "status shows the backend healthy")
        self.assertEqual(client.health_check.call_count, p.ONE, "the health is checked once")
        self.assertEqual(client.get_version.call_count, p.ONE, "the version is read once")

    def bud_status_shows_unreachable_when_the_health_check_fails(self):
        """A failed health check shows Unreachable and reads no version."""
        client = MagicMock()
        client.health_check.return_value = False
        auth = MagicMock(backend_url=c.DEFAULT, runner_account=None, token=None)
        with (
            patch("bud_runner.cli.AuthManager", return_value=auth),
            patch("bud_runner.cli.BudAPIClient", return_value=client),
            patch("bud_runner.cli._read_runner_package_version", return_value=p.PLAIN_VERSION),
        ):
            result = CliRunner().invoke(app, ["status"])
        self.assertEqual(result.exit_code, p.OK, f"status exits 0: {result.output}")
        self.assertIn(member=m.UNREACHABLE, container=result.stdout, msg="status says Unreachable")
        self.assertEqual(client.get_version.call_count, p.NONE, "no version is read")

    def bud_the_runner_version_comes_from_the_package_metadata(self):
        """The runner's version is the installed package's version."""
        with patch("bud_runner.cli.read_package_version", return_value=p.METADATA_VERSION) as version:
            shown = _read_runner_package_version()
        self.assertEqual(shown, p.METADATA_VERSION, "the package version is shown")
        self.assertEqual(version.call_count, p.ONE, "it is read once")
        self.assertEqual(version.call_args.args, (), "it is read without arguments")

    def bud_the_registration_project_link_omits_the_socket_port(self):
        """register prints the project link without the socket port."""
        result, _ = self.register(self.station(), "--password", p.PASSWORD)
        self.assertEqual(result.exit_code, p.OK, f"register exits 0: {result.output}")
        for line in (m.ACCOUNT_LINE, m.BACKEND_LINE):
            self.assertIn(member=line, container=result.stdout, msg=f"the link holds {line!r}")
        self.assertNotIn(member=m.SOCKET_LINE, container=result.stdout, msg="the link holds no socket port")

    def bud_register_without_a_password_generates_one_and_prints_it_once(self):
        """register without --password generates one, registers with it and prints it."""
        with patch("bud_runner.cli.secrets.token_urlsafe", return_value=p.GENERATED):
            result, manager = self.register(self.station())
        self.assertEqual(result.exit_code, p.OK, f"register exits 0: {result.output}")
        self.assertEqual(
            manager.register.call_args.kwargs,
            {"username": p.STATION, "password": p.GENERATED, "socket_port": c.DEFAULT_PORT},
            "the generated password registers the station",
        )
        for text in (m.GENERATED, p.GENERATED):
            self.assertIn(member=text, container=result.stdout, msg=f"register prints {text!r}")

    def bud_register_refuses_an_existing_local_runner_without_re_register(self):
        """A station in the vault is refused with exit 2 without --re-register."""
        result, _ = self.register(self.station(p.VAULT_ENTRY))
        self.assertEqual(result.exit_code, p.REFUSED, "register exits 2")
        self.assertIn(member=m.ALREADY_LOCAL, container=result.output, msg="register says already registered locally")

    def bud_re_register_requires_the_existing_password(self):
        """--re-register without --password is refused with exit 2."""
        result, _ = self.register(self.station(p.VAULT_ENTRY), "--re-register")
        self.assertEqual(result.exit_code, p.REFUSED, "register exits 2")
        self.assertIn(member=m.NEEDS_PASSWORD, container=result.output, msg="register asks for the existing password")

    def bud_re_register_uses_the_given_password_and_refreshes_the_registration(self):
        """--re-register with --password registers again with that password."""
        result, manager = self.register(self.station(p.VAULT_ENTRY), "--password", p.KNOWN_PASSWORD, "--re-register")
        self.assertEqual(result.exit_code, p.OK, f"register exits 0: {result.output}")
        self.assertEqual(
            manager.register.call_args.kwargs,
            {"username": p.STATION, "password": p.KNOWN_PASSWORD, "socket_port": c.DEFAULT_PORT},
            "the given password registers the station again",
        )
        self.assertIn(member=m.RE_REGISTERING, container=result.stdout, msg=f"register prints {m.RE_REGISTERING!r}")

    def bud_the_auth_manager_exposes_the_registered_socket_port(self):
        """A registered station's socket port comes from the vault."""
        with self.clean(p.SERVICE_VAULT):
            port = AuthManager(username=p.SERVICE_RUNNER).socket_port
        self.assertEqual(port, p.SERVICE_PORT, "the vault's port is used")

    def bud_list_tests_resolves_a_suite_without_running_it(self):
        """list-tests resolves the fixture list's two classes."""
        result = CliRunner().invoke(app, ["list-tests", "--test-case-list", c.FIXTURE_LIST])
        self.assertEqual(result.exit_code, p.OK, f"list-tests exits 0: {result.output}")
        for text in (m.RESOLVED, c.FIRST_FIXTURE):
            self.assertIn(member=text, container=result.stdout, msg=f"list-tests prints {text!r}")

    def bud_list_tests_supports_json_output(self):
        """list-tests --output-format json names the list, the count and each test."""
        result = CliRunner().invoke(app, ["list-tests", "--test-case-list", c.FIXTURE_LIST, "--output-format", "json"])
        self.assertEqual(result.exit_code, p.OK, f"list-tests exits 0: {result.output}")
        payload = json.loads(result.stdout)
        self.assertEqual(payload["test_case_list"], c.FIXTURE_LIST, "the list is named")
        self.assertEqual(payload["count"], p.FIXTURE_COUNT, "two tests are counted")
        self.assertEqual(payload["tests"][0]["path"], c.FIRST_FIXTURE, "the first test is named")

    def bud_an_artifact_upload_uses_the_client_session(self):
        """upload_artifact posts through the client's session with the run, test case, timeout and auth."""
        client = self.client("user-token")
        path = self.artifact()
        with patch.object(client._session, "post") as post, patch("bud_runner.api_client.requests.post") as bare_post:
            post.return_value = MagicMock(json=MagicMock(return_value=p.UPLOADED))
            answer = client.upload_artifact(str(path), run_id=p.RUN_ID, test_case=p.TEST_CASE)
        self.assertEqual(answer, p.UPLOADED, "the answer is returned")
        self.assertEqual(post.call_count, p.ONE, "the session posts once", abort_on_fail=True)
        self.assertEqual(bare_post.call_count, p.NONE, "requests.post is not used")
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["data"], {"run_id": p.RUN_ID, "test_case": p.TEST_CASE}, "the run and test case are sent")
        self.assertEqual(kwargs["timeout"], c.UPLOAD_TIMEOUT, "the upload has a 120 s timeout")
        self.assertIn(member="Authorization", container=kwargs["headers"], msg="the upload is authenticated")

    def bud_an_artifact_upload_is_real_multipart(self):
        """The prepared request is multipart/form-data with a boundary."""
        client = self.client("runner-token")
        path = self.artifact()
        response = requests.Response()
        response.status_code = p.CREATED
        response._content = p.CREATED_BODY
        response.headers["Content-Type"] = "application/json"
        with patch.object(client._session, "send", return_value=response) as send:
            client.upload_artifact(str(path), run_id=p.RUN_ID, test_case=p.TEST_CASE)
        content_type = send.call_args.args[0].headers["Content-Type"]
        self.assertTrue(content_type.startswith(m.MULTIPART), f"the body is multipart: {content_type!r}")
