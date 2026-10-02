import { createHmac } from 'node:crypto'
import axios from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PythonService } from './python'

vi.mock('axios', () => ({ default: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }))
vi.mock('electron', () => ({ safeStorage: {} }))

const token = 'test-backend-token'
const credentials = (value: string) => ({
  YUIZAKI_PROVIDER_CREDENTIALS_JSON: JSON.stringify({ 'llm.api_key': value }),
  YUIZAKI_TELEGRAM_BOT_TOKEN: value,
})
const createService = () => new PythonService(token, credentials('initial'), '', '', {
  startupMaxAttempts: 1,
  startupRetryDelayMs: 0,
  logOutput: false,
})

function deferred() {
  let resolve!: (value: unknown) => void
  let reject!: (reason: Error) => void
  const promise = new Promise((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

describe('externally managed Python lifecycle', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.stubEnv('DESKTOP_PET_SKIP_INTERNAL_PYTHON', '1')
    vi.mocked(axios.get).mockImplementation(async (url) => ({ data: {
      ok: true,
      runtime: {
        service: 'yuizaki-python-backend', version: 'launcher', instance_id: 'instance',
        generation: '1', startup_nonce: 'nonce',
      },
      runtime_proof: createHmac('sha256', token)
        .update(`yuizaki-backend-proof-v1:${new URL(url).searchParams.get('challenge')}`).digest('hex'),
    } }))
    vi.mocked(axios.post).mockResolvedValue({ data: { ok: true } })
    vi.mocked(axios.put).mockResolvedValue({ data: { ok: true } })
  })
  afterEach(() => vi.unstubAllEnvs())

  it('requires authenticated runtime health before sending any credentials', async () => {
    const service = createService()
    vi.mocked(axios.get).mockResolvedValueOnce({ data: { ok: true, runtime_proof: 'wrong' } })
    await expect(service.start()).rejects.toThrow('authenticated health check')
    expect(axios.post).not.toHaveBeenCalled()
    expect(axios.put).not.toHaveBeenCalled()
    await service.start()
    expect(service.getStatus().state).toBe('running')
    expect(axios.post).toHaveBeenCalledWith(expect.stringContaining('/credentials/reload'),
      { credentials: { 'llm.api_key': 'initial' } }, expect.objectContaining({
        headers: expect.objectContaining({ 'x-yuizaki-backend-token': token }),
      }))
  })

  it('drains updates during startup before declaring the service running', async () => {
    const service = createService()
    const pending = deferred()
    vi.mocked(axios.post).mockImplementationOnce(() => pending.promise)
    const start = service.start()
    await vi.waitFor(() => expect(axios.post).toHaveBeenCalledTimes(1))
    service.updateProviderCredentialEnvironment(credentials('new'))
    pending.resolve({ data: { ok: true } })
    await start
    expect(vi.mocked(axios.post).mock.calls.map((call) => call[1])).toEqual([
      { credentials: { 'llm.api_key': 'initial' } }, { credentials: { 'llm.api_key': 'new' } },
    ])
    expect(service.getStatus().state).toBe('running')
    const telegram = vi.mocked(axios.put).mock.calls.filter(([url]) => url.includes('/telegram/'))
    expect(telegram.map((call) => call[1].botToken)).toEqual(['initial', 'new'])
  })

  it.each(['resolve', 'reject'] as const)('serializes overlapping updates when the older connector request %ss', async (outcome) => {
    const service = createService()
    await service.start()
    vi.mocked(axios.post).mockClear()
    vi.mocked(axios.put).mockClear()
    const pending = deferred()
    vi.mocked(axios.put).mockImplementationOnce(() => pending.promise)
    service.updateProviderCredentialEnvironment(credentials('first'))
    await vi.waitFor(() => expect(axios.put).toHaveBeenCalledTimes(1))
    service.updateProviderCredentialEnvironment(credentials('second'))
    // The second provider write must wait for the first connector batch.
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(axios.post).toHaveBeenCalledTimes(1)
    if (outcome === 'reject') pending.reject(new Error('old request failed'))
    else pending.resolve({ data: { ok: true } })
    await vi.waitFor(() => expect(axios.put).toHaveBeenCalledTimes(outcome === 'reject' ? 6 : 10))
    const telegram = vi.mocked(axios.put).mock.calls.filter(([url]) => url.includes('/telegram/'))
    expect(telegram.map((call) => call[1].botToken)).toEqual(['first', 'second'])
    expect(service.getStatus().state).toBe('running')
  })

  it.each(['resolve', 'reject'] as const)('ignores a stopped generation when its provider request %ss', async (outcome) => {
    const service = createService()
    await service.start()
    vi.mocked(axios.post).mockClear()
    vi.mocked(axios.put).mockClear()
    const pending = deferred()
    vi.mocked(axios.post).mockImplementationOnce(() => pending.promise)
    service.updateProviderCredentialEnvironment(credentials('new'))
    await vi.waitFor(() => expect(axios.post).toHaveBeenCalledTimes(1))
    await service.stop()
    if (outcome === 'reject') pending.reject(new Error('request failed'))
    else pending.resolve({ data: { ok: true } })
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(axios.put).not.toHaveBeenCalled()
    expect(service.getStatus()).toMatchObject({ state: 'idle', error: null })
  })
})
