import { describe, expect, it } from 'vitest'
import {
  normalizedRegionFromPointerDrag,
  normalizedRegionFromWorkspace,
  workspaceRegionFromNormalized,
} from '../vision/region-selection'

describe('vision region selection', () => {
  it('maps workspace coordinates to the preview coordinate system', () => {
    expect(normalizedRegionFromWorkspace(
      { x: 480, y: 270, width: 960, height: 540 },
      { width: 1920, height: 1080 },
    )).toEqual({ x: 0.25, y: 0.25, width: 0.5, height: 0.5 })
  })

  it('supports reverse pointer drags and clamps them to the preview', () => {
    expect(normalizedRegionFromPointerDrag(
      { x: 260, y: 170 },
      { x: 60, y: 20 },
      { left: 100, top: 50, width: 200, height: 100 },
    )).toEqual({ x: 0, y: 0, width: 0.8, height: 1 })
  })

  it('keeps the applied workspace region inside the selected display', () => {
    expect(workspaceRegionFromNormalized(
      { x: 0.98, y: 0.98, width: 0.01, height: 0.01 },
      { width: 1920, height: 1080 },
    )).toEqual({ x: 1882, y: 1058, width: 38, height: 22 })
  })

  it('enforces the minimum capture size when room is available', () => {
    expect(workspaceRegionFromNormalized(
      { x: 0.5, y: 0.5, width: 0, height: 0 },
      { width: 1920, height: 1080 },
    )).toEqual({ x: 960, y: 540, width: 64, height: 64 })
  })
})
