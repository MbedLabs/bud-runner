"""Values the bud-runner unit suites use: inputs and Bud's answers."""


class StationNaming:
    """Values of the station_naming suite."""

    PASSWORD = "p"
    ASSIGNED = "bench-a"
    OWN_NAME = "lab-station-01"
    RENAMED = "bench-a-renamed"
    REGISTERED_TOKEN = "t"
    ASSIGNED_ANSWER = {"account": ASSIGNED, "token": REGISTERED_TOKEN}
    NAMELESS_ANSWER = {"token": REGISTERED_TOKEN}
    ONE = 1
    NONE = 0


def _result(test_class: str, skipped: bool) -> dict:
    """A result of a test class, skipped or not, as the adapters report it."""
    return {"test_class": test_class, "metadata": {"skipped": True} if skipped else {}}


class Reporting:
    """Values of the reporting suite."""

    SHORT_IDS = [
        ("PRJ-001", "PRJ-TC-001"),
        (" PRJ-001 ", "PRJ-TC-001"),
        ("PRJ-TC-001", "PRJ-TC-001"),
        ("prj-tc-001", "prj-tc-001"),
        ("PRJ-a_7", "PRJ-TC-a_7"),
        ("PRJ001", "PRJ001"),
        ("-001", "-001"),
        ("PRJ-", "PRJ-"),
    ]
    SKIPPED_COUNTS = [
        ([], 0),
        ([_result("a", True), _result("b", False)], 1),
        ([_result("feature", True), _result("feature", False)], 0),
        ([_result("feature", True), _result("feature", True), _result("other", True)], 2),
        ([{"test_class": "a"}], 0),
    ]


class ApiClient:
    """Values of the api_client suite."""

    HUMAN = "human-session"
    STATION = "station-session"
    STATION_KEY = "station-enrolment-key"
    RUN_ID = 7
    CREATED = 201
    ANSWER = {"id": 7}
    SUITE = "suite"
    RUN_NAME = "Station run"
    TOTAL_TESTS = 3
    RESULTS = {"results": [{"test_class": "Suite", "test_method": "test_one", "passed": True}]}
    OPERATIONS = ["create", "patch", "results"]
    HUMANS = [None, "human-session"]
    SUBMISSIONS = [
        ("create", None),
        ("create", "human-session"),
        ("patch", None),
        ("patch", "human-session"),
        ("results", None),
        ("results", "human-session"),
    ]
    STATION_BEARER = "Bearer station-session"
    NONE = 0


class Verbose:
    """Values of the verbose suite."""

    LEVELS = [(False, 20), (True, 10)]
    FLAGS = [([], False), (["--verbose"], True), (["-v"], True)]
    TEST_LIST = "Suite.CASES"
    CLAIM = {"run": {"id": 4, "name": "Run"}, "claim_id": "claim", "selected_tests": None}
    VERBOSE_FLAG = "--verbose"
    PASSED_EXIT = 0


class PackagingMetadata:
    """Values of the packaging_metadata suite."""

    RELEASE_NUMBER = r"\d+\.\d+\.\d+"
    ORG = {"name": "EmbedLabs", "email": "dev@embedlabs.net"}
    AUTHORS = 2
    URLS = {
        "Homepage": "https://embedlabs.net",
        "Documentation": "https://embedlabs.net/docs",
        "Support": "https://embedlabs.net",
    }
    LICENSE = {"text": "AGPL-3.0-only"}
    STABLE = "Development Status :: 5 - Production/Stable"
    CHANGELOG_ENTRY = "## [{version}]"
    SELF_HOSTED = "self-hosted CI"
    RELATIVE_LINK = r"\[[^]]+\]\((?!https?://|mailto:|#)[^)]+\)"
    CREATOR = "Creator: {maintainer}"


