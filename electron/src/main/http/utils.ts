import type { IncomingMessage, ServerResponse } from 'http'
import path from 'node:path'

const DEFAULT_MAX_BODY_BYTES = 1024 * 1024

export class HttpRequestError extends Error {
  constructor(
    readonly statusCode: number,
    readonly payload: unknown,
  ) {
    super(typeof payload === 'object' && payload && 'error' in payload ? String(payload.error) : `HTTP ${statusCode}`)
  }
}

export const isPathInsideBase = (baseDir: string, targetPath: string): boolean => {
  const relative = path.relative(path.resolve(baseDir), path.resolve(targetPath))
  return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative))
}

export const sendJson = (res: ServerResponse, statusCode: number, payload: unknown): void => {
  const allowHeaders = res.getHeader('Access-Control-Allow-Headers')
  const allowMethods = res.getHeader('Access-Control-Allow-Methods')
  const allowOrigin = res.getHeader('Access-Control-Allow-Origin')
  const vary = res.getHeader('Vary')

  res.writeHead(statusCode, {
    ...(allowHeaders ? { 'Access-Control-Allow-Headers': String(allowHeaders) } : {}),
    ...(allowMethods ? { 'Access-Control-Allow-Methods': String(allowMethods) } : {}),
    ...(allowOrigin ? { 'Access-Control-Allow-Origin': String(allowOrigin) } : {}),
    ...(vary ? { Vary: String(vary) } : {}),
    'Content-Type': 'application/json; charset=utf-8',
  })
  res.end(JSON.stringify(payload))
}

const readRequestBody = async (req: IncomingMessage, maxBytes = DEFAULT_MAX_BODY_BYTES): Promise<string> =>
  new Promise((resolve, reject) => {
    let data = ''
    let totalBytes = 0
    let rejected = false

    req.setEncoding('utf8')
    req.on('data', (chunk) => {
      if (rejected) return
      totalBytes += Buffer.byteLength(chunk, 'utf8')
      if (totalBytes > maxBytes) {
        rejected = true
        reject(new HttpRequestError(413, { error: 'Request body too large' }))
        return
      }
      data += chunk
    })
    req.on('end', () => {
      if (!rejected) resolve(data)
    })
    req.on('error', (error) => {
      if (!rejected) reject(error)
    })
  })

export const parseRequestBody = async <T>(req: IncomingMessage, maxBytes?: number): Promise<T> => {
  const raw = await readRequestBody(req, maxBytes)
  if (!raw) {
    return {} as T
  }

  try {
    return JSON.parse(raw) as T
  } catch {
    throw new HttpRequestError(400, { error: 'Invalid JSON request body' })
  }
}
