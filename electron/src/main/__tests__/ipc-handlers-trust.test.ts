import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { IpcContext } from '../ipc-handlers'
import { buildPackagedRendererUrl } from '../renderer-protocol'
import { DEFAULT_PET_CONTROL_STATE } from '../../shared/pet-control'

const electronMock = vi.hoisted(() => {
  const handlers = new Map<string, (...args: unknown[]) => unknown>()
  const listeners = new Map<string, (...args: unknown[]) => unknown>()
  return {
    handlers,
    listeners,
    ipcMain: {
      handle: vi.fn((channel: string, handler: (...args: unknown[]) => unknown) => {
        handlers.set(channel, handler)
      }),
      on: vi.fn((channel: string, listener: (...args: unknown[]) => unknown) => {
        listeners.set(channel, listener)
      }),
    },
    screen: {
      getPrimaryDisplay: vi.fn(() => ({ workArea: { x: 0, y: 0, width: 1920, height: 1080 } })),
      getAllDisplays: vi.fn(() => []),
    },
    nativeImage: {
      createFromBuffer: vi.fn(),
      createFromBitmap: vi.fn(),
    },
    shell: {
      openExternal: vi.fn(),
    },
    app: {
      getAppMetrics: vi.fn(() => []),
    },
  }
})

const pythonOriginMock = vi.hoisted(() => ({
  resolvePythonApiOrigin: vi.fn(() => 'http://127.0.0.1:8001'),
}))

vi.mock('electron', () => ({
  ipcMain: electronMock.ipcMain,
  nativeImage: electronMock.nativeImage,
  screen: electronMock.screen,
  shell: electronMock.shell,
  app: electronMock.app,
}))

vi.mock('../http/python-origin', () => pythonOriginMock)

