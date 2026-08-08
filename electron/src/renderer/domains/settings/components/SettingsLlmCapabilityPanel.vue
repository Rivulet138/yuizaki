<template>
  <div v-if="model.trim()" class="model-capability-panel">
    <div class="model-capability-head">
      <strong>模型能力</strong>
      <span>
        {{ capabilitySourceLabel }}
        <a
          v-if="capabilities.metadata"
          :href="capabilities.metadata.documentationUrl"
          target="_blank"
          rel="noreferrer"
        >来源</a>
      </span>
    </div>
    <div class="model-capability-strip">
      <el-tag :type="latencyTagType" size="small">{{ latencyLabel }}</el-tag>
      <el-tag
        v-for="item in capabilityRows"
        :key="item.key"
        :type="capabilityTagType(item.support)"
        size="small"
      >
        {{ item.label }} · {{ capabilitySupportLabel(item.support) }}
      </el-tag>
    </div>
    <div v-if="capabilities.metadata" class="model-metadata-grid">
      <div v-for="item in metadataRows" :key="item.label">
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
      </div>
    </div>
    <p v-if="pricingLabel" class="model-pricing-note">{{ pricingLabel }}</p>
    <el-alert
      v-for="warning in configurationWarnings"
      :key="warning"
      class="model-capability-warning"
      type="warning"
      :closable="false"
      :title="warning"
    />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { inferModelCapabilities, type ModelCapabilitySupport } from '@/../shared/model-capabilities'
import type { LlmProviderPreset } from '../llmProviders'

type TagType = 'success' | 'warning' | 'info' | 'danger'

const props = defineProps<{
  provider: LlmProviderPreset
  model: string
  contextMaxTokens: number
  maxOutputTokens: number
  visionEnabled: boolean
}>()

const capabilities = computed(() => inferModelCapabilities(props.provider, props.model))
const formatTokenLimit = (value: number | null) => value === null ? '未知' : value.toLocaleString('en-US')
const lifecycleLabel = computed(() => ({
  stable: '稳定',
  preview: '预览',
  deprecated: '即将停用',
  legacy: '旧版',
  unknown: '未知',
}[capabilities.value.metadata?.lifecycle || 'unknown']))
const capabilitySourceLabel = computed(() => {
  const metadata = capabilities.value.metadata
  if (capabilities.value.source === 'registry' && metadata) return `官方资料登记 · 核验 ${metadata.verifiedAt}`
  if (capabilities.value.source === 'model-pattern') return '根据模型名推断，请以提供商文档为准'
  return '未识别，请以服务端文档为准'
})
const metadataRows = computed(() => {
  const metadata = capabilities.value.metadata
  if (!metadata) return []
  return [
    { label: '上下文窗口', value: `${formatTokenLimit(metadata.contextWindowTokens)} tokens` },
    { label: '最大输出', value: `${formatTokenLimit(metadata.maxOutputTokens)} tokens` },
    { label: '生命周期', value: lifecycleLabel.value },
    { label: '规范模型', value: metadata.canonicalModel },
  ]
})
const pricingLabel = computed(() => {
  const pricing = capabilities.value.metadata?.pricing
  if (!pricing) return ''
  const cached = pricing.cachedInputPerMillionUsd === undefined ? '' : `，缓存命中输入 $${pricing.cachedInputPerMillionUsd}`
  const note = pricing.note ? `；${pricing.note}` : ''
  return `参考价（每 100 万 tokens）：输入 $${pricing.inputPerMillionUsd}，输出 $${pricing.outputPerMillionUsd}${cached}${note}`
})
const configurationWarnings = computed(() => {
  const metadata = capabilities.value.metadata
  if (!metadata) return []
  const warnings: string[] = []
  if (metadata.lifecycle === 'deprecated') {
    const date = metadata.deprecationAt ? new Date(metadata.deprecationAt).toLocaleString() : '提供商公布的停用时间'
    warnings.push(`当前模型别名将于 ${date} 停用，建议切换到 ${metadata.canonicalModel}。`)
  }
  if (metadata.contextWindowTokens !== null && props.contextMaxTokens > metadata.contextWindowTokens) {
    warnings.push(`当前上下文配置 ${formatTokenLimit(props.contextMaxTokens)} 超过登记上限 ${formatTokenLimit(metadata.contextWindowTokens)}。`)
  }
  if (metadata.maxOutputTokens !== null && props.maxOutputTokens > metadata.maxOutputTokens) {
    warnings.push(`当前最大输出 ${formatTokenLimit(props.maxOutputTokens)} 超过登记上限 ${formatTokenLimit(metadata.maxOutputTokens)}。`)
  }
  if (capabilities.value.vision === false && !props.visionEnabled) {
    warnings.push('当前文本模型不支持视觉；启用实时屏幕观察前，请配置独立视觉模型。')
  }
  return warnings
})
const capabilityRows = computed(() => [
  { key: 'vision', label: '视觉', support: capabilities.value.vision },
  { key: 'tools', label: '工具', support: capabilities.value.tools },
  { key: 'structuredOutput', label: '结构化输出', support: capabilities.value.structuredOutput },
  { key: 'realtimeAudio', label: '实时音频', support: capabilities.value.realtimeAudio },
  { key: 'computerUse', label: '电脑操作', support: capabilities.value.computerUse },
])
const capabilitySupportLabel = (support: ModelCapabilitySupport) => support === true ? '支持' : support === false ? '不支持' : '未知'
const capabilityTagType = (support: ModelCapabilitySupport): TagType => support === true ? 'success' : support === false ? 'info' : 'warning'
const latencyLabel = computed(() => ({
  realtime: '延迟 · 实时',
  fast: '延迟 · 快',
  balanced: '延迟 · 均衡',
  deliberate: '延迟 · 深度',
  unknown: '延迟 · 未知',
}[capabilities.value.latency]))
const latencyTagType = computed<TagType>(() => ['realtime', 'fast'].includes(capabilities.value.latency)
  ? 'success'
  : capabilities.value.latency === 'unknown'
    ? 'warning'
    : 'info')
</script>

<style scoped src="./SettingsLlmCapabilityPanel.css"></style>
