# Product scope

## Promise

Yuizaki is a local desktop companion that can talk, listen, remember, use tools, and express high-level Agent state through a Live2D or VRM avatar.

## Supported core loop

```text
input -> session-scoped turn -> optional Job
      -> streamed text or audio -> persistence -> avatar feedback
```

The text lane is the reference path. Voice, vision, TTS, ASR, remote providers, and optional services activate only when their dependencies and settings are available.

## Capability matrix

| Capability | Product status | Boundary |
| --- | --- | --- |
| Text chat | Supported | Requires a configured LLM provider |
| Sessions and history | Supported | Stored locally in SQLite |
| Tools and MCP | Supported with review | Configured tools may access local or remote systems |
| Memory | Supported | SQLite is the default; semantic retrieval is optional |
| Live2D/VRM pet | Supported with assets | User-provided models remain separately licensed |
| Realtime voice | Optional | Requires provider, model, microphone, speaker, and permissions |
| Vision | Optional and request-scoped | No continuous capture loop |
| Heartbeat/scheduler | Supported | Low-frequency, bounded, inspectable jobs |
| Cloud multi-user service | Not supported | Local loopback security model |

## Product boundaries

- No always-on screen or camera capture.
- No public server hardening or multi-tenant isolation claim.
- No bundled third-party model weights, voices, or avatar assets by default.
- No claim that unit tests replace real hardware/provider validation.
- No promise of Discord, Telegram, PWA/mobile, browser extension, or game-agent integrations in the current release.

## Design direction

Yuizaki follows a local-first, event-driven desktop model: the backend owns Agent orchestration and persistence; the renderer owns input, audio transport, and frame-level avatar behavior; jobs expose progress and terminal states; stale work is rejected by session/turn/request identities.

## Next increments

1. More full-duplex voice providers and measured VAD tuning.
2. Clearer user-facing Job artifacts and pet state transitions.
3. External messaging connectors using the same cancellable Job protocol.
4. Optional browser/PWA runtime.
5. Separate game-agent integrations.
