<template>
  <el-card shadow="never">
    <template #header>{{ t('settings.summary.title') }}</template>
    <el-form label-position="top" @submit.prevent>
      <div class="form-grid three">
        <el-form-item :label="t('settings.summary.triggerMessages')">
          <el-input-number :model-value="modelValue.trigger_messages" :min="10" :max="100" controls-position="right" @change="emitField('trigger_messages', $event)" />
        </el-form-item>
        <el-form-item :label="t('settings.summary.keepRecent')">
          <el-input-number :model-value="modelValue.keep_recent_messages" :min="0" :max="50" controls-position="right" @change="emitField('keep_recent_messages', $event)" />
        </el-form-item>
        <el-form-item :label="t('settings.summary.rewriteInterval')">
          <el-input-number :model-value="modelValue.rewrite_interval_messages" :min="5" :max="100" controls-position="right" @change="emitField('rewrite_interval_messages', $event)" />
        </el-form-item>
        <el-form-item :label="t('settings.summary.itemMaxChars')">
          <el-input-number :model-value="modelValue.item_max_chars" :min="100" :max="2000" :step="100" controls-position="right" @change="emitField('item_max_chars', $event)" />
        </el-form-item>
        <el-form-item :label="t('settings.summary.scorer')">
          <el-select :model-value="modelValue.quality_scorer_mode" class="full-width" @change="emitField('quality_scorer_mode', $event)">
            <el-option label="Rule" value="rule" />
            <el-option label="LLM" value="llm" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('settings.summary.budget')">
          <el-input-number :model-value="modelValue.quality_score_budget_per_hour" :min="1" :max="100" controls-position="right" @change="emitField('quality_score_budget_per_hour', $event)" />
        </el-form-item>
        <el-form-item :label="t('settings.summary.cooldown')">
          <el-input-number :model-value="modelValue.quality_score_cooldown_seconds" :min="0" :max="3600" :step="60" controls-position="right" @change="emitField('quality_score_cooldown_seconds', $event)" />
        </el-form-item>
      </div>
    </el-form>
  </el-card>
</template>

<script setup lang="ts">
import { t } from '@/i18n'

export type SummarySettings = {
  trigger_messages: number
  keep_recent_messages: number
  item_max_chars: number
  rewrite_interval_messages: number
  quality_scorer_mode: 'rule' | 'llm'
  quality_score_budget_per_hour: number
  quality_score_cooldown_seconds: number
}

defineProps<{ modelValue: SummarySettings }>()

const emit = defineEmits<{
  'update-field': [field: keyof SummarySettings, value: number | string]
}>()

const emitField = (field: keyof SummarySettings, value: unknown) => {
  if (typeof value === 'string' || (typeof value === 'number' && Number.isFinite(value))) {
    emit('update-field', field, value)
  }
}
</script>

<style scoped>
.form-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px 16px;
}

.full-width {
  width: 100%;
}

@media (max-width: 960px) {
  .form-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
