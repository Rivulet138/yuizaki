import { EventEmitter } from 'node:events'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { app } from 'electron'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { HttpRouteContext } from '../http/types'
import type { BackendApiTokenStoreLike } from '../backend-api-token-store'

vi.mock('electron', () => ({
  app: {
    getPath: vi.fn(() => os.tmpdir()),
  },
  dialog: {
    showOpenDialog: vi.fn(),
  },
}))

const ORIGINAL_ENV = {
  DESKTOP_PET_BACKEND_URL: process.env['DESKTOP_PET_BACKEND_URL'],
  SERVER_HOST: process.env['SERVER_HOST'],
  SERVER_PORT: process.env['SERVER_PORT'],
  YUIZAKI_ELECTRON_ROOT: process.env['YUIZAKI_ELECTRON_ROOT'],
}

const restoreEnv = () => {
  for (const [key, value] of Object.entries(ORIGINAL_ENV)) {
    if (value === undefined) {
      delete process.env[key]
    } else {
      process.env[key] = value
    }
  }
}

const expectedBackendOrigin = (): string => {
  const explicitUrl = process.env['DESKTOP_PET_BACKEND_URL']?.trim()
  if (explicitUrl) {
    const withoutTrailingSlash = explicitUrl.replace(/\/$/, '')
    return withoutTrailingSlash.endsWith('/health')
      ? withoutTrailingSlash.slice(0, -'/health'.length)
      : withoutTrailingSlash
  }

  const host = process.env['SERVER_HOST']?.trim() || 'localhost'
  const port = process.env['SERVER_PORT']?.trim() || '8001'
  return `http://${host}:${port}`
}

const createJsonRequest = (body: unknown, headers: IncomingMessage['headers'] = {}): IncomingMessage => {
  const request = new EventEmitter() as EventEmitter & {
    headers: IncomingMessage['headers']
    setEncoding: (encoding: BufferEncoding) => void
  }
  request.headers = headers
  request.setEncoding = () => {}

  queueMicrotask(() => {
    request.emit('data', JSON.stringify(body))
    request.emit('end')
  })

  return request as unknown as IncomingMessage
}

const createJsonResponse = (): {
  response: ServerResponse
  getStatus: () => number | null
  getJson: () => unknown
  getText: () => string
  getHeader: (name: string) => number | string | string[] | undefined
} => {
  let statusCode: number | null = null
  let payloadText = ''
  const headers = new Map<string, number | string | string[]>()
  const response = {
    getHeader: (name: string) => headers.get(name),
    writeHead: (nextStatusCode: number, nextHeaders?: Record<string, number | string | string[]>) => {
      statusCode = nextStatusCode
      for (const [name, value] of Object.entries(nextHeaders ?? {})) {
        headers.set(name, value)
      }
      return response
    },
    end: (payload?: string | Buffer) => {
      payloadText = Buffer.isBuffer(payload) ? payload.toString('utf8') : payload ?? ''
      return response
    },
  }

  return {
    response: response as unknown as ServerResponse,
    getStatus: () => statusCode,
    getJson: () => JSON.parse(payloadText) as unknown,
    getText: () => payloadText,
    getHeader: (name: string) => headers.get(name),
  }
}

const createBackendApiTokenStoreMock = (
  overrides: Partial<BackendApiTokenStoreLike> = {},
): BackendApiTokenStoreLike => ({
  getBackendApiToken: vi.fn(() => 'active-backend-token'),
  getBackendApiTokenStatus: vi.fn(() => ({
    hasToken: true,
    source: 'stored',
    tokenPreview: 'active...oken',
    storedTokenPreview: 'active...oken',
    requiresRestart: false,
  })),
  setBackendApiToken: vi.fn(() => ({
    ok: true,
    hasToken: true,
    source: 'stored',
    tokenPreview: 'saved...oken',
    requiresRestart: true,
  })),
  resetBackendApiToken: vi.fn(() => ({
    ok: true,
    hasToken: true,
    source: 'generated',
    tokenPreview: 'next...oken',
    requiresRestart: true,
  })),
  ...overrides,
})

