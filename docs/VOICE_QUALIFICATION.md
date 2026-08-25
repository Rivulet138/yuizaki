# Voice device qualification / 语音设备资格验证

Voice fixture tests protect contracts; they do not establish device or provider
quality. A release may claim real-device voice qualification only from the
fail-closed report returned by
`modules.system.voice_diagnostics.VoiceDiagnostics.qualification_snapshot()`.

## Evidence contract

Each real-device run must use one immutable `VoiceEvidenceProvenance` value and
record all of the following. Missing or mixed provenance produces
`status: not_qualified` even when latency numbers look healthy.

Each measurement run must also use a unique `run_id`. Call
`VoiceDiagnostics.begin_run()` before collecting a new matrix; it clears prior
samples so stages cannot be assembled from different runs, workspaces, or
restarts. `qualification_snapshot(run_id=...)` only evaluates that run.
For asynchronous qualification callbacks, prefer `begin_measurement()` and
pass its opaque `VoiceMeasurementHandle` to `record()` or `record_elapsed()`;
the handle is invalidated when a new run begins and cannot be reused for a
later matrix. Legacy callbacks without a handle remain supported for runtime
telemetry, but qualification harnesses should use the handle path.

| Evidence group | Required fields |
| --- | --- |
| Host | machine label, OS/platform version, Electron/Python runtime versions, power profile |
| Provider | ASR/TTS/LLM provider and exact model/configuration identifier |
| Input | microphone label, sample rate, channel count, echo cancellation, noise suppression, VAD profile |
| Output | speaker/headset label |
| Measurements | stage sample count, success/error rate, latency P50/P95, playback underruns |
| Recovery | attempts, successes, success rate, recovery latency P50/P95 |

Do not include serial numbers, user names, API credentials, transcript content,
or raw audio in a report. Use stable lab labels for machines and devices.

## Required matrix

The default matrix requires at least five samples for every stage below. The
`interruption` and `playback_recovery` stages additionally require an explicit
recovered/not-recovered outcome and recovery latency for every sample.

| Stage | Start / stop boundary | Required result |
| --- | --- | --- |
| `asr_final` | end of user speech to accepted final transcript | latency P50/P95, errors |
| `first_token` | accepted final transcript to first LLM text token | latency P50/P95, errors |
| `first_audio` | response accepted by TTS to first audible frame | latency P50/P95, errors |
| `interruption` | barge-in accepted to audible playback stopped | latency P50/P95 and recovery fields |
| `playback_recovery` | induced underrun/device loss to resumed or failed terminal state | latency P50/P95, underruns and recovery fields |

Qualification means the report is complete and reproducible. It does not mean
the measurements meet a release performance threshold. Product release gates
must compare the qualified matrix with the budgets in
`.omx/ultragoal/brief.md`, including barge-in P95 below 250 ms.
The report also exposes `recovery_quality`; a complete matrix with zero
successful recoveries is still not a product-quality pass and must fail the
release recovery-success gate.

## Recording example

```python
from modules.system.voice_diagnostics import VoiceDiagnostics, VoiceEvidenceProvenance

provenance = VoiceEvidenceProvenance(
    kind="real_device",
    machine="win-lab-01",
    platform="Windows 11 24H2",
    runtime="Electron 38 / Python 3.12",
    provider="configured-provider",
    model="exact-model-or-config-id",
    input_device="USB microphone A",
    output_device="USB headset A",
    power_profile="balanced/ac",
    sample_rate_hz=48_000,
    channel_count=1,
    echo_cancellation=True,
    noise_suppression=True,
    vad_profile="default-voice",
)

diagnostics = VoiceDiagnostics()
handle = diagnostics.begin_measurement("win-lab-2026-08-23-a")
diagnostics.record("asr_final", 420, provenance=provenance, handle=handle)
diagnostics.record(
    "interruption",
    180,
    provenance=provenance,
    recovered=True,
    recovery_latency_ms=210,
    handle=handle,
)
report = diagnostics.qualification_snapshot(handle=handle)
```

Incomplete examples deliberately remain `not_qualified`. The five-sample
release floor cannot be lowered by a caller; larger qualification runs may set
a higher `min_samples_per_stage` value.

## Redacted artifact persistence

`modules.system.voice_qualification_artifact.JsonVoiceQualificationArtifactStore`
is the local evidence boundary for saving a qualification snapshot. It accepts
only reports with `evidence_kind: real_device` and the required matrix,
provenance, recovery, gap, and claim fields. Before writing, it rejects
transcript, prompt, raw-audio, credential, token, password, and binary fields;
the file is written through a temporary file, `fsync`, and atomic replace.
Reads validate the same shape and fail closed on corruption. This makes a
redacted lab artifact reproducible without turning a synthetic snapshot into a
device qualification claim. A `status: qualified` report additionally requires
an explicitly injected `attestation_verifier` supplied by a release runner;
without that external verifier, both write and read fail closed. The verifier
is an authority boundary, not a local fixture: the repository does not provide
the hardware attestation or publisher identity.

