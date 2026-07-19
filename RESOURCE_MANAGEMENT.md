# 资源管理

本文定义模型、缓存、数据库、备份与永久清理的实际行为。删除操作均为永久删除，不提供软删除兼容层。

## 资源分类

| 类型 | 默认位置 | 生命周期 | 是否备份 |
| --- | --- | --- | --- |
| 对话库 | `python/data/chat.db` | 持久 | 是 |
| 长期记忆 | `python/data/memory.db` | 持久 | 是 |
| 设置 | `python/config/settings.json` | 持久 | 是 |
| TTS 音频 | `python/audio_cache/` | 临时 | 当前备份包含 |
| 实时视觉帧 | 进程内存 | 会话级，默认 TTL 60 秒 | 否 |
| OCR 上传 | 请求内存 | 请求级 | 否 |
| Electron 依赖 | `electron/node_modules/` | 可重建 | 否 |
| Python 环境 | `python/.venv/` | 可重建 | 否 |
| Hugging Face/模型缓存 | `python/.cache/` 等 | 可重下 | 否 |
| 桌宠模型 | 内置资源或受管导入目录 | 持久 | 导入目录按功能管理 |

自定义 `MEMORY_SQLITE_PATH` 指向仓库外时，不会被默认备份自动发现。生产使用自定义路径时必须配置外部备份。

## 按需下载

资源管理器识别 `soulx`、`sherpa`、`sherpa_online`、`embedding` 和 `tts`。第一次调用能力或用户在设置中手动准备时下载；同一资源的并发准备请求会合并。

当前 ready 判断主要基于文件存在与模型加载验证。后续必须升级为资源锁：固定 revision、SHA-256、许可证、体积、平台和状态。未通过校验的部分下载不得标记 ready。

## 自动清理

Python janitor 默认每 600 秒运行一次，只删除超过 1800 秒的受管生成文件：

- `python/audio_cache/*.wav`
- Yuizaki 命名的预热与 SVC 临时音频

它不会删除用户任意音频、数据库、模型缓存或实时视觉 PNG。实时视觉本身不写 PNG，只在内存中替换每个会话的最新帧。

## 手动永久清理

`GET /api/system/storage` 返回类别、大小和文件数。`POST /api/system/storage/cleanup` 使用固定确认词 `PERMANENT_CLEAN`，可处理：

- `tts_audio`：永久删除受管 TTS 音频文件
- `runtime_temp`：永久删除受管运行时临时文件
- `memory`：压缩 SQLite/Qdrant 存储，不删除记忆记录

`visual_frames` 始终是内存状态，不存在磁盘清理动作。实现会跳过符号链接，避免越过受管目录。

## 备份与恢复

默认备份目标：

- `python/data/chat.db`
- `python/data/memory.db`
- `python/config/settings.json`
- `python/data/governance_alert_state.json`
- `python/audio_cache/`
- Electron `pet-state.json`
- `electron/plugins/`

恢复默认先生成 dry-run 计划；执行恢复时会拒绝受管根目录外路径、符号链接目标和被替换成符号链接的父目录。

模型资源不进入备份，原因是体积大且应由资源锁重建。角色资源的授权文件不可在清理时单独丢弃。

## 本次磁盘取证

本机开发目录抽样：

| 路径 | 占用 |
| --- | ---: |
| `python/.cache` | 约 3.00 GiB |
| `python/.venv` | 约 2.79 GiB |
| `electron/node_modules` | 约 731 MiB |
| `python/CharacterModels` | 约 321 MiB |
| `electron/dist` | 约 33 MiB |
| `node-mcp/node_modules` | 约 19 MiB |

这些目录合计超过 7 GiB，但大部分可重建且已被 Git 忽略。清理建议顺序：

1. 使用界面清理 TTS 和运行时临时文件。
2. 确认无运行进程后删除并重建陈旧 `node_modules`。
3. 按模型 ID 删除不再使用的缓存，不能整库盲删。
4. 虚拟环境损坏或跨 Python 版本时删除并重建 `.venv`。
5. 保留数据库备份后再执行数据库维护。

## 尚缺的资源功能

P0：增加统一资源清单和内容校验；固定 SoulX 与 Hugging Face revision；验证 Sherpa 归档 SHA-256。

P1：设置页展示资源体积、版本、许可证、使用方、最后使用时间，并提供带依赖检查的永久卸载。

P1：为模型缓存设置可选磁盘预算和 LRU 提示，但不自动删除正在使用的模型。

P2：发布构建生成资源 SBOM，将模型、代码依赖和角色素材分开列示。
