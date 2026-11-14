# 前端面板修复二次复核（2026-11-11）

> 后续处理：本报告保留发现时的只读复核结论。对应修复及 2026-11-13 的最新验证见 [面板二次复核修复与验证](panel-review-fixes-2026-11-13.md)。

本次为只读复核，针对上一轮补丁、异步状态边界和验证方法排查剩余遗漏。未修改生产代码，仅新增复现脚本、结果和本报告。当前确认 13 项问题：2 项 P1、10 项 P2、1 项 P3。其中 12 项通过执行生产声明/实现并控制外部依赖复现；Infrastructure 的缓存生命周期问题为静态确认，实际多缓存实例行为尚未挂载验收。不能将本轮结论解释为已无其他问题。

上一轮单测、类型检查和构建通过的记录仍成立，但不足以推出所有面板功能已完整验收。特别是慢响应、并发操作、工作区切换及成功写入读回没有被原有检查充分覆盖。

## P1：优先修复

### 1. 主动设置请求未绑定工作区，可能写入另一个工作区

- 位置：`electron/src/shared/proactive.ts:318`、`electron/src/renderer/api/clients/proactive-client.ts`、`python/modules/system/runtime_endpoints.py:83`。
- 请求体仅携带 expectedRevision 和 patch，不携带 workspaceId；后端执行 PATCH 时读取全局 active workspace。`python/routes/system_api.py:333` 的处理函数在线程中执行，工作区切换与该执行之间没有绑定关系。单个工作区 revision 校验无法隔离两个 revision 相同的工作区。
- 复现：在 A 准备 expectedRevision=0、dnd=true 的请求，延迟执行端点；活动工作区变为 B 后放行。实际生产端点、服务和临时 SQLite 得到 A revision=0/dnd=false，B revision=1/dnd=true，响应 workspaceId=B。
- 证据边界：这是受控调度下真实端点闭包、服务、数据库的复现，没有启动 HTTP 服务，也没有声称用户数据已发生串写。
- 最小修复方向：请求显式携带并校验工作区身份，后端针对该工作区执行；响应仍需由前端操作上下文校验。仅丢弃旧前端回包不能撤销错误后端写入。
- 可重跑证据：`artifacts/panel-review-workspace-write-2026-11-11.py` 和同名 `.json`。数据库位于临时目录，执行后清理。

### 2. 聊天分支的迟到响应会抢回用户后选的会话

- 位置：`electron/src/renderer/stores/sessionStore.ts:96`、`electron/src/renderer/domains/chat/views/ChatPanel.vue:1475`。
- A 创建分支尚未返回，用户已选择 B 工作区的会话；A 返回后，store 无条件改变 activeSessionId，组件继续清空当前消息视图、切换上下文、替换路由。
- 动态结果：用户选择仍是 B 时，activeSession=a-branch、chatWorkspace=A，调用 router.replace('/w/A/chat/a-branch')。没有证据表明 B 的持久化消息被删除。
- 最小修复方向：创建分支与激活分支分离；调用方捕获选择代次和工作区，只有仍属于当前操作才激活。只给组件 await 后补检查不够，store 已提前改变全局选择。

## P2：功能、状态和等待问题

### 3. 主动反馈的迟到响应污染新工作区策略

`useProactiveControls.ts:187` 等待反馈后没有检查工作区或 generation；never_source 分支修改此刻的 settings。复现：A 发出反馈，切换并加载 B，A 成功返回后，B 的 sourceEnabled.completed_turn_followup 从 true 变 false。已证实前端状态串用；本场景没有证明后端 B 被持久化修改。应将回包提交绑定操作开始时的工作区/上下文版本。

### 4. 旧工作区删除失败可使新工作区进入失败状态

`useProactiveControls.ts:156` 的 deleteFrame 未绑定上下文；catch 无条件设置 policyClosed、loaded 和 error。复现：A 删除中切到 B，B 已成功加载，A 失败后 B 的 loaded 变 false、policyClosed 变 true，并显示 A 的错误。成功与失败分支都应做操作归属校验。

### 5. 后台读取会使正在保存的主动设置失效

