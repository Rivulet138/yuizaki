import fs from 'node:fs'
import path from 'node:path'
import type { PackageKeyRotationEnvelope, PackageKeyRotationStore, TrustedPackageKey } from './package-trust'

const isTrustedKey = (value: unknown): value is TrustedPackageKey => {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Record<string, unknown>
  return typeof candidate['keyId'] === 'string'
    && candidate['keyId'].trim().length > 0
    && typeof candidate['publicKeyPem'] === 'string'
    && candidate['publicKeyPem'].trim().length > 0
}

const parseEnvelope = (value: unknown): PackageKeyRotationEnvelope => {
  if (!value || typeof value !== 'object') throw new Error('package key rotation state is invalid')
  const candidate = value as Record<string, unknown>
  if (!Number.isSafeInteger(candidate['version']) || (candidate['version'] as number) < 1
    || typeof candidate['signerKeyId'] !== 'string' || !(candidate['signerKeyId'] as string).trim()
    || typeof candidate['signature'] !== 'string' || !(candidate['signature'] as string).trim()
    || !Array.isArray(candidate['keys']) || candidate['keys'].length === 0
    || !candidate['keys'].every(isTrustedKey)) {
    throw new Error('package key rotation state is invalid')
  }
  const keys = candidate['keys'] as TrustedPackageKey[]
  if (new Set(keys.map((key) => key.keyId)).size !== keys.length) {
    throw new Error('package key rotation state contains duplicate keys')
  }
  return {
    version: candidate['version'] as number,
    keys: keys.map((key) => ({ keyId: key.keyId, publicKeyPem: key.publicKeyPem })),
    signerKeyId: candidate['signerKeyId'] as string,
    signature: candidate['signature'] as string,
  }
}

/** Durable, fail-closed storage for the last root-signed key rotation. */
export class JsonPackageKeyRotationStore implements PackageKeyRotationStore {
  private readonly filePath: string

  constructor(private readonly rootDir: string, fileName = 'package-key-rotation.json') {
    this.filePath = path.join(rootDir, fileName)
  }

  load(): PackageKeyRotationEnvelope | null {
    if (!fs.existsSync(this.filePath)) return null
    try {
      return parseEnvelope(JSON.parse(fs.readFileSync(this.filePath, 'utf8')))
    } catch (error) {
      throw Object.assign(new Error('package key rotation state is corrupt'), { cause: error })
    }
  }

  save(envelope: PackageKeyRotationEnvelope): void {
    const safe = parseEnvelope(envelope)
    fs.mkdirSync(this.rootDir, { recursive: true })
    const temporaryPath = `${this.filePath}.tmp-${process.pid}-${Date.now()}`
    let descriptor: number | undefined
    try {
      descriptor = fs.openSync(temporaryPath, 'wx')
      fs.writeFileSync(descriptor, `${JSON.stringify(safe, null, 2)}\n`, 'utf8')
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
