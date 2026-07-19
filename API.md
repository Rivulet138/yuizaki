# API

维护基线：2026-07-19。默认 Python 服务为 `http://127.0.0.1:8001`，Electron 控制服务为 `http://127.0.0.1:38945`。

## 认证

Python 的 `/api`、`/memory`、`/vision`、`/svc` 等受保护前缀默认要求 backend token。Electron 控制服务负责把桌面端请求代理到后端。仅隔离本地开发可以设置 `YUIZAKI_ALLOW_UNAUTHENTICATED_LOCAL_DEV=1`。

不要把 token 放进 URL、日志或前端持久化明文。健康检查与必要的静态音频读取按中间件白名单处理。

## 系统与健康

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/health` | Python 健康状态 |
| GET | `/api/readiness` | 依赖就绪状态 |
| GET | `/system/status` | 后端模块状态 |
| GET | `/api/system/heartbeat` | 桌宠心跳 |
| GET | `/api/system/capabilities` | 能力注册信息 |
| GET | `/api/system/experience-metrics` | 延迟与体验指标 |
| GET | `/api/system/agent-trace` | Agent 执行记录 |

## 对话与模型

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| POST | `/v1/chat/completions` | OpenAI 兼容文本生成 |
| POST | `/v1/models` | 查询模型列表 |
| POST | `/api/chat/translate` | 翻译 |
| GET | `/api/sessions` | 会话列表 |
| GET | `/api/history/{session_id}` | 会话历史 |
| PATCH | `/api/messages/{message_id}` | 修改消息 |
| DELETE | `/api/messages/{message_id}` | 永久删除消息 |
| POST | `/api/export/json` | 导出 JSON |
| POST | `/api/export/csv` | 导出 CSV |

## 工作区与角色

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET/POST | `/api/workspaces` | 列出或创建工作区 |
| PATCH/DELETE | `/api/workspaces/{workspace_id}` | 更新或永久删除工作区 |
| GET/POST | `/api/workspaces/{workspace_id}/sessions` | 工作区会话 |
| GET/POST | `/api/companions` | 列出或创建桌宠角色 |
| GET/PATCH/DELETE | `/api/companions/{companion_id}` | 读取、更新或永久删除角色 |

## 记忆与摘要

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET/POST | `/memory/docs` | 记忆文档列表与新增 |
| PUT/DELETE | `/memory/docs/{doc_id}` | 更新或永久删除记忆 |
| POST | `/memory/docs/batch-delete` | 批量永久删除 |
| POST | `/memory/memory/add` | 新增记忆项 |
| POST | `/memory/rag/query` | RAG 查询 |
| GET | `/memory/index/status` | 索引状态 |
| POST | `/memory/index/rebuild` | 重建索引 |
| POST | `/memory/maintenance/preview` | 维护预览 |
| POST | `/memory/maintenance/apply` | 应用维护 |
| GET | `/api/summary` | 摘要总览 |
| GET | `/api/summary/audit` | 摘要审计 |
| POST | `/api/summary/{session_id}/rewrite` | 重写会话摘要 |

存储清理目标 `memory` 只做数据库压缩，不删除记忆记录；记录删除使用明确的 memory API。

## 视觉、语音与 SVC

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| POST | `/vision/ocr` | 对上传图片做显式 OCR |
| POST | `/svc/convert` | 音色转换 |
| POST | `/api/settings/test/tts` | TTS 测试 |
| POST | `/api/settings/tts/warmup` | TTS 预热 |
| GET | `/api/settings/tts/status` | TTS 状态 |

实时视觉帧和流式语音通过 Socket.IO 传输，不通过 OCR 路由轮询。

## 设置

设置路由前缀为 `/api/settings`：

- `GET /`、`PATCH /`：读取与批量更新
- `GET /metadata`：字段元数据
- `GET/DELETE /history`：历史与清空
- `GET /export`、`POST /import`：导出导入
- `POST /rollback`：回滚
- `POST /test/llm`、`POST /llm/models`、`GET /llm/status`
- `GET/POST/DELETE /{key}`：单字段操作

## Electron 控制服务

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/api/system/resources` | 受管模型资源状态 |
| POST | `/api/system/resources/prepare` | 批量准备资源 |
| POST | `/api/system/resources/sherpa/download` | 准备离线 Sherpa |
| POST | `/api/system/resources/sherpa-online/download` | 准备在线 Sherpa |
| POST | `/api/system/resources/embedding/prefetch` | 预取嵌入模型 |
| POST | `/api/system/resources/tts/prefetch` | 预取 TTS |
| POST | `/api/system/resources/soulx/download` | 准备 SoulX |
| GET | `/api/system/storage` | 存储用量 |
| POST | `/api/system/storage/cleanup` | 永久清理受管临时文件 |
| GET | `/api/system/backup/targets` | 备份目标 |
| POST | `/api/system/backup/create` | 创建备份 |
| POST | `/api/system/backup/restore` | 预览或执行恢复 |

清理请求必须带 `confirmation: "PERMANENT_CLEAN"`。具体类别见 [RESOURCE_MANAGEMENT.md](RESOURCE_MANAGEMENT.md)。

## Socket.IO 事件族

- `system.*`：心跳、错误、延迟、打断、权限
- `audio.*`：音频块、ASR partial/final、VAD 与 speech start
- `llm.*`：请求、delta、final
- `tts.*`：音频 chunk、done
- `agent.*`：对话与结构化动作结果
- `tool.*`：调用、结果和错误
- `screenshot.*`：最新视觉帧与分析结果
- `pet.*`：桌宠状态与动作控制
- `memory.*`：实时记忆查询
- `svc.*`：音色转换

事件 payload 在 `python/protocol/` 与前端共享类型附近维护。新增事件时必须同时更新协议测试和本文档。