`useProactiveControls.ts:77` 对 load/update 共用 requestGeneration，并且每次请求重置 saving；`useCompanionRuntimeBridge.ts:121` 的授权检查也调用 load。复现：保存 dnd=true 未返回时发起 load，读到旧 dnd=false 并清掉 saving；保存随后成功返回，被 generation 检查丢弃，前端 revision 和 dnd 仍为旧值。应区分读快照版本与写操作确认，读请求不得取消有效写确认。本场景未证明通知实际越过免打扰策略。

### 6. 主动记录删除失败后持续不可见，刷新无法恢复

`useProactiveControls.ts:157` 先将条目加入 hiddenFrameIds；失败没有撤销，load 也不清理该 ID，第 73 行始终过滤。复现：delete 返回 ok:false，随后成功 load 返回原条目，frames 长度 1 而 visibleFrames 长度 0。应在失败时撤销该次隐藏，补失败重试和刷新用例。

### 7. 可选反馈统计阻塞主动设置主加载

`useProactiveControls.ts:104` 在 settings/frames 已返回后继续 await feedbackSummary，之后才提交 loaded/settings/frames。受控延迟下，主数据已可用但 loading=true、loaded=false。真实 HTTP 有默认超时，不能称为无限等待；可确认抽屉和运行时授权被非必要请求延迟。应先提交主数据，统计独立异步提交并验证工作区。

### 8. TTS 状态刷新混淆写操作确认，并允许旧错误污染新状态

- 位置：`domains/settings/composables/useSettingsDomain.ts:142`、`:153`；`shared/composables/useDomainRequest.ts:40`；`SettingsPanel.vue:1262`、`:2748`。
- 场景一：预热 pending，用户刷新状态；刷新递增共享 ttsStatusSequence，预热成功回包被丢弃并返回 null，调用方显示预热失败。
- 场景二：旧状态 GET pending，预热成功提交新 runtime；旧 GET 随后失败，底层请求先写入 error，外层版本判断无法撤回，界面优先显示“状态不可读”。
- 最小修复方向：保留写操作 ACK，仅对 runtime 快照提交做版本判断；新 runtime 接管时同步使旧状态请求的 data/error/loading 失效。

### 9. 多连接器保存后的自动探测互相覆盖

`domains/system/composables/useSystemDomain.ts:88` 和 `:334` 仍让所有 connector 共用一个 connectorProbeRequest。deliveries/account 已隔离，但 probe 遗漏。`AgentGovernancePanel.vue:1403` 的各连接器保存后会自动触发探测，单连接器保存锁不能阻止并发。复现 QQ/WeChat 同时 probe、WeChat 先返回：QQ 后返回 null，connectorProbes 仅保留 WeChat。配置保存本身未撤销，丢失的是探测结果，可能显示“待确认”。应复用现有按 connector 隔离的请求机制。

### 10. 桌宠普通操作丢弃首次加载结果，并终止就绪重试

- 位置：`domains/pet/views/PetControlPanel.vue:752`、`:820`、`:859`。
- 首次 refresh 未返回时调整缩放：操作递增 refreshSequence，旧刷新整批失效，模型目录、显示器和能力也被丢弃；缩放结束不补读。
- 另一个场景：已有模型能力就绪重试时调整缩放，操作清理重试定时器，完成后未恢复。
- 动态结果：modelId 和 scale 已更新，但 catalog=[]、displays=[]、capabilities=null、hasLoadedState=false、timerCount=0。模型列表/动作能力需要手动刷新或再次激活才恢复。
- 最小修复方向：目录/能力读取与可变状态快照分开控制，操作结束后恢复尚未完成的就绪同步。

### 11. 引导“修复”与专用启动入口的等待期限不一致

`domains/onboarding/views/OnboardingGate.vue:201` 的专用启动设置 180 秒；`:209` 的 runRepair 没指定期限，使用 `api/clients/http-client.ts:77` 的默认 12 秒。主进程 `onboarding-readiness-coordinator.ts:346` 将 backend.retry 转为等待 startBackend 完成。执行实际浏览器 API 和公共 HTTP 客户端，未返回修复响应在 12 秒被判 request_timeout。主进程可能稍后完成是调用链推断，本次未启动真实 Electron 复现慢启动。应按修复动作采用对应操作期限，至少对齐 backend.retry 和扫描类操作。

