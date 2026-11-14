import registry from '../../../python/modules/llm/generation-parameters.registry.json'

export type GenerationParameter = 'temperature' | 'top_p' | 'top_k' | 'min_p' | 'frequency_penalty' | 'presence_penalty' | 'repetition_penalty'
export type GenerationParameterRange = { min: number; max: number }
export type GenerationCapabilities = {
  parameters: Partial<Record<GenerationParameter, GenerationParameterRange>>
  reasoningEfforts: string[]
  reasoningTransport: string
  outputTokenField: string
  samplingRequiresNone?: boolean
}
type ModelRule = Partial<GenerationCapabilities> & { provider: string; pattern: string }
type CapabilityRegistry = { providers: Record<string, GenerationCapabilities> & { custom: GenerationCapabilities }; rules: ModelRule[] }
const capabilitiesRegistry = registry as CapabilityRegistry

/** Match the same ordered provider/model rules used by the Python request adapter. */
export function resolveGenerationCapabilities(provider: string, model: string, reasoningEffort = 'default'): GenerationCapabilities {
  const providerKey = String(provider || 'custom').trim().toLowerCase()
  const normalizedProvider = ({ openai: 'chatgpt', anthropic: 'claude' } as Record<string, string>)[providerKey] || providerKey
  const normalizedModel = String(model || '').trim().toLowerCase().replace(/^models\//, '')
  let capability = { ...(capabilitiesRegistry.providers[normalizedProvider] || capabilitiesRegistry.providers['custom']) }
  for (const rule of capabilitiesRegistry.rules) {
    if (rule.provider !== normalizedProvider || !new RegExp(rule.pattern, 'i').test(normalizedModel)) continue
    const { provider: _provider, pattern: _pattern, ...override } = rule
    capability = { ...capability, ...override }
  }
  const parameters = Object.fromEntries(Object.entries(capability.parameters).map(([field, range]) => [field, { ...range }])) as GenerationCapabilities['parameters']
  if (capability.samplingRequiresNone && (reasoningEffort !== 'none' || !capability.reasoningEfforts.includes('none'))) {
    delete parameters.temperature
    delete parameters.top_p
  }
  return { ...capability, parameters, reasoningEfforts: [...capability.reasoningEfforts] }
}

export function normalizeGenerationValue(value: number, range: GenerationParameterRange): number {
  return Math.min(range.max, Math.max(range.min, Number.isFinite(value) ? value : range.min))
}
