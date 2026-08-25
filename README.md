# Yuizaki / 唯知崎

Yuizaki is a local-first AI desktop companion for Windows and Linux. It combines a transparent Live2D/VRM pet with text chat, optional realtime voice, request-scoped vision, local memory, tools, MCP, scheduled jobs, and visible Agent traces.

Yuizaki 是一款本地优先的 Windows 和 Linux AI 桌面伙伴。它将透明的 Live2D/VRM 桌宠与文字聊天、可选实时语音、按请求启用的视觉、本地记忆、工具、MCP、定时任务和可见的 Agent 链路追踪结合在一起。

## What is ready / 当前可用范围

- Desktop pet window with Live2D and VRM adapters.
- 提供带 Live2D 和 VRM 适配器的桌宠窗口。
- Text Agent turns with streaming responses, session isolation, tools, memory, cancellation, and trace events.
- 支持文字 Agent 轮次、流式响应、会话隔离、工具、记忆、取消操作和链路追踪事件。
- Push-to-talk and continuous voice lanes, when a compatible provider, model, microphone, and speaker are configured.
- 在配置兼容的服务商、模型、麦克风和扬声器后，支持按键说话与持续语音通道。
- Optional ASR, TTS, vision, Qdrant retrieval, plugins, MCP, heartbeat, and scheduler integrations.
- 可选集成 ASR、TTS、视觉、Qdrant 检索、插件、MCP、心跳和调度器。
- Request-scoped vision only. Yuizaki does not run a permanent screenshot or camera loop.
- 视觉仅按请求启用；Yuizaki 不会持续截屏或运行常驻摄像头循环。
- Local SQLite persistence for chat and memory.
- 使用本地 SQLite 持久化聊天和记忆。

## Code-backed capability map / 代码取证能力地图

The following table is derived from the current source tree. A source path proves
that the implementation path exists; it does not certify a particular provider,
microphone, GPU, avatar asset, or operating-system integration.

| Capability | Implementation evidence | Runtime boundary |
| --- | --- | --- |
| Agent runtime composition | `python/modules/agent/runtime.py:85-119` | Registers default tools, Desktop Action, Computer Use, MCP, Policy, Trace, Scheduler, Turn Store, and Activity Frames. |
| Text turns and streaming | `python/routes/ai_api.py:212-370`, `electron/src/renderer/domains/chat/composables/useChatDomain.ts` | Requires a configured LLM client; HTTP and Socket.IO paths are separate transports. |
| Planning and bounded tool loop | `python/modules/agent/planner.py:133-181`, `python/modules/agent/tool_loop.py:73-251` | Tool iterations, retry budget, token budget, cancellation, permission receipts, and unknown effects are explicit. |
| Memory retrieval | `python/modules/memory/pipeline.py:20-178`, `python/modules/memory/sqlite_store.py` | Scope/layer/lifecycle filters are applied before the final result; semantic projection is optional. |
| Request-scoped perception | `python/modules/agent/perception.py:35-177`, `electron/src/main/authorized-perception-bridge.ts` | Consent is single-use, TTL-bound, and tied to workspace/session/turn/request/generation. No permanent capture loop is implemented. |
| Voice | `electron/src/renderer/app/composables/useVoiceConversationBridge.ts:256-375`, `electron/src/renderer/audio` | Realtime transport may fall back to the local pipeline; microphone, provider, model, and speaker are required. |
| Avatar embodiment | `electron/src/renderer/runtime/live2d-runtime-adapter.ts`, `electron/src/renderer/runtime/vrm-runtime-adapter.ts`, `electron/src/renderer/pet-embodiment-coordinator.ts` | Agent emits high-level controls; frame-level animation remains in the renderer. |
| Proactive behavior | `electron/src/renderer/app/composables/useProactiveControls.ts`, `python/modules/system/relationship_runtime.py`, `python/modules/agent/scheduler.py` | Controls and scheduler exist, but proactive quality and retention are not certified by this repository alone. |
| Native desktop actions | `python/modules/agent/desktop_actions.py:187-202`, `:358-542`, `electron/src/main/desktop-action-bridge.ts` | Windows user32 and Linux X11 are implemented; pure Wayland, macOS, and unsupported platforms fail closed. |
| Plugins and MCP | `python/modules/agent/plugin_trust.py`, `python/modules/agent/mcp_manager.py`, `electron/src/main/plugin-sandbox.ts` | Enabling a service or plugin authorizes its declared tools without per-call prompts; outputs remain untrusted data. |
| Onboarding/readiness | `electron/src/renderer/domains/onboarding`, `electron/src/main/onboarding-readiness-coordinator.ts`, `python/routes/system_api.py:217-260` | Readiness is reported per capability; it does not install third-party models or guarantee hardware quality. |

