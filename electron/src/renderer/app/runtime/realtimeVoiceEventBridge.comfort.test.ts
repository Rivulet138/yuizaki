import { describe, expect, it, vi } from 'vitest'
import {
  RealtimeVoiceEventBridge,
  acceptsRealtimeVoiceEnvelope,
  matchesRealtimeVoiceScope,
  matchesRealtimeVoiceTurnScope,
  type RealtimeVoiceEventSource,
} from './realtimeVoiceEventBridge'

describe('RealtimeVoiceEventBridge comfort signals', () => {
  const createSource = () => {
    const listeners = new Map<string, Set<(payload: unknown) => void>>()
    const source: RealtimeVoiceEventSource = {
      on: (event, listener) => {
        const set = listeners.get(event) ?? new Set<(payload: unknown) => void>()
        set.add(listener as (payload: unknown) => void)
        listeners.set(event, set)
        return () => set.delete(listener as (payload: unknown) => void)
      },
    }
    const emit = (event: string, payload: unknown) => {
      listeners.get(event)?.forEach((listener) => listener(payload))
    }
    return { source, emit }
  }

  it('keeps bounded, transcript-free signal aggregates and rejects malformed samples', () => {
    const { source, emit } = createSource()
    const bridge = new RealtimeVoiceEventBridge(source)
    bridge.listen('comfort-signal', () => undefined)

    emit('comfort-signal', { signal: 'hesitation', source: 'local_vad', confidence: 0.8, durationMs: 120 })
    emit('comfort-signal', { signal: 'backchannel', source: 'provider_vad', confidence: 0.6 })
    emit('comfort-signal', { signal: 'not-a-signal', source: 'classifier', confidence: 1 })
    emit('comfort-signal', { signal: 'background_speech', source: 'classifier', confidence: 2 })

    const snapshot = bridge.getDiagnosticSnapshot()
    expect(snapshot.comfortSignals).toEqual({
      sampleCount: 2,
      bySignal: { hesitation: 1, backchannel: 1 },
      bySource: { local_vad: 1, provider_vad: 1 },
      confidenceP50: 0.6,
      confidenceP95: 0.6,
      durationP50Ms: 120,
      durationP95Ms: 120,
    })
    expect(JSON.stringify(snapshot)).not.toContain('transcript')
  })

  it('bounds diagnostic samples and isolates reporter failures', () => {
    const { source, emit } = createSource()
    const reporter = vi.fn(() => {
      throw new Error('persistence unavailable')
    })
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    const bridge = new RealtimeVoiceEventBridge(source, reporter)
    bridge.listen('playback-start', () => undefined)

    for (let index = 0; index < 140; index += 1) emit('playback-start', { elapsedMs: index })

    expect(bridge.getDiagnosticSnapshot().sampleCount).toBe(128)
    expect(reporter).toHaveBeenCalledTimes(140)
    expect(warn).toHaveBeenCalled()
    warn.mockRestore()
  })

  it('records one diagnostic sample when an event has multiple listeners', () => {
    const { source, emit } = createSource()
    const bridge = new RealtimeVoiceEventBridge(source)
    const first = vi.fn()
    const second = vi.fn()
    bridge.listen('playback-start', first)
    bridge.listen('playback-start', second)

    emit('playback-start', { elapsedMs: 42 })

    expect(first).toHaveBeenCalledTimes(1)
    expect(second).toHaveBeenCalledTimes(1)
    expect(bridge.getDiagnosticSnapshot().sampleCount).toBe(1)
  })

  it('captures the run identity at event time', () => {
    const { source, emit } = createSource()
    const reporter = vi.fn()
    const bridge = new RealtimeVoiceEventBridge(source, reporter)
    bridge.listen('playback-start', () => undefined)

    bridge.setDiagnosticRunId('voice-ui-run-a')
    emit('playback-start', {
      elapsedMs: 12,
      workspaceId: 'workspace-a',
      sessionId: 'session-a',
      interruptionEpoch: 1,
    })
    bridge.setDiagnosticRunId('voice-ui-run-b')
    emit('playback-start', {
      elapsedMs: 24,
      workspaceId: 'workspace-b',
      sessionId: 'session-b',
      interruptionEpoch: 2,
    })

    expect(reporter.mock.calls.map(([sample]) => sample.runId)).toEqual([
      'voice-ui-run-a',
      'voice-ui-run-b',
    ])
    expect(reporter.mock.calls.map(([sample]) => sample.scope?.sessionId)).toEqual([
      'session-a',
      'session-b',
    ])
  })

  it('clears local aggregates when the measurement run rotates', () => {
    const { source, emit } = createSource()
    const bridge = new RealtimeVoiceEventBridge(source)
    bridge.listen('playback-start', () => undefined)
    bridge.listen('comfort-signal', () => undefined)

    bridge.setDiagnosticRunId('voice-run-a')
    emit('playback-start', { elapsedMs: 20 })
    emit('comfort-signal', { signal: 'hesitation', source: 'local_vad', confidence: 0.7 })
    expect(bridge.getDiagnosticSnapshot().sampleCount).toBe(1)
    expect(bridge.getDiagnosticSnapshot().comfortSignals.sampleCount).toBe(1)

    bridge.setDiagnosticRunId('voice-run-b')
    expect(bridge.getDiagnosticSnapshot().sampleCount).toBe(0)
    expect(bridge.getDiagnosticSnapshot().comfortSignals.sampleCount).toBe(0)

    emit('playback-start', { elapsedMs: 30 })
    expect(bridge.getDiagnosticSnapshot().sampleCount).toBe(1)
    bridge.setDiagnosticRunId(null)
    expect(bridge.getDiagnosticSnapshot().sampleCount).toBe(0)
  })

  it('stops forwarding and collecting events after detach', () => {
    const { source, emit } = createSource()
    const bridge = new RealtimeVoiceEventBridge(source)
    const listener = vi.fn()
    bridge.listen('comfort-signal', listener)

    emit('comfort-signal', { signal: 'hesitation', source: 'local_vad', confidence: 0.7 })
    bridge.detach()
    emit('comfort-signal', { signal: 'backchannel', source: 'provider_vad', confidence: 0.8 })

    expect(listener).toHaveBeenCalledTimes(1)
    expect(bridge.getDiagnosticSnapshot().comfortSignals.sampleCount).toBe(1)
  })
})

