import { randomBytes, randomUUID } from 'node:crypto'
import type { PerceptionBridgeResult, PerceptionCapability } from '../shared/authorized-perception'

const MAX_TEXT_BYTES = 128 * 1024
const MAX_IMAGE_BYTES = 4 * 1024 * 1024
const SECRET_PATTERNS = [
  /\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}/gi,
  /\b(?:api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*[^\s,;]+/gi,
  /-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----/g,
]
const SENSITIVE_APPLICATION_PATTERNS = [
  /password|1password|lastpass|keychain/i,
  /bank|finance|payment|支付宝|微信支付/i,
  /medical|health|医院|病历/i,
]

export interface PerceptionScope {
  workspaceId: string
  sessionId: string
  turnId: string
  requestId: string
  generationId: string
  interruptionEpoch: number
}

export interface PerceptionAuthorization {
  capability: PerceptionCapability
  scope: PerceptionScope
  permissionGranted: true
  selection?: { sourceId?: string; filePath?: string }
  ttlMs?: number
}

export interface AuthorizedPerceptionDependencies {
  captureScreenshot?: (signal: AbortSignal) => Promise<{ data: Buffer; displayId?: string }>
  captureTargetWindow?: (sourceId: string, signal: AbortSignal) => Promise<{ data: Buffer; title?: string }>
  selectTargetWindow?: (signal: AbortSignal) => Promise<{ sourceId: string } | null>
  readActiveApplication?: (signal: AbortSignal) => Promise<{ name: string; title?: string }>
  isSensitiveApplication?: (application: { name: string; title: string }) => boolean
  selectFile?: (suggestedPath: string | undefined, signal: AbortSignal) => Promise<{ path: string; name: string; text?: string } | null>
  readClipboard?: (signal: AbortSignal) => Promise<string>
}

export interface HostPerceptionEvidence {
  evidence_id: string
  provider: string
  capability: PerceptionCapability
  workspace_id: string
  session_id: string
  turn_id: string
  request_id: string
  generation_id: string
  interruption_epoch: number
  captured_at: number
  expires_at: number
  payload: unknown
  provenance: { trust: 'untrusted'; authority: 'evidence'; capture_source: 'electron_main' }
}

export type HostPerceptionResult =
  | { ok: true; evidence: HostPerceptionEvidence }
  | { ok: false; code: string; message: string }

interface Session extends PerceptionAuthorization {
  id: string
  issuedAt: number
  expiresAt: number
  controller: AbortController
}

const exactText = (value: unknown): string => typeof value === 'string' ? value.trim() : ''

const validScope = (scope: PerceptionScope): boolean => Boolean(
  exactText(scope.workspaceId)
  && exactText(scope.sessionId)
  && exactText(scope.turnId)
  && exactText(scope.requestId)
  && exactText(scope.generationId)
  && Number.isInteger(scope.interruptionEpoch)
  && scope.interruptionEpoch >= 0,
)

const redactText = (value: string): string => SECRET_PATTERNS.reduce(
  (text, pattern) => text.replace(pattern, '[REDACTED]'),
  value,
)

class PerceptionBridgeError extends Error {
  constructor(readonly code: string, message: string) {
    super(message)
  }
}

export class AuthorizedPerceptionBridge {
  private readonly sessions = new Map<string, Session>()
  private readonly inFlight = new Set<Session>()
  private readonly pendingAuthorizations = new Map<AbortController, number>()
  private minimumInterruptionEpoch = 0
  private stopFenceActive = false
  private disposed = false

  constructor(private readonly dependencies: AuthorizedPerceptionDependencies, private readonly now = Date.now) {}

  /** Main-process only. Never expose this authority constructor through preload. */
  issue(authorization: PerceptionAuthorization): string {
    if (this.disposed) throw new Error('perception bridge is disposed')
    if (this.stopFenceActive) throw new Error('perception bridge is fenced by emergency stop')
    if (authorization.permissionGranted !== true || !validScope(authorization.scope)) {
      throw new Error('invalid perception authorization')
    }
    if (authorization.scope.interruptionEpoch < this.minimumInterruptionEpoch) {
      throw new Error('stale perception interruption epoch')
    }
    if (authorization.capability === 'target_window' && !exactText(authorization.selection?.sourceId)) {
      throw new Error('target window requires explicit source selection')
    }
    const issuedAt = this.now()
    const ttlMs = Math.min(15_000, Math.max(1_000, authorization.ttlMs ?? 10_000))
    const id = randomBytes(32).toString('base64url')
    this.sessions.set(id, {
      ...structuredClone(authorization),
      id,
      issuedAt,
      expiresAt: issuedAt + ttlMs,
      controller: new AbortController(),
    })
    return id
  }

