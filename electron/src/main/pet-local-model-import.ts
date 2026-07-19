import { dialog } from 'electron'
import fs from 'node:fs'
import path from 'node:path'
import type {
  PetControlConfigPatch,
  PetControlState,
  PetModelCatalogPayload,
  PetModelDefinition,
} from '../shared/pet-control'
import type {
  LocalModelImportResponse,
  LocalModelPickerResponse,
  LocalModelRoots,
  PetImportableModelType,
  PetModelImportMode,
} from '../shared/resource-manager'

export const isImportableModelType = (value: unknown): value is PetImportableModelType =>
  value === 'live2d' || value === 'vrm'

export const isModelImportMode = (value: unknown): value is PetModelImportMode =>
  isImportableModelType(value) || value === 'auto'

interface PetModelCatalogOps {
  refresh: () => void
  normalizeModelId: (modelId: string | null | undefined) => string | null
  getModelById: (modelId: string | null | undefined) => PetModelDefinition | null
  getModels: () => PetModelDefinition[]
  getCatalog: (activeModelId: string | null) => PetModelCatalogPayload
  getLocalModelRoots: () => LocalModelRoots
  importLocalLive2dModel: (sourcePath: string) => Promise<PetModelDefinition>
  importLocalVrmModel: (sourcePath: string) => PetModelDefinition
  removeLocalModel: (modelId: string) => boolean
}

interface PetStateStoreOps {
  getState: () => PetControlState
  applyConfigPatch: (patch: PetControlConfigPatch) => PetControlState
}

export interface PetModelMutationContext {
  petModelCatalog: PetModelCatalogOps
  petStateStore: PetStateStoreOps
  applyStateToLive2D: (state: PetControlState) => PetControlState
}

export interface FreshPetCatalogResult {
  state: PetControlState
  catalog: PetModelCatalogPayload
}

interface RefreshPetCatalogOptions {
  fallbackMissingToDefault?: boolean
}

export interface DeleteLocalModelResult extends FreshPetCatalogResult {
  success: true
  modelRoots: LocalModelRoots
}

const toRealPathOrNull = (inputPath: string): string | null => {
  try {
    return fs.realpathSync.native(inputPath)
  } catch {
    return null
  }
}

const isPathInsideRealBase = (baseDir: string, targetPath: string): boolean => {
  const relative = path.relative(baseDir, targetPath)
  return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative))
}

const collectFilesBySuffix = (rootDir: string, suffix: string): string[] => {
  const files: string[] = []
  const realRoot = toRealPathOrNull(rootDir)
  if (!realRoot) return files

  const walk = (dirPath: string): void => {
    const realDir = toRealPathOrNull(dirPath)
    if (!realDir || !isPathInsideRealBase(realRoot, realDir)) return

    for (const entry of fs.readdirSync(realDir, { withFileTypes: true })) {
      const absolutePath = path.join(realDir, entry.name)
      const linkStatus = fs.lstatSync(absolutePath)
      if (linkStatus.isSymbolicLink()) continue

      const realEntryPath = toRealPathOrNull(absolutePath)
      if (!realEntryPath || !isPathInsideRealBase(realRoot, realEntryPath)) continue

      const stat = fs.statSync(realEntryPath)
      if (stat.isDirectory()) {
        walk(realEntryPath)
        continue
      }

      if (stat.isFile() && entry.name.toLowerCase().endsWith(suffix)) {
        files.push(realEntryPath)
      }
    }
  }

  walk(rootDir)
  return files
}

export const detectLocalModelType = (sourcePath: string): PetImportableModelType => {
  const rawSourcePath = String(sourcePath || '').trim()
  const source = path.resolve(rawSourcePath)
  if (!rawSourcePath || !fs.existsSync(source)) {
    throw new Error('本地模型路径不存在')
  }

  const stat = fs.statSync(source)
  if (stat.isFile()) {
    const lowerSource = source.toLowerCase()
    if (lowerSource.endsWith('.model3.json') || lowerSource.endsWith('.zip')) return 'live2d'
    if (lowerSource.endsWith('.vrm')) return 'vrm'
    throw new Error('请选择 Live2D .model3.json/.zip、VRM .vrm 文件，或包含模型文件的文件夹')
  }

  if (!stat.isDirectory()) {
    throw new Error('请选择 Live2D 或 3D/VRM 模型文件夹')
  }

  const hasLive2dModel = collectFilesBySuffix(source, '.model3.json').length > 0
  const hasVrmModel = collectFilesBySuffix(source, '.vrm').length > 0
  if (hasLive2dModel && hasVrmModel) {
    throw new Error('所选文件夹同时包含 Live2D 和 3D/VRM 模型，请在手动导入中指定类型')
  }
  if (hasLive2dModel) return 'live2d'
  if (hasVrmModel) return 'vrm'

  throw new Error('所选文件夹中未找到 Live2D .model3.json 或 3D/VRM .vrm 文件')
}

