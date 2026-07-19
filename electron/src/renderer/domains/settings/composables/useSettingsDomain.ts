import { ref } from 'vue'
import { settingsClient } from '@/api/client'
import type { LlmModelsRequest, LlmModelsResponse, SettingsMutationResponse, SettingsResponse, TestConnectionResponse, TtsRuntimeStatusResponse, TtsWarmupResponse } from '@/api/clients/settings-client'
import { useDomainRequest } from '@/shared/composables/useDomainRequest'

type SettingsRecord = Record<string, unknown>

const isRecord = (value: unknown): value is SettingsRecord => {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

const mergeSettingsRecord = (base: SettingsRecord, patch: SettingsRecord): SettingsRecord => {
  const merged: SettingsRecord = { ...base }
  for (const [key, value] of Object.entries(patch)) {
    const existing = merged[key]
    merged[key] = isRecord(existing) && isRecord(value)
      ? mergeSettingsRecord(existing, value)
      : value
  }
  return merged
}

export function useSettingsDomain() {
  const settings = ref<SettingsResponse | null>(null)
  const llmModels = ref<string[]>([])
  const ttsStatus = ref<TtsRuntimeStatusResponse | null>(null)

  const settingsRequest = useDomainRequest<SettingsResponse>()
  const updateRequest = useDomainRequest<SettingsMutationResponse>()
  const llmModelsRequest = useDomainRequest<LlmModelsResponse>()
  const testLlmRequest = useDomainRequest<TestConnectionResponse>()
  const testTtsRequest = useDomainRequest<TestConnectionResponse>()
  const ttsStatusRequest = useDomainRequest<TtsRuntimeStatusResponse>()
  const warmupTtsRequest = useDomainRequest<TtsWarmupResponse>()

  const loadSettings = async () => {
    const result = await settingsRequest.execute(() => settingsClient.load())
    if (result) {
      settings.value = result
    }
  }

  const patchSettings = async (patch: Record<string, unknown>) => {
    const result = await updateRequest.execute(() => settingsClient.save(patch))
    if (result && settings.value) {
      settings.value = mergeSettingsRecord(settings.value as unknown as SettingsRecord, patch) as unknown as SettingsResponse
    }
    return result
  }

  const loadLlmModels = async (payload: LlmModelsRequest) => {
    const result = await llmModelsRequest.execute(() => settingsClient.listLlmModels(payload))
    if (result?.ok) {
      llmModels.value = result.models
    } else if (result) {
      llmModels.value = []
    }
    return result
  }

  const testLlm = async () => {
    return testLlmRequest.execute(() => settingsClient.testLlm())
  }

  const testTts = async () => {
    return testTtsRequest.execute(() => settingsClient.testTts())
  }

  const warmupTts = async () => {
    const result = await warmupTtsRequest.execute(() => settingsClient.warmupTts())
    if (result?.runtime) {
      ttsStatus.value = result.runtime
    }
    return result
  }

  const loadTtsStatus = async () => {
    const result = await ttsStatusRequest.execute(() => settingsClient.ttsStatus())
    if (result) {
      ttsStatus.value = result
    }
    return result
  }

  return {
    settings,
    settingsRequest,
    updateRequest,
    llmModels,
    llmModelsRequest,
    ttsStatus,
    ttsStatusRequest,
    testLlmRequest,
    testTtsRequest,
    warmupTtsRequest,
    loadSettings,
    patchSettings,
    loadLlmModels,
    loadTtsStatus,
    testLlm,
    testTts,
    warmupTts,
  }
}
