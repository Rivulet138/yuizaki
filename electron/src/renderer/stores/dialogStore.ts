import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

export interface PermissionRequestPayload {
  request_id: string
  tool_name: string
  capability_id?: string
  capability_type?: string
  capability_kind?: string
  risk_level: string
  reason: string
  args?: unknown
}

export const isPermissionRequestPayload = (value: unknown): value is PermissionRequestPayload => {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false
  const payload = value as Record<string, unknown>
  return ['request_id', 'tool_name', 'risk_level', 'reason'].every((key) => typeof payload[key] === 'string')
    && typeof payload.request_id === 'string' && payload.request_id.trim().length > 0
    && ['capability_id', 'capability_type', 'capability_kind'].every((key) => (
      payload[key] === undefined || typeof payload[key] === 'string'
    ))
}

export const useDialogStore = defineStore('dialog', () => {
  const workspaceDrawerVisible = ref(false)
  const editCompanionDialogVisible = ref(false)
  const permissionDialogVisible = ref(false)

  const editCompanionTargetId = ref('default')

  const permissionRequests = ref<PermissionRequestPayload[]>([])
  const permissionRequest = computed(() => permissionRequests.value[0] ?? null)

  const openWorkspaceDrawer = () => {
    workspaceDrawerVisible.value = true
  }

  const openEditCompanion = (companionId: string) => {
    editCompanionTargetId.value = companionId
    editCompanionDialogVisible.value = true
  }

  const openPermissionRequest = (request: PermissionRequestPayload) => {
    if (permissionRequests.value.some((item) => item.request_id === request.request_id)) return
    permissionRequests.value.push(request)
    permissionDialogVisible.value = true
  }

  const completePermissionRequest = (requestId: string) => {
    if (permissionRequests.value[0]?.request_id !== requestId) return
    permissionRequests.value.shift()
    permissionDialogVisible.value = permissionRequests.value.length > 0
  }

  const removePermissionRequest = (requestId: string) => {
    const index = permissionRequests.value.findIndex((item) => item.request_id === requestId)
    if (index < 0) return
    permissionRequests.value.splice(index, 1)
    permissionDialogVisible.value = permissionRequests.value.length > 0
  }

  const clearPermissionRequests = () => {
    permissionRequests.value = []
    permissionDialogVisible.value = false
  }

  return {
    workspaceDrawerVisible,
    editCompanionDialogVisible,
    permissionDialogVisible,
    editCompanionTargetId,
    permissionRequest,
    permissionRequests,
    openWorkspaceDrawer,
    openEditCompanion,
    openPermissionRequest,
    completePermissionRequest,
    removePermissionRequest,
    clearPermissionRequests,
  }
})
