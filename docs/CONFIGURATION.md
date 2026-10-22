# 配置 / Configuration

## 中文概览

本地配置位于 `python/.env` 和 `python/config/settings.json`；启动器根据 `python/.env.example` 创建环境文件，凭据不得提交或写入日志。安装配置分为 `core` 和 `full`，模型权重在首次运行时从锁定来源下载，不嵌入安装包。

- LLM 使用 OpenAI 兼容端点；视觉默认关闭且只处理当前请求的帧。
- 完整语音链路需要麦克风、ASR、LLM、TTS 和对应模型；Sherpa、Genie、Embedding 等资源按需加载。
- SQLite 是默认记忆权威源；Qdrant 仅作为可重建语义索引，纠正、遗忘和永久删除应通过 UI/API 完成。
- MCP 浏览器自动化默认关闭，需要 `--with-mcp`；SoulX 变声服务是可选组件，不影响文字、ASR 和默认 TTS 路径。
- 服务默认绑定回环地址。`YUIZAKI_BACKEND_API_TOKEN` 只保护可选非回环访问；桌面动作另用 `YUIZAKI_HOST_DESKTOP_ACTION_TOKEN`，两者必须分离。
- Telegram、Discord、QQ 个人桥和微信个人桥默认关闭；启用连接器即授权其声明的收发流程，状态接口不会返回密钥。
- Live2D/VRM、模型权重、声音和缓存默认不进入 Git；分发前阅读 [第三方声明](../THIRD_PARTY_NOTICES.md)。

Yuizaki stores local runtime configuration in `python/.env` and `python/config/settings.json`. The launcher creates `python/.env` from `python/.env.example`; keep credentials out of Git and logs.

Yuizaki 将本地运行配置保存在 `python/.env` 和 `python/config/settings.json`。启动器会根据 `python/.env.example` 创建环境文件；不要提交或记录凭据。

## Install profiles / 安装配置

| Profile | Contents |
| --- | --- |
| `core` | Backend, SQLite, OCR foundations, Electron, and required runtime packages |
| `full` | Core plus Sherpa ASR, Genie TTS, embeddings, Qdrant, and model helpers |

The launcher selects the platform lock file under `python/`, installs Electron with `npm ci`, creates `python/.venv`, and validates the installed packages. Electron and node-mcp are installed with `npm ci`; the node-mcp install runs only when MCP is enabled for that launch. Use `YUIZAKI_INSTALL_PROFILE=full` before setup so the local ASR/TTS/embedding dependencies are installed. The model weights themselves remain first-run downloads in Settings > Resources and are not embedded in the installer. Native model compatibility still depends on the operating system, CPU, GPU, and model files.

Launcher builds require Go 1.27+ (`tools/yuizaki-launcher/go.mod`); the release workflows pin the same version.

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

For OpenLux, select `provider=custom`, `base_url=https://api.openlux.ai/v1`, and
`model=deepseek-v4.1-flash`. Keep `api_key` empty in settings. Supply the key to the backend
through `YUIZAKI_PROVIDER_CREDENTIALS_JSON`, a JSON object whose `llm.api_key` entry is injected
into memory (for example, `{"llm.api_key":"<provider-key>"}`). Credential values are scrubbed
before settings/history persistence and are not returned by settings snapshots. Named provider
profiles remain independent of this active selection.

Vision is separate and disabled by default:

```dotenv
VISION_LLM_ENABLED=0
VISION_LLM_PROVIDER=custom
VISION_LLM_BASE_URL=
VISION_LLM_API_KEY=
VISION_LLM_MODEL=
```

Enabling vision does not create a permanent capture loop. Frames remain request-scoped and require the relevant application flow.

## DSH delegation / DSH 任务委托

The optional DSH Agent plugin exposes `ask_dsh` for explicitly requested coding,
file-editing, test, and repository-analysis tasks, not ordinary companion chat. Install DSH separately
and configure its `headless` profile using DSH's own credential storage. Yuizaki does not copy its
provider key into DSH or modify DSH profiles.

