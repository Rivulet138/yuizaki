import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { JsonPackageStateStore } from '../package-state-store'

describe('JsonPackageStateStore', () => {
  it('persists state atomically and restores it after recreation', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-package-state-'))
    try {
      const state = { activeVersion: '2.0.0', previousVersion: '1.0.0', revokedVersions: ['0.9.0'] }
      new JsonPackageStateStore(root).save('official.avatar.feibi', state)
      const restored = new JsonPackageStateStore(root).load('official.avatar.feibi')
      expect(restored).toEqual(state)
      expect(fs.readFileSync(path.join(root, 'package-state.json'), 'utf8')).toContain('official.avatar.feibi')
    } finally {
      fs.rmSync(root, { recursive: true, force: true })
    }
  })

  it('fails closed on corrupt state instead of treating it as empty', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-package-state-corrupt-'))
    try {
      fs.writeFileSync(path.join(root, 'package-state.json'), '{"official.avatar.feibi":{"activeVersion":42}}', 'utf8')
      expect(() => new JsonPackageStateStore(root).load('official.avatar.feibi')).toThrow('corrupt')
    } finally {
      fs.rmSync(root, { recursive: true, force: true })
    }
  })

  it('removes package state without affecting sibling packages', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-package-state-remove-'))
    try {
      const store = new JsonPackageStateStore(root)
      store.save('official.avatar.feibi', { activeVersion: '1.0.0', previousVersion: null, revokedVersions: [] })
      store.save('official.skill.clock', { activeVersion: '1.0.0', previousVersion: null, revokedVersions: [] })
      store.remove('official.avatar.feibi')
      expect(store.load('official.avatar.feibi')).toBeNull()
      expect(store.load('official.skill.clock')?.activeVersion).toBe('1.0.0')
    } finally {
      fs.rmSync(root, { recursive: true, force: true })
    }
  })

  it('lists persisted package ids in stable order for startup reconciliation', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-package-state-list-'))
    try {
      const store = new JsonPackageStateStore(root)
      store.save('official.skill.clock', { activeVersion: '1.0.0', previousVersion: null, revokedVersions: [] })
      store.save('official.avatar.feibi', { activeVersion: '1.0.0', previousVersion: null, revokedVersions: [] })
      expect(store.listPackageIds()).toEqual(['official.avatar.feibi', 'official.skill.clock'])
    } finally {
      fs.rmSync(root, { recursive: true, force: true })
    }
  })
})
