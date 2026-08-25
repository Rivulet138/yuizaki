import fs from 'node:fs'
import path from 'node:path'
import { createHash } from 'node:crypto'
import type { PackageHealthChecker } from './package-lifecycle'

export type PackageEvidenceKind = 'local_contract' | 'release_runner' | 'real_device'
export type PackageEvidencePlatform = 'windows' | 'linux' | 'macos' | 'unknown'

export interface PackageReleaseCheck {
  name: string
  status: 'passed' | 'failed'
}

export interface PackageReleaseEvidenceManifest {
  schemaVersion: 1
  packageId: string
  version: string
  artifactSha256: string
  evidenceKind: PackageEvidenceKind
  platform: PackageEvidencePlatform
  runtimeVersion: string
  checks: readonly PackageReleaseCheck[]
}

export interface PackageReleaseAttestation {
  schemaVersion: 1
  publisherIdentity: string
  signerKeyId: string
  signature: string
}

export interface PackageReleaseEvidenceEnvelope {
  manifest: unknown
  attestation: unknown
}

export interface PackageReleaseHealthCheckResult {
  passed: boolean
  failures: readonly string[]
}

export type PackageReleaseEvidenceResolver = (
  packageId: string,
  version: string,
) => unknown | null

export type PackageReleaseAttestationVerifier = (
  canonicalEvidence: Buffer,
  attestation: PackageReleaseAttestation,
) => boolean

const SHA256 = /^[a-f0-9]{64}$/i
const VERSION = /^\d+(?:\.\d+){0,3}$/
const IDENTIFIER = /^[A-Za-z0-9._-]+$/
const SIGNATURE = /^[A-Za-z0-9+/]+={0,2}$/
const DEFAULT_MAX_EVIDENCE_BYTES = 256 * 1024

const isPathInside = (baseDir: string, targetPath: string): boolean => {
  const relative = path.relative(baseDir, targetPath)
  return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative))
}

const isRecord = (value: unknown): value is Record<string, unknown> => (
  value !== null && typeof value === 'object' && !Array.isArray(value)
)

const hasOnlyKeys = (value: Record<string, unknown>, allowed: readonly string[]): boolean => {
  const expected = new Set(allowed)
  return Object.keys(value).every((key) => expected.has(key))
}

const isEvidenceKind = (value: unknown): value is PackageEvidenceKind => (
  value === 'local_contract' || value === 'release_runner' || value === 'real_device'
)

const isPlatform = (value: unknown): value is PackageEvidencePlatform => (
  value === 'windows' || value === 'linux' || value === 'macos' || value === 'unknown'
)

/** Runtime validation keeps a hand-edited evidence file from becoming a release gate. */
export const parsePackageReleaseEvidence = (value: unknown): PackageReleaseEvidenceManifest => {
  if (!isRecord(value) || !hasOnlyKeys(value, [
    'schemaVersion', 'packageId', 'version', 'artifactSha256', 'evidenceKind',
    'platform', 'runtimeVersion', 'checks',
  ])) throw new Error('package release evidence is invalid')
  if (value['schemaVersion'] !== 1 || typeof value['packageId'] !== 'string'
    || !IDENTIFIER.test(value['packageId']) || typeof value['version'] !== 'string'
    || !VERSION.test(value['version']) || typeof value['artifactSha256'] !== 'string'
    || !SHA256.test(value['artifactSha256']) || !isEvidenceKind(value['evidenceKind'])
    || !isPlatform(value['platform']) || typeof value['runtimeVersion'] !== 'string'
    || !VERSION.test(value['runtimeVersion']) || !Array.isArray(value['checks'])
    || value['checks'].length === 0) {
    throw new Error('package release evidence is invalid')
  }

  const names = new Set<string>()
  const checks: PackageReleaseCheck[] = []
  for (const check of value['checks']) {
    if (!isRecord(check) || !hasOnlyKeys(check, ['name', 'status'])
      || typeof check['name'] !== 'string' || !IDENTIFIER.test(check['name'])
      || (check['status'] !== 'passed' && check['status'] !== 'failed')
      || names.has(check['name'])) throw new Error('package release evidence is invalid')
    names.add(check['name'])
    checks.push({ name: check['name'], status: check['status'] })
  }

  return {
    schemaVersion: 1,
    packageId: value['packageId'],
    version: value['version'],
    artifactSha256: value['artifactSha256'].toLowerCase(),
    evidenceKind: value['evidenceKind'],
    platform: value['platform'],
    runtimeVersion: value['runtimeVersion'],
    checks,
  }
}

