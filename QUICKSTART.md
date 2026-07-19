# Quick Start

适用环境: Windows、PowerShell 或 `cmd.exe`、Node.js 20+、Python 3.13 环境。Docker 只在启用 Qdrant 或 SoulX-SVC 时需要。

## 1. 安装

完整安装:

```bat
install_full.bat
```

轻量安装:

```bat
install_core.bat
```

安装脚本会创建 `python\.venv`，安装 Electron、后端和可选 MCP 所需依赖，并在缺少时从 `python\.env.example` 复制 `python\.env`。

## 2. 启动前检查

```bat
start.bat --check --no-qdrant
```

该命令只做本地路径、依赖、端口和脚本完整性检查，不启动应用。默认记忆后端是 `inmemory`，所以普通启动不需要 Qdrant。

## 3. 配置 LLM

启动应用后打开 `模型与语音 -> LLM`。

1. 选择提供商: DeepSeek、Qwen、Gemini、ChatGPT、Claude、Grok 或自定义。
2. 填写 Base URL、模型名和 API Key。
3. Base URL 写基础路径即可，例如 `https://api.openai.com/v1`。如果误贴 `/models` 或 `/chat/completions`，前后端会归一化回基础路径。
4. 点击模型检测或 LLM 测试。

当前调用约定是 OpenAI-compatible:

- 模型列表: `{base}/models`
- 聊天补全: `{base}/chat/completions`

Claude 预设也按这个兼容链路处理，因此需要使用支持 OpenAI-compatible 路径的端点或网关。

## 4. 配置 TTS

默认 TTS 语言为 `ja`。常用设置在 `模型与语音 -> TTS`:

- `genie_character`
- `genie_model_dir`
- `ref_audio`
- `ref_text`
- `lang`
- `device`
- `quality`
- `split`
- `mode`
- `save_mode`

用户当前常用参考音频可写入:

```text
E:/GPT-SoVITS-1007-cu124/GPT-SoVITS-1007-cu124/custom_refs/【_unk_】もうこんなひどいことさせないからね.wav
```

参考文本:

```text
もうこんなひどいことさせないからね
```

如果需要预热 Genie 资源，可在 `模型与语音 -> 资源` 中运行预取。

## 5. 配置 ASR

默认 ASR:

```env
ASR_PROVIDER=sensevoice-service
ASR_BASE_URL=http://127.0.0.1:8899/v1
SENSEVOICE_MODEL=iic/SenseVoiceSmall
WHISPER_LANG=zh
```

该模式要求外部服务提供:

- `GET /v1/models`
- `POST /v1/audio/transcriptions`

本地 ONNX ASR:

```env
ASR_PROVIDER=sherpa-onnx
SHERPA_ONNX_MODEL_PATH=./.cache/sherpa-onnx/sensevoice/model.int8.onnx
SHERPA_ONNX_TOKENS_PATH=./.cache/sherpa-onnx/sensevoice/tokens.txt
SHERPA_ONNX_NUM_THREADS=2
SHERPA_ONNX_PROVIDER=cpu
```

可在资源面板下载 Sherpa SenseVoice 文件。

## 6. 配置记忆

默认:

```env
MEMORY_BACKEND=inmemory
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B
```

启用 Qdrant:

```env
MEMORY_BACKEND=qdrant
QDRANT_URL=http://127.0.0.1:6333
QDRANT_COLLECTION=memories
QDRANT_AUTO_START=1
```

启用 Qdrant 后，`start.bat` 可自动拉起本地 Docker Qdrant。切换 embedding 模型或维度后，需要重建 collection 并重新写入向量。

## 7. 导入 Live2D/VRM

打开 `人物与桌宠`:

- 选择 Live2D 文件夹时需要包含 `.model3.json`。
- 选择 VRM 时需要 `.vrm` 文件。
- 导入后资源会复制到 Electron 用户数据目录，由控制服务统一管理。

LLM 输出的 `pet_control` 会通过白名单映射到当前模型可用的 expression、motion group 和 motion index，避免模型不存在的动作被直接执行。

## 8. 启动

```bat
start.bat
```

常用参数:

```bat
start.bat --no-qdrant
start.bat --with-mcp
start.bat --dev-renderer
start.bat --smoke
```

如果要启动 SoulX-SVC:

```bat
start_soulx_svc.bat --check
start_soulx_svc.bat path\to\reference.wav
```

## 9. 验证

后端 ASR 相关测试:

```bat
cd python
.venv\Scripts\python.exe -m pytest tests\test_asr_pipeline.py tests\test_voice_service_clients.py -q
```

前端:

```bat
cd electron
npm run lint
npm run type-check
npm test
```

启动脚本:

```bat
start.bat --check --no-qdrant
```

## 常见问题

- LLM 模型列表为空: 先确认 Base URL 是基础路径，远程提供商通常需要 API Key。
- ASR 没反应: 检查 `ASR_PROVIDER`，外部服务是否提供 `/v1/audio/transcriptions`，以及前端麦克风权限。
- TTS 无声: 检查 Genie 模型目录、参考音频、参考文本和音频缓存目录。
- Live2D 不动: 确认当前模型确实有对应 expression 或 motion group，查看 `pet:control` 事件是否发出。
- Qdrant 启动失败: 先保持 `MEMORY_BACKEND=inmemory` 或使用 `start.bat --no-qdrant`，待 Docker 可用后再切换。
