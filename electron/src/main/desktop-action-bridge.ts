import type {
  DesktopActionResult,
  DesktopActionStatus,
} from '../shared/desktop-action'

const MAX_MESSAGE_LENGTH = 256
const HOST_LEASE_TTL_SECONDS = 5
const STOP_ATTEMPTS = 3
const STOP_RETRY_DELAY_MS = 100

interface DesktopActionDiscoveredApp {
  appId: string
  label: string
  windowTitles: string[]
}

export interface DesktopActionBackendResponse {
  ok: boolean
  enabled?: boolean
  windowActionsAvailable?: boolean
  nativeInputAvailable?: boolean
  emergencyStopped?: boolean
  revision?: number
  stopEpoch?: number
  leaseEpoch?: number
  leaseExpiresInMs?: number
  discoveryRevision?: number
  apps?: DesktopActionDiscoveredApp[]
  authorizationExpiresInMs?: number
  reason?: string
  code?: string
  message?: string
}

export interface DesktopActionBackendPort {
  status(signal: AbortSignal): Promise<DesktopActionBackendResponse>
  enable(signal: AbortSignal): Promise<DesktopActionBackendResponse>
  disable(signal: AbortSignal): Promise<DesktopActionBackendResponse>
  rearm(signal: AbortSignal): Promise<DesktopActionBackendResponse>
  emergencyStop(signal: AbortSignal): Promise<DesktopActionBackendResponse>
  heartbeat(signal: AbortSignal, leaseEpoch: number): Promise<DesktopActionBackendResponse>
  discover(signal: AbortSignal): Promise<DesktopActionBackendResponse>
  grant(signal: AbortSignal, appId: string, discoveryRevision: number): Promise<DesktopActionBackendResponse>
}

export interface DesktopActionBridgeDependencies {
  confirmNativeEnable(mode: 'enable' | 'rearm', signal: AbortSignal): Promise<boolean>
  selectNativeApp(apps: ReadonlyArray<{ id: string; label: string; windowTitles: readonly string[] }>, signal: AbortSignal): Promise<string | null>
  isEmergencyHotkeyAvailable(): boolean
  now?: () => number
}

type FetchLike = typeof fetch
type Operation = 'enable' | 'disable' | 'rearm' | 'emergency-stop' | 'heartbeat' | 'status' | 'discover' | 'grant'

const isInteger = (value: unknown, minimum: number, maximum: number): value is number =>
  Number.isSafeInteger(value) && Number(value) >= minimum && Number(value) <= maximum

const boundedText = (value: unknown, fallback: string): string =>
  typeof value === 'string' && value.trim() ? value.trim().slice(0, MAX_MESSAGE_LENGTH) : fallback

const boundedCounter = (value: unknown): number | undefined =>
  isInteger(value, 0, Number.MAX_SAFE_INTEGER) ? value : undefined

const projectApps = (value: unknown): DesktopActionDiscoveredApp[] | undefined => {
  if (!Array.isArray(value)) return undefined
  const apps: DesktopActionDiscoveredApp[] = []
  for (const item of value.slice(0, 100)) {
    if (!item || typeof item !== 'object' || Array.isArray(item)) continue
    const record = item as Record<string, unknown>
    const appId = boundedText(record['app_id'] ?? record['appId'], '')
    const label = boundedText(record['app_label'] ?? record['label'], 'Application')
    if (!appId.startsWith('das_app_')) continue
    const directTitles = Array.isArray(record['windowTitles']) ? record['windowTitles'] : []
    const windows = Array.isArray(record['windows']) ? record['windows'] : []
    const windowTitles = directTitles.slice(0, 100).flatMap((title) => {
      const bounded = boundedText(title, '')
      return bounded ? [bounded] : []
    }).concat(windows.slice(0, 100).flatMap((window) => {
      if (!window || typeof window !== 'object' || Array.isArray(window)) return []
      const title = boundedText((window as Record<string, unknown>)['title'], '')
      return title ? [title] : []
    }))
    apps.push({ appId, label, windowTitles })
  }
  return apps
}

