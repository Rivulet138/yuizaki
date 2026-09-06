import { afterEach, describe, expect, it, vi } from 'vitest'
import { MousePttController, type MouseHookPort } from './mouse-ptt-controller'

type Listener = (event: { button: number }) => void

function createHook() {
  const listeners = new Map<string, Listener>()
  const hook: MouseHookPort = {
    on: vi.fn((event: string, listener: Listener) => { listeners.set(event, listener) }),
    off: vi.fn((event: string) => { listeners.delete(event) }),
    start: vi.fn(),
    stop: vi.fn(),
  }
  return { hook, emit: (event: string, button: number) => listeners.get(event)?.({ button }) }
}

afterEach(() => vi.useRealTimers())

describe('MousePttController', () => {
  it('loads and starts the hook only when explicitly started', async () => {
    const hook = createHook()
    const load = vi.fn(async () => hook.hook)
    const controller = new MousePttController(vi.fn(), vi.fn(), load)

    expect(load).not.toHaveBeenCalled()
    await expect(controller.start(4)).resolves.toBe(true)
    expect(load).toHaveBeenCalledOnce()
    expect(hook.hook.start).toHaveBeenCalledOnce()
  })

  it('starts voice for the configured button and releases on mouseup', async () => {
    const hook = createHook()
    const startVoice = vi.fn()
    const stopVoice = vi.fn()
    const controller = new MousePttController(startVoice, stopVoice, async () => hook.hook)
    await controller.start(4)

    hook.emit('mousedown', 3)
    expect(startVoice).not.toHaveBeenCalled()
    hook.emit('mousedown', 4)
    hook.emit('mousedown', 4)
    expect(startVoice).toHaveBeenCalledOnce()
    hook.emit('mouseup', 4)
    expect(stopVoice).toHaveBeenCalledOnce()
  })

  it('releases a stuck press at the safety timeout and stops idempotently', async () => {
    vi.useFakeTimers()
    const hook = createHook()
    const stopVoice = vi.fn()
    const controller = new MousePttController(vi.fn(), stopVoice, async () => hook.hook)
    await controller.start(4)
    hook.emit('mousedown', 4)
    vi.advanceTimersByTime(120_000)
    expect(stopVoice).toHaveBeenCalledOnce()
    controller.release()
    controller.stop()
    controller.stop()
    expect(hook.hook.stop).toHaveBeenCalledOnce()
  })

  it('cleans up when loading fails and exposes the error', async () => {
    const controller = new MousePttController(vi.fn(), vi.fn(), async () => { throw new Error('native unavailable') })
    await expect(controller.start(4)).resolves.toBe(false)
    expect(controller.getError()).toBe('native unavailable')
  })
})
