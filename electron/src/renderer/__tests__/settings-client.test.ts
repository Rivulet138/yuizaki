import { afterEach, describe, expect, it, vi } from 'vitest'
import { CONTROL_ORIGIN, clearControlAuthToken } from '../api/clients/http-client'
import { settingsClient } from '../api/clients/settings-client'

describe('settingsClient', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    clearControlAuthToken()
    window.sessionStorage.clear()
  })

  it('dedupes concurrent settings loads', async () => {
    window.sessionStorage.setItem('yuizaki.control.token', 'settings-token')
    const payload = {
      llm: { provider: 'custom', base_url: 'https://api.example/v1', api_key: '', model: 'gpt-test', temperature: 0.7, top_p: 1 },
      tts: {},
      asr: {},
      svc: {},
      summary: {},
      system: { language: 'zh-CN', theme: 'light' },
    }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue(payload),
    }))

    const [first, second] = await Promise.all([
      settingsClient.load(),
      settingsClient.load(),
    ])

    expect(first).toBe(payload)
    expect(second).toBe(payload)
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/settings/'), expect.any(Object))
  })

  it('posts inline LLM credentials when loading model options', async () => {
    window.sessionStorage.setItem('yuizaki.control.token', 'settings-token')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ ok: true, models: ['gpt-test'] }),
    }))

    const result = await settingsClient.listLlmModels({
      base_url: 'https://models.example/v1',
      api_key: 'test-key',
      timeout: 12,
    })

    expect(result.models).toEqual(['gpt-test'])
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/settings/llm/models'), expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({
        base_url: 'https://models.example/v1',
        api_key: 'test-key',
        timeout: 12,
      }),
      headers: expect.objectContaining({
        'Content-Type': 'application/json',
        'x-trace-id': expect.stringMatching(/^trace_/),
      }),
    }))
  })

  it('imports a JSON settings payload through the control server', async () => {
    window.sessionStorage.setItem('yuizaki.control.token', 'settings-token')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ status: 'imported', filepath: 'inline-upload', runtime_applied: ['llm'] }),
    }))

    const payload = { llm: { base_url: 'https://api.example/v1', api_key: '', model: 'gpt-test' } }
    const result = await settingsClient.importPayload(payload)

    expect(result.status).toBe('imported')
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/settings/import'), expect.objectContaining({
      method: 'POST',
      body: JSON.stringify(payload),
      headers: expect.objectContaining({
        'Content-Type': 'application/json',
        'x-trace-id': expect.stringMatching(/^trace_/),
      }),
    }))
  })

  it('exports settings through the authenticated control server request', async () => {
    window.sessionStorage.setItem('yuizaki.control.token', 'settings-token')
    const blob = new Blob(['{"ok":true}'], { type: 'application/json' })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      blob: vi.fn().mockResolvedValue(blob),
    }))

    const result = await settingsClient.exportBlob()

    expect(result).toBe(blob)
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/settings/export'), expect.objectContaining({
      cache: 'no-store',
      headers: expect.objectContaining({
        Authorization: 'Bearer settings-token',
        'x-trace-id': expect.stringMatching(/^trace_/),
      }),
    }))
  })

  it('queues TTS warmup through the authenticated control server', async () => {
    window.sessionStorage.setItem('yuizaki.control.token', 'tts-warmup-token')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ ok: true, queued: true, runtime: { warmup_running: true } }),
    }))

    const result = await settingsClient.warmupTts()

    expect(result.queued).toBe(true)
    expect(fetch).toHaveBeenCalledWith(`${CONTROL_ORIGIN}/api/settings/tts/warmup`, expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({
        Authorization: 'Bearer tts-warmup-token',
        'x-trace-id': expect.stringMatching(/^trace_/),
      }),
    }))
  })
})
