import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchSettings, saveSettings, useSettingsStore } from '../state/settingsStore'
import { settingsClient } from '../api/client'
import type { SettingsMutationResponse, SettingsResponse } from '../api/clients/settings-client'
import { DEFAULT_VAD_MIN_SILENCE_MS } from '../../shared/runtime-defaults'

vi.mock('../api/client', () => ({
  settingsClient: {
    load: vi.fn(),
    save: vi.fn(),
    testLlm: vi.fn(),
    testTts: vi.fn(),
    warmupTts: vi.fn(),
  },
}))

const mockedSettingsClient = vi.mocked(settingsClient)

const mutationOk: SettingsMutationResponse = { status: 'success' }

describe('settingsStore', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('uses the backend VAD endpoint default before settings load', () => {
    const { state } = useSettingsStore()
    expect(DEFAULT_VAD_MIN_SILENCE_MS).toBe(300)
    expect(state.asr.vad_min_silence_ms).toBe(DEFAULT_VAD_MIN_SILENCE_MS)
  })

  it('should merge fetched settings into state', async () => {
    mockedSettingsClient.load.mockResolvedValue({
      llm: { provider: 'custom', base_url: 'http://test', api_key: 'k', model: 'm', timeout: 60 },
    } as SettingsResponse)

    await fetchSettings()

    const { state } = useSettingsStore()
    expect(state.llm.base_url).toBe('http://test')
    expect(state.llm.model).toBe('m')
  })

  it('should merge saved settings into local state', async () => {
    mockedSettingsClient.save.mockResolvedValue(mutationOk)

    await saveSettings({
      summary: {
        trigger_messages: 99,
        keep_recent_messages: 8,
        item_max_chars: 140,
        rewrite_interval_messages: 6,
        quality_scorer_mode: 'rule',
        quality_score_cooldown_seconds: 300,
        quality_score_budget_per_hour: 20,
      },
    })

    const { state } = useSettingsStore()
    expect(state.summary.trigger_messages).toBe(99)
  })

  it('preserves the selected TTS provider when saving nested settings', async () => {
    mockedSettingsClient.save.mockResolvedValue({ status: 'success', runtime_applied: ['tts'] })

    await saveSettings({
      tts: {
        genie_character: 'feibi',
        genie_model_dir: '',
        ref_audio: '',
        ref_text: '',
        lang: 'zh',
        device: 'cpu',
        quality: '质量优先',
        split: '智能切分',
        mode: '串行推理',
        save_mode: '禁用自动保存',
        provider: 'openai-compatible',
      },
    })

    const { state } = useSettingsStore()
    expect(mockedSettingsClient.save).toHaveBeenCalledWith(expect.objectContaining({
      tts: expect.objectContaining({
        provider: 'openai-compatible',
      }),
    }))
    expect(state.tts.provider).toBe('openai-compatible')
  })

  it('preserves the backend TTS provider when loading settings', async () => {
    mockedSettingsClient.load.mockResolvedValue({
      tts: { provider: 'openai-compatible', model: 'gpt-4o-mini-tts', voice: 'alloy' },
    } as SettingsResponse)

    await fetchSettings()

    expect(useSettingsStore().state.tts.provider).toBe('openai-compatible')
  })
})
