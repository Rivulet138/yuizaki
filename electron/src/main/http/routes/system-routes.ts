import fs from 'node:fs'
import path from 'node:path'
import { app } from 'electron'
import { getRuntimeExceptions } from '../../runtime-diagnostics'
import {
  cancelModelResources,
  getModelResourceStatus,
  getModelResourceProgress,
  importSoulxReferenceAudio,
  prepareEmbeddingModel,
  prepareGenieTts,
  prepareModelResources,
  prepareSherpaSenseVoice,
  prepareSherpaStreamingZipformer,
  prepareSoulxModels,
  removeModelResources,
} from '../../resource-manager'
import type { ManagedModelResourceId } from '../../../shared/resource-manager'
import type { HttpRouteHandler } from '../types'
import { resolvePythonRuntime } from '../../python-runtime'
import { parseRequestBody, sendJson } from '../utils'
import { resolvePythonApiOrigin } from '../python-origin'
import type { SkillCatalogItem, SkillCatalogSnapshot } from '../../../shared/capability'

const PYTHON_PROXY_TIMEOUT_MS = 12000

const resolveElectronRoot = (): string => {
  const { YUIZAKI_ELECTRON_ROOT: explicitRoot } = process.env
  if (explicitRoot) {
    return path.resolve(explicitRoot)
  }

  const cwd = process.cwd()
  if (fs.existsSync(path.join(cwd, 'package.json')) && fs.existsSync(path.join(cwd, 'src/main'))) {
    return cwd
  }

  const electronChild = path.join(cwd, 'electron')
  if (fs.existsSync(path.join(electronChild, 'package.json'))) {
    return electronChild
  }

  return cwd
}

const resolveProjectRoot = (): string => path.resolve(resolveElectronRoot(), '..')

const buildProxyHeaders = (ctx: Parameters<HttpRouteHandler>[4], bodyIncluded: boolean, traceId: string | null) => {
  const headers: { Connection: string; 'Content-Type'?: string; 'x-trace-id'?: string; 'x-yuizaki-backend-token'?: string } = {
    Connection: 'close',
  }
  if (ctx.backendApiToken) {
    headers['x-yuizaki-backend-token'] = ctx.backendApiToken
  }
  if (bodyIncluded) {
    headers['Content-Type'] = 'application/json'
  }
  if (traceId) {
    headers['x-trace-id'] = traceId
  }
  return headers
}

const proxyPythonJson = async (
  req: Parameters<HttpRouteHandler>[0],
  res: Parameters<HttpRouteHandler>[1],
  method: string,
  url: URL,
  ctx: Parameters<HttpRouteHandler>[4],
) => {
  const body = method === 'GET' || method === 'DELETE' ? undefined : await parseRequestBody<unknown>(req)
  const abortController = new AbortController()
  const timeout = setTimeout(() => abortController.abort(), PYTHON_PROXY_TIMEOUT_MS)
  const init: RequestInit = {
    method,
    headers: buildProxyHeaders(ctx, body !== undefined, String(req.headers['x-trace-id'] || '').trim() || null),
    signal: abortController.signal,
  }
  if (body !== undefined) {
    init.body = JSON.stringify(body)
  }
  let response: Response
  try {
    response = await fetch(`${resolvePythonApiOrigin()}${url.pathname}${url.search}`, init)
  } catch (error) {
    const aborted = abortController.signal.aborted
    sendJson(res, aborted ? 504 : 502, {
      error: aborted ? 'Python backend request timed out' : 'Python backend request failed',
      path: url.pathname,
      detail: error instanceof Error ? error.message : String(error),
    })
    return
  } finally {
    clearTimeout(timeout)
  }

  const text = await response.text()
  let payload: unknown = {}
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = { raw: text }
    }
  }
  if (response.ok) {
    if (method === 'PATCH' && url.pathname === '/api/settings/' && body !== undefined) {
      ctx.providerCredentialStore.captureSettingsPayload(body)
    } else if (method === 'POST' && url.pathname === '/api/settings/import' && body !== undefined) {
      ctx.providerCredentialStore.captureSettingsPayload(body)
    } else if (method === 'POST' && url.pathname.startsWith('/api/settings/') && body !== undefined) {
      const fieldPath = decodeURIComponent(url.pathname.slice('/api/settings/'.length))
      ctx.providerCredentialStore.captureSettingValue(fieldPath, body)
    } else if (method === 'DELETE' && url.pathname.startsWith('/api/settings/')) {
      const fieldPath = decodeURIComponent(url.pathname.slice('/api/settings/'.length))
      ctx.providerCredentialStore.delete(fieldPath)
    }
  }
  sendJson(res, response.status, payload)
}

