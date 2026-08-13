# Quick start

This guide gets a local text-chat installation running. Voice, vision, semantic retrieval, and SoulX are optional extensions.

## Windows

```powershell
.\install.bat core
Copy-Item python/.env.example python/.env
notepad python/.env
.\start.bat --check --no-pause
.\start.bat
```

Use `.\install.bat full` when you need the optional ASR, Genie-TTS, Qdrant, embedding, and model helper packages.

## Linux

```bash
./install.sh core
cp python/.env.example python/.env
$EDITOR python/.env
./start.sh --check
./start.sh
```

See [LINUX.md](LINUX.md) before troubleshooting audio, Wayland, or GPU behavior.

## Minimum provider configuration

Set these fields in `python/.env`:

```dotenv
LLM_PROVIDER=custom
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_API_KEY=local
LLM_MODEL=your-model
```

The endpoint must implement the OpenAI-compatible chat contract expected by the configured adapter. Remote providers may require a real key.

## Launcher modes

`--check` performs preflight only. `--verify` runs the supported verification suite. `--smoke` adds health, pet, and MCP checks after startup. `--dev-renderer` uses Vite. MCP is enabled by default; `--no-mcp` opts out. Windows also supports `--with-qdrant`, `--no-show-pet`, and `--no-open`.

## First checks after startup

1. Confirm the control panel opens and the pet window is visible.
2. Check `/api/ping` for liveness and `/health` for component status.
3. Configure or select a model in Settings.
4. Send a text message before enabling optional voice or tools.
5. Review MCP/plugin permissions before enabling external actions.

## Common failures

- Missing `python/.venv`: rerun the installer.
- Node version too old: install Node.js 22.13+.
- Port conflict: set `SERVER_PORT`, `CONTROL_SERVER_PORT`, `RENDERER_PORT`, or `MCP_PORT`.
- Blank pet: verify the model path, renderer logs, and model license.
- No voice: verify permissions, provider configuration, model resources, and audio devices.
- Degraded health: treat optional ASR/TTS/Qdrant status as a configuration signal, not as a successful voice claim.
