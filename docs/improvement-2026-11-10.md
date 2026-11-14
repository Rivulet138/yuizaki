# Yuizaki 全面改进方案与本地实施验收记录

> 续作已实施：[2026-11-10 追加修复与最终验收](improvement-followup-2026-11-10.md)。下面的 353 项测试、类型声明及 Go 阻塞是第一轮历史快照；本轮已将类型错误收紧为 0，并通过 Go 1.27.0 启动器测试。最新结果以续作记录及 followup 证据为准。

日期：2026-11-10。范围：工作区实际公开的 Python HTTP/Socket、Electron control/宿主接口、长期记忆、浏览器面板与设置子页；兼顾两个独立 MCP 和 Go launcher 的既有验证边界。

依据：`audit-2026-11-09-frontend.md`、`audit-2026-11-09-memory.md`，以及 backend、verification 和总报告。原始缺陷取证不覆盖、不改成成功记录。共覆盖 **M-01～M-05、F01～F15、B-01～B-05、V-01～V-05，30 个原编号条目**，并补充健康、引导、工作区冲突和外部动作未知结果。

本文件把“完整改进要求”和“本轮实际处置”放在一起。已实现表示源码已变更；本地验收表示合成数据、函数、真实临时 HTTP 入口或浏览器证据支持该契约；不等于现存后端进程已加载、真实供应商已联调或原始运行异常根因已查明。

## 一、目标、顺序与状态约定

所有操作应区分：请求已接受、持久数据已保存、运行时已应用、索引已就绪、执行已完成。取消请求还应区分离线、已发送、ACK、终态和未知。网络可达、服务就绪、模型可用、实际播放结束也分别反馈。

| 批次 | 实施内容 | 依赖与完成标准 |
|---|---|---|
| 0 | 固定解释器、源码、构建与运行进程身份；保留原有改动和缺陷取证 | 后续证据可以对应源码和运行环境；使用项目 `.venv` 验证业务 Python |
| 1 | 记忆 M-01～05、TTS 完成 V-01、并发取消 B-02、ASR B-03、插件持久化 B-04 | 先修权威数据与终态契约，再调整前端显示 |
| 2 | F01～10、工作区冲突、任务/动作恢复 | 预览冻结目标；旧响应不覆盖新实体；失败保留输入 |
| 3 | B-01/B-05、V-04/V-05、健康与引导 | 真增量 SSE、完整路由清单、准确授权说明和分层健康 |
| 4 | F11～15、全部面板、设置十子页 | 生命周期、能力门控、局部错误、批处理结果和窄屏可用性 |
| 5 | 历史异常检查、当前构建验收、剩余现场问题 | 按编号登记证据及缺口，不用测试数量替代产品行为验收 |

第一轮没有增加依赖，没有扩大类型基线，也没有执行真实用户数据删除、备份恢复或外部平台发送。原有十个前端修改保留，并在必要处做集成修复。

## 二、长期记忆：完整机制与五项缺陷

链路一：已提交 turn → 用户信号投影 → 候选准入/provenance → candidate ID 幂等 → SQLite 权威数据 → 进程文档与派生向量。

链路二：请求上下文 → scope/layer/state 过滤 → 向量/词法评分与可选 rerank → 关联扩展 → top-k/token 预算 → 带来源的不可信证据注入。

链路三：会话历史 → 摘要压缩/修订校验 → 独立摘要上下文。摘要不能等同于长期事实，也不能等同于向量索引。

保留原有准入、来源校验、访问限制、幂等、authority revision 和 prefetch 失效保护。当前普通聊天按明确 scope 召回，没有自动合并 global/workspace/session 三层的承诺。未来如需继承合并，应单独设计冲突优先级，不能静默改变现有范围。

