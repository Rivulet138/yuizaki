<template>
  <PanelShell :title="t('i18n.title')" tone="admin">
    <div class="i18n-panel">
      <el-card shadow="never">
        <template #header>
          <div class="card-header">
            <strong>{{ t('i18n.frontendTitle') }}</strong>
          </div>
        </template>
        <div class="language-row">
          <el-select v-model="selectedFrontendLocale" :placeholder="t('language.select')" class="locale-select">
            <el-option v-for="localeOption in supportedLocales" :key="localeOption" :label="localeLabel(localeOption)" :value="localeOption" />
          </el-select>
          <el-button type="primary" :loading="syncingLocale" :disabled="syncingLocale || !selectedFrontendLocale" @click="applyAppLocale">{{ t('i18n.syncAppLanguage') }}</el-button>
          <el-tag>{{ localeLabel(locale) }} · {{ locale }}</el-tag>
          <el-tag v-if="currentLocale" type="info">{{ t('i18n.currentBackend') }}: {{ currentLocale }}</el-tag>
        </div>
      </el-card>

      <el-card shadow="never">
        <template #header>
          <div class="card-header">
            <strong>{{ t('i18n.backend.title') }}</strong>
            <el-button type="primary" :loading="loading" :disabled="loading" @click="loadAll">{{ t('i18n.refresh') }}</el-button>
          </div>
        </template>
        <div class="language-row">
          <el-select v-model="selectedLocale" :placeholder="t('language.select')" class="locale-select">
            <el-option v-for="localeOption in locales" :key="localeOption" :label="backendLocaleLabel(localeOption)" :value="localeOption" />
          </el-select>
          <el-button type="primary" :loading="applyingBackendLocale" :disabled="applyingBackendLocale || !selectedLocale" @click="applyBackendLocale">{{ t('i18n.backendOnly') }}</el-button>
          <el-tag>{{ currentLocale || t('i18n.unknown') }}</el-tag>
        </div>
        <el-alert v-if="loadError" :title="loadError" type="warning" show-icon :closable="false" />
      </el-card>

      <el-card shadow="never">
        <template #header>
          <div class="card-header">
            <strong>{{ t('i18n.messages.title') }}</strong>
            <el-input v-model="messageKey" placeholder="common.save / errors.networkError" clearable class="key-input" />
          </div>
        </template>
        <div class="button-row">
          <el-button plain @click="lookupMessage">{{ t('i18n.lookup.message') }}</el-button>
          <el-button plain @click="lookupError">{{ t('i18n.lookup.error') }}</el-button>
        </div>
        <el-alert v-if="lastLookup" :title="lastLookup" type="info" show-icon :closable="false" />
        <pre class="messages-preview">{{ messagesPreview }}</pre>
      </el-card>
    </div>
  </PanelShell>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { setLocale as setFrontendLocale, useI18n } from '@/i18n'
import PanelShell from '@/shared/components/panel/PanelShell.vue'
import { i18nClient } from '@/api/client'

const loading = ref(false)
const locales = ref<string[]>([])
const localeNames = ref<Record<string, string>>({})
const currentLocale = ref('')
const selectedLocale = ref('')
const messages = ref<Record<string, unknown>>({})
const messageKey = ref('')
const lastLookup = ref('')
const loadError = ref('')
const syncingLocale = ref(false)
const applyingBackendLocale = ref(false)
const { locale, localeLabel, supportedLocales, t } = useI18n()
const selectedFrontendLocale = ref(locale.value)
let loadSequence = 0
let appLocaleSequence = 0
let backendLocaleSequence = 0

const messagesPreview = computed(() => JSON.stringify(messages.value, null, 2))
const backendLocaleLabel = (locale: string) => localeNames.value[locale] ? `${localeNames.value[locale]} · ${locale}` : locale