const sendProxyBlob = async (
  req: Parameters<HttpRouteHandler>[0],
  res: Parameters<HttpRouteHandler>[1],
  method: string,
  url: URL,
  ctx: Parameters<HttpRouteHandler>[4],
) => {
  const body = method === 'GET' || method === 'DELETE' ? undefined : await parseRequestBody<unknown>(req)
  const abortController = new AbortController()
  const timeout = setTimeout(() => abortController.abort(), PYTHON_PROXY_TIMEOUT_MS)
  const init: RequestInit = {
    method,
    headers: buildProxyHeaders(ctx, body !== undefined, String(req.headers['x-trace-id'] || '').trim() || null),
    signal: abortController.signal,
  }
  if (body !== undefined) {
    init.body = JSON.stringify(body)
  }

  let response: Response
  try {
    response = await fetch(`${resolvePythonApiOrigin()}${url.pathname}${url.search}`, init)
  } catch (error) {
    const aborted = abortController.signal.aborted
    sendJson(res, aborted ? 504 : 502, {
      error: aborted ? 'Python backend request timed out' : 'Python backend request failed',
      path: url.pathname,
      detail: error instanceof Error ? error.message : String(error),
    })
    return
  } finally {
    clearTimeout(timeout)
  }

  const allowHeaders = res.getHeader('Access-Control-Allow-Headers')
  const allowMethods = res.getHeader('Access-Control-Allow-Methods')
  const allowOrigin = res.getHeader('Access-Control-Allow-Origin')
  const vary = res.getHeader('Vary')
  const contentType = response.headers.get('Content-Type') || 'application/octet-stream'
  const contentDisposition = response.headers.get('Content-Disposition')
  const cacheControl = response.headers.get('Cache-Control')
  const headers: Record<string, string> = {
    ...(allowHeaders ? { 'Access-Control-Allow-Headers': String(allowHeaders) } : {}),
    ...(allowMethods ? { 'Access-Control-Allow-Methods': String(allowMethods) } : {}),
    ...(allowOrigin ? { 'Access-Control-Allow-Origin': String(allowOrigin) } : {}),
    ...(vary ? { Vary: String(vary) } : {}),
    'Content-Type': contentType,
    ...(contentDisposition ? { 'Content-Disposition': contentDisposition } : {}),
    ...(cacheControl ? { 'Cache-Control': cacheControl } : {}),
  }
  res.writeHead(response.status, headers)
  res.end(Buffer.from(await response.arrayBuffer()))
}

const readLogTail = (logPath: string, maxChars = 8000): string | null => {
  if (!fs.existsSync(logPath)) {
    return null
  }

  const stats = fs.statSync(logPath)
  const bytesToRead = Math.min(stats.size, maxChars)
  const buffer = Buffer.alloc(bytesToRead)
  const file = fs.openSync(logPath, 'r')
  try {
    fs.readSync(file, buffer, 0, bytesToRead, stats.size - bytesToRead)
  } finally {
    fs.closeSync(file)
  }

  const content = buffer.toString('utf8')
  return content.length > maxChars ? content.slice(-maxChars) : content
}

const resolveFirstExistingPath = (...candidatePaths: string[]): string | null => {
  for (const candidatePath of candidatePaths) {
    if (fs.existsSync(candidatePath)) {
      return candidatePath
    }
  }
  return null
}

const isPathInside = (baseDir: string, targetPath: string): boolean => {
  const relative = path.relative(path.resolve(baseDir), path.resolve(targetPath))
  return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative))
}

type BackupTargetSnapshot = {
  path: string
  exists: boolean
  type?: 'file' | 'directory' | 'other'
  backupPath?: string
  skippedReason?: string
}

type BackupManifest = {
  createdAt?: string
  targets?: BackupTargetSnapshot[]
}

type ImportedSkillStore = {
  savedAt?: string
  items?: unknown[]
}

const IMPORTED_SKILLS_STORE_FILE = 'imported-skills.json'
const MAX_IMPORTED_SKILLS = 1000

const resolveImportedSkillsStorePath = (): string =>
  path.join(app.getPath('userData'), 'skills', IMPORTED_SKILLS_STORE_FILE)

const normalizeStoredString = (value: unknown, maxLength = 2000): string => {
  if (typeof value !== 'string') {
    return ''
  }
  return value.trim().slice(0, maxLength)
}

const hashImportedSkillString = (value: string): string => {
  let hash = 0
  for (let index = 0; index < value.length; index += 1) {
    hash = ((hash << 5) - hash + value.charCodeAt(index)) | 0
  }
  return Math.abs(hash).toString(36)
}

const normalizeImportedSkillId = (value: string, fallback: string): string => {
  const raw = (value || fallback).trim()
  if (/^[a-z0-9_.:-]+$/i.test(raw)) {
    return raw.slice(0, 160)
  }

  const slug = raw
    .normalize('NFKD')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 120)

  return `imported.skill.${slug || hashImportedSkillString(raw)}`
}

const normalizeSkillFit = (value: unknown): SkillCatalogItem['fit'] => {
  if (value === 'high' || value === 'medium' || value === 'low') {
    return value
  }
  return 'medium'
}