| 编号/优先级 | 完整改进要求与本轮处置 | 验收与边界 |
|---|---|---|
| M-01 / P1 | 候选墓碑只保留最小 ID、范围、状态、时间和 revision；正文清空，嵌套 evidence/history 等移除；删除关联操作日志自由文本和索引引用；单删、批删、维护删除共用规则；启动迁移清理旧墓碑；低层同 ID 重放不得复活 | 合成数据覆盖三种删除、all-state 导出、日志、重启和重放。墓碑仍存在用于防重放。此处不是文件取证级安全擦除，也不自动擦除 SQLite 页/WAL、旧备份、聊天历史和摘要 |
| M-02 / P1 | metadata-only 写入/同 ID 替换同步文档视图、失效旧向量；检索可靠补建缺向量记录；排除非可召回和删除记录；重建发布时核对文档身份及正文 | 先检索再写入、同 ID 替换均可不手工重建而召回；覆盖 SQLite 和内存后端。并发重建不发布旧正文向量 |
| M-03 / P1 | SQLite 提交后立即同步运行视图；embedding 失败保留已存记录并记录每文档索引错误；API 分开返回 storage_status/index_status | 故障时记录可见且状态 failed，重启后可恢复索引；同 ID 重试不重复写。不能把“已存储”显示为“已可召回” |
| M-04 / P2 | 更新时验证合并后的最终 scope/workspace/session；null、空白和缺失会话都遵守约束；overview 显示孤立会话记录诊断 | 非法变更 400 且原记录不变。已有归属不明记录需显式指定，未擅自迁入 global 或猜测会话 |
| M-05 / P2 | 每接受一个关系邻居前检查 relation_limit，准确设置 accepted/truncated | 一锚点六邻居、配额 1 时仅扩展 1 条；保留 top-k、去重、scope 和 token 预算 |

记忆面板还需要：Library 展示权威存储、索引状态和错误；Review 批处理逐项说明；Inspector 草稿按实体隔离并保护 dirty；导入导出说明 scope/include_state/session；索引任务显示 ID/进度/终态；召回调试区分原始得分与最终 chunks、来源、过滤和截断。前述状态显示、草稿、删除预检、终态和范围说明已同步调整。

删除反馈明确说明：长期记忆条目、派生索引与防重放墓碑是一组；已存在摘要、聊天历史和备份是独立保留范围。本轮实现 revision 失效和关联引用清理，没有承诺“所有上下文和所有备份立即遗忘”。旧数据迁移代码已经由临时数据库验证，未对运行中的真实数据库执行修复统计。

主要文件：`python/modules/memory/{metadata,vector_store,sqlite_store,operations,indexed_backend,routes,pipeline}.py`；`electron/src/renderer/domains/memory/`。

## 三、前端十五项缺陷逐项方案

| 编号/优先级 | 改进措施和本轮实际行为 | 验收标准/证据 |
|---|---|---|
| F01 / P1 | 恢复预览绑定规范化目录、manifest、源文件状态、目标影响摘要和 planId；执行端纯预览重算后校验；UI 冻结目标，修改选项失效 | A 预览后切 B、manifest/源目录/目标状态改变均拒绝旧计划，缺计划 409；临时备份案例通过。保留路径保护；未新增事务式恢复或执行期间文件锁 |
| F02 / P1 | 请求代次及 workspace/scope/entity 在结果提交处校验；memory/plugin/system 不再把旧返回值提交到独立 ref | A 慢 B 快只能显示 B；旧刷新不能恢复已删项目；共享请求回归覆盖 |
| F03 / P1 | Socket 返回 accepted/offline/rejected；Trace 等待匹配 request/session 的 ACK 和终态；超时保持未知；后端精准取消 request，不推进无关全局 epoch | 离线不报已发；旧 job 不取消新 generation；通用中断仍保留。新增两个后端 targeting case 通过 |
| F04 / P1 | 模型加载成功才提交 key；失败保留旧模型并可重试；快速切换由最新代次决定；渲染失败向 UI 传播 | 同 URL 失败后重试可恢复，旧请求不能覆盖新模型；BrowserPetStage 回归通过 |
| F05 / P2 | 每个异步边界检查存活/代次；迟到 renderer、observer、interval 释放；destroy 可重复调用 | 初始化期间离页无迟到资源创建或泄漏；与 F04 同组覆盖 |
| F06 / P2 | Infrastructure effective preset 使用当前 workspaceId，切换时丢弃旧结果 | 非 default 工作区不能显示 default preset |
| F07 / P2 | 删除预检、确认取消和实际删除拆开错误处理 | 合成预检 500 显示失败，未打开确认和提交删除；取消不显示错误 |
| F08 / P2 | Prompt/Memory 草稿按 workspace/scope/entity 管理；dirty 刷新保留输入，不用远端值覆盖 | 浏览器模拟远端文本变化后刷新，Inspector 草稿仍在；切实体不串草稿 |
| F09 / P2 | 设置单键明确 JSON/字符串模式；JSON 解析失败停止发送；局部 busy/error、保留输入 | 浏览器 `{broken` 显示无效 JSON，未发送 key 写请求 |
| F10 / P2 | 保存后以服务端规范化响应或受控 GET 回填；用草稿 revision 保留更晚输入；secret 清空串行提交 | 规范化和异步保存回归通过，不再将原 patch 当作已生效值 |
| F11 / P2 | keep-alive 以工作区+路由隔离；onActivated 刷新，onDeactivated 暂停页面轮询；后台任务终态另有归属 | 页面复入取得新状态，扫码/资源等轮询有界、不重叠；与实际任务生命周期区分 |
| F12 / P2 | 语言状态共享提交代次；lookup 绑定 key/locale/请求序号 | 乱序语言和查询不回退；诊断回归通过 |
| F13 / P2 | 文本附件读取真实内容；图片/二进制明确说明暂不支持，不再把文件名当作上传图像；大小和读取对象检查 | UI 与 payload 能力一致。没有新增真实图像上传/视觉附件协议 |
| F14 / P2 | 接入 capability，区分浏览器本地、宿主 HTTP 和 Electron IPC；说明不可用原因和宿主路径 | HTTP 支持的操作保留，IPC 专用项按能力禁用；Persona 动作按模型能力显示 |
| F15 / P2 | 聊天运行控件按实际容器宽度换行；工作区保存提示进入布局，不覆盖发送区 | 390px 模型、回复模式、发送按钮在视区内；中心点无遮挡，发送按钮可聚焦。768px 同样通过 |

