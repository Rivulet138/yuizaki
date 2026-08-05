export interface VisualCaptureActivity {
  configuredIntervalMs: number
  microphoneRecording: boolean
  microphoneLevel: number
  hasPartialTranscript: boolean
  assistantSpeaking: boolean
}

export interface VisualCapturePolicy {
  shouldCapture: boolean
  minUploadIntervalMs: number
  forceUploadIntervalMs: number
}

export interface VisualCaptureReadiness {
  enabled: boolean
  pauseWhenAppHidden: boolean
  documentHidden: boolean
  servicesHealthy: boolean
  socketConnected: boolean
}

export type VisualCaptureBlockReason = 'disabled' | 'document-hidden' | 'health-unavailable' | 'socket-disconnected'

const MIN_SPEECH_LEVEL = 0.02
export const MIN_VISUAL_CAPTURE_INTERVAL_MS = 10_000
export const MAX_VISUAL_CAPTURE_INTERVAL_MS = 60 * 60 * 1_000

export function normalizeVisualCaptureInterval(value: unknown): number {
  const intervalMs = Number(value)
  if (!Number.isFinite(intervalMs)) return 30_000
  return Math.max(
    MIN_VISUAL_CAPTURE_INTERVAL_MS,
    Math.min(MAX_VISUAL_CAPTURE_INTERVAL_MS, Math.round(intervalMs)),
  )
}

export function resolveVisualCaptureBlockReason(readiness: VisualCaptureReadiness): VisualCaptureBlockReason | null {
  if (!readiness.enabled) return 'disabled'
  if (readiness.pauseWhenAppHidden && readiness.documentHidden) return 'document-hidden'
  if (!readiness.servicesHealthy) return 'health-unavailable'
  if (!readiness.socketConnected) return 'socket-disconnected'
  return null
}

export function resolveVisualCapturePolicy(activity: VisualCaptureActivity): VisualCapturePolicy {
  const configuredIntervalMs = normalizeVisualCaptureInterval(activity.configuredIntervalMs)
  if (activity.assistantSpeaking) {
    return {
      shouldCapture: true,
      minUploadIntervalMs: configuredIntervalMs,
      forceUploadIntervalMs: configuredIntervalMs * 2,
    }
  }
  if (activity.microphoneRecording && !activity.hasPartialTranscript && activity.microphoneLevel < MIN_SPEECH_LEVEL) {
    return { shouldCapture: false, minUploadIntervalMs: configuredIntervalMs, forceUploadIntervalMs: Infinity }
  }
  if (activity.microphoneRecording) {
    return {
      shouldCapture: true,
      minUploadIntervalMs: configuredIntervalMs,
      forceUploadIntervalMs: Infinity,
    }
  }
  return {
    shouldCapture: true,
    minUploadIntervalMs: configuredIntervalMs,
    forceUploadIntervalMs: Math.max(30_000, configuredIntervalMs * 6),
  }
}
