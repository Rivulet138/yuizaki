# 长期记忆机制专项审计

## 结论与验证环境

五个缺陷均在项目解释器 `E:/yuizaki/python/.venv/Scripts/python.exe`、FastAPI 0.143.2 复现。主线重新执行保留的五探针脚本，全部得到预期缺陷输出，退出码 0。脚本在内存 SQLite、fake embedding、进程内 TestClient 上运行，禁止出站连接，未读取真实记忆、下载模型或调用供应商。

记忆代理早期专项为 69 passed / 4 deselected，属于全局 Python/FastAPI 0.128.0。主线随后在项目 venv 对 memory_operations、memory_context_recall、memory_write_pipeline、memory_retrieval_check、prompt_assembly 五文件完整复测，结果 **78 passed，5.54s，未排除用例**；日志与JUnit为 pytest-memory-venv.log/xml。项目环境的五个缺陷探针结果另列。首轮网络阻断曾误伤 Windows asyncio socketpair；调整为仅允许内部 socketpair 后验证，不能将那次隔离错误归因于业务实现。

复现文件：`audit-evidence-2026-11-09/memory_five_probes.py`；原始输出：`memory-five-probes.log`。命令：

```powershell
& 'E:\yuizaki\python\.venv\Scripts\python.exe' -B 'E:\yuizaki\docs\audit-evidence-2026-11-09\memory_five_probes.py'
```

该脚本是缺陷取证器，断言当前错误行为；退出 0 表示错误行为成功复现，不表示系统正确。修复后的回归测试应断言相反的产品契约。

## 完整链路

### 1. 自动写入与候选准入

`python/modules/agent/runtime.py:283` 的 `_project_relationship_user_signal` 消费已提交 turn → `build_user_signal_event` → `modules/system/relationship_runtime.py:65` 的 `write_relationship_memory` → 标准化候选 → `modules/system/memory_write_pipeline.py:602` 的 `persist_relationship_memory` → 准入/provenance 校验、candidate ID 幂等 → 优先 `add_metadata_document`。

因此不能把“存在自动写入链路”解读为所有聊天事实都被无条件长期记住。候选准入、review 状态、layer、scope 和可召回条件都影响结果。显式审核批准会走 add_document；M-02 不能泛化到所有 candidate 或所有手工写入。

### 2. 权威存储与派生索引

`modules/memory/backend_factory.py:16` 创建后端；`sqlite_store.py:108` 管理记忆独立 schema/启动迁移。SQLite 是持久化权威；进程 `_docs`、`_vectors` 与可选 Qdrant 属于派生/运行视图，不能以向量索引成功代替权威写入成功。

M-02 位于 metadata-only 写入与索引 ready 状态之间；M-03 位于 SQLite 提交与 embedding 更新之间。两者均为存储/索引生命周期契约问题，不是检索模型质量不好。

### 3. 召回与过滤

`modules/agent/context_stage.py:100` → prefetch 或 `modules/memory/pipeline.py:103` → 后端向量/词法评分、可选 rerank → 状态/scope/layer 过滤 → 关联扩展 → top-k/token 预算。

普通聊天有 workspace 时固定选择 workspace scope；没有发现自动合并 global、workspace、session 三级记忆的证据。这是当前实现契约，若用户期待“全局事实在任何工作区自动生效”，应明确设计是否采用分层合并、优先级与冲突处理，不能单纯改面板标签。

未发现独立 FTS/BM25 回退路径；已有词法评分不等同于数据库 FTS 索引。没有把词法评分、向量索引和会话摘要混为一种机制。

### 4. 提示词注入与预取有效性

`modules/agent/context_stage.py:193` 将命中整理为 chunks/来源 → `modules/agent/prompt_assembly.py:593` 以不可信证据注入。已有 authority revision 与 prefetch 过期防护，是应保留的保护。

改进应让 UI 能解释本轮为何命中/未命中、来源、scope、layer、索引状态和过滤原因；不要让用户仅凭列表中存在一条记录推断模型已经看到了它。

### 5. 会话摘要是独立上下文

`modules/core/state.py:415` 压缩会话历史 → 可选 LLM 重写与 revision 校验 → `modules/agent/prompt_assembly.py:577` 单独注入。摘要不是向量索引，也不代表长期事实整合。

删除长期记忆是否同步清除已存在摘要、聊天历史或预取中的衍生事实，尚未端到端验证。这应作为后续删除语义验收项，不将“主记录删除”扩大为“模型任何上下文都已忘记”。

### 6. 管理、去重与遗忘

主要入口在 `modules/memory/routes.py`。更新 `:1913`；维护删除 `:1675` → 删除函数 `:1045`；导出 `:1407`。去重包括 candidate ID 幂等、top-5 候选文本比对及维护时精确文本分组；未证明存在对所有语义冲突的自动合并。

软遗忘、审核、过期/质量筛选、永久删除、索引重建和操作 trace 是不同动作。前端应分别显示动作对可召回状态、权威数据与索引的影响。

## M-01：永久删除保留正文并可再次导出

**P1；源码 + 维护 API 合成复现；置信度高。**