| Variable | Default | Meaning |
| --- | --- | --- |
| `YUIZAKI_DSH_COMMAND` | Auto-discovered local DSH | JSON argv array for the executable and fixed arguments, without the task or profile arguments; not a shell command |
| `YUIZAKI_DSH_TIMEOUT_S` | `180` | Maximum subprocess runtime in seconds |
| `YUIZAKI_DSH_MAX_OUTPUT_CHARS` | `8000` | Maximum returned output, retaining the beginning and end |

On Windows the command is Node plus the JS entry, never a directly spawned `dsh.cmd`. An explicit
override looks like `["node","C:/Users/<user>/AppData/Roaming/npm/node_modules/@deepseek-ai/dsh/lib/bin.js"]`.
The bridge appends `--profile`, `headless`, and the task as separate argv entries, without a shell.
Tasks must be nonempty, at most 4000 characters, and must not begin with `--`.
The child inherits the MCP stdio environment whitelist plus explicitly allowed DSH provider keys
(`DEEPSEEK_API_KEY`, `OP_API_KEY`, `ROAI_API_KEY`, `OPENLUX_API_KEY`); no `YUIZAKI_*` variable is
forwarded. One DSH process runs at a time; a queue wait longer than 30 seconds returns `dsh_busy`.
Timeout and cancellation kill and await the child. A failed or interrupted delegation may already
have changed files: inspect the result before trying again. Each invocation may consume provider
tokens and create a persistent session under `~/.dsh/sessions`; manage those sessions with DSH.

## Voice / 语音

The full voice path requires all of the following:

- a microphone and speaker available to the desktop session;
- a configured ASR provider and model;
- a working LLM provider;
- a configured TTS provider and voice.

The default local providers are selected with `ASR_PROVIDER=sherpa-onnx` and `TTS_PROVIDER=genie-tts`. `sherpa-onnx` uses the offline SenseVoice model under `python/.cache/sherpa-onnx/sensevoice`. Use `ASR_PROVIDER=sherpa-onnx-online` only when the separate Zipformer streaming resources under `python/.cache/sherpa-onnx/streaming-zipformer-small-ctc-zh` are installed. Genie uses the built-in fixed character mode by default; leave `TTS_GENIE_MODEL_DIR` empty to use it. Set that variable only for a custom character directory. In the UI, use **Settings → Resources → Genie TTS Assets → Prefetch Genie Assets**. Source checkouts store shared Genie data under `python/.cache/GenieData/GenieData` and character bundles under `python/CharacterModels/v2ProPlus/<character>`; packaged runs use the writable Electron `userData/python-data` equivalents. An OpenAI-compatible speech service uses `TTS_PROVIDER=openai-compatible`, `TTS_BASE_URL`, `TTS_API_KEY`, `TTS_MODEL`, and `TTS_VOICE`.

ASR providers available in Settings are:

| Provider | Use | Required settings |
| --- | --- | --- |
| `sherpa-onnx` | Local offline SenseVoice ONNX; recommended default | Sherpa model and tokens under `python/.cache/sherpa-onnx/sensevoice` |
| `sherpa-onnx-online` | Streaming Zipformer recognition with SenseVoice final refinement | Separate Zipformer model and tokens under `python/.cache/sherpa-onnx/streaming-zipformer-small-ctc-zh` |
| `sensevoice-local` | Local FunASR/ModelScope SenseVoice | `SENSEVOICE_MODEL`, `SENSEVOICE_DEVICE`, and the `funasr` runtime |
| `sensevoice-service` | SenseVoice/FunASR HTTP service | `ASR_BASE_URL`, optional `ASR_API_KEY`, `SENSEVOICE_MODEL` |
| `funasr-service` | OpenAI-compatible FunASR HTTP service | `ASR_BASE_URL`, optional `ASR_API_KEY`, `SENSEVOICE_MODEL` |
| `openai-compatible` | Any compatible `/v1/audio/transcriptions` service | `ASR_BASE_URL`, `ASR_API_KEY`, `SENSEVOICE_MODEL` |
| `disabled` | Disable microphone transcription | None |

