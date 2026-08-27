# Yuizaki / 结崎

[![CI](https://github.com/Rivulet138/yuizaki/actions/workflows/ci.yml/badge.svg)](https://github.com/Rivulet138/yuizaki/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/Rivulet138/yuizaki)](https://github.com/Rivulet138/yuizaki/releases/latest)
[![License](https://img.shields.io/github/license/Rivulet138/yuizaki)](LICENSE)

本地优先的 Windows/Linux AI 桌宠 Agent。将 Live2D 或 VRM 角色、文字与语音对话、视觉、本地记忆、工具执行和桌面交互整合在同一个桌面应用中。

## 功能

| 能力 | 当前实现 | 依赖或边界 |
| --- | --- | --- |
| 文字对话 | 流式输出、会话隔离、历史记录、取消和恢复 | 需要 OpenAI-compatible LLM |
| Agent 执行 | 规划、工具调用、MCP、插件、定时任务、进度与终态 | 工具能力按配置启用 |
| 桌宠形象 | Live2D/VRM、表情、动作、注视、口型、透明桌面窗口 | 需要合法的角色资源 |
| 语音 | 按键说话、连续对话、VAD、ASR、流式 TTS、打断 | 需要麦克风、扬声器和语音 Provider |
| 视觉 | 按请求截屏和视觉理解 | 不持续录屏；需要视觉模型 |
| 本地记忆 | SQLite、召回、纠正、审核、软遗忘、永久删除 | Qdrant 仅作为可选检索索引 |
| 桌面动作 | 窗口发现、聚焦和正常关闭 | Windows、Linux X11；默认关闭 |
| 主动行为 | 心跳、计划任务、频率控制、接受/忽略/取消反馈 | 受本地策略和用户设置约束 |
| 消息连接器 | Telegram、Discord、QQ/微信个人桥 | 实验性，默认关闭 |
| 运行诊断 | Provider、语音设备、记忆索引、平台能力、任务与错误状态 | 位于应用治理和系统面板 |

## 产品目标

- 本地优先：会话、记忆和设置以本地存储为权威数据源。
- 舒适优先：主动行为可控，语音可打断，角色状态与 Agent 状态保持一致。
- 链路完整：感知、理解、规划、执行、反馈和记忆由统一 Turn/Job 协议连接。
- 可检查：工具、记忆、Provider 和失败状态在界面中可查看、重试或撤销。
- 可替换：LLM、ASR、TTS、视觉、MCP、角色和检索后端通过适配器接入。
- 可降级：可选服务不可用时保留文字对话、SQLite 和基础桌宠能力。

## 下载

发布文件位于 [GitHub Releases](https://github.com/Rivulet138/yuizaki/releases/latest)。仓库为私有状态时，需在浏览器登录 GitHub，或使用已认证的 GitHub CLI 下载；匿名直链会返回 404。

| 文件 | 用途 |
| --- | --- |
| `YuizakiLauncher.exe` | Windows x64 源码目录启动器 |
| `YuizakiLauncher` | Linux x86_64 源码目录启动器 |
| `Yuizaki-0.1.0-win-x64.exe` | Windows x64 NSIS 安装包 |
| `SHA256SUMS.txt` | 发布文件校验值 |

Launcher 负责创建环境、安装锁定依赖、启动 Python、MCP 和 Electron，并监督进程退出。独立 Launcher 必须放在源码仓库根目录，不能脱离 `python/`、`electron/` 和 `node-mcp/` 单独运行。

## 快速开始

### 运行要求

- Windows 10/11 x64，或带图形桌面的 Linux x86_64
- Python 3.11-3.13
- Node.js 22.13 或更高版本，附带 npm
- 一个可用的 OpenAI-compatible LLM 服务
- GitHub CLI，仅在从私有仓库命令行下载发布文件时需要
- Go 1.22 仅在自行编译 Launcher 时需要
- Docker 仅在使用自动启动的 Qdrant 时需要

### Windows

```powershell
git clone https://github.com/Rivulet138/yuizaki.git
cd yuizaki
gh release download v0.1.0 --pattern YuizakiLauncher.exe
./YuizakiLauncher.exe setup
./YuizakiLauncher.exe start
```

### Linux

```bash
git clone https://github.com/Rivulet138/yuizaki.git
cd yuizaki
gh release download v0.1.0 --pattern YuizakiLauncher
chmod +x YuizakiLauncher
./YuizakiLauncher setup
./YuizakiLauncher start
```

`setup` 创建 `python/.env`、选择 `core` 或 `full` 依赖配置，并写入首个 LLM 设置。最小本地配置示例：

```dotenv
LLM_PROVIDER=custom
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_API_KEY=local
LLM_MODEL=your-model
```

常用 Launcher 命令：

| 命令 | 作用 |
| --- | --- |
| `setup` | 初始化环境和 Provider |
| `start` | 启动并监督完整应用 |
| `status` | 查看监督进程状态 |
| `logs` | 打开或读取运行日志 |
| `stop` | 停止由 Launcher 管理的服务 |
| `install-desktop` | 创建桌面入口 |
| `remove-desktop` | 删除桌面入口 |
| `start --check` | 只执行启动前检查 |
| `start --no-mcp` | 不启动 MCP 服务 |
| `start --with-qdrant` | 请求启动 Qdrant Docker 服务 |

完整安装与故障处理见 [快速开始](docs/QUICKSTART.md)，Provider、语音、连接器和资源配置见 [配置](docs/CONFIGURATION.md)。

## 平台支持

| 平台 | 应用 | 桌宠窗口 | 原生桌面动作 | 发布状态 |
| --- | --- | --- | --- | --- |
| Windows 10/11 x64 | 支持 | 支持 | 支持 | Launcher、NSIS |
| Linux x86_64 + X11 | 支持 | 支持 | 支持 | Launcher；AppImage/deb 由发布 workflow 构建 |
| Linux x86_64 + Wayland | 支持 | 支持 | 不支持或受 compositor 限制 | Launcher；需目标桌面验证 |
| macOS | 不支持 | 未实现 | 未实现 | 无发布文件 |

自动化测试不等于真实硬件认证。麦克风、扬声器、GPU、模型、Provider、桌面 compositor 和角色资源需要在目标机器上验证。

## 技术栈

| 层 | 技术 |
| --- | --- |
| 桌面应用 | Electron 42、Vue 3.5、TypeScript 6、Vite 8、Pinia 3、Element Plus 2 |
| 角色渲染 | PixiJS 8、easy-live2d、Three.js、`@pixiv/three-vrm` |
| Agent 后端 | Python 3.11-3.13、FastAPI、Pydantic 2、python-socketio |
| 数据与记忆 | SQLite、SQLAlchemy 2、可选 Qdrant |
| 语音与视觉 | Web Audio、可选 Sherpa-ONNX、Genie TTS/OpenAI-compatible TTS、视觉 LLM |
| 工具与自动化 | MCP、插件系统、Playwright、受控桌面动作 |
| 进程管理 | Go Launcher、Electron main process、Python runtime identity/recovery |
| 通信 | HTTP、SSE、Socket.IO、Electron IPC |
| 构建与测试 | electron-builder、Vitest、Pytest、Ruff、BasedPyright、ESLint、GitHub Actions |

## 架构

```text
用户输入 / 麦克风 / 请求级视觉
              |
              v
Electron + Vue + Live2D/VRM
              |
       HTTP / SSE / Socket.IO
              |
              v
TurnService -> AgentPipeline stages -> Planner / ToolExecutor
              |                         |
              |                         +-> MCP / Plugins / Desktop actions
              v
       SQLite chat + memory <-> optional Qdrant projection
              |
              v
  stream / job / voice / avatar events -> 用户反馈
```

Python 负责 Agent 编排、工具、记忆和 Provider；Electron main 负责窗口、设备和宿主能力；Vue renderer 负责交互与可视状态；Launcher 负责依赖准备、端口选择和进程生命周期。详细边界见 [架构](docs/ARCHITECTURE.md)。

## 数据位置

| 数据 | 默认位置 |
| --- | --- |
| 聊天 | `python/data/chat.db` |
| 记忆 | `python/data/memory.db` |
| 设置 | `python/config/settings.json` |
| 环境和密钥 | `python/.env` |
| 生成音频 | `python/audio_cache/` |
| Launcher 日志 | `logs/dev/` |

云端 Provider 只在相应功能启用时接收所需文本、音频或图像。MCP、插件、浏览器自动化、桌面动作和消息连接器具有其配置所声明的能力。启用前阅读 [安全边界](SECURITY.md)。

## 从源码构建

```powershell
cd electron
npm ci
npm run prepare:launcher
npm run type-check
npm run lint
npm test
npm run build
```

Python 验证：

```powershell
cd python
./.venv/Scripts/python.exe -m ruff check .
./.venv/Scripts/python.exe -m pytest -q --tb=short
```

发行构建：

```powershell
cd electron
npm run package:win
```

```bash
cd electron
npm run package:linux
```

## 文档

| 文档 | 内容 |
| --- | --- |
| [快速开始](docs/QUICKSTART.md) | 安装、首次启动、检查和常见故障 |
| [配置](docs/CONFIGURATION.md) | LLM、语音、记忆、连接器、端口和资源 |
| [Linux](docs/LINUX.md) | 音频、X11、Wayland 和系统依赖 |
| [架构](docs/ARCHITECTURE.md) | 进程、模块、数据流和失败边界 |
| [API](docs/API.md) | 本地 HTTP 与实时事件契约 |
| [安全](SECURITY.md) | 数据、工具、桌面动作和连接器边界 |
| [贡献](CONTRIBUTING.md) | 开发流程与质量门 |

## 许可证

源码采用 [MIT License](LICENSE)。模型、声音、角色、字体和美术资源可能适用独立许可证，重新分发前检查 [第三方声明](THIRD_PARTY_NOTICES.md)。
