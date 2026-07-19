<template>
  <!-- Permission Dialog -->
  <el-dialog v-model="dialogStore.permissionDialogVisible" title="工具权限确认" width="480px">
    <div v-if="dialogStore.permissionRequest">
      <p><strong>工具：</strong>{{ dialogStore.permissionRequest.tool_name }}</p>
      <p v-if="dialogStore.permissionRequest.capability_id"><strong>Capability：</strong>{{ dialogStore.permissionRequest.capability_id }}</p>
      <p v-if="dialogStore.permissionRequest.capability_kind"><strong>类别：</strong>{{ dialogStore.permissionRequest.capability_type }} / {{ dialogStore.permissionRequest.capability_kind }}</p>
      <p><strong>风险等级：</strong>{{ dialogStore.permissionRequest.risk_level }}</p>
      <p><strong>原因：</strong>{{ dialogStore.permissionRequest.reason }}</p>
      <pre class="permission-args">{{ JSON.stringify(dialogStore.permissionRequest.args || {}, null, 2) }}</pre>
      <el-checkbox v-model="rememberPermissionDecision">记住本次选择</el-checkbox>
    </div>
    <template #footer>
      <el-button @click="respondPermission(false)">拒绝</el-button>
      <el-button type="primary" @click="respondPermission(true)">允许</el-button>
    </template>
  </el-dialog>

  <!-- Workspace Drawer -->
  <WorkspaceDrawer
    :visible="dialogStore.workspaceDrawerVisible"
    :workspace="workspaceStore.activeWorkspace"
    :companions="companionStore.companions"
    :active-companion="companionStore.activeCompanion"
    @update:visible="dialogStore.workspaceDrawerVisible = $event"
    @update-field="handleWorkspaceFieldUpdate"
    @create-companion="createCompanionProfile"
    @edit-companion="dialogStore.openEditCompanion"
    @delete-companion="deleteCompanionProfile"
  />

  <!-- Edit desktop pet profile dialog -->
  <el-dialog v-model="dialogStore.editCompanionDialogVisible" title="编辑桌宠档案" width="560px" @open="initEditCompanionForm">
    <el-form label-position="top" size="small">
      <el-form-item label="名称"><el-input v-model="editCompanionForm.name" /></el-form-item>
      <el-form-item label="模型类型"><el-select v-model="editCompanionForm.model_type" style="width:100%"><el-option label="Live2D" value="live2d" /><el-option label="VRM" value="vrm" /></el-select></el-form-item>
      <el-form-item label="模型 ID"><el-input v-model="editCompanionForm.model_id" /></el-form-item>
      <el-form-item label="气质"><el-select v-model="editCompanionForm.temperament" style="width:100%"><el-option label="温暖" value="warm" /><el-option label="活泼" value="playful" /><el-option label="克制" value="reserved" /></el-select></el-form-item>
      <el-form-item label="依恋类型"><el-select v-model="editCompanionForm.attachment_style" style="width:100%"><el-option label="安全型" value="secure" /><el-option label="独立型" value="independent" /><el-option label="贴近型" value="attached" /></el-select></el-form-item>
      <el-form-item label="支持风格"><el-select v-model="editCompanionForm.support_style" style="width:100%"><el-option label="温柔" value="gentle" /><el-option label="分析型" value="analytical" /><el-option label="明朗型" value="cheerful" /></el-select></el-form-item>
      <el-form-item label="TTS Base URL"><el-input v-model="editCompanionForm.voice_profile.base_url" /></el-form-item>
      <el-form-item label="参考音频路径"><el-input v-model="editCompanionForm.voice_profile.ref_audio" /></el-form-item>
      <el-form-item label="参考文本"><el-input v-model="editCompanionForm.voice_profile.ref_text" type="textarea" :rows="2" /></el-form-item>
      <el-form-item label="语音语言"><el-input v-model="editCompanionForm.voice_profile.lang" /></el-form-item>
      <el-form-item label="情绪状态"><el-input v-model="editCompanionForm.emotion_state" /></el-form-item>
      <el-form-item label="亲密度"><el-input v-model="editCompanionForm.affinity_state" type="number" /></el-form-item>
      <el-form-item label="能量"><el-input v-model="editCompanionForm.energy_state" type="number" /></el-form-item>
      <el-form-item label="信任度"><el-input v-model="editCompanionForm.trust_state" type="number" /></el-form-item>
      <el-form-item label="亲密深度"><el-input v-model="editCompanionForm.intimacy_state" type="number" /></el-form-item>
      <el-form-item label="可打断性"><el-input v-model="editCompanionForm.interruptibility_state" type="number" /></el-form-item>
      <el-form-item label="疲劳度"><el-input v-model="editCompanionForm.fatigue_state" type="number" /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialogStore.editCompanionDialogVisible = false">取消</el-button>
      <el-button type="primary" @click="submitEditCompanion">保存</el-button>
    </template>
  </el-dialog>

</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useDialogStore } from '@/stores/dialogStore'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { useCompanionStore } from '@/stores/companionStore'
import { useCompanionRuntimeBridge } from '../../composables/useCompanionRuntimeBridge'
import WorkspaceDrawer from '../../WorkspaceDrawer.vue'
import { getSocketClient } from '@/net/socketClient'

const dialogStore = useDialogStore()
const workspaceStore = useWorkspaceStore()
const companionStore = useCompanionStore()
const { applyActiveCompanionRuntime, handleCompanionChange } = useCompanionRuntimeBridge()

const rememberPermissionDecision = ref(false)

