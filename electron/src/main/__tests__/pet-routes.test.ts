import { EventEmitter } from 'node:events'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { dialog } from 'electron'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { describe, expect, it, vi } from 'vitest'
import { handlePetRoutes } from '../http/routes/pet-routes'
import type { HttpRouteContext } from '../http/types'

vi.mock('electron', () => ({
  dialog: {
    showOpenDialog: vi.fn(),
  },
}))

const createJsonRequest = (body: unknown): IncomingMessage => {
  const request = new EventEmitter() as EventEmitter & {
    setEncoding: (encoding: BufferEncoding) => void
  }
  request.setEncoding = () => {}

  queueMicrotask(() => {
    request.emit('data', JSON.stringify(body))
    request.emit('end')
  })

  return request as unknown as IncomingMessage
}

const createJsonResponse = (): {
  response: ServerResponse
  getStatus: () => number | null
  getJson: () => unknown
} => {
  let statusCode: number | null = null
  let payloadText = ''
  const response = {
    getHeader: () => undefined,
    writeHead: (nextStatusCode: number) => {
      statusCode = nextStatusCode
      return response
    },
    end: (payload: string) => {
      payloadText = payload
      return response
    },
  }

  return {
    response: response as unknown as ServerResponse,
    getStatus: () => statusCode,
    getJson: () => JSON.parse(payloadText) as unknown,
  }
}

const createPetRouteContext = (options: { doNotDisturb?: boolean } = {}) => {
  const sendToRenderer = vi.fn()
  const applyCompanionIdleProfile = vi.fn()
  const context = {
    live2dWindow: {
      sendToRenderer,
      applyCompanionIdleProfile,
    },
    petStateStore: {
      getState: () => ({ modelId: 'hiyori', doNotDisturb: Boolean(options.doNotDisturb) }),
    },
    petModelCatalog: {},
    applyStateToLive2D: (state: unknown) => state,
  } as unknown as HttpRouteContext

  return { context, sendToRenderer, applyCompanionIdleProfile }
}

const runPetRoute = async (pathname: string, body: unknown, options: { doNotDisturb?: boolean } = {}) => {
  const { context, sendToRenderer, applyCompanionIdleProfile } = createPetRouteContext(options)
  const { response, getStatus, getJson } = createJsonResponse()
  const handled = await handlePetRoutes(
    createJsonRequest(body),
    response,
    'POST',
    new URL(`http://127.0.0.1:38945${pathname}`),
    context,
  )

  return { handled, status: getStatus(), payload: getJson(), sendToRenderer, applyCompanionIdleProfile }
}

const runMoveRoute = async (locked: boolean) => {
  const applyConfigPatch = vi.fn((patch: unknown) => ({ modelId: 'hiyori', ...(patch as Record<string, unknown>) }))
  const context = {
    live2dWindow: {},
    petStateStore: {
      getState: () => ({ modelId: 'hiyori', locked }),
      applyConfigPatch,
    },
    applyPetStateToRenderer: vi.fn(),
  } as unknown as HttpRouteContext
  const { response, getStatus, getJson } = createJsonResponse()
  const handled = await handlePetRoutes(
    createJsonRequest({ x: 42, y: 64 }),
    response,
    'POST',
    new URL('http://127.0.0.1:38945/api/pet/move'),
    context,
  )

  return { handled, status: getStatus(), payload: getJson(), applyConfigPatch }
}

const runPlaceRoute = async (body: unknown) => {
  const place = vi.fn((placement: unknown, displayId: unknown) => ({
    modelId: 'hiyori',
    placement,
    displayId,
    positionX: null,
    positionY: null,
  }))
  const applyStateToLive2D = vi.fn((state: unknown) => state)
  const context = {
    live2dWindow: {},
    petStateStore: {
      place,
    },
    applyStateToLive2D,
  } as unknown as HttpRouteContext
  const { response, getStatus, getJson } = createJsonResponse()
  const handled = await handlePetRoutes(
    createJsonRequest(body),
    response,
    'POST',
    new URL('http://127.0.0.1:38945/api/pet/place'),
    context,
  )

  return { handled, status: getStatus(), payload: getJson(), place, applyStateToLive2D }
}

