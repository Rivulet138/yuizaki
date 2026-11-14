# 面板切换与保存问题修复验收（2026-11-11）

本轮落实 `review-panel-lifecycle-2026-11-11.md` 确认的 R1～R5。四项功能缺陷已修复，性能验收缺口已使用新构建补齐。沿用现有界面、接口与依赖，不改真实设置或记忆，不重启真实后端，不提交 Git。

## 修复与完成标准

| 项目 | 最终实现 | 验证 |
| --- | --- | --- |
| R1：跨实例规范化回填 | 共享队列分别保留 pending/active/failed 字段的提交标识；本地草稿保存相应确认凭据。只确认实际属于该草稿且提交后未再编辑的字段。同步跟踪后续编辑，包含改走后又改回同值。完成通知同步消费，避免同一 tick 的多次确认被合并遗漏。嵌套 LLM profiles 使用相同规则。 | 另一实例代为排空队列后，原表单显示规范化值；独立同值草稿和后续输入保留；嵌套 profile 的规范化与更晚模型草稿可同时成立。 |
| R2：重试后旧保存错误 | 失败尝试记录原失败字段范围；仅由对应字段的成功保存或成功删除逐项确认，全部字段恢复后才清理该失败。裁剪重试队列不会丢失错误关联，部分重试也不会提前隐藏错误。 | A 失败、B 接续重试成功后 A 清除旧错误；连续失败恢复、同/跨实例凭据删除、DELETE 失败、混合字段部分恢复均有回归；无关完成通知不清除原错误。 |
| R3：已恢复仍显示重试错误 | 按服务和目标修订号保存错误。状态 GET、重试响应、保存 ACK 统一协调，目标已经应用或已被新修订取代时解除对应错误。保留不相关服务与未解决目标的错误；原请求序列仍阻止迟到响应恢复旧状态。 | 同 revision applied、部分恢复、多目标、无关状态、修订取代和迟到响应均有回归。 |
| R4：弹层跨页遮挡 | Memory 停用时关闭高级工具 Drawer 和编辑 Dialog，由现有 Element Plus 关闭流程清理遮罩、焦点捕获和 body lock。使用既有草稿缓存保留输入。返回页面不自动弹出，重新打开可继续。 | 真实 Chromium 中三轮停用均无残留可见遮罩；新页按钮鼠标及 Space 均触发；返回后编辑文本与召回查询均保留。 |
| R5：无关请求验收空通过 | 新增独立场景，经真实 access 前端流程启动 token GET，等待服务端确认收到；切 summary 时断言请求仍 pending、表单已可编辑；释放合成响应后验证浏览器完成事件与 UI。直接 summary 为零请求负对照。保存次数另设 normalized/legacy 独立用例。 | 新构建四个浏览器场景均通过，延迟请求确实开始且完成；保存均为 1 PATCH，规范响应 0 回读，旧接口 1 回读。 |

共享提交元数据只有应用内存中的字段路径、符号标识与恢复关系，不新增本地持久化。凭据继续遵守现有删除和脱敏逻辑。

## 变更文件

- `electron/src/renderer/domains/settings/settingsSaveState.ts`：字段提交标识、失败字段范围、成功确认及嵌套字段选择工具。
- `electron/src/renderer/domains/settings/views/SettingsPanel.vue`：草稿确认与后续编辑协调、跨实例完成同步、精确错误恢复、嵌套 profile 确认。
- `electron/src/renderer/domains/settings/views/SettingsPanel.regression.test.ts`：新增 11 项针对性回归，本文件 60 项。
- `electron/src/renderer/domains/settings/composables/useSettingsDomain.ts`：按服务/修订号协调运行重试错误。
- `electron/src/renderer/domains/settings/composables/useSettingsDomain.test.ts`：新增 30 项运行恢复与竞态回归，本文件 40 项。
- `electron/src/renderer/domains/memory/views/MemoryPanel.vue`：停用时关闭弹层。
- `electron/src/renderer/domains/memory/views/MemoryPanel.regression.test.ts`：新增 3 项停用关闭与草稿回归，本文件 21 项。
- 新增本次证据目录 `docs/fix-evidence-2026-11-11/panel-lifecycle/`；旧证据保持原样。

## 验证结果

