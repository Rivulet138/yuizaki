import { describe, expect, it, vi } from 'vitest'

import {
  DesktopActionBridge,
  type DesktopActionBackendPort,
} from '../desktop-action-bridge'

const backend = (overrides: Partial<DesktopActionBackendPort> = {}): DesktopActionBackendPort => ({
  status: vi.fn(async () => ({ ok: true, enabled: false, windowActionsAvailable: true, nativeInputAvailable: false, revision: 2, stopEpoch: 0 })),
  enable: vi.fn(async () => ({ ok: true, enabled: true, windowActionsAvailable: true, nativeInputAvailable: false, revision: 3, stopEpoch: 0, leaseEpoch: 2, leaseExpiresInMs: 5_000 })),
  disable: vi.fn(async () => ({ ok: true, enabled: false, windowActionsAvailable: true, nativeInputAvailable: false, revision: 4, stopEpoch: 0 })),
  rearm: vi.fn(async () => ({ ok: true, enabled: true, windowActionsAvailable: true, nativeInputAvailable: false, emergencyStopped: false, revision: 5, stopEpoch: 2, leaseEpoch: 4, leaseExpiresInMs: 5_000 })),
  emergencyStop: vi.fn(async () => ({ ok: true, enabled: false, windowActionsAvailable: true, nativeInputAvailable: false, emergencyStopped: true, revision: 6, stopEpoch: 2 })),
  heartbeat: vi.fn(async (_signal, leaseEpoch) => ({ ok: true, enabled: true, windowActionsAvailable: true, leaseEpoch, leaseExpiresInMs: 5_000 })),
  discover: vi.fn(async () => ({ ok: true, discoveryRevision: 1, apps: [{ appId: 'das_app_test', label: 'Editor', windowTitles: ['Notes'] }] })),
  grant: vi.fn(async () => ({ ok: true, authorizationExpiresInMs: 30_000 })),
  ...overrides,
})

const dependencies = () => ({
  confirmNativeEnable: vi.fn(async () => true),
  selectNativeApp: vi.fn(async (apps) => apps[0]?.id ?? null),
  isEmergencyHotkeyAvailable: vi.fn(() => true),
})

