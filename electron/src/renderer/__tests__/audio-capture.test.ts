import { describe, expect, it } from 'vitest'
import {
  normalizeAudioProcessingSettings,
  StreamingPcmNormalizer,
} from '../audio/audio-capture'

describe('audio capture normalization', () => {
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
})
