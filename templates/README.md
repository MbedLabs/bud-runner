# CI templates

Jobs for running tests with bud-runner in GitHub Actions and GitLab CI. Copy one into
your test repository and adjust the suites, the triggers and the runner tag.

| Template | Copy to | Runs |
|---|---|---|
| `github/bud-tests.yml` | `.github/workflows/` | Python test case lists with `bud-runner run-tests` |
| `github/bud-robot.yml` | `.github/workflows/` | Robot Framework suites with `bud-runner run-robot` |
| `gitlab/gitlab-ci.yml` | `.gitlab-ci.yml` in the repository root | Python test case lists |
| `gitlab/gitlab-ci.robot.yml` | `.gitlab-ci.yml` in the repository root | Robot Framework suites |

All of them run on a self-hosted runner tagged `teststations`, on the bench host, and
read the backend from `BUD_BACKEND_URL`. The station, product and credentials come from
`app.properties` and the `BUD_*` environment, as for any bud-runner command.

## Python test case lists

`bud-tests.yml` runs on a daily schedule (commented out until you enable it) and on
manual dispatch with an optional `run_label`. Each step runs one test case list, a
Python module attribute such as `BudSuite.SUITE_A`, with `--continue-on-error` so later
suites still run, and uploads its JUnit file. The GitLab version declares the JUnit
files as test reports, so GitLab shows each case in the merge request and the Tests tab;
manual runs come from the web UI with `RUN_LABEL` as a pipeline variable, and
`interruptible: false` keeps a newer pipeline from cancelling one that is driving the
bench.

## Robot Framework suites

`bud-robot.yml` and `gitlab-ci.robot.yml` run `bud-runner run-robot`, which starts
`robot` with the Bud listener and passes every other argument to it. List
`bud-runner[robot]` in `requirements.txt`. The job fails when a Robot test fails, as
Robot's exit code is kept; the GitLab version also writes an xUnit file for GitLab's
Tests tab.

A team that already has a Robot job does not need these templates: it adds
`--listener bud_runner.robot_listener.BudListener` to its existing `robot` command. See
"Report a Robot Framework run" in the bud-runner README for what is reported.