const projectBackendResponse = (value: unknown): DesktopActionBackendResponse => {
  const record = value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
  const ok = record['ok'] === true
  const revision = boundedCounter(record['feature_revision'] ?? record['revision'])
  const stopEpoch = boundedCounter(record['stop_epoch'] ?? record['stopEpoch'])
  const leaseEpoch = boundedCounter(record['lease_epoch'] ?? record['leaseEpoch'])
  const leaseExpiresInMs = boundedCounter(record['lease_expires_in_ms'] ?? record['leaseExpiresInMs'])
  const discoveryRevision = boundedCounter(record['discovery_revision'] ?? record['discoveryRevision'])
  const authorizationExpiresInMs = boundedCounter(record['expires_in_ms'] ?? record['authorizationExpiresInMs'])
  const apps = projectApps(record['apps'])
  const rawWindowActionsAvailable = record['window_actions_available'] ?? record['windowActionsAvailable']
  const windowActionsAvailable = typeof rawWindowActionsAvailable === 'boolean'
    ? rawWindowActionsAvailable
    : undefined
  const emergencyStopped = record['emergency_stopped'] ?? record['emergencyStopped']
  return {
    ok,
    ...(typeof record['enabled'] === 'boolean' ? { enabled: record['enabled'] } : {}),
    ...(windowActionsAvailable !== undefined ? { windowActionsAvailable } : {}),
    nativeInputAvailable: false,
    ...(typeof emergencyStopped === 'boolean' ? { emergencyStopped } : {}),
    ...(revision !== undefined ? { revision } : {}),
    ...(stopEpoch !== undefined ? { stopEpoch } : {}),
    ...(leaseEpoch !== undefined ? { leaseEpoch } : {}),
    ...(leaseExpiresInMs !== undefined ? { leaseExpiresInMs } : {}),
    ...(discoveryRevision !== undefined ? { discoveryRevision } : {}),
    ...(authorizationExpiresInMs !== undefined ? { authorizationExpiresInMs } : {}),
    ...(apps !== undefined ? { apps } : {}),
    ...(typeof record['reason'] === 'string' ? { reason: boundedText(record['reason'], 'unavailable') } : {}),
    ...(!ok ? {
      code: boundedText(record['code'], 'DA_BACKEND_REJECTED'),
      message: boundedText(record['message'] ?? record['reason'], 'desktop action backend rejected the request'),
    } : {}),
  }
}

const cloneStatus = (status: DesktopActionStatus): DesktopActionStatus => structuredClone(status)

export class DesktopActionBridge {
  private state: DesktopActionStatus = {
    enabled: false,
    windowActionsAvailable: false,
    nativeInputAvailable: false,
    emergencyHotkeyAvailable: false,
    emergencyStopped: false,
    revision: 0,
    stopEpoch: 0,
    operationInFlight: false,
    degraded: false,
    leaseState: 'inactive',
    leaseExpiresAt: null,
    lastHeartbeatAt: null,
    authorizationGranted: false,
    authorizationExpiresAt: null,
    reason: 'desktop action beta is disabled',
    lastError: null,
  }
  private readonly pendingControllers = new Set<AbortController>()
  private stopPromise: Promise<DesktopActionResult<DesktopActionStatus>> | null = null
  private heartbeatTimer: ReturnType<typeof setTimeout> | null = null
  private leaseEpoch: number | null = null
  private operationGeneration = 0
  private disposed = false

  constructor(
    private readonly backend: DesktopActionBackendPort,
    private readonly dependencies: DesktopActionBridgeDependencies,
    private readonly timeoutMs = 2_000,
  ) {}

  getStatus(): DesktopActionStatus {
    this.expireAuthorizationProjection()
    return cloneStatus({
      ...this.state,
      emergencyHotkeyAvailable: this.dependencies.isEmergencyHotkeyAvailable(),
    })
  }

  async refreshStatus(): Promise<DesktopActionResult<DesktopActionStatus>> {
    const priorLeaseFailure = this.state.leaseState === 'unconfirmed'
      ? { lastError: this.state.lastError, reason: this.state.reason }
      : null
    const response = await this.callBackend('status', (signal) => this.backend.status(signal))
    if (!response.ok) return response
    this.applyBackendStatus(response.data)
    if (this.state.emergencyStopped || this.state.leaseState !== 'confirmed') this.state.enabled = false
    if (priorLeaseFailure !== null) {
      this.markLeaseUnconfirmed()
      this.state.lastError = priorLeaseFailure.lastError
      this.state.reason = priorLeaseFailure.reason
    }
    return this.success(this.getStatus())
  }