const loadAll = async () => {
  const requestId = ++loadSequence
  loading.value = true
  loadError.value = ''
  try {
    const localeData = await i18nClient.locales()
    const messageData = await i18nClient.messages(localeData.current)
    if (requestId !== loadSequence) return
    locales.value = localeData.available
    localeNames.value = localeData.localeNames
    currentLocale.value = localeData.current
    selectedLocale.value = localeData.current
    messages.value = messageData.messages
  } catch (error) {
    if (requestId !== loadSequence) return
    loadError.value = error instanceof Error ? error.message : '后端翻译诊断加载失败'
    console.warn('加载后端翻译诊断失败', error)
  } finally {
    if (requestId === loadSequence) loading.value = false
  }
}

const applyAppLocale = async () => {
  if (syncingLocale.value || !selectedFrontendLocale.value) return
  const requestId = ++appLocaleSequence
  const nextLocale = selectedFrontendLocale.value
  syncingLocale.value = true
  try {
    await setFrontendLocale(nextLocale)
    const backendResult = await i18nClient.setLocale(nextLocale)
    const messageData = await i18nClient.messages(backendResult.locale)
    if (requestId !== appLocaleSequence) return
    currentLocale.value = backendResult.locale
    selectedLocale.value = backendResult.locale
    messages.value = messageData.messages
    ElMessage.success(t('language.changed'))
  } catch {
    if (requestId !== appLocaleSequence) return
    ElMessage.warning(t('common.localOnly'))
  } finally {
    if (requestId === appLocaleSequence) syncingLocale.value = false
  }
}

const applyBackendLocale = async () => {
  if (applyingBackendLocale.value || !selectedLocale.value) return
  const requestId = ++backendLocaleSequence
  const nextLocale = selectedLocale.value
  applyingBackendLocale.value = true
  try {
    const result = await i18nClient.setLocale(nextLocale)
    if (requestId !== backendLocaleSequence) return
    currentLocale.value = result.locale
    ElMessage.success(result.message || t('language.changed'))
    await loadAll()
  } catch (error) {
    if (requestId !== backendLocaleSequence) return
    const message = error instanceof Error ? error.message : '切换后端语言失败'
    loadError.value = message
    ElMessage.error(message)
  } finally {
    if (requestId === backendLocaleSequence) applyingBackendLocale.value = false
  }
}

const lookupMessage = async () => {
  if (!messageKey.value.trim()) return
  try {
    const result = await i18nClient.message(messageKey.value.trim(), selectedLocale.value || undefined)
    lastLookup.value = result.message
  } catch (error) {
    const message = error instanceof Error ? error.message : '查询翻译消息失败'
    lastLookup.value = message
    ElMessage.error(message)
  }
}

const lookupError = async () => {
  if (!messageKey.value.trim()) return
  try {
    const result = await i18nClient.errorMessage(messageKey.value.trim(), selectedLocale.value || undefined)
    lastLookup.value = result.message
  } catch (error) {
    const message = error instanceof Error ? error.message : '查询错误消息失败'
    lastLookup.value = message
    ElMessage.error(message)
  }
}

onMounted(() => {
  void loadAll()
})

watch(locale, (value) => {
  selectedFrontendLocale.value = value
})
</script>

<style scoped>
.i18n-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.card-header,
.language-row,
.button-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.card-header {
  justify-content: space-between;
}

.language-row,
.button-row {
  flex-wrap: wrap;
}

.locale-select,
.key-input {
  max-width: 320px;
}

.messages-preview {
  max-height: 360px;
  overflow: auto;
  padding: 12px;
  border: 1px solid var(--yui-border);
  border-radius: var(--yui-radius-card);
  background: var(--yui-surface-muted);
  color: var(--yui-text);
  font-size: 12px;
  line-height: 1.55;
}

@media (max-width: 760px) {
  .card-header,
  .language-row {
    align-items: stretch;
    flex-direction: column;
  }

  .locale-select,
  .key-input {
    max-width: none;
    width: 100%;
  }
}
</style>
