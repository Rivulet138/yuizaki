# Environment setup / 环境配置

## Supported runtime / 支持的运行时

- Python 3.11-3.13, preferably in `python/.venv`.
- Python 3.11-3.13，建议安装在 `python/.venv` 中。
- Node.js 22.13+ and npm.
- Node.js 22.13+ 和 npm。
- Windows 10/11 or x86_64 Linux with a desktop session.
- Windows 10/11，或带桌面会话的 x86_64 Linux。
- Docker only for optional Qdrant or SoulX workflows.
- Docker 仅用于可选的 Qdrant 或 SoulX 流程。

## Install profiles / 安装配置

The generated `YuizakiLauncher.exe` or `YuizakiLauncher` selects the platform lock file, installs Electron and
node-mcp with `npm ci`, creates the Python venv, runs `pip check`, and validates
the installed lock. `core` uses `requirements-core-lock-*`; `full` uses
`requirements-lock-*` and adds optional ASR, Genie-TTS, Qdrant, embedding, and
model helpers. Platform lock files record tested resolutions; native model
packages can still vary by CPU, GPU, and operating system.

`core` 安装服务端、SQLite、OCR 基础组件和必需运行时。`full` 额外安装可选 ASR、Genie-TTS、Qdrant、嵌入和模型辅助组件。平台锁文件记录已测试的依赖解析结果；原生模型软件包仍可能因 CPU、GPU 和操作系统而不同。

Use `YuizakiLauncher.exe` on Windows or `./YuizakiLauncher` on Linux. Set
`YUIZAKI_INSTALL_PROFILE=full` before the first run when optional ASR, TTS,
Qdrant, embedding, and model helpers are required; the default is `core`.

Source checkouts do not contain the generated binaries. Run `npm ci` followed
by `npm run prepare:launcher` in `electron` to place both launchers in the
repository root. These files remain ignored by Git.

## Local environment file / 本地环境文件

```powershell
Copy-Item python/.env.example python/.env
```

Configure an LLM first. Then configure TTS, ASR, memory, Qdrant, and vision only as needed. Keep `VISION_LLM_ENABLED=0` unless a visual Agent workflow is deliberate. TTS defaults to `TTS_STARTUP_MODE=lazy` and `TTS_WARMUP_ENABLED=0`, so clean startup does not load an optional voice model. Set `TTS_STARTUP_MODE=background` and `TTS_WARMUP_ENABLED=1` only as an explicit opt-in when faster first speech is worth the startup CPU and memory cost. Keep `ASR_STARTUP_MODE=lazy` on constrained hardware.

These defaults are read by `python/modules/core/config.py`,
`python/modules/system/runtime_services.py`, and `python/.env.example`; they
are not only installer documentation. The renderer readiness UI consumes the
resulting capability state through `electron/src/renderer/domains/onboarding`
and `electron/src/renderer/api/clients/system-client.ts`.

The required `host.runtime` onboarding probe reports a closed
`qualified` / `not_qualified` / `unsupported` result. Qualification requires
Windows or Linux x64, Node.js 22.13+, Electron 42.7+, and an X11 or Wayland
desktop session on Linux. Its evidence is a local compatibility probe and
explicitly reports real-device qualification as `not_measured`; release claims
still require clean-machine Windows and Linux walkthrough evidence.

必需的 `host.runtime` 入门探针只会报告 `qualified`、`not_qualified` 或
`unsupported`。通过资格检查需要 Windows/Linux x64、Node.js 22.13+、
Electron 42.7+，Linux 还必须具有 X11 或 Wayland 桌面会话。该结果只是本机兼容性
探测，并会明确把真实设备发布资格标记为 `not_measured`；发布结论仍需 Windows 与
Linux 洁净机走查证据。

请先配置 LLM，再按需配置 TTS、ASR、记忆、Qdrant 和视觉。除非明确需要视觉 Agent 流程，否则保持 `VISION_LLM_ENABLED=0`。TTS 默认使用 `TTS_STARTUP_MODE=lazy` 和 `TTS_WARMUP_ENABLED=0`，因此全新启动不会加载可选语音模型。只有在愿意承担启动阶段的 CPU 与内存开销、并希望缩短首次语音等待时，才显式改为 `TTS_STARTUP_MODE=background` 和 `TTS_WARMUP_ENABLED=1`。硬件受限时保持 `ASR_STARTUP_MODE=lazy`。

## Launcher verification / 启动器验证

Use `YuizakiLauncher.exe --check` (or `./YuizakiLauncher --check`) for a startup preflight that does not launch services. Use `--verify` for the non-GUI verification suite: Python and Electron type checks/tests, Electron lint/build, and node-mcp tests. E2E is intentionally opt-in: `YuizakiLauncher.exe --verify-e2e` first runs the standard verification suite and then starts the Electron E2E checks. On headless Linux, `xvfb-run` must be installed.

