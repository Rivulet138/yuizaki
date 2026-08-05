import { app } from 'electron'
import fs from 'node:fs'
import path from 'node:path'
import extractZip from 'extract-zip'
import type {
  PetControlConfigPatch,
  PetControlState,
  AvatarManifest,
  PetEmotionMotionTarget,
  PetEmotionPreset,
  PetModelCatalogPayload,
  PetModelDefinition,
  PetModelExpressionOption,
  PetModelMotionOption,
  PetResolvedEmotionTrigger,
} from '../shared/pet-control'
import type { LocalModelCounts, LocalModelRoots } from '../shared/resource-manager'
import type { PluginRegistry } from './plugin-registry'
import { logger } from './logger'
import { AvatarManifestService } from './avatar-manifest-service'

interface CubismModelReference {
  File?: string
  Name?: string
  Sound?: string
}

interface CubismModelJson {
  FileReferences?: {
    Moc?: string
    Textures?: string[]
    Physics?: string
    Pose?: string
    DisplayInfo?: string
    UserData?: string
    Expressions?: CubismModelReference[]
    Motions?: Record<string, CubismModelReference[]>
  }
}

interface RawEmotionMotionTarget {
  group?: string
  index?: number
}

interface RawEmotionPreset {
  label?: string
  motions?: RawEmotionMotionTarget[]
  expressions?: string[]
}

interface RawEmotionMapEntry {
  emotions?: Record<string, RawEmotionPreset>
}

type RawEmotionMapFile = Record<string, RawEmotionMapEntry>
type CubismAssetReference = { label: string; file: string }

const LIVE2D_ROOT_CANDIDATES = [
  path.resolve(__dirname, '../../src/renderer/public/live2d'),
  path.resolve(__dirname, '../../dist/renderer/live2d'),
]
const VRM_ROOT_CANDIDATES = [
  path.resolve(__dirname, '../../src/renderer/public/vrm'),
  path.resolve(__dirname, '../../dist/renderer/vrm'),
]
const EMOTION_MAP_FILE_NAME = 'emotion-map.json'
const USER_LIVE2D_ASSET_PREFIX = '/api/pet/assets/live2d/'
const USER_VRM_ASSET_PREFIX = '/api/pet/assets/vrm/'

const toPosixPath = (inputPath: string): string => inputPath.replace(/\\/g, '/')
const encodeAssetPath = (inputPath: string): string =>
  toPosixPath(inputPath).split('/').map((part) => encodeURIComponent(part)).join('/')

const titleCase = (value: string): string =>
  value
    .replace(/[-_]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase())

const basenameWithoutExt = (filePath: string): string =>
  path.basename(filePath, path.extname(filePath))

const isZipArchivePath = (filePath: string): boolean =>
  path.extname(filePath).toLowerCase() === '.zip'

const sanitizeImportFolderName = (value: string): string =>
  value
    .replace(/[<>:"/\\|?*\x00-\x1F]+/g, '-')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 80) || 'model'

const buildMotionLabel = (group: string, motionsInGroup: number, index: number): string =>
  motionsInGroup > 1 ? `${group} ${index + 1}` : group

interface DerivedEmotionRule {
  id: string
  label: string
  keywords: string[]
}

const DERIVED_EMOTION_RULES: DerivedEmotionRule[] = [
  { id: 'neutral', label: '平静', keywords: ['neutral', 'normal', 'default', 'idle', '平静', '普通', '默认'] },
  { id: 'happy', label: '开心', keywords: ['happy', 'smile', 'laugh', 'joy', '开心', '高兴', '笑'] },
  { id: 'sad', label: '难过', keywords: ['sad', 'cry', 'tear', 'down', '难过', '伤心', '哭', '泪'] },
  { id: 'angry', label: '生气', keywords: ['angry', 'mad', 'rage', '生气', '愤怒', '怒'] },
  { id: 'surprised', label: '惊讶', keywords: ['surprise', 'surprised', 'shock', '惊讶', '震惊', '惊', '呆'] },
  { id: 'shy', label: '害羞', keywords: ['shy', 'blush', 'red', '害羞', '脸红', '羞'] },
  { id: 'love', label: '喜欢', keywords: ['love', 'heart', 'like', '喜欢', '爱心', '心'] },
  { id: 'sleepy', label: '困倦', keywords: ['sleep', 'sleepy', 'asleep', '困', '睡', '眠'] },
  { id: 'thinking', label: '思考', keywords: ['think', 'thinking', 'question', '疑问', '思考', '问号'] },
]

const normalizeEmotionText = (value: string): string => value.toLowerCase().replace(/[\s_-]+/g, '')

const isPathInsideRealBase = (baseDir: string, targetPath: string): boolean => {
  const relative = path.relative(baseDir, targetPath)
  return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative))
}

