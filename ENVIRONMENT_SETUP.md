# Environment Setup

本文记录当前 Yuizaki 本地运行环境、主要变量和资源边界。敏感配置位于 `python\config\settings.json` 和 `python\.env`，不要把 API Key 写入文档或提交到仓库。

## 运行时

| 项 | 当前要求 |
| --- | --- |
| OS | Windows 10/11；主流 x86_64 Linux 桌面发行版 |
| Node.js | 22.13+ |
| Python | 3.12+；本地模型原生包按平台和 Python 版本支持情况选择 |
| Docker | 可选，仅 Qdrant 和 SoulX-SVC 需要 |
| Electron | 42.x |
| Vue/Vite | Vue 3.5, Vite 8 |

## 安装命令

```bat
install_full.bat
```

Linux:

```bash
./install_full.sh
./start.sh --check
```

Linux 系统依赖、Wayland 和 PipeWire 说明见 [LINUX.md](LINUX.md)。

手动安装等价流程:

```bat
cd electron
npm install

cd ..\node-mcp
npm install

cd ..\python
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

## 核心端口

| 服务 | 默认地址 |
| --- | --- |
| Python FastAPI | `http://127.0.0.1:8001` |
| Electron 控制服务 | `http://127.0.0.1:38945` |
| Vite 开发渲染端 | `http://localhost:5173` |
| Playwright MCP | `http://127.0.0.1:7777` |
| ASR 服务 | `http://127.0.0.1:8899/v1` |
| SoulX-SVC | `http://127.0.0.1:7861` |
| Qdrant | `http://127.0.0.1:6333` |

## 环境变量

后端从 `python\.env` 读取环境变量。设置面板写入 `python\config\settings.json`，并在运行时 patch 对应服务。

### LLM

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `LLM_PROVIDER` | `custom` | `deepseek`, `qwen`, `gemini`, `chatgpt`, `claude`, `grok`, `custom` |
| `LLM_BASE_URL` | 空 | OpenAI-compatible 基础 URL |
| `LLM_API_KEY` | 空 | API Key |
| `LLM_MODEL` | `gpt-3.5-turbo` | 模型名 |
| `LLM_TIMEOUT` | `60` | 请求超时 |
| `LLM_CONTEXT_MAX_TOKENS` | `1145140` | 上下文预算 |
| `LLM_DEFAULT_MAX_OUTPUT_TOKENS` | `65535` | 默认输出长度 |
| `LLM_TEMPERATURE` | `1.2` | 采样温度 |
| `LLM_TOP_P` | `0.9` | nucleus sampling |
| `LLM_TOP_K` | `500` | top-k sampling |
| `LLM_MIN_P` | `0` | min-p sampling |
| `LLM_FREQUENCY_PENALTY` | `0.2` | 频率惩罚 |
| `LLM_PRESENCE_PENALTY` | `0` | 存在惩罚 |
| `LLM_REPETITION_PENALTY` | `1` | 重复惩罚 |

Base URL 会自动去掉误贴的 `/models`、`/chat/completions` 或 `/messages` 后缀。实际调用统一为 `{base}/models` 和 `{base}/chat/completions`。

### TTS

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `TTS_GENIE_CHARACTER` | `feibi` | Genie 角色 |
| `TTS_GENIE_MODEL_DIR` | 空 | 可选模型目录 |
| `TTS_BASE_URL` | `http://127.0.0.1:9880` | 兼容旧服务字段 |
| `TTS_REF_AUDIO` | 空 | 参考音频 |
| `TTS_REF_TEXT` | 空 | 参考文本 |
| `TTS_LANG` | `ja` | 默认 TTS 语言 |
| `TTS_DEVICE` | `cpu` | `cpu` 或 `cuda` |
| `TTS_QUALITY` | 运行时默认 | Genie 推理质量 |
| `TTS_SPLIT` | 运行时默认 | 分句策略 |
| `TTS_MODE` | 运行时默认 | 推理模式 |
| `TTS_SAVE_MODE` | 运行时默认 | 保存模式 |
| `AUDIO_CACHE_DIR` | `./audio_cache` | 音频缓存目录 |

### ASR

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `ASR_PROVIDER` | `sensevoice-service` | `sensevoice-service`, `funasr-service`, `openai-compatible`, `sherpa-onnx`, `sherpa-onnx-online`, `sensevoice-local`, `disabled`；旧值 `sherpa-online` 会自动迁移 |
| `ASR_BASE_URL` | `http://127.0.0.1:8899/v1` | 外部 ASR 服务基础 URL |
| `ASR_API_KEY` | 空 | 可选 Bearer Token |
| `ASR_TIMEOUT` | `60` | 请求超时 |
| `SENSEVOICE_MODEL` | `iic/SenseVoiceSmall` | 模型名 |
| `SENSEVOICE_DEVICE` | `cpu` | 本地 FunASR 设备 |
| `SHERPA_ONNX_MODEL_PATH` | 空 | 可选自定义 ONNX 模型；留空时按 provider 使用独立托管目录 |
| `SHERPA_ONNX_TOKENS_PATH` | 空 | 可选自定义 tokens；留空时按 provider 使用独立托管目录 |
| `SHERPA_ONNX_NUM_THREADS` | `2` | sherpa 线程 |
| `SHERPA_ONNX_PROVIDER` | `cpu` | sherpa provider |
| `WHISPER_LANG` | `zh` | 通用 ASR 语言提示；变量名为历史兼容名称 |
| `VAD_THRESHOLD` | `0.5` | VAD 阈值 |
| `VAD_MIN_SILENCE_MS` | `500` | 端点静音上限，运行时归一化到 `160–1200ms` 并按语句长度与停顿习惯动态调整 |
| `ASR_PARTIAL_EVERY` | `15` | 离线 ASR 的 partial 基础音频块间隔，范围 `1–30` |

