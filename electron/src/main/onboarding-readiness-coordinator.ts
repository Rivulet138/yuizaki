import { randomUUID } from 'node:crypto'
import type { PythonService } from './python'
import { OnboardingReadinessStore } from './onboarding-readiness-store'
import {
  ONBOARDING_REQUIRED_TEXT_PROBES,
  ONBOARDING_SCHEMA_VERSION,
  isOnboardingProbeId,
  isOnboardingProbeMessageKey,
  isOnboardingRepairActionId,
  type OnboardingProbeId,
  type OnboardingProbeRequest,
  type OnboardingProbeResult,
  type OnboardingReadinessSnapshot,
  type OnboardingRuntimeQualification,
  type OnboardingCancelRunRequest,
  type OnboardingDeviceProbeReport,
  type OnboardingRepairActionId,
  type OnboardingRetryRequest,
} from '../shared/onboarding-readiness'

type FetchLike = typeof fetch

export interface DesktopRuntimeFacts {
  platform: string
  arch: string
  nodeVersion: string
  electronVersion: string | null
  desktopSession: string | null
}

interface DesktopRuntimeQualification {
  qualification: OnboardingRuntimeQualification
  reasons: string[]
}

const versionAtLeast = (value: string, minimum: readonly [number, number, number]): boolean => {
  const match = /^(\d+)\.(\d+)\.(\d+)/.exec(value)
  if (!match) return false
  const actual = match.slice(1, 4).map(Number)
  for (let index = 0; index < actual.length; index += 1) {
    if (actual[index]! > minimum[index]!) return true
    if (actual[index]! < minimum[index]!) return false
  }
  return true
}

export const qualifyDesktopRuntime = (facts: DesktopRuntimeFacts): DesktopRuntimeQualification => {
  const unsupported: string[] = []
  if (!['win32', 'linux'].includes(facts.platform)) unsupported.push('unsupported_platform')
  if (facts.arch !== 'x64') unsupported.push('unsupported_architecture')
  if (!versionAtLeast(facts.nodeVersion, [22, 13, 0])) unsupported.push('unsupported_node_version')
  if (facts.electronVersion !== null && !versionAtLeast(facts.electronVersion, [42, 7, 0])) {
    unsupported.push('unsupported_electron_version')
  }
  if (unsupported.length > 0) return { qualification: 'unsupported', reasons: unsupported }

  const unqualified: string[] = []
  if (!facts.electronVersion) unqualified.push('electron_runtime_unavailable')
  if (facts.platform === 'linux' && !['x11', 'wayland'].includes(facts.desktopSession ?? '')) {
    unqualified.push('desktop_session_unavailable')
  }
  return unqualified.length > 0
    ? { qualification: 'not_qualified', reasons: unqualified }
    : { qualification: 'qualified', reasons: [] }
}

const currentDesktopRuntimeFacts = (): DesktopRuntimeFacts => {
  const sessionType = String(process.env['XDG_SESSION_TYPE'] ?? '').trim().toLowerCase()
  const desktopSession = process.platform === 'win32'
    ? 'windows'
    : ['x11', 'wayland'].includes(sessionType)
      ? sessionType
      : process.env['WAYLAND_DISPLAY']
        ? 'wayland'
        : process.env['DISPLAY']
          ? 'x11'
          : null
  return {
    platform: process.platform,
    arch: process.arch,
    nodeVersion: process.versions.node,
    electronVersion: process.versions['electron'] ?? null,
    desktopSession,
  }
}

export interface OnboardingRepairPorts {
  openPanel: (section: string) => Promise<void>
  prepareResource: (resourceId: 'soulx' | 'sherpa' | 'sherpa_online' | 'embedding' | 'tts') => Promise<unknown>
  reloadAvatar: () => void
  refreshMcp: () => Promise<unknown>
  openLogs: () => Promise<void>
  openInstallGuide: () => Promise<void>
}

