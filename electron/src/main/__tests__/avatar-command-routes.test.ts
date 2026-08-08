import { EventEmitter } from 'node:events'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { describe, expect, it, vi } from 'vitest'
import { handlePetRoutes } from '../http/routes/pet-routes'
import type { HttpRouteContext } from '../http/types'

const request = (body?: unknown): IncomingMessage => {
  const req = new EventEmitter() as EventEmitter & { setEncoding: () => void }
  req.setEncoding = () => {}
  queueMicrotask(() => {
    if (body !== undefined) req.emit('data', JSON.stringify(body))
    req.emit('end')
  })
  return req as unknown as IncomingMessage
}

const response = (): { value: () => unknown; status: () => number | null; res: ServerResponse } => {
  let statusCode: number | null = null
  let payload = ''
  const res = {
    getHeader: () => undefined,
    writeHead: (status: number) => {
      statusCode = status
      return res
    },
    end: (body: string) => {
      payload = body
      return res
    },
  }
  return {
    value: () => JSON.parse(payload),
    status: () => statusCode,
    res: res as unknown as ServerResponse,
  }
}

const context = (overrides: Record<string, unknown> = {}): HttpRouteContext => ({
  live2dWindow: {
    getAvatarCapabilities: () => null,
    requestAvatarCapabilities: vi.fn(),
    sendAvatarCommand: vi.fn(),
    ...overrides,
  },
  petStateStore: {
    getState: () => ({ doNotDisturb: false }),
  },
} as unknown as HttpRouteContext)

describe('avatar command routes', () => {
  it('returns cached capabilities without starting a polling loop', async () => {
    const capabilities = { revision: 'vrm:model:1', modelType: 'vrm', modelId: 'model', generatedAt: 1 }
    const result = response()
    const handled = await handlePetRoutes(
      request(),
      result.res,
      'GET',
      new URL('http://127.0.0.1/api/pet/avatar-capabilities'),
      context({ getAvatarCapabilities: () => capabilities }),
    )

    expect(handled).toBe(true)
    expect(result.status()).toBe(200)
    expect(result.value()).toEqual({ success: true, capabilities })
  })

  it('waits for a renderer ACK and exposes degraded results', async () => {
    const ack = {
      commandId: 'cmd-1',
      sequence: 1,
      status: 'degraded',
      message: 'No VRM animation clip source is loaded',
      at: 2,
    }
    const sendAvatarCommand = vi.fn().mockResolvedValue(ack)
    const result = response()
    const handled = await handlePetRoutes(
      request({
        source: 'automation',
        command: {
          version: 1,
          id: 'cmd-1',
          streamId: 'python:test',
          sequence: 1,
          issuedAt: Date.now(),
          priority: 20,
          interrupt: 'replace',
          actions: [{ type: 'motion', group: 'Wave', index: 0 }],
        },
      }),
      result.res,
      'POST',
      new URL('http://127.0.0.1/api/pet/avatar-command'),
      context({ sendAvatarCommand }),
    )

    expect(handled).toBe(true)
    expect(result.status()).toBe(200)
    expect(result.value()).toEqual({ success: true, result: ack })
    expect(sendAvatarCommand).toHaveBeenCalledWith(expect.objectContaining({
      id: 'cmd-1',
      streamId: 'python:test',
      version: 1,
    }))
  })

  it('rejects malformed v1 payloads before reaching the renderer', async () => {
    const sendAvatarCommand = vi.fn().mockResolvedValue({
      commandId: 'cmd-dnd',
      sequence: 2,
      status: 'accepted',
      at: Date.now(),
    })
    const result = response()
    await handlePetRoutes(
      request({ command: { version: 1, id: '', streamId: '', sequence: -1, actions: [] } }),
      result.res,
      'POST',
      new URL('http://127.0.0.1/api/pet/avatar-command'),
      context({ sendAvatarCommand }),
    )

    expect(result.status()).toBe(400)
    expect(sendAvatarCommand).not.toHaveBeenCalled()
  })

  it('applies do-not-disturb gating to automation avatar commands', async () => {
    const sendAvatarCommand = vi.fn().mockResolvedValue({
      commandId: 'cmd-dnd',
      sequence: 2,
      status: 'accepted',
      at: Date.now(),
    })
    const result = response()
    await handlePetRoutes(
      request({
        source: 'automation',
        command: {
          version: 1,
          id: 'cmd-dnd',
          streamId: 'python:test',
          sequence: 2,
          issuedAt: Date.now(),
          priority: 20,
          interrupt: 'replace',
          actions: [{ type: 'behavior', behavior: 'idle' }],
        },
      }),
      result.res,
      'POST',
      new URL('http://127.0.0.1/api/pet/avatar-command'),
      context({
        sendAvatarCommand,
        getState: undefined,
      }),
    )

    const dndContext = context({ sendAvatarCommand })
    dndContext.petStateStore.getState = () => ({ doNotDisturb: true }) as never
    const dndResult = response()
    await handlePetRoutes(
      request({
        source: 'automation',
        command: {
          version: 1,
          id: 'cmd-dnd',
          streamId: 'python:test',
          sequence: 2,
          issuedAt: Date.now(),
          priority: 20,
          interrupt: 'replace',
          actions: [{ type: 'behavior', behavior: 'idle' }],
        },
      }),
      dndResult.res,
      'POST',
      new URL('http://127.0.0.1/api/pet/avatar-command'),
      dndContext,
    )

    expect(dndResult.value()).toEqual({ success: true, skipped: true, reason: 'do-not-disturb' })
    expect(sendAvatarCommand).toHaveBeenCalledTimes(1)
  })
})
