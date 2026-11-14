# 后端功能链路、调用边界与问题

## 取证范围

覆盖 Python FastAPI/Socket、Electron control/宿主接口、两个独立 Node MCP、SoulX SVC 与 Go launcher 的相关边界。长期记忆内部细节见单独报告；没有把依赖目录、模型缓存或动态外部插件视为本仓库可穷尽的源码。

装配根：`E:/yuizaki/python/app.py:618`，router registry 与 `modules/system/runtime_composition.py:453` 注入 handlers；Socket 挂载 `app.py:846`。部分路由由 handler 是否注入决定注册，静态清单不等于实际运行已注册集合。项目 venv 的 `_IncludedRouter` 使当前 route manifest 漏列，不能用仅 4 条的运行清单反推系统只有 4 个 API。

## 主要公开链路

下表 Python 相对路径基于 `E:/yuizaki/python/`；renderer/main 相对路径基于 `E:/yuizaki/electron/src/`。

| 功能与入口 | 函数/服务链路 | 最终边界 |
|---|---|---|
| 控制 HTTP 代理 | renderer clients → main/http/routes/system-routes.ts:109 proxyPythonJson → :135 Python 请求；control-server.ts 路由先处理专用宿主接口 | Python 固定 origin 白名单代理、独立宿主 API，不是任意 URL 代理 |
| HTTP AI | routes/ai_api.py:311 models；:374 chat/completions → modules/agent/turn_service.py:805 execute_streaming_context/execute_context → agent/pipeline.py:251 run / :262 run_streaming → ExecutionStage → LLMClient | 外部 LLM、Turn commit 与会话持久化；HTTP streaming 问题见 B-05 |
| Socket 对话 | renderer/net/socketClient.ts:291 → socket_handlers/llm.py:70 → :289 TurnService → pipeline → agent/execution_stage.py:164 → tool loop / llm/client.py:1167 stream_chat | Socket 事件、LLM、工具、turn/history；与 HTTP 路径分别验证 |
| 工具/规划 | socketClient.ts:388 → socket_handlers/tool.py:144/:228 → agent/tool_executor.py:432 execute；规划经 StepExecutor；default_tools.py:37 注册 | modules/tools/local_tools.py:140/168/234/267/284 的 OS、URL、搜索、文件读写等；权限、执行和验证是不同阶段 |
| MCP | routes/system_api.py:570 的管理入口 → agent/mcp_manager.py:1217 call_tool → tools/mcp_bridge.py:36 HTTP 或 stdio/SSE/streamable HTTP | node-mcp/server.mjs:246 工具分发 → Playwright/Chromium；Node还暴露health、manifest、tools、events与stdio |
| 独立桌宠 MCP | E:/yuizaki/tools/yuizaki-mcp/server.mjs → loopback HTTP；5工具为status/start/chat/memory_query/connector_status | 这是把 Yuizaki 暴露给外部 MCP 客户端，不等于上述被 Agent 使用的浏览器 MCP |
| ASR | renderer/net/socketClient.ts:326 audio:chunk → socket_handlers/audio.py:60/:205 → modules/asr/transcriber.py:96 → streaming backend 或 :270 _transcribe | 本地/远端ASR；final更新GenerationManager历史并发ASR_FINAL；B-03涉及超时取消 |
| TTS | socket_handlers/llm.py:344 → socket_server.py:2678；Agent流式在 :3397 逐段合成 → modules/tts/synthesizer.py:510 或 openai_compatible.py:133 | 本地/外部TTS → 音频缓存与/audio、Socket → 前端播放器；两端分别存在完成/取消问题 |
| SVC | routes/ai_api.py:617 POST /svc/convert 或 socket_handlers/voice.py:40 → modules/svc/converter.py:92/:140 | 外部转换服务；services/soulx-svc/server.py:281 health、:292 convert → 返回音频缓存 |
| Realtime | routes/realtime_api.py:255 client-secret → :199 mint；:324 transcript → :356 save_message_pair | 外部Realtime、双消息持久化；未做真实语音调用 |
| 调度 | renderer system-client.ts:192 → routes/system_api.py:504 → modules/system/runtime_endpoints.py:1142 → agent/scheduler.py:182 | schedule_store.py:61 JSON；scheduler:256/:521执行、:554进入TurnService |
| Agent插件 | routes/system_api.py:603 → runtime_endpoints.py:1078 toggle / :1091 config → modules/agent_plugins/manager.py:172/:194 | 注册工具、hook、agent_plugins.json；B-04持久化依赖trace批次 |
| 技能 | system_api 管理导入技能 → skill import/store → 只读SKILL.md内容与Agent上下文 | 不应把导入文档视为自动授予工具执行权限 |
| Prompt | socket_handlers/llm.py:140 profile入ctx → agent/context_stage.py:283 → prompt_assembly.py:409/:563 | workspace system prompt、persona、摘要、记忆分别组装；未发现独立Python /api/prompt 管理路由 |
| 工作区/分支 | routes/workspace_api.py:70 list、:83 create、:113 patch、:192/:205 sessions、:217 branches、:243 session patch、:268 effective-preset → database/repository | SQLite、contextRevision乐观并发；409是既有保护契约 |
| 会话/消息/导出 | routes/database_api.py:68 history、:80 sessions、:92/:107会话删除、:122/:137/:155消息删除编辑、:170统计、:193/:210导出 | DatabaseRepository、SQLite；活跃工作区/会话访问检查 |
| Companion/关系 | routes/companion_api.py:52/:83读取、:103创建、:122修改、:139删除、:64关系历史 | repository与关系运行时；长期事实投影另见memory报告 |
| 摘要/治理报告 | routes/summary_api.py:121/:405读取、:433重写、:157审计、:329/:340/:352告警状态、:359/:374报告 | 会话压缩状态、revision校验、治理统计/CSV/JSON；不等于向量记忆 |
| 连接器/账号 | routes/connector_api.py:335/:342配置、:373 probe、:384..:415账号、:526/:527投递/事件、:604 retry、:765 resolve、:823 retry、:829 cancel、:894 webhook | MessageConnectorRegistry、Agent turn/恢复/投递；外部 Telegram/Discord/OneBot/微信桥 |
| QQ托管桥 | connector_api.py:460状态、:467安装、:481签名、:495/:505启停、:515 logout → QQ bridge supervisor | 本地子进程、桥资源与账号扫码；默认可选，未真实启动/登录 |
| 资源/存储/设置 | settings_api与system_api handler；routes/storage_api.py:191创建、:204状态、:207清理 | SettingsManager/DynamicConfigManager、历史快照、下载任务、模型/缓存文件；UI保存、应用runtime、资源可用应分层 |
| 视觉/感知/桌面 | app.py直接active-application、system API与main perception/pet routes → 授权perception bridge、OCR/vision provider、desktop actions | 浏览器capability与宿主能力不同，宿主token独立；未调用真实桌面动作 |
| 健康/能力/诊断 | /api/ping、/health、/api/readiness、/api/system/ui-capabilities、/api/system/route-manifest | 存活/依赖健康/就绪/能力/路由契约是五类信号，详见后文 |
| 启动监管 | E:/yuizaki/tools/yuizaki-launcher/main.go:756 runtime身份复用核对、:986 backend、:989 MCP、:1005 renderer、:1034 smoke | Go监督Python、control和可选node-mcp；测试受Go1.27要求阻断，已静态核对 |

