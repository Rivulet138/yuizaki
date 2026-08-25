import { afterEach, describe, expect, it, vi } from 'vitest'
import { SocketClient, SocketEvents } from '../net/socketClient'
import { clearControlAuthToken, CONTROL_ORIGIN } from '../api/clients/http-client'

const socketIoMock = vi.hoisted(() => ({
  io: vi.fn(),
  socket: {
    connected: false,
    id: 'sid-test',
    on: vi.fn(),
    once: vi.fn(),
    off: vi.fn(),
    emit: vi.fn(),
    connect: vi.fn(),
    disconnect: vi.fn(),
    auth: undefined as { token: string } | undefined,
  },
}))

vi.mock('socket.io-client', () => ({
  io: socketIoMock.io,
}))

describe('SocketClient contract helpers', () => {
  const createConnectedClient = () => {
    const socket = {
      ...socketIoMock.socket,
      connected: true,
      id: 'sid-test',
      on: vi.fn(),
      off: vi.fn(),
      emit: vi.fn(),
    }
    const client = new SocketClient()
    ;(client as unknown as { socket: typeof socket }).socket = socket
    client.connected.value = true
    return { client, socket }
  }

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.clearAllMocks()
    clearControlAuthToken()
    window.sessionStorage.clear()
    delete (window as Window & { __YUIZAKI_CONTROL_TOKEN__?: string }).__YUIZAKI_CONTROL_TOKEN__
    window.history.replaceState({}, '', '/')
  })

  it('keeps agent and lifecycle event constants aligned with the backend contract', () => {
    expect(SocketEvents.CONNECT).toBe('connect')
    expect(SocketEvents.DISCONNECT).toBe('disconnect')
    expect(SocketEvents.AGENT_CHAT).toBe('agent:chat')
    expect(SocketEvents.AGENT_UPDATE).toBe('agent:update')
    expect(SocketEvents.AGENT_RESULT).toBe('agent:result')
    expect(SocketEvents.ASR_VAD_START).toBe('asr:vad-start')
    expect(SocketEvents.ASR_SPEECH_START).toBe('asr:speech-start')
    expect(SocketEvents.INTERRUPT_ACK).toBe('interrupt:ack')
    expect(SocketEvents.CLIENT_TIMING).toBe('system:client-timing')
  })

  it('sends correlated interrupt and renderer timing events', () => {
    const client = new SocketClient()
    const emitSpy = vi.spyOn(client, 'emit').mockImplementation(() => undefined)

    client.sendInterrupt('session-1', 'interrupt-1')
    client.sendClientTiming('interrupt_ack', {
      sessionId: 'session-1',
      generationId: 'generation-1',
      elapsedMs: 48.25,
    })

    expect(emitSpy).toHaveBeenNthCalledWith(1, SocketEvents.INTERRUPT, {
      session_id: 'session-1',
      request_id: 'interrupt-1',
      source: 'manual',
    })
    expect(emitSpy).toHaveBeenNthCalledWith(2, SocketEvents.CLIENT_TIMING, {
      stage: 'interrupt_ack',
      session_id: 'session-1',
      generation_id: 'generation-1',
      elapsed_ms: 48.25,
    })
  })

  it('sends tool job identity and retry metadata', () => {
    const client = new SocketClient()
    const emitSpy = vi.spyOn(client, 'emit').mockImplementation(() => undefined)

    client.sendToolCall('call-retry', 'read_file', { path: 'readme.txt' }, {
      requestId: 'request-retry',
      runId: 'run-original',
      jobId: 'job-original',
      source: 'desktop',
      retry: true,
    })

    expect(emitSpy).toHaveBeenCalledWith(SocketEvents.TOOL_CALL, {
      id: 'call-retry',
      name: 'read_file',
      args: { path: 'readme.txt' },
      request_id: 'request-retry',
      run_id: 'run-original',
      job_id: 'job-original',
      source: 'desktop',
      retry: true,
    })
  })

  it('waits for one exact heartbeat echo and returns a redacted audit', async () => {
    const { client, socket } = createConnectedClient()
    const correlation = { timestamp: 123, request_id: 'request-1', client_id: 'sid-test' }
    socket.emit.mockImplementation((_event, payload) => {
      const handler = socket.on.mock.calls.find(([event]) => event === SocketEvents.HEARTBEAT)?.[1]
      queueMicrotask(() => handler(payload))
    })

    await expect(client.emitHeartbeatOnceAndWaitForEcho({ correlation, duplicateWindowMs: 1 })).resolves.toEqual({
      emitted: true,
      echoed: true,
      echo_count: 1,
      correlation: { timestamp: 123, request_id: '[verified]', client_id: '[verified]' },
    })
    expect(socket.off).toHaveBeenCalledWith(SocketEvents.HEARTBEAT, expect.any(Function))
  })

  it('fails heartbeat verification when no echo arrives', async () => {
    const { client, socket } = createConnectedClient()

    await expect(client.emitHeartbeatOnceAndWaitForEcho({ timeoutMs: 5 })).rejects.toThrow(/timed out/i)
    expect(socket.off).toHaveBeenCalledWith(SocketEvents.HEARTBEAT, expect.any(Function))
  })

  it('rejects heartbeat echoes with the wrong timestamp or request id', async () => {
    for (const wrong of [
      { timestamp: 124, request_id: 'request-1', client_id: 'sid-test' },
      { timestamp: 123, request_id: 'wrong', client_id: 'sid-test' },
    ]) {
      const { client, socket } = createConnectedClient()
      socket.emit.mockImplementation(() => {
        const handler = socket.on.mock.calls.find(([event]) => event === SocketEvents.HEARTBEAT)?.[1]
        queueMicrotask(() => handler(wrong))
      })
      await expect(client.emitHeartbeatOnceAndWaitForEcho({
        correlation: { timestamp: 123, request_id: 'request-1', client_id: 'sid-test' },
        timeoutMs: 20,
      })).rejects.toThrow(/did not match/i)
    }
  })

  it('rejects duplicate exact heartbeat echoes', async () => {
    const { client, socket } = createConnectedClient()
    const correlation = { timestamp: 123, request_id: 'request-1', client_id: 'sid-test' }
    socket.emit.mockImplementation((_event, payload) => {
      const handler = socket.on.mock.calls.find(([event]) => event === SocketEvents.HEARTBEAT)?.[1]
      queueMicrotask(() => {
        handler(payload)
        handler(payload)
      })
    })

    await expect(client.emitHeartbeatOnceAndWaitForEcho({ correlation, duplicateWindowMs: 10 })).rejects.toThrow(/duplicated/i)
    expect(socket.off).toHaveBeenCalledWith(SocketEvents.HEARTBEAT, expect.any(Function))
  })

  it('includes workspace context in direct LLM socket requests', () => {
    const client = new SocketClient()
    const emitSpy = vi.spyOn(client, 'emit').mockImplementation(() => undefined)

    client.sendLLMRequest(
      [{ role: 'user', content: 'hello' }],
      'session-1',
      'req-1',
      'workspace-1',
      { model: 'gpt-test' },
      'generation-1',
      'turn-1',
      6,
    )

    expect(emitSpy).toHaveBeenCalledWith(SocketEvents.LLM_REQUEST, {
      messages: [{ role: 'user', content: 'hello' }],
      session_id: 'session-1',
      request_id: 'req-1',
      generation_id: 'generation-1',
      turn_id: 'turn-1',
      interruption_epoch: 6,
      version: 1,
      workspace_id: 'workspace-1',
      chat_options: { model: 'gpt-test' },
    })
  })

  it('includes chat options in agent socket requests', () => {
    const client = new SocketClient()
    const emitSpy = vi.spyOn(client, 'emit').mockImplementation(() => undefined)

    client.sendAgentChat(
      [{ role: 'user', content: 'hello' }],
      'session-1',
      { expressions: [] },
      'req-1',
      'workspace-1',
      { reasoning_effort: 'high', mcp_enabled: false },
      5,
      'generation-1',
      'turn-1',
    )

    expect(emitSpy).toHaveBeenCalledWith(SocketEvents.AGENT_CHAT, {
      messages: [{ role: 'user', content: 'hello' }],
      session_id: 'session-1',
      workspace_id: 'workspace-1',
      pet_control_context: { expressions: [] },
      request_id: 'req-1',
      generation_id: 'generation-1',
      turn_id: 'turn-1',
      version: 1,
      chat_options: { reasoning_effort: 'high', mcp_enabled: false },
      interruption_epoch: 5,
    })
  })

  it('includes the complete generation envelope in ASR audio chunks', () => {
    const client = new SocketClient()
    const emitSpy = vi.spyOn(client, 'emit').mockImplementation(() => undefined)

    client.sendAudioChunk('base64-audio', 24_000, true, {
      sessionId: 'session-voice',
      generationId: 'generation-voice',
      turnId: 'turn-voice',
      requestId: 'request-voice',
      interruptionEpoch: 7,
      version: 1,
    })

    expect(emitSpy).toHaveBeenCalledWith(SocketEvents.AUDIO_CHUNK, {
      chunk: 'base64-audio',
      sample_rate: 24_000,
      is_final: true,
      session_id: 'session-voice',
      generation_id: 'generation-voice',
      turn_id: 'turn-voice',
      request_id: 'request-voice',
      interruption_epoch: 7,
      version: 1,
    })
  })

  it('emits realtime visual frame requests for companion-layer screen context by default', () => {
    const client = new SocketClient()
    const emitSpy = vi.spyOn(client, 'emit').mockImplementation(() => undefined)

    client.requestScreenshot('data:image/png;base64,cG5n', {
      displayIndex: 2,
      caption: 'user is moving a window',
      source: 'desktop',
      frameId: 'frame-1',
      changeScore: 0.18,
      captureReason: 'change',
    })

    expect(emitSpy).toHaveBeenCalledWith(SocketEvents.SCREENSHOT_REQUEST, {
      image: 'data:image/png;base64,cG5n',
      display_index: 2,
      mode: 'observe',
      caption: 'user is moving a window',
      source: 'desktop',
      frame_id: 'frame-1',
      change_score: 0.18,
      capture_reason: 'change',
    })
  })

  it('can still request OCR explicitly when exact screen text is needed', () => {
    const client = new SocketClient()
    const emitSpy = vi.spyOn(client, 'emit').mockImplementation(() => undefined)

    client.requestScreenshot('data:image/png;base64,cG5n', { displayIndex: 1, mode: 'ocr' })

    expect(emitSpy).toHaveBeenCalledWith(SocketEvents.SCREENSHOT_REQUEST, {
      image: 'data:image/png;base64,cG5n',
      display_index: 1,
      mode: 'ocr',
    })
  })

  it('carries the visual Job identity with an explicit Agent frame', () => {
    const client = new SocketClient()
    const emitSpy = vi.spyOn(client, 'emit').mockImplementation(() => undefined)

    client.requestScreenshot('data:image/png;base64,cG5n', {
      mode: 'vision',
      frameId: 'frame-agent',
      workspaceId: 'workspace-1',
      sessionId: 'session-1',
      turnId: 'turn-1',
      jobId: 'vision-job-1',
      requestId: 'request-1',
      generationId: 'generation-1',
      interruptionEpoch: 3,
    })

    expect(emitSpy).toHaveBeenCalledWith(SocketEvents.SCREENSHOT_REQUEST, {
      image: 'data:image/png;base64,cG5n',
      display_index: 0,
      mode: 'vision',
      frame_id: 'frame-agent',
      workspace_id: 'workspace-1',
      session_id: 'session-1',
      turn_id: 'turn-1',
      job_id: 'vision-job-1',
      request_id: 'request-1',
      generation_id: 'generation-1',
      interruption_epoch: 3,
    })
  })

  it('sends the backend auth token during the Socket.IO handshake', () => {
    window.sessionStorage.setItem('yuizaki.control.token', 'backend-token')
    socketIoMock.io.mockReturnValue(socketIoMock.socket)

    const client = new SocketClient('http://127.0.0.1:8001')
    client.connect()

    return vi.waitFor(() => {
      expect(socketIoMock.io).toHaveBeenCalled()
    }).then(() => {
      expect(socketIoMock.io).toHaveBeenCalledWith('http://127.0.0.1:8001', expect.objectContaining({
        path: '/socket.io',
        auth: { token: 'backend-token' },
      }))
    })
  })

  it('does not open Socket.IO when no backend auth token is available', async () => {
    window.history.replaceState({}, '', `/?control_origin=${encodeURIComponent(CONTROL_ORIGIN)}`)
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))
    vi.stubGlobal('fetch', fetchMock)
    socketIoMock.io.mockReturnValue(socketIoMock.socket)

    const client = new SocketClient('http://127.0.0.1:8001')
    client.connect()

    await vi.waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(`${CONTROL_ORIGIN}/`, expect.objectContaining({ cache: 'no-store' }))
    })
    expect(socketIoMock.io).not.toHaveBeenCalled()
  })

  it('uses the runtime Python API origin for the default Socket.IO endpoint', async () => {
    window.sessionStorage.setItem('yuizaki.control.token', 'backend-token')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ pythonApiOrigin: 'http://localhost:8011' }),
    }))
    socketIoMock.io.mockReturnValue(socketIoMock.socket)

    const client = new SocketClient()
    client.connect()

    await vi.waitFor(() => {
      expect(socketIoMock.io).toHaveBeenCalled()
    })

    expect(fetch).toHaveBeenCalledWith(`${CONTROL_ORIGIN}/api/system/env-check`, expect.objectContaining({
      headers: expect.objectContaining({
        Authorization: 'Bearer backend-token',
      }),
    }))
    expect(socketIoMock.io).toHaveBeenCalledWith('http://localhost:8011', expect.objectContaining({
      path: '/socket.io',
      auth: { token: 'backend-token' },
    }))
  })

  it('invalidates an in-flight bootstrap across disconnect and remount', async () => {
    window.sessionStorage.setItem('yuizaki.control.token', 'backend-token')
    let resolveFirst!: (value: unknown) => void
    const fetchMock = vi.fn()
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve }))
    vi.stubGlobal('fetch', fetchMock)
    socketIoMock.io.mockReturnValue(socketIoMock.socket)
    const client = new SocketClient()

    client.connect()
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    client.disconnect()
    client.connect()
    resolveFirst({
      ok: true,
      status: 200,
      json: async () => ({ pythonApiOrigin: 'http://localhost:8011' }),
    })
    await vi.waitFor(() => expect(socketIoMock.io).toHaveBeenCalledTimes(1))
    expect(socketIoMock.io).toHaveBeenCalledWith('http://localhost:8011', expect.any(Object))
    expect(socketIoMock.io).toHaveBeenCalledTimes(1)
  })

  it('does not let an old rejected socket retry mutate a remounted socket', async () => {
    window.history.replaceState({}, '', `/?control_origin=${encodeURIComponent(CONTROL_ORIGIN)}`)
    window.sessionStorage.setItem('yuizaki.control.token', 'backend-token')
    let resolveRefresh!: (value: unknown) => void
    vi.stubGlobal('fetch', vi.fn(() => new Promise((resolve) => { resolveRefresh = resolve })))
    const createSocket = () => ({
      connected: false,
      id: 'socket-test',
      on: vi.fn(),
      once: vi.fn(),
      off: vi.fn(),
      emit: vi.fn(),
      connect: vi.fn(),
      disconnect: vi.fn(),
      auth: undefined as { token: string } | undefined,
    })
    const oldSocket = createSocket()
    const remountedSocket = createSocket()
    socketIoMock.io.mockReturnValueOnce(oldSocket as never).mockReturnValueOnce(remountedSocket as never)
    const client = new SocketClient('http://127.0.0.1:8001')

    client.connect()
    await vi.waitFor(() => expect(socketIoMock.io).toHaveBeenCalledTimes(1))
    const oldConnectError = oldSocket.on.mock.calls.find(([event]) => event === 'connect_error')?.[1] as ((error: Error) => void)
    oldConnectError(new Error('authentication rejected'))
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))

    client.disconnect()
    client.connect()
    await vi.waitFor(() => expect(socketIoMock.io).toHaveBeenCalledTimes(2))
    resolveRefresh({
      ok: true,
      text: async () => '<meta name="yuizaki-control-token" content="fresh-token">',
    })
    await vi.waitFor(() => {
      expect(window.sessionStorage.getItem('yuizaki.control.token')).toBe('fresh-token')
    })

    expect(oldSocket.connect).not.toHaveBeenCalled()
    expect(remountedSocket.connect).not.toHaveBeenCalled()
    expect(remountedSocket.auth).toBeUndefined()
    client.disconnect()
  })
})
