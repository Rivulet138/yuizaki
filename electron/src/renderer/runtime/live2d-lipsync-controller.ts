import type * as PIXI from 'pixi.js'
import {
  normalizePetLipSyncProfile,
  type PetLipSyncProfile,
} from '../../shared/pet-control'
import type { Live2DCoreModel } from './live2d-core-model'

const clamp = (value: number, min: number, max: number): number => Math.max(min, Math.min(max, value))
const RELEASE_DURATION_MS = 200
const RELEASE_FRAME_MS = 16

export class Live2DLipSyncController {
  private ticker: ((ticker: PIXI.Ticker) => void) | null = null
  private audioElement: HTMLAudioElement | null = null
  private audioContext: AudioContext | null = null
  private analyser: AnalyserNode | null = null
  private buffer: Uint8Array | null = null
  private externalLevel: number | null = null
  private externalVisemeLevel: number | null = null
  private profile: PetLipSyncProfile = normalizePetLipSyncProfile()
  private parameterIds = ['ParamMouthOpenY']
  private mouthOpen = 0
  private unavailableParams = new Set<string>()
  private startGeneration = 0
  private readyCleanup: (() => void) | null = null
  private releaseTimer: number | null = null
  private releaseStartedAt = 0
  private releaseStartValue = 0

  constructor(
    private readonly app: PIXI.Application,
    private readonly getCoreModel: () => Live2DCoreModel | null,
    private readonly onEnded?: () => void,
  ) {}

  async start(audioUrl: string, onReady?: () => void): Promise<void> {
    this.stop()
    this.cancelRelease()
    const generation = this.startGeneration
    if (!audioUrl.trim()) {
      return
    }

    const audio = new Audio()
    audio.crossOrigin = 'anonymous'
    audio.preload = 'auto'
    let readyReported = false
    let readyFallbackTimer: number | null = null
    const cleanupReady = () => {
      audio.removeEventListener('loadstart', reportReady)
      if (readyFallbackTimer !== null) {
        window.clearTimeout(readyFallbackTimer)
        readyFallbackTimer = null
      }
      if (this.readyCleanup === cleanupReady) {
        this.readyCleanup = null
      }
    }
    const reportReady = () => {
      if (readyReported) return
      readyReported = true
      cleanupReady()
      onReady?.()
    }
    this.readyCleanup = cleanupReady
    audio.addEventListener('loadstart', reportReady, { once: true })
    audio.src = audioUrl
    audio.addEventListener('ended', this.handleAudioEnded, { once: true })
    audio.addEventListener('error', this.handleAudioError, { once: true })
    // Start the analyser request before any async AudioContext work. The panel
    // playback clock can be interrupted while the context is resuming.
    audio.load()
    readyFallbackTimer = window.setTimeout(reportReady, 120)

    const context = new AudioContext()
    const source = context.createMediaElementSource(audio)
    const analyser = context.createAnalyser()
    analyser.fftSize = 1024
    analyser.smoothingTimeConstant = 0.68
    source.connect(analyser)

    this.audioElement = audio
    this.audioContext = context
    this.analyser = analyser
    this.buffer = new Uint8Array(analyser.fftSize)
    this.mouthOpen = 0
    this.unavailableParams.clear()
    this.startTicker()

    if (context.state === 'suspended') {
      await context.resume()
    }

    if (generation !== this.startGeneration) {
      this.stopResources(audio, context)
      return
    }

    try {
      await audio.play()
    } catch (error) {
      if (generation !== this.startGeneration) return
      console.warn('[Live2DLipSync] failed to play analyser audio:', error)
      this.stop()
    }
  }

  configure(profile: Partial<PetLipSyncProfile> | undefined, parameterIds?: string[]): void {
    this.profile = normalizePetLipSyncProfile(profile)
    if (parameterIds) {
      this.parameterIds = [...new Set(parameterIds.filter((id) => id.trim()))]
    }
    this.unavailableParams.clear()
  }

  setExternalLevel(level: number): void {
    if (this.externalLevel === null) {
      this.stop()
      this.externalLevel = 0
      this.unavailableParams.clear()
      this.startTicker()
    }
    this.externalLevel = clamp(level, 0, 1)
    this.externalVisemeLevel = null
  }

  setExternalViseme(weight: number, active: boolean): void {
    if (active) {
      if (this.externalLevel !== null) this.stopExternal()
      if (!this.ticker) this.startTicker()
      this.externalVisemeLevel = clamp(weight, 0, 1)
      return
    }
    this.externalVisemeLevel = null
    this.stopTicker()
    this.cancelRelease()
    this.resetMouth(this.getCoreModel())
  }

  stopExternal(): void {
    if (this.externalLevel !== null) {
      this.stop()
      // External realtime level updates are already frame-bounded by the
      // caller; keep their explicit inactive transition immediate.
      this.cancelRelease()
      this.resetMouth(this.getCoreModel())
    }
  }

