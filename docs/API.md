# API reference

This document describes the local contracts used by the desktop client. It is not a public internet API.

## Endpoints

The default Python service is `http://127.0.0.1:8001`. Electron exposes a local control proxy at `http://127.0.0.1:38945`; launcher fallback ports may change either value. Protected routes use the per-run token.

| Area | Routes |
| --- | --- |
| Liveness/readiness | `GET /api/ping`, `GET /health`, `GET /api/readiness` |
| Runtime | `GET /system/status`, `GET /api/system/capabilities`, `GET /api/system/heartbeat`, `GET /api/system/experience-metrics`, `GET /api/system/agent-trace` |
| Chat | `POST /v1/chat/completions`, `GET /api/sessions`, `GET /api/history/{session_id}`, `PATCH /api/messages/{message_id}`, `DELETE /api/messages/{message_id}` |
| Export | `POST /api/export/json`, `POST /api/export/csv` |
| Settings | `GET/PATCH /api/settings`, metadata/history/export/import/rollback, provider tests, model discovery, and status routes |
| Resources | `/api/system/resources`, prepare/cancel/remove, storage status/cleanup, and backup routes |
| Vision | `/vision/ocr` and explicit Agent screenshot request events |

`/api/ping` is the lightweight liveness probe. `/health` reports component state. `/api/readiness` is protected and should be called with the backend token.

## Voice events

Realtime voice uses Socket.IO for session configuration, audio input, ASR partial/final transcripts, response deltas, TTS chunks, playback completion, and interruption. Events carry session/turn/request/generation identity where applicable. Late events are ignored after cancellation or interruption.

## Job envelope

Tool, MCP, scheduler, heartbeat, and visual operations use a common event shape:

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

Terminal statuses are `completed`, `failed`, `cancelled`, `interrupted`, and `discarded`. Progress may be coalesced; terminal events must be retained.

## Avatar commands

Avatar control is intent-level: behavior, idle profile, gaze, expression, motion, viseme/lip-sync, visibility, opacity, scale, dock, and model reload. Live2D/VRM adapters own smoothing, release timing, and frame-level work.
