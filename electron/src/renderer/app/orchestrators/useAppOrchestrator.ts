import { logger } from '@/logger'
import { onBeforeUnmount, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useChatStore } from '@/stores/chatStore'
import { useCompanionStore } from '@/stores/companionStore'
import { useSessionStore } from '@/stores/sessionStore'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { petControlClient } from '@/api/client'
import { isPanelKey } from '@/navigation/modules'
import { useCompanionRuntimeBridge } from '../composables/useCompanionRuntimeBridge'

const encodeRouteParam = (value: string) => encodeURIComponent(value)
const moduleRoute = (workspaceId: string, tab: string, sessionId?: string | null) =>
  sessionId
    ? `/w/${encodeRouteParam(workspaceId)}/${tab}/${encodeRouteParam(sessionId)}`
    : `/w/${encodeRouteParam(workspaceId)}/${tab}`

interface AppDomainBootstrapDependencies {
  initChatStore: () => void
  loadCompanions: () => Promise<unknown> | unknown
  syncFromBackend: () => Promise<unknown> | unknown
  resolveActiveCompanion?: () => void
  applyActiveCompanionRuntime: () => Promise<unknown> | unknown
  loadSessions: () => Promise<unknown> | unknown
  run?: (label: string, task: () => Promise<unknown> | unknown) => Promise<void>
}

export const bootstrapAppDomains = async (dependencies: AppDomainBootstrapDependencies) => {
  const run = dependencies.run ?? (async (_label, task) => { await task() })
  dependencies.initChatStore()
  await run('load companions', dependencies.loadCompanions)
  await run('sync workspaces', dependencies.syncFromBackend)
  dependencies.resolveActiveCompanion?.()
  await run('apply active companion runtime', dependencies.applyActiveCompanionRuntime)
  await run('load sessions', dependencies.loadSessions)
}

export const switchWorkspaceAndLoadSessions = async (
  workspaceId: string,
  setActiveWorkspaceSynced: (id: string) => Promise<unknown>,
  loadSessions: () => Promise<unknown> | unknown,
) => {
  await setActiveWorkspaceSynced(workspaceId)
  await loadSessions()
}

