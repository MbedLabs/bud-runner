# bud_runner

`bud_runner` is the command-line execution agent for Bud TMP. It runs trusted
Python test suites, emits CI-friendly reports, uploads results to Bud, and can
operate as a long-lived registered runner daemon.

Creator: Amine El Omari

## What it does

- Runs test case lists from local automation or CI.
- Produces JUnit XML, JSON, or text output.
- Creates and updates Bud test runs.
- Uploads test results and artifacts to Bud.
- Registers persistent runner identities.
- Runs a heartbeat and local control daemon.
- Spools failed result uploads for later retry.

## Installation

```bash
python -m pip install bud-runner budtestlibrary
```

Requirements:

- Python 3.9 or later;
- `budtestlibrary`;
- a Bud backend for registration, test-run creation, or result upload.

The package can execute tests and generate local reports without Bloom. Bloom is
not a direct dependency of `bud_runner`.

## Trusted-code execution model

`bud_runner` imports and executes Python test code from the selected local
workspace. Only run test modules you trust. Test code can access files, the
network, subprocesses, and any credentials available to the runner account.

Each discovered test class runs in a separate spawned operating-system process.
Per-test and global suite timeouts limit hangs, but process isolation is not a
security sandbox.

The daemon control socket binds to `127.0.0.1` by default. Do not expose it to an
untrusted network. Non-loopback binding requires an external protection layer.

## Quick start

### Run tests locally

```bash
python -m bud_runner run-tests \
  --test-case-list <Module.ClassName> \
  --output report_junit.xml \
  --no-upload
```

### Run and upload results

```bash
python -m bud_runner run-tests \
  --test-case-list <Module.ClassName> \
  --backend-url "https://<your-bud-instance-url>" \
  --username "ci-user@example.com" \
  --password "<bud-password>" \
  --upload
```

If an upload returns `401 Unauthorized` and credentials were supplied,
`bud_runner` logs in again through the Bud authentication API, refreshes the
cached user token, and retries once.

### Create a Bud test run

```bash
python -m bud_runner add-test-run \
  --test-case-list <Module.ClassName> \
  --test-suite-name "Nightly Automated Tests" \
  --url-test-software https://github.com/org/tests.git \
  --ref-test-software main \
  --sw-under-test https://github.com/org/product.git \
  --ref-sw-under-test release-2026.07
```

### Register a runner

```bash
export RUNNER_API_KEY="<registration-secret>"
export BUD_BACKEND_URL="https://<your-bud-instance-url>"

python -m bud_runner register \
  --username "lab-station-01" \
  --socket-port 53035
```

Runner identity, tokens, and daemon state are stored under `~/.bud/`. Keep that
directory private to the runner account and never commit it.

### Start the daemon

```bash
python -m bud_runner daemon \
  --username "lab-station-01" \
  --location "Hardware Lab" \
  --bind-host 127.0.0.1
```

Run the daemon under a service manager such as systemd, launchd, or a Windows
service wrapper.

## Configuration

Environment variables:

```bash
export BUD_BACKEND_URL="https://<your-bud-instance-url>"
export BUD_TOKEN="<user-token>"
export BUD_RUNNER_ACCOUNT="lab-station-01"
export BUD_RUNNER_TOKEN="<runner-token>"
export RUNNER_API_KEY="<registration-secret>"
```

Project-level, non-secret context can be stored in `app.properties`:

```properties
budBackend=https://<your-bud-instance-url>
budRunnerAccount=lab-station-01
```

Do not put passwords, user tokens, runner tokens, or registration secrets in
`app.properties`.

## Main commands

| Command | Purpose |
|---|---|
| `run-tests` | Execute tests, generate reports, and optionally upload results |
| `list-tests` | Resolve and list discovered tests without executing them |
| `add-test-run` | Create a Bud test run |
| `register` | Register or re-register a runner identity |
| `daemon` | Run heartbeat and local control services |
| `status` | Show local configuration, versions, and Bud health |
| `version` | Print the installed package version |

Run `python -m bud_runner <command> --help` for complete options.

## CI example

```yaml
name: Run tests

on:
  push:
    branches: [main]

jobs:
  test:
    runs-on: self-hosted
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python -m pip install bud-runner budtestlibrary
      - name: Execute tests
        env:
          BUD_BACKEND_URL: ${{ secrets.BUD_BACKEND_URL }}
          BUD_TOKEN: ${{ secrets.BUD_TOKEN }}
        run: |
          python -m bud_runner run-tests \
            --test-case-list <Module.ClassName> \
            --ref-test-software ${{ github.sha }} \
            --output report_junit.xml
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: test-results
          path: report_junit.xml
```

## Licence

`bud_runner` is permanent free and open-source software licensed under the
**GNU Affero General Public License v3.0 only (`AGPL-3.0-only`)**.

No paid EmbedLabs licence is required to use `bud_runner`, including for
commercial use, provided the AGPL terms are followed. Accepted community
contributions remain publicly available under `AGPL-3.0-only` and will not
become proprietary-only.

Bud and Bloom are separate source-available applications. Commercial licensing,
deployment, integration, and support offered through `sales@embedlabs.de`
applies to those applications and services—not to the `bud_runner` package
licence.

Technical, security, and contribution questions: `dev@embedlabs.net`.

Copyright (C) 2026 Mohamed Amine El Omari Alaoui, operating under the name
EmbedLabs.

See [`LICENSE`](LICENSE), [`CONTRIBUTING.md`](CONTRIBUTING.md), and
[`CLA.md`](CLA.md).
