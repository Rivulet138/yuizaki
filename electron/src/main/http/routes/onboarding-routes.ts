import type { OnboardingReadinessCoordinator } from '../../onboarding-readiness-coordinator'
import {
  isOnboardingProbeId,
  isOnboardingRepairActionId,
  type OnboardingProbeRequest,
  type OnboardingRetryRequest,
} from '../../../shared/onboarding-readiness'
import type { HttpRouteHandler } from '../types'
import { parseRequestBody, sendJson } from '../utils'

const hasExactKeys = (value: unknown, allowed: readonly string[]): value is Record<string, unknown> =>
  Boolean(value) && typeof value === 'object' && !Array.isArray(value) &&
  Object.keys(value as Record<string, unknown>).every((key) => allowed.includes(key))

const parseProbeIds = (value: unknown): OnboardingProbeRequest['probeIds'] | null => {
  if (value === undefined) return undefined
  if (!Array.isArray(value) || value.length > 12 || !value.every(isOnboardingProbeId)) return null
  return [...new Set(value)]
}

const invalid = (res: Parameters<HttpRouteHandler>[1], message = 'Invalid onboarding request'): true => {
  sendJson(res, 400, { error: message })
  return true
}

export const handleOnboardingRoutes = async (
  req: Parameters<HttpRouteHandler>[0],
  res: Parameters<HttpRouteHandler>[1],
  method: string,
  url: URL,
  coordinator: OnboardingReadinessCoordinator,
): Promise<boolean> => {
  if (!url.pathname.startsWith('/api/onboarding/')) return false
  if (method === 'GET' && url.pathname === '/api/onboarding/snapshot') {
    sendJson(res, 200, coordinator.snapshot())
    return true
  }
  if (method === 'POST' && url.pathname === '/api/onboarding/backend/start') {
    const body = await parseRequestBody<unknown>(req)
    if (!hasExactKeys(body, [])) return invalid(res)
    sendJson(res, 200, await coordinator.startBackend())
    return true
  }
  if (method === 'POST' && url.pathname === '/api/onboarding/backend/cancel') {
    const body = await parseRequestBody<unknown>(req)
    if (!hasExactKeys(body, [])) return invalid(res)
    sendJson(res, 200, await coordinator.cancelBackend())
    return true
  }
  if (method === 'POST' && url.pathname === '/api/onboarding/cancel') {
    const body = await parseRequestBody<Record<string, unknown>>(req)
    if (!hasExactKeys(body, ['runId']) || typeof body['runId'] !== 'string' || !body['runId']) return invalid(res)
    sendJson(res, 200, await coordinator.cancelRun({ runId: body['runId'] }))
    return true
  }
  if (method === 'POST' && url.pathname === '/api/onboarding/run') {
    const body = await parseRequestBody<Record<string, unknown>>(req)
    if (!hasExactKeys(body, ['probeIds'])) return invalid(res)
    const probeIds = parseProbeIds(body['probeIds'])
    if (probeIds === null) return invalid(res)
    sendJson(res, 200, await coordinator.runProbe({ ...(probeIds ? { probeIds } : {}) }))
    return true
  }
  if (method === 'POST' && url.pathname === '/api/onboarding/retry') {
    const body = await parseRequestBody<Record<string, unknown>>(req)
    if (!hasExactKeys(body, ['runId', 'probeIds']) || typeof body['runId'] !== 'string' || !body['runId']) return invalid(res)
    const probeIds = parseProbeIds(body['probeIds'])
    if (probeIds === null) return invalid(res)
    const request: OnboardingRetryRequest = { runId: body['runId'], ...(probeIds ? { probeIds } : {}) }
    sendJson(res, 200, await coordinator.retry(request))
    return true
  }
  if (method === 'POST' && url.pathname === '/api/onboarding/repair') {
    const body = await parseRequestBody<Record<string, unknown>>(req)
    if (!hasExactKeys(body, ['actionId']) || !isOnboardingRepairActionId(body['actionId'])) return invalid(res, 'Unknown repair action')
    sendJson(res, 200, await coordinator.runRepair(body['actionId']))
    return true
  }
  sendJson(res, 404, { error: 'Not found' })
  return true
}
