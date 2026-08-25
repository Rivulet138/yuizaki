import { describe, expect, it, vi } from 'vitest'

import { AuthorizedPerceptionBridge, type PerceptionAuthorization } from '../authorized-perception-bridge'
import { stopComputerUseWithPerceptionFence } from '../perception-stop-coordinator'

const authorization = (interruptionEpoch: number): PerceptionAuthorization => ({
  capability: 'clipboard',
  permissionGranted: true,
  scope: {
    workspaceId: 'workspace-1',
    sessionId: 'session-1',
    turnId: `turn-${interruptionEpoch}`,
    requestId: `request-${interruptionEpoch}`,
    generationId: `generation-${interruptionEpoch}`,
    interruptionEpoch,
  },
})

describe('perception emergency-stop coordinator', () => {
  it('persists the backend interruption revision as the minimum authorized epoch', () => {
    const bridge = new AuthorizedPerceptionBridge({ readClipboard: async () => 'fresh' })

    bridge.interrupt(4)

    expect(() => bridge.issue(authorization(3))).toThrow(/stale perception interruption epoch/)
    expect(() => bridge.issue(authorization(4))).not.toThrow()
  })

  it('fails closed during stop and opens only at the real backend revision', async () => {
    let resolveStop!: (value: { ok: true; data: { revision: number } }) => void
    const stop = vi.fn(() => new Promise<{ ok: true; data: { revision: number } }>((resolve) => {
      resolveStop = resolve
    }))
    const bridge = new AuthorizedPerceptionBridge({ readClipboard: async () => 'fresh' })

    const stopping = stopComputerUseWithPerceptionFence({ stop }, bridge, 'ipc')
    expect(() => bridge.issue(authorization(999))).toThrow(/fenced by emergency stop/)

    resolveStop({ ok: true, data: { revision: 7 } })
    await expect(stopping).resolves.toMatchObject({ ok: true, data: { revision: 7 } })
    expect(() => bridge.issue(authorization(6))).toThrow(/stale perception interruption epoch/)
    expect(() => bridge.issue(authorization(7))).not.toThrow()
  })

  it('cancels old work and rejects its late result after the revision advances', async () => {
    let finishOld!: (value: string) => void
    const oldProvider = new Promise<string>((resolve) => { finishOld = resolve })
    let calls = 0
    const bridge = new AuthorizedPerceptionBridge({
      readClipboard: async () => (++calls === 1 ? oldProvider : 'fresh evidence'),
    })
    const oldCollection = bridge.collectClipboard(bridge.issue(authorization(3)))
    const computerUse = {
      stop: vi.fn(async () => ({ ok: true as const, data: { revision: 4 } })),
    }

    await stopComputerUseWithPerceptionFence(computerUse, bridge, 'shortcut')
    await expect(oldCollection).resolves.toMatchObject({ ok: false, code: 'PERCEPTION_CANCELLED' })
    const freshCollection = bridge.collectClipboard(bridge.issue(authorization(4)))
    finishOld('late stale evidence')

    await expect(freshCollection).resolves.toMatchObject({
      ok: true,
      evidence: { payload: { text: 'fresh evidence' } },
    })
  })

  it('keeps the fence closed when stop does not return a valid revision', async () => {
    const bridge = new AuthorizedPerceptionBridge({ readClipboard: async () => 'must not run' })
    const computerUse = {
      stop: vi.fn(async () => ({ ok: false as const, code: 'CU_STOP_FAILED', message: 'failed' })),
    }

    await stopComputerUseWithPerceptionFence(computerUse, bridge, 'host')

    expect(() => bridge.issue(authorization(100))).toThrow(/fenced by emergency stop/)
  })
})
