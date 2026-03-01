# macOS launchd guide

For macOS hosts, run `bud_runner daemon` under a user LaunchAgent so the
runner starts automatically when the account logs in.

## Example plist

Save a file like `~/Library/LaunchAgents/net.embedlabs.bud-runner.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>net.embedlabs.bud-runner</string>
    <key>ProgramArguments</key>
    <array>
      <string>/usr/bin/env</string>
      <string>python</string>
      <string>-m</string>
      <string>bud_runner</string>
      <string>daemon</string>
      <string>--username</string>
      <string>runner-01</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>WorkingDirectory</key>
    <string>/Users/runner-01</string>
  </dict>
</plist>
```

## Load it

```bash
launchctl load ~/Library/LaunchAgents/net.embedlabs.bud-runner.plist
launchctl start net.embedlabs.bud-runner
```

Register the runner once before enabling the agent so `~/.bud/config.json`
already contains the token and socket port.
