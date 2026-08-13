# Architecture

## Process boundaries

| Process | Responsibility |
| --- | --- |
| Electron main | Windows, control proxy, preload bridge, native input, lifecycle |
| Electron renderer | Vue panels, chat state, audio transport, Live2D/VRM rendering |
| Python backend | FastAPI/Socket.IO, Agent orchestration, providers, memory, tools, scheduler |
| node-mcp | MCP HTTP service and configured MCP tools |

## Runtime lanes

1. **Interaction**: chat or voice creates a session-scoped turn.
2. **Agent**: the backend streams text and emits tool, memory, and perception events.
3. **Jobs**: tools, MCP, heartbeat, scheduler, and visual capture expose created/running/progress/terminal states with cancellation and stale-result protection.
4. **Embodiment**: the renderer maps high-level states to a local avatar state machine.

Voice keeps capture and playback asynchronous. A barge-in invalidates the current output generation, cancels provider work, clears TTS queues, releases lip-sync, and preserves the new microphone turn.

## Avatar runtime

The Agent sends intent-level targets such as `listen`, `think`, `speak`, gaze, expression, motion, and idle profile. Live2D and VRM adapters apply smoothing, TTL, fade, looping, and relationship-aware strength locally. This avoids asking an LLM to emit animation frames and keeps pointer-follow and idle animation responsive.

## Perception

Vision is a request-scoped Job: `requested -> captured -> analyzed -> completed` or `discarded`. The backend never starts a permanent screenshot loop. OCR/VLM results are attached to the corresponding Agent turn and are not written to history unless explicitly requested.

## Persistence

SQLite stores chat, settings metadata, and memory. Qdrant is optional for semantic retrieval. Session runtime state remains isolated by `sessionId`; background completion updates unread state rather than switching the active session.
