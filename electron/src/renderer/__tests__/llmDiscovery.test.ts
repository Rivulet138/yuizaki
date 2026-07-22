import { describe, expect, it } from 'vitest'
import { isLocalLlmEndpoint, normalizeOpenAiBaseUrl, shouldAutoDiscoverLlmModels } from '../domains/settings/llmDiscovery'
import { LLM_PROVIDER_BASE_URLS, LLM_PROVIDER_ENDPOINTS, choosePreferredLlmModel, inferLlmProviderPreset } from '../domains/settings/llmProviders'

describe('LLM model discovery policy', () => {
  it('allows automatic discovery for local OpenAI-compatible endpoints', () => {
    expect(isLocalLlmEndpoint('http://127.0.0.1:11434/v1')).toBe(true)
    expect(isLocalLlmEndpoint('http://localhost:11434/v1')).toBe(true)
    expect(shouldAutoDiscoverLlmModels('http://127.0.0.1:11434/v1', '')).toBe(true)
  })

  it('skips automatic discovery for remote endpoints without an API key', () => {
    expect(isLocalLlmEndpoint('https://api.deepseek.com/v1')).toBe(false)
    expect(shouldAutoDiscoverLlmModels('https://api.deepseek.com/v1', '')).toBe(false)
  })

  it('allows automatic discovery for remote endpoints after a key is provided', () => {
    expect(shouldAutoDiscoverLlmModels('https://api.deepseek.com/v1', 'sk-test')).toBe(true)
  })

  it('normalizes copied OpenAI-compatible final endpoint URLs', () => {
    expect(normalizeOpenAiBaseUrl('https://api.example/v1/chat/completions')).toBe('https://api.example/v1')
    expect(normalizeOpenAiBaseUrl('https://api.example/v1/models/')).toBe('https://api.example/v1')
    expect(shouldAutoDiscoverLlmModels('http://127.0.0.1:11434/v1/chat/completions', '')).toBe(true)
  })

  it('exposes the configured provider switch presets', () => {
    expect(Object.keys(LLM_PROVIDER_BASE_URLS)).toEqual([
      'deepseek',
      'qwen',
      'gemini',
      'chatgpt',
      'claude',
      'grok',
      'ollama',
      'lmstudio',
      'custom',
    ])
    expect(LLM_PROVIDER_BASE_URLS.qwen).toBe('https://dashscope.aliyuncs.com/compatible-mode/v1')
    expect(LLM_PROVIDER_BASE_URLS.gemini).toBe('https://generativelanguage.googleapis.com/v1beta')
    expect(LLM_PROVIDER_BASE_URLS.grok).toBe('https://api.x.ai/v1')
    expect(LLM_PROVIDER_BASE_URLS.ollama).toBe('http://localhost:11434/v1')
    expect(LLM_PROVIDER_BASE_URLS.lmstudio).toBe('http://localhost:1234/v1')
    expect(LLM_PROVIDER_ENDPOINTS.claude.chatPath).toBe('/messages')
  })

  it('infers provider presets from OpenAI-compatible endpoints', () => {
    expect(inferLlmProviderPreset('https://api.deepseek.com/v1/chat/completions')).toBe('deepseek')
    expect(inferLlmProviderPreset('https://dashscope.aliyuncs.com/compatible-mode/v1/models')).toBe('qwen')
    expect(inferLlmProviderPreset('https://generativelanguage.googleapis.com/v1beta/openai')).toBe('gemini')
    expect(inferLlmProviderPreset('https://api.openai.com/v1')).toBe('chatgpt')
    expect(inferLlmProviderPreset('https://api.anthropic.com/v1')).toBe('claude')
    expect(inferLlmProviderPreset('https://api.x.ai/v1')).toBe('grok')
    expect(inferLlmProviderPreset('http://localhost:11434/v1/models')).toBe('ollama')
    expect(inferLlmProviderPreset('http://localhost:1234/v1/models')).toBe('lmstudio')
    expect(inferLlmProviderPreset('https://proxy.example/v1')).toBe('custom')
  })

  it('chooses provider-appropriate models from discovered lists', () => {
    expect(choosePreferredLlmModel(['qwen-turbo', 'qwen-max', 'qwen-plus'], 'qwen')).toBe('qwen-max')
    expect(choosePreferredLlmModel(['gemini-1.5-pro', 'gemini-2.5-flash'], 'gemini')).toBe('gemini-2.5-flash')
    expect(choosePreferredLlmModel(['gpt-4o-mini', 'gpt-5-mini'], 'chatgpt')).toBe('gpt-5-mini')
    expect(choosePreferredLlmModel(['claude-3-haiku', 'claude-sonnet-4-5'], 'claude')).toBe('claude-sonnet-4-5')
    expect(choosePreferredLlmModel(['grok-3-mini', 'grok-4'], 'grok')).toBe('grok-4')
    expect(choosePreferredLlmModel(['gemma3:latest', 'llama3.2:latest'], 'ollama')).toBe('llama3.2:latest')
    expect(choosePreferredLlmModel(['mistral-7b-instruct', 'gemma-3'], 'lmstudio')).toBe('mistral-7b-instruct')
  })
})
