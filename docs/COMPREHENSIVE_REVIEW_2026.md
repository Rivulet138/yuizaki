# Yuizaki 产品与技术专业评估（证据版）

更新时间：2026-09-06。范围是当前工作区的代码、测试、配置、文档和本轮可执行的本地验证。本文不把 README、路线图或预印本结论当作成熟度证明。证据标签：`[代码事实]`、`[测试证据]`、`[文档意图]`、`[外部基准]`、`[推断]`、`[未知]`。

说明：原始评估请求要求只读分析；本文件描述的是当前工作区（包含此前已实施的改进），不是未修改基线的历史快照。实施记录与产品能力判断已用证据标签区分。

## 1. 执行摘要与总体结论

Yuizaki 已形成一个本地优先的桌面伴侣雏形：文字流式对话、语音管线、Live2D/VRM、按请求视觉、工具/MCP、长期记忆、连接器和调度器均有代码入口与部分测试。[代码事实] 但跨进程 Agent 步骤恢复尚未接入，真实 Windows/Linux 设备、音频/GPU、外部账号、24 小时稳定性和 GUI 沙箱尚未由仓库证据证明。[未知] 当前阶段是**可用 Alpha，接近 Beta 的工程化阶段**，不是生产级。

**结论：适合有条件开源。** 开源前必须完成安装/首次运行与平台资格证据、密钥和 host-token 契约、插件/MCP/桌面动作信任边界、崩溃/取消/unknown_effect 回放、模型与素材许可清单、跨平台发布和故障排查。P1/P2 可在开源后迭代，但必须公开声明实验性连接器、macOS 缺失能力、模型需单独下载和未经真实设备验证的性能目标。[代码事实][未知]

### 总体评分

| 维度 | 分数 | 理由 |
|---|---:|---|
| 产品熟练度 | 6/10 | 主要场景入口齐全，状态与失败语义已有 `known_success/unknown_effect`；真实设备和陪伴闭环证据不足。[代码事实][测试证据] |
| 功能完善度 | 6/10 | 对话、记忆、工具、桌宠已有实现；跨进程步骤恢复、真实公网连接器、GUI 沙箱仍缺。[代码事实][未知] |
| 技术栈合理性 | 7/10 | Electron/Vue + Python/FastAPI + SQLite/Qdrant 与本地优先目标匹配，双运行时和 Socket 契约带来成本。[推断] |
| 架构与可改进性 | 6/10 | Runtime/Repository/Policy/Composition 边界正在形成，`app.py`/`socket_server.py` 仍偏重。[代码事实] |
| Agent 全链路完整性 | 5/10 | 感知到反馈可运行，验证、恢复、重启后恢复和主动反馈闭环未完整。[代码事实][未知] |
| 开源准备度 | 5/10 | MIT、CI、依赖和安全文档存在；多运行时门槛、资源许可、token 契约和平台资格仍阻断。[代码事实][未知] |
| 商业化潜力 | 6/10 | 隐私、桌宠形态和扩展能力有差异化；成本、留存、平台合规和模型分发无实测。[推断][未知] |

## 2. 产品熟练度评估

文字对话由 `python/socket_handlers/llm.py:build_llm_request_handler`、`python/modules/agent/turn_service.py` 和 `electron/src/renderer/domains/chat` 串联，事件模型位于 `python/socket_events.py`。[代码事实] 取消、分支、恢复和流式终态已有测试，但没有目标机端到端延迟或长时断线报告。[测试证据][未知]

语音包括 AudioWorklet/ScriptProcessor、VAD/ASR/TTS 事件和打断路径，主要在 `electron/src/renderer/audio/audio-capture.ts`、`python/socket_handlers/audio.py`。[代码事实] 设备枚举与断连有单元测试；真实声卡、首包 p95、barge-in 停止 p95 尚未验证。[测试证据][未知]

桌宠状态通过 `electron/src/renderer/pet-renderer.ts`、`pet-renderer-runtime.ts` 和 `python/socket_events.py:PetStateData` 投影。动作/表情/口型接口存在，但 Agent 真实终态与 Avatar 终态一致缺少跨进程回放证据。[代码事实][未知]

主动行为由 scheduler/heartbeat 与 `ProactiveSettingsSection` 暴露，已有安静时段和预算设计；拒绝后再次触达率、解释可理解性和长期打扰率没有数据。[文档意图][未知]

