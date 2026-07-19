import modelRegistryJson from './model-capabilities.registry.json'

export type ModelCapabilitySupport = true | false | 'unknown'
export type ModelLatencyClass = 'realtime' | 'fast' | 'balanced' | 'deliberate' | 'unknown'
export type ModelLifecycle = 'stable' | 'preview' | 'deprecated' | 'legacy' | 'unknown'

export interface ModelPricing {
  inputPerMillionUsd: number
  outputPerMillionUsd: number
  cachedInputPerMillionUsd?: number
  note?: string
}

export interface ModelRegistryMetadata {
  canonicalModel: string
  contextWindowTokens: number | null
  maxOutputTokens: number | null
  lifecycle: ModelLifecycle
  deprecationAt?: string
  pricing: ModelPricing | null
  verifiedAt: string
  documentationUrl: string
}

export interface ModelCapabilities {
  vision: ModelCapabilitySupport
  tools: ModelCapabilitySupport
  structuredOutput: ModelCapabilitySupport
  realtimeAudio: ModelCapabilitySupport
  computerUse: ModelCapabilitySupport
  latency: ModelLatencyClass
  source: 'registry' | 'provider-default' | 'model-pattern' | 'unknown'
  metadata: ModelRegistryMetadata | null
}

const UNKNOWN_CAPABILITIES: ModelCapabilities = {
  vision: 'unknown',
  tools: 'unknown',
  structuredOutput: 'unknown',
  realtimeAudio: 'unknown',
  computerUse: 'unknown',
  latency: 'unknown',
  source: 'unknown',
  metadata: null,
}

const MODEL_REGISTRY = modelRegistryJson as Record<string, ModelCapabilities>

const cloneCapabilities = (value: ModelCapabilities): ModelCapabilities => ({
  ...value,
  metadata: value.metadata
    ? {
        ...value.metadata,
        pricing: value.metadata.pricing ? { ...value.metadata.pricing } : null,
      }
    : null,
})

export const inferModelCapabilities = (provider: string, model: string): ModelCapabilities => {
  const normalizedProvider = provider.trim().toLowerCase()
  const normalizedModel = model.trim().toLowerCase().replace(/^models\//, '')
  if (!normalizedModel) return cloneCapabilities(UNKNOWN_CAPABILITIES)

  const registered = MODEL_REGISTRY[`${normalizedProvider}:${normalizedModel}`]
  if (registered) return cloneCapabilities(registered)

  if (normalizedProvider === 'deepseek' || normalizedModel.includes('deepseek')) {
    const vision = /(?:^|[-_.])(vl|vision)(?:[-_.]|$)/.test(normalizedModel)
    return {
      vision,
      tools: true,
      structuredOutput: true,
      realtimeAudio: false,
      computerUse: false,
      latency: /flash|chat/.test(normalizedModel) ? 'fast' : /reasoner|pro/.test(normalizedModel) ? 'deliberate' : 'balanced',
      source: 'model-pattern',
      metadata: null,
    }
  }

  if (normalizedProvider === 'qwen' || normalizedModel.includes('qwen')) {
    const multimodal = /vl|omni|audio/.test(normalizedModel)
    return {
      vision: /vl|omni/.test(normalizedModel),
      tools: true,
      structuredOutput: true,
      realtimeAudio: /omni|audio/.test(normalizedModel),
      computerUse: /computer|agent/.test(normalizedModel) ? true : 'unknown',
      latency: /flash|turbo/.test(normalizedModel) ? 'fast' : multimodal ? 'balanced' : 'balanced',
      source: 'model-pattern',
      metadata: null,
    }
  }

  if (normalizedProvider === 'gemini' || normalizedModel.includes('gemini')) {
    const live = /live|native-audio/.test(normalizedModel)
    return {
      vision: true,
      tools: true,
      structuredOutput: true,
      realtimeAudio: live,
      computerUse: /computer-use/.test(normalizedModel),
      latency: live ? 'realtime' : /flash/.test(normalizedModel) ? 'fast' : 'balanced',
      source: 'model-pattern',
      metadata: null,
    }
  }

  if (normalizedProvider === 'chatgpt' || /^(gpt|o\d|computer-use)/.test(normalizedModel)) {
    const realtime = /realtime|audio/.test(normalizedModel)
    return {
      vision: /gpt-4o|gpt-5|realtime|vision|computer-use/.test(normalizedModel),
      tools: true,
      structuredOutput: !realtime,
      realtimeAudio: realtime,
      computerUse: /computer-use/.test(normalizedModel),
      latency: realtime ? 'realtime' : /mini|nano/.test(normalizedModel) ? 'fast' : 'balanced',
      source: 'model-pattern',
      metadata: null,
    }
  }

  if (normalizedProvider === 'claude' || normalizedModel.includes('claude')) {
    return {
      vision: true,
      tools: true,
      structuredOutput: true,
      realtimeAudio: false,
      computerUse: /computer-use/.test(normalizedModel) ? true : 'unknown',
      latency: /haiku/.test(normalizedModel) ? 'fast' : /opus/.test(normalizedModel) ? 'deliberate' : 'balanced',
      source: 'model-pattern',
      metadata: null,
    }
  }

  if (normalizedProvider === 'ollama' || normalizedProvider === 'lmstudio' || normalizedProvider === 'custom') {
    return cloneCapabilities(UNKNOWN_CAPABILITIES)
  }

  return cloneCapabilities(UNKNOWN_CAPABILITIES)
}
