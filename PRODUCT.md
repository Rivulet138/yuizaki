# Product

## Register

product

## Users

Yuizaki serves people who keep an AI companion open throughout the day, local-AI users who want control over providers and stored data, and advanced users who occasionally inspect Agent, voice, memory, or desktop integration failures. The primary workflow is a sequence of short, low-attention conversations, with deeper configuration and diagnostics used only when something needs attention.

## Product Purpose

Yuizaki is a local-first AI desktop companion Agent that combines text and voice conversation, Live2D or VRM embodiment, long-term memory, request-scoped perception, tools, and desktop actions. Success means that the companion feels available without demanding attention, completed actions have observable outcomes, failures lead to a clear next step, and users can inspect or correct the memories and permissions that shape future behavior.

## Brand Personality

Calm, observant, trustworthy. Copy is concise and specific. The companion can be warm, but operational surfaces describe observable state and never use personality to hide uncertainty or failure.

## Anti-references

- Card-heavy dashboards that repeat the same health state in several summaries.
- Assistants that interrupt frequently, steal focus, or use relationship pressure to drive engagement.
- Opaque autonomous agents that claim completion without showing the result or recovery path.
- Browser experiences that imply Electron-only window, device, or process capabilities are available.
- Debug consoles exposed as the default companion experience.

## Design Principles

1. Companion first: keep chat, voice, avatar, and immediate feedback visually primary; diagnostics stay secondary.
2. Exceptions over inventories: show the highest-priority problem and next action before complete status matrices.
3. Progressive disclosure: common actions remain visible; traces, raw metadata, and provider details expand on demand.
4. Comfortable autonomy: proactive behavior is low-frequency, non-blocking, explainable, and easy to postpone or reduce.
5. Honest recovery: distinguish checking, ready, degraded, failed, and unknown outcomes; every recoverable failure has a direct next step.

## Accessibility & Inclusion

Target WCAG 2.2 AA within the Electron stack. All controls are keyboard reachable with visible focus, body and placeholder text meet contrast requirements, state is not communicated by color alone, compact layouts preserve understandable navigation without hover, and animation respects reduced-motion preferences.
