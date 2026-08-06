<template>
  <PanelShell :title="t('navigation.companion.title')" tone="companion">
    <div class="companion-home">
      <section v-if="companionStore.loading && !activeCompanion" class="home-state" aria-live="polite">
        <strong>{{ t('companion.home.loading') }}</strong>
      </section>

      <section v-else-if="!activeCompanion" class="home-state" aria-live="polite">
        <template v-if="companionLoadError">
          <el-alert
            type="warning"
            :title="t('companion.home.loadError')"
            :description="companionLoadError"
            :closable="false"
            show-icon
          />
          <el-button type="primary" @click="loadCompanionHome">{{ t('shell.retry') }}</el-button>
        </template>
        <template v-else>
          <el-empty :description="t('companion.home.empty')" />
          <el-button type="primary" @click="loadCompanionHome">{{ t('shell.retry') }}</el-button>
        </template>
      </section>

      <template v-else>
        <el-alert
          v-if="runtimeSyncError || petQuickError"
          class="runtime-alert"
          type="warning"
          :title="t('companion.home.degraded')"
          :description="runtimeSyncError || petQuickError"
          :closable="false"
          show-icon
        />

        <CompanionHero
          :companion-name="activeCompanion.name"
          :avatar="activeCompanion.avatar"
          :model-type="activeCompanion.model_type || petRuntimeState.modelType"
          :model-id="activeCompanion.model_id || petRuntimeState.modelId || t('companion.home.modelUnbound')"
          :presentation-state="presentationState"
          :state-label="presentationLabel"
          :state-detail="presentationDetail"
          :availability-title="t('companion.home.availability')"
          :availability-label="availabilityLabel"
          :permission-title="t('companion.home.permission')"
          :permission-label="permissionLabel"
          :dnd-title="t('companion.home.dnd')"
          :dnd-label="petRuntimeState.doNotDisturb ? t('companion.home.enabled') : t('companion.home.disabled')"
        />

        <CompanionQuickActions
          :actions-title="t('companion.home.actions')"
          :chat-path="modulePath('chat')"
          :talk-label="t('companion.home.talk')"
          :mute-label="t('companion.home.mute')"
          :unmute-label="t('companion.home.unmute')"
          :interrupt-label="t('companion.home.interrupt')"
          :can-interrupt="canInterrupt"
          :muted="muted"
          :dnd="petRuntimeState.doNotDisturb"
          :dnd-label="t('companion.home.dnd')"
          :dnd-loading="petOperationKey === 'dnd'"
          :proactivity-label="t('companion.home.proactivity')"
          :proactivity-preset="proactivityPreset"
          :conservative-label="t('companion.home.proactivityConservative')"
          :standard-label="t('companion.home.proactivityStandard')"
          @interrupt="interruptCompanion"
          @toggle-mute="toggleMute"
          @set-dnd="setPetDoNotDisturb"
          @set-proactivity="setHomeProactivityPreset"
        />

        <CompanionActivitySummary
          :summary-title="t('companion.home.recent')"
          :summary-subtitle="t('companion.home.recentSubtitle')"
          :memory-title="t('companion.home.memory')"
          :memory-total="memoryTotal"
          :recent-signals="recentSignals"
          :memory-empty-label="t('companion.home.memoryEmpty')"
          :memory-path="modulePath('memory')"
          :open-memory-label="t('companion.home.openMemory')"
          :task-title="t('companion.home.task')"
          :task-status="taskStatusLabel"
          :task-summary="taskSummary"
          :task-path="modulePath('agent-trace')"
          :open-task-label="t('companion.home.openTask')"
          :receipt-path="modulePath('agent-governance')"
          :open-receipt-label="t('companion.home.openReceipt')"
          :relationship-title="t('companion.home.relationship')"
          :relationship-summary="relationshipSummary"
        />

        <nav class="advanced-links" :aria-label="t('companion.home.advanced')">
          <span>{{ t('companion.home.advanced') }}</span>
          <router-link :to="modulePath('prompt')">{{ t('companion.home.personaProfile') }}</router-link>
          <router-link :to="modulePath('persona-memory')">{{ t('companion.home.heartbeatSettings') }}</router-link>
          <router-link :to="modulePath('settings')">{{ t('companion.home.visionSettings') }}</router-link>
          <router-link :to="modulePath('memory')">{{ t('companion.home.memoryMaintenance') }}</router-link>
          <router-link :to="modulePath('pet')">{{ t('companion.home.petSettings') }}</router-link>
          <router-link :to="modulePath('agent-governance')">{{ t('companion.home.permissionSettings') }}</router-link>
          <router-link :to="modulePath('agent-trace')">{{ t('companion.home.diagnostics') }}</router-link>
        </nav>
      </template>
    </div>
  </PanelShell>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import PanelShell from '@/shared/components/panel/PanelShell.vue'
