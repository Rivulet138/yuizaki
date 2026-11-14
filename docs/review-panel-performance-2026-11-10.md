# 面板切换与保存体验复核（2026-11-10）

范围：上轮面板缓存、舞台生命周期、设置按需加载、保存队列及后端运行配置排队。业务代码只读；复现脚本和结果存放于 `docs/improvement-evidence-2026-11-10/panel-performance-review/`。所有浏览器真实写入均被拦截。审查针对当前源码，包含与本轮功能有关的既有缺口，不把它们一律说成新增回归。

## 已确认问题

| 编号 | 优先级 | 问题和证据 | 具体修法 |
| --- | --- | --- | --- |
| UX-01 | P1 | SettingsPanel在途保存时卸载，随后失败：failedSavePatch仅留在旧实例；新实例failed/pending均为空，未产生失败消息。隔离测试1项通过，断言该缺陷确实存在。 | 把待保存/失败patch及其版本放入共享设置保存协调器，组件只订阅状态；面板卸载不销毁恢复入口；保留更晚输入与凭据删除顺序。离线持久化不得直接写入密钥。 |
| UX-02 | P2 | 首次进入svc时，runtime/status返回failed target7，但可见alerts为空、重试按钮0。顶层提示条件只考虑保存忙碌/写入错误/lastSavedAt，未让运行失败主动显示；retryRuntime未接入模板。 | 为运行应用状态设置独立可见条件；恢复带section和target_revision的重试入口，不通过重复PATCH代替重试；覆盖真实DOM和按钮行为。 |
| UX-03 | P2 | 记忆页已有running重建任务时切换到设置，隐藏1.7秒内仍产生3次任务GET；轮询条件只有disposed/job/sequence，没有active/visible。 | onDeactivated/visibilitychange暂停查询，onActivated恢复单条监视链；不要取消服务端重建任务，返回时读取真实终态。 |
| UX-04 | P2 | 返回缓存记忆页没有重新读取列表（本次为0 GET）；记忆可能已由聊天或其他入口更新，缓存页缺少失效/重新验证流程。 | 保留列表即时显示，激活时进行版本/失效检查并后台刷新；显示刷新状态或更新时间，保留检查器脏草稿。 |
| UX-05 | P2 | 已缓存记忆页时，导航到memory?edit=review-doc不会打开编辑框；openRequestedMemoryDoc只在onMounted调用。 | 在激活及edit参数变更时处理请求，等当前scope数据就绪后定位；去重消费参数，防止重复弹窗或旧响应定位错误条目。 |
| UX-06 | P3 | 聊天保持激活但模拟document.hidden+visibilitychange后，3.1秒仍有1次catalog GET。renderer会暂停，但目录轮询只依赖KeepAlive active。该测试模拟页面可见性，不等价于操作系统最小化实测。 | 为舞台目录轮询补充页面可见性条件和恢复钩子；恢复时只刷新一次，避免与onActivated重复发请求。 |

## 代码位置

- UX-01：`SettingsPanel.vue:1913`（unmounted提前返回），`:1955`（失败patch停放），`:3625`（卸载flush）；共享状态尚未接管失败修改。
- UX-02：`SettingsPanel.vue:13`（提示渲染条件），`:1780`（错误只进入隐藏的详情），`:801`（未接入retryRuntime），`:3583`（svc读取运行状态）。
- UX-03：`MemoryPanel.vue:900`、`:929`、`:1599`（500ms轮询与仅卸载终止）。
- UX-04：`MemoryPanel.vue:768`、`:1607`（首次挂载刷新，缺少激活失效检查）。
- UX-05：`MemoryPanel.vue:1075`、`:1611`（一次性的edit参数处理）。
- UX-06：`BrowserPetStage.vue:374`、`:394`、`:463`（目录轮询与激活/停用钩子）。

## 证据和边界

- `save-unmount.log`：利用现有SettingsPanel回归环境隔离执行保存→卸载→失败→新实例；不把手动生命周期测试称作浏览器LRU淘汰实测。
- `memory-cache.json`：隐藏轮询、缓存返回无列表重读、缓存edit链接不打开；pageerrors为空。
- `runtime-feedback.json`：failed target7响应已读取，但提示和按钮均缺失；pageerrors为空。
- `hidden-document.json`：document.hidden模拟下目录请求继续。
- `live-runtime-status.json`：本轮当前服务GET运行状态HTTP200，各section为applied。不能继续沿用上轮“该接口404、后端一定尚未加载”的现场判断；未向用户真实设置发送写入来验证端到端保存。

已有前端通过结果仍有效，但setup/computed单测不能证明真实提示可见；此前导航成功和单次耗时也不能覆盖失败后卸载恢复、全部缓存面板生命周期或长期内存占用。缓存淘汰、窗口真实最小化/恢复、连续快速导航与保存的P95、长时间GPU/内存占用仍是明确的后续验收项目。

## 独立复核结论

独立代码复核返回 REQUEST CHANGES，确认UX-02，并核对UX-01属于既有恢复缺口；另行执行4个相关测试文件66项通过，仍未覆盖缺失的真实DOM反馈。UX-01由主审追加的隔离生命周期测试确认。

后端队列的独立架构复核未形成可用结论，收敛本轮报告时已停止该审查通道，因此标记 independent review unavailable，不用作者自审替代，也不声明架构CLEAR或整体可合并。上述6项确认发现已经足以给出需要继续修正的结论。

本轮报告没有修改业务实现，临时测试文件已清理；复核范围源码的SHA256与上一轮验收快照一致。后续实际改进优先顺序为UX-01、UX-02，其次将UX-03/04/05作为记忆页生命周期一起修复，最后处理UX-06并补齐真实最小化及长期资源测试。


## 2026-11-11 实施进展

UX01～UX06 的本地实现及隔离验收已完成，并修复共享保存独立复核发现的四个竞态/同步边界。详细实现、最终测试、浏览器合成接口证据和仍未覆盖的真实运行环境边界见 [本轮验收记录](improvement-panel-lifecycle-2026-11-11.md)。本段为后续实施状态；上文保留发现时的原始证据，不再把六项问题列为尚未实现。