  /** Authenticated host route entry; target selection remains main-owned. */
  async issueAuthorized(authorization: PerceptionAuthorization, externalSignal?: AbortSignal): Promise<string> {
    if (externalSignal?.aborted) throw new Error('perception authorization was cancelled')
    if (authorization.capability !== 'target_window') return this.issue(authorization)
    if (authorization.selection !== undefined) throw new Error('target selection cannot be supplied by the caller')
    const select = this.dependencies.selectTargetWindow
    if (!select) throw new Error('target window selection is unavailable')
    const controller = new AbortController()
    const abortFromExternal = () => controller.abort()
    externalSignal?.addEventListener('abort', abortFromExternal, { once: true })
    this.pendingAuthorizations.set(controller, authorization.scope.interruptionEpoch)
    try {
      const aborted = new Promise<never>((_resolve, reject) => {
        controller.signal.addEventListener('abort', () => reject(new Error('target window selection was cancelled')), { once: true })
      })
      const selected = await Promise.race([select(controller.signal), aborted])
      if (!selected || !exactText(selected.sourceId)) throw new Error('target window selection was cancelled')
      return this.issue({ ...authorization, selection: { sourceId: selected.sourceId } })
    } finally {
      externalSignal?.removeEventListener('abort', abortFromExternal)
      this.pendingAuthorizations.delete(controller)
    }
  }

  interrupt(nextEpoch: number): void {
    if (!Number.isSafeInteger(nextEpoch) || nextEpoch < 0) throw new Error('invalid interruption epoch')
    this.minimumInterruptionEpoch = Math.max(this.minimumInterruptionEpoch, nextEpoch)
    this.stopFenceActive = false
    for (const [id, session] of this.sessions) {
      if (session.scope.interruptionEpoch < nextEpoch) {
        session.controller.abort()
        this.sessions.delete(id)
      }
    }
    for (const session of this.inFlight) {
      if (session.scope.interruptionEpoch < nextEpoch) session.controller.abort()
    }
    for (const [controller, epoch] of this.pendingAuthorizations) {
      if (epoch < nextEpoch) controller.abort()
    }
  }

  beginStopFence(): void {
    this.stopFenceActive = true
    for (const session of this.sessions.values()) session.controller.abort()
    for (const session of this.inFlight) session.controller.abort()
    for (const controller of this.pendingAuthorizations.keys()) controller.abort()
    this.sessions.clear()
  }

  dispose(): void {
    if (this.disposed) return
    this.disposed = true
    for (const session of this.sessions.values()) session.controller.abort()
    for (const session of this.inFlight) session.controller.abort()
    for (const controller of this.pendingAuthorizations.keys()) controller.abort()
    this.sessions.clear()
  }

  collectScreenshot(id: unknown): Promise<PerceptionBridgeResult> { return this.collectProjection(id, 'screenshot') }
  collectTargetWindow(id: unknown): Promise<PerceptionBridgeResult> { return this.collectProjection(id, 'target_window') }
  collectActiveApplication(id: unknown): Promise<PerceptionBridgeResult> { return this.collectProjection(id, 'active_application') }
  collectSelectedFile(id: unknown): Promise<PerceptionBridgeResult> { return this.collectProjection(id, 'selected_file') }
  collectClipboard(id: unknown): Promise<PerceptionBridgeResult> { return this.collectProjection(id, 'clipboard') }
  collectOcr(id: unknown): Promise<PerceptionBridgeResult> { return this.collectProjection(id, 'ocr') }

  collectHostEvidence(id: string, capability: PerceptionCapability, signal?: AbortSignal): Promise<HostPerceptionResult> {
    return this.collect(id, capability, signal)
  }

  private async collectProjection(value: unknown, capability: PerceptionCapability): Promise<PerceptionBridgeResult> {
    const result = await this.collect(value, capability)
    if (!result.ok) return result
    const evidence = result.evidence
    return {
      ok: true,
      evidence: {
        evidenceId: evidence.evidence_id,
        capability: evidence.capability,
        capturedAt: evidence.captured_at,
        expiresAt: evidence.expires_at,
        redacted: !['screenshot', 'target_window'].includes(evidence.capability),
        payload: evidence.payload,
        provenance: { trust: 'untrusted', authority: 'evidence' },
      },
    }
  }

