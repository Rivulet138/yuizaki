# 2026-11-10 追加排查问题修复与验收

本轮承接“检查遗漏”新增的 12 项问题，直接实施改进。之前 M-01～M-05、F01～F15、B-01～B-05、V-01～V-05 的措施与现场边界保留于 `improvement-2026-11-10.md` 和 `improvement-followup-2026-11-10.md`。本文件记录追加问题，不用旧验收结果代替当前代码验证。

## 问题与改动

| 编号 | 原始问题 | 改进与验收范围 |
|---|---|---|
| A01 | session 记忆只校验 session_id，可跨工作区查询或维护删除 | routes、召回流水线和向量过滤共用 workspace+session 归属规则；维护执行对最新候选逐条校验，整批通过后再删除；真实路由与临时 SQLite 验证跨域列表、export、recall、operations、维护、PUT、DELETE。 |
| A02 | session import 丢失 workspace_id，之后可被其他工作区操作 | 导入保留合法归属，检查整批来源；归属冲突整批拒绝，旧无归属记录要求明确指定；不根据活动工作区猜测。重启读回验收。 |
| A03 | 直接复制 SQLite 主文件丢失已提交 WAL 数据 | 使用 Python 标准库 SQLite online backup，校验完整性，产生独立快照；现代快照恢复也通过 SQLite 事务协议写入，避免旧 WAL 覆盖恢复内容。临时真实 WAL 数据库验证快照和持有连接时恢复。 |
| A04 | 设置读—合并—替换跨请求竞争导致丢更新 | 将读取、验证、合并、提交放在相同提交锁中；并发不相交 patch 均保留；版本与快照沿用现有持久化契约。 |
| A05 | 迟到 session 列表把新工作区的选中项改回旧会话 | 工作区切换与新请求递增代次；旧结果不写列表、选中项和 loading；覆盖 A→B→A 与乱序返回。 |
| A06 | KeepAlive Chat 各自保存整份草稿，覆盖其他实例 | 同一 Storage 共享响应式草稿与防抖队列；输入框直接读写共享草稿；default 草稿按工作区隔离；失败按发送时捕获的工作区恢复。 |
| A07 | to_thread 发送取消后释放租约，允许重复外发 | 发送一旦开始，取消/丢响应/本地确认失败保留 sending 与 owner；全部连接器禁止对未决投递重新 claim/reset；明确未发或明确拒绝才可重试；使用阻塞假 sender 和临时 SQLite 验证。 |
| A08 | 资源重载失败只有日志，同值保存无法恢复 | 增加可查询、带目标修订的重载状态与明确重试；配置提交和运行资源完成分别表达；前端显示状态与失败恢复入口。 |
| A09 | 调度首次执行前取消，active 与 created 永久残留 | 取消路径补做终态持久化；收尾按具体 run 身份幂等；停止时先取消整批再等待；旧 run 不能清除新 run，保留已有 durable 终态。 |
| A10 | export/import 丢失 layer，profile fact 变 semantic | 导出显式 layer，导入兼容显式字段与旧 metadata.layer；写前整批验证。7 个 layer 在 workspace/session、新旧格式往返验收。 |
| A11 | 备份目标写死默认 chat.db/memory.db，漏掉自定义路径 | 新增只读运行源接口，读取实际 repository 与解包后的记忆 authority 路径；后端不可用或旧版无接口时按真实配置离线解析并提示来源；恢复白名单与预览使用同一次解析的目标；非文件数据库显式拒绝，memory-only 不备份遗留同名磁盘文件。 |
| A12 | 缓存设置面板保存其他字段时附带旧完整 profiles，覆盖别处配置 | 普通 LLM 字段仅发改动字段及当前 profile 对应字段，不携带其他 provider 的整份缓存；重新激活面板回填最新数据并保护 dirty、排队及请求期间的新输入。 |

## 代码入口

- 记忆：`python/modules/memory/{routes,metadata,pipeline,vector_store,sqlite_store,operations}.py`。
- 设置：`python/modules/system/{settings_api,settings_models}.py`、renderer settings domain、SettingsPanel 和 settings client。
- 会话与草稿：`electron/src/renderer/stores/sessionStore.ts`、`domains/chat/composables/useSessionDrafts.ts`、`domains/chat/views/ChatPanel.vue`。
- 备份：`electron/src/main/backup-snapshot.ts`、`http/routes/system-routes.ts`、`python/modules/system/backup_snapshot.py`、`python/routes/storage_api.py`、`python/app.py` storage router provider。
- 连接器与调度：`python/routes/connector_api.py`、`python/modules/agent/{turn_store,scheduler}.py`。

## 验收记录

本轮 12 项已完成代码改进；现场联调边界见下节。`source-build-snapshot.json` 记录 86 个源文件及构建文件的 SHA-256，用于对应本轮验收；`diff-check.log` 对应最终 `git diff --check` 退出 0。证据位于 `improvement-evidence-2026-11-10/additional/`。

