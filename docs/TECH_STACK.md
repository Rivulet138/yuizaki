# Technology stack

## Desktop and renderer

- Electron `^42.7.0`
- Vue `^3.5.35`, Vue Router `^5.1.0`, Pinia `^3.0.4`, TypeScript `^6.0.3`
- Vite `^8.0.16`, Vitest `^4.1.8`, ESLint `^10.4.1`, Prettier `^3.8.3`
- PixiJS `^8.19.0` and easy-live2d `^0.4.4` for Live2D
- Three.js `^0.184.0` and `@pixiv/three-vrm` `^3.5.3` for VRM
- Socket.IO client `^4.8.3` for realtime events; native Electron bridges handle host capabilities
- AudioWorklet and renderer capture/playback modules under `electron/src/renderer/audio`

Authoritative versions are in `electron/package.json:34-72`. Runtime entry and
build boundaries are defined by `electron/package.json:13-32`.

## Backend

- Python 3.11-3.13 compatibility is exercised by the lock matrix and pyright configuration.
- FastAPI, Pydantic, Uvicorn, HTTPX, aiofiles, multipart, and python-socketio for API and realtime transport.
- SQLAlchemy and Alembic for local persistence and migrations.
- SQLite repositories for chat, turn commits, settings metadata, and memory.
- NumPy and Pillow for media foundations.
- Optional Sherpa ONNX, RapidOCR, Genie-TTS, Qdrant, sentence-transformers, and tiktoken.

The compatible ranges are declared in `python/requirements.txt:8-34`; runtime
composition is wired in `python/app.py` and `python/modules/agent/runtime.py`.

## Runtime constraints

Provider adapters isolate wire protocols in `python/modules/llm`, `python/modules/asr`,
`python/modules/tts`, and `python/modules/ocr`. Audio, Job, perception, and
avatar state use explicit session/turn/request/generation identities and
terminal events. Frame-level animation remains local to the renderer; the LLM
emits intent-level commands through `pet_control.py` and companion event bridges.

## Architecture fit and risks

| Choice | Benefit | Risk/control |
|---|---|---|
| Electron + Python split | Strong native-window and AI/media ecosystem coverage | Startup, packaging, token handoff, process shutdown, and platform-specific dependencies; validate through `electron/src/main/python.ts` and launcher checks |
| Socket.IO event transport | Suitable for audio, deltas, Jobs, traces, and Avatar events | Event drift across Python and TypeScript; update contract tests in both trees |
| SQLite authority + optional vector projection | Local/offline operation and rebuildable retrieval | Index freshness and concurrent writes; use `turn_outbox.py`, migration tests, and rebuild verification |
| MCP/plugins | Broad tool ecosystem | Disabled services expose no tools; enabling a service or plugin authorizes its declared scope without per-call prompts, while all returned content remains untrusted input |
| Live2D/VRM adapters | Rich embodiment without per-frame LLM calls | Asset licensing and GPU/driver variance; test adapters on target machines |

## Cross-platform boundary

The product shell targets Windows and Linux. Native desktop actions have a
Windows user32 adapter and a Linux X11 adapter
(`python/modules/agent/desktop_actions.py:193-196`, `:358-542`); pure Wayland
and unsupported platforms fail closed, and macOS has no adapter. Treat platform
support as capability-level, not a blanket feature guarantee. Add a macOS
adapter and platform-specific permission/postcondition tests before claiming
equivalent Computer Use behavior.

## 中文说明

技术栈包括 Electron、Vue、Vite、Pinia、PixiJS、Three.js/VRM、FastAPI、Socket.IO、SQLAlchemy、SQLite，以及可选的 Sherpa ONNX、Genie TTS、Qdrant、MCP 和 SoulX 服务。各模块保持可替换边界，使核心桌面聊天链路无需安装可选模型服务即可运行；语音、视觉、检索和桌宠质量仍取决于本机设备、提供商配置、模型资源与资产许可证。