  private async collect(value: unknown, capability: PerceptionCapability, externalSignal?: AbortSignal): Promise<HostPerceptionResult> {
    const id = exactText(value)
    const session = this.sessions.get(id)
    if (session) this.sessions.delete(id)
    if (!session || session.capability !== capability) return this.failure('PERCEPTION_SESSION_INVALID', 'perception session is invalid')
    if (this.disposed || session.controller.signal.aborted) return this.failure('PERCEPTION_CANCELLED', 'perception request was cancelled')
    if (this.now() >= session.expiresAt) return this.failure('PERCEPTION_SESSION_EXPIRED', 'perception session expired')
    const abortFromExternal = () => session.controller.abort()
    externalSignal?.addEventListener('abort', abortFromExternal, { once: true })
    if (externalSignal?.aborted) {
      session.controller.abort()
      externalSignal.removeEventListener('abort', abortFromExternal)
      return this.failure('PERCEPTION_CANCELLED', 'perception request was cancelled')
    }
    this.inFlight.add(session)
    const expiryTimer = setTimeout(
      () => session.controller.abort(),
      Math.max(0, session.expiresAt - this.now()),
    )
    try {
      const aborted = new Promise<never>((_resolve, reject) => {
        session.controller.signal.addEventListener(
          'abort',
          () => reject(new PerceptionBridgeError('PERCEPTION_CANCELLED', 'perception request was cancelled')),
          { once: true },
        )
      })
      const payload = await Promise.race([this.invoke(session), aborted])
      if (session.controller.signal.aborted) return this.failure('PERCEPTION_CANCELLED', 'perception request was cancelled')
      if (this.now() >= session.expiresAt) return this.failure('PERCEPTION_SESSION_EXPIRED', 'perception session expired')
      const serialized = Buffer.from(JSON.stringify(payload), 'utf8')
      const limit = ['screenshot', 'target_window', 'ocr'].includes(capability) ? MAX_IMAGE_BYTES : MAX_TEXT_BYTES
      if (serialized.byteLength > limit) return this.failure('PERCEPTION_PAYLOAD_TOO_LARGE', 'perception payload exceeds limit')
      const capturedAt = this.now()
      return {
        ok: true,
        evidence: {
          evidence_id: randomUUID(),
          provider: `electron-${capability}`,
          capability,
          workspace_id: session.scope.workspaceId,
          session_id: session.scope.sessionId,
          turn_id: session.scope.turnId,
          request_id: session.scope.requestId,
          generation_id: session.scope.generationId,
          interruption_epoch: session.scope.interruptionEpoch,
          captured_at: capturedAt / 1_000,
          expires_at: Math.min(session.expiresAt, capturedAt + 10_000) / 1_000,
          payload,
          provenance: { trust: 'untrusted', authority: 'evidence', capture_source: 'electron_main' },
        },
      }
    } catch (error) {
      if (error instanceof PerceptionBridgeError) return this.failure(error.code, error.message)
      return this.failure(
        session.controller.signal.aborted ? 'PERCEPTION_CANCELLED' : 'PERCEPTION_PROVIDER_UNAVAILABLE',
        session.controller.signal.aborted ? 'perception request was cancelled' : 'perception provider unavailable',
      )
    } finally {
      clearTimeout(expiryTimer)
      externalSignal?.removeEventListener('abort', abortFromExternal)
      this.inFlight.delete(session)
    }
  }

  private async invoke(session: Session): Promise<unknown> {
    const signal = session.controller.signal
    switch (session.capability) {
      case 'screenshot': {
        const capture = this.dependencies.captureScreenshot
        if (!capture) throw new Error('unavailable')
        const result = await capture(signal)
        if (result.data.byteLength > MAX_IMAGE_BYTES) throw new PerceptionBridgeError('PERCEPTION_PAYLOAD_TOO_LARGE', 'perception image exceeds limit')
        return { image: result.data.toString('base64'), mimeType: 'image/png', displayId: result.displayId }
      }
      case 'target_window': {
        const capture = this.dependencies.captureTargetWindow
        const sourceId = exactText(session.selection?.sourceId)
        if (!capture || !sourceId) throw new Error('unavailable')
        const result = await capture(sourceId, signal)
        if (result.data.byteLength > MAX_IMAGE_BYTES) throw new PerceptionBridgeError('PERCEPTION_PAYLOAD_TOO_LARGE', 'perception image exceeds limit')
        return { image: result.data.toString('base64'), mimeType: 'image/png', title: redactText(result.title ?? '') }
      }
      case 'active_application': {
        const read = this.dependencies.readActiveApplication
        if (!read) throw new Error('unavailable')
        const result = await read(signal)
        const application = { name: result.name ?? '', title: result.title ?? '' }
        const sensitive = this.dependencies.isSensitiveApplication?.(application)
          ?? SENSITIVE_APPLICATION_PATTERNS.some((pattern) => pattern.test(`${application.name} ${application.title}`))
        if (sensitive) return { name: '[SENSITIVE_APPLICATION]', title: '[REDACTED]' }
        return { name: redactText(application.name), title: redactText(application.title) }
      }
      case 'selected_file': {
        const select = this.dependencies.selectFile
        if (!select) throw new Error('unavailable')
        const result = await select(session.selection?.filePath, signal)
        if (!result) throw new Error('cancelled')
        return { name: redactText(result.name), path: '[USER_SELECTED_FILE]', text: result.text ? redactText(result.text) : undefined }
      }
      case 'clipboard': {
        const read = this.dependencies.readClipboard
        if (!read) throw new Error('unavailable')
        return { text: redactText(await read(signal)) }
      }
      case 'ocr': {
        throw new Error('OCR requires authorized screenshot evidence')
      }
    }
  }

  private failure(code: string, message: string): HostPerceptionResult {
    return { ok: false, code, message }
  }
}
