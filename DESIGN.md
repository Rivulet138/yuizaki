# Design / 设计

## Source of truth / 信息源

- Status: Active
- Last refreshed: 2026-08-17
- Primary product surfaces: desktop companion, chat, long-term memory, Agent jobs, settings, Live2D/VRM pet
- Code evidence reviewed: `electron/src/renderer/app`, `electron/src/renderer/domains`, `electron/src/renderer/runtime`, `electron/src/renderer/audio`, `electron/src/main`, `python/modules/agent`, `python/modules/memory`, and `python/routes`
- Documentation boundary: README and design documents describe intent; implementation claims must be rechecked against source paths before release
- External material may inform design decisions, but only current code, tests, and target-device evidence establish a local capability.

## Code evidence map / 代码证据映射

- Product shell and navigation: `electron/src/renderer/App.vue`, `app/AppShell.vue`, `navigation/modules.ts`, `stores/workspaceStore.ts`.
- Chat and voice: `domains/chat`, `stores/chatStore.ts`, `app/composables/useVoiceConversationBridge.ts`, `audio`, and `app/runtime/realtimeVoiceEventBridge.ts`.
- Companion/Avatar: `pet-embodiment-coordinator.ts`, `pet-sentence-emotion-scheduler.ts`, `runtime/live2d-runtime-adapter.ts`, `runtime/vrm-runtime-adapter.ts`, `utils/petControl.ts`.
- Memory: `domains/memory`, `api/clients/memory-client.ts`, `python/modules/memory/routes.py`, `python/modules/memory/pipeline.py`, `python/modules/memory/sqlite_store.py`.
- Agent execution: `python/modules/agent/runtime.py`, `pipeline.py`, `planner.py`, `step_executor.py`, `tool_executor.py`, `tool_loop.py`.
- Trust boundaries: `python/modules/agent/perception.py`, `desktop_actions.py`, `policy_engine.py`, `permission_receipt.py`, `plugin_trust.py`, `electron/src/main/*token-store.ts`, and `plugin-sandbox.ts`.

## Brand / 品牌

- Personality: calm, observant, local-first, companionable, technically trustworthy
- Trust signals: visible scope, provenance, confidence, last update, retrieval reason, reversible correction, explicit destructive confirmation
- Avoid: decorative dashboards, anthropomorphic claims that imply certainty, hidden capture, autonomous profile rewriting without provenance, opaque graph visualizations

## Product goals / 产品目标

- Goals:
  - Keep a useful and inspectable long-term relationship with the user across sessions.
  - Separate raw events, derived memories, core profile, and rebuildable search indexes.
  - Make every recalled memory traceable to its source and current validity.
  - Let users correct, protect, forget, and permanently delete memory with predictable effects.
  - Keep SQLite as the local authority and semantic search as an optional projection.
- Non-goals:
  - A cloud multi-user memory service.
  - An always-on screen or camera history.
  - A graph database or autonomous "memory OS" as a baseline dependency.
  - Treating summaries, reflections, embeddings, or model-generated profile text as canonical evidence.
- Success signals:
  - Cross-workspace and cross-session isolation tests pass.
  - A corrected fact supersedes history without destroying provenance.
  - Forgotten or expired memory cannot be recalled through any query path.
  - Index rebuilds reproduce the recallable projection from SQLite.
  - Users can understand why an item exists and why it was recalled from the panel.

## Personas and jobs / 用户与任务

- Primary personas: a daily desktop-companion user; a privacy-conscious local AI user; an advanced user diagnosing retrieval quality
- User jobs:
  - Tell the companion a stable fact, preference, boundary, or meaningful event.
  - Review what the companion currently believes and correct mistakes.
  - Find the source and history of a memory.
  - Test recall for a question and inspect ranking/filter decisions.
  - Forget sensitive or obsolete information and verify that it is no longer recallable.
  - Maintain storage without accidentally deleting protected profile or relationship memories.
- Key contexts of use: repeated short desktop interactions, cross-session continuity, low-attention background companionship, occasional advanced diagnostics

