export interface PetRenderBudgetInput {
  hardwareConcurrency?: number
  deviceMemory?: number
}

export interface PetRenderBudget {
  dprCap: number
  antialias: boolean
  powerPreference: 'high-performance' | 'low-power'
}

const finitePositive = (value: number | undefined): number | undefined => (
  typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : undefined
)

/** Keep the transparent pet responsive on older laptops without changing model behavior. */
export const resolvePetRenderBudget = (input: PetRenderBudgetInput = {}): PetRenderBudget => {
  const cores = finitePositive(input.hardwareConcurrency)
  const memory = finitePositive(input.deviceMemory)
  const lowPower = (cores !== undefined && cores <= 4) || (memory !== undefined && memory <= 4)
  const constrained = !lowPower && ((cores !== undefined && cores <= 8) || (memory !== undefined && memory <= 8))

  if (lowPower) {
    return { dprCap: 1, antialias: false, powerPreference: 'low-power' }
  }
  if (constrained) {
    return { dprCap: 1.25, antialias: true, powerPreference: 'low-power' }
  }
  return { dprCap: 1.5, antialias: true, powerPreference: 'high-performance' }
}
