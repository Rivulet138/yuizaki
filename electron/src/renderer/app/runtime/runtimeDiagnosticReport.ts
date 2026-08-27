/**
 * Small, privacy-preserving runtime report for local troubleshooting.
 * This is deliberately separate from the human-readable diagnostic bundle:
 * no free-form strings, identifiers, paths, account data or credentials cross
 * this boundary.
 */

export type RuntimeDiagnosticState =
  | 'unknown'
  | 'ready'
  | 'healthy'
  | 'degraded'
  | 'error'
  | 'offline'
  | 'configured'
  | 'unconfigured'
  | 'available'
  | 'unavailable'
  | 'running'
  | 'stopped'
  | 'executing'
  | 'verified'
  | 'failed'
  | 'cancelled'
  | 'unknown_effect'

export interface RuntimeDiagnosticReport {
  schemaVersion: 1
  report: Record<string, unknown>
}

const stateValues = new Set<RuntimeDiagnosticState>([
  'unknown', 'ready', 'healthy', 'degraded', 'error', 'offline',
  'configured', 'unconfigured', 'available', 'unavailable', 'running',
  'stopped', 'executing', 'verified', 'failed', 'cancelled', 'unknown_effect',
])

const stateKeys = /(?:status|state|availability|health|outcome|qualification|readiness|mode)$/i
const blockedKey = /(?:text|message|detail|description|path|url|account|token|secret|password|credential|authorization|cookie|title|prompt|query|content|reply|error|reason|trace|raw|payload|args|evidence|association|headers?|(?:^|_)(?:key|id|name)(?:$|_)|(?:Key|Id|Name)$)/i

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

const enumValue = (value: unknown): RuntimeDiagnosticState => {
  const normalized = String(value ?? '').trim().toLowerCase().replace(/[\s-]+/g, '_')
  return stateValues.has(normalized as RuntimeDiagnosticState)
    ? normalized as RuntimeDiagnosticState
    : 'unknown'
}

const projectValue = (value: unknown, key = ''): unknown => {
  if (typeof value === 'number') return Number.isFinite(value) ? value : undefined
  if (typeof value === 'boolean') return value
  if (typeof value === 'string') return stateKeys.test(key) ? enumValue(value) : undefined
  if (Array.isArray(value)) {
    const projected = value.map(item => projectValue(item, key)).filter(item => item !== undefined)
    return projected.length ? projected.slice(0, 64) : undefined
  }
  if (!isRecord(value)) return undefined
  const output: Record<string, unknown> = {}
  for (const [childKey, childValue] of Object.entries(value).slice(0, 128)) {
    if (blockedKey.test(childKey)) continue
    const projected = projectValue(childValue, childKey)
    if (projected !== undefined) output[childKey] = projected
  }
  return Object.keys(output).length ? output : undefined
}

/** Project arbitrary runtime snapshots into numeric/boolean/closed-state data. */
export const projectRuntimeDiagnosticReport = (snapshot: unknown): Record<string, unknown> => {
  const projected = projectValue(snapshot)
  return isRecord(projected) ? projected : {}
}

export const createRuntimeDiagnosticReport = (snapshot: unknown): RuntimeDiagnosticReport => ({
  schemaVersion: 1,
  report: projectRuntimeDiagnosticReport(snapshot),
})

export const serializeRuntimeDiagnosticReport = (
  report: RuntimeDiagnosticReport,
): { ok: true; json: string } | { ok: false; reason: 'serialization_failed' } => {
  try {
    return { ok: true, json: `${JSON.stringify(report, null, 2)}\n` }
  } catch {
    return { ok: false, reason: 'serialization_failed' }
  }
}
