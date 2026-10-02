# Yuizaki / 结崎

[![CI](https://github.com/Rivulet138/yuizaki/actions/workflows/ci.yml/badge.svg)](https://github.com/Rivulet138/yuizaki/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/Rivulet138/yuizaki)](https://github.com/Rivulet138/yuizaki/releases/latest)
[![License](https://img.shields.io/github/license/Rivulet138/yuizaki)](LICENSE)

Yuizaki 是一个**本地优先的 Windows/Linux AI 桌面伴侣 Agent**。它把文字和语音对话、Live2D/VRM 桌宠、长期记忆、按请求视觉感知、工具调用和有限的桌面动作组合在一个本地应用中。

它适合希望把 AI 长时间放在桌面上、又希望掌握模型提供商、对话数据、记忆和本地权限的用户。项目默认面向单用户本机运行，不是经过公网加固的 SaaS，也不应直接暴露到互联网。

> **Genie 角色模型下载入口**
>
> [下载 Genie 角色模型 Release](https://github.com/Rivulet138/yuizaki/releases/tag/genie-models-2026-10-02)（包含 `feibi` 和其他内置角色包）。四个非 `feibi` 角色按目录声明 CC BY-NC-SA 4.0，`feibi` 遵循 Genie 上游 MIT 许可；许可证随每个压缩包提供。
>
> 使用应用自动下载时，打开 **设置 → 资源 → Genie TTS 资源 → 预取 Genie 资源**。资源版本和来源由 [`resources.lock.json`](resources.lock.json) 锁定。

## 能做什么

### 对话与 Agent

- 流式文字对话，会话隔离、历史、分支、取消和恢复入口。
- 统一的 Agent Turn，支持规划、工具调用、任务、MCP、插件和计划任务。
- Socket.IO、SSE 和 HTTP 三种本地通信方式。
- 工具结果区分已验证成功、失败、取消和 `unknown_effect`，不会把无法确认的现实副作用伪装成成功。

### 桌宠与语音

- Live2D 和 VRM 角色运行时。
- 表情、动作、注视、口型和 Agent 状态投影。
- 按键说话、连续对话、VAD、ASR、流式 TTS 和打断。
- 透明窗口、托盘、键盘快捷键，以及可选的鼠标按键说话。

### 感知、记忆与本地动作

- 按请求的屏幕捕获、OCR 和视觉模型分析；默认不运行永久录屏循环。
- SQLite 作为记忆权威存储，支持召回、审核、纠正、软遗忘、永久删除、导入、导出和索引重建。
- Qdrant 仅作为可重建的语义检索索引，不是记忆权威源。
- Windows 和明确的 Linux X11 会话支持可见窗口发现、聚焦和优雅关闭；能力默认关闭并需要独立 host token。
- Telegram、Discord、QQ/微信个人桥连接器已提供实验性入口，默认关闭。

### 当前边界

- 支持目标是 Windows 10/11 x64 和 Linux x86_64 图形桌面。
- macOS 没有受支持的应用和原生桌面动作适配器。
- Wayland 下全局输入钩子和宿主级桌面动作可能受合成器限制。
- 模型权重、语音、角色和字体通常需要首次运行时单独下载或由用户提供。
- 本地测试和 CI 不能替代目标机器上的音频、GPU、桌面合成器、Provider、连接器和长时间运行验证。

## 资源类型

Yuizaki 的源码、运行数据和可下载资源分开管理。安装包不默认携带模型权重。

| 资源类型 | 用途 | 默认来源或位置 | 是否必需 |
| --- | --- | --- | --- |
| LLM Provider 和模型 | 文字 Agent、规划和工具调用 | 用户配置的 OpenAI-compatible 本地或远程端点 | 文字对话必需 |
| Sherpa SenseVoice / Zipformer2 | 本地或流式 ASR | `resources.lock.json` 锁定的 Sherpa/icefall 资源 | 启用本地语音时必需，约 188 MiB |
| Qwen3 Embedding 0.6B | 长期记忆向量化 | 锁定的 Hugging Face revision | 使用语义记忆检索时必需，约 1.12 GiB |
| Genie TTS | 本地语音合成 | `High-Logic/Genie` 固定 revision；[角色包 Release](https://github.com/Rivulet138/yuizaki/releases/tag/genie-models-2026-10-02) | 使用内置本地 TTS 时必需，约 391 MiB |
| SoulX Singer | 可选的音色转换服务资源 | `resources.lock.json` 锁定的服务资源 | 可选，体积大，不是基础启动依赖 |
| Live2D / VRM 资源 | 桌宠角色、动作、表情和纹理 | 用户导入或明确许可的资源目录 | 使用桌宠时需要 |
| Qdrant | 可重建的语义索引 | 本机 Docker 或远程地址 | 可选 |
| 插件、MCP 和连接器凭据 | 外部工具、浏览器自动化和消息平台 | Electron vault、环境变量或本地设置 | 可选 |
| 本地运行数据 | 对话、记忆、设置、日志、音频缓存 | `python/data/`、`python/config/`、`python/audio_cache/` 或 userData | 运行时生成 |

资源版本和校验信息以 [`resources.lock.json`](resources.lock.json) 为准。模型、声音、角色、字体和美术素材有独立许可，分发前必须阅读 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。不要把密钥、数据库、个人对话、截图、音频缓存或模型权重提交到 Git。

### Genie 资源位置

- 应用内下载：**设置 → 资源 → Genie TTS 资源 → 预取 Genie 资源**。
- 源码运行的共享资源：`python/.cache/GenieData/GenieData`。
- 源码运行的角色目录：`python/CharacterModels/v2ProPlus/<character>`。
- 打包运行的共享资源：`<Electron userData>/python-data/.cache/GenieData/GenieData`。
- 打包运行的角色目录：`<Electron userData>/python-data/CharacterModels/v2ProPlus/<character>`。

应用会从锁定的 `High-Logic/Genie` revision 下载 Genie TTS 运行时和内置角色资源；Release 中的角色包适合手动保存或离线分发。

## 技术栈

```text
Go Launcher
  └─ Electron 主进程 / preload / control server
       └─ Vue 3 + TypeScript + Vite + Pinia + Element Plus
            ├─ Chat、Settings、Memory、Diagnostics
            ├─ Web Audio、ASR/TTS、Live2D、VRM
            └─ HTTP / SSE / Socket.IO 客户端

Python FastAPI + Socket.IO
  ├─ Agent Runtime、Planner、Tool/Policy、Scheduler
  ├─ Provider、Memory、Connector、MCP 管理
  └─ SQLite 权威存储 + 可选 Qdrant 索引

Node.js Playwright MCP（可选）
```

主要技术包括：

- Electron 42、Vue 3.5、TypeScript 6、Vite 8、Pinia 3、Element Plus 2。
- PixiJS 8、easy-live2d、Three.js、`@pixiv/three-vrm`。
- Python 3.11–3.13、FastAPI、Pydantic 2、Uvicorn、python-socketio、SQLAlchemy 2、Alembic。
- SQLite、可选 Qdrant、Web Audio、Sherpa-ONNX、Genie TTS、RapidOCR。
- Node.js Playwright MCP、Go 1.22 Launcher、npm、Ruff、BasedPyright、ESLint、GitHub Actions、electron-builder。

进程边界和数据流见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。HTTP、SSE 和 Socket.IO 契约见 [`docs/API.md`](docs/API.md)。

## 仓库结构

```text
electron/                 Electron 主进程、preload、Vue renderer 和构建脚本
python/                   FastAPI、Socket.IO、Agent、记忆、调度器和测试
node-mcp/                 独立的 Playwright MCP 服务
tools/yuizaki-launcher/   Go Launcher 源码
scripts/                  文档、资源、锁文件和 staging 检查
services/                 可选外部服务，例如 soulx-svc
docs/                     快速开始、配置、API、架构和平台文档
.github/workflows/        CI 与发行构建 workflow
```

## 安装与启动

### 环境要求

- Windows 10/11 x64，或 Linux x86_64 图形桌面。
- Python 3.11–3.13。
- Node.js >= 22.13 和 npm。
- 从源码构建 Launcher 需要 Go 1.22+。
- Qdrant 自动启动需要 Docker；语音和视觉还需要对应设备、Provider 与资源。

### 推荐方式：Go Launcher

先从源码构建当前平台的 Launcher：

```powershell
cd electron
npm ci
npm run prepare:launcher:win
cd ..
```

Linux 使用：

```bash
cd electron
npm ci
npm run prepare:launcher:linux
cd ..
chmod +x YuizakiLauncher
```

初始化并启动：

```powershell
.\YuizakiLauncher.exe setup
.\YuizakiLauncher.exe start --check
.\YuizakiLauncher.exe start
```

Linux 对应：

```bash
./YuizakiLauncher setup
./YuizakiLauncher start --check
./YuizakiLauncher start
```

默认启动浏览器对话页。需要 Electron 控制面板和桌宠时加入 `--electron-ui`。常用参数包括 `--check`、`--smoke`、`--no-mcp`、`--with-qdrant`、`--no-install`、`--no-open`、`--no-show-pet` 和 `--dev-renderer`。

启动器命令、首次验收和故障处理见 [`docs/QUICKSTART.md`](docs/QUICKSTART.md)。

首次使用请优先通过上面的 Launcher 流程完成环境初始化和启动。下面的方式仅用于后端开发/诊断模式，不会替代 Launcher 对 Electron、桌宠和可选服务的编排。

### 直接启动 Python 后端（后端开发/诊断模式）

```powershell
cd python
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
.\.venv\Scripts\python.exe app.py
```

Linux 使用 `.venv/bin/python` 和 `cp .env.example .env`。后端默认监听 `127.0.0.1:8001`。

### Electron 开发与构建

```powershell
cd electron
npm ci
npm run dev
npm run type-check
npm run lint
npm run test:unit
npm run build
npm run start:check
```

发行包命令为 `npm run package:win` 和 `npm run package:linux`。发布工作流会生成 Windows NSIS、Linux AppImage 和 deb 构建产物，但当前仓库不会自动创建 GitHub Release；正式发布仍需平台资格、签名、校验和与许可报告。

## 设置

### 配置文件

- `python/.env`：Provider、端口、可选服务和运行时环境变量，不提交到 Git。
- `python/config/settings.json`：应用持久化设置，由设置页或 Launcher 管理。
- `resources.lock.json`：模型和资源的 URL、revision、校验和及许可边界。

最小文字配置示例：

```dotenv
LLM_PROVIDER=custom
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_API_KEY=local
LLM_MODEL=your-model
```

### 常用设置

| 设置 | 默认或示例 | 说明 |
| --- | --- | --- |
| `SERVER_PORT` | `8001` | Python HTTP 和 Socket.IO |
| `CONTROL_SERVER_PORT` | `38945` | Electron control server |
| `RENDERER_PORT` | `5173` | Vite 开发服务器 |
| `MCP_PORT` | `7777` | Node MCP 服务 |
| `VISION_LLM_ENABLED` | `0` | 视觉默认关闭，启用后仍按请求处理 |
| `MEMORY_BACKEND` | `sqlite` | SQLite 是记忆权威源 |
| `QDRANT_AUTO_START` | `0` | 是否请求自动启动 Qdrant |
| `ASR_STARTUP_MODE` / `TTS_STARTUP_MODE` | `lazy` | 受限机器上延迟加载语音资源 |
| `YUIZAKI_INSTALL_PROFILE` | `core` / `full` | 选择基础或完整 Python 依赖 |

完整变量、语音、视觉、记忆、连接器、端口和本地信任模型见 [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md)。

### 本地数据和隐私

默认服务绑定 loopback。loopback API 是桌面运行时的本地信任边界，不是公网认证方案。原生桌面动作额外要求 Electron 生成的 `YUIZAKI_HOST_DESKTOP_ACTION_TOKEN`；它必须与 `YUIZAKI_BACKEND_API_TOKEN` 分开保存。

聊天、记忆、设置和缓存默认留在本机；选择云 Provider 时，相应的文字、音频或图像会发送给该 Provider。MCP、插件、浏览器自动化和远程 Provider 可能按配置读取或修改本地数据。启用前请检查权限和工具作用域。详细边界见 [`SECURITY.md`](SECURITY.md)。

## 文档地图

| 文档 | 用途 | 状态 |
| --- | --- | --- |
| [`docs/QUICKSTART.md`](docs/QUICKSTART.md) | 从源码启动、首次验收、Launcher 命令和故障处理 | 用户操作文档 |
| [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) | 环境变量、Provider、语音、视觉、记忆、连接器和打包设置 | 用户/运维文档 |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 进程边界、Agent 阶段、数据流、权限和平台边界 | 开发者文档 |
| [`docs/API.md`](docs/API.md) | HTTP、SSE、Socket.IO、Job、记忆和认证契约 | 开发者文档 |
| [`docs/LINUX.md`](docs/LINUX.md) | Linux、X11、Wayland、音频、GPU 和桌面限制 | 平台文档 |
| [`SECURITY.md`](SECURITY.md) | 安全边界、凭据、MCP、连接器和数据处理 | 安全政策 |
| [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) | 依赖、模型、角色、声音和字体许可提醒 | 发布前必读 |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | 贡献流程和提交边界 | 贡献者文档 |

以下文档是内部评估或过程记录，不是安装和配置指南：

- [`docs/COMPREHENSIVE_REVIEW_2026.md`](docs/COMPREHENSIVE_REVIEW_2026.md)：带日期的产品与技术评估快照。
- [`docs/IMPROVEMENT_RESEARCH.md`](docs/IMPROVEMENT_RESEARCH.md)：外部研究与同类项目参考。
- [`docs/IMPROVEMENT_ROADMAP.md`](docs/IMPROVEMENT_ROADMAP.md)：改进路线、验收记录和历史执行日志。

这些文件目前仍有审计和开发参考价值，不应被视为当前产品承诺；修改实现后需要重新核对其中的日期、评分和状态。

## 验证

本地常用检查：

```powershell
python -m pytest -q
python scripts/check_docs.py
python scripts/check_resources.py
cd python
python scripts/check_requirements_lock.py
cd ..\electron
npm run type-check
npm run lint
npm run test:unit
npm run build
npm run start:check
```

当前 CI 还覆盖 Python 3.11–3.13、Windows/Linux、Node 22/24、Node MCP 和 Windows Go Launcher。测试通过不等于真实 Provider、声卡、GPU、桌面合成器、连接器或 24 小时运行已经取得发布资格；这些能力需要目标机器验证。

## 许可与贡献

源码采用 [MIT License](LICENSE)。MIT 不自动覆盖模型权重、声音、角色、字体、美术资源或用户选择的外部服务；分发前阅读 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。

贡献前请阅读 [`CONTRIBUTING.md`](CONTRIBUTING.md)、[`SECURITY.md`](SECURITY.md) 和 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。不要提交 API 密钥、个人数据、聊天历史、截图、音频缓存、数据库、日志或模型权重。涉及 Socket.IO、取消、认证、存储删除、恢复或资源权限的改动必须补充针对性测试。

## 项目状态

Yuizaki 当前是**功能广泛、正在封板的可用 Alpha**。核心文字链路和本地合同已有较多自动化测试，但真实设备资格、跨平台体验、第三方扩展沙箱、长期稳定性和正式发行治理仍在完善中。请把 Issue 或 PR 中的操作系统、桌面会话、Provider、模型、硬件、启动参数和脱敏日志一并提供。
