import type { RealtimeVoiceEventMap, RealtimeVoiceScope } from '@/audio/realtime-voice'
import type { VoiceTurnEnvelope } from '@/../shared/agent'

export const matchesRealtimeVoiceScope = (event: RealtimeVoiceScope, current: RealtimeVoiceScope): boolean =>
  event.workspaceId === current.workspaceId
  && event.sessionId === current.sessionId
  && event.interruptionEpoch === current.interruptionEpoch
  && (!event.turnId || !current.turnId || event.turnId === current.turnId)

/** Strict identity gate for versioned turn completion events. */
export const matchesRealtimeVoiceTurnScope = (
  event: RealtimeVoiceScope,
  current: RealtimeVoiceScope,
): boolean => event.workspaceId === current.workspaceId
  && event.sessionId === current.sessionId
  && event.interruptionEpoch === current.interruptionEpoch
  && Boolean(event.turnId && current.turnId && event.turnId === current.turnId)
  && Boolean(event.generationId && current.generationId && event.generationId === current.generationId)
  && Boolean(event.requestId && current.requestId && event.requestId === current.requestId)

/** Accept legacy events, but reject versioned events from an older generation/sequence. */
export const acceptsRealtimeVoiceEnvelope = (
  event: RealtimeVoiceScope & Partial<VoiceTurnEnvelope>,
  current: RealtimeVoiceScope & Partial<VoiceTurnEnvelope>,
  lastSequence = -1,
): boolean => matchesRealtimeVoiceScope(event, current)
  && (!event.generationId || !current.generationId || event.generationId === current.generationId)
  && (event.sequence === undefined || event.sequence > lastSequence)

export interface RealtimeVoiceEventSource {
  on: <K extends keyof RealtimeVoiceEventMap>(event: K, listener: (payload: RealtimeVoiceEventMap[K]) => void) => () => void
}

export interface RealtimeVoiceDiagnosticSample {
  stage: 'connect' | 'asr_final' | 'first_token' | 'first_audio' | 'interruption' | 'playback_recovery'
  latencyMs: number
  ok: boolean
  recovered?: boolean
  recoveryLatencyMs?: number
  playbackUnderruns?: number
}

export class RealtimeVoiceEventBridge {
  private readonly unsubscribers: Array<() => void> = []
  private readonly diagnosticSamples: RealtimeVoiceDiagnosticSample[] = []
  private static readonly maxDiagnosticSamples = 128

  constructor(private readonly source: RealtimeVoiceEventSource) {}

  listen<K extends keyof RealtimeVoiceEventMap>(event: K, listener: (payload: RealtimeVoiceEventMap[K]) => void): void {
    this.unsubscribers.push(this.source.on(event, (payload) => {
      this.recordDiagnostic(event, payload)
      listener(payload)
    }))
  }

  getDiagnosticSnapshot(): { sampleCount: number; stages: Record<string, { count: number; p50Ms: number | null; p95Ms: number | null; errorCount: number; recoveryAttempts: number; recoverySuccesses: number; recoveryP50Ms: number | null; recoveryP95Ms: number | null; playbackUnderruns: number }> } {
    const grouped = new Map<string, RealtimeVoiceDiagnosticSample[]>()
    for (const sample of this.diagnosticSamples) grouped.set(sample.stage, [...(grouped.get(sample.stage) ?? []), sample])
    const percentile = (values: number[], fraction: number): number | null => {
      if (!values.length) return null
      const sorted = [...values].sort((a, b) => a - b)
      return Math.round(sorted[Math.min(sorted.length - 1, Math.floor((sorted.length - 1) * fraction))] * 100) / 100
    }
    return {
      sampleCount: this.diagnosticSamples.length,
      stages: Object.fromEntries([...grouped.entries()].map(([stage, samples]) => ({
        stage,
        value: {
          count: samples.length,
          p50Ms: percentile(samples.map((sample) => sample.latencyMs), 0.5),
          p95Ms: percentile(samples.map((sample) => sample.latencyMs), 0.95),
          errorCount: samples.filter((sample) => !sample.ok).length,
          recoveryAttempts: samples.filter((sample) => sample.recovered !== undefined).length,
          recoverySuccesses: samples.filter((sample) => sample.recovered === true).length,
          recoveryP50Ms: percentile(samples.flatMap((sample) => sample.recoveryLatencyMs === undefined ? [] : [sample.recoveryLatencyMs]), 0.5),
          recoveryP95Ms: percentile(samples.flatMap((sample) => sample.recoveryLatencyMs === undefined ? [] : [sample.recoveryLatencyMs]), 0.95),
          playbackUnderruns: samples.reduce((total, sample) => total + (sample.playbackUnderruns ?? 0), 0),
        },
      })).map(({ stage, value }) => [stage, value])),
    }
  }

  private recordDiagnostic(event: string, payload: unknown): void {
    const stageByEvent: Record<string, RealtimeVoiceDiagnosticSample['stage']> = {
      connect: 'connect',
      'transcript-stable': 'asr_final',
      'response-start': 'first_token',
      'playback-start': 'first_audio',
      'playback-stop': 'interruption',
      'playback-recovery': 'playback_recovery',
    }
    const stage = stageByEvent[event]
    if (!stage || !payload || typeof payload !== 'object' || !('elapsedMs' in payload)) return
    const typed = payload as {
      elapsedMs?: unknown
      ok?: unknown
      recovered?: unknown
      recoveryLatencyMs?: unknown
      playbackUnderruns?: unknown
    }
    const latencyMs = Number(typed.elapsedMs)
    if (!Number.isFinite(latencyMs) || latencyMs < 0) return
    const recoveryLatencyMs = typed.recoveryLatencyMs === undefined ? undefined : Number(typed.recoveryLatencyMs)
    const playbackUnderruns = typed.playbackUnderruns === undefined ? undefined : Number(typed.playbackUnderruns)
    if (recoveryLatencyMs !== undefined && (!Number.isFinite(recoveryLatencyMs) || recoveryLatencyMs < 0)) return
    if (playbackUnderruns !== undefined && (!Number.isInteger(playbackUnderruns) || playbackUnderruns < 0)) return
    const ok = stage === 'playback_recovery' ? typed.ok === true : typed.ok !== false
    this.diagnosticSamples.push({
      stage,
      latencyMs,
      ok,
      ...(typeof typed.recovered === 'boolean' ? { recovered: typed.recovered } : {}),
      ...(recoveryLatencyMs === undefined ? {} : { recoveryLatencyMs }),
      ...(playbackUnderruns === undefined ? {} : { playbackUnderruns }),
    })
    if (this.diagnosticSamples.length > RealtimeVoiceEventBridge.maxDiagnosticSamples) this.diagnosticSamples.shift()
  }

  detach(): void {
    this.unsubscribers.splice(0).forEach((unsubscribe) => unsubscribe())
  }
}
