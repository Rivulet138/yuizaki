<template>
  <section class="pet-model-manager" aria-labelledby="pet-model-title">
    <header class="pet-model-manager__header">
      <div>
        <h2 id="pet-model-title">{{ t('pet.model.title') }}</h2>
        <span>{{ t('pet.model.count', { count: models.length }) }}</span>
      </div>
      <el-button
        type="primary"
        :loading="pendingAction === 'model-import'"
        :disabled="loading || refreshing"
        @click="$emit('import-picker')"
      >
        <el-icon><Upload /></el-icon>
        {{ t('pet.model.import') }}
      </el-button>
    </header>

    <div class="pet-model-manager__body">
      <div v-if="models.length" class="pet-model-manager__selection">
        <el-select v-model="selectedModelId" class="full-field" :placeholder="t('pet.model.choose')" :disabled="loading || refreshing">
          <el-option v-for="model in models" :key="model.id" :label="optionLabel(model)" :value="model.id" />
        </el-select>
        <el-button
          type="primary"
          :loading="pendingAction === 'model-apply'"
          :disabled="loading || refreshing || !selectedModelId"
          @click="$emit('apply')"
        >
          {{ t('pet.model.switch') }}
        </el-button>
        <el-tooltip :content="t('pet.model.refresh')" placement="top">
          <el-button class="pet-model-manager__icon-button" :loading="refreshing" :disabled="refreshing" :aria-label="t('pet.model.refresh')" @click="$emit('refresh')">
            <el-icon><Refresh /></el-icon>
          </el-button>
        </el-tooltip>
      </div>

      <div v-else class="pet-model-manager__empty">
        <el-icon><FolderOpened /></el-icon>
        <strong>{{ t('pet.model.empty') }}</strong>
        <el-button type="primary" :loading="pendingAction === 'model-import'" :disabled="loading || refreshing" @click="$emit('import-picker')">{{ t('pet.model.import') }}</el-button>
      </div>

      <div v-if="currentModel" class="pet-model-manager__summary">
        <dl>
          <div><dt>{{ t('pet.model.type') }}</dt><dd>{{ currentModel.type.toUpperCase() }}</dd></div>
          <div><dt>{{ t('pet.model.source') }}</dt><dd>{{ sourceLabel }}</dd></div>
          <div><dt>{{ t('pet.model.motions') }}</dt><dd>{{ currentModel.motions.length }}</dd></div>
          <div><dt>{{ t('pet.model.expressions') }}</dt><dd>{{ currentModel.expressions.length }}</dd></div>
        </dl>
        <div v-if="capabilities" class="pet-model-manager__capabilities" :aria-label="t('pet.model.capabilities')">
          <span
            v-for="capability in capabilityItems"
            :key="capability.key"
            :class="{ supported: capability.enabled }"
            :aria-label="`${capability.label}: ${capability.enabled ? t('common.enabled') : t('common.disabled')}`"
          >
            <el-icon aria-hidden="true"><CircleCheck v-if="capability.enabled" /><CircleClose v-else /></el-icon>
            {{ capability.label }}
          </span>
        </div>
        <div
          v-if="currentModel.source === 'local' && currentModel.license"
          class="pet-model-manager__license"
          :class="`pet-model-manager__license--${currentModel.license.status}`"
        >
          <strong>{{ t('pet.model.license') }}</strong>
          <template v-if="currentModel.license.status === 'declared'">
            <span>{{ currentModel.license.spdx }}</span>
            <span>{{ currentModel.license.redistributable ? t('pet.model.redistributionAllowed') : t('pet.model.redistributionDisallowed') }}</span>
            <span v-if="currentModel.license.attribution">{{ t('pet.model.attribution', { attribution: currentModel.license.attribution }) }}</span>
          </template>
          <span v-else-if="currentModel.license.status === 'invalid'">{{ t('pet.model.licenseInvalid') }}</span>
          <span v-else>{{ t('pet.model.licenseMissing') }}</span>
        </div>
      </div>

      <small v-if="syncHint" class="pet-model-manager__warning">{{ syncHint }}</small>

      <details class="pet-model-manager__import">
        <summary>{{ t('pet.model.manualImport') }}</summary>
        <div class="pet-model-manager__import-controls">
          <el-radio-group v-model="localModelType" size="small">
            <el-radio-button value="live2d">Live2D</el-radio-button>
            <el-radio-button value="vrm">VRM</el-radio-button>
          </el-radio-group>
          <div class="pet-model-manager__path-row">
            <el-input v-model="sourcePath" :placeholder="sourcePlaceholder" clearable />
            <el-button :loading="pendingAction === 'model-browse'" :disabled="loading || refreshing" @click="$emit('browse')">{{ t('pet.model.browse') }}</el-button>
            <el-button :loading="pendingAction === 'model-import'" :disabled="loading || refreshing || !sourcePath.trim()" @click="$emit('import-path')">{{ t('pet.model.import') }}</el-button>
          </div>
        </div>
      </details>

      <div v-if="currentModel?.source === 'local'" class="pet-model-manager__danger">
        <el-button type="danger" plain :loading="pendingAction === 'model-delete'" :disabled="loading || refreshing" @click="$emit('delete')">
          <el-icon><Delete /></el-icon>
          {{ t('pet.model.deleteLocal') }}
        </el-button>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { CircleCheck, CircleClose, Delete, FolderOpened, Refresh, Upload } from '@element-plus/icons-vue'
