# Architecture

Yuizaki is a local, multi-process desktop application. The boundaries below are
implemented by the current source tree; this page is a map of code ownership,
not a substitute for runtime validation.

## Process boundaries

| Process | Owns | Does not own |
| --- | --- | --- |
| Electron main | Windows, lifecycle, preload bridge, native input, control proxy | Agent decisions, persistence, frame-level avatar behavior |
| Electron renderer | Chat/settings UI, audio transport, Live2D/VRM rendering, Job/Trace projection | API keys, backend persistence, provider orchestration |
| Python backend | FastAPI/Socket.IO, Agent turns, provider adapters, memory, vision, tools, scheduler, heartbeat | Browser window lifecycle and frame-level rendering |
| node-mcp | MCP HTTP transport and configured MCP servers | Core chat persistence or authorization policy |

Primary wiring is visible in `electron/src/main/control-server.ts`,
`electron/src/main/index.ts`, `python/app.py`, and `python/socket_server.py`.
The renderer-to-backend HTTP clients live under
`electron/src/renderer/api/clients`; Socket.IO event names and transport logic
live in `electron/src/renderer/net/socketClient.ts` and
`python/socket_server.py`.

## Request path

1. `chat-client.ts` or the Socket.IO bridge creates a session/workspace/turn-scoped request.
2. Electron main routes local control, onboarding, pet, plugin, model, and perception requests through `ControlServer`.
3. Python `TurnService` binds request context and persistence to `AgentPipeline`.
4. `AgentPipeline` resolves intent/context, invokes `Planner`, and delegates typed steps to `StepExecutor` and `ToolExecutor`.
5. LLM deltas, tool results, permission requests, Job events, and Avatar commands are emitted through Socket.IO or HTTP streaming.
6. `TurnCommitStore`/`TurnOutboxDispatcher` persist and project turn state; memory writes and retrieval traces are stored separately.
7. Renderer bridges (`companionJobProjection.ts`, `companionRuntime.ts`, `useVoiceConversationBridge.ts`) map events to chat, audio, trace, and frame-level Avatar behavior.

## Runtime lanes

### Text and Agent

Text turns are the reference path. `python/routes/ai_api.py:212-370` exposes the
HTTP stream, while `python/modules/agent/turn_service.py` and
`python/modules/agent/pipeline.py` own the Agent path. Tool calls, memory
operations, session/workspace isolation, cancellation, and trace records are
implemented by separate collaborators rather than by the route handler alone.

### Voice

Capture, ASR, LLM response, TTS, playback, and lip-sync are asynchronous. The
renderer bridge uses realtime and local-pipeline transports, checks microphone
permission, increments interruption identity, and falls back when realtime is
unavailable (`useVoiceConversationBridge.ts:256-375`). The Python Socket.IO
server handles ASR partial/final events, LLM deltas, TTS chunks, and interruption
acknowledgement (`python/socket_server.py:2536-3046`).

### Jobs

Tools, MCP, scheduler, heartbeat, and visual capture share Job projection
primitives. `python/modules/agent/companion_events.py`,
`python/modules/agent/agent_trace_store.py`, and
`electron/src/renderer/app/runtime/companionJobProjection.ts` carry progress,
terminal status, cancellation, artifact, and error data. Tool-loop terminal
reasons include `completed`, `cancelled`, `unknown_effect`, permission failure,
budget exhaustion, and `max_iterations` (`tool_loop.py:125-251`).

### Embodiment

The Agent emits intent-level states such as `listen`, `think`, `execute`, and
`speak`. The renderer normalizes these into the versioned operational-only
`CompanionEmbodimentIntent` contract (`companion-embodiment.ts`) with a closed
state vocabulary, source, confidence, and bounded TTL. Persona prompts remain
in the conversation layer and are never animation inputs. User pet-link and
system reduced-motion preferences are evaluated before delivery; disabled,
expired, or high-motion terminal feedback falls back to restrained idle/waiting
behavior without suppressing semantic status in the main UI.
`pet-embodiment-coordinator.ts`,
`pet-sentence-emotion-scheduler.ts`, `live2d-runtime-adapter.ts`, and
`vrm-runtime-adapter.ts` own smoothing, TTL, fade, looping, gaze, expressions,
motion, viseme/lip-sync, and resource release. No per-frame LLM path exists.

### Perception

Vision is a request-scoped Job. `PerceptionRequest` requires workspace,
session, turn, capability, generation, and interruption identity; consent is
single-use and expires (`python/modules/agent/perception.py:59-177`). Electron
captures through `authorized-perception-bridge.ts` and `desktop-capture.ts`.
There is no permanent screenshot/camera collector in the current code. Visual
results are attached to the originating turn and OCR/LLM analysis runs only
after the authorized frame path (`python/socket_server.py:1249-1824`).

## Persistence

SQLite-backed repositories store chat, settings metadata, turn commits, and
memory. `python/modules/memory/backend_factory.py` selects the memory backend;
`qdrant-client` and embedding code are optional projections. Runtime context is
scoped by workspace/session/turn/request identities, and renderer stores project
background completion without replacing the active session.

## Failure and trust boundaries

`electron/src/main/control-server.ts`, `backend-api-token-store.ts`, and
`python/modules/system/backend_api_auth.py` enforce loopback/per-run token
boundaries. `tool_registry.py` models risk, confirmation, and remembered
decisions; `mcp_manager.py` registers external tools as medium-risk and
confirmation-required; `tool_loop.py` marks MCP/tool output as untrusted with
no instruction authority. Provider and optional-dependency degradation is
reported through readiness/capability routes, but end-to-end hardware quality
remains unverified here.

## Known architectural gaps

- `python/modules/agent/pipeline.py` remains the main orchestration seam for intent, context, planning, execution, retrieval prefetch, and projection; split ownership would reduce change risk.
- `python/socket_server.py` combines authentication, voice, visual capture, LLM, tool, memory, and event handlers; typed handler modules would reduce Socket.IO contract drift.
- Native Desktop Action has Windows user32 and Linux X11 adapters (`desktop_actions.py:187-196`, `:358-542`); pure Wayland and unsupported platforms fail closed and macOS has no adapter.
- Job artifacts and postcondition verification are represented in contracts but need consistent user-facing rendering and tool-specific success checks.

## 中文说明

Yuizaki 由 Electron 主进程、Vue 渲染器、FastAPI/Socket.IO 后端以及可选的 node-mcp、Qdrant 和外部模型服务组成。主进程负责窗口、preload 桥接、控制代理和生命周期；渲染器负责聊天、设置、音频传输、Live2D/VRM 与任务/追踪界面；后端负责 Agent、提供商、记忆、视觉、工具、调度和心跳。启动器统一负责进程启动、端口选择、可选非回环 Backend Token 传递和关闭顺序；回环请求默认可信。