const normalizeSkillTags = (value: unknown): string[] => {
  if (!Array.isArray(value)) {
    return []
  }

  return [...new Set(value.map((item) => normalizeStoredString(item, 48)).filter(Boolean))].slice(0, 16)
}

const normalizeOptionalField = (value: unknown, maxLength = 1000): string | null => {
  const normalized = normalizeStoredString(value, maxLength)
  return normalized || null
}

const normalizeImportedSkillItem = (
  value: unknown,
  index: number,
  usedIds: Set<string>,
): SkillCatalogItem | null => {
  if (!value || typeof value !== 'object') {
    return null
  }

  const raw = value as Record<string, unknown>
  const name = normalizeStoredString(raw['name'], 120) || normalizeStoredString(raw['id'], 120) || `Skill ${index + 1}`
  const baseId = normalizeImportedSkillId(
    normalizeStoredString(raw['id'], 160) || name,
    `imported.skill.${index + 1}`,
  )
  let id = baseId
  let suffix = 2
  while (usedIds.has(id)) {
    id = `${baseId}-${suffix}`
    suffix += 1
  }
  usedIds.add(id)

  return {
    id,
    name,
    description: normalizeStoredString(raw['description'], 2000) || '未填写说明',
    category: normalizeStoredString(raw['category'], 80) || '通用',
    source: 'imported',
    status: 'built-in',
    fit: normalizeSkillFit(raw['fit']),
    installed: true,
    enabled_codex: true,
    directory: normalizeOptionalField(raw['directory']),
    repo: normalizeOptionalField(raw['repo']),
    url: normalizeOptionalField(raw['url']),
    tags: normalizeSkillTags(raw['tags']),
  }
}

const normalizeImportedSkillItems = (items: unknown[]): SkillCatalogItem[] => {
  const usedIds = new Set<string>()
  return items
    .slice(0, MAX_IMPORTED_SKILLS)
    .map((item, index) => normalizeImportedSkillItem(item, index, usedIds))
    .filter((item): item is SkillCatalogItem => Boolean(item))
    .sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'))
}

const buildImportedSkillsSnapshot = (items: SkillCatalogItem[]): SkillCatalogSnapshot => {
  const categories = items.reduce<Record<string, number>>((acc, item) => {
    acc[item.category] = (acc[item.category] ?? 0) + 1
    return acc
  }, {})

  return {
    items,
    summary: {
      total: items.length,
      built_in: items.filter((item) => item.status === 'built-in').length,
      ready: items.filter((item) => item.installed).length,
      planned: items.filter((item) => item.status === 'planned').length,
      high_fit: items.filter((item) => item.fit === 'high').length,
      medium_fit: items.filter((item) => item.fit === 'medium').length,
      recommended: items.filter((item) => item.fit === 'high' || item.fit === 'medium').length,
      categories,
    },
  }
}

const readImportedSkillsSnapshot = (): SkillCatalogSnapshot => {
  const storePath = resolveImportedSkillsStorePath()
  if (!fs.existsSync(storePath)) {
    return buildImportedSkillsSnapshot([])
  }

  try {
    const payload = JSON.parse(fs.readFileSync(storePath, 'utf8')) as ImportedSkillStore | unknown[]
    const items = Array.isArray(payload)
      ? payload
      : Array.isArray((payload as ImportedSkillStore).items)
        ? (payload as ImportedSkillStore).items ?? []
        : []
    return buildImportedSkillsSnapshot(normalizeImportedSkillItems(items))
  } catch {
    return buildImportedSkillsSnapshot([])
  }
}

const writeImportedSkillsSnapshot = (items: SkillCatalogItem[]): SkillCatalogSnapshot => {
  const snapshot = buildImportedSkillsSnapshot(normalizeImportedSkillItems(items))
  const storePath = resolveImportedSkillsStorePath()
  fs.mkdirSync(path.dirname(storePath), { recursive: true })
  const tempPath = `${storePath}.${process.pid}.${Date.now()}.tmp`
  try {
    fs.writeFileSync(tempPath, JSON.stringify({ savedAt: new Date().toISOString(), items: snapshot.items }, null, 2), 'utf8')
    fs.renameSync(tempPath, storePath)
  } finally {
    if (fs.existsSync(tempPath)) {
      fs.rmSync(tempPath, { force: true })
    }
  }
  return snapshot
}

const deleteImportedSkills = (ids: unknown): SkillCatalogSnapshot & { ok: boolean; removed: number } => {
  const idSet = new Set(Array.isArray(ids) ? ids.map((id) => normalizeStoredString(id, 160)).filter(Boolean) : [])
  const currentItems = readImportedSkillsSnapshot().items
  const nextItems = currentItems.filter((item) => !idSet.has(item.id))
  const snapshot = writeImportedSkillsSnapshot(nextItems)
  return {
    ...snapshot,
    ok: true,
    removed: currentItems.length - nextItems.length,
  }
}

