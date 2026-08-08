import { describe, expect, it, vi } from 'vitest'

import { AudioPlayerEventBridge } from '../audio/playbackEventBridge'

class EventHost {
  private readonly listeners = new Map<string, EventListener[]>()

  addEventListener(type: string, listener: EventListener): void {
    const listeners = this.listeners.get(type) ?? []
    listeners.push(listener)
    this.listeners.set(type, listeners)
  }

  removeEventListener(type: string, listener: EventListener): void {
    this.listeners.set(type, (this.listeners.get(type) ?? []).filter(candidate => candidate !== listener))
  }

  dispatch(type: string, detail?: unknown): void {
    const event = new CustomEvent(type, { detail })
    for (const listener of this.listeners.get(type) ?? []) listener(event)
  }

  listenerCount(type: string): number {
    return this.listeners.get(type)?.length ?? 0
  }
}

describe('AudioPlayerEventBridge', () => {
  it('attaches idempotently and detaches exact listeners', () => {
    const host = new EventHost()
    const player = {
      play: vi.fn(async () => undefined),
      stop: vi.fn(),
      enqueue: vi.fn(),
      enqueuePcm: vi.fn(),
    }
    const bridge = new AudioPlayerEventBridge(player)

    bridge.attach(host)
    bridge.attach(host)
    expect(host.listenerCount('pet:tts-play-url')).toBe(1)
    expect(host.listenerCount('pet:tts-play-pcm')).toBe(1)
    expect(host.listenerCount('pet:tts-stop')).toBe(1)

    bridge.detach(host)
    bridge.detach(host)
    expect(host.listenerCount('pet:tts-play-url')).toBe(0)
    expect(host.listenerCount('pet:tts-play-pcm')).toBe(0)
    expect(host.listenerCount('pet:tts-stop')).toBe(0)
  })

  it('routes one URL, PCM, and stop command to the player exactly once', () => {
    const host = new EventHost()
    const player = {
      play: vi.fn(async () => undefined),
      stop: vi.fn(),
      enqueue: vi.fn(),
      enqueuePcm: vi.fn(),
    }
    const bridge = new AudioPlayerEventBridge(player)
    bridge.attach(host)
    bridge.attach(host)

    const urlDetail = { audio_url: 'http://localhost/reply.wav', generationId: 'g1' }
    const pcmDetail = {
      audio: new Uint8Array([1, 2]),
      audioFormat: 'pcm_s16le' as const,
      sampleRate: 16_000,
      channels: 1,
      sampleWidthBytes: 2 as const,
    }
    host.dispatch('pet:tts-play-url', urlDetail)
    host.dispatch('pet:tts-play-pcm', pcmDetail)
    host.dispatch('pet:tts-stop', { interrupted: true })

    expect(player.enqueue).toHaveBeenCalledTimes(1)
    expect(player.enqueue).toHaveBeenCalledWith(urlDetail.audio_url, urlDetail)
    expect(player.enqueuePcm).toHaveBeenCalledTimes(1)
    expect(player.enqueuePcm).toHaveBeenCalledWith(pcmDetail)
    expect(player.stop).toHaveBeenCalledTimes(1)
    expect(player.stop).toHaveBeenCalledWith({ interrupted: true, petLipSyncHandled: false })

    bridge.detach(host)
    host.dispatch('pet:tts-play-url', urlDetail)
    expect(player.enqueue).toHaveBeenCalledTimes(1)
  })
})
