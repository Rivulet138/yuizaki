# WP1 / WP2 / WP3 改进与检查报告

检查日期：2026-10-31。范围为计划中的 WP1、WP2、WP3，以及直接相连的设置历史、凭据、策略确认、作业重试、QQ 恢复与前端状态展示。实施与回归验证已完成；外部服务的真实部署联调尚未执行。

## 最终行为

| 工作包 | 已落实的行为 |
| --- | --- |
| WP1 | 本地配置为 `provider=custom`、`base_url=https://api.openlux.ai/v1`、`model=deepseek-v4.1-flash`；应用密钥由 `YUIZAKI_PROVIDER_CREDENTIALS_JSON` 注入。切换供应商或地址时隔离旧密钥，普通空值/掩码更新保留当前密钥，显式删除清空密钥。 |
| WP2 | Windows 使用 Node 加 DSH 的 `lib/bin.js --profile headless`，argv 分离，拒绝选项形态任务；沿用 MCP 环境白名单，不透传 `YUIZAKI_*`；单并发、排队与执行超时、进程树清理、首尾限长及流式脱敏；通过现有作业事件展示进度。 |
| WP3 | 过滤非消息和自身事件；群聊要求真实 at-self 段；用户/群白名单；会话限流与并发准入，超限返回 2xx `rate_limited`；图片/语音等媒体保留占位符；恢复和重试重新检查当前准入条件。 |

完整运行契约与配置示例见 [DSH 集成说明](DSH_INTEGRATION_HARDENING.md)，通用配置入口见 [配置文档](CONFIGURATION.md)。DSH 自身的 headless profile 凭据独立配置，应用密钥不会自动传给 DSH。

## 扫描中发现并修复的问题

以下优先级用于安排修复，不代表已完成外部漏洞评级。

| 优先级 | 问题及影响 | 修复与回归依据 |
| --- | --- | --- |
| P1 | 单项设置、显式删除、主/视觉连接切换及历史回滚可能保留不属于目标连接的密钥。 | 所有相关设置路径使用一致的连接隔离语义；回滚只在规范化后的供应商和地址均一致时保留当前密钥；删除覆盖运行时残留。`test_wp1_provider_credentials.py` 覆盖设置、删除、回滚与环境注入。 |
| P1 | DSH 根进程结束后，后代仍可能存活并持有输出管道；普通直接 kill 不能证明进程树已结束。 | Windows 挂起启动、分配 Job Object 后恢复，清理时终止 Job 并有界等待后代；POSIX 使用独立进程组。包含真实 Python 子进程树和 Windows 挂起启动回归。 |
| P1 | Authorization 的 Bearer 前缀、引号或密钥被拆到多个输出块时可能漏脱敏。 | 增加跨块状态处理，在输出进入限长缓存前脱敏；覆盖不同切分位置、日志与截断结果。 |
| P1 | 子进程读取失败后，其他 reader/waiter 可能仍挂起，影响并发槽释放。 | 失败清理收集原始任务，有界等待后取消并等待剩余任务结束；桥接测试覆盖异常和取消路径。 |
| P1 | 历史“记住允许”可能使 high/critical 工具跳过新的用户确认。 | high/critical 忽略历史允许，保留历史拒绝；确认结果持久化成功后才唤醒执行。覆盖 builtin/plugin/mcp 入口。 |
| P1 | DSH 已可能修改文件时，失败/超时或取消作业被当作普通可重试失败。 | 将可能存在副作用的终态标为 `unknown_effect`，禁止自动重放，保留状态供检查。 |
| P1 | OneBot HTTP 成功、异步受理或不合法结果包被误判为消息已经送达。 | OneBot 11 仅 `status=ok, retcode=0` 确认成功；异步受理和不确定传输保留未知结果。 |
| P1 | 取消发送等待、远端已发送但本地状态提交失败，可能把已发送消息重新标为可重试并重复发送。 | 首次发送和手动重试均记录 POST 已开始的边界，取消或本地提交异常后保留 sending/未知状态，后续重试返回冲突。 |
| P1 | 模型输出中的 CQ 代码可能触发群全体 at 或媒体等动作。 | OneBot 11 文本发送使用 `auto_escape=true`，覆盖私聊和群聊。 |
| P2 | 确认阶段断线/取消可能遗留作业；前端可能提供服务端无法安全执行的重试。 | 确认失败、信号取消和直接 task 取消均写入终态并清理待确认项；仅参数完整且服务端明确可重试时显示重试。脱敏收据不重放。 |
| P2 | 恢复或重试可能沿用过期的连接器启用、白名单及并发状态。 | 重新执行当前准入检查，避免旧作业绕过新设置。 |

上述变更复用现有策略、作业日志、凭据与连接器机制，未增加第三方依赖。`CompanionJobEventLog` 为有界内存事件记录，不是持久审计数据库。

## 参考项目和论文如何落到实现

