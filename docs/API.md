# Local API / 本地 API

Yuizaki exposes local HTTP, SSE, and Socket.IO contracts for its desktop client. These interfaces are not a hardened public internet API.

Yuizaki 为桌面客户端提供本地 HTTP、SSE 和 Socket.IO 接口。这些接口不是经过加固的公网 API。

## Runtime discovery / 运行时发现

The default Python origin is `http://127.0.0.1:8001`; the default Electron control origin is `http://127.0.0.1:38945`. The launcher can select fallback ports and passes the selected origins to the renderer. Clients must use the runtime configuration instead of assuming a fixed port.

FastAPI publishes the live HTTP schema at `/openapi.json` and the interactive local reference at `/docs`. The running schema and route contract tests are authoritative for exact request and response fields.

## HTTP areas / HTTP 资源组

| Area | Main routes | Source |
| --- | --- | --- |
| Liveness and readiness | `/api/ping`, `/health`, `/api/readiness`, `/api/system/onboarding/readiness` | `python/routes/system_api.py`, `python/app.py` |
| Chat and Agent turns | `/v1/models`, `/v1/chat/completions`, `/api/chat/translate`, `/api/agent/recovery/resume` | `python/routes/ai_api.py` |
| Sessions and history | `/api/sessions`, `/api/history/{session_id}`, message mutations and exports | `python/routes/database_api.py` |
| Workspaces | `/api/workspaces`, workspace sessions, branches, and effective presets | `python/routes/workspace_api.py` |
| Companions | `/api/companions` and relationship history | `python/routes/companion_api.py` |
| Memory | `/memory/docs`, `/memory/overview`, import/export, correction, forgetting, rollback, query, and index rebuild | `python/modules/memory/routes.py` |
| Settings | `/api/settings`, provider tests, model discovery, history, import/export, and rollback | `python/modules/system/settings_api.py` |
| Runtime status | `/api/system/providers`, `/api/system/voice-diagnostics`, `/api/system/voice-diagnostics/sample`, `/api/system/voice-diagnostics/comfort`, `/api/system/voice-diagnostics/comfort-signal`, `/api/system/platforms`, permissions, schedules, trace, and metrics | `python/routes/system_api.py` |
| Connectors | `/api/system/connectors` plus connector config, account, event, retry, cancel, and webhook routes | `python/routes/system_api.py`, `python/routes/connector_api.py` |
| Storage and resources | storage status, cleanup, backup/restore, models, avatars, and local host routes | `python/routes/storage_api.py`, `electron/src/main/http/routes` |

`/api/ping` is the lightweight liveness probe. For an Electron-managed Python child it also returns process identity fields used by Electron to reject a stale service on the configured port. `/health` reports component state. Readiness and diagnostics report configuration and observed runtime state; they do not qualify a real provider or device.

## Streaming turns / 流式轮次

`POST /v1/chat/completions` supports the local text-turn path. Streaming HTTP responses use server-sent events and converge on one terminal result. Cancellation, tool failures, provider failures, and unknown tool effects remain explicit outcomes rather than being reported as successful completion.

The renderer normally uses its typed API clients under `electron/src/renderer/api` and chat domain modules instead of constructing raw requests.

## Realtime events / 实时事件

Socket.IO is used for:

- connection health and interruption;
- audio chunks, ASR partial/final results, and voice activity;
- LLM request, delta, final, and error events;
- TTS chunks, playback completion, and timing;
- tool execution, permissions, jobs, traces, and scheduler updates;
- screenshot/OCR/vision request flow;
- avatar and companion state projection.

Canonical Python event names are defined in `python/socket_events.py`. Handler modules live under `python/socket_handlers`, with remaining registration and shared state in `python/socket_server.py`. TypeScript contracts are under `electron/src/shared`; renderer adapters reject stale session, turn, request, generation, or interruption identities.

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

## Job envelope / 任务信封

Tools, scheduler operations, memory maintenance, connectors, and perception use durable or projected job states. A typical projection contains:

```json
{
  "jobId": "job_...",
  "runId": "run_...",
  "sessionId": "session_...",
  "kind": "tool",
  "status": "running",
  "progress": 0.5,
  "summary": "Running",
  "artifact": null,
  "error": null
}
```

Consumers must handle terminal states such as `completed`, `failed`, `cancelled`, `interrupted`, `discarded`, and `unknown_effect`. Progress events may be coalesced; terminal events and failure receipts must be retained.

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

`GET /api/system/skills/imported` returns a versioned catalog snapshot. Imported entries expose `runtimeBinding: "catalog_only"` and `executionReady: false` until a trusted executor is explicitly integrated; catalog presence must not be presented as an executable tool. Legacy `installed`, `status`, and `ready` fields remain for client compatibility.

## Memory lifecycle / 记忆生命周期

The renderer uses the `/memory` routes for listing, querying, adding, correcting, reviewing, forgetting, restoring, rolling back, deleting, and rebuilding the optional index. SQLite remains authoritative. Permanent deletion and maintenance previews can affect chat references and the derived index, so clients should use the preview endpoints before destructive operations.

Legacy RAG query routes remain compatibility adapters. New clients should use `/memory/query`.

Memory writes may include `memory_role` with one of `user_fact`, `relationship_event`, `task_experience`, `failure_reflection`, `reusable_skill`, or `tool_permission`. The role is persisted in SQLite metadata and is deterministically inferred from legacy `layer`/`type`/`source` when omitted. `/memory/query` accepts the same `memory_role` filter; omission preserves legacy mixed recall behavior for backward compatibility.

`POST /memory/docs/delete-preview` and `POST /memory/docs/batch-delete` return `memory_role_counts`. `tool_permission` records are automatically marked `review_required`, `candidate`, `review_status=pending`, and therefore remain outside normal recall until explicitly reviewed.

The deterministic memory evaluator accepts `expected_memory_roles` and `forbidden_memory_roles` in golden cases and reports `memory_role_accuracy`, mismatch counts, and sensitive-role leakage separately from ordinary recall. The repository keeps these cases in `python/tests/fixtures/memory_role_golden_cases.json`.

## Authentication and trust / 认证与信任

- Python, Socket.IO, and Electron control services bind to loopback by default.
- Loopback clients are trusted by the desktop application and do not use per-request Bearer authentication.
- Optional non-loopback Python or Socket.IO clients require `YUIZAKI_BACKEND_API_TOKEN`.
- Native desktop actions use a separate host-only token and are not authorized by the normal backend token.
- Connector webhook routes apply provider-specific verification. Configuration and management routes remain inside the normal backend boundary.
- In the production app, Telegram and personal bridge webhooks are acknowledged only after the inbound envelope is persisted in `connector_deliveries`; the response may contain `queued: true` while Agent execution continues. `processing`/`failed` rows are recoverable via the delivery retry route, and `sending` is treated as an unknown external effect rather than auto-retried.
- Delivery list responses include bounded `recovery` telemetry (`yuizaki.connector-recovery.v1`) with scan/recovery/failure counters and the last scan timestamp; it contains no message body or credentials.
- Prompt text, OCR, screenshots, web pages, tool output, MCP output, and plugin output are untrusted data.

Do not expose these services to a public network without a separate authentication, origin, rate-limit, secret, sandbox, tenancy, and audit design. See [Security and privacy](../SECURITY.md).

## Compatibility / 兼容性

HTTP changes should update FastAPI models and route tests. Realtime changes should update `python/socket_events.py`, the TypeScript shared contracts, and Socket.IO parity tests. Avoid documenting source line numbers; stable file and symbol names are less likely to drift during refactoring.
