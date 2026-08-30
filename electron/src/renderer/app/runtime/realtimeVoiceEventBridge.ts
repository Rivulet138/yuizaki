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
  stage: 'connect' | 'asr_final' | 'first_token' | 'first_audio' | 'interruption' | 'interrupt_ack' | 'playback_recovery'
  latencyMs: number
  ok: boolean
  recovered?: boolean
  recoveryLatencyMs?: number
  playbackUnderruns?: number
  /** Run identity captured when the provider event was observed. */
  runId?: string
  /** Voice session identity captured with the diagnostic event. */
  scope?: RealtimeVoiceScope
}

export interface RealtimeVoiceComfortSample {
  signal: RealtimeVoiceEventMap['comfort-signal']['signal']
  source: RealtimeVoiceEventMap['comfort-signal']['source']
  confidence: number
  durationMs?: number
}

export type RealtimeVoiceDiagnosticReporter = (sample: RealtimeVoiceDiagnosticSample) => void

export class RealtimeVoiceEventBridge {
  private readonly unsubscribers: Array<() => void> = []
  private readonly listeners = new Map<string, Set<(payload: unknown) => void>>()
  private readonly eventUnsubscribers = new Map<string, () => void>()
  private readonly diagnosticSamples: RealtimeVoiceDiagnosticSample[] = []
  private readonly comfortSamples: RealtimeVoiceComfortSample[] = []
  private detached = false
  private diagnosticRunId: string | null = null
  private static readonly maxDiagnosticSamples = 128

  constructor(
    private readonly source: RealtimeVoiceEventSource,
    private readonly reportDiagnostic?: RealtimeVoiceDiagnosticReporter,
  ) {}

  /** Associate subsequent diagnostics with the active renderer measurement run. */
  setDiagnosticRunId(runId: string | null): void {
    const nextRunId = runId?.trim() || null
    if (nextRunId !== this.diagnosticRunId) {
      // A run is the unit of comfort qualification. Keep the renderer's
      // bounded snapshot aligned with the backend, which clears samples when
      // begin_run() rotates the measurement identity.
      this.diagnosticSamples.splice(0)
      this.comfortSamples.splice(0)
    }
    this.diagnosticRunId = nextRunId
  }

  listen<K extends keyof RealtimeVoiceEventMap>(event: K, listener: (payload: RealtimeVoiceEventMap[K]) => void): void {
    const key = String(event)
    const eventListeners = this.listeners.get(key) ?? new Set<(payload: unknown) => void>()
    const callback = listener as (payload: unknown) => void
    eventListeners.add(callback)
    this.listeners.set(key, eventListeners)
    if (!this.eventUnsubscribers.has(key)) {
      const unsubscribe = this.source.on(event, (payload) => {
        if (this.detached) return
        this.recordDiagnostic(key, payload)
        for (const currentListener of eventListeners) currentListener(payload)
      })
      this.eventUnsubscribers.set(key, unsubscribe)
    }
    this.unsubscribers.push(() => {
      eventListeners.delete(callback)
      if (eventListeners.size > 0) return
      this.listeners.delete(key)
      const unsubscribe = this.eventUnsubscribers.get(key)
      this.eventUnsubscribers.delete(key)
      unsubscribe?.()
    })
  }

  getDiagnosticSnapshot(): {
    sampleCount: number
    stages: Record<string, { count: number; p50Ms: number | null; p95Ms: number | null; errorCount: number; recoveryAttempts: number; recoverySuccesses: number; recoveryP50Ms: number | null; recoveryP95Ms: number | null; playbackUnderruns: number }>
    comfortSignals: {
      sampleCount: number
      bySignal: Record<string, number>
      bySource: Record<string, number>
      confidenceP50: number | null
      confidenceP95: number | null
      durationP50Ms: number | null
      durationP95Ms: number | null
    }
  } {
    const grouped = new Map<string, RealtimeVoiceDiagnosticSample[]>()
    for (const sample of this.diagnosticSamples) grouped.set(sample.stage, [...(grouped.get(sample.stage) ?? []), sample])
    const percentile = (values: number[], fraction: number): number | null => {
      if (!values.length) return null
      const sorted = [...values].sort((a, b) => a - b)
      return Math.round(sorted[Math.min(sorted.length - 1, Math.floor((sorted.length - 1) * fraction))] * 100) / 100
    }
    const comfortPercentile = (values: number[], fraction: number): number | null => {
      if (!values.length) return null
      const sorted = [...values].sort((a, b) => a - b)
      return Math.round(sorted[Math.min(sorted.length - 1, Math.floor((sorted.length - 1) * fraction))] * 100) / 100
    }
    const bySignal: Record<string, number> = {}
    const bySource: Record<string, number> = {}
    for (const sample of this.comfortSamples) {
      bySignal[sample.signal] = (bySignal[sample.signal] ?? 0) + 1
      bySource[sample.source] = (bySource[sample.source] ?? 0) + 1
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
      comfortSignals: {
        sampleCount: this.comfortSamples.length,
        bySignal,
        bySource,
        confidenceP50: comfortPercentile(this.comfortSamples.map((sample) => sample.confidence), 0.5),
        confidenceP95: comfortPercentile(this.comfortSamples.map((sample) => sample.confidence), 0.95),
        durationP50Ms: comfortPercentile(this.comfortSamples.flatMap((sample) => sample.durationMs === undefined ? [] : [sample.durationMs]), 0.5),
        durationP95Ms: comfortPercentile(this.comfortSamples.flatMap((sample) => sample.durationMs === undefined ? [] : [sample.durationMs]), 0.95),
      },
    }
  }