const collectBackupTargets = () => {
  const electronRoot = resolveElectronRoot()
  const projectRoot = resolveProjectRoot()
  const userDataDir = app.getPath('userData')
  return [
    path.join(projectRoot, 'python/data/chat.db'),
    path.join(projectRoot, 'python/data/memory.db'),
    path.join(projectRoot, 'python/config/settings.json'),
    path.join(projectRoot, 'python/data/governance_alert_state.json'),
    path.join(projectRoot, 'python/audio_cache'),
    path.join(userDataDir, 'pet-state.json'),
    path.join(electronRoot, 'plugins'),
  ]
}

const comparablePath = (targetPath: string): string => {
  const resolved = path.resolve(targetPath)
  return process.platform === 'win32' ? resolved.toLowerCase() : resolved
}

const validateRestoreDestination = (targetPath: string): string | null => {
  const resolvedTarget = path.resolve(targetPath)
  if (fs.existsSync(resolvedTarget) && fs.lstatSync(resolvedTarget).isSymbolicLink()) {
    return 'backup restore target must not be a symbolic link'
  }

  const parentDir = path.dirname(resolvedTarget)
  const parsed = path.parse(parentDir)
  let currentPath = parsed.root
  const relativeParts = path.relative(parsed.root, parentDir).split(path.sep).filter(Boolean)
  for (const part of relativeParts) {
    currentPath = path.join(currentPath, part)
    if (!fs.existsSync(currentPath)) {
      break
    }
    if (fs.lstatSync(currentPath).isSymbolicLink()) {
      return 'backup restore target parent must not be a symbolic link'
    }
  }

  return null
}

const copyBackupEntry = (sourcePath: string, destinationPath: string): { copied: boolean; type: 'file' | 'directory' | 'other'; skippedReason?: string } => {
  const stats = fs.lstatSync(sourcePath)
  if (stats.isSymbolicLink()) {
    return { copied: false, type: 'other', skippedReason: 'symbolic_link' }
  }

  if (stats.isDirectory()) {
    fs.mkdirSync(destinationPath, { recursive: true })
    for (const item of fs.readdirSync(sourcePath)) {
      const childSource = path.join(sourcePath, item)
      const childDestination = path.join(destinationPath, item)
      copyBackupEntry(childSource, childDestination)
    }
    return { copied: true, type: 'directory' }
  }

  if (stats.isFile()) {
    fs.mkdirSync(path.dirname(destinationPath), { recursive: true })
    fs.copyFileSync(sourcePath, destinationPath)
    return { copied: true, type: 'file' }
  }

  return { copied: false, type: 'other', skippedReason: 'unsupported_file_type' }
}

const createBackupManifest = (backupDir: string): BackupManifest => {
  const targets = collectBackupTargets().map((target, index): BackupTargetSnapshot => {
    if (!fs.existsSync(target)) {
      return { path: target, exists: false }
    }

    const backupPath = path.join('targets', `${index}-${path.basename(target) || 'target'}`)
    const copyResult = copyBackupEntry(target, path.join(backupDir, backupPath))
    const snapshot: BackupTargetSnapshot = {
      path: target,
      exists: true,
      type: copyResult.type,
    }
    if (copyResult.copied) {
      snapshot.backupPath = backupPath
    }
    if (copyResult.skippedReason) {
      snapshot.skippedReason = copyResult.skippedReason
    }
    return snapshot
  })

  return {
    createdAt: new Date().toISOString(),
    targets,
  }
}

const restoreBackupEntry = (sourcePath: string, destinationPath: string, type: BackupTargetSnapshot['type']): void => {
  if (type === 'directory') {
    fs.rmSync(destinationPath, { recursive: true, force: true })
    copyBackupEntry(sourcePath, destinationPath)
    return
  }

  if (type === 'file') {
    fs.mkdirSync(path.dirname(destinationPath), { recursive: true })
    fs.copyFileSync(sourcePath, destinationPath)
  }
}

type RestorePlanItem = {
  path: string
  currentlyExists: boolean
  backedUpAtSnapshot: boolean
  restored: boolean
  skippedReason?: string
}

type RestoreEffectStatus = 'will_restore' | 'restored' | 'rebuild_required' | 'unchanged' | 'skipped'

type RestoreEffectSummary = {
  database: RestoreEffectStatus
  memoryIndex: RestoreEffectStatus
  settings: RestoreEffectStatus
  governance: RestoreEffectStatus
  audioCache: RestoreEffectStatus
  petState: RestoreEffectStatus
  plugins: RestoreEffectStatus
}

type RestoreSummary = {
  totalTargets: number
  restoreCount: number
  skippedCount: number
  overwriteCount: number
  missingCurrentCount: number
}

