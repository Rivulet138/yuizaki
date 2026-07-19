# Yuizaki

Yuizaki 是一个本地优先、跨平台的 AI 桌宠 Agent。产品核心是常驻桌面的 Live2D/VRM 角色，以及围绕角色组织的实时语音、屏幕视觉、长期记忆、工具和插件能力；它不是通用工作台。

当前维护基线：2026-07-19，Windows 与 Linux 进入同一 CI 验证矩阵。

## 当前能力

- Live2D 与 VRM 桌宠窗口、拖拽、缩放、点击和动作控制
- 麦克风按住说话、可配置鼠标侧键与键盘快捷键
- 流式 ASR、LLM、分句 TTS、打断和端到端延迟指标
- 实时屏幕帧理解；OCR 仅用于需要精确读字的显式流程
- SQLite 默认长期记忆，可选 Qdrant 语义检索
- MCP、插件、桌宠事件和受控工具调用
- 按需下载 ASR、嵌入、TTS 与 SoulX 资源
- Windows 和 Linux 安装、启动与 CI 冒烟验证

## 运行要求

| 组件 | 最低要求 | 建议 |
| --- | --- | --- |
| Node.js | 22.13 | Node.js 24 LTS |
| Python | 3.12 | 3.12.x |
| 系统 | Windows 10/11、主流 x86_64 Linux | Windows 11 或 Ubuntu 24.04 |
| 内存 | 8 GiB | 16 GiB 以上 |
| GPU | 可选 | 本地 TTS/SVC/视觉模型建议 NVIDIA GPU |
| Docker | 可选 | 使用 Qdrant 或 SoulX 容器时需要 |

Python 3.12 是当前原生模型依赖的兼容基线。Node 22 仍可运行，但新环境优先使用 Node 24 LTS。

## 快速启动

Windows：

```powershell
.\install_core.bat
.\start.bat
```

Linux：

```bash
./install_core.sh
./start.sh
```

完整模型资源不在安装阶段强制下载。首次使用对应能力或在设置中手动准备资源时才下载。详细步骤见 [QUICKSTART.md](QUICKSTART.md) 和 [LINUX.md](LINUX.md)。

## 默认数据行为

- 对话：`python/data/chat.db`
- 长期记忆：`python/data/memory.db`
- 设置：`python/config/settings.json`
- TTS 临时音频：`python/audio_cache/`
- 下载模型：仓库内受管资源目录或用户缓存目录
- 实时视觉：每个会话只保留最新帧于内存，默认不落盘

备份包含默认聊天库、默认长期记忆库、设置、治理状态、音频缓存、桌宠状态和插件。自定义到仓库外的数据库路径与下载模型不自动进入备份。

## 开发验证

```powershell
cd electron
npm ci
npm run type-check
npm run lint
npm test
npm run build

cd ..\python
.\.venv\Scripts\python.exe -m pytest -q
```

Linux 将 Python 命令改为 `.venv/bin/python`。文档契约检查：

```bash
python scripts/check_docs.py
```

## 文档

- [PRODUCT.md](PRODUCT.md)：产品目标、范围与路线
- [ARCHITECTURE.md](ARCHITECTURE.md)：进程、数据流和边界
- [API.md](API.md)：HTTP、Socket.IO 与资源接口
- [ENVIRONMENT_SETUP.md](ENVIRONMENT_SETUP.md)：环境变量与运行配置
- [DEPENDENCIES.md](DEPENDENCIES.md)：依赖基线、升级与供应链策略
- [RESOURCE_MANAGEMENT.md](RESOURCE_MANAGEMENT.md)：模型、缓存、记忆、备份和永久清理
- [REPOSITORY_AUDIT.md](REPOSITORY_AUDIT.md)：本次评估、优先级与实际建议
- [SECURITY.md](SECURITY.md)：安全边界和漏洞报告
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)：第三方代码、模型和素材约束

## 许可

源代码许可见 [LICENSE](LICENSE)。仓库中的 Live2D/VRM 模型、字体、角色图片、参考音频和下载模型不因代码许可证而自动获得再分发许可；分发前必须逐项确认来源和授权。