  enable(): Promise<DesktopActionResult<DesktopActionStatus>> {
    return this.confirmAndSet('enable')
  }

  rearm(): Promise<DesktopActionResult<DesktopActionStatus>> {
    return this.confirmAndSet('rearm')
  }

  async manageAuthorization(): Promise<DesktopActionResult<DesktopActionStatus>> {
    if (this.disposed) return this.failure('DA_BRIDGE_DISPOSED', 'desktop action bridge is disposed')
    if (this.state.operationInFlight) return this.failure('DA_OPERATION_IN_FLIGHT', 'another desktop action operation is in flight')
    const gate = this.gateAvailability()
    if (gate !== null || this.state.leaseState !== 'confirmed' || !this.state.enabled) {
      return gate ?? this.failure('DA_HOST_LEASE_UNCONFIRMED', 'desktop action host lease is not confirmed')
    }
    this.state.operationInFlight = true
    const generation = this.operationGeneration
    try {
      const discovered = await this.callBackend('discover', (signal) => this.backend.discover(signal))
      if (!discovered.ok) return discovered
      if (generation !== this.operationGeneration) return this.failure('DA_OPERATION_REVOKED', 'desktop action authorization was revoked')
      const revision = discovered.data.discoveryRevision
      const apps = discovered.data.apps ?? []
      if (revision === undefined || apps.length === 0) return this.failure('DA_NO_APPLICATIONS', 'no applications are available for authorization')
      const controller = new AbortController()
      this.pendingControllers.add(controller)
      let selected: string | null
      try {
        selected = await this.dependencies.selectNativeApp(
          apps.map((app) => ({ id: app.appId, label: app.label, windowTitles: app.windowTitles })),
          controller.signal,
        )
      } catch {
        return this.failure('DA_APP_PICKER_UNAVAILABLE', 'application authorization picker is unavailable')
      } finally {
        this.pendingControllers.delete(controller)
      }
      if (controller.signal.aborted || generation !== this.operationGeneration) return this.failure('DA_OPERATION_REVOKED', 'desktop action authorization was revoked')
      if (selected === null) return this.failure('DA_APP_PICKER_CANCELLED', 'application authorization was cancelled')
      if (!apps.some((app) => app.appId === selected)) return this.failure('DA_APP_SCOPE_MISMATCH', 'selected application is not in the current discovery')
      const granted = await this.callBackend('grant', (signal) => this.backend.grant(signal, selected, revision))
      if (!granted.ok) return granted
      if (generation !== this.operationGeneration) return this.failure('DA_OPERATION_REVOKED', 'desktop action authorization was revoked')
      this.state.authorizationGranted = true
      this.state.authorizationExpiresAt = this.expiresAt(granted.data.authorizationExpiresInMs)
      this.clearError()
      return this.success(this.getStatus())
    } finally {
      if (generation === this.operationGeneration) this.state.operationInFlight = false
    }
  }

  async disable(): Promise<DesktopActionResult<DesktopActionStatus>> {
    if (this.state.operationInFlight) return this.failure('DA_OPERATION_IN_FLIGHT', 'another desktop action operation is in flight')
    this.beginLocalFence(false)
    this.state.operationInFlight = true
    const generation = this.operationGeneration
    const response = await this.callBackend('disable', (signal) => this.backend.disable(signal))
    this.state.operationInFlight = false
    if (!response.ok) {
      this.markLeaseUnconfirmed()
      return response
    }
    if (generation !== this.operationGeneration) return this.failure('DA_OPERATION_REVOKED', 'desktop action operation was revoked')
    this.applyBackendStatus(response.data)
    this.state.enabled = false
    this.state.leaseState = 'inactive'
    return this.success(this.getStatus())
  }

  beginEmergencyFence(): void {
    this.beginLocalFence(true)
  }