用户粘性可能来自长期记忆、关系连续性、个性化和主动任务，而不是通知频率；依赖诱导、人格操控和敏感记忆泄漏尚未完成红队。[推断][未知] Provider、MCP、插件、连接器、Avatar、语音和工具均存在 registry/route/manifest 入口，但第三方签名、撤销、沙箱和开发者 SDK 不完整。[代码事实]

### 对标表

| 对标对象 | 目标用户/核心能力 | Yuizaki 优势 | 明显短板 | 可借鉴设计 | 证据来源 |
|---|---|---|---|---|---|
| AIRI | 桌宠/VTuber；Live2D/VRM、多模态 | 本地权限、记忆、终态治理更明确 | 真实设备和生态规模未知 | 角色与实时交互组合 | GitHub `moeru-ai/airi` |
| Open-LLM-VTuber | 本地模型桌宠；ASR/TTS、Live2D/VRM | 记忆、工具、审计面更广 | 下载和安装更复杂 | 本地模型降级 | GitHub `Open-LLM-VTuber/Open-LLM-VTuber` |
| Open WebUI | 自托管 AI；Provider、工具、权限 | 桌宠/语音/桌面动作差异化 | 桌面运行时复杂 | 设置和扩展控制面 | GitHub `open-webui/open-webui` |
| Jan | 本地 AI 桌面；本地模型、localhost API | Avatar、计划任务、记忆更丰富 | 双运行时发布门槛 | readiness 与恢复动作 | GitHub `janhq/jan` |
| SillyTavern / Replika | 角色/伴侣；Persona 或商业陪伴 | 权限、删除、审计边界更强 | 关系安全和留存无数据 | persona 与聊天分离、关系红队 | GitHub `SillyTavern/SillyTavern`；产品站点 |

商业化只能作为假设：本地隐私、专业工作流、角色/声音/插件、直播和团队治理可能形成付费点；模型下载成本、支持成本、分发许可、平台审核、留存和每小时推理成本必须用试用与 staging 数据验证。[推断][未知]

## 3. 功能实现清单

| 功能 | 用户价值 | 主要路径/事件 | 测试证据 | 状态 |
|---|---|---|---|---|
| 流式文字对话 | 低等待聊天 | `socket_handlers/llm.py`、`turn_service.py`、`LLMEvents` | Python 回归、Socket 定向测试 | 完成但跨平台未验证 |
| 会话/历史/分支/取消 | 保留上下文并可控停止 | `turn_store.py`、`turn_service.py` | turn store/recovery tests | 部分完成 |
| 语音输入/VAD/ASR/TTS/打断 | 免手交互 | `audio-capture.ts`、`socket_handlers/audio.py` | audio health tests | 部分完成，设备未知 |
| Live2D/VRM 状态 | 具身反馈 | `pet-renderer.ts`、`PetStateData` | renderer tests/build | 部分完成 |
| 请求级屏幕感知/OCR | 读取当前环境 | `authorized-perception-bridge.ts`、`socket_handlers/perception.py` | perception/route tests | 部分完成，真实 GUI 未验证 |
| 工具/规划/验证 | 执行动作 | `planner.py`、`step_executor.py`、`tool_executor.py` | verification/step tests | 部分完成 |
| `unknown_effect` 终态 | 防止错误重试副作用 | `socket_handlers/tool.py`、`runtime.py` | scheduler/connector/stream tests | 合同完成，外部效果未知 |
| MCP/插件 | 扩展工具 | `mcp_manager.py`、vault、plugin routes | vault、node-mcp 7 tests | 部分完成，第三方沙箱缺 |
| 长期记忆 | 跨会话连续性 | `python/modules/memory` | memory operation/recall tests | 部分完成 |
| 调度/心跳 | 定时工作和陪伴 | `scheduler.py`、proactive UI | scheduler outcome tests | 部分完成 |
| 连接器 | 外部消息入口 | `connector_api.py`、`message_connectors.py` | connector e2e/probe/recovery | 实验性，公网未知 |
| Provider/离线降级 | 适配多模型 | provider settings/runtime | readiness/config tests | 部分完成 |
| 运行治理/诊断 | 可观察和排障 | `agent_trace_store.py`、metrics | trace/metrics tests | 合同完成，长期容量未知 |
| 安装/模型下载/发布 | 可重复安装 | launcher、`resources.lock.json` | Go/package checks | 部分完成，平台资格未知 |

