# Research, interaction decisions, and release review / 研究、交互决策与发布核验

Status: active release evidence, refreshed 2026-08-26.

This document records current repository evidence used for product decisions and the boundary between a source release and an end-user bundle. It is updated when capability, license, resource, or release-gate facts change.

本文持续记录产品决策所依据的仓库事实，以及源码发布包与用户二进制包之间的边界；能力、许可、资源或发布门槛发生变化时必须同步更新。

## Evidence used / 参考证据

The paper, standard, benchmark, upstream snapshot, and comparable-project list
is maintained once in [REFERENCES.md](REFERENCES.md). The interaction decisions carried
into this repository are: voice must be interruptible and recoverable; active
and failure states stay close to the composer; the pet expresses bounded
high-level intent; pet linkage remains optional; generation, audio, and
interruption use separate asynchronous identities.

论文、标准、评测集、上游版本和同类项目统一维护在 [REFERENCES.md](REFERENCES.md)。本仓库采用的交互结论是：语音可中断且可恢复；活动与失败状态靠近输入区；桌宠只表达有限的高层意图；桌宠联动默认可关闭；生成、音频和中断使用独立异步身份。

## Repository facts checked / 仓库实际核验

- `electron/src/renderer/domains/chat` contains the chat view, composer, playback bar, voice status, session rail, and chat domain state; `electron/src/renderer/audio` owns capture and playback; `electron/src/renderer/app/runtime` owns voice/companion event projection.
- `electron/src/renderer/app/composables/useVoiceConversationBridge.ts:256-375` implements realtime prewarm, push-to-talk, continuous mode, interruption, and fallback to the local audio pipeline.
- `python/modules/agent/runtime.py:85-119` composes default tools, MCP, policy, trace, scheduler, turn persistence, desktop actions, computer use, and activity frames.
- `python/modules/agent/tool_loop.py:125-251` enforces cancellation, iteration/tool budgets, permission receipts, untrusted tool output, unknown-effect handling, and terminal reasons.
- `python/modules/agent/perception.py:59-177` implements request-scoped, expiring, single-use perception consent; `python/socket_server.py:1249-1824` performs authorized visual capture/OCR/analysis.
- `python/modules/memory/pipeline.py:20-178` implements scoped/layered retrieval, lifecycle filtering, hybrid ranking, score components, and latency trace; `python/modules/memory/routes.py:893-1654` exposes memory maintenance, correction, review, forgetting, rollback, index, and query routes.
- `electron/src/renderer/domains/memory/views/MemoryPanel.vue` and its child components expose library, review, overview, quick capture, advanced query, maintenance, correction, and deletion workflows.
- `python/modules/agent/desktop_actions.py:187-202` provides Windows user32 and `:358-542` provides Linux X11 adapters; pure Wayland and unsupported platforms fail closed, and macOS has no adapter. This is a capability boundary, not a blanket cross-platform Computer Use claim.
- `python/audio_cache/`, `python/data/`, model directories, logs, Electron build output, screenshots, and test caches are ignored and are not release inputs.
- Automated evidence is defined by `electron/package.json:24-32`, `.github/workflows/ci.yml`, `electron/src/**/__tests__`, and `python/tests`; passing those checks still does not certify a particular microphone, speaker, GPU, provider, model, or avatar asset.

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

## Current GitHub packaging status / 当前 GitHub 打包状态

`.github/workflows/release-packages.yml` is a manually dispatched packaging
workflow. It builds a Windows NSIS installer and Linux AppImage/deb packages,
then uploads them as GitHub Actions artifacts. Its current `contents: read`
permission does not create a tag or GitHub Release and does not publish assets
automatically.

`.github/workflows/release-packages.yml` 当前只能手动触发。它构建 Windows
NSIS 安装器与 Linux AppImage/deb，并上传为 GitHub Actions artifacts；当前
`contents: read` 权限不会创建标签或 GitHub Release，也不会自动发布附件。

The root `YuizakiLauncher.exe` and `YuizakiLauncher` files are generated local
artifacts and are intentionally ignored by Git. Build them with
`npm run prepare:launcher` from `electron`, or obtain packaged artifacts from a
completed workflow run. Do not commit locally generated binaries to the source
tree.

根目录的 `YuizakiLauncher.exe` 与 `YuizakiLauncher` 是本地生成产物，按设计
不纳入 Git。可在 `electron` 目录运行 `npm run prepare:launcher` 生成，或从已完成
的工作流下载打包产物；不要把本地编译的二进制提交到源码树。
