import fs from 'node:fs'
import path from 'node:path'
import { isPathInsideBase } from './http/utils'
import type {
  AvatarExpression,
  AvatarManifest,
  AvatarParameterControl,
  AvatarPromptContext,
  ExpressionKind,
  MotionBinding,
} from '../shared/pet-control'

interface CubismModelReference {
  File?: string
  Name?: string
}

interface CubismModelJson {
  FileReferences?: {
    DisplayInfo?: string
    Expressions?: CubismModelReference[]
    Motions?: Record<string, CubismModelReference[]>
  }
  Groups?: Array<{
    Target?: string
    Name?: string
    Ids?: string[]
  }>
}

interface Cdi3Parameter {
  Id?: string
  Name?: string
}

interface Cdi3Payload {
  Parameters?: Cdi3Parameter[]
}

interface VtubeParameterSetting {
  Name?: string
  OutputLive2D?: string
  OutputRangeLower?: number
  OutputRangeUpper?: number
}

interface VtubePayload {
  ParameterSettings?: VtubeParameterSetting[]
}

interface ParameterInfo {
  id: string
  label: string
  min: number
  max: number
}

const GENERIC_PARAMETER_RANGES: Record<string, { min: number; max: number; prompt: string }> = {
  ParamAngleX: { min: -30, max: 30, prompt: 'turn head left or right' },
  ParamAngleY: { min: -30, max: 30, prompt: 'tilt head up or down' },
  ParamAngleZ: { min: -30, max: 30, prompt: 'tilt head clockwise or counterclockwise' },
  ParamBodyAngleX: { min: -10, max: 10, prompt: 'lean body left or right' },
  ParamBodyAngleY: { min: -10, max: 10, prompt: 'lean body forward or backward' },
  ParamBodyAngleZ: { min: -10, max: 10, prompt: 'tilt body clockwise or counterclockwise' },
  ParamEyeLOpen: { min: 0, max: 1, prompt: 'open or close left eye' },
  ParamEyeROpen: { min: 0, max: 1, prompt: 'open or close right eye' },
  ParamMouthOpenY: { min: 0, max: 1, prompt: 'open or close mouth' },
}

const toPosixPath = (inputPath: string): string => inputPath.replace(/\\/g, '/')

const titleCase = (value: string): string =>
  value
    .replace(/[-_]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase())

const basenameWithoutExt = (filePath: string): string =>
  path.basename(filePath, path.extname(filePath))

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null

const readJson = <T>(filePath: string): T | null => {
  try {
    return JSON.parse(fs.readFileSync(filePath, 'utf8')) as T
  } catch {
    return null
  }
}

const realpathOrNull = (filePath: string): string | null => {
  try {
    return fs.realpathSync.native(filePath)
  } catch {
    return null
  }
}

const inferExpressionKind = (name: string): ExpressionKind => {
  const lowered = name.toLowerCase()
  if (/pose|hand|arm|hair|tail|ear|shou|rhair|hair/.test(lowered) || /手|发|髮|尾|耳|抱枕|话筒/.test(name)) {
    return 'pose'
  }
  if (/star|heart|eye|mouth|angry|shock|red|black|tear/.test(lowered) || /眼|嘴|泪|星|爱心|红|黑/.test(name)) {
    return 'emotion'
  }
  if (/effect|water|shuiyin/.test(lowered) || /水印|漂浮|小狗/.test(name)) {
    return 'effect'
  }
  return 'emotion'
}

export class AvatarManifestService {
  constructor(private readonly live2dRootDir: string) {}

  discoverModels(rootPath = this.live2dRootDir): string[] {
    return this.collectFiles(rootPath, '.model3.json')
  }

  discoverExpressions(modelDir: string, modelJson: CubismModelJson): AvatarExpression[] {
    const byId = new Map<string, AvatarExpression>()
    const references = modelJson.FileReferences?.Expressions ?? []

    references.forEach((entry, index) => {
      const file = entry.File ?? `expression-${index + 1}.exp3.json`
      const resolvedFile = this.resolveModelRelativePath(modelDir, file)
      if (!resolvedFile) {
        return
      }
      const relativeFile = toPosixPath(path.relative(modelDir, resolvedFile))
      const id = entry.Name?.trim() || basenameWithoutExt(file)
      byId.set(id, {
        id,
        label: titleCase(id),
        kind: inferExpressionKind(id),
        prompt: titleCase(id).toLowerCase(),
        binding: { mode: 'file', file: relativeFile },
      })
    })

    for (const filePath of this.collectFiles(modelDir, '.exp3.json')) {
      const relativeFile = toPosixPath(path.relative(modelDir, filePath))
      const id = basenameWithoutExt(filePath)
      if (!byId.has(id)) {
        byId.set(id, {
          id,
          label: titleCase(id),
          kind: inferExpressionKind(id),
          prompt: titleCase(id).toLowerCase(),
          binding: { mode: 'file', file: relativeFile },
        })
      }
    }

    return [...byId.values()].sort((a, b) => a.id.localeCompare(b.id))
  }

