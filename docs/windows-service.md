# Windows service guide

On Windows, the simplest production setup is to wrap `bud_runner daemon` with a
service manager such as NSSM (the Non-Sucking Service Manager).

## Recommended flow

1. Install Python and `bud-runner`.
2. Register the runner once from an elevated PowerShell prompt:

```powershell
bud-runner register --username runner-01 --backend-url https://your-bud-instance.example
```

3. Create the service with NSSM:

```powershell
nssm install BudRunner "C:\Python313\python.exe" "-m bud_runner daemon --username runner-01"
```

4. Start the service:

```powershell
nssm start BudRunner
```

## Notes

- The service account needs access to the `%USERPROFILE%\.bud\config.json` file that was created during registration.
- Daemon output is structured JSON, so point NSSM stdout/stderr capture at a log file if you want to ingest it centrally.
