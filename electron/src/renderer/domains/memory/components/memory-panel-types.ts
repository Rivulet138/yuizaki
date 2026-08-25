import type { MemoryDoc, MemoryDuplicateCandidate } from '../composables/useMemoryDomain'
import type { MemoryIndexStatus, MemoryMaintenancePreview } from '@/api/clients/memory-client'
import type { InjectionKey } from 'vue'

export type MemoryScope = 'global' | 'workspace' | 'session'
export type MemoryTab = 'library' | 'review' | 'overview'
export type DocViewMode = 'all' | 'recallable' | 'review' | 'important' | 'hits'
export type DocSortMode = 'updated' | 'importance' | 'quality' | 'confidence'
export type TagType = 'success' | 'warning' | 'danger' | 'info' | 'primary'

export interface MemoryLayer {
  value: string
  label: string
  desc: string
  color?: string
  count?: number
}

export interface MemoryOption {
  value: string
  label: string
}

export interface MemoryMetric {
  label: string
  value: string | number
  detail: string
  tone: string
}

export interface MemoryCaptureForm {
  text: string
  type: string
  layer: string
  importance: number
  confidence: number
  source: string
}

export interface MemoryDocumentForm {
  id: string
  text: string
  metadataJson: string
}

export interface MemoryQueryForm {
  query: string
  scope: MemoryScope
  top_k: number
}

export interface MemoryInspectorDraft extends MemoryCaptureForm {
  id: string
  validFrom: string
  validTo: string
  expiresAt: string
}

export interface MemoryVersionSnapshot {
  revision: number
  text?: string
  metadata?: Record<string, unknown>
}

export interface MemoryScoreComponents {
  semantic?: number
  lexical?: number
  recency?: number
  quality?: number
  learned?: number
  final?: number
}

export interface MemoryInspectorActions {
  rollback: (doc: MemoryDoc, revision: number) => Promise<void>
}

export const memoryInspectorActionsKey: InjectionKey<MemoryInspectorActions> = Symbol('memory-inspector-actions')

export interface MemoryMaintenancePolicy {
  workingRetentionDays: number
  lowQualityThreshold: number
  includeStaleWorking: boolean
  includeLowQuality: boolean
  includeExactDuplicates: boolean
}

export type { MemoryDoc, MemoryDuplicateCandidate, MemoryIndexStatus, MemoryMaintenancePreview }
