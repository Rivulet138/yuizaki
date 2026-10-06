# Yuizaki / 结崎

[![CI](https://github.com/Rivulet138/yuizaki/actions/workflows/ci.yml/badge.svg)](https://github.com/Rivulet138/yuizaki/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/Rivulet138/yuizaki)](https://github.com/Rivulet138/yuizaki/releases/latest)
[![License](https://img.shields.io/github/license/Rivulet138/yuizaki)](LICENSE)

本地优先的 Windows/Linux AI 桌面伴侣 Agent，提供文字与语音对话、Live2D/VRM 桌宠、长期记忆、按请求视觉分析、工具调用和有限桌面动作。

## Genie 角色模型

[下载 Genie 角色模型 Release](https://github.com/Rivulet138/yuizaki/releases/tag/genie-models-2026-10-02)

| 角色包 | 许可证 |
| --- | --- |
| `genie-character-feibi.zip` | Genie 上游 MIT（许可证见压缩包内 `feibi/LICENSE`） |
| `genie-character-huiye.zip` | CC BY-NC-SA 4.0 |
| `genie-character-meihua.zip` | CC BY-NC-SA 4.0 |
| `genie-character-meikuli.zip` | CC BY-NC-SA 4.0 |
| `genie-character-pulachina.zip` | CC BY-NC-SA 4.0 |

压缩包内附许可证和 SHA-256；共享的 GenieData 运行时资源不包含在内。角色包仅用于对应角色模型，分发前请阅读 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。

应用内下载：**设置 → 资源 → Genie TTS 资源 → 预取 Genie 资源**。版本和来源由 [`resources.lock.json`](resources.lock.json) 锁定。

源码运行路径：

```text
python/.cache/GenieData/GenieData
python/CharacterModels/v2ProPlus/<character>
```

打包运行路径：

```text
<Electron userData>/python-data/.cache/GenieData/GenieData
<Electron userData>/python-data/CharacterModels/v2ProPlus/<character>
```

当前 `genie-character-pulachina.zip` 使用 GPT `e15`、SoVITS `e8` 和 `sampling025` 配置；解压目录保持为 `普拉琪娜_e15_e8_correct_sampling_v2`，可直接覆盖旧目录。

## 功能

- 流式文字对话、会话隔离、历史、分支、取消与恢复。
- Agent Turn、规划、工具调用、任务、MCP、插件和计划任务。
- Live2D/VRM 角色、表情、动作、注视、口型和状态投影。
- 按键说话、连续对话、VAD、ASR、流式 TTS 和打断。
- 按请求的屏幕捕获、OCR 和视觉模型分析；默认不运行永久录屏。
- SQLite 记忆权威存储，支持召回、审核、纠正、软遗忘、永久删除、导入、导出和索引重建。
- Windows 和明确的 Linux X11 会话支持可见窗口发现、聚焦和关闭；能力默认关闭并需要独立 host token。
- Telegram、Discord、QQ/微信个人桥提供实验性入口，默认关闭。

## 资源与运行边界

| 资源 | 用途 | 来源/位置 | 要求 |
| --- | --- | --- | --- |
| LLM Provider | 文字 Agent、规划、工具调用 | 用户配置的 OpenAI-compatible 端点 | 文字对话必需 |
| Sherpa SenseVoice / Zipformer2 | ASR | `resources.lock.json` | 启用本地语音时必需，约 188 MiB |
| Qwen3 Embedding 0.6B | 语义记忆检索 | 锁定的 Hugging Face revision | 使用语义记忆时必需，约 1.12 GiB |
| Genie TTS | 本地语音合成 | 锁定的 `High-Logic/Genie` revision | 使用本地 TTS 时必需，约 391 MiB |
| SoulX Singer | 音色转换 | `resources.lock.json` | 可选 |
| Live2D / VRM | 桌宠角色 | 用户导入或明确许可的目录 | 使用桌宠时需要 |
| Qdrant | 可重建语义索引 | 本机 Docker 或远程地址 | 可选 |

模型、声音、角色、字体和美术素材有独立许可。不要将密钥、数据库、个人对话、截图、音频缓存或模型权重提交到 Git。

支持 Windows 10/11 x64 和 Linux x86_64 图形桌面。macOS 没有受支持的应用和原生桌面动作适配器；Wayland 下全局输入钩子和宿主级桌面动作受合成器限制。真实 Provider、音频、GPU、桌面合成器、连接器和长时间运行需要在目标机器验证。

## 安装与启动

### 环境要求

- Windows 10/11 x64 或 Linux x86_64 图形桌面
- Python 3.11–3.13
- Node.js >= 22.13、npm
- Go 1.22+（从源码构建 Launcher）
- Docker（自动启动 Qdrant 时需要）

### Go Launcher

Windows：

```powershell
cd electron
npm ci
npm run prepare:launcher:win
cd ..
.\YuizakiLauncher.exe setup
.\YuizakiLauncher.exe start --check
.\YuizakiLauncher.exe start
```

Linux：

```bash
cd electron
npm ci
npm run prepare:launcher:linux
cd ..
chmod +x YuizakiLauncher
./YuizakiLauncher setup
./YuizakiLauncher start --check
./YuizakiLauncher start
```

默认启动浏览器对话页；需要 Electron 控制面板和桌宠时加 `--electron-ui`。可用参数包括 `--check`、`--smoke`、`--no-mcp`、`--with-qdrant`、`--no-install`、`--no-open`、`--no-show-pet` 和 `--dev-renderer`。

命令和故障处理见 [`docs/QUICKSTART.md`](docs/QUICKSTART.md)。

### 后端开发模式

```powershell
cd python
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
.\.venv\Scripts\python.exe app.py
```

Linux 使用 `.venv/bin/python` 和 `cp .env.example .env`。后端默认监听 `127.0.0.1:8001`。

## 设置

| 文件 | 用途 |
| --- | --- |
| `python/.env` | Provider、端口、可选服务和运行时变量，不提交到 Git |
| `python/config/settings.json` | 应用持久化设置，由设置页或 Launcher 管理 |
| `resources.lock.json` | 模型/资源 URL、revision、校验和及许可边界 |

最小文字配置：

```dotenv
LLM_PROVIDER=custom
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_API_KEY=local
LLM_MODEL=your-model
```

| 变量 | 示例/默认值 | 说明 |
| --- | --- | --- |
| `SERVER_PORT` | `8001` | Python HTTP 和 Socket.IO |
| `CONTROL_SERVER_PORT` | `38945` | Electron control server |
| `RENDERER_PORT` | `5173` | Vite 开发服务器 |
| `MCP_PORT` | `7777` | Node MCP 服务 |
| `VISION_LLM_ENABLED` | `0` | 视觉默认关闭 |
| `MEMORY_BACKEND` | `sqlite` | SQLite 为记忆权威源 |
| `QDRANT_AUTO_START` | `0` | 是否自动启动 Qdrant |
| `ASR_STARTUP_MODE` / `TTS_STARTUP_MODE` | `lazy` | 延迟加载语音资源 |
| `YUIZAKI_INSTALL_PROFILE` | `core` / `full` | 基础或完整 Python 依赖 |

完整配置见 [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md)。默认服务绑定 loopback；云 Provider、MCP、插件、浏览器自动化和远程 Provider 可能按配置访问外部服务或本地数据。安全边界见 [`SECURITY.md`](SECURITY.md)。

## 技术栈与结构

Electron 42、Vue 3、TypeScript、Vite、Pinia、Element Plus、PixiJS、Three.js、Python 3.11–3.13、FastAPI、Socket.IO、SQLite、可选 Qdrant、Sherpa-ONNX、Genie TTS、RapidOCR、Go Launcher。

```text
electron/                 Electron、preload、Vue renderer 和构建脚本
python/                   FastAPI、Agent、记忆、调度器和测试
node-mcp/                 Playwright MCP 服务
tools/yuizaki-launcher/   Go Launcher
scripts/                  文档、资源和锁文件检查
services/                 可选外部服务
docs/                     快速开始、配置、API、架构和平台文档
.github/workflows/        CI 与发行构建
```

## 文档

| 文档 | 内容 |
| --- | --- |
| [`docs/QUICKSTART.md`](docs/QUICKSTART.md) | 启动、首次验收、Launcher 命令和故障处理 |
| [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) | 环境变量、Provider、语音、视觉、记忆和打包 |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 进程边界、Agent 阶段、数据流和权限 |
| [`docs/API.md`](docs/API.md) | HTTP、SSE、Socket.IO、Job、记忆和认证契约 |
| [`docs/LINUX.md`](docs/LINUX.md) | Linux、X11、Wayland、音频、GPU 和桌面限制 |
| [`SECURITY.md`](SECURITY.md) | 安全边界、凭据、MCP、连接器和数据处理 |
| [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) | 依赖、模型、角色、声音和字体许可 |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | 贡献流程和提交边界 |

## 验证

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

## 许可与贡献

源码采用 [MIT License](LICENSE)。MIT 不覆盖模型权重、声音、角色、字体、美术资源或外部服务；分发前阅读 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。贡献前阅读 [`CONTRIBUTING.md`](CONTRIBUTING.md)、[`SECURITY.md`](SECURITY.md) 和 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。

当前版本为可用 Alpha；真实设备资格、跨平台体验、第三方扩展沙箱、长期稳定性和发行治理仍在完善中。
