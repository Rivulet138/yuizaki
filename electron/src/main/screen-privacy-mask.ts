import type { Rectangle } from 'electron'

export interface LogicalScreenRegion {
  x: number
  y: number
  width: number
  height: number
}

export interface ScreenSize {
  width: number
  height: number
}

const clamp = (value: number, minimum: number, maximum: number): number =>
  Math.max(minimum, Math.min(maximum, value))

export const normalizeLogicalScreenRegion = (
  value: LogicalScreenRegion,
  displayBounds: Rectangle,
): Rectangle | null => {
  const x = Number(value.x)
  const y = Number(value.y)
  const width = Number(value.width)
  const height = Number(value.height)
  if (![x, y, width, height].every(Number.isFinite) || width <= 0 || height <= 0) return null

  const relativeX = x >= displayBounds.x && x < displayBounds.x + displayBounds.width
    ? x - displayBounds.x
    : x
  const relativeY = y >= displayBounds.y && y < displayBounds.y + displayBounds.height
    ? y - displayBounds.y
    : y
  const normalizedX = clamp(Math.round(relativeX), 0, Math.max(0, displayBounds.width - 1))
  const normalizedY = clamp(Math.round(relativeY), 0, Math.max(0, displayBounds.height - 1))
  return {
    x: normalizedX,
    y: normalizedY,
    width: clamp(Math.round(width), 1, displayBounds.width - normalizedX),
    height: clamp(Math.round(height), 1, displayBounds.height - normalizedY),
  }
}

export const mapLogicalRegionToPixels = (
  region: Rectangle,
  viewport: Rectangle,
  imageSize: ScreenSize,
): Rectangle | null => {
  const left = Math.max(region.x, viewport.x)
  const top = Math.max(region.y, viewport.y)
  const right = Math.min(region.x + region.width, viewport.x + viewport.width)
  const bottom = Math.min(region.y + region.height, viewport.y + viewport.height)
  if (right <= left || bottom <= top) return null

  const scaleX = imageSize.width / Math.max(1, viewport.width)
  const scaleY = imageSize.height / Math.max(1, viewport.height)
  const x = clamp(Math.round((left - viewport.x) * scaleX), 0, Math.max(0, imageSize.width - 1))
  const y = clamp(Math.round((top - viewport.y) * scaleY), 0, Math.max(0, imageSize.height - 1))
  const rightPixel = clamp(Math.round((right - viewport.x) * scaleX), x + 1, imageSize.width)
  const bottomPixel = clamp(Math.round((bottom - viewport.y) * scaleY), y + 1, imageSize.height)
  return { x, y, width: rightPixel - x, height: bottomPixel - y }
}

export const applyBlackPrivacyMasks = (
  bitmap: Buffer,
  imageSize: ScreenSize,
  masks: Rectangle[],
): Buffer => {
  const expectedBytes = imageSize.width * imageSize.height * 4
  if (imageSize.width <= 0 || imageSize.height <= 0 || bitmap.length < expectedBytes) return bitmap

  for (const mask of masks) {
    const x = clamp(Math.round(mask.x), 0, imageSize.width)
    const y = clamp(Math.round(mask.y), 0, imageSize.height)
    const width = clamp(Math.round(mask.width), 0, imageSize.width - x)
    const height = clamp(Math.round(mask.height), 0, imageSize.height - y)
    if (width <= 0 || height <= 0) continue

    const blackRow = Buffer.alloc(width * 4)
    for (let offset = 3; offset < blackRow.length; offset += 4) blackRow[offset] = 255
    for (let row = y; row < y + height; row += 1) {
      blackRow.copy(bitmap, (row * imageSize.width + x) * 4)
    }
  }
  return bitmap
}
