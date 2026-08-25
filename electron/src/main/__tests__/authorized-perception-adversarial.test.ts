import { describe, expect, it, vi } from 'vitest'
import {
  AuthorizedPerceptionBridge,
  type PerceptionAuthorization,
} from '../authorized-perception-bridge'

const authorization = (
  capability: PerceptionAuthorization['capability'],
  overrides: Partial<PerceptionAuthorization> = {},
): PerceptionAuthorization => ({
  capability,
  permissionGranted: true,
  scope: {
    workspaceId: 'workspace-1',
    sessionId: 'session-1',
    turnId: 'turn-1',
    requestId: 'request-1',
    generationId: 'generation-1',
    interruptionEpoch: 3,
  },
  ...(capability === 'target_window' ? { selection: { sourceId: 'window:1' } } : {}),
  ...overrides,
})

describe('AuthorizedPerceptionBridge adversarial contract', () => {
  it('consumes a session after the first collection attempt regardless of capability', async () => {
    const readClipboard = vi.fn(async () => 'must not run')
    const bridge = new AuthorizedPerceptionBridge({ readClipboard })
    const session = bridge.issue(authorization('clipboard'))

    await expect(bridge.collectScreenshot(session)).resolves.toMatchObject({
      ok: false,
      code: 'PERCEPTION_SESSION_INVALID',
    })
    await expect(bridge.collectClipboard(session)).resolves.toMatchObject({
      ok: false,
      code: 'PERCEPTION_SESSION_INVALID',
    })
    expect(readClipboard).not.toHaveBeenCalled()
  })

  it('rejects evidence when authorization expires while the provider is running', async () => {
    let now = 1_000
    let finishCapture: ((value: string) => void) | undefined
    const clipboardResult = new Promise<string>((resolve) => {
      finishCapture = resolve
    })
    const bridge = new AuthorizedPerceptionBridge(
      { readClipboard: async () => clipboardResult },
      () => now,
    )
    const collection = bridge.collectClipboard(bridge.issue({
      ...authorization('clipboard'),
      ttlMs: 1_000,
    }))

    now = 2_001
    finishCapture?.('late evidence')

    await expect(collection).resolves.toMatchObject({
      ok: false,
      code: 'PERCEPTION_SESSION_EXPIRED',
    })
  })

  it('interrupts a blocked provider even when it ignores AbortSignal', async () => {
    let finishCapture: ((value: string) => void) | undefined
    const clipboardResult = new Promise<string>((resolve) => {
      finishCapture = resolve
    })
    const bridge = new AuthorizedPerceptionBridge({
      readClipboard: async () => clipboardResult,
    })
    const collection = bridge.collectClipboard(bridge.issue(authorization('clipboard')))

    bridge.interrupt(4)
    const outcome = await Promise.race([
      collection,
      new Promise<'timeout'>((resolve) => setTimeout(() => resolve('timeout'), 25)),
    ])
    finishCapture?.('late evidence')

    expect(outcome).not.toBe('timeout')
    expect(outcome).toMatchObject({ ok: false, code: 'PERCEPTION_CANCELLED' })
  })

  it('does not let a late pre-interruption result contaminate a new session', async () => {
    let finishOld: ((value: string) => void) | undefined
    let calls = 0
    const oldResult = new Promise<string>((resolve) => { finishOld = resolve })
    const bridge = new AuthorizedPerceptionBridge({
      readClipboard: async () => (++calls === 1 ? oldResult : 'fresh evidence'),
    })
    const oldCollection = bridge.collectClipboard(bridge.issue(authorization('clipboard')))

    bridge.interrupt(4)
    await expect(oldCollection).resolves.toMatchObject({ ok: false, code: 'PERCEPTION_CANCELLED' })
    const newAuthorization = authorization('clipboard', {
      scope: { ...authorization('clipboard').scope, interruptionEpoch: 4 },
    })
    const fresh = await bridge.collectClipboard(bridge.issue(newAuthorization))
    finishOld?.('late stale evidence')

    expect(fresh).toMatchObject({ ok: true, evidence: { payload: { text: 'fresh evidence' } } })
  })

  it('does not invoke target selection when the external signal is already aborted', async () => {
    const selectTargetWindow = vi.fn(async () => ({ sourceId: 'window:late' }))
    const bridge = new AuthorizedPerceptionBridge({ selectTargetWindow })
    const controller = new AbortController()
    controller.abort()

    await expect(
      bridge.issueAuthorized(authorization('target_window', { selection: undefined }), controller.signal),
    ).rejects.toThrow(/cancelled/)
    expect(selectTargetWindow).not.toHaveBeenCalled()
  })

  it('does not issue or invoke any provider for an already-aborted request', async () => {
    const readClipboard = vi.fn(async () => 'must not run')
    const bridge = new AuthorizedPerceptionBridge({ readClipboard })
    const controller = new AbortController()
    controller.abort()

    await expect(
      bridge.issueAuthorized(authorization('clipboard'), controller.signal),
    ).rejects.toThrow(/cancelled/)
    expect(readClipboard).not.toHaveBeenCalled()

    const session = bridge.issue(authorization('clipboard'))
    await expect(bridge.collectHostEvidence(session, 'clipboard', controller.signal)).resolves.toMatchObject({
      ok: false,
      code: 'PERCEPTION_CANCELLED',
    })
    expect(readClipboard).not.toHaveBeenCalled()
  })

  it('returns the payload-too-large code for an oversized screenshot before base64', async () => {
    const bridge = new AuthorizedPerceptionBridge({
      captureScreenshot: async () => ({ data: Buffer.alloc(4 * 1024 * 1024 + 1) }),
    })

    await expect(
      bridge.collectScreenshot(bridge.issue(authorization('screenshot'))),
    ).resolves.toMatchObject({
      ok: false,
      code: 'PERCEPTION_PAYLOAD_TOO_LARGE',
    })
  })

  it('marks raw screenshot projection as not redacted', async () => {
    const bridge = new AuthorizedPerceptionBridge({
      captureScreenshot: async () => ({ data: Buffer.from('image') }),
    })

    await expect(
      bridge.collectScreenshot(bridge.issue(authorization('screenshot'))),
    ).resolves.toMatchObject({ ok: true, evidence: { redacted: false } })
  })

  it('does not recapture the desktop for OCR without authorized screenshot evidence', async () => {
    const captureScreenshot = vi.fn(async () => ({ data: Buffer.from('unexpected') }))
    const bridge = new AuthorizedPerceptionBridge({
      captureScreenshot,
    })

    await expect(
      bridge.collectOcr(bridge.issue(authorization('ocr'))),
    ).resolves.toMatchObject({
      ok: false,
      code: 'PERCEPTION_PROVIDER_UNAVAILABLE',
    })
    expect(captureScreenshot).not.toHaveBeenCalled()
  })

  it('projects no backend scope or host authorization into renderer evidence', async () => {
    const bridge = new AuthorizedPerceptionBridge({ readClipboard: async () => 'hello' })

    const result = await bridge.collectClipboard(bridge.issue(authorization('clipboard')))
    const serialized = JSON.stringify(result)

    expect(serialized).not.toContain('workspace-1')
    expect(serialized).not.toContain('session-1')
    expect(serialized).not.toContain('turn-1')
    expect(serialized).not.toContain('request-1')
    expect(serialized).not.toContain('generation-1')
    expect(serialized).not.toContain('permissionGranted')
  })

  it('returns the complete immutable scope only through the host evidence path', async () => {
    const bridge = new AuthorizedPerceptionBridge({ readClipboard: async () => 'hello' })
    const result = await bridge.collectHostEvidence(
      bridge.issue(authorization('clipboard')),
      'clipboard',
    )

    expect(result).toMatchObject({
      ok: true,
      evidence: {
        provider: 'electron-clipboard',
        capability: 'clipboard',
        workspace_id: 'workspace-1',
        session_id: 'session-1',
        turn_id: 'turn-1',
        request_id: 'request-1',
        generation_id: 'generation-1',
        interruption_epoch: 3,
        provenance: {
          trust: 'untrusted',
          authority: 'evidence',
          capture_source: 'electron_main',
        },
      },
    })
  })
})
