import { logger } from '@/logger'
import { onMounted, watch } from 'vue'
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

  const runRecoverableTask = async (label: string, task: () => Promise<unknown> | unknown) => {
    try {
      await task()
    } catch (error) {
      logger.warn(`[AppOrchestrator] ${label} failed`, error)
    }
  }

  const changeWorkspace = async (workspaceId: string) => {
    await switchWorkspaceAndLoadSessions(
      workspaceId,
      workspaceStore.setActiveWorkspaceSynced,
      () => runRecoverableTask('load sessions after workspace change', () => sessionStore.loadSessions()),
    )
    const workspace = workspaceStore.activeWorkspace
    if (workspace.context?.activeTab && isPanelKey(workspace.context.activeTab)) {
      const tab = workspace.context.activeTab
      const activeSession = sessionStore.activeSession
      await runRecoverableTask('route after workspace change', () =>
        router.push(moduleRoute(workspace.id, tab, activeSession?.id)),
      )
    } else {
      const activeSession = sessionStore.activeSession
      await runRecoverableTask('route after workspace change', () =>
        router.push(moduleRoute(workspace.id, 'companion', activeSession?.id)),
      )
    }

    const workspaceModelId = workspace.context?.modelId
    const workspaceModelType = workspace.context?.modelType
    if (workspaceModelId) {
      try {
        await petControlClient.setModelSelection(workspaceModelId, workspaceModelType)
      } catch (error) {
        logger.warn('Failed to restore workspace pet model context:', error)
      }
    }
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
    return 'companion'
  }

  onMounted(async () => {
    const initialTab = resolveInitialTab()
    await bootstrapAppDomains({
      initChatStore: chatStore.initChatStore,
      loadCompanions: companionStore.loadCompanions,
      syncFromBackend: workspaceStore.syncFromBackend,
      resolveActiveCompanion: () => {
        if (workspaceStore.activeWorkspace.companion_profile_id) {
          companionStore.setActiveCompanion(workspaceStore.activeWorkspace.companion_profile_id)
        }
      },
      applyActiveCompanionRuntime,
      loadSessions: sessionStore.loadSessions,
      run: runRecoverableTask,
    })

    const activeSessionId = sessionStore.activeSession?.id
    if (activeSessionId) {
      await runRecoverableTask('load chat history', () => chatStore.loadHistory(activeSessionId, workspaceStore.activeWorkspaceId))
    }

    if (route.path === '/') {
      const session = sessionStore.activeSession
      const tab = initialTab
      await runRecoverableTask('restore initial route', () =>
        router.replace(moduleRoute(workspaceStore.activeWorkspaceId, tab, session?.id)),
      )
    }
    document.documentElement.dataset['yuizakiAppReady'] = 'true'
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
