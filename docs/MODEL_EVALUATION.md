# Model evaluation

Evaluation fixtures are useful for regression checks, not proof of production quality.

## Suggested measures

| Area | Metric |
| --- | --- |
| ASR | WER/CER, final-transcript latency, false endpoint rate |
| TTS | time to first audio, real-time factor, segment ordering, interruption cleanup |
| LLM/tools | first-token latency, tool success rate, cancellation latency, stale-result rejection |
| Memory | Recall@k, source attribution accuracy, correction/forget success |
| Avatar | model load time, frame time, idle/active FPS, lip-sync release latency |
| Vision | capture-to-result latency and request-scoped release |

Run offline fixtures and unit tests first. Hardware trials must record OS, CPU/GPU, audio device, provider, model, and power profile. A passing test suite does not certify microphone, speaker, GPU, or model quality.
