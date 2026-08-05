import { describe, expect, it, vi } from 'vitest'

import { PointerMoveCoalescer } from '@/pet-pointer-coalescer'

describe('PointerMoveCoalescer', () => {
  it('coalesces high-frequency pointer input to the latest point per frame', () => {
    let callback: (() => void) | null = null
    const onMove = vi.fn()
    const coalescer = new PointerMoveCoalescer({
      onMove,
      requestFrame: (next) => {
        callback = next
        return 1
      },
      cancelFrame: vi.fn(),
    })

    for (let index = 0; index < 125; index += 1) {
      coalescer.submit({ x: index, y: index + 1 })
    }

    expect(onMove).not.toHaveBeenCalled()
    callback?.()
    expect(onMove).toHaveBeenCalledTimes(1)
    expect(onMove).toHaveBeenLastCalledWith({ x: 124, y: 125 })
  })

  it('cancels a queued hover update without invoking the consumer', () => {
    let callback: (() => void) | null = null
    const onMove = vi.fn()
    const cancelFrame = vi.fn()
    const coalescer = new PointerMoveCoalescer({
      onMove,
      requestFrame: (next) => {
        callback = next
        return 7
      },
      cancelFrame,
    })

    coalescer.submit({ x: 10, y: 20 })
    coalescer.cancel()
    callback?.()

    expect(cancelFrame).toHaveBeenCalledWith(7)
    expect(onMove).not.toHaveBeenCalled()
  })
})
