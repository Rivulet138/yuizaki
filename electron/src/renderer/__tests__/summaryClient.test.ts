import { afterEach, describe, expect, it, vi } from 'vitest'
import { CONTROL_ORIGIN, clearControlAuthToken } from '../api/clients/http-client'
import { summaryClient } from '../api/clients/summary-client'

describe('summaryClient exports', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    clearControlAuthToken()
    window.sessionStorage.clear()
  })

  it('attaches the backend bearer token to governance report downloads', async () => {
    window.sessionStorage.setItem('yuizaki.control.token', 'backend-token')
    const reportBlob = new Blob(['session_id,total\n'], { type: 'text/csv' })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      blob: vi.fn().mockResolvedValue(reportBlob),
    }))

    const blob = await summaryClient.exportGovernanceReport('csv', 3)

    expect(blob).toBe(reportBlob)
    expect(fetch).toHaveBeenCalledWith(`${CONTROL_ORIGIN}/api/summary/report/csv?days=3`, expect.objectContaining({
      headers: expect.objectContaining({
        Authorization: 'Bearer backend-token',
        'x-trace-id': expect.stringMatching(/^trace_/),
      }),
    }))
  })

  it('encodes summary governance query parameters', async () => {
    window.sessionStorage.setItem('yuizaki.control.token', 'summary-token')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ trends: [], alerts: [] }),
    }))

    await summaryClient.getGovernanceReport(14)
    await summaryClient.snoozeAlert('session/needs review', 45)

    expect(fetch).toHaveBeenNthCalledWith(1, `${CONTROL_ORIGIN}/api/summary/report/json?days=14`, expect.any(Object))
    expect(fetch).toHaveBeenNthCalledWith(2, `${CONTROL_ORIGIN}/api/summary/alerts/snooze?key=session%2Fneeds%20review&minutes=45`, expect.objectContaining({
      method: 'POST',
    }))
  })
})
