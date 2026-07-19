import { beforeEach, describe, expect, it, vi } from 'vitest'
import { PetShortcuts } from '../shortcuts'
import { DEFAULT_INPUT_BINDINGS } from '../../shared/input-bindings'

const electronMock = vi.hoisted(() => ({
  callbacks: new Map<string, () => void>(),
  register: vi.fn<(accelerator: string, callback: () => void) => boolean>(),
  unregister: vi.fn(),
}))

const hookMock = vi.hoisted(() => ({
  callbacks: new Map<string, (event: { button: number }) => void>(),
  on: vi.fn((event: string, callback: (payload: { button: number }) => void) => {
    hookMock.callbacks.set(event, callback)
  }),
  off: vi.fn((event: string) => {
    hookMock.callbacks.delete(event)
  }),
  start: vi.fn(),
  stop: vi.fn(),
}))

vi.mock('electron', () => ({
  globalShortcut: {
    register: electronMock.register,
    unregister: electronMock.unregister,
  },
}))

vi.mock('uiohook-napi', () => ({
  uIOhook: hookMock,
}))

vi.mock('../logger', () => ({
  logger: {
    info: vi.fn(),
    warn: vi.fn(),
  },
}))

const createShortcuts = () => {
  const handlers = {
    toggleInteract: vi.fn(),
    toggleLock: vi.fn(),
    openPanel: vi.fn(),
    startVoice: vi.fn(),
    stopVoice: vi.fn(),
    toggleVision: vi.fn(),
  }
  const shortcuts = new PetShortcuts(
    { toggleInteract: handlers.toggleInteract } as never,
    handlers.toggleLock,
    handlers.openPanel,
    handlers.startVoice,
    handlers.stopVoice,
    handlers.toggleVision,
  )
  return { shortcuts, handlers }
}

describe('PetShortcuts', () => {
  beforeEach(() => {
    electronMock.callbacks.clear()
    electronMock.register.mockReset()
    electronMock.unregister.mockReset()
    electronMock.register.mockImplementation((accelerator, callback) => {
      electronMock.callbacks.set(accelerator, callback)
      return true
    })
    hookMock.callbacks.clear()
    hookMock.on.mockClear()
    hookMock.off.mockClear()
    hookMock.start.mockReset()
    hookMock.stop.mockReset()
  })

  it('uses mouse side button 2 as hold-to-talk by default', () => {
    const { shortcuts, handlers } = createShortcuts()

    const status = shortcuts.register()
    hookMock.callbacks.get('mousedown')?.({ button: 5 })
    hookMock.callbacks.get('mousedown')?.({ button: 5 })
    hookMock.callbacks.get('mouseup')?.({ button: 5 })

    expect(status.pushToTalkActive).toBe(true)
    expect(handlers.startVoice).toHaveBeenCalledOnce()
    expect(handlers.stopVoice).toHaveBeenCalledOnce()
  })

  it('applies custom mouse and keyboard bindings immediately', () => {
    const { shortcuts, handlers } = createShortcuts()
    const settings = structuredClone(DEFAULT_INPUT_BINDINGS)
    settings.pushToTalk.mouseButton = 4
    settings.keyboard.openPanel = 'Control+Alt+Y'

    const status = shortcuts.register(settings)
    hookMock.callbacks.get('mousedown')?.({ button: 5 })
    hookMock.callbacks.get('mousedown')?.({ button: 4 })
    electronMock.callbacks.get('Control+Alt+Y')?.()
    electronMock.callbacks.get(DEFAULT_INPUT_BINDINGS.keyboard.toggleVision)?.()

    expect(status.keyboard.openPanel).toBe(true)
    expect(handlers.startVoice).toHaveBeenCalledOnce()
    expect(handlers.openPanel).toHaveBeenCalledOnce()
    expect(handlers.toggleVision).toHaveBeenCalledOnce()
  })

  it('reports occupied keyboard accelerators without disabling push-to-talk', () => {
    electronMock.register.mockImplementation((accelerator, callback) => {
      electronMock.callbacks.set(accelerator, callback)
      return accelerator !== DEFAULT_INPUT_BINDINGS.keyboard.lock
    })
    const { shortcuts } = createShortcuts()

    const status = shortcuts.register()

    expect(status.keyboard.lock).toBe(false)
    expect(status.pushToTalkActive).toBe(true)
    expect(status.errors).toContain(`lock shortcut unavailable: ${DEFAULT_INPUT_BINDINGS.keyboard.lock}`)
  })

  it('reports invalid accelerators without crashing the main process', () => {
    electronMock.register.mockImplementation((accelerator, callback) => {
      if (accelerator === DEFAULT_INPUT_BINDINGS.keyboard.interact) {
        throw new Error('invalid accelerator')
      }
      electronMock.callbacks.set(accelerator, callback)
      return true
    })
    const { shortcuts } = createShortcuts()

    const status = shortcuts.register()

    expect(status.keyboard.interact).toBe(false)
    expect(status.pushToTalkActive).toBe(true)
    expect(status.errors).toContain(
      `interact shortcut invalid: ${DEFAULT_INPUT_BINDINGS.keyboard.interact} (invalid accelerator)`,
    )
  })

  it('releases active voice input and unregisters owned bindings during shutdown', () => {
    const { shortcuts, handlers } = createShortcuts()
    shortcuts.register()
    hookMock.callbacks.get('mousedown')?.({ button: 5 })

    shortcuts.unregister()

    expect(handlers.stopVoice).toHaveBeenCalledOnce()
    expect(hookMock.stop).toHaveBeenCalledOnce()
    expect(electronMock.unregister).toHaveBeenCalledTimes(4)
  })
})