import CompanionActivitySummary from '../components/CompanionActivitySummary.vue'
import CompanionHero from '../components/CompanionHero.vue'
import CompanionQuickActions from '../components/CompanionQuickActions.vue'
import { useCompanionRuntimeBridge } from '@/app/composables/useCompanionRuntimeBridge'
import { useChatStore } from '@/stores/chatStore'
import { useCompanionStore } from '@/stores/companionStore'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { petControlClient, systemClient } from '@/api/client'
import { useI18n } from '@/i18n'
import type { CompanionRuntimeSnapshot } from '@/../shared/agent'
import { DEFAULT_PET_CONTROL_STATE, type PetControlState } from '@/../shared/pet-control'
import { isAuthMissingError } from '@/api/clients/http-client'

type MemoryState = NonNullable<CompanionRuntimeSnapshot['memory_state']>
type RecentSignal = NonNullable<MemoryState['recent_signals']>[number]
type PetOperationKey = 'dnd' | null

const companionStore = useCompanionStore()
const e2eMode = Boolean(window.petApi?.e2e)
const chatStore = useChatStore()
const workspaceStore = useWorkspaceStore()
const { t } = useI18n()
const {
  applyActiveCompanionRuntime,
  runtimeSnapshot,
  runtimeState,
  presentationState,
  proactivityPreset,
  setProactivityPreset,
} = useCompanionRuntimeBridge()

const activeCompanion = computed(() => companionStore.activeCompanion)
const activeWorkspaceId = computed(() => workspaceStore.activeWorkspaceId)
const memoryState = ref<MemoryState | null>(null)
const relationshipStage = ref<string | null>(null)
const proactiveReason = ref('')
const runtimeSyncError = ref('')
const companionLoadError = ref('')
const petQuickError = ref('')
const petOperationKey = ref<PetOperationKey>(null)
const petRuntimeState = reactive<PetControlState>({ ...DEFAULT_PET_CONTROL_STATE })
let runtimeLoadSequence = 0
let companionHomeLoading = false

const modulePath = (moduleId: string) => `/w/${activeWorkspaceId.value}/${moduleId}`
const resolveCompanionLoadError = (error: unknown) => isAuthMissingError(error)
  ? t('companion.home.authorizationRequired')
  : error instanceof Error ? error.message : t('companion.home.loadError')
const muted = computed(() => chatStore.chatOptions.tts_enabled === false)
const canInterrupt = computed(() =>
  chatStore.state.isGenerating ||
  chatStore.state.isSpeaking ||
  chatStore.state.isTTSPlaying ||
  runtimeState.activity !== 'idle',
)

const presentationLabel = computed(() => t(`companion.home.state.${presentationState.value}`))
const presentationDetail = computed(() => {
  if (runtimeSyncError.value) return runtimeSyncError.value
  if (chatStore.state.lastError) return chatStore.state.lastError
  if (proactiveReason.value) return proactiveReason.value
  if (chatStore.state.currentText) return chatStore.state.currentText
  return t(`companion.home.stateDetail.${presentationState.value}`)
})
const availabilityLabel = computed(() => t(`companion.home.availability.${runtimeState.availability}`))
const permissionLabel = computed(() => runtimeState.permission === 'waiting'
  ? t('companion.home.permissionWaiting')
  : t('companion.home.permissionNone'))

const memoryTotal = computed(() => {
  const state = memoryState.value
  if (!state) return 0
  return state.profile_count + state.semantic_count + state.episodic_count + state.relationship_count + state.working_count + state.reflective_count
})
const recentSignals = computed<RecentSignal[]>(() => memoryState.value?.recent_signals?.slice(0, 3) ?? [])
const relationshipSummary = computed(() => relationshipStage.value
  ? t('companion.home.relationshipStage', { stage: relationshipStage.value })
  : '')

const taskStatusLabel = computed(() => {
  if (runtimeState.permission === 'waiting') return t('companion.home.taskWaiting')
  if (runtimeState.activity === 'executing') return t('companion.home.taskExecuting')
  if (chatStore.state.lastAgentEnvelope) return t('companion.home.taskRecent')
  return t('companion.home.taskIdle')
})
const taskSummary = computed(() => {
  const envelope = chatStore.state.lastAgentEnvelope
  if (runtimeState.permission === 'waiting') {
    return runtimeState.lastRequestId
      ? t('companion.home.permissionRequest', { id: runtimeState.lastRequestId })
      : t('companion.home.permissionWaitingDetail')
  }
  if (envelope?.reply) return envelope.reply
  if (runtimeState.lastRequestId) return t('companion.home.activeRequest', { id: runtimeState.lastRequestId })
  return t('companion.home.noTask')
})

