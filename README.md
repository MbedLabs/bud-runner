# bud_runner

`bud_runner` is the command-line execution agent for Bud TMP. It runs trusted
Python test suites, emits CI-friendly reports, uploads results to Bud, and can
operate as a long-lived registered runner daemon.

Creator: Amine El Omari

`bud_runner` is designed for machines you manage, including dedicated lab hosts
and self-hosted CI runners.

## What it does

- Runs test case lists from local automation or CI.
- Produces JUnit XML, JSON, or text output.
- Creates and updates Bud test runs.
- Uploads test results and artifacts to Bud.
- Runs work the backend has queued for a test station.
- Registers persistent runner identities.
- Runs a heartbeat and local control daemon.
- Spools failed result uploads for later retry.

## Compatibility

| `bud_runner` | Intended `budtestlibrary` pairing | Notes |
|---|---|---|
| `1.1.0` | `1.1.0` | Updated compatibility matrix |
| `1.0.3` | `1.0.3` | Backend-queued runs, `--artifact` uploads, optional `addr` on `FlashEvent` |
| `1.0.2` | `1.0.2` | Multipart artifact uploads and formatting fixes |
| `1.0.1` | `1.0.1` | Timeout fixes and PyPI release structure |

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

Register the Test Station with its enrolment key first, as described below. Registration
stores the station token used to create runs and submit execution results.

```bash
python -m bud_runner run-tests \
  --test-case-list <Module.ClassName> \
  --backend-url "https://<your-bud-instance-url>" \
  --username "ci-user@example.com" \
  --password "<bud-password>" \
  --upload
```

Run creation, execution updates and raw result uploads use the station's credentials.
The client selects the station token for execution submissions and artifact uploads
when a user session is also configured. Result
uploads can also use an enrolment key already bound to that station.

### Upload artifacts with the results

`--artifact` (`-A`) takes a file path or glob and is repeatable. Matching files
are uploaded alongside the results, so logs, captures, and reports stay attached
to the run:

```bash
python -m bud_runner run-tests \
  --test-case-list <Module.ClassName> \
  --artifact "logs/*.log" \
  --artifact capture.png \
  --upload
```

A file that fails to upload is reported but does not fail the run.

### Run work queued by Bud

`claim-run` asks the backend for this station's next queued run and executes it
through the same path as any other run. With `--interval 0` (the default) it
claims once and exits, which suits a cron entry or a one-shot CI job; a non-zero
interval polls continuously:

```bash
python -m bud_runner claim-run \
  --backend-url "https://<your-bud-instance-url>" \
  --username "station-01@example.com" \
  --workspace ./tests \
  --interval 30 \
  --artifact "logs/*.log"
```

`--workspace` points at the directory holding this station's test modules and
defaults to the current directory. `--test-timeout` and `--suite-timeout` cap a
single test and the full suite, at 300 and 1800 seconds respectively.

Registration must supply a station token, either stored locally or provided as
`BUD_RUNNER_TOKEN`. The backend and station account resolved from `app.properties`
remain available to the child execution when `--workspace` changes its directory.
Only the selected classes run. If a selected class cannot be imported, execution
fails before running any class and reports the failure to Bud. Result upload does
not release the station's claim; the final completion acknowledgement does.

### Report a Robot Framework run

`run-robot` runs Robot Framework with the Bud listener attached; every argument
it does not know goes to `robot` unchanged, and Robot's exit code is returned.
Install the extra first: `python -m pip install "bud-runner[robot]"`.

```bash
python -m bud_runner run-robot \
  --backend-url "https://<your-bud-instance-url>" \
  --outputdir robot-results \
  --include smoke \
  tests/
```

Each Robot test becomes one Bud test case (its full name as the test class, its
name as the method); SKIP counts as skipped. Each library keyword call
inside a test becomes one entry: a check (a library keyword whose name contains
"Should") is an assertion named `Assert` plus what it checks (`AssertEqual`,
`AssertIn`, `AssertTrue`, `AssertEmpty`, ...), with expected and actual for BuiltIn's
checks; a keyword that checks nothing, such as `Log`, or a failure that a TRY or a
keyword such as `Run Keyword And Ignore Error` handled, is an information entry; a
keyword that fails, or is not found, is a failed entry; `Skip` is a skipped entry. Each entry carries its .robot file, line and call,
and a failure the Robot call chain as its traceback. A `bloom:<project>-<number>` tag such as `bloom:PRJ-001`
links the result to that Bloom test case (`PRJ-TC-001`; the full id is accepted too); tests without one are shown in Bud and
not synced. output.xml, log.html and report.html are attached to the run. A
failed upload is spooled and replayed by the next bud-runner command.