export const pickLocalModelSource = async (modelType: PetModelImportMode): Promise<LocalModelPickerResponse> => {
  const result = await dialog.showOpenDialog({
    title: modelType === 'auto'
      ? 'Import Live2D or 3D model folder'
      : modelType === 'live2d'
        ? 'Import Live2D model'
        : 'Import 3D/VRM model',
    properties: modelType === 'auto' ? ['openDirectory'] : ['openFile', 'openDirectory'],
    filters: modelType === 'live2d'
      ? [
          { name: 'Live2D model or archive', extensions: ['model3.json', 'json', 'zip'] },
          { name: 'All files', extensions: ['*'] },
        ]
      : modelType === 'vrm'
        ? [
            { name: 'VRM model', extensions: ['vrm'] },
            { name: 'All files', extensions: ['*'] },
          ]
        : [
            { name: 'Model folder', extensions: ['*'] },
          ],
  })

  const sourcePath = result.canceled || result.filePaths.length === 0
    ? null
    : result.filePaths[0] ?? null

  return {
    canceled: !sourcePath,
    modelType,
    sourcePath,
  }
}

export const refreshPetCatalog = (
  ctx: PetModelMutationContext,
  options: RefreshPetCatalogOptions = {},
): FreshPetCatalogResult => {
  ctx.petModelCatalog.refresh()

  const currentState = ctx.petStateStore.getState()
  const activeModel = ctx.petModelCatalog.getModelById(currentState.modelId)
  let patch: PetControlConfigPatch | null = null

  if (activeModel) {
    if (currentState.modelId !== activeModel.id || currentState.modelType !== activeModel.type) {
      patch = { modelId: activeModel.id, modelType: activeModel.type }
    }
  } else if (options.fallbackMissingToDefault) {
    const fallbackModelId = ctx.petModelCatalog.normalizeModelId(currentState.modelId)
    const fallbackModel = ctx.petModelCatalog.getModelById(fallbackModelId)
    patch = { modelId: fallbackModelId }
    if (fallbackModel) {
      patch.modelType = fallbackModel.type
    }
  }

  const nextState = patch
    ? ctx.applyStateToLive2D(ctx.petStateStore.applyConfigPatch(patch))
    : currentState

  return {
    state: nextState,
    catalog: ctx.petModelCatalog.getCatalog(ctx.petStateStore.getState().modelId),
  }
}

export const importLocalModelFromPath = async (
  ctx: PetModelMutationContext,
  sourcePath: string,
  modelType: PetModelImportMode,
): Promise<LocalModelImportResponse> => {
  const resolvedModelType = modelType === 'auto' ? detectLocalModelType(sourcePath) : modelType
  const importedModel = resolvedModelType === 'vrm'
    ? ctx.petModelCatalog.importLocalVrmModel(sourcePath)
    : await ctx.petModelCatalog.importLocalLive2dModel(sourcePath)
  const nextState = ctx.applyStateToLive2D(ctx.petStateStore.applyConfigPatch({
    modelId: importedModel.id,
    modelType: importedModel.type,
  }))

  return {
    success: true,
    modelType: importedModel.type,
    importedModelId: importedModel.id,
    state: nextState,
    localModels: ctx.petModelCatalog.getModels().filter((model) => model.source === 'local'),
    catalog: ctx.petModelCatalog.getCatalog(ctx.petStateStore.getState().modelId),
    modelRoots: ctx.petModelCatalog.getLocalModelRoots(),
  }
}

export const deleteLocalModelById = (
  ctx: PetModelMutationContext,
  modelId: string,
): DeleteLocalModelResult | null => {
  const removed = ctx.petModelCatalog.removeLocalModel(modelId)
  if (!removed) {
    return null
  }

  const fresh = refreshPetCatalog(ctx, { fallbackMissingToDefault: true })
  return {
    success: true,
    state: fresh.state,
    catalog: fresh.catalog,
    modelRoots: ctx.petModelCatalog.getLocalModelRoots(),
  }
}
