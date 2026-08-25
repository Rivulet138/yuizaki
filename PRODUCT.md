# Product scope / 产品范围

## Promise / 产品承诺

Yuizaki is a local, single-user AI desktop pet Agent that can talk, listen, remember, use tools, and express high-level Agent state through a Live2D or VRM avatar.

Yuizaki 是一款面向本机单用户的 AI 桌宠 Agent，可以对话、聆听、记忆、使用工具，并通过 Live2D 或 VRM 化身表达高层 Agent 状态。

## Supported core loop / 支持的核心链路

```text
input -> session-scoped turn -> optional Job
      -> streamed text or audio -> persistence -> avatar feedback
```

The text lane is the reference path. Voice, vision, TTS, ASR, remote providers, and optional services activate only when their dependencies and settings are available.

文本链路是参考路径。语音、视觉、TTS、ASR、远程 provider 和可选服务仅在依赖与设置可用时启用。

The code-level path is:

```text
renderer input
  -> chat client / Socket.IO event
  -> TurnService + AgentPipeline
  -> Planner / StepExecutor / ToolExecutor
  -> streamed LLM, tool, Job, and companion events
  -> turn store / memory write projection
  -> renderer chat, audio, trace, and avatar state
```

Evidence: `electron/src/renderer/api/clients/chat-client.ts`,
`python/modules/agent/turn_service.py`, `python/modules/agent/pipeline.py`,
`python/modules/agent/step_executor.py`, `python/modules/agent/tool_executor.py`,
`python/modules/agent/turn_store.py`, and
`electron/src/renderer/app/runtime/companionJobProjection.ts`.

## Capability matrix / 能力矩阵

| Capability | Product status | Boundary |
| --- | --- | --- |
| Text chat | Implemented | `python/routes/ai_api.py:212-370`; requires a configured LLM client |
| Sessions and history | Implemented | `python/routes/database_api.py:69-202`, `python/routes/workspace_api.py:50-173`; scope is resolved by workspace/session code |
| Tools and MCP | Implemented with policy | `python/modules/agent/runtime.py:86-104`, `tool_registry.py`, `mcp_manager.py`; configured tools may access local or remote systems |
| Memory | Implemented | `python/modules/memory/sqlite_store.py`, `memory/pipeline.py`; vector/embedding projection is optional |
| Live2D/VRM pet | Implemented with assets | `electron/src/renderer/runtime/live2d-runtime-adapter.ts`, `vrm-runtime-adapter.ts`, `pet-model-runtime.ts` |
| Realtime voice | Implemented conditionally | `useVoiceConversationBridge.ts:256-375`, `audio/realtime-voice.ts`; requires provider/model/microphone/speaker/permission |
| Vision | Implemented as request-scoped perception | `python/modules/agent/perception.py:35-177`, `electron/src/main/authorized-perception-bridge.ts`; no continuous capture loop |
| Heartbeat/scheduler | Implemented | `python/modules/agent/scheduler.py`, `python/routes/system_api.py:400-450`; jobs are bounded and cancellable |
| Proactive companion controls | Implemented as a policy/control surface | `useProactiveControls.ts`, `proactive-client.ts`, `python/routes/system_api.py:285-351`; outcome quality is not guaranteed |
| Native desktop actions | Windows and Linux/X11 implementations | `python/modules/agent/desktop_actions.py:187-202`, `:358-542`; pure Wayland and unsupported platforms fail closed |
| Onboarding readiness | Implemented | `onboarding-readiness-coordinator.ts`, `python/routes/system_api.py:217-260`; reports readiness, does not certify hardware |
| Cloud multi-user service | Not implemented | No tenant/auth boundary for public deployment; the desktop control plane trusts loopback by default |

| 能力 | 产品状态 | 边界 |
| --- | --- | --- |
| 文本聊天 | 支持 | 需要配置 LLM provider |
| 会话与历史 | 支持 | 存储在本地 SQLite |
| 工具与 MCP | 选择启用后可用 | 启用即授权其声明工具，不逐次确认；关闭服务或插件即撤销选择 |
| 记忆 | 支持 | 默认使用 SQLite；语义检索为可选项 |
| Live2D/VRM 桌宠 | 搭配资源支持 | 用户提供的模型需单独授权 |
| 实时语音 | 可选 | 需要 provider、模型、麦克风、扬声器和权限 |
| 视觉 | 可选且按请求生效 | 无持续采集循环 |
| 心跳/调度器 | 支持 | 低频、有界且可检查的任务 |
| 云端多用户服务 | 不支持 | 桌面控制面默认信任本机回环访问，不提供公网或多租户安全承诺 |

## Product boundaries / 产品边界

- No always-on screen or camera capture.
- No public server hardening or multi-tenant isolation claim.
- No bundled third-party model weights, voices, or avatar assets by default.
- No claim that unit tests replace real hardware/provider validation.
- No promise of Discord, Telegram, PWA/mobile, browser extension, or game-agent integrations in the current release.
- No promise that a passing contract test proves a target microphone, speaker, GPU, provider, model, or avatar asset works acceptably.
- No promise that a `completed` tool result alone proves the user's real-world goal; postcondition verification remains tool-specific.
- 当前版本不承诺提供 Discord、Telegram、PWA/移动端、浏览器扩展或游戏 Agent 集成。

## Design direction / 设计方向

Yuizaki follows a local-first, event-driven desktop model: the backend owns Agent orchestration and persistence; the renderer owns input, audio transport, and frame-level avatar behavior; jobs expose progress and terminal states; stale work is rejected by session/turn/request identities.

Yuizaki 采用本地优先、事件驱动的桌面模型：后端负责 Agent 编排与持久化；渲染器负责输入、音频传输和逐帧化身行为；任务暴露进度与终态；通过会话/轮次/请求身份拒绝过期工作。

The implementation enforces several of these boundaries directly:

- `python/modules/agent/tool_loop.py` rejects cancelled or invalidated generations and bounds iterations, retries, output tokens, and tool calls.
- `python/modules/agent/perception.py` consumes one-time consent tied to request identity and TTL.
- `python/modules/agent/desktop_actions.py` fences native actions after emergency stop, feature revision, or authorization revocation.
- `python/modules/agent/turn_store.py` and `turn_outbox.py` provide idempotent turn persistence and event projection primitives.
- `electron/src/renderer/app/composables/useCompanionRuntimeBridge.ts` and `companionRuntime.ts` convert backend intent/events into renderer presentation state.

## Next increments / 后续增量

1. More full-duplex voice providers and measured VAD tuning.
2. Clearer user-facing Job artifacts and pet state transitions.
3. External messaging connectors using the same cancellable Job protocol.
4. Optional browser/PWA runtime.
5. Separate game-agent integrations.
6. macOS native-action adapter and platform-specific permission/postcondition tests; Linux remains explicitly X11-only until a Wayland contract exists.
7. Evidence-backed end-to-end quality metrics for voice latency, tool success, memory recall, proactive acceptance, and Avatar stability.
8. A signed role/voice/motion asset format and optional creator distribution layer.