const hasText = (value: unknown): value is string =>
  typeof value === 'string' && value.trim().length > 0

const realpathOrNull = (inputPath: string): string | null => {
  try {
    return fs.realpathSync.native(inputPath)
  } catch {
    return null
  }
}

const inferDerivedEmotion = (expression: { id: string; label: string; prompt: string }): DerivedEmotionRule | null => {
  const candidates = [expression.id, expression.label, expression.prompt].map(normalizeEmotionText)
  return DERIVED_EMOTION_RULES.find((rule) =>
    rule.keywords.some((keyword) => candidates.some((candidate) => candidate.includes(normalizeEmotionText(keyword)))),
  ) ?? null
}

export class PetModelCatalog {
  private readonly live2dRootDir: string
  private readonly vrmRootDir: string | null
  private readonly userLive2dRootDir: string
  private readonly userVrmRootDir: string
  private readonly avatarManifestService: AvatarManifestService
  private models: PetModelDefinition[] = []
  private emotionMap: RawEmotionMapFile = {}
  private localModelDirs = new Map<string, { rootDir: string; removePath: string }>()

  constructor(private readonly pluginRegistry?: PluginRegistry) {
    this.live2dRootDir = this.resolveLive2dRootDir()
    this.vrmRootDir = this.resolveVrmRootDir()
    this.userLive2dRootDir = this.resolveUserLive2dRootDir()
    this.userVrmRootDir = this.resolveUserVrmRootDir()
    fs.mkdirSync(this.userLive2dRootDir, { recursive: true })
    fs.mkdirSync(this.userVrmRootDir, { recursive: true })
    this.avatarManifestService = new AvatarManifestService(this.live2dRootDir)
    this.refresh()
  }

  refresh(): void {
    this.emotionMap = this.loadEmotionMap()
    this.localModelDirs.clear()
    this.models = this.scanModels()
  }

  getModels(): PetModelDefinition[] {
    return this.models.map((model) => ({
      ...model,
      motions: [...model.motions],
      expressions: [...model.expressions],
      emotions: model.emotions.map((emotion) => ({
        ...emotion,
        motions: [...emotion.motions],
        expressions: [...emotion.expressions],
      })),
    }))
  }

  getCatalog(activeModelId: string | null): PetModelCatalogPayload {
    return {
      activeModelId: this.normalizeModelId(activeModelId),
      models: this.getModels(),
    }
  }

  getModelById(modelId: string | null | undefined): PetModelDefinition | null {
    if (!modelId) {
      return null
    }

    return this.models.find((model) => model.id === modelId) ?? null
  }

  getEmotionPresets(modelId: string | null | undefined): PetEmotionPreset[] {
    return this.getModelById(modelId)?.emotions.map((emotion) => ({
      ...emotion,
      motions: [...emotion.motions],
      expressions: [...emotion.expressions],
    })) ?? []
  }

  getAvatarManifest(modelId: string | null | undefined): AvatarManifest | null {
    return this.getModelById(modelId)?.manifest ?? null
  }

  buildPromptContext(modelId: string | null | undefined): string {
    const manifest = this.getAvatarManifest(modelId)
    return manifest ? this.avatarManifestService.buildPromptContext(manifest).prompt : ''
  }

  resolveEmotionTrigger(
    modelId: string | null | undefined,
    emotionId: string,
  ): PetResolvedEmotionTrigger | null {
    const emotion = this.getEmotionPresets(modelId).find((item) => item.id === emotionId)
    if (!emotion) {
      return null
    }

    const motion =
      emotion.motions.length > 0
        ? emotion.motions[Math.floor(Math.random() * emotion.motions.length)]
        : undefined

    const expressionName =
      emotion.expressions.length > 0
        ? emotion.expressions[Math.floor(Math.random() * emotion.expressions.length)]
        : undefined

    const trigger: PetResolvedEmotionTrigger = {
      id: emotion.id,
      label: emotion.label,
    }

    if (motion) {
      trigger.motion = motion
    }

    if (expressionName) {
      trigger.expressionName = expressionName
    }

    return trigger
  }

  getDefaultModelId(): string | null {
    return this.models.find((model) => model.source === 'bundled')?.id
      ?? this.models.find((model) => model.source === 'local')?.id
      ?? null
  }

  getUserLive2dRootDir(): string {
    return this.userLive2dRootDir
  }

  getUserVrmRootDir(): string {
    return this.userVrmRootDir
  }

  getLocalModelRoots(): LocalModelRoots {
    return {
      live2d: this.userLive2dRootDir,
      vrm: this.userVrmRootDir,
    }
  }

