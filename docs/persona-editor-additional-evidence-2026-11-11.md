# 人格编辑补充源码取证：RisuAI、Agnai、SillyTavern

> 后续实施更新（2026-11-11）：用户继续授权改进后，已实现原 JSON 字段保留、备用开场参考与会话局部场景/示例覆盖。下文“尚未实现”为本次取证阶段的历史状态；当前实现、兼容边界及验证见 `persona-editor-implementation-2026-11-11.md`。

日期：2026-11-11。请求类型：实现参考取证。仅研究官方功能源码；范围不限于角色卡规范。

## 直接结论与完成边界

本轮已核实三个项目的固定提交源码，并由主线程补齐本地实现对照。值得继续考虑的新增能力是备用开场白和会话局部覆盖；基础/高级分层及独立对话示例本地已有。另以角色卡 V2 规范补查了导入导出保真缺口，建议优先处理数据保留。

本轮产品改动只删除设定检查、来源预览、情境访谈及检查入口；保留角色档案、世界书、行为规则。下面的功能建议尚未实现，不建议恢复上述界面。

## 版本与官方证据范围

2026-11-11 通过官方 GitHub API 查询默认分支，随后按完整 SHA 读取源码。提交时间使用 UTC；分支是取样渠道，不替代固定版本引用。

| 项目 | 取样渠道 | 完整 SHA | 提交时间 UTC |
| --- | --- | --- | --- |
| kwaroran/RisuAI | main | 4d87a70ffb325db84dd35cb1b76b31d7074da156 | 2026-11-09T08:23:47Z |
| agnaistic/agnai | dev | fccee00f5f7628d150760c787c4be87e6b1a652c | 2026-06-13T11:58:57Z |
| SillyTavern/SillyTavern | release | 06bde939fb1e9c4c8d8641d810f0a916b5bce127 | 2026-09-14T19:01:34Z |

