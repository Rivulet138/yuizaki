# Yuizaki design principles

## Product shape

Yuizaki is a desktop companion first and a control panel second. The pet should remain visible, calm, and interactive while chat, Agent work, and settings stay available without competing for attention.

## Interaction principles

- Keep the chat input usable while a response or background Job is running.
- Use explicit states: listening, thinking, executing, speaking, success, error, interrupted, and sleep.
- Show what the Agent is doing and the resulting artifact; collapse implementation diagnostics.
- Keep model, provider, MCP, TTS, and pet controls in settings rather than repeating them in every message.
- Preserve per-session drafts, generation identity, unread completion, and cancellation semantics.
- Support reduced motion and avoid animation work when the window is hidden.

## Visual principles

- Transparent pet surface; no mandatory glassmorphism or opaque decorative shell.
- High contrast text and controls with restrained spacing and compact repeated items.
- Pet motion is expressive but bounded: local state machines smooth gaze, expression, motion, idle breathing, and lip-sync.
- Avoid always-on status prose, duplicate badges, and panels that explain their own controls.
- Error, progress, and completion should be visible at the point of action.

## Performance principles

- Audio work stays off the UI thread where possible.
- Pointer events are coalesced before reaching the renderer.
- Active and idle FPS tiers, DPR caps, hidden-window pause, and TTL-based lip-sync prevent runaway work.
- Vision captures one frame only when an Agent request needs it.
- Job progress is coalesced; terminal events are never dropped.
