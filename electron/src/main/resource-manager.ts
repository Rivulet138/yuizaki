import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { dialog } from 'electron'
import type { PetModelCatalog } from './pet-model-catalog'
import type {
  EmbeddingResourceStatus,
  ManagedResourceMetadata,
  ModelResourceStatusPayload,
  ManagedModelResourceId,
  ResourceCancelResult,
  ResourceCommandResult,
  ResourceDownloadProgress,
  ResourceFailureCode,
  ResourceProgressPhase,
  ResourceProgressSnapshot,
  ResourceRemovalResult,
  ResumableResourceDownload,
  PetImportableModelType,
  SherpaResourceStatus,
  SoulxResourceStatus,
  TtsResourceStatus,
} from '../shared/resource-manager'
import { resolvePythonRuntime } from './python-runtime'

type StoredSettings = {
  asr?: {
    provider?: string
    sherpa_model_path?: string
    sherpa_tokens_path?: string
  }
  memory?: {
    embedding_model?: string
  }
  tts?: {
    provider?: string
    genie_character?: string
    genie_model_dir?: string
    lang?: string
    ref_audio?: string
    ref_text?: string
  }
  svc?: {
    provider?: string
  }
}

type CommandExecution = {
  success: boolean
  cancelled: boolean
  code: number
  stdout: string[]
  stderr: string[]
  message: string
}

const resolveProjectRoot = (): string => {
  const explicitRoot = process.env['YUIZAKI_PROJECT_ROOT']?.trim()
  if (explicitRoot) {
    return path.resolve(explicitRoot)
  }

  const cwd = process.cwd()
  if (fs.existsSync(path.join(cwd, 'python', 'app.py'))) {
    return cwd
  }
  if (fs.existsSync(path.join(cwd, 'app.py'))) {
    return path.resolve(cwd, '..')
  }
  return path.resolve(__dirname, '../../..')
}

const PROJECT_ROOT = resolveProjectRoot()
const RESOURCE_LOCK_PATH = path.join(PROJECT_ROOT, 'resources.lock.json')

type LockedResourceSource = {
  url?: string
  sha256?: string
  repo?: string
  revision?: string
  package?: string
  version?: string
}

type LockedResource = {
  label: string
  version: string
  kind: 'archive' | 'huggingface_snapshot' | 'huggingface_bundle' | 'package_managed'
  license: string
  licenseUrl: string
  downloadBytes: number
  sources: LockedResourceSource[]
}

type ResourceLock = {
  schemaVersion: number
  resources: Record<ManagedModelResourceId, LockedResource>
}

const readResourceLock = (): ResourceLock => {
  const lock = JSON.parse(fs.readFileSync(RESOURCE_LOCK_PATH, 'utf8')) as ResourceLock
  if (lock.schemaVersion !== 1) {
    throw new Error(`Unsupported resource lock schema: ${lock.schemaVersion}`)
  }
  return lock
}

const RESOURCE_LOCK = readResourceLock()
const lockedResource = (resourceId: ManagedModelResourceId): LockedResource => RESOURCE_LOCK.resources[resourceId]
const lockedSource = (resourceId: ManagedModelResourceId, index = 0): LockedResourceSource => {
  const source = lockedResource(resourceId).sources[index]
  if (!source) throw new Error(`Missing source ${index} for resource ${resourceId}`)
  return source
}
const resourceMetadata = (resourceId: ManagedModelResourceId, inUseBy: string[] = []): ManagedResourceMetadata => {
  const resource = lockedResource(resourceId)
  const source = lockedSource(resourceId)
  return {
    label: resource.label,
    version: resource.version,
    license: resource.license,
    licenseUrl: resource.licenseUrl,
    downloadBytes: resource.downloadBytes,
    source: source.repo ?? source.package ?? source.url ?? '',
    integrity: resource.kind === 'archive'
      ? 'sha256'
      : resource.kind === 'package_managed'
        ? source.revision ? 'package+revision' : 'package'
        : 'revision',
    inUseBy,
  }
}

const DEFAULT_SHERPA_ASSET_URL = lockedSource('sherpa').url ?? ''
const DEFAULT_SHERPA_SHA256 = lockedSource('sherpa').sha256 ?? ''
const DEFAULT_SHERPA_ONLINE_ASSET_URL = lockedSource('sherpa_online').url ?? ''
const DEFAULT_SHERPA_ONLINE_SHA256 = lockedSource('sherpa_online').sha256 ?? ''
const PYTHON_DIR = path.join(PROJECT_ROOT, 'python')
const PYTHON_EXE = resolvePythonRuntime(PYTHON_DIR).executable
const SETTINGS_PATH = path.join(PYTHON_DIR, 'config', 'settings.json')
const SHERPA_DIR = path.join(PYTHON_DIR, '.cache', 'sherpa-onnx', 'sensevoice')
const DEFAULT_SHERPA_MODEL_PATH = path.join(SHERPA_DIR, 'model.int8.onnx')
const DEFAULT_SHERPA_TOKENS_PATH = path.join(SHERPA_DIR, 'tokens.txt')
const SHERPA_PARTIAL_ARCHIVE_PATH = path.join(SHERPA_DIR, '.download', 'sherpa-sensevoice.tar.bz2.part')
const SHERPA_ONLINE_DIR = path.join(PYTHON_DIR, '.cache', 'sherpa-onnx', 'streaming-zipformer-small-ctc-zh')
const DEFAULT_SHERPA_ONLINE_MODEL_PATH = path.join(SHERPA_ONLINE_DIR, 'model.int8.onnx')
const DEFAULT_SHERPA_ONLINE_TOKENS_PATH = path.join(SHERPA_ONLINE_DIR, 'tokens.txt')
const SHERPA_ONLINE_PARTIAL_ARCHIVE_PATH = path.join(SHERPA_ONLINE_DIR, '.download', 'sherpa-streaming.tar.bz2.part')
const HF_CACHE_ROOT = path.join(PYTHON_DIR, '.cache', 'huggingface')
const DEFAULT_EMBEDDING_MODEL = 'Qwen/Qwen3-Embedding-0.6B'
const DEFAULT_GENIE_ROOT = path.join(PYTHON_DIR, '.cache', 'GenieData')
const DEFAULT_GENIE_DATA_DIR = path.join(DEFAULT_GENIE_ROOT, 'GenieData')
const GENIE_CHARACTER_ROOT = path.join(PYTHON_DIR, 'CharacterModels', 'v2ProPlus')
const GENIE_CHARACTER_METADATA_ROOT = path.join(HF_CACHE_ROOT, 'download', 'CharacterModels', 'v2ProPlus')
const SOULX_SERVICE_DIR = path.join(PROJECT_ROOT, 'services', 'soulx-svc')
const SOULX_DOWNLOAD_SCRIPT = path.join(SOULX_SERVICE_DIR, 'download_models.py')
const SOULX_LAUNCHER = path.join(SOULX_SERVICE_DIR, 'docker-compose.yml')
const SOULX_MODEL_DIR = path.join(SOULX_SERVICE_DIR, 'models', 'SoulX-Singer')
const SOULX_PREPROCESS_DIR = path.join(SOULX_SERVICE_DIR, 'models', 'SoulX-Singer-Preprocess')
const SOULX_REFERENCE_DIR = path.join(SOULX_SERVICE_DIR, 'references')
const SOULX_CHECKPOINT_CANDIDATES = [
  path.join(SOULX_MODEL_DIR, 'model-svc.pt'),
  path.join(SOULX_MODEL_DIR, 'model.pt'),
]

