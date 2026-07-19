import { beforeEach, describe, expect, it, vi } from 'vitest'
import { PetWindow } from '../window'

const electronMock = vi.hoisted(() => {
  const instances: Array<{
    options: Record<string, unknown>
    webContents: {
      on: ReturnType<typeof vi.fn>
      send: ReturnType<typeof vi.fn>
      emit: (event: string, ...args: unknown[]) => void
    }
    loadFile: ReturnType<typeof vi.fn>
    loadURL: ReturnType<typeof vi.fn>
    show: ReturnType<typeof vi.fn>
    focus: ReturnType<typeof vi.fn>
    hide: ReturnType<typeof vi.fn>
    on: ReturnType<typeof vi.fn>
  }> = []

  const BrowserWindow = vi.fn(function MockBrowserWindow(options: Record<string, unknown>) {
    const webContentsHandlers = new Map<string, (...args: unknown[]) => void>()
    const windowHandlers = new Map<string, (...args: unknown[]) => void>()
    const webContents = {
      on: vi.fn((event: string, handler: (...args: unknown[]) => void) => {
        webContentsHandlers.set(event, handler)
      }),
      send: vi.fn(),
      emit: (event: string, ...args: unknown[]) => webContentsHandlers.get(event)?.(...args),
    }
    const instance = {
      options,
      webContents,
      loadFile: vi.fn(async () => undefined),
      loadURL: vi.fn(async () => undefined),
      show: vi.fn(),
      focus: vi.fn(),
      hide: vi.fn(),
      isVisible: vi.fn(() => false),
      close: vi.fn(),
      on: vi.fn((event: string, handler: (...args: unknown[]) => void) => {
        windowHandlers.set(event, handler)
      }),
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

vi.mock('../app-icon', () => ({
  resolveAppIcon: vi.fn(() => undefined),
}))

vi.mock('../trusted-renderer-url', () => ({
  configureTrustedNavigation: vi.fn(),
  resolvePackagedRendererFile: vi.fn((entry: string) => `E:\\app\\renderer\\${entry}`),
  resolveTrustedDevServerUrl: vi.fn(() => null),
}))

describe('PetWindow', () => {
  beforeEach(() => {
    electronMock.instances.length = 0
    electronMock.BrowserWindow.mockClear()
  })

  it('creates a hidden usable panel with runtime service metadata', () => {
    const petWindow = new PetWindow()
    const window = petWindow.create({
      controlOrigin: 'http://localhost:38945',
      apiOrigin: 'http://localhost:8001',
      controlToken: 'control-token',
      tab: 'chat',
    })

    expect(electronMock.BrowserWindow).toHaveBeenCalledWith(expect.objectContaining({
      width: 1180,
      height: 780,
      show: false,
      webPreferences: expect.objectContaining({
        nodeIntegration: false,
        contextIsolation: true,
        sandbox: true,
      }),
    }))
    expect(window.loadFile).not.toHaveBeenCalled()
    expect(window.loadURL).toHaveBeenCalledWith(
      'yuizaki-app://renderer/index.html?control_origin=http%3A%2F%2Flocalhost%3A38945&api_origin=http%3A%2F%2Flocalhost%3A8001&control_token=control-token&tab=chat',
    )
  })

  it('queues shortcut messages until the renderer has finished loading', () => {
    const petWindow = new PetWindow()
    const window = petWindow.create()

    expect(petWindow.send('shortcut:toggle-mic')).toBe(true)
    expect(window.webContents.send).not.toHaveBeenCalled()

    window.webContents.emit('did-finish-load')

    expect(window.webContents.send).toHaveBeenCalledWith('shortcut:toggle-mic')
  })
})