export interface OnboardingHostPorts {
  avatar: () => Promise<{ visible: boolean; fallback: boolean; message?: string }>
}

const REQUIRED_TEXT_IDS = new Set<OnboardingProbeId>(ONBOARDING_REQUIRED_TEXT_PROBES)
const PYTHON_PROBE_IDS: OnboardingProbeId[] = [
  'backend.service', 'llm.provider', 'llm.model_chat', 'tts.status', 'asr.runtime',
  'database.status', 'memory.status', 'mcp.snapshot',
]
const PYTHON_PROBE_ID_SET = new Set<OnboardingProbeId>(PYTHON_PROBE_IDS)
const SECRET_KEY_PATTERN = /(authorization|token|secret|api.?key|credential|password)/i

const redactEvidence = (value: unknown): unknown => {
  if (Array.isArray(value)) return value.map(redactEvidence)
  if (!value || typeof value !== 'object') {
    if (typeof value === 'string') {
      if (/^(bearer\s+|sk-|[a-z0-9_-]{32,}$)/i.test(value)) return '[redacted]'
      return value.replace(/\b(api[_-]?key|token|secret|authorization)\s*[:=]\s*[^\s,;]+/gi, '$1=[redacted]')
    }
    return value
  }
  return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([key, child]) => [
    key,
    SECRET_KEY_PATTERN.test(key) ? '[redacted]' : redactEvidence(child),
  ]))
}

const hostProbe = (
  id: OnboardingProbeId,
  label: string,
  status: OnboardingProbeResult['status'],
  requiredForText: boolean,
  message: string,
  repairActionId: OnboardingRepairActionId | null = null,
  evidence: Record<string, unknown> = {},
): OnboardingProbeResult => ({
  id,
  label,
  status,
  requiredForText,
  dependencies: [],
  timeoutMs: 0,
  message,
  evidence,
  repairActionId,
})

const normalizePythonProbe = (value: unknown): OnboardingProbeResult | null => {
  if (!value || typeof value !== 'object') return null
  const probe = value as Record<string, unknown>
  if (!isOnboardingProbeId(probe['id']) || !PYTHON_PROBE_ID_SET.has(probe['id'])) return null
  const rawStatus = String(probe['status'] || 'failed')
  const status: OnboardingProbeResult['status'] = rawStatus === 'ready' || rawStatus === 'running' ||
    rawStatus === 'pending' || rawStatus === 'cancelled' || rawStatus === 'needs_user' ||
    rawStatus === 'degraded' || rawStatus === 'unavailable'
    ? rawStatus
    : 'failed'
  const dependencies = Array.isArray(probe['dependencies'])
    ? probe['dependencies'].filter(isOnboardingProbeId)
    : []
  const repairActionId = isOnboardingRepairActionId(probe['repairActionId']) ? probe['repairActionId'] : null
  return {
    id: probe['id'],
    label: typeof probe['label'] === 'string' ? probe['label'] : probe['id'],
    status,
    requiredForText: REQUIRED_TEXT_IDS.has(probe['id']),
    dependencies,
    timeoutMs: Number.isFinite(probe['timeoutMs']) ? Math.max(0, Number(probe['timeoutMs'])) : 0,
    message: typeof probe['message'] === 'string' ? probe['message'].slice(0, 500) : '',
    ...(isOnboardingProbeMessageKey(probe['messageKey']) ? { messageKey: probe['messageKey'] } : {}),
    evidence: (redactEvidence(probe['evidence']) as Record<string, unknown>) ?? {},
    repairActionId,
  }
}

export class OnboardingReadinessCoordinator {
  private operationGeneration = 0
  private scanGeneration = 0
  private activeScan: {
    localRunId: string
    pythonRunId?: string
    pythonRevision?: number
    controller: AbortController
    promise: Promise<OnboardingReadinessSnapshot>
  } | null = null

