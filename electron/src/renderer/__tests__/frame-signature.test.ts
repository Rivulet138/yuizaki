import { describe, expect, it } from 'vitest'
import { calculateFrameDifference } from '../vision/frame-signature'

describe('visual frame signature', () => {
  it('returns zero for identical signatures', () => {
    const signature = new Uint8Array([10, 20, 30, 40])
    expect(calculateFrameDifference(signature, signature)).toBe(0)
  })

  it('normalizes pixel differences and treats shape changes as a new frame', () => {
    expect(calculateFrameDifference(new Uint8Array([0, 0]), new Uint8Array([255, 255]))).toBe(1)
    expect(calculateFrameDifference(new Uint8Array([0]), new Uint8Array([0, 0]))).toBe(1)
  })
})
