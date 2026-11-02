# WP1 / WP2 / WP3 改进与检查报告

复查日期：2026-11-02；初次检查日期：2026-10-31。范围为计划中的 WP1、WP2、WP3，以及直接相连的设置历史、凭据、策略确认、作业重试、QQ 恢复与前端状态展示。本轮进一步修复原报告记录的类型、lint 和生命周期问题，并补充回归；外部服务的真实部署联调尚未执行。

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

## 2026-11-02 复查改进

| 范围 | 本轮修复及回归 |
| --- | --- |
| 连接器后台任务 | HTTP waiter 取消后，`asyncio.shield` 内的 worker 仍可能继续执行。原清理逻辑会提前删除活动任务、阶段和事件映射，令取消接口返回 404。现在统一由 worker 完成回调清理，并校验任务身份，避免删除后续任务；新增内存/持久化两种模式的断连、取消及并发槽释放回归。 |
| 数据库写入 | 幂等键在 workspace 校验前规范化，避免异常处理引用未赋值变量而掩盖原始 `IntegrityError`；workspace 更新使用 ORM 返回的受影响行数，保留原子 revision 条件，明确处理零行更新与提交后记录消失。 |
| 迁移、QQ 与对话持久化 | 反射列采用 Mapping 契约，唯一约束识别支持子类；PTY 使用明确 Protocol，停止桥接时持有稳定进程引用；对话双消息写入采用可选 callable Protocol，保留旧仓库逐条写入兼容路径。新增 8 项数据库、迁移、桥接与持久化回归。 |
| SoulX 生命周期 | 使用 FastAPI lifespan 替代弃用的 `on_event`。保留工作目录先于 runtime 初始化、启动失败传播及关闭后 runtime 状态；新增 3 项测试，覆盖不同精度配置、重复启动和初始化失败。 |
| Python lint | 修复测试中的导入位置、lambda 赋值和无插值 f-string，同时修复根目录扫描发现的 6 个检查脚本导入位置问题；未添加忽略规则。 |

这些修复不改变 DSH 的高风险确认、子进程环境隔离、未知副作用禁止重放及 OneBot 文本转义边界；未增加依赖或扩展到 WP4 / WP5 / WP6。

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

下列结果来自 2026-11-02 本轮复查；Python 完整回归在后端修复完成后重新执行。跳过项、静态提示与外部验收边界分别记录，不把基线门禁通过等同于类型错误清零。

| 检查 | 结果 |
| --- | --- |
| Python：`cd python; .venv/Scripts/python.exe -m pytest -q` | **872 passed、2 skipped，无 warnings**。两个跳过项为仅适用于 POSIX 的进程组测试；当前为 Windows，Windows 真实进程测试已运行。 |
| Python 编译检查 | `app.py`、`socket_server.py`、`migration_bootstrap.py`、modules、routes、socket_handlers、tests 全部通过。 |
| 全仓 Ruff：`python/.venv/Scripts/python.exe -m ruff check .` | **0 条诊断**，包含 Python、服务及根目录检查脚本。 |
| Python basedpyright | Python **3.11 / 3.12 / 3.13** 目标各为 **0 errors、24 warnings，退出码 0**，原报告的 13 个错误已清零。24 条提示均为框架注册函数的静态“未使用”提示，未通过关闭检查消除。 |
| Electron 单元测试 | **28 个文件、217 项通过**。 |
| Electron 类型门禁与 lint | 通过；渲染器仍有 **25 个已登记类型错误、涉及 9 个文件**，新增错误为 0。 |
| Electron 构建、renderer bundle 审计及 `start:check` | 通过，运行预检就绪。 |
| Go Launcher：`go test ./...` | 通过。 |
| Yuizaki MCP：`npm test` | **11 项通过**。 |
| 文档、资源、Python 依赖锁检查 | 通过。 |
| memory / stream / connector / voice 检查脚本 | 通过；stream 6/6、connector 4/4、voice 3/3。 |
| `git diff --check` | 通过。 |

## 仍存在的问题与验证边界

1. **Python 保留 24 条非阻断静态提示。** `app_factory.py` 2 条、`modules/system/http_observability.py` 3 条、`routes/connector_api.py` 19 条，均涉及已通过框架注册的嵌套处理函数。13 个类型错误及全仓 Ruff 诊断已修复；未为消除提示重写路由注册或添加忽略配置。
2. **本轮回归新增 13 项 Python 测试。** 数据库/迁移/桥接/持久化 8 项、连接器断连 2 项、SoulX 生命周期 3 项。SoulX 使用模拟 runtime 验证应用生命周期，未加载真实模型权重。
3. **前端类型检查采取基线门禁。** 门禁通过表示没有新增错误，25 个既有错误尚未清零，涉及 9 个文件。
4. **FastAPI 弃用警告已消除。** SoulX 改用 lifespan，生命周期及相关回归在弃用警告作为错误的设置下通过；完整 Python 回归没有 warnings。
5. **真实外部链路尚未验证。** 未使用真实 OpenLux 凭据发起模型请求，未运行已认证 DSH headless profile 的真实写文件任务，未向真实 OneBot 桥发送消息。仓库自动化验证不能替代部署环境验收。
6. **未执行 WP4 / WP5 / WP6。** 本次完成用户明确指定的 WP1 / WP2 / WP3 及其关联修复，未扩大为新协议、技能导入或其他工作包。

原轮次的 WP1 / WP2 / WP3 核心实现保持不变。本轮修改集中于 `python/database/repository.py`、`python/migration_bootstrap.py`、`python/modules/system/qq_bridge.py`、`python/routes/connector_api.py`、`python/socket_server.py`、`services/soulx-svc/server.py`、检查脚本及 Electron 类型契约；回归测试位于 `python/tests/` 与 Electron 相邻测试。配置与安全行为仍以已有 README、SECURITY、ARCHITECTURE、CONFIGURATION 及 DSH 集成说明为准。
