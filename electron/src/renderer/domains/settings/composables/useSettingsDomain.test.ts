import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { settingsClient } from '@/api/client'
import type { RuntimeReloadSection, RuntimeReloadStatusResponse } from '@/api/clients/settings-client'
import { useSettingsDomain } from './useSettingsDomain'

vi.mock('@/api/client', () => ({ settingsClient: { runtimeStatus: vi.fn(), retryRuntime: vi.fn(), load: vi.fn(), save: vi.fn(), ttsStatus: vi.fn(), warmupTts: vi.fn() } }))
const deferred = <T>() => {
  let resolve!: (value: T) => void
  let reject!: (reason: Error) => void
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}

beforeEach(() => vi.resetAllMocks())

describe('settings persistence readback', () => {
  it('does not let an earlier warmup runtime overwrite a newer status read', async () => {
    const warmup = deferred<Awaited<ReturnType<typeof settingsClient.warmupTts>>>()
    vi.mocked(settingsClient.warmupTts).mockReturnValueOnce(warmup.promise)
    vi.mocked(settingsClient.ttsStatus).mockResolvedValue({ available: false, provider: 'openai-compatible' })
    const domain = useSettingsDomain()
    const warming = domain.warmupTts()
    await domain.loadTtsStatus()
    warmup.resolve({ ok: true, queued: false, runtime: { available: true, provider: 'genie-tts' } })
    expect(await warming).toEqual({ ok: true, queued: false, runtime: { available: true, provider: 'genie-tts' } })
    expect(domain.ttsStatus.value).toEqual({ available: false, provider: 'openai-compatible' })
  })

  it('uses the normalized GET response rather than the submitted patch', async () => {
    vi.mocked(settingsClient.save).mockResolvedValue({ status: 'ok', runtime_changed: ['llm'], runtime_applied: [] })
    const normalized = { llm: { timeout: 120 } } as Awaited<ReturnType<typeof settingsClient.load>>
    vi.mocked(settingsClient.load).mockResolvedValue(normalized)
    const domain = useSettingsDomain()
    const result = await domain.patchSettings({ llm: { timeout: 999 } })
    expect(result?.normalizedSettings).toEqual(normalized)
    expect(domain.settings.value).toEqual(normalized)
    expect(result?.runtime_applied).toEqual([])
  })

  it('distinguishes a saved mutation from a failed readback', async () => {
    const logging = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    vi.mocked(settingsClient.save).mockResolvedValue({ status: 'ok' })
    vi.mocked(settingsClient.load).mockRejectedValue(new Error('readback unavailable'))
    try {
      const domain = useSettingsDomain()
      expect(await domain.patchSettings({ llm: { timeout: 999 } })).toBeNull()
      expect(domain.settingsReadbackFailed.value).toBe(true)
      expect(domain.settings.value).toBeNull()
    } finally {
      logging.mockRestore()
    }
  })

  it('discards a load response that predates a save and its readback', async () => {
    const older = deferred<Awaited<ReturnType<typeof settingsClient.load>>>()
    const normalized = { asr: { api_key: '' } } as Awaited<ReturnType<typeof settingsClient.load>>
    vi.mocked(settingsClient.load).mockReturnValueOnce(older.promise).mockResolvedValueOnce(normalized)
    vi.mocked(settingsClient.save).mockResolvedValue({ status: 'ok' })
    const domain = useSettingsDomain()
    const loading = domain.loadSettings()
    await domain.patchSettings({ asr: { api_key: '' } })
    older.resolve({ asr: { api_key: 'old' } } as typeof normalized)
    expect(await loading).toBeNull()
    expect(domain.settings.value).toEqual(normalized)
  })
})


