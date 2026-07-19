import * as PIXI from 'pixi.js'
import type { PetInteractionBoundsPayload } from '../shared/pet-control'
import { logger } from './logger'

export function getInteractionBounds(
  bounds: PetInteractionBoundsPayload | null,
  buffer = 0,
): PIXI.Rectangle | null {
  if (!bounds) {
    return null
  }

  return new PIXI.Rectangle(
    bounds.x - buffer,
    bounds.y - buffer,
    bounds.width + buffer * 2,
    bounds.height + buffer * 2,
  )
}

export function isPointInsideInteractionArea(options: {
  model: { containsPoint?: ((point: { x: number; y: number }) => boolean) | undefined } | null
  x: number
  y: number
  bounds: PIXI.Rectangle | null
}): boolean {
  if (!options.model) {
    return false
  }

  try {
    const containsPoint = options.model.containsPoint
    if (typeof containsPoint === 'function' && containsPoint.call(options.model, { x: options.x, y: options.y })) {
      return true
    }
  } catch (error) {
    logger.warn('[PetRenderer] containsPoint hit test failed:', error)
  }

  return options.bounds ? options.bounds.contains(options.x, options.y) : false
}

export function getCanvasPointFromClient(options: {
  canvas: HTMLCanvasElement | null
  app: { renderer: { width: number; height: number } } | null
  clientX: number
  clientY: number
}): { x: number; y: number } | null {
  if (!options.canvas || !options.app) {
    return null
  }

  const rect = options.canvas.getBoundingClientRect()
  if (rect.width <= 0 || rect.height <= 0) {
    return null
  }

  const scaleX = options.app.renderer.width / rect.width
  const scaleY = options.app.renderer.height / rect.height

  return {
    x: (options.clientX - rect.left) * scaleX,
    y: (options.clientY - rect.top) * scaleY,
  }
}
