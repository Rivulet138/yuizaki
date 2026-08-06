import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Live2DWindow } from '../live2d-window'

const fsMock = vi.hoisted(() => ({
  mkdir: vi.fn(async () => undefined),
  appendFile: vi.fn(async () => undefined),
}))

const electronMock = vi.hoisted(() => {
  const instances: Array<Record<string, any>> = []
  const BrowserWindow = vi.fn(function MockBrowserWindow() {
    const webContentsHandlers = new Map<string, (...args: unknown[]) => void>()
    const windowHandlers = new Map<string, (...args: unknown[]) => void>()
    let alwaysOnTop = false
    const instance = {
      webContentsHandlers,
      webContents: {
        on: vi.fn((event: string, handler: (...args: unknown[]) => void) => webContentsHandlers.set(event, handler)),
        send: vi.fn(),
        reload: vi.fn(),
        isDestroyed: vi.fn(() => false),
      },
      setVisibleOnAllWorkspaces: vi.fn(),
      setIgnoreMouseEvents: vi.fn(),
      isDestroyed: vi.fn(() => false),
      isAlwaysOnTop: vi.fn(() => alwaysOnTop),
      setAlwaysOnTop: vi.fn(() => { alwaysOnTop = true }),
      loadURL: vi.fn(async () => undefined),
      show: vi.fn(),
      hide: vi.fn(),
      close: vi.fn(),
      on: vi.fn((event: string, handler: (...args: unknown[]) => void) => windowHandlers.set(event, handler)),
    }
    instances.push(instance)
    return instance
  })
  return {
    BrowserWindow,
    instances,
    screen: {
      getPrimaryDisplay: vi.fn(() => ({
        workArea: { x: 0, y: 0, width: 1920, height: 1080 },
      })),
    },
  }
})

vi.mock('electron', () => ({
  BrowserWindow: electronMock.BrowserWindow,
  screen: electronMock.screen,
}))

vi.mock('node:fs', async (importOriginal) => {
  const actual = await importOriginal<typeof import('node:fs')>()
  return {
    ...actual,
    default: {
      ...actual,
      mkdirSync: vi.fn(),
      appendFileSync: vi.fn(),
      promises: {
        ...actual.promises,
        mkdir: fsMock.mkdir,
        appendFile: fsMock.appendFile,
      },
    },
  }
})

vi.mock('../app-icon', () => ({ resolveAppIcon: vi.fn(() => undefined) }))
vi.mock('../trusted-renderer-url', () => ({
  configureTrustedNavigation: vi.fn(),
  resolveTrustedDevServerUrl: vi.fn(() => null),
}))
vi.mock('../renderer-protocol', () => ({
  buildPackagedRendererUrl: vi.fn((entry: string) => `yuizaki-app://renderer/${entry}`),
}))

describe('Live2DWindow hardware lifecycle', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    electronMock.instances.length = 0
    electronMock.BrowserWindow.mockClear()
    fsMock.mkdir.mockClear()
    fsMock.appendFile.mockReset().mockResolvedValue(undefined)
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('runs the topmost guard only while the desktop pet is visible', async () => {
    const setIntervalSpy = vi.spyOn(globalThis, 'setInterval')
    const clearIntervalSpy = vi.spyOn(globalThis, 'clearInterval')
    const live2dWindow = new Live2DWindow()
    live2dWindow.show()
    expect(setIntervalSpy).not.toHaveBeenCalled()

    live2dWindow.create()

    expect(setIntervalSpy).not.toHaveBeenCalled()
    live2dWindow.hide()
    expect(clearIntervalSpy).not.toHaveBeenCalled()

    live2dWindow.show()
    live2dWindow.show()
    expect(setIntervalSpy).toHaveBeenCalledTimes(2)
    expect(clearIntervalSpy).toHaveBeenCalledTimes(1)

    live2dWindow.close()
    expect(clearIntervalSpy).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(100)
  })

  it('bounds and drains renderer logs through a single asynchronous writer', async () => {
    let activeWrites = 0
    let maxActiveWrites = 0
    let resolveFirstWrite: (() => void) | undefined
    fsMock.appendFile
      .mockImplementationOnce(() => new Promise<void>((resolve) => {
        activeWrites += 1
        maxActiveWrites = Math.max(maxActiveWrites, activeWrites)
        resolveFirstWrite = () => {
          activeWrites -= 1
          resolve()
        }
      }))
      .mockImplementation(async () => {
        activeWrites += 1
        maxActiveWrites = Math.max(maxActiveWrites, activeWrites)
        activeWrites -= 1
      })

    const live2dWindow = new Live2DWindow()
    live2dWindow.create()
    await vi.advanceTimersByTimeAsync(100)
    expect(fsMock.appendFile).toHaveBeenCalledTimes(1)

    const instance = electronMock.instances[0]
    const consoleHandler = instance?.webContentsHandlers.get('console-message')
    expect(consoleHandler).toBeTypeOf('function')
    for (let index = 0; index < 40; index += 1) {
      consoleHandler?.({
        level: 'info',
        message: `renderer-entry-${index}:${'x'.repeat(8192)}`,
        lineNumber: index,
        sourceId: 'pet-renderer.ts',
      })
    }
    expect(fsMock.appendFile).toHaveBeenCalledTimes(1)

    resolveFirstWrite?.()
    await Promise.resolve()
    await Promise.resolve()
    await vi.advanceTimersByTimeAsync(100)

    expect(fsMock.appendFile).toHaveBeenCalledTimes(2)
    expect(maxActiveWrites).toBe(1)
    expect(String(fsMock.appendFile.mock.calls[1]?.[1])).toContain('[renderer-log] dropped')
  })
})