  getLocalModelCounts(): LocalModelCounts {
    return this.models.reduce<LocalModelCounts>((counts, model) => {
      if (model.source === 'local') {
        counts[model.type] += 1
      }
      return counts
    }, { live2d: 0, vrm: 0 })
  }

  async importLocalLive2dModel(sourcePath: string): Promise<PetModelDefinition> {
    const previousLocalIds = new Set(
      this.getModels()
        .filter((model) => model.source === 'local' && model.type === 'live2d')
        .map((model) => model.id),
    )
    const source = path.resolve(String(sourcePath || '').trim())
    if (!source || !fs.existsSync(source)) {
      throw new Error('Local model path does not exist')
    }

    const stat = fs.statSync(source)
    if (!stat.isDirectory() && !stat.isFile()) {
      throw new Error('Choose a Live2D .model3.json file, model folder, or .zip archive')
    }

    let importedModelFile: string
    let createdTargetDir: string | null = null

    if (stat.isFile() && isZipArchivePath(source)) {
      const targetDir = this.resolveUniqueImportTarget(this.userLive2dRootDir, basenameWithoutExt(source))
      createdTargetDir = targetDir
      fs.mkdirSync(targetDir, { recursive: true })
      try {
        await extractZip(source, { dir: targetDir })
        importedModelFile = this.findFirstModelFile(targetDir)
      } catch (error) {
        fs.rmSync(targetDir, { recursive: true, force: true })
        const importError = new Error(
          `Failed to import Live2D archive: ${error instanceof Error ? error.message : String(error)}`,
        )
        ;(importError as Error & { cause?: unknown }).cause = error
        throw importError
      }
    } else {
      const modelFile = stat.isDirectory() ? this.findFirstModelFile(source) : source
      if (!modelFile.toLowerCase().endsWith('.model3.json')) {
        throw new Error('Choose a Live2D .model3.json file, model folder, or .zip archive')
      }

      const sourceDir = path.dirname(modelFile)
      const relativeToUserRoot = path.relative(this.userLive2dRootDir, sourceDir)
      const sourceAlreadyManaged =
        relativeToUserRoot === '' ||
        (!relativeToUserRoot.startsWith('..') && !path.isAbsolute(relativeToUserRoot))

      importedModelFile = modelFile
      if (!sourceAlreadyManaged) {
        const targetDir = this.resolveUniqueImportTarget(this.userLive2dRootDir, path.basename(sourceDir))
        createdTargetDir = targetDir
        fs.cpSync(sourceDir, targetDir, { recursive: true })
        importedModelFile = path.join(targetDir, path.basename(modelFile))
      }
    }

    try {
      const importedConfig = this.parseModelConfig(importedModelFile)
      this.validateLive2dModelFile(importedModelFile, this.userLive2dRootDir, importedConfig)
      this.refresh()
      const importedModel = this.findImportedLocalModel('live2d', previousLocalIds)
        ?? this.requireImportedLocalModel(importedModelFile, this.userLive2dRootDir, USER_LIVE2D_ASSET_PREFIX)
      return importedModel
    } catch (error) {
      if (createdTargetDir) {
        fs.rmSync(createdTargetDir, { recursive: true, force: true })
        this.refresh()
      }
      throw error
    }
  }

  importLocalVrmModel(sourcePath: string): PetModelDefinition {
    const previousLocalIds = new Set(
      this.getModels()
        .filter((model) => model.source === 'local' && model.type === 'vrm')
        .map((model) => model.id),
    )
    const source = path.resolve(String(sourcePath || '').trim())
    if (!source || !fs.existsSync(source)) {
      throw new Error('Local VRM path does not exist')
    }

    const stat = fs.statSync(source)
    const vrmFile = stat.isDirectory() ? this.findFirstVrmFile(source) : source
    if (!vrmFile.toLowerCase().endsWith('.vrm')) {
      throw new Error('Choose a .vrm file or a folder containing one')
    }

    const sourceDir = stat.isDirectory() ? source : path.dirname(source)
    const relativeToUserRoot = path.relative(this.userVrmRootDir, sourceDir)
    const sourceAlreadyManaged =
      relativeToUserRoot === '' ||
      (!relativeToUserRoot.startsWith('..') && !path.isAbsolute(relativeToUserRoot))

    let importedModelFile = vrmFile
    if (!sourceAlreadyManaged) {
      const targetDir = this.resolveUniqueImportTarget(
        this.userVrmRootDir,
        stat.isDirectory() ? path.basename(sourceDir) : basenameWithoutExt(vrmFile),
      )
      fs.mkdirSync(targetDir, { recursive: true })
      if (stat.isDirectory()) {
        fs.cpSync(sourceDir, targetDir, { recursive: true })
        importedModelFile = path.join(targetDir, path.relative(sourceDir, vrmFile))
      } else {
        importedModelFile = path.join(targetDir, path.basename(vrmFile))
        fs.copyFileSync(vrmFile, importedModelFile)
      }
    }

    this.refresh()
    return this.findImportedLocalModel('vrm', previousLocalIds)
      ?? this.requireImportedLocalModel(importedModelFile, this.userVrmRootDir, USER_VRM_ASSET_PREFIX)
  }

