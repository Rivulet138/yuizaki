import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { OnboardingReadinessCoordinator, qualifyDesktopRuntime } from '../onboarding-readiness-coordinator'
import { OnboardingReadinessStore } from '../onboarding-readiness-store'
import { isOnboardingRepairActionId } from '../../shared/onboarding-readiness'

const tempDirs: string[] = []
const createStore = () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-onboarding-'))
  tempDirs.push(dir)
  return new OnboardingReadinessStore(dir)
}
const createPython = (healthy = true) => ({
  start: vi.fn(async () => undefined), cancelStart: vi.fn(async () => undefined), health: vi.fn(async () => healthy),
  getStatus: vi.fn(() => ({ state: healthy ? 'running' : 'failed', generation: 1, error: healthy ? null : 'spawn failed' })),
})
const createPorts = () => ({
  openPanel: vi.fn(async () => undefined), prepareResource: vi.fn(async () => undefined), reloadAvatar: vi.fn(),
  refreshMcp: vi.fn(async () => undefined), openLogs: vi.fn(async () => undefined), openInstallGuide: vi.fn(async () => undefined),
})
const qualifiedRuntime = () => ({
  platform: 'win32', arch: 'x64', nodeVersion: '22.13.0', electronVersion: '42.7.0', desktopSession: 'windows',
})

