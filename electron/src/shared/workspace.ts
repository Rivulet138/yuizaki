import type { PetModelType } from './pet-control'

export type WorkspacePromptMode = 'auto' | 'work' | 'daily'

export interface WorkspaceRoleCard {
  enabled: boolean
  name: string
  personality: string
  scenario: string
  instructions: string
  firstMessage: string
}

export interface WorkspacePromptEngineering {
  workPrompt: string
  dailyPrompt: string
}

export interface WorkspaceVisionRegion {
  x: number
  y: number
  width: number
  height: number
}

export interface WorkspaceVisionSettings {
  enabled: boolean
  displayIndex: number
  intervalMs: number
  pauseWhenAppHidden: boolean
  captureMode: 'display' | 'region'
  region: WorkspaceVisionRegion
  privacyMasks: WorkspaceVisionRegion[]
}

export interface WorkspaceMemoryPolicy {
  workingRetentionDays: number
  lowQualityThreshold: number
  includeStaleWorking: boolean
  includeLowQuality: boolean
  includeExactDuplicates: boolean
}

export interface WorkspaceWorldBookEntry {
  id: string
  title: string
  keys: string[]
  secondaryKeys: string[]
  content: string
  enabled: boolean
  priority: number
  insertionOrder: number
  constant: boolean
  selective: boolean
  caseSensitive: boolean
  matchWholeWords: boolean
  probability: number
}

export interface WorkspaceWorldBook {
  enabled: boolean
  scanDepth: number
  maxEntries: number
  budgetTokens: number
  entries: WorkspaceWorldBookEntry[]
}

export interface WorkspaceContext {
  activeTab: string
  modelType: PetModelType
  modelId: string | null
  wallpaperMode: boolean
  heroHeight: number
  menuOrder: string[]
  recentTabs: string[]
  layoutPreset: 'focus' | 'balanced' | 'wide'
  promptVersion: number
  promptMode: WorkspacePromptMode
  promptEngineering: WorkspacePromptEngineering
  roleCard: WorkspaceRoleCard
  worldBook: WorkspaceWorldBook
  vision: WorkspaceVisionSettings
  memoryPolicy: WorkspaceMemoryPolicy
}

export interface WorkspaceRecord {
  id: string
  name: string
  description?: string | null
  icon?: string | null
  color?: string | null
  companion_profile_id?: string | null
  default_model?: string | null
  system_prompt?: string | null
  tool_preset?: string | null
  memory_scope?: string | null
  mcp_preset_id?: string | null
  createdAt: string
  updatedAt: string
  context: WorkspaceContext
}

export interface WorkspaceStatePayload {
  activeWorkspaceId: string
  workspaces: WorkspaceRecord[]
  recentWorkspaceIds: string[]
}