class FlattenResults:
    """Values of the flatten_results suite."""

    VOLTAGE = "VoltageTest"
    CELLS = "bud_check_cells"
    PACK = "bud_check_pack"
    RUN_ID = 42
    OK = "ok"
    TOO_LOW = "too low"
    CELL_ERROR = "cell 3 out of range"
    TRACE = "Traceback..."
    SUMMARY = "Failed: cell 3 out of range"
    CELL_ASSERTIONS = [{"passed": True, "message": "ok"}, {"passed": False, "message": "too low"}]
    TWO_ROWS = 2
    ONE_ROW = 1
    BROKEN = "BrokenSuite"
    BROKEN_RUN_ID = 7
    SETUP_ERROR = "setUpClass raised"
    PLACEHOLDER = "__class__"
    SOLO = "bud_solo"
    UNKNOWN_CLASS = "UnknownTestClass"
    SMOKE_RUN_ID = 9
    SMOKE_ROW = {
        "test_class": "SmokeTest",
        "test_method": "bud_hello",
        "passed": True,
        "duration_seconds": 0.1,
        "assertions": [{"passed": True, "message": "ok"}],
    }
    HELLO = "bud_hello"


class Executor:
    """Values of the executor suite."""

    WITH_VALID_CASE = [False, True]
    TIMED_OUT = ("timed out", "failed to retrieve")
    TRUNCATED = "__suite_truncated__"
    SUITE_TIMEOUT_TEXT = "suite timeout"
    INTERRUPTED = "__suite_interrupted__"
    INTERRUPTED_TEXT = "interrupted"
    LARGE = "LargeResultTest"
    FAST = "FastPassTest"
    STUB_RESULT = {
        "test_class": "StubTest",
        "passed": True,
        "method_results": [],
        "duration_seconds": 0.0,
        "error_message": None,
        "start_time": None,
        "end_time": None,
        "metadata": {},
    }
    ROUNDTRIP_CLASS = "X"
    ROUNDTRIP_SECONDS = 1.5
    MARKERS = 2
    NONE = 0


class Auth:
    """Values of the auth suite."""

    RUNNER_VAULT = (
        '{"ci-runner": {"token": "vault-token", "port": 53035, "backend": "https://vault-backend"}}'
    )
    STRAY_PROPERTIES = (
        "budRunnerAccount=ci-runner\nbudBackend=https://project-backend\nbudRunnerToken=project-token\n"
        "runnerApiKey=project-api-key\nbudToken=project-user-token"
    )
    PROJECT_PROPERTIES = "budBackend=https://project-backend\nbudRunnerAccount=project-runner"
    SERVICE_VAULT = '{"service-runner": {"token": "vault-token", "port": 54001, "backend": "https://vault-backend"}}'
    USER_VAULT = '{"_users": {"ci@example.com": {"token": "user-token", "backend": "https://vault-backend"}}}'
    CI_RUNNER = "ci-runner"
    SERVICE_RUNNER = "service-runner"
    USER = "ci@example.com"
    VAULT_BACKEND = "https://vault-backend"
    VAULT_TOKEN = "vault-token"
    USER_TOKEN = "user-token"
    ENV = {
        "BUD_BACKEND_URL": "https://env-backend",
        "BUD_RUNNER_ACCOUNT": "env-runner",
        "BUD_RUNNER_TOKEN": "env-token",
    }
    ENV_BACKEND = "https://env-backend"
    ENV_RUNNER = "env-runner"
    ENV_TOKEN = "env-token"
    ARG_BACKEND = "https://arg-backend"
    ARG_USERNAME = "arg-runner"
    ARG_RUNNER = "arg-explicit-runner"
    SAVE_ARGUMENTS = {
        "username": "last-user",
        "backend_url": "https://bud.example",
        "runner_account": "runner-01",
        "runner_token": "secret-token",
        "runner_api_key": "secret-api-key",
    }
    LOCATION = "Lab A"
    PRODUCT_ID = 42
    SAVED_LINES = [
        "budBackend=https://bud.example",
        "budRunnerAccount=runner-01",
        "location=Lab A",
        "productId=42",
        "lastUser=last-user",
    ]
    UNSAVED = [
        "runnerSocketPort",
        "budRunnerToken",
        "runnerApiKey",
        "secret-token",
        "secret-api-key",
    ]
    BAD_PROPERTIES = "budBackend=https://bud.example"
    BAD_ERROR = "bad properties"
    LOAD_WARNING = "Error loading properties"


class CliSignals:
    """Values of the cli_signals suite."""

    JUNIT = "<testsuite/>"
    PASSED_CLASS = "T1"
    INTERRUPT_EXIT = 130
    ONE = 1
    PASSED_EXIT = 0
    RUNNER = "runner-01"
    SERVICE_RUNNER = "service-runner"
    TOKEN = "runner-token"
    REGISTERED_PORT = 54001
    LOG_MESSAGE = "Heartbeat task started"
    LOG_LINE = 123
    LEVEL = "INFO"