const runLive2dAssetRoute = async (pathname: string) => {
  const resolveLocalLive2dAsset = vi.fn(() => null)
  const context = {
    petModelCatalog: {
      resolveLocalLive2dAsset,
    },
  } as unknown as HttpRouteContext
  const { response, getStatus, getJson } = createJsonResponse()
  const handled = await handlePetRoutes(
    createJsonRequest({}),
    response,
    'GET',
    new URL(`http://127.0.0.1:38945${pathname}`),
    context,
  )

  return { handled, status: getStatus(), payload: getJson(), resolveLocalLive2dAsset }
}

const runCatalogRoute = async () => {
  const refresh = vi.fn()
  const applyConfigPatch = vi.fn((patch: unknown) => ({
    modelId: 'hiyori',
    modelType: 'live2d',
    ...(patch as Record<string, unknown>),
  }))
  const applyStateToLive2D = vi.fn((state: unknown) => state)
  const context = {
    petStateStore: {
      getState: () => ({ modelId: 'local:deleted', modelType: 'vrm' }),
      applyConfigPatch,
    },
    petModelCatalog: {
      refresh,
      normalizeModelId: () => 'hiyori',
      getModelById: (modelId: string | null) => modelId === 'hiyori' ? { id: 'hiyori', type: 'live2d' } : null,
      getCatalog: () => ({
        activeModelId: 'hiyori',
        models: [{ id: 'hiyori', type: 'live2d', source: 'bundled' }],
      }),
    },
    applyStateToLive2D,
  } as unknown as HttpRouteContext
  const { response, getStatus, getJson } = createJsonResponse()
  const handled = await handlePetRoutes(
    createJsonRequest({}),
    response,
    'GET',
    new URL('http://127.0.0.1:38945/api/pet/catalog'),
    context,
  )

  return { handled, status: getStatus(), payload: getJson(), refresh, applyConfigPatch, applyStateToLive2D }
}

const runConfigRoute = async (body: unknown) => {
  const currentState = { modelId: 'local:vrm/hero', modelType: 'vrm', locked: false }
  const applyConfigPatch = vi.fn((patch: unknown) => ({ ...currentState, ...(patch as Record<string, unknown>) }))
  const applyStateToLive2D = vi.fn((state: unknown) => state)
  const getModelById = vi.fn()
  const context = {
    live2dWindow: {},
    petStateStore: {
      getState: () => currentState,
      applyConfigPatch,
    },
    petModelCatalog: {
      getModelById,
    },
    applyStateToLive2D,
  } as unknown as HttpRouteContext
  const { response, getStatus, getJson } = createJsonResponse()
  const handled = await handlePetRoutes(
    createJsonRequest(body),
    response,
    'POST',
    new URL('http://127.0.0.1:38945/api/pet/config'),
    context,
  )

  return { handled, status: getStatus(), payload: getJson(), applyConfigPatch, applyStateToLive2D, getModelById }
}

const runSelectPetModelRoute = async (body: unknown, model: { id: string; type: 'live2d' | 'vrm' } | null) => {
  const applyConfigPatch = vi.fn((patch: unknown) => ({ ...(patch as Record<string, unknown>) }))
  const applyStateToLive2D = vi.fn((state: unknown) => state)
  const context = {
    live2dWindow: {},
    petStateStore: {
      applyConfigPatch,
    },
    petModelCatalog: {
      getDefaultModelId: vi.fn(() => 'hiyori'),
      getModelById: vi.fn((modelId: string | null) => (model && modelId === model.id ? model : null)),
    },
    applyStateToLive2D,
  } as unknown as HttpRouteContext
  const { response, getStatus, getJson } = createJsonResponse()
  const handled = await handlePetRoutes(
    createJsonRequest(body),
    response,
    'POST',
    new URL('http://127.0.0.1:38945/api/pet/model'),
    context,
  )

  return { handled, status: getStatus(), payload: getJson(), applyConfigPatch, applyStateToLive2D }
}

