# Linux notes

## Supported shape

The Linux launcher targets x86_64 systems with Python 3.11-3.13, Node.js 22.13+, a graphical desktop session, and an Electron-compatible X11 or Wayland environment.

## Install and start

```bash
./install.sh core
./start.sh --check
./start.sh
```

MCP starts by default. Use `--no-mcp` for a reduced run and `--dev-renderer` to serve the renderer through Vite.

## Audio and input

Verify the PipeWire or PulseAudio input/output device and grant microphone permission to the desktop session. Global mouse/keyboard hooks may be limited under Wayland; ordinary window interaction remains available. Realtime voice also requires a secure Electron context and a user-granted microphone stream.

## GPU and pet rendering

If the pet is blank or unstable, verify the asset path, try a lower performance profile, and inspect Electron logs. Disabling hardware acceleration can help isolate driver problems. Hidden windows pause rendering work by design.

## Evidence boundary

Linux CI can validate builds and scripted smoke paths, but it cannot represent every desktop compositor, audio device, GPU driver, or avatar asset. Record the OS, desktop session, provider, model, and hardware when reporting an issue.