更完整的路由/事件声明位于证据目录 `python-routes.md`；完整函数和文本调用点分别位于两个 call-inventory.json。涉及动态 handler 的关联以本表和源文件为准。

## 隔离复现与缺陷

项目 `.venv`，Python 3.13.2，FastAPI 0.143.2。`backend_probes.py` 从真实源码提取指定函数，仅替换外部依赖，不启动真实模型/数据库/服务。结果为 **6 个动态场景，覆盖 4 类问题，加 1 个静态流控制检查**，不是“6 类动态缺陷”。主线已复跑并保留 backend-probes.log。

### B-01：SVC 探测的可达状态被当作可用（P2）

`modules/system/settings_api.py:772` test_svc_connection GET base_url；`:807` 附近仅HTTP≥500判失败，401/404/405仍返回ok。源码提取探针分别得到：

```text
svc_probe status=401 ok=True
svc_probe status=404 ok=True
svc_probe status=405 ok=True
```

返回message明确说reachable并带HTTP状态，因此不是伪造2xx；问题是检测只证明网络可达，而前端 `domains/tools/views/SVCPanel.vue:191` 将ok映射ready。它不能证明授权、转换路由或模型就绪。

另有本地配置契约冲突：`:783` 使用 `_safe_probe_url`，该函数 `:54` 拒绝私网及127.0.0.1这类loopback字面量，但对解析结果全为loopback的localhost/localhost.localdomain设有例外。现有 test_settings_api_probe 明确断言拒绝127.0.0.1；services/soulx-svc/README.md:16、python/.env.example:83和SettingsSvcSection.vue:59又推荐 `http://127.0.0.1:7861`。因此文档默认本机配置无法通过该连接测试；不能扩大为所有localhost配置均被拒绝。没有在此建议取消全部URL限制。

改进：拆reachable与ready，针对已选择provider测试约定health endpoint/响应结构；对本地受控服务使用明确的本机目标策略。验收覆盖本机SoulX、401/404/405、超时、错误schema以及200但模型未就绪；不让仅可达直接变ready。

### B-02：共享 active_request 导致跨生成取消（P1）

`modules/tts/openai_compatible.py:133` synthesize_stream_segment 将局部request写入同一 `self._active_request`；`:188` 取消时调用 `_cancel_active_request`；该方法 `:267` 取消当前共享字段。

