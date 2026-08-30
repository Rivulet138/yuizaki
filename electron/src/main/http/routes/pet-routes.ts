import { createReadStream } from 'fs'
import {
  PET_SCALE_DEFAULT,
  PET_SCALE_MIN,
  PET_SCALE_MAX,
} from '../../../shared/pet-control'
import type {
  PetCompanionIdleProfile,
  PetControlConfigPatch,
  PetControlSource,
  PetPlacement,
} from '../../../shared/pet-control'
import { normalizeAvatarCommand, type AvatarCommand } from '../../../shared/avatar-command'
import type { HttpRouteHandler } from '../types'
import { parseRequestBody, sendJson } from '../utils'
import {
  deleteLocalModelById,
  importLocalModelFromPath,
  isModelImportMode,
  pickLocalModelSource,
  refreshPetCatalog,
} from '../../pet-local-model-import'

type PetBehaviorState =
  | 'idle'
  | 'thinking'
  | 'speaking'
  | 'reacting'
  | 'sleepy'
  | 'waiting'
  | 'curious'
  | 'focused'
  | 'interrupted'

const PET_BEHAVIOR_STATES = new Set<PetBehaviorState>([
  'idle',
  'thinking',
  'speaking',
  'reacting',
  'sleepy',
  'waiting',
  'curious',
  'focused',
  'interrupted',
])

const isPetBehaviorState = (value: unknown): value is PetBehaviorState =>
  typeof value === 'string' && PET_BEHAVIOR_STATES.has(value as PetBehaviorState)

const isPlacement = (value: unknown): value is PetPlacement =>
  value === 'bottom-right' ||
  value === 'bottom-left' ||
  value === 'top-right' ||
  value === 'top-left' ||
  value === 'center' ||
  value === 'free'

const isAutomationSource = (value: unknown): value is PetControlSource => value === 'automation'

const shouldSkipAutomation = (ctx: Parameters<HttpRouteHandler>[4], source: unknown): boolean =>
  isAutomationSource(source) && ctx.petStateStore.getState().doNotDisturb

const sendAutomationSkipped = (res: Parameters<HttpRouteHandler>[1]): void => {
  sendJson(res, 200, { success: true, skipped: true, reason: 'do-not-disturb' })
}

const ASSET_MIME_TYPES: Record<string, string> = {
  '.json': 'application/json; charset=utf-8',
  '.moc3': 'application/octet-stream',
  '.png': 'image/png',
  '.webp': 'image/webp',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.motion3.json': 'application/json; charset=utf-8',
  '.physics3.json': 'application/json; charset=utf-8',
  '.pose3.json': 'application/json; charset=utf-8',
  '.cdi3.json': 'application/json; charset=utf-8',
  '.exp3.json': 'application/json; charset=utf-8',
}

const sendLocalModelAsset = (res: Parameters<HttpRouteHandler>[1], filePath: string): void => {
  const lowerPath = filePath.toLowerCase()
  const matchedType = Object.entries(ASSET_MIME_TYPES).find(([extension]) => lowerPath.endsWith(extension))?.[1]
  res.writeHead(200, { 'Content-Type': matchedType ?? 'application/octet-stream' })
  createReadStream(filePath).pipe(res)
}

const clampUnit = (value: unknown): number | null => {
  if (value == null || value === '') {
    return null
  }
  const number = Number(value)
  return Number.isFinite(number) ? Math.max(0, Math.min(1, number)) : null
}

const normalizeOptionalString = (value: unknown): string | null =>
  typeof value === 'string' && value.trim() ? value.trim().slice(0, 64) : null

const normalizeCount = (value: unknown): number | null => {
  if (value == null || value === '') {
    return null
  }
  const number = Number(value)
  return Number.isFinite(number) ? Math.max(0, Math.min(100, Math.floor(number))) : null
}

const normalizeCompanionIdleProfile = (body: PetCompanionIdleProfile): PetCompanionIdleProfile => ({
  supportStyle: normalizeOptionalString(body.supportStyle),
  mood: normalizeOptionalString(body.mood),
  relationshipStage: normalizeOptionalString(body.relationshipStage),
  relationshipTrend: normalizeOptionalString(body.relationshipTrend),
  energy: clampUnit(body.energy),
  affinity: clampUnit(body.affinity),
  trust: clampUnit(body.trust),
  intimacy: clampUnit(body.intimacy),
  interruptibility: clampUnit(body.interruptibility),
  fatigue: clampUnit(body.fatigue),
  recentTrustShiftCount: normalizeCount(body.recentTrustShiftCount),
  recentGratitudeCount: normalizeCount(body.recentGratitudeCount),
})

