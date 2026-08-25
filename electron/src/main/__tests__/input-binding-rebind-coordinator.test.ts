import { afterEach, describe, expect, it, vi } from 'vitest'

import { DEFAULT_INPUT_BINDINGS } from '../../shared/input-bindings'
import {
  DesktopActionBridge,
  type DesktopActionBackendPort,
} from '../desktop-action-bridge'
import { rebindInputBindingsWithDesktopActionFence } from '../input-binding-rebind-coordinator'

const backend = (overrides: Partial<DesktopActionBackendPort> = {}): DesktopActionBackendPort => ({
  status: vi.fn(async () => ({ ok: true, enabled: false, windowActionsAvailable: true })),
  enable: vi.fn(async () => ({
    ok: true,
    enabled: true,
    windowActionsAvailable: true,
    leaseEpoch: 2,
    leaseExpiresInMs: 5_000,
  })),
  disable: vi.fn(async () => ({ ok: true, enabled: false, windowActionsAvailable: true })),
  rearm: vi.fn(async () => ({
    ok: true,
    enabled: true,
    emergencyStopped: false,
    windowActionsAvailable: true,
    leaseEpoch: 4,
    leaseExpiresInMs: 5_000,
  })),
  emergencyStop: vi.fn(async () => ({
    ok: true,
    enabled: false,
    emergencyStopped: true,
    windowActionsAvailable: true,
  })),
  heartbeat: vi.fn(async (_signal, leaseEpoch) => ({
    ok: true,
    enabled: true,
    windowActionsAvailable: true,
    leaseEpoch,
    leaseExpiresInMs: 5_000,
  })),
  discover: vi.fn(async () => ({ ok: true, discoveryRevision: 1, apps: [] })),
  grant: vi.fn(async () => ({ ok: true, authorizationExpiresInMs: 30_000 })),
  ...overrides,
})

const dependencies = () => ({
  confirmNativeEnable: vi.fn(async () => true),
  selectNativeApp: vi.fn(async () => null),
  isEmergencyHotkeyAvailable: vi.fn(() => true),
})

const registrationStatus = {
  mouseHookAvailable: true,
  pushToTalkActive: true,
  keyboard: {
    interact: true,
    lock: true,
    openPanel: true,
    toggleVision: true,
    emergencyStop: true,
  },
  errors: [],
}

describe('safe input binding rebind', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('fences the live lease before shortcut unregister/register and requires explicit rearm', async () => {
    vi.useFakeTimers()
    let resolveStop!: (value: {
      ok: true
      enabled: false
      emergencyStopped: true
      windowActionsAvailable: true
    }) => void
    const port = backend({
      emergencyStop: vi.fn(() => new Promise((resolve) => { resolveStop = resolve })),
    })
    const bridge = new DesktopActionBridge(port, dependencies())
    const register = vi.fn(() => {
      expect(bridge.getStatus()).toMatchObject({ enabled: false, emergencyStopped: true, leaseState: 'inactive' })
      return registrationStatus
    })
    await bridge.enable()

    const rebinding = rebindInputBindingsWithDesktopActionFence(
      structuredClone(DEFAULT_INPUT_BINDINGS),
      { register },
      bridge,
    )
    expect(bridge.getStatus()).toMatchObject({ enabled: false, emergencyStopped: true, leaseState: 'inactive' })
    expect(register).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1_000)
    expect(port.heartbeat).not.toHaveBeenCalled()
    expect(register).not.toHaveBeenCalled()

    resolveStop({ ok: true, enabled: false, emergencyStopped: true, windowActionsAvailable: true })
    await expect(rebinding).resolves.toEqual(registrationStatus)
    expect(register).toHaveBeenCalledOnce()
    expect(bridge.getStatus()).toMatchObject({ enabled: false, emergencyStopped: true })

    await expect(bridge.rearm()).resolves.toMatchObject({
      ok: true,
      status: { enabled: true, emergencyStopped: false, leaseState: 'confirmed' },
    })
    bridge.dispose()
  })

  it('preserves existing shortcuts when stop is unconfirmed and leaves TTL as the fail-closed boundary', async () => {
    vi.useFakeTimers()
    const port = backend({
      emergencyStop: vi.fn(async () => ({ ok: false, code: 'DA_BACKEND_UNAVAILABLE', message: 'offline' })),
    })
    const bridge = new DesktopActionBridge(port, dependencies())
    const register = vi.fn(() => registrationStatus)
    await bridge.enable()
    const existingStop = bridge.emergencyStop()

    const rebinding = rebindInputBindingsWithDesktopActionFence(
      structuredClone(DEFAULT_INPUT_BINDINGS),
      { register },
      bridge,
    )
    const rebindFailure = expect(rebinding).rejects.toMatchObject({
      code: 'DA_HOTKEY_REBIND_STOP_UNCONFIRMED',
    })
    expect(register).not.toHaveBeenCalled()
    expect(bridge.getStatus()).toMatchObject({ enabled: false, emergencyStopped: true })

    await vi.advanceTimersByTimeAsync(1_000)
    await expect(existingStop).resolves.toMatchObject({ ok: false })
    await rebindFailure
    expect(port.emergencyStop).toHaveBeenCalledTimes(3)
    expect(register).not.toHaveBeenCalled()
    expect(bridge.getStatus()).toMatchObject({
      enabled: false,
      emergencyStopped: true,
      degraded: true,
      leaseState: 'unconfirmed',
      leaseExpiresAt: null,
      lastError: { message: 'offline' },
    })
    await vi.advanceTimersByTimeAsync(5_000)
    expect(port.heartbeat).not.toHaveBeenCalled()
  })
})
