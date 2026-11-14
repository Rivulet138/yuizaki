type SettingsRecord = Record<string, unknown>

const isRecord = (value: unknown): value is SettingsRecord =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

export const snapshotSettingsDraft = <T>(value: T): T => value === undefined ? value : JSON.parse(JSON.stringify(value)) as T

// Reconcile a normalized readback while keeping edits made since the request began.
// Queued fields also count as edits when the user changed away and back again.
export const restoreLaterSettingsDraft = (
  normalized: SettingsRecord,
  before: SettingsRecord,
  current: SettingsRecord,
  queued: SettingsRecord = {},
): void => {
  for (const [key, value] of Object.entries(current)) {
    const protectedField = Object.prototype.hasOwnProperty.call(queued, key)
    if (isRecord(value) && isRecord(before[key]) && isRecord(normalized[key])) {
      restoreLaterSettingsDraft(normalized[key], before[key], value, isRecord(queued[key]) ? queued[key] : {})
    } else if (protectedField || JSON.stringify(value) !== JSON.stringify(before[key])) {
      normalized[key] = snapshotSettingsDraft(value)
    }
  }
}

export const settingValueAt = (settings: unknown, key: string): unknown => {
  let value = settings
  for (const part of key.split('.')) {
    if (!isRecord(value) || !Object.prototype.hasOwnProperty.call(value, part)) return undefined
    value = value[part]
  }
  return value
}

export const parseSettingInput = (raw: string, mode: 'json' | 'string', expected: unknown): unknown => {
  const value: unknown = mode === 'string' ? raw : JSON.parse(raw)
  const kind = (item: unknown) => Array.isArray(item) ? 'array' : item === null ? 'null' : typeof item
  if (expected !== undefined && kind(value) !== kind(expected)) throw new TypeError('setting-type-mismatch')
  if (typeof value === 'number' && !Number.isFinite(value)) throw new TypeError('setting-type-mismatch')
  return value
}

// Protect drafts that were already dirty before a request started, except fields
// included in that request (those need the server's normalized readback).
export const unsentSettingsDraft = (baseline: SettingsRecord, draft: SettingsRecord, submitted: SettingsRecord = {}): SettingsRecord => {
  const dirty: SettingsRecord = {}
  for (const [key, value] of Object.entries(draft)) {
    if (isRecord(value) && isRecord(baseline[key])) {
      const nested = unsentSettingsDraft(baseline[key], value, isRecord(submitted[key]) ? submitted[key] : {})
      if (Object.keys(nested).length) dirty[key] = nested
    } else if (!Object.prototype.hasOwnProperty.call(submitted, key) && JSON.stringify(value) !== JSON.stringify(baseline[key])) {
      dirty[key] = snapshotSettingsDraft(value)
    }
  }
  return dirty
}
