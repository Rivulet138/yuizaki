# 本地 API / Local API

## 中文概览

Yuizaki 为桌面客户端提供本地 HTTP、SSE 和 Socket.IO 契约，不是面向公网的加固 API。默认 Python 服务为 `127.0.0.1:8001`，Electron 控制服务为 `127.0.0.1:38945`；启动器可能选择备用端口，客户端必须读取运行时配置。

- FastAPI 提供 `/openapi.json` 和 `/docs`；运行中的 schema 与路由契约测试是字段定义的权威来源。
- HTTP 路由覆盖存活/就绪、聊天与 Agent、会话、工作区、伴侣、记忆、设置、运行状态、连接器、存储和资源；`/api/realtime/*` 提供 OpenAI Realtime 语音桥的客户端密钥与转写落库。
- `POST /v1/chat/completions` 支持 SSE 流式对话；取消、工具失败、Provider 失败和未知工具效果都必须作为明确终态返回。
- 会话、历史、消息编辑、统计和导出按工作区校验；跨工作区请求返回 `403 workspace_mismatch`。
- Socket.IO 负责语音、Agent 增量、打断、权限、工具执行、追踪和桌宠状态；调度与聚合状态通过 HTTP 投影读取；变更事件名时同时更新 Python/TypeScript 契约和传输测试。
- 任务事件是有界的版本化信封（`version`、`type`、`jobId`、`status`、`revision`、`timestamp`、`data` 等），终态为 `completed`/`failed`/`cancelled`/`interrupted`/`unknown_effect`。感知请求按请求授权、单次使用，不保留连续截图或摄像头历史。

Yuizaki exposes local HTTP, SSE, and Socket.IO contracts for its desktop client. These interfaces are not a hardened public internet API.

Yuizaki 为桌面客户端提供本地 HTTP、SSE 和 Socket.IO 接口。这些接口不是经过加固的公网 API。

## Runtime discovery / 运行时发现

The default Python origin is `http://127.0.0.1:8001`; the default Electron control origin is `http://127.0.0.1:38945`. The launcher can select fallback ports and passes the selected origins to the renderer. Clients must use the runtime configuration instead of assuming a fixed port.

FastAPI publishes the live HTTP schema at `/openapi.json` and the interactive local reference at `/docs`. The running schema and route contract tests are authoritative for exact request and response fields.

`GET /api/system/route-manifest` returns `schema_version: 1`, the proxy prefixes and the advertised routes; it covers paths under `/api/`, `/memory/`, `/system/`, `/health`, and `/v1/`. The Electron control proxy validates the manifest and keeps its own explicit allowlist, so the manifest is a contract check rather than a permission to proxy every advertised path.

### Electron control HTTP / Electron 控制 HTTP

The Electron control service exposes `/health`, `/api/health`, and approved pet-asset GET paths without a control token. Other routed control requests require `Authorization: Bearer <control-token>` or `x-yuizaki-backend-token: <control-token>`. For the local browser bootstrap only, a loopback GET with no `Origin` header may use `?control_token=<control-token>`; query authentication is rejected for cross-origin requests and mutating methods. Unauthorized requests return `401` with `WWW-Authenticate: Bearer`; disallowed browser origins return `403`.

The control token is distinct from the host desktop-action token. Do not put either token in logs, source control, or reusable URLs.

## HTTP areas / HTTP 资源组

