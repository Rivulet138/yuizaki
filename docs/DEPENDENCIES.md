# Dependencies

## Authoritative files

- Electron versions and resolutions: `electron/package.json` and `electron/package-lock.json`.
- Node MCP versions and resolutions: `node-mcp/package.json` and `node-mcp/package-lock.json`.
- Python compatible ranges: `python/requirements-core.txt` and `python/requirements.txt`.
- Tested platform resolutions: `python/requirements-*-lock-windows.txt` and `python/requirements-*-lock-linux.txt`.
- Downloadable model/resource checksums and declared licenses: `resources.lock.json`.

The Go launcher is the executable source for profile behavior: it selects
`requirements-core-lock-*` or `requirements-lock-*`, runs `npm ci` for Electron
and node-mcp, creates the Python venv, runs `pip check`, and invokes
`python/scripts/check_installed_lock.py`. The manifests describe allowed ranges;
the platform lock files describe the tested resolution.

## Installation profiles

| Profile | Intended use |
| --- | --- |
| `core` | The dependency set selected by `requirements-core-lock-*`; excludes the full optional audio/vector/model stack |
| `full` | The dependency set selected by `requirements-lock-*`; adds optional ASR, Genie-TTS, Qdrant, embeddings, and model helpers |
| development locks | Tests, lint, type checks, and build verification |

Optional native model backends are not installed by default because CUDA and
platform builds vary. Runtime feature gates are visible in
`python/modules/core/config.py`, `python/modules/system/runtime_services.py`,
and the provider modules under `python/modules/{asr,tts,ocr,llm}`. Do not add a
dependency when a local adapter or browser API already covers the behavior.

## Compatibility policy

Keep Python 3.11 compatibility and Node 22.13+ support. Prefer a compatible existing version over a major upgrade unless a security or runtime requirement justifies the change. Run `pip check`, the installed-lock validator, Electron `npm ci`, and the relevant test suites after dependency changes.

## License review

Package metadata is not a substitute for the upstream license. Review [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) and the exact lock files before shipping a binary.

## 中文说明

Electron、node-mcp 和 Python 的锁文件是可复现安装的权威输入。提交依赖升级时必须同时更新锁文件，并运行安装、审计、类型检查、测试和构建。ASR、TTS、嵌入、Qdrant、SoulX 及模型权重属于可选能力，可能有平台、GPU、模型卡或独立许可证限制；不要把用户下载的模型、声音、Live2D/VRM 文件或缓存放入源码归档。
