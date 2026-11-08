import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  isProactivePythonProxyRoute,
  isPythonBlobProxyPath,
  isPythonJsonProxyPath,
  proxyPythonJsonRequest,
  restoreVaultedLlmCredential,
} from './system-routes'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('control-server Python proxy route contract', () => {
  it('restores the vaulted key for remote LLM config edits that omit the unchanged key', () => {
    expect(restoreVaultedLlmCredential({
      llm: { provider: 'custom', base_url: 'https://provider.example/v1', api_key: '' },
    }, { 'llm.api_key': 'vaulted-key' })).toEqual({
      llm: { provider: 'custom', base_url: 'https://provider.example/v1', api_key: 'vaulted-key' },
    })
  })

  it.each([
    { provider: 'ollama', base_url: 'http://localhost:11434/v1' },
    { provider: 'custom', base_url: 'http://127.0.0.1:9000/v1' },
  ])('does not attach remote credentials to keyless local providers', (llm) => {
    expect(restoreVaultedLlmCredential({ llm: { ...llm, api_key: '' } }, {
      'llm.api_key': 'vaulted-key',
    })).toEqual({ llm: { ...llm, api_key: '' } })
  })

  it('exposes memory audit, export/import and rebuild job routes', () => {
    expect(isPythonJsonProxyPath('/memory/operations')).toBe(true)
    expect(isPythonJsonProxyPath('/memory/export')).toBe(true)
    expect(isPythonJsonProxyPath('/memory/import')).toBe(true)
    expect(isPythonJsonProxyPath('/memory/index/rebuild/job-1')).toBe(true)
    expect(isPythonJsonProxyPath('/memory/index/rebuild/job-1/cancel')).toBe(true)
    expect(isPythonJsonProxyPath('/memory/index/rebuild/job-1/retry')).toBe(true)
    expect(isPythonJsonProxyPath('/memory/index/rebuild/job-1/unknown')).toBe(false)
  })

  it('exposes activity-frame rebuild only for POST', () => {
    expect(isProactivePythonProxyRoute('POST', '/api/system/activity-frames/rebuild')).toBe(true)
    expect(isProactivePythonProxyRoute('GET', '/api/system/activity-frames/rebuild')).toBe(false)
  })

  it('keeps credential reload on the authenticated JSON proxy', () => {
    expect(isPythonJsonProxyPath('/api/settings/credentials/reload')).toBe(true)
    expect(isPythonBlobProxyPath('/api/settings/credentials/reload')).toBe(false)
  })

  it('keeps the proxy deadline active while reading the response body', async () => {
    vi.useFakeTimers()
    const body = Promise.withResolvers<string>()
    const fetchMock = vi.fn(async (_target: string, init?: RequestInit) => {
      init?.signal?.addEventListener('abort', () => body.reject(new DOMException('Aborted', 'AbortError')), { once: true })
      return { ok: true, status: 200, text: () => body.promise } as Response
    })
    vi.stubGlobal('fetch', fetchMock)

    const pending = proxyPythonJsonRequest('http://python.test/api/settings/test/svc', {}, '/api/settings/test/svc', 1_000)
    const assertion = expect(pending).rejects.toMatchObject({ name: 'AbortError' })
    await vi.advanceTimersByTimeAsync(1_000)

    await assertion
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
