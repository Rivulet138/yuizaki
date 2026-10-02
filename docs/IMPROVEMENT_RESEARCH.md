# 2026 研究与同类项目参考

本文记录本轮设计与工程决策使用的外部依据。论文中的实验结果不外推为 Yuizaki 的结果，
Yuizaki 的性能结论仍以目标设备实测为准。

## 2026 研究资料

| 资料 | 核验结论 | 对本仓库的决策 |
|---|---|---|
| Peters, Khatoonabadi, Shihab, *Evaluating the Use of LLMs for Automated DOM-Level Resolution of Web Performance Issues*, MSR 2026, <https://arxiv.org/abs/2601.05502> | 自动 DOM 修改可降低部分 Lighthouse 问题，但会引入 visual stability 回归。 | 性能改动必须同时记录构建指标、LCP/请求 p95 和截图/布局回归，不能只看 bundle 或 Lighthouse 分数。 |
| Umar, Tripathi, *Experimental Analysis of Server-Side Caching for Web Performance*, 2026, <https://arxiv.org/abs/2602.06074> | 有界缓存可降低重复只读请求延迟，但缓存边界决定一致性风险。 | 只考虑能力摘要等幂等元数据缓存，不缓存记忆、权限、turn commit 或流式终态。 |
| Ma et al., *Negotiating Digital Identities with AI Companions: Motivations, Strategies, and Emotional Outcomes*, CHI 2026, published 2026-04-13, <https://doi.org/10.1145/3772318.3791473> | DOI/Crossref 核验了题名、作者和出版元数据；具体行为结论需以 ACM 正文/摘要为准，不能只从 DOI 元数据推导。 | persona 与记忆编辑要显式、可追溯，不能让 UI 静默改写身份或关系状态。 |
| Anthis et al., *CompanionSim: Synthetic Data for Evaluating Anthropomorphism in Human-AI Relationships*, AIES 2026 accepted, v1 2026-08-31, <https://arxiv.org/abs/2609.00250> | 摘要报告 companionship behaviors 会降低 likability、humanlikeness 和 trust；这是预印本/会议录用资料，不是 Yuizaki 的产品结论。 | 保留安静时段、暂停、降频和可解释主动行为；状态文案描述可观察事实，不用情感压力换取留存。 |
| Zhang et al., *CompanionHarm*, 2026, <https://arxiv.org/abs/2608.25377> | 多轮上下文对伴侣风险检测有帮助，但严重度与关系边界仍难稳定判断。 | 主界面提供纠正、停止召回、暂停和升级路径，不把本地分类器当成最终裁决。 |
| Venkit et al., *Best Friends, Not Forever: Evaluating Long-Horizon Persona Collapse and Behavioral Drift in AI Companions*, v1 2026-07-30, <https://arxiv.org/abs/2607.28818> | “ANCHOR”是方法简称；摘要报告长程 trajectory accuracy 平均约 44.4%，不能外推为产品性能。 | 继续分离 raw event、derived memory、profile 和 search projection，并分别做回归指标。 |
| *State Without a Landlord*, 2026, <https://arxiv.org/abs/2609.17645> | 提议 append-only authenticated journal、single-writer epoch、closure certificate 和 executor succession；属于预印本架构建议。 | Agent recovery 需要 generation/epoch、fencing、结果证明和有界 payload；单独保存 ToolStep marker 不足以授权跨进程执行。 |
| *Bounded Loops*, 2026, <https://arxiv.org/abs/2609.27871> | 将全局 repair budget、独立 gate、终止证明和 hash-chained ledger 结合；实验结论仍需复核。 | 重试预算必须跨恢复闭包累计，policy gate 要独立于执行器，避免自我证明“已完成”。 |
| *Verified Detection and Prevention of Concurrency Anomalies in Multi-Agent LLM Systems*, 2026, <https://arxiv.org/abs/2606.17182> | 讨论 stale generation、phantom tool 和 effect reordering 等并发异常。 | 恢复记录绑定 generation、semantic fingerprint、tool registry revision，并让 Turn outbox 负责提交顺序。 |
| *Debugging the Debuggers: Failure-Anchored Structured Recovery for Software Engineering Agents*, v2 2026-06-05, <https://arxiv.org/abs/2605.08717> | PROBE 是方法名；预印本以 telemetry→diagnosis→bounded guidance 限制恢复建议。 | 只在证据充分且预算有界时生成恢复动作，失败诊断与执行授权分离。 |
| *GraphFlow: An Architecture for Formally Verifiable Visual Workflows Enabling Reliable Agentic AI Automation*, v1 2026-05-14, <https://arxiv.org/abs/2605.14968> | 摘要把 verified core 标为开发中，不能当成已证明的生产机制。 | 完整 typed plan、事件历史和 commit/outbox 应作为恢复权威，不能依赖进程内 `_resume_*` 状态。 |
| *Scope Before You Persist: Preventing Cross-Family Interference in Agent Memory*, v1 2026-09-24, <https://arxiv.org/abs/2609.29144> | 受控代码修复流实验支持先按任务族做 scope/certification；不是通用 companion 质量证明。 | workspace、companion、任务族和权限 scope 要进入 memory 写入与检索边界，拒绝全局向量污染。 |
| *Just-in-Time Memory: Learning to Curate Task-Adaptive Memory for LLM Agents*, v1 2026-09-23, <https://arxiv.org/abs/2609.27334> | 保留 raw trajectories，在读时按任务自适应整理；基准提升不能直接迁移到产品。 | SQLite 保留原始事件/Turn，derived memory 与 Qdrant projection 可重建。 |
| *EnSIMem: Entity-Structured Indexing for Long-Term Agent Memory*, v1 2026-09-23, <https://arxiv.org/abs/2609.27279> | entity-property 条目带 source turn 与时间 provenance；属于预印本。 | 记忆条目回链 turn/tool/result，支持纠正、删除传播和审计。 |
| *When Does Execution Provenance Help Agent Memory Retrieval?*, v1 2026-09-22, <https://arxiv.org/abs/2609.25913> | 工具参数/输出形成 source-aligned provenance units；离线 benchmark 结果不等于本地召回保证。 | 检索结果携带 provenance ID、authority revision 和 complete 标志，证据不完整时 fail-closed。 |
| *TWIST: A Proposed Benchmark for Intervention Quality in Conversational Memory*, v1 2026-09-23, <https://arxiv.org/abs/2609.28575> | proposed benchmark，关注 contradiction intervention、hard negatives 和敏感召回。 | P2 才加入纠正/拒绝过度干预评测，不阻塞基础可用性。 |
| *Where Does Exactly-Once Live? Model, Harness, and Tool-Contract Effects on Duplicate Side Effects in LLM Agents*, v1 2026-09-24, <https://arxiv.org/abs/2609.29095> | LIMBO 故障沙箱强调丢 ACK、迟到提交和重投递；工具 idempotency key 与 exactly-once 不是同一件事。 | 有副作用工具必须有 idempotency key、sending/unknown_effect 终态和人工核验，不能把重试当成功。 |
| *AkasicMEM: Governed Enterprise Memory for Agents*, v1 2026-09-22, <https://arxiv.org/abs/2609.25563> | 讨论 authorization continuity、transitive lineage 和 retrieval policy re-evaluation；属于架构/系统预印本。 | 记忆继承必须重新检查 workspace/角色/权限，不能只沿用旧向量或旧授权。 |
| *Security of Agent-Integrated Software: When Human Operations and Agent Actions Coexist*, v1 2026-09-19, <https://arxiv.org/abs/2609.23226> | 将 context misuse、authorization、execution control 和 effect integrity 作为系统级边界；属于预印本。 | MCP、插件、人工操作和 Agent 共用状态时，审批、provenance 与恢复状态要在同一策略面校验。 |
| *MemCalib: Benchmarking and Optimizing Memory Use in LLM Agents*, v2 2026-09-21, <https://arxiv.org/abs/2609.24259> | 评测过度使用与不足使用 memory；不能把 Recall 单指标当成长期记忆质量。 | 增加 memory influence、误用率、敏感召回和删除传播指标；排在 P1/P2。 |

