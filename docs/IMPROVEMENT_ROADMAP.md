# Yuizaki 改进流程路线图

状态：2026-08-28 启动，按小步迭代执行。本文档以当前仓库代码为基线，不改变默认 loopback 信任、现有权限收据、请求级视觉和“unknown effect 不自动重试”安全约束。

## 目标与不变量

### 90 天目标

1. 每个会产生现实影响的工具调用都有可观察的结果状态、证据和恢复路径。
2. 文字、语音、视觉和桌宠动作共享统一的意图与终态契约，长任务不会静默丢失。
3. 主动行为保持低频、可解释、可暂停，并能利用接受/忽略/取消反馈改善时机。
4. SQLite 仍是记忆权威源；记忆、任务经验、失败反思和可执行技能分层治理。
5. Windows/Linux 目标机完成 Provider、音频、GPU、角色资源和 24 小时驻留认证后，才扩大公开发布范围。

### 不变量

- 默认 loopback 信任模型不在本路线图中削弱或替换；任何公网部署另行立项。
- 用户确认、host token、lease、revocation 和 emergency stop 仍是高风险能力的权威边界。
- 工具、OCR、截图、网页、MCP 和插件输出永远是不可信 evidence，不得直接产生授权。
- 状态改变后无法确认现实效果时，结果必须是 `unknown_effect`，不得自动重试为成功。
- 视觉默认请求级、短期处理，不引入默认持续录屏或摄像头历史。

## 阶段路线图

| 阶段 | 时间 | 交付目标 | 关键模块 | 验收指标 |
|---|---|---|---|---|
| P0-A | 0-2 周 | 统一结果验证与终态 | `python/modules/agent/tool_executor.py`、`step_executor.py`、`tool_loop.py`、`tool_registry.py`、`socket_events.py` | state-changing tool 均能报告 verification status；终态幂等；错误/取消/unknown effect 有测试 |
| P0-B | 0-2 周 | 发布资格和驻留稳定性 | `.github/workflows`、`scripts`、launcher、音频/角色运行时 | Windows/Linux 设备矩阵；24h 内存、句柄、CPU、GPU 无持续增长 |
| P0-C | 0-2 周 | 连接器可靠交付 | `python/routes/connector_api.py`、`modules/agent/turn_store.py`、`message_connectors.py` | webhook 重放幂等；Agent 崩溃可恢复；已确认投递不重复 |
| P1-A | 3-6 周 | 意图和敏感度契约 | `modules/agent/interpret.py`、`planning_stage.py`、`context_stage.py` | 每个 turn trace 含 `intent-envelope.v1`；低置信度或敏感意图可解释 |
| P1-B | 3-6 周 | 主动行为反馈学习 | `activity_frames.py`、`heartbeat.py`、proactive renderer | 接受/忽略/取消写入反馈；后续冷却、时机和类别可回溯 |
| P1-C | 3-6 周 | 记忆和技能分层 | `modules/memory`、`skill_store.py`、`memory_write_pipeline.py` | 用户事实、关系事件、反思和技能分开检索/删除；敏感候选默认 review-only |
| P2-A | 2-3 月 | 低敏感桌面上下文 | Electron host perception、activity frames、隐私设置 | 用户显式授权后才采集；敏感应用屏蔽；每条建议有原因和撤销 |
| P2-B | 2-3 月 | GUI Agent 沙箱验证 | 独立 sandbox/VM、截图循环、verifier | 主机不可越权；每步可暂停、接管、恢复；OSGym 风格任务集通过 |
| P2-C | 3-6 月 | 角色/技能生态 | plugin SDK、manifest、签名、审核和版本 | 第三方能力声明权限、可禁用、可回滚；不影响基础文本链路 |

## 当前已完成改进

- 规划阶段生成 `yuizaki.intent-envelope.v1`，显式记录意图类型、置信度、敏感度、证据 ID、确认要求和过期时间。
- 该 envelope 仅作为上下文和 trace 元数据，不替代 `PolicyEngine`、PermissionReceipt 或 Electron host 权限。
- 现有 `ToolDefinition.postcondition_verifier`、`recheck_handler`、`unknown_effect` 和 `idempotency_key` 作为结果验证增量改造的兼容基础。
- `tool:result` / `tool:error` 的 Socket.IO 投影已保留结果验证目标、参数摘要、证据、可重试性和未知效果字段，并携带 `schemaVersion: yuizaki.tool-event.v1`；Electron 共享类型和协议清单同步支持这些字段，旧字段仍兼容。
- P0-A 补齐未知效果终态归一化：`python/socket_handlers/tool.py` 对执行器返回的 `success=True, outcome="unknown_effect"` 强制投影为 `tool:error`、`status="failed"`，清空输出并保留 `unknown_effect`/不可重试语义；`python/tests/test_socket_tool_handler.py` 覆盖该回归，避免现实效果未确认时伪装为成功完成。
- P0-A 补齐步骤层终态一致性：`python/modules/agent/step_executor.py` 的 typed 与兼容 `execute_tool_steps()` 两条路径均按 `outcome == "known_success"` 且 `success=True` 派生步骤成功字段；新增旧适配器伪造 `success=True + unknown_effect` 的回归，确保步骤汇总不会把未知现实效果记为成功。
- P0-A 补齐 tool-loop 终态一致性：`python/modules/agent/tool_loop.py` 新增统一 `_outcome_succeeded()`，非流式记录、状态变更标记以及流式/非流式工具消息均以显式 `known_success` 为成功来源；新增 malformed adapter 回归，确保 `unknown_effect` 不会在任一路径投影为成功。
- P0-A 收敛成功判定接口：`python/modules/agent/tool_result.py` 新增 `is_known_success()` 及 `ToolResultEnvelope.is_known_success`，步骤执行器和 tool-loop 复用同一谓词，降低新增适配器路径发生终态漂移的风险。
- P0-A 加固长任务事件日志：`python/modules/agent/companion_events.py` 对 job timestamp 执行有限数值校验，`NaN/Infinity` fail-closed 且不会分配半成品 job；新增 100 次 progress 后 terminal 保留、容量裁剪和非有限时间戳回归。
- 主动行为机会事件已增加 `reason_code`、`scene_confidence`、`user_work_state`、`expected_benefit` 和 `interrupt_cost`；当前环境感知不足时显式报告 `scene_confidence=0` 与 `unknown`，不把猜测当作事实。
- 记忆写入和检索已增加受控 `memory_role`：`user_fact`、`relationship_event`、`task_experience`、`failure_reflection`、`reusable_skill`、`tool_permission`。旧文档缺省该字段时按既有 layer/type/source 确定性回退；检索可按职责过滤，SkillCatalogStore 仍保持独立存储。
- 删除预览/批量删除返回职责计数，审计事件记录 `memory_role`；`tool_permission` 自动进入 review-only pending 状态，避免权限历史混入普通召回。
- 新增 `python/modules/system/release_readiness.py` 与 `scripts/platform_release_check.py`：发布门禁只接受显式目标机资格证明和完整驻留采样（时长、RSS、句柄、GPU、CPU p95）；缺失或超预算时 fail-closed 为 `not_qualified`，不会把能力矩阵中的 `experimental`/`needs_config` 升级为可发布。
- P1-A 增加 `python/modules/agent/interpret_evaluation.py` 与 `python/tests/fixtures/intent_evaluation_cases.json`：以 `yuizaki.intent-evaluation.v1` 重放 intent、敏感度、确认要求和置信度范围；敏感资源请求统一归类为 task，但评测永远不产生授权。
- P1-A 补齐 durable trace parity：`TurnCommitStore.persist()` 以白名单和长度/数值边界保存 `yuizaki.intent-envelope.v1`，`agent-trace.terminal` 投影可在重启/回放后恢复同一 envelope；该元数据不进入权限判定。
- P1-A 加固评测输入契约：`interpret_evaluation.py` 现在拒绝非法 intent、非布尔 confirmation、超出 `[0,1]` 或非有限 confidence 边界、非有限 replay 时间及未类型化结果，避免损坏 golden case 或伪造结果污染聚合指标。
- P1-A 加固 envelope 本体边界：`python/modules/agent/interpret.py` 的 `IntentEnvelope` 现在对 intent/sensitivity、有限 confidence、evidence ID、确认布尔值和过期时间执行 fail-closed 校验，避免未经过评测入口的直接构造污染 trace/store。
- P1-B 扩展 `activity_frames.py` 的行为反馈契约：`accepted`、`ignored`、`cancelled`、`snoozed` 写入持久化反馈；取消/延后/忽略会围栏待处理机会，接受只作为学习信号，实际投递仍由 Turn/Job 终态确认；提供 `list_feedback()` 审计回放。
- `ActivityFrameService.project_event()` 对主动上下文同时兼容 Python `snake_case` 与 renderer `camelCase` 字段，并继续执行白名单、数值范围裁剪和原始内容剔除；新增跨命名风格回归测试，避免跨进程事件投影静默降级为 `unknown`。
- P1-B 增加主动反馈保留治理：反馈按 workspace 建立时间索引，超过 90 天自动清理；30 天学习窗口和 7 天半衰期保持不变，避免长期运行下反馈无限增长。
- P1-B 增加 `feedback_summary().categoryPreferenceScores`，输出每个活动类别的有界衰减偏好分数，让治理 UI 能解释可逆的主动行为抑制原因而不暴露原始内容。
- P1-B 增加反馈摘要的显式评测时钟：`feedback_summary(now=...)` 支持固定时间回放并拒绝非有限时间戳；默认不传参数时继续使用系统时钟，生产主动行为策略和用户暂停语义保持不变。
- P1-B 修复反馈回放与留存耦合：`ActivityFrameStore.list_feedback(now=...)` 接受显式清理时钟，`feedback_summary(now=...)` 将同一时钟传入留存清理，历史策略评测不再受当前墙上时钟隐式删除影响；默认线上调用仍使用系统时钟。

