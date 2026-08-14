# Research, interaction decisions, and release review / 研究、交互决策与发布核验

This is the evidence record for the chat-panel and desktop-pet refactor completed in 2026. It records the sources used for product decisions, the repository facts that were checked, and the boundary between a source release and an end-user bundle.

本文记录 2026 年聊天面板与桌宠交互重构所依据的资料、仓库核验事实，以及源码发布包与用户二进制包之间的边界。

## Evidence used / 参考证据

### Papers and standards / 论文与标准

| Source | Applied decision |
| --- | --- |
| [CHI 2024: System and User Strategies to Repair Conversational Breakdowns of Spoken Dialogue Systems](https://doi.org/10.1145/3640794.3665558) | Voice interaction must expose interruption and recovery instead of trapping the user in a turn. |
| [Information 2024: User Experience and Usability of Voice User Interfaces](https://doi.org/10.3390/info15090579) | Keep voice state close to the composer and make the active state, failure state, and exit action visible. |
| [CHI 2024: Understanding Public Perceptions of AI Conversational Agents](https://doi.org/10.1145/3613904.3642840) | Avoid unexplained anthropomorphic claims; show what the agent is doing without pretending that an animation is an internal feeling. |
| [Applied Sciences 2025: Emotional Embodied Conversational Agent](https://doi.org/10.3390/app15084256) | Use a small number of high-level embodiment states and avoid exposing low-level animation controls in the primary chat flow. |
| [Frontiers in Robotics and AI 2025: Building for speech](https://doi.org/10.3389/frobt.2024.1356477) | Audio systems need explicit playback, latency, and barge-in affordances. |
| [PNAS 2025: Benefits and dangers of anthropomorphic conversational agents](https://doi.org/10.1073/pnas.2415898122) | Keep the pet linkage optional and bounded; do not make continuous presence or emotional dependence the default. |
| [Frontiers in Psychology 2025: Uncanny valley in embodied conversational agents](https://doi.org/10.3389/fpsyg.2025.1625984) | Prefer restrained, intention-level animation and a predictable idle state. |
| [arXiv 2025: LLM-Enhanced Dialogue Management for Full-Duplex Spoken Dialogue Systems](https://doi.org/10.48550/arxiv.2502.14145) | Treat generation, audio, and interruption as separate asynchronous states with identity checks. |

上述论文共同支持以下决策：语音必须可中断并可恢复；状态反馈应靠近输入区；桌宠只表达高层意图；联动默认可关闭；不要用持续动画或拟人化文案掩盖系统真实状态。

### Comparable projects / 类似项目

The following projects were reviewed for information architecture and feature boundaries, not copied as implementation dependencies:

以下项目用于比较信息架构和功能边界，不作为本项目的实现依赖：

- [AIRI](https://github.com/moeru-ai/airi): desktop embodiment, voice, and model-provider separation.
- [Open WebUI](https://github.com/open-webui/open-webui): task-first chat surface with secondary diagnostics.
- [SillyTavern](https://github.com/SillyTavern/SillyTavern): explicit session and provider controls.
- [Warashi](https://github.com/inni918/warashi): compact companion interaction loop.
- [LyraMate](https://github.com/andreadx95/LyraMate): bounded desktop-companion controls.

## Repository facts checked / 仓库实际核验

- The renderer has separate chat, audio, pet-renderer, session, and runtime-event modules. The refactor keeps those boundaries and only composes playback controls in the chat composer.
- `ChatPlaybackBar` shows processing/playing state, the latest assistant-response summary, a stop action, and an explicit pet-link toggle in one place.
- Advice-feed presentation was removed from the composer. Advice storage APIs remain untouched, so this is a presentation simplification rather than data loss.
- `AppShell` no longer repeats streaming chat status above non-chat panels.
- `python/audio_cache/`, `python/data/`, model directories, logs, Electron build output, screenshots, and test caches are ignored and are not release inputs.
- Automated evidence covers renderer type-check, lint, unit tests, build, and Electron TypeScript compilation. Hardware/provider quality still requires a target-machine smoke run.

仓库核验结论：聊天、音频、桌宠、会话和运行时事件仍保持模块边界；播放控制条集中处理状态、停止和桌宠联动；建议流只移除聊天输入区的展示，不删除数据 API；非聊天页面不再重复显示流式聊天状态；本地数据库、音频缓存、模型、日志、构建物、截图和测试缓存均不属于发布输入。自动化检查不能替代目标设备上的麦克风、扬声器、模型和角色资源验收。

## License and redistribution review / 许可证与再分发核验

| Item | Source-of-truth | Release decision |
| --- | --- | --- |
| Yuizaki source | Root `LICENSE` | MIT; include the license and copyright notice. |
| JavaScript and Python packages | Package manifests and lock files | Recheck exact installed metadata for every binary build and ship required notices. |
| Sherpa SenseVoice | `resources.lock.json`, FunASR model card | Reference/checksum only by default; do not bundle weights without model-card review. |
| Sherpa streaming Zipformer2 | `resources.lock.json`, Apache-2.0 upstream notice | Bundle only with Apache notices and the exact model terms. |
| Qwen3 Embedding 0.6B | `resources.lock.json`, Hugging Face model card | Bundle only after preserving Apache notice and model-card terms. |
| Genie TTS 2.0.2 | `resources.lock.json`, MIT upstream notice | Package license is permissive; voices and reference audio remain separately licensed. |
| SoulX Singer and preprocess assets | `resources.lock.json`, upstream repositories | Keep optional and external by default; verify every model/preprocess asset before distribution. |
| Live2D/VRM, fonts, artwork, voices | Asset-specific notices and vendor terms | Do not redistribute unless the exact asset license grants it. |

These declarations are an engineering release checklist, not legal advice. A public source push may include source and lock metadata; it must not include downloaded model weights, user data, API keys, local databases, audio cache, logs, or test screenshots.

以上是工程发布清单，不构成法律意见。公开源码可以包含源码与锁文件元数据，但不得包含下载的模型权重、用户数据、API 密钥、本地数据库、音频缓存、日志或测试截图。

## Public-release gate / 公开发布门槛

1. Run `npm run type-check`, `npm run lint`, `npm test`, `npm run build`, and the Electron TypeScript build.
2. Run a target-machine smoke test with the selected provider, microphone, speaker, TTS provider, and avatar asset.
3. Generate a dependency/license report from the exact lock files used for the binary.
4. Inspect the staged file list. Reject `.env`, databases, caches, logs, model directories, `dist/`, screenshots, and temporary test output.
5. Publish the bilingual README, security boundary, third-party notices, and this evidence record with the same release tag.

1. 运行类型检查、Lint、测试、构建和 Electron TypeScript 构建。
2. 使用目标服务商、麦克风、扬声器、TTS 服务和桌宠资源完成目标设备冒烟测试。
3. 根据构建所用的精确锁文件生成依赖与许可证报告。
4. 检查暂存文件列表，拒绝 `.env`、数据库、缓存、日志、模型目录、`dist/`、截图和临时测试产物。
5. 在同一版本标签中发布双语 README、安全边界、第三方声明和本证据记录。
