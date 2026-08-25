import { beforeEach, describe, expect, it, vi } from 'vitest'
import { buildPackagedRendererUrl } from '../renderer-protocol'

const electronMock = vi.hoisted(() => {
  const handlers = new Map<string, (...args: unknown[]) => unknown>()
  const exposed = new Map<string, unknown>()
  return {
    handlers,
    exposed,
    ipcMain: {
      handle: vi.fn((channel: string, handler: (...args: unknown[]) => unknown) => handlers.set(channel, handler)),
      on: vi.fn(),
    },
    ipcRenderer: {
      invoke: vi.fn(),
      send: vi.fn(),
      on: vi.fn(),
      removeListener: vi.fn(),
    },
    contextBridge: {
      exposeInMainWorld: vi.fn((name: string, value: unknown) => exposed.set(name, value)),
    },
  }
})

vi.mock('electron', () => ({
  app: { getAppMetrics: vi.fn(() => []) },
  contextBridge: electronMock.contextBridge,
  ipcMain: electronMock.ipcMain,
  ipcRenderer: electronMock.ipcRenderer,
  nativeImage: { createFromBitmap: vi.fn(), createFromBuffer: vi.fn() },
  screen: { getAllDisplays: vi.fn(() => []), getPrimaryDisplay: vi.fn() },
  shell: { openExternal: vi.fn() },
}))

const trustedEvent = {
  senderFrame: { url: buildPackagedRendererUrl('index.html') },
  sender: { getURL: () => '' },
}

const untrustedEvent = {
  senderFrame: { url: 'https://attacker.example/app.html' },
  sender: { getURL: () => '' },
}

const desktopActionBridge = () => ({
  getStatus: vi.fn(() => ({ enabled: false })),
  refreshStatus: vi.fn(async () => ({ ok: true })),
  enable: vi.fn(async () => ({ ok: true })),
  disable: vi.fn(async () => ({ ok: true })),
  rearm: vi.fn(async () => ({ ok: true })),
  manageAuthorization: vi.fn(async () => ({ ok: true })),
})

describe('desktop action IPC security', () => {
  beforeEach(() => {
    electronMock.handlers.clear()
    electronMock.exposed.clear()
    vi.clearAllMocks()
  })

  it.each([
    'desktop-action:status',
    'desktop-action:enable',
    'desktop-action:disable',
    'desktop-action:rearm',
    'desktop-action:manage-authorization',
  ])('rejects an untrusted renderer on %s before calling the bridge', async (channel) => {
    const { registerIpcHandlers } = await import('../ipc-handlers')
    const bridge = desktopActionBridge()
    registerIpcHandlers(new Proxy({ desktopActionBridge: bridge }, { get: (target, key) => Reflect.get(target, key) }) as never)

    expect(() => electronMock.handlers.get(channel)?.(untrustedEvent, { actions: [] })).toThrow(/Blocked IPC/)
    expect(bridge.refreshStatus).not.toHaveBeenCalled()
    expect(bridge.enable).not.toHaveBeenCalled()
    expect(bridge.disable).not.toHaveBeenCalled()
    expect(bridge.rearm).not.toHaveBeenCalled()
    expect(bridge.manageAuthorization).not.toHaveBeenCalled()
  })

  it.each([
    ['desktop-action:status', 'refreshStatus'],
    ['desktop-action:enable', 'enable'],
    ['desktop-action:disable', 'disable'],
    ['desktop-action:rearm', 'rearm'],
    ['desktop-action:manage-authorization', 'manageAuthorization'],
  ] as const)('rejects extra arguments on %s', async (channel, method) => {
    const { registerIpcHandlers } = await import('../ipc-handlers')
    const bridge = desktopActionBridge()
    registerIpcHandlers({ desktopActionBridge: bridge } as never)

    expect(electronMock.handlers.get(channel)?.(trustedEvent, {})).toMatchObject({
      ok: false,
      code: 'DA_INVALID_REQUEST',
    })
    expect(bridge[method]).not.toHaveBeenCalled()
  })

  it('does not register a renderer preview channel', async () => {
    const { registerIpcHandlers } = await import('../ipc-handlers')
    const bridge = desktopActionBridge()
    registerIpcHandlers({ desktopActionBridge: bridge } as never)

    expect(electronMock.handlers.has('desktop-action:preview')).toBe(false)
  })

  it('preload exposes only the closed desktop action control surface', async () => {
    await import('../../preload/index')
    const api = electronMock.exposed.get('petApi') as Record<string, unknown>
    const surface = api['desktopAction'] as Record<string, unknown>

    expect(Object.keys(surface).sort()).toEqual(['disable', 'enable', 'manageAuthorization', 'rearm', 'status'])
    expect(surface).not.toHaveProperty('heartbeat')
    expect(surface).not.toHaveProperty('renew')
    expect(surface).not.toHaveProperty('preview')
    expect(surface).not.toHaveProperty('execute')
    expect(surface).not.toHaveProperty('perform')
    expect(surface).not.toHaveProperty('emergencyStop')
    expect(surface).not.toHaveProperty('token')
    expect(surface).not.toHaveProperty('invoke')
  })
})