const buildRestoreImpact = (restorePlan: RestorePlanItem[], dryRun: boolean): { summary: RestoreSummary; effects: RestoreEffectSummary } => {
  const restorable = restorePlan.filter((item) => item.backedUpAtSnapshot && !item.skippedReason)
  const summary: RestoreSummary = {
    totalTargets: restorePlan.length,
    restoreCount: restorable.length,
    skippedCount: restorePlan.length - restorable.length,
    overwriteCount: restorable.filter((item) => item.currentlyExists).length,
    missingCurrentCount: restorable.filter((item) => !item.currentlyExists).length,
  }

  const statusFor = (suffix: string): RestoreEffectStatus => {
    const item = restorePlan.find((candidate) => candidate.path.replace(/\\/g, '/').endsWith(suffix))
    if (!item || !item.backedUpAtSnapshot || item.skippedReason) return item ? 'skipped' : 'unchanged'
    return dryRun ? 'will_restore' : item.restored ? 'restored' : 'skipped'
  }

  const memoryStatus = statusFor('/python/data/memory.db')
  const effects: RestoreEffectSummary = {
    database: statusFor('/python/data/chat.db'),
    memoryIndex: memoryStatus === 'unchanged' ? 'unchanged' : memoryStatus === 'skipped' ? 'skipped' : 'rebuild_required',
    settings: statusFor('/python/config/settings.json'),
    governance: statusFor('/python/data/governance_alert_state.json'),
    audioCache: statusFor('/python/audio_cache'),
    petState: statusFor('/pet-state.json'),
    plugins: statusFor('/plugins'),
  }

  return { summary, effects }
}

const buildRestorePlan = (manifest: BackupManifest, realBackupDir: string, dryRun: boolean) => {
  const allowedTargets = new Set(collectBackupTargets().map((target) => comparablePath(target)))
  const restorePlan: RestorePlanItem[] = []

  for (const target of manifest.targets ?? []) {
    if (!allowedTargets.has(comparablePath(target.path))) {
      return {
        error: 'backup manifest contains unmanaged target',
        target: target.path,
        restorePlan,
      }
    }

    const plan: RestorePlanItem = {
      path: target.path,
      currentlyExists: fs.existsSync(target.path),
      backedUpAtSnapshot: target.exists,
      restored: false,
    }

    if (!target.exists) {
      plan.skippedReason = 'not_present_at_snapshot'
    } else if (!target.backupPath || !target.type || target.skippedReason) {
      plan.skippedReason = target.skippedReason ?? 'snapshot_missing'
    } else {
      const backupSource = path.resolve(realBackupDir, target.backupPath)
      if (!isPathInside(realBackupDir, backupSource)) {
        return {
          error: 'backup manifest contains invalid snapshot path',
          target: target.path,
          restorePlan,
        }
      }

      if (!fs.existsSync(backupSource)) {
        plan.skippedReason = 'snapshot_missing'
      } else {
        const realBackupSource = fs.realpathSync.native(backupSource)
        if (!isPathInside(realBackupDir, realBackupSource)) {
          return {
            error: 'backup manifest contains invalid snapshot path',
            target: target.path,
            restorePlan,
          }
        }
        if (!dryRun) {
          const destinationError = validateRestoreDestination(target.path)
          if (destinationError) {
            return {
              error: destinationError,
              target: target.path,
              restorePlan,
            }
          }
          restoreBackupEntry(realBackupSource, target.path, target.type)
          plan.restored = true
          plan.currentlyExists = fs.existsSync(target.path)
        }
      }
    }

    restorePlan.push(plan)
  }

  return { restorePlan, impact: buildRestoreImpact(restorePlan, dryRun) }
}

const collectEnvironmentChecks = () => {
  const electronRoot = resolveElectronRoot()
  const projectRoot = resolveProjectRoot()
  const pythonRuntime = resolvePythonRuntime(path.join(projectRoot, 'python'))
  return {
    electronRoot,
    projectRoot,
    pythonAppExists: fs.existsSync(path.join(projectRoot, 'python/app.py')),
    pythonVenvExists: pythonRuntime.venvExists,
    pythonVenvPath: path.relative(projectRoot, pythonRuntime.venvPath).split(path.sep).join('/'),
    rendererDistExists: fs.existsSync(path.join(electronRoot, 'dist/renderer/index.html')),
    pluginDirExists: fs.existsSync(path.join(electronRoot, 'plugins')),
    backupDirExists: fs.existsSync(path.join(projectRoot, 'backups')),
  }
}

const resolveControlPanelUrl = (): string => {
  const rawPort = Number.parseInt(String(process.env['CONTROL_SERVER_PORT'] || '').trim(), 10)
  const port = Number.isInteger(rawPort) && rawPort > 0 && rawPort <= 65535 ? rawPort : 38945
  return `http://localhost:${port}/`
}

const scanPetOverlayVisibility = async (ctx: Parameters<HttpRouteHandler>[4]): Promise<boolean | null> => {
  try {
    return await ctx.live2dWindow.hasVisiblePixels()
  } catch {
    return null
  }
}

