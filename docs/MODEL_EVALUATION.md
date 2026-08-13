# Model and runtime evaluation

Fixtures and unit tests are regression evidence, not proof of production quality. Real-device measurements must identify the machine, provider, model, audio device, and power profile.

## Required measures

| Area | Measures |
| --- | --- |
| ASR | WER/CER, final transcript latency, partial stability, false endpoint rate |
| TTS | Time to first audio, real-time factor, segment ordering, interruption cleanup |
| LLM/tools | First-token latency, tool success rate, cancellation latency, stale-result rejection |
| Memory | Recall@k, source attribution, correction/forget success, false recall rate |
| Avatar | Model load time, frame time, idle/active FPS, lip-sync release latency |
| Vision | Capture-to-result latency, request-scoped release, persistence check |

## Evaluation order

1. Run documentation and dependency checks.
2. Run Python and Electron unit/contract tests.
3. Run offline fixture evaluation with `python -m evals`.
4. Run a local backend health/readiness probe.
5. Run real provider, microphone, speaker, GPU, and avatar tests on target hardware.

## Reporting

Store only redacted reports. Include commit, OS, runtime versions, provider/model identifiers, configuration profile, and measured results. Never include API keys, control tokens, personal conversations, or captured screens.