const RESOURCE_IDS = new Set<ManagedModelResourceId>(['soulx', 'sherpa', 'sherpa_online', 'embedding', 'tts'])
const resourcePreparation = new Map<ManagedModelResourceId, Promise<ResourceCommandResult>>()
const resourceProcesses = new Map<ManagedModelResourceId, ReturnType<typeof spawn>>()
const resourceCancellationRequests = new Set<ManagedModelResourceId>()
const resourceProgress = new Map<ManagedModelResourceId, ResourceDownloadProgress>()
const RESOURCE_PROGRESS_PREFIX = 'YUIZAKI_RESOURCE_PROGRESS '
const RESOURCE_PROGRESS_PHASES = new Set<ResourceProgressPhase>([
  'preparing',
  'downloading',
  'verifying',
  'extracting',
  'installing',
  'cancelling',
])

const beginResourceProgress = (resourceId: ManagedModelResourceId): void => {
  const timestamp = new Date().toISOString()
  const expectedBytes = lockedResource(resourceId).downloadBytes
  resourceProgress.set(resourceId, {
    resourceId,
    phase: 'preparing',
    message: 'Preparing resource download',
    bytesDownloaded: null,
    bytesTotal: expectedBytes > 0 ? expectedBytes : null,
    percent: null,
    startedAt: timestamp,
    updatedAt: timestamp,
  })
}

export const parseResourceProgressLine = (line: string): Partial<ResourceDownloadProgress> | null => {
  if (!line.startsWith(RESOURCE_PROGRESS_PREFIX)) return null
  try {
    const payload = JSON.parse(line.slice(RESOURCE_PROGRESS_PREFIX.length)) as Record<string, unknown>
    if (!RESOURCE_PROGRESS_PHASES.has(payload['phase'] as ResourceProgressPhase)) return null
    const bytesDownloaded = Number.isFinite(Number(payload['bytesDownloaded']))
      ? Math.max(0, Number(payload['bytesDownloaded']))
      : null
    const bytesTotal = Number.isFinite(Number(payload['bytesTotal'])) && Number(payload['bytesTotal']) >= 0
      ? Number(payload['bytesTotal'])
      : null
    return {
      phase: payload['phase'] as ResourceProgressPhase,
      message: String(payload['message'] || ''),
      bytesDownloaded,
      bytesTotal,
    }
  } catch {
    return null
  }
}

const updateResourceProgress = (resourceId: ManagedModelResourceId, line: string): boolean => {
  const patch = parseResourceProgressLine(line)
  if (!patch) return false
  const current = resourceProgress.get(resourceId)
  if (!current) return true
  const bytesDownloaded = patch.bytesDownloaded ?? current.bytesDownloaded
  const bytesTotal = patch.bytesTotal ?? current.bytesTotal
  const percent = bytesDownloaded !== null && bytesTotal !== null && bytesTotal > 0
    ? Math.min(100, Math.round(bytesDownloaded * 100 / bytesTotal))
    : null
  resourceProgress.set(resourceId, {
    ...current,
    ...patch,
    bytesDownloaded,
    bytesTotal,
    percent,
    updatedAt: new Date().toISOString(),
  })
  return true
}

export type ProcessTreeTerminationPlan =
  | { kind: 'windows'; command: 'taskkill'; args: string[] }
  | { kind: 'posix'; processGroupId: number }

export const buildProcessTreeTerminationPlan = (
  platform: NodeJS.Platform,
  pid: number,
): ProcessTreeTerminationPlan => platform === 'win32'
  ? { kind: 'windows', command: 'taskkill', args: ['/pid', String(pid), '/T', '/F'] }
  : { kind: 'posix', processGroupId: -pid }

const terminateProcessTree = (child: ReturnType<typeof spawn>): void => {
  const pid = child.pid
  if (!pid) {
    child.kill()
    return
  }
  const plan = buildProcessTreeTerminationPlan(process.platform, pid)
  if (plan.kind === 'windows') {
    const terminator = spawn(plan.command, plan.args, { windowsHide: true, stdio: 'ignore' })
    terminator.on('error', () => child.kill())
    return
  }
  try {
    process.kill(plan.processGroupId, 'SIGTERM')
  } catch {
    child.kill('SIGTERM')
  }
  setTimeout(() => {
    if (child.exitCode !== null) return
    try {
      process.kill(plan.processGroupId, 'SIGKILL')
    } catch {
      child.kill('SIGKILL')
    }
  }, 1_500).unref()
}

const buildSummary = (checks: Array<[boolean, string]>): { state: 'missing' | 'partial' | 'ready'; message: string; details: string[]; ready: boolean } => {
  const details = checks.filter(([ok]) => !ok).map(([, message]) => message)
  if (details.length === 0) {
    return {
      ready: true,
      state: 'ready',
      message: 'Ready',
      details: [],
    }
  }
  if (details.length === checks.length) {
    return {
      ready: false,
      state: 'missing',
      message: 'Missing required assets',
      details,
    }
  }
  return {
    ready: false,
    state: 'partial',
    message: 'Partially prepared',
    details,
  }
}

const readStoredSettings = (): StoredSettings => {
  if (!fs.existsSync(SETTINGS_PATH)) {
    return {}
  }
  try {
    return JSON.parse(fs.readFileSync(SETTINGS_PATH, 'utf8')) as StoredSettings
  } catch {
    return {}
  }
}

export const readResumableResourceDownload = (
  resourceId: ManagedModelResourceId,
  partialPath: string,
  fallbackTotal: number | null = null,
): ResumableResourceDownload | null => {
  if (!fs.existsSync(partialPath)) return null
  const stat = fs.statSync(partialPath)
  if (!stat.isFile() || stat.size <= 0) return null
  let bytesTotal = fallbackTotal && fallbackTotal >= stat.size ? fallbackTotal : null
  let updatedAt = stat.mtime.toISOString()
  const journalPath = `${partialPath}.json`
  if (fs.existsSync(journalPath)) {
    try {
      const journal = JSON.parse(fs.readFileSync(journalPath, 'utf8')) as { bytesTotal?: unknown; updatedAt?: unknown }
      const journalTotal = Number(journal.bytesTotal)
      if (Number.isFinite(journalTotal) && journalTotal >= stat.size) bytesTotal = journalTotal
      const journalUpdatedAt = String(journal.updatedAt || '')
      if (!Number.isNaN(Date.parse(journalUpdatedAt))) updatedAt = new Date(journalUpdatedAt).toISOString()
    } catch {
      // The partial file remains resumable when its optional journal is unreadable.
    }
  }
  return {
    resourceId,
    bytesDownloaded: stat.size,
    bytesTotal,
    percent: bytesTotal && bytesTotal > 0 ? Math.min(100, Math.round(stat.size * 100 / bytesTotal)) : null,
    updatedAt,
  }
}