import { computed } from 'vue'
import { useI18n } from '@/i18n'
import type { AvatarCapabilitySnapshot } from '../../../../shared/avatar-command'
import type { PetModelDefinition } from '../../../../shared/pet-control'
import type { PetImportableModelType } from '../../../../shared/resource-manager'

const props = defineProps<{
  models: PetModelDefinition[]
  currentModel: PetModelDefinition | null
  sourceLabel: string
  capabilities: AvatarCapabilitySnapshot | null
  syncHint: string
  sourcePlaceholder: string
  loading: boolean
  refreshing: boolean
  pendingAction: string | null
  optionLabel: (model: PetModelDefinition) => string
}>()

defineEmits<{
  apply: []
  refresh: []
  'import-picker': []
  browse: []
  'import-path': []
  delete: []
}>()

const selectedModelId = defineModel<string | null>('selectedModelId', { required: true })
const localModelType = defineModel<PetImportableModelType>('localModelType', { required: true })
const sourcePath = defineModel<string>('sourcePath', { required: true })
const { t } = useI18n()

const capabilityItems = computed(() => {
  if (!props.capabilities) return []
  return [
    { key: 'expression', label: t('pet.model.capability.expression'), enabled: props.capabilities.actions.expression },
    { key: 'gaze', label: t('pet.model.capability.gaze'), enabled: props.capabilities.actions.gaze },
    { key: 'motion', label: t('pet.model.capability.motion'), enabled: props.capabilities.actions.motion },
    { key: 'viseme', label: t('pet.model.capability.viseme'), enabled: props.capabilities.actions.viseme },
  ]
})
</script>

<style scoped>
.pet-model-manager {
  min-width: 0;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-raised);
  box-shadow: var(--yui-shadow-card);
  overflow: hidden;
}

.pet-model-manager__header {
  display: flex;
  min-height: 58px;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--yui-border);
}

.pet-model-manager__header > div {
  min-width: 0;
}

.pet-model-manager__header h2 {
  margin: 0;
  color: var(--yui-text);
  font-size: 15px;
  line-height: 1.35;
}

.pet-model-manager__header span {
  display: block;
  margin-top: 2px;
  color: var(--yui-muted);
  font-size: 12px;
}

.pet-model-manager__header :deep(.el-button) {
  min-height: 36px;
  border-radius: 7px;
  font-weight: 750;
}

.pet-model-manager__body {
  padding: 14px;
}

.pet-model-manager__selection {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto 38px;
  gap: 8px;
}

