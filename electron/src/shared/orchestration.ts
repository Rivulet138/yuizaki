export type OrchestrationKind = 'skill' | 'command' | 'hook'

export interface OrchestrationAgentDescriptor {
  id: string
  name: string
  description: string
  role: string
  audience: 'core' | 'admin'
}

export interface OrchestrationDescriptor {
  id: string
  name: string
  description: string
  kind: OrchestrationKind
  audience: 'core' | 'admin'
  target?: string
  stage?: string
}

export interface OrchestrationSnapshot {
  agents?: OrchestrationAgentDescriptor[]
  skills: OrchestrationDescriptor[]
  commands: OrchestrationDescriptor[]
  hooks: OrchestrationDescriptor[]
  summary?: {
    agents: number
    skills: number
    commands: number
    hooks: number
  }
}
