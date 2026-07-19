import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { IpcContext } from '../ipc-handlers'
import { buildPackagedRendererUrl } from '../renderer-protocol'

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
    modelId: null,
    locked: false,
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
      hasVisiblePixelAt: vi.fn(async () => false),
    },
    petWindow: {
      window: null,
    },
    petStateStore: {
      getState: vi.fn(() => state as never),
      applyConfigPatch: vi.fn((patch: Record<string, unknown>) => Object.assign(state, patch)),
      setReady: vi.fn(),
      setInteractMode: vi.fn((enabled: boolean) => Object.assign(state, { interactMode: enabled })),
      setVisible: vi.fn((visible: boolean) => Object.assign(state, { visible })),
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
    screenshotDesktop: vi.fn(async () => Buffer.from([])),
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
    adminTokenStore: {
      getSummaryAdminToken: vi.fn(() => ''),
      setSummaryAdminToken: vi.fn(() => ({ ok: true, hasToken: true })),
      clearSummaryAdminToken: vi.fn(() => ({ ok: true })),
    },
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
    expect(ctx.screenshotDesktop).not.toHaveBeenCalled()
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
    vi.mocked(ctx.screenshotDesktop).mockResolvedValue(Buffer.from('full-resolution-png'))
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
    vi.mocked(ctx.screenshotDesktop).mockResolvedValue(Buffer.from('full-resolution-png'))
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
    vi.mocked(ctx.screenshotDesktop).mockResolvedValue(Buffer.from('full-resolution-png'))
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
    vi.mocked(ctx.screenshotDesktop).mockResolvedValue(Buffer.from('full-screen'))
    registerIpcHandlers(ctx)

    const handler = electronMock.handlers.get('screen:capture-region')
    const result = await handler?.(trustedEvent, {
      displayIndex: 0,
      x: 150,
      y: 75,
      width: 50,
      height: 25,
    })

    expect(ctx.screenshotDesktop).toHaveBeenCalledWith({ screen: '10' })
    expect(crop).toHaveBeenCalledWith({ x: 100, y: 50, width: 100, height: 50 })
    expect(result).toBe(`data:image/png;base64,${Buffer.from('cropped').toString('base64')}`)
  })

  it('rejects untrusted screen OCR requests before reading the desktop', async () => {
    const { registerIpcHandlers } = await import('../ipc-handlers')
    const ctx = buildIpcContext()
    registerIpcHandlers(ctx)

    const handler = electronMock.handlers.get('screen:ocr')

    expect(handler).toBeDefined()
    await expect(handler?.(untrustedEvent, { displayIndex: 0 })).rejects.toThrow(/Blocked IPC from untrusted renderer/)
    expect(ctx.screenshotDesktop).not.toHaveBeenCalled()
  })

  it('proxies trusted screen OCR requests to the Python OCR endpoint without returning the screenshot', async () => {
    electronMock.screen.getAllDisplays.mockReturnValue([
      {
        id: 10,
        bounds: { x: 0, y: 0, width: 200, height: 100 },
        workArea: { x: 0, y: 0, width: 200, height: 100 },
      },
    ])
    const fetchMock = vi.fn(async () => new Response(
      JSON.stringify({ status: 'ok', text: 'screen text', blocks: [] }),
      { status: 200 },
    ))
    vi.stubGlobal('fetch', fetchMock)

    const { registerIpcHandlers } = await import('../ipc-handlers')
    const ctx = buildIpcContext()
    vi.mocked(ctx.screenshotDesktop).mockResolvedValue(Buffer.from('raw-png-bytes'))
    registerIpcHandlers(ctx)

    const handler = electronMock.handlers.get('screen:ocr')
    const result = await handler?.(trustedEvent, { displayIndex: 0 })

    expect(ctx.screenshotDesktop).toHaveBeenCalledWith({ screen: '10' })
    expect(fetchMock).toHaveBeenCalledWith('http://127.0.0.1:8001/vision/ocr', expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({
        'x-yuizaki-backend-token': 'backend-token',
      }),
    }))
    expect(result).toEqual({ status: 'ok', text: 'screen text', blocks: [] })
    expect(result).not.toHaveProperty('image')
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
})
