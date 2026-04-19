# Bud Runner Setup Guide

This guide explains how to register and run a new Bud runner instance. 

## 1. Installation
Install the required packages. If you are developing locally, editable mode is recommended:
```bash
pip install -e ./bud-test-library
pip install -e ./bud-runner
```

## 2. Environment Configuration
Define your backend URL and registration secret. The `RUNNER_API_KEY` is a shared secret configured on your Bud backend instance.

```bash
export BUD_BACKEND_URL="https://<your-bud-backend-domain>"
export RUNNER_API_KEY="<your-registration-secret>"
```

## 3. Register the Runner
Execute the registration command to create a runner account. **The heartbeat daemon will start automatically in the background** upon successful registration.

```bash
# Register runner (daemon starts automatically)
python -m bud_runner register --username <new-runner-name> --password <secure-password>

# Register without starting the daemon
python -m bud_runner register --username <new-runner-name> --no-start
```

## 4. Verification
Registration will update your global identity vault (`~/.bud/config.json`) and generate namespaced process files:
- PID: `bud_<username>.pid`
- Log: `bud_<username>.log`

```properties
# Repository app.properties
budBackend=https://<your-bud-instance-url>
budRunnerAccount=<new-runner-name>
runnerSocketPort=53035
```

## 5. Management
The runner remains active in the background. You can manage it using the `daemon` command if needed:

```bash
# Start manually if stopped
python -m bud_runner daemon

# Check status
python -m bud_runner status
```
