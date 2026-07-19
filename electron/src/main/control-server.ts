import http, { type IncomingMessage, type ServerResponse } from 'http'
import path from 'path'
import fs, { createReadStream } from 'fs'
import { type AddressInfo } from 'net'
import { Live2DWindow } from './live2d-window'
import { PetWindow } from './window'
import { PetStateStore } from './pet-state-store'
import { PetModelCatalog } from './pet-model-catalog'
import { type PetControlState } from '../shared/pet-control'
import { logger } from './logger'
import { type PluginRegistry } from './plugin-registry'
import { HttpRequestError, isPathInsideBase, sendJson } from './http/utils'
import { resolvePythonApiOrigin } from './http/python-origin'
import { handlePetRoutes } from './http/routes/pet-routes'
import { handleModelRoutes } from './http/routes/model-routes'
import { handleSystemRoutes } from './http/routes/system-routes'
import { handlePluginRoutes } from './http/routes/plugin-routes'
import { createTransientBackendApiTokenStore, type BackendApiTokenStoreLike } from './backend-api-token-store'
import { ProviderCredentialStore } from './provider-credential-store'

const parseLocalPort = (value: string | undefined, fallback: number): number => {
  const port = Number.parseInt(String(value || '').trim(), 10)
  return Number.isInteger(port) && port > 0 && port <= 65535 ? port : fallback
}

const DEFAULT_PORT = parseLocalPort(process.env['CONTROL_SERVER_PORT'], 38945)
const DEFAULT_RENDERER_DEV_PORT = parseLocalPort(process.env['VITE_DEV_SERVER_PORT'], 5173)
const DEFAULT_API_ALLOWED_ORIGINS = [
  `http://127.0.0.1:${DEFAULT_PORT}`,
  `http://localhost:${DEFAULT_PORT}`,
  `http://127.0.0.1:${DEFAULT_RENDERER_DEV_PORT}`,
  `http://localhost:${DEFAULT_RENDERER_DEV_PORT}`,
]
const CONTROL_CORS_METHODS = 'GET,POST,PUT,PATCH,DELETE,OPTIONS'

const parseAllowedOrigins = (value: string | undefined): Set<string> => {
  const origins = value
    ?.split(',')
    .map((origin) => origin.trim().replace(/\/$/, ''))
    .filter(Boolean)
  return new Set(origins?.length ? origins : DEFAULT_API_ALLOWED_ORIGINS)
}

const API_ALLOWED_ORIGINS = parseAllowedOrigins(process.env['YUIZAKI_ALLOWED_ORIGINS'])

const MIME_TYPES: Record<string, string> = {
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
  '.webp': 'image/webp',
}

const escapeHtmlAttribute = (value: string): string =>
  value
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

const injectRuntimeMetadata = (
  html: string,
  metadata: { controlToken: string; controlOrigin: string; apiOrigin: string },
): string => {
  const meta = [
    `<meta name="yuizaki-control-token" content="${escapeHtmlAttribute(metadata.controlToken)}" />`,
    `<meta name="yuizaki-control-origin" content="${escapeHtmlAttribute(metadata.controlOrigin)}" />`,
    `<meta name="yuizaki-api-origin" content="${escapeHtmlAttribute(metadata.apiOrigin)}" />`,
  ].join('')
  return html.includes('</head>')
    ? html.replace('</head>', `${meta}</head>`)
    : `${meta}${html}`
}

export class ControlServer {
  private server: http.Server | null = null
  private port = DEFAULT_PORT

  constructor(
    private readonly live2dWindow: Live2DWindow,
    private readonly petWindow: PetWindow,
    private readonly petStateStore: PetStateStore,
    private readonly petModelCatalog: PetModelCatalog,
    private readonly pluginRegistry: PluginRegistry,
    private readonly adminTokenStore: { getSummaryAdminToken: () => string; setSummaryAdminToken: (token: string) => { ok: boolean; hasToken: boolean }; clearSummaryAdminToken: () => { ok: boolean } },
    private readonly rendererDistDir: string,
    private readonly applyPetStateToRenderer: ((state: PetControlState) => void) | undefined,
    private readonly providerCredentialStore: ProviderCredentialStore,
    private readonly backendApiTokenStore: BackendApiTokenStoreLike = createTransientBackendApiTokenStore(),
  ) {}

  private resolveAllowedOrigin(originHeader: string | undefined, allowNullOrigin = false): string | null {
    const origin = String(originHeader || '').trim()
    if (!origin) {
      return null
    }
    if (allowNullOrigin && origin === 'null') {
      return 'null'
    }
    return API_ALLOWED_ORIGINS.has(origin) ? origin : null
  }

  private isPetAssetPath(pathname: string): boolean {
    return pathname.startsWith('/api/pet/assets/live2d/') || pathname.startsWith('/api/pet/assets/vrm/')
  }