## Information architecture / 信息架构

- Primary navigation: Chat and Memory remain primary user surfaces; backend/index controls remain in Settings; persona behavior debugging remains admin-only.
- Memory screen views:
  - Overview: health, recallable count, review queue, layer distribution, latest activity.
  - Library: searchable memory list with scope/layer/state filters and a persistent inspector.
  - Review: low-confidence, contradictory, duplicate, stale, or inferred items requiring confirmation.
  - Recall lab: advanced query, selected layers, results, score components, filters, latency, and selected IDs.
- Content hierarchy: user meaning and current belief first; provenance/history second; backend/index diagnostics third.
- Core memory model:
  - Raw event: immutable source observation with `occurred_at`, `ingested_at`, source IDs, and scope.
  - Derived memory: typed fact/preference/event/reflection with confidence, importance, validity, and source IDs.
  - Core profile: small protected profile/relationship set that is always explicit and manually reviewable.
  - Search projection: rebuildable embedding/lexical index, never the authority.

## Design principles / 设计原则

1. Evidence before personality: friendly language must never hide uncertainty, provenance, or destructive impact.
2. Current belief with history: show the active value directly while retaining corrections, superseded versions, and audit history.
3. Progressive disclosure: common review and correction stay visible; raw metadata, retrieval traces, and index maintenance remain advanced.
4. Local-first degradation: missing embedding or Qdrant falls back to SQLite authority and clearly reports reduced search quality.
5. Companion first, control panel second: the pet remains calm and visible; memory tools are dense, predictable, and task-focused.
- Tradeoffs: consistency and user trust take priority over autonomous write volume, graph novelty, and maximum recall aggressiveness.

## Research basis / 研究依据

- Human-centered proactive agents: CUI 2024 recommends that proactive timing and content follow user goals and context, with persistent controls over frequency and categories. Yuizaki therefore keeps proactive behavior low-attention and user-adjustable instead of using blocking prompts. <https://doi.org/10.1145/3626772.3657843>
- Explainable proactive intent: CHI 2025 supports short user-facing reasons for proactive interventions without exposing chain-of-thought. Yuizaki surfaces a concise reason and next action rather than raw internal reasoning. <https://doi.org/10.1145/3706598.3713760>
- Companion well-being: AI & Society 2025 identifies both relationship benefits and dependency risks in companion AI. Yuizaki prioritizes pause, quiet hours, reduced frequency, and non-coercive copy over engagement pressure. <https://doi.org/10.1007/s00146-025-02318-6>
- Long-term memory: CAIM at IUI 2026 separates persistent cognitive memory from transient interaction context. Yuizaki keeps stable facts and preferences distinct from session context and does not promote one-off emotional statements directly into the core profile. <https://doi.org/10.1145/3742413.3789222>
- Memory evaluation: the ACL 2024 long-term memory benchmark covers temporal change, contradiction, and multi-session retrieval. Yuizaki preserves correction history and gives the user's current correction precedence in recall. <https://doi.org/10.48550/arXiv.2402.17753>
- Operational interaction: Microsoft Human-AI Interaction Guidelines, OpenAI Memory controls, and Anthropic Computer Use guidance support visible system state, low-cost correction, scoped memory controls, and observable tool execution. <https://www.microsoft.com/en-us/research/publication/guidelines-for-human-ai-interaction/> <https://help.openai.com/en/articles/8590148-memory-faq> <https://docs.anthropic.com/en/docs/build-with-claude/computer-use>

## Visual language / 视觉语言

- Color: reuse existing Yuizaki neutral surfaces and one accent; reserve green/amber/red for verified states, review, and destructive risk.
- Typography: use the existing UI family and a fixed compact scale; monospace is limited to IDs, traces, and raw metadata.
- Spacing/layout rhythm: 8px base rhythm; dense toolbars and lists; wide inspector layout collapses structurally on narrow windows.
- Shape/radius/elevation: reuse repository panel/card tokens; no nested decorative cards or glass effects.
- Motion: 150-250ms state transitions only; no page choreography; fully respect reduced motion.
- Imagery/iconography: use the installed Element Plus icon set; icons support commands and state, not decoration.

