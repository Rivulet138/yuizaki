# 前端面板功能审计与改进矩阵

## 范围与运行证据

14 条导航记录对应 13 个实际目标：deploy 重定向 infrastructure；SVC 独立旧路由仍可访问，同时嵌入设置。OverviewPanel 有源码但未被当前导航加载，不能计作已暴露面板。公共工作区抽屉、运行引导、聊天舞台与设置子页也纳入。

静态结论来自当前工作树；浏览器实测针对 38945 控制端口提供的构建产物。两者不是同一证据：不能把源码推断写成浏览器实测故障，也不能用旧构建正常覆盖工作树问题。

实际运行：

- 遍历全部 14 个路由，1440×900 页面级横向溢出均为 0，未记录 pageerror。
- 第二轮启动捕获一次 GET /api/workspaces 504，以及自动 PATCH /api/workspaces/default 的 5 次 409。409 可由乐观并发保护正常产生，未证明用户修改丢失，不能单凭状态码判定丢数据。
- Settings 10 子页、Memory 3 子页、Tool 5 子页、Governance 4 个主子页、Trace 4 子页，共 26 次主要页签切换；该轮未捕获 HTTP 4xx/5xx 或 pageerror。页签数量不表示每个嵌套页签或每项操作均执行过。
- 768px 下检查 chat/memory/settings 无发现越界元素；390px 下 chat 的模型选择器 x=452..606、回复模式选择器 x=612..694，均位于视口右侧；根 scrollWidth 仍为 390，说明根溢出检查会漏掉内部裁切。
- 未提交真实聊天、发送消息给连接器、转换真实音频、恢复备份、删除用户记忆或修改业务源码；数据改变类操作通过代码审计和隔离探针评价。

机器证据：`audit-evidence-2026-11-09/browser-panels.json`、`browser-subpanels.json`、`browser-runtime-detail.json`，均有可重跑 Python Playwright 脚本。

## 已确证的静态问题及修复验收

“静态确证”表示问题控制流确实存在，实际用户影响仍依赖触发条件；只有带运行/探针证据的项可称动态复现。

