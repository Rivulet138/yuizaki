import type { SettingsMutationResponse, SettingsResponse } from '@/api/clients/settings-client'

const COMPANION_TTS_KEYS = ['ref_audio', 'ref_text', 'lang'] as const

type CompanionTtsKey = (typeof COMPANION_TTS_KEYS)[number]
type CompanionVoiceProfile = Record<string, unknown>
type CompanionTtsPatch = Partial<Record<CompanionTtsKey, unknown>>

export interface CompanionVoiceSettingsClient {
  load: () => Promise<SettingsResponse>
  save: (patch: Record<string, unknown>) => Promise<SettingsMutationResponse>
}

let voiceSettingsSyncTail: Promise<void> = Promise.resolve()

export const buildCompanionTtsPatch = (voiceProfile: CompanionVoiceProfile): CompanionTtsPatch => {
  const patch: CompanionTtsPatch = {}
  for (const key of COMPANION_TTS_KEYS) {
    const value = voiceProfile[key]
    if (value != null) patch[key] = value
  }
  return patch
}

export const changedCompanionTtsPatch = (
  desired: CompanionTtsPatch,
  current: SettingsResponse['tts'],
): CompanionTtsPatch => Object.fromEntries(
  Object.entries(desired).filter(([key, value]) => !Object.is(current[key as CompanionTtsKey], value)),
) as CompanionTtsPatch

const syncCompanionVoiceSettingsNow = async (
  client: CompanionVoiceSettingsClient,
  voiceProfile: CompanionVoiceProfile,
): Promise<boolean> => {
  const desired = buildCompanionTtsPatch(voiceProfile)
  if (Object.keys(desired).length === 0) return false

  let patch = desired
  try {
    const current = await client.load()
    patch = changedCompanionTtsPatch(desired, current.tts)
  } catch {
    // Applying the companion's desired voice remains useful when the read path is temporarily unavailable.
  }

  if (Object.keys(patch).length === 0) return false
  await client.save({ tts: patch })
  return true
}

export const syncCompanionVoiceSettings = (
  client: CompanionVoiceSettingsClient,
  voiceProfile: CompanionVoiceProfile,
): Promise<boolean> => {
  const operation = voiceSettingsSyncTail.then(
    () => syncCompanionVoiceSettingsNow(client, voiceProfile),
    () => syncCompanionVoiceSettingsNow(client, voiceProfile),
  )
  voiceSettingsSyncTail = operation.then(() => undefined, () => undefined)
  return operation
}