The listener also works on an existing `robot` command:
`robot --listener bud_runner.robot_listener.BudListener tests/`. Like `run-tests`,
it reads the backend, the station and the product from `app.properties`
(`budBackend`, `budRunnerAccount`, `productId`) and the `BUD_*` environment, so Bud
names the run `<product> - <root suite>`. Listener arguments override them:
`backend`, `product_id`, `suite_name`, `test_run_id`, `ref_sw_under_test`,
`upload=false`, `artifacts=false`, separated by semicolons so a URL's colons are
kept (`BudListener;backend=https://bud.example`).

### Report a pytest run

`run-pytest` runs pytest with the Bud plugin attached; every argument it does not
know goes to `pytest` unchanged, and pytest's exit code is returned. Install the
extra first: `python -m pip install "bud-runner[pytest]"` (pytest 7.0 or later).

```bash
python -m bud_runner run-pytest \
  --backend-url "https://<your-bud-instance-url>" \
  tests/ -k smoke
```

Each pytest test becomes one Bud test case (its node id as the test class, its name
as the method). Every `assert` in a test module or `conftest.py` becomes one
assertion entry in the shape budtestlibrary sends: a single comparison is named
after what it checks (`==` AssertEqual, `!=` AssertNotEqual, `in` AssertIn,
`not in` AssertNotIn, `<` AssertLess, `>` AssertGreater) with its expected and
actual values, any other expression is AssertTrue with the value as pytest displays
it as its actual (pytest shortens long values unless run with `-vv`), or the boolean
for `not`, `and`, `or` and other comparisons. A failed assert carries pytest's
explanation as its message and pytest's traceback; any other exception is a failed
entry named after its class; a fixture error fails the test; `pytest.skip` and
xfail are skipped. Mark a test with `@pytest.mark.bloom("PRJ-001")` to link it to
the Bloom test case `PRJ-TC-001` (the full id is accepted too); tests without the marker are shown in Bud and not synced.

The `bud_assert` fixture offers budtestlibrary's assertion methods with the same
arguments (`assertEqual`, `assertNotEqual`, `assertIn`, `assertNotIn`, `assertTrue`,
`assertFalse`, `assertGreater`, `assertLess`, `assertInRange`, `assertInTolerance`,
`assertRegex`, `skipAssert`):

```python
import pytest


@pytest.mark.bloom("PRJ-001")
def test_supply_voltage(bud_assert):
    voltage = 3.29
    bud_assert.assertInTolerance(voltage, 3.3, absolute_tolerance=0.05, msg="3V3 rail")
    assert voltage > 3.0
```

As in budtestlibrary, a failed `bud_assert` check does not stop the test; the test
fails at its end with the first failed check as its error. `abort_on_fail=True`
stops the test at that check. In a test marked xfail, a failed check is the
expected failure.

Like `run-tests`, the upload reads the backend, the station and the product from
`app.properties` and the `BUD_*` environment; `--test-run-id`, `--product-id`,
`--suite-name` (default: the pytest rootdir name) and `--ref-sw-under-test`
override them. A failed upload is spooled and replayed by the next bud-runner
command. Assert statements are reported through pytest's assertion pass hook:
`run-pytest` switches it on and compiles the session's bytecode into
`~/.bud/pycache`, because pytest would otherwise reuse test modules it rewrote
without the hook and leave their passing asserts out. The plugin also works on an
existing `pytest` command:
`pytest -p bud_runner.pytest_plugin -o enable_assertion_pass_hook=true tests/`,
with `--bud-backend-url`, `--bud-test-run-id`, `--bud-product-id`,
`--bud-suite-name`, `--bud-ref-sw-under-test` and `--bud-no-upload`; clear the
test modules' `__pycache__` the first time.

### Report a Behave run

`run-behave` runs Behave with the Bud formatter attached; every argument it does not
know goes to `behave` unchanged, and Behave's exit code is returned. Install the
extra first: `python -m pip install "bud-runner[behave]"` (Behave 1.2.6 or later).

```bash
python -m bud_runner run-behave \
  --backend-url "https://<your-bud-instance-url>" \
  features/ --tags=@smoke
```

Each feature becomes one Bud test case (its name as the test class) and each
scenario one result of it (its name as the method); each Scenario Outline row is its
own result. Each step becomes one entry named after its text, with its .feature file,
line and the step as written: a Then step (and the And or But steps that follow it)
is a check and a Given or When step an information entry; a step that fails or raises
is failed with the error and its traceback, which the scenario's result carries too,
and a step without a step definition is failed with an "Undefined step" message. A hook error fails the scenario, with its traceback. A
scenario skipped with a reason (`scenario.skip("...")` in a hook) counts as skipped;
a scenario left out by `--tags` is not reported. Tag a scenario or its feature with
`@bloom:PRJ-001` to link it to the Bloom test case `PRJ-TC-001` (the full id is accepted
too).

