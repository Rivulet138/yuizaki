import type { ScreenCaptureEncodingOptions } from '@/shared/types'
import type { VisualAnalysisStatus } from '@/stores/systemStore'
import {
  isTerminalVisualFrameResult,
  isVisualFrameResult,
  VisualCaptureEpoch,
} from '@/visual-capture-epoch'

type CaptureMode = 'display' | 'region'

export interface VisualCaptureSettings {
  enabled: boolean
  displayIndex: number
  captureMode: CaptureMode
  region: { x: number; y: number; width: number; height: number }
  privacyMasks: NonNullable<ScreenCaptureEncodingOptions['privacyMasks']>
}

interface VisualScreenApi {
  capture?: (displayIndex?: number, options?: ScreenCaptureEncodingOptions) => Promise<unknown>
  captureRegion?: (
    x: number,
    y: number,
    width: number,
    height: number,
    displayIndex?: number,
    options?: ScreenCaptureEncodingOptions,
  ) => Promise<unknown>
}

interface VisualSocketApi {
  isConnected: () => boolean
  requestScreenshot: (image: string, options: Record<string, unknown>) => void
  clearVisualContext: () => void
  discardScreenshotRequest: (request: Record<string, unknown>, reason: string) => void
}

export interface VisualCaptureRequest {
  workspaceId: string
  sessionId: string
  turnId: string
  jobId: string
  requestId: string
  frameId: string
  interruptionEpoch: number
}

interface VisualCaptureState {
  markVisualPerceptionCapturing: () => void
  markVisualPerceptionReady: (
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
  ) => void
  markVisualPerceptionError: (message: string) => void
}

interface PendingVisualResult {
  resolve: (payload: Record<string, unknown>) => void
  reject: (error: Error) => void
  timeout: ReturnType<typeof setTimeout>
}

export interface VisualCaptureRuntimeOptions {
  getSettings: () => VisualCaptureSettings
  getHealth: () => { controlRunning: boolean; pythonRunning: boolean }
  isDocumentHidden: () => boolean
  getScreenApi: () => VisualScreenApi | undefined
  getSocket: () => VisualSocketApi
  state: VisualCaptureState
  logger: { warn: (...args: unknown[]) => void }
  now?: () => number
  setTimeout?: typeof setTimeout
  clearTimeout?: typeof clearTimeout
}

const VISUAL_CAPTURE_ENCODING: ScreenCaptureEncodingOptions = {
  maxWidth: 1280,
  maxHeight: 720,
  format: 'jpeg',
  quality: 72,
}