describe('system routes', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.mocked(app.getPath).mockReturnValue(os.tmpdir())
    restoreEnv()
  })

  it('requires explicit confirmation before permanent model removal', async () => {
    const { handleSystemRoutes } = await import('../http/routes/system-routes')
    const { response, getStatus, getJson } = createJsonResponse()

    const handled = await handleSystemRoutes(
      createJsonRequest({ resources: ['sherpa'] }),
      response,
      'POST',
      new URL('http://127.0.0.1:38945/api/system/resources/remove'),
      {} as HttpRouteContext,
    )

    expect(handled).toBe(true)
    expect(getStatus()).toBe(400)
    expect(getJson()).toEqual({ error: 'PERMANENT_REMOVE confirmation is required' })
  })

  it('rejects backup restore paths outside the managed backups directory', async () => {
    const { handleSystemRoutes } = await import('../http/routes/system-routes')
    const { response, getStatus, getJson } = createJsonResponse()

    const handled = await handleSystemRoutes(
      createJsonRequest({ backupDir: path.join(os.tmpdir(), 'not-yuizaki-backup') }),
      response,
      'POST',
      new URL('http://127.0.0.1:38945/api/system/backup/restore'),
      {} as HttpRouteContext,
    )

    expect(handled).toBe(true)
    expect(getStatus()).toBe(403)
    expect(getJson()).toEqual({ error: 'backupDir must stay within the managed backups directory' })
  })

  it('rejects backup restore paths that escape through symlinks', async () => {
    const projectRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-project-root-'))
    const electronRoot = path.join(projectRoot, 'electron')
    const backupRoot = path.join(projectRoot, 'backups')
    const outsideRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-backup-outside-'))
    const linkDir = path.join(backupRoot, 'linked')

    try {
      fs.mkdirSync(electronRoot, { recursive: true })
      fs.mkdirSync(backupRoot, { recursive: true })
      fs.writeFileSync(path.join(outsideRoot, 'manifest.json'), JSON.stringify({ createdAt: 'outside', targets: [] }), 'utf8')
      try {
        fs.symlinkSync(outsideRoot, linkDir, process.platform === 'win32' ? 'junction' : 'dir')
      } catch {
        return
      }
      process.env['YUIZAKI_ELECTRON_ROOT'] = electronRoot

      const { handleSystemRoutes } = await import('../http/routes/system-routes')
      const { response, getStatus, getJson } = createJsonResponse()

      const handled = await handleSystemRoutes(
        createJsonRequest({ backupDir: linkDir }),
        response,
        'POST',
        new URL('http://127.0.0.1:38945/api/system/backup/restore'),
        {} as HttpRouteContext,
      )

      expect(handled).toBe(true)
      expect(getStatus()).toBe(403)
      expect(getJson()).toEqual({ error: 'backupDir must stay within the managed backups directory' })
    } finally {
      fs.rmSync(projectRoot, { recursive: true, force: true })
      fs.rmSync(outsideRoot, { recursive: true, force: true })
    }
  })

  it('creates file snapshots and restores them when dryRun is false', async () => {
    const projectRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-project-root-'))
    const electronRoot = path.join(projectRoot, 'electron')
    const chatDbPath = path.join(projectRoot, 'python/data/chat.db')
    const memoryDbPath = path.join(projectRoot, 'python/data/memory.db')

    try {
      fs.mkdirSync(electronRoot, { recursive: true })
      fs.mkdirSync(path.dirname(chatDbPath), { recursive: true })
      fs.writeFileSync(chatDbPath, 'snapshot-version', 'utf8')
      fs.writeFileSync(memoryDbPath, 'memory-snapshot-version', 'utf8')
      process.env['YUIZAKI_ELECTRON_ROOT'] = electronRoot

      const { handleSystemRoutes } = await import('../http/routes/system-routes')
      const createResponse = createJsonResponse()
      const createHandled = await handleSystemRoutes(
        createJsonRequest({}),
        createResponse.response,
        'POST',
        new URL('http://127.0.0.1:38945/api/system/backup/create'),
        {} as HttpRouteContext,
      )
      const createPayload = createResponse.getJson() as { backupDir: string; manifest: { targets: Array<{ path: string; backupPath?: string }> } }

      expect(createHandled).toBe(true)
      expect(createResponse.getStatus()).toBe(200)
      expect(createPayload.manifest.targets.find((target) => target.path === chatDbPath)?.backupPath).toBeTruthy()
      expect(createPayload.manifest.targets.find((target) => target.path === memoryDbPath)?.backupPath).toBeTruthy()

      fs.writeFileSync(chatDbPath, 'mutated-version', 'utf8')
      fs.writeFileSync(memoryDbPath, 'memory-mutated-version', 'utf8')

      const restoreResponse = createJsonResponse()
      const restoreHandled = await handleSystemRoutes(
        createJsonRequest({ backupDir: createPayload.backupDir, dryRun: false }),
        restoreResponse.response,
        'POST',
        new URL('http://127.0.0.1:38945/api/system/backup/restore'),
        {} as HttpRouteContext,
      )
      const restorePayload = restoreResponse.getJson() as {
        restorePlan: Array<{ path: string; restored: boolean }>
        summary: { totalTargets: number; restoreCount: number; skippedCount: number; overwriteCount: number; missingCurrentCount: number }
        effects: { database: string; memoryIndex: string }
      }

      expect(restoreHandled).toBe(true)
      expect(restoreResponse.getStatus()).toBe(200)
      expect(fs.readFileSync(chatDbPath, 'utf8')).toBe('snapshot-version')
      expect(fs.readFileSync(memoryDbPath, 'utf8')).toBe('memory-snapshot-version')
      expect(restorePayload.restorePlan.find((target) => target.path === chatDbPath)?.restored).toBe(true)
      expect(restorePayload.restorePlan.find((target) => target.path === memoryDbPath)?.restored).toBe(true)
      expect(restorePayload.summary.totalTargets).toBeGreaterThanOrEqual(2)
      expect(restorePayload.summary.restoreCount).toBe(restorePayload.summary.overwriteCount)
      expect(restorePayload.summary.skippedCount).toBe(restorePayload.summary.totalTargets - restorePayload.summary.restoreCount)
      expect(restorePayload.effects.database).toBe('restored')
      expect(restorePayload.effects.memoryIndex).toBe('rebuild_required')
    } finally {
      fs.rmSync(projectRoot, { recursive: true, force: true })
    }
  })

  it('previews backup restore plans without mutating files by default', async () => {
    const projectRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-project-root-'))
    const electronRoot = path.join(projectRoot, 'electron')
    const chatDbPath = path.join(projectRoot, 'python/data/chat.db')

    try {
      fs.mkdirSync(electronRoot, { recursive: true })
      fs.mkdirSync(path.dirname(chatDbPath), { recursive: true })
      fs.writeFileSync(chatDbPath, 'snapshot-version', 'utf8')
      process.env['YUIZAKI_ELECTRON_ROOT'] = electronRoot

      const { handleSystemRoutes } = await import('../http/routes/system-routes')
      const createResponse = createJsonResponse()
      await handleSystemRoutes(
        createJsonRequest({}),
        createResponse.response,
        'POST',
        new URL('http://127.0.0.1:38945/api/system/backup/create'),
        {} as HttpRouteContext,
      )
      const createPayload = createResponse.getJson() as { backupDir: string }

      fs.writeFileSync(chatDbPath, 'mutated-version', 'utf8')

      const restoreResponse = createJsonResponse()
      const restoreHandled = await handleSystemRoutes(
        createJsonRequest({ backupDir: createPayload.backupDir }),
        restoreResponse.response,
        'POST',
        new URL('http://127.0.0.1:38945/api/system/backup/restore'),
        {} as HttpRouteContext,
      )
      const restorePayload = restoreResponse.getJson() as {
        dryRun: boolean
        restorePlan: Array<{ path: string; restored: boolean }>
        summary: { restoreCount: number; overwriteCount: number; missingCurrentCount: number }
        effects: { database: string }
      }

      expect(restoreHandled).toBe(true)
      expect(restoreResponse.getStatus()).toBe(200)
      expect(restorePayload.dryRun).toBe(true)
      expect(restorePayload.restorePlan.find((target) => target.path === chatDbPath)?.restored).toBe(false)
      expect(restorePayload.summary.restoreCount).toBeGreaterThan(0)
      expect(restorePayload.summary.overwriteCount).toBe(1)
      expect(restorePayload.summary.missingCurrentCount).toBe(restorePayload.summary.restoreCount - 1)
      expect(restorePayload.effects.database).toBe('will_restore')
      expect(fs.readFileSync(chatDbPath, 'utf8')).toBe('mutated-version')
    } finally {
      fs.rmSync(projectRoot, { recursive: true, force: true })
    }
  })

  it('rejects backup restore when a managed target parent is replaced by a symlink', async () => {
    const projectRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-project-root-'))
    const outsideRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-restore-outside-'))
    const electronRoot = path.join(projectRoot, 'electron')
    const dataDir = path.join(projectRoot, 'python/data')
    const chatDbPath = path.join(dataDir, 'chat.db')

    try {
      fs.mkdirSync(electronRoot, { recursive: true })
      fs.mkdirSync(dataDir, { recursive: true })
      fs.writeFileSync(chatDbPath, 'snapshot-version', 'utf8')
      process.env['YUIZAKI_ELECTRON_ROOT'] = electronRoot

      const { handleSystemRoutes } = await import('../http/routes/system-routes')
      const createResponse = createJsonResponse()
      await handleSystemRoutes(
        createJsonRequest({}),
        createResponse.response,
        'POST',
        new URL('http://127.0.0.1:38945/api/system/backup/create'),
        {} as HttpRouteContext,
      )
      const createPayload = createResponse.getJson() as { backupDir: string }

      fs.rmSync(dataDir, { recursive: true, force: true })
      fs.writeFileSync(path.join(outsideRoot, 'chat.db'), 'outside-version', 'utf8')
      try {
        fs.symlinkSync(outsideRoot, dataDir, process.platform === 'win32' ? 'junction' : 'dir')
      } catch {
        return
      }

      const restoreResponse = createJsonResponse()
      const restoreHandled = await handleSystemRoutes(
        createJsonRequest({ backupDir: createPayload.backupDir, dryRun: false }),
        restoreResponse.response,
        'POST',
        new URL('http://127.0.0.1:38945/api/system/backup/restore'),
        {} as HttpRouteContext,
      )

      expect(restoreHandled).toBe(true)
      expect(restoreResponse.getStatus()).toBe(403)
      expect((restoreResponse.getJson() as { error: string }).error).toContain('symbolic link')
      expect(fs.readFileSync(path.join(outsideRoot, 'chat.db'), 'utf8')).toBe('outside-version')
    } finally {
      fs.rmSync(projectRoot, { recursive: true, force: true })
      fs.rmSync(outsideRoot, { recursive: true, force: true })
    }
  })

  it('passes only the backend API token when proxying Python', async () => {
    const { handleSystemRoutes } = await import('../http/routes/system-routes')
    const { response, getStatus, getJson } = createJsonResponse()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      status: 200,
      text: vi.fn().mockResolvedValue('{"ok":true}'),
    }))

    const handled = await handleSystemRoutes(
      createJsonRequest({}, { 'x-trace-id': 'trace-system-test' }),
      response,
      'POST',
      new URL('http://127.0.0.1:38945/api/summary/session-1/rewrite'),
      {
        backendApiToken: 'backend-token',
      } as HttpRouteContext,
    )

    expect(handled).toBe(true)
    expect(getStatus()).toBe(200)
    expect(getJson()).toEqual({ ok: true })
    expect(fetch).toHaveBeenCalledWith(
      `${expectedBackendOrigin()}/api/summary/session-1/rewrite`,
      expect.objectContaining({
        headers: expect.objectContaining({
          'x-yuizaki-backend-token': 'backend-token',
          'x-trace-id': 'trace-system-test',
        }),
      }),
    )
    const [, requestInit] = vi.mocked(fetch).mock.calls[0]
    expect(requestInit?.headers).not.toHaveProperty('Authorization')
    expect(requestInit?.headers).not.toHaveProperty('x-yuizaki-admin-token')
  })

  it('returns backend API token status from the local token store', async () => {
    const { handleSystemRoutes } = await import('../http/routes/system-routes')
    const backendApiTokenStore = createBackendApiTokenStoreMock()
    const { response, getStatus, getJson } = createJsonResponse()

    const handled = await handleSystemRoutes(
      createJsonRequest({}),
      response,
      'GET',
      new URL('http://127.0.0.1:38945/api/system/backend-token'),
      { backendApiTokenStore } as unknown as HttpRouteContext,
    )

    expect(handled).toBe(true)
    expect(getStatus()).toBe(200)
    expect(getJson()).toEqual({
      hasToken: true,
      source: 'stored',
      tokenPreview: 'active...oken',
      storedTokenPreview: 'active...oken',
      requiresRestart: false,
    })
    expect(backendApiTokenStore.getBackendApiTokenStatus).toHaveBeenCalledTimes(1)
  })

  it('saves backend API tokens through the local token store', async () => {
    const { handleSystemRoutes } = await import('../http/routes/system-routes')
    const backendApiTokenStore = createBackendApiTokenStoreMock()
    const { response, getStatus, getJson } = createJsonResponse()

    const handled = await handleSystemRoutes(
      createJsonRequest({ token: 'new-backend-token' }),
      response,
      'POST',
      new URL('http://127.0.0.1:38945/api/system/backend-token'),
      { backendApiTokenStore } as unknown as HttpRouteContext,
    )

    expect(handled).toBe(true)
    expect(getStatus()).toBe(200)
    expect(getJson()).toEqual({
      ok: true,
      hasToken: true,
      source: 'stored',
      tokenPreview: 'saved...oken',
      requiresRestart: true,
    })
    expect(backendApiTokenStore.setBackendApiToken).toHaveBeenCalledWith('new-backend-token')
  })

  it('rejects empty backend API tokens with a bounded error', async () => {
    const { handleSystemRoutes } = await import('../http/routes/system-routes')
    const backendApiTokenStore = createBackendApiTokenStoreMock({
      setBackendApiToken: vi.fn(() => {
        throw new Error('Backend API token cannot be empty')
      }),
    })
    const { response, getStatus, getJson } = createJsonResponse()

    const handled = await handleSystemRoutes(
      createJsonRequest({ token: '   ' }),
      response,
      'POST',
      new URL('http://127.0.0.1:38945/api/system/backend-token'),
      { backendApiTokenStore } as unknown as HttpRouteContext,
    )

    expect(handled).toBe(true)
    expect(getStatus()).toBe(400)
    expect(getJson()).toEqual({
      ok: false,
      error: 'Backend API token cannot be empty',
    })
  })

  it('resets backend API tokens through the local token store', async () => {
    const { handleSystemRoutes } = await import('../http/routes/system-routes')
    const backendApiTokenStore = createBackendApiTokenStoreMock()
    const { response, getStatus, getJson } = createJsonResponse()

    const handled = await handleSystemRoutes(
      createJsonRequest({}),
      response,
      'DELETE',
      new URL('http://127.0.0.1:38945/api/system/backend-token'),
      { backendApiTokenStore } as unknown as HttpRouteContext,
    )

    expect(handled).toBe(true)
    expect(getStatus()).toBe(200)
    expect(getJson()).toEqual({
      ok: true,
      hasToken: true,
      source: 'generated',
      tokenPreview: 'next...oken',
      requiresRestart: true,
    })
    expect(backendApiTokenStore.resetBackendApiToken).toHaveBeenCalledTimes(1)
  })

  it('persists imported skills in the local control service', async () => {
    const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-imported-skills-'))
    vi.mocked(app.getPath).mockReturnValue(userDataDir)

    try {
      const { handleSystemRoutes } = await import('../http/routes/system-routes')
      const saveResponse = createJsonResponse()
      const handledSave = await handleSystemRoutes(
        createJsonRequest({
          items: [
            {
              id: 'voice-dialogue-chain',
              name: 'Voice Dialogue Chain',
              description: 'ASR input, LLM reply and Genie TTS output.',
              category: '语音链路',
              source: 'external',
              status: 'planned',
              fit: 'high',
              installed: false,
              enabled_codex: false,
              tags: ['ASR', 'LLM', 'TTS', 'ASR'],
            },
          ],
        }),
        saveResponse.response,
        'PUT',
        new URL('http://127.0.0.1:38945/api/system/skills/imported'),
        {} as HttpRouteContext,
      )
      const saved = saveResponse.getJson() as { items: Array<Record<string, unknown>>; summary: Record<string, unknown> }

      expect(handledSave).toBe(true)
      expect(saveResponse.getStatus()).toBe(200)
      expect(saved.items).toEqual([
        expect.objectContaining({
          id: 'voice-dialogue-chain',
          name: 'Voice Dialogue Chain',
          description: 'ASR input, LLM reply and Genie TTS output.',
          category: '语音链路',
          source: 'imported',
          status: 'built-in',
          fit: 'high',
          installed: true,
          enabled_codex: true,
          tags: ['ASR', 'LLM', 'TTS'],
        }),
      ])
      expect(saved.summary).toEqual(expect.objectContaining({
        total: 1,
        built_in: 1,
        ready: 1,
        high_fit: 1,
      }))
      expect(fs.existsSync(path.join(userDataDir, 'skills', 'imported-skills.json'))).toBe(true)

      const readResponse = createJsonResponse()
      const handledRead = await handleSystemRoutes(
        createJsonRequest({}),
        readResponse.response,
        'GET',
        new URL('http://127.0.0.1:38945/api/system/skills/imported'),
        {} as HttpRouteContext,
      )

      expect(handledRead).toBe(true)
      expect(readResponse.getStatus()).toBe(200)
      expect(readResponse.getJson()).toEqual(saved)
    } finally {
      fs.rmSync(userDataDir, { recursive: true, force: true })
    }
  })

  it('deletes only selected imported skills by id', async () => {
    const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-imported-skills-delete-'))
    vi.mocked(app.getPath).mockReturnValue(userDataDir)

    try {
      const { handleSystemRoutes } = await import('../http/routes/system-routes')
      await handleSystemRoutes(
        createJsonRequest({
          items: [
            { id: 'skill-a', name: 'Skill A', description: 'A', category: '通用', fit: 'medium' },
            { id: 'skill-b', name: 'Skill B', description: 'B', category: '通用', fit: 'medium' },
          ],
        }),
        createJsonResponse().response,
        'PUT',
        new URL('http://127.0.0.1:38945/api/system/skills/imported'),
        {} as HttpRouteContext,
      )

      const deleteResponse = createJsonResponse()
      const handledDelete = await handleSystemRoutes(
        createJsonRequest({ ids: ['skill-a'] }),
        deleteResponse.response,
        'DELETE',
        new URL('http://127.0.0.1:38945/api/system/skills/imported'),
        {} as HttpRouteContext,
      )
      const deleted = deleteResponse.getJson() as { ok: boolean; removed: number; items: Array<{ id: string }> }

      expect(handledDelete).toBe(true)
      expect(deleteResponse.getStatus()).toBe(200)
      expect(deleted.ok).toBe(true)
      expect(deleted.removed).toBe(1)
      expect(deleted.items.map((item) => item.id)).toEqual(['skill-b'])

      const readResponse = createJsonResponse()
      await handleSystemRoutes(
        createJsonRequest({}),
        readResponse.response,
        'GET',
        new URL('http://127.0.0.1:38945/api/system/skills/imported'),
        {} as HttpRouteContext,
      )

      expect((readResponse.getJson() as { items: Array<{ id: string }> }).items.map((item) => item.id)).toEqual(['skill-b'])
    } finally {
      fs.rmSync(userDataDir, { recursive: true, force: true })
    }
  })

  it('proxies exported data downloads without JSON wrapping', async () => {
    const { handleSystemRoutes } = await import('../http/routes/system-routes')
    const csv = 'session_id,total\ns1,2\n'
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      status: 200,
      headers: new Headers({
        'Content-Type': 'text/csv',
        'Content-Disposition': 'attachment; filename=chat_history.csv',
      }),
      arrayBuffer: vi.fn().mockResolvedValue(new TextEncoder().encode(csv).buffer),
    }))
    const { response, getStatus, getText, getHeader } = createJsonResponse()

    const handled = await handleSystemRoutes(
      createJsonRequest({}, { 'x-trace-id': 'trace-export-test' }),
      response,
      'POST',
      new URL('http://127.0.0.1:38945/api/export/csv'),
      {
        backendApiToken: 'backend-token',
      } as HttpRouteContext,
    )

    expect(handled).toBe(true)
    expect(getStatus()).toBe(200)
    expect(getText()).toBe(csv)
    expect(getHeader('Content-Type')).toBe('text/csv')
    expect(getHeader('Content-Disposition')).toBe('attachment; filename=chat_history.csv')
    expect(fetch).toHaveBeenCalledWith(
      `${expectedBackendOrigin()}/api/export/csv`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({}),
        headers: expect.objectContaining({
          'Content-Type': 'application/json',
          'x-yuizaki-backend-token': 'backend-token',
          'x-trace-id': 'trace-export-test',
        }),
      }),
    )
  })

  it('proxies advanced panel JSON endpoints through the control server', async () => {
    const { handleSystemRoutes } = await import('../http/routes/system-routes')
    vi.stubGlobal('fetch', vi.fn((_url: string) => Promise.resolve({
      status: 200,
      text: vi.fn().mockResolvedValue('{"ok":true}'),
    })))

    const proxiedPaths = [
      '/api/ping',
      '/health',
      '/api/readiness',
      '/memory/docs?scope=workspace',
      '/memory/docs/doc-1',
      '/memory/overview?scope=workspace',
      '/memory/query',
      '/memory/index/status',
      '/memory/memory/add',
      '/memory/rag/query',
      '/memory/maintenance/preview',
      '/memory/maintenance/apply',
      '/api/memory/pipeline/query?query=hello',
      '/api/companions',
      '/api/companions/default',
      '/api/companions/default/relationship-history?limit=5',
      '/api/chat/translate',
      '/api/history/default-session?limit=50',
      '/api/i18n/locales',
      '/api/i18n/messages',
      '/api/i18n/message/common.save',
      '/api/summary',
      '/api/summary/default-session',
      '/api/summary/audit',
      '/api/summary/report/json?days=7',
      '/api/settings/',
      '/api/settings/metadata',
      '/api/settings/history',
      '/api/settings/system.theme',
      '/api/system/capabilities',
      '/api/system/orchestration',
      '/api/system/experience-metrics',
      '/api/system/product-metrics/consent',
      '/api/system/companion-runtime?limit=4',
      '/api/system/heartbeat',
      '/api/system/active-workspace',
      '/api/system/proactive/settings',
      '/api/system/activity-frames',
      '/api/workspaces',
      '/api/sessions',
      '/api/workspaces/default',
      '/api/workspaces/default/sessions',
      '/api/sessions/default-session',
      '/system/status',
      '/api/database/stats',
      '/api/statistics',
      '/api/statistics/update',
      '/v1/models',
      '/api/workspaces/default/effective-preset',
    ]

    for (const pathName of proxiedPaths) {
      const { response, getStatus, getJson } = createJsonResponse()
      const handled = await handleSystemRoutes(
        createJsonRequest({}),
        response,
        'GET',
        new URL(`http://127.0.0.1:38945${pathName}`),
        {
          providerCredentialStore: {
            captureSettingsPayload: vi.fn(),
            captureSettingValue: vi.fn(),
            delete: vi.fn(),
          },
        } as HttpRouteContext,
      )

      expect(handled).toBe(true)
      expect(getStatus()).toBe(200)
      expect(getJson()).toEqual({ ok: true })
    }

    expect(fetch).toHaveBeenCalledWith(
      `${expectedBackendOrigin()}/api/ping`,
      expect.objectContaining({
        method: 'GET',
        headers: expect.objectContaining({ Connection: 'close' }),
      }),
    )
    expect(fetch).toHaveBeenCalledWith(
      `${expectedBackendOrigin()}/health`,
      expect.objectContaining({ method: 'GET' }),
    )
    expect(fetch).toHaveBeenCalledWith(
      `${expectedBackendOrigin()}/api/readiness`,
      expect.objectContaining({ method: 'GET' }),
    )
    expect(fetch).toHaveBeenCalledWith(
      `${expectedBackendOrigin()}/memory/docs?scope=workspace`,
      expect.objectContaining({ method: 'GET' }),
    )
    expect(fetch).toHaveBeenCalledWith(
      `${expectedBackendOrigin()}/api/memory/pipeline/query?query=hello`,
      expect.objectContaining({ method: 'GET' }),
    )
    expect(fetch).toHaveBeenCalledWith(
      `${expectedBackendOrigin()}/api/companions`,
      expect.objectContaining({ method: 'GET' }),
    )
    expect(fetch).toHaveBeenCalledWith(
      `${expectedBackendOrigin()}/api/companions/default/relationship-history?limit=5`,
      expect.objectContaining({ method: 'GET' }),
    )
    expect(fetch).toHaveBeenCalledWith(
      `${expectedBackendOrigin()}/api/i18n/locales`,
      expect.objectContaining({ method: 'GET' }),
    )
    expect(fetch).toHaveBeenCalledWith(
      `${expectedBackendOrigin()}/api/summary/report/json?days=7`,
      expect.objectContaining({ method: 'GET' }),
    )
    expect(fetch).toHaveBeenCalledWith(
      `${expectedBackendOrigin()}/api/system/capabilities`,
      expect.objectContaining({ method: 'GET' }),
    )
    expect(fetch).toHaveBeenCalledWith(
      `${expectedBackendOrigin()}/api/system/orchestration`,
      expect.objectContaining({ method: 'GET' }),
    )
    expect(fetch).toHaveBeenCalledWith(
      `${expectedBackendOrigin()}/api/system/companion-runtime?limit=4`,
      expect.objectContaining({ method: 'GET' }),
    )
    expect(fetch).toHaveBeenCalledWith(
      `${expectedBackendOrigin()}/api/workspaces`,
      expect.objectContaining({ method: 'GET' }),
    )
    expect(fetch).toHaveBeenCalledWith(
      `${expectedBackendOrigin()}/api/workspaces/default/effective-preset`,
      expect.objectContaining({ method: 'GET' }),
    )
  })

  it('proxies advanced panel mutation endpoints through the control server with method and body', async () => {
    const { handleSystemRoutes } = await import('../http/routes/system-routes')
    vi.stubGlobal('fetch', vi.fn((_url: string) => Promise.resolve({
      status: 200,
      text: vi.fn().mockResolvedValue('{"ok":true}'),
    })))

    const mutationCases = [
      { method: 'POST', pathName: '/api/i18n/locale?locale=zh-CN', body: { locale: 'zh-CN' } },
      { method: 'PATCH', pathName: '/api/settings/', body: { llm: { provider: 'openai-compatible' } } },
      { method: 'POST', pathName: '/api/settings/import', body: { llm: { model: 'test-model' } } },
      { method: 'POST', pathName: '/api/settings/test/llm', body: { prompt: 'ping' } },
      { method: 'POST', pathName: '/api/settings/llm/models', body: { base_url: 'http://127.0.0.1:9999', api_key: 'token' } },
      { method: 'POST', pathName: '/api/settings/test/tts', body: {} },
      { method: 'POST', pathName: '/memory/index/rebuild', body: {} },
      { method: 'POST', pathName: '/api/settings/rollback?steps=1', body: {} },
      { method: 'POST', pathName: '/api/settings/system.theme', body: 'dark' },
      { method: 'DELETE', pathName: '/api/settings/system.theme' },
      { method: 'DELETE', pathName: '/api/settings/history' },
      { method: 'POST', pathName: '/api/summary/alerts/ack?key=slow_summary', body: { key: 'slow_summary' } },
      { method: 'POST', pathName: '/api/summary/alerts/snooze?key=slow_summary&minutes=30', body: { key: 'slow_summary', minutes: 30 } },
      { method: 'POST', pathName: '/api/summary/alerts/clear', body: {} },
      { method: 'DELETE', pathName: '/api/system/permissions/tool.read_file' },
      { method: 'DELETE', pathName: '/api/system/permissions' },
      { method: 'POST', pathName: '/api/system/mcp/fetch/toggle', body: { enabled: true } },
      { method: 'POST', pathName: '/api/system/mcp', body: { name: 'fetch', transport: 'http', base_url: 'http://127.0.0.1:7777', enabled: true } },
      { method: 'POST', pathName: '/api/system/mcp/presets/fetch/install', body: {} },
      { method: 'DELETE', pathName: '/api/system/mcp/fetch' },
      { method: 'POST', pathName: '/api/system/mcp/fetch/refresh', body: {} },
      { method: 'POST', pathName: '/api/system/agent-plugins/memory/toggle', body: { enabled: false } },
      { method: 'POST', pathName: '/api/system/agent-plugins/memory/config', body: { memory: true } },
      { method: 'POST', pathName: '/api/system/schedules/once', body: { name: 'test', prompt: 'ping', run_after_seconds: 5 } },
      { method: 'POST', pathName: '/api/system/schedules/interval', body: { name: 'test', prompt: 'ping', interval_seconds: 60 } },
      { method: 'DELETE', pathName: '/api/system/schedules/task-1' },
      { method: 'POST', pathName: '/api/system/schedules/task-1/toggle', body: { enabled: false } },
      { method: 'POST', pathName: '/api/system/schedules/task-1/run', body: {} },
      {
        method: 'POST',
        pathName: '/api/agent/recovery/resume',
        body: {
          recovery_handle: 'recovery-handle-1',
          workspace_id: 'default',
          session_id: 'session-1',
          turn_id: 'turn-1',
          failed_step_id: 'step-2',
        },
      },
      { method: 'POST', pathName: '/api/system/active-workspace', body: { workspace_id: 'default' } },
      { method: 'PATCH', pathName: '/api/system/proactive/settings', body: { expectedRevision: 1, dnd: true } },
      { method: 'PATCH', pathName: '/api/system/product-metrics/consent', body: { consented: true } },
      { method: 'POST', pathName: '/api/system/proactive/feedback', body: { feedbackId: 'f1', jobId: 'j1', requestId: 'r1', sourceKind: 'completed_turn_followup', kind: 'useful' } },
      { method: 'POST', pathName: '/api/system/companion-runtime/opportunities/outcome/job-1', body: { request_id: 'r1', outcome: 'delivered' } },
      { method: 'POST', pathName: '/api/system/heartbeat/opportunities/job%2F1/accept', body: { request_id: 'r1' } },
      { method: 'POST', pathName: '/api/system/heartbeat/goals/goal%2F1/cancel', body: { reason: 'user_cancelled' } },
      { method: 'DELETE', pathName: '/api/system/activity-frames/frame%2F1' },
    ]

    for (const item of mutationCases) {
      const { response, getStatus, getJson } = createJsonResponse()
      const handled = await handleSystemRoutes(
        createJsonRequest(item.body ?? {}),
        response,
        item.method,
        new URL(`http://127.0.0.1:38945${item.pathName}`),
        {
        } as HttpRouteContext,
      )

      expect(handled).toBe(true)
      expect(getStatus()).toBe(200)
      expect(getJson()).toEqual({ ok: true })
    }

    for (const item of mutationCases) {
      const expectedUrl = `${expectedBackendOrigin()}${item.pathName}`
      const expectedInit = item.method === 'GET' || item.method === 'DELETE'
        ? expect.objectContaining({ method: item.method })
        : expect.objectContaining({
          method: item.method,
          body: JSON.stringify(item.body ?? {}),
        })
      expect(fetch).toHaveBeenCalledWith(expectedUrl, expectedInit)
    }
  })

  it('does not expose the administrative activity-frame rebuild route', async () => {
    const { handleSystemRoutes } = await import('../http/routes/system-routes')
    const { response } = createJsonResponse()
    const handled = await handleSystemRoutes(
      createJsonRequest({}),
      response,
      'POST',
      new URL('http://127.0.0.1:38945/api/system/activity-frames/rebuild'),
      {} as HttpRouteContext,
    )
    expect(handled).toBe(false)
  })

  it('proxies provider, platform, connector config and delivery operations', async () => {
    const { handleSystemRoutes } = await import('../http/routes/system-routes')
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })))
    const cases = [
      { method: 'GET', pathName: '/api/system/providers' },
      { method: 'GET', pathName: '/api/system/platforms' },
      { method: 'GET', pathName: '/api/system/connectors' },
      { method: 'GET', pathName: '/api/system/connectors/qq/config' },
      { method: 'PUT', pathName: '/api/system/connectors/wechat/config', body: { enabled: false } },
      { method: 'GET', pathName: '/api/system/connectors/telegram/deliveries?limit=20' },
      { method: 'POST', pathName: '/api/system/connectors/telegram/deliveries/connector%3Atelegram%3Aevent-1/retry', body: {} },
    ]

    for (const item of cases) {
      const { response, getStatus } = createJsonResponse()
      const handled = await handleSystemRoutes(
        createJsonRequest(item.body ?? {}),
        response,
        item.method,
        new URL(`http://127.0.0.1:38945${item.pathName}`),
        {} as HttpRouteContext,
      )
      expect(handled).toBe(true)
      expect(getStatus()).toBe(200)
    }
  })

  it('returns a bounded JSON error when proxied Python requests time out', async () => {
    vi.useFakeTimers()
    try {
      const { handleSystemRoutes } = await import('../http/routes/system-routes')
      const { response, getStatus, getJson } = createJsonResponse()
      vi.stubGlobal('fetch', vi.fn((_url: string, init?: RequestInit) => new Promise((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })))
      })))

      const handledPromise = handleSystemRoutes(
        createJsonRequest({}, { 'x-trace-id': 'trace-timeout-test' }),
        response,
        'GET',
        new URL('http://127.0.0.1:38945/api/system/mcp'),
        {
        } as HttpRouteContext,
      )

      await vi.advanceTimersByTimeAsync(12000)
      const handled = await handledPromise

      expect(handled).toBe(true)
      expect(getStatus()).toBe(504)
      expect(getJson()).toEqual(expect.objectContaining({
        error: 'Python backend request timed out',
        path: '/api/system/mcp',
      }))
    } finally {
      vi.useRealTimers()
    }
  })

  it('reports the effective Python API origin for renderer runtime handshakes', async () => {
    const { handleSystemRoutes } = await import('../http/routes/system-routes')
    const { response, getStatus, getJson } = createJsonResponse()
    process.env['DESKTOP_PET_BACKEND_URL'] = 'http://localhost:8011'

    try {
      const handled = await handleSystemRoutes(
        createJsonRequest({}),
        response,
        'GET',
        new URL('http://127.0.0.1:38945/api/system/env-check'),
        {} as HttpRouteContext,
      )

      expect(handled).toBe(true)
      expect(getStatus()).toBe(200)
      expect(getJson()).toEqual(expect.objectContaining({
        status: 'ok',
        pythonApiOrigin: 'http://localhost:8011',
      }))
    } finally {
      delete process.env['DESKTOP_PET_BACKEND_URL']
    }
  })

  it('includes the rendered pet alpha visibility scan in diagnostics', async () => {
    const { handleSystemRoutes } = await import('../http/routes/system-routes')
    const { response, getStatus, getJson } = createJsonResponse()

    const handled = await handleSystemRoutes(
      createJsonRequest({}),
      response,
      'GET',
      new URL('http://127.0.0.1:38945/api/system/diagnostics'),
      {
        pluginRegistry: {
          snapshot: () => ({
            plugins: [],
            loadFailures: [],
            pluginStates: [],
          }),
        },
        petWindow: { window: { isVisible: () => false } },
        live2dWindow: {
          window: { isVisible: () => true },
          getBounds: () => ({ x: 0, y: 0, width: 1280, height: 720 }),
          hasVisiblePixels: vi.fn(async () => true),
        },
        petStateStore: {
          getState: () => ({ modelId: 'llm-live2d/yumi', visible: true }),
        },
      } as unknown as HttpRouteContext,
    )

    expect(handled).toBe(true)
    expect(getStatus()).toBe(200)
    expect(getJson()).toEqual(expect.objectContaining({
      petOverlayVisible: true,
      petOverlayHasVisiblePixels: true,
      petBounds: { x: 0, y: 0, width: 1280, height: 720 },
    }))
  })

  it('reads only bounded tails for system logs', async () => {
    const projectRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-project-root-'))
    const electronRoot = path.join(projectRoot, 'electron')

    try {
      fs.mkdirSync(electronRoot, { recursive: true })
      fs.mkdirSync(path.join(projectRoot, 'logs/dev'), { recursive: true })
      fs.mkdirSync(path.join(projectRoot, 'logs/prod'), { recursive: true })
      fs.writeFileSync(path.join(electronRoot, 'live2d-renderer.log'), `${'a'.repeat(9000)}renderer-tail`, 'utf8')
      fs.writeFileSync(path.join(projectRoot, 'logs/dev/python.log'), `${'b'.repeat(9000)}python-tail`, 'utf8')
      fs.writeFileSync(path.join(projectRoot, 'logs/dev/electron.log'), `${'c'.repeat(9000)}electron-tail`, 'utf8')
      process.env['YUIZAKI_ELECTRON_ROOT'] = electronRoot
      const readFileSyncSpy = vi.spyOn(fs, 'readFileSync')

      const { handleSystemRoutes } = await import('../http/routes/system-routes')
      const { response, getStatus, getJson } = createJsonResponse()

      const handled = await handleSystemRoutes(
        createJsonRequest({}),
        response,
        'GET',
        new URL('http://127.0.0.1:38945/api/system/logs'),
        {
          pluginRegistry: { getAuditLog: () => [] },
        } as unknown as HttpRouteContext,
      )

      const payload = getJson() as { logs: { renderer: string; python: string; electron: string } }
      expect(handled).toBe(true)
      expect(getStatus()).toBe(200)
      expect(payload.logs.renderer).toHaveLength(8000)
      expect(payload.logs.renderer.endsWith('renderer-tail')).toBe(true)
      expect(payload.logs.python.endsWith('python-tail')).toBe(true)
      expect(payload.logs.electron.endsWith('electron-tail')).toBe(true)
      expect(readFileSyncSpy).not.toHaveBeenCalled()
      readFileSyncSpy.mockRestore()
    } finally {
      fs.rmSync(projectRoot, { recursive: true, force: true })
    }
  })
})
