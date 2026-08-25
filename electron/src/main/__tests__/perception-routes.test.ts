import { EventEmitter } from 'node:events'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { describe, expect, it, vi } from 'vitest'
import { AuthorizedPerceptionBridge } from '../authorized-perception-bridge'
import { handlePerceptionRoutes } from '../http/routes/perception-routes'

const scope = {
  workspaceId: 'workspace-1',
  sessionId: 'session-1',
  turnId: 'turn-1',
  requestId: 'request-1',
  generationId: 'generation-1',
  interruptionEpoch: 4,
}

const request = (body: unknown, hostToken = 'host-secret'): IncomingMessage => {
  const emitter = new EventEmitter() as EventEmitter & {
    setEncoding: (encoding: BufferEncoding) => void
  }
  emitter.setEncoding = () => {}
  ;(emitter as unknown as { headers: Record<string, string> }).headers = {
    ...(hostToken ? { 'x-yuizaki-host-perception-token': hostToken } : {}),
  }
  queueMicrotask(() => {
    emitter.emit('data', JSON.stringify(body))
    emitter.emit('end')
  })
  return emitter as unknown as IncomingMessage
}

const response = () => {
  let status: number | null = null
  let payload = ''
  const target = {
    getHeader: () => undefined,
    writeHead: (value: number) => {
      status = value
      return target
    },
    end: (value?: string | Buffer) => {
      payload = Buffer.isBuffer(value) ? value.toString('utf8') : value ?? ''
      return target
    },
  }
  return {
    target: target as unknown as ServerResponse,
    status: () => status,
    json: () => JSON.parse(payload) as unknown,
  }
}

describe('authorized perception HTTP routes', () => {
  it('rejects requests that have no renderer-inaccessible host credential', async () => {
    const output = response()
    await handlePerceptionRoutes(
      request({ scope }, ''),
      output.target,
      'POST',
      new URL('http://127.0.0.1/api/perception/collect-clipboard'),
      new AuthorizedPerceptionBridge({ readClipboard: async () => 'must not run' }),
      'host-secret',
    )
    expect(output.status()).toBe(401)
  })

  it('rejects authorization bodies with unknown or caller-selected capability fields', async () => {
    const bridge = new AuthorizedPerceptionBridge({ readClipboard: async () => 'hello' })
    const output = response()

    const handled = await handlePerceptionRoutes(
      request({
        scope,
        capability: 'screenshot',
        executionPermit: 'forged',
      }),
      output.target,
      'POST',
      new URL('http://127.0.0.1/api/perception/collect-clipboard'),
      bridge,
      'host-secret',
    )

    expect(handled).toBe(true)
    expect(output.status()).toBe(400)
    expect(output.json()).toMatchObject({ code: 'PERCEPTION_AUTHORIZATION_INVALID' })
  })

  it('returns full host scope while taking capability only from the fixed route', async () => {
    const bridge = new AuthorizedPerceptionBridge({ readClipboard: async () => 'hello' })
    const output = response()

    await handlePerceptionRoutes(
      request({ scope }),
      output.target,
      'POST',
      new URL('http://127.0.0.1/api/perception/collect-clipboard'),
      bridge,
      'host-secret',
    )

    expect(output.status()).toBe(200)
    expect(output.json()).toMatchObject({
      ok: true,
      evidence: {
        provider: 'electron-clipboard',
        capability: 'clipboard',
        workspace_id: 'workspace-1',
        session_id: 'session-1',
        turn_id: 'turn-1',
        request_id: 'request-1',
        generation_id: 'generation-1',
        interruption_epoch: 4,
      },
    })
  })

  it('requires explicit target-window selection before any collector runs', async () => {
    let collected = false
    const bridge = new AuthorizedPerceptionBridge({
      captureTargetWindow: async () => {
        collected = true
        return { data: Buffer.from('unexpected') }
      },
    })
    const output = response()

    await handlePerceptionRoutes(
      request({ scope }),
      output.target,
      'POST',
      new URL('http://127.0.0.1/api/perception/collect-target-window'),
      bridge,
      'host-secret',
    )

    expect(output.status()).toBe(400)
    expect(output.json()).toMatchObject({ code: 'PERCEPTION_AUTHORIZATION_INVALID' })
    expect(collected).toBe(false)
  })

  it('rejects a caller-supplied target id even when the host selector exists', async () => {
    const output = response()
    await handlePerceptionRoutes(
      request({ scope, selection: { sourceId: 'window:forged' } }),
      output.target,
      'POST',
      new URL('http://127.0.0.1/api/perception/collect-target-window'),
      new AuthorizedPerceptionBridge({
        selectTargetWindow: async () => ({ sourceId: 'window:host-selected' }),
      }),
      'host-secret',
    )
    expect(output.status()).toBe(400)
    expect(output.json()).toMatchObject({ code: 'PERCEPTION_SELECTION_INVALID' })
  })

  it('captures only the target chosen by the main-process selector', async () => {
    const captured: string[] = []
    const output = response()
    await handlePerceptionRoutes(
      request({ scope }),
      output.target,
      'POST',
      new URL('http://127.0.0.1/api/perception/collect-target-window'),
      new AuthorizedPerceptionBridge({
        selectTargetWindow: async () => ({ sourceId: 'window:host-selected' }),
        captureTargetWindow: async (sourceId) => {
          captured.push(sourceId)
          return { data: Buffer.from('image') }
        },
      }),
      'host-secret',
    )
    expect(output.status()).toBe(200)
    expect(captured).toEqual(['window:host-selected'])
  })

  it('cancels a blocked provider when the HTTP request disconnects', async () => {
    const req = request({ scope })
    const output = response()
    const readClipboard = vi.fn(async () => new Promise<string>(() => {}))
    const handling = handlePerceptionRoutes(
      req,
      output.target,
      'POST',
      new URL('http://127.0.0.1/api/perception/collect-clipboard'),
      new AuthorizedPerceptionBridge({ readClipboard }),
      'host-secret',
    )
    await new Promise((resolve) => setTimeout(resolve, 0))
    ;(req as unknown as EventEmitter).emit('aborted')

    const outcome = await Promise.race([
      handling,
      new Promise<'timeout'>((resolve) => setTimeout(() => resolve('timeout'), 25)),
    ])

    expect(outcome).not.toBe('timeout')
    expect(output.status()).toBe(503)
    expect(output.json()).toMatchObject({ ok: false, code: 'PERCEPTION_CANCELLED' })
  })
})