const runModelImportRoute = async (body: unknown) => {
  const importLocalVrmModel = vi.fn(() => ({ id: 'local:vrm/hero', type: 'vrm' }))
  const applyConfigPatch = vi.fn((patch: unknown) => ({ modelId: 'local:vrm/hero', ...(patch as Record<string, unknown>) }))
  const context = {
    live2dWindow: {},
    petStateStore: {
      applyConfigPatch,
      getState: () => ({ modelId: 'local:vrm/hero' }),
    },
    petModelCatalog: {
      importLocalVrmModel,
      importLocalLive2dModel: vi.fn(),
      getModels: () => [{ id: 'local:vrm/hero', type: 'vrm', source: 'local' }],
      getCatalog: () => ({ activeModelId: 'local:vrm/hero', models: [{ id: 'local:vrm/hero', type: 'vrm', source: 'local' }] }),
      getLocalModelRoots: () => ({ live2d: 'live2d-root', vrm: 'vrm-root' }),
    },
    applyStateToLive2D: vi.fn((state: unknown) => state),
  } as unknown as HttpRouteContext
  const { response, getStatus, getJson } = createJsonResponse()
  const handled = await handlePetRoutes(
    createJsonRequest(body),
    response,
    'POST',
    new URL('http://127.0.0.1:38945/api/pet/model/import'),
    context,
  )

  return { handled, status: getStatus(), payload: getJson(), importLocalVrmModel, applyConfigPatch, applyStateToLive2D: context.applyStateToLive2D as ReturnType<typeof vi.fn> }
}

const runModelImportFromPickerRoute = async (body: unknown) => {
  const importLocalLive2dModel = vi.fn(async () => ({ id: 'local:hiyori', type: 'live2d', source: 'local' }))
  const applyConfigPatch = vi.fn((patch: unknown) => ({ modelId: 'local:hiyori', ...(patch as Record<string, unknown>) }))
  const context = {
    live2dWindow: {},
    petStateStore: {
      applyConfigPatch,
      getState: () => ({ modelId: 'local:hiyori' }),
    },
    petModelCatalog: {
      importLocalLive2dModel,
      importLocalVrmModel: vi.fn(),
      getModels: () => [{ id: 'local:hiyori', type: 'live2d', source: 'local' }],
      getCatalog: () => ({ activeModelId: 'local:hiyori', models: [{ id: 'local:hiyori', type: 'live2d', source: 'local' }] }),
      getLocalModelRoots: () => ({ live2d: 'live2d-root', vrm: 'vrm-root' }),
    },
    applyStateToLive2D: vi.fn((state: unknown) => state),
  } as unknown as HttpRouteContext
  const { response, getStatus, getJson } = createJsonResponse()
  const handled = await handlePetRoutes(
    createJsonRequest(body),
    response,
    'POST',
    new URL('http://127.0.0.1:38945/api/pet/model/import-from-picker'),
    context,
  )

  return { handled, status: getStatus(), payload: getJson(), importLocalLive2dModel, applyConfigPatch }
}

const runModelDeleteRoute = async (body: unknown) => {
  let currentState = { modelId: 'local:old', modelType: 'live2d' }
  const removeLocalModel = vi.fn((modelId: string) => modelId === 'local:old')
  const refresh = vi.fn()
  const applyConfigPatch = vi.fn((patch: unknown) => {
    currentState = { ...currentState, ...(patch as typeof currentState) }
    return currentState
  })
  const applyStateToLive2D = vi.fn((state: unknown) => state)
  const context = {
    live2dWindow: {},
    petStateStore: {
      getState: () => currentState,
      applyConfigPatch,
    },
    petModelCatalog: {
      removeLocalModel,
      refresh,
      normalizeModelId: () => 'hiyori',
      getModelById: () => ({ id: 'hiyori', type: 'live2d' }),
      getCatalog: (activeModelId: string | null) => ({
        activeModelId,
        models: [{ id: 'hiyori', type: 'live2d', source: 'bundled' }],
      }),
      getLocalModelRoots: () => ({ live2d: 'live2d-root', vrm: 'vrm-root' }),
    },
    applyStateToLive2D,
  } as unknown as HttpRouteContext
  const { response, getStatus, getJson } = createJsonResponse()
  const handled = await handlePetRoutes(
    createJsonRequest(body),
    response,
    'POST',
    new URL('http://127.0.0.1:38945/api/pet/model/delete'),
    context,
  )

  return { handled, status: getStatus(), payload: getJson(), removeLocalModel, refresh, applyConfigPatch, applyStateToLive2D }
}