The source tree and automated tests are public-facing engineering artifacts. Real microphone, speaker, provider, GPU, model, and avatar quality still require machine-level validation.

源码树和自动化测试属于面向公开发布的工程材料。真实的麦克风、扬声器、服务商、GPU、模型和角色资源质量仍需在目标机器上验证。

## Runtime shape / 运行时结构

```text
Electron main process
  windows, preload bridge, control proxy, lifecycle
        |
Electron/Vue renderer
  chat, settings, audio transport, Live2D/VRM, Job/Trace UI
        |
FastAPI + Socket.IO backend
  Agent, providers, memory, vision, tools, scheduler, heartbeat
        |
optional node-mcp, Qdrant, local or remote providers
```

The process boundaries are implemented rather than conceptual: Electron main
routes control, pet, model, plugin, perception, and onboarding requests through
`electron/src/main/control-server.ts`; the renderer communicates through preload
and typed client/Socket.IO adapters; Python owns Agent orchestration and
persistence. See `python/app.py`, `python/socket_server.py`, and
`electron/src/main/control-server.ts` for the wiring.

The launcher binds local services to loopback. Loopback HTTP and Socket.IO requests are trusted; the generated backend token is only required by optional non-loopback clients. Yuizaki is a desktop application, not a hardened public service.

启动器将本地服务绑定到回环地址。本机 HTTP 与 Socket.IO 请求默认可信，生成的 Backend Token 仅供可选非回环客户端使用。Yuizaki 是桌面应用，不是经过强化的公共服务。

## Requirements / 环境要求

- Windows 10/11 or x86_64 Linux with a graphical desktop session.
- Windows 10/11，或带图形桌面会话的 x86_64 Linux。
- Python 3.11-3.13 in `python/.venv`.
- 在 `python/.venv` 中使用 Python 3.11-3.13。
- Node.js 22.13+ and npm.
- Node.js 22.13+ 和 npm。
- 8 GiB RAM minimum; 16 GiB is recommended for local audio and embedding models.
- 内存最低 8 GiB；运行本地音频和嵌入模型时建议 16 GiB。
- Docker only for optional Qdrant or SoulX service workflows.
- Docker 仅用于可选的 Qdrant 或 SoulX 服务流程。

## Install and start / 安装与启动

The root launchers are generated artifacts and are not committed to Git. In a
source checkout, build both launchers first:

```powershell
cd electron
npm ci
npm run prepare:launcher
cd ..
```

该仓库不会提交根目录启动器二进制。源码检出后，先运行以上命令生成 Windows
`YuizakiLauncher.exe` 和 Linux `YuizakiLauncher`。

Windows (the generated root `YuizakiLauncher.exe` is the one-click entry):

```powershell
.\YuizakiLauncher.exe
```

The first run creates `python/.env`, asks for the provider/API/model, and can
install the selected runtime profile automatically. The launcher is the
supported source-checkout entry; use `--check` or `--verify` for development
checks.

For the product-style supervised launcher, double-click `YuizakiLauncher.exe`
in the repository root after generation:

```powershell
YuizakiLauncher.exe setup
YuizakiLauncher.exe start
YuizakiLauncher.exe status
YuizakiLauncher.exe stop
YuizakiLauncher.exe logs
YuizakiLauncher.exe install-desktop
```

Linux:

```bash
./YuizakiLauncher
```

Linux uses the same Go launcher contract after building `YuizakiLauncher` with
`npm run prepare:launcher:linux` from `electron`. The command works on Windows
and Linux and writes the Linux executable without an extension to the repository
root. On Linux, ensure it is executable with `chmod +x YuizakiLauncher` after
copying it from a filesystem that does not preserve Unix permissions.
`./YuizakiLauncher setup` creates
the first `.env`, asks for the provider/API/model, and `./YuizakiLauncher start`
supervises all child processes. `./YuizakiLauncher install-desktop` writes a
user-scoped `yuizaki.desktop` entry.

