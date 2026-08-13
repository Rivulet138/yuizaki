# Environment setup

## Runtime versions

- Python 3.11-3.13, preferably in `python/.venv`.
- Node.js 22.13+ and npm.
- Windows 10/11 or x86_64 Linux.
- Docker only for optional Qdrant auto-start.

## Python environment

Install a core runtime for chat, SQLite, OCR, and server features:

```powershell
python -m venv python/.venv
python/.venv/Scripts/python -m pip install -r python/requirements-core.txt
```

Use `requirements.txt` or `install.bat full` for Sherpa ONNX, Genie-TTS, Qdrant, embeddings, and related optional stacks. Platform lock files pin the tested resolution; the manifests keep compatible lower and upper bounds for slightly older environments.

## `.env`

Copy `python/.env.example` to `python/.env`. Configure a text provider, then optionally configure TTS, ASR, memory, Qdrant, and vision. Keep `VISION_LLM_ENABLED=0` unless a visual Agent workflow is needed. Set `TTS_STARTUP_MODE=lazy` and `TTS_WARMUP_ENABLED=0` on constrained hardware.

## Providers

`LLM_PROVIDER=custom` targets OpenAI-compatible chat endpoints. TTS supports `genie-tts` and `openai-compatible`. ASR defaults to Sherpa ONNX when the optional package/model is available. SoulX-SVC is an HTTP service and is not installed by the core dependency set.

## Frontend variables

The launcher exports `VITE_YUIZAKI_API_ORIGIN`, `VITE_YUIZAKI_CONTROL_ORIGIN`, `SERVER_PORT`, `CONTROL_SERVER_PORT`, `RENDERER_PORT`, and `MCP_PORT`. Avoid hard-coding fallback ports in application code.

## Model assets

Store Live2D/VRM assets and local model caches outside Git. The startup path restores the saved model reference when the file is present; missing assets are reported in the pet/resource panel.
