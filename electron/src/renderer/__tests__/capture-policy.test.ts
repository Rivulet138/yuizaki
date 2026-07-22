import { describe, expect, it } from 'vitest'
import { resolveVisualCapturePolicy } from '../vision/capture-policy'


describe('realtime visual capture policy', () => {
  it('keeps sparse visual keyframes while the assistant is speaking and pauses a silent microphone', () => {
    expect(resolveVisualCapturePolicy({
      configuredIntervalMs: 1000,
      microphoneRecording: false,
      microphoneLevel: 0,
      hasPartialTranscript: false,
      assistantSpeaking: true,
    })).toEqual({
      shouldCapture: true,
      minUploadIntervalMs: 1500,
      forceUploadIntervalMs: 8000,
    })

    expect(resolveVisualCapturePolicy({
      configuredIntervalMs: 1000,
      microphoneRecording: true,
      microphoneLevel: 0.005,
      hasPartialTranscript: false,
      assistantSpeaking: false,
    }).shouldCapture).toBe(false)
  })

  it('rate-limits voice keyframes and avoids forced uploads during speech', () => {
    expect(resolveVisualCapturePolicy({
      configuredIntervalMs: 1000,
      microphoneRecording: true,
      microphoneLevel: 0.2,
      hasPartialTranscript: true,
      assistantSpeaking: false,
    })).toEqual({
      shouldCapture: true,
      minUploadIntervalMs: 1200,
      forceUploadIntervalMs: Infinity,
    })
  })

  it('keeps idle visual perception change-driven with a sparse heartbeat', () => {
    expect(resolveVisualCapturePolicy({
      configuredIntervalMs: 5000,
      microphoneRecording: false,
      microphoneLevel: 0,
      hasPartialTranscript: false,
      assistantSpeaking: false,
    })).toEqual({
      shouldCapture: true,
      minUploadIntervalMs: 5000,
      forceUploadIntervalMs: 30_000,
    })
  })
})
