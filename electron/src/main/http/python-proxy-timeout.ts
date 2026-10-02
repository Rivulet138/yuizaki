import { resolveLlmModelsTimeoutMs } from '../../shared/llm-models-timeout'

/** Proxy budgets for requests forwarded from the control server to the Python backend. */
export const PYTHON_PROXY_TIMEOUT_MS = 12000
export const PYTHON_LOCAL_DISCOVERY_TIMEOUT_MS = 30000
export const PYTHON_SESSION_READ_TIMEOUT_MS = 30000
export const PYTHON_TTS_WARMUP_TIMEOUT_MS = 5 * 60 * 1000
export const PYTHON_PING_ATTEMPT_TIMEOUT_MS = 4000

export const PYTHON_LLM_MODELS_PATH = '/api/settings/llm/models'

export const resolvePythonProxyTimeout = (pathname: string): number => {
  if (pathname === '/api/settings/local-discovery') return PYTHON_LOCAL_DISCOVERY_TIMEOUT_MS
  if (pathname === '/api/sessions') return PYTHON_SESSION_READ_TIMEOUT_MS
  if (pathname === '/api/settings/tts/warmup') return PYTHON_TTS_WARMUP_TIMEOUT_MS
  if (pathname === '/api/ping') return PYTHON_PING_ATTEMPT_TIMEOUT_MS
  return PYTHON_PROXY_TIMEOUT_MS
}

const readBodyTimeoutSeconds = (body: unknown): unknown => {
  if (typeof body !== 'object' || body === null || Array.isArray(body)) return undefined
  return (body as Record<string, unknown>)['timeout']
}

export const resolvePythonProxyRequestTimeout = (pathname: string, body?: unknown): number => {
  if (pathname !== PYTHON_LLM_MODELS_PATH) return resolvePythonProxyTimeout(pathname)
  return resolveLlmModelsTimeoutMs(readBodyTimeoutSeconds(body))
}
