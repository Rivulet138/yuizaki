# 证据与复现索引

所有路径相对于本目录。JSON 中的 calls 为静态文本调用点，不能视为已解析运行图。探针用于复现缺陷，成功退出不等于产品通过验收。

## 证据文件

| 文件 | 内容 |
|---|---|
| environment.json | Git基线、工作树10个既有改动的SHA256、依赖版本、采集时间 |
| python-call-inventory.json | 224文件、3409函数、29221调用点、imports、205个路由/事件声明 |
| typescript-call-inventory.json | 276文件、6316函数/回调、22847调用点、imports |
| python-routes.md | 可读的Python路由/事件静态声明索引，带源码行号 |
| route-manifest.json | 运行中manifest原始结果，仅4条直接注册路由 |
| runtime-http.json | 8001/38945的ping、health、capabilities、manifest状态与耗时；不含凭据 |
| browser-panels.json | 14路由巡检、控件/标题、HTTP状态；含启动504与自动PATCH409 |
| browser-subpanels.json | 26主要子页签与768/390px布局检查 |
| browser-runtime-detail.json | 延长等待后的设置加载、onboarding状态、运行请求状态；两个手工错误探测路径/api/ui-capabilities和/api/route-manifest产生的404是探测者路径写错，不是产品按钮发出的错误，不计入缺陷。正确路径位于/api/system/*，已在runtime-http验证 |
| onboarding-observation.json | 新上下文初始运行引导文字；与真实snapshot区分 |
| *desktop.png、settings-after-20s.png | 控制入口浏览器截图；未做逐像素视觉验收，最终判断以DOM、源码与请求证据为准 |
| pytest-main.xml/log | 全局Python的主线101测试，仅作对照 |
| pytest-venv.xml/log | 项目venv主线101 passed，13.69s |
| pytest-memory-venv.xml/log | 项目venv记忆/召回/写入/检索评估/prompt五文件78 passed，5.54s |
| memory-five-probes.log | 记忆五项缺陷在项目venv的原始输出 |
| backend-probes.log | 6个后端动态场景（4类问题）与1个静态控制流检查 |
| reproduce-tts-bridge.log | 从当前adapter/bridge复现TypeError |
| route-manifest-reproduction.log | 项目venv的include_router可访问但manifest为空 |

pytest 的 basetemp 目录包含本次生成的合成测试夹具，保留在本证据目录内；环境策略阻止了可选的递归清理，本轮没有改用其他删除方式。这些夹具不是用户业务数据。

## 重跑缺陷探针

在 `E:/yuizaki`，使用现有环境，不安装依赖：

```powershell
& 'E:\yuizaki\python\.venv\Scripts\python.exe' -B 'E:\yuizaki\docs\audit-evidence-2026-11-09\memory_five_probes.py'
& 'E:\yuizaki\python\.venv\Scripts\python.exe' -B 'E:\yuizaki\docs\audit-evidence-2026-11-09\backend_probes.py'
& 'E:\yuizaki\python\.venv\Scripts\python.exe' -B 'E:\yuizaki\docs\audit-evidence-2026-11-09\reproduce_route_manifest.py'
node 'E:\yuizaki\docs\audit-evidence-2026-11-09\reproduce-tts-bridge.cjs'
```

memory探针使用内存SQLite、fake embedding与进程内HTTP，禁出站连接。backend探针提取真实函数替换外部依赖，不启动应用。TTS bridge只执行当前adapter与完成handler，不访问声音设备。

## 浏览器巡检

运行中的control端口为38945，脚本使用已有Python Playwright与bundled Chromium，独立headless上下文。

```powershell
python 'E:\yuizaki\docs\audit-evidence-2026-11-09\browser_audit.py'
python 'E:\yuizaki\docs\audit-evidence-2026-11-09\browser_runtime_detail.py'
python 'E:\yuizaki\docs\audit-evidence-2026-11-09\browser_subpanels.py'
```

巡检会产生页面正常的挂载请求，包括诊断、模型目录发现与应用自己的工作区自动保存；不承诺页面导航绝无服务端状态变化。没有主动提交配置、聊天、外部投递或破坏性操作。若将来业务挂载行为改变，应先重新审查脚本范围。

`browser_audit.py`首次通过界面跳过引导；其后两个脚本只在独立测试上下文设置本地completion标记，不将跳过记为readiness通过。部分加载取决于后端延迟，UI无异常不代表所有数据操作成功。

## 重建静态清单

```powershell
python 'E:\yuizaki\docs\audit-evidence-2026-11-09\inventory_python.py'
node 'E:\yuizaki\docs\audit-evidence-2026-11-09\inventory_typescript.cjs'
```

源文件变化后行号可能改变，重跑后需重新核对人工链路与缺陷。原有类型检查、lint、i18n失败明细记录于上级verification报告；没有把人工摘录包装成不存在的原始日志文件。
