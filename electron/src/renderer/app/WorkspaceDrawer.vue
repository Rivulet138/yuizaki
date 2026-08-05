<template>
  <el-drawer
    :model-value="visible"
    :title="t('workspaceDrawer.title')"
    direction="rtl"
    size="400px"
    class="workspace-drawer"
    @update:model-value="$emit('update:visible', $event)"
  >
    <div class="drawer-content">
      <section class="drawer-section">
        <h3>{{ t('workspaceDrawer.scene.title') }}</h3>
        <el-form label-position="top" size="default" class="w-full">
          <el-form-item :label="t('workspaceDrawer.scene.name')">
            <el-input data-testid="workspace-name" :model-value="workspace.name" :placeholder="t('workspaceDrawer.scene.namePlaceholder')" @change="updateField('name', $event)" />
          </el-form-item>
          <el-form-item :label="t('workspaceDrawer.scene.description')">
            <el-input :model-value="workspace.description || ''" type="textarea" :rows="3" :placeholder="t('workspaceDrawer.scene.descriptionPlaceholder')" resize="none" @change="updateField('description', $event)" />
          </el-form-item>
        </el-form>
      </section>

      <el-divider />

      <section class="drawer-section">
        <div class="section-heading">
          <h3>{{ t('workspaceDrawer.avatar.title') }}</h3>
          <router-link :to="canonicalRoute('pet')" class="text-link" data-testid="workspace-companion-manage">
            {{ t('workspaceDrawer.avatar.manage') }}
          </router-link>
        </div>
        <el-select :model-value="workspace.companion_profile_id || 'default'" class="w-full" @change="updateField('companion_profile_id', $event)">
          <el-option v-for="companion in companions" :key="companion.id" :label="companion.name" :value="companion.id" />
        </el-select>
        <div class="quick-summary" :aria-label="t('workspaceDrawer.avatar.summaryAria')">
          <div><span>{{ t('workspaceDrawer.avatar.model') }}</span><strong>{{ activeCompanion?.model_id || t('workspaceDrawer.avatar.followProfile') }}</strong></div>
          <div><span>{{ t('workspaceDrawer.avatar.voice') }}</span><strong>{{ t('workspaceDrawer.avatar.followVoice') }}</strong></div>
        </div>
      </section>

      <el-divider />

      <section class="drawer-section" :aria-label="t('workspaceDrawer.runtime.aria')">
        <h3>{{ t('workspaceDrawer.runtime.title') }}</h3>
        <label class="toggle-row">
          <span>
            <strong>{{ t('workspaceDrawer.runtime.mute') }}</strong>
            <small>{{ t('workspaceDrawer.runtime.muteHint') }}</small>
          </span>
          <input
            data-testid="workspace-mute"
            type="checkbox"
            :checked="muted"
            :aria-label="t('workspaceDrawer.runtime.mute')"
            @change="emitChecked('set-muted', $event)"
          />
        </label>
        <label class="toggle-row">
          <span>
            <strong>{{ t('workspaceDrawer.runtime.dnd') }}</strong>
            <small>{{ t('workspaceDrawer.runtime.dndHint') }}</small>
          </span>
          <input
            data-testid="workspace-dnd"
            type="checkbox"
            :checked="doNotDisturb"
            :disabled="dndLoading"
            :aria-label="t('workspaceDrawer.runtime.dnd')"
            @change="emitChecked('set-dnd', $event)"
          />
        </label>
        <div class="preset-row">
          <span>
            <strong>{{ t('workspaceDrawer.runtime.proactivity') }}</strong>
            <small>{{ t('workspaceDrawer.runtime.proactivityHint') }}</small>
          </span>
          <div class="segmented-control" role="group" :aria-label="t('workspaceDrawer.runtime.proactivity')">
            <button
              data-testid="workspace-proactivity-conservative"
              type="button"
              :aria-pressed="proactivityPreset === 'conservative'"
              @click="$emit('set-proactivity', 'conservative')"
            >{{ t('workspaceDrawer.runtime.conservative') }}</button>
            <button
              data-testid="workspace-proactivity-standard"
              type="button"
              :aria-pressed="proactivityPreset === 'standard'"
              @click="$emit('set-proactivity', 'standard')"
            >{{ t('workspaceDrawer.runtime.standard') }}</button>
          </div>
        </div>
      </section>

      <el-divider />

      <section class="drawer-section">
        <h3>{{ t('workspaceDrawer.capabilities.title') }}</h3>
        <router-link :to="canonicalRoute('settings')" class="summary-link" data-testid="workspace-model-summary">
          <span>{{ t('workspaceDrawer.capabilities.model') }}</span><strong>{{ workspace.default_model || t('workspaceDrawer.capabilities.globalModel') }}</strong>
        </router-link>
        <router-link :to="canonicalRoute('memory')" class="summary-link" data-testid="workspace-memory-summary">
          <span>{{ t('workspaceDrawer.capabilities.memory') }}</span><strong>{{ memoryScopeSummary }}</strong>
        </router-link>
        <router-link :to="canonicalRoute('tool')" class="summary-link" data-testid="workspace-tool-summary">
          <span>{{ t('workspaceDrawer.capabilities.tools') }}</span><strong>{{ toolSummary }}</strong>
        </router-link>
        <router-link :to="canonicalRoute('agent-governance')" class="summary-link" data-testid="workspace-mcp-summary">
          <span>MCP</span><strong>{{ workspace.mcp_preset_id || t('workspaceDrawer.capabilities.allMcp') }}</strong>
        </router-link>
      </section>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { WorkspaceRecord } from '@/../shared/workspace'