使用 `YuizakiLauncher.exe --check` 或 `./YuizakiLauncher --check` 执行不启动服务的启动前检查。`--verify` 执行无 GUI 的 Python/Electron 类型检查与测试、Electron lint/build 以及 node-mcp 测试。E2E 必须显式启用：`YuizakiLauncher.exe --verify-e2e` 会先运行标准验证套件，再启动 Electron E2E 检查。无显示器的 Linux 环境需要安装 `xvfb-run`。

### Supervised one-click launcher / 监督式一键启动

`YuizakiLauncher` is the product-style entry point for installed or source
checkouts. Build it from `electron` with `npm run prepare:launcher`, then use
the same command set on both platforms:

```text
YuizakiLauncher setup             first-run .env/API/model wizard
YuizakiLauncher start             supervised startup with automatic dependency repair
YuizakiLauncher status            endpoint and child-process status
YuizakiLauncher stop              stop the complete supervised process tree
YuizakiLauncher logs [-f]         show or follow supervisor.log
YuizakiLauncher install-desktop   install a desktop shortcut / .desktop entry
```

The launcher keeps a per-user supervisor state file and log directory, hides
Windows service consoles, uses Unix process groups on Linux, and removes child
processes on Ctrl+C/stop. It does not install optional model weights silently;
those remain explicit onboarding resources. `--no-install` disables automatic
dependency installation for locked-down environments.

### Release packaging / 发布打包

Electron Builder is configured for a Windows NSIS installer and Linux AppImage
plus deb packages:

```bash
cd electron
npm run package:win
npm run package:linux
```

`npm run prepare:runtime` stages only runtime Python/Node sources and launcher
scripts, excluding tests, caches, model data, and temporary directories.

## Provider boundaries / 服务商边界

- `LLM_PROVIDER=custom` targets OpenAI-compatible chat endpoints.
- `LLM_PROVIDER=custom` 连接 OpenAI 兼容聊天端点。
- `TTS_PROVIDER=genie-tts` uses the optional local Genie runtime.
- `TTS_PROVIDER=genie-tts` 使用可选的本地 Genie 运行时。
- `TTS_PROVIDER=openai-compatible` targets `/v1/audio/speech`.
- `TTS_PROVIDER=openai-compatible` 连接 `/v1/audio/speech`。
- `ASR_PROVIDER=sherpa-onnx-online` uses a local model when installed and configured.
- `ASR_PROVIDER=sherpa-onnx-online` 在完成安装和配置后使用本地模型。
- SoulX-SVC is an external HTTP service and is not part of the core install.
- SoulX-SVC 是外部 HTTP 服务，不属于核心安装内容。

## Frontend variables / 前端变量

The launcher exports `VITE_YUIZAKI_API_ORIGIN`, `VITE_YUIZAKI_CONTROL_ORIGIN`, `SERVER_PORT`, `CONTROL_SERVER_PORT`, `RENDERER_PORT`, and `MCP_PORT`. Keep port selection in the launcher rather than hard-coding fallback ports in application code.

The Electron control proxy binds only to `127.0.0.1`. Loopback browser, Python API, and Socket.IO requests do not use per-request Bearer authentication. `YUIZAKI_BACKEND_API_TOKEN` remains the boundary for optional non-loopback Python/Socket.IO clients; desktop capability authorization remains separate.

启动器导出 `VITE_YUIZAKI_API_ORIGIN`、`VITE_YUIZAKI_CONTROL_ORIGIN`、`SERVER_PORT`、`CONTROL_SERVER_PORT`、`RENDERER_PORT` 和 `MCP_PORT`。请在启动器中选择端口，不要在应用代码中硬编码备用端口。

Electron 控制代理只绑定 `127.0.0.1`，本机回环的浏览器、Python API 和 Socket.IO 请求均不执行逐请求 Bearer 校验。`YUIZAKI_BACKEND_API_TOKEN` 仅保留为可选非回环 Python/Socket.IO 客户端的访问边界；屏幕、剪贴板和桌面操作授权仍是独立边界。

## Assets and caches / 资源与缓存

Store Live2D/VRM assets and model caches outside Git. Startup restores the saved model reference when the asset exists; missing assets are reported in the pet/resource panel. Read [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) before redistributing any asset or weight.

请将 Live2D/VRM 资源和模型缓存存放在 Git 之外。资源存在时，启动过程会恢复已保存的模型引用；缺失资源会在桌宠/资源面板中报告。重新分发任何资源或权重前，请阅读 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)。