const PYTHON_JSON_PROXY_PATHS = new Set([
  '/api/ping',
  '/api/readiness',
  '/health',
  '/memory/docs',
  '/memory/overview',
  '/memory/query',
  '/memory/index/status',
  '/memory/index/rebuild',
  '/memory/memory/add',
  '/memory/rag/query',
  '/memory/maintenance/preview',
  '/memory/maintenance/apply',
  '/api/memory/pipeline/query',
  '/api/agent/recovery/resume',
  '/api/companions',
  '/api/chat/translate',
  '/api/i18n/locales',
  '/api/i18n/messages',
  '/api/summary',
  '/api/summary/audit',
  '/api/summary/report/json',
  '/system/status',
  '/api/database/stats',
  '/api/statistics',
  '/api/statistics/update',
  '/v1/models',
  '/api/settings',
  '/api/settings/',
  '/api/summary/alerts/ack',
  '/api/summary/alerts/snooze',
  '/api/summary/alerts/clear',
  '/api/system/permissions',
  '/api/system/capabilities',
  '/api/system/providers',
  '/api/system/connectors',
  '/api/system/platforms',
  '/api/system/orchestration',
  '/api/system/schedules',
  '/api/system/mcp',
  '/api/system/agent-trace',
  '/api/system/experience-metrics',
  '/api/system/product-metrics/consent',
  '/api/system/agent-plugins',
  '/api/system/heartbeat',
  '/api/system/companion-runtime',
  '/api/system/storage',
  '/api/system/storage/cleanup',
  '/api/system/active-workspace',
  '/api/workspaces',
  '/api/sessions',
  '/api/session-branches',
])

const isPythonJsonProxyPath = (pathname: string): boolean =>
  PYTHON_JSON_PROXY_PATHS.has(pathname) ||
  pathname.startsWith('/memory/docs/') ||
  pathname.startsWith('/api/companions/') ||
  pathname.startsWith('/api/history/') ||
  pathname.startsWith('/api/i18n/') ||
  pathname.startsWith('/api/summary/') ||
  pathname.startsWith('/api/settings/') ||
  pathname.startsWith('/api/memory/') ||
  pathname.startsWith('/api/system/permissions/') ||
  pathname.startsWith('/api/system/schedules/') ||
  pathname.startsWith('/api/system/mcp/') ||
  pathname.startsWith('/api/system/agent-plugins/') ||
  pathname.startsWith('/api/system/connectors/') ||
  /^\/api\/messages\/[^/]+$/.test(pathname) ||
  /^\/api\/sessions\/[^/]+$/.test(pathname) ||
  /^\/api\/sessions\/[^/]+\/messages$/.test(pathname) ||
  /^\/api\/workspaces\/[^/]+$/.test(pathname) ||
  /^\/api\/workspaces\/[^/]+\/sessions$/.test(pathname) ||
  /^\/api\/workspaces\/[^/]+\/effective-preset$/.test(pathname)

const isPythonBlobProxyPath = (pathname: string): boolean =>
  pathname === '/api/settings/export' ||
  pathname === '/api/summary/report/csv' ||
  pathname === '/api/export/json' ||
  pathname === '/api/export/csv'

const isProactivePythonProxyRoute = (method: string, pathname: string): boolean =>
  (method === 'GET' && pathname === '/api/system/proactive/settings')
  || (method === 'PATCH' && pathname === '/api/system/proactive/settings')
  || (method === 'POST' && pathname === '/api/system/proactive/feedback')
  || (method === 'POST' && /^\/api\/system\/companion-runtime\/opportunities\/outcome\/[^/]+$/.test(pathname))
  || (method === 'POST' && /^\/api\/system\/heartbeat\/opportunities\/[^/]+\/accept$/.test(pathname))
  || (method === 'POST' && /^\/api\/system\/heartbeat\/goals\/[^/]+\/cancel$/.test(pathname))
  || (method === 'GET' && pathname === '/api/system/activity-frames')
  || (method === 'DELETE' && /^\/api\/system\/activity-frames\/(?!rebuild$)[^/]+$/.test(pathname))

