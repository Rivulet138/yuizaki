import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const electron = vi.hoisted(() => ({
  exposeInMainWorld: vi.fn(),
  sendSync: vi.fn(),
  invoke: vi.fn().mockResolvedValue(undefined),
  send: vi.fn(),
  on: vi.fn(),
  off: vi.fn(),
}))

vi.mock('electron', () => ({
  contextBridge: { exposeInMainWorld: electron.exposeInMainWorld },
  ipcRenderer: {
    sendSync: electron.sendSync,
    invoke: electron.invoke,
    send: electron.send,
    on: electron.on,
    off: electron.off,
  },
}))

const originalArgv = [...process.argv]
const originalFlag = process.env['YUIZAKI_E2E']
const originalToken = process.env['YUIZAKI_E2E_TOKEN']

const loadPreload = async (activation: unknown) => {
  vi.resetModules()
  electron.sendSync.mockReturnValue(activation)
  process.env['YUIZAKI_E2E'] = '1'
  process.env['YUIZAKI_E2E_TOKEN'] = 'spoofed-token'
  process.argv = [...originalArgv, '--yuizaki-e2e-token=spoofed-token']
  await import('../../preload/index')
  return electron.exposeInMainWorld.mock.calls.find(([name]) => name === 'petApi')?.[1] as Record<string, unknown>
}

describe('real preload E2E activation wiring', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    process.argv = [...originalArgv]
    if (originalFlag === undefined) delete process.env['YUIZAKI_E2E']
    else process.env['YUIZAKI_E2E'] = originalFlag
    if (originalToken === undefined) delete process.env['YUIZAKI_E2E_TOKEN']
    else process.env['YUIZAKI_E2E_TOKEN'] = originalToken
  })

  it('does not expose the API when default or packaged main has no activation handler', async () => {
    const api = await loadPreload(undefined)
    expect(electron.sendSync).toHaveBeenCalledWith('e2e:activate', 'spoofed-token')
    expect(api).not.toHaveProperty('e2e')
  })

  it('exposes the API only after main returns a proof and sends it on every call', async () => {
    const api = await loadPreload({ proof: 'main-issued-proof' })
    expect(api).toHaveProperty('e2e')
    const e2e = api['e2e'] as { pauseHealthPolling: () => Promise<unknown> }
    await e2e.pauseHealthPolling()
    expect(electron.invoke).toHaveBeenCalledWith(
      'e2e:pause-health-polling',
      'spoofed-token',
      'main-issued-proof',
      undefined,
    )
  })

  it('wires the desktop adjustment lifecycle to explicit IPC channels', async () => {
    const api = await loadPreload(undefined) as {
      pet: {
        beginAdjustment: () => Promise<unknown>
        completeAdjustment: () => Promise<unknown>
        cancelAdjustment: () => Promise<unknown>
      }
    }

    await api.pet.beginAdjustment()
    await api.pet.completeAdjustment()
    await api.pet.cancelAdjustment()

    expect(electron.invoke).toHaveBeenCalledWith('pet:begin-adjustment')
    expect(electron.invoke).toHaveBeenCalledWith('pet:complete-adjustment')
    expect(electron.invoke).toHaveBeenCalledWith('pet:cancel-adjustment')
  })
})
