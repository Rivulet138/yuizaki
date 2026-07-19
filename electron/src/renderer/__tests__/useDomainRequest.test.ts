import { describe, expect, it } from 'vitest'
import { useDomainRequest } from '../shared/composables/useDomainRequest'

type Deferred<T> = {
  promise: Promise<T>
  resolve: (value: T) => void
  reject: (reason?: unknown) => void
}

const deferred = <T>(): Deferred<T> => {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

const nextTick = () => Promise.resolve()

describe('useDomainRequest', () => {
  it('keeps loading true for concurrent requests and only publishes the latest result', async () => {
    const request = useDomainRequest<string>()
    const slow = deferred<string>()
    const fast = deferred<string>()

    const slowResult = request.execute(() => slow.promise)
    const fastResult = request.execute(() => fast.promise)

    expect(request.loading).toBe(true)

    fast.resolve('latest')
    await nextTick()

    expect(await fastResult).toBe('latest')
    expect(request.data).toBe('latest')
    expect(request.loading).toBe(true)

    slow.resolve('stale')
    await slowResult
    await nextTick()

    expect(request.data).toBe('latest')
    expect(request.loading).toBe(false)
  })

  it('ignores stale errors from older requests', async () => {
    const request = useDomainRequest<string>()
    const slow = deferred<string>()
    const fast = deferred<string>()

    const slowResult = request.execute(() => slow.promise)
    const fastResult = request.execute(() => fast.promise)

    fast.resolve('latest')
    await fastResult

    slow.reject(new Error('stale failure'))
    await slowResult

    expect(request.data).toBe('latest')
    expect(request.error).toBeNull()
    expect(request.loading).toBe(false)
  })
  it('keeps post-reset requests isolated from older completions', async () => {
    const request = useDomainRequest<string>()
    const stale = deferred<string>()
    const current = deferred<string>()

    const staleResult = request.execute(() => stale.promise)
    request.reset()
    const currentResult = request.execute(() => current.promise)

    stale.resolve('stale')
    await staleResult
    await nextTick()

    expect(request.data).toBeNull()
    expect(request.loading).toBe(true)

    current.resolve('current')
    expect(await currentResult).toBe('current')
    await nextTick()

    expect(request.data).toBe('current')
    expect(request.loading).toBe(false)
  })
})