  removeLocalModel(modelId: string): boolean {
    const localModel = this.localModelDirs.get(modelId)
    if (!localModel) {
      return false
    }

    const linkStatus = (() => {
      try {
        return fs.lstatSync(localModel.removePath)
      } catch {
        return null
      }
    })()
    const realRoot = realpathOrNull(localModel.rootDir)
    const realLocalDir = realpathOrNull(localModel.removePath)
    if (!linkStatus || linkStatus.isSymbolicLink() || !realRoot || !realLocalDir || !isPathInsideRealBase(realRoot, realLocalDir)) {
      return false
    }

    fs.rmSync(realLocalDir, { recursive: true, force: true })
    this.refresh()
    return true
  }

  resolveLocalLive2dAsset(relativeAssetPath: string): string | null {
    return this.resolveManagedAsset(relativeAssetPath, this.userLive2dRootDir)
  }

  resolveLocalVrmAsset(relativeAssetPath: string): string | null {
    return this.resolveManagedAsset(relativeAssetPath, this.userVrmRootDir)
  }

  private resolveManagedAsset(relativeAssetPath: string, rootDir: string): string | null {
    const decodedPath = toPosixPath(relativeAssetPath).replace(/^\/+/, '')
    const absolutePath = path.resolve(rootDir, decodedPath)
    const relativeToUserRoot = path.relative(rootDir, absolutePath)
    if (relativeToUserRoot.startsWith('..') || path.isAbsolute(relativeToUserRoot)) {
      return null
    }
    if (!fs.existsSync(absolutePath)) {
      return null
    }
    const linkStatus = fs.lstatSync(absolutePath)
    if (linkStatus.isSymbolicLink() || !linkStatus.isFile()) {
      return null
    }
    const realRoot = fs.realpathSync.native(rootDir)
    const realAssetPath = fs.realpathSync.native(absolutePath)
    if (!isPathInsideRealBase(realRoot, realAssetPath)) {
      return null
    }
    return realAssetPath
  }

  normalizeModelId(modelId: string | null | undefined): string | null {
    const matched = this.getModelById(modelId)
    return matched?.id ?? this.getDefaultModelId()
  }

  resolveModelId(modelId: string | null | undefined): string | null {
    return this.getModelById(modelId)?.id ?? null
  }

  buildRendererConfig(state: PetControlState): PetControlConfigPatch {
    const modelId = this.normalizeModelId(state.modelId)
    const model = this.getModelById(modelId)

    const config: PetControlConfigPatch = {
      modelType: model?.type ?? state.modelType,
      modelId,
      scale: state.scale,
      positionX: state.positionX,
      positionY: state.positionY,
      placement: state.placement,
      interactMode: state.interactMode,
      clickThrough: state.clickThrough,
      locked: state.locked,
      opacity: state.opacity,
      lipSyncProfile: state.lipSyncProfile,
    }

    if (model) {
      config.modelPath = model.assetPath.startsWith('/')
        ? model.assetPath
        : model.type === 'vrm'
          ? `./vrm/${model.assetPath}`
          : `./live2d/${model.assetPath}`
      config.modelManifest = model.manifest ?? null
    }

    return config
  }

  private resolveLive2dRootDir(): string {
    const matchedRoot = LIVE2D_ROOT_CANDIDATES.find((candidate) => fs.existsSync(candidate))
    if (!matchedRoot) {
      throw new Error('Live2D asset directory not found')
    }

    return matchedRoot
  }

  private resolveUserLive2dRootDir(): string {
    try {
      return path.join(app.getPath('userData'), 'pet-models', 'live2d')
    } catch {
      return path.resolve(process.cwd(), '.yuizaki', 'pet-models', 'live2d')
    }
  }

  private resolveUserVrmRootDir(): string {
    try {
      return path.join(app.getPath('userData'), 'pet-models', 'vrm')
    } catch {
      return path.resolve(process.cwd(), '.yuizaki', 'pet-models', 'vrm')
    }
  }

