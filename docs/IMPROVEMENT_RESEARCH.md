# 2026 研究与同类项目参考

本文记录本轮设计与工程决策使用的外部依据。论文中的实验结果不外推为 Yuizaki 的结果，
Yuizaki 的性能结论仍以目标设备实测为准。

## 2026 研究资料

| 资料 | 核验结论 | 对本仓库的决策 |
|---|---|---|
| Peters, Khatoonabadi, Shihab, *Evaluating the Use of LLMs for Automated DOM-Level Resolution of Web Performance Issues*, MSR 2026, <https://arxiv.org/abs/2601.05502> | 自动 DOM 修改可降低部分 Lighthouse 问题，但会引入 visual stability 回归。 | 性能改动必须同时记录构建指标、LCP/请求 p95 和截图/布局回归，不能只看 bundle 或 Lighthouse 分数。 |
| Umar, Tripathi, *Experimental Analysis of Server-Side Caching for Web Performance*, 2026, <https://arxiv.org/abs/2602.06074> | 有界缓存可降低重复只读请求延迟，但缓存边界决定一致性风险。 | 只考虑能力摘要等幂等元数据缓存，不缓存记忆、权限、turn commit 或流式终态。 |
| Ma et al., *Negotiating Digital Identities with AI Companions*, CHI 2026, <https://doi.org/10.1145/3772318.3791473> | 伴侣身份与用户关系会被持续协商和重新解释。 | persona 与记忆编辑要显式、可追溯，不能让 UI 静默改写身份或关系状态。 |
| Anthis et al., *CompanionSim*, AIES 2026 accepted, <https://arxiv.org/abs/2609.00250> | 研究评估拟人化与信任变化，提醒产品行为不应依赖情感压力。 | 保留安静时段、暂停、降频和可解释主动行为；状态文案描述可观察事实。 |
| Zhang et al., *CompanionHarm*, 2026, <https://arxiv.org/abs/2608.25377> | 多轮上下文对伴侣风险检测有帮助，但严重度与关系边界仍难稳定判断。 | 主界面提供纠正、停止召回、暂停和升级路径，不把本地分类器当成最终裁决。 |
| Venkit et al., *ANCHOR: Best Friends, Not Forever*, 2026, <https://arxiv.org/abs/2607.28818> | 长程 persona/trajectory 评估存在明显漂移与低准确率。 | 继续分离 raw event、derived memory、profile 和 search projection，并分别做回归指标。 |

## 同类项目借鉴

| 项目 | 类型与可核验实践 | Yuizaki 的借鉴边界 |
|---|---|---|
| [Open WebUI](https://github.com/open-webui/open-webui) | 开源、自托管、provider/tool 扩展、持久记忆和权限控制面；参考 commit `0a7c15832fb30b1903753e83f81dc7d27e5b0944`。 | 让记忆拥有单一用户控制面，扩展能力留在 provider/tool 边界，不把诊断信息塞进聊天主流程。 |
| [Jan](https://github.com/janhq/jan) | 开源本地 AI 桌面应用、localhost OpenAI-compatible API、provider readiness；参考 commit `e2185dbc7db3a002da35b3688b57910ec6fd87b2`。 | 先呈现当前 provider/模型是否可用和直接恢复动作，再逐步展开诊断细节。 |
| [SillyTavern](https://github.com/SillyTavern/SillyTavern) | 开源角色/伴侣前端，角色设定和聊天流程分离，扩展按需启用；参考 commit `8172dcd0ee672d3cd9a5e5f7af134f91a45cd2b8`。 | persona 配置保持独立，聊天界面维持轻量；高级扩展通过设置/工具入口渐进披露。 |
| [Replika](https://my.replika.com/) | 商业 AI companion，对多轮关系安全研究有大量公开讨论。 | 仅作为多轮安全评估对象，不复制其交互或把关系承诺作为产品机制。 |

## 官方工程依据

- Electron process model：<https://www.electronjs.org/docs/latest/tutorial/process-model>，支持主进程/预加载/渲染器能力边界。
- Vue performance best practices：<https://vuejs.org/guide/best-practices/performance>，支持路由级拆包、减少无效更新和大列表虚拟化。
- Vite build guide：<https://vite.dev/guide/build>，支持保留现有 bundle audit 并对冷启动 chunk 做基线。
- WCAG 2.2 contrast minimum：<https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html>，普通文本目标对比度至少 4.5:1。

这些资料直接映射到本轮代码：HTTP timing 边界、renderer timing 事件、背景图不替换的遮罩提亮、focus-visible 和
reduced-motion，以及不改变记忆权威源的架构边界。
