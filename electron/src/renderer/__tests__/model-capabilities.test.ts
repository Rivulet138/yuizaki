import { describe, expect, it } from 'vitest'
import { inferModelCapabilities } from '../../shared/model-capabilities'

describe('model capability inference', () => {
  it('does not claim vision for a text-only DeepSeek model', () => {
    const result = inferModelCapabilities('deepseek', 'deepseek-v4-flash')
    expect(result.vision).toBe(false)
    expect(result.latency).toBe('fast')
    expect(result.tools).toBe(true)
    expect(result.source).toBe('registry')
    expect(result.metadata).toMatchObject({
      contextWindowTokens: 1_000_000,
      maxOutputTokens: 384_000,
      lifecycle: 'stable',
    })
  })

  it('recognizes realtime multimodal model families', () => {
    expect(inferModelCapabilities('gemini', 'gemini-3.1-flash-live-preview')).toMatchObject({
      vision: true,
      realtimeAudio: true,
      latency: 'realtime',
    })
    expect(inferModelCapabilities('chatgpt', 'gpt-realtime-2.1-mini')).toMatchObject({
      vision: true,
      realtimeAudio: true,
      latency: 'realtime',
    })
  })

  it('keeps unrecognized local models unknown', () => {
    expect(inferModelCapabilities('ollama', 'my-local-model')).toMatchObject({
      vision: 'unknown',
      tools: 'unknown',
      latency: 'unknown',
    })
  })

  it('marks deprecated aliases and points to the replacement model', () => {
    expect(inferModelCapabilities('deepseek', 'deepseek-chat').metadata).toMatchObject({
      canonicalModel: 'deepseek-v4-flash',
      lifecycle: 'deprecated',
      deprecationAt: '2026-07-24T15:59:00Z',
    })
  })

  it('normalizes provider model prefixes before registry lookup', () => {
    expect(inferModelCapabilities('gemini', 'models/gemini-3.1-flash-lite')).toMatchObject({
      source: 'registry',
      vision: true,
      latency: 'fast',
      metadata: {
        contextWindowTokens: 1_000_000,
        lifecycle: 'stable',
      },
    })
  })
})