For Sherpa, `SHERPA_ONNX_MODEL_PATH` and `SHERPA_ONNX_TOKENS_PATH` may override the managed paths. Keep `SHERPA_ONNX_PROVIDER=cpu` unless the installed runtime and model support CUDA/Core ML. `SHERPA_ONNX_NUM_THREADS=2` is a good CPU starting point; use `4` on a capable machine. The UI Settings > ASR section writes these values to `python/config/settings.json`, which takes precedence over environment defaults after saving and restarting the backend.

Keep optional models lazy on constrained machines:

```dotenv
ASR_STARTUP_MODE=lazy
TTS_STARTUP_MODE=lazy
TTS_WARMUP_ENABLED=0
```

Runtime diagnostics can show configuration and recorded timing evidence, but repository fixtures do not qualify a real microphone, speaker, provider, or model combination.

## MCP and browser automation / MCP 与浏览器自动化

`node-mcp` is an optional Playwright service that exposes `browser.open_page` and `browser.click`. The launcher leaves it stopped by default. Start it with `--with-mcp` or `YUIZAKI_WITH_MCP=1`; `--no-mcp` forces it off even when the environment enables it. The service listens on `127.0.0.1:${MCP_PORT}` (default `7777`) and offers `POST /tools`, `GET /events` (SSE) and a `--stdio` line mode for a supervised process.

| Variable | Default | Meaning |
| --- | --- | --- |
| `MCP_PORT` | `7777` | Loopback HTTP port |
| `MCP_BROWSER_TIMEOUT_MS` | `30000` | Per-operation and queue timeout, capped at `120000` |
| `MCP_MAX_CONCURRENT_BROWSERS` | `2` | Concurrent browser limit, capped at `16` |

MCP is disabled by default because it launches a real browser that can reach public sites and consume memory. Its tools accept only HTTP(S) URLs without embedded credentials, resolve the hostname, and reject loopback, private, link-local, and cloud-metadata destinations for each request; JSON bodies are capped at 64 KiB, SSE clients at 64, `requestId` at 128 characters, URL at 2048 characters, and selector at 1024 characters; errors are sanitized. In `--stdio` mode each input line is capped at 64 KiB with a 128 KiB total buffer. This is a request-target filter, not a network sandbox. See [Security](../SECURITY.md) for the boundary.

If `node-mcp` is not installed because MCP was disabled during setup, enabling it later installs the dependencies on the next launcher start.

## SVC and SoulX / 变声与 SoulX

The optional SoulX Singer service converts a generated voice clip. It is not required for text chat, ASR, or the default TTS path.

```dotenv
SVC_PROVIDER=soulx-service
SVC_BASE_URL=http://127.0.0.1:7861
SVC_SPEAKER_ID=0
SVC_PITCH=0
SVC_TIMEOUT=120
```

Use `SVC_PROVIDER=disabled` to turn voice conversion off; the available providers are `soulx-service` and `disabled`.

The service side uses `SOULX_ROOT`, `SOULX_MODEL_DIR`, `SOULX_PREPROCESS_DIR`, `SOULX_HOST` (default `127.0.0.1`), `SOULX_PORT` (default `7861`), `SOULX_AUTH_TOKEN`, upload/step/output limits, and the optional CUDA/FP16 switches documented in [`services/soulx-svc/README.md`](../services/soulx-svc/README.md). It binds to loopback by default; a non-loopback `SOULX_HOST` requires `SOULX_AUTH_TOKEN` and the process refuses to start without it.