const pathUsage = (targetPath: string): { bytes: number; mtimeMs: number } => {
  if (!fs.existsSync(targetPath)) return { bytes: 0, mtimeMs: 0 }
  try {
    const stat = fs.lstatSync(targetPath)
    if (!stat.isDirectory() || stat.isSymbolicLink()) {
      return { bytes: stat.size, mtimeMs: stat.mtimeMs }
    }
    return fs.readdirSync(targetPath, { withFileTypes: true }).reduce((usage, entry) => {
      const child = pathUsage(path.join(targetPath, entry.name))
      return {
        bytes: usage.bytes + child.bytes,
        mtimeMs: Math.max(usage.mtimeMs, child.mtimeMs, stat.mtimeMs),
      }
    }, { bytes: 0, mtimeMs: stat.mtimeMs })
  } catch {
    return { bytes: 0, mtimeMs: 0 }
  }
}

export const readResumableResourceDirectories = (
  resourceId: ManagedModelResourceId,
  candidatePaths: readonly string[],
): ResumableResourceDownload | null => {
  const roots = [...new Set(candidatePaths.map((candidate) => path.resolve(candidate)))]
    .filter((candidate, _index, all) => !all.some((parent) => {
      if (parent === candidate) return false
      const relative = path.relative(parent, candidate)
      return relative !== '' && relative !== '..' && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative)
    }))
  const usage = roots.reduce((total, candidate) => {
    const current = pathUsage(candidate)
    return {
      bytes: total.bytes + current.bytes,
      mtimeMs: Math.max(total.mtimeMs, current.mtimeMs),
    }
  }, { bytes: 0, mtimeMs: 0 })
  if (usage.bytes <= 0) return null
  return {
    resourceId,
    bytesDownloaded: usage.bytes,
    bytesTotal: null,
    percent: null,
    updatedAt: new Date(usage.mtimeMs || Date.now()).toISOString(),
  }
}

const huggingFaceRepoCachePaths = (repoId: string): string[] => {
  const repoCacheName = `models--${repoId.replace(/\//g, '--')}`
  return [HF_CACHE_ROOT, path.join(HF_CACHE_ROOT, 'hub')].map((root) => path.join(root, repoCacheName))
}

const huggingFaceRepoLockPaths = (repoId: string): string[] => {
  const repoCacheName = `models--${repoId.replace(/\//g, '--')}`
  return [HF_CACHE_ROOT, path.join(HF_CACHE_ROOT, 'hub')].map((root) => path.join(root, '.locks', repoCacheName))
}

const normalizeGenieCharacter = (value: string | undefined): string => {
  const character = String(value || '').trim()
  return character && character !== '.' && character !== '..' && !/[\\/\0]/.test(character) ? character : 'feibi'
}
const genieCharacterDir = (character: string): string => path.join(GENIE_CHARACTER_ROOT, normalizeGenieCharacter(character))
const genieCharacterMetadataDir = (character: string): string => path.join(GENIE_CHARACTER_METADATA_ROOT, normalizeGenieCharacter(character))

const resumableResourceDownloads = (
  embedding: EmbeddingResourceStatus,
  tts: TtsResourceStatus,
): ResumableResourceDownload[] => {
  const downloads = ([
    ['sherpa', SHERPA_PARTIAL_ARCHIVE_PATH],
    ['sherpa_online', SHERPA_ONLINE_PARTIAL_ARCHIVE_PATH],
  ] as const).flatMap(([resourceId, partialPath]) => {
    if (resourcePreparation.has(resourceId) || resourceProcesses.has(resourceId)) return []
    const state = readResumableResourceDownload(resourceId, partialPath, lockedResource(resourceId).downloadBytes)
    return state ? [state] : []
  })

  if (!embedding.ready && !resourcePreparation.has('embedding') && !resourceProcesses.has('embedding')) {
    const state = readResumableResourceDirectories('embedding', huggingFaceRepoCachePaths(embedding.modelName))
    if (state) downloads.push(state)
  }
  if (!tts.ready && !resourcePreparation.has('tts') && !resourceProcesses.has('tts')) {
    const state = readResumableResourceDirectories('tts', [
      DEFAULT_GENIE_ROOT,
      genieCharacterDir(tts.character),
      genieCharacterMetadataDir(tts.character),
      ...huggingFaceRepoCachePaths('High-Logic/Genie'),
    ])
    if (state) downloads.push(state)
  }
  return downloads
}

const resolveBackendRelativePath = (value: string | undefined, fallback: string): string => {
  const trimmed = String(value || '').trim()
  if (!trimmed) {
    return fallback
  }
  return path.isAbsolute(trimmed) ? trimmed : path.join(PYTHON_DIR, trimmed)
}

const resolveEmbeddingSnapshot = (modelName: string): string | null => {
  const repoCacheName = `models--${modelName.replace(/\//g, '--')}`
  for (const root of [HF_CACHE_ROOT, path.join(HF_CACHE_ROOT, 'hub')]) {
    const modelRoot = path.join(root, repoCacheName)
    const snapshotsDir = path.join(modelRoot, 'snapshots')
    if (!fs.existsSync(snapshotsDir)) {
      continue
    }
    const refsMain = path.join(modelRoot, 'refs', 'main')
    if (fs.existsSync(refsMain)) {
      const revision = fs.readFileSync(refsMain, 'utf8').trim()
      const snapshotPath = path.join(snapshotsDir, revision)
      if (fs.existsSync(snapshotPath)) {
        return snapshotPath
      }
    }
    const snapshots = fs.readdirSync(snapshotsDir).flatMap((name) => {
      const snapshotPath = path.join(snapshotsDir, name)
      const stat = fs.statSync(snapshotPath)
      return stat.isDirectory() ? [{ path: snapshotPath, mtimeMs: stat.mtimeMs }] : []
    })
    if (snapshots.length > 0) {
      snapshots.sort((left, right) => right.mtimeMs - left.mtimeMs)
      return snapshots[0]?.path ?? null
    }
  }
  return null
}

const findSoulxCheckpoint = (): string | null => SOULX_CHECKPOINT_CANDIDATES.find((candidate) => fs.existsSync(candidate)) ?? null

