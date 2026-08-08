import { type Ref, ref } from 'vue'
import type { PetSentenceEmotionCue, PetVisemeCue } from '../../shared/pet-control'
import { petControl } from '../utils/petControl'
import { resolveBackendUrl } from '../api/clients/http-client'
import { AudioPlayerEventBridge } from './playbackEventBridge'

export interface TtsPlaybackDetail {
  audio_url?: string
  text?: string
  sentenceEmotionCues?: PetSentenceEmotionCue[]
  petLinkEnabled?: boolean
  generationId?: string
  sequence?: number
  isFinal?: boolean
  durationMs?: number
  visemeCues?: PetVisemeCue[]
}

export interface PcmPlaybackDetail extends Omit<TtsPlaybackDetail, 'audio_url'> {
  audio: Uint8Array
  audioFormat: 'pcm_s16le'
  sampleRate: number
  channels: number
  sampleWidthBytes: 2
}

interface AudioStartedDetail extends TtsPlaybackDetail {
  audio_url: string
  durationMs?: number
}

export interface TtsStopDetail {
  interrupted?: boolean
  petLipSyncHandled?: boolean
}

const normalizePlaybackUrl = async (audioUrl: string): Promise<string> => {
  const trimmed = audioUrl.trim()
  if (!trimmed) return ''
  if (/^https?:\/\//i.test(trimmed)) return trimmed
  if (/^blob:/i.test(trimmed)) return trimmed
  if (/^data:audio\//i.test(trimmed)) return trimmed
  if (/^file:\/\//i.test(trimmed)) return ''
  return resolveBackendUrl(trimmed)
}

const writeAscii = (view: DataView, offset: number, value: string) => {
  for (let index = 0; index < value.length; index += 1) {
    view.setUint8(offset + index, value.charCodeAt(index))
  }
}

export interface PcmLipSyncEnvelope {
  frameDurationMs: number
  levels: number[]
}

const PCM_LIP_SYNC_FRAME_MS = 33
const URL_LIP_SYNC_START_TIMEOUT_MS = 500

export const buildPcmS16leEnvelope = (
  pcm: Uint8Array,
  sampleRate: number,
  channels: number,
  frameDurationMs = PCM_LIP_SYNC_FRAME_MS,
): PcmLipSyncEnvelope => {
  const safeRate = Math.max(8_000, Math.min(192_000, Math.round(sampleRate)))
  const safeChannels = Math.max(1, Math.min(2, Math.round(channels)))
  const safeFrameDurationMs = Math.max(16, Math.min(100, Math.round(frameDurationMs)))
  const sampleFrameCount = Math.floor(pcm.byteLength / (safeChannels * 2))
  const samplesPerEnvelopeFrame = Math.max(1, Math.round(safeRate * safeFrameDurationMs / 1_000))
  const view = new DataView(pcm.buffer, pcm.byteOffset, pcm.byteLength)
  const levels: number[] = []

  for (let frameStart = 0; frameStart < sampleFrameCount; frameStart += samplesPerEnvelopeFrame) {
    const frameEnd = Math.min(sampleFrameCount, frameStart + samplesPerEnvelopeFrame)
    let sumSquares = 0
    let sampleCount = 0
    for (let sampleFrame = frameStart; sampleFrame < frameEnd; sampleFrame += 1) {
      for (let channel = 0; channel < safeChannels; channel += 1) {
        const byteOffset = (sampleFrame * safeChannels + channel) * 2
        const normalized = view.getInt16(byteOffset, true) / 32_768
        sumSquares += normalized * normalized
        sampleCount += 1
      }
    }
    levels.push(sampleCount > 0 ? Math.min(1, Math.sqrt(sumSquares / sampleCount)) : 0)
  }

  return {
    frameDurationMs: safeFrameDurationMs,
    levels,
  }
}

export const pcmS16leToWavBlob = (pcm: Uint8Array, sampleRate: number, channels: number): Blob => {
  const safeRate = Math.max(8_000, Math.min(192_000, Math.round(sampleRate)))
  const safeChannels = Math.max(1, Math.min(2, Math.round(channels)))
  const header = new ArrayBuffer(44)
  const view = new DataView(header)
  const byteRate = safeRate * safeChannels * 2
  const blockAlign = safeChannels * 2

  writeAscii(view, 0, 'RIFF')
  view.setUint32(4, 36 + pcm.byteLength, true)
  writeAscii(view, 8, 'WAVE')
  writeAscii(view, 12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, safeChannels, true)
  view.setUint32(24, safeRate, true)
  view.setUint32(28, byteRate, true)
  view.setUint16(32, blockAlign, true)
  view.setUint16(34, 16, true)
  writeAscii(view, 36, 'data')
  view.setUint32(40, pcm.byteLength, true)

  const pcmCopy = new Uint8Array(pcm.byteLength)
  pcmCopy.set(pcm)
  return new Blob([header, pcmCopy.buffer], { type: 'audio/wav' })
}

type QueuedAudio = {
  audioUrl: string
  detail: Omit<TtsPlaybackDetail, 'audio_url'>
  ownedObjectUrl?: string
  lipSyncEnvelope?: PcmLipSyncEnvelope
}

type ActiveLipSyncMode = 'none' | 'url' | 'pcm-level'

export class AudioPlayer {
  private audioElement: HTMLAudioElement | null = null
  private isPlaying: Ref<boolean> = ref(false)
  private playbackToken = 0
  private currentPetLinkEnabled = true
  private playbackPending = false
  private queue: QueuedAudio[] = []
  private currentOwnedObjectUrl: string | null = null
  private activeLipSyncMode: ActiveLipSyncMode = 'none'
  private pcmLipSyncTimer: number | null = null
  private pcmLipSyncEnvelope: PcmLipSyncEnvelope | null = null
  private lastPcmLipSyncFrame = -1
  private pcmVisemeCues: PetVisemeCue[] = []
  private lastPcmVisemeKey: string | null = null
  private lipSyncAbortController: AbortController | null = null
  private segmentEndedHandler: (() => void) | null = null
  private segmentErrorHandler: (() => void) | null = null

  constructor() {
    this.audioElement = new Audio()
  }

  async play(audioUrl: string, detail: Omit<TtsPlaybackDetail, 'audio_url'> = {}): Promise<void> {
    this.clearQueuedAudio()
    this.releaseCurrentObjectUrl()
    const token = this.nextPlaybackToken()
    await this.startPlayback(audioUrl, detail, token)
  }

  enqueue(audioUrl: string, detail: Omit<TtsPlaybackDetail, 'audio_url'> = {}): void {
    this.enqueueInternal({ audioUrl, detail })
  }

  enqueuePcm(detail: PcmPlaybackDetail): void {
    if (detail.audioFormat !== 'pcm_s16le' || detail.sampleWidthBytes !== 2 || detail.audio.byteLength === 0) return
    const wavBlob = pcmS16leToWavBlob(detail.audio, detail.sampleRate, detail.channels)
    const lipSyncEnvelope = buildPcmS16leEnvelope(detail.audio, detail.sampleRate, detail.channels)
    const objectUrl = URL.createObjectURL(wavBlob)
    const durationMs = Math.round(detail.audio.byteLength / (detail.sampleRate * detail.channels * 2) * 1000)
    const { audio: _audio, audioFormat: _format, sampleRate: _rate, channels: _channels, sampleWidthBytes: _width, ...playbackDetail } = detail
    this.enqueueInternal({
      audioUrl: objectUrl,
      detail: { ...playbackDetail, durationMs },
      ownedObjectUrl: objectUrl,
      lipSyncEnvelope,
    })
  }

  private enqueueInternal(item: QueuedAudio): void {
    const { audioUrl } = item
    if (!audioUrl.trim()) return
    this.queue.push(item)
    if (!this.isPlaying.value && !this.playbackPending) {
      void this.playNextQueued()
    }
  }

  private async startPlayback(
    audioUrl: string,
    detail: Omit<TtsPlaybackDetail, 'audio_url'>,
    token: number,
    ownedObjectUrl?: string,
    lipSyncEnvelope?: PcmLipSyncEnvelope,
  ): Promise<boolean> {
    if (!this.audioElement) {
      if (ownedObjectUrl) URL.revokeObjectURL(ownedObjectUrl)
      return false
    }
    const playbackUrl = await normalizePlaybackUrl(audioUrl)
    if (!playbackUrl || token !== this.playbackToken) {
      if (ownedObjectUrl) URL.revokeObjectURL(ownedObjectUrl)
      return false
    }

    try {
      this.detachSegmentListeners()
      const endedHandler = () => {
        if (this.segmentEndedHandler !== endedHandler || token !== this.playbackToken) return
        this.segmentEndedHandler = null
        this.finishCurrentSegment()
      }
      const errorHandler = () => {
        if (this.segmentErrorHandler !== errorHandler || token !== this.playbackToken) return
        this.segmentErrorHandler = null
        this.finishCurrentSegment()
      }
      this.segmentEndedHandler = endedHandler
      this.segmentErrorHandler = errorHandler
      this.audioElement.addEventListener('ended', endedHandler)
      this.audioElement.addEventListener('error', errorHandler)
      this.currentOwnedObjectUrl = ownedObjectUrl ?? null
      this.audioElement.src = playbackUrl
      this.audioElement.load?.()
      this.isPlaying.value = true
      const petLinkEnabled = detail.petLinkEnabled !== false
      this.currentPetLinkEnabled = petLinkEnabled
      if (petLinkEnabled) {
        if (lipSyncEnvelope?.levels.length) {
          this.activeLipSyncMode = 'pcm-level'
          this.startPcmLipSync(lipSyncEnvelope, detail.visemeCues)
        } else {
          this.activeLipSyncMode = 'url'
          const controller = new AbortController()
          this.lipSyncAbortController = controller
          const lipSyncStart = petControl.startLipSync(playbackUrl, {
            source: 'automation',
            signal: controller.signal,
          })
          const timeoutMarker = Symbol('lip-sync-start-timeout')
          let timeoutId: number | null = null
          let timedOut = false
          try {
            const result = await Promise.race([
              lipSyncStart.then(() => undefined),
              new Promise<typeof timeoutMarker>((resolve) => {
                timeoutId = setTimeout(() => resolve(timeoutMarker), URL_LIP_SYNC_START_TIMEOUT_MS)
              }),
            ])
            if (result === timeoutMarker) {
              timedOut = true
              console.debug('[AudioPlayer] pet lip sync start timed out; continuing audio playback')
              void lipSyncStart
                .catch((error) => {
                  if (controller.signal.aborted || token !== this.playbackToken) return
                  console.debug('[AudioPlayer] failed to start pet lip sync:', error)
                })
                .finally(() => {
                  if (this.lipSyncAbortController === controller) {
                    this.lipSyncAbortController = null
                  }
                })
            }
          } catch (error) {
            if (token !== this.playbackToken || controller.signal.aborted) {
              return false
            }
            console.debug('[AudioPlayer] failed to start pet lip sync:', error)
          } finally {
            if (timeoutId !== null) {
              clearTimeout(timeoutId)
            }
            if (this.lipSyncAbortController === controller && !timedOut) {
              this.lipSyncAbortController = null
            }
          }
          if (token !== this.playbackToken) return false
        }
      }
      if (token !== this.playbackToken) return false

      // The analyzer request is primed before the media element starts. Do not
      // await HTMLAudioElement.play(): Chromium can leave that promise pending
      // while the media clock is already advancing, especially for short WAVs.
      // The started event describes our playback start boundary, while ended or
      // error events remain responsible for the lifecycle's terminal boundary.
      const playPromise = Promise.resolve(this.audioElement.play())
      void playPromise.catch((error) => {
        if (token !== this.playbackToken || !this.isPlaying.value) return
        console.debug('[AudioPlayer] media playback failed:', error)
        this.finishCurrentSegment()
      })
      const startedDetail: AudioStartedDetail = { audio_url: playbackUrl }
      if (detail.text) {
        startedDetail.text = detail.text
      }
      if (petLinkEnabled && detail.sentenceEmotionCues?.length) {
        startedDetail.sentenceEmotionCues = detail.sentenceEmotionCues
      }
      if (detail.durationMs && detail.durationMs > 0) {
        startedDetail.durationMs = Math.round(detail.durationMs)
      } else if (Number.isFinite(this.audioElement.duration) && this.audioElement.duration > 0) {
        startedDetail.durationMs = Math.round(this.audioElement.duration * 1000)
      }
      if (!petLinkEnabled) {
        startedDetail.petLinkEnabled = false
      }
      if (detail.generationId) startedDetail.generationId = detail.generationId
      if (detail.sequence !== undefined) startedDetail.sequence = detail.sequence
      if (detail.isFinal !== undefined) startedDetail.isFinal = detail.isFinal
      window.dispatchEvent(new CustomEvent('pet:audio-started', { detail: startedDetail }))
      return true
    } catch (err) {
      console.error('Failed to play audio:', err)
      this.detachSegmentListeners()
      this.isPlaying.value = false
      this.releaseCurrentObjectUrl()
      return false
    }
  }

  stop(options: TtsStopDetail = {}): void {
    this.clearQueuedAudio()
    this.playbackPending = false
    this.nextPlaybackToken()
    if (this.audioElement) {
      this.audioElement.pause()
      this.audioElement.currentTime = 0
    }
    this.finishPlayback(true, options, true)
  }

  getIsPlaying(): Ref<boolean> {
    return this.isPlaying
  }

  private nextPlaybackToken(): number {
    this.playbackToken += 1
    return this.playbackToken
  }

  private async playNextQueued(): Promise<void> {
    if (this.playbackPending || this.isPlaying.value) return
    this.playbackPending = true
    try {
      while (!this.isPlaying.value && this.queue.length > 0) {
        const next = this.queue.shift()
        if (!next) break
        const token = this.nextPlaybackToken()
        await this.startPlayback(next.audioUrl, next.detail, token, next.ownedObjectUrl, next.lipSyncEnvelope)
      }
      if (!this.isPlaying.value && this.queue.length === 0) {
        window.dispatchEvent(new CustomEvent('pet:audio-ended'))
      }
    } finally {
      this.playbackPending = false
    }
  }

  private finishCurrentSegment(): void {
    const hasNext = this.queue.length > 0
    this.finishPlayback(false, {}, !hasNext)
    if (hasNext) {
      void this.playNextQueued()
    }
  }

  private finishPlayback(force = false, options: TtsStopDetail = {}, emitEnded = true): void {
    if (!this.isPlaying.value && !force) return
    this.detachSegmentListeners()
    this.isPlaying.value = false
    this.lipSyncAbortController?.abort()
    this.lipSyncAbortController = null
    if (this.activeLipSyncMode === 'pcm-level') {
      this.stopPcmLipSync()
    } else if (
      this.activeLipSyncMode === 'url'
      && this.currentPetLinkEnabled
      && options.petLipSyncHandled !== true
    ) {
      const stopLipSync = options.interrupted === true
        ? petControl.stopLipSync({ interrupted: true })
        : petControl.stopLipSync()
      void stopLipSync.catch((error) => {
        console.debug('[AudioPlayer] failed to stop pet lip sync:', error)
      })
    }
    this.activeLipSyncMode = 'none'
    this.currentPetLinkEnabled = true
    this.releaseCurrentObjectUrl()
    if (emitEnded) {
      window.dispatchEvent(new CustomEvent('pet:audio-ended'))
    }
  }

  private clearQueuedAudio(): void {
    for (const item of this.queue) {
      if (item.ownedObjectUrl) URL.revokeObjectURL(item.ownedObjectUrl)
    }
    this.queue = []
  }

  private detachSegmentListeners(): void {
    if (!this.audioElement) return
    if (this.segmentEndedHandler) {
      this.audioElement.removeEventListener('ended', this.segmentEndedHandler)
      this.segmentEndedHandler = null
    }
    if (this.segmentErrorHandler) {
      this.audioElement.removeEventListener('error', this.segmentErrorHandler)
      this.segmentErrorHandler = null
    }
  }

  private releaseCurrentObjectUrl(): void {
    if (!this.currentOwnedObjectUrl) return
    URL.revokeObjectURL(this.currentOwnedObjectUrl)
    this.currentOwnedObjectUrl = null
  }

  private startPcmLipSync(envelope: PcmLipSyncEnvelope, visemeCues: PetVisemeCue[] = []): void {
    this.stopPcmLipSync(false)
    this.pcmLipSyncEnvelope = envelope
    this.pcmVisemeCues = [...visemeCues].sort((left, right) => left.offsetMs - right.offsetMs)
    this.lastPcmLipSyncFrame = -1
    this.lastPcmVisemeKey = null
    this.reportPcmLipSyncFrame()
    this.pcmLipSyncTimer = window.setInterval(() => {
      this.reportPcmLipSyncFrame()
    }, envelope.frameDurationMs)
  }

  private reportPcmLipSyncFrame(): void {
    if (!this.audioElement || !this.pcmLipSyncEnvelope) return
    const frameIndex = Math.min(
      this.pcmLipSyncEnvelope.levels.length - 1,
      Math.max(0, Math.floor(this.audioElement.currentTime * 1_000 / this.pcmLipSyncEnvelope.frameDurationMs)),
    )
    if (frameIndex !== this.lastPcmLipSyncFrame) {
      this.lastPcmLipSyncFrame = frameIndex
      window.petApi?.pet?.setTtsLipSync?.(this.pcmLipSyncEnvelope.levels[frameIndex] ?? 0, true)
    }
    this.reportPcmViseme(this.audioElement.currentTime * 1_000)
  }

  private stopPcmLipSync(reportInactive = true): void {
    if (this.pcmLipSyncTimer !== null) {
      window.clearInterval(this.pcmLipSyncTimer)
      this.pcmLipSyncTimer = null
    }
    this.pcmLipSyncEnvelope = null
    this.lastPcmLipSyncFrame = -1
    const hadVisemeTimeline = this.pcmVisemeCues.length > 0
    this.pcmVisemeCues = []
    this.lastPcmVisemeKey = null
    if (reportInactive) {
      window.petApi?.pet?.setTtsLipSync?.(0, false)
      if (hadVisemeTimeline) {
        window.petApi?.pet?.setTtsViseme?.('sil', 0, false)
      }
    }
  }

  private reportPcmViseme(playbackMs: number): void {
    if (this.pcmVisemeCues.length === 0) return
    let cueIndex = -1
    for (let index = 0; index < this.pcmVisemeCues.length; index += 1) {
      if ((this.pcmVisemeCues[index]?.offsetMs ?? Number.POSITIVE_INFINITY) > playbackMs) break
      cueIndex = index
    }
    const cue = cueIndex >= 0 ? this.pcmVisemeCues[cueIndex] : undefined
    const expired = cue?.durationMs !== undefined && playbackMs >= cue.offsetMs + cue.durationMs
    const viseme = !cue || expired ? 'sil' : cue.viseme
    const weight = !cue || expired ? 0 : cue.weight ?? 1
    const key = `${cueIndex}:${expired ? 'expired' : viseme}:${weight}`
    if (key === this.lastPcmVisemeKey) return
    this.lastPcmVisemeKey = key
    window.petApi?.pet?.setTtsViseme?.(viseme, weight, true)
  }
}

// 全局播放器实例
let globalPlayer: AudioPlayer | null = null

export function getAudioPlayer(): AudioPlayer {
  if (!globalPlayer) {
    globalPlayer = new AudioPlayer()
  }
  return globalPlayer
}

let globalEventBridge: AudioPlayerEventBridge | null = null
const GLOBAL_AUDIO_BRIDGE_KEY = '__yuizakiAudioPlaybackBridge'

export function getAudioPlayerEventBridge(): AudioPlayerEventBridge {
  if (!globalEventBridge) {
    globalEventBridge = new AudioPlayerEventBridge({
      play: (audioUrl, detail) => getAudioPlayer().play(audioUrl, detail),
      stop: (options) => getAudioPlayer().stop(options),
      enqueue: (audioUrl, detail) => getAudioPlayer().enqueue(audioUrl, detail),
      enqueuePcm: (detail) => getAudioPlayer().enqueuePcm(detail),
    })
  }
  return globalEventBridge
}

const attachGlobalAudioBridge = (): void => {
  if (typeof window === 'undefined') return

  const host = window as Window & {
    [GLOBAL_AUDIO_BRIDGE_KEY]?: AudioPlayerEventBridge
  }
  const bridge = getAudioPlayerEventBridge()

  // Module reloads can reuse the same window. Detach the previous bridge so
  // playback events are delivered to exactly one AudioPlayer instance.
  host[GLOBAL_AUDIO_BRIDGE_KEY]?.detach(window)
  bridge.attach(window)
  host[GLOBAL_AUDIO_BRIDGE_KEY] = bridge
}

// 监听 TTS 播放事件（兼容老的 WS 事件 + 新的 Socket.IO 事件）
if (typeof window !== 'undefined') {
  // 旧的 WS 路径：由 wsClient 触发 pet:tts-play / pet:tts-stop
  attachGlobalAudioBridge()


  // 新的 Socket.IO 路径：直接监听 tts:done 事件由 chatStore 中注册

}
