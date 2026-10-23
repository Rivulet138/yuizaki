<template>
  <PanelShell :title="t('promptPanel.panel.title')" tone="companion">
    <div class="prompt-panel">
      <section class="prompt-card prompt-card--split">
        <header class="prompt-card-header">
          <div>
            <h3>{{ t('promptPanel.workspace.title') }}</h3>
            <span>{{ activeWorkspace.name }}</span>
          </div>
            <el-button size="small" type="primary" :disabled="!workspacePromptDirty" :loading="savingWorkspacePrompt" @click="saveWorkspaceSystemPrompt">{{ t('promptPanel.workspace.save') }}</el-button>
        </header>
        <el-input
          v-model="workspaceSystemPrompt"
          type="textarea"
          :rows="5"
          resize="none"
        />
      </section>

      <section class="prompt-card prompt-card--split">
        <header class="prompt-card-header">
          <div>
            <h3>{{ t('promptPanel.companion.title') }}</h3>
            <span>{{ activeCompanion?.name || t('promptPanel.companion.noProfile') }}</span>
          </div>
          <div class="prompt-card-actions">
          <el-button size="small" plain :loading="companionStore.loading" @click="loadCompanions">{{ t('promptPanel.companion.refresh') }}</el-button>
          <el-button size="small" type="primary" :disabled="!activeCompanion || !companionPromptDirty" :loading="savingCompanionPrompt" @click="saveCompanionPersonaPrompt">{{ t('promptPanel.companion.save') }}</el-button>
          </div>
        </header>
        <el-input
          v-model="companionPersonaPrompt"
          type="textarea"
          :rows="5"
          resize="none"
        />
      </section>

      <details class="prompt-editor-block">
        <summary class="prompt-card-header prompt-editor-header">
          <span>
            <strong>{{ t('promptPanel.advanced.title') }}</strong>
            <small>{{ t('promptPanel.advanced.hint') }}</small>
          </span>
          <span class="prompt-editor-chevron" aria-hidden="true">⌄</span>
        </summary>
        <WorkspacePromptEditor />
      </details>
    </div>
  </PanelShell>
</template>

<script setup lang="ts">
import { ElButton } from 'element-plus'
import 'element-plus/es/components/button/style/css'
import { ElInput } from 'element-plus'
import 'element-plus/es/components/input/style/css'
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import PanelShell from '@/shared/components/panel/PanelShell.vue'
import { t } from '@/i18n'
import WorkspacePromptEditor from '@/shared/components/prompt/WorkspacePromptEditor.vue'
import { useCompanionRuntimeBridge } from '@/app/composables/useCompanionRuntimeBridge'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { useCompanionStore } from '@/stores/companionStore'

const workspaceStore = useWorkspaceStore()
const companionStore = useCompanionStore()
const { applyActiveCompanionRuntime } = useCompanionRuntimeBridge()

const workspaceSystemPrompt = ref('')
const companionPersonaPrompt = ref('')
const savingWorkspacePrompt = ref(false)
const savingCompanionPrompt = ref(false)

const activeWorkspace = computed(() => workspaceStore.activeWorkspace)
const activeCompanion = computed(() => companionStore.activeCompanion)
const workspacePromptDirty = computed(() => workspaceSystemPrompt.value !== (activeWorkspace.value.system_prompt || ''))
const companionPromptDirty = computed(() => companionPersonaPrompt.value !== (activeCompanion.value?.persona_prompt || ''))

const syncWorkspaceSystemPrompt = () => {
  workspaceSystemPrompt.value = activeWorkspace.value.system_prompt || ''
}

const syncCompanionPersonaPrompt = () => {
  companionPersonaPrompt.value = activeCompanion.value?.persona_prompt || ''
}

const loadCompanions = async () => {
  try {
    await companionStore.loadCompanions()
    syncCompanionPersonaPrompt()
  } catch {
    ElMessage.warning(t('promptPanel.companion.loadFailed'))
  }
}

const saveWorkspaceSystemPrompt = async () => {
  if (savingWorkspacePrompt.value) return
  savingWorkspacePrompt.value = true
  try {
    await workspaceStore.updateWorkspaceRemote(activeWorkspace.value.id, {
      system_prompt: workspaceSystemPrompt.value.trim() || null,
    })
    ElMessage.success(t('promptPanel.workspace.saved'))
  } catch {
    ElMessage.error(t('promptPanel.workspace.saveFailed'))
  } finally {
    savingWorkspacePrompt.value = false
  }
}

const saveCompanionPersonaPrompt = async () => {
  if (savingCompanionPrompt.value || !activeCompanion.value) return
  savingCompanionPrompt.value = true
  try {
    await companionStore.updateCompanion(activeCompanion.value.id, {
      persona_prompt: companionPersonaPrompt.value.trim() || null,
    })
    await applyActiveCompanionRuntime()
    ElMessage.success(t('promptPanel.companion.saved'))
  } catch {
    ElMessage.error(t('promptPanel.companion.saveFailed'))
  } finally {
    savingCompanionPrompt.value = false
  }
}

watch(() => activeWorkspace.value.id, syncWorkspaceSystemPrompt, { immediate: true })
watch(() => activeWorkspace.value.system_prompt, syncWorkspaceSystemPrompt)
watch(() => activeCompanion.value?.id, syncCompanionPersonaPrompt, { immediate: true })
watch(() => activeCompanion.value?.persona_prompt, syncCompanionPersonaPrompt)

onMounted(() => {
  if (!companionStore.companions.length) {
    void loadCompanions()
  }
})
</script>

<style scoped>
.prompt-panel {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 14px;
}

.prompt-card {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 12px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-raised);
  padding: 14px;
  box-shadow: var(--yui-shadow-card);
}

.prompt-editor-block {
  grid-column: 1 / -1;
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 12px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-raised);
  box-shadow: var(--yui-shadow-card);
  overflow: hidden;
}

.prompt-editor-header {
  padding: 14px;
  cursor: pointer;
  list-style: none;
}

.prompt-editor-header::-webkit-details-marker {
  display: none;
}

.prompt-editor-header > span:first-child {
  display: grid;
  gap: 4px;
}

.prompt-editor-header strong {
  color: var(--yui-text);
  font-size: 14px;
  font-weight: 820;
}

.prompt-editor-header small {
  color: var(--yui-muted);
  font-size: 12px;
  font-weight: 500;
}

.prompt-editor-chevron {
  color: var(--yui-muted);
  font-size: 18px;
  line-height: 1;
  transition: transform 160ms ease;
}

.prompt-editor-block[open] .prompt-editor-chevron {
  transform: rotate(180deg);
}

.prompt-editor-block > :deep(.workspace-prompt-editor) {
  padding: 0 14px 14px;
}

.prompt-card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.prompt-card-header h3 {
  margin: 0;
  color: var(--yui-text);
  font-size: 14px;
  font-weight: 820;
  letter-spacing: 0;
}

.prompt-card-header span {
  display: block;
  margin-top: 4px;
  color: var(--yui-muted);
  font-size: 12px;
  line-height: 1.45;
}

.prompt-card-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

@media (max-width: 960px) {
  .prompt-panel {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .prompt-card-header {
    flex-direction: column;
  }

  .prompt-card-actions {
    width: 100%;
    justify-content: flex-start;
  }
}
</style>
