# Linux notes

## Supported shape

The launcher targets x86_64 Linux with Python 3.11-3.13, Node.js 22.13+, a desktop session, and an Electron-compatible X11 or Wayland environment.

## Start

```bash
./install.sh core
./start.sh --check
./start.sh
```

MCP starts by default. Pass `--no-mcp` for a backend/Electron-only run. `--dev-renderer` serves Vite separately.

## Audio and input

Check the default PipeWire/PulseAudio device and grant microphone permission to the desktop session. Global mouse/keyboard hooks may be limited under Wayland; normal window interaction remains available. Realtime voice still requires a secure Electron context and a user-granted microphone stream.

## GPU and pet rendering

If the pet is blank or unstable, try a lower performance profile, disable hardware acceleration for diagnosis, verify the model asset, and inspect Electron logs. Hidden windows pause rendering work; this is expected.
