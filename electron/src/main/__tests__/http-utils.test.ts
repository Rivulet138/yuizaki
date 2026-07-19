import path from 'node:path'
import { EventEmitter } from 'node:events'
import type { IncomingMessage } from 'node:http'
import { describe, expect, it } from 'vitest'
import { HttpRequestError, isPathInsideBase, parseRequestBody } from '../http/utils'

const createRequest = (chunks: string[]): IncomingMessage => {
  const request = new EventEmitter() as EventEmitter & {
    setEncoding: (encoding: BufferEncoding) => void
  }
  request.setEncoding = () => {}
  queueMicrotask(() => {
    for (const chunk of chunks) {
      request.emit('data', chunk)
    }
    request.emit('end')
  })
  return request as unknown as IncomingMessage
}

describe('http utils', () => {
  it('rejects sibling directories that only share a path prefix', () => {
    const base = path.join('C:', 'tmp', 'renderer')
    const sibling = path.join('C:', 'tmp', 'renderer-evil', 'index.html')

    expect(isPathInsideBase(base, sibling)).toBe(false)
  })

  it('allows the base directory and descendants', () => {
    const base = path.join('C:', 'tmp', 'renderer')

    expect(isPathInsideBase(base, base)).toBe(true)
    expect(isPathInsideBase(base, path.join(base, 'assets', 'app.js'))).toBe(true)
  })

  it('rejects request bodies above the configured limit', async () => {
    await expect(parseRequestBody(createRequest(['{"payload":"too-large"}']), 8)).rejects.toMatchObject({
      statusCode: 413,
      payload: { error: 'Request body too large' },
    } satisfies Partial<HttpRequestError>)
  })

  it('maps invalid JSON bodies to a client error', async () => {
    await expect(parseRequestBody(createRequest(['{not-json}']))).rejects.toMatchObject({
      statusCode: 400,
      payload: { error: 'Invalid JSON request body' },
    } satisfies Partial<HttpRequestError>)
  })
})
