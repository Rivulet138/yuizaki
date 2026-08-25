import manifestJson from './runtime-protocol-manifest.json'

type JsonScalarType = 'string' | 'number' | 'integer' | 'boolean' | 'object' | 'array' | 'null'
export type ProtocolSchema = {
  type?: JsonScalarType
  const?: string | number | boolean | null
  oneOf?: ProtocolSchema[]
  required?: Record<string, ProtocolSchema>
  optional?: Record<string, ProtocolSchema>
}

type ProtocolInteraction = {
  channel: 'http' | 'socket'
  direction: string
  name: string
  min: number
  max: number
  order: number
}

type ProtocolManifest = typeof manifestJson
export const runtimeProtocolManifest: ProtocolManifest = manifestJson
export const runtimeProtocolHash = '11d3256146f8e31a18d5f538eff800201db5832461522355b6d89c32256ba3ca'
export const SocketEvents = runtimeProtocolManifest.production_protocol.socket_events
export type SocketEventName = typeof SocketEvents[keyof typeof SocketEvents]

const valueType = (value: unknown): JsonScalarType => {
  if (value === null) return 'null'
  if (Array.isArray(value)) return 'array'
  return typeof value as JsonScalarType
}

export const matchProtocolPayload = (schema: ProtocolSchema, value: unknown): { ok: boolean; errors: string[] } => {
  if (schema.oneOf) {
    const matches = schema.oneOf.map((candidate) => matchProtocolPayload(candidate, value))
    const successCount = matches.filter((result) => result.ok).length
    return successCount === 1
      ? { ok: true, errors: [] }
      : { ok: false, errors: [`expected exactly one schema match, received ${successCount}`] }
  }
  if ('const' in schema && value !== schema.const) {
    return { ok: false, errors: [`expected constant ${JSON.stringify(schema.const)}`] }
  }
  if (schema.type) {
    const actual = valueType(value)
    const valid = schema.type === 'integer' ? Number.isInteger(value) : actual === schema.type
    if (!valid) return { ok: false, errors: [`expected ${schema.type}, received ${actual}`] }
  }
  if (schema.type === 'object') {
    const objectValue = value as Record<string, unknown>
    const errors: string[] = []
    for (const [key, fieldSchema] of Object.entries(schema.required ?? {})) {
      if (!(key in objectValue)) {
        errors.push(`missing required key ${key}`)
        continue
      }
      errors.push(...matchProtocolPayload(fieldSchema, objectValue[key]).errors.map((error) => `${key}: ${error}`))
    }
    for (const [key, fieldSchema] of Object.entries(schema.optional ?? {})) {
      if (key in objectValue) {
        errors.push(...matchProtocolPayload(fieldSchema, objectValue[key]).errors.map((error) => `${key}: ${error}`))
      }
    }
    return { ok: errors.length === 0, errors }
  }
  return { ok: true, errors: [] }
}

export type LedgerEntry = Pick<ProtocolInteraction, 'channel' | 'direction' | 'name'>

type LedgerState = {
  expectationCounts: number[]
  highestOrder: number
}

export class ProtocolLedger {
  private readonly expected: ProtocolInteraction[]
  private readonly counts = new Map<string, number>()
  private readonly unexpected: string[] = []
  private states: LedgerState[]

  constructor(caseId: keyof ProtocolManifest['cases']) {
    this.expected = runtimeProtocolManifest.cases[caseId].interactions as ProtocolInteraction[]
    this.states = [{
      expectationCounts: Array.from({ length: this.expected.length }, () => 0),
      highestOrder: 0,
    }]
  }

  private key(entry: LedgerEntry): string {
    return `${entry.channel} ${entry.direction} ${entry.name}`
  }

  record(entry: LedgerEntry): void {
    const key = this.key(entry)
    const matchingIndices = this.expected
      .map((candidate, index) => this.key(candidate) === key ? index : -1)
      .filter((index) => index >= 0)
    if (matchingIndices.length === 0) {
      this.unexpected.push(key)
      return
    }
    const count = (this.counts.get(key) ?? 0) + 1
    this.counts.set(key, count)
    const nextStates: LedgerState[] = []
    let hasRemainingCapacity = false
    for (const state of this.states) {
      for (const index of matchingIndices) {
        const expectation = this.expected[index]!
        if ((state.expectationCounts[index] ?? 0) >= expectation.max) continue
        hasRemainingCapacity = true
        if (expectation.order < state.highestOrder) continue
        const expectationCounts = [...state.expectationCounts]
        expectationCounts[index] = (expectationCounts[index] ?? 0) + 1
        nextStates.push({
          expectationCounts,
          highestOrder: Math.max(state.highestOrder, expectation.order),
        })
      }
    }
    if (nextStates.length === 0) {
      if (hasRemainingCapacity) {
        this.unexpected.push(`${key} out of order`)
        return
      }
      const allowedMax = matchingIndices.reduce((sum, index) => sum + (this.expected[index]?.max ?? 0), 0)
      this.unexpected.push(`${key} exceeded max ${allowedMax}`)
      return
    }
    const uniqueStates = new Map<string, LedgerState>()
    for (const state of nextStates) {
      uniqueStates.set(`${state.highestOrder}:${state.expectationCounts.join(',')}`, state)
    }
    this.states = [...uniqueStates.values()]
  }

  assertComplete(): { ok: boolean; missing: string[]; unexpected: string[] } {
    const deficit = (state: LedgerState): number => this.expected.reduce((total, expectation, index) => (
      total + Math.max(0, expectation.min - (state.expectationCounts[index] ?? 0))
    ), 0)
    const state = [...this.states].sort((left, right) => deficit(left) - deficit(right))[0]!
    const missing = this.expected
      .filter((expectation, index) => (state.expectationCounts[index] ?? 0) < expectation.min)
      .map((expectation) => `${this.key(expectation)} expected ${expectation.min}..${expectation.max}`)
    return { ok: missing.length === 0 && this.unexpected.length === 0, missing, unexpected: [...this.unexpected] }
  }
}
