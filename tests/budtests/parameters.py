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
