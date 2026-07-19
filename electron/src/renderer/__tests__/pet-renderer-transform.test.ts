import { describe, expect, it } from 'vitest'
import { computeBaseModelScale, computeModelTransform, resolveModelAnchor } from '../pet-renderer-transform'

describe('pet-renderer-transform', () => {
  it('should reuse cached base scale when available', () => {
    const result = computeBaseModelScale({
      cachedBaseScale: 1.23,
      model: null,
      viewportWidth: 1000,
      viewportHeight: 800,
    })

    expect(result.baseScale).toBe(1.23)
    expect(result.nextCache).toBe(1.23)
  })

  it('should compute base scale from model bounds', () => {
    const result = computeBaseModelScale({
      cachedBaseScale: null,
      model: {
        getLocalBounds: () => ({ width: 500, height: 1000 }),
      },
      viewportWidth: 1000,
      viewportHeight: 800,
    })

    expect(result.baseScale).toBeGreaterThan(0)
    expect(result.nextCache).toBe(result.baseScale)
  })

  it('should compute docked transform and interaction bounds when no explicit position is provided', () => {
    const result = computeModelTransform({
      configScale: 0.28,
      defaultScale: 0.28,
      minScale: 0.12,
      maxScale: 0.6,
      baseScale: 1,
      viewportWidth: 1000,
      viewportHeight: 800,
    })

    expect(result.nextScale).toBe(1)
    expect(result.anchorX).toBe(828)
    expect(result.anchorY).toBeCloseTo(768)
    expect(result.interactionBounds.width).toBeGreaterThan(0)
    expect(result.interactionBounds.height).toBeGreaterThan(0)
    expect(result.interactionBounds.x + result.interactionBounds.width).toBeLessThanOrEqual(968)
  })

  it('should use explicit position when provided', () => {
    const result = computeModelTransform({
      configScale: 0.28,
      defaultScale: 0.28,
      minScale: 0.12,
      maxScale: 0.6,
      baseScale: 1,
      viewportWidth: 1000,
      viewportHeight: 800,
      positionX: 500,
      positionY: 752,
    })

    expect(result.anchorX).toBe(500)
    expect(result.anchorY).toBe(752)
  })

  it('should resolve placement presets when no explicit position is provided', () => {
    const result = computeModelTransform({
      configScale: 0.28,
      defaultScale: 0.28,
      minScale: 0.12,
      maxScale: 0.6,
      baseScale: 1,
      viewportWidth: 1000,
      viewportHeight: 800,
      placement: 'top-left',
    })

    expect(result.anchorX).toBe(172)
    expect(result.anchorY).toBeCloseTo(608)
    expect(result.interactionBounds.x).toBeGreaterThanOrEqual(32)
    expect(result.interactionBounds.y).toBeGreaterThanOrEqual(32)
  })

  it('should resolve drag anchor from the active placement instead of always bottom-right', () => {
    const anchor = resolveModelAnchor({
      viewportWidth: 1000,
      viewportHeight: 800,
      placement: 'top-left',
    })

    expect(anchor).toEqual({ x: 172, y: 608 })
    expect({
      x: anchor.x + 20,
      y: anchor.y + 10,
    }).toEqual({ x: 192, y: 618 })
  })

  it('should keep explicit free position as the drag anchor', () => {
    expect(resolveModelAnchor({
      viewportWidth: 1000,
      viewportHeight: 800,
      placement: 'free',
      positionX: 420,
      positionY: 620,
    })).toEqual({ x: 420, y: 620 })
  })

  it('should clamp explicit positions into the visible interaction area', () => {
    expect(resolveModelAnchor({
      viewportWidth: 1000,
      viewportHeight: 800,
      placement: 'free',
      positionX: 9999,
      positionY: -50,
    })).toEqual({ x: 828, y: 608 })
  })
})
