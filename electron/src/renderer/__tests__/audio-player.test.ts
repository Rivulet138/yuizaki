import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const petControlMocks = vi.hoisted(() => ({
  startLipSync: vi.fn(),
  stopLipSync: vi.fn(),
}))

const httpClientMocks = vi.hoisted(() => ({
  resolveBackendUrl: vi.fn((pathOrUrl: string) => Promise.resolve(`http://localhost:8001${pathOrUrl.startsWith('/') ? pathOrUrl : `/${pathOrUrl}`}`)),
}))

const setTtsLipSyncMock = vi.fn()
const setTtsVisemeMock = vi.fn()

vi.mock('../utils/petControl', () => ({
  petControl: petControlMocks,
}))

vi.mock('../api/clients/http-client', () => httpClientMocks)

type AudioEventName = 'ended' | 'error'

class MockAudioElement {
  static instances: MockAudioElement[] = []

  src = ''
  currentTime = 0
  duration = 2.4
  readonly play = vi.fn(() => Promise.resolve())
  readonly pause = vi.fn()
  private readonly listeners = new Map<AudioEventName, Array<() => void>>()

  constructor() {
    MockAudioElement.instances.push(this)
  }

  addEventListener(event: AudioEventName, handler: () => void): void {
    const handlers = this.listeners.get(event) ?? []
    handlers.push(handler)
    this.listeners.set(event, handlers)
  }

  removeEventListener(event: AudioEventName, handler: () => void): void {
    const handlers = this.listeners.get(event) ?? []
    this.listeners.set(event, handlers.filter((candidate) => candidate !== handler))
  }

  emit(event: AudioEventName): void {
    for (const handler of this.listeners.get(event) ?? []) {
      handler()
    }
  }
}

const flushAsyncPlayback = async () => {
  for (let i = 0; i < 10; i += 1) {
    await Promise.resolve()
  }
}

