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
  }
})
