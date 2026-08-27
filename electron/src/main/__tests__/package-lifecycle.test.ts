import { createHash } from 'node:crypto'
import { describe, expect, it } from 'vitest'
import { canonicalizePackageManifest, PackageLifecycle, type PackageArtifactStore, type PackageAssetManifest, type PackageManifest, type PackageState, type PackageStateStore } from '../package-lifecycle'

class FakeStore implements PackageArtifactStore {
  readonly installed = new Map<string, Buffer>()
  readonly removals: Array<{ id: string; version: string; preserve: boolean }> = []
  install(id: string, version: string, artifact: Buffer): void { this.installed.set(`${id}@${version}`, artifact) }
  remove(id: string, version: string, preserveUserData: boolean): void { this.removals.push({ id, version, preserve: preserveUserData }); this.installed.delete(`${id}@${version}`) }
  has(id: string, version: string): boolean { return this.installed.has(`${id}@${version}`) }
}

class FakeStateStore implements PackageStateStore {
  readonly states = new Map<string, PackageState>()
  load(id: string): PackageState | null { return this.states.get(id) ?? null }
  save(id: string, state: PackageState): void { this.states.set(id, { ...state, revokedVersions: [...state.revokedVersions] }) }
  remove(id: string): void { this.states.delete(id) }
}

class FailingStateStore extends FakeStateStore {
  override save(): void { throw new Error('state persistence failed') }
}

const manifest = (version: string, artifact: Buffer, capabilities: PackageManifest['capabilities'] = ['avatar']): PackageManifest => ({
  packageId: 'official.avatar.feibi', version, sha256: createHash('sha256').update(artifact).digest('hex'), signature: 'sig', keyId: 'official-2026', capabilities,
})

const assetManifest = (artifactSha256: string): PackageAssetManifest => ({
  schemaVersion: 1,
  displayName: 'Feibi companion pack',
  assets: [
    { kind: 'motion', path: 'motions/wave.motion3.json', sha256: artifactSha256 },
    { kind: 'voice', path: 'voices/default.wav', sha256: artifactSha256 },
    { kind: 'role', path: 'role/persona.json', sha256: artifactSha256 },
  ],
  license: {
    spdx: 'CC-BY-4.0',
    redistributable: true,
    attribution: 'Example creator',
  },
})

