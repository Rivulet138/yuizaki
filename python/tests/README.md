# Python verification

The Python suite is a contract suite for settings, authentication, memory, summaries, realtime events, vision, audio, tools, plugins, storage cleanup, and cross-layer behavior.

## Run the suite

From the repository root:

```powershell
cd python
.\.venv\Scripts\python.exe -m pytest -q --tb=short
```

Linux:

```bash
cd python
.venv/bin/python -m pytest -q --tb=short
```

## Targeted checks

```bash
python -m pytest -q tests/test_settings_api_router.py
python -m pytest -q tests/test_realtime_session_config.py
python -m pytest -q tests/test_tts_openai_compatible.py
```

## Test boundary

External models, Docker, network services, microphones, speakers, and GPUs must be mocked or explicitly provisioned. A passing test suite verifies software contracts; it does not certify a particular provider, audio device, model, or avatar asset.

Do not write fixtures into `python/data`. Use temporary directories. Changes to Socket.IO events, deletion, restore, or cancellation semantics require contract coverage.