| Area | Main routes | Source |
| --- | --- | --- |
| Liveness and readiness | `/api/ping`, `/health`, `/api/readiness`, `/api/system/onboarding/readiness` | `python/routes/system_api.py`, `python/app.py` |
| Chat and Agent turns | `/v1/models`, `/v1/chat/completions`, `/api/chat/translate`, `/api/agent/recovery/resume` | `python/routes/ai_api.py` |
| Sessions and history | `/api/sessions`, `/api/history/{session_id}`, message mutations and exports; workspace-scoped and limit-bounded | `python/routes/database_api.py` |
| Realtime voice | `/api/realtime/client-secret`, `/api/realtime/transcript` | `python/routes/realtime_api.py` |
| Workspaces | `/api/workspaces`, workspace sessions, branches, effective presets, and persisted prompt context | `python/routes/workspace_api.py` |
| Companions | `/api/companions` and relationship history | `python/routes/companion_api.py` |
| Memory | `/memory/docs`, `/memory/overview`, import/export, correction, forgetting, rollback, query, and index rebuild | `python/modules/memory/routes.py` |
| Settings | `/api/settings`, provider tests, model discovery, history, import/export, and rollback | `python/modules/system/settings_api.py` |
| Runtime status | `/api/system/providers`, `/api/system/voice-diagnostics`, `/api/system/voice-diagnostics/sample`, `/api/system/voice-diagnostics/comfort`, `/api/system/voice-diagnostics/comfort-signal`, `/api/system/platforms`, permissions, schedules, trace, and metrics | `python/routes/system_api.py` |
| Summaries | `/api/summary`, `/api/summary/audit`, alert ack/snooze/clear, JSON/CSV reports, per-session summary and rewrite | `python/routes/summary_api.py` |
| Internationalization | `/api/i18n/locales`, `/api/i18n/messages` | `python/i18n.py` |
| Host computer use | `/api/computer-use/*` | `python/modules/agent/host_control.py` |
| Desktop actions | `/api/desktop-actions/*`; requires the separate host token | `python/modules/agent/host_control.py`, `python/modules/agent/desktop_actions.py` |
| Connectors | `/api/system/connectors` plus connector config, account, event, retry, cancel, and webhook routes | `python/routes/system_api.py`, `python/routes/connector_api.py` |
| Storage and resources | storage status, cleanup, backup/restore, models, avatars, and local host routes | `python/routes/storage_api.py`, `electron/src/main/http/routes` |

`/api/ping` is the lightweight liveness probe. For an Electron-managed Python child it also returns process identity fields used by Electron to reject a stale service on the configured port. `/health` reports component state. Readiness and diagnostics report configuration and observed runtime state; they do not qualify a real provider or device.

Workspace `PATCH` accepts an optional `context` object for role card, world book, prompt engineering, vision, and memory policy. The context is stored on the workspace row, so it commits in the same transaction as the rest of the workspace metadata. `context: null` clears the stored context for that workspace; `GET /api/workspaces` returns `context: null` and `contextRevision: 0` for a workspace that never stored one. Every context write (including a clear) bumps `contextRevision`, which only resets when the workspace row is deleted; sending a stale `contextRevision` returns `409 context_revision_conflict` with the current context so the caller can rebase.

### Workspace-scoped persistence / 工作区限定的持久化

Session, history, message-mutation, statistics, and export routes accept an optional `workspace_id`. When neither the request nor the active workspace supplies one, the route behaves as before; when a workspace is known, the target session or message must belong to it. A mismatch returns `403` with `error: "workspace_mismatch"` plus `active_workspace_id`, `requested_workspace_id`, and `session_workspace_id`. Missing sessions return `404`, and other database errors return `400`.

`GET /api/history/{session_id}` bounds `limit` to `1..1000` (default `100`) and filters by workspace in SQL. `GET /api/statistics` bounds `days` to `1..3650` and aggregates only the scoped workspace's messages when a workspace is supplied. Deleting a session that does not exist returns `404` instead of silently succeeding. `POST /api/realtime/transcript` additionally requires the transcript's `session_id` to belong to the resolved workspace, and its in-memory deduplication key is `workspace_id:turn_id` rather than the bare turn id.

## Streaming turns / 流式轮次

`POST /v1/chat/completions` supports the local text-turn path. Streaming HTTP responses use server-sent events and converge on one terminal result. Cancellation, tool failures, provider failures, and unknown tool effects remain explicit outcomes rather than being reported as successful completion.

The renderer normally uses its typed API clients under `electron/src/renderer/api` and chat domain modules instead of constructing raw requests.

### Realtime voice bridge / 实时语音桥

`POST /api/realtime/client-secret` mints a short-lived OpenAI Realtime client secret for the resolved workspace and session. It is rate-limited to 8 requests per 60 seconds per client address and workspace (`429` with `Retry-After`), returns `409 realtime_not_configured` when no Realtime-capable key is configured, `502 realtime_upstream_error` for an upstream status, and `503 realtime_unavailable` for transport or validation failures. A successful response includes `client_secret`, `expires_at`, `model`, `voice`, `agent_model`, `workspace_id`, and `session_id`; the long-lived provider key never reaches the renderer.

`POST /api/realtime/transcript` persists the finished turn as an atomic user/assistant pair. It returns `{status: "saved", turn_id, user_message, assistant_message}`, or `{status: "duplicate", turn_id}` when the same `workspace_id:turn_id` was already recorded; blank text returns `422 transcript_text_required`, a cross-workspace session returns `403 workspace_mismatch`, and an unavailable database returns `503`. The transcript also emits the bounded relationship signal through the same writer used by chat turns.

