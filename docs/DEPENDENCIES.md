# Dependencies

## Source of truth

- Electron versions: `electron/package.json` and `electron/package-lock.json`.
- Python compatible ranges: `python/requirements-core.txt` and `python/requirements.txt`.
- Platform resolutions: `python/requirements-core-lock-windows.txt`, `requirements-core-lock-linux.txt`, and full/dev variants.

## Compatibility policy

Keep the lower bounds compatible with Python 3.11 and Node 22.13. Prefer an existing slightly older compatible version over a major upgrade unless the current runtime or security fix requires it. Do not add a dependency for a feature already covered by local adapters or browser APIs.

## Install profiles

- `core`: FastAPI, SQLite, OCR foundation, and server runtime.
- `full`: core plus ASR, Genie-TTS, Qdrant, embeddings, and model helpers.
- `dev`: test, lint, and build tooling.

Optional native model backends are intentionally not installed by default because CUDA and platform builds vary widely.
