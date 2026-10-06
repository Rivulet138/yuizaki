# Linux 说明 / Linux notes

## 支持范围 / Supported shape

Linux 启动器面向 x86_64，要求 Python 3.11-3.13、Node.js 22.13+、图形桌面会话，以及与 Electron 兼容的 X11 或 Wayland。Wayland 下会自动选择 Chromium Ozone Wayland 后端；全局输入钩子和宿主级桌面动作可能受合成器策略限制，普通窗口和托盘仍可用。

The Linux launcher targets x86_64 with Python 3.11-3.13, Node.js 22.13+, a graphical desktop session, and an Electron-compatible X11 or Wayland environment. Wayland selects Chromium's Ozone Wayland backend automatically; compositor policy may restrict global hooks and host desktop actions while ordinary windows and the tray remain supported.

## 安装与启动 / Install and start

在支持的开发主机上构建根目录 `YuizakiLauncher`：

Build the root `YuizakiLauncher` executable on any supported development host:

```bash
cd electron
npm run prepare:launcher:linux
cd ..
chmod +x YuizakiLauncher
```

```bash
./YuizakiLauncher setup
./YuizakiLauncher start --check
./YuizakiLauncher start
```

可选 MCP 默认关闭；需要扩展工具时使用 `--with-mcp`，可用 `--no-mcp` 显式保持关闭，`--dev-renderer` 通过 Vite 提供渲染器服务。

Optional MCP is disabled by default. Use `--with-mcp` when extension tools are needed, `--no-mcp` to keep it disabled explicitly, and `--dev-renderer` to serve the renderer through Vite.

## 音频与输入 / Audio and input

确认 PipeWire 或 PulseAudio 的输入/输出设备，并向桌面会话授予麦克风权限。Wayland 可能限制全局鼠标/键盘钩子；实时语音还需要安全的 Electron 上下文和用户授权的麦克风流。

Verify PipeWire or PulseAudio input/output devices and grant microphone permission. Wayland may limit global mouse/keyboard hooks; realtime voice also requires a secure Electron context and a user-granted microphone stream.

## GPU 与桌宠渲染 / GPU and pet rendering

桌宠空白或不稳定时，确认资源路径、尝试较低性能配置并检查 Electron 日志；禁用硬件加速有助于定位驱动问题。隐藏窗口按设计会暂停渲染。

If the pet is blank or unstable, verify asset paths, try a lower performance profile, and inspect Electron logs. Disabling hardware acceleration can isolate driver issues. Hidden windows pause rendering by design.

## 证据边界 / Evidence boundary

Linux CI 可以验证构建和脚本化冒烟路径，但无法覆盖所有合成器、音频设备、GPU 驱动或虚拟形象资源。报告问题时记录操作系统、桌面会话、Provider、模型和硬件。Provider、端口和可选模型设置见 [配置](CONFIGURATION.md)。

Linux CI can validate builds and scripted smoke paths, but it cannot represent every compositor, audio device, GPU driver, or avatar asset. Record the OS, desktop session, provider, model, and hardware when reporting an issue. See [Configuration](CONFIGURATION.md) for providers, ports, and optional model settings.
