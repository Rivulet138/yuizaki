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
| Runtime status | `/api/system/providers`, `/api/system/voice-diagnostics`, `/api/system/platforms`, permissions, schedules, trace, and metrics | `python/routes/system_api.py` |
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

## Memory lifecycle / 记忆生命周期

The renderer uses the `/memory` routes for listing, querying, adding, correcting, reviewing, forgetting, restoring, rolling back, deleting, and rebuilding the optional index. SQLite remains authoritative. Permanent deletion and maintenance previews can affect chat references and the derived index, so clients should use the preview endpoints before destructive operations.

Legacy RAG query routes remain compatibility adapters. New clients should use `/memory/query`.

## Authentication and trust / 认证与信任

- Python, Socket.IO, and Electron control services bind to loopback by default.
- Loopback clients are trusted by the desktop application and do not use per-request Bearer authentication.
- Optional non-loopback Python or Socket.IO clients require `YUIZAKI_BACKEND_API_TOKEN`.
- Native desktop actions use a separate host-only token and are not authorized by the normal backend token.
- Connector webhook routes apply provider-specific verification. Configuration and management routes remain inside the normal backend boundary.
- Prompt text, OCR, screenshots, web pages, tool output, MCP output, and plugin output are untrusted data.

Do not expose these services to a public network without a separate authentication, origin, rate-limit, secret, sandbox, tenancy, and audit design. See [Security and privacy](../SECURITY.md).

## Compatibility / 兼容性

HTTP changes should update FastAPI models and route tests. Realtime changes should update `python/socket_events.py`, the TypeScript shared contracts, and Socket.IO parity tests. Avoid documenting source line numbers; stable file and symbol names are less likely to drift during refactoring.
