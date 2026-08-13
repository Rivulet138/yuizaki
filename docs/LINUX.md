# Linux notes / Linux 说明

## Supported shape / 支持范围

Linux 启动器面向 x86_64 系统，要求 Python 3.11-3.13、Node.js 22.13+、图形桌面会话，以及与 Electron 兼容的 X11 或 Wayland 环境。

The Linux launcher targets x86_64 systems with Python 3.11-3.13, Node.js 22.13+, a graphical desktop session, and an Electron-compatible X11 or Wayland environment.

## Install and start / 安装与启动

```bash
./install.sh core
./start.sh --check
./start.sh
```

默认会启动 MCP。使用 `--no-mcp` 可运行精简模式，使用 `--dev-renderer` 可通过 Vite 提供渲染器服务。

MCP starts by default. Use `--no-mcp` for a reduced run and `--dev-renderer` to serve the renderer through Vite.

## Audio and input / 音频与输入

确认 PipeWire 或 PulseAudio 的输入/输出设备，并向桌面会话授予麦克风权限。在 Wayland 下，全局鼠标/键盘钩子可能受限，但普通窗口交互仍可用。实时语音还需要安全的 Electron 上下文和用户授权的麦克风音频流。

Verify the PipeWire or PulseAudio input/output device and grant microphone permission to the desktop session. Global mouse/keyboard hooks may be limited under Wayland; ordinary window interaction remains available. Realtime voice also requires a secure Electron context and a user-granted microphone stream.

## GPU and pet rendering / GPU 与桌宠渲染

如果桌宠空白或不稳定，请确认资源路径、尝试较低性能配置，并检查 Electron 日志。禁用硬件加速有助于定位驱动问题。隐藏窗口按设计会暂停渲染工作。

If the pet is blank or unstable, verify the asset path, try a lower performance profile, and inspect Electron logs. Disabling hardware acceleration can help isolate driver problems. Hidden windows pause rendering work by design.

## Evidence boundary / 证据边界

Linux CI 可以验证构建和脚本化冒烟路径，但无法覆盖所有桌面合成器、音频设备、GPU 驱动或虚拟形象资源。报告问题时请记录操作系统、桌面会话、服务商、模型和硬件。

Linux CI can validate builds and scripted smoke paths, but it cannot represent every desktop compositor, audio device, GPU driver, or avatar asset. Record the OS, desktop session, provider, model, and hardware when reporting an issue.
