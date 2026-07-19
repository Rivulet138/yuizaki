import type { PetControlConfigPatch } from '../../../shared/pet-control'
import type { HttpRouteHandler } from '../types'
import { parseRequestBody, sendJson } from '../utils'

export const handleModelRoutes: HttpRouteHandler = async (req, res, method, url, ctx) => {
  if (method === 'GET' && url.pathname === '/api/model/catalog') {
    sendJson(res, 200, ctx.petModelCatalog.getCatalog(ctx.petStateStore.getState().modelId))
    return true
  }

  if (method === 'POST' && url.pathname === '/api/model/set') {
    const body = await parseRequestBody<{ modelId?: string | null; modelType?: 'live2d' | 'vrm' }>(req)
    const requestedModelId = typeof body.modelId === 'string' ? body.modelId : null
    const matchedModel = requestedModelId
      ? ctx.petModelCatalog.getModelById(requestedModelId)
      : ctx.petModelCatalog.getModelById(ctx.petModelCatalog.getDefaultModelId())
    if (!matchedModel) {
      sendJson(res, 404, { success: false, error: 'Model not found' })
      return true
    }
    const patch: PetControlConfigPatch = {
      modelId: matchedModel.id,
      modelType: matchedModel.type,
    }
    const nextState = ctx.applyStateToLive2D(ctx.petStateStore.applyConfigPatch(patch))
    sendJson(res, 200, nextState)
    return true
  }

  if (method === 'POST' && url.pathname === '/api/model/type') {
    const body = await parseRequestBody<{ modelType?: 'live2d' | 'vrm' }>(req)
    const patch: PetControlConfigPatch = {}
    if (body.modelType === 'live2d' || body.modelType === 'vrm') {
      patch.modelType = body.modelType
    }
    const nextState = ctx.applyStateToLive2D(ctx.petStateStore.applyConfigPatch(patch))
    sendJson(res, 200, nextState)
    return true
  }

  return false
}
