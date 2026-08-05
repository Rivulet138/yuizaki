import { describe, expect, it } from 'vitest'

import {
  assertE2E02LipSyncObservations,
  createE2E02LipSyncAudit,
  findFatalRendererConsoleEntries,
} from '../e2e-test-mode'

describe('Electron E2E renderer evidence gates', () => {
  it('treats the legacy invalid lip-sync URL error as fatal', () => {
    const entries = [{
      source: 'panel' as const,
      level: 0,
      message: '[AudioPlayer] failed to start pet lip sync: Error: Invalid lip sync audio URL',
    }]

    expect(findFatalRendererConsoleEntries('E2E-02', entries)).toEqual(entries)
  })

  it('fails uncaught, unhandled, failed-to, and console error entries without broad ignores', () => {
    const entries = [
      { source: 'panel' as const, level: 1, message: 'Uncaught TypeError: broken' },
      { source: 'panel' as const, level: 1, message: 'Unhandled Promise Rejection: broken' },
      { source: 'live2d' as const, level: 0, message: 'failed to initialize production runtime' },
      { source: 'panel' as const, level: 3, message: 'explicit console error' },
    ]

    expect(findFatalRendererConsoleEntries('E2E-02', entries)).toEqual(entries)
    expect(findFatalRendererConsoleEntries('E2E-02', [
      { source: 'panel', level: 2, message: '[SocketIO] reconnect scheduled' },
    ])).toEqual([])
  })

  it('treats model loading failures as fatal in every case', () => {
    const knownEntry = {
      source: 'live2d' as const,
      level: 3,
      message: '[PetRenderer] failed to load VRM model: TypeError: Failed to fetch',
    }

    expect(findFatalRendererConsoleEntries('E2E-05', [knownEntry])).toEqual([knownEntry])
    expect(findFatalRendererConsoleEntries('E2E-02', [knownEntry])).toEqual([knownEntry])
  })

  it('accepts bounded fixture URLs with observable lip-sync starts and stops', () => {
    const origin = 'http://127.0.0.1:43210'
    const token = 'run-token'
    const audioUrl = `${origin}/audio.wav?token=${token}`

    expect(() => assertE2E02LipSyncObservations([
      { event: 'onSpeechStart', payload: { audioUrl } },
      { event: 'onSpeechEnd', payload: { interrupted: false } },
      { event: 'onSpeechStart', payload: { audioUrl } },
      { event: 'onSpeechEnd', payload: { interrupted: true } },
    ], origin, token)).not.toThrow()
  })

  it('rejects arbitrary lip-sync asset URLs', () => {
    expect(() => assertE2E02LipSyncObservations([
      { event: 'onSpeechStart', payload: { audioUrl: 'https://example.test/audio.wav' } },
      { event: 'onSpeechEnd', payload: {} },
      { event: 'onSpeechStart', payload: { audioUrl: 'https://example.test/audio.wav' } },
      { event: 'onSpeechEnd', payload: {} },
    ], 'http://127.0.0.1:43210', 'run-token')).toThrow(/origin/i)
  })

  it('rejects a wrong run token without echoing either token in the error', () => {
    const expectedToken = 'expected-secret-token'
    const actualToken = 'actual-secret-token'
    let message = ''
    try {
      assertE2E02LipSyncObservations([
        { event: 'onSpeechStart', payload: { audioUrl: `http://127.0.0.1:43210/audio.wav?token=${actualToken}` } },
        { event: 'onSpeechEnd', payload: {} },
        { event: 'onSpeechStart', payload: { audioUrl: `http://127.0.0.1:43210/audio.wav?token=${actualToken}` } },
        { event: 'onSpeechEnd', payload: {} },
      ], 'http://127.0.0.1:43210', expectedToken)
    } catch (error) {
      message = error instanceof Error ? error.stack || error.message : String(error)
    }

    expect(message).toContain('lip-sync audio URL token did not match the run')
    expect(message).not.toContain(expectedToken)
    expect(message).not.toContain(actualToken)
  })

  it('creates an exact lip-sync audit without exposing the run token', () => {
    const token = 'fixture-secret-token'
    const audioUrl = `http://127.0.0.1:43123/audio.wav?token=${token}`
    const audit = createE2E02LipSyncAudit([
      { event: 'onSpeechStart', payload: { audioUrl } },
      { event: 'onSpeechEnd', payload: { interrupted: false } },
      { event: 'onSpeechStart', payload: { audioUrl } },
      { event: 'onSpeechEnd', payload: { interrupted: true } },
    ], 'http://127.0.0.1:43123', token, 'token-sha256')

    expect(audit).toEqual({
      start_count: 2,
      end_count: 2,
      starts: [
        { audio_url: 'http://127.0.0.1:43123/audio.wav?token=[redacted]', token_hash: 'token-sha256' },
        { audio_url: 'http://127.0.0.1:43123/audio.wav?token=[redacted]', token_hash: 'token-sha256' },
      ],
      ends: [{ interrupted: false }, { interrupted: true }],
    })
    expect(JSON.stringify(audit)).not.toContain(token)
  })
})
