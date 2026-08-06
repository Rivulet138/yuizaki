import { describe, expect, it, vi } from 'vitest'

const electronMock = vi.hoisted(() => ({
  exposed: {} as Record<string, unknown>,
  send: vi.fn(),
  on: vi.fn(),
  removeListener: vi.fn(),
}))

vi.mock('electron', () => ({
  contextBridge: {
    exposeInMainWorld: (name: string, value: unknown) => {
      electronMock.exposed[name] = value
    },
  },
  ipcRenderer: {
    invoke: vi.fn(),
    send: electronMock.send,
    on: electronMock.on,
    removeListener: electronMock.removeListener,
  },
}))

describe('live2d preload subscriptions', () => {
  it('notifies the main process after renderer listeners are ready', async () => {
    await import('../live2d-preload')
    const api = electronMock.exposed['live2dApi'] as {
      pet: { rendererReady: () => void }
    }

    api.pet.rendererReady()

    expect(electronMock.send).toHaveBeenCalledWith('pet:renderer-ready')
  })

  it('removes the wrapped listener registered for a callback', async () => {
    await import('../live2d-preload')
    const api = electronMock.exposed['live2dApi'] as {
      on: (channel: string, callback: (...args: unknown[]) => void) => void
      off: (channel: string, callback: (...args: unknown[]) => void) => void
    }
    const callback = vi.fn()

    api.on('pet:apply-config', callback)
    const wrapped = electronMock.on.mock.calls[0]?.[1]
    expect(wrapped).toBeTypeOf('function')

    api.off('pet:apply-config', callback)
    expect(electronMock.removeListener).toHaveBeenCalledWith('pet:apply-config', wrapped)
  })
})
