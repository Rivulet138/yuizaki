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

The launcher binds local services to loopback and creates a per-run control token. Yuizaki is a desktop application, not a hardened public service.

启动器将本地服务绑定到回环地址，并为每次运行创建控制令牌。Yuizaki 是桌面应用，不是经过强化的公共服务。

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

Windows:

```powershell
.\install.bat core
Copy-Item python/.env.example python/.env
# Edit python/.env and configure an LLM provider.
.\start.bat
```

Linux:

```bash
./install.sh core
cp python/.env.example python/.env
# Edit python/.env and configure an LLM provider.
./start.sh
```

Use `full` instead of `core` for optional ASR, Genie-TTS, Qdrant, embedding, and related packages. See [docs/ENVIRONMENT_SETUP.md](docs/ENVIRONMENT_SETUP.md) for provider setup and [docs/LINUX.md](docs/LINUX.md) for desktop/audio notes.

需要可选 ASR、Genie-TTS、Qdrant、嵌入及相关软件包时，请将 `core` 替换为 `full`。服务商配置请参阅 [docs/ENVIRONMENT_SETUP.md](docs/ENVIRONMENT_SETUP.md)，桌面和音频说明请参阅 [docs/LINUX.md](docs/LINUX.md)。

For the chat/pet interaction rationale, repository evidence, and public-release gate, see [docs/RESEARCH_AND_RELEASE.md](docs/RESEARCH_AND_RELEASE.md).

有关聊天/桌宠交互依据、仓库核验结果和公开发布门槛，请参阅 [docs/RESEARCH_AND_RELEASE.md](docs/RESEARCH_AND_RELEASE.md)。

## Useful launcher modes / 常用启动模式

| Mode | Purpose |
| --- | --- |
| `--check` | Validate paths, runtimes, dependencies, and startup configuration without launching services |
| `--verify` | Run the supported type-check/build/test verification path without launching services |
| `--smoke` | Run lightweight health, pet, and MCP checks after startup |
| `--dev-renderer` | Serve the renderer through Vite during development |
| `--no-mcp` | Start a reduced backend/Electron run without the default MCP service |
| `--with-qdrant` | Request Docker-backed Qdrant on Windows |
| `--no-show-pet` / `--no-open` | Suppress the pet window or control-panel opening on Windows |

| 模式 | 用途 |
| --- | --- |
| `--check` | 启动前验证路径、运行时、依赖和配置 |
| `--verify` | 不启动服务，运行支持的类型检查、构建和测试验证流程 |
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

The repository CI covers documentation, dependency locks, Electron type-check/lint/tests/build, Python tests/type checks, Node MCP tests, and offline fixture evaluation. Run the local checks described in [docs/MODEL_EVALUATION.md](docs/MODEL_EVALUATION.md) and [python/tests/README.md](python/tests/README.md).

Passing automated tests does not certify a particular microphone, speaker, GPU, provider, model weight, or avatar asset.

自动化测试通过并不代表某一特定麦克风、扬声器、GPU、服务商、模型权重或角色资源已经获得质量保证。

## Scope and non-goals / 范围与非目标

The current release targets a local desktop companion. Discord/Telegram connectors, browser/mobile clients, browser extensions, game-specific agents, and a cloud multi-user service are not part of the supported core release.

当前版本面向本地桌面伙伴。Discord/Telegram 连接器、浏览器/移动端客户端、浏览器扩展、特定游戏 Agent 以及云端多用户服务不属于受支持的核心版本范围。

## License / 许可证

Yuizaki source code is MIT-licensed. Character models, voices, fonts, artwork, downloaded weights, and external services have separate terms. Read [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) before redistributing a build.

Yuizaki 源代码采用 MIT 许可证。角色模型、声音、字体、艺术素材、下载的权重和外部服务均有独立条款；重新分发构建产物前请阅读 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
