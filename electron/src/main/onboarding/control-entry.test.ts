import { createServer, type IncomingMessage, type ServerResponse } from 'node:http'
import { mkdtempSync, rmSync, rmdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import type { AddressInfo } from 'node:net'
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'
import { ControlServer } from '../control-server'
import { OnboardingReadinessCoordinator } from '../onboarding-readiness-coordinator'
import { OnboardingReadinessStore } from '../onboarding-readiness-store'

vi.mock('electron', () => ({ safeStorage: {} }))

describe('V04 actual control HTTP entry (local trust contract)', () => {
  const dir = mkdtempSync(path.join(tmpdir(), 'yuizaki-control-entry-'))
  const store = new OnboardingReadinessStore(dir)
  const probe = { source: 'python:/api/ping', startedAt: '2026-11-10T00:00:00Z', checkedAt: '2026-11-10T00:00:02Z', durationMs: 2000, budgetMs: 2000, error: 'timeout of 2000ms exceeded' }
  const coordinator = new OnboardingReadinessCoordinator(store, {
    health: async () => false, getHealthProbe: () => probe, getStatus: () => ({ error: 'old startup error' }),
  } as never, 'http://127.0.0.1:1', 'backend-secret', {
    avatar: async () => ({ visible: true, fallback: false }),
  }, {} as never)
  const control = new ControlServer({} as never, {} as never, {} as never, {} as never, {} as never,
    dir, undefined, {} as never, { getBackendApiToken: () => 'backend-secret' } as never)
  control.setOnboardingCoordinator(coordinator)
  // Wire real incoming requests into the production entry handler on a private,
  // ephemeral loopback listener; never bind or restart the user's control port.
  const entry = control as unknown as { handleRequest(req: IncomingMessage, res: ServerResponse): Promise<void> }
  const server = createServer((req, res) => { void entry.handleRequest(req, res) })
  let origin = ''
  beforeAll(async () => {
    await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
    origin = `http://127.0.0.1:${(server.address() as AddressInfo).port}`
  })
  afterAll(async () => {
    await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()))
    rmSync(path.join(dir, 'onboarding-readiness.json'), { force: true })
    rmdirSync(dir)
  })

  it.each([undefined, 'Bearer wrong', 'Bearer expired', 'Bearer backend-secret'])('accepts no-Origin ordinary requests with token=%s', async authorization => {
    const response = await fetch(`${origin}/api/onboarding/snapshot`, { headers: authorization ? { authorization } : {} })
    expect(response.status).toBe(200)
  })

  it.each(['http://localhost:54321', 'https://127.0.0.1:64321', 'http://[::1]:12345', 'yuizaki-app://renderer'])('accepts allowed Origin %s without token', async allowed => {
    const response = await fetch(`${origin}/api/onboarding/snapshot`, { headers: { origin: allowed } })
    expect(response.status).toBe(200)
    expect(response.headers.get('access-control-allow-origin')).toBe(allowed)
  })

  it.each(['https://example.com', 'null', 'http://localhost.evil.test:1234', 'file://'])('rejects foreign Origin %s even with a token', async blocked => {
    const response = await fetch(`${origin}/api/onboarding/snapshot`, { headers: { origin: blocked, authorization: 'Bearer backend-secret' } })
    expect(response.status).toBe(403)
  })

  it('keeps preflight policy and dedicated vault authorization separate', async () => {
    expect((await fetch(`${origin}/api/onboarding/snapshot`, { method: 'OPTIONS', headers: { origin: 'http://localhost:43210' } })).status).toBe(204)
    expect((await fetch(`${origin}/api/onboarding/snapshot`, { method: 'OPTIONS', headers: { origin: 'https://example.com' } })).status).toBe(403)
    expect((await fetch(`${origin}/api/internal/mcp-config-vault`, { method: 'POST', body: '{}' })).status).toBe(403)
  })

  it('labels control health as liveness only', async () => {
    const response = await fetch(`${origin}/api/health`)
    expect(await response.json()).toMatchObject({ status: 'ok', service: 'yuizaki-control', signal: 'liveness', checkedAt: expect.any(String) })
  })

  it('persists the actual browser device report and rejects contradictory success', async () => {
    const send = (body: unknown) => fetch(`${origin}/api/onboarding/device-probe`, { method: 'POST', body: JSON.stringify(body) })
    const response = await send({ probeId: 'host.microphone', outcome: 'unavailable', messageCode: 'permission_denied' })
    expect(response.status).toBe(200)
    expect((await response.json()).probes).toContainEqual(expect.objectContaining({ id: 'host.microphone', status: 'unavailable', evidence: expect.objectContaining({ source: 'user_gesture', messageCode: 'permission_denied', reportedAt: expect.any(String) }) }))
    expect((await send({ probeId: 'host.microphone', outcome: 'ready', messageCode: 'permission_denied' })).status).toBe(400)
  })

  it('uses the fresh ping error and preserves its timestamp across an unrelated retry', async () => {
    const first = await coordinator.runProbe({ probeIds: ['backend.service'] })
    const backend = first.probes.find(item => item.id === 'backend.service')!
    expect(backend.message).toBe(probe.error)
    expect(backend).toMatchObject({ timeoutMs: 2000, durationMs: 2000, evidence: expect.objectContaining({ checkedAt: probe.checkedAt }) })
    const next = await coordinator.runProbe({ probeIds: ['host.avatar'] })
    expect(next.probes.find(item => item.id === 'backend.service')).toEqual(backend)
    expect(next.readyForText).toBe(false)
  })
})
