# Design principles

## Product shape

Yuizaki is a desktop companion first and a control panel second. The pet should remain visible and calm while chat, Agent work, and settings stay usable without competing for attention.

## Interaction

- Keep chat input usable while a response or background Job runs.
- Represent explicit states: listening, thinking, executing, speaking, success, error, interrupted, and sleep.
- Show the current action and resulting artifact at the point of action; keep implementation diagnostics collapsible.
- Keep provider, MCP, TTS, pet, and model controls in settings.
- Preserve session drafts, generation identity, unread completion, and cancellation semantics.
- Respect reduced motion and pause hidden-window rendering work.

## Embodiment

The Agent emits intent-level commands such as `listen`, `think`, `speak`, gaze, expression, motion, and lip-sync. Live2D and VRM adapters own smoothing, TTL, fade, looping, and release timing. The LLM never emits frame-level animation instructions.

## Privacy and perception

Vision is an explicit one-shot capability. A request moves through `requested -> captured -> analyzed -> completed` or `discarded`; frames are released after the request and are not persisted by default.

## Performance

- Keep audio work off the UI thread where possible.
- Coalesce pointer and progress events, but never drop terminal Job events.
- Cap device-pixel ratio and active/idle frame rates.
- Pause hidden-window rendering.
- Use lazy model startup on constrained hardware.

## Failure behavior

Cancellation, interruption, stale results, provider errors, and missing assets are visible states. A slow tool or TTS segment must not freeze chat input. A missing optional provider should degrade the feature rather than silently fabricate a result.