class ClaimRun:
    """Values of the claim_run suite."""

    CLAIM_ID = "11111111-1111-4111-8111-111111111111"
    RUN_ID = 7
    RUN_NAME = "Custom run"
    DEFAULT_LIST = "Suite.CASES"
    OWN_LIST = "Bud_Suite.HIL"
    ALPHA = ["suite.Alpha"]
    SELECTION = ["voltage_suite.VoltageTest", "boot_suite.BootTest"]
    SELECTION_RUN = 42
    LIST_NAME = "CUSTOM_TEST_LIST"
    FIRST_PATH, FIRST_RUN = ["a.A"], 1
    SECOND_PATH, SECOND_RUN = ["b.B"], 2
    MODULE = "bud_custom_{run}.py"
    QUOTED_PATH = "suite.Test'X"
    QUOTED_RUN = 3
    CUSTOM_LIST = "bud_custom_7.CUSTOM_TEST_LIST"
    RUN_TESTS = ["-m", "bud_runner", "run-tests"]
    PASSTHROUGH = ["--artifact", "*.png"]
    COMPLETED = {"status": "Completed"}
    EXECUTOR_ERROR = "executor crashed"
    WRAPPED_ERROR = "RuntimeError: executor crashed"
    INTERVAL = ["--interval", "5"]
    OK = 200
    EMPTY = 204
    FORBIDDEN = 403
    PASSED = 0
    FAILED = 1
    CONFIG_ERROR = 2
    INTERRUPTED = 130
    ONE = 1
    TWO = 2
    NONE = 0


class CucumberImporter:
    """Values of the cucumber_importer suite."""

    SCENARIOS = [
        "Voltage within limit",
        "Wrong value",
        "Step raises",
        "Missing step",
        "Hook fails",
        "Pending step",
        "Outline 1",
        "Outline 2",
    ]
    FEATURE = "Bench supply"
    MEASURED = "Voltage within limit"
    TC_ID = "PRJ-TC-001"
    TAGS = ["bloom:PRJ-001", "smoke", "suite-tag"]
    LOCATION_END = "features/bench.feature:7"
    MEASURED_STEPS = [
        ("a bench", True, True),
        ("I measure 3", True, True),
        ("the value is 3", True, False),
        ("the value is below 5", True, False),
    ]
    CHECK_CONTEXT = "And the value is below 5"
    CHECK_LINE = 10
    JS_COUNTS = {"features": 1, "scenarios": 8, "passed": 3, "failed": 5, "skipped": 0}
    WRONG = "Wrong value"
    FAILED_STEP = ("the value is 3", False)
    RAISES = "Step raises"
    MISSING = "Missing step"
    PENDING = "Pending step"
    HOOK = "Hook fails"
    HOOK_STEPS = [("HookError", False)]
    OWN_TAG = "Own tag wins"
    OWN_TC = "PRJ-TC-002"
    OWN_TAGS = ["bloom:PRJ-002", "bloom:PRJ-009"]
    FEATURE_TAG_ONLY = "Feature tag only"
    FEATURE_TC = "PRJ-TC-009"
    AMBIGUOUS = "Ambiguous step"
    AFTER = "After hook fails"
    AFTER_STEPS = [("a bench", True), ("HookError", False)]
    SKIPPED_SCENARIOS = [
        ("Skips itself", "Skipped by the runner"),
        ("Nothing in it", "Scenario has no steps"),
    ]
    SAME_NAMES = ["Same name (line 33)", "Same name (line 34)"]
    GERMAN = "Wert prüfen"
    GERMAN_FEATURE = "Prüfstand"
    EDGES_COUNTS = {"features": 2, "scenarios": 9, "passed": 5, "failed": 2, "skipped": 2}
    HOOK_ONLY = [
        {"keyword": "Before", "hidden": True, "result": {"status": "passed", "duration": 1}}
    ]
    UNDEFINED_STEPS = [
        {"keyword": "When ", "name": "a", "line": 3, "result": {"status": "undefined"}}
    ]
    FAILED_AFTER = [{"result": {"status": "failed", "error_message": "Error: after broke"}}]
    PAYLOAD_OPTIONS = {"test_run_id": 7, "product_id": 4, "ref_sw_under_test": "v2.4.1"}
    PAYLOAD_EXPECTED = {
        "test_run_id": 7,
        "product_id": 4,
        "runner_account": "station-1",
        "ref_software_under_test": "v2.4.1",
        "test_suite_name": "Bench supply",
    }
    ACCOUNT = "station-1"
    DEFAULT_PRODUCT = 12
    RESULTS = 8
    EDGES_RESULTS = 9
    EDGES_SUITE = "features"
    SUITE_NAME = "Bench"
    NO_URI = [{"name": "A", "elements": []}, {"name": "B", "elements": []}]
    NO_URI_FILE = "nightly.json"
    NO_URI_SUITE = "nightly"
    FEATURE_PATHS = [
        (
            "file:src/test/resources/features/bench.feature",
            "src/test/resources/features/bench.feature",
        ),
        ("features/bench.feature", "features/bench.feature"),
        (None, None),
        ("classpath:com/acme/bench.feature", "com/acme/bench.feature"),
    ]
    ERROR_TEXTS = [
        ("Error: bad\n    at World.<anonymous> (features/steps.js:5:37)", "Error: bad"),
        (
            "java.lang.AssertionError: x\n\tat probe.Steps.valueIs(Steps.java:12)",
            "java.lang.AssertionError: x",
        ),
        ("x (RuntimeError)\n./features/steps.rb:5:in `block'", "x (RuntimeError)"),
    ]
    JVM_LOCATION = "src/test/resources/features/bench.feature:7"
    REPORT_FILE = "report.json"
    UTF16_REPORT = '[{"name": "x", "elements": []}]'
    WRONG_SHAPE = '[{"name": "x", "elements": [{"steps": [{"name": "a", "result": "passed"}]}]}]'
    RUN_ID = "7"
    RUN_ID_VALUE = 7
    OK = 0
    FAILED = 1
    REFUSED = 2
    ONE = 1


