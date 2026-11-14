# R4 Memory Drawer 缓存停用修复与回归

执行日期：2026-11-11。执行环境：Windows、指定 Node 24 路径、真实 headless Chromium 151.0.7922.34。

## 修改

仅修改拥有的 `MemoryPanel.vue`、`MemoryPanel.regression.test.ts`，并在本目录添加证据。未修改 Settings、profiles、其他业务文件或旧证据。

`onDeactivated` 在停止读取前将 `advancedToolsVisible`、`editDialogVisible` 设为 false。继续使用现有 Element Plus v-model 关闭流程释放遮罩、焦点捕获与 body lock；没有手动修改全局 body class、overflow 或其他弹层。Dialog 关闭触发现有同步 watcher 缓存草稿；查询表单、编辑表单与 inspector 状态保留。返回缓存页不会自动恢复弹层，用户重新打开即可继续编辑。

## 先失败再修改

- `unit-red.log`：修改业务代码前运行新增回归，21 项中 2 失败、19 通过。失败分别为 Drawer 与 Dialog 停用后 visible 仍为 true。
- `source-before.sha256`：修复前 MemoryPanel 源文件指纹。
- `browser-before.json`、`before-memory-deactivated-drawer.png`：修改业务代码前真实重跑旧复现脚本。Drawer 停用后仍有 1 个可见 Drawer，按钮 covered=true，实际点击被 overlay 拦截；编辑 Dialog 停用后 body 仍为 hidden。

## 修复后结果

- `unit-green.log`：21/21 通过。新增覆盖关闭 Drawer 并保留 query/top_k、关闭 Dialog 并保留完整编辑草稿与 inspector 草稿，以及切换编辑目标后恢复缓存草稿。
- `eslint.log`：两个拥有文件定向 ESLint，退出码 0，无诊断。
- `renderer-types.log`：renderer type gate 完成，0 known errors、0 new errors，通过。没有更新类型基线。
- `browser-after.json`、`browser-after.log`：真实浏览器断言全部通过。Dialog、Drawer、Drawer 第二轮停用后 visible overlays/dialogs/drawers 均为 0；body class 空、overflow=visible、width 还原；焦点不在 Dialog/Drawer 内。新页按钮每轮均鼠标点击成功并保持焦点，Space 再次触发处理器，累计 otherClicks=6。
- 返回缓存 Memory 后，通过原有 UI 重开编辑 Dialog，文本仍为 `UNSAVED DIALOG DRAFT`；重开 Drawer，查询仍为 `UNSAVED RECALL QUERY`。
- 浏览器 pageerrors=[]，blocked_requests=[]。截图 `edit-deactivated.png`、`advanced-deactivated.png`、`advanced_second_cycle-deactivated.png`。
- `old-evidence-integrity.json`：旧证据所有文件前后 SHA256 相同。

## 隔离与复跑

`fixture-harness.stdin.mjs` 复制自旧证据，只改专属端口为 48957 和临时 Vite 缓存名。加载真实当前 MemoryPanel、Vue Router、KeepAlive、Element Plus；API/store/i18n 沿用合成 fixture。另一路由为占位按钮。浏览器只允许 127.0.0.1:48957 的 GET/HEAD/OPTIONS，没有启动真实后端、访问真实数据或新增依赖。

在 `E:/yuizaki/electron` 的 PowerShell 中启动：

```powershell
Get-Content -Raw -LiteralPath '../docs/fix-evidence-2026-11-11/panel-lifecycle/memory-drawer/fixture-harness.stdin.mjs' | & 'C:/Users/溪羽rivulet/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe' --input-type=module -
```

另一终端在仓库根目录运行：

```powershell
python docs/fix-evidence-2026-11-11/panel-lifecycle/memory-drawer/verify-memory-drawer.py
```

`reproduce-memory-drawer.py` 是用于修复前复现的旧脚本新副本，仅修改端口与截图输出位置；修复后使用 `verify-memory-drawer.py`，它通过 UI 重开已关闭的 Dialog 验证草稿。

定向测试与静态检查（工作目录 `E:/yuizaki/electron`，均使用上述 Node 路径）：

```text
node node_modules/vitest/vitest.mjs run --root . src/renderer/domains/memory/views/MemoryPanel.regression.test.ts
node node_modules/eslint/bin/eslint.js src/renderer/domains/memory/views/MemoryPanel.vue src/renderer/domains/memory/views/MemoryPanel.regression.test.ts
node scripts/check-renderer-types.mjs
```

验证范围为本次隔离 KeepAlive 生命周期；全量测试、构建与主线 profiles 规范化由主线统一确认。本次未扩大业务检查。
