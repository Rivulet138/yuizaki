import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { LocalPackageArtifactStore } from '../package-artifact-store'

describe('LocalPackageArtifactStore', () => {
  it('writes and replaces an artifact atomically within the root', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-package-artifacts-'))
    try {
      const store = new LocalPackageArtifactStore(root)
      store.install('official.avatar.feibi', '1.0.0', Buffer.from('one'))
      store.install('official.avatar.feibi', '1.0.0', Buffer.from('two'))
      expect(store.has('official.avatar.feibi', '1.0.0')).toBe(true)
      expect(fs.readFileSync(path.join(root, 'official.avatar.feibi', '1.0.0', 'artifact.bin'), 'utf8')).toBe('two')
      expect(fs.readdirSync(path.join(root, 'official.avatar.feibi', '1.0.0'))).toEqual(['artifact.bin'])
    } finally {
      fs.rmSync(root, { recursive: true, force: true })
    }
  })

  it('rejects traversal segments and symlinked package directories', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-package-artifacts-path-'))
    const outside = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-package-artifacts-outside-'))
    try {
      const store = new LocalPackageArtifactStore(root)
      expect(() => store.install('../escape', '1.0.0', Buffer.from('x'))).toThrow('invalid')
      fs.symlinkSync(outside, path.join(root, 'linked-package'), 'junction')
      expect(() => store.install('linked-package', '1.0.0', Buffer.from('x'))).toThrow()
      expect(fs.existsSync(path.join(outside, '1.0.0', 'artifact.bin'))).toBe(false)
    } finally {
      fs.rmSync(root, { recursive: true, force: true })
      fs.rmSync(outside, { recursive: true, force: true })
    }
  })
})
