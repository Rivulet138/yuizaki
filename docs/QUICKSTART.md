# 快速开始

## 要求

- Node.js 22.13 以上
- Python 3.11、3.12 或 3.13（新环境优先 3.12/3.13；项目运行时使用 `python/.venv`）
- Windows 10/11 或 x86_64 Linux
- 至少 8 GiB 内存

## 安装

Windows：

```powershell
.\install.bat core
```

Linux：

```bash
./install.sh core
```

完整本地模型环境：

```powershell
.\install.bat full
```

```bash
./install.sh full
```

建议先使用核心安装，模型在首次使用或设置页手动选择时下载。

后端默认在后台加载并预热 Genie TTS，使首次回复可以直接发声。若机器资源紧张，可在 `python/.env` 中设置 `TTS_STARTUP_MODE=lazy` 和 `TTS_WARMUP_ENABLED=0`，将模型加载推迟到首次语音请求。

## 配置文本模型

编辑 `python/.env`：

```dotenv
LLM_PROVIDER=custom
LLM_BASE_URL=https://example.com/v1
LLM_API_KEY=replace-me
LLM_MODEL=your-model
```

本地 OpenAI 兼容服务同样使用这组字段。

## 配置视觉模型

```dotenv
VISION_LLM_ENABLED=1
VISION_LLM_PROVIDER=custom
VISION_LLM_BASE_URL=https://example.com/v1
VISION_LLM_API_KEY=replace-me
VISION_LLM_MODEL=your-vision-model
VISION_LLM_DETAIL=low
```

视觉默认关闭。启用后只在发送 Agent 回合时采集当前单帧并提交独立 VLM；VLM 不可用、失败或返回空结果时才回退到本地 OCR。后台不会持续截图。`VISION_LLM_DETAIL=low` 是低延迟默认值，需要空间细节时再改为 `high` 或 `original`。

## 启动

Windows：

```powershell
.\start.bat
```

普通启动使用已构建 UI、SQLite 记忆并启动 MCP，保证工具能力完整；Qdrant 仍按语义记忆需求启用。开发调试可添加 `--dev-renderer`，启用本地 Qdrant 使用 `--with-qdrant`，明确不需要 MCP 时使用 `--no-mcp`。

也可以构建并使用 Windows 监督启动器：

```powershell
.\scripts\build_yuizaki_launcher.bat
.\YuizakiLauncher.exe
```

启动器使用 `/api/ping` 判断后端进程是否可用；ASR、TTS 等可选服务处于降级状态时不会阻塞桌面端启动。

Linux：

```bash
./start.sh
```

## 语音

默认支持鼠标侧键按住说话，可在设置中修改鼠标和键盘绑定。

本地流式 ASR 默认使用 Sherpa ONNX Streaming Zipformer，不会首次启动下载 SenseVoice。Sherpa 本地 recognizer 默认按首次语音请求懒加载；需要启动阶段预热时可设置 `ASR_STARTUP_MODE=background`，必须同步加载时使用 `blocking`。SenseVoice/FunASR 仍可在设置中显式选择；选择后才准备对应资源。Genie TTS 需要模型或参考音频：

```dotenv
TTS_PROVIDER=genie-tts
TTS_REF_AUDIO=/path/to/reference.wav
TTS_REF_TEXT=参考音频文本
TTS_LANG=zh
```

## 记忆

默认配置：

```dotenv
MEMORY_BACKEND=sqlite
MEMORY_SQLITE_PATH=./data/memory.db
```

记忆 reranker 默认关闭，不会自动下载 CrossEncoder。需要更高精度时显式开启：

```dotenv
MEMORY_RERANKER_ENABLED=1
MEMORY_RERANKER_MODEL=BAAI/bge-reranker-v2-m3
MEMORY_RERANKER_CANDIDATES=32
```

需要 Qdrant 时见 [ENVIRONMENT_SETUP.md](ENVIRONMENT_SETUP.md)。

## 常见问题

- 桌面端无法启动：`cd electron && npm ci && npm run start:check`
- Python 依赖异常：`python -m pip check`
- Linux 窗口异常：运行 `scripts/check_linux_environment.sh`
- 模型下载失败：检查磁盘、代理和模型源访问
- 长期记忆为空：检查 `MEMORY_BACKEND` 和数据库写入权限

## 验证安装

Windows：

```powershell
.\start.bat --check
cd python
.\.venv\Scripts\python.exe scripts/check_installed_lock.py --lock requirements-lock-windows.txt
.\.venv\Scripts\python.exe -m evals
```

Linux：

```bash
./start.sh --check
cd python
./.venv/bin/python scripts/check_installed_lock.py --lock requirements-lock-linux.txt
./.venv/bin/python -m evals
```

离线评测不会调用云端服务或下载模型。fixture、来源元数据、质量门槛和报告格式见 [MODEL_EVALUATION.md](MODEL_EVALUATION.md)。