| 一手资料 | 本次采用的结论 |
| --- | --- |
| [OneBot 11 HTTP 协议](https://github.com/botuniverse/onebot-11/blob/master/communication/http.md) 与 [公开 API](https://github.com/botuniverse/onebot-11/blob/master/api/public.md) | 区分 HTTP 成功、动作完成和异步受理；使用文本转义阻止 CQ 动作注入。 |
| [NoneBot OneBot 适配器](https://github.com/nonebot/adapter-onebot) | 对照真实适配器的动作响应包解析方式；本项目对未知送达采用明确的本地状态约束。 |
| [VS Code 进程管理](https://github.com/microsoft/vscode/blob/main/src/vs/base/node/processes.ts)、[Microsoft Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects) | 对照进程树清理；结合 Windows Job Object 实现启动前归属和完整树清理。 |
| [Python asyncio subprocess](https://docs.python.org/3/library/asyncio-subprocess.html) 与 [tasks](https://docs.python.org/3/library/asyncio-task.html) | 明确管道、取消和后台同步 HTTP 的生命周期，避免误认为取消等待等于撤回请求。 |
| [AWS 幂等重试资料](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/) | 无远端幂等保证时，不把丢失响应当作安全重试依据。 |
| [InjecAgent，arXiv:2403.02691](https://arxiv.org/abs/2403.02691) 与 [AgentDojo，arXiv:2406.13352](https://arxiv.org/abs/2406.13352) | 外部文本及工具结果继续按不可信输入处理；真实写操作保留明确确认边界。未声称复现论文基准或达到其安全结论。 |

## 验证结果

下列检查均在本次工作中执行。代码变动完成后重新运行了完整 Python 回归和最终静态差异检查；未变动的前端、Launcher、MCP 检查复用本次已通过结果。

| 检查 | 结果 |
| --- | --- |
| Python：`cd python; .venv/Scripts/python.exe -m pytest -q` | **859 passed、2 skipped、2 warnings**。两个跳过项为仅适用于 POSIX 的进程组测试；当前为 Windows，Windows 真实进程测试已运行。 |
| Python 编译检查 | `app.py`、`socket_server.py`、modules、routes、socket_handlers、tests 全部通过。 |
| Python Ruff：本次全部修改/新增的 20 个 Python 文件 | **0 条诊断**。 |
| Python basedpyright 与 HEAD 对比 | 当前 **13 errors、24 warnings**；HEAD 为 **14 errors、24 warnings**；新增诊断 **0**。完整类型检查仍非零退出，不标记为全通过。 |
| Electron 单元测试 | **27 个文件、215 项通过**。 |
| Electron 类型门禁与 lint | 通过；渲染器仍有 **169 个已登记类型错误、涉及 35 个文件**，新增错误为 0。 |
| Electron 构建、renderer bundle 审计及 `start:check` | 通过，运行预检就绪。 |
| Go Launcher：`go test ./...` | 通过。 |
| Yuizaki MCP：`npm test` | **7 项通过**。 |
| 文档、资源、Python 依赖锁检查 | 通过。 |
| memory / stream / connector / voice 检查脚本 | 通过；stream 6/6、connector 4/4、voice 3/3。 |
| `git diff --check` | 通过。 |

## 仍存在的问题与验证边界

1. **Python 既有类型债务仍在。** `database/repository.py` 涉及可能未绑定变量、SQLAlchemy 返回类型和 Optional；`migration_bootstrap.py` 涉及反射结构类型；`modules/system/qq_bridge.py` 涉及可空进程与工厂类型；`socket_server.py` 涉及 repository Protocol 和多余判空。以上属于静态诊断，不能仅据此宣称每一项都是已触发的运行故障。
2. **全仓 Ruff 保留 6 条既有测试诊断。** 与 HEAD 相同，涉及导入位置、lambda 赋值和无插值 f-string；此次修改文件无诊断。
3. **前端类型检查采取基线门禁。** 门禁通过表示没有新增错误，169 个既有错误尚未清零。
4. **FastAPI 有 2 条弃用警告。** 来自 `services/soulx-svc/server.py` 的 `on_event` 及 FastAPI 对应路径，未影响本次回归。
5. **真实外部链路尚未验证。** 未使用真实 OpenLux 凭据发起模型请求，未运行已认证 DSH headless profile 的真实写文件任务，未向真实 OneBot 桥发送消息。仓库自动化验证不能替代部署环境验收。
6. **未执行 WP4 / WP5 / WP6。** 本次完成用户明确指定的 WP1 / WP2 / WP3 及其关联修复，未扩大为新协议、技能导入或其他工作包。

修改清单以当前工作区为准：核心变动位于 `python/modules/agent/`、`python/modules/agent_plugins/dsh_delegate_plugin.py`、`python/modules/llm/client.py`、`python/modules/system/`、`python/routes/connector_api.py`、`python/socket_handlers/tool.py`、`python/socket_server.py` 和 Electron 作业展示/权限对话。回归测试位于 `python/tests/` 与 Electron 相邻测试；README、SECURITY、ARCHITECTURE、CONFIGURATION 同步更新。