const hasSoulxReferenceAudio = (): boolean => {
  const directCandidates = [
    path.join(SOULX_REFERENCE_DIR, '0.wav'),
    path.join(SOULX_REFERENCE_DIR, '0.mp3'),
    path.join(SOULX_REFERENCE_DIR, '0.flac'),
    path.join(SOULX_REFERENCE_DIR, '0.m4a'),
    path.join(SOULX_REFERENCE_DIR, 'default.wav'),
    path.join(SOULX_REFERENCE_DIR, 'default.mp3'),
    path.join(SOULX_REFERENCE_DIR, 'default.flac'),
  ]
  if (directCandidates.some((candidate) => fs.existsSync(candidate))) {
    return true
  }
  const nestedDir = path.join(SOULX_REFERENCE_DIR, '0')
  if (!fs.existsSync(nestedDir) || !fs.statSync(nestedDir).isDirectory()) {
    return false
  }
  return ['prompt.wav', 'reference.wav', 'voice.wav', 'prompt.mp3', 'reference.mp3']
    .some((name) => fs.existsSync(path.join(nestedDir, name)))
}

const buildSoulxStatus = (settings: StoredSettings): SoulxResourceStatus => {
  const checkpointPath = findSoulxCheckpoint()
  const summary = buildSummary([
    [fs.existsSync(SOULX_SERVICE_DIR), 'SoulX service directory is missing'],
    [Boolean(checkpointPath), 'SoulX checkpoint is missing'],
    [fs.existsSync(SOULX_PREPROCESS_DIR), 'SoulX preprocess assets are missing'],
  ])

  return {
    ...summary,
    metadata: resourceMetadata('soulx', settings.svc?.provider === 'soulx-service' ? ['音色转换'] : []),
    serviceDir: SOULX_SERVICE_DIR,
    launcherPath: SOULX_LAUNCHER,
    checkpointPath,
    checkpointCandidates: SOULX_CHECKPOINT_CANDIDATES,
    preprocessDir: SOULX_PREPROCESS_DIR,
    referenceDir: SOULX_REFERENCE_DIR,
    hasReferenceAudio: hasSoulxReferenceAudio(),
  }
}

const buildSherpaStatus = (settings: StoredSettings): SherpaResourceStatus => {
  const usedForFinalAsr = settings.asr?.provider === 'sherpa-onnx'
    || settings.asr?.provider === 'sherpa-onnx-online'
  const useConfiguredPaths = settings.asr?.provider === 'sherpa-onnx'
  const modelPath = resolveBackendRelativePath(useConfiguredPaths ? settings.asr?.sherpa_model_path : '', DEFAULT_SHERPA_MODEL_PATH)
  const tokensPath = resolveBackendRelativePath(useConfiguredPaths ? settings.asr?.sherpa_tokens_path : '', DEFAULT_SHERPA_TOKENS_PATH)
  const summary = buildSummary([
    [fs.existsSync(modelPath), 'Sherpa SenseVoice model file is missing'],
    [fs.existsSync(tokensPath), 'Sherpa SenseVoice tokens file is missing'],
  ])

  return {
    ...summary,
    metadata: resourceMetadata('sherpa', usedForFinalAsr ? ['句末语音识别'] : []),
    assetUrl: DEFAULT_SHERPA_ASSET_URL,
    modelPath,
    tokensPath,
    format: 'sensevoice-offline',
    validated: false,
    validationPath: null,
  }
}

const hasCurrentSherpaOnlineValidation = (modelPath: string, tokensPath: string, validationPath: string): boolean => {
  if (!fs.existsSync(validationPath)) {
    return false
  }
  try {
    const payload = JSON.parse(fs.readFileSync(validationPath, 'utf8')) as {
      format?: string
      model?: { size?: number; mtime_ns?: string }
      tokens?: { size?: number; mtime_ns?: string }
    }
    const modelStat = fs.statSync(modelPath, { bigint: true })
    const tokensStat = fs.statSync(tokensPath, { bigint: true })
    return payload.format === 'sherpa-onnx-online-zipformer2-ctc'
      && BigInt(payload.model?.size ?? -1) === modelStat.size
      && BigInt(payload.model?.mtime_ns ?? '-1') === modelStat.mtimeNs
      && BigInt(payload.tokens?.size ?? -1) === tokensStat.size
      && BigInt(payload.tokens?.mtime_ns ?? '-1') === tokensStat.mtimeNs
  } catch {
    return false
  }
}

const buildSherpaOnlineStatus = (settings: StoredSettings): SherpaResourceStatus => {
  const useConfiguredPaths = settings.asr?.provider === 'sherpa-onnx-online'
  const modelPath = resolveBackendRelativePath(useConfiguredPaths ? settings.asr?.sherpa_model_path : '', DEFAULT_SHERPA_ONLINE_MODEL_PATH)
  const tokensPath = resolveBackendRelativePath(useConfiguredPaths ? settings.asr?.sherpa_tokens_path : '', DEFAULT_SHERPA_ONLINE_TOKENS_PATH)
  const validationPath = path.join(path.dirname(modelPath), '.yuizaki-validation.json')
  const modelExists = fs.existsSync(modelPath)
  const tokensExist = fs.existsSync(tokensPath)
  const filesExist = modelExists && tokensExist
  const validated = filesExist && hasCurrentSherpaOnlineValidation(modelPath, tokensPath, validationPath)
  const summary = buildSummary([
    [modelExists, 'Sherpa streaming Zipformer2 CTC model file is missing'],
    [tokensExist, 'Sherpa streaming tokens file is missing'],
    [validated, 'Sherpa streaming model has not passed the Yuizaki load validation'],
  ])

  return {
    ...summary,
    metadata: resourceMetadata('sherpa_online', settings.asr?.provider === 'sherpa-onnx-online' ? ['流式语音识别'] : []),
    assetUrl: DEFAULT_SHERPA_ONLINE_ASSET_URL,
    modelPath,
    tokensPath,
    format: 'zipformer2-ctc-online',
    validated,
    validationPath,
  }
}

const buildEmbeddingStatus = (settings: StoredSettings): EmbeddingResourceStatus => {
  const modelName = settings.memory?.embedding_model?.trim() || DEFAULT_EMBEDDING_MODEL
  const cachePath = resolveEmbeddingSnapshot(modelName)
  const metadata = modelName === DEFAULT_EMBEDDING_MODEL
    ? resourceMetadata('embedding')
    : {
        label: modelName,
        version: 'unlocked',
        license: 'unverified',
        licenseUrl: '',
        downloadBytes: 0,
        source: modelName,
        integrity: 'unverified' as const,
        inUseBy: ['长期记忆'],
      }
  const summary = buildSummary([
    [Boolean(cachePath), 'Embedding model snapshot is missing'],
  ])

  return {
    ...summary,
    metadata,
    modelName,
    cachePath,
    cacheRoot: HF_CACHE_ROOT,
  }
}