describe('pet routes', () => {
  it('rejects malformed Live2D asset path encoding', async () => {
    const result = await runLive2dAssetRoute('/api/pet/assets/live2d/%E0%A4%A')

    expect(result.handled).toBe(true)
    expect(result.status).toBe(400)
    expect(result.payload).toEqual({ success: false, error: 'Invalid path encoding' })
    expect(result.resolveLocalLive2dAsset).not.toHaveBeenCalled()
  })

  it('refreshes the model catalog without persisting a fallback over stale active model ids', async () => {
    const result = await runCatalogRoute()

    expect(result.handled).toBe(true)
    expect(result.status).toBe(200)
    expect(result.refresh).toHaveBeenCalled()
    expect(result.applyConfigPatch).not.toHaveBeenCalled()
    expect(result.applyStateToLive2D).not.toHaveBeenCalled()
    expect(result.payload).toEqual({
      activeModelId: 'hiyori',
      models: [{ id: 'hiyori', type: 'live2d', source: 'bundled' }],
    })
  })

  it('updates pet config without normalizing the current model id when no model id is provided', async () => {
    const result = await runConfigRoute({ locked: true })

    expect(result.handled).toBe(true)
    expect(result.status).toBe(200)
    expect(result.getModelById).not.toHaveBeenCalled()
    expect(result.applyConfigPatch).toHaveBeenCalledWith({ locked: true })
    expect(result.applyStateToLive2D).toHaveBeenCalledWith({
      modelId: 'local:vrm/hero',
      modelType: 'vrm',
      locked: true,
    })
  })

  it('forwards lip-sync calibration through the pet config route', async () => {
    const lipSyncProfile = {
      gain: 6.4,
      noiseGate: 0.012,
      maxOpen: 0.85,
      attack: 0.55,
      release: 0.3,
    }
    const result = await runConfigRoute({ lipSyncProfile })

    expect(result.handled).toBe(true)
    expect(result.status).toBe(200)
    expect(result.applyConfigPatch).toHaveBeenCalledWith({ lipSyncProfile })
    expect(result.applyStateToLive2D).toHaveBeenCalledWith(expect.objectContaining({
      lipSyncProfile,
    }))
  })

  it('persists model selections through the pet model route with the catalog model type', async () => {
    const result = await runSelectPetModelRoute(
      { modelId: 'local:vrm/hero' },
      { id: 'local:vrm/hero', type: 'vrm' },
    )

    expect(result.handled).toBe(true)
    expect(result.status).toBe(200)
    expect(result.applyConfigPatch).toHaveBeenCalledWith({
      modelId: 'local:vrm/hero',
      modelType: 'vrm',
    })
    expect(result.applyStateToLive2D).toHaveBeenCalledWith({
      modelId: 'local:vrm/hero',
      modelType: 'vrm',
    })
  })

  it('forwards valid behavior state payloads to the pet renderer', async () => {
    const result = await runPetRoute('/api/pet/behavior-state', { state: 'curious', durationMs: 1200 })

    expect(result.handled).toBe(true)
    expect(result.status).toBe(200)
    expect(result.payload).toEqual({ success: true })
    expect(result.sendToRenderer).toHaveBeenCalledWith('pet:behavior-state', {
      state: 'curious',
      durationMs: 1200,
    })
  })

  it('skips automation-triggered motion while do-not-disturb is enabled', async () => {
    const result = await runPetRoute('/api/pet/animation', { group: 'Idle', index: 0, source: 'automation' }, { doNotDisturb: true })

    expect(result.handled).toBe(true)
    expect(result.status).toBe(200)
    expect(result.payload).toEqual({ success: true, skipped: true, reason: 'do-not-disturb' })
    expect(result.sendToRenderer).not.toHaveBeenCalled()
  })

  it('rejects invalid behavior state payloads before renderer dispatch', async () => {
    const result = await runPetRoute('/api/pet/behavior-state', { state: 'sleeping' })

    expect(result.handled).toBe(true)
    expect(result.status).toBe(400)
    expect(result.payload).toEqual({ success: false, error: 'Invalid behavior state' })
    expect(result.sendToRenderer).not.toHaveBeenCalled()
  })


  it('forwards structured pet control directives to the pet renderer', async () => {
    const result = await runPetRoute('/api/pet/control-directive', {
      expressionMix: [{ expression: 'happy', weight: 1 }],
      parameterOverrides: [{ id: 'ParamMouthOpenY', value: 0.5, weight: 1 }],
      motion: { group: 'Idle', index: 0 },
      intensity: 0.8,
      durationMs: 1200,
    })

    expect(result.handled).toBe(true)
    expect(result.status).toBe(200)
    expect(result.payload).toEqual({ success: true })
    expect(result.sendToRenderer).toHaveBeenCalledWith('pet:trigger-expression-mix', {
      expressionMix: [{ expression: 'happy', weight: 1 }],
      expressions: [{ expression: 'happy', weight: 1 }],
      parameterOverrides: [{ id: 'ParamMouthOpenY', value: 0.5, weight: 1 }],
      motion: { group: 'Idle', index: 0 },
      intensity: 0.8,
      durationMs: 1200,
    })
  })

  it('normalizes companion idle profiles before renderer dispatch', async () => {
    const result = await runPetRoute('/api/pet/companion-idle-profile', {
      supportStyle: ' cheerful ',
      mood: 'warm',
      relationshipStage: 'close',
      relationshipTrend: 'improving',
      energy: 2,
      affinity: 0.8,
      trust: '0.7',
      intimacy: -1,
      interruptibility: 1.2,
      fatigue: 0.2,
      recentTrustShiftCount: 1.8,
      recentGratitudeCount: 101,
    })

    expect(result.handled).toBe(true)
    expect(result.status).toBe(200)
    expect(result.payload).toEqual({
      success: true,
      profile: {
        supportStyle: 'cheerful',
        mood: 'warm',
        relationshipStage: 'close',
        relationshipTrend: 'improving',
        energy: 1,
        affinity: 0.8,
        trust: 0.7,
        intimacy: 0,
        interruptibility: 1,
        fatigue: 0.2,
        recentTrustShiftCount: 1,
        recentGratitudeCount: 100,
      },
    })
    expect(result.applyCompanionIdleProfile).toHaveBeenCalledWith({
      supportStyle: 'cheerful',
      mood: 'warm',
      relationshipStage: 'close',
      relationshipTrend: 'improving',
      energy: 1,
      affinity: 0.8,
      trust: 0.7,
      intimacy: 0,
      interruptibility: 1,
      fatigue: 0.2,
      recentTrustShiftCount: 1,
      recentGratitudeCount: 100,
    })
  })

  it('forwards safe lip sync audio URLs to the pet renderer', async () => {
    const result = await runPetRoute('/api/pet/lipsync', {
      enabled: true,
      audioUrl: 'https://example.test/audio.wav',
    })

    expect(result.handled).toBe(true)
    expect(result.status).toBe(200)
    expect(result.payload).toEqual({ success: true })
    expect(result.sendToRenderer).toHaveBeenCalledWith('pet:lipsync-start', {
      audioUrl: 'https://example.test/audio.wav',
    })
  })

  it('rejects unsafe lip sync URL schemes', async () => {
    const result = await runPetRoute('/api/pet/lipsync', {
      enabled: true,
      audioUrl: 'javascript:alert(1)',
    })

    expect(result.handled).toBe(true)
    expect(result.status).toBe(400)
    expect(result.payload).toEqual({ success: false, error: 'Invalid lip sync audio URL' })
    expect(result.sendToRenderer).not.toHaveBeenCalled()
  })

  it('rejects local file lip sync URLs', async () => {
    const result = await runPetRoute('/api/pet/lipsync', {
      enabled: true,
      audioUrl: 'file:///tmp/reply.wav',
    })

    expect(result.handled).toBe(true)
    expect(result.status).toBe(400)
    expect(result.payload).toEqual({ success: false, error: 'Invalid lip sync audio URL' })
    expect(result.sendToRenderer).not.toHaveBeenCalled()
  })

  it('stops lip sync without requiring an audio URL', async () => {
    const result = await runPetRoute('/api/pet/lipsync', { enabled: false })

    expect(result.handled).toBe(true)
    expect(result.status).toBe(200)
    expect(result.payload).toEqual({ success: true })
    expect(result.sendToRenderer).toHaveBeenCalledWith('pet:lipsync-stop', {})
  })

  it('marks interrupted lip sync stops for renderer feedback', async () => {
    const result = await runPetRoute('/api/pet/lipsync', {
      enabled: false,
      interrupted: true,
    })

    expect(result.handled).toBe(true)
    expect(result.status).toBe(200)
    expect(result.payload).toEqual({ success: true })
    expect(result.sendToRenderer).toHaveBeenCalledWith('pet:lipsync-stop', { interrupted: true })
  })

  it('rejects move requests while pet position is locked', async () => {
    const result = await runMoveRoute(true)

    expect(result.handled).toBe(true)
    expect(result.status).toBe(409)
    expect(result.payload).toEqual({ success: false, error: 'Pet position is locked' })
    expect(result.applyConfigPatch).not.toHaveBeenCalled()
  })

  it('persists move requests when pet position is unlocked', async () => {
    const result = await runMoveRoute(false)

    expect(result.handled).toBe(true)
    expect(result.status).toBe(200)
    expect(result.applyConfigPatch).toHaveBeenCalledWith({
      positionX: 42,
      positionY: 64,
      placement: 'free',
    })
  })

  it('applies display-aware placement presets', async () => {
    const result = await runPlaceRoute({ placement: 'top-left', displayId: 7 })

    expect(result.handled).toBe(true)
    expect(result.status).toBe(200)
    expect(result.place).toHaveBeenCalledWith('top-left', 7)
    expect(result.applyStateToLive2D).toHaveBeenCalledWith({
      modelId: 'hiyori',
      placement: 'top-left',
      displayId: 7,
      positionX: null,
      positionY: null,
    })
  })

  it('imports VRM models through the local model route and selects them immediately', async () => {
    const result = await runModelImportRoute({ sourcePath: 'C:/models/hero.vrm', modelType: 'vrm' })

    expect(result.handled).toBe(true)
    expect(result.status).toBe(200)
    expect(result.importLocalVrmModel).toHaveBeenCalledWith('C:/models/hero.vrm')
    expect(result.applyConfigPatch).toHaveBeenCalledWith({
      modelId: 'local:vrm/hero',
      modelType: 'vrm',
    })
    expect(result.payload).toEqual(expect.objectContaining({
      success: true,
      importedModelId: 'local:vrm/hero',
      modelRoots: { live2d: 'live2d-root', vrm: 'vrm-root' },
    }))
  })

  it('imports Live2D models directly from the picker and selects them immediately', async () => {
    vi.mocked(dialog.showOpenDialog).mockResolvedValue({
      canceled: false,
      filePaths: ['C:/models/hiyori.zip'],
    })
    const result = await runModelImportFromPickerRoute({ modelType: 'live2d' })

    expect(result.handled).toBe(true)
    expect(result.status).toBe(200)
    expect(dialog.showOpenDialog).toHaveBeenCalledWith(expect.objectContaining({
      title: 'Import Live2D model',
      properties: ['openFile', 'openDirectory'],
    }))
    expect(result.importLocalLive2dModel).toHaveBeenCalledWith('C:/models/hiyori.zip')
    expect(result.applyConfigPatch).toHaveBeenCalledWith({
      modelId: 'local:hiyori',
      modelType: 'live2d',
    })
    expect(result.payload).toEqual(expect.objectContaining({
      success: true,
      canceled: false,
      importedModelId: 'local:hiyori',
      sourcePath: 'C:/models/hiyori.zip',
    }))
  })

  it('auto-detects a VRM folder through the local model route and selects it immediately', async () => {
    const modelDir = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-route-vrm-'))
    try {
      fs.writeFileSync(path.join(modelDir, 'hero.vrm'), 'vrm-binary-placeholder', 'utf8')
      const result = await runModelImportRoute({ sourcePath: modelDir, modelType: 'auto' })

      expect(result.handled).toBe(true)
      expect(result.status).toBe(200)
      expect(result.importLocalVrmModel).toHaveBeenCalledWith(modelDir)
      expect(result.applyConfigPatch).toHaveBeenCalledWith({
        modelId: 'local:vrm/hero',
        modelType: 'vrm',
      })
      expect(result.payload).toEqual(expect.objectContaining({
        success: true,
        modelType: 'vrm',
        importedModelId: 'local:vrm/hero',
      }))
    } finally {
      fs.rmSync(modelDir, { recursive: true, force: true })
    }
  })

  it('asks for an explicit type when auto import sees both Live2D and VRM files', async () => {
    const modelDir = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-route-mixed-'))
    try {
      fs.writeFileSync(path.join(modelDir, 'hero.model3.json'), '{}', 'utf8')
      fs.writeFileSync(path.join(modelDir, 'hero.vrm'), 'vrm-binary-placeholder', 'utf8')
      const result = await runModelImportRoute({ sourcePath: modelDir, modelType: 'auto' })

      expect(result.handled).toBe(true)
      expect(result.status).toBe(400)
      expect(result.payload).toEqual(expect.objectContaining({
        success: false,
        error: expect.stringContaining('Live2D'),
      }))
      expect(result.importLocalVrmModel).not.toHaveBeenCalled()
    } finally {
      fs.rmSync(modelDir, { recursive: true, force: true })
    }
  })

  it('auto-detects a Live2D folder from the picker and selects it immediately', async () => {
    const modelDir = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-route-live2d-'))
    try {
      fs.writeFileSync(path.join(modelDir, 'hero.model3.json'), '{}', 'utf8')
      vi.mocked(dialog.showOpenDialog).mockResolvedValue({
        canceled: false,
        filePaths: [modelDir],
      })
      const result = await runModelImportFromPickerRoute({ modelType: 'auto' })

      expect(result.handled).toBe(true)
      expect(result.status).toBe(200)
      expect(dialog.showOpenDialog).toHaveBeenCalledWith(expect.objectContaining({
        title: 'Import Live2D or 3D model folder',
        properties: ['openDirectory'],
      }))
      expect(result.importLocalLive2dModel).toHaveBeenCalledWith(modelDir)
      expect(result.applyConfigPatch).toHaveBeenCalledWith({
        modelId: 'local:hiyori',
        modelType: 'live2d',
      })
      expect(result.payload).toEqual(expect.objectContaining({
        success: true,
        canceled: false,
        modelType: 'live2d',
        importedModelId: 'local:hiyori',
        sourcePath: modelDir,
      }))
    } finally {
      fs.rmSync(modelDir, { recursive: true, force: true })
    }
  })

  it('deletes local models, refreshes the catalog, and falls back to an available model', async () => {
    const result = await runModelDeleteRoute({ modelId: 'local:old' })

    expect(result.handled).toBe(true)
    expect(result.status).toBe(200)
    expect(result.removeLocalModel).toHaveBeenCalledWith('local:old')
    expect(result.refresh).toHaveBeenCalled()
    expect(result.applyConfigPatch).toHaveBeenCalledWith({
      modelId: 'hiyori',
      modelType: 'live2d',
    })
    expect(result.applyStateToLive2D).toHaveBeenCalledWith({
      modelId: 'hiyori',
      modelType: 'live2d',
    })
    expect(result.payload).toEqual({
      success: true,
      state: { modelId: 'hiyori', modelType: 'live2d' },
      catalog: {
        activeModelId: 'hiyori',
        models: [{ id: 'hiyori', type: 'live2d', source: 'bundled' }],
      },
      modelRoots: { live2d: 'live2d-root', vrm: 'vrm-root' },
    })
  })
})
