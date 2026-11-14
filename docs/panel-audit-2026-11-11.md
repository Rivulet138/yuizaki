# 前端面板排查与修复记录（2026-11-11）

> 二次复核补充：同日进一步确认了工作区写入归属、聊天分支切换、桌宠加载及并发状态等剩余问题。本文记录的是首轮修复和当时验证结果，不代表所有功能已完整验收。当前问题清单及证据见 [二次复核报告](panel-review-followup-2026-11-11.md)。

本轮在现有工作区上检查前端全部注册面板，保留此前未提交内容，修复能够通过代码或测试复现的功能失效、前后端响应处理及等待状态问题。未替换依赖，未改动真实用户设置、会话或记忆。

## 检查范围与方法

- 浏览器进入 14 条注册导航：对话、长期记忆、设置、提示词、桌宠、SVC、工具、插件、基础设施、权限治理、执行追踪、人设记忆、语言管理、部署。部署旧链接实际跳转到基础设施。
- 遍历 29 个可见子页签；检查 1440px 桌面及 768px、390px 窄屏。历史 Overview 组件和首次引导通过源代码及专属测试补充检查。
- 使用现有 Vite 前端与独立启动的真实 Python 后端联调；后端端口为 48001，数据保存在 `artifacts/panel-audit-2026-11-11/runtime-data`。浏览器扫描拦截宿主和供应商写操作，仅允许隔离工作区与会话的必要状态保存。
- 对照 Python 与 Electron 主进程的路由和响应契约；对乱序响应、切换工作区/会话、失败重试及等待标志编写回归测试。
- 浏览器保存失败场景返回明确的模拟 503；该场景验证前端保留草稿与重试，不作为真实后端保存失败的取证。

## 已确认并修复的问题

| 范围 | 原有问题 | 修复后的行为 |
| --- | --- | --- |
| 聊天 | 删除、截断、重新生成、清空、编辑的异步响应在切换会话后可能继续作用于新会话 | 确认框及操作完成后校验会话归属；旧操作只更新原会话计数，不重发新会话、不清空新草稿 |
| 提示词 | 全局保存及运行时应用标志导致切换角色/工作区后按钮仍被另一个目标占用 | 按工作区、角色和应用目标分别记录等待状态 |
| 记忆 | 重建监控暂停后遗留 loading，返回页面遇到状态读取失败时持续转圈 | 暂停监控释放本地等待；恢复时重新设置，失败能够结束等待并显示错误 |
| 设置 | LLM/TTS 测试和 TTS 预热的成功/失败提示等待另一个状态 GET 完成 | 操作结果及时显示；运行状态单独刷新 |
| 连接器治理 | 多个连接器共用“只接受最新请求”的状态，其他连接器的并发结果被丢弃 | 按连接器隔离请求，聚合整体 loading/error；同一个连接器继续拒绝旧响应 |
| 历史 Overview | 旧轮询覆盖刚调整的缩放/透明度；响应乱序恢复旧草稿 | 状态快照按序提交，显式编辑使先前状态失效；模型目录独立排序接收 |
| 基础设施 | 切换工作区后，旧统计更新失败清掉新请求的 loading 并显示旧错误 | 分离统计更新状态，提交前校验工作区身份 |
| 执行追踪 | 删除任务失败或返回 `ok:false` 仍显示成功 | 仅在 `ok:true` 时确认删除成功 |
| 部署 | 健康刷新抹掉启动/停止的错误；文档 URL 解析失败未被捕获 | 操作错误与健康检查错误分别保留；文档解析纳入异常处理 |
| 工具 | 旧列表请求结束时提前清除新请求的 loading | 仅当前请求清除等待；面板失活释放页面状态 |
| SVC | 嵌入模式下本地检查结果未显示 | 检查结果与运行中状态一致显示 |
| 插件 | 并行取消共用最新请求状态，较早成功被误报失败 | 每个 invocation 独立记录取消结果、错误与等待状态 |
| 桌宠 | 模型就绪重试只读取 state，未恢复 capabilities，导致预览按钮持续禁用 | 重试补读能力快照，可从临时 503 恢复 |
| 桌宠公共传输 | 原始 fetch 没有超时，取消被包装成一般连接失败，结构化错误字段丢失 | 复用公共 HTTP 客户端，普通请求 12 秒超时，保留 AbortError 和错误元数据；模型选择/导入沿用资源操作的 30 分钟期限 |
| 语言管理 | 切换语言使旧刷新失效后，旧 loading 永久占用按钮 | 释放失效请求的等待，旧响应不清除新请求状态 |
| 首次引导 | 一次快照请求失败后停止轮询，迟到旧响应覆盖新快照，卸载后可能重建定时器 | 失败后按已有运行状态继续轮询，按 revision 拒绝旧快照，卸载后停止调度 |
| 工作区主动设置 | load/save 相互替代或上下文失效后，被替代请求无法释放自己的等待标志 | 新请求和失效处理同步释放旧锁，继续拒绝旧结果 |