| ID / 优先级 | 证据与触发 | 具体改进 | 验收 |
|---|---|---|---|
| F01 / P1 | InfrastructurePanel.vue:460 任意有效 dry-run 能启用恢复；:743 执行读取当前目录，未绑定预览目标。 | 预览保存规范化目录、计划 ID 和摘要；目录或选项改变使预览失效；提交同一冻结计划。 | 预览 A 后改成 B，不允许直接恢复 B；真正恢复结果关联原计划。 |
| F02 / P1 | shared/composables/useDomainRequest.ts:33 保护内部 data 但仍返回旧 result；useMemoryDomain.ts:369、usePluginDomain.ts:51、useSystemDomain.ts:88 又提交到独立 ref。 | 展示派生自受保护 data，或提交时检查代次及 workspace/scope/entity。 | A 慢 B 快，逆序返回只能显示 B；删除后的旧刷新不能恢复旧列表。 |
| F03 / P1 | AgentTracePanel.vue:820 发送 interrupt 后无条件提示已请求取消；net/socketClient.ts:236 离线只记日志，不返回发送失败。 | 发送返回接受/离线/拒绝；展示等待 ACK、执行终态、超时未知。 | 离线不提示已发送；发送成功也不提前显示已取消。 |
| F04 / P1 | app/BrowserPetStage.vue:315 加载成功前更新 currentModelKey；失败仅日志，相同 key 后续跳过。 | 成功才提交当前 key；失败保留旧模型并提供重试；模型请求加代次。 | 同一 URL 首次 503、随后 200，不换路由可恢复；快速切换只保留最新模型。 |
| F05 / P2 | BrowserPetStage.vue:245 异步初始化缺少卸载代次检查；:335 只清理卸载时已创建资源。 | 每个 await 后验证实例存活，迟到资源立即 dispose；轮询不重叠。 | 初始化期间离开，迟到响应不创建 renderer/observer/interval。 |
| F06 / P2 | InfrastructurePanel.vue:656 固定读取 default 的 effective preset。 | 使用当前 workspaceId，切换时刷新并丢弃旧结果。 | 两工作区 preset 分别正确，非 default 不显示默认配置。 |
| F07 / P2 | MemoryPanel.vue:1132 删除预检与确认共用 catch，预检失败被当成用户取消。 | 拆开预检失败和弹窗取消，预检有 pending/error。 | 401/500/超时可见，未删除；用户取消无错误提示。 |
| F08 / P2 | PromptPanel.vue:89 刷新覆盖 persona 编辑框；MemoryPanel.vue:1356 Inspector 更新只检查 saving，未保护 dirty。 | 草稿按实体保存，刷新 dirty 时保留输入并显示差异。 | 未保存修改遇到刷新/后台更新不丢失，切实体不串草稿。 |
| F09 / P2 | SettingsPanel.vue:2892 单键读写缺少局部忙碌/错误；:2898 无效 JSON 退回原字符串。 | 明确 JSON/字符串模式、类型校验、请求互斥和错误。 | JSON 模式 `{broken` 不发送；失败保留输入并允许重试。 |
| F10 / P2 | useSettingsDomain.ts:46、SettingsPanel.vue:1775 保存后合并提交 patch，未用服务端规范化值回填。 | 使用规范化响应或受控 GET，保护更晚未保存输入。 | 后端钳位/规范化后，表单最终与 GET 一致；不误报原值已生效。 |
| F11 / P2 | AppShell.vue:49 按 route.name keep-alive；多个页只在 onMounted 加载；AgentGovernancePanel.vue:1339 轮询仅卸载时停止。 | onActivated 刷新，onDeactivated 暂停页面轮询；后台任务另定归属。 | 返回页数据不过期；隐藏页无无界/重叠轮询；显示更新时间。 |
| F12 / P2 | I18nPanel.vue:100 多种操作用不同序号写同一语言状态，:165/:177 lookup 无请求代次。 | 共享语言提交代次；lookup 绑定 key、locale、序号。 | 乱序响应不回退语言，不覆盖最新查询。 |
| F13 / P2 | ChatPanel.vue:1596 图片/二进制附件只生成文字说明，:1623 发送文本，没有真实图像内容。 | 明示支持的文件类型；若提供识图，发送真实图像引用/数据并校验大小、MIME。 | 图片输入的 UI 说明与网络 payload 一致，不能把文件名当图像已上传。 |
| F14 / P2 | app/composables/useUiCapabilities.ts:61 已定义能力查询，但引用搜索只找到定义。 | 将 capability 接入操作门控，区分浏览器本地、宿主 HTTP、Electron IPC。 | 每个受限操作说明原因和替代入口，支持的 HTTP 操作仍可使用。 |
| F15 / P2 | 390px 浏览器实测两个 ChatRuntimeSettings 选择器在右侧视区外，详见 browser-subpanels.json。 | 窄屏 runtime 控件换行或收纳至设置弹层；按输入区实际宽度布局，检查祖先 overflow。 | 390px 模型、回复模式、发送按钮均在视区内，键盘焦点可见；不只检查根 scrollWidth。 |

上述路径未写绝对前缀的，均位于 `E:/yuizaki/electron/src/renderer/`；F11 的 AppShell 属于 app 目录。行号以本批次工作树为准，环境文件已记录 SHA256。

## 面板功能、调用入口与改进