export const handleSystemRoutes: HttpRouteHandler = async (_req, res, method, url, ctx) => {
  if (method === 'GET' && url.pathname === '/api/health') {
    sendJson(res, 200, { status: 'ok' })
    return true
  }

  if (method === 'GET' && url.pathname === '/api/system/diagnostics') {
    const snapshot = ctx.pluginRegistry.snapshot()
    const petOverlayHasVisiblePixels = await scanPetOverlayVisibility(ctx)
    sendJson(res, 200, {
      status: 'ok',
      panelUrl: resolveControlPanelUrl(),
      petWindowVisible: Boolean(ctx.petWindow.window?.isVisible()),
      petOverlayVisible: Boolean(ctx.live2dWindow.window?.isVisible()),
      petOverlayHasVisiblePixels,
      petBounds: ctx.live2dWindow.getBounds(),
      petState: ctx.petStateStore.getState(),
      pluginCount: snapshot.plugins.length,
      pluginErrorCount: snapshot.loadFailures.length,
      activePluginExecutions: snapshot.pluginStates.reduce((sum, item) => sum + item.activeExecutions.length, 0),
      runtimeExceptions: getRuntimeExceptions(),
      envCheck: collectEnvironmentChecks(),
    })
    return true
  }

  if (method === 'GET' && url.pathname === '/api/system/logs') {
    const electronRoot = resolveElectronRoot()
    const projectRoot = resolveProjectRoot()
    const rendererPath = resolveFirstExistingPath(
      path.join(electronRoot, 'live2d-renderer.log'),
      path.join(projectRoot, 'logs/dev/live2d-renderer.log'),
      path.join(projectRoot, 'logs/prod/live2d-renderer.log'),
    )
    const pythonPath = resolveFirstExistingPath(
      path.join(projectRoot, 'logs/dev/python.log'),
      path.join(projectRoot, 'logs/prod/python.log'),
      path.join(projectRoot, 'logs/python.log'),
    )
    const electronPath = resolveFirstExistingPath(
      path.join(projectRoot, 'logs/dev/electron.log'),
      path.join(projectRoot, 'logs/prod/electron.log'),
      path.join(projectRoot, 'logs/electron.log'),
    )

    sendJson(res, 200, {
      logs: {
        renderer: rendererPath ? readLogTail(rendererPath) : null,
        python: pythonPath ? readLogTail(pythonPath) : null,
        electron: electronPath ? readLogTail(electronPath) : null,
      },
      metadata: {
        rendererExists: Boolean(rendererPath),
        pythonExists: Boolean(pythonPath),
        electronExists: Boolean(electronPath),
      },
      pluginAudit: ctx.pluginRegistry.getAuditLog().slice(0, 20),
      runtimeExceptions: getRuntimeExceptions(),
    })
    return true
  }

  if (method === 'GET' && url.pathname === '/api/system/backup/targets') {
    const targets = collectBackupTargets().map((target) => ({
      path: target,
      exists: fs.existsSync(target),
      type: fs.existsSync(target) && fs.statSync(target).isDirectory() ? 'directory' : 'file',
    }))

    sendJson(res, 200, { targets })
    return true
  }

  if (method === 'POST' && url.pathname === '/api/system/backup/create') {
    const backupRoot = path.join(resolveProjectRoot(), 'backups')
    fs.mkdirSync(backupRoot, { recursive: true })
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-')
    const backupDir = path.join(backupRoot, `backup-${timestamp}`)
    fs.mkdirSync(backupDir, { recursive: true })

    const manifest = createBackupManifest(backupDir)

    fs.writeFileSync(path.join(backupDir, 'manifest.json'), JSON.stringify(manifest, null, 2), 'utf8')
    sendJson(res, 200, { ok: true, backupDir, manifest })
    return true
  }

  if (method === 'POST' && url.pathname === '/api/system/backup/restore') {
    const body = await parseRequestBody<{ backupDir?: string; dryRun?: boolean }>(_req)
    if (!body.backupDir) {
      sendJson(res, 400, { error: 'backupDir is required' })
      return true
    }

    const backupRoot = path.resolve(resolveProjectRoot(), 'backups')
    const backupDir = path.resolve(body.backupDir)
    if (!isPathInside(backupRoot, backupDir)) {
      sendJson(res, 403, { error: 'backupDir must stay within the managed backups directory' })
      return true
    }

    let realBackupRoot: string
    let realBackupDir: string
    try {
      realBackupRoot = fs.realpathSync.native(backupRoot)
      realBackupDir = fs.realpathSync.native(backupDir)
    } catch {
      sendJson(res, 404, { error: 'backup manifest not found' })
      return true
    }

    if (!isPathInside(realBackupRoot, realBackupDir)) {
      sendJson(res, 403, { error: 'backupDir must stay within the managed backups directory' })
      return true
    }

    const manifestPath = path.join(realBackupDir, 'manifest.json')
    if (!fs.existsSync(manifestPath)) {
      sendJson(res, 404, { error: 'backup manifest not found' })
      return true
    }

    const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8')) as BackupManifest
    const dryRun = body.dryRun !== false
    const restoreResult = buildRestorePlan(manifest, realBackupDir, dryRun)
    if ('error' in restoreResult) {
      sendJson(res, 403, restoreResult)
      return true
    }

    sendJson(res, 200, {
      ok: true,
      dryRun,
      backupDir: realBackupDir,
      manifest,
      restorePlan: restoreResult.restorePlan,
      summary: restoreResult.impact.summary,
      effects: restoreResult.impact.effects,
    })
    return true
  }

  if (method === 'GET' && url.pathname === '/api/system/env-check') {
    sendJson(res, 200, {
      status: 'ok',
      pythonApiOrigin: resolvePythonApiOrigin(),
      checks: collectEnvironmentChecks(),
    })
    return true
  }

  if (method === 'GET' && url.pathname === '/api/system/backend-token') {
    sendJson(res, 200, ctx.backendApiTokenStore.getBackendApiTokenStatus())
    return true
  }

  if (method === 'GET' && url.pathname === '/api/system/skills/imported') {
    sendJson(res, 200, readImportedSkillsSnapshot())
    return true
  }

  if (method === 'PUT' && url.pathname === '/api/system/skills/imported') {
    const body = await parseRequestBody<{ items?: unknown[] }>(_req)
    const items = Array.isArray(body.items) ? body.items : []
    sendJson(res, 200, writeImportedSkillsSnapshot(normalizeImportedSkillItems(items)))
    return true
  }

  if (method === 'GET' && url.pathname === '/api/system/resources') {
    sendJson(res, 200, getModelResourceStatus(ctx.petModelCatalog))
    return true
  }

  if (method === 'GET' && url.pathname === '/api/system/resources/progress') {
    sendJson(res, 200, getModelResourceProgress())
    return true
  }

  if (method === 'POST' && url.pathname === '/api/system/resources/prepare') {
    const body = await parseRequestBody<{ resources?: ManagedModelResourceId[] }>(_req)
    const resources = Array.isArray(body.resources) ? body.resources.slice(0, 5) : []
    sendJson(res, 200, await prepareModelResources(resources, ctx.petModelCatalog))
    return true
  }

  if (method === 'POST' && url.pathname === '/api/system/resources/cancel') {
    const body = await parseRequestBody<{ resources?: ManagedModelResourceId[] }>(_req)
    const resources = Array.isArray(body.resources) ? body.resources.slice(0, 5) : []
    sendJson(res, 200, cancelModelResources(resources, ctx.petModelCatalog))
    return true
  }

  if (method === 'POST' && url.pathname === '/api/system/resources/remove') {
    const body = await parseRequestBody<{ resources?: ManagedModelResourceId[]; confirmation?: string }>(_req)
    if (body.confirmation !== 'PERMANENT_REMOVE') {
      sendJson(res, 400, { error: 'PERMANENT_REMOVE confirmation is required' })
      return true
    }
    const resources = Array.isArray(body.resources) ? body.resources.slice(0, 5) : []
    sendJson(res, 200, removeModelResources(resources, ctx.petModelCatalog))
    return true
  }

  if (method === 'POST' && url.pathname === '/api/system/resources/soulx/download') {
    sendJson(res, 200, await prepareSoulxModels(ctx.petModelCatalog))
    return true
  }

  if (method === 'POST' && url.pathname === '/api/system/resources/soulx/reference') {
    sendJson(res, 200, await importSoulxReferenceAudio(ctx.petModelCatalog))
    return true
  }

  if (method === 'POST' && url.pathname === '/api/system/resources/sherpa/download') {
    sendJson(res, 200, await prepareSherpaSenseVoice(ctx.petModelCatalog))
    return true
  }

  if (method === 'POST' && url.pathname === '/api/system/resources/sherpa-online/download') {
    sendJson(res, 200, await prepareSherpaStreamingZipformer(ctx.petModelCatalog))
    return true
  }

  if (method === 'POST' && url.pathname === '/api/system/resources/embedding/prefetch') {
    sendJson(res, 200, await prepareEmbeddingModel(ctx.petModelCatalog))
    return true
  }

  if (method === 'POST' && url.pathname === '/api/system/resources/tts/prefetch') {
    sendJson(res, 200, await prepareGenieTts(ctx.petModelCatalog))
    return true
  }

  if (method === 'POST' && url.pathname === '/api/system/backend-token') {
    const body = await parseRequestBody<{ token?: string }>(_req)
    try {
      sendJson(res, 200, ctx.backendApiTokenStore.setBackendApiToken(String(body.token || '')))
    } catch (error) {
      sendJson(res, 400, { ok: false, error: error instanceof Error ? error.message : 'Invalid backend API token' })
    }
    return true
  }

  if (method === 'DELETE' && url.pathname === '/api/system/backend-token') {
    sendJson(res, 200, ctx.backendApiTokenStore.resetBackendApiToken())
    return true
  }

  if (method === 'DELETE' && url.pathname === '/api/system/skills/imported') {
    const body = await parseRequestBody<{ ids?: unknown[] }>(_req)
    sendJson(res, 200, deleteImportedSkills(body.ids))
    return true
  }

  if (method === 'POST' && /^\/api\/summary\/[^/]+\/rewrite$/.test(url.pathname)) {
    await proxyPythonJson(_req, res, method, url, ctx)
    return true
  }

  if (isPythonBlobProxyPath(url.pathname)) {
    await sendProxyBlob(_req, res, method, url, ctx)
    return true
  }

  if (isProactivePythonProxyRoute(method, url.pathname) || isPythonJsonProxyPath(url.pathname)) {
    await proxyPythonJson(_req, res, method, url, ctx)
    return true
  }

  return false
}