const resolveSafeLipSyncUrl = (audioUrl: string): string | null => {
  try {
    const parsedUrl = new URL(audioUrl)
    if (parsedUrl.protocol === 'http:' || parsedUrl.protocol === 'https:') {
      return parsedUrl.toString()
    }
  } catch {
    return null
  }

  return null
}

export const handlePetRoutes: HttpRouteHandler = async (req, res, method, url, ctx) => {
  if (method === 'GET' && url.pathname.startsWith('/api/pet/assets/live2d/')) {
    let relativeAssetPath: string
    try {
      relativeAssetPath = decodeURIComponent(url.pathname.replace('/api/pet/assets/live2d/', ''))
    } catch {
      sendJson(res, 400, { success: false, error: 'Invalid path encoding' })
      return true
    }
    const assetPath = ctx.petModelCatalog.resolveLocalLive2dAsset(relativeAssetPath)
    if (!assetPath) {
      sendJson(res, 404, { success: false, error: 'Local model asset not found' })
      return true
    }
    sendLocalModelAsset(res, assetPath)
    return true
  }

  if (method === 'GET' && url.pathname.startsWith('/api/pet/assets/vrm/')) {
    let relativeAssetPath: string
    try {
      relativeAssetPath = decodeURIComponent(url.pathname.replace('/api/pet/assets/vrm/', ''))
    } catch {
      sendJson(res, 400, { success: false, error: 'Invalid path encoding' })
      return true
    }
    const assetPath = ctx.petModelCatalog.resolveLocalVrmAsset(relativeAssetPath)
    if (!assetPath) {
      sendJson(res, 404, { success: false, error: 'Local VRM asset not found' })
      return true
    }
    sendLocalModelAsset(res, assetPath)
    return true
  }

  if (method === 'GET' && url.pathname === '/api/pet/state') {
    ctx.live2dWindow.requestPetState()
    sendJson(res, 200, ctx.petStateStore.getState())
    return true
  }

  if (method === 'GET' && url.pathname === '/api/pet/displays') {
    const displays = ctx.live2dWindow.getDisplays()
    sendJson(res, 200, {
      activeDisplayId: ctx.petStateStore.getState().displayId ?? displays.find((display) => display.primary)?.id ?? null,
      displays,
    })
    return true
  }

  if (method === 'GET' && url.pathname === '/api/pet/catalog') {
    sendJson(res, 200, refreshPetCatalog(ctx).catalog)
    return true
  }

  if (method === 'POST' && url.pathname === '/api/pet/model/pick') {
    const body = await parseRequestBody<{ modelType?: unknown }>(req)
    const modelType = isModelImportMode(body.modelType) ? body.modelType : 'live2d'
    sendJson(res, 200, await pickLocalModelSource(modelType))
    return true
  }

  if (method === 'POST' && url.pathname === '/api/pet/model/import-from-picker') {
    const body = await parseRequestBody<{ modelType?: unknown }>(req)
    const modelType = isModelImportMode(body.modelType) ? body.modelType : 'live2d'
    const picked = await pickLocalModelSource(modelType)
    if (!picked.sourcePath) {
      sendJson(res, 200, {
        success: false,
        canceled: true,
        modelType,
        sourcePath: null,
      })
      return true
    }
    try {
      sendJson(res, 200, {
        ...(await importLocalModelFromPath(ctx, picked.sourcePath, modelType)),
        canceled: false,
        sourcePath: picked.sourcePath,
      })
    } catch (error) {
      sendJson(res, 400, {
        success: false,
        canceled: false,
        modelType,
        sourcePath: picked.sourcePath,
        error: error instanceof Error ? error.message : String(error),
      })
    }
    return true
  }

  if (method === 'POST' && url.pathname === '/api/pet/model/import') {
    const body = await parseRequestBody<{ sourcePath?: string; modelType?: unknown }>(req)
    const modelType = isModelImportMode(body.modelType) ? body.modelType : 'live2d'
    try {
      sendJson(res, 200, await importLocalModelFromPath(ctx, body.sourcePath ?? '', modelType))
    } catch (error) {
      sendJson(res, 400, {
        success: false,
        error: error instanceof Error ? error.message : String(error),
      })
    }
    return true
  }

  if (method === 'POST' && url.pathname === '/api/pet/model/delete') {
    const body = await parseRequestBody<{ modelId?: string }>(req)
    const result = body.modelId ? deleteLocalModelById(ctx, body.modelId) : null
    if (!result) {
      sendJson(res, 404, { success: false, error: 'Local model not found' })
      return true
    }
    sendJson(res, 200, result)
    return true
  }

  if (method === 'POST' && url.pathname === '/api/pet/config') {
    const body = await parseRequestBody<PetControlConfigPatch>(req)
    const normalizedPatch: PetControlConfigPatch = {
      ...body,
    }
    if ('modelId' in body) {
      if (typeof body.modelId === 'string') {
        const matchedModel = ctx.petModelCatalog.getModelById(body.modelId)
        if (!matchedModel) {
          sendJson(res, 404, { success: false, error: 'Model not found' })
          return true
        }
        normalizedPatch.modelId = matchedModel.id
        if (!normalizedPatch.modelType) {
          normalizedPatch.modelType = matchedModel.type
        }
      } else if (body.modelId === null) {
        normalizedPatch.modelId = null
      } else {
        delete normalizedPatch.modelId
      }
    }
    let patchedState = ctx.petStateStore.applyConfigPatch(normalizedPatch)
    if (normalizedPatch.clickThrough === true) {
      ctx.live2dWindow.setInteractMode(false)
      patchedState = ctx.petStateStore.setInteractMode(false)
    }
    const nextState = ctx.applyStateToLive2D(patchedState)
    sendJson(res, 200, nextState)
    return true
  }

  if (method === 'POST' && url.pathname === '/api/pet/model') {
    const body = await parseRequestBody<{ modelId?: string | null }>(req)
    const requestedModelId = typeof body.modelId === 'string' ? body.modelId : null
    const matchedModel = requestedModelId
      ? ctx.petModelCatalog.getModelById(requestedModelId)
      : ctx.petModelCatalog.getModelById(ctx.petModelCatalog.getDefaultModelId())
    if (!matchedModel) {
      sendJson(res, 404, { success: false, error: 'Model not found' })
      return true
    }
    const patch: PetControlConfigPatch = { modelId: matchedModel.id, modelType: matchedModel.type }
    const nextState = ctx.applyStateToLive2D(ctx.petStateStore.applyConfigPatch(patch))
    sendJson(res, 200, nextState)
    return true
  }

  if (method === 'POST' && url.pathname === '/api/pet/interact') {
    const body = await parseRequestBody<{ enabled?: boolean }>(req)
    const enabled = Boolean(body.enabled)
    ctx.live2dWindow.setInteractMode(enabled)
    let nextState = ctx.petStateStore.setInteractMode(enabled)
    if (enabled) {
      ctx.live2dWindow.show()
      ctx.live2dWindow.setLocked(false)
      ctx.live2dWindow.setClickThrough(false)
      nextState = ctx.petStateStore.applyConfigPatch({ visible: true, locked: false, clickThrough: false })
    }
    sendJson(res, 200, ctx.applyStateToLive2D(nextState))
    return true
  }

  if (method === 'POST' && url.pathname === '/api/pet/dock') {
    const nextState = ctx.applyStateToLive2D(ctx.petStateStore.dockBottomRight())
    sendJson(res, 200, nextState)
    return true
  }

  if (method === 'POST' && url.pathname === '/api/pet/place') {
    const body = await parseRequestBody<{ placement?: unknown; displayId?: unknown }>(req)
    if (!isPlacement(body.placement) || body.placement === 'free') {
      sendJson(res, 400, { success: false, error: 'Invalid placement preset' })
      return true
    }

    const displayId = body.displayId === null || body.displayId === undefined ? null : Number(body.displayId)
    if (displayId !== null && !Number.isFinite(displayId)) {
      sendJson(res, 400, { success: false, error: 'Invalid display id' })
      return true
    }

    const nextState = ctx.applyStateToLive2D(ctx.petStateStore.place(body.placement, displayId))
    sendJson(res, 200, nextState)
    return true
  }

  if (method === 'POST' && url.pathname === '/api/pet/reload') {
    ctx.live2dWindow.reloadRenderer()
    sendJson(res, 200, { success: true })
    return true
  }

  if (method === 'POST' && url.pathname === '/api/pet/visibility') {
    const body = await parseRequestBody<{ visible?: boolean }>(req)
    if (body.visible === false) {
      ctx.live2dWindow.hide()
      ctx.petStateStore.setVisible(false)
      sendJson(res, 200, { success: true, visible: false })
      return true
    }
    ctx.live2dWindow.show()
    ctx.petStateStore.setVisible(true)
    sendJson(res, 200, { success: true, visible: true })
    return true
  }

  if (method === 'GET' && url.pathname === '/api/pet/avatar-capabilities') {
    const capabilities = ctx.live2dWindow.getAvatarCapabilities?.() ?? null
    if (!capabilities) {
      ctx.live2dWindow.requestAvatarCapabilities?.()
      sendJson(res, 503, { success: false, error: 'Pet renderer capabilities are not ready' })
      return true
    }
    sendJson(res, 200, { success: true, capabilities })
    return true
  }

  if (method === 'POST' && url.pathname === '/api/pet/avatar-command') {
    const body = await parseRequestBody<{ command?: Partial<AvatarCommand>; source?: PetControlSource }>(req)
    if (shouldSkipAutomation(ctx, body.source)) {
      sendAutomationSkipped(res)
      return true
    }
    // Main-process delivery applies the short transport lease; the HTTP boundary
    // should not discard a command merely because it waited in the backend queue.
    const normalized = normalizeAvatarCommand(body.command, 0)
    if (!normalized.command) {
      sendJson(res, 400, { success: false, error: 'Invalid AvatarCommand v1 payload' })
      return true
    }
    if (!ctx.live2dWindow.sendAvatarCommand) {
      sendJson(res, 503, { success: false, error: 'Pet renderer command transport is unavailable' })
      return true
    }
    const result = await ctx.live2dWindow.sendAvatarCommand(normalized.command)
    const statusCode = result.status === 'rejected'
      ? 409
      : result.status === 'timeout'
        ? 504
        : result.status === 'dropped'
          ? 202
          : 200
    sendJson(res, statusCode, {
      success: result.status !== 'rejected' && result.status !== 'timeout',
      result,
    })
    return true
  }

  if (method === 'POST' && url.pathname === '/api/pet/animation') {
    const body = await parseRequestBody<{ group?: string; index?: number; name?: string; source?: PetControlSource }>(req)
    if (shouldSkipAutomation(ctx, body.source)) {
      sendAutomationSkipped(res)
      return true
    }
    ctx.live2dWindow.sendToRenderer('pet:trigger-animation', {
      name: body.name,
      group: body.group,
      index: body.index,
    })
    sendJson(res, 200, { success: true })
    return true
  }

  if (method === 'POST' && url.pathname === '/api/pet/expression') {
    const body = await parseRequestBody<{ name?: string; source?: PetControlSource }>(req)
    if (shouldSkipAutomation(ctx, body.source)) {
      sendAutomationSkipped(res)
      return true
    }
    ctx.live2dWindow.sendToRenderer('pet:trigger-expression', { name: body.name })
    sendJson(res, 200, { success: true })
    return true
  }

  if (method === 'POST' && (url.pathname === '/api/pet/expression-mix' || url.pathname === '/api/pet/control-directive')) {
    const body = await parseRequestBody<{
      expressions?: Array<{ expression: string; weight?: number }>
      expressionMix?: Array<{ expression: string; weight?: number }>
      intensity?: number
      durationMs?: number
      parameterOverrides?: Array<{ id: string; value: number; weight?: number }>
      motion?: { group: string; index?: number }
      source?: PetControlSource
    }>(req)
    if (shouldSkipAutomation(ctx, body.source)) {
      sendAutomationSkipped(res)
      return true
    }
    const expressionMix = body.expressionMix ?? body.expressions ?? []
    ctx.live2dWindow.sendToRenderer('pet:trigger-expression-mix', {
      ...body,
      expressions: expressionMix,
      expressionMix,
    })
    sendJson(res, 200, { success: true })
    return true
  }

  if (method === 'POST' && url.pathname === '/api/pet/emotion') {
    const body = await parseRequestBody<{ emotionId?: string; source?: PetControlSource }>(req)
    if (shouldSkipAutomation(ctx, body.source)) {
      sendAutomationSkipped(res)
      return true
    }
    const resolvedTrigger = ctx.petModelCatalog.resolveEmotionTrigger(ctx.petStateStore.getState().modelId, body.emotionId ?? '')

    if (!resolvedTrigger) {
      sendJson(res, 404, { success: false, error: 'Emotion preset not found' })
      return true
    }

    ctx.live2dWindow.sendToRenderer('pet:trigger-emotion', resolvedTrigger)
    sendJson(res, 200, { success: true, trigger: resolvedTrigger })
    return true
  }

  if (method === 'POST' && url.pathname === '/api/pet/behavior-state') {
    const body = await parseRequestBody<{ state?: unknown; durationMs?: number; source?: PetControlSource }>(req)
    if (shouldSkipAutomation(ctx, body.source)) {
      sendAutomationSkipped(res)
      return true
    }
    if (!isPetBehaviorState(body.state)) {
      sendJson(res, 400, { success: false, error: 'Invalid behavior state' })
      return true
    }

    ctx.live2dWindow.sendToRenderer('pet:behavior-state', {
      state: body.state,
      durationMs: body.durationMs,
    })
    sendJson(res, 200, { success: true })
    return true
  }

  if (method === 'POST' && url.pathname === '/api/pet/companion-idle-profile') {
    const body = await parseRequestBody<PetCompanionIdleProfile>(req)
    const profile = normalizeCompanionIdleProfile(body)
    ctx.live2dWindow.applyCompanionIdleProfile(profile)
    sendJson(res, 200, { success: true, profile })
    return true
  }

  if (method === 'POST' && url.pathname === '/api/pet/lipsync') {
    const body = await parseRequestBody<{ audioUrl?: string; enabled?: boolean; interrupted?: boolean; source?: PetControlSource }>(req)
    if (body.enabled !== false && shouldSkipAutomation(ctx, body.source)) {
      sendAutomationSkipped(res)
      return true
    }
    if (body.enabled === false || !body.audioUrl) {
      ctx.live2dWindow.sendToRenderer('pet:lipsync-stop', body.interrupted === true ? { interrupted: true } : {})
      sendJson(res, 200, { success: true })
      return true
    }

    const safeAudioUrl = resolveSafeLipSyncUrl(body.audioUrl)
    if (!safeAudioUrl) {
      sendJson(res, 400, { success: false, error: 'Invalid lip sync audio URL' })
      return true
    }

    if (typeof ctx.live2dWindow.startLipSync === 'function') {
      await ctx.live2dWindow.startLipSync(safeAudioUrl)
    } else {
      ctx.live2dWindow.sendToRenderer('pet:lipsync-start', { audioUrl: safeAudioUrl })
    }
    sendJson(res, 200, { success: true })
    return true
  }

  if (method === 'POST' && url.pathname === '/api/pet/move') {
    const body = await parseRequestBody<{ x?: number; y?: number; duration?: number }>(req)
    if (ctx.petStateStore.getState().locked) {
      sendJson(res, 409, { success: false, error: 'Pet position is locked' })
      return true
    }
    const x = Number(body.x)
    const y = Number(body.y)
    if (Number.isFinite(x) && Number.isFinite(y)) {
      let nextState = ctx.petStateStore.applyConfigPatch({
        positionX: x,
        positionY: y,
        placement: 'free',
      })
      ctx.applyPetStateToRenderer?.(nextState)
      nextState = ctx.petStateStore.getState()
      sendJson(res, 200, { success: true, state: nextState })
    } else {
      sendJson(res, 400, { success: false, error: 'Invalid position' })
    }
    return true
  }

  if (method === 'POST' && url.pathname === '/api/pet/scale') {
    const body = await parseRequestBody<{ scale?: number; duration?: number }>(req)
    const scale = Math.max(PET_SCALE_MIN, Math.min(PET_SCALE_MAX, body.scale ?? PET_SCALE_DEFAULT))
    ctx.live2dWindow.setScale(scale)
    let nextState = ctx.petStateStore.applyConfigPatch({ scale })
    ctx.applyPetStateToRenderer?.(nextState)
    nextState = ctx.petStateStore.getState()
    sendJson(res, 200, { success: true, state: nextState })
    return true
  }

  if (method === 'POST' && url.pathname === '/api/pet/opacity') {
    const body = await parseRequestBody<{ opacity?: number }>(req)
    const opacity = Math.max(0.1, Math.min(1.0, body.opacity ?? 1.0))
    ctx.live2dWindow.setOpacity(opacity)
    let nextState = ctx.petStateStore.applyConfigPatch({ opacity })
    ctx.applyPetStateToRenderer?.(nextState)
    nextState = ctx.petStateStore.getState()
    sendJson(res, 200, { success: true, state: { ...nextState, opacity } })
    return true
  }

  if (method === 'GET' && url.pathname === '/api/pet/presets') {
    const presets = [
      { id: 'bottom-right', name: '右下角', placement: 'bottom-right' },
      { id: 'bottom-left', name: '左下角', placement: 'bottom-left' },
      { id: 'top-right', name: '右上角', placement: 'top-right' },
      { id: 'top-left', name: '左上角', placement: 'top-left' },
      { id: 'center', name: '居中', placement: 'center' },
    ]
    sendJson(res, 200, { presets })
    return true
  }

  return false
}
