"""Texts the bud-runner unit suites expect bud-runner to show."""


class ApiClient:
    """Texts of the api_client suite."""

    STATION_REQUIRED = "Station authentication is required"


class CliSignals:
    """Texts of the cli_signals suite."""

    STARTING = "Starting Bud Runner Daemon for: {account}"
    SOCKET_PORT = "Socket Port: {port}"


class ClaimRun:
    """Texts of the claim_run suite."""

    CLAIMED = "Claimed run 7"
    NOTHING_QUEUED = "Nothing queued"
    COULD_NOT_CLAIM = "Could not claim a run"
    REGISTER = "register"
