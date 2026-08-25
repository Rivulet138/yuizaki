# Reference index / 参考资料索引

This file is the canonical index for external research and comparable projects
used by Yuizaki product, memory, interaction, computer-use, and release
decisions. It is intentionally shorter than an implementation document: durable
design contracts belong in `DESIGN.md`, `docs/LONG_TERM_MEMORY.md`,
`docs/NATIVE_DESKTOP_ACTIONS.md`, and `SECURITY.md`.

本文是 Yuizaki 产品、记忆、交互、电脑操作和发布决策所使用的外部资料唯一索引。
实现约束仍以 `DESIGN.md`、`docs/LONG_TERM_MEMORY.md`、
`docs/NATIVE_DESKTOP_ACTIONS.md` 和 `SECURITY.md` 为准。

## Evidence policy / 证据等级

| Level | Meaning |
| --- | --- |
| E0 | Current Yuizaki source code, tests, lock files, or reproducible local measurements. This is the only level that proves a repository capability. |
| E1 | Official upstream documentation or a released benchmark harness. Useful for interface and test-shape design, not proof of Yuizaki quality. |
| E2 | Peer-reviewed paper, preprint, or first-party product/project description. Useful for hypotheses and comparative design. |
| E3 | Unreproduced claim, future-dated preprint, or external benchmark result. Track for research only; never present as a Yuizaki result. |

External sources do not replace E0 evidence. Any product claim should cite the
local file and test first, then use this index to explain why the design is
worth testing.

外部资料不能替代 E0 代码证据。产品结论必须先引用本地文件和测试，再使用本索引说明设计假设和待验证方向。

## Memory and agent references / 记忆与 Agent

