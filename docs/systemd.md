# systemd service template

Use the bundled unit file at [`docs/systemd/bud-runner.service`](systemd/bud-runner.service)
as a starting point for Linux hosts that should keep `bud_runner daemon`
running after boot.

## Recommended flow

1. Install `bud-runner` in the target Python environment.
2. Register the runner once interactively:

```bash
bud-runner register --username runner-01 --backend-url https://your-bud-instance.example
```

3. Copy the unit file into `/etc/systemd/system/bud-runner@.service`.
4. Enable and start it for the runner account:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now bud-runner@runner-01.service
```

## Notes

- `~/.bud/config.json` stores the runner token and socket port after registration.
- `RUNNER_API_KEY` is only required for the registration command, not for the daemon itself.
- Structured daemon logs are written through stdout/stderr, so `journalctl -u bud-runner@runner-01` will show JSON log lines.
