# Architecture

Yuizaki is a local, multi-process desktop application. Each process owns a narrow responsibility and communicates through explicit HTTP, Socket.IO, IPC, or renderer contracts.

## Process boundaries

| Process | Owns | Does not own |
| --- | --- | --- |
| Electron main | Windows, lifecycle, preload bridge, native input, control proxy | Agent decisions, persistence, frame-level avatar behavior |
| Electron renderer | Chat/settings UI, audio transport, Live2D/VRM rendering, Job/Trace projection | API keys, backend persistence, provider orchestration |
| Python backend | FastAPI/Socket.IO, Agent turns, provider adapters, memory, vision, tools, scheduler, heartbeat | Browser window lifecycle and frame-level rendering |
| node-mcp | MCP HTTP transport and configured MCP servers | Core chat persistence or authorization policy |

## Request path

1. The renderer creates a session-scoped text or voice turn.
2. Electron forwards local control requests and the backend authenticates protected routes.
3. The Python Agent assembles context, optionally schedules tools/memory/vision Jobs, and streams output.
4. Persistence records the conversation and explainable metadata.
5. Job and avatar events are projected into the renderer.
6. The renderer maps high-level intent to local avatar behavior and audio playback.

## Runtime lanes

### Text and Agent

Text turns are the reference path. They support streaming output, tool calls, memory operations, session isolation, cancellation, and trace records.

### Voice

Capture, ASR, LLM response, TTS, playback, and lip-sync are asynchronous. A barge-in increments the interruption/generation identity, cancels provider work, clears queued audio, releases lip-sync, and rejects late events.

### Jobs

Tools, MCP, scheduler, heartbeat, and visual capture share a Job envelope with creation, progress, terminal status, cancellation, and artifact/error fields. UI progress may be coalesced; terminal events are retained.

### Embodiment

The Agent emits intent-level states such as `listen`, `think`, `execute`, and `speak`. Live2D and VRM adapters own smoothing, TTL, fade, looping, gaze, expressions, motion, and resource release. No per-frame LLM path exists.

### Perception

Vision is a request-scoped Job: `requested -> captured -> analyzed -> completed` or `discarded`. There is no permanent screenshot or camera loop. Results are attached to the originating turn and are not written to history by default.

## Persistence

SQLite stores chat, settings metadata, and memory. Qdrant is optional for semantic retrieval. Runtime state is isolated by `sessionId`; background completion updates unread state without changing the active session.

## Failure and trust boundaries

Loopback services use a per-run token. Provider failures and missing optional dependencies are surfaced as degraded capabilities. Prompt content, OCR, screenshots, web pages, and MCP output are untrusted evidence and cannot authorize policy changes. See [SECURITY.md](../SECURITY.md) for the public-release boundary.

## 中文说明

Yuizaki 由 Electron 主进程、Vue 渲染器、FastAPI/Socket.IO 后端以及可选的 node-mcp、Qdrant 和外部模型服务组成。主进程负责窗口、preload 桥接、控制代理和生命周期；渲染器负责聊天、设置、音频传输、Live2D/VRM 与任务/追踪界面；后端负责 Agent、提供商、记忆、视觉、工具、调度和心跳。启动器统一负责进程启动、端口选择、控制令牌传递和关闭顺序。
