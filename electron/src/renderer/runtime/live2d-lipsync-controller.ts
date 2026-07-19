import type * as PIXI from 'pixi.js'
import {
  normalizePetLipSyncProfile,
  type PetLipSyncProfile,
} from '../../shared/pet-control'
import type { Live2DCoreModel } from './live2d-core-model'

const clamp = (value: number, min: number, max: number): number => Math.max(min, Math.min(max, value))

export class Live2DLipSyncController {
  private ticker: ((ticker: PIXI.Ticker) => void) | null = null
  private audioElement: HTMLAudioElement | null = null
  private audioContext: AudioContext | null = null
  private analyser: AnalyserNode | null = null
  private buffer: Uint8Array | null = null
  private externalLevel: number | null = null
  private profile: PetLipSyncProfile = normalizePetLipSyncProfile()
  private parameterIds = ['ParamMouthOpenY']
  private mouthOpen = 0
  private unavailableParams = new Set<string>()

  constructor(
    private readonly app: PIXI.Application,
    private readonly getCoreModel: () => Live2DCoreModel | null,
    private readonly onEnded?: () => void,
  ) {}

  async start(audioUrl: string): Promise<void> {
    this.stop()
    if (!audioUrl.trim()) {
      return
    }

    const audio = new Audio(audioUrl)
    audio.crossOrigin = 'anonymous'
    audio.preload = 'auto'
    audio.addEventListener('ended', this.handleAudioEnded, { once: true })
    audio.addEventListener('error', this.handleAudioError, { once: true })

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

    try {
      await audio.play()
    } catch (error) {
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
  }

  stopExternal(): void {
    if (this.externalLevel !== null) {
      this.stop()
    }
  }

  stop(): void {
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
    this.mouthOpen = 0
    const coreModel = this.getCoreModel()
    if (coreModel) {
      for (const parameterId of this.parameterIds) {
        this.setParameter(coreModel, parameterId, 0, 1)
      }
    }
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