.pet-model-manager__selection :deep(.el-button) {
  min-height: 38px;
  margin: 0;
  border-radius: 7px;
}

.pet-model-manager__icon-button {
  width: 38px;
  padding: 0;
}

.full-field {
  width: 100%;
}

.pet-model-manager__summary {
  margin-top: 14px;
  padding-top: 13px;
  border-top: 1px solid var(--yui-border);
}

.pet-model-manager__summary dl {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin: 0;
}

.pet-model-manager__summary dl > div {
  min-width: 0;
  border-radius: 7px;
  background: var(--yui-surface-muted);
  padding: 8px 9px;
}

.pet-model-manager__summary dt {
  color: var(--yui-muted);
  font-size: 11px;
}

.pet-model-manager__summary dd {
  margin: 3px 0 0;
  overflow: hidden;
  color: var(--yui-text);
  font-size: 13px;
  font-weight: 760;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pet-model-manager__capabilities {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.pet-model-manager__capabilities span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: 1px solid var(--yui-border);
  border-radius: 999px;
  color: var(--yui-muted);
  font-size: 11px;
  padding: 4px 8px;
}

.pet-model-manager__capabilities span.supported {
  border-color: color-mix(in srgb, var(--yui-accent) 34%, var(--yui-border));
  background: var(--yui-accent-soft);
  color: var(--yui-accent);
}

.pet-model-manager__license {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 10px;
  margin-top: 10px;
  padding: 9px 10px;
  border-left: 3px solid var(--yui-accent);
  border-radius: 4px;
  background: var(--yui-surface-muted);
  color: var(--yui-muted);
  font-size: 12px;
  overflow-wrap: anywhere;
}

.pet-model-manager__license strong {
  color: var(--yui-text);
}

.pet-model-manager__license--missing,
.pet-model-manager__license--invalid {
  border-left-color: var(--el-color-warning);
}

.pet-model-manager__warning {
  display: block;
  margin-top: 10px;
  color: color-mix(in srgb, var(--el-color-warning) 62%, var(--yui-text));
  font-size: 12px;
  overflow-wrap: anywhere;
}

.pet-model-manager__import {
  margin-top: 14px;
  border-top: 1px solid var(--yui-border);
  padding-top: 11px;
}

.pet-model-manager__import summary {
  display: flex;
  min-height: 40px;
  width: 100%;
  align-items: center;
  color: var(--yui-muted);
  cursor: pointer;
  font-size: 12px;
  font-weight: 700;
  outline: none;
}

.pet-model-manager__import summary:hover {
  color: var(--yui-text);
}

.pet-model-manager__import summary:focus-visible {
  border-radius: 6px;
  box-shadow: 0 0 0 3px var(--yui-accent-soft);
}

.pet-model-manager__import-controls {
  display: grid;
  gap: 10px;
  margin-top: 10px;
}

.pet-model-manager__path-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  gap: 8px;
}

.pet-model-manager__path-row :deep(.el-button) {
  margin: 0;
}

.pet-model-manager__danger {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

.pet-model-manager__empty {
  display: flex;
  min-height: 116px;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--yui-muted);
}

.pet-model-manager__empty strong {
  color: var(--yui-text);
  font-size: 13px;
}

@media (max-width: 640px) {
  .pet-model-manager__header {
    align-items: stretch;
    flex-direction: column;
    gap: 8px;
  }

  .pet-model-manager__header :deep(.el-button) {
    width: 100%;
  }

  .pet-model-manager__selection,
  .pet-model-manager__path-row {
    grid-template-columns: 1fr;
  }

  .pet-model-manager__selection :deep(.el-button),
  .pet-model-manager__path-row :deep(.el-button) {
    width: 100%;
  }

  .pet-model-manager__icon-button {
    width: 100%;
  }

  .pet-model-manager__summary dl {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .pet-model-manager__empty {
    flex-direction: column;
    padding: 16px 0;
    text-align: center;
  }

  .pet-model-manager__empty strong {
    overflow-wrap: anywhere;
  }
}
</style>
