import { describe, expect, it } from 'vitest'
import { normalizeGenerationValue, resolveGenerationCapabilities } from './llm-generation-parameters'

describe('provider and model generation capabilities', () => {
  it('keeps remote provider sampling controls separate from local extensions', () => {
    const openai = resolveGenerationCapabilities('chatgpt', 'gpt-4o')
    expect(openai.parameters.temperature).toEqual({ min: 0, max: 2 })
    expect(openai.parameters.top_k).toBeUndefined()
    expect(openai.parameters.min_p).toBeUndefined()
    expect(resolveGenerationCapabilities('qwen', 'qwen-plus').parameters.presence_penalty).toBeDefined()
    expect(resolveGenerationCapabilities('qwen', 'qwen-plus').parameters.frequency_penalty).toBeUndefined()
    expect(resolveGenerationCapabilities('claude', 'claude-3-5-sonnet').parameters.temperature?.max).toBe(1)
  })
  it('offers reasoning and sampling only for the selected OpenAI model and effort', () => {
    const reasoning = resolveGenerationCapabilities('chatgpt', 'models/gpt-5.2', 'high')
    expect(reasoning.parameters.temperature).toBeUndefined()
    expect(reasoning.parameters.top_p).toBeUndefined()
    expect(reasoning.reasoningEfforts).toContain('none')
    expect(reasoning.outputTokenField).toBe('max_completion_tokens')
    expect(resolveGenerationCapabilities('chatgpt', 'gpt-5.2', 'none').parameters.temperature).toBeDefined()
    expect(resolveGenerationCapabilities('chatgpt', 'gpt-5-mini', 'none').parameters.temperature).toBeUndefined()
    expect(resolveGenerationCapabilities('chatgpt', 'gpt-6.1-sol').reasoningEfforts).not.toContain('none')
    expect(resolveGenerationCapabilities('chatgpt', 'gpt-6.1-sol', 'none').parameters.temperature).toBeUndefined()
  })
  it('resolves model reasoning fields without applying rules to another provider', () => {
    expect(resolveGenerationCapabilities('claude', 'claude-opus-4-6').reasoningTransport).toBe('claude_adaptive_effort')
    expect(resolveGenerationCapabilities('claude', 'claude-opus-4-6').reasoningEfforts).toContain('max')
    expect(resolveGenerationCapabilities('gemini', 'gemini-2.5-flash').reasoningEfforts).toContain('none')
    expect(resolveGenerationCapabilities('gemini', 'gemini-2.5-pro').reasoningEfforts).not.toContain('none')
    expect(resolveGenerationCapabilities('custom', 'gpt-5.2').reasoningEfforts).toEqual([])
    expect(resolveGenerationCapabilities('custom', 'gpt-5.2').parameters.temperature).toBeDefined()
  })
  it.each(['gpt-5.4', 'gpt-5.5', 'gpt-5.6', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna'])('matches current reasoning parameters for %s', (model) => {
    expect(resolveGenerationCapabilities('chatgpt', model, 'high').parameters).toEqual({})
    expect(resolveGenerationCapabilities('chatgpt', model, 'none').parameters.temperature).toBeDefined()
    expect(resolveGenerationCapabilities('chatgpt', model).reasoningEfforts).toContain('xhigh')
  })
  it('uses max only on documented families and keeps local reasoning provider-specific', () => {
    expect(resolveGenerationCapabilities('chatgpt', 'gpt-5.6-sol').reasoningEfforts).toContain('max')
    expect(resolveGenerationCapabilities('chatgpt', 'gpt-6.1-sol').reasoningEfforts).toContain('max')
    expect(resolveGenerationCapabilities('chatgpt', 'gpt-5.5').reasoningEfforts).not.toContain('max')
    expect(resolveGenerationCapabilities('chatgpt', 'gpt-5.3-codex').parameters).toEqual({})
    expect(resolveGenerationCapabilities('ollama', 'gpt-oss:20b').reasoningEfforts).toEqual(['none', 'low', 'medium', 'high'])
    expect(resolveGenerationCapabilities('ollama', 'unknown-local-model').reasoningEfforts).toEqual([])
  })
  it('never mutates the shared rules when switching providers, models or reasoning', () => {
    const previous = resolveGenerationCapabilities('chatgpt', 'gpt-5.2', 'none')
    previous.parameters.temperature!.max = 99
    delete previous.parameters.temperature
    previous.reasoningEfforts.length = 0
    resolveGenerationCapabilities('claude', 'claude-3-5-sonnet')
    expect(resolveGenerationCapabilities('chatgpt', 'gpt-5.2', 'none').parameters.temperature?.max).toBe(2)
    expect(resolveGenerationCapabilities('openai', 'GPT-5.2', 'high').reasoningEfforts).toContain('none')
    expect(resolveGenerationCapabilities('unknown', 'new-model').parameters.temperature).toBeDefined()
  })
  it('clamps values to the provider range including malformed numbers', () => {
    const range = resolveGenerationCapabilities('claude', 'claude-3-5-sonnet').parameters.temperature!
    expect(normalizeGenerationValue(1.8, range)).toBe(1)
    expect(normalizeGenerationValue(-2, range)).toBe(0)
    expect(normalizeGenerationValue(Number.NaN, range)).toBe(0)
  })
})
