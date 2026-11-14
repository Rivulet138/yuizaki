import { describe, expect, it } from 'vitest'
import { parseSettingInput, restoreLaterSettingsDraft, settingValueAt, snapshotSettingsDraft, unsentSettingsDraft } from './settingsDraft'

describe('normalized settings drafts', () => {
  it('protects unsent fields while allowing submitted fields to be normalized', () => {
    expect(unsentSettingsDraft(
      { summary: { trigger_messages: 24 }, asr: { base_url: '' } },
      { summary: { trigger_messages: 999 }, asr: { base_url: 'unsubmitted' } },
      { summary: { trigger_messages: 999 } },
    )).toEqual({ asr: { base_url: 'unsubmitted' } })
  })

  it('keeps normalized fields while protecting later nested edits and queued edits back to the original value', () => {
    const before = { llm: { timeout: 999, model: 'old' }, summary: { trigger_messages: 999 } }
    const current = snapshotSettingsDraft(before)
    current.llm.model = 'new'
    const normalized = { llm: { timeout: 120, model: 'old' }, summary: { trigger_messages: 100 } }
    restoreLaterSettingsDraft(normalized, before, current, { summary: { trigger_messages: 999 } })
    expect(normalized).toEqual({ llm: { timeout: 120, model: 'new' }, summary: { trigger_messages: 999 } })
  })

  it('preserves a credential cleared during a readback', () => {
    const normalized = { tts: { api_key: '********', timeout: 30 } }
    restoreLaterSettingsDraft(normalized, { tts: { api_key: 'old', timeout: 60 } }, { tts: { api_key: '', timeout: 60 } })
    expect(normalized).toEqual({ tts: { api_key: '', timeout: 30 } })
  })
})

describe('single setting input', () => {
  it('rejects malformed JSON and mismatched types without a string fallback', () => {
    expect(() => parseSettingInput('{broken', 'json', {})).toThrow(SyntaxError)
    expect(() => parseSettingInput('"42"', 'json', 42)).toThrow(TypeError)
    expect(() => parseSettingInput('42', 'string', 42)).toThrow(TypeError)
    expect(() => parseSettingInput('1e999', 'json', 42)).toThrow(TypeError)
  })

  it('preserves string whitespace and empty values and accepts typed JSON', () => {
    expect(parseSettingInput('  dark  ', 'string', 'light')).toBe('  dark  ')
    expect(parseSettingInput('', 'string', 'light')).toBe('')
    expect(parseSettingInput('42', 'json', 24)).toBe(42)
    expect(parseSettingInput('{"enabled":true}', 'json', {})).toEqual({ enabled: true })
    expect(settingValueAt({ summary: { trigger_messages: 24 } }, 'summary.trigger_messages')).toBe(24)
    expect(settingValueAt({}, 'toString')).toBeUndefined()
  })
})
