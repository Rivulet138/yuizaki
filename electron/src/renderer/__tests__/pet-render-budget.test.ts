import { describe, expect, it } from 'vitest'
import { resolvePetRenderBudget } from '../pet-render-budget'

describe('pet render budget', () => {
  it('keeps full quality when hardware signals are unavailable', () => {
    expect(resolvePetRenderBudget()).toEqual({
      dprCap: 1.5,
      antialias: true,
      powerPreference: 'high-performance',
    })
  })

  it('uses a low-power budget on older hardware', () => {
    expect(resolvePetRenderBudget({ hardwareConcurrency: 4, deviceMemory: 4 })).toEqual({
      dprCap: 1,
      antialias: false,
      powerPreference: 'low-power',
    })
  })

  it('uses a constrained budget for mid-range hardware', () => {
    expect(resolvePetRenderBudget({ hardwareConcurrency: 8, deviceMemory: 8 })).toEqual({
      dprCap: 1.25,
      antialias: true,
      powerPreference: 'low-power',
    })
  })
})
