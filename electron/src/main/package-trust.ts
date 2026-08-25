import { createPublicKey, verify as verifySignature } from 'node:crypto'
import type { KeyObject } from 'node:crypto'

export interface TrustedPackageKey {
  keyId: string
  publicKeyPem: string
}

export interface PackageKeyRotationEnvelope {
  version: number
  keys: readonly TrustedPackageKey[]
  signerKeyId: string
  signature: string
}

export interface PackageKeyRotationStore {
  load(): PackageKeyRotationEnvelope | null
  save(envelope: PackageKeyRotationEnvelope): void
}

const decodeSignature = (signature: string): Buffer | null => {
  const normalized = signature.trim()
  if (!normalized || !/^[A-Za-z0-9+/]+={0,2}$/.test(normalized) || normalized.length % 4 !== 0) return null
  try {
    const decoded = Buffer.from(normalized, 'base64')
    return decoded.length > 0 ? decoded : null
  } catch {
    return null
  }
}

const canonicalizeKeys = (keys: readonly TrustedPackageKey[]): Buffer => Buffer.from(JSON.stringify(
  [...keys].sort((left, right) => left.keyId.localeCompare(right.keyId)),
), 'utf8')

export const canonicalizePackageKeyRotation = (envelope: Omit<PackageKeyRotationEnvelope, 'signature'>): Buffer => Buffer.from(JSON.stringify({
  version: envelope.version,
  keys: JSON.parse(canonicalizeKeys(envelope.keys).toString('utf8')),
  signerKeyId: envelope.signerKeyId,
}), 'utf8')

const buildKeyMap = (keys: readonly TrustedPackageKey[]): Map<string, KeyObject> => {
  const result = new Map<string, KeyObject>()
  for (const key of keys) {
    if (!key.keyId.trim() || !key.publicKeyPem.trim() || result.has(key.keyId)) {
      throw new Error('trusted package key is invalid')
    }
    result.set(key.keyId, createPublicKey(key.publicKeyPem))
  }
  return result
}

const verifyWithKeys = (keys: ReadonlyMap<string, KeyObject>, canonicalManifest: Buffer, signature: string, keyId: string): boolean => {
  const key = keys.get(keyId)
  const decoded = decodeSignature(signature)
  if (!key || !decoded) return false
  try {
    return verifySignature(null, canonicalManifest, key, decoded)
  } catch {
    return false
  }
}

/**
 * Verifies package manifests against an explicitly supplied Ed25519 key set.
 * The key set is intentionally injected by a higher-level trusted source.
 */
export class TrustedPackageKeyAuthority {
  private readonly keys = new Map<string, KeyObject>()

  constructor(keys: readonly TrustedPackageKey[]) {
    for (const [keyId, key] of buildKeyMap(keys)) this.keys.set(keyId, key)
  }

  verify(canonicalManifest: Buffer, signature: string, keyId: string): boolean {
    return verifyWithKeys(this.keys, canonicalManifest, signature, keyId)
  }

  hasKey(keyId: string): boolean {
    return this.keys.has(keyId)
  }
}

/**
 * Rotates package verification keys only through a root-signed, monotonic
 * envelope. Applying an invalid envelope leaves the active set untouched.
 */
export class RotatingPackageKeyAuthority {
  private readonly root: TrustedPackageKeyAuthority
  private active: Map<string, KeyObject>
  private rotationVersion: number

  constructor(
    rootKeys: readonly TrustedPackageKey[],
    initialKeys: readonly TrustedPackageKey[],
    initialVersion = 0,
    private readonly rotationStore?: PackageKeyRotationStore,
  ) {
    if (!Number.isSafeInteger(initialVersion) || initialVersion < 0) throw new Error('package key rotation version is invalid')
    this.root = new TrustedPackageKeyAuthority(rootKeys)
    this.active = buildKeyMap(initialKeys)
    this.rotationVersion = initialVersion
    const persisted = rotationStore?.load()
    if (persisted) this.applyRotationInternal(persisted, false)
  }

  verify(canonicalManifest: Buffer, signature: string, keyId: string): boolean {
    return verifyWithKeys(this.active, canonicalManifest, signature, keyId)
  }

  applyRotation(envelope: PackageKeyRotationEnvelope): void {
    this.applyRotationInternal(envelope, true)
  }

  private applyRotationInternal(envelope: PackageKeyRotationEnvelope, persist: boolean): void {
    if (!Number.isSafeInteger(envelope.version) || envelope.version <= this.rotationVersion) {
      throw new Error('package key rotation version must advance')
    }
    if (!envelope.signerKeyId.trim() || !this.root.verify(
      canonicalizePackageKeyRotation({
        version: envelope.version,
        keys: envelope.keys,
        signerKeyId: envelope.signerKeyId,
      }),
      envelope.signature,
      envelope.signerKeyId,
    )) {
      throw new Error('package key rotation signature rejected')
    }
    const next = buildKeyMap(envelope.keys)
    if (next.size === 0) throw new Error('package key rotation cannot remove every key')
    if (persist) this.rotationStore?.save(envelope)
    this.active = next
    this.rotationVersion = envelope.version
  }

  get version(): number {
    return this.rotationVersion
  }

  hasKey(keyId: string): boolean {
    return this.active.has(keyId)
  }
}

export const createFailClosedPackageKeyAuthority = (): TrustedPackageKeyAuthority => (
  new TrustedPackageKeyAuthority([])
)
