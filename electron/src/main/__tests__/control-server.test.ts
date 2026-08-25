import { EventEmitter } from 'node:events'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ControlServer } from '../control-server'

vi.mock('electron', () => ({
  app: {
    getPath: vi.fn(() => os.tmpdir()),
  },
}))

const handleSystemRoutesMock = vi.hoisted(() => vi.fn())

vi.mock('../http/routes/system-routes', () => ({
  handleSystemRoutes: handleSystemRoutesMock,
}))

type RequestHandler = {
  handleRequest: (req: IncomingMessage, res: ServerResponse) => Promise<void>
}

const createRequest = (
  url: string,
  headers: IncomingMessage['headers'] = {},
  method = 'GET',
  body?: unknown,
): IncomingMessage => {
  const request = new EventEmitter() as EventEmitter & {
    method: string
    url: string
    headers: IncomingMessage['headers']
    setEncoding: (encoding: BufferEncoding) => IncomingMessage
  }
  request.method = method
  request.url = url
  request.headers = headers
  request.setEncoding = () => request as unknown as IncomingMessage
  if (body !== undefined) {
    queueMicrotask(() => {
      request.emit('data', Buffer.from(JSON.stringify(body)))
      request.emit('end')
    })
  }
  return request as unknown as IncomingMessage
}

const createJsonResponse = (): {
  response: ServerResponse
  getStatus: () => number | null
  getJson: () => unknown
  getText: () => string
  getHeader: (name: string) => number | string | string[] | undefined
} => {
  let statusCode: number | null = null
  let payloadText = ''
  const headers = new Map<string, number | string | string[]>()
  const response = {
    getHeader: (name: string) => headers.get(name),
    setHeader: (name: string, value: number | string | string[]) => {
      headers.set(name, value)
      return response
    },
    writeHead: (nextStatusCode: number, nextHeaders?: Record<string, number | string | string[]>) => {
      statusCode = nextStatusCode
      for (const [name, value] of Object.entries(nextHeaders ?? {})) {
        headers.set(name, value)
      }
      return response
    },
    end: (payload?: string | Buffer) => {
      payloadText = Buffer.isBuffer(payload) ? payload.toString('utf8') : payload ?? ''
      return response
    },
  }

  return {
    response: response as unknown as ServerResponse,
    getStatus: () => statusCode,
    getJson: () => JSON.parse(payloadText) as unknown,
    getText: () => payloadText,
    getHeader: (name: string) => headers.get(name),
  }
}

const createServer = async (): Promise<ControlServer> => {
  process.env['YUIZAKI_BACKEND_API_TOKEN'] = 'test-control-token'
  const { ControlServer } = await import('../control-server')
  return new ControlServer(
    {} as never,
    {} as never,
    {} as never,
    {} as never,
    { snapshot: () => ({ plugins: [] }) } as never,
    'dist/renderer',
  )
}

const createServerWithRendererRoot = async (rendererRoot: string): Promise<ControlServer> => {
  process.env['YUIZAKI_BACKEND_API_TOKEN'] = 'test-control-token'
  const { ControlServer } = await import('../control-server')
  return new ControlServer(
    {} as never,
    {} as never,
    {} as never,
    {} as never,
    { snapshot: () => ({ plugins: [] }) } as never,
    rendererRoot,
  )
}

const createServerWithPetCatalog = async (petModelCatalog: unknown): Promise<ControlServer> => {
  process.env['YUIZAKI_BACKEND_API_TOKEN'] = 'test-control-token'
  const { ControlServer } = await import('../control-server')
  return new ControlServer(
    {} as never,
    {} as never,
    {} as never,
    petModelCatalog as never,
    { snapshot: () => ({ plugins: [] }) } as never,
    'dist/renderer',
  )
}

