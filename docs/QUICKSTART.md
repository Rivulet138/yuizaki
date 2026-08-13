# Quick start

## Windows

```powershell
.\install.bat core
.\start.bat
```

Use `full` when you want optional local ASR, embedding, and vector dependencies:

```powershell
.\install.bat full
```

The normal launcher starts the backend, Electron control service, pet layer, and MCP service. It restores the last selected Live2D or VRM model when the saved model is available.

## Linux

```bash
./install.sh core
./start.sh
```

Linux support depends on the desktop session, audio device, and Electron GPU stack. See [LINUX.md](LINUX.md).

## Launcher flags

`--check` runs preflight only. `--verify` runs the supported type-check/build/test path without launching services. `--smoke` performs health, pet, and MCP endpoint checks after startup. `--dev-renderer` serves the renderer through Vite. MCP is on by default; `--no-mcp` opts out. Windows also supports `--with-qdrant`, `--no-show-pet`, and `--no-open`.

## Local configuration

```powershell
Copy-Item python/.env.example python/.env
```

Configure `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL`. Keep secrets in the local `.env` or settings panel. `TTS_PROVIDER=genie-tts` is the default; `TTS_PROVIDER=openai-compatible` uses `/v1/audio/speech`.

## Startup failures

- Missing `python/.venv`: run `install.bat core` or `install.sh core`.
- Node version too old: install Node.js 22.13+.
- MCP dependencies missing: run `npm install` in `node-mcp`, or pass `--no-mcp` intentionally.
- Port conflict: set `SERVER_PORT`, `CONTROL_SERVER_PORT`, `RENDERER_PORT`, or `MCP_PORT`; Windows also has fallback lists.
- Blank pet: use the control panel to reload the model and verify the asset path and renderer logs.
- No voice: grant microphone permission and verify the selected provider/model; unit tests do not replace a real audio-device check.
