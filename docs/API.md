# API reference

This document describes the local contracts used by the desktop client. It is
not a public internet API. Route names below are taken from the current Python
route modules and Electron control-server dispatch; contract tests remain the
authoritative compatibility check.

## Endpoints

The default Python service is `http://127.0.0.1:8001`. Electron exposes a local control proxy at `http://127.0.0.1:38945`; launcher fallback ports may change either value. The proxy binds to loopback, accepts `localhost` and `127.0.0.1` browser origins on any port, and rejects remote, `file:`, and `null` origins. Direct Python and Socket.IO access continues to use the backend token.

| Area | Routes and code source |
| --- | --- |
| Liveness/readiness | `GET /api/ping`, `GET /health`, `GET /api/readiness`; `python/routes/system_api.py:195-217` and `python/app.py` |
| Chat | `POST /v1/models`, `POST /v1/chat/completions`, `POST /api/chat/translate`; `python/routes/ai_api.py:212-418` |
| Sessions/history | `GET /api/sessions`, `GET /api/history/{session_id}`, message/session mutations and exports; `python/routes/database_api.py:69-202` |
| Workspaces | Workspace CRUD, workspace sessions, branches, effective prompt; `python/routes/workspace_api.py:50-173` |
| Companions | Companion list/detail/create/update/delete and relationship history; `python/routes/companion_api.py:52-100` |
| Memory | Docs, overview, add/update/correction/review, candidates, soft-forget/restore/rollback, maintenance, index status/rebuild, query/RAG; `python/modules/memory/routes.py:893-1654` |
| Runtime/proactive | Onboarding readiness, heartbeat, companion runtime opportunities, proactive settings/feedback, activity frames, capabilities, orchestration, permissions, schedules, trace, experience metrics, and product-metrics consent; `python/routes/system_api.py:217-590` |
| Settings | Settings CRUD, metadata/history/export/import/rollback, LLM/TTS tests and discovery; `python/modules/system/settings_api.py:798-935` |
| Resources/storage | Resource preparation/removal and storage status/cleanup; `python/routes/storage_api.py:211-212`, Electron system/model routes under `electron/src/main/http/routes` |
| Realtime voice | Client secret and transcript HTTP helpers plus Socket.IO audio/ASR/LLM/TTS events; `python/routes/realtime_api.py:375-376`, `python/socket_server.py:2536-3046` |
| Vision | Screenshot request/result events and internal OCR/vision analyzers; `python/socket_server.py:1249-1824`, `python/socket_server.py:3181-3341`; no public OCR upload route |

`/api/ping` is the lightweight liveness probe. `/health` reports component state. `/api/readiness` is protected and should be called with the backend token.

## Product metrics consent

The product-metrics consent contract is backed by the runtime data directory,
not renderer `localStorage`:

| Method | Route | Request | Response / behavior |
| --- | --- | --- | --- |
| `GET` | `/api/system/product-metrics/consent` | none | `{ consented, scope: "local_product_metrics", transport: "not_configured" }`; missing or corrupt durable state is closed (`consented: false`) |
| `PATCH` | `/api/system/product-metrics/consent` | `{ "consented": boolean }` | Persists the explicit decision atomically and returns the same snapshot; unknown fields and non-boolean values are rejected with `422`, persistence failures with `409` |

The Electron control proxy supplies the local backend boundary. The renderer
calls these routes through `systemClient.productMetricsConsent()` and
`patchProductMetricsConsent()`; no remote event endpoint is configured by this
repository.

The local exporter also exposes an optional `ProductEventBatchTransport` shape
whose `send_batch` receives a deterministic SHA-256 `idempotency_key` for the
normalized batch. The legacy one-argument `send` transport remains supported;
this key is a retry/deduplication boundary, not evidence that a remote service
or authenticated delivery is configured.

Normalized product events accept only a pseudonymous `user_id` format made of
ASCII letters, digits, `.`, `_`, `:`, or `-` (maximum 128 characters). Email
addresses, whitespace-bearing display names, and other direct identifiers are
dropped before local persistence or transport.

`python/evals/product_metrics_transport.py` provides the opt-in
`HttpProductEventTransport` implementation. It requires HTTPS, an explicit
origin allowlist, a bearer token, bounded payload size, and bounded retries.
`send_batch()` accepts 2xx and idempotent duplicate (`409`) acknowledgements;
`delete_batch()` is separate and requires an explicit deletion endpoint. No
endpoint or token is configured by the application runtime.

