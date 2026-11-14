# 面板二次复核修复与验证（2026-11-13）

针对 [2026-11-11 二次复核](panel-review-followup-2026-11-11.md) 的 13 项问题完成修正，并补齐联调中发现的工作区路由、首次空时间戳和主动设置并发时序。以下结果来自当前工作区的实际执行；工作区还包含此前任务的未提交修改，本文仅记录本次问题范围，不将全部差异归为本次修改。

## 逐项处理

| 原编号 | 修复后的行为 | 主要实现 / 回归文件 |
| --- | --- | --- |
| 1 | 主动设置、记录、重建、删除、反馈和统计接口均显式携带 `workspace_id`；后端校验后按该目标执行，不读取全局活动工作区决定写入对象。缺失或非法身份返回 422，版本冲突仍返回 409。 | `electron/src/renderer/api/clients/proactive-client.ts`、同目录 `proactive-client.test.ts`；`python/routes/system_api.py`；`python/modules/system/runtime_endpoints.py`；`python/tests/test_proactive_workspace_api.py` |
| 2 | 分支创建与激活分离；调用方在创建、路由和历史读取各等待点校验工作区、选择代次和卸载状态，迟到分支不会抢回用户新选择。 | `electron/src/renderer/stores/sessionStore.ts`、`sessionStore.regression.test.ts`；`electron/src/renderer/domains/chat/views/ChatPanel.vue`、`ChatPanel.async.test.ts` |
| 3 | 反馈成功、错误及统计提交绑定开始时的工作区和上下文代次，A 的迟到反馈不能修改 B 的策略。 | `electron/src/renderer/app/composables/useProactiveControls.ts`、`useProactiveControls.test.ts` |
| 4 | 删除操作的成功及失败都校验上下文，旧工作区删除失败不再关闭新工作区策略或注入旧错误。 | 同上 |
| 5 | 读取快照代次与写入确认分离；保存中后台读取不提交旧快照、不取消写确认、不解除保存锁。 | 同上；`electron/src/renderer/app/composables/useCompanionRuntimeBridge.ts` |
| 6 | 删除拒绝或异常会撤销本次隐藏，记录可以重新显示、刷新和重试。 | `electron/src/renderer/app/composables/useProactiveControls.ts`、`useProactiveControls.test.ts` |
| 7 | 设置和记录返回后即可提交主数据；反馈统计独立异步加载，迟到统计也检查工作区归属。 | 同上 |
| 8 | TTS 写操作成功确认独立保留；新写入接管运行状态时，旧 GET 的数据、错误和加载状态一起失效，旧回包不能污染新状态。 | `electron/src/renderer/domains/settings/composables/useSettingsDomain.ts`、`useSettingsDomain.test.ts`；`electron/src/renderer/shared/composables/useDomainRequest.ts`、`useDomainRequest.test.ts` |
| 9 | 四类连接器探测按 connector ID 隔离，同连接器仍执行新请求覆盖旧请求规则；聚合等待及错误保留。 | `electron/src/renderer/domains/system/composables/useSystemDomain.ts`、`useSystemDomain.test.ts`、`useConnectorRequest.ts` |
| 10 | 桌宠目录、显示器和能力读取与可变状态写入分别控制，调整缩放不会丢弃独立加载结果；写入结束或失败后继续尚未完成的就绪同步。 | `electron/src/renderer/domains/pet/views/PetControlPanel.vue`、`PetControlPanel.readiness.test.ts` |
| 11 | 引导 `backend.retry` 使用与专用启动一致的 180000ms 期限；供应商及形象探测使用 35000ms。 | `electron/src/renderer/domains/onboarding/views/OnboardingGate.vue`、`OnboardingGate.requests.test.ts` |
| 12 | Infrastructure 失活后停止读取并使在途快照失效，激活时按当前工作区重新读取；覆盖中断后重入和回到同一工作区。 | `electron/src/renderer/domains/system/views/InfrastructurePanel.vue`、`InfrastructurePanel.test.ts` |
| 13 | Overview 用共同提交代次防止旧写响应覆盖新状态，并保留写入成功确认；过期确认不会启动旧读回。 | `electron/src/renderer/domains/system/composables/useSystemOverview.ts`、`useSystemOverview.test.ts` |

