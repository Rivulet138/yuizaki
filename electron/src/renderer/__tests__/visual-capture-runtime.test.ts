import { afterEach, describe, expect, it, vi } from 'vitest'

import { createVisualCaptureRuntime } from '../app/runtime/visualCaptureRuntime'

const createHarness = () => {
  let now = 1_700_000_000_000
  let hidden = false
  let socketConnected = true
  let settings = {
    enabled: true,
    displayIndex: 0,
    captureMode: 'display' as const,
    region: { x: 0, y: 0, width: 320, height: 240 },
    privacyMasks: [],
  }
  let health = { controlRunning: true, pythonRunning: true }
  const capture = vi.fn(async () => 'data:image/jpeg;base64,frame')
  const captureRegion = vi.fn(async () => 'data:image/jpeg;base64,region')
  const requestScreenshot = vi.fn()
  const clearVisualContext = vi.fn()
  const discardScreenshotRequest = vi.fn()
  const state = {
    markVisualPerceptionCapturing: vi.fn(),
    markVisualPerceptionReady: vi.fn(),
    markVisualPerceptionError: vi.fn(),
  }
  const logger = { warn: vi.fn() }
  const runtime = createVisualCaptureRuntime({
    getSettings: () => settings,
    getHealth: () => health,
    isDocumentHidden: () => hidden,
    getScreenApi: () => ({ capture, captureRegion }),
    getSocket: () => ({
      isConnected: () => socketConnected,
      requestScreenshot,
      clearVisualContext,
      discardScreenshotRequest,
    }),
    state,
    logger,
    now: () => now,
    setTimeout,
    clearTimeout,
  })

  return {
    runtime,
    capture,
    captureRegion,
    requestScreenshot,
    clearVisualContext,
    discardScreenshotRequest,
    state,
    logger,
    setHidden: (value: boolean) => { hidden = value },
    setSocketConnected: (value: boolean) => { socketConnected = value },
    getSettings: () => settings,
    setSettings: (value: typeof settings) => { settings = value },
    setHealth: (value: typeof health) => { health = value },
    advance: (milliseconds: number) => { now += milliseconds },
  }
}

afterEach(() => {
  vi.useRealTimers()
})

