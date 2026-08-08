import type { RealtimeVoiceEventMap } from '@/audio/realtime-voice'

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
