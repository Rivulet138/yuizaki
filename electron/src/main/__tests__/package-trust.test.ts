import { generateKeyPairSync, sign } from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { canonicalizePackageManifest, type PackageManifest } from '../package-lifecycle'
import {
  canonicalizePackageKeyRotation,
  RotatingPackageKeyAuthority,
  TrustedPackageKeyAuthority,
} from '../package-trust'
import { JsonPackageKeyRotationStore } from '../package-trust-store'

const packageManifest = (): PackageManifest => ({
  packageId: 'official.avatar.feibi',
  version: '1.0.0',
  sha256: 'a'.repeat(64),
  signature: 'placeholder',
  keyId: 'official-2026',
  capabilities: ['avatar'],
})

describe('TrustedPackageKeyAuthority', () => {
  it('verifies an Ed25519 signature only for the trusted key id', () => {
    const { publicKey, privateKey } = generateKeyPairSync('ed25519')
    const authority = new TrustedPackageKeyAuthority([{
      keyId: 'official-2026',
      publicKeyPem: publicKey.export({ type: 'spki', format: 'pem' }).toString(),
    }])
    const manifest = packageManifest()
    const signature = sign(null, canonicalizePackageManifest(manifest), privateKey).toString('base64')

    expect(authority.verify(canonicalizePackageManifest(manifest), signature, 'official-2026')).toBe(true)
    expect(authority.verify(canonicalizePackageManifest(manifest), signature, 'unknown')).toBe(false)
    expect(authority.verify(canonicalizePackageManifest(manifest), 'not-base64', 'official-2026')).toBe(false)
  })

  it('applies only root-signed monotonic key rotations', () => {
    const root = generateKeyPairSync('ed25519')
    const initial = generateKeyPairSync('ed25519')
    const next = generateKeyPairSync('ed25519')
    const publicPem = (key: ReturnType<typeof generateKeyPairSync>['public']) => key.export({ type: 'spki', format: 'pem' }).toString()
    const authority = new RotatingPackageKeyAuthority(
      [{ keyId: 'root-2026', publicKeyPem: publicPem(root.publicKey) }],
      [{ keyId: 'package-2026-a', publicKeyPem: publicPem(initial.publicKey) }],
    )
    const envelope = {
      version: 1,
      keys: [{ keyId: 'package-2026-b', publicKeyPem: publicPem(next.publicKey) }],
      signerKeyId: 'root-2026',
    }
    const signed = {
      ...envelope,
      signature: sign(null, canonicalizePackageKeyRotation(envelope), root.privateKey).toString('base64'),
    }

    authority.applyRotation(signed)
    expect(authority.version).toBe(1)
    expect(authority.hasKey('package-2026-a')).toBe(false)
    expect(authority.hasKey('package-2026-b')).toBe(true)
    expect(() => authority.applyRotation({ ...signed, version: 1 })).toThrow('must advance')
    expect(() => authority.applyRotation({ ...signed, version: 2, signature: 'invalid' })).toThrow('signature rejected')
    expect(authority.version).toBe(1)
  })

  it('persists a verified rotation and restores it after recreation', () => {
    const root = generateKeyPairSync('ed25519')
    const initial = generateKeyPairSync('ed25519')
    const next = generateKeyPairSync('ed25519')
    const publicPem = (key: ReturnType<typeof generateKeyPairSync>['public']) => key.export({ type: 'spki', format: 'pem' }).toString()
    const stateRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-package-keys-'))
    try {
      const store = new JsonPackageKeyRotationStore(stateRoot)
      const authority = new RotatingPackageKeyAuthority(
        [{ keyId: 'root-2026', publicKeyPem: publicPem(root.publicKey) }],
        [{ keyId: 'package-2026-a', publicKeyPem: publicPem(initial.publicKey) }],
        0,
        store,
      )
      const envelope = {
        version: 1,
        keys: [{ keyId: 'package-2026-b', publicKeyPem: publicPem(next.publicKey) }],
        signerKeyId: 'root-2026',
      }
      const signed = {
        ...envelope,
        signature: sign(null, canonicalizePackageKeyRotation(envelope), root.privateKey).toString('base64'),
      }
      authority.applyRotation(signed)

      const restored = new RotatingPackageKeyAuthority(
        [{ keyId: 'root-2026', publicKeyPem: publicPem(root.publicKey) }],
        [{ keyId: 'package-2026-a', publicKeyPem: publicPem(initial.publicKey) }],
        0,
        store,
      )
      expect(restored.version).toBe(1)
      expect(restored.hasKey('package-2026-b')).toBe(true)
      expect(restored.hasKey('package-2026-a')).toBe(false)
    } finally {
      fs.rmSync(stateRoot, { recursive: true, force: true })
    }
  })

  it('fails closed when persisted rotation state is corrupt', () => {
    const stateRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-package-keys-corrupt-'))
    try {
      fs.writeFileSync(path.join(stateRoot, 'package-key-rotation.json'), '{"version":0}', 'utf8')
      const store = new JsonPackageKeyRotationStore(stateRoot)
      expect(() => store.load()).toThrow('corrupt')
    } finally {
      fs.rmSync(stateRoot, { recursive: true, force: true })
    }
  })

  it('keeps the active key set when durable rotation save fails', () => {
    const root = generateKeyPairSync('ed25519')
    const initial = generateKeyPairSync('ed25519')
    const next = generateKeyPairSync('ed25519')
    const publicPem = (key: ReturnType<typeof generateKeyPairSync>['public']) => key.export({ type: 'spki', format: 'pem' }).toString()
    const authority = new RotatingPackageKeyAuthority(
      [{ keyId: 'root-2026', publicKeyPem: publicPem(root.publicKey) }],
      [{ keyId: 'package-2026-a', publicKeyPem: publicPem(initial.publicKey) }],
      0,
      { load: () => null, save: () => { throw new Error('disk unavailable') } },
    )
    const envelope = {
      version: 1,
      keys: [{ keyId: 'package-2026-b', publicKeyPem: publicPem(next.publicKey) }],
      signerKeyId: 'root-2026',
    }
    const signed = {
      ...envelope,
      signature: sign(null, canonicalizePackageKeyRotation(envelope), root.privateKey).toString('base64'),
    }
    expect(() => authority.applyRotation(signed)).toThrow('disk unavailable')
    expect(authority.version).toBe(0)
    expect(authority.hasKey('package-2026-a')).toBe(true)
    expect(authority.hasKey('package-2026-b')).toBe(false)
  })
})
