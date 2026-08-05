<template>
  <!-- Permission Dialog -->
  <el-dialog
    v-model="dialogStore.permissionDialogVisible"
    :title="t('dialogs.permission.title')"
    width="480px"
    :before-close="dismissPermissionRequest"
    @closed="handlePermissionDialogClosed"
  >
    <div v-if="dialogStore.permissionRequest">
      <p><strong>{{ t('dialogs.permission.tool') }}：</strong>{{ dialogStore.permissionRequest.tool_name }}</p>
      <p v-if="dialogStore.permissionRequest.capability_id"><strong>Capability：</strong>{{ dialogStore.permissionRequest.capability_id }}</p>
      <p v-if="dialogStore.permissionRequest.capability_kind"><strong>{{ t('dialogs.permission.category') }}：</strong>{{ dialogStore.permissionRequest.capability_type }} / {{ dialogStore.permissionRequest.capability_kind }}</p>
      <p><strong>{{ t('dialogs.permission.risk') }}：</strong>{{ dialogStore.permissionRequest.risk_level }}</p>
      <p><strong>{{ t('dialogs.permission.reason') }}：</strong>{{ dialogStore.permissionRequest.reason }}</p>
      <pre class="permission-args" :aria-label="t('dialogs.permission.arguments')">{{ JSON.stringify(dialogStore.permissionRequest.args || {}, null, 2) }}</pre>
      <el-checkbox v-model="rememberPermissionDecision">{{ t('dialogs.permission.remember') }}</el-checkbox>
    </div>
    <template #footer>
      <el-button data-testid="permission-deny" @click="respondPermission(false)">{{ t('dialogs.permission.deny') }}</el-button>
      <el-button data-testid="permission-allow" type="primary" @click="respondPermission(true)">{{ t('dialogs.permission.allow') }}</el-button>
    </template>
  </el-dialog>

  <!-- Workspace Drawer -->
  <WorkspaceDrawer
    :visible="dialogStore.workspaceDrawerVisible"
    :workspace="workspaceStore.activeWorkspace"
    :companions="companionStore.companions"
    :active-companion="companionStore.activeCompanion"
    :muted="muted"
    :do-not-disturb="doNotDisturb"
    :dnd-loading="dndLoading"
    :proactivity-preset="proactivityPreset"
    @update:visible="dialogStore.workspaceDrawerVisible = $event"
    @update-field="handleWorkspaceFieldUpdate"
    @set-muted="setMuted"
    @set-dnd="setDrawerDoNotDisturb"
    @set-proactivity="setDrawerProactivity"
  />

  <!-- Edit desktop pet profile dialog -->
  <el-dialog v-model="dialogStore.editCompanionDialogVisible" :title="t('dialogs.profile.title')" width="560px" @open="initEditCompanionForm">
    <el-form label-position="top" size="small">
      <el-form-item :label="t('dialogs.profile.name')"><el-input v-model="editCompanionForm.name" /></el-form-item>
      <el-form-item :label="t('dialogs.profile.modelType')"><el-select v-model="editCompanionForm.model_type" style="width:100%"><el-option label="Live2D" value="live2d" /><el-option label="VRM" value="vrm" /></el-select></el-form-item>
      <el-form-item :label="t('dialogs.profile.modelId')"><el-input v-model="editCompanionForm.model_id" /></el-form-item>
      <el-form-item :label="t('dialogs.profile.temperament')"><el-select v-model="editCompanionForm.temperament" style="width:100%"><el-option :label="t('dialogs.profile.temperament.warm')" value="warm" /><el-option :label="t('dialogs.profile.temperament.playful')" value="playful" /><el-option :label="t('dialogs.profile.temperament.reserved')" value="reserved" /></el-select></el-form-item>
      <el-form-item :label="t('dialogs.profile.attachment')"><el-select v-model="editCompanionForm.attachment_style" style="width:100%"><el-option :label="t('dialogs.profile.attachment.secure')" value="secure" /><el-option :label="t('dialogs.profile.attachment.independent')" value="independent" /><el-option :label="t('dialogs.profile.attachment.attached')" value="attached" /></el-select></el-form-item>
      <el-form-item :label="t('dialogs.profile.support')"><el-select v-model="editCompanionForm.support_style" style="width:100%"><el-option :label="t('dialogs.profile.support.gentle')" value="gentle" /><el-option :label="t('dialogs.profile.support.analytical')" value="analytical" /><el-option :label="t('dialogs.profile.support.cheerful')" value="cheerful" /></el-select></el-form-item>
      <el-form-item label="TTS Base URL"><el-input v-model="editCompanionForm.voice_profile.base_url" /></el-form-item>
      <el-form-item :label="t('dialogs.profile.referenceAudio')"><el-input v-model="editCompanionForm.voice_profile.ref_audio" /></el-form-item>
      <el-form-item :label="t('dialogs.profile.referenceText')"><el-input v-model="editCompanionForm.voice_profile.ref_text" type="textarea" :rows="2" /></el-form-item>
      <el-form-item :label="t('dialogs.profile.voiceLanguage')"><el-input v-model="editCompanionForm.voice_profile.lang" /></el-form-item>
      <el-form-item :label="t('dialogs.profile.emotion')"><el-input v-model="editCompanionForm.emotion_state" /></el-form-item>
      <el-form-item :label="t('dialogs.profile.affinity')"><el-input v-model="editCompanionForm.affinity_state" type="number" /></el-form-item>
      <el-form-item :label="t('dialogs.profile.energy')"><el-input v-model="editCompanionForm.energy_state" type="number" /></el-form-item>
      <el-form-item :label="t('dialogs.profile.trust')"><el-input v-model="editCompanionForm.trust_state" type="number" /></el-form-item>
      <el-form-item :label="t('dialogs.profile.intimacy')"><el-input v-model="editCompanionForm.intimacy_state" type="number" /></el-form-item>
      <el-form-item :label="t('dialogs.profile.interruptibility')"><el-input v-model="editCompanionForm.interruptibility_state" type="number" /></el-form-item>
      <el-form-item :label="t('dialogs.profile.fatigue')"><el-input v-model="editCompanionForm.fatigue_state" type="number" /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialogStore.editCompanionDialogVisible = false">{{ t('common.cancel') }}</el-button>
      <el-button type="primary" @click="submitEditCompanion">{{ t('common.save') }}</el-button>
    </template>
  </el-dialog>

