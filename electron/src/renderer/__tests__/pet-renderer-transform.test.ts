import { describe, expect, it } from 'vitest'
import {
  clampVisualAnchorToViewport,
  computeBaseModelScale,
  computeModelTransform,
  isAlphaBoundsClipped,
  mapAlphaBoundsToLocalBounds,
  projectLocalVisualBounds,
  resolveModelAnchor,
  resolveVisualPlacementOffset,
  resolveViewportAnchorOffset,
  scanAlphaBounds,
} from '../pet-renderer-transform'

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

  it('should cap the default model scale so docked pets stay inside the viewport', () => {
    const result = computeBaseModelScale({
      cachedBaseScale: null,
      model: {
        getModelCanvasSize: () => ({ width: 320, height: 320 }),
        getLocalBounds: () => ({ width: 320, height: 320 }),
      },
      viewportWidth: 2560,
      viewportHeight: 1440,
    })

    expect(result.baseScale).toBeLessThanOrEqual(0.72)
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

  it('should clamp explicit free positions to the full work area instead of the model-sized interaction box', () => {
    expect(resolveModelAnchor({
      viewportWidth: 1000,
      viewportHeight: 800,
      placement: 'free',
      positionX: 9999,
      positionY: -50,
    })).toEqual({ x: 968, y: 32 })

    expect(resolveModelAnchor({
      viewportWidth: 1000,
      viewportHeight: 800,
      placement: 'free',
      positionX: 40,
      positionY: 740,
    })).toEqual({ x: 40, y: 740 })
  })

  it('should normalize free anchors for screen-space runtimes such as VRM', () => {
    const corner = resolveViewportAnchorOffset({
      viewportWidth: 1000,
      viewportHeight: 800,
      placement: 'free',
      positionX: 968,
      positionY: 32,
    })
    expect(corner.x).toBeCloseTo(0.936)
    expect(corner.y).toBeCloseTo(0.92)

    expect(resolveViewportAnchorOffset({
      viewportWidth: 1000,
      viewportHeight: 800,
      placement: 'free',
      positionX: 500,
      positionY: 400,
    })).toEqual({ x: 0, y: 0 })
  })

  it('should clamp the visual bottom-center anchor to the viewport instead of the Pixi container origin', () => {
    expect(clampVisualAnchorToViewport({
      candidateX: 1200,
      candidateY: 1600,
      visualWidth: 400,
      visualHeight: 600,
      viewportWidth: 1000,
      viewportHeight: 1200,
    })).toEqual({ x: 800, y: 1200 })
  })

  it('should keep an oversized model recoverable while still allowing edge docking', () => {
    expect(clampVisualAnchorToViewport({
      candidateX: -9999,
      candidateY: 9999,
      visualWidth: 1200,
      visualHeight: 1600,
      viewportWidth: 1000,
      viewportHeight: 1200,
      minimumVisible: 48,
    })).toEqual({ x: -552, y: 2752 })
  })

  it('should align free and docked placement to the measured visual bounds', () => {
    const visualBounds = { x: 300, y: 200, width: 400, height: 600 }
    expect(resolveVisualPlacementOffset({
      placement: 'free',
      visualBounds,
      viewportWidth: 1000,
      viewportHeight: 1200,
      desiredX: 600,
      desiredY: 1200,
    })).toEqual({ x: 100, y: 400 })
    expect(resolveVisualPlacementOffset({
      placement: 'bottom-right',
      visualBounds,
      viewportWidth: 1000,
      viewportHeight: 1200,
      desiredX: 0,
      desiredY: 0,
    })).toEqual({ x: 268, y: 368 })
  })

  it('should scan visible alpha while ignoring fully transparent padding', () => {
    const pixels = new Uint8ClampedArray(6 * 5 * 4)
    const setAlpha = (x: number, y: number, alpha: number) => {
      pixels[(y * 6 + x) * 4 + 3] = alpha
    }
    setAlpha(1, 1, 3)
    setAlpha(2, 2, 255)
    setAlpha(4, 3, 64)

    expect(scanAlphaBounds({
      pixels,
      width: 6,
      height: 5,
      alphaThreshold: 8,
    })).toEqual({ x: 2, y: 2, width: 3, height: 2 })
  })

  it('should return no visual bounds for an entirely transparent extraction', () => {
    expect(scanAlphaBounds({
      pixels: new Uint8ClampedArray(4 * 3 * 4),
      width: 4,
      height: 3,
    })).toBeNull()
  })

  it('should reject alpha bounds that touch the framebuffer edge as clipped measurements', () => {
    expect(isAlphaBoundsClipped({
      alphaBounds: { x: 2417, y: 156, width: 145, height: 649 },
      width: 2562,
      height: 1530,
    })).toBe(true)

    expect(isAlphaBoundsClipped({
      alphaBounds: { x: 400, y: 180, width: 500, height: 700 },
      width: 2562,
      height: 1530,
    })).toBe(false)
  })

  it('should map extracted pixels back to local coordinates and scale the cached bounds', () => {
    const localBounds = mapAlphaBoundsToLocalBounds({
      extractionFrame: { x: -200, y: -900, width: 400, height: 900 },
      pixelWidth: 200,
      pixelHeight: 450,
      alphaBounds: { x: 20, y: 30, width: 160, height: 370 },
    })
    expect(localBounds).toEqual({ x: -160, y: -840, width: 320, height: 740 })
    expect(projectLocalVisualBounds({
      localBounds,
      positionX: 500,
      positionY: 1000,
      scaleX: 0.5,
      scaleY: 0.5,
    })).toEqual({ x: 420, y: 580, width: 160, height: 370 })
  })
})
