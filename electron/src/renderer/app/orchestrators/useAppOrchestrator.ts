import { logger } from '@/logger'
import { onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useChatStore } from '@/stores/chatStore'
import { useCompanionStore } from '@/stores/companionStore'
import { useSessionStore } from '@/stores/sessionStore'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { petControlClient, systemClient } from '@/api/client'
import { isPanelKey } from '@/navigation/modules'
import { useCompanionRuntimeBridge } from '../composables/useCompanionRuntimeBridge'

const LEGACY_DEFAULT_MODEL_ID = 'hiyori'
const encodeRouteParam = (value: string) => encodeURIComponent(value)
const moduleRoute = (workspaceId: string, tab: string, sessionId?: string | null) =>
  sessionId
    ? `/w/${encodeRouteParam(workspaceId)}/${tab}/${encodeRouteParam(sessionId)}`
    : `/w/${encodeRouteParam(workspaceId)}/${tab}`

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
    await workspaceStore.setActiveWorkspaceSynced(workspaceId)
    await runRecoverableTask('load sessions after workspace change', () => sessionStore.loadSessions())
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
    const isLegacyDefaultModel = workspaceModelId === LEGACY_DEFAULT_MODEL_ID && workspaceModelType === 'live2d'
    if (workspaceModelId && !isLegacyDefaultModel) {
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
    chatStore.initChatStore()
    const initialTab = resolveInitialTab()
    await runRecoverableTask('load companions', () => companionStore.loadCompanions())
    await runRecoverableTask('sync workspaces', () => workspaceStore.syncFromBackend())

    if (workspaceStore.activeWorkspace.companion_profile_id) {
      companionStore.setActiveCompanion(workspaceStore.activeWorkspace.companion_profile_id)
    }
    await runRecoverableTask('apply active companion runtime', applyActiveCompanionRuntime)
    await runRecoverableTask('load sessions', () => sessionStore.loadSessions())

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
  })

  watch(
    () => [workspaceStore.activeWorkspaceId, sessionStore.activeSessionId],
    async ([workspaceId, sessionId]) => {
      chatStore.setWorkspaceContext(String(workspaceId || 'default'), String(sessionId || 'default'))
      await runRecoverableTask('sync active workspace', () => systemClient.setActiveWorkspace(String(workspaceId || 'default')))
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
