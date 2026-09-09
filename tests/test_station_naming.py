"""The name Bud reports is the name this station uses."""

from unittest.mock import MagicMock

from bud_runner.runner_manager import RunnerManager


def _manager(register_response):
    auth = MagicMock()
    auth.runner_account = "whatever-the-bench-typed"
    auth.runner_token = "a-token"
    auth.socket_port = 53035
    manager = RunnerManager(auth)
    manager._client = MagicMock()
    manager._client.register_runner.return_value = register_response
    return manager, auth


def test_registration_stores_the_name_bud_assigned():
    manager, auth = _manager({"account": "bench-a", "token": "t"})

    result = manager.register(username="whatever-the-bench-typed", password="p", socket_port=53035)

    assert result["account"] == "bench-a"
    auth.save_identity.assert_called_once()
    assert auth.save_identity.call_args.kwargs["username"] == "bench-a"


def test_registration_keeps_its_own_name_when_bud_names_none():
    manager, auth = _manager({"token": "t"})

    result = manager.register(username="lab-station-01", password="p", socket_port=53035)

    assert result["account"] == "lab-station-01"
    assert auth.save_identity.call_args.kwargs["username"] == "lab-station-01"


def test_a_heartbeat_reporting_a_new_name_rewrites_the_identity():
    manager, auth = _manager({"account": "bench-a", "token": "t"})

    manager._adopt_renamed_account("bench-a-renamed")

    auth.save_identity.assert_called_once_with(
        username="bench-a-renamed", token="a-token", port=53035
    )


def test_a_heartbeat_reporting_the_same_name_rewrites_nothing():
    manager, auth = _manager({"account": "bench-a", "token": "t"})

    manager._adopt_renamed_account("whatever-the-bench-typed")
    manager._adopt_renamed_account(None)

    auth.save_identity.assert_not_called()
