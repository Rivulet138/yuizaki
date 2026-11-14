import { createHmac } from 'node:crypto'
import axios from 'axios'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PythonService } from '../python'
import { OnboardingReadinessCoordinator } from '../onboarding-readiness-coordinator'
import type { OnboardingReadinessSnapshot } from '../../shared/onboarding-readiness'

vi.mock('axios', () => ({ default: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }))
vi.mock('electron', () => ({ safeStorage: {} }))
afterEach(() => { vi.useRealTimers(); vi.resetAllMocks(); vi.unstubAllEnvs() })
const identity = { service: 'yuizaki-python-backend', version: 'electron', instanceId: 'instance', generation: 3, startupNonce: 'nonce', pid: null }
const runtime = { service: identity.service, version: identity.version, instance_id: identity.instanceId, generation: identity.generation, startup_nonce: identity.startupNonce }

describe('fresh Python ping evidence without weakening identity', () => {
  it('rejects a reachable unrelated managed runtime and clears the error only after a valid probe', async () => {
    vi.stubEnv('DESKTOP_PET_SKIP_INTERNAL_PYTHON', '0')
    const service = new PythonService()
    vi.mocked(axios.get).mockResolvedValueOnce({ data: { ok: true, runtime: { ...runtime, generation: 2 } } })
    expect(await service.health(identity)).toBe(false)
    expect(service.getHealthProbe()?.error).toContain('identity does not match')
    vi.mocked(axios.get).mockResolvedValueOnce({ data: { ok: true, runtime } })
    expect(await service.health(identity)).toBe(true)
    expect(service.getHealthProbe()).toMatchObject({ error: null, source: 'python:/api/ping', budgetMs: 2000, checkedAt: expect.any(String), durationMs: expect.any(Number) })
  })

  it('retains the actual transport error for this probe', async () => {
    vi.stubEnv('DESKTOP_PET_SKIP_INTERNAL_PYTHON', '0')
    const service = new PythonService()
    vi.mocked(axios.get).mockRejectedValueOnce(new Error('timeout of 2000ms exceeded'))
    expect(await service.health(identity)).toBe(false)
    expect(service.getHealthProbe()?.error).toBe('timeout of 2000ms exceeded')
    expect(axios.get).toHaveBeenCalledWith(expect.stringContaining('/api/ping'), { timeout: 2000 })
  })

  it('requires a valid challenge proof from the external runtime', async () => {
    vi.stubEnv('DESKTOP_PET_SKIP_INTERNAL_PYTHON', '1')
    const token = 'test-backend-token'
    const service = new PythonService(token)
    vi.mocked(axios.get).mockResolvedValueOnce({ data: { ok: true, runtime, runtime_proof: 'a'.repeat(64) } })
    expect(await service.health()).toBe(false)
    expect(service.getHealthProbe()?.error).toContain('challenge proof is invalid')
    vi.mocked(axios.get).mockImplementationOnce(async url => ({ data: { ok: true, runtime, runtime_proof: createHmac('sha256', token)
      .update(`yuizaki-backend-proof-v1:${new URL(url).searchParams.get('challenge')}`).digest('hex') } }))
    expect(await service.health()).toBe(true)
  })
})

const setupCoordinator = (health: () => Promise<boolean>, fetchImpl: typeof fetch) => {
  let snapshot: OnboardingReadinessSnapshot = {
    schemaVersion: 1, runId: '', revision: 0, state: 'idle', operation: 'idle', readyForText: false,
    startedAt: null, completedAt: null, probes: [],
  }
  const store = {
    get: () => structuredClone(snapshot),
    set: (next: OnboardingReadinessSnapshot) => { snapshot = structuredClone(next); return structuredClone(next) },
  }
  return new OnboardingReadinessCoordinator(store as never, { health } as never,
    'http://127.0.0.1:1', 'test-backend-token', { avatar: async () => ({ visible: true, fallback: false }) },
    {} as never, fetchImpl, 50)
}

describe('bounded onboarding cleanup', () => {
  it('does not probe Python for an exclusively host avatar scan', async () => {
    const health = vi.fn(async () => true)
    const fetchImpl = vi.fn<typeof fetch>()
    const coordinator = setupCoordinator(health, fetchImpl)
    const snapshot = await coordinator.runProbe({ probeIds: ['host.avatar'] })
    expect(snapshot.probes.find(probe => probe.id === 'host.avatar')?.status).toBe('ready')
    expect(health).not.toHaveBeenCalled()
    expect(fetchImpl).not.toHaveBeenCalled()
  })

  it.each(['health', 'cancel-fetch'])('bounds cleanup even when %s never settles', async stuck => {
    vi.useFakeTimers()
    const health = vi.fn(() => stuck === 'health' ? new Promise<boolean>(() => undefined) : Promise.resolve(true))
    const fetchImpl = vi.fn<typeof fetch>(() => new Promise<Response>(() => undefined))
    const coordinator = setupCoordinator(health, fetchImpl)
    const cleanup = coordinator as unknown as { cancelPythonRun(runId: string): Promise<void> }
    let settled = false
    const operation = cleanup.cancelPythonRun('python-run').then(() => { settled = true })
    await vi.advanceTimersByTimeAsync(60)
    expect(settled).toBe(true)
    if (stuck === 'cancel-fetch') {
      expect(fetchImpl).toHaveBeenCalledWith(expect.stringContaining('/cancel'), expect.objectContaining({ signal: expect.any(AbortSignal) }))
    }
    await operation
  })
})
