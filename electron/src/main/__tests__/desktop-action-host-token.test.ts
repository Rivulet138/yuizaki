import { describe, expect, it, vi } from 'vitest'

import { createAuthenticatedDesktopActionBackendPort } from '../desktop-action-bridge'

describe('desktop action host authentication', () => {
  it('fails closed without the dedicated token and never calls the backend', async () => {
    const fetchImpl = vi.fn()
    const port = createAuthenticatedDesktopActionBackendPort(
      'http://127.0.0.1:8001',
      '',
      fetchImpl as never,
    )

    await expect(port.status(new AbortController().signal)).resolves.toMatchObject({
      ok: false,
      code: 'DA_HOST_TOKEN_MISSING',
    })
    expect(fetchImpl).not.toHaveBeenCalled()
  })

  it('uses only the dedicated token on fixed desktop-action routes', async () => {
    const fetchImpl = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: vi.fn(async () => ({
        ok: true,
        enabled: false,
        window_actions_available: true,
        native_input_available: false,
      })),
    }))
    const port = createAuthenticatedDesktopActionBackendPort(
      'http://127.0.0.1:8001',
      'dedicated-desktop-token',
      fetchImpl as never,
    )

    await port.status(new AbortController().signal)

    expect(fetchImpl).toHaveBeenCalledWith(
      new URL('http://127.0.0.1:8001/api/desktop-actions/status'),
      expect.objectContaining({
        method: 'GET',
        headers: {
          Authorization: 'Bearer dedicated-desktop-token',
          'Content-Type': 'application/json',
        },
      }),
    )
    expect(JSON.stringify(fetchImpl.mock.calls)).not.toContain('general-token')
  })

  it('keeps lease renewal and application grants on fixed host-only requests', async () => {
    const fetchImpl = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: vi.fn(async () => ({ ok: true })),
    }))
    const port = createAuthenticatedDesktopActionBackendPort(
      'http://127.0.0.1:8001',
      'dedicated-desktop-token',
      fetchImpl as never,
    )
    const signal = new AbortController().signal

    await port.enable(signal)
    await port.heartbeat(signal, 17)
    await port.discover(signal)
    await port.grant(signal, 'das_app_opaque', 9)

    expect(fetchImpl.mock.calls.map(([url]) => String(url))).toEqual([
      'http://127.0.0.1:8001/api/desktop-actions/enable',
      'http://127.0.0.1:8001/api/desktop-actions/heartbeat',
      'http://127.0.0.1:8001/api/desktop-actions/discover',
      'http://127.0.0.1:8001/api/desktop-actions/grant',
    ])
    expect(fetchImpl.mock.calls.map(([, init]) => JSON.parse(String(init?.body)))).toEqual([
      { lease_ttl_seconds: 5 },
      { lease_epoch: 17, lease_ttl_seconds: 5 },
      { ttl_seconds: 15 },
      {
        app_id: 'das_app_opaque',
        discovery_revision: 9,
        allowed_actions: ['focus', 'request_close'],
        ttl_seconds: 30,
      },
    ])
    expect(fetchImpl.mock.calls.every(([, init]) => init?.headers?.Authorization === 'Bearer dedicated-desktop-token')).toBe(true)
  })

  it('preserves typed FastAPI error details for fail-closed handling', async () => {
    const port = createAuthenticatedDesktopActionBackendPort(
      'http://127.0.0.1:8001',
      'dedicated-desktop-token',
      vi.fn(async () => ({
        ok: false,
        status: 409,
        json: vi.fn(async () => ({ detail: { code: 'DA_HOST_LEASE_EPOCH_MISMATCH', message: 'lease epoch changed' } })),
      })) as never,
    )

    await expect(port.heartbeat(new AbortController().signal, 2)).resolves.toEqual({
      ok: false,
      nativeInputAvailable: false,
      code: 'DA_HOST_LEASE_EPOCH_MISMATCH',
      message: 'lease epoch changed',
    })
  })
})
