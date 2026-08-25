import { createHash } from 'node:crypto'
import { describe, expect, it } from 'vitest'
import {
  HttpPackageArtifactSource,
  HttpPackageKeyRotationSource,
  PackageDistributionAdapter,
  type PackageArtifactSource,
} from '../package-distribution'
import { PackageLifecycle, type PackageArtifactStore, type PackageManifest } from '../package-lifecycle'

class Store implements PackageArtifactStore {
  readonly artifacts = new Map<string, Buffer>()
  install(id: string, version: string, artifact: Buffer): void { this.artifacts.set(`${id}@${version}`, artifact) }
  remove(id: string, version: string): void { this.artifacts.delete(`${id}@${version}`) }
  has(id: string, version: string): boolean { return this.artifacts.has(`${id}@${version}`) }
}

const arrayBufferFor = (value: string): ArrayBuffer => Uint8Array.from(Buffer.from(value)).buffer

const manifestFor = (artifact: Buffer): PackageManifest => ({
  packageId: 'official.skill.clock',
  version: '1.0.0',
  sha256: createHash('sha256').update(artifact).digest('hex'),
  signature: 'sig',
  keyId: 'official-2026',
  capabilities: ['skill'],
})

describe('PackageDistributionAdapter', () => {
  it('downloads through a source and delegates trust/health to PackageLifecycle', async () => {
    const artifact = Buffer.from('signed-artifact')
    const source: PackageArtifactSource = { fetch: async () => artifact }
    const store = new Store()
    const lifecycle = new PackageLifecycle(store, () => true, '42.7.0', new Set(['skill']))
    const adapter = new PackageDistributionAdapter(lifecycle, source)

    const result = await adapter.installFromSource(manifestFor(artifact), new AbortController().signal)

    expect(result.operation).toBe('install')
    expect(store.has('official.skill.clock', '1.0.0')).toBe(true)
  })

  it('requires HTTPS and an explicit origin allowlist', async () => {
    const response = {
      ok: true,
      status: 200,
      headers: { get: () => null },
      arrayBuffer: async () => Uint8Array.from([1, 2]).buffer,
    }
    const allowed = new HttpPackageArtifactSource(
      () => 'http://packages.example.test/artifact',
      new Set(['https://packages.example.test']),
      10,
      async () => response,
    )
    await expect(allowed.fetch(manifestFor(Buffer.from([1, 2])), new AbortController().signal)).rejects.toThrow('origin')
  })

  it('rejects declared and actual artifacts above the size limit', async () => {
    const oversizedResponse = {
      ok: true,
      status: 200,
      headers: { get: () => '11' },
      arrayBuffer: async () => new ArrayBuffer(11),
    }
    const source = new HttpPackageArtifactSource(
      () => 'https://packages.example.test/artifact',
      new Set(['https://packages.example.test']),
      10,
      async () => oversizedResponse,
    )
    await expect(source.fetch(manifestFor(Buffer.from('x')), new AbortController().signal)).rejects.toThrow('size limit')
  })

  it('honors cancellation before a network request', async () => {
    const controller = new AbortController()
    controller.abort()
    const source = new HttpPackageArtifactSource(
      () => 'https://packages.example.test/artifact',
      new Set(['https://packages.example.test']),
      10,
      async () => { throw new Error('request must not start') },
    )
    await expect(source.fetch(manifestFor(Buffer.from('x')), controller.signal)).rejects.toThrow()
  })

  it('fetches bounded HTTPS key rotation metadata and leaves signature application to the authority', async () => {
    const envelope = {
      version: 2,
      keys: [{ keyId: 'package-2026-b', publicKeyPem: '-----BEGIN PUBLIC KEY-----\nkey\n-----END PUBLIC KEY-----' }],
      signerKeyId: 'root-2026',
      signature: 'c2lnbmF0dXJl',
    }
    const source = new HttpPackageKeyRotationSource(
      () => 'https://packages.example.test/keys.json',
      new Set(['https://packages.example.test']),
      1024,
      async () => ({
        ok: true,
        status: 200,
        headers: { get: () => null },
        arrayBuffer: async () => arrayBufferFor(JSON.stringify(envelope)),
      }),
    )
    await expect(source.fetch(new AbortController().signal)).resolves.toEqual(envelope)
  })

  it('rejects invalid key rotation metadata and non-HTTPS origins', async () => {
    const response = {
      ok: true,
      status: 200,
      headers: { get: () => null },
      arrayBuffer: async () => arrayBufferFor('{"version":0}'),
    }
    const invalid = new HttpPackageKeyRotationSource(
      () => 'https://packages.example.test/keys.json',
      new Set(['https://packages.example.test']),
      1024,
      async () => response,
    )
    await expect(invalid.fetch(new AbortController().signal)).rejects.toThrow('metadata')
    const insecure = new HttpPackageKeyRotationSource(
      () => 'http://packages.example.test/keys.json',
      new Set(['https://packages.example.test']),
      1024,
      async () => response,
    )
    await expect(insecure.fetch(new AbortController().signal)).rejects.toThrow('origin')
  })

  it('applies fetched key rotation only after the request completes', async () => {
    const envelope = {
      version: 2,
      keys: [{ keyId: 'package-2026-b', publicKeyPem: 'pem' }],
      signerKeyId: 'root-2026',
      signature: 'c2lnbmF0dXJl',
    }
    const source: PackageArtifactSource = { fetch: async () => Buffer.from('unused') }
    const lifecycle = new PackageLifecycle(new Store(), () => true, '42.7.0', new Set(['skill']))
    const adapter = new PackageDistributionAdapter(lifecycle, source)
    const applied: unknown[] = []
    const keySource = { fetch: async () => envelope }
    await expect(adapter.refreshKeyRotation(keySource, { applyRotation: (value) => applied.push(value) }, new AbortController().signal)).resolves.toBe(2)
    expect(applied).toEqual([envelope])
  })
})
