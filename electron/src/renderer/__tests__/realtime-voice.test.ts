import { beforeEach, describe, expect, it, vi } from 'vitest'

const requestJsonMock = vi.fn()

vi.mock('@/api/clients/http-client', () => ({
  API_ORIGIN: 'http://localhost:8001',
  requestJson: requestJsonMock,
}))

class MockDataChannel extends EventTarget {
  readyState: RTCDataChannelState = 'connecting'
  sent: string[] = []

  send(payload: string) {
    this.sent.push(payload)
  }

  close() {
    this.readyState = 'closed'
  }

  open() {
    this.readyState = 'open'
    this.dispatchEvent(new Event('open'))
  }

  serverEvent(payload: Record<string, unknown>) {
    this.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(payload) }))
  }
}

class MockPeerConnection extends EventTarget {
  static latest: MockPeerConnection | null = null
  connectionState: RTCPeerConnectionState = 'new'
  iceGatheringState: RTCIceGatheringState = 'complete'
  localDescription: RTCSessionDescription | null = null
  ontrack: RTCPeerConnection['ontrack'] = null
  onconnectionstatechange: RTCPeerConnection['onconnectionstatechange'] = null
  channel = new MockDataChannel()

  constructor() {
    super()
    MockPeerConnection.latest = this
  }

  addTrack() {
    return {} as RTCRtpSender
  }

  createDataChannel() {
    queueMicrotask(() => this.channel.open())
    return this.channel as unknown as RTCDataChannel
  }

  async createOffer() {
    return { type: 'offer' as RTCSdpType, sdp: 'offer-sdp' }
  }

  async setLocalDescription(description: RTCSessionDescriptionInit) {
    this.localDescription = description as RTCSessionDescription
  }

  async setRemoteDescription() {
    this.connectionState = 'connected'
  }

  close() {
    this.connectionState = 'closed'
  }
}

const audioTrack = {
  enabled: true,
  stop: vi.fn(),
}
const mediaStream = {
  getAudioTracks: () => [audioTrack],
  getTracks: () => [audioTrack],
}

