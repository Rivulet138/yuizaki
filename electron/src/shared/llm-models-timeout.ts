/**
 * Model discovery performs a live upstream LLM request, so the generic
 * local-service budgets (a few seconds) are far too small: a healthy but slow
 * provider would surface as a timeout in the settings UI.
 */
export const LLM_MODELS_MIN_TIMEOUT_MS = 60 * 1000
export const LLM_MODELS_MAX_TIMEOUT_MS = 5 * 60 * 1000
/**
 * The renderer waits slightly longer than the proxy so the backend's own
 * message (for example a rejected credential) reaches the user instead of the
 * generic local timeout notice.
 */
export const LLM_MODELS_CLIENT_GRACE_MS = 5 * 1000

const toMilliseconds = (requestedSeconds: unknown): number => {
  const seconds = Number(requestedSeconds)
  if (!Number.isFinite(seconds) || seconds <= 0) {
    return LLM_MODELS_MIN_TIMEOUT_MS
  }
  return seconds * 1000
}

/** Proxy budget for a model discovery request, derived from the requested timeout. */
export const resolveLlmModelsTimeoutMs = (requestedSeconds: unknown): number =>
  Math.min(Math.max(toMilliseconds(requestedSeconds), LLM_MODELS_MIN_TIMEOUT_MS), LLM_MODELS_MAX_TIMEOUT_MS)

/** Client-side fallback budget; always slightly larger than the proxy budget. */
export const resolveLlmModelsClientTimeoutMs = (requestedSeconds: unknown): number =>
  resolveLlmModelsTimeoutMs(requestedSeconds) + LLM_MODELS_CLIENT_GRACE_MS
