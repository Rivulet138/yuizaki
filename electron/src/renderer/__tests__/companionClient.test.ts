import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useCompanionStore } from '../stores/companionStore'
import { companionClient } from '../api/clients/companion-client'
import { CONTROL_ORIGIN, clearControlAuthToken } from '../api/clients/http-client'

describe('companionClient', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    clearControlAuthToken()
    window.sessionStorage.clear()
  })

  it('routes companion management through the Electron control server', async () => {
    window.sessionStorage.setItem('yuizaki.control.token', 'companion-token')
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ companions: [], id: 'default' }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await companionClient.list()
    await companionClient.update('default', { name: 'Yui' })
    await companionClient.relationshipHistory('default', 5)

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      `${CONTROL_ORIGIN}/api/companions`,
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer companion-token' }),
      }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      `${CONTROL_ORIGIN}/api/companions/default`,
      expect.objectContaining({
        method: 'PATCH',
        headers: expect.objectContaining({
          Authorization: 'Bearer companion-token',
          'Content-Type': 'application/json',
        }),
      }),
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      `${CONTROL_ORIGIN}/api/companions/default/relationship-history?limit=5`,
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer companion-token' }),
      }),
    )
  })

  it('encodes companion IDs in dynamic control routes', async () => {
    window.sessionStorage.setItem('yuizaki.control.token', 'encoded-companion-token')
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ id: '桌宠/yui alpha' }),
    })
    vi.stubGlobal('fetch', fetchMock)

    await companionClient.get('桌宠/yui alpha')
    await companionClient.update('桌宠/yui alpha', { name: 'Yui' })
    await companionClient.remove('桌宠/yui alpha')
    await companionClient.relationshipHistory('桌宠/yui alpha', 8)

    expect(fetchMock).toHaveBeenNthCalledWith(1, `${CONTROL_ORIGIN}/api/companions/%E6%A1%8C%E5%AE%A0%2Fyui%20alpha`, expect.any(Object))
    expect(fetchMock).toHaveBeenNthCalledWith(2, `${CONTROL_ORIGIN}/api/companions/%E6%A1%8C%E5%AE%A0%2Fyui%20alpha`, expect.objectContaining({ method: 'PATCH' }))
    expect(fetchMock).toHaveBeenNthCalledWith(3, `${CONTROL_ORIGIN}/api/companions/%E6%A1%8C%E5%AE%A0%2Fyui%20alpha`, expect.objectContaining({ method: 'DELETE' }))
    expect(fetchMock).toHaveBeenNthCalledWith(4, `${CONTROL_ORIGIN}/api/companions/%E6%A1%8C%E5%AE%A0%2Fyui%20alpha/relationship-history?limit=8`, expect.any(Object))
  })

  it('keeps companion store stable when the control server returns a malformed list payload', async () => {
    window.sessionStorage.setItem('yuizaki.control.token', 'companion-token')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ ok: true }),
    }))

    const store = useCompanionStore()

    await store.loadCompanions()

    expect(store.companions).toEqual([])
    expect(store.activeCompanionId).toBe('default')
  })
})