describe('RealtimeVoiceSession', () => {
  beforeEach(() => {
    vi.useRealTimers()
    vi.resetModules()
    vi.clearAllMocks()
    audioTrack.enabled = true
    MockPeerConnection.latest = null
    requestJsonMock.mockResolvedValue({
      client_secret: 'ek_test',
      model: 'gpt-realtime-test',
      voice: 'marin',
      workspace_id: 'default',
      session_id: 'voice',
    })
    vi.stubGlobal('RTCPeerConnection', MockPeerConnection)
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(new Response('answer-sdp', {
      status: 201,
      headers: { 'content-type': 'application/sdp' },
    }))))
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue(mediaStream) },
    })
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
    vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => undefined)
  })

  it('keeps the server key out of the renderer and submits audio on release', async () => {
    const { RealtimeVoiceSession } = await import('@/audio/realtime-voice')
    const session = new RealtimeVoiceSession()
    let now = 1_000
    vi.spyOn(performance, 'now').mockImplementation(() => now)

    await session.startPushToTalk({ workspaceId: 'default', sessionId: 'voice' })
    const peer = MockPeerConnection.latest!
    expect(audioTrack.enabled).toBe(true)
    expect(requestJsonMock).toHaveBeenCalledWith(
      'http://localhost:8001/api/realtime/client-secret',
      expect.objectContaining({ method: 'POST' }),
    )
    expect(fetch).toHaveBeenCalledWith(
      'https://api.openai.com/v1/realtime/calls',
      expect.objectContaining({
        method: 'POST',
        headers: {
          Authorization: 'Bearer ek_test',
          'Content-Type': 'application/sdp',
        },
        body: 'offer-sdp',
      }),
    )

    now = 1_400
    expect(session.stopPushToTalk()).toBe(true)
    expect(audioTrack.enabled).toBe(false)
    const sentTypes = peer.channel.sent.map((payload) => JSON.parse(payload).type)
    expect(sentTypes).toContain('input_audio_buffer.commit')
    expect(sentTypes).toContain('response.create')
    expect(peer.channel.sent.join(' ')).not.toContain('sk-')
    session.close()
  })

  it('reconnects before reusing a session near the provider time limit', async () => {
    const { RealtimeVoiceSession } = await import('@/audio/realtime-voice')
    const session = new RealtimeVoiceSession()
    let wallClock = 10_000
    vi.spyOn(Date, 'now').mockImplementation(() => wallClock)
    vi.spyOn(performance, 'now').mockReturnValue(1_000)

    await session.connect({ workspaceId: 'default', sessionId: 'voice' })
    expect(requestJsonMock).toHaveBeenCalledTimes(1)

    wallClock += 56 * 60 * 1_000
    await session.connect({ workspaceId: 'default', sessionId: 'voice' })
    expect(requestJsonMock).toHaveBeenCalledTimes(2)
    session.close()
  })

  it('keeps a session alive when a transient disconnect recovers within the grace period', async () => {
    const { RealtimeVoiceSession } = await import('@/audio/realtime-voice')
    const session = new RealtimeVoiceSession()
    const errors: Array<{ message: string; fatal: boolean }> = []
    session.on('error', error => errors.push(error))

    await session.connect({ workspaceId: 'default', sessionId: 'voice' })
    const peer = MockPeerConnection.latest!
    vi.useFakeTimers()
    try {
      peer.connectionState = 'disconnected'
      peer.onconnectionstatechange?.(new Event('connectionstatechange'))
      vi.advanceTimersByTime(2_500)
      peer.connectionState = 'connected'
      peer.onconnectionstatechange?.(new Event('connectionstatechange'))
      vi.advanceTimersByTime(5_000)

      expect(errors).toEqual([])
      expect(session.getStatus()).toBe('ready')
      expect(session.isConnected()).toBe(true)
    } finally {
      session.close()
      vi.useRealTimers()
    }
  })

  it('closes a session when a disconnect persists beyond the grace period', async () => {
    const { RealtimeVoiceSession } = await import('@/audio/realtime-voice')
    const session = new RealtimeVoiceSession()
    const errors: Array<{ message: string; fatal: boolean }> = []
    session.on('error', error => errors.push(error))

    await session.connect({ workspaceId: 'default', sessionId: 'voice' })
    const peer = MockPeerConnection.latest!
    vi.useFakeTimers()
    try {
      peer.connectionState = 'disconnected'
      peer.onconnectionstatechange?.(new Event('connectionstatechange'))
      vi.advanceTimersByTime(5_000)

      expect(errors).toEqual([{ message: 'Realtime voice connection was lost', fatal: true }])
      expect(session.getStatus()).toBe('error')
      expect(session.isConnected()).toBe(false)
      expect(audioTrack.stop).toHaveBeenCalled()
    } finally {
      session.close()
      vi.useRealTimers()
    }
  })

  it('streams transcripts, completes an ordered turn, and acknowledges interruption', async () => {
    const { RealtimeVoiceSession } = await import('@/audio/realtime-voice')
    const session = new RealtimeVoiceSession()
    const turns: Array<{ userText: string; assistantText: string }> = []
    const assistantDeltas: string[] = []
    const interruptAcks: number[] = []
    const transcriptStable: number[] = []
    let now = 2_000
    vi.spyOn(performance, 'now').mockImplementation(() => now)
    session.on('turn-complete', (turn) => turns.push(turn))
    session.on('assistant-delta', ({ text }) => assistantDeltas.push(text))
    session.on('interrupt-ack', ({ elapsedMs }) => interruptAcks.push(elapsedMs))
    session.on('transcript-stable', ({ elapsedMs }) => transcriptStable.push(elapsedMs))

    await session.startPushToTalk({ workspaceId: 'default', sessionId: 'voice' })
    now = 2_300
    session.stopPushToTalk()
    const channel = MockPeerConnection.latest!.channel
    channel.serverEvent({
      type: 'conversation.item.input_audio_transcription.completed',
      transcript: '你好',
    })
    channel.serverEvent({ type: 'response.output_audio_transcript.delta', delta: '我' })
    channel.serverEvent({ type: 'response.output_audio_transcript.delta', delta: '在。' })
    channel.serverEvent({
      type: 'response.output_audio_transcript.done',
      transcript: '我在。',
    })
    channel.serverEvent({ type: 'response.done', response: { status: 'completed' } })

    expect(assistantDeltas).toEqual(['我', '我在。'])
    expect(turns).toHaveLength(1)
    expect(turns[0]).toMatchObject({
      userText: '你好',
      assistantText: '我在。',
      workspaceId: 'default',
      sessionId: 'voice',
    })
    expect(transcriptStable).toHaveLength(1)
    expect(transcriptStable[0]).toBeGreaterThanOrEqual(0)

    now = 3_000
    session.interrupt()
    now = 3_045
    channel.serverEvent({ type: 'output_audio_buffer.cleared' })
    expect(interruptAcks).toEqual([45])
    session.close()
  })

  it('uses a bounded transcript grace window when provider events arrive out of order', async () => {
    vi.useFakeTimers()
    try {
      const { RealtimeVoiceSession } = await import('@/audio/realtime-voice')
      const session = new RealtimeVoiceSession()
      const turns: unknown[] = []
      session.on('turn-complete', (turn) => turns.push(turn))
      await session.startPushToTalk({ workspaceId: 'default', sessionId: 'voice' })
      session.stopPushToTalk()
      const channel = MockPeerConnection.latest!.channel
      channel.serverEvent({ type: 'response.output_audio_transcript.done', transcript: 'answer' })
      channel.serverEvent({ type: 'response.done', response: { status: 'completed' } })
      vi.advanceTimersByTime(599)
      expect(turns).toHaveLength(0)
      channel.serverEvent({ type: 'conversation.item.input_audio_transcription.completed', transcript: 'question' })
      expect(turns).toHaveLength(1)
      expect(turns[0]).toMatchObject({ userText: 'question', assistantText: 'answer' })
      session.close()
    } finally {
      vi.useRealTimers()
    }
  })

  it('ignores late transcript and audio events after a turn is interrupted', async () => {
    const { RealtimeVoiceSession } = await import('@/audio/realtime-voice')
    const session = new RealtimeVoiceSession()
    const partials: string[] = []
    const deltas: string[] = []
    const lipSync: Array<{ active: boolean }> = []
    vi.spyOn(performance, 'now').mockReturnValue(2_000)
    session.on('input-partial', ({ text }) => partials.push(text))
    session.on('assistant-delta', ({ text }) => deltas.push(text))
    session.on('lip-sync-level', ({ active }) => lipSync.push({ active }))

    await session.startPushToTalk({ workspaceId: 'default', sessionId: 'voice' })
    session.stopPushToTalk()
    const channel = MockPeerConnection.latest!.channel
    session.interrupt()

    channel.serverEvent({ type: 'conversation.item.input_audio_transcription.delta', delta: 'late input' })
    channel.serverEvent({ type: 'response.output_audio_transcript.delta', delta: 'late answer' })
    channel.serverEvent({ type: 'response.output_audio.delta', delta: 'late audio' })

    expect(partials).toEqual([])
    expect(deltas).toEqual([])
    expect(lipSync).toEqual([])
    session.close()
  })

  it('rejects identified events from an interrupted response after a new turn starts', async () => {
    const { RealtimeVoiceSession } = await import('@/audio/realtime-voice')
    const session = new RealtimeVoiceSession()
    const partials: string[] = []
    const deltas: string[] = []
    const turns: Array<{ userText: string; assistantText: string }> = []
    const lipSync: Array<{ active: boolean }> = []
    let now = 2_000
    vi.spyOn(performance, 'now').mockImplementation(() => now)
    session.on('input-partial', ({ text }) => partials.push(text))
    session.on('assistant-delta', ({ text }) => deltas.push(text))
    session.on('turn-complete', (turn) => turns.push(turn))
    session.on('lip-sync-level', ({ active }) => lipSync.push({ active }))

    await session.startPushToTalk({ workspaceId: 'default', sessionId: 'voice', interruptionEpoch: 1 })
    now = 2_300
    session.stopPushToTalk()
    const channel = MockPeerConnection.latest!.channel
    const firstCreate = channel.sent.map((payload) => JSON.parse(payload))
      .find((payload) => payload.type === 'response.create')
    channel.serverEvent({
      type: 'response.created',
      response: { id: 'response-a', status: 'in_progress', metadata: firstCreate.response.metadata },
    })
    session.interrupt()

    now = 3_000
    await session.startPushToTalk({ workspaceId: 'default', sessionId: 'voice', interruptionEpoch: 2 })
    now = 3_300
    session.stopPushToTalk()
    const creates = channel.sent.map((payload) => JSON.parse(payload))
      .filter((payload) => payload.type === 'response.create')
    const secondCreate = creates.at(-1)
    channel.serverEvent({
      type: 'response.created',
      response: { id: 'response-b', status: 'in_progress', metadata: secondCreate.response.metadata },
    })

    channel.serverEvent({ type: 'input_audio_buffer.committed', item_id: 'item-a' })
    channel.serverEvent({
      type: 'conversation.item.input_audio_transcription.delta',
      item_id: 'item-a',
      delta: 'late input',
    })
    channel.serverEvent({
      type: 'response.output_audio_transcript.delta',
      response_id: 'response-a',
      delta: 'late answer',
    })
    channel.serverEvent({
      type: 'response.output_audio.delta',
      response_id: 'response-a',
      delta: 'late audio',
    })
    channel.serverEvent({ type: 'output_audio_buffer.started', response_id: 'response-a' })
    channel.serverEvent({ type: 'output_audio_buffer.stopped', response_id: 'response-a' })
    channel.serverEvent({
      type: 'response.done',
      response: { id: 'response-a', status: 'completed', metadata: firstCreate.response.metadata },
    })

    expect(partials).toEqual([])
    expect(deltas).toEqual([])
    expect(turns).toEqual([])
    expect(lipSync).toEqual([])

    channel.serverEvent({ type: 'input_audio_buffer.committed', item_id: 'item-b' })
    channel.serverEvent({
      type: 'conversation.item.input_audio_transcription.completed',
      item_id: 'item-b',
      transcript: 'current input',
    })
    channel.serverEvent({
      type: 'response.output_audio_transcript.done',
      response_id: 'response-b',
      transcript: 'current answer',
    })
    channel.serverEvent({
      type: 'response.done',
      response: { id: 'response-b', status: 'completed', metadata: secondCreate.response.metadata },
    })

    expect(turns).toHaveLength(1)
    expect(turns[0]).toMatchObject({
      userText: 'current input',
      assistantText: 'current answer',
      interruptionEpoch: 2,
    })
    session.close()
  })

  it('delegates completed realtime function calls to the existing agent endpoint once', async () => {
    const actionEnvelope = {
      version: 1,
      request_id: 'agent-request',
      actions: [{ type: 'tool_trace', payload: [{ step_id: 'tool-1', status: 'completed' }] }],
    }
    requestJsonMock.mockImplementation((url: string) => {
      if (url.endsWith('/api/realtime/client-secret')) {
        return Promise.resolve({
          client_secret: 'ek_test',
          model: 'gpt-realtime-test',
          voice: 'marin',
          agent_model: 'agent-model-test',
          workspace_id: 'default',
          session_id: 'voice',
        })
      }
      if (url.endsWith('/v1/chat/completions')) {
        return Promise.resolve({
          choices: [{ message: { role: 'assistant', content: 'Agent result' } }],
          pet_control: { emotion_id: 'happy' },
          action_envelope: actionEnvelope,
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    const { RealtimeVoiceSession } = await import('@/audio/realtime-voice')
    const session = new RealtimeVoiceSession()
    const petControlContext = {
      models: [{ id: 'model-a', type: 'live2d' as const }],
      emotions: ['happy'],
      motionGroups: ['TapBody'],
      motionOptions: [{ group: 'TapBody', index: 0 }],
      expressions: ['smile'],
      parameters: [{ id: 'ParamAngleX', min: -30, max: 30 }],
    }
    const agentResults: unknown[] = []
    const companionEvents: unknown[] = []
    const turns: unknown[] = []
    session.on('agent-result', (payload) => agentResults.push(payload))
    session.on('companion-event', (payload) => companionEvents.push(payload))
    session.on('turn-complete', (payload) => turns.push(payload))
    vi.spyOn(performance, 'now').mockReturnValue(2_000)

    await session.startPushToTalk({ workspaceId: 'default', sessionId: 'voice', petControlContext })
    session.stopPushToTalk()
    const channel = MockPeerConnection.latest!.channel
    channel.serverEvent({
      type: 'conversation.item.input_audio_transcription.completed',
      transcript: 'Please check my tools',
    })
    const toolResponse = {
      type: 'response.done',
      response: {
        status: 'completed',
        output: [{
          type: 'function_call',
          status: 'completed',
          call_id: 'call-1',
          name: 'delegate_to_agent',
          arguments: JSON.stringify({ request: 'Please check my tools', intent: 'tool' }),
        }],
      },
    }
    channel.serverEvent(toolResponse)
    channel.serverEvent(toolResponse)

    await vi.waitFor(() => {
      expect(requestJsonMock).toHaveBeenCalledWith(
        'http://localhost:8001/v1/chat/completions',
        expect.objectContaining({
          method: 'POST',
          timeoutMs: 120_000,
        }),
      )
    })
    const agentCalls = requestJsonMock.mock.calls.filter(([url]) => String(url).endsWith('/v1/chat/completions'))
    expect(agentCalls).toHaveLength(1)
    const requestBody = JSON.parse(agentCalls[0][1].body)
    expect(requestBody).toMatchObject({
      model: 'agent-model-test',
      session_id: 'voice',
      workspace_id: 'default',
      mcp_enabled: true,
      pet_control_context: petControlContext,
      stream: false,
      messages: [{ role: 'user', content: 'Please check my tools' }],
    })

    await vi.waitFor(() => {
      const sent = channel.sent.map((payload) => JSON.parse(payload))
      const output = sent.find((payload) => payload.item?.type === 'function_call_output')
      expect(output).toMatchObject({
        type: 'conversation.item.create',
        item: { call_id: 'call-1' },
      })
      expect(JSON.parse(output.item.output)).toMatchObject({ ok: true, reply: 'Agent result' })
    })
    expect(agentResults).toEqual([expect.objectContaining({
      callId: 'call-1',
      reply: 'Agent result',
      petControl: { emotion_id: 'happy' },
      actionEnvelope,
      workspaceId: 'default',
      sessionId: 'voice',
      interruptionEpoch: 0,
    })])
    expect(companionEvents).toEqual([
      expect.objectContaining({
        type: 'AgentJobCreated',
        workspaceId: 'default',
        sessionId: 'voice',
        jobId: 'realtime-agent:call-1',
        requestId: 'realtime_call-1',
        revision: 1,
        interruptionEpoch: 0,
        source: 'voice',
        status: 'created',
      }),
      expect.objectContaining({
        type: 'AgentJobCompleted',
        jobId: 'realtime-agent:call-1',
        revision: 2,
        status: 'completed',
      }),
    ])
    expect(companionEvents[0]).toMatchObject({ turnId: companionEvents[1].turnId })

    channel.serverEvent({
      type: 'response.output_audio_transcript.done',
      transcript: 'Agent result',
    })
    channel.serverEvent({ type: 'response.done', response: { status: 'completed', output: [] } })
    expect(turns).toHaveLength(1)
    expect(turns[0]).toMatchObject({
      turnId: companionEvents[0].turnId,
      interruptionEpoch: 0,
      actionEnvelope,
    })
    session.close()
  })

  it('drops a delegated agent result after the user interrupts the realtime turn', async () => {
    let resolveAgent: ((value: unknown) => void) | null = null
    requestJsonMock.mockImplementation((url: string) => {
      if (url.endsWith('/api/realtime/client-secret')) {
        return Promise.resolve({
          client_secret: 'ek_test',
          model: 'gpt-realtime-test',
          voice: 'marin',
          agent_model: 'agent-model-test',
          workspace_id: 'default',
          session_id: 'voice',
        })
      }
      if (url.endsWith('/v1/chat/completions')) {
        return new Promise((resolve) => { resolveAgent = resolve })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    const { RealtimeVoiceSession } = await import('@/audio/realtime-voice')
    const session = new RealtimeVoiceSession()
    const companionEvents: unknown[] = []
    session.on('companion-event', (payload) => companionEvents.push(payload))
    vi.spyOn(performance, 'now').mockReturnValue(2_000)

    await session.startPushToTalk({ workspaceId: 'default', sessionId: 'voice' })
    session.stopPushToTalk()
    const channel = MockPeerConnection.latest!.channel
    channel.serverEvent({
      type: 'response.done',
      response: {
        status: 'completed',
        output: [{
          type: 'function_call',
          status: 'completed',
          call_id: 'call-late',
          name: 'delegate_to_agent',
          arguments: JSON.stringify({ request: 'Run a slow task', intent: 'task' }),
        }],
      },
    })
    await vi.waitFor(() => expect(resolveAgent).not.toBeNull())
    session.interrupt()
    resolveAgent?.({ choices: [{ message: { content: 'Late result' } }] })
    await Promise.resolve()
    await Promise.resolve()

    const outputs = channel.sent
      .map((payload) => JSON.parse(payload))
      .filter((payload) => payload.item?.type === 'function_call_output')
    expect(outputs).toEqual([])
    expect(companionEvents).toEqual([
      expect.objectContaining({ type: 'AgentJobCreated', revision: 1, status: 'created' }),
      expect.objectContaining({ type: 'AgentJobCancelled', revision: 2, status: 'cancelled' }),
    ])
    session.close()
  })

  it('keeps an Agent delegation inside its original turn when push-to-talk is pressed again', async () => {
    let resolveAgent: ((value: unknown) => void) | null = null
    requestJsonMock.mockImplementation((url: string) => {
      if (url.endsWith('/api/realtime/client-secret')) {
        return Promise.resolve({
          client_secret: 'ek_test',
          model: 'gpt-realtime-test',
          voice: 'marin',
          agent_model: 'agent-model-test',
          workspace_id: 'default',
          session_id: 'voice',
        })
      }
      if (url.endsWith('/v1/chat/completions')) {
        return new Promise((resolve) => { resolveAgent = resolve })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    const { RealtimeVoiceSession } = await import('@/audio/realtime-voice')
    const session = new RealtimeVoiceSession()
    const companionEvents: unknown[] = []
    session.on('companion-event', (payload) => companionEvents.push(payload))
    vi.spyOn(performance, 'now').mockReturnValue(2_000)

    await session.startPushToTalk({ workspaceId: 'default', sessionId: 'voice' })
    session.stopPushToTalk()
    const channel = MockPeerConnection.latest!.channel
    channel.serverEvent({
      type: 'response.done',
      response: {
        status: 'completed',
        output: [{
          type: 'function_call',
          status: 'completed',
          call_id: 'call-pending',
          name: 'delegate_to_agent',
          arguments: JSON.stringify({ request: 'Run a slow task', intent: 'task' }),
        }],
      },
    })
    await vi.waitFor(() => expect(resolveAgent).not.toBeNull())

    await expect(session.startPushToTalk({ workspaceId: 'default', sessionId: 'voice' }))
      .rejects.toThrow('being interrupted')
    resolveAgent?.({ choices: [{ message: { content: 'Late result' } }] })
    await Promise.resolve()
    await Promise.resolve()

    expect(channel.sent.map((payload) => JSON.parse(payload)).filter((payload) => payload.item?.type === 'function_call_output')).toEqual([])
    expect(companionEvents).toEqual([
      expect.objectContaining({ type: 'AgentJobCreated', status: 'created' }),
      expect.objectContaining({ type: 'AgentJobCancelled', status: 'cancelled' }),
    ])
    session.close()
  })

  it('returns every delegated function-call output before requesting one follow-up response', async () => {
    requestJsonMock.mockImplementation((url: string, options?: { body?: string }) => {
      if (url.endsWith('/api/realtime/client-secret')) {
        return Promise.resolve({
          client_secret: 'ek_test',
          model: 'gpt-realtime-test',
          voice: 'marin',
          agent_model: 'agent-model-test',
          workspace_id: 'default',
          session_id: 'voice',
        })
      }
      if (url.endsWith('/v1/chat/completions')) {
        const body = JSON.parse(options?.body || '{}')
        return Promise.resolve({ choices: [{ message: { content: `Done: ${body.messages?.[0]?.content}` } }] })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    const { RealtimeVoiceSession } = await import('@/audio/realtime-voice')
    const session = new RealtimeVoiceSession()
    vi.spyOn(performance, 'now').mockReturnValue(2_000)

    await session.startPushToTalk({ workspaceId: 'default', sessionId: 'voice' })
    session.stopPushToTalk()
    const channel = MockPeerConnection.latest!.channel
    channel.serverEvent({
      type: 'response.done',
      response: {
        status: 'completed',
        output: [
          {
            type: 'function_call',
            status: 'completed',
            call_id: 'call-a',
            name: 'delegate_to_agent',
            arguments: JSON.stringify({ request: 'Task A', intent: 'tool' }),
          },
          {
            type: 'function_call',
            status: 'completed',
            call_id: 'call-b',
            name: 'delegate_to_agent',
            arguments: JSON.stringify({ request: 'Task B', intent: 'memory' }),
          },
        ],
      },
    })

    await vi.waitFor(() => {
      expect(requestJsonMock.mock.calls.filter(([url]) => String(url).endsWith('/v1/chat/completions'))).toHaveLength(2)
    })
    const sent = channel.sent.map((payload) => JSON.parse(payload))
    expect(sent.filter((payload) => payload.item?.type === 'function_call_output')).toHaveLength(2)
    expect(sent.filter((payload) => payload.response?.metadata?.source === 'yuizaki_agent_delegation')).toHaveLength(1)
    session.close()
  })

  it('rejects a late delegated follow-up response after interruption starts a new turn', async () => {
    requestJsonMock.mockImplementation((url: string) => {
      if (url.endsWith('/api/realtime/client-secret')) {
        return Promise.resolve({
          client_secret: 'ek_test',
          model: 'gpt-realtime-test',
          voice: 'marin',
          agent_model: 'agent-model-test',
          workspace_id: 'default',
          session_id: 'voice',
        })
      }
      if (url.endsWith('/v1/chat/completions')) {
        return Promise.resolve({ choices: [{ message: { content: 'delegated answer' } }] })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    const { RealtimeVoiceSession } = await import('@/audio/realtime-voice')
    const session = new RealtimeVoiceSession()
    const deltas: string[] = []
    const turns: unknown[] = []
    session.on('assistant-delta', ({ text }) => deltas.push(text))
    session.on('turn-complete', turn => turns.push(turn))
    vi.spyOn(performance, 'now').mockReturnValue(2_000)

    await session.startPushToTalk({ workspaceId: 'default', sessionId: 'voice', interruptionEpoch: 1 })
    session.stopPushToTalk()
    const channel = MockPeerConnection.latest!.channel
    channel.serverEvent({
      type: 'response.done',
      response: {
        status: 'completed',
        output: [{
          type: 'function_call',
          status: 'completed',
          call_id: 'call-follow-up-a',
          name: 'delegate_to_agent',
          arguments: JSON.stringify({ request: 'Task A', intent: 'task' }),
        }],
      },
    })
    await vi.waitFor(() => {
      const followUps = channel.sent
        .map(payload => JSON.parse(payload))
        .filter(payload => payload.response?.metadata?.source === 'yuizaki_agent_delegation')
      expect(followUps).toHaveLength(1)
    })
    const followUpA = channel.sent
      .map(payload => JSON.parse(payload))
      .find(payload => payload.response?.metadata?.source === 'yuizaki_agent_delegation')
    channel.serverEvent({
      type: 'response.created',
      response: { id: 'delegated-response-a', metadata: followUpA.response.metadata },
    })

    session.interrupt()
    await session.startPushToTalk({ workspaceId: 'default', sessionId: 'voice', interruptionEpoch: 2 })
    session.stopPushToTalk()
    const latestCreate = channel.sent
      .map(payload => JSON.parse(payload))
      .filter(payload => payload.type === 'response.create')
      .at(-1)
    channel.serverEvent({
      type: 'response.created',
      response: { id: 'response-b', metadata: latestCreate.response.metadata },
    })

    channel.serverEvent({
      type: 'response.output_audio_transcript.delta',
      response_id: 'delegated-response-a',
      delta: 'late delegated A',
    })
    channel.serverEvent({
      type: 'response.done',
      response: {
        id: 'delegated-response-a',
        status: 'completed',
        metadata: followUpA.response.metadata,
      },
    })

    expect(deltas).toEqual([])
    expect(turns).toEqual([])
    session.close()
  })

  it('rejects a new realtime turn until the interrupted response is isolated', async () => {
    const { RealtimeVoiceSession } = await import('@/audio/realtime-voice')
    const session = new RealtimeVoiceSession()
    let now = 2_000
    vi.spyOn(performance, 'now').mockImplementation(() => now)

    await session.startPushToTalk({ workspaceId: 'default', sessionId: 'voice' })
    now = 2_300
    session.stopPushToTalk()
    const channel = MockPeerConnection.latest!.channel
    const create = channel.sent
      .map(payload => JSON.parse(payload))
      .find(payload => payload.type === 'response.create')
    channel.serverEvent({
      type: 'response.created',
      response: { id: 'response-old', metadata: create.response.metadata },
    })

    await expect(session.startPushToTalk({ workspaceId: 'default', sessionId: 'voice' }))
      .rejects.toThrow('being interrupted')
    expect(channel.sent.map((payload) => JSON.parse(payload).type)).toContain('response.cancel')
    session.close()
  })

  it('derives a bounded lip-sync envelope from the remote WebRTC audio track', async () => {
    const analyser = {
      fftSize: 0,
      getFloatTimeDomainData: vi.fn((samples: Float32Array) => samples.fill(0.1)),
    }
    const source = {
      connect: vi.fn(),
      disconnect: vi.fn(),
    }
    const audioContext = {
      createMediaStreamSource: vi.fn(() => source),
      createAnalyser: vi.fn(() => analyser),
      resume: vi.fn().mockResolvedValue(undefined),
      close: vi.fn().mockResolvedValue(undefined),
    }
    function MockAudioContext() {
      return audioContext
    }
    vi.stubGlobal('AudioContext', MockAudioContext)
    let animationFrame: FrameRequestCallback | null = null
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
      animationFrame = callback
      return 41
    })
    vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => {
      animationFrame = null
    })

    const { RealtimeVoiceSession } = await import('@/audio/realtime-voice')
    const session = new RealtimeVoiceSession()
    const levels: Array<{ level: number; active: boolean }> = []
    let now = 5_000
    vi.spyOn(performance, 'now').mockImplementation(() => now)
    session.on('lip-sync-level', (payload) => levels.push(payload))

    await session.startPushToTalk({ workspaceId: 'default', sessionId: 'voice' })
    const peer = MockPeerConnection.latest!
    peer.ontrack?.({
      streams: [new MediaStream()],
      track: audioTrack as unknown as MediaStreamTrack,
    } as RTCTrackEvent)
    now = 5_300
    session.stopPushToTalk()
    peer.channel.serverEvent({ type: 'output_audio_buffer.started' })

    expect(levels[0]).toEqual({ level: 0, active: true })
    now = 5_340
    animationFrame?.(now)
    expect(levels.at(-1)?.active).toBe(true)
    expect(levels.at(-1)?.level).toBeGreaterThan(0)
    expect(levels.at(-1)?.level).toBeLessThanOrEqual(1)

    peer.channel.serverEvent({ type: 'output_audio_buffer.stopped' })
    expect(levels.at(-1)).toEqual({ level: 0, active: false })
    session.close()
  })
})