const parsePackageReleaseAttestation = (value: unknown): PackageReleaseAttestation => {
  if (!isRecord(value) || !hasOnlyKeys(value, ['schemaVersion', 'publisherIdentity', 'signerKeyId', 'signature'])
    || value['schemaVersion'] !== 1 || typeof value['publisherIdentity'] !== 'string'
    || !IDENTIFIER.test(value['publisherIdentity']) || typeof value['signerKeyId'] !== 'string'
    || !IDENTIFIER.test(value['signerKeyId']) || typeof value['signature'] !== 'string'
    || !SIGNATURE.test(value['signature']) || value['signature'].length % 4 !== 0) {
    throw new Error('package release attestation is invalid')
  }
  return {
    schemaVersion: 1,
    publisherIdentity: value['publisherIdentity'],
    signerKeyId: value['signerKeyId'],
    signature: value['signature'],
  }
}

export const parsePackageReleaseEvidenceEnvelope = (value: unknown): {
  manifest: PackageReleaseEvidenceManifest
  attestation: PackageReleaseAttestation
} => {
  if (!isRecord(value) || !hasOnlyKeys(value, ['manifest', 'attestation'])) {
    throw new Error('package release evidence envelope is invalid')
  }
  return {
    manifest: parsePackageReleaseEvidence(value['manifest']),
    attestation: parsePackageReleaseAttestation(value['attestation']),
  }
}

export const canonicalizePackageReleaseAttestation = (
  manifest: PackageReleaseEvidenceManifest,
  attestation: Omit<PackageReleaseAttestation, 'signature'>,
): Buffer => Buffer.from(JSON.stringify({
  manifest: {
    schemaVersion: manifest.schemaVersion,
    packageId: manifest.packageId,
    version: manifest.version,
    artifactSha256: manifest.artifactSha256,
    evidenceKind: manifest.evidenceKind,
    platform: manifest.platform,
    runtimeVersion: manifest.runtimeVersion,
    checks: [...manifest.checks].sort((left, right) => left.name.localeCompare(right.name)),
  },
  attestation: {
    schemaVersion: attestation.schemaVersion,
    publisherIdentity: attestation.publisherIdentity,
    signerKeyId: attestation.signerKeyId,
  },
}), 'utf8')

/**
 * Read-only release evidence adapter for CI/release-runner output.
 *
 * The directory is intentionally separate from installed artifacts. A missing,
 * corrupt, symlinked, or out-of-root file resolves to `null` and therefore
 * fails the health checker; this class never promotes evidence or installs a
 * package.
 */
export class LocalPackageReleaseEvidenceStore {
  private readonly rootDir: string
  private readonly maxEvidenceBytes: number

  constructor(rootDir: string, maxEvidenceBytes = DEFAULT_MAX_EVIDENCE_BYTES) {
    if (!Number.isInteger(maxEvidenceBytes) || maxEvidenceBytes < 1) {
      throw new Error('package release evidence size limit is invalid')
    }
    this.rootDir = path.resolve(rootDir)
    this.maxEvidenceBytes = maxEvidenceBytes
  }

  resolve(packageId: string, version: string): unknown | null {
    const evidencePath = this.resolveEvidencePath(packageId, version)
    if (!evidencePath) return null
    try {
      return JSON.parse(fs.readFileSync(evidencePath, 'utf8')) as unknown
    } catch {
      return null
    }
  }

  asResolver(): PackageReleaseEvidenceResolver {
    return (packageId, version) => this.resolve(packageId, version)
  }