`POST /api/settings/test/svc` probes the configured base URL. For safety it accepts only public hostnames or `localhost` that resolves to loopback, re-validates every redirect (at most three), and rejects literal loopback or private IP addresses. That means the default `SVC_BASE_URL=http://127.0.0.1:7861` cannot be probed from that button; use `http://localhost:7861` for a local probe or treat the probe as a remote-endpoint check.

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
| `MCP_PORT` | `7777` | Default node-mcp service; used only when MCP is enabled |

The launcher may select a fallback port when a default is occupied and passes the chosen origins to the application. Do not hard-code these defaults in clients.

The default services bind to loopback. Python loopback HTTP and Socket.IO traffic follows the desktop trust model. Electron routed control APIs require the control token in `Authorization: Bearer ...` or `x-yuizaki-backend-token`; health and approved pet-asset GET paths are public. A `control_token` query parameter is accepted only for a loopback GET without an `Origin` header, for the browser bootstrap. `YUIZAKI_BACKEND_API_TOKEN` protects optional non-loopback Python and Socket.IO access; it does not turn Yuizaki into a hardened public service.

Desktop action controls are a narrower capability than the general loopback API. Electron generates `YUIZAKI_HOST_DESKTOP_ACTION_TOKEN` at startup and sends it only to the managed Python child and desktop-action bridge. `/api/desktop-actions/*` rejects missing, malformed, incorrect, or backend-token-reused credentials. When Python is managed externally, set the same sufficiently random value in the Electron and Python environments; otherwise desktop actions remain unavailable by design. Keep this token separate from `YUIZAKI_BACKEND_API_TOKEN` and never put either value in logs or source control.

## Database bootstrap and migrations / 数据库启动迁移

The launcher runs `python/migration_bootstrap.py` before starting backend traffic. The script reads the current Alembic head from `python/alembic/versions` at runtime rather than embedding a date-based revision in application code or tests.

- An empty database is created at the current head.
- A database with a trusted Alembic revision is upgraded to the current head and its schema is checked.
- An existing database with tables but no trusted revision is rejected instead of being guessed or silently rebuilt.
- The turn idempotency index is scoped by `session_id`, `turn_idempotency_key`, and `role`; an existing idempotent turn is reused only when it belongs to the same workspace. Databases at the previous migration are upgraded to this shape.

Run the launcher setup or the bootstrap script again after installing a new version. Do not edit the SQLite schema while the backend is running.

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

Live2D/VRM assets, model weights, voices, and generated caches stay outside Git unless their exact licenses allow redistribution. Sherpa, Embedding, and Genie are marked `requiredOnFirstRun` in `resources.lock.json`; Genie is marked `mode: builtin`, so its package and fixed character assets are prepared locally from the pinned official source. The settings resource panel preselects missing entries and downloads them through the locked source/revision path. Startup restores saved avatar references when the files still exist; missing assets are reported in the application.

Default local data includes:

- `python/data/` for chat, memory, and runtime databases;
- `python/config/` for persisted settings;
- `python/audio_cache/` for generated audio;
- provider-specific model and cache directories.

`YUIZAKI_DATA_DIR` relocates the data root and, unless `YUIZAKI_SETTINGS_PATH` is set, also moves `settings.json` beside it. `DATABASE_URL` overrides only the chat database, `MEMORY_SQLITE_PATH` only the memory database, and `YUIZAKI_ALLOWED_ORIGINS` lists the allowed browser origins for Python and the Electron control service. Explicit documented overrides affect only their own target.

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

The manually dispatched release workflow is gated by repository variables `RELEASE_QUALIFIED` and `RELEASE_SIGNING_READY`; each package job fails until both are `true`. It builds Windows NSIS and Linux AppImage/deb artifacts, writes `SHA256SUMS.txt`, uploads the artifacts, and attests build provenance with `actions/attest-build-provenance`. It does not create a GitHub Release automatically. Workflow actions are pinned to commit SHAs.