  emergencyStop(): Promise<DesktopActionResult<DesktopActionStatus>> {
    if (this.stopPromise !== null) return this.stopPromise
    const priorLeaseFailure = this.state.leaseState === 'unconfirmed'
      ? { lastError: this.state.lastError, reason: this.state.reason }
      : null
    this.beginEmergencyFence()
    this.state.operationInFlight = true
    const generation = this.operationGeneration
    this.stopPromise = (async () => {
      let response: DesktopActionResult<DesktopActionBackendResponse> | null = null
      for (let attempt = 1; attempt <= STOP_ATTEMPTS; attempt += 1) {
        response = await this.callBackend('emergency-stop', (signal) => this.backend.emergencyStop(signal))
        if (response.ok) break
        if (attempt < STOP_ATTEMPTS && await this.waitForRetry(generation) === false) break
      }
      this.state.operationInFlight = false
      if (response === null || !response.ok) {
        this.markLeaseUnconfirmed()
        return response ?? this.failure('DA_BACKEND_UNAVAILABLE', 'emergency-stop backend unavailable')
      }
      if (generation !== this.operationGeneration) return this.failure('DA_OPERATION_REVOKED', 'desktop action stop was superseded')
      this.applyBackendStatus(response.data)
      this.state.enabled = false
      this.state.emergencyStopped = true
      this.state.leaseState = 'inactive'
      if (priorLeaseFailure !== null) {
        this.markLeaseUnconfirmed()
        this.state.lastError = priorLeaseFailure.lastError
        this.state.reason = priorLeaseFailure.reason
      }
      return this.success(this.getStatus())
    })().finally(() => {
      this.stopPromise = null
    })
    return this.stopPromise
  }

  dispose(): void {
    if (this.disposed) return
    this.beginLocalFence(true)
    this.disposed = true
    void this.stopBackendAfterDispose()
    this.state.degraded = true
    this.state.reason = 'desktop action bridge is disposed'
    this.state.lastError = {
      at: new Date(this.now()).toISOString(),
      code: 'DA_BRIDGE_DISPOSED',
      message: 'desktop action bridge is disposed',
    }
  }

  private async confirmAndSet(mode: 'enable' | 'rearm'): Promise<DesktopActionResult<DesktopActionStatus>> {
    if (this.disposed) return this.failure('DA_BRIDGE_DISPOSED', 'desktop action bridge is disposed')
    if (this.state.operationInFlight) return this.failure('DA_OPERATION_IN_FLIGHT', 'another desktop action operation is in flight')
    if (mode === 'enable' && this.state.emergencyStopped) return this.failure('DA_REARM_REQUIRED', 'desktop actions require explicit rearm after emergency stop')
    this.state.operationInFlight = true
    const generation = this.operationGeneration
    let result: DesktopActionResult<DesktopActionStatus>
    try {
      result = await this.performConfirmedSet(mode, generation)
    } finally {
      if (generation === this.operationGeneration) this.state.operationInFlight = false
    }
    return { ...result, status: this.getStatus() }
  }