const buildTtsStatus = (settings: StoredSettings): TtsResourceStatus => {
  const configuredValue = settings.tts?.genie_model_dir?.trim() || ''
  const configuredModelDir = configuredValue ? resolveBackendRelativePath(configuredValue, configuredValue) : null
  const character = normalizeGenieCharacter(settings.tts?.genie_character)
  const modelDir = configuredModelDir ?? genieCharacterDir(character)
  const modelFilesReady = (root: string): boolean => [
    't2s_encoder_fp32.onnx',
    't2s_first_stage_decoder_fp32.onnx',
    't2s_stage_decoder_fp32.onnx',
    'vits_fp32.onnx',
    'prompt_encoder_fp32.onnx',
  ].every((name) => fs.existsSync(path.join(root, name)))
  const checks: Array<[boolean, string]> = [
    [fs.existsSync(path.join(DEFAULT_GENIE_DATA_DIR, 'speaker_encoder.onnx')), 'Genie speaker encoder is missing'],
    [fs.existsSync(path.join(DEFAULT_GENIE_DATA_DIR, 'chinese-hubert-base')), 'Genie Hubert assets are missing'],
    [fs.existsSync(path.join(DEFAULT_GENIE_DATA_DIR, 'G2P')), 'Genie G2P assets are missing'],
    [fs.existsSync(modelDir), configuredModelDir ? 'Configured Genie model directory is missing' : 'Genie character model is missing'],
  ]
  if (configuredModelDir) {
    checks.push([modelFilesReady(modelDir), 'Genie character model files are incomplete'])
    const refAudio = resolveBackendRelativePath(settings.tts?.ref_audio, '')
    checks.push([Boolean(refAudio) && fs.existsSync(refAudio), 'Genie reference audio is missing'])
    checks.push([Boolean(settings.tts?.ref_text?.trim()), 'Genie reference text is missing'])
  } else {
    checks.push(
      [fs.existsSync(path.join(modelDir, 'tts_models')), 'Genie character TTS models are missing'],
      [fs.existsSync(path.join(modelDir, 'prompt_wav')), 'Genie character prompt audio is missing'],
      [fs.existsSync(path.join(modelDir, 'prompt_wav.json')), 'Genie character prompt metadata is missing'],
    )
  }
  const summary = buildSummary(checks)

  return {
    ...summary,
    metadata: resourceMetadata('tts', settings.tts?.provider === 'genie-tts' ? ['语音合成'] : []),
    character,
    cacheDir: DEFAULT_GENIE_DATA_DIR,
    modelDir,
  }
}

const ensureParentDir = (filePath: string): void => {
  fs.mkdirSync(path.dirname(filePath), { recursive: true })
}

const copySoulxReferenceAudio = (sourcePath: string, speakerId = '0'): string => {
  const resolvedSource = path.resolve(sourcePath)
  if (!fs.existsSync(resolvedSource) || !fs.statSync(resolvedSource).isFile()) {
    throw new Error(`Reference audio not found: ${resolvedSource}`)
  }
  const ext = path.extname(resolvedSource).toLowerCase()
  if (!['.wav', '.mp3', '.flac', '.m4a'].includes(ext)) {
    throw new Error('Reference audio must be .wav, .mp3, .flac, or .m4a')
  }
  const targetPath = path.join(SOULX_REFERENCE_DIR, `${speakerId}${ext}`)
  ensureParentDir(targetPath)
  fs.copyFileSync(resolvedSource, targetPath)
  return targetPath
}

const runCommand = async (
  command: string,
  args: string[],
  options: { cwd?: string; env?: NodeJS.ProcessEnv; resourceId?: ManagedModelResourceId } = {},
): Promise<CommandExecution> =>
  new Promise((resolve) => {
    const stdout: string[] = []
    const stderr: string[] = []
    const child = spawn(command, args, {
      cwd: options.cwd ?? PROJECT_ROOT,
      env: {
        ...process.env,
        ...options.env,
      },
      windowsHide: true,
      detached: process.platform !== 'win32',
    })
    if (options.resourceId) {
      resourceProcesses.set(options.resourceId, child)
      if (resourceCancellationRequests.has(options.resourceId)) {
        terminateProcessTree(child)
      }
    }

    let stdoutBuffer = ''
    const consumeStdoutLine = (line: string) => {
      const text = line.trim()
      if (!text) return
      if (options.resourceId && updateResourceProgress(options.resourceId, text)) return
      stdout.push(text)
    }
    child.stdout.on('data', (chunk) => {
      stdoutBuffer += String(chunk)
      const lines = stdoutBuffer.split(/\r?\n/)
      stdoutBuffer = lines.pop() ?? ''
      lines.forEach(consumeStdoutLine)
    })
    child.stderr.on('data', (chunk) => {
      const text = String(chunk).trim()
      if (text) {
        stderr.push(...text.split(/\r?\n/).filter(Boolean))
      }
    })
    child.on('error', (error) => {
      stderr.push(String(error))
    })
    child.on('close', (code) => {
      consumeStdoutLine(stdoutBuffer)
      const cancelled = Boolean(options.resourceId && resourceCancellationRequests.has(options.resourceId))
      if (options.resourceId && resourceProcesses.get(options.resourceId) === child) {
        resourceProcesses.delete(options.resourceId)
        resourceCancellationRequests.delete(options.resourceId)
      }
      const exitCode = code ?? 1
      resolve({
        success: exitCode === 0 && !cancelled,
        cancelled,
        code: exitCode,
        stdout,
        stderr,
        message: cancelled ? 'Resource download cancelled' : exitCode === 0 ? 'Command completed' : `Command failed with exit code ${exitCode}`,
      })
    })
  })

const ensurePythonModule = async (moduleName: string, packageName: string = moduleName): Promise<CommandExecution | null> => {
  const probe = await runCommand(PYTHON_EXE, ['-c', `import ${moduleName}`], { cwd: PYTHON_DIR })
  if (probe.success) {
    return null
  }
  return runCommand(PYTHON_EXE, ['-m', 'pip', 'install', packageName], { cwd: PYTHON_DIR })
}

type ResourceFailure = {
  errorCode: ResourceFailureCode
  retryable: boolean
  message: string
}