describe('visual capture runtime', () => {
  it('keeps disabled and hidden captures one-shot and side-effect free', async () => {
    const harness = createHarness()

    harness.setSettings({ ...harness.getSettings(), enabled: false })
    await expect(harness.runtime.capture()).resolves.toBe('skipped:disabled')

    harness.setSettings({ ...harness.getSettings(), enabled: true })
    harness.setHidden(true)
    await expect(harness.runtime.capture()).resolves.toBe('skipped:document-hidden')

    expect(harness.capture).not.toHaveBeenCalled()
    expect(harness.requestScreenshot).not.toHaveBeenCalled()
  })

  it('discards a backend request without touching capture APIs when vision is disabled', async () => {
    const harness = createHarness()
    harness.setSettings({ ...harness.getSettings(), enabled: false })

    await harness.runtime.handleCaptureRequest({
      requestId: 'request-disabled',
      sessionId: 'session-disabled',
      workspaceId: 'workspace-disabled',
      turnId: 'turn-disabled',
      jobId: 'vision:request-disabled',
      frameId: 'frame-disabled',
      interruptionEpoch: 0,
    })

    expect(harness.capture).not.toHaveBeenCalled()
    expect(harness.requestScreenshot).not.toHaveBeenCalled()
    expect(harness.discardScreenshotRequest).toHaveBeenCalledWith(expect.objectContaining({
      jobId: 'vision:request-disabled',
    }), 'skipped:disabled')
  })

  it('ignores malformed backend capture identities', async () => {
    const harness = createHarness()

    await harness.runtime.handleCaptureRequest({
      requestId: 'request-malformed',
      sessionId: 'session-malformed',
      workspaceId: 'workspace-malformed',
      turnId: 'turn-malformed',
      jobId: 'vision:request-malformed',
      frameId: 'frame-malformed',
      interruptionEpoch: -1,
    })

    expect(harness.capture).not.toHaveBeenCalled()
    expect(harness.requestScreenshot).not.toHaveBeenCalled()
    expect(harness.discardScreenshotRequest).not.toHaveBeenCalled()
  })

  it('rejects unavailable health, disconnected socket, and concurrent capture', async () => {
    const harness = createHarness()
    harness.setHealth({ controlRunning: false, pythonRunning: true })
    await expect(harness.runtime.capture()).resolves.toBe('skipped:health:false:true')

    harness.setHealth({ controlRunning: true, pythonRunning: true })
    harness.setSocketConnected(false)
    await expect(harness.runtime.capture()).resolves.toBe('skipped:socket-disconnected')

    harness.setSocketConnected(true)
    let releaseCapture!: (value: string) => void
    harness.capture.mockImplementationOnce(() => new Promise(resolve => { releaseCapture = resolve }))
    const first = harness.runtime.capture('frame-1')
    await vi.waitFor(() => expect(harness.state.markVisualPerceptionCapturing).toHaveBeenCalledTimes(1))
    await expect(harness.runtime.capture('frame-2')).resolves.toBe('skipped:capture-in-flight')
    releaseCapture('data:image/jpeg;base64:frame')
    await expect(first).resolves.toBe('frame-1')
  })

  it('resolves correlated results, rejects errors, and invalidates pending waits on stop', async () => {
    vi.useFakeTimers()
    const harness = createHarness()
    const resultPromise = harness.runtime.waitForResult('frame-1')
    await harness.runtime.capture('frame-1')

    harness.runtime.handleResult({
      frame_id: 'frame-1',
      status: 'ok',
      mode: 'vision',
      analysis_status: 'ready',
      received_at: 123,
    })
    await expect(resultPromise).resolves.toMatchObject({ frame_id: 'frame-1' })
    expect(harness.state.markVisualPerceptionReady).toHaveBeenCalledTimes(1)

    const errorPromise = harness.runtime.waitForResult('frame-2')
    await harness.runtime.capture('frame-2')
    harness.runtime.handleResult({ frame_id: 'frame-2', error: 'OCR_FAILED' })
    await expect(errorPromise).rejects.toThrow('OCR_FAILED')
    expect(harness.state.markVisualPerceptionError).toHaveBeenCalledWith('OCR_FAILED')

    const pending = harness.runtime.waitForResult('frame-3')
    harness.runtime.stop()
    await expect(pending).rejects.toThrow('cancelled')
  })

  it('does not accept a result from an invalidated epoch', async () => {
    const harness = createHarness()
    const pending = harness.runtime.waitForResult('frame-1')
    await harness.runtime.capture('frame-1')
    harness.runtime.invalidate()
    harness.runtime.handleResult({ frame_id: 'frame-1', status: 'ok', mode: 'vision', analysis_status: 'ready' })

    await expect(pending).rejects.toThrow('invalidated')
    expect(harness.state.markVisualPerceptionReady).not.toHaveBeenCalled()
  })

  it('responds to one backend capture request without local intent matching', async () => {
    const harness = createHarness()
    await harness.runtime.handleCaptureRequest({
      workspaceId: 'workspace-backend',
      sessionId: 'session-backend',
      turnId: 'turn-backend',
      jobId: 'vision:request-backend',
      requestId: 'request-backend',
      frameId: 'frame-backend',
      interruptionEpoch: 3,
    })

    expect(harness.requestScreenshot).toHaveBeenCalledTimes(1)
    expect(harness.requestScreenshot.mock.calls[0]?.[1]).toMatchObject({
      frameId: 'frame-backend',
      jobId: 'vision:request-backend',
      requestId: 'request-backend',
      turnId: 'turn-backend',
    })
  })

  it('discards a concurrent backend request without cancelling the active capture', async () => {
    const harness = createHarness()
    let releaseCapture!: (value: string) => void
    harness.capture.mockImplementationOnce(() => new Promise(resolve => { releaseCapture = resolve }))
    const firstRequest = {
      requestId: 'request-first',
      sessionId: 'session-first',
      workspaceId: 'workspace-vision',
      turnId: 'turn-first',
      jobId: 'vision:request-first',
      frameId: 'frame-first',
      interruptionEpoch: 0,
    }
    const secondRequest = {
      ...firstRequest,
      requestId: 'request-second',
      sessionId: 'session-second',
      turnId: 'turn-second',
      jobId: 'vision:request-second',
      frameId: 'frame-second',
    }

    const first = harness.runtime.handleCaptureRequest(firstRequest)
    await vi.waitFor(() => expect(harness.state.markVisualPerceptionCapturing).toHaveBeenCalledTimes(1))
    await harness.runtime.handleCaptureRequest(secondRequest)

    expect(harness.discardScreenshotRequest).toHaveBeenCalledWith(secondRequest, 'skipped:capture-in-flight')
    releaseCapture('data:image/jpeg;base64,frame')
    await first
    expect(harness.requestScreenshot).toHaveBeenCalledTimes(1)
  })
})