### 12. Infrastructure 的缓存实例失活后仍跟随全局工作区读取

- 位置：`app/AppShell.vue:64`；`domains/system/views/InfrastructurePanel.vue:654`、`:677`、`:836`。
- 静态确认：应用按 workspaceId:routeName 缓存最多 12 个面板；Infrastructure 的工作区 watcher 没有 active 门控。曾加载过 API 快照的实例会在全局工作区变化时再次触发 5 个读取，并写回旧缓存实例。只有卸载失效，没有失活处理。
- 推断及边界：多个已访问工作区的失活实例可能重复读取当前工作区。本轮未做真实多实例 KeepAlive 挂载，不声称存在服务端写入。
- 最小修复方向：失活后停止页面读取并使在途快照失效，激活时刷新目标工作区；补真实 KeepAlive 切换用例。

## P3：历史组件

### 13. 未注册导航的 Overview 仍有写/写乱序回退

`domains/system/composables/useSystemOverview.ts:74`、`:85` 的写响应无条件提交完整 state。复现透明度依次 0.4→0.8，让 0.8 先完成，最终 petState.opacity 和 opacityDraft 回退为 0.4。当前导航未注册 Overview，降为 P3。应对写响应增加归属校验；这只能解决前端回退，不能独自保证服务端实际写入顺序。

## 复现与验证产物

- 主动控制 5 场景：`artifacts/panel-review-proactive-2026-11-11.cjs`、同名 `.json`。使用当前生产 TS、共享类型模块和真实 Vue，API 响应受控。
- 后端工作区写入场景：`artifacts/panel-review-workspace-write-2026-11-11.py`、同名 `.json`。使用实际端点闭包/服务/临时 SQLite，延迟调度受控。
- 聊天、TTS、connector 和历史 Overview：`artifacts/panel-review-architecture-2026-11-11.*`。生产 TS/组件声明的内存执行和受控 Promise，见产物中的适用边界。
- 桌宠 2 场景及引导期限：`artifacts/panel-review-host-2026-11-11.mjs`、同名 `.log`。执行生产声明和 HTTP 实现，外部端口/计时器受控，无真实网络请求。
- 独立复核限定运行的 6 个既有测试文件共 41 项通过；这些用例未覆盖新发现的交错时序。本轮未修改生产代码，也未重复上轮全量检查。

## 上一轮验证的不足

- `docs/panel-audit-evidence-2026-11-11/browser_panels.py:42` 每个面板重新 page.goto，并清掉部分工作区缓存，主要证明冷进入和子页可渲染；没有覆盖缓存面板快速切换、A→B→A 或在途写请求。
- 该脚本第 44/69 行忽略 networkidle 超时，第 73 行将子页交互失败写 JSON 后继续；没有把持续 loading、接口失败或交互异常转为失败断言。原报告的 0 异常/0 溢出仅是已有观测结果，不能等同逐功能验收。响应宽度抽样也不是所有子页与所有宽度的笛卡尔覆盖。
- 保存浏览器场景注入 503 并验证草稿保留/重新发送，尚未覆盖真实保存成功后的读回、页面刷新后持久化与运行时应用。
- 聊天旧测试覆盖普通新建会话迟到，未覆盖分支 store 的隐式激活；TTS 测试断言旧预热返回 null，没覆盖 UI 因此显示失败；connector 测试主要覆盖 deliveries/account；Overview 测试覆盖读/读和读/写。
- Electron 宿主 IPC、真实模型渲染、语音设备和真实供应商链路仍缺端到端证据。上轮已披露未启动宿主造成的 404 边界。

## 评审可用性与处理顺序

专用 code-reviewer 角色启动失败，服务返回模型不可用；以独立普通代理和 architect 进行只读交叉复核。本报告不是合并就绪或无遗漏批准。

建议先修复工作区写入身份和聊天分支激活，再处理主动控制/桌宠的请求边界、TTS/connector 并发结果，随后对齐引导期限、补缓存生命周期测试。验证应优先增加这些已复现场景，再补真实成功写入读回和 Electron 环境验收。