  constructor(
    private readonly store: OnboardingReadinessStore,
    private readonly pythonService: PythonService,
    private readonly backendOrigin: string,
    private readonly backendApiToken: string,
    private readonly hostPorts: OnboardingHostPorts,
    private readonly repairPorts: OnboardingRepairPorts,
    private readonly fetchImpl: FetchLike = fetch,
    private readonly scanTimeoutMs = 30_000,
    private readonly runtimeFactsProvider: () => DesktopRuntimeFacts = currentDesktopRuntimeFacts,
  ) {}

  snapshot(): OnboardingReadinessSnapshot {
    return this.store.get()
  }

  async startBackend(): Promise<OnboardingReadinessSnapshot> {
    const generation = ++this.operationGeneration
    this.updateBackendProbe('running', 'Starting backend')
    try {
      await this.pythonService.start()
      if (generation !== this.operationGeneration) return this.snapshot()
      this.updateBackendProbe('ready', 'Backend is available')
      return await this.runProbe({})
    } catch (error) {
      if (generation !== this.operationGeneration) return this.snapshot()
      this.updateBackendProbe('failed', this.safeError(error))
      return this.snapshot()
    }
  }

  async cancelBackend(): Promise<OnboardingReadinessSnapshot> {
    this.operationGeneration += 1
    await this.pythonService.cancelStart()
    this.updateBackendProbe('cancelled', 'Backend start cancelled')
    return this.snapshot()
  }

  async runProbe(request: OnboardingProbeRequest): Promise<OnboardingReadinessSnapshot> {
    if (this.activeScan) {
      const previous = this.activeScan
      previous.controller.abort()
      if (previous.pythonRunId) await this.cancelPythonRun(previous.pythonRunId)
      await previous.promise.catch(() => this.snapshot())
    }
    const generation = ++this.scanGeneration
    const runId = randomUUID()
    const controller = new AbortController()
    const deadline = setTimeout(() => controller.abort(), this.scanTimeoutMs)
    const promise = this.executeRunProbe(request, runId, generation, controller.signal)
    this.activeScan = { localRunId: runId, controller, promise }
    try {
      return await promise
    } finally {
      clearTimeout(deadline)
      if (this.activeScan?.promise === promise) this.activeScan = null
    }
  }

  async cancelRun(request: OnboardingCancelRunRequest): Promise<OnboardingReadinessSnapshot> {
    const active = this.activeScan
    if (!active || (request.runId !== active.pythonRunId && request.runId !== active.localRunId)) throw new Error('Stale onboarding runId')
    active.controller.abort()
    if (active.pythonRunId) await this.cancelPythonRun(active.pythonRunId)
    await active.promise.catch(() => this.snapshot())
    return this.snapshot()
  }

  reportDeviceProbe(report: OnboardingDeviceProbeReport): OnboardingReadinessSnapshot {
    const current = this.snapshot()
    const label = report.probeId === 'host.microphone' ? 'Microphone' : 'Speaker'
    const messages: Record<OnboardingDeviceProbeReport['messageCode'], string> = {
      permission_granted: 'Microphone permission and capture succeeded',
      permission_denied: 'Microphone permission was denied',
      no_device: 'No matching audio device is available',
      test_completed: 'Speaker test completed',
      test_failed: 'Audio device test failed',
    }
    const probe = hostProbe(report.probeId, label, report.outcome, false, messages[report.messageCode], 'navigate:settings', {
      source: 'user_gesture',
      reportedAt: new Date().toISOString(),
      messageCode: report.messageCode,
    })
    const probes = [...current.probes.filter((candidate) => candidate.id !== report.probeId), probe]
    return this.store.set({ ...current, revision: current.revision + 1, probes })
  }