describe('PackageLifecycle', () => {
  it('requires a valid signature, checksum, runtime, and capability set', () => {
    const store = new FakeStore()
    const lifecycle = new PackageLifecycle(store, (bytes, signature, keyId) => bytes.length > 0 && signature === 'sig' && keyId === 'official-2026', '42.7.0', new Set(['avatar']))
    expect(lifecycle.install(manifest('1.0.0', Buffer.from('one')), Buffer.from('one')).operation).toBe('install')
    expect(() => lifecycle.install({ ...manifest('2.0.0', Buffer.from('two')), capabilities: ['voice'] }, Buffer.from('two'))).toThrow('capability')
    expect(() => lifecycle.install({ ...manifest('3.0.0', Buffer.from('three')), minRuntime: '43' }, Buffer.from('three'))).toThrow('too old')
  })

  it('validates and signs role, voice, and motion asset declarations deterministically', () => {
    const store = new FakeStore()
    const artifact = Buffer.from('asset-pack')
    const checksum = createHash('sha256').update(artifact).digest('hex')
    const declared = assetManifest(checksum)
    const packageManifest = {
      ...manifest('1.0.0', artifact, ['avatar', 'voice']),
      assetManifest: declared,
    }
    const reordered = {
      ...packageManifest,
      assetManifest: { ...declared, assets: [...declared.assets].reverse() },
    }

    expect(canonicalizePackageManifest(packageManifest)).toEqual(canonicalizePackageManifest(reordered))
    const lifecycle = new PackageLifecycle(store, () => true, '42.7.0', new Set(['avatar', 'voice']))
    expect(lifecycle.install(packageManifest, artifact).operation).toBe('install')
  })

  it('rejects unsafe asset paths and undeclared asset capabilities', () => {
    const artifact = Buffer.from('asset-pack')
    const checksum = createHash('sha256').update(artifact).digest('hex')
    const lifecycle = new PackageLifecycle(new FakeStore(), () => true, '42.7.0', new Set(['avatar', 'voice']))
    const base = assetManifest(checksum)

    expect(() => lifecycle.install({
      ...manifest('1.0.0', artifact, ['avatar', 'voice']),
      assetManifest: { ...base, assets: [{ ...base.assets[0]!, path: '../escape.motion3.json' }] },
    }, artifact)).toThrow('path is unsafe')
    expect(() => lifecycle.install({
      ...manifest('1.0.0', artifact, ['avatar']),
      assetManifest: base,
    }, artifact)).toThrow('capability is not declared')
  })

  it('updates, rolls back, and preserves state without touching user data', () => {
    const store = new FakeStore()
    const lifecycle = new PackageLifecycle(store, () => true, '42.7.0', new Set(['avatar']))
    lifecycle.install(manifest('1.0.0', Buffer.from('one')), Buffer.from('one'))
    lifecycle.install(manifest('2.0.0', Buffer.from('two')), Buffer.from('two'))
    expect(lifecycle.state('official.avatar.feibi').previousVersion).toBe('1.0.0')
    expect(lifecycle.rollback('official.avatar.feibi').version).toBe('1.0.0')
    const result = lifecycle.uninstall('official.avatar.feibi')
    expect(result.userDataPreserved).toBe(true)
    expect(store.removals).toHaveLength(2)
    expect(store.removals.every((removal) => removal.preserve)).toBe(true)
    expect(store.has('official.avatar.feibi', '1.0.0')).toBe(false)
    expect(store.has('official.avatar.feibi', '2.0.0')).toBe(false)
  })

  it('revokes an active version and blocks reinstall', () => {
    const store = new FakeStore()
    const lifecycle = new PackageLifecycle(store, () => true, '42.7.0', new Set(['avatar']))
    lifecycle.install(manifest('1.0.0', Buffer.from('one')), Buffer.from('one'))
    lifecycle.revoke('official.avatar.feibi', '1.0.0')
    expect(() => lifecycle.install(manifest('1.0.0', Buffer.from('one')), Buffer.from('one'))).toThrow('revoked')
    expect(lifecycle.state('official.avatar.feibi').activeVersion).toBeNull()
  })

  it('restores revocation and active state after lifecycle recreation', () => {
    const store = new FakeStore()
    const stateStore = new FakeStateStore()
    const first = new PackageLifecycle(store, () => true, '42.7.0', new Set(['avatar']), stateStore)
    first.install(manifest('1.0.0', Buffer.from('one')), Buffer.from('one'))
    first.revoke('official.avatar.feibi', '1.0.0')

    const recreated = new PackageLifecycle(store, () => true, '42.7.0', new Set(['avatar']), stateStore)
    expect(recreated.state('official.avatar.feibi').revokedVersions).toEqual(['1.0.0'])
    expect(() => recreated.install(manifest('1.0.0', Buffer.from('one')), Buffer.from('one'))).toThrow('revoked')
  })

  it('removes an artifact and preserves lifecycle state when health checks fail', () => {
    const store = new FakeStore()
    const stateStore = new FakeStateStore()
    const lifecycle = new PackageLifecycle(store, () => true, '42.7.0', new Set(['avatar']), stateStore, () => false)

    expect(() => lifecycle.install(manifest('1.0.0', Buffer.from('one')), Buffer.from('one'))).toThrow('health check')
    expect(store.has('official.avatar.feibi', '1.0.0')).toBe(false)
    expect(lifecycle.state('official.avatar.feibi').activeVersion).toBeNull()
    expect(stateStore.states.has('official.avatar.feibi')).toBe(false)
  })

  it('keeps the previous active version when an update health check fails', () => {
    const store = new FakeStore()
    let healthChecks = 0
    const lifecycle = new PackageLifecycle(
      store,
      () => true,
      '42.7.0',
      new Set(['avatar']),
      undefined,
      () => {
        healthChecks += 1
        return healthChecks === 1
      },
    )

    lifecycle.install(manifest('1.0.0', Buffer.from('one')), Buffer.from('one'))
    expect(() => lifecycle.install(manifest('2.0.0', Buffer.from('two')), Buffer.from('two'))).toThrow('health check')
    expect(lifecycle.state('official.avatar.feibi')).toEqual({
      activeVersion: '1.0.0',
      previousVersion: null,
      revokedVersions: [],
    })
    expect(store.has('official.avatar.feibi', '1.0.0')).toBe(true)
    expect(store.has('official.avatar.feibi', '2.0.0')).toBe(false)
  })

  it('cleans up a staged artifact when durable state persistence fails', () => {
    const store = new FakeStore()
    const lifecycle = new PackageLifecycle(store, () => true, '42.7.0', new Set(['avatar']), new FailingStateStore())

    expect(() => lifecycle.install(manifest('1.0.0', Buffer.from('one')), Buffer.from('one'))).toThrow('state persistence')
    expect(store.has('official.avatar.feibi', '1.0.0')).toBe(false)
    expect(lifecycle.state('official.avatar.feibi').activeVersion).toBeNull()
  })

  it('fails closed when restored state references a missing active artifact', () => {
    const store = new FakeStore()
    const stateStore = new FakeStateStore()
    stateStore.states.set('official.avatar.feibi', {
      activeVersion: '1.0.0',
      previousVersion: null,
      revokedVersions: [],
    })
    const lifecycle = new PackageLifecycle(store, () => true, '42.7.0', new Set(['avatar']), stateStore)

    expect(() => lifecycle.install(manifest('2.0.0', Buffer.from('two')), Buffer.from('two')))
      .toThrow('artifact is unavailable')
    expect(store.has('official.avatar.feibi', '2.0.0')).toBe(false)
  })

  it('fails closed before rollback when either restored reference is missing', () => {
    const store = new FakeStore()
    const stateStore = new FakeStateStore()
    stateStore.states.set('official.avatar.feibi', {
      activeVersion: '2.0.0',
      previousVersion: '1.0.0',
      revokedVersions: [],
    })
    store.installed.set('official.avatar.feibi@2.0.0', Buffer.from('two'))
    const lifecycle = new PackageLifecycle(store, () => true, '42.7.0', new Set(['avatar']), stateStore)

    expect(() => lifecycle.rollback('official.avatar.feibi')).toThrow('artifact is unavailable')
  })

  it('validates state loaded from an injected store at runtime', () => {
    const store = new FakeStore()
    const stateStore = new FakeStateStore()
    stateStore.states.set('official.avatar.feibi', {
      activeVersion: 42 as unknown as string,
      previousVersion: null,
      revokedVersions: [],
    })
    const lifecycle = new PackageLifecycle(store, () => true, '42.7.0', new Set(['avatar']), stateStore)

    expect(() => lifecycle.state('official.avatar.feibi')).toThrow('state is invalid')
  })

  it('reconciles restored artifact references without mutating lifecycle state', () => {
    const store = new FakeStore()
    const stateStore = new FakeStateStore()
    stateStore.states.set('official.avatar.feibi', {
      activeVersion: '2.0.0',
      previousVersion: '1.0.0',
      revokedVersions: [],
    })
    store.installed.set('official.avatar.feibi@2.0.0', Buffer.from('two'))
    const lifecycle = new PackageLifecycle(store, () => true, '42.7.0', new Set(['avatar']), stateStore)

    expect(lifecycle.reconcile('official.avatar.feibi')).toEqual({
      packageId: 'official.avatar.feibi',
      status: 'missing_artifact',
      state: { activeVersion: '2.0.0', previousVersion: '1.0.0', revokedVersions: [] },
      missingArtifacts: ['1.0.0'],
    })
    expect(lifecycle.state('official.avatar.feibi').activeVersion).toBe('2.0.0')
  })

  it('reports corrupt durable state during reconciliation instead of treating it as empty', () => {
    const store = new FakeStore()
    const stateStore = new FakeStateStore()
    stateStore.load = () => { throw new Error('package state file is corrupt') }
    stateStore.listPackageIds = () => ['official.avatar.feibi']
    const lifecycle = new PackageLifecycle(store, () => true, '42.7.0', new Set(['avatar']), stateStore)

    expect(lifecycle.reconcileAll()).toEqual([{
      packageId: 'official.avatar.feibi',
      status: 'state_invalid',
      state: null,
      missingArtifacts: [],
      error: 'package state file is corrupt',
    }])
  })
})
