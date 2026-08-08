export interface VoiceEventHost {
  addEventListener: (type: string, listener: EventListener) => void
  removeEventListener: (type: string, listener: EventListener) => void
}

export interface VoiceShortcutHost {
  on: (event: string, handler: (...args: any[]) => void) => void
  off: (event: string, handler: (...args: any[]) => void) => void
}

export interface VoiceEventBridgeHandlers {
  onLlmControl: EventListener
  onAudioStarted: EventListener
  onAudioEnded: EventListener
  onTtsStop: EventListener
  onRealtimeInterrupt: EventListener
  onStartMic: () => void | Promise<void>
  onStopMic: () => void
  onToggleMic: () => void | Promise<void>
}

export class VoiceEventBridge {
  private eventHost: VoiceEventHost | null = null
  private shortcutHost: VoiceShortcutHost | null = null

  constructor(private readonly handlers: VoiceEventBridgeHandlers) {}

  attach(eventHost: VoiceEventHost, shortcutHost: VoiceShortcutHost): void {
    if (this.eventHost === eventHost && this.shortcutHost === shortcutHost) return
    this.detach()
    this.eventHost = eventHost
    this.shortcutHost = shortcutHost

    eventHost.addEventListener('pet:llm-control', this.handlers.onLlmControl)
    eventHost.addEventListener('pet:audio-started', this.handlers.onAudioStarted)
    eventHost.addEventListener('pet:audio-ended', this.handlers.onAudioEnded)
    eventHost.addEventListener('pet:tts-stop', this.handlers.onTtsStop)
    eventHost.addEventListener('pet:realtime-interrupt', this.handlers.onRealtimeInterrupt)

    shortcutHost.on('shortcut:start-mic', this.handlers.onStartMic)
    shortcutHost.on('shortcut:stop-mic', this.handlers.onStopMic)
    shortcutHost.on('shortcut:toggle-mic', this.handlers.onToggleMic)
  }

  detach(): void {
    if (this.eventHost) {
      this.eventHost.removeEventListener('pet:llm-control', this.handlers.onLlmControl)
      this.eventHost.removeEventListener('pet:audio-started', this.handlers.onAudioStarted)
      this.eventHost.removeEventListener('pet:audio-ended', this.handlers.onAudioEnded)
      this.eventHost.removeEventListener('pet:tts-stop', this.handlers.onTtsStop)
      this.eventHost.removeEventListener('pet:realtime-interrupt', this.handlers.onRealtimeInterrupt)
    }
    if (this.shortcutHost) {
      this.shortcutHost.off('shortcut:start-mic', this.handlers.onStartMic)
      this.shortcutHost.off('shortcut:stop-mic', this.handlers.onStopMic)
      this.shortcutHost.off('shortcut:toggle-mic', this.handlers.onToggleMic)
    }
    this.eventHost = null
    this.shortcutHost = null
  }
}
