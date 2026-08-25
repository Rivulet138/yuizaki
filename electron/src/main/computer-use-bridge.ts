import type {
  ComputerUseAction,
  ComputerUseBackendResponse,
  ComputerUseBridgeResult,
  ComputerUseBridgeStatus,
  ComputerUsePreviewRequest,
} from '../shared/computer-use'

const MAX_PREVIEW_ACTIONS = 20
const MAX_PREVIEW_BYTES = 16 * 1024
const MAX_TEXT_LENGTH = 4096
const MAX_BACKEND_MESSAGE_LENGTH = 256
const SUPPORTED_KEYS = new Set([
  'alt', 'backspace', 'ctrl', 'delete', 'down', 'end', 'enter', 'escape', 'home', 'left',
  'meta', 'pagedown', 'pageup', 'right', 'shift', 'space', 'tab', 'up',
  ...Array.from({ length: 12 }, (_, index) => `f${index + 1}`),
  ...'abcdefghijklmnopqrstuvwxyz0123456789',
])

export interface ComputerUseBackendPort {
  preview(request: ComputerUsePreviewRequest, signal: AbortSignal): Promise<ComputerUseBackendResponse>
  stop(signal: AbortSignal): Promise<ComputerUseBackendResponse>
  status(signal: AbortSignal): Promise<ComputerUseBackendResponse>
}

type FetchLike = typeof fetch

const exactKeys = (value: Record<string, unknown>, expected: readonly string[]): boolean => {
  const actual = Object.keys(value).sort()
  const wanted = [...expected].sort()
  return actual.length === wanted.length && actual.every((key, index) => key === wanted[index])
}

const isInteger = (value: unknown, minimum: number, maximum: number): value is number =>
  Number.isInteger(value) && Number(value) >= minimum && Number(value) <= maximum

const parseAction = (value: unknown): ComputerUseAction | null => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const action = value as Record<string, unknown>
  switch (action['type']) {
    case 'move':
      return exactKeys(action, ['type', 'x', 'y'])
        && isInteger(action['x'], 0, 100_000)
        && isInteger(action['y'], 0, 100_000)
        ? { type: 'move', x: action['x'], y: action['y'] }
        : null
    case 'click':
      return exactKeys(action, ['type', 'button', 'count'])
        && ['left', 'middle', 'right'].includes(String(action['button']))
        && isInteger(action['count'], 1, 3)
        ? { type: 'click', button: action['button'] as 'left' | 'middle' | 'right', count: action['count'] }
        : null
    case 'key_press': {
      if (!exactKeys(action, ['type', 'keys']) || !Array.isArray(action['keys']) || action['keys'].length < 1 || action['keys'].length > 4) return null
      const keys = action['keys'].map((key) => typeof key === 'string' ? key.toLowerCase() : '')
      return keys.every((key) => SUPPORTED_KEYS.has(key)) && new Set(keys).size === keys.length
        ? { type: 'key_press', keys }
        : null
    }
    case 'text_input':
      return exactKeys(action, ['type', 'text'])
        && typeof action['text'] === 'string'
        && action['text'].length >= 1
        && action['text'].length <= MAX_TEXT_LENGTH
        && !action['text'].includes('\0')
        ? { type: 'text_input', text: action['text'] }
        : null
    default:
      return null
  }
}

const parsePreviewRequest = (value: unknown): ComputerUsePreviewRequest | null => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const request = value as Record<string, unknown>
  if (!exactKeys(request, ['actions']) || !Array.isArray(request['actions'])) return null
  if (request['actions'].length < 1 || request['actions'].length > MAX_PREVIEW_ACTIONS) return null
  let serialized: string
  try {
    serialized = JSON.stringify(value)
  } catch {
    return null
  }
  if (Buffer.byteLength(serialized, 'utf8') > MAX_PREVIEW_BYTES) return null
  const actions = request['actions'].map(parseAction)
  return actions.every((action): action is ComputerUseAction => action !== null) ? { actions } : null
}

const cloneStatus = (status: ComputerUseBridgeStatus): ComputerUseBridgeStatus => structuredClone(status)

