<template>
  <el-card shadow="never">
    <template #header>
      <div class="summary-header">
        <div>
          <strong>{{ t('settings.summary.title') }}</strong>
        </div>
        <el-tag type="success">{{ t('settings.summary.automatic') }}</el-tag>
      </div>
    </template>

    <details class="summary-advanced">
      <summary>{{ t('settings.summary.advancedTitle') }}</summary>
      <el-form label-position="top" @submit.prevent>
        <section class="summary-settings-group">
          <h3>{{ t('settings.summary.compressionTitle') }}</h3>
          <div class="form-grid three">
            <el-form-item :label="t('settings.summary.triggerMessages')">
              <el-input-number :model-value="modelValue.trigger_messages" :min="1" :max="100" controls-position="right" @change="emitField('trigger_messages', $event)" />
            </el-form-item>
            <el-form-item :label="t('settings.summary.keepRecent')">
              <el-input-number :model-value="modelValue.keep_recent_messages" :min="1" :max="50" controls-position="right" @change="emitField('keep_recent_messages', $event)" />
            </el-form-item>
            <el-form-item :label="t('settings.summary.itemMaxChars')">
              <el-input-number :model-value="modelValue.item_max_chars" :min="20" :max="2000" :step="20" controls-position="right" @change="emitField('item_max_chars', $event)" />
            </el-form-item>
          </div>
        </section>

        <section class="summary-settings-group">
          <h3>{{ t('settings.summary.rewriteTitle') }}</h3>
          <div class="form-grid three">
            <el-form-item :label="t('settings.summary.rewriteInterval')">
              <el-input-number :model-value="modelValue.rewrite_interval_messages" :min="1" :max="100" controls-position="right" @change="emitField('rewrite_interval_messages', $event)" />
            </el-form-item>
            <el-form-item :label="t('settings.summary.scorer')">
              <el-select :model-value="modelValue.quality_scorer_mode" class="full-width" @change="emitField('quality_scorer_mode', $event)">
                <el-option :label="t('settings.summary.scorerRule')" value="rule" />
                <el-option :label="t('settings.summary.scorerLlm')" value="llm" />
              </el-select>
            </el-form-item>
          </div>
        </section>

        <section v-if="modelValue.quality_scorer_mode === 'llm'" class="summary-settings-group">
          <h3>{{ t('settings.summary.guardTitle') }}</h3>
          <div class="form-grid three">
            <el-form-item :label="t('settings.summary.budget')">
              <el-input-number :model-value="modelValue.quality_score_budget_per_hour" :min="1" :max="100" controls-position="right" @change="emitField('quality_score_budget_per_hour', $event)" />
            </el-form-item>
            <el-form-item :label="t('settings.summary.cooldown')">
              <el-input-number :model-value="modelValue.quality_score_cooldown_seconds" :min="1" :max="3600" :step="60" controls-position="right" @change="emitField('quality_score_cooldown_seconds', $event)" />
            </el-form-item>
          </div>
        </section>
      </el-form>
    </details>
  </el-card>
</template>

<script setup lang="ts">
import { ElOption, ElSelect } from 'element-plus'
import 'element-plus/es/components/select/style/css'
import 'element-plus/es/components/option/style/css'
import { ElInputNumber } from 'element-plus'
import 'element-plus/es/components/input-number/style/css'
import { ElCard, ElForm, ElFormItem } from 'element-plus'
import 'element-plus/es/components/card/style/css'
import 'element-plus/es/components/form/style/css'
import 'element-plus/es/components/form-item/style/css'
import { ElTag } from 'element-plus'
import 'element-plus/es/components/tag/style/css'
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
.form-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px 16px; }
.summary-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.summary-header strong { color: var(--yui-text); }
.summary-advanced { border-top: 1px solid var(--yui-border); padding-top: 12px; }
.summary-advanced summary { color: var(--yui-text); cursor: pointer; font-size: 13px; font-weight: 650; }
.summary-advanced .form-grid { margin-top: 14px; }
.summary-settings-group + .summary-settings-group { margin-top: 16px; padding-top: 14px; border-top: 1px solid var(--yui-border); }
.summary-settings-group h3 { margin: 0; color: var(--yui-text); font-size: 13px; }
.summary-settings-group :deep(.el-form-item) { margin-bottom: 4px; }
.full-width { width: 100%; }
@media (max-width: 960px) { .form-grid { grid-template-columns: minmax(0, 1fr); } }
</style>
