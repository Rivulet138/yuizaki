import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { LocalRequestInit } from './http-client'

const controlUrl = 'http://localhost:38945/api/example'
const backendUrl = 'http://localhost:8001/api/example'
const jsonResponse = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status,
  headers: { 'Content-Type': 'application/json' },
})

beforeEach(() => vi.resetModules())
afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe.each(['json', 'blob'] as const)('%s HTTP client contract', (format) => {
  const loadRequest = async () => {
    const client = await import('./http-client')
    return (url: string, init?: LocalRequestInit) => format === 'json'
      ? client.requestJson(url, init)
      : client.requestBlob(url, init)
  }

  it('refreshes rejected credentials once and decodes a successful response', async () => {
    const request = await loadRequest()
    let bootstrapCount = 0
    const authHeaders: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/')) {
        bootstrapCount += 1
        return new Response(`<meta name="yuizaki-control-token" content="token-${bootstrapCount}">`)
      }
      if (url.endsWith('/api/system/env-check')) return jsonResponse({ pythonApiOrigin: 'http://localhost:8001' })
      authHeaders.push(new Headers(init?.headers).get('Authorization') || '')
      return authHeaders.length === 1 ? jsonResponse({ error: 'expired' }, 401) : jsonResponse({ ok: true })
    }))
    const result = await request(backendUrl)
    expect(authHeaders).toEqual(['Bearer token-1', 'Bearer token-2'])
    expect(bootstrapCount).toBe(2)
    expect(format === 'blob' ? JSON.parse(await (result as Blob).text()) : result).toEqual({ ok: true })
  })

  it.each([
    { payload: { error: 'Legacy failure description' }, expected: { message: 'Legacy failure description', code: 'Legacy failure description', retryable: false } },
    { payload: { detail: [{ msg: 'Field required' }] }, expected: { message: 'Field required', retryable: false } },
    { payload: { detail: 'Legacy detail description' }, expected: { message: 'Legacy detail description', retryable: false } },
    { payload: { detail: { error: 'recovery_expired' } }, expected: { message: 'recovery_expired', code: 'recovery_expired', retryable: false } },
    { payload: { detail: { code: 'busy', message: 'Try later', details: { operation_id: 'op-1' }, retryable: true, request_id: 'req-1' } }, expected: { code: 'busy', message: 'Try later', details: { operation_id: 'op-1' }, retryable: true, requestId: 'req-1' } },
    { payload: { code: 'canonical', message: 'Canonical message', details: null, retryable: false, request_id: 'canonical-id', detail: { code: 'old', error: 'Old error', message: 'Old message', details: { old: true }, retryable: true, request_id: 'old-id' } }, expected: { code: 'canonical', message: 'Canonical message', details: null, retryable: false, requestId: 'canonical-id' } },
    { payload: { code: 'busy', message: 'Try later', details: { operation_id: 'op-1' }, retryable: true, request_id: 'req-1' }, expected: { code: 'busy', message: 'Try later', details: { operation_id: 'op-1' }, retryable: true, requestId: 'req-1' } },
  ])('preserves server error fields: $payload', async ({ payload, expected }) => {
    const request = await loadRequest()
    const fetchMock = vi.fn(async () => jsonResponse(payload, 409))
    vi.stubGlobal('fetch', fetchMock)
    await expect(request(controlUrl)).rejects.toMatchObject({ ...expected, status: 409, requestPath: '/api/example', payload })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it.each(['timeout', 'caller'] as const)('distinguishes %s abort without retrying the request', async (reason) => {
    const request = await loadRequest()
    vi.useFakeTimers()
    const started = Promise.withResolvers<void>()
    const fetchMock = vi.fn((_url: string, init: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true })
      started.resolve()
    }))
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()
    const pending = request(controlUrl, { method: 'POST', signal: controller.signal, timeoutMs: 1_000 })
    const assertion = expect(pending).rejects.toMatchObject(reason === 'timeout'
      ? { code: 'request_timeout', message: expect.stringContaining('响应超时') }
      : { name: 'AbortError' })
    await started.promise
    if (reason === 'caller') controller.abort()
    else await vi.advanceTimersByTimeAsync(1_000)
    await assertion
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('keeps the local deadline active while a response body is delayed', async () => {
    const request = await loadRequest()
    vi.useFakeTimers()
    const body = Promise.withResolvers<unknown>()
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
      init?.signal?.addEventListener('abort', () => body.reject(new DOMException('Aborted', 'AbortError')), { once: true })
      return Promise.resolve({ ok: true, status: 200, headers: new Headers(), json: () => body.promise, blob: () => body.promise } as unknown as Response)
    })
    vi.stubGlobal('fetch', fetchMock)
    const pending = request(controlUrl, { timeoutMs: 1_000 })
    const assertion = expect(pending).rejects.toMatchObject({ code: 'request_timeout' })
    await Promise.resolve()
    await Promise.resolve()
    await vi.advanceTimersByTimeAsync(1_000)
    await assertion
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('cancels promptly while shared token bootstrap is still pending', async () => {
    const request = await loadRequest()
    const bootstrap = Promise.withResolvers<Response>()
    const fetchMock = vi.fn(() => bootstrap.promise)
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()
    const pending = request(backendUrl, { signal: controller.signal })
    const assertion = expect(pending).rejects.toMatchObject({ name: 'AbortError' })
    controller.abort()
    await assertion
    expect(fetchMock).toHaveBeenCalledTimes(1)
    bootstrap.resolve(new Response('<meta name="yuizaki-control-token" content="token">'))
    await bootstrap.promise
  })
})