The manually triggered `Release Packages` workflow builds Windows NSIS and
Linux AppImage/deb artifacts. It uploads workflow artifacts only; it does not
currently create a GitHub Release or publish a stable download automatically.

On Wayland, the Electron shell selects the Ozone Wayland backend automatically.
Global input hooks and host-level desktop actions remain capability-gated by the
compositor, while normal windows and the tray continue to work.

Use `full` instead of `core` for optional ASR, Genie-TTS, Qdrant, embedding, and related packages. See [docs/ENVIRONMENT_SETUP.md](docs/ENVIRONMENT_SETUP.md) for provider setup and [docs/LINUX.md](docs/LINUX.md) for desktop/audio notes.

需要可选 ASR、Genie-TTS、Qdrant、嵌入及相关软件包时，请将 `core` 替换为 `full`。服务商配置请参阅 [docs/ENVIRONMENT_SETUP.md](docs/ENVIRONMENT_SETUP.md)，桌面和音频说明请参阅 [docs/LINUX.md](docs/LINUX.md)。

For the chat/pet interaction rationale, repository evidence, and public-release gate, see [docs/RESEARCH_AND_RELEASE.md](docs/RESEARCH_AND_RELEASE.md). The maintained paper, standard, benchmark, and comparable-project index is [docs/REFERENCES.md](docs/REFERENCES.md).

有关聊天/桌宠交互依据、仓库核验结果和公开发布门槛，请参阅 [docs/RESEARCH_AND_RELEASE.md](docs/RESEARCH_AND_RELEASE.md)；论文、标准、评测集与同类项目统一索引见 [docs/REFERENCES.md](docs/REFERENCES.md)。

## Useful launcher modes / 常用启动模式

| Mode | Purpose |
| --- | --- |
| `--check` | Validate paths, runtimes, dependencies, and startup configuration without launching services |
| `--verify` | Run Python/Electron type checks and tests, Electron lint/build, and node-mcp tests without launching services |
| `--verify-e2e` | Run `--verify`, then explicitly launch the Electron E2E validation suite (GUI/display required) |
| `--smoke` | Run lightweight health, pet, and MCP checks after startup |
| `--dev-renderer` | Serve the renderer through Vite during development |
| `--no-mcp` | Start a reduced backend/Electron run without the default MCP service |
| `--with-qdrant` | Request Docker-backed Qdrant on Windows |
| `--no-show-pet` / `--no-open` | Suppress the pet window or control-panel opening on Windows |

The supervised launcher also accepts the commands `setup`, `start`, `stop`,
`status`, `logs`, `install-desktop`, and `remove-desktop`. `start` automatically
creates `python/.env` and installs the selected `core`/`full` profile when the
runtime is missing; pass `--no-install` when network/package mutation is not
allowed. Build fingerprints under `electron/dist/.launcher-build.json` avoid
rebuilding an unchanged production renderer.

| 模式 | 用途 |
| --- | --- |
| `--check` | 启动前验证路径、运行时、依赖和配置 |
| `--verify` | 不启动服务，运行 Python/Electron 类型检查与测试、Electron lint/build 及 node-mcp 测试 |
| `--verify-e2e` | 先运行 `--verify`，再显式启动 Electron E2E 验证套件（需要 GUI/显示环境） |
| `--smoke` | 启动后执行轻量健康、桌宠和 MCP 检查 |
| `--dev-renderer` | 开发时通过 Vite 提供渲染器服务 |
| `--no-mcp` | 不启用默认 MCP 服务，启动精简后端/Electron 流程 |
| `--with-qdrant` | 在 Windows 上请求由 Docker 提供的 Qdrant |
| `--no-show-pet` / `--no-open` | 在 Windows 上禁止打开桌宠窗口或控制面板 |

## Provider example / 服务商配置示例

OpenAI-compatible local servers such as Ollama and LM Studio use the same fields:

```dotenv
LLM_PROVIDER=custom
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_API_KEY=local
LLM_MODEL=your-model
```