const isPetControlState = (value: unknown): value is PetControlState =>
  Boolean(value && typeof value === 'object' && 'modelType' in value && 'visible' in value)

const applyPetControlState = (value: unknown) => {
  if (isPetControlState(value)) Object.assign(petRuntimeState, value)
}

const refreshPetState = async () => {
  if (typeof petControlClient.getState !== 'function') return
  try {
    applyPetControlState(await petControlClient.getState())
    petQuickError.value = ''
  } catch (error) {
    petQuickError.value = error instanceof Error ? error.message : t('companion.home.petStateError')
  }
}

const applyRuntimeSnapshot = (payload: CompanionRuntimeSnapshot) => {
  memoryState.value = payload.memory_state || null
  relationshipStage.value = payload.relationship?.summary?.relationship_stage || payload.companion_state?.stage || null
  proactiveReason.value = payload.companion_state?.proactive_state?.trigger_reason || ''
  runtimeSyncError.value = ''
}

const loadRuntime = async () => {
  const companionId = activeCompanion.value?.id
  const requestId = ++runtimeLoadSequence
  if (!companionId) return
  try {
    const payload = await systemClient.companionRuntime(8)
    if (requestId !== runtimeLoadSequence || activeCompanion.value?.id !== companionId) return
    applyRuntimeSnapshot(payload)
  } catch (error) {
    if (requestId !== runtimeLoadSequence || activeCompanion.value?.id !== companionId) return
    runtimeSyncError.value = error instanceof Error ? error.message : t('companion.home.runtimeError')
  }
}

const loadCompanionHome = async () => {
  companionLoadError.value = ''
  companionHomeLoading = true
  try {
    try {
      await companionStore.loadCompanions()
      if (!e2eMode) await applyActiveCompanionRuntime()
    } catch (error) {
      companionLoadError.value = resolveCompanionLoadError(error)
    }
    await Promise.all([e2eMode ? undefined : loadRuntime(), refreshPetState()])
  } finally {
    companionHomeLoading = false
  }
}

const interruptCompanion = () => {
  chatStore.interrupt()
}

const toggleMute = () => {
  const nextEnabled = muted.value
  chatStore.setTtsEnabled(nextEnabled)
  ElMessage.success(nextEnabled ? t('companion.home.unmuted') : t('companion.home.muted'))
}

const setPetDoNotDisturb = async (enabled: boolean) => {
  if (petOperationKey.value) return
  petOperationKey.value = 'dnd'
  petQuickError.value = ''
  try {
    applyPetControlState(await petControlClient.setDoNotDisturb(enabled))
    petRuntimeState.doNotDisturb = enabled
    ElMessage.success(enabled ? t('companion.home.dndEnabled') : t('companion.home.dndDisabled'))
  } catch (error) {
    petQuickError.value = error instanceof Error ? error.message : t('companion.home.petActionError')
    ElMessage.error(petQuickError.value)
  } finally {
    petOperationKey.value = null
  }
}

const setHomeProactivityPreset = (value: string) => {
  const preset = value === 'standard' ? 'standard' : 'conservative'
  if (setProactivityPreset(preset)) ElMessage.success(t(`companion.home.proactivitySet.${preset}`))
  else ElMessage.error(t('companion.home.proactivityError'))
}

watch(activeCompanion, () => {
  if (companionHomeLoading) return
  if (!e2eMode) {
    void applyActiveCompanionRuntime()
    void loadRuntime()
  }
  void refreshPetState()
})

watch(runtimeSnapshot, (snapshot) => {
  if (snapshot) applyRuntimeSnapshot(snapshot)
})

onMounted(() => {
  void loadCompanionHome()
})
</script>

<style scoped>
.companion-home {
  display: grid;
  gap: 16px;
  min-width: 0;
  color: var(--yui-text);
}

.home-state {
  display: grid;
  min-height: 360px;
  place-items: center;
  gap: 12px;
}

.runtime-alert {
  width: 100%;
}

.advanced-links {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 16px;
  border-top: 1px solid var(--yui-border);
  padding: 14px 2px 0;
}

.advanced-links span {
  color: var(--yui-muted);
  font-size: 12px;
  font-weight: 760;
}

.advanced-links a {
  color: var(--yui-accent);
  font-size: 12px;
  font-weight: 720;
  text-decoration: none;
}

.advanced-links a:focus-visible {
  outline: 3px solid var(--yui-accent);
  outline-offset: 2px;
}

@media (max-width: 760px) {
  .companion-home {
    gap: 12px;
  }

  .advanced-links {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
