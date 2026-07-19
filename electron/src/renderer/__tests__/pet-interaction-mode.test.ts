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
})
