import { describe, expect, it, vi } from 'vitest'
import type { RealtimeVoiceEventMap } from '../audio/realtime-voice'
import { RealtimeVoiceEventBridge, type RealtimeVoiceEventSource } from '../app/runtime/realtimeVoiceEventBridge'

describe('RealtimeVoiceEventBridge', () => {
  it('tracks typed subscriptions and disposes each one exactly once', () => {
    const disposers = new Map<keyof RealtimeVoiceEventMap, () => void>()
    const source: RealtimeVoiceEventSource = {
      on: (event, _listener) => {
        const dispose = vi.fn()
        disposers.set(event, dispose)
        return dispose
      },
    }
    const bridge = new RealtimeVoiceEventBridge(source)

    bridge.listen('status', () => undefined)
    bridge.listen('playback-end', () => undefined)
    bridge.detach()
    bridge.detach()

    expect(disposers.get('status')).toHaveBeenCalledTimes(1)
    expect(disposers.get('playback-end')).toHaveBeenCalledTimes(1)
  })

  it('can be reused after detaching the previous subscriptions', () => {
    const firstDispose = vi.fn()
    const secondDispose = vi.fn()
    let bindCount = 0
    const source: RealtimeVoiceEventSource = {
      on: () => {
        bindCount += 1
        return bindCount === 1 ? firstDispose : secondDispose
      },
    }
    const bridge = new RealtimeVoiceEventBridge(source)

    bridge.listen('status', () => undefined)
    bridge.detach()
    bridge.listen('status', () => undefined)
    bridge.detach()

    expect(firstDispose).toHaveBeenCalledTimes(1)
    expect(secondDispose).toHaveBeenCalledTimes(1)
  })
})