  discoverMotions(modelDir: string, modelJson: CubismModelJson): Record<string, MotionBinding> {
    const motions: Record<string, MotionBinding> = {}
    const references = modelJson.FileReferences?.Motions ?? {}
    for (const [group, entries] of Object.entries(references)) {
      entries.forEach((entry, index) => {
        if (!entry.File) {
          return
        }
        const resolvedFile = this.resolveModelRelativePath(modelDir, entry.File)
        if (resolvedFile) {
          motions[`${group}:${index}`] = {
            file: toPosixPath(path.relative(modelDir, resolvedFile)),
            group,
          }
        }
      })
    }

    for (const filePath of this.collectFiles(modelDir, '.motion3.json')) {
      const relativeFile = toPosixPath(path.relative(modelDir, filePath))
      const id = basenameWithoutExt(filePath)
      if (!motions[id]) {
        motions[id] = { file: relativeFile }
      }
    }

    return motions
  }

  discoverParameters(modelDir: string, modelJson: CubismModelJson): AvatarParameterControl[] {
    const cdi3Path = this.resolveCdi3Path(modelDir, modelJson)
    const vtubePath = this.collectFiles(modelDir, '.vtube.json')[0]
    const parameters = new Map<string, ParameterInfo>()

    if (cdi3Path) {
      const cdi3 = readJson<Cdi3Payload>(cdi3Path)
      for (const item of cdi3?.Parameters ?? []) {
        if (typeof item.Id === 'string' && item.Id.trim()) {
          const generic = GENERIC_PARAMETER_RANGES[item.Id]
          parameters.set(item.Id, {
            id: item.Id,
            label: item.Name?.trim() || item.Id,
            min: generic?.min ?? -1,
            max: generic?.max ?? 1,
          })
        }
      }
    }

    if (vtubePath) {
      const vtube = readJson<VtubePayload>(vtubePath)
      for (const item of vtube?.ParameterSettings ?? []) {
        const id = typeof item.OutputLive2D === 'string' && item.OutputLive2D.trim()
          ? item.OutputLive2D
          : item.Name
        if (!id) continue
        const previous = parameters.get(id)
        parameters.set(id, {
          id,
          label: previous?.label ?? item.Name ?? id,
          min: typeof item.OutputRangeLower === 'number' ? item.OutputRangeLower : previous?.min ?? GENERIC_PARAMETER_RANGES[id]?.min ?? -1,
          max: typeof item.OutputRangeUpper === 'number' ? item.OutputRangeUpper : previous?.max ?? GENERIC_PARAMETER_RANGES[id]?.max ?? 1,
        })
      }
    }

    return [...parameters.values()]
      .map((item) => ({
        id: item.id,
        label: item.label,
        prompt: GENERIC_PARAMETER_RANGES[item.id]?.prompt ?? item.label.toLowerCase(),
        min: item.min,
        max: item.max,
      }))
      .sort((a, b) => a.id.localeCompare(b.id))
  }

  buildAvatarManifest(modelFilePath: string, rootDir = this.live2dRootDir): AvatarManifest {
    const modelDir = path.dirname(modelFilePath)
    const modelJson = readJson<CubismModelJson>(modelFilePath) ?? {}
    const relativeModelJson = toPosixPath(path.relative(rootDir, modelFilePath))
    const id = toPosixPath(path.dirname(relativeModelJson) || basenameWithoutExt(modelFilePath)).replace(/[^\w/-]+/g, '-')
    const name = this.resolveDisplayName(modelDir, id)
    const expressions = this.discoverExpressions(modelDir, modelJson)
    const parameterControls = this.discoverParameters(modelDir, modelJson)
    const motions = this.discoverMotions(modelDir, modelJson)
    const declaredLipSyncIds = (modelJson.Groups ?? [])
      .filter((group) => group.Target === 'Parameter' && group.Name === 'LipSync')
      .flatMap((group) => group.Ids ?? [])
      .filter((id): id is string => typeof id === 'string' && Boolean(id.trim()))
    const lipSyncParameterIds = [...new Set(
      declaredLipSyncIds.length > 0
        ? declaredLipSyncIds
        : ['ParamMouthOpenY'],
    )]

    return {
      id,
      name,
      summary: `${name} Live2D avatar with ${expressions.length} expressions and ${parameterControls.length} controllable parameters.`,
      persona: {
        tone: 'warm companion',
        traits: ['responsive', 'expressive'],
        styleRules: ['Use subtle expressions unless the user asks for strong emotion.'],
      },
      modelJson: relativeModelJson,
      modelTransform: this.buildDefaultTransform(modelDir),
      transformDefaults: this.buildDefaultTransform(modelDir),
      expressions,
      parameterControls,
      motions,
      lipSync: {
        parameterIds: lipSyncParameterIds,
      },
    }
  }

