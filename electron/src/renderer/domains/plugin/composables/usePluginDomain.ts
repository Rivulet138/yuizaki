import { ref, computed } from 'vue'
import { pluginClient } from '@/api/client'
import { useDomainRequest } from '@/shared/composables/useDomainRequest'
import type { DesktopPetPlugin, PluginAuditRecord, PluginLoadFailure, PluginRegistrySnapshot, PluginRuntimeState } from '../../../../shared/plugin'

export function usePluginDomain() {
  const payload = ref<PluginRegistrySnapshot | null>(null)
  const selectedPluginId = ref('')
  const cancellingInvocationIds = ref(new Set<string>())

  const pluginsRequest = useDomainRequest<PluginRegistrySnapshot>()
  const cancelRequest = useDomainRequest<{ ok: boolean; invocationId: string; status: string }>()

  const plugins = computed(() => payload.value?.plugins ?? [])
  const pluginStates = computed(() => payload.value?.pluginStates ?? [])
  const loadFailures = computed<PluginLoadFailure[]>(() => payload.value?.loadFailures ?? [])
  const auditLogs = computed<PluginAuditRecord[]>(() => payload.value?.audit ?? [])
  const stateMap = computed(() => new Map(pluginStates.value.map((state) => [state.pluginId, state] as const)))

  const pluginRows = computed(() =>
    plugins.value.map((plugin) => {
      const state = stateMap.value.get(plugin.id)
      return {
        ...plugin,
        status: state?.status ?? 'loaded',
        routeCount: plugin.routes?.length ?? 0,
        toolCount: plugin.toolCapabilities?.length ?? 0,
        activeCount: state?.activeExecutions.length ?? 0,
        lastError: state?.lastError ?? '—',
      }
    }),
  )

  const selectedPlugin = computed<DesktopPetPlugin | undefined>(() => plugins.value.find((plugin) => plugin.id === selectedPluginId.value) ?? plugins.value[0])
  const selectedPluginState = computed<PluginRuntimeState | undefined>(() => {
    const pluginId = selectedPlugin.value?.id
    return pluginId ? stateMap.value.get(pluginId) : undefined
  })

  const blockedOrErrorCount = computed(
    () => pluginStates.value.filter((state) => state.status === 'blocked' || state.status === 'error').length,
  )
  const activeExecutionCount = computed(() => pluginStates.value.reduce((sum, state) => sum + state.activeExecutions.length, 0))

  const ensureSelectedPlugin = () => {
    if (!selectedPluginId.value || !plugins.value.some((plugin) => plugin.id === selectedPluginId.value)) {
      selectedPluginId.value = plugins.value[0]?.id ?? ''
    }
  }

  const loadPlugins = async () => {
    const result = await pluginsRequest.execute(() => pluginClient.list())
    if (result) {
      payload.value = result
      ensureSelectedPlugin()
    }
  }

  const cancelExecution = async (pluginId: string, routeId: string, invocationId: string) => {
    const next = new Set(cancellingInvocationIds.value)
    next.add(invocationId)
    cancellingInvocationIds.value = next

    try {
      const result = await cancelRequest.execute(() => pluginClient.cancelExecution(pluginId, routeId, invocationId))
      if (!result?.ok) {
        return false
      }
      await loadPlugins()
      return true
    } finally {
      const finalSet = new Set(cancellingInvocationIds.value)
      finalSet.delete(invocationId)
      cancellingInvocationIds.value = finalSet
    }
  }

  return {
    payload,
    selectedPluginId,
    cancellingInvocationIds,
    pluginsRequest,
    cancelRequest,
    plugins,
    pluginStates,
    loadFailures,
    auditLogs,
    pluginRows,
    selectedPlugin,
    selectedPluginState,
    blockedOrErrorCount,
    activeExecutionCount,
    loadPlugins,
    cancelExecution
  }
}