  stop(): void {
    this.startGeneration += 1
    const releaseValue = this.mouthOpen
    this.readyCleanup?.()
    this.readyCleanup = null
    this.stopTicker()
    const audio = this.audioElement
    if (audio) {
      audio.removeEventListener('ended', this.handleAudioEnded)
      audio.removeEventListener('error', this.handleAudioError)
      audio.pause()
      audio.src = ''
      this.audioElement = null
    }

    if (this.audioContext) {
      this.audioContext.close().catch((error) => {
        console.debug('[Live2DLipSync] audio context close failed:', error)
      })
      this.audioContext = null
    }

    this.analyser = null
    this.buffer = null
    this.externalLevel = null
    this.externalVisemeLevel = null
    const coreModel = this.getCoreModel()
    if (coreModel && releaseValue > 0.005) this.startRelease(coreModel, releaseValue)
    else this.resetMouth(coreModel)
  }

  private stopResources(audio: HTMLAudioElement, context: AudioContext): void {
    audio.removeEventListener('ended', this.handleAudioEnded)
    audio.removeEventListener('error', this.handleAudioError)
    audio.pause()
    audio.src = ''
    context.close().catch((error) => {
      console.debug('[Live2DLipSync] audio context close failed:', error)
    })
  }

  private startRelease(coreModel: Live2DCoreModel, value: number): void {
    this.cancelRelease()
    this.releaseStartedAt = performance.now()
    this.releaseStartValue = value
    const tick = () => {
      const elapsed = Math.max(0, performance.now() - this.releaseStartedAt)
      const progress = clamp(elapsed / RELEASE_DURATION_MS, 0, 1)
      const remaining = this.releaseStartValue * (1 - progress) * (1 - progress)
      this.mouthOpen = remaining
      for (const parameterId of this.parameterIds) this.setParameter(coreModel, parameterId, remaining, 1)
      this.setParameter(coreModel, 'ParamMouthForm', 0.18 + remaining * 0.34, 0.35)
      if (progress >= 1) {
        this.cancelRelease()
        this.resetMouth(coreModel)
      }
    }
    tick()
    this.releaseTimer = window.setInterval(tick, RELEASE_FRAME_MS)
  }

  private cancelRelease(): void {
    if (this.releaseTimer !== null) {
      window.clearInterval(this.releaseTimer)
      this.releaseTimer = null
    }
  }

  private resetMouth(coreModel: Live2DCoreModel | null): void {
    this.mouthOpen = 0
    if (!coreModel) return
    for (const parameterId of this.parameterIds) this.setParameter(coreModel, parameterId, 0, 1)
    this.setParameter(coreModel, 'ParamMouthForm', 0.18, 0.35)
  }

  private startTicker(): void {
    if (this.ticker) {
      return
    }

    this.ticker = () => this.tick()
    this.app.ticker.add(this.ticker)
  }

  private stopTicker(): void {
    if (this.ticker) {
      this.app.ticker.remove(this.ticker)
      this.ticker = null
    }
  }

  private tick(): void {
    const coreModel = this.getCoreModel()
    if (!coreModel) {
      return
    }

    let inputLevel: number
    if (this.externalLevel !== null) {
      inputLevel = this.externalLevel
    } else if (this.externalVisemeLevel !== null) {
      inputLevel = this.externalVisemeLevel
    } else {
      if (!this.analyser || !this.buffer) return
      this.analyser.getByteTimeDomainData(this.buffer)
      let sumSquares = 0
      for (const sample of this.buffer) {
        const normalized = (sample - 128) / 128
        sumSquares += normalized * normalized
      }

      inputLevel = Math.sqrt(sumSquares / this.buffer.length)
    }

    const target = inputLevel < this.profile.noiseGate
      ? 0
      : clamp(inputLevel * this.profile.gain, 0, this.profile.maxOpen)
    const smoothing = target > this.mouthOpen ? this.profile.attack : this.profile.release
    this.mouthOpen += (target - this.mouthOpen) * smoothing

    for (const parameterId of this.parameterIds) {
      this.setParameter(coreModel, parameterId, this.mouthOpen, 1)
    }
    this.setParameter(coreModel, 'ParamMouthForm', 0.18 + this.mouthOpen * 0.34, 0.35)
  }

  private readonly handleAudioEnded = (): void => {
    this.stop()
    this.onEnded?.()
  }

  private readonly handleAudioError = (): void => {
    this.stop()
    this.onEnded?.()
  }

  private setParameter(coreModel: Live2DCoreModel, parameterId: string, value: number, weight: number): void {
    if (this.unavailableParams.has(parameterId)) {
      return
    }

    try {
      coreModel.setParameterValueById(parameterId, value, weight)
    } catch (error) {
      this.unavailableParams.add(parameterId)
      console.debug(`[Live2DLipSync] parameter unavailable: ${parameterId}`, error)
    }
  }
}
