import { clamp } from './pet-interaction-utils'
import type { PetInteractionBoundsPayload, PetPlacement } from '../shared/pet-control'

const INTERACTION_WIDTH_RATIO = 0.28
const INTERACTION_HEIGHT_RATIO = 0.72
const EDGE_MARGIN = 32

export function computeBaseModelScale(options: {
  cachedBaseScale: number | null
  model: {
    getLocalBounds: () => { width: number; height: number }
    getModelCanvasSize?: (() => { width: number; height: number; pixelsPerUnit?: number } | null) | undefined
  } | null
  viewportWidth: number
  viewportHeight: number
}): { baseScale: number; nextCache: number | null } {
  if (typeof options.cachedBaseScale === 'number' && Number.isFinite(options.cachedBaseScale)) {
    return { baseScale: options.cachedBaseScale, nextCache: options.cachedBaseScale }
  }

  if (!options.model) {
    return { baseScale: 1, nextCache: options.cachedBaseScale }
  }

  try {
    const modelCanvasSize = options.model.getModelCanvasSize?.()
    if (
      modelCanvasSize &&
      Number.isFinite(modelCanvasSize.width) &&
      Number.isFinite(modelCanvasSize.height) &&
      modelCanvasSize.width > 0 &&
      modelCanvasSize.height > 0
    ) {
      const widthScale = (options.viewportWidth * 0.42) / modelCanvasSize.width
      const heightScale = (options.viewportHeight * 0.78) / modelCanvasSize.height
      const nextBaseScale = Math.min(widthScale, heightScale)
      return { baseScale: nextBaseScale, nextCache: nextBaseScale }
    }

    const localBounds = options.model.getLocalBounds()
    const localWidth = Math.max(localBounds.width, 220)
    const localHeight = Math.max(localBounds.height, 360)
    const widthScale = (options.viewportWidth * 0.86) / localWidth
    const heightScale = (options.viewportHeight * 0.92) / localHeight
    const nextBaseScale = Math.min(widthScale, heightScale)
    return { baseScale: nextBaseScale, nextCache: nextBaseScale }
  } catch {
    return { baseScale: 1, nextCache: options.cachedBaseScale }
  }
}

export function computeModelTransform(options: {
  configScale: number
  defaultScale: number
  minScale: number
  maxScale: number
  baseScale: number
  viewportWidth: number
  viewportHeight: number
  positionX?: number | null
  positionY?: number | null
  placement?: PetPlacement
}): {
  nextScale: number
  anchorX: number
  anchorY: number
  interactionBounds: PetInteractionBoundsPayload
} {
  const safeDefaultScale = options.defaultScale > 0 ? options.defaultScale : 1
  const clampedConfigScale = clamp(options.configScale, options.minScale, options.maxScale)
  const minScaleFactor = options.minScale / safeDefaultScale
  const maxScaleFactor = options.maxScale / safeDefaultScale
  const scaleFactor = clamp(clampedConfigScale / safeDefaultScale, minScaleFactor, maxScaleFactor)
  const nextScale = options.baseScale * scaleFactor
  const debugWidth = options.viewportWidth * INTERACTION_WIDTH_RATIO
  const debugHeight = options.viewportHeight * INTERACTION_HEIGHT_RATIO
  const anchor = resolveModelAnchor({
    viewportWidth: options.viewportWidth,
    viewportHeight: options.viewportHeight,
    positionX: options.positionX,
    positionY: options.positionY,
    placement: options.placement,
  })

  return {
    nextScale,
    anchorX: anchor.x,
    anchorY: anchor.y,
    interactionBounds: {
      x: anchor.x - debugWidth / 2,
      y: anchor.y - debugHeight,
      width: debugWidth,
      height: debugHeight,
    },
  }
}

export function resolveModelAnchor(options: {
  viewportWidth: number
  viewportHeight: number
  positionX?: number | null
  positionY?: number | null
  placement?: PetPlacement
}): { x: number; y: number } {
  const debugWidth = options.viewportWidth * INTERACTION_WIDTH_RATIO
  const debugHeight = options.viewportHeight * INTERACTION_HEIGHT_RATIO
  const safeMargin = Math.min(EDGE_MARGIN, Math.max(12, Math.min(options.viewportWidth, options.viewportHeight) * 0.04))
  const leftAnchor = debugWidth / 2 + safeMargin
  const rightAnchor = options.viewportWidth - debugWidth / 2 - safeMargin
  const bottomAnchor = options.viewportHeight - safeMargin
  const topAnchor = debugHeight + safeMargin
  const centerAnchorY = clamp(options.viewportHeight / 2 + debugHeight / 2, topAnchor, bottomAnchor)
  const placement = options.placement ?? 'bottom-right'
  const presetAnchor = (() => {
    switch (placement) {
      case 'bottom-left':
        return { x: leftAnchor, y: bottomAnchor }
      case 'top-right':
        return { x: rightAnchor, y: topAnchor }
      case 'top-left':
        return { x: leftAnchor, y: topAnchor }
      case 'center':
        return { x: options.viewportWidth / 2, y: centerAnchorY }
      case 'free':
      case 'bottom-right':
      default:
        return { x: rightAnchor, y: bottomAnchor }
    }
  })()

  return {
    x: typeof options.positionX === 'number'
      ? clamp(options.positionX, leftAnchor, rightAnchor)
      : presetAnchor.x,
    y: typeof options.positionY === 'number'
      ? clamp(options.positionY, topAnchor, bottomAnchor)
      : presetAnchor.y,
  }
}
