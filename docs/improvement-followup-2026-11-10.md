# Yuizaki 改进续作与验收记录（2026-11-10）

本轮承接 `improvement-2026-11-10.md` 的 30 个原编号和运行待办，按“取证 → 修改 → 最小必要验收”继续工作。保留已有改动与原始证据，不另设门禁，也不以旧日志替代当前源码验证。

## 已关闭的环境问题

1. `three@0.186.1` 的实际安装包不带项目所需的声明，`@pixiv/three-vrm` 的声明也引用这些类型。增加匹配的开发依赖 `@types/three@0.186.0`，未改应用运行依赖；保留 lockfile 其余包的版本及无关元数据。
2. 直接运行 `vue-tsc --noEmit -p tsconfig.renderer.json` 退出 0；类型基线从三个历史条目收紧为零，`--changed` 检查的 75 个前端文件也无错误。后续源码变动仍由最终检查确认。
3. 系统 PATH 首选 Node 22.14.0，低于项目 package.json 要求。后续验证使用已有 Codex runtime 的 Node 24.22.1，无需修改用户全局安装。
4. `GOTOOLCHAIN=auto` 在 launcher 目录实际选择 `go1.27.0 windows/amd64`，`go test -count=1 ./...` 返回 `ok yuizaki-launcher 1.807s`，未复用结果缓存。原 Go 工具链阻塞已关闭。

对应修改：`electron/package.json`、`electron/package-lock.json`、`electron/renderer-types-baseline.json`。取证概要：`improvement-evidence-2026-11-10/followup/environment.json`。

## 健康与引导取证及修复

现存服务 2026-11-10 14:16 的有限超时请求：Python `/health` 1759.4ms/200，control `/health` 2489.1ms/200，同期 ping 分别 7.1ms、8.4ms。该轮主要耗时在 LLM 健康探测，TTS 和 DB 耗时很短。历史超过 8 秒的情况本轮未复现，不能把这次测量推为历史根因。

本轮隔离复现发现：

- 20ms 总预算下，同步探针阻塞约 81ms 后仍可能返回 healthy。修复为共用绝对截止时间；晚到成功不能通过，已过截止时间的排队检查不再执行。
- TTS provider 更换期间会复用旧实例尚未完成的状态任务。复用现在绑定实际 provider 的方法及所属实例，新实例不会显示旧实例 healthy。
- 只重试 avatar 时不再额外探测 Python；取消清理的 ping 和 cancel HTTP 共用有界截止时间；正常轮询完成后移除 abort listener。

修改：`python/modules/system/health_check.py`、`health_providers.py`、`electron/src/main/onboarding-readiness-coordinator.ts` 及对应既有测试/隔离脚本。runtime identity/HMAC 校验保留。

主线重新执行 `verify-health-budget.py`，日志 `followup/health-budget.log`：晚到成功判 unhealthy，过期排队检查未运行，provider 更换正确显示 unavailable；慢取消收尾从 HEAD 233.2ms 降为当前 46.5ms。同步阻塞本身仍不能被 asyncio 强制抢占，不能承诺整个进程任何负载下都精确按预算返回。

现存 Python PID21792 的 `ExecutablePath` 为 base Python，但启动命令和父 PID14048 均指向项目 `.venv/Scripts/python.exe`，符合 Windows venv redirector。**此前“可执行文件在全局路径，所以不在虚拟环境”的判断已撤回并更正文档。** 当前 ping 没有暴露 sys.prefix，不能仅凭路径作相反断言。隔离验证进程明确报告 venv prefix/base_prefix。

运行观测由子任务 stdout 整理为 `followup/running-health-observation.json`，其原始访问日志为 `logs/dev/backend.supervisor.log`；不把隔离脚本的慢函数日志冒充旧进程现场日志。

## 长期记忆与 HTTP 流的追加闭环

- 候选永久删除改为直接提交空正文墓碑，消除先删除 ID 再写墓碑的防重放空窗；已删除候选的修改和恢复返回 409。
- 墓碑提交同步清理操作账本敏感载荷；迟到的操作日志再次写入时仍会脱敏，metadata 更新不能剥掉墓碑状态。
- embedding 发布核对当前文档身份、正文及 metadata，迟到向量不能覆盖删除或更晚写入。
- 派生索引接收权威记录的独立副本，避免索引实现修改传入参数后污染权威视图；墓碑投影先清旧正文，再尝试可能失败的后续更新。
- HTTP SSE 断连不再重复 invalidate 已失效的 generation。主线进一步复现“重复 interrupt → replacement → disconnect”会取消尚在完成的持久化，修复 Generation.invalidate 不再对正在取消的同一 task 重复 cancel。原失败场景改为提交一次且新 generation 有效。
- single/batch/maintenance 删除响应统一返回 `index_cleanup_status`。`complete` 才显示索引清理完成；远端 dirty 为 `pending`，不支持状态读取为 `unknown`，后两者返回 `status=authority_deleted`。权威删除不回滚，也不重复发送 delete。VectorStore/SQLite 的本地索引同步清理可确认 complete；Qdrant 断网仍可能保留旧载荷，必须等待既有 rebuild/恢复流程，不能拿 excluded 当擦除证据。

