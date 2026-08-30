import { beforeEach, describe, expect, it, vi } from 'vitest'

const requestJsonMock = vi.fn()

vi.mock('@/api/clients/http-client', () => ({
  API_ORIGIN: 'http://localhost:8001',
  requestJson: requestJsonMock,
}))

class MockDataChannel extends EventTarget {
  readyState: RTCDataChannelState = 'connecting'
  sent: string[] = []

  send(payload: string): void {
    this.sent.push(payload)
  }

  close(): void {
    this.readyState = 'closed'
  }

  open(): void {
    this.readyState = 'open'
    this.dispatchEvent(new Event('open'))
  }

  serverEvent(payload: Record<string, unknown>): void {
    this.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(payload) }))
  }
}

class MockPeerConnection extends EventTarget {
  static latest: MockPeerConnection | null = null
  connectionState: RTCPeerConnectionState = 'new'
  iceGatheringState: RTCIceGatheringState = 'complete'
  localDescription: RTCSessionDescription | null = null
  channel = new MockDataChannel()

  constructor() {
    super()
    MockPeerConnection.latest = this
  }

  addTrack(): RTCRtpSender {
    return {} as RTCRtpSender
  }

  createDataChannel(): RTCDataChannel {
    queueMicrotask(() => this.channel.open())
    return this.channel as unknown as RTCDataChannel
  }

  async createOffer(): Promise<RTCSessionDescriptionInit> {
    return { type: 'offer', sdp: 'offer-sdp' }
  }

  async setLocalDescription(description: RTCSessionDescriptionInit): Promise<void> {
    this.localDescription = description as RTCSessionDescription
  }

  async setRemoteDescription(): Promise<void> {
    this.connectionState = 'connected'
  }

  close(): void {
    this.connectionState = 'closed'
  }
}

const audioTrack = { enabled: true, readyState: 'live' as MediaStreamTrackState, stop: vi.fn() }
const mediaStream = {
  getAudioTracks: () => [audioTrack],
  getTracks: () => [audioTrack],
}