  private async executeRunProbe(
    request: OnboardingProbeRequest,
    runId: string,
    generation: number,
    signal: AbortSignal,
  ): Promise<OnboardingReadinessSnapshot> {
    const startedAt = new Date().toISOString()
    const selected = request.probeIds?.length ? new Set(request.probeIds) : null
    const base = this.snapshot()
    this.store.set({
      ...base,
      runId,
      revision: base.revision + 1,
      state: 'running',
      operation: 'probe_scan',
      readyForText: false,
      startedAt,
      completedAt: null,
    })

    const hostProbes = await this.collectHostProbes(selected, signal)
    const pythonSnapshot = await this.collectPythonSnapshot(request, signal)
    if (generation !== this.scanGeneration) return this.snapshot()
    if (signal.aborted) {
      const cancelled = this.snapshot()
      return this.store.set({
        ...cancelled,
        revision: cancelled.revision + 1,
        state: 'cancelled',
        operation: 'idle',
        readyForText: false,
        completedAt: new Date().toISOString(),
        probes: cancelled.probes.map((probe) => probe.status === 'running' ? { ...probe, status: 'cancelled' } : probe),
      })
    }
    const existing = this.snapshot().probes.filter((probe) => !hostProbes.some((host) => host.id === probe.id))
    const selectedPythonIds = request.probeIds?.filter((id) => PYTHON_PROBE_IDS.includes(id)) ?? PYTHON_PROBE_IDS
    const pythonProbes = pythonSnapshot?.probes.map(normalizePythonProbe).filter((probe): probe is OnboardingProbeResult => probe !== null) ?? []
    const returnedPythonIds = new Set(pythonProbes.map((probe) => probe.id))
    const unavailablePythonProbes = selectedPythonIds
      .filter((id) => !returnedPythonIds.has(id))
      .map((id) => hostProbe(
        id,
        id,
        'unavailable',
        REQUIRED_TEXT_IDS.has(id),
        'Readiness probe transport unavailable',
        `probe.retry:${id}`,
        { category: 'transport' },
      ))
    const merged = new Map<OnboardingProbeId, OnboardingProbeResult>()
    for (const probe of [...existing, ...unavailablePythonProbes, ...pythonProbes, ...hostProbes]) merged.set(probe.id, probe)
    const probes = [...merged.values()]
    const readyForText = ONBOARDING_REQUIRED_TEXT_PROBES.every((id) => probes.find((probe) => probe.id === id)?.status === 'ready')
    const completedAt = new Date().toISOString()
    return this.store.set({
      schemaVersion: ONBOARDING_SCHEMA_VERSION,
      runId: pythonSnapshot?.runId ?? runId,
      revision: this.snapshot().revision + 1,
      state: readyForText ? 'ready' : 'blocked',
      operation: 'idle',
      readyForText,
      startedAt,
      completedAt,
      probes,
    })
  }

  async retry(request: OnboardingRetryRequest): Promise<OnboardingReadinessSnapshot> {
    if (request.runId !== this.snapshot().runId) throw new Error('Stale onboarding runId')
    return this.runProbe({ ...(request.probeIds ? { probeIds: request.probeIds } : {}) })
  }

  async runRepair(actionId: OnboardingRepairActionId): Promise<OnboardingReadinessSnapshot> {
    if (!isOnboardingRepairActionId(actionId)) throw new Error('Unknown onboarding repair action')
    if (actionId === 'backend.retry') return this.startBackend()
    if (actionId === 'avatar.reload') this.repairPorts.reloadAvatar()
    else if (actionId === 'mcp.refresh_existing') await this.repairPorts.refreshMcp()
    else if (actionId === 'logs.open') await this.repairPorts.openLogs()
    else if (actionId === 'guide.open') await this.repairPorts.openInstallGuide()
    else if (actionId.startsWith('probe.retry:')) {
      const probeId = actionId.slice('probe.retry:'.length)
      if (!isOnboardingProbeId(probeId)) throw new Error('Unknown onboarding probe')
      return this.runProbe({ probeIds: [probeId] })
    } else if (actionId.startsWith('navigate:')) {
      await this.repairPorts.openPanel(actionId.slice('navigate:'.length))
    } else if (actionId.startsWith('resource.prepare:')) {
      const resourceId = actionId.slice('resource.prepare:'.length) as Parameters<OnboardingRepairPorts['prepareResource']>[0]
      await this.repairPorts.prepareResource(resourceId)
    }
    return this.snapshot()
  }

