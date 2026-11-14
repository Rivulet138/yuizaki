import { afterEach, describe, expect, it, vi } from 'vitest'
import * as httpClient from '../api/clients/http-client'
import { AudioPlayer, getAudioPlayer, getAudioPlayerEventBridge, type PcmPlaybackDetail } from './player'

const audioElements: MockAudio[] = []

class MockAudio extends EventTarget {
  constructor() {
    super()
    audioElements.push(this)
  }
  src = ''
  currentTime = 0
  duration = 0
  play = vi.fn(async () => undefined)
  pause = vi.fn()
  load = vi.fn()
}

class MockCustomEvent<T> extends Event {
  readonly detail: T | undefined
  constructor(type: string, options?: CustomEventInit<T>) {
    super(type)
    this.detail = options?.detail
  }
}

describe('AudioPlayer PCM streaming', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('plays every PCM chunk when several chunks share one Genie sequence', async () => {
    audioElements.length = 0
    const windowTarget = Object.assign(new EventTarget(), { setTimeout, clearTimeout })
    vi.stubGlobal('Audio', MockAudio)
    vi.stubGlobal('window', windowTarget)
    vi.stubGlobal('CustomEvent', MockCustomEvent)
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:tts-chunk')
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)

    const player = new AudioPlayer()
    const audio = audioElements[0]!
    const baseDetail: Omit<PcmPlaybackDetail, 'audio'> = {
      version: 1,
      generationId: 'gen-1',
      sequence: 0,
      petLinkEnabled: false,
      audioFormat: 'pcm_s16le',
      sampleRate: 32_000,
      channels: 1,
      sampleWidthBytes: 2,
    }

    player.enqueuePcm({ ...baseDetail, audio: new Uint8Array(320) })
    await vi.waitFor(() => expect(audio.play).toHaveBeenCalledTimes(1))
    player.enqueuePcm({ ...baseDetail, audio: new Uint8Array(320) })

    audio.dispatchEvent(new Event('ended'))
    await vi.waitFor(() => expect(audio.play).toHaveBeenCalledTimes(2))
    player.stop()
  })

  it('waits for final stream completion while playback startup is pending', async () => {
    audioElements.length = 0
    const windowTarget = Object.assign(new EventTarget(), { setTimeout, clearTimeout })
    vi.stubGlobal('Audio', MockAudio)
    vi.stubGlobal('window', windowTarget)
    vi.stubGlobal('CustomEvent', MockCustomEvent)
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:tts-final')
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
    const ended = vi.fn()
    windowTarget.addEventListener('pet:audio-ended', ended)

    const player = new AudioPlayer()
    const audio = audioElements[0]!
    player.enqueuePcm({
      version: 1,
      generationId: 'gen-final',
      sequence: 0,
      petLinkEnabled: false,
      audioFormat: 'pcm_s16le',
      sampleRate: 32_000,
      channels: 1,
      sampleWidthBytes: 2,
      audio: new Uint8Array(320),
    })
    player.markTtsStreamComplete('gen-final')

    await vi.waitFor(() => expect(audio.play).toHaveBeenCalledTimes(1))
    audio.dispatchEvent(new Event('ended'))
    await vi.waitFor(() => expect(ended).toHaveBeenCalledTimes(1))
    player.stop()
  })
  it('delegates real bridge completion and closes a zero-audio generation only once', () => {
    const host = Object.assign(new EventTarget(), { setTimeout, clearTimeout })
    vi.stubGlobal('Audio', MockAudio)
    vi.stubGlobal('window', host)
    vi.stubGlobal('CustomEvent', MockCustomEvent)
    const ended = vi.fn()
    host.addEventListener('pet:audio-ended', ended)
    const bridge = getAudioPlayerEventBridge()
    bridge.attach(host)
    host.dispatchEvent(new CustomEvent('pet:tts-stream-complete', { detail: { generationId: 'zero-audio' } }))
    host.dispatchEvent(new CustomEvent('pet:tts-stream-complete', { detail: { generationId: 'zero-audio' } }))
    expect(ended).toHaveBeenCalledTimes(1)
    host.dispatchEvent(new CustomEvent('pet:tts-stream-complete', { detail: { generationId: 'next-zero-audio' } }))
    host.dispatchEvent(new CustomEvent('pet:tts-stream-complete', { detail: { generationId: 'next-zero-audio' } }))
    expect(ended).toHaveBeenCalledTimes(2)
    bridge.detach(host)
    getAudioPlayer().stop()
  })

  it('ignores completion for an interrupted or stale generation', async () => {
    const host = Object.assign(new EventTarget(), { setTimeout, clearTimeout })
    vi.stubGlobal('Audio', MockAudio)
    vi.stubGlobal('window', host)
    vi.stubGlobal('CustomEvent', MockCustomEvent)
    const ended = vi.fn()
    host.addEventListener('pet:audio-ended', ended)
    const player = new AudioPlayer()
    player.enqueue('data:audio/wav;base64,old', { version: 1, generationId: 'old', petLinkEnabled: false })
    await vi.waitFor(() => expect(player.isPlaying.value).toBe(true))
    player.stop()
    ended.mockClear()
    player.markTtsStreamComplete('old')
    expect(ended).not.toHaveBeenCalled()
    player.enqueue('data:audio/wav;base64,new', { version: 1, generationId: 'new', petLinkEnabled: false })
    await vi.waitFor(() => expect(player.isPlaying.value).toBe(true))
    player.markTtsStreamComplete('old')
    expect(ended).not.toHaveBeenCalled()
    player.markTtsStreamComplete('new')
    audioElements.at(-1)!.dispatchEvent(new Event('ended'))
    await vi.waitFor(() => expect(ended).toHaveBeenCalledTimes(1))
    player.markTtsStreamComplete('new')
    expect(ended).toHaveBeenCalledTimes(1)
  })

  it('ends a standalone URL exactly once after its media ended event', async () => {
    const host = Object.assign(new EventTarget(), { setTimeout, clearTimeout })
    vi.stubGlobal('Audio', MockAudio)
    vi.stubGlobal('window', host)
    vi.stubGlobal('CustomEvent', MockCustomEvent)
    const ended = vi.fn()
    host.addEventListener('pet:audio-ended', ended)
    const player = new AudioPlayer()
    await player.play('data:audio/wav;base64,standalone', { version: 1, generationId: 'standalone', petLinkEnabled: false })
    const audio = audioElements.at(-1)!
    const removeListener = vi.spyOn(audio, 'removeEventListener')
    audio.dispatchEvent(new Event('ended'))
    audio.dispatchEvent(new Event('ended'))
    expect(removeListener).toHaveBeenCalledWith('ended', expect.any(Function))
    expect(removeListener).toHaveBeenCalledWith('error', expect.any(Function))
    expect(ended).toHaveBeenCalledTimes(1)
    expect(ended.mock.calls[0]?.[0].detail.generationId).toBe('standalone')
    expect(player.isPlaying.value).toBe(false)
  })

  it('does not let an interrupted URL resolution finish a newer pending generation', async () => {
    const host = Object.assign(new EventTarget(), { setTimeout, clearTimeout })
    vi.stubGlobal('Audio', MockAudio)
    vi.stubGlobal('window', host)
    vi.stubGlobal('CustomEvent', MockCustomEvent)
    const ended = vi.fn()
    host.addEventListener('pet:audio-ended', ended)
    let releaseOld!: (url: string) => void
    let releaseNew!: (url: string) => void
    vi.spyOn(httpClient, 'resolveBackendUrl')
      .mockImplementationOnce(() => new Promise(resolve => { releaseOld = resolve }))
      .mockImplementationOnce(() => new Promise(resolve => { releaseNew = resolve }))
    const player = new AudioPlayer()
    player.enqueue('/old.wav', { version: 1, generationId: 'old', petLinkEnabled: false })
    player.stop()
    ended.mockClear()
    player.enqueue('/new.wav', { version: 1, generationId: 'new', petLinkEnabled: false })
    player.markTtsStreamComplete('new')
    releaseOld('data:audio/wav;base64,old')
    for (let index = 0; index < 8; index += 1) await Promise.resolve()
    expect(ended).not.toHaveBeenCalled()
    releaseNew('data:audio/wav;base64,new')
    await vi.waitFor(() => expect(player.isPlaying.value).toBe(true))
    audioElements.at(-1)!.dispatchEvent(new Event('ended'))
    expect(ended).toHaveBeenCalledTimes(1)
    expect(ended.mock.calls[0]?.[0].detail.generationId).toBe('new')
  })

})
