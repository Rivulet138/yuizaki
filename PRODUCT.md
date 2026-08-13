# Product scope

## Core promise

Yuizaki provides a local-first AI companion that can talk, listen, remember, use tools, and express the result through a Live2D or VRM desktop avatar.

## Completed core loop

`user input -> session-scoped Agent turn -> optional tool/memory/vision Job -> streamed response -> TTS or text -> avatar state feedback`

Voice turns support push-to-talk and continuous capture, provider VAD, barge-in cancellation, ordered TTS, and lip-sync cleanup. The pet restores its last selected model at startup and maps high-level Agent state to local animation behavior.

## AIRI alignment

Yuizaki already covers the local desktop pet, chat, voice, memory, tools, MCP, visual traces, and Live2D/VRM embodiment portions of the AIRI direction. The implementation deliberately keeps animation local and perception request-scoped. AIRI-style integrations that remain open are external messaging connectors, browser/mobile clients, and game-specific adapters.

## Non-goals for the current release

- Always-on screen or camera capture.
- A cloud-hosted multi-user service.
- Shipping third-party model weights or character assets without their licenses.
- Claiming real hardware or provider quality from unit tests alone.

## Next product increments

1. More full-duplex voice providers and automatic VAD tuning.
2. Finer pet-to-Job state transitions and user-visible artifacts.
3. Discord/Telegram connectors with the same cancellable Job protocol.
4. Optional browser/PWA runtime.
5. Separate game-agent integrations.