Keep keys in `python/.env` or local settings. Do not commit them or put them in logs.

请将密钥保存在 `python/.env` 或本地设置中，不要提交到版本库，也不要写入日志。

## Data and privacy / 数据与隐私

| Data | Default location | Boundary |
| --- | --- | --- |
| Chat | `python/data/chat.db` | Local SQLite |
| Memory | `python/data/memory.db` | Correctable and forgettable records |
| Settings | `python/config/settings.json` | Local runtime configuration |
| TTS cache | `python/audio_cache/` | Temporary audio artifacts |
| Vision frame | Process memory | One request by default; not written to history |

Cloud providers receive only the payload required by the selected feature. MCP servers, plugins, shell tools, and remote providers can read or change data within their configured capabilities. Read [SECURITY.md](SECURITY.md) before enabling them.

云服务商只会收到所选功能所需的数据。MCP 服务、插件、Shell 工具和远程服务商可以在其配置能力范围内读取或修改数据；启用前请阅读 [SECURITY.md](SECURITY.md)。

## Verification / 验证

The repository CI covers documentation, dependency locks, Electron type-check/lint/tests/build, Python tests/type checks, and Node MCP tests. Product metrics are opt-in runtime telemetry, not a fixture-based release gate. See [docs/MODEL_EVALUATION.md](docs/MODEL_EVALUATION.md) and [python/tests/README.md](python/tests/README.md) for the remaining validation boundary.

Passing automated tests does not certify a particular microphone, speaker, GPU, provider, model weight, or avatar asset.

自动化测试通过并不代表某一特定麦克风、扬声器、GPU、服务商、模型权重或角色资源已经获得质量保证。

## Scope and non-goals / 范围与非目标

The current release targets a local desktop companion. Discord/Telegram connectors, browser/mobile clients, browser extensions, game-specific agents, and a cloud multi-user service are not part of the supported core release.

当前版本面向本地桌面伙伴。Discord/Telegram 连接器、浏览器/移动端客户端、浏览器扩展、特定游戏 Agent 以及云端多用户服务不属于受支持的核心版本范围。

## Evidence and release boundary / 证据与发布边界

- Code paths and contract tests establish implementation intent and tested cases; they do not establish end-to-end hardware quality.
- `electron/package.json:24-32` defines type-check, lint, unit, build, and Electron E2E commands. `.github/workflows/ci.yml` runs those checks across Windows/Linux and Python 3.11-3.13, but a local checkout must still run them before a release claim.
- `electron/src/renderer/__tests__`, `electron/src/main/__tests__`, and `python/tests` contain contract coverage for voice, pet, memory, perception, desktop actions, permissions, onboarding, and turn lifecycle.
- The current worktree may contain uncommitted changes. Treat the commit and exact lock files used for a build as the release identity.

## Documentation / 文档入口

| Task | Document |
| --- | --- |
| First install and basic checks / 首次安装与基本检查 | [Quick start](docs/QUICKSTART.md) |
| Providers, ports, voice, vision, and assets / 服务商、端口、语音、视觉与资源 | [Environment setup](docs/ENVIRONMENT_SETUP.md) |
| Linux desktop, audio, X11, and Wayland / Linux 桌面、音频、X11 与 Wayland | [Linux notes](docs/LINUX.md) |
| Process, data, IPC, HTTP, and Socket.IO boundaries / 进程、数据与通信边界 | [Architecture](docs/ARCHITECTURE.md) and [API](docs/API.md) |
| Local trust and external capability boundary / 本机信任与外部能力边界 | [Security](SECURITY.md) |
| Packaging, evidence, and redistribution / 打包、证据与再分发 | [Research and release](docs/RESEARCH_AND_RELEASE.md) and [Third-party notices](THIRD_PARTY_NOTICES.md) |
| Design sources and comparable projects / 设计资料与同类项目 | [References](docs/REFERENCES.md) |

## License / 许可证

Yuizaki source code is MIT-licensed. Character models, voices, fonts, artwork, downloaded weights, and external services have separate terms. Read [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) before redistributing a build.

Yuizaki 源代码采用 MIT 许可证。角色模型、声音、字体、艺术素材、下载的权重和外部服务均有独立条款；重新分发构建产物前请阅读 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
