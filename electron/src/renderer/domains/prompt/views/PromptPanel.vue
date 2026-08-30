<template>
  <PanelShell title="提示词设置" tone="companion">
    <div class="prompt-panel">
      <section class="prompt-status-grid" aria-label="提示词状态">
        <article v-for="item in promptStatusItems" :key="item.key" class="prompt-status-item" :class="`is-${item.tone}`">
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
        </article>
      </section>

      <section class="prompt-card prompt-card--split">
        <header class="prompt-card-header">
          <div>
        <h3>工作区系统提示词</h3>
            <span>{{ activeWorkspace.name }}</span>
          </div>
            <el-button size="small" type="primary" :disabled="!workspacePromptDirty" :loading="savingWorkspacePrompt" @click="saveWorkspaceSystemPrompt">保存工作区提示词</el-button>
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
        <h3>桌宠人格提示词</h3>
            <span>{{ activeCompanion?.name || '未加载桌宠档案' }}</span>
          </div>
          <div class="prompt-card-actions">
          <el-button size="small" plain :loading="companionStore.loading" @click="loadCompanions">刷新桌宠档案</el-button>
          <el-button size="small" type="primary" :disabled="!activeCompanion || !companionPromptDirty" :loading="savingCompanionPrompt" @click="saveCompanionPersonaPrompt">保存人格提示词</el-button>
          </div>
        </header>
        <el-input
          v-model="companionPersonaPrompt"
          type="textarea"
          :rows="5"
          resize="none"
        />
      </section>

      <section class="prompt-editor-block">
        <header class="prompt-card-header prompt-editor-header">
          <div>
            <h3>Agent 提示词工程</h3>
            <span>{{ promptSummary }}</span>
          </div>
        </header>
        <WorkspacePromptEditor />
      </section>
    </div>
  </PanelShell>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import PanelShell from '@/shared/components/panel/PanelShell.vue'
import WorkspacePromptEditor from '@/shared/components/prompt/WorkspacePromptEditor.vue'
import { useCompanionRuntimeBridge } from '@/app/composables/useCompanionRuntimeBridge'
import { DEFAULT_DAILY_PROMPT, DEFAULT_WORK_PROMPT, useWorkspaceStore } from '@/stores/workspaceStore'
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
type PromptStatusTone = 'ready' | 'idle' | 'accent'

const workspacePromptDirty = computed(() => workspaceSystemPrompt.value !== (activeWorkspace.value.system_prompt || ''))
const companionPromptDirty = computed(() => companionPersonaPrompt.value !== (activeCompanion.value?.persona_prompt || ''))

const promptModeLabel = computed(() => {
  const mode = activeWorkspace.value.context.promptMode || 'auto'
  if (mode === 'work') return '任务'
  if (mode === 'daily') return '日常陪伴'
  return workspaceStore.activeWorkspaceId === 'default' ? '自动:日常陪伴' : '自动:任务'
})

const roleCardReady = computed(() => {
  const roleCard = activeWorkspace.value.context.roleCard
  return roleCard.enabled !== false && [
    roleCard.name,
    roleCard.personality,
    roleCard.scenario,
    roleCard.instructions,
    roleCard.firstMessage,
  ].some((value) => Boolean(value?.trim()))
})

const basePromptCustomized = computed(() => {
  const prompts = activeWorkspace.value.context.promptEngineering
  return prompts.workPrompt.trim() !== DEFAULT_WORK_PROMPT.trim() ||
    prompts.dailyPrompt.trim() !== DEFAULT_DAILY_PROMPT.trim()
})

const promptSummary = computed(() => {
  const labels = []
  if (basePromptCustomized.value) labels.push('基础提示词')
  if (roleCardReady.value) labels.push('角色卡')
  if (activeWorkspace.value.context.worldBook.enabled) labels.push('世界书')
  return labels.length ? labels.join(' / ') : '默认'
})

const promptStatusItems = computed<Array<{ key: string; label: string; value: string; tone: PromptStatusTone }>>(() => [
  {
    key: 'core',
    label: '核心约束',
    value: '后端固定',
    tone: 'ready',
  },
  {
    key: 'mode',
    label: '模式',
    value: promptModeLabel.value,
    tone: 'accent',
  },
  {
    key: 'workspace',
    label: '场景提示词',
    value: activeWorkspace.value.system_prompt ? '已设置' : '默认',
    tone: activeWorkspace.value.system_prompt ? 'ready' : 'idle',
  },
  {
    key: 'persona',
    label: '桌宠人格',
    value: activeCompanion.value?.persona_prompt ? '已设置' : '未设置',
    tone: activeCompanion.value?.persona_prompt ? 'ready' : 'idle',
  },
  {
    key: 'role-card',
    label: '角色卡',
    value: roleCardReady.value ? '启用' : '未启用',
    tone: roleCardReady.value ? 'ready' : 'idle',
  },
  {
    key: 'world-book',
    label: '世界书',
    value: activeWorkspace.value.context.worldBook.enabled ? `${activeWorkspace.value.context.worldBook.entries.length} 条` : '未启用',
    tone: activeWorkspace.value.context.worldBook.enabled ? 'ready' : 'idle',
  },
])

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
    ElMessage.warning('桌宠档案加载失败')
  }
}

const saveWorkspaceSystemPrompt = async () => {
  if (savingWorkspacePrompt.value) return
  savingWorkspacePrompt.value = true
  try {
    await workspaceStore.updateWorkspaceRemote(activeWorkspace.value.id, {
      system_prompt: workspaceSystemPrompt.value.trim() || null,
    })
    ElMessage.success('场景提示词已保存')
  } catch {
    ElMessage.error('保存场景提示词失败')
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
    ElMessage.success('桌宠人格提示词已保存')
  } catch {
    ElMessage.error('保存桌宠人格提示词失败')
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
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.prompt-status-grid {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 8px;
}

.prompt-status-item {
  display: grid;
  min-width: 0;
  gap: 5px;
  border: 1px solid var(--yui-border);
  border-radius: 10px;
  background: var(--yui-surface-raised);
  padding: 10px 12px;
}

.prompt-status-item span {
  overflow: hidden;
  color: var(--yui-muted);
  font-size: 12px;
  font-weight: 720;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.prompt-status-item strong {
  overflow: hidden;
  color: var(--yui-text);
  font-size: 14px;
  font-weight: 820;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.prompt-status-item.is-ready {
  background: var(--yui-success-soft);
}

.prompt-status-item.is-accent {
  background: var(--yui-accent-soft);
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
}

.prompt-editor-header {
  border-bottom: 1px solid var(--yui-border);
  padding-bottom: 10px;
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

  .prompt-status-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .prompt-status-grid {
    grid-template-columns: 1fr;
  }

  .prompt-card-header {
    flex-direction: column;
  }

  .prompt-card-actions {
    width: 100%;
    justify-content: flex-start;
  }
}
</style>