const boundedText = (value: unknown, fallback: string): string =>
  typeof value === 'string' && value.trim() ? value.trim().slice(0, MAX_BACKEND_MESSAGE_LENGTH) : fallback

const boundedCounter = (value: unknown): number | undefined =>
  isInteger(value, 0, Number.MAX_SAFE_INTEGER) ? value : undefined

const projectBackendResponse = (value: unknown): ComputerUseBackendResponse => {
  const response = value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
  const ok = response['ok'] === true
  const revision = boundedCounter(response['revision'])
  const controllerStopEpoch = boundedCounter(response['controller_stop_epoch'] ?? response['controllerStopEpoch'])
  const interruptedVisual = boundedCounter(response['interrupted_visual'] ?? response['interruptedVisual'])
  const interruptedTools = boundedCounter(response['interrupted_tools'] ?? response['interruptedTools'])
  const interruptedGenerations = boundedCounter(response['interrupted_generations'] ?? response['interruptedGenerations'])
  return {
    ok,
    scope: 'device',
    ...(revision !== undefined ? { revision } : {}),
    ...(typeof response['stopped'] === 'boolean' ? { stopped: response['stopped'] } : {}),
    ...(typeof response['degraded'] === 'boolean' ? { degraded: response['degraded'] } : {}),
    ...(controllerStopEpoch !== undefined ? { controllerStopEpoch } : {}),
    ...(interruptedVisual !== undefined ? { interruptedVisual } : {}),
    ...(interruptedTools !== undefined ? { interruptedTools } : {}),
    ...(interruptedGenerations !== undefined ? { interruptedGenerations } : {}),
    ...(response['idempotent'] === true ? { idempotent: true } : {}),
    ...(!ok ? {
      code: boundedText(response['code'], 'CU_BACKEND_REJECTED'),
      message: boundedText(response['message'], 'computer-use backend rejected the request'),
    } : {}),
  }
}

export class ComputerUseBridge {
  private state: ComputerUseBridgeStatus = {
    scope: 'device',
    revision: 0,
    stopped: false,
    degraded: false,
    stopInFlight: false,
    lastStop: null,
    lastError: null,
  }
  private stopPromise: Promise<ComputerUseBridgeResult<ComputerUseBackendResponse>> | null = null
  private readonly pendingControllers = new Set<AbortController>()
  private disposed = false

  constructor(
    private readonly backend: ComputerUseBackendPort,
    private readonly timeoutMs = 2_000,
  ) {}

  getStatus(): ComputerUseBridgeStatus {
    return cloneStatus(this.state)
  }

  dispose(): void {
    if (this.disposed) return
    this.disposed = true
    for (const controller of this.pendingControllers) controller.abort()
    this.pendingControllers.clear()
    this.state = {
      ...this.state,
      revision: this.state.revision + 1,
      stopped: true,
      degraded: true,
      stopInFlight: false,
      lastError: {
        at: new Date().toISOString(),
        code: 'CU_BRIDGE_DISPOSED',
        message: 'computer-use bridge is disposed',
      },
    }
  }

  async preview(value: unknown): Promise<ComputerUseBridgeResult<ComputerUseBackendResponse>> {
    const request = parsePreviewRequest(value)
    if (request === null) return this.failure('CU_INVALID_PREVIEW', 'preview payload is invalid')
    if (this.state.stopped) return this.failure('CU_EMERGENCY_STOPPED', 'computer use is fenced by emergency stop')
    return this.callBackend('preview', (signal) => this.backend.preview(request, signal))
  }

  stop(source: 'ipc' | 'shortcut' | 'host' = 'ipc'): Promise<ComputerUseBridgeResult<ComputerUseBackendResponse>> {
    if (this.stopPromise !== null) return this.stopPromise
    this.state = {
      ...this.state,
      revision: this.state.revision + 1,
      stopped: true,
      stopInFlight: true,
      lastStop: { at: new Date().toISOString(), source },
      lastError: null,
    }
    this.stopPromise = (async () => {
      const result = await this.callBackend('stop', (signal) => this.backend.stop(signal))
      if (result.ok) {
        this.state.lastStop = {
          ...this.state.lastStop!,
          ...(typeof result.data.revision === 'number' ? { backendRevision: result.data.revision } : {}),
        }
      }
      this.state.stopInFlight = false
      return { ...result, status: this.getStatus() }
    })().finally(() => {
      this.stopPromise = null
    })
    return this.stopPromise
  }