describe('runtime reload status', () => {
  const failed = { sections: { llm: { state: 'failed' as const, target_revision: 3, applied_revision: null, error: 'runtime_reload_failed' } } }
  const pending = { sections: { llm: { state: 'pending' as const, target_revision: 4, applied_revision: null } } }

  it('retains saved runtime state when normalized readback fails', async () => {
    const logging = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    vi.mocked(settingsClient.save).mockResolvedValue({ status: 'ok', runtime_reload: pending })
    vi.mocked(settingsClient.load).mockRejectedValue(new Error('readback failed'))
    const domain = useSettingsDomain()
    try {
      expect(await domain.patchSettings({ llm: { model: 'new' } })).toBeNull()
      expect(domain.runtimeReload.value).toEqual(pending)
      expect(domain.settingsReadbackFailed.value).toBe(true)
    } finally { logging.mockRestore() }
  })

  it('rejects a stale status read after a newer mutation acknowledgement', async () => {
    const older = deferred<typeof failed>()
    vi.mocked(settingsClient.runtimeStatus).mockReturnValueOnce(older.promise)
    const domain = useSettingsDomain()
    const loading = domain.loadRuntimeStatus()
    domain.acceptRuntimeStatus(pending)
    older.resolve(failed)
    expect(await loading).toBeNull()
    expect(domain.runtimeReload.value).toEqual(pending)
  })

  it('retries only explicitly displayed target revisions without saving', async () => {
    const domain = useSettingsDomain()
    domain.acceptRuntimeStatus(failed)
    vi.mocked(settingsClient.retryRuntime).mockResolvedValue(pending)
    expect(await domain.retryRuntime({ llm: 3 })).toEqual(pending)
    expect(settingsClient.retryRuntime).toHaveBeenCalledWith({ llm: 3 })
    expect(settingsClient.save).not.toHaveBeenCalled()
  })
})