  private loadEmotionMap(): RawEmotionMapFile {
    const emotionMapPath = path.join(this.live2dRootDir, EMOTION_MAP_FILE_NAME)
    if (!fs.existsSync(emotionMapPath)) {
      return {}
    }

    try {
      return JSON.parse(fs.readFileSync(emotionMapPath, 'utf8')) as RawEmotionMapFile
    } catch (error) {
      logger.warn('[PetModelCatalog] Failed to load emotion-map.json:', error)
      return {}
    }
  }

  private scanModels(): PetModelDefinition[] {
    const modelFiles = this.collectModelFiles(this.live2dRootDir)
    const localModelFiles = fs.existsSync(this.userLive2dRootDir)
      ? this.collectModelFiles(this.userLive2dRootDir)
      : []
    const vrmFiles = this.vrmRootDir ? this.collectVrmFiles(this.vrmRootDir) : []
    const localVrmFiles = fs.existsSync(this.userVrmRootDir)
      ? this.collectVrmFiles(this.userVrmRootDir)
      : []
    const pluginProviderModels = this.buildPluginProviderModels()

    return [
      ...this.buildModelDefinitions(modelFiles, this.live2dRootDir, 'bundled'),
      ...this.buildModelDefinitions(localModelFiles, this.userLive2dRootDir, 'local'),
      ...this.buildVrmModelDefinitions(vrmFiles, this.vrmRootDir ?? this.live2dRootDir, 'bundled'),
      ...this.buildVrmModelDefinitions(localVrmFiles, this.userVrmRootDir, 'local'),
      ...pluginProviderModels,
    ]
      .sort((a, b) => a.name.localeCompare(b.name))
  }

  private buildModelDefinitions(
    modelFiles: string[],
    rootDir: string,
    source: 'bundled' | 'local',
  ): PetModelDefinition[] {
    return modelFiles
      .map((modelFile) => {
        try {
          return this.buildModelDefinition(modelFile, rootDir, source)
        } catch (error) {
          logger.warn(`[PetModelCatalog] Skipped invalid Live2D model: ${modelFile}`, error)
          return null
        }
      })
      .filter((model): model is PetModelDefinition => model !== null)
  }

  private buildVrmModelDefinitions(
    vrmFiles: string[],
    rootDir: string,
    source: 'bundled' | 'local',
  ): PetModelDefinition[] {
    return vrmFiles
      .map((vrmFile) => {
        try {
          return this.buildVrmModelDefinition(vrmFile, rootDir, source)
        } catch (error) {
          logger.warn(`[PetModelCatalog] Skipped invalid VRM model: ${vrmFile}`, error)
          return null
        }
      })
      .filter((model): model is PetModelDefinition => model !== null)
  }

  private buildPluginProviderModels(): PetModelDefinition[] {
    if (!this.pluginRegistry) {
      return []
    }

    return this.pluginRegistry.snapshot().plugins.flatMap((plugin) => {
      const allowedModelScopes = plugin.permissions?.modelScopes ?? []
      return (plugin.modelProviders ?? [])
        .filter((provider) => allowedModelScopes.length === 0 || allowedModelScopes.includes(provider.id))
        .map((provider) => ({
          id: `plugin:${provider.id}`,
          name: provider.name,
          type: provider.modelType,
          source: 'plugin' as const,
          assetPath: provider.assetPath ?? `providers/${provider.id}`,
          motions: [],
          expressions: [],
          emotions: [],
        }))
    })
  }

  private collectModelFiles(rootDir: string): string[] {
    return this.collectFilesBySuffix(rootDir, '.model3.json')
  }

  private findFirstModelFile(rootDir: string): string {
    const [modelFile] = this.collectModelFiles(rootDir)
    if (!modelFile) {
      throw new Error('No .model3.json file found in the selected folder')
    }
    return modelFile
  }

  private findFirstVrmFile(rootDir: string): string {
    const [vrmFile] = this.collectVrmFiles(rootDir)
    if (!vrmFile) {
      throw new Error('No .vrm file found in the selected folder')
    }
    return vrmFile
  }

  private resolveUniqueImportTarget(rootDir: string, sourceFolderName: string): string {
    const baseName = sanitizeImportFolderName(sourceFolderName)
    let candidate = path.join(rootDir, baseName)
    let index = 1
    while (fs.existsSync(candidate)) {
      index += 1
      candidate = path.join(rootDir, `${baseName}-${index}`)
    }
    return candidate
  }

  private collectVrmFiles(rootDir: string): string[] {
    return this.collectFilesBySuffix(rootDir, '.vrm')
  }

