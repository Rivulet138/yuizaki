# 环境与配置

依赖安装由平台 lock 文件控制；模型质量评测使用 `python -m evals`，默认不需要云端凭据或模型下载。

配置优先级从高到低：运行时设置 `python/config/settings.json`、进程环境变量、`python/.env`、代码默认值。安装脚本只在缺少 `.env` 时复制 `.env.example`。

## LLM

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `LLM_PROVIDER` | `custom` | 文本模型提供方标识 |
| `LLM_BASE_URL` | 空 | OpenAI 兼容 API 根地址 |
| `LLM_API_KEY` | 空 | API 密钥 |
| `LLM_MODEL` | 空 | 文本模型名 |
| `LLM_TIMEOUT` | `60` | 请求超时秒数 |
| `LLM_CONTEXT_MAX_TOKENS` | `131072` | 上下文总预算 |
| `LLM_DEFAULT_MAX_OUTPUT_TOKENS` | `8192` | 默认最大输出 |
| `LLM_TEMPERATURE` | `1.2` | 温度 |
| `LLM_TOP_P` | `0.9` | nucleus sampling |
| `LLM_TOP_K` | `500` | top-k |
| `LLM_MIN_P` | `0` | min-p |
| `LLM_FREQUENCY_PENALTY` | `0.2` | 频率惩罚 |
| `LLM_PRESENCE_PENALTY` | `0` | 存在惩罚 |
| `LLM_REPETITION_PENALTY` | `1` | 重复惩罚 |

前端与后端共享默认上下文 `131072`、默认输出 `8192`。当模型能力注册表包含明确的上下文/输出上限时，后端会在发送请求前自动裁剪超出值；未知模型不使用猜测性的硬编码上限。

## 视觉模型

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `VISION_LLM_ENABLED` | `0` | 启用独立视觉模型 |
| `VISION_LLM_PROVIDER` | `custom` | 视觉提供方 |
| `VISION_LLM_BASE_URL` | 空 | 视觉 API 根地址 |
| `VISION_LLM_API_KEY` | 空 | 视觉 API 密钥 |
| `VISION_LLM_MODEL` | 空 | 视觉模型名 |
| `VISION_LLM_TIMEOUT` | `30` | 视觉请求超时秒数 |

视觉默认关闭。启用后只在发送 Agent 回合时采集当前单帧并保存在内存中；后台不会持续截图。OCR 使用独立 `/vision/ocr` 路由，只在该视觉回合需要读取文本时调用。

## TTS

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `TTS_PROVIDER` | `genie-tts` | TTS 提供方 |
| `TTS_GENIE_CHARACTER` | 空 | Genie 角色 |
| `TTS_GENIE_MODEL_DIR` | 空 | Genie 模型目录 |
| `TTS_REF_AUDIO` | 空 | 参考音频路径 |
| `TTS_REF_TEXT` | 空 | 参考音频文本 |
| `TTS_LANG` | `ja` | 合成语言 |
| `TTS_DEVICE` | `cpu` | 推理设备 |
| `AUDIO_CACHE_DIR` | `./audio_cache` | 生成音频缓存 |

质量、切分、推理和保存模式可以通过 `TTS_QUALITY`、`TTS_SPLIT`、`TTS_MODE`、`TTS_SAVE_MODE` 配置。

## ASR 与 VAD

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `ASR_PROVIDER` | `sherpa-onnx-online` | ASR 提供方 |
| `ASR_BASE_URL` | 空 | SenseVoice/FunASR 服务地址；仅服务模式需要 |
| `ASR_API_KEY` | 空 | 服务密钥 |
| `ASR_TIMEOUT` | `60` | 超时秒数 |
| `ASR_LANGUAGE` | `zh` | 语言提示 |
| `VAD_THRESHOLD` | `0.5` | VAD 阈值 |
| `VAD_MIN_SILENCE_MS` | `300` | 端点静音时间 |
| `ASR_PARTIAL_EVERY` | `15` | partial 节奏参数 |

Sherpa Streaming Zipformer 是默认本地 ASR；SenseVoice/FunASR 服务需要显式选择对应 provider 并配置 `ASR_BASE_URL`。Sherpa 使用 `SHERPA_ONNX_MODEL_PATH`、`SHERPA_ONNX_TOKENS_PATH`、`SHERPA_ONNX_NUM_THREADS` 和 `SHERPA_ONNX_PROVIDER`。已删除无效旧字段，不再做名称兼容。

## 记忆与 Qdrant

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `MEMORY_BACKEND` | `sqlite` | `sqlite` 或 `qdrant` |
| `MEMORY_SQLITE_PATH` | `./data/memory.db` | 权威长期记忆库 |
| `QDRANT_URL` | `http://127.0.0.1:6333` | Qdrant 地址 |
| `QDRANT_API_KEY` | 空 | Qdrant 密钥 |
| `QDRANT_COLLECTION` | `memories` | collection |
| `QDRANT_TIMEOUT` | `10` | 超时秒数 |
| `QDRANT_AUTO_START` | `1` | 尝试启动本地容器 |
| `QDRANT_DOCKER_IMAGE` | `qdrant/qdrant:v1.18.3` | 固定容器版本 |
| `EMBEDDING_MODEL` | `Qwen/Qwen3-Embedding-0.6B` | 默认嵌入模型 |
| `EMBEDDING_MODEL_LOCAL_PATH` | 空 | 本地模型目录 |

## 缓存、摘要与服务

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `CACHE_MAX_AGE` | `1800` | 受管临时音频保留秒数 |
| `CACHE_JANITOR_INTERVAL` | `600` | 清理周期秒数 |
| `DATABASE_URL` | `sqlite:///./data/chat.db` | 对话数据库 |
| `SERVER_HOST` | `127.0.0.1` | Python 监听地址 |
| `SERVER_PORT` | `8001` | Python 端口 |
| `CONTROL_SERVER_PORT` | `38945` | Electron 控制服务端口 |
| `LOG_LEVEL` | `INFO` | 日志等级 |

摘要治理变量以 `SUMMARY_` 开头。服务对外暴露时必须设置 `YUIZAKI_BACKEND_API_TOKEN` 并限制 `YUIZAKI_ALLOWED_ORIGINS`；仅隔离的本地开发可使用 `YUIZAKI_ALLOW_UNAUTHENTICATED_LOCAL_DEV=1`。

## 配置检查

```powershell
cd python
.\.venv\Scripts\python.exe -c "from modules.core.config import public_config_snapshot, config; print(public_config_snapshot(config))"
```

输出会隐藏密钥。完整模板见 [python/.env.example](../python/.env.example)，资源目录见 [RESOURCE_MANAGEMENT.md](RESOURCE_MANAGEMENT.md)。