## 研究依据

- Computer Use UX、解释和接管：[E1] https://arxiv.org/abs/2602.07283
- Computer Use 失败诊断和恢复：[E2] https://arxiv.org/abs/2608.02643
- Universal Verifier：[E5] https://arxiv.org/abs/2604.06240
- 持久 Agent 信息流安全：[E6] https://arxiv.org/abs/2608.27234
- 工具输出与授权分离：[E7] https://arxiv.org/abs/2608.27146
- 主动 Agent 反馈和可争议性：[E16] https://arxiv.org/abs/2603.14449
- 全双工语音视觉评测：[E15] https://arxiv.org/abs/2605.30256
- 长期记忆证据融合：[E11] https://arxiv.org/abs/2608.26983
- 主动个性化 Agent workshop：[E26] https://arxiv.org/abs/2608.18638
- LangGraph durable execution：[G6] https://github.com/langchain-ai/langgraph

### 2026-08-28 研究复核与同类项目映射

以下资料在 2026-08-28 通过 arXiv 页面或 pinned GitHub commit 复核；论文中的实验指标不外推为 Yuizaki 的指标，启发项属于架构推断。

| 来源 | 已核验事实 | 对本仓库的具体启发 |
|---|---|---|
| [CUADesignSpace, arXiv:2602.07283](https://arxiv.org/abs/2602.07283) | 访谈与 Wizard-of-Oz 研究将 Computer Use UX 归纳为提示、解释、用户控制和心智模型 | 将 `activity_frames.py` 的 `reason_code/scene_confidence/expected_benefit/interrupt_cost` 转成用户可理解的主动行为解释；高风险动作保留暂停/接管 |
| [Universal Verifier, arXiv:2604.06240](https://arxiv.org/abs/2604.06240) | 强调 process/outcome 分离、可控/不可控失败区分和长轨迹分治验证 | `tool_executor.py`、`step_executor.py`、`tool_loop.py` 统一 `known_success/known_failure/unknown_effect`；P2-B 仍需真实 CUA verifier |
| [CUADebug, arXiv:2608.02643](https://arxiv.org/abs/2608.02643) | OSWorld 失败轨迹显示 reasoning/control、perception、grounding 等失败族，结构化 RCA+重执行优于 history-only | GUI step 应保存 before/after 状态、根因和纠正策略；当前仅有 sandbox evidence 契约，诊断器/截图循环未交付 |
| [SPA, arXiv:2608.27234](https://arxiv.org/abs/2608.27234) | plan-first 信息流控制给持久 Agent 的 artifact 加 confidentiality/integrity 标签 | 继续保持 SQLite authority、`memory_role` 分层及 evidence 不产生授权；长期记忆只回传净化 metadata/provenance |
| [SARA, arXiv:2608.27146](https://arxiv.org/abs/2608.27146) | 将 action induction/provenance 与 runtime authorization 分离，阻止历史晋升为新权限 | `skill_runtime.py` 必须经过 manifest/trust、scope 和 `ToolExecutor`；工具输出不能直接触发新权限 |
| [Tap-to-Adapt, arXiv:2603.14449](https://arxiv.org/abs/2603.14449) | 激活/打断等 tap 事件可作为响应时机在线标签 | 当前 `activity_frames.py` 已持久化 accepted/ignored/cancelled/snoozed，并计算 30 日窗口的类别偏好；仍缺真实语音样本 |
| [VideoFDB, arXiv:2605.30256](https://arxiv.org/abs/2605.30256) | 双工视觉-语音评测显示字幕、视觉忽略和级联 avatar 的非语言交互缺陷 | 不能把文本链路通过等同于 AV 完成；P0-B 资格门禁仍等待音频/GPU/角色资源实机证据 |
| [GraphMemix, arXiv:2608.26983](https://arxiv.org/abs/2608.26983) | query-aware evidence forest 用证据效用/关系验证/预算优化长期多模态记忆 | 记忆召回应携带 evidence IDs、index revision、预算和 incomplete 状态；当前已落地 incomplete/dedupe 契约，算法与长期数据集未完成 |
| [CHIIR 2026 Proactive Agents Workshop, arXiv:2608.18638](https://arxiv.org/abs/2608.18638) | 主动性强调适时、透明、可争议和符合用户目标，而非单纯更早预测 | 保持低频、可解释、可暂停和反馈学习；将关系安全和舒适度列为退出条件 |
| [`microsoft/fara`](https://github.com/microsoft/fara/tree/a675d6d61c41c47ae87bacefeab22caad18e3e84) | pinned README 描述 observe-think-act、用户模拟器、环境/solver/verifier 和可审计沙箱 | P2-B 可采用 environment/solver/verifier 分层及不可逆动作前审批；不代表 Yuizaki 已有真实执行器 |
| [`OpenHands/OpenHands`](https://github.com/OpenHands/OpenHands/tree/226a6d2e68ebd5c86e4f275a0f33ca25f1ee0878) | pinned README 支持 REST/TS 控制中心、schedule/webhook 自动化和 Docker/VM 后端，并警告无 sandbox 时主机权限过大 | P0-C 继续使用 durable queue；P2-B 采用显式 sandbox 路径和能力矩阵，保留风险提示 |
| [`xlang-ai/OSWorld`](https://github.com/xlang-ai/OSWorld/tree/84aee655c2afb6b77ecf39884432615ba345c031) | pinned README 支持 Ubuntu/Windows VM、Docker/KVM、截图/动作/视频记录，并提示异常中断资源清理 | P2-B 必须增加跨平台 VM 资格、每步视觉证据和残留资源清理；当前未完成真实 VM/OSWorld 验收 |
| [`microsoft/magentic-ui`](https://github.com/microsoft/magentic-ui/tree/d3c9d13c39288257286a66daabf7c5b5fb72ee69) | pinned README 描述 Quicksand 轻量 VM sandbox、工具审批和浏览器/本地文件工作流 | 借鉴隔离默认与审批 UX；不把外部 sandbox 当作仓库内执行器 |
| [`langchain-ai/langgraph` checkpoint](https://github.com/langchain-ai/langgraph/tree/11ee185999b86bfea2d8c0e69cef9a5e37acf686/libs/checkpoint) | pinned checkpoint 文档支持 thread/checkpoint、pending writes、human-in-loop 和 durable execution | `TurnCommitStore`/connector queue 可继续采用 checkpoint/pending-write 语义；跨重启快照保持 schema 白名单校验，不引入 LangGraph 依赖 |

## 退出条件

- P0：文本主链路、可选语音/视觉降级、任务终态和安全回归全部通过；没有已知 P0 阻断项。
- P1：用户能理解主动行为原因、纠正记忆并看到任务验证状态；至少有一套多轮语音和长期记忆评测集。
- P2：桌面上下文和 GUI Agent 在隔离环境中可证明收益；生态能力有权限、许可证和回滚机制。

## 2026-08-28 执行进度

- P0-A：结果验证、终态投影和 `yuizaki.tool-event.v1` 已有代码与回归测试；剩余跨平台长任务/终态压力验证。
- P0-B：平台能力矩阵已有实现；本轮补齐发布门禁和 24 小时驻留报告 schema/CLI，当前仍等待 Windows/Linux 实机资格证明，状态为未资格化。
- P0-C：应用入口已为 Telegram/Discord/QQ/微信个人桥启用“持久化后快速确认/Deferred ACK”；新增 `ConnectorRecoveryController` 按应用 lifespan 扫描过期 `processing` lease 并复用 retry 路由恢复，`sending`/unknown-effect 不自动重发；新增 Discord ACK 前 durable enqueue 回归测试；仍需公网 webhook/真实桥接器的目标机验收。
- P0-C 本地端到端增量：新增 ASGI 级 Telegram Webhook 回归，覆盖验签、durable enqueue、Agent turn、provider 回复、重复事件幂等和错误签名拒绝；当前测试集合共 64 项通过，仍不替代真实平台 staging 验收。
- P0-C 增加 `yuizaki.connector-recovery.v1` 有界运行时遥测：delivery 列表返回扫描、恢复、失败累计数和最近扫描时间，不包含消息或凭据，便于发现 durable queue 无人消费。
- P0-C 补齐恢复遥测前端可见性：Electron `system-client` 对 `recovery` 字段执行白名单归一化，系统域按连接器保留快照，Agent Governance 面板展示扫描、检查、恢复、失败和最近扫描时间；缺失或非法遥测只降级为空，不影响投递列表。
- P0-C 增强恢复遥测持久化：`ConnectorRecoveryController` 支持由应用显式传入 data 目录路径，使用限值校验和原子替换跨重启恢复计数/最近错误；默认未传路径时不落盘，持久化快照不含 delivery key、事件 ID、消息正文或凭据。
- P0-C 修正恢复遥测终态统计：retry 只有 2xx 响应才计为成功，4xx/5xx/异常均计入失败并记录有界错误码；载入的 `lastRunAt` 要求有限且处于合理时间范围。
- P0-C 增加恢复状态机回归：验证 retry 返回 5xx 或抛出异常时恢复行仍保持 `failed`、可由人工 retry；重复扫描只处理仍为 `processing` 的过期行，并明确不触碰 `sending` 与 `unknown_effect`。新增 SQLite 集成回归，直接断言真实 `TurnCommitStore` 在 502 后清空 claim 并保留 `failed`。该测试覆盖恢复控制器与 durable store 之间的失败边界，不把 provider 错误误报为已送达。
- P0-C 修复 durable enqueue 后的重复 webhook 边界：已有 `failed` 且无 `reply_text` 的 turn 只返回幂等状态，不再隐式重新生成 Agent turn；已有 `failed` 且带回复的 provider 投递仍允许复用回复重投；`sending` 继续保持未知效果 409，`delivered` 返回已送达，delivery key/event 冲突 fail-closed。新增“进程崩溃后重复 webhook 不重跑 Agent”回归。
- P1-A：意图 envelope、敏感意图识别、可重放评测契约、聚合准确率/敏感度/确认率/置信度指标和 durable trace parity 已落地，golden fixture、TurnStore/Outbox 定向测试通过；仍需在真实多轮数据集上扩展覆盖。
- P1-A 增强 intent golden fixture：新增情感陪伴和屏幕截图敏感请求样例，当前脱敏可重放样例共 6 个；评测只验证解释/确认契约，不产生权限或工具授权。
- P1-B：主动行为解释字段、接受/忽略/取消/延后反馈、舒适度门控、类别级预算、受控场景上下文投影、30 天窗口/7 天半衰期类别偏好分数、高置信工作状态抑制、显式暂停/恢复、持久化回放和 90 天反馈保留治理已落地；仍需接入更丰富的长期用户模型。
- P2-A：Electron 感知桥对 `active_application` 增加常见敏感应用/窗口屏蔽和主进程可配置匹配器；仍保持请求级、单次授权和无持续截图/摄像头历史。
- P2-B：已补齐 `computer_use_sandbox.py` 的 fail-closed 沙箱 attestation、GUI step evidence 和任务级验证率/接管/unknown-effect 聚合指标；现在额外要求带生命周期的 `attestationId`/`taskId`/`nonce`、有效时间窗、任务 `objectiveDigest`、每步 `actionDigest` 与绑定的 `verifierEvidenceIds`，并拒绝跨任务或状态不一致的聚合结果。步骤仍要求唯一 ID、固定顺序、显式截图 evidence ID、pre/post 状态链和 verifier 状态；真实隔离执行器、截图采集、OSGym 风格任务集和接管实现仍未完成。
- P1-C：六类 `memory_role`、检索过滤、删除职责计数、审计、`tool_permission` review-only、SkillCatalogStore 的版本化原子持久化、目录/执行能力分离契约、显式技能运行时绑定、manifest/签名校验、密钥撤销/轮换、ToolExecutor 委托和脱敏审计已落地；新增角色准确率/敏感角色泄漏评测及 `memory_role_golden_cases.json`，仍需真实长期对话数据集、生产密钥托管策略和具体技能执行器整合。
- P1-C 增强 `SkillCatalogStore`：导入技能目录条目显式返回 `executionReady` 与 `runtimeBinding`；当前导入条目标记为 `catalog_only`，不会把目录存在误报为可执行能力，旧 `installed/status/ready` 字段保留用于兼容。
- P1-C 前端 ToolPanel 已消费该契约：本地导入、后端迁移和目录卡片统一显示“仅目录”，离线/后端降级时也不会把 catalog 条目当作可调用工具。
- P1-C 新增 `python/modules/agent/skill_runtime.py`：运行时只能把目录条目绑定到已注册的 `ToolDefinition`，请求范围必须是目标工具已声明的 scope；技能执行强制委托给现有 `ToolExecutor`，不新增权限绕过；审计只保留参数摘要、结果终态、验证状态和重试性，并以 `yuizaki.skill-runtime.v1` 版本化、限长、原子写入。
- `AgentRuntime` 现在持有共享 `SkillCatalogStore` 与 `SkillRuntimeRegistry`，系统路由复用同一目录实例；绑定仍为进程内显式动作，重启后默认为 `catalog_only`，避免可编辑文件成为隐式信任根。
- P1-C 新增 `python/modules/agent/skill_manifest.py`：`SkillManifest` 对技能包执行 SHA-256、可选签名、运行时版本上下界和 runtime binding 校验；`SkillRuntimeRegistry.bind_verified_tool()` 在校验通过后才写入执行态，并在审计中标记 manifest 版本与签名状态。
- P2-C 加固技能 manifest 输入边界：签名、key ID、runtime binding、checksum、scope 数量/长度和 package 类型均执行显式格式/长度校验；损坏或恶意 manifest 在密码学验证前 fail-closed。
- P1-C 新增 `python/modules/agent/skill_trust.py`：`SkillTrustStore` 仅持久化签名 key ID、active/revoked 状态、轮换关系和原因；`wrap_verifier()` 在调用密码学验证器前强制检查 key 是否 active，未知或已撤销 key fail-closed，且不保存私钥或签名材料。
- P1-C 完成跨重启审计脱敏闭环：`SkillRuntimeRegistry` 和 `SkillTrustStore` 载入持久化 JSON 时先校验 schema，再按字段白名单、长度、状态和有限时间戳逐条规范化；含 `parameters`、未知字段、NaN/Infinity 或错误类型的历史条目会被丢弃，不会通过 snapshot 回显。
- P1-C 增加跨重启审计回归证据：技能执行审计不再持久化原始 `parameters`；腐坏历史记录、未知字段、私密参数和非有限时间戳在恢复后均被丢弃，snapshot 仅保留受控摘要。
- P0-A 补齐步骤层终态字段一致性：typed 与兼容工具步骤均以 `success=True` 且 `outcome=known_success` 派生 `StepResultRecord.success`；旧适配器伪造 `success=True + unknown_effect` 时仍投影为失败且不可自动重试。
- P1-C 补齐记忆 dedupe 降级契约：新增/typed 写入在索引扫描不完整时返回 `memory_dedupe_incomplete`、`complete=false`、backend 和 trace，且在无法证明去重完成时不写入 SQLite 权威源或向量索引。
- P1-C 加固默认召回隔离：`python/modules/memory/vector_store.py:is_memory_recallable()` 对 `tool_permission` 执行默认拒绝，即使遗留/外部文档缺少 `candidate/pending` 治理字段，也只有显式 `memory_role=tool_permission` 的审计查询可以请求该角色。
- P1-C 增强召回证据追溯：`python/modules/memory/schema.py:RetrievalTrace` 与 `pipeline.py` 现在投影 `authority_revision`、`index_snapshot_revision`、`revision_stable` 和 `index_consistency`；召回期间 SQLite 权威 revision 发生变化时标记 `complete=false`/`authority_changed_during_recall`，避免并发写入下误把结果当作稳定快照。
- P0-C 补齐 connector lease 保护回归：真实 `TurnCommitStore` 的有效 `processing` lease 不会被恢复扫描抢占、重复执行或重复投递；过期 lease 仍按既有恢复状态机处理。
- P0-B 测试稳定性加固：崩溃边界夹具将 Windows 冷启动/导入超时从 10 秒调整为仍有上限的 30 秒，保留子进程 barrier 和退出码断言，避免环境启动延迟伪造崩溃失败。
- `AgentRuntime` 默认创建并注入共享 `SkillTrustStore`，`SkillRuntimeRegistry` 使用同一信任状态；密钥轮换在旧 key 预检、替换关系和单次原子写入后才提交，失败不会残留半轮换状态。
- P0-B 增强 `python/modules/system/release_readiness.py`：资格门禁结果现在附带平台 attestation 与 soak report 的 SHA-256 evidence fingerprint，只输出摘要指纹，不回显设备标识或驻留采样内容，便于 CI/发布审计追溯输入版本。
- P0-B 增强驻留证据独立性：`evaluate_soak_report()` 要求每条采样包含严格递增的 `timestampSeconds`，并验证采样跨度与声明时长一致；自定义预算只接受已知字段、有限数值和非负边界。显式空/非法平台能力快照保持 fail-closed，不会被本机探测结果隐式替换。
- P0-B 加固 `scripts/platform_release_check.py`：`--output` 使用同目录临时文件和原子替换，避免发布门禁报告被中断写入截断；无资格证据仍稳定返回退出码 2，并通过 CLI 回归验证 stdout/文件报告一致。
- P0-B 加强发布证据绑定：`python/modules/system/release_readiness.py` 要求 `platform_qualification` 显式声明 `targetPlatform`，且必须与能力快照目标一致；缺失或错配均 fail-closed，`test_release_readiness.py` 覆盖两种情况，避免把一台平台的资格证明套用于另一平台。
- P0-B 修复发布报告隐私边界：资格通过时不再原样回显 attestation，仅输出 `status`、规范化 `targetPlatform` 和 SHA-256 evidence fingerprint；设备标识及驻留原文不会进入公开报告。
- P2-B 增强证据绑定契约：`validate_sandbox_attestation()` 对 attestation 生命周期和任务绑定 fail-closed；`evaluate_gui_task()` 对目标摘要、动作摘要和 verifier evidence 执行白名单校验；`summarize_gui_task_results()` 拒绝 schema、任务 ID、任务终态或证据绑定不一致的自描述结果，并统计 `rejectedRows`。
- P2-B 加固 GUI 证据输入边界：`computer_use_sandbox.py` 对 attestation/task/step/evidence 标识执行安全字符校验，单任务最多 128 步，非法证据 ID 或超限轨迹 fail-closed；新增身份、证据和容量回归，仍不等同于真实 VM 执行器。
- P1-B 增加反馈可见性闭环：后端新增 `GET /api/system/proactive/feedback-summary`，只返回有界总数、行为反馈数、接受率和类别偏好分数；Electron 设置面板显示该摘要，摘要读取失败只影响遥测显示，不会关闭已同步的主动陪伴策略。提交反馈后会尝试刷新摘要，仍不暴露消息正文、原始音频或凭据。
- P1-B 增加用户延后入口：前端主动陪伴面板暴露“稍后提醒”，复用后端已有 `snoozed` 反馈、冷却和类别偏好学习；摘要 workspace 不匹配时丢弃，避免跨工作区遥测串线。
- S1 语音增量：运行设置新增麦克风输入设备选择，枚举仅返回有界的输入设备 ID/标签；本地录音和 WebRTC 都使用用户选择的 `ideal deviceId`，设备切换会关闭旧实时会话并重新预热，避免继续占用已拔出的设备。
- S1 语音设备选择验证：Electron 音频健康/实时状态机定向测试 `9 passed`，完整当前 Electron 测试集 `15 passed`；Python 当前测试集 `57 passed`，type-check、相关 ESLint、compileall、文档校验和差异检查通过。
- 本轮增量验证：主动陪伴反馈摘要/路由与 `snoozed` 持久化回归 `2 passed`；当前工作树可运行的 Python 测试集 `57 passed`，Electron 测试 `13 passed`，type-check、相关 ESLint、compileall、文档校验和 `git diff --check` 通过。
- 本轮验证：Electron 全量 `174 passed / 1230 tests`；Electron type-check、lint 通过；连接器恢复定向 `10 passed`（含有效 lease 不抢占、非 2xx 遥测、非有限时间和真实 `TurnCommitStore` 502 持久化断言）、连接器路由定向 `58 passed`（含重复 webhook、failed turn 不重跑、provider 失败回复复用、sending unknown-effect 和并发 canonical turn 回归）、GUI sandbox 定向 `10 passed`（含过期、跨任务、缺目标/验证证据和伪造聚合回归）、intent evaluation 定向 `5 passed`（含 malformed confidence/confirmation/result 回归）、release readiness 定向 `10 passed`（含时间戳、采样跨度、预算边界、空快照、资格目标错配及完整报告隐私投影回归）、发布检查 CLI 定向 `1 passed`（含退出码、原子输出和临时文件清理）、主动行为定向 `46 passed`（含固定时间回放摘要）、技能运行时/manifest/trust/启动定向 `18 passed`（含跨重启审计清洗和 schema fail-closed 回归）、工具 Socket 终态定向 `6 passed`（含 unknown-effect 成功伪装回归）、步骤计划契约定向 `114 passed`（含双路径 unknown-effect success 归一化回归）、tool-loop 定向 `36 passed`（含非流式/流式 malformed unknown-effect 投影回归）、job event capacity 定向 `15 passed`（含 100 次 progress、terminal 保留和非有限 timestamp 回归），关键变更文件 Ruff 与 `--select F,E9`、compileall、`git diff --check` 通过；`python/modules/memory/routes.py` 仍有既有 87 项全量风格告警，未在本轮扩大清理范围；Python 受版本控制测试集全量 `1347 passed, 1 skipped`。根目录 pytest 仍会扫描本地临时目录并受 Windows 权限阻断，因此全量证据以 `python/tests` 为准。
- 本轮增量验证：intent envelope/context/planning/evaluation `16 passed`（含 malformed metadata），工具结果/计划/tool-loop `68 passed`，GUI sandbox/contract/host `47 passed`，主动行为/记忆反馈 `52 passed`（含回放时钟控制 retention），memory role/source/week1 `67 passed`（含权限角色默认隔离、revision trace 和并发变更回归）；最终全量受版本控制 Python 测试 `1354 passed, 1 skipped`。Ruff（关键变更文件）、compileall 和 `git diff --check` 通过。
- 本轮增量验证：记忆过期/索引不完整及两条 dedupe 写入路径 `13 passed`，覆盖结构化 503、cause/trace 和未写入断言；Python 版本控制测试集全量为 `1347 passed, 1 skipped`。
- 总体完成度：约 95%（按 P0/P1/P2 交付权重估算；近期补齐 IntentEnvelope 本体边界、共享成功谓词、GUI 证据输入边界、反馈回放时钟、权限记忆默认隔离和召回 revision 追溯，但不代表 Windows/Linux 实机、公网连接器、签名技能生态或 24 小时驻留发布资格）。

### 2026-08-29 增量：直播执行与 Twitch 入站

- 直播动作现在采用 `preview -> confirm -> execute -> verify -> audit` 闭环；OBS WebSocket v5 只在显式执行时建立短连接，支持 `GetSceneList`、`SetCurrentProgramScene`、`StartStream`、`StopStream`、`GetCurrentProgramScene` 和 `GetStreamStatus`。
- 预览票据有效期 120 秒、参数和动作绑定、执行前原子消费；人工接管、未配置 OBS、过期/重放/篡改请求均 fail-closed；Provider 异常或验证不一致统一投影为 `unknown_effect`，不能用同一票据重试。
- Electron ToolPanel 已提供风险/参数确认、执行结果、验证状态和审计展示；未配置 OBS 时仍可生成预览，但不会误报为可执行。
- 新增 Twitch EventSub 入站验签、challenge 响应、通知去重和 `channel.chat.message`/`channel.follow`/`channel.subscribe` 归一化；新增 IRC 行解析入口。事件只进入本地队列，当前没有 Twitch 出站动作。
- 新增接口：`POST /api/system/stream/execute`、`POST /api/system/stream/twitch/eventsub`、`POST /api/system/stream/twitch/irc`。Twitch EventSub 使用 `YUIZAKI_TWITCH_EVENTSUB_SECRET`，密钥不进入快照。
- 验证：OBS fake adapter 执行/验证/重放/未知效果回归通过；Twitch 签名、过期、重复、challenge、IRC 和路由注册回归通过；Python 编译/Ruff、Electron type-check/lint、`git diff --check` 通过。
- 主动陪伴策略对 `proactive_budget` 和 persona `energy` 增加有限数值校验；损坏、非有限或越界输入会抑制主动触达而不会让 Heartbeat 任务崩溃。
- Twitch EventSub 精确加入公网 webhook 鉴权例外，仍由 Twitch HMAC 验签保护；IRC 入站路径继续要求 Yuizaki backend token，避免把本地桥接入口公开到公网。
- S0 直播审计增量：`StreamRuntime` 新增 `stream_actions.json`（`yuizaki.stream-actions.v1`），在外部 provider 调用前持久化 `sending`，成功写入 `known_success`，异常或验证不一致写入 `unknown_effect`；进程重启恢复 `lastAction`，新增 `GET /api/system/stream/actions`，并在 ToolPanel 展示脱敏历史。动作历史不保存参数、返回正文、Token 或凭据；未知效果仍不可自动重试。
- S0 验证：直播动作/草稿定向测试 `9 passed`，Electron type-check、lint，Python Ruff/compile 和文档校验均通过；尚未宣称真实 Twitch/OBS 账号或跨平台设备资格。
- S4 基础增量：新增 `TwitchConnectionSupervisor`，将 Twitch IRC 的显式连接意图、`connecting/connected/backoff/stopped/unconfigured/revoked` 状态、指数退避和人工断开边界独立出来；`POST /api/system/stream/twitch/connect|disconnect|tick` 与 ToolPanel 状态展示已接入。当前仍未自动建立真实 socket，未配置 transport 时 fail-closed，后续再接入 staging IRC transport。
- S4 验证：连接状态机、退避恢复、撤销阻断、快照和路由测试通过；本地不触发 Twitch 网络连接。
- S4 transport 增量：`TwitchIrcTransport` 在显式连接后通过现有可选 `websocket-client` 发送 IRC `PASS/NICK/CAP/JOIN`，处理 `PING/PONG`、入站行和断线回调；频道与用户名由 `YUIZAKI_TWITCH_CHANNEL`/`YUIZAKI_TWITCH_USERNAME` 提供。没有完整配置或依赖时不建连。
- S4 transport 稳定性：识别 Twitch IRC `RECONNECT` 并触发退避；识别认证失败并停止自动重试，防止错误凭据造成无限连接循环。
- S1 语音舒适度增量：renderer 诊断上报增加卸载竞态门禁、同步 reporter 异常隔离，并在真实播放开始时记录 transcript/audio-free 的 `first_audio` comfort 样本；后端将 `first_audio` 作为延迟指标样本接收，但不把它加入五类行为场景覆盖门禁。实时语音源对空输入提交发出不含文本的 `empty-input` 事件并记录 `empty_asr`。新增 `comfort-signal` 事件、`POST /api/system/voice-diagnostics/comfort-signal`、独立持久化摘要及 Overview 只读覆盖提示，严格接受 `hesitation`/`backchannel`/`background_speech` 及显式 VAD/classifier 来源；当前仍没有生产分类器，缺失事件不会被猜测。
- S1 语音诊断增量：`RealtimeVoiceEventBridge` 新增 transcript/audio-free 的有界 comfort 聚合（按 signal/source 计数、confidence/duration p50/p95），只统计显式 provider/local VAD/classifier 事件；非法样本被丢弃，聚合不会从 RMS 或普通语音边界推断语义。
- S1 状态机回归增量：新增无公网/无真实麦克风的 WebRTC fake harness，验证连续模式下短于 160ms 的 VAD 候选不打断输出，持续候选才发送取消/清空输出并回到录音态；同时验证空 ASR 不生成 turn、被打断 turn 的延迟 commit/error 不污染新 turn。这只证明状态机契约，不替代真实设备的声学舒适度和长时 soak。
- S1 本地设备反馈增量：`AudioCapture` 增加 `unknown/silent/active/disconnected` 输入健康状态；连续 1.8 秒低能量显示“暂未检测到声音”，音轨 `ended` 停止发送并进入错误态，ChatVoiceStatus 展示对应状态。该判定只使用有界 RMS/MediaStreamTrack 状态，不推断 hesitation、background speech 等语义。
- S1 语音恢复入口增量：实时语音状态同步到 ChatStore；当即时语音进入 `error/closed` 且没有录音或播放时，ChatVoiceStatus 提供用户主动“重连语音”按钮，通过事件桥重建会话。该恢复不会自动循环重连，也不会覆盖本地语音或文字链路；策略由纯函数测试锁定。
- S1 语音舒适度边界增量：`useVoiceConversationBridge` 对 `comfort-signal` 应用 workspace/session/interruption epoch 门禁，重连、抢话或关闭后的延迟信号不会污染当前诊断；新增事件桥 detach、诊断有界保留、reporter 异常隔离和版本化 turn 身份回归测试。
- S4 直播链路增量：Twitch EventSub/IRC 事件已经验签、解析、去重并持久化到本地队列；新增 `POST /api/system/stream/drafts/consume` 有界消费接口，并接入可显式启用/暂停、单飞、human-takeover 门控和重启恢复的 `StreamDraftConsumer`。前端治理面板可查看/切换消费者，自动路径只生成本地 Agent 草稿，复用同一幂等 `TurnService`，不会触发 Twitch/OBS 出站动作。
- S4 EventSub 订阅计划增量：新增 `subscriptionPlan` 本地契约和 `PUT /api/system/stream/twitch/subscriptions`，支持聊天、关注、订阅三类事件的有序选择、持久化和前端展示；默认仍是 `management=local_only`、`active=[]`、`remoteSyncAvailable=false`，保存计划不会调用 Twitch API。注入 `TwitchSubscriptionProvider` 后，`stream.twitch_subscriptions_sync` 纳入统一 `preview -> confirm -> execute -> verify -> audit` 闭环，提供本地 `in-memory-staging` provider、创建/删除差异预览、幂等同步、失败 `unknown_effect` 和安全 active 元数据恢复。
- S4 Twitch Helix Provider 增量：新增显式关闭的 `TwitchHelixSubscriptionProvider`，支持 EventSub 订阅查询、创建和删除；只有设置 `YUIZAKI_TWITCH_SUBSCRIPTION_PROVIDER=helix` 且提供 HTTPS callback、client ID、EventSub token、broadcaster/moderator ID 和 webhook secret 时才注入，单次 HTTP 请求不自动重试，凭据不进入快照或结果元数据。真实账号、公网 webhook、平台审核和回滚仍需 staging 目标机验收。
- S4 直播治理增量：新增本地 `StreamModerationPolicy`，对 `stream.chat_send` 在预览和执行阶段执行敏感词、慢模式和每分钟频率门禁；策略独立持久化并通过 `GET/PATCH /api/system/stream/moderation` 和 ToolPanel 暴露。执行 claim 在锁内重新校验，重复并发票据不会触发第二次平台调用；治理拒绝不会产生外部副作用。
- S4 Twitch 配置闭环增量：Electron ToolPanel 新增 Twitch 凭据配置入口，凭据通过 `ProviderCredentialStore` 使用操作系统安全存储，保存后经 `PUT /api/system/stream/twitch/config` 在 Python 运行时内存重配置 IRC/EventSub/聊天适配器；响应只返回 configured 状态，不回显 Token，不自动连接或发言。清除配置会停止 IRC 重连意图；Helix 配置不完整时在任何状态变更前 fail-closed。
- S4 Twitch 只读准备度检查：新增 `POST /api/system/stream/twitch/probe`，只汇总 EventSub、聊天、IRC 和订阅管理配置状态，不建立网络连接、不执行外部副作用；保存配置后 ToolPanel 自动执行该检查。
- S4 Twitch 配置验证：新增运行时重配置、凭据不回显、Helix 不完整配置不变更和路由暴露回归；本轮 Twitch 定向测试 `11 passed`，Python compileall/Ruff、Electron type-check/lint 通过。真实 Twitch OAuth、staging 账号、公网回调和跨平台资格仍未宣称完成。
- 2026-08-30 S4 本地 staging 回放：新增 `scripts/stream_staging_check.py` 与 `python/tests/test_stream_staging_check.py`，用内存 OBS/Twitch provider 回放字幕草稿、OBS 场景切换验证、`unknown_effect` 终态与不可重放、human takeover、订阅同步和动作审计重启恢复；输出 `yuizaki.stream-staging-evaluation.v1`，明确 `networkAccess=false`、`realProviders=false`，不替代真实账号资格。
- 2026-08-30 连接器 staging 回放：新增 `scripts/connector_staging_check.py` 与 `python/tests/test_connector_staging_check.py`，通过 ASGI 路由和临时 SQLite 回放 Telegram/Discord 签名校验、durable enqueue、Agent 回复、重复事件幂等、错误密钥拒绝，以及 provider 失败后的显式人工重投；输出 `yuizaki.connector-staging-evaluation.v1`，明确 `networkAccess=false`、`realProviders=false`，不替代公网 webhook 或真实账号验收。
- 2026-08-30 连接器未知效果收敛：新增 `POST /api/system/connectors/{connector_id}/events/{event_id}/resolve`，仅允许无活动任务且 lease 已过期的 `sending` 记录由用户明确标记 `delivered` 或 `failed`；非法 lease 元数据 fail-closed，重复标记已送达幂等，不触发新 Agent turn 或自动重发。Electron Agent Governance 面板提供确认入口。
- 2026-08-30 语音舒适度回放：新增 `scripts/voice_comfort_check.py` 与 `python/tests/test_voice_comfort_check.py`，回放打断/首音频/空 ASR/连续 turn 完成率、显式 VAD 信号、缺数据 fail-closed 和 run 轮换清理；输出 `yuizaki.voice-comfort-evaluation.v1`，明确 `networkAccess=false`、`realDevice=false`，不替代真实麦克风、扬声器、回声消除或长驻留验收。
- S4 直播草稿恢复增量：失败草稿现在支持显式 `retry=true` 人工重新生成；默认请求继续幂等，已生成草稿不可覆盖，自动消费者不会重试失败草稿。ToolPanel 对失败草稿展示“重新生成”，并保持本地草稿路径无平台出站副作用；新增失败→显式重试回归。
- 2026-08-30 本地回归：修复 Electron `ProviderCredentialStore` 的 `subscriptionProvider` 索引访问类型错误；新增清除 Twitch 聊天凭据后强制进入 `unconfigured + desired=false` 的回归。历史定向快照为 Python `104 passed`、renderer 语音/恢复/主动反馈 `26 passed`，Electron type-check、lint、renderer/electron build 均通过；当前 Python 全量回归为 `131 passed`。
- 2026-08-30 资格核验：`scripts/platform_release_check.py --target-platform windows` 正确返回 `not_qualified`，原因包括缺少平台 attestation、缺少 24 小时 soak、desktop/text_voice 未达到 `available`；该结果仅说明发布门禁生效，不是设备能力证明。
- 2026-08-30 当前回归快照：仓库现存 Python 测试 `131 passed`；新增 memory replay 独立测试 `3 passed`，连接器 staging 回放 `4/4`，Ruff、compileall、`git diff --check` 和 Markdown 校验通过。工作树仍含用户既有的大量删除/修改，以上仅描述本轮新增路径的验证。
- 2026-08-30 CI 门禁增量：`.github/workflows/ci.yml` 新增 `python-contracts` job，安装 Linux core lock 后执行 deterministic memory replay，并运行主动陪伴、直播草稿/审核、连接器 probe 契约测试；该 job 不访问真实账号、不建立公网连接。目标机音频、Twitch OAuth、公网 webhook 和 24 小时驻留仍由 staging/release 门禁负责。
- 2026-08-30 S1 舒适度增量：语音面板的停止按钮不再只在 TTS 已出声后可用；实时响应处于 `responding/interrupting` 时也允许用户立即中断，且空闲/错误状态保持禁用。新增 `shouldOfferRealtimeInterrupt` 纯策略和回归测试，仍复用既有 interruption epoch/unknown-effect 约束，不增加自动重连。
- 2026-08-30 S1 诊断一致性增量：`RealtimeVoiceEventBridge` 现在对同一事件只建立一次底层订阅，再向多个监听器分发；诊断/comfort 样本不会因组件注册多个 listener 而重复计数。新增多监听器回归，detach 仍会清理全部订阅。
- 2026-08-30 S1 run 生命周期增量：新增 `POST /api/system/voice-diagnostics/run`，renderer 在挂载、工作区/会话切换和语音配置变化时启动隔离 run；诊断样本在事件发生时固定 `runId`，并携带 realtime scope，旧会话的延迟回调会被后端 stale-run 校验或前端 scope 门禁丢弃。该改动只改善本地统计隔离，不等同于真实设备舒适度资格。
- 2026-08-30 S1 资格可见性增量：`/api/system/voice-diagnostics` 和 Overview 现在展示脱敏的 `qualification`/`release_gate` 摘要、阶段缺口和恢复统计；不返回 provenance 或设备标识，也不改变真实设备 attestation 与 24 小时驻留的 fail-closed 门禁。
- 2026-08-30 S3 评测增量：新增 `python/modules/agent/proactive_evaluation.py` 与 `yuizaki.proactive-evaluation.v1`，在临时 SQLite 中重建脱敏场景，复用线上 `ActivityFrameStore.evaluate()` 验证 `allowed/reason`、暂停、忽略反馈、每日预算和冷却门禁；不调用 LLM、调度器或外部连接器。新增延后、来源关闭、类别预算、冷却过期场景，并支持断言剩余预算。
- 2026-08-30 S3 CLI 增量：新增 `scripts/proactive_policy_check.py` 与 `python/evals/fixtures/proactive_policy.json`；固定时间回放 11 个脱敏场景，输出 `yuizaki.proactive-evaluation.v1` 报告，全部通过时退出码为 `0`，任一策略不匹配时退出码为 `2`。
- 2026-08-30 S3 评测时钟修复：主动陪伴 CLI 未指定 `--now` 时从 fixture 的最早 `frame.sourceCreatedAt` 推导确定性回放时钟，避免墙上时间推进后冷却/预算案例漂移；显式 `--now` 仍可用于定点回放。
- 2026-08-30 S3 生命周期回归：补充 `cancelled` 反馈对 pending opportunity 的围栏，以及 SQLite 关闭/重开后的状态检查；取消后的机会不会再次出现在 pending 列表，反馈记录仍可审计回放。Python `tests` 目录全量回归为 `117 passed`。
- 2026-08-30 S5 记忆评测闭环：新增 `python/evals/fixtures/memory_retrieval.json`、`scripts/memory_retrieval_check.py` 和 `python/tests/test_memory_evaluation.py`。回放使用真实 `RetrievalPipeline`/`VectorStore`，注入确定性 embedding，零网络、零 LLM；6 个脱敏案例覆盖 memory role、workspace scope、过期/删除生命周期、tool permission review-only、关系 evidence ID 和 missing-premise abstention。输出 schema 为 `yuizaki.memory-evaluation.v1`，失败退出码为 `2`，当前本地回放 6/6 通过。该证据只证明本地契约与回放，不代表真实长期对话集、embedding/reranker 或敏感记忆泄漏率已验证。

## 不纳入当前迭代

- 默认持续录屏/摄像头历史。
- 未经沙箱和 verifier 的鼠标键盘自治。
- 未经真实目标机、第三方平台 staging 或长期用户数据集验证的能力，不得写成“已完成”。
- 复杂 temporal graph 或多租户公网服务。
- 在留存和付费假设验证前建设大规模角色市场。

## 2026-08-29 产品化路线图（陪伴型功能 Agent）

本节把“已能运行”和“可对外承诺”分开。时间按单个小团队、优先单用户桌面版估算；外部平台审核、公网部署和真实设备资格会改变日历，不改变阶段依赖。

### 能力基线

| 能力面 | 当前仓库状态 | 下一道门禁 |
|---|---|---|
| 对话与任务 | `TurnService` 统一文字、HTTP、heartbeat、语音入口；工具结果有 `known_success/unknown_effect` | 长任务恢复、取消和回放压力测试 |
| 语音与桌宠 | Electron 音频捕获/播放、ASR/TTS、Live2D/VRM、延迟诊断；comfort signal 记录入口；运行设置可调 VAD 抢话灵敏度 | Windows/Linux 真实设备的首包、打断、回声和 30 分钟稳定性证据 |
| 记忆 | SQLite 权威源；`memory_role`、候选审核、删除/导出、索引 revision 和 provenance | 长期对话集上的召回准确率、敏感事实泄漏率、用户纠错闭环 |
| 主动陪伴 | heartbeat、安静时段、类别预算、接受/忽略/取消/延后反馈、原因码 | 明确拒绝后的再次触达率为 0；打扰率、接受率和延后率可回放 |
| 外部连接器 | Telegram、Discord、QQ/微信个人兼容桥的入站、持久化投递、重试/取消和恢复遥测 | 公网 webhook、真实账号桥接、凭据托管和平台审核 |
| 直播 | OBS 预览/确认/执行/验证；Twitch EventSub/IRC 入站；Twitch 聊天发送需显式确认；本地敏感词、慢模式和频率门禁 | 长连接状态机、动作审计持久化、真实 staging 账号 |
| MCP/插件/技能 | 能力快照、manifest/trust、目录与执行分离、前端治理 | 签名发行、撤销/轮换、第三方沙箱和回滚 |
| GUI Agent | 沙箱 attestation、步骤证据和 verifier 契约 | 真 VM/容器执行器、跨平台任务集、人工接管 |

### 分阶段交付

| 阶段 | 周期 | 必须交付 | 依赖与停止条件 |
|---|---:|---|---|
| S0 可靠性封板 | 0-2 周 | 持久化 `stream_actions`（`sending/known_success/unknown_effect/failed`）；连接器恢复扫描；语音 comfort 数据落盘；补齐应用重启后的状态恢复 | 不接真实外部账号。任一未知效果自动重试或凭据泄漏即停止发布 |
| S1 实时语音 MVP | 2-6 周 | 全双工会话状态机（listen/speak/interrupted）；barge-in；设备选择；首包/端到端延迟面板；降级到文字；30 分钟 soak | 需真实 Windows/Linux 设备。目标：首个音频 p95 < 800 ms，打断停止 p95 < 250 ms；失败自动回文字 |
| S2 连接器 Beta | 4-8 周 | Telegram/Discord 官方 webhook；QQ/微信仅兼容桥；安全凭据存储；公网反向代理说明；delivery history、重投和人工取消 UI | 先 staging workspace；重复 webhook 不重复生成 turn；`sending/unknown_effect` 不自动重发 |
| S3 主动陪伴 Beta | 6-12 周 | 场景采集（请求级、敏感应用屏蔽）；机会评分；安静时段和每日预算；snooze/拒绝记忆；“为什么现在联系我”解释 | 以离线回放评测为先。明确拒绝后再次触达率必须为 0；高风险情绪/依赖话术进入安全红队 |
| S4 直播工作室 | 3-6 月 | Twitch EventSub/IRC 长连接与指数退避；OBS profile/scene 管理；聊天草稿→确认→发送；慢模式、敏感词和人工接管；动作审计历史 | 只有 staging 账号可发送。每个外部动作有 receipt、结果验证和不可重试 unknown effect；撤销后必须停发 |
| S5 记忆与技能生态 | 4-8 月 | query-aware 召回预算；事实/关系/任务经验/反思/技能分层；技能签名、版本、撤销和权限声明；导入/删除/回滚 | 生产密钥托管和第三方审核未就绪前保持 catalog-only；敏感记忆默认 review-only |
| S6 隔离式桌面操作 | 6-12 月 | 独立 VM/容器；observe-think-act；每步截图/前后状态/verifier；暂停、接管、恢复；OSWorld 风格回归 | 主机不可越权且资源可清理；未达到任务成功率和 unknown-effect 预算不开放主机操作 |
| S7 规模化与游戏（后置） | 12 月后 | 多用户/云端会话、角色市场、游戏内陪伴（Minecraft 等） | 只有 S1-S6 的安全、留存和成本数据稳定后立项；游戏不阻塞前述路线 |

### 外部连接器如何使用

前端已经暴露入口：`Agent Governance` 面板中的 Telegram、Discord、QQ、微信标签页。对应客户端封装在 `electron/src/renderer/api/clients/system-client.ts`，后端路由在 `python/routes/connector_api.py`。

1. Telegram/Discord：在面板填 Bot Token；Telegram 还填 Webhook Secret，Discord 填 64 位 Public Key，打开启用开关并保存。把面板显示的 `/api/system/connectors/{id}/webhook` 配到平台的 HTTPS webhook；平台到达后由后端验签、去重、生成 canonical turn，并先持久化 delivery 再回复。
2. QQ/微信：只支持用户自行运行的个人账号兼容桥。在面板填 `bridgeUrl`、桥协议（QQ 可选 OneBot 11/12）和 bridge token，点击“开始登录”，确认状态为已连接后再启用。桥掉线、封号和协议变化不由 Yuizaki 保证。
3. 运维：面板的“最近事件”查看 `processing/delivered/failed/sending/unknown_effect`；可对明确可重试的失败执行“重投”，可取消仍未发送的事件。`sending` 或 `unknown_effect` 必须人工确认实际效果后处理。
4. 当前边界：连接器是入站消息→Agent 回复→平台出站的实验性链路，不等于公网 SaaS；反向代理、TLS、平台 webhook 注册和账号风控仍由部署者负责。Token 不应出现在普通 JSON、日志、快照或草稿中。

Twitch EventSub 订阅同步默认关闭。仅在本地验证治理流程时设置 `YUIZAKI_TWITCH_SUBSCRIPTION_PROVIDER=in-memory-staging`；此 provider 不联网，只模拟创建/删除，前端 ToolPanel 才会显示 `stream.twitch_subscriptions_sync`。真实 OAuth/Twitch provider 接入前，不要把该开关当作公网连接能力。

### 参考项目（用于架构借鉴，不代表成熟度背书）

| 项目 | 可借鉴部分 | 不直接照搬的部分 |
|---|---|---|
| [AIRI](https://github.com/moeru-ai/airi) | 桌宠、Live2D/VRM、语音和多模态陪伴形态 | 其插件/模型组合不能替代 Yuizaki 的权限和终态验证 |
| [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber) | 本地模型、ASR/TTS、Live2D/VRM 的端到端参考 | 不把 demo 级实时性当作设备资格证据 |
| [LiveClaw](https://github.com/maumcrez-svg/liveclaw) | Studio、OBS、MediaMTX、聊天、TTS、heartbeat 的直播平台切分 | 外部出站仍需 Yuizaki 的 preview/confirm/audit |
| [wadebot](https://github.com/WadeWagmi/wadebot) | VTuber 化 Agent、REST/WebSocket、多 Agent overlay | 不复制其凭据和平台耦合方式 |
| [Nekro Agent](https://github.com/KroMiose/nekro-agent) | 中文多平台、B 站直播、MCP、长期记忆和事件流组合 | QQ/微信个人桥的合规、稳定性必须单独评估 |
| [HermesCraft](https://github.com/bigph00t/hermescraft) | Minecraft 持久 persona、独立记忆、视觉和多 Agent 协作原型 | 仅作为 S7 游戏阶段的设计参考，不进入当前依赖图；社区原型，不作成熟度背书 |
| [OBS WebSocket](https://github.com/obsproject/obs-websocket) | OBS v5 请求/事件协议和 profile/scene 操作 | 只在显式用户确认后执行不可逆动作 |
| [LiveKit Agents](https://github.com/livekit/agents) / [Pipecat](https://github.com/pipecat-ai/pipecat) | 全双工音频管线、transport、interrupt 和观测 | 当前仓库先复用既有音频抽象，不为框架名义引入依赖 |
| [LangGraph](https://github.com/langchain-ai/langgraph) | checkpoint、pending writes、human-in-the-loop、durable execution | 保持 SQLite/TurnStore 为权威，不引入第二套状态源 |
| [OpenHands](https://github.com/All-Hands-AI/OpenHands) / [OSWorld](https://github.com/xlang-ai/OSWorld) / [Microsoft Fara](https://github.com/microsoft/fara) | 沙箱、环境/求解器/verifier、跨平台 GUI 任务和资源清理 | 只用于 S6 隔离验证，不开放主机自治 |

### 2026 论文阅读清单与对应决策

以下链接为 2026 年 arXiv/CVPR 页面；论文结论只用于设计假设，不能替代 Yuizaki 自己的评测。

| 资料 | 影响的设计决策 |
|---|---|
| [GraphMemix (arXiv:2608.26983)](https://arxiv.org/abs/2608.26983) | 记忆召回使用 evidence forest、关系验证和预算；保留 evidence ID、revision 和 incomplete 状态 |
| [VoiceChat-TTS (arXiv:2608.13831)](https://arxiv.org/abs/2608.13831) | 评估对话式 TTS 的响应速度、韵律和可打断性；S1 不能只看 MOS |
| [Agentic-DuplexGen (arXiv:2608.16053)](https://arxiv.org/abs/2608.16053) / [DuplexWorld (arXiv:2608.10716)](https://arxiv.org/abs/2608.10716) | 全双工 turn-taking、抢话和并行感知；需要明确 session 状态机和取消语义 |
| [StreamAvatar (CVPR 2026)](https://openaccess.thecvf.com/content/CVPR2026/html/Sun_StreamAvatar_Streaming_Diffusion_Models_for_Real-Time_Interactive_Human_Avatars_CVPR2026_paper.html) | 直播 avatar 的分块生成和实时约束；先以 Live2D/VRM 稳定性为门禁，再评估生成式 avatar |
| [Proactive Agents Workshop (CHIIR 2026)](https://arxiv.org/abs/2608.18638) | 主动行为应适时、透明、可争议并符合用户目标；预算、安静时段和解释不可省略 |
| [CompanionHarm (arXiv:2608.25377)](https://arxiv.org/abs/2608.25377) / [Persona-Grounded Safety (arXiv:2605.00227)](https://arxiv.org/abs/2605.00227) | 红队覆盖依赖、操控、危机和 persona 越界；关系记忆与安全策略分离 |
| [Tap-to-Adapt (arXiv:2603.14449)](https://arxiv.org/abs/2603.14449) | 将接受、忽略、取消、延后作为时机反馈，而非直接改写权限 |
| [CUADesignSpace (arXiv:2602.07283)](https://arxiv.org/abs/2602.07283) / [CUADebug (arXiv:2608.02643)](https://arxiv.org/abs/2608.02643) | GUI 操作需要解释、接管、根因分类和重执行证据 |
| [Universal Verifier (arXiv:2604.06240)](https://arxiv.org/abs/2604.06240) | 过程验证与结果验证分离；现实效果不确定时保留 `unknown_effect` |
| [SPA (arXiv:2608.27234)](https://arxiv.org/abs/2608.27234) / [SARA (arXiv:2608.27146)](https://arxiv.org/abs/2608.27146) | 持久 Agent 的 artifact 需要 confidentiality/integrity/provenance；历史和工具输出不能晋升为新权限 |

S7 游戏后置资料： [GameWAM (arXiv:2608.26200)](https://arxiv.org/abs/2608.26200)（短规划→执行→再观测）、[The Latent Bridge (arXiv:2606.24470)](https://arxiv.org/abs/2606.24470)（快反应/慢推理双速循环）、[OmniGameArena (arXiv:2606.09826)](https://arxiv.org/abs/2606.09826)（多轮技能反思评测）、[HermesCraft](https://github.com/bigph00t/hermescraft)（独立 persona/记忆与 Minecraft 身体）。这些是预印本、benchmark 或社区原型，不能作为当前产品能力承诺。

### 2026-08-30 补充资料与证据边界

以下资料用于补足长期陪伴、关系安全和 GUI 感知设计。2608.* 论文按 2026-08-30 检索日记录，引用时应固定 arXiv 版本；预印本实验指标不能外推为 Yuizaki 的生产 SLA、心理疗效或通用游戏能力。社区项目的 README、star 和提交记录只是活动信号。

| 资料 | 可借鉴点 | 证据边界 |
|---|---|---|
| [Mem0](https://arxiv.org/abs/2504.19413) / [MIRIX](https://arxiv.org/abs/2507.07957) / [ZifaMem](https://arxiv.org/abs/2607.17564) | 动态记忆巩固、情节/语义/程序记忆分层、用户模型和 persona 连续性评测 | 论文数据集和 LLM-as-judge 结果需用本仓库的长期对话集复现；屏幕记忆默认仍需用户授权 |
| [CompanionHarm](https://arxiv.org/abs/2608.25377) / [ANCHOR](https://arxiv.org/abs/2607.28818) | 多轮依赖、操控、persona 漂移和轨迹回忆红队 | Replika/审计语料不代表所有用户或语言，不能替代人工安全审查 |
| [Playing Games with My Heart](https://arxiv.org/abs/2605.08093) | 检查暗黑模式、拟人化、色情和等级激励，形成关系安全检查表 | 小样本应用审计是风险信号，不是行业因果结论 |
| [ComBodied Agents](https://arxiv.org/abs/2608.10915) | 事件感知→可纠正记忆→个人世界模型；干预受同意、不确定度、可逆性约束 | 概念框架，尚无可直接部署的实现或产品验证 |
| [Microsoft OmniParser](https://github.com/microsoft/OmniParser) | GUI 屏幕结构化解析，可作为 S6 perception 层 | 只解决解析，不提供规划、授权、验证或沙箱 |
| [STS2MCP](https://github.com/Gennadiyev/STS2MCP) / [STS2-Agent](https://github.com/CharTyr/STS2-Agent) | 通过游戏 mod/HTTP 暴露结构化状态与动作，再包装为 MCP | 单游戏、版本绑定的社区方案；不进入 S0-S6 依赖 |

### 统一验收面板

- 可靠性：turn/connector/stream 在崩溃、重启、重复 webhook、超时和取消下可回放；未知效果不自动重试。
- 实时性：语音首包、端到端响应、barge-in 停止、TTS underrun、avatar 帧率分别采样 p50/p95/p99。
- 陪伴质量：主动触达接受率、忽略率、延后率、取消率、打扰率；明确拒绝后再次触达率为 0。
- 记忆质量：事实召回 precision/recall、过期/删除生效时间、敏感角色泄漏率、provenance 完整率。
- 安全：高风险动作确认率、人工接管成功率、越权/凭据泄漏红队、依赖和危机话术处置。
- 成本：每小时音频/推理/转码费用、CPU/GPU/RAM、外部平台限流和失败重试预算。

发布策略固定为 `dogfood -> staging -> 受邀 beta -> 公测`；每阶段只放开已通过门禁的能力。游戏保持后置，不进入 S0-S6 的依赖图。
