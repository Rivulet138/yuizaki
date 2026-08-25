<template>
  <section class="memory-section quick-capture" aria-labelledby="memory-quick-capture-title">
    <div class="section-heading">
      <div>
        <h3 id="memory-quick-capture-title">快速记忆</h3>
        <p>新增一条可被检索的记忆文档。</p>
      </div>
      <el-tag size="small" type="info">{{ selectedLayerDescription }}</el-tag>
    </div>
    <el-form class="capture-form" label-position="top" @submit.prevent="emit('submit')">
      <el-form-item label="记忆内容" class="capture-text">
        <el-input id="memory-capture-text" :model-value="form.text" aria-describedby="memory-capture-hint" type="textarea" :rows="3" resize="none" placeholder="例如：我喜欢被叫溪羽；周五提醒我检查模型。" @update:model-value="updateForm('text', String($event))" />
        <p id="memory-capture-hint" class="field-hint">保存后会按当前范围和层级参与召回。</p>
      </el-form-item>
      <div class="capture-options">
        <el-form-item label="记忆层级">
          <el-select :model-value="form.layer" class="full-width" @update:model-value="updateForm('layer', String($event))">
            <el-option v-for="layer in layers" :key="layer.value" :label="layer.label" :value="layer.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="记忆类型">
          <el-select :model-value="form.type" data-testid="memory-type-select" class="full-width" filterable allow-create default-first-option placeholder="选择或输入类型" @update:model-value="updateForm('type', String($event))">
            <el-option v-for="option in typeOptions" :key="option.value" :label="option.label" :value="option.value" />
          </el-select>
        </el-form-item>
      </div>
      <details class="capture-details">
        <summary>高级字段</summary>
        <div class="capture-options detail-fields">
          <el-form-item :label="`重要度：${form.importance.toFixed(2)}`"><el-slider :model-value="form.importance" :min="0" :max="1" :step="0.05" @update:model-value="updateForm('importance', Number($event))" /></el-form-item>
          <el-form-item :label="`置信度：${form.confidence.toFixed(2)}`"><el-slider :model-value="form.confidence" :min="0" :max="1" :step="0.05" @update:model-value="updateForm('confidence', Number($event))" /></el-form-item>
          <el-form-item label="来源">
            <el-select :model-value="form.source" class="full-width" @update:model-value="updateForm('source', String($event))"><el-option v-for="option in sourceOptions" :key="option.value" :label="option.label" :value="option.value" /></el-select>
          </el-form-item>
        </div>
      </details>
      <div class="capture-actions">
        <span role="status" aria-live="polite" :class="{ 'duplicate-hint': duplicateCandidates.length }">{{ duplicateCandidates.length ? `发现 ${duplicateCandidates.length} 条相似记忆，请确认是否重复` : '保存位置：本机' }}</span>
        <el-button type="primary" native-type="submit" :loading="loading" :disabled="!form.text.trim()">保存记忆</el-button>
      </div>
    </el-form>
    <div v-if="duplicateCandidates.length" class="duplicate-list" aria-label="相似记忆">
      <article v-for="candidate in duplicateCandidates" :key="candidate.id">
        <strong>{{ candidate.text }}</strong>
        <span>{{ candidate.layer || '未分类' }}<template v-if="candidate.match_reason"> · {{ candidate.match_reason }}</template></span>
      </article>
    </div>
  </section>
</template>

<script setup lang="ts">
import type { MemoryCaptureForm, MemoryDuplicateCandidate, MemoryLayer, MemoryOption } from './memory-panel-types'

defineProps<{
  form: MemoryCaptureForm
  layers: MemoryLayer[]
  typeOptions: MemoryOption[]
  sourceOptions: MemoryOption[]
  selectedLayerDescription: string
  duplicateCandidates: MemoryDuplicateCandidate[]
  loading: boolean
}>()

const emit = defineEmits<{ submit: []; 'update-form': [value: Partial<MemoryCaptureForm>] }>()
const updateForm = <K extends keyof MemoryCaptureForm>(key: K, value: MemoryCaptureForm[K]) => emit('update-form', { [key]: value })
</script>

<style scoped>
.memory-section { padding: 16px 18px 18px; border: 1px solid var(--yui-border); border-radius: var(--yui-radius-card); background: var(--yui-surface); }
.section-heading, .capture-actions { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
h3 { margin: 0; color: var(--yui-text); font-size: 15px; }
p { margin: 4px 0 0; color: var(--yui-muted); font-size: 12px; }
.field-hint { margin-top: 6px; font-size: 11px; line-height: 1.45; }
.capture-form { margin-top: 14px; }
.capture-options { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.detail-fields { grid-template-columns: repeat(3, minmax(0, 1fr)); margin-top: 12px; }
.full-width { width: 100%; }
.capture-details summary { color: var(--yui-muted); cursor: pointer; font-size: 12px; }
.capture-actions { align-items: center; margin-top: 12px; }
.capture-actions span { color: var(--yui-muted); font-size: 12px; line-height: 1.4; }
.capture-actions span.duplicate-hint { color: var(--yui-warning-text, #a16207); }
.duplicate-list { display: grid; gap: 8px; margin-top: 12px; }
.duplicate-list article { display: flex; flex-direction: column; gap: 4px; padding: 10px 12px; border: 1px solid var(--yui-border); border-radius: var(--yui-radius-card); background: var(--yui-surface-muted); }
.duplicate-list strong { color: var(--yui-text); font-size: 13px; font-weight: 600; }
.duplicate-list span { color: var(--yui-muted); font-size: 11px; }
@media (max-width: 760px) { .capture-options, .detail-fields { grid-template-columns: 1fr; } .section-heading { align-items: flex-start; } .capture-actions { align-items: stretch; flex-direction: column; } .capture-actions :deep(.el-button) { width: 100%; } }
</style>
