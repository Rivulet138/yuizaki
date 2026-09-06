import fs from 'node:fs'
import path from 'node:path'

export type RuntimePathOptions = {
  cwd?: string
  dirname?: string
  resourcesPath?: string
  projectRootOverride?: string | undefined
}

export type WritableRuntimePaths = {
  dataDir: string
  settingsPath: string
  audioCacheDir: string
  cacheDir: string
  sherpaDir: string
  sherpaOnlineDir: string
  genieDataDir: string
  genieWorkspaceRoot: string
  huggingfaceHome: string
  soulxServiceDir: string
}

const hasPythonRuntime = (root: string): boolean => fs.existsSync(path.join(root, 'python', 'app.py'))

export const resolveRuntimeProjectRoot = (options: RuntimePathOptions = {}): string => {
  const explicitRoot = options.projectRootOverride?.trim() || process.env['YUIZAKI_PROJECT_ROOT']?.trim()
  if (explicitRoot) return path.resolve(explicitRoot)

  const resourcesPath = options.resourcesPath ?? process.resourcesPath
  if (resourcesPath) {
    const packagedRoot = path.join(resourcesPath, 'runtime')
    if (hasPythonRuntime(packagedRoot) && fs.existsSync(path.join(packagedRoot, 'resources.lock.json'))) {
      return packagedRoot
    }
  }

  const cwd = options.cwd ?? process.cwd()
  if (hasPythonRuntime(cwd)) return path.resolve(cwd)
  const electronChild = path.join(cwd, 'electron')
  if (fs.existsSync(path.join(electronChild, 'package.json')) && hasPythonRuntime(path.resolve(cwd))) {
    return path.resolve(cwd)
  }
  if (hasPythonRuntime(path.join(cwd, '..'))) return path.resolve(cwd, '..')

  return path.resolve(options.dirname ?? __dirname, '../../..')
}

export const isPackagedRuntime = (root = resolveRuntimeProjectRoot()): boolean =>
  Boolean(process.resourcesPath && root === path.join(process.resourcesPath, 'runtime'))

export const resolveWritableRuntimePaths = (userDataDir: string): WritableRuntimePaths => {
  const dataDir = path.join(userDataDir, 'python-data')
  const cacheDir = path.join(dataDir, '.cache')
  return {
    dataDir,
    settingsPath: path.join(dataDir, 'settings.json'),
    audioCacheDir: path.join(dataDir, 'audio_cache'),
    cacheDir,
    sherpaDir: path.join(cacheDir, 'sherpa-onnx', 'sensevoice'),
    sherpaOnlineDir: path.join(cacheDir, 'sherpa-onnx', 'streaming-zipformer-small-ctc-zh'),
    genieDataDir: path.join(cacheDir, 'GenieData', 'GenieData'),
    genieWorkspaceRoot: dataDir,
    huggingfaceHome: path.join(cacheDir, 'huggingface'),
    soulxServiceDir: path.join(userDataDir, 'soulx-svc'),
  }
}