describe('runtime retry error recovery', () => {
  const section = (state: RuntimeReloadSection['state'], revision = 7, applied: number | null = null): RuntimeReloadSection => ({
    state, target_revision: revision, applied_revision: applied,
  })
  const failedStatus = { sections: { svc: section('failed') } }
  const appliedStatus = { sections: { svc: section('applied', 7, 7) } }
  const failRetry = async (domain: ReturnType<typeof useSettingsDomain>, targets: Record<string, number> = { svc: 7 }, message = 'synthetic retry failure') => {
    vi.mocked(settingsClient.retryRuntime).mockRejectedValueOnce(new Error(message))
    expect(await domain.retryRuntime(targets)).toBeNull()
    expect(domain.runtimeRetryRequest.error).toContain(message)
  }

  beforeEach(() => { vi.spyOn(console, 'error').mockImplementation(() => undefined) })
  afterEach(() => { vi.restoreAllMocks() })

  const statuses: Array<{ name: string; status: RuntimeReloadStatusResponse; recovered: boolean }> = [
    { name: 'svc r7 applied', status: appliedStatus, recovered: true },
    { name: 'a newer revision of the same service', status: { sections: { svc: section('pending', 8) } }, recovered: true },
    { name: 'an older applied revision', status: { sections: { svc: section('applied', 6, 6) } }, recovered: false },
    { name: 'another applied service', status: { sections: { llm: section('applied', 7, 7) } }, recovered: false },
    { name: 'an empty status', status: { sections: {} }, recovered: false },
    { name: 'the same failed target', status: failedStatus, recovered: false },
    { name: 'the same pending target', status: { sections: { svc: section('pending') } }, recovered: false },
    { name: 'the same applying target', status: { sections: { svc: section('applying') } }, recovered: false },
    { name: 'the same unavailable target', status: { sections: { svc: section('unavailable') } }, recovered: false },
    { name: 'applied state without revision confirmation', status: { sections: { svc: section('applied', 7, 6) } }, recovered: false },
  ]
  describe.each(['read', 'acknowledgement'] as const)('%s reconciliation', source => {
    it.each(statuses)('reconciles only matching targets: $name', async ({ status, recovered }) => {
      const domain = useSettingsDomain()
      domain.acceptRuntimeStatus(failedStatus)
      await failRetry(domain)
      const error = domain.runtimeRetryRequest.error
      if (source === 'read') {
        vi.mocked(settingsClient.runtimeStatus).mockResolvedValueOnce(status)
        expect(await domain.loadRuntimeStatus()).toEqual(status)
      } else {
        domain.acceptRuntimeStatus(status)
      }
      expect(domain.runtimeReload.value).toEqual(status)
      expect(domain.runtimeRetryRequest.error).toBe(recovered ? null : error)
    })
  })

  it('waits for all failed targets and remembers targets already recovered', async () => {
    const domain = useSettingsDomain()
    await failRetry(domain, { svc: 7, llm: 3 })
    const error = domain.runtimeRetryRequest.error
    vi.mocked(settingsClient.runtimeStatus).mockResolvedValueOnce(appliedStatus)
    await domain.loadRuntimeStatus()
    expect(domain.runtimeRetryRequest.error).toBe(error)
    domain.acceptRuntimeStatus({ sections: { llm: section('pending', 4) } })
    expect(domain.runtimeRetryRequest.error).toBeNull()
  })

  it('preserves unrelated failures across successful and failed retries', async () => {
    const domain = useSettingsDomain()
    await failRetry(domain)
    vi.mocked(settingsClient.retryRuntime).mockResolvedValueOnce({ sections: { llm: section('applied', 3, 3) } })
    await domain.retryRuntime({ llm: 3 })
    expect(domain.runtimeRetryRequest.error).toContain('synthetic retry failure')
    await failRetry(domain, { llm: 4 }, 'LLM retry failure')
    domain.acceptRuntimeStatus(appliedStatus)
    expect(domain.runtimeRetryRequest.error).toBe('LLM retry failure')
    domain.acceptRuntimeStatus({ sections: { llm: section('applied', 4, 4) } })
    expect(domain.runtimeRetryRequest.error).toBeNull()
  })

  it('keeps a failed target until a successful retry confirms its recovery', async () => {
    const domain = useSettingsDomain()
    await failRetry(domain)
    vi.mocked(settingsClient.retryRuntime).mockResolvedValueOnce({ sections: { svc: section('pending') } })
    await domain.retryRuntime({ svc: 7 })
    expect(domain.runtimeRetryRequest.error).toContain('synthetic retry failure')
    vi.mocked(settingsClient.retryRuntime).mockResolvedValueOnce(appliedStatus)
    await domain.retryRuntime({ svc: 7 })
    expect(domain.runtimeRetryRequest.error).toBeNull()
  })

  it('does not treat a failed GET as recovery', async () => {
    const domain = useSettingsDomain()
    await failRetry(domain)
    const error = domain.runtimeRetryRequest.error
    vi.mocked(settingsClient.runtimeStatus).mockRejectedValueOnce(new Error('status unavailable'))
    await domain.loadRuntimeStatus()
    expect(domain.runtimeRetryRequest.error).toBe(error)
    expect(domain.runtimeStatusRequest.error).toBeTruthy()
  })

  it('reconciles save acknowledgements without clearing unrelated retry failures', async () => {
    const domain = useSettingsDomain()
    await failRetry(domain)
    const normalized = {} as Awaited<ReturnType<typeof settingsClient.load>>
    vi.mocked(settingsClient.save).mockResolvedValueOnce({ status: 'ok', normalized_settings: normalized, runtime_reload: { sections: { llm: section('pending', 9) } } })
    await domain.patchSettings({ llm: { model: 'new' } })
    expect(domain.runtimeRetryRequest.error).toContain('synthetic retry failure')
    vi.mocked(settingsClient.save).mockResolvedValueOnce({ status: 'ok', normalized_settings: normalized, runtime_reload: { sections: { svc: section('pending', 8) } } })
    await domain.patchSettings({ svc: { enabled: false } })
    expect(domain.runtimeRetryRequest.error).toBeNull()
  })

  it('binds failures to a snapshot of the requested revisions', async () => {
    const retry = deferred<RuntimeReloadStatusResponse>()
    vi.mocked(settingsClient.retryRuntime).mockReturnValueOnce(retry.promise)
    const domain = useSettingsDomain()
    const targets = { svc: 7 }
    const retrying = domain.retryRuntime(targets)
    targets.svc = 8
    retry.reject(new Error('synthetic retry failure'))
    await retrying
    expect(domain.runtimeRetryRequest.error).toBeTruthy()
    domain.acceptRuntimeStatus(appliedStatus)
    expect(domain.runtimeRetryRequest.error).toBeNull()
  })

  it('does not let a stale GET clear a newer retry failure', async () => {
    const status = deferred<RuntimeReloadStatusResponse>()
    vi.mocked(settingsClient.runtimeStatus).mockReturnValueOnce(status.promise)
    const domain = useSettingsDomain()
    const loading = domain.loadRuntimeStatus()
    await failRetry(domain)
    status.resolve(appliedStatus)
    expect(await loading).toBeNull()
    expect(domain.runtimeRetryRequest.error).toContain('synthetic retry failure')
  })

  it('does not let a late retry rejection restore an error after an applied GET', async () => {
    const retry = deferred<RuntimeReloadStatusResponse>()
    vi.mocked(settingsClient.retryRuntime).mockReturnValueOnce(retry.promise)
    const domain = useSettingsDomain()
    const retrying = domain.retryRuntime({ svc: 7 })
    vi.mocked(settingsClient.runtimeStatus).mockResolvedValueOnce(appliedStatus)
    await domain.loadRuntimeStatus()
    retry.reject(new Error('late retry failure'))
    expect(await retrying).toBeNull()
    expect(domain.runtimeReload.value).toEqual(appliedStatus)
    expect(domain.runtimeRetryRequest.error).toBeNull()
  })

  it.each(['resolve', 'reject'] as const)('invalidates an older retry %s after an acknowledgement without losing unrelated errors', async outcome => {
    const domain = useSettingsDomain()
    await failRetry(domain)
    const retry = deferred<RuntimeReloadStatusResponse>()
    vi.mocked(settingsClient.retryRuntime).mockReturnValueOnce(retry.promise)
    const retrying = domain.retryRuntime({ llm: 3 })
    const newer = { sections: { llm: section('pending', 4) } }
    domain.acceptRuntimeStatus(newer)
    if (outcome === 'resolve') retry.resolve(appliedStatus)
    else retry.reject(new Error('late LLM failure'))
    expect(await retrying).toBeNull()
    expect(domain.runtimeReload.value).toEqual(newer)
    expect(domain.runtimeRetryRequest.error).toBe('synthetic retry failure')
    expect(domain.runtimeRetryRequest.loading).toBe(false)
  })
})

