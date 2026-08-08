import type { PcmPlaybackDetail, TtsPlaybackDetail, TtsStopDetail } from './player'

export interface AudioPlaybackTarget {
  play: (audioUrl: string, detail?: TtsPlaybackDetail) => Promise<void> | void
  stop: (options?: TtsStopDetail) => void
  enqueue: (audioUrl: string, detail?: TtsPlaybackDetail) => void
  enqueuePcm: (detail: PcmPlaybackDetail) => void
}

export interface AudioEventHost {
  addEventListener: (type: string, listener: EventListener) => void
  removeEventListener: (type: string, listener: EventListener) => void
}

export class AudioPlayerEventBridge {
  private host: AudioEventHost | null = null

  private readonly handleLegacyPlay = (event: Event) => {
    const detail = (event as CustomEvent<TtsPlaybackDetail>).detail
    const audioUrl = detail?.audio_url
    if (!audioUrl) return
    void Promise.resolve(this.target.play(audioUrl, detail)).catch((error) => console.error(error))
  }

  private readonly handleStop = (event: Event) => {
    const detail = (event as CustomEvent<TtsStopDetail>).detail
    this.target.stop({
      interrupted: detail?.interrupted === true,
      petLipSyncHandled: detail?.petLipSyncHandled === true,
    })
  }

  private readonly handleUrl = (event: Event) => {
    const detail = (event as CustomEvent<TtsPlaybackDetail>).detail
    const audioUrl = detail?.audio_url
    if (audioUrl) this.target.enqueue(audioUrl, detail)
  }

  private readonly handlePcm = (event: Event) => {
    const detail = (event as CustomEvent<PcmPlaybackDetail>).detail
    if (detail?.audio instanceof Uint8Array) this.target.enqueuePcm(detail)
  }

  constructor(private readonly target: AudioPlaybackTarget) {}

  attach(host: AudioEventHost): void {
    if (this.host === host) return
    this.detach()
    this.host = host
    host.addEventListener('pet:tts-play', this.handleLegacyPlay)
    host.addEventListener('pet:tts-stop', this.handleStop)
    host.addEventListener('pet:tts-play-url', this.handleUrl)
    host.addEventListener('pet:tts-play-pcm', this.handlePcm)
  }

  detach(host: AudioEventHost | null = this.host): void {
    if (!host) return
    host.removeEventListener('pet:tts-play', this.handleLegacyPlay)
    host.removeEventListener('pet:tts-stop', this.handleStop)
    host.removeEventListener('pet:tts-play-url', this.handleUrl)
    host.removeEventListener('pet:tts-play-pcm', this.handlePcm)
    if (this.host === host) this.host = null
  }
}