import type { CompanionRecord } from '@/api/clients/companion-client'
import { useI18n } from '@/i18n'

const props = defineProps<{
  visible: boolean
  workspace: WorkspaceRecord
  companions: CompanionRecord[]
  activeCompanion: CompanionRecord | null
  muted: boolean
  doNotDisturb: boolean
  dndLoading: boolean
  proactivityPreset: 'conservative' | 'standard'
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'update-field', field: string, value: string): void
  (e: 'set-muted', value: boolean): void
  (e: 'set-dnd', value: boolean): void
  (e: 'set-proactivity', value: 'conservative' | 'standard'): void
}>()

const { t } = useI18n()
const updateField = (field: string, value: string) => emit('update-field', field, value)
const canonicalRoute = (panel: string) => `/w/${encodeURIComponent(props.workspace.id)}/${panel}`
const emitChecked = (event: 'set-muted' | 'set-dnd', value: Event) => {
  emit(event, (value.target as HTMLInputElement).checked)
}

const memoryScopeSummary = computed(() => ({
  global: t('workspaceDrawer.memoryScope.global'),
  workspace: t('workspaceDrawer.memoryScope.workspace'),
  session: t('workspaceDrawer.memoryScope.session'),
}[props.workspace.memory_scope || 'workspace'] || props.workspace.memory_scope || t('workspaceDrawer.memoryScope.workspace')))

const toolSummary = computed(() => {
  const preset = props.workspace.tool_preset?.trim()
  if (!preset) return t('workspaceDrawer.capabilities.allTools')
  try {
    const parsed = JSON.parse(preset) as unknown
    if (Array.isArray(parsed)) {
      const ids = parsed.filter((item): item is string => typeof item === 'string' && Boolean(item.trim()))
      return ids.length ? ids.join(t('workspaceDrawer.toolSeparator')) : t('workspaceDrawer.capabilities.allTools')
    }
  } catch {
    // Older backends may store a named preset instead of a JSON list.
  }
  return preset
})
</script>

<style scoped>
.workspace-drawer :deep(.el-drawer__header) {
  margin-bottom: 0;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--yui-border);
}

.workspace-drawer :deep(.el-drawer__body) {
  padding: 20px;
}

.drawer-content,
.drawer-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.drawer-section h3 {
  margin: 0;
  color: var(--yui-text);
  font-size: 14px;
}

.section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.text-link {
  color: var(--yui-accent);
  font-size: 12px;
  font-weight: 700;
  text-decoration: none;
}

.quick-summary {
  display: grid;
  gap: 8px;
}

.quick-summary > div,
.summary-link {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.quick-summary span,
.summary-link span {
  color: var(--yui-muted);
}

.quick-summary strong,
.summary-link strong {
  min-width: 0;
  overflow-wrap: anywhere;
  text-align: right;
}

.toggle-row,
.preset-row {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 10px 0;
}

.toggle-row > span,
.preset-row > span {
  display: grid;
  min-width: 0;
  gap: 3px;
}

.toggle-row small,
.preset-row small {
  color: var(--yui-muted);
  line-height: 1.4;
}

.toggle-row input {
  width: 18px;
  height: 18px;
  flex: 0 0 auto;
  accent-color: var(--yui-primary);
}

.segmented-control {
  display: inline-flex;
  flex: 0 0 auto;
  border: 1px solid var(--yui-border-strong);
  border-radius: 6px;
  overflow: hidden;
}

.segmented-control button {
  min-height: 32px;
  padding: 0 10px;
  border: 0;
  background: var(--yui-surface);
  color: var(--yui-muted);
  cursor: pointer;
}

.segmented-control button + button {
  border-left: 1px solid var(--yui-border-strong);
}

.segmented-control button[aria-pressed='true'] {
  background: var(--yui-primary);
  color: #fff;
}

.summary-link {
  padding: 10px 0;
  border-bottom: 1px solid var(--yui-border);
  color: inherit;
  text-decoration: none;
}

.summary-link:focus-visible,
.text-link:focus-visible,
.segmented-control button:focus-visible,
.toggle-row input:focus-visible {
  outline: 2px solid var(--yui-primary);
  outline-offset: 2px;
}
</style>
