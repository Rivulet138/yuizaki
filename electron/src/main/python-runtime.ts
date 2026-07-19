import fs from 'node:fs'
import path from 'node:path'

export type PythonRuntime = {
  executable: string
  venvPath: string
  venvExists: boolean
}

export const pythonVenvCandidates = (
  pythonDir: string,
  platform: NodeJS.Platform = process.platform,
): string[] => platform === 'win32'
  ? [path.join(pythonDir, '.venv', 'Scripts', 'python.exe')]
  : [
      path.join(pythonDir, '.venv', 'bin', 'python'),
      path.join(pythonDir, '.venv', 'bin', 'python3'),
    ]

export const resolvePythonRuntime = (
  pythonDir: string,
  platform: NodeJS.Platform = process.platform,
  exists: (targetPath: string) => boolean = fs.existsSync,
): PythonRuntime => {
  const candidates = pythonVenvCandidates(pythonDir, platform)
  const defaultVenvPath = candidates[0]
  if (!defaultVenvPath) {
    throw new Error(`No Python virtual environment path is defined for ${platform}`)
  }
  const venvPath = candidates.find(exists) ?? defaultVenvPath
  const venvExists = exists(venvPath)
  return {
    executable: venvExists ? venvPath : platform === 'win32' ? 'python' : 'python3',
    venvPath,
    venvExists,
  }
}
