import { describe, expect, it } from 'vitest'
import { migrateLegacyLlmDefaults } from './llmDiscovery'

describe('migrateLegacyLlmDefaults', () => {
  it('updates only values matching the previous built-in defaults', () => {
    expect(migrateLegacyLlmDefaults({
      model: 'gpt-6.1-sol',
      temperature: 1.2,
      top_p: 0.9,
      top_k: 500,
      frequency_penalty: 0.2,
      timeout: 60,
      context_max_tokens: 131072,
      default_max_output_tokens: 8192,
      presence_penalty: 0.25,
    })).toEqual({
      temperature: 1,
      top_p: 1,
      top_k: 0,
      frequency_penalty: 0,
      timeout: 120,
      context_max_tokens: 500000,
      default_max_output_tokens: 16384,
    })
  })

  it('leaves customized values intact', () => {
    expect(migrateLegacyLlmDefaults({
      temperature: 0.8,
      top_p: 0.95,
      top_k: 40,
      context_max_tokens: 24000,
    })).toEqual({})
  })

  it('does not migrate defaults for another model', () => {
    expect(migrateLegacyLlmDefaults({ model: 'gpt-4.1', temperature: 1.2, context_max_tokens: 131072 })).toEqual({})
  })
})
