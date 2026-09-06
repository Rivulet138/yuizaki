import type { IncomingMessage, ServerResponse } from 'node:http'
import { timingSafeEqual } from 'node:crypto'
import { parseRequestBody, sendJson } from '../utils'
import type { McpConfigVault } from '../../mcp-config-vault'

const ROUTE = '/api/internal/mcp-config-vault'
const loopback = (address: string | undefined): boolean => address === '127.0.0.1' || address === '::1' || address === '::ffff:127.0.0.1'
const auth = (provided: string, expected: string): boolean => {
  if (!expected) return false
  const a = Buffer.from(provided); const b = Buffer.from(expected)
  return a.length === b.length && timingSafeEqual(a, b)
}
const fail = (res: ServerResponse, status: number, code: string): void => { res.setHeader('Cache-Control', 'no-store'); sendJson(res, status, { ok: false, code }) }

export const handleMcpVaultRoutes = async (req: IncomingMessage, res: ServerResponse, method: string, url: URL, vault: McpConfigVault | null, token: string): Promise<boolean> => {
  if (url.pathname !== ROUTE || [...url.searchParams.keys()].length) return false
  res.setHeader('Cache-Control', 'no-store')
  if (method !== 'POST') { fail(res, 405, 'method_not_allowed'); return true }
  const authorization = String(req.headers.authorization || '')
  if (req.headers.origin !== undefined || !loopback(req.socket.remoteAddress) || !/^Bearer\s+\S+$/.test(authorization) || !auth(authorization.slice(7).trim(), token)) { fail(res, 403, 'unauthorized'); return true }
  if (!vault || !vault.isAvailable()) { fail(res, 503, 'mcp_config_vault_unavailable'); return true }
  try {
    const body = await parseRequestBody<Record<string, unknown>>(req, 1024 * 1024)
    if (!body || typeof body !== 'object' || !['store', 'read', 'prune'].includes(String(body['operation'])) || typeof body['namespace'] !== 'string') { fail(res, 400, 'invalid_request'); return true }
    const operation = body['operation']
    if (operation === 'store') {
      if (typeof body['document'] !== 'string') { fail(res, 400, 'invalid_request'); return true }
      const reference = vault.store(body['namespace'], body['document']); sendJson(res, 200, { ok: true, reference }); return true
    }
    if (typeof body['reference'] !== 'string') { fail(res, 400, 'invalid_request'); return true }
    if (operation === 'read') { sendJson(res, 200, { ok: true, document: vault.read(body['namespace'], body['reference']) }); return true }
    vault.prune(body['namespace'], body['reference']); sendJson(res, 200, { ok: true }); return true
  } catch (error) {
    if (error && typeof error === 'object' && 'statusCode' in error && Number(error.statusCode) === 413) { fail(res, 413, 'request_too_large'); return true }
    const message = error instanceof Error ? error.message : ''
    fail(res, message === 'invalid' ? 400 : 503, message === 'invalid' ? 'invalid_request' : 'mcp_config_vault_error'); return true
  }
}
