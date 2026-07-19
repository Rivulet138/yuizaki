import { defineStore } from 'pinia'
import { ref } from 'vue'

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

  const permissionRequest = ref<PermissionRequestPayload | null>(null)
  
  const openWorkspaceDrawer = () => {
    workspaceDrawerVisible.value = true
  }

  const openEditCompanion = (companionId: string) => {
    editCompanionTargetId.value = companionId
    editCompanionDialogVisible.value = true
  }

  const openPermissionRequest = (request: PermissionRequestPayload) => {
    permissionRequest.value = request
    permissionDialogVisible.value = true
  }

  return {
    workspaceDrawerVisible,
    editCompanionDialogVisible,
    permissionDialogVisible,
    editCompanionTargetId,
    permissionRequest,
    openWorkspaceDrawer,
    openEditCompanion,
    openPermissionRequest,
  }
})
