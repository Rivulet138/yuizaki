import type { IncomingMessage, ServerResponse } from 'node:http'
import { timingSafeEqual } from 'node:crypto'
import type { AuthorizedPerceptionBridge, PerceptionAuthorization, PerceptionScope } from '../../authorized-perception-bridge'
import type { PerceptionCapability } from '../../../shared/authorized-perception'
import { parseRequestBody, sendJson } from '../utils'

const ROUTES = new Map<string, PerceptionCapability>([
  ['/api/perception/collect-screenshot', 'screenshot'],
  ['/api/perception/collect-target-window', 'target_window'],
  ['/api/perception/collect-active-application', 'active_application'],
  ['/api/perception/collect-selected-file', 'selected_file'],
  ['/api/perception/collect-clipboard', 'clipboard'],
  ['/api/perception/collect-ocr', 'ocr'],
])

const exactKeys = (value: Record<string, unknown>, allowed: readonly string[]): boolean =>
  Object.keys(value).every((key) => allowed.includes(key))
  && allowed.filter((key) => key !== 'selection').every((key) => key in value)

const parseScope = (value: unknown): PerceptionScope | null => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const scope = value as Record<string, unknown>
  const keys = ['workspaceId', 'sessionId', 'turnId', 'requestId', 'generationId', 'interruptionEpoch'] as const
  if (!exactKeys(scope, keys)) return null
  if (!keys.slice(0, 5).every((key) => typeof scope[key] === 'string' && String(scope[key]).trim())) return null
  if (!Number.isInteger(scope['interruptionEpoch']) || Number(scope['interruptionEpoch']) < 0) return null
  return scope as unknown as PerceptionScope
}

const parseAuthorization = (value: unknown, capability: PerceptionCapability): PerceptionAuthorization | null => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const body = value as Record<string, unknown>
  if (!exactKeys(body, ['scope', 'selection'])) return null
  const scope = parseScope(body['scope'])
  if (!scope) return null
  const selection = body['selection']
  if (selection !== undefined && (!selection || typeof selection !== 'object' || Array.isArray(selection))) return null
  if (selection) {
    const record = selection as Record<string, unknown>
    if (!Object.keys(record).every((key) => ['sourceId', 'filePath'].includes(key))) return null
    if (!Object.values(record).every((item) => typeof item === 'string' && item.trim())) return null
  }
  const parsedSelection = selection as Record<string, string> | undefined
  return {
    capability,
    scope,
    permissionGranted: true,
    ...(parsedSelection ? { selection: parsedSelection } : {}),
  }
}

export const handlePerceptionRoutes = async (
  req: IncomingMessage,
  res: ServerResponse,
  method: string,
  url: URL,
  bridge: AuthorizedPerceptionBridge | null,
  hostPerceptionToken: string,
): Promise<boolean> => {
  const capability = ROUTES.get(url.pathname)
  if (!capability) return false
  if (method !== 'POST') {
    sendJson(res, 405, { error: 'Method not allowed' })
    return true
  }
  const providedToken = String(req.headers['x-yuizaki-host-perception-token'] || '')
  const expected = Buffer.from(hostPerceptionToken)
  const provided = Buffer.from(providedToken)
  if (!hostPerceptionToken || provided.length !== expected.length || !timingSafeEqual(provided, expected)) {
    sendJson(res, 401, { error: 'Unauthorized' })
    return true
  }
  if (!bridge) {
    sendJson(res, 503, { ok: false, code: 'PERCEPTION_PROVIDER_UNAVAILABLE', message: 'perception bridge unavailable' })
    return true
  }
  const authorization = parseAuthorization(await parseRequestBody<unknown>(req, 8 * 1024), capability)
  if (!authorization) {
    sendJson(res, 400, { ok: false, code: 'PERCEPTION_AUTHORIZATION_INVALID', message: 'invalid perception authorization' })
    return true
  }
  if (authorization.selection !== undefined) {
    sendJson(res, 400, { ok: false, code: 'PERCEPTION_SELECTION_INVALID', message: 'selection must be performed by the host' })
    return true
  }
  try {
    const controller = new AbortController()
    const abortRequest = () => controller.abort()
    req.once('aborted', abortRequest)
    req.once('close', () => {
      if (!req.complete) abortRequest()
    })
    const sessionId = await bridge.issueAuthorized(authorization, controller.signal)
    const result = await bridge.collectHostEvidence(sessionId, capability, controller.signal)
    sendJson(res, result.ok ? 200 : 503, result)
  } catch {
    sendJson(res, 400, { ok: false, code: 'PERCEPTION_AUTHORIZATION_INVALID', message: 'invalid perception authorization' })
  }
  return true
}
