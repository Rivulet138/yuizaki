import { afterEach, describe, expect, it, vi } from 'vitest'
import { PetEmbodimentCoordinator } from '../pet-embodiment-coordinator'

describe('PetEmbodimentCoordinator', () => {
  afterEach(() => vi.useRealTimers())

  it('resolves speaking above reacting and restores the retained lower-priority state', async () => {
    vi.useFakeTimers()
    const applied: string[] = []
    const coordinator = new PetEmbodimentCoordinator({ applyBehavior: (state) => applied.push(state) })

    coordinator.requestBehavior('thinking')
    coordinator.requestBehavior('reacting', 500)
    coordinator.requestBehavior('speaking')
    expect(applied).toEqual(['thinking', 'reacting', 'speaking'])

    await vi.advanceTimersByTimeAsync(600)
    expect(applied).toEqual(['thinking', 'reacting', 'speaking'])

    coordinator.clearBehavior('speaking')
    expect(applied.at(-1)).toBe('thinking')
  })

  it('uses latest-wins epochs so stale behavior timers cannot override a refreshed state', async () => {
    vi.useFakeTimers()
    const applied: string[] = []
    const coordinator = new PetEmbodimentCoordinator({ applyBehavior: (state) => applied.push(state) })

    coordinator.requestBehavior('reacting', 100)
    await vi.advanceTimersByTimeAsync(50)
    coordinator.requestBehavior('reacting', 200)
    await vi.advanceTimersByTimeAsync(100)
    expect(applied.at(-1)).toBe('reacting')

    await vi.advanceTimersByTimeAsync(101)
    expect(applied.at(-1)).toBe('idle')
  })

  it('keeps visemes transient and ignores a stale explicit completion', async () => {
    vi.useFakeTimers()
    const resetTransient = vi.fn()
    const coordinator = new PetEmbodimentCoordinator({ applyBehavior: vi.fn(), resetTransient })

    const staleEpoch = coordinator.beginTransient('viseme', 100)
    const currentEpoch = coordinator.beginTransient('viseme', 250)
    coordinator.endTransient('viseme', staleEpoch)
    await vi.advanceTimersByTimeAsync(150)
    expect(resetTransient).not.toHaveBeenCalled()

    coordinator.endTransient('viseme', currentEpoch)
    expect(resetTransient).toHaveBeenCalledWith('viseme')
  })

  it('cancels only the requested command owner and restores retained state', () => {
    const applied: string[] = []
    const coordinator = new PetEmbodimentCoordinator({ applyBehavior: (state) => applied.push(state) })

    coordinator.requestBehavior('thinking', 0, 'thinking-command')
    coordinator.requestBehavior('speaking', 0, 'speech-command')
    coordinator.cancelOwner('speech-command', 'behavior')

    expect(applied).toEqual(['thinking', 'speaking', 'thinking'])
  })

  it('invalidates command timers on global cancel without clearing ownerless speech', async () => {
    vi.useFakeTimers()
    const applied: string[] = []
    const resetTransient = vi.fn()
    const coordinator = new PetEmbodimentCoordinator({
      applyBehavior: (state) => applied.push(state),
      resetTransient,
    })

    coordinator.requestBehavior('speaking')
    coordinator.requestBehavior('reacting', 100, 'reaction-command')
    coordinator.beginTransient('gaze', 100, 'reaction-command')
    coordinator.cancelCommandClaims()
    await vi.advanceTimersByTimeAsync(150)

    expect(applied).toEqual(['speaking'])
    expect(resetTransient).toHaveBeenCalledOnce()
  })

  it('resets active transients during disposal', () => {
    const resetTransient = vi.fn()
    const coordinator = new PetEmbodimentCoordinator({ applyBehavior: vi.fn(), resetTransient })
    coordinator.beginTransient('gaze')
    coordinator.beginTransient('viseme')

    coordinator.destroy()

    expect(resetTransient).toHaveBeenCalledWith('gaze')
    expect(resetTransient).toHaveBeenCalledWith('viseme')
  })
})
