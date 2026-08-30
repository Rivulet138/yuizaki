import { clamp } from './pet-interaction-utils'
import type { PetInteractionBoundsPayload, PetPlacement } from '../shared/pet-control'

const INTERACTION_WIDTH_RATIO = 0.28
const INTERACTION_HEIGHT_RATIO = 0.72
const EDGE_MARGIN = 32
const MAX_BASE_MODEL_SCALE = 0.72

export interface VisualBounds {
  x: number
  y: number
  width: number
  height: number
}

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
    // `getModelCanvasSize()` is a Cubism canvas-space measurement. Its units
    // are not guaranteed to match Pixi's local bounds, so do not mix it with
    // CSS viewport pixels when calculating a screen-space scale.
    const localBounds = options.model.getLocalBounds()
    const localWidth = Math.max(localBounds.width, 220)
    const localHeight = Math.max(localBounds.height, 360)
    // Keep the companion visually present on high-resolution desktop windows.
    // The previous fit target made the default model occupy too little of the
    // available work area, especially for tall Live2D assets.
    const widthScale = (options.viewportWidth * 0.36) / localWidth
    const heightScale = (options.viewportHeight * 0.78) / localHeight
    const nextBaseScale = Math.min(MAX_BASE_MODEL_SCALE, widthScale, heightScale)
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
  modelCalibrationScale?: number
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
  const calibrationScale = Number.isFinite(options.modelCalibrationScale) && (options.modelCalibrationScale ?? 0) > 0
    ? Math.min(16, Math.max(0.08, options.modelCalibrationScale ?? 1))
    : 1
  const nextScale = options.baseScale * calibrationScale * scaleFactor
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
  const freeMinX = safeMargin
  const freeMaxX = Math.max(freeMinX, options.viewportWidth - safeMargin)
  const freeMinY = safeMargin
  const freeMaxY = Math.max(freeMinY, options.viewportHeight - safeMargin)
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
      ? clamp(options.positionX, freeMinX, freeMaxX)
      : presetAnchor.x,
    y: typeof options.positionY === 'number'
      ? clamp(options.positionY, freeMinY, freeMaxY)
      : presetAnchor.y,
  }
}

export function resolveViewportAnchorOffset(options: {
  viewportWidth: number
  viewportHeight: number
  positionX?: number | null
  positionY?: number | null
  placement?: PetPlacement
}): { x: number; y: number } {
  const width = Math.max(1, options.viewportWidth)
  const height = Math.max(1, options.viewportHeight)
  const anchor = resolveModelAnchor({
    ...options,
    viewportWidth: width,
    viewportHeight: height,
  })
  return {
    x: (anchor.x / width - 0.5) * 2,
    y: (0.5 - anchor.y / height) * 2,
  }
}

export function clampVisualAnchorToViewport(options: {
  candidateX: number
  candidateY: number
  visualWidth: number
  visualHeight: number
  viewportWidth: number
  viewportHeight: number
  minimumVisible?: number
}): { x: number; y: number } {
  const viewportWidth = Math.max(1, options.viewportWidth)
  const viewportHeight = Math.max(1, options.viewportHeight)
  const visualWidth = Math.max(1, options.visualWidth)
  const visualHeight = Math.max(1, options.visualHeight)
  const minimumVisible = clamp(
    options.minimumVisible ?? 48,
    1,
    Math.max(viewportWidth, viewportHeight),
  )

  const minX = visualWidth <= viewportWidth
    ? visualWidth / 2
    : minimumVisible - visualWidth / 2
  const maxX = visualWidth <= viewportWidth
    ? viewportWidth - visualWidth / 2
    : viewportWidth - minimumVisible + visualWidth / 2
  const minY = visualHeight <= viewportHeight ? visualHeight : minimumVisible
  const maxY = visualHeight <= viewportHeight
    ? viewportHeight
    : viewportHeight - minimumVisible + visualHeight

  return {
    x: clamp(options.candidateX, minX, Math.max(minX, maxX)),
    y: clamp(options.candidateY, minY, Math.max(minY, maxY)),
  }
}

