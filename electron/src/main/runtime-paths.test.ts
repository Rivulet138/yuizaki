import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { resolveRuntimeProjectRoot, resolveWritableRuntimePaths } from './runtime-paths'

const tempRoots: string[] = []

const makeTempRoot = (): string => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-runtime-paths-'))
  tempRoots.push(root)
  return root
}

afterEach(() => {
  while (tempRoots.length) {
    const root = tempRoots.pop()
    if (root) fs.rmSync(root, { recursive: true, force: true })
  }
})

describe('runtime path resolution', () => {
  it('requires both the packaged Python entrypoint and lockfile', () => {
    const resources = makeTempRoot()
    const runtime = path.join(resources, 'runtime')
    fs.mkdirSync(path.join(runtime, 'python'), { recursive: true })
    fs.writeFileSync(path.join(runtime, 'python', 'app.py'), '')

    expect(resolveRuntimeProjectRoot({ resourcesPath: resources, cwd: makeTempRoot() })).not.toBe(runtime)

    fs.writeFileSync(path.join(runtime, 'resources.lock.json'), '{}')
    expect(resolveRuntimeProjectRoot({ resourcesPath: resources, cwd: makeTempRoot() })).toBe(runtime)
  })

  it('gives an explicit project root precedence over packaged discovery', () => {
    const resources = makeTempRoot()
    const explicit = makeTempRoot()
    const runtime = path.join(resources, 'runtime')
    fs.mkdirSync(path.join(runtime, 'python'), { recursive: true })
    fs.writeFileSync(path.join(runtime, 'python', 'app.py'), '')
    fs.writeFileSync(path.join(runtime, 'resources.lock.json'), '{}')

    expect(resolveRuntimeProjectRoot({ resourcesPath: resources, projectRootOverride: explicit })).toBe(path.resolve(explicit))
  })

  it('maps packaged mutable state below userData without writing into runtime', () => {
    const paths = resolveWritableRuntimePaths(path.join('C:', 'Users', 'tester', 'AppData', 'Yuizaki'))

    expect(paths.settingsPath).toBe(path.join(paths.dataDir, 'settings.json'))
    expect(paths.audioCacheDir).toBe(path.join(paths.dataDir, 'audio_cache'))
    expect(paths.huggingfaceHome).toBe(path.join(paths.cacheDir, 'huggingface'))
    expect(paths.genieWorkspaceRoot).toBe(paths.dataDir)
    expect(paths.soulxServiceDir).toContain(path.join('AppData', 'Yuizaki', 'soulx-svc'))
    expect(paths.soulxServiceDir).not.toContain('resources')
  })
})
