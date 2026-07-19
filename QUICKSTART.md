# 快速开始

## 1. 选择安装范围

核心安装只准备桌面端、Python 后端和必要依赖，模型在首次使用或手动勾选时下载：

```powershell
.\install_core.bat
```

```bash
./install_core.sh
```

需要额外本地模型与完整能力时使用：

```powershell
.\install_full.bat
```

```bash
./install_full.sh
```

建议先使用核心安装，确认基础对话、桌宠窗口和云端模型可用后，再准备本地 ASR、TTS、嵌入或 SoulX。

## 2. 配置后端

首次安装会从 `python/.env.example` 创建 `python/.env`。至少配置一个 OpenAI 兼容的文本模型：

```dotenv
LLM_PROVIDER=custom
LLM_BASE_URL=https://example.com/v1
LLM_API_KEY=replace-me
LLM_MODEL=your-model
```

视觉模型单独配置，避免普通对话每轮携带屏幕图像：

```dotenv
VISION_LLM_ENABLED=1
VISION_LLM_PROVIDER=custom
VISION_LLM_BASE_URL=https://example.com/v1
VISION_LLM_API_KEY=replace-me
VISION_LLM_MODEL=your-vision-model
```

默认长期记忆已启用：

```dotenv
MEMORY_BACKEND=sqlite
MEMORY_SQLITE_PATH=./data/memory.db
```

不要把真实密钥提交到 Git。运行时设置页会写入 `python/config/settings.json`，其中敏感字段通过后端受控接口管理。

## 3. 启动

Windows：

```powershell
.\start.bat
```

Linux：

```bash
./start.sh
```

脚本会启动 Python 服务、Electron 控制服务和桌宠窗口。开发模式可以分别启动：

```powershell
.\scripts\run_backend_dev.bat
.\scripts\run_electron_dev.bat
```

```bash
./scripts/run_backend_dev.sh
cd electron && npm run dev
```

## 4. 配置语音

默认 ASR 配置：

```dotenv
ASR_PROVIDER=sensevoice-service
ASR_LANGUAGE=zh
VAD_MIN_SILENCE_MS=300
```

桌宠支持按住说话。默认可以使用鼠标侧键，设置页中可重新绑定麦克风和其他桌宠快捷键。释放按键后进入 ASR 最终结果、LLM、TTS 播放链路；再次按下可触发打断。

Genie TTS 示例：

```dotenv
TTS_PROVIDER=genie-tts
TTS_REF_AUDIO=/path/to/reference.wav
TTS_REF_TEXT=参考音频的准确文本
TTS_LANG=zh
TTS_DEVICE=cpu
```

参考音频路径必须指向本机真实文件，不要把个人绝对路径写回模板或文档。

## 5. 准备模型资源

设置页的资源区可以查看并准备：

- `sherpa`：离线 ASR
- `sherpa_online`：流式 ASR
- `embedding`：语义记忆嵌入模型
- `tts`：Genie TTS 资源
- `soulx`：变声服务资源

资源操作会合并重复请求，但下载体积可能很大。下载目录、清理范围和当前限制见 [RESOURCE_MANAGEMENT.md](RESOURCE_MANAGEMENT.md)。

## 6. 可选 Qdrant

SQLite 是权威长期记忆默认值。需要向量检索时启用 Qdrant：

```dotenv
MEMORY_BACKEND=qdrant
QDRANT_URL=http://127.0.0.1:6333
QDRANT_AUTO_START=1
QDRANT_DOCKER_IMAGE=qdrant/qdrant:v1.18.3
```

Windows 可预先运行：

```powershell
.\scripts\ensure_qdrant_docker.ps1
```

Qdrant 不可用时应切回 `sqlite`，不要切到非持久的内存后端。

## 7. 常见问题

- Electron 无法启动：运行 `cd electron && npm ci && npm run start:check`。
- Python 导入失败：确认使用项目 `.venv`，然后执行 `python -m pip check`。
- Linux 窗口为空：运行 `scripts/check_linux_environment.sh`，确认 X11/Wayland 兼容库完整。
- 模型下载失败：检查磁盘、代理和 Hugging Face 访问；不要反复删除部分下载目录。
- 长期记忆为空：确认 `MEMORY_BACKEND=sqlite` 且 `python/data/memory.db` 可写。
- 屏幕理解无结果：确认视觉模型已配置；OCR 只负责显式精确读字，不代替实时视觉。
