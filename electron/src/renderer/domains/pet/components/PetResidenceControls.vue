<template>
  <section class="pet-residence" :class="{ 'is-adjusting': state.interactMode }" aria-labelledby="pet-residence-title">
    <header class="pet-residence__header">
      <div>
        <h2 id="pet-residence-title">{{ t('pet.residence.title') }}</h2>
        <span>{{ displayLabel }}</span>
      </div>
      <span class="pet-residence__state" :class="{ active: state.interactMode }">
        <i aria-hidden="true"></i>
        {{ state.interactMode ? t('pet.residence.adjusting') : t('pet.residence.resident') }}
      </span>
    </header>

    <div class="pet-residence__actions">
      <el-button
        class="pet-residence__primary"
        type="primary"
        :loading="pendingAction === 'adjustment'"
        :disabled="loading || !state.ready || state.interactMode"
        @click="$emit('begin-adjustment')"
      >
        <el-icon><FullScreen /></el-icon>
        {{ state.interactMode ? t('pet.residence.adjusting') : t('pet.residence.fullscreenAdjust') }}
      </el-button>
      <el-button :loading="pendingAction === 'restore'" :disabled="loading || state.interactMode" @click="$emit('restore-resident')">
        <el-icon><Aim /></el-icon>
        {{ t('pet.residence.restore') }}
      </el-button>
    </div>

    <div class="pet-residence__settings">
      <div class="pet-residence__row">
        <span class="pet-residence__icon" aria-hidden="true"><el-icon><Pointer /></el-icon></span>
        <div class="pet-residence__copy">
          <strong>{{ t('pet.residence.clickThrough') }}</strong>
          <span>{{ state.clickThrough ? t('common.enabled') : t('common.disabled') }}</span>
        </div>
        <el-switch
          :model-value="state.clickThrough"
          :disabled="loading || state.interactMode"
          :aria-label="t('pet.residence.clickThrough')"
          @change="emitBoolean('update-click-through', $event)"
        />
      </div>

      <div class="pet-residence__row">
        <span class="pet-residence__icon" aria-hidden="true"><el-icon><Lock /></el-icon></span>
        <div class="pet-residence__copy">
          <strong>{{ t('pet.residence.lockPosition') }}</strong>
          <span>{{ state.locked ? t('pet.residence.locked') : t('pet.residence.unlocked') }}</span>
        </div>
        <el-switch
          :model-value="state.locked"
          :disabled="loading || state.interactMode"
          :aria-label="t('pet.residence.lockPosition')"
          @change="emitBoolean('update-locked', $event)"
        />
      </div>

      <div class="pet-residence__row">
        <span class="pet-residence__icon" aria-hidden="true"><el-icon><MuteNotification /></el-icon></span>
        <div class="pet-residence__copy">
          <strong>{{ t('pet.residence.dnd') }}</strong>
          <span>{{ state.doNotDisturb ? t('common.enabled') : t('common.disabled') }}</span>
        </div>
        <el-switch
          :model-value="state.doNotDisturb"
          :disabled="loading"
          :aria-label="t('pet.residence.dnd')"
          @change="emitBoolean('update-dnd', $event)"
        />
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { Aim, FullScreen, Lock, MuteNotification, Pointer } from '@element-plus/icons-vue'
import { useI18n } from '@/i18n'
import type { PetControlState } from '../../../../shared/pet-control'

defineProps<{
  state: PetControlState
  displayLabel: string
  loading: boolean
  pendingAction: string | null
}>()

const emit = defineEmits<{
  'begin-adjustment': []
  'restore-resident': []
  'update-click-through': [enabled: boolean]
  'update-locked': [enabled: boolean]
  'update-dnd': [enabled: boolean]
}>()

const { t } = useI18n()

const emitBoolean = (
  event: 'update-click-through' | 'update-locked' | 'update-dnd',
  value: string | number | boolean,
) => emit(event, Boolean(value))
</script>

<style scoped>
.pet-residence {
  min-width: 0;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-raised);
  box-shadow: var(--yui-shadow-card);
  overflow: hidden;
  transition: border-color 180ms ease, box-shadow 180ms ease;
}

.pet-residence.is-adjusting {
  border-color: color-mix(in srgb, var(--yui-accent) 48%, var(--yui-border));
  box-shadow: 0 0 0 3px var(--yui-accent-soft), var(--yui-shadow-card);
}

.pet-residence__header {
  display: flex;
  min-height: 58px;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 11px 14px;
  border-bottom: 1px solid var(--yui-border);
}

.pet-residence__header > div {
  min-width: 0;
}

.pet-residence__header h2 {
  margin: 0;
  color: var(--yui-text);
  font-size: 15px;
  line-height: 1.35;
}

.pet-residence__header > div > span {
  display: block;
  margin-top: 2px;
  overflow: hidden;
  color: var(--yui-muted);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pet-residence__state {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 7px;
  border: 1px solid var(--yui-border);
  border-radius: 999px;
  background: var(--yui-surface-muted);
  color: var(--yui-muted);
  font-size: 12px;
  font-weight: 700;
  padding: 5px 9px;
}

.pet-residence__state i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
}

.pet-residence__state.active {
  border-color: color-mix(in srgb, var(--yui-accent) 38%, var(--yui-border));
  background: var(--yui-accent-soft);
  color: var(--yui-accent);
}

.pet-residence__actions {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  padding: 14px;
  border-bottom: 1px solid var(--yui-border);
}

.pet-residence__actions :deep(.el-button) {
  min-height: 40px;
  margin: 0;
  border-radius: 7px;
  font-weight: 750;
}

.pet-residence__primary {
  width: 100%;
}

.pet-residence__settings {
  padding: 0 14px;
}

.pet-residence__row {
  display: grid;
  grid-template-columns: 32px minmax(0, 1fr) auto;
  min-height: 62px;
  align-items: center;
  gap: 10px;
  border-bottom: 1px solid var(--yui-border);
}

.pet-residence__row:last-child {
  border-bottom: 0;
}

.pet-residence__icon {
  display: inline-flex;
  width: 30px;
  height: 30px;
  align-items: center;
  justify-content: center;
  border-radius: 7px;
  background: var(--yui-surface-muted);
  color: var(--yui-muted);
}

.pet-residence__copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.pet-residence__copy strong {
  color: var(--yui-text);
  font-size: 13px;
}

.pet-residence__copy span {
  color: var(--yui-muted);
  font-size: 11px;
}

.pet-residence__row :deep(.el-switch) {
  flex: 0 0 auto;
}

@media (max-width: 560px) {
  .pet-residence__header {
    align-items: flex-start;
    flex-direction: column;
    gap: 8px;
  }

  .pet-residence__header > div > span {
    overflow-wrap: anywhere;
    white-space: normal;
  }

  .pet-residence__actions {
    grid-template-columns: 1fr;
  }

  .pet-residence__actions :deep(.el-button) {
    width: 100%;
  }
}

@media (prefers-reduced-motion: reduce) {
  .pet-residence {
    transition: none;
  }
}
</style>
