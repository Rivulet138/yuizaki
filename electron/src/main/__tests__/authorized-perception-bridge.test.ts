import { describe, expect, it, vi } from 'vitest'
import { AuthorizedPerceptionBridge, type PerceptionAuthorization } from '../authorized-perception-bridge'

const authorization = (capability: PerceptionAuthorization['capability']): PerceptionAuthorization => ({
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
})

describe('AuthorizedPerceptionBridge', () => {
  it('uses host-issued sessions once and rejects cross-capability replay', async () => {
    const readClipboard = vi.fn(async () => 'hello')
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

  it('requires permission and explicit target selection before issuing', () => {
    const bridge = new AuthorizedPerceptionBridge({})
    expect(() => bridge.issue({ ...authorization('clipboard'), permissionGranted: false as true })).toThrow()
    expect(() => bridge.issue(authorization('target_window'))).not.toThrow()
    expect(() => bridge.issue({ ...authorization('target_window'), selection: undefined })).toThrow(
      'target window requires explicit source selection',
    )
  })

  it('redacts clipboard secrets and labels evidence as untrusted', async () => {
    const bridge = new AuthorizedPerceptionBridge({
      readClipboard: async () => 'Authorization: Bearer abcdefghijklmnop password=hunter2',
    })
    const result = await bridge.collectClipboard(bridge.issue(authorization('clipboard')))
    expect(result).toMatchObject({
      ok: true,
      evidence: {
        redacted: true,
        payload: { text: expect.not.stringContaining('hunter2') },
        provenance: { trust: 'untrusted', authority: 'evidence' },
      },
    })
  })

  it('fails closed when a provider is unavailable or an authorization expires', async () => {
    let now = 1_000
    const bridge = new AuthorizedPerceptionBridge({}, () => now)
    const unavailable = bridge.issue(authorization('active_application'))
    await expect(bridge.collectActiveApplication(unavailable)).resolves.toMatchObject({
      ok: false,
      code: 'PERCEPTION_PROVIDER_UNAVAILABLE',
    })

    const expired = bridge.issue({ ...authorization('clipboard'), ttlMs: 1_000 })
    now += 1_001
    await expect(bridge.collectClipboard(expired)).resolves.toMatchObject({
      ok: false,
      code: 'PERCEPTION_SESSION_EXPIRED',
    })
  })

  it('cancels sessions fenced by a newer interruption epoch', async () => {
    const readClipboard = vi.fn(async () => 'should not run')
    const bridge = new AuthorizedPerceptionBridge({ readClipboard })
    const session = bridge.issue(authorization('clipboard'))
    bridge.interrupt(4)

    await expect(bridge.collectClipboard(session)).resolves.toMatchObject({
      ok: false,
      code: 'PERCEPTION_SESSION_INVALID',
    })
    expect(readClipboard).not.toHaveBeenCalled()
  })
})
