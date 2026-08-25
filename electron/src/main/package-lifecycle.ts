import { createHash } from 'node:crypto'

export type PackageCapability = 'voice' | 'avatar' | 'skill' | 'workflow' | 'memory-sync'

export interface PackageManifest {
  packageId: string
  version: string
  sha256: string
  signature: string
  keyId: string
  capabilities: PackageCapability[]
  minRuntime?: string
  maxRuntime?: string
}

export interface PackageArtifactStore {
  install(packageId: string, version: string, artifact: Buffer): void
  remove(packageId: string, version: string, preserveUserData: boolean): void
  has(packageId: string, version: string): boolean
}

export interface PackageStateStore {
  load(packageId: string): PackageState | null
  save(packageId: string, state: PackageState): void
  remove(packageId: string): void
  listPackageIds?(): readonly string[]
}

export type PackageSignatureVerifier = (canonicalManifest: Buffer, signature: string, keyId: string) => boolean
export type PackageHealthChecker = (packageId: string, version: string, artifact: Buffer) => boolean

export interface PackageState {
  activeVersion: string | null
  previousVersion: string | null
  revokedVersions: string[]
}

export interface PackageOperationResult {
  packageId: string
  version: string | null
  operation: 'install' | 'update' | 'rollback' | 'revoke' | 'uninstall'
  capabilities: PackageCapability[]
  userDataPreserved: boolean
}

export type PackageReconciliationStatus = 'ready' | 'missing_artifact' | 'state_invalid'

export interface PackageReconciliation {
  packageId: string | null
  status: PackageReconciliationStatus
  state: PackageState | null
  missingArtifacts: string[]
  error?: string
}

const RUNTIME_VERSION = /\d+/g

const versionKey = (value: string): number[] => {
  const parts = value.match(RUNTIME_VERSION)?.map(Number) ?? []
  if (!parts.length) throw new Error('invalid package runtime version')
  return parts.slice(0, 4)
}

const compareVersions = (left: string, right: string): number => {
  const a = versionKey(left)
  const b = versionKey(right)
  for (let index = 0; index < Math.max(a.length, b.length); index += 1) {
    const difference = (a[index] ?? 0) - (b[index] ?? 0)
    if (difference) return difference
  }
  return 0
}

export const canonicalizePackageManifest = (manifest: PackageManifest): Buffer => Buffer.from(JSON.stringify({
  packageId: manifest.packageId,
  version: manifest.version,
  sha256: manifest.sha256,
  keyId: manifest.keyId,
  capabilities: [...manifest.capabilities].sort(),
  minRuntime: manifest.minRuntime ?? null,
  maxRuntime: manifest.maxRuntime ?? null,
}), 'utf8')

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

export class PackageLifecycle {
  private readonly states = new Map<string, PackageState>()

  constructor(
    private readonly store: PackageArtifactStore,
    private readonly verifySignature: PackageSignatureVerifier,
    private readonly runtimeVersion: string,
    private readonly allowedCapabilities: ReadonlySet<PackageCapability>,
    private readonly stateStore?: PackageStateStore,
    private readonly healthCheck: PackageHealthChecker = () => true,
  ) {}

  state(packageId: string): PackageState {
    const state = this.states.get(packageId) ?? this.stateStore?.load(packageId) ?? undefined
    if (state !== undefined && !isPackageState(state)) throw new Error('package state is invalid')
    if (state && !this.states.has(packageId)) this.states.set(packageId, cloneState(state))
    return state ? cloneState(state) : { activeVersion: null, previousVersion: null, revokedVersions: [] }
  }

  reconcile(packageId: string): PackageReconciliation {
    try {
      const state = this.state(packageId)
      const referenced = [state.activeVersion, state.previousVersion]
        .filter((version): version is string => version !== null)
      const missingArtifacts = referenced.filter((version) => !this.store.has(packageId, version))
      return {
        packageId,
        status: missingArtifacts.length > 0 ? 'missing_artifact' : 'ready',
        state,
        missingArtifacts,
      }
    } catch (error) {
      return {
        packageId,
        status: 'state_invalid',
        state: null,
        missingArtifacts: [],
        error: error instanceof Error ? error.message : String(error),
      }
    }
  }

  reconcileAll(): readonly PackageReconciliation[] {
    const listPackageIds = this.stateStore?.listPackageIds
    if (!listPackageIds) return []
    try {
      return listPackageIds.call(this.stateStore).map((packageId) => this.reconcile(packageId))
    } catch (error) {
      return [{
        packageId: null,
        status: 'state_invalid',
        state: null,
        missingArtifacts: [],
        error: error instanceof Error ? error.message : String(error),
      }]
    }
  }

  private setState(packageId: string, state: PackageState): void {
    if (!isPackageState(state)) throw new Error('package state is invalid')
    const next = cloneState(state)
    const previous = this.states.get(packageId)
    try {
      this.stateStore?.save(packageId, next)
      this.states.set(packageId, next)
    } catch (error) {
      if (previous) this.states.set(packageId, cloneState(previous))
      else this.states.delete(packageId)
      throw error
    }
  }