使用 Node 24.22.1，在 `electron/` 运行；不增加依赖，不更新类型错误基线。

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| Settings 修改前定向回归 | 4 失败、50 通过，确认原行为不满足新增断言 | `settings-before.log` |
| Settings 与凭据恢复修改后定向回归 | 60/60 通过；凭据增量修改前 4 项失败 | `credential-after.log`、`credential-before.log` |
| Memory 修改前/后定向回归 | 2 失败、19 通过 → 21/21 通过 | `memory-drawer/unit-red.log`、`unit-green.log` |
| 全量 Vitest | **77 文件、756/756 通过**（`--maxWorkers 4`）；早期版本 752 项通过 | `final-bounded-unit.log`、`full-unit.log` |
| 全仓 ESLint | 退出码 0 | `final-full-lint.log` |
| renderer 类型检查 | 0 已知错误、0 新错误，通过 | `final-renderer-types.log` |
| renderer 与 Electron 构建、bundle audit | 全部通过 | `final-build.log` |
| 本轮业务文件 diff whitespace check | 退出码 0；仅 CRLF/LF 提示 | `diff-check.log` |
| Memory 真实浏览器 | Drawer/Dialog/第二轮 Drawer 关闭及交互、草稿均通过，pageerrors=[] | `memory-drawer/browser-after.json` |
| 新构建性能浏览器 | 4 场景全部通过，pageerrors=[] | `save-performance/final-credential-build/results.json` |

本轮共新增 44 项回归；全量测试数包含工作区其他已有及并发改动，不以旧报告的 705 项简单累加推断。以最后一轮 756 项实际执行结果为准。源码 SHA256 见 `source-snapshot.json`。

## 性能证据的准确解释

最终构建的 renderer 指纹及前后完整性核对见 `save-performance/final-credential-build/results.json`；`final-build/` 是补齐凭据分支前的历史构建验收，不作为最终源码证据。

- token GET 实际启动 1 次；启动后 314.89ms 时 summary 表单可编辑且请求仍 pending，受控释放后 21.68ms 呈现 token 状态。浏览器与服务端双重断言均通过。
- 两种保存均为 1 PATCH；规范响应 0 次保存后回读、编辑到已保存 1432.32ms；旧接口 1 次回读、1982.39ms。
- 两种保存均额外观察 1100ms，未出现重复 PATCH。每个独立上下文的初始 settings GET 基线为 2 次，已从保存后回读计数中扣除。
- 上述为各场景单次合成 HTTP 验收，注入 GET/PATCH 各 150ms，并包括浏览器/UI 自动化开销。不能据此证明生产延迟、相较旧样本的性能升降或任何 P95 预算。
- 所有场景 pageerror 为零；隔离环境因缺少部分接口、拒绝后台写入而存在 404/409/socket 控制台信息，不声称控制台完全无错误。
- 该场景以受控响应门验证挂起与恢复，不再沿用旧“未完成就代表已发起”的判断，也不将其描述为固定 3 秒测试。

## 证据与范围

- R4 的浏览器 harness 加载真实当前组件、Vue Router、KeepAlive 和 Element Plus，API/store 为合成数据，另一页面为占位按钮，不是完整 AppShell。
- R5 加载主线最新 dist，合成写入限定到 fixture 的摘要字段；其他写入被阻止。自用 fixture 已由 runner 关闭。
- 未操作真实设置、记忆、供应商、设备或真实后端。真实 Electron IPC、最小化/GPU、真实负载及此前 /health 现场根因仍不在本轮关闭范围内。

## 独立复核与最后增量

独立只读复核在最初 R1～R3 修改后确认了凭据 DELETE 裁掉唯一失败字段但不确认恢复的遗漏。随后新增 4 项回归，先得到 4 失败，再修复为 60/60 通过；独立复核实际重跑这 60 项后，未发现本轮范围内的阻断问题。该检查是有明确范围的补充审查，不是整个工作区无缺陷的保证。

补齐凭据分支后的首轮全量检查与构建、类型检查并发时，既有 HTTP client 的一项认证测试触发 5 秒超时，并影响下一项 fetch 次数断言（754 通过、2 失败）。保留 `final-full-unit.log`，没有修改 HTTP client 代码或测试来绕过。单独复跑该文件 24/24 通过，见 `http-client-recheck.log`；随后使用 `--maxWorkers 4` 重跑全量，77 文件、756/756 通过，见 `final-bounded-unit.log`。
