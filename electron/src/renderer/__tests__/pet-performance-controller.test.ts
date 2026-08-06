import { afterEach, describe, expect, it, vi } from 'vitest'
import { PetPerformanceController } from '../pet-performance-controller'

describe('PetPerformanceController', () => {
  afterEach(() => vi.useRealTimers())

  it('uses one deadline timer and suspends the ticker while hidden', async () => {
    vi.useFakeTimers()
    let hidden = false
    const ticker = { start: vi.fn(), stop: vi.fn() }
    const onTierChange = vi.fn()
    const controller = new PetPerformanceController({
      ticker,
      isHidden: () => hidden,
      onTierChange,
      idleThresholdMs: 30_000,
    })

    controller.start()
    expect(ticker.start).toHaveBeenCalledOnce()
    expect(vi.getTimerCount()).toBe(1)

    await vi.advanceTimersByTimeAsync(10_000)
    controller.markActivity('pointer')
    expect(vi.getTimerCount()).toBe(1)
    await vi.advanceTimersByTimeAsync(20_000)
    expect(onTierChange).not.toHaveBeenCalledWith('idle', expect.any(String))
    expect(vi.getTimerCount()).toBe(1)

    hidden = true
    controller.syncVisibility()
    expect(ticker.stop).toHaveBeenCalledOnce()
    expect(vi.getTimerCount()).toBe(0)
    await vi.advanceTimersByTimeAsync(40_000)
    expect(onTierChange).not.toHaveBeenCalledWith('idle', expect.any(String))

    hidden = false
    controller.syncVisibility()
    expect(ticker.start).toHaveBeenCalledTimes(2)
    expect(onTierChange).toHaveBeenCalledWith('idle', 'idle-60s')

    controller.markActivity('visible-again')
    expect(onTierChange).toHaveBeenCalledWith('active', 'visible-again')
    expect(vi.getTimerCount()).toBe(1)
    controller.stop()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('does not restart after stop when a late visibility event arrives', () => {
    vi.useFakeTimers()
    const ticker = { start: vi.fn(), stop: vi.fn() }
    const controller = new PetPerformanceController({
      ticker,
      isHidden: () => false,
      onTierChange: vi.fn(),
      idleThresholdMs: 30_000,
    })

    controller.start()
    controller.stop()
    ticker.start.mockClear()
    controller.syncVisibility()

    expect(ticker.start).not.toHaveBeenCalled()
    expect(vi.getTimerCount()).toBe(0)
  })
})
