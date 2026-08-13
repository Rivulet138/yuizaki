# Design principles / 设计原则

## Product shape / 产品形态

Yuizaki is a desktop companion first and a control panel second. The pet should remain visible and calm while chat, Agent work, and settings stay usable without competing for attention.

Yuizaki 首先是桌面陪伴，其次才是控制面板。桌宠应保持可见且平和，同时让聊天、Agent 工作和设置保持可用，彼此不争夺注意力。

## Interaction / 交互

- Keep chat input usable while a response or background Job runs.
- 在响应或后台 Job 运行期间，保持聊天输入可用。
- Represent explicit states: listening, thinking, executing, speaking, success, error, interrupted, and sleep.
- 明确表示 listening（聆听）、thinking（思考）、executing（执行）、speaking（说话）、success（成功）、error（错误）、interrupted（中断）和 sleep（休眠）状态。
- Show the current action and resulting artifact at the point of action; keep implementation diagnostics collapsible.
- 在操作发生处显示当前动作及其产物；实现诊断信息应可折叠。
- Keep provider, MCP, TTS, pet, and model controls in settings.
- 将 provider、MCP、TTS、桌宠和模型控制集中在设置中。
- Preserve session drafts, generation identity, unread completion, and cancellation semantics.
- 保留会话草稿、生成身份、未读完成状态和取消语义。
- Respect reduced motion and pause hidden-window rendering work.
- 尊重减少动态效果设置，并暂停隐藏窗口的渲染工作。

## Embodiment / 具身表现

The Agent emits intent-level commands such as `listen`, `think`, `speak`, gaze, expression, motion, and lip-sync. Live2D and VRM adapters own smoothing, TTL, fade, looping, and release timing. The LLM never emits frame-level animation instructions.

Agent 发出意图级命令，例如 `listen`、`think`、`speak`、注视、表情、动作和口型同步。Live2D 与 VRM 适配器负责平滑、TTL、淡入淡出、循环和释放时机。LLM 永远不会发出逐帧动画指令。

## Privacy and perception / 隐私与感知

Vision is an explicit one-shot capability. A request moves through `requested -> captured -> analyzed -> completed` or `discarded`; frames are released after the request and are not persisted by default.

视觉是显式的一次性能力。请求经过 `requested -> captured -> analyzed -> completed` 或 `discarded` 状态；请求完成后释放帧，默认不持久化。

## Performance / 性能

- Keep audio work off the UI thread where possible.
- 在可能的情况下，将音频工作移出 UI 线程。
- Coalesce pointer and progress events, but never drop terminal Job events.
- 合并指针和进度事件，但绝不丢弃 Job 终态事件。
- Cap device-pixel ratio and active/idle frame rates.
- 限制设备像素比以及活跃/空闲帧率。
- Pause hidden-window rendering.
- 暂停隐藏窗口的渲染。
- Use lazy model startup on constrained hardware.
- 在受限硬件上采用模型延迟启动。

## Failure behavior / 失败行为

Cancellation, interruption, stale results, provider errors, and missing assets are visible states. A slow tool or TTS segment must not freeze chat input. A missing optional provider should degrade the feature rather than silently fabricate a result.

取消、中断、过期结果、provider 错误和缺失资源都必须是可见状态。缓慢的工具或 TTS 片段不得冻结聊天输入。缺少可选 provider 时应降级功能，而不是静默伪造结果。