  private collectFilesBySuffix(rootDir: string, suffix: string): string[] {
    const files: string[] = []
    const realRoot = realpathOrNull(rootDir)
    if (!realRoot) {
      return files
    }

    const walk = (dirPath: string) => {
      const realDir = realpathOrNull(dirPath)
      if (!realDir || !isPathInsideRealBase(realRoot, realDir)) {
        return
      }
      const entries = fs.readdirSync(realDir, { withFileTypes: true })

      for (const entry of entries) {
        const absolutePath = path.join(realDir, entry.name)
        const linkStatus = fs.lstatSync(absolutePath)
        if (linkStatus.isSymbolicLink()) {
          continue
        }
        const realEntryPath = realpathOrNull(absolutePath)
        if (!realEntryPath || !isPathInsideRealBase(realRoot, realEntryPath)) {
          continue
        }
        const stat = fs.statSync(realEntryPath)
        if (stat.isDirectory()) {
          walk(realEntryPath)
          continue
        }

        if (stat.isFile() && entry.name.toLowerCase().endsWith(suffix.toLowerCase())) {
          files.push(realEntryPath)
        }
      }
    }

    walk(rootDir)
    return files
  }

  private extractMotions(config: CubismModelJson): PetModelMotionOption[] {
    const motions = config.FileReferences?.Motions ?? {}

    return Object.entries(motions).flatMap(([group, entries]) =>
      entries.map((_entry, index) => ({
        id: `${group}:${index}`,
        group,
        index,
        label: buildMotionLabel(group, entries.length, index),
      })),
    )
  }

  private extractExpressions(config: CubismModelJson): PetModelExpressionOption[] {
    const expressions = config.FileReferences?.Expressions ?? []

    return expressions.map((entry, index) => {
      const fallbackName = basenameWithoutExt(entry.File ?? `expression-${index + 1}`)
      const name = entry.Name?.trim() || fallbackName

      return {
        name,
        label: titleCase(name),
      }
    })
  }

  private parseModelConfig(modelFilePath: string): CubismModelJson {
    return JSON.parse(fs.readFileSync(modelFilePath, 'utf8')) as CubismModelJson
  }

  private collectReferencedLive2dAssets(config: CubismModelJson): CubismAssetReference[] {
    const references = config.FileReferences
    if (!references) {
      return []
    }

    const assets: CubismAssetReference[] = []
    const addAsset = (label: string, file: unknown): void => {
      if (hasText(file)) {
        assets.push({ label, file: file.trim() })
      }
    }

    addAsset('Moc', references.Moc)
    references.Textures?.forEach((texture, index) => addAsset(`Texture ${index + 1}`, texture))
    addAsset('Physics', references.Physics)
    addAsset('Pose', references.Pose)
    addAsset('DisplayInfo', references.DisplayInfo)
    addAsset('UserData', references.UserData)
    references.Expressions?.forEach((expression, index) =>
      addAsset(`Expression ${expression.Name?.trim() || index + 1}`, expression.File),
    )
    Object.entries(references.Motions ?? {}).forEach(([group, motions]) => {
      motions.forEach((motion, index) => {
        addAsset(`Motion ${group}:${index}`, motion.File)
        addAsset(`Motion sound ${group}:${index}`, motion.Sound)
      })
    })

    return assets
  }

  private validateLive2dModelFile(
    modelFilePath: string,
    rootDir: string,
    config: CubismModelJson,
  ): void {
    const references = config.FileReferences
    if (!references || !hasText(references.Moc)) {
      throw new Error('Live2D model is missing FileReferences.Moc')
    }
    if (!Array.isArray(references.Textures) || references.Textures.length === 0 || references.Textures.some((texture) => !hasText(texture))) {
      throw new Error('Live2D model is missing FileReferences.Textures')
    }

    const modelDir = path.dirname(modelFilePath)
    const realRoot = realpathOrNull(rootDir)
    const realModelDir = realpathOrNull(modelDir)
    if (!realRoot || !realModelDir || !isPathInsideRealBase(realRoot, realModelDir)) {
      throw new Error('Live2D model directory is outside the model library')
    }

    const missingAssets = this.collectReferencedLive2dAssets(config)
      .filter((reference) => !this.resolveReferencedLive2dAsset(modelDir, realModelDir, reference.file))
    if (missingAssets.length > 0) {
      const preview = missingAssets
        .slice(0, 4)
        .map((asset) => `${asset.label}: ${asset.file}`)
        .join(', ')
      const suffix = missingAssets.length > 4 ? `, and ${missingAssets.length - 4} more` : ''
      throw new Error(`Live2D model has missing or unsafe referenced assets: ${preview}${suffix}`)
    }
  }

