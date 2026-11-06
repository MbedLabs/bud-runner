"""Run submissions use station credentials even when a human session exists, with Bud's HTTP
transport mocked."""

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import requests
from budtestlibrary import BudTestCase, parameterized

from bud_runner.api_client import BudAPIClient
from tests.budtests.config import ApiClient as c
from tests.budtests.messages import ApiClient as m
from tests.budtests.parameters import ApiClient as p


class ApiClient(BudTestCase):
    """BudAPIClient's run submissions and artifact uploads through a mocked transport."""

    def client(self, human, station, key=None) -> BudAPIClient:
        """A client whose transport answers every request with 201 and records it."""
        auth = SimpleNamespace(
            backend_url=c.BACKEND_URL,
            token=human or station,
            runner_token=station,
            runner_api_key=key,
            runner_account=c.ACCOUNT,
        )
        client = BudAPIClient(auth)
        response = Mock(spec=requests.Response)
        response.status_code = p.CREATED
        response.json.return_value = p.ANSWER
        client._session.send = Mock(return_value=response)
        return client

    def submit(self, client: BudAPIClient, operation: str):
        """Create a run, patch it, or upload raw results."""
        if operation == "create":
            client.create_test_run(p.SUITE, p.RUN_NAME)
        elif operation == "patch":
            client.update_test_run(p.RUN_ID, total_tests=p.TOTAL_TESTS)
        else:
            client.upload_results_payload(p.RESULTS)

    def sent_headers(self, client: BudAPIClient):
        """The headers of the request the transport sent."""
        return client._session.send.call_args.args[0].headers

    @parameterized(p.SUBMISSIONS)
    def bud_run_submission_uses_station_token(self, operation, human):
        """Every submission carries the station token, with or without a human session."""
        client = self.client(human, p.STATION)
        self.submit(client, operation)
        self.assertEqual(
            self.sent_headers(client).get("Authorization"),
            p.STATION_BEARER,
            f"{operation} with human session {human!r} sends the station token",
        )

    @parameterized(p.OPERATIONS)
    def bud_a_human_session_without_station_token_submits_nothing(self, operation):
        """A human session alone is refused before anything is sent."""
        client = self.client(p.HUMAN, None)
        try:
            self.submit(client, operation)
            raised = ""
        except RuntimeError as error:
            raised = str(error)
        self.assertIn(member=m.STATION_REQUIRED, container=raised, msg=f"{operation} is refused")
        self.assertEqual(client._session.send.call_count, p.NONE, f"{operation} sends nothing")

    def bud_result_submission_with_station_key_drops_the_human_session(self):
        """Results sent with a station key carry the key and no human bearer token."""
        client = self.client(p.HUMAN, None, p.STATION_KEY)
        self.submit(client, "results")
        headers = self.sent_headers(client)
        self.assertNotIn(member="Authorization", container=headers, msg="no bearer token is sent")
        self.assertEqual(headers.get("X-API-Key"), p.STATION_KEY, "the station key is sent")

    @parameterized(p.HUMANS)
    def bud_execution_artifact_uses_station_token(self, human):
        """An execution artifact is uploaded with the station token."""
        folder = Path(os.environ[c.WORK_DIR_SETTING])
        folder.mkdir(parents=True, exist_ok=True)
        artifact = folder / c.ARTIFACT_NAME
        artifact.write_text(c.ARTIFACT_TEXT)
        client = self.client(human, p.STATION)
        client.upload_artifact(str(artifact), run_id=p.RUN_ID)
        self.assertEqual(
            self.sent_headers(client).get("Authorization"),
            p.STATION_BEARER,
            f"the artifact with human session {human!r} is sent with the station token",
        )
