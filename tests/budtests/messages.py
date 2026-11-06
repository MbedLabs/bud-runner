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


class CucumberImporter:
    """Texts of the cucumber_importer suite."""

    RUNNER_MESSAGES = [
        ("cucumber-js.json", "AssertionError [ERR_ASSERTION]\n    + expected - actual\n\n    -2\n    +3"),
        ("cucumber-jvm.json", "java.lang.AssertionError: expected 3"),
        ("cucumber-ruby.json", "expected 3 (RuntimeError)"),
    ]
    BAD_VALUE = "bad value"
    UNDEFINED = "Undefined step: When nobody wrote this"
    HOOK_BROKE = "hook broke"
    AMBIGUOUS = "Ambiguous step: When I do twice"
    AFTER_BROKE = "Error: after broke"
    SKIPPED_BY_RUNNER = "Skipped by the runner"
    NO_STEPS = "Scenario has no steps"
    UNDEFINED_A = "Undefined step: When a"
    MALFORMED = [
        ("{not json", "not valid JSON"),
        ('{"name": "x"}', "a Cucumber JSON report is a list of features"),
        ('[{"name": "x"}]', "feature 1 has no list of elements"),
        ('[{"name": "x", "elements": [{"steps": 3}]}]', "feature 1 has an element whose steps are not a list"),
        ('[{"name": "x", "elements": [3]}]', "feature 1 has an element that is not an object"),
        ('[{"name": "x", "elements": [{"steps": [3]}]}]', "feature 1 has steps that are not objects"),
        ('[{"name": "x", "elements": [{"steps": [{"name": "a", "result": "passed"}]}]}]', "a steps entry whose result"),
        ('[{"name": "x", "elements": [{"before": {"result": {}}}]}]', "whose before are not a list"),
        ('[{"name": "x", "tags": "@a", "elements": []}]', "feature 1 has tags that are not a list"),
    ]
    NOT_UTF8 = "not UTF-8 text"
    CANNOT_READ = "cannot read the file"
    EDGES_SUMMARY = "2 features, 9 scenarios (5 passed, 2 failed, 2 skipped)"
    NOT_JSON = "✗ {path}: not valid JSON"
    RESULT_NOT_OBJECT = "result is not an object"
    JVM_SUMMARY = "1 features, 8 scenarios (3 passed, 5 failed, 0 skipped)"
    EMPTY_SUMMARY = "0 features, 0 scenarios"
    NO_BACKEND = "No backend URL configured"
    BACKEND_DOWN = "backend down"