  private async performConfirmedSet(
    mode: 'enable' | 'rearm',
    generation: number,
  ): Promise<DesktopActionResult<DesktopActionStatus>> {
    const status = await this.callBackend('status', (signal) => this.backend.status(signal))
    if (!status.ok) return status
    this.applyBackendStatus(status.data)
    if (mode === 'enable' && this.state.emergencyStopped) {
      return this.failure('DA_REARM_REQUIRED', 'desktop actions require explicit rearm after emergency stop')
    }
    const gate = this.gateAvailability()
    if (gate !== null) return gate
    const controller = new AbortController()
    this.pendingControllers.add(controller)
    let confirmed: boolean
    try {
      const aborted = new Promise<false>((resolve) => {
        controller.signal.addEventListener('abort', () => resolve(false), { once: true })
      })
      confirmed = await Promise.race([
        Promise.resolve().then(() => this.dependencies.confirmNativeEnable(mode, controller.signal)),
        aborted,
      ])
    } catch {
      return this.failure('DA_CONFIRMATION_UNAVAILABLE', 'native desktop action confirmation is unavailable')
    } finally {
      this.pendingControllers.delete(controller)
    }
    if (controller.signal.aborted || generation !== this.operationGeneration) {
      return this.failure('DA_CONFIRMATION_REVOKED', 'desktop action confirmation was revoked')
    }
    if (!confirmed) return this.failure('DA_CONFIRMATION_DECLINED', 'desktop action confirmation was declined')
    const freshGate = this.gateAvailability()
    if (freshGate !== null) return freshGate
    const response = await this.callBackend(mode, (signal) => this.backend[mode](signal))
    if (generation !== this.operationGeneration) return this.failure('DA_OPERATION_REVOKED', 'desktop action operation was revoked')
    if (!response.ok) return response
    this.applyBackendStatus(response.data)
    if (mode === 'rearm' && response.data.emergencyStopped !== false) {
      this.beginLocalFence(true)
      return this.failure('DA_BACKEND_NOT_REARMED', 'desktop action backend did not clear the emergency-stop latch')
    }
    if (response.data.enabled !== true || response.data.leaseEpoch === undefined || !response.data.leaseExpiresInMs) {
      this.beginLocalFence(true)
      return this.failure('DA_BACKEND_LEASE_INVALID', 'desktop action backend did not return an active host lease')
    }
    this.leaseEpoch = response.data.leaseEpoch
    this.state.enabled = true
    this.state.leaseState = 'confirmed'
    this.state.leaseExpiresAt = this.expiresAt(response.data.leaseExpiresInMs)
    if (mode === 'rearm') this.state.emergencyStopped = false
    this.state.reason = null
    this.clearError()
    this.scheduleHeartbeat(generation, response.data.leaseExpiresInMs)
    return this.success(this.getStatus())
  }

  private gateAvailability(): DesktopActionResult<DesktopActionStatus> | null {
    if (!this.dependencies.isEmergencyHotkeyAvailable()) {
      return this.failure('DA_EMERGENCY_HOTKEY_UNAVAILABLE', 'emergency stop hotkey is unavailable')
    }
    if (!this.state.windowActionsAvailable) {
      return this.failure('DA_WINDOW_ACTIONS_UNAVAILABLE', this.state.reason ?? 'window actions are unavailable')
    }
    return null
  }

  private scheduleHeartbeat(generation: number, expiresInMs: number): void {
    this.clearHeartbeatTimer()
    const delay = Math.max(100, Math.min(1_000, Math.floor(expiresInMs / 3)))
    this.heartbeatTimer = setTimeout(() => {
      this.heartbeatTimer = null
      void this.runHeartbeat(generation)
    }, delay)
  }

  private async runHeartbeat(generation: number): Promise<void> {
    if (
      this.disposed
      || generation !== this.operationGeneration
      || this.leaseEpoch === null
      || !this.state.enabled
      || this.state.leaseState !== 'confirmed'
    ) return
    if (!this.dependencies.isEmergencyHotkeyAvailable()) {
      void this.emergencyStop()
      return
    }
    const leaseEpoch = this.leaseEpoch
    const response = await this.callBackend('heartbeat', (signal) => this.backend.heartbeat(signal, leaseEpoch))
    if (generation !== this.operationGeneration || this.disposed) return
    if (!response.ok || response.data.enabled !== true || response.data.leaseEpoch !== leaseEpoch || !response.data.leaseExpiresInMs) {
      const code = response.ok ? 'DA_HEARTBEAT_INVALID' : response.code
      const message = response.ok ? 'desktop action heartbeat response is invalid' : response.message
      this.beginLocalFence(true)
      this.markLeaseUnconfirmed()
      this.recordError(code, message)
      void this.emergencyStop()
      return
    }
    this.applyBackendStatus(response.data)
    this.leaseEpoch = leaseEpoch
    this.state.enabled = true
    this.state.leaseState = 'confirmed'
    this.state.lastHeartbeatAt = new Date(this.now()).toISOString()
    this.state.leaseExpiresAt = this.expiresAt(response.data.leaseExpiresInMs)
    this.scheduleHeartbeat(generation, response.data.leaseExpiresInMs)
  }

  private beginLocalFence(emergencyStopped: boolean): void {
    this.operationGeneration += 1
    this.clearHeartbeatTimer()
    this.leaseEpoch = null
    for (const controller of this.pendingControllers) controller.abort()
    this.pendingControllers.clear()
    this.state.enabled = false
    this.state.emergencyStopped ||= emergencyStopped
    this.state.operationInFlight = false
    this.state.leaseState = 'inactive'
    this.state.leaseExpiresAt = null
    this.state.authorizationGranted = false
    this.state.authorizationExpiresAt = null
  }