const buildIpcContext = (): IpcContext => {
  const state = {
    ...DEFAULT_PET_CONTROL_STATE,
    positionX: 100,
    positionY: 100,
  }
  return {
    live2dWindow: {
      sendToRenderer: vi.fn(),
      setInteractMode: vi.fn(),
      setLocked: vi.fn(),
      setClickThrough: vi.fn(),
      toggleInteract: vi.fn(() => true),
      setMousePassthrough: vi.fn(),
      getBounds: vi.fn(() => null),
      show: vi.fn(),
      hide: vi.fn(),
      reloadRenderer: vi.fn(),
      requestPetState: vi.fn(),
      handleRendererReady: vi.fn(() => true),
    },
    petWindow: {
      window: null,
    },
    petStateStore: {
      getState: vi.fn(() => ({ ...state, lipSyncProfile: { ...state.lipSyncProfile } }) as never),
      applyConfigPatch: vi.fn((patch: Record<string, unknown>) => {
        Object.assign(state, patch)
        return { ...state, lipSyncProfile: { ...state.lipSyncProfile } }
      }),
      setReady: vi.fn(),
      setInteractMode: vi.fn((enabled: boolean) => {
        Object.assign(state, { interactMode: enabled })
        return { ...state, lipSyncProfile: { ...state.lipSyncProfile } }
      }),
      setVisible: vi.fn((visible: boolean) => {
        Object.assign(state, { visible })
        return { ...state, lipSyncProfile: { ...state.lipSyncProfile } }
      }),
    },
    petModelCatalog: {
      refresh: vi.fn(),
      normalizeModelId: vi.fn((id: string | null) => id),
      getDefaultModelId: vi.fn(() => null),
      getModelById: vi.fn(() => null),
      getModels: vi.fn(() => []),
      resolveEmotionTrigger: vi.fn(() => null),
      getCatalog: vi.fn(() => ({ activeModelId: null, models: [] })),
      getLocalModelRoots: vi.fn(() => ({ live2d: '', vrm: '' })),
      importLocalLive2dModel: vi.fn(),
      importLocalVrmModel: vi.fn(),
      removeLocalModel: vi.fn(),
    },
    applyPetStateToRenderer: vi.fn(),
    normalizePetPatch: vi.fn((patch) => patch),
    dockPetToBottomRight: vi.fn(),
    captureDisplayPng: vi.fn(async () => Buffer.from([])),
    pluginRegistry: {
      snapshot: vi.fn(() => ({
        plugins: [],
        routes: [],
        modelProviders: [],
        toolCapabilities: [],
        pluginStates: [],
        loadFailures: [],
        audit: [],
      })),
    } as never,
    backendApiToken: 'backend-token',
    controlOrigin: 'http://127.0.0.1:38945',
    openPanel: vi.fn(async () => undefined),
    pythonService: {
      start: vi.fn(async () => undefined),
      stop: vi.fn(async () => undefined),
      health: vi.fn(async () => true),
    },
    onboardingCoordinator: {
      snapshot: vi.fn(() => ({ schemaVersion: 1, runId: '', revision: 0, state: 'idle', readyForText: false, startedAt: null, completedAt: null, probes: [] })),
      startBackend: vi.fn(),
      cancelBackend: vi.fn(),
      cancelRun: vi.fn(),
      reportDeviceProbe: vi.fn(),
      runProbe: vi.fn(),
      retry: vi.fn(),
      runRepair: vi.fn(),
    } as never,
    inputBindings: {
      getSnapshot: vi.fn(() => ({
        settings: {
          pushToTalk: { enabled: true, mouseButton: 5 },
          keyboard: {
            interact: 'Control+Shift+P',
            lock: 'Control+Shift+L',
            openPanel: 'Control+Shift+O',
          },
        },
        status: {
          mouseHookAvailable: true,
          pushToTalkActive: true,
          keyboard: { interact: true, lock: true, openPanel: true },
          errors: [],
        },
      })),
      update: vi.fn((patch) => ({
        settings: {
          pushToTalk: { enabled: true, mouseButton: patch.pushToTalk?.mouseButton ?? 5 },
          keyboard: {
            interact: 'Control+Shift+P',
            lock: 'Control+Shift+L',
            openPanel: 'Control+Shift+O',
          },
        },
        status: {
          mouseHookAvailable: true,
          pushToTalkActive: true,
          keyboard: { interact: true, lock: true, openPanel: true },
          errors: [],
        },
      })),
      reset: vi.fn(() => ({
        settings: {
          pushToTalk: { enabled: true, mouseButton: 5 },
          keyboard: {
            interact: 'Control+Shift+P',
            lock: 'Control+Shift+L',
            openPanel: 'Control+Shift+O',
          },
        },
        status: {
          mouseHookAvailable: true,
          pushToTalkActive: true,
          keyboard: { interact: true, lock: true, openPanel: true },
          errors: [],
        },
      })),
    },
    computerUseBridge: {
      preview: vi.fn(async () => ({ ok: true })),
      stop: vi.fn(async () => ({ ok: true, data: { revision: 7 } })),
      refreshStatus: vi.fn(async () => ({ ok: true })),
    } as never,
    desktopActionBridge: {
      getStatus: vi.fn(() => ({
        enabled: false,
        windowActionsAvailable: false,
        nativeInputAvailable: false,
        emergencyHotkeyAvailable: true,
        emergencyStopped: false,
        revision: 0,
        stopEpoch: 0,
        operationInFlight: false,
        degraded: false,
        reason: 'disabled',
        lastError: null,
      })),
      refreshStatus: vi.fn(async () => ({ ok: true })),
      enable: vi.fn(async () => ({ ok: true })),
      disable: vi.fn(async () => ({ ok: true })),
      rearm: vi.fn(async () => ({ ok: true })),
      beginEmergencyFence: vi.fn(),
      emergencyStop: vi.fn(async () => ({ ok: true, data: { revision: 7 } })),
    } as never,
    perceptionBridge: {
      collectScreenshot: vi.fn(async () => ({ ok: true })),
      collectTargetWindow: vi.fn(async () => ({ ok: true })),
      collectActiveApplication: vi.fn(async () => ({ ok: true })),
      collectSelectedFile: vi.fn(async () => ({ ok: true })),
      collectClipboard: vi.fn(async () => ({ ok: true })),
      collectOcr: vi.fn(async () => ({ ok: true })),
      beginStopFence: vi.fn(),
      interrupt: vi.fn(),
    } as never,
  }
}

const trustedEvent = {
  senderFrame: { url: buildPackagedRendererUrl('index.html') },
  sender: {
    getURL: () => '',
    session: {
      getCacheSize: vi.fn(async () => 0),
      clearCache: vi.fn(async () => undefined),
    },
  },
}

const untrustedEvent = {
  senderFrame: { url: 'https://example.com/app.html' },
  sender: {
    getURL: () => '',
    session: {
      getCacheSize: vi.fn(async () => 0),
      clearCache: vi.fn(async () => undefined),
    },
  },
}

