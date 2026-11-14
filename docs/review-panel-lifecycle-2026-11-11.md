# 面板切换与保存补充复核（2026-11-11）

> 修复跟进（2026-11-11）：本报告的 R1～R5 已完成本地修复及隔离验收，详见 [修复验收报告](fix-panel-lifecycle-2026-11-11.md)。下文保留发现时的原始问题与证据。

本次为只读复核，范围是上一轮面板切换、共享保存、运行状态恢复、Memory 缓存和聊天舞台生命周期改进。确认 **4 处功能缺陷和 1 处验收证据缺口**；不能将上一轮测试通过理解为这些边界已经关闭。本次未修改业务源码和持久测试，未操作真实设置、记忆及供应商服务。

六份核心实现文件的 SHA256 均与上一轮验收源码快照一致，记录见 `review-evidence-2026-11-11/panel-lifecycle/review-source-snapshot.json`。检查时发现其他工作对 SystemOverview 有并发改动，因此本报告不把旧版全量 705 项通过结果当成当前整个工作区的验证结果。

## 确认的问题

| 编号 | 优先级 | 场景与实际结果 | 影响与改进 |
| --- | --- | --- | --- |
| R1 | P2 | 实例 A 正在保存，实例 B 排队提交摘要阈值 999；A 排空共享队列，服务端把 B 的值规范化为 100。B 的 settings 已是 100、待保存队列为空，但表单仍是 999。 | 界面与已保存值不一致，后续编辑可能再次携带错误值。共享队列需保留字段来源及编辑版本，完成通知按实际提交与后续编辑判断哪些字段可规范化。保留真正晚于提交的输入。 |
| R2 | P2 | A 保存失败，B 继承失败 patch 并成功重试；共享失败状态已清除，但 A 的 updateRequest.error 仍存在，保存状态继续显示“保存失败”。 | 成功恢复后仍错误提示失败。错误应与提交身份绑定，收到同一失败提交的成功重试确认时清除对应错误；不能靠任意其他保存成功清空全部错误。 |
| R3 | P2 | svc r7 重试请求失败，随后状态 GET 已确认 r7 applied；runtimeRetryRequest.error 仍保留，运行反馈面板继续展示旧错误。 | 用户不能判断恢复是否完成，可能重复重试。按目标服务及修订号保存重试错误；匹配目标已应用或已被新修订取代时，协调清理相应错误，保留不相关目标的失败。 |
| R4 | P2 | Memory 高级工具 Drawer 打开时，路由切换导致组件进入 KeepAlive 停用状态；页面主体已移走，但 append-to-body 的 Drawer、遮罩和 body 滚动锁仍存在。新页面按钮被遮罩拦截。 | 面板切换后出现无法点击的界面。停用时关闭 Drawer，或以激活状态约束弹层渲染，同时保留其中的表单草稿；验证关闭过渡、滚动锁清理及返回页面后的状态。 |
| R5 | 验证缺口 | 旧保存性能脚本为 backend-token GET 配置了 3 秒延迟，但实际进入 summary 子页，两种接口情景均未发起该请求；只检查“token 尚未完成”，导致零请求也被判为通过。 | 不能用该用例证明“无关 token 请求仍在等待时表单已经可用”。应实际启动目标请求，断言请求已开始，表单可用时它仍未完成，再验证延迟结束。原有 PATCH 次数、回读次数和本次采样时长仍可独立观察；此缺口不证明产品性能回退。 |

## 代码依据与复现

### R1：队列字段来源丢失

- `electron/src/renderer/domains/settings/views/SettingsPanel.vue:1897`：queueSavePatch 合并 patch 值，没有保留每个字段来自哪个实例、哪次编辑。
- 同文件 `:1968`：由执行排空操作的实例发布完成通知，owner 代表执行者。
- 同文件 `:1939`：草稿恢复依赖 acknowledged/submitted 区分提交与未提交字段。
- 同文件 `:3671`：其他实例接收完成通知时没有传入对应的字段提交确认，已提交的原始值被当成本地未提交草稿保留。
- 探针第 3 项复现常见排队路径；第 2 项同时覆盖失败转移后的规范化不一致。