| Source | Level | Relevant idea | Yuizaki implication |
| --- | --- | --- | --- |
| [LoCoMo](https://arxiv.org/abs/2402.17753) and [official repository](https://github.com/snap-research/locomo) | E1/E2 | Long conversations with temporal, causal, multi-hop, summarization, and multimodal cases. | Shape golden cases in `python/evals`; do not copy external scores as product targets. |
| [LongMemEval](https://arxiv.org/abs/2410.10813) and [repository](https://github.com/xiaowu0162/LongMemEval) | E1/E2 | Extraction, multi-session reasoning, temporal updates, and abstention. | Extend memory tests for stale facts, cross-session recall, and no-evidence abstention. |
| [LongMemEval-V2](https://arxiv.org/abs/2605.12493) | E3 until locally reproduced | Evidence retrieval, answer quality, and latency over long agent trajectories. | Record retrieval quality, latency, and token cost together in memory traces. |
| [MemoryAgentBench](https://github.com/HUST-AI-HYZ/MemoryAgentBench) | E1/E2 | Incremental retrieval, fact consolidation, and long-horizon tasks. | Add continuous-update and conflict cases to `python/evals`. |
| [A-MEM](https://arxiv.org/abs/2502.12110) | E2 | Structured notes, tags, and evolving associations. | Enrich optional metadata while keeping source provenance immutable. |
| [Mem0](https://arxiv.org/abs/2504.19413) and [memory operations](https://docs.mem0.ai/core-concepts/memory-operations) | E1/E2 | Extract, consolidate, retrieve, update, and delete as one lifecycle. | Keep the Python routes and renderer client aligned around explicit lifecycle operations. |
| [Zep/Graphiti](https://arxiv.org/abs/2501.13956) and [Graphiti repository](https://github.com/getzep/graphiti) | E1/E2 | Temporal relationships and invalidation. | Use existing `valid_from`/`valid_to`/`supersedes` before adding a graph store. |
| [MemGPT](https://arxiv.org/abs/2310.08560) and [Letta memory blocks](https://docs.letta.com/v1-sdk/memory/memory-blocks/) | E1/E2 | Small explicit core context plus archival memory. | Keep persona/profile/relationship memory bounded and reviewable; do not inject the full library. |
| [MemoryOS](https://arxiv.org/abs/2506.06326) and [repository](https://github.com/MemTensor/MemOS) | E2 | Short-, mid-, and long-term memory layers. | Preserve explicit local layers and measure consolidation before adopting another framework. |
| [LangGraph memory](https://docs.langchain.com/oss/python/langgraph/add-memory) and [repository](https://github.com/langchain-ai/langgraph) | E1 | Thread checkpoints separated from cross-thread stores. | Keep session, workspace, and global scopes distinct in `python/modules/memory`. |

### Emerging 2026 research / 2026 年前后新资料

These papers are research watch items, not release evidence. Their URLs and
claims should be rechecked before citing them in a public benchmark.

| Source | Design signal to test locally |
| --- | --- |
| [RippleMem](https://arxiv.org/abs/2608.13334) | Event-centred associative expansion for distributed multi-hop evidence. |
| [LycheeMemory V2](https://arxiv.org/abs/2608.12990) | Segment-level consolidation may reduce eager per-turn construction cost. |
| [ReFind](https://arxiv.org/abs/2608.12888) | Agent-controlled lexical search can complement semantic retrieval. |
| [Governed Persistent Memory](https://arxiv.org/abs/2608.12476) | Source-bound bitemporal state and fail-closed recallability barriers. |
| [Total Recall at What Cost?](https://arxiv.org/abs/2608.11879) | Accuracy, latency, and serving cost must be reported independently. |
| [TEPA](https://arxiv.org/abs/2608.07429) | Retained but revoked evidence should not support active claims. |
| [ChronoMem](https://arxiv.org/abs/2607.27773) | Versioned memory and append-only semantic rollback. |
| [MemTxn](https://arxiv.org/abs/2607.27834) | Provenance-preserving update transactions and recovery. |
| [MemSecBench](https://arxiv.org/abs/2607.27080) | Memory security must cover write, execute, forget, and repair. |
| [Memory Provenance Laundering](https://arxiv.org/abs/2607.29167) | Derived summaries must not upgrade untrusted source authority. |
| [MemLens](https://arxiv.org/abs/2607.25992) | Lifecycle analytics should expose value, quality, latency, and token use. |

## Voice, embodiment, and interaction / 语音、具身与交互

| Source | Level | Yuizaki implication |
| --- | --- | --- |
| [CHI 2024: Spoken dialogue breakdown repair](https://doi.org/10.1145/3640794.3665558) | E2 | Make interruption and recovery first-class states. |
| [Information 2024: Voice UI usability](https://doi.org/10.3390/info15090579) | E2 | Keep active, failure, and exit states visible near the composer. |
| [CHI 2024: Public perceptions of conversational agents](https://doi.org/10.1145/3613904.3642840) | E2 | Explain agent state without claiming animation is a human feeling. |
| [Applied Sciences 2025: Emotional embodied conversational agent](https://doi.org/10.3390/app15084256) | E2 | Use a small set of high-level embodiment states. |
| [Frontiers 2025: Building for speech](https://doi.org/10.3389/frobt.2024.1356477) | E2 | Expose playback, latency, and barge-in affordances. |
| [PNAS 2025: Anthropomorphic conversational agents](https://doi.org/10.1073/pnas.2415898122) | E2 | Keep pet linkage optional and avoid default emotional dependence. |
| [Frontiers 2025: Uncanny valley in embodied agents](https://doi.org/10.3389/fpsyg.2025.1625984) | E2 | Prefer restrained, intention-level animation and a predictable idle state. |
| [Full-duplex spoken dialogue management](https://doi.org/10.48550/arxiv.2502.14145) | E2 | Keep generation, audio, and interruption asynchronous with identity checks. |

## Package trust and release / 包信任与发布

| Source | Level | Yuizaki implication |
| --- | --- | --- |
| [The Update Framework security model](https://theupdateframework.io/security/) and [specification](https://theupdateframework.github.io/specification/latest/) | E1 | Separate root trust from rotating targets, reject rollback/downgrade metadata, and keep recovery fail-closed. |
| [Sigstore documentation](https://docs.sigstore.dev/) | E1 | Treat signing identity, verification, and transparency evidence as separate release inputs; do not equate a local signature check with publisher identity. |

## Privacy and product measurement / 隐私与产品指标

| Source | Level | Yuizaki implication |
| --- | --- | --- |
| [NIST Privacy Framework](https://www.nist.gov/privacy-framework) | E1 | Treat consent, data minimization, retention, and deletion as lifecycle controls rather than a transport checkbox. |
| [EU GDPR, Articles 7 and 17](https://eur-lex.europa.eu/eli/reg/2016/679/oj) | E1 | Keep consent explicit and revocable, and design deletion propagation as a first-class requirement for any remote event sink. |
| [IETF HTTPAPI Idempotency-Key draft](https://datatracker.ietf.org/doc/draft-ietf-httpapi-idempotency-key-header/) | E1 | Use a stable request identity for retryable writes, but require an application-level receipt that confirms the exact batch key and count before marking local delivery complete. |
| [Mixpanel retention report](https://docs.mixpanel.com/docs/reports/retention) and [Amplitude retention analysis](https://amplitude.com/docs/analytics/charts/retention-analysis/retention-analysis-build) | E1 | Retention is cohort- and interval-based; keep the observation cutoff explicit and exclude users whose target interval has not elapsed from the D7 denominator. |

## Computer use and safety / 电脑操作与安全

| Source | Level | Yuizaki implication |
| --- | --- | --- |
| [OpenAI Computer-Using Agent](https://openai.com/index/computer-using-agent/) | E1/E2 | Couple screenshots, actions, confirmation, and post-action evidence. |
| [Anthropic Computer Use](https://docs.anthropic.com/en/docs/agents-and-tools/computer-use) | E1 | Treat screen/tool output as untrusted; isolate risky actions and require human confirmation. |

The local security contract is in `docs/NATIVE_DESKTOP_ACTIONS.md` and
`SECURITY.md`; this table is not a substitute for those contracts.

## Comparable products and projects / 同类产品与项目

These are comparison references for information architecture and feature
boundaries, not runtime dependencies:

- [AIRI](https://github.com/moeru-ai/airi): desktop embodiment, voice, and provider separation.
- [Open WebUI](https://github.com/open-webui/open-webui): task-first chat with secondary diagnostics.
- [SillyTavern](https://github.com/SillyTavern/SillyTavern): explicit sessions and provider controls.
- [Warashi](https://github.com/inni918/warashi): compact companion interaction loop.
- [LyraMate](https://github.com/andreadx95/LyraMate): bounded desktop-companion controls.
- [Jan](https://github.com/janhq/jan): download-first installation, requirements, troubleshooting, and contribution paths.
- [AnythingLLM](https://github.com/Mintplex-Labs/anything-llm): separates local-first product scope, self-hosting, development, telemetry, and privacy.
- [LobeHub](https://github.com/lobehub/lobehub): separates getting started, provider/plugin ecosystem, development, and community guidance.
- [Cherry Studio](https://github.com/CherryHQ/cherry-studio): desktop-AI repository structure with feature, contribution, security, and release entry points.

Repository organization was rechecked on 2026-08-26. These projects inform the
documentation shape only. Their activity, features, benchmark results, and
security claims are not evidence for Yuizaki.

以上项目结构于 2026-08-26 复核，仅用于确定文档信息架构；其活跃度、功能、
评测结果和安全声明均不能作为 Yuizaki 的实现证据。

## Tracked upstream snapshots / 跟踪的上游版本

Version snapshots are context only; exact dependency and license truth remains
in `package-lock.json`, `python/requirements*.txt`, `resources.lock.json`, and
`THIRD_PARTY_NOTICES.md`.

- [Graphiti v0.29.3](https://github.com/getzep/graphiti/releases/tag/v0.29.3)
- [Mem0 ts-v3.1.6](https://github.com/mem0ai/mem0/releases/tag/ts-v3.1.6)
- [Letta 0.16.8](https://github.com/letta-ai/letta/releases/tag/0.16.8)
- [MemOS v2.0.30](https://github.com/MemTensor/MemOS/releases/tag/v2.0.30)
- [LangGraph 1.2.11](https://github.com/langchain-ai/langgraph/releases/tag/1.2.11)

## Local evidence entry points / 本地证据入口

- Product intent and UX contracts: [../PRODUCT.md](../PRODUCT.md), [../DESIGN.md](../DESIGN.md)
- Memory contract and evaluation shape: [LONG_TERM_MEMORY.md](LONG_TERM_MEMORY.md)
- Computer-use security boundary: [NATIVE_DESKTOP_ACTIONS.md](NATIVE_DESKTOP_ACTIONS.md), [../SECURITY.md](../SECURITY.md)
- Release, license, and redistribution gate: [RESEARCH_AND_RELEASE.md](RESEARCH_AND_RELEASE.md), [../THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)
- Automated checks: [../.github/workflows/ci.yml](../.github/workflows/ci.yml), [../electron/package.json](../electron/package.json), `python/tests`, `python/evals`