describe('IPC handler sender trust', () => {
  beforeEach(() => {
    electronMock.handlers.clear()
    electronMock.listeners.clear()
    vi.spyOn(console, 'warn').mockImplementation(() => undefined)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('rejects untrusted invoke senders for pet control handles', async () => {
    const { registerIpcHandlers } = await import('../ipc-handlers')
    const ctx = buildIpcContext()
    registerIpcHandlers(ctx)

    const handler = electronMock.handlers.get('pet:set-visible')

    expect(handler).toBeDefined()
    expect(() => handler?.(untrustedEvent, true)).toThrow(/Blocked IPC from untrusted renderer/)
    expect(ctx.live2dWindow.show).not.toHaveBeenCalled()
  })

  it('starts and completes an adjustment while preserving the new transform', async () => {
    const { registerIpcHandlers } = await import('../ipc-handlers')
    const ctx = buildIpcContext()
    ctx.petStateStore.applyConfigPatch({ locked: true, clickThrough: false })
    registerIpcHandlers(ctx)

    const started = electronMock.handlers.get('pet:begin-adjustment')?.(trustedEvent)
    expect(started).toEqual(expect.objectContaining({
      visible: true,
      locked: false,
      clickThrough: false,
      interactMode: true,
    }))
    expect(ctx.live2dWindow.show).toHaveBeenCalledOnce()
    expect(ctx.live2dWindow.setInteractMode).toHaveBeenCalledWith(true)

    ctx.petStateStore.applyConfigPatch({
      displayId: 8,
      placement: 'free',
      positionX: 640,
      positionY: 420,
      scale: 0.4,
    })
    const completed = electronMock.handlers.get('pet:complete-adjustment')?.(trustedEvent)

    expect(completed).toEqual(expect.objectContaining({
      displayId: 8,
      placement: 'free',
      positionX: 640,
      positionY: 420,
      scale: 0.4,
      locked: true,
      clickThrough: false,
      interactMode: false,
    }))
    expect(ctx.live2dWindow.setLocked).toHaveBeenLastCalledWith(true)
    expect(ctx.live2dWindow.setClickThrough).toHaveBeenLastCalledWith(false)
  })

  it('cancels an adjustment by restoring the first session snapshot', async () => {
    const { registerIpcHandlers } = await import('../ipc-handlers')
    const ctx = buildIpcContext()
    ctx.petStateStore.applyConfigPatch({
      displayId: 3,
      placement: 'free',
      positionX: 120,
      positionY: 240,
      scale: 0.25,
      opacity: 0.65,
      visible: false,
      locked: true,
      clickThrough: true,
    })
    registerIpcHandlers(ctx)

    electronMock.handlers.get('pet:begin-adjustment')?.(trustedEvent)
    electronMock.handlers.get('pet:begin-adjustment')?.(trustedEvent)
    ctx.petStateStore.applyConfigPatch({
      displayId: 9,
      positionX: 900,
      positionY: 700,
      scale: 0.52,
      opacity: 1,
    })
    const canceled = electronMock.handlers.get('pet:cancel-adjustment')?.(trustedEvent)

    expect(canceled).toEqual(expect.objectContaining({
      displayId: 3,
      placement: 'free',
      positionX: 120,
      positionY: 240,
      scale: 0.25,
      opacity: 0.65,
      visible: false,
      locked: true,
      clickThrough: true,
      interactMode: false,
    }))
    expect(ctx.live2dWindow.hide).toHaveBeenCalledOnce()
    expect(ctx.applyPetStateToRenderer).toHaveBeenCalledWith(expect.objectContaining({ visible: false }))
  })

  it.each(['pet:begin-adjustment', 'pet:complete-adjustment', 'pet:cancel-adjustment'])(
    'rejects untrusted adjustment IPC on %s',
    async (channel) => {
      const { registerIpcHandlers } = await import('../ipc-handlers')
      const ctx = buildIpcContext()
      registerIpcHandlers(ctx)

      expect(() => electronMock.handlers.get(channel)?.(untrustedEvent)).toThrow(/Blocked IPC/)
      expect(ctx.applyPetStateToRenderer).not.toHaveBeenCalled()
    },
  )

  it('routes trusted window control invokes to the workbench window', async () => {
    const { registerIpcHandlers } = await import('../ipc-handlers')
    const ctx = buildIpcContext()
    const workbenchWindow = {
      minimize: vi.fn(),
      maximize: vi.fn(),
      unmaximize: vi.fn(),
      isMaximized: vi.fn(() => false),
      close: vi.fn(),
    }
    ctx.petWindow.window = workbenchWindow as never
    registerIpcHandlers(ctx)

    expect(electronMock.handlers.get('window:minimize')?.(trustedEvent)).toBe(true)
    expect(electronMock.handlers.get('window:maximize')?.(trustedEvent)).toBe(true)
    expect(electronMock.handlers.get('window:close')?.(trustedEvent)).toBe(true)

    expect(workbenchWindow.minimize).toHaveBeenCalled()
    expect(workbenchWindow.maximize).toHaveBeenCalled()
    expect(workbenchWindow.close).toHaveBeenCalled()
  })

  it('reports process memory and clears only the trusted renderer session cache', async () => {
    electronMock.app.getAppMetrics.mockReturnValue([
      { pid: 10, type: 'Browser', memory: { privateBytes: 12000, workingSetSize: 15000, peakWorkingSetSize: 18000 } },
      { pid: 11, type: 'Tab', memory: { privateBytes: 8000, workingSetSize: 9000, peakWorkingSetSize: 11000 } },
    ])
    const cacheSizes = [4096, 1024]
    trustedEvent.sender.session.getCacheSize.mockImplementation(async () => cacheSizes.shift() ?? 1024)
    const { registerIpcHandlers } = await import('../ipc-handlers')
    registerIpcHandlers(buildIpcContext())

    const snapshot = await electronMock.handlers.get('runtime:get-resource-snapshot')?.(trustedEvent)
    const cleared = await electronMock.handlers.get('runtime:clear-session-cache')?.(trustedEvent)

    expect(snapshot).toEqual(expect.objectContaining({
      cacheBytes: 4096,
      totalPrivateKb: 20000,
      processes: expect.arrayContaining([expect.objectContaining({ pid: 10, type: 'Browser' })]),
    }))
    expect(trustedEvent.sender.session.clearCache).toHaveBeenCalledOnce()
    expect(cleared).toEqual(expect.objectContaining({ ok: true, cacheBytesBefore: 1024 }))
    await expect(electronMock.handlers.get('runtime:get-resource-snapshot')?.(untrustedEvent)).rejects.toThrow(/Blocked IPC from untrusted renderer/)
  })

  it('drops untrusted fire-and-forget pet events without changing state', async () => {
    const { registerIpcHandlers } = await import('../ipc-handlers')
    const ctx = buildIpcContext()
    registerIpcHandlers(ctx)

    const listener = electronMock.listeners.get('pet:interact-enable')

    expect(listener).toBeDefined()
    expect(() => listener?.(untrustedEvent)).not.toThrow()
    expect(ctx.live2dWindow.setInteractMode).not.toHaveBeenCalled()

    listener?.(trustedEvent)
    expect(ctx.live2dWindow.setInteractMode).toHaveBeenCalledWith(true)
  })

  it('passes renderer readiness to the desktop pet window identity check', async () => {
    const { registerIpcHandlers } = await import('../ipc-handlers')
    const ctx = buildIpcContext()
    registerIpcHandlers(ctx)

    electronMock.listeners.get('pet:renderer-ready')?.(trustedEvent)

    expect(ctx.live2dWindow.handleRendererReady).toHaveBeenCalledWith(trustedEvent.sender)
  })

  it('forwards only trusted, bounded, and recognized lip-sync levels', async () => {
    const { registerIpcHandlers } = await import('../ipc-handlers')
    const ctx = buildIpcContext()
    registerIpcHandlers(ctx)

    const listener = electronMock.listeners.get('ui:set-lipsync-level')
    expect(listener).toBeDefined()

    listener?.(untrustedEvent, { level: 0.8, active: true, source: 'realtime' })
    expect(ctx.live2dWindow.sendToRenderer).not.toHaveBeenCalled()

    listener?.(trustedEvent, { level: 4.2, active: true, source: 'realtime' })
    expect(ctx.live2dWindow.sendToRenderer).toHaveBeenLastCalledWith('pet:lipsync-level', {
      level: 1,
      active: true,
      source: 'realtime',
    })

    vi.mocked(ctx.live2dWindow.sendToRenderer).mockClear()
    listener?.(trustedEvent, { level: Number.NaN, active: true, source: 'realtime' })
    expect(ctx.live2dWindow.sendToRenderer).not.toHaveBeenCalled()

    listener?.(trustedEvent, { level: 0.7, active: false, source: 'realtime' })
    expect(ctx.live2dWindow.sendToRenderer).toHaveBeenCalledWith('pet:lipsync-level', {
      level: 0,
      active: false,
      source: 'realtime',
    })

    listener?.(trustedEvent, { level: 0.35, active: true, source: 'tts-pcm' })
    expect(ctx.live2dWindow.sendToRenderer).toHaveBeenLastCalledWith('pet:lipsync-level', {
      level: 0.35,
      active: true,
      source: 'tts-pcm',
    })

    vi.mocked(ctx.live2dWindow.sendToRenderer).mockClear()
    listener?.(trustedEvent, { level: 0.5, active: true, source: 'unknown' })
    expect(ctx.live2dWindow.sendToRenderer).not.toHaveBeenCalled()
  })

  it('forwards only trusted and normalized PCM viseme controls', async () => {
    const { registerIpcHandlers } = await import('../ipc-handlers')
    const ctx = buildIpcContext()
    registerIpcHandlers(ctx)

    const listener = electronMock.listeners.get('ui:set-lipsync-viseme')
    expect(listener).toBeDefined()

    listener?.(untrustedEvent, { viseme: 'ih', weight: 0.8, active: true, source: 'tts-pcm' })
    expect(ctx.live2dWindow.sendToRenderer).not.toHaveBeenCalled()

    listener?.(trustedEvent, { viseme: 'ih', weight: 4, active: true, source: 'tts-pcm' })
    expect(ctx.live2dWindow.sendToRenderer).toHaveBeenLastCalledWith('pet:lipsync-viseme', {
      viseme: 'ih',
      weight: 1,
      active: true,
      source: 'tts-pcm',
    })

    vi.mocked(ctx.live2dWindow.sendToRenderer).mockClear()
    listener?.(trustedEvent, { viseme: 'unknown', weight: 1, active: true, source: 'tts-pcm' })
    listener?.(trustedEvent, { viseme: 'aa', weight: Number.NaN, active: true, source: 'tts-pcm' })
    expect(ctx.live2dWindow.sendToRenderer).not.toHaveBeenCalled()

    listener?.(trustedEvent, { viseme: 'aa', weight: 1, active: false, source: 'tts-pcm' })
    expect(ctx.live2dWindow.sendToRenderer).toHaveBeenCalledWith('pet:lipsync-viseme', {
      viseme: 'sil',
      weight: 0,
      active: false,
      source: 'tts-pcm',
    })
  })

  it('dispatches trusted desktop pet events to subscribed plugin routes', async () => {
    const { registerIpcHandlers } = await import('../ipc-handlers')
    const ctx = buildIpcContext()
    ctx.pluginRegistry = {
      snapshot: vi.fn(() => ({
        plugins: [
          {
            id: 'click-skill',
            name: 'Click Skill',
            manifestVersion: 2,
            permissions: { routes: ['react'], toolScopes: [], modelScopes: [] },
            execution: { maxConcurrentExecutions: 1, maxExecutionTimeMs: 1000, allowCancellation: true },
            routes: [{ id: 'react', namespace: 'plugin' }],
            petEvents: [{ event: 'onPetClicked', routeId: 'react', description: 'React to clicks' }],
          },
        ],
        routes: [],
        modelProviders: [],
        toolCapabilities: [],
        pluginStates: [],
        loadFailures: [],
        audit: [],
      })),
    } as never
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ invocationId: 'run-1', traceId: 'trace-1' }),
    }))
    registerIpcHandlers(ctx)

    const handler = electronMock.handlers.get('pet:dispatch-event')
    const result = await handler?.(trustedEvent, {
      event: 'onPetClicked',
      timestamp: '2026-07-15T09:00:00.000Z',
      payload: { gesture: 'single_click' },
    })

    expect(result).toEqual(expect.objectContaining({
      ok: true,
      matched: 1,
      dispatched: 1,
      skipped: 0,
    }))
    expect(fetch).toHaveBeenCalledTimes(1)
    const [requestUrl, requestInit] = vi.mocked(fetch).mock.calls[0] as [URL, RequestInit]
    expect(requestUrl.toString()).toBe('http://127.0.0.1:38945/api/plugin/click-skill/react')
    expect(requestInit).toEqual(expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({
        Authorization: 'Bearer backend-token',
        'Content-Type': 'application/json',
      }),
    }))
    expect(JSON.parse(String(requestInit.body))).toMatchObject({
      event: 'onPetClicked',
      payload: { gesture: 'single_click' },
      source: 'desktop-pet',
      subscription: {
        event: 'onPetClicked',
        routeId: 'react',
      },
    })
  })

  it('rejects malformed desktop pet events before plugin dispatch', async () => {
    const { registerIpcHandlers } = await import('../ipc-handlers')
    const ctx = buildIpcContext()
    vi.stubGlobal('fetch', vi.fn())
    registerIpcHandlers(ctx)

    const handler = electronMock.handlers.get('pet:dispatch-event')
    const result = await handler?.(trustedEvent, {
      event: 'unknown',
      payload: {},
    })

    expect(result).toEqual(expect.objectContaining({
      ok: false,
      error: 'Invalid desktop pet event payload',
    }))
    expect(fetch).not.toHaveBeenCalled()
  })

  it('rejects untrusted screen capture requests before reading the desktop', async () => {
    const { registerIpcHandlers } = await import('../ipc-handlers')
    const ctx = buildIpcContext()
    registerIpcHandlers(ctx)

    const handler = electronMock.handlers.get('screen:capture')

    expect(handler).toBeDefined()
    await expect(handler?.(untrustedEvent, { displayIndex: 0 })).rejects.toThrow(/Blocked IPC from untrusted renderer/)
    expect(ctx.captureDisplayPng).not.toHaveBeenCalled()
  })

  it('downscales realtime vision captures and encodes them as bounded JPEG data', async () => {
    const resizedJpeg = Buffer.from('vision-jpeg')
    const resizedImage = {
      isEmpty: vi.fn(() => false),
      toJPEG: vi.fn(() => resizedJpeg),
    }
    const sourceImage = {
      isEmpty: vi.fn(() => false),
      getSize: vi.fn(() => ({ width: 3840, height: 2160 })),
      resize: vi.fn(() => resizedImage),
    }
    electronMock.nativeImage.createFromBuffer.mockReturnValue(sourceImage)
    electronMock.screen.getAllDisplays.mockReturnValue([{
      id: 10,
      bounds: { x: 0, y: 0, width: 3840, height: 2160 },
      workArea: { x: 0, y: 0, width: 3840, height: 2100 },
      scaleFactor: 1,
    }])
    const { registerIpcHandlers } = await import('../ipc-handlers')
    const ctx = buildIpcContext()
    vi.mocked(ctx.captureDisplayPng).mockResolvedValue(Buffer.from('full-resolution-png'))
    registerIpcHandlers(ctx)

    const handler = electronMock.handlers.get('screen:capture')
    const result = await handler?.(trustedEvent, {
      displayIndex: 0,
      maxWidth: 1280,
      maxHeight: 720,
      format: 'jpeg',
      quality: 72,
    })

    expect(sourceImage.resize).toHaveBeenCalledWith({ width: 1280, height: 720, quality: 'good' })
    expect(resizedImage.toJPEG).toHaveBeenCalledWith(72)
    expect(result).toBe(`data:image/jpeg;base64,${resizedJpeg.toString('base64')}`)
  })

  it('applies privacy masks in the main process before returning encoded capture data', async () => {
    const bitmap = Buffer.alloc(320 * 180 * 4, 70)
    const maskedJpeg = Buffer.from('masked-vision-jpeg')
    const maskedImage = {
      isEmpty: vi.fn(() => false),
      toJPEG: vi.fn(() => maskedJpeg),
    }
    const resizedImage = {
      isEmpty: vi.fn(() => false),
      getSize: vi.fn(() => ({ width: 320, height: 180 })),
      toBitmap: vi.fn(() => bitmap),
    }
    electronMock.nativeImage.createFromBuffer.mockReturnValue({
      isEmpty: vi.fn(() => false),
      getSize: vi.fn(() => ({ width: 640, height: 360 })),
      resize: vi.fn(() => resizedImage),
    })
    electronMock.nativeImage.createFromBitmap.mockReturnValue(maskedImage)
    electronMock.screen.getAllDisplays.mockReturnValue([{
      id: 10,
      bounds: { x: 0, y: 0, width: 640, height: 360 },
      workArea: { x: 0, y: 0, width: 640, height: 360 },
      scaleFactor: 1,
    }])
    const { registerIpcHandlers } = await import('../ipc-handlers')
    const ctx = buildIpcContext()
    vi.mocked(ctx.captureDisplayPng).mockResolvedValue(Buffer.from('full-resolution-png'))
    registerIpcHandlers(ctx)

    const handler = electronMock.handlers.get('screen:capture')
    const result = await handler?.(trustedEvent, {
      displayIndex: 0,
      maxWidth: 320,
      maxHeight: 180,
      format: 'jpeg',
      privacyMasks: [{ x: 0, y: 0, width: 640, height: 360 }],
    })

    expect(electronMock.nativeImage.createFromBitmap).toHaveBeenCalledWith(bitmap, { width: 320, height: 180 })
    expect([...bitmap.subarray(0, 4)]).toEqual([0, 0, 0, 255])
    expect([...bitmap.subarray(bitmap.length - 4)]).toEqual([0, 0, 0, 255])
    expect(maskedImage.toJPEG).toHaveBeenCalled()
    expect(result).toBe(`data:image/jpeg;base64,${maskedJpeg.toString('base64')}`)
  })

  it('fails closed when a privacy mask cannot be encoded', async () => {
    const bitmap = Buffer.alloc(320 * 180 * 4, 70)
    const resizedImage = {
      isEmpty: vi.fn(() => false),
      getSize: vi.fn(() => ({ width: 320, height: 180 })),
      toBitmap: vi.fn(() => bitmap),
    }
    electronMock.nativeImage.createFromBuffer.mockReturnValue({
      isEmpty: vi.fn(() => false),
      getSize: vi.fn(() => ({ width: 640, height: 360 })),
      resize: vi.fn(() => resizedImage),
    })
    electronMock.nativeImage.createFromBitmap.mockReturnValue({
      isEmpty: vi.fn(() => true),
    })
    electronMock.screen.getAllDisplays.mockReturnValue([{
      id: 10,
      bounds: { x: 0, y: 0, width: 640, height: 360 },
      workArea: { x: 0, y: 0, width: 640, height: 360 },
      scaleFactor: 1,
    }])
    const { registerIpcHandlers } = await import('../ipc-handlers')
    const ctx = buildIpcContext()
    vi.mocked(ctx.captureDisplayPng).mockResolvedValue(Buffer.from('full-resolution-png'))
    registerIpcHandlers(ctx)

    const handler = electronMock.handlers.get('screen:capture')
    const result = await handler?.(trustedEvent, {
      displayIndex: 0,
      maxWidth: 320,
      maxHeight: 180,
      format: 'jpeg',
      privacyMasks: [{ x: 0, y: 0, width: 640, height: 360 }],
    })

    expect(result).toBeNull()
  })

  it('returns only normalized display metadata to trusted renderers', async () => {
    electronMock.screen.getPrimaryDisplay.mockReturnValue({
      id: 20,
      workArea: { x: 0, y: 0, width: 1920, height: 1080 },
    })
    electronMock.screen.getAllDisplays.mockReturnValue([
      {
        id: 20,
        label: 'Primary',
        bounds: { x: 0, y: 0, width: 1920, height: 1080 },
        workArea: { x: 0, y: 0, width: 1920, height: 1040 },
        scaleFactor: 1.25,
      },
    ])
    const { registerIpcHandlers } = await import('../ipc-handlers')
    registerIpcHandlers(buildIpcContext())

    const handler = electronMock.handlers.get('screen:list-displays')
    const result = await handler?.(trustedEvent)

    expect(result).toEqual([{
      index: 0,
      id: 20,
      label: 'Primary',
      width: 1920,
      height: 1080,
      scaleFactor: 1.25,
      isPrimary: true,
    }])
  })

  it('returns cropped image data for region captures', async () => {
    const crop = vi.fn(() => ({
      isEmpty: () => false,
      getSize: () => ({ width: 100, height: 50 }),
      toPNG: () => Buffer.from('cropped'),
    }))
    electronMock.screen.getAllDisplays.mockReturnValue([
      {
        id: 10,
        bounds: { x: 100, y: 50, width: 200, height: 100 },
        workArea: { x: 100, y: 50, width: 200, height: 100 },
      },
    ])
    electronMock.nativeImage.createFromBuffer.mockReturnValue({
      isEmpty: () => false,
      getSize: () => ({ width: 400, height: 200 }),
      crop,
    })
    const { registerIpcHandlers } = await import('../ipc-handlers')
    const ctx = buildIpcContext()
    vi.mocked(ctx.captureDisplayPng).mockResolvedValue(Buffer.from('full-screen'))
    registerIpcHandlers(ctx)

    const handler = electronMock.handlers.get('screen:capture-region')
    const result = await handler?.(trustedEvent, {
      displayIndex: 0,
      x: 150,
      y: 75,
      width: 50,
      height: 25,
    })

    expect(ctx.captureDisplayPng).toHaveBeenCalledWith(expect.objectContaining({ id: 10 }), 0)
    expect(crop).toHaveBeenCalledWith({ x: 100, y: 50, width: 100, height: 50 })
    expect(result).toBe(`data:image/png;base64,${Buffer.from('cropped').toString('base64')}`)
  })

  it('does not register the legacy screen OCR bypass', async () => {
    const { registerIpcHandlers } = await import('../ipc-handlers')
    const ctx = buildIpcContext()
    registerIpcHandlers(ctx)

    expect(electronMock.handlers.has('screen:ocr')).toBe(false)
    expect(ctx.captureDisplayPng).not.toHaveBeenCalled()
  })

  it('does not register the legacy fire-and-forget full-screen capture listener', async () => {
    const { registerIpcHandlers } = await import('../ipc-handlers')
    const ctx = buildIpcContext()
    registerIpcHandlers(ctx)

    expect(electronMock.listeners.has('invoke-screen-capture')).toBe(false)
  })

  it('applies trusted desktop input binding updates through the main process', async () => {
    const { registerIpcHandlers } = await import('../ipc-handlers')
    const ctx = buildIpcContext()
    registerIpcHandlers(ctx)

    const handler = electronMock.handlers.get('input-bindings:update')
    const result = await handler?.(trustedEvent, { pushToTalk: { mouseButton: 4 } })

    expect(ctx.inputBindings.update).toHaveBeenCalledWith({ pushToTalk: { mouseButton: 4 } })
    expect(result).toEqual(expect.objectContaining({
      settings: expect.objectContaining({ pushToTalk: { enabled: true, mouseButton: 4 } }),
    }))
  })

  it('rejects untrusted desktop input binding changes', async () => {
    const { registerIpcHandlers } = await import('../ipc-handlers')
    const ctx = buildIpcContext()
    registerIpcHandlers(ctx)

    const handler = electronMock.handlers.get('input-bindings:update')

    expect(() => handler?.(untrustedEvent, { pushToTalk: { mouseButton: 4 } })).toThrow(/Blocked IPC/)
    expect(ctx.inputBindings.update).not.toHaveBeenCalled()
  })

  it('rejects untrusted computer-use IPC before reaching the host bridge', async () => {
    const { registerIpcHandlers } = await import('../ipc-handlers')
    const ctx = buildIpcContext()
    registerIpcHandlers(ctx)

    const preview = electronMock.handlers.get('computer-use:preview')
    const stop = electronMock.handlers.get('computer-use:emergency-stop')
    const status = electronMock.handlers.get('computer-use:status')

    expect(() => preview?.(untrustedEvent, { actions: [] })).toThrow(/Blocked IPC/)
    expect(() => stop?.(untrustedEvent)).toThrow(/Blocked IPC/)
    expect(() => status?.(untrustedEvent)).toThrow(/Blocked IPC/)
    expect(ctx.computerUseBridge.preview).not.toHaveBeenCalled()
    expect(ctx.computerUseBridge.stop).not.toHaveBeenCalled()
    expect(ctx.computerUseBridge.refreshStatus).not.toHaveBeenCalled()
    expect(ctx.perceptionBridge.beginStopFence).not.toHaveBeenCalled()
    expect(ctx.perceptionBridge.interrupt).not.toHaveBeenCalled()
  })

  it('fences in-flight perception before a trusted emergency stop reaches computer-use', async () => {
    const { registerIpcHandlers } = await import('../ipc-handlers')
    const ctx = buildIpcContext()
    const order: string[] = []
    vi.mocked(ctx.perceptionBridge.beginStopFence).mockImplementation(() => { order.push('perception-fence') })
    vi.mocked(ctx.perceptionBridge.interrupt).mockImplementation(() => { order.push('perception-revision') })
    vi.mocked(ctx.computerUseBridge.stop).mockImplementation(async () => {
      order.push('computer-use')
      return { ok: true, data: { revision: 7 } } as never
    })
    registerIpcHandlers(ctx)

    const stop = electronMock.handlers.get('computer-use:emergency-stop')
    await stop?.(trustedEvent)

    expect(ctx.perceptionBridge.beginStopFence).toHaveBeenCalledOnce()
    expect(ctx.perceptionBridge.interrupt).toHaveBeenCalledWith(7)
    expect(order).toEqual(['perception-fence', 'computer-use', 'perception-revision'])
  })

  it('allows only trusted fixed perception IPC with one opaque session id', async () => {
    const { registerIpcHandlers } = await import('../ipc-handlers')
    const ctx = buildIpcContext()
    registerIpcHandlers(ctx)
    const channels = [
      'perception:collect-screenshot',
      'perception:collect-target-window',
      'perception:collect-active-application',
      'perception:collect-selected-file',
      'perception:collect-clipboard',
      'perception:collect-ocr',
    ]

    for (const channel of channels) {
      const handler = electronMock.handlers.get(channel)
      expect(() => handler?.(untrustedEvent, 'opaque-session')).toThrow(/Blocked IPC/)
      await handler?.(trustedEvent, 'opaque-session')
    }

    expect(ctx.perceptionBridge.collectScreenshot).toHaveBeenCalledWith('opaque-session')
    expect(ctx.perceptionBridge.collectTargetWindow).toHaveBeenCalledWith('opaque-session')
    expect(ctx.perceptionBridge.collectActiveApplication).toHaveBeenCalledWith('opaque-session')
    expect(ctx.perceptionBridge.collectSelectedFile).toHaveBeenCalledWith('opaque-session')
    expect(ctx.perceptionBridge.collectClipboard).toHaveBeenCalledWith('opaque-session')
    expect(ctx.perceptionBridge.collectOcr).toHaveBeenCalledWith('opaque-session')
    expect(electronMock.handlers.has('perception:collect')).toBe(false)
    expect(electronMock.handlers.has('perception:issue')).toBe(false)
  })

  it('exposes only closed trusted onboarding requests', async () => {
    const { registerIpcHandlers } = await import('../ipc-handlers')
    const ctx = buildIpcContext()
    registerIpcHandlers(ctx)

    expect(() => electronMock.handlers.get('onboarding:snapshot')?.(untrustedEvent)).toThrow(/Blocked IPC/)
    expect(() => electronMock.handlers.get('onboarding:start-backend')?.(trustedEvent, { command: 'python' })).toThrow(/does not accept arguments/)
    expect(() => electronMock.handlers.get('onboarding:run-probe')?.(trustedEvent, { probeIds: ['host.runtime'], env: {} })).toThrow(/Invalid onboarding probe request/)
    expect(() => electronMock.handlers.get('onboarding:run-repair')?.(trustedEvent, { actionId: 'backend.retry', args: ['--unsafe'] })).toThrow(/Unknown onboarding repair action/)
    expect(() => electronMock.handlers.get('onboarding:run-repair')?.(trustedEvent, { actionId: 'shell:cmd.exe' })).toThrow(/Unknown onboarding repair action/)
    expect(() => electronMock.handlers.get('onboarding:cancel-run')?.(trustedEvent, { runId: 'run-1', command: 'kill' })).toThrow(/Invalid onboarding cancel request/)
    expect(() => electronMock.handlers.get('onboarding:report-device-probe')?.(trustedEvent, {
      probeId: 'host.microphone', outcome: 'ready', messageCode: 'permission_granted', evidence: { deviceId: 'secret' },
    })).toThrow(/Invalid onboarding device report/)
    expect(() => electronMock.handlers.get('onboarding:report-device-probe')?.(trustedEvent, {
      probeId: 'host.microphone', outcome: 'ready', messageCode: 'arbitrary text',
    })).toThrow(/Invalid onboarding device report/)

    await electronMock.handlers.get('onboarding:run-repair')?.(trustedEvent, { actionId: 'backend.retry' })
    expect(ctx.onboardingCoordinator.runRepair).toHaveBeenCalledWith('backend.retry')
    await electronMock.handlers.get('onboarding:report-device-probe')?.(trustedEvent, {
      probeId: 'host.speaker', outcome: 'ready', messageCode: 'test_completed',
    })
    expect(ctx.onboardingCoordinator.reportDeviceProbe).toHaveBeenCalledWith({
      probeId: 'host.speaker', outcome: 'ready', messageCode: 'test_completed',
    })
  })
})