  async refreshStatus(): Promise<ComputerUseBridgeResult<ComputerUseBackendResponse>> {
    const result = await this.callBackend('status', (signal) => this.backend.status(signal))
    if (result.ok) {
      if (typeof result.data.revision === 'number') this.state.revision = Math.max(this.state.revision, result.data.revision)
      if (typeof result.data['stopped'] === 'boolean') this.state.stopped ||= result.data['stopped']
      this.state.degraded = false
      this.state.lastError = null
      return { ...result, status: this.getStatus() }
    }
    return result
  }

  private async callBackend(
    operation: string,
    invoke: (signal: AbortSignal) => Promise<ComputerUseBackendResponse>,
  ): Promise<ComputerUseBridgeResult<ComputerUseBackendResponse>> {
    const controller = new AbortController()
    if (this.disposed) return this.failure('CU_BRIDGE_DISPOSED', 'computer-use bridge is disposed')
    this.pendingControllers.add(controller)
    let timedOut = false
    const timeout = setTimeout(() => {
      timedOut = true
      controller.abort()
    }, this.timeoutMs)
    const aborted = new Promise<never>((_resolve, reject) => {
      controller.signal.addEventListener('abort', () => reject(new Error('computer-use request aborted')), { once: true })
    })
    try {
      const response = projectBackendResponse(await Promise.race([
        Promise.resolve().then(() => invoke(controller.signal)),
        aborted,
      ]))
      if (!response.ok) return this.failure(response.code ?? 'CU_BACKEND_REJECTED', response.message ?? `${operation} rejected`)
      return { ok: true, data: response, status: this.getStatus() }
    } catch (_error) {
      return this.failure(
        timedOut ? 'CU_BACKEND_TIMEOUT' : this.disposed ? 'CU_BRIDGE_DISPOSED' : 'CU_BACKEND_UNAVAILABLE',
        timedOut ? `${operation} timed out` : this.disposed ? 'computer-use bridge is disposed' : `${operation} backend unavailable`,
      )
    } finally {
      clearTimeout(timeout)
      this.pendingControllers.delete(controller)
    }
  }

  private failure(code: string, message: string): ComputerUseBridgeResult<ComputerUseBackendResponse> {
    this.state.degraded = true
    this.state.lastError = { at: new Date().toISOString(), code, message }
    return { ok: false, code, message, status: this.getStatus() }
  }
}

export const createAuthenticatedComputerUseBackendPort = (
  origin: string,
  backendToken: string,
  fetchImpl: FetchLike = fetch,
): ComputerUseBackendPort => {
  const request = async (path: string, init: RequestInit, signal: AbortSignal): Promise<ComputerUseBackendResponse> => {
    const response = await fetchImpl(new URL(path, origin), {
      ...init,
      signal,
      headers: {
        Authorization: `Bearer ${backendToken}`,
        'Content-Type': 'application/json',
      },
    })
    const body = await response.json().catch(() => ({})) as Record<string, unknown>
    return response.ok ? projectBackendResponse(body) : projectBackendResponse({
      ok: false,
      code: typeof body['code'] === 'string' ? body['code'] : `CU_BACKEND_HTTP_${response.status}`,
      message: typeof body['message'] === 'string' ? body['message'] : 'computer-use backend request failed',
    })
  }
  return {
    preview: (payload, signal) => request('/api/computer-use/preview', { method: 'POST', body: JSON.stringify(payload) }, signal),
    stop: (signal) => request('/api/computer-use/emergency-stop', { method: 'POST', body: '{}' }, signal),
    status: (signal) => request('/api/computer-use/status', { method: 'GET' }, signal),
  }
}
