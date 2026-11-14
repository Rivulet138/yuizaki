import { beforeEach, describe, expect, it, vi } from 'vitest'
import { pluginClient } from '@/api/client'
import { usePluginDomain } from './usePluginDomain'

vi.mock('@/api/client', () => ({ pluginClient: { list: vi.fn(), cancelExecution: vi.fn() } }))
vi.mock('@/shared/errors/describe-error', () => ({ describeError: (error: Error) => error.message }))
const deferred = <T>() => {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(pluginClient.list).mockResolvedValue({ plugins: [], pluginStates: [], loadFailures: [], audit: [] } as never)
})

describe('plugin execution cancellation', () => {
  it('retains both successful results when two different executions are cancelled concurrently', async () => {
    const a = deferred<Awaited<ReturnType<typeof pluginClient.cancelExecution>>>()
    const b = deferred<Awaited<ReturnType<typeof pluginClient.cancelExecution>>>()
    vi.mocked(pluginClient.cancelExecution).mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise)
    const domain = usePluginDomain()
    const first = domain.cancelExecution('plugin', 'route', 'a')
    const second = domain.cancelExecution('plugin', 'route', 'b')
    a.resolve({ ok: true, invocationId: 'a', status: 'cancelled' })
    expect(await first).toBe(true)
    expect(domain.cancellingInvocationIds.value.has('b')).toBe(true)
    b.resolve({ ok: true, invocationId: 'b', status: 'cancelled' })
    expect(await second).toBe(true)
    expect(domain.cancellationStates.value).toEqual({ a: 'cancelled', b: 'cancelled' })
    expect(domain.cancellingInvocationIds.value.size).toBe(0)
  })

  it('keeps failures attached to their invocation and permits a retry', async () => {
    vi.mocked(pluginClient.cancelExecution).mockRejectedValueOnce(new Error('cancellation disabled'))
      .mockResolvedValueOnce({ ok: true, invocationId: 'a', status: 'cancelled' })
    const domain = usePluginDomain()
    expect(await domain.cancelExecution('plugin', 'route', 'a')).toBe(false)
    expect(domain.cancellationErrors.value.a).toBe('cancellation disabled')
    expect(domain.cancellingInvocationIds.value.size).toBe(0)
    expect(await domain.cancelExecution('plugin', 'route', 'a')).toBe(true)
    expect(domain.cancellationErrors.value.a).toBeUndefined()
  })
})