## 四、后端五项与验证五项

| 编号/优先级 | 实施方案与本轮处置 | 验收/剩余边界 |
|---|---|---|
| B-01 / P2 | SVC probe 使用所选 provider 的 health/schema，返回 reachable 与 ready，ok 表示 ready；允许明确本机服务策略，保留其他目标和重定向限制 | 401/404/405/错误 schema/200 未就绪不能 ready；修正文档默认 127.0.0.1 本机探测契约；未调用真实 SoulX 模型 |
| B-02 / P1 | TTS 每调用持有自己的 task，取消只影响本次；disconnect 负责全部清理 | 并发 A/B 取消 A 不影响 B；合成并发探针通过 |
| B-03 / P2 | ASR 记录后重新抛出 CancelledError，外层 wait_for 正确进入超时归属 | 阻塞识别得到 TIMEOUT，保留用户取消语义；未使用真实麦克风制造超时 |
| B-04 / P2 | 插件启停/配置立即原子持久化，失败返回；高频 trace 仍批量 | 一次 toggle/config 后新 manager 重读一致，写盘失败不报已保存 |
| B-05 / P1 | HTTP SSE 由有界队列边生成边 yield；执行器完成后再处理 commit/终帧；断连传播取消并保护清理；不再重复完整文本 delta | 延迟两块文本在最终完成前收到第一块，断连取消及终态由真实 ASGI 流探针覆盖；Socket 路径独立 |
| V-01 / P1 | Player adapter 委托已有 markTtsStreamComplete；按 generation 完成且只发一次 | 正常、零音频、排队、打断、旧 generation 回归通过；未验证物理扬声器 |
| V-02 / P2 | 删除 SettingsPanel 无效初值，局部 const 表达实际赋值 | 最终完整 lint 通过 |
| V-03 / P2 | 补六个英文消息键；新提示补中英日；保护 lookup 意图 | i18n 10 项定向断言通过；原全套单元测试三项失败已消除 |
| V-04 / 边界 | 明确普通本机 API 信任 loopback，不把 backend token 描述为覆盖所有本机 API；专用 vault/感知/桌面动作边界保持 | 临时真实 HTTP 入口覆盖无 Origin、允许/拒绝 Origin、随机本机端口、错误/过期 token、OPTIONS、vault 拒绝；不是已证远程漏洞的修复结论 |
| V-05 / P2 | manifest 使用框架支持的路由展开，兼容旧版直接 APIRoute；避免只认私有类名 | include_router/嵌套/prefix/method 与 OpenAPI 比较；项目 FastAPI 0.143.2 和全局 0.128.0 均有隔离核验 |

主要入口：`python/modules/system/settings_api.py`、`python/modules/tts/openai_compatible.py`、`python/modules/asr/transcriber.py`、`python/modules/agent_plugins/manager.py`、`python/routes/ai_api.py`、`python/route_manifest.py`；以及 `electron/src/main/http/routes/`、`electron/src/renderer/audio/player.ts`。

## 五、运行异常与跨面板契约

### 健康和运行引导