  private resolveReferencedLive2dAsset(
    modelDir: string,
    realModelDir: string,
    referencePath: string,
  ): string | null {
    const reference = referencePath.trim()
    if (!reference || path.isAbsolute(reference)) {
      return null
    }

    const candidatePath = path.resolve(modelDir, reference)
    const relativeToModelDir = path.relative(modelDir, candidatePath)
    if (relativeToModelDir.startsWith('..') || path.isAbsolute(relativeToModelDir)) {
      return null
    }
    if (!fs.existsSync(candidatePath)) {
      return null
    }
    const linkStatus = fs.lstatSync(candidatePath)
    if (linkStatus.isSymbolicLink() || !linkStatus.isFile()) {
      return null
    }
    const realAssetPath = realpathOrNull(candidatePath)
    if (!realAssetPath || !isPathInsideRealBase(realModelDir, realAssetPath)) {
      return null
    }
    return realAssetPath
  }

  private buildModelDefinition(
    modelFilePath: string,
    rootDir: string,
    source: 'bundled' | 'local',
  ): PetModelDefinition {
    const relativeModelPath = this.getManagedRelativePath(rootDir, modelFilePath)
    const modelDir = path.dirname(relativeModelPath)
    const parsedConfig = this.parseModelConfig(modelFilePath)
    this.validateLive2dModelFile(modelFilePath, rootDir, parsedConfig)
    const folderName = path.basename(modelDir)
    const name = titleCase(folderName || basenameWithoutExt(modelFilePath))
    const rawId = toPosixPath(modelDir || basenameWithoutExt(modelFilePath)).replace(/[^\w/-]+/g, '-')
    const id = source === 'local' ? `local:${rawId}` : rawId
    const motions = this.extractMotions(parsedConfig)
    const manifest: AvatarManifest = {
      ...this.avatarManifestService.buildAvatarManifest(modelFilePath, rootDir),
      id: rawId,
      modelJson: relativeModelPath,
    }
    const expressions = manifest.expressions.length > 0
      ? manifest.expressions.map((expression) => ({ name: expression.id, label: expression.label }))
      : this.extractExpressions(parsedConfig)
    const assetPath = source === 'local'
      ? `${USER_LIVE2D_ASSET_PREFIX}${encodeAssetPath(relativeModelPath)}`
      : relativeModelPath

    if (source === 'local') {
      this.localModelDirs.set(id, {
        rootDir: this.userLive2dRootDir,
        removePath: this.resolveLocalRemovalPath(modelFilePath, this.userLive2dRootDir),
      })
    }

    return {
      id,
      name,
      type: 'live2d',
      source,
      assetPath,
      motions,
      expressions,
      emotions: this.extractEmotions(id, motions, expressions, manifest),
      manifest,
      promptContext: this.avatarManifestService.buildPromptContext(manifest).prompt,
    }
  }

  private buildVrmModelDefinition(
    vrmFilePath: string,
    rootDir: string,
    source: 'bundled' | 'local',
  ): PetModelDefinition {
    const relativeModelPath = this.getManagedRelativePath(rootDir, vrmFilePath)
    const name = titleCase(basenameWithoutExt(vrmFilePath))
    const normalizedPath = toPosixPath(relativeModelPath).replace(/[^\w/-]+/g, '-')
    const id = source === 'local' ? `local:vrm/${normalizedPath}` : `vrm:${normalizedPath}`
    const assetPath = source === 'local'
      ? `${USER_VRM_ASSET_PREFIX}${encodeAssetPath(relativeModelPath)}`
      : relativeModelPath

    if (source === 'local') {
      this.localModelDirs.set(id, {
        rootDir: this.userVrmRootDir,
        removePath: this.resolveLocalRemovalPath(vrmFilePath, this.userVrmRootDir),
      })
    }

    return {
      id,
      name,
      type: 'vrm',
      source,
      assetPath,
      motions: [],
      expressions: [],
      emotions: [],
    }
  }

  private requireImportedLocalModel(
    modelFilePath: string,
    rootDir: string,
    assetPrefix: string,
  ): PetModelDefinition {
    const relativeModelPath = this.getManagedRelativePath(rootDir, modelFilePath)
    const assetPath = `${assetPrefix}${encodeAssetPath(relativeModelPath)}`
    const model = this.getModels().find((item) => item.assetPath === assetPath)
      ?? this.getModels().find((item) => (
        item.source === 'local' &&
        item.assetPath.startsWith(assetPrefix) &&
        toPosixPath(decodeURIComponent(item.assetPath.replace(assetPrefix, ''))) === relativeModelPath
      ))
    if (!model) {
      throw new Error('Imported model was copied, but it could not be indexed')
    }
    return model
  }