`ConsentGatedProductEventExporter.revoke_consent()` always revokes the local
store first. If the transport exposes `delete_batch()`, it then reports whether
the remote deletion was acknowledged or failed; a remote failure never restores
local events or leaves local consent enabled.

## 中文说明

本页描述本地控制面、后端 HTTP 接口、Socket.IO 事件和 MCP 边界。Electron 控制代理只监听回环地址，允许任意端口的 `localhost`/`127.0.0.1` 浏览器来源，并拒绝远程、`file:` 与 `null` 来源；控制路由不再要求额外令牌。Python 与 Socket.IO 直连仍使用 Backend API Token。具体路由和事件名称以当前源码及契约测试为准。API 变更必须同步增加或更新契约测试，并更新本文件。

## Voice events

Realtime voice uses Socket.IO for heartbeat, interruption, permission response,
audio chunks, ASR partial/final/VAD events, LLM request/delta/final, TTS chunks
and completion, and client timing. The server handlers are registered in
`python/socket_server.py:2536-3046`; renderer event adapters are in
`electron/src/renderer/app/runtime/realtimeVoiceEventBridge.ts`,
`voiceEventBridge.ts`, and `electron/src/renderer/net/socketClient.ts`.
Events carry session/turn/request/generation/interruption identity where
applicable. The renderer rejects stale scopes in
`useVoiceConversationBridge.ts:68-73` and stops or falls back when transport
state becomes invalid.

## Job envelope

Tool, MCP, scheduler, heartbeat, and visual operations use a common projection
shape. The exact fields are produced by `companion_events.py`,
`agent_trace_store.py`, `turn_outbox.py`, and renderer projection modules:

```json
{
  "jobId": "job_...",
  "runId": "run_...",
  "sessionId": "session_...",
  "kind": "tool",
  "status": "running",
  "progress": 0.5,
  "summary": "human-readable status",
  "artifact": null,
  "error": null
}
```

Terminal statuses include `completed`, `failed`, `cancelled`, `interrupted`,
`discarded`, `unknown_effect`, and budget/permission failure reasons. Progress
may be coalesced; terminal events and failure receipts must be retained. The
tool loop explicitly returns cancellation, invalid adapter result, tool budget,
unknown effect, permission, and max-iteration outcomes in
`python/modules/agent/tool_loop.py:125-251`.

## Avatar commands

Avatar control is intent-level: behavior, idle profile, gaze, expression, motion, viseme/lip-sync, visibility, opacity, scale, dock, and model reload. Live2D/VRM adapters own smoothing, release timing, and frame-level work.

Runtime state feedback uses `CompanionEmbodimentIntent` version 1. It carries
only operational state, source, confidence, expiry, reduced-motion, and the
user's pet-link decision. It never carries persona or prompt text. Non-idle
states have a bounded renderer TTL, and expired or user-disabled intents resolve
to idle before reaching either avatar adapter.

Avatar commands are emitted by backend/Socket.IO `PetEvents.CONTROL` and
consumed by `electron/src/renderer/app/composables/useVoiceConversationBridge.ts`
and `electron/src/renderer/utils/petControl.ts`. Native pet/model HTTP routes
are dispatched by `electron/src/main/control-server.ts` and the route modules
under `electron/src/main/http/routes`.

## Authentication and trust

- Loopback Python API and Socket.IO clients are trusted by default; non-loopback clients use `YUIZAKI_BACKEND_API_TOKEN` through `python/modules/system/backend_api_auth.py`.
- Electron creates and stores that optional non-loopback token through `backend-api-token-store.ts`; ControlServer routes do not add another Bearer or admin-token gate.
- Socket.IO loopback detection and non-loopback token validation are handled in `python/socket_server.py`.
- MCP, plugin, screenshot, OCR, webpage, and tool outputs are data, not authority. `tool_loop.py:169-224` labels tool output as untrusted and gives it no instruction authority.
- Permission requests are explicit events (`SystemEvents.PERMISSION_REQUEST` / `PERMISSION_RESPONSE`) and native desktop actions have revocation/emergency-stop fences.

## Contract-test locations

- Python route and socket contracts: `python/tests/test_runtime_endpoints.py`, `test_memory_routes.py`, `test_socket_server_contract.py`, `test_electron_perception_transport.py`, `test_desktop_action_contract.py`.
- Electron route/IPC contracts: `electron/src/main/__tests__`, `electron/src/preload/__tests__`, and renderer `api-clients`, `socketClient`, `voice`, `memory`, `pet`, and `onboarding` tests.
- API changes should update the relevant contract test and this file in the same change.
