# bud_runner

CLI tool for test execution and CI/CD integration with the Bud platform.

## Overview

`bud_runner` provides a command-line interface for:
- Creating and managing test runs
- Executing test suites
- Generating JUnit XML reports for CI/CD
- Runner registration and management

## Identity & Security

Bud Runner uses a **split-configuration** architecture to prevent secret tokens from being committed to your repositories.

1.  **Global Identity Vault**: Secret tokens and daemon settings are stored locally on your machine in `~/.bud/config.json`.
2.  **Project Context**: Non-sensitive project metadata (account name, backend URL) is stored in your repository's `app.properties`.

## Installation

To use `bud_runner` in your projects, add it as a submodule:

```bash
git submodule add https://github.com/MbedLabs/bud_runner.git
pip install -e ./bud_runner
```

## Prerequisites

- `budtestlibrary` must be installed
- Python 3.9+

## Quick Start

### Run Tests

```bash
# Run tests and generate JUnit report
python -m bud_runner run-tests \
    --test-case-list <Module.ClassName> \
    --output report_junit.xml

# With result upload
python -m bud_runner run-tests \
    --test-case-list <Module.ClassName> \
    --backend-url "https://<your-bud-instance-url>/" \
    --upload
```

### Create Test Run

```bash
python -m bud_runner add-test-run \
    --test-case-list <Module.ClassName> \
    --test-suite-name "Nightly Automated Tests" \
    --url-test-software https://github.com/org/repo.git \
    --ref-test-software main
```

### Register Runner (Machine Identity)

The backend protects registration with a shared secret (`X-API-Key`). 
Identity and tokens are saved to a global machine vault (`~/.bud/config.json`).

> **⚠️ Important: Registration Path & Reregistration**
> Always run the `register` command from the directory where the daemon runs (typically your user's `$HOME` directory or the designated `$WORKSPACE_DIR`). Running it from a sub-directory containing its own `app.properties` can cause the daemon to read a stale token from a higher-level `app.properties` (shadowing the newly updated vault). If you are reregistering an existing runner, you must use its original password.

```bash
export RUNNER_API_KEY="<your-backend-shared-secret>"
export BUD_BACKEND_URL="https://<your-bud-instance-url>"

python -m bud_runner register \
    --username "my-runner" \
    --password "mypassword" \
    --socket-port 53035
```

### Project Linking

To link a repository to a registered runner, add the following to its
`app.properties`. No secret tokens are stored in the repo.

```properties
budRunnerAccount=my-runner
budBackend=https://<your-bud-instance-url>
runnerSocketPort=53035
```


## Commands

### `add-test-run`

Create a new test run on the Bud platform.

```bash
python -m bud_runner add-test-run [OPTIONS]

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

### `run-tests`

Execute tests from a test case list.

```bash
python -m bud_runner run-tests [OPTIONS]

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
export BUD_BACKEND_URL="https://<your-bud-instance-url>/"
export BUD_TOKEN="your-api-token"
export BUD_RUNNER_ACCOUNT="my-runner"
export BUD_RUNNER_TOKEN="runner-token"

# Required for `bud_runner register` only — NOT needed for normal API calls.
export RUNNER_API_KEY="shared-runner-registration-secret"
```

### app.properties

```properties
budBackend=https://<your-bud-instance-url>/
budRunnerAccount=my-runner
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
          python -m bud_runner run-tests \
            --test-case-list <Module.ClassName> \
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

## Multi-Runner Support

You can run multiple runners on the same machine by using unique usernames and ports:

```bash
# Runner 01
python -m bud_runner register --username "runner-01" --socket-port 53035
# Runner 02
python -m bud_runner register --username "runner-02" --socket-port 53036
```

Each runner will have its own independent logs and PID file in the current directory, prefixed with `bud_<username>`.

## License

This project is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**. See the [LICENSE](LICENSE) file for the full text.

Copyright (C) 2026 EmbedLabs.

For commercial licensing options that do not require AGPL compliance, contact dev@embedlabs.net. Contributions are accepted under the [CLA](CLA.md) — see [CONTRIBUTING.md](CONTRIBUTING.md).