describe('RealtimeVoiceEventBridge scope gates', () => {
  const baseScope = {
    workspaceId: 'workspace-a',
    sessionId: 'session-a',
    interruptionEpoch: 3,
  }

  it('rejects events from another session or interruption epoch', () => {
    expect(matchesRealtimeVoiceScope(baseScope, baseScope)).toBe(true)
    expect(matchesRealtimeVoiceScope({ ...baseScope, sessionId: 'session-b' }, baseScope)).toBe(false)
    expect(matchesRealtimeVoiceScope({ ...baseScope, interruptionEpoch: 4 }, baseScope)).toBe(false)
  })

  it('requires complete identity for versioned turn events', () => {
    const current = { ...baseScope, turnId: 'turn-1', generationId: 'generation-1', requestId: 'request-1' }
    expect(matchesRealtimeVoiceTurnScope(current, current)).toBe(true)
    expect(matchesRealtimeVoiceTurnScope({ ...current, requestId: 'request-2' }, current)).toBe(false)
    expect(matchesRealtimeVoiceTurnScope({ ...current, turnId: undefined }, current)).toBe(false)
  })

  it('accepts legacy events but enforces sequence and generation for versioned envelopes', () => {
    const current = { ...baseScope, generationId: 'generation-1' }
    expect(acceptsRealtimeVoiceEnvelope(baseScope, current, -1)).toBe(true)
    expect(acceptsRealtimeVoiceEnvelope({ ...current, sequence: 4 }, current, 3)).toBe(true)
    expect(acceptsRealtimeVoiceEnvelope({ ...current, sequence: 3 }, current, 3)).toBe(false)
    expect(acceptsRealtimeVoiceEnvelope({ ...current, generationId: 'generation-2' }, current, -1)).toBe(false)
  })
})