提交元数据：[kwaroran/RisuAI](https://api.github.com/repos/kwaroran/RisuAI/commits/4d87a70ffb325db84dd35cb1b76b31d7074da156)；[agnaistic/agnai](https://api.github.com/repos/agnaistic/agnai/commits/fccee00f5f7628d150760c787c4be87e6b1a652c)；[SillyTavern/SillyTavern](https://api.github.com/repos/SillyTavern/SillyTavern/commits/06bde939fb1e9c4c8d8641d810f0a916b5bce127)。main/dev 是开发快照，release 是发布分支快照；本研究不宣称对应某个已发布语义版本，也不据提交日期评价维护状态。

主线程已获取 SillyTavern personas 与 characterdesign 官方文档；本轮不再展开文档研究。下述结论以固定源码为依据，未使用第三方教程或扩展项目作为证据。源码取证不能替代运行项目后的端到端验证。

## 上游事实：RisuAI

**编辑字段分层。** `CharConfig.svelte` 的 `$CharConfigSubMenu === 0` 分支直接绑定 `name/desc/firstMessage`；组件其他位置编辑 `exampleMessage/creatorNotes/systemPrompt/replaceGlobalNote`。`personality/scenario` 仅在 `showUnrecommended` 开启或字段长度大于 3 时显示，不能概括成“所有非空扩展字段总会显示”。
出处：[基础字段](https://github.com/kwaroran/RisuAI/blob/4d87a70ffb325db84dd35cb1b76b31d7074da156/src/lib/SideBars/CharConfig.svelte#L280-L288)；[扩展字段与显示条件](https://github.com/kwaroran/RisuAI/blob/4d87a70ffb325db84dd35cb1b76b31d7074da156/src/lib/SideBars/CharConfig.svelte#L1119-L1142)。

**备用开场白有编辑和运行闭环。** `moveAlternateGreetingUp/Down` 交换数组项，编辑区支持新增、删除与上下移动。`sendChat` 在非群组且相关消息段未重置时，以 `fmIndex === -1` 取主开场白，否则取备用项，再构造 assistant 消息。它不是只存在于角色卡中的字段。
出处：[排序函数](https://github.com/kwaroran/RisuAI/blob/4d87a70ffb325db84dd35cb1b76b31d7074da156/src/lib/SideBars/CharConfig.svelte#L225-L244)；[列表操作](https://github.com/kwaroran/RisuAI/blob/4d87a70ffb325db84dd35cb1b76b31d7074da156/src/lib/SideBars/CharConfig.svelte#L1173-L1215)；[运行时选择](https://github.com/kwaroran/RisuAI/blob/4d87a70ffb325db84dd35cb1b76b31d7074da156/src/ts/process/index.svelte.ts#L866-L883)。

**示例与描述实际被消费。** `sendChat` 调用 `exampleMessage(currentChar, getUserName())`，计入 token 后用于初始化 chats；随后单独加入开场白。描述路径则将 `desc`、附加信息、`personality`、`scenario` 组合成 system 内容。这证明示例对话和角色描述具有不同装配路径。
出处：[示例装配](https://github.com/kwaroran/RisuAI/blob/4d87a70ffb325db84dd35cb1b76b31d7074da156/src/ts/process/index.svelte.ts#L831-L843)；[描述装配](https://github.com/kwaroran/RisuAI/blob/4d87a70ffb325db84dd35cb1b76b31d7074da156/src/ts/process/index.svelte.ts#L465-L487)。

**覆盖存在适用条件。** 非 utilityBot 且没有 promptTemplate 时，角色 `systemPrompt` 可以通过 `{{original}}` 引入全局 mainPrompt，空结果回退全局值；不能外推成所有模式共享同一优先级。
出处：[sendChat 的条件与覆盖表达式](https://github.com/kwaroran/RisuAI/blob/4d87a70ffb325db84dd35cb1b76b31d7074da156/src/ts/process/index.svelte.ts#L410-L425)。

## 上游事实：Agnai

**属性编辑连接运行时。** `CreateCharacterForm` 将 `personaKind/personaAttrs` 接入 `PersonaAttributes`。`formatCharacter` 实现 wpp、sbf、boostyle、attributes、text；`buildPromptPlaceholders` 在回复角色与主角色一致时选择 `chat.overrides ?? replyAs.persona`，再格式化 persona 占位内容。该格式化函数不是仅供导入导出使用。
出处：[表单接入](https://github.com/agnaistic/agnai/blob/fccee00f5f7628d150760c787c4be87e6b1a652c/web/pages/Character/CreateCharacterForm.tsx#L544-L559)；[formatCharacter](https://github.com/agnaistic/agnai/blob/fccee00f5f7628d150760c787c4be87e6b1a652c/common/characters.ts#L92-L141)；[buildPromptPlaceholders](https://github.com/agnaistic/agnai/blob/fccee00f5f7628d150760c787c4be87e6b1a652c/common/prompt.ts#L510-L529)。

**会话覆盖能区分某些空值与继承。** `resolveScenario` 在存在 `chat.overrides` 时返回 `chat.scenario || 空串`，否则采用角色场景并按 scenario books 的覆盖/追加配置组合。示例对话在满足角色一致且启用覆盖的条件下使用 `chat.sampleChat ?? replyAs.sampleChat`，因此空串可以保留，而未指定值回退。
出处：[resolveScenario](https://github.com/agnaistic/agnai/blob/fccee00f5f7628d150760c787c4be87e6b1a652c/common/prompt.ts#L1058-L1077)；[示例对话覆盖](https://github.com/agnaistic/agnai/blob/fccee00f5f7628d150760c787c4be87e6b1a652c/common/prompt.ts#L574-L588)。

**备用开场白确有编辑组件。** `AlternateGreetingsInput` 的 `addGreeting/removeGreeting/onChange` 支持新增、删除、逐项编辑；父表单接入 `editor.state.alternateGreetings`。此处仅确认编辑链，未追踪 Agnai 新聊天的选择逻辑，不能将 RisuAI/SillyTavern 的使用行为套给 Agnai。
出处：[AlternateGreetingsInput](https://github.com/agnaistic/agnai/blob/fccee00f5f7628d150760c787c4be87e6b1a652c/web/pages/Character/form/AltGreetings.tsx#L6-L45)；[父表单绑定](https://github.com/agnaistic/agnai/blob/fccee00f5f7628d150760c787c4be87e6b1a652c/web/pages/Character/CreateCharacterForm.tsx#L564-L585)。

**不建议照搬格式切换。** `PersonaAttributes` 包含属性转文本及反向处理，但父表单明确提示文本与非文本切换可能丢失数据。这不足以证明任意双向转换无损；格式体系不纳入本轮四项建议。
出处：[转换 effect](https://github.com/agnaistic/agnai/blob/fccee00f5f7628d150760c787c4be87e6b1a652c/web/shared/PersonaAttributes.tsx#L61-L100)；[表单警告](https://github.com/agnaistic/agnai/blob/fccee00f5f7628d150760c787c4be87e6b1a652c/web/pages/Character/CreateCharacterForm.tsx#L525-L559)。

## 上游事实：SillyTavern

**会话覆盖有编辑和消费两端。** `setCharacterSettingsOverrides` 将 scenario、examples、system_prompt 暂存于 pendingChanges，弹窗返回后写入 chat_metadata 并调用 saveMetadata。该函数没有检查弹窗返回值，不能据此宣称取消必然回滚。`getCharacterCardFieldsLazy` 对 scenario、mesExamples 使用“会话值 || 角色值 || 空串”，所以空串意味着回退；system 还受 prefer_character_prompt 控制，群组卡片另有前置路径。
出处：[覆盖编辑与保存](https://github.com/SillyTavern/SillyTavern/blob/06bde939fb1e9c4c8d8641d810f0a916b5bce127/public/script.js#L8996-L9054)；[字段读取优先级](https://github.com/SillyTavern/SillyTavern/blob/06bde939fb1e9c4c8d8641d810f0a916b5bce127/public/script.js#L3402-L3467)。

**备用开场白成为首条消息候选。** `getFirstMessage` 将主开场白与 alternate_greetings 组成 swipes；主开场白为空时使用首个备用项。`getChatResult` 在 chat 为空时插入返回消息。
出处：[空聊天初始化](https://github.com/SillyTavern/SillyTavern/blob/06bde939fb1e9c4c8d8641d810f0a916b5bce127/public/script.js#L7684-L7695)；[getFirstMessage](https://github.com/SillyTavern/SillyTavern/blob/06bde939fb1e9c4c8d8641d810f0a916b5bce127/public/script.js#L7710-L7741)。

**术语边界。** RisuAI 的 `saveUserPersona/changeUserPersona` 和 SillyTavern 的 `loadPersonaForCurrentChat` 管理玩家身份；它们不是 AI 角色定义，不应直接计为本地 AI 人格编辑缺口。
出处：[RisuAI 玩家身份](https://github.com/kwaroran/RisuAI/blob/4d87a70ffb325db84dd35cb1b76b31d7074da156/src/ts/persona.ts#L29-L45)；[SillyTavern 聊天身份绑定](https://github.com/SillyTavern/SillyTavern/blob/06bde939fb1e9c4c8d8641d810f0a916b5bce127/public/scripts/personas.js#L1543-L1567)。

## 本地事实与缺口判定

主线程于 2026-11-11 直接读取本地工作树。基准 HEAD 为 `865df8a284a3c7ea29a5c50f1c689d2c955e8680`；相关实现含本次及前序未提交修改，以下以工作树中的文件/符号为准。

| 本地源码与符号 | 已核实事实 | 判定 |
| --- | --- | --- |
| `electron/src/renderer/shared/components/prompt/WorkspacePromptEditor.vue` 的角色表单、`role-json-editor`；`domains/prompt/views/PromptPanel.vue` 的三分区 | 名称、背景、性格、情境、行为、示例、开场独立编辑；JSON 折叠且显式应用 | 编辑分层已有；若继续减轻视觉密度，可将示例/开场折叠并显示非空状态，不再增加导航或检查页 |
| `electron/src/shared/workspace.ts:WorkspaceRoleCard`；`domains/prompt/character-card.ts:parseCharacterCard/exportCharacterCard` | 类型只有单个 firstMessage，解析器不读 alternate_greetings，导出固定空数组；编辑器也只有一个开场参考框 | 当前核心卡导入/编辑链缺少备用开场白；不把导出中的空字段当作功能支持 |
| `stores/workspaceStore.ts:normalizeRoleCard`；`stores/chatStore.ts:normalizePromptProfile`；`python/modules/agent/prompt_assembly.py:_role_card_prompt` | exampleDialogue 经表单、规范化、请求及后端装配，和 description/personality 分开。后台将其放入角色参考数据块，不伪造成历史 | 示例全链路已有；不重复实现，也不直接照搬上游示例转聊天消息的机制 |
| `stores/sessionStore.ts:SessionRecord`；`domains/chat/views/ChatPanel.vue` 的 profile 同步；`prompt_assembly.py:_resolve_prompt_profile` | UI 从当前 workspace 组装 profile；后端已有当前工作区默认值加请求字段优先的一层合并。SessionRecord 没有角色场景/示例覆盖字段 | 请求覆盖基础已有；本次检查的会话列表模型和人格编辑 UI 尚无“仅本会话”持久化覆盖及恢复继承入口，不能宣称服务端完全没有任何临时覆盖能力 |
| `domains/prompt/character-card.ts:parseCharacterCard/exportCharacterCard` | 导入后只返回核心角色字段；creator_notes/tags/creator/character_version/alternate_greetings 导出为空，未知扩展未回写；system_prompt 和 post_history_instructions 合并成 instructions | 核心兼容已实现，原始元数据和指令位置并非无损保留。当前按钮提示已披露范围，但改进数据保真仍有价值 |

本地 `firstMessage` 的现有产品语义是开场风格参考；后端 `_role_card_prompt` 将其放入角色参考块。新增备用开场时需要先明确“多条参考”与“新建会话首条消息”的区别，不能把过去没有发生的共同经历写成事实，也不应改写已有聊天。

用户侧资料另有现成来源：memory 翻译已有 `memoryPanel.layerProfileLabel=偏好与称呼` 与 `sourceProfile=User profile`。本轮没有审计完整 profile 管线，不作“后端缺少用户档案”的判断，也不建议再建一套用户记忆。

## 借鉴建议与实施顺序

| 优先级 | 具体建议 | 依据与本地收益 | 最小实施边界 |
| --- | --- | --- | --- |
| 1 | 导入导出保留原始元数据、未知扩展与原字段结构 | V2 规范要求保留已有可选数据及未知扩展；本地当前导出会把未建模字段置空 | 保存原始卡片副本，只回写明确修改过的核心字段；不执行扩展脚本，不承诺 PNG/V3 资源无损；用导入→修改名称→导出回归证明 |
| 2 | 备用开场白列表 | RisuAI 与 SillyTavern 有编辑和运行使用闭环，本地当前仅一个参考字符串 | 先保留并编辑数组，再明确新会话选择语义；已有聊天保持原文，不能仅加数组字段就称运行时支持 |
| 3 | 会话局部情境覆盖与恢复继承 | Agnai/SillyTavern 有会话字段覆盖；本地已有请求覆盖基础，缺少对应的会话编辑入口 | 先定作用域、持久化和优先级；明确未指定、空串清除、恢复继承的区别，禁止无意修改工作区/原角色 |
| 已有，可微调 | 结构化编辑与独立示例 | 上游表单/装配能提供组织方式参考；本地已全链路实现 | 只在操作确有摩擦时减少展开项；保留示例为参考而非事实历史，不追加设定检查页 |

前三项属于后续建议，本轮未实现。上游源码证明功能存在，不证明一定提升本项目模型的人格表现。

补充规范来源：[Character Card V2](https://raw.githubusercontent.com/malfoyslastname/character-card-spec-v2/main/spec_v2.md)，重点为 `TavernCardV2`、未知 `extensions` 保留要求及原 `system_prompt/post_history_instructions` 的独立字段语义。此链接为 2026-11-11 抓取的主分支规范，未固定 SHA；不与上面三个项目的固定快照混称。

## 可复用固定源码索引

- `kwaroran/RisuAI@4d87a70ffb325db84dd35cb1b76b31d7074da156:src/lib/SideBars/CharConfig.svelte:L225-L244` — moveAlternateGreetingUp/Down；[固定源码](https://github.com/kwaroran/RisuAI/blob/4d87a70ffb325db84dd35cb1b76b31d7074da156/src/lib/SideBars/CharConfig.svelte#L225-L244)。
- `kwaroran/RisuAI@4d87a70ffb325db84dd35cb1b76b31d7074da156:src/ts/process/index.svelte.ts:L866-L883` — sendChat 中开场白选取；[固定源码](https://github.com/kwaroran/RisuAI/blob/4d87a70ffb325db84dd35cb1b76b31d7074da156/src/ts/process/index.svelte.ts#L866-L883)。
- `agnaistic/agnai@fccee00f5f7628d150760c787c4be87e6b1a652c:common/characters.ts:L92-L141` — formatCharacter；[固定源码](https://github.com/agnaistic/agnai/blob/fccee00f5f7628d150760c787c4be87e6b1a652c/common/characters.ts#L92-L141)。
- `agnaistic/agnai@fccee00f5f7628d150760c787c4be87e6b1a652c:common/prompt.ts:L510-L529` — buildPromptPlaceholders；[固定源码](https://github.com/agnaistic/agnai/blob/fccee00f5f7628d150760c787c4be87e6b1a652c/common/prompt.ts#L510-L529)。
- `agnaistic/agnai@fccee00f5f7628d150760c787c4be87e6b1a652c:common/prompt.ts:L1058-L1077` — resolveScenario；[固定源码](https://github.com/agnaistic/agnai/blob/fccee00f5f7628d150760c787c4be87e6b1a652c/common/prompt.ts#L1058-L1077)。
- `SillyTavern/SillyTavern@06bde939fb1e9c4c8d8641d810f0a916b5bce127:public/script.js:L3402-L3467` — getCharacterCardFieldsLazy；[固定源码](https://github.com/SillyTavern/SillyTavern/blob/06bde939fb1e9c4c8d8641d810f0a916b5bce127/public/script.js#L3402-L3467)。
- `SillyTavern/SillyTavern@06bde939fb1e9c4c8d8641d810f0a916b5bce127:public/script.js:L7710-L7741` — getFirstMessage；[固定源码](https://github.com/SillyTavern/SillyTavern/blob/06bde939fb1e9c4c8d8641d810f0a916b5bce127/public/script.js#L7710-L7741)。
- `SillyTavern/SillyTavern@06bde939fb1e9c4c8d8641d810f0a916b5bce127:public/script.js:L8996-L9054` — setCharacterSettingsOverrides；[固定源码](https://github.com/SillyTavern/SillyTavern/blob/06bde939fb1e9c4c8d8641d810f0a916b5bce127/public/script.js#L8996-L9054)。

## 验证记录与交付状态

- 上游：读取三个官方仓库固定 SHA 源码，核对函数、字段及引用行段；未运行上游应用。
- 本地：主线程直接核对上述表单、核心转换、存储规范化、聊天请求和服务端装配。所有建议均区分已有与缺口。
- 产品删除：移除 Review 分区、来源预览、情境访谈、复制问题及侧栏检查入口；移除其专用状态、计算属性和样式，角色信息栏维持已删除状态。
- 2026-11-11 验证：`PromptPanel.test.ts` 和 `WorkspacePromptEditor.test.ts` 共 **21 项通过**；改动 SFC ESLint 通过；renderer changed type gate **0 错误**；Vite build 通过（既有 Cubism classic-script 提示保留）。
- 浏览器：Chrome/Playwright 验证只剩 3 tabs、各区可切换、键盘首尾循环、被删元素不存在；1600/1000/800 宽度无水平溢出，pageerror **0**。测试隔离并拦截非 GET API 写入，未调用模型。
- 交付：新增本文档，更新 `DESIGN.md` 及前次取证文档的版本说明，产品代码变更集中在 `PromptPanel.vue`；本轮建议均未实现。