describe('ControlServer local API boundary', () => {
  afterEach(() => {
    delete process.env['YUIZAKI_BACKEND_API_TOKEN']
    vi.unstubAllEnvs()
    handleSystemRoutesMock.mockReset()
    vi.resetModules()
  })

  it('allows loopback API requests without a control token', async () => {
    const server = await createServer()
    const { response, getStatus, getJson } = createJsonResponse()

    await (server as unknown as RequestHandler).handleRequest(createRequest('/api/plugin/list'), response)

    expect(getStatus()).toBe(200)
    expect(getJson()).toEqual({ plugins: [] })
  }, 15000)

  it('allows the public Python ping probe without the control token', async () => {
    handleSystemRoutesMock.mockImplementation(async (_req, res, _method, url) => {
      res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' })
      res.end(JSON.stringify({ ok: true, path: url.pathname }))
      return true
    })
    const server = await createServer()
    const { response, getStatus, getJson } = createJsonResponse()

    await (server as unknown as RequestHandler).handleRequest(createRequest('/api/ping'), response)

    expect(getStatus()).toBe(200)
    expect(getJson()).toEqual({ ok: true, path: '/api/ping' })
  })

  it('allows API requests from any loopback browser port', async () => {
    const server = await createServer()
    const { response, getStatus, getJson, getHeader } = createJsonResponse()

    await (server as unknown as RequestHandler).handleRequest(
      createRequest('/api/plugin/list', { origin: 'http://127.0.0.1:43127' }),
      response,
    )

    expect(getStatus()).toBe(200)
    expect(getJson()).toEqual({ plugins: [] })
    expect(getHeader('Access-Control-Allow-Origin')).toBe('http://127.0.0.1:43127')
  })

  it('allows the trusted packaged renderer origin through API preflight', async () => {
    const server = await createServer()
    const { response, getStatus, getHeader } = createJsonResponse()

    await (server as unknown as RequestHandler).handleRequest(
      createRequest('/api/ping', { origin: 'yuizaki-app://renderer' }, 'OPTIONS'),
      response,
    )

    expect(getStatus()).toBe(204)
    expect(getHeader('Access-Control-Allow-Origin')).toBe('yuizaki-app://renderer')
  })

  it('rejects remote, file, and null origins through API preflight', async () => {
    const server = await createServer()

    for (const origin of ['https://example.com', 'file:///C:/app/index.html', 'null']) {
      const { response, getStatus, getHeader } = createJsonResponse()
      await (server as unknown as RequestHandler).handleRequest(
        createRequest('/api/ping', { origin }, 'OPTIONS'),
        response,
      )
      expect(getStatus()).toBe(403)
      expect(getHeader('Access-Control-Allow-Origin')).toBeUndefined()
    }
  })

  it('does not expose the deprecated workbench module inventory', async () => {
    const server = await createServer()
    const { response, getStatus, getJson } = createJsonResponse()

    await (server as unknown as RequestHandler).handleRequest(
      createRequest('/api/workbench/modules', { authorization: 'Bearer test-control-token' }),
      response,
    )

    expect(getStatus()).toBe(404)
    expect(getJson()).toEqual({ error: 'Not found' })
  })

  it('routes backend proxy paths outside /api without control auth', async () => {
    handleSystemRoutesMock.mockImplementation(async (_req, res, _method, url) => {
      res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' })
      res.end(JSON.stringify({ path: url.pathname }))
      return true
    })
    const server = await createServer()

    for (const pathname of ['/health', '/memory/docs', '/system/status', '/v1/models']) {
      const routed = createJsonResponse()
      await (server as unknown as RequestHandler).handleRequest(
        createRequest(pathname),
        routed.response,
      )
      expect(routed.getStatus()).toBe(200)
      expect(routed.getJson()).toEqual({ path: pathname })
    }

    expect(handleSystemRoutesMock).toHaveBeenCalledTimes(4)
  })

  it('serves managed pet assets without a control token but keeps CORS origin checks', async () => {
    const resolveLocalLive2dAsset = vi.fn(() => null)
    const server = await createServerWithPetCatalog({ resolveLocalLive2dAsset })
    const { response, getStatus, getJson, getHeader } = createJsonResponse()

    await (server as unknown as RequestHandler).handleRequest(
      createRequest('/api/pet/assets/live2d/missing.model3.json', { origin: 'http://localhost:5173' }),
      response,
    )

    expect(getStatus()).toBe(404)
    expect(getJson()).toEqual({ success: false, error: 'Local model asset not found' })
    expect(getHeader('Access-Control-Allow-Origin')).toBe('http://localhost:5173')
    expect(resolveLocalLive2dAsset).toHaveBeenCalledWith('missing.model3.json')
  })

  it('uses the backend API token as the shared panel token when no control token is configured', async () => {
    process.env['YUIZAKI_BACKEND_API_TOKEN'] = 'shared-backend-token'
    const { ControlServer } = await import('../control-server')
    const server = new ControlServer(
      {} as never,
      {} as never,
      {} as never,
      {} as never,
      { snapshot: () => ({ plugins: [] }) } as never,
      'dist/renderer',
    )

    expect(server.getControlToken()).toBe('shared-backend-token')
  })

  it('rejects static files that resolve outside the renderer root through symlinks', async () => {
    const rendererRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-renderer-root-'))
    const externalRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-renderer-outside-'))
    const linkDir = path.join(rendererRoot, 'linked')

    try {
      fs.writeFileSync(path.join(rendererRoot, 'index.html'), '<html></html>', 'utf8')
      fs.writeFileSync(path.join(externalRoot, 'secret.txt'), 'secret', 'utf8')
      fs.symlinkSync(externalRoot, linkDir, process.platform === 'win32' ? 'junction' : 'dir')

      const server = await createServerWithRendererRoot(rendererRoot)
      const { response, getStatus, getJson } = createJsonResponse()

      await (server as unknown as RequestHandler).handleRequest(createRequest('/linked/secret.txt'), response)

      expect(getStatus()).toBe(403)
      expect(getJson()).toEqual({ error: 'Forbidden' })
    } finally {
      fs.rmSync(rendererRoot, { recursive: true, force: true })
      fs.rmSync(externalRoot, { recursive: true, force: true })
    }
  })

  it('injects the control token into the served renderer index', async () => {
    const rendererRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-renderer-root-'))

    try {
      fs.writeFileSync(
        path.join(rendererRoot, 'index.html'),
        '<html><head><title>Yuizaki</title></head><body><div id="app"></div></body></html>',
        'utf8',
      )

      const server = await createServerWithRendererRoot(rendererRoot)
      const { response, getStatus, getText, getHeader } = createJsonResponse()

      await (server as unknown as RequestHandler).handleRequest(createRequest('/'), response)

      expect(getStatus()).toBe(200)
      expect(getHeader('Content-Type')).toBe('text/html; charset=utf-8')
      expect(getHeader('Cache-Control')).toBe('no-store')
      expect(getText()).toContain('<meta name="yuizaki-control-token" content="test-control-token" />')
      expect(getText().indexOf('yuizaki-control-token')).toBeLessThan(getText().indexOf('</head>'))
    } finally {
      fs.rmSync(rendererRoot, { recursive: true, force: true })
    }
  })

  it('allows the Vite renderer origin to bootstrap the static index token', async () => {
    const rendererRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-renderer-root-'))

    try {
      fs.writeFileSync(
        path.join(rendererRoot, 'index.html'),
        '<html><head><title>Yuizaki</title></head><body><div id="app"></div></body></html>',
        'utf8',
      )

      const server = await createServerWithRendererRoot(rendererRoot)
      const { response, getStatus, getText, getHeader } = createJsonResponse()

      await (server as unknown as RequestHandler).handleRequest(
        createRequest('/', { origin: 'http://localhost:5173' }),
        response,
      )

      expect(getStatus()).toBe(200)
      expect(getHeader('Access-Control-Allow-Origin')).toBe('http://localhost:5173')
      expect(getHeader('Vary')).toBe('Origin')
      expect(getText()).toContain('<meta name="yuizaki-control-token" content="test-control-token" />')
    } finally {
      fs.rmSync(rendererRoot, { recursive: true, force: true })
    }
  })

  it('serves onboarding routes without control auth', async () => {
    const server = await createServer()
    const snapshot = { schemaVersion: 1, runId: 'run-1', revision: 2, state: 'blocked', readyForText: false, startedAt: null, completedAt: null, probes: [] }
    server.setOnboardingCoordinator({ snapshot: vi.fn(() => snapshot) } as never)

    const result = createJsonResponse()
    await (server as unknown as RequestHandler).handleRequest(createRequest('/api/onboarding/snapshot'), result.response)
    expect(result.getStatus()).toBe(200)
    expect(result.getJson()).toEqual(snapshot)
    expect(handleSystemRoutesMock).not.toHaveBeenCalled()
  })

  it('rejects command-bearing onboarding HTTP payloads before dispatch', async () => {
    const server = await createServer()
    const startBackend = vi.fn()
    const cancelRun = vi.fn()
    server.setOnboardingCoordinator({ startBackend, cancelRun } as never)
    const headers = { authorization: 'Bearer test-control-token', 'content-type': 'application/json' }

    const maliciousStart = createJsonResponse()
    await (server as unknown as RequestHandler).handleRequest(
      createRequest('/api/onboarding/backend/start', headers, 'POST', { command: 'python', env: { TOKEN: 'x' } }),
      maliciousStart.response,
    )
    expect(maliciousStart.getStatus()).toBe(400)

    const maliciousCancel = createJsonResponse()
    await (server as unknown as RequestHandler).handleRequest(
      createRequest('/api/onboarding/cancel', headers, 'POST', { runId: 'run-1', args: ['--kill'] }),
      maliciousCancel.response,
    )
    expect(maliciousCancel.getStatus()).toBe(400)
    expect(startBackend).not.toHaveBeenCalled()
    expect(cancelRun).not.toHaveBeenCalled()
  })
})
