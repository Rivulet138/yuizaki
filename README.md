# Yuizaki / 结崎

Yuizaki is a local-first AI desktop companion for Windows and Linux. It combines a transparent Live2D or VRM pet with text chat, optional voice and vision, local memory, tools, MCP services, schedules, and visible Agent activity.

Yuizaki 是一款面向 Windows 与 Linux 的本地优先 AI 桌面伙伴，提供 Live2D/VRM 桌宠、文字对话、可选语音与视觉、本地记忆、工具、MCP、定时任务和可见的 Agent 运行状态。

## Features / 功能

- Streaming text conversations with isolated sessions, cancellation, history, and local SQLite persistence.
- Agent planning and tool execution with MCP, plugins, schedules, permissions, and trace feedback.
- Live2D and VRM avatars with expressions, motions, gaze, lip sync, and reduced-motion handling.
- Push-to-talk and continuous voice modes when ASR, LLM, TTS, microphone, and speaker are configured.
- Request-scoped screenshots and vision. Yuizaki does not run a permanent capture loop.
- Inspectable memory with correction, soft forgetting, permanent deletion, and an optional Qdrant projection.
- Experimental Telegram, Discord, QQ personal bridge, and WeChat personal bridge connectors.

核心功能包括流式文字对话、Agent 工具调用、Live2D/VRM 桌宠、可选语音与视觉、可检查和可遗忘的本地记忆，以及实验性消息连接器。语音、视觉、语义检索和外部连接器均为可选能力。

## Platform support / 平台支持

| Platform | Application | Native desktop actions |
| --- | --- | --- |
| Windows 10/11 x64 | Supported | Window discovery, focus, and graceful close |
| Linux x86_64 with X11 | Supported | Window discovery, focus, and graceful close |
| Linux x86_64 with Wayland | Supported shell and tray | Native actions and global hooks are unavailable or compositor-dependent |
| macOS | Not supported | Not implemented |

Automated tests do not qualify a specific microphone, speaker, GPU, provider, model, desktop compositor, or avatar asset. Validate optional capabilities on the target machine before relying on them.

自动化测试不能替代真实设备验收。麦克风、扬声器、GPU、Provider、模型、桌面合成器和角色资源需要在目标机器上单独验证。

## Quick start / 快速开始

Requirements:

- Python 3.11-3.13
- Node.js 22.13 or newer and npm
- Go 1.22 or newer to build the launcher
- A graphical Windows or Linux desktop session

Build the generated launchers from a source checkout:

```powershell
cd electron
npm ci
npm run prepare:launcher
cd ..
```

Windows:

```powershell
.\YuizakiLauncher.exe setup
.\YuizakiLauncher.exe start
```

Linux:

```bash
chmod +x YuizakiLauncher
./YuizakiLauncher setup
./YuizakiLauncher start
```

The setup command creates `python/.env` when needed and asks for the initial LLM provider, endpoint, key, and model. See [Quick start](docs/QUICKSTART.md) for checks and common failures.

`setup` 会在需要时创建 `python/.env`，并引导配置首个 LLM。检查项和常见故障见[快速开始](docs/QUICKSTART.md)。

## Configure an LLM / 配置模型

OpenAI-compatible local services such as Ollama or LM Studio use the custom provider:

```dotenv
LLM_PROVIDER=custom
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_API_KEY=local
LLM_MODEL=your-model
```

Store keys in the ignored `python/.env` file or local settings. Never commit credentials. Optional ASR, TTS, Qdrant, connectors, ports, and assets are documented in [Configuration](docs/CONFIGURATION.md).

密钥应保存在已忽略的 `python/.env` 或本地设置中。ASR、TTS、Qdrant、连接器、端口和资源配置见[配置说明](docs/CONFIGURATION.md)。

## Data and privacy / 数据与隐私

| Data | Default location | Notes |
| --- | --- | --- |
| Chat | `python/data/chat.db` | Local SQLite |
| Memory | `python/data/memory.db` | Local authority; correctable and forgettable |
| Settings | `python/config/settings.json` | Local runtime configuration |
| Audio cache | `python/audio_cache/` | Temporary generated audio |
| Vision frame | Process memory | Request-scoped and not persisted by default |

Cloud providers receive the payload required by the feature you enable. MCP servers, plugins, browser automation, shell tools, and message connectors operate with their configured capabilities. Review [Security and privacy](SECURITY.md) before enabling external tools or services.

云端 Provider 仅在相应功能启用时接收所需负载。启用外部工具或服务前，请阅读[安全与隐私边界](SECURITY.md)。

## Development / 开发

Use the repository launchers for the complete application. For code changes, follow [Contributing](CONTRIBUTING.md). The primary checks are defined by `electron/package.json`, the Python requirement locks, and `.github/workflows/ci.yml`.

```powershell
python scripts/check_docs.py
cd electron
npm run type-check
npm run lint
npm test
npm run build
```

Python tests run from `python` with the project virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pytest -q --tb=short
```

## Documentation / 文档

| Task | Document |
| --- | --- |
| Install and first run / 安装与首次启动 | [Quick start](docs/QUICKSTART.md) |
| Providers, voice, ports, connectors, and assets / Provider、语音、端口、连接器与资源 | [Configuration](docs/CONFIGURATION.md) |
| Linux, audio, X11, and Wayland / Linux、音频、X11 与 Wayland | [Linux notes](docs/LINUX.md) |
| Processes, data flow, and module boundaries / 进程、数据流与模块边界 | [Architecture](docs/ARCHITECTURE.md) |
| Local HTTP and realtime contracts / 本地 HTTP 与实时契约 | [API](docs/API.md) |
| Trust, data, and capability boundaries / 信任、数据与能力边界 | [Security](SECURITY.md) |
| Contribution workflow / 贡献流程 | [Contributing](CONTRIBUTING.md) |

## Status and limitations / 状态与限制

Yuizaki is a local desktop application, not a hardened public service. The release workflow builds Windows NSIS and Linux AppImage/deb artifacts on manual dispatch; it does not publish a GitHub Release automatically. Browser/mobile clients, game-specific agents, a cloud multi-user service, native Wayland desktop actions, and macOS support are outside the current supported release.

Yuizaki 是本地桌面应用，不是公网多用户服务。当前不支持浏览器/移动端、特定游戏 Agent、Wayland 原生桌面动作或 macOS；发布工作流也不会自动创建 GitHub Release。

## License / 许可证

Yuizaki source code is licensed under the MIT License. Models, voices, avatars, fonts, artwork, and external services may have separate terms. Review [Third-party notices](THIRD_PARTY_NOTICES.md) before redistribution.

Yuizaki 源代码采用 MIT 许可证。模型、声音、角色、字体、美术资源和外部服务可能适用独立条款；重新分发前请阅读[第三方声明](THIRD_PARTY_NOTICES.md)。
