# 产品 / Product

## 用户 / Users

Yuizaki 面向全天使用 AI 桌宠的人、本地 AI 用户，以及偶尔排查 Agent、语音、记忆或桌面集成问题的高级用户。主要流程是低注意力的短对话，只有需要处理问题时才进入配置和诊断。

Yuizaki serves people who keep an AI companion open throughout the day, local-AI users who want control over providers and stored data, and advanced users who inspect Agent, voice, memory, or desktop integration failures. The primary workflow is a sequence of short, low-attention conversations; deeper configuration is used when attention is needed.

## 产品目的 / Product purpose

Yuizaki 是本地优先的 AI 桌面 Agent，结合文字和语音对话、Live2D/VRM 形象、长期记忆、按请求感知、工具和桌面操作。成功标准是：桌宠随时可用但不打扰，完成的动作有可观察结果，失败时给出明确下一步，用户能检查并纠正影响后续行为的记忆和权限。

Yuizaki is a local-first AI desktop companion Agent combining text and voice conversation, Live2D or VRM embodiment, long-term memory, request-scoped perception, tools, and desktop actions. Success means the companion is available without demanding attention, completed actions have observable outcomes, failures provide a next step, and users can inspect or correct the memories and permissions that shape future behavior.

## 品牌性格 / Brand personality

平静、敏锐、可信。文案简洁具体；陪伴体验可以温和，但操作界面只描述可观察状态，不用人格化表达掩盖不确定性或失败。

Calm, observant, trustworthy. Copy is concise and specific. The companion can be warm, but operational surfaces describe observable state and never use personality to hide uncertainty or failure.

## 避免的方向 / Anti-references

- 重复展示同一健康状态的卡片式仪表盘。
- 频繁打断、抢夺焦点或利用关系压力促进使用的助手。
- 不展示结果或恢复路径、却声称已完成的黑箱 Agent。
- 暗示浏览器具备 Electron 专属窗口、设备或进程能力的体验。
- 将调试控制台作为默认桌宠界面。

- Card-heavy dashboards that repeat the same health state.
- Assistants that interrupt, steal focus, or use relationship pressure.
- Opaque agents that claim completion without showing the result or recovery path.
- Browser experiences that imply Electron-only capabilities.
- Debug consoles exposed as the default companion experience.

## 设计原则 / Design principles

1. 桌宠优先：聊天、语音、形象和即时反馈为主，诊断为辅。
2. 先处理例外：先展示最高优先级问题和下一步，再展示完整状态。
3. 渐进披露：常用操作保持可见，追踪、原始元数据和 Provider 详情按需展开。
4. 舒适自主：主动行为低频、非阻塞、可解释，并可延后或降低频率。
5. 诚实恢复：区分检查中、就绪、降级、失败和未知；可恢复失败必须有直接下一步。

1. Companion first: keep chat, voice, avatar, and immediate feedback primary.
2. Exceptions over inventories: show the highest-priority problem and next action first.
3. Progressive disclosure: keep common actions visible; expand traces and provider details on demand.
4. Comfortable autonomy: proactive behavior is low-frequency, non-blocking, explainable, and easy to postpone.
5. Honest recovery: distinguish checking, ready, degraded, failed, and unknown outcomes; every recoverable failure has a next step.

## 无障碍与包容 / Accessibility and inclusion

在 Electron 技术栈内以 WCAG 2.2 AA 为目标。所有控件可用键盘访问并有可见焦点；正文和占位文字满足对比度要求；状态不只通过颜色传达；紧凑布局在不依赖悬停的情况下保持可理解导航；动画遵循减少动态效果偏好。

Target WCAG 2.2 AA within the Electron stack. All controls are keyboard reachable with visible focus, text meets contrast requirements, state is not communicated by color alone, compact layouts remain understandable without hover, and animation respects reduced-motion preferences.
