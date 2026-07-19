# Linux support

Yuizaki supports Linux development and local use on x86_64 desktop
distributions with Node.js 22.13+, Python 3.12+, and a graphical session.

## System packages

Install the packages required by Electron/Chromium, Python virtual
environments, audio, and desktop capture. Package names differ by
distribution; the required capabilities are:

- Python venv and development runtime;
- GTK 3, NSS, GBM, ATK/AT-SPI, X11/XCB, and ALSA compatibility libraries;
- PipeWire and `xdg-desktop-portal` for Wayland screen capture;
- Docker Engine with Compose v2 only when Qdrant or SoulX-SVC is enabled.

Ubuntu/Debian example:

```bash
sudo apt update
sudo apt install python3 python3-venv \
  libgtk-3-0 libnss3 libgbm1 libxss1 libatk-bridge2.0-0 \
  libasound2 xdg-desktop-portal pipewire
```

Install Node.js 22.13 or newer with a maintained distribution package, `nvm`,
or another version manager. Do not rely on the older Node.js package shipped
by distributions whose repository version is below this requirement.

On distributions that use `t64` package names, install the corresponding
`libgtk-3-0t64` and `libasound2t64` packages.

## Install

```bash
chmod +x install_core.sh install_full.sh start.sh start_soulx_svc.sh \
  scripts/run_backend_dev.sh
./install_full.sh
```

Use `./install_core.sh` when local TTS/ASR and embedding runtimes are not
needed yet. Optional model files remain first-use or manually selected
downloads and are not stored in Git.

## Start

```bash
./start.sh --check
./start.sh
```

Optional modes:

```bash
./start.sh --with-mcp
./start.sh --dev-renderer
./start.sh --smoke
./scripts/run_backend_dev.sh
./start_soulx_svc.sh /path/to/reference.wav
```

The Linux launcher selects free loopback ports, creates a per-run API token,
applies database migrations, builds Electron, starts the backend and optional
services, and terminates owned child processes when Electron exits.

## Wayland and X11

Electron runs natively on Wayland in current releases. Wayland compositors
intentionally restrict programmatic window positioning and desktop capture:

- desktop capture is selected through PipeWire/desktop portals and can return
  only the user-approved source;
- moving or docking the pet window programmatically may be limited by the
  compositor;
- global shortcuts and mouse side buttons depend on compositor policy.

Use an X11 session or XWayland when unrestricted pet positioning is required.
Do not use `--no-sandbox`; the application keeps Electron renderer sandboxing
enabled on every platform.

The Go source under `tools/yuizaki-launcher` builds the Windows packaging
launcher. Linux users should use `start.sh`; the application runtime itself is
shared across both platforms.

## Troubleshooting

- Blank or missing capture picker: verify PipeWire and the desktop-specific
  `xdg-desktop-portal` backend are running.
- Electron fails to load a shared library: install the missing Chromium system
  library from the distribution package manager.
- No microphone: grant microphone permission in the desktop environment and
  verify the input device with PipeWire/PulseAudio tools.
- Local model wheel unavailable: use the service provider mode or a Python
  version supported by that model's native package.