回归涵盖旧墓碑、三种删除、迟到写入、投影故障、重建恢复、SSE commit 及重复中断。项目 `.venv` 最终八文件 **104 passed / 10.83s**，详见 `followup/python-memory-stream.log`；该组包含重叠的定向结果，不与子任务计数相加。

实际数据只读预检：依据运行接口给出的 `E:/yuizaki/python/data/memory.db`，以 SQLite `mode=ro`、`query_only` 读取聚合统计，共 2 条 workspace 记录；残留正文墓碑、缺 session/workspace ID 和损坏 metadata 均为 0。没有导出正文或更改真实数据，修复数量为 0；索引待处理不能仅凭冷启动 index_ready=false 定责。原始统计见 `followup/memory-authority-preflight.json`。

## 功能链路与界面追加改进

原报告第三至七节保留 M-01～05、F01～15、B-01～05、V-01～05 共 30 个编号，以及全部面板和十个设置子页的功能清单；本节记录在该基础上再次取证后实际补修的内容，不能将新增验收数量与原有重叠测试相加。

| 功能范围 | 本轮实际补修 | 关键源码位置 |
|---|---|---|
| 公共壳、缓存页面、工作区 | 排队刷新执行前再次核对 active 和代次；隐藏页不开始新请求；恢复页面重新刷新；工作区请求不向更晚对象提交结果 | `usePanelLifecycle.ts`、`useDomainRequest.ts`、`workspaceStore.ts` |
| 聊天、会话与附件 | 创建会话不抢先激活过期目标；历史加载合并在途新消息；回复绑定原消息身份；读取附件期间禁止发送；切换会话取消旧读操作；失败草稿合并更晚文字及文件；翻译核对原消息版本 | `ChatPanel.vue`、`chatStore.ts`、`sessionStore.ts` |
| 语音、舞台与模型 | 单 URL 播放补齐 finish 终态；旧 URL 的迟到解析不终止新播放；移除结束媒体监听；后台 TTS 失败不停止前台音频；口型结果核对 renderer 和播放代次；临时 catalog 失败不覆盖正在加载的模型 | `audio/player.ts`、`BrowserPetStage.vue`、`chatStore.ts` |
| 记忆列表、Inspector、Review、Operations | 读结果提交同时校验范围、对象和代次；草稿按对象保存；删除预检和确认分开；批处理逐项记录 success/pending/failed/skipped；刷新失败不覆盖已发生的删除效果；维护操作单次执行 | `MemoryPanel.vue`、`useMemoryDomain.ts`、`memory-feedback.ts` |
| 记忆高级工具和设置记忆页 | 导入校验目标范围与每条记录；导出限定范围；召回显示不完整与 trace；未知重建终态不报成功；展示真实存储修订、索引代次及快照修订，缺失值不伪造 | `MemoryAdvancedTools.vue`、`MemoryStorageStatus.vue`、`SettingsMemorySection.vue`、`SettingsPanel.vue` |
| Prompt | 工作区和角色草稿隔离；保存与运行时应用分开反馈；运行时应用失败可单独重试，不重复保存 | `PromptPanel.vue` |
| 设置的访问、LLM、TTS、ASR、SVC、记忆、摘要、资源、系统、运行引导 | 保存失败阻止依赖新配置的发现、测试、预热及转换；规范化读回不覆盖更晚输入；清 secret 等旧保存完成并去掉队列旧值；无关保存不回传隐藏 TTS 凭据；资源逐项结果与重试；取消 ACK 和最终结果分开；保留第一轮 JSON/字符串模式及引导修复 | `SettingsPanel.vue`、各 `Settings*Section.vue`、`settings-client.ts` |
| SVC | 独立页重新激活刷新配置、隐藏后失效旧读取；保留冻结文件/配置/requestId 及可达与就绪区分 | `SVCPanel.vue` |
| Pet 与 Persona Memory | 脏参数不被自动刷新覆盖；动作核对能力版本、commandId 和结构化结果；拒绝/降级不报成功；导入后显示失败保留；关系历史隐藏时不因全局角色变化发请求 | `PetControlPanel.vue`、`RelationshipHistoryDrawer.vue`、`PersonaMemoryPanel.vue` |
| Tools | 调度前保存 unknown 请求身份；确认后重新查询原请求；审计不可用时阻止无法判断副作用的发送；预览及列表响应校验代次；保留第一轮批处理、独立错误与输入恢复 | `ToolPanel.vue` |
| Plugins、Infrastructure、Deploy、Agent Trace | 保留并复核第一轮执行/取消终态、按任务身份恢复、备份冻结计划、分层健康及部分失败反馈；共同使用修复后的页面生命周期；不增加不存在的安装能力 | 相应面板、`usePanelLifecycle.ts`、`useSystemDomain.ts` |
| Agent Governance | 重试超时或身份不符时保留绑定 event/delivery/attemptCount 的 unknown 锁；增加精确只读原投递查询，不再受最近 20 条限制；缺失记录仍为 unknown；没有自动重发 | `AgentGovernancePanel.vue`、`system-client.ts`、`connector_api.py` |
| I18n | 后端语言已切换但字典加载失败时显示部分成功，避免把两阶段写成一起失败；补相关中英日提示；保留 lookup 防乱序与缺键修复 | `I18nPanel.vue`、`settingsPanelMessages.ts` |
| Onboarding、健康和接口契约 | 绝对总预算、真实 provider 身份、avatar 单独重试、取消清理预算和 abort listener 回收；保留 Python identity/HMAC、真实 HTTP 授权边界及 manifest 验证 | `health_check.py`、`health_providers.py`、`onboarding-readiness-coordinator.ts` |