## Realtime events / 实时事件

Socket.IO is used for:

- connection health and interruption;
- audio chunks, ASR partial/final results, and voice activity;
- LLM request, delta, final, and error events;
- TTS chunks, playback completion, and timing;
- tool execution and permissions;
- screenshot/OCR/vision request flow;
- avatar and companion state projection.

Scheduler runs execute in a synthetic `scheduler` session. Their state, traces, and metrics are exposed through HTTP projections such as `/api/system/schedules`, `/api/system/agent-trace`, `/api/system/companion-runtime`, and `/api/system/experience-metrics`, not as live Socket.IO updates.

Canonical Python event names are defined in `python/socket_events.py`. Handler modules live under `python/socket_handlers`, with remaining registration and shared state in `python/socket_server.py`. TypeScript contracts are under `electron/src/shared`; renderer adapters reject stale session, turn, request, generation, or interruption identities.

Inbound realtime payloads are validated before decoding. `audio:chunk` accepts at most 2 MiB of PCM16 data (the base64 length is checked first) and `svc:convert` at most 6 MiB; violations end that request with a scoped error event instead of being buffered. Realtime error codes currently include:

| Code | Where | Meaning |
| --- | --- | --- |
| `AUDIO_CHUNK_TOO_LARGE` | `audio:chunk` | Chunk or decoded PCM exceeds the limit |
| `INVALID_AUDIO_CHUNK` | `audio:chunk` | Chunk is not valid base64 |
| `INVALID_SVC_AUDIO` | `svc:convert` | Audio payload is missing, too large, or not valid base64 |
| `UNSUPPORTED_PROTOCOL_VERSION` | `svc:convert` | Socket protocol version mismatch (current version is `1`) |
| `MEMORY_RECALL_FAILED` | `rag:query` → `rag:result` | Recall failed; the result carries empty `docs` and no provider detail |
| `PERMISSION_RESOLUTION_FAILED` | `permission:response` | The response could not be applied; the request stays pending |
| `PERMISSION_REQUEST_UNKNOWN` | `permission:response` | No pending permission matched the request id |
| `CHAT_PERSISTENCE_FAILED` | chat turn failure | The reply was generated but the exchange could not be durably stored |

A chat turn that cannot persist its exchange ends as a failure with `CHAT_PERSISTENCE_FAILED`; it is not reported as a delivered turn with missing message ids.

Event changes must update both Python and TypeScript contracts and their transport tests.

`POST /api/system/voice-diagnostics/sample` accepts only bounded stage timing and
recovery metadata from the renderer. `POST /api/system/voice-diagnostics/comfort`
accepts transcript-free scenario outcomes. `POST
/api/system/voice-diagnostics/comfort-signal` accepts only an explicit
`hesitation`, `backchannel`, or `background_speech` signal from `provider_vad`,
`local_vad`, or `classifier`, with bounded confidence and optional duration.
All three reject unknown fields and never accept audio, transcript, prompt, or
credential data. The resulting local snapshot is suitable for regression
visibility, not real-device release qualification; missing signals are not
inferred from missing turns.

Perception is request-scoped and single-use. `active_application` returns bounded metadata; common password-manager, finance/payment, and medical application names/titles are replaced with `[SENSITIVE_APPLICATION]`/`[REDACTED]` in the Electron main process. No continuous screenshot, camera, or active-window history is retained.

## Job events / 任务事件

Companion job events are an in-memory, bounded, replayable projection for the renderer runtime snapshot. They are not the durable record of the work: turn commits, schedules, and connector deliveries are persisted separately in SQLite, and a backend restart clears in-flight job events.

```json
{
  "version": 1,
  "type": "AgentJobProgress",
  "workspaceId": "workspace_...",
  "sessionId": "session_...",
  "turnId": "turn_...",
  "jobId": "job_...",
  "requestId": "request_...",
  "revision": 2,
  "interruptionEpoch": 0,
  "source": "tool",
  "timestamp": 1760000000000,
  "status": "progress",
  "data": {}
}
```

Optional fields are `conversationId`, `operationId`, `stepIndex`, `runId`, and `data`. `type` is the presentation name for `status` (`AgentJobCreated`, `AgentJobRunning`, `AgentJobProgress`, `AgentJobCompleted`, `AgentJobFailed`, `AgentJobCancelled`, `AgentJobInterrupted`, `AgentJobUnknownEffect`). `revision` increases monotonically per job and the presentation projection rejects gaps, stale revisions, and conflicting duplicates.

