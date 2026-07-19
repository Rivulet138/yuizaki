import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { requestJson, CONTROL_ORIGIN } from '@/api/clients/http-client'
import { useWorkspaceStore } from '@/stores/workspaceStore'

export interface SessionRecord {
  id: string
  workspace_id: string
  title: string
  summary?: string | null
  pinned: boolean
  created_at: string | null
  updated_at: string | null
  message_count: number
  total_tokens: number
}

const normalizeWorkspaceId = (workspaceId?: string | null) => (workspaceId || 'default').trim() || 'default'

const workspaceQuery = (workspaceId?: string | null) => {
  const cleanWorkspaceId = workspaceId?.trim()
  return cleanWorkspaceId ? `?workspace_id=${encodeURIComponent(cleanWorkspaceId)}` : ''
}

export const useSessionStore = defineStore('session', () => {
  const sessions = ref<SessionRecord[]>([])
  const activeSessionId = ref<string>('default')
  const loading = ref(false)

  const activeSession = computed(() => {
    const current = sessions.value.find((item) => item.id === activeSessionId.value)
    if (current) return current
    const workspaceStore = useWorkspaceStore()
    const workspaceId = normalizeWorkspaceId(workspaceStore.activeWorkspace?.id)
    return sessions.value.find((item) => normalizeWorkspaceId(item.workspace_id) === workspaceId)
      ?? null
  })

  const loadSessions = async () => {
    loading.value = true
    try {
      const workspaceStore = useWorkspaceStore()
      const workspaceId = workspaceStore.activeWorkspace?.id
      if (!workspaceId) return

      const payload = await requestJson<{ sessions: SessionRecord[] }>(`${CONTROL_ORIGIN}/api/sessions?scope=all`)
      sessions.value = Array.isArray(payload.sessions)
        ? payload.sessions.map((session) => ({
            ...session,
            workspace_id: normalizeWorkspaceId(session.workspace_id),
          }))
        : []
      const activeSession = sessions.value.find((item) => item.id === activeSessionId.value)
      const activeSessionMatchesWorkspace = normalizeWorkspaceId(activeSession?.workspace_id) === normalizeWorkspaceId(workspaceId)
      if (!activeSessionMatchesWorkspace) {
        const workspaceSession = sessions.value.find((item) => normalizeWorkspaceId(item.workspace_id) === normalizeWorkspaceId(workspaceId))
        activeSessionId.value = workspaceSession?.id || 'default'
      }
    } finally {
      loading.value = false
    }
  }

  const createSession = async (title?: string) => {
    const workspaceStore = useWorkspaceStore()
    const workspaceId = workspaceStore.activeWorkspace?.id
    if (!workspaceId) throw new Error("No active workspace")

    const session = await requestJson<SessionRecord>(`${CONTROL_ORIGIN}/api/workspaces/${encodeURIComponent(workspaceId)}/sessions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    })
    sessions.value.unshift(session)
    activeSessionId.value = session.id
    return session
  }

  const setActiveSession = (sessionId: string) => {
    activeSessionId.value = sessionId
  }

  const deleteSession = async (sessionId: string, workspaceId?: string) => {
    await requestJson<{ status: string }>(`${CONTROL_ORIGIN}/api/sessions/${encodeURIComponent(sessionId)}${workspaceQuery(workspaceId)}`, { method: 'DELETE' })
    sessions.value = sessions.value.filter((item) => item.id !== sessionId)
    if (activeSessionId.value === sessionId) {
      const targetWorkspaceId = normalizeWorkspaceId(workspaceId ?? useWorkspaceStore().activeWorkspace?.id)
      const nextWorkspaceSession = sessions.value.find((item) => normalizeWorkspaceId(item.workspace_id) === targetWorkspaceId)
      activeSessionId.value = nextWorkspaceSession?.id || 'default'
    }
  }

  const updateSession = async (sessionId: string, patch: Partial<SessionRecord>, workspaceId?: string) => {
    const updated = await requestJson<SessionRecord>(`${CONTROL_ORIGIN}/api/sessions/${encodeURIComponent(sessionId)}${workspaceQuery(workspaceId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    })
    const normalizedUpdated = {
      ...updated,
      workspace_id: normalizeWorkspaceId(updated.workspace_id),
    }
    sessions.value = sessions.value.map((item) => (item.id === sessionId ? { ...item, ...normalizedUpdated } : item))
    return normalizedUpdated
  }

  const noteMessagesDeleted = (sessionId: string, count = 1) => {
    const amount = Math.max(0, Math.round(count))
    if (!amount) return
    sessions.value = sessions.value.map((item) => item.id === sessionId
      ? {
          ...item,
          message_count: Math.max(0, (item.message_count || 0) - amount),
          updated_at: new Date().toISOString(),
        }
      : item)
  }

  const noteMessageDeleted = (sessionId: string) => {
    noteMessagesDeleted(sessionId, 1)
  }

  const noteSessionMessagesCleared = (sessionId: string) => {
    sessions.value = sessions.value.map((item) => item.id === sessionId
      ? {
          ...item,
          message_count: 0,
          total_tokens: 0,
          updated_at: new Date().toISOString(),
        }
      : item)
  }

  return {
    sessions,
    activeSessionId,
    activeSession,
    loading,
    loadSessions,
    createSession,
    setActiveSession,
    deleteSession,
    updateSession,
    noteMessageDeleted,
    noteMessagesDeleted,
    noteSessionMessagesCleared,
  }
})
