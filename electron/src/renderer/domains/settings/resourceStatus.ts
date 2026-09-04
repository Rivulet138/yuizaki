import type {
  ManagedModelResourceId,
  ModelResourceStatusPayload,
  ResumableResourceDownload,
  ResourceDownloadProgress,
  ResourceProgressPhase,
  StorageCategoryId,
  StorageStatusPayload,
} from '@/../shared/resource-manager'

export type SettingsRecord = Record<string, unknown>

export const isPlainRecord = (value: unknown): value is SettingsRecord => (
  typeof value === 'object' && value !== null && !Array.isArray(value)
)

const resourceSummaryFallback = (message = '') => ({
  ready: false,
  state: 'missing' as const,
  message,
  details: [] as string[],
})

const resourceIds = new Set<ManagedModelResourceId>(['soulx', 'sherpa', 'sherpa_online', 'embedding', 'tts'])
const progressPhases = new Set<ResourceProgressPhase>([
  'preparing',
  'downloading',
  'verifying',
  'extracting',
  'installing',
  'cancelling',
])

export const normalizeResourceStatus = (value: unknown): ModelResourceStatusPayload | null => {
  if (!isPlainRecord(value)) return null
  const modelRoots = isPlainRecord(value.modelRoots) ? value.modelRoots : {}
  const localCounts = isPlainRecord(value.localCounts) ? value.localCounts : {}
  const soulx = isPlainRecord(value.soulx) ? value.soulx : {}
  const sherpa = isPlainRecord(value.sherpa) ? value.sherpa : {}
  const sherpaOnline = isPlainRecord(value.sherpaOnline) ? value.sherpaOnline : {}
  const embedding = isPlainRecord(value.embedding) ? value.embedding : {}
  const ttsStatus = isPlainRecord(value.tts) ? value.tts : {}
  const activeDownloads = (Array.isArray(value.activeDownloads) ? value.activeDownloads : [])
    .filter(isPlainRecord)
    .flatMap((progress): ResourceDownloadProgress[] => {
      const resourceId = String(progress.resourceId || '') as ManagedModelResourceId
      const phase = progress.phase as ResourceProgressPhase
      if (!resourceIds.has(resourceId) || !progressPhases.has(phase)) return []
      const bytesDownloaded = progress.bytesDownloaded === null ? null : Math.max(0, Number(progress.bytesDownloaded || 0))
      const bytesTotal = progress.bytesTotal === null ? null : Math.max(0, Number(progress.bytesTotal || 0))
      const percent = progress.percent === null ? null : Math.min(100, Math.max(0, Number(progress.percent || 0)))
      return [{
        resourceId,
        phase,
        message: String(progress.message || ''),
        bytesDownloaded,
        bytesTotal,
        percent,
        startedAt: String(progress.startedAt || ''),
        updatedAt: String(progress.updatedAt || ''),
      }]
    })
  const resumableDownloads = (Array.isArray(value.resumableDownloads) ? value.resumableDownloads : [])
    .filter(isPlainRecord)
    .flatMap((download): ResumableResourceDownload[] => {
      const resourceId = String(download.resourceId || '') as ManagedModelResourceId
      if (!resourceIds.has(resourceId)) return []
      const bytesDownloaded = Math.max(0, Number(download.bytesDownloaded || 0))
      if (!Number.isFinite(bytesDownloaded) || bytesDownloaded <= 0) return []
      const rawBytesTotal = download.bytesTotal === null ? null : Number(download.bytesTotal || 0)
      const bytesTotal = rawBytesTotal !== null && Number.isFinite(rawBytesTotal)
        ? Math.max(bytesDownloaded, rawBytesTotal)
        : null
      const rawPercent = download.percent === null ? null : Number(download.percent || 0)
      const percent = rawPercent !== null && Number.isFinite(rawPercent)
        ? Math.min(100, Math.max(0, rawPercent))
        : null
      return [{
        resourceId,
        bytesDownloaded,
        bytesTotal,
        percent,
        updatedAt: String(download.updatedAt || ''),
      }]
    })
  const metadata = (source: SettingsRecord) => {
    const raw = isPlainRecord(source.metadata) ? source.metadata : {}
    const integrity = raw.integrity === 'sha256' || raw.integrity === 'revision' || raw.integrity === 'package' || raw.integrity === 'package+revision'
      ? raw.integrity
      : 'unverified'
    return {
      label: String(raw.label || ''),
      version: String(raw.version || ''),
      requiredOnFirstRun: raw.requiredOnFirstRun === true,
      license: String(raw.license || ''),
      licenseUrl: String(raw.licenseUrl || ''),
      downloadBytes: Math.max(0, Number(raw.downloadBytes || 0)),
      source: String(raw.source || ''),
      integrity,
      inUseBy: Array.isArray(raw.inUseBy) ? raw.inUseBy.map(String) : [],
    }
  }
  const summary = (source: SettingsRecord, fallbackMessage: string) => ({
    ...resourceSummaryFallback(String(source.message || fallbackMessage)),
    ...source,
    ready: Boolean(source.ready),
    state: source.state === 'ready' || source.state === 'partial' ? source.state : 'missing',
    message: String(source.message || fallbackMessage),
    details: Array.isArray(source.details) ? source.details.map(String) : [],
    metadata: metadata(source),
  })
  return {
    modelRoots: {
      live2d: String(modelRoots.live2d || ''),
      vrm: String(modelRoots.vrm || ''),
    },
    localCounts: {
      live2d: Number(localCounts.live2d || 0),
      vrm: Number(localCounts.vrm || 0),
    },
    soulx: {
      ...summary(soulx, 'SoulX resources unavailable'),
      serviceDir: String(soulx.serviceDir || ''),
      launcherPath: String(soulx.launcherPath || ''),
      checkpointPath: typeof soulx.checkpointPath === 'string' ? soulx.checkpointPath : null,
      checkpointCandidates: Array.isArray(soulx.checkpointCandidates) ? soulx.checkpointCandidates.map(String) : [],
      preprocessDir: String(soulx.preprocessDir || ''),
      referenceDir: String(soulx.referenceDir || ''),
      hasReferenceAudio: Boolean(soulx.hasReferenceAudio),
    },
    sherpa: {
      ...summary(sherpa, 'Sherpa resources unavailable'),
      assetUrl: String(sherpa.assetUrl || ''),
      modelPath: String(sherpa.modelPath || ''),
      tokensPath: String(sherpa.tokensPath || ''),
      format: 'sensevoice-offline',
      validated: Boolean(sherpa.validated),
      validationPath: typeof sherpa.validationPath === 'string' ? sherpa.validationPath : null,
    },
    sherpaOnline: {
      ...summary(sherpaOnline, 'Sherpa streaming resources unavailable'),
      assetUrl: String(sherpaOnline.assetUrl || ''),
      modelPath: String(sherpaOnline.modelPath || ''),
      tokensPath: String(sherpaOnline.tokensPath || ''),
      format: 'zipformer2-ctc-online',
      validated: Boolean(sherpaOnline.validated),
      validationPath: typeof sherpaOnline.validationPath === 'string' ? sherpaOnline.validationPath : null,
    },
    embedding: {
      ...summary(embedding, 'Embedding resources unavailable'),
      modelName: String(embedding.modelName || ''),
      cachePath: typeof embedding.cachePath === 'string' ? embedding.cachePath : null,
      cacheRoot: String(embedding.cacheRoot || ''),
    },
    tts: {
      ...summary(ttsStatus, 'TTS resources unavailable'),
      character: String(ttsStatus.character || ''),
      cacheDir: String(ttsStatus.cacheDir || ''),
      modelDir: String(ttsStatus.modelDir || ''),
    },
    activeDownloads,
    resumableDownloads,
  }
}

const storageCategoryIds = new Set<StorageCategoryId>(['tts_audio', 'runtime_temp', 'memory', 'visual_frames'])

export const normalizeStorageStatus = (value: unknown): StorageStatusPayload | null => {
  if (!isPlainRecord(value) || !Array.isArray(value.categories)) return null
  const categories = value.categories.flatMap((rawCategory) => {
    if (!isPlainRecord(rawCategory)) return []
    const id = String(rawCategory.id || '') as StorageCategoryId
    if (!storageCategoryIds.has(id)) return []
    const action = rawCategory.action === 'delete_files' || rawCategory.action === 'compact' ? rawCategory.action : 'none'
    return [{
      id,
      bytes: Math.max(0, Number(rawCategory.bytes || 0)),
      files: Math.max(0, Number(rawCategory.files || 0)),
      action,
      persistence: rawCategory.persistence === 'disk' ? 'disk' as const : 'memory_only' as const,
      failed_files: Math.max(0, Number(rawCategory.failed_files || 0)),
    }]
  })
  return {
    categories,
    total_bytes: Math.max(0, Number(value.total_bytes || 0)),
    reclaimable_bytes: Math.max(0, Number(value.reclaimable_bytes || 0)),
  }
}
