import { describe, expect, it } from 'vitest'
import {
  MAX_VISUAL_CAPTURE_INTERVAL_MS,
  MIN_VISUAL_CAPTURE_INTERVAL_MS,
  normalizeVisualCaptureInterval,
  resolveVisualCaptureBlockReason,
  resolveVisualCapturePolicy,
} from '../vision/capture-policy'


describe('realtime visual capture policy', () => {
  it('normalizes capture timers within the browser-safe product range', () => {
    expect(normalizeVisualCaptureInterval(1)).toBe(MIN_VISUAL_CAPTURE_INTERVAL_MS)
    expect(normalizeVisualCaptureInterval(3_000_000_000)).toBe(MAX_VISUAL_CAPTURE_INTERVAL_MS)
    expect(normalizeVisualCaptureInterval(Number.POSITIVE_INFINITY)).toBe(30_000)
  })

  it('blocks capture while hidden or disconnected', () => {
    const readiness = {
      enabled: true,
      pauseWhenAppHidden: true,
      documentHidden: true,
      servicesHealthy: true,
      socketConnected: true,
    }
    expect(resolveVisualCaptureBlockReason(readiness)).toBe('document-hidden')
    expect(resolveVisualCaptureBlockReason({
      ...readiness,
      documentHidden: false,
      socketConnected: false,
    })).toBe('socket-disconnected')
  })

  it('keeps sparse visual keyframes while the assistant is speaking and pauses a silent microphone', () => {
    expect(resolveVisualCapturePolicy({
      configuredIntervalMs: 1000,
      microphoneRecording: false,
      microphoneLevel: 0,
      hasPartialTranscript: false,
      assistantSpeaking: true,
    })).toEqual({
      shouldCapture: true,
      minUploadIntervalMs: 10_000,
      forceUploadIntervalMs: 20_000,
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
      minUploadIntervalMs: 10_000,
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
      minUploadIntervalMs: 10_000,
      forceUploadIntervalMs: 60_000,
    })
  })

  it('never shortens a configured interval above the minimum', () => {
    expect(resolveVisualCapturePolicy({
      configuredIntervalMs: 45_000,
      microphoneRecording: false,
      microphoneLevel: 0,
      hasPartialTranscript: false,
      assistantSpeaking: false,
    }).minUploadIntervalMs).toBe(45_000)
  })
})