## 联调补齐

- `useProactiveControls` 按工作区保留尚未结束的写锁。A 保存期间切到 B 再回 A，策略保持关闭；原写结束后重新读取 A 的服务端结果。
- `never_source` 会改变设置版本，因此与设置保存互斥；成功后读回版本，随后才允许下一次设置修改。
- `never_source` 开始时使更早发出的读取失效，防止旧快照在反馈 pending 期间提前解除策略关闭状态。新增回归先复现该问题，再修正 `loadSequence` 和 `loading`。
- `electron/src/shared/proactive.ts` 保留合法的 `updatedAt: null`，新工作区首次读取不再被误判为字段缺失。
- `electron/src/renderer/app/orchestrators/useAppOrchestrator.ts` 在后端工作区发现完成后按最新 URL 选择目标，同步 SPA 和前进后退，非法目标回退；切换代次防止旧激活、会话或模型请求在新导航及卸载后继续操作。对应 12 项回归通过。
- 补齐设置页刷新图标导入，消除相关渲染分支的引用遗漏。

## 最终验证

本次检查日期：2026-11-13。命令均退出 0。

| 检查 | 结果 | 日志 / 证据 |
| --- | --- | --- |
| 前端 `npm run test:unit` | 79 个文件、844 项测试全部通过 | `artifacts/panel-fix-unit-2026-11-13.log` |
| `npm run type-check` | 主进程检查通过；renderer 0 已知错误、0 新错误 | `artifacts/panel-fix-type-check-2026-11-13.log` |
| `npm run lint` | ESLint 通过 | `artifacts/panel-fix-lint-2026-11-13.log` |
| `npm run build` | Vite、renderer 包体审计、Electron TypeScript 编译通过 | `artifacts/panel-fix-build-2026-11-13.log` |
| 后端定向 pytest | 80 项全部通过 | `artifacts/panel-fix-python-2026-11-13.log` |
| 真实后端 + Chromium | 19 个断言场景通过，页面 JavaScript 异常 0 | [browser-verification.json](panel-fix-evidence-2026-11-11/browser-verification.json) |

后端定向命令，在 `python` 目录执行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_proactive_workspace_api.py tests/test_proactive_feedback_summary.py tests/test_scheduler_outcome_contract.py -q
```

浏览器重跑命令，在仓库根目录执行：

```powershell
python docs/panel-fix-evidence-2026-11-11/browser_verification.py
```

浏览器使用独立 Python 后端、Vite 和临时 SQLite/设置目录，不读写用户运行数据。它验证：

1. 新工作区 `updatedAt: null` 可以正常加载；统计请求暂缓时主控件仍可用。
2. 浏览器发出携带 A 身份的 PATCH 后暂缓请求，切换后端全局活动工作区到 B，再放行；实际读回 A 为 `dnd=true/revision=1`，B 保持 `dnd=false/revision=0`。
3. 完整刷新后保存仍存在；SPA A→B→A 后各工作区设置正确。
4. 14 个面板入口连续 SPA 导航可渲染，其中历史 `deploy` 入口重定向到 `infrastructure`。
5. 未携带工作区身份的 PATCH 返回 422；浏览器观测到的主动控制接口响应均为 200。

保存读回截图：[proactive-save-readback.png](panel-fix-evidence-2026-11-11/proactive-save-readback.png)。

## 验证边界

- 本次浏览器没有启动 Electron 宿主、真实供应商、语音设备或模型渲染链路；面板入口可渲染不等于这些外部功能已端到端验收。
- Infrastructure 回归实际执行 Vue `KeepAlive` 生命周期，覆盖失活、重入和旧响应；未做浏览器多缓存实例的完整端到端验收。
- Overview 修复保证前端提交顺序，不单独证明后端写入执行顺序；该历史组件仍未注册为当前导航入口。
- 后端运行的是本次相关 80 项定向测试，并非整个 Python 测试集。
