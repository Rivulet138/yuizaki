import { defineStore } from 'pinia'
import { ref } from 'vue'
import { systemClient } from '@/api/client'
import type { HttpClientError } from '@/api/clients/http-client'

export type VisualPerceptionPhase = 'disabled' | 'waiting' | 'capturing' | 'ready' | 'error'
export type VisualAnalysisStatus = 'unavailable' | 'pending' | 'cached' | 'ready' | 'empty' | 'error' | null

const isHealthyPythonPayload = (data: unknown): boolean => {
  if (!data || typeof data !== 'object') return false
  const payload = data as Record<string, unknown>
  return payload['status'] === 'healthy' ||
    payload['status'] === 'ok' ||
    payload['healthy'] === true ||
    payload['ok'] === true
}

const isHealthyControlPayload = (data: unknown): boolean => {
  if (!data || typeof data !== 'object') return false
  const payload = data as Record<string, unknown>
  return payload['status'] === 'ok' || payload['healthy'] === true || payload['ok'] === true
}

export const useSystemStore = defineStore('system', () => {
  const controlRunning = ref(false)
  const pythonRunning = ref(false)
  const wsConnected = ref(false)
  const sioConnected = ref(false)
  const statusChecked = ref(false)
  const controlHealthError = ref<string | null>(null)
  const pythonHealthError = ref<string | null>(null)
  const controlLastHealthyAt = ref<number | null>(null)
  const pythonLastHealthyAt = ref<number | null>(null)
  const visualPerceptionPhase = ref<VisualPerceptionPhase>('waiting')
  const visualPerceptionLastFrameAt = ref<number | null>(null)
  const visualPerceptionFrameId = ref<string | null>(null)
  const visualPerceptionError = ref<string | null>(null)
  const visualAnalysisStatus = ref<VisualAnalysisStatus>(null)
  const visualAnalysisReason = ref<string | null>(null)
  const visualAnalysisAttempts = ref(0)
  const visualAnalysisSkipped = ref(0)
  const visualChangeScore = ref<number | null>(null)
  const visualCaptureReason = ref<string | null>(null)
  const visualAnalysisLatencyMs = ref<number | null>(null)

  let statusTimer: ReturnType<typeof setInterval> | null = null
  let checkingControl = false
  let checkingPython = false

  const checkControlByHttp = async (): Promise<{ healthy: boolean; error: string | null }> => {
    try {
      const data = await systemClient.controlHealth()
      const healthy = isHealthyControlPayload(data)
      return {
        healthy,
        error: healthy ? null : 'Control server returned an unhealthy payload',
      }
    } catch (error) {
      const clientError = error as HttpClientError
      return {
        healthy: false,
        error: error instanceof Error ? error.message : clientError?.code || 'Control server is unavailable',
      }
    }
  }

  const checkPythonByHttp = async (): Promise<{ healthy: boolean; error: string | null }> => {
    try {
      const data = await systemClient.pythonHealth()
      const healthy = isHealthyPythonPayload(data)
      return {
        healthy,
        error: healthy ? null : 'Python backend returned an unhealthy payload',
      }
    } catch (error) {
      const clientError = error as HttpClientError
      return {
        healthy: false,
        error: error instanceof Error ? error.message : clientError?.code || 'Python backend is unavailable',
      }
    }
  }

  const checkControl = async (): Promise<void> => {
    if (checkingControl) return
    checkingControl = true
    try {
      const result = await checkControlByHttp()
      controlRunning.value = result.healthy
      controlHealthError.value = result.error
      if (result.healthy) {
        controlLastHealthyAt.value = Date.now()
      }
    } catch {
      controlRunning.value = false
      controlHealthError.value = 'Control server health check failed'
    } finally {
      statusChecked.value = true
      checkingControl = false
    }
  }

  const checkPython = async (): Promise<void> => {
    if (checkingPython) return
    checkingPython = true
    try {
      const result = await checkPythonByHttp()
      pythonRunning.value = result.healthy
      pythonHealthError.value = result.error
      if (result.healthy) {
        pythonLastHealthyAt.value = Date.now()
      }
    } catch {
      pythonRunning.value = false
      pythonHealthError.value = 'Python backend health check failed'
    } finally {
      statusChecked.value = true
      checkingPython = false
    }
  }

  const checkLocalServices = (): void => {
    void checkControl()
    void checkPython()
  }

  const startHealthCheck = (
    checkWs: () => boolean,
    checkSio: () => boolean,
  ) => {
    if (statusTimer) clearInterval(statusTimer)

    checkLocalServices()

    statusTimer = setInterval(() => {
      wsConnected.value = checkWs()
      sioConnected.value = checkSio()
      checkLocalServices()
    }, 1500)
  }

  const refreshStatus = (
    checkWs: () => boolean,
    checkSio: () => boolean,
  ) => {
    wsConnected.value = checkWs()
    sioConnected.value = checkSio()
    checkLocalServices()
  }

  const stopHealthCheck = () => {
    if (statusTimer) {
      clearInterval(statusTimer)
      statusTimer = null
    }
    wsConnected.value = false
    sioConnected.value = false
    statusChecked.value = false
    controlHealthError.value = null
    pythonHealthError.value = null
  }

  const setVisualPerceptionEnabled = (enabled: boolean) => {
    visualPerceptionPhase.value = enabled ? 'waiting' : 'disabled'
    visualPerceptionError.value = null
    if (!enabled) {
      visualPerceptionFrameId.value = null
      visualAnalysisStatus.value = null
      visualAnalysisReason.value = null
      visualAnalysisAttempts.value = 0
      visualAnalysisSkipped.value = 0
      visualChangeScore.value = null
      visualCaptureReason.value = null
      visualAnalysisLatencyMs.value = null
    }
  }

  const markVisualPerceptionCapturing = () => {
    visualPerceptionPhase.value = 'capturing'
    visualPerceptionError.value = null
  }

  const markVisualPerceptionReady = (
    frameId?: string | null,
    receivedAt?: number | null,
    diagnostics?: {
      analysisStatus?: VisualAnalysisStatus
      analysisReason?: string | null
      analysisAttempts?: number | null
      analysisSkipped?: number | null
      changeScore?: number | null
      captureReason?: string | null
      analysisLatencyMs?: number | null
    },
  ) => {
    visualPerceptionPhase.value = 'ready'
    visualPerceptionFrameId.value = frameId || null
    visualPerceptionLastFrameAt.value = receivedAt && Number.isFinite(receivedAt)
      ? Math.round(receivedAt * (receivedAt < 10_000_000_000 ? 1000 : 1))
      : Date.now()
    visualPerceptionError.value = null
    visualAnalysisStatus.value = diagnostics?.analysisStatus ?? null
    visualAnalysisReason.value = diagnostics?.analysisReason || null
    visualAnalysisAttempts.value = Number.isFinite(diagnostics?.analysisAttempts)
      ? Math.max(0, Math.round(diagnostics?.analysisAttempts ?? 0))
      : 0
    visualAnalysisSkipped.value = Number.isFinite(diagnostics?.analysisSkipped)
      ? Math.max(0, Math.round(diagnostics?.analysisSkipped ?? 0))
      : 0
    visualChangeScore.value = Number.isFinite(diagnostics?.changeScore)
      ? Math.max(0, Math.min(1, diagnostics?.changeScore ?? 0))
      : null
    visualCaptureReason.value = diagnostics?.captureReason || null
    visualAnalysisLatencyMs.value = Number.isFinite(diagnostics?.analysisLatencyMs)
      ? Math.max(0, diagnostics?.analysisLatencyMs ?? 0)
      : null
  }

  const markVisualPerceptionError = (message: string) => {
    visualPerceptionPhase.value = 'error'
    visualPerceptionError.value = message || '实时视觉不可用'
  }

  return {
    controlRunning,
    pythonRunning,
    wsConnected,
    sioConnected,
    statusChecked,
    controlHealthError,
    pythonHealthError,
    controlLastHealthyAt,
    pythonLastHealthyAt,
    visualPerceptionPhase,
    visualPerceptionLastFrameAt,
    visualPerceptionFrameId,
    visualPerceptionError,
    visualAnalysisStatus,
    visualAnalysisReason,
    visualAnalysisAttempts,
    visualAnalysisSkipped,
    visualChangeScore,
    visualCaptureReason,
    visualAnalysisLatencyMs,
    startHealthCheck,
    refreshStatus,
    stopHealthCheck,
    setVisualPerceptionEnabled,
    markVisualPerceptionCapturing,
    markVisualPerceptionReady,
    markVisualPerceptionError,
  }
})

export const __test__ = {
  isHealthyControlPayload,
  isHealthyPythonPayload,
}