## 同类项目借鉴

| 项目 | 类型与可核验实践 | Yuizaki 的借鉴边界 |
|---|---|---|
| [Open WebUI](https://github.com/open-webui/open-webui) | README 明确 Persistent Memory、SQLite/PostgreSQL、Qdrant 与离线/数据目录注意事项；固定提交只证明当时 README 内容，不证明整体质量。 | 让记忆拥有单一用户控制面，SQLite 权威与向量 projection 分离；启动页显示数据目录和离线状态。 |
| [Jan](https://github.com/janhq/jan) | README 明确本地模型、OpenAI-compatible localhost API、MCP 和 Windows 长路径诊断；固定提交不等于设备资格。 | 先呈现 provider/model readiness 和直接恢复动作，再展开诊断细节。 |
| [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber) | 固定 README 承认长期记忆暂移除，但保留聊天日志与未完成对话；不要把聊天恢复误称长期记忆。 | UI 显式区分 conversation replay 与 long-term memory readiness。 |
| [AIRI](https://github.com/moeru-ai/airi) | 2026 DevLog 标出 Memory 和插件仍 WIP，并同时支持浏览器/桌面与嵌入式 DB。 | 能力开关按运行环境展示，WIP 不进入默认可用入口。 |
| [SillyTavern](https://github.com/SillyTavern/SillyTavern) | 扩展/连接器生态丰富；其复杂入口只适合借鉴渐进披露，不复制大量入口。 | persona 与聊天分离，高级扩展集中在设置/工具入口。 |
| [Letta](https://github.com/letta-ai/letta) / [Mem0](https://github.com/mem0ai/mem0) | 分别强调 stateful agent state 与 User/Session/Agent 多级记忆、时间/来源字段；托管 benchmark 不能当本地质量证明。 | 运行时 callable/token 与持久记忆分开，scope、时间、来源和用户纠正可审计。 |
| [Replika](https://my.replika.com/) | 商业 AI companion，对多轮关系安全研究有大量公开讨论。 | 仅作为多轮安全评估对象，不复制其交互或把关系承诺作为产品机制。 |

固定版本的 README 证据：

- [Open-LLM-VTuber@992309c](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber/blob/992309c0aa19845960228f880013d4685fde93b5/README.md#L51-L79)：长期记忆暂移除，聊天日志和未完成对话仍可继续。
- [AIRI@7abffae](https://github.com/moeru-ai/airi/blob/7abffaee58984499fc25957f961939ad47f62873/README.md#L186-L245)：Memory/插件标为 WIP，并区分浏览器与桌面运行环境。
- [Jan@1cd96da](https://github.com/janhq/jan/blob/1cd96da93443c89c9f069f13a647dd9b6f8181e8/README.md#L92-L97)：本地模型、localhost OpenAI-compatible API、MCP 与平台诊断入口。
- [Open WebUI@8bd8b4f](https://github.com/open-webui/open-webui/blob/8bd8b4fac5e059578ac0c74b3c18d11139f88b7d/README.md#L32-L70)：Persistent Memory、SQLite/PostgreSQL、Qdrant 和离线模式；数据目录说明见 [L226-L231](https://github.com/open-webui/open-webui/blob/8bd8b4fac5e059578ac0c74b3c18d11139f88b7d/README.md#L226-L231)。
- [Letta@5bcdd17](https://github.com/letta-ai/letta/blob/5bcdd177d70fa2b31a754cfcd801e77b2e1ab16a/README.md#L3-L33) 与 [Mem0@94c3fe9](https://github.com/mem0ai/mem0/blob/94c3fe9f238f3dbf29c9ce98643bd71eb13077cd/README.md#L61-L78)：分别展示 stateful agent state 与多级记忆/时间字段的产品边界。
- [LangGraph@7daa3ab](https://github.com/langchain-ai/langgraph/blob/7daa3ab49d678a5da75edb08baa87db4a2be52c3/README.md#L39-L41)：将 durable execution、短期 checkpoint 和长期 store 分开；官方持久化文档是实现依据。

这些固定提交只证明引用时的 README 内容，不证明项目整体质量、运行资格或 Yuizaki 的性能。

## 官方工程依据

- Electron process model：<https://www.electronjs.org/docs/latest/tutorial/process-model>，支持主进程/预加载/渲染器能力边界。
- Vue performance best practices：<https://vuejs.org/guide/best-practices/performance>，支持路由级拆包、减少无效更新和大列表虚拟化。
- Vite build guide：<https://vite.dev/guide/build>，支持保留现有 bundle audit 并对冷启动 chunk 做基线。
- WCAG 2.2 contrast minimum：<https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html>，普通文本目标对比度至少 4.5:1。
- Temporal Workflows：<https://docs.temporal.io/workflows>，跨进程恢复依赖 deterministic replay Event History 与版本化，而不是恢复进程内内存。
- Restate durable execution：<https://docs.restate.dev>，完成步骤、定时器和外部事件写入 durable state，服务逻辑与失败机制分离。
- DBOS durable workflows：<https://docs.dbos.dev>，用数据库事务保存工作流状态，适合作为 SQLite authority + outbox 的对照实现。

这些资料直接映射到本轮代码：HTTP timing 边界、renderer timing 事件、背景图不替换的遮罩提亮、focus-visible 和
reduced-motion，以及不改变记忆权威源的架构边界。2026 年新增的 durable-workflow 资料只用于优先级和不变量设计；
它们大多是预印本或厂商文档，不构成 Yuizaki 的性能、安全或跨平台资格证明。