| 验证 | 最终结果 | 证据 |
|---|---|---|
| Electron 全套单元测试 | 60 文件 / 448 项通过，20.96s | `electron-unit-verified.log` |
| Electron lint、main/renderer 类型、构建和 bundle audit | 全部退出 0；renderer 0 错误，未扩大基线 | `electron-lint-verified.log`、`electron-types-verified.log`、`electron-build-verified.log` |
| Python 合并定向回归 | 26 文件 / 483 项通过，36.64s；包含记忆、连接器、调度、备份、设置、凭据、路由契约 | `python-final.log`、`python-final.xml` |
| Python 修改模块与 app/settings 类型 | 0 errors、0 warnings | `python-types.log`、`python-app-settings-types.log` |
| Python 新增备份与运行 hook 文件 Ruff | 通过 | `python-new-ruff.log` |
| Python 14 个相关实现文件 Ruff 对照 HEAD | 26 条既有诊断；HEAD 为 28 条，按规则、消息、对应源码行比对无新增；未宣称全仓 Ruff 清零 | `python-ruff-comparison.json` |
| 浏览器设置和记忆 | 设置十页、非法 JSON 不提交、索引失败、孤立会话诊断、草稿保护、删除预检失败、pending 清理提示通过 | `browser-settings-memory.json` |
| 浏览器运行服务恢复 | 合成 failed → applying → applied，按 svc:7 重试一次，应用后隐藏重试按钮；配置/服务/资源说明可见；未调用真实重载接口 | `browser-runtime-recovery.json`、`settings-runtime-recovery.png` |
| 浏览器离线备份来源 | 本地配置来源和 memory-only 排除说明可见 | `browser-runtime-recovery.json` |
| 浏览器全导航及响应式 | 14 条导航、26 个主要页签；390px/768px 关键面板无横向溢出，pageerror 为 0 | `browser-acceptance.json`、`browser-acceptance-verified.log` |
| 浏览器 390×844 聊天 | 发送按钮 (302,770)–(346,814)，无遮挡、可聚焦，pageerror 0 | `browser-chat-final.json`、`chat-390.png` |

最终浏览器全导航记录的 HTTP 失败中，54 个 409 来自写请求拦截；其余 404 为旧后端缺少 `/api/settings/runtime/status`，前端按无法确认应用状态处理。重载恢复的新接口通过真实 SettingsAPI 定向测试和浏览器合成响应分别验证，不将该 404 算作新服务已部署。

最终浏览器构建主入口为 `main-Bd9BWULF.js`；fixture 和写请求拦截均记录在脚本及 JSON。既有服务只用于静态文件与只读信息，不把旧 Python 服务的响应当作新后端已加载的证据。早期失败日志保留，不以增加超时或跳过断言处理功能失败。

## 集成复核中追加关闭的边界

- 旧 manifest 缺少 snapshotMethod 时仍按 database/memory 角色使用 SQLite API 恢复，避免现存 WAL 覆盖恢复结果。
- 每次异步步骤前后重验冻结源与 manifest；已有快照修改、原本缺失的快照迟到出现均返回 409，不继续写后续目标；若已有部分恢复，返回已恢复列表和明确消息。恢复执行互斥，防止两个 apply 交错。恢复仍不是跨多个目标的原子事务。
- 目录源包含备份目标时拒绝自我复制；恢复目标包含备份目录也在预览阶段拒绝。
- 离线 SQLite URL 复用已有 SQLAlchemy make_url，支持 sqlite+pysqlite，拒绝空 database、:memory: 和非 SQLite；新增依赖为零。
- app.py 的记忆重载失败向状态层传播并保留旧 authority；设置重载的 vision 初始化失败也传播，保留启动时可选 vision 的原行为。实际 hook 定义与 SettingsAPI 状态链有 5 项回归，未导入 app 启动真实资源。
- 运行状态卡片的默认插槽曾覆盖 description：说明改为插槽中的实际文本，计算值显式读取 ref；3 个状态文本单测与浏览器真实渲染验证失败、应用中、已应用。
- 新记忆布局中重新接入已有 MemoryStorageStatus 到高级工具抽屉，恢复存储修订、索引代次、失败及孤立会话诊断。验收脚本按真实抽屉交互定位，保留现有布局。
- 对工作区同时存在的新模型参数注册表，仅补充 custom provider 必有属性的类型声明与索引访问写法，使严格类型检查通过；保留其功能改动。

## 适用边界

- 测试使用合成记录、临时 SQLite、假 embedding 和受控 sender，不删除用户真实记忆、不对供应商真实发送。
- 单个 SQLite 快照包含其一致性事务状态；多个数据库、设置及音频之间不承诺同一全局事务时刻。目录与普通文件沿用现有备份方式；旧格式备份仍兼容，不能据此追认旧快照包含了当时 WAL 数据。
- 离线源标注 `configured_offline`，只能证明当前本地配置，不能替代对运行中旧后端实际路径的核对。收到运行源接口的授权或初始化错误时明确失败，不回退到另一套默认路径。
- 恢复设置、记忆索引和其他运行资源仍须遵守界面列出的重新加载/重建提示；本轮没有做物理介质安全擦除或删除旧备份。
- 现存服务、真实供应商、硬件和外部服务的现场验证与代码/临时环境验收分别记录。
