import { describe, expect, it, vi } from 'vitest'
import {
  AlphaHitTestScheduler,
  computeDragDelta,
  resolveContextMenu,
  resolveDragEnd,
  resolveMouseDown,
  resolveMouseLeave,
  resolveMouseMove,
  resolveMouseUp,
  resolveWheel,
} from '../pet-interaction-controller'

describe('pet-interaction-controller', () => {
  it('should ignore non-left-button mousedown', () => {
    const result = resolveMouseDown({
      button: 1,
      clientX: 10,
      clientY: 20,
    })
    expect(result.shouldIgnore).toBe(true)
  })

  it('should compute drag delta from screen coordinates', () => {
    const event = { screenX: 140, screenY: 240, clientX: 15, clientY: 25 } as MouseEvent
    const result = computeDragDelta(
      {
        dragLastScreen: { x: 100, y: 200 },
        dragLastClient: { x: 10, y: 20 },
      },
      event,
    )

    expect(result?.deltaX).toBe(40)
    expect(result?.deltaY).toBe(40)
  })

  it('should resolve mouse move only when dragging', () => {
    const event = { screenX: 110, screenY: 205, clientX: 11, clientY: 21 } as MouseEvent
    expect(
      resolveMouseMove({ isDraggingWindow: false, dragLastScreen: { x: 100, y: 200 }, dragLastClient: null }, event),
    ).toBeNull()
  })

  it('should trigger click only when not moved and not dragging', () => {
    expect(
      resolveMouseUp({ button: 0, moved: false, mouseDownOnModel: true, isDraggingWindow: false }),
    ).toBe(true)

    expect(
      resolveMouseUp({ button: 0, moved: true, mouseDownOnModel: true, isDraggingWindow: false }),
    ).toBe(false)
  })

  it('should handle context menu only inside interaction area', () => {
    expect(resolveContextMenu({ hasPoint: true, insideInteractionArea: true })).toBe(true)
    expect(resolveContextMenu({ hasPoint: false, insideInteractionArea: true })).toBe(false)
  })

  it('should produce wheel scale update inside interaction area', () => {
    const result = resolveWheel({
      isDraggingWindow: false,
      buttons: 0,
      hasPoint: true,
      insideInteractionArea: true,
      currentScale: 0.3,
      minScale: 0.12,
      maxScale: 0.6,
      deltaY: -100,
    })

    expect(result.shouldIgnore).toBe(false)
    if (!result.shouldIgnore) {
      expect(result.nextScale).toBeGreaterThan(0.3)
    }
  })

  it('should resolve mouse leave only when not dragging window', () => {
    expect(resolveMouseLeave({ isDraggingWindow: false })).toBe(true)
    expect(resolveMouseLeave({ isDraggingWindow: true })).toBe(false)
  })

  it('should resolve drag end metadata', () => {
    const result = resolveDragEnd(true, 123)
    expect(result.shouldFinish).toBe(true)
    expect(result.draggedAt).toBe(123)
    expect(result.nextDragCooldownUntil).toBeGreaterThan(123)
  })
})

describe('AlphaHitTestScheduler', () => {
  it('limits 125Hz pointer input to one hit test every 250ms', async () => {
    vi.useFakeTimers()
    const startedAt: number[] = []
    const execute = vi.fn(async () => {
      startedAt.push(Date.now())
      return true
    })
    const scheduler = new AlphaHitTestScheduler({ execute, onResult: vi.fn() })

    for (let index = 0; index < 125; index += 1) {
      scheduler.request({ x: index * 5, y: index * 5 })
      await vi.advanceTimersByTimeAsync(8)
    }

    expect(execute.mock.calls.length).toBeLessThanOrEqual(5)
    expect(startedAt.slice(1).every((time, index) => time - startedAt[index] >= 250)).toBe(true)
    scheduler.dispose()
    vi.useRealTimers()
  })

  it('keeps at most one hit test in flight and runs only the latest pending point', async () => {
    vi.useFakeTimers()
    const resolvers: Array<(value: boolean) => void> = []
    let concurrent = 0
    let maxConcurrent = 0
    const execute = vi.fn((_point: { x: number; y: number }) => {
      concurrent += 1
      maxConcurrent = Math.max(maxConcurrent, concurrent)
      return new Promise<boolean>((resolve) => {
        resolvers.push((value) => {
          concurrent -= 1
          resolve(value)
        })
      })
    })
    const scheduler = new AlphaHitTestScheduler({ execute, onResult: vi.fn() })

    scheduler.request({ x: 0, y: 0 })
    await vi.advanceTimersByTimeAsync(0)
    scheduler.request({ x: 10, y: 10 })
    scheduler.request({ x: 20, y: 20 })
    await vi.advanceTimersByTimeAsync(500)

    expect(execute).toHaveBeenCalledTimes(1)
    resolvers[0]?.(true)
    await vi.advanceTimersByTimeAsync(0)
    expect(execute).toHaveBeenCalledTimes(2)
    expect(execute).toHaveBeenLastCalledWith({ x: 20, y: 20 })
    expect(maxConcurrent).toBe(1)

    resolvers[1]?.(true)
    await vi.advanceTimersByTimeAsync(0)
    scheduler.dispose()
    vi.useRealTimers()
  })

  it('deduplicates identical and nearby points', async () => {
    const execute = vi.fn(async () => true)
    const scheduler = new AlphaHitTestScheduler({ execute, onResult: vi.fn() })

    expect(scheduler.request({ x: 40, y: 50 })).toBe(true)
    expect(scheduler.request({ x: 40, y: 50 })).toBe(false)
    expect(scheduler.request({ x: 43, y: 47 })).toBe(false)
    await Promise.resolve()
    await Promise.resolve()

    expect(execute).toHaveBeenCalledTimes(1)
    scheduler.dispose()
  })

  it('does not publish a result after a newer request invalidates it', async () => {
    vi.useFakeTimers()
    const resolvers: Array<(value: boolean) => void> = []
    const onResult = vi.fn()
    const scheduler = new AlphaHitTestScheduler({
      execute: () => new Promise<boolean>((resolve) => resolvers.push(resolve)),
      onResult,
    })

    scheduler.request({ x: 0, y: 0 })
    await vi.advanceTimersByTimeAsync(0)
    scheduler.request({ x: 10, y: 10 })
    resolvers[0]?.(true)
    await vi.advanceTimersByTimeAsync(250)

    expect(onResult).not.toHaveBeenCalled()
    resolvers[1]?.(false)
    await vi.advanceTimersByTimeAsync(0)
    expect(onResult).toHaveBeenCalledOnce()
    expect(onResult).toHaveBeenCalledWith(false, { x: 10, y: 10 })

    scheduler.dispose()
    vi.useRealTimers()
  })

  it('does not publish an in-flight result after disposal', async () => {
    let resolve: ((value: boolean) => void) | null = null
    const onResult = vi.fn()
    const scheduler = new AlphaHitTestScheduler({
      execute: () => new Promise<boolean>((done) => { resolve = done }),
      onResult,
    })

    scheduler.request({ x: 10, y: 20 })
    await Promise.resolve()
    scheduler.dispose()
    resolve?.(true)
    await Promise.resolve()
    await Promise.resolve()

    expect(onResult).not.toHaveBeenCalled()
  })
})
