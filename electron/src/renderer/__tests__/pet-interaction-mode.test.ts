import { describe, expect, it } from 'vitest'
import { resolveInteractionMode } from '../pet-interaction-mode'

describe('pet-interaction-mode', () => {
  it('keeps transparent areas click-through while position is locked', () => {
    const result = resolveInteractionMode({
      locked: true,
      isDraggingWindow: false,
      hoveringInteractionArea: false,
      interactMode: false,
    })

    expect(result.state).toBe('locked')
    expect(result.shouldIgnoreMouse).toBe(true)
    expect(result.cursor).toBe('default')
  })

  it('allows model hit area capture while position is locked', () => {
    const result = resolveInteractionMode({
      locked: true,
      isDraggingWindow: false,
      hoveringInteractionArea: true,
      interactMode: true,
    })

    expect(result.state).toBe('locked')
    expect(result.shouldIgnoreMouse).toBe(false)
    expect(result.cursor).toBe('pointer')
  })

  it('captures the full display while explicit adjustment mode is active', () => {
    const result = resolveInteractionMode({
      locked: false,
      isDraggingWindow: false,
      hoveringInteractionArea: false,
      interactMode: true,
    })

    expect(result.state).toBe('adjusting')
    expect(result.shouldIgnoreMouse).toBe(false)
    expect(result.cursor).toBe('default')
  })

  it('shows a grab cursor over the model during adjustment', () => {
    expect(resolveInteractionMode({
      locked: false,
      isDraggingWindow: false,
      hoveringInteractionArea: true,
      interactMode: true,
    })).toEqual({ state: 'adjusting', shouldIgnoreMouse: false, cursor: 'grab' })
  })

  it('keeps dragging feedback above adjustment feedback', () => {
    expect(resolveInteractionMode({
      locked: false,
      isDraggingWindow: true,
      hoveringInteractionArea: false,
      interactMode: true,
    })).toEqual({ state: 'dragging', shouldIgnoreMouse: false, cursor: 'grabbing' })
  })

  it('captures normal model hits and passes through normal empty space', () => {
    expect(resolveInteractionMode({
      locked: false,
      isDraggingWindow: false,
      hoveringInteractionArea: true,
      interactMode: false,
    })).toEqual({ state: 'interactive', shouldIgnoreMouse: false, cursor: 'pointer' })

    expect(resolveInteractionMode({
      locked: false,
      isDraggingWindow: false,
      hoveringInteractionArea: false,
      interactMode: false,
    })).toEqual({ state: 'passthrough', shouldIgnoreMouse: true, cursor: 'default' })
  })
})
