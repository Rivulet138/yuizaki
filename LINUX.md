# Linux 使用

Linux 与 Windows 使用同一 Electron、Vue 和 Python 代码。当前 CI 在 Ubuntu 上执行构建、测试、启动脚本语法检查和 Xvfb GUI 冒烟。

## 支持范围

- x86_64 主流发行版
- X11；Wayland 通过 Electron/XWayland 兼容层运行
- Node.js 22.13 以上，优先 Node 24 LTS
- Python 3.12
- PulseAudio 或 PipeWire 兼容音频栈

全局鼠标侧键、透明窗口、置顶行为和屏幕捕获受桌面环境及 Wayland 权限影响。功能缺失时应降级为键盘按住说话，不应让桌宠整体无法启动。

## 安装

Ubuntu/Debian 常见依赖：

```bash
sudo apt-get update
sudo apt-get install -y python3.12 python3.12-venv build-essential libxtst6 libasound2t64 libnss3 libgtk-3-0 libgbm1
```

然后：

```bash
chmod +x install_core.sh start.sh scripts/*.sh
./install_core.sh
./start.sh
```

完整安装：

```bash
./install_full.sh
```

模型仍遵循按需下载，不要求启动前拥有全部资源。

## 环境检查

```bash
./scripts/check_linux_environment.sh
bash -n install_core.sh install_full.sh start.sh start_soulx_svc.sh scripts/*.sh
```

开发后端：

```bash
./scripts/run_backend_dev.sh
```

开发桌面端：

```bash
cd electron
npm ci
npm run start:check
npm run dev
```

## Wayland 与全局输入

Wayland 会限制全局输入监听和无提示屏幕捕获。建议顺序：

1. 优先使用桌面门户授权屏幕捕获。
2. 鼠标侧键不可用时使用设置中的键盘按住说话绑定。
3. 必要时以 XWayland 运行 Electron，而不是禁用系统安全机制。
4. 不要要求 root 运行桌宠。

## 音频

确认输入输出设备：

```bash
pactl info
pactl list short sources
pactl list short sinks
```

容器化 SoulX 需要单独映射 GPU 和音频/文件资源。普通 TTS/ASR 本地进程不应依赖容器音频直通。

## GPU

CPU 路径应始终可启动。NVIDIA 加速需要与宿主驱动兼容的 CUDA 运行时；不要因为检测到 GPU 就自动安装或替换系统 CUDA。SoulX 容器基于 CUDA 12.1，详见 [services/soulx-svc/README.md](services/soulx-svc/README.md)。

## 常见故障

- `chrome-sandbox` 权限错误：使用发行版/Electron 推荐的 sandbox 权限，不要长期加 `--no-sandbox`。
- 窗口空白：执行 `npm run start:check`，检查 `libgbm`、GTK、NSS 和显示变量。
- 全局快捷键失效：检查 Wayland 限制，改用键盘绑定或 XWayland。
- 麦克风无数据：检查 PipeWire/PulseAudio source 和桌面权限。
- Python 模型轮子缺失：保持 Python 3.12，确认对应平台 wheel 后再升级 Python。

跨平台发布仍需在目标发行版做真实桌面测试；Xvfb 只能证明窗口可以创建，不能证明音频、门户和鼠标侧键全部可用。
