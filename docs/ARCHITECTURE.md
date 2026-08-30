# Architecture / 架构

Yuizaki is a local, multi-process desktop application. Electron owns windows and host capabilities; Vue owns the user interface and avatar rendering; Python owns Agent orchestration, providers, tools, memory, and persistence.

Yuizaki 是本地多进程桌面应用。Electron 管理窗口与宿主能力，Vue 管理界面与角色渲染，Python 管理 Agent 编排、Provider、工具、记忆和持久化。

## Process boundaries / 进程边界

```text
Go launcher
  supervises ports, environment, installation, and child processes
        |
Electron main process
  windows, tray, preload, control service, host capabilities
        |
Vue renderer
  chat, settings, audio, diagnostics, Live2D and VRM
        |
FastAPI + Socket.IO backend
  turns, providers, tools, memory, scheduler, connectors
        |
optional node-mcp, Qdrant, local or remote providers
```

Primary composition points are `tools/yuizaki-launcher`, `electron/src/main`, `electron/src/renderer`, `python/app.py`, and `python/socket_server.py`. Optional services must not become prerequisites for the text-chat path.

## Request flow / 请求链路

```text
user input
  -> renderer client
  -> HTTP, SSE, or Socket.IO transport
  -> TurnService
  -> context and memory retrieval
  -> planning
  -> LLM and tool execution
  -> projection and persistence
  -> text, Job, trace, voice, and avatar feedback
```

`python/modules/agent/turn_service.py` owns turn identity and commit ordering. The Agent stages are separated into:

| Stage | Owner | Responsibility |
| --- | --- | --- |
| Context | `python/modules/agent/context_stage.py` | Workspace prompt, memory evidence, and visual intent |
| Planning | `python/modules/agent/planning_stage.py` | Typed plan and trace metadata |
| Execution | `python/modules/agent/execution_stage.py` | LLM calls, tools, streaming, cancellation, and terminal outcomes |
| Projection | `python/modules/agent/projection_stage.py` | Plugins, memory signals, pet control, and final result |

`python/modules/agent/pipeline.py` remains the compatibility facade around these stages. Transport-specific behavior stays outside the stage modules.

## Transports / 传输

- FastAPI routes serve local configuration, history, memory, diagnostics, and non-realtime operations.
- SSE serves streaming HTTP Agent turns.
- Socket.IO carries realtime voice, Agent deltas, interruption, permissions, tool jobs, traces, and avatar commands.
- Electron preload and IPC expose selected host capabilities to the renderer.
- The Electron control service proxies local browser-facing operations and binds to loopback.

Socket handlers are divided by responsibility under `python/socket_handlers`. Event names originate in `python/socket_events.py`; shared renderer contracts live under `electron/src/shared` and renderer runtime adapters. Session, turn, request, generation, and interruption identities prevent stale asynchronous results from replacing newer state.

## Voice and embodiment / 语音与具身

Renderer audio modules capture and play audio. Python ASR, LLM, and TTS providers process the selected voice path. Interruption and playback are asynchronous and scoped to the active generation. If voice is unavailable, text chat remains usable.

The Agent emits intent-level avatar commands. `electron/src/renderer/pet-renderer.ts` and the Live2D/VRM runtime adapters own frame updates, smoothing, expressions, motions, gaze, lip sync, fallback behavior, and reduced-motion handling. The LLM does not control animation frames directly.

## Perception / 环境感知

Vision is request-scoped. Electron obtains the authorized frame through the perception bridge; Python OCR or vision providers analyze it for the active request. Consent, request identity, expiry, and single-use handling are implemented in `electron/src/main/authorized-perception-bridge.ts`, `python/modules/agent/perception.py`, and the perception Socket handler. Active-application metadata is also request-scoped: built-in password, finance/payment, and medical application patterns are masked before projection, and the main process may add a user-configured matcher. There is no permanent screenshot or camera loop.

## Persistence and memory / 持久化与记忆

SQLite is authoritative for chat, turn commits, runtime delivery state, and memory. `YUIZAKI_DATA_DIR` can relocate runtime data; explicit database or settings paths override only their documented targets.

Memory retrieval applies workspace/session scope and lifecycle filters before returning evidence. Corrections preserve version history. Soft-forgotten, expired, superseded, rejected, and permanently deleted records must not cross the final recall boundary.

Qdrant is an optional rebuildable projection. When the projection is unavailable, dirty, interrupted, or rebuilding, SQLite remains available. Index maintenance is journaled and restartable; it does not replace the authority database.

## Tools and external services / 工具与外部服务

Built-in tools, MCP services, plugins, browser automation, desktop actions, and message connectors enter through explicit registries or adapters. Tool output, OCR, web content, plugin output, and MCP output are untrusted data, not authorization.

Native desktop actions are a narrow host capability: visible top-level window discovery, focus, and graceful close. Windows and explicit Linux X11 sessions have adapters. Native Wayland and macOS actions are not implemented. The feature starts disabled and uses host-side permission, lease, revocation, and emergency-stop boundaries.

## Failure boundaries / 故障边界

- Optional provider failures degrade their capability without blocking text chat.
- Cancellation carries a terminal outcome. A dispatched state-changing tool may end as `unknown_effect` rather than being retried automatically.
- Electron verifies the identity of the Python child it starts so a stale process on the same port cannot satisfy startup health.
- Connector Agent completion and external message delivery are separate durable states.
- Avatar and voice failures return to visible idle, stopped, or degraded states instead of leaving an active indicator indefinitely.

## Platform boundary / 平台边界

The supported application targets are Windows x64 and Linux x86_64 with a graphical session. The Linux shell supports X11 and Wayland, but compositor policy can restrict global hooks and desktop actions. macOS has no supported application or native-action adapter. Platform capability reporting must describe the individual capability rather than implying feature parity across operating systems.
