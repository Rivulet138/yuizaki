import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Live2DWindow } from '../live2d-window'
import { DEFAULT_PET_CONTROL_STATE } from '../../shared/pet-control'

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
      getBounds: vi.fn(() => ({ x: 0, y: 0, width: 1920, height: 1080 })),
      setBounds: vi.fn(),
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
        id: 1,
        workArea: { x: 0, y: 0, width: 1920, height: 1080 },
      })),
      getAllDisplays: vi.fn(() => []),
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

  it('creates a physical fullscreen work-area window and follows the selected display', async () => {
    electronMock.screen.getPrimaryDisplay.mockReturnValue({
      id: 1,
      workArea: { x: 0, y: 0, width: 1920, height: 1040 },
    })
    electronMock.screen.getAllDisplays.mockReturnValue([
      {
        id: 2,
        workArea: { x: -1600, y: 40, width: 1600, height: 900 },
      },
    ])
    const live2dWindow = new Live2DWindow()
    live2dWindow.create()

    expect(electronMock.BrowserWindow).toHaveBeenCalledWith(expect.objectContaining({
      x: 0,
      y: 0,
      width: 1920,
      height: 1040,
      transparent: true,
      frame: false,
    }))

    const instance = electronMock.instances[0]
    instance?.getBounds.mockReturnValue({ x: 0, y: 0, width: 1920, height: 1040 })
    const layout = live2dWindow.applyWindowLayout({
      ...DEFAULT_PET_CONTROL_STATE,
      displayId: 2,
    })

    expect(instance?.setBounds).toHaveBeenCalledWith({
      x: -1600,
      y: 40,
      width: 1600,
      height: 900,
    }, false)
    expect(layout?.displayId).toBe(2)
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

  it.each([
    ['live2d', 'live2d:local:shizuku', 'E:/models/shizuku/shizuku.model3.json'],
    ['vrm', 'vrm:local:avatar', 'E:/models/avatar/avatar.vrm'],
  ] as const)('restores the persisted %s model only after the renderer is ready', (modelType, modelId, modelPath) => {
    const live2dWindow = new Live2DWindow()
    live2dWindow.create()
    live2dWindow.applyPetConfig({
      modelType,
      modelId,
      modelPath,
      scale: 0.82,
      placement: 'bottom-left',
      lipSyncProfile: { inputGain: 1.25 },
    })

    const instance = electronMock.instances[0]
    instance?.webContentsHandlers.get('did-finish-load')?.()
    expect(instance?.webContents.send).not.toHaveBeenCalledWith('pet:apply-config', expect.anything())

    expect(live2dWindow.handleRendererReady({} as never)).toBe(false)
    expect(instance?.webContents.send).not.toHaveBeenCalledWith('pet:apply-config', expect.anything())

    expect(live2dWindow.handleRendererReady(instance?.webContents as never)).toBe(true)
    expect(instance?.webContents.send).toHaveBeenCalledWith('pet:apply-config', expect.objectContaining({
      modelType,
      modelId,
      modelPath,
      scale: 0.82,
      placement: 'bottom-left',
      lipSyncProfile: { inputGain: 1.25 },
    }))

    instance?.webContents.send.mockClear()
    expect(live2dWindow.handleRendererReady(instance?.webContents as never)).toBe(true)
    expect(instance?.webContents.send).not.toHaveBeenCalled()
  })

  it.each([
    ['main-frame reload', 'did-start-navigation', [{ isMainFrame: true, isSameDocument: false }]],
    ['renderer recovery', 'render-process-gone', [{}, { reason: 'crashed', exitCode: 1 }]],
  ] as const)('restores the model again after %s', (_label, eventName, eventArgs) => {
    const live2dWindow = new Live2DWindow()
    live2dWindow.create()
    live2dWindow.applyPetConfig({
      modelType: 'live2d',
      modelId: 'live2d:local:shizuku',
      modelPath: 'E:/models/shizuku/shizuku.model3.json',
    })

    const instance = electronMock.instances[0]
    live2dWindow.handleRendererReady(instance?.webContents as never)
    instance?.webContents.send.mockClear()

    live2dWindow.handleAvatarCapabilities(instance?.webContents as never, {
      revision: 'live2d:model-a:1',
      modelType: 'live2d',
      modelId: 'live2d:local:shizuku',
      generatedAt: Date.now(),
      actions: {},
      expressions: [],
      motions: [],
      parameters: [],
    })
    expect(live2dWindow.getAvatarCapabilities()).not.toBeNull()

    instance?.webContentsHandlers.get(eventName)?.(...eventArgs)
    expect(live2dWindow.getAvatarCapabilities()).toBeNull()
    expect(live2dWindow.handleRendererReady(instance?.webContents as never)).toBe(true)
    expect(instance?.webContents.send).toHaveBeenCalledWith('pet:apply-config', expect.objectContaining({
      modelId: 'live2d:local:shizuku',
      modelPath: 'E:/models/shizuku/shizuku.model3.json',
    }))
  })

  it('drops pending avatar commands immediately when the renderer reloads', async () => {
    const live2dWindow = new Live2DWindow()
    live2dWindow.create()
    const instance = electronMock.instances[0]
    live2dWindow.handleRendererReady(instance?.webContents as never)
    live2dWindow.handleAvatarCapabilities(instance?.webContents as never, {
      revision: 'live2d:model-a:1',
      modelType: 'live2d',
      modelId: 'model-a',
      generatedAt: Date.now(),
      actions: {},
      expressions: [],
      motions: [],
      parameters: [],
    })

    const resultPromise = live2dWindow.sendAvatarCommand({
      version: 1,
      id: 'reload-command',
      sequence: 1,
      issuedAt: Date.now(),
      priority: 50,
      interrupt: 'replace',
      actions: [{ type: 'behavior', behavior: 'idle' }],
    })

    instance?.webContentsHandlers.get('did-start-navigation')?.({
      isMainFrame: true,
      isSameDocument: false,
    })

    await expect(resultPromise).resolves.toMatchObject({
      commandId: 'reload-command',
      status: 'dropped',
      message: 'Pet renderer navigation interrupted the avatar command',
    })
    expect(live2dWindow.getAvatarCapabilities()).toBeNull()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('rejects duplicate in-flight avatar command ids without replacing the original waiter', async () => {
    const live2dWindow = new Live2DWindow()
    live2dWindow.create()
    const instance = electronMock.instances[0]
    live2dWindow.handleRendererReady(instance?.webContents as never)
    const command = {
      version: 1 as const,
      id: 'duplicate-command',
      sequence: 2,
      issuedAt: Date.now(),
      priority: 50,
      interrupt: 'replace' as const,
      actions: [{ type: 'behavior' as const, behavior: 'think' as const }],
    }

    const firstResult = live2dWindow.sendAvatarCommand(command)
    await expect(live2dWindow.sendAvatarCommand(command)).resolves.toMatchObject({
      commandId: 'duplicate-command',
      status: 'rejected',
      message: 'Avatar command id is already pending',
    })

    expect(live2dWindow.handleAvatarCommandResult(instance?.webContents as never, {
      commandId: 'duplicate-command',
      sequence: 1,
      status: 'completed',
      at: Date.now(),
    })).toBe(false)

    expect(live2dWindow.handleAvatarCommandResult(instance?.webContents as never, {
      commandId: 'duplicate-command',
      sequence: 2,
      status: 'completed',
      at: Date.now(),
    })).toBe(true)
    await expect(firstResult).resolves.toMatchObject({ status: 'completed' })
    expect(vi.getTimerCount()).toBe(0)
  })

  it('reports a transport timeout distinctly from a renderer-side drop', async () => {
    const live2dWindow = new Live2DWindow()
    live2dWindow.create()
    const instance = electronMock.instances[0]
    live2dWindow.handleRendererReady(instance?.webContents as never)

    const resultPromise = live2dWindow.sendAvatarCommand({
      version: 1,
      id: 'timeout-command',
      streamId: 'test-stream',
      sequence: 3,
      issuedAt: Date.now(),
      priority: 50,
      interrupt: 'replace',
      actions: [{ type: 'behavior', behavior: 'idle' }],
    })

    await vi.advanceTimersByTimeAsync(1200)
    await expect(resultPromise).resolves.toMatchObject({
      commandId: 'timeout-command',
      status: 'timeout',
    })
  })

  it('waits for the Live2D media request-start acknowledgement', async () => {
    const live2dWindow = new Live2DWindow()
    live2dWindow.create()
    const instance = electronMock.instances[0]
    live2dWindow.handleRendererReady(instance?.webContents as never)

    let settled = false
    const resultPromise = live2dWindow.startLipSync('https://fixture.test/audio.wav')
      .then(() => { settled = true })
    const startCall = instance?.webContents.send.mock.calls
      .find((call: unknown[]) => call[0] === 'pet:lipsync-start')
    const payload = startCall?.[1] as { requestId?: string } | undefined
    expect(payload?.requestId).toEqual(expect.any(String))
    await Promise.resolve()
    expect(settled).toBe(false)

    expect(live2dWindow.handleLipSyncReady(instance?.webContents as never, {
      requestId: payload?.requestId,
      ready: true,
    })).toBe(true)
    await resultPromise
    expect(settled).toBe(true)
    expect(vi.getTimerCount()).toBe(0)
  })
})
