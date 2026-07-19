import { spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { dialog } from 'electron'
import type { PetModelCatalog } from './pet-model-catalog'
import type {
  EmbeddingResourceStatus,
  ModelResourceStatusPayload,
  ManagedModelResourceId,
  ResourceCommandResult,
  PetImportableModelType,
  SherpaResourceStatus,
  SoulxResourceStatus,
  TtsResourceStatus,
} from '../shared/resource-manager'

const DEFAULT_SHERPA_ASSET_URL = 'https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2025-01-06.tar.bz2'
const DEFAULT_SHERPA_ONLINE_ASSET_URL = 'https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-zipformer-small-ctc-zh-int8-2025-04-01.tar.bz2'

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
    genie_character?: string
    genie_model_dir?: string
    lang?: string
  }
}

type CommandExecution = {
  success: boolean
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
const PYTHON_DIR = path.join(PROJECT_ROOT, 'python')
const PYTHON_EXE = fs.existsSync(path.join(PYTHON_DIR, '.venv', 'Scripts', 'python.exe'))
  ? path.join(PYTHON_DIR, '.venv', 'Scripts', 'python.exe')
  : 'python'
const SETTINGS_PATH = path.join(PYTHON_DIR, 'config', 'settings.json')
const SHERPA_DIR = path.join(PYTHON_DIR, '.cache', 'sherpa-onnx', 'sensevoice')
const DEFAULT_SHERPA_MODEL_PATH = path.join(SHERPA_DIR, 'model.int8.onnx')
const DEFAULT_SHERPA_TOKENS_PATH = path.join(SHERPA_DIR, 'tokens.txt')
const SHERPA_ONLINE_DIR = path.join(PYTHON_DIR, '.cache', 'sherpa-onnx', 'streaming-zipformer-small-ctc-zh')
const DEFAULT_SHERPA_ONLINE_MODEL_PATH = path.join(SHERPA_ONLINE_DIR, 'model.int8.onnx')
const DEFAULT_SHERPA_ONLINE_TOKENS_PATH = path.join(SHERPA_ONLINE_DIR, 'tokens.txt')
const HF_CACHE_ROOT = path.join(PYTHON_DIR, '.cache', 'huggingface')
const DEFAULT_EMBEDDING_MODEL = 'Qwen/Qwen3-Embedding-0.6B'
const DEFAULT_GENIE_DATA_DIR = path.join(PYTHON_DIR, '.cache', 'GenieData', 'GenieData')
const SOULX_SERVICE_DIR = path.join(PROJECT_ROOT, 'services', 'soulx-svc')
const SOULX_DOWNLOAD_SCRIPT = path.join(SOULX_SERVICE_DIR, 'download_models.py')
const SOULX_LAUNCHER = path.join(PROJECT_ROOT, 'start_soulx_svc.bat')
const SOULX_MODEL_DIR = path.join(SOULX_SERVICE_DIR, 'models', 'SoulX-Singer')
const SOULX_PREPROCESS_DIR = path.join(SOULX_SERVICE_DIR, 'models', 'SoulX-Singer-Preprocess')
const SOULX_REFERENCE_DIR = path.join(SOULX_SERVICE_DIR, 'references')
const SOULX_CHECKPOINT_CANDIDATES = [
  path.join(SOULX_MODEL_DIR, 'model-svc.pt'),
  path.join(SOULX_MODEL_DIR, 'model.pt'),
]

const RESOURCE_IDS = new Set<ManagedModelResourceId>(['soulx', 'sherpa', 'sherpa_online', 'embedding', 'tts'])
const resourcePreparation = new Map<ManagedModelResourceId, Promise<ResourceCommandResult>>()

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
    const snapshotNames = fs.readdirSync(snapshotsDir).filter((item) => fs.statSync(path.join(snapshotsDir, item)).isDirectory())
    if (snapshotNames.length > 0) {
      const sorted = snapshotNames.sort((left, right) => (
        fs.statSync(path.join(snapshotsDir, right)).mtimeMs - fs.statSync(path.join(snapshotsDir, left)).mtimeMs
      ))
      return path.join(snapshotsDir, sorted[0] ?? '')
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

const buildSoulxStatus = (): SoulxResourceStatus => {
  const checkpointPath = findSoulxCheckpoint()
  const summary = buildSummary([
    [fs.existsSync(SOULX_SERVICE_DIR), 'SoulX service directory is missing'],
    [Boolean(checkpointPath), 'SoulX checkpoint is missing'],
    [fs.existsSync(SOULX_PREPROCESS_DIR), 'SoulX preprocess assets are missing'],
    [hasSoulxReferenceAudio(), 'SoulX reference audio is missing'],
  ])

  return {
    ...summary,
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
  const useConfiguredPaths = settings.asr?.provider === 'sherpa-onnx'
  const modelPath = resolveBackendRelativePath(useConfiguredPaths ? settings.asr?.sherpa_model_path : '', DEFAULT_SHERPA_MODEL_PATH)
  const tokensPath = resolveBackendRelativePath(useConfiguredPaths ? settings.asr?.sherpa_tokens_path : '', DEFAULT_SHERPA_TOKENS_PATH)
  const summary = buildSummary([
    [fs.existsSync(modelPath), 'Sherpa SenseVoice model file is missing'],
    [fs.existsSync(tokensPath), 'Sherpa SenseVoice tokens file is missing'],
  ])

  return {
    ...summary,
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
  const filesExist = fs.existsSync(modelPath) && fs.existsSync(tokensPath)
  const validated = filesExist && hasCurrentSherpaOnlineValidation(modelPath, tokensPath, validationPath)
  const summary = buildSummary([
    [fs.existsSync(modelPath), 'Sherpa streaming Zipformer2 CTC model file is missing'],
    [fs.existsSync(tokensPath), 'Sherpa streaming tokens file is missing'],
    [validated, 'Sherpa streaming model has not passed the Yuizaki load validation'],
  ])

  return {
    ...summary,
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
  const summary = buildSummary([
    [Boolean(cachePath), 'Embedding model snapshot is missing'],
  ])

  return {
    ...summary,
    modelName,
    cachePath,
    cacheRoot: HF_CACHE_ROOT,
  }
}

const buildTtsStatus = (settings: StoredSettings): TtsResourceStatus => {
  const configuredModelDir = settings.tts?.genie_model_dir?.trim() || null
  const character = settings.tts?.genie_character?.trim() || 'feibi'
  const ready = configuredModelDir ? fs.existsSync(configuredModelDir) : fs.existsSync(DEFAULT_GENIE_DATA_DIR)
  const summary = buildSummary([
    [ready, configuredModelDir ? 'Configured Genie model directory is missing' : 'Genie cache is missing'],
  ])

  return {
    ...summary,
    character,
    cacheDir: DEFAULT_GENIE_DATA_DIR,
    configuredModelDir,
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
  options: { cwd?: string; env?: NodeJS.ProcessEnv } = {},
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
    })

    child.stdout.on('data', (chunk) => {
      const text = String(chunk).trim()
      if (text) {
        stdout.push(...text.split(/\r?\n/).filter(Boolean))
      }
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
      const exitCode = code ?? 1
      resolve({
        success: exitCode === 0,
        code: exitCode,
        stdout,
        stderr,
        message: exitCode === 0 ? 'Command completed' : `Command failed with exit code ${exitCode}`,
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

const buildResult = (execution: CommandExecution, status: ModelResourceStatusPayload, successMessage: string): ResourceCommandResult => ({
  success: execution.success,
  message: execution.success ? successMessage : (execution.stderr[execution.stderr.length - 1] || execution.message),
  stdout: execution.stdout,
  stderr: execution.stderr,
  status,
})

export const getModelResourceStatus = (petModelCatalog: PetModelCatalog): ModelResourceStatusPayload => {
  const settings = readStoredSettings()
  return {
    modelRoots: petModelCatalog.getLocalModelRoots(),
    localCounts: petModelCatalog.getLocalModelCounts(),
    soulx: buildSoulxStatus(),
    sherpa: buildSherpaStatus(settings),
    sherpaOnline: buildSherpaOnlineStatus(settings),
    embedding: buildEmbeddingStatus(settings),
    tts: buildTtsStatus(settings),
  }
}

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

  const execution = await runCommand(PYTHON_EXE, [SOULX_DOWNLOAD_SCRIPT], {
    cwd: SOULX_SERVICE_DIR,
    env: {
      PYTHONIOENCODING: 'utf-8',
    },
  })
  return buildResult(execution, getModelResourceStatus(petModelCatalog), 'SoulX model assets are ready')
}

export const prepareSherpaSenseVoice = async (petModelCatalog: PetModelCatalog): Promise<ResourceCommandResult> => {
  const scriptPath = path.join(PYTHON_DIR, 'scripts', 'download_sherpa_sensevoice.py')
  const execution = await runCommand(PYTHON_EXE, [scriptPath], {
    cwd: PYTHON_DIR,
    env: {
      PYTHONIOENCODING: 'utf-8',
    },
  })
  return buildResult(execution, getModelResourceStatus(petModelCatalog), 'Sherpa SenseVoice assets are ready')
}

export const prepareSherpaStreamingZipformer = async (petModelCatalog: PetModelCatalog): Promise<ResourceCommandResult> => {
  const install = await ensurePythonModule('sherpa_onnx', 'sherpa-onnx>=1.13.2,<2')
  if (install && !install.success) {
    return buildResult(install, getModelResourceStatus(petModelCatalog), 'sherpa-onnx installed')
  }
  const scriptPath = path.join(PYTHON_DIR, 'scripts', 'download_sherpa_streaming_zipformer.py')
  const execution = await runCommand(PYTHON_EXE, [scriptPath], {
    cwd: PYTHON_DIR,
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
  const execution = await runCommand(PYTHON_EXE, [scriptPath, '--model', modelName], {
    cwd: PYTHON_DIR,
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
  const character = settings.tts?.genie_character?.trim() || 'feibi'
  const language = settings.tts?.lang?.trim() || 'ja'
  const configuredModelDir = settings.tts?.genie_model_dir?.trim() || ''
  const scriptPath = path.join(PYTHON_DIR, 'scripts', 'prefetch_genie_tts.py')
  const args = [scriptPath, '--character', character, '--language', language]
  if (configuredModelDir) {
    args.push('--model-dir', configuredModelDir)
  }
  const execution = await runCommand(PYTHON_EXE, args, {
    cwd: PYTHON_DIR,
    env: {
      PYTHONIOENCODING: 'utf-8',
      GENIE_DATA_DIR: DEFAULT_GENIE_DATA_DIR,
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

  const task = (() => {
    if (resourceId === 'soulx') return prepareSoulxModels(petModelCatalog)
    if (resourceId === 'sherpa') return prepareSherpaSenseVoice(petModelCatalog)
    if (resourceId === 'sherpa_online') return prepareSherpaStreamingZipformer(petModelCatalog)
    if (resourceId === 'embedding') return prepareEmbeddingModel(petModelCatalog)
    return prepareGenieTts(petModelCatalog)
  })().finally(() => resourcePreparation.delete(resourceId))
  resourcePreparation.set(resourceId, task)
  return task
}

export const prepareModelResources = async (
  requested: readonly ManagedModelResourceId[],
  petModelCatalog: PetModelCatalog,
): Promise<ResourceCommandResult> => {
  const missing = missingModelResources(getModelResourceStatus(petModelCatalog), requested)
  if (missing.length === 0) {
    return {
      success: true,
      message: 'Selected model resources are ready',
      stdout: [],
      stderr: [],
      status: getModelResourceStatus(petModelCatalog),
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
    stdout,
    stderr,
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
      stdout: [],
      stderr: [],
      status,
    }
  }

  const copiedPath = copySoulxReferenceAudio(result.filePaths[0] ?? '', speakerId)
  return {
    success: true,
    message: `Reference audio imported: ${copiedPath}`,
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
}