| 面板 | 实际功能与调用入口 | 具体改进与验收 |
|---|---|---|
| 公共壳与工作区 | router.ts:4、app/AppShell.vue:3；工作区路由、主题/语言/通知/快捷键、缓存、voice/companion runtime；workspaceStore、settingsStore、inputBindingsStore。 | 切工作区建立统一刷新契约，丢弃旧实体结果；深链、返回缓存页均正确。工作区保存显示 saving/saved/conflict/failed，自动 PATCH 的 409 必须能解释并收敛；不把接口失败伪装为空工作区。 |
| 聊天舞台 | app/BrowserStageView.vue:240、BrowserPetStage.vue:245；Live2D/VRM、fallback、缩放复位、拖拽宽度记忆、沉浸语音、字幕、录音/播放、口型事件。 | F04/F05/F15；断线状态覆盖文字与语音；字幕随 generation 清理；离页无残留资源。 |
| Chat | domains/chat/views/ChatPanel.vue:1067；会话新增/改名/置顶/归档/删除/分支，消息搜索/复制/引用/编辑重发/再生成/删除，上下文、草稿、快捷语、附件、翻译、参数、语音中断、遗忘。通过 chatStore/sessionStore、sessions/history/messages、Socket Agent/LLM/ASR/TTS/interrupt。 | F13；断线保留草稿、服务端失败不删除本地消息、切会话不串流；翻译结果绑定原消息版本；TTS 桥接修复后验证最终 busy 清除；生成与持久化分别确认。 |
| Memory | domains/memory/views/MemoryPanel.vue:431；Library/Review/Overview、scope、筛选、详情编辑、分层、回滚、审核、遗忘/恢复、永久/批删、导入导出、召回反馈、重建取消、维护。通过 useMemoryDomain、memoryClient docs/overview/candidates/operations/import/export/index/maintenance/query。 | 优先修记忆报告五项缺陷；F02/F07/F08；明确权威已写入与索引待恢复；批处理逐项结果，重建有终态；错误、空列表、零结果分开。永久删除必须覆盖导出和派生索引。 |
| Prompt | domains/prompt/views/PromptPanel.vue:81；工作区 system prompt、companion persona 编辑/保存/刷新/运行时应用；workspaceStore、companionStore、runtime bridge。 | F08；保存与应用 runtime 分别反馈；草稿按 workspace/companion 隔离；保存失败不显示全部生效。 |
| Pet | domains/pet/views/PetControlPanel.vue:767；模型选择/导入/删除、关系历史、缩放透明度、免打扰/穿透/锁定、常驻/位置/显示器/停靠、动作表情参数/idle/口型/显隐重载；petControl IPC 与 /api/pet/* HTTP fallback。 | 按具体 capability 门控；本地文件路径注明宿主路径；显示器失败不阻断模型列表；动作接受与渲染完成分开；删除当前模型后 catalog/state/stage 一致。 |
| SVC | domains/tools/views/SVCPanel.vue:161；服务检查、音频选择、转换、播放、设置跳转；settingsClient、POST /svc/convert、beforeAction flush。 | 文件与已保存配置快照绑定转换；A 转换时选 B 不误标 A 结果为 B；保存失败不继续旧配置转换；错误持续可重试。 |
| Tools | domains/tools/views/ToolPanel.vue:608；Status/Stream/Capabilities/Skills/History，能力快照、技能导入筛选批删、Twitch/OBS 配置、订阅、接管审核、事件、草稿生成消费重试发送、动作确认审计；systemClient、pluginClient。 | 动作结果与后续刷新结果分开；幂等标识贯穿重试；请求超时显示未知并查询终态；批删冻结选择集合；每列表独立错误和更新时间。 |
| Plugins | domains/plugin/views/PluginManagementPanel.vue:490；搜索分类/问题过滤、manifest/权限/routes/tools/pet events、加载错误、活动执行取消、审计；usePluginDomain、pluginClient.list/cancelExecution。未暴露安装卸载/启用开关。 | F02；取消接受与终态分开；空列表与加载失败分开；说明该面板与治理页 agent plugin 的职责。 |
| Infrastructure | domains/system/views/InfrastructurePanel.vue:641；环境/runtime/cache、系统/DB/统计/模型/preset、JSON/CSV 导出、备份预览恢复、日志、内嵌 Deploy。 | F01/F06；导出显示 scope；子请求部分失败保留成功数据；日志/诊断标时间；恢复必须与预览同目标。 |
| Deploy | domains/deploy/views/DeployPanel.vue:189；health/readiness/provider 检查、后端启停、API 文档、平台命令复制；systemClient.pythonHealth/providers、summaryClient.getReadiness、petApi.python。旧路由跳 Infrastructure。 | 浏览器 IPC 启停禁用与 onboarding HTTP 启动入口统一解释；进程存活、依赖健康、聊天就绪分别显示；不能只凭 control /api/health 的固定 ok 显示全健康。 |
| Agent Governance | domains/system/views/AgentGovernancePanel.vue:1205；Connectors/MCP/Permissions/Extensions，Telegram/Discord/QQ/微信配置探测、恢复取消/投递重试、账号绑定、QQ bridge 安装启停扫码、MCP/预设、权限清理、agent plugin 配置；systemClient。 | F11；保留“已保存但探测失败”区别；清 secret 后防旧保存回写；恢复绑定 event/delivery；已完成投递不重复发送；离页扫码轮询有界。 |
| Agent Trace | domains/system/views/AgentTracePanel.vue:522；Status/Jobs/Schedules/Traces、指标、请求轨迹、恢复/重试/副作用未知确认/recheck/取消、一次/周期任务创建启停立即执行删除、导出；systemClient、Socket。 | F03/F11；job/run/request 关联不可丢；离线取消不报成功；未知副作用保留人工确认；调度失败保留输入，终态更新及时。 |
| Persona Memory | domains/memory/views/PersonaMemoryPanel.vue:164；heartbeat、亲密度、行为事件/抑制原因、建议、表情动作触发、聊天建议；systemClient.heartbeat、petControlClient、appendLocalAdvice。 | 事件时间、角色/模型身份可见；历史行为不描述成当前；按 avatar capability 禁用不可用 motion；建议写入聊天与事实记忆分开。 |
| I18n | domains/i18n/views/I18nPanel.vue:100；前端语言同步、后端语言切换、字典预览、普通/错误消息 lookup；i18nClient、setLocale。 | F12；各阶段单独结果；补六个英文键；后端失败时说明前端是否已改变；乱序查询稳定。 |
| Onboarding | domains/onboarding/views/OnboardingGate.vue:184；snapshot、启动/取消后端、扫描重试、LLM 设置、安全修复、可选/语音/设备检查、跳过/重开；petApi.onboarding 或 /api/onboarding/*。 | 展示扫描时间、原始错误和重试入口；跳过与通过分别记录；浏览器设备检测与服务端 snapshot 分开反馈。 |

## 设置十个子页

共同入口 SettingsPanel.vue:61、useSettingsDomain 与 settings-client.ts:327。已有一秒去抖、串行保存、失败 patch 保留与重试，应保留这些行为。

| 子页 | 已实现功能 | 改进及验收 |
|---|---|---|
| 访问 | backend token 状态/保存/重置，/api/system/backend-token | 保存、需重启、失败分别反馈；准确描述 loopback 信任模型；补英文消息；保存后重读一致。 |
| LLM | provider/profile、URL/key/model、模型和本地发现、参数、推荐值、测试、独立 vision | 格式/保存/可达/模型可用分开；后端规范化值回填；测试前 flush 失败不继续；错误定位字段。 |
| TTS | provider/profile/key、角色、本地发现、状态、warmup、测试、重置 | 持久化、runtime applied、资源就绪、播放完成分开；warmup 失败可重试；切 provider 不复用旧角色；完成后不 busy。 |
| ASR | provider/模型/路径/凭据、识别参数、本地发现 | 清理或显式保留不兼容隐藏字段；宿主路径标识；缺资源与读取失败分开；清凭据不被旧保存复活。 |
| SVC | provider/endpoint/speaker/pitch/timeout、本地发现测试重置及内嵌转换 | 转换绑定保存成功的配置；保存失败不运行；结果绑定文件与请求；超时说明一致。 |
| 记忆 | backend/embedding、本地发现、索引重建 | 等待实际 backend 应用后重建；显示存储与索引版本/健康；超时不显示已生效；重建、取消、失败均有终态。 |
| 摘要 | 摘要策略配置 | 标明全局/工作区作用域及对新旧摘要的影响；重读一致；切工作区不误以为独立配置。 |
| 资源 | 批量下载/取消、SoulX参考、Sherpa/online/embedding/TTS下载删除、分类和全清 | 未安装、读取失败分开；逐项已删除/跳过/失败；取消确认终态；部分失败可单项重试，轮询有界。 |
| 系统 | 主题语言、输入绑定/浏览器 fallback、metrics consent、metadata/history/清历史/rollback、单键读写重置 | F09/F10；键位冲突可见；不抢输入框快捷键；回滚后刷新值与历史；JSON 模式校验。 |
| 运行引导 | 重开 onboarding | 显示上次扫描时间和跳过/通过，重开读取新 snapshot；旧 completion 不掩盖当前失败。 |

## 运行引导专项结论

1. Electron `http/routes/onboarding-routes.ts:34` 的 GET snapshot 返回存储快照；coordinator.ts:196 不实时探活。
2. OnboardingGate.vue:226 对非运行、非空失败快照停止自动轮询，旧失败可能持续显示。
3. shared/onboarding-readiness.ts:95 的 readyForText 要求 backend.service、llm.provider、llm.model_chat 都通过。
4. main/python.ts:138 管理模式核对 runtime 身份；:256 外部管理模式核对 challenge HMAC。普通 ping 200 不等于这两个验证已经通过。
5. coordinator.ts:322 合并时 host probe 覆盖同名 Python probe。
6. OnboardingReadinessRail.vue:102 中文无具体 messageKey 时使用通用文案。运行实证 snapshot 中 backend.service.message 为 `timeout of 2000ms exceeded`，UI 只显示通用失败。
7. OnboardingGate.vue:435 跳过和开始均写同一个 completion；旧上下文直接进入应用不能证明 readiness 通过。
8. OnboardingGate.vue:189 的 browser reportDeviceProbe 忽略 report，仅重读 snapshot，服务端状态不会因此记录浏览器设备检查结果。

运行中 ping 很快但 snapshot 仍 backend failed；只能确认当前显示快照与普通存活观测不同，不能据此认定宿主身份校验应当通过。改进应提供 fresh scan、扫描时间、分层健康与具体错误，保留身份校验。