位置：`E:/yuizaki/python/modules/memory/routes.py:1045` 删除函数；`:1064` 重建墓碑；`:1074` 保留 `existing.text`；`:1434` 导出记录；`:1713` 维护删除调用。

触发：存在已批准、过期的 candidate；先维护预览，再携带 preview_token 与 `PERMANENT_DELETE` 确认执行，最后 GET `/memory/export?include_state=all`。

```text
preview_status=200 purge_status=200 reported_changed=1
remaining_docs=1 export_status=200
export_contains_synthetic_erased_text=true
```

原因：为防止候选重放而重建墓碑，但墓碑带着原正文和完整 metadata。返回已清除，正文仍可导出；不是单纯记录数仍为 1 的统计问题。

修复：保留最少防重放 ID/scope/状态；清空正文，以及可能携带原文的历史/证据字段，清理派生索引。验收对候选和普通记录、直接删除和维护删除分别执行；all-state 导出、进程视图、重启后查询、派生索引都不含删除标记正文。防重放仍成立，不能靠删除墓碑取消幂等。

## M-02：metadata-only 写入未进入已就绪索引

**P1；SQLite 内存探针复现；置信度高。**

位置：`modules/system/memory_write_pipeline.py:631`；`modules/memory/sqlite_store.py:619`、`:667`；`vector_store.py:477`、`:609`。

触发：SQLite 已执行首次检索建立索引；随后通过 metadata-only 路径增加 semantic/workspace 可召回文档。

```text
durable=1 recalled=0 index_ready=true
recalled_after_rebuild=1
```

新文档已在 SQLite 与 `_docs`，却没有 `_vectors`，也未使 `_index_ready` 失效。检索排除无向量 ID。

修复：metadata-only 写入后标记索引失效，或可靠补建该 ID 向量；同 ID 内容替换也必须更新向量。验收必须先做一次检索再写入，不能只测冷启动；后续检索不手动重建即可命中，状态准确区分待索引/已索引。

## M-03：embedding 故障造成写入报错与持久化分裂

**P1；SQLite 内存故障注入复现；置信度高。**

位置：`modules/memory/sqlite_store.py:557`、`:614`；`vector_store.py:470`。

触发：add_document 中 fake embedding 抛 `synthetic_embedding_failure`。

```text
caught=synthetic_embedding_failure
durable=1 visible=false
```

`_persist` 已提交 SQLite，随后 embedding 失败，尚未更新 `_docs`。调用者看到失败，但数据库已有数据；当前列表看不到，重启后可能出现，容易引起重复重试或对写入状态的误判。

修复：明确以 SQLite 提交为权威的契约。若保留提交，立即同步进程文档视图、标记索引待恢复，返回“已存储/索引失败”的可恢复状态；若业务决定原子失败，则回滚所有权威写入。不要混合两种语义。验收覆盖失败、重试、重启和同 ID 幂等，DB/列表/响应/索引状态始终可解释。

## M-04：scope 更新生成无 session 的孤立记忆

**P2；API 合成复现；置信度高。**

位置：routes.py:414、:419 已有必填规则；`:1913`、`:1957` 更新路径；`:951` 所属会话校验。

触发：原记录为 workspace；PUT `/memory/docs/{id}`，请求仅 `{"scope":"session"}`。

```text
update_status=200 persisted_scope=session persisted_session=null
subsequent_delete_status=403
```

更新仅验证原记录访问权，未验证合并后的 scope/session。修复应对最终文档调用同等约束，缺失/null/空白 session_id 均拒绝，保持原记录不变。验收还应覆盖 global/workspace/session 互转与跨工作区访问，迁移已有孤立记录需显式归属策略，不能猜测所属会话。

## M-05：关系扩展突破 relation_limit

**P2；管线合成复现；置信度高。**

位置：pipeline.py:229 外层配额；`:233` 邻居遍历；`:248` 接受；`:261` trace。

触发：1 个锚点关联 6 个可用邻居，relation_limit=1、top_k=10。

```text
selected=7 relation_attempted=6 relation_accepted=6
expansion_truncated=false
```

配额只在外层 while 检查，单次内层循环接受所有邻居。最终 top-k 仍有效，不是无限返回。

修复：每次接受前检查剩余配额，到限退出；有未处理邻居时标记 truncated。验收覆盖 0/1/N 配额、去重/循环、跨 scope、过滤后预算；trace 的 attempted/accepted/truncated 与实际一致。

## 面板需要同步改变的操作反馈

1. Library 显示权威记录与索引状态，解释“列表有而尚不可召回”。
2. Review 批量批准显示每项准入、持久化、索引的结果；失败重试保持 candidate ID。
3. 删除确认说明软遗忘/永久删除作用范围；永久删除成功必须遵守 M-01 验收，不能只看 changed_count。
4. 导入/导出显示 include_state、scope、session 和版本；不以导出成功证明已清除内容不存在。
5. 重建、取消与维护操作显示操作 ID、进度、终态和失败项；新请求不能被旧轮询覆盖。
6. 召回调试展示最终 chunks/来源、过滤原因和预算截断，而不是仅显示原始向量分数。
