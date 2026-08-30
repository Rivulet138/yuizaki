import { describe, expect, it, vi } from 'vitest'
import {
  AUDIO_SILENCE_GRACE_MS,
  AUDIO_SPEECH_RMS_THRESHOLD,
  AudioCapture,
  classifyAudioInputHealth,
  enumerateAudioInputDevices,
} from './audio-capture'

describe('audio capture input health', () => {
  it('distinguishes active input, grace-period silence, and sustained silence', () => {
    expect(classifyAudioInputHealth(AUDIO_SPEECH_RMS_THRESHOLD * 2, 0)).toBe('active')
    expect(classifyAudioInputHealth(0, AUDIO_SILENCE_GRACE_MS - 1)).toBe('unknown')
    expect(classifyAudioInputHealth(0, AUDIO_SILENCE_GRACE_MS)).toBe('silent')
  })

  it('treats an ended media track as disconnected regardless of energy', () => {
    expect(classifyAudioInputHealth(AUDIO_SPEECH_RMS_THRESHOLD * 2, 0, 'ended')).toBe('disconnected')
  })

  it('does not infer semantic comfort signals from a quiet input', () => {
    expect(classifyAudioInputHealth(0, AUDIO_SILENCE_GRACE_MS)).toBe('silent')
  })

  it('returns bounded input IDs and redacted fallback labels', async () => {
    const enumerateDevices = vi.fn().mockResolvedValue([
      { kind: 'audioinput', deviceId: 'mic-1', label: 'Desk microphone' },
      { kind: 'audiooutput', deviceId: 'speaker-1', label: 'Speaker' },
      { kind: 'audioinput', deviceId: 'mic-2', label: '' },
    ])
    vi.stubGlobal('navigator', { mediaDevices: { enumerateDevices } })

    await expect(enumerateAudioInputDevices()).resolves.toEqual([
      { deviceId: 'mic-1', label: 'Desk microphone' },
      { deviceId: 'mic-2', label: '未命名麦克风' },
    ])
  })

  it('releases an active capture immediately when the transport disappears', () => {
    const capture = new AudioCapture()
    capture.getIsRecording().value = true
    const disconnectedSocket = { isConnected: () => false } as never

    ;(capture as unknown as { sendAudioChunkNow: (data: Float32Array, socket: unknown) => void }).sendAudioChunkNow(
      new Float32Array([0.1, -0.1]),
      disconnectedSocket,
    )

    const status = capture.getStatus()
    expect(capture.getIsRecording().value).toBe(false)
    expect(status.phase).toBe('error')
    expect(status.error).toBe('实时通道连接已断开')
  })
})
