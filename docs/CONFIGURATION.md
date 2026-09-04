# Configuration / 配置

Yuizaki stores local runtime configuration in `python/.env` and `python/config/settings.json`. The launcher creates `python/.env` from `python/.env.example`; keep credentials out of Git and logs.

Yuizaki 将本地运行配置保存在 `python/.env` 和 `python/config/settings.json`。启动器会根据 `python/.env.example` 创建环境文件；不要提交或记录凭据。

## Install profiles / 安装配置

| Profile | Contents |
| --- | --- |
| `core` | Backend, SQLite, OCR foundations, Electron, and required runtime packages |
| `full` | Core plus Sherpa ASR, Genie TTS, embeddings, Qdrant, and model helpers |

The launcher selects the platform lock file under `python/`, installs Electron and node-mcp with `npm ci`, creates `python/.venv`, and validates the installed packages. Use `YUIZAKI_INSTALL_PROFILE=full` before setup so the local ASR/TTS/embedding dependencies are installed. The model weights themselves remain first-run downloads in Settings > Resources and are not embedded in the installer. Native model compatibility still depends on the operating system, CPU, GPU, and model files.

## LLM / 大语言模型

Configure an OpenAI-compatible local or remote endpoint:

```dotenv
LLM_PROVIDER=custom
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_API_KEY=local
LLM_MODEL=your-model
LLM_TIMEOUT=60
```

Remote providers normally require a real key. The configured endpoint must implement the OpenAI-compatible chat contract used by the adapter.

Vision is separate and disabled by default:

```dotenv
VISION_LLM_ENABLED=0
VISION_LLM_PROVIDER=custom
VISION_LLM_BASE_URL=
VISION_LLM_API_KEY=
VISION_LLM_MODEL=
```

Enabling vision does not create a permanent capture loop. Frames remain request-scoped and require the relevant application flow.

## Voice / 语音

The full voice path requires all of the following:

- a microphone and speaker available to the desktop session;
- a configured ASR provider and model;
- a working LLM provider;
- a configured TTS provider and voice.

The default local providers are selected with `ASR_PROVIDER=sherpa-onnx-online` and `TTS_PROVIDER=genie-tts`. An OpenAI-compatible speech service uses `TTS_PROVIDER=openai-compatible`, `TTS_BASE_URL`, `TTS_API_KEY`, `TTS_MODEL`, and `TTS_VOICE`.

Keep optional models lazy on constrained machines:

```dotenv
ASR_STARTUP_MODE=lazy
TTS_STARTUP_MODE=lazy
TTS_WARMUP_ENABLED=0
```

Runtime diagnostics can show configuration and recorded timing evidence, but repository fixtures do not qualify a real microphone, speaker, provider, or model combination.

## Memory and Qdrant / 记忆与 Qdrant

SQLite is the default memory authority:

```dotenv
MEMORY_BACKEND=sqlite
MEMORY_SQLITE_PATH=./data/memory.db
```

Qdrant is optional and acts as a rebuildable semantic index, not the source of truth:

```dotenv
QDRANT_URL=http://127.0.0.1:6333
QDRANT_COLLECTION=memories
QDRANT_AUTO_START=0
```

Use `--with-qdrant` on Windows to request the configured Docker service. Memory correction, soft forgetting, and permanent deletion should be performed through the application UI or API, not by editing SQLite while the service is running.

## Ports and local access / 端口与本机访问

| Variable | Default | Service |
| --- | --- | --- |
| `SERVER_PORT` | `8001` | Python HTTP and Socket.IO backend |
| `CONTROL_SERVER_PORT` | `38945` | Electron control service |
| `RENDERER_PORT` | `5173` | Vite renderer in development |
| `MCP_PORT` | `7777` | Default node-mcp service |

The launcher may select a fallback port when a default is occupied and passes the chosen origins to the application. Do not hard-code these defaults in clients.

The default services bind to loopback. Loopback HTTP and Socket.IO clients are trusted by the desktop runtime. `YUIZAKI_BACKEND_API_TOKEN` protects optional non-loopback access; it does not turn Yuizaki into a hardened public service.

## Connectors / 消息连接器

Telegram, Discord, QQ personal bridge, and WeChat personal bridge adapters are experimental and disabled until enabled in the governance panel.

| Connector | Required configuration |
| --- | --- |
| Telegram | Bot Token and Webhook Secret |
| Discord | Ed25519 Public Key; optional Bot Token for an expired interaction fallback |
| QQ personal bridge | Local bridge URL, protocol, and Bridge Token |
| WeChat personal bridge | Local bridge URL, protocol, and Bridge Token |

Enabling a connector authorizes its declared inbound message and outbound reply flow without per-message approval. Stored secrets are not returned by status APIs. QQ and WeChat personal bridges are not official platform APIs and require separate local compatibility testing.

## Avatars, models, and caches / 角色、模型与缓存

Live2D/VRM assets, model weights, voices, and generated caches stay outside Git unless their exact licenses allow redistribution. Sherpa, Embedding, and Genie are marked `requiredOnFirstRun` in `resources.lock.json`; the settings resource panel preselects missing entries and downloads them through the locked source/checksum path. Startup restores saved avatar references when the files still exist; missing assets are reported in the application.

Default local data includes:

- `python/data/` for chat, memory, and runtime databases;
- `python/config/` for persisted settings;
- `python/audio_cache/` for generated audio;
- provider-specific model and cache directories.

Use application cleanup and backup flows while services are running. Review [Third-party notices](../THIRD_PARTY_NOTICES.md) before distributing any model, voice, font, artwork, or avatar.

## Packaging / 打包

Electron Builder scripts create local installers:

```powershell
cd electron
npm run package:win
```

```bash
cd electron
npm run package:linux
```

The manually dispatched release workflow uploads Windows NSIS and Linux AppImage/deb artifacts to GitHub Actions. It does not create a GitHub Release automatically.
