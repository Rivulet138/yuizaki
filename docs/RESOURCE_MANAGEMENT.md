# Resource management / 资源管理

## Persistent data / 持久化数据

聊天和记忆数据库位于 `python/data/`，设置位于 `python/config/`。请通过控制面板 API 备份，或在服务停止时备份。

Chat and memory databases live under `python/data/`. Settings live under `python/config/`. Back up through the control-panel API or while services are stopped.

## Caches and models / 缓存与模型

TTS 文件位于 `python/audio_cache/`。Embedding、ASR、TTS 和服务商缓存由资源面板或服务商专用路径管理。除非许可证明确允许纳入，否则模型权重和虚拟形象资源必须保留在 Git 之外。

TTS files live under `python/audio_cache/`. Embedding, ASR, TTS, and provider caches are managed by the resource panel or provider-specific paths. Model weights and avatar assets must remain outside Git unless their licenses explicitly allow inclusion.

## Vision and audio / 视觉与音频

视觉帧仅在一次 Agent 请求期间保存在内存中，分析后释放。实时音频使用当前会话；中断时清空排队的 TTS。不要将麦克风缓冲区或屏幕截图写入长期日志。

Vision frames are held in memory for one Agent request and released after analysis. Realtime audio uses the active session; queued TTS is cleared on interruption. Do not write microphone buffers or screenshots to long-lived logs.

## Hardware profiles / 硬件配置

使用性能设置限制 DPR/FPS，并暂停隐藏窗口。在集成 GPU 或低内存设备上，建议延迟启动、CPU 推理、较低 TTS 质量和 SQLite 内存模式。Qdrant 为可选组件，除非需要语义检索，否则不应自动启动。

Use the performance settings to cap DPR/FPS and pause hidden windows. On integrated GPUs or low-memory machines, prefer lazy startup, CPU inference, lower TTS quality, and SQLite memory mode. Qdrant is optional and should not be auto-started unless semantic retrieval is needed.

## Cleanup boundary / 清理边界

绝不要提交 `.venv`、模型权重、`audio_cache`、`python/data`、日志或 pytest 临时目录。相较于手动删除活动文件，优先使用启动器和资源 API。永久删除前请先审阅清理预览。

Never commit `.venv`, model weights, `audio_cache`, `python/data`, logs, or pytest temporary directories. Prefer the launcher and resource APIs over deleting active files manually. Review cleanup previews before permanent deletion.