Terminal statuses are `completed`, `failed`, `cancelled`, `interrupted`, and `unknown_effect`. Progress events may be coalesced to at most one per 100 ms per job; a terminal event cannot be followed by another transition except a recheck completing it. The log holds at most 256 jobs with 64 events per job and fails closed with a capacity error instead of silently dropping a job. `GET /api/system/companion-runtime` exposes the snapshot with secret redaction and bounded truncation.

### Result verification / 结果验证

State-changing tools may include the following additive fields in `data`:

```json
{
  "verificationTarget": "tool.name",
  "verificationParameters": {
    "kind": "object",
    "count": 1,
    "keys": ["path"],
    "sha256": "..."
  },
  "verificationStatus": "verified|unverified|error|cancelled",
  "verificationEvidence": ["bounded, redacted evidence"],
  "verificationRetryable": false,
  "unknownEffect": false
}
```

These fields are observational metadata. They do not grant permission, alter the existing loopback trust model, or replace the `PolicyEngine`, permission receipt, host lease, or emergency-stop boundary. Parameter values are intentionally omitted from the summary.

The same fields are projected on `tool:result` and `tool:error` Socket.IO terminal events and are declared in `electron/src/shared/types.ts`; clients may read either the top-level fields or the additive `data` projection while migrating. These terminal events carry `schemaVersion: "yuizaki.tool-event.v1"`; the version is also listed in `electron/src/shared/runtime-protocol-manifest.json`.

### Intent envelope / 意图信封

Planning traces and durable `turn.committed`/`agent-trace.terminal` projections may include `yuizaki.intent-envelope.v1` metadata with normalized goal, bounded confidence, evidence IDs, sensitivity, confirmation requirement, and expiry. The envelope helps routing, replay and user-visible diagnostics; policy and permission components remain authoritative for side effects.

The replayable evaluator in `python/modules/agent/interpret_evaluation.py` consumes redacted golden cases from `python/tests/fixtures/intent_evaluation_cases.json` and emits `yuizaki.intent-evaluation.v1`. It checks intent, sensitivity, confirmation, and confidence ranges; a passing case never authorizes a tool.

### Proactive feedback / 主动行为反馈

`PATCH /api/system/proactive/settings` accepts `paused` for an explicit user pause. Pausing is persisted, cancels pending proactive opportunities, and survives restart; resuming only permits new opportunities. It also optionally accepts `categoryBudgets`, an object mapping bounded activity categories to daily limits (1-20). Empty or omitted mappings inherit the global `dailyBudget`; current projected categories are `conversation`, `tool_followup`, and `scheduled`. The global budget is checked first, followed by the category budget, so total daily delivery remains bounded.

`POST /api/system/proactive/feedback` accepts the existing utility labels (`useful`, `not_useful`, `too_frequent`, `wrong_time`, `never_source`) and behavioral labels (`accepted`, `ignored`, `cancelled`, `snoozed`). Behavioral labels are durable learner signals. `ignored`, `cancelled`, and `snoozed` fence the matching pending opportunity; `accepted` is recorded without consuming a delivery budget until the accepted turn is actually delivered. Recent `ignored`/`snoozed` signals add a short, reversible comfort gate to future opportunities. `ActivityFrameStore.list_feedback()` and `feedback_summary()` provide bounded replay and aggregate views for audits and offline policy evaluation.
Behavioral feedback is retained for at most 90 days per workspace; the learner uses a 30-day window with a 7-day half-life. This is a bounded preference history, not an immutable audit archive.
`feedback_summary()` also returns `categoryPreferenceScores`, a bounded decayed score per activity category so the governance UI can explain reversible suppression decisions without exposing prompt, screenshot, audio or tool content.

### Imported skill catalog / 导入技能目录

`GET /api/system/skills/imported` returns a versioned catalog snapshot. Catalog entries are untrusted metadata: they default to `runtimeBinding: "catalog_only"` and `executionReady: false`. A live runtime may set `runtimeBinding: "tool"`, `executionReady: true`, `runtimeTarget`, and bounded `runtimeScopes` only through `bind_verified_tool`, which checks manifest identity and signature; the binding is ephemeral and resets to `catalog_only` on restart. Do not present catalog presence as an executable tool. Legacy `installed`, `status`, and `ready` fields remain for client compatibility.

## Memory lifecycle / 记忆生命周期

The renderer uses the `/memory` routes for listing, querying, adding, correcting, reviewing, forgetting, restoring, rolling back, deleting, and rebuilding the optional index. SQLite remains authoritative. Permanent deletion and maintenance previews can affect chat references and the derived index, so clients should use the preview endpoints before destructive operations.

