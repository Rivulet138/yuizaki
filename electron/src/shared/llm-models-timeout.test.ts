import { describe, expect, it } from 'vitest'
import {
  LLM_MODELS_CLIENT_GRACE_MS,
  LLM_MODELS_MAX_TIMEOUT_MS,
  LLM_MODELS_MIN_TIMEOUT_MS,
  resolveLlmModelsClientTimeoutMs,
  resolveLlmModelsTimeoutMs,
} from './llm-models-timeout'

describe('llm model discovery timeouts', () => {
  it('keeps a floor that covers a live provider round trip', () => {
    expect(resolveLlmModelsTimeoutMs(undefined)).toBe(LLM_MODELS_MIN_TIMEOUT_MS)
    expect(resolveLlmModelsTimeoutMs(null)).toBe(LLM_MODELS_MIN_TIMEOUT_MS)
    expect(resolveLlmModelsTimeoutMs('soon')).toBe(LLM_MODELS_MIN_TIMEOUT_MS)
    expect(resolveLlmModelsTimeoutMs(0)).toBe(LLM_MODELS_MIN_TIMEOUT_MS)
    expect(resolveLlmModelsTimeoutMs(1)).toBe(LLM_MODELS_MIN_TIMEOUT_MS)
  })

  it('honors a configured timeout and caps it at the ceiling', () => {
    expect(resolveLlmModelsTimeoutMs(90)).toBe(90_000)
    expect(resolveLlmModelsTimeoutMs(99_999)).toBe(LLM_MODELS_MAX_TIMEOUT_MS)
  })

  it('always gives the client more time than the proxy', () => {
    expect(resolveLlmModelsClientTimeoutMs(90)).toBe(90_000 + LLM_MODELS_CLIENT_GRACE_MS)
    expect(resolveLlmModelsClientTimeoutMs(undefined)).toBe(
      resolveLlmModelsTimeoutMs(undefined) + LLM_MODELS_CLIENT_GRACE_MS,
    )
  })
})