  private recordDiagnostic(event: string, payload: unknown): void {
    if (event === 'comfort-signal') {
      this.recordComfortSignal(payload)
      return
    }
    const stageByEvent: Record<string, RealtimeVoiceDiagnosticSample['stage']> = {
      connect: 'connect',
      'transcript-stable': 'asr_final',
      'response-start': 'first_token',
      'playback-start': 'first_audio',
      'playback-stop': 'interruption',
      'interrupt-ack': 'interrupt_ack',
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
    const scope = this.readScope(payload)
    this.diagnosticSamples.push({
      stage,
      latencyMs,
      ok,
      ...(this.diagnosticRunId ? { runId: this.diagnosticRunId } : {}),
      ...(scope ? { scope } : {}),
      ...(typeof typed.recovered === 'boolean' ? { recovered: typed.recovered } : {}),
      ...(recoveryLatencyMs === undefined ? {} : { recoveryLatencyMs }),
      ...(playbackUnderruns === undefined ? {} : { playbackUnderruns }),
    })
    if (this.diagnosticSamples.length > RealtimeVoiceEventBridge.maxDiagnosticSamples) this.diagnosticSamples.shift()
    try {
      this.reportDiagnostic?.(this.diagnosticSamples[this.diagnosticSamples.length - 1])
    } catch (error) {
      // Diagnostic persistence must never break the realtime voice event path.
      console.warn('[VoiceBridge] diagnostic reporter failed:', error)
    }
  }

  private readScope(payload: unknown): RealtimeVoiceScope | undefined {
    if (!payload || typeof payload !== 'object') return undefined
    const value = payload as Partial<RealtimeVoiceScope>
    if (
      typeof value.workspaceId !== 'string'
      || typeof value.sessionId !== 'string'
      || !Number.isInteger(value.interruptionEpoch)
    ) return undefined
    return {
      workspaceId: value.workspaceId,
      sessionId: value.sessionId,
      interruptionEpoch: value.interruptionEpoch,
      ...(typeof value.turnId === 'string' ? { turnId: value.turnId } : {}),
      ...(typeof value.generationId === 'string' ? { generationId: value.generationId } : {}),
      ...(typeof value.requestId === 'string' ? { requestId: value.requestId } : {}),
      ...(Number.isInteger(value.sequence) ? { sequence: value.sequence } : {}),
      ...(value.envelopeVersion === 1 ? { envelopeVersion: 1 } : {}),
    }
  }

  private recordComfortSignal(payload: unknown): void {
    if (!payload || typeof payload !== 'object') return
    const typed = payload as {
      signal?: unknown
      source?: unknown
      confidence?: unknown
      durationMs?: unknown
    }
    const signal = typed.signal
    const source = typed.source
    const confidence = Number(typed.confidence)
    const durationMs = typed.durationMs === undefined ? undefined : Number(typed.durationMs)
    if (signal !== 'hesitation' && signal !== 'backchannel' && signal !== 'background_speech') return
    if (source !== 'provider_vad' && source !== 'local_vad' && source !== 'classifier') return
    if (!Number.isFinite(confidence) || confidence < 0 || confidence > 1) return
    if (durationMs !== undefined && (!Number.isFinite(durationMs) || durationMs < 0 || durationMs > 120_000)) return
    this.comfortSamples.push({
      signal,
      source,
      confidence,
      ...(durationMs === undefined ? {} : { durationMs }),
    })
    if (this.comfortSamples.length > RealtimeVoiceEventBridge.maxDiagnosticSamples) this.comfortSamples.shift()
  }

  detach(): void {
    this.detached = true
    this.diagnosticRunId = null
    this.unsubscribers.splice(0).forEach((unsubscribe) => unsubscribe())
    this.listeners.clear()
    this.eventUnsubscribers.clear()
  }
}
