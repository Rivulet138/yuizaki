import { describe, expect, it, vi } from 'vitest'

import { stopDesktopAutomationWithPerceptionFence } from '../perception-stop-coordinator'

describe('desktop automation emergency-stop coordinator', () => {
  it('fences perception first, stops both action paths, and commits the real backend revision', async () => {
    const order: string[] = []
    const perception = {
      beginStopFence: vi.fn(() => { order.push('perception-fence') }),
      interrupt: vi.fn((revision: number) => { order.push(`perception-revision:${revision}`) }),
    }
    const desktopAction = {
      emergencyStop: vi.fn(async () => {
        order.push('desktop-action')
        return { ok: true as const, data: { stopEpoch: 8 } }
      }),
    }
    const computerUse = {
      stop: vi.fn(async () => {
        order.push('computer-use')
        return { ok: true as const, data: { revision: 11 } }
      }),
    }

    const result = await stopDesktopAutomationWithPerceptionFence(
      computerUse,
      desktopAction,
      perception,
      'shortcut',
    )

    expect(result).toMatchObject({
      computerUse: { ok: true, data: { revision: 11 } },
      desktopAction: { ok: true, data: { stopEpoch: 8 } },
    })
    expect(computerUse.stop).toHaveBeenCalledWith('shortcut')
    expect(order).toEqual([
      'perception-fence',
      'desktop-action',
      'computer-use',
      'perception-revision:11',
    ])
  })

  it('leaves the perception fence closed when ComputerUse lacks a committed revision', async () => {
    const perception = { beginStopFence: vi.fn(), interrupt: vi.fn() }

    await stopDesktopAutomationWithPerceptionFence(
      { stop: vi.fn(async () => ({ ok: false as const, code: 'CU_STOP_FAILED', message: 'failed' })) },
      { emergencyStop: vi.fn(async () => ({ ok: false as const, code: 'DA_STOP_FAILED', message: 'failed' })) },
      perception,
      'ipc',
    )

    expect(perception.beginStopFence).toHaveBeenCalledOnce()
    expect(perception.interrupt).not.toHaveBeenCalled()
  })
})