class BackendUrl:
    """Values of the backend_url suite."""

    ACCEPTED = [
        "http://localhost:8001",
        "http://127.0.0.1:8001",
        "http://[::1]:8001",
        "https://bud.example.com",
        "http://localhost:8000",
        "http://LocalHost:8001",
        "HTTP://127.0.0.1:8001",
        "http://127.255.255.254",
        "https://192.168.1.10:8001",
    ]
    REFUSED_URLS = [
        "http://bud.example.com",
        "http://192.168.1.10:8001",
        "http://10.0.0.5",
        "http://BUD.EXAMPLE.COM",
        "HTTP://bud.example.com",
        " http://bud.example.com",
        "http://[fe80::1]:8001",
        "http://[::ffff:127.0.0.1]:8001",
        "http://0.0.0.0:8001",
        "http://localhost.example.com",
        "http://127.0.0.1.example.com",
        "http://[::1",
        "http://",
    ]
    COMMANDS = [
        ["add-test-run", "-t", "Suite.CASES", "-n", "Nightly", "--bud-token", "user-token"],
        ["run-tests", "-t", "Suite.CASES", "--format", "text"],
        ["claim-run"],
        ["register", "--username", "station-01", "--api-key", "enrolment-key", "--no-start"],
        ["daemon", "--username", "station-01"],
        ["run-robot", "tests/"],
        ["run-pytest", "tests/"],
        ["run-behave", "features/"],
        ["import-cucumber", "--report", "{report}"],
    ]
    OPT_IN_URLS = ["http://bud.example.com", "http://192.168.1.10:8001", "http://bud:8000"]
    OTHER_VALUES = ["0", "true", "yes", "false", "2", ""]
    UNREADABLE = ["http://", "http://[::1"]
    NOT_WEAKENED = ["https://bud.example.com", "http://localhost:8000"]
    SECRET_URL = "http://user:password@bud.example.com?token=private"
    SECRETS = ("password", "private")
    PREVIOUS = [None, "0", "1"]
    BUNDLE = "lab-ca.pem"
    PYTEST_FILE = "test_one.py"
    PYTEST_BODY = "def test_one():\n    assert 1 == 1\n"
    PID = 12345
    REGISTER = [
        "--allow-http",
        "register",
        "--username",
        "station-01",
        "--password",
        "test-password",
        "--api-key",
        "enrolment-key",
        "--backend-url",
        "http://bud.example.com",
    ]
    ON = "1"
    OK = 0
    REFUSED_EXIT = 2
    ONE = 1
    TWO = 2
    NONE = 0


