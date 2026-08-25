<template>
  <el-card shadow="never" data-testid="product-metrics-consent-section">
    <template #header>
      <SettingsSectionHeader :title="t('settings.productMetrics.title')">
        <template #status>
          <el-tag size="small" type="info" effect="plain">{{ t('settings.productMetrics.scope') }}</el-tag>
          <el-tag size="small" type="warning" effect="plain">{{ t('settings.productMetrics.transport') }}</el-tag>
        </template>
      </SettingsSectionHeader>
    </template>

    <div class="product-metrics-consent">
      <div class="consent-copy">
        <strong>{{ t('settings.productMetrics.consent') }}</strong>
        <p>{{ t('settings.productMetrics.description') }}</p>
      </div>
      <el-switch
        data-testid="product-metrics-consent"
        :model-value="consented"
        :loading="loading || saving"
        :disabled="loading || saving"
        :aria-label="t('settings.productMetrics.consent')"
        @change="handleChange"
      />
    </div>
    <el-alert
      v-if="error"
      class="consent-status"
      :title="error"
      type="error"
      show-icon
      :closable="false"
    />
    <p v-else class="consent-status" role="status">{{ statusLabel }}</p>
  </el-card>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { t } from '@/i18n'
import { systemClient } from '@/api/clients/system-client'
import SettingsSectionHeader from './SettingsSectionHeader.vue'

type ConsentSnapshot = {
  consented: boolean
  scope: string
  transport: string
}

const consented = ref(false)
const scope = ref('local_product_metrics')
const transport = ref('not_configured')
const loading = ref(true)
const saving = ref(false)
const error = ref<string | null>(null)

const statusLabel = computed(() => {
  if (loading.value) return t('settings.productMetrics.loading')
  if (saving.value) return t('settings.productMetrics.saving')
  return t('settings.productMetrics.ready')
})

const applySnapshot = (snapshot: ConsentSnapshot) => {
  consented.value = snapshot.consented
  scope.value = snapshot.scope
  transport.value = snapshot.transport
}

const load = async () => {
  loading.value = true
  error.value = null
  try {
    applySnapshot(await systemClient.productMetricsConsent())
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : t('common.error.unknown')
    consented.value = false
  } finally {
    loading.value = false
  }
}

const handleChange = async (nextValue: string | number | boolean) => {
  if (typeof nextValue !== 'boolean' || saving.value) return
  const previous = consented.value
  consented.value = nextValue
  saving.value = true
  error.value = null
  try {
    applySnapshot(await systemClient.patchProductMetricsConsent(nextValue))
  } catch (err: unknown) {
    consented.value = previous
    error.value = err instanceof Error ? err.message : t('settings.productMetrics.failed')
  } finally {
    saving.value = false
  }
}

onMounted(load)

defineExpose({ consented, scope, transport, load, handleChange })
</script>

<style scoped>
.product-metrics-consent {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.consent-copy {
  min-width: 0;
}

.consent-copy strong {
  display: block;
  color: var(--yui-text-primary);
}

.consent-copy p,
.consent-status {
  margin: 6px 0 0;
  color: var(--yui-text-secondary);
  font-size: 12px;
  line-height: 1.5;
}

.consent-status {
  min-height: 18px;
}

.consent-status :deep(.el-alert__title) {
  font-size: 12px;
}

@media (max-width: 600px) {
  .product-metrics-consent {
    align-items: center;
  }
}
</style>