export function resolveVisualPlacementOffset(options: {
  placement: PetPlacement
  visualBounds: VisualBounds
  viewportWidth: number
  viewportHeight: number
  desiredX: number
  desiredY: number
}): { x: number; y: number } {
  const bounds = options.visualBounds
  const centerX = bounds.x + bounds.width / 2
  const centerY = bounds.y + bounds.height / 2
  const right = bounds.x + bounds.width
  const bottom = bounds.y + bounds.height

  switch (options.placement) {
    case 'bottom-left':
      return { x: EDGE_MARGIN - bounds.x, y: options.viewportHeight - EDGE_MARGIN - bottom }
    case 'top-right':
      return { x: options.viewportWidth - EDGE_MARGIN - right, y: EDGE_MARGIN - bounds.y }
    case 'top-left':
      return { x: EDGE_MARGIN - bounds.x, y: EDGE_MARGIN - bounds.y }
    case 'center':
      return {
        x: options.viewportWidth / 2 - centerX,
        y: options.viewportHeight / 2 - centerY,
      }
    case 'free':
      return {
        x: options.desiredX - centerX,
        y: options.desiredY - bottom,
      }
    case 'bottom-right':
    default:
      return {
        x: options.viewportWidth - EDGE_MARGIN - right,
        y: options.viewportHeight - EDGE_MARGIN - bottom,
      }
  }
}

export function scanAlphaBounds(options: {
  pixels: ArrayLike<number>
  width: number
  height: number
  alphaThreshold?: number
}): VisualBounds | null {
  const width = Math.floor(options.width)
  const height = Math.floor(options.height)
  if (width <= 0 || height <= 0 || options.pixels.length < width * height * 4) {
    return null
  }

  const threshold = clamp(options.alphaThreshold ?? 8, 0, 255)
  let minX = width
  let minY = height
  let maxX = -1
  let maxY = -1

  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const alpha = options.pixels[(y * width + x) * 4 + 3] ?? 0
      if (alpha <= threshold) continue
      minX = Math.min(minX, x)
      minY = Math.min(minY, y)
      maxX = Math.max(maxX, x)
      maxY = Math.max(maxY, y)
    }
  }

  return maxX < minX || maxY < minY
    ? null
    : {
        x: minX,
        y: minY,
        width: maxX - minX + 1,
        height: maxY - minY + 1,
      }
}

/**
 * A framebuffer alpha rectangle that touches an edge may be only the visible
 * slice of a model clipped by the viewport. It is not safe to use it as the
 * model's full visual bounds for docking or dragging.
 */
export function isAlphaBoundsClipped(options: {
  alphaBounds: VisualBounds
  width: number
  height: number
  edgeTolerance?: number
}): boolean {
  const width = Math.max(1, Math.floor(options.width))
  const height = Math.max(1, Math.floor(options.height))
  const tolerance = clamp(Math.floor(options.edgeTolerance ?? 1), 0, Math.max(width, height))
  const right = options.alphaBounds.x + options.alphaBounds.width
  const bottom = options.alphaBounds.y + options.alphaBounds.height
  return options.alphaBounds.x <= tolerance
    || options.alphaBounds.y <= tolerance
    || right >= width - tolerance
    || bottom >= height - tolerance
}

export function mapAlphaBoundsToLocalBounds(options: {
  extractionFrame: VisualBounds
  pixelWidth: number
  pixelHeight: number
  alphaBounds: VisualBounds
}): VisualBounds {
  const scaleX = options.extractionFrame.width / Math.max(1, options.pixelWidth)
  const scaleY = options.extractionFrame.height / Math.max(1, options.pixelHeight)
  return {
    x: options.extractionFrame.x + options.alphaBounds.x * scaleX,
    y: options.extractionFrame.y + options.alphaBounds.y * scaleY,
    width: options.alphaBounds.width * scaleX,
    height: options.alphaBounds.height * scaleY,
  }
}

export function projectLocalVisualBounds(options: {
  localBounds: VisualBounds
  positionX: number
  positionY: number
  scaleX: number
  scaleY: number
}): VisualBounds {
  const x1 = options.positionX + options.localBounds.x * options.scaleX
  const x2 = options.positionX + (options.localBounds.x + options.localBounds.width) * options.scaleX
  const y1 = options.positionY + options.localBounds.y * options.scaleY
  const y2 = options.positionY + (options.localBounds.y + options.localBounds.height) * options.scaleY
  return {
    x: Math.min(x1, x2),
    y: Math.min(y1, y2),
    width: Math.abs(x2 - x1),
    height: Math.abs(y2 - y1),
  }
}