export const createVisualCaptureRuntime = (options: VisualCaptureRuntimeOptions) => {
  const now = options.now ?? Date.now
  const setTimer = options.setTimeout ?? setTimeout
  const clearTimer = options.clearTimeout ?? clearTimeout
  const epoch = new VisualCaptureEpoch()
  const pendingResults = new Map<string, PendingVisualResult>()
  let frameInFlight = false
  let frameSequence = 0

  const rejectPending = (frameId: string, message: string) => {
    const pending = pendingResults.get(frameId)
    if (!pending) return
    clearTimer(pending.timeout)
    pendingResults.delete(frameId)
    pending.reject(new Error(message))
  }

  const waitForResult = (frameId: string): Promise<Record<string, unknown>> => (
    new Promise((resolve, reject) => {
      const timeout = setTimer(() => {
        pendingResults.delete(frameId)
        epoch.forgetFrame(frameId)
        reject(new Error(`Visual frame result timed out: ${frameId}`))
      }, 20_000)
      pendingResults.set(frameId, { resolve, reject, timeout })
    })
  )

  const cancelResultWait = (frameId: string) => {
    const pending = pendingResults.get(frameId)
    if (!pending) return
    clearTimer(pending.timeout)
    pendingResults.delete(frameId)
    epoch.forgetFrame(frameId)
  }

  const capture = async (requestedFrameId?: string, forceEnabled = false, request?: VisualCaptureRequest): Promise<string> => {
    const vision = options.getSettings()
    const socket = options.getSocket()
    if (!forceEnabled && !vision.enabled) return 'skipped:disabled'
    if (!forceEnabled && options.isDocumentHidden()) return 'skipped:document-hidden'
    const health = options.getHealth()
    if (!health.controlRunning || !health.pythonRunning) {
      return `skipped:health:${health.controlRunning}:${health.pythonRunning}`
    }
    if (!socket.isConnected()) return 'skipped:socket-disconnected'
    const screenApi = options.getScreenApi()
    if (!screenApi?.capture) {
      options.state.markVisualPerceptionError('当前环境不支持屏幕采集')
      return 'skipped:capture-api-unavailable'
    }
    if (frameInFlight) return 'skipped:capture-in-flight'

    const captureEpoch = epoch.current()
    frameInFlight = true
    options.state.markVisualPerceptionCapturing()
    try {
      const captureOptions = {
        ...VISUAL_CAPTURE_ENCODING,
        privacyMasks: vision.privacyMasks.map((mask) => ({ ...mask })),
      }
      const image = vision.captureMode === 'region' && screenApi.captureRegion
        ? await screenApi.captureRegion(
            vision.region.x,
            vision.region.y,
            vision.region.width,
            vision.region.height,
            vision.displayIndex,
            captureOptions,
          )
        : await screenApi.capture(vision.displayIndex, captureOptions)
      if (!epoch.isCurrent(captureEpoch)) return 'skipped:capture-invalidated'
      if (typeof image !== 'string' || !image.startsWith('data:image/')) {
        options.state.markVisualPerceptionError('没有捕获到可用画面')
        return 'skipped:invalid-image'
      }
      frameSequence += 1
      const frameId = requestedFrameId ?? `renderer-${now()}-${frameSequence}`
      epoch.trackFrame(frameId, captureEpoch, forceEnabled)
      socket.requestScreenshot(image, {
        displayIndex: vision.displayIndex,
        region: vision.captureMode === 'region' ? { ...vision.region } : undefined,
        mode: 'vision',
        source: vision.captureMode === 'region' ? 'desktop_region' : 'desktop',
        timestamp: now(),
        frameId,
        changeScore: 1,
        captureReason: forceEnabled ? 'manual' : 'agent_turn',
        ...(request ? {
          workspaceId: request.workspaceId,
          sessionId: request.sessionId,
          turnId: request.turnId,
          jobId: request.jobId,
          requestId: request.requestId,
          interruptionEpoch: request.interruptionEpoch,
        } : {}),
      })
      return frameId
    } catch (error) {
      if (!epoch.isCurrent(captureEpoch)) return 'skipped:capture-error-invalidated'
      options.logger.warn('Failed to capture realtime visual frame:', error)
      const message = error instanceof Error ? error.message : String(error)
      options.state.markVisualPerceptionError(message || '实时视觉采集失败')
      return `skipped:capture-error:${message}`
    } finally {
      frameInFlight = false
    }
  }

  const handleResult = (value: unknown) => {
    if (!value || typeof value !== 'object') return
    const payload = value as Record<string, unknown>
    const frameId = typeof payload.frame_id === 'string' ? payload.frame_id : null
    const pending = frameId ? pendingResults.get(frameId) : undefined
    const terminalResult = isTerminalVisualFrameResult(payload)
    const accepted = frameId
      ? epoch.acceptResult(frameId, options.getSettings().enabled, terminalResult)
      : false
    if (!accepted) {
      if (frameId && pending) rejectPending(frameId, `Visual frame result was invalidated: ${frameId}`)
      return
    }
    if (typeof payload.error === 'string' && payload.error) {
      if (frameId && pending) rejectPending(frameId, payload.error)
      options.state.markVisualPerceptionError(
        typeof payload.message === 'string' && payload.message ? payload.message : payload.error,
      )
      return
    }
    if (payload.status !== 'ok' || !isVisualFrameResult(payload)) return
    if (frameId && pending) {
      clearTimer(pending.timeout)
      pendingResults.delete(frameId)
      pending.resolve(payload)
    }
    options.state.markVisualPerceptionReady(
      typeof payload.frame_id === 'string' ? payload.frame_id : null,
      typeof payload.received_at === 'number' ? payload.received_at : null,
      {
        analysisStatus: typeof payload.analysis_status === 'string'
          ? payload.analysis_status as VisualAnalysisStatus
          : null,
        analysisReason: typeof payload.analysis_reason === 'string' ? payload.analysis_reason : null,
        analysisAttempts: typeof payload.analysis_attempts === 'number' ? payload.analysis_attempts : null,
        analysisSkipped: typeof payload.analysis_skipped === 'number' ? payload.analysis_skipped : null,
        changeScore: typeof payload.change_score === 'number' ? payload.change_score : null,
        captureReason: typeof payload.capture_reason === 'string' ? payload.capture_reason : null,
        analysisLatencyMs: typeof payload.analysis_latency_ms === 'number' ? payload.analysis_latency_ms : null,
      },
    )
  }

  const captureAndWait = async (frameId: string, forceEnabled = false) => {
    const resultPromise = waitForResult(frameId)
    const sentFrameId = await capture(frameId, forceEnabled)
    if (sentFrameId !== frameId) {
      cancelResultWait(frameId)
      options.getSocket().clearVisualContext()
      throw new Error(`Visual frame was not captured: ${sentFrameId}`)
    }
    return resultPromise
  }

  const isCaptureRequest = (value: unknown): value is VisualCaptureRequest => {
    if (!value || typeof value !== 'object') return false
    const request = value as Record<string, unknown>
    return ['workspaceId', 'sessionId', 'turnId', 'jobId', 'requestId', 'frameId']
      .every(key => typeof request[key] === 'string' && request[key] !== '')
      && Number.isInteger(request['interruptionEpoch'])
      && Number(request['interruptionEpoch']) >= 0
  }

  const handleCaptureRequest = async (value: unknown) => {
    if (!isCaptureRequest(value)) return
    const request = value
    const result = await capture(request.frameId, false, request)
    if (result !== request.frameId) {
      options.getSocket().discardScreenshotRequest(request as unknown as Record<string, unknown>, result)
    }
  }

  const discardOutstanding = (reason: string) => {
    for (const [frameId, pending] of pendingResults) {
      clearTimer(pending.timeout)
      pending.reject(new Error(`Visual frame result wait ${reason}: ${frameId}`))
    }
    pendingResults.clear()
  }

  const invalidate = () => {
    epoch.invalidate()
    discardOutstanding('invalidated')
  }

  const stop = () => {
    epoch.invalidate()
    discardOutstanding('cancelled')
  }

  return {
    capture,
    captureAndWait,
    handleCaptureRequest,
    handleResult,
    waitForResult,
    cancelResultWait,
    invalidate,
    stop,
  }
}
