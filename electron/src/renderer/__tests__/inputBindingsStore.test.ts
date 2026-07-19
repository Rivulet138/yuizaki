import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useInputBindingsStore } from '@/state/inputBindingsStore'

const snapshot = {
  settings: {
    pushToTalk: { enabled: true, mouseButton: 5 as const },
    keyboard: {
      interact: 'Control+Shift+P',
      lock: 'Control+Shift+L',
      openPanel: 'Control+Shift+O',
      toggleVision: 'Control+Alt+V',
    },
  },
  status: {
    mouseHookAvailable: true,
    pushToTalkActive: true,
    keyboard: { interact: true, lock: true, openPanel: true, toggleVision: true },
    errors: [],
  },
}

describe('inputBindingsStore', () => {
  const get = vi.fn(async () => structuredClone(snapshot))
  const update = vi.fn(async () => structuredClone({
    ...snapshot,
    settings: {
      ...snapshot.settings,
      pushToTalk: { enabled: true, mouseButton: 4 as const },
    },
  }))
  const reset = vi.fn(async () => structuredClone(snapshot))

  beforeEach(() => {
    get.mockClear()
    update.mockClear()
    reset.mockClear()
    Object.defineProperty(window, 'petApi', {
      configurable: true,
      value: { inputBindings: { get, update, reset } },
    })
  })

  it('loads the active desktop input registration status', async () => {
    const store = useInputBindingsStore()

    await store.load()

    expect(store.state.status.pushToTalkActive).toBe(true)
    expect(store.pushToTalkLabel.value).toBe('按住鼠标侧键 2')
  })

  it('applies updates returned by the Electron main process', async () => {
    const store = useInputBindingsStore()

    await store.update({ pushToTalk: { mouseButton: 4 } })

    expect(update).toHaveBeenCalledWith({ pushToTalk: { mouseButton: 4 } })
    expect(store.pushToTalkLabel.value).toBe('按住鼠标侧键 1')
  })
})
