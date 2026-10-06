# 快速开始 / Quickstart

从源码启动 Yuizaki。先验证文字对话，再启用语音、视觉、Qdrant 和连接器。

Start Yuizaki from source. Verify text chat first, then enable voice, vision, Qdrant, and connectors.

## 环境 / Requirements

- Windows 10/11 x64 或 x86_64 Linux 图形桌面 / Windows 10/11 x64 or x86_64 Linux desktop
- Python 3.11-3.13
- Node.js 22.13+、npm / Node.js 22.13+ and npm
- Go 1.22+

Launcher 会创建并管理 `python/.venv`。

The launcher creates and manages `python/.venv`.

## 构建 Launcher / Build the launcher

根目录启动器由 `electron` 生成：

Build the root launcher from `electron`:

```powershell
cd electron
npm ci
npm run prepare:launcher
cd ..
```

生成 `YuizakiLauncher.exe` 或 `YuizakiLauncher`，位于仓库根目录。 / This creates `YuizakiLauncher.exe` or `YuizakiLauncher` in the repository root.

## 启动 / Start

```powershell
.\YuizakiLauncher.exe setup
.\YuizakiLauncher.exe start --check
.\YuizakiLauncher.exe start
```

`setup` 创建 `python/.env` 并配置 LLM；`--check` 只检查，不启动服务。默认打开浏览器对话页；需要 Electron 控制面板和桌宠时加 `--electron-ui`。

`setup` creates `python/.env` and configures the LLM; `--check` validates without starting services. The default opens the browser chat; add `--electron-ui` for the Electron control panel and pet window.

Linux： / Linux:

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

## 首次验收 / First-run checks

1. 确认对话页和 Live2D/VRM 模型显示。 / Confirm the chat page and Live2D/VRM model render.
2. 配置 LLM provider、endpoint 和 model。 / Configure the LLM provider, endpoint, and model.
3. 发送文字消息并收到最终响应。 / Send a text message and receive a terminal response.
4. 在 **设置 → 资源** 下载 Sherpa、Embedding 和 Genie 资源；Genie 使用 **Genie TTS 资源 → 预取 Genie 资源**。角色包可从 [Genie character models Release](https://github.com/Rivulet138/yuizaki/releases/tag/genie-models-2026-10-02) 下载。 / In **Settings → Resources**, download Sherpa, Embedding, and Genie assets; use **Genie TTS Assets → Prefetch Genie Assets**. Character bundles are available from the linked release.
5. 再启用语音、视觉、工具、MCP 或连接器。 / Then enable voice, vision, tools, MCP, or connectors.

## Launcher 命令 / Launcher commands

| 命令 / Command | 作用 / Purpose |
| --- | --- |
| `setup` | 初始化配置与依赖 / Initialize configuration and dependencies |
| `start` | 启动并监管服务 / Start and supervise services |
| `status` | 查看进程和端点 / Show processes and endpoints |
| `stop` | 停止服务 / Stop services |
| `logs [-f]` | 查看或跟踪日志 / View or follow logs |
| `install-desktop` | 安装桌面快捷方式 / Install desktop shortcuts |
| `remove-desktop` | 删除桌面快捷方式 / Remove desktop shortcuts |

常用参数：`--check`、`--smoke`、`--no-mcp`、`--no-install`、`--dev-renderer`、`--no-open`、`--no-show-pet`、`--electron-ui`。Windows 支持 `--with-qdrant`。

Common flags: `--check`, `--smoke`, `--no-mcp`, `--no-install`, `--dev-renderer`, `--no-open`, `--no-show-pet`, and `--electron-ui`. Windows also supports `--with-qdrant`.

## 故障处理 / Troubleshooting

- Launcher 缺失：在 `electron` 执行 `npm run prepare:launcher:*`。 / Missing launcher: run `npm run prepare:launcher:*` in `electron`.
- 虚拟环境缺失：重新执行 `setup`，不要使用 `--no-install`。 / Missing virtual environment: run `setup` again without `--no-install`.
- LLM 无响应：检查 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`。 / No LLM response: check `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL`.
- 端口冲突：修改 `.env` 中的端口变量。 / Port conflict: change the port variables in `.env`.
- 桌宠空白或无声音：检查模型路径、设备、权限和 Electron 日志。 / Blank pet or no audio: check asset paths, devices, permissions, and Electron logs.
- Wayland 桌面动作受限：使用 X11 或保留应用内窗口交互。 / Restricted Wayland actions: use X11 or keep interactions inside the app window.

完整设置见 [CONFIGURATION.md](CONFIGURATION.md)，Linux 限制见 [LINUX.md](LINUX.md)。 / See [CONFIGURATION.md](CONFIGURATION.md) for settings and [LINUX.md](LINUX.md) for Linux limitations.