## 4. AI 桌宠 Agent 功能矩阵

| 能力 | 现状 | 风险 | 优先级 | 证据 |
|---|---|---|---|---|
| 文字/流式输出 | 已有实现 | schema registry、Provider 行为和目标机延迟仍未知 | P0 | `socket_handlers/llm.py`、`socket_events.py` |
| 多会话/恢复/取消 | 部分实现 | 重启后步骤上下文缺失 | P0 | `turn_store.py`、`step_executor.py` |
| 语音/VAD/打断 | 部分实现 | 设备、延迟、回声未知 | P0 | `audio-capture.ts` |
| 情感/动作/口型/注视 | 部分实现 | 真实终态映射未证明 | P1 | pet renderer/events |
| Live2D/VRM/资源 | 部分实现 | 资源许可与性能未知 | P0 | pet domains、notices |
| 屏幕/OCR/视觉 | 部分实现 | 权限、截图泄漏、GUI 成功率 | P0 | authorized perception |
| 桌面窗口动作 | 部分实现 | 平台能力有限，真实动作资格未知 | P0 | `backend_api_auth.py`、`host_control.py` |
| 规划/执行/验证/恢复 | 部分实现 | durable step recovery 未接线 | P0 | `step_executor.py`、`recovery_store.py` |
| MCP/插件/技能 | 部分实现 | 第三方供应链和沙箱 | P0 | `mcp_manager.py`、vault |
| 记忆纠正/删除/索引 | 部分实现 | 删除传播和召回回归未知 | P0 | memory modules |
| 画像/关系 | 部分实现 | 关系操控与漂移 | P1 | runtime projections |
| 主动行为/频率 | 部分实现 | 拒绝后触达未知 | P1 | scheduler/proactive UI |
| 连接器 | 实验性 | 重复投递和账号风控 | P0 | connector routes |
| 多 Provider/离线 | 部分实现 | 行为和成本差异 | P1 | provider settings |
| 工作区/权限/审计 | 部分实现 | loopback 信任模型 | P0 | policy/HTTP routes |
| 办公/学习/直播/游戏 | 入口或规划 | 场景成功率未验证 | P2 | roadmap |
| 设置/诊断/导出 | 部分实现 | 长期可读性未知 | P1 | system panels |
| Windows/Linux/macOS | Windows/Linux 目标；macOS 缺失 | compositor/音频/GUI 差异 | P0 | README/architecture |
| 安全/隐私/密钥 | 部分实现 | host-token 本地合同已收紧，真实平台红队未知 | P0 | SECURITY/vault |
| 安装/升级/卸载 | 部分实现 | 大模型许可/下载失败 | P0 | launcher/scripts |

## 5. 技术栈选型评审

| 维度 | 分数 | 依据与风险 |
|---|---:|---|
| 性能/资源 | 6 | Three/Pixi 适合桌宠但静态 chunk 较大；主入口约 431.86 kB，320 kB 目标未达成。[测试证据] |
| 实时交互 | 7 | Socket.IO、Web Audio、SSE 覆盖流式场景；音频设备/网络抖动未知。[代码事实][未知] |
| 跨平台 | 5 | Windows/Linux 有目标路径；Wayland/macOS 和桌面动作未证明。[文档意图][未知] |
| 可维护性 | 6 | domain modules、runtime container、socket compositions 已建立；入口仍重。[代码事实] |
| 类型安全 | 7 | TypeScript、Pydantic、dataclass、BasedPyright/Ruff；跨语言事件仍漂移。[代码事实] |
| 可观测性 | 6 | trace、duration、ExperienceMetrics 已有；无长期采样和外部 receipt。[代码事实][未知] |
| 生态/人才 | 8 | Electron/Vue/Python/Playwright 生态成熟。[外部基准] |
| 依赖/供应链 | 5 | npm/Python/模型/插件多源，需签名和许可证审计。[推断] |
| 安全边界 | 6 | vault、policy、loopback 和独立 host-token 合同已有；第三方沙箱仍缺。[代码事实] |
| 扩展能力 | 7 | Provider/MCP/plugin/connector registry 存在；公开 SDK 和版本策略不足。[代码事实] |
| 发布复杂度 | 5 | Electron、Python、Node、Go、模型资源四套发布面。[代码事实] |