export const classifyResourceFailure = (output: string, cancelled = false): ResourceFailure => {
  if (cancelled) return { errorCode: 'cancelled', retryable: true, message: 'Resource download cancelled' }
  const text = output.toLowerCase()
  if (/no space left|enospc|disk (?:is )?full|insufficient disk space/.test(text)) {
    return { errorCode: 'disk_full', retryable: false, message: 'Insufficient disk space' }
  }
  if (/sha-?256|checksum|integrity|digest mismatch|hash mismatch/.test(text)) {
    return { errorCode: 'integrity_failed', retryable: true, message: 'Resource integrity verification failed' }
  }
  if (/\b(?:401|403)\b|unauthori[sz]ed|forbidden|gated repo|authentication required|invalid token/.test(text)) {
    return { errorCode: 'authentication_required', retryable: false, message: 'Resource access denied' }
  }
  if (/timed? out|timeout|readtimeout|connecttimeout/.test(text)) {
    return { errorCode: 'network_timeout', retryable: true, message: 'Resource download timed out' }
  }
  if (/getaddrinfo|name resolution|temporary failure in name resolution|network is unreachable|connection (?:refused|reset|aborted)|failed to establish a new connection/.test(text)) {
    return { errorCode: 'network_unreachable', retryable: true, message: 'Resource network unavailable' }
  }
  if (/modulenotfounderror|no module named|could not find a version that satisfies|resolutionimpossible|failed building wheel/.test(text)) {
    return { errorCode: 'dependency_failed', retryable: false, message: 'Resource dependency installation failed' }
  }
  return { errorCode: 'unknown', retryable: false, message: 'Resource preparation failed' }
}

const buildResult = (execution: CommandExecution, status: ModelResourceStatusPayload, successMessage: string): ResourceCommandResult => {
  const detail = execution.stderr[execution.stderr.length - 1] || execution.message
  const failure = execution.success ? null : classifyResourceFailure(`${execution.stderr.join('\n')}\n${execution.stdout.join('\n')}\n${execution.message}`, execution.cancelled)
  return {
    success: execution.success,
    message: execution.success ? successMessage : failure?.message || detail,
    errorCode: failure?.errorCode ?? null,
    retryable: failure?.retryable ?? false,
    stdout: execution.stdout,
    stderr: execution.stderr,
    status,
  }
}

export const getModelResourceStatus = (petModelCatalog: PetModelCatalog): ModelResourceStatusPayload => {
  const settings = readStoredSettings()
  const embedding = buildEmbeddingStatus(settings)
  const tts = buildTtsStatus(settings)
  return {
    modelRoots: petModelCatalog.getLocalModelRoots(),
    localCounts: petModelCatalog.getLocalModelCounts(),
    soulx: buildSoulxStatus(settings),
    sherpa: buildSherpaStatus(settings),
    sherpaOnline: buildSherpaOnlineStatus(settings),
    embedding,
    tts,
    activeDownloads: [...resourceProgress.values()].map((progress) => ({ ...progress })),
    resumableDownloads: resumableResourceDownloads(embedding, tts),
  }
}

export const getModelResourceProgress = (): ResourceProgressSnapshot => ({
  activeDownloads: [...resourceProgress.values()].map((progress) => ({ ...progress })),
})

export const pickLocalModelPath = async (modelType: PetImportableModelType): Promise<string | null> => {
  const result = await dialog.showOpenDialog({
    title: modelType === 'live2d' ? 'Select a Live2D model' : 'Select a VRM model',
    properties: modelType === 'live2d' ? ['openFile', 'openDirectory'] : ['openFile'],
    filters: modelType === 'live2d'
      ? [
          { name: 'Live2D model', extensions: ['model3.json'] },
          { name: 'All files', extensions: ['*'] },
        ]
      : [
          { name: 'VRM model', extensions: ['vrm'] },
          { name: 'All files', extensions: ['*'] },
        ],
  })

  return result.canceled ? null : (result.filePaths[0] ?? null)
}

export const prepareSoulxModels = async (petModelCatalog: PetModelCatalog): Promise<ResourceCommandResult> => {
  const install = await ensurePythonModule('huggingface_hub')
  if (install && !install.success) {
    return buildResult(install, getModelResourceStatus(petModelCatalog), 'huggingface_hub installed')
  }

  const singerSource = lockedSource('soulx', 0)
  const preprocessSource = lockedSource('soulx', 1)
  const execution = await runCommand(PYTHON_EXE, [
    SOULX_DOWNLOAD_SCRIPT,
    '--singer-revision',
    singerSource.revision ?? '',
    '--preprocess-revision',
    preprocessSource.revision ?? '',
  ], {
    cwd: SOULX_SERVICE_DIR,
    resourceId: 'soulx',
    env: {
      PYTHONIOENCODING: 'utf-8',
    },
  })
  return buildResult(execution, getModelResourceStatus(petModelCatalog), 'SoulX model assets are ready')
}

export const prepareSherpaSenseVoice = async (petModelCatalog: PetModelCatalog): Promise<ResourceCommandResult> => {
  const install = await ensurePythonModule('sherpa_onnx', 'sherpa-onnx>=1.13.6,<2')
  if (install && !install.success) {
    return buildResult(install, getModelResourceStatus(petModelCatalog), 'sherpa-onnx installed')
  }
  const scriptPath = path.join(PYTHON_DIR, 'scripts', 'download_sherpa_sensevoice.py')
  const execution = await runCommand(PYTHON_EXE, [scriptPath, '--asset-url', DEFAULT_SHERPA_ASSET_URL, '--sha256', DEFAULT_SHERPA_SHA256], {
    cwd: PYTHON_DIR,
    resourceId: 'sherpa',
    env: {
      PYTHONIOENCODING: 'utf-8',
    },
  })
  return buildResult(execution, getModelResourceStatus(petModelCatalog), 'Sherpa SenseVoice assets are ready')
}

export const prepareSherpaStreamingZipformer = async (petModelCatalog: PetModelCatalog): Promise<ResourceCommandResult> => {
  const install = await ensurePythonModule('sherpa_onnx', 'sherpa-onnx>=1.13.6,<2')
  if (install && !install.success) {
    return buildResult(install, getModelResourceStatus(petModelCatalog), 'sherpa-onnx installed')
  }
  const scriptPath = path.join(PYTHON_DIR, 'scripts', 'download_sherpa_streaming_zipformer.py')
  const execution = await runCommand(PYTHON_EXE, [scriptPath, '--asset-url', DEFAULT_SHERPA_ONLINE_ASSET_URL, '--sha256', DEFAULT_SHERPA_ONLINE_SHA256], {
    cwd: PYTHON_DIR,
    resourceId: 'sherpa_online',
    env: {
      PYTHONIOENCODING: 'utf-8',
    },
  })
  return buildResult(execution, getModelResourceStatus(petModelCatalog), 'Sherpa streaming Zipformer2 CTC assets are validated and ready')
}

