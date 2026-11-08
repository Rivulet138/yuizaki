export const isLocalLlmEndpoint = (value: string): boolean => {
  try {
    const parsed = new URL(value)
    return ['localhost', '127.0.0.1', '::1'].includes(parsed.hostname)
  } catch {
    return false
  }
}

export const normalizeOpenAiBaseUrl = (value: string): string => {
  let normalized = value.trim().replace(/\/+$/, '')
  for (const suffix of ['/chat/completions', '/models']) {
    if (normalized.toLowerCase().endsWith(suffix)) {
      normalized = normalized.slice(0, -suffix.length).replace(/\/+$/, '')
    }
  }
  return normalized
}

export const shouldAutoDiscoverLlmModels = (baseUrl: string, apiKey: string): boolean => {
  const cleanBaseUrl = normalizeOpenAiBaseUrl(baseUrl)
  if (!cleanBaseUrl) return false
  return isLocalLlmEndpoint(cleanBaseUrl) || Boolean(apiKey.trim())
}


type LlmInferenceValues = Record<string, unknown>

export const isGpt61SolModel = (model: unknown): boolean =>
  typeof model === 'string' && /^gpt-?6\.1-?sol(?:$|[-/])/i.test(model.trim().replace(/^models\//i, ''))

const legacyLlmDefaults: Record<string, number> = {
  temperature: 1.2,
  top_p: 0.9,
  top_k: 500,
  frequency_penalty: 0.2,
  timeout: 60,
  context_max_tokens: 131072,
  default_max_output_tokens: 8192,
}

const recommendedLlmDefaults: Record<string, number> = {
  temperature: 1,
  top_p: 1,
  top_k: 0,
  frequency_penalty: 0,
  timeout: 120,
  context_max_tokens: 500000,
  default_max_output_tokens: 16384,
}

export const migrateLegacyLlmDefaults = (values: LlmInferenceValues): Partial<Record<string, number>> => {
  if (!isGpt61SolModel(values.model)) return {}
  const patch: Partial<Record<string, number>> = {}
  for (const [field, legacyValue] of Object.entries(legacyLlmDefaults)) {
    if (values[field] === legacyValue) patch[field] = recommendedLlmDefaults[field]
  }
  return patch
}
