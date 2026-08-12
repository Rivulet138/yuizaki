import { describe, expect, it, vi } from 'vitest'
import type { RealtimeVoiceEventMap } from '../audio/realtime-voice'
import {
  acceptsRealtimeVoiceEnvelope,
  matchesRealtimeVoiceScope,
  matchesRealtimeVoiceTurnScope,
  RealtimeVoiceEventBridge,
  type RealtimeVoiceEventSource,
} from '../app/runtime/realtimeVoiceEventBridge'

describe('RealtimeVoiceEventBridge', () => {
  it('rejects results from another workspace, session, or interruption epoch', () => {
    const current = { workspaceId: 'workspace-a', sessionId: 'session-a', interruptionEpoch: 2 }
    expect(matchesRealtimeVoiceScope(current, current)).toBe(true)
    expect(matchesRealtimeVoiceScope({ ...current, workspaceId: 'workspace-b' }, current)).toBe(false)
    expect(matchesRealtimeVoiceScope({ ...current, sessionId: 'session-b' }, current)).toBe(false)
    expect(matchesRealtimeVoiceScope({ ...current, interruptionEpoch: 1 }, current)).toBe(false)
    expect(matchesRealtimeVoiceScope({ ...current, turnId: 'old-turn' }, { ...current, turnId: 'current-turn' })).toBe(false)
    expect(matchesRealtimeVoiceScope({ ...current, turnId: 'current-turn' }, { ...current, turnId: 'current-turn' })).toBe(true)
    expect(matchesRealtimeVoiceScope(current, { ...current, turnId: 'current-turn' })).toBe(true)
  })

  it('rejects delayed envelope sequences and generations while accepting legacy events', () => {
    const current = { workspaceId: 'w', sessionId: 's', interruptionEpoch: 2, generationId: 'g2' }
    expect(acceptsRealtimeVoiceEnvelope(current, current, 3)).toBe(true)
    expect(acceptsRealtimeVoiceEnvelope({ ...current, sequence: 3 }, current, 3)).toBe(false)
    expect(acceptsRealtimeVoiceEnvelope({ ...current, generationId: 'g1', sequence: 4 }, current, 0)).toBe(false)
    expect(acceptsRealtimeVoiceEnvelope({ workspaceId: 'w', sessionId: 's', interruptionEpoch: 2 }, current, 99)).toBe(true)
  })

  it('requires complete identity for versioned turn completion', () => {
    const current = { workspaceId: 'w', sessionId: 's', interruptionEpoch: 2, turnId: 't2', generationId: 'g2', requestId: 'r2' }
    expect(matchesRealtimeVoiceTurnScope(current, current)).toBe(true)
    expect(matchesRealtimeVoiceTurnScope({ ...current, generationId: 'g1' }, current)).toBe(false)
    expect(matchesRealtimeVoiceTurnScope({ ...current, requestId: 'r1' }, current)).toBe(false)
    expect(matchesRealtimeVoiceTurnScope({ ...current, turnId: undefined }, current)).toBe(false)
  })

  it('tracks typed subscriptions and disposes each one exactly once', () => {
    const disposers = new Map<keyof RealtimeVoiceEventMap, () => void>()
    const source: RealtimeVoiceEventSource = {
      on: (event, _listener) => {
        const dispose = vi.fn()
        disposers.set(event, dispose)
        return dispose
      },
    }
    const bridge = new RealtimeVoiceEventBridge(source)

    bridge.listen('status', () => undefined)
    bridge.listen('playback-end', () => undefined)
    bridge.detach()
    bridge.detach()

    expect(disposers.get('status')).toHaveBeenCalledTimes(1)
    expect(disposers.get('playback-end')).toHaveBeenCalledTimes(1)
  })

  it('can be reused after detaching the previous subscriptions', () => {
    const firstDispose = vi.fn()
    const secondDispose = vi.fn()
    let bindCount = 0
    const source: RealtimeVoiceEventSource = {
      on: () => {
        bindCount += 1
        return bindCount === 1 ? firstDispose : secondDispose
      },
    }
    const bridge = new RealtimeVoiceEventBridge(source)

    bridge.listen('status', () => undefined)
    bridge.detach()
    bridge.listen('status', () => undefined)
    bridge.detach()

    expect(firstDispose).toHaveBeenCalledTimes(1)
    expect(secondDispose).toHaveBeenCalledTimes(1)
  })
})