describe('onboarding readiness authority', () => {
  afterEach(() => {
    for (const dir of tempDirs.splice(0)) fs.rmSync(dir, { recursive: true, force: true })
  })

  it('keeps optional failures from blocking text and redacts backend evidence', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ schemaVersion: 1, runId: 'python-ready', revision: 1, state: 'completed', probes: [
      { id: 'llm.provider', label: 'Provider', status: 'ready', dependencies: [], timeoutMs: 1000, message: 'configured', evidence: { provider: 'openai', apiKey: 'secret-value' }, repairActionId: null },
      { id: 'llm.model_chat', label: 'Model', status: 'ready', dependencies: ['llm.provider'], timeoutMs: 1000, message: 'real response received', evidence: { model: 'gpt-test' }, repairActionId: null },
      { id: 'tts.status', label: 'TTS', status: 'failed', dependencies: [], timeoutMs: 1000, message: 'optional unavailable', evidence: {}, repairActionId: null },
    ] }), { status: 200 }))
    const coordinator = new OnboardingReadinessCoordinator(createStore(), createPython() as never, 'http://127.0.0.1:8001', 'backend-token',
      { avatar: async () => ({ visible: false, fallback: true }) }, createPorts(), fetchMock as never, 30_000, qualifiedRuntime)
    const snapshot = await coordinator.runProbe({})
    expect(snapshot.readyForText).toBe(true)
    expect(snapshot.probes.find((probe) => probe.id === 'tts.status')?.status).toBe('failed')
    expect(snapshot.probes.find((probe) => probe.id === 'llm.provider')?.evidence).toEqual({ provider: 'openai', apiKey: '[redacted]' })
    expect(snapshot.probes.find((probe) => probe.id === 'host.microphone')?.status).toBe('needs_user')
    expect(snapshot.probes.find((probe) => probe.id === 'host.speaker')?.status).toBe('needs_user')
  })

  it.each([
    ['win32 x64', qualifiedRuntime(), 'qualified', []],
    ['linux x64 X11', { ...qualifiedRuntime(), platform: 'linux', desktopSession: 'x11' }, 'qualified', []],
    ['linux x64 Wayland', { ...qualifiedRuntime(), platform: 'linux', desktopSession: 'wayland' }, 'qualified', []],
    ['Linux without a desktop session', { ...qualifiedRuntime(), platform: 'linux', desktopSession: null }, 'not_qualified', ['desktop_session_unavailable']],
    ['unsupported architecture', { ...qualifiedRuntime(), arch: 'arm64' }, 'unsupported', ['unsupported_architecture']],
    ['old Node runtime', { ...qualifiedRuntime(), nodeVersion: '22.12.0' }, 'unsupported', ['unsupported_node_version']],
    ['older Node major with larger minor', { ...qualifiedRuntime(), nodeVersion: '21.99.0' }, 'unsupported', ['unsupported_node_version']],
    ['missing Electron runtime', { ...qualifiedRuntime(), electronVersion: null }, 'not_qualified', ['electron_runtime_unavailable']],
  ])('classifies %s with a closed runtime qualification', (_name, facts, qualification, reasons) => {
    expect(qualifyDesktopRuntime(facts)).toEqual({ qualification, reasons })
  })

  it('blocks text readiness when the required host runtime is not qualified', async () => {
    const fetchMock = vi.fn()
    const coordinator = new OnboardingReadinessCoordinator(
      createStore(), createPython() as never, 'http://127.0.0.1:8001', 'backend-token',
      { avatar: async () => ({ visible: true, fallback: false }) }, createPorts(), fetchMock as never, 30_000,
      () => ({ ...qualifiedRuntime(), platform: 'linux', desktopSession: null }),
    )

    const snapshot = await coordinator.runProbe({ probeIds: ['host.runtime'] })
    const runtime = snapshot.probes.find((probe) => probe.id === 'host.runtime')

    expect(snapshot.readyForText).toBe(false)
    expect(runtime).toEqual(expect.objectContaining({
      status: 'unavailable',
      repairActionId: 'guide.open',
      evidence: expect.objectContaining({
        qualification: 'not_qualified',
        reasons: ['desktop_session_unavailable'],
        realDeviceQualification: 'not_measured',
      }),
    }))
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('replaces prior selected Python success when the readiness route fails', async () => {
    const store = createStore()
    store.set({
      schemaVersion: 1, runId: 'prior', revision: 4, state: 'ready', operation: 'idle', readyForText: true,
      startedAt: null, completedAt: new Date().toISOString(),
      probes: [
        { id: 'host.runtime', label: 'Host', status: 'ready', requiredForText: true, dependencies: [], timeoutMs: 0, message: 'ready', evidence: {}, repairActionId: null },
        { id: 'backend.service', label: 'Backend', status: 'ready', requiredForText: true, dependencies: [], timeoutMs: 0, message: 'ready', evidence: {}, repairActionId: null },
        { id: 'llm.provider', label: 'Provider', status: 'ready', requiredForText: true, dependencies: [], timeoutMs: 0, message: 'ready', evidence: {}, repairActionId: null },
        { id: 'llm.model_chat', label: 'Model', status: 'ready', requiredForText: true, dependencies: [], timeoutMs: 0, message: 'ready', evidence: {}, repairActionId: null },
      ],
    })
    const fetchMock = vi.fn(async () => new Response('{}', { status: 503 }))
    const coordinator = new OnboardingReadinessCoordinator(store, createPython() as never, 'http://127.0.0.1:8001', 'backend-token',
      { avatar: async () => ({ visible: true, fallback: false }) }, createPorts(), fetchMock as never)

    const snapshot = await coordinator.runProbe({ probeIds: ['llm.provider', 'llm.model_chat'] })

    expect(snapshot.readyForText).toBe(false)
    expect(snapshot.probes.find((probe) => probe.id === 'llm.provider')).toEqual(expect.objectContaining({
      status: 'unavailable', evidence: { category: 'transport' },
    }))
    expect(snapshot.probes.find((probe) => probe.id === 'llm.model_chat')?.status).toBe('unavailable')
  })

  it.each([
    ['a superseding run', { runId: 'python-run-b', revision: 4 }],
    ['a lower revision', { runId: 'python-run-a', revision: 2 }],
  ])('rejects %s while polling Python readiness', async (_case, staleIdentity) => {
    const store = createStore()
    store.set({
      schemaVersion: 1, runId: 'prior', revision: 4, state: 'ready', operation: 'idle', readyForText: true,
      startedAt: null, completedAt: new Date().toISOString(),
      probes: [
        { id: 'host.runtime', label: 'Host', status: 'ready', requiredForText: true, dependencies: [], timeoutMs: 0, message: 'ready', evidence: {}, repairActionId: null },
        { id: 'backend.service', label: 'Backend', status: 'ready', requiredForText: true, dependencies: [], timeoutMs: 0, message: 'ready', evidence: {}, repairActionId: null },
        { id: 'llm.provider', label: 'Provider', status: 'ready', requiredForText: true, dependencies: [], timeoutMs: 0, message: 'ready', evidence: {}, repairActionId: null },
        { id: 'llm.model_chat', label: 'Model', status: 'ready', requiredForText: true, dependencies: [], timeoutMs: 0, message: 'ready', evidence: {}, repairActionId: null },
      ],
    })
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      if (String(input).endsWith('/readiness/run')) {
        return new Response(JSON.stringify({ schemaVersion: 1, runId: 'python-run-a', revision: 3, state: 'running', probes: [] }), { status: 200 })
      }
      return new Response(JSON.stringify({
        schemaVersion: 1,
        ...staleIdentity,
        state: 'completed',
        probes: [
          { id: 'llm.provider', status: 'ready' },
          { id: 'llm.model_chat', status: 'ready' },
        ],
      }), { status: 200 })
    })
    const coordinator = new OnboardingReadinessCoordinator(store, createPython() as never, 'http://127.0.0.1:8001', 'backend-token',
      { avatar: async () => ({ visible: true, fallback: false }) }, createPorts(), fetchMock as never)

    const snapshot = await coordinator.runProbe({ probeIds: ['llm.provider', 'llm.model_chat'] })

    expect(snapshot.readyForText).toBe(false)
    expect(snapshot.probes.find((probe) => probe.id === 'llm.provider')).toEqual(expect.objectContaining({
      status: 'unavailable', evidence: { category: 'transport' },
    }))
    expect(snapshot.probes.find((probe) => probe.id === 'llm.model_chat')?.status).toBe('unavailable')
  })

  it.each(['initial response', 'poll response'])('rejects a wrong schema version in the Python %s', async (stage) => {
    const readyProbes = [
      { id: 'llm.provider', status: 'ready' },
      { id: 'llm.model_chat', status: 'ready' },
    ]
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      if (String(input).endsWith('/readiness/run')) {
        return new Response(JSON.stringify(stage === 'initial response'
          ? { schemaVersion: 2, runId: 'python-run', revision: 1, state: 'completed', probes: readyProbes }
          : { schemaVersion: 1, runId: 'python-run', revision: 1, state: 'running', probes: [] }), { status: 200 })
      }
      return new Response(JSON.stringify({
        schemaVersion: 2, runId: 'python-run', revision: 2, state: 'completed', probes: readyProbes,
      }), { status: 200 })
    })
    const coordinator = new OnboardingReadinessCoordinator(createStore(), createPython() as never, 'http://127.0.0.1:8001', 'backend-token',
      { avatar: async () => ({ visible: true, fallback: false }) }, createPorts(), fetchMock as never)

    const snapshot = await coordinator.runProbe({ probeIds: ['llm.provider', 'llm.model_chat'] })

    expect(snapshot.readyForText).toBe(false)
    expect(snapshot.probes.find((probe) => probe.id === 'llm.provider')?.status).toBe('unavailable')
    expect(snapshot.probes.find((probe) => probe.id === 'llm.model_chat')?.status).toBe('unavailable')
  })

  it('rejects Python attempts to overwrite main-owned host probes', async () => {
    const store = createStore()
    store.set({
      schemaVersion: 1, runId: 'prior', revision: 2, state: 'blocked', operation: 'idle', readyForText: false,
      startedAt: null, completedAt: new Date().toISOString(),
      probes: [
        { id: 'host.runtime', label: 'Host', status: 'failed', requiredForText: true, dependencies: [], timeoutMs: 0, message: 'main-owned failure', evidence: {}, repairActionId: null },
        { id: 'host.microphone', label: 'Microphone', status: 'needs_user', requiredForText: false, dependencies: [], timeoutMs: 0, message: 'main-owned gesture', evidence: {}, repairActionId: null },
      ],
    })
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({
      schemaVersion: 1, runId: 'python-run', revision: 1, state: 'completed', probes: [
        { id: 'host.runtime', status: 'ready', message: 'forged' },
        { id: 'host.microphone', status: 'ready', message: 'forged' },
        { id: 'llm.provider', status: 'ready' },
        { id: 'llm.model_chat', status: 'ready' },
      ],
    }), { status: 200 }))
    const coordinator = new OnboardingReadinessCoordinator(store, createPython() as never, 'http://127.0.0.1:8001', 'backend-token',
      { avatar: async () => ({ visible: true, fallback: false }) }, createPorts(), fetchMock as never)

    const snapshot = await coordinator.runProbe({ probeIds: ['llm.provider', 'llm.model_chat'] })

    expect(snapshot.probes.find((probe) => probe.id === 'host.runtime')).toEqual(expect.objectContaining({
      status: 'failed', message: 'main-owned failure',
    }))
    expect(snapshot.probes.find((probe) => probe.id === 'host.microphone')).toEqual(expect.objectContaining({
      status: 'needs_user', message: 'main-owned gesture',
    }))
  })

  it('does not contact Python or trigger side effects for host-only passive probes', async () => {
    const fetchMock = vi.fn()
    const ports = createPorts()
    const coordinator = new OnboardingReadinessCoordinator(createStore(), createPython() as never, 'http://127.0.0.1:8001', 'backend-token',
      { avatar: async () => ({ visible: true, fallback: false }) }, ports, fetchMock as never)
    const snapshot = await coordinator.runProbe({ probeIds: ['host.microphone', 'host.speaker'] })
    expect(snapshot.probes.every((probe) => probe.status === 'needs_user')).toBe(true)
    expect(fetchMock).not.toHaveBeenCalled()
    expect(ports.prepareResource).not.toHaveBeenCalled()
    expect(ports.reloadAvatar).not.toHaveBeenCalled()
    expect(ports.refreshMcp).not.toHaveBeenCalled()
  })

  it('publishes and cancels backend startup as a distinct operation', async () => {
    let resolveStart: (() => void) | undefined
    const python = createPython()
    python.start.mockImplementation(() => new Promise<void>((resolve) => { resolveStart = resolve }))
    const coordinator = new OnboardingReadinessCoordinator(createStore(), python as never, 'http://127.0.0.1:8001', 'backend-token',
      { avatar: async () => ({ visible: true, fallback: false }) }, createPorts(), vi.fn() as never)

    const starting = coordinator.startBackend()
    await vi.waitFor(() => expect(coordinator.snapshot().operation).toBe('backend_start'))
    const cancelled = await coordinator.cancelBackend()
    resolveStart?.()
    await starting

    expect(python.cancelStart).toHaveBeenCalledOnce()
    expect(cancelled).toEqual(expect.objectContaining({ state: 'cancelled', operation: 'idle' }))
    expect(coordinator.snapshot().operation).toBe('idle')
  })

  it('cancels and awaits the active Python run by its Python runId', async () => {
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/readiness/cancel')) {
        return new Response(JSON.stringify({ state: 'cancelled' }), { status: 200 })
      }
      if (url.endsWith('/readiness/run')) {
        return new Response(JSON.stringify({ schemaVersion: 1, runId: 'python-run-1', revision: 1, state: 'running', probes: [] }), { status: 200 })
      }
      if (url.endsWith('/readiness')) {
        await new Promise<void>((resolve, reject) => {
          init?.signal?.addEventListener('abort', () => reject(new Error('aborted')), { once: true })
          setTimeout(resolve, 10_000)
        })
      }
      return new Response(JSON.stringify({ schemaVersion: 1, runId: 'python-run-1', revision: 1, state: 'running', probes: [] }), { status: 200 })
    })
    const coordinator = new OnboardingReadinessCoordinator(createStore(), createPython() as never, 'http://127.0.0.1:8001', 'backend-token',
      { avatar: async () => ({ visible: true, fallback: false }) }, createPorts(), fetchMock as never)

    const first = coordinator.runProbe({ probeIds: ['llm.provider'] })
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/readiness$/), expect.objectContaining({ signal: expect.any(AbortSignal) }),
    ))
    const cancelled = coordinator.cancelRun({ runId: 'python-run-1' })
    await expect(Promise.all([first, cancelled])).resolves.toHaveLength(2)

    const cancelCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/readiness/cancel'))
    expect(cancelCall?.[1]).toEqual(expect.objectContaining({ body: JSON.stringify({ runId: 'python-run-1' }) }))
  })

  it('persists a terminal cancelled state when a readiness run times out', async () => {
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      if (String(input).endsWith('/readiness/run')) {
        return new Response(JSON.stringify({ schemaVersion: 1, runId: 'python-timeout', revision: 1, state: 'running', probes: [] }), { status: 200 })
      }
      await new Promise<void>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => reject(new Error('aborted')), { once: true })
      })
      return new Response('{}')
    })
    const coordinator = new OnboardingReadinessCoordinator(createStore(), createPython() as never, 'http://127.0.0.1:8001', 'backend-token',
      { avatar: async () => ({ visible: true, fallback: false }) }, createPorts(), fetchMock as never, 10)
    const snapshot = await coordinator.runProbe({ probeIds: ['llm.provider'] })
    expect(snapshot.state).toBe('cancelled')
    expect(snapshot.operation).toBe('idle')
    expect(snapshot.completedAt).not.toBeNull()
  })

  it('bounds and cancels hanging host probes under the shared scan deadline', async () => {
    const never = new Promise<never>(() => undefined)
    const python = createPython()
    python.health.mockImplementation(() => never)
    const coordinator = new OnboardingReadinessCoordinator(createStore(), python as never, 'http://127.0.0.1:8001', 'backend-token',
      { avatar: () => never }, createPorts(), vi.fn() as never, 15)

    const snapshot = await coordinator.runProbe({ probeIds: ['backend.service', 'host.avatar'] })

    expect(snapshot.state).toBe('cancelled')
    expect(snapshot.readyForText).toBe(false)
    expect(snapshot.completedAt).not.toBeNull()
  })

  it('locally cancels a hanging host probe without waiting for its promise', async () => {
    const never = new Promise<never>(() => undefined)
    const python = createPython()
    python.health.mockImplementation(() => never)
    const coordinator = new OnboardingReadinessCoordinator(createStore(), python as never, 'http://127.0.0.1:8001', 'backend-token',
      { avatar: async () => ({ visible: true, fallback: false }) }, createPorts(), vi.fn() as never, 5_000)
    const running = coordinator.runProbe({ probeIds: ['backend.service'] })
    await vi.waitFor(() => expect(coordinator.snapshot().state).toBe('running'))
    const runId = coordinator.snapshot().runId

    const cancelled = await coordinator.cancelRun({ runId })
    await running
    expect(cancelled.state).toBe('cancelled')
  })

  it('locally aborts before Python supplies a runId and rejects the late response', async () => {
    let resolveRun: ((response: Response) => void) | undefined
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      if (String(input).endsWith('/readiness/run')) {
        return new Promise<Response>((resolve) => { resolveRun = resolve })
      }
      return new Response('{}', { status: 200 })
    })
    const coordinator = new OnboardingReadinessCoordinator(createStore(), createPython() as never, 'http://127.0.0.1:8001', 'backend-token',
      { avatar: async () => ({ visible: true, fallback: false }) }, createPorts(), fetchMock as never)
    const running = coordinator.runProbe({ probeIds: ['llm.provider'] })
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledOnce())
    const localRunId = coordinator.snapshot().runId
    const cancelling = coordinator.cancelRun({ runId: localRunId })
    resolveRun?.(new Response(JSON.stringify({ schemaVersion: 1, runId: 'late-python-run', revision: 1, state: 'ready', probes: [] }), { status: 200 }))
    await Promise.all([running, cancelling])

    expect(coordinator.snapshot().runId).toBe(localRunId)
    expect(coordinator.snapshot().state).toBe('cancelled')
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/readiness/cancel'))).toBe(false)
  })

  it('recovers interrupted persisted runs', () => {
    const store = createStore()
    const storagePath = (store as unknown as { storagePath: string }).storagePath
    store.set({ schemaVersion: 1, runId: 'crashed', revision: 4, state: 'running', operation: 'probe_scan', readyForText: false, startedAt: new Date().toISOString(), completedAt: null, probes: [
      { id: 'backend.service', label: 'Backend', status: 'running', requiredForText: true, dependencies: [], timeoutMs: 1000, message: 'starting', evidence: {}, repairActionId: 'backend.retry' },
    ] })
    const recovered = new OnboardingReadinessStore(path.dirname(storagePath)).get()
    expect(recovered.state).toBe('blocked')
    expect(recovered.probes[0]?.status).toBe('failed')
    if (process.platform !== 'win32') expect(fs.statSync(storagePath).mode & 0o777).toBe(0o600)
  })

  it('migrates schema-v1 snapshots without an operation discriminator to idle', () => {
    const store = createStore()
    const storagePath = (store as unknown as { storagePath: string }).storagePath
    fs.writeFileSync(storagePath, JSON.stringify({
      schemaVersion: 1, runId: 'legacy', revision: 3, state: 'blocked', readyForText: false,
      startedAt: null, completedAt: new Date().toISOString(), probes: [],
    }))

    expect(new OnboardingReadinessStore(path.dirname(storagePath)).get().operation).toBe('idle')
  })

  it('accepts only closed repair identifiers', () => {
    expect(isOnboardingRepairActionId('resource.prepare:tts')).toBe(true)
    expect(isOnboardingRepairActionId('navigate:settings')).toBe(true)
    expect(isOnboardingRepairActionId('mcp.refresh_existing')).toBe(true)
    expect(isOnboardingRepairActionId('shell:cmd.exe')).toBe(false)
    expect(isOnboardingRepairActionId('backend.retry:--command')).toBe(false)
    expect(isOnboardingRepairActionId('resource.prepare:C:\\secret')).toBe(false)
  })

  it('persists only main-generated evidence for explicit user device reports', () => {
    const coordinator = new OnboardingReadinessCoordinator(createStore(), createPython(false) as never, 'http://127.0.0.1:8001', 'backend-token',
      { avatar: async () => ({ visible: true, fallback: false }) }, createPorts(), vi.fn() as never)
    const snapshot = coordinator.reportDeviceProbe({ probeId: 'host.microphone', outcome: 'ready', messageCode: 'permission_granted' })
    const probe = snapshot.probes.find((candidate) => candidate.id === 'host.microphone')
    expect(probe?.status).toBe('ready')
    expect(probe?.evidence).toEqual(expect.objectContaining({ source: 'user_gesture', messageCode: 'permission_granted' }))
  })
})
