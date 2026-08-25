import fs from 'node:fs'
import path from 'node:path'
import type { PackageState, PackageStateStore } from './package-lifecycle'

type PersistedPackageStates = Record<string, PackageState>

const cloneState = (state: PackageState): PackageState => ({
  activeVersion: state.activeVersion,
  previousVersion: state.previousVersion,
  revokedVersions: [...state.revokedVersions],
})

const isPackageState = (value: unknown): value is PackageState => {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Record<string, unknown>
  return (candidate['activeVersion'] === null || typeof candidate['activeVersion'] === 'string')
    && (candidate['previousVersion'] === null || typeof candidate['previousVersion'] === 'string')
    && Array.isArray(candidate['revokedVersions'])
    && candidate['revokedVersions'].every((version) => typeof version === 'string')
}

const parseStates = (value: unknown): PersistedPackageStates => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('package state file is invalid')
  const states: PersistedPackageStates = {}
  for (const [packageId, state] of Object.entries(value)) {
    if (!packageId.trim() || !isPackageState(state)) throw new Error('package state file is invalid')
    states[packageId] = cloneState(state)
  }
  return states
}

export class JsonPackageStateStore implements PackageStateStore {
  private readonly filePath: string

  constructor(private readonly rootDir: string, fileName = 'package-state.json') {
    this.filePath = path.join(rootDir, fileName)
  }

  load(packageId: string): PackageState | null {
    const states = this.read()
    const state = states[packageId]
    return state ? cloneState(state) : null
  }

  listPackageIds(): readonly string[] {
    return Object.keys(this.read()).sort()
  }

  save(packageId: string, state: PackageState): void {
    if (!packageId.trim() || !isPackageState(state)) throw new Error('package state is invalid')
    const states = this.read()
    states[packageId] = cloneState(state)
    this.write(states)
  }

  remove(packageId: string): void {
    const states = this.read()
    if (!(packageId in states)) return
    delete states[packageId]
    this.write(states)
  }

  private read(): PersistedPackageStates {
    if (!fs.existsSync(this.filePath)) return {}
    try {
      return parseStates(JSON.parse(fs.readFileSync(this.filePath, 'utf8')))
    } catch (error) {
      throw Object.assign(new Error('package state file is corrupt'), { cause: error })
    }
  }

  private write(states: PersistedPackageStates): void {
    fs.mkdirSync(this.rootDir, { recursive: true })
    const temporaryPath = `${this.filePath}.tmp-${process.pid}-${Date.now()}`
    const payload = `${JSON.stringify(states, null, 2)}\n`
    let descriptor: number | undefined
    try {
      descriptor = fs.openSync(temporaryPath, 'w')
      fs.writeFileSync(descriptor, payload, 'utf8')
      fs.fsyncSync(descriptor)
      fs.closeSync(descriptor)
      descriptor = undefined
      fs.renameSync(temporaryPath, this.filePath)
    } finally {
      if (descriptor !== undefined) fs.closeSync(descriptor)
      if (fs.existsSync(temporaryPath)) fs.rmSync(temporaryPath, { force: true })
    }
  }
}

export const createDefaultPackageStateStore = (userDataDir: string): JsonPackageStateStore => (
  new JsonPackageStateStore(path.join(userDataDir, 'packages'))
)
