# Design

## Source of truth

- Status: Active
- Last refreshed: 2026-08-04
- Primary product surfaces: desktop pet window, companion home, conversation, memory, settings and developer administration.
- Evidence reviewed: `README.md`, `docs/ARCHITECTURE.md`, `docs/TECH_STACK.md`, `electron/src/shared/navigation.ts`, `electron/src/renderer/app/AppShell.vue`, `electron/src/renderer/app/AppSidebar.vue`, `electron/src/renderer/app/WorkspaceDrawer.vue`, the 17 routed panels, current i18n resources, test suites, and screenshots under `.omx/artifacts/`.
- External evidence: AIRI, Open-LLM-VTuber, OpenAvatarChat, Amica, ZcChat, ElizaOS and SillyTavern; Relational Agents, HAI Guidelines, mixed-initiative interaction, interruptibility, Generative Agents, MemGPT, ToolEmu, AgentDojo, OWASP LLM Top 10 and NIST AI RMF.
- Evidence note: source files are valid UTF-8. Mojibake observed in earlier PowerShell output was a console decoding issue, not a repository defect.

## Brand

- Personality: quiet, capable, warm and observant without pretending to be human.
- Trust signals: explicit AI identity, visible local/cloud data boundaries, permission receipts, memory provenance, clear offline and degraded states.
- Avoid: manipulative attachment language, relationship scores used as pressure, oversized marketing UI, decorative cards, dense operations-console defaults, and a one-hue purple or beige palette.

## Product goals

- Goals: make the avatar the first-class daily surface; keep conversation interruptible; provide useful but bounded proactivity; make memory and tool actions understandable, correctable and reversible; retain local-first operation.
- Non-goals: replacing Electron/Python/Live2D, copying a third-party Agent framework wholesale, hiding advanced capabilities, or presenting the product as therapy or a human relationship.
- Success signals: three-item primary navigation; all proactive events can be stopped and disabled; all long-term memories expose provenance and deletion; risky tools show exact parameters and confirmation; pet state remains coherent across avatar, voice and Agent execution.

## Personas and jobs

- Primary personas: a daily desktop-companion user; a privacy-conscious local-model user; an advanced operator integrating models, MCP and automation.
- User jobs: talk or speak quickly; understand what the companion is doing; pause or interrupt it; review and correct memory; safely authorize capabilities; diagnose advanced failures without cluttering daily use.
- Key contexts of use: background work, focused full-screen activity, voice interaction, intermittent or offline providers, compact pet window and full control-panel window.

## Information architecture

- Primary navigation: Desktop Pet Home, Conversation, Memory.
- Core routes/screens: `companion`, `chat`, `memory` remain stable for compatibility.
- Content hierarchy: daily state and quick actions first; relationship and memory summaries second; models, MCP, diagnostics, traces and raw RAG controls behind an advanced/developer disclosure.
- Administration groups: Skills, Connections and Permissions; Tasks and Automation; System and Diagnostics; Developer Tools.
- Workspace drawer: quick scene, avatar, voice and proactive-behavior settings only; deeper configuration links to the canonical settings surface.

## Design principles

- Quiet by default: proactivity respects do-not-disturb, cooldown, frequency and interruptibility.
- Progressive disclosure: ordinary users see intent, status and recovery; engine parameters and raw records stay in advanced views.
- One authoritative state: avatar motion, expression, voice and Agent execution consume one companion state model.
- Explain consequential actions: show scope, exact parameters, risk, result and recovery without exposing hidden chain-of-thought.
- User-owned memory: every durable memory has source, time, scope, confidence, expiry and correction/deletion controls.
- Tradeoffs: compatibility and incremental delivery take priority over a large navigation/router rewrite; advanced routes remain deep-linkable while disappearing from the daily path.

## Visual language