  buildPromptContext(manifest: AvatarManifest): AvatarPromptContext {
    const expressionLines = manifest.expressions.map((item) =>
      `- ${item.id} (${item.kind}): ${item.prompt}`,
    )
    const parameterLines = manifest.parameterControls.slice(0, 80).map((item) =>
      `- ${item.id}: ${item.prompt} [${item.min}..${item.max}]`,
    )
    const prompt = [
      `[CURRENT_AVATAR]`,
      `Model: ${manifest.name} (${manifest.id})`,
      `Persona tone: ${manifest.persona.tone}`,
      `Available expressions:`,
      ...expressionLines,
      `Available parameter controls:`,
      ...parameterLines,
      `Output pet_control using expressionMix and optional parameterOverrides only from this list.`,
    ].join('\n')

    return {
      modelId: manifest.id,
      modelName: manifest.name,
      expressions: manifest.expressions,
      parameterControls: manifest.parameterControls,
      prompt,
    }
  }

  buildDefaultTransform(_modelDir: string): { scale: number; offsetX: number; offsetY: number } {
    return { scale: 1, offsetX: 0, offsetY: 0 }
  }

  private collectFiles(rootDir: string, suffix: string): string[] {
    const files: string[] = []
    const realRoot = realpathOrNull(rootDir)
    if (!realRoot) {
      return files
    }

    const walk = (dirPath: string): void => {
      const realDir = realpathOrNull(dirPath)
      if (!realDir || !isPathInsideBase(realRoot, realDir)) {
        return
      }
      for (const entry of fs.readdirSync(realDir, { withFileTypes: true })) {
        const absolutePath = path.join(realDir, entry.name)
        const realEntryPath = realpathOrNull(absolutePath)
        if (!realEntryPath || !isPathInsideBase(realRoot, realEntryPath)) {
          continue
        }
        const stat = fs.statSync(realEntryPath)
        if (stat.isDirectory()) {
          walk(realEntryPath)
        } else if (stat.isFile() && entry.name.endsWith(suffix)) {
          files.push(realEntryPath)
        }
      }
    }
    walk(rootDir)
    return files.sort((a, b) => a.localeCompare(b))
  }

  private resolveModelRelativePath(modelDir: string, referencePath: string): string | null {
    const reference = referencePath.trim()
    if (!reference || path.isAbsolute(reference)) {
      return null
    }
    const realModelDir = realpathOrNull(modelDir)
    if (!realModelDir) {
      return null
    }
    const candidatePath = path.resolve(modelDir, reference)
    if (!isPathInsideBase(modelDir, candidatePath)) {
      return null
    }
    const realCandidatePath = realpathOrNull(candidatePath)
    if (!realCandidatePath || !isPathInsideBase(realModelDir, realCandidatePath)) {
      return null
    }
    return realCandidatePath
  }

  private resolveCdi3Path(modelDir: string, modelJson: CubismModelJson): string | null {
    const displayInfo = modelJson.FileReferences?.DisplayInfo
    if (displayInfo) {
      const displayInfoPath = this.resolveModelRelativePath(modelDir, displayInfo)
      if (displayInfoPath) {
        return displayInfoPath
      }
    }
    return this.collectFiles(modelDir, '.cdi3.json')[0] ?? null
  }

  private resolveDisplayName(modelDir: string, fallback: string): string {
    const parent = path.basename(modelDir)
    if (parent && parent !== '.') {
      return titleCase(parent)
    }
    return titleCase(fallback)
  }
}

export const isAvatarManifest = (value: unknown): value is AvatarManifest => {
  if (!isRecord(value)) return false
  return typeof value['id'] === 'string' && typeof value['name'] === 'string' && Array.isArray(value['expressions'])
}
