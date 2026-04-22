# bud_runner

CLI tool for test execution and CI/CD integration with the **Bud Test Platform**.

## Overview

`bud_runner` provides a command-line interface for:
- Registering machines as Bud test runners
- Creating and managing test runs
- Executing Python-based test suites and reporting results
- Generating JUnit XML reports for CI/CD

## Installation

```bash
pip install bud_runner
```

## Getting Started

### 1. Register the Runner
Register your machine with the Bud backend to obtain an identity token.

```bash
python -m bud_runner register \
    --username your-runner-name \
    --password your-secret-password \
    --backend-url https://<your-bud-instance-url>
```

### 2. Add a Test Run
Before executing tests, create a run record to track results.

```bash
python -m bud_runner add-test-run \
    --test-suite-name "Standard Test Suite" \
    --test-case-list "YourModule.TEST_CASE_LIST"
```

### 3. Run Tests
Execute the tests and upload results to the dashboard.

```bash
python -m bud_runner run_tests \
    --test-case-list "YourModule.TEST_CASE_LIST" \
    --test-run-id <run-id> \
    --junit-report report.xml
```

## Configuration

`bud_runner` looks for configuration in:
1. Command line options (e.g., `--backend-url`)
2. Environment variables (e.g., `BUD_BACKEND_URL`, `BUD_TOKEN`)
3. Local `app.properties` file

### Example `app.properties`
```properties
budBackend=https://<your-bud-instance-url>
budRunnerAccount=your-runner-name
```

## License

Copyright (c) 2026 EmbedLabs. All rights reserved.
