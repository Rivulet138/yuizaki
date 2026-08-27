export type CapabilityKind = 'builtin-tool' | 'plugin-tool' | 'mcp-tool' | 'skill' | 'command'

export type CapabilityType = 'tool' | 'skill' | 'command'

export type CapabilityRiskLevel = 'safe' | 'low' | 'medium' | 'high' | 'critical'

export type CapabilityEffectKind = 'read' | 'write' | 'unknown'

export interface CapabilityDescriptor {
  id: string
  name: string
  description: string
  type: CapabilityType
  kind: CapabilityKind
  source: string
  riskLevel: CapabilityRiskLevel
  requiresApproval: boolean
  owner?: string
  tags?: string[]
  contributionCategories?: string[]
  scopes?: string[]
  inputSchema?: Record<string, unknown>
  outputSchema?: Record<string, unknown>
  timeoutMs?: number
  memoryHooks?: string[]
  observability?: {
    trace?: boolean
    audit?: boolean
    stage?: string
  }
  parameters?: Record<string, unknown>
  effectKind?: CapabilityEffectKind
  hasPostcondition?: boolean
  hasRecheck?: boolean
}

export interface CapabilitiesSnapshot {
  capabilities: CapabilityDescriptor[]
  summary?: {
    total: number
    builtin: number
    plugin: number
    mcp: number
    skill: number
    command: number
    approval_required: number
  }
}

export interface CapabilityCategorySummary {
  kind: CapabilityKind
  count: number
}

export interface SkillCatalogItem {
  id: string
  name: string
  description: string
  category: string
  source: string
  status: string
  fit: 'high' | 'medium' | 'low' | string
  installed: boolean
  enabled_codex: boolean
  directory?: string | null
  repo?: string | null
  url?: string | null
  tags?: string[] | null
}

export interface SkillCatalogSnapshot {
  items: SkillCatalogItem[]
  summary: {
    total: number
    built_in: number
    ready: number
    planned: number
    high_fit: number
    medium_fit: number
    recommended: number
    categories?: Record<string, number>
  }
  notes?: string[]
}