describe('DesktopActionBridge', () => {
  it('starts disabled and rejects enable when the native adapter is absent', async () => {
    const port = backend({
      status: vi.fn(async () => ({ ok: true, enabled: false, windowActionsAvailable: false, reason: 'adapter absent' })),
    })
    const deps = dependencies()
    const bridge = new DesktopActionBridge(port, deps)

    expect(bridge.getStatus()).toMatchObject({ enabled: false, windowActionsAvailable: false, nativeInputAvailable: false })
    await expect(bridge.enable()).resolves.toMatchObject({
      ok: false,
      code: 'DA_WINDOW_ACTIONS_UNAVAILABLE',
      status: { enabled: false },
    })
    expect(deps.confirmNativeEnable).not.toHaveBeenCalled()
    expect(port.enable).not.toHaveBeenCalled()
  })

  it('fails closed when the native confirmation dialog is unavailable', async () => {
    const port = backend()
    const deps = {
      ...dependencies(),
      confirmNativeEnable: vi.fn(async () => { throw new Error('dialog failed') }),
    }

    await expect(new DesktopActionBridge(port, deps).enable()).resolves.toMatchObject({
      ok: false,
      code: 'DA_CONFIRMATION_UNAVAILABLE',
      status: { enabled: false, operationInFlight: false },
    })
    expect(port.enable).not.toHaveBeenCalled()
  })

  it('requires rearm and a new native confirmation after emergency stop', async () => {
    const port = backend()
    const deps = dependencies()
    const bridge = new DesktopActionBridge(port, deps)

    await expect(bridge.enable()).resolves.toMatchObject({ ok: true, status: { enabled: true } })
    await expect(bridge.emergencyStop()).resolves.toMatchObject({
      ok: true,
      status: { enabled: false, emergencyStopped: true, stopEpoch: 2 },
    })
    await expect(bridge.refreshStatus()).resolves.toMatchObject({
      ok: true,
      status: { enabled: false, emergencyStopped: true },
    })
    await expect(bridge.enable()).resolves.toMatchObject({ ok: false, code: 'DA_REARM_REQUIRED' })
    await expect(bridge.rearm()).resolves.toMatchObject({ ok: true, status: { enabled: true } })
    expect(deps.confirmNativeEnable).toHaveBeenNthCalledWith(1, 'enable', expect.any(AbortSignal))
    expect(deps.confirmNativeEnable).toHaveBeenNthCalledWith(2, 'rearm', expect.any(AbortSignal))
  })

  it('never projects native input availability even when the backend claims it', async () => {
    const bridge = new DesktopActionBridge(backend({
      status: vi.fn(async () => ({
        ok: true,
        enabled: false,
        windowActionsAvailable: true,
        nativeInputAvailable: true,
      })),
    }), dependencies())

    await expect(bridge.refreshStatus()).resolves.toMatchObject({
      ok: true,
      status: { windowActionsAvailable: true, nativeInputAvailable: false },
    })
  })

  it('does not clear the stop latch when the backend fails to rearm', async () => {
    const port = backend({
      rearm: vi.fn(async () => ({
        ok: true,
        enabled: true,
        emergencyStopped: true,
        windowActionsAvailable: true,
      })),
    })
    const bridge = new DesktopActionBridge(port, dependencies())
    await bridge.emergencyStop()

    await expect(bridge.rearm()).resolves.toMatchObject({
      ok: false,
      code: 'DA_BACKEND_NOT_REARMED',
      status: { enabled: false, emergencyStopped: true },
    })
  })

  it('coalesces concurrent emergency stops but a later stop advances the backend again', async () => {
    let resolveStop!: (value: { ok: true; enabled: false; windowActionsAvailable: true; revision: number; stopEpoch: number }) => void
    const stop = vi.fn<DesktopActionBackendPort['emergencyStop']>()
      .mockImplementationOnce(() => new Promise((resolve) => { resolveStop = resolve }))
      .mockResolvedValue({ ok: true, enabled: false, windowActionsAvailable: true, revision: 8, stopEpoch: 4 })
    const bridge = new DesktopActionBridge(backend({ emergencyStop: stop }), dependencies())

    const first = bridge.emergencyStop()
    const concurrent = bridge.emergencyStop()
    expect(concurrent).toBe(first)
    await Promise.resolve()
    resolveStop({ ok: true, enabled: false, windowActionsAvailable: true, revision: 7, stopEpoch: 3 })
    await expect(first).resolves.toMatchObject({ ok: true, status: { stopEpoch: 3 } })
    await expect(bridge.emergencyStop()).resolves.toMatchObject({ ok: true, status: { stopEpoch: 4 } })
    expect(stop).toHaveBeenCalledTimes(2)
  })

  it('settles and revokes confirmation work when emergency stop wins the race', async () => {
    let resolveConfirmation!: (confirmed: boolean) => void
    const deps = {
      ...dependencies(),
      confirmNativeEnable: vi.fn(() => new Promise<boolean>((resolve) => { resolveConfirmation = resolve })),
    }
    const bridge = new DesktopActionBridge(backend(), deps)

    const enabling = bridge.enable()
    await vi.waitFor(() => expect(deps.confirmNativeEnable).toHaveBeenCalledOnce())
    await expect(bridge.emergencyStop()).resolves.toMatchObject({ ok: true })
    await expect(enabling).resolves.toMatchObject({ ok: false, code: 'DA_CONFIRMATION_REVOKED' })
    resolveConfirmation(true)
    await Promise.resolve()
    expect(bridge.getStatus()).toMatchObject({ enabled: false, emergencyStopped: true })
  })

  it('settles ignored backend work on timeout and dispose', async () => {
    vi.useFakeTimers()
    const timedOut = new DesktopActionBridge(backend({
      status: vi.fn(() => new Promise(() => undefined)),
    }), dependencies(), 20)
    const pendingTimeout = timedOut.refreshStatus()
    await vi.advanceTimersByTimeAsync(25)
    await expect(pendingTimeout).resolves.toMatchObject({ ok: false, code: 'DA_BACKEND_TIMEOUT' })

    const disposedPort = backend({
      status: vi.fn(() => new Promise(() => undefined)),
    })
    const disposed = new DesktopActionBridge(disposedPort, dependencies(), 10_000)
    const pendingDispose = disposed.refreshStatus()
    disposed.dispose()
    await expect(pendingDispose).resolves.toMatchObject({ ok: false, code: 'DA_BRIDGE_DISPOSED' })
    expect(disposed.getStatus()).toMatchObject({ enabled: false, emergencyStopped: true, degraded: true })
    expect(disposedPort.emergencyStop).toHaveBeenCalledOnce()
    vi.useRealTimers()
  })

  it('renews only while the emergency hotkey and confirmed lease remain healthy', async () => {
    vi.useFakeTimers()
    const port = backend()
    const deps = dependencies()
    const bridge = new DesktopActionBridge(port, deps)

    await expect(bridge.enable()).resolves.toMatchObject({
      ok: true,
      status: { enabled: true, leaseState: 'confirmed' },
    })
    await vi.advanceTimersByTimeAsync(1_000)
    expect(port.heartbeat).toHaveBeenCalledWith(expect.any(AbortSignal), 2)
    expect(bridge.getStatus()).toMatchObject({ enabled: true, leaseState: 'confirmed' })

    deps.isEmergencyHotkeyAvailable.mockReturnValue(false)
    await vi.advanceTimersByTimeAsync(1_000)
    await vi.waitFor(() => expect(port.emergencyStop).toHaveBeenCalledOnce())
    expect(bridge.getStatus()).toMatchObject({ enabled: false, emergencyStopped: true })
    vi.useRealTimers()
  })

  it('fails closed and preserves an unconfirmed lease error when heartbeat fails', async () => {
    vi.useFakeTimers()
    const port = backend({
      heartbeat: vi.fn(async () => ({ ok: false, code: 'DA_HOST_LEASE_EXPIRED', message: 'lease expired' })),
    })
    const bridge = new DesktopActionBridge(port, dependencies())
    await bridge.enable()

    await vi.advanceTimersByTimeAsync(1_000)
    await vi.waitFor(() => expect(port.emergencyStop).toHaveBeenCalledOnce())

    expect(bridge.getStatus()).toMatchObject({
      enabled: false,
      emergencyStopped: true,
      degraded: true,
      leaseState: 'unconfirmed',
      lastError: { code: 'DA_HOST_LEASE_EXPIRED', message: 'lease expired' },
    })
    vi.useRealTimers()
  })

  it('ignores a late heartbeat after disable and never revives the lease', async () => {
    vi.useFakeTimers()
    let resolveHeartbeat!: (value: { ok: true; enabled: true; leaseEpoch: number; leaseExpiresInMs: number }) => void
    const port = backend({
      heartbeat: vi.fn(() => new Promise((resolve) => { resolveHeartbeat = resolve })),
    })
    const bridge = new DesktopActionBridge(port, dependencies())
    await bridge.enable()
    await vi.advanceTimersByTimeAsync(1_000)
    await vi.waitFor(() => expect(port.heartbeat).toHaveBeenCalledOnce())

    await bridge.disable()
    resolveHeartbeat({ ok: true, enabled: true, leaseEpoch: 2, leaseExpiresInMs: 5_000 })
    await Promise.resolve()

    expect(bridge.getStatus()).toMatchObject({ enabled: false, leaseState: 'inactive' })
    await vi.advanceTimersByTimeAsync(5_000)
    expect(port.heartbeat).toHaveBeenCalledOnce()
    vi.useRealTimers()
  })

  it('bounds emergency-stop retries and leaves the backend outcome unconfirmed', async () => {
    vi.useFakeTimers()
    const port = backend({
      emergencyStop: vi.fn(async () => ({ ok: false, code: 'DA_BACKEND_UNAVAILABLE', message: 'offline' })),
    })
    const bridge = new DesktopActionBridge(port, dependencies())

    const stopping = bridge.emergencyStop()
    await vi.advanceTimersByTimeAsync(1_000)
    await expect(stopping).resolves.toMatchObject({ ok: false })
    expect(port.emergencyStop).toHaveBeenCalledTimes(3)
    expect(bridge.getStatus()).toMatchObject({
      enabled: false,
      emergencyStopped: true,
      degraded: true,
      leaseState: 'unconfirmed',
      lastError: { message: 'offline' },
    })
    await expect(bridge.refreshStatus()).resolves.toMatchObject({
      ok: true,
      status: { degraded: true, leaseState: 'unconfirmed', lastError: { message: 'offline' } },
    })
    vi.useRealTimers()
  })

  it('keeps opaque app identifiers inside main while returning only closed status', async () => {
    const port = backend()
    const deps = dependencies()
    const bridge = new DesktopActionBridge(port, deps)
    await bridge.enable()

    const result = await bridge.manageAuthorization()

    expect(deps.selectNativeApp).toHaveBeenCalledWith([
      { id: 'das_app_test', label: 'Editor', windowTitles: ['Notes'] },
    ], expect.any(AbortSignal))
    expect(port.grant).toHaveBeenCalledWith(expect.any(AbortSignal), 'das_app_test', 1)
    expect(result).toMatchObject({ ok: true, status: { authorizationGranted: true } })
    expect(JSON.stringify(result)).not.toContain('das_app_test')
  })

  it('clears the renderer authorization projection when its bounded TTL expires', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-15T00:00:00.000Z'))
    const bridge = new DesktopActionBridge(backend(), dependencies())
    await bridge.enable()
    await bridge.manageAuthorization()
    expect(bridge.getStatus()).toMatchObject({ authorizationGranted: true })

    await vi.advanceTimersByTimeAsync(30_000)

    expect(bridge.getStatus()).toMatchObject({
      authorizationGranted: false,
      authorizationExpiresAt: null,
    })
    bridge.dispose()
    vi.useRealTimers()
  })
})
