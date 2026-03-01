# bud_runner

CLI tool for test execution and CI/CD integration with bud.embedlabs.de.

## Overview

`bud_runner` provides command-line interface for:
- Creating and managing test runs
- Executing test suites
- Generating JUnit XML reports for CI/CD
- Syncing test cases to OpenProject
- Runner registration and management

## Installation

### From GitHub (submodule)

```bash
git submodule add https://github.com/embedlabs/bud_runner.git
pip install -e ./bud_runner
```

### From pip.embedlabs.de (coming soon)

```bash
pip install bud_runner --index-url https://pip.embedlabs.de/simple
```

## Prerequisites

- `budtestlibrary` must be installed
- Python 3.9+

## Quick Start

### Run Tests

```bash
# Run tests and generate JUnit report
python -m bud_runner run_tests \
    --test-case-list Bud_Test_Suite.HIL_TEST_CASES \
    --output report_junit.xml

# With result upload
python -m bud_runner run_tests \
    --test-case-list Bud_Test_Suite.HIL_TEST_CASES \
    --backend-url https://bud.embedlabs.de/ \
    --upload
```

### Create Test Run

```bash
python -m bud_runner add_test_run \
    --test-case-list Bud_Test_Suite.HIL_TEST_CASES \
    --test-suite-name "Nightly HIL Tests" \
    --url-test-software https://github.com/org/repo.git \
    --ref-test-software main
```

### Register Runner

```bash
python -m bud_runner register \
    --username my-runner \
    --password mypassword \
    --socket-port 53035
```

### Sync to OpenProject

```bash
python -m bud_runner sync_test_cases \
    --project bms-project \
    --test-case-list Bud_Test_Suite.HIL_TEST_CASES \
    --suite-name "HIL Tests"
```

## Commands

### `add_test_run`

Create a new test run on bud.embedlabs.de.

```bash
python -m bud_runner add_test_run [OPTIONS]

Options:
  -t, --test-case-list TEXT    Test case list module path (required)
  -n, --test-suite-name TEXT   Name for the test run (required)
  --url-test-software TEXT     Repository URL
  --ref-test-software TEXT     Git ref [default: main]
  --product-composition-id INT Product ID [default: 1]
  --status TEXT                Initial status [default: Running]
  -b, --backend-url TEXT       Backend URL
  -u, --username TEXT          Username
  --bud-token TEXT             API token
```

### `run_tests`

Execute tests from a test case list.

```bash
python -m bud_runner run_tests [OPTIONS]

Options:
  -t, --test-case-list TEXT    Test case list module path (required)
  -o, --output PATH            JUnit XML output [default: report_junit.xml]
  -f, --format [json|text|junit]  Output format [default: junit]
  --continue-on-error/--stop-on-error  Continue after failure [default: continue]
  -b, --backend-url TEXT       Backend URL for upload
  --upload/--no-upload         Upload results [default: upload]
```

### `register`

Register this machine as a test runner.

```bash
python -m bud_runner register [OPTIONS]

Options:
  -u, --username TEXT          Runner account (required)
  -p, --password TEXT          Password (prompted if not provided)
  -b, --backend-url TEXT       Backend URL
  --socket-port INT            Socket port [default: 53035]
```

### `sync_test_cases`

Sync test cases to OpenProject Work Packages.

```bash
python -m bud_runner sync_test_cases [OPTIONS]

Options:
  -p, --project TEXT           OpenProject project ID (required)
  -t, --test-case-list TEXT    Test case list module path (required)
  -s, --suite-name TEXT        Test suite name (required)
  --pm-url TEXT                OpenProject URL
  --pm-token TEXT              OpenProject API token
  --dry-run                    Preview without making changes
```

### `status`

Show runner status and connectivity.

```bash
python -m bud_runner status [OPTIONS]

Options:
  -b, --backend-url TEXT       Backend URL
```

### `version`

Show bud_runner version.

```bash
python -m bud_runner version
```

## Configuration

### Environment Variables

```bash
export BUD_BACKEND_URL="https://bud.embedlabs.de/"
export BUD_TOKEN="your-api-token"
export BUD_RUNNER_ACCOUNT="my-runner"
export BUD_RUNNER_TOKEN="runner-token"
export PM_URL="https://pm.embedlabs.de/"
export PM_TOKEN="openproject-token"
```

### app.properties

```properties
budBackend=https://bud.embedlabs.de/
budRunnerAccount=my-runner
budRunnerToken=xxx
pmUrl=https://pm.embedlabs.de/
pmToken=xxx
runnerSocketPort=53035
```

## GitHub Actions Integration

```yaml
name: Run Tests

on:
  push:
    branches: [main]
  schedule:
    - cron: '0 2 * * *'  # Nightly at 2 AM

jobs:
  test:
    runs-on: self-hosted
    steps:
      - uses: actions/checkout@v4
      
      - name: Install dependencies
        run: |
          pip install -e ./budtestlibrary
          pip install -e ./bud_runner
      
      - name: Run tests
        env:
          BUD_BACKEND_URL: ${{ secrets.BUD_BACKEND_URL }}
          BUD_TOKEN: ${{ secrets.BUD_TOKEN }}
        run: |
          python -m bud_runner run_tests \
            --test-case-list Bud_Test_Suite.HIL_TEST_CASES \
            --output report_junit.xml
      
      - name: Upload test results
        uses: actions/upload-artifact@v4
        with:
          name: test-results
          path: report_junit.xml
      
      - name: Publish test report
        uses: mikepenz/action-junit-report@v4
        if: always()
        with:
          report_paths: 'report_junit.xml'
```

## License

MIT License - Copyright (c) 2025 EmbedLabs