  private resolveEvidencePath(packageId: string, version: string): string | null {
    if (!IDENTIFIER.test(packageId) || !VERSION.test(version)) return null
    try {
      const rootRealPath = fs.realpathSync.native(this.rootDir)
      const packageDir = path.join(rootRealPath, packageId)
      const versionDir = path.join(packageDir, version)
      if (!isPathInside(rootRealPath, versionDir)) return null
      const packageStat = fs.lstatSync(packageDir, { throwIfNoEntry: false })
      const versionStat = fs.lstatSync(versionDir, { throwIfNoEntry: false })
      if (!packageStat?.isDirectory() || packageStat.isSymbolicLink()
        || !versionStat?.isDirectory() || versionStat.isSymbolicLink()) return null
      const evidencePath = path.join(versionDir, 'evidence.json')
      const evidenceStat = fs.lstatSync(evidencePath, { throwIfNoEntry: false })
      if (!evidenceStat?.isFile() || evidenceStat.isSymbolicLink()) return null
      if (evidenceStat.size > this.maxEvidenceBytes) return null
      const evidenceRealPath = fs.realpathSync.native(evidencePath)
      return isPathInside(rootRealPath, evidenceRealPath) ? evidencePath : null
    } catch {
      return null
    }
  }
}

export class PackageReleaseHealthCheckRunner {
  private readonly requiredChecks: ReadonlySet<string>
  private readonly acceptedEvidenceKinds: ReadonlySet<PackageEvidenceKind>

  constructor(
    requiredChecks: Iterable<string> = ['artifact-present', 'runtime-startup'],
    acceptedEvidenceKinds: Iterable<PackageEvidenceKind> = ['local_contract', 'release_runner'],
  ) {
    this.requiredChecks = new Set(requiredChecks)
    this.acceptedEvidenceKinds = new Set(acceptedEvidenceKinds)
    if (this.requiredChecks.size === 0) throw new Error('package health checks are required')
    if (this.acceptedEvidenceKinds.size === 0) throw new Error('package evidence kinds are required')
  }

  evaluate(
    packageId: string,
    version: string,
    artifact: Buffer,
    evidence: unknown,
  ): PackageReleaseHealthCheckResult {
    const failures: string[] = []
    let manifest: PackageReleaseEvidenceManifest
    try {
      manifest = parsePackageReleaseEvidence(evidence)
    } catch {
      return { passed: false, failures: ['evidence-invalid'] }
    }
    if (!this.acceptedEvidenceKinds.has(manifest.evidenceKind)) failures.push('evidence-kind-not-authorized')
    if (manifest.packageId !== packageId || manifest.version !== version) failures.push('identity-mismatch')
    const digest = createHash('sha256').update(artifact).digest('hex')
    if (digest !== manifest.artifactSha256) failures.push('artifact-digest-mismatch')
    const checks = new Map(manifest.checks.map((check) => [check.name, check.status]))
    for (const required of this.requiredChecks) {
      if (checks.get(required) !== 'passed') failures.push(`check:${required}`)
    }
    return { passed: failures.length === 0, failures }
  }

  createHealthChecker(resolveEvidence: PackageReleaseEvidenceResolver): PackageHealthChecker {
    return (packageId, version, artifact) => (
      this.evaluate(packageId, version, artifact, resolveEvidence(packageId, version)).passed
    )
  }

  evaluateAttested(
    packageId: string,
    version: string,
    artifact: Buffer,
    envelope: unknown,
    verifier: PackageReleaseAttestationVerifier,
  ): PackageReleaseHealthCheckResult {
    let parsed: { manifest: PackageReleaseEvidenceManifest; attestation: PackageReleaseAttestation }
    try {
      parsed = parsePackageReleaseEvidenceEnvelope(envelope)
    } catch {
      return { passed: false, failures: ['attestation-invalid'] }
    }
    const result = this.evaluate(packageId, version, artifact, parsed.manifest)
    if (!result.passed) return result
    let verified: boolean
    try {
      verified = verifier(
        canonicalizePackageReleaseAttestation(parsed.manifest, {
          schemaVersion: parsed.attestation.schemaVersion,
          publisherIdentity: parsed.attestation.publisherIdentity,
          signerKeyId: parsed.attestation.signerKeyId,
        }),
        parsed.attestation,
      )
    } catch {
      verified = false
    }
    return verified
      ? result
      : { passed: false, failures: [...result.failures, 'attestation-rejected'] }
  }

  createAttestedHealthChecker(
    resolveEvidence: PackageReleaseEvidenceResolver,
    verifier: PackageReleaseAttestationVerifier,
  ): PackageHealthChecker {
    return (packageId, version, artifact) => (
      this.evaluateAttested(packageId, version, artifact, resolveEvidence(packageId, version), verifier).passed
    )
  }
}
