# bud_runner

CLI tool for test execution and CI/CD integration with bud.embedlabs.de.

## Overview

`bud_runner` provides command-line interface for:
- Creating and managing test runs
- Executing test suites
- Generating JUnit XML reports for CI/CD
- Syncing test cases to Bloom ALM
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

The backend protects `POST /api/runners/register` with a shared secret
(`X-API-Key`). Export `RUNNER_API_KEY` (must match the backend's
`RUNNER_API_KEY` env var) before running `register`, or pass `--api-key`:

```bash
export RUNNER_API_KEY=...  # shared secret from the Bud backend
export BUD_BACKEND_URL=https://bud.embedlabs.de

python -m bud_runner register \
    --username my-runner \
    --password mypassword \
    --socket-port 53035
```

### Sync to Bloom ALM

```bash
python -m bud_runner sync_test_cases \
    --project bms-project \
    --test-case-list Bud_Test_Suite.HIL_TEST_CASES \
    --suite-name "HIL Tests" \
    --bloom-token "your-jwt-token"

# Or authenticate with email/password
python -m bud_runner sync_test_cases \
    --project bms-project \
    --test-case-list Bud_Test_Suite.HIL_TEST_CASES \
    --suite-name "HIL Tests" \
    --bloom-email admin@embedlabs.de \
    --bloom-password yourpassword
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
  -o, --output, --junit-report PATH  JUnit XML output [default: report_junit.xml]
  -f, --format [json|text|junit]  Output format [default: junit]
  --continue-on-error/--stop-on-error  Continue after failure [default: continue]
  -b, --backend-url TEXT       Backend URL for upload
  --test-run-id INT            Associate uploaded results with this TestRun id
  --bud-token TEXT             User JWT (falls back to BUD_TOKEN env)
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
  --api-key TEXT               Shared secret sent as X-API-Key.
                               Falls back to RUNNER_API_KEY env var.
```

### `sync_test_cases`

Sync test cases to Bloom ALM.

```bash
python -m bud_runner sync_test_cases [OPTIONS]

Options:
  -p, --project TEXT           Bloom project prefix or ID (required)
  -t, --test-case-list TEXT    Test case list module path (required)
  -s, --suite-name TEXT        Test campaign name (required)
  --bloom-url TEXT             Bloom ALM URL
  --bloom-token TEXT           Bloom ALM JWT token
  --bloom-email TEXT           Bloom ALM login email
  --bloom-password TEXT        Bloom ALM login password
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
export BLOOM_URL="https://bloom.embedlabs.de/"
export BLOOM_TOKEN="bloom-jwt-token"
export BLOOM_EMAIL="user@embedlabs.de"
export BLOOM_PASSWORD="your-password"

# Required for `bud_runner register` only — NOT needed for normal API calls.
export RUNNER_API_KEY="shared-runner-registration-secret"
```

### app.properties

```properties
budBackend=https://bud.embedlabs.de/
budRunnerAccount=my-runner
budRunnerToken=xxx
bloomUrl=https://bloom.embedlabs.de/
bloomToken=xxx
bloomEmail=user@embedlabs.de
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

This project is licensed under the **GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)**. See the [LICENSE](LICENSE) file for the full text.

Copyright (C) 2024-2026 EmbedLabs.

For commercial licensing options that do not require AGPL compliance, contact dev@embedlabs.de. Contributions are accepted under the [CLA](CLA.md) — see [CONTRIBUTING.md](CONTRIBUTING.md).
