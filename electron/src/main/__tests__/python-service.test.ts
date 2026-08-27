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

const healthyRuntimeResponse = () => {
  const options = spawnMock.mock.calls.at(-1)?.[2] as {
    env?: Record<string, string | undefined>
  } | undefined
  const env = options?.env
  return {
    data: {
      ok: true,
      runtime: {
        instance_id: env?.['YUIZAKI_RUNTIME_INSTANCE_ID'],
        generation: env?.['YUIZAKI_RUNTIME_GENERATION'],
        startup_nonce: env?.['YUIZAKI_RUNTIME_STARTUP_NONCE'],
      },
    },
  }
}

describe('PythonService', () => {
  const clearBackendEnv = () => {
    delete process.env['DESKTOP_PET_BACKEND_URL']
    delete process.env['DESKTOP_PET_SKIP_INTERNAL_PYTHON']
    delete process.env['SERVER_HOST']
    delete process.env['SERVER_PORT']
    delete process.env['YUIZAKI_BACKEND_API_TOKEN']
    delete process.env['YUIZAKI_HOST_DESKTOP_ACTION_TOKEN']
  }

  beforeEach(() => {
    clearBackendEnv()
  })

  afterEach(() => {
    vi.useRealTimers()
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
    axiosGetMock.mockImplementation(async () => healthyRuntimeResponse())

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

  it('passes the dedicated desktop action token only through the child environment', async () => {
    vi.spyOn(fs, 'existsSync').mockReturnValue(true)
    spawnMock.mockReturnValue(createChildProcess())
    axiosGetMock.mockImplementation(async () => healthyRuntimeResponse())

    const { PythonService } = await import('../python')
    await new PythonService('general-token', {}, 'perception-token', 'desktop-host-token').start()

    const spawnOptions = spawnMock.mock.calls[0]?.[2] as { env?: Record<string, string> }
    expect(spawnOptions.env).toMatchObject({
      YUIZAKI_BACKEND_API_TOKEN: 'general-token',
      YUIZAKI_HOST_PERCEPTION_TOKEN: 'perception-token',
      YUIZAKI_HOST_DESKTOP_ACTION_TOKEN: 'desktop-host-token',
    })
    expect(process.env['YUIZAKI_HOST_DESKTOP_ACTION_TOKEN']).toBeUndefined()
  })

  it('normalizes explicit backend health URLs before deriving uvicorn args', async () => {
    process.env['DESKTOP_PET_BACKEND_URL'] = 'http://127.0.0.1:8234/health'
    vi.spyOn(fs, 'existsSync').mockReturnValue(true)
    spawnMock.mockReturnValue(createChildProcess())
    axiosGetMock.mockImplementation(async () => healthyRuntimeResponse())

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

  it('does not accept status-only health for an internal runtime without an identity', async () => {
    vi.spyOn(fs, 'existsSync').mockReturnValue(true)
    axiosGetMock.mockResolvedValue({ data: { ok: true } })

    const { PythonService } = await import('../python')

    await expect(new PythonService().health()).resolves.toBe(false)
  })

  it('cancels an in-flight start, rejects its stale health result, and allows retry without an orphan', async () => {
    vi.spyOn(fs, 'existsSync').mockReturnValue(true)
    let resolveFirstHealth: ((value: ReturnType<typeof healthyRuntimeResponse>) => void) | undefined
    axiosGetMock.mockImplementationOnce(() => new Promise((resolve) => { resolveFirstHealth = resolve }))
    const firstChild = createChildProcess()
    firstChild.kill.mockImplementation(() => {
      queueMicrotask(() => firstChild.emit('exit', null))
      return true
    })
    const secondChild = createChildProcess()
    spawnMock.mockReturnValueOnce(firstChild).mockReturnValueOnce(secondChild)

    const { PythonService } = await import('../python')
    const service = new PythonService()
    const firstStart = service.start()
    await vi.waitFor(() => expect(spawnMock).toHaveBeenCalledOnce())
    const cancellation = service.cancelStart()
    resolveFirstHealth?.(healthyRuntimeResponse())

    await expect(firstStart).rejects.toThrow(/cancelled/)
    await cancellation
    expect(firstChild.kill).toHaveBeenCalledWith('SIGTERM')
    expect(service.getStatus().state).toBe('cancelled')

    axiosGetMock.mockImplementation(async () => healthyRuntimeResponse())
    await expect(service.start()).resolves.toBeUndefined()
    expect(spawnMock).toHaveBeenCalledTimes(2)
    expect(service.getStatus().state).toBe('running')
  })

  it('restarts an unexpectedly exited process with bounded exponential backoff', async () => {
    vi.useFakeTimers()
    vi.spyOn(fs, 'existsSync').mockReturnValue(true)
    const firstChild = createChildProcess()
    spawnMock
      .mockReturnValueOnce(firstChild)
      .mockImplementation(() => {
        throw new Error('spawn failed')
      })
    axiosGetMock.mockImplementation(async () => healthyRuntimeResponse())

    const { PythonService } = await import('../python')
    const service = new PythonService()
    await service.start()
    firstChild.emit('exit', 1, null)

    expect(service.getStatus().state).toBe('failed')
    await expect(service.health()).resolves.toBe(false)
    await vi.advanceTimersByTimeAsync(999)
    expect(spawnMock).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(spawnMock).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(1999)
    expect(spawnMock).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(1)
    expect(spawnMock).toHaveBeenCalledTimes(3)
    await vi.advanceTimersByTimeAsync(3999)
    expect(spawnMock).toHaveBeenCalledTimes(3)
    await vi.advanceTimersByTimeAsync(1)
    expect(spawnMock).toHaveBeenCalledTimes(4)

    await vi.advanceTimersByTimeAsync(10_000)
    expect(spawnMock).toHaveBeenCalledTimes(4)
    expect(service.getStatus()).toMatchObject({ state: 'failed', error: 'spawn failed' })
  })

  it('requires the current spawned runtime identity before reporting running', async () => {
    vi.spyOn(fs, 'existsSync').mockReturnValue(true)
    const child = createChildProcess()
    spawnMock.mockReturnValue(child)
    axiosGetMock.mockResolvedValue({
      data: {
        ok: true,
        runtime: {
          instance_id: 'stale-instance',
          generation: '0',
          startup_nonce: 'stale-nonce',
        },
      },
    })

    const { PythonService } = await import('../python')
    const service = new PythonService('', {}, '', '', {
      startupMaxAttempts: 2,
      startupRetryDelayMs: 1,
    })
    const starting = service.start()
    await vi.waitFor(() => expect(spawnMock).toHaveBeenCalledOnce())
    child.emit('exit', 1, null)

    await expect(starting).rejects.toThrow(/exited before becoming healthy/)
    expect(service.getStatus()).toMatchObject({ state: 'failed', instanceId: null })
  })

  it('rejects a process error during startup and keeps recovery bounded', async () => {
    vi.useFakeTimers()
    vi.spyOn(fs, 'existsSync').mockReturnValue(true)
    const child = createChildProcess()
    spawnMock.mockReturnValue(child)
    axiosGetMock.mockImplementation(() => new Promise(() => undefined))

    const { PythonService } = await import('../python')
    const service = new PythonService('', {}, '', '', {
      maxAttempts: 1,
      baseDelayMs: 10,
    })
    const starting = service.start()
    await vi.waitFor(() => expect(spawnMock).toHaveBeenCalledOnce())
    child.emit('error', new Error('spawn stream failed'))

    await expect(starting).rejects.toThrow(/process error.*spawn stream failed/i)
    expect(service.getStatus()).toMatchObject({ state: 'failed', instanceId: null })
    await vi.advanceTimersByTimeAsync(10)
    expect(spawnMock).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(100)
    expect(spawnMock).toHaveBeenCalledTimes(2)
  })

  it('resets recovery backoff after a successful health probe', async () => {
    vi.useFakeTimers()
    vi.spyOn(fs, 'existsSync').mockReturnValue(true)
    const firstChild = createChildProcess()
    const recoveredChild = createChildProcess()
    const secondRecoveredChild = createChildProcess()
    spawnMock
      .mockReturnValueOnce(firstChild)
      .mockReturnValueOnce(recoveredChild)
      .mockReturnValueOnce(secondRecoveredChild)
    axiosGetMock.mockImplementation(async () => healthyRuntimeResponse())

    const { PythonService } = await import('../python')
    const service = new PythonService()
    await service.start()

    firstChild.emit('exit', 1, null)
    await vi.advanceTimersByTimeAsync(1000)
    expect(service.getStatus().state).toBe('running')
    const firstNonce = (spawnMock.mock.calls[0]?.[2] as { env?: Record<string, string> })
      .env?.['YUIZAKI_RUNTIME_STARTUP_NONCE']
    const secondNonce = (spawnMock.mock.calls[1]?.[2] as { env?: Record<string, string> })
      .env?.['YUIZAKI_RUNTIME_STARTUP_NONCE']
    expect(firstNonce).toMatch(/^[a-f0-9]{48}$/)
    expect(secondNonce).toMatch(/^[a-f0-9]{48}$/)
    expect(secondNonce).not.toBe(firstNonce)
    expect(axiosGetMock).toHaveBeenCalledTimes(2)

    recoveredChild.emit('exit', 1, null)
    await vi.advanceTimersByTimeAsync(999)
    expect(spawnMock).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(1)
    expect(spawnMock).toHaveBeenCalledTimes(3)
    expect(service.getStatus().state).toBe('running')
  })

  it('never restarts a process terminated by an explicit stop', async () => {
    vi.useFakeTimers()
    vi.spyOn(fs, 'existsSync').mockReturnValue(true)
    const child = createChildProcess()
    child.kill.mockImplementation(() => {
      queueMicrotask(() => child.emit('exit', 0, null))
      return true
    })
    spawnMock.mockReturnValue(child)
    axiosGetMock.mockImplementation(async () => healthyRuntimeResponse())

    const { PythonService } = await import('../python')
    const service = new PythonService()
    await service.start()
    await service.stop()
    await vi.advanceTimersByTimeAsync(10_000)

    expect(spawnMock).toHaveBeenCalledTimes(1)
    expect(service.getStatus().state).toBe('idle')
    await expect(service.health()).resolves.toBe(false)
  })

  it('clears a pending unexpected-exit recovery when start is cancelled', async () => {
    vi.useFakeTimers()
    vi.spyOn(fs, 'existsSync').mockReturnValue(true)
    const child = createChildProcess()
    spawnMock.mockReturnValue(child)
    axiosGetMock.mockImplementation(async () => healthyRuntimeResponse())

    const { PythonService } = await import('../python')
    const service = new PythonService()
    await service.start()
    child.emit('exit', 1, null)
    await service.cancelStart()
    await vi.advanceTimersByTimeAsync(10_000)

    expect(spawnMock).toHaveBeenCalledTimes(1)
    expect(service.getStatus().state).toBe('cancelled')
  })

  it('fails promptly when the child exits while startup health is pending', async () => {
    vi.useFakeTimers()
    vi.spyOn(fs, 'existsSync').mockReturnValue(true)
    const child = createChildProcess()
    spawnMock.mockReturnValue(child)
    axiosGetMock.mockImplementation(() => new Promise(() => undefined))

    const { PythonService } = await import('../python')
    const service = new PythonService()
    const start = service.start()
    await vi.waitFor(() => expect(spawnMock).toHaveBeenCalledOnce())
    child.emit('exit', 1, null)

    await expect(start).rejects.toThrow(/exited before becoming healthy/)
    expect(service.getStatus().state).toBe('failed')
    await vi.advanceTimersByTimeAsync(999)
    expect(spawnMock).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(spawnMock).toHaveBeenCalledTimes(2)
  })
})
