export interface NavigationCapability {
  petControl?: boolean
  voice?: boolean
  memory?: boolean
  deployment?: boolean
  plugins?: boolean
  tasks?: boolean
  admin?: boolean
  companion?: boolean
  prompt?: boolean
}

export type NavigationSlot = 'primary' | 'secondary' | 'system' | 'admin'

export type NavigationAudience = 'core' | 'assistant' | 'admin'

export interface NavigationModuleRecord {
  id: string
  /**
   * Display copy lives in the renderer message tables (`navigation.<id>.title` /
   * `.desc`). Records keep no text of their own so this module stays free of
   * user-facing Chinese and cannot drift from the translations.
   */
  title?: string
  desc?: string
  order?: number
  enabled?: boolean
  capabilities?: NavigationCapability
  slot?: NavigationSlot
  audience?: NavigationAudience
  primary?: boolean
}

export const staticNavigationModuleRecords = [
  {
    id: 'chat',
    order: 0,
    enabled: true,
    capabilities: { voice: true, petControl: true, companion: true },
    slot: 'primary',
    audience: 'core',
    primary: true,
  },
  {
    id: 'prompt',
    order: 2,
    enabled: true,
    capabilities: { companion: true, prompt: true },
    slot: 'admin',
    audience: 'admin',
    primary: false,
  },
  {
    id: 'pet',
    order: 3,
    enabled: true,
    capabilities: { petControl: true, companion: true },
    slot: 'admin',
    audience: 'admin',
    primary: false,
  },
  {
    id: 'svc',
    order: 4,
    enabled: true,
    capabilities: { voice: true, admin: true },
    slot: 'admin',
    audience: 'admin',
    primary: false,
  },
  {
    id: 'tool',
    order: 5,
    enabled: true,
    capabilities: { plugins: true, tasks: true },
    slot: 'admin',
    audience: 'admin',
    primary: false,
  },
  {
    id: 'plugins',
    order: 6,
    enabled: true,
    capabilities: { plugins: true, admin: true },
    slot: 'admin',
    audience: 'admin',
  },
  {
    id: 'infrastructure',
    order: 7,
    enabled: true,
    capabilities: { deployment: true, admin: true },
    slot: 'admin',
    audience: 'admin',
  },
  {
    id: 'agent-governance',
    order: 8,
    enabled: true,
    capabilities: { plugins: true, admin: true },
    slot: 'admin',
    audience: 'admin',
  },
  {
    id: 'agent-trace',
    order: 9,
    enabled: true,
    capabilities: { plugins: true, tasks: true },
    slot: 'admin',
    audience: 'admin',
    primary: false,
  },
  {
    id: 'persona-memory',
    order: 11,
    enabled: true,
    capabilities: { memory: true, petControl: true, admin: true },
    slot: 'admin',
    audience: 'admin',
  },
  {
    id: 'memory',
    order: 14,
    enabled: true,
    capabilities: { memory: true, companion: true },
    slot: 'secondary',
    audience: 'core',
    primary: true,
  },
  {
    id: 'settings',
    order: 12,
    enabled: true,
    capabilities: { petControl: true, voice: true, companion: true },
    slot: 'admin',
    audience: 'admin',
    primary: true,
  },
  {
    id: 'i18n',
    order: 13,
    enabled: true,
    capabilities: { admin: true },
    slot: 'admin',
    audience: 'admin',
  },
  {
    id: 'deploy',
    order: 15,
    enabled: true,
    capabilities: { deployment: true, admin: true },
    slot: 'admin',
    audience: 'admin',
  },
] as const satisfies readonly NavigationModuleRecord[]

export type StaticNavigationModuleId = typeof staticNavigationModuleRecords[number]['id']
