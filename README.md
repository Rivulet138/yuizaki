# 结崎 Yuizaki

[![Release](https://img.shields.io/github/v/release/Rivulet138/yuizaki)](https://github.com/Rivulet138/yuizaki/releases/latest)
[![License](https://img.shields.io/github/license/Rivulet138/yuizaki)](LICENSE)

本地优先的 Windows / Linux AI 桌面伴侣 Agent，提供文字与语音对话、Live2D/VRM 桌宠、长期记忆、按需视觉、工具调用和有限的桌面动作。

## Genie TTS 

1. Genie TTS 资源：启动后进入 **设置 → 资源 → Genie TTS 资源 → 预取 Genie 资源**。当前锁定 Genie TTS 2.0.2，下载量约 391 MiB。
2. Genie 角色包：从 [Genie character models Release](https://github.com/Rivulet138/yuizaki/releases/tag/genie-models-2026-10-02) 下载并放入角色模型目录。角色包不是根目录 MIT 许可证自动覆盖的源码文件，分发前必须阅读 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。

源码运行时的默认路径如下；使用打包版时，路径会映射到 Electron `userData` 下的 `python-data`：

| 内容 | 默认路径 |
| --- | --- |
| Genie 运行时与缓存 | `python/.cache/GenieData/GenieData` |
| Genie 角色包 | `python/CharacterModels/v2ProPlus/<character>` |

```dotenv
LLM_PROVIDER=custom
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_API_KEY=local
LLM_MODEL=your-chat-model

TTS_PROVIDER=genie-tts
TTS_GENIE_CHARACTER=普拉琪娜_e15_e8_correct_sampling_v2
TTS_GENIE_MODEL_DIR=
TTS_LANG=ja
TTS_DEVICE=cpu
TTS_STARTUP_MODE=lazy
TTS_WARMUP_ENABLED=0
```

如果只需要文字聊天，可以不下载 Genie；如果需要完整语音，还需要麦克风、Sherpa ASR 资源以及可用的音频输入/输出设备。资源版本、校验和与许可边界以 [`resources.lock.json`](resources.lock.json) 为准。

## 快速开始

### 环境

- Windows 10/11 x64 或 x86_64 Linux 图形桌面
- Python 3.11–3.13
- Node.js ≥ 22.13 和 npm
- Go 1.27+，仅在构建 Launcher 时需要
- Docker，仅在启用 Qdrant 时需要

Launcher 会创建并管理 `python/.venv`。首次安装 Genie、ASR 或 Embedding 时，应使用 `full` profile：

```powershell
# Windows
$env:YUIZAKI_INSTALL_PROFILE = "full"
cd electron
npm ci
npm run prepare:launcher:win
cd ..
.\YuizakiLauncher.exe setup
.\YuizakiLauncher.exe start --check
.\YuizakiLauncher.exe start
```

```bash
# Linux
export YUIZAKI_INSTALL_PROFILE=full
cd electron
npm ci
npm run prepare:launcher:linux
cd ..
chmod +x YuizakiLauncher
./YuizakiLauncher setup
./YuizakiLauncher start --check
./YuizakiLauncher start
```

`setup` 创建 `python/.env` 并配置 LLM；`start --check` 只检查配置，不启动服务。默认打开浏览器对话页；加 `--electron-ui` 使用 Electron 控制面板和桌宠。MCP 默认关闭，需要浏览器自动化工具时才加 `--with-mcp`。

常用 Launcher 命令：

| 命令 | 作用 |
| --- | --- |
| `setup` | 初始化配置与依赖 |
| `start --check` | 检查配置，不启动服务 |
| `start` | 启动并监管服务 |
| `status` | 查看进程和端点 |
| `stop` | 停止服务 |
| `logs [-f]` | 查看或跟踪日志 |
| `install-desktop` / `remove-desktop` | 安装或删除桌面快捷方式 |

完整参数、首次验收和故障处理见 [`docs/QUICKSTART.md`](docs/QUICKSTART.md)。

## 功能

- **对话**：流式文字与语音对话、会话隔离、历史与分支、取消与恢复；按键说话、VAD、ASR、流式 TTS 和打断。
- **桌宠**：Live2D/VRM 角色、表情、动作、注视、口型与状态投影。
- **Agent**：Agent Turn、规划、工具调用、任务、MCP、插件与计划任务。
- **记忆**：SQLite 权威存储，支持召回、审核、纠正、软遗忘、永久删除、导入导出与索引重建。
- **隔离**：工作区隔离会话与提示词上下文；设置快照最多 20 份。
- **桌面动作**：Windows 与 Linux X11 下的窗口发现、聚焦和关闭，默认关闭且需独立 host token。
- **可选集成**：`ask_dsh` 把明确要求的编码/测试委托给本机 DSH；`tools/yuizaki-mcp` 把桌宠暴露为 MCP 服务；技能目录导入只读 `SKILL.md`。
- **消息入口**：Telegram、Discord、QQ/微信个人桥均为实验性、默认关闭；QQ 内置桥可在设置里一键托管并扫码登录。

界面支持简体中文、English、日本語 三种语言。

## 资源与许可

大模型、语音、嵌入和角色资源由 [`resources.lock.json`](resources.lock.json) 锁定版本、校验和与许可边界。在应用内获取：**设置 → 资源**。

| 资源 | 用途 | 体积（约） |
| --- | --- | --- |
| 用户配置的 OpenAI-compatible 端点 | 文字 Agent、规划、工具调用 | — |
| Sherpa SenseVoice / Zipformer2 | 本地 ASR | 178 MiB |
| Qwen3 Embedding 0.6B | 语义记忆检索 | 1.12 GiB |
| Genie TTS 2.0.2 | 本地语音合成运行时 | 391 MiB |
| Genie character models | 角色音色与语音模型 | 独立 Release |
| SoulX Singer / Qdrant / QQ 内置桥 | 音色转换 / 可重建语义索引 / 个人号接入 | 可选 |


模型、声音、角色、字体和美术素材有独立许可；不要提交密钥、数据库、个人对话、截图、音频缓存或模型权重。详见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。

## 配置

| 文件 | 用途 |
| --- | --- |
| `python/.env` | Provider、端口与运行时变量 |
| `python/config/settings.json` | 应用设置，由设置页或 Launcher 管理 |
| `python/data/chat.db` | 聊天、会话、工作区上下文与数据 |
| `python/data/settings_history.json` | 设置快照 |

后端开发模式：`cd python && python -m venv .venv`，安装 `requirements.txt`，复制 `.env.example` 为 `.env` 后运行 `app.py`（默认 `127.0.0.1:8001`）。完整变量、端口、视觉/记忆开关和打包方式见 [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md)；服务默认绑定 loopback，安全边界与鉴权见 [`SECURITY.md`](SECURITY.md)。

## 技术栈与结构

Electron 44 · Vue 3 · TypeScript · Vite · Pinia · Element Plus · PixiJS · Three.js · Python 3.11–3.13 · FastAPI · Socket.IO · SQLite · 可选 Qdrant · Sherpa-ONNX · Genie TTS · RapidOCR · Go Launcher

```text
electron/                 Electron、preload、Vue renderer 和构建脚本
python/                   FastAPI、Agent、记忆、调度器和测试
node-mcp/                 可选 Playwright MCP 服务（默认不启动）
tools/yuizaki-launcher/   Go Launcher
scripts/                  文档、资源与锁文件检查
services/                 可选外部服务
docs/                     快速开始、配置、API、架构、国际化与平台文档
```

## 文档

| 文档 | 内容 |
| --- | --- |
| [`docs/QUICKSTART.md`](docs/QUICKSTART.md) | 启动、首次验收、Launcher 命令和故障处理 |
| [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) | 环境变量、Provider、语音、SVC、MCP、视觉、记忆和打包 |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 进程边界、Agent 阶段、数据流和权限 |
| [`docs/API.md`](docs/API.md) | HTTP、SSE、Socket.IO、Job、记忆和认证契约 |
| [`docs/LINUX.md`](docs/LINUX.md) | Linux、X11、Wayland、音频、GPU 和桌面限制 |
| [`docs/I18N.md`](docs/I18N.md) | 三语文案层、校验闸门和新增语言步骤 |
| [`PRODUCT.md`](PRODUCT.md) · [`DESIGN.md`](DESIGN.md) | 产品目标与设计规范 |
| [`SECURITY.md`](SECURITY.md) · [`CONTRIBUTING.md`](CONTRIBUTING.md) | 安全边界与贡献流程 |

## 验证

```bash
cd python && python -m pytest -q && cd ..
python scripts/check_docs.py && python scripts/check_resources.py
cd electron && npm run type-check && npm run lint && npm run test:unit && npm run build
```

完整 CI（含 renderer 类型基线、资源锁校验、Launcher 测试）见 [`.github/workflows/ci.yml`](.github/workflows/ci.yml)。renderer 类型错误基线记录在 [`electron/renderer-types-baseline.json`](electron/renderer-types-baseline.json)：新增错误直接失败，修好后用 `node electron/scripts/check-renderer-types.mjs --update` 收紧。

## 许可

源码采用 [MIT License](LICENSE)。MIT 不覆盖模型权重、声音、角色、字体、美术资源或外部服务。贡献前请阅读 [`CONTRIBUTING.md`](CONTRIBUTING.md) 与 [`SECURITY.md`](SECURITY.md)。

---

## English

A local-first Windows/Linux AI desktop companion agent: text and voice chat, Live2D/VRM pet, long-term memory, on-demand vision, tool calls, and limited desktop actions. Currently a usable alpha.

Genie is the local TTS and character-voice runtime, not the chat LLM. To use Genie, install with `YUIZAKI_INSTALL_PROFILE=full`, prefetch **Settings → Resources → Genie TTS Assets → Prefetch Genie Assets**, and download a compatible character bundle from the [Genie character models release](https://github.com/Rivulet138/yuizaki/releases/tag/genie-models-2026-10-02). Configure an independent OpenAI-compatible chat endpoint for text responses. The default runtime path is `python/.cache/GenieData/GenieData`; character bundles use `python/CharacterModels/v2ProPlus/<character>`.

```powershell
$env:YUIZAKI_INSTALL_PROFILE = "full"
cd electron; npm ci; npm run prepare:launcher:win; cd ..
.\YuizakiLauncher.exe setup
.\YuizakiLauncher.exe start --check
.\YuizakiLauncher.exe start
```

Requires Windows 10/11 x64 or a Linux x86_64 desktop, Python 3.11–3.13, Node.js ≥ 22.13, and Go 1.27+ to build the launcher. Use `--electron-ui` for the Electron panel and pet, `--with-mcp` for browser-automation tools (MCP stays off by default). The UI ships in Simplified Chinese, English, and Japanese.

Highlights: streaming chat with isolated workspaces, agent turns with tools/jobs/MCP/plugins, SQLite-authoritative memory with review and deletion, request-scoped vision, and rollback-able settings snapshots. Desktop control, messaging bridges, and MCP are opt-in and off by default.

Model assets are pinned in [`resources.lock.json`](resources.lock.json); Genie character models ship as a [separate release](https://github.com/Rivulet138/yuizaki/releases/tag/genie-models-2026-10-02). Models, voices, characters, fonts, and artwork carry their own licenses — never commit secrets, databases, conversations, screenshots, audio caches, or model weights.

Docs: [Quickstart](docs/QUICKSTART.md) · [Configuration](docs/CONFIGURATION.md) · [Architecture](docs/ARCHITECTURE.md) · [API](docs/API.md) · [Linux](docs/LINUX.md) · [i18n](docs/I18N.md) · [Security](SECURITY.md) · [Contributing](CONTRIBUTING.md) · [Third-party notices](THIRD_PARTY_NOTICES.md)
