import { afterEach, describe, expect, it, vi } from 'vitest'
import { API_ORIGIN, clearControlAuthToken, CONTROL_ORIGIN, requestJson } from '../api/clients/http-client'

describe('requestJson error normalization', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.unstubAllEnvs()
    clearControlAuthToken()
    delete (window as Window & { __YUIZAKI_CONTROL_TOKEN__?: string }).__YUIZAKI_CONTROL_TOKEN__
    document.querySelectorAll('meta[name="yuizaki-control-token"]').forEach((item) => item.remove())
    window.sessionStorage.clear()
    window.history.replaceState({}, '', '/')
  })

  it('uses FastAPI detail strings as the thrown message', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: vi.fn().mockResolvedValue({ detail: 'Invalid settings payload' }),
    }))

    await expect(requestJson('/api/settings/', { method: 'PATCH' })).rejects.toThrow('Invalid settings payload')
  })

  it('joins FastAPI validation detail arrays into a readable message', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: vi.fn().mockResolvedValue({ detail: [{ msg: 'Input should be a valid number' }, { msg: 'Extra inputs are not permitted' }] }),
    }))

    await expect(requestJson('/api/settings/', { method: 'PATCH' })).rejects.toThrow('Input should be a valid number; Extra inputs are not permitted')
  })

  it('preserves trace ids when callers provide custom headers', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ ok: true }),
    }))

    await requestJson('/api/settings/', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
    })

    expect(fetch).toHaveBeenCalledWith('/api/settings/', expect.objectContaining({
      headers: expect.objectContaining({
        'Content-Type': 'application/json',
        'x-trace-id': expect.stringMatching(/^trace_/),
      }),
    }))
  })

  it('consumes the backend token from the URL without attaching it to ControlServer requests', async () => {
    window.history.replaceState({}, '', '/?tab=settings&control_token=secret-control-token')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ ok: true }),
    }))

    await requestJson(`${CONTROL_ORIGIN}/api/settings/`)

    expect(fetch).toHaveBeenCalledWith(`${CONTROL_ORIGIN}/api/settings/`, expect.objectContaining({
      headers: expect.not.objectContaining({ Authorization: expect.anything() }),
    }))
    expect(window.location.href).not.toContain('control_token')
    expect(window.sessionStorage.getItem('yuizaki.control.token')).toBe('secret-control-token')
  })

  it('reuses the control token for protected Python API requests', async () => {
    window.sessionStorage.setItem('yuizaki.control.token', 'backend-token')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ ok: true }),
    }))

    await requestJson(`${API_ORIGIN}/api/workspaces`)

    expect(fetch).toHaveBeenCalledWith(`${API_ORIGIN}/api/workspaces`, expect.objectContaining({
      headers: expect.objectContaining({
        Authorization: 'Bearer backend-token',
      }),
    }))
  })

  it('prefers the injected control token over stale browser storage', async () => {
    window.sessionStorage.setItem('yuizaki.control.token', 'stale-token')
    ;(window as Window & { __YUIZAKI_CONTROL_TOKEN__?: string }).__YUIZAKI_CONTROL_TOKEN__ = 'injected-token'
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ ok: true }),
    }))

    await requestJson(`${API_ORIGIN}/api/workspaces`)

    expect(fetch).toHaveBeenCalledWith(`${API_ORIGIN}/api/workspaces`, expect.objectContaining({
      headers: expect.objectContaining({
        Authorization: 'Bearer injected-token',
      }),
    }))
    expect(window.sessionStorage.getItem('yuizaki.control.token')).toBe('injected-token')
  })

  it('does not attach the injected backend token to ControlServer requests', async () => {
    const meta = document.createElement('meta')
    meta.name = 'yuizaki-control-token'
    meta.content = 'bare-page-token'
    document.head.appendChild(meta)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ ok: true }),
    }))

    await requestJson(`${CONTROL_ORIGIN}/api/pet/catalog`)

    expect(fetch).toHaveBeenCalledWith(`${CONTROL_ORIGIN}/api/pet/catalog`, expect.objectContaining({
      headers: expect.not.objectContaining({ Authorization: expect.anything() }),
    }))
  })

  it('refreshes a stale injected token after a protected request returns 401', async () => {
    const meta = document.createElement('meta')
    meta.name = 'yuizaki-control-token'
    meta.content = 'stale-token'
    document.head.appendChild(meta)
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 401,
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: vi.fn().mockResolvedValue({ message: 'Unauthorized' }),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        text: vi.fn().mockResolvedValue('<!doctype html><meta name="yuizaki-control-token" content="fresh-token">'),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: vi.fn().mockResolvedValue({ pythonApiOrigin: 'http://localhost:8011' }),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: vi.fn().mockResolvedValue({ ok: true }),
      })
    vi.stubGlobal('fetch', fetchMock)

    await expect(requestJson(`${API_ORIGIN}/api/system/companion-runtime?limit=2`)).resolves.toEqual({ ok: true })

    expect(fetchMock).toHaveBeenNthCalledWith(1, `${CONTROL_ORIGIN}/api/system/env-check`, expect.objectContaining({
      headers: expect.objectContaining({
        Authorization: 'Bearer stale-token',
      }),
    }))
    expect(fetchMock).toHaveBeenNthCalledWith(2, `${API_ORIGIN}/api/system/companion-runtime?limit=2`, expect.objectContaining({
      headers: expect.objectContaining({
        Authorization: 'Bearer stale-token',
      }),
    }))
    expect(fetchMock).toHaveBeenNthCalledWith(3, `${CONTROL_ORIGIN}/`, expect.objectContaining({
      cache: 'no-store',
    }))
    expect(fetchMock).toHaveBeenNthCalledWith(4, `${CONTROL_ORIGIN}/api/system/env-check`, expect.objectContaining({
      headers: expect.objectContaining({
        Authorization: 'Bearer fresh-token',
      }),
    }))
    expect(fetchMock).toHaveBeenNthCalledWith(5, 'http://localhost:8011/api/system/companion-runtime?limit=2', expect.objectContaining({
      headers: expect.objectContaining({
        Authorization: 'Bearer fresh-token',
      }),
    }))
    expect(window.sessionStorage.getItem('yuizaki.control.token')).toBe('fresh-token')
    expect(document.querySelector<HTMLMetaElement>('meta[name="yuizaki-control-token"]')?.content).toBe('fresh-token')
  })

  it('bootstraps a control token before the first protected Python API request', async () => {
    window.history.replaceState({}, '', `/?control_origin=${encodeURIComponent(CONTROL_ORIGIN)}`)
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        text: vi.fn().mockResolvedValue('<!doctype html><meta name="yuizaki-control-token" content="fresh-token">'),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: vi.fn().mockResolvedValue({ pythonApiOrigin: 'http://localhost:8011' }),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: vi.fn().mockResolvedValue({ ok: true }),
      })
    vi.stubGlobal('fetch', fetchMock)

    await expect(requestJson(`${API_ORIGIN}/api/settings`)).resolves.toEqual({ ok: true })

    expect(fetchMock).toHaveBeenNthCalledWith(1, `${CONTROL_ORIGIN}/`, expect.objectContaining({
      cache: 'no-store',
    }))
    expect(fetchMock).toHaveBeenNthCalledWith(2, `${CONTROL_ORIGIN}/api/system/env-check`, expect.objectContaining({
      headers: expect.objectContaining({
        Authorization: 'Bearer fresh-token',
      }),
    }))
    expect(fetchMock).toHaveBeenNthCalledWith(3, 'http://localhost:8011/api/settings', expect.objectContaining({
      headers: expect.objectContaining({
        Authorization: 'Bearer fresh-token',
      }),
    }))
    expect(window.sessionStorage.getItem('yuizaki.control.token')).toBe('fresh-token')
  })

  it('explains missing authorization for protected Python API requests', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: vi.fn().mockResolvedValue({}),
    }))

    await expect(requestJson(`${API_ORIGIN}/api/workspaces`)).rejects.toThrow('重新打开界面')
  })

  it('sends control requests without bootstrapping or attaching a token', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))
    vi.stubGlobal('fetch', fetchMock)

    await expect(requestJson(`${CONTROL_ORIGIN}/api/pet/catalog`)).rejects.toThrow('本地服务')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock).toHaveBeenCalledWith(`${CONTROL_ORIGIN}/api/pet/catalog`, expect.objectContaining({
      headers: expect.not.objectContaining({ Authorization: expect.anything() }),
    }))
  })

  it('reports direct control connection failures from standalone browser pages', async () => {
    vi.stubEnv('VITE_YUIZAKI_CONTROL_ORIGIN', CONTROL_ORIGIN)
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))
    vi.stubGlobal('fetch', fetchMock)

    await expect(requestJson(`${CONTROL_ORIGIN}/api/pet/catalog`)).rejects.toThrow('无法连接本地服务')
    expect(fetchMock).toHaveBeenCalledOnce()
  })

  it('bounds local requests with a readable timeout error', async () => {
    vi.useFakeTimers()
    try {
      window.sessionStorage.setItem('yuizaki.control.token', 'local-token')
      vi.stubGlobal('fetch', vi.fn((_url: string, init?: RequestInit) => new Promise((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })))
      })))

      const requestPromise = expect(requestJson(`${CONTROL_ORIGIN}/api/system/mcp`)).rejects.toMatchObject({
        code: 'request_timeout',
        message: expect.stringContaining('本地服务响应超时'),
      })
      await vi.advanceTimersByTimeAsync(12000)

      await requestPromise
    } finally {
      vi.useRealTimers()
    }
  })

  it('does not start a backend fetch after cancellation during auth bootstrap', async () => {
    window.history.replaceState({}, '', `/?control_origin=${encodeURIComponent(CONTROL_ORIGIN)}`)
    const controller = new AbortController()
    let resolveBootstrap: ((response: Response) => void) | undefined
    const fetchMock = vi.fn((url: string) => {
      if (url === `${CONTROL_ORIGIN}/`) {
        return new Promise<Response>((resolve) => {
          resolveBootstrap = resolve
        })
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: vi.fn().mockResolvedValue({ ok: true }),
      } as Response)
    })
    vi.stubGlobal('fetch', fetchMock)

    const requestPromise = requestJson(`${API_ORIGIN}/api/pet/lipsync`, {
      method: 'POST',
      signal: controller.signal,
      body: JSON.stringify({ enabled: false }),
    })
    await Promise.resolve()
    controller.abort()
    resolveBootstrap?.({
      ok: true,
      status: 200,
      text: vi.fn().mockResolvedValue('<meta name="yuizaki-control-token" content="fresh-token">'),
    } as unknown as Response)

    await expect(requestPromise).rejects.toMatchObject({ name: 'AbortError' })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('allows long-running local operations to choose a route-specific timeout', async () => {
    vi.useFakeTimers()
    try {
      window.sessionStorage.setItem('yuizaki.control.token', 'local-token')
      let requestSignal: AbortSignal | undefined
      vi.stubGlobal('fetch', vi.fn((_url: string, init?: RequestInit) => new Promise((_resolve, reject) => {
        requestSignal = init?.signal ?? undefined
        requestSignal?.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })))
      })))

      const requestPromise = expect(requestJson(`${CONTROL_ORIGIN}/api/system/resources/embedding/prefetch`, {
        method: 'POST',
        timeoutMs: 60_000,
      })).rejects.toMatchObject({
        code: 'request_timeout',
        message: expect.stringContaining('60 秒'),
      })
      await vi.advanceTimersByTimeAsync(12_000)
      expect(requestSignal?.aborted).toBe(false)
      await vi.advanceTimersByTimeAsync(48_000)

      await requestPromise
    } finally {
      vi.useRealTimers()
    }
  })
})
