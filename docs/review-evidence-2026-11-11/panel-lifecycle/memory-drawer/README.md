# Memory Drawer lifecycle review evidence

归档日期：2026-11-11。本次仅归档此前实际执行的结果，没有重跑浏览器或测试。

## 文件来源

- fixture-harness.stdin.mjs：从本次会话实际执行的 Node stdin 脚本复制。加载当前 MemoryPanel.vue、真实 Vue Router / KeepAlive / Element Plus；API/store/i18n 通过 Vite 内存插件替换为合成 fixture。另一面板为占位按钮，不是完整 AppShell。
- reproduce-memory-drawer.py：从本次会话实际执行的 Playwright stdin 脚本复制，未为了归档修改其行为。
- browser-output.log：从本次会话浏览器命令实际返回的 stdout 复制；原执行时没有单独的磁盘 stdout 日志，不是重新执行生成的日志。
- browser-result.json：同一份实际 stdout JSON 的归档副本。保留原 screenshot 字段中的临时路径，归档截图在 memory-deactivated-drawer.png。
- memory-deactivated-drawer.png：从原执行生成的临时截图复制，不是重新截图。
- SHA256SUMS.txt：本次归档文件的 SHA256，用于后续完整性核对，不是原运行时生成的源码快照。

## 已证实发现

MemoryPanel.vue:88 的 append-to-body Drawer 未在 MemoryPanel.vue:1692 的 onDeactivated 中关闭。打开高级工具并路由切换后：route=other，memoryInBody=false，visibleDrawers=1；新面板按钮 covered=true，命中 el-overlay is-drawer el-modal-drawer；实际点击超时信息明确报告 intercepts pointer events；pageerrors=[]。

编辑 Dialog 的反证也保留在同一 JSON：停用后 visibleDialogs=0，新面板按钮 covered=false、实际点击 success；返回后未保存草稿为 UNSAVED DIALOG DRAFT。body 锁残留未证实对完整 AppShell 的影响，不列为独立缺陷。

## 原执行方式（仅说明；归档时未执行）

Node 版本：v24.22.1。工作目录：E:\yuizaki\electron。

PowerShell 终端 A（此脚本原先通过 stdin 执行；仍须通过 stdin 运行，避免相对 import 按归档文件目录解析）：

```powershell
Set-Location -LiteralPath 'E:\yuizaki\electron'
Get-Content -Raw -LiteralPath 'E:\yuizaki\docs\review-evidence-2026-11-11\panel-lifecycle\memory-drawer\fixture-harness.stdin.mjs' | & $env:CODEX_MCP_NODE_PATH --input-type=module -
```

终端 B：

```powershell
python 'E:\yuizaki\docs\review-evidence-2026-11-11\panel-lifecycle\memory-drawer\reproduce-memory-drawer.py'
```

独立端口为 127.0.0.1:48947。浏览器拦截非该地址和非只读 HTTP 方法；fixture API 在浏览器内直接返回合成数据。Vite 缓存位于系统临时目录。原验证结束后通过 /__shutdown 关闭了该服务；未使用或关闭主代理的 48945。

## 范围与限制

本证据为专项补充，不代表官方 code-reviewer lane 或合并批准。没有修改业务代码、持久测试或既有 improvement-evidence。此次归档不包含新一次复现，也不声称归档时的工作树仍与原运行源码逐字一致。
