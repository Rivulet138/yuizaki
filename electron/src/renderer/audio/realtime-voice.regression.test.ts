import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RealtimeVoiceSession } from './realtime-voice'
import { FINALIZATION_GRACE_MS } from './realtime-voice.test-fixtures'

type SessionState = Record<string, unknown>

const stateOf = (session: RealtimeVoiceSession): SessionState =>
  session as unknown as SessionState

const callServerEvent = (session: RealtimeVoiceSession, event: unknown): void => {
  const handler = stateOf(session).handleServerEvent as ((raw: unknown) => void) | undefined
  if (!handler) throw new Error('Realtime voice test handler is unavailable')
  handler.call(session, event)
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
    vi.advanceTimersByTime(FINALIZATION_GRACE_MS - 1)
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

})