it('clears a failed status query when a newer save acknowledges its target', async () => {
  const logging = vi.spyOn(console, 'error').mockImplementation(() => undefined)
  const domain = useSettingsDomain()
  vi.mocked(settingsClient.runtimeStatus).mockRejectedValue(new Error('status temporarily unavailable'))
  try {
    await domain.loadRuntimeStatus()
    expect(domain.runtimeStatusRequest.error).toBeTruthy()
    domain.acceptRuntimeStatus({ sections: { llm: { state: 'pending', target_revision: 5, applied_revision: null } } })
    expect(domain.runtimeStatusRequest.error).toBeNull()
  } finally { logging.mockRestore() }
})


it('uses additive normalized_settings without waiting for a GET', async () => {
  const normalized = { llm: { timeout: 120, api_key: '********' } } as Awaited<ReturnType<typeof settingsClient.load>>
  vi.mocked(settingsClient.save).mockResolvedValue({ status: 'ok', normalized_settings: normalized })
  vi.mocked(settingsClient.load).mockReturnValue(new Promise(() => {}))
  const domain = useSettingsDomain()
  const result = await domain.patchSettings({ llm: { timeout: 999 } })
  expect(result?.normalizedSettings).toEqual(normalized)
  expect(domain.settings.value).toEqual(normalized)
  expect(domain.settingsReadbackFailed.value).toBe(false)
  expect(settingsClient.load).not.toHaveBeenCalled()
})

it('does not replace newer normalized settings or runtime targets with an older ACK', async () => {
  const older = deferred<Awaited<ReturnType<typeof settingsClient.save>>>()
  const normalized = { llm: { timeout: 120 } } as Awaited<ReturnType<typeof settingsClient.load>>
  vi.mocked(settingsClient.save).mockReturnValueOnce(older.promise).mockResolvedValueOnce({ status: 'ok', normalized_settings: normalized, runtime_reload: { sections: {} } })
  const domain = useSettingsDomain()
  const saving = domain.patchSettings({ llm: { timeout: 999 } })
  await domain.patchSettings({ llm: { timeout: 120 } })
  older.resolve({ status: 'ok', normalized_settings: { llm: { timeout: 999 } } as typeof normalized, runtime_reload: { sections: { llm: { state: 'pending', target_revision: 1, applied_revision: null } } } })
  expect(await saving).toBeNull()
  expect(domain.settings.value).toEqual(normalized)
  expect(domain.runtimeReload.value).toEqual({ sections: {} })
  expect(settingsClient.load).not.toHaveBeenCalled()
})


