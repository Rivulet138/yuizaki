import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RealtimeVoiceSession } from './realtime-voice'

type SessionState = Record<string, unknown>

const stateOf = (session: RealtimeVoiceSession): SessionState =>
  session as unknown as SessionState

const callServerEvent = (session: RealtimeVoiceSession, event: unknown): void => {
  const handler = stateOf(session).handleServerEvent as ((raw: unknown) => void) | undefined
  if (!handler) throw new Error('Realtime voice test handler is unavailable')
  handler.call(session, event)
}

const configureConnectedContinuousSession = (): RealtimeVoiceSession => {
  const session = new RealtimeVoiceSession()
  const state = stateOf(session)
  state.voiceMode = 'continuous'
  state.workspaceId = 'workspace-a'
  state.sessionId = 'session-a'
  state.connectedAt = Date.now()
  state.responseActive = true
  state.dataChannel = {
    readyState: 'open',
    send: vi.fn(),
    close: vi.fn(),
  }
  state.peer = {
    connectionState: 'connected',
    close: vi.fn(),
  }
  return session
}

describe('RealtimeVoiceSession turn-taking regressions', () => {
  const originalWindow = (globalThis as unknown as { window?: unknown }).window

  beforeEach(() => {
    vi.useFakeTimers()
    const timerWindow = {
      setTimeout: globalThis.setTimeout.bind(globalThis),
      clearTimeout: globalThis.clearTimeout.bind(globalThis),
    }
    Object.defineProperty(globalThis, 'window', {
      configurable: true,
      value: timerWindow,
    })
  })

  afterEach(() => {
    vi.useRealTimers()
    Object.defineProperty(globalThis, 'window', {
      configurable: true,
      value: originalWindow,
    })
  })

  it('does not interrupt output for a barge-in candidate shorter than 160ms', () => {
    const session = configureConnectedContinuousSession()
    const cancelled = vi.fn()
    const acknowledged = vi.fn()
    const speechStarted = vi.fn()
    session.on('provider-cancel', cancelled)
    session.on('interrupt-ack', acknowledged)
    session.on('speech-start', speechStarted)

    callServerEvent(session, { type: 'input_audio_buffer.speech_started' })
    vi.advanceTimersByTime(159)
    callServerEvent(session, { type: 'input_audio_buffer.speech_stopped' })
    vi.runOnlyPendingTimers()

    expect(cancelled).not.toHaveBeenCalled()
    expect(acknowledged).not.toHaveBeenCalled()
    expect(speechStarted).toHaveBeenCalledWith(expect.objectContaining({
      workspaceId: 'workspace-a',
      sessionId: 'session-a',
      interruptionEpoch: 0,
    }))
    expect(stateOf(session).responseActive).toBe(true)
  })

  it('interrupts sustained barge-in and reaches an acknowledgement state', () => {
    const session = configureConnectedContinuousSession()
    const cancelled = vi.fn()
    const stopped = vi.fn()
    const acknowledged = vi.fn()
    session.on('provider-cancel', cancelled)
    session.on('playback-stop', stopped)
    session.on('interrupt-ack', acknowledged)

    callServerEvent(session, { type: 'input_audio_buffer.speech_started' })
    vi.advanceTimersByTime(161)

    expect(cancelled).toHaveBeenCalledTimes(1)
    expect(stopped).toHaveBeenCalledTimes(1)
    // The confirmation callback starts the replacement continuous turn after
    // requesting cancellation, so the observable settled state is recording.
    expect(stateOf(session).status).toBe('recording')
    vi.advanceTimersByTime(250)

    expect(acknowledged).toHaveBeenCalledTimes(1)
    expect(stateOf(session).status).toBe('recording')
  })

  it('does not accept transcript deltas from a retired response', () => {
    const session = new RealtimeVoiceSession()
    const state = stateOf(session)
    state.workspaceId = 'workspace-a'
    state.sessionId = 'session-a'
    state.currentResponseId = 'response-current'
    state.assistantDeltaText = ''
    const deltas: string[] = []
    session.on('assistant-delta', ({ delta }) => deltas.push(delta))

    callServerEvent(session, {
      type: 'response.output_audio_transcript.delta',
      response_id: 'response-retired',
      delta: 'late text',
    })

    expect(deltas).toEqual([])
    expect(state.assistantDeltaText).toBe('')
  })

  it('waits for a late assistant transcript within the finalization grace window', () => {
    const session = new RealtimeVoiceSession()
    const state = stateOf(session)
    state.workspaceId = 'workspace-a'
    state.sessionId = 'session-a'
    state.currentInputItemId = 'item-current'
    state.currentResponseId = 'response-current'
    state.inputTranscript = 'hello'
    state.responseActive = true
    const completed = vi.fn()
    session.on('turn-complete', completed)

    callServerEvent(session, {
      type: 'response.done',
      response_id: 'response-current',
      response: { status: 'completed', output: [] },
    })
    vi.advanceTimersByTime(599)
    expect(completed).not.toHaveBeenCalled()

    callServerEvent(session, {
      type: 'response.output_audio_transcript.done',
      response_id: 'response-current',
      transcript: 'world',
    })

    expect(completed).toHaveBeenCalledTimes(1)
    expect(completed.mock.calls[0]?.[0]).toMatchObject({
      userText: 'hello',
      assistantText: 'world',
    })
  })

  it('settles an empty commit without producing a turn', () => {
    const session = new RealtimeVoiceSession()
    const state = stateOf(session)
    state.currentGenerationId = 'generation-current'
    state.currentTurnId = 'turn-current'
    state.currentRequestId = 'request-current'
    state.currentInterruptionEpoch = 0
    state.speechEndedAt = performance.now() - 10
    state.pendingInputCommits = [{
      commitEventId: 'commit-current',
      generationId: 'generation-current',
      turnId: 'turn-current',
      requestId: 'request-current',
      interruptionEpoch: 0,
    }]
    const emptyInput = vi.fn()
    const completed = vi.fn()
    session.on('empty-input', emptyInput)
    session.on('turn-complete', completed)

    callServerEvent(session, {
      type: 'error',
      error: {
        code: 'input_audio_buffer_commit_empty',
        event_id: 'commit-current',
      },
    })

    expect(emptyInput).toHaveBeenCalledTimes(1)
    expect(completed).not.toHaveBeenCalled()
    expect(state.pendingInputCommits).toEqual([])
  })
})