### R2：局部错误没有随共享重试确认恢复

- `SettingsPanel.vue:3671` 的其他实例完成处理更新 settings、表单与保存记录，但不协调原实例的 updateRequest.error。
- `SettingsPanel.vue:1796` 的状态标签优先读取旧错误，因此成功后仍显示失败。
- 探针第 2 项断言共享失败为空、settings 为规范化值，但原实例错误仍为真，标签仍为失败。

### R3：运行状态成功读取不协调旧重试错误

- `electron/src/renderer/domains/settings/composables/useSettingsDomain.ts:66`：loadRuntimeStatus 更新 runtimeReload，不清理相关重试错误。
- `electron/src/renderer/domains/settings/components/SettingsRuntimeFeedback.vue:67`：visible 包含 retryError，因此即便已经 applied 也继续显示。
- 探针第 1 项使用同一 svc r7，先模拟重试失败，再读取 applied，确认错误仍存在。

### R4：Teleport 弹层未随停用处理

- `electron/src/renderer/domains/memory/views/MemoryPanel.vue:88`：高级工具 Drawer 使用 append-to-body。
- 同文件 `:1692`：onDeactivated 只调整面板活动状态、同步读取生命周期，没有处理弹层。
- 独立专项使用当前组件、真实 Vue Router、KeepAlive 和 Element Plus，API/store 使用合成数据，在隔离 Chromium 中复现。切换后 `.memory-panel` 不在 body，`.el-drawer` 仍可见；点击新页面按钮超时，Playwright 指出 `.el-overlay.is-drawer.el-modal-drawer` 拦截指针事件。pageerror 为空。
- 这是组件与路由级真实浏览器复现，不是完整生产 AppShell 的端到端实测。证据归档目录：`review-evidence-2026-11-11/panel-lifecycle/memory-drawer/`。

### R5：没有实际发起延迟请求

- `docs/improvement-evidence-2026-11-11/panel-lifecycle/measure_save.py:19` 配置延迟分支，`:36` 导航到 summary，`:40` 仅检查 token 不在完成集合。
- 新脚本 `token_evidence_probe.py` 在延迟分支入口计数，normalized 与 legacy 两种响应均记录 `token_requests_started: 0`、`ready_before_unrelated_token: true`。
- 新脚本和结果写入本次证据目录，未覆盖原始验收材料。

## 验证记录

- 本次定向运行 5 份现有测试文件，共 **122/122 通过**，见 `core-tests.log`。
- 新增临时问题探针 **3/3 通过，49 跳过**，见 `settings-probe.log`。这些断言用于确认现有错误行为，不能解释成修复通过。探针正文保存在 `settings-probe-source.txt`；临时 `.test.ts` 已删除。
- Memory/Stage 专项单独运行两份现有测试，**48/48 通过**。与主审定向结果存在重叠，不合计成 170 项。
- token 证据探针两种情景均无 pageerror，均确认请求未开始，见 `review-token-probe-save.json` 和 `token-evidence-probe.log`。
- 架构复核对 R1～R3 给出 BLOCK；其判断基于实现与主审探针证据，未独立重复运行这三项探针。Memory/Stage 专项另确认 R4。
- 官方 code-reviewer 子代理因配置模型不可用而启动失败，独立代码审查环节未完成；本报告不构成其审批通过。

## 边界与下一步

优先修复 R4 的交互遮挡，再协调 R1/R2 的共享提交确认模型，最后处理 R3 的错误恢复与 R5 的验收断言。每项先补能够区分当前错误行为与目标行为的回归用例，再修改实现。

编辑 Dialog 停用后的 body 滚动锁残留已观察到，但尚未证明对真实 AppShell 的滚动或点击产生影响，不计为独立缺陷。凭据删除成功后回读失败的本地清理完整性也未取得确定复现，不列为事实。

真实 Electron 最小化/恢复、GPU/WebGL 资源、真实后端负载及供应商/音频硬件/Qdrant 等联调仍未在本次验证。旧 /health 超时现场根因和进程是否已经加载此前后端修复，仍需真实环境证据，本次不作关闭判断。上述内容是覆盖边界，不能扩大解释为已证实故障。