  private isRoutedApiPath(pathname: string): boolean {
    return pathname.startsWith('/api/') ||
      pathname === '/health' ||
      pathname.startsWith('/memory/') ||
      pathname.startsWith('/system/') ||
      pathname.startsWith('/v1/')
  }

  get panelUrl(): string {
    return `http://localhost:${this.port}/`
  }

  getControlToken(): string {
    return this.backendApiTokenStore.getBackendApiToken()
  }

  authorizePanelUrl(url: URL): URL {
    url.searchParams.set('control_token', this.getControlToken())
    return url
  }

  async start(): Promise<void> {
    if (this.server) {
      return
    }

    this.server = http.createServer((req, res) => {
      void this.handleRequest(req, res)
    })

    await new Promise<void>((resolve, reject) => {
      this.server!.once('error', reject)
      this.server!.listen(DEFAULT_PORT, '127.0.0.1', () => {
        const address = this.server!.address() as AddressInfo
        this.port = address.port
        resolve()
      })
    })

    logger.info(`[ControlServer] listening at ${this.panelUrl}`)
  }

  async stop(): Promise<void> {
    if (!this.server) {
      return
    }

    const activeServer = this.server
    this.server = null

    await new Promise<void>((resolve, reject) => {
      activeServer.close((error) => {
        if (error) {
          reject(error)
          return
        }

        resolve()
      })
    })
  }

  private async handleRequest(req: IncomingMessage, res: ServerResponse): Promise<void> {
    try {
      const method = req.method ?? 'GET'
      const url = new URL(req.url ?? '/', this.panelUrl)
      const isPetAssetPath = this.isPetAssetPath(url.pathname)
      const allowedOrigin = this.resolveAllowedOrigin(req.headers.origin, isPetAssetPath)
      const hasOrigin = Boolean(String(req.headers.origin || '').trim())

      if (method === 'OPTIONS') {
        if (hasOrigin && !allowedOrigin) {
          res.writeHead(403)
          res.end()
          return
        }
        const headers: Record<string, string> = {
          'Access-Control-Allow-Headers': 'Authorization, Content-Type, x-trace-id, x-yuizaki-backend-token',
          'Access-Control-Allow-Methods': CONTROL_CORS_METHODS,
        }
        if (allowedOrigin) {
          headers['Access-Control-Allow-Origin'] = allowedOrigin
          headers['Vary'] = 'Origin'
        }
        res.writeHead(204, headers)
        res.end()
        return
      }

      if (method === 'GET' && isPetAssetPath) {
        if (hasOrigin && !allowedOrigin) {
          sendJson(res, 403, { error: 'Origin not allowed' })
          return
        }
        if (allowedOrigin) {
          res.setHeader('Access-Control-Allow-Origin', allowedOrigin)
          res.setHeader('Access-Control-Allow-Headers', 'Authorization, Content-Type, x-trace-id, x-yuizaki-backend-token')
          res.setHeader('Access-Control-Allow-Methods', CONTROL_CORS_METHODS)
          res.setHeader('Vary', 'Origin')
        }
        await this.handleApiRequest(req, res, method, url)
        return
      }

      if (this.isRoutedApiPath(url.pathname)) {
        if (hasOrigin && !allowedOrigin) {
          sendJson(res, 403, { error: 'Origin not allowed' })
          return
        }
        if (allowedOrigin) {
          res.setHeader('Access-Control-Allow-Origin', allowedOrigin)
          res.setHeader('Access-Control-Allow-Headers', 'Authorization, Content-Type, x-trace-id, x-yuizaki-backend-token')
          res.setHeader('Access-Control-Allow-Methods', CONTROL_CORS_METHODS)
          res.setHeader('Vary', 'Origin')
        }
        if (!this.isAuthorizedApiRequest(req, url)) {
          sendJson(res, 401, { error: 'Unauthorized' })
          return
        }
        await this.handleApiRequest(req, res, method, url)
        return
      }

      if (hasOrigin && !allowedOrigin) {
        sendJson(res, 403, { error: 'Origin not allowed' })
        return
      }
      if (allowedOrigin) {
        res.setHeader('Access-Control-Allow-Origin', allowedOrigin)
        res.setHeader('Access-Control-Allow-Headers', 'Authorization, Content-Type, x-trace-id, x-yuizaki-backend-token')
        res.setHeader('Access-Control-Allow-Methods', CONTROL_CORS_METHODS)
        res.setHeader('Vary', 'Origin')
      }

      this.serveStaticFile(res, url.pathname)
    } catch (error) {
      if (error instanceof HttpRequestError) {
        sendJson(res, error.statusCode, error.payload)
        return
      }
      logger.error('[ControlServer] request failed:', error)
      sendJson(res, 500, { error: 'Internal server error' })
    }
  }