describe('RealtimeVoiceSession comfort state machine', () => {
  beforeEach(() => {
    vi.resetModules()
    vi.clearAllMocks()
    vi.useRealTimers()
    MockPeerConnection.latest = null
    requestJsonMock.mockResolvedValue({
      client_secret: 'ek_test',
      model: 'gpt-realtime-test',
      voice: 'marin',
      workspace_id: 'default',
      session_id: 'voice',
    })
    vi.stubGlobal('RTCPeerConnection', MockPeerConnection)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('answer-sdp', {
      status: 201,
      headers: { 'content-type': 'application/sdp' },
    })))
    vi.stubGlobal('window', globalThis)
    vi.stubGlobal('document', {
      body: { appendChild: vi.fn(), removeChild: vi.fn() },
      createElement: () => ({
        autoplay: false,
        style: {},
        setAttribute: vi.fn(),
        remove: vi.fn(),
        play: vi.fn().mockResolvedValue(undefined),
        pause: vi.fn(),
      }),
    })
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn().mockResolvedValue(mediaStream) } })
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => setTimeout(() => callback(performance.now()), 16) as unknown as number)
    vi.stubGlobal('cancelAnimationFrame', (id: number) => clearTimeout(id))
  })

  it('does not interrupt output for a short VAD candidate', async () => {
    vi.useFakeTimers()
    const { RealtimeVoiceSession } = await import('./realtime-voice')
    const session = new RealtimeVoiceSession()
    await session.connect({ workspaceId: 'default', sessionId: 'voice', voiceMode: 'continuous' })
    const channel = MockPeerConnection.latest!.channel
    channel.serverEvent({ type: 'response.created', response: { id: 'response-1' } })
    channel.serverEvent({ type: 'output_audio_buffer.started', response_id: 'response-1' })
    channel.serverEvent({ type: 'input_audio_buffer.speech_started' })
    vi.advanceTimersByTime(80)
    channel.serverEvent({ type: 'input_audio_buffer.speech_stopped' })
    vi.advanceTimersByTime(160)

    const sentTypes = channel.sent.map((payload) => JSON.parse(payload).type)
    expect(sentTypes).not.toContain('response.cancel')
    expect(session.getStatus()).toBe('recording')
    session.close()
  })

  it('passes the selected microphone as an ideal device constraint', async () => {
    const { RealtimeVoiceSession } = await import('./realtime-voice')
    const session = new RealtimeVoiceSession()
    await session.connect({ workspaceId: 'default', sessionId: 'voice', audioInputDeviceId: 'mic-1' })

    const getUserMedia = (navigator.mediaDevices.getUserMedia as unknown as ReturnType<typeof vi.fn>)
    expect(getUserMedia).toHaveBeenCalledWith(expect.objectContaining({
      audio: expect.objectContaining({ deviceId: { ideal: 'mic-1' } }),
    }))
    session.close()
  })

  it('interrupts output only after sustained VAD speech', async () => {
    vi.useFakeTimers()
    const { RealtimeVoiceSession } = await import('./realtime-voice')
    const session = new RealtimeVoiceSession()
    await session.connect({ workspaceId: 'default', sessionId: 'voice', voiceMode: 'continuous' })
    const channel = MockPeerConnection.latest!.channel
    channel.serverEvent({ type: 'response.created', response: { id: 'response-1' } })
    channel.serverEvent({ type: 'output_audio_buffer.started', response_id: 'response-1' })
    channel.serverEvent({ type: 'input_audio_buffer.speech_started' })
    vi.advanceTimersByTime(160)

    const sentTypes = channel.sent.map((payload) => JSON.parse(payload).type)
    expect(sentTypes.filter((type: string) => type === 'response.cancel')).toHaveLength(1)
    expect(sentTypes.filter((type: string) => type === 'output_audio_buffer.clear')).toHaveLength(1)
    expect(session.getStatus()).toBe('recording')
    session.close()
  })

  it('settles an empty audio commit without producing a turn', async () => {
    const { RealtimeVoiceSession } = await import('./realtime-voice')
    const session = new RealtimeVoiceSession()
    const emptyInputs: unknown[] = []
    const turns: unknown[] = []
    session.on('empty-input', (payload) => emptyInputs.push(payload))
    session.on('turn-complete', (payload) => turns.push(payload))
    let now = 1_000
    vi.spyOn(performance, 'now').mockImplementation(() => now)
    await session.startPushToTalk({ workspaceId: 'default', sessionId: 'voice' })
    now = 1_400
    expect(session.stopPushToTalk()).toBe(true)
    MockPeerConnection.latest!.channel.serverEvent({
      type: 'error',
      error: { code: 'input_audio_buffer_commit_empty' },
    })

    expect(emptyInputs).toHaveLength(1)
    expect(turns).toHaveLength(0)
    expect(session.getStatus()).toBe('ready')
    session.close()
  })

  it('ignores delayed commit errors from an interrupted turn', async () => {
    vi.useFakeTimers()
    const { RealtimeVoiceSession } = await import('./realtime-voice')
    const session = new RealtimeVoiceSession()
    const turns: Array<{ userText: string; assistantText: string }> = []
    session.on('turn-complete', (turn) => turns.push(turn))
    let now = 1_000
    vi.spyOn(performance, 'now').mockImplementation(() => now)
    await session.startPushToTalk({ workspaceId: 'default', sessionId: 'voice' })
    now = 1_400
    session.stopPushToTalk()
    const channel = MockPeerConnection.latest!.channel
    const firstCommit = channel.sent
      .map((payload) => JSON.parse(payload))
      .find((payload) => payload.type === 'input_audio_buffer.commit')
    session.interrupt()
    vi.advanceTimersByTime(250)
    await session.startPushToTalk({ workspaceId: 'default', sessionId: 'voice' })
    now = 1_800
    session.stopPushToTalk()
    const responseCreate = channel.sent
      .map((payload) => JSON.parse(payload))
      .filter((payload) => payload.type === 'response.create')
      .at(-1)
    const metadata = responseCreate.response.metadata

    channel.serverEvent({ type: 'input_audio_buffer.committed', item_id: 'old-item' })
    channel.serverEvent({
      type: 'error',
      error: { code: 'input_audio_buffer_commit_empty', event_id: firstCommit.event_id },
    })
    channel.serverEvent({ type: 'input_audio_buffer.committed', item_id: 'new-item' })
    channel.serverEvent({
      type: 'conversation.item.input_audio_transcription.completed',
      item_id: 'new-item',
      transcript: 'new input',
    })
    channel.serverEvent({ type: 'response.created', response: { id: 'new-response', metadata } })
    channel.serverEvent({
      type: 'response.output_audio_transcript.done',
      response_id: 'new-response',
      transcript: 'new answer',
    })
    channel.serverEvent({
      type: 'response.done',
      response: { id: 'new-response', status: 'completed', output: [] },
    })
    vi.advanceTimersByTime(600)

    expect(turns).toEqual([expect.objectContaining({ userText: 'new input', assistantText: 'new answer' })])
    session.close()
  })
})