  private async collectHostProbes(selected: Set<OnboardingProbeId> | null, signal: AbortSignal): Promise<OnboardingProbeResult[]> {
    const probes: OnboardingProbeResult[] = []
    const include = (id: OnboardingProbeId) => !selected || selected.has(id)
    if (include('host.runtime')) {
      const facts = this.runtimeFactsProvider()
      const result = qualifyDesktopRuntime(facts)
      const ready = result.qualification === 'qualified'
      probes.push(hostProbe(
        'host.runtime',
        'Desktop runtime',
        ready ? 'ready' : 'unavailable',
        true,
        ready ? 'Desktop runtime is supported' : 'Desktop runtime is not qualified',
        ready ? null : 'guide.open',
        {
          qualification: result.qualification,
          reasons: result.reasons,
          platform: facts.platform,
          arch: facts.arch,
          node: facts.nodeVersion,
          electron: facts.electronVersion,
          desktopSession: facts.desktopSession,
          measurement: 'runtime_probe',
          realDeviceQualification: 'not_measured',
        },
      ))
    }
    if (include('backend.service')) {
      try {
        const healthy = await this.awaitHostProbe(this.pythonService.health(), signal)
        probes.push(hostProbe('backend.service', 'Backend service', healthy ? 'ready' : 'failed', true,
          healthy ? 'Backend is available' : this.pythonService.getStatus().error || 'Backend is unavailable', 'backend.retry'))
      } catch {
        probes.push(hostProbe('backend.service', 'Backend service', 'unavailable', true,
          'Backend health probe timed out', 'backend.retry', { category: 'timeout' }))
      }
    }
    if (include('host.avatar')) {
      try {
        const avatar = await this.awaitHostProbe(this.hostPorts.avatar(), signal)
        probes.push(hostProbe('host.avatar', 'Avatar', avatar.visible ? 'ready' : 'failed', false,
          avatar.message || (avatar.visible ? 'Avatar is visible' : 'Avatar is not visible'), 'avatar.reload', {
            visible: avatar.visible,
            fallback: avatar.fallback,
          }))
      } catch {
        probes.push(hostProbe('host.avatar', 'Avatar', 'unavailable', false,
          'Avatar visibility probe timed out', 'avatar.reload', { category: 'timeout' }))
      }
    }
    if (include('host.microphone')) probes.push(hostProbe('host.microphone', 'Microphone', 'needs_user', false,
      'Microphone check requires a user gesture', 'navigate:settings'))
    if (include('host.speaker')) probes.push(hostProbe('host.speaker', 'Speaker', 'needs_user', false,
      'Speaker check requires a user gesture', 'navigate:settings'))
    return probes
  }

