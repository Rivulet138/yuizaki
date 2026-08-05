# 资源管理

运行时 Python 依赖版本由平台 lock 文件固定；模型质量指标和 smoke fixture 见 [MODEL_EVALUATION.md](MODEL_EVALUATION.md)。

## 数据位置

| 资源 | 默认位置 | 保留方式 |
| --- | --- | --- |
| 对话 | `python/data/chat.db` | 持久 |
| 长期记忆 | `python/data/memory.db` | 持久 |
| 设置 | `python/config/settings.json` | 持久 |
| TTS 音频 | `python/audio_cache/` | 临时 |
| 按需视觉帧 | 内存 | 单次 Agent 回合、会话级替换 |
| Electron 依赖 | `electron/node_modules/` | 可重建 |
| Python 环境 | `python/.venv/` | 可重建 |
| 模型缓存 | 受管模型目录 | 可重新下载 |

## 模型下载

模型默认不随核心安装包分发。首次启用能力或在资源页勾选后下载。

| 资源 | 固定版本 | 下载量 | 授权 | 校验 |
| --- | --- | ---: | --- | --- |
| Sherpa SenseVoice | `2025-09-09-int8` | 158 MiB | FunASR Model License | SHA-256；仅显式选择 SenseVoice 时准备 |
| Sherpa Streaming Zipformer | `2025-04-01-int8` | 20 MiB | Apache-2.0 | SHA-256 + 加载验证；默认 ASR |
| Qwen3 Embedding 0.6B | `97b0c614be4d` | 1.12 GiB | Apache-2.0 | Hugging Face commit |
| Genie TTS | `2.0.2` / `52b17272e0b7` | 约 391 MiB | MIT | Python 包版本 + Hugging Face commit |
| SoulX Singer SVC | `2026-02` | 约 9.04 GiB | Apache-2.0 | Hugging Face/Git commit |

CrossEncoder reranker（默认关闭）不属于首次资源准备；启用后由 Sentence Transformers 按需加载 `MEMORY_RERANKER_MODEL`，先使用 embedding 召回候选再重排。

权威元数据位于 `resources.lock.json`。自定义嵌入模型不继承默认模型的授权和 revision 状态。

## 永久清理

可清理项目：

- TTS 临时音频
- 运行时临时文件
- 不再使用的模型资源
- 导入的 Live2D/VRM 模型
- 对话、记忆和工作区数据

数据库压缩不等于删除记忆。删除记忆必须使用明确的永久删除操作。

模型卸载直接删除受管资源，不进入回收站或软删除区。正在下载的模型必须先取消；参考音频、导入角色和仓库外自定义模型不随模型卸载删除。

Sherpa 下载显示实际字节与百分比，并在受管模型目录的 `.download` 中保留可续传 `.part` 文件和 JSON 日志。再次下载时使用 HTTP Range；服务器忽略 Range 时重新覆盖，SHA-256 失败时永久删除损坏断点，安装完成后删除下载文件。模型永久卸载会一并删除断点和日志。

Hugging Face 和 Genie 下载复用磁盘缓存；重启后显示已缓存字节，不生成虚假百分比。Windows 取消会终止任务进程树，Linux 与 macOS 会终止独立进程组。

Genie 共享资源位于 `python/.cache/GenieData/`，预定义角色位于 `python/CharacterModels/v2ProPlus/<角色>/`。卸载 Genie 会永久删除共享资源、当前预定义角色、仓库缓存、下载元数据和仓库锁目录，不删除 `genie_model_dir` 指向的自定义模型。

资源失败返回稳定错误码：`cancelled`、`network_timeout`、`network_unreachable`、`authentication_required`、`disk_full`、`integrity_failed`、`dependency_failed`、`unknown`。`retryable` 标识可直接重试的网络、取消和完整性错误。

## 备份

默认备份包含：

- 对话数据库
- 长期记忆数据库
- 设置
- 桌宠状态
- 插件
- 治理状态

模型、依赖目录和仓库外自定义数据库不进入默认备份。

## 边界

- 不清空仓库外的 Hugging Face 缓存。
- 不保存默认屏幕截图历史。
- 不删除未归属到受管根目录的文件。
- 模型、角色和参考音频分别清理。
