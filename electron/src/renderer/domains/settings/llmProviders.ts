import { normalizeOpenAiBaseUrl } from './llmDiscovery'

export type LlmProviderPreset = 'deepseek' | 'qwen' | 'gemini' | 'chatgpt' | 'claude' | 'grok' | 'ollama' | 'lmstudio' | 'custom'

export interface LlmProviderOption {
  label: string
  value: LlmProviderPreset
}

export interface LlmProviderEndpoints {
  baseUrl: string
  modelsPath: string
  chatPath: string
}

export const LLM_PROVIDER_BASE_URLS: Record<LlmProviderPreset, string> = {
  deepseek: 'https://api.deepseek.com/v1',
  qwen: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  gemini: 'https://generativelanguage.googleapis.com/v1beta/openai',
  chatgpt: 'https://api.openai.com/v1',
  claude: 'https://api.anthropic.com/v1',
  grok: 'https://api.x.ai/v1',
  ollama: 'http://localhost:11434/v1',
  lmstudio: 'http://localhost:1234/v1',
  custom: '',
}

export const LLM_PROVIDER_ENDPOINTS: Record<LlmProviderPreset, LlmProviderEndpoints> = {
  deepseek: { baseUrl: LLM_PROVIDER_BASE_URLS.deepseek, modelsPath: '/models', chatPath: '/chat/completions' },
  qwen: { baseUrl: LLM_PROVIDER_BASE_URLS.qwen, modelsPath: '/models', chatPath: '/chat/completions' },
  gemini: { baseUrl: LLM_PROVIDER_BASE_URLS.gemini, modelsPath: '/models', chatPath: '/chat/completions' },
  chatgpt: { baseUrl: LLM_PROVIDER_BASE_URLS.chatgpt, modelsPath: '/models', chatPath: '/chat/completions' },
  claude: { baseUrl: LLM_PROVIDER_BASE_URLS.claude, modelsPath: '/models', chatPath: '/messages' },
  grok: { baseUrl: LLM_PROVIDER_BASE_URLS.grok, modelsPath: '/models', chatPath: '/chat/completions' },
  ollama: { baseUrl: LLM_PROVIDER_BASE_URLS.ollama, modelsPath: '/models', chatPath: '/chat/completions' },
  lmstudio: { baseUrl: LLM_PROVIDER_BASE_URLS.lmstudio, modelsPath: '/models', chatPath: '/chat/completions' },
  custom: { baseUrl: '', modelsPath: '/models', chatPath: '/chat/completions' },
}

const preferredModelPatterns: Record<LlmProviderPreset, RegExp[]> = {
  deepseek: [/^deepseek-v\d.*flash/i, /^deepseek-v\d.*pro/i, /^deepseek-chat$/i, /^deepseek-reasoner$/i, /deepseek/i],
  qwen: [/^qwen-max/i, /^qwen-plus/i, /^qwen-turbo/i, /^qwen3\.?5/i, /^qwen3/i, /^qwen2\.?5/i, /^qwen/i],
  gemini: [/^gemini-3\.?5.*flash/i, /^gemini-3/i, /^gemini-2\.5/i, /^gemini-2\.0/i, /^gemini-1\.5/i, /^gemini/i],
  chatgpt: [/^gpt-5/i, /^gpt-4\.1/i, /^gpt-4o/i, /^gpt-4/i, /^o[134]($|-)/i, /^gpt-3\.5/i, /^chatgpt/i],
  claude: [/^claude-.*sonnet/i, /^claude-.*opus/i, /^claude-.*haiku/i, /^claude/i],
  grok: [/^grok-4/i, /^grok-3/i, /^grok/i],
  ollama: [/^llama3\.?3/i, /^llama3\.?2/i, /^llama3/i, /^qwen3/i, /^qwen2\.?5/i, /^mistral/i, /^gemma/i, /llama/i],
  lmstudio: [/^openai\/gpt-oss/i, /^llama/i, /^qwen/i, /^mistral/i, /^gemma/i, /^phi/i, /instruct/i],
  custom: [/chat/i, /gpt/i, /claude/i, /deepseek/i, /qwen/i, /gemini/i, /grok/i, /llama/i, /mistral/i],
}

export const getLlmProviderOptions = (customLabel: string): LlmProviderOption[] => [
  { label: 'DeepSeek', value: 'deepseek' },
  { label: 'Qwen', value: 'qwen' },
  { label: 'Gemini', value: 'gemini' },
  { label: 'ChatGPT', value: 'chatgpt' },
  { label: 'Claude', value: 'claude' },
  { label: 'Grok', value: 'grok' },
  { label: 'Ollama', value: 'ollama' },
  { label: 'LM Studio', value: 'lmstudio' },
  { label: customLabel, value: 'custom' },
]

export const inferLlmProviderPreset = (baseUrl: string): LlmProviderPreset => {
  const normalized = normalizeOpenAiBaseUrl(baseUrl).toLowerCase()
  if (!normalized) return 'custom'
  if (normalized.includes('deepseek.com')) return 'deepseek'
  if (normalized.includes('dashscope.aliyuncs.com') || normalized.includes('dashscope-intl.aliyuncs.com')) return 'qwen'
  if (normalized.includes('generativelanguage.googleapis.com')) return 'gemini'
  if (normalized.includes('api.openai.com')) return 'chatgpt'
  if (normalized.includes('api.anthropic.com') || normalized.includes('anthropic.com')) return 'claude'
  if (normalized.includes('api.x.ai') || normalized.includes('x.ai')) return 'grok'
  if (normalized.includes('localhost:11434') || normalized.includes('127.0.0.1:11434') || normalized.includes('[::1]:11434')) return 'ollama'
  if (normalized.includes('localhost:1234') || normalized.includes('127.0.0.1:1234') || normalized.includes('[::1]:1234')) return 'lmstudio'
  return 'custom'
}

export const choosePreferredLlmModel = (models: string[], preset: LlmProviderPreset): string => {
  if (!models.length) return ''
  const cleanModels = models.map((model) => model.trim()).filter(Boolean)
  const patterns = preferredModelPatterns[preset] || preferredModelPatterns.custom
  for (const pattern of patterns) {
    const match = cleanModels.find((model) => pattern.test(model))
    if (match) return match
  }
  return cleanModels[0] || ''
}