主要风险是双运行时生命周期、Socket.IO 契约漂移、GPU/音频/compositor 差异、Qdrant/模型体积、插件/MCP/浏览器自动化/桌面动作越权、loopback 信任、多 Provider 行为和可复现构建。[推断]

## 6. 架构、数据流和状态管理

```text
Renderer(Vue/Pinia/Audio/Pet)
        | preload / local control HTTP / Socket.IO
Electron Main + Control Server + vault
        | localhost HTTP/Socket.IO
Python FastAPI + Socket handlers + AgentRuntime
        | planner -> policy -> StepExecutor/ToolExecutor -> verifier
        | SQLite authority / optional Qdrant / model providers
Node MCP (Playwright)       Go Launcher (process lifecycle)
        | optional external connectors/providers
```

输入经 renderer 到 `TurnService`，绑定 workspace/session/turn/generation/interruption，再经过 pipeline 的 context、planning、execution、projection 阶段，终态投影到 Socket、Avatar、TTS 和 trace；记忆写入 SQLite 并更新可重建 Qdrant 索引。[代码事实]

SQLite 是 turn/job/记忆权威；Qdrant 是可重建索引；Pinia 是 UI 投影；trace/event log 是审计投影；`recovery_store.py` 是受限 typed step 原型，尚未成为 runtime 权威。[代码事实]

| 位置 | 当前问题 | 改造与验收 |
|---|---|---|
| `socket_server.py` | handler 注册和生命周期偏重 | 继续迁移 `socket_compositions/`；事件 schema 测试全覆盖 |
| `step_executor.py`/`recovery_store.py` | 跨进程恢复依赖进程内 capability/context | `RecoveryContextFactory`、plan hash、attestation、lease fencing；重启后仅 fresh preflight 可恢复 |
| `socket_events.py` | 完整跨语言 schema 仍未集中生成 | 当前协议版本已严格限制为 v1，未知/非法版本 fail-closed；仍需 schema registry、`schema_version` 和旧版本显式降级 |
| memory modules | 删除/纠正和索引传播缺长期证据 | raw/derived/profile/index revision 回归集，删除后不可召回 |
| `backend_api_auth.py` | 桌面动作需要独立 host-token，普通 loopback 仍信任 | 继续补 middleware/路由矩阵和外部托管配置文档 |
| release scripts | 平台资格和资源许可缺真实证明 | Win/Linux matrix、artifact hash、许可证、24h soak 归档 |

## 7. Agent 全链路完整性审查

| 环节 | 输入/输出与路径 | 控制/状态 | 断点与风险 |
|---|---|---|---|
| 环境感知 | 请求级截图/OCR → evidence；perception bridge/handler | 单次 consent、scope、TTL、redaction、cancel | 真 GUI 和泄漏红队未知 |
| 请求理解 | 文本/音频 → canonical turn/context；`llm.py`/`context.py` | workspace、generation、interruption | 置信度和意图信封参与路由需核验 |
| 决策规划 | context → typed plan；`planner.py` | policy、敏感参数、依赖限制 | plan closure 未跨重启持久化 |
| 工具执行 | plan → result；`step_executor.py` | permission、timeout、cancel、known/unknown | durable recovery 未接入，副作用只能人工处理 |
| 结果验证 | action + verifier → receipt/unknown_effect | `tool_executor.py`、verification tests | 真实平台 receipt 未验证 |
| 反馈输出 | events → chat/TTS/avatar | `socket_events.py`、renderer/audio/pet | 断线回放和真实终态一致性未知 |
| 记忆写入 | exchange/event → raw/derived/profile/index | SQLite authority、review/delete | 长期召回与删除传播未知 |
| 后续召回/学习 | retrieval + accept/ignore/cancel → next context | memory、scheduler、proactive | 主动反馈闭环和拒绝后 0 触达未测量 |

判定：**存在关键断点（5/10）**。本地合同、状态枚举、权限路径和异常测试已证明；跨进程恢复、真实副作用、设备/平台、长期记忆和主动行为安全尚未证明。[测试证据][未知]

