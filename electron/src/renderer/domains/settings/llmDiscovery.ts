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
