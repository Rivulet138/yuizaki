import { describe, expect, it } from 'vitest'
import {
  computeDragDelta,
  resolveContextMenu,
  resolveDragEnd,
  resolveMouseDown,
  resolveMouseLeave,
  resolveMouseMove,
  resolveMouseUp,
  resolvePointerDragStart,
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

  it('should allow adjustment drags to start anywhere in the work area', () => {
    expect(resolvePointerDragStart({
      button: 0,
      hitModel: false,
      interactMode: true,
      locked: false,
    })).toEqual({ shouldStart: true, modelInteraction: false })

    expect(resolvePointerDragStart({
      button: 0,
      hitModel: false,
      interactMode: false,
      locked: false,
    })).toEqual({ shouldStart: false, modelInteraction: false })
  })

  it('should keep locked, right-button, and normal blank-area input from starting a drag', () => {
    expect(resolvePointerDragStart({
      button: 0,
      hitModel: true,
      interactMode: true,
      locked: true,
    }).shouldStart).toBe(false)
    expect(resolvePointerDragStart({
      button: 2,
      hitModel: true,
      interactMode: true,
      locked: false,
    }).shouldStart).toBe(false)
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