- Color: retain repository tokens; use neutral surfaces plus restrained semantic accent, success, warning and danger colors. Do not make purple the dominant field color.
- Typography: compact interface hierarchy; hero-scale type only where the avatar/product identity is the primary viewport signal; letter spacing stays at `0`.
- Spacing/layout rhythm: 4/8 px rhythm, dense but scannable settings, stable control dimensions.
- Shape/radius/elevation: cards at 8 px radius or less unless an existing token requires otherwise; no nested cards or floating page-section cards.
- Motion: brief state transitions tied to meaning; honor `prefers-reduced-motion` by removing nonessential animation and smooth scrolling.
- Imagery/iconography: avatar/model is the primary visual asset; use the existing Element Plus icon library for familiar actions and tooltips for unfamiliar icons.

## Components

- Existing components to reuse: `AppShell`, `AppSidebar`, `WorkspaceDrawer`, shared async/error states, Element Plus controls, existing Live2D/VRM renderers and permission dialogs.
- New/changed components: companion runtime composable/store, daily companion status sections, advanced-disclosure sections for Memory and Pet, consolidated admin navigation groups.
- Variants and states: idle, listening, thinking, speaking, executing, waiting-for-permission, interrupted, offline, degraded and error.
- Token/component ownership: extend existing renderer theme variables and domain components; do not add a second design-system dependency.

## Accessibility

- Target standard: WCAG 2.2 AA for the control panel where practical.
- Keyboard/focus behavior: all daily actions, disclosure controls, permission decisions and interruption controls are keyboard reachable with visible focus.
- Contrast/readability: semantic state must not depend on color alone; compact text remains readable at 200% zoom.
- Screen-reader semantics: status updates use appropriate live regions; buttons have action labels; decorative avatar elements are hidden from assistive technology.
- Reduced motion and sensory considerations: implement global reduced-motion CSS and suppress idle loops, parallax and nonessential avatar transitions when requested; voice and proactive notifications remain independently mutable.

## Responsive behavior

- Supported breakpoints/devices: Windows 10/11 and x86_64 Linux control windows; compact desktop-pet layouts and full management layouts.
- Layout adaptations: primary navigation remains usable without labels at narrow widths; panels use stable min/max tracks and avoid horizontal overflow; advanced tables gain compact/list fallbacks.
- Touch/hover differences: hover is enhancement only; all commands have focus/click equivalents, touch-capable targets are at least 44 by 44 pixels, and tooltips do not carry required information.

## Interaction states

- Loading: preserve layout with local progress near the affected action.
- Empty: explain the missing user data or capability and offer the single next useful action.
- Error: state what failed, whether data/action was committed, and offer retry or diagnostics.
- Success: show a concise receipt for settings, permissions, memory edits and tool actions.
- Disabled: explain the prerequisite without silently failing.
- Offline/slow network: keep local pet controls and local data available; clearly distinguish unavailable cloud providers from a failed local runtime.

## Content voice

- Tone: concise, calm and companionable; never guilt-inducing or possessive.
- Terminology: use Desktop Pet, Conversation and Memory for daily areas; use Skills, Permissions, Tasks and Diagnostics for advanced areas.
- Microcopy rules: name the action and consequence; disclose AI identity and uncertainty; never claim emotions, surveillance or real-world actions that did not occur.

## Implementation constraints

- Framework/styling system: Electron, Vue 3, TypeScript, Pinia/Vue Router, Element Plus and existing scoped/global CSS.
- Design-token constraints: extend existing `--yui-*` tokens; keep source UTF-8 and existing localization architecture.
- Performance constraints: no new startup-blocking work; background polling must be lifecycle-owned, deduplicated and paused when unavailable; avoid eager loading of advanced panels.
- Compatibility constraints: preserve stable route ids and public IPC/HTTP contracts; support the repository's documented Node.js and Python version range; add no dependency without explicit approval.
- Test/screenshot expectations: targeted Vitest/pytest first, then typecheck/lint/build; add E2E or component coverage for navigation, permissions, memory, interruption, offline/error and reduced-motion behavior.

## Open questions

- [ ] Validate proactive-event frequency presets with real users; owner: product; impact: default interruption budget.
- [ ] Define a licensed default avatar/voice distribution package; owner: release; impact: first-run quality.
- [ ] Measure compact-window usability and 200% zoom on Windows/Linux; owner: QA; impact: responsive thresholds.
- [ ] Decide whether relationship summaries remain user-visible after usability testing; owner: product/safety; impact: Companion home content.
