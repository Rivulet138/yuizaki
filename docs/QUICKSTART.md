# Quick start / 快速开始

This guide starts Yuizaki from a source checkout with text chat as the first acceptance check. Voice, vision, Qdrant, and message connectors are optional.

本指南用于从源码启动 Yuizaki，并先以文字对话作为验收项。语音、视觉、Qdrant 和消息连接器均为可选能力。

## Requirements / 环境要求

- Windows 10/11 x64, or x86_64 Linux with an X11 or Wayland desktop session
- Python 3.11-3.13
- Node.js 22.13 or newer and npm
- Go 1.22 or newer

The launcher creates and manages `python/.venv`; do not use a global Python environment for the application runtime.

## Build the launcher / 构建启动器

The root launcher binaries are generated and ignored by Git:

```powershell
cd electron
npm ci
npm run prepare:launcher
cd ..
```

This creates `YuizakiLauncher.exe` and `YuizakiLauncher` in the repository root.

## Windows

```powershell
.\YuizakiLauncher.exe setup
.\YuizakiLauncher.exe start --check
.\YuizakiLauncher.exe start
```

`setup` creates `python/.env` when missing and asks for the install profile and initial LLM settings. `--check` validates paths, runtimes, dependencies, and startup configuration without launching services.

默认启动会打开浏览器对话页，Electron 仅作为隐藏的本地宿主运行；需要旧 Electron 控制窗口和桌宠时使用 `.\YuizakiLauncher.exe start --electron-ui`。

## Linux

Build only the Linux launcher when preferred:

```bash
cd electron
npm ci
npm run prepare:launcher:linux
cd ..
chmod +x YuizakiLauncher
./YuizakiLauncher setup
./YuizakiLauncher start --check
./YuizakiLauncher start
```

默认启动会打开浏览器对话页，Electron 仅作为隐藏的本地宿主运行；需要旧 Electron 控制窗口和桌宠时使用 `./YuizakiLauncher start --electron-ui`。

Read [Linux notes](LINUX.md) before diagnosing audio, GPU, X11, or Wayland behavior.

## First run / 首次运行

1. Open the browser chat page and confirm that the Live2D/VRM stage appears.
2. Open Settings and confirm that an LLM provider, endpoint, and model are configured.
3. Send a text message and wait for the final response.
4. Enable voice, vision, tools, MCP services, or connectors only after text chat works.

首次启动时先确认浏览器对话页、模型展示和文字对话正常，再逐项启用语音、视觉、工具、MCP 或连接器。

## Launcher commands / 启动器命令

| Command | Purpose |
| --- | --- |
| `setup` | Create local configuration and run the first-run wizard |
| `start` | Start and supervise the application processes |
| `status` | Show child-process and endpoint status |
| `stop` | Stop the supervised process tree |
| `logs` | Show the supervisor log; add `-f` to follow it |
| `install-desktop` | Install a user-scoped shortcut or desktop entry |
| `remove-desktop` | Remove the user-scoped shortcut or desktop entry |

Useful start flags include `--check`, `--smoke`, `--no-mcp`, `--no-install`, `--dev-renderer`, `--no-open`, `--no-show-pet`, and `--electron-ui`. Windows also supports `--with-qdrant` for the Docker-backed optional Qdrant service.

## Common failures / 常见故障

- **Missing launcher:** rerun `npm run prepare:launcher` from `electron`.
- **Missing `python/.venv`:** run `setup`, then start again without `--no-install`.
- **No LLM response:** verify `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, and provider availability.
- **Port conflict:** set `SERVER_PORT`, `CONTROL_SERVER_PORT`, `RENDERER_PORT`, or `MCP_PORT` in `python/.env`.
- **Blank pet:** verify the Live2D/VRM asset path and inspect the Electron logs.
- **No voice:** verify desktop permission, input/output devices, ASR, TTS, and model resources. Fixture tests do not qualify real devices.
- **Wayland action unavailable:** native desktop actions support Windows and explicit X11 sessions; Wayland support is limited to the application shell and compositor-permitted behavior.

Provider and optional feature settings are documented in [Configuration](CONFIGURATION.md).
