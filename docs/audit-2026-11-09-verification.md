# 定向核验与检查结果

本批次只新增审计文档、静态清单和复现脚本，未修改业务源码。源码已有 10 项未提交改动，见 `audit-evidence-2026-11-09/environment.json` 的路径、SHA256 与 Git 基线。以下为实际执行结果；通过项不代表未覆盖行为也正确。

## 检查结果

| 检查 | 结果 | 证据或边界 |
|---|---|---|
| `electron: npm run test:unit` | 39 files，277 passed / 3 failed，共 280 tests | 两个失败文件：i18n coverage、lookup；具体断言见下文。 |
| `electron: npm run type-check` | 失败 | renderer 报 4 项已知基线错误，另新增 player.ts 类型错误；未更新基线掩盖问题。 |
| `electron: npm run lint` | 失败，1 error / 0 warning | SettingsPanel.vue:2953，无用初值。 |
| `node-mcp: npm test` | 11 passed | health、tools、SSE、URL/输入约束、stdio；没有执行真实浏览器工具。 |
| `tools/yuizaki-mcp: node --test` | 7 passed | 独立验证代理执行；fake backend，不等于完整真实 Agent 端到端通过。 |
| control-server、system-routes 定向 Vitest | 2 files / 13 passed | 独立验证代理执行；helper 测试不替代真实请求入口测试。 |
| Python 12 个契约/工作区/设置/Socket/迁移测试文件 | 101 passed | 全局 Python 16.70s；项目 `.venv` 重跑 13.69s；均通过。保留 XML 与日志。 |
| 项目 venv 记忆/召回/写入/检索评估/提示词五文件 | **78 passed，5.54s** | pytest-memory-venv.xml/log；未排除用例。早期69/4为全局环境历史结果，不计入项目环境总数。 |
| 后端缺陷探针 | 6动态场景覆盖4类问题 + 1静态检查，均复现 | backend-probes.log；源码函数提取，不是产品验收通过。 |
| 记忆缺陷探针 | 5项均在项目venv复现 | memory-five-probes.log；全部合成数据。 |
| Go launcher `GOTOOLCHAIN=local GOPROXY=off go test ./...` | 测试启动前受阻 | 本机 Go 1.26.2，go.mod 要求 ≥1.27；未下载工具链。不可记为实现测试失败或通过。 |

Python 主线的 12 个文件为：test_route_manifest、test_ui_capabilities、test_workspace_context_api/migration/repository/store、test_settings_api_probe、test_socket_protocol、test_socket_turn_service_gate、test_settings_history_store、test_settings_store、test_migration_bootstrap。实际 JUnit：`audit-evidence-2026-11-09/pytest-venv.xml`。

## V-01：TTS 完成事件调用缺失方法（P1，运行时合成复现）

- `E:/yuizaki/electron/src/renderer/audio/playbackEventBridge.ts:3` 要求 target 提供 `markTtsStreamComplete(generationId?)`。
- `E:/yuizaki/electron/src/renderer/audio/player.ts:724` 构造 bridge 时只委托 play、stop、enqueue、enqueuePcm，漏接该方法。
- `E:/yuizaki/electron/src/renderer/audio/player.ts:539` 已有该方法实现；`:558` 结束判定依赖最终帧标记。
- `E:/yuizaki/electron/src/renderer/audio/playbackEventBridge.ts:47` 收到 `pet:tts-stream-complete` 无条件调用缺失成员。
- `E:/yuizaki/electron/src/renderer/stores/chatStore.ts:1104`、`:1193` 派发完成事件；`:1243` 监听 audio-ended 清理状态。

直接从当前 player.ts AST 提取真实 adapter，转译真实 bridge，在内存调用已注册完成 handler：

```text
Actual target keys: enqueue, enqueuePcm, play, stop
Observed: TypeError: this.target.markTtsStreamComplete is not a function
```

可复现文件：`audit-evidence-2026-11-09/reproduce-tts-bridge.cjs` 与同名 `.log`。命令：`node docs/audit-evidence-2026-11-09/reproduce-tts-bridge.cjs`。

影响：完成事件确实抛异常；由控制流推断，TTS 最终排空和 busy 清理可能不发生。未使用真实声音设备验证状态卡住，不应扩大为“所有音频都无法播放”。最小修复是补上现有方法的委托；验收应同时覆盖正常完成、零音频完成、排队播放结束、打断与过期 generation，确认最终结束只派发一次。