describe('AudioPlayer sentence emotion forwarding', () => {
  beforeEach(() => {
    vi.resetModules()
    MockAudioElement.instances = []
    petControlMocks.startLipSync.mockClear()
    petControlMocks.stopLipSync.mockClear()
    petControlMocks.startLipSync.mockResolvedValue(undefined)
    petControlMocks.stopLipSync.mockResolvedValue(undefined)
    httpClientMocks.resolveBackendUrl.mockReset()
    httpClientMocks.resolveBackendUrl.mockImplementation((pathOrUrl: string) => Promise.resolve(`http://localhost:8001${pathOrUrl.startsWith('/') ? pathOrUrl : `/${pathOrUrl}`}`))
    vi.stubGlobal('Audio', MockAudioElement)
    vi.stubGlobal('petApi', {
      pet: {
        setTtsLipSync: setTtsLipSyncMock,
        setTtsViseme: setTtsVisemeMock,
      },
    })
    setTtsLipSyncMock.mockClear()
    setTtsVisemeMock.mockClear()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('forwards sentence cues on tts playback start and emits audio-ended on end/stop', async () => {
    await import('../audio/player')
    const startedDetails: unknown[] = []
    const endedListener = vi.fn()
    const onStarted = (event: Event) => {
      startedDetails.push((event as CustomEvent<unknown>).detail)
    }
    window.addEventListener('pet:audio-started', onStarted)
    window.addEventListener('pet:audio-ended', endedListener)

    try {
      window.dispatchEvent(
        new CustomEvent('pet:tts-play-url', {
          detail: {
            audio_url: '/audio/reply.wav',
            text: '第一句。第二句。',
            sentenceEmotionCues: [{ sentenceIndex: 1, emotionId: 'happy' }],
          },
        }),
      )
      await flushAsyncPlayback()

      expect(MockAudioElement.instances).toHaveLength(1)
      expect(MockAudioElement.instances[0]?.play).toHaveBeenCalledTimes(1)
      expect(petControlMocks.startLipSync).toHaveBeenCalledWith(
        'http://localhost:8001/audio/reply.wav',
        expect.objectContaining({ source: 'automation', signal: expect.any(AbortSignal) }),
      )
      expect(startedDetails).toEqual([
        {
          audio_url: 'http://localhost:8001/audio/reply.wav',
          text: '第一句。第二句。',
          sentenceEmotionCues: [{ sentenceIndex: 1, emotionId: 'happy' }],
          durationMs: 2400,
        },
      ])

      MockAudioElement.instances[0]?.emit('ended')
      await Promise.resolve()
      expect(endedListener).toHaveBeenCalledTimes(1)
      expect(petControlMocks.stopLipSync).toHaveBeenCalledTimes(1)
      expect(petControlMocks.stopLipSync.mock.calls[0]).toEqual([])

      window.dispatchEvent(new CustomEvent('pet:tts-stop'))
      await Promise.resolve()
      expect(MockAudioElement.instances[0]?.pause).toHaveBeenCalledTimes(1)
      expect(MockAudioElement.instances[0]?.currentTime).toBe(0)
      expect(endedListener).toHaveBeenCalledTimes(2)
      expect(petControlMocks.stopLipSync).toHaveBeenCalledTimes(1)
    } finally {
      window.removeEventListener('pet:audio-started', onStarted)
      window.removeEventListener('pet:audio-ended', endedListener)
    }
  })

  it('forwards interrupted stop options to pet lip sync', async () => {
    const { AudioPlayer } = await import('../audio/player')
    const player = new AudioPlayer()

    await player.play('/audio/reply.wav')
    await flushAsyncPlayback()

    player.stop({ interrupted: true })
    await Promise.resolve()

    expect(petControlMocks.stopLipSync).toHaveBeenCalledTimes(1)
    expect(petControlMocks.stopLipSync).toHaveBeenCalledWith({ interrupted: true })
  })

  it('does not duplicate pet lip sync stops when another layer handled them', async () => {
    const { AudioPlayer } = await import('../audio/player')
    const player = new AudioPlayer()

    await player.play('/audio/reply.wav')
    await flushAsyncPlayback()

    player.stop({
      interrupted: true,
      petLipSyncHandled: true,
    })
    await Promise.resolve()

    expect(MockAudioElement.instances[0]?.pause).toHaveBeenCalledTimes(1)
    expect(petControlMocks.stopLipSync).not.toHaveBeenCalled()
  })

  it('plays TTS without lip sync or sentence cues when pet linkage is disabled', async () => {
    const { AudioPlayer } = await import('../audio/player')
    const startedDetails: unknown[] = []
    const onStarted = (event: Event) => {
      startedDetails.push((event as CustomEvent<unknown>).detail)
    }
    window.addEventListener('pet:audio-started', onStarted)

    try {
      const player = new AudioPlayer()
      await player.play('/audio/reply.wav', {
        text: '第一句。',
        sentenceEmotionCues: [{ sentenceIndex: 0, emotionId: 'happy' }],
        petLinkEnabled: false,
      })
      await Promise.resolve()

      expect(MockAudioElement.instances).toHaveLength(1)
      expect(MockAudioElement.instances[0]?.play).toHaveBeenCalledTimes(1)
      expect(petControlMocks.startLipSync).not.toHaveBeenCalled()
      expect(startedDetails).toEqual([
        {
          audio_url: 'http://localhost:8001/audio/reply.wav',
          text: '第一句。',
          durationMs: 2400,
          petLinkEnabled: false,
        },
      ])

      MockAudioElement.instances[0]?.emit('ended')
      await Promise.resolve()
      expect(petControlMocks.stopLipSync).not.toHaveBeenCalled()
    } finally {
      window.removeEventListener('pet:audio-started', onStarted)
    }
  })

  it('ignores local file playback URLs', async () => {
    const { AudioPlayer } = await import('../audio/player')
    const startedListener = vi.fn()
    window.addEventListener('pet:audio-started', startedListener)

    try {
      const player = new AudioPlayer()
      await player.play('file:///tmp/reply.wav')
      await Promise.resolve()

      expect(MockAudioElement.instances[0]?.play).not.toHaveBeenCalled()
      expect(petControlMocks.startLipSync).not.toHaveBeenCalled()
      expect(startedListener).not.toHaveBeenCalled()
    } finally {
      window.removeEventListener('pet:audio-started', startedListener)
    }
  })

  it('normalizes backend-relative audio URLs before playback and lip sync', async () => {
    const { AudioPlayer } = await import('../audio/player')
    const startedDetails: unknown[] = []
    const onStarted = (event: Event) => {
      startedDetails.push((event as CustomEvent<unknown>).detail)
    }
    window.addEventListener('pet:audio-started', onStarted)

    try {
      const player = new AudioPlayer()
      await player.play('/audio/reply.wav')
      await Promise.resolve()

      expect(MockAudioElement.instances[0]?.src).toBe('http://localhost:8001/audio/reply.wav')
      expect(httpClientMocks.resolveBackendUrl).toHaveBeenCalledWith('/audio/reply.wav')
      expect(petControlMocks.startLipSync).toHaveBeenCalledWith(
        'http://localhost:8001/audio/reply.wav',
        expect.objectContaining({ source: 'automation', signal: expect.any(AbortSignal) }),
      )
      expect(startedDetails).toEqual([
        {
          audio_url: 'http://localhost:8001/audio/reply.wav',
          durationMs: 2400,
        },
      ])
    } finally {
      window.removeEventListener('pet:audio-started', onStarted)
    }
  })

  it('uses the runtime backend origin for backend-relative audio URLs', async () => {
    httpClientMocks.resolveBackendUrl.mockResolvedValue('http://localhost:8011/audio/reply.wav')
    const { AudioPlayer } = await import('../audio/player')

    const player = new AudioPlayer()
    await player.play('/audio/reply.wav')
    await Promise.resolve()

    expect(httpClientMocks.resolveBackendUrl).toHaveBeenCalledWith('/audio/reply.wav')
    expect(MockAudioElement.instances[0]?.src).toBe('http://localhost:8011/audio/reply.wav')
    expect(petControlMocks.startLipSync).toHaveBeenCalledWith(
      'http://localhost:8011/audio/reply.wav',
      expect.objectContaining({ source: 'automation', signal: expect.any(AbortSignal) }),
    )
  })

  it('waits for URL lip sync startup before announcing audio playback', async () => {
    let resolveLipSync: (() => void) | undefined
    petControlMocks.startLipSync.mockImplementationOnce(() => new Promise<void>((resolve) => {
      resolveLipSync = resolve
    }))
    const { AudioPlayer } = await import('../audio/player')
    const startedListener = vi.fn()
    window.addEventListener('pet:audio-started', startedListener)

    try {
      const player = new AudioPlayer()
      const playback = player.play('/audio/reply.wav')
      await flushAsyncPlayback()

      expect(petControlMocks.startLipSync).toHaveBeenCalledTimes(1)
      expect(MockAudioElement.instances[0]?.play).not.toHaveBeenCalled()
      expect(startedListener).not.toHaveBeenCalled()

      resolveLipSync?.()
      await playback
      expect(MockAudioElement.instances[0]?.play).toHaveBeenCalledTimes(1)
      expect(startedListener).toHaveBeenCalledTimes(1)
    } finally {
      window.removeEventListener('pet:audio-started', startedListener)
    }
  })

  it('cancels a pending URL lip sync startup when playback is interrupted', async () => {
    let resolveLipSync: (() => void) | undefined
    petControlMocks.startLipSync.mockImplementationOnce(() => new Promise<void>((resolve) => {
      resolveLipSync = resolve
    }))
    const { AudioPlayer } = await import('../audio/player')
    const startedListener = vi.fn()
    window.addEventListener('pet:audio-started', startedListener)

    try {
      const player = new AudioPlayer()
      const playback = player.play('/audio/reply.wav')
      await flushAsyncPlayback()
      player.stop({ interrupted: true })
      resolveLipSync?.()
      await playback

      expect(startedListener).not.toHaveBeenCalled()
      expect(petControlMocks.stopLipSync).toHaveBeenCalledWith({ interrupted: true })
      expect(petControlMocks.startLipSync.mock.calls[0]?.[1]?.signal.aborted).toBe(true)
    } finally {
      window.removeEventListener('pet:audio-started', startedListener)
    }
  })

  it('plays queued TTS segments in order and emits one final ended event', async () => {
    const { AudioPlayer } = await import('../audio/player')
    const endedListener = vi.fn()
    window.addEventListener('pet:audio-ended', endedListener)

    try {
      const player = new AudioPlayer()
      player.enqueue('/audio/segment-0.wav', { sequence: 0, isFinal: false })
      player.enqueue('/audio/segment-1.wav', { sequence: 1, isFinal: true })
      await flushAsyncPlayback()

      const audio = MockAudioElement.instances[0]
      expect(audio?.play).toHaveBeenCalledTimes(1)
      expect(audio?.src).toBe('http://localhost:8001/audio/segment-0.wav')

      audio?.emit('ended')
      await flushAsyncPlayback()
      expect(audio?.play).toHaveBeenCalledTimes(2)
      expect(audio?.src).toBe('http://localhost:8001/audio/segment-1.wav')
      expect(endedListener).not.toHaveBeenCalled()

      audio?.emit('ended')
      await Promise.resolve()
      expect(endedListener).toHaveBeenCalledTimes(1)
    } finally {
      window.removeEventListener('pet:audio-ended', endedListener)
    }
  })

  it('reorders sequenced TTS segments that arrive out of order', async () => {
    const { AudioPlayer } = await import('../audio/player')
    const player = new AudioPlayer()
    player.enqueue('/audio/segment-1.wav', { generationId: 'g1', sequence: 1, isFinal: true })
    await flushAsyncPlayback()
    expect(MockAudioElement.instances[0]?.play).not.toHaveBeenCalled()

    player.enqueue('/audio/segment-0.wav', { generationId: 'g1', sequence: 0, isFinal: false })
    await flushAsyncPlayback()
    const audio = MockAudioElement.instances[0]
    expect(audio?.src).toBe('http://localhost:8001/audio/segment-0.wav')
    audio?.emit('ended')
    await flushAsyncPlayback()
    expect(audio?.src).toBe('http://localhost:8001/audio/segment-1.wav')
  })

  it('drops a duplicate segment after its sequence was already consumed', async () => {
    const { AudioPlayer } = await import('../audio/player')
    const player = new AudioPlayer()
    player.enqueue('/audio/segment-0.wav', { generationId: 'g-consumed', sequence: 0 })
    await flushAsyncPlayback()

    player.enqueue('/audio/duplicate-0.wav', { generationId: 'g-consumed', sequence: 0 })
    MockAudioElement.instances[0]?.emit('ended')
    await flushAsyncPlayback()

    expect(MockAudioElement.instances[0]?.play).toHaveBeenCalledTimes(1)
    expect(httpClientMocks.resolveBackendUrl).not.toHaveBeenCalledWith('/audio/duplicate-0.wav')
  })

  it('flushes an incomplete final sequence instead of deadlocking playback', async () => {
    vi.useFakeTimers()
    const { AudioPlayer } = await import('../audio/player')
    try {
      const player = new AudioPlayer()
      player.enqueue('/audio/segment-2.wav', { generationId: 'g2', sequence: 2, isFinal: true })
      await flushAsyncPlayback()
      vi.advanceTimersByTime(250)
      await flushAsyncPlayback()
      const audio = MockAudioElement.instances[0]
      expect(audio?.src).toBe('http://localhost:8001/audio/segment-2.wav')
    } finally {
      vi.useRealTimers()
    }
  })

  it('plays streamed PCM from memory and releases the object URL after playback', async () => {
    const createObjectURL = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:tts-pcm-1')
    const revokeObjectURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
    const { AudioPlayer } = await import('../audio/player')
    const startedDetails: unknown[] = []
    const onStarted = (event: Event) => startedDetails.push((event as CustomEvent<unknown>).detail)
    window.addEventListener('pet:audio-started', onStarted)

    try {
      const player = new AudioPlayer()
      player.enqueuePcm({
        audio: new Uint8Array(6_400),
        audioFormat: 'pcm_s16le',
        sampleRate: 32_000,
        channels: 1,
        sampleWidthBytes: 2,
        generationId: 'generation-pcm',
        sequence: 0,
      })
      await flushAsyncPlayback()

      expect(createObjectURL).toHaveBeenCalledWith(expect.any(Blob))
      const wav = createObjectURL.mock.calls[0]?.[0] as Blob
      const wavBytes = new Uint8Array(await wav.arrayBuffer())
      expect(new TextDecoder().decode(wavBytes.slice(0, 4))).toBe('RIFF')
      expect(wavBytes.byteLength).toBe(6_444)
      expect(MockAudioElement.instances[0]?.src).toBe('blob:tts-pcm-1')
      expect(httpClientMocks.resolveBackendUrl).not.toHaveBeenCalledWith('blob:tts-pcm-1')
      expect(startedDetails).toEqual([expect.objectContaining({
        audio_url: 'blob:tts-pcm-1',
        durationMs: 100,
        generationId: 'generation-pcm',
        sequence: 0,
      })])
      expect(petControlMocks.startLipSync).not.toHaveBeenCalled()
      expect(setTtsLipSyncMock).toHaveBeenCalledWith(0, true)

      MockAudioElement.instances[0]?.emit('ended')
      await Promise.resolve()
      expect(revokeObjectURL).toHaveBeenCalledWith('blob:tts-pcm-1')
      expect(setTtsLipSyncMock).toHaveBeenLastCalledWith(0, false)
      expect(petControlMocks.stopLipSync).not.toHaveBeenCalled()
    } finally {
      window.removeEventListener('pet:audio-started', onStarted)
    }
  })

  it('revokes a PCM object URL when its sequence is older than the playback cursor', async () => {
    const createObjectURL = vi.spyOn(URL, 'createObjectURL')
      .mockReturnValueOnce('blob:tts-pcm-current')
      .mockReturnValueOnce('blob:tts-pcm-stale')
    const revokeObjectURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
    const { AudioPlayer } = await import('../audio/player')
    const player = new AudioPlayer()
    const pcm = {
      audio: new Uint8Array(6_400),
      audioFormat: 'pcm_s16le' as const,
      sampleRate: 32_000,
      channels: 1,
      sampleWidthBytes: 2 as const,
      generationId: 'generation-pcm-stale',
      sequence: 0,
    }

    player.enqueuePcm(pcm)
    await flushAsyncPlayback()
    player.enqueuePcm(pcm)

    expect(createObjectURL).toHaveBeenCalledTimes(2)
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:tts-pcm-stale')
    expect(MockAudioElement.instances[0]?.play).toHaveBeenCalledTimes(1)
  })

  it('builds raw PCM RMS frames and follows the audio playback clock', async () => {
    vi.useFakeTimers()
    const sampleRate = 8_000
    const samplesPerFrame = Math.round(sampleRate * 33 / 1_000)
    const pcm = new Uint8Array(samplesPerFrame * 2 * 2)
    const view = new DataView(pcm.buffer)
    for (let sample = samplesPerFrame; sample < samplesPerFrame * 2; sample += 1) {
      view.setInt16(sample * 2, 16_384, true)
    }
    const createObjectURL = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:tts-pcm-envelope')
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
    const { AudioPlayer, buildPcmS16leEnvelope } = await import('../audio/player')

    const envelope = buildPcmS16leEnvelope(pcm, sampleRate, 1)
    expect(envelope.frameDurationMs).toBe(33)
    expect(envelope.levels).toHaveLength(2)
    expect(envelope.levels[0]).toBe(0)
    expect(envelope.levels[1]).toBeCloseTo(0.5, 4)

    const player = new AudioPlayer()
    player.enqueuePcm({
      audio: pcm,
      audioFormat: 'pcm_s16le',
      sampleRate,
      channels: 1,
      sampleWidthBytes: 2,
      visemeCues: [
        { viseme: 'aa', offsetMs: 0 },
        { viseme: 'ih', offsetMs: 33, weight: 0.8 },
      ],
    })
    await flushAsyncPlayback()
    expect(createObjectURL).toHaveBeenCalledOnce()
    expect(setTtsLipSyncMock).toHaveBeenLastCalledWith(0, true)
    expect(setTtsVisemeMock).toHaveBeenLastCalledWith('aa', 1, true)

    const audio = MockAudioElement.instances[0]
    if (audio) audio.currentTime = 0.04
    await vi.advanceTimersByTimeAsync(33)
    expect(setTtsLipSyncMock).toHaveBeenLastCalledWith(expect.closeTo(0.5, 4), true)
    expect(setTtsVisemeMock).toHaveBeenLastCalledWith('ih', 0.8, true)

    player.stop({ interrupted: true })
    expect(setTtsLipSyncMock).toHaveBeenLastCalledWith(0, false)
    expect(setTtsVisemeMock).toHaveBeenLastCalledWith('sil', 0, false)
    expect(petControlMocks.stopLipSync).not.toHaveBeenCalled()
    vi.useRealTimers()
  })

  it('releases queued PCM object URLs when interrupted', async () => {
    const createObjectURL = vi.spyOn(URL, 'createObjectURL')
      .mockReturnValueOnce('blob:tts-pcm-current')
      .mockReturnValueOnce('blob:tts-pcm-queued')
    const revokeObjectURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
    const { AudioPlayer } = await import('../audio/player')
    const player = new AudioPlayer()
    const base = {
      audio: new Uint8Array(6_400),
      audioFormat: 'pcm_s16le' as const,
      sampleRate: 32_000,
      channels: 1,
      sampleWidthBytes: 2 as const,
    }

    player.enqueuePcm(base)
    player.enqueuePcm(base)
    await flushAsyncPlayback()
    player.stop({ interrupted: true })

    expect(createObjectURL).toHaveBeenCalledTimes(2)
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:tts-pcm-current')
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:tts-pcm-queued')
  })

  it('clears queued segments when interrupted', async () => {
    const { AudioPlayer } = await import('../audio/player')
    const player = new AudioPlayer()
    player.enqueue('/audio/segment-0.wav')
    player.enqueue('/audio/segment-1.wav')
    await flushAsyncPlayback()

    const audio = MockAudioElement.instances[0]
    player.stop({ interrupted: true })
    audio?.emit('ended')
    await flushAsyncPlayback()

    expect(audio?.play).toHaveBeenCalledTimes(1)
    expect(petControlMocks.stopLipSync).toHaveBeenCalledWith({ interrupted: true })
  })
})
