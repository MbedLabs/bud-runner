"""Run submissions use station credentials even when a human session exists."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from bud_runner.api_client import BudAPIClient


def _client(human_token, station_token, station_key=None):
    """Build a client with an intercepted HTTP transport."""
    auth = SimpleNamespace(
        backend_url="https://example.com",
        token=human_token or station_token,
        runner_token=station_token,
        runner_api_key=station_key,
        runner_account="station-01",
    )
    client = BudAPIClient(auth)
    response = Mock(spec=requests.Response)
    response.status_code = 201
    response.json.return_value = {"id": 7}
    client._session.send = Mock(return_value=response)
    return client


def _submit(client, operation):
    """Submit a run record or raw execution results."""
    if operation == "create":
        client.create_test_run("suite", "Station run")
    elif operation == "patch":
        client.update_test_run(7, total_tests=3)
    else:
        client.upload_results_payload(
            {"results": [{"test_class": "Suite", "test_method": "test_one", "passed": True}]}
        )


@pytest.mark.parametrize("operation", ["create", "patch", "results"])
@pytest.mark.parametrize("human_token", [None, "human-session"])
def test_run_submission_uses_station_token(operation, human_token):
    client = _client(human_token, "station-session")
    _submit(client, operation)
    request = client._session.send.call_args.args[0]
    assert request.headers["Authorization"] == "Bearer station-session"


@pytest.mark.parametrize("operation", ["create", "patch", "results"])
def test_human_session_cannot_submit_run_without_station_token(operation):
    client = _client("human-session", None)
    with pytest.raises(RuntimeError, match="Station authentication is required"):
        _submit(client, operation)
    client._session.send.assert_not_called()


def test_result_submission_with_station_key_removes_human_session():
    client = _client("human-session", None, "station-enrolment-key")
    _submit(client, "results")
    request = client._session.send.call_args.args[0]
    assert "Authorization" not in request.headers
    assert request.headers["X-API-Key"] == "station-enrolment-key"


@pytest.mark.parametrize("human_token", [None, "human-session"])
def test_execution_artifact_uses_station_token(tmp_path, human_token):
    artifact = tmp_path / "report_junit.xml"
    artifact.write_text("<testsuite/>\n")
    client = _client(human_token, "station-session")
    client.upload_artifact(str(artifact), run_id=7)
    request = client._session.send.call_args.args[0]
    assert request.headers["Authorization"] == "Bearer station-session"


def test_human_artifact_upload_keeps_existing_human_authentication(tmp_path):
    artifact = tmp_path / "report_junit.xml"
    artifact.write_text("<testsuite/>\n")
    client = _client("human-session", None)
    client.upload_artifact(str(artifact), run_id=7)
    request = client._session.send.call_args.args[0]
    assert request.headers["Authorization"] == "Bearer human-session"