class AuthAndStatus:
    """Values of the auth_and_status suite."""

    SERVER_VERSION = "1.2.3"
    RUNNER_VERSION = "0.4.6-test"
    PLAIN_VERSION = "0.4.6"
    METADATA_VERSION = "9.9.9"
    RUNNER = "runner-a"
    SECRET_TOKEN = "secret-token"
    STATION = "runner-01"
    PASSWORD = "super-secret"
    API_KEY = "shared-secret"
    GENERATED = "generated-pass-123"
    KNOWN_PASSWORD = "known-password-123"
    REGISTERED = {"id": 1}
    VAULT_ENTRY = {"token": "runner-token", "port": 53035}
    SERVICE_VAULT = '{"service-runner": {"token": "vault-token", "port": 54001, "backend": "https://vault-backend"}}'
    SERVICE_RUNNER = "service-runner"
    SERVICE_PORT = 54001
    FIXTURE_COUNT = 2
    ARTIFACT_NAME = "trace.log"
    ARTIFACT_TEXT = "trace-data"
    UPLOADED = {"id": 7, "url": "https://bud.example.com/a/7"}
    RUN_ID = 12
    TEST_CASE = "VoltageTest"
    CREATED = 201
    CREATED_BODY = b'{"id": 7}'
    OK = 0
    REFUSED = 2
    ONE = 1
    NONE = 0


class BehaveFormatter:
    """Values of the behave_formatter suite."""

    FEATURE = """Feature: Bench supply
  Background:
    Given a bench

  @bloom:PRJ-TC-001 @smoke
  Scenario: Voltage within limit
    When I measure 3
    Then the value is 3
    And the value is below 5

  Scenario: Wrong value
    When I measure 2
    Then the value is 3
    Then the value is below 5

  Scenario: Step raises
    When I break

  Scenario: Missing step
    When nobody wrote this

  @skipme
  Scenario: Skipped by hook
    When I measure 1

  @excluded
  Scenario: Excluded by tags
    When I measure 1

  @hookfail
  Scenario: Hook fails
    When I measure 1

  Scenario Outline: Outline <v>
    When I measure <v>
    Then the value is <v>
    Examples:
      | v |
      | 1 |
      | 2 |
"""
    STEPS = """
from behave import given, when, then


@given("a bench")
def a_bench(context):
    context.v = None


@when("I measure {v:d}")
def measure(context, v):
    context.v = v


@when("I break")
def broken(context):
    raise ValueError("bad value")


@then("the value is {v:d}")
def value_is(context, v):
    assert context.v == v, f"expected {v}"


@then("the value is below {v:d}")
def below(context, v):
    assert context.v < v
"""
    ENVIRONMENT = """
def before_scenario(context, scenario):
    if "skipme" in scenario.tags:
        scenario.skip("not on this bench")
    if "hookfail" in scenario.tags:
        raise RuntimeError("hook broke")
"""
    SECOND_FEATURE = """@bloom:PRJ-003
Feature: Bench clock
  Scenario: Clock runs
    Given a bench
"""
    NO_UPLOAD = ["-D", "bud_upload=false"]
    SCENARIOS = [
        "Voltage within limit",
        "Wrong value",
        "Step raises",
        "Missing step",
        "Skipped by hook",
        "Hook fails",
        "Outline 1 -- @1.1",
        "Outline 2 -- @1.2",
    ]
    FEATURE_NAME = "Bench supply"
    MEASURED = "Voltage within limit"
    TC_ID = "PRJ-TC-001"
    TAGS = ["bloom:PRJ-TC-001", "smoke"]
    LOCATION = "features/bench.feature:6"
    MEASURED_STEPS = [
        ("a bench", True, True, False),
        ("I measure 3", True, True, False),
        ("the value is 3", True, False, False),
        ("the value is below 5", True, False, False),
    ]
    CHECK_CONTEXT = "And the value is below 5"
    CHECK_SOURCE = ("features/bench.feature", 9)
    OUTLINE = "Outline 2 -- @1.2"
    OUTLINE_STEPS = ["a bench", "I measure 2", "the value is 2"]
    WRONG = "Wrong value"
    WRONG_STEPS = [
        ("a bench", True, True, False),
        ("I measure 2", True, True, False),
        ("the value is 3", False, False, False),
    ]
    RAISES = "Step raises"
    BREAK_STEP = ("I break", False, True, False)
    MISSING = "Missing step"
    MISSING_STEP = ("nobody wrote this", False, True, False)
    EXCLUDED = "Excluded by tags"
    SKIPPED = "Skipped by hook"
    SKIP_STEPS = [("Skip", True, False, True)]
    HOOK = "Hook fails"
    HOOK_STEPS = [("HookError", False)]
    PAYLOAD_OPTIONS = [
        "-D",
        "bud_test_run_id=7",
        "-D",
        "bud_product_id=4",
        "-D",
        "bud_ref_sw_under_test=v2.4.1",
    ]
    PAYLOAD_EXPECTED = {
        "test_run_id": 7,
        "product_id": 4,
        "runner_account": "station-1",
        "ref_software_under_test": "v2.4.1",
        "test_suite_name": "Bench supply",
    }
    ACCOUNT = "station-1"
    DEFAULT_PRODUCT = 12
    RESULTS = 8
    MANY_FEATURES = "features"
    CLOCK = "Clock runs"
    CLOCK_TC = "PRJ-TC-003"
    CLOCK_TAGS = ["bloom:PRJ-003"]
    SUITE_OPTION = ["-D", "bud_suite_name=Bench"]
    SUITE_NAME = "Bench"
    BACKEND_OPTION = ["-D", "bud_backend_url=https://bud.example"]
    RUN_ID_OPTION = ["-D", "bud_test_run_id=7"]
    RUN_ID = 7
    RUN_BEHAVE = [
        "run-behave",
        "--no-upload",
        "--test-run-id",
        "5",
        "--suite-name",
        "Bench",
        "features/",
        "--tags=@smoke",
    ]
    PASSED_ON = ["bud_test_run_id=5", "bud_suite_name=Bench", "bud_upload=false"]
    BEHAVE_TAIL = ["features/", "--tags=@smoke"]
    PROGRESS = ["run-behave", "--no-upload", "-f", "progress", "features/"]
    PROGRESS_TAIL = ["-f", "progress", "features/"]
    FAILED = 1
    OK = 0
    REFUSED = 2
    ONE = 1