`sherpa-onnx-online` 需要兼容的在线 Zipformer2 CTC 模型和 tokens。设置的资源页可安装并加载校验官方 `sherpa-onnx-streaming-zipformer-small-ctc-zh-int8-2025-04-01`；默认目录为 `python/.cache/sherpa-onnx/streaming-zipformer-small-ctc-zh/`。SenseVoice ONNX 属于离线模型，不能直接当作在线模型使用。

`WHISPER_MODEL`、`WHISPER_DEVICE` 和 `WHISPER_COMPUTE` 目前仅用于读取旧配置；当前 provider 列表没有 Whisper 实现，普通设置页不会展示这些无效控件。

### SVC

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `SVC_PROVIDER` | `soulx-service` | `soulx-service` 或 `disabled` |
| `SVC_BASE_URL` | `http://127.0.0.1:7861` | SoulX Docker 服务 |
| `SVC_SPEAKER_ID` | `0` | 参考音频 id |
| `SVC_PITCH` | `0` | pitch shift |
| `SVC_TIMEOUT` | `120` | 请求超时 |

### Memory

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `MEMORY_BACKEND` | `sqlite` | 默认 SQLite 权威存储；`inmemory` 仅用于临时运行，`qdrant` 为可选增强 |
| `MEMORY_SQLITE_PATH` | `python/data/memory/memories.db` | SQLite 长期记忆数据库路径 |
| `QDRANT_URL` | `http://127.0.0.1:6333` | Qdrant 地址 |
| `QDRANT_API_KEY` | 空 | 可选 token |
| `QDRANT_COLLECTION` | `memories` | collection |
| `QDRANT_AUTO_START` | `1` | 仅在 backend 为 qdrant 且 URL 为本地 HTTP 时生效 |
| `QDRANT_DOCKER_IMAGE` | `qdrant/qdrant:latest` | Docker 镜像 |
| `QDRANT_DOCKER_CONTAINER` | `yuizaki-qdrant` | 容器名 |
| `QDRANT_DOCKER_VOLUME` | `yuizaki-qdrant-storage` | volume |
| `EMBEDDING_MODEL` | `Qwen/Qwen3-Embedding-0.6B` | SentenceTransformer 模型 |
| `EMBEDDING_MODEL_LOCAL_PATH` | 空 | 可选本地模型路径 |

### 安全与启动

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `YUIZAKI_ALLOWED_ORIGINS` | 本地控制和 Vite 地址 | CORS 白名单 |
| `YUIZAKI_BACKEND_API_TOKEN` | 启动时生成 | 保护 Python `/api`, `/memory`, `/v1`, `/vision`, `/svc`, `/system` 等路由 |
| `YUIZAKI_ALLOW_UNAUTHENTICATED_LOCAL_DEV` | `0` | 仅隔离本地调试可设为 `1` |
| `SUMMARY_ADMIN_TOKEN` | 空 | 设置/summary 管理 token |
| `SERVER_HOST` | `127.0.0.1` | FastAPI host |
| `SERVER_PORT` | `8001` | FastAPI port |
| `CONTROL_SERVER_PORT` | `38945` | Electron 控制服务 port |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `YUIZAKI_PYTHON_LOG_FILE` | `logs/dev/python.log` | Python 日志文件路径 |
| `YUIZAKI_LOG_MAX_BYTES` | `5242880` | 单个 Python 日志文件上限，默认 5 MiB |
| `YUIZAKI_LOG_BACKUP_COUNT` | `3` | 保留的滚动日志文件数量 |

## 资源目录

不要在普通清理中删除:

- `python\.cache\GenieData\`
- `python\.cache\sherpa-onnx\`
- `python\.cache\huggingface\`
- `python\CharacterModels\`
- `python\audio_cache\`
- `electron\src\renderer\public\live2d\`
- `electron\dist\renderer\live2d\`
- `services\soulx-svc\models\`
- `services\soulx-svc\references\`
- `data\` 和 `python\data\`

可以清理:

- `.pytest_cache\`
- `python\.pytest_cache\`
- `__pycache__\`
- `.playwright-mcp\` 中的运行日志
- `electron\.codex-settings-vite.log`
- `tmp\` 中的临时研究克隆、生成图片和一次性参考
- `logs\dev\` 中的旧启动日志

## 健康检查

```bat
curl http://127.0.0.1:8001/health
curl http://127.0.0.1:38945/api/health
curl http://127.0.0.1:7777/health
```

启动脚本检查:

```bat
start.bat --check --no-qdrant
```
