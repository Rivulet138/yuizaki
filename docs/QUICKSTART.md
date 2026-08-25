# Quick start / 快速开始

This guide gets a local text-chat installation running. Voice, vision, semantic retrieval, and SoulX are optional extensions.

本指南用于启动本地文字聊天安装。语音、视觉、语义检索和 SoulX 均为可选扩展。

The launcher binaries are generated and are not stored in Git. For a source
checkout, install Node.js 22.13+ and Go 1.22+, then run `npm ci` and
`npm run prepare:launcher` in `electron`. This creates
`YuizakiLauncher.exe` and `YuizakiLauncher` in the repository root.

启动器二进制不存入 Git。源码检出后，请安装 Node.js 22.13+ 与 Go 1.22+，在
`electron` 目录运行 `npm ci` 和 `npm run prepare:launcher`，随后根目录会生成
`YuizakiLauncher.exe` 与 `YuizakiLauncher`。

## Windows / Windows

```powershell
YuizakiLauncher.exe --check
YuizakiLauncher.exe
```

Set `YUIZAKI_INSTALL_PROFILE=full` before first launch when you need optional
ASR, Genie-TTS, Qdrant, embedding, and model helper packages.

需要可选 ASR、Genie-TTS、Qdrant、嵌入和模型辅助软件包时，请在首次启动前设置 `YUIZAKI_INSTALL_PROFILE=full`。

## Linux / Linux

```bash
./YuizakiLauncher --check
./YuizakiLauncher
```

See [LINUX.md](LINUX.md) before troubleshooting audio, Wayland, or GPU behavior.

排查音频、Wayland 或 GPU 行为前，请先阅读 [LINUX.md](LINUX.md)。

## Minimum provider configuration / 最低服务商配置

Set these fields in `python/.env`:

```dotenv
LLM_PROVIDER=custom
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_API_KEY=local
LLM_MODEL=your-model
```

The endpoint must implement the OpenAI-compatible chat contract expected by the configured adapter. Remote providers may require a real key.

该端点必须实现所配置适配器要求的 OpenAI 兼容聊天协议。远程服务商可能需要真实密钥。

## Launcher modes / 启动模式

`--check` performs preflight only. `--verify` runs the supported verification suite. `--dev-renderer` uses Vite. MCP is enabled by default; `--no-mcp` opts out. Windows also supports `--with-qdrant`, `--no-show-pet`, and `--no-open`.

`--check` 只执行启动前检查。`--verify` 运行受支持的验证套件。`--dev-renderer` 使用 Vite。MCP 默认启用，可用 `--no-mcp` 退出。Windows 还支持 `--with-qdrant`、`--no-show-pet` 和 `--no-open`。

## First checks after startup / 启动后首次检查

1. Confirm the control panel opens and the pet window is visible.
   确认控制面板已打开且桌宠窗口可见。
2. Check `/api/ping` for liveness and `/health` for component status.
   检查 `/api/ping` 的存活状态和 `/health` 的组件状态。
3. Configure or select a model in Settings.
   在设置中配置或选择模型。
4. Send a text message before enabling optional voice or tools.
   启用可选语音或工具前，先发送一条文字消息。
5. Review MCP/plugin permissions before enabling external actions.
   启用外部操作前，检查 MCP/插件权限。

## Common failures / 常见故障

- Missing `python/.venv`: rerun the installer.
- 缺少 `python/.venv`：重新运行安装程序。
- Node version too old: install Node.js 22.13+.
- Node 版本过低：安装 Node.js 22.13+。
- Port conflict: set `SERVER_PORT`, `CONTROL_SERVER_PORT`, `RENDERER_PORT`, or `MCP_PORT`.
- 端口冲突：设置 `SERVER_PORT`、`CONTROL_SERVER_PORT`、`RENDERER_PORT` 或 `MCP_PORT`。
- Blank pet: verify the model path, renderer logs, and model license.
- 桌宠空白：检查模型路径、渲染器日志和模型许可证。
- No voice: verify permissions, provider configuration, model resources, and audio devices.
- 没有语音：检查权限、服务商配置、模型资源和音频设备。
- Degraded health: treat optional ASR/TTS/Qdrant status as a configuration signal, not as a successful voice claim.
- 健康状态降级：将可选 ASR/TTS/Qdrant 状态视为配置提示，不要据此宣称语音功能已经成功。
