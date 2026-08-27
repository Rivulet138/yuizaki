import { describe, expect, it, vi } from 'vitest'
import {
  AUDIO_SPEECH_RMS_THRESHOLD,
  hasSpeechEnergy,
  normalizeAudioProcessingSettings,
  enumerateAudioDevices,
  StreamingPcmNormalizer,
} from '../audio/audio-capture'

describe('audio capture normalization', () => {
  it('enumerates input and output endpoints without opening a device', async () => {
    const enumerateDevices = vi.fn().mockResolvedValue([
      { kind: 'audioinput', label: 'Mic' },
      { kind: 'audioinput', label: '' },
      { kind: 'audiooutput', label: 'Speakers' },
      { kind: 'videoinput', label: 'Camera' },
    ])
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { enumerateDevices },
    })

    await expect(enumerateAudioDevices()).resolves.toEqual({
      inputCount: 2,
      outputCount: 1,
      inputLabels: ['Mic'],
      outputLabels: ['Speakers'],
    })
    expect(enumerateDevices).toHaveBeenCalledOnce()
  })

  it('degrades to an empty inventory when endpoint enumeration is unavailable', async () => {
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: undefined })
    await expect(enumerateAudioDevices()).resolves.toEqual({
      inputCount: 0,
      outputCount: 0,
      inputLabels: [],
      outputLabels: [],
    })
  })

  it('reports the audio processing settings actually selected by the device', () => {
    expect(normalizeAudioProcessingSettings({
      echoCancellation: true,
      noiseSuppression: false,
      autoGainControl: true,
    })).toEqual({
      echoCancellation: true,
      noiseSuppression: false,
      autoGainControl: true,
    })
    expect(normalizeAudioProcessingSettings()).toEqual({
      echoCancellation: null,
      noiseSuppression: null,
      autoGainControl: null,
    })
  })

  it('converts 48kHz input into exact 512-sample 16kHz chunks', () => {
    const normalizer = new StreamingPcmNormalizer(48_000, 16_000, 512)
    const chunks = [
      ...normalizer.push(new Float32Array(512).fill(0.25)),
      ...normalizer.push(new Float32Array(512).fill(0.25)),
      ...normalizer.push(new Float32Array(512).fill(0.25)),
    ]

    expect(chunks).toHaveLength(1)
    expect(chunks[0]).toHaveLength(512)
    expect(chunks[0]?.every(sample => Math.abs(sample - 0.25) < 0.0001)).toBe(true)
  })

  it('preserves 16kHz chunks and pads only the final tail', () => {
    const normalizer = new StreamingPcmNormalizer(16_000, 16_000, 512)
    const chunks = normalizer.push(new Float32Array(700).fill(0.5))
    const tail = normalizer.flush()

    expect(chunks).toHaveLength(1)
    expect(chunks[0]).toHaveLength(512)
    expect(tail).toHaveLength(1)
    expect(tail[0]).toHaveLength(512)
    expect(tail[0]?.slice(0, 188).every(sample => sample === 0.5)).toBe(true)
    expect(tail[0]?.slice(188).every(sample => sample === 0)).toBe(true)
  })

  it('classifies speech energy without treating digital silence as speech', () => {
    expect(hasSpeechEnergy(new Float32Array(512))).toBe(false)
    expect(hasSpeechEnergy(new Float32Array(512).fill(AUDIO_SPEECH_RMS_THRESHOLD * 2))).toBe(true)
    expect(hasSpeechEnergy(new Float32Array(512).fill(0.005))).toBe(false)
  })
})