class RunTestsUpload:
    """Values of the run_tests_upload suite."""

    PASSING_CLASS = "VoltageTest"
    PASSING = [("bud_a", True), ("bud_b", True), ("bud_c", True)]
    MIXED_CLASS = "BetaTest"
    MIXED = [("bud_one", True), ("bud_two", False)]
    CHECK_TEXT = "ok"
    ROWS = 3
    REPORT = "<testsuites/>"
    PAYLOAD = {"results": [{"test_class": "VoltageTest", "test_method": "bud_a"}]}
    RUN_ID = 42
    FAILED_RUN_ID = 7
    COMPLETED = "Completed"
    COUNTERS = ("total_tests", "passed_tests", "failed_tests")
    SOFTWARE = {
        "url_test_software": "https://github.com/example/test-suite",
        "ref_test_software": "tests-abc123",
        "url_software_under_test": "https://github.com/example/firmware",
        "ref_software_under_test": "fw-abc123",
    }
    SOFTWARE_OPTIONS = [
        "--url-test-software",
        "https://github.com/example/test-suite",
        "--ref-test-software",
        "tests-abc123",
        "--sw-under-test",
        "https://github.com/example/firmware",
        "--ref-sw-under-test",
        "fw-abc123",
    ]
    TEST_SOFTWARE = {
        "url_test_software": "https://github.com/example/repo",
        "ref_test_software": "abc123",
    }
    TEST_SOFTWARE_OPTIONS = [
        "--url-test-software",
        "https://github.com/example/repo",
        "--ref-test-software",
        "abc123",
    ]
    PENDING = '{"results":[{"test_class":"PendingTest","test_method":"bud_pending"}]}'
    PENDING_CLASS = "PendingTest"
    UNAVAILABLE = 503
    SERVER_ERROR = 500
    OK = 0
    FAILED = 1
    ONE = 1
    TWO = 2
    NONE = 0
