import { EventEmitter } from 'node:events'
import fs from 'node:fs'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const spawnMock = vi.hoisted(() => vi.fn())
const axiosGetMock = vi.hoisted(() => vi.fn())

vi.mock('child_process', () => ({
  spawn: spawnMock,
  default: {
    spawn: spawnMock,
  },
}))

vi.mock('axios', () => ({
  default: {
    get: axiosGetMock,
  },
}))

const createChildProcess = () => {
  const child = new EventEmitter() as EventEmitter & {
    stdout: EventEmitter
    stderr: EventEmitter
    kill: ReturnType<typeof vi.fn>
  }
  child.stdout = new EventEmitter()
  child.stderr = new EventEmitter()
  child.kill = vi.fn()
  return child
}

describe('PythonService', () => {
  const clearBackendEnv = () => {
    delete process.env['DESKTOP_PET_BACKEND_URL']
    delete process.env['DESKTOP_PET_SKIP_INTERNAL_PYTHON']
    delete process.env['SERVER_HOST']
    delete process.env['SERVER_PORT']
    delete process.env['YUIZAKI_BACKEND_API_TOKEN']
  }

  beforeEach(() => {
    clearBackendEnv()
  })

  afterEach(() => {
    clearBackendEnv()
    spawnMock.mockReset()
    axiosGetMock.mockReset()
    vi.restoreAllMocks()
    vi.resetModules()
  })

  it('starts uvicorn on the configured backend host and port', async () => {
    process.env['SERVER_HOST'] = '127.0.0.1'
    process.env['SERVER_PORT'] = '8123'
    vi.spyOn(fs, 'existsSync').mockReturnValue(true)
    spawnMock.mockReturnValue(createChildProcess())
    axiosGetMock.mockResolvedValue({ data: { status: 'healthy' } })

    const { PythonService } = await import('../python')
    await new PythonService('backend-token').start()

    expect(spawnMock).toHaveBeenCalledWith(
      expect.any(String),
      expect.arrayContaining(['--host', '127.0.0.1', '--port', '8123']),
      expect.objectContaining({
        env: expect.objectContaining({ YUIZAKI_BACKEND_API_TOKEN: 'backend-token' }),
      }),
    )
    expect(axiosGetMock).toHaveBeenCalledWith('http://127.0.0.1:8123/api/ping', expect.any(Object))
  })

  it('normalizes explicit backend health URLs before deriving uvicorn args', async () => {
    process.env['DESKTOP_PET_BACKEND_URL'] = 'http://127.0.0.1:8234/health'
    vi.spyOn(fs, 'existsSync').mockReturnValue(true)
    spawnMock.mockReturnValue(createChildProcess())
    axiosGetMock.mockResolvedValue({ data: { ok: true } })

    const { PythonService } = await import('../python')
    await new PythonService().start()

    expect(spawnMock).toHaveBeenCalledWith(
      expect.any(String),
      expect.arrayContaining(['--host', '127.0.0.1', '--port', '8234']),
      expect.any(Object),
    )
    expect(axiosGetMock).toHaveBeenCalledWith('http://127.0.0.1:8234/api/ping', expect.any(Object))
  })

  it('uses the liveness endpoint when an externally managed backend may be degraded', async () => {
    process.env['DESKTOP_PET_BACKEND_URL'] = 'http://127.0.0.1:8333'
    process.env['DESKTOP_PET_SKIP_INTERNAL_PYTHON'] = '1'
    vi.spyOn(fs, 'existsSync').mockReturnValue(true)
    axiosGetMock.mockResolvedValue({ data: { ok: true } })

    const { PythonService } = await import('../python')
    await new PythonService().start()

    expect(spawnMock).not.toHaveBeenCalled()
    expect(axiosGetMock).toHaveBeenCalledTimes(1)
    expect(axiosGetMock).toHaveBeenCalledWith('http://127.0.0.1:8333/api/ping', expect.any(Object))
  })

  it.each([
    ['an explicit negative response', { data: { ok: false } }],
    ['a malformed response', { data: { status: 'degraded' } }],
  ])('rejects %s from the liveness endpoint', async (_label, response) => {
    vi.spyOn(fs, 'existsSync').mockReturnValue(true)
    axiosGetMock.mockResolvedValue(response)

    const { PythonService } = await import('../python')

    await expect(new PythonService().health()).resolves.toBe(false)
  })

  it('rejects an unreachable liveness endpoint', async () => {
    vi.spyOn(fs, 'existsSync').mockReturnValue(true)
    axiosGetMock.mockRejectedValue(new Error('connection refused'))

    const { PythonService } = await import('../python')

    await expect(new PythonService().health()).resolves.toBe(false)
  })
})
