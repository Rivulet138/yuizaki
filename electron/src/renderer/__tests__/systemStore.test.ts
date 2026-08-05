import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { __test__, useSystemStore } from '../stores/systemStore'
import { systemClient } from '../api/client'

vi.mock('../api/client', () => ({
  systemClient: {
    controlHealth: vi.fn(),
    pythonHealth: vi.fn(),
  },
}))

const mockedSystemClient = vi.mocked(systemClient)

describe('systemStore health payloads', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.resetAllMocks()
    mockedSystemClient.controlHealth.mockResolvedValue({ status: 'ok' })
  })

  afterEach(() => {
    vi.useRealTimers()
    Object.defineProperty(document, 'hidden', { configurable: true, value: false })
  })

  it('accepts the current control health payload as healthy', () => {
    expect(__test__.isHealthyControlPayload({ status: 'ok' })).toBe(true)
    expect(__test__.isHealthyControlPayload({ ok: true })).toBe(true)
    expect(__test__.isHealthyControlPayload({ healthy: true })).toBe(true)
  })

  it('accepts the current /api/ping ok payload as healthy', () => {
    expect(__test__.isHealthyPythonPayload({ ok: true })).toBe(true)
  })

  it('keeps legacy status based health payloads working', () => {
    expect(__test__.isHealthyPythonPayload({ status: 'healthy' })).toBe(true)
    expect(__test__.isHealthyPythonPayload({ status: 'ok' })).toBe(true)
    expect(__test__.isHealthyPythonPayload({ healthy: true })).toBe(true)
  })

  it('rejects timeout and malformed payloads', () => {
    expect(__test__.isHealthyPythonPayload({ error: 'Python backend request timed out' })).toBe(false)
    expect(__test__.isHealthyPythonPayload(null)).toBe(false)
  })

  it('recovers pythonRunning and clears health errors after a later successful ping', async () => {
    mockedSystemClient.pythonHealth
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({ ok: true })

    const store = useSystemStore()
    store.refreshStatus(() => false, () => false)
    await Promise.resolve()
    await Promise.resolve()

    expect(store.statusChecked).toBe(true)
    expect(store.pythonRunning).toBe(false)
    expect(store.pythonHealthError).toContain('offline')

    store.refreshStatus(() => false, () => false)
    await Promise.resolve()
    await Promise.resolve()

    expect(store.pythonRunning).toBe(true)
    expect(store.pythonHealthError).toBeNull()
    expect(store.pythonLastHealthyAt).toEqual(expect.any(Number))
  })

  it('tracks control server health separately from Python health', async () => {
    mockedSystemClient.controlHealth
      .mockRejectedValueOnce(new Error('control offline'))
      .mockResolvedValueOnce({ status: 'ok' })
    mockedSystemClient.pythonHealth.mockResolvedValue({ ok: true })

    const store = useSystemStore()
    store.refreshStatus(() => false, () => false)
    await Promise.resolve()
    await Promise.resolve()

    expect(store.controlRunning).toBe(false)
    expect(store.controlHealthError).toContain('control offline')
    expect(store.pythonRunning).toBe(true)

    store.refreshStatus(() => false, () => false)
    await Promise.resolve()
    await Promise.resolve()

    expect(store.controlRunning).toBe(true)
    expect(store.controlHealthError).toBeNull()
    expect(store.controlLastHealthyAt).toEqual(expect.any(Number))
  })

  it('checks immediately and polls healthy services every 30 seconds', async () => {
    vi.useFakeTimers()
    mockedSystemClient.pythonHealth.mockResolvedValue({ ok: true })
    const store = useSystemStore()

    store.startHealthCheck(() => false, () => true)
    await vi.advanceTimersByTimeAsync(0)
    expect(mockedSystemClient.pythonHealth).toHaveBeenCalledTimes(1)
    expect(store.sioConnected).toBe(true)

    await vi.advanceTimersByTimeAsync(29_999)
    expect(mockedSystemClient.pythonHealth).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(mockedSystemClient.pythonHealth).toHaveBeenCalledTimes(2)
    store.stopHealthCheck()
  })

  it('backs off failed health checks from 5 to 10 to 30 seconds', async () => {
    vi.useFakeTimers()
    mockedSystemClient.controlHealth.mockResolvedValue({ status: 'down' })
    mockedSystemClient.pythonHealth.mockResolvedValue({ ok: false })
    const store = useSystemStore()

    store.startHealthCheck(() => false, () => false)
    await vi.advanceTimersByTimeAsync(0)
    expect(mockedSystemClient.pythonHealth).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(5_000)
    expect(mockedSystemClient.pythonHealth).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(10_000)
    expect(mockedSystemClient.pythonHealth).toHaveBeenCalledTimes(3)
    await vi.advanceTimersByTimeAsync(30_000)
    expect(mockedSystemClient.pythonHealth).toHaveBeenCalledTimes(4)
    store.stopHealthCheck()
  })

  it('does not overlap checks and pauses polling while the document is hidden', async () => {
    vi.useFakeTimers()
    let resolvePython: ((value: { ok: true }) => void) | null = null
    mockedSystemClient.pythonHealth.mockImplementation(() => new Promise((resolve) => {
      resolvePython = resolve
    }))
    const store = useSystemStore()

    store.startHealthCheck(() => false, () => false)
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(60_000)
    expect(mockedSystemClient.pythonHealth).toHaveBeenCalledTimes(1)

    resolvePython?.({ ok: true })
    await vi.advanceTimersByTimeAsync(0)
    Object.defineProperty(document, 'hidden', { configurable: true, value: true })
    document.dispatchEvent(new Event('visibilitychange'))
    await vi.advanceTimersByTimeAsync(60_000)
    expect(mockedSystemClient.pythonHealth).toHaveBeenCalledTimes(1)

    Object.defineProperty(document, 'hidden', { configurable: true, value: false })
    document.dispatchEvent(new Event('visibilitychange'))
    await vi.advanceTimersByTimeAsync(0)
    expect(mockedSystemClient.pythonHealth).toHaveBeenCalledTimes(2)
    store.stopHealthCheck()
  })

  it('does not commit stale health results after polling stops or restarts', async () => {
    vi.useFakeTimers()
    let resolveControl: ((value: { status: 'ok' }) => void) | null = null
    let resolvePython: ((value: { ok: true }) => void) | null = null
    mockedSystemClient.controlHealth.mockImplementationOnce(() => new Promise((resolve) => {
      resolveControl = resolve
    })).mockResolvedValue({ status: 'ok' })
    mockedSystemClient.pythonHealth.mockImplementationOnce(() => new Promise((resolve) => {
      resolvePython = resolve
    })).mockResolvedValue({ ok: true })
    const store = useSystemStore()

    store.startHealthCheck(() => false, () => false)
    await vi.advanceTimersByTimeAsync(0)
    store.stopHealthCheck()
    resolveControl?.({ status: 'ok' })
    resolvePython?.({ ok: true })
    await vi.advanceTimersByTimeAsync(0)

    expect(store.statusChecked).toBe(false)
    expect(store.controlRunning).toBe(false)
    expect(store.pythonRunning).toBe(false)

    store.startHealthCheck(() => false, () => true)
    await vi.advanceTimersByTimeAsync(0)

    expect(mockedSystemClient.pythonHealth).toHaveBeenCalledTimes(2)
    expect(store.statusChecked).toBe(true)
    expect(store.controlRunning).toBe(true)
    expect(store.pythonRunning).toBe(true)
    expect(store.sioConnected).toBe(true)
    store.stopHealthCheck()
  })

  it('tracks realtime visual capture acknowledgements and errors', () => {
    const store = useSystemStore()

    store.setVisualPerceptionEnabled(true)
    expect(store.visualPerceptionPhase).toBe('waiting')

    store.markVisualPerceptionCapturing()
    expect(store.visualPerceptionPhase).toBe('capturing')

    store.markVisualPerceptionReady('frame-1', 1_700_000_000, {
      analysisStatus: 'cached',
      analysisReason: 'minor_change_cached',
      analysisAttempts: 2,
      analysisSkipped: 4,
      changeScore: 0.04,
      captureReason: 'change',
      analysisLatencyMs: 182.4,
    })
    expect(store.visualPerceptionPhase).toBe('ready')
    expect(store.visualPerceptionFrameId).toBe('frame-1')
    expect(store.visualPerceptionLastFrameAt).toBe(1_700_000_000_000)
    expect(store.visualAnalysisStatus).toBe('cached')
    expect(store.visualAnalysisReason).toBe('minor_change_cached')
    expect(store.visualAnalysisAttempts).toBe(2)
    expect(store.visualAnalysisSkipped).toBe(4)
    expect(store.visualChangeScore).toBe(0.04)
    expect(store.visualCaptureReason).toBe('change')
    expect(store.visualAnalysisLatencyMs).toBe(182.4)

    store.markVisualPerceptionError('model rejected image input')
    expect(store.visualPerceptionPhase).toBe('error')
    expect(store.visualPerceptionError).toBe('model rejected image input')

    store.setVisualPerceptionEnabled(false)
    expect(store.visualPerceptionPhase).toBe('disabled')
    expect(store.visualPerceptionError).toBeNull()
    expect(store.visualAnalysisStatus).toBeNull()
    expect(store.visualAnalysisAttempts).toBe(0)
    expect(store.visualAnalysisLatencyMs).toBeNull()
  })
})
