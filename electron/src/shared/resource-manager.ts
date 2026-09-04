import type { PetControlState, PetModelCatalogPayload, PetModelType } from './pet-control'

export type PetImportableModelType = Extract<PetModelType, 'live2d' | 'vrm'>
export type PetModelImportMode = PetImportableModelType | 'auto'

export interface LocalModelRoots {
  live2d: string
  vrm: string
}

export interface LocalModelCounts {
  live2d: number
  vrm: number
}

export interface LocalModelPickerResponse {
  canceled: boolean
  modelType: PetModelImportMode
  sourcePath: string | null
}

export interface LocalModelImportResponse {
  success: boolean
  modelType: PetImportableModelType
  importedModelId: string | null
  state?: PetControlState
  localModels: PetModelCatalogPayload['models']
  catalog: PetModelCatalogPayload
  modelRoots: LocalModelRoots
}

export interface LocalModelPickerImportResponse extends Partial<Omit<LocalModelImportResponse, 'modelType'>> {
  success: boolean
  canceled: boolean
  modelType: PetModelImportMode
  sourcePath: string | null
}

export interface ManagedResourceSummary {
  ready: boolean
  state: 'missing' | 'partial' | 'ready'
  message: string
  details: string[]
  metadata: ManagedResourceMetadata
}

export interface ManagedResourceMetadata {
  label: string
  version: string
  requiredOnFirstRun: boolean
  license: string
  licenseUrl: string
  downloadBytes: number
  source: string
  integrity: 'sha256' | 'revision' | 'package' | 'package+revision' | 'unverified'
  inUseBy: string[]
}

export interface SoulxResourceStatus extends ManagedResourceSummary {
  serviceDir: string
  launcherPath: string
  checkpointPath: string | null
  checkpointCandidates: string[]
  preprocessDir: string
  referenceDir: string
  hasReferenceAudio: boolean
}

export interface SherpaResourceStatus extends ManagedResourceSummary {
  assetUrl: string
  modelPath: string
  tokensPath: string
  format: 'sensevoice-offline' | 'zipformer2-ctc-online'
  validated: boolean
  validationPath: string | null
}

export interface EmbeddingResourceStatus extends ManagedResourceSummary {
  modelName: string
  cachePath: string | null
  cacheRoot: string
}

export interface TtsResourceStatus extends ManagedResourceSummary {
  character: string
  cacheDir: string
  modelDir: string
}

export type ResourceProgressPhase = 'preparing' | 'downloading' | 'verifying' | 'extracting' | 'installing' | 'cancelling'

export interface ResourceDownloadProgress {
  resourceId: ManagedModelResourceId
  phase: ResourceProgressPhase
  message: string
  bytesDownloaded: number | null
  bytesTotal: number | null
  percent: number | null
  startedAt: string
  updatedAt: string
}

export interface ResumableResourceDownload {
  resourceId: ManagedModelResourceId
  bytesDownloaded: number
  bytesTotal: number | null
  percent: number | null
  updatedAt: string
}

export interface ModelResourceStatusPayload {
  modelRoots: LocalModelRoots
  localCounts: LocalModelCounts
  soulx: SoulxResourceStatus
  sherpa: SherpaResourceStatus
  sherpaOnline: SherpaResourceStatus
  embedding: EmbeddingResourceStatus
  tts: TtsResourceStatus
  activeDownloads: ResourceDownloadProgress[]
  resumableDownloads: ResumableResourceDownload[]
}

export interface ResourceProgressSnapshot {
  activeDownloads: ResourceDownloadProgress[]
}

export type ManagedModelResourceId = 'soulx' | 'sherpa' | 'sherpa_online' | 'embedding' | 'tts'

export type ResourceFailureCode =
  | 'cancelled'
  | 'network_timeout'
  | 'network_unreachable'
  | 'authentication_required'
  | 'disk_full'
  | 'integrity_failed'
  | 'dependency_failed'
  | 'unknown'

export interface ResourceCommandResult {
  success: boolean
  message: string
  errorCode: ResourceFailureCode | null
  retryable: boolean
  stdout: string[]
  stderr: string[]
  status: ModelResourceStatusPayload
}

export interface ResourceCancelResult {
  success: boolean
  cancelled: ManagedModelResourceId[]
  status: ModelResourceStatusPayload
}

export interface ResourceRemovalFailure {
  resourceId: ManagedModelResourceId
  reason: string
}

export interface ResourceRemovalResult {
  success: boolean
  message: string
  removed: ManagedModelResourceId[]
  failed: ResourceRemovalFailure[]
  reclaimedBytes: number
  status: ModelResourceStatusPayload
}

export type StorageCategoryId = 'tts_audio' | 'runtime_temp' | 'memory' | 'visual_frames'
export type StorageCategoryAction = 'delete_files' | 'compact' | 'none'

export interface StorageCategoryStatus {
  id: StorageCategoryId
  bytes: number
  files: number
  action: StorageCategoryAction
  persistence: 'disk' | 'memory_only'
  failed_files?: number
}

export interface StorageStatusPayload {
  categories: StorageCategoryStatus[]
  total_bytes: number
  reclaimable_bytes: number
}

export interface StorageCleanupResult {
  deleted_files: number
  failed_files: number
  reclaimed_bytes: number
  completed: Array<Exclude<StorageCategoryId, 'visual_frames'>>
  status: StorageStatusPayload
}
