import { describe, expect, it } from 'vitest'
import {
  applyBlackPrivacyMasks,
  mapLogicalRegionToPixels,
  normalizeLogicalScreenRegion,
} from '../screen-privacy-mask'

describe('screen privacy masks', () => {
  it('normalizes absolute multi-display coordinates into display-local coordinates', () => {
    expect(normalizeLogicalScreenRegion(
      { x: 150, y: 75, width: 80, height: 40 },
      { x: 100, y: 50, width: 200, height: 100 },
    )).toEqual({ x: 50, y: 25, width: 80, height: 40 })
  })

  it('maps only the intersection with a cropped viewport into output pixels', () => {
    expect(mapLogicalRegionToPixels(
      { x: 40, y: 30, width: 80, height: 60 },
      { x: 60, y: 50, width: 100, height: 50 },
      { width: 200, height: 100 },
    )).toEqual({ x: 0, y: 0, width: 120, height: 80 })
  })

  it('replaces selected bitmap pixels with opaque black pixels', () => {
    const bitmap = Buffer.alloc(4 * 3 * 4, 50)
    applyBlackPrivacyMasks(bitmap, { width: 4, height: 3 }, [
      { x: 1, y: 1, width: 2, height: 1 },
    ])

    const pixel = (x: number, y: number) => [...bitmap.subarray((y * 4 + x) * 4, (y * 4 + x + 1) * 4)]
    expect(pixel(0, 1)).toEqual([50, 50, 50, 50])
    expect(pixel(1, 1)).toEqual([0, 0, 0, 255])
    expect(pixel(2, 1)).toEqual([0, 0, 0, 255])
    expect(pixel(3, 1)).toEqual([50, 50, 50, 50])
  })
})