## 8. 2025–2026 资料与同类项目参考

资料用于设计参考，不外推 Yuizaki 的性能或安全结论；版本和发布日期应在发布前再次核验。[外部基准]

| 资料（作者/机构，日期） | URL | 核心结论 | 仓库映射 | 类型 |
|---|---|---|---|---|
| Mem0，Chhikara 等，2025 | <https://arxiv.org/abs/2504.19413> | 记忆提取/更新可降低上下文负担，需事实保持评测 | `python/modules/memory` 的 provenance/revision | 短期评测 |
| MIRIX，Wang 等，2025 | <https://arxiv.org/abs/2507.07957> | 多类型记忆分层支持跨会话任务与用户模型 | raw/derived/profile/index 分离 | 架构方向 |
| GraphMemix，作者以 arXiv 页面为准，2026 | <https://arxiv.org/abs/2608.26983> | 关系证据和预算约束记忆召回 | evidence id、revision、incomplete 状态 | 短期设计 |
| VoiceChat-TTS，作者以 arXiv 页面为准，2026 | <https://arxiv.org/abs/2608.13831> | 对话 TTS 应评响应速度、韵律和可打断性 | 语音 S1 指标和 `audio-capture.ts` | 短期评测 |
| CompanionHarm，作者以 arXiv 页面为准，2026 | <https://arxiv.org/abs/2608.25377> | 多轮伴侣风险需要关系上下文、暂停与升级 | scheduler/proactive 安全红队 | 风险参考 |
| Ma 等，*Negotiating Digital Identities with AI Companions*，CHI 2026 | <https://doi.org/10.1145/3772318.3791473> | 伴侣身份是持续协商过程 | persona/关系编辑显式可追踪 | 产品设计 |
| Electron 项目官方文档，持续更新 | <https://www.electronjs.org/docs/latest/tutorial/process-model> | 主进程、预加载、渲染器权限边界不同 | control server/vault 留在主进程 | 工程基准 |
| Open WebUI 维护者，2025–2026 releases | <https://github.com/open-webui/open-webui> | 自托管 provider/tool/权限控制面可扩展 | 参考治理面，不复制成熟度 | 同类产品 |
| Stanford HAI，*AI Index Report 2025*，2025 | <https://hai.stanford.edu/ai-index/2025-ai-index-report> | 行业报告汇总模型能力、成本、采用和治理趋势；不专门评估桌宠 | 用于 provider 成本、模型分发和治理假设的外部背景，不替代 Yuizaki 实测 | 行业报告（非桌宠专门） |
| OWASP GenAI Security Project，OWASP，2025–2026 | <https://genai.owasp.org/> | Agent、插件、工具调用需不可信输入、最小权限、审计 | MCP/网页/OCR/桌面动作边界 | 安全基准 |

## 9. P0/P1/P2 改进路线图

