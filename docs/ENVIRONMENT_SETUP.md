# Environment setup

## Supported runtime

- Python 3.11-3.13, preferably in `python/.venv`.
- Node.js 22.13+ and npm.
- Windows 10/11 or x86_64 Linux with a desktop session.
- Docker only for optional Qdrant or SoulX workflows.

## Install profiles

`core` installs the server, SQLite, OCR foundation, and required runtime. `full` adds optional ASR, Genie-TTS, Qdrant, embedding, and model helpers. Platform lock files record tested resolutions; native model packages can still vary by CPU, GPU, and operating system.

Windows:

```powershell
.\install.bat core
# or
.\install.bat full
```

Linux:

```bash
./install.sh core
# or
./install.sh full
```

## Local environment file

```powershell
Copy-Item python/.env.example python/.env
```

Configure an LLM first. Then configure TTS, ASR, memory, Qdrant, and vision only as needed. Keep `VISION_LLM_ENABLED=0` unless a visual Agent workflow is deliberate. On constrained hardware use `TTS_STARTUP_MODE=lazy`, `TTS_WARMUP_ENABLED=0`, and `ASR_STARTUP_MODE=lazy`.

## Provider boundaries

- `LLM_PROVIDER=custom` targets OpenAI-compatible chat endpoints.
- `TTS_PROVIDER=genie-tts` uses the optional local Genie runtime.
- `TTS_PROVIDER=openai-compatible` targets `/v1/audio/speech`.
- `ASR_PROVIDER=sherpa-onnx-online` uses a local model when installed and configured.
- SoulX-SVC is an external HTTP service and is not part of the core install.

## Frontend variables

The launcher exports `VITE_YUIZAKI_API_ORIGIN`, `VITE_YUIZAKI_CONTROL_ORIGIN`, `SERVER_PORT`, `CONTROL_SERVER_PORT`, `RENDERER_PORT`, and `MCP_PORT`. Keep port selection in the launcher rather than hard-coding fallback ports in application code.

## Assets and caches

Store Live2D/VRM assets and model caches outside Git. Startup restores the saved model reference when the asset exists; missing assets are reported in the pet/resource panel. Read [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) before redistributing any asset or weight.