## V-02：无效初值阻断 lint（P2，确定）

`E:/yuizaki/electron/src/renderer/domains/settings/views/SettingsPanel.vue:2953` 给 activeMigrationPatch 赋 `{}`，在 `s.llm` 分支内 `:2985` 被无条件覆盖后才读取。问题是初值无用，不是变量整体未用。将声明移入实际赋值分支并使用 const 即可；未发现该初始化造成运行时错误的证据。

## V-03：英文缺六个消息键（P2，确定）

英文 3811 键、中文 3817 键。缺失：

- `settings.messages.backendTokenRequired`
- `settings.messages.backendTokenReset`
- `settings.messages.backendTokenResetRestart`
- `settings.messages.backendTokenSaved`
- `settings.messages.backendTokenSavedRestart`
- `settings.messages.historyCleared`

`E:/yuizaki/electron/src/renderer/i18n/index.ts:654` 为中文定义；`jaOverrides.ts:531` 有日文对应。`index.ts:2284` 按当前语言→中文→原键回退，故英文操作提示会混入中文；不会仅因缺键使业务操作崩溃。coverage 的键集检查和占位符检查、lookup 完整性共三项失败，其中占位符异常 `undefined.matchAll` 是缺键的后果。补英文键并验证三语 key/placeholder 一致。

## V-04：实际 loopback 授权边界与测试缺口（边界观察，非已证远程漏洞）

`E:/yuizaki/electron/src/main/control-server.ts:293` 的普通 API 入口检查 Origin 后直接路由；`:304` 注释明确取消 control token 要求。`:134` 接受 loopback HTTP/HTTPS origin 且不限端口，无 Origin 客户端也可进入。`:354` 及 `http/routes/system-routes.ts:93` 的代理使用服务端 backend token。

Python 的 `E:/yuizaki/python/modules/system/backend_api_auth.py` 同样明确豁免 loopback：`backend_api_auth_required` 对本机返回 False，`verify_backend_api_authorization` 对本机返回 True。因此 tools/yuizaki-mcp 默认 loopback 请求不带 token 本身不是功能缺陷；已撤销这个怀疑。

真正需明确的是产品授权模型：当前普通 API 信任本机调用方；不能把 UI 的 token 设置描述成覆盖所有本机 API 的强制访问控制。control-server.test.ts:33 测 helper、:81 测路径分类，但入口没有调用鉴权 helper，测试通过不证明实际 API 要求 token。建议补真实 HTTP 请求矩阵：无 Origin、有允许/不允许 Origin、随机本机端口、错误/过期 token，并明确预期。

专用边界仍独立：mcp-vault-routes.ts:15 要求专用 token；桌面动作与 perception 也有单独宿主能力约束。未做敏感操作或远程攻击，不把普通 API 结论外推到这些入口。

## V-05：路由 manifest 漏掉 include_router（P2，项目 venv 合成复现 + 运行实证）

`E:/yuizaki/python/route_manifest.py:20` 仅枚举 app.routes 中 APIRoute。项目 `.venv` 的 FastAPI 0.143.2 中，合成 include_router 路由在该层为 `_IncludedRouter`：HTTP 200，但 manifest.routes 为空。全局 FastAPI 0.128.0 上同样合成路由可被枚举。不要根据全局测试通过推断项目运行环境兼容。

真实 `/api/system/route-manifest` 仅列 4 项直接注册路由：ping、ui-capabilities、route-manifest、active-application；/api/workspaces 等实际可访问入口未列入。control 的 system-routes.ts:1239 只告警，不因此拒绝所有代理请求，因此不是“所有后端路由失效”。

复现：`python/.venv/Scripts/python.exe docs/audit-evidence-2026-11-09/reproduce_route_manifest.py`；输出与运行接口 JSON 已保留。现有 test_route_manifest 三例全部直接 app 装饰注册，缺少 include_router、嵌套 router、prefix、重复 method 的测试。

改进：使用当前框架支持的完整路由展开结果生成清单，或由注册入口累积规范化路由；不要仅以私有类名硬编码替代。验收同时比较实际可访问路由、OpenAPI 与 manifest 的路径/方法集合，并在项目虚拟环境运行。
