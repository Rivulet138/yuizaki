# Yuizaki

Yuizaki is a local-first AI desktop companion for Windows and Linux. It combines a transparent Live2D/VRM pet with text chat, optional realtime voice, request-scoped vision, local memory, tools, MCP, scheduled jobs, and visible Agent traces.

## What is ready

- Desktop pet window with Live2D and VRM adapters.
- Text Agent turns with streaming responses, session isolation, tools, memory, cancellation, and trace events.
- Push-to-talk and continuous voice lanes, when a compatible provider, model, microphone, and speaker are configured.
- Optional ASR, TTS, vision, Qdrant retrieval, plugins, MCP, heartbeat, and scheduler integrations.
- Request-scoped vision only. Yuizaki does not run a permanent screenshot or camera loop.
- Local SQLite persistence for chat and memory.

The source tree and automated tests are public-facing engineering artifacts. Real microphone, speaker, provider, GPU, model, and avatar quality still require machine-level validation.

## Runtime shape

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

## Requirements

- Windows 10/11 or x86_64 Linux with a graphical desktop session.
- Python 3.11-3.13 in `python/.venv`.
- Node.js 22.13+ and npm.
- 8 GiB RAM minimum; 16 GiB is recommended for local audio and embedding models.
- Docker only for optional Qdrant or SoulX service workflows.

## Install and start

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

## Useful launcher modes

| Mode | Purpose |
| --- | --- |
| `--check` | Validate paths, runtimes, dependencies, and startup configuration without launching services |
| `--verify` | Run the supported type-check/build/test verification path without launching services |
| `--smoke` | Run lightweight health, pet, and MCP checks after startup |
| `--dev-renderer` | Serve the renderer through Vite during development |
| `--no-mcp` | Start a reduced backend/Electron run without the default MCP service |
| `--with-qdrant` | Request Docker-backed Qdrant on Windows |
| `--no-show-pet` / `--no-open` | Suppress the pet window or control-panel opening on Windows |

## Provider example

OpenAI-compatible local servers such as Ollama and LM Studio use the same fields:

```dotenv
LLM_PROVIDER=custom
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_API_KEY=local
LLM_MODEL=your-model
```

Keep keys in `python/.env` or local settings. Do not commit them or put them in logs.

## Data and privacy

| Data | Default location | Boundary |
| --- | --- | --- |
| Chat | `python/data/chat.db` | Local SQLite |
| Memory | `python/data/memory.db` | Correctable and forgettable records |
| Settings | `python/config/settings.json` | Local runtime configuration |
| TTS cache | `python/audio_cache/` | Temporary audio artifacts |
| Vision frame | Process memory | One request by default; not written to history |

Cloud providers receive only the payload required by the selected feature. MCP servers, plugins, shell tools, and remote providers can read or change data within their configured capabilities. Read [SECURITY.md](SECURITY.md) before enabling them.

## Verification

The repository CI covers documentation, dependency locks, Electron type-check/lint/tests/build, Python tests/type checks, Node MCP tests, and offline fixture evaluation. Run the local checks described in [docs/MODEL_EVALUATION.md](docs/MODEL_EVALUATION.md) and [python/tests/README.md](python/tests/README.md).

Passing automated tests does not certify a particular microphone, speaker, GPU, provider, model weight, or avatar asset.

## Scope and non-goals

The current release targets a local desktop companion. Discord/Telegram connectors, browser/mobile clients, browser extensions, game-specific agents, and a cloud multi-user service are not part of the supported core release.

## License

Yuizaki source code is MIT-licensed. Character models, voices, fonts, artwork, downloaded weights, and external services have separate terms. Read [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) before redistributing a build.