export const prepareEmbeddingModel = async (petModelCatalog: PetModelCatalog): Promise<ResourceCommandResult> => {
  const settings = readStoredSettings()
  const modelName = settings.memory?.embedding_model?.trim() || DEFAULT_EMBEDDING_MODEL
  const scriptPath = path.join(PYTHON_DIR, 'scripts', 'prefetch_embedding_model.py')
  const args = [scriptPath, '--model', modelName]
  if (modelName === DEFAULT_EMBEDDING_MODEL) {
    args.push('--revision', lockedSource('embedding').revision ?? '')
  }
  const execution = await runCommand(PYTHON_EXE, args, {
    cwd: PYTHON_DIR,
    resourceId: 'embedding',
    env: {
      PYTHONIOENCODING: 'utf-8',
      HF_HOME: HF_CACHE_ROOT,
      SENTENCE_TRANSFORMERS_HOME: HF_CACHE_ROOT,
    },
  })
  return buildResult(execution, getModelResourceStatus(petModelCatalog), 'Embedding model is ready')
}

export const prepareGenieTts = async (petModelCatalog: PetModelCatalog): Promise<ResourceCommandResult> => {
  const settings = readStoredSettings()
  const character = normalizeGenieCharacter(settings.tts?.genie_character)
  const language = settings.tts?.lang?.trim() || 'ja'
  const configuredModelDir = settings.tts?.genie_model_dir?.trim() || ''
  const scriptPath = path.join(PYTHON_DIR, 'scripts', 'prefetch_genie_tts.py')
  const args = [
    scriptPath,
    '--character', character,
    '--language', language,
    '--revision', lockedSource('tts').revision ?? '',
  ]
  if (configuredModelDir) {
    args.push('--model-dir', configuredModelDir)
  }
  const execution = await runCommand(PYTHON_EXE, args, {
    cwd: PYTHON_DIR,
    resourceId: 'tts',
    env: {
      PYTHONIOENCODING: 'utf-8',
      GENIE_DATA_DIR: DEFAULT_GENIE_DATA_DIR,
      HF_HOME: HF_CACHE_ROOT,
      HF_HUB_CACHE: path.join(HF_CACHE_ROOT, 'hub'),
    },
  })
  return buildResult(execution, getModelResourceStatus(petModelCatalog), 'Genie TTS assets are ready')
}

export const missingModelResources = (
  status: ModelResourceStatusPayload,
  requested: readonly ManagedModelResourceId[],
): ManagedModelResourceId[] => {
  const ready: Record<ManagedModelResourceId, boolean> = {
    soulx: status.soulx.ready,
    sherpa: status.sherpa.ready,
    sherpa_online: status.sherpaOnline.ready,
    embedding: status.embedding.ready,
    tts: status.tts.ready,
  }
  return [...new Set(requested)].filter((resourceId) => RESOURCE_IDS.has(resourceId) && !ready[resourceId])
}

const prepareModelResource = (
  resourceId: ManagedModelResourceId,
  petModelCatalog: PetModelCatalog,
): Promise<ResourceCommandResult> => {
  const current = resourcePreparation.get(resourceId)
  if (current) return current

  beginResourceProgress(resourceId)
  const task = (() => {
    if (resourceId === 'soulx') return prepareSoulxModels(petModelCatalog)
    if (resourceId === 'sherpa') return prepareSherpaSenseVoice(petModelCatalog)
    if (resourceId === 'sherpa_online') return prepareSherpaStreamingZipformer(petModelCatalog)
    if (resourceId === 'embedding') return prepareEmbeddingModel(petModelCatalog)
    return prepareGenieTts(petModelCatalog)
  })().finally(() => {
    resourcePreparation.delete(resourceId)
    resourceProgress.delete(resourceId)
    resourceCancellationRequests.delete(resourceId)
  })
  resourcePreparation.set(resourceId, task)
  return task
}

export const prepareModelResources = async (
  requested: readonly ManagedModelResourceId[],
  petModelCatalog: PetModelCatalog,
): Promise<ResourceCommandResult> => {
  const status = getModelResourceStatus(petModelCatalog)
  const missing = missingModelResources(status, requested)
  if (missing.length === 0) {
    return {
      success: true,
      message: 'Selected model resources are ready',
      errorCode: null,
      retryable: false,
      stdout: [],
      stderr: [],
      status,
    }
  }

  const stdout: string[] = []
  const stderr: string[] = []
  for (const resourceId of missing) {
    const result = await prepareModelResource(resourceId, petModelCatalog)
    stdout.push(...result.stdout)
    stderr.push(...result.stderr)
    if (!result.success) {
      return { ...result, stdout, stderr }
    }
  }
  return {
    success: true,
    message: `Prepared ${missing.length} model resource${missing.length === 1 ? '' : 's'}`,
    errorCode: null,
    retryable: false,
    stdout,
    stderr,
    status: getModelResourceStatus(petModelCatalog),
  }
}

const normalizeResourceIds = (requested: readonly ManagedModelResourceId[]): ManagedModelResourceId[] => (
  [...new Set(requested)].filter((resourceId) => RESOURCE_IDS.has(resourceId))
)

export const cancelModelResources = (
  requested: readonly ManagedModelResourceId[],
  petModelCatalog: PetModelCatalog,
): ResourceCancelResult => {
  const cancelled: ManagedModelResourceId[] = []
  for (const resourceId of normalizeResourceIds(requested)) {
    if (!resourcePreparation.has(resourceId) && !resourceProcesses.has(resourceId)) continue
    resourceCancellationRequests.add(resourceId)
    const progress = resourceProgress.get(resourceId)
    if (progress) {
      resourceProgress.set(resourceId, {
        ...progress,
        phase: 'cancelling',
        message: 'Cancelling resource download',
        updatedAt: new Date().toISOString(),
      })
    }
    const child = resourceProcesses.get(resourceId)
    if (child) terminateProcessTree(child)
    cancelled.push(resourceId)
  }
  return {
    success: true,
    cancelled,
    status: getModelResourceStatus(petModelCatalog),
  }
}

export const cancelAllModelResourceTasks = (): ManagedModelResourceId[] => {
  const active = normalizeResourceIds([
    ...resourcePreparation.keys(),
    ...resourceProcesses.keys(),
  ])
  for (const resourceId of active) {
    resourceCancellationRequests.add(resourceId)
    const child = resourceProcesses.get(resourceId)
    if (child) terminateProcessTree(child)
  }
  return active
}

export const isManagedResourceRemovalTarget = (targetPath: string, managedRoot: string): boolean => {
  const target = path.resolve(targetPath)
  const root = path.resolve(managedRoot)
  const relative = path.relative(root, target)
  return relative !== '' && relative !== '..' && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative)
}

const directorySize = (targetPath: string): number => {
  return pathUsage(targetPath).bytes
}

export const removeManagedResourceDirectory = (targetPath: string, managedRoot: string): number => {
  if (!isManagedResourceRemovalTarget(targetPath, managedRoot)) {
    throw new Error('unsafe_path')
  }
  if (!fs.existsSync(targetPath)) return 0
  if (fs.lstatSync(targetPath).isSymbolicLink()) {
    throw new Error('unsafe_path')
  }
  const reclaimedBytes = directorySize(targetPath)
  fs.rmSync(targetPath, { recursive: true, force: true, maxRetries: 3, retryDelay: 100 })
  return reclaimedBytes
}

