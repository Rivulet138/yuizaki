import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/i18n', () => ({ t: (key: string) => key }))

beforeEach(() => {
  vi.resetModules()
  vi.stubGlobal('window', { location: new URL('http://localhost:38945/') })
  vi.stubGlobal('document', { querySelector: () => null })
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('browser pet control transport', () => {
  it('uses the bounded shared transport for a stalled host request', async () => {
    vi.useFakeTimers()
    const started = Promise.withResolvers<void>()
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true })
      started.resolve()
    }))
    vi.stubGlobal('fetch', fetchMock)
    const { petControl } = await import('./petControl')
    const pending = petControl.getState()
    const assertion = expect(pending).rejects.toMatchObject({ code: 'request_timeout' })
    await started.promise
    expect(fetchMock.mock.calls[0]?.[1]?.signal).toBeInstanceOf(AbortSignal)
    await vi.advanceTimersByTimeAsync(12_000)
    await assertion
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('preserves structured host failures for panel error handling', async () => {
    const payload = { code: 'pet_renderer_busy', message: 'Renderer busy', retryable: true, request_id: 'pet-request' }
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(payload), {
      status: 409, headers: { 'Content-Type': 'application/json' },
    })))
    const { petControl } = await import('./petControl')
    await expect(petControl.getState()).rejects.toMatchObject({
      status: 409, code: 'pet_renderer_busy', message: 'Renderer busy', retryable: true, requestId: 'pet-request',
    })
  })

  it('keeps caller cancellation distinguishable from service failure', async () => {
    vi.stubGlobal('fetch', vi.fn((_url: string, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      if (init?.signal?.aborted) reject(new DOMException('Aborted', 'AbortError'))
      else init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true })
    })))
    const { petControl } = await import('./petControl')
    const controller = new AbortController()
    const pending = petControl.triggerMotion('Idle', 0, { source: 'automation', signal: controller.signal })
    const assertion = expect(pending).rejects.toMatchObject({ name: 'AbortError' })
    controller.abort()
    await assertion
  })

  it('retains the desktop IPC path without a host fetch', async () => {
    const state = { modelId: 'desktop-model' }
    vi.stubGlobal('window', { petApi: { pet: { getState: vi.fn(async () => state) } } })
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const { petControl } = await import('./petControl')
    await expect(petControl.getState()).resolves.toEqual(state)
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