Like `run-tests`, the upload reads the backend, the station and the product from
`app.properties` and the `BUD_*` environment; `--test-run-id`, `--product-id`,
`--suite-name` (default: the feature's name when one feature ran, else the features
directory) and `--ref-sw-under-test` override them. A failed upload is spooled and
replayed by the next bud-runner command. The formatter writes nothing to the console:
without `-f` in the arguments, `run-behave` also shows Behave's `pretty` output. The
formatter also works on an existing `behave` command:
`behave -f bud_runner.behave_formatter:BudFormatter -o /dev/null -f pretty features/`,
with the options as userdata: `-D bud_backend_url=...`, `bud_test_run_id`,
`bud_product_id`, `bud_suite_name`, `bud_ref_sw_under_test`, `bud_upload=false`.

### Import a Cucumber JSON report

`import-cucumber` reads the Cucumber JSON report that cucumber-js
(`--format json:report.json`), Cucumber-JVM (`--plugin json:report.json`) or
Cucumber-Ruby (`--format json --out report.json`) writes, and uploads it as a Bud run.
It needs no extra package.

```bash
python -m bud_runner import-cucumber \
  --backend-url "https://<your-bud-instance-url>" \
  --report report.json
```

The mapping is the one `run-behave` uses. Each feature becomes one Bud test case and
each scenario, every Scenario Outline row included, one result of it; when two
scenarios of a feature share a name, `(line N)` is added to each. Background steps
count as the scenario's own. Each step becomes one entry named after its text, with
its .feature file, line and the step as written: a Then step is a check and a Given or
When step an information entry; And, But and `*` take the type of the step before. A
step that fails, is ambiguous, undefined or pending is failed with the runner's
message, and its stack trace is the traceback; a failed hook is a failed `HookError`
entry. As Cucumber computes it, a scenario's status is its worst step's: a scenario
with a skipped step, or with no steps, counts as skipped. Tag a scenario or its
feature with `@bloom:PRJ-001` to link it to the Bloom test case `PRJ-TC-001` (the full
id is accepted too); the scenario's own tag comes first. Step keywords are recognised
in English: in a feature written in another Gherkin language every step takes the
type of the one before, so its Then steps are information entries.

`--test-run-id`, `--product-id`, `--suite-name` (default: the feature's name when the
report has one feature, else the features directory, else the report's file name) and
`--ref-sw-under-test` set the run; the station, the product and the backend otherwise
come from `app.properties` and the `BUD_*` environment, as for `run-tests`. The report
file is attached to the run unless `--no-artifacts` is given; `--no-upload` only reads
the report and prints its summary. Exit code 0 when the report was read and reached
Bud; 1 when the upload did not reach Bud (the results are spooled and replayed by the
next bud-runner command); 2 when the report cannot be read or no backend is
configured, and nothing is sent.

### Create a Bud test run

This command requires the registered station's token, stored by registration or supplied
as `BUD_RUNNER_TOKEN`.

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

Each station enrols with its own key. A Bud administrator mints it under **Test
Stations** → **Enrolment keys**; it is shown once, and pins to the first station that
registers with it. There is no shared secret across benches.

The administrator also names the station when minting the key, and that name wins: if it
differs from the `--username` passed here, registration returns the name Bud assigned and
the runner stores that one. A later rename in Bud is picked up on the next heartbeat.


```bash
export RUNNER_API_KEY="<enrolment-key-minted-in-bud>"
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
export RUNNER_API_KEY="<enrolment-key-minted-in-bud>"
```

Project-level, non-secret context can be stored in `app.properties`:

```properties
budBackend=https://<your-bud-instance-url>
budRunnerAccount=lab-station-01
```

Do not put passwords, user tokens, runner tokens, or enrolment keys in
`app.properties`.

## Main commands

| Command | Purpose |
|---|---|
| `run-tests` | Execute tests, generate reports, and optionally upload results |
| `claim-run` | Run work the backend has queued for this test station |
| `run-robot` | Run Robot Framework with the Bud listener and report the run |
| `run-pytest` | Run pytest with the Bud plugin and report the run |
| `run-behave` | Run Behave with the Bud formatter and report the run |
| `import-cucumber` | Import a Cucumber JSON report into Bud |
| `list-tests` | Resolve and list discovered tests without executing them |
| `add-test-run` | Create a Bud test run |
| `register` | Register or re-register a runner identity |
| `daemon` | Run heartbeat and local control services |
| `status` | Show local configuration, versions, and Bud health |
| `version` | Print the installed package version |

Run `python -m bud_runner <command> --help` for complete options.

## CI example

Ready-to-copy jobs for GitHub Actions and GitLab CI, for Python test case lists
and for Robot Framework suites, are in the `templates/` folder of the bud-runner repository.

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
          BUD_RUNNER_TOKEN: ${{ secrets.BUD_RUNNER_TOKEN }}
          BUD_RUNNER_ACCOUNT: station-01
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

- [Full licence](https://github.com/MbedLabs/bud-runner/blob/main/LICENSE)
- [Contributing](https://github.com/MbedLabs/bud-runner/blob/main/CONTRIBUTING.md)
- [Contributor License Agreement](https://github.com/MbedLabs/bud-runner/blob/main/CLA.md)