const validateManagedRemovalTarget = ({ targetPath, managedRoot }: ManagedRemovalTarget): string | null => {
  if (!isManagedResourceRemovalTarget(targetPath, managedRoot)) return 'unsafe_path'
  try {
    if (fs.existsSync(targetPath) && fs.lstatSync(targetPath).isSymbolicLink()) return 'unsafe_path'
  } catch (error) {
    return error instanceof Error ? error.message : 'path_unreadable'
  }
  return null
}

type ManagedRemovalTarget = {
  targetPath: string
  managedRoot: string
}

const embeddingRemovalTargets = (modelName: string): ManagedRemovalTarget[] => {
  return [...huggingFaceRepoCachePaths(modelName), ...huggingFaceRepoLockPaths(modelName)].map((targetPath) => ({
    managedRoot: path.dirname(targetPath),
    targetPath,
  }))
}

const genieRemovalTargets = (character: string): ManagedRemovalTarget[] => {
  const targets: ManagedRemovalTarget[] = [
    { targetPath: DEFAULT_GENIE_ROOT, managedRoot: path.join(PYTHON_DIR, '.cache') },
    { targetPath: genieCharacterDir(character), managedRoot: GENIE_CHARACTER_ROOT },
    { targetPath: genieCharacterMetadataDir(character), managedRoot: GENIE_CHARACTER_METADATA_ROOT },
  ]
  targets.push(...huggingFaceRepoCachePaths('High-Logic/Genie').map((targetPath) => ({
    managedRoot: path.dirname(targetPath),
    targetPath,
  })))
  targets.push(...huggingFaceRepoLockPaths('High-Logic/Genie').map((targetPath) => ({
    managedRoot: path.dirname(targetPath),
    targetPath,
  })))
  return targets
}

const managedRemovalTargets = (resourceId: ManagedModelResourceId, settings: StoredSettings): ManagedRemovalTarget[] => {
  const pythonCacheRoot = path.join(PYTHON_DIR, '.cache')
  if (resourceId === 'sherpa') return [{ targetPath: SHERPA_DIR, managedRoot: pythonCacheRoot }]
  if (resourceId === 'sherpa_online') return [{ targetPath: SHERPA_ONLINE_DIR, managedRoot: pythonCacheRoot }]
  if (resourceId === 'embedding') {
    return embeddingRemovalTargets(settings.memory?.embedding_model?.trim() || DEFAULT_EMBEDDING_MODEL)
  }
  if (resourceId === 'tts') return genieRemovalTargets(normalizeGenieCharacter(settings.tts?.genie_character))
  const soulxModelsRoot = path.join(SOULX_SERVICE_DIR, 'models')
  return [
    { targetPath: SOULX_MODEL_DIR, managedRoot: soulxModelsRoot },
    { targetPath: SOULX_PREPROCESS_DIR, managedRoot: soulxModelsRoot },
  ]
}

export const removeModelResources = (
  requested: readonly ManagedModelResourceId[],
  petModelCatalog: PetModelCatalog,
): ResourceRemovalResult => {
  const resourceIds = normalizeResourceIds(requested)
  const activeResources = resourceIds.filter((resourceId) => resourcePreparation.has(resourceId) || resourceProcesses.has(resourceId))
  if (activeResources.length > 0) {
    return {
      success: false,
      message: 'Cancel active downloads before permanent removal',
      removed: [],
      failed: activeResources.map((resourceId) => ({ resourceId, reason: 'download_active' })),
      reclaimedBytes: 0,
      status: getModelResourceStatus(petModelCatalog),
    }
  }

  const settings = readStoredSettings()
  const targets = new Map(resourceIds.map((resourceId) => [resourceId, managedRemovalTargets(resourceId, settings)]))
  const invalidResources = resourceIds.flatMap((resourceId) => {
    const reason = (targets.get(resourceId) ?? [])
      .map(validateManagedRemovalTarget)
      .find((value): value is string => Boolean(value))
    return reason ? [{ resourceId, reason }] : []
  })
  if (invalidResources.length > 0) {
    return {
      success: false,
      message: 'Resource removal path validation failed',
      removed: [],
      failed: invalidResources,
      reclaimedBytes: 0,
      status: getModelResourceStatus(petModelCatalog),
    }
  }

  const removed: ManagedModelResourceId[] = []
  const failed: ResourceRemovalResult['failed'] = []
  let reclaimedBytes = 0
  for (const resourceId of resourceIds) {
    try {
      for (const { targetPath, managedRoot } of targets.get(resourceId) ?? []) {
        reclaimedBytes += removeManagedResourceDirectory(targetPath, managedRoot)
      }
      removed.push(resourceId)
    } catch (error) {
      failed.push({
        resourceId,
        reason: error instanceof Error ? error.message : String(error),
      })
    }
  }

  return {
    success: failed.length === 0,
    message: failed.length === 0 ? `Permanently removed ${removed.length} model resources` : 'Some model resources could not be removed',
    removed,
    failed,
    reclaimedBytes,
    status: getModelResourceStatus(petModelCatalog),
  }
}

export const importSoulxReferenceAudio = async (
  petModelCatalog: PetModelCatalog,
  speakerId = '0',
): Promise<ResourceCommandResult> => {
  const result = await dialog.showOpenDialog({
    title: 'Select SoulX reference audio',
    filters: [
      { name: 'Audio files', extensions: ['wav', 'mp3', 'flac', 'm4a'] },
      { name: 'All files', extensions: ['*'] },
    ],
    properties: ['openFile'],
  })

  if (result.canceled || result.filePaths.length === 0) {
    const status = getModelResourceStatus(petModelCatalog)
    return {
      success: false,
      message: 'Reference audio selection was canceled',
      errorCode: 'cancelled',
      retryable: false,
      stdout: [],
      stderr: [],
      status,
    }
  }

  const copiedPath = copySoulxReferenceAudio(result.filePaths[0] ?? '', speakerId)
  return {
    success: true,
    message: `Reference audio imported: ${copiedPath}`,
    errorCode: null,
    retryable: false,
    stdout: [copiedPath],
    stderr: [],
    status: getModelResourceStatus(petModelCatalog),
  }
}

export const resourceManagerPaths = {
  projectRoot: PROJECT_ROOT,
  pythonDir: PYTHON_DIR,
  pythonExe: PYTHON_EXE,
  sherpaAssetUrl: DEFAULT_SHERPA_ASSET_URL,
  sherpaOnlineAssetUrl: DEFAULT_SHERPA_ONLINE_ASSET_URL,
  soulxReferenceDir: SOULX_REFERENCE_DIR,
  resourceLockPath: RESOURCE_LOCK_PATH,
}