  private async awaitHostProbe<T>(operation: Promise<T>, signal: AbortSignal): Promise<T> {
    signal.throwIfAborted()
    return new Promise<T>((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('Host probe timed out')), Math.min(2_000, this.scanTimeoutMs))
      const abort = () => reject(new Error('Host probe cancelled'))
      signal.addEventListener('abort', abort, { once: true })
      operation.then(resolve, reject).finally(() => {
        clearTimeout(timeout)
        signal.removeEventListener('abort', abort)
      })
    })
  }

  private async collectPythonSnapshot(request: OnboardingProbeRequest, signal: AbortSignal): Promise<{ runId: string; probes: unknown[] } | null> {
    try {
      if (!(await this.awaitHostProbe(this.pythonService.health(), signal))) return null
    } catch {
      return null
    }
    const pythonProbeIds = request.probeIds?.filter((id) => !id.startsWith('host.'))
    if (request.probeIds && pythonProbeIds?.length === 0) return null
    const path = '/api/system/onboarding/readiness/run'
    try {
      const response = await this.fetchImpl(`${this.backendOrigin}${path}`, {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          'x-yuizaki-backend-token': this.backendApiToken,
        },
        body: JSON.stringify({ ...(pythonProbeIds?.length ? { probeIds: pythonProbeIds } : {}) }),
        signal,
      })
      if (!response.ok) return null
      let payload = await response.json() as { schemaVersion?: unknown; runId?: unknown; revision?: unknown; state?: unknown; probes?: unknown }
      if (signal.aborted) return null
      const pythonRunId = typeof payload.runId === 'string' ? payload.runId.trim() : ''
      let pythonRevision = Number.isInteger(payload.revision) ? Number(payload.revision) : -1
      if (payload.schemaVersion !== ONBOARDING_SCHEMA_VERSION || !pythonRunId || pythonRevision < 0 || !this.activeScan) return null
      this.activeScan.pythonRunId = pythonRunId
      this.activeScan.pythonRevision = pythonRevision
      const current = this.snapshot()
      this.store.set({ ...current, runId: pythonRunId, revision: current.revision + 1 })
      while (payload.state === 'running' && !signal.aborted) {
        await new Promise<void>((resolve) => {
          const timer = setTimeout(resolve, 250)
          signal.addEventListener('abort', () => {
            clearTimeout(timer)
            resolve()
          }, { once: true })
        })
        if (signal.aborted) return null
        const poll = await this.fetchImpl(`${this.backendOrigin}/api/system/onboarding/readiness`, {
          headers: { 'x-yuizaki-backend-token': this.backendApiToken },
          signal,
        })
        if (!poll.ok) return null
        const nextPayload = await poll.json() as { schemaVersion?: unknown; runId?: unknown; revision?: unknown; state?: unknown; probes?: unknown }
        const nextRevision = Number.isInteger(nextPayload.revision) ? Number(nextPayload.revision) : -1
        if (nextPayload.schemaVersion !== ONBOARDING_SCHEMA_VERSION || nextPayload.runId !== pythonRunId || nextRevision < pythonRevision) return null
        pythonRevision = nextRevision
        if (this.activeScan?.pythonRunId === pythonRunId) this.activeScan.pythonRevision = pythonRevision
        payload = nextPayload
      }
      return Array.isArray(payload.probes) ? {
        runId: pythonRunId,
        probes: payload.probes,
      } : null
    } catch {
      return null
    }
  }

  private async cancelPythonRun(runId: string): Promise<void> {
    if (!(await this.pythonService.health())) return
    try {
      await this.fetchImpl(`${this.backendOrigin}/api/system/onboarding/readiness/cancel`, {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          'x-yuizaki-backend-token': this.backendApiToken,
        },
        body: JSON.stringify({ runId }),
      })
    } catch {
      // Local abort is authoritative even if the backend disappeared.
    }
  }

  private updateBackendProbe(status: OnboardingProbeResult['status'], message: string): void {
    const current = this.snapshot()
    const probe = hostProbe('backend.service', 'Backend service', status, true, message, 'backend.retry')
    const probes = [...current.probes.filter((candidate) => candidate.id !== probe.id), probe]
    const readyForText = ONBOARDING_REQUIRED_TEXT_PROBES.every((id) => probes.find((candidate) => candidate.id === id)?.status === 'ready')
    this.store.set({
      ...current,
      revision: current.revision + 1,
      state: status === 'running' ? 'running' : readyForText ? 'ready' : status === 'cancelled' ? 'cancelled' : 'blocked',
      operation: status === 'running' ? 'backend_start' : 'idle',
      readyForText,
      completedAt: status === 'running' ? null : new Date().toISOString(),
      probes,
    })
  }

  private safeError(error: unknown): string {
    const message = error instanceof Error ? error.message : String(error)
    return message.replace(/(bearer\s+|sk-)[a-z0-9._-]+/gi, '$1[redacted]').slice(0, 500)
  }
}
