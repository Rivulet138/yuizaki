<template>
  <section class="model-setup" aria-labelledby="onboarding-model-title">
    <div class="section-heading">
      <div>
        <h2 id="onboarding-model-title">{{ t('onboarding.model.title') }}</h2>
        <p>{{ t('onboarding.model.description') }}</p>
      </div>
      <span v-if="tested" class="tested-status" role="status">
        <el-icon><CircleCheckFilled /></el-icon>{{ t('onboarding.model.testPassed') }}
      </span>
    </div>

    <el-form label-position="top" @submit.prevent="saveAndTest">
      <div class="model-fields">
        <el-form-item :label="t('onboarding.model.provider')">
          <el-select v-model="draft.provider" :disabled="busy" @change="applyProvider">
            <el-option v-for="option in providers" :key="option.value" :label="option.label" :value="option.value" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('onboarding.model.model')">
          <el-input v-model="draft.model" :disabled="busy" autocomplete="off" :placeholder="t('onboarding.model.modelPlaceholder')" />
        </el-form-item>
        <el-form-item class="wide-field" :label="t('onboarding.model.endpoint')">
          <el-input v-model="draft.baseUrl" :disabled="busy" autocomplete="url" placeholder="https://api.example.com/v1" />
        </el-form-item>
        <el-form-item class="wide-field" :label="t('onboarding.model.apiKey')">
          <el-input v-model="draft.apiKey" :disabled="busy" type="password" show-password autocomplete="new-password" :placeholder="t('onboarding.model.apiKeyPlaceholder')" />
        </el-form-item>
      </div>
      <p v-if="error" class="model-error" role="alert">{{ error }}</p>
      <div class="model-actions">
        <el-button native-type="submit" type="primary" :loading="busy" :disabled="!canSubmit">
          <el-icon><Connection /></el-icon>{{ t('onboarding.model.saveAndTest') }}
        </el-button>
      </div>
    </el-form>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { CircleCheckFilled, Connection } from '@element-plus/icons-vue'
import { settingsClient } from '@/api/clients/settings-client'
import { t } from '@/i18n'
import { useSettingsStore } from '@/state/settingsStore'
import { LLM_PROVIDER_BASE_URLS, getLlmProviderOptions, type LlmProviderPreset } from '@/domains/settings/llmProviders'

const emit = defineEmits<{ completed: [] }>()
const settingsStore = useSettingsStore()
const busy = ref(false)
const tested = ref(false)
const error = ref('')
const draft = reactive({ provider: 'custom' as LlmProviderPreset, baseUrl: '', apiKey: '', model: '' })
const providers = computed(() => getLlmProviderOptions(t('common.custom')))
const canSubmit = computed(() => Boolean(draft.baseUrl.trim() && draft.model.trim()))

const syncDraft = (): void => {
  draft.provider = providers.value.some(item => item.value === settingsStore.state.llm.provider)
    ? settingsStore.state.llm.provider as LlmProviderPreset
    : 'custom'
  draft.baseUrl = settingsStore.state.llm.base_url
  draft.apiKey = settingsStore.state.llm.api_key
  draft.model = settingsStore.state.llm.model
}

const applyProvider = (value: string | number | boolean): void => {
  const provider = String(value) as LlmProviderPreset
  draft.provider = provider
  if (provider !== 'custom') draft.baseUrl = LLM_PROVIDER_BASE_URLS[provider]
  tested.value = false
}

const saveAndTest = async (): Promise<void> => {
  if (!canSubmit.value || busy.value) return
  busy.value = true
  error.value = ''
  tested.value = false
  try {
    await settingsStore.saveSettings({
      llm: {
        ...settingsStore.state.llm,
        provider: draft.provider,
        base_url: draft.baseUrl.trim(),
        api_key: draft.apiKey.trim(),
        model: draft.model.trim(),
      },
    })
    const result = await settingsClient.testLlm()
    if (!(result.ok || result.status === 'ok')) throw new Error(result.message || t('onboarding.model.testFailed'))
    tested.value = true
    emit('completed')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : t('onboarding.model.testFailed')
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  if (!settingsStore.state.loading) await settingsStore.fetchSettings()
  syncDraft()
})
</script>

<style scoped>
.model-setup {
  padding-top: 20px;
  border-top: 1px solid var(--yui-border, #d9e1ea);
}

.section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.section-heading h2 { margin: 0; color: var(--yui-text, #172033); font-size: 16px; line-height: 1.35; }
.section-heading p { max-width: 65ch; margin: 4px 0 0; color: var(--yui-text-muted, #526176); font-size: 13px; line-height: 1.5; }
.tested-status { display: inline-flex; align-items: center; gap: 5px; color: #15803d; font-size: 12px; white-space: nowrap; }

.model-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 16px; }
.wide-field { grid-column: 1 / -1; }
.model-actions { display: flex; justify-content: flex-end; }
.model-error { margin: 0 0 12px; overflow-wrap: anywhere; color: #b91c1c; font-size: 13px; }

@media (max-width: 520px) {
  .section-heading { flex-direction: column; }
  .model-fields { grid-template-columns: minmax(0, 1fr); }
  .wide-field { grid-column: auto; }
  .model-actions :deep(.el-button) { width: 100%; }
}
</style>
