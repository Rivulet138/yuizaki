import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterAll, describe, expect, it, vi } from 'vitest'
import { PetModelCatalog } from '../pet-model-catalog'
import { DEFAULT_PET_CONTROL_STATE } from '../../shared/pet-control'

const mockUserDataRoot = vi.hoisted(() => {
  const tempRoot = process.env.TEMP || process.env.TMP || process.env.TMPDIR || '.'
  const normalizedTempRoot = tempRoot.replace(/[\\/]+$/, '')
  return `${normalizedTempRoot}/yuizaki-pet-catalog-${process.pid}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
})

vi.mock('electron', () => ({
  app: {
    getPath: vi.fn(() => mockUserDataRoot),
  },
}))

afterAll(() => {
  fs.rmSync(mockUserDataRoot, { recursive: true, force: true })
})

const uniqueName = (prefix: string): string =>
  `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`

const toPosixPath = (inputPath: string): string => inputPath.replace(/\\/g, '/')

const basenameWithoutExt = (filePath: string): string =>
  path.basename(filePath, path.extname(filePath))

const collectModelFiles = (rootDir: string): string[] => {
  if (!fs.existsSync(rootDir)) return []
  return fs.readdirSync(rootDir, { withFileTypes: true })
    .flatMap((entry) => {
      const entryPath = path.join(rootDir, entry.name)
      if (entry.isDirectory()) return collectModelFiles(entryPath)
      return entry.isFile() && entry.name.endsWith('.model3.json') ? [entryPath] : []
    })
}

const isUsableLive2dModelFile = (modelFile: string): boolean => {
  try {
    const parsed = JSON.parse(fs.readFileSync(modelFile, 'utf8')) as {
      FileReferences?: {
        Moc?: string
        Textures?: string[]
      }
    }
    const references = parsed.FileReferences
    const modelDir = path.dirname(modelFile)
    return Boolean(
      references?.Moc &&
      fs.existsSync(path.resolve(modelDir, references.Moc)) &&
      Array.isArray(references.Textures) &&
      references.Textures.length > 0 &&
      references.Textures.every((texture) => texture && fs.existsSync(path.resolve(modelDir, texture))),
    )
  } catch {
    return false
  }
}

const bundledLive2dModelIdsFromDisk = (): string[] => {
  const live2dRoot = path.resolve(process.cwd(), 'src/renderer/public/live2d')
  return collectModelFiles(live2dRoot)
    .filter(isUsableLive2dModelFile)
    .map((modelFile) => {
      const relativeModelPath = path.relative(live2dRoot, modelFile)
      const modelDir = path.dirname(relativeModelPath)
      const rawId = toPosixPath(modelDir || basenameWithoutExt(modelFile)).replace(/[^\w/-]+/g, '-')
      return rawId
    })
    .sort()
}

const writeLive2dFixture = (modelDir: string, modelName: string): string => {
  const modelFile = path.join(modelDir, `${modelName}.model3.json`)
  fs.mkdirSync(path.join(modelDir, 'textures'), { recursive: true })
  fs.mkdirSync(path.join(modelDir, 'motions'), { recursive: true })
  fs.writeFileSync(path.join(modelDir, `${modelName}.moc3`), 'moc-placeholder', 'utf8')
  fs.writeFileSync(path.join(modelDir, 'textures', 'texture_00.png'), 'png-placeholder', 'utf8')
  fs.writeFileSync(path.join(modelDir, 'happy.exp3.json'), '{}', 'utf8')
  fs.writeFileSync(path.join(modelDir, 'motions', 'idle.motion3.json'), '{}', 'utf8')
  fs.writeFileSync(
    modelFile,
    JSON.stringify({
      FileReferences: {
        Moc: `${modelName}.moc3`,
        Textures: ['textures/texture_00.png'],
        Expressions: [{ Name: 'happy', File: 'happy.exp3.json' }],
        Motions: {
          Idle: [{ File: 'motions/idle.motion3.json' }],
        },
      },
    }),
    'utf8',
  )
  return modelFile
}

describe('PetModelCatalog', () => {
  it('includes the active lip-sync profile in renderer configuration', () => {
    const catalog = new PetModelCatalog()
    const state = {
      ...DEFAULT_PET_CONTROL_STATE,
      lipSyncProfile: {
        gain: 6.2,
        noiseGate: 0.014,
        maxOpen: 0.8,
        attack: 0.55,
        release: 0.3,
      },
    }

    expect(catalog.buildRendererConfig(state).lipSyncProfile).toEqual(state.lipSyncProfile)
  })

  it('mirrors the usable bundled Live2D model files in the catalog', () => {
    const catalog = new PetModelCatalog()
    const bundledLive2dIds = catalog.getModels()
      .filter((item) => item.source === 'bundled' && item.type === 'live2d')
      .map((item) => item.id)
      .sort()

    expect(bundledLive2dIds).toEqual(bundledLive2dModelIdsFromDisk())
  })

  it('derives emotion presets from manifest expressions for the bundled Yumi model', () => {
    const catalog = new PetModelCatalog()
    const model = catalog.getModels().find((item) => item.id === 'llm-live2d/yumi')

    expect(model).toBeDefined()
    expect(model?.manifest).toBeDefined()
    expect(model?.expressions.length).toBeGreaterThan(0)
    expect(model?.emotions.length).toBeGreaterThan(0)
    expect(model?.emotions.some((emotion) => emotion.expressions.length > 0)).toBe(true)
  })

  it('rejects local Live2D assets that resolve outside the user model root', () => {
    const catalog = new PetModelCatalog()
    const root = catalog.getUserLive2dRootDir()
    const externalDir = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-live2d-outside-'))
    const linkName = `linked-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    const linkDir = path.join(root, linkName)

    try {
      fs.mkdirSync(root, { recursive: true })
      fs.writeFileSync(path.join(externalDir, 'secret.png'), 'not-a-real-image', 'utf8')
      fs.symlinkSync(externalDir, linkDir, process.platform === 'win32' ? 'junction' : 'dir')

      expect(catalog.resolveLocalLive2dAsset(`${linkName}/secret.png`)).toBeNull()
    } finally {
      fs.rmSync(linkDir, { recursive: true, force: true })
      fs.rmSync(externalDir, { recursive: true, force: true })
    }
  })

  it('does not discover local Live2D models through symlinked directories', () => {
    const catalog = new PetModelCatalog()
    const root = catalog.getUserLive2dRootDir()
    const externalDir = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-live2d-outside-'))
    const linkName = uniqueName('linked-model')
    const linkDir = path.join(root, linkName)

    try {
      fs.mkdirSync(root, { recursive: true })
      fs.writeFileSync(path.join(externalDir, 'escape.model3.json'), JSON.stringify({ FileReferences: {} }), 'utf8')
      try {
        fs.symlinkSync(externalDir, linkDir, process.platform === 'win32' ? 'junction' : 'dir')
      } catch {
        return
      }

      catalog.refresh()

      expect(catalog.getModels().some((model) => model.id === `local:${linkName}`)).toBe(false)
    } finally {
      fs.rmSync(linkDir, { recursive: true, force: true })
      fs.rmSync(externalDir, { recursive: true, force: true })
    }
  })

  it('skips local Live2D models with missing referenced runtime assets', () => {
    const catalog = new PetModelCatalog()
    const root = catalog.getUserLive2dRootDir()
    const modelName = uniqueName('broken-live2d')
    const modelDir = path.join(root, modelName)

    try {
      fs.mkdirSync(modelDir, { recursive: true })
      fs.writeFileSync(path.join(modelDir, `${modelName}.moc3`), 'moc-placeholder', 'utf8')
      fs.writeFileSync(
        path.join(modelDir, `${modelName}.model3.json`),
        JSON.stringify({
          FileReferences: {
            Moc: `${modelName}.moc3`,
            Textures: ['textures/missing.png'],
          },
        }),
        'utf8',
      )

      catalog.refresh()

      expect(catalog.getModels().some((model) => model.id === `local:${modelName}`)).toBe(false)
    } finally {
      fs.rmSync(modelDir, { recursive: true, force: true })
    }
  })

  it('imports Live2D model folders from outside the managed root and selects the model directory only', async () => {
    const catalog = new PetModelCatalog()
    const externalDir = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-live2d-import-'))
    const modelName = uniqueName('hero')
    const parentDir = path.join(externalDir, 'download-bundle')
    const modelDir = path.join(parentDir, modelName)

    try {
      writeLive2dFixture(modelDir, modelName)

      const imported = await catalog.importLocalLive2dModel(parentDir)

      expect(imported.type).toBe('live2d')
      expect(imported.source).toBe('local')
      expect(imported.assetPath.startsWith('/api/pet/assets/live2d/')).toBe(true)
      expect(imported.assetPath).toContain(encodeURIComponent(modelName))
      expect(imported.manifest?.modelJson).toBe(`${modelName}/${modelName}.model3.json`)

      const relativeAssetPath = decodeURIComponent(imported.assetPath.replace('/api/pet/assets/live2d/', ''))
      expect(catalog.resolveLocalLive2dAsset(relativeAssetPath)).toBeTruthy()
      expect(catalog.removeLocalModel(imported.id)).toBe(true)
      expect(catalog.getModels().some((model) => model.id === imported.id)).toBe(false)
    } finally {
      fs.rmSync(externalDir, { recursive: true, force: true })
    }
  }, 30000)

  it('rejects invalid Live2D imports and removes the copied managed folder', async () => {
    const catalog = new PetModelCatalog()
    const root = catalog.getUserLive2dRootDir()
    const externalDir = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-live2d-broken-import-'))
    const modelName = uniqueName('broken-import')
    const parentDir = path.join(externalDir, 'download-bundle')
    const modelDir = path.join(parentDir, modelName)
    const managedDir = path.join(root, modelName)

    try {
      fs.mkdirSync(modelDir, { recursive: true })
      fs.writeFileSync(path.join(modelDir, `${modelName}.moc3`), 'moc-placeholder', 'utf8')
      fs.writeFileSync(
        path.join(modelDir, `${modelName}.model3.json`),
        JSON.stringify({
          FileReferences: {
            Moc: `${modelName}.moc3`,
            Textures: ['textures/missing.png'],
          },
        }),
        'utf8',
      )

      await expect(catalog.importLocalLive2dModel(parentDir)).rejects.toThrow(/referenced assets|Textures/)
      expect(fs.existsSync(managedDir)).toBe(false)
      expect(catalog.getModels().some((model) => model.id === `local:${modelName}`)).toBe(false)
    } finally {
      fs.rmSync(managedDir, { recursive: true, force: true })
      fs.rmSync(externalDir, { recursive: true, force: true })
    }
  })

  it('imports and removes local VRM models from the managed local root', () => {
    const catalog = new PetModelCatalog()
    const externalDir = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-vrm-import-'))
    const vrmFile = path.join(externalDir, 'hero.vrm')

    try {
      fs.writeFileSync(vrmFile, 'vrm-binary-placeholder', 'utf8')
      const imported = catalog.importLocalVrmModel(vrmFile)

      expect(imported.type).toBe('vrm')
      expect(imported.source).toBe('local')
      expect(imported.assetPath.startsWith('/api/pet/assets/vrm/')).toBe(true)

      const relativeAssetPath = decodeURIComponent(imported.assetPath.replace('/api/pet/assets/vrm/', ''))
      expect(catalog.resolveLocalVrmAsset(relativeAssetPath)).toBeTruthy()
      expect(catalog.removeLocalModel(imported.id)).toBe(true)
      expect(catalog.getModels().some((model) => model.id === imported.id)).toBe(false)
    } finally {
      fs.rmSync(externalDir, { recursive: true, force: true })
    }
  })

  it('reuses a VRM file that is already in the managed root instead of copying it again', () => {
    const catalog = new PetModelCatalog()
    const root = catalog.getUserVrmRootDir()
    const fileName = `managed-${Date.now()}-${Math.random().toString(36).slice(2, 8)}.vrm`
    const vrmFile = path.join(root, fileName)

    try {
      fs.mkdirSync(root, { recursive: true })
      fs.writeFileSync(vrmFile, 'vrm-binary-placeholder', 'utf8')

      const imported = catalog.importLocalVrmModel(vrmFile)

      expect(imported.assetPath).toBe(`/api/pet/assets/vrm/${encodeURIComponent(fileName)}`)
      expect(fs.existsSync(vrmFile)).toBe(true)
      expect(catalog.removeLocalModel(imported.id)).toBe(true)
      expect(fs.existsSync(vrmFile)).toBe(false)
    } finally {
      fs.rmSync(vrmFile, { force: true })
    }
  })
})