索引状态契约补充：SQLite 的 `authority_revision` 来自数据库权威修订，`index_generation=local:N` 只表示进程内索引代次，`index_snapshot_revision=null` 表示没有持久化快照承诺；组合远端索引的代次/快照来自 SQLite 已激活 generation 记录。缺失或未激活显示“未提供／尚未激活”，不能用界面推算一个版本号。

## 关键调用链与证据

| 调用链 | 修复后的契约 | 对应证据 |
|---|---|---|
| `/memory/docs` → memory routes → SQLite 权威提交 → IndexedBackend/VectorStore → `/memory/index/status` → Memory/设置 | 持久化、正文清理、索引失败及修订信息可相互解释；远端未清理时明确 pending | `python-memory-stream.log`、`python-memory-final-status.log`、`browser-settings-memory.json` |
| `/ai/stream` → `ai_api.py` → stream runtime → Generation → interrupt/disconnect 收尾 | 增量流可见；旧代次不会终止新代次；重复取消不二次取消持久化收尾 | `interrupt-stream.log`、`python-memory-stream.log` |
| `/health` → HealthChecker → provider snapshot → control/readiness | 截止后返回的成功无效；provider 替换不复用旧状态；进程存活和聊天就绪分开 | `health-budget.log`、`running-health-observation.json`、Electron readiness 单元测试 |
| `GET .../deliveries?delivery_key=...` → delivery store 单条只读 → public projection → 原投递恢复区 | 不重发、不回收租约；跨 connector 不返回记录；缺失不解锁 unknown | `connector-exact-query.log`、`system-client` 与治理定向验证 |

## 最终本地验收

最终检查日志统一位于 `improvement-evidence-2026-11-10/followup/`。浏览器使用本轮 `dist/renderer`，主入口 `main-BaVSr7Zo.js`，既有 control 只承担静态文件服务，不用旧后端的响应代替新源码验收。

- Electron 全套单元测试 **56 文件 / 392 项通过 / 20.22s**；lint、main/renderer type-check、build、renderer bundle audit 均退出 0；renderer 类型为 0，基线为空。
- 浏览器等待目标面板实际出现后覆盖 14 条导航、26 个主要页签，设置十个子页另有定向验证；所有记录视口横向溢出为 0，pageerror 为 0。
- 390×844 中发送按钮范围 `(302,770)–(346,814)`，无遮挡且可获得焦点；主入口资源与最终构建一致。
- 合成数据验证：非法 JSON 不发写请求；刷新保留记忆草稿；索引失败及孤立诊断可见；删除预检失败不提交删除；一次合成删除返回 pending 后持久显示待恢复警告，未显示索引清理完成；修订字段可见。
- 浏览器拦截真实写请求；总览中的 55 个 409 均来自本地只读拦截，没有额外 HTTP 失败；这会使自动保存或设备诊断显示失败提示，不能据此判断真实写接口异常。合成删除由浏览器 fixture 响应，未到真实后端。
- Python 记忆/HTTP 流八文件 104 项通过；追加状态字段后两文件 43 项通过，两组有重叠，不累加。
- 既有 connector resolution 4 项回归通过；原投递精确查询隔离验证通过：超出最近 20 条、特殊字符 key、跨 connector、缺失、过期租约、公开字段及重启读回，未调用供应商或回收租约，详见 `connector-exact-query.log`、`python-connector-resolution.log`。
- 两个独立 MCP 的 Node 测试分别 11、7 项通过；Go 再次使用 1.27.0 执行 `go test -count=1 ./...` 通过，详见 `go-launcher.log`。

首次 Electron 全套记录保留为 `electron-unit-first.log`：SVC 四项因 SFC 测试未注入新增的真实生命周期 composable 失败，现已改为真实组件作用域；HTTP 客户端首次导入超时并干扰下一用例，独立 24 项全通过。最终全套控制 worker 数为 4，完整结果为 **392/392 通过**，保存 `electron-unit.log`。测试没有提高超时或跳过用例。浏览器旧版固定 650ms 等待也已改为按目标面板可见性等待，避免把迟到页面误记为已覆盖。

## 现场边界

现存 Python/control 服务未重启，新后端不能由旧进程响应证明已加载。先前启动隔离后台服务被自动审批策略以 `blocked by policy` 拒绝，未绕过。真实麦克风/扬声器、LLM 生成、SoulX 模型、Qdrant、扫码登录和连接器/OBS/Twitch 真实投递仍需具备对应服务与硬件的现场验证。