并发A/B合成，B覆盖字段后取消A，实际A与B请求都被取消：`tts cancel_A_also_cancels_B`。这是使用真实函数的异步任务复现；未经过真实TTS供应商或生产并发会话。

改进：取消当前调用持有的局部task，或按generation/session管理请求，不取消其他generation的共享当前任务。验收同时运行A/B，取消A后B仍能完成；反向取消、重启、异常、stop与complete的归属一致。

### B-03：ASR 吞掉取消，使超时变成空结果（P2）

`modules/asr/transcriber.py:270` 的 `_transcribe` 在`:290`捕获CancelledError并return；外层 `socket_handlers/audio.py:212` 用wait_for，超时分支本应cleanup并发ASR_TIMEOUT。

探针阻塞实际等待边界，0.01秒wait_for最终得到None而非TimeoutError。最终识别未发出时外层可能走ASR_EMPTY_RESULT，而非超时清理分支；这是代码推断，未做真实音频超时。

改进：记录取消指标后重新抛出CancelledError；确需吞掉的用户取消与外层超时分开建模，保证清理有明确归属。验收阻塞final识别得到ASR_TIMEOUT与一次cleanup，用户打断无误报、无迟到识别写入新会话。

### B-04：插件配置/启停未立即持久化（P2）

`modules/agent_plugins/manager.py:172` set_enabled、`:194` update_config 只调用_append_trace；`:53` _append_trace仅trace长度为20倍数时 `_save_store`。runtime_endpoints的管理入口未额外持久化。

空trace执行一次toggle，内存enabled=false但 `persistence_calls=0`。准确结论是最近不足一个批次的设置可能尚未写盘，不能说插件永远不保存。

改进：用户配置/启停属于持久状态变更，应可靠保存并将失败返回给调用者；高频运行trace仍可批量刷盘。验收toggle/config后立即重建manager，状态一致；写盘失败不提示已持久化成功，运行trace批次不影响设置。

### B-05：HTTP stream=true 仍等待完整reply后才首yield（P1，静态控制流确证）

`routes/ai_api.py:397` stream_generator；两分支在`:449` await pipeline.run_streaming 或`:451` await TurnService.execute_streaming_context，直到`:458`才首次yield；terminal随后把完整final_reply作为delta发送。

AST检查：`waits=[449,451] earliest_yield=458`。HTTP SSE的外观存在，但这条HTTP路径没有把增量文本边生成边向响应yield。不能将此结论套到有独立事件发送机制的Socket路径。

改进：让执行器通过有界异步队列/迭代器提供delta，响应生成器及时yield；最终commit/outcome仍保持现有持久化契约，客户端断开要传播取消。验收fake LLM延迟产出两块文本，第一块须在最终完成前到达；错误终帧与turn_commit仍正确，取消不会继续工具副作用。

## 健康与浏览器运行异常

- Python `/api/ping`：app.py:559，轻量存活/runtime身份。主线一次8.3ms/200。
- Python `/health`：routes/system_api.py:223 → runtime_composition.py:290 → health_check.py:71 check_all。`:84` gather并发，默认每项5秒，不能解释为六项顺序累计30秒。
- LLM健康 health_providers.py:78 每次preconnect(force=True)，预算2.5秒，实际会访问供应商models；TTS :104 同步status_snapshot；DB :146 走to_thread，memory状态也走线程。
- control `/health` 代理同名Python路径；control `/api/health` 在system-routes.ts:884直接返回ok，不能证明Python或模型可用。
- onboarding coordinator.ts:393 → pythonService.health → main/python.ts:57 的 `/api/ping`，2秒预算；managed校验runtime身份，external校验challenge proof。不是调用 `/health`。

运行实证：Python与control的 `/health` 均超过8秒触发客户端ReadTimeout；随后Python ui-capabilities耗时6887.1ms。该现象与事件循环延迟、同步工作、取消收尾或共享资源争用相容，当前未定位具体阻塞函数，不能直接定责LLM/DB/记忆。

onboarding readyForText=false、backend.service failed（message为timeout2000ms）与LLM/DB/memory ready共存。host probe合并时覆盖同名结果，且message可能来自已有service status，不一定是本轮新异常。应增加各probe时间戳/耗时和loop lag观测，展示具体错误，保留身份验证。

GET /api/workspaces504与自动PATCH409：代理有超时返回504分支；workspace_api.py:143的409是contextRevision保护。没有证明工作区逻辑错误或用户数据丢失。前端应显示冲突/rebase/最终保存状态；不要盲目自动重试覆盖。

## 验证边界

6场景与静态检查只证明目标函数逻辑；没有替代HTTP路由装配、真实provider、音频硬件、跨进程退出或持久文件重启整链测试。现有API/workspace/socket101项和两套MCP测试结果在verification文档单列，不能用其通过否定上述未覆盖场景。