未确认新的接口路径或字段映射缺陷；本轮跨前后端的问题主要表现为响应归属、错误回包和并发结果处理错误。

## 修改文件

实现涉及以下文件；这些文件部分已有此前修改，本清单仅说明本轮触及范围，不能把全部 git diff 归为本轮新增。

- `electron/src/renderer/domains/chat/views/ChatPanel.vue`
- `electron/src/renderer/stores/chatStore.ts`
- `electron/src/renderer/domains/prompt/views/PromptPanel.vue`
- `electron/src/renderer/domains/memory/views/MemoryPanel.vue`
- `electron/src/renderer/domains/settings/composables/useSettingsDomain.ts`
- `electron/src/renderer/domains/settings/views/SettingsPanel.vue`
- `electron/src/renderer/domains/system/composables/useConnectorRequest.ts`（按连接器隔离请求的辅助函数）
- `electron/src/renderer/domains/system/composables/useSystemDomain.ts`
- `electron/src/renderer/domains/system/composables/useSystemOverview.ts`
- `electron/src/renderer/domains/system/views/InfrastructurePanel.vue`
- `electron/src/renderer/domains/system/views/AgentTracePanel.vue`
- `electron/src/renderer/domains/deploy/views/DeployPanel.vue`
- `electron/src/renderer/domains/tools/views/ToolPanel.vue`
- `electron/src/renderer/domains/tools/views/SVCPanel.vue`
- `electron/src/renderer/domains/plugin/composables/usePluginDomain.ts`
- `electron/src/renderer/domains/plugin/views/PluginManagementPanel.vue`
- `electron/src/renderer/domains/pet/views/PetControlPanel.vue`
- `electron/src/renderer/domains/i18n/composables/useI18nDiagnostics.ts`
- `electron/src/renderer/domains/onboarding/views/OnboardingGate.vue`
- `electron/src/renderer/utils/petControl.ts`
- `electron/src/renderer/app/composables/useProactiveControls.ts`

回归测试位于相应域的 `.test.ts` 文件；新测试辅助 `domains/tools/tests/panel-script.mjs` 仅用于提取并执行组件目标声明。公共桌宠传输删除了重复的 fetch/错误解析，沿用现有 HTTP 实现；没有新依赖。

## 验证证据

最终计数及检查状态见同目录 `panel-audit-evidence-2026-11-11/verification-summary.json`，原始执行记录位于 `artifacts/panel-audit-*-2026-11-11.log`。

- 前端全量单测：77 个文件、713 项全部通过，较初轮新增 52 项回归测试。主进程和 renderer 类型检查、ESLint、生产构建、bundle audit、diff whitespace 检查均通过。
- 后端 14 个接口与契约测试文件，共 169 项通过。
- `browser-panels.json`：14 条导航、29 个子页签，页面脚本异常 0，所有尺寸样本横向溢出 0。设置初始采样存在一个短暂 loading；进入各子页后全部结束，另通过实际表单编辑及失败重试交互验证可用性。
- `browser-interactions.json`：设置保存失败后保留草稿并可重试、记忆高级抽屉、工作区主动设置加载、宿主不可用时跳过引导，四项通过，页面异常 0。
- 初轮全量单测的 HTTP 测试在高并行负载下有两项失败；独立 24 项全部通过，随后全量限制为 4 workers 验证通过，未据此修改业务超时或放宽断言。
- 专项修复已由不同执行者交叉复核；复核额外发现首次模型目录被状态失效保护丢弃的边界，并纳入修复与测试。

## 验证边界

Electron 控制服务未运行。桌宠目录、显示器、宿主资源、插件注册等专属于该服务的接口在隔离 Python 服务上返回 404，这些响应属于测试环境能力缺失，未误判为路由实现错误。相关逻辑通过源代码契约与单测验证，但没有声称完成真实 Electron IPC、托盘/窗口控制、模型资源加载与渲染的端到端验收。

隔离后端没有可用的 LLM/TTS/ASR 供应商配置。本轮没有调用真实付费供应商，也没有执行资源下载安装、真实连接器发送、数据恢复或删除真实用户资料。实际语音设备、第三方服务及 Live2D/VRM 模型的运行效果仍需要对应环境才能验证。

验证结束后已停止本轮独立启动的后端，保留原有 Vite 服务；未提交或推送代码。
