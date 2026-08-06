import { EventEmitter } from 'node:events'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { describe, expect, it, vi } from 'vitest'
import { handleModelRoutes } from '../http/routes/model-routes'
import type { HttpRouteContext } from '../http/types'

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

const runSetModelRoute = async (body: unknown, model: { id: string; type: 'live2d' | 'vrm' } | null) => {
  const applyConfigPatch = vi.fn((patch: unknown) => ({ ...(patch as Record<string, unknown>) }))
  const applyStateToLive2D = vi.fn((state: unknown) => state)
  const context = {
    petStateStore: {
      applyConfigPatch,
    },
    petModelCatalog: {
      getDefaultModelId: vi.fn(() => 'fallback-live2d'),
      getModelById: vi.fn((modelId: string | null) => (model && modelId === model.id ? model : null)),
    },
    applyStateToLive2D,
  } as unknown as HttpRouteContext
  const { response, getStatus, getJson } = createJsonResponse()
  const handled = await handleModelRoutes(
    createJsonRequest(body),
    response,
    'POST',
    new URL('http://127.0.0.1:38945/api/model/set'),
    context,
  )

  return { handled, status: getStatus(), payload: getJson(), applyConfigPatch, applyStateToLive2D }
}

describe('model routes', () => {
  it('rejects unknown model ids instead of falling back and persisting the default model', async () => {
    const result = await runSetModelRoute({ modelId: 'llm-live2d/yumi', modelType: 'live2d' }, null)

    expect(result.handled).toBe(true)
    expect(result.status).toBe(404)
    expect(result.payload).toEqual({ success: false, error: 'Model not found' })
    expect(result.applyConfigPatch).not.toHaveBeenCalled()
    expect(result.applyStateToLive2D).not.toHaveBeenCalled()
  })

  it('persists the matched model type from the catalog', async () => {
    const result = await runSetModelRoute(
      { modelId: 'local:vrm/hero', modelType: 'live2d' },
      { id: 'local:vrm/hero', type: 'vrm' },
    )

    expect(result.handled).toBe(true)
    expect(result.status).toBe(200)
    expect(result.applyConfigPatch).toHaveBeenCalledWith({
      modelId: 'local:vrm/hero',
      modelType: 'vrm',
    })
  })
})
