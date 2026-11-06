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
