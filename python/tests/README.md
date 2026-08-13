# Python tests

The Python suite covers settings, authentication boundaries, memory, summaries, realtime events, vision, audio, tools, plugins, resource cleanup, and cross-layer contracts.

Run from the repository root:

```powershell
cd python
.\\.venv\\Scripts\\python.exe -m pytest -q --tb=short
```

Linux:

```bash
cd python
.venv/bin/python -m pytest -q --tb=short
```

Targeted examples:

```bash
python -m pytest -q tests/test_settings_api_router.py
python -m pytest -q tests/test_realtime_session_config.py
python -m pytest -q tests/test_tts_openai_compatible.py
```

Tests that require external models, Docker, network services, microphone, speakers, or GPU must be marked or mocked explicitly. Do not write fixtures into `python/data`; use a temporary directory. Changes to Socket.IO events, permanent deletion, restore, or cancellation semantics require contract coverage.
