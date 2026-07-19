import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
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
