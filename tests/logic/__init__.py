"""The bud-runner suites of tests/logic, as bud-runner run-tests -t tests.logic.SUITES runs them."""

SUITES = [
    "tests.logic.auth.Auth",
    "tests.logic.behave_formatter.BehaveFormatter",
    "tests.logic.cli_signals.CliSignals",
    "tests.logic.cucumber_importer.CucumberImporter",
    "tests.logic.executor.Executor",
    "tests.logic.flatten_results.FlattenResults",
    "tests.logic.packaging_metadata.PackagingMetadata",
    "tests.logic.pytest_plugin.PytestPlugin",
    "tests.logic.reporting.Reporting",
    "tests.logic.robot_listener.RobotListener",
    "tests.logic.station_naming.StationNaming",
    "tests.logic.verbose.Verbose",
]
