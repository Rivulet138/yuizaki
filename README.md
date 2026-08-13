# Yuizaki

Yuizaki is a local-first AI desktop companion agent. It combines a transparent desktop pet (Live2D or VRM) with chat, realtime voice, optional vision, memory, tools, MCP, scheduled jobs, and visible Agent traces.

## Current capabilities

- Transparent, draggable pet window with Live2D and VRM runtime adapters.
- Automatic restoration of the last selected model during startup.
- Live2D/VRM high-level behavior mapping: idle profiles, gaze, expressions, motion, lip-sync, fatigue, affinity, trust, mood, and relationship trend. Frame-level animation remains local to the renderer.
- Push-to-talk and continuous realtime voice sessions.
- Streaming ASR, incremental LLM responses, Genie TTS, OpenAI-compatible `/v1/audio/speech` TTS, ordered segment playback, lip-sync, barge-in interruption, stale-event rejection, and turn cancellation.
- Independent chat-session runtime identity, background completion, unread state, and visible Job/Trace steps.
- MCP (enabled by the normal launcher), built-in tools, plugins, scheduler, heartbeat, and visual capture represented as cancellable Job events.
- Local memory with confidence, source/trace identity, model version, correction, and forget operations.
- Request-scoped vision only: an Agent request captures and analyzes one current frame, then releases it. There is no permanent screenshot loop.
- Hardware-aware rendering: device-pixel-ratio cap, power preference, active/idle FPS tiers, hidden-window pause, and coalesced pointer input.

## Runtime layout

```text
Electron/Vue renderer
  chat, voice transport, pet rendering, settings, Job/Trace projection
        |
FastAPI + Socket.IO backend
  Agent, provider adapters, memory, vision, tools, scheduler, heartbeat
        |
optional node-mcp service, Qdrant, local or remote model providers
```

The Electron process owns windows, input, rendering, audio transport, and UI state. The Python process owns Agent orchestration and persistence. `node-mcp` is started by default by `start.bat` and `start.sh`; pass `--no-mcp` only for an intentional reduced startup.

## Requirements

- Windows 10/11 or x86_64 Linux.
- Python 3.11, 3.12, or 3.13 in `python/.venv`.
- Node.js 22.13 or newer.
- 8 GiB RAM minimum; 16 GiB is recommended for local ASR, TTS, or embedding models.
- Docker is optional and only needed when Qdrant auto-start is requested.

## Quick start

Windows:

```powershell
.\install.bat core
.\start.bat
```

Linux:

```bash
./install.sh core
./start.sh
```

Useful launcher flags:

```text
--check          preflight without launching services
--verify         run the supported verification suite without launching services
--dev-renderer   use the Vite renderer during development
--smoke          run lightweight health/pet/MCP endpoint checks after startup
--with-qdrant    start Qdrant through Docker when available (Windows launcher)
--no-mcp         opt out of the default MCP service
--no-show-pet    leave the pet layer hidden after startup (Windows launcher)
--no-open        do not open the control panel automatically (Windows launcher)
```

Copy `python/.env.example` to `python/.env` and configure a text provider. OpenAI-compatible local servers such as Ollama and LM Studio use the same fields:

```dotenv
LLM_PROVIDER=custom
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_API_KEY=local
LLM_MODEL=your-model
```

## Interaction and latency model

Voice uses one microphone capture path. Local audio processing can emit an immediate speech-start signal while the provider owns turn finalization. On barge-in, the renderer invalidates the old output generation, stops queued audio, resets lip-sync, cancels the provider response, and ignores late chunks. Session, turn, request, and interruption identifiers prevent cross-session or stale-result updates.

TTS chunks are ordered by sequence number. WAV duration is supplied by the backend when known and falls back to browser media duration for legacy payloads. Audio, Agent work, and pet animation are asynchronous lanes; a slow tool or TTS segment does not freeze the chat input.

## Vision boundary

Vision is disabled unless enabled in settings and requested by an Agent turn. The lifecycle is `requested -> captured -> analyzed -> completed` or `discarded`. Frames are held in memory for the request and are not written to chat history by default.

## Data locations

| Data | Default location | Notes |
| --- | --- | --- |
| Chat database | `python/data/chat.db` | Local SQLite persistence |
| Memory database | `python/data/memory.db` | Correctable and forgettable records |
| Settings | `python/config/settings.json` | Local runtime configuration |
| TTS cache | `python/audio_cache/` | Removable temporary artifacts |
| Vision frames | process memory | Request-scoped by default |

Cloud providers receive only the payloads required by the selected feature. Local providers keep those payloads on the machine.

## Verification status

The latest verified Electron baseline is 133 test files and 793 tests, plus TypeScript type-check, ESLint, production build, renderer bundle audit, and `git diff --check`. Python targeted settings/TTS/realtime tests previously passed (75 tests). A socket contract test remains environment-limited when `python-socketio` is absent; real microphone, speaker, provider credentials, and multiple hardware models still require machine-level validation.

Run the checks locally:

```powershell
cd electron
npm run type-check
npm run lint
npm test
npm run build

cd ..\python
python -m pytest -q tests test_*.py
python -m compileall -q modules app.py socket_server.py
```

## Status and non-goals

The core local companion loop is implemented. Discord/Telegram connectors, PWA/mobile clients, browser extensions, game-specific agents, and a broad external TTS catalog remain future integrations. They are not advertised as completed features.

The design direction is informed by AIRI (pinned implementation reference), OpenAI Realtime WebRTC/VAD guidance, MDN Web Audio APIs, LiveKit turn-taking guidance, and 2024-2026 work on low-latency voice, interruption handling, asynchronous tools, visual memory, and embodied agents. See the linked design and API documents for source URLs and boundaries.

## License

Source code is MIT-licensed. Live2D/VRM models, voices, fonts, artwork, and downloaded model weights may have separate licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) before redistribution.