  install(manifest: PackageManifest, artifact: Buffer): PackageOperationResult {
    this.validate(manifest, artifact)
    const current = this.state(manifest.packageId)
    this.assertReferencedArtifactsAvailable(manifest.packageId, current)
    if (current.revokedVersions.includes(manifest.version)) throw new Error('package version is revoked')
    if (current.activeVersion && compareVersions(manifest.version, current.activeVersion) <= 0) throw new Error('package version must advance')
    this.store.install(manifest.packageId, manifest.version, artifact)
    const healthy = (() => {
      try {
        return this.healthCheck(manifest.packageId, manifest.version, artifact)
      } catch {
        return false
      }
    })()
    if (!healthy) {
      this.store.remove(manifest.packageId, manifest.version, true)
      throw new Error('package health check failed')
    }
    try {
      this.setState(manifest.packageId, {
        activeVersion: manifest.version,
        previousVersion: current.activeVersion,
        revokedVersions: current.revokedVersions,
      })
    } catch (error) {
      try {
        this.store.remove(manifest.packageId, manifest.version, true)
      } catch {
        // The state store remains authoritative; an orphan is inert until reconciled.
      }
      throw error
    }
    return this.result(manifest, current.activeVersion ? 'update' : 'install', false)
  }

  rollback(packageId: string): PackageOperationResult {
    const current = this.state(packageId)
    this.assertReferencedArtifactsAvailable(packageId, current)
    if (!current.activeVersion || !current.previousVersion) throw new Error('no rollback version is available')
    if (current.revokedVersions.includes(current.previousVersion)) throw new Error('rollback version is revoked')
    if (!this.store.has(packageId, current.previousVersion)) throw new Error('rollback artifact is unavailable')
    this.setState(packageId, {
      ...cloneState(current),
      activeVersion: current.previousVersion,
      previousVersion: current.activeVersion,
    })
    return { packageId, version: current.previousVersion, operation: 'rollback', capabilities: [], userDataPreserved: false }
  }

  revoke(packageId: string, version: string): PackageOperationResult {
    const current = this.state(packageId)
    const revokedVersions = [...new Set([...current.revokedVersions, version])]
    if (current.activeVersion === version) this.store.remove(packageId, version, true)
    this.setState(packageId, {
      ...cloneState(current),
      activeVersion: current.activeVersion === version ? null : current.activeVersion,
      previousVersion: current.activeVersion === version ? null : current.previousVersion,
      revokedVersions,
    })
    return { packageId, version, operation: 'revoke', capabilities: [], userDataPreserved: true }
  }

  uninstall(packageId: string, preserveUserData = true): PackageOperationResult {
    const current = this.state(packageId)
    for (const version of new Set([current.activeVersion, current.previousVersion])) {
      if (version) this.store.remove(packageId, version, preserveUserData)
    }
    this.states.delete(packageId)
    this.stateStore?.remove(packageId)
    return { packageId, version: current.activeVersion, operation: 'uninstall', capabilities: [], userDataPreserved: preserveUserData }
  }

  private validate(manifest: PackageManifest, artifact: Buffer): void {
    if (!manifest.packageId.trim() || !manifest.version.trim() || !manifest.signature.trim() || !manifest.keyId.trim()) throw new Error('signed package identity is required')
    versionKey(manifest.version)
    if (manifest.capabilities.some((capability) => !this.allowedCapabilities.has(capability))) throw new Error('package capability is not allowed')
    if (manifest.minRuntime && compareVersions(this.runtimeVersion, manifest.minRuntime) < 0) throw new Error('package runtime is too old')
    if (manifest.maxRuntime && compareVersions(this.runtimeVersion, manifest.maxRuntime) > 0) throw new Error('package runtime is too new')
    const checksum = createHash('sha256').update(artifact).digest('hex')
    if (checksum !== manifest.sha256.toLowerCase()) throw new Error('package checksum mismatch')
    if (!this.verifySignature(canonicalizePackageManifest(manifest), manifest.signature, manifest.keyId)) throw new Error('package signature rejected')
  }

  private assertReferencedArtifactsAvailable(packageId: string, state: PackageState): void {
    const missing = [state.activeVersion, state.previousVersion]
      .filter((version): version is string => version !== null)
      .filter((version) => !this.store.has(packageId, version))
    if (missing.length > 0) throw new Error(`package artifact is unavailable: ${missing.join(', ')}`)
  }

  private result(manifest: PackageManifest, operation: PackageOperationResult['operation'], userDataPreserved: boolean): PackageOperationResult {
    return { packageId: manifest.packageId, version: manifest.version, operation, capabilities: [...manifest.capabilities], userDataPreserved }
  }
}