  private isAuthorizedApiRequest(req: IncomingMessage, url: URL): boolean {
    if (url.pathname === '/api/health' || url.pathname === '/api/ping') {
      return true
    }
    const authorization = String(req.headers.authorization || '').trim()
    if (!authorization.startsWith('Bearer ')) {
      return false
    }
    const providedToken = authorization.slice('Bearer '.length).trim()
    return providedToken.length > 0 && providedToken === this.getControlToken()
  }

  private async handleApiRequest(
    req: IncomingMessage,
    res: ServerResponse,
    method: string,
    url: URL,
  ): Promise<void> {
    const routeContext = {
      live2dWindow: this.live2dWindow,
      petWindow: this.petWindow,
      petStateStore: this.petStateStore,
      petModelCatalog: this.petModelCatalog,
      pluginRegistry: this.pluginRegistry,
      backendApiToken: this.getControlToken(),
      backendApiTokenStore: this.backendApiTokenStore,
      providerCredentialStore: this.providerCredentialStore,
      adminTokenStore: this.adminTokenStore,
      applyPetStateToRenderer: this.applyPetStateToRenderer,
      applyStateToLive2D: (state: PetControlState) => this.applyStateToLive2D(state),
    }

    if (await handleSystemRoutes(req, res, method, url, routeContext)) {
      return
    }

    if (await handleModelRoutes(req, res, method, url, routeContext)) {
      return
    }

    if (await handlePluginRoutes(req, res, method, url, routeContext)) {
      return
    }

    if (await handlePetRoutes(req, res, method, url, routeContext)) {
      return
    }

    sendJson(res, 404, { error: 'Not found' })
  }

  private serveStaticFile(res: ServerResponse, pathname: string): void {
    const requestedPath = pathname === '/' ? '/index.html' : pathname
    let decodedPath: string
    try {
      decodedPath = decodeURIComponent(requestedPath)
    } catch {
      sendJson(res, 400, { error: 'Invalid path encoding' })
      return
    }

    const rendererRoot = path.resolve(this.rendererDistDir)
    let realRendererRoot: string
    try {
      realRendererRoot = fs.realpathSync.native(rendererRoot)
    } catch {
      sendJson(res, 404, { error: 'File not found' })
      return
    }

    const absolutePath = path.resolve(rendererRoot, `.${decodedPath}`)

    if (!isPathInsideBase(rendererRoot, absolutePath)) {
      sendJson(res, 403, { error: 'Forbidden' })
      return
    }

    let filePath = absolutePath
    if (!fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
      filePath = path.join(this.rendererDistDir, 'index.html')
    }

    if (!fs.existsSync(filePath)) {
      sendJson(res, 404, { error: 'File not found' })
      return
    }

    let realFilePath: string
    try {
      realFilePath = fs.realpathSync.native(filePath)
    } catch {
      sendJson(res, 404, { error: 'File not found' })
      return
    }

    if (!isPathInsideBase(realRendererRoot, realFilePath)) {
      sendJson(res, 403, { error: 'Forbidden' })
      return
    }

    if (!fs.statSync(realFilePath).isFile()) {
      sendJson(res, 404, { error: 'File not found' })
      return
    }

    const extension = path.extname(realFilePath)
    const mimeType = MIME_TYPES[extension] ?? 'application/octet-stream'

    if (extension === '.html' && path.basename(realFilePath).toLowerCase() === 'index.html') {
      const html = fs.readFileSync(realFilePath, 'utf8')
      res.writeHead(200, {
        'Content-Type': mimeType,
        'Cache-Control': 'no-store',
      })
      res.end(injectRuntimeMetadata(html, {
        controlToken: this.getControlToken(),
        controlOrigin: this.panelUrl.replace(/\/$/, ''),
        apiOrigin: resolvePythonApiOrigin(),
      }))
      return
    }

    res.writeHead(200, { 'Content-Type': mimeType })
    createReadStream(realFilePath).pipe(res)
  }
  private applyStateToLive2D(state: PetControlState): PetControlState {
    let nextState = state
    const layout = this.live2dWindow.applyWindowLayout(state)

    if (layout) {
      if (layout.placement === 'free') {
        if (
          state.positionX !== layout.positionX ||
          state.positionY !== layout.positionY ||
          state.placement !== 'free'
        ) {
          nextState = this.petStateStore.applyConfigPatch({
            positionX: layout.positionX,
            positionY: layout.positionY,
            placement: 'free',
          })
        }
      }
      if (state.displayId !== layout.displayId) {
        nextState = this.petStateStore.applyConfigPatch({ displayId: layout.displayId })
      }
    }

    this.live2dWindow.setInteractMode(nextState.interactMode)
    this.live2dWindow.setClickThrough(nextState.clickThrough)
    this.live2dWindow.setLocked(nextState.locked)
    this.live2dWindow.applyPetConfig(this.petModelCatalog.buildRendererConfig(nextState))
    return nextState
  }
}
