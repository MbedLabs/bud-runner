# bud_runner

`bud_runner` is the command-line runner for Bud TMP. It executes Python-based
test suites, emits CI-friendly reports, uploads results to Bud, and manages a
runner machine identity for long-lived daemon use.

Creator: Amine El Omari

`bud_runner` is designed to run on machines you manage, such as self-hosted CI
runners and dedicated lab hosts.

## What It Does

`bud_runner` is designed for:
- running test case lists from CI or local automation
- generating JUnit XML for CI systems
- creating and updating Bud test runs
- uploading test results to Bud TMP
- registering and operating a persistent runner daemon

## Identity & Security

Bud Runner uses a **split-configuration** architecture to prevent secret tokens from being committed to your repositories.

1.  **Global Identity Vault**: Secret tokens and daemon settings are stored locally on your machine in `~/.bud/config.json`.
2.  **Project Context**: Non-sensitive project metadata (account name, backend URL) is stored in your repository's `app.properties`.

### Trusted-Code Execution Model

**`bud_runner` imports and executes Python test code from your local workspace.**
This is by design — the runner relies on `importlib` to discover and run test
classes. Because of this architecture:

- **Only run trusted test code.** Do not point `bud_runner` at test modules from
  untrusted sources. A malicious test class can execute arbitrary code on the
  runner host (file access, network calls, shell commands).
- **Isolation per test class.** Each test class runs in a *separate OS process*
  spawned with `multiprocessing.get_context("spawn")`. A crash or hang in one
  test does not corrupt state in another. Per-test timeouts (default 5 min) and
  a global suite timeout (default 30 min) prevent unbounded execution.
- **Runner vs. daemon trust boundary.** The CLI commands (`run-tests`,
  `add-test-run`, `register`) are trusted tools that you invoke directly. The
  daemon (`bud_runner daemon`) responds to socket commands and should only be
  exposed to localhost or a trusted network layer.

### Daemon Socket Model

`bud_runner daemon` binds its control socket to `127.0.0.1` by default.
Remote socket exposure is not a supported feature unless you deliberately
override the bind host and add your own external protection layer.

Use the explicit override only when you understand the risk:

```bash
python -m bud_runner daemon --bind-host 127.0.0.1
```

Until the socket protocol has authentication, do not treat non-loopback daemon
binding as a public or LAN-safe deployment mode.

## Installation

Install `bud_runner` from the package index:

```bash
pip install bud-runner
```

## Prerequisites

- `budtestlibrary` must be installed
- Python 3.9+
- A running Bud backend (local dev default: `http://localhost:8000`)

When no `budBackend` / `BUD_BACKEND_URL` is set, `AuthManager` defaults to
`http://localhost:8000`. Override with `--backend-url` or `export BUD_BACKEND_URL=...`
for remote instances.

## Quick Start

The usual flow is:
1. Install `bud_runner` and `budtestlibrary`
2. Point the runner at a Bud backend
3. Run tests directly, or register a daemon-backed runner identity

### Run Tests

```bash
# Run tests and generate JUnit report
python -m bud_runner run-tests \
    --test-case-list <Module.ClassName> \
    --output report_junit.xml

# With result upload to Bud TMP
python -m bud_runner run-tests \
    --test-case-list <Module.ClassName> \
    --backend-url "https://<your-bud-instance-url>/" \
    --username "ci-user@example.com" \
    --password "<bud-password>" \
    --upload
```

If an upload returns `401 Unauthorized` and you provided `--username` plus
`--password`, `bud_runner` will log in again via the Bud auth API, refresh the
cached user token in `~/.bud/config.json`, and retry the upload once.

### Create a Test Run

```bash
python -m bud_runner add-test-run \
    --test-case-list <Module.ClassName> \
    --test-suite-name "Nightly Automated Tests" \
    --url-test-software https://github.com/org/repo.git \
    --ref-test-software main \
    --sw-under-test https://github.com/org/firmware.git \
    --ref-sw-under-test release-2026.06
```

### Register a Runner Identity

The backend protects registration with a shared secret (`X-API-Key`).
Identity and tokens are saved to a global machine vault (`~/.bud/config.json`).

```bash
export RUNNER_API_KEY="<your-backend-shared-secret>"
export BUD_BACKEND_URL="https://<your-bud-instance-url>"

python -m bud_runner register \
    --username "my-runner" \
    --socket-port 53035
```

If `--password` is omitted, `bud_runner` generates one during registration and
prints it once so the registrant can save it securely.

If the runner is already registered on this machine, use `--re-register` with
the existing password to refresh the token or update socket settings safely.

### Project Linking

To associate a project with a registered runner, add the following to its
`app.properties`. Keep secrets out of the repository.

```properties
budRunnerAccount=my-runner
budBackend=https://<your-bud-instance-url>
```


## Command Reference

### `add-test-run`

Create a new test run on the Bud platform.