| 优先级/问题/影响 | 方案、文件、工作量 | 依赖/风险 | 验收与收益 |
|---|---|---|---|
| P0 安装与首次运行 | launcher readiness、资源锁、诊断、回滚；launcher/scripts；2–3 人周 | 真实 Win/Linux runner、许可 | clean install/升级/重启/失败恢复归档，降低流失 |
| P0 host-token/桌面动作 | 独立 Bearer host-token、常量时间比较和 distinct 检查已落地；补 middleware/路由矩阵；0.5–1 人周 | 外部托管 Python 需显式注入 token | 错/缺/复用 token 明确拒绝，避免越权 |
| P0 durable step recovery | `RecoveryContextFactory`、plan hash、attestation、lease fencing 接入 runtime；3–5 人周 | capability 生命周期 | 崩溃后只恢复安全 typed step，副作用不自动重试 |
| P0 MCP/插件供应链 | manifest 签名、权限、撤销、catalog-only；`mcp_manager.py`/plugin routes；2–4 人周 | 第三方沙箱 | 无签名/过期/越权能力不执行，审计可回放 |
| P0 语音/Avatar/视觉资格 | Win/Linux 设备矩阵、30 分钟 soak、GPU/音频/compositor 回归；2–4 人周 | 真实设备资源 | 首包/打断/帧率/崩溃阈值达标或诚实降级 |
| P0 法律与发布 | 完成 notices、模型/声音/角色/字体清单、artifact hash；1–2 人周 | 上游许可核验 | 每项资源有来源、版本、许可、卸载说明 |
| P1 低注意力/主动反馈 | 机会评分、预算、snooze、解释、接受/忽略/取消指标；scheduler/UI；3–4 人周 | P0 可观测性 | 拒绝后再次触达率 0，频率可调可解释 |
| P1 记忆质量 | query-aware budget、evidence forest、删除回归集；memory；3–5 人周 | 长期对话数据 | precision/recall、删除时间、泄漏率有基线 |
| P1 事件契约/tracing | Socket v1 版本门禁已落地；继续建设 schema registry、版本协商、trace correlation；socket/HTTP；2–3 人周 | 生成工具 | 未知版本明确拒绝；后续旧客户端显式降级，单 turn 可串联事件 |
| P1 Provider/平台适配 | capability matrix、文字降级、Wayland/macOS 适配；2–6 人周 | 目标平台 | 每个平台能力和失败文案可验证 |
| P2 角色/插件市场 | 签名目录、版本、撤销、隔离；6–10 人周 | P0 供应链 | 第三方包可审查、回滚、撤销，成本可测 |
| P2 直播/办公/游戏 | OBS/Twitch staging、沙箱 GUI、场景评测；6–12 人周 | P0/P1 | 外部动作有 preview/confirm/receipt，成功率和成本有数据 |

## 10. 开源适合度专项评估

| 项目 | 当前证据 | 判断 |
|---|---|---|
| LICENSE/第三方资源 | MIT 与 `THIRD_PARTY_NOTICES.md` 存在，模型/声音/角色需逐项核验 | 部分满足 |
| SECURITY/密钥 | `SECURITY.md`、vault、脱敏、no-store 和 host-token 合同已有 | 平台红队与外部托管验证仍需 P0 |
| 本地隐私 | SQLite、截图、音频、日志、缓存路径有文档；删除传播未知 | 部分满足 |
| 安装门槛 | Electron/Python/Node/Go/模型五套依赖 | 需更强诊断 |
| 平台声明 | Windows/Linux 目标，macOS/Wayland 限制应公开 | 部分满足 |
| CI/锁定/发布 | workflows、npm lock、Python、Go、runtime checks 存在 | 真实 artifact 仍缺 |
| 文档 | README/API/配置/架构/贡献/安全存在 | 缺完整故障排查和能力矩阵 |
| 插件/MCP/连接器 | vault、policy、manifest 基础；签名/沙箱/撤销缺 | P0 未完成 |
| 社区治理 | `CONTRIBUTING.md`、`CODE_OF_CONDUCT.md` 存在 | Issue 模板和维护责任需补 |
| 贡献边界 | 目录和测试入口清晰，双运行时学习成本高 | 需开发容器/最小测试集 |

开源前 P0：真实 Win/Linux 安装与升级；host-token middleware/路由矩阵和外部托管配置验证；MCP/插件最小权限和签名；副作用回放；模型/素材许可；漏洞响应；发布 hash 与回滚；明确 macOS、QQ/微信桥、公网连接器和模型下载限制。角色市场、直播、游戏、多设备同步可延后。必须声明本地数据默认不上传但用户配置的 Provider/连接器例外，视觉按请求仍可能处理敏感屏幕，实验性能力不保证平台账号或法律合规。[未知]

## 11. 关键风险登记表

| 风险 | 可能性/影响 | 当前控制 | 缺口与动作 |
|---|---|---|---|
| 桌面动作越权 | 中/高 | policy、独立 host-token、loopback、审计 | 外部托管和真实平台红队仍需验证 |
| 副作用重复执行 | 中/高 | known/unknown effect、lease 原型 | StepExecutor 未跨进程恢复；接入 attestation/fencing |
| 凭据泄漏 | 中/高 | vault、脱敏、no-store | 真实 OS backend/CAS 和插件审计未知 |
| 截图/音频/记忆泄漏 | 中/高 | 请求级感知、SQLite 删除 | 长期删除传播和红队未知 |
| 多运行时崩溃/升级 | 中/高 | launcher、CI | Win/Linux soak 缺 |
| 依赖/模型许可证 | 中/高 | lock files、notices | 资源版本/许可证未逐项证明 |
| 连接器重复投递/风控 | 中/高 | delivery 状态、去重 | 公网 staging 未验证 |
| 伴侣依赖/操控 | 中/中高 | 暂停、频率控制设计 | 多轮红队和用户研究缺 |
| 资源占用/首屏 | 中/中 | bundle audit | LCP/RAM/GPU p95 未知 |

