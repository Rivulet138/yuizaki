import { createServer } from 'node:http'
import { mkdtempSync, mkdirSync, readFileSync, realpathSync, writeFileSync, rmSync, rmdirSync, symlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import type { AddressInfo } from 'node:net'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { handleSystemRoutes } from '../http/routes/system-routes'
import { restoreSqliteDatabase, snapshotSqliteDatabase } from '../backup-snapshot'

vi.mock('../backup-snapshot', async importOriginal => ({
  ...await importOriginal<typeof import('../backup-snapshot')>(),
  restoreSqliteDatabase: vi.fn(async (_python: string, source: string, destination: string) => { writeFileSync(destination, readFileSync(source)) }),
  snapshotSqliteDatabase: vi.fn(async (_python: string, _source: string, destination: string) => {
    mkdirSync(path.dirname(destination), { recursive: true }); writeFileSync(destination, 'coherent-snapshot')
  }),
}))

vi.mock('electron', () => ({ app: { getPath: () => `${process.env['YUIZAKI_PROJECT_ROOT']}/user-data` }, safeStorage: {} }))

describe('F01 restore plan binding through the HTTP route', () => {
  let root: string
  let backupDir: string
  let source: string
  let target: string
  let manifestPath: string
  let origin: string
  let server: ReturnType<typeof createServer>
  beforeEach(async () => {
    root = mkdtempSync(path.join(tmpdir(), 'yuizaki-restore-plan-'))
    const originalFetch = globalThis.fetch
    vi.stubGlobal('fetch', (input: string | URL | Request, init?: RequestInit) => {
      if (String(input).endsWith('/api/system/storage/backup-sources')) return Promise.resolve(new Response(JSON.stringify({
        source: 'running_backend', database: path.join(root, 'python', 'data', 'chat.db'),
        memory: path.join(root, 'python', 'data', 'memory.db'), memory_persistence: 'disk',
        settings: path.join(root, 'python', 'config', 'settings.json'), data_dir: path.join(root, 'python', 'data'),
        audio_cache: path.join(root, 'python', 'audio_cache'),
      })))
      return originalFetch(input, init)
    })
    vi.stubEnv('YUIZAKI_PROJECT_ROOT', root)
    vi.stubEnv('YUIZAKI_ELECTRON_ROOT', path.join(root, 'electron'))
    backupDir = path.join(root, 'backups', 'fixture')
    mkdirSync(backupDir, { recursive: true })
    target = path.join(root, 'python', 'data', 'chat.db')
    mkdirSync(path.dirname(target), { recursive: true })
    writeFileSync(target, 'live-content')
    source = path.join(backupDir, 'chat.db')
    writeFileSync(source, 'snapshot-content')
    manifestPath = path.join(backupDir, 'manifest.json')
    writeFileSync(manifestPath, JSON.stringify({ targets: [{ path: target, exists: true, type: 'file', backupPath: 'chat.db' }] }))
    server = createServer((req, res) => {
      void handleSystemRoutes(req, res, req.method!, new URL(req.url!, 'http://127.0.0.1'), {} as never).catch(error => {
        res.writeHead(500); res.end(String(error))
      })
    })
    await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
    origin = `http://127.0.0.1:${(server.address() as AddressInfo).port}`
  })
  afterEach(async () => {
    await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()))
    vi.unstubAllGlobals()
    vi.clearAllMocks()
    vi.unstubAllEnvs()
    // Verify the exact temporary fixture root before recursive cleanup.
    if (path.dirname(root) !== path.resolve(tmpdir()) || !path.basename(root).startsWith('yuizaki-restore-plan-')) throw new Error('Invalid fixture root')
    rmSync(root, { recursive: true, force: true })
  })
  const post = async (body: unknown) => {
    const response = await fetch(`${origin}/api/system/backup/restore`, { method: 'POST', body: JSON.stringify(body) })
    return { status: response.status, data: await response.json() }
  }
  const preview = () => post({ backupDir, dryRun: true })

  it('snapshots SQLite through the online helper rather than copying the main file', async () => {
    const response = await fetch(`${origin}/api/system/backup/create`, { method: 'POST' })
    expect(response.status).toBe(200)
    const result = await response.json()
    const database = result.manifest.targets[0]
    expect(database.snapshotMethod).toBe('sqlite_online_backup')
    expect(snapshotSqliteDatabase).toHaveBeenCalledWith(path.join(root, 'python'), target, path.join(result.backupDir, database.backupPath))
    expect(readFileSync(path.join(result.backupDir, database.backupPath), 'utf8')).toBe('coherent-snapshot')
    expect(readFileSync(target, 'utf8')).toBe('live-content')
  })

  it('uses actual custom paths for targets, snapshot and restore allowlist', async () => {
    const customChat = path.join(root, 'custom', 'conversation.sqlite')
    const customMemory = path.join(root, 'custom', 'facts.sqlite')
    mkdirSync(path.dirname(customChat), { recursive: true })
    writeFileSync(customChat, 'custom-chat')
    writeFileSync(customMemory, 'custom-memory')
    const originalFetch = globalThis.fetch
    vi.stubGlobal('fetch', (input: string | URL | Request, init?: RequestInit) => {
      if (String(input).endsWith('/api/system/storage/backup-sources')) return Promise.resolve(new Response(JSON.stringify({
        source: 'running_backend', database: customChat, memory: customMemory, memory_persistence: 'disk',
        settings: path.join(root, 'custom', 'settings.json'), data_dir: path.join(root, 'custom'),
        audio_cache: path.join(root, 'custom', 'audio'),
      })))
      return originalFetch(input, init)
    })
    const response = await fetch(`${origin}/api/system/backup/create`, { method: 'POST' })
    const result = await response.json()
    expect(result.manifest.targets.slice(0, 2).map((item: { path: string }) => item.path)).toEqual([customChat, customMemory])
    expect(result.manifest.targets.slice(0, 2).every((item: { snapshotMethod: string }) => item.snapshotMethod === 'sqlite_online_backup')).toBe(true)
    writeFileSync(manifestPath, JSON.stringify({ targets: [{ path: customChat, exists: true, type: 'file', backupPath: 'chat.db' }] }))
    expect((await preview()).status).toBe(200)
    writeFileSync(manifestPath, JSON.stringify({ targets: [{ path: target, exists: true, type: 'file', backupPath: 'chat.db' }] }))
    expect((await preview()).status).toBe(403)
  })

  it('restores tagged SQLite snapshots through the database helper', async () => {
    const created = await fetch(`${origin}/api/system/backup/create`, { method: 'POST' })
    const snapshot = await created.json()
    const preflight = await post({ backupDir: snapshot.backupDir, dryRun: true })
    expect(preflight.status).toBe(200)
    const restored = await post({ backupDir: snapshot.backupDir, dryRun: false, planId: preflight.data.planId })
    expect(restored.status).toBe(200)
    expect(restoreSqliteDatabase).toHaveBeenCalledTimes(1)
    expect(readFileSync(target, 'utf8')).toBe('coherent-snapshot')
  })

  it('fails closed when the running backend rejects source discovery', async () => {
    const originalFetch = globalThis.fetch
    vi.stubGlobal('fetch', (input: string | URL | Request, init?: RequestInit) => {
      if (String(input).endsWith('/api/system/storage/backup-sources')) return Promise.resolve(new Response('{}', { status: 401 }))
      return originalFetch(input, init)
    })
    const response = await fetch(`${origin}/api/system/backup/create`, { method: 'POST' })
    expect(response.status).toBe(500)
    expect(snapshotSqliteDatabase).not.toHaveBeenCalled()
  })

  it('does not claim success if a SQLite snapshot fails', async () => {
    vi.mocked(snapshotSqliteDatabase).mockRejectedValueOnce(new Error('sqlite_snapshot_failed'))
    const response = await fetch(`${origin}/api/system/backup/create`, { method: 'POST' })
    expect(response.status).toBe(500)
    expect(await response.text()).toContain('sqlite_snapshot_failed')
    expect(readFileSync(target, 'utf8')).toBe('live-content')
  })

  it('serializes apply while a SQLite helper is in flight', async () => {
    const planned = await preview()
    let entered!: () => void
    let release!: () => void
    const started = new Promise<void>(resolve => { entered = resolve })
    const gate = new Promise<void>(resolve => { release = resolve })
    vi.mocked(restoreSqliteDatabase).mockImplementationOnce(async (_python, snapshot, destination) => {
      entered(); await gate; writeFileSync(destination, readFileSync(snapshot))
    })
    const applying = post({ backupDir, dryRun: false, planId: planned.data.planId })
    await started
    const second = await post({ backupDir, dryRun: false, planId: planned.data.planId })
    expect(second.status).toBe(409)
    expect(second.data.error).toBe('restore_in_progress')
    release()
    expect((await applying).status).toBe(200)
    expect(restoreSqliteDatabase).toHaveBeenCalledTimes(1)
  })

  it.each([true, false])('rejects a later snapshot changing or appearing while SQLite restore awaits (existed: %s)', async existed => {
    const settingsTarget = path.join(root, 'python', 'config', 'settings.json')
    const settingsSource = path.join(backupDir, 'settings.json')
    mkdirSync(path.dirname(settingsTarget), { recursive: true })
    writeFileSync(settingsTarget, 'live-settings')
    if (existed) writeFileSync(settingsSource, 'snapshot-settings')
    writeFileSync(manifestPath, JSON.stringify({ targets: [
      { path: target, exists: true, type: 'file', backupPath: 'chat.db' },
      { path: settingsTarget, exists: true, type: 'file', backupPath: 'settings.json' },
    ] }))
    const planned = await preview()
    let entered!: () => void
    let release!: () => void
    const started = new Promise<void>(resolve => { entered = resolve })
    const gate = new Promise<void>(resolve => { release = resolve })
    vi.mocked(restoreSqliteDatabase).mockImplementationOnce(async (_python, snapshot, destination) => {
      entered()
      await gate
      writeFileSync(destination, readFileSync(snapshot))
    })
    const applying = post({ backupDir, dryRun: false, planId: planned.data.planId })
    await started
    writeFileSync(settingsSource, 'changed-after-confirmation')
    release()
    const result = await applying
    expect(result.status).toBe(409)
    expect(result.data.error).toBe('restore_plan_changed')
    expect(result.data.partial).toBe(true)
    expect(result.data.restorePlan[0].restored).toBe(true)
    expect(readFileSync(settingsTarget, 'utf8')).toBe('live-settings')
  })

  it('rejects a directory source containing the backup destination', async () => {
    const originalFetch = globalThis.fetch
    vi.stubGlobal('fetch', async (input: string | URL | Request, init?: RequestInit) => {
      const response = await originalFetch(input, init)
      if (!String(input).endsWith('/api/system/storage/backup-sources')) return response
      return new Response(JSON.stringify({ ...await response.json(), audio_cache: root }))
    })
    const response = await fetch(`${origin}/api/system/backup/create`, { method: 'POST' })
    expect(response.status).toBe(500)
    expect(await response.text()).toContain('backup_directory_overlaps_source')
  })

  it('returns a stable sha256 plan for normalized backup paths and applies the same planId', async () => {
    const first = await preview()
    expect(first.status).toBe(200)
    expect(first.data.planId).toMatch(/^[a-f0-9]{64}$/)
    const second = await post({ backupDir: path.join(backupDir, '.'), dryRun: true })
    expect(second.data.planId).toBe(first.data.planId)
    expect(readFileSync(target, 'utf8')).toBe('live-content')
    const applied = await post({ backupDir, dryRun: false, planId: first.data.planId })
    expect(applied.status).toBe(200)
    expect(applied.data.planId).toBe(first.data.planId)
    expect(applied.data.restorePlan[0].restored).toBe(true)
    expect(restoreSqliteDatabase).toHaveBeenCalledWith(path.join(root, 'python'), realpathSync.native(source), target)
    expect(readFileSync(target, 'utf8')).toBe('snapshot-content')
  })

  it.each([undefined, 'wrong-plan'])('rejects a missing or mismatched plan without writing: %s', async planId => {
    const response = await post({ backupDir, dryRun: false, planId })
    expect(response.status).toBe(409)
    expect(readFileSync(target, 'utf8')).toBe('live-content')
  })

  it.each(['manifest', 'source', 'target', 'backupDir'])('invalidates preview when %s changes before apply', async changed => {
    const first = await preview()
    if (changed === 'manifest') writeFileSync(manifestPath, `${readFileSync(manifestPath, 'utf8')}\n`)
    if (changed === 'source') writeFileSync(source, 'changed-snapshot-longer')
    if (changed === 'target') rmSync(target)
    if (changed === 'backupDir') {
      backupDir = path.join(root, 'backups', 'other')
      mkdirSync(backupDir)
      writeFileSync(path.join(backupDir, 'manifest.json'), readFileSync(manifestPath))
      writeFileSync(path.join(backupDir, 'chat.db'), 'snapshot-content')
    }
    const applied = await post({ backupDir, dryRun: false, planId: first.data.planId })
    expect(applied.status).toBe(409)
    if (changed !== 'target') expect(readFileSync(target, 'utf8')).toBe('live-content')
  })

  it('detects nested directory source changes', async () => {
    const audioDir = path.join(backupDir, 'audio')
    mkdirSync(audioDir)
    writeFileSync(path.join(audioDir, 'voice.wav'), 'original')
    const audioTarget = path.join(root, 'python', 'audio_cache')
    writeFileSync(manifestPath, JSON.stringify({ targets: [{ path: audioTarget, exists: true, type: 'directory', backupPath: 'audio' }] }))
    const first = await preview()
    writeFileSync(path.join(audioDir, 'voice.wav'), 'changed-source')
    expect((await post({ backupDir, dryRun: false, planId: first.data.planId })).status).toBe(409)
  })

  it('retains unmanaged-target and source-escape protections', async () => {
    writeFileSync(manifestPath, JSON.stringify({ targets: [{ path: path.join(root, 'unmanaged'), exists: true, type: 'file', backupPath: 'chat.db' }] }))
    expect((await preview()).status).toBe(403)
    writeFileSync(manifestPath, JSON.stringify({ targets: [{ path: target, exists: true, type: 'file', backupPath: '../../outside' }] }))
    expect((await preview()).status).toBe(403)
    expect(readFileSync(target, 'utf8')).toBe('live-content')
  })

  it('rejects a linked target parent during preview before any writes', async () => {
    // The existing managed target parent is replaced by a junction in this fixture.
    const originalDir = path.dirname(target)
    const elsewhere = path.join(root, 'actual-data')
    mkdirSync(elsewhere)
    rmSync(target)
    rmdirSync(originalDir)
    symlinkSync(elsewhere, originalDir, 'junction')
    expect((await preview()).status).toBe(403)
  })
})