describe('TTS operation acknowledgements and runtime ownership', () => {
  const ready = { available: true, provider: 'genie-tts' }
  const older = { available: false, provider: 'openai-compatible' }

  it.each(['resolve', 'reject'] as const)('invalidates older GET data/error/loading when warmup starts, including a late %s', async outcome => {
    const logging = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const status = deferred<typeof older>()
    const warmup = deferred<Awaited<ReturnType<typeof settingsClient.warmupTts>>>()
    vi.mocked(settingsClient.ttsStatus).mockResolvedValueOnce(older).mockReturnValueOnce(status.promise)
    vi.mocked(settingsClient.warmupTts).mockReturnValueOnce(warmup.promise)
    const domain = useSettingsDomain()
    try {
      await domain.loadTtsStatus()
      const loading = domain.loadTtsStatus()
      expect(domain.ttsStatusRequest.data).toEqual(older)
      expect(domain.ttsStatusRequest.loading).toBe(true)
      const warming = domain.warmupTts()
      expect(domain.ttsStatusRequest.data).toBeNull()
      expect(domain.ttsStatusRequest.error).toBeNull()
      expect(domain.ttsStatusRequest.loading).toBe(false)
      if (outcome === 'resolve') status.resolve(older)
      else status.reject(new Error('stale GET failed before warmup ACK'))
      expect(await loading).toBeNull()
      expect(domain.ttsStatusRequest.data).toBeNull()
      expect(domain.ttsStatusRequest.error).toBeNull()
      expect(domain.ttsStatusRequest.loading).toBe(false)
      const ack = { ok: true, queued: true, runtime: ready }
      warmup.resolve(ack)
      expect(await warming).toEqual(ack)
      expect(domain.ttsStatus.value).toEqual(ready)
      expect(domain.ttsStatusRequest.error).toBeNull()
    } finally { logging.mockRestore() }
  })

  it('clears a completed GET failure when warmup takes over', async () => {
    const logging = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    vi.mocked(settingsClient.ttsStatus).mockRejectedValueOnce(new Error('old GET failure'))
    vi.mocked(settingsClient.warmupTts).mockResolvedValueOnce({ ok: true, runtime: ready })
    const domain = useSettingsDomain()
    try {
      await domain.loadTtsStatus()
      expect(domain.ttsStatusRequest.error).toBeTruthy()
      expect(await domain.warmupTts()).toEqual({ ok: true, runtime: ready })
      expect(domain.ttsStatusRequest.error).toBeNull()
      expect(domain.ttsStatus.value).toEqual(ready)
    } finally { logging.mockRestore() }
  })

  it('retains a newer GET loading state and runtime when an older warmup acknowledges', async () => {
    const status = deferred<typeof older>()
    const warmup = deferred<Awaited<ReturnType<typeof settingsClient.warmupTts>>>()
    vi.mocked(settingsClient.ttsStatus).mockReturnValueOnce(status.promise)
    vi.mocked(settingsClient.warmupTts).mockReturnValueOnce(warmup.promise)
    const domain = useSettingsDomain()
    const warming = domain.warmupTts()
    const loading = domain.loadTtsStatus()
    const ack = { ok: true, queued: true, runtime: ready }
    warmup.resolve(ack)
    expect(await warming).toEqual(ack)
    expect(domain.ttsStatus.value).toBeNull()
    expect(domain.ttsStatusRequest.loading).toBe(true)
    status.resolve(older)
    expect(await loading).toEqual(older)
    expect(domain.ttsStatus.value).toEqual(older)
    expect(domain.ttsStatusRequest.data).toEqual(older)
    expect(domain.ttsStatusRequest.loading).toBe(false)
  })

  it.each(['load', 'save'] as const)('invalidates old GET state on settings %s while preserving the warmup ACK', async operation => {
    const logging = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const status = deferred<typeof older>()
    const warmup = deferred<Awaited<ReturnType<typeof settingsClient.warmupTts>>>()
    const normalized = { tts: { provider: 'openai-compatible' } } as Awaited<ReturnType<typeof settingsClient.load>>
    vi.mocked(settingsClient.ttsStatus).mockReturnValueOnce(status.promise)
    vi.mocked(settingsClient.warmupTts).mockReturnValueOnce(warmup.promise)
    vi.mocked(settingsClient.load).mockResolvedValueOnce(normalized)
    vi.mocked(settingsClient.save).mockResolvedValueOnce({ status: 'ok', normalized_settings: normalized })
    const domain = useSettingsDomain()
    try {
      const warming = domain.warmupTts()
      const loading = domain.loadTtsStatus()
      const updating = operation === 'load' ? domain.loadSettings() : domain.patchSettings({ tts: normalized.tts })
      expect(domain.ttsStatusRequest.loading).toBe(false)
      await updating
      status.reject(new Error('GET belongs to older settings'))
      expect(await loading).toBeNull()
      const ack = { ok: true, runtime: ready }
      warmup.resolve(ack)
      expect(await warming).toEqual(ack)
      expect(domain.ttsStatus.value).toBeNull()
      expect(domain.ttsStatusRequest.data).toBeNull()
      expect(domain.ttsStatusRequest.error).toBeNull()
      expect(domain.settings.value).toEqual(normalized)
    } finally { logging.mockRestore() }
  })
})
