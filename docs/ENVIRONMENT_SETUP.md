# Environment setup / 环境配置

## Supported runtime / 支持的运行时

- Python 3.11-3.13, preferably in `python/.venv`.
- Python 3.11-3.13，建议安装在 `python/.venv` 中。
- Node.js 22.13+ and npm.
- Node.js 22.13+ 和 npm。
- Windows 10/11 or x86_64 Linux with a desktop session.
- Windows 10/11，或带桌面会话的 x86_64 Linux。
- Docker only for optional Qdrant or SoulX workflows.
- Docker 仅用于可选的 Qdrant 或 SoulX 流程。

## Install profiles / 安装配置

`core` installs the server, SQLite, OCR foundation, and required runtime. `full` adds optional ASR, Genie-TTS, Qdrant, embedding, and model helpers. Platform lock files record tested resolutions; native model packages can still vary by CPU, GPU, and operating system.

`core` 安装服务端、SQLite、OCR 基础组件和必需运行时。`full` 额外安装可选 ASR、Genie-TTS、Qdrant、嵌入和模型辅助组件。平台锁文件记录已测试的依赖解析结果；原生模型软件包仍可能因 CPU、GPU 和操作系统而不同。

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

## Local environment file / 本地环境文件

```powershell
Copy-Item python/.env.example python/.env
```

Configure an LLM first. Then configure TTS, ASR, memory, Qdrant, and vision only as needed. Keep `VISION_LLM_ENABLED=0` unless a visual Agent workflow is deliberate. On constrained hardware use `TTS_STARTUP_MODE=lazy`, `TTS_WARMUP_ENABLED=0`, and `ASR_STARTUP_MODE=lazy`.

请先配置 LLM，再按需配置 TTS、ASR、记忆、Qdrant 和视觉。除非明确需要视觉 Agent 流程，否则保持 `VISION_LLM_ENABLED=0`。在硬件受限时，使用 `TTS_STARTUP_MODE=lazy`、`TTS_WARMUP_ENABLED=0` 和 `ASR_STARTUP_MODE=lazy`。

## Provider boundaries / 服务商边界

- `LLM_PROVIDER=custom` targets OpenAI-compatible chat endpoints.
- `LLM_PROVIDER=custom` 连接 OpenAI 兼容聊天端点。
- `TTS_PROVIDER=genie-tts` uses the optional local Genie runtime.
- `TTS_PROVIDER=genie-tts` 使用可选的本地 Genie 运行时。
- `TTS_PROVIDER=openai-compatible` targets `/v1/audio/speech`.
- `TTS_PROVIDER=openai-compatible` 连接 `/v1/audio/speech`。
- `ASR_PROVIDER=sherpa-onnx-online` uses a local model when installed and configured.
- `ASR_PROVIDER=sherpa-onnx-online` 在完成安装和配置后使用本地模型。
- SoulX-SVC is an external HTTP service and is not part of the core install.
- SoulX-SVC 是外部 HTTP 服务，不属于核心安装内容。

## Frontend variables / 前端变量

The launcher exports `VITE_YUIZAKI_API_ORIGIN`, `VITE_YUIZAKI_CONTROL_ORIGIN`, `SERVER_PORT`, `CONTROL_SERVER_PORT`, `RENDERER_PORT`, and `MCP_PORT`. Keep port selection in the launcher rather than hard-coding fallback ports in application code.

启动器导出 `VITE_YUIZAKI_API_ORIGIN`、`VITE_YUIZAKI_CONTROL_ORIGIN`、`SERVER_PORT`、`CONTROL_SERVER_PORT`、`RENDERER_PORT` 和 `MCP_PORT`。请在启动器中选择端口，不要在应用代码中硬编码备用端口。

## Assets and caches / 资源与缓存

Store Live2D/VRM assets and model caches outside Git. Startup restores the saved model reference when the asset exists; missing assets are reported in the pet/resource panel. Read [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) before redistributing any asset or weight.

请将 Live2D/VRM 资源和模型缓存存放在 Git 之外。资源存在时，启动过程会恢复已保存的模型引用；缺失资源会在桌宠/资源面板中报告。重新分发任何资源或权重前，请阅读 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)。