## Components / 组件

- Existing components to reuse: `PanelShell`, `AsyncState`, Element Plus buttons/selects/tags/forms/dialogs, existing Yuizaki tokens.
- New/changed components:
  - `MemoryOverview`
  - `MemoryLibrary`
  - `MemoryInspector`
  - `MemoryReviewQueue`
  - `MemoryRecallLab`
  - `MemoryMaintenancePanel`
- Variants and states: loading skeleton, empty guidance, stale preview, unavailable index, partial recall, dirty draft, conflict, protected, forgotten, expired, superseded.
- Token/component ownership: memory-specific layout lives under `domains/memory`; shared primitives remain generic and are not forked for this feature.

## Accessibility / 无障碍

- Target standard: WCAG 2.2 AA where the desktop stack permits.
- Keyboard/focus behavior: all list selections, tabs, filters, dialogs, and destructive actions are keyboard reachable with visible focus.
- Contrast/readability: body and placeholder text meet 4.5:1; state is never communicated by color alone.
- Screen-reader semantics: real buttons for actions, labelled scopes and filters, status regions for async results, descriptive destructive copy.
- Reduced motion and sensory considerations: no decorative motion; avatar rendering and panel transitions respect reduced-motion and hidden-window rules.

## Responsive behavior / 响应式

- Supported breakpoints/devices: Electron desktop from compact 760px windows through wide desktop; browser dev mode follows the same layout.
- Layout adaptations: overview metrics wrap; library inspector moves below the list; toolbars stack; tables become list rows instead of horizontal overflow.
- Touch/hover differences: actions remain visible without hover; hit targets remain at least 32px in dense desktop mode.

## Interaction states / 交互状态

- Loading: preserve layout with skeletons or bounded loading states.
- Empty: explain the next meaningful action, such as adding a stable preference or clearing filters.
- Error: keep prior successful data visible when possible and offer scoped retry.
- Success: update the affected row and announce the operation; do not rely on toast alone.
- Disabled: explain unavailable actions through adjacent status or tooltip.
- Offline/slow network: SQLite operations remain available; optional semantic services visibly degrade.
- Destructive: soft forget is the default removal from recall; permanent delete requires impact preview and explicit confirmation.

## Content voice / 文案

- Tone: concise, calm, specific, and non-judgmental.
- Terminology: use “记忆”, “来源”, “当前有效”, “待确认”, “停止召回”, and “永久删除”; avoid implying the model “knows” uncertain facts.
- Microcopy rules: command labels use verb + object; state labels describe observable state; advanced terms include a short plain-language explanation.

## Implementation constraints / 实现约束

- Framework/styling system: Vue 3, Element Plus, scoped CSS, existing Yuizaki CSS variables; Python FastAPI and SQLite authority.
- Design-token constraints: extend existing tokens only when a semantic state cannot be expressed; do not create a second design system.
- Memory invariants:
  - Canonical records keep a schema version and immutable origin provenance.
  - Search indexes and summaries are projections and can be rebuilt.
  - Retrieval applies recallability, scope, validity, and sensitivity filters at the final boundary.
  - Corrections append history; they do not silently overwrite origin evidence.
  - Permanent deletion clears chat references and all configured index projections.
- Performance constraints: list rendering stays bounded; index rebuild is explicit; embedding models load lazily; terminal Job events are never dropped.
- Compatibility constraints: preserve existing `/memory` contracts while introducing a single canonical frontend client surface; Qdrant remains optional.
- Verification expectations: typecheck/build plus desktop and compact viewport checks with no overlap or blank states.

## Open questions / 待确认

- [ ] Decide whether automatic candidate extraction should default to review-only for sensitive categories / product owner / privacy and trust
- [ ] Add an optional temporal graph projection only after LongMemEval-style local tests show a measurable multi-hop benefit / engineering / dependency and migration cost
- [ ] Define export and backup deletion semantics before claiming full regulatory erasure across user-managed backups / product and legal / external data lifecycle
