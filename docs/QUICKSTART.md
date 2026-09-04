# 快速开始

从源码启动 Yuizaki。先验证文字对话，再启用语音、视觉、Qdrant 和连接器。

## 环境

- Windows 10/11 x64，或 x86_64 Linux 图形桌面
- Python 3.11–3.13
- Node.js 22.13+、npm
- Go 1.22+

Launcher 会创建并管理 `python/.venv`。

## 构建 Launcher

The root launcher binaries are generated and ignored by Git:

```powershell
cd electron
npm ci
npm run prepare:launcher
cd ..
```

生成 `YuizakiLauncher.exe` 或 `YuizakiLauncher`，位于仓库根目录。

## 启动

```powershell
.\YuizakiLauncher.exe setup
.\YuizakiLauncher.exe start --check
.\YuizakiLauncher.exe start
```

`setup` 创建 `python/.env` 并配置 LLM；`--check` 只检查，不启动服务。

默认启动会打开浏览器对话页，Electron 仅作为隐藏的本地宿主运行；需要旧 Electron 控制窗口和桌宠时使用 `.\YuizakiLauncher.exe start --electron-ui`。

Linux 构建与启动：

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

默认启动会打开浏览器对话页，Electron 仅作为隐藏的本地宿主运行；需要旧 Electron 控制窗口和桌宠时使用 `./YuizakiLauncher start --electron-ui`。

平台问题见 [LINUX.md](LINUX.md)。

## 首次验收

1. 确认对话页和 Live2D/VRM 模型显示。
2. 配置 LLM provider、endpoint 和 model。
3. 发送文字消息并收到最终响应。
4. 在设置页下载 Sherpa、Embedding、Genie 必需资源。
5. 再启用语音、视觉、工具、MCP 或连接器。

## Launcher 命令

| 命令 | 作用 |
| --- | --- |
| `setup` | 初始化配置与依赖 |
| `start` | 启动并监管服务 |
| `status` | 查看进程和端点 |
| `stop` | 停止服务 |
| `logs [-f]` | 查看或跟踪日志 |
| `install-desktop` | 安装桌面快捷方式 |
| `remove-desktop` | 删除桌面快捷方式 |

常用参数：`--check`、`--smoke`、`--no-mcp`、`--no-install`、`--dev-renderer`、`--no-open`、`--no-show-pet`、`--electron-ui`。Windows 支持 `--with-qdrant`。

## 故障处理

- Launcher 缺失：在 `electron` 执行 `npm run prepare:launcher:*`。
- 虚拟环境缺失：重新执行 `setup`，不要使用 `--no-install`。
- LLM 无响应：检查 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`。
- 端口冲突：修改 `.env` 中的 `SERVER_PORT`、`CONTROL_SERVER_PORT`、`RENDERER_PORT`、`MCP_PORT`。
- 桌宠空白：检查模型路径和 Electron 日志。
- 无声音：检查设备、系统权限、ASR/TTS 资源。
- Wayland 桌面动作受限：使用 X11 或保留应用内窗口交互。

配置见 [CONFIGURATION.md](CONFIGURATION.md)。
