import { ref, shallowRef } from 'vue'
import type { SettingsMutationResponse, SettingsResponse } from '@/api/clients/settings-client'

export type SettingsFieldTokens = Map<string, symbol>
type SettingsSaveFailure = { owner: symbol; fields: Set<string>; error: string }

// JSON paths also distinguish profile keys that contain dots.
export const settingsPatchFields = (patch: Record<string, unknown>, prefix: string[] = []): Array<[string, unknown]> =>
  Object.entries(patch).flatMap(([key, value]) => {
    const path = [...prefix, key]
    return value && typeof value === 'object' && !Array.isArray(value)
      ? settingsPatchFields(value as Record<string, unknown>, path)
      : [[JSON.stringify(path), value] as [string, unknown]]
  })

export const selectSettingsFields = (patch: Record<string, unknown>, accept: (path: string) => boolean, prefix: string[] = []): Record<string, unknown> =>
  Object.fromEntries(Object.entries(patch).flatMap(([key, value]) => {
    const path = [...prefix, key]
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      const nested = selectSettingsFields(value as Record<string, unknown>, accept, path)
      return Object.keys(nested).length ? [[key, nested]] : []
    }
    return accept(JSON.stringify(path)) ? [[key, value]] : []
  }))

// Settings are global. Keep pending writes and recovery in application memory,
// independently of workspace panels and their KeepAlive eviction. Never persist secrets here.
const createSaveState = () => ({
  pending: ref<Record<string, unknown> | null>(null),
  failed: ref<Record<string, unknown> | null>(null),
  active: shallowRef<Record<string, unknown> | null>(null),
  pendingFields: new Map<string, symbol>(),
  failedFields: new Map<string, symbol>(),
  activeFields: new Map<string, symbol>(),
  failureScopes: shallowRef(new Map<symbol, SettingsSaveFailure>()),
  inFlight: ref(false),
  readbackFailed: ref(false),
  deletingKeys: ref(new Set<string>()),
  completion: shallowRef<(SettingsMutationResponse & { normalizedSettings: SettingsResponse; submitted: Record<string, unknown>; owner: symbol; fields?: SettingsFieldTokens; recoveredFailures?: Set<symbol>; deletedKeys?: string[] }) | null>(null),
  queuedAt: null as number | null,
  timeout: null as ReturnType<typeof setTimeout> | null,
  failures: 0,
  idleResolvers: [] as Array<(value: boolean) => void>,
  adminInFlight: false,
  adminResolvers: [] as Array<() => void>,
})

export const settingsSaveState = createSaveState()

// Only a successful write/delete can resolve a failed field. Removing a draft
// from the retry queue is not an acknowledgement of persisted state.
export const acknowledgeSettingsFailures = (paths: Iterable<string>): Set<symbol> => {
  const confirmed = new Set(paths)
  const recovered = new Set<symbol>()
  const remaining = new Map<symbol, SettingsSaveFailure>()
  for (const [id, failure] of settingsSaveState.failureScopes.value) {
    const fields = new Set([...failure.fields].filter(path => !confirmed.has(path)))
    if (fields.size) remaining.set(id, { ...failure, fields })
    else recovered.add(id)
  }
  settingsSaveState.failureScopes.value = remaining
  return recovered
}
