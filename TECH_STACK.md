# 技术栈

Python 直接运行依赖使用平台 lock 文件；模型质量回归使用 `python -m evals`，指标和 fixture 见 [MODEL_EVALUATION.md](MODEL_EVALUATION.md)。

## 桌面与界面

| 技术 | 用途 |
| --- | --- |
| Electron 42 | Windows/Linux 桌面应用、透明桌宠窗口、系统能力 |
| Vue 3 | 控制面板与桌宠界面 |
| TypeScript 6 | 桌面端与前端类型系统 |
| Vite 8 | 前端构建 |
| Pinia | 应用状态 |
| Vue Router | 面板导航 |
| Element Plus | 表单、菜单、对话框和数据控件 |
| PixiJS | Live2D 渲染 |
| Three.js + `@pixiv/three-vrm` | VRM 渲染 |
| `uiohook-napi` | 鼠标侧键与全局输入 |

## Agent 与服务

| 技术 | 用途 |
| --- | --- |
| Python 3.12–3.13 | Agent、语音、视觉、记忆和工具服务 |
| FastAPI | HTTP API |
| Socket.IO | 实时语音、模型输出、桌宠动作和状态同步 |
| Pydantic | 配置与协议校验 |
| SQLAlchemy + SQLite | 对话、设置和长期记忆 |
| Qdrant | 可选语义记忆检索 |
| Express + Playwright | 浏览器 MCP 服务 |

## AI 能力

| 能力 | 当前方案 |
| --- | --- |
| 文本模型 | OpenAI 兼容 API，可接云端或本地服务 |
| 视觉模型 | 独立 OpenAI 兼容视觉端点 |
| 实时视觉 | 屏幕关键帧、变化检测、VLM 优先、OCR fallback、会话级最新帧 |
| OCR | RapidOCR ONNX Runtime |
| 流式 ASR | Sherpa ONNX |
| 流式 ASR 模型 | Sherpa Streaming Zipformer2 CTC INT8（默认，约 20 MiB） |
| 可选 ASR | SenseVoiceSmall/FunASR 兼容服务或 Sherpa SenseVoice（显式选择才准备） |
| TTS | Genie TTS |
| SVC | SoulX Singer SVC |
| 嵌入 | Sentence Transformers + Qwen3 Embedding 0.6B |
| Reranker | 可选 Sentence Transformers CrossEncoder，默认 `BAAI/bge-reranker-v2-m3` 且关闭 |
| Token 预算 | tiktoken |

LLM wire protocol is selected per provider: Claude uses Anthropic Messages, Gemini uses native `generateContent`/`streamGenerateContent` unless an explicit `/openai` gateway is configured, and DeepSeek/Qwen/OpenAI/xAI/Ollama/LM Studio/custom use the OpenAI Chat Completions contract. The client converts internal messages, images, tools, generation settings, and normalized responses at the adapter boundary.

## 数据与资源

| 数据 | 默认方案 |
| --- | --- |
| 对话 | SQLite |
| 长期记忆 | SQLite |
| 语义索引 | Qdrant，可选 |
| 模型缓存 | 按需下载到受管目录 |
| 模型锁定 | `resources.lock.json` |
| 临时音频 | 定时清理 |
| 实时视觉帧 | 内存，不建立默认截图历史 |

启动性能：核心服务先完成轻量注册，Genie TTS 默认后台加载并预热，不阻塞主启动链；低资源设备可切换为 lazy load。服务管理器会记录每个初始化阶段耗时，并在失败时回滚已启动服务。

## 工程工具

| 范围 | 工具 |
| --- | --- |
| 前端测试 | Vitest、Vue Test Utils、Happy DOM |
| Python 测试 | pytest、`python -m evals` 模型评测 smoke suite |
| 类型检查 | TypeScript、Pyright |
| 代码检查 | ESLint、Ruff |
| CI | GitHub Actions，Windows 与 Ubuntu |
| 依赖更新 | Dependabot |
| 容器 | Docker Compose，Qdrant 与 SoulX |

代码依赖版本以 `electron/package-lock.json`、`node-mcp/package-lock.json` 和 `python/requirements*.txt` 为准；模型版本以 `resources.lock.json` 为准。

## 同类项目参考

| 项目 | 可借鉴方向 | Yuizaki 取向 |
| --- | --- | --- |
| [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber) | 模块化 LLM/ASR/TTS、语音打断、视觉、跨平台桌宠 | 保留可替换模型层，强化系统级桌宠与 Agent 行动 |
| [Project AIRI](https://github.com/moeru-ai/airi) | 数字角色、Agent、MCP、游戏与外部环境互动 | 聚焦本机桌面场景、权限和长期陪伴 |
| [Utsuwa](https://github.com/The-Lab-by-Ordinary-Company/utsuwa) | 角色优先界面、VRM、本地数据、关系成长 | 同时支持 Live2D/VRM，强化实时视觉和插件 |
| [Petto](https://github.com/funnycups/petto) | 低步骤启动、按需下载、Live2D 桌面交互 | 保持核心安装轻量，模型首次使用再准备 |
| [Soul of Waifu](https://github.com/jofizcd/Soul-of-Waifu) | 本地模型、角色扮演、Live2D/VRM、长期记忆 | 保持本地优先，但提供更明确的工具权限边界 |

### Reranker 候选评估

| 模型 | 适合场景 | 当前结论 |
| --- | --- | --- |
| `BAAI/bge-reranker-v2-m3` | 多语言、Sentence Transformers CrossEncoder、成熟且易部署 | 默认推荐；中文桌宠记忆的兼容性和成本最平衡 |
| `Qwen/Qwen3-Reranker-0.6B` | 中文/多语言、较新的 Qwen 生态 | 可作为下一阶段实验候选，但需要验证 Transformers 自定义推理接口，不能直接假设兼容 CrossEncoder |
| `jinaai/jina-reranker-v2-base-multilingual` | 多语言检索、较小模型 | 许可证和商业分发边界需单独确认，不作为默认资源 |
| `BAAI/bge-reranker-v2-gemma` | 更高容量的重排 | 对桌面端延迟和显存成本过高，不推荐默认使用 |

## 技术选择原则

- 桌宠窗口、快捷键和屏幕能力留在 Electron。
- Agent、语音、视觉和记忆留在 Python。
- 文本模型与视觉模型独立配置。
- 本地与云端模型使用同一兼容接口。
- 模型按需下载，固定版本并校验内容。
- 用户数据默认本地保存，可导出、备份和永久删除。
