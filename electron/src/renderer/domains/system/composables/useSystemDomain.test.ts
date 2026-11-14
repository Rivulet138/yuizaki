import { beforeEach, describe, expect, it, vi } from 'vitest'
import { systemClient } from '@/api/client'
import { useSystemDomain } from './useSystemDomain'

vi.mock('@/api/client', () => ({ systemClient: {
  connectorDeliveries: vi.fn(), connectorAccount: vi.fn(), logoutConnectorAccount: vi.fn(), probeConnector: vi.fn(),
} }))
const deferred = <T>() => {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}
beforeEach(() => vi.resetAllMocks())

describe('connector snapshot isolation', () => {
  it('keeps deliveries and recovery for all four connectors loaded in parallel', async () => {
    const ids = ['telegram', 'discord', 'qq', 'wechat'] as const
    const pending = ids.map(() => deferred<any>())
    vi.mocked(systemClient.connectorDeliveries).mockImplementation((id) => pending[ids.indexOf(id)].promise)
    const domain = useSystemDomain()
    const loads = ids.map((id) => domain.loadConnectorDeliveries(id))
    for (const index of [3, 1, 2, 0]) {
      pending[index].resolve({ ok: true, connectorId: ids[index], items: [{ deliveryKey: ids[index] }], recovery: { nextRetryAt: index } })
    }
    const results = await Promise.all(loads)
    ids.forEach((id, index) => {
      expect(domain.connectorDeliveries.value[id]).toEqual([{ deliveryKey: id }])
      expect(domain.connectorRecovery.value[id]).toEqual({ nextRetryAt: index })
      expect(results[index]?.connectorId).toBe(id)
    })
  })

  it('keeps QQ and WeChat account results independent and loading until both finish', async () => {
    const qq = deferred<any>()
    const wechat = deferred<any>()
    vi.mocked(systemClient.connectorAccount).mockImplementation((id) => id === 'qq' ? qq.promise : wechat.promise)
    const domain = useSystemDomain()
    const loadingQq = domain.loadConnectorAccount('qq')
    const loadingWechat = domain.loadConnectorAccount('wechat')
    wechat.resolve({ ok: true, account: { connectorId: 'wechat', loginState: 'connected' } })
    await loadingWechat
    expect(domain.connectorAccountRequest.loading).toBe(true)
    qq.resolve({ ok: true, account: { connectorId: 'qq', loginState: 'logged_out' } })
    expect(await loadingQq).toEqual({ connectorId: 'qq', loginState: 'logged_out' })
    expect(Object.keys(domain.connectorAccounts.value).sort()).toEqual(['qq', 'wechat'])
    expect(domain.connectorAccountRequest.loading).toBe(false)
  })

  it('still rejects older deliveries for the same connector', async () => {
    const older = deferred<any>()
    vi.mocked(systemClient.connectorDeliveries).mockReturnValueOnce(older.promise).mockResolvedValueOnce({ ok: true, connectorId: 'qq', items: [{ deliveryKey: 'new' }] } as any)
    const domain = useSystemDomain()
    const loading = domain.loadConnectorDeliveries('qq')
    await domain.loadConnectorDeliveries('qq')
    older.resolve({ ok: true, connectorId: 'qq', items: [{ deliveryKey: 'old' }] })
    expect(await loading).toBeNull()
    expect(domain.connectorDeliveries.value.qq).toEqual([{ deliveryKey: 'new' }])
  })

  it('still rejects an older read for the same account after logout', async () => {
    const older = deferred<any>()
    vi.mocked(systemClient.connectorAccount).mockReturnValue(older.promise)
    vi.mocked(systemClient.logoutConnectorAccount).mockResolvedValue({ ok: true, account: { connectorId: 'qq', loginState: 'logged_out' } } as any)
    const domain = useSystemDomain()
    const loading = domain.loadConnectorAccount('qq')
    await domain.logoutConnectorAccount('qq')
    older.resolve({ ok: true, account: { connectorId: 'qq', loginState: 'connected' } })
    expect(await loading).toBeUndefined()
    expect(domain.connectorAccounts.value.qq.loginState).toBe('logged_out')
  })
})


describe('connector probe isolation', () => {
  it('retains all four parallel probes and aggregates loading until the last connector finishes', async () => {
    const ids = ['telegram', 'discord', 'qq', 'wechat'] as const
    const pending = ids.map(() => deferred<any>())
    vi.mocked(systemClient.probeConnector).mockImplementation((id) => pending[ids.indexOf(id)].promise)
    const domain = useSystemDomain()
    const probes = ids.map((id) => domain.probeConnector(id))
    for (const index of [3, 1, 2, 0]) {
      expect(domain.connectorProbeRequest.loading).toBe(true)
      const result = { ok: true, connectorId: ids[index], status: 'reachable' }
      pending[index].resolve(result)
      expect(await probes[index]).toEqual(result)
      expect(domain.connectorProbes.value[ids[index]]).toEqual(result)
    }
    expect(domain.connectorProbeRequest.loading).toBe(false)
    expect(domain.connectorProbeRequest.error).toBeNull()
  })

  it('rejects an older probe for the same connector without affecting another connector', async () => {
    const older = deferred<any>()
    vi.mocked(systemClient.probeConnector).mockReturnValueOnce(older.promise)
      .mockResolvedValueOnce({ ok: true, connectorId: 'wechat', status: 'reachable' } as any)
      .mockResolvedValueOnce({ ok: true, connectorId: 'qq', status: 'reachable' } as any)
    const domain = useSystemDomain()
    const oldProbe = domain.probeConnector('qq')
    await domain.probeConnector('wechat')
    await domain.probeConnector('qq')
    older.resolve({ ok: false, connectorId: 'qq', status: 'unreachable' })
    expect(await oldProbe).toBeNull()
    expect(domain.connectorProbes.value.qq?.status).toBe('reachable')
    expect(domain.connectorProbes.value.wechat?.status).toBe('reachable')
    expect(domain.connectorProbeRequest.loading).toBe(false)
  })

  it('keeps a connector failure visible when another connector completes successfully', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    try {
      const qq = deferred<any>()
      const wechat = deferred<any>()
      vi.mocked(systemClient.probeConnector).mockImplementation((id) => id === 'qq' ? qq.promise : wechat.promise)
      const domain = useSystemDomain()
      const one = domain.probeConnector('qq')
      const two = domain.probeConnector('wechat')
      qq.reject(new Error('QQ probe failed'))
      expect(await one).toBeNull()
      expect(domain.connectorProbeRequest.error).toContain('QQ probe failed')
      expect(domain.connectorProbeRequest.loading).toBe(true)
      wechat.resolve({ ok: true, connectorId: 'wechat', status: 'reachable' })
      await two
      expect(domain.connectorProbeRequest.error).toContain('QQ probe failed')
      expect(domain.connectorProbeRequest.loading).toBe(false)
    } finally {
      vi.mocked(console.error).mockRestore()
    }
  })
})
