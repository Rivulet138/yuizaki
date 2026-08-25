import fs from 'node:fs'
import path from 'node:path'
import type { PackageArtifactStore } from './package-lifecycle'

const isSafeSegment = (value: string): boolean => (
  value.trim().length > 0
  && value !== '.'
  && value !== '..'
  && !value.includes('/')
  && !value.includes('\\')
  && !value.includes('\0')
)

const isPathInside = (baseDir: string, targetPath: string): boolean => {
  const relative = path.relative(baseDir, targetPath)
  return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative))
}

/** Local artifact persistence only; trust, download, and health policy stay above this adapter. */
export class LocalPackageArtifactStore implements PackageArtifactStore {
  private readonly rootDir: string

  constructor(rootDir: string) {
    this.rootDir = path.resolve(rootDir)
    fs.mkdirSync(this.rootDir, { recursive: true })
    this.assertRealInside(this.rootDir)
  }

  install(packageId: string, version: string, artifact: Buffer): void {
    const artifactPath = this.resolveArtifactPath(packageId, version, true)
    if (!artifactPath) throw new Error('package artifact path is unavailable')
    const temporaryPath = `${artifactPath}.tmp-${process.pid}-${Date.now()}-${Math.random().toString(16).slice(2)}`
    let descriptor: number | undefined
    try {
      descriptor = fs.openSync(temporaryPath, 'wx', 0o600)
      fs.writeFileSync(descriptor, artifact)
      fs.fsyncSync(descriptor)
      fs.closeSync(descriptor)
      descriptor = undefined
      fs.renameSync(temporaryPath, artifactPath)
    } finally {
      if (descriptor !== undefined) fs.closeSync(descriptor)
      if (fs.existsSync(temporaryPath)) fs.rmSync(temporaryPath, { force: true })
    }
  }

  remove(packageId: string, version: string, _preserveUserData: boolean): void {
    const versionDir = this.resolveVersionDir(packageId, version, false)
    if (!versionDir || !fs.existsSync(versionDir)) return
    fs.rmSync(versionDir, { recursive: true, force: true })
  }

  has(packageId: string, version: string): boolean {
    const artifactPath = this.resolveArtifactPath(packageId, version, false)
    return artifactPath !== null && fs.lstatSync(artifactPath, { throwIfNoEntry: false })?.isFile() === true
  }

  private resolveArtifactPath(packageId: string, version: string, create: boolean): string | null {
    const versionDir = this.resolveVersionDir(packageId, version, create)
    return versionDir ? path.join(versionDir, 'artifact.bin') : null
  }

  private resolveVersionDir(packageId: string, version: string, create: boolean): string | null {
    if (!isSafeSegment(packageId) || !isSafeSegment(version)) throw new Error('package artifact path is invalid')
    const packageDir = path.join(this.rootDir, packageId)
    const versionDir = path.join(packageDir, version)
    if (!isPathInside(this.rootDir, versionDir)) throw new Error('package artifact path escapes root')
    if (create) fs.mkdirSync(versionDir, { recursive: true, mode: 0o700 })
    if (!fs.existsSync(versionDir)) return null
    this.assertRealInside(packageDir)
    this.assertRealInside(versionDir)
    if (fs.lstatSync(versionDir).isSymbolicLink()) throw new Error('package artifact path must not be a symlink')
    return versionDir
  }

  private assertRealInside(targetPath: string): void {
    const rootRealPath = fs.realpathSync.native(this.rootDir)
    const targetRealPath = fs.realpathSync.native(targetPath)
    if (!isPathInside(rootRealPath, targetRealPath)) throw new Error('package artifact path escapes root')
  }
}

export const createDefaultPackageArtifactStore = (userDataDir: string): LocalPackageArtifactStore => (
  new LocalPackageArtifactStore(path.join(userDataDir, 'packages', 'artifacts'))
)
