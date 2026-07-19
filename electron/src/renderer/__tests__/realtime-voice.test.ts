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
    let now = 2_000
    vi.spyOn(performance, 'now').mockImplementation(() => now)
    session.on('turn-complete', (turn) => turns.push(turn))
    session.on('assistant-delta', ({ text }) => assistantDeltas.push(text))
    session.on('interrupt-ack', ({ elapsedMs }) => interruptAcks.push(elapsedMs))

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

    now = 3_000
    session.interrupt()
    now = 3_045
    channel.serverEvent({ type: 'output_audio_buffer.cleared' })
    expect(interruptAcks).toEqual([45])
    session.close()
  })

  it('rejects a new realtime turn until the interrupted response is isolated', async () => {
    const { RealtimeVoiceSession } = await import('@/audio/realtime-voice')
    const session = new RealtimeVoiceSession()
    vi.spyOn(performance, 'now').mockReturnValue(2_000)

    await session.startPushToTalk({ workspaceId: 'default', sessionId: 'voice' })
    session.stopPushToTalk()
    const channel = MockPeerConnection.latest!.channel
    channel.serverEvent({ type: 'response.created', response: { id: 'response-old' } })

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
