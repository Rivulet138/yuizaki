import { describe, expect, it, vi } from 'vitest'
import { useDomainRequest } from './useDomainRequest'
vi.mock('@/shared/errors/describe-error', () => ({ describeError: (error: Error) => error.message }))
const deferred = <T>() => {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}
describe('useDomainRequest commit boundaries', () => {
  it('returns null for a late result so external refs keep the newer response', async () => {
    const request = useDomainRequest<string>()
    const slow = deferred<string>()
    let visible = ''
    const load = async (task: () => Promise<string>) => {
      const result = await request.execute(task)
      if (result && request.isCurrent(result)) visible = result
    }
    const first = load(() => slow.promise)
    await load(async () => 'B')
    expect(request.loading).toBe(false)
    slow.resolve('A')
    await first
    expect(visible).toBe('B')
    expect(request.data).toBe('B')
  })
  it('rechecks the commit boundary when reset occurs between result and consumer', async () => {
    const request = useDomainRequest<string>()
    const pending = request.execute(async () => 'stale')
    queueMicrotask(() => request.reset())
    const result = await pending
    expect(request.isCurrent(result)).toBe(false)
    expect(request.data).toBeNull()
  })
  it('a reset invalidates a pre-mutation read before the next refresh', async () => {
    const request = useDomainRequest<string[]>()
    const stale = deferred<string[]>()
    const pending = request.execute(() => stale.promise)
    request.reset()
    await request.execute(async () => [])
    stale.resolve(['deleted-record'])
    expect(await pending).toBeNull()
    expect(request.data).toEqual([])
  })
  it('finishing an obsolete request does not clear a newer loading state', async () => {
    const request = useDomainRequest<string>()
    const old = deferred<string>()
    const current = deferred<string>()
    const first = request.execute(() => old.promise)
    request.reset()
    const second = request.execute(() => current.promise)
    old.resolve('old')
    await first
    expect(request.loading).toBe(true)
    current.resolve('current')
    await second
    expect(request.loading).toBe(false)
  })
})
