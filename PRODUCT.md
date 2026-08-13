# Product scope / 产品范围

## Promise / 产品承诺

Yuizaki is a local desktop companion that can talk, listen, remember, use tools, and express high-level Agent state through a Live2D or VRM avatar.

Yuizaki 是一款本地桌面陪伴应用，可以对话、聆听、记忆、使用工具，并通过 Live2D 或 VRM 化身表达高层 Agent 状态。

## Supported core loop / 支持的核心链路

```text
input -> session-scoped turn -> optional Job
      -> streamed text or audio -> persistence -> avatar feedback
```

The text lane is the reference path. Voice, vision, TTS, ASR, remote providers, and optional services activate only when their dependencies and settings are available.

文本链路是参考路径。语音、视觉、TTS、ASR、远程 provider 和可选服务仅在依赖与设置可用时启用。

## Capability matrix / 能力矩阵

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

| 能力 | 产品状态 | 边界 |
| --- | --- | --- |
| 文本聊天 | 支持 | 需要配置 LLM provider |
| 会话与历史 | 支持 | 存储在本地 SQLite |
| 工具与 MCP | 经审核后支持 | 已配置工具可能访问本地或远程系统 |
| 记忆 | 支持 | 默认使用 SQLite；语义检索为可选项 |
| Live2D/VRM 桌宠 | 搭配资源支持 | 用户提供的模型需单独授权 |
| 实时语音 | 可选 | 需要 provider、模型、麦克风、扬声器和权限 |
| 视觉 | 可选且按请求生效 | 无持续采集循环 |
| 心跳/调度器 | 支持 | 低频、有界且可检查的任务 |
| 云端多用户服务 | 不支持 | 使用本地回环安全模型 |

## Product boundaries / 产品边界

- No always-on screen or camera capture.
- No public server hardening or multi-tenant isolation claim.
- No bundled third-party model weights, voices, or avatar assets by default.
- No claim that unit tests replace real hardware/provider validation.
- No promise of Discord, Telegram, PWA/mobile, browser extension, or game-agent integrations in the current release.
- 当前版本不承诺提供 Discord、Telegram、PWA/移动端、浏览器扩展或游戏 Agent 集成。

## Design direction / 设计方向

Yuizaki follows a local-first, event-driven desktop model: the backend owns Agent orchestration and persistence; the renderer owns input, audio transport, and frame-level avatar behavior; jobs expose progress and terminal states; stale work is rejected by session/turn/request identities.

Yuizaki 采用本地优先、事件驱动的桌面模型：后端负责 Agent 编排与持久化；渲染器负责输入、音频传输和逐帧化身行为；任务暴露进度与终态；通过会话/轮次/请求身份拒绝过期工作。

## Next increments / 后续增量

1. More full-duplex voice providers and measured VAD tuning.
2. Clearer user-facing Job artifacts and pet state transitions.
3. External messaging connectors using the same cancellable Job protocol.
4. Optional browser/PWA runtime.
5. Separate game-agent integrations.
5. 独立的游戏 Agent 集成。