## 12. 证据索引

| 主题 | 证据 |
|---|---|
| 对话/Socket | `python/socket_handlers/llm.py`、`python/socket_events.py`、`python/modules/agent/turn_service.py` |
| Agent/工具 | `runtime.py`、`pipeline.py`、`planner.py`、`step_executor.py`、`tool_executor.py`、`policy_engine.py` |
| 记忆 | `python/modules/memory/`、`test_memory_operations.py`、`test_memory_context_recall.py` |
| 语音/Avatar/视觉 | `electron/src/renderer/audio/`、`pet-renderer*.ts`、`authorized-perception-bridge.ts` |
| MCP/安全 | `mcp_manager.py`、`mcp-config-vault.ts`、`mcp-vault-routes.ts`、`SECURITY.md` |
| 恢复 | `recovery_store.py`、`test_recovery_store.py`、`test_step_recovery_contract.py` |
| 发布/平台 | `.github/workflows/`、`scripts/platform_release_check.py`、`tools/yuizaki-launcher/`、`resources.lock.json` |
| 产品意图 | `README.md`、`PRODUCT.md`、`docs/ARCHITECTURE.md`、`docs/IMPROVEMENT_ROADMAP.md` |

## 13. 验证结果与覆盖边界

- `python -m pytest -q`：292 passed。[测试证据] 覆盖合同、异常、脱敏、恢复、recovery-store fencing、host-token middleware、Socket v1 版本门禁和模拟路径；不覆盖真实 GPU、声卡、外部平台、跨进程重启和 24h soak。[未知]
- 变更文件的 Ruff import/F/E9 检查与 `compileall`：通过；全仓 Ruff 仍有 `socket_events.py` 等既有 typing 风格告警，未在本轮扩大清理范围。[测试证据]
- Electron `npm run test:unit`：12 files / 51 tests；`npm run type-check`、`npm run lint`、`npm run build`：通过；主入口约 431.86 kB，320 kB 目标未达成。[测试证据]
- `npm run check:package-runtime`：15 required files，无模型权重；node-mcp：7 passed；Go `go test ./...`：通过。[测试证据]
- `git diff --check`：通过（既有 CRLF warning）。[测试证据]
- `python scripts/platform_release_check.py --target-platform windows`：按设计 `not_qualified`，缺平台 attestation、24h soak、desktop/text_voice qualification；这是 fail-closed 门禁证据，不是实现失败。[测试证据]

## 14. 未知项与下一步验证建议

未知项包括 Windows/Linux 真实音频、GPU、Wayland、Live2D/VRM 资源，macOS，Provider 成本与行为，公网 Telegram/Discord/Twitch staging，连接器重复 webhook，GUI VM/sandbox，长期记忆质量，主动行为打扰率，逐项资源许可证，外部托管 host-token 配置和跨进程 Agent step recovery。[未知]

1. 在干净 Windows/Linux 主机执行安装、升级、卸载、重启和 24h soak，保存 artifact hash、日志和资源曲线。
2. 用真实声卡/GPU 测量语音首包、端到端延迟、barge-in、TTS underrun、Avatar 帧率和崩溃恢复。
3. 在 staging 账号验证 Telegram/Discord webhook 去重、发送 receipt、撤销和 unknown_effect，不接生产账号。
4. 建立长期对话和敏感记忆回归集，测召回 precision/recall、删除传播时间、泄漏率和 provenance。
5. 验证外部托管 host-token 配置与 middleware/路由矩阵，再将 `recovery_store.py` 接入 fresh context/capability preflight。
6. 对 MCP、插件、网页内容、OCR、截图和桌面动作做越权、凭据泄漏、提示注入和人工接管红队。

在证据收齐前，最准确的外部表述是“本地优先、功能广泛、正在封板的可用 Alpha”，不能宣称生产级桌面 Agent、离线全能力产品或公网连接器平台。[推断][未知]
