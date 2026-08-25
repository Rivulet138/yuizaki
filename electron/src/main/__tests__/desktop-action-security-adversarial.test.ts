import { describe, expect, it, vi } from 'vitest'
import {
  createAuthenticatedDesktopActionBackendPort,
  DesktopActionBridge,
  type DesktopActionBackendPort,
} from '../desktop-action-bridge'

const backend = (overrides: Partial<DesktopActionBackendPort> = {}): DesktopActionBackendPort => ({
  status: vi.fn(async () => ({ ok: true, enabled: false, window_actions_available: true, feature_revision: 3, stop_epoch: 1 } as never)),
  enable: vi.fn(async () => ({ ok: true, enabled: true, window_actions_available: true, feature_revision: 4, stop_epoch: 1, lease_epoch: 2, lease_expires_in_ms: 5_000 } as never)),
  disable: vi.fn(async () => ({ ok: true, enabled: false, window_actions_available: true, feature_revision: 5, stop_epoch: 1 } as never)),
  rearm: vi.fn(async () => ({ ok: true, enabled: true, emergency_stopped: false, window_actions_available: true, feature_revision: 6, stop_epoch: 2, lease_epoch: 4, lease_expires_in_ms: 5_000 } as never)),
  emergencyStop: vi.fn(async () => ({ ok: true, enabled: false, emergency_stopped: true, window_actions_available: true, feature_revision: 7, stop_epoch: 3 } as never)),
  heartbeat: vi.fn(async (_signal, leaseEpoch) => ({ ok: true, enabled: true, window_actions_available: true, lease_epoch: leaseEpoch, lease_expires_in_ms: 5_000 } as never)),
  discover: vi.fn(async () => ({ ok: true, discovery_revision: 1, apps: [] } as never)),
  grant: vi.fn(async () => ({ ok: true, expires_in_ms: 30_000 } as never)),
  ...overrides,
})

const dependencies = (overrides: Partial<ConstructorParameters<typeof DesktopActionBridge>[1]> = {}) => ({
  confirmNativeEnable: vi.fn(async () => true),
  selectNativeApp: vi.fn(async () => null),
  isEmergencyHotkeyAvailable: vi.fn(() => true),
  ...overrides,
})

describe('desktop action security boundary', () => {
  it('does not request confirmation or enable when the emergency hotkey is unavailable', async () => {
    const port = backend()
    const deps = dependencies({ isEmergencyHotkeyAvailable: vi.fn(() => false) })
    const bridge = new DesktopActionBridge(port, deps)

    await expect(bridge.enable()).resolves.toMatchObject({
      ok: false,
      code: 'DA_EMERGENCY_HOTKEY_UNAVAILABLE',
    })
    expect(deps.confirmNativeEnable).not.toHaveBeenCalled()
    expect(port.enable).not.toHaveBeenCalled()
  })

  it('requires a fresh native confirmation for every enable operation', async () => {
    const port = backend()
    const deps = dependencies()
    const bridge = new DesktopActionBridge(port, deps)

    await expect(bridge.enable()).resolves.toMatchObject({ ok: true })
    await expect(bridge.disable()).resolves.toMatchObject({ ok: true })
    await expect(bridge.enable()).resolves.toMatchObject({ ok: true })

    expect(deps.confirmNativeEnable).toHaveBeenCalledTimes(2)
    expect(deps.confirmNativeEnable).toHaveBeenNthCalledWith(1, 'enable', expect.any(AbortSignal))
    expect(deps.confirmNativeEnable).toHaveBeenNthCalledWith(2, 'enable', expect.any(AbortSignal))
  })

  it('projects backend responses without private tokens, native ids, pids, or paths', async () => {
    const port = backend({
      status: vi.fn(async () => ({
        ok: true,
        enabled: false,
        window_actions_available: true,
        revision: 9,
        token: 'private-token',
        hwnd: '0x1234',
        xid: '0x5678',
        pid: 4321,
        path: 'C:\\private\\app.exe',
      } as never)),
    })
    const serialized = JSON.stringify(await new DesktopActionBridge(port, dependencies()).refreshStatus())

    expect(serialized).not.toContain('private-token')
    expect(serialized).not.toContain('0x1234')
    expect(serialized).not.toContain('0x5678')
    expect(serialized).not.toContain('4321')
    expect(serialized).not.toContain('private\\app.exe')
  })

  it('keeps the host token private while authenticating the backend request', async () => {
    const fetchImpl = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: vi.fn(async () => ({ ok: true, window_actions_available: true, token: 'echoed-private-token' })),
    }))
    const port = createAuthenticatedDesktopActionBackendPort(
      'http://127.0.0.1:8000',
      'host-secret',
      fetchImpl as never,
    )

    const result = await port.status(new AbortController().signal)

    expect(fetchImpl).toHaveBeenCalledWith(
      new URL('http://127.0.0.1:8000/api/desktop-actions/status'),
      expect.objectContaining({ headers: expect.objectContaining({ Authorization: 'Bearer host-secret' }) }),
    )
    expect(JSON.stringify(result)).not.toContain('host-secret')
    expect(JSON.stringify(result)).not.toContain('echoed-private-token')
  })

  it('keeps native input unavailable even when the backend claims it is available', async () => {
    const port = backend({
      status: vi.fn(async () => ({
        ok: true,
        enabled: false,
        window_actions_available: true,
        native_input_available: true,
      } as never)),
    })
    const bridge = new DesktopActionBridge(port, dependencies())

    await expect(bridge.refreshStatus()).resolves.toMatchObject({
      ok: true,
      status: { windowActionsAvailable: true, nativeInputAvailable: false },
    })
  })

  it('keeps emergency stop latched across refresh and rejects enable until rearm', async () => {
    const port = backend()
    const bridge = new DesktopActionBridge(port, dependencies())
    await bridge.enable()
    await bridge.emergencyStop()
    vi.mocked(port.status).mockResolvedValue({
      ok: true,
      enabled: true,
      window_actions_available: true,
      emergency_stopped: false,
    } as never)

    await expect(bridge.refreshStatus()).resolves.toMatchObject({
      ok: true,
      status: { enabled: false, emergencyStopped: true },
    })
    await expect(bridge.enable()).resolves.toMatchObject({ ok: false, code: 'DA_REARM_REQUIRED' })
    await expect(bridge.rearm()).resolves.toMatchObject({
      ok: true,
      status: { enabled: true, emergencyStopped: false },
    })
  })

  it('fails closed without a private host token and does not contact fetch', async () => {
    const fetchImpl = vi.fn()
    const port = createAuthenticatedDesktopActionBackendPort('http://127.0.0.1:8000', ' ', fetchImpl as never)

    await expect(port.status(new AbortController().signal)).resolves.toMatchObject({
      ok: false,
      code: 'DA_HOST_TOKEN_MISSING',
    })
    expect(fetchImpl).not.toHaveBeenCalled()
  })

  it('exposes main-process fencing controls but no preview or native input execution method', () => {
    const methods = Object.getOwnPropertyNames(DesktopActionBridge.prototype)

    expect(methods).toContain('emergencyStop')
    expect(methods).not.toContain('preview')
    expect(methods).not.toContain('perform')
    expect(methods).not.toContain('execute')
    expect(methods).not.toContain('injectMouse')
    expect(methods).not.toContain('injectKeyboard')
  })
})
