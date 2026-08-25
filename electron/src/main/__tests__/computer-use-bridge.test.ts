import { describe, expect, it, vi } from 'vitest'
import { ComputerUseBridge, type ComputerUseBackendPort } from '../computer-use-bridge'

const backend = (overrides: Partial<ComputerUseBackendPort> = {}): ComputerUseBackendPort => ({
  preview: vi.fn(async () => ({ ok: true })),
  stop: vi.fn(async () => ({ ok: true, revision: 4 })),
  status: vi.fn(async () => ({ ok: true, revision: 4, stopped: false })),
  ...overrides,
})

describe('ComputerUseBridge', () => {
  it('rejects unknown and oversized preview payloads before the backend', async () => {
    const port = backend()
    const bridge = new ComputerUseBridge(port)

    await expect(bridge.preview({ actions: [{ type: 'move', x: 1, y: 2, extra: true }] })).resolves.toMatchObject({
      ok: false,
      code: 'CU_INVALID_PREVIEW',
    })
    await expect(bridge.preview({ actions: [{ type: 'text_input', text: 'x'.repeat(16_385) }] })).resolves.toMatchObject({
      ok: false,
      code: 'CU_INVALID_PREVIEW',
    })
    expect(port.preview).not.toHaveBeenCalled()
  })

  it('coalesces concurrent stop while allowing a later stop to advance the backend fence', async () => {
    let resolveStop!: (value: { ok: true; revision: number }) => void
    const stop = vi.fn<ComputerUseBackendPort['stop']>()
      .mockImplementationOnce(() => new Promise((resolve) => { resolveStop = resolve }))
      .mockResolvedValue({ ok: true, revision: 10 })
    const port = backend({ stop })
    const bridge = new ComputerUseBridge(port)

    const first = bridge.stop('shortcut')
    const concurrent = bridge.stop('ipc')
    expect(first).toBe(concurrent)
    await Promise.resolve()
    resolveStop({ ok: true, revision: 9 })
    await expect(first).resolves.toMatchObject({
      ok: true,
      status: { scope: 'device', stopped: true, stopInFlight: false },
    })
    await expect(bridge.stop('ipc')).resolves.toMatchObject({ ok: true })
    expect(port.stop).toHaveBeenCalledTimes(2)
  })

  it('settles on timeout when the backend ignores AbortSignal and keeps the local fence', async () => {
    vi.useFakeTimers()
    const bridge = new ComputerUseBridge(backend({
      stop: vi.fn(() => new Promise(() => undefined)),
    }), 25)

    const result = bridge.stop()
    await vi.advanceTimersByTimeAsync(30)

    await expect(result).resolves.toMatchObject({
      ok: false,
      code: 'CU_BACKEND_TIMEOUT',
      status: { stopped: true, degraded: true, stopInFlight: false },
    })
    vi.useRealTimers()
  })

  it('projects only bounded backend fields to callers', async () => {
    const bridge = new ComputerUseBridge(backend({
      status: vi.fn(async () => ({
        ok: true,
        revision: 3,
        stopped: false,
        token: 'secret',
        session_id: 'private',
        message: 'x'.repeat(1000),
      } as never)),
    }))

    const result = await bridge.refreshStatus()

    expect(result).toMatchObject({ ok: true, data: { ok: true, scope: 'device', revision: 3 } })
    expect(JSON.stringify(result)).not.toContain('secret')
    expect(JSON.stringify(result)).not.toContain('private')
  })

  it('dispose aborts and settles pending calls', async () => {
    const bridge = new ComputerUseBridge(backend({
      status: vi.fn(() => new Promise(() => undefined)),
    }), 10_000)
    const pending = bridge.refreshStatus()

    bridge.dispose()

    await expect(pending).resolves.toMatchObject({ ok: false, code: 'CU_BRIDGE_DISPOSED' })
    expect(bridge.getStatus()).toMatchObject({ stopped: true, degraded: true, stopInFlight: false })
  })
})