</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useDialogStore } from '@/stores/dialogStore'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { useCompanionStore } from '@/stores/companionStore'
import { useCompanionRuntimeBridge } from '../../composables/useCompanionRuntimeBridge'
import WorkspaceDrawer from '../../WorkspaceDrawer.vue'
import { getSocketClient } from '@/net/socketClient'
import { publishCompanionRuntimeEvent } from '../../runtime/companionRuntime'
import { useChatStore } from '@/stores/chatStore'
import { useI18n } from '@/i18n'

const dialogStore = useDialogStore()
const workspaceStore = useWorkspaceStore()
const companionStore = useCompanionStore()
const chatStore = useChatStore()
const { t } = useI18n()
const {
  applyActiveCompanionRuntime,
  doNotDisturb,
  proactivityPreset,
  setDoNotDisturb,
  setProactivityPreset,
} = useCompanionRuntimeBridge()
const muted = computed(() => chatStore.chatOptions.tts_enabled === false)
const dndLoading = ref(false)

const rememberPermissionDecision = ref(false)
const respondingPermissionIds = new Set<string>()

const errorMessage = (error: unknown) => error instanceof Error ? error.message : t('common.error.unknown')

const respondPermission = async (allow: boolean) => {
  const req = dialogStore.permissionRequest
  if (!req || respondingPermissionIds.has(req.request_id)) return
  respondingPermissionIds.add(req.request_id)
  try {
    getSocketClient().sendPermissionResponse(req.request_id, allow, rememberPermissionDecision.value)
    ElMessage.success(allow ? t('dialogs.permission.allowed') : t('dialogs.permission.denied'))
  } catch (error) {
    ElMessage.error(t('dialogs.permission.responseFailed', { message: errorMessage(error) }))
  } finally {
    if (dialogStore.permissionRequest?.request_id === req.request_id) {
      dialogStore.permissionDialogVisible = false
      dialogStore.permissionRequest = null
    }
    void publishCompanionRuntimeEvent({ source: 'permission', permission: 'none', requestId: req.request_id })
    respondingPermissionIds.delete(req.request_id)
  }
}

const dismissPermissionRequest = (done: () => void) => {
  void respondPermission(false).finally(done)
}

const handlePermissionDialogClosed = () => {
  if (dialogStore.permissionRequest) void respondPermission(false)
}

const handleWorkspaceFieldUpdate = async (field: string, value: string) => {
  const workspaceId = workspaceStore.activeWorkspaceId
  const patch: Record<string, string> = { [field]: value }
  try {
    await workspaceStore.updateWorkspaceRemote(workspaceId, patch)
    ElMessage.success(t('dialogs.workspace.saved'))
  } catch {
    ElMessage.error(t('dialogs.workspace.saveFailed'))
  }
}

const setMuted = (value: boolean) => {
  chatStore.setTtsEnabled(!value)
  ElMessage.success(value ? t('companion.home.muted') : t('companion.home.unmuted'))
}

const setDrawerDoNotDisturb = async (enabled: boolean) => {
  if (dndLoading.value) return
  dndLoading.value = true
  try {
    await setDoNotDisturb(enabled)
    ElMessage.success(enabled ? t('companion.home.dndEnabled') : t('companion.home.dndDisabled'))
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : t('companion.home.petActionError'))
  } finally {
    dndLoading.value = false
  }
}

const setDrawerProactivity = (value: 'conservative' | 'standard') => {
  if (setProactivityPreset(value)) ElMessage.success(t(`companion.home.proactivitySet.${value}`))
  else ElMessage.error(t('companion.home.proactivityError'))
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
  ElMessage.success(t('dialogs.profile.saved'))
}

</script>
