import { afterEach, describe, expect, it, vi } from 'vitest'
import { clearControlAuthToken } from '../api/clients/http-client'
import { i18nClient } from '../api/clients/i18n-client'

describe('i18nClient', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    clearControlAuthToken()
    window.sessionStorage.clear()
  })

  it('switches backend locale through the control server', async () => {
    window.sessionStorage.setItem('yuizaki.control.token', 'i18n-token')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ status: 'success', locale: 'en-US', message: 'ok' }),
    }))

    const result = await i18nClient.setLocale('en-US')

    expect(result.locale).toBe('en-US')
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/i18n/locale?locale=en-US'), expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ locale: 'en-US' }),
      headers: expect.objectContaining({
        'Content-Type': 'application/json',
        'x-trace-id': expect.stringMatching(/^trace_/),
      }),
    }))
  })

  it('looks up messages with the selected backend diagnostic locale', async () => {
    window.sessionStorage.setItem('yuizaki.control.token', 'i18n-token')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ message: '保存' }),
    }))

    await i18nClient.message('common.save', 'zh-CN')
    await i18nClient.errorMessage('errors.networkError', 'ja-JP')

    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/i18n/message/common.save?locale=zh-CN'), expect.any(Object))
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/api/i18n/error/errors.networkError?locale=ja-JP'), expect.any(Object))
  })
})
