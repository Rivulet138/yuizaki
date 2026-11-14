import { describe, expect, it, vi } from 'vitest'
import { SocketClient, SocketEvents } from './socketClient'

vi.mock('../logger', () => ({ logger: { warn: vi.fn() } }))
vi.mock('../api/clients/http-client', () => ({ API_ORIGIN: 'http://localhost' }))

describe('socket send contract', () => {
  it('returns offline without emitting or queueing a cancellation', () => {
    const client = new SocketClient()
    const emit = vi.fn()
    Object.assign(client, { socket: { connected: false, emit } })
    expect(client.sendInterrupt('session', 'request')).toEqual({ status: 'offline' })
    expect(emit).not.toHaveBeenCalled()
  })

  it('returns accepted with the exact cancellation target, without claiming a server ACK', () => {
    const client = new SocketClient()
    const emit = vi.fn()
    Object.assign(client, { socket: { connected: true, emit } })
    expect(client.sendInterrupt('session', 'request')).toEqual({ status: 'accepted' })
    expect(emit).toHaveBeenCalledWith(SocketEvents.INTERRUPT, { session_id: 'session', request_id: 'request', source: 'manual' })
  })

  it('returns rejected when the local transport refuses the send', () => {
    const client = new SocketClient()
    Object.assign(client, { socket: { connected: true, emit: () => { throw new Error('transport rejected') } } })
    expect(client.sendAgentChat([{ role: 'user', content: 'keep this draft' }])).toEqual({ status: 'rejected' })
  })
})