`modules.system.voice_release_runner.VoiceQualificationReleaseRunner` is the
execution boundary for a release artifact. It evaluates the diagnostics run
directly, combines `qualification_snapshot()` with `release_gate()`, and
persists `not_qualified` reports without attestation. A report is persisted as
`qualified` only when both completeness and performance gates pass and the
artifact store's externally injected attestation verifier accepts it. The
runner does not accept caller-supplied measurements or snapshots, so a copied
fixture cannot be promoted through this path.

For CI and release review, `python -m modules.system.voice_release_runner`
provides an evidence-consumption CLI. `--artifact` reads an existing redacted
artifact and `--output` may persist the resulting report. The command never
constructs measurements from JSON and has no publisher or hardware attestation
authority: missing, corrupt, synthetic, or unattested `qualified` input is
converted to a fresh `not_qualified` report and exits with status `2` (output
write failures exit `3`). A future release runner may inject the real external
verifier around `VoiceQualificationReleaseRunner`; the CLI's non-zero result is
therefore an explicit gate rather than a local qualification claim.

## Repository qualification matrix

As of 2026-08-23, the repository contains synthetic contract tests but no
redacted, reproducible real-device voice report. The honest release matrix is:

| Target | Evidence present | Qualification | Blocking gap |
| --- | --- | --- | --- |
| Windows x86_64 | Synthetic fixtures only | `not_qualified` | target machine/provider/model/input/output/power provenance and five-stage measurements |
| Linux x86_64 (PipeWire/PulseAudio) | Synthetic fixtures only | `not_qualified` | target machine/provider/model/input/output/power provenance and five-stage measurements |
| macOS | Not a supported production target | `not_qualified` | platform support and complete real-device matrix |

Voice unavailability is an optional-capability degradation. The runtime
diagnostic snapshot reports `voice: degraded`, `text_chat: preserved`, and
`text_chat_blocked_by_voice: false`; an absent microphone, speaker, ASR, or TTS
provider must not block text chat.

The runtime composition in `modules.system.runtime_services` owns one scoped
`VoiceDiagnostics` instance and injects it into ASR plus every supported TTS
provider. Provider `status_snapshot()` values expose a projection of that same
authority, so release reports can be assembled without merging private stores.
The Python ASR transcriber and TTS clients record bounded execution samples at
final transcription, first audio, generation failure, and active-inference
interruption boundaries.
The shared LLM client records the first visible token at the same authority,
bound to the generation id and provider.

The Electron realtime bridge is a transport/renderer observation adapter. Its
bounded `connect`, transcript, response-start, playback-start, interruption,
and playback-recovery events are synthetic/diagnostic observations only; they
are not a second release-qualification authority and do not export turn text,
tokens, credentials, or device identifiers. A rejected `audioElement.play()`
currently records a failed terminal recovery observation. Until a real device
loss/underrun path produces explicit recovered and terminal-failure events on a
qualified lab matrix, `playback_recovery` and the Windows/Linux targets remain
`not_qualified` regardless of synthetic sample counts.

The release distinction is implemented by
`VoiceDiagnostics.release_gate()`. `qualification_snapshot()` answers whether
the evidence is complete and reproducible; `release_gate()` additionally checks
configured latency budgets (the default interruption P95 budget is 250 ms) and
the minimum recovery success rate. A complete five-sample matrix with zero
successful recoveries therefore remains a failed product gate.

## Verification references

- `python/modules/system/voice_diagnostics.py` defines the bounded store,
  provenance contract, percentiles, recovery metrics, and fail-closed matrix.
- `python/modules/system/voice_qualification_artifact.py` defines the redacted,
  atomic qualification artifact persistence boundary and external-attestation
  gate for qualified reports.
- `python/modules/system/voice_release_runner.py` defines the fail-closed
  qualification-plus-performance release runner.
- `python/tests/test_voice_diagnostics.py` proves fixture/real-device separation,
  incomplete and mixed provenance rejection, and text-chat degradation.
- `python/tests/test_voice_release_runner.py` proves incomplete, over-budget,
  attested, and unattested release outcomes.
- `python/tests/test_voice_release_cli.py` proves missing, corrupt, synthetic,
  and unattested artifacts remain `not_qualified` and that a valid
  non-qualified artifact can be round-tripped.
- `docs/MODEL_EVALUATION.md` defines the broader release evidence policy.
- `.omx/ultragoal/brief.md` defines the product latency and reliability budgets.
