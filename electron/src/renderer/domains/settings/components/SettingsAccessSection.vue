<template>
  <el-card class="settings-access-card" shadow="never">
    <div class="access-row backend-token-row">
        <div>
          <strong>{{ t('settings.backendToken.title') }}</strong>
          <div v-if="backendTokenStatusKnown" class="access-token-details">
            <el-tag size="small" type="info">{{ t('settings.backendToken.source') }} · {{ backendTokenSourceLabel }}</el-tag>
            <el-tag v-if="backendTokenPreview" size="small" type="info">{{ t('settings.backendToken.preview') }} · {{ backendTokenPreview }}</el-tag>
            <el-tag v-if="backendTokenRequiresRestart" size="small" type="warning">{{ t('settings.backendToken.restartRequired') }}</el-tag>
          </div>
        </div>
        <div class="access-controls">
          <el-input
            class="backend-token-input"
            :model-value="backendToken"
            type="password"
            show-password
            :placeholder="t('settings.backendToken.placeholder')"
            @update:model-value="$emit('update:backendToken', String($event))"
            @keyup.enter="$emit('save-backend-token')"
          />
          <el-button type="primary" plain :loading="backendTokenBusy" @click="$emit('save-backend-token')">
            {{ t('settings.backendToken.save') }}
          </el-button>
          <el-button data-testid="reset-backend-token" plain :loading="backendTokenBusy" @click="$emit('reset-backend-token')">
            {{ t('settings.backendToken.reset') }}
          </el-button>
          <el-tag :type="backendTokenRequiresRestart ? 'warning' : backendTokenConfigured ? 'success' : 'info'">
            {{ backendTokenRequiresRestart ? t('settings.backendToken.restartRequired') : backendTokenConfigured ? t('settings.backendToken.tokenSet') : t('settings.backendToken.tokenNotSet') }}
          </el-tag>
        </div>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { t } from '@/i18n'

defineProps<{
  backendToken: string
  backendTokenConfigured: boolean
  backendTokenBusy: boolean
  backendTokenStatusKnown: boolean
  backendTokenSourceLabel: string
  backendTokenPreview: string
  backendTokenRequiresRestart: boolean
}>()

defineEmits<{
  'update:backendToken': [value: string]
  'save-backend-token': []
  'reset-backend-token': []
}>()
</script>

<style scoped>
.settings-access-card { border-color: var(--yui-border); background: var(--yui-surface); }
.settings-access-card :deep(.el-card__body) { padding: 12px 14px; }
.access-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-width: 0; }
.access-row strong { color: var(--yui-text); font-size: 14px; }
.access-token-details { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.access-controls { display: flex; align-items: center; justify-content: flex-end; gap: 7px; min-width: min(560px, 100%); flex-wrap: wrap; }
.backend-token-input { max-width: 300px; }
@media (max-width: 960px) {
  .access-row,
  .access-controls { align-items: stretch; flex-direction: column; }
  .access-controls,
  .backend-token-input { width: 100%; max-width: none; }
}
</style>
