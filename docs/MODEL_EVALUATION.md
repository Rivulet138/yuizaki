# Model and runtime evaluation / 模型与运行时评估

fixture 和单元测试只能作为回归证据，不能证明生产质量。真实设备测量必须注明机器、服务商、模型、音频设备和电源配置。

Fixtures and unit tests are regression evidence, not proof of production quality. Real-device measurements must identify the machine, provider, model, audio device, and power profile.

## Required measures / 必测指标

| Area | Measures |
| --- | --- |
| ASR | WER/CER, final transcript latency, partial stability, false endpoint rate |
| TTS | Time to first audio, real-time factor, segment ordering, interruption cleanup |
| LLM/tools | First-token latency, tool success rate, cancellation latency, stale-result rejection |
| Memory | Recall@k, source attribution, correction/forget success, false recall rate |
| Avatar | Model load time, frame time, idle/active FPS, lip-sync release latency |
| Vision | Capture-to-result latency, request-scoped release, persistence check |

## Evaluation order / 评估顺序

1. 运行文档和依赖检查。 / Run documentation and dependency checks.
2. 运行 Python 与 Electron 单元/契约测试。 / Run Python and Electron unit/contract tests.
3. 使用 `python -m evals` 运行离线 fixture 评估。 / Run offline fixture evaluation with `python -m evals`.
4. 运行本地后端健康/就绪探针。 / Run a local backend health/readiness probe.
5. 在目标硬件上运行真实服务商、麦克风、扬声器、GPU 和虚拟形象测试。 / Run real provider, microphone, speaker, GPU, and avatar tests on target hardware.

## Reporting / 报告

只保存经过脱敏的报告。报告应包含 commit、操作系统、运行时版本、服务商/模型标识、配置档案和测量结果。不得包含 API 密钥、控制令牌、个人对话或屏幕截图。

Store only redacted reports. Include commit, OS, runtime versions, provider/model identifiers, configuration profile, and measured results. Never include API keys, control tokens, personal conversations, or captured screens.