const errorMessage = (error: unknown) => error instanceof Error ? error.message : '未知错误'

const respondPermission = async (allow: boolean) => {
  const req = dialogStore.permissionRequest
  if (!req) return
  try {
    getSocketClient().sendPermissionResponse(req.request_id, allow, rememberPermissionDecision.value)
    ElMessage.success(allow ? '已允许执行' : '已拒绝执行')
  } catch (error) {
    ElMessage.error(`响应权限失败: ${errorMessage(error)}`)
  }
  dialogStore.permissionDialogVisible = false
  dialogStore.permissionRequest = null
}

const handleWorkspaceFieldUpdate = async (field: string, value: string) => {
  const workspaceId = workspaceStore.activeWorkspaceId
  const patch: Record<string, string> = { [field]: value }
  try {
    await workspaceStore.updateWorkspaceRemote(workspaceId, patch)
    ElMessage.success('场景设置已保存')
  } catch {
    ElMessage.error('保存场景设置失败')
  }
}

const editCompanionForm = ref({
  name: '',
  model_type: 'live2d',
  model_id: '',
  persona_prompt: '',
  temperament: 'warm',
  attachment_style: 'secure',
  support_style: 'gentle',
  voice_profile: {
    ref_audio: '',
    ref_text: '',
    lang: '',
    base_url: '',
  },
  emotion_state: 'neutral',
  affinity_state: '0.5',
  energy_state: '1.0',
  trust_state: '0.5',
  intimacy_state: '0.5',
  interruptibility_state: '0.75',
  fatigue_state: '0.0',
})

const initEditCompanionForm = () => {
  const companion = companionStore.companions.find((item) => item.id === dialogStore.editCompanionTargetId)
  if (!companion) return
  editCompanionForm.value = {
    name: companion.name,
    model_type: companion.model_type || 'live2d',
    model_id: companion.model_id || '',
    persona_prompt: companion.persona_prompt || '',
    temperament: companion.temperament || 'warm',
    attachment_style: companion.attachment_style || 'secure',
    support_style: companion.support_style || 'gentle',
    voice_profile: {
      ref_audio: companion.voice_profile?.ref_audio || '',
      ref_text: companion.voice_profile?.ref_text || '',
      lang: companion.voice_profile?.lang || '',
      base_url: companion.voice_profile?.base_url || '',
    },
    emotion_state: companion.emotion_state || 'neutral',
    affinity_state: String(companion.affinity_state ?? 0.5),
    energy_state: String(companion.energy_state ?? 1.0),
    trust_state: String(companion.trust_state ?? 0.5),
    intimacy_state: String(companion.intimacy_state ?? 0.5),
    interruptibility_state: String(companion.interruptibility_state ?? 0.75),
    fatigue_state: String(companion.fatigue_state ?? 0.0),
  }
}

const submitEditCompanion = async () => {
  await companionStore.updateCompanion(dialogStore.editCompanionTargetId, {
    name: editCompanionForm.value.name,
    model_type: editCompanionForm.value.model_type,
    model_id: editCompanionForm.value.model_id || null,
    persona_prompt: editCompanionForm.value.persona_prompt || null,
    temperament: editCompanionForm.value.temperament || null,
    attachment_style: editCompanionForm.value.attachment_style || null,
    support_style: editCompanionForm.value.support_style || null,
    voice_profile: {
      ref_audio: editCompanionForm.value.voice_profile.ref_audio || null,
      ref_text: editCompanionForm.value.voice_profile.ref_text || null,
      lang: editCompanionForm.value.voice_profile.lang || null,
      base_url: editCompanionForm.value.voice_profile.base_url || null,
    },
    emotion_state: editCompanionForm.value.emotion_state || null,
    affinity_state: Number(editCompanionForm.value.affinity_state),
    energy_state: Number(editCompanionForm.value.energy_state),
    trust_state: Number(editCompanionForm.value.trust_state),
    intimacy_state: Number(editCompanionForm.value.intimacy_state),
    interruptibility_state: Number(editCompanionForm.value.interruptibility_state),
    fatigue_state: Number(editCompanionForm.value.fatigue_state),
  })
  dialogStore.editCompanionDialogVisible = false
  await applyActiveCompanionRuntime()
  ElMessage.success('桌宠档案已保存')
}

const createCompanionProfile = async () => {
  try {
    const { value } = await ElMessageBox.prompt('输入新的桌宠名称', '新建桌宠档案', {
      confirmButtonText: '创建',
      cancelButtonText: '取消',
      inputPattern: /\S+/,
      inputErrorMessage: '名称不能为空',
    })
    const companion = await companionStore.createCompanion({ name: value.trim(), model_type: workspaceStore.activeWorkspace.context?.modelType, model_id: workspaceStore.activeWorkspace.context?.modelId || undefined })
    await handleCompanionChange(companion.id)
  } catch (error) {
    console.debug('[GlobalDialogs] create companion cancelled or failed:', error)
  }
}

const deleteCompanionProfile = async (companionId: string) => {
  if (companionId === 'default') {
    ElMessage.warning('默认桌宠档案不能删除')
    return
  }
  try {
    await ElMessageBox.confirm('确认删除当前桌宠档案？绑定到该档案的工作区会回退到默认桌宠档案。', '删除桌宠档案', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
    await companionStore.deleteCompanion(companionId)
    await handleCompanionChange('default')
  } catch (error) {
    console.debug('[GlobalDialogs] delete companion cancelled or failed:', error)
  }
}
</script>
