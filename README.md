# Yuizaki / 结崎

[![CI](https://github.com/Rivulet138/yuizaki/actions/workflows/ci.yml/badge.svg)](https://github.com/Rivulet138/yuizaki/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/Rivulet138/yuizaki)](https://github.com/Rivulet138/yuizaki/releases/latest)
[![License](https://img.shields.io/github/license/Rivulet138/yuizaki)](LICENSE)

本地优先的 Windows/Linux AI 桌面伴侣：文字与语音对话、Live2D/VRM 桌宠、长期记忆、按请求视觉、工具和本地桌面动作。

## 主要功能

- 流式文字对话：会话隔离、历史、取消、恢复和分支。
- Agent 执行：统一 TurnService、工具调用、MCP、插件、计划任务和心跳。
- 桌宠：Live2D/VRM、表情、动作、注视、口型、透明窗口和状态同步。
- 语音：按键说话、连续对话、VAD、ASR、流式 TTS 和打断。
- 视觉：请求级屏幕捕获与视觉模型分析，不运行永久录屏循环。
- 记忆：SQLite 权威存储，召回、纠正、审核、软遗忘和永久删除；Qdrant 可选。
- 桌面动作：Windows/Linux X11 的窗口发现、聚焦和关闭，默认关闭。
- 连接器：Telegram、Discord、QQ/微信个人桥，默认关闭并标为实验性。
- 运行治理：Provider、设备、记忆索引、任务、连接器和错误状态可检查。

## 首次运行必需下载

安装包不携带模型权重。设置页会预选缺失资源；“下载选中项”会包含所有缺失必需资源。

| 资源 | 用途 | 预计下载量 | 下载来源 | 上游/致谢 |
| --- | --- | ---: | --- | --- |
| Sherpa SenseVoice + Streaming Zipformer2 | 离线/流式 ASR | 约 188 MiB | `resources.lock.json` 中的 Sherpa ONNX release | [k2-fsa/sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)、[k2-fsa/icefall](https://github.com/k2-fsa/icefall) |
| Qwen3 Embedding 0.6B | 长期记忆向量化 | 约 1.12 GiB | Hugging Face 固定 revision | [QwenLM/Qwen3](https://github.com/QwenLM/Qwen3) |
| Genie TTS 内置角色和模型 | 语音合成 | 约 391 MiB | Hugging Face `High-Logic/Genie` 固定 revision | [High-Logic/Genie-TTS](https://github.com/High-Logic/Genie-TTS) |

Genie 为内置模式：默认固定角色，首次运行下载到本地；可在设置中指定自定义模型目录。使用官方 `High-Logic/Genie` 和 `genie-tts==2.0.2`。预留至少 2 GiB 磁盘空间。许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 技术栈

- Electron 42、Vue 3.5、TypeScript 6、Vite 8、Pinia 3、Element Plus 2。
- PixiJS 8、easy-live2d、Three.js、`@pixiv/three-vrm`。
- Python 3.11–3.13、FastAPI、Pydantic 2、Uvicorn、python-socketio、SQLAlchemy 2、Alembic。
- SQLite、可选 Qdrant；Web Audio、可选 Sherpa-ONNX/Genie TTS；MCP 与 Playwright。
- Go 1.22 Launcher；npm、Ruff、BasedPyright、ESLint、GitHub Actions。

## 目录

```text
electron/                 Electron 主进程、preload、Vue renderer 和构建脚本
python/                   FastAPI、Socket.IO、Agent、记忆、调度器和测试
node-mcp/                 独立 Playwright MCP 服务
tools/yuizaki-launcher/   Go Launcher 源码
scripts/                  文档、资源、锁文件和 staging 检查
docs/                     快速开始、配置、API、架构和平台说明
services/                 可选外部服务（例如 soulx-svc）
.github/workflows/        CI 与发行构建 workflow
```

## 安装与启动

要求：Windows 10/11 x64 或 Linux x86_64、Python 3.11–3.13、Node.js >= 22.13、npm。首次运行必需下载模型；需要自行编译 Launcher 时还需要 Go 1.22；Qdrant 自动启动需要 Docker（Windows）。

### 推荐：Launcher

从源码构建 Launcher：

```powershell
cd electron
npm ci
npm run prepare:launcher:win    # Windows
# Linux 使用：npm run prepare:launcher:linux
cd ..
```

首次配置并启动：

```powershell
.\YuizakiLauncher.exe setup
.\YuizakiLauncher.exe start
```

Linux 对应：

```bash
./YuizakiLauncher setup
./YuizakiLauncher start
```

默认 `start` 打开浏览器对话页；`start --electron-ui` 打开 Electron 控制面板和桌宠窗口。参数：`--check`、`--smoke`、`--no-mcp`、`--with-qdrant`、`--no-install`、`--no-open`、`--no-show-pet`、`--dev-renderer`。命令：`setup`、`start`、`status`、`logs`、`stop`、`install-desktop`、`remove-desktop`。

### 直接运行后端

```powershell
cd python
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
.\.venv\Scripts\python.exe app.py
```

`python/app.py` 创建 FastAPI 应用并用 Uvicorn 启动，默认监听 `127.0.0.1:8001`。Linux 使用 `.venv/bin/python` 和 `cp .env.example .env`。

### Electron 开发与构建

```powershell
cd electron
npm ci
npm run dev
npm run type-check
npm run lint
npm run build
npm run start:check
```

`npm run dev` 同时启动 TypeScript watch、Vite 和 Electron。发行包使用 `npm run package:win` 或 `npm run package:linux`。Electron 没有 `npm test` 脚本。

## 配置

运行配置位于 `python/.env`，持久化设置位于 `python/config/settings.json`。从 `python/.env.example` 开始，不要提交密钥。

```dotenv
LLM_PROVIDER=custom
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_API_KEY=local
LLM_MODEL=your-model
```

主要默认端口：

| 变量 | 默认值 | 用途 |
| --- | ---: | --- |
| `SERVER_PORT` | `8001` | Python HTTP 和 Socket.IO |
| `CONTROL_SERVER_PORT` | `38945` | Electron 控制服务 |
| `RENDERER_PORT` | `5173` | Vite 开发服务器 |
| `MCP_PORT` | `7777` | node-mcp Playwright 服务 |

视觉默认关闭（`VISION_LLM_ENABLED=0`）。语音需要设备、ASR、LLM 和 TTS 资源。SQLite 是记忆权威；Qdrant 仅作可重建索引。变量见 [docs/CONFIGURATION.md](docs/CONFIGURATION.md)。

## API 与关键模块

Python 入口是 [python/app.py](python/app.py)，AI 路由在 `python/routes/ai_api.py`，实时处理在 `python/socket_server.py` 和 `python/socket_handlers/`。Electron 本地控制路由在 `electron/src/main/http/routes/`，前端客户端在 `electron/src/renderer/api/`。

主要接口分组：

- Python：`/api/ping`、`/api/system/*`、`/v1/models`、`/v1/chat/completions`、工作区/会话/记忆/连接器/存储接口，以及 `/socket.io`。
- Electron：`/api/pet/*`、模型与资源管理、系统诊断、Provider 设置、工作区和会话控制接口。
- node-mcp：`http://127.0.0.1:7777/health`、`/tools`、`/sse`。

详细字段和事件契约见 [docs/API.md](docs/API.md)；架构边界见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 验证

```powershell
cd python
python -m pytest tests -q
python -m compileall -q modules routes app.py socket_server.py
cd ..
python scripts/check_docs.py
python scripts/check_resources.py
cd python
python scripts/check_requirements_lock.py
```

CI 还会运行内存、流、连接器和语音 staging checks，以及 Electron `npm ci`、type-check、lint、build、start-check 和 Windows Launcher `go test ./...`。第三方 Provider、音频设备、GPU、桌面 compositor 和角色资源仍需目标机器验证。

## 数据、许可与贡献

默认运行数据在 `python/data/`、`python/config/`、`python/audio_cache/`；Launcher 状态和日志位于用户状态目录或仓库 `logs/`。不要提交 `.env`、数据库、日志、截图、音频缓存、模型权重或个人对话。

源码采用 [MIT License](LICENSE)。角色、模型、声音、字体和其他美术资源可能有独立许可，分发前请阅读 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

贡献前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)、[SECURITY.md](SECURITY.md) 和 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。行为变更应附带相关测试；涉及 Socket.IO、取消、认证、存储删除、恢复或资源权限时，补充针对性验证。
