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
    disconnect: vi.fn(),
  },
}))

vi.mock('socket.io-client', () => ({
  io: socketIoMock.io,
}))

describe('SocketClient contract helpers', () => {
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

  it('includes workspace context in direct LLM socket requests', () => {
    const client = new SocketClient()
    const emitSpy = vi.spyOn(client, 'emit').mockImplementation(() => undefined)

    client.sendLLMRequest([{ role: 'user', content: 'hello' }], 'session-1', 'req-1', 'workspace-1', { model: 'gpt-test' })

    expect(emitSpy).toHaveBeenCalledWith(SocketEvents.LLM_REQUEST, {
      messages: [{ role: 'user', content: 'hello' }],
      session_id: 'session-1',
      request_id: 'req-1',
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
    )

    expect(emitSpy).toHaveBeenCalledWith(SocketEvents.AGENT_CHAT, {
      messages: [{ role: 'user', content: 'hello' }],
      session_id: 'session-1',
      workspace_id: 'workspace-1',
      pet_control_context: { expressions: [] },
      request_id: 'req-1',
      chat_options: { reasoning_effort: 'high', mcp_enabled: false },
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
})
