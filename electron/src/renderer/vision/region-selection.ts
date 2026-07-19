import type { WorkspaceVisionSettings } from '../../shared/workspace'

export interface VisionDisplaySize {
  width: number
  height: number
}

export interface NormalizedVisionRegion {
  x: number
  y: number
  width: number
  height: number
}

export interface PointerBounds {
  left: number
  top: number
  width: number
  height: number
}

const clamp = (value: number, minimum: number, maximum: number): number =>
  Math.max(minimum, Math.min(maximum, value))

const validDisplaySize = (display: VisionDisplaySize): VisionDisplaySize => ({
  width: Math.max(1, Math.round(Number(display.width) || 1)),
  height: Math.max(1, Math.round(Number(display.height) || 1)),
})

export const normalizedRegionFromWorkspace = (
  region: WorkspaceVisionSettings['region'],
  display: VisionDisplaySize,
): NormalizedVisionRegion => {
  const size = validDisplaySize(display)
  const x = clamp(Number(region.x) / size.width, 0, 1)
  const y = clamp(Number(region.y) / size.height, 0, 1)
  const width = clamp(Number(region.width) / size.width, 0, 1 - x)
  const height = clamp(Number(region.height) / size.height, 0, 1 - y)
  if (width > 0 && height > 0) return { x, y, width, height }
  return { x: 0.1, y: 0.1, width: 0.8, height: 0.8 }
}

export const normalizedRegionFromPointerDrag = (
  start: { x: number; y: number },
  current: { x: number; y: number },
  bounds: PointerBounds,
): NormalizedVisionRegion => {
  const width = Math.max(1, Number(bounds.width) || 1)
  const height = Math.max(1, Number(bounds.height) || 1)
  const startX = clamp((start.x - bounds.left) / width, 0, 1)
  const startY = clamp((start.y - bounds.top) / height, 0, 1)
  const currentX = clamp((current.x - bounds.left) / width, 0, 1)
  const currentY = clamp((current.y - bounds.top) / height, 0, 1)
  return {
    x: Math.min(startX, currentX),
    y: Math.min(startY, currentY),
    width: Math.abs(currentX - startX),
    height: Math.abs(currentY - startY),
  }
}

export const workspaceRegionFromNormalized = (
  selection: NormalizedVisionRegion,
  display: VisionDisplaySize,
  minimumSize = 64,
): WorkspaceVisionSettings['region'] => {
  const size = validDisplaySize(display)
  const x = clamp(Math.round(selection.x * size.width), 0, Math.max(0, size.width - 1))
  const y = clamp(Math.round(selection.y * size.height), 0, Math.max(0, size.height - 1))
  const minWidth = Math.min(minimumSize, size.width - x)
  const minHeight = Math.min(minimumSize, size.height - y)
  const width = clamp(Math.round(selection.width * size.width), minWidth, size.width - x)
  const height = clamp(Math.round(selection.height * size.height), minHeight, size.height - y)
  return { x, y, width, height }
}