export function useAppOrchestrator() {
  const router = useRouter()
  const route = useRoute()
  const workspaceStore = useWorkspaceStore()
  const sessionStore = useSessionStore()
  const companionStore = useCompanionStore()
  const chatStore = useChatStore()
  const { applyActiveCompanionRuntime, handleCompanionChange } = useCompanionRuntimeBridge()
  let disposed = false
  let workspacesReady = false
  let initialized = false
  let workspaceChange = 0
  let loadedWorkspaceId: string | undefined
  const ownsWorkspaceChange = (change: number) => !disposed && change === workspaceChange

  onBeforeUnmount(() => {
    disposed = true
    workspaceChange++
  })

  const runRecoverableTask = async (label: string, task: () => Promise<unknown> | unknown) => {
    try {
      await task()
    } catch (error) {
      logger.warn(`[AppOrchestrator] ${label} failed`, error)
    }
  }

  const changeWorkspace = async (workspaceId: string) => {
    const change = ++workspaceChange
    await workspaceStore.setActiveWorkspaceSynced(workspaceId)
    if (!ownsWorkspaceChange(change)) return
    await runRecoverableTask('load sessions after workspace change', () => sessionStore.loadSessions())
    if (!ownsWorkspaceChange(change)) return
    loadedWorkspaceId = workspaceId
    const workspace = workspaceStore.activeWorkspace
    const workspaceModelId = workspace.context?.modelId
    const workspaceModelType = workspace.context?.modelType
    if (workspaceModelId) {
      try {
        await petControlClient.setModelSelection(workspaceModelId, workspaceModelType)
      } catch (error) {
        logger.warn('Failed to restore workspace pet model context:', error)
      }
    }
    if (!ownsWorkspaceChange(change)) return
    const tab = workspace.context?.activeTab && isPanelKey(workspace.context.activeTab)
      ? workspace.context.activeTab : 'chat'
    await runRecoverableTask('route after workspace change', () =>
      router.push(moduleRoute(workspace.id, tab, sessionStore.activeSession?.id)),
    )
  }

  const resolveInitialTab = (): string => {
    const workspaceTab = workspaceStore.activeWorkspace.context?.activeTab
    if (workspaceTab && isPanelKey(workspaceTab)) {
      return workspaceTab
    }
    const url = new URL(window.location.href)
    const queryTab = (url.searchParams.get('tab') ?? '').trim().toLowerCase()
    if (queryTab && isPanelKey(queryTab)) {
      return queryTab
    }
    const hashTab = url.hash.replace(/^#\/?/, '').trim().toLowerCase()
    if (hashTab && isPanelKey(hashTab)) {
      return hashTab
    }
    return 'chat'
  }

  const synchronizeRouteWorkspace = async (change: number) => {
    if (route.path === '/') {
      await runRecoverableTask('restore initial route', () =>
        router.replace(moduleRoute(workspaceStore.activeWorkspaceId, resolveInitialTab())),
      )
      return
    }
    const workspaceId = String(route.params.workspaceId || 'default')
    if (!workspaceStore.workspaces.some(workspace => workspace.id === workspaceId)) {
      const fallback = workspaceStore.workspaces.find(workspace => workspace.id === 'default')
        ?? workspaceStore.workspaces[0]
      await router.replace(moduleRoute(fallback?.id ?? 'default', 'chat'))
      return
    }
    if (workspaceStore.activeWorkspaceId === workspaceId && loadedWorkspaceId === workspaceId && initialized) return
    await workspaceStore.setActiveWorkspaceSynced(workspaceId)
    if (!ownsWorkspaceChange(change)) return
    if (!initialized) {
      const companionId = workspaceStore.activeWorkspace.companion_profile_id
      if (companionId) companionStore.setActiveCompanion(companionId)
      await runRecoverableTask('apply active companion runtime', applyActiveCompanionRuntime)
      if (!ownsWorkspaceChange(change)) return
    }
    await runRecoverableTask('load sessions from workspace route', () => sessionStore.loadSessions())
    if (!ownsWorkspaceChange(change)) return
    loadedWorkspaceId = workspaceId
    if (!initialized && sessionStore.activeSession?.id) {
      const activeSessionId = sessionStore.activeSession.id
      await runRecoverableTask('load chat history', () => chatStore.loadHistory(activeSessionId, workspaceId))
      if (!ownsWorkspaceChange(change)) return
    }
    initialized = true
    document.documentElement.dataset['yuizakiAppReady'] = 'true'
  }

  watch(() => route.fullPath, () => {
    const change = ++workspaceChange
    if (workspacesReady) {
      void runRecoverableTask('synchronize workspace route', () => synchronizeRouteWorkspace(change))
    }
  }, { flush: 'sync' })

  onMounted(async () => {
    chatStore.initChatStore()
    await runRecoverableTask('load companions', companionStore.loadCompanions)
    if (disposed) return
    await runRecoverableTask('sync workspaces', workspaceStore.syncFromBackend)
    if (disposed) return
    workspacesReady = true
    const change = ++workspaceChange
    await runRecoverableTask('synchronize initial workspace route', () => synchronizeRouteWorkspace(change))
  })

  watch(
    () => [workspaceStore.activeWorkspaceId, sessionStore.activeSessionId],
    ([workspaceId, sessionId]) => {
      chatStore.setWorkspaceContext(String(workspaceId || 'default'), String(sessionId || 'default'))
    },
    { immediate: true },
  )

  watch(
    () => workspaceStore.activeWorkspace.companion_profile_id,
    async (companionId) => {
      if (companionId && companionId !== companionStore.activeCompanionId) {
        companionStore.setActiveCompanion(companionId)
        await runRecoverableTask('apply companion runtime after workspace profile change', applyActiveCompanionRuntime)
      }
    },
  )

  return {
    applyActiveCompanionRuntime,
    handleCompanionChange,
    changeWorkspace,
  }
}
