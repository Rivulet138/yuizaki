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

  it('exposes only explicit computer-use request methods', async () => {
    const api = await loadPreload(undefined) as {
      computerUse: {
        preview: (payload: unknown) => Promise<unknown>
        emergencyStop: () => Promise<unknown>
        status: () => Promise<unknown>
      }
    }
    const payload = { actions: [{ type: 'move', x: 10, y: 20 }] }

    await api.computerUse.preview(payload)
    await api.computerUse.emergencyStop()
    await api.computerUse.status()

    expect(electron.invoke).toHaveBeenCalledWith('computer-use:preview', payload)
    expect(electron.invoke).toHaveBeenCalledWith('computer-use:emergency-stop')
    expect(electron.invoke).toHaveBeenCalledWith('computer-use:status')
    expect(api.computerUse).not.toHaveProperty('invoke')
    expect(api.computerUse).not.toHaveProperty('on')
  })

  it('exposes only fixed opaque-session perception methods', async () => {
    const api = await loadPreload(undefined) as {
      perception: Record<string, (sessionId: string) => Promise<unknown>>
    }
    const calls = [
      ['collectScreenshot', 'perception:collect-screenshot'],
      ['collectTargetWindow', 'perception:collect-target-window'],
      ['collectActiveApplication', 'perception:collect-active-application'],
      ['collectSelectedFile', 'perception:collect-selected-file'],
      ['collectClipboard', 'perception:collect-clipboard'],
      ['collectOcr', 'perception:collect-ocr'],
    ] as const
    for (const [method, channel] of calls) {
      await api.perception[method]?.('opaque-session')
      expect(electron.invoke).toHaveBeenCalledWith(channel, 'opaque-session')
    }
    expect(api.perception).not.toHaveProperty('issue')
    expect(api.perception).not.toHaveProperty('invoke')
    expect(api.perception).not.toHaveProperty('collect')
  })

  it('does not expose the legacy screen OCR bypass', async () => {
    const api = await loadPreload(undefined) as { screen: Record<string, unknown> }

    expect(api.screen).not.toHaveProperty('ocr')
  })

  it('exposes a closed onboarding bootstrap surface', async () => {
    const api = await loadPreload(undefined) as { onboarding: Record<string, (...args: unknown[]) => Promise<unknown>> }
    expect(Object.keys(api.onboarding).sort()).toEqual([
      'cancelBackend', 'cancelRun', 'reportDeviceProbe', 'retry', 'runProbe', 'runRepair', 'snapshot', 'startBackend',
    ])
    await api.onboarding.snapshot?.()
    await api.onboarding.runProbe?.({ probeIds: ['host.runtime'] })
    await api.onboarding.runRepair?.({ actionId: 'backend.retry' })
    expect(electron.invoke).toHaveBeenCalledWith('onboarding:snapshot')
    expect(electron.invoke).toHaveBeenCalledWith('onboarding:run-probe', { probeIds: ['host.runtime'] })
    expect(electron.invoke).toHaveBeenCalledWith('onboarding:run-repair', { actionId: 'backend.retry' })
    expect(api.onboarding).not.toHaveProperty('invoke')
    expect(api.onboarding).not.toHaveProperty('command')
  })
})
