import { ref } from 'vue'
import { settingsClient } from '@/api/client'
import type { RuntimeReloadStatusResponse, LlmModelsRequest, LlmModelsResponse, LlmRuntimeStatusResponse, SettingsMutationResponse, SettingsResponse, TestConnectionResponse, TtsRuntimeStatusResponse, TtsWarmupResponse } from '@/api/clients/settings-client'
import { useDomainRequest } from '@/shared/composables/useDomainRequest'

export function useSettingsDomain() {
  const settings = ref<SettingsResponse | null>(null)
  const settingsReadbackFailed = ref(false)
  const runtimeReload = ref<RuntimeReloadStatusResponse | null>(null)
  const runtimeStatusRequest = useDomainRequest<RuntimeReloadStatusResponse>()
  const runtimeRetryState = useDomainRequest<RuntimeReloadStatusResponse>()
  const runtimeRetryFailures = ref<Array<{ service: string; revision: number; error: string }>>([])
  const runtimeRetryRequest = {
    get data() { return runtimeRetryState.data },
    get loading() { return runtimeRetryState.loading },
    get error() { return [...new Set(runtimeRetryFailures.value.map(failure => failure.error))].join('\n') || null },
    execute: runtimeRetryState.execute,
    isCurrent: runtimeRetryState.isCurrent,
    reset: () => {
      runtimeRetryState.reset()
      runtimeRetryFailures.value = []
    },
  }
  let runtimeSequence = 0

  const reconcileRuntimeStatus = (status: RuntimeReloadStatusResponse) => {
    runtimeReload.value = status
    runtimeRetryFailures.value = runtimeRetryFailures.value.filter(({ service, revision }) => {
      const section = status.sections[service]
      // Missing services and older/unresolved revisions cannot acknowledge this failure.
      return !section || !(section.target_revision > revision
        || (section.applied_revision !== null && section.applied_revision >= revision))
    })
  }

  const acceptRuntimeStatus = (status: RuntimeReloadStatusResponse) => {
    runtimeSequence += 1
    runtimeStatusRequest.reset()
    // Invalidate older requests while retaining errors for unrelated targets.
    runtimeRetryState.reset()
    reconcileRuntimeStatus(status)
  }
  const llmModels = ref<string[]>([])
  const llmStatus = ref<LlmRuntimeStatusResponse | null>(null)
  const ttsStatus = ref<TtsRuntimeStatusResponse | null>(null)

  const settingsRequest = useDomainRequest<SettingsResponse>()
  const updateRequest = useDomainRequest<SettingsMutationResponse & { normalizedSettings: SettingsResponse }>()
  const llmModelsRequest = useDomainRequest<LlmModelsResponse>()
  const llmStatusRequest = useDomainRequest<LlmRuntimeStatusResponse>()
  const testLlmRequest = useDomainRequest<TestConnectionResponse>()
  const testTtsRequest = useDomainRequest<TestConnectionResponse>()
  const testSvcRequest = useDomainRequest<TestConnectionResponse>()
  const ttsStatusRequest = useDomainRequest<TtsRuntimeStatusResponse>()
  const warmupTtsRequest = useDomainRequest<TtsWarmupResponse>()

  let settingsSequence = 0
  let ttsStatusSequence = 0

  const invalidateTtsStatusRead = () => {
    // Reset the request itself so stale GETs cannot publish data, errors or loading.
    ttsStatusRequest.reset()
    return ++ttsStatusSequence
  }

  const loadSettings = async () => {
    const requestId = ++settingsSequence
    invalidateTtsStatusRead()
    const result = await settingsRequest.execute(() => settingsClient.load(true))
    if (!result || requestId !== settingsSequence) return null
    settings.value = result
    settingsReadbackFailed.value = false
    return result
  }

  const patchSettings = async (patch: Record<string, unknown>) => {
    const requestId = ++settingsSequence
    invalidateTtsStatusRead()
    settingsReadbackFailed.value = false
    const mutation = await updateRequest.execute(async () => {
      const result = await settingsClient.save(patch)
      if (requestId === settingsSequence && result.runtime_reload) acceptRuntimeStatus(result.runtime_reload)
      // New backends return the canonical, redacted settings with the acknowledgement.
      let normalized: SettingsResponse
      try {
        normalized = result.normalized_settings ?? await settingsClient.load(true)
      } catch (error) {
        if (requestId === settingsSequence) settingsReadbackFailed.value = true
        throw error
      }
      if (requestId === settingsSequence) settings.value = normalized
      return { ...result, normalizedSettings: normalized }
    })
    return requestId === settingsSequence ? mutation : null
  }

  const loadRuntimeStatus = async () => {
    const version = ++runtimeSequence
    const settingsVersion = settingsSequence
    const result = await runtimeStatusRequest.execute(() => settingsClient.runtimeStatus())
    if (version !== runtimeSequence || settingsVersion !== settingsSequence) return null
    if (result) reconcileRuntimeStatus(result)
    return result
  }

  const retryRuntime = async (targets: Record<string, number>) => {
    const version = ++runtimeSequence
    const settingsVersion = settingsSequence
    const requestedTargets = { ...targets }
    const result = await runtimeRetryState.execute(() => settingsClient.retryRuntime(requestedTargets))
    if (version !== runtimeSequence || settingsVersion !== settingsSequence) return null
    if (result) {
      reconcileRuntimeStatus(result)
    } else if (runtimeRetryState.error) {
      const error = runtimeRetryState.error
      runtimeRetryFailures.value = [
        ...runtimeRetryFailures.value.filter(failure => requestedTargets[failure.service] !== failure.revision),
        ...Object.entries(requestedTargets).map(([service, revision]) => ({ service, revision, error })),
      ]
    }
    return result
  }

  const loadLlmModels = async (payload: LlmModelsRequest) => {
    return llmModelsRequest.execute(() => settingsClient.listLlmModels(payload))
  }

  const loadLlmStatus = async () => {
    const settingsVersion = settingsSequence
    const result = await llmStatusRequest.execute(() => settingsClient.llmStatus())
    if (settingsVersion !== settingsSequence) return null
    if (result) llmStatus.value = result
    return result
  }

  const testLlm = async () => {
    const result = await testLlmRequest.execute(() => settingsClient.testLlm())
    void loadLlmStatus()
    return result
  }

  const testTts = async () => {
    return testTtsRequest.execute(() => settingsClient.testTts())
  }

  const testSvc = async () => {
    return testSvcRequest.execute(() => settingsClient.testSvc())
  }

  const warmupTts = async () => {
    const version = invalidateTtsStatusRead()
    const settingsVersion = settingsSequence
    const result = await warmupTtsRequest.execute(() => settingsClient.warmupTts())
    // Runtime ownership may change while the operation still succeeds. Keep its ACK.
    if (version === ttsStatusSequence && settingsVersion === settingsSequence && result?.runtime) {
      ttsStatus.value = result.runtime
    }
    return result
  }

  const loadTtsStatus = async () => {
    const version = ++ttsStatusSequence
    const settingsVersion = settingsSequence
    const result = await ttsStatusRequest.execute(() => settingsClient.ttsStatus())
    if (version !== ttsStatusSequence || settingsVersion !== settingsSequence) return null
    if (result) {
      ttsStatus.value = result
    }
    return result
  }

  return {
    settings,
    settingsReadbackFailed,
    runtimeReload,
    runtimeStatusRequest,
    runtimeRetryRequest,
    acceptRuntimeStatus,
    loadRuntimeStatus,
    retryRuntime,
    settingsRequest,
    updateRequest,
    llmModels,
    llmModelsRequest,
    llmStatus,
    llmStatusRequest,
    ttsStatus,
    ttsStatusRequest,
    testLlmRequest,
    testTtsRequest,
    testSvcRequest,
    warmupTtsRequest,
    loadSettings,
    patchSettings,
    loadLlmModels,
    loadLlmStatus,
    loadTtsStatus,
    testLlm,
    testTts,
    testSvc,
    warmupTts,
  }
}
