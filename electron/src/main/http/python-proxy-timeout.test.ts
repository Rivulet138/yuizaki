import { describe, expect, it } from 'vitest'
import { LLM_MODELS_MAX_TIMEOUT_MS, LLM_MODELS_MIN_TIMEOUT_MS } from '../../shared/llm-models-timeout'
import {
  PYTHON_LOCAL_DISCOVERY_TIMEOUT_MS,
  PYTHON_PING_ATTEMPT_TIMEOUT_MS,
  PYTHON_PROXY_TIMEOUT_MS,
  PYTHON_SESSION_READ_TIMEOUT_MS,
  resolvePythonProxyRequestTimeout,
  resolvePythonProxyTimeout,
} from './python-proxy-timeout'

describe('python proxy timeouts', () => {
  it('keeps the generic budget for ordinary proxied routes', () => {
    expect(resolvePythonProxyTimeout('/api/settings')).toBe(PYTHON_PROXY_TIMEOUT_MS)
    expect(resolvePythonProxyRequestTimeout('/api/settings')).toBe(PYTHON_PROXY_TIMEOUT_MS)
  })

  it('keeps the long budgets for the slow read routes', () => {
    expect(resolvePythonProxyTimeout('/api/settings/local-discovery')).toBe(PYTHON_LOCAL_DISCOVERY_TIMEOUT_MS)
    expect(resolvePythonProxyTimeout('/api/sessions')).toBe(PYTHON_SESSION_READ_TIMEOUT_MS)
    expect(resolvePythonProxyTimeout('/api/ping')).toBe(PYTHON_PING_ATTEMPT_TIMEOUT_MS)
  })

  it('waits long enough for live model discovery', () => {
    expect(resolvePythonProxyRequestTimeout('/api/settings/llm/models')).toBe(LLM_MODELS_MIN_TIMEOUT_MS)
    expect(resolvePythonProxyRequestTimeout('/api/settings/llm/models', { timeout: 60 })).toBe(60000)
  })

  it('clamps the requested model discovery timeout to a sane range', () => {
    expect(resolvePythonProxyRequestTimeout('/api/settings/llm/models', { timeout: 0.001 })).toBe(
      LLM_MODELS_MIN_TIMEOUT_MS,
    )
    expect(resolvePythonProxyRequestTimeout('/api/settings/llm/models', { timeout: 9999 })).toBe(
      LLM_MODELS_MAX_TIMEOUT_MS,
    )
  })

  it('ignores malformed timeout payloads', () => {
    expect(resolvePythonProxyRequestTimeout('/api/settings/llm/models', { timeout: 'soon' })).toBe(
      LLM_MODELS_MIN_TIMEOUT_MS,
    )
    expect(resolvePythonProxyRequestTimeout('/api/settings/llm/models', null)).toBe(LLM_MODELS_MIN_TIMEOUT_MS)
  })
})
