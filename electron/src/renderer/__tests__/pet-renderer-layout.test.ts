import { describe, expect, it } from 'vitest'
import { getCanvasPointFromClient } from '../pet-renderer-layout'

const createCanvas = (rect: Partial<DOMRect>) => ({
  getBoundingClientRect: () => ({
    left: 0,
    top: 0,
    width: 1000,
    height: 800,
    ...rect,
  }),
}) as unknown as HTMLCanvasElement

describe('pet-renderer-layout', () => {
  it('should use Pixi logical screen coordinates on high-DPI displays', () => {
    expect(getCanvasPointFromClient({
      canvas: createCanvas({ left: 100, top: 50 }),
      app: {
        screen: { width: 1000, height: 800 },
        renderer: { width: 2000, height: 1600, resolution: 2 },
      },
      clientX: 600,
      clientY: 450,
    })).toEqual({ x: 500, y: 400 })
  })

  it('should preserve canvas offsets and intentional CSS scaling', () => {
    expect(getCanvasPointFromClient({
      canvas: createCanvas({ left: 20, top: 30, width: 500, height: 400 }),
      app: {
        screen: { width: 1000, height: 800 },
        renderer: { width: 2000, height: 1600, resolution: 2 },
      },
      clientX: 270,
      clientY: 230,
    })).toEqual({ x: 500, y: 400 })
  })
})
