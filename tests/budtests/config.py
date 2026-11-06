"""Set-up of the bud-runner unit suites: what the mocked station is configured with."""

from pathlib import Path


class StationNaming:
    """Set-up of the station_naming suite."""

    BACKEND_URL = "https://bud.example.com"
    TYPED_NAME = "whatever-the-bench-typed"
    TOKEN = "a-token"
    PORT = 53035


class ApiClient:
    """Set-up of the api_client suite."""

    BACKEND_URL = "https://example.com"
    ACCOUNT = "station-01"
    WORK_DIR_SETTING = "BUDTEST_WORK_DIR"
    ARTIFACT_NAME = "report_junit.xml"
    ARTIFACT_TEXT = "<testsuite/>\n"


class Verbose:
    """Set-up of the verbose suite."""

    WORK_DIR_SETTING = "BUDTEST_WORK_DIR"
    REPORT_NAME = "result.xml"
    BACKEND_URL = "https://bud.example"
    STATION_TOKEN = "station-token"
    ACCOUNT = "station-01"
    TEST_TIMEOUT = 10


class PackagingMetadata:
    """Set-up of the packaging_metadata suite."""

    ROOT = Path(__file__).resolve().parents[2]
    ORG_SETTING = "PACKAGE_ORG"
    MAINTAINER_SETTING = "ORG_MAINTAINER"


class Executor:
    """Set-up of the executor suite."""

    TEST_TIMEOUT = 10
    SUITE_TIMEOUT = 60
    SHORT_TEST_TIMEOUT = 2
    LONG_TEST_TIMEOUT = 30
    NO_SUITE_TIME = 0
    STUB_TEST_TIMEOUT = 5
    FIXTURE_LIST = "tests.fixtures.mock_tests.MOCK_TEST_LIST"
    VALID_CASE = "tests.fixtures.mock_tests.FastPassTest"
    MISSING_CASE = "unavailable_station_suite.MissingCase"
    SELECTION_MODULE = "selected_station_cases"
    SELECTION = "selected_station_cases.CASES"
    CONTEXT_TARGET = "bud_runner.test_executor.multiprocessing.get_context"


class Auth:
    """Set-up of the auth suite."""

    WORK_DIR_SETTING = "BUDTEST_WORK_DIR"
    FOLDER = "auth"
    HOME = "home"
    REPO = "repo"
    VAULT = ".bud/config.json"
    PROPERTIES = "app.properties"
    BUD_PREFIX = "BUD_"
    READ_STRING = "bud_runner.auth.configparser.ConfigParser.read_string"
    DEFAULT_BACKEND = "http://localhost:8000"


class CliSignals:
    """Set-up of the cli_signals suite."""

    FIXTURE_LIST = "tests.fixtures.mock_tests.MOCK_TEST_LIST"
    BACKEND_URL = "https://bud.example.com"
    LOOPBACK = "127.0.0.1"
    PORT = 53035
    INTERVAL = 60
    LOGGER = "bud_runner.runner_manager"


class ClaimRun:
    """Set-up of the claim_run suite."""

    WORK_DIR_SETTING = "BUDTEST_WORK_DIR"
    FOLDER = "claim_run"
    TEMP_TARGET = "bud_runner.cli.tempfile.gettempdir"
    SUBPROCESS_TARGET = "bud_runner.cli.subprocess.run"
    SLEEP_TARGET = "bud_runner.cli.time.sleep"
    BACKEND_URL = "http://localhost:8000"
    USER_TOKEN = "user-token"
    RUNNER_TOKEN = "runner-token"
    ACCOUNT = "station-01"


class CucumberImporter:
    """Set-up of the cucumber_importer suite."""

    FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "cucumber"
    RUNNERS = ("cucumber-js.json", "cucumber-jvm.json", "cucumber-ruby.json")
    JS, JVM, RUBY = RUNNERS
    EDGES = "cucumber-js-edges.json"
    WORK_DIR_SETTING = "BUDTEST_WORK_DIR"
    FOLDER = "cucumber_importer"
    BACKEND_URL = "https://bud.example"
    STATION = "station-1"
    PRODUCT_ID = 12
    UPLOADED_RUN = 42


class BackendUrl:
    """Set-up of the backend_url suite."""

    WORK_DIR_SETTING = "BUDTEST_WORK_DIR"
    FOLDER = "backend_url"
    REFUSED = "http://bud.example.com"
    HTTPS = "https://bud.example.com"
    LOOPBACK = "http://127.0.0.1:8001"
    DEFAULT = "http://localhost:8000"
    CUCUMBER_REPORT = Path(__file__).resolve().parents[1] / "fixtures" / "cucumber" / "cucumber-js.json"
    BUD_SETTINGS = (
        "BUD_BACKEND_URL",
        "BUD_TOKEN",
        "BUD_USERNAME",
        "BUD_RUNNER_ACCOUNT",
        "BUD_RUNNER_TOKEN",
        "BUD_RUNNER_API_KEY",
        "RUNNER_API_KEY",
        "BUD_ALLOW_HTTP",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
    )
    ALLOW = "BUD_ALLOW_HTTP"
    CA_BUNDLE = "REQUESTS_CA_BUNDLE"
    TOKEN = "station-session"
    ACCOUNT = "station-01"
