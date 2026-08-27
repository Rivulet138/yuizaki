import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import fs from 'node:fs'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)
const electronRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')
const repositoryRoot = path.resolve(electronRoot, '..')
const pythonRoot = path.join(repositoryRoot, 'python')
const { PythonService } = require('../../dist/main/python.js')

const waitUntil = async (predicate, timeoutMs = 30_000) => {
  const deadline = Date.now() + timeoutMs
  let lastError = null
  while (Date.now() < deadline) {
    try {
      const value = await predicate()
      if (value) return value
    } catch (error) {
      lastError = error
    }
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
  throw lastError ?? new Error('condition did not become true before timeout')
}

const closeServer = (server) => new Promise((resolve, reject) => {
  server.close((error) => error ? reject(error) : resolve())
})

const fetchPing = async (port) => {
  const response = await fetch(`http://127.0.0.1:${port}/api/ping`, {
    signal: AbortSignal.timeout(2_000),
  })
  assert.equal(response.ok, true)
  return response.json()
}

test('real Python runtime rejects stale health, recovers once, and stops cleanly', {
  timeout: 90_000,
}, async () => {
  const tempDirectory = fs.mkdtempSync(path.join(os.tmpdir(), 'yuizaki-runtime-smoke-'))
  const dataDirectory = path.join(tempDirectory, 'data')
  const audioDirectory = path.join(tempDirectory, 'audio')
  const settingsPath = path.join(tempDirectory, 'settings.json')
  const chatDatabasePath = path.join(dataDirectory, 'chat.db')
  const memoryDatabasePath = path.join(dataDirectory, 'memory.db')
  const smokeEnvFile = path.join(tempDirectory, 'runtime.env')
  const isolatedEnvironment = {
    YUIZAKI_DATA_DIR: dataDirectory,
    YUIZAKI_SETTINGS_PATH: settingsPath,
    DATABASE_URL: `sqlite:///${chatDatabasePath.replaceAll('\\', '/')}`,
    MEMORY_BACKEND: 'sqlite',
    MEMORY_SQLITE_PATH: memoryDatabasePath,
    AUDIO_CACHE_DIR: audioDirectory,
    APP_ENV: 'test',
    SCHEMA_MIGRATION_MODE: 'bootstrap',
    QDRANT_URL: '',
    QDRANT_API_KEY: '',
    QDRANT_AUTO_START: '0',
    LLM_PROVIDER: 'custom',
    LLM_BASE_URL: '',
    LLM_API_KEY: '',
    LLM_MODEL: '',
    VISION_LLM_ENABLED: '0',
    VISION_LLM_BASE_URL: '',
    VISION_LLM_API_KEY: '',
    TTS_BASE_URL: '',
    TTS_API_KEY: '',
    ASR_BASE_URL: '',
    ASR_API_KEY: '',
  }
  fs.writeFileSync(smokeEnvFile, [
    ...Object.entries(isolatedEnvironment).map(([key, value]) => (
      `${key}=${value.replaceAll('\\', '/')}`
    )),
    '',
  ].join('\n'))
  const staleServer = http.createServer((_request, response) => {
    response.writeHead(200, { 'content-type': 'application/json' })
    response.end('{"ok":true}')
  })
  await new Promise((resolve, reject) => {
    staleServer.once('error', reject)
    staleServer.listen(0, '127.0.0.1', resolve)
  })
  const address = staleServer.address()
  assert.ok(address && typeof address !== 'string')
  const port = address.port

  const managedEnvironment = [
    'DESKTOP_PET_BACKEND_URL',
    'DESKTOP_PET_SKIP_INTERNAL_PYTHON',
    'SERVER_HOST',
    'SERVER_PORT',
    'YUIZAKI_PYTHON_DIR',
    'NO_PROXY',
    'no_proxy',
  ]
  const previousEnvironment = new Map(managedEnvironment.map((key) => [key, process.env[key]]))
  delete process.env['DESKTOP_PET_BACKEND_URL']
  delete process.env['DESKTOP_PET_SKIP_INTERNAL_PYTHON']
  process.env['SERVER_HOST'] = '127.0.0.1'
  process.env['SERVER_PORT'] = String(port)
  process.env['YUIZAKI_PYTHON_DIR'] = pythonRoot
  process.env['NO_PROXY'] = '127.0.0.1,localhost'
  process.env['no_proxy'] = '127.0.0.1,localhost'

  const service = new PythonService('', isolatedEnvironment, '', '', {
    maxAttempts: 2,
    baseDelayMs: 100,
    startupMaxAttempts: 100,
    startupRetryDelayMs: 100,
    pythonEnvFile: smokeEnvFile,
    logOutput: false,
  })

  try {
    await assert.rejects(
      service.start(),
      /exited before becoming healthy|process error|failed to start after retries/i,
    )
    assert.notEqual(service.getStatus().state, 'running')
    await service.stop()
    await closeServer(staleServer)

    await service.start()
    const firstStatus = service.getStatus()
    assert.equal(firstStatus.state, 'running')
    assert.equal(fs.existsSync(chatDatabasePath), true)
    assert.equal(fs.existsSync(memoryDatabasePath), true)
    assert.match(firstStatus.instanceId ?? '', /^[0-9a-f-]{36}$/i)
    assert.ok((firstStatus.pid ?? 0) > 0)
    const firstPing = await fetchPing(port)
    assert.equal(firstPing.runtime?.instance_id, firstStatus.instanceId)
    assert.ok(Number(firstPing.runtime?.pid) > 0)

    process.kill(firstStatus.pid, 'SIGKILL')
    const recoveredStatus = await waitUntil(async () => {
      const status = service.getStatus()
      if (
        status.state !== 'running'
        || status.instanceId === null
        || status.instanceId === firstStatus.instanceId
      ) return null
      const ping = await fetchPing(port)
      return ping.runtime?.instance_id === status.instanceId ? status : null
    })
    assert.notEqual(recoveredStatus.instanceId, firstStatus.instanceId)
    assert.notEqual(recoveredStatus.pid, firstStatus.pid)

    await service.stop()
    assert.equal(service.getStatus().state, 'idle')
    await new Promise((resolve) => setTimeout(resolve, 500))
    await assert.rejects(fetchPing(port))
    assert.equal(service.getStatus().state, 'idle')
  } finally {
    await service.stop().catch(() => undefined)
    if (staleServer.listening) await closeServer(staleServer).catch(() => undefined)
    for (const [key, value] of previousEnvironment) {
      if (value === undefined) delete process.env[key]
      else process.env[key] = value
    }
    fs.rmSync(tempDirectory, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 })
  }
})
