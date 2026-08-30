import { describe, expect, it } from 'vitest'
import { shouldOfferRealtimeInterrupt, shouldOfferRealtimeRecovery } from './realtimeRecoveryPolicy'

describe('realtime recovery policy', () => {
  it('offers a user-controlled retry only after an instant-mode failure', () => {
    expect(shouldOfferRealtimeRecovery({ responseMode: 'instant', recording: false, ttsPlaying: false, status: 'error' })).toBe(true)
    expect(shouldOfferRealtimeRecovery({ responseMode: 'instant', recording: false, ttsPlaying: false, status: 'closed' })).toBe(true)
  })

  it('does not add a recovery action while another audio operation is active', () => {
    expect(shouldOfferRealtimeRecovery({ responseMode: 'instant', recording: true, ttsPlaying: false, status: 'error' })).toBe(false)
    expect(shouldOfferRealtimeRecovery({ responseMode: 'instant', recording: false, ttsPlaying: true, status: 'closed' })).toBe(false)
    expect(shouldOfferRealtimeRecovery({ responseMode: 'balanced', recording: false, ttsPlaying: false, status: 'error' })).toBe(false)
    expect(shouldOfferRealtimeRecovery({ responseMode: 'instant', recording: false, ttsPlaying: false, status: 'ready' })).toBe(false)
  })
})

describe('realtime interrupt policy', () => {
  it('allows stopping a response before audio starts', () => {
    expect(shouldOfferRealtimeInterrupt({ ttsPlaying: false, status: 'responding' })).toBe(true)
    expect(shouldOfferRealtimeInterrupt({ ttsPlaying: false, status: 'interrupting' })).toBe(true)
    expect(shouldOfferRealtimeInterrupt({ ttsPlaying: true, status: 'ready' })).toBe(true)
  })

  it('does not expose a stop action while realtime voice is idle', () => {
    expect(shouldOfferRealtimeInterrupt({ ttsPlaying: false, status: 'idle' })).toBe(false)
    expect(shouldOfferRealtimeInterrupt({ ttsPlaying: false, status: 'ready' })).toBe(false)
    expect(shouldOfferRealtimeInterrupt({ ttsPlaying: false, status: 'error' })).toBe(false)
  })
})
