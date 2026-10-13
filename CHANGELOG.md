# Changelog

All notable changes to `bud_runner` will be documented in this file.

## [Unreleased]

### Added
- `run-robot` and `bud_runner.robot_listener.BudListener`: a Robot Framework run is reported to Bud. Each test becomes a test case, each library keyword call an entry: a check (a name containing "Should") an assertion named `Assert` plus what it checks (AssertEqual, AssertIn, AssertTrue, AssertEmpty, ...), with expected and actual for BuiltIn's checks; a keyword that checks nothing, or a failure a TRY or Run Keyword And Ignore Error handled, an information entry; a failing or missing keyword a failed entry; `Skip` a skipped entry; each with its .robot file, line and call, and a failure with the call chain as traceback, a `bloom:PRJ-001` tag the Bloom test case `PRJ-TC-001` (the full id is accepted too), SKIP a skipped test; output.xml, log.html and report.html are attached to the run. Robot's exit code is unchanged; a failed upload is spooled. Robot Framework 7 or later, as the `robot` extra.
- `run-pytest` and `bud_runner.pytest_plugin`: a pytest run is reported to Bud. Each test becomes a test case, each `assert` an assertion entry in budtestlibrary's shape: a single comparison named after what it checks (AssertEqual, AssertNotEqual, AssertIn, AssertNotIn, AssertLess, AssertGreater) with expected and actual, anything else AssertTrue with the value pytest displays; a failed assert carries pytest's explanation and traceback, another exception is a failed entry named after its class, a fixture error fails the test, skip and xfail are skipped, a `@pytest.mark.bloom("PRJ-001")` marker the Bloom test case `PRJ-TC-001` (the full id is accepted too). The `bud_assert` fixture offers budtestlibrary's assertion methods with the same arguments and records; a failed check fails the test without stopping it, unless `abort_on_fail=True`, and is the expected failure of an xfail test. `run-pytest` switches on pytest's assertion pass hook with its own bytecode cache, forwards every other argument to pytest and returns its exit code; a failed upload is spooled. pytest 7.0 or later, as the `pytest` extra.
- `run-behave` and `bud_runner.behave_formatter.BudFormatter`: a Behave run is reported to Bud. Each feature becomes a test case and each scenario, Scenario Outline rows included, a result of it; each step an entry named after its text with its .feature file, line and the step as written: a Then step a check and a Given or When step an information entry, a failing or raising step failed with the error and traceback, an undefined step failed with an "Undefined step" message; a hook error fails the scenario with its traceback, a scenario skipped with a reason is skipped, one left out by tag selection is not reported, a `@bloom:PRJ-001` tag the Bloom test case `PRJ-TC-001` (the full id is accepted too). Options as `-D bud_*` userdata. `run-behave` forwards every other argument to behave, keeps Behave's pretty output when no `-f` is given and returns Behave's exit code; a failed upload is spooled. Behave 1.2.6 or later, as the `behave` extra.
- `import-cucumber` and `bud_runner.cucumber_importer`: a Cucumber JSON report from cucumber-js, Cucumber-JVM or Cucumber-Ruby is imported into Bud with the mapping of `run-behave`: each feature a test case, each scenario (Scenario Outline rows included, `(line N)` added to shared names) a result, Background steps the scenario's own; each step an entry named after its text, a Then step a check, a Given or When step an information entry, And, But and `*` the type of the step before; a failing, ambiguous, undefined or pending step failed with the runner's message and stack trace, a failed hook a failed `HookError` entry; a scenario with a skipped step or no steps skipped; a `@bloom:PRJ-001` tag the Bloom test case `PRJ-TC-001`. English step keywords. The report file is attached to the run (`--no-artifacts` to leave it out); exit code 0 when the report reached Bud, 1 when the upload was spooled, 2 for a report that cannot be read or no backend.
- `templates/`: CI jobs for GitHub Actions and GitLab CI, for Python test case lists (`run-tests`) and Robot Framework suites (`run-robot`).
- `update_test_run` takes `skipped_tests`; `upload_results_payload` returns the server's answer, which names the run.

### Changed
- Execution submissions and artifact uploads use the station token when a user session is also configured. A queued selection keeps the backend and station account resolved before entering its test workspace, and the station acknowledges completion after execution and uploads.

### Fixed
- An unavailable selected test class fails the selection before execution instead of being silently skipped and reported as a successful zero-test run.

## [1.1.0] — 2026-09-09

### Changed
- The station takes the name Bud assigned it. An administrator names a Test Station when minting its enrolment key, and that name wins over `--username`: registration now stores what the backend returned rather than what was sent, and a later rename in Bud is adopted on the next heartbeat and written to `~/.bud/`.
- The documentation no longer describes `RUNNER_API_KEY` as a shared secret configured on the backend. Bud stopped accepting a shared key: an administrator mints one enrolment key per station in the interface, it is shown once, and it pins to the first station that registers with it. The variable and the `--api-key` option are unchanged — only what you put in them, and where it comes from.

## [1.0.3] — 2026-08-16

### Added
- Run work queued by the backend for this station
- Upload run artifacts with `--artifact`
- Send the report and remaining files a run leaves behind

### Fixed
- Completed run claims are acknowledged idempotently

### Changed
- Version aligned with `budtestlibrary` 1.0.3, which adds an optional `addr`
  target address to `FlashEvent.flash()` and `FlashEvent.execute()`

## [1.0.2] — 2026-07-22

### Changed
- Package licensing wording now explicitly confirms that `bud_runner` remains free and open source under `AGPL-3.0-only`, including for commercial use subject to AGPL compliance
- Bud and Bloom application licensing is clearly separated from the `bud_runner` package licence
- Contributor terms now guarantee that Accepted Contributions remain publicly available under `AGPL-3.0-only`
- Pull requests now include an explicit CLA acceptance declaration

### Fixed
- README relative-link validation allows `#`-prefixed anchor links supported by PyPI

## [1.0.1] — 2026-07-19

### Changed
- Hardened `.gitignore` with key/cert patterns for public release
- Removed internal hostname from CI workflow step name
- Added PR template for contribution guidelines

## [1.0.0.post2] — 2026-06-28

### Changed
- Package version advanced to `1.0.0.post2` for final public metadata and documentation corrections
- Project URLs now point to `embedlabs.net`
- PyPI README no longer relies on private-repository file links for service deployment guidance

## [1.0.0.post1] — 2026-06-28

### Changed
- Package version advanced to `1.0.0.post1` for a documentation-only PyPI metadata correction
- Package author metadata now credits Amine El Omari
- README now includes creator credit for the published project page

## [1.0.0] — 2026-06-28

### Added
- Stable open-source release packaging for `bud_runner`
- Release metadata regression coverage for version, licence metadata, and changelog presence

### Changed
- Package version advanced to `1.0.0`
- Packaging metadata now uses a PEP 621-compatible licence table
- Release classifier moved from beta to production/stable
