# Python verification / Python 验证

Python 测试套件用于验证设置、认证、记忆、摘要、实时事件、视觉、音频、工具、插件、存储清理及跨层行为契约。

The Python suite is a contract suite for settings, authentication, memory, summaries, realtime events, vision, audio, tools, plugins, storage cleanup, and cross-layer behavior.

## Run the suite / 运行测试套件

从仓库根目录运行：

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

## Targeted checks / 定向检查

```bash
python -m pytest -q tests/test_settings_api_router.py
python -m pytest -q tests/test_realtime_session_config.py
python -m pytest -q tests/test_tts_openai_compatible.py
```

## Test boundary / 测试边界

外部模型、Docker、网络服务、麦克风、扬声器和 GPU 必须进行 mock 或显式配置。测试套件通过只能证明软件契约，不代表特定服务商、音频设备、模型或虚拟形象资源已获认证。

External models, Docker, network services, microphones, speakers, and GPUs must be mocked or explicitly provisioned. A passing test suite verifies software contracts; it does not certify a particular provider, audio device, model, or avatar asset.

不要将 fixture 写入 `python/data`，请使用临时目录。对 Socket.IO 事件、删除、恢复或取消语义的改动必须补充契约覆盖。

Do not write fixtures into `python/data`. Use temporary directories. Changes to Socket.IO events, deletion, restore, or cancellation semantics require contract coverage.
