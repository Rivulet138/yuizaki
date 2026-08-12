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

export class RealtimeVoiceEventBridge {
  private readonly unsubscribers: Array<() => void> = []

  constructor(private readonly source: RealtimeVoiceEventSource) {}

  listen<K extends keyof RealtimeVoiceEventMap>(event: K, listener: (payload: RealtimeVoiceEventMap[K]) => void): void {
    this.unsubscribers.push(this.source.on(event, listener))
  }

  detach(): void {
    this.unsubscribers.splice(0).forEach((unsubscribe) => unsubscribe())
  }
}
