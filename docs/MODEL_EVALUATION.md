# Model and runtime evaluation / 模型与运行时评估

fixture 和单元测试只能作为回归证据，不能证明生产质量。真实设备测量必须注明机器、服务商、模型、音频设备和电源配置。

Fixtures and unit tests are regression evidence, not proof of production quality. Real-device measurements must identify the machine, provider, model, audio device, and power profile.

The former fixture-based evaluation runner has been removed. Release evidence
now comes from the focused Electron/Python contract suites and real-device
qualification. Product metrics under `python/evals/product_metrics.py` remain
an opt-in runtime feature, not a synthetic quality score.

## Required measures / 必测指标

| Area | Measures |
| --- | --- |
| ASR | WER/CER, final transcript latency, partial stability, false endpoint rate |
| TTS | Time to first audio, real-time factor, segment ordering, interruption cleanup |
| LLM/tools | First-token latency, tool success rate, cancellation latency, stale-result rejection |
| Memory | Recall@k, source attribution, correction/forget success, false recall rate |
| Avatar | Model load time, frame time, idle/active FPS, lip-sync release latency |
| Vision | Capture-to-result latency, request-scoped release, consent expiry, redaction, persistence check |
| Proactive | Opportunity acceptance/rejection, quiet-hours compliance, duplicate suppression, user stop latency |
| Desktop actions | Capability availability by OS/session, permission latency, postcondition success, unknown-effect emergency stop |

## Evaluation order / 评估顺序

1. 运行文档和依赖检查。 / Run documentation and dependency checks.
2. 运行 Python 与 Electron 单元/契约测试。 / Run Python and Electron unit/contract tests.
3. 运行本地后端健康/就绪探针。 / Run a local backend health/readiness probe.
4. 在目标硬件上运行真实服务商、麦克风、扬声器、GPU 和虚拟形象测试。 / Run real provider, microphone, speaker, GPU, and avatar tests on target hardware.

For a code-to-runtime trace, correlate the measurement with
`turn_store.py`, `agent_trace_store.py`, `companion_events.py`,
`realtimeVoiceEventBridge.ts`, `companionJobProjection.ts`, and the relevant
provider/adapter implementation. Do not report a feature as production-ready
from a fixture result alone.

## Reporting / 报告

只保存经过脱敏的报告。报告应包含 commit、操作系统、运行时版本、服务商/模型标识、配置档案和测量结果。不得包含 API 密钥、Backend Token、个人对话或屏幕截图。

Store only redacted reports. Include commit, OS, runtime versions, provider/model identifiers, configuration profile, and measured results. Never include API keys, backend tokens, personal conversations, or captured screens.

The concrete voice provenance contract, latency/recovery matrix, and current
supported-platform qualification status are maintained in
[`VOICE_QUALIFICATION.md`](VOICE_QUALIFICATION.md). A synthetic fixture result
must never be relabeled as real-device evidence.
