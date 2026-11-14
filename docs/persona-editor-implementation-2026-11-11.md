# 人格设定后续实现与验收（2026-11-11）

本次根据用户“继续改进”实施上一轮取证建议。上游固定提交与本地差距见 [补充取证](persona-editor-additional-evidence-2026-11-11.md)。保持三分区，不恢复角色信息栏、设定检查、来源预览或访谈 UI。

## 1. 角色卡 JSON 数据保留

- `electron/src/shared/workspace.ts:WorkspaceRoleCard` 新增可选 `sourceCard`，只存原始 JSON 深拷贝；`character-card.ts` 的 parse/clone/export 保留 V1 根对象、V2/V3 包装及未知 JSON 字段。新建卡默认 V2。
- 从原始 JSON 开始导出，仅回写用户明确更改的核心字段。作者说明、标签、版本、第三方扩展及未编辑的 system_prompt/post_history_instructions 拆分保留。
- 用户修改聚合 instructions 后，用新值替换旧规则来源并清空旧 post-history 及别名，避免旧规则重现。空字符串同样有效。
- 有世界书编辑时，按已有 ID 或无 ID 条目的 insertionOrder 匹配条目，合并已支持字段并保留匹配条目的扩展；明确新增/删除，包括删除全部条目。JSON 容器可保留未知资源字段，但本轮不处理 PNG 嵌入或外部资源打包，不宣称全部第三方语义无损。
- `workspaceStore.ts:normalizeRoleCard` 保留元数据与备用开场并独立复制。`chatStore.ts:normalizePromptProfile` 继续用字段白名单，sourceCard、creator_notes 和任意扩展均不发送模型；服务端角色装配同样只消费已知角色字段。

## 2. 备用开场参考

- `WorkspacePromptEditor.vue` 使用折叠列表，支持新增、编辑、删除、上移、下移；可选择主开场或一个备用项。
- `alternateGreetings` 保存完整文本数组；`greetingIndex=-1` 选择主开场。移动条目时保持选中的内容；删除选中项则恢复主开场；非法索引回退主开场，选中的空文本保持为空。
- 前端概览与后端 `_role_card_prompt` 选择一致。这里只提供语气参考，不生成 assistant 历史消息，不改写共同经历或事实记忆。UI 最多新增 20 个列表项，不截断已导入的更长列表。

## 3. 仅当前会话的情境/示例覆盖

- `domains/prompt/components/SessionPersonaOverrides.vue` 放在行为规则的折叠区；从当前工作区会话中选择，分别启用场景和示例覆盖。未勾选继承工作区，勾选后留空表示显式清空。
- `sessionStore.ts` 的 `SessionRecord.persona_overrides` 为 `{scenario?: string, exampleDialogue?: string} | null`，通过现有带 workspace_id 的 session PATCH 保存。省略保持、null 恢复继承、空对象无覆盖；拒绝未知键/非字符串/每字段超过 1600 字符，非法请求 422。
- 新 Alembic revision `20261111_00` 接续 `20261020_01`，为 `chat_sessions` 添加 nullable JSON 列。create/list/update/branch 返回该字段；分支独立复制。
- `prompt_assembly.py:build_prompt_assembly` 先解析当前工作区及请求 profile，再读取所属会话覆盖场景/示例。工作区不匹配拒绝，null/false/disabled 角色卡不会被重新启用。
- UI 草稿和保存状态按 workspace/session 键管理，保留保存期间的新输入；晚到响应只归属原会话；失败显示错误并允许重试。保存不会修改工作区角色或其他聊天。

## 4. 实际验证

| 范围 | 结果 |
| --- | --- |
| 人格前端：prompt 目录、WorkspacePromptEditor、workspace/chat/session store、navigation | 8 文件 **175 项通过** |
| 后端：prompt assembly、session persona、migration bootstrap、workspace context API/repository/store/migration、companion persona | 8 文件 **158 项通过**；额外单跑 session persona **35 项通过** |
| 浏览器 Chrome/Playwright | 6 组检查通过；pageerror 0；仅3分区、V3 metadata/split 保留、备用选择重排、会话保存/切换/null 恢复、1600/1000/800 无横向溢出 |
| 静态 | 本轮 TS/Vue ESLint 通过；renderer changed type gate 0 错误；Python compileall 通过 |
| 构建 | Vite build、renderer bundle audit 通过；保留既有 Cubism classic-script 提示 |
| 后端 Ruff | 25 条既有告警仍在 repository/prompt_assembly/workspace_api；新文件及新增路径未增加告警。没有宣称全量 lint 为零 |
| 扩展检查 | ChatPanel.async.test.ts 13 项通过；SettingsPanel.regression.test.ts 49 项中 3 项失败，均为新增的连接/预热失败即时反馈断言。该页工作树在本次检查期间有并行修改，本轮不改其行为、不放宽断言 |

浏览器使用隔离 context，拦截非 GET API 并用临时会话响应验证交互；没有写用户配置、调用付费模型或写记忆。持久化及服务端生效由真实 SQLite/FastAPI/装配测试覆盖。未评测真实模型人格表现。

类型检查曾发现 SettingsPanel.vue 缺失 SettingsResponse 类型导入，补齐类型导入，不改变设置页行为。上述扩展测试失败与该类型导入没有运行时关系。

## 5. 命令摘要

前端 cwd `electron`：`node node_modules/vitest/vitest.mjs run src/renderer/domains/prompt src/renderer/shared/components/prompt/WorkspacePromptEditor.test.ts src/renderer/stores/workspaceStore.regression.test.ts src/renderer/stores/chatStore.regression.test.ts src/renderer/stores/sessionStore.regression.test.ts src/renderer/navigation/navigation-contract.test.ts --root .`。

后端 cwd `python`：`.venv/Scripts/python.exe -m pytest tests/test_prompt_assembly.py tests/test_session_persona_overrides.py tests/test_migration_bootstrap.py tests/test_workspace_context_api.py tests/test_workspace_context_repository.py tests/test_workspace_context_store.py tests/test_workspace_context_migration.py tests/test_companion_persona_api.py -q`。