  private resolveLocalRemovalPath(modelFilePath: string, rootDir: string): string {
    const modelDir = path.dirname(modelFilePath)
    const resolvedModelDir = realpathOrNull(modelDir) ?? path.resolve(modelDir)
    const resolvedRootDir = realpathOrNull(rootDir) ?? path.resolve(rootDir)
    return resolvedModelDir === resolvedRootDir
      ? modelFilePath
      : modelDir
  }

  private getManagedRelativePath(rootDir: string, filePath: string): string {
    const resolvedRootDir = realpathOrNull(rootDir) ?? path.resolve(rootDir)
    const resolvedFilePath = realpathOrNull(filePath) ?? path.resolve(filePath)
    const relativePath = path.relative(resolvedRootDir, resolvedFilePath)
    if (!relativePath || relativePath.startsWith('..') || path.isAbsolute(relativePath)) {
      throw new Error(`Managed model path escaped root: ${resolvedFilePath}`)
    }
    return toPosixPath(relativePath)
  }

  private findImportedLocalModel(
    modelType: PetModelDefinition['type'],
    previousIds: Set<string>,
  ): PetModelDefinition | null {
    return this.getModels().find((item) => (
      item.source === 'local' &&
      item.type === modelType &&
      !previousIds.has(item.id)
    )) ?? null
  }

  private resolveVrmRootDir(): string | null {
    return VRM_ROOT_CANDIDATES.find((candidate) => fs.existsSync(candidate)) ?? null
  }

  private extractEmotions(
    modelId: string,
    motions: PetModelMotionOption[],
    expressions: PetModelExpressionOption[],
    manifest: AvatarManifest,
  ): PetEmotionPreset[] {
    const rawEntry = this.emotionMap[modelId]
    const rawEmotions = rawEntry?.emotions ?? {}
    const motionLookup = new Map<string, PetModelMotionOption>()
    const expressionNames = new Set(expressions.map((expression) => expression.name))

    for (const motion of motions) {
      motionLookup.set(`${motion.group}:${motion.index}`, motion)
    }

    const mappedEmotions = Object.entries(rawEmotions)
      .map(([emotionId, preset]) => {
        const resolvedMotions: PetEmotionMotionTarget[] = (preset.motions ?? [])
          .map((target) => {
            const group = target.group?.trim()
            const index = target.index ?? 0
            if (!group) {
              return null
            }

            const matchedMotion = motionLookup.get(`${group}:${index}`)
            if (!matchedMotion) {
              return null
            }

            return {
              group: matchedMotion.group,
              index: matchedMotion.index,
              label: matchedMotion.label,
            }
          })
          .filter((target): target is PetEmotionMotionTarget => target !== null)

        const resolvedExpressions = (preset.expressions ?? []).filter((name) =>
          expressionNames.has(name),
        )
        const manifestExpression = expressions.find(
          (expression) =>
            expression.name === emotionId ||
            expression.name.toLowerCase() === emotionId.toLowerCase(),
        )
        const fallbackExpressions = resolvedExpressions.length > 0
          ? resolvedExpressions
          : manifestExpression
            ? [manifestExpression.name]
            : []

        if (resolvedMotions.length === 0 && fallbackExpressions.length === 0) {
          return null
        }

        return {
          id: emotionId,
          label: preset.label?.trim() || titleCase(emotionId),
          motions: resolvedMotions,
          expressions: fallbackExpressions,
        }
      })
      .filter((emotion): emotion is PetEmotionPreset => emotion !== null)

    const byId = new Map(mappedEmotions.map((emotion) => [emotion.id, emotion]))

    for (const derivedEmotion of this.deriveManifestEmotionPresets(manifest, expressionNames)) {
      const existing = byId.get(derivedEmotion.id)
      if (!existing) {
        byId.set(derivedEmotion.id, derivedEmotion)
        continue
      }

      const existingExpressions = new Set(existing.expressions)
      for (const expression of derivedEmotion.expressions) {
        if (!existingExpressions.has(expression)) {
          existing.expressions.push(expression)
        }
      }
    }

    return [...byId.values()]
  }

  private deriveManifestEmotionPresets(
    manifest: AvatarManifest,
    expressionNames: Set<string>,
  ): PetEmotionPreset[] {
    const byId = new Map<string, PetEmotionPreset>()

    for (const expression of manifest.expressions) {
      if (expression.kind !== 'emotion' || !expressionNames.has(expression.id)) {
        continue
      }

      const rule = inferDerivedEmotion(expression)
      const id = rule?.id ?? expression.id
      const preset = byId.get(id) ?? {
        id,
        label: rule?.label ?? expression.label,
        motions: [],
        expressions: [],
      }

      if (!preset.expressions.includes(expression.id)) {
        preset.expressions.push(expression.id)
      }
      byId.set(id, preset)
    }

    return [...byId.values()]
  }
}