- control `/api/health` 只表示 control 存活；Python `/api/ping` 表示进程存活/身份；`/health` 表示依赖健康；readiness 表示聊天条件；capability 表示可用操作。界面分别展示。
- HealthChecker 使用总预算，阻塞 snapshot 在线程执行并合并同类探测；慢取消清理不阻塞 HTTP 返回；迟到结果不能覆盖本轮；记录来源、时间、预算、耗时及 loop lag。
- 隔离注入中，40ms 预算+300ms 同步 TTS 状态从原 300.5ms/错误 healthy 变为 53.1ms/unhealthy；180ms 取消收尾从 233.6ms 变为 47.1ms。证明已修的阻塞/预算机制，不证明历史超过 8 秒异常的唯一根因。
- 引导提供 fresh scan、原始错误、探测时间与来源；保留 managed runtime 身份与 external challenge HMAC。
- passed/skipped 分别记录；浏览器设备报告真实写回 snapshot，矛盾报告 400；旧 completion 不等于本次就绪。
- 浏览器能使用现有 onboarding HTTP 启动入口；停止仍按进程管理/IPC 能力判断。

历史 `/health` 超时没有栈或逐项耗时证据，**根因仍待现场复测**。本轮不把其归因到某个供应商、DB 或记忆。

### 工作区与外部动作

- 工作区保存串行化，显示 saving/saved/conflict/failed；409 保留输入，受控重读/rebase 一次仍冲突则明确重试，不盲目覆盖；504 与空工作区分开。历史 409 没有证明已发生用户数据丢失。
- Tools 执行成功与后续刷新失败分开；批删冻结目标；超时保留原 requestId。
- 精准查询后端保留审计 `GET /api/system/stream/actions?request_id=...`，返回 found/status/terminal/recovery；不是扫描前端最近 100 条猜终态。
- 未知副作用禁止自动重试。人工接管后绑定原 requestId/action 登记 known_success/failed，不调用 provider；执行中禁止人工覆盖，已确认同结论幂等；关联草稿同步投递状态。重新执行仍需新预览与确认。
- 后端审计最多保留 200 条；被淘汰或缺失的请求保持 unknown，不能据“查不到”宣称未执行。

## 六、全部面板的功能改进矩阵

导航 14 条对应 13 个实际目标，deploy 跳 Infrastructure；SVC 旧路由和设置嵌入都纳入；未暴露的 OverviewPanel 不计为已巡检独立页面。

| 面板/区域 | 覆盖的实际功能 | 改进要求与当前处置 |
|---|---|---|
| 公共壳/工作区抽屉 | 路由、工作区、主题、语言、通知、快捷键、缓存和保存 | 工作区隔离、保存终态与重试、恢复缓存页刷新；窄屏状态提示不覆盖发送；已有编辑不丢 |
| 聊天舞台 | Live2D/VRM、fallback、缩放、拖拽布局、沉浸语音、字幕、录音、播放、口型 | F04/F05/F15；文字/语音共同显示离线，字幕按 generation 清理，迟到资源释放 |
| Chat | 会话增改置顶归档删除分支；消息搜索复制引用编辑重发再生删除；草稿快捷语、附件翻译参数和打断 | 草稿在失败保留；流和持久化结果绑定会话；翻译绑定原消息版本/目标语言；附件按 F13 明示能力 |
| Memory | Library/Review/Operations、检索召回、Inspector、准入遗忘、导入导出、维护和索引 | M-01～05+F02/F07/F08；存储与索引分开，批处理逐项反馈，预检错误可见，草稿和任务终态准确 |
| Prompt | 工作区 system prompt、companion persona、编辑保存刷新和运行时应用 | 草稿按 workspace/companion 隔离，dirty 刷新保留；保存和 runtime apply 分开反馈 |
| Pet | 模型选导删、关系历史、尺寸透明度、免打扰/穿透/锁定、常驻位置显示器停靠、动作表情参数/idle/口型/显隐重载 | capability 逐项门控；宿主路径说明；显示器失败不阻断模型；删除当前模型后 catalog/state 同步，关系历史按角色隔离 |
| SVC | 检查、文件选择、转换、播放、设置跳转 | 点击冻结文件/配置/requestId，flush 成功且读回匹配再转换；A 结果不标成 B；可达与就绪分开。没有跨客户端配置事务锁 |
| Tools | Status/Stream/Capabilities/Skills/History；导入筛选批删、Twitch/OBS、订阅接管事件草稿/动作 | 独立列表错误与时间；冻结批处理；动作和刷新分开；原请求精准终态、未知副作用人工确认契约 |
| Plugins | 搜索分类问题过滤、manifest/权限/routes/tools/pet events、加载错误、执行取消和审计 | F02；接受取消与完成分开；空/失败分开；说明与治理 agent plugin 的职责；不凭空增加安装卸载开关 |
| Infrastructure | 环境/runtime/cache、系统/DB/统计/模型/preset、JSON/CSV、备份预览恢复、日志与 Deploy | F01/F06；当前工作区 preset；部分失败保留成功数据；导出/日志说明范围与时间；恢复绑定计划 |
| Deploy | health/readiness/provider、后端启停、API 文档、命令复制 | 分层健康；浏览器 HTTP 启动可用，停止按能力；control ok 不等于聊天 ready |
| Agent Governance | Connectors/MCP/Permissions/Extensions；多连接器配置探测、恢复取消投递重试、账号绑定、QQ 桥安装启停扫码、MCP/预设、权限清理和 agent plugin | 保存与探测分开；清 secret 防旧回写；event/delivery 关联、完成不重复投递；扫码轮询有界且离页暂停 |
| Agent Trace | Status/Jobs/Schedules/Traces；指标轨迹、恢复/重试/未知确认/recheck/取消、定时任务增改启停立即执行删除导出 | F03/F11；job/run/request 身份一致；取消 ACK+终态；精准取消旧任务不影响新 turn；失败保留输入 |
| Persona Memory | heartbeat、亲密度、行为事件/抑制原因、建议、表情动作和聊天建议 | 显示时间及角色/模型身份；历史不称当前；按模型能力禁用动作；本地建议不冒充事实长期记忆 |
| I18n | 前端/后端语言切换、字典预览、普通/错误消息查询 | F12/V03；各阶段结果分开；语言和 lookup 防乱序；后端失败时说明前端已切换与否 |
| Onboarding | snapshot、启动/取消、fresh scan、LLM、安全修复、可选语音设备检查、跳过和重开 | 新鲜度、来源、原错误；passed/skipped 分离；身份校验保留；浏览器设备结果真正写入 |