  private clearHeartbeatTimer(): void {
    if (this.heartbeatTimer !== null) clearTimeout(this.heartbeatTimer)
    this.heartbeatTimer = null
  }

  private markLeaseUnconfirmed(): void {
    this.state.enabled = false
    this.state.leaseState = 'unconfirmed'
    this.state.leaseExpiresAt = null
    this.state.authorizationGranted = false
    this.state.authorizationExpiresAt = null
    this.state.degraded = true
  }

  private applyBackendStatus(response: DesktopActionBackendResponse): void {
    if (typeof response.enabled === 'boolean') this.state.enabled = response.enabled
    if (typeof response.windowActionsAvailable === 'boolean') this.state.windowActionsAvailable = response.windowActionsAvailable
    this.state.nativeInputAvailable = false
    if (response.emergencyStopped === true) this.state.emergencyStopped = true
    if (typeof response.revision === 'number') this.state.revision = Math.max(this.state.revision, response.revision)
    if (typeof response.stopEpoch === 'number') this.state.stopEpoch = Math.max(this.state.stopEpoch, response.stopEpoch)
    this.state.enabled = this.state.emergencyStopped ? false : this.state.enabled
    this.state.reason = response.reason ?? (this.state.windowActionsAvailable ? null : this.state.reason)
    this.clearError()
  }

  private async waitForRetry(generation: number): Promise<boolean> {
    if (this.disposed || generation !== this.operationGeneration) return false
    const controller = new AbortController()
    this.pendingControllers.add(controller)
    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        this.pendingControllers.delete(controller)
        resolve(!this.disposed && generation === this.operationGeneration)
      }, STOP_RETRY_DELAY_MS)
      controller.signal.addEventListener('abort', () => {
        clearTimeout(timer)
        this.pendingControllers.delete(controller)
        resolve(false)
      }, { once: true })
    })
  }

  private async stopBackendAfterDispose(): Promise<void> {
    for (let attempt = 1; attempt <= STOP_ATTEMPTS; attempt += 1) {
      const controller = new AbortController()
      const timeout = setTimeout(() => controller.abort(), this.timeoutMs)
      try {
        const response = projectBackendResponse(await this.backend.emergencyStop(controller.signal))
        if (response.ok) return
      } catch {
        // The Python TTL remains the final fail-closed boundary after retries.
      } finally {
        clearTimeout(timeout)
      }
      if (attempt < STOP_ATTEMPTS) await new Promise((resolve) => setTimeout(resolve, STOP_RETRY_DELAY_MS))
    }
  }

  private async callBackend(
    operation: Operation,
    invoke: (signal: AbortSignal) => Promise<DesktopActionBackendResponse>,
  ): Promise<DesktopActionResult<DesktopActionBackendResponse>> {
    if (this.disposed) return this.failure('DA_BRIDGE_DISPOSED', 'desktop action bridge is disposed')
    const controller = new AbortController()
    this.pendingControllers.add(controller)
    let timedOut = false
    const timeout = setTimeout(() => {
      timedOut = true
      controller.abort()
    }, this.timeoutMs)
    const aborted = new Promise<never>((_resolve, reject) => {
      controller.signal.addEventListener('abort', () => reject(new Error('desktop action request aborted')), { once: true })
    })
    try {
      const response = projectBackendResponse(await Promise.race([
        Promise.resolve().then(() => invoke(controller.signal)),
        aborted,
      ]))
      if (!response.ok) return this.failure(response.code ?? 'DA_BACKEND_REJECTED', response.message ?? `${operation} rejected`)
      return { ok: true, data: response, status: this.getStatus() }
    } catch {
      return this.failure(
        timedOut ? 'DA_BACKEND_TIMEOUT' : this.disposed ? 'DA_BRIDGE_DISPOSED' : 'DA_BACKEND_UNAVAILABLE',
        timedOut ? `${operation} timed out` : this.disposed ? 'desktop action bridge is disposed' : `${operation} backend unavailable`,
      )
    } finally {
      clearTimeout(timeout)
      this.pendingControllers.delete(controller)
    }
  }

  private expiresAt(expiresInMs: number | undefined): string | null {
    return expiresInMs === undefined ? null : new Date(this.now() + expiresInMs).toISOString()
  }

  private expireAuthorizationProjection(): void {
    if (!this.state.authorizationGranted || this.state.authorizationExpiresAt === null) return
    const expiresAt = Date.parse(this.state.authorizationExpiresAt)
    if (!Number.isFinite(expiresAt) || expiresAt <= this.now()) {
      this.state.authorizationGranted = false
      this.state.authorizationExpiresAt = null
    }
  }

  private now(): number {
    return this.dependencies.now?.() ?? Date.now()
  }

  private clearError(): void {
    this.state.degraded = false
    this.state.lastError = null
  }

  private recordError(code: string, message: string): void {
    const boundedMessage = boundedText(message, 'desktop action request failed')
    this.state.degraded = true
    this.state.lastError = { at: new Date(this.now()).toISOString(), code, message: boundedMessage }
  }

  private success<T>(data: T): DesktopActionResult<T> {
    return { ok: true, data, status: this.getStatus() }
  }

  private failure<T = DesktopActionStatus>(code: string, message: string): DesktopActionResult<T> {
    const boundedMessage = boundedText(message, 'desktop action request failed')
    this.recordError(code, boundedMessage)
    return { ok: false, code, message: boundedMessage, status: this.getStatus() }
  }
}