```bash
python -m bud_runner add-test-run [OPTIONS]

Options:
  -t, --test-case-list TEXT    Test case list module path (required)
  -n, --test-suite-name TEXT   Name for the test run (required)
  --url-test-software, --url-test-sw TEXT
                               Test software repository URL
  --ref-test-software, --ref-test-sw TEXT
                               Test software git ref [default: main]
  --sw-under-test TEXT         Software-under-test repository URL
  --ref-sw-under-test TEXT     Software-under-test git ref
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
  -u, --username TEXT          Bud user email for token refresh during uploads
  --password TEXT              Bud user password for token refresh during uploads
  --test-run-id INT            Associate uploaded results with this TestRun id
  --url-test-software, --url-test-sw TEXT
                               Test software repository URL for auto-created runs
  --ref-test-software, --ref-test-sw TEXT
                               Test software git ref for auto-created runs
  --sw-under-test TEXT         Software-under-test repository URL for auto-created runs
  --ref-sw-under-test TEXT     Software-under-test git ref for auto-created runs
  --bud-token TEXT             User JWT (falls back to BUD_TOKEN env)
  --upload/--no-upload         Upload results [default: upload]
```

If result upload fails after the test run completes, `bud_runner` exits non-zero
and spools the serialized payload under `~/.bud/spool/results/` for replay on
the next successful `run-tests` invocation. If the home directory is not
writable, it falls back to a temp-directory spool path for that machine.

### `list-tests`

Resolve a test case list without executing the tests.

```bash
python -m bud_runner list-tests [OPTIONS]

Options:
  -t, --test-case-list TEXT    Test case list module path (required)
  --output-format [json|text]  Output format [default: text]
```

### `register`

Register this machine as a test runner.

```bash
python -m bud_runner register [OPTIONS]

Options:
  -u, --username TEXT          Runner account (required)
  -p, --password TEXT          Password for registration (auto-generated if omitted)
  -b, --backend-url TEXT       Backend URL
  --socket-port INT            Socket port [default: 53035]
  --api-key TEXT               Shared secret sent as X-API-Key.
                               Falls back to RUNNER_API_KEY env var.
  --re-register                Refresh an existing local runner registration
```


### `status`

Show runner configuration, backend health, and versions.

```bash
python -m bud_runner status [OPTIONS]

Options:
  -b, --backend-url TEXT       Backend URL (default: http://localhost:8000)
  --output-format [json|text]  Output format [default: text]
```

Reports backend URL, token presence, runner account, package version, and
`GET /api/health` + `GET /api/version` when the backend is reachable. When a
runner identity is configured, status also includes the registered socket port
and backend runner-status details. Use `--output-format json` in CI.

### `daemon`

Start the long-lived runner daemon (heartbeat plus local control socket).

```bash
python -m bud_runner daemon [OPTIONS]

Options:
  -u, --username TEXT          Runner account loaded from ~/.bud/config.json
  -b, --backend-url TEXT       Backend URL
  -i, --interval INT           Heartbeat interval in seconds [default: 60]
  -p, --port INT               Socket listener port (defaults to the registered port)
  --bind-host TEXT             Socket bind host [default: 127.0.0.1]
  -l, --location TEXT          Human-readable runner location
```

### `version`

Show bud_runner version.

```bash
python -m bud_runner version
```

### Shell completion

Typer shell completion is enabled. Install it with:

```bash
bud-runner --install-completion
```

## Configuration

### Environment Variables

```bash
# Optional for local dev — defaults to http://localhost:8000 when unset
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
```

`app.properties` must contain project metadata only. Never store
`budRunnerToken`, `runnerApiKey`, `budToken`, or passwords in the repository;
runner secrets and daemon port state belong in `~/.bud/config.json` or
environment variables.

## CI Integration

Use `bud_runner` in CI when you want machine-readable JUnit output plus optional
result upload back to Bud TMP. The intended deployment model is self-hosted CI
where you control the runner host, installed test code, and local machine
secrets.

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
          pip install budtestlibrary
          pip install bud-runner
      
      - name: Run tests
        env:
          BUD_BACKEND_URL: ${{ secrets.BUD_BACKEND_URL }}
          BUD_TOKEN: ${{ secrets.BUD_TOKEN }}
        run: |
          python -m bud_runner run-tests \
            --test-case-list <Module.ClassName> \
            --url-test-software https://github.com/my-org/my-test-repo \
            --ref-test-software ${{ github.sha }} \
            --sw-under-test https://github.com/my-org/my-firmware-repo \
            --ref-sw-under-test ${{ github.ref_name }} \
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

Each runner will have its own independent PID and log files under `~/.bud/daemons/`, prefixed with `bud_<username>`.

Daemon log files are newline-delimited JSON records with `timestamp`, `level`,
`logger`, and `message` fields so they can be parsed by log shippers or basic
CLI tooling.

## Service Deployment

`bud_runner daemon` is intended to run under a service manager on a machine you
control.

- Linux/systemd: run the daemon under a dedicated service account and keep
  `~/.bud/config.json` owned by that account.
- macOS/launchd: run the same daemon command under a LaunchAgent or
  LaunchDaemon, depending on whether the runner is user-scoped or machine-scoped.
- Windows: run the daemon behind a service wrapper such as NSSM or WinSW and
  keep the Bud config directory private to that service identity.

## License

This project is licensed under the **GNU Affero General Public License v3.0
(AGPL-3.0)**. Full license text: https://www.gnu.org/licenses/agpl-3.0.html

Copyright (C) 2026 EmbedLabs.

For commercial licensing options that do not require AGPL compliance, contact dev@embedlabs.net. For support or private-source collaboration, email dev@embedlabs.net.
