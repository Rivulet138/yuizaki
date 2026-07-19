import { describe, expect, it, vi } from 'vitest'
import type { SettingsResponse } from '../api/clients/settings-client'
import {
  buildCompanionTtsPatch,
  changedCompanionTtsPatch,
  syncCompanionVoiceSettings,
} from '../app/composables/companion-voice-settings'

const settingsWithTts = (tts: Partial<SettingsResponse['tts']>): SettingsResponse => ({
  llm: {} as SettingsResponse['llm'],
  tts: {
    genie_character: '', genie_model_dir: '', lang: 'zh',
    ref_audio: '', ref_text: '', device: 'cpu', quality: '', split: '', mode: '', save_mode: '',
    provider: 'genie-tts',
    ...tts,
  },
  asr: {} as SettingsResponse['asr'],
  svc: {} as SettingsResponse['svc'],
  summary: {} as SettingsResponse['summary'],
  system: {} as SettingsResponse['system'],
})

describe('companion voice settings reconciliation', () => {
  it('drops retired TTS fields from companion startup sync', () => {
    expect(buildCompanionTtsPatch({
      base_url: 'http://127.0.0.1:9880',
      speed: 1.2,
      volume: 2,
      timeout: 45,
      voice: 'legacy-voice',
    })).toEqual({})
  })

  it('keeps only supported and changed TTS fields', () => {
    const desired = buildCompanionTtsPatch({ lang: 'zh', ref_text: '你好', device: 'cuda' })

    expect(desired).toEqual({ lang: 'zh', ref_text: '你好' })
    expect(changedCompanionTtsPatch(desired, settingsWithTts({ lang: 'zh' }).tts)).toEqual({ ref_text: '你好' })
  })

  it('does not PATCH when the companion voice already matches runtime settings', async () => {
    const client = {
      load: vi.fn().mockResolvedValue(settingsWithTts({ lang: 'zh', ref_text: '你好' })),
      save: vi.fn(),
    }

    await expect(syncCompanionVoiceSettings(client, { lang: 'zh', ref_text: '你好' })).resolves.toBe(false)

    expect(client.load).toHaveBeenCalledOnce()
    expect(client.save).not.toHaveBeenCalled()
  })

  it('serializes duplicate startup syncs so only one PATCH is sent', async () => {
    let current = settingsWithTts({ lang: 'ja' })
    const client = {
      load: vi.fn(async () => current),
      save: vi.fn(async (patch: Record<string, unknown>) => {
        const tts = patch.tts as Partial<SettingsResponse['tts']>
        current = settingsWithTts({ ...current.tts, ...tts })
        return { status: 'success', runtime_applied: ['tts'] }
      }),
    }

    const results = await Promise.all([
      syncCompanionVoiceSettings(client, { lang: 'zh' }),
      syncCompanionVoiceSettings(client, { lang: 'zh' }),
    ])

    expect(results).toEqual([true, false])
    expect(client.load).toHaveBeenCalledTimes(2)
    expect(client.save).toHaveBeenCalledOnce()
    expect(client.save).toHaveBeenCalledWith({ tts: { lang: 'zh' } })
  })
})
