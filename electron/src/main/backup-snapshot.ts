import { execFile } from 'node:child_process'
import path from 'node:path'
import { promisify } from 'node:util'
import { resolvePythonRuntime } from './python-runtime'

const executeFile = promisify(execFile)

export type BackupSources = {
  source: 'running_backend' | 'configured_offline'
  database: string
  memory: string
  memory_persistence: 'disk' | 'memory_only'
  settings: string
  data_dir: string
  audio_cache: string
}

export const parseBackupSources = (value: unknown): BackupSources => {
  if (!value || typeof value !== 'object') throw new Error('invalid_backup_sources')
  const source = value as BackupSources
  for (const field of ['database', 'memory', 'settings', 'data_dir', 'audio_cache'] as const) {
    if (typeof source[field] !== 'string' || !path.isAbsolute(source[field])) throw new Error(`invalid_backup_source_${field}`)
  }
  if (source.source !== 'running_backend' && source.source !== 'configured_offline') throw new Error('invalid_backup_source_origin')
  if (source.memory_persistence !== 'disk' && source.memory_persistence !== 'memory_only') throw new Error('invalid_memory_persistence')
  return source
}

const runHelper = async (pythonDir: string, args: string[], environment?: NodeJS.ProcessEnv): Promise<unknown> => {
  const runtime = resolvePythonRuntime(pythonDir)
  const { stdout } = await executeFile(runtime.executable, [path.join(pythonDir, 'modules', 'system', 'backup_snapshot.py'), ...args], {
    cwd: pythonDir,
    env: { ...process.env, ...environment, PYTHONIOENCODING: 'utf-8' },
    windowsHide: true,
    timeout: 60_000,
    maxBuffer: 1024 * 1024,
  })
  return JSON.parse(stdout.trim()) as unknown
}

export const resolveConfiguredBackupSources = async (pythonDir: string, environment?: NodeJS.ProcessEnv): Promise<BackupSources> =>
  parseBackupSources(await runHelper(pythonDir, ['sources'], environment))

export const snapshotSqliteDatabase = async (pythonDir: string, source: string, destination: string): Promise<void> => {
  const result = await runHelper(pythonDir, ['snapshot', source, destination]) as { ok?: boolean }
  if (!result.ok) throw new Error('sqlite_snapshot_failed')
}

// Restore through SQLite as well: copying over a live main file leaves stale WAL pages.
export const restoreSqliteDatabase = async (pythonDir: string, source: string, destination: string): Promise<void> => {
  const result = await runHelper(pythonDir, ['restore', source, destination]) as { ok?: boolean }
  if (!result.ok) throw new Error('sqlite_restore_failed')
}
