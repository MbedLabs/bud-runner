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
Execute the registration command to create a runner account. You can use the `--start` flag to launch the heartbeat daemon immediately after successful registration.

```bash
# Register and start daemon in one go
python -m bud_runner register \
    --username <new-runner-name> \
    --password <secure-password> \
    --start

# Or just register
python -m bud_runner register \
    --username <new-runner-name> \
    --password <secure-password>
```

## 4. Verification
Registration will generate or update an `app.properties` file in your working directory. Ensure it contains the following:
```properties
budBackend=https://<your-bud-backend-domain>
budRunnerAccount=<new-runner-name>
budRunnerToken=eyJ...
```

## 5. Stay Online (Daemon)
The runner must remain active to appear as "Online" and receive commands. Use the `daemon` command to start the heartbeat and socket listener:

```bash
# Start the daemon
python -m bud_runner daemon

# Start with custom interval or port
python -m bud_runner daemon --interval 30 --port 54000
```