## 七、设置十个子页

保留现有去抖、串行保存和失败 patch 重试，统一“编辑/已保存/运行时已应用/资源就绪”，后端规范化回填不覆盖后续输入。

| 子页 | 实际功能与完整改进要求 |
|---|---|
| 访问 | token 保存/重置：显示保存/需重启/失败，重读一致，描述 loopback 信任边界，补全英文提示 |
| LLM | provider/profile、URL/key/model、发现、参数、推荐、测试、vision：格式/保存/可达/模型可用分开，测试前 flush 失败则停止，规范化回填 |
| TTS | provider/profile/key、角色、发现、status/warmup/test/reset：保存、应用、资源、播放终态分开；切 provider 不带旧角色，失败可重试 |
| ASR | provider/模型/路径/凭据、参数和发现：不兼容隐藏字段明确清理或保留；标明宿主路径；资源缺失/读取失败分开，清凭据防回写 |
| SVC | provider/endpoint/speaker/pitch/timeout/发现/测试/重置/嵌入转换：B-01 准确 ready；转换使用保存并读回的一致快照，结果绑定原文件/request |
| 记忆 | backend/embedding/发现/重建：等待实际 backend 应用再重建，显示权威/索引状态及错误，重建/失败/取消都有终态 |
| 摘要 | 策略编辑：说明全局作用域、对既有与新摘要的影响，保存重读；工作区切换不伪装独立配置 |
| 资源 | 下载/取消、SoulX/Sherpa/online/embedding/TTS、删除/分类/清理：未安装与读取失败分开，逐项结果，部分失败可重试，轮询有界 |
| 系统 | 主题语言、快捷键/fallback、consent、metadata/history/清理/回滚、单键：F09/F10，冲突说明、输入框保护、回滚后刷新数据及历史 |
| 运行引导 | 重开：显示上次扫描时间及跳过/通过；取得新 snapshot，旧 completion 不掩盖当前错误 |

这些子页已有相应保存、反馈、就绪和错误处理调整；浏览器逐页进入验证，不表示每个外部资源下载或每项硬件动作都执行过。

## 八、验收证据、未关闭项与交付

证据目录：`improvement-evidence-2026-11-10/`。浏览器脚本使用独立临时浏览器 profile；HTTP 写操作被拦截，记忆交互使用合成响应；因此期望的拦截 409 不计作产品故障，也不把合成响应算作真实数据库修复。

