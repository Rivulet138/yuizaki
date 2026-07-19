import { describe, expect, it } from 'vitest'
import { hasVisibleAlpha } from '../pet-alpha-hit-test'

describe('pet-alpha-hit-test', () => {
  it('treats transparent pixels as pass-through', () => {
    expect(hasVisibleAlpha(Buffer.from([0, 0, 0, 0]))).toBe(false)
  })

  it('treats visible pixels as interactive', () => {
    expect(hasVisibleAlpha(Buffer.from([0, 0, 0, 255]))).toBe(true)
  })

  it('respects alpha thresholds', () => {
    expect(hasVisibleAlpha(Buffer.from([0, 0, 0, 6]), 8)).toBe(false)
    expect(hasVisibleAlpha(Buffer.from([0, 0, 0, 12]), 8)).toBe(true)
  })

  it('scans the whole captured bitmap for visible pixels', () => {
    expect(hasVisibleAlpha(Buffer.from([
      0, 0, 0, 0,
      0, 0, 0, 0,
      0, 0, 0, 255,
    ]))).toBe(true)
  })
})