export const createAuthenticatedDesktopActionBackendPort = (
  origin: string,
  hostToken: string,
  fetchImpl: FetchLike = fetch,
): DesktopActionBackendPort => {
  if (!hostToken.trim()) {
    const unavailable = async (): Promise<DesktopActionBackendResponse> => ({
      ok: false,
      code: 'DA_HOST_TOKEN_MISSING',
      message: 'desktop action host token is unavailable',
    })
    return {
      status: unavailable,
      enable: unavailable,
      disable: unavailable,
      rearm: unavailable,
      emergencyStop: unavailable,
      heartbeat: unavailable,
      discover: unavailable,
      grant: unavailable,
    }
  }
  const request = async (path: string, method: 'GET' | 'POST', signal: AbortSignal, body?: unknown) => {
    const response = await fetchImpl(new URL(path, origin), {
      method,
      signal,
      headers: {
        Authorization: `Bearer ${hostToken}`,
        'Content-Type': 'application/json',
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    })
    const payload = await response.json().catch(() => ({})) as Record<string, unknown>
    const detail = payload['detail'] && typeof payload['detail'] === 'object' && !Array.isArray(payload['detail'])
      ? payload['detail'] as Record<string, unknown>
      : payload
    return projectBackendResponse(response.ok ? payload : {
      ok: false,
      code: typeof detail['code'] === 'string' ? detail['code'] : `DA_BACKEND_HTTP_${response.status}`,
      message: typeof detail['message'] === 'string' ? detail['message'] : 'desktop action backend request failed',
    })
  }
  return {
    status: (signal) => request('/api/desktop-actions/status', 'GET', signal),
    enable: (signal) => request('/api/desktop-actions/enable', 'POST', signal, { lease_ttl_seconds: HOST_LEASE_TTL_SECONDS }),
    disable: (signal) => request('/api/desktop-actions/disable', 'POST', signal, {}),
    rearm: (signal) => request('/api/desktop-actions/rearm', 'POST', signal, { lease_ttl_seconds: HOST_LEASE_TTL_SECONDS }),
    emergencyStop: (signal) => request('/api/desktop-actions/emergency-stop', 'POST', signal, {}),
    heartbeat: (signal, leaseEpoch) => request('/api/desktop-actions/heartbeat', 'POST', signal, {
      lease_epoch: leaseEpoch,
      lease_ttl_seconds: HOST_LEASE_TTL_SECONDS,
    }),
    discover: (signal) => request('/api/desktop-actions/discover', 'POST', signal, { ttl_seconds: 15 }),
    grant: (signal, appId, discoveryRevision) => request('/api/desktop-actions/grant', 'POST', signal, {
      app_id: appId,
      discovery_revision: discoveryRevision,
      allowed_actions: ['focus', 'request_close'],
      ttl_seconds: 30,
    }),
  }
}