Legacy RAG query routes remain compatibility adapters. New clients should use `/memory/query`.

Memory writes may include `memory_role` with one of `user_fact`, `relationship_event`, `task_experience`, `failure_reflection`, `reusable_skill`, or `tool_permission`. The role is persisted in SQLite metadata and is deterministically inferred from legacy `layer`/`type`/`source` when omitted. `/memory/query` accepts the same `memory_role` filter; omission preserves legacy mixed recall behavior for backward compatibility.

`POST /memory/docs/delete-preview` and `POST /memory/docs/batch-delete` return `memory_role_counts`. `tool_permission` records are automatically marked `review_required`, `candidate`, `review_status=pending`, and therefore remain outside normal recall until explicitly reviewed.

The deterministic memory evaluator accepts `expected_memory_roles` and `forbidden_memory_roles` in golden cases and reports `memory_role_accuracy`, mismatch counts, and sensitive-role leakage separately from ordinary recall. The repository keeps these cases in `python/tests/fixtures/memory_role_golden_cases.json`.

A failed recall emits `rag:result` with `error: "MEMORY_RECALL_FAILED"` and empty `docs`; it does not return provider details and must not be presented as an empty memory store.

## DSH delegation / DSH 联动

`ask_dsh` is an optional Agent plugin tool, not a standalone HTTP endpoint. Its required `task`
and optional `context` describe a self-contained coding or repository task. The headless DSH
process can read and change local files, so the tool is `risk_level=high`, `effect_kind=write`
and enters the normal policy confirmation flow before execution. Plugin enablement alone must
not bypass high/critical-risk confirmation. Remembered permissions follow the tool's scoped policy.

The subprocess uses separated argv and a minimal inherited environment, never a shell command.
Tasks starting with `--` or exceeding 4000 characters are rejected. Execution is serialized;
`dsh_busy`, `dsh_not_found`, `dsh_timeout`, `dsh_nonzero_exit`, and `dsh_output_too_large`
identify queue, setup, execution, and bounded-output failures. Returned output is bounded and
sanitized. Failure after launch can leave file changes; do not automatically repeat a delegation.
The existing `CompanionJobEventLog` records queued/running/terminal tool states, visible through
`GET /api/system/companion-runtime`, without a separate DSH job store.

## Authentication and trust / 认证与信任

- Python, Socket.IO, and Electron control services bind to loopback by default.
- Python loopback traffic follows the local desktop trust model; optional non-loopback Python or Socket.IO clients require `YUIZAKI_BACKEND_API_TOKEN`.
- Electron routed control APIs require the control Bearer/header token described above, except for health and approved pet-asset GET paths. The loopback query bootstrap is restricted to no-Origin GET requests.
- Native desktop actions use a separate host-only token and are not authorized by the normal backend token.
- Connector webhook routes apply provider-specific verification. Configuration and management routes remain inside the normal backend boundary.
- In the production app, Telegram and personal bridge webhooks are acknowledged only after the inbound envelope is persisted in `connector_deliveries`; the response may contain `queued: true` while Agent execution continues. `processing`/`failed` rows are recoverable via the delivery retry route, and `sending` is treated as an unknown external effect rather than auto-retried.
- Delivery list responses include bounded `recovery` telemetry (`yuizaki.connector-recovery.v1`) with scan/recovery/failure counters and the last scan timestamp; it contains no message body or credentials.
- Prompt text, OCR, screenshots, web pages, tool output, MCP output, and plugin output are untrusted data.

Do not expose these services to a public network without a separate authentication, origin, rate-limit, secret, sandbox, tenancy, and audit design. See [Security and privacy](../SECURITY.md).

## Plugin execution lifecycle / 插件执行生命周期

Plugin routes are admitted through a registry. During Electron shutdown, admission closes before the HTTP server is closed, so a request that races with shutdown receives `503` instead of registering a new execution. Already registered executions are cancelled and shutdown waits until request-body parsing, broker work, sandbox handlers, and descendant processes settle. Cancellation returns `499`; timeout returns `504`. A dispatched external side effect can still have an unknown outcome and must not be retried automatically.

## Compatibility / 兼容性

HTTP changes should update FastAPI models and route tests. Realtime changes should update `python/socket_events.py`, the TypeScript shared contracts, and Socket.IO parity tests. Avoid documenting source line numbers; stable file and symbol names are less likely to drift during refactoring.
