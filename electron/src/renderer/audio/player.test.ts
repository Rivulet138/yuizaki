import { afterEach, describe, expect, it, vi } from 'vitest'
import { AudioPlayer, type PcmPlaybackDetail } from './player'

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
  constructor(type: string, readonly detail: T) {
    super(type)
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
})
