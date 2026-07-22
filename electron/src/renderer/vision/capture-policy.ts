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

const MIN_SPEECH_LEVEL = 0.02

export function resolveVisualCapturePolicy(activity: VisualCaptureActivity): VisualCapturePolicy {
  const configuredIntervalMs = Math.max(750, activity.configuredIntervalMs)
  if (activity.assistantSpeaking) {
    return {
      shouldCapture: true,
      minUploadIntervalMs: Math.max(1500, configuredIntervalMs),
      forceUploadIntervalMs: Math.max(8000, configuredIntervalMs * 2),
    }
  }
  if (activity.microphoneRecording && !activity.hasPartialTranscript && activity.microphoneLevel < MIN_SPEECH_LEVEL) {
    return { shouldCapture: false, minUploadIntervalMs: configuredIntervalMs, forceUploadIntervalMs: Infinity }
  }
  if (activity.microphoneRecording) {
    return {
      shouldCapture: true,
      minUploadIntervalMs: Math.max(1200, configuredIntervalMs),
      forceUploadIntervalMs: Infinity,
    }
  }
  return {
    shouldCapture: true,
    minUploadIntervalMs: configuredIntervalMs,
    forceUploadIntervalMs: Math.max(30_000, configuredIntervalMs * 6),
  }
}
