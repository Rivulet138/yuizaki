# 健康、引导、SVC 与本机授权核验（2026-11-10）

## 健康证据与预算

审计原始证据是 `docs/audit-evidence-2026-11-09/runtime-http.json`：Python `/health` 8014.9ms ReadTimeout、control `/health` 8002.2ms ReadTimeout、随后 Python ui-capabilities 6887.1ms。这些记录没有函数栈或逐项耗时，不能归因给某个 provider。主线进程检查确认现存 control PID 8208 和 Python PID 21792 加载的是旧代码；其可执行文件路径为 `C:\Python313\python.exe`，但启动命令和父进程均指向项目 `.venv`，符合 Windows venv redirector 行为；仅凭可执行文件路径无法判断 Python 环境。本 slice 没有重启、终止或用它们验证新修复。

隔离回归运行真实 HEAD 与工作树 HealthChecker / health provider 函数，仅注入耗时边界，不访问模型、网络或用户数据：

```powershell
python/.venv/Scripts/python.exe electron/src/main/onboarding/verify-health-budget.py
```

一次结果：

| 场景 | HEAD | 工作树 |
|---|---:|---:|
| `tts.status_snapshot` 注入 300ms，检查预算 40ms | 300.5ms，错误地 healthy | 53.1ms，unhealthy |
| coroutine 取消后收尾 180ms，检查预算 40ms | 233.6ms | 47.1ms |
| 同步 snapshot 期间事件循环心跳 | 被同步执行占用 | 21.8ms |

这是两种**可复现超预算机制**，不是对旧进程 8 秒超时根因的认定。默认总预算保持 5000ms。扫描并发共享一个任务；不等待 provider 取消收尾，晚到结果不会覆写快照。同步 LLM/TTS status 在 worker 执行，并复用未结束的 snapshot，避免反复扫描积累同类阻塞 worker。响应包含 source、started_at / checked_at、budget_ms、duration_ms、逐项 response_time_ms 和 loop_lag_ms。超过 250ms 的 snapshot 记录具体函数名，例如 `Health slow function tts.status_snapshot duration_ms=...`。任何同进程事件循环的其他同步阻塞仍会延迟定时器，需要在新进程通过这些观测继续定位。

PythonService 仍使用 2000ms `/api/ping`。managed runtime identity / generation / nonce 和 external HMAC challenge 校验保留；本轮失败细节与时间单独记录，避免复用旧启动错误。

## 分层信号与引导

- control `/api/health` 只表示 `yuizaki-control` liveness；不承诺 Python 或模型就绪。
- Python `/api/ping` 是进程存活；Python `/health` 是依赖检查；`/api/readiness` 是聊天就绪。Deploy 分别显示，不能用 control ok 推导全部健康。
- 浏览器与 Electron 都可通过 onboarding 启动；停止仍需 Electron 能力或进程管理方。浏览器启动调用 `/api/onboarding/backend/start`，不再显示不能启动的旧结论。
- 引导可以重新全量扫描；显示本轮起止时间、各 probe 的来源/预算/可用的测量时间。Python onboarding 的 `receivedAt` 只表示 Electron 收到结果，不能当作 provider 的实际测量时间。部分 retry 保留未重测结果原时间。
- `yuizaki.onboarding.completed.v1` 保留旧的关闭流程兼容行为；新的 `yuizaki.onboarding.outcome.v1` 单独存 `passed` 或 `skipped`、runId、时间与 optionalSkipped。关闭/跳过不伪造 probe 通过。
- 浏览器设备报告 `POST /api/onboarding/device-probe` 写回 coordinator；矛盾的 outcome/messageCode 返回 400。麦克风捕获成功、扬声器测试播放完成仍不等于用户已经确认听见声音。

## SVC 契约

转换点击时冻结文件、provider/base_url/speaker_id/pitch/timeout 和 requestId，在保存回调完成后读回已保存配置；保存失败或读回与快照不一致时停止。表单与 `x-trace-id` 使用冻结请求，完成音频显示原文件名及配置。选择 B 不把 A 的响应标作 B。

Python SVC probe 的约定为 `ok = ready`，并返回 `reachable` 与 `ready`；本面板直接请求时要求三者为 true。设置父组件投影后的 `ok` 也应表示 ready；单独 reachable 不通过。本 slice 没有修改 settings_api 或 SettingsPanel。Python convert 仍由服务端取当前 converter；前端快照/读回没有提供跨客户端的服务端配置事务锁。

## V04 本机授权产品契约

普通 control API 信任本机调用方：无 Origin 客户端，以及任意端口的 HTTP/HTTPS loopback Origin（另含打包 renderer Origin）不强制 token；错误或过期 token 不改变这个规则。外站/无效 Origin 被拒绝，即使携带 token。UI 的 backend token 用于需要 token 的后端边界及代理，不是所有本机 API 的强制访问控制。MCP vault、perception、桌面动作的专用检查独立保留。

`control-entry.test.ts` 在独立临时 loopback 端口，通过真实 `ControlServer.handleRequest` 入口发送 HTTP，覆盖无/允许/拒绝 Origin、随机 loopback 端口、错误/过期 token、OPTIONS、vault 无授权拒绝和设备报告。不对现存控制端口执行操作。

## F01 restore API（与主线 UI 签名一致）

```ts
restoreBackup(backupDir: string, dryRun = true, planId?: string)
```

请求体为 `{ backupDir, dryRun, planId }`。dry-run 返回原字段及 `planId`（64 位十六进制 SHA-256），摘要绑定规范化真实 backupDir、manifest 原文、实际恢复源的 stat（目录递归、稳定排序）与 preview 的目标/impact 输出。apply 必须传相同 planId；服务端先纯 dry-run 重算，不匹配或缺失返回 HTTP 409 / `restore_plan_changed`，此时尚未写文件。路径或 managed target 违规继续返回 403。验证后执行，并回传用于核验的同一个 planId；保留 realpath、managed target、目标 symlink/父目录检查。预览也预先校验所有恢复目标。

`backup-plan.test.ts` 仅使用临时目录：稳定摘要、缺失/错误摘要、manifest/源文件/嵌套目录/目标存在状态/backupDir 变化、合法 apply，以及原有路径保护。它没有恢复真实备份。这个 contract 没有新增事务式恢复或文件系统锁；执行期间的 OS 错误仍可能导致部分恢复。

## 验证与外部验收边界

定向 Vitest 覆盖 HTTP 入口、Python identity/HMAC、引导时间/新错误、SVC 保存/文件竞态和 restore plan。main typecheck、修改文件 ESLint 与 renderer baseline gate 另外执行。renderer 的现有 baseline 错误不算本 slice 已修复。

主线仍需重建 dist 后，用独立 Python Playwright 验收新前端；真实音频权限/播放、SoulX 模型 readiness、真实供应商、完整 Electron 生命周期，以及新进程负载下 `/health` 的实际 5 秒预算与慢函数日志均属外部验收。不要拿旧的 38945/8001 进程响应当作本修复结果。

若安排后续恢复：先核对 PID 8208/21792 的当前 executable、command line、启动时间与监听端口，保存证据；只在主线授权重启后按原 supervisor 的生命周期停止对应实例，并以项目 `.venv/Scripts/python.exe` 及同一组受管路径/身份环境启动 Python、再启动重建的 Electron。不得仅凭旧 PID 直接杀进程，也不要为了绕过身份失败移除 HMAC/identity 校验。