| 检查 | 已取得结果 | 含义 |
|---|---|---|
| Electron 全套单元测试 | 53 files / 353 passed | `electron-unit.log`；收尾 UI 文案后另跑 i18n 2 files/10 passed；不累计重复计数 |
| 最终 renderer/main build | 通过，含 bundle audit | `electron-build.log`；已经生成最新 dist，不等于现存 Electron main 已重载 |
| 完整 lint | 通过 | `electron-lint.log`；最后两文件文案改动另作定向检查 |
| 类型检查 | main 通过，renderer 无新增错误 | `electron-types.log`；尚有 2 项既有 three/GLTFLoader 声明缺失，未扩大 baseline；修复了 player 和 parser 推断问题 |
| 记忆修复验收 | 六文件曾 89 passed；最终 memory_audit_regressions+memory_operations 为 34 passed | 后者覆盖日志脱敏/墓碑重放等最终补充；两次范围重叠，不相加 |
| 取消身份 | 2 passed | `python/tests/test_interrupt_targeting.py`；匹配、旧/错 request、其他会话及通用中断 |
| 后端临时探针 | 34 passed | SVC、TTS、ASR、插件、SSE 和路由契约；由执行子任务返回结果，非全部真实供应商端到端 |
| 宿主/引导/SVC/restore 定向 | 6 files / 45 passed | 临时真实 HTTP 入口和临时备份；完整细节见 `electron/src/main/onboarding/verification.md` |
| 工作区 | 2 files / 4 passed | 串行保存、409 rebase、保留失败状态；浏览器验证可见提示 |
| Tools 收尾 | 5 个现有相关用例及隔离探针通过 | 超 100 条精确查询、重启、缺失 unknown、执行中保护、人工幂等、provider 仅调用一次；不是真实 Twitch/OBS 操作 |
| 浏览器导航/页签 | 14 导航、26 个主要页签、无 pageerror | `browser-acceptance.json` 的 16 页签加 `browser-settings-memory.json` 的 10 设置页；deploy 重定向计导航不计新面板 |
| 浏览器故障交互 | JSON 未发送、索引错误/孤立诊断可见、dirty 保留、预检失败且未删除 | `browser-settings-memory.json`；合成场景 |
| 最终 390px | 发送按钮 x=302..346，y=770..814，无遮挡且可聚焦 | `browser-chat-final.json` 与 `chat-390.png`；记录最终 main asset，768px 也通过 |
| diff 检查 | 通过 | 保留原有工作区修改 |

不能宣称关闭的事项：

1. **历史超过 8 秒健康超时根因**：已修预算/同步阻塞/取消收尾机制并增加观测，尚缺原始现场函数栈和新进程负载复测。
2. **现存后端重载**：控制进程 PID 8208 与 Python PID 21792 是先前运行实例；可执行文件路径本身不能证明使用全局环境；后续查明其命令和父进程均指向项目 `.venv`，符合 Windows venv redirector 行为。没有终止、重启它们；新后端通过隔离/进程内验收，不能用旧实例响应证明已上线。
3. **隔离服务启动限制**：启动隔离后台服务的操作被自动审批策略以 `blocked by policy` 拒绝；未改用其他方式绕过，改用进程内与临时入口验证。
4. **真实外部能力**：真实 LLM/SoulX/TTS/ASR、麦克风扬声器、Qdrant、QQ 扫码、连接器投递、OBS/Twitch 和完整 Electron 生命周期未做真实副作用联调。
5. **类型声明与 Go（续作已关闭）**：第一轮遗留的声明问题已通过匹配的开发类型包修复，类型错误及基线均为 0；Go 自动选择 1.27.0，启动器测试通过，详见续作记录。
6. **恢复与删除的产品边界**：备份恢复尚非事务；执行中 OS 错误可部分恢复。永久删除不承诺物理介质安全擦除，也不暗中清历史/摘要/备份。索引失败可恢复不代表供应商永不失败。

后续现场验收依次处理：核对当前 PID/启动身份和监督器 → 在允许的新进程中加载当前构建与项目解释器 → 带逐项耗时/loop lag 复测健康 → 执行已配置的真实对话/语音闭环 → 对需要外部副作用的能力逐项确认结果 → 记录历史数据修复的实际数量/跳过项。记录结果前保持对应条目为待现场验证。

本轮交付包含：原始审计与复现、完整改进矩阵、实际代码变更、最小行为回归、当前前端构建及浏览器证据。未把计划、源码实现、本地通过和真实环境通过合并成同一个完成状态。